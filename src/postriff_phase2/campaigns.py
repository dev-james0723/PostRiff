"""Persisted campaign plans and recurring draft preparation definitions (Automations).

These commands create drafts and plans only. They never create publication approvals.

An automation is one campaign brief plus one recurring task. `raffi_recurrence_save` creates or edits
both in one command: any change to what would be drafted (brief, schedule, destinations, content
type, writer, reasoning, cost limit or sources) returns the task to `draft`, so the owner activates
the new definition before it runs. Renaming alone keeps the current status.
"""
from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from typing import Any

from postriff_alpha.domain import AlphaError, clean, uid
from . import content_types, locales
from .agent_runtime import PLATFORMS
from .contracts import digest

DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
REASONING = ("quick", "standard", "deep")
MAX_DESTINATIONS = 10
MAX_COST_USD_MICRO = 10_000_000
# The definition an activation authorizes. Legacy (authority 1) tasks keep their original digest.
LEGACY_DEFINITION = ("campaignId", "campaignVersion", "version", "schedule", "limits", "route", "contextSourceIds", "destination", "maxCostUsdMicro")
DEFINITION = ("campaignId", "campaignVersion", "version", "schedule", "limits", "route", "reasoning", "contextSourceIds", "destinations", "contentType", "maxCostUsdMicro")
LIBRARY_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,79}")


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


def _zone(schedule: dict) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(schedule.get("timeZone"))
    except (zoneinfo.ZoneInfoNotFoundError, TypeError, ValueError, OSError):
        raise AlphaError("Choose a valid IANA time zone.")


def weekdays_of(schedule: dict) -> list[int]:
    """Weekday indexes (Monday = 0) of a schedule: `weekdays` (a list) or the legacy single `weekday`."""
    raw = schedule.get("weekdays") if "weekdays" in schedule else [schedule.get("weekday")]
    if not isinstance(raw, list) or not raw or len(raw) > 7:
        raise AlphaError("Choose at least one weekday for recurring preparation.")
    days = []
    for value in raw:
        day = DAYS.get(value.casefold()) if isinstance(value, str) else None
        if day is None:
            raise AlphaError("Choose at least one weekday for recurring preparation.")
        if day not in days:
            days.append(day)
    return sorted(days)


def _local_time(schedule: dict) -> tuple[int, int]:
    try:
        hour, minute = map(int, str(schedule.get("localTime", "")).split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59): raise ValueError
    except (TypeError, ValueError):
        raise AlphaError("Choose a local time as HH:MM.")
    return hour, minute


def _next_local(current: dt.datetime, weekday: int, hour: int, minute: int, zone: zoneinfo.ZoneInfo) -> dt.datetime:
    days = (weekday - current.weekday()) % 7
    local = dt.datetime.combine(current.date() + dt.timedelta(days=days), dt.time(hour, minute), zone).replace(fold=0)
    if local <= current:
        local += dt.timedelta(days=7)
    # A nonexistent wall time does not round-trip. Advance to the next valid local minute.
    for _ in range(180):
        round_trip = local.astimezone(dt.timezone.utc).astimezone(zone)
        if (round_trip.hour, round_trip.minute, round_trip.date()) == (local.hour, local.minute, local.date()):
            return local
        local += dt.timedelta(minutes=1)
    raise AlphaError("Could not resolve the next local occurrence.")


def next_occurrence(schedule: dict, after: float) -> dict:
    """The first scheduled local time strictly after `after` (epoch), across every chosen weekday.
    A repeated wall time (autumn) uses its first, earlier-offset instance; a skipped one (spring)
    moves to the next valid local minute."""
    zone = _zone(schedule)
    weekdays = weekdays_of(schedule)
    hour, minute = _local_time(schedule)
    current = dt.datetime.fromtimestamp(after, dt.timezone.utc).astimezone(zone)
    local = min((_next_local(current, weekday, hour, minute, zone) for weekday in weekdays), key=lambda item: item.astimezone(dt.timezone.utc))
    utc = local.astimezone(dt.timezone.utc)
    return {"scheduledFor": utc.timestamp(), "local": local.isoformat(), "utc": utc.isoformat(), "offset": local.strftime("%z"), "fold": local.fold}


def upcoming(schedule: dict, after: float, count: int = 3) -> list[dict]:
    """The next `count` occurrences after `after`, for previews."""
    items, cursor = [], after
    for _ in range(max(0, min(count, 14))):
        item = next_occurrence(schedule, cursor)
        items.append(item)
        cursor = item["scheduledFor"] + 1
    return items


def normalize_schedule(schedule: Any) -> dict:
    if not isinstance(schedule, dict):
        raise AlphaError("Add a recurring schedule.")
    zone = _zone(schedule)
    days = weekdays_of(schedule)
    hour, minute = _local_time(schedule)
    return {"weekdays": [WEEKDAY_NAMES[day] for day in days], "localTime": f"{hour:02d}:{minute:02d}", "timeZone": zone.key}


def normalize_destinations(state: dict, value: Any) -> list[dict]:
    """1–10 (platform, language, account) destinations. An account must be one of this workspace's live
    connections on that platform; a platform-only destination drafts without an account, as on Home."""
    if not isinstance(value, list) or not value:
        raise AlphaError("Choose at least one account or channel for this automation.")
    if len(value) > MAX_DESTINATIONS:
        raise AlphaError(f"An automation prepares drafts for up to {MAX_DESTINATIONS} destinations.")
    channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict)}
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or item.get("platform") not in PLATFORMS:
            raise AlphaError("Choose channels Rafii can draft for.")
        tag = locales.canonical(item.get("language"))
        if tag is None:
            raise AlphaError("Choose a language for each destination.")
        channel_id = item.get("channelId") if isinstance(item.get("channelId"), str) and item.get("channelId") else None
        destination = {"platform": item["platform"], "language": tag}
        if channel_id is not None:
            channel = channels.get(channel_id)
            if channel is None or channel.get("revoked") or channel.get("platform") != item["platform"]:
                raise AlphaError("One selected account is no longer connected to this workspace. Choose your destinations again.", 409)
            destination["channelId"] = channel_id
        key = (destination["platform"], channel_id, tag)
        if key not in seen:
            seen.add(key)
            out.append(destination)
    return out


def connected_destinations(state: dict, destinations: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split destinations into those still drafted for and accounts disconnected since activation."""
    channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict)}
    kept, skipped = [], []
    for destination in destinations:
        channel = channels.get(destination.get("channelId")) if destination.get("channelId") else None
        if destination.get("channelId") and (channel is None or channel.get("revoked") or channel.get("platform") != destination["platform"]):
            skipped.append(destination)
        else:
            kept.append({key: destination[key] for key in ("platform", "language", "channelId") if key in destination})
    return kept, skipped


def normalize_content_type(state: dict, value: Any) -> dict | None:
    """None means no content type (general drafting); otherwise a type this workspace offers, at its current version."""
    if value is None or value == {}:
        return None
    if not isinstance(value, dict):
        raise AlphaError("Choose a content type available in this workspace.")
    type_id = value.get("contentTypeId")
    if type_id in (None, "unclassified"):
        return None
    if not isinstance(type_id, str):
        raise AlphaError("Choose a content type available in this workspace.")
    item = content_types.definition(state, type_id)
    format_id = value.get("formatId")
    if format_id is not None and format_id not in content_types.FORMAT_IDS:
        raise AlphaError("Choose a supported format.")
    return {"contentTypeId": item["id"], "contentTypeVersion": item["version"], "formatId": format_id}


def _content_display(value: Any) -> tuple[str | None, dict | None]:
    """Display-only label and Content Library ids (not part of the authorized definition)."""
    if not isinstance(value, dict):
        return None, None
    label = clean(value["label"], 160) if isinstance(value.get("label"), str) and value["label"].strip() else None
    library = value.get("library")
    if isinstance(library, dict) and all(isinstance(library.get(key), str) and LIBRARY_ID.fullmatch(library[key]) for key in ("editorialId", "nativeId")):
        return label, {"editorialId": library["editorialId"], "nativeId": library["nativeId"]}
    return label, None


def normalize_sources(state: dict, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AlphaError("Choose sources from this workspace.")
    available = {s.get("id") for s in state.get("sources", []) if s.get("active") and s.get("kind") != "voice_sample"}
    ids = list(dict.fromkeys(item for item in value if isinstance(item, str)))[:50]
    if any(item not in available for item in ids):
        raise AlphaError("One selected source is no longer available. Choose your sources again.", 409)
    return ids


def _facts(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AlphaError("Campaign facts must be structured.")
    facts = {}
    for key, item in list(value.items())[:12]:
        if isinstance(key, str) and key.strip() and isinstance(item, str) and item.strip():
            facts[clean(key, 40)] = clean(item, 400)
    return facts


def _required(value: Any, message: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AlphaError(message)
    return clean(value, limit)


def definition_digest(task: dict) -> str:
    keys = DEFINITION if task.get("authorityVersion") == 2 else LEGACY_DEFINITION
    return digest({key: task.get(key) for key in keys})


def _apply_brief(root: dict, campaign: dict, task: dict | None, goal: str, audience: str, facts: dict, account_ids: list[str], actor: str, now: float) -> bool:
    """Update a campaign's brief; a real change versions it, pauses the other active tasks that use it and
    marks its unpublished items for review (as `raffi_campaign_update` does). Returns whether it changed."""
    if (campaign.get("goal"), campaign.get("audience"), campaign.get("facts") or {}) == (goal, audience, facts):
        return False
    campaign.update(goal=goal, audience=audience, facts=facts, accountIds=account_ids)
    campaign["missingFacts"] = missing_facts(goal, facts)
    campaign["status"] = "needs_input" if campaign["missingFacts"] else "draft"
    campaign["version"] += 1
    campaign["updatedAt"], campaign["updatedBy"] = now, actor
    for other in root["recurringTasks"]:
        if other is not task and other["campaignId"] == campaign["id"] and other["status"] == "active":
            other.update(status="paused", pauseReason="campaign_changed")
    for item in campaign.get("items", []):
        if item.get("status") not in ("published", "scheduled"):
            item["needsReview"] = True
    return True


def _save_automation(state: dict, root: dict, payload: dict, actor: str, now: float) -> dict:
    name = _required(payload.get("name"), "Name this automation.", 120)
    goal = _required(payload.get("goal"), "Describe what the drafts should be about.", 1200)
    audience = _required(payload.get("audience"), "Describe who the drafts are for.", 800)
    facts = _facts(payload.get("facts"))
    schedule = normalize_schedule(payload.get("schedule"))
    destinations = normalize_destinations(state, payload.get("destinations"))
    content = normalize_content_type(state, payload.get("contentType"))
    content_label, library = _content_display(payload.get("contentType"))
    route = payload.get("route")
    if not isinstance(route, str) or not route.strip():
        raise AlphaError("Choose a writer for this automation.")
    route = clean(route, 120)
    if route == "local-cli":
        raise AlphaError("Choose a specific writer for this automation.")
    reasoning = payload.get("reasoning", "quick")
    if reasoning not in REASONING:
        raise AlphaError("Choose a reasoning level: quick, standard or deep.")
    max_cost = payload.get("maxCostUsdMicro", 0)
    if type(max_cost) is not int or not 0 <= max_cost <= MAX_COST_USD_MICRO:
        raise AlphaError("Choose a cost limit per run between $0 and $10.")
    sources = normalize_sources(state, payload.get("sourceIds"))
    label = clean(payload["destinationLabel"], 120) if isinstance(payload.get("destinationLabel"), str) and payload["destinationLabel"].strip() else None
    channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict)}
    # Display only, so a later account rename never changes the authorized definition.
    account_labels = {d["channelId"]: clean(channels[d["channelId"]].get("account") or "", 120) for d in destinations if d.get("channelId")}
    definition = {"schedule": schedule, "destinations": destinations, "contentType": content, "route": route, "reasoning": reasoning,
                  "maxCostUsdMicro": max_cost, "contextSourceIds": sources, "limits": {"draftsPerOccurrence": len(destinations)}}
    task_id = payload.get("taskId")
    account_ids = list(dict.fromkeys(d["channelId"] for d in destinations if d.get("channelId")))
    if task_id is None:
        if payload.get("campaignId") is not None:
            # Scheduling an existing brief (an older campaign, or one a suggestion pointed at) keeps its history.
            campaign = _find(root["campaigns"], payload["campaignId"], "Campaign")
            if campaign.get("status") == "cancelled":
                raise AlphaError("This campaign is cancelled.", 409)
            _apply_brief(root, campaign, None, goal, audience, facts, account_ids, actor, now)
        else:
            missing = missing_facts(goal, facts)
            campaign = {
                "id": uid(), "version": 1, "goal": goal, "audience": audience, "facts": facts, "kind": "automation",
                "accountIds": account_ids, "assetIds": [],
                "items": [], "status": "needs_input" if missing else "draft", "missingFacts": missing,
                "createdBy": actor, "createdAt": now, "updatedAt": now,
            }
            root["campaigns"].append(campaign)
        task = {"id": uid(), "campaignId": campaign["id"], "version": 1, "status": "draft", "createdBy": actor, "createdAt": now}
        root["recurringTasks"].append(task)
        changed = True
    else:
        task = _find(root["recurringTasks"], task_id, "Automation")
        if task["status"] == "cancelled":
            raise AlphaError("This automation was cancelled. Create a new one.", 409)
        campaign = _find(root["campaigns"], task["campaignId"], "Campaign")
        brief_changed = _apply_brief(root, campaign, task, goal, audience, facts, account_ids, actor, now)
        changed = brief_changed or task.get("authorityVersion") != 2 or any(task.get(key) != value for key, value in definition.items())
        if changed:
            task["version"] += 1
    task.update(name=name, destinationLabel=label, accountLabels=account_labels, contentLabel=content_label, contentLibrary=library, updatedAt=now, updatedBy=actor)
    if changed:
        task.pop("destination", None)
        for key in ("activatedBy", "activatedAt", "pauseReason"):
            task.pop(key, None)
        task.update(definition, status="draft", authorityVersion=2, campaignVersion=campaign["version"], nextOccurrence=next_occurrence(schedule, now))
        task["definitionDigest"] = definition_digest(task)
        # Nothing prepared under the previous definition may still run.
        for occurrence in root["occurrences"]:
            if occurrence["taskId"] == task["id"] and occurrence["state"] in ("pending", "running"):
                occurrence.update(state="cancelled", reason="definition_changed")
    return {"taskId": task["id"], "campaignId": campaign["id"], "status": task["status"], "missingFacts": campaign["missingFacts"],
            "nextOccurrence": task["nextOccurrence"], "upcoming": upcoming(task["schedule"], now, 3)}


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
        task["definitionDigest"] = definition_digest(task)
        root["recurringTasks"].append(task)
        return {"taskId": task["id"], "preview": preview, "status": "draft"}
    if action == "raffi_recurrence_save":
        return _save_automation(state, root, payload, actor, now)
    task = _find(root["recurringTasks"], payload.get("taskId"), "Recurring task")
    if task['status'] == 'cancelled':
        raise AlphaError('This recurring task is cancelled. Create a new preview.', 409)
    if action == "raffi_recurrence_activate":
        if payload.get("confirmed") is not True: raise AlphaError("Confirm recurring draft preparation.")
        if task['status'] != 'draft': raise AlphaError('Only a draft task can be activated.', 409)
        campaign = _find(root['campaigns'], task['campaignId'], 'Campaign')
        if campaign.get('missingFacts'):
            raise AlphaError(f"Add the missing campaign facts first: {', '.join(campaign['missingFacts'])}.", 409)
        if campaign['version'] != task.get('campaignVersion'):
            raise AlphaError('Campaign facts changed. Create a new schedule preview.', 409)
        if task.get('authorityVersion') == 2:
            # The accounts and content type must still exist when the owner authorizes the definition.
            normalize_destinations(state, task['destinations'])
            if task.get('contentType'):
                content_types.definition(state, task['contentType']['contentTypeId'], task['contentType']['contentTypeVersion'])
        task["status"], task["activatedBy"], task["activatedAt"] = "active", actor, now
        # A definition saved earlier must not run at a time that passed while it waited for activation.
        task["nextOccurrence"] = next_occurrence(task["schedule"], now)
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
