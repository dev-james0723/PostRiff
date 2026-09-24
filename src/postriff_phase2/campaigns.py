"""Persisted campaign plans and recurring draft preparation definitions.

These commands create drafts and plans only. They never create publication approvals.
"""
from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any

from postriff_alpha.domain import AlphaError, clean, uid
from .contracts import digest

DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _root(state: dict) -> dict:
    return state.setdefault("raffi", {}).setdefault("campaignPlanning", {"campaigns": [], "recurringTasks": [], "occurrences": []})


def _find(items: list[dict], item_id: str, label: str) -> dict:
    item = next((entry for entry in items if entry.get("id") == item_id), None)
    if item is None:
        raise AlphaError(f"{label} unavailable.", 404)
    return item


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AlphaError(f"Add a {name}.")
    return clean(value, limit)


def missing_facts(goal: str, facts: dict) -> list[str]:
    lower = goal.casefold()
    missing = []
    if any(word in lower for word in ("concert", "event", "festival", "recital", "音樂會", "演奏會", "活動", "音樂節")):
        if not facts.get("date"): missing.append("date")
        if not facts.get("venue"): missing.append("venue")
    return missing


def next_occurrence(schedule: dict, after: float) -> dict:
    zone_name = schedule.get("timeZone")
    try:
        zone = zoneinfo.ZoneInfo(zone_name)
    except (zoneinfo.ZoneInfoNotFoundError, TypeError):
        raise AlphaError("Choose a valid IANA time zone.")
    weekday = DAYS.get(str(schedule.get("weekday", "")).casefold())
    if weekday is None:
        raise AlphaError("Choose a weekday for recurring preparation.")
    try:
        hour, minute = map(int, str(schedule.get("localTime", "")).split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59): raise ValueError
    except (TypeError, ValueError):
        raise AlphaError("Choose a local time as HH:MM.")
    current = dt.datetime.fromtimestamp(after, dt.timezone.utc).astimezone(zone)
    days = (weekday - current.weekday()) % 7
    local = dt.datetime.combine(current.date() + dt.timedelta(days=days), dt.time(hour, minute), zone).replace(fold=0)
    if local <= current:
        local += dt.timedelta(days=7)
    # A nonexistent wall time does not round-trip. Advance to the next valid local minute.
    for _ in range(180):
        round_trip = local.astimezone(dt.timezone.utc).astimezone(zone)
        if (round_trip.hour, round_trip.minute, round_trip.date()) == (local.hour, local.minute, local.date()):
            break
        local += dt.timedelta(minutes=1)
    else:
        raise AlphaError("Could not resolve the next local occurrence.")
    utc = local.astimezone(dt.timezone.utc)
    return {"scheduledFor": utc.timestamp(), "local": local.isoformat(), "utc": utc.isoformat(), "offset": local.strftime("%z"), "fold": local.fold}


def apply_action(state: dict, action: str, payload: dict, actor: str, now: float) -> dict | None:
    if not action.startswith("raffi_campaign_") and not action.startswith("raffi_recurrence_"):
        return None
    root = _root(state)
    if action == "raffi_campaign_create":
        goal = _text(payload.get("goal"), "campaign goal", 1200)
        audience = _text(payload.get("audience"), "campaign audience", 800)
        facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
        missing = missing_facts(goal, facts)
        campaign = {
            "id": uid(), "version": 1, "goal": goal, "audience": audience, "facts": facts,
            "accountIds": list(dict.fromkeys(payload.get("accountIds") or []))[:20],
            "assetIds": list(dict.fromkeys(payload.get("assetIds") or []))[:50],
            "items": [], "status": "needs_input" if missing else "draft", "missingFacts": missing,
            "createdBy": actor, "createdAt": now, "updatedAt": now,
        }
        root["campaigns"].append(campaign)
        return {"campaignId": campaign["id"], "status": campaign["status"], "missingFacts": missing}
    if action == "raffi_campaign_update":
        campaign = _find(root["campaigns"], payload.get("campaignId"), "Campaign")
        if campaign.get("status") == "cancelled": raise AlphaError("This campaign is cancelled.", 409)
        for key, limit in (("goal", 1200), ("audience", 800)):
            if key in payload: campaign[key] = _text(payload[key], f"campaign {key}", limit)
        if "facts" in payload:
            if not isinstance(payload["facts"], dict): raise AlphaError("Campaign facts must be structured.")
            campaign["facts"] = payload["facts"]
        campaign["missingFacts"] = missing_facts(campaign["goal"], campaign["facts"])
        campaign["status"] = "needs_input" if campaign["missingFacts"] else "draft"
        campaign["version"] += 1
        campaign["updatedAt"], campaign["updatedBy"] = now, actor
        for task in root['recurringTasks']:
            if task['campaignId'] == campaign['id'] and task['status'] == 'active':
                task.update(status='paused', pauseReason='campaign_changed')
        for item in campaign.get("items", []):
            if item.get("status") not in ("published", "scheduled"):
                item["needsReview"] = True
        return {"campaignId": campaign["id"], "version": campaign["version"], "missingFacts": campaign["missingFacts"]}
    if action == "raffi_recurrence_preview":
        campaign = _find(root["campaigns"], payload.get("campaignId"), "Campaign")
        if campaign["missingFacts"]: raise AlphaError("Add the missing campaign facts before scheduling recurring preparation.", 409)
        schedule = payload.get("schedule")
        if not isinstance(schedule, dict): raise AlphaError("Add a recurring schedule.")
        preview = next_occurrence(schedule, now)
        if type(payload.get('draftsPerOccurrence', 1)) is not int or payload.get('draftsPerOccurrence', 1) != 1:
            raise AlphaError('Recurring preparation currently supports one draft per occurrence.')
        max_cost = payload.get('maxCostUsdMicro', 0)
        if type(max_cost) is not int or not 0 <= max_cost <= 10_000_000:
            raise AlphaError('Choose a per-occurrence cost limit between $0 and $10.')
        task = {
            "id": uid(), "campaignId": campaign["id"], "version": 1, "status": "draft", "schedule": schedule,
            "limits": {"draftsPerOccurrence": min(max(int(payload.get("draftsPerOccurrence", 1)), 1), 10)},
            "route": clean(payload.get("route", "local-cli"), 120), "contextSourceIds": list(dict.fromkeys(payload.get("sourceIds") or []))[:50],
            "nextOccurrence": preview, "createdBy": actor, "createdAt": now,
            "authorityVersion": 1, "campaignVersion": campaign['version'], "maxCostUsdMicro": max_cost,
            "destination": {"platform": "LinkedIn", "language": payload.get('language', 'en')},
        }
        task["definitionDigest"] = digest({key: task[key] for key in ("campaignId", "campaignVersion", "version", "schedule", "limits", "route", "contextSourceIds", "destination", "maxCostUsdMicro")})
        root["recurringTasks"].append(task)
        return {"taskId": task["id"], "preview": preview, "status": "draft"}
    task = _find(root["recurringTasks"], payload.get("taskId"), "Recurring task")
    if task['status'] == 'cancelled':
        raise AlphaError('This recurring task is cancelled. Create a new preview.', 409)
    if action == "raffi_recurrence_activate":
        if payload.get("confirmed") is not True: raise AlphaError("Confirm recurring draft preparation.")
        if task['status'] != 'draft': raise AlphaError('Only a draft task can be activated.', 409)
        campaign = _find(root['campaigns'], task['campaignId'], 'Campaign')
        if campaign['version'] != task.get('campaignVersion') or campaign.get('missingFacts'):
            raise AlphaError('Campaign facts changed. Create a new schedule preview.', 409)
        task["status"], task["activatedBy"], task["activatedAt"] = "active", actor, now
    elif action == "raffi_recurrence_pause":
        task["status"], task["pausedBy"], task["pausedAt"] = "paused", actor, now
    elif action == "raffi_recurrence_resume":
        if payload.get('confirmed') is not True: raise AlphaError('Confirm recurring draft preparation.')
        campaign = _find(root['campaigns'], task['campaignId'], 'Campaign')
        if campaign['version'] != task.get('campaignVersion'):
            raise AlphaError('Campaign facts changed. Create a new schedule preview.', 409)
        task["status"], task["nextOccurrence"] = "active", next_occurrence(task["schedule"], now)
        task['activatedBy'] = actor
        task["resumedBy"], task["resumedAt"] = actor, now
    elif action == "raffi_recurrence_cancel":
        if payload.get("confirmed") is not True: raise AlphaError("Confirm cancellation of future draft preparation.")
        task["status"], task["cancelledBy"], task["cancelledAt"] = "cancelled", actor, now
    else:
        raise AlphaError("Unsupported campaign action.")
    if task['status'] in ('paused', 'cancelled'):
        for occurrence in root['occurrences']:
            if occurrence['taskId'] == task['id'] and occurrence['state'] in ('pending', 'running'):
                occurrence.update(state='cancelled', reason='authority_revoked')
    return {"taskId": task["id"], "status": task["status"], "nextOccurrence": task.get("nextOccurrence")}


def claim_occurrence(state: dict, task_id: str, scheduled_for: float, now: float) -> dict:
    """Idempotently record one preparation occurrence; it carries no publish authority."""
    root = _root(state)
    task = _find(root["recurringTasks"], task_id, "Recurring task")
    if task.get("status") != "active": raise AlphaError("Recurring task is not active.", 409)
    key = digest({"workspace": state.get("workspace", {}).get("id"), "task": task_id, "taskVersion": task["version"], "scheduledFor": scheduled_for})
    existing = next((item for item in root["occurrences"] if item["idempotencyKey"] == key), None)
    if existing: return existing
    occurrence = {"id": uid(), "taskId": task_id, "taskVersion": task["version"], "scheduledFor": scheduled_for, "state": "pending", "createdAt": now, "idempotencyKey": key, "authority": "draft_preparation_only"}
    root["occurrences"].append(occurrence)
    task["lastOccurrence"] = occurrence["id"]
    task["nextOccurrence"] = next_occurrence(task["schedule"], scheduled_for + 1)
    return occurrence
