"""CF-2 H1/H3: transactional invalidation of engine approvals and work.

The permissions store invokes these only in enforce mode. Engine off/shadow is
also checked here, so a stored choice never changes legacy task behavior.
"""
from __future__ import annotations
import time
from . import flags, model, store, checkpoints


def install():
    from ..agent_permissions import register_revocation_handler
    register_revocation_handler("agent_approvals", approvals)
    register_revocation_handler("agent_tasks", tasks)


def _present(cur, event):
    if not flags.enabled_for(event.workspace_id):
        return False
    cur.execute("SELECT to_regclass('public.pr_agent_tasks')")
    return bool(cur.fetchone()[0])


def _caps(event):
    return sorted({str(cap).removeprefix("tool.") for cap in event.denied_now})


def approvals(cur, event):
    if not _present(cur, event):
        return 0
    cur.execute("UPDATE public.pr_agent_approvals SET state='revoked',decision_surface='system',decided_at=now(),updated_at=now() "
                "WHERE workspace_id=%s AND (%s::uuid IS NULL OR requested_for=%s::uuid) AND state='pending' "
                "AND (%s OR capability_id=ANY(%s::text[]))",
                (event.workspace_id, event.user_id, event.user_id, event.reason == "membership_ended", _caps(event)))
    return cur.rowcount or 0


def tasks(cur, event):
    if not _present(cur, event):
        return 0
    from ...ideas import IdeasService
    ideas = object.__new__(IdeasService)  # event methods use only this cursor, never a service/session
    cur.execute("SELECT id::text FROM public.pr_agent_tasks WHERE workspace_id=%s AND (%s::uuid IS NULL OR created_by=%s::uuid) "
                "AND state IN ('queued','running','awaiting_approval','blocked') ORDER BY id",
                (event.workspace_id, event.user_id, event.user_id))
    changed = 0
    caps = set(_caps(event))
    ended = event.reason == "membership_ended"
    for (task_id,) in cur.fetchall():
        task = store.lock_task(cur, ideas, event.workspace_id, task_id)
        steps = store.load_steps(cur, event.workspace_id, task_id, lock=True)
        affected = False
        if ended:
            cur.execute("UPDATE public.pr_agent_tasks SET cancel_requested_at=coalesce(cancel_requested_at,now()), "
                        "cancel_requested_by=coalesce(cancel_requested_by,created_by),authz_token=%s,updated_at=now() WHERE id::text=%s",
                        (event.token_after, task_id))
            task["cancelRequestedAt"] = task["cancelRequestedAt"] or time.time()
        for step in steps:
            if step["state"] not in model.OPEN_STATES:
                continue
            observer = step["kind"] == "delegate" and step["observesExternal"] and step["delegateType"] in ("publish_job", "automation_item")
            if ended and observer:
                store.set_step(cur, step, state="queued", next_attempt_at=time.time(), reason_code=None, reason=None)
            elif ended or str(step.get("capabilityId") or "").removeprefix("tool.") in caps:
                store.set_step(cur, step, state="cancelled" if ended else "blocked", reason_code="cancelled_by_revocation" if ended else "permission_revoked",
                               reason="Your permissions changed.", next_attempt_at=None)
                store.close_pending_approvals(cur, event.workspace_id, task_id, "revoked", step_ids={step["stepId"]})
                affected = True
        if affected or ended:
            checkpoints.discard_live(cur, event.workspace_id, task_id, "permission_revoked")
            changed += 1
        store.refresh(cur, ideas, task, steps)
        cur.execute("UPDATE public.pr_agent_tasks SET next_wake_at=now(),authz_token=%s WHERE id::text=%s "
                    "AND state IN ('queued','running','awaiting_approval','blocked')", (event.token_after, task_id))
    return changed
