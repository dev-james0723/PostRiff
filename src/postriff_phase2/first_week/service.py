"""First Week Ready: one guided, resumable path from the person's own material to a reviewed, deliverable week.

The journey stores references only (`state.coworker.firstWeek`): source, draft and Weekly recipe/week ids, the accepted
draft revision, the frozen scope and assisted handoffs. Drafts live in `state.variants`, weeks in the Weekly Operator,
approvals and publishing in Queue — this module never keeps a second copy of any of them, never approves, schedules or
publishes, and never spends without the existing credit quote. Its own revision counter guards every change.

Accept a draft, approve a week's scope and authorize an exact publication are three different actions; only the first
two happen here. Scheduling and publication states are always read back from Queue.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import re
import time

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError, uid

from .. import growth_events
from ..coworker import weekly_operator

FLAG = "RAFII_FIRST_WEEK_ENABLED"
MAX_TEXT = 8000                 # the anonymous Post Doctor's own input limit
DEFAULT_POSTS = 3
MAX_POSTS = 3                   # the first week's default is also its ceiling; Weekly keeps its own limits afterwards
LANGUAGES = ("en", "zh-HK", "zh-TW", "zh-CN", "other")
SELECTIONS = ("original", "edited")
MAX_IMPORTS = 20
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
HANDOFF_STATES = ("export_ready", "user_confirmed_used")
STEPS = ("source", "context", "draft", "accept", "plan", "scope", "drafting", "review", "deliver")


def enabled(values=None):
    values = os.environ if values is None else values
    return values.get(FLAG) == "1"


def root(state):
    coworker = state.setdefault("coworker", {})
    journey = coworker.setdefault("firstWeek", {})
    journey.setdefault("revision", 0)
    journey.setdefault("imports", {})
    return journey


def journey_of(state):
    return copy.deepcopy(((state.get("coworker") or {}).get("firstWeek")) or {"revision": 0, "imports": {}})


def _text(value, name="text"):
    if not isinstance(value, str):
        raise AlphaError(f"Add the {name}.", 400, code="unsupported_input")
    text = value.replace("\x00", "").replace("\r\n", "\n").strip()
    if not text:
        raise AlphaError("Add some text first.", 400, code="unsupported_input")
    if len(text) > MAX_TEXT:   # refuse rather than silently truncate the person's words
        raise AlphaError(f"This draft is {len(text):,} characters; the limit here is {MAX_TEXT:,}. Shorten it and try again.", 400, code="unsupported_input")
    return text


def _expected(journey, body):
    expected = body.get("expectedRevision")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise AlphaError("Reload your first week and try again.", 409, code="revision_conflict")
    if expected != journey.get("revision", 0):
        raise AlphaError("Your first week changed in another tab. Reload it and try again.", 409, code="revision_conflict")


def new_variant(state, text, platform, language, source_id, principal, origin, now, *, slot=None):
    """A canonical draft from the person's own words: the same shape the writer's `apply` stores, with provenance that
    says no model wrote it. Free of charge — nothing is generated."""
    speaker = state.get("speaker") or {}
    variant = {"id": uid(), "revision": 1, "platform": platform, "language": language, "text": text,
               "sourceIds": [source_id] if source_id else [], "voiceSourceIds": [], "voiceBindings": [], "unknowns": [], "warnings": [],
               "openings": [], "voiceRevision": speaker.get("activeRevision"), "styleRevision": learning.revision(state),
               "briefRevision": (state.get("brief") or {}).get("revision"), "runId": None, "speakerId": speaker.get("id"),
               "customized": True, "needsReview": True, "blockedByRetraction": False, "selectedOpening": 0, "localPreferences": {},
               "revisions": [{"revision": 1, "text": text, "origin": origin}],
               "provenance": {"origin": origin, "author": "person", "model": None, "importedBy": principal, "importedAt": now}}
    if slot:
        variant["automation"] = {"weekPlanId": slot["weekId"], "slotId": slot["slotId"]}
    state.setdefault("variants", []).append(variant)
    return variant


class FirstWeekService:
    def __init__(self, hosted, values=None, clock=None):
        self.hosted = hosted
        self.values = os.environ if values is None else values
        self.clock = clock or getattr(hosted, "clock", None) or time.time

    # --- plumbing ------------------------------------------------------------------------------------------------------
    @property
    def repository(self):
        return self.hosted.repository

    def _require(self):
        if not enabled(self.values):
            raise AlphaError("First Week Ready is not available yet.", 404, code="feature_disabled")

    def _coworker(self):
        from ..coworker import runtime as coworker_runtime
        coworker_runtime.ensure(self.hosted)
        return self.hosted.coworker

    def _command(self, workspace_id, token, fn, requirement, audit_kind, subject="", meta=None, after=None):
        """repository.command with one retry on a workspace-wide revision conflict (the journey's own revision is what
        the person's request is checked against)."""
        box = {}

        def trusted(state, principal):
            box["result"] = fn(state, principal)
            return state

        for attempt in range(2):
            revision = self.repository.get(workspace_id, token)["revision"]
            try:
                self.repository.command(workspace_id, token, revision, trusted, requirement=requirement,
                                        audit_event=lambda _s: (audit_kind, str(subject)[:200], meta or {}), after=after)
                return box.get("result")
            except AlphaError as error:
                if getattr(error, "code", None) == "workspace_revision_conflict" and attempt == 0:
                    continue
                raise
        raise AlphaError("The workspace changed while saving. Try again.", 409, code="revision_conflict")

    def _mode(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            ledger = self.hosted.ledger
            ledger.ensure_entitlement(cur, workspace_id, None)
            return ledger.growth_mode(cur, workspace_id) if hasattr(ledger, "growth_mode") else "legacy"

    # --- R-FWR-01: consented continuation --------------------------------------------------------------------------------
    def import_continuation(self, workspace_id, token, body):
        """`continue_source`: the person's consented Post Doctor text becomes a canonical source and draft in the workspace
        they chose. Idempotent per workspace and continuation key: a replay returns the same ids; the same key with other
        text is refused. The key is opaque and never authorizes anything — the session does."""
        self._require()
        key = body.get("idempotencyKey")
        if not isinstance(key, str) or not _KEY.match(key):
            raise AlphaError("This continuation link is not valid. Paste your draft again.", 400, code="unsupported_input")
        if body.get("consent") is not True:
            raise AlphaError("Confirm that Rafii may keep this draft in your workspace.", 400, code="consent_required")
        items = body.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 2:
            raise AlphaError("Choose the original or edited draft (or both).", 400, code="unsupported_input")
        selected = []
        for item in items:
            kind = item.get("kind") if isinstance(item, dict) else None
            if kind not in SELECTIONS or any(k == kind for k, _ in selected):
                raise AlphaError("Choose the original or edited draft (or both).", 400, code="unsupported_input")
            selected.append((kind, _text(item.get("text"), "draft")))
        platform = body.get("platform")
        if platform not in weekly_operator.FIRST_WEEK_PLATFORMS:
            raise AlphaError("Choose a supported platform.", 400, code="unsupported_input")
        language = body.get("language") if body.get("language") in LANGUAGES else "en"
        digest = hashlib.sha256(json.dumps({"items": selected, "platform": platform, "language": language}, ensure_ascii=False).encode()).hexdigest()
        key_hash = hashlib.sha256(("continuation:" + key).encode()).hexdigest()[:32]
        now = self.clock()

        def change(state, principal):
            journey = root(state)
            prior = journey["imports"].get(key_hash)
            if prior:
                if prior["digest"] != digest:
                    raise AlphaError("This continuation was already used for a different draft.", 409, code="idempotency_conflict")
                return {**prior, "replayed": True}
            primary = dict(selected).get("edited") or dict(selected)["original"]
            source = self.hosted.ideas._quick_start_source(state, principal, {"title": "My Post Doctor draft"}, primary, None, True)
            variants = {kind: new_variant(state, text, platform, language, source["id"], principal, f"continuation:{kind}", now)["id"]
                        for kind, text in selected}
            draft_id = variants.get("edited") or variants["original"]
            record = {"digest": digest, "sourceId": source["id"], "variantIds": variants, "draftVariantId": draft_id, "importedAt": now}
            if len(journey["imports"]) >= MAX_IMPORTS:
                oldest = min(journey["imports"], key=lambda k: journey["imports"][k]["importedAt"])
                journey["imports"].pop(oldest)
            journey["imports"][key_hash] = record
            if not journey.get("draftVariantId"):
                journey.update({"startedAt": now, "sourceId": source["id"], "draftVariantId": draft_id, "platform": platform, "language": language,
                                "continuation": {"origin": "post_doctor", "selection": "+".join(k for k, _ in selected), "importedAt": now}})
            journey["revision"] += 1
            return {**record, "replayed": False}

        # Product events dedupe globally on (event, entity, revision): the entity is this workspace's claim, so the same
        # continuation imported into two workspaces is two claims, and a replay in one workspace stays one.
        claim_id = hashlib.sha256(f"continuation:{workspace_id}:{key}".encode()).hexdigest()[:32]

        def emitted(cur, state, principal):
            growth_events.emit(cur, workspace_id=workspace_id, event="continuation.claimed", entity_id=claim_id, revision=0, user_id=principal,
                               values={"source": "post_doctor", "selection": "-".join(k for k, _ in selected), "outcome": "imported"})

        result = self._command(workspace_id, token, change, "edit", "first_week.continuation_imported", key_hash, {"items": len(selected)}, after=emitted)
        return {**{k: result[k] for k in ("sourceId", "variantIds", "draftVariantId", "replayed")}, "journey": self.view(workspace_id, token)}

    def start_from_text(self, workspace_id, token, body):
        """Signed-in start (no anonymous step): the same import, from text pasted in the app."""
        return self.import_continuation(workspace_id, token, {**body, "items": [{"kind": "original", "text": body.get("text")}]})

    # --- context, draft acceptance ----------------------------------------------------------------------------------------
    def set_context(self, workspace_id, token, body):
        """Ask only for what is missing: purpose and audience go through the existing Brand Brain `context` command."""
        self._require()
        purpose, audience = body.get("purpose"), body.get("audience")
        if not all(isinstance(v, str) and v.strip() for v in (purpose, audience)):
            raise AlphaError("Add what the posts are for and who they help.", 400, code="unsupported_input")
        mode = body.get("mode") if body.get("mode") in ("personal", "business") else "personal"

        def change(state, principal):
            journey = root(state)
            _expected(journey, body)
            brand = state.get("brandHub") or {}
            if brand.get("mode") not in ("personal", "niche", "business", "hybrid"):
                self.hosted.ideas.commands(state, principal, "mode", {"mode": mode})
                brand = state.get("brandHub") or {}
            fields = {"purpose": purpose.strip()[:1500], "audience": audience.strip()[:1500]}
            if brand.get("mode") in ("niche", "business", "hybrid"):
                subject = (body.get("subject") or brand.get("subject") or "").strip()
                if not subject:
                    raise AlphaError("Add the subject or business these posts draw from.", 400, code="unsupported_input")
                fields["subject"] = subject[:1500]
                if brand.get("mode") == "hybrid":
                    fields["speaker"] = brand.get("speaker") or ""
                    fields["layers"] = brand.get("layers") or []
            self.hosted.ideas.commands(state, principal, "context", fields)
            journey["revision"] += 1
            return True

        self._command(workspace_id, token, change, "edit", "first_week.context_set")
        return self.view(workspace_id, token)

    def accept_draft(self, workspace_id, token, body):
        """Explicit acceptance of one real draft revision ("accept this draft" — not an approval to publish)."""
        self._require()
        variant_id, variant_revision = body.get("variantId"), body.get("variantRevision")
        if not isinstance(variant_id, str) or not isinstance(variant_revision, int) or isinstance(variant_revision, bool):
            raise AlphaError("Choose the draft revision you accept.", 400, code="unsupported_input")
        now = self.clock()
        box = {}

        def change(state, principal):
            journey = root(state)
            _expected(journey, body)
            variant = next((v for v in state.get("variants") or [] if v.get("id") == variant_id), None)
            if variant is None:
                raise AlphaError("That draft isn't in this workspace.", 404)
            if variant.get("revision") != variant_revision:
                raise AlphaError("The draft changed since you read it. Review the latest version.", 409, code="revision_conflict")
            if variant.get("blockedByRetraction"):
                raise AlphaError("A source behind this draft was withdrawn. Edit or replace it first.", 409, code="source_unavailable")
            journey["accepted"] = {"variantId": variant_id, "revision": variant_revision, "at": now, "by": principal}
            journey["draftVariantId"] = variant_id
            journey["revision"] += 1
            box["first"] = not journey.get("firstAcceptedAt")
            journey.setdefault("firstAcceptedAt", now)
            return True

        def emitted(cur, state, principal):
            origin = ((next((v for v in state.get("variants") or [] if v.get("id") == variant_id), {}) or {}).get("provenance") or {}).get("origin") or "writer"
            growth_events.emit(cur, workspace_id=workspace_id, event="draft.accepted", entity_id=variant_id, revision=variant_revision, user_id=principal,
                               values={"origin": origin.split(":")[0].replace("_", "-"), "revision": variant_revision})

        self._command(workspace_id, token, change, "edit", "first_week.draft_accepted", variant_id, {"revision": variant_revision}, after=emitted)
        return self.view(workspace_id, token)

    # --- R-FWR-02: the suggested week ---------------------------------------------------------------------------------------
    def plan(self, workspace_id, token, body):
        """`prepare_first_week`: a deterministic plan of up to three posts on one channel, built by the Weekly Operator.
        Planning never drafts or spends. The accepted draft becomes the week's first post."""
        self._require()
        coworker = self._coworker()
        coworker._require("RAFII_WEEKLY_OPERATOR_ENABLED")
        state = self.repository.get(workspace_id, token)["state"]
        journey = journey_of(state)
        _expected(journey, body)
        if not journey.get("accepted"):
            raise AlphaError("Accept one draft before planning the week.", 409, code="approval_required")
        if journey.get("scope"):
            # The committed week is frozen; planning again would re-save its recipe (and limit) behind the person's back.
            raise AlphaError("Your first week is already committed. Change its posts instead of planning again.", 409, code="approval_required")
        posts = body.get("postsPerWeek", DEFAULT_POSTS)
        if not isinstance(posts, int) or isinstance(posts, bool) or not 1 <= posts <= MAX_POSTS:
            raise AlphaError(f"Your first week plans 1–{MAX_POSTS} posts.", 400, code="unsupported_input")
        channel_id = body.get("channelId")
        platform = body.get("platform") or journey.get("platform")
        channels = {c.get("id"): c for c in ((state.get("phase2") or {}).get("channels") or []) if not c.get("revoked")}
        if channel_id is not None:
            channel = channels.get(channel_id)
            if channel is None:
                raise AlphaError("Choose an account connected to this workspace.", 400, code="channel_unavailable")
            platform = channel.get("platform")
        language = body.get("language") if body.get("language") in LANGUAGES else journey.get("language") or "en"
        brand = state.get("brandHub") or {}
        goal = (brand.get("purpose") or "Share what I know").strip()[:160]
        recipe_payload = {"name": "First week", "goals": [goal], "firstWeek": True, "timeZone": body.get("timeZone") or "UTC",
                          "destinations": [{"channelId": channel_id, "platform": platform, "language": language, "postsPerWeek": posts}],
                          "sourceIds": [journey["sourceId"]] if journey.get("sourceId") else [], "maxCostUsdMicroPerWeek": 0,
                          "contentMix": {"tutorial_how_to": 1.0, "deep_point_of_view": 1.0}}
        saved = coworker.weekly_save_recipe(workspace_id, token, recipe_payload, journey.get("recipeId"))
        recipe = saved["recipe"]
        now = self.clock()
        planned = weekly_operator.plan_week(self.repository.get(workspace_id, token)["state"], recipe, now)
        accepted = journey["accepted"]

        def change(state, principal):
            current = root(state)
            _expected(current, body)
            weekly = weekly_operator.root(state)
            existing = next((w for w in weekly["weeks"] if w["id"] == planned["id"]), None)
            if existing is not None and not current.get("scope"):
                weekly["weeks"].remove(existing)   # nothing committed yet: re-planning replaces the suggestion
                existing = None
            week = existing
            if week is None:
                week = copy.deepcopy(planned)
                draft = next((v for v in state.get("variants") or [] if v.get("id") == accepted["variantId"]), None)
                # The accepted draft is the week's first post (no new draft, no spend) when it was written for this platform.
                if week["slots"] and draft is not None and draft.get("platform") == platform:
                    first = week["slots"][0]
                    first.update({"variantId": draft["id"], "status": "ready", "reason": None, "question": None, "origin": "accepted_draft"})
                    if channel_id and not draft.get("channelId"):
                        draft["channelId"] = channel_id   # a destination binding, not content: no revision change
                weekly["weeks"] = weekly["weeks"][-11:] + [week]
                weekly["revision"] += 1
            stored = next((r for r in weekly["recipes"] if r["id"] == recipe["id"]), None)
            if stored is not None and weekly_operator.first_week_only(stored) and stored.get("firstWeekId") != week["id"]:
                stored["firstWeekId"] = week["id"]   # the one week this recipe may plan and draft (never due for cron)
                weekly["revision"] += 1
            current.update({"recipeId": recipe["id"], "weekId": week["id"], "platform": platform, "language": language,
                            "channelId": channel_id, "plannedAt": current.get("plannedAt") or now})
            current["revision"] += 1
            return week["id"]

        self._command(workspace_id, token, change, "edit", "first_week.week_planned", planned["id"], {"posts": posts, "connected": channel_id is not None})
        return self.view(workspace_id, token)

    def approve_scope(self, workspace_id, token, body):
        """Freeze the committed scope (the slots this week promises). Later changes are explicit, versioned and audited,
        so a completion rate is never improved by silently dropping a slot."""
        self._require()
        slot_ids = body.get("slotIds")
        if not isinstance(slot_ids, list) or not slot_ids or any(not isinstance(s, str) for s in slot_ids):
            raise AlphaError("Choose the posts this week commits to.", 400, code="unsupported_input")
        reason = " ".join(str(body.get("reason") or "").split())[:200] or None
        now = self.clock()
        box = {}

        def change(state, principal):
            journey = root(state)
            _expected(journey, body)
            week = next((w for w in weekly_operator.root(state)["weeks"] if w["id"] == journey.get("weekId")), None)
            if week is None:
                raise AlphaError("Plan the week first.", 409, code="approval_required")
            known = {s["id"] for s in week["slots"]}
            if not set(slot_ids) <= known:
                raise AlphaError("Choose posts from this week's plan.", 400, code="unsupported_input")
            scope = journey.get("scope")
            if scope and scope.get("slotIds") == sorted(slot_ids):
                box["changed"] = False
                return scope
            for slot in week["slots"]:
                if slot["id"] not in slot_ids and slot["status"] not in ("rejected", "published", "scheduled"):
                    slot["status"], slot["reason"] = "rejected", "Not in this week's committed plan"
                elif slot["id"] in slot_ids and slot["status"] == "rejected" and slot.get("reason") == "Not in this week's committed plan":
                    slot["status"], slot["reason"] = ("ready" if slot.get("variantId") else "planned"), None
            weekly_operator.root(state)["revision"] += 1
            history = (scope or {}).get("changes") or []
            if scope:
                if not reason:
                    raise AlphaError("Say why the committed plan changes.", 400, code="unsupported_input")
                history = history[-20:] + [{"at": now, "by": principal, "from": scope["slotIds"], "to": sorted(slot_ids), "reason": reason}]
            journey["scope"] = {"weekId": week["id"], "slotIds": sorted(slot_ids), "scopeRevision": (scope or {}).get("scopeRevision", 0) + 1,
                                "frozenAt": (scope or {}).get("frozenAt") or now, "approvedBy": principal, "changes": history}
            journey["revision"] += 1
            box["changed"], box["first"], box["scope"] = True, scope is None, journey["scope"]
            return journey["scope"]

        def emitted(cur, state, principal):
            if not box.get("changed"):
                return
            scope = box["scope"]
            event = "week.scope_approved" if box["first"] else "week.scope_changed"
            values = {"mode": "first-week", "slots": len(scope["slotIds"])} if box["first"] else {"change": "resized", "slots": len(scope["slotIds"])}
            growth_events.emit(cur, workspace_id=workspace_id, event=event, entity_id=scope["weekId"], revision=scope["scopeRevision"], user_id=principal, values=values)

        self._command(workspace_id, token, change, "edit", "first_week.scope_approved", "scope", {"slots": len(slot_ids)}, after=emitted)
        return self.view(workspace_id, token)

    def draft_week(self, workspace_id, token, body):
        """Draft the remaining committed posts of the first week, once. Managed credits: the owner confirms a credit limit
        for this week and every post is drafted against its own quote inside it. Legacy: the plan's writing allowance,
        within the Weekly Operator's default cost limit for this week. Free: no managed writing — write the posts yourself
        or upgrade. The limit covers this frozen week only: the recipe stays one-time (never due for cron, refused for any
        other week) until the owner turns on weekly drafting in Weekly plan."""
        self._require()
        if body.get("confirmed") is not True:
            raise AlphaError("Confirm the credit limit before drafting.", 400, code="approval_required")
        state = self.repository.get(workspace_id, token)["state"]
        journey = journey_of(state)
        _expected(journey, body)
        if not journey.get("scope"):
            raise AlphaError("Approve which posts this week commits to first.", 409, code="approval_required")
        mode = self._mode(workspace_id, token)
        if mode == "free":
            raise AlphaError("Free plans don't include AI drafting. Write the remaining posts yourself, or upgrade to Creator.", 402,
                             code="insufficient_budget")
        coworker = self._coworker()
        recipe = next((r for r in weekly_operator.view(state)["recipes"] if r["id"] == journey.get("recipeId")), None)
        week = next((w for w in weekly_operator.view(state)["weeks"] if w["id"] == journey.get("weekId")), None)
        if recipe is None or week is None:
            raise AlphaError("Plan the week first.", 409, code="approval_required")
        # A recipe the owner has since made recurring keeps the owner's own weekly limit; it is never turned back.
        one_time = weekly_operator.first_week_only(recipe)
        if one_time and mode == "legacy" and not int(recipe.get("maxCostUsdMicroPerWeek") or 0):
            payload = {k: recipe[k] for k in ("name", "goals", "destinations", "contentMix", "sourceIds", "planningDay", "planningHour", "timeZone", "voiceMode", "model")}
            payload.update(firstWeek=True, maxCostUsdMicroPerWeek=2_000_000)   # the Weekly Operator's own default limit, this week only
            coworker.weekly_save_recipe(workspace_id, token, payload, recipe["id"])
        if one_time and mode == "managed_credits":
            limit = body.get("maxCredits")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3500:
                raise AlphaError("Set this week's credit limit (1–3,500 credits).", 400, code="insufficient_budget")
            usd_micro = (limit * 1_000_000) // 300   # 300 credits = US$1 of verified provider cost
            payload = {k: recipe[k] for k in ("name", "goals", "destinations", "contentMix", "sourceIds", "planningDay", "planningHour", "timeZone", "voiceMode", "model")}
            payload.update(firstWeek=True, maxCostUsdMicroPerWeek=usd_micro)
            coworker.weekly_save_recipe(workspace_id, token, payload, recipe["id"])
        # Always the committed week (its own Monday), even after the calendar has moved on: never "next week".
        result = coworker.weekly_prepare(workspace_id, token, recipe["id"], max_slots=2, week_of=datetime.date.fromisoformat(week["weekOf"]))
        return {"prepare": {k: result.get(k) for k in ("advanced", "drafted", "draftedSlotIds")}, "journey": self.view(workspace_id, token)}

    def write_slot(self, workspace_id, token, body):
        """Write a planned post yourself (any plan; free). The text becomes a canonical draft linked to the slot."""
        self._require()
        week_id, slot_id = body.get("weekId"), body.get("slotId")
        text = _text(body.get("text"), "post")
        now = self.clock()

        def change(state, principal):
            journey = root(state)
            _expected(journey, body)
            week = next((w for w in weekly_operator.root(state)["weeks"] if w["id"] == week_id and w["id"] == journey.get("weekId")), None)
            slot = next((s for s in (week or {}).get("slots") or [] if s["id"] == slot_id), None)
            if slot is None:
                raise AlphaError("That post isn't in your first week.", 404)
            if slot["status"] in ("in_queue", "approved", "scheduled", "published"):
                raise AlphaError("This post is already in Queue. Edit it there.", 409, code="approval_required")
            variant = new_variant(state, text, slot["platform"], slot["language"], (slot.get("sourceIds") or [None])[0], principal, "first_week:manual", now,
                                  slot={"weekId": week_id, "slotId": slot_id})
            slot.update({"variantId": variant["id"], "status": "ready", "reason": None, "question": None, "origin": "person"})
            if week["state"] == "planned" and not any(s["status"] in ("planned", "drafted") for s in week["slots"]):
                # The Weekly state machine has no shortcut to review; the history says the person wrote these posts.
                weekly_operator.transition(week, "generating", now, "posts written by the person")
            weekly_operator.settle(week, now)
            weekly_operator.root(state)["revision"] += 1
            journey["revision"] += 1
            return variant["id"]

        self._command(workspace_id, token, change, "edit", "first_week.slot_written", slot_id)
        return self.view(workspace_id, token)

    def handoff(self, workspace_id, token, body):
        """Assisted delivery for a post Rafii can't publish here (Free, unconnected or unsupported): `export_ready` when
        the person takes the text, `user_confirmed_used` when they say they posted it. Neither is a verified publication."""
        self._require()
        week_id, slot_id, action = body.get("weekId"), body.get("slotId"), body.get("action")
        if action not in HANDOFF_STATES + ("undo",):
            raise AlphaError("Choose export_ready, user_confirmed_used or undo.", 400, code="unsupported_input")
        now = self.clock()

        def change(state, principal):
            journey = root(state)
            _expected(journey, body)
            week = next((w for w in weekly_operator.root(state)["weeks"] if w["id"] == week_id and w["id"] == journey.get("weekId")), None)
            slot = next((s for s in (week or {}).get("slots") or [] if s["id"] == slot_id), None)
            if slot is None or not slot.get("variantId"):
                raise AlphaError("Only a written post can be handed off.", 409, code="approval_required")
            if slot["status"] in ("scheduled", "published"):
                raise AlphaError("Rafii is already publishing this post through Queue.", 409, code="approval_required")
            handoffs = journey.setdefault("handoffs", {})
            if action == "undo":
                handoffs.pop(slot_id, None)
            else:
                variant = next((v for v in state.get("variants") or [] if v.get("id") == slot["variantId"]), {})
                handoffs[slot_id] = {"state": action, "at": now, "by": principal, "variantId": slot["variantId"], "variantRevision": variant.get("revision")}
            journey["revision"] += 1
            return True

        self._command(workspace_id, token, change, "edit", f"first_week.handoff_{action}", slot_id)
        return self.view(workspace_id, token)

    # --- R-FWR-03: one read model to resume from ----------------------------------------------------------------------
    def view(self, workspace_id, token):
        self._require()
        state = self.repository.get(workspace_id, token)["state"]
        journey = journey_of(state)
        journey.pop("imports", None)
        brand = state.get("brandHub") or {}
        variants = {v["id"]: v for v in state.get("variants") or []}
        draft = variants.get(journey.get("draftVariantId"))
        accepted = journey.get("accepted")
        accepted_current = bool(accepted and draft and accepted["variantId"] == draft["id"] and accepted["revision"] == draft.get("revision"))
        week = None
        if journey.get("weekId"):
            try:
                week = self._coworker().weekly_week(workspace_id, token, journey["weekId"])["week"]
            except AlphaError:
                week = None
        mode = self._mode(workspace_id, token)
        scope = journey.get("scope") or {}
        handoffs = journey.get("handoffs") or {}
        slots = []
        for slot in (week or {}).get("slots") or []:
            variant = variants.get(slot.get("variantId"))
            handoff = handoffs.get(slot["id"])
            if handoff and variant and handoff.get("variantRevision") != variant.get("revision"):
                handoff = {**handoff, "stale": True}   # an edit after export means the exported text is not this one
            slots.append({"id": slot["id"], "day": slot.get("day"), "localTime": slot.get("localTime"), "timeZone": slot.get("timeZone"),
                          "platform": slot.get("platform"), "language": slot.get("language"), "channelId": slot.get("channelId"),
                          "status": slot.get("status"), "reason": slot.get("reason"), "question": slot.get("question"),
                          "publishBlocker": slot.get("publishBlocker"), "costState": slot.get("costState") or ("requires_upgrade" if mode == "free" and not slot.get("variantId") else None),
                          "needsAsset": slot.get("status") == "needs_asset", "sourceIds": slot.get("sourceIds") or [], "contentType": slot.get("contentType"),
                          "committed": slot["id"] in (scope.get("slotIds") or []), "variantId": slot.get("variantId"),
                          "draft": ({"text": variant.get("text"), "revision": variant.get("revision"), "needsReview": variant.get("needsReview"),
                                     "origin": (variant.get("provenance") or {}).get("origin")} if variant else None),
                          "handoff": handoff, "nextAction": _slot_next(slot, handoff, mode)})
        committed = [s for s in slots if s["committed"]]
        delivered = [s for s in committed if s["status"] == "published" or (s["handoff"] or {}).get("state") == "user_confirmed_used" and not (s["handoff"] or {}).get("stale")]
        complete = bool(committed) and len(delivered) == len(committed)
        missing = [k for k in ("purpose", "audience") if not (brand.get(k) or "").strip()]
        if brand.get("mode") in ("niche", "business", "hybrid") and not (brand.get("subject") or "").strip():
            missing.append("subject")   # set_context refuses these modes without the subject the posts draw from
        recipe = next((r for r in weekly_operator.view(state)["recipes"] if r.get("id") == journey.get("recipeId")), None)
        weekly_drafting = None if recipe is None else "first_week_only" if weekly_operator.first_week_only(recipe) else "recurring"
        step = ("source" if not draft else "context" if missing else "accept" if not accepted_current else "plan" if not journey.get("weekId")
                else "scope" if not scope else "review" if any(s["status"] in ("planned", "needs_input", "needs_source", "drafted", "needs_revision", "ready") for s in committed)
                else "deliver" if not complete else "complete")
        return {"enabled": True, "revision": journey.get("revision", 0), "step": step, "billingMode": {"free": "free_preview", "managed_credits": "managed_credits"}.get(mode, "legacy_allowances"),
                "missingContext": missing, "context": {"purpose": brand.get("purpose") or None, "audience": brand.get("audience") or None, "mode": brand.get("mode") or None,
                                                       "subject": brand.get("subject") or None},
                # "first_week_only": the first week's limit drafts that one week; later weeks wait for Weekly plan.
                "weeklyDrafting": weekly_drafting,
                "source": {"id": journey.get("sourceId"), "origin": (journey.get("continuation") or {}).get("origin")} if journey.get("sourceId") else None,
                "draft": ({"variantId": draft["id"], "revision": draft.get("revision"), "text": draft.get("text"), "platform": draft.get("platform"),
                           "language": draft.get("language"), "accepted": accepted_current, "acceptedRevision": (accepted or {}).get("revision")} if draft else None),
                "week": ({"id": week["id"], "weekOf": week.get("weekOf"), "state": week.get("state"), "blockedReason": week.get("blockedReason")} if week else None),
                "scope": ({k: scope.get(k) for k in ("slotIds", "scopeRevision", "frozenAt", "changes")} if scope else None),
                "slots": slots, "delivered": len(delivered), "committed": len(committed), "complete": complete,
                "queueHref": "/app/queue?view=drafts", "channelConnected": bool(journey.get("channelId")),
                "notes": ["Accepting a draft or a week never publishes anything. Scheduling and publishing happen only in Queue after you approve each post.",
                          "A post you copy and use yourself is counted as an assisted handoff, never as a verified publication."]}


def _slot_next(slot, handoff, mode):
    status = slot.get("status")
    if status in ("needs_input", "needs_source"):
        return "answer"
    if status == "planned":
        return "write_or_upgrade" if mode == "free" else "draft"
    if status in ("ready", "needs_revision", "needs_asset"):
        return "review"
    if status == "accepted":
        return "connect_account" if slot.get("publishBlocker") == "channel_not_connected" else "approve_in_queue"
    if status in ("in_queue", "approval_expired"):
        return "approve_in_queue"
    if status in ("approved", "scheduled"):
        return "wait_for_publish"
    if status == "published":
        return "done"
    if handoff and handoff.get("state") == "export_ready":
        return "confirm_used"
    return None
