"""The seam between legacy TaskPlan v1 (`task_state.py`) and the engine (CF-3 §1, §4.5, §4.6, §21.2).

Only active when the engine is on for the workspace (`flags.enabled_for`); otherwise every function returns without reading
or writing anything, so legacy behaviour is byte-for-byte today's. When on:
- a legacy task gets its engine row in the same transaction (`on_create`), anchored on the same `task:` run (same taskId);
- every legacy save mirrors the Manager's own steps (`model` steps) into pr_agent_steps and re-projects the engine's own steps
  back into `artifact.task` (`on_save`), so old readers stay correct and the Manager never changes an engine step;
- a running legacy task with no engine row is adopted per actor (`adopt`), the newest per person per conversation.
"""
from __future__ import annotations

import logging

from . import flags, model, store

log = logging.getLogger("postriff.agent_tasks")


def enabled(workspace_id) -> bool:
    return flags.store_for(workspace_id)


def _specs(plan) -> list[dict]:
    specs = []
    for step in plan.steps:
        if step.id in getattr(plan, "engine_steps", set()):
            continue
        state, reason_code = model.from_legacy(step.state, has_approvals=bool(step.approvals))
        specs.append({"key": step.id, "label": step.label, "kind": "model", "state": state, "reasonCode": reason_code, "reason": step.reason,
                      "verified": bool(step.verified) or state == "completed", "dependsOn": list(step.depends_on), "outputs": list(step.outputs)[:20],
                      "entities": list(step.entities)[:20]})
    return specs


def on_create(cur, ideas, workspace_id: str, conversation_id: str, principal: str, task_id: str, task_key: str, title: str, trace_id: str) -> None:
    if not enabled(workspace_id):
        return
    try:
        _create(cur, ideas, workspace_id, conversation_id, principal, task_id, task_key, title, trace_id, origin="chat")
    except Exception as error:  # noqa: BLE001 — conflicts are resolved below; anything else must not break the legacy turn
        if getattr(error, "code", None) == "task_conflict" and flags.enabled_for(workspace_id):
            _supersede_open(cur, ideas, workspace_id, conversation_id, principal, exclude=task_id)
            _create(cur, ideas, workspace_id, conversation_id, principal, task_id, task_key, title, trace_id, origin="chat")
        else:
            raise


def _create(cur, ideas, workspace_id, conversation_id, principal, task_id, task_key, title, trace_id, *, origin, steps=()):
    store.create_task(cur, ideas, workspace_id=workspace_id, conversation_id=conversation_id, created_by=principal, origin=origin, title=title,
                      request_key=task_key, payload={"anchor": task_id}, steps=list(steps), trace_id=trace_id if _trace(trace_id) else _new_trace(),
                      anchor_id=task_id)


def _trace(value) -> bool:
    return isinstance(value, str) and value.startswith("trace_") and len(value) == 38


def _new_trace() -> str:
    import uuid
    return "trace_" + uuid.uuid4().hex


def _supersede_open(cur, ideas, workspace_id, conversation_id, principal, *, exclude) -> None:
    """A new plan supersedes the person's stale open chat task (no pending approval; nothing left but conversation steps)."""
    if not flags.enabled_for(workspace_id):
        return
    cur.execute("SELECT id::text FROM public.pr_agent_tasks WHERE workspace_id=%s AND conversation_id::text=%s AND created_by=%s AND id::text<>%s "
                "AND origin IN ('chat','voice','adopted') AND parent_task_id IS NULL AND state IN ('queued','running','awaiting_approval','blocked')",
                (workspace_id, conversation_id, principal, exclude))
    for (old_id,) in cur.fetchall():
        close(cur, ideas, workspace_id, old_id, "task_superseded")


def close(cur, ideas, workspace_id: str, task_id: str, reason_code: str) -> None:
    """Close every open step of a task (cancelled/<reason>), supersede its approvals, discard its paused run."""
    from . import checkpoints
    task = store.lock_task(cur, ideas, workspace_id, task_id)
    if task is None:
        return
    for step in store.load_steps(cur, workspace_id, task_id, lock=True):
        if step["state"] in ("queued", "awaiting_approval", "blocked") and not step["observesExternal"]:
            store.set_step(cur, step, state="cancelled", reason_code=reason_code, reason="A newer plan replaced this one.")
    store.close_pending_approvals(cur, workspace_id, task_id, "superseded")
    checkpoints.discard_live(cur, workspace_id, task_id, reason_code)
    store.refresh(cur, ideas, task)


def on_save(cur, ideas, workspace_id: str, plan) -> None:
    """After task_state.save wrote the legacy artifact (same transaction): mirror the Manager's steps, re-project the engine's."""
    if not enabled(workspace_id) or not plan.task_id:
        return
    task = store.lock_task(cur, ideas, workspace_id, plan.task_id)
    if task is None:
        task = adopt(cur, ideas, workspace_id, plan.task_id)
        if task is None:
            return
    steps = {s["stepKey"]: s for s in store.load_steps(cur, workspace_id, plan.task_id, lock=True)}
    new_specs = []
    for spec in _specs(plan):
        existing = steps.get(spec["key"])
        if existing is None:
            new_specs.append(spec)
            continue
        if existing["kind"] != "model" or existing["state"] in model.TERMINAL_STATES:
            continue                       # engine steps follow the engine; a terminal step is never reopened
        changes = {k: v for k, v in (("state", spec["state"]), ("reason_code", spec["reasonCode"]), ("reason", spec["reason"]),
                                     ("verified", spec["verified"]), ("outputs", spec["outputs"]), ("entities", spec["entities"])) if v != existing[_camel(k)]}
        if changes:
            store.set_step(cur, existing, **changes)
    if new_specs:
        store.add_steps(cur, task, new_specs)
    _wrap_proposals(cur, ideas, task, plan)
    store.refresh(cur, ideas, task)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


def _wrap_proposals(cur, ideas, task, plan) -> None:
    """Proposals a Manager step waits on get their approval row once the proposal is stored on an answer (lazy X1)."""
    from .. import approvals as legacy
    from .approvals import ensure_proposal_approval
    for step in plan.steps:
        if not step.approvals or step.state != "needs_user":
            continue
        engine_step = store.load_step(cur, task["workspaceId"], task["taskId"], step.id)
        if engine_step is None:
            continue
        for proposal_id in step.approvals:
            if store.approval_by_proposal(cur, task["workspaceId"], proposal_id) is not None:
                continue
            item = legacy.find(cur, task["workspaceId"], task["conversationId"], proposal_id)
            if item is not None:
                ensure_proposal_approval(cur, ideas, task, engine_step, item)


def adopt(cur, ideas, workspace_id: str, run_id: str):
    """A running legacy `task:` row with no engine row: insert its task (origin 'adopted', created_by = the run's actor) and its
    steps, move a paused run into a checkpoint. The newest per actor per conversation is adopted; older ones of the same actor
    close failed/task_superseded (tasks of different actors are adopted separately)."""
    from .. import task_state
    from . import checkpoints
    cur.execute("SELECT conversation_id::text,actor::text,idempotency_key,status,artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s "
                "AND idempotency_key LIKE 'task:%%' FOR UPDATE", (run_id, workspace_id))
    row = cur.fetchone()
    if not row or row[3] != "running":
        return None
    conversation_id, actor, key, _status, artifact = row
    cur.execute("SELECT r.id::text FROM public.pr_agent_runs r WHERE r.workspace_id=%s AND r.conversation_id::text=%s AND r.actor=%s AND r.status='running' "
                "AND r.idempotency_key LIKE 'task:%%' AND r.id::text<>%s AND r.created_at > (SELECT created_at FROM public.pr_agent_runs WHERE id::text=%s)",
                (workspace_id, conversation_id, actor, run_id, run_id))
    if cur.fetchone():
        # A newer running legacy task of the same person exists in this conversation: this one is superseded, not adopted.
        if flags.enabled_for(workspace_id):
            cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (run_id,))
        return None
    plan = task_state.TaskPlan.from_artifact(run_id, artifact or {}, "running")
    _supersede_open(cur, ideas, workspace_id, conversation_id, actor, exclude=run_id)
    traces = (artifact or {}).get("task", {}).get("traceIds") or []
    store.create_task(cur, ideas, workspace_id=workspace_id, conversation_id=conversation_id, created_by=actor, origin="adopted", title=plan.title,
                      request_key=key, payload={"anchor": run_id}, steps=_specs(plan), trace_id=traces[0] if traces and _trace(traces[0]) else _new_trace(),
                      anchor_id=run_id)
    task = store.lock_task(cur, ideas, workspace_id, run_id)
    _wrap_proposals(cur, ideas, task, plan)
    pending = (artifact or {}).get("pendingRun") or {}
    if isinstance(pending, dict) and pending.get("state"):
        checkpoints.store_run(cur, ideas, task, pending["state"], list(pending.get("proposalIds") or []), writer_model=pending.get("writerModel"),
                              stored_at=float(pending.get("storedAt") or 0))
        if flags.enabled_for(workspace_id):
            cur.execute("UPDATE public.pr_agent_runs SET artifact=artifact - 'pendingRun' WHERE id::text=%s", (run_id,))
    store.log_event("adopted", taskId=run_id, steps=len(plan.steps))
    return store.lock_task(cur, ideas, workspace_id, run_id)


def adopt_some(service, *, limit: int = 50) -> int:
    """Recovery phase 3: adopt running legacy tasks of allowlisted workspaces (≤ limit per tick)."""
    adopted = 0
    with service.repository.connection_factory() as db, db.cursor() as scan:
        scan.execute("SELECT r.id::text,r.workspace_id::text FROM public.pr_agent_runs r WHERE r.status='running' AND r.idempotency_key LIKE 'task:%%' "
                     "AND NOT EXISTS (SELECT 1 FROM public.pr_agent_tasks t WHERE t.id=r.id) ORDER BY r.created_at DESC LIMIT %s", (int(limit) * 4,))
        candidates = scan.fetchall()
    for run_id, workspace_id in candidates:
        if adopted >= limit:
            break
        if not flags.enabled_for(workspace_id):
            continue
        try:
            with store.service_tx(service, workspace_id, skip_locked=True) as cur:
                if cur is None:
                    continue
                if adopt(cur, service.ideas, workspace_id, run_id) is not None:
                    adopted += 1
        except Exception as error:  # noqa: BLE001 — one bad row never stops the tick
            log.warning('{"event": "agent_task.adopt_failed", "errorClass": "%s"}', type(error).__name__)
    return adopted


def dispatch_bound(ctx, tool, args):
    """Route a planned tool call through its creator-bound claim; None means legacy execution."""
    from postriff_alpha.domain import AlphaError
    from . import executor, errors
    from .. import task_state
    if not args.get("stepId") or getattr(ctx, "step_binding", None) or not flags.enabled_for(ctx.workspace_id, ctx.config):
        return None
    if ctx.task is None or ctx.task.created_by != ctx.principal:
        raise errors.error("task_forbidden")
    clean = {k: v for k, v in args.items() if k != "stepId"}
    with ctx.workspace() as (cur, _row, principal, _member, _state):
        task = store.lock_task(cur, ctx.service.ideas, ctx.workspace_id, ctx.task.task_id)
        if task is None or task["createdBy"] != principal:
            raise errors.error("task_forbidden")
        step = store.load_step(cur, ctx.workspace_id, task["taskId"], args["stepId"])
        if step is None:
            raise errors.error("step_unavailable")
        if step["kind"] == "model":
            return None
        if step["kind"] != "tool" or step["capabilityId"] != tool.name or step["inputDigest"] != model.input_digest(tool.name, clean):
            raise AlphaError("This call does not match the planned step.", 409, code="task_conflict")
        claim = executor.claim_next(cur, ctx.service.ideas, workspace_id=ctx.workspace_id, executor="inline", principal=principal,
                                    task_id=task["taskId"], step_key=step["stepKey"], seconds_left=ctx.remaining() or 240,
                                    owner=executor.lease_owner("inline"), actor_kind="agent", request_text=ctx.request_text,
                                    run_id=ctx.run_id, config=ctx.config)
        if claim is None or claim == "handled":
            current = store.load_step(cur, ctx.workspace_id, task["taskId"], step["stepKey"])
            return {"ok": current["state"] == "completed", "verified": current["verified"], "needsUser": current["state"] != "completed",
                    "code": current["reasonCode"] or "step_waiting", "taskId": task["taskId"], "stepId": step["stepKey"], "state": current["state"]}
    from types import SimpleNamespace
    runtime = SimpleNamespace(service=ctx.service, cfg=ctx.config, clock=ctx.now, image_studio=ctx.image_studio, vision=ctx.vision)
    result = executor.execute(runtime, claim, token=ctx.token, seconds_left=ctx.remaining() or 240, return_result=True)
    with ctx.workspace() as (cur, _row, _principal, _member, _state):
        ctx.task = task_state.load(cur, ctx.workspace_id, task["taskId"])
    return result
