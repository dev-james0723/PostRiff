"""SiteAgentService: one Rafii across the app, on the existing conversation, run, event and approval machinery (§4, §5.3).

A turn from the side panel is an ordinary conversation message and an ordinary run (`pr_agent_runs`, idempotency key
`site:<key>`), with safe events in `pr_agent_events` and the answer on the assistant message (`body.siteAgent`). No
new table: the run's model, reasoning, context digest, policy epoch, artifact and usage columns already hold what the
spec's turn and trace need.

Pipeline (§5.3): authenticate and bind the workspace → validate the page context → classify → select procedures →
read with typed tools inside one workspace transaction → compose a grounded answer → persist events. Writing
requests (a draft now, a post at a time, an automation, a standing writing instruction) are handed to
`IdeasService.turn` unchanged, in the same conversation. Automation changes become proposals applied through the
workspace command path. When a model may phrase the answer, the turn returns `needsCompose` and the browser calls
`compose`, which reserves the cost, calls the chosen writer outside the transaction, validates the answer and settles.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from postriff_alpha.domain import AlphaError, clean, uid

from .. import automation_edit, intent as writing_intent, request_model
from ..agent_runtime import safe_event
from ..contracts import digest
from ..permissions import Membership, require
from . import classifier, compose as composer, contracts, knowledge, policy, procedures, prompts, proposals, references, routes, tools

KEY_PREFIX = "site:"
GROUNDED_MODEL = "site-agent:grounded"
MAX_BLOCK_EVENTS = 10
STALE_COMPOSE_SECONDS = 180
CLAIMED_STALE_SECONDS = 900
WITHHELD = ["passwords, tokens and keys", "other workspaces", "files and media contents"]
ENTITY_READERS = {"job": "job.get", "review": "job.get", "draft": "draft.get"}


def policy_epoch() -> str:
    kb = knowledge.snapshot()
    return digest({"prompt": prompts.EPOCH, "tools": tools.RELEASE, "knowledge": kb["id"], "routes": routes.manifest()["version"]})


class SiteAgentService:
    def __init__(self, service):
        self.service = service
        self.ideas = service.ideas
        self.repository = service.repository
        self.clock = service.clock
        # Tests inject a structured call here (the same shape as request_model.call_for's answer).
        self.model = None

    # --- helpers --------------------------------------------------------------------------------------------------------
    def _member(self, row):
        return self.ideas._member(row)

    def _run(self, cur, workspace_id, run_id, lock=False):
        cur.execute("SELECT status,conversation_id::text,model,reasoning,artifact,usage,actor::text,idempotency_key,extract(epoch from created_at) FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s" + (" FOR UPDATE" if lock else ""),
                    (run_id, workspace_id))
        row = cur.fetchone()
        if not row or not str(row[7]).startswith(KEY_PREFIX):
            raise AlphaError("Run unavailable.", 404)
        return {"status": row[0], "conversationId": row[1], "model": row[2], "reasoning": row[3], "artifact": row[4] or {}, "usage": row[5] or {},
                "actor": row[6], "key": row[7], "createdAt": float(row[8])}

    def _message_for_run(self, cur, workspace_id, conversation_id, run_id):
        cur.execute("SELECT id::text,body FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND run_id::text=%s AND role='assistant' ORDER BY seq DESC LIMIT 1",
                    (conversation_id, workspace_id, run_id))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)

    def _response(self, cur, workspace_id, run_id, cursor=0):
        run = self._run(cur, workspace_id, run_id)
        events = self.ideas._events_for(cur, workspace_id, run_id, cursor)
        message_id, body = self._message_for_run(cur, workspace_id, run["conversationId"], run_id)
        needs = run["status"] == "running" and bool(run["artifact"].get("pending")) and not run["usage"].get("composeClaimedAt")
        return {"conversationId": run["conversationId"], "runId": run_id, "status": run["status"], "needsCompose": needs,
                "events": events["events"], "cursor": events["cursor"], "messageId": message_id, "message": body}

    def _history(self, cur, workspace_id, conversation_id):
        cur.execute("SELECT role,body FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s ORDER BY seq DESC LIMIT 6", (conversation_id, workspace_id))
        rows = list(reversed(cur.fetchall()))
        return [{"role": role, "text": (body or {}).get("text") or ""} for role, body in rows if isinstance(body, dict) and (body.get("text") or "").strip()]

    def _emit(self, cur, workspace_id, run_id, event_type, **body):
        self.ideas._insert_event(cur, workspace_id, run_id, safe_event(event_type, **body))

    def _runtime(self, model_id):
        """(runtime, note) — note explains why the chosen writer cannot phrase answers now; never another model."""
        if not model_id:
            return None, None
        try:
            return self.ideas._select_runtime(model_id), None
        except AlphaError as error:
            return None, {"code": "writer_unavailable", "message": f"The writer you chose isn't available right now ({error}). This answer comes from Rafii's help and your workspace."}

    def _paid_route(self, route):
        try:
            return self.ideas._select_runtime(route).cost_class == "paid"
        except AlphaError:
            return True

    # --- turn -----------------------------------------------------------------------------------------------------------
    def turn(self, workspace_id, token, payload):
        if not isinstance(payload, dict):
            raise AlphaError("Send a structured turn.", 400)
        text = clean(payload.get("message", ""), contracts.MAX_MESSAGE)
        if not text:
            raise AlphaError("Ask Rafii something.", 400)
        key = clean(payload.get("idempotencyKey", ""), 100) or uid()
        run_key = KEY_PREFIX + key
        page = contracts.page_context(payload.get("pageContext"))
        model_id = payload.get("model") if isinstance(payload.get("model"), str) and payload.get("model") else None
        zone = writing_intent.safe_zone(payload.get("timeZone"))
        now = self.clock()
        delegate = reading = focus = after_turn = None
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = self._member(row)
            require(member, "read")
            cur.execute("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, run_key))
            prior = cur.fetchone()
            if prior:
                return self._response(cur, workspace_id, prior[0])
            conversation_id = payload.get("conversationId")
            if conversation_id:
                if not isinstance(conversation_id, str):
                    raise AlphaError("Conversation unavailable.", 404)
                self.ideas._conversation(cur, workspace_id, conversation_id)
            else:
                title = clean(text.splitlines()[0][:80], 200) or "Question for Rafii"
                cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text", (workspace_id, principal, title))
                conversation_id = cur.fetchone()[0]
            state = self.ideas._state(row)
            names = [task.get("name") or "Automation" for task in automation_edit.live_tasks(state)]
            continuing = bool(payload.get("conversationId"))
            history = self._recent_refs(cur, workspace_id, conversation_id) if continuing else []
            pending = self._pending_choice(cur, workspace_id, conversation_id) if continuing else None
            chosen = self._choose(pending, text)
            shown, request = text, text
            if chosen is not None:
                # "the second one" answers Rafii's own question: the request it asked about runs on the chosen item.
                request = f"{pending['request']} — {text}"
                resolved = {"entity": chosen, "source": "conversation", "candidates": [], "ambiguous": False}
            else:
                resolved = references.resolve(text, page.get("selectedEntity"), history)
                if resolved["entity"] is None and not resolved["ambiguous"]:
                    resolved = self._day_reference(state, member, principal, workspace_id, text, now, zone) or resolved
            text = request
            focus = resolved["entity"]
            entity = focus or page.get("selectedEntity") or {}
            in_context = entity.get("type") == "automation" or page.get("routeId") == "automations"
            if continuing and member.allows("edit") and self._answers_pending_question(cur, workspace_id, conversation_id, state, text):
                # An answer to Rafii's own automation question ("Publish automatically") goes back to the automation it asked about.
                delegate = {"conversationId": conversation_id, "kind": "answer"}
            else:
                reading = classifier.classify(text, page, automation_names=names, in_automation_context=in_context, focus=focus)
                reading["reference"] = {"source": resolved["source"], "ambiguous": resolved["ambiguous"], "candidates": resolved["candidates"]}
                if resolved["ambiguous"] and not focus and (reading["intent"] in ("schedule", "edit") or reading.get("operate") == "transform"):
                    # Several items fit "it" / "Thursday's post": ask instead of guessing a target for a change.
                    reading = {**reading, "intent": "clarify", "clarify": {"ask": "Which one do you mean?", "candidates": resolved["candidates"]}}
                if reading["intent"] == "compound":
                    compound = self._compound_setup(state, member, principal, workspace_id, text, now, zone, reading, focus, history, conversation_id)
                    reading = {**reading, "compound": compound}
                    after_turn = "compound"
                    if compound.get("delegate"):
                        delegate = {"conversationId": conversation_id, "kind": "compound", **compound["delegate"]}
                if reading["intent"] in ("campaign_link", "campaign_unlink"):
                    linking = self._link_setup(state, member, text, focus, history, reading)
                    reading = {**reading, **linking.get("reading", {}), "link": linking}
                    if linking.get("execute"):
                        after_turn = "link"
                if reading["intent"] == "operate":
                    if not member.allows("edit"):
                        reading = {**reading, "intent": "forbidden", "risk": "workspace_mutation", "forbidden": {"category": "role", "routeId": "roles"}}
                    elif reading["operate"] in ("transform", "campaign_post"):
                        prepared = self._material(state, reading, focus, text)
                        if "ask" in prepared:
                            reading = {**reading, "intent": "clarify", "clarify": prepared}
                        else:
                            delegate = {"conversationId": conversation_id, "kind": reading["operate"], **prepared}
                    else:
                        delegate = {"conversationId": conversation_id, "kind": reading["operate"]}
            if delegate is None and after_turn is None:
                return self._guide(cur, workspace_id, principal, member, state, conversation_id, text, page, reading, model_id, zone, now, run_key, names, focus, shown=shown)
        if after_turn == "link":
            # The campaign's own action, as the person; the edit permission is checked again when it runs.
            reading["link"]["result"] = self._run_link(workspace_id, token, reading["link"])
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                return self._guide(cur, workspace_id, principal, self._member(row), self.ideas._state(row), conversation_id, text, page, reading, model_id, zone, now,
                                   run_key, names, focus, shown=shown)
        if after_turn == "compound":
            from . import compound as flow
            plan = reading["compound"]
            if delegate is not None:
                # The writing step goes through the writing pipeline; its message is the person's message in this conversation.
                delegated = self._delegate(workspace_id, token, delegate, delegate.get("text") or text, key, model_id, zone, payload)
                plan["runId"] = delegated.get("runId")
            plan = flow.advance(self, workspace_id, token, plan, principal=principal, now=now, zone=zone, text=text)
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                return self._guide(cur, workspace_id, principal, self._member(row), self.ideas._state(row), conversation_id, text, page, {**reading, "compound": plan},
                                   model_id, zone, now, run_key, names, focus, append_user=delegate is None, shown=shown)
        return self._delegate(workspace_id, token, delegate, text, key, model_id, zone, payload)

    _DAY_ITEM = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)'?s\s+(post|draft)\b"
                           r"|\bthe\s+(post|draft)\s+(?:scheduled|planned|going\s+out|for)\s+(?:on\s+|for\s+)?((?:next\s+|this\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow))\b", re.I)

    def _day_reference(self, state, member, principal, workspace_id, text, now, zone):
        """"Thursday's post" / "the draft scheduled next Tuesday": the one post on that day, or the choices when there are several."""
        from . import reads, timeframe
        match = self._DAY_ITEM.search(text)
        if not match:
            return None
        day_words = match.group(1) or match.group(4)
        frame = timeframe.parse(day_words, now, zone)
        if frame is None:
            return None
        ctx = tools.Context(state=state, membership=member, principal=principal, workspace_id=workspace_id, now=now, zone=zone)
        entries = [e for e in reads._entries(ctx, frame["start"], frame["end"], zone) if e["kind"] in ("job", "review")]
        refs = [{"type": e["kind"], "id": e["id"], "title": f"{e['platform']} post {e['when']}"} for e in entries]
        if len(refs) == 1:
            return {"entity": refs[0], "source": "calendar", "candidates": [], "ambiguous": False}
        return {"entity": None, "source": None, "candidates": refs[:5], "ambiguous": bool(refs)}

    _CHOICE = re.compile(r"^\s*(?:(?:the|number|option|no\.?)\s+)?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|[1-5])(?:\s+(?:one|option|post|draft|item))?\s*[.!。]?\s*$"
                         r"|^\s*(第[一二三四五]|最後)(?:個|篇|項)?\s*$", re.I)
    _CHOICE_INDEX = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1, "third": 2, "3rd": 2, "3": 2, "fourth": 3, "4th": 3, "4": 3,
                     "fifth": 4, "5th": 4, "5": 4, "last": -1, "第一": 0, "第二": 1, "第三": 2, "第四": 3, "第五": 4, "最後": -1}

    def _pending_choice(self, cur, workspace_id, conversation_id):
        """The question Rafii asked in its last answer, with the request it was about and the options it offered."""
        cur.execute("SELECT body->'siteAgent'->'pending' FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND role='assistant' ORDER BY seq DESC LIMIT 1",
                    (conversation_id, workspace_id))
        row = cur.fetchone()
        pending = row[0] if row else None
        if isinstance(pending, dict) and isinstance(pending.get("request"), str) and isinstance(pending.get("candidates"), list) and pending["candidates"]:
            return pending
        return None

    def _choose(self, pending, text):
        """The option a short reply picks: by position ("the second one", "2") or by words only one option has ("the 16:30 one")."""
        if not pending or len(text) > 60:
            return None
        options = [c for c in pending["candidates"] if isinstance(c, dict) and c.get("type") and c.get("id")]
        match = self._CHOICE.search(text)
        if match:
            index = self._CHOICE_INDEX.get((match.group(1) or match.group(2) or "").lower())
            return options[index] if index is not None and -len(options) <= index < len(options) else None
        words = set(re.findall(r"\d{1,2}:\d{2}|[a-z0-9]{3,}|[㐀-鿿]{2,}", text.lower())) - {"the", "one", "that", "this", "post", "draft", "please"}
        scored = [(len(words & set(re.findall(r"\d{1,2}:\d{2}|[a-z0-9]{3,}|[㐀-鿿]{2,}", str(c.get("title") or "").lower()))), c) for c in options]
        best = max((score for score, _ in scored), default=0)
        winners = [c for score, c in scored if score == best]
        return winners[0] if best and len(winners) == 1 else None

    def _recent_refs(self, cur, workspace_id, conversation_id):
        """The items the last few answers named, newest answer first (references.resolve)."""
        cur.execute("SELECT body->'siteAgent'->'refs' FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND role='assistant' AND body ? 'siteAgent' ORDER BY seq DESC LIMIT 4",
                    (conversation_id, workspace_id))
        return [refs for (refs,) in cur.fetchall() if isinstance(refs, list)]

    def _answers_pending_question(self, cur, workspace_id, conversation_id, state, text):
        from .. import automation_plan
        cur.execute("SELECT body FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND role='assistant' ORDER BY seq DESC LIMIT 1", (conversation_id, workspace_id))
        row = cur.fetchone()
        pending = ((row[0] or {}).get("automation") or {}).get("pending") if row and isinstance(row[0], dict) else None
        if not isinstance(pending, dict) or len(text) > 200:
            return False
        if pending.get("question") == "policy":
            return automation_plan.answer_policy(text) is not None
        task = next((t for t in automation_edit.live_tasks(state) if t.get("id") == pending.get("taskId")), None)
        return bool(task) and automation_plan.answer_review_time(text, task.get("schedule") or {}) is not None

    def _material(self, state, reading, focus, text):
        """What the writer works from for a rework of a draft or a post for a campaign; or a question when it is unclear."""
        from .. import campaigns
        if reading["operate"] == "campaign_post":
            root = campaigns._root(state)
            live = [c for c in root["campaigns"] if c.get("status") != "cancelled"]
            campaign = None
            if focus and focus.get("type") in ("campaign", "automation"):
                task = next((t for t in root["recurringTasks"] if t.get("id") == focus["id"]), None)
                campaign = next((c for c in live if c["id"] in (focus["id"], (task or {}).get("campaignId"))), None)
            if campaign is None and len(live) == 1:
                campaign = live[0]
            if campaign is None:
                return {"ask": "Which campaign should the post be for?", "candidates": [{"type": "campaign", "id": c["id"], "title": (c.get("goal") or "Campaign")[:80]} for c in live[:5]]}
            facts = "; ".join(f"{k}: {v}" for k, v in (campaign.get("facts") or {}).items())
            material = f"Campaign goal: {campaign.get('goal')}\nAudience: {campaign.get('audience')}" + (f"\nFacts: {facts}" if facts else "")
            return {"material": material, "materialRef": {"type": "campaign", "id": campaign["id"], "title": (campaign.get("goal") or "")[:80]}}
        variants = [v for v in state.get("variants", []) if isinstance(v, dict)]
        draft = None
        if focus and focus.get("type") == "draft":
            draft = next((v for v in variants if v.get("id") == focus["id"]), None)
        elif focus and focus.get("type") in ("job", "review"):
            items = (state.get("phase2") or {}).get("jobs", []) + (state.get("phase2") or {}).get("reviews", [])
            item = next((i for i in items if i.get("id") == focus["id"]), None)
            draft = next((v for v in variants if v.get("id") == ((item or {}).get("manifest") or {}).get("variantId")), None)
        if draft is None:
            recent = [v for v in reversed(variants) if not v.get("rejected")][:5]
            if not recent:
                return {"ask": "There's no draft to work from yet. Write one first, or tell me what to write.", "candidates": []}
            return {"ask": "Which draft should I work from?", "candidates": [{"type": "draft", "id": v["id"], "title": f"{v.get('platform')} draft: {' '.join((v.get('text') or '').split())[:60]}"} for v in recent]}
        named = [p for p in reading["entities"]["platforms"] if p != draft.get("platform")]
        if named:
            destinations = [{"platform": platform, "language": draft.get("language") or "en"} for platform in named]
        else:
            destinations = [{"platform": draft.get("platform"), "language": draft.get("language") or "en", **({"channelId": draft["channelId"]} if draft.get("channelId") else {})}]
        wants_voice = re.search(r"sounds?\s+(?:more\s+)?like\s+me|\bmy\s+(?:own\s+)?(?:usual\s+)?voice\b|我嘅語氣|似我", text, re.I)
        samples = any(s.get("kind") == "voice_sample" and s.get("active") and s.get("selected") for s in state.get("sources", []) if isinstance(s, dict))
        prepared = {"material": draft.get("text") or "", "materialRef": {"type": "draft", "id": draft["id"], "title": f"{draft.get('platform')} draft"}, "destinations": destinations}
        if wants_voice and samples:
            prepared["voiceMode"] = "personalized"
        return prepared

    def _delegate(self, workspace_id, token, delegate, text, key, model_id, zone, payload):
        """Writing requests go to the writing pipeline itself (IdeasService.turn), in the same conversation."""
        request = {"text": text, "idempotencyKey": key, "timeZone": zone}
        if model_id:
            request["model"] = model_id
        for name in ("reasoning", "destinations", "language", "voiceMode", "voiceSourceIds", "sourceIds"):
            if payload.get(name) is not None:
                request[name] = payload[name]
        # A rework of a draft or a campaign post: the writer reads the material; the destinations are the draft's own
        # account (or the platforms the message names), never channels mentioned inside the material.
        for name in ("material", "materialRef", "destinations", "voiceMode"):
            if delegate.get(name) is not None:
                request[name] = delegate[name]
        result = self.ideas.turn(workspace_id, token, delegate["conversationId"], request)
        return {"conversationId": delegate["conversationId"], "delegated": True, "kind": delegate["kind"],
                "status": result.get("status"), "runId": result.get("runId"), "result": result}

    def _guide(self, cur, workspace_id, principal, member, state, conversation_id, text, page, reading, model_id, zone, now, run_key, names, focus=None, append_user=True, shown=None):
        if reading["intent"] == "forbidden" and reading["forbidden"]["category"] == "role":
            plan = {"procedures": ["policy_block"], "tools": [("route.describe", {"routeId": "roles"})], "navigate": ("roles", {})}
        elif reading["intent"] in ("clarify", "schedule"):
            plan = {"procedures": ["clarify" if reading["intent"] == "clarify" else "schedule_draft"], "tools": [], "navigate": None}
        elif reading["intent"] == "compound":
            plan = {"procedures": ["compound_request"], "tools": [], "navigate": None}
        elif reading["intent"] in ("campaign_link", "campaign_unlink"):
            plan = {"procedures": ["campaign_link"], "tools": [], "navigate": None}
        else:
            plan = procedures.select(reading, page, text, automation_count=len(names), now=now, zone=zone)
        ctx = tools.Context(state=state, membership=member, principal=principal, workspace_id=workspace_id, cur=cur, service=self.service, now=now,
                            page=page, model_id=model_id, zone=zone)
        records, results = [], {}
        for tool_id, args in plan["tools"][: tools.MAX_TOOLS_PER_TURN]:
            record, result = tools.run(tool_id, args, ctx)
            records.append({**record, "args": sorted(args)})
            results[tool_id] = result
        entity = page.get("selectedEntity") or {}
        reader = ENTITY_READERS.get(entity.get("type"))
        if reader and any(r["id"] == reader and r.get("code") == "not_found" for r in records):
            # The browser's selection is only a hint: an item this workspace doesn't hold is dropped, never described.
            page = {**page, "selectedEntity": None, "issues": sorted(set(page.get("issues", [])) | {"entity_not_found"})}
        model_tier = prompts.tier(reading, plan["tools"], text)
        context = {"page": contracts.page_summary(page), "intent": reading["intent"], "risk": reading["risk"], "entities": reading["entities"],
                   "tools": [(tool_id, sorted(args.items())) for tool_id, args in plan["tools"]]}
        cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key) VALUES(%s,%s,%s,'running',%s,%s,%s,%s,%s) RETURNING id::text",
                    (conversation_id, workspace_id, principal, model_id or GROUNDED_MODEL, "standard" if model_tier == "strong" else "quick", digest(context), policy_epoch(), run_key))
        run_id = cur.fetchone()[0]
        if append_user:
            self.ideas._append_message(cur, workspace_id, conversation_id, "user", {"text": shown or text, "siteAgent": {"role": "question", "page": contracts.page_summary(page), "runId": run_id}})
        self._emit(cur, workspace_id, run_id, "run.started", agent="site", model=model_id or GROUNDED_MODEL, reasoning="standard" if model_tier == "strong" else "quick", contextDigest=digest(context))
        self._emit(cur, workspace_id, run_id, "progress.updated", stage="classified", intent=reading["intent"], language=reading["language"], risk=reading["risk"], procedures=plan["procedures"])
        self._emit(cur, workspace_id, run_id, "progress.updated", stage="context", route=page.get("routeId"), title=page.get("title"),
                   entity=(page.get("selectedEntity") or {}).get("type"), stale=bool(page.get("stale")))
        for record in records:
            self._emit(cur, workspace_id, run_id, "progress.updated", stage="tool", tool=record["id"], label=record["label"], effect=record["effect"],
                       status=record["status"], latencyMs=record["latencyMs"])
        if "help.search" in results and results["help.search"].get("data"):
            data = results["help.search"]["data"]
            self._emit(cur, workspace_id, run_id, "progress.updated", stage="retrieval", snapshot=data["snapshot"], retrieval=data["retrieval"],
                       passages=len(data["passages"]), sufficient=data["sufficient"])
        answer = composer.compose(reading, page, plan, results, language=reading["language"], trace_id=run_id, retrieved_at=contracts.iso(now), text=text)
        if "entity_not_found" in page.get("issues", []):
            answer["blocks"].insert(0, contracts.warning("The item selected on this page isn't in this workspace, so I answered without it.", "entity_not_found"))
        proposal_list = []
        if reading["intent"] == "edit":
            answer, proposal_list = self._proposal_answer(state, text, principal, member, now, zone, page, answer, reading["language"])
        elif reading["intent"] == "schedule":
            answer, proposal_list = self._schedule_answer(state, text, principal, member, now, zone, focus, reading, answer)
        elif reading["intent"] == "clarify":
            answer = self._clarify_answer(reading["clarify"], answer, request=text)
        elif reading["intent"] == "compound":
            answer, proposal_list = self._compound_answer(reading["compound"], answer)
        elif reading["intent"] in ("campaign_link", "campaign_unlink"):
            answer = self._link_answer(reading["link"], answer, text)
        elif (reading.get("reference") or {}).get("ambiguous") and reading["intent"] in ("status",) and not focus:
            answer = self._clarify_answer({"ask": "Which one do you mean?", "candidates": reading["reference"]["candidates"]}, answer)
        for proposal in proposal_list:
            self._emit(cur, workspace_id, run_id, "action.proposed", action=proposal["type"], proposalId=proposal["id"], status="proposed")
        runtime, note = self._runtime(model_id)
        call = request_model.call_for(runtime, self.model, model_tier) if runtime is not None else None
        wants_model = reading["intent"] not in ("forbidden", "greeting", "edit", "schedule", "clarify", "compound", "campaign_link", "campaign_unlink") and member.allows("edit") and call is not None
        read_labels = [r["label"] for r in records if r["status"] == "verified" and r["effect"] == "read"]
        withheld = list(WITHHELD) + ([] if "memory.summary" in results else ["private memory"])
        summary = {"route": page.get("title"), "entity": page.get("selectedEntity"), "read": read_labels, "withheld": withheld, "stale": bool(page.get("stale"))}
        trace = {"intent": reading["intent"], "risk": reading["risk"], "language": reading["language"], "procedures": plan["procedures"],
                 "tools": [{k: r.get(k) for k in ("id", "effect", "status", "latencyMs", "code")} for r in records],
                 "knowledge": knowledge.snapshot()["id"], "retrievalRefs": [f"{c['documentId']}#{c['section']}" for c in answer["citations"]],
                 "grounded": answer["grounding"]["sufficient"], "tier": model_tier, "promptVersion": prompts.PROMPT_VERSION, "toolRelease": tools.RELEASE}
        if note:
            answer["blocks"].insert(0, contracts.warning(note["message"], note["code"]))
            trace["fallback"] = note["code"]
        if wants_model:
            # Where the words actually go decides what may be sent: the person's own CLI, or a cloud gateway.
            provider_class = "local" if getattr(call, "local", False) else "cloud"
            draft = (results.get("draft.get") or {}).get("data") if (results.get("draft.get") or {}).get("ok") else None
            pending = {"model": model_id, "tier": model_tier, "language": reading["language"], "intent": reading["intent"],
                       "grounding": bool(reading.get("requiresGrounding", True)), "providerClass": provider_class, "page": contracts.page_summary(page),
                       "member": member.summary(), "procedures": plan["procedures"], "message": text, "history": self._history(cur, workspace_id, conversation_id)[:-1],
                       "passages": ((results.get("help.search") or {}).get("data") or {}).get("passages", []) if (results.get("help.search") or {}).get("ok") else [],
                       "facts": answer["facts"], "actions": self._actions(answer, plan, page), "labels": self._labels(state),
                       "knownIds": self._known_ids(page, results, state), "draftText": draft.get("text") if draft and provider_class == "local" else None,
                       "grounded": answer, "summary": summary, "trace": trace}
            cur.execute("UPDATE public.pr_agent_runs SET artifact=%s::jsonb WHERE id::text=%s", (json.dumps({"pending": pending}, ensure_ascii=False), run_id))
            self._emit(cur, workspace_id, run_id, "progress.updated", stage="composing", tier=model_tier)
            body = {"text": "", "pending": True, "runId": run_id, "siteAgent": {"version": contracts.VERSION, "runId": run_id, "status": "running", "intent": reading["intent"],
                                                                                "language": reading["language"], "context": summary, "blocks": [], "proposals": []}}
            self.ideas._append_message(cur, workspace_id, conversation_id, "assistant", body, run_id)
            return self._response(cur, workspace_id, run_id)
        composed_by = "grounded"
        if reading["intent"] not in ("forbidden", "greeting", "edit", "schedule", "clarify") and not note and runtime is not None and not member.allows("edit"):
            answer["blocks"].insert(0, contracts.warning("Answers from a writer model need edit access, so this one comes from Rafii's help and your workspace.", "role_grounded"))
        self._finalize(cur, workspace_id, conversation_id, run_id, answer, summary, trace, reading, proposal_list, composed_by=composed_by, model_id=model_id,
                       follow_ups=[], usage={"provenance": "grounded", "modelRequests": 0})
        return self._response(cur, workspace_id, run_id)

    def _proposal_answer(self, state, text, principal, member, now, zone, page, answer, language):
        entity = page.get("selectedEntity") or {}
        conversation_task = entity.get("id") if entity.get("type") == "automation" else None
        providers = getattr(getattr(self.service, "oauth", None), "providers", None) or {}
        task_route = None
        target, _ = automation_edit.resolve(state, None, conversation_task, text)
        if target is not None:
            task_route = target.get("route")
        built = proposals.build(state, text, actor=principal, now=now, owner=member.allows("owner"), paid=self._paid_route(task_route) if task_route else False,
                                zone=zone, conversation_task_id=conversation_task, providers=providers, live=bool(getattr(self.service, "publishing_live", False)))
        blocks = []
        if "proposal" in built:
            proposal = built["proposal"]
            lead = "Here's the change I'd make. Nothing changes until you apply it." if language != "zh-Hant" else "以下係我建議嘅改動。你按「套用」之前，乜都唔會改。"
            blocks.append(contracts.text(lead))
            blocks.append({"type": "proposal_diff", "proposal": proposals.view(proposal, now)})
            nav = routes.href("automations", query={"edit": proposal["taskId"]})
            if nav:
                blocks.append(contracts.navigation("Open the automation", nav, "automations"))
            return {**answer, "blocks": blocks, "text": lead, "grounding": {"required": True, "sufficient": True, "missing": []}}, [proposal]
        if "ask" in built:
            blocks.append(contracts.question(built["ask"], built.get("candidates") or []))
            return {**answer, "blocks": blocks, "text": built["ask"], "grounding": {"required": False, "sufficient": True, "missing": []}}, []
        blocks.append(contracts.text(built["refuse"]))
        if built.get("taskId"):
            blocks.append(contracts.navigation("Open the automation", routes.href("automations", query={"edit": built["taskId"]}), "automations"))
        else:
            blocks.append(contracts.navigation("Open Automations", routes.href("automations"), "automations"))
        return {**answer, "blocks": blocks, "text": built["refuse"], "grounding": {"required": False, "sufficient": True, "missing": []}}, []

    _CLAUSE = re.compile(r",\s*|;\s*|\s+and\s+then\s+|\s+then\s+|\s+and\s+(?=(?:add|put|link|schedule|tell|find|create|write|draft|make|shorten|rewrite|post)\b)", re.I)
    _PLURAL = re.compile(r"\b(?:these|those|both|all\s+(?:of\s+)?(?:these|those|them))\b(?:\s+(two|three|four|five|\d))?", re.I)
    _COUNT = {"two": 2, "three": 3, "four": 4, "five": 5}

    def _instruction(self, text, pattern):
        """The clause of a compound message that is the writing request ("shorten this draft"), without the other steps."""
        for clause in self._CLAUSE.split(text or ""):
            if clause and pattern.search(clause):
                return clause.strip().rstrip(".") or text
        return text

    def _focus_draft(self, state, focus):
        variants = [v for v in state.get("variants", []) if isinstance(v, dict)]
        if focus and focus.get("type") == "draft":
            return next((v for v in variants if v.get("id") == focus["id"]), None)
        if focus and focus.get("type") in ("job", "review"):
            p2 = state.get("phase2") or {}
            item = next((i for i in p2.get("jobs", []) + p2.get("reviews", []) if i.get("id") == focus["id"]), None)
            return next((v for v in variants if v.get("id") == ((item or {}).get("manifest") or {}).get("variantId")), None)
        return None

    def _compound_setup(self, state, member, principal, workspace_id, text, now, zone, reading, focus, history, conversation_id):
        """Resolve each step of a compound request without guessing; the find and gap steps are reads done now."""
        from . import compound as flow, reads
        steps = reading["steps"]
        ctx = tools.Context(state=state, membership=member, principal=principal, workspace_id=workspace_id, now=now, zone=zone)
        plan = {"steps": steps, "status": {}, "conversationId": conversation_id, "proposals": []}
        wants_campaign = bool(re.search(r"\bcampaigns?\b|活動", text, re.I)) or "link" in steps or "gaps" in steps
        campaign = None
        if wants_campaign:
            found = flow.resolve_campaign(state, text, focus, history)
            campaign = found.get("campaign")
            if campaign:
                detail = reads._campaign_view(ctx, campaign, detail=True)
                plan.update(campaignId=campaign["id"], campaignTitle=(campaign.get("goal") or "")[:80])
                if "find" in steps:
                    plan["status"]["find"] = flow.status("done", f"“{plan['campaignTitle']}”, covering {', '.join(detail['platforms']) or 'no platform yet'}", detail.get("href"))
                if "gaps" in steps:
                    derived = detail["derived"]
                    gaps = ([f"missing facts: {', '.join(detail['missingFacts'])}"] if detail["missingFacts"] else []) + \
                           ([f"connected but not covered: {', '.join(derived['platformsNotCovered']['items'])}"] if derived["platformsNotCovered"]["items"] else []) + \
                           (["no automation is set to run next"] if derived["noUpcomingRun"]["value"] else [])
                    plan["status"]["gaps"] = flow.status("done", ("; ".join(gaps) if gaps else "nothing stored is missing") + " (derived from the campaign's records)", detail.get("href"))
                    plan["gaps"] = gaps
            else:
                problem = (f"no campaign matches “{found['none']}”" if found.get("none")
                           else "more than one campaign could be meant: " + "; ".join(c["title"] for c in found.get("candidates") or []))
                plan["campaignProblem"] = problem
                if "find" in steps:
                    plan["status"]["find"] = flow.status("needs_you", problem)
                if "gaps" in steps:
                    plan["status"]["gaps"] = flow.status("not_done", "no single campaign was found")
        writing = "revise" if "revise" in steps else ("create" if "create" in steps else None)
        delegate = None
        if writing and not member.allows("edit"):
            plan["status"][writing] = flow.status("needs_you", "your role can't create or change drafts")
        elif writing == "revise":
            draft = self._focus_draft(state, focus)
            if draft is None:
                plan["status"]["revise"] = flow.status("needs_you", "select the draft to revise (or say which one)")
            else:
                plan["focusDraftId"] = draft["id"]
                delegate = {"text": self._instruction(text, classifier.COMPOUND_REVISE), "material": draft.get("text") or "",
                            "materialRef": {"type": "draft", "id": draft["id"], "title": f"{draft.get('platform')} draft"},
                            "destinations": [{"platform": draft.get("platform"), "language": draft.get("language") or "en", **({"channelId": draft["channelId"]} if draft.get("channelId") else {})}]}
        elif writing == "create":
            if wants_campaign and campaign is None:
                plan["status"]["create"] = flow.status("needs_you", "I need to know which campaign first")
            else:
                material = ""
                if campaign:
                    facts = "; ".join(f"{k}: {v}" for k, v in (campaign.get("facts") or {}).items())
                    material = (f"Campaign goal: {campaign.get('goal')}\nAudience: {campaign.get('audience')}" + (f"\nFacts: {facts}" if facts else "")
                                + (f"\nWhat the campaign is missing: {'; '.join(plan.get('gaps') or [])}" if plan.get("gaps") else ""))
                platforms = reading["entities"]["platforms"]
                delegate = {"text": self._instruction(text, classifier.COMPOUND_CREATE), "material": material or None,
                            "materialRef": {"type": "campaign", "id": campaign["id"], "title": (campaign.get("goal") or "")[:80]} if campaign else None,
                            "destinations": [{"platform": p, "language": "en"} for p in platforms] or None}
                samples = any(x.get("kind") == "voice_sample" and x.get("active") and x.get("selected") for x in state.get("sources", []) if isinstance(x, dict))
                if re.search(r"\bmy\s+(?:own\s+)?(?:usual\s+)?voice\b|sounds?\s+like\s+me", text, re.I) and samples:
                    delegate["voiceMode"] = "personalized"
                plan["linkImplied"] = bool(campaign)
        elif "link" in steps or "schedule" in steps:
            draft = self._focus_draft(state, focus)
            if draft is not None:
                plan["focusDraftId"] = draft["id"]
                plan["drafts"] = [{"id": draft["id"], "update": False}]
            else:
                for step in ("link", "schedule"):
                    if step in steps:
                        plan["status"][step] = flow.status("needs_you", "select the draft first (or say which one)")
                plan["done"] = [step for step in ("link", "schedule") if step in steps]
        if "link" in steps and not member.allows("edit"):
            plan["status"]["link"] = flow.status("needs_you", "your role can't change campaigns")
            plan.setdefault("done", []).append("link")
        if "schedule" in steps and not member.allows("approve"):
            plan["status"]["schedule"] = flow.status("needs_you", "preparing a post for approval needs the approve permission")
            plan.setdefault("done", []).append("schedule")
        plan["delegate"] = delegate
        return plan

    def _compound_answer(self, compound, answer):
        """One line per step with its real state: done, waiting for your approval, running, needs you, not done, failed."""
        from . import compound as flow
        from .compose_reads import result_list
        words = {"done": "Done", "waiting": "Waiting for your approval", "running": "Running", "needs_you": "Needs you", "not_done": "Not done", "failed": "Failed"}
        order = [step for step in ("find", "gaps", "revise", "create", "save", "link", "schedule")
                 if step in compound["status"] or step in compound["steps"] or (step == "link" and compound.get("linkImplied"))
                 or (step == "save" and ("revise" in compound["steps"] or "create" in compound["steps"]))]
        items = []
        for step in order:
            st = compound["status"].get(step) or (flow.status("running", "after the writer finishes") if compound.get("pending") else flow.status("not_done", "not reached"))
            items.append({"kind": st["state"], "title": f"{flow.STEP_LABELS[step]} — {st['detail']}", "excerpt": None, "meta": words[st["state"]], "href": st.get("href")})
        count = lambda state: sum(1 for i in items if i["kind"] == state)  # noqa: E731
        lead = f"{count('done')} of {len(items)} steps are done."
        if count("waiting"):
            lead += " Scheduling is prepared as a proposal: nothing is scheduled until you apply it, and the post still needs approval."
        if count("running") or compound.get("pending"):
            lead += " The writer is still working; the remaining steps run when it finishes."
        if count("needs_you") or count("failed"):
            lead += " Some steps need you; each says why."
        blocks = [contracts.text(lead), result_list("Steps", items)]
        blocks += [{"type": "proposal_diff", "proposal": proposals.view(p, self.clock())} for p in compound.get("proposals") or []]
        refs = ([{"type": "campaign", "id": compound["campaignId"], "title": compound.get("campaignTitle") or "campaign"}] if compound.get("campaignId") else [])
        refs += [{"type": "draft", "id": d["id"], "title": "draft"} for d in compound.get("drafts") or []]
        answer = {**answer, "blocks": blocks, "text": lead, "refs": refs, "compound": compound, "grounding": {"required": False, "sufficient": True, "missing": []}}
        return answer, list(compound.get("proposals") or [])

    def _link_setup(self, state, member, text, focus, history, reading):
        """What to link (or unlink) and to which campaign: {"execute", ...}, or a question / a refusal. Nothing is guessed."""
        from . import compound as flow
        unlink = reading["intent"] == "campaign_unlink"
        if not member.allows("edit"):
            return {"reading": {"intent": "forbidden", "risk": "workspace_mutation", "forbidden": {"category": "role", "routeId": "roles"}}}
        p2 = state.get("phase2") or {}
        items = []
        plural = self._PLURAL.search(text)
        if plural and history:
            wanted = self._COUNT.get((plural.group(1) or "").lower()) or (int(plural.group(1)) if (plural.group(1) or "").isdigit() else None)
            mentions_posts = bool(re.search(r"\bposts?\b", text, re.I))
            kinds = ("job", "review") if mentions_posts else ("draft", "job", "review")
            # The most recent answer that listed such items (an answer in between may have listed none).
            latest = next(([r for r in refs if r.get("type") in kinds] for refs in history if any(r.get("type") in kinds for r in refs)), [])
            if wanted is not None and len(latest) != wanted:
                return {"ask": f"Your last list has {len(latest)} item(s), not {wanted}. Which ones do you mean?", "candidates": latest[:5]}
            if not latest or len(latest) > 5:
                return {"ask": "Which drafts or posts do you mean?", "candidates": latest[:5]}
            items = latest
        elif focus:
            items = [focus]
        if not items:
            return {"ask": "Which draft or post do you mean? Select it, or say “this draft”.", "candidates": []}
        draft_ids, job_ids, labels = [], [], []
        variants = {v.get("id"): v for v in state.get("variants", []) if isinstance(v, dict)}
        for item in items:
            if not item.get("title") and item.get("type") == "draft" and item.get("id") in variants:
                item = {**item, "title": f"the {variants[item['id']].get('platform')} draft"}
            if item.get("type") == "draft":
                draft_ids.append(item["id"])
            elif item.get("type") == "job":
                job_ids.append(item["id"])
            elif item.get("type") == "review":
                review = next((r for r in p2.get("reviews", []) if r.get("id") == item["id"]), None)
                if review and (review.get("manifest") or {}).get("variantId"):
                    draft_ids.append(review["manifest"]["variantId"])
            labels.append(item.get("title") or item.get("type"))
        found = flow.resolve_campaign(state, text, focus if (focus or {}).get("type") in ("automation", "campaign") else None, history)
        campaign = found.get("campaign")
        if campaign is None and unlink and not flow.campaign_name(text):
            # "Remove this draft from its campaign": the campaigns it is linked to.
            from .. import campaigns as campaign_records
            linked = {c["campaign"]["id"]: c["campaign"] for kind, ids in (("draft", draft_ids), ("post", job_ids)) for i in ids
                      for c in campaign_records.linked_campaigns(state, kind, i)}
            if len(linked) == 1:
                campaign = next(iter(linked.values()))
            elif linked:
                found = {"candidates": [{"type": "campaign", "id": c["id"], "title": (c.get("goal") or "")[:80]} for c in linked.values()]}
        if campaign is None:
            if found.get("none"):
                return {"none": found["none"], "candidates": found.get("candidates") or []}
            return {"ask": "Which campaign do you mean?", "candidates": found.get("candidates") or []}
        return {"execute": True, "op": "unlink" if unlink else "link", "campaignId": campaign["id"], "campaignTitle": (campaign.get("goal") or "")[:80],
                "draftIds": draft_ids, "jobIds": job_ids, "labels": labels[:5]}

    def _run_link(self, workspace_id, token, link):
        from ..hosted import audit
        from .. import campaigns as campaign_actions
        result = {}
        action = "raffi_campaign_unlink" if link["op"] == "unlink" else "raffi_campaign_link"

        def command(state, actor):
            result.update(campaign_actions.apply_action(state, action, {"campaignId": link["campaignId"], "draftIds": link["draftIds"], "jobIds": link["jobIds"]}, actor, self.clock()) or {})
            return state

        def after(cur, state, actor):
            kind = "campaign.items_unlinked_by_agent" if link["op"] == "unlink" else "campaign.items_linked_by_agent"
            audit(cur, workspace_id, actor, kind, link["campaignId"], {"drafts": len(link["draftIds"]), "posts": len(link["jobIds"])})

        for attempt in range(2):
            try:
                self.repository.command(workspace_id, token, self.service.get(workspace_id, token)["revision"], command, requirement="edit", after=after)
                return {"ok": True, **result}
            except AlphaError as error:
                if error.code == "workspace_revision_conflict" and not attempt:
                    continue
                return {"ok": False, "error": str(error), "status": error.status}
        return {"ok": False, "error": "The workspace kept changing; nothing was linked.", "status": 409}

    def _link_answer(self, link, answer, text=None):
        from .compose_reads import result_list

        def reply(message, blocks=(), refs=()):
            return {**answer, "blocks": [contracts.text(message), *blocks], "text": message, "refs": list(refs), "grounding": {"required": False, "sufficient": True, "missing": []}}

        if "ask" in link:
            return self._clarify_answer({"ask": link["ask"], "candidates": link.get("candidates") or []}, answer, request=text)
        if "none" in link:
            options = link.get("candidates") or []
            return reply(f"No campaign matches “{link['none']}”, so nothing was linked." + (" These are your campaigns:" if options else " There are no campaigns yet."),
                         blocks=[result_list("Campaigns", [{"kind": "campaign", "title": c["title"], "excerpt": None, "meta": None, "href": routes.href("automations", query={"campaign": c["id"]})}
                                                           for c in options])] if options else [])
        result = link.get("result") or {}
        href = routes.href("automations", query={"campaign": link["campaignId"]})
        things = ", ".join(link.get("labels") or []) or "it"
        if not result.get("ok"):
            return reply(f"Nothing was changed: {result.get('error') or 'the campaign could not be updated'}.", blocks=[contracts.navigation("Open the campaign", href, "automations")])
        if link["op"] == "unlink":
            message = (f"Removed {things} from “{link['campaignTitle']}”. The drafts and posts themselves are unchanged." if result.get("removed")
                       else f"{things[:1].upper() + things[1:]} wasn't in “{link['campaignTitle']}”, so nothing changed.")
        else:
            added, already = len(result.get("added") or []), result.get("alreadyLinked", 0)
            message = (f"Added {things} to “{link['campaignTitle']}”." if added and not already else
                       f"Added {added} and {already} {'was' if already == 1 else 'were'} already in “{link['campaignTitle']}”." if added else
                       f"{things[:1].upper() + things[1:]} {'is' if already == 1 else 'are'} already in “{link['campaignTitle']}”; nothing changed.")
            message += " Nothing was scheduled or published."
        blocks = [contracts.navigation("Open the campaign", href, "automations")]
        blocks += [contracts.navigation("Open the draft", routes.href("queue", query={"view": "drafts", "draft": d}), "queue") for d in link["draftIds"][:1]]
        refs = [{"type": "campaign", "id": link["campaignId"], "title": link["campaignTitle"]}] + [{"type": "draft", "id": d, "title": "draft"} for d in link["draftIds"]]
        return reply(message, blocks=blocks, refs=refs)

    def compound_continue(self, workspace_id, token, payload):
        """Finish a compound request whose writing run ended after the turn: save, link, propose scheduling. Idempotent."""
        from . import compound as flow
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            body = self._message_body(cur, workspace_id, payload)
            site = body.get("siteAgent") or {}
            plan = site.get("compound")
            if not plan or not plan.get("pending"):
                return {"message": body, "status": "unchanged"}
        zone = writing_intent.safe_zone(payload.get("timeZone"))
        plan = flow.advance(self, workspace_id, token, {**plan, "proposals": []}, principal=principal, now=now, zone=zone, text=plan.get("text") or "")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            body = self._message_body(cur, workspace_id, payload, lock=True)
            site = dict(body.get("siteAgent") or {})
            if not (site.get("compound") or {}).get("pending"):
                return {"message": body, "status": "unchanged"}
            answer, proposal_list = self._compound_answer(plan, {"blocks": [], "text": "", "citations": [], "grounding": {}})
            site.update(blocks=answer["blocks"], proposals=proposal_list, refs=answer["refs"], compound={k: v for k, v in plan.items() if k not in ("proposals", "delegate")})
            body = {**body, "text": answer["text"], "siteAgent": site}
            cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s AND workspace_id=%s", (json.dumps(body, ensure_ascii=False), payload["messageId"], workspace_id))
            return {"message": body, "status": "advanced"}

    def _message_body(self, cur, workspace_id, payload, lock=False):
        conversation_id, message_id = payload.get("conversationId"), payload.get("messageId")
        if not isinstance(conversation_id, str) or not isinstance(message_id, str):
            raise AlphaError("Choose the answer to continue.", 400)
        self.ideas._conversation(cur, workspace_id, conversation_id)
        cur.execute("SELECT body FROM public.pr_messages WHERE id::text=%s AND conversation_id::text=%s AND workspace_id=%s AND role='assistant'" + (" FOR UPDATE" if lock else ""),
                    (message_id, conversation_id, workspace_id))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Answer unavailable.", 404)
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])

    @staticmethod
    def _clarify_answer(clarify, answer, request=None):
        """Ask instead of guessing; the options are sentences that resolve on the next turn ("the second one"), which
        then runs the request this question was about on the chosen item (`pending`)."""
        candidates = clarify.get("candidates") or []
        words = ("the first one", "the second one", "the third one", "the fourth one", "the fifth one")
        options = [words[i] for i in range(min(len(candidates), len(words)))]
        blocks = [contracts.question(clarify["ask"], options)]
        if candidates:
            from .compose_reads import result_list
            blocks.append(result_list("Options", [{"kind": c.get("type"), "title": f"{i + 1}. {c.get('title')}", "excerpt": None, "meta": None, "href": None} for i, c in enumerate(candidates)]))
        pending = {"request": request[:contracts.MAX_MESSAGE], "candidates": candidates[:5]} if request and candidates else None
        return {**answer, "blocks": blocks, "text": clarify["ask"], "refs": candidates, "pending": pending, "grounding": {"required": False, "sufficient": True, "missing": []}}

    def _schedule_answer(self, state, text, principal, member, now, zone, focus, reading, answer):
        """Schedule a draft, or move a waiting post, as a proposal checked with the real review commands on a copy."""
        from .. import workflow_parse
        from . import timeframe

        def reply(message, *, blocks=(), refs=(), proposals_=()):
            return {**answer, "blocks": [contracts.text(message), *blocks], "text": message, "refs": list(refs), "grounding": {"required": False, "sufficient": True, "missing": []}}, list(proposals_)

        if not member.allows("approve"):
            return reply("Preparing a post for approval needs the approve permission. Someone who can approve can schedule it from Queue → Drafts.",
                         blocks=[contracts.navigation("Open Drafts", routes.href("queue", query={"view": "drafts"}), "queue")])
        p2 = state.get("phase2") or {}
        variants = [v for v in state.get("variants", []) if isinstance(v, dict)]
        job = variant = None
        if focus and focus.get("type") == "draft":
            variant = next((v for v in variants if v.get("id") == focus["id"]), None)
        elif focus and focus.get("type") in ("job", "review"):
            item = next((i for i in p2.get("jobs", []) + p2.get("reviews", []) if i.get("id") == focus["id"]), None)
            if item is not None:
                job = item if focus["type"] == "job" and item in p2.get("jobs", []) else None
                variant = next((v for v in variants if v.get("id") == (item.get("manifest") or {}).get("variantId")), None)
        if variant is None:
            clarify = {"ask": "Which draft should I schedule?", "candidates": [{"type": "draft", "id": v["id"], "title": f"{v.get('platform')} draft: {' '.join((v.get('text') or '').split())[:60]}"}
                                                                              for v in reversed(variants) if not v.get("rejected")][:5]}
            return self._clarify_answer(clarify, answer), []
        frame = timeframe.parse(text, now, zone)
        clock = workflow_parse._time_in(text)
        if clock is None and job is not None:
            clock = (((job.get("manifest") or {}).get("timing") or {}).get("local") or "")[11:16] or None
        day_ok = frame is not None and frame["end"] - frame["start"] <= 25 * 3600
        if not day_ok or clock is None:
            example = f"Schedule it for {(frame or {}).get('label') or 'Tuesday'} at 18:00" if job is None else f"Move it to {(frame or {}).get('label') or 'Thursday'} at 18:00"
            return reply(("Tell me the day and time" if not day_ok else "Tell me the time") + f", for example “{example}”.",
                         blocks=[contracts.question("Which day and time?", [example])], refs=[{"type": "draft", "id": variant["id"], "title": f"{variant.get('platform')} draft"}] if not job else [{"type": "job", "id": job["id"], "title": "post"}])
        channels = [c for c in p2.get("channels", []) if isinstance(c, dict) and not c.get("revoked")]
        channel = next((c for c in channels if c.get("id") == (variant.get("channelId") or ((job or {}).get("manifest") or {}).get("channelId"))), None)
        if channel is None:
            same = [c for c in channels if c.get("platform") == variant.get("platform")]
            channel = same[0] if len(same) == 1 else None
        if channel is None:
            return reply(f"Choose the {variant.get('platform')} account in the schedule dialog: this draft has no account and I won't pick one for you.",
                         blocks=[contracts.navigation("Open the draft", routes.href("queue", query={"view": "drafts", "draft": variant["id"]}), "queue")])
        local_time = f"{frame['startDate']}T{clock}"
        built = proposals.build_schedule(state, variant=variant, channel=channel, local_time=local_time, zone=zone, actor=principal, now=now,
                                         commands=self.service.commands, job=job)
        if "refuse" in built:
            return reply(f"I can't prepare that yet: {built['refuse']}", blocks=[contracts.navigation("Open the draft", routes.href("queue", query={"view": "drafts", "draft": variant["id"]}), "queue")],
                         refs=[{"type": "draft", "id": variant["id"], "title": f"{variant.get('platform')} draft"}])
        proposal = built["proposal"]
        lead = ("Here's the move I'd make. Nothing changes until you apply it, and the new time still needs approval." if job
                else "Here's what I'd prepare. Nothing changes until you apply it, and the post still needs approval before it can publish.")
        return {**answer, "blocks": [contracts.text(lead), {"type": "proposal_diff", "proposal": proposals.view(proposal, now)}], "text": lead,
                "refs": [{"type": "draft", "id": variant["id"], "title": f"{variant.get('platform')} draft"}], "grounding": {"required": True, "sufficient": True, "missing": []}}, [proposal]

    @staticmethod
    def _actions(answer, plan, page):
        actions, seen = [], set()
        for block in answer["blocks"]:
            if block["type"] == "navigation_card" and block["href"] not in seen:
                seen.add(block["href"])
                actions.append({"ref": f"A{len(actions) + 1}", "label": block["label"], "href": block["href"], "routeId": block["routeId"]})
        for citation in answer["citations"][:2]:
            href = f"/app/help/{citation['documentId']}#" + knowledge.slug(citation["section"])
            if href not in seen:
                seen.add(href)
                actions.append({"ref": f"A{len(actions) + 1}", "label": f"Read: {citation['title']}", "href": href, "routeId": "help_article"})
        return actions[:4]

    @staticmethod
    def _labels(state):
        labels = [c.get("account") for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict)]
        return [label for label in labels if isinstance(label, str)]

    @staticmethod
    def _known_ids(page, results, state):
        ids = set()
        entity = page.get("selectedEntity") or {}
        if entity.get("id"):
            ids.add(entity["id"].lower())
        blob = json.dumps({k: v.get("data") for k, v in results.items()}, default=str).lower()
        import re
        ids.update(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{24,64}", blob))
        return sorted(ids)[:200]

    def _finalize(self, cur, workspace_id, conversation_id, run_id, answer, summary, trace, reading, proposal_list, *, composed_by, model_id, follow_ups, usage):
        blocks = answer["blocks"]
        for block in blocks[:MAX_BLOCK_EVENTS]:
            self._emit(cur, workspace_id, run_id, "artifact.created", artifact="site_agent.block", block=block)
        for block in blocks:
            if block["type"] == "warning":
                self._emit(cur, workspace_id, run_id, "warning.created", message=block["message"], code=block["code"])
        self._emit(cur, workspace_id, run_id, "message.completed", text=answer["text"][:12000])
        trace = {**trace, "composedBy": composed_by, "outcome": _outcome(reading, answer, proposal_list)}
        refs = [r for r in (answer.get("refs") or []) if isinstance(r, dict) and r.get("id")][:12]
        artifact = {"version": contracts.VERSION, "blocks": blocks, "citations": answer["citations"], "grounding": answer["grounding"],
                    "proposalRefs": [p["id"] for p in proposal_list], "contextSummary": summary, "next": {"questions": follow_ups}, "trace": trace, "refs": refs}
        artifact_hash = digest(artifact)
        cur.execute("UPDATE public.pr_agent_runs SET status='completed',artifact=%s::jsonb,artifact_hash=%s,usage=%s::jsonb,updated_at=now() WHERE id::text=%s",
                    (json.dumps(artifact, ensure_ascii=False), artifact_hash, json.dumps(usage), run_id))
        body = {"text": answer["text"], "runId": run_id, "siteAgent": {"version": contracts.VERSION, "runId": run_id, "status": "completed", "intent": reading["intent"],
                                                                       "language": reading.get("language"), "blocks": blocks, "citations": answer["citations"],
                                                                       "grounding": answer["grounding"], "proposals": proposal_list, "context": summary,
                                                                       "model": {"id": model_id, "composedBy": composed_by}, "followUps": follow_ups, "feedback": None,
                                                                       "refs": refs}}
        if answer.get("pending"):
            body["siteAgent"]["pending"] = answer["pending"]
        if answer.get("compound"):
            body["siteAgent"]["compound"] = {k: v for k, v in answer["compound"].items() if k not in ("proposals", "delegate")}
        self.ideas._settle_message(cur, workspace_id, conversation_id, run_id, body)
        self._emit(cur, workspace_id, run_id, "run.completed", usage={k: usage.get(k) for k in ("provenance", "modelRequests", "costUsd", "billing") if k in usage})

    # --- compose ----------------------------------------------------------------------------------------------------------
    def compose(self, workspace_id, token, run_id):
        now = self.clock()
        reservation = None
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = self._member(row)
            require(member, "read")
            self.ideas._lock_run_events(cur, workspace_id, run_id)
            run = self._run(cur, workspace_id, run_id, lock=True)
            pending = run["artifact"].get("pending")
            if run["status"] != "running" or not pending or run["usage"].get("composeClaimedAt"):
                return self._response(cur, workspace_id, run_id)
            if run["actor"] != principal:
                raise AlphaError("Only the person who asked can finish this answer.", 403)
            require(member, "edit")
            runtime, note = self._runtime(pending["model"])
            call = request_model.call_for(runtime, self.model, pending["tier"]) if runtime is not None else None
            user = None
            mapping = {}
            if call is not None:
                facts = [f["text"] for f in pending["facts"]]
                cloud = not getattr(call, "local", False)
                if cloud:
                    facts, mapping = prompts.pseudonymize(facts, pending.get("labels") or [])
                fact_items = [{**f, "text": text} for f, text in zip(pending["facts"], facts)]
                user = prompts.user_prompt(language=pending["language"], page=pending["page"], membership=pending["member"],
                                           procedures=pending["procedures"], passages=pending["passages"], facts=fact_items, actions=pending["actions"],
                                           history=pending["history"], message=pending["message"], draft_text=None if cloud else pending.get("draftText"))
                if not getattr(call, "local", False):
                    cur.execute("SAVEPOINT site_agent_reserve")
                    try:
                        reservation = self.service.ledger.reserve(cur, workspace_id, principal, "text_model", prompts.price_quote_micro(user, pending["tier"]),
                                                                  f"site-agent:{run_id}", charge_batch=False, provider="site_agent", model=getattr(call, "model", "") or "", run_id=run_id)
                        cur.execute("RELEASE SAVEPOINT site_agent_reserve")
                    except AlphaError as error:
                        cur.execute("ROLLBACK TO SAVEPOINT site_agent_reserve")
                        note = {"code": "budget", "message": f"Rafii didn't use the writer for this answer: {error} This answer comes from Rafii's help and your workspace."}
                        call = None
            if call is None:
                self._finish_grounded(cur, workspace_id, run, run_id, pending, note or {"code": "writer_unavailable", "message": "The chosen writer can't phrase answers here, so this one comes from Rafii's help and your workspace."})
                return self._response(cur, workspace_id, run_id)
            claimed = {**run["usage"], "composeClaimedAt": now, "reservationId": (reservation or {}).get("reservationId"), "provenance": "pending"}
            cur.execute("UPDATE public.pr_agent_runs SET usage=%s::jsonb,updated_at=now() WHERE id::text=%s", (json.dumps(claimed), run_id))
        answer, reason, actual = None, None, None
        try:
            result = call(prompts.SYSTEM_PROMPT, user, prompts.SCHEMA)
            actual = getattr(result, "cost_usd_micro", None)
            help_refs = {p["ref"] for p in pending["passages"]}
            fact_refs = {f["ref"] for f in pending["facts"]}
            action_refs = {a["ref"] for a in pending["actions"]}
            answer, reason = policy.validate_answer(dict(result) if isinstance(result, dict) else result, help_refs=help_refs, fact_refs=fact_refs,
                                                    action_refs=action_refs, known_ids=set(pending.get("knownIds") or []), grounding_required=pending["grounding"])
        except Exception as error:  # noqa: BLE001 — a failed model answer never loses the grounded one
            reason = "error" if not isinstance(error, AlphaError) else (error.code or "error")
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            self.ideas._lock_run_events(cur, workspace_id, run_id)
            run = self._run(cur, workspace_id, run_id, lock=True)
            if reservation is not None:
                self.service.ledger.settle(cur, workspace_id, reservation["reservationId"], "completed" if actual is not None else "unknown", actual)
            if run["status"] != "running":
                return self._response(cur, workspace_id, run_id)
            usage = {"provenance": "model" if answer else "grounded", "modelRequests": 1, "tier": pending["tier"],
                     "costUsd": (actual / 1_000_000) if actual is not None else None, "billing": "metered" if reservation else "subscription_or_local"}
            if answer is None:
                message = {"error": "Rafii's writer didn't answer, so this answer comes straight from Rafii's help and your workspace."}.get(
                    reason, "Rafii's written answer didn't pass its checks, so this answer comes straight from Rafii's help and your workspace.")
                self._finish_grounded(cur, workspace_id, run, run_id, pending, {"code": f"model_{reason}", "message": message}, usage=usage)
                return self._response(cur, workspace_id, run_id)
            grounded = pending["grounded"]
            text = prompts.restore(answer["answer"], mapping) if mapping else answer["answer"]
            structured = [b for b in grounded["blocks"] if b["type"] in ("diagnostic_card", "handoff_card", "question_form", "warning", "error", "result_list")]
            navs = [contracts.navigation(a["label"], a["href"], a["routeId"]) for a in pending["actions"] if a["ref"] in answer["actions"]]
            if not navs:
                navs = [b for b in grounded["blocks"] if b["type"] == "navigation_card"][:1]
            citations = [c for c in grounded["citations"] if c.get("ref") in answer["citations"]]
            if not citations and answer["citations"]:
                passages = [p for p in pending["passages"] if p["ref"] in answer["citations"]]
                citations = composer.citation_objects(passages, contracts.iso(now), used=set(answer["citations"]))
            blocks = [contracts.text(text)] + structured + navs + ([contracts.citations(citations)] if citations else [])
            if not answer["sufficient"] and answer["missing"]:
                blocks.append(contracts.warning("Not covered by Rafii's help or your workspace: " + "; ".join(answer["missing"]), "grounding_insufficient"))
            final = {"blocks": blocks, "text": text, "citations": citations, "refs": grounded.get("refs") or [],
                     "grounding": {"required": pending["grounding"], "sufficient": answer["sufficient"], "missing": answer["missing"]}}
            trace = {**pending["trace"], "modelFacts": answer["facts"]}
            reading = {"intent": pending["intent"], "language": pending["language"]}
            self._finalize(cur, workspace_id, run["conversationId"], run_id, final, pending["summary"], trace, reading, [], composed_by="model",
                           model_id=pending["model"], follow_ups=answer["followUps"], usage=usage)
            return self._response(cur, workspace_id, run_id)

    def _finish_grounded(self, cur, workspace_id, run, run_id, pending, note, usage=None):
        grounded = pending["grounded"]
        blocks = [contracts.warning(note["message"], note["code"])] + list(grounded["blocks"])
        answer = {**grounded, "blocks": blocks}
        trace = {**pending["trace"], "fallback": note["code"]}
        reading = {"intent": pending["intent"], "language": pending["language"]}
        self._finalize(cur, workspace_id, run["conversationId"], run_id, answer, pending["summary"], trace, reading, [], composed_by="grounded",
                       model_id=pending["model"], follow_ups=[], usage=usage or {"provenance": "grounded", "modelRequests": 0})

    def events(self, workspace_id, token, run_id, cursor=0):
        """Replay a panel run's events after `cursor`, with the answer message (reconnect, §13.4)."""
        if type(cursor) is not int or cursor < 0:
            raise AlphaError("Invalid event cursor.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "read")
            return self._response(cur, workspace_id, run_id, cursor)

    # --- cancel and recovery ----------------------------------------------------------------------------------------------
    def cancel(self, workspace_id, token, run_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "read")
            self.ideas._lock_run_events(cur, workspace_id, run_id)
            run = self._run(cur, workspace_id, run_id, lock=True)
            if run["status"] != "running":
                return {"runId": run_id, "status": run["status"], "note": "Already finished; nothing to stop."}
            reservation = run["usage"].get("reservationId")
            if reservation:
                # The writer may already be answering; its cost is held as unknown, never recorded as free.
                self.service.ledger.settle(cur, workspace_id, reservation, "unknown")
            self._emit(cur, workspace_id, run_id, "run.cancelled", message="Stopped. Nothing was changed.")
            cur.execute("UPDATE public.pr_agent_runs SET status='cancelled',updated_at=now() WHERE id::text=%s", (run_id,))
            message_id, body = self._message_for_run(cur, workspace_id, run["conversationId"], run_id)
            if message_id:
                body = dict(body or {})
                site = dict(body.get("siteAgent") or {})
                site.update(status="cancelled", blocks=[contracts.text("Stopped. Nothing was changed.")])
                body.update(text="Stopped. Nothing was changed.", pending=False, cancelled=True, siteAgent=site)
                cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s", (json.dumps(body, ensure_ascii=False), message_id))
            return {"runId": run_id, "status": "cancelled"}

    def recover_stalled(self, max_runs=25):
        """Cron: a panel answer whose composition never started (tab closed) or never finished gets its grounded answer.
        A claimed composition's cost stays held as unknown; nothing calls a model here."""
        recovered = 0
        cutoff = self.clock() - STALE_COMPOSE_SECONDS
        with self.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT workspace_id::text,id::text FROM public.pr_agent_runs WHERE status='running' AND idempotency_key LIKE 'site:%%' AND updated_at<to_timestamp(%s) ORDER BY updated_at LIMIT %s",
                        (cutoff, max_runs))
            for workspace_id, run_id in cur.fetchall():
                self.ideas._lock_run_events(cur, workspace_id, run_id)
                run = self._run(cur, workspace_id, run_id, lock=True)
                if run["status"] != "running" or not run["artifact"].get("pending"):
                    continue
                claimed = run["usage"].get("composeClaimedAt")
                if claimed and claimed > self.clock() - CLAIMED_STALE_SECONDS:
                    continue  # a writer may still be answering; its own request settles it
                if run["usage"].get("reservationId"):
                    self.service.ledger.settle(cur, workspace_id, run["usage"]["reservationId"], "unknown")
                self._finish_grounded(cur, workspace_id, run, run_id, run["artifact"]["pending"],
                                      {"code": "composition_interrupted", "message": "Rafii's written answer didn't finish, so this answer comes from Rafii's help and your workspace."})
                recovered += 1
        return {"recovered": recovered, "providerRequests": 0}

    # --- proposals --------------------------------------------------------------------------------------------------------
    def _proposal_row(self, cur, workspace_id, payload, lock=False):
        message_id, conversation_id, proposal_id = payload.get("messageId"), payload.get("conversationId"), payload.get("proposalId")
        if not all(isinstance(v, str) and v for v in (message_id, conversation_id, proposal_id)):
            raise AlphaError("Name the proposal to apply.", 400)
        cur.execute("SELECT id::text,body FROM public.pr_messages WHERE id::text=%s AND conversation_id::text=%s AND workspace_id=%s AND role='assistant'" + (" FOR UPDATE" if lock else ""),
                    (message_id, conversation_id, workspace_id))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Proposal unavailable.", 404)
        body = row[1] or {}
        found = next((p for p in (body.get("siteAgent") or {}).get("proposals") or [] if isinstance(p, dict) and p.get("id") == proposal_id), None)
        if found is None:
            raise AlphaError("Proposal unavailable.", 404)
        return body, found

    def _store_proposal(self, cur, workspace_id, payload, body, proposal):
        site = dict(body.get("siteAgent") or {})
        site["proposals"] = [proposal if p.get("id") == proposal["id"] else p for p in site.get("proposals") or []]
        site["blocks"] = [({**b, "proposal": proposals.view(proposal, self.clock())} if b.get("type") == "proposal_diff" and (b.get("proposal") or {}).get("id") == proposal["id"] else b)
                          for b in site.get("blocks") or []]
        cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s AND workspace_id=%s", (json.dumps({**body, "siteAgent": site}, ensure_ascii=False), payload["messageId"], workspace_id))

    def apply_proposal(self, workspace_id, token, payload):
        from ..hosted import audit
        now = self.clock()
        zone = writing_intent.safe_zone(payload.get("timeZone"))
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            _, proposal = self._proposal_row(cur, workspace_id, payload)
            scheduling = proposal.get("type") in proposals.SCHEDULE_TYPES
            # Preparing a review is approve-class in the app (permissions.ACTION_CLASSES); an automation change is edit-class.
            require(member, "approve" if scheduling else "edit")
            if scheduling and proposal.get("needsEdit"):
                # Using a rewrite or confirming a draft review are edits of the draft (Queue → Drafts); preparing it is approve-class.
                require(member, "edit")
            proposals.check(proposal, digest_value=payload.get("digest"), now=now)
            owner = member.allows("owner")
            can_edit = member.allows("edit")
            task = next((t for t in automation_edit.live_tasks(self.ideas._state(row)) if t.get("id") == proposal.get("taskId")), None)
            paid = self._paid_route(task.get("route")) if task else False
            zone = proposal.get("timeZone") or zone
        outcome = {}

        def command(state, actor):
            outcome.update(proposals.apply(state, proposal, actor=actor, now=now, owner=owner, paid=paid, zone=zone, commands=self.service.commands, can_approve=scheduling,
                                           can_edit=can_edit))
            return state

        def after(cur, state, actor):
            body, stored = self._proposal_row(cur, workspace_id, payload, lock=True)
            proposals.check(stored, digest_value=payload.get("digest"), now=now)
            if stored.get("requiredPermission") == "owner":
                cur.execute("SELECT m.role FROM public.pr_memberships m WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active'", (workspace_id, actor))
                role = cur.fetchone()
                if not role or role[0] != "owner":
                    raise AlphaError("Only an owner of this workspace can apply this change.", 403, code="owner_required")
            if scheduling and stored.get("needsEdit"):
                cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active'",
                            (workspace_id, actor))
                role = cur.fetchone()
                if not role or not Membership.from_row(*role).allows("edit"):
                    raise AlphaError("Using the rewrite or confirming the draft review needs the edit permission as well.", 403, code="edit_required")
            if scheduling:
                from ..billing import require_publishing
                require_publishing(cur, workspace_id, self.clock())  # the same plan gate as preparing a review in the Queue
            applied = {**stored, "status": "applied", "appliedAt": now,
                       "result": {k: outcome.get(k) for k in ("taskId", "status", "version", "summary", "needs", "reviewId", "localTime", "timeZone", "cancelledJobId")}}
            self._store_proposal(cur, workspace_id, payload, body, applied)
            if scheduling:
                audit(cur, workspace_id, actor, "post.review_prepared_by_proposal", outcome.get("reviewId") or "", {"proposal": stored["id"], "moved": bool(stored.get("jobId"))})
            else:
                audit(cur, workspace_id, actor, "automation.changed_by_proposal", stored.get("taskId") or "", {"changes": len(stored.get("changes") or []), "proposal": stored["id"]})

        try:
            saved = self.repository.command(workspace_id, token, payload.get("expectedRevision"), command, requirement="approve" if scheduling else "edit", after=after)
        except AlphaError as error:
            if error.code in ("proposal_stale", "proposal_expired"):
                with self.repository.transaction(token, workspace_id) as (cur, _, _):
                    body, stored = self._proposal_row(cur, workspace_id, payload, lock=True)
                    if stored.get("status") == "proposed":
                        closed = {**stored, "status": "superseded" if error.code == "proposal_stale" else "expired", "closedReason": str(error)}
                        self._store_proposal(cur, workspace_id, payload, body, closed)
            raise
        return {"proposal": proposals.view({**proposal, "status": "applied", "appliedAt": now, "result": outcome}, now), "revision": saved["revision"],
                "state": self.service.commands.present(saved["state"], saved["revision"]) if hasattr(self.service, "commands") else None}

    def dismiss_proposal(self, workspace_id, token, payload):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            body, proposal = self._proposal_row(cur, workspace_id, payload, lock=True)
            require(member, "approve" if proposal.get("type") in proposals.SCHEDULE_TYPES else "edit")
            if proposal.get("status") != "proposed":
                return {"proposal": proposals.view(proposal, self.clock())}
            closed = {**proposal, "status": "dismissed", "closedReason": "Dismissed."}
            self._store_proposal(cur, workspace_id, payload, body, closed)
            return {"proposal": proposals.view(closed, self.clock())}

    # --- feedback, help, insights -------------------------------------------------------------------------------------------
    def feedback(self, workspace_id, token, payload):
        value, reason = payload.get("value"), payload.get("reason")
        if value not in ("helpful", "not_helpful") or reason not in (None, "wrong", "unclear", "missing", "other"):
            raise AlphaError("Choose helpful or not helpful.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "read")
            cur.execute("SELECT id::text,body FROM public.pr_messages WHERE id::text=%s AND workspace_id=%s AND role='assistant' FOR UPDATE", (payload.get("messageId"), workspace_id))
            found = cur.fetchone()
            if not found or not isinstance((found[1] or {}).get("siteAgent"), dict):
                raise AlphaError("Answer unavailable.", 404)
            body = found[1]
            site = {**body["siteAgent"], "feedback": {"value": value, "reason": reason, "at": contracts.iso(self.clock())}}
            cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s", (json.dumps({**body, "siteAgent": site}, ensure_ascii=False), found[0]))
            return {"messageId": found[0], "feedback": site["feedback"]}

    def help_catalogue(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (_, row, _):
            require(self._member(row), "read")
        kb = knowledge.snapshot()
        return {"snapshot": kb["id"], "productVersion": kb["productVersion"], "documents": knowledge.catalogue()}

    def help_document(self, workspace_id, token, document_id):
        with self.repository.transaction(token, workspace_id) as (_, row, _):
            require(self._member(row), "read")
        doc = knowledge.get(document_id)
        if doc is None:
            raise AlphaError("Help article unavailable.", 404)
        return doc

    def insights(self, workspace_id, token, days=30):
        """Owner and admin view of how the panel is doing: volumes, outcomes, fallbacks, blocked tools and feedback (§16.2).
        Built from the traces only; no question text."""
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            if member.role not in ("owner", "admin"):
                raise AlphaError("Only an owner or admin can see Rafii's answer quality.", 403)
            since = self.clock() - days * 86400
            cur.execute("SELECT status,artifact->'trace' FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key LIKE 'site:%%' AND created_at>=to_timestamp(%s)", (workspace_id, since))
            rows = cur.fetchall()
            cur.execute("SELECT body->'siteAgent'->'feedback'->>'value',count(*) FROM public.pr_messages WHERE workspace_id=%s AND role='assistant' AND body ? 'siteAgent' AND created_at>=to_timestamp(%s) GROUP BY 1", (workspace_id, since))
            feedback = {value or "none": int(count) for value, count in cur.fetchall()}
        by_intent, outcomes, composed, fallbacks, blocked, ungrounded = {}, {}, {}, {}, 0, 0
        for status, trace in rows:
            trace = trace or {}
            by_intent[trace.get("intent") or "unknown"] = by_intent.get(trace.get("intent") or "unknown", 0) + 1
            outcome = trace.get("outcome") or status
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if trace.get("composedBy"):
                composed[trace["composedBy"]] = composed.get(trace["composedBy"], 0) + 1
            if trace.get("fallback"):
                fallbacks[trace["fallback"]] = fallbacks.get(trace["fallback"], 0) + 1
            blocked += sum(1 for tool in trace.get("tools") or [] if tool.get("status") == "blocked")
            ungrounded += 0 if trace.get("grounded", True) else 1
        return {"days": days, "turns": len(rows), "byIntent": by_intent, "outcomes": outcomes, "composedBy": composed, "fallbacks": fallbacks,
                "blockedTools": blocked, "unanswered": ungrounded, "feedback": feedback, "since": dt.datetime.fromtimestamp(since, dt.timezone.utc).date().isoformat()}


def _outcome(reading, answer, proposal_list):
    if reading["intent"] == "forbidden":
        return "blocked"
    if proposal_list:
        return "proposed"
    if any(b["type"] == "handoff_card" for b in answer["blocks"]):
        return "handoff"
    return "answered" if answer["grounding"]["sufficient"] else "unanswered"
