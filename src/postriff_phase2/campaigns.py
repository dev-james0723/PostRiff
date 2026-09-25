"""Persisted campaign plans and recurring draft preparation definitions (Automations).

These commands create drafts and plans, and record people's decisions about them. They never create a
publication approval themselves: an approved post is committed by the worker through the Phase 2 review and
approve chain (publisher.py), as the person who approved it or, for auto-publish, as the owner who granted it.

An automation is one campaign brief plus one recurring task. `raffi_recurrence_save` creates or edits
both in one command: any change to what would be drafted (brief, schedule, destinations, content
type, writer, reasoning, cost limit, sources, voice or workflow) returns the task to `draft`, so the owner
activates the new definition before it runs. Renaming alone keeps the current status.

A version 3 automation carries a `workflow` (workflow.py): separate generation, review and publication times, a
publish policy (auto, review or drafts), optional research, and per-platform notes. Its runs keep their items'
lifecycle (lifecycle.py) and history in the occurrence body; the projected occurrence state stays the generation state.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import statistics
import zoneinfo
from typing import Any

from postriff_alpha.domain import AlphaError, clean, uid
from . import content_types, lifecycle, locales, source_policy
from . import workflow as workflows
from .agent_runtime import PLATFORMS
from .contracts import digest

DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
REASONING = ("quick", "standard", "deep")
MAX_DESTINATIONS = 10
MAX_COST_USD_MICRO = 10_000_000
# The definition an activation authorizes. Legacy (authority 1) tasks keep their original digest.
LEGACY_DEFINITION = ("campaignId", "campaignVersion", "version", "schedule", "limits", "route", "contextSourceIds", "destination", "maxCostUsdMicro")
DEFINITION = ("campaignId", "campaignVersion", "version", "schedule", "limits", "route", "reasoning", "contextSourceIds", "destinations", "contentType", "maxCostUsdMicro", "include", "voiceMode")
# Version 3 adds the staged workflow (generation, review and publication times, publish policy, research).
DEFINITION_V3 = DEFINITION + ("workflow",)
MAX_PAUSE_SECONDS = 366 * 86400
MAX_SLOTS = 14
VOICE_MODES = ("neutral", "personalized")
# Event triggers run when something happens instead of at a time (Phase 3).
EVENT_KINDS = ("on_new_source", "on_strong_post")
SCHEDULE_KINDS = ("weekly", "monthly", "countdown", "once") + EVENT_KINDS
SOURCE_KINDS = ("idea", "text", "link", "document")
# Conversation metrics per provider (insights.INSIGHT_METRICS); LinkedIn reports none.
CONVERSATION_METRICS = {"threads": "replies", "instagram": "comments"}
MIN_COMPARABLE = 3
MAX_MONTH_DAYS = 4
MAX_COUNTDOWN_STEPS = 8
MAX_COUNTDOWN_DAYS = 90
# A campaign's items: what its automation runs produced, and drafts or posts a person linked to it (by id).
LINK_KEYS = {"draft": "variantId", "post": "jobId", "asset": "assetId"}
MAX_CAMPAIGN_ITEMS = 200
MAX_ITEM_LOG = 100
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


def slots_of(schedule: dict) -> list[tuple[int, int, int]]:
    """(weekday, hour, minute) for every weekly slot: `slots` when they give days their own times ("Monday at 9
    and Thursday at 5"), else each chosen weekday at the one local time."""
    raw = schedule.get("slots")
    if raw is None:
        hour, minute = _local_time(schedule)
        return [(day, hour, minute) for day in weekdays_of(schedule)]
    if not isinstance(raw, list) or not raw or len(raw) > MAX_SLOTS:
        raise AlphaError(f"Choose one to {MAX_SLOTS} weekly times.")
    out = []
    for slot in raw:
        day = DAYS.get(slot.get("weekday", "").casefold()) if isinstance(slot, dict) and isinstance(slot.get("weekday"), str) else None
        if day is None:
            raise AlphaError("Choose a weekday for each weekly time.")
        hour, minute = _local_time(slot)
        if (day, hour, minute) not in out:
            out.append((day, hour, minute))
    return sorted(out)


def once_of(schedule: dict) -> dt.datetime:
    """The local date and time of a one-time schedule (naive; the zone is applied by the caller)."""
    try:
        day = dt.date.fromisoformat(str(schedule.get("date", "")))
    except ValueError:
        raise AlphaError("Choose the date as YYYY-MM-DD.")
    hour, minute = _local_time(schedule)
    return dt.datetime(day.year, day.month, day.day, hour, minute)


def _valid_local(local: dt.datetime, zone: zoneinfo.ZoneInfo) -> dt.datetime:
    """A nonexistent wall time does not round-trip: advance to the next valid local minute."""
    for _ in range(180):
        round_trip = local.astimezone(dt.timezone.utc).astimezone(zone)
        if (round_trip.hour, round_trip.minute, round_trip.date()) == (local.hour, local.minute, local.date()):
            return local
        local += dt.timedelta(minutes=1)
    raise AlphaError("Could not resolve the next local occurrence.")


def _next_local(current: dt.datetime, weekday: int, hour: int, minute: int, zone: zoneinfo.ZoneInfo) -> dt.datetime:
    days = (weekday - current.weekday()) % 7
    local = dt.datetime.combine(current.date() + dt.timedelta(days=days), dt.time(hour, minute), zone).replace(fold=0)
    if local <= current:
        local += dt.timedelta(days=7)
    return _valid_local(local, zone)


def schedule_kind(schedule: dict) -> str:
    kind = schedule.get("kind", "weekly")
    if kind not in SCHEDULE_KINDS:
        raise AlphaError("Choose a weekly, monthly or countdown schedule, or a trigger.")
    return kind


def is_event(schedule: dict) -> bool:
    return schedule.get("kind") in EVENT_KINDS


def _per_day(schedule: dict, default: int) -> int:
    value = schedule.get("maxPerDay", default)
    if type(value) is not int or not 1 <= value <= 10:
        raise AlphaError("Choose between 1 and 10 runs a day.")
    return value


def month_days_of(schedule: dict) -> list:
    """Days of the month (1–31, or "last"), in calendar order. A day a month lacks runs on its last day."""
    raw = schedule.get("monthDays")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_MONTH_DAYS:
        raise AlphaError(f"Choose one to {MAX_MONTH_DAYS} days of the month.")
    days = []
    for value in raw:
        if value != "last" and (type(value) is not int or not 1 <= value <= 31):
            raise AlphaError("Choose days of the month between 1 and 31, or the last day.")
        if value not in days:
            days.append(value)
    return sorted(days, key=lambda day: 32 if day == "last" else day)


def countdown_of(schedule: dict) -> tuple[dt.date, list[int]]:
    """The event date and the days before it that get a run (descending, so runs come in date order)."""
    try:
        event = dt.date.fromisoformat(str(schedule.get("eventDate", "")))
    except ValueError:
        raise AlphaError("Choose the event date as YYYY-MM-DD.")
    raw = schedule.get("daysBefore")
    if (not isinstance(raw, list) or not raw or len(raw) > MAX_COUNTDOWN_STEPS
            or any(type(day) is not int or not 0 <= day <= MAX_COUNTDOWN_DAYS for day in raw)):
        raise AlphaError(f"Choose up to {MAX_COUNTDOWN_STEPS} countdown days, each 0 to {MAX_COUNTDOWN_DAYS} days before the event.")
    return event, sorted(set(raw), reverse=True)


def _next_monthly(current: dt.datetime, days: list, hour: int, minute: int, zone: zoneinfo.ZoneInfo) -> dt.datetime:
    year, month = current.year, current.month
    for _ in range(14):
        last = calendar.monthrange(year, month)[1]
        for day in sorted({last if value == "last" else min(value, last) for value in days}):
            local = dt.datetime.combine(dt.date(year, month, day), dt.time(hour, minute), zone).replace(fold=0)
            if local > current:
                return _valid_local(local, zone)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise AlphaError("Could not resolve the next local occurrence.")


def _next_countdown(current: dt.datetime, event: dt.date, days_before: list[int], hour: int, minute: int, zone: zoneinfo.ZoneInfo) -> dt.datetime | None:
    for days in days_before:
        local = dt.datetime.combine(event - dt.timedelta(days=days), dt.time(hour, minute), zone).replace(fold=0)
        if local > current:
            return _valid_local(local, zone)
    return None


def next_occurrence(schedule: dict, after: float) -> dict | None:
    """The first scheduled local time strictly after `after` (epoch). Weekly: across every chosen weekday.
    Monthly: across the chosen days (a day the month lacks runs on its last day). Countdown: the chosen
    days before the event date; None once every date has passed. A repeated wall time (autumn) uses its
    first, earlier-offset instance; a skipped one (spring) moves to the next valid local minute."""
    zone = _zone(schedule)
    kind = schedule_kind(schedule)
    if kind in EVENT_KINDS:
        return None  # triggered by events (`enqueue_events`), never by the clock
    if kind == "weekly":
        current = dt.datetime.fromtimestamp(after, dt.timezone.utc).astimezone(zone)
        local = min((_next_local(current, weekday, hour, minute, zone) for weekday, hour, minute in slots_of(schedule)), key=lambda item: item.astimezone(dt.timezone.utc))
    elif kind == "once":
        local = _valid_local(once_of(schedule).replace(tzinfo=zone, fold=0), zone)
        if local.astimezone(dt.timezone.utc).timestamp() <= after:
            return None
    elif kind == "monthly":
        days = month_days_of(schedule)
        hour, minute = _local_time(schedule)
        current = dt.datetime.fromtimestamp(after, dt.timezone.utc).astimezone(zone)
        local = _next_monthly(current, days, hour, minute, zone)
    else:
        event, days_before = countdown_of(schedule)
        hour, minute = _local_time(schedule)
        current = dt.datetime.fromtimestamp(after, dt.timezone.utc).astimezone(zone)
        local = _next_countdown(current, event, days_before, hour, minute, zone)
        if local is None:
            return None
    utc = local.astimezone(dt.timezone.utc)
    return {"scheduledFor": utc.timestamp(), "local": local.isoformat(), "utc": utc.isoformat(), "offset": local.strftime("%z"), "fold": local.fold}


def upcoming(schedule: dict, after: float, count: int = 3) -> list[dict]:
    """The next `count` occurrences after `after`, for previews."""
    items, cursor = [], after
    for _ in range(max(0, min(count, 14))):
        item = next_occurrence(schedule, cursor)
        if item is None:
            break
        items.append(item)
        cursor = item["scheduledFor"] + 1
    return items


def normalize_schedule(schedule: Any) -> dict:
    """Weekly schedules keep their original shape (no `kind`); monthly and countdown carry theirs."""
    if not isinstance(schedule, dict):
        raise AlphaError("Add a recurring schedule.")
    zone = _zone(schedule)
    kind = schedule_kind(schedule)
    if kind == "weekly":
        slots = slots_of(schedule)
        days = list(dict.fromkeys(day for day, _, _ in slots))
        hour, minute = slots[0][1], slots[0][2]
        out = {"weekdays": [WEEKDAY_NAMES[day] for day in days], "localTime": f"{hour:02d}:{minute:02d}", "timeZone": zone.key}
        if len({(h, m) for _, h, m in slots}) > 1 or len(slots) != len(days):
            # Days with their own times keep every slot; `weekdays`/`localTime` stay readable by older views.
            out["slots"] = [{"weekday": WEEKDAY_NAMES[day], "localTime": f"{h:02d}:{m:02d}"} for day, h, m in slots]
        return out
    if kind == "once":
        local = once_of(schedule)
        return {"kind": "once", "date": local.date().isoformat(), "localTime": f"{local.hour:02d}:{local.minute:02d}", "timeZone": zone.key}
    if kind == "monthly":
        days = month_days_of(schedule)
        hour, minute = _local_time(schedule)
        return {"kind": "monthly", "monthDays": days, "localTime": f"{hour:02d}:{minute:02d}", "timeZone": zone.key}
    if kind == "on_new_source":
        kinds = schedule.get("sourceKinds", list(SOURCE_KINDS))
        if not isinstance(kinds, list) or not kinds or any(item not in SOURCE_KINDS for item in kinds):
            raise AlphaError("Choose which kinds of new material start a run.")
        return {"kind": kind, "sourceKinds": [item for item in SOURCE_KINDS if item in kinds], "maxPerDay": _per_day(schedule, 3), "timeZone": zone.key}
    if kind == "on_strong_post":
        within = schedule.get("withinDays", 7)
        if type(within) is not int or not 1 <= within <= 30:
            raise AlphaError("Look back between 1 and 30 days for strong posts.")
        return {"kind": kind, "maxPerDay": _per_day(schedule, 1), "withinDays": within, "timeZone": zone.key}
    event, days_before = countdown_of(schedule)
    hour, minute = _local_time(schedule)
    return {"kind": "countdown", "eventDate": event.isoformat(), "daysBefore": days_before, "localTime": f"{hour:02d}:{minute:02d}", "timeZone": zone.key}


def normalize_include(value: Any) -> dict | None:
    """Extra context each run reads: `recentPostsDays` adds this workspace's own published posts from that
    many days; `evergreen.minAgeDays` adds one older published post to refresh (never the same one twice)."""
    if value is None or value == {}:
        return None
    if not isinstance(value, dict) or not value or set(value) - {"recentPostsDays", "evergreen"}:
        raise AlphaError("Choose what each run should include.")
    out = {}
    if "recentPostsDays" in value:
        days = value["recentPostsDays"]
        if type(days) is not int or not 7 <= days <= 92:
            raise AlphaError("Include published posts from the last 7 to 92 days.")
        out["recentPostsDays"] = days
    if "evergreen" in value:
        evergreen = value["evergreen"]
        age = evergreen.get("minAgeDays") if isinstance(evergreen, dict) and set(evergreen) <= {"minAgeDays"} else None
        if type(age) is not int or not 14 <= age <= 365:
            raise AlphaError("Reshare posts that are between 14 and 365 days old.")
        out["evergreen"] = {"minAgeDays": age}
    return out


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


def recent_posts(state: dict, until: float, days: int, limit: int = 10) -> list[dict]:
    """This workspace's own posts verified as published in the `days` before `until`, newest first (text trimmed).
    Only what the workspace already published: no drafts, sources or other workspaces."""
    since = until - days * 86400
    items = []
    for job in (state.get("phase2") or {}).get("jobs", []):
        at = (job.get("verification") or {}).get("at")
        if job.get("state") != "verified" or not isinstance(at, (int, float)) or not since <= at <= until:
            continue
        manifest = job.get("manifest") or {}
        text = str((manifest.get("payload") or {}).get("text") or "").strip()
        if text:
            items.append({"platform": manifest.get("platform"), "publishedAt": dt.datetime.fromtimestamp(at, dt.timezone.utc).date().isoformat(), "text": text[:600], "_at": at})
    items.sort(key=lambda item: item["_at"], reverse=True)
    return [{key: item[key] for key in ("platform", "publishedAt", "text")} for item in items[:limit]]


def countdown_context(schedule: dict, scheduled_for: float) -> dict | None:
    """For a countdown run: the event date and the whole days left, counted in the schedule's own time zone."""
    if schedule.get("kind") != "countdown":
        return None
    day = dt.datetime.fromtimestamp(scheduled_for, dt.timezone.utc).astimezone(_zone(schedule)).date()
    return {"eventDate": schedule["eventDate"], "daysToGo": (dt.date.fromisoformat(schedule["eventDate"]) - day).days}


def definition_digest(task: dict) -> str:
    version = task.get("authorityVersion")
    keys = DEFINITION_V3 if version == 3 else DEFINITION if version == 2 else LEGACY_DEFINITION
    return digest({key: task.get(key) for key in keys})


def is_staged(task: dict) -> bool:
    """A version 3 automation with a workflow: staged generation, review and publication."""
    return task.get("authorityVersion") == 3 and isinstance(task.get("workflow"), dict)


def first_run(task: dict, now: float) -> dict | None:
    """The next generation instant of a task (its workflow's, for a staged one)."""
    if is_staged(task):
        return workflows.next_run(task, now)
    return next_occurrence(task["schedule"], now)


def next_publish(task: dict, occurrence: dict | None) -> str | None:
    """Local ISO time the next run publishes (display only)."""
    if not occurrence or not is_staged(task) or not occurrence.get("anchorAt"):
        return None
    return workflows.stage_times(task["workflow"], task["schedule"], occurrence["anchorAt"], claimed_at=occurrence["scheduledFor"])["local"]["publish"]


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
    task_id = payload.get("taskId")
    existing = _find(root["recurringTasks"], task_id, "Automation") if task_id is not None else None
    # A save that does not mention the workflow keeps the one the automation has (the builder never drops it).
    raw_workflow = payload["workflow"] if "workflow" in payload else (existing or {}).get("workflow")
    staged_destinations = [d.get("platform") for d in payload.get("destinations") or [] if isinstance(d, dict)]
    workflow = workflows.normalize_workflow(raw_workflow, schedule, staged_destinations) if raw_workflow is not None else None
    if schedule.get("kind") == "once" and workflow is None:
        raise AlphaError("A one-time automation needs its publishing plan.")
    probe = {"schedule": schedule, "workflow": workflow, "authorityVersion": 3 if workflow else 2,
             "lastAnchorAt": (existing or {}).get("lastAnchorAt") if existing and existing.get("schedule") == schedule else None}
    upcoming_run = first_run(probe, now)
    if schedule.get("kind") == "once":
        # A one-time post is valid while its time is ahead, even when its run already started (then no new run).
        if next_occurrence(schedule, now) is None:
            raise AlphaError("That time has already passed. Choose a later time.", 409)
    elif upcoming_run is None and not is_event(schedule):
        raise AlphaError("Every countdown date has passed. Choose a later event date.", 409)
    if is_event(schedule) and isinstance(payload.get("include"), dict) and "evergreen" in payload["include"]:
        raise AlphaError("Resharing an older post needs a weekly, monthly or countdown schedule.")
    if schedule.get("kind") == "countdown" and not facts.get("date"):
        # The countdown's event date is the brief's date fact unless the person wrote one.
        facts["date"] = schedule["eventDate"]
    include = normalize_include(payload.get("include"))
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
    # Personalized drafts use the workspace's selected writing samples allowed for this writer at run time.
    voice_mode = payload.get("voiceMode", "neutral")
    if voice_mode not in VOICE_MODES:
        raise AlphaError("Choose neutral or personalized writing.")
    label = clean(payload["destinationLabel"], 120) if isinstance(payload.get("destinationLabel"), str) and payload["destinationLabel"].strip() else None
    channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict)}
    # Display only, so a later account rename never changes the authorized definition.
    account_labels = {d["channelId"]: clean(channels[d["channelId"]].get("account") or "", 120) for d in destinations if d.get("channelId")}
    definition = {"schedule": schedule, "destinations": destinations, "contentType": content, "route": route, "reasoning": reasoning,
                  "maxCostUsdMicro": max_cost, "contextSourceIds": sources, "limits": {"draftsPerOccurrence": len(destinations)}, "include": include,
                  "voiceMode": voice_mode}
    version = 3 if workflow is not None else 2
    if workflow is not None:
        definition["workflow"] = workflow
    intent_text = clean(payload["intent"], 600) if isinstance(payload.get("intent"), str) and payload["intent"].strip() else (existing or {}).get("intent")
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
        task = existing
        if task["status"] == "cancelled":
            raise AlphaError("This automation was cancelled. Create a new one.", 409)
        campaign = _find(root["campaigns"], task["campaignId"], "Campaign")
        brief_changed = _apply_brief(root, campaign, task, goal, audience, facts, account_ids, actor, now)
        changed = brief_changed or task.get("authorityVersion") != version or any(task.get(key) != value for key, value in definition.items()) or (version == 2 and "workflow" in task)
        if changed:
            task["version"] += 1
    task.update(name=name, destinationLabel=label, accountLabels=account_labels, contentLabel=content_label, contentLibrary=library, updatedAt=now, updatedBy=actor)
    if intent_text:
        task["intent"] = intent_text
    if changed:
        task.pop("destination", None)
        for key in ("activatedBy", "activatedAt", "pauseReason", "watchFrom", "pendingEvents", "publishAuthority", "pausedUntil"):
            task.pop(key, None)
        if version == 2:
            task.pop("workflow", None)
        task.update(definition, status="draft", authorityVersion=version, campaignVersion=campaign["version"], nextOccurrence=upcoming_run)
        task["definitionDigest"] = definition_digest(task)
        task["nextPublish"] = next_publish(task, upcoming_run)
        # Nothing prepared under the previous definition may still run; drafted runs follow the new plan.
        for occurrence in root["occurrences"]:
            if occurrence["taskId"] == task["id"] and occurrence["state"] in ("pending", "running"):
                occurrence.update(state="cancelled", reason="definition_changed")
                if occurrence.get("lifecycle"):
                    occurrence["lifecycle"] = "skipped"
                    _history(occurrence, now, "cancelled", "The automation changed before this run finished, so it stopped.", actor)
        retime_open_runs(state, task, now, actor)
    return {"taskId": task["id"], "campaignId": campaign["id"], "status": task["status"], "missingFacts": campaign["missingFacts"],
            "nextOccurrence": task["nextOccurrence"], "upcoming": upcoming(task["schedule"], now, 3)}


def _history(occurrence: dict, at: float, event: str, detail: str, actor: str = "raffi") -> None:
    """Append one line to a run's execution history (bounded; the newest lines are kept)."""
    items = occurrence.setdefault("history", [])
    items.append({"at": at, "event": event, "detail": clean(detail, 400) if detail else "", "actor": actor})
    del items[:-60]


def item_of(occurrence: dict, key: Any) -> dict:
    item = next((entry for entry in occurrence.get("items") or [] if entry.get("key") == key), None)
    if item is None:
        raise AlphaError("That post is not part of this run.", 404)
    return item


def open_items(occurrence: dict) -> list[dict]:
    """Items that have not reached a final state."""
    return [item for item in occurrence.get("items") or [] if item.get("state") not in lifecycle.ITEM_TERMINAL]


def _cancel_job(state: dict, job_id: str | None, now: float, message: str) -> bool:
    """Cancel a job that has not been handed to the platform yet (as p2_cancel does); never recalls a post."""
    job = next((j for j in (state.get("phase2") or {}).get("jobs", []) if j.get("id") == job_id), None) if job_id else None
    if job is None or job.get("state") not in ("approved", "scheduled", "held"):
        return False
    job["cancelRequested"] = True
    job["state"] = "canceled"
    job.setdefault("events", []).append({"at": now, "state": "canceled", "message": message, "execution": (job.get("manifest") or {}).get("execution", "synthetic")})
    return True


def stop_open_items(state: dict, task: dict, now: float, reason: str, actor: str, *, publish_before: float | None = None) -> int:
    """Stop this automation's unpublished posts: waiting drafts are skipped and posts not yet handed to the platform
    are cancelled. A post already being published is left alone (a cancel cannot recall it). With `publish_before`,
    only posts due before then (a pause window) are stopped."""
    stopped = 0
    for occurrence in _root(state)["occurrences"]:
        if occurrence["taskId"] != task["id"]:
            continue
        for item in open_items(occurrence):
            if item.get("state") == "publishing":
                continue
            if publish_before is not None and (item.get("publishAt") is None or item["publishAt"] >= publish_before):
                continue
            if item.get("jobId") and not _cancel_job(state, item["jobId"], now, reason):
                continue
            lifecycle.move(item, "skipped", reason=reason, at=now)
            stopped += 1
        if stopped:
            _history(occurrence, now, "stopped", reason, actor)
    return stopped


def retime_open_runs(state: dict, task: dict, now: float, actor: str) -> None:
    """After an edit, drafted runs that have not published follow the new plan instead of running twice: their
    publish time is recomputed (a moved anchor re-anchors them), destinations that were removed are skipped, and the
    automation never claims an anchor one of these runs already covers. Posts already handed to the platform keep
    their time; a policy change applies from the next run (drafts already waiting for review still need approval)."""
    if not is_staged(task):
        return
    workflow, schedule = task["workflow"], task["schedule"]
    wanted = {(d["platform"], d.get("channelId") or "", d["language"]) for d in task["destinations"]}
    for occurrence in _root(state)["occurrences"]:
        if occurrence["taskId"] != task["id"] or occurrence.get("lifecycle") != "drafted" or not open_items(occurrence):
            continue
        anchor = occurrence.get("anchorAt")
        if schedule.get("kind") == "once":
            found = next_occurrence(schedule, 0)
            anchor = found["scheduledFor"] if found else anchor
        elif occurrence.get("schedule") != schedule:
            # The run's post moves to the new schedule's next time, never into the past.
            found = next_occurrence(schedule, max(now, float(occurrence.get("generatedAt") or occurrence["scheduledFor"])) - 1)
            anchor = found["scheduledFor"] if found else anchor
        times = workflows.stage_times(workflow, schedule, anchor, claimed_at=occurrence["scheduledFor"])
        occurrence.update(anchorAt=anchor, schedule=schedule, stages={key: times[key] for key in ("generateAt", "reviewAt", "publishAt", "local")})
        task["lastAnchorAt"] = max(float(task.get("lastAnchorAt") or 0), anchor)
        for item in open_items(occurrence):
            if (item["platform"], item.get("channelId") or "", item["language"]) not in wanted:
                if item.get("state") != "publishing" and (not item.get("jobId") or _cancel_job(state, item["jobId"], now, "Removed from the automation")):
                    lifecycle.move(item, "skipped", reason=f"{item['platform']} was removed from this automation.", at=now)
                continue
            if item.get("jobId") or item.get("publishAt") is None:
                continue  # already queued at its approved time, or a draft only (never turned into a publication)
            item["publishAt"] = times["publishAt"] if workflow.get("policy") != "drafts" else None
            if item["publishAt"] is None and item.get("state") == "approved":
                # Switching to drafts only: an approval to publish no longer applies.
                item["decision"], item["approvedVia"] = None, None
                lifecycle.move(item, "ready_for_review", reason="This automation now prepares drafts only.", at=now)
        _history(occurrence, now, "retimed", f"Updated to the new plan: publish {times['local']['publish'] or 'not scheduled'}.", actor)
    task["nextOccurrence"] = first_run(task, now)
    task["nextPublish"] = next_publish(task, task["nextOccurrence"])


def _decide(state: dict, root: dict, payload: dict, actor: str, now: float) -> dict:
    """A person's decision on one drafted post: approve this exact draft, ask for changes, or reject it. Approval
    records exactly what was reviewed (revision, text digest, excluded unknowns, acknowledged warnings, source use);
    the worker publishes it at its time through the review and approve chain, as this person."""
    if payload.get("confirmed") is not True:
        raise AlphaError("Confirm your decision on this post.")
    decision = payload.get("decision")
    if decision not in ("approve", "reject", "revise"):
        raise AlphaError("Choose approve, request changes, or reject.")
    occurrence = _find(root["occurrences"], payload.get("occurrenceId"), "Run")
    task = _find(root["recurringTasks"], occurrence["taskId"], "Automation")
    item = item_of(occurrence, payload.get("itemKey"))
    allowed = ("ready_for_review", "needs_revision", "platform_disconnected") if decision == "approve" else ("ready_for_review", "needs_revision", "approved", "platform_disconnected")
    if item.get("state") not in allowed or item.get("jobId"):
        raise AlphaError(f"This post is {lifecycle.LABELS.get(item.get('state'), item.get('state'))} and can't take that decision now.", 409, code="lifecycle_transition")
    note = clean(payload["note"], 400) if isinstance(payload.get("note"), str) and payload["note"].strip() else ""
    if decision == "approve":
        if item.get("publishAt") is not None and now >= item["publishAt"]:
            raise AlphaError("The publish time for this post has passed, so it can no longer be approved. Its draft is kept.", 409, code="approval_expired")
        variant = next((v for v in state.get("variants", []) if v.get("id") == item.get("variantId")), None)
        if variant is None:
            raise AlphaError("This draft is no longer available.", 404)
        if payload.get("variantRevision") != variant.get("revision"):
            raise AlphaError("This draft changed. Read the current version before approving it.", 409)
        if variant.get("rejected") or variant.get("blockedByRetraction") or variant.get("policyBlocked"):
            raise AlphaError("This draft can't be published as it is. Draft it again or edit it first.", 409)
        if payload.get("excludedUnknowns") != variant.get("unknowns", []):
            raise AlphaError("Review every unknown and confirm unsupported details are left out of this draft.", 409)
        if sorted(payload.get("acknowledgedWarnings") or []) != sorted(variant.get("warnings") or []):
            raise AlphaError("Acknowledge every warning shown for this draft.", 409)
        given = {entry.get("sourceId"): entry.get("factsDigest") for entry in payload.get("sourceUse") or [] if isinstance(entry, dict)}
        uses = []
        for source_id in variant.get("sourceIds", []):
            source = next((x for x in state.get("sources", []) if x.get("id") == source_id), None)
            if source is None or not source.get("active"):
                continue
            if source.get("sourcePolicy") == "rewrite_approval" and not source_policy.use_approved(source):
                current = source_policy.facts_digest(source)
                if given.get(source_id) != current:
                    raise AlphaError(f"Confirm public use of “{clean(source.get('title') or 'a source', 80)}” before approving.", 409)
                uses.append({"sourceId": source_id, "factsDigest": current})
        item["decision"] = {"decision": "approve", "by": actor, "at": now, "note": note, "variantRevision": variant["revision"], "textDigest": digest(variant.get("text", "")),
                            "excludedUnknowns": list(variant.get("unknowns", [])), "acknowledgedWarnings": list(variant.get("warnings") or []), "sourceUse": uses}
        item["approvedVia"] = "human"
        lifecycle.move(item if item["state"] != "needs_revision" else lifecycle.move(item, "ready_for_review", at=now), "approved", at=now)
        _history(occurrence, now, "approved", f"{item['platform']} post approved; it publishes at its scheduled time." if item.get("publishAt") else f"{item['platform']} draft approved.", actor)
    elif decision == "revise":
        if not note:
            raise AlphaError("Say what should change.")
        if item["state"] in ("approved", "platform_disconnected"):
            item["decision"] = None
            lifecycle.move(item, "ready_for_review", at=now)
        lifecycle.move(item, "needs_revision", reason=note, at=now)
        item["revisionFrom"] = item.get("variantRevision")
        _history(occurrence, now, "changes_requested", f"{item['platform']}: {note}", actor)
    else:
        if item["state"] in ("approved", "platform_disconnected"):
            lifecycle.move(item, "ready_for_review", at=now)
        lifecycle.move(item, "rejected", reason=note or "Rejected", at=now)
        item["decision"] = {"decision": "reject", "by": actor, "at": now, "note": note}
        _history(occurrence, now, "rejected", f"{item['platform']} post rejected; it will not be published.", actor)
    return {"occurrenceId": occurrence["id"], "itemKey": item["key"], "state": item["state"], "taskId": task["id"]}


def _link_targets(state: dict, payload: dict, known_only: bool = True) -> list[tuple[str, str]]:
    """The drafts (`draftIds`), posts (`jobIds`) and images (`assetIds`) a link names. Linking checks each against
    this workspace (a deleted image is refused); unlinking also accepts an id the campaign still holds after it is gone."""
    variants = {v.get("id") for v in state.get("variants", []) if isinstance(v, dict)}
    jobs = {j.get("id") for j in (state.get("phase2") or {}).get("jobs", []) if isinstance(j, dict)}
    assets = {a.get("id") for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and not a.get("deleted")}
    targets = []
    for kind, key, known in (("draft", "draftIds", variants), ("post", "jobIds", jobs), ("asset", "assetIds", assets)):
        ids = payload.get(key) if payload.get(key) is not None else []
        if not isinstance(ids, list) or len(ids) > 20 or not all(isinstance(item, str) and item for item in ids):
            raise AlphaError("Choose up to 20 drafts, posts or images.")
        for target in dict.fromkeys(ids):
            if known_only and target not in known:
                raise AlphaError(f"That {kind} is not in this workspace.", 404)
            targets.append((kind, target))
    if not targets:
        raise AlphaError("Choose a draft, a post or an image.")
    return targets


def linked_campaigns(state: dict, kind: str, target: str) -> list[dict]:
    """The campaigns a draft or post was linked to, with who linked it and when."""
    key = LINK_KEYS[kind]
    return [{"campaign": campaign, "item": item} for campaign in _root(state)["campaigns"] if campaign.get("status") != "cancelled"
            for item in campaign.get("items") or [] if item.get("kind") == kind and item.get(key) == target]


def _log_items(campaign: dict, op: str, kind: str, target: str, actor: str, now: float) -> None:
    log = campaign.setdefault("itemLog", [])
    log.append({"op": op, "kind": kind, "id": target, "by": actor, "at": now})
    del log[:-MAX_ITEM_LOG]


def apply_action(state: dict, action: str, payload: dict, actor: str, now: float) -> dict | None:
    if not action.startswith("raffi_campaign_") and not action.startswith("raffi_recurrence_") and action != "raffi_run_decide":
        return None
    root = _root(state)
    if action == "raffi_run_decide":
        return _decide(state, root, payload, actor, now)
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
    if action == "raffi_campaign_link":
        # Organisation only: the campaign lists the draft or post. Nothing is drafted, scheduled or published, and
        # the brief itself (its version, goal, audience) is unchanged, so no automation is paused for it.
        campaign = _find(root["campaigns"], payload.get("campaignId"), "Campaign")
        if campaign.get("status") == "cancelled":
            raise AlphaError("This campaign is cancelled.", 409)
        added, already = [], 0
        for kind, target in _link_targets(state, payload):
            key = LINK_KEYS[kind]
            if any(item.get("kind") == kind and item.get(key) == target for item in campaign["items"]):
                already += 1
                continue
            if len(campaign["items"]) >= MAX_CAMPAIGN_ITEMS:
                raise AlphaError("This campaign already holds as many items as it can.", 409)
            item = {"id": uid(), "kind": kind, key: target, "addedBy": actor, "addedAt": now}
            campaign["items"].append(item)
            _log_items(campaign, "link", kind, target, actor, now)
            added.append(item["id"])
        return {"campaignId": campaign["id"], "added": added, "alreadyLinked": already}
    if action == "raffi_campaign_unlink":
        campaign = _find(root["campaigns"], payload.get("campaignId"), "Campaign")
        removed = 0
        for kind, target in _link_targets(state, payload, known_only=False):
            key = LINK_KEYS[kind]
            keep = [item for item in campaign["items"] if not (item.get("kind") == kind and item.get(key) == target)]
            if len(keep) != len(campaign["items"]):
                removed += len(campaign["items"]) - len(keep)
                campaign["items"] = keep
                _log_items(campaign, "unlink", kind, target, actor, now)
        return {"campaignId": campaign["id"], "removed": removed}
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
            "destination": _recurring_destination(state, payload),
        }
        task["definitionDigest"] = definition_digest(task)
        root["recurringTasks"].append(task)
        return {"taskId": task["id"], "preview": preview, "status": "draft"}
    if action == "raffi_recurrence_save":
        return _save_automation(state, root, payload, actor, now)
    if action == "raffi_recurrence_seen":
        # Marks prepared drafts as looked at for the whole workspace (clears "drafts ready"); changes no draft.
        task = _find(root["recurringTasks"], payload.get("taskId"), "Automation")
        wanted = payload.get("occurrenceIds")
        if wanted is not None and (not isinstance(wanted, list) or not all(isinstance(item, str) for item in wanted)):
            raise AlphaError("Choose runs of this automation.")
        marked = 0
        for occurrence in root["occurrences"]:
            if occurrence["taskId"] == task["id"] and occurrence["state"] == "completed" and not occurrence.get("seenAt") and (wanted is None or occurrence["id"] in wanted):
                occurrence.update(seenAt=now, seenBy=actor)
                marked += 1
        return {"taskId": task["id"], "marked": marked}
    if action == "raffi_recurrence_watch":
        # A person's own opt-in to an email when this automation's drafts are ready. Outside the definition.
        task = _find(root["recurringTasks"], payload.get("taskId"), "Automation")
        if type(payload.get("email")) is not bool:
            raise AlphaError("Choose whether to email you when drafts are ready.")
        watchers = [item for item in task.get("emailWatchers", []) if item != actor]
        task["emailWatchers"] = (watchers + [actor]) if payload["email"] else watchers
        return {"taskId": task["id"], "email": payload["email"]}
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
        if task.get('authorityVersion') in (2, 3):
            # The accounts and content type must still exist when the owner authorizes the definition.
            normalize_destinations(state, task['destinations'])
            if task.get('contentType'):
                content_types.definition(state, task['contentType']['contentTypeId'], task['contentType']['contentTypeVersion'])
        if is_staged(task):
            policy = task["workflow"].get("policy")
            if policy is None:
                raise AlphaError("Choose whether posts publish automatically, wait for your approval, or stay as drafts.", 409, code="publish_policy_required")
            grant = payload.get("publishAuthority") if isinstance(payload.get("publishAuthority"), dict) else {}
            if policy == "auto":
                # Standing authority to publish without a per-post review: granted by an owner, for this exact definition.
                if grant.get("confirmed") is not True:
                    raise AlphaError("Confirm that Rafii may publish these posts without asking you each time.", 409, code="publish_authority_required")
                task["publishAuthority"] = {"grantedBy": actor, "grantedAt": now, "definitionDigest": task["definitionDigest"], "sourceUse": grant.get("sourceUse") is True}
            else:
                task.pop("publishAuthority", None)
        # A definition saved earlier must not run at a time that passed while it waited for activation.
        upcoming_run = first_run(task, now)
        if task["schedule"].get("kind") == "once":
            if next_occurrence(task["schedule"], now) is None:
                raise AlphaError("That time has already passed. Edit the time to use it again.", 409)
        elif upcoming_run is None and not is_event(task["schedule"]):
            raise AlphaError("Every countdown date has passed. Edit the event date to use it again.", 409)
        task["status"], task["activatedBy"], task["activatedAt"] = "active", actor, now
        task["nextOccurrence"] = upcoming_run
        task["nextPublish"] = next_publish(task, upcoming_run)
        task.pop("pausedUntil", None)
        if is_event(task["schedule"]):
            # Only what happens from now on starts a run; nothing from before is replayed.
            task["watchFrom"], task["pendingEvents"] = now, []
    elif action == "raffi_recurrence_pause":
        until = payload.get("until")
        if until is not None:
            if type(until) not in (int, float) or not now < until <= now + MAX_PAUSE_SECONDS:
                raise AlphaError("Choose when the pause ends, within a year.")
            task["pausedUntil"] = float(until)
        else:
            task.pop("pausedUntil", None)
        task["status"], task["pausedBy"], task["pausedAt"] = "paused", actor, now
        # Nothing this automation prepared publishes while it is paused.
        stop_open_items(state, task, now, "The automation was paused before this post's time.", actor, publish_before=task.get("pausedUntil", float("inf")))
    elif action == "raffi_recurrence_resume":
        if payload.get('confirmed') is not True: raise AlphaError('Confirm recurring draft preparation.')
        campaign = _find(root['campaigns'], task['campaignId'], 'Campaign')
        if campaign['version'] != task.get('campaignVersion'):
            raise AlphaError('Campaign facts changed. Create a new schedule preview.', 409)
        if is_staged(task) and task["workflow"].get("policy") == "auto" and (task.get("publishAuthority") or {}).get("definitionDigest") != task["definitionDigest"]:
            raise AlphaError("Turn this automation on again to confirm automatic publishing.", 409, code="publish_authority_required")
        upcoming_run = first_run(task, now)
        if task["schedule"].get("kind") == "once":
            if next_occurrence(task["schedule"], now) is None:
                raise AlphaError("That time has already passed. Edit the time to use it again.", 409)
        elif upcoming_run is None and not is_event(task["schedule"]):
            raise AlphaError("Every countdown date has passed. Edit the event date to use it again.", 409)
        task["status"], task["nextOccurrence"] = "active", upcoming_run
        task["nextPublish"] = next_publish(task, upcoming_run)
        task.pop("pausedUntil", None)
        if is_event(task["schedule"]):
            task["watchFrom"], task["pendingEvents"] = now, []
        task['activatedBy'] = actor
        task["resumedBy"], task["resumedAt"] = actor, now
    elif action == "raffi_recurrence_cancel":
        if payload.get("confirmed") is not True: raise AlphaError("Confirm cancellation of future draft preparation.")
        task["status"], task["cancelledBy"], task["cancelledAt"] = "cancelled", actor, now
        if payload.get("delete") is True:
            # Deleting hides the automation; its run history stays for the audit trail.
            task["deletedAt"], task["deletedBy"] = now, actor
        stop_open_items(state, task, now, "The automation was deleted." if payload.get("delete") is True else "The automation was cancelled.", actor)
    else:
        raise AlphaError("Unsupported campaign action.")
    if task['status'] in ('paused', 'cancelled'):
        task.pop('pendingEvents', None)
        if is_event(task['schedule']):
            task['nextOccurrence'] = None
        for occurrence in root['occurrences']:
            if occurrence['taskId'] == task['id'] and occurrence['state'] in ('pending', 'running'):
                occurrence.update(state='cancelled', reason='authority_revoked')
                if occurrence.get('lifecycle'):
                    occurrence['lifecycle'] = 'skipped'
                    _history(occurrence, now, 'stopped', 'The automation was paused or cancelled before this run finished.', actor)
    return {"taskId": task["id"], "status": task["status"], "nextOccurrence": task.get("nextOccurrence"), "pausedUntil": task.get("pausedUntil")}


def _recurring_destination(state: dict, payload: dict) -> dict:
    """The one confirmed destination of a recurring task: a platform, or one connected account, and a language."""
    raw = payload.get("destination")
    if raw is None:
        return {"platform": "LinkedIn", "language": payload.get("language", "en")}  # the earlier fixed default
    from .agent_runtime import PLATFORMS
    from . import locales
    if not isinstance(raw, dict) or raw.get("platform") not in PLATFORMS:
        raise AlphaError("Choose a platform recurring drafts can be written for.", 400)
    language = locales.canonical(raw.get("language"))
    if not language:
        raise AlphaError("Choose the language recurring drafts are written in.", 400)
    destination = {"platform": raw["platform"], "language": language}
    channel_id = raw.get("channelId")
    if channel_id is not None:
        channels = (state.get("phase2") or {}).get("channels") or []
        account = next((c for c in channels if isinstance(c, dict) and c.get("id") == channel_id), None)
        if not account or account.get("platform") != raw["platform"] or account.get("revoked"):
            raise AlphaError("Choose a connected account on that platform.", 409)
        destination["channelId"] = channel_id
    return destination


def claim_occurrence(state: dict, task_id: str, scheduled_for: float, now: float) -> dict:
    """Idempotently record one preparation occurrence; it carries no publish authority. An event trigger's
    occurrence carries its event and is keyed by the event, so the same idea or post never runs twice."""
    root = _root(state)
    task = _find(root["recurringTasks"], task_id, "Recurring task")
    if task.get("status") != "active": raise AlphaError("Recurring task is not active.", 409)
    event = None
    if is_event(task["schedule"]):
        pending = task.get("pendingEvents") or []
        event = next((item for item in pending if item["at"] == scheduled_for), pending[0] if pending else None)
        if event is None:
            raise AlphaError("Nothing is waiting for this automation.", 409)
        scheduled_for = event["at"]
        key = digest({"workspace": state.get("workspace", {}).get("id"), "task": task_id, "taskVersion": task["version"], "event": event["id"]})
    else:
        key = digest({"workspace": state.get("workspace", {}).get("id"), "task": task_id, "taskVersion": task["version"], "scheduledFor": scheduled_for})
    existing = next((item for item in root["occurrences"] if item["idempotencyKey"] == key), None)
    if existing: return existing
    occurrence = {"id": uid(), "taskId": task_id, "taskVersion": task["version"], "scheduledFor": scheduled_for, "state": "pending", "createdAt": now, "idempotencyKey": key, "authority": "draft_preparation_only"}
    if event is not None:
        occurrence["event"] = {k: v for k, v in event.items() if k != "at"}
    if is_staged(task):
        # A staged run: its own anchor and stage instants, frozen now so later edits re-time it explicitly.
        anchor = (task.get("nextOccurrence") or {}).get("anchorAt") or scheduled_for
        workflow = task["workflow"]
        times = workflows.stage_times(workflow, task["schedule"], anchor, claimed_at=scheduled_for)
        occurrence.update(anchorAt=anchor, schedule=task["schedule"], policy=workflow.get("policy"), authority=f"workflow_{workflow.get('policy')}",
                          stages={key: times[key] for key in ("generateAt", "reviewAt", "publishAt", "local")}, lifecycle="planned",
                          research=None, skills=[], items=[], history=[], notices={})
        _history(occurrence, now, "triggered", f"Scheduled run for {times['local']['publish'] or times['local']['generate']}.")
        task["lastAnchorAt"] = max(float(task.get("lastAnchorAt") or 0), anchor)
    root["occurrences"].append(occurrence)
    task["lastOccurrence"] = occurrence["id"]
    if event is not None:
        task["pendingEvents"] = [item for item in task.get("pendingEvents") or [] if item is not event]
        task["nextOccurrence"] = _due(task["pendingEvents"][0]["at"], task["schedule"]) if task["pendingEvents"] else None
    elif is_staged(task):
        task["nextOccurrence"] = workflows.next_run(task, max(now, scheduled_for))
        task["nextPublish"] = next_publish(task, task["nextOccurrence"])
    else:
        task["nextOccurrence"] = next_occurrence(task["schedule"], scheduled_for + 1)
    return occurrence


def refresh_next(task: dict, now: float) -> None:
    """Point the task at its next due time: the next waiting event for a trigger, else the schedule."""
    if is_event(task["schedule"]):
        pending = task.get("pendingEvents") or []
        task["nextOccurrence"] = _due(pending[0]["at"], task["schedule"]) if pending else None
    else:
        task["nextOccurrence"] = first_run(task, now)
        task["nextPublish"] = next_publish(task, task["nextOccurrence"])


def _due(at: float, schedule: dict) -> dict:
    local = dt.datetime.fromtimestamp(at, dt.timezone.utc).astimezone(_zone(schedule))
    utc = local.astimezone(dt.timezone.utc)
    return {"scheduledFor": at, "local": local.isoformat(), "utc": utc.isoformat(), "offset": local.strftime("%z"), "fold": local.fold}


def _epoch(value: Any) -> float:
    """Source rows store ISO-8601 strings (domain) or epoch floats (hosted)."""
    if type(value) in (int, float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)).timestamp()
    return 0.0


def new_source_events(state: dict, task: dict) -> list[dict]:
    """Ideas, notes, links and documents added (and still usable) since the automation started watching."""
    watch = float(task.get("watchFrom") or 0)
    kinds = set(task["schedule"].get("sourceKinds") or SOURCE_KINDS)
    events = []
    for source in state.get("sources", []):
        # Pages an automation's own research stored are its inputs, not new material to react to.
        if (source.get("origin") or {}).get("kind") in ("web_research", "automation_research"):
            continue
        if source.get("active") and source.get("kind") in kinds and _epoch(source.get("createdAt")) >= watch:
            events.append({"id": f"source:{source['id']}", "kind": "new_source", "sourceId": source["id"], "title": clean(source.get("title") or "Untitled", 200)})
    return events


def _conversation(post: dict) -> tuple[str | None, float | None]:
    metric = CONVERSATION_METRICS.get(post.get("provider"))
    value = ((post.get("metrics") or {}).get(metric) or {}).get("value") if metric else None
    return metric, (float(value) if isinstance(value, (int, float)) else None)


def strong_post_events(state: dict, task: dict, posts: list[dict], now: float) -> list[dict]:
    """Recently published posts that started more conversation (replies or comments) than comparable posts.

    Follows the analytics rules (insights.py): posts are compared only within one cohort (same provider,
    language, content type and metric definition), only when at least three posts in it are measured, and
    a post qualifies when it is in the cohort's top quarter with a clear margin over the median (at least
    1.5 times it and at least two more), so the best of a few ordinary posts is not called strong.
    An observation, not a cause.
    """
    within = task["schedule"].get("withinDays", 7) * 86400
    jobs = {job.get("providerReference"): job for job in (state.get("phase2") or {}).get("jobs", []) if job.get("providerReference")}
    cohorts: dict = {}
    for post in posts:
        metric, value = _conversation(post)
        if value is not None:
            cohorts.setdefault(tuple(sorted((post.get("cohort") or {}).items())), []).append((post, metric, value))
    events = []
    for members in cohorts.values():
        if len(members) < MIN_COMPARABLE:
            continue
        values = sorted(value for _, _, value in members)
        typical = statistics.median(values)
        top_quarter = statistics.quantiles(values, n=4, method="inclusive")[2]
        for post, metric, value in members:
            job = jobs.get(post.get("providerPostId"))
            at = ((job or {}).get("verification") or {}).get("at")
            if not job or job.get("state") != "verified" or not isinstance(at, (int, float)) or at < now - within:
                continue
            if value >= top_quarter and value >= 1.5 * typical and value - typical >= 2:
                manifest = job.get("manifest") or {}
                events.append({"id": f"post:{job['id']}", "kind": "strong_post", "jobId": job["id"], "platform": manifest.get("platform"),
                               "publishedAt": dt.datetime.fromtimestamp(at, dt.timezone.utc).date().isoformat(),
                               "text": str((manifest.get("payload") or {}).get("text") or "")[:600],
                               "metric": metric, "value": value, "typical": typical, "sampleSize": len(members)})
    return events


def enqueue_events(state: dict, task: dict, events: list[dict], now: float) -> bool:
    """Queue newly detected events: each at most once, and at most `maxPerDay` runs in any 24 hours. An event
    over the limit is skipped (counted), never saved for later, so a busy day cannot become a backlog."""
    if task.get("status") != "active" or not events:
        return False
    seen = list(task.get("seenEventIds") or [])
    known = set(seen) | {item["id"] for item in task.get("pendingEvents") or []}
    fresh = [event for event in events if event["id"] not in known]
    if not fresh:
        return False
    recent = sum(1 for item in _root(state)["occurrences"] if item["taskId"] == task["id"] and item.get("event") and item.get("createdAt", 0) > now - 86400)
    budget = task["schedule"].get("maxPerDay", 1) - recent - len(task.get("pendingEvents") or [])
    pending = task.setdefault("pendingEvents", [])
    for event in fresh:
        seen.append(event["id"])
        if budget <= 0:
            task["skippedEvents"] = task.get("skippedEvents", 0) + 1
            continue
        pending.append({**event, "at": now + len(pending) * 0.001})
        budget -= 1
    task["seenEventIds"] = seen[-500:]
    if pending:
        task["nextOccurrence"] = _due(pending[0]["at"], task["schedule"])
    return True


def evergreen_post(state: dict, task: dict, now: float, posts: list[dict] | None = None) -> dict | None:
    """One older published post to refresh: at least `minAgeDays` old, never one this automation used
    before; the one that started the most conversation first (when measured), then the oldest."""
    config = (task.get("include") or {}).get("evergreen")
    if not config:
        return None
    used = set(task.get("evergreenUsed") or [])
    measured = {post.get("providerPostId"): _conversation(post)[1] or 0 for post in posts or []}
    best = None
    for job in (state.get("phase2") or {}).get("jobs", []):
        at = (job.get("verification") or {}).get("at")
        text = str(((job.get("manifest") or {}).get("payload") or {}).get("text") or "").strip()
        if job.get("state") != "verified" or not isinstance(at, (int, float)) or at > now - config["minAgeDays"] * 86400 or not text or job["id"] in used:
            continue
        rank = (measured.get(job.get("providerReference"), 0), -at)
        if best is None or rank > best[0]:
            best = (rank, job, at, text)
    if best is None:
        return None
    _, job, at, text = best
    return {"jobId": job["id"], "platform": (job.get("manifest") or {}).get("platform"), "publishedAt": dt.datetime.fromtimestamp(at, dt.timezone.utc).date().isoformat(), "text": text[:600]}
