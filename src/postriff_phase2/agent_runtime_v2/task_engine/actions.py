"""A person's actions on a task: cancel, retry, undo, continue (CF-3 §12, §9.3, §13, §7.4, §17).

Authority (DP-10): cancel = the task's creator or an owner-class member; retry, continue and undo = the creator only. Each
action is idempotent per (person, key): the same person with the same key and body gets the stored response; the key reused
by anyone else, or with another body, is 409 `idempotency_conflict` and reveals nothing about the other use. Errors are only
the frozen CF-2 §13.1 codes.
"""
from __future__ import annotations

import time

from postriff_alpha.domain import AlphaError

from . import authz_seam, checkpoints, compensation, errors, executor, model, store, views


def _key(payload) -> str:
    key = payload.get("idempotencyKey") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not (16 <= len(key) <= 120):
        raise AlphaError("Send an idempotency key of 16 to 120 characters.", 400)
    return key


def _task_or_404(cur, ideas, workspace_id, task_id):
    task = store.lock_task(cur, ideas, workspace_id, task_id)
    if task is None:
        raise errors.error("task_unavailable")
    return task


# --- cancel (EX-26) ---------------------------------------------------------------------------------------------------------
def cancel(runtime, workspace_id: str, token: str, task_id: str, payload: dict) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    key = _key(payload)
    reason = model.clip(payload.get("reason"), 200)
    expected = payload.get("expectedVersion")
    body_digest = model.sha256({"expectedVersion": expected, "reason": reason, "taskId": task_id})
    ideas = runtime.service.ideas
    live_runs: list[str] = []
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        member = ideas._member(row)
        task = _task_or_404(cur, ideas, workspace_id, task_id)
        if not (task["createdBy"] == principal or member.allows("owner")):
            raise errors.error("task_forbidden")
        stored = store.remembered(cur, workspace_id, principal, "agent.task.cancel", key, body_digest)
        if stored is not None:
            return stored
        if expected is not None and (not isinstance(expected, int) or expected != int(task["version"])) and task["state"] != "cancelled":
            raise errors.error("task_conflict")
        if task["state"] in ("completed", "failed"):
            raise errors.error("task_terminal")
        cancelled_steps, superseded = [], []
        if task["state"] != "cancelled":
            task, cancelled_steps, superseded, live_runs = cancel_in_tx(cur, ideas, workspace_id, task_id, principal, reason)
        cur.execute("SELECT s.step_key FROM public.pr_agent_steps s WHERE s.task_id::text=%s AND (s.state='running' OR (s.observes_external AND s.state IN ('queued','awaiting_approval','blocked')))", (task_id,))
        still = [r[0] for r in cur.fetchall()]
        response = {"taskId": task_id, "state": task["state"], "version": int(task["version"]), "cancelledSteps": cancelled_steps, "stillRunning": still,
                    "supersededApprovals": superseded,
                    "note": "Rafii will stop after the current step; that step may still finish." if still else "Cancelled. Anything already finished stays as it is."}
        store.remember(cur, workspace_id, principal, "agent.task.cancel", key, body_digest, task_id, response, task["rootTraceId"])
    if live_runs and task["createdBy"] == principal:
        # The creator's own in-flight turns that run these steps stop before their next change (never another member's turns).
        try:
            runtime.cancel_running(workspace_id, token, task["conversationId"], reason="You cancelled this task.", only=set(live_runs))
        except AlphaError:
            pass
    return response


def cancel_in_tx(cur, ideas, workspace_id: str, task_id: str, principal: str, reason: str | None):
    """The cancellation itself, in the caller's transaction (the caller checked the authority): cancel_requested, every queued,
    waiting or blocked step cancelled/cancelled_by_person (external-effect observers keep observing), pending approvals
    superseded, the paused run discarded. A running step stops before its next non-READ effect. → (task, steps, approvals, runs)"""
    task = store.lock_task(cur, ideas, workspace_id, task_id)
    if task is None or task["state"] not in model.OPEN_STATES:
        return task, [], [], []
    cur.execute("UPDATE public.pr_agent_tasks SET cancel_requested_at=coalesce(cancel_requested_at,now()),cancel_requested_by=coalesce(cancel_requested_by,%s),"
                "updated_at=now() WHERE id::text=%s", (principal, task_id))
    task = store.lock_task(cur, ideas, workspace_id, task_id)
    cancelled_steps = []
    for step in store.load_steps(cur, workspace_id, task_id, lock=True):
        if step["state"] in ("queued", "awaiting_approval", "blocked") and not step["observesExternal"]:
            store.set_step(cur, step, state="cancelled", reason_code="cancelled_by_person", reason=reason or "You cancelled this task.")
            cancelled_steps.append(step["stepKey"])
        elif step["observesExternal"] and step["state"] in ("queued", "awaiting_approval", "blocked"):
            store.set_step(cur, step, state="queued", next_attempt_at=time.time(), reason_code=None)
    superseded = store.close_pending_approvals(cur, workspace_id, task_id, "superseded")
    checkpoints.discard_live(cur, workspace_id, task_id, "task_cancelled")
    cur.execute("SELECT DISTINCT a.run_id::text FROM public.pr_agent_step_attempts a WHERE a.task_id::text=%s AND a.state='running' AND a.run_id IS NOT NULL",
                (task_id,))
    live_runs = [r[0] for r in cur.fetchall()]
    task = store.refresh(cur, ideas, task)
    store.emit(cur, ideas, task, "task_state", state=task["state"], cancelled=len(cancelled_steps))
    store.log_event("cancelled", taskId=task_id, steps=len(cancelled_steps), byOwner=task["createdBy"] != principal)
    return task, cancelled_steps, superseded, live_runs


# --- retry (§9.3) -----------------------------------------------------------------------------------------------------------
def retry(runtime, workspace_id: str, token: str, task_id: str, step_key: str, payload: dict, *, request_id: str | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    key = _key(payload)
    expected = payload.get("expectedGeneration")
    body_digest = model.sha256({"taskId": task_id, "stepKey": step_key, "expectedGeneration": expected})
    ideas = runtime.service.ideas
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        task = _task_or_404(cur, ideas, workspace_id, task_id)
        if task["createdBy"] != principal:
            raise errors.error("task_forbidden")
        stored = store.remembered(cur, workspace_id, principal, "agent.task.retry", key, body_digest)
        if stored is not None:
            return stored
        step = store.load_step(cur, workspace_id, task_id, step_key, lock=True)
        if step is None:
            raise errors.error("step_unknown")
        if task["state"] not in model.OPEN_STATES:
            raise errors.error("step_not_retryable")
        if step["state"] not in ("failed", "blocked") or step["kind"] not in ("tool", "delegate", "wait") or step["retryClass"] == "never":
            raise errors.error("step_not_retryable")
        if not isinstance(expected, int) or expected != int(step["generation"]):
            raise errors.error("task_conflict")
        if int(step["generation"]) >= model.MAX_GENERATION or int(task["attemptsLeft"]) <= 0:
            raise errors.error("retry_budget_exhausted")
        verdict = authz_seam.decide_for_step(cur, task, {**step, "generation": int(step["generation"]) + 1},
                                             actor=authz_seam.Actor("retry", principal, ""), now=time.time(),
                                             allowed_before=store.allowed_before(cur, workspace_id, task_id))
        if verdict.verdict == "deny":
            raise errors.error("agent_permission_revoked" if verdict.reason_code == "permission_revoked" else "agent_permission_denied")
        generation = int(step["generation"]) + 1
        store.set_step(cur, step, state="queued", generation=generation, attempts=0, reason=None, reason_code=None, verified=False, next_attempt_at=time.time(),
                       effect_key=model.effect_key(task_id, step_key, generation) if step["effectKey"] else None)
        task = store.refresh(cur, ideas, task)
        store.emit(cur, ideas, task, "step_attempt", stepKey=step_key, generation=generation, state="queued")
        runs_inline = step["kind"] == "tool"
    executed = executor.drive_inline(runtime, workspace_id, token, principal, task_id, actor_kind="retry", request_id=request_id) if runs_inline else []
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, _principal):
        after = store.load_step(cur, workspace_id, task_id, step_key)
        approval = next((a for a in store.approvals_for(cur, workspace_id, task_id, state="pending") if a["stepId"] == after["stepId"]), None)
        response = {"taskId": task_id, "stepKey": step_key, "generation": generation, "state": after["state"], "approvalId": approval["approvalId"] if approval else None,
                    "nextAttemptAt": views.iso(after["nextAttemptAt"]), "runsInline": runs_inline, "executed": executed}
        store.remember(cur, workspace_id, principal, "agent.task.retry", key, body_digest, f"{task_id}:{step_key}", response)
    return response


# --- undo (EX-27) -----------------------------------------------------------------------------------------------------------
def undo(runtime, workspace_id: str, token: str, task_id: str, step_key: str, payload: dict) -> dict:
    from .. import domain_tools, tool_adapter
    payload = payload if isinstance(payload, dict) else {}
    key = _key(payload)
    compensation_id = payload.get("compensationId")
    body_digest = model.sha256({"taskId": task_id, "stepKey": step_key, "compensationId": compensation_id})
    ideas = runtime.service.ideas
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        member = ideas._member(row)
        task = _task_or_404(cur, ideas, workspace_id, task_id)
        if task["createdBy"] != principal:
            raise errors.error("task_forbidden")
        stored = store.remembered(cur, workspace_id, principal, "agent.task.undo", key, body_digest)
        if stored is not None:
            return stored
        step = store.load_step(cur, workspace_id, task_id, step_key)
        record = store.compensation(cur, workspace_id, compensation_id, lock=True) if isinstance(compensation_id, str) else None
        if step is None or record is None or record["stepId"] != step["stepId"]:
            raise errors.error("undo_unavailable")
        if record["state"] == "expired" or record["pastWindow"]:
            raise errors.error("undo_expired")
        if record["state"] != "available":
            raise errors.error("undo_unavailable" if record["state"] == "applied" else "undo_conflict")
        if compensation.current_digest(cur, workspace_id, record, step["capabilityId"]) != record["postImageDigest"]:
            raise errors.error("undo_conflict")
        domain_tools.ensure_registered()
        tool = tool_adapter.REGISTRY.get(record["inverseCapabilityId"])
        if tool is None or not member.allows(tool.spec.permission):
            raise errors.error("agent_permission_revoked")
        undo_key = ("undo:" + record["effectKey"])[:120]
        inverse_inputs = dict(record["inverseInputs"] or {})
        source = ideas._state(row)
        import copy
        state = copy.deepcopy(source)
        if step["capabilityId"] == "draft_edit":
            draft = next((v for v in state.get("variants", []) if v.get("id") == inverse_inputs.get("draftId")), None)
            old = next((r for r in (draft or {}).get("revisions", []) if r.get("revision") == inverse_inputs.get("restoreRevision")), None)
            if not draft or not old or not old.get("text"):
                raise errors.error("undo_unavailable")
            inverse_inputs = {"draftId": draft["id"], "revision": draft["revision"], "text": old["text"]}
            committed = [j for j in (state.get("phase2") or {}).get("jobs", [])
                         if (j.get("manifest") or {}).get("variantId") == draft["id"] and j.get("state") not in ("canceled", "failed")]
            if committed:
                raise errors.error("undo_conflict")
            action = "variant_edit"
            domain_payload = {"variantId": draft["id"], "variantRevision": draft["revision"], "text": old["text"]}
        elif record["inverseCapabilityId"] in ("campaign_link", "campaign_unlink"):
            action = "raffi_" + record["inverseCapabilityId"]
            domain_payload = inverse_inputs
        else:
            raise errors.error("undo_unavailable")
        verdict = authz_seam.decide_for_step(cur, task, {**step, "kind": "tool", "capabilityId": record["inverseCapabilityId"], "inputs": inverse_inputs},
                                           actor=authz_seam.Actor("human_ui", principal), now=time.time(), config=getattr(runtime, "cfg", None))
        if verdict.verdict != "allow":
            raise errors.error("agent_permission_revoked")
        inverse_digest = model.input_digest(record["inverseCapabilityId"], inverse_inputs)
        existing = store.receipt(cur, workspace_id, undo_key, lock=True)
        if existing is not None:
            raise errors.error("undo_unavailable")
        cur.execute("INSERT INTO public.pr_agent_receipts(workspace_id,effect_key,task_id,step_id,principal,capability_id,input_digest,trace_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (workspace_id, undo_key, task_id, step["stepId"], principal,
                                                       record["inverseCapabilityId"], inverse_digest, executor.new_trace()))
        state = runtime.service.commands(state, principal, action, domain_payload)
        import json
        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
        for effect in runtime.service.repository.effects:
            effect(cur, workspace_id, source, state, principal)
        from ...hosted import audit
        audit(cur, workspace_id, principal, "agent.task.undo", step_key, {"taskId": task_id, "compensationId": record["compensationId"]})
        refs = [{"type": record["targetType"], "id": record["targetId"], "change": "restored"}]
        store.receipt_done(cur, workspace_id, undo_key, outcome="applied", verified=True,
                           result={"checks": [{"name": "guarded_domain_inverse", "ok": True}], "changedRefs": refs})
        cur.execute("UPDATE public.pr_agent_compensations SET state='applied',applied_effect_key=%s,applied_by=%s,applied_at=now(),updated_at=now() "
                    "WHERE id::text=%s AND state='available'", (undo_key, principal, record["compensationId"]))
        store.emit(cur, ideas, task, "compensation", stepKey=step_key, compensationId=record["compensationId"], state="applied")
        response = {"outcome": "applied", "verified": True,
                    "receipt": {"effectKey": undo_key, "outcome": "applied", "verified": True, "checks": [{"name": "guarded_domain_inverse", "ok": True}]},
                    "compensation": {"state": "applied"}}
        store.remember(cur, workspace_id, principal, "agent.task.undo", key, body_digest, f"{task_id}:{step_key}", response)
        return response


# --- continue (§7.4) --------------------------------------------------------------------------------------------------------
def continue_task(runtime, workspace_id: str, token: str, task_id: str, payload: dict, *, request_id: str | None = None) -> dict:
    """The creator's Continue: queued engine steps run inline; a paused Manager run resumes from its checkpoint (a metered turn,
    reserved like any other); otherwise a turn bound to the task continues the conversation."""
    payload = payload if isinstance(payload, dict) else {}
    key = _key(payload)
    body_digest = model.sha256({"taskId": task_id, "modality": payload.get("modality") or "text"})
    ideas = runtime.service.ideas
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        task = _task_or_404(cur, ideas, workspace_id, task_id)
        if task["createdBy"] != principal:
            raise errors.error("task_forbidden")
        stored = store.remembered(cur, workspace_id, principal, "agent.task.continue", key, body_digest)
        if stored is not None:
            return stored
        if task["state"] in ("completed", "failed", "cancelled"):
            raise errors.error("task_terminal")
        has_checkpoint = checkpoints.available(cur, workspace_id, task_id)
        steps = store.load_steps(cur, workspace_id, task_id)
    executed = executor.drive_inline(runtime, workspace_id, token, principal, task_id, actor_kind="continuation", request_id=request_id)
    response: dict
    if has_checkpoint is not None:
        response = _resume(runtime, workspace_id, token, task, has_checkpoint, key)
    elif not executed and any(s["kind"] == "model" and s["state"] in ("blocked", "queued") for s in steps):
        turn = runtime.turn(workspace_id, token, {"conversationId": task["conversationId"], "message": "Continue", "idempotencyKey": "continue:" + key[:90],
                                                  "modality": "text"})
        response = {**turn, "taskId": task_id, "resumed": "inline", "executed": executed}
    else:
        with runtime.service.repository.transaction(token, workspace_id) as (cur, row, _p):
            current = store.load_task(cur, workspace_id, task_id)
            response = {"taskId": task_id, "resumed": "inline" if executed else "none", "executed": executed,
                        "task": views.summary(current, store.load_steps(cur, workspace_id, task_id), store.approvals_for(cur, workspace_id, task_id), principal,
                                              ideas._member(row))}
    with runtime.service.repository.transaction(token, workspace_id) as (cur, _row, _p):
        store.remember(cur, workspace_id, principal, "agent.task.continue", key, body_digest, task_id,
                       {k: v for k, v in response.items() if k in ("taskId", "resumed", "executed", "runId", "conversationId", "messageId", "status")})
    return response


def _resume(runtime, workspace_id, token, task, checkpoint, key) -> dict:
    from .. import approvals as legacy, contracts
    from ...site_agent import contracts as site_contracts
    conversation_id = task["conversationId"]
    with runtime.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
        applied = [p for p in checkpoint["proposalIds"]
                   if ((legacy.find(cur, workspace_id, conversation_id, p) or {}).get("proposal") or {}).get("status") == "applied"]
    trace_id = contracts.new_trace_id()
    run_id, _ = runtime._open_run(workspace_id, token, conversation_id, "Continue", "text", "agent:continue:" + key[:80], trace_id, [], model="rafii-approvals")
    with runtime.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
        claimed = checkpoints.claim(cur, workspace_id, task["taskId"], principal, "req:" + run_id)
    resumed = None
    if claimed is not None and applied:
        checkpoint_id, payload = claimed
        approved = [{"type": "proposal", "id": p, "change": "applied", "verified": True, "checks": []} for p in applied]
        resumed = runtime._resume_pending_run(workspace_id, token, conversation_id, applied[0], (task["taskId"], payload), run_id=run_id, trace_id=trace_id,
                                              modality="text", zone=None, approved=approved)
        checkpoints.finish(runtime.service, runtime.service.ideas, workspace_id, task["taskId"], checkpoint_id, ok=resumed is not None)
    elif claimed is not None:
        checkpoints.finish(runtime.service, runtime.service.ideas, workspace_id, task["taskId"], claimed[0], ok=False)
    if resumed is not None:
        return {**resumed, "taskId": task["taskId"], "resumed": "inline"}
    result = contracts.empty_result(trace_id, "text")
    answer = "Your approval was applied and checked. There was nothing more Rafii could continue from where it stopped."
    result.update({"answerText": answer, "speakableSummary": answer, "composedBy": "deterministic"})
    out = runtime._finish_simple(workspace_id, token, conversation_id, run_id, trace_id, result, [site_contracts.text(answer)])
    return {**out, "taskId": task["taskId"], "resumed": "none"}
