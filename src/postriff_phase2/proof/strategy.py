"""Next-week strategy decisions (PRD R-PROOF-02): deterministic proposals, a versioned decision state machine, scope
matching, and how an accepted decision applies to the next planned week.

A decision is a planning input only. It is scoped to goal / account / language / format, versioned (every change is a
new row in ``pr_strategy_decisions``) and revocable. Accepted and edited decisions are mirrored into a small bounded
projection (``state.coworker.growthLoop.strategy``) so Weekly planning stays a pure function of the workspace; the
table keeps the full history. Nothing here touches identity, voice, brand, learned preferences, approvals or
publishing: a decision can only add context to a slot the person still reviews in Queue.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

KINDS = ("experiment_preference", "brief_topic")
STATUSES = ("proposed", "accepted", "edited", "rejected", "revoked")
IN_EFFECT = ("accepted", "edited")
TRANSITIONS = {"proposed": {"accept": "accepted", "edit": "edited", "reject": "rejected"},
               "accepted": {"edit": "edited", "revoke": "revoked"},
               "edited": {"edit": "edited", "revoke": "revoked"},
               "rejected": {}, "revoked": {}}
SCOPE_FIELDS = ("goalId", "channelId", "language", "contentType")
MAX_ACTIVE = 12
MAX_PROPOSALS = 3
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$")
_CONTENT_TYPE = re.compile(r"^[a-z0-9_]{1,60}$")


def decision_id(workspace_id, kind, key):
    return "sd_" + hashlib.sha256(f"{workspace_id}:{kind}:{key}".encode()).hexdigest()[:20]


def _clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _label(value):
    return str(value or "").replace("_", " ")


# --- proposals ---------------------------------------------------------------------------------------------------------
def proposals(state, workspace_id, brief_actions, now):
    """Every candidate proposal, deterministic for the same records: measured experiment results that were never
    decided, then ideas the person saved from a brief. Each has a stable id, so a rejected or revoked proposal is
    recognised and never offered again; the caller skips decided ids before applying the MAX_PROPOSALS cap, so old
    decisions never crowd out new candidates."""
    from ..coworker import growth_loop
    goal = growth_loop.active_goal(state)
    goal_id = goal["id"] if goal else None
    out = []
    experiments = sorted(growth_loop.view(state).get("experiments") or [], key=lambda e: (-(e.get("updatedAt") or 0), e.get("id") or ""))
    for e in experiments:
        result = e.get("result") or {}
        factor = result.get("supportedFactor")
        if (e.get("status") != "complete" or not factor or e.get("decision") in ("applied", "rejected", "revoked")
                or (e.get("expiresAt") or 0) <= now):
            continue
        cohort = e.get("cohort") or {}
        out.append({"id": decision_id(workspace_id, "experiment_preference", f"{e['id']}:{e.get('hypothesisRevision')}"), "kind": "experiment_preference",
                    "statement": _clean(f"Prefer “{_label(factor)}” for {_label(e.get('dimension'))} on {cohort.get('provider') or 'this account'} posts in "
                                        f"{cohort.get('language') or 'this language'} ({_label(cohort.get('contentTypeId')) or 'this format'}). "
                                        "Observational evidence, not a proven cause.", 240),
                    "scope": {"goalId": goal_id, "channelId": cohort.get("connectionId"), "language": cohort.get("language"), "contentType": cohort.get("contentTypeId")},
                    "basis": {"experimentId": e["id"], "hypothesisRevision": e.get("hypothesisRevision"), "supportedFactor": factor, "dimension": e.get("dimension")}})
    sources = {s.get("id"): s for s in state.get("sources") or [] if s.get("active")}
    for action in brief_actions:
        source_id = next((r.get("id") for r in action.get("outcomeRefs") or [] if r.get("type") == "source"), None)
        source = sources.get(source_id)
        if action.get("action") not in ("accept", "save_idea") or source is None:
            continue
        out.append({"id": decision_id(workspace_id, "brief_topic", action["id"]), "kind": "brief_topic",
                    "statement": _clean(f"Plan one post next week from the saved idea “{_clean(source.get('title'), 80)}”.", 240),
                    "scope": {"goalId": goal_id, "channelId": action.get("channelId"), "language": None, "contentType": None},
                    "basis": {"briefActionId": action["id"], "sourceId": source_id, "itemId": action.get("itemId")}})
    return out


# --- the decision state machine ----------------------------------------------------------------------------------------
def transition(status, action):
    target = TRANSITIONS.get(status, {}).get(action)
    if target is None:
        verb = {"accept": "accepted", "edit": "edited", "reject": "rejected", "revoke": "revoked"}.get(action, "changed")
        raise AlphaError(f"A {status} decision can't be {verb}.", 409, code="invalid_transition")
    return target


def clean_statement(value):
    text = _clean(value, 241)
    if not 3 <= len(text) <= 240:
        raise AlphaError("Write the next-week action in 3–240 characters.", 400)
    return text


def narrow(scope, edits, state):
    """An edit may set a scope field that was open; it never clears or changes one that was set, so an edited
    decision never applies more widely than its evidence."""
    if edits is None:
        return dict(scope)
    if not isinstance(edits, dict) or set(edits) - set(SCOPE_FIELDS):
        raise AlphaError("Scope is goal, account, language and format only.", 400)
    result = dict(scope)
    channels = {c.get("id"): c for c in ((state.get("phase2") or {}).get("channels") or [])}
    goals = {g.get("id") for g in ((state.get("coworker") or {}).get("growthLoop") or {}).get("goals") or []}
    for field, value in edits.items():
        if value is None or value == scope.get(field):
            continue
        if scope.get(field) is not None:
            raise AlphaError("An edit can narrow a decision's scope, not change or widen it.", 409, code="scope_widened")
        if field == "channelId" and (value not in channels or channels[value].get("revoked")):
            raise AlphaError("Choose an account from this workspace.", 400)
        if field == "goalId" and value not in goals:
            raise AlphaError("Choose a goal from this workspace.", 400)
        if field == "language" and (not isinstance(value, str) or not _LANGUAGE.match(value)):
            raise AlphaError("Choose a language tag such as en or zh-Hant.", 400)
        if field == "contentType" and (not isinstance(value, str) or not _CONTENT_TYPE.match(value)):
            raise AlphaError("Choose a content format.", 400)
        result[field] = value
    return result


def _tz(zone_name):
    try:
        return ZoneInfo(zone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def next_week_start(now, zone_name):
    """The Monday 00:00 (local) after `now`."""
    tz = _tz(zone_name)
    local = datetime.fromtimestamp(now, tz).date()
    monday = local - timedelta(days=local.weekday()) + timedelta(days=7)
    return datetime.combine(monday, dtime(0), tzinfo=tz).timestamp(), monday.isoformat()


def planned_weeks(state):
    """The local Mondays (weekOf) that already have a stored weekly plan. A stored week is never planned again, so a
    decision adopted after it was planned cannot reach it."""
    weeks = ((state.get("coworker") or {}).get("weekly") or {}).get("weeks") or []
    return {w.get("weekOf") for w in weeks if isinstance(w, dict) and isinstance(w.get("weekOf"), str)}


def first_unplanned_week(state, now, zone_name, limit=60):
    """(epoch, local date, already planned dates): the first Monday from next week on whose plan is not stored yet —
    the first week an adopted decision can actually apply to — and the weeks before it that were already planned (and
    so do not get it)."""
    tz = _tz(zone_name)
    _epoch, first = next_week_start(now, zone_name)
    monday = datetime.fromisoformat(first).date()
    planned, skipped = planned_weeks(state), []
    while monday.isoformat() in planned and len(skipped) < limit:
        skipped.append(monday.isoformat())
        monday += timedelta(days=7)
    return datetime.combine(monday, dtime(0), tzinfo=tz).timestamp(), monday.isoformat(), skipped


# --- the in-effect projection ------------------------------------------------------------------------------------------
def active(state):
    root = ((state.get("coworker") or {}).get("growthLoop") or {}).get("strategy") or {}
    return [d for d in root.get("decisions") or [] if d.get("status") in IN_EFFECT]


def project(state, record):
    """Mirror one decision version into the bounded projection: in effect → present (latest version), otherwise
    removed. The table row is the authority; this is what planning reads."""
    from ..coworker import growth_loop
    root = growth_loop.root(state).setdefault("strategy", {"revision": 0, "decisions": []})
    decisions = [d for d in root.get("decisions") or [] if d.get("id") != record["id"]]
    if record["status"] in IN_EFFECT:
        if len(decisions) >= MAX_ACTIVE:
            raise AlphaError(f"At most {MAX_ACTIVE} next-week decisions can be in effect. Revoke one first.", 409, code="too_many_active_decisions")
        basis = record.get("basis") or {}
        decisions.append({"id": record["id"], "revision": record["revision"], "status": record["status"], "kind": record["kind"],
                          "statement": record["statement"], "scope": {k: (record.get("scope") or {}).get(k) for k in SCOPE_FIELDS},
                          "appliesFrom": record.get("appliesFrom"), "appliesFromDate": record.get("appliesFromDate"),
                          "basis": {k: basis[k] for k in ("experimentId", "sourceId") if basis.get(k)}, "decidedAt": record.get("decidedAt")})
    root["decisions"] = decisions
    root["revision"] = int(root.get("revision") or 0) + 1
    return root


# --- application to a planned week -------------------------------------------------------------------------------------
def matches(scope, slot):
    scope = scope or {}
    if scope.get("channelId") and scope["channelId"] != slot.get("channelId"):
        return False
    if scope.get("language"):
        want, have = str(scope["language"]).lower(), str(slot.get("language") or "").lower()
        if not (have == want or have.startswith(want + "-") or want.startswith(have + "-") and have):
            return False
    if scope.get("contentType") and scope["contentType"] != slot.get("contentType"):
        return False
    return True


def _context(state):
    """What a decision depends on right now: the active goal, the workspace's accounts and its active sources."""
    from ..coworker import growth_loop
    return (growth_loop.active_goal(state), {c.get("id"): c for c in ((state.get("phase2") or {}).get("channels") or [])},
            {s.get("id") for s in state.get("sources") or [] if s.get("active")})


def unavailable_reason(decision, goal, channels, sources):
    """Why an in-effect decision cannot apply at its current version (source, account or goal gone), or None."""
    scope = decision.get("scope") or {}
    if decision.get("kind") == "brief_topic" and (decision.get("basis") or {}).get("sourceId") not in sources:
        return "source_unavailable"
    if scope.get("channelId") and (scope["channelId"] not in channels or channels[scope["channelId"]].get("revoked")):
        return "account_unavailable"
    if scope.get("goalId") and (goal is None or goal.get("id") != scope["goalId"]):
        return "goal_not_active"
    return None


def apply_to_week(state, slots, week_of):
    """Which in-effect decisions this week applies, to which slots, and why any other cannot apply. An experiment
    preference applies to every matching slot of every week while it is in effect; a brief topic is one post, on the
    first matching slot of the first week planned after it was adopted."""
    goal, channels, sources = _context(state)
    weeks = ((state.get("coworker") or {}).get("weekly") or {}).get("weeks") or []
    planned_before = {d.get("id") for w in weeks if w.get("weekOf") != week_of for d in w.get("appliedDecisions") or []}
    applied, not_applied, by_slot = [], [], {}
    ordered = sorted(slots, key=lambda s: (s.get("localTime") or "", s.get("id") or ""))
    for decision in active(state):
        scope = decision.get("scope") or {}
        reason = None
        if decision.get("appliesFromDate") and week_of < decision["appliesFromDate"]:
            reason = "applies_from_later"
        elif decision.get("kind") == "brief_topic" and decision["id"] in planned_before:
            reason = "already_applied"
        else:
            reason = unavailable_reason(decision, goal, channels, sources)
        eligible = [] if reason else [s for s in ordered if s.get("status") != "channel_unavailable" and matches(scope, s)]
        if not reason and not eligible:
            reason = "no_matching_slot"
        if reason:
            not_applied.append({"id": decision["id"], "revision": decision["revision"], "reason": reason})
            continue
        chosen = eligible if decision.get("kind") == "experiment_preference" else eligible[:1]
        applied.append({"id": decision["id"], "revision": decision["revision"], "kind": decision.get("kind"), "slotIds": [s["id"] for s in chosen]})
        for slot in chosen:
            by_slot.setdefault(slot["id"], []).append({"id": decision["id"], "revision": decision["revision"]})
    return {"appliedDecisions": applied, "notApplied": not_applied, "slotDecisions": by_slot}


def for_slot(state, slot, skip_experiments=()):
    """The decisions a slot's writer receives: those planned onto the slot and still in effect now (a revoked
    decision stops at once), at their current version — and only while that version still fits the slot: an edit
    may have narrowed the scope since the week was planned, and its source, account or goal may be gone. Data for the
    writer, never instructions."""
    planned = {d.get("id") for d in slot.get("strategyDecisions") or [] if isinstance(d, dict)}
    goal, channels, sources = _context(state)
    out = []
    for decision in active(state):
        if decision["id"] not in planned or (decision.get("basis") or {}).get("experimentId") in skip_experiments:
            continue
        if not matches(decision.get("scope"), slot) or unavailable_reason(decision, goal, channels, sources):
            continue
        out.append({"decisionId": decision["id"], "revision": decision["revision"], "kind": decision["kind"], "statement": decision["statement"],
                    "scope": {k: v for k, v in (decision.get("scope") or {}).items() if v}, "causal": False})
    return out[:5]
