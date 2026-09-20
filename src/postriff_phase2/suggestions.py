"""Evidence-linked, dismissible Raffi suggestions. Accepting never publishes or activates tasks."""
from __future__ import annotations

from postriff_alpha.domain import AlphaError, uid
from .contracts import digest


def _root(state: dict) -> list[dict]:
    return state.setdefault("raffi", {}).setdefault("suggestions", [])


def _evidence(state: dict) -> list[dict]:
    candidates = []
    used_assets = {asset["id"] for job in state.get("phase2", {}).get("jobs", []) for asset in job.get("manifest", {}).get("media", [])}
    for asset in state.get("phase2", {}).get("assets", []):
        if not asset.get("deleted") and asset.get("id") not in used_assets and asset.get("processing") == "decoded":
            candidates.append({"kind": "unused_asset", "reason": "An approved reusable asset has not been used in a draft.", "evidence": [{"type": "asset", "id": asset["id"], "revision": asset.get("revision", 1)}], "action": "draft"})
    for campaign in state.get("raffi", {}).get("campaignPlanning", {}).get("campaigns", []):
        if campaign.get("status") == "draft" and not campaign.get("items"):
            candidates.append({"kind": "campaign_gap", "reason": "This campaign has confirmed facts but no draft items yet.", "evidence": [{"type": "campaign", "id": campaign["id"], "revision": campaign["version"]}], "action": "campaign"})
    for job in state.get("phase2", {}).get("jobs", []):
        if job.get("state") == "held":
            candidates.append({"kind": "held_draft", "reason": "A held publishing job needs a fresh review before any further action.", "evidence": [{"type": "job", "id": job["id"], "revision": len(job.get("events", []))}], "action": "review"})
    return candidates


def refresh(state: dict, now: float) -> list[dict]:
    items = _root(state)
    for candidate in _evidence(state):
        identity = digest({"kind": candidate["kind"], "evidence": candidate["evidence"]})
        existing = next((item for item in items if item["identity"] == identity), None)
        if existing:
            existing["lastSeenAt"] = now
            continue
        items.append({**candidate, "id": uid(), "identity": identity, "status": "open", "createdAt": now, "lastSeenAt": now, "actionRef": None})
    live = {digest({"kind": item["kind"], "evidence": item["evidence"]}) for item in _evidence(state)}
    for item in items:
        if item["identity"] not in live and item["status"] in ("open", "snoozed"):
            item["status"] = "stale"
            item["staleAt"] = now
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
        if item.get("actionRef"):
            return {"suggestionId": item["id"], "status": item["status"], "actionRef": item["actionRef"]}
        item["actionRef"] = {"id": uid(), "type": {"draft": "draft_intent", "campaign": "campaign_editor", "review": "review_queue"}[item["action"]], "authority": "open_for_review"}
        item.update({"status": "accepted", "acceptedBy": actor, "acceptedAt": now})
    else:
        raise AlphaError("Unsupported suggestion action.")
    return {"suggestionId": item["id"], "status": item["status"], "actionRef": item.get("actionRef")}
