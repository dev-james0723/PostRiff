"""Evidence-linked, dismissible Raffi suggestions. Accepting never publishes or activates tasks."""
from __future__ import annotations

from datetime import date, datetime, timezone

from postriff_alpha.domain import AlphaError, uid
from .contracts import digest

UPCOMING_DAYS = 14
DISMISS_COOLDOWN = 7 * 86400
DRAFTABLE = ("LinkedIn", "Instagram", "Threads")


def _root(state: dict) -> list[dict]:
    return state.setdefault("raffi", {}).setdefault("suggestions", [])


def _days_until(value, now: float):
    """Whole calendar days (UTC) from now until a confirmed ISO date; None when it is not a date."""
    if not isinstance(value, str):
        return None
    try:
        target = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return (target - datetime.fromtimestamp(now, timezone.utc).date()).days


def _ready(channel: dict, now: float) -> bool:
    return bool(channel.get("identityVerified") and channel.get("capabilityVerified") and not channel.get("revoked") and (channel.get("expiresAt") or 0) > now)


def _evidence(state: dict, now: float) -> list[dict]:
    candidates = []
    used_assets = {asset["id"] for job in state.get("phase2", {}).get("jobs", []) for asset in job.get("manifest", {}).get("media", [])}
    for asset in state.get("phase2", {}).get("assets", []):
        if not asset.get("deleted") and asset.get("id") not in used_assets and asset.get("processing") == "decoded":
            candidates.append({"kind": "unused_asset", "reason": "An uploaded image has not been used in a scheduled post yet.", "evidence": [{"type": "asset", "id": asset["id"], "revision": asset.get("revision", 1)}], "action": "draft"})
    for campaign in state.get("raffi", {}).get("campaignPlanning", {}).get("campaigns", []):
        if campaign.get("status") == "draft" and not campaign.get("items"):
            days = _days_until((campaign.get("facts") or {}).get("date"), now)
            if days is not None and 0 <= days <= UPCOMING_DAYS:
                when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} away"
                candidates.append({"kind": "upcoming_event", "reason": f"The confirmed date {campaign['facts']['date'][:10]} for “{campaign.get('goal', 'this campaign')[:80]}” is {when} and has no draft yet.", "evidence": [{"type": "campaign", "id": campaign["id"], "revision": campaign["version"]}], "action": "campaign"})
            else:
                candidates.append({"kind": "campaign_gap", "reason": "This campaign has confirmed facts but no draft items yet.", "evidence": [{"type": "campaign", "id": campaign["id"], "revision": campaign["version"]}], "action": "campaign"})
    brief_revision = (state.get("brief") or {}).get("revision")
    drafted = [v for v in state.get("variants", []) if brief_revision is not None and v.get("briefRevision") == brief_revision]
    if drafted:
        covered = {v.get("channelId") for v in drafted}
        for channel in (state.get("phase2") or {}).get("channels", []):
            if channel.get("platform") in DRAFTABLE and _ready(channel, now) and channel.get("id") not in covered:
                candidates.append({"kind": "missing_variant", "reason": f"This brief has drafts, but none for {channel['platform']} {channel.get('account', '')} yet.".replace("  ", " "), "evidence": [{"type": "channel", "id": channel["id"], "revision": brief_revision}], "action": "draft"})
    for job in state.get("phase2", {}).get("jobs", []):
        if job.get("state") == "held":
            candidates.append({"kind": "held_draft", "reason": "A held publishing job needs a fresh review before any further action.", "evidence": [{"type": "job", "id": job["id"], "revision": len(job.get("events", []))}], "action": "review"})
    return candidates


def _recently_dismissed(items: list[dict], candidate: dict, now: float) -> bool:
    """A dismissed suggestion stays quiet for a week even if its evidence revision moves on."""
    target = candidate["evidence"][0]["id"]
    return any(item["kind"] == candidate["kind"] and item["evidence"][0]["id"] == target and item["status"] == "dismissed" and now - item.get("dismissedAt", 0) < DISMISS_COOLDOWN for item in items)


def refresh(state: dict, now: float) -> list[dict]:
    items = _root(state)
    evidence = _evidence(state, now)
    for candidate in evidence:
        identity = digest({"kind": candidate["kind"], "evidence": candidate["evidence"]})
        existing = next((item for item in items if item["identity"] == identity), None)
        if existing:
            existing["lastSeenAt"] = now
            continue
        if _recently_dismissed(items, candidate, now):
            continue
        items.append({**candidate, "id": uid(), "identity": identity, "status": "open", "createdAt": now, "lastSeenAt": now, "actionRef": None})
    state.setdefault("raffi", {})["suggestionsCheckedAt"] = now
    live = {digest({"kind": item["kind"], "evidence": item["evidence"]}) for item in evidence}
    for item in items:
        if item["identity"] not in live and item["status"] in ("open", "snoozed"):
            item["status"] = "stale"
            item["staleAt"] = now
        elif item['status'] == 'snoozed' and item.get('snoozedUntil', now + 1) <= now:
            item['status'] = 'open'
    return items


def apply_action(state: dict, action: str, payload: dict, actor: str, now: float) -> dict | None:
    if not action.startswith("raffi_suggestion_"):
        return None
    items = refresh(state, now)
    if action == "raffi_suggestion_refresh":
        return {"open": len([item for item in items if item["status"] == "open"])}
    item = next((entry for entry in items if entry["id"] == payload.get("suggestionId")), None)
    if item is None: raise AlphaError("Suggestion unavailable.", 404)
    if item["status"] == "stale": raise AlphaError("This suggestion is no longer current.", 409)
    if action == "raffi_suggestion_dismiss":
        item.update({"status": "dismissed", "dismissedBy": actor, "dismissedAt": now})
    elif action == "raffi_suggestion_snooze":
        until = payload.get("until")
        if not isinstance(until, (int, float)) or until <= now: raise AlphaError("Choose a future snooze time.")
        item.update({"status": "snoozed", "snoozedUntil": until, "snoozedBy": actor})
    elif action == "raffi_suggestion_accept":
        live = {digest({'kind': entry['kind'], 'evidence': entry['evidence']}) for entry in _evidence(state, now)}
        if item['identity'] not in live:
            raise AlphaError("This suggestion's evidence changed. Refresh suggestions.", 409)
        if (item.get('actionRef') or {}).get('targetId'):
            return {"suggestionId": item["id"], "status": item["status"], "actionRef": item["actionRef"]}
        evidence = item['evidence'][0]
        item["actionRef"] = {"id": (item.get('actionRef') or {}).get('id') or uid(), "type": {"draft": "draft_intent", "campaign": "campaign_editor", "review": "review_queue"}[item["action"]], "authority": "open_for_review", "workspaceId": state['workspace']['id'], "targetType": evidence['type'], "targetId": evidence['id'], "targetRevision": evidence['revision']}
        item.update({"status": "accepted", "acceptedBy": actor, "acceptedAt": now})
    else:
        raise AlphaError("Unsupported suggestion action.")
    return {"suggestionId": item["id"], "status": item["status"], "actionRef": item.get("actionRef")}
