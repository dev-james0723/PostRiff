"""Service-only checkpoints of a paused Manager run (CF-3 §11, EX-25; fixes 2, 4, 5 of §20).

The SDK RunState of a run paused on `proposal_apply` moves out of the member-readable `pr_agent_runs.artifact.pendingRun` into
`pr_agent_checkpoints`. Claiming never deletes it before a resume succeeds; a version or SDK change, or expiry, discards it
(the deterministic "Done and checked" answer stands); only the task creator's request can claim it; consumed and discarded
checkpoints keep no payload (a CHECK in 108).
"""
from __future__ import annotations

import json

from . import model, store

KIND = "sdk_run_state"
CONTINUE_LABEL = "Continue where Rafii stopped"


def sdk_version() -> str:
    try:
        from importlib.metadata import version
        return version("openai-agents")[:40]
    except Exception:  # noqa: BLE001
        return "unknown"


def runtime_version() -> str:
    from ..service import RUNTIME_VERSION
    return RUNTIME_VERSION


def available(cur, workspace_id: str, task_id: str) -> dict | None:
    cur.execute("SELECT id::text,state,payload->'proposalIds',runtime_version,sdk_version FROM public.pr_agent_checkpoints WHERE task_id::text=%s "
                "AND workspace_id=%s AND kind=%s AND state='available' AND expires_at > now()", (task_id, workspace_id, KIND))
    row = cur.fetchone()
    return {"checkpointId": row[0], "state": row[1], "proposalIds": list(row[2] or []), "runtimeVersion": row[3], "sdkVersion": row[4]} if row else None


def live(cur, workspace_id: str, task_id: str) -> dict | None:
    cur.execute("SELECT id::text,state,extract(epoch from expires_at),runtime_version,sdk_version,writer_model,cardinality(approval_ids),"
                "extract(epoch from claim_expires_at) FROM public.pr_agent_checkpoints WHERE task_id::text=%s AND workspace_id=%s AND kind=%s "
                "AND state IN ('available','claimed')", (task_id, workspace_id, KIND))
    row = cur.fetchone()
    if not row:
        return None
    return {"checkpointId": row[0], "state": row[1], "expiresAt": float(row[2]), "runtimeVersion": row[3], "sdkVersion": row[4], "writerModel": row[5],
            "approvals": int(row[6] or 0), "claimExpiresAt": float(row[7]) if row[7] is not None else None}


def store_run(cur, ideas, task: dict, state_json: str, proposal_ids: list, *, writer_model: str | None, stored_at: float) -> str | None:
    """Keep a paused run's state (never on the member-readable run artifact). Over 1 MiB → none (deterministic path)."""
    payload = {"state": state_json, "proposalIds": [p for p in proposal_ids if isinstance(p, str)][:10], "storedAt": stored_at,
               "writerModel": writer_model if isinstance(writer_model, str) else None}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if len(text.encode("utf-8")) > model.CHECKPOINT_MAX_BYTES - 1024:
        store.log_event("checkpoint_too_large", taskId=task["taskId"])
        return None
    discard_live(cur, task["workspaceId"], task["taskId"], "replaced")
    approval_ids = []
    for proposal_id in payload["proposalIds"]:
        approval = store.approval_by_proposal(cur, task["workspaceId"], proposal_id)
        if approval is not None and approval["taskId"] == task["taskId"]:
            approval_ids.append(approval["approvalId"])
    cur.execute("INSERT INTO public.pr_agent_checkpoints(task_id,workspace_id,kind,payload,payload_hash,runtime_version,sdk_version,writer_model,approval_ids,"
                "expires_at) VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::uuid[],least((SELECT hard_expires_at FROM public.pr_agent_tasks WHERE id::text=%s),"
                "coalesce((SELECT max(expires_at) FROM public.pr_agent_approvals WHERE id=ANY(%s::uuid[])),now()+make_interval(secs => %s)))) RETURNING id::text",
                (task["taskId"], task["workspaceId"], KIND, text, model.sha256(text), runtime_version(), sdk_version(),
                 payload["writerModel"][:80] if payload["writerModel"] else None, approval_ids, task["taskId"], approval_ids, model.APPROVAL_TTL_SECONDS))
    checkpoint_id = cur.fetchone()[0]
    ensure_continuation(cur, task)
    store.emit(cur, ideas, task, "task_state", checkpoint="stored")
    return checkpoint_id


def ensure_continuation(cur, task: dict, *, state: str = "queued", reason_code: str | None = None) -> dict | None:
    """The `continuation` step that represents resuming the paused run (never claimed by any executor; resumed only by the
    creator's own request). At most one open per task; none when the plan is already 12 steps long."""
    steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
    open_one = next((s for s in steps if s["kind"] == "continuation" and s["state"] in model.OPEN_STATES), None)
    if open_one is not None:
        if open_one["state"] != state or open_one["reasonCode"] != reason_code:
            store.set_step(cur, open_one, state=state, reason_code=reason_code,
                           reason="Rafii stopped to wait for an approval; continue when you're ready." if state == "blocked" else None)
        return open_one
    if len(steps) >= model.MAX_STEPS:
        return None
    key = f"s{len(steps) + 1}"
    cur.execute("INSERT INTO public.pr_agent_steps(task_id,workspace_id,step_key,label,kind,risk_class,effect,state,reason_code,reason,retry_class,max_attempts,"
                "timeout_seconds) VALUES(%s,%s,%s,%s,'continuation','R0','READ',%s,%s,%s,'manual',1,200)",
                (task["taskId"], task["workspaceId"], key, CONTINUE_LABEL, state, reason_code,
                 "Rafii stopped to wait for an approval; continue when you're ready." if state == "blocked" else None))
    return store.load_step(cur, task["workspaceId"], task["taskId"], key)


def needs_continue(cur, ideas, task: dict) -> None:
    """The approval this run waited on was decided, but not in the creator's own request (or not on a surface that resumes
    inline): the continuation waits for the creator's Continue (needsMe.kind='continue')."""
    ensure_continuation(cur, task, state="blocked", reason_code="needs_input")


def claim(cur, workspace_id: str, task_id: str, principal: str, claimer: str, *, proposal_id: str | None = None) -> tuple[str, dict] | None:
    """(checkpoint id, payload) for the creator's own request, or None. A runtime or SDK change discards it (runtime_changed)."""
    task = store.load_task(cur, workspace_id, task_id)
    if task is None or task["createdBy"] != str(principal):
        return None
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='discarded',payload='{}'::jsonb,discard_reason='runtime_changed',updated_at=now() "
                "WHERE task_id::text=%s AND workspace_id=%s AND state='available' AND expires_at<=now()", (task_id, workspace_id))
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='claimed',claimed_by=%s,claim_expires_at=now()+make_interval(secs => %s),updated_at=now() "
                "WHERE task_id::text=%s AND workspace_id=%s AND kind=%s AND state='available' AND expires_at > now()"
                + (" AND payload->'proposalIds' ? %s" if proposal_id else "") + " RETURNING id::text,payload,runtime_version,sdk_version,payload_hash",
                (claimer[:80], model.CHECKPOINT_CLAIM_SECONDS, task_id, workspace_id, KIND, *([proposal_id] if proposal_id else [])))
    row = cur.fetchone()
    if not row:
        return None
    if (row[2] != runtime_version() or row[3] != sdk_version()
            or model.sha256(json.dumps(row[1] or {}, ensure_ascii=False, sort_keys=True, default=str)) != row[4]):
        discard(cur, row[0], "runtime_changed")
        return None
    return row[0], dict(row[1] or {})


def find_task_for_proposal(cur, workspace_id: str, conversation_id: str, proposal_id: str) -> str | None:
    cur.execute("SELECT c.task_id::text FROM public.pr_agent_checkpoints c JOIN public.pr_agent_tasks t ON t.id=c.task_id AND t.workspace_id=c.workspace_id "
                "WHERE c.workspace_id=%s AND t.conversation_id::text=%s AND c.kind=%s AND c.state='available' AND c.payload->'proposalIds' ? %s "
                "ORDER BY c.created_at DESC LIMIT 1", (workspace_id, conversation_id, KIND, proposal_id))
    row = cur.fetchone()
    return row[0] if row else None


def consume(cur, checkpoint_id: str) -> None:
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='consumed',payload='{}'::jsonb,claim_expires_at=NULL,updated_at=now() "
                "WHERE id::text=%s AND state IN ('claimed','available')", (checkpoint_id,))


def discard(cur, checkpoint_id: str, reason: str) -> None:
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='discarded',payload='{}'::jsonb,discard_reason=%s,updated_at=now() "
                "WHERE id::text=%s AND state IN ('claimed','available')", (reason, checkpoint_id))


def discard_live(cur, workspace_id: str, task_id: str, reason: str) -> int:
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='discarded',payload='{}'::jsonb,discard_reason=%s,updated_at=now() "
                "WHERE task_id::text=%s AND workspace_id=%s AND state IN ('available','claimed') RETURNING 1", (reason, task_id, workspace_id))
    return len(cur.fetchall())


def release(cur, checkpoint_id: str) -> None:
    """A resume that ran out of time: back to available, so the creator's Continue can resume it (effects dedupe by key)."""
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='available',claimed_by=NULL,claim_expires_at=NULL,updated_at=now() "
                "WHERE id::text=%s AND state='claimed'", (checkpoint_id,))


def finish(service, ideas, workspace_id: str, task_id: str, checkpoint_id: str, *, ok: bool) -> None:
    """After the creator's resume: consumed (and the continuation completed) on success; otherwise discarded/resume_failed and
    the continuation failed/outcome_unknown. Bookkeeping in its own transaction; never raises."""
    try:
        with store.service_tx(service, workspace_id) as cur:
            task = store.lock_task(cur, ideas, workspace_id, task_id)
            if task is None:
                return
            if ok:
                consume(cur, checkpoint_id)
            else:
                discard(cur, checkpoint_id, "resume_failed")
            for step in store.load_steps(cur, workspace_id, task_id):
                if step["kind"] == "continuation" and step["state"] in model.OPEN_STATES:
                    if ok:
                        store.set_step(cur, step, state="completed", reason=None, reason_code=None)
                    else:
                        store.set_step(cur, step, state="failed", reason_code="outcome_unknown", reason="Rafii couldn't continue; your approval still stands.")
            store.refresh(cur, ideas, task)
    except Exception as error:  # noqa: BLE001
        store.log_event("checkpoint_finish_failed", taskId=task_id, errorClass=type(error).__name__)


def sweep(cur, workspace_id) -> dict:
    """Expiry phase: claims past their lease return to available; checkpoints past expiry are discarded (payload cleared)."""
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='available',claimed_by=NULL,claim_expires_at=NULL,updated_at=now() "
                "WHERE workspace_id=%s AND state='claimed' AND claim_expires_at < now() AND expires_at > now() RETURNING task_id::text", (workspace_id,))
    tasks = [row[0] for row in cur.fetchall()]
    released = len(tasks)
    for task_id in tasks:
        for step in store.load_steps(cur, workspace_id, task_id):
            if step["kind"] == "continuation" and step["state"] in model.OPEN_STATES:
                store.set_step(cur, step, state="failed", reason_code="outcome_unknown", reason="The previous continuation stopped before its outcome was known.")
    cur.execute("UPDATE public.pr_agent_checkpoints SET state='discarded',payload='{}'::jsonb,discard_reason='expired',updated_at=now() "
                "WHERE workspace_id=%s AND state IN ('available','claimed') AND expires_at <= now() RETURNING 1", (workspace_id,))
    return {"released": released, "discarded": len(cur.fetchall())}
