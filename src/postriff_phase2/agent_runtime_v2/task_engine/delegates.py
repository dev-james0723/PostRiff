"""Delegate adapters (CF-3 §7.3, EX-16; correction 13): read-only observers of executors that already exist.

A delegate step never writes its target. It resolves `delegate_id` only inside the step's own workspace, maps the target
record to a step state, and copies only what the target itself recorded (a publish job's provider receipt is its stored
state; the engine never writes a receipt the queue did not record). `running` means "still in flight; keep observing".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import targets


@dataclass
class Observation:
    state: str                         # running | completed | failed | blocked
    reason_code: str | None = None
    reason: str | None = None
    outputs: list = field(default_factory=list)
    read_failed: bool = False


ADAPTERS: dict = {}


def adapter(kind: str):
    def wrap(fn):
        ADAPTERS[kind] = fn
        return fn
    return wrap


def poll(cur, task: dict, step: dict) -> Observation:
    fn = ADAPTERS.get(step.get("delegateType") or "")
    if fn is None:
        return Observation("failed", None, "Rafii can't follow this kind of record yet.")
    cur.execute("SAVEPOINT delegate_read")
    try:
        return fn(cur, task, step)
    except Exception as error:  # noqa: BLE001 — an observer that can't read keeps the step open, never invents an outcome
        cur.execute("ROLLBACK TO SAVEPOINT delegate_read")
        return Observation("running", None, "Rafii could not read the current status yet.", read_failed=True)
    finally:
        cur.execute("RELEASE SAVEPOINT delegate_read")


@adapter("publish_job")
def _publish_job(cur, task, step) -> Observation:
    state = targets.workspace_state(cur, task["workspaceId"])
    job = next((j for j in (state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict) and j.get("id") == step["delegateId"]), None)
    if job is None:
        return Observation("blocked", "target_changed", "That post is no longer in this workspace's queue.")
    job_state = str(job.get("state") or "unknown")
    receipt = {"type": "publish_job", "id": job["id"], "state": job_state,
               "providerAccepted": job_state in ("provider_accepted", "published", "verified") or bool(job.get("providerAcceptedAt")),
               "verifiedAt": job.get("verifiedAt") if isinstance(job.get("verifiedAt"), (str, int, float)) else None,
               "href": f"/app/queue?job={job['id']}"}
    if job_state == "verified":
        return Observation("completed", None, None, [receipt])
    if job_state in ("failed", "canceled"):
        return Observation("failed", None, "The post didn't publish." if job_state == "failed" else "The post was cancelled in the queue.", [receipt])
    if job_state == "uncertain":
        return Observation("running", None, "Rafii can't confirm yet whether the platform published it.", [receipt])
    return Observation("running", None, None, [receipt])


@adapter("proposal")
def _proposal(cur, task, step) -> Observation:
    from .. import approvals as legacy
    item = legacy.find(cur, task["workspaceId"], task["conversationId"], step["delegateId"])
    if item is None:
        return Observation("blocked", "target_changed", "That proposal is no longer in this conversation.")
    proposal = item["proposal"]
    status = proposal.get("status")
    out = [{"type": "proposal", "id": proposal.get("id"), "state": status}]
    if status == "applied":
        verified, _checks = legacy.verify_applied(targets.workspace_state(cur, task["workspaceId"]), proposal)
        return Observation("completed" if verified else "failed", None if verified else "outcome_unknown",
                           None if verified else "It was applied, but re-reading the workspace didn't match.", out)
    if status in ("dismissed", "rejected"):
        return Observation("failed", "approval_rejected", "The proposal was dismissed.", out)
    if status == "expired":
        return Observation("failed", "approval_expired", "The proposal expired.", out)
    if status in ("superseded", "failed"):
        return Observation("failed", None, f"The proposal was {status}.", out)
    return Observation("running", None, None, out)


@adapter("agent_task")
def _agent_task(cur, task, step) -> Observation:
    cur.execute("SELECT state FROM public.pr_agent_tasks WHERE id::text=%s AND workspace_id=%s AND created_by=%s",
                (step["delegateId"], task["workspaceId"], task["createdBy"]))
    row = cur.fetchone()
    if not row:
        return Observation("blocked", "target_changed", "That task is unavailable.")
    if row[0] == "completed":
        return Observation("completed", None, None, [{"type": "agent_task", "id": step["delegateId"], "state": row[0]}])
    if row[0] in ("failed", "cancelled"):
        return Observation("failed", None, f"That task {row[0]}.", [{"type": "agent_task", "id": step["delegateId"], "state": row[0]}])
    return Observation("running")


def _stored(kind, ident, state, completed, failed, blocked=()):
    output = [{"type": kind, "id": ident, "state": state}]
    if state in completed:
        return Observation("completed", outputs=output)
    if state in failed:
        return Observation("failed", "outcome_unknown" if state == "interrupted" else None, outputs=output)
    if state in blocked:
        return Observation("blocked", "provider_disconnected" if state in ("platform_disconnected", "channel_unavailable") else "needs_input", outputs=output)
    return Observation("running", outputs=output)


@adapter("automation_item")
def _automation_item(cur, task, step):
    state = targets.workspace_state(cur, task["workspaceId"])
    occurrences = ((state.get("raffi") or {}).get("campaignPlanning") or {}).get("occurrences") or []
    matches = [(run, item) for run in occurrences for item in run.get("items", [])
               if step["delegateId"] in (item.get("id"), str(run.get("id")) + ":" + str(item.get("key")))]
    if len(matches) != 1:
        return Observation("blocked", "target_changed", "That automation item is unavailable.")
    _run, item = matches[0]
    goal = (step.get("inputs") or {}).get("goal", "published")
    return _stored("automation_item", step["delegateId"], item.get("state"),
                   ("scheduled", "published") if goal == "scheduled" else ("published",),
                   ("rejected", "failed", "approval_expired", "skipped"), ("platform_disconnected",))


@adapter("weekly_slot")
def _weekly_slot(cur, task, step):
    state = targets.workspace_state(cur, task["workspaceId"])
    weeks = ((state.get("coworker") or {}).get("weekly") or {}).get("weeks") or []
    slots = [slot for week in weeks for slot in week.get("slots", []) if slot.get("id") == step["delegateId"]]
    if len(slots) != 1:
        return Observation("blocked", "target_changed", "That weekly slot is unavailable.")
    return _stored("weekly_slot", step["delegateId"], slots[0].get("status"), ("approved", "scheduled"), ("rejected", "failed"),
                   ("needs_input", "needs_source", "needs_asset", "channel_unavailable", "approval_expired"))


@adapter("ui_attempt")
def _ui_attempt(cur, task, step):
    cur.execute("SELECT state FROM public.pr_ui_attempts WHERE id::text=%s AND workspace_id=%s", (step["delegateId"], task["workspaceId"]))
    row = cur.fetchone()
    return (_stored("ui_attempt", step["delegateId"], row[0], ("ready",), ("failed", "canceled", "interrupted")) if row else
            Observation("blocked", "target_changed", "That presentation attempt is unavailable."))


@adapter("ui_action")
def _ui_action(cur, task, step):
    cur.execute("SELECT state,outcome FROM public.pr_ui_actions WHERE idempotency_key=%s AND workspace_id=%s", (step["delegateId"], task["workspaceId"]))
    row = cur.fetchone()
    if not row:
        return Observation("blocked", "target_changed", "That presentation action is unavailable.")
    outcome = row[1] or {}
    if row[0] != "done":
        return Observation("running")
    verified = outcome.get("verified") is True
    state = str(outcome.get("outcome") or "failed")
    if state == "applied" and not verified:
        return Observation("failed", "outcome_unknown", "The action completed without a verified result.")
    return _stored("ui_action", step["delegateId"], state, ("applied",), ("rejected", "conflict", "failed", "unknown"))


@adapter("library_job")
def _library_job(cur, task, step):
    cur.execute("SELECT to_regclass('public.pr_library_jobs')")
    if not cur.fetchone()[0]:
        return Observation("blocked", "feature_unavailable", "Library processing is unavailable in this release.")
    cur.execute("SELECT status FROM public.pr_library_jobs WHERE id::text=%s AND workspace_id=%s", (step["delegateId"], task["workspaceId"]))
    row = cur.fetchone()
    return (_stored("library_job", step["delegateId"], row[0], ("completed", "partial"), ("failed", "cancelled"), ("blocked",)) if row else
            Observation("blocked", "target_changed", "That Library job is unavailable."))
