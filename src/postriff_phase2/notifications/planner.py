"""Deterministic notification planner (adaptive coworker spec §14; architecture lock N3).

Pure functions. Given an event, the workspace's members and each person's preferences, decide who receives it on
which channel, now or in the digest, and what quiet hours, a temporary mute, an unsubscribe or a rate limit change.
Nothing here is model-driven: recipient, urgency, transactional status, security classification, dedupe (the
database's unique keys), quiet hours, digest and rate limits are all code.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import catalog

FIELDS = ("in_app", "email_mode", "push_mode", "digest_frequency", "quiet_start", "quiet_end", "time_zone", "muted_until", "email_unsubscribed")


def zone(name):
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def effective_preferences(rows, workspace_id, category):
    """Merge a person's preference rows, most specific first: (workspace, category) → (workspace, *) → (*, category)
    → (*, *). `rows` maps (scope_key, category) → row dict. The first non-null value of each field wins."""
    order = [(workspace_id or "*", category), (workspace_id or "*", "*"), ("*", category), ("*", "*")]
    merged = {}
    for key in order:
        row = rows.get(key) or {}
        for field in FIELDS:
            if field not in merged and row.get(field) is not None:
                merged[field] = row[field]
    return merged


def opted_out(event_type, channel, mode, prefs, now):
    """Re-checked at send time: the reason a still-queued email or push must not go out any more (an unsubscribe,
    a bounce or complaint suppression, a mute, or the channel switched off after it was planned), else None.
    Transactional notices ignore these, as they do when planned."""
    if catalog.transactional(event_type):
        return None
    if isinstance(prefs.get("muted_until"), (int, float)) and prefs["muted_until"] > now:
        return "muted"
    if channel == "email":
        if prefs.get("email_unsubscribed"):
            return "unsubscribed"
        if prefs.get("email_mode") == "off":
            return "email_off"
        if mode == "digest" and prefs.get("digest_frequency") == "off":
            return "digest_off"
    if channel == "push" and prefs.get("push_mode") == "off":
        return "push_off"
    return None


def in_quiet_hours(now, prefs):
    start, end = prefs.get("quiet_start"), prefs.get("quiet_end")
    if start is None or end is None or start == end:
        return False
    local = datetime.fromtimestamp(now, zone(prefs.get("time_zone")))
    minute = local.hour * 60 + local.minute
    return start <= minute < end if start < end else (minute >= start or minute < end)


def quiet_end_after(now, prefs):
    """The next moment the quiet window ends, in the person's time zone (DST-safe: the local wall time is resolved
    on the actual date)."""
    tz = zone(prefs.get("time_zone"))
    local = datetime.fromtimestamp(now, tz)
    end = prefs["quiet_end"]
    candidate = local.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    if candidate <= local:
        candidate = (local + timedelta(days=1)).replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    # Re-attach the zone after date arithmetic so a DST change between today and tomorrow is honoured.
    naive = candidate.replace(tzinfo=None)
    return naive.replace(tzinfo=tz).timestamp()


def next_digest(now, prefs):
    tz = zone(prefs.get("time_zone"))
    local = datetime.fromtimestamp(now, tz)
    frequency = prefs.get("digest_frequency") or "daily"
    target = local.replace(hour=catalog.DIGEST_HOUR, minute=0, second=0, microsecond=0)
    if frequency == "weekly":
        days = (7 - local.weekday()) % 7
        target = (local + timedelta(days=days)).replace(hour=catalog.DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if target <= local:
            target = target + timedelta(days=7)
    elif target <= local:
        target = target + timedelta(days=1)
    return target.replace(tzinfo=None).replace(tzinfo=tz).timestamp()


def audience(members, event, actor=None):
    """The members an event reaches: the permission class in the catalogue, re-checked here, never widened.
    `members`: [{userId, membership (permissions.Membership), active}]."""
    who = catalog.spec(event["event_type"])["audience"]
    if who == "actor":
        return [m for m in members if m["userId"] == (actor or event.get("actor"))]
    if who == "owner":
        return [m for m in members if m.get("active", True) and m["membership"].role == "owner"]
    return [m for m in members if m.get("active", True) and m["membership"].allows(who)]


def plan(event, recipient, prefs_rows, now, *, push_available=False, email_available=True, recent=None):
    """Planned deliveries for one person: [{channel, mode, status, next_attempt_at, reason}]. Suppressed rows are
    kept (status 'suppressed', with the reason) so the audit shows why nothing was sent."""
    spec = catalog.spec(event["event_type"])
    transactional = bool(spec.get("transactional"))
    severity = event.get("severity") or spec["severity"]
    prefs = effective_preferences(prefs_rows, event.get("workspace_id"), spec["category"])
    if not prefs.get("time_zone") and recipient.get("time_zone"):
        prefs["time_zone"] = recipient["time_zone"]
    recent = recent or {}
    out = []
    # In-app: always recorded for the centre (it is the audit of what Rafii told the person), unless switched off.
    in_app_on = prefs.get("in_app", True) is not False or transactional
    out.append({"channel": "in_app", "mode": "in_app", "status": "delivered" if in_app_on else "suppressed", "next_attempt_at": now,
                "reason": None if in_app_on else "in_app_off"})
    muted = isinstance(prefs.get("muted_until"), (int, float)) and prefs["muted_until"] > now and not transactional
    quiet = in_quiet_hours(now, prefs) and severity not in catalog.BREAKS_QUIET_HOURS

    # Email.
    mode = prefs.get("email_mode") or spec["email"]
    if transactional:
        mode = "immediate"
    reason = None
    if not email_available:
        mode, reason = "off", "email_unconfigured"
    elif prefs.get("email_unsubscribed") and not transactional:
        mode, reason = "off", "unsubscribed"
    elif muted:
        mode, reason = "off", "muted"
    if mode == "immediate" and recent.get("email", 0) >= catalog.RATE_LIMITS["email"] and not transactional:
        mode, reason = "digest", "rate_limited"
    if mode == "immediate":
        when = quiet_end_after(now, prefs) if quiet and severity in ("info", "action") else now
        out.append({"channel": "email", "mode": "immediate", "status": "pending", "next_attempt_at": when, "reason": "quiet_hours" if when != now else None})
    elif mode == "digest":
        if (prefs.get("digest_frequency") or "daily") == "off":
            out.append({"channel": "email", "mode": "digest", "status": "suppressed", "next_attempt_at": now, "reason": "digest_off"})
        else:
            out.append({"channel": "email", "mode": "digest", "status": "pending", "next_attempt_at": next_digest(now, prefs), "reason": reason})
    else:
        out.append({"channel": "email", "mode": "immediate", "status": "suppressed", "next_attempt_at": now, "reason": reason or "email_off"})

    # Push: only for an explicit opt-in (an active subscription), never in a digest.
    push_mode = prefs.get("push_mode") or spec["push"]
    if push_mode == "immediate":
        if not push_available:
            push_reason = "no_subscription"
        elif muted:
            push_reason = "muted"
        elif recent.get("push", 0) >= catalog.RATE_LIMITS["push"] and severity not in ("critical", "security"):
            push_reason = "rate_limited"
        else:
            push_reason = None
        if push_reason:
            out.append({"channel": "push", "mode": "immediate", "status": "suppressed", "next_attempt_at": now, "reason": push_reason})
        else:
            when = quiet_end_after(now, prefs) if quiet else now
            out.append({"channel": "push", "mode": "immediate", "status": "pending", "next_attempt_at": when, "reason": "quiet_hours" if when != now else None})
    return out
