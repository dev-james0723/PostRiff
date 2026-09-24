"""The content lifecycle of an automation run, shared with the web app (web/src/lib/automation-lifecycle.ts).

A run (one anchor of an automation) first researches and drafts; each destination then becomes an item that moves
through review, approval, scheduling and publishing. The run's generation stage is stored; an item's state is
stored and advanced only through `move`, so an item can never jump from "ready for review" to "scheduled" without
an approval in between. Both sides of the app read the same vectors (tests/fixtures/automation_lifecycle.json).

Silence never approves: nothing here moves an item out of `ready_for_review` except a recorded decision or expiry.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

RUN_STAGES = ("planned", "researching", "drafting", "drafted", "skipped", "source_unavailable", "failed")
RUN_TERMINAL = ("skipped", "source_unavailable", "failed")
ITEM_STATES = ("ready_for_review", "needs_revision", "approved", "scheduled", "publishing", "published",
               "rejected", "skipped", "failed", "platform_disconnected", "approval_expired")
ITEM_TERMINAL = ("published", "rejected", "approval_expired", "failed", "skipped")
TRANSITIONS = {
    "ready_for_review": ("approved", "rejected", "needs_revision", "approval_expired", "platform_disconnected", "skipped"),
    "needs_revision": ("ready_for_review", "rejected", "approval_expired", "skipped"),
    "approved": ("scheduled", "ready_for_review", "approval_expired", "platform_disconnected", "failed", "skipped"),
    "scheduled": ("publishing", "published", "failed", "platform_disconnected", "skipped"),
    "publishing": ("published", "failed"),
    "platform_disconnected": ("approved", "ready_for_review", "approval_expired", "failed", "skipped"),
    "published": (), "rejected": (), "approval_expired": (), "failed": (), "skipped": (),
}
# What the run shows once drafted: the most active item wins, then problems, then settled outcomes.
PRIORITY = ("publishing", "scheduled", "approved", "ready_for_review", "needs_revision", "platform_disconnected",
            "failed", "approval_expired", "published", "rejected", "skipped")
ATTENTION = ("needs_revision", "platform_disconnected", "failed", "approval_expired")
# Plain words for every state, shown in the app and in Raffi's explanations.
LABELS = {
    "planned": "Planned", "researching": "Researching", "drafting": "Drafting", "drafted": "Drafted",
    "skipped": "Skipped", "source_unavailable": "Source unavailable", "failed": "Failed",
    "ready_for_review": "Ready for review", "needs_revision": "Changes requested", "approved": "Approved",
    "scheduled": "Scheduled", "publishing": "Publishing", "published": "Published", "rejected": "Rejected",
    "platform_disconnected": "Account disconnected", "approval_expired": "Approval expired",
}
# Job states (store.py / hosted_worker.py) → item state.
JOB_ITEM = {"approved": "scheduled", "scheduled": "scheduled", "claimed": "scheduled",
            "submitting": "publishing", "processing": "publishing", "provider_accepted": "publishing", "published": "publishing", "uncertain": "publishing",
            "verified": "published", "failed": "failed", "canceled": "skipped"}


def can_move(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


def move(item: dict, target: str, *, reason: str | None = None, at: float | None = None) -> dict:
    """Advance one item. Moving to its current state is a no-op; anything not in TRANSITIONS is refused."""
    current = item.get("state")
    if current == target:
        if reason is not None:
            item["reason"] = reason
        return item
    if not can_move(current, target):
        raise AlphaError(f"This post cannot go from {LABELS.get(current, current)} to {LABELS.get(target, target)}.", 409, code="lifecycle_transition")
    item["state"] = target
    item["reason"] = reason
    if at is not None:
        item["changedAt"] = at
    return item


def job_item_state(job_state: str, channel_ready: bool) -> str | None:
    """The item state a job implies. A held job is a disconnected account when its channel is not ready, else failed."""
    if job_state == "held":
        return "failed" if channel_ready else "platform_disconnected"
    return JOB_ITEM.get(job_state)


def status(run: dict) -> str:
    """What the run shows: its generation stage until drafted, then the items' combined state."""
    stage = run.get("lifecycle") or "planned"
    if stage != "drafted":
        return stage
    states = [item.get("state") for item in run.get("items") or []]
    for state in PRIORITY:
        if state in states:
            return state
    return "drafted"


def attention(run: dict) -> bool:
    """Whether the person has something to look at: a problem, or a draft waiting for approval before it can post."""
    if run.get("lifecycle") in ("source_unavailable", "failed"):
        return True
    for item in run.get("items") or []:
        if item.get("state") in ATTENTION or (item.get("state") == "ready_for_review" and item.get("publishAt")):
            return True
    return False


def projected(run: dict) -> str:
    """The 018 projection's check-constrained state: the generation stage, never a publishing state."""
    stage = run.get("lifecycle")
    if stage is None:
        return run.get("state", "pending")
    if stage == "planned":
        return "pending"
    if stage in ("researching", "drafting"):
        return "running"
    if stage == "drafted":
        return "completed"
    if stage == "skipped":
        return "cancelled"
    return "failed"
