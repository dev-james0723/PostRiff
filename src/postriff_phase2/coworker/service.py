"""CoworkerService: the deterministic application service behind the coworker workflows (architecture lock W1, S1-S2,
A1, C1, P1, L1, T1, G1).

Every mutation runs through `repository.command` with an explicit permission requirement and a content-free audit
row, then the result is re-read and compared before success is reported (`verified`). Drafting goes through the
existing writing pipeline (`IdeasService.turn` → `apply`), so the usage ledger, source policy, voice consent, skill
binding and learning capture all apply unchanged. Nothing here schedules, publishes, sends or charges: approval and
publishing stay in Queue, replies stay behind the existing reply approval.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import time

from postriff_alpha.domain import AlphaError

from .. import skill_compiler
from . import creative, engagement, fact_pack, flags, humanizer, overlays, research_broker, source_intake, weekly_operator

log = logging.getLogger("postriff.coworker")
VISUAL_FIRST = ("Instagram", "TikTok", "Pinterest", "YouTube", "Xiaohongshu")
DEFAULT_WRITER_SLOTS_PER_CALL = 8
WRITER_RUN_SECONDS = 95   # one writer run: two attempts of 45 s plus saving
UNKNOWN_RUN_USD_MICRO = 50_000   # a weekly writing run with no recorded cost and no reservation counts as $0.05


def _event(cur, workspace_id, user_id, event, properties=None, dedupe=None):
    """Growth instrumentation: ids, counts and categories only (never text)."""
    cur.execute("INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key) VALUES(%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
                (workspace_id, user_id, event, json.dumps(properties or {}), dedupe))


def attention_enabled():
    return flags.enabled("RAFII_NOTIFICATIONS_V2_ENABLED") or flags.enabled("RAFII_WEEKLY_OPERATOR_ENABLED")


class CoworkerService:
    def __init__(self, hosted, values=None, clock=None):
        self.hosted = hosted
        self.values = dict(values or {})
        self.clock = clock or getattr(hosted, "clock", None) or time.time

    # --- plumbing ----------------------------------------------------------------------------------------------------------
    @property
    def repository(self):
        return self.hosted.repository

    def _require(self, flag):
        flags.require(flag)

    def _state(self, workspace_id, token):
        return self.repository.get(workspace_id, token)["state"]

    def _command(self, workspace_id, token, fn, requirement, audit_kind, subject="", meta=None, after=None):
        """repository.command with one retry on a revision conflict; returns (result, state_after)."""
        box = {}

        def trusted(state, principal):
            box["result"] = fn(state, principal)
            return state

        for attempt in range(2):
            revision = self.repository.get(workspace_id, token)["revision"]
            try:
                saved = self.repository.command(workspace_id, token, revision, trusted, requirement=requirement,
                                                audit_event=lambda _s: (audit_kind, subject[:200], meta or {}), after=after)
                return box.get("result"), (saved or {}).get("state") if isinstance(saved, dict) else None
            except AlphaError as error:
                if getattr(error, "code", None) == "workspace_revision_conflict" and attempt == 0:
                    continue
                raise
        raise AlphaError("The workspace changed while saving. Try again.", 409, code="workspace_revision_conflict")

    def _principal(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (_cur, row, principal):
            return principal, self.hosted.ideas._member(row)

    # --- status -------------------------------------------------------------------------------------------------------------
    def status(self, workspace_id, token):
        from .. import skill_registry
        state = self._state(workspace_id, token)
        weekly = weekly_operator.view(state)
        notifications = getattr(self.hosted, "notifications", None)
        return {**flags.public(), "registryRelease": skill_registry.default_registry().release(),
                "notifications": notifications.status() if notifications else {"enabled": False},
                "research": research_broker.ResearchBroker(state=state).diagnostics() if flags.enabled("RAFII_RESEARCH_BROKER_ENABLED") else [],
                "weekly": {"recipes": len([r for r in weekly["recipes"] if r.get("status") != "deleted"]), "weeks": len(weekly["weeks"])}}

    # === Weekly Social Operator ==================================================================================================
    def weekly_list(self, workspace_id, token):
        self._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        state = self._state(workspace_id, token)
        weekly = copy.deepcopy(weekly_operator.view(state))
        for week in weekly["weeks"]:
            weekly_operator.sync_from_queue(state, week, self.clock())
            week["counts"] = weekly_operator.summarize(week)
        return {"recipes": [r for r in weekly["recipes"] if r.get("status") != "deleted"], "weeks": sorted(weekly["weeks"], key=lambda w: w["weekOf"], reverse=True)[:8]}

    def weekly_save_recipe(self, workspace_id, token, payload, recipe_id=None):
        """Owner: a recipe authorises recurring paid drafting (like activating an automation)."""
        self._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        now = self.clock()

        def change(state, principal):
            return weekly_operator.save_recipe(state, payload, principal, now, recipe_id)

        recipe, _ = self._command(workspace_id, token, change, "owner", "weekly.recipe_saved", recipe_id or "new", {"destinations": len(payload.get("destinations") or [])})
        stored = next((r for r in weekly_operator.view(self._state(workspace_id, token))["recipes"] if r["id"] == recipe["id"]), None)
        with self.repository.transaction(token, workspace_id) as (cur, _row, principal):
            _event(cur, workspace_id, principal, "weekly_operator.enabled", {"recipeId": recipe["id"]}, f"weekly_enabled:{recipe['id']}")
        return {"recipe": stored, "verified": stored is not None and stored["version"] == recipe["version"]}

    def weekly_recipe_status(self, workspace_id, token, recipe_id, status):
        self._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        now = self.clock()
        self._command(workspace_id, token, lambda state, _p: weekly_operator.set_recipe_status(state, recipe_id, status, now), "owner",
                      "weekly.recipe_status", recipe_id, {"status": status})
        stored = next((r for r in weekly_operator.view(self._state(workspace_id, token))["recipes"] if r["id"] == recipe_id), None)
        return {"recipe": stored, "verified": bool(stored and stored["status"] == status)}

    def _bound_ideas(self, repository):
        """A copy of the writing pipeline that reads and writes through `repository`. Its credit checks must use the
        same repository: the shared `credit_requests` would open the service's original one with the cron capability,
        which the session verifier cannot read (campaign_worker does the same rebind)."""
        from ..credit_requests import CreditRequests
        ideas = copy.copy(self.hosted.ideas)
        ideas.repository = repository
        ideas.credit_requests = CreditRequests(ideas)
        return ideas

    def _writer(self, workspace_id, token, actor=None):
        """The writing pipeline as the person (HTTP) or as the recipe's owner (cron capability)."""
        if actor is None:
            return copy.copy(self.hosted.ideas), token
        from ..automation_runs import principal_repository
        repository, capability = principal_repository(self.hosted, workspace_id, actor, "edit")
        return self._bound_ideas(repository), capability

    def _find_week(self, state, week_id):
        week = next((w for w in weekly_operator.view(state)["weeks"] if w["id"] == week_id), None)
        if week is None:
            raise AlphaError("Week unavailable.", 404)
        return week

    def _update_week(self, workspace_id, token, week_id, mutate, audit_kind="weekly.week_updated", meta=None, emit=None):
        """Change one week in one command; `emit(state, week, cur)` may emit notification events in that transaction."""
        box = {}

        def change(state, principal):
            week = self._find_week(state, week_id)
            mutate(state, week, principal)
            weekly_operator.root(state)["revision"] += 1
            box["week"] = copy.deepcopy(week)
            return week

        def after(cur, state, principal):
            if emit is not None:
                emit(cur, state, box["week"], principal)

        self._command(workspace_id, token, change, "edit", audit_kind, week_id, meta or {}, after=after)
        stored = self._find_week(self._state(workspace_id, token), week_id)
        return stored

    def weekly_prepare(self, workspace_id, token, recipe_id, actor=None, max_slots=DEFAULT_WRITER_SLOTS_PER_CALL, week_of=None, deadline=None):
        """Plan (if needed) and move next week forward as far as it safely can: draft, check, and stop at review or
        at a real blocker. Idempotent per week and per slot; a repeated call continues where the last one stopped."""
        self._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        now = self.clock()
        if actor is None:
            repository, writer_token = self.repository, token
        else:
            # The cron acts as the recipe's owner through a private capability (never an HTTP credential); each
            # transaction re-checks that person's membership class.
            writer, writer_token = self._writer(workspace_id, token, actor)
            repository = writer.repository
        state = repository.get(workspace_id, writer_token)["state"]
        recipe = next((r for r in weekly_operator.view(state)["recipes"] if r["id"] == recipe_id and r.get("status") == "active"), None)
        if recipe is None:
            raise AlphaError("This weekly recipe is not active.", 409)
        planned = weekly_operator.plan_week(state, recipe, now, week_of)
        existing = next((w for w in weekly_operator.view(state)["weeks"] if w["id"] == planned["id"]), None)
        if existing is None:
            def add(state_, principal):
                weekly = weekly_operator.root(state_)
                if not any(w["id"] == planned["id"] for w in weekly["weeks"]):
                    weekly["weeks"] = weekly["weeks"][-11:] + [planned]
                    weekly["revision"] += 1
                return planned
            self._command_as(repository, workspace_id, writer_token, add, "edit", "weekly.week_planned", planned["id"], {"slots": len(planned["slots"])})
        return self._advance(workspace_id, writer_token, repository, recipe, planned["id"], actor, max_slots, deadline)

    def _command_as(self, repository, workspace_id, token, fn, requirement, audit_kind, subject, meta, after=None):
        box = {}

        def trusted(state, principal):
            box["result"] = fn(state, principal)
            return state
        for attempt in range(2):
            revision = repository.get(workspace_id, token)["revision"]
            try:
                repository.command(workspace_id, token, revision, trusted, requirement=requirement, audit_event=lambda _s: (audit_kind, subject[:200], meta or {}), after=after)
                return box.get("result")
            except AlphaError as error:
                if getattr(error, "code", None) == "workspace_revision_conflict" and attempt == 0:
                    continue
                raise

    def _advance(self, workspace_id, token, repository, recipe, week_id, actor, max_slots, deadline=None):
        ideas = self._bound_ideas(repository)
        state = repository.get(workspace_id, token)["state"]
        week = self._find_week(state, week_id)
        if week["state"] in ("ready_for_review", "approved", "scheduled"):
            return {"week": week, "advanced": False, "drafted": 0, "draftedSlotIds": [], "verified": True}
        drafting = [s for s in week["slots"] if s["status"] == "planned"]
        if drafting and week["state"] in ("planned",) + weekly_operator.BLOCKED_STATES:
            self._week_state(repository, workspace_id, token, week_id, "generating", f"drafting {len(drafting)} posts")
        # Conversation for this week's writing runs (the runs and their events are the audit trail).
        if not week.get("conversationId"):
            conversation = ideas.create_conversation(workspace_id, token, f"Week of {week['weekOf']}")
            conversation_id = conversation["conversationId"]

            def keep(state_, _p):
                self._find_week(state_, week_id)["conversationId"] = conversation_id
                weekly_operator.root(state_)["revision"] += 1
            self._command_as(repository, workspace_id, token, keep, "edit", "weekly.week_updated", week_id, {"conversation": True})
            week["conversationId"] = conversation_id
        drafted_ids = []
        for slot in drafting[:max_slots]:
            if deadline is not None and time.monotonic() + WRITER_RUN_SECONDS > deadline:
                break   # a paid writer run is not started unless it can finish inside the caller's time budget; the next call continues
            key = f"weekly:{week_id}:{slot['id']}:{slot.get('attempt', 0)}"
            spent, limit = self._week_spend(workspace_id, week_id), int(recipe.get("maxCostUsdMicroPerWeek") or 0)
            if spent >= limit:   # a $0 limit means Rafii plans the week but never drafts with a paid model
                outcome = {"status": "needs_input", "reason": "This week's writing budget is used up. Raise the recipe's weekly limit or skip the remaining posts."
                           if limit > 0 else "The weekly drafting limit is $0, so Rafii planned this post but didn't draft it. Raise the limit, or write it yourself."}
            else:
                outcome = self._draft_slot(ideas, workspace_id, token, repository, recipe, week, slot, key, state)
            self._record_slot(repository, workspace_id, token, week_id, slot["id"], outcome)
            if outcome["status"] == "drafted":
                drafted_ids.append(slot["id"])
        return self._quality_and_settle(workspace_id, token, repository, recipe, week_id, actor, drafted_ids)

    def _week_spend(self, workspace_id, week_id):
        """What this week's writing runs have cost so far: the recorded cost when it is known; otherwise the run's
        reserved estimate from the usage ledger; otherwise a conservative fixed estimate. Only a run that made no
        model call (provenance 'none') counts as free."""
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT coalesce(sum(CASE WHEN r.usage->>'costUsd' IS NOT NULL THEN (r.usage->>'costUsd')::numeric * 1000000
                                                    WHEN r.usage->>'provenance' = 'none' THEN 0
                                                    ELSE coalesce((SELECT max(l.estimated_usd_micro) FROM public.pr_usage_ledger l WHERE l.run_id = r.id), %s) END), 0)
                             FROM public.pr_agent_runs r WHERE r.workspace_id=%s AND r.idempotency_key LIKE %s""",
                        (UNKNOWN_RUN_USD_MICRO, workspace_id, f"weekly:{week_id}:%"))
            return int(float(cur.fetchone()[0]))

    def _draft_slot(self, ideas, workspace_id, token, repository, recipe, week, slot, key, state):
        """One post through the writing pipeline. The slot brief is `material` (data, never instructions), so the
        pipeline treats this as a drafting request: it never becomes an automation, a schedule or a memory."""
        try:
            with skill_compiler.workflow_context("rafii-weekly-operator"):
                ideas.turn(workspace_id, token, week["conversationId"], {
                    "text": "Write one post for this week's plan from the material.", "material": weekly_operator.slot_brief(recipe, slot, state),
                    "idempotencyKey": key, "model": recipe.get("model"), "reasoning": "quick", "sourceIds": slot["sourceIds"],
                    "destinations": [{"platform": slot["platform"], "language": slot["language"], "channelId": slot["channelId"]}], "research": False,
                    "voiceMode": recipe.get("voiceMode", "neutral"), "timeZone": recipe["timeZone"]})
            with self.hosted.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT id::text,status,artifact_hash FROM pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
                run = cur.fetchone()
            if run and run[1] == "completed":
                applied = ideas.apply(workspace_id, token, repository.get(workspace_id, token)["revision"], run[0], run[2], separate=True,
                                      tag={"weekPlanId": week["id"], "slotId": slot["id"]})
                # apply() returns the drafts it created as [{platform, language, channelId, variantId}].
                variant_id = next((c["variantId"] for c in applied.get("variantIds") or [] if isinstance(c, dict) and c.get("variantId")), None)
                return {"status": "drafted", "runId": run[0], "variantId": variant_id}
            if run and run[1] == "applied":
                return {"status": "drafted", "runId": run[0], "variantId": None}
            if run and run[1] == "running":
                return {"status": "planned", "runId": run[0], "reason": "The writer is still working on this post."}
            return {"status": "failed", "reason": "The writer couldn't prepare this post. Nothing was published."}
        except AlphaError as error:
            return {"status": "failed", "reason": str(error)[:200]}

    def _record_slot(self, repository, workspace_id, token, week_id, slot_id, result):
        def record(state_, _p):
            target = next(s for s in self._find_week(state_, week_id)["slots"] if s["id"] == slot_id)
            target["status"] = result["status"] if result["status"] != "failed" else "needs_input"
            target["runId"] = result.get("runId") or target.get("runId")
            if result.get("variantId"):
                target["variantId"] = result["variantId"]
            if result.get("reason"):
                target["reason"] = result["reason"]
                if result["status"] == "failed":
                    target["question"] = "Rafii couldn't draft this post. Try again, change the angle, or skip it."
            weekly_operator.root(state_)["revision"] += 1
        self._command_as(repository, workspace_id, token, record, "edit", "weekly.slot_drafted", week_id, {"status": result["status"]})

    def _week_state(self, repository, workspace_id, token, week_id, target, note):
        now = self.clock()

        def change(state_, _p):
            weekly_operator.transition(self._find_week(state_, week_id), target, now, note)
            weekly_operator.root(state_)["revision"] += 1
        self._command_as(repository, workspace_id, token, change, "edit", "weekly.week_state", week_id, {"state": target})

    def _quality_and_settle(self, workspace_id, token, repository, recipe, week_id, actor, drafted_ids):
        now = self.clock()
        state = repository.get(workspace_id, token)["state"]
        week = self._find_week(state, week_id)
        brand_terms = [t for t in ((state.get("coworker") or {}).get("glossary") or []) if isinstance(t, str)]
        checks = {}
        for slot in week["slots"]:
            if slot["status"] != "drafted":
                continue
            variant = next((v for v in state.get("variants") or [] if v.get("id") == slot.get("variantId")), None)
            if variant is None:
                variant = next((v for v in reversed(state.get("variants") or []) if (v.get("automation") or {}).get("slotId") == slot["id"]), None)
            if variant is None:
                checks[slot["id"]] = {"status": "needs_input", "reason": "The draft could not be found after saving."}
                continue
            source_text = "\n".join(f["text"] for s in state.get("sources") or [] if s.get("id") in slot["sourceIds"] for f in s.get("facts") or [] if f.get("approved"))
            result = humanizer.evaluate(variant.get("text") or "", source=None, locale=slot["language"], platform=slot["platform"], brand_terms=brand_terms,
                                        voice_state=state)
            # A number, name or date the draft states that nothing it was given supports is a meaning violation. The
            # basis is the approved facts, else the person's own answer; with neither, the record says it was not compared.
            basis_text, basis = (source_text, "approved_facts") if source_text else ((slot.get("answer") or "", "your_answer") if slot.get("answer") else ("", "none"))
            unsupported = [v for v in humanizer.meaning_diff(basis_text, variant.get("text") or "", brand_terms) if v["code"] in ("number_added", "name_added", "anecdote_added", "feeling_added")] if basis_text else []
            blocking = unsupported
            creative_plan = None
            if recipe.get("expectImages") and slot["platform"] in VISUAL_FIRST:
                creative_plan = creative.plan_assets(state, {"message": slot["goal"], "copy": variant.get("text"), "documentary": True}, [slot["platform"]], "image",
                                                     assets=[a for a in ((state.get("phase2") or {}).get("assets") or []) if a.get("status") != "deleted"][:5])
            checks[slot["id"]] = {"status": "needs_revision" if blocking else ("needs_asset" if creative_plan and creative_plan["missingAssets"] else "ready"),
                                  "variantId": variant["id"], "quality": {"evaluator": result["version"], "patterns": result["patternsVersion"], "style": result["styleFindings"],
                                                                          "meaning": blocking, "meaningBasis": basis, "lint": result["stages"]["lint"][:5],
                                                                          "voiceFit": result["stages"].get("voiceFit")},
                                  "creative": {k: creative_plan[k] for k in ("plans", "missingAssets", "compiled")} if creative_plan else None}

        if not checks:
            unchanged = copy.deepcopy(week)
            weekly_operator.settle(unchanged, now)
            if unchanged == week:
                # Nothing was drafted and the week's state stands: no write, no revision bump, no audit row. `advanced`
                # stays true: only a week already in review answers false (the web and the agent tool read it that way).
                return {"week": week, "advanced": True, "drafted": len(drafted_ids), "draftedSlotIds": list(drafted_ids), "verified": True}

        def apply_checks(state_, _p):
            target_week = self._find_week(state_, week_id)
            if checks and target_week["state"] == "generating":
                weekly_operator.transition(target_week, "quality_check", now, f"{len(checks)} drafts checked")
            for slot in target_week["slots"]:
                check = checks.get(slot["id"])
                if check:
                    slot.update({k: v for k, v in check.items() if v is not None})
                    if check["status"] == "needs_asset":
                        slot["reason"] = "This post needs an image. A creative brief is ready; add or generate an image, then accept."
            weekly_operator.settle(target_week, now)
            weekly_operator.root(state_)["revision"] += 1
            return copy.deepcopy(target_week)

        def emit(cur, state_, principal):
            target_week = self._find_week(state_, week_id)
            notifications = getattr(self.hosted, "notifications", None)
            if notifications is None:
                return
            if target_week["state"] == "ready_for_review":
                notifications.emit(cur, workspace_id=workspace_id, event_type="campaign.week_ready", dedupe_key=f"week_ready:{week_id}", entity_type="week_plan",
                                   entity_id=week_id, payload={"weekOf": target_week["weekOf"], "count": sum(1 for s in target_week["slots"] if s["status"] in ("ready", "needs_revision")),
                                                               "href": f"/app/weekly?week={week_id}"}, actor=principal)
                _event(cur, workspace_id, principal, "weekly_plan.ready", {"weekId": week_id, "slots": len(target_week["slots"])}, f"weekly_ready:{week_id}")
            elif target_week["state"] in weekly_operator.BLOCKED_STATES:
                notifications.emit(cur, workspace_id=workspace_id, event_type="campaign.blocked", dedupe_key=f"week_blocked:{week_id}:{target_week['state']}",
                                   entity_type="week_plan", entity_id=week_id, payload={"weekOf": target_week["weekOf"], "title": "Next week needs you",
                                                                                        "reason": (target_week.get("blockedReason") or "")[:200], "href": f"/app/weekly?week={week_id}"})

        settled = self._command_as(repository, workspace_id, token, apply_checks, "edit", "weekly.week_checked", week_id, {"checked": len(checks)},
                                   after=lambda cur, state_, principal: emit(cur, state_, principal))
        stored = self._find_week(repository.get(workspace_id, token)["state"], week_id)
        return {"week": stored, "advanced": True, "drafted": len(drafted_ids), "draftedSlotIds": list(drafted_ids),
                "verified": settled is not None and stored["state"] == settled["state"]}

    def weekly_week(self, workspace_id, token, week_id):
        self._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        with self.repository.transaction(token, workspace_id) as (_cur, row, _principal):
            can_edit = self._can_edit(row)
        state = self._state(workspace_id, token)
        week = copy.deepcopy(self._find_week(state, week_id))
        changed = weekly_operator.sync_from_queue(state, week, self.clock())
        if changed and can_edit:   # anyone may read the Queue-synced week; only an editor's read saves it
            live = self._update_week(workspace_id, token, week_id, lambda s, w, p: weekly_operator.sync_from_queue(s, w, self.clock()), "weekly.week_synced")
            week = live
        variants = {v["id"]: v for v in state.get("variants") or []}
        for slot in week["slots"]:
            variant = variants.get(slot.get("variantId"))
            slot["draft"] = {"text": variant.get("text"), "unknowns": variant.get("unknowns"), "needsReview": variant.get("needsReview")} if variant else None
        with self.repository.transaction(token, workspace_id) as (cur, _row, principal):
            _event(cur, workspace_id, principal, "weekly_plan.reviewed", {"weekId": week_id}, f"weekly_reviewed:{week_id}:{principal}")
        return {"week": week, "counts": weekly_operator.summarize(week), "queueHref": "/app/queue?view=drafts"}

    def weekly_slot(self, workspace_id, token, week_id, slot_id, action, payload=None):
        """accept | reject | answer | redo | skip. Accept hands the draft to Queue, where the person confirms, reviews
        and approves it exactly as any other draft; Rafii does not approve or schedule."""
        self._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        payload = payload or {}
        if action not in ("accept", "reject", "answer", "redo", "skip"):
            raise AlphaError("Choose accept, reject, answer, redo or skip.", 400)
        now = self.clock()

        def mutate(state, week, principal):
            slot = next((s for s in week["slots"] if s["id"] == slot_id), None)
            if slot is None:
                raise AlphaError("Slot unavailable.", 404)
            if action == "accept":
                if slot["status"] not in ("ready", "needs_revision", "needs_asset") or not slot.get("variantId"):
                    raise AlphaError("Only a drafted post can be accepted.", 409)
                slot["status"], slot["acceptedBy"], slot["acceptedAt"] = "accepted", principal, now
            elif action in ("reject", "skip"):
                slot["status"], slot["reason"] = "rejected", _clean(payload.get("reason"), 200) or ("Skipped" if action == "skip" else "Rejected")
            elif action == "answer":
                if slot["status"] not in ("needs_input", "needs_source"):
                    raise AlphaError("This post isn't waiting for an answer.", 409)
                answer = _clean(payload.get("answer"), 600)
                if not answer:
                    raise AlphaError("Write a short answer.", 400)
                slot["answer"], slot["status"], slot["question"], slot["reason"] = answer, "planned", None, None
                slot["attempt"] = slot.get("attempt", 0) + 1
                if week["state"] == "ready_for_review":   # otherwise the answered post would never be drafted
                    weekly_operator.transition(week, "generating", now, "a question was answered")
            elif action == "redo":
                if slot["status"] not in ("ready", "needs_revision", "needs_asset", "needs_input"):
                    raise AlphaError("Only a drafted or failed post can be redone.", 409)
                slot["status"], slot["variantId"], slot["attempt"] = "planned", None, slot.get("attempt", 0) + 1
                if week["state"] == "ready_for_review":
                    weekly_operator.transition(week, "generating", now, "a post is being redone")
            weekly_operator.settle(week, now)

        week = self._update_week(workspace_id, token, week_id, mutate, f"weekly.slot_{action}", {"slot": slot_id})
        slot = next(s for s in week["slots"] if s["id"] == slot_id)
        expected = {"accept": "accepted", "reject": "rejected", "skip": "rejected", "answer": "planned", "redo": "planned"}[action]
        return {"week": week, "slot": slot, "verified": slot["status"] == expected,
                "next": "Open Queue → Drafts to confirm, review and approve this post." if action == "accept" else None}

    def weekly_cron(self, max_workspaces=20, max_seconds=110, deadline=None):
        if not flags.enabled("RAFII_WEEKLY_OPERATOR_ENABLED"):
            return {"status": "disabled"}
        started, done = time.monotonic(), []
        deadline = deadline if deadline is not None else started + max_seconds
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT id::text, state->'coworker'->'weekly'->'recipes' FROM public.pr_workspaces
                           WHERE state->'coworker'->'weekly'->'recipes' IS NOT NULL AND NOT state ? 'accountDeletion' LIMIT %s""", (max_workspaces,))
            rows = cur.fetchall()
        for workspace_id, recipes in rows:
            for recipe in recipes or []:
                if time.monotonic() - started > max_seconds:
                    return {"prepared": done, "stoppedEarly": True}
                if not weekly_operator.due(recipe, self.clock()):
                    continue
                try:
                    result = self.weekly_prepare(workspace_id, None, recipe["id"], actor=recipe["createdBy"], max_slots=2, deadline=deadline)
                    done.append({"workspaceId": workspace_id, "recipeId": recipe["id"], "state": result["week"]["state"]})
                except AlphaError as error:
                    done.append({"workspaceId": workspace_id, "recipeId": recipe["id"], "error": str(error)[:120]})
                except Exception as error:  # noqa: BLE001 - one recipe's defect never stops the others this minute
                    log.warning(json.dumps({"event": "coworker.weekly_recipe_failed", "error": type(error).__name__}))
                    done.append({"workspaceId": workspace_id, "recipeId": recipe["id"], "error": type(error).__name__})
        return {"prepared": done}

    # === Research Broker + One Source → Full Campaign ============================================================================
    def _broker(self, state):
        return research_broker.ResearchBroker(state=state)

    def _store_evidence(self, cur, workspace_id, request_key, item_provenance, excerpt):
        prov = item_provenance or {}
        cur.execute("""INSERT INTO public.pr_research_evidence(workspace_id,request_key,provider,provider_kind,access_method,query,url,host,platform,retrieved_at,
                              published_at,author,content_sha256,represented_scope,evidence_type,rights,injection_flags,excerpt)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                       ON CONFLICT (workspace_id,content_sha256,url) DO UPDATE SET request_key=excluded.request_key RETURNING id::text""",
                    (workspace_id, request_key, prov.get("provider") or "user", prov.get("kind") if prov.get("kind") in ("web_search", "web_reader", "official_api", "mcp", "local_agent_reach", "fixture") else "user_supplied",
                     prov.get("accessMethod") or "user_upload", (prov.get("query") or None) and prov["query"][:400], prov.get("url"), prov.get("host"), prov.get("platform"),
                     prov.get("retrievedAt") or self.clock(), (str(prov.get("publishedAt"))[:60] if prov.get("publishedAt") else None), (prov.get("author") or None),
                     prov.get("contentHash") or research_broker.content_hash(excerpt or ""), prov.get("representedScope") or "user_supplied",
                     prov.get("evidenceType") if prov.get("evidenceType") in ("search_snippet", "page_text", "transcript", "owned_post", "user_supplied", "social_post", "image_text") else "user_supplied",
                     json.dumps(prov.get("rights") or {}), json.dumps(prov.get("injectionFlags") or []), (excerpt or "")[:8000]))
        return cur.fetchone()[0]

    def research_search(self, workspace_id, token, query):
        self._require("RAFII_RESEARCH_BROKER_ENABLED")
        query = _clean(query, 400)
        if not query:
            raise AlphaError("Say what to look for.", 400)
        self._require_edit(workspace_id, token)   # before any provider call: a viewer never causes egress
        state = self._state(workspace_id, token)
        outcome = self._broker(state).search_items(query, {"limit": 6})
        key = f"research:search:{hashlib.sha256(query.encode()).hexdigest()[:16]}"
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from ..permissions import require
            require(self.hosted.ideas._member(row), "edit")
            evidence_ids = [self._store_evidence(cur, workspace_id, key, item["provenance"], item["snippet"]) for item in outcome["items"]]
            _event(cur, workspace_id, principal, "research.search", {"status": outcome["status"], "results": len(outcome["items"])})
        return {"status": outcome["status"], "provider": outcome["provider"], "errors": outcome["errors"],
                "items": [{**i, "evidenceId": e, "usableForDraft": False, "note": "A search result is a lead, not a verified fact."} for i, e in zip(outcome["items"], evidence_ids)]}

    def _require_edit(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (_cur, row, _principal):
            from ..permissions import require
            require(self.hosted.ideas._member(row), "edit")

    def _can_edit(self, row):
        from ..permissions import require
        try:
            require(self.hosted.ideas._member(row), "edit")
            return True
        except AlphaError:
            return False

    def research_diagnostics(self, workspace_id, token):
        state = self._state(workspace_id, token)
        return {"providers": self._broker(state).diagnostics(), "enabled": flags.enabled("RAFII_RESEARCH_BROKER_ENABLED")}

    def source_campaign(self, workspace_id, token, payload):
        """One source → FactPack → CanonicalBrief → angles → channel drafts (+ quality) → creative briefs → campaign."""
        if not (flags.enabled("RAFII_WEEKLY_OPERATOR_ENABLED") or flags.enabled("RAFII_RESEARCH_BROKER_ENABLED")):
            raise AlphaError("This Rafii feature isn’t turned on yet.", 404, code="feature_disabled")
        now = self.clock()
        self._require_edit(workspace_id, token)   # before a link is fetched: a viewer never causes egress
        state = self._state(workspace_id, token)
        kind = payload.get("format") or "text"
        if kind == "url" and not flags.enabled("RAFII_RESEARCH_BROKER_ENABLED"):
            raise AlphaError("Reading links needs the Research Broker, which is off.", 404, code="feature_disabled")
        artifact = source_intake.normalize(kind, payload, broker=self._broker(state) if kind == "url" else None, now=now)
        pack = fact_pack.build([artifact], now)
        goal = _clean(payload.get("goal"), 600) or f"Share: {artifact['title'][:120]}"
        audience = _clean(payload.get("audience"), 400) or ((state.get("brandHub") or {}).get("audience") or "")
        brief = fact_pack.canonical_brief(pack, goal=goal, audience=audience, cta=_clean(payload.get("cta"), 160) or None)
        angles = fact_pack.angles(pack, brief)
        channels = {c.get("id"): c for c in ((state.get("phase2") or {}).get("channels") or [])}
        destinations = []
        for item in (payload.get("destinations") or [])[:6]:
            channel = channels.get(item.get("channelId"))
            if channel is None or channel.get("revoked"):
                raise AlphaError("Choose connected accounts from this workspace.", 400)
            destinations.append({"platform": channel["platform"], "language": _clean(item.get("language") or channel.get("language") or "en", 20), "channelId": channel["id"]})
        if not destinations:
            raise AlphaError("Choose at least one account to write for.", 400)
        usable = [c for c in pack["claims"] if c["usableForDraft"]]
        record_id = "sc_" + hashlib.sha256(f"{workspace_id}:{pack['hash']}:{brief['hash']}".encode()).hexdigest()[:12]
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from ..permissions import require
            require(self.hosted.ideas._member(row), "edit")
            evidence_id = self._store_evidence(cur, workspace_id, f"source:{record_id}", artifact["provenance"], artifact["text"])
        source_text = "\n".join(c["text"] for c in pack["claims"])
        box = {}

        def create(state_, principal):
            commands = self.hosted.commands
            existing = next((x for x in ((state_.get("coworker") or {}).get("sourceCampaigns") or []) if x["id"] == record_id), None)
            if existing:
                box["record"] = existing
                return existing
            source_id = None
            if pack["claims"]:
                before = {s.get("id") for s in state_.get("sources") or []}
                commands(state_, principal, "source", {"kind": "text", "title": artifact["title"][:200], "text": source_text})
                source = next(s for s in state_["sources"] if s.get("id") not in before)
                source_id = source["id"]
                fact_ids = [f["id"] for f, claim in zip(source["facts"], pack["claims"]) if claim["usableForDraft"]]
                commands(state_, principal, "approve_source", {"sourceId": source_id, "factIds": fact_ids})
                source["origin"] = {"kind": "source_to_campaign", **{k: artifact["provenance"].get(k) for k in ("provider", "accessMethod", "url", "host", "publishedAt", "author", "contentHash", "evidenceType", "representedScope")},
                                    "retrievedAt": artifact["provenance"].get("retrievedAt"), "evidenceId": evidence_id, "factPackId": pack["id"], "format": artifact["format"]}
            created = commands(state_, principal, "raffi_campaign_create", {"goal": goal, "audience": audience or "Not specified",
                                                                             "facts": {f"claim_{i + 1}": c["text"][:200] for i, c in enumerate(usable[:12])},
                                                                             "accountIds": [d["channelId"] for d in destinations]})
            campaign_id = next((c["id"] for c in reversed(((state_.get("raffi") or {}).get("campaignPlanning") or {}).get("campaigns") or []) if c.get("goal") == goal), None)
            record = {"id": record_id, "campaignId": campaign_id, "sourceId": source_id, "evidenceId": evidence_id,
                      "source": {k: artifact[k] for k in ("id", "format", "title", "provenance")}, "factPack": pack, "brief": brief, "angles": angles,
                      "destinations": destinations, "drafts": [], "creativeBriefs": [], "status": "drafting", "createdAt": now, "createdBy": principal}
            state_.setdefault("coworker", {}).setdefault("sourceCampaigns", [])
            state_["coworker"]["sourceCampaigns"] = state_["coworker"]["sourceCampaigns"][-19:] + [record]
            box["record"] = record
            del created
            return record

        self._command(workspace_id, token, create, "edit", "source_campaign.created", record_id, {"claims": len(pack["claims"]), "usable": len(usable)})
        record = box["record"]
        drafts = []
        if usable and record.get("sourceId"):
            ideas = copy.copy(self.hosted.ideas)
            conversation = ideas.create_conversation(workspace_id, token, f"Campaign: {artifact['title'][:80]}")
            conversation_id = conversation["conversationId"]
            angle = angles[0] if angles else None
            material = json.dumps({"brief": {k: brief[k] for k in ("goal", "audience", "coreMessage", "cta")}, "angle": angle,
                                   "claims": [c["text"] for c in usable if not angle or c["claimId"] in angle["claimIds"] or len(angle["claimIds"]) > 1][:8],
                                   "exclusions": "Do not use any claim that is not listed here."}, ensure_ascii=False)
            key = f"source_campaign:{record_id}"
            try:
                with skill_compiler.workflow_context("rafii-source-to-campaign"):
                    ideas.turn(workspace_id, token, conversation_id, {"text": "Write one post per destination from the campaign brief.", "material": material,
                                                                      "materialRef": {"type": "campaign", "id": record["campaignId"]}, "idempotencyKey": key,
                                                                      "sourceIds": [record["sourceId"]], "destinations": destinations, "research": False, "reasoning": "quick",
                                                                      "model": payload.get("model")})
                with self.hosted.connection_factory() as db, db.cursor() as cur:
                    cur.execute("SELECT id::text,status,artifact_hash FROM pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
                    run = cur.fetchone()
                if run and run[1] == "completed":
                    applied = ideas.apply(workspace_id, token, self.repository.get(workspace_id, token)["revision"], run[0], run[2], separate=True,
                                          tag={"sourceCampaignId": record_id})
                    drafts = [{"variantId": c.get("variantId"), "platform": c.get("platform"), "language": c.get("language"), "runId": run[0]}
                              for c in applied.get("variantIds") or [] if isinstance(c, dict) and c.get("variantId")]
            except AlphaError as error:
                drafts = [{"error": str(error)[:200]}]
        state = self._state(workspace_id, token)
        variants = {v["id"]: v for v in state.get("variants") or []}
        claims_text = "\n".join(c["text"] for c in usable)
        for draft in drafts:
            variant = variants.get(draft.get("variantId"))
            if variant:
                result = humanizer.evaluate(variant.get("text") or "", locale=draft["language"], platform=draft["platform"], voice_state=state)
                unsupported = [v for v in humanizer.meaning_diff(claims_text, variant.get("text") or "") if v["code"] in ("number_added", "name_added", "anecdote_added", "feeling_added")]
                draft["quality"] = {"evaluator": result["version"], "meaning": unsupported, "style": result["styleFindings"], "lint": result["stages"]["lint"][:5]}
                draft["status"] = "needs_revision" if unsupported else "ready"
        visual = [d["platform"] for d in destinations if d["platform"] in VISUAL_FIRST]
        creative_plan = creative.plan_assets(state, {"message": brief["coreMessage"], "copy": brief["coreMessage"], "cta": brief.get("cta")}, visual, "image") if visual else None

        def finish(state_, _p):
            target = next(x for x in state_["coworker"]["sourceCampaigns"] if x["id"] == record_id)
            target["drafts"] = drafts
            target["creativeBriefs"] = creative_plan["plans"] if creative_plan else []
            target["status"] = "ready_for_review" if any(d.get("status") in ("ready", "needs_revision") for d in drafts) else ("needs_source" if not usable else "needs_input")
            target["updatedAt"] = self.clock()
            return copy.deepcopy(target)

        def emit(cur, state_, principal):
            target = next(x for x in state_["coworker"]["sourceCampaigns"] if x["id"] == record_id)
            notifications = getattr(self.hosted, "notifications", None)
            if notifications and target["status"] == "ready_for_review":
                notifications.emit(cur, workspace_id=workspace_id, event_type="campaign.drafts_ready", dedupe_key=f"source_campaign:{record_id}", entity_type="source_campaign",
                                   entity_id=record_id, payload={"count": len(drafts), "recipeName": artifact["title"][:80], "href": "/app/queue?view=drafts"}, actor=principal)
            _event(cur, workspace_id, principal, "research.campaign_created", {"sourceCampaignId": record_id, "drafts": len(drafts)}, f"source_campaign:{record_id}")

        self._command(workspace_id, token, finish, "edit", "source_campaign.drafted", record_id, {"drafts": len(drafts)}, after=emit)
        stored = next(x for x in (self._state(workspace_id, token).get("coworker") or {}).get("sourceCampaigns") or [] if x["id"] == record_id)
        return {"sourceCampaign": stored, "verified": stored["status"] in ("ready_for_review", "needs_source", "needs_input") and len(stored["drafts"]) == len(drafts),
                "creative": creative_plan and {"missingAssets": creative_plan["missingAssets"], "compiled": creative_plan["compiled"]}}

    # === Adaptive overlays (WP4) ===================================================================================================
    def overlays_view(self, workspace_id, token):
        self._require("RAFII_ADAPTIVE_SKILLS_ENABLED")
        state = self._state(workspace_id, token)
        items = overlays.all_items(state, self.clock())
        with self.repository.transaction(token, workspace_id) as (cur, _row, _p):
            cur.execute("""SELECT id::text, platform, dimension, statement, confidence, status, sample_a, sample_b, extract(epoch from expires_at) FROM public.pr_strategy_hypotheses
                           WHERE workspace_id=%s AND status IN ('candidate','experiment','supported') ORDER BY created_at DESC LIMIT 20""", (workspace_id,))
            hypotheses = [{"id": r[0], "platform": r[1], "dimension": r[2], "statement": r[3], "confidence": r[4], "status": r[5], "samples": [r[6], r[7]],
                           "expiresAt": float(r[8]) if r[8] else None, "memoryType": "strategy", "causal": False} for r in cur.fetchall()]
        return {"voice": [i for i in items if i["memoryType"] == "voice"], "brand": [i for i in items if i["memoryType"] == "brand"], "strategy": hypotheses,
                "revisions": overlays.revisions(state), "history": (overlays._view(state).get("history") or [])[-30:]}

    def overlay_note(self, workspace_id, token, payload, note_id=None):
        """Owner: add or edit an explicit voice/brand note. Protected policy can never be overlaid."""
        self._require("RAFII_ADAPTIVE_SKILLS_ENABLED")
        from .. import skill_registry
        memory_type = payload.get("memoryType")
        if memory_type not in overlays.MEMORY_TYPES:
            raise AlphaError("Choose voice or brand.", 400)
        statement = _clean(payload.get("statement"), 240)
        if not statement:
            raise AlphaError("Write the note.", 400)
        scope = {k: _clean(v, 60) for k, v in (payload.get("scope") or {}).items() if k in ("platform", "language", "contentTypeId", "audience") and v}
        try:
            skill_registry.validate_overlay({"ruleKey": payload.get("ruleKey") or "", "capability": payload.get("capability")})
        except ValueError as error:
            raise AlphaError(str(error), 400) from error
        now = self.clock()

        def change(state, principal):
            view = overlays.ensure(state)
            if note_id:
                item = next((i for i in view["items"] if i["id"] == note_id), None)
                if item is None:
                    raise AlphaError("Note unavailable.", 404)
                view["history"] = view["history"][-99:] + [{"at": now, "id": note_id, "change": "edited", "before": item.get("statement"), "by": principal}]
                item.update({"statement": statement, "scope": scope, "memoryType": memory_type, "revision": item.get("revision", 1) + 1, "updatedAt": now})
            else:
                item = {"id": "ov_" + hashlib.sha256(f"{now}:{statement}".encode()).hexdigest()[:10], "memoryType": memory_type, "statement": statement, "scope": scope,
                        "status": "active", "revision": 1, "createdAt": now, "updatedAt": now, "createdBy": principal, "ruleKey": _clean(payload.get("ruleKey"), 60) or None}
                view["items"].append(item)
                view["history"] = view["history"][-99:] + [{"at": now, "id": item["id"], "change": "added", "by": principal}]
            view["revision"] += 1
            return copy.deepcopy(item)

        item, _ = self._command(workspace_id, token, change, "owner", "overlay.note_saved", note_id or "new", {"memoryType": memory_type})
        stored = next((i for i in overlays.explicit_items(self._state(workspace_id, token)) if i["id"] == item["id"]), None)
        return {"note": stored, "verified": bool(stored and stored["statement"] == statement)}

    def overlay_status(self, workspace_id, token, item_id, status):
        """Owner: disable/enable a note, or pause/resume/retire a learned preference through preference learning's own
        API (so the writer's memory projection honours it; no parallel ledger)."""
        self._require("RAFII_ADAPTIVE_SKILLS_ENABLED")
        state = self._state(workspace_id, token)
        now = self.clock()
        if any(i["id"] == item_id for i in overlays.explicit_items(state)):
            if status not in ("active", "disabled", "retired"):
                raise AlphaError("Choose active, disabled or retired.", 400)

            def change(state_, principal):
                view = overlays.ensure(state_)
                item = next(i for i in view["items"] if i["id"] == item_id)
                item["status"], item["updatedAt"] = status, now
                view["history"] = view["history"][-99:] + [{"at": now, "id": item_id, "change": status, "by": principal}]
                view["revision"] += 1
            self._command(workspace_id, token, change, "owner", "overlay.note_status", item_id, {"status": status})
            stored = next((i for i in overlays.explicit_items(self._state(workspace_id, token)) if i["id"] == item_id), None)
            return {"id": item_id, "status": stored["status"] if stored else None, "verified": bool(stored and stored["status"] == status)}
        learned = {"active": "active", "disabled": "paused", "paused": "paused", "retired": "retired"}.get(status)
        if learned is None:
            raise AlphaError("Choose active, disabled or retired.", 400)
        learning = self.hosted.learning
        revision = self.repository.get(workspace_id, token)["revision"]
        learning.update_version(self.repository, workspace_id, token, revision, item_id, learned)
        stored = next((i for i in overlays.learned_items(self._state(workspace_id, token), now) if i["id"] == item_id), None)
        return {"id": item_id, "status": stored["status"] if stored else "retired", "verified": (stored is None and learned == "retired") or bool(stored and stored["status"] == learned)}

    def overlay_reset(self, workspace_id, token, scope, confirmed):
        """Owner: forget explicit notes ('notes'), learned preferences ('learned', through preference learning's reset)
        or both. The global skills are untouched either way."""
        self._require("RAFII_ADAPTIVE_SKILLS_ENABLED")
        if confirmed is not True or scope not in ("notes", "learned", "all"):
            raise AlphaError("Choose what to reset and confirm it.", 400)
        now = self.clock()
        if scope in ("notes", "all"):
            def change(state, principal):
                view = overlays.ensure(state)
                view["history"] = view["history"][-99:] + [{"at": now, "change": "reset", "count": len(view["items"]), "by": principal}]
                view["items"], view["meta"] = [], {}
                view["revision"] += 1
            self._command(workspace_id, token, change, "owner", "overlay.reset", scope, {})
        if scope in ("learned", "all"):
            self.hosted.mutate(workspace_id, token, self.repository.get(workspace_id, token)["revision"], "learning_reset", {"confirmed": True})
        state = self._state(workspace_id, token)
        remaining = len(overlays.explicit_items(state)) if scope in ("notes", "all") else 0
        remaining += len([i for i in overlays.learned_items(state, now) if i["status"] in ("active", "paused")]) if scope in ("learned", "all") else 0
        return {"reset": scope, "remaining": remaining, "verified": remaining == 0}

    def overlays_export(self, workspace_id, token):
        view = self.overlays_view(workspace_id, token)
        return {"schema": "rafii.overlays-export.v1", "exportedAt": self.clock(), **view}

    # === Performance learning (WP8) ================================================================================================
    def performance_cron(self, max_workspaces=20, deadline=None):
        if not flags.enabled("RAFII_PERFORMANCE_LEARNING_ENABLED"):
            return {"status": "disabled"}
        from . import performance
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT DISTINCT workspace_id::text FROM public.pr_metric_observations WHERE observed_at > now() - interval '120 days' LIMIT %s", (max_workspaces,))
            workspaces = [r[0] for r in cur.fetchall()]
        out = []
        for workspace_id in workspaces:
            if deadline is not None and time.monotonic() > deadline:
                break
            with self.hosted.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
                row = cur.fetchone()
                if row is None:
                    continue
                result = performance.refresh(cur, workspace_id, row[0], self.clock(), getattr(self.hosted, "notifications", None))
                db.commit()
            out.append({"workspaceId": workspace_id, **result})
        return {"workspaces": out}

    def performance_view(self, workspace_id, token):
        self._require("RAFII_PERFORMANCE_LEARNING_ENABLED")
        from . import performance
        with self.repository.transaction(token, workspace_id) as (cur, row, _p):
            state = self.hosted.ideas._state(row)
            return performance.view(cur, workspace_id, state, self.clock())

    def hypothesis_decide(self, workspace_id, token, hypothesis_id, decision):
        """Owner: run as an experiment, dismiss or mark rejected. Never becomes a voice rule or a learned preference."""
        self._require("RAFII_PERFORMANCE_LEARNING_ENABLED")
        if decision not in ("experiment", "dismissed", "rejected"):
            raise AlphaError("Choose experiment, dismissed or rejected.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from ..permissions import require
            require(self.hosted.ideas._member(row), "owner")
            cur.execute("""UPDATE public.pr_strategy_hypotheses SET status=%s, decided_by=%s, decided_at=now(),
                           experiment = CASE WHEN %s='experiment' THEN jsonb_build_object('startedAt', extract(epoch from now()), 'design', 'alternate the two arms for the next comparable posts') ELSE experiment END
                           WHERE id::text=%s AND workspace_id=%s AND status IN ('candidate','experiment') RETURNING status""", (decision, principal, decision, hypothesis_id, workspace_id))
            changed = cur.fetchone()
            from ..hosted import audit
            audit(cur, workspace_id, principal, "hypothesis.decided", hypothesis_id, {"decision": decision})
            cur.execute("SELECT status, causal FROM public.pr_strategy_hypotheses WHERE id::text=%s AND workspace_id=%s", (hypothesis_id, workspace_id))
            stored = cur.fetchone()
        if stored is None:
            raise AlphaError("Hypothesis unavailable.", 404)
        return {"id": hypothesis_id, "status": stored[0], "causal": stored[1], "verified": bool(changed) and stored[0] == decision}

    # === Listening + engagement (WP9) =============================================================================================
    def listening_view(self, workspace_id, token):
        self._require("RAFII_LISTENING_ENABLED")
        from . import listening
        return listening.view(self._state(workspace_id, token), self.clock())

    def watchlist_save(self, workspace_id, token, payload, watchlist_id=None):
        self._require("RAFII_LISTENING_ENABLED")
        from . import listening
        now = self.clock()
        saved, _ = self._command(workspace_id, token, lambda state, principal: listening.save_watchlist(state, payload, principal, now, watchlist_id), "edit",
                                 "listening.watchlist_saved", watchlist_id or "new", {})
        stored = next((w for w in listening.view(self._state(workspace_id, token), now)["watchlists"] if w["id"] == saved["id"]), None)
        return {"watchlist": stored, "verified": stored is not None}

    def opportunity_decide(self, workspace_id, token, opportunity_id, decision):
        self._require("RAFII_LISTENING_ENABLED")
        from . import listening
        now = self.clock()
        self._command(workspace_id, token, lambda state, principal: listening.decide(state, opportunity_id, decision, principal, now), "edit",
                      "listening.opportunity_decided", opportunity_id, {"decision": decision})
        stored = next((o for o in listening.view(self._state(workspace_id, token), now)["opportunities"] if o["id"] == opportunity_id), None)
        return {"opportunity": stored, "verified": bool(stored and stored["status"] == {"act": "acted", "dismiss": "dismissed"}.get(decision))}

    def retention_sweep(self, limit=5000):
        """Product events expire after 400 days (migration 025's expires_at): delete a bounded batch of expired rows."""
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("""DELETE FROM public.pr_product_events WHERE ctid IN (SELECT ctid FROM public.pr_product_events WHERE expires_at < now() LIMIT %s)""", (limit,))
            removed = cur.rowcount
            db.commit()
        return {"productEventsRemoved": removed}

    def listening_cron(self, max_workspaces=20):
        if not flags.enabled("RAFII_LISTENING_ENABLED"):
            return {"status": "disabled"}
        from . import listening
        return listening.cron(self, max_workspaces)

    def engagement_triage(self, workspace_id, token):
        self._require("RAFII_ENGAGEMENT_COPILOT_ENABLED")
        threads = self.hosted.audience.threads(workspace_id, token)
        result = engagement.triage(threads["threads"], self.clock())
        return {**result, "capabilities": threads.get("capabilities"), "replySendingEnabled": threads.get("replySendingEnabled"), "limits": threads.get("limits")}

    def engagement_draft(self, workspace_id, token, thread_id):
        self._require("RAFII_ENGAGEMENT_COPILOT_ENABLED")
        return engagement.draft_reply(self.hosted, workspace_id, token, thread_id, now=self.clock())

    # === Attention + growth =========================================================================================================
    def attention(self, workspace_id, token):
        from . import attention as attention_module
        if not attention_enabled():   # with the features it summarises off, there is no attention list (the Overview is unchanged)
            raise AlphaError("This Rafii feature isn’t turned on yet.", 404, code="feature_disabled")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            state = self.hosted.ideas._state(row)
            return attention_module.build(cur, workspace_id, principal, self.hosted.ideas._member(row), state, self.clock())

    def growth(self, workspace_id, token):
        from . import growth
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from ..permissions import require
            require(self.hosted.ideas._member(row), "manage_members")
            return growth.metrics(cur, workspace_id, self.hosted.ideas._state(row), self.clock())

    def experiment(self, workspace_id, token, experiment):
        from . import growth
        if not flags.enabled("RAFII_GROWTH_EXPERIMENTS_ENABLED"):
            return {"experiment": experiment, "variant": None, "enabled": False}
        with self.repository.transaction(token, workspace_id) as (cur, _row, principal):
            return growth.assign(cur, experiment, workspace_id, expose=True)


def _clean(value, limit):
    return " ".join(str(value or "").split())[:limit]
