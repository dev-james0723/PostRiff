"""“What needs my attention?” (adaptive coworker spec §12, §19; architecture lock T1).

A deterministic synthesis of what is waiting on this person, from authoritative state only: approvals, failed /
held / uncertain posts, reconnects, weekly plans ready or blocked, drafts waiting, missing assets, campaign
deadlines, important unanswered engagement, high-confidence opportunities, budget and billing. Each item says why
it matters, with its evidence and a deep link. Priority comes from a fixed rule table; engagement and
opportunities are never marked urgent on their own.
"""
from __future__ import annotations

from ..notifications import detector

# Lower is more important. Only these rules decide the order; there is no model in the loop.
PRIORITY = {"publish.failed": 10, "publish.uncertain": 10, "channel.reconnect_required": 15, "billing.payment_failed": 15, "campaign.approval_required": 20,
            "campaign.blocked": 25, "campaign.week_ready": 30, "campaign.drafts_ready": 35, "asset.review_required": 40, "budget.threshold_reached": 45,
            "billing.trial_ending": 45, "engagement.needs_attention": 60, "learning.preference_proposed": 70, "opportunity.detected": 80}
URGENT = {"publish.failed", "publish.uncertain", "channel.reconnect_required", "billing.payment_failed"}
WHY = {
    "publish.failed": "A post that was approved did not go out. The draft is kept; it needs a decision.",
    "publish.uncertain": "Rafii can't confirm whether this post went out. Check the platform before retrying, so it isn't posted twice.",
    "channel.reconnect_required": "Posts for this account are paused until it is reconnected.",
    "billing.payment_failed": "The plan stays active only if the payment method is updated.",
    "campaign.approval_required": "It publishes only if someone with approval rights approves it before its time.",
    "campaign.blocked": "Rafii stopped here and needs your decision to continue.",
    "campaign.week_ready": "Next week's posts are drafted and checked; nothing is scheduled until you approve.",
    "campaign.drafts_ready": "Drafts are waiting for review; nothing is scheduled.",
    "budget.threshold_reached": "Paid work pauses at the limit.",
    "billing.trial_ending": "Publishing pauses when the trial ends unless a plan is chosen.",
    "engagement.needs_attention": "Someone asked a question or needs an answer. Not urgent unless you decide it is.",
    "learning.preference_proposed": "Rafii noticed a pattern in your edits; it becomes a preference only if you accept it.",
    "opportunity.detected": "A fresh, relevant item from a source you follow.",
}
SKIP = {"publish.verified", "publish.scheduled", "automation.completed", "analytics.weekly_ready"}


def build(cur, workspace_id, principal, member, state, now):
    events = detector.from_state(workspace_id, state, now) + detector.from_database(cur, workspace_id, now)
    listening = ((state.get("coworker") or {}).get("listening") or {}).get("opportunities") or []
    for opportunity in listening:
        if opportunity.get("status") == "open" and opportunity.get("confidence") == "high" and opportunity.get("expiresAt", 0) > now:
            events.append({"event_type": "opportunity.detected", "dedupe_key": f"opportunity:{opportunity['id']}", "entity_type": "opportunity",
                           "entity_id": opportunity["id"], "payload": {"title": opportunity.get("title"), "why": opportunity.get("why"), "href": "/app/weekly?tab=opportunities"}})
    audiences = {"campaign.approval_required": "approve", "publish.failed": "approve", "publish.uncertain": "approve", "channel.reconnect_required": "manage_connections",
                 "billing.payment_failed": "owner", "billing.trial_ending": "owner", "budget.threshold_reached": "owner", "learning.preference_proposed": "owner",
                 "engagement.needs_attention": "reply"}
    items, seen = [], set()
    for event in events:
        kind = event["event_type"]
        if kind in SKIP or event["dedupe_key"] in seen:
            continue
        need = audiences.get(kind, "edit")
        allowed = member.role == "owner" if need == "owner" else member.allows(need)
        if not allowed:
            continue
        seen.add(event["dedupe_key"])
        payload = event.get("payload") or {}
        items.append({"id": event["dedupe_key"], "type": kind, "priority": PRIORITY.get(kind, 90), "urgent": kind in URGENT,
                      "title": payload.get("title") or kind.replace(".", " ").replace("_", " ").capitalize(), "why": WHY.get(kind, ""),
                      "detail": payload.get("reason") or payload.get("platform") or payload.get("recipeName") or "",
                      "evidence": {"entityType": event.get("entity_type"), "entityId": event.get("entity_id"), "platform": payload.get("platform"),
                                   "account": payload.get("account"), "count": payload.get("count")},
                      "href": payload.get("href") or "/app"})
    items.sort(key=lambda i: (i["priority"], i["title"]))
    return {"items": items[:30], "counts": {"total": len(items), "urgent": sum(1 for i in items if i["urgent"])},
            "rules": "Order comes from a fixed rule table: failed or uncertain publishing and reconnects first, then approvals, then reviews. Engagement and opportunities are never urgent on their own."}
