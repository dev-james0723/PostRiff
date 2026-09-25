"""Weekly Social Operator: state, planning and the week state machine (adaptive coworker spec §12; lock W1).

Pure functions over the workspace document (`state.coworker.weekly`); the service layer (`coworker/service.py`)
runs them inside `repository.command` and drives the writing pipeline between them.

A recipe says what a normal week looks like. A week moves
    planned → researching → generating → quality_check → ready_for_review → approved → scheduled
and can stop in a blocked state (needs_input, needs_source, needs_asset, channel_unavailable, approval_expired) with
a precise reason. Rafii never schedules or publishes: "approved" and "scheduled" are read back from the existing
Queue (reviews and jobs on the week's drafts), so they are true only when the application says so.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError

WEEK_STATES = ("planned", "researching", "generating", "quality_check", "ready_for_review", "approved", "scheduled")
BLOCKED_STATES = ("needs_input", "needs_source", "needs_asset", "channel_unavailable", "approval_expired")
SLOT_STATES = ("planned", "needs_source", "needs_input", "needs_asset", "channel_unavailable", "drafted", "needs_revision", "ready", "accepted",
               "in_queue", "approved", "scheduled", "published", "failed", "rejected", "approval_expired")
MAX_RECIPES = 5
MAX_SLOTS = 28
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_HOURS = {"LinkedIn": 9, "X": 12, "Threads": 12, "Instagram": 18, "Facebook": 13, "TikTok": 19, "YouTube": 17, "Pinterest": 20, "Bluesky": 12}
PERSONAL_TYPES = ("personal_reflection", "behind_the_scenes", "music_performance_teaching")
_ID = re.compile(r"^[a-z0-9_-]{4,64}$")


def root(state):
    coworker = state.setdefault("coworker", {})
    weekly = coworker.setdefault("weekly", {})
    weekly.setdefault("recipes", [])
    weekly.setdefault("weeks", [])
    weekly.setdefault("revision", 0)
    return weekly


def view(state):
    return ((state.get("coworker") or {}).get("weekly") or {"recipes": [], "weeks": [], "revision": 0})


def _clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def validate_recipe(payload, state, zone_default="UTC"):
    """A recipe from the person's form. Everything is bounded; an unknown channel or campaign is refused."""
    channels = {c.get("id"): c for c in ((state.get("phase2") or {}).get("channels") or [])}
    name = _clean(payload.get("name"), 80) or "My week"
    goals = [_clean(g, 160) for g in (payload.get("goals") or []) if _clean(g, 160)][:5]
    if not goals:
        raise AlphaError("Give the week at least one goal.", 400)
    destinations = []
    for item in (payload.get("destinations") or [])[:8]:
        channel = channels.get(item.get("channelId"))
        if channel is None or channel.get("revoked"):
            raise AlphaError("Choose connected accounts from this workspace.", 400)
        per_week = item.get("postsPerWeek", 3)
        if not isinstance(per_week, int) or isinstance(per_week, bool) or not 0 <= per_week <= 7:
            raise AlphaError("Posts per week are 0–7 per account.", 400)
        destinations.append({"channelId": channel["id"], "platform": channel.get("platform"), "account": channel.get("account"),
                             "language": _clean(item.get("language") or channel.get("language") or "en", 20), "postsPerWeek": per_week})
    if not destinations or sum(d["postsPerWeek"] for d in destinations) == 0:
        raise AlphaError("Choose at least one account and how often to post.", 400)
    if sum(d["postsPerWeek"] for d in destinations) > MAX_SLOTS:
        raise AlphaError(f"A week plans at most {MAX_SLOTS} posts.", 400)
    mix = {}
    for key, weight in (payload.get("contentMix") or {}).items():
        if isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight > 0:
            mix[_clean(key, 60)] = float(weight)
    zone = payload.get("timeZone") or zone_default
    try:
        ZoneInfo(zone)
    except Exception as error:  # noqa: BLE001
        raise AlphaError("Unknown time zone.", 400) from error
    day = payload.get("planningDay", 4)
    hour = payload.get("planningHour", 9)
    if not isinstance(day, int) or not 0 <= day <= 6 or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise AlphaError("Planning day is 0 (Monday)–6 and hour 0–23.", 400)
    campaigns = {c.get("id") for c in (((state.get("raffi") or {}).get("campaignPlanning") or {}).get("campaigns") or [])}
    campaign_ids = [c for c in (payload.get("campaignIds") or [])[:5] if c in campaigns]
    sources = {s.get("id") for s in state.get("sources") or [] if s.get("active")}
    source_ids = [s for s in (payload.get("sourceIds") or [])[:20] if s in sources]
    budget = payload.get("maxCostUsdMicroPerWeek", 2_000_000)
    if not isinstance(budget, int) or isinstance(budget, bool) or not 0 <= budget <= 50_000_000:
        raise AlphaError("The weekly cost limit is 0–50 USD.", 400)
    return {"name": name, "goals": goals, "destinations": destinations, "contentMix": mix or {"tutorial_how_to": 1.0, "deep_point_of_view": 1.0, "building_in_public": 1.0},
            "campaignIds": campaign_ids, "sourceIds": source_ids, "planningDay": day, "planningHour": hour, "timeZone": zone,
            "voiceMode": "personalized" if payload.get("voiceMode") == "personalized" else "neutral", "reviewPolicy": "review",
            "expectImages": bool(payload.get("expectImages")), "useResearch": bool(payload.get("useResearch")),
            "maxCostUsdMicroPerWeek": budget, "model": _clean(payload.get("model"), 80) or None}


def save_recipe(state, payload, actor, now, recipe_id=None):
    weekly = root(state)
    values = validate_recipe(payload, state)
    if recipe_id:
        recipe = next((r for r in weekly["recipes"] if r["id"] == recipe_id), None)
        if recipe is None:
            raise AlphaError("Recipe unavailable.", 404)
        recipe.update(values)
        recipe["version"] += 1
        recipe["updatedAt"] = now
    else:
        if len([r for r in weekly["recipes"] if r.get("status") != "deleted"]) >= MAX_RECIPES:
            raise AlphaError(f"A workspace has at most {MAX_RECIPES} weekly recipes.", 409)
        recipe = {"id": "wr_" + uuid.uuid4().hex[:12], **values, "status": "active", "version": 1, "createdBy": actor, "createdAt": now, "updatedAt": now}
        weekly["recipes"].append(recipe)
    weekly["revision"] += 1
    return recipe


def set_recipe_status(state, recipe_id, status, now):
    if status not in ("active", "paused", "deleted"):
        raise AlphaError("Choose active, paused or deleted.", 400)
    weekly = root(state)
    recipe = next((r for r in weekly["recipes"] if r["id"] == recipe_id), None)
    if recipe is None:
        raise AlphaError("Recipe unavailable.", 404)
    recipe["status"], recipe["updatedAt"] = status, now
    weekly["revision"] += 1
    return recipe


def week_start(now, zone, ahead=True):
    """The Monday that starts the week to plan: next week when `ahead`."""
    local = datetime.fromtimestamp(now, ZoneInfo(zone)).date()
    monday = local - timedelta(days=local.weekday())
    return monday + timedelta(days=7) if ahead else monday


def iso_week(monday):
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def due(recipe, now):
    """True when the recipe's planning moment for next week has passed (planning day/hour in its time zone)."""
    zone = ZoneInfo(recipe["timeZone"])
    local = datetime.fromtimestamp(now, zone)
    monday = local.date() - timedelta(days=local.weekday())
    planning = datetime.combine(monday + timedelta(days=recipe["planningDay"]), datetime.min.time()).replace(hour=recipe["planningHour"], tzinfo=zone)
    return recipe.get("status") == "active" and local >= planning


def _stable(seed, n):
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % max(1, n)


def _channel_ready(state, channel_id, now):
    channel = next((c for c in ((state.get("phase2") or {}).get("channels") or []) if c.get("id") == channel_id), None)
    if channel is None or channel.get("revoked"):
        return False, "The account is disconnected."
    if channel.get("connectionState") in ("token_expired", "reauthorization_required", "scope_missing"):
        return False, "The account needs to be reconnected."
    expires = channel.get("expiresAt")
    if isinstance(expires, (int, float)) and 0 < expires < now:
        return False, "The account's access has expired; reconnect it."
    return True, ""


def plan_week(state, recipe, now, monday=None):
    """A deterministic week plan: slots spread over the week in the recipe's zone, the content mix balanced across the
    week, sources assigned in turn. Slots that need something the workspace doesn't have are blocked with a reason."""
    monday = monday or week_start(now, recipe["timeZone"])
    mix = sorted(recipe["contentMix"].items(), key=lambda kv: (-kv[1], kv[0]))
    total_weight = sum(w for _, w in mix) or 1.0
    sources = [s for s in state.get("sources") or [] if s.get("active") and s.get("kind") != "voice_sample" and any(f.get("approved") for f in s.get("facts") or [])]
    preferred = [s for s in sources if s.get("id") in recipe.get("sourceIds", [])] or sources
    slots, index = [], 0
    for destination in recipe["destinations"]:
        count = destination["postsPerWeek"]
        days = [round(i * 7 / count) % 7 for i in range(count)] if count else []
        ready, reason = _channel_ready(state, destination["channelId"], now)
        for n, day in enumerate(days):
            # Weighted round-robin over the content mix, offset per platform so the week does not repeat itself.
            cursor = (index + _stable(destination["platform"], len(mix))) % max(1, len(mix))
            quota = [(key, weight / total_weight) for key, weight in mix]
            content_type = quota[cursor % len(quota)][0] if quota else "deep_point_of_view"
            source = preferred[(index) % len(preferred)] if preferred else None
            when = datetime.combine(monday + timedelta(days=day), datetime.min.time()).replace(hour=DEFAULT_HOURS.get(destination["platform"], 10), tzinfo=ZoneInfo(recipe["timeZone"]))
            goal = recipe["goals"][index % len(recipe["goals"])]
            slot = {"id": "sl_" + hashlib.sha256(f"{recipe['id']}:{monday}:{destination['channelId']}:{n}".encode()).hexdigest()[:12],
                    "day": (monday + timedelta(days=day)).isoformat(), "localTime": when.strftime("%Y-%m-%dT%H:%M"), "timeZone": recipe["timeZone"],
                    "platform": destination["platform"], "language": destination["language"], "channelId": destination["channelId"], "account": destination.get("account"),
                    "contentType": content_type, "goal": goal, "angle": f"{goal} — {content_type.replace('_', ' ')}", "sourceIds": [source["id"]] if source else [],
                    "status": "planned", "reason": None, "question": None, "variantId": None, "runId": None, "quality": None, "creative": None}
            if not ready:
                slot["status"], slot["reason"] = "channel_unavailable", reason
            elif content_type in PERSONAL_TYPES:
                slot["status"] = "needs_input"
                slot["question"] = f"What happened this week that you'd like to share on {destination['platform']}? One or two sentences is enough."
            elif not source:
                slot["status"], slot["reason"] = "needs_source", "No approved source is available for this post. Add one or approve a research lead."
            slots.append(slot)
            index += 1
    week = {"id": "wk_" + hashlib.sha256(f"{recipe['id']}:{monday}".encode()).hexdigest()[:12], "recipeId": recipe["id"], "recipeVersion": recipe["version"],
            "weekOf": monday.isoformat(), "isoWeek": iso_week(monday), "state": "planned", "blockedReason": None, "slots": slots,
            "createdAt": now, "updatedAt": now, "readyAt": None, "history": [{"at": now, "state": "planned", "note": f"{len(slots)} posts planned"}],
            "conversationId": None, "costBudgetUsdMicro": recipe["maxCostUsdMicroPerWeek"]}
    return week


def transition(week, target, now, note=""):
    allowed = {"planned": ("researching", "generating") + BLOCKED_STATES, "researching": ("generating",) + BLOCKED_STATES,
               "generating": ("quality_check",) + BLOCKED_STATES, "quality_check": ("ready_for_review",) + BLOCKED_STATES,
               "ready_for_review": ("approved", "approval_expired", "generating", "quality_check"), "approved": ("scheduled", "approval_expired"),
               "scheduled": (), **{b: ("planned", "generating", "quality_check", "ready_for_review") for b in BLOCKED_STATES}}
    if target == week["state"]:
        return week
    if target not in allowed.get(week["state"], ()):
        raise AlphaError(f"A week cannot move from {week['state']} to {target}.", 409)
    week["state"], week["updatedAt"] = target, now
    week["history"] = (week.get("history") or [])[-30:] + [{"at": now, "state": target, "note": note[:200]}]
    return week


def summarize(week):
    counts = {}
    for slot in week["slots"]:
        counts[slot["status"]] = counts.get(slot["status"], 0) + 1
    return counts


def settle(week, now):
    """After generation and quality: ready_for_review when every slot is ready or explicitly blocked with a reason;
    if nothing at all is reviewable, the week takes its dominant blocked state."""
    reviewable = [s for s in week["slots"] if s["status"] in ("ready", "needs_revision")]
    open_work = [s for s in week["slots"] if s["status"] in ("planned", "drafted")]
    if open_work:
        return week
    if reviewable:
        if week["state"] != "ready_for_review":
            if week["state"] in ("generating",) + BLOCKED_STATES:
                transition(week, "quality_check", now, "quality checked")
            transition(week, "ready_for_review", now, f"{len(reviewable)} posts ready for review")
            week["readyAt"] = now
            week["blockedReason"] = None
        return week
    blocked = [s["status"] for s in week["slots"] if s["status"] in BLOCKED_STATES]
    if blocked:
        dominant = max(set(blocked), key=blocked.count)
        reason = next((s.get("reason") or s.get("question") for s in week["slots"] if s["status"] == dominant), dominant)
        if week["state"] != dominant:
            if week["state"] in ("ready_for_review", "approved", "scheduled"):
                return week
            transition(week, dominant, now, reason or dominant)
        week["blockedReason"] = reason
    return week


def sync_from_queue(state, week, now):
    """Read the Queue back: a slot is in_queue when its draft has a review, approved when that review was approved,
    scheduled when a job is approved/scheduled or in flight, published only when a job is `verified`, failed when a
    job failed, approval_expired when its review went stale. The week follows its slots."""
    phase2 = state.get("phase2") or {}
    reviews = phase2.get("reviews") or []
    jobs = phase2.get("jobs") or []
    changed = False
    for slot in week["slots"]:
        variant = slot.get("variantId")
        if not variant or slot["status"] in ("rejected",):
            continue
        slot_jobs = [j for j in jobs if (j.get("manifest") or {}).get("variantId") == variant]
        slot_reviews = [r for r in reviews if (r.get("manifest") or {}).get("variantId") == variant]
        status = slot["status"]
        if any(j.get("state") == "verified" for j in slot_jobs):
            status = "published"
        elif any(j.get("state") in ("approved", "scheduled", "claimed", "processing", "submitting", "provider_accepted", "published", "uncertain") for j in slot_jobs):
            status = "scheduled"
        elif any(j.get("state") in ("failed", "held") for j in slot_jobs):
            status = "failed"
        elif any(r.get("status") == "approved" for r in slot_reviews):
            status = "approved"
        elif any(r.get("status") == "needs_review" for r in slot_reviews):
            status = "in_queue"
        elif slot_reviews and all(r.get("status") == "stale" for r in slot_reviews) and status in ("in_queue", "accepted"):
            status = "approval_expired"
        if status != slot["status"]:
            slot["status"], changed = status, True
    expired = [s for s in week["slots"] if s["status"] == "approval_expired"]
    if week["state"] == "approval_expired" and not expired:
        transition(week, "ready_for_review", now, "the expired approval was renewed or the post was skipped")
        week["blockedReason"] = None
        changed = True
    if expired and week["state"] in ("ready_for_review", "approved"):
        # Checked first: one expired approval means a post will not go out, whatever the others did.
        transition(week, "approval_expired", now, "an approval expired before its publish time")
        week["blockedReason"] = "An approval expired before its publish time. Review a new time in Queue."
        return True
    active = [s for s in week["slots"] if s["status"] not in ("rejected",) + BLOCKED_STATES]
    if active and week["state"] in ("ready_for_review", "approved"):
        if all(s["status"] in ("scheduled", "published", "failed") for s in active) and any(s["status"] in ("scheduled", "published") for s in active):
            if week["state"] == "ready_for_review":
                transition(week, "approved", now, "every accepted post was approved in Queue")
            transition(week, "scheduled", now, "every approved post has a publishing job")
            changed = True
        elif week["state"] == "ready_for_review" and all(s["status"] in ("approved", "scheduled", "published") for s in active):
            transition(week, "approved", now, "every accepted post was approved in Queue")
            changed = True
    return changed


def slot_brief(recipe, slot, state):
    """The material the writer receives for one slot: data, never instructions."""
    source_titles = [s.get("title") for s in state.get("sources") or [] if s.get("id") in slot["sourceIds"]]
    return json.dumps({"weekOf": slot["day"], "goal": slot["goal"], "contentType": slot["contentType"], "platform": slot["platform"], "language": slot["language"],
                       "angle": slot["angle"], "answer": slot.get("answer"), "sources": source_titles}, ensure_ascii=False)
