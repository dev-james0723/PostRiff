"""AgentRuntimeService — one operation: run a Rafii turn against authenticated workspace context (spec §8, ADR-P2).

Text, delegated voice and image requests all come through `turn`. The modality changes the output's shape
(`speakableSummary`), never what Rafii may do.

    authenticate + bind workspace → idempotency → conversation → attachments → deterministic front door
      ├─ "yes" / "no"  → bind to exactly one presented proposal → site agent apply/dismiss → re-read → verified answer
      ├─ "cancel that" → cancel running agent work and open steps in the backend → confirm by re-reading
      ├─ fallback      → the verified SiteAgentService.turn, unchanged (runtime off, viewer, no route, budget, forbidden,
      │                  greeting — no model spend where the site agent already answers deterministically)
      └─ Manager       → Agents SDK run outside any transaction → effect ledger → answer policy → one assistant message
                         in the site agent's block format (the panel renders it; apply/dismiss work unchanged) plus the
                         surface-neutral result (`body.agent`) → run/usage/trace persisted → task saved.

Nothing here writes workspace state directly: every mutation is a tool's domain command or the site agent's apply path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from postriff_alpha.domain import AlphaError, clean, uid

from .. import intent as writing_intent
from ..agent_runtime import safe_event
from ..contracts import digest
from ..permissions import require
from . import answer_policy, approvals, config as runtime_config, contracts, creative, domain_tools, task_state
from .context import RafiiRunContext

KEY_PREFIX = "agent:"
VOICE_PREFIX = "voice:"
AGENT_MODEL = "rafii-agent"
MAX_MESSAGE = 4000
MAX_ATTACHMENTS = 4
TURN_BUDGET_SECONDS = 240
SUPERSEDE_WINDOW_SECONDS = 180
# An agent turn still "running" this long after it last changed was killed (Vercel stops a function at 300 s).
STALE_TURN_SECONDS = 600
HISTORY_MESSAGES = 12
RUNTIME_VERSION = "agent-runtime-1"
# Extensions add blocks to a run's trace (e.g. the skill provenance of the turn): fn(ctx=..., routes=...) -> dict.
TRACE_HOOKS: list = []


def register_trace_hook(fn) -> None:
    if fn not in TRACE_HOOKS:
        TRACE_HOOKS.append(fn)
EPOCH = digest({"runtime": RUNTIME_VERSION})
log = logging.getLogger("postriff.agent_runtime")
_IMAGE_ORDINAL = re.compile(r"\b(?:the\s+)?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+(?:image|picture|photo|pic|one\s+you\s+made)\b"
                            r"|(第[一二三四五]|最後|最后)(?:張|张|個|个|幅)?(?:圖|图|相|相片|圖片|图片)", re.I)
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1,
             "第一": 1, "第二": 2, "第三": 3, "第四": 4, "第五": 5, "最後": -1, "最后": -1}


class AgentRuntimeService:
    def __init__(self, service, cfg: runtime_config.RuntimeConfig | None = None, *, model_factory=None, image_studio=None, vision=None, live_transport=None, clock=None):
        self.service = service
        self.cfg = cfg or runtime_config.RuntimeConfig.from_environment()
        self.model_factory = model_factory
        self.image_studio = image_studio
        self.vision = vision
        self.live_transport = live_transport
        self.clock = clock or getattr(service, "clock", None) or time.time
        domain_tools.ensure_registered()

    # --- public status -----------------------------------------------------------------------------------------------
    def status(self, workspace_id, token) -> dict:
        with self.service.repository.transaction(token, workspace_id) as (_cur, row, _principal):
            member = self.service.ideas._member(row)
            require(member, "read")
        voice = self.cfg.route("voice_front_end", reason="status")
        manager = self.cfg.route("standard_reasoning", reason="status")
        return {"runtime": RUNTIME_VERSION, **self.cfg.public(), "canUseModel": member.allows("edit"),
                # Voice delegates every request to the agent runtime, so it needs both flags.
                "voice": {"available": voice.available and self.cfg.enabled("RAFII_VOICE_ENABLED") and self.cfg.enabled("RAFII_AGENT_V2_ENABLED") and member.allows("edit"),
                          "blocker": voice.blocker if not voice.available else
                          (None if self.cfg.enabled("RAFII_VOICE_ENABLED") and self.cfg.enabled("RAFII_AGENT_V2_ENABLED") else "Voice Mode is not enabled on this deployment.")},
                "manager": {"available": (manager.available or self.model_factory is not None) and self.cfg.enabled("RAFII_AGENT_V2_ENABLED"), "blocker": manager.blocker}}

    # --- turn --------------------------------------------------------------------------------------------------------
    def turn(self, workspace_id, token, payload) -> dict:
        if not isinstance(payload, dict):
            raise AlphaError("Send a structured turn.", 400)
        from ..site_agent import contracts as site_contracts
        text = clean(payload.get("message", ""), MAX_MESSAGE)
        modality = payload.get("modality") if payload.get("modality") in contracts.MODALITIES else "text"
        attachments_in = [a for a in (payload.get("attachments") or []) if isinstance(a, dict) and isinstance(a.get("assetId"), str)][:MAX_ATTACHMENTS]
        if not text and not attachments_in:
            raise AlphaError("Ask Rafii something.", 400)
        text = text or "What do you see in this image?"
        key = clean(payload.get("idempotencyKey", ""), 100) or uid()
        run_key = KEY_PREFIX + key
        page = site_contracts.page_context(payload.get("pageContext"))
        zone = writing_intent.safe_zone(payload.get("timeZone"))
        trace_id = payload.get("traceId") if contracts.valid_trace_id(payload.get("traceId")) else contracts.new_trace_id()
        now = self.clock()
        repo, ideas = self.service.repository, self.service.ideas
        with repo.transaction(token, workspace_id) as (cur, row, principal):
            member = ideas._member(row)
            require(member, "read")
            cur.execute("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, run_key))
            prior = cur.fetchone()
            if prior:
                return self._stored(cur, workspace_id, prior[0])
            conversation_id = payload.get("conversationId")
            if conversation_id:
                if not isinstance(conversation_id, str):
                    raise AlphaError("Conversation unavailable.", 404)
                ideas._conversation(cur, workspace_id, conversation_id)
            state = ideas._state(row)
            attachments = self._attach(cur, state, workspace_id, conversation_id, principal, attachments_in, member) if conversation_id else []
            decision = self._front_door(cur, state, workspace_id, conversation_id, member, text, page, modality)
        if decision["mode"] == "fallback":
            return self._fallback(workspace_id, token, payload, text, modality, trace_id, reason=decision.get("reason"))
        if not conversation_id:
            conversation_id = self._new_conversation(workspace_id, token, text)
            with repo.transaction(token, workspace_id) as (cur, row, principal):
                attachments = self._attach(cur, ideas._state(row), workspace_id, conversation_id, principal, attachments_in, ideas._member(row))
        if decision["mode"] in ("confirm", "reject", "choose"):
            return self._decide_turn(workspace_id, token, conversation_id, text, modality, run_key, trace_id, decision, zone, attachments)
        if decision["mode"] == "cancel":
            return self._cancel_turn(workspace_id, token, conversation_id, text, modality, run_key, trace_id)
        return self._manager_turn(workspace_id, token, conversation_id, text, modality, run_key, trace_id, page, zone, payload, attachments, now)

    # --- front door --------------------------------------------------------------------------------------------------
    def _front_door(self, cur, state, workspace_id, conversation_id, member, text, page, modality) -> dict:
        from ..site_agent import classifier
        if conversation_id:
            pending = self._pending_choice(cur, workspace_id, conversation_id)
            if pending and any(c.get("type") == "proposal" for c in pending["candidates"] if isinstance(c, dict)):
                # Choosing which proposal to apply needs an explicit position ("the second one", "2", "第二個"); word overlap
                # with a proposal's summary never selects one (an unrelated follow-up must not apply anything).
                chosen = self._ordinal_choice(pending, text)
                if chosen and chosen.get("type") == "proposal":
                    return {"mode": "choose", "proposalId": chosen["id"], "decision": pending.get("decision", "apply")}
            if approvals.is_cancel_request(text) and member.allows("edit"):
                # Stopping work changes it, so it needs edit (a viewer's "cancel that" goes to the site agent, which changes nothing).
                return {"mode": "cancel"}
            if approvals.is_confirmation(text) or approvals.is_rejection(text):
                bound = approvals.bind(cur, workspace_id, conversation_id, self.clock())
                if "none" not in bound:
                    return {"mode": "confirm" if approvals.is_confirmation(text) else "reject", "bound": bound}
        if not self.cfg.enabled("RAFII_AGENT_V2_ENABLED"):
            return {"mode": "fallback", "reason": "runtime_off"}
        if not member.allows("edit"):
            return {"mode": "fallback", "reason": "role_grounded"}
        if self.model_factory is None and not self.cfg.route("standard_reasoning", reason="turn").available:
            return {"mode": "fallback", "reason": "no_model_route"}
        reading = classifier.classify(text, page)
        if reading.get("intent") in ("forbidden", "greeting"):
            # The site agent refuses (with the page where a person does it) and greets deterministically, at no model cost.
            return {"mode": "fallback", "reason": reading["intent"]}
        return {"mode": "manager", "reading": {"intent": reading.get("intent"), "language": reading.get("language")}}

    def _ordinal_choice(self, pending, text):
        site = self.service.site_agent
        if not pending or len(text) > 40:
            return None
        match = site._CHOICE.search(text)
        if not match:
            return None
        options = [c for c in pending["candidates"] if isinstance(c, dict) and c.get("type") and c.get("id")]
        index = site._CHOICE_INDEX.get((match.group(1) or match.group(2) or "").lower())
        return options[index] if index is not None and -len(options) <= index < len(options) else None

    def _pending_choice(self, cur, workspace_id, conversation_id):
        cur.execute("SELECT body->'siteAgent'->'pending' FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND role='assistant' ORDER BY seq DESC LIMIT 1",
                    (conversation_id, workspace_id))
        row = cur.fetchone()
        pending = row[0] if row else None
        return pending if isinstance(pending, dict) and isinstance(pending.get("candidates"), list) and pending["candidates"] else None

    def _attach(self, cur, state, workspace_id, conversation_id, principal, attachments_in, member) -> list[dict]:
        """Images sent with the turn must be this workspace's assets; each is recorded once on the conversation."""
        if not attachments_in:
            return []
        if not member.allows("edit"):
            raise AlphaError("Your role can't attach images.", 403)
        assets = {a.get("id"): a for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and not a.get("deleted")}
        out = []
        for item in attachments_in:
            asset = assets.get(item["assetId"])
            if asset is None:
                raise AlphaError("That image is not in this workspace.", 404)
            cur.execute("SELECT 1 FROM public.pr_attachments WHERE conversation_id::text=%s AND workspace_id=%s AND kind='asset' AND ref->>'assetId'=%s", (conversation_id, workspace_id, asset["id"]))
            if not cur.fetchone():
                cur.execute("INSERT INTO public.pr_attachments(conversation_id,workspace_id,kind,ref,created_by) VALUES(%s,%s,'asset',%s::jsonb,%s)",
                            (conversation_id, workspace_id, json.dumps({"assetId": asset["id"], "hash": asset["hash"], "mime": asset.get("mime"), "addedAt": self.clock()}), principal))
            out.append({"assetId": asset["id"], "hash": asset["hash"], "mime": asset.get("mime"), "width": asset.get("width"), "height": asset.get("height")})
        return out

    def _new_conversation(self, workspace_id, token, text) -> str:
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
            title = clean(text.splitlines()[0][:80], 200) or "Question for Rafii"
            cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text", (workspace_id, principal, title))
            return cur.fetchone()[0]

    # --- fallback: the verified site agent ------------------------------------------------------------------------------
    def _fallback(self, workspace_id, token, payload, text, modality, trace_id, *, reason=None) -> dict:
        site_payload = {"message": text, "idempotencyKey": clean(payload.get("idempotencyKey", ""), 100) or uid(), "timeZone": payload.get("timeZone"),
                        **{k: payload[k] for k in ("conversationId", "pageContext", "model") if payload.get(k) is not None}}
        site = self.service.site_agent
        result = site.turn(workspace_id, token, site_payload)
        if result.get("needsCompose") and result.get("runId") and modality == "voice":
            # Voice can't wait for a separate compose call from the browser; finish it here (same checks, same ledger).
            result = site.compose(workspace_id, token, result["runId"])
        message = result.get("message") or {}
        answer = message.get("text") or ""
        out = contracts.empty_result(trace_id, modality)
        out.update({"answerText": answer, "speakableSummary": contracts.speakable(answer) or ("I've started that; it will appear in the panel." if result.get("delegated") else ""),
                    "blocks": ((message.get("siteAgent") or {}).get("blocks") or []), "composedBy": "site_agent",
                    "references": ((message.get("siteAgent") or {}).get("refs") or []), "citations": ((message.get("siteAgent") or {}).get("citations") or []),
                    "pendingApprovals": [{"proposalId": p.get("id"), "messageId": result.get("messageId"), "type": p.get("type"), "summary": p.get("summary"),
                                          "digest": p.get("digest"), "expiresAt": p.get("expiresAt")} for p in ((message.get("siteAgent") or {}).get("proposals") or [])
                                         if p.get("status") == "proposed"]})
        if reason in ("no_model_route", "runtime_off") and modality == "voice":
            out["warnings"].append({"code": reason, "message": "Rafii's agent runtime isn't available here, so this answer comes from Rafii's help and your workspace."})
        return {"conversationId": result.get("conversationId"), "runId": result.get("runId"), "messageId": result.get("messageId"), "status": result.get("status"),
                "delegated": bool(result.get("delegated")), "fallback": reason, "siteAgent": result, "result": out}

    # --- approvals by conversation ----------------------------------------------------------------------------------------
    def _decide_turn(self, workspace_id, token, conversation_id, text, modality, run_key, trace_id, decision, zone, attachments) -> dict:
        ledger_notes, outcome_blocks = [], []
        from ..site_agent import contracts as site_contracts
        run_id, _ = self._open_run(workspace_id, token, conversation_id, text, modality, run_key, trace_id, attachments, model="rafii-approvals")
        result = contracts.empty_result(trace_id, modality)
        result["composedBy"] = "deterministic"
        if decision["mode"] == "choose":
            with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
                found = approvals.find(cur, workspace_id, conversation_id, decision["proposalId"])
            target = {"bind": {**found, "proposalId": decision["proposalId"], "digest": (found or {}).get("proposal", {}).get("digest")}} if found else {"none": "gone"}
            wants = decision.get("decision", "apply")
        else:
            target = decision["bound"]
            wants = "apply" if decision["mode"] == "confirm" else "dismiss"
        if "ask" in target:
            options = ["the first one", "the second one", "the third one", "the fourth one", "the fifth one"][:len(target["candidates"])]
            answer = target["ask"]
            outcome_blocks = [site_contracts.question(answer, options if len(target["candidates"]) > 1 else ["Yes, apply it", "No, leave it"])]
            if len(target["candidates"]) > 1:
                from ..site_agent.compose_reads import result_list
                outcome_blocks.append(result_list("Waiting for you", [{"kind": "proposal", "title": f"{i + 1}. {c['title']}", "excerpt": None, "meta": None, "href": None}
                                                                    for i, c in enumerate(target["candidates"])]))
            pending = {"request": "apply", "decision": wants, "candidates": target["candidates"]} if len(target["candidates"]) > 1 else None
            result.update({"answerText": answer, "speakableSummary": contracts.speakable(answer)})
            # Restating one proposal presents it again: the next "yes" (within the window) binds to it instead of asking forever.
            presents = {"proposalIds": [target["restate"]["proposalId"]], "at": self.clock()} if target.get("restate") else None
            return self._finish_simple(workspace_id, token, conversation_id, run_id, trace_id, result, outcome_blocks, pending=pending,
                                       site_extra={"presents": presents} if presents else None)
        if "none" in target:
            answer = "That proposal is no longer open, so nothing was changed."
            result.update({"answerText": answer, "speakableSummary": answer})
            return self._finish_simple(workspace_id, token, conversation_id, run_id, trace_id, result, [site_contracts.text(answer)])
        item = target["bind"]
        proposal = item.get("proposal") or {}
        try:
            decided = approvals.decide(self.service, workspace_id, token, conversation_id=conversation_id, message_id=item["messageId"], proposal_id=item["proposalId"],
                                       digest=proposal.get("digest") or item.get("digest"), decision=wants, zone=zone)
        except AlphaError as error:
            answer = f"I didn't apply it: {error}"
            result.update({"answerText": answer, "speakableSummary": contracts.speakable(answer), "errors": [{"code": error.code or "not_applied", "message": str(error)}]})
            # The proposal didn't change (a role, plan gate or staleness refusal), so a step waiting on it keeps waiting: someone
            # who may apply it can still do so, and the step follows the stored proposal (_sync_task). It is still open, so this
            # answer presents it again.
            return self._finish_simple(workspace_id, token, conversation_id, run_id, trace_id, result, [site_contracts.warning(answer, error.code or "not_applied")],
                                       site_extra={"presents": {"proposalIds": [item["proposalId"]], "at": self.clock()}})
        summary = "; ".join(proposal.get("summary") or [])[:300]
        if decided["outcome"] == "applied" and decided["verified"]:
            answer = f"Done and checked: {summary}." + (" The post now waits for approval of that exact post before it can publish." if proposal.get("type") in ("schedule_draft", "reschedule_post") else "")
            spoken = "Done, and I checked it in your workspace. " + ("It now waits for approval before it can publish." if proposal.get("type") in ("schedule_draft", "reschedule_post") else "")
            result["changedEntities"] = [{"type": "proposal", "id": item["proposalId"], "change": "applied", "verified": True, "checks": decided["checks"]}]
        elif decided["outcome"] == "applied":
            answer = f"I applied it, but re-reading the workspace didn't match everything I expected ({', '.join(c['what'] for c in decided['checks'] if not c['verified'])}). Please check it."
            spoken = "I applied it, but the check didn't fully match. Please look at the panel."
            result["changedEntities"] = [{"type": "proposal", "id": item["proposalId"], "change": "applied", "verified": False, "checks": decided["checks"]}]
        else:
            answer = f"Left it: {summary}. Nothing was changed." if wants == "dismiss" else f"It wasn't applied (it is {decided['outcome']}). Nothing was changed."
            spoken = answer
        # A Manager run paused on this proposal is taken off its task first: resolving the step may finish the task, and a
        # finished task keeps no paused model state.
        claimed = self._claim_pending_run(workspace_id, token, conversation_id, item["proposalId"]) if decided["outcome"] == "applied" else None
        self._resolve_task_steps(workspace_id, token, conversation_id, item["proposalId"], decided["outcome"] if wants == "apply" else "dismissed",
                                 verified=decided["verified"], outputs=[{"type": "review", "id": (decided.get("result") or {}).get("reviewId")}] if (decided.get("result") or {}).get("reviewId") else [])
        result.update({"answerText": answer, "speakableSummary": contracts.speakable(spoken)})
        blocks = [site_contracts.text(answer)]
        if decided.get("proposal"):
            blocks.append({"type": "proposal_diff", "proposal": decided["proposal"]})
        # How long the approval waited, from when Rafii presented it to the person's decision (§30).
        waited = round(self.clock() - float(proposal.get("createdAt") or self.clock()), 1)
        approval_trace = {"approval": {"proposalId": item["proposalId"], "decision": wants, "outcome": decided["outcome"], "verified": decided["verified"],
                                       "waitSeconds": waited, "via": modality, "checks": [c["what"] for c in decided["checks"] if not c["verified"]]}}
        if claimed is not None:
            resumed = self._resume_pending_run(workspace_id, token, conversation_id, item["proposalId"], claimed, run_id=run_id, trace_id=trace_id, modality=modality,
                                               zone=zone, approved=result["changedEntities"])
            if resumed is not None:
                return resumed
        return self._finish_simple(workspace_id, token, conversation_id, run_id, trace_id, result, blocks, trace_extra=approval_trace)

    def _resolve_task_steps(self, workspace_id, token, conversation_id, proposal_id, outcome, *, verified, outputs=(), reason=None):
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            plan = task_state.active(cur, workspace_id, conversation_id)
            if plan is None:
                return
            touched = plan.resolve_approval(proposal_id, outcome, self.clock(), verified=verified, outputs=[o for o in outputs if o.get("id")], reason=reason)
            if touched:
                task_state.save(cur, self.service.ideas, workspace_id, plan)

    # --- cancellation (Live has no cancel command; the backend owns it) -----------------------------------------------
    def _cancel_turn(self, workspace_id, token, conversation_id, text, modality, run_key, trace_id) -> dict:
        from ..site_agent import contracts as site_contracts
        cancelled_runs = self.cancel_running(workspace_id, token, conversation_id, reason="You asked to cancel.")
        steps = []
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
            plan = task_state.active(cur, workspace_id, conversation_id)
            cur.execute("SELECT actor::text FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", ((plan.task_id if plan else None), workspace_id))
            owner = (cur.fetchone() or [None])[0]
            if plan is not None and owner == principal:
                # Only the task's own person cancels its open steps.
                steps = plan.cancel_open("You asked to cancel.", self.clock())
                if steps:
                    task_state.save(cur, self.service.ideas, workspace_id, plan)
            bound = approvals.bind(cur, workspace_id, conversation_id, self.clock())
        dismissed, not_dismissed = None, None
        if "bind" in bound:
            item = bound["bind"]
            try:
                decided = approvals.decide(self.service, workspace_id, token, conversation_id=conversation_id, message_id=item["messageId"], proposal_id=item["proposalId"],
                                           digest=item["proposal"].get("digest"), decision="dismiss")
                dismissed = decided["outcome"]
            except AlphaError as error:
                not_dismissed = str(error)
        # Confirm by re-reading before saying it (live-delegation guidance: "confirm it succeeded before telling the user").
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            still = [r for r in cancelled_runs if self._run_status(cur, workspace_id, r) == "running"]
        parts = []
        if cancelled_runs:
            parts.append(f"Stopped {len(cancelled_runs) - len(still)} request(s) that were still running" + (f" ({len(still)} could not be stopped)" if still else "") + ".")
        if steps:
            parts.append(f"Cancelled {len(steps)} open step(s): " + "; ".join(s.label for s in steps)[:200] + ".")
        if dismissed:
            parts.append("Left the proposal unapplied.")
        if not_dismissed:
            parts.append(f"The waiting proposal is still open ({not_dismissed[:160]}); nothing was applied.")
        if not parts:
            parts.append("There was nothing running to cancel.")
        parts.append("Anything already finished stays as it is; nothing more was changed.")
        answer = " ".join(parts)
        run_id, _ = self._open_run(workspace_id, token, conversation_id, text, modality, run_key, trace_id, [], model="rafii-cancel")
        result = contracts.empty_result(trace_id, modality)
        result.update({"answerText": answer, "speakableSummary": contracts.speakable(answer), "composedBy": "deterministic"})
        return self._finish_simple(workspace_id, token, conversation_id, run_id, trace_id, result, [site_contracts.text(answer)])

    def cancel_running(self, workspace_id, token, conversation_id, *, reason, exclude=None, only=None) -> list[str]:
        """Stop this member's own running agent turns in the conversation (never another member's)."""
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND conversation_id::text=%s AND idempotency_key LIKE 'agent:%%' AND status='running' "
                        "AND actor=%s", (workspace_id, conversation_id, principal))
            ids = [r[0] for r in cur.fetchall() if r[0] != exclude and (only is None or r[0] in only)]
            for run_id in ids:
                self.service.ideas._insert_event(cur, workspace_id, run_id, safe_event("run.cancelled", message=reason))
                cur.execute("UPDATE public.pr_agent_runs SET status='cancelled',updated_at=now() WHERE id::text=%s AND status='running'", (run_id,))
        return ids

    def cancel(self, workspace_id, token, run_id) -> dict:
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self.service.ideas._member(row), "edit")
            cur.execute("SELECT status,conversation_id::text,idempotency_key,actor::text FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (run_id, workspace_id))
            found = cur.fetchone()
            if not found or not str(found[2]).startswith(KEY_PREFIX) or found[3] != principal:
                # Only the person who asked stops their request (the same answer as a missing one).
                raise AlphaError("Run unavailable.", 404)
            if found[0] != "running":
                return {"runId": run_id, "status": found[0], "note": "Already finished; nothing to stop."}
            self.service.ideas._insert_event(cur, workspace_id, run_id, safe_event("run.cancelled", message="Stopped. Anything already finished stays as it is."))
            cur.execute("UPDATE public.pr_agent_runs SET status='cancelled',updated_at=now() WHERE id::text=%s", (run_id,))
        return {"runId": run_id, "status": "cancelled"}

    @staticmethod
    def _run_status(cur, workspace_id, run_id):
        cur.execute("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        row = cur.fetchone()
        return row[0] if row else None

    # --- the Manager ------------------------------------------------------------------------------------------------------
    def _manager_turn(self, workspace_id, token, conversation_id, text, modality, run_key, trace_id, page, zone, payload, attachments, now) -> dict:
        _ = now
        superseded = []
        if modality == "voice" or payload.get("supersede"):
            superseded = self._supersede(workspace_id, token, conversation_id)
        workload, why = runtime_config.choose_reasoning(text, modality=modality, attachments=len(attachments), steps_hint=text.count(",") + text.count(" then ") + text.count(" and "))
        try:
            run_id, reservation = self._open_run(workspace_id, token, conversation_id, text, modality, run_key, trace_id, attachments, model=AGENT_MODEL, reserve_for=workload,
                                                 delegation_id=payload.get("delegationId"), live_session=payload.get("voiceSessionId"))
        except AlphaError as error:
            if error.status in (402, 403, 409, 429, 503) and error.code != "workspace_revision_conflict":
                # Out of budget or allowance, or no verified price: no model call, and no other paid route (spec §21, §36).
                return self._fallback(workspace_id, token, {**payload, "conversationId": conversation_id}, text, modality, trace_id, reason="budget")
            raise
        holder: dict = {}
        try:
            return self._run_manager(workspace_id, token, conversation_id, text, modality, trace_id, page, zone, payload, attachments, run_id, reservation,
                                     workload, why, superseded, holder)
        except Exception as error:  # noqa: BLE001 — whatever failed after the run opened, it ends settled and closed
            return self._abort_run(workspace_id, token, conversation_id, run_id, reservation, trace_id, modality, error, holder.get("ctx"))

    def _run_manager(self, workspace_id, token, conversation_id, text, modality, trace_id, page, zone, payload, attachments, run_id, reservation,
                     workload, why, superseded, holder) -> dict:
        from agents import RunConfig, Runner
        from agents.exceptions import InputGuardrailTripwireTriggered, MaxTurnsExceeded, OutputGuardrailTripwireTriggered

        from . import manager as manager_mod

        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = self.service.ideas._member(row)
            state = self.service.ideas._state(row)
            focus, refs_note = self._resolve(cur, state, workspace_id, conversation_id, text, page)
            plan = task_state.active(cur, workspace_id, conversation_id)
            images = creative.conversation_images(cur, state, workspace_id, conversation_id)
            if plan is not None and _sync_task(self, cur, workspace_id, plan, state):
                task_state.save(cur, self.service.ideas, workspace_id, plan)
                plan = plan if plan.status == "running" else None
            last = task_state.latest(cur, workspace_id, conversation_id) if plan is None else None
            open_items = approvals.open_proposals(cur, workspace_id, conversation_id, self.clock())
            history = self._history(cur, workspace_id, conversation_id)
            from .live import recent_transcript
            spoken = recent_transcript(cur, workspace_id, conversation_id)
        ctx = RafiiRunContext(service=self.service, workspace_id=workspace_id, token=token, principal=principal, membership=member, conversation_id=conversation_id,
                              trace_id=trace_id, modality=modality, page=page, zone=zone, locale=payload.get("locale") if isinstance(payload.get("locale"), str) else None,
                              writer_model=payload.get("model") if isinstance(payload.get("model"), str) and payload.get("model") else None, attachments=attachments,
                              conversation_assets=images, focus=focus, task=plan, run_id=run_id, now=self.clock, config=self.cfg, image_studio=self.image_studio,
                              vision=self.vision, request_text=text, page_raw=payload.get("pageContext") if isinstance(payload.get("pageContext"), dict) else None)
        ctx.cancelled = lambda: self._is_cancelled(workspace_id, token, run_id)
        ctx.deadline = time.monotonic() + TURN_BUDGET_SECONDS
        holder["ctx"] = ctx
        items = self._assemble(ctx, text, history, refs_note, open_items, images, superseded, spoken, last)
        manager, routes = manager_mod.build(ctx, model_factory=self.model_factory, workload=workload)
        collector = manager_mod.collector(self.cfg)
        run_config = RunConfig(workflow_name="rafii.turn", trace_id=trace_id, group_id=conversation_id, trace_metadata={"modality": modality, "runtime": RUNTIME_VERSION},
                               trace_include_sensitive_data=False)
        reply, note, fallback_reason, interruptions, state_json = None, None, None, [], None
        started = time.monotonic()
        try:
            result = asyncio.run(asyncio.wait_for(Runner.run(manager, items, context=ctx, max_turns=14, run_config=run_config), timeout=TURN_BUDGET_SECONDS))
            interruptions = list(result.interruptions or [])
            if interruptions:
                # The paused run is kept server-side with identifiers only — never the session token (§13, SDK HITL).
                state_json = result.to_state().to_json(context_serializer=lambda c: {"conversationId": c.conversation_id, "traceId": c.trace_id, "runId": c.run_id})
                waiting = set()
                for item in interruptions:
                    try:
                        waiting.add(json.loads(getattr(item, "arguments", "") or "{}").get("proposalId"))
                    except ValueError:
                        pass
                named = [answer_policy.spoken_proposal(o["proposal"]) for o in open_items if o["proposalId"] in waiting]
                if named:
                    # Said in the application's words (the stored proposal), so a spoken "yes" is to exactly this.
                    note = f"This waits for your decision: {named[0]}. Say yes to apply it, or no to leave it."
            else:
                reply = result.final_output
        except OutputGuardrailTripwireTriggered:
            fallback_reason = "guardrail_output"
        except InputGuardrailTripwireTriggered:
            fallback_reason = "guardrail_input"
            note = "I can't do that from a chat. Those actions stay on their own pages, with their own confirmation."
        except MaxTurnsExceeded:
            fallback_reason = "max_turns"
            note = "This took more steps than I allow in one turn, so I stopped. Here is exactly where things stand."
        except asyncio.TimeoutError:
            fallback_reason = "timeout"
            note = "This took longer than one turn allows, so I stopped. Here is exactly where things stand."
        except AlphaError as error:
            fallback_reason = error.code or "error"
            note = "You cancelled this, so I stopped. Here is what had already finished." if error.code == "run_cancelled" else f"I stopped: {error}"
        except Exception as error:  # noqa: BLE001 — a model or provider failure never becomes a success claim
            log.error(json.dumps({"event": "agent_turn.failed", "errorClass": type(error).__name__, "traceId": trace_id}))
            fallback_reason = "model_error"
            note = "Rafii's reasoning model didn't answer, so nothing more was done. Here is exactly where things stand."
        elapsed = round((time.monotonic() - started) * 1000)
        spans = collector.take(trace_id)
        return self._finalize(ctx, run_id, reservation, reply=reply, note=note, fallback_reason=fallback_reason, interruptions=interruptions, state_json=state_json,
                              routes=routes, workload=workload, why=why, spans=spans, elapsed_ms=elapsed, superseded=superseded)

    def _supersede(self, workspace_id, token, conversation_id) -> list[dict]:
        """A new spoken request while an earlier one still runs: the earlier one stops before its next change (voice refinement)."""
        # Only this member's earlier spoken requests: a typed turn still running is not a voice refinement.
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute("SELECT r.id::text,(SELECT m.body->>'text' FROM public.pr_messages m WHERE m.run_id=r.id AND m.role='user' LIMIT 1) FROM public.pr_agent_runs r "
                        "WHERE r.workspace_id=%s AND r.conversation_id::text=%s AND r.idempotency_key LIKE 'agent:%%' AND r.status='running' AND r.actor=%s "
                        "AND r.created_at>now()-make_interval(secs=>%s) AND EXISTS (SELECT 1 FROM public.pr_messages m WHERE m.run_id=r.id AND m.role='user' "
                        "AND m.body->'agent'->>'modality'='voice')", (workspace_id, conversation_id, principal, SUPERSEDE_WINDOW_SECONDS))
            rows = cur.fetchall()
        if not rows:
            return []
        self.cancel_running(workspace_id, token, conversation_id, reason="Superseded by a newer request.", only={r[0] for r in rows})
        return [{"runId": r[0], "request": (r[1] or "")[:500]} for r in rows]

    def _is_cancelled(self, workspace_id, token, run_id) -> bool:
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            return self._run_status(cur, workspace_id, run_id) != "running"

    def _resolve(self, cur, state, workspace_id, conversation_id, text, page):
        """Deterministic references before any model reasoning (spec §3.5): the page item, "that draft", ordinals, "the second image"."""
        from ..site_agent import references
        cur.execute("SELECT body->'siteAgent'->'refs' FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND role='assistant' AND body ? 'siteAgent' ORDER BY seq DESC LIMIT 4",
                    (conversation_id, workspace_id))
        history = [refs for (refs,) in cur.fetchall() if isinstance(refs, list)]
        resolved = references.resolve(text, page.get("selectedEntity"), history)
        notes = []
        if resolved.get("entity"):
            notes.append({"phrase": "this/that/ordinal reference", "resolvedTo": resolved["entity"], "source": resolved.get("source")})
        elif resolved.get("ambiguous"):
            notes.append({"phrase": "ambiguous reference", "candidates": resolved.get("candidates")})
        match = _IMAGE_ORDINAL.search(text)
        if match:
            from .creative import conversation_images
            images = conversation_images(cur, state, workspace_id, conversation_id)
            index = _ORDINALS.get((match.group(1) or match.group(2) or "").lower())
            if index is not None and images and -len(images) <= index <= len(images) and index != 0:
                chosen = images[index - 1] if index > 0 else images[index]
                notes.append({"phrase": match.group(0), "resolvedTo": {"type": "asset", "id": chosen["assetId"], "index": chosen["index"]}, "source": "conversation images"})
            else:
                notes.append({"phrase": match.group(0), "resolvedTo": None, "note": f"this conversation has {len(images)} image(s)"})
        return resolved.get("entity"), notes

    def _history(self, cur, workspace_id, conversation_id) -> list[dict]:
        cur.execute("SELECT role,body FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s ORDER BY seq DESC LIMIT %s", (conversation_id, workspace_id, HISTORY_MESSAGES))
        out = []
        for role, body in reversed(cur.fetchall()):
            if not isinstance(body, dict) or role not in ("user", "assistant"):
                continue
            words = (body.get("text") or "").strip()
            if not words:
                continue
            modality = (body.get("agent") or {}).get("modality")
            out.append({"role": role, "text": words[:1200], **({"modality": modality} if modality else {})})
        return out[:-1] if out and out[-1]["role"] == "user" else out

    def _assemble(self, ctx: RafiiRunContext, text, history, refs_note, open_items, images, superseded, spoken=(), last=None) -> list[dict]:
        """Bounded, labelled context (spec §15). Exact ids stay in machine context; every block says what kind of data it is."""
        from ..site_agent import contracts as site_contracts
        app_state = {"kind": "APP_STATE", "page": site_contracts.page_summary(ctx.page), "timeZone": ctx.zone, "now": site_contracts.iso(ctx.now()),
                     "modality": ctx.modality, "member": ctx.membership.summary(), "resolvedReferences": refs_note,
                     "activeTask": ctx.task.view() if ctx.task is not None else None,
                     "pendingApprovals": [{"proposalId": i["proposalId"], "type": i["type"], "summary": i["summary"]} for i in open_items][:5],
                     "conversationImages": [{"index": i["index"], "assetId": i["assetId"], "origin": i["origin"]} for i in images][-8:],
                     "attachedThisTurn": [a["assetId"] for a in ctx.attachments]}
        if superseded:
            app_state["supersededRequests"] = [s["request"] for s in superseded]
        if spoken:
            app_state["recentVoiceTranscript"] = list(spoken)
        if last is not None:
            app_state["lastTask"] = last.view()
        for asset_id in app_state["attachedThisTurn"]:
            ctx.ledger.known_ids.add(asset_id.lower())
        for item in images:
            ctx.ledger.known_ids.add(item["assetId"].lower())
        entity = (ctx.page or {}).get("selectedEntity") or {}
        if entity.get("id"):
            ctx.ledger.known_ids.add(str(entity["id"]).lower())
        items = [{"role": h["role"], "content": ("[spoken] " if h.get("modality") == "voice" else "") + h["text"]} for h in history]
        context_json = json.dumps(app_state, ensure_ascii=False, default=str)
        items.append({"role": "user", "content": f"<context kind=\"APP_STATE\">\n{context_json}\n</context>\n<request kind=\"USER_INSTRUCTION\" modality=\"{ctx.modality}\">\n{text}\n</request>"})
        return items

    # --- runs, messages, finalisation ---------------------------------------------------------------------------------------
    def _open_run(self, workspace_id, token, conversation_id, text, modality, run_key, trace_id, attachments, *, model, reserve_for=None, delegation_id=None, live_session=None):
        """Insert the run and the person's message; reserve the Manager's estimated cost (a refusal is a truthful budget stop)."""
        repo, ideas = self.service.repository, self.service.ideas
        reservation = None
        if reserve_for and self.model_factory is None:
            # Specialists run on the fast model and images are read by the vision model: an unpriced route would leave the
            # turn's spend unknown, so the turn doesn't start (the budget fallback answers instead).
            for load in ("fast_language", "vision"):
                route = self.cfg.route(load, reason="price check")
                if route.available and self.cfg.estimate_usd_micro(route.model or "", 1, 1) is None:
                    raise AlphaError(f"Configure a verified price for {route.model} before using the agent runtime.", 503, code="price_unknown")
        with repo.transaction(token, workspace_id) as (cur, _row, _principal):
            # Its own transaction: closing dead turns must not depend on this turn's reservation being accepted.
            self._reap_stale_turns(cur, workspace_id)
        with repo.transaction(token, workspace_id) as (cur, _row, principal):
            context = {"trace": trace_id, "modality": modality, "attachments": [a["assetId"] for a in attachments]}
            cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key) "
                        "VALUES(%s,%s,%s,'running',%s,%s,%s,%s,%s) RETURNING id::text",
                        (conversation_id, workspace_id, principal, model, "deep" if reserve_for == "deep_reasoning" else "standard", digest(context), EPOCH, run_key))
            run_id = cur.fetchone()[0]
            body = {"text": text, "agent": {"modality": modality, "attachments": [a["assetId"] for a in attachments], "traceId": trace_id,
                                            **({"delegationId": str(delegation_id)[:120]} if delegation_id else {}), **({"voiceSessionId": str(live_session)[:80]} if live_session else {})},
                    "siteAgent": {"role": "question", "runId": run_id}}
            ideas._append_message(cur, workspace_id, conversation_id, "user", body, run_id)
            ideas._insert_event(cur, workspace_id, run_id, safe_event("run.started", agent="rafii", model=model, traceId=trace_id, modality=modality))
            if reserve_for and self.model_factory is None:
                route = self.cfg.route(reserve_for, reason="reservation")
                estimate = self.cfg.estimate_usd_micro(route.model or "", 24_000, 4_000)
                if estimate is None:
                    raise AlphaError("Configure verified prices for the agent model before using it.", 503, code="price_unknown")
                reservation = self.service.ledger.reserve(cur, workspace_id, principal, "text_model", estimate, f"agent:{run_id}", charge_batch=False,
                                                          provider=route.provider or "", model=route.model or "", run_id=run_id, meta={"via": "rafii_agent", "traceId": trace_id})
        return run_id, reservation

    def _finish_simple(self, workspace_id, token, conversation_id, run_id, trace_id, result, blocks, *, pending=None, trace_extra=None, site_extra=None) -> dict:
        from ..site_agent import contracts as site_contracts
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            self._persist(cur, workspace_id, conversation_id, run_id, result, blocks, [], [], trace={"traceId": trace_id, "composedBy": result["composedBy"], **(trace_extra or {})}, pending=pending,
                          status="completed", usage={"provenance": "deterministic", "modelRequests": 0}, site_extra=site_extra)
            out = self._stored(cur, workspace_id, run_id)
        _ = site_contracts
        return out

    def _finalize(self, ctx: RafiiRunContext, run_id, reservation, *, reply, note, fallback_reason, interruptions, state_json, routes, workload, why, spans, elapsed_ms, superseded):
        from ..site_agent import contracts as site_contracts
        ledger = ctx.ledger
        result = contracts.empty_result(ctx.trace_id, ctx.modality)
        composed_by, reason = "manager", None
        if reply is not None:
            answer_text = getattr(reply, "answer", None) if not isinstance(reply, str) else reply
            spoken = getattr(reply, "speakable", "") if not isinstance(reply, str) else ""
            reason = answer_policy.check(answer_text or "", ledger) or (answer_policy.check(spoken, ledger) if spoken else None)
            if reason is None:
                answer = answer_policy.clean(answer_text)
                speakable = contracts.speakable(spoken or answer)
                if ledger.proposals:
                    # What a spoken "yes" would apply is said in the application's words (the stored proposal), not only the model's.
                    speakable = answer_policy.compose(ledger, ctx.task)[1]
                result["followUps"] = [f for f in (contracts.trim(item, 120) for item in (getattr(reply, "follow_ups", None) or [])) if f][:3]
                result["language"] = getattr(reply, "language", None)
        if reply is None or reason is not None:
            composed_by = "deterministic"
            if interruptions:
                note = note or "A proposal is waiting for your decision before I can continue."
            answer, speakable = answer_policy.compose(ledger, ctx.task, note=note)
            reason = reason or fallback_reason
        blocks = [site_contracts.text(answer)]
        for proposal in ledger.proposals:
            from ..site_agent import proposals as site_proposals
            blocks.append({"type": "proposal_diff", "proposal": site_proposals.view(proposal, self.clock())})
        if ctx.task is not None and ctx.task.steps:
            from ..site_agent.compose_reads import result_list
            blocks.append(result_list("Steps", [{"kind": s.state, "title": s.label, "excerpt": s.reason, "meta": s.state.replace("_", " "), "href": None} for s in ctx.task.steps]))
        blocks.extend(evidence_blocks(ledger, ctx.request_text, result.get("language")))
        blocks.extend(ledger.navigation[:2])
        if ledger.citations:
            blocks.append(site_contracts.citations(ledger.citations[:4]))
        for warning in ledger.warnings[:3]:
            blocks.append(site_contracts.warning(warning["message"], warning["code"]))
        if reason and composed_by == "deterministic":
            blocks.append(site_contracts.warning("I've shown only what the workspace confirms.", f"agent_{reason}"))
        usage_tokens = {"inputTokens": sum(s.get("inputTokens", 0) for s in ledger.spans), "outputTokens": sum(s.get("outputTokens", 0) for s in ledger.spans)}
        manager_route = next((r for r in routes if r.get("agent") == "rafii_manager"), {})
        cost = self._spend(ledger, manager_route.get("model")) if self.model_factory is None else None
        result.update({"answerText": answer, "speakableSummary": speakable, "composedBy": composed_by, "references": ledger.references[:20], "citations": ledger.citations[:4],
                       "facts": ledger.facts[:20], "toolActivity": ledger.tool_activity[:40], "task": ctx.task.view() if ctx.task is not None else None,
                       "changedEntities": ledger.changed[:20], "generatedAssets": ledger.assets[:8], "warnings": ledger.warnings[:6], "errors": ledger.errors[:6],
                       "routes": routes, "usage": {"modelRequests": ledger.model_requests, **usage_tokens, "costUsdMicro": cost, "route": manager_route.get("model"),
                                                   "billing": "metered" if reservation else ("scripted" if self.model_factory else None)}})
        trace = {"traceId": ctx.trace_id, "runtime": RUNTIME_VERSION, "workload": workload, "why": why, "routes": routes, "composedBy": composed_by, "fallback": reason,
                 "tools": [{k: a.get(k) for k in ("tool", "effect", "status", "latencyMs", "code", "specialist")} for a in ledger.tool_activity][:60],
                 "specialists": sorted({a["specialist"] for a in ledger.tool_activity if a.get("specialist")}), "guardrails": ledger.guardrail_trips,
                 "generations": ledger.spans[:40], "sdkSpans": spans[:120], "elapsedMs": elapsed_ms, "superseded": [s["runId"] for s in superseded],
                 "interruptions": [{"tool": getattr(i, "name", None)} for i in interruptions][:5]}
        for hook in TRACE_HOOKS:
            try:
                extra = hook(ctx=ctx, routes=routes)
            except Exception:  # noqa: BLE001 — trace extensions never break a turn
                extra = {"traceHookError": getattr(hook, "__name__", "hook")}
            if isinstance(extra, dict):
                trace.update({k: v for k, v in extra.items() if k not in trace})
        with self.service.repository.transaction(ctx.token, ctx.workspace_id) as (cur, _row, _principal):
            status = self._run_status(cur, ctx.workspace_id, run_id)
            final_status = "cancelled" if status == "cancelled" else "completed"
            if reservation is not None:
                self.service.ledger.settle(cur, ctx.workspace_id, reservation["reservationId"], "completed" if cost is not None else "unknown", cost)
            if ctx.task is not None and ctx.task.changes:
                task_state.save(cur, self.service.ideas, ctx.workspace_id, ctx.task, trace_id=ctx.trace_id)
            if state_json is not None:
                if ctx.task is None:
                    ctx.task = task_state.create(cur, self.service.ideas, ctx.workspace_id, ctx.conversation_id, ctx.principal, "Waiting for your approval", ctx.trace_id)
                self._store_pending_run(cur, ctx.workspace_id, ctx.task.task_id, state_json, interruptions, writer_model=ctx.writer_model)
                for item in interruptions:
                    try:
                        args = json.loads(getattr(item, "arguments", "") or "{}")
                    except ValueError:
                        args = {}
                    ctx.ledger.interruptions.append({"tool": getattr(item, "name", None), "proposalId": args.get("proposalId")})
            # A run paused on proposal_apply presents that proposal: the person's next "yes" binds to it.
            waiting = [i["proposalId"] for i in ctx.ledger.interruptions if i.get("proposalId")]
            self._persist(cur, ctx.workspace_id, ctx.conversation_id, run_id, result, blocks, ledger.proposals, ledger.references, trace=trace, status=final_status,
                          usage={"provenance": composed_by, "modelRequests": ledger.model_requests, "costUsd": (cost / 1_000_000) if cost is not None else None,
                                 "billing": result["usage"]["billing"]}, language=result.get("language"), follow_ups=result.get("followUps") or [],
                          site_extra={"presents": {"proposalIds": waiting, "at": self.clock()}} if waiting else None)
            return self._stored(cur, ctx.workspace_id, run_id)

    def _persist(self, cur, workspace_id, conversation_id, run_id, result, blocks, proposals, refs, *, trace, status, usage, pending=None, language=None, follow_ups=(),
                 site_extra=None):
        ideas = self.service.ideas
        from ..site_agent import contracts as site_contracts
        site = {"version": site_contracts.VERSION, "runId": run_id, "status": "completed" if status != "cancelled" else "cancelled", "intent": "agent",
                "language": language, "blocks": blocks, "citations": result.get("citations") or [], "grounding": {"required": False, "sufficient": True, "missing": []},
                "proposals": proposals, "context": {"route": None, "entity": None, "read": [a["label"] for a in result.get("toolActivity") or [] if a.get("status") == "verified" and a.get("effect") == "READ"][:12],
                                                    "withheld": ["passwords, tokens and keys", "other workspaces"], "stale": False},
                # 'agent': the Manager phrased it (not the person's chosen writer), and phrasedBy names its model as the site agent's
                # answers do; 'grounded': composed from verified tool results only, so no model phrased it.
                "model": {"id": result.get("usage", {}).get("route"), "composedBy": "agent" if result["composedBy"] == "manager" else "grounded",
                          **({"phrasedBy": result["usage"]["route"]} if result["composedBy"] == "manager" and (result.get("usage") or {}).get("route") else {})},
                "followUps": list(follow_ups)[:3], "feedback": None, "refs": [r for r in refs if isinstance(r, dict) and r.get("id")][:12]}
        if pending:
            site["pending"] = pending
        site.update({k: v for k, v in (site_extra or {}).items() if k not in site})
        visible = {**result, "usage": {k: v for k, v in (result.get("usage") or {}).items() if k != "costUsdMicro"}}
        body = {"text": result["answerText"], "runId": run_id, "siteAgent": site, "agent": visible}
        message = ideas._append_message(cur, workspace_id, conversation_id, "assistant", body, run_id)
        result["pendingApprovals"] = [{"proposalId": p["id"], "messageId": message["messageId"], "type": p.get("type"), "summary": p.get("summary"), "digest": p.get("digest"),
                                       "expiresAt": p.get("expiresAt"), "requiredPermission": p.get("requiredPermission")} for p in proposals]
        body["agent"] = {**visible, "pendingApprovals": result["pendingApprovals"]}
        cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s", (json.dumps(body, ensure_ascii=False, default=str), message["messageId"]))
        for block in blocks[:10]:
            ideas._insert_event(cur, workspace_id, run_id, safe_event("artifact.created", artifact="site_agent.block", block=block))
        for proposal in proposals:
            ideas._insert_event(cur, workspace_id, run_id, safe_event("action.proposed", action=proposal["type"], proposalId=proposal["id"], status="proposed"))
        ideas._insert_event(cur, workspace_id, run_id, safe_event("message.completed", text=result["answerText"][:12000]))
        if status == "failed":
            ideas._insert_event(cur, workspace_id, run_id, safe_event("run.failed", message=(result.get("errors") or [{}])[0].get("message") or "The request stopped before it finished."))
        else:
            ideas._insert_event(cur, workspace_id, run_id, safe_event("run.completed" if status != "cancelled" else "run.cancelled",
                                                                      **({"usage": {k: usage.get(k) for k in ("provenance", "modelRequests", "costUsd", "billing")}} if status != "cancelled" else {"message": "Stopped."})))
        artifact = {"version": 1, "result": result, "trace": trace}
        cur.execute("UPDATE public.pr_agent_runs SET status=%s,artifact=%s::jsonb,artifact_hash=%s,usage=%s::jsonb,updated_at=now() WHERE id::text=%s",
                    (status, json.dumps(artifact, ensure_ascii=False, default=str), digest(json.loads(json.dumps(artifact, default=str))), json.dumps(usage, default=str), run_id))

    def _stored(self, cur, workspace_id, run_id) -> dict:
        cur.execute("SELECT status,conversation_id::text,artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Run unavailable.", 404)
        cur.execute("SELECT id::text FROM public.pr_messages WHERE run_id::text=%s AND workspace_id=%s AND role='assistant' ORDER BY seq DESC LIMIT 1", (run_id, workspace_id))
        message = cur.fetchone()
        artifact = row[2] or {}
        return {"conversationId": row[1], "runId": run_id, "status": row[0], "messageId": message[0] if message else None, "result": artifact.get("result"),
                "traceId": (artifact.get("trace") or {}).get("traceId")}

    def _spend(self, ledger, default_model) -> int | None:
        """This turn's model spend: each metered call priced at its own model (a specialist on the fast model is not billed at
        the Manager's price; vision calls count too). None when any call's model has no price."""
        total = 0
        for span in (ledger.spans if ledger is not None else []):
            price = self.cfg.estimate_usd_micro(span.get("model") or default_model or "", span.get("inputTokens") or 0, span.get("outputTokens") or 0)
            if price is None:
                return None
            total += price
        return total

    def _abort_run(self, workspace_id, token, conversation_id, run_id, reservation, trace_id, modality, error, ctx=None) -> dict:
        """Something failed after the run opened (a bug, the database, a reply that couldn't be stored). The run still ends:
        its spend is booked from the metered calls (released when no model was called), it is marked failed, and the
        person gets a plain account instead of a request that stays "running" forever."""
        from ..site_agent import contracts as site_contracts
        log.error(json.dumps({"event": "agent_turn.aborted", "errorClass": type(error).__name__, "traceId": trace_id}))
        ledger = ctx.ledger if ctx is not None else None
        answer = (f"I stopped: {error} Anything already finished stays as it is; nothing more was changed." if isinstance(error, AlphaError) and error.status < 500 else
                  "Something went wrong on Rafii's side before this finished, so I stopped. Anything already finished stays as it is; nothing more was changed.")
        result = contracts.empty_result(trace_id, modality)
        result.update({"answerText": answer, "speakableSummary": contracts.speakable(answer), "composedBy": "deterministic",
                       "errors": [{"code": "internal_error", "message": "The request stopped before it finished."}],
                       "changedEntities": (ledger.changed if ledger else [])[:20], "generatedAssets": (ledger.assets if ledger else [])[:8]})
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            if reservation is not None:
                spent = self._spend(ledger, None)
                if ledger is None or not ledger.spans:
                    self.service.ledger.settle(cur, workspace_id, reservation["reservationId"], "failed", 0)
                else:
                    self.service.ledger.settle(cur, workspace_id, reservation["reservationId"], "completed" if spent is not None else "unknown", spent)
            if self._run_status(cur, workspace_id, run_id) == "running":
                self._persist(cur, workspace_id, conversation_id, run_id, result, [site_contracts.warning(answer, "internal_error")], [], [],
                              trace={"traceId": trace_id, "composedBy": "deterministic", "fallback": "internal_error", "errorClass": type(error).__name__},
                              status="failed", usage={"provenance": "deterministic", "modelRequests": ledger.model_requests if ledger else 0})
            return self._stored(cur, workspace_id, run_id)

    def _reap_stale_turns(self, cur, workspace_id):
        """A turn whose function was killed never finalised. The writing-recovery cron leaves the runtime's rows alone, so the
        runtime closes its own dead turns here: each is failed, the person sees why, and its reservations are booked at the
        reserved amount (the calls it made are unknown; never free, and never held forever)."""
        # A turn cancelled after its function died never settled either: its open reservations are booked the same way.
        cur.execute("SELECT r.id::text,r.estimated_usd_micro FROM public.pr_usage_ledger r JOIN public.pr_agent_runs a ON a.id=r.run_id "
                    "WHERE r.workspace_id=%s AND a.idempotency_key LIKE 'agent:%%' AND a.status='cancelled' AND a.updated_at<now()-make_interval(secs=>%s) AND r.kind='reserve' "
                    "AND NOT EXISTS (SELECT 1 FROM public.pr_usage_ledger t WHERE t.workspace_id=r.workspace_id AND t.reservation_id=r.id AND t.kind IN ('settle','release')) LIMIT 20",
                    (workspace_id, STALE_TURN_SECONDS))
        for reservation_id, estimate in cur.fetchall():
            self.service.ledger.settle(cur, workspace_id, reservation_id, "completed", int(estimate or 0))
        cur.execute("SELECT id::text,conversation_id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key LIKE 'agent:%%' AND status='running' "
                    "AND updated_at<now()-make_interval(secs=>%s) ORDER BY created_at LIMIT 10 FOR UPDATE SKIP LOCKED", (workspace_id, STALE_TURN_SECONDS))
        for run_id, conversation_id in cur.fetchall():
            cur.execute("SELECT r.id::text,r.estimated_usd_micro FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.run_id::text=%s AND r.kind='reserve' "
                        "AND NOT EXISTS (SELECT 1 FROM public.pr_usage_ledger t WHERE t.workspace_id=r.workspace_id AND t.reservation_id=r.id AND t.kind IN ('settle','release'))",
                        (workspace_id, run_id))
            for reservation_id, estimate in cur.fetchall():
                self.service.ledger.settle(cur, workspace_id, reservation_id, "completed", int(estimate or 0))
            answer = "This request stopped before it finished (the server ran out of time). Anything already finished stays as it is; please ask again."
            result = contracts.empty_result(contracts.new_trace_id(), "text")
            result.update({"answerText": answer, "speakableSummary": contracts.speakable(answer), "composedBy": "deterministic",
                           "errors": [{"code": "turn_stalled", "message": "The request stopped before it finished."}]})
            from ..site_agent import contracts as site_contracts
            self._persist(cur, workspace_id, conversation_id, run_id, result, [site_contracts.warning(answer, "turn_stalled")], [], [],
                          trace={"traceId": result["traceId"], "composedBy": "deterministic", "fallback": "turn_stalled"}, status="failed",
                          usage={"provenance": "deterministic", "billing": "reservation booked: the turn never finished"})

    # --- SDK human-in-the-loop resume (ADR-H1) ---------------------------------------------------------------------------
    def _store_pending_run(self, cur, workspace_id, task_id, state_json, interruptions, writer_model=None):
        cur.execute("SELECT artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (task_id, workspace_id))
        row = cur.fetchone()
        artifact = row[0] or {} if row else {}
        proposal_ids = []
        for item in interruptions:
            try:
                args = json.loads(getattr(item, "arguments", "") or "{}")
            except ValueError:
                args = {}
            if args.get("proposalId"):
                proposal_ids.append(args["proposalId"])
        # The writer the person chose travels with the paused run, so drafting after an approval uses it too.
        artifact["pendingRun"] = {"state": state_json, "proposalIds": proposal_ids, "storedAt": self.clock(), "writerModel": writer_model}
        cur.execute("UPDATE public.pr_agent_runs SET artifact=%s::jsonb WHERE id::text=%s", (json.dumps(artifact, ensure_ascii=False, default=str), task_id))

    def _claim_pending_run(self, workspace_id, token, conversation_id, proposal_id):
        """Take the Manager run paused on this proposal off its task: (task id, paused state), or None."""
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            cur.execute("SELECT id::text,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND conversation_id::text=%s AND idempotency_key LIKE 'task:%%' "
                        "AND artifact->'pendingRun'->'proposalIds' ? %s ORDER BY created_at DESC LIMIT 1 FOR UPDATE", (workspace_id, conversation_id, proposal_id))
            found = cur.fetchone()
            if not found:
                return None
            task_id, artifact = found[0], found[1] or {}
            pending = artifact.pop("pendingRun", None) or {}
            cur.execute("UPDATE public.pr_agent_runs SET artifact=%s::jsonb WHERE id::text=%s", (json.dumps(artifact, ensure_ascii=False, default=str), task_id))
        return (task_id, pending) if pending.get("state") else None

    def _resume_pending_run(self, workspace_id, token, conversation_id, proposal_id, claimed, *, run_id, trace_id, modality, zone, approved=()):
        """The person approved a proposal a paused Manager run was waiting on (its proposal_apply call). The application has
        already applied and verified it; resume that run from its stored state with the call approved — the tool then only
        re-reads and verifies — and let the Manager finish the answer. Other paused calls are rejected, never applied.
        None when it can't resume (no price, no budget, or a failure): the deterministic "Done and checked" answer stands."""
        from agents import RunConfig, Runner
        from agents.run_state import RunState

        from . import manager as manager_mod

        task_id, pending = claimed
        workload = "standard_reasoning"
        reservation = None
        if self.model_factory is None:
            # The resumed Manager is a paid model run like any other: reserved first, or not run (the approval stands).
            route = self.cfg.route(workload, reason="resume after approval")
            estimate = self.cfg.estimate_usd_micro(route.model or "", 24_000, 4_000)
            if estimate is None:
                return None
            try:
                with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
                    reservation = self.service.ledger.reserve(cur, workspace_id, principal, "text_model", estimate, f"agent-resume:{run_id}", charge_batch=False,
                                                              provider=route.provider or "", model=route.model or "", run_id=run_id,
                                                              meta={"via": "rafii_agent_resume", "traceId": trace_id})
            except AlphaError:
                return None
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = self.service.ideas._member(row)
            plan = task_state.load(cur, workspace_id, task_id)
        ctx = RafiiRunContext(service=self.service, workspace_id=workspace_id, token=token, principal=principal, membership=member, conversation_id=conversation_id,
                              trace_id=trace_id, modality=modality, zone=zone, task=plan, run_id=run_id, now=self.clock, config=self.cfg, image_studio=self.image_studio,
                              vision=self.vision, request_text="(approved)",
                              writer_model=pending.get("writerModel") if isinstance(pending.get("writerModel"), str) and pending.get("writerModel") else None)
        ctx.cancelled = lambda: self._is_cancelled(workspace_id, token, run_id)
        ctx.deadline = time.monotonic() + TURN_BUDGET_SECONDS
        ctx.ledger.changed.extend(dict(change) for change in approved)  # the approval the application applied and verified
        try:
            manager, routes = manager_mod.build(ctx, model_factory=self.model_factory, workload=workload)
            collector = manager_mod.collector(self.cfg)
            reply, note, fallback_reason = None, None, None
            started = time.monotonic()

            async def resume():
                state = await RunState.from_json(manager, pending["state"], context_override=ctx)
                for item in state.get_interruptions():
                    try:
                        args = json.loads(getattr(item, "arguments", "") or "{}")
                    except ValueError:
                        args = {}
                    if getattr(item, "name", None) == "proposal_apply" and args.get("proposalId") == proposal_id:
                        state.approve(item)
                    else:
                        state.reject(item, rejection_message="The person did not approve this.")
                return await Runner.run(manager, state, context=ctx, max_turns=8, run_config=RunConfig(workflow_name="rafii.turn.resume", trace_id=trace_id,
                                                                                                      group_id=conversation_id, trace_include_sensitive_data=False))
            try:
                result = asyncio.run(asyncio.wait_for(resume(), timeout=TURN_BUDGET_SECONDS))
                reply = result.final_output if not result.interruptions else None
            except Exception as error:  # noqa: BLE001 — the approval stands; only the Manager's wording is lost
                fallback_reason = getattr(error, "code", None) or type(error).__name__
                note = "Your approval was applied and checked."
            return self._finalize(ctx, run_id, reservation, reply=reply, note=note, fallback_reason=fallback_reason, interruptions=[], state_json=None, routes=routes,
                                  workload=workload, why="resume after approval", spans=collector.take(trace_id), elapsed_ms=round((time.monotonic() - started) * 1000),
                                  superseded=[])
        except Exception as error:  # noqa: BLE001 — the approval stands: settle what the resume spent, answer deterministically
            log.error(json.dumps({"event": "agent_resume.failed", "errorClass": type(error).__name__, "traceId": trace_id}))
            if reservation is not None:
                with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
                    spent = self._spend(ctx.ledger, None)
                    if not ctx.ledger.spans:
                        self.service.ledger.settle(cur, workspace_id, reservation["reservationId"], "failed", 0)
                    else:
                        self.service.ledger.settle(cur, workspace_id, reservation["reservationId"], "completed" if spent is not None else "unknown", spent)
            return None


# --- endpoints beyond the turn ----------------------------------------------------------------------------------------------
def _sync_task(runtime: "AgentRuntimeService", cur, workspace_id: str, plan, state: dict) -> bool:
    """Steps waiting on a proposal follow the stored proposal, whichever surface decided it (panel button, voice, text)."""
    changed = False
    for step in plan.steps:
        if step.state != "needs_user" or not step.approvals:
            continue
        for proposal_id in step.approvals:
            found = approvals.find(cur, workspace_id, _conversation_of(cur, workspace_id, plan.task_id), proposal_id)
            status = ((found or {}).get("proposal") or {}).get("status")
            if status == "applied":
                verified, _checks = approvals.verify_applied(state, found["proposal"])
                plan.resolve_approval(proposal_id, "applied", runtime.clock(), verified=verified)
                changed = True
            elif status in ("dismissed", "expired", "superseded", "failed"):
                plan.resolve_approval(proposal_id, status, runtime.clock(), verified=False, reason=f"The proposal was {status}.")
                changed = True
    return changed


def _conversation_of(cur, workspace_id, run_id):
    cur.execute("SELECT conversation_id::text FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
    row = cur.fetchone()
    return row[0] if row else None


def task_view(runtime: "AgentRuntimeService", workspace_id, token, task_id, cursor=0) -> dict:
    if type(cursor) is not int or cursor < 0:
        raise AlphaError("Invalid event cursor.", 400)
    ideas = runtime.service.ideas
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, _principal):
        require(ideas._member(row), "read")
        plan = task_state.load(cur, workspace_id, task_id, lock=True)
        if plan.status == "running" and _sync_task(runtime, cur, workspace_id, plan, ideas._state(row)):
            task_state.save(cur, ideas, workspace_id, plan)
        events = ideas._events_for(cur, workspace_id, task_id, cursor)
    return {"task": plan.view(), "events": events["events"], "cursor": events["cursor"]}


def conversation_task(runtime: "AgentRuntimeService", workspace_id, token, conversation_id) -> dict:
    ideas = runtime.service.ideas
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, _principal):
        require(ideas._member(row), "read")
        ideas._conversation(cur, workspace_id, conversation_id)
        plan = task_state.active(cur, workspace_id, conversation_id)
        if plan is not None and _sync_task(runtime, cur, workspace_id, plan, ideas._state(row)):
            task_state.save(cur, ideas, workspace_id, plan)
        images = creative.conversation_images(cur, ideas._state(row), workspace_id, conversation_id)
        pending = approvals.open_proposals(cur, workspace_id, conversation_id, runtime.clock())
    return {"task": plan.view() if plan else None, "images": images,
            "pendingApprovals": [{k: v for k, v in item.items() if k != "proposal"} for item in pending]}


def decide(runtime: "AgentRuntimeService", workspace_id, token, payload) -> dict:
    """The panel's (or Voice Mode's visual card's) Apply/Dismiss for an agent proposal: the site agent's apply path, then
    re-read and verify, then the task step and any paused Manager run follow."""
    if not isinstance(payload, dict):
        raise AlphaError("Send a structured decision.", 400)
    names = ("conversationId", "messageId", "proposalId", "digest")
    if not all(isinstance(payload.get(k), str) and payload.get(k) for k in names) or payload.get("decision") not in ("apply", "dismiss"):
        raise AlphaError("Name the proposal and the decision.", 400)
    decided = approvals.decide(runtime.service, workspace_id, token, conversation_id=payload["conversationId"], message_id=payload["messageId"],
                               proposal_id=payload["proposalId"], digest=payload["digest"], decision=payload["decision"], zone=payload.get("timeZone"))
    runtime._resolve_task_steps(workspace_id, token, payload["conversationId"], payload["proposalId"],
                                decided["outcome"] if payload["decision"] == "apply" else "dismissed", verified=decided["verified"])
    spoken = ("Done, and I checked it in your workspace." if decided["outcome"] == "applied" and decided["verified"]
              else "I applied it, but the check didn't fully match. Please look at the panel." if decided["outcome"] == "applied"
              else "Okay, I left it. Nothing was changed.")
    return {**{k: v for k, v in decided.items() if k != "revision"}, "speakableSummary": spoken}


def attach_upload(runtime: "AgentRuntimeService", workspace_id, token, payload) -> dict:
    """An image the person adds to the conversation (text or voice): decoded and stored privately by the existing media
    path, then recorded on the conversation so "the second image" is stable."""
    if not isinstance(payload, dict) or not isinstance(payload.get("conversationId"), str):
        raise AlphaError("Name the conversation.", 400)
    service = runtime.service
    with service.repository.transaction(token, workspace_id) as (cur, row, _principal):
        require(service.ideas._member(row), "edit")
        service.ideas._conversation(cur, workspace_id, payload["conversationId"])
    if payload.get("assetId"):
        asset_id = payload["assetId"]
    else:
        before = {a.get("id") for a in (service.repository.get(workspace_id, token)["state"].get("phase2") or {}).get("assets", [])}
        revision = service.repository.get(workspace_id, token)["revision"]
        saved = service.upload_media(workspace_id, token, revision, {"data": payload.get("data")})
        state = saved.get("state") or service.repository.get(workspace_id, token)["state"]
        new = [a for a in (state.get("phase2") or {}).get("assets", []) if a.get("id") not in before]
        if not new:
            raise AlphaError("The image was not saved.", 502)
        asset_id = new[-1]["id"]
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        state = service.ideas._state(row)
        attached = runtime._attach(cur, state, workspace_id, payload["conversationId"], principal, [{"assetId": asset_id}], service.ideas._member(row))
        images = creative.conversation_images(cur, state, workspace_id, payload["conversationId"])
    index = next((i["index"] for i in images if i["assetId"] == asset_id), None)
    return {"assetId": attached[0]["assetId"], "index": index, "images": images, "href": f"/api/workspaces/{workspace_id}/media/{asset_id}"}


# The site agent's own evidence views for what the Manager read: stored facts and derived observations (with their rules),
# voice-check findings with their basis, audit-backed attribution — so a recommendation is inspectable (spec §22, §24).
EVIDENCE_INTENTS = {"attention.summary": "attention", "reviews.list": "reviews", "publishing.summary": "publishing", "calendar.range": "calendar",
                    "campaign.get": "campaign", "voice.check": "voice_check", "member.activity": "member_activity", "record.attribution": "attribution",
                    "campaign.membership": "campaign_membership"}
MAX_EVIDENCE_BLOCKS = 6


def evidence_blocks(ledger, text: str, language: str | None) -> list[dict]:
    from ..site_agent import compose_reads
    out = []
    for tool_id, intent in EVIDENCE_INTENTS.items():
        result = ledger.site_results.get(tool_id)
        if not result:
            continue
        try:
            composed = compose_reads.compose(intent, {"intent": intent, "language": language or "en", "entities": {"platforms": [], "days": []}}, {tool_id: result}, text or "")
        except Exception:  # noqa: BLE001 — evidence is additive; a composer that needs more context is skipped
            composed = None
        kept = [b for b in (composed or {}).get("blocks") or [] if b.get("type") in ("result_list", "diagnostic_card")]
        if not kept and (composed or {}).get("lines") and len(out) < MAX_EVIDENCE_BLOCKS:
            # Nothing to list, but the grounded reading still says something true ("no profile to compare with").
            from ..site_agent import contracts as site_contracts
            out.append(site_contracts.text(" ".join(composed["lines"])[:600]))
        for block in kept:
            if len(out) < MAX_EVIDENCE_BLOCKS:
                out.append(block)
    return out
