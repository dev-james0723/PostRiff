"""Pure Growth Loop proof v2 rules (PRD R-PROOF-01, R-MET-01).

A proof covers one completed civil period (weekly Monday–Monday or a calendar month) in the workspace's zone. Its
figures each carry a definition, a data state and the scoped evidence ids they count; different things stay
separate (accepted work, verified publications, assisted exports, unresolved slots, outcomes by provenance, Time
Back by confidence class, actual versus unknown provider cost). A recomputation whose material figures changed
becomes a new revision with a correction note; the earlier revision is kept.

Workspace zone rule (documented once, used everywhere): the zone of the earliest-created active weekly recipe (the
zone the work week is planned in); else the owner's notification-preference zone; else the owner's profile zone;
else UTC.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFINITION_VERSION = "rafii.proof.v2.2026-10-01"
MATURITY_SECONDS = 72 * 3600           # late Queue read-backs, provider metrics and cost settlements usually land by then
FREQUENCIES = ("weekly", "monthly")
EVIDENCE_LIMIT = 100                   # ids shown per evidence list (totals stay exact; truncation is flagged)
MAX_COUNTS_BYTES = 240_000             # below the 256 KiB column check in 084, so a busy period can never fail to store
CORRECTION_VALUE_BYTES = 400           # a larger before/after value is recorded as changed, not copied
FIGURES = ("acceptedWork", "verifiedPublications", "assistedExports", "unresolvedSlots", "outcomes", "timeBack", "providerCost")
RESOLVED_SLOTS = {"accepted", "in_queue", "approved", "scheduled", "published", "rejected"}
LIMITATIONS = (
    "Delivery is not growth: verified publications and accepted work say what was done, not what it caused.",
    "Missing analytics never erase a verified delivery; unavailable figures stay unavailable, never zero.",
    "Assisted exports are counted apart from verified publications and are never added to them.",
    "Time Back classes (estimated, personalized, measured) are shown separately; they are not one measured figure.",
)


def zone(name):
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid_zone(name):
    try:
        ZoneInfo(name)
        return isinstance(name, str) and bool(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def workspace_zone(state, preference_zone=None, profile_zone=None):
    """(zone, source) per the module rule."""
    recipes = [r for r in ((state.get("coworker") or {}).get("weekly") or {}).get("recipes") or []
               if r.get("status") == "active" and valid_zone(r.get("timeZone"))]
    if recipes:
        return min(recipes, key=lambda r: (r.get("createdAt") or 0, r.get("id") or ""))["timeZone"], "recipe"
    if valid_zone(preference_zone):
        return preference_zone, "notification_preferences"
    if valid_zone(profile_zone):
        return profile_zone, "profile"
    return "UTC", "default_utc"


def _midnight(day, tz):
    return datetime.combine(day, dtime(0), tzinfo=tz).timestamp()


def period_bounds(day, frequency, zone_name):
    """The period containing local date `day`, as UTC epochs of local midnights (DST-safe)."""
    tz = zone(zone_name)
    if frequency == "weekly":
        first = day - timedelta(days=day.weekday())
        following = first + timedelta(days=7)
    elif frequency == "monthly":
        first = day.replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
    else:
        raise ValueError(frequency)
    return _midnight(first, tz), _midnight(following, tz)


def latest_completed(now, frequency, zone_name):
    tz = zone(zone_name)
    today = datetime.fromtimestamp(now, tz).date()
    start, _end = period_bounds(today, frequency, zone_name)
    previous = datetime.fromtimestamp(start - 1, tz).date()
    return period_bounds(previous, frequency, zone_name)


def period_for(start_date, frequency, zone_name):
    """The period starting on local date `start_date` (YYYY-MM-DD): a Monday for weekly, the 1st for monthly."""
    try:
        day = date.fromisoformat(str(start_date))
    except ValueError:
        return None
    if (frequency == "weekly" and day.weekday() != 0) or (frequency == "monthly" and day.day != 1):
        return None
    return period_bounds(day, frequency, zone_name)


def local_date(epoch, zone_name):
    return datetime.fromtimestamp(epoch, zone(zone_name)).date().isoformat()


def proof_id(workspace_id, frequency, start):
    """The Growth Loop proof id formula: for a UTC workspace it is the same id as the existing weekly/monthly recap."""
    return "gp_" + hashlib.sha256(f"{workspace_id}:{frequency}:{int(start)}".encode()).hexdigest()[:20]


def maturity(end, now):
    return {"mature": now >= end + MATURITY_SECONDS, "maturesAt": end + MATURITY_SECONDS, "windowSeconds": MATURITY_SECONDS}


def ids(values):
    """Sorted unique ids, bounded; (ids, truncated)."""
    unique = sorted({str(v) for v in values if v is not None})
    return unique[:EVIDENCE_LIMIT], len(unique) > EVIDENCE_LIMIT


def figure(value, *, definition, evidence=None, data_state="available", reason=None, **extra):
    out = {"value": value, "dataState": data_state, "definition": definition, "evidence": {}, "evidenceTruncated": False}
    for name, values in (evidence or {}).items():
        out["evidence"][name], truncated = ids(values)
        out["evidenceTruncated"] = out["evidenceTruncated"] or truncated
    if reason:
        out["reason"] = reason
    out.update(extra)
    return out


def unavailable(definition, reason):
    return figure(None, definition=definition, data_state="unavailable", reason=reason)


def _slot_instant(slot):
    try:
        return datetime.fromisoformat(slot["localTime"]).replace(tzinfo=zone(slot.get("timeZone"))).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def unresolved_slots(state, start, end):
    """Planned slots in the period that never reached a decision (accepted, in Queue or later, or skipped)."""
    weekly = (state.get("coworker") or {}).get("weekly") or {}
    definition = "Weekly-plan slots scheduled in this period that were neither accepted, handed to Queue nor skipped."
    if not weekly.get("recipes") and not weekly.get("weeks"):
        return unavailable(definition, "weekly_not_set_up")
    open_slots, by_reason, weeks = [], {}, set()
    for week in weekly.get("weeks") or []:
        for slot in week.get("slots") or []:
            at = _slot_instant(slot)
            if at is None or not start <= at < end or slot.get("status") in RESOLVED_SLOTS:
                continue
            open_slots.append(slot.get("id"))
            weeks.add(week.get("id"))
            by_reason[slot.get("status") or "unknown"] = by_reason.get(slot.get("status") or "unknown", 0) + 1
    return figure(len(open_slots), definition=definition, evidence={"slotIds": open_slots, "weekIds": weeks}, byReason=dict(sorted(by_reason.items())))


def jsonable(value, depth=0):
    """JSON-safe copy of another module's summary: numbers, strings, bools, None, lists and dicts only."""
    if depth > 6:
        return None
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(k)[:80]: jsonable(v, depth + 1) for k, v in list(value.items())[:60]}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, depth + 1) for v in list(value)[:200]]
    return None


def overall_state(figures, mature):
    if not mature or any(f.get("dataState") in ("unavailable", "partial") for f in figures.values()):
        return "partial"
    return "available"


def material(counts):
    """What a correction is about: each figure's value, data state and evidence ids, and the definition version.
    Not the as-of time, watermarks, maturity or wording."""
    return {"definitionVersion": counts["definitionVersion"],
            "figures": {name: {"value": f.get("value"), "dataState": f.get("dataState"), "evidence": f.get("evidence")} for name, f in sorted(counts["figures"].items())}}


def digest(counts):
    return hashlib.sha256(json.dumps(material(counts), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bounded(counts):
    """Keep a proof storable however busy the period: if the serialized counts exceed MAX_COUNTS_BYTES, every evidence
    list is cut to a short sample and flagged truncated (totals are unaffected). Deterministic, so the digest is too."""
    if len(json.dumps(counts, separators=(",", ":"))) <= MAX_COUNTS_BYTES:
        return counts
    for figure_value in counts["figures"].values():
        evidence = figure_value.get("evidence") or {}
        if any(len(ids_) > 10 for ids_ in evidence.values()):
            figure_value["evidence"] = {name: ids_[:10] for name, ids_ in evidence.items()}
            figure_value["evidenceTruncated"] = True
    return counts


def _compact(value):
    """A correction keeps small values as they were; a large one (a provenance summary, say) is recorded as changed."""
    return value if len(json.dumps(value, separators=(",", ":"), default=str)) <= CORRECTION_VALUE_BYTES else {"changed": True}


def corrections(previous, current, limit=20):
    """The material-correction note: per figure, what changed (value and/or data state), in a bounded list."""
    before, after = (previous or {}).get("figures") or {}, current.get("figures") or {}
    out = []
    for name in FIGURES:
        old, new = before.get(name) or {}, after.get(name) or {}
        changed_value = old.get("value") != new.get("value")
        changed_state = old.get("dataState") != new.get("dataState")
        changed_evidence = old.get("evidence") != new.get("evidence")
        if changed_value or changed_state or changed_evidence:
            entry = {"figure": name, "before": _compact(old.get("value")), "after": _compact(new.get("value"))}
            if changed_state:
                entry.update(dataStateBefore=old.get("dataState"), dataStateAfter=new.get("dataState"))
            if changed_evidence and not changed_value:
                entry["evidenceOnly"] = True
            out.append(entry)
    if (previous or {}).get("definitionVersion") != current.get("definitionVersion"):
        out.append({"figure": "definitionVersion", "before": (previous or {}).get("definitionVersion"), "after": current.get("definitionVersion")})
    return out[:limit]
