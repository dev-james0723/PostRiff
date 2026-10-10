"""The two executors and recovery (CF-3 §5, §6, §9; EX-11..EX-14).

    inline  a request by the task's creator (approval decide, retry, continue): any kind except `wait`... and `model`/
            `continuation`, inside the request's budget; a step starts only if its timeout + 30 s still fits.
    cron    /api/cron/agent-tasks (unscheduled until DP-12; RAFII_AGENT_TASKS_BACKGROUND): background-allowed steps only
            (R0 workspace reads, delegate polls, waits), as the creator through `principal_repository`.

Every claim runs `decide_for_step` (whatever any epoch says) and records the verdict on the attempt. A tool step runs through
the existing `tool_adapter.execute` (no second tool path) with a context bound to the step; its effect key and receipt make
a re-run replay instead of repeating; its lease (timeout + 30 s) is what recovery reaps. Clients never drive execution:
polling only reads, and a client that disconnects cancels nothing.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from postriff_alpha.domain import AlphaError

from ... import leases
from . import authz_seam, delegates, flags, model, store, targets

INLINE_KINDS = ["tool", "approval", "delegate"]
CRON_KINDS = ["tool", "delegate", "wait"]
DEFAULT_REQUEST_SECONDS = 240          # service.TURN_BUDGET_SECONDS
RECOVERY_BUDGET_SECONDS = 10
_CODE_CATEGORY = {
    "run_cancelled": "cancelled", "tool_forbidden": "permission", "forbidden": "permission", "agent_permission_denied": "permission",
    "agent_permission_revoked": "revoked", "tool_input": "permanent", "not_found": "permanent", "workspace_revision_conflict": "conflict",
    "conflict": "conflict", "timeout": "timeout", "price_unknown": "budget", "budget": "budget", "insufficient_credits": "budget",
    "credit_limit": "budget", "voice_not_allowed": "unsupported", "tool_tenant": "unsupported", "tool_out_of_scope": "unsupported",
    "youtube_analytics_read_only": "unsupported", "asset_link_unsupported": "unsupported", "rate_limited": "retryable", "provider_unavailable": "retryable",
}

CLAIM_SQL = """
UPDATE public.pr_agent_steps s SET state='running', attempts=s.attempts+1,
       started_at=coalesce(s.started_at, now()), updated_at=now()
WHERE s.id = (
  SELECT d.id FROM public.pr_agent_steps d JOIN public.pr_agent_tasks t ON t.id = d.task_id AND t.workspace_id = d.workspace_id
  WHERE d.workspace_id = %(workspace_id)s AND d.state='queued' AND d.next_attempt_at <= now()
    AND %(engine_on)s
    AND d.kind = ANY(%(kinds)s)
    AND (%(executor)s = 'inline' OR d.background_allowed)
    AND (%(executor)s = 'cron' OR t.created_by = %(principal)s::uuid)
    AND (%(task_id)s::uuid IS NULL OR d.task_id = %(task_id)s::uuid)
    AND (%(step_key)s::text IS NULL OR d.step_key = %(step_key)s::text)
    AND t.state IN ('queued','running','awaiting_approval','blocked') AND (t.cancel_requested_at IS NULL OR (%(executor)s = 'cron' AND d.observes_external))
    AND t.hard_expires_at > now()
    AND (t.attempts_left > 0 OR d.kind = 'delegate')
    AND (d.kind = 'delegate' OR d.attempts < 20)
    AND d.timeout_seconds + 30 <= %(seconds_left)s
    AND NOT EXISTS (SELECT 1 FROM public.pr_agent_steps x WHERE x.task_id=d.task_id AND x.step_key = ANY(d.depends_on) AND x.state <> 'completed')
    AND EXISTS (SELECT 1 FROM public.pr_workspaces w WHERE w.id=d.workspace_id AND NOT (coalesce(w.state,'{}'::jsonb) ? 'accountBlock')
                AND NOT (coalesce(w.state,'{}'::jsonb) ? 'accountDeletion'))
    AND (%(executor)s = 'inline' OR (SELECT count(*) FROM public.pr_agent_step_attempts a WHERE a.workspace_id=d.workspace_id AND a.state='running'
                                      AND a.executor='cron') < 2)
  ORDER BY d.next_attempt_at, d.created_at LIMIT 1 FOR UPDATE OF d SKIP LOCKED)
RETURNING s.id::text, s.task_id::text
"""


@dataclass
class Claim:
    task: dict
    step: dict
    attempt_id: str
    attempt_no: int
    lease_owner: str
    executor: str
    trace_id: str
    verdict: authz_seam.StepVerdict
    request_text: str = ""
    actor: authz_seam.Actor | None = None
    approval_evidence: dict | None = None


def new_trace() -> str:
    return "trace_" + uuid.uuid4().hex


def lease_owner(executor: str, request_id: str | None = None) -> str:
    if executor == "inline":
        return "req:" + (str(request_id or "")[:60] or uuid.uuid4().hex)
    return "cron:" + uuid.uuid4().hex


# --- claim (one short transaction; the workspace row is already locked by the caller) ------------------------------------
def claim_next(cur, ideas, *, workspace_id: str, executor: str, principal: str | None, task_id: str | None, seconds_left: float, owner: str,
               request_id: str | None = None, actor_kind: str = "agent", request_text: str = "", run_id: str | None = None, config=None, step_key=None):
    """Claim the next ready step and decide it. Returns None (nothing claimable), "handled" (resolved inside this transaction:
    approval requested, denied, a wait/delegate/approval step, or a replayed receipt), or a Claim to execute outside it."""
    params = {"workspace_id": workspace_id, "executor": executor, "principal": principal, "task_id": task_id,
              "kinds": INLINE_KINDS if executor == "inline" else CRON_KINDS, "seconds_left": int(max(0, seconds_left)),
              "engine_on": flags.enabled_for(workspace_id, config), "step_key": step_key}
    cur.execute(CLAIM_SQL, params)
    row = cur.fetchone()
    if not row:
        return None
    step_id, claimed_task = row
    task = store.lock_task(cur, ideas, workspace_id, claimed_task)
    step = next(s for s in store.load_steps(cur, workspace_id, claimed_task) if s["stepId"] == step_id)
    actor = authz_seam.Actor(actor_kind if executor == "inline" else "cron", task["createdBy"], request_text if executor == "inline" else "")
    evidence = _approval_evidence(cur, task, step)
    if evidence is not None and step["kind"] == "tool":
        actor = authz_seam.Actor("approval", task["createdBy"], "", {"approvalId": evidence["approvalId"], "digest": evidence["digest"]})
    verdict = authz_seam.decide_for_step(cur, task, step, actor=actor, now=time.time(),
                                         allowed_before=store.allowed_before(cur, workspace_id, claimed_task), config=config)
    if verdict.token != task["authzToken"]:
        cur.execute("UPDATE public.pr_agent_tasks SET authz_token=%s,updated_at=now() WHERE id::text=%s", (verdict.token, claimed_task))
        task["authzToken"] = verdict.token
    trace_id = new_trace()
    attempt_no = _next_attempt_no(cur, step)
    if step["kind"] != "delegate":
        cur.execute("UPDATE public.pr_agent_tasks SET attempts_left=greatest(attempts_left-1,0) WHERE id::text=%s", (claimed_task,))
        task["attemptsLeft"] = max(0, int(task["attemptsLeft"]) - 1)
    attempt_id = _insert_attempt(cur, task, step, attempt_no, executor, owner, verdict, trace_id, request_id, run_id)
    store.emit(cur, ideas, task, "step_attempt", stepKey=step["stepKey"], attempt=attempt_no, executor=executor, verdict=verdict.verdict)
    store.log_event("step_claimed", taskId=claimed_task, stepKey=step["stepKey"], attempt=attempt_no, executor=executor, verdict=verdict.verdict,
                    traceId=trace_id, requestId=request_id)
    if step["kind"] != "tool":
        if verdict.verdict == "observe" and not (executor == "cron" and step["kind"] == "delegate" and step["observesExternal"]):
            raise ValueError("observe is restricted to external cron delegates")
        read_failed = _handle_inline_kind(cur, ideas, task, step, verdict, evidence, trace_id)
        failed = read_failed or step["state"] in ("failed", "blocked")
        _finish_attempt(cur, attempt_id, "failed" if failed else "succeeded", "permission" if verdict.verdict == "deny" else "retryable" if read_failed else None, step.get("reasonCode"))
        return "handled"
    if verdict.verdict == "observe":
        raise ValueError("a tool cannot run as an observer")
    if verdict.verdict in ("approve", "step_up"):
        _finish_attempt(cur, attempt_id, "succeeded", None, None)
        store.set_step(cur, step, attempts=max(0, int(step["attempts"]) - 1))
        from .approvals import request_approval
        request_approval(cur, ideas, task, step, verdict, trace_id=trace_id)
        store.refresh(cur, ideas, task)
        return "handled"
    if verdict.verdict == "deny":
        _finish_attempt(cur, attempt_id, "failed", "revoked" if verdict.reason_code == "permission_revoked" else "permission", verdict.reason_code)
        store.set_step(cur, step, state="blocked", reason_code=verdict.reason_code or "permission_missing", attempts=max(0, int(step["attempts"]) - 1),
                       reason="Rafii isn't allowed to do this step now.")
        revoke_for_step(cur, ideas, task, step, verdict)
        store.refresh(cur, ideas, task)
        return "handled"
    if not targets.all_present(cur, workspace_id, step["targetRefs"]):
        _finish_attempt(cur, attempt_id, "failed", "permanent", "target_changed")
        store.set_step(cur, step, state="blocked", reason_code="target_changed", reason="What this step works on has changed or moved.",
                       attempts=max(0, int(step["attempts"]) - 1))
        store.refresh(cur, ideas, task)
        return "handled"
    if step["effectKey"]:
        mode, found = store.receipt_begin(cur, task, step, attempt_id, trace_id)
        if mode == "replay":
            # The effect already happened (the step committed, then its executor died): replay the receipt, never repeat it.
            _finish_attempt(cur, attempt_id, "succeeded", None, "receipt_replayed")
            _complete_from_receipt(cur, ideas, task, step, found)
            return "handled"
        if mode == "conflict":
            _finish_attempt(cur, attempt_id, "failed", "conflict", "idempotency_conflict")
            store.set_step(cur, step, state="failed", reason="This step's inputs changed after it ran; nothing was repeated.")
            store.refresh(cur, ideas, task)
            return "handled"
    store.refresh(cur, ideas, task)
    return Claim(task=task, step=step, attempt_id=attempt_id, attempt_no=attempt_no, lease_owner=owner, executor=executor, trace_id=trace_id,
                 verdict=verdict, request_text=actor.request_text, actor=actor, approval_evidence=evidence)


def _next_attempt_no(cur, step) -> int:
    cur.execute("SELECT coalesce(max(attempt_no),0)+1 FROM public.pr_agent_step_attempts WHERE step_id::text=%s", (step["stepId"],))
    return int(cur.fetchone()[0])


def _insert_attempt(cur, task, step, attempt_no, executor, owner, verdict, trace_id, request_id, run_id) -> str:
    timeout = int(step["timeoutSeconds"])
    cur.execute("INSERT INTO public.pr_agent_step_attempts(step_id,task_id,workspace_id,actor,attempt_no,generation,executor,run_id,lease_owner,"
                "lease_expires_at,deadline_at,authz_token,authz_verdict,authz_reason,trace_id,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "now()+make_interval(secs => %s),now()+make_interval(secs => %s),%s,%s,%s,%s,%s) RETURNING id::text",
                (step["stepId"], task["taskId"], task["workspaceId"], task["createdBy"], attempt_no, int(step["generation"]), executor, run_id, owner,
                 leases.lease_seconds(timeout), timeout, verdict.token, verdict.verdict, (verdict.authz_reason or "allowed")[:64], trace_id,
                 (request_id or None) and str(request_id)[:80]))
    return cur.fetchone()[0]


def _finish_attempt(cur, attempt_id, state, category, code, timings=None) -> None:
    cur.execute("UPDATE public.pr_agent_step_attempts SET state=%s,error_category=%s,error_code=%s,finished_at=now(),timings=coalesce(%s::jsonb,timings) "
                "WHERE id::text=%s AND state='running'", (state, category, (code or None) and str(code)[:80], _json(timings), attempt_id))


def _json(value):
    import json
    return json.dumps(value) if value is not None else None


def _approval_evidence(cur, task, step) -> dict | None:
    """An approved (not yet consumed) approval for exactly this step generation, or for the explicit approval step gating it."""
    cur.execute("SELECT a.id::text,a.digest FROM public.pr_agent_approvals a JOIN public.pr_agent_steps s ON s.id=a.step_id "
                "WHERE a.task_id::text=%s AND a.workspace_id=%s AND a.state='approved' AND ((a.step_id::text=%s AND a.generation=%s) "
                "OR (s.kind='approval' AND s.inputs->>'approves'=%s)) ORDER BY a.decided_at DESC LIMIT 1",
                (task["taskId"], task["workspaceId"], step["stepId"], int(step["generation"]), step["stepKey"]))
    row = cur.fetchone()
    return {"approvalId": row[0], "digest": row[1]} if row else None


def consume_approval(cur, evidence: dict) -> None:
    """The approval is used up at the claim that acts on it (a replayed approval can never run the step twice)."""
    cur.execute("UPDATE public.pr_agent_approvals SET state='consumed',consumed_at=now(),updated_at=now() WHERE id::text=%s AND state='approved'",
                (evidence["approvalId"],))


def revoke_for_step(cur, ideas, task, step, verdict) -> None:
    """A deny at claim: pending approvals of this step become revoked (system), the paused run is discarded (CF-3 §6.2)."""
    from . import checkpoints
    closed = store.close_pending_approvals(cur, task["workspaceId"], task["taskId"], "revoked", step_ids={step["stepId"]})
    checkpoints.discard_live(cur, task["workspaceId"], task["taskId"], "permission_revoked")
    store.emit(cur, ideas, task, "revocation", stepKey=step["stepKey"], reasonCode=verdict.reason_code, revokedApprovals=len(closed))
    store.log_event("revoked", taskId=task["taskId"], stepKey=step["stepKey"], reasonCode=verdict.reason_code)


def _handle_inline_kind(cur, ideas, task, step, verdict, evidence, trace_id) -> None:
    """approval / wait / delegate steps resolve inside the claiming transaction (no provider I/O, no lease needed)."""
    read_failed = False
    if verdict.verdict == "deny":
        store.set_step(cur, step, state="blocked", reason_code=verdict.reason_code or "permission_missing", reason="Rafii isn't allowed to do this step now.")
        revoke_for_step(cur, ideas, task, step, verdict)
    elif step["kind"] == "approval":
        steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
        gated = next((s for s in steps if s["stepKey"] == (step.get("inputs") or {}).get("approves")), None)
        if gated is None or gated["state"] in model.TERMINAL_STATES:
            store.set_step(cur, step, state="cancelled", reason_code="dependency_failed", reason="There is nothing left to approve.")
        else:
            from .approvals import request_approval
            request_approval(cur, ideas, task, step, None, gated=gated, trace_id=trace_id)
    elif step["kind"] == "wait":
        store.set_step(cur, step, state="completed", verified=True, reason=None)
    elif step["kind"] == "delegate":
        read_failed = _poll_delegate(cur, ideas, task, step)
    store.refresh(cur, ideas, task, extend_expiry=step["state"] == "completed")
    return read_failed


def _poll_delegate(cur, ideas, task, step) -> None:
    result = delegates.poll(cur, task, step)
    if result.state == "completed":
        store.set_step(cur, step, state="completed", verified=True, reason=result.reason, outputs=_merge(step["outputs"], result.outputs))
    elif result.state == "failed":
        store.set_step(cur, step, state="failed", reason_code=result.reason_code, reason=result.reason, outputs=_merge(step["outputs"], result.outputs))
        if not model.retryable(store.facts([step])[0], int(task["attemptsLeft"])):
            store.cancel_dependents(cur, store.load_steps(cur, task["workspaceId"], task["taskId"]), step["stepKey"])
    elif result.state == "blocked":
        store.set_step(cur, step, state="blocked", reason_code=result.reason_code, reason=result.reason)
    else:
        # Still in flight (e.g. a publish job the queue holds as `uncertain`): keep observing; a poll is not a retry.
        store.set_step(cur, step, state="queued", next_attempt_at=time.time() + model.DELEGATE_POLL_SECONDS, reason=result.reason,
                       outputs=_merge(step["outputs"], result.outputs))
    store.emit(cur, ideas, task, "task_step", stepId=step["stepKey"], state=model.legacy_state(step["state"], step["reasonCode"]), label=step["label"],
               reason=step["reason"], at=time.time())
    return result.read_failed


def _merge(old, new):
    out = list(old or [])
    for item in new or []:
        if item not in out:
            out.append(item)
    return out[:20]


def _complete_from_receipt(cur, ideas, task, step, receipt) -> None:
    verified = bool(receipt.get("verified"))
    refs = (receipt.get("result") or {}).get("changedRefs") or []
    if receipt.get("outcome") == "applied" and verified:
        store.set_step(cur, step, state="completed", verified=True, reason=None, reason_code=None,
                       entities=_merge(step["entities"], [{"type": r.get("type"), "id": r.get("id")} for r in refs]))
    else:
        store.set_step(cur, step, state="failed", reason_code="outcome_unknown", reason="Rafii couldn't confirm this step's result.")
    store.emit(cur, ideas, task, "task_step", stepId=step["stepKey"], state=model.legacy_state(step["state"], step["reasonCode"]), label=step["label"],
               reason=step["reason"], at=time.time())
    store.refresh(cur, ideas, task, extend_expiry=verified)


# --- running a claimed tool step -----------------------------------------------------------------------------------------
class _ActingService:
    """The hosted service as seen by a cron step: every repository transaction acts as the task's creator through
    principal_repository (membership, role and account state re-checked in every transaction)."""

    def __init__(self, service, repository):
        self._service = service
        self.repository = repository

    def __getattr__(self, name):
        return getattr(self._service, name)


def _context(runtime, claim: Claim, *, token, service, member, seconds_left: float):
    from ..context import RafiiRunContext
    task, step = claim.task, claim.step
    ctx = RafiiRunContext(service=service, workspace_id=task["workspaceId"], token=token, principal=task["createdBy"], membership=member,
                          conversation_id=task["conversationId"], trace_id=claim.trace_id, modality="text", now=getattr(runtime, "clock", time.time),
                          config=getattr(runtime, "cfg", None), image_studio=getattr(runtime, "image_studio", None), vision=getattr(runtime, "vision", None),
                          request_text=claim.request_text)
    budget = max(1.0, min(float(step["timeoutSeconds"]), seconds_left - model.INLINE_RESERVE_SECONDS))
    ctx.deadline = time.monotonic() + budget
    heartbeat = {"at": time.monotonic()}

    def cancelled() -> bool:
        # Before every non-READ effect: the person cancelled the task, or this attempt was reaped / is no longer ours.
        with store.service_tx(runtime.service, task["workspaceId"]) as cur:
            cur.execute("SELECT t.cancel_requested_at IS NOT NULL, a.state, a.lease_owner FROM public.pr_agent_tasks t JOIN public.pr_agent_step_attempts a "
                        "ON a.task_id=t.id WHERE a.id::text=%s", (claim.attempt_id,))
            row = cur.fetchone()
            if not row or row[0] or row[1] != "running" or row[2] != claim.lease_owner:
                return True
            if time.monotonic() - heartbeat["at"] >= leases.HEARTBEAT_EVERY_SECONDS:
                leases.renew(cur, "pr_agent_step_attempts", claim.attempt_id, lease_owner=claim.lease_owner, timeout_seconds=int(step["timeoutSeconds"]))
                heartbeat["at"] = time.monotonic()
        return False
    ctx.cancelled = cancelled
    # The step binding (CF-3 §8.1): a receipt-aware executor commits the receipt in its own domain transaction (receipts.commit_in).
    ctx.step_binding = {"taskId": task["taskId"], "stepId": step["stepId"], "stepKey": step["stepKey"], "effectKey": step["effectKey"],
                        "attemptId": claim.attempt_id, "leaseOwner": claim.lease_owner, "inputDigest": step["inputDigest"], "workspaceId": task["workspaceId"],
                        "principal": task["createdBy"], "traceId": claim.trace_id}
    return ctx


def execute(runtime, claim: Claim, *, token=None, seconds_left: float = DEFAULT_REQUEST_SECONDS, return_result=False) -> dict:
    """Run the claimed tool step outside any transaction and finish it. Returns a content-free summary."""
    from .. import domain_tools, tool_adapter
    domain_tools.ensure_registered()
    task, step = claim.task, claim.step
    service = runtime.service
    started = time.monotonic()
    ctx = None
    try:
        tool = tool_adapter.REGISTRY.get(step["capabilityId"])
        with store.service_tx(runtime.service, task["workspaceId"]) as cur:
            current = store.lock_task(cur, runtime.service.ideas, task["workspaceId"], task["taskId"])
            member = authz_seam.membership(cur, task["workspaceId"], task["createdBy"])
            actor = claim.actor or authz_seam.Actor("cron" if claim.executor == "cron" else "agent", task["createdBy"], claim.request_text)
            verdict = authz_seam.decide_for_step(cur, current, step, actor=actor, now=time.time(), allowed_before=True,
                                                config=getattr(runtime, "cfg", None))
            if current["cancelRequestedAt"] is not None or not leases.still_owned(cur, "pr_agent_step_attempts", claim.attempt_id, lease_owner=claim.lease_owner):
                result = {"ok": False, "code": "run_cancelled", "error": "This step has stopped."}
            elif verdict.verdict != "allow":
                result = {"ok": False, "code": "agent_permission_revoked", "error": "This step is no longer allowed."}
            else:
                if claim.approval_evidence:
                    consume_approval(cur, claim.approval_evidence)
                result = None
        if result is None and tool is None:
            result = {"ok": False, "code": "unsupported", "error": "This capability is no longer available."}
        if result is None:
            if claim.executor == "cron" or token is None:
                from ...automation_runs import principal_repository
                repository, capability = principal_repository(service, task["workspaceId"], task["createdBy"], tool.spec.permission)
                service, token = _ActingService(service, repository), capability
            ctx = _context(runtime, claim, token=token, service=service, member=member, seconds_left=seconds_left)
            result = tool_adapter.execute(ctx, tool, dict(step["inputs"] or {}))
    except AlphaError as error:
        result = {"ok": False, "code": getattr(error, "code", None) or "tool_forbidden", "error": str(error)}
    except Exception as error:  # the leased attempt always records its known outcome
        result = {"ok": False, "code": "tool_error", "error": type(error).__name__}
    elapsed_ms = round((time.monotonic() - started) * 1000)
    outcome = finish(runtime, claim, result, ctx=ctx, elapsed_ms=elapsed_ms)
    return {**result, "taskStep": outcome} if return_result else outcome


def _category(result: dict, step: dict) -> str:
    code = str(result.get("code") or "failed")
    if code == "tool_error":
        return "retryable" if step["effect"] == "READ" else "outcome_unknown"
    return _CODE_CATEGORY.get(code, "permanent")


def finish(runtime, claim: Claim, result: dict, *, ctx=None, elapsed_ms: int = 0) -> dict:
    """Record the attempt's outcome in one bookkeeping transaction (the creator's session may be gone). Lease lost → nothing."""
    from . import compensation
    service, ideas = runtime.service, runtime.service.ideas
    task_id, workspace_id = claim.task["taskId"], claim.task["workspaceId"]
    with store.service_tx(service, workspace_id) as cur:
        task = store.lock_task(cur, ideas, workspace_id, task_id)
        steps = store.load_steps(cur, workspace_id, task_id, lock=True) if task is not None else []
        step = next((s for s in steps if s["stepId"] == claim.step["stepId"]), None)
        if task is None or step is None or not leases.still_owned(cur, "pr_agent_step_attempts", claim.attempt_id, lease_owner=claim.lease_owner):
            # Reaped, cancelled or deleted meanwhile: a producer that lost its lease writes nothing.
            store.log_event("lease_lost", taskId=task_id, stepKey=claim.step["stepKey"], attempt=claim.attempt_no)
            return {"stepKey": claim.step["stepKey"], "state": "lease_lost"}
        timings = {"ms": elapsed_ms}
        committed = store.receipt(cur, workspace_id, step["effectKey"], lock=True) if step["effectKey"] else None
        if committed and committed["state"] == "done" and committed["outcome"] == "applied" and committed.get("verified"):
            _finish_attempt(cur, claim.attempt_id, "succeeded", None, None, timings)
            _complete_from_receipt(cur, ideas, task, step, committed)
            return {"stepKey": step["stepKey"], "state": "completed", "taskState": store.load_task(cur, workspace_id, task_id)["state"]}
        ok = bool(result.get("ok", True)) and not result.get("needsUser")
        verified = bool(result.get("verified", result.get("ok", True)))
        changed = list(getattr(getattr(ctx, "ledger", None), "changed", []) or [])
        refs = [{"type": c.get("type"), "id": c.get("id"), "change": c.get("change")} for c in changed if isinstance(c, dict) and c.get("id")]
        if ok:
            receipt_info = {"checks": result.get("checks") or [], "changedRefs": refs, "costState": "none", "compensation": {"available": False}}
            if verified:
                if step["effectKey"]:
                    receipt_info["compensation"] = compensation.capture(cur, task, step, result, refs)
                    store.receipt_done(cur, workspace_id, step["effectKey"], outcome="applied", verified=True, result=receipt_info)
                _finish_attempt(cur, claim.attempt_id, "succeeded", None, None, timings)
                store.set_step(cur, step, state="completed", verified=True, reason=None, reason_code=None,
                               entities=_merge(step["entities"], [{"type": r["type"], "id": r["id"]} for r in refs]),
                               outputs=_merge(step["outputs"], _outputs(result)))
            else:
                if step["effectKey"]:
                    store.receipt_done(cur, workspace_id, step["effectKey"], outcome="applied", verified=False, result=receipt_info)
                _finish_attempt(cur, claim.attempt_id, "succeeded", None, "unverified", timings)
                store.set_step(cur, step, state="failed", verified=False, reason="The change could not be confirmed by re-reading the workspace.")
        elif result.get("needsUser"):
            if step["effectKey"]:
                store.receipt_done(cur, workspace_id, step["effectKey"], outcome="rejected", verified=None, result={})
            _finish_attempt(cur, claim.attempt_id, "succeeded", None, str(result.get("code") or "needs_detail"), timings)
            store.set_step(cur, step, state="blocked", reason_code="needs_input",
                           reason=model.clip(result.get("question") or result.get("error") or "Rafii needs more detail for this step.", 300))
        else:
            category = _category(result, step)
            previous_conflict = _previous_category(cur, step) == "conflict"
            outcome = leases.classify(category, retry_class=step["retryClass"], attempts=int(step["attempts"]), max_attempts=int(step["maxAttempts"]),
                                      conflict_retried=previous_conflict)
            _finish_attempt(cur, claim.attempt_id, "cancelled" if outcome.state == "cancelled" else "failed", category, result.get("code"), timings)
            if step["effectKey"] and outcome.state in ("failed", "cancelled", "blocked") and category not in ("outcome_unknown",):
                store.receipt_done(cur, workspace_id, step["effectKey"], outcome="failed", verified=False, result={})
            reason = model.clip(result.get("error"), 300)
            if outcome.state == "queued":
                store.set_step(cur, step, state="queued", next_attempt_at=time.time() + outcome.delay_seconds, reason=reason)
            elif outcome.state == "blocked":
                store.set_step(cur, step, state="blocked", reason_code=outcome.reason_code, reason=reason)
            else:
                store.set_step(cur, step, state=outcome.state, reason_code=outcome.reason_code, reason=reason)
                if outcome.state == "failed" and not model.retryable(store.facts([step])[0], int(task["attemptsLeft"])):
                    store.cancel_dependents(cur, steps, step["stepKey"])
        store.emit(cur, ideas, task, "task_step", stepId=step["stepKey"], state=model.legacy_state(step["state"], step["reasonCode"]), label=step["label"],
                   reason=step["reason"], at=time.time())
        store.emit(cur, ideas, task, "step_attempt", stepKey=step["stepKey"], attempt=claim.attempt_no, state=step["state"])
        updated = store.refresh(cur, ideas, task, extend_expiry=step["state"] == "completed")
        store.log_event("step_finished", taskId=task_id, stepKey=step["stepKey"], attempt=claim.attempt_no, state=step["state"], ms=elapsed_ms,
                        traceId=claim.trace_id)
        return {"stepKey": step["stepKey"], "state": step["state"], "taskState": updated["state"]}


def _outputs(result: dict) -> list:
    out = []
    for key, kind in (("draftId", "draft"), ("campaignId", "campaign"), ("assetId", "asset"), ("jobId", "job"), ("reviewId", "review")):
        if isinstance(result.get(key), str):
            out.append({"type": kind, "id": result[key]})
    return out


def _previous_category(cur, step) -> str | None:
    cur.execute("SELECT error_category FROM public.pr_agent_step_attempts WHERE step_id::text=%s AND state<>'running' AND generation=%s "
                "ORDER BY attempt_no DESC LIMIT 1", (step["stepId"], int(step["generation"])))
    row = cur.fetchone()
    return row[0] if row else None


# --- the inline driver (the creator's own request) ----------------------------------------------------------------------
def drive_inline(runtime, workspace_id: str, token: str, principal: str, task_id: str, *, actor_kind: str = "agent", request_text: str = "",
                 request_id: str | None = None, seconds: float = DEFAULT_REQUEST_SECONDS, max_steps: int = model.MAX_STEPS) -> list[str]:
    """Run this creator's ready steps of one task inside the current request's budget. Returns the step keys it finished."""
    deadline = time.monotonic() + seconds
    owner = lease_owner("inline", request_id)
    done: list[str] = []
    for _ in range(max_steps * 2):
        left = deadline - time.monotonic()
        with runtime.service.repository.transaction(token, workspace_id) as (cur, _row, acting):
            if acting != principal:
                raise AlphaError("Workspace unavailable.", 403)
            claimed = claim_next(cur, runtime.service.ideas, workspace_id=workspace_id, executor="inline", principal=principal, task_id=task_id,
                                 seconds_left=left - model.INLINE_RESERVE_SECONDS, owner=owner, request_id=request_id, actor_kind=actor_kind,
                                 request_text=request_text, config=getattr(runtime, "cfg", None))
        if claimed is None:
            break
        if claimed == "handled":
            continue
        outcome = execute(runtime, claimed, token=token, seconds_left=deadline - time.monotonic())
        if outcome.get("state") == "completed":
            done.append(outcome["stepKey"])
        elif outcome.get("state") not in ("queued",):
            # Failed, blocked or cancelled: the dependents wait; independent steps may still run.
            continue
    return done


# --- recovery and expiry (cron phases 1-3; zero provider requests) ------------------------------------------------------
def recover(runtime, *, limit: int = 50, budget_seconds: float = RECOVERY_BUDGET_SECONDS) -> dict:
    """Phase 1: attempts whose lease expired → interrupted; the step completes from a done receipt, requeues if `auto`, else
    fails/outcome_unknown (manual retry offered). Never re-runs a manual step. Isolated: never raises."""
    from . import flags
    started = time.monotonic()
    counts = {"interrupted": 0, "completedFromReceipt": 0, "requeued": 0, "outcomeUnknown": 0, "skipped": 0}
    try:
        with runtime.service.repository.connection_factory() as db, db.cursor() as scan:
            scan.execute("SELECT a.id::text,a.workspace_id::text FROM public.pr_agent_step_attempts a WHERE a.state='running' AND a.lease_expires_at < now() "
                         "ORDER BY a.lease_expires_at LIMIT %s", (int(limit),))
            candidates = scan.fetchall()
        for attempt_id, workspace_id in candidates:
            if time.monotonic() - started > budget_seconds:
                break
            outcome = _reap_one(runtime, workspace_id, attempt_id, authoritative=flags.enabled_for(workspace_id, getattr(runtime, "cfg", None)))
            if outcome:
                counts["interrupted"] += 1
                counts[outcome] = counts.get(outcome, 0) + 1
    except Exception as error:  # noqa: BLE001
        counts["error"] = type(error).__name__
    return counts


def _reap_one(runtime, workspace_id: str, attempt_id: str, *, authoritative=True) -> str | None:
    ideas = runtime.service.ideas
    with store.service_tx(runtime.service, workspace_id, skip_locked=True) as cur:
        if cur is None:
            return None
        cur.execute("SELECT task_id::text,step_id::text FROM public.pr_agent_step_attempts WHERE id::text=%s", (attempt_id,))
        found = cur.fetchone()
        if not found:
            return None
        task = store.lock_task(cur, ideas, workspace_id, found[0])
        steps = store.load_steps(cur, workspace_id, found[0], lock=True)
        cur.execute("SELECT state='running' AND lease_expires_at < now() FROM public.pr_agent_step_attempts WHERE id::text=%s FOR UPDATE", (attempt_id,))
        if task is None or not cur.fetchone()[0]:
            return None                                  # renewed or finished since the scan
        step = next(s for s in steps if s["stepId"] == found[1])
        cur.execute("UPDATE public.pr_agent_step_attempts SET state='interrupted',error_category='outcome_unknown',error_code='lease_expired',"
                    "finished_at=now(),cost_state=CASE WHEN reservation_id IS NOT NULL THEN 'unknown' ELSE cost_state END WHERE id::text=%s", (attempt_id,))
        _settle_unknown(runtime, cur, workspace_id, attempt_id)
        if not authoritative:
            return "rollbackSettled"
        receipt = store.receipt(cur, workspace_id, step["effectKey"], lock=True) if step["effectKey"] else None
        decision = leases.reaped(receipt_done=bool(receipt and receipt["state"] == "done" and receipt["outcome"] == "applied"),
                                 receipt_verified=bool(receipt and receipt.get("verified")), retry_class=step["retryClass"], attempts=int(step["attempts"]),
                                 max_attempts=int(step["maxAttempts"]), task_attempts_left=int(task["attemptsLeft"]))
        if step["state"] != "running":
            outcome = "skipped"
        elif decision == "completed":
            _complete_from_receipt(cur, ideas, task, step, receipt)
            outcome = "completedFromReceipt"
        elif decision.state == "queued":
            store.set_step(cur, step, state="queued", next_attempt_at=time.time() + decision.delay_seconds,
                           reason="The last try stopped before it finished; Rafii will try again.")
            outcome = "requeued"
        else:
            store.set_step(cur, step, state="failed", reason_code="outcome_unknown",
                           reason="The last try stopped before Rafii could confirm it. Retry it if it didn't happen.")
            outcome = "outcomeUnknown"
        store.emit(cur, ideas, task, "task_step", stepId=step["stepKey"], state=model.legacy_state(step["state"], step["reasonCode"]), label=step["label"],
                   reason=step["reason"], at=time.time())
        store.refresh(cur, ideas, task)
        store.log_event("step_reclaimed", taskId=task["taskId"], stepKey=step["stepKey"], outcome=outcome)
        return outcome


def _settle_unknown(runtime, cur, workspace_id, attempt_id) -> None:
    """A reaped attempt's reservation is settled unknown (the hold is kept, never booked as zero)."""
    cur.execute("SELECT reservation_id FROM public.pr_agent_step_attempts WHERE id::text=%s", (attempt_id,))
    row = cur.fetchone()
    ledger = getattr(runtime.service, "ledger", None)
    if row and row[0] and ledger is not None:
        try:
            ledger.settle(cur, workspace_id, row[0], "unknown", None)
        except AlphaError:
            pass


def expire(runtime, *, limit: int = 50, budget_seconds: float = RECOVERY_BUDGET_SECONDS) -> dict:
    """Phase 2: approvals past expiry → expired + step failed/approval_expired; checkpoints past expiry → discarded;
    compensations past their window → expired; tasks past expires_at → open steps cancelled/task_expired, except external-effect
    observers, which keep observing until the hard cap and then end failed/outcome_unknown with the job link (§4.4)."""
    from . import approvals, checkpoints, flags
    started = time.monotonic()
    counts = {"approvals": 0, "tasks": 0, "observersCapped": 0, "compensations": 0}
    ideas = runtime.service.ideas
    try:
        with runtime.service.repository.connection_factory() as db, db.cursor() as scan:
            scan.execute("SELECT a.id::text,a.workspace_id::text FROM public.pr_agent_approvals a WHERE a.state='pending' AND a.expires_at <= now() LIMIT %s", (limit,))
            expired_approvals = scan.fetchall()
            scan.execute("SELECT t.id::text,t.workspace_id::text FROM public.pr_agent_tasks t WHERE t.state IN ('queued','running','awaiting_approval','blocked') "
                         "AND t.expires_at <= now() ORDER BY t.expires_at LIMIT %s", (limit,))
            expired_tasks = scan.fetchall()
            scan.execute("SELECT DISTINCT workspace_id::text FROM public.pr_agent_checkpoints WHERE state IN ('available','claimed') "
                         "UNION SELECT DISTINCT workspace_id::text FROM public.pr_agent_compensations WHERE state='available'")
            bookkeeping_workspaces = [r[0] for r in scan.fetchall()]
        counts["checkpoints"] = {"released": 0, "discarded": 0}
        for workspace_id in bookkeeping_workspaces:
            if time.monotonic() - started > budget_seconds or not flags.enabled_for(workspace_id, getattr(runtime, "cfg", None)):
                continue
            with store.service_tx(runtime.service, workspace_id, skip_locked=True) as cur:
                if cur is None:
                    continue
                cur.execute("UPDATE public.pr_agent_compensations SET state='expired',updated_at=now() "
                            "WHERE workspace_id=%s AND state='available' AND undo_until <= now() RETURNING 1", (workspace_id,))
                counts["compensations"] += len(cur.fetchall())
                swept = checkpoints.sweep(cur, workspace_id)
                for key, count in swept.items():
                    counts["checkpoints"][key] += count
        for approval_id, workspace_id in expired_approvals:
            if time.monotonic() - started > budget_seconds or not flags.enabled_for(workspace_id, getattr(runtime, "cfg", None)):
                continue
            with store.service_tx(runtime.service, workspace_id, skip_locked=True) as cur:
                if cur is None:
                    continue
                found = store.load_approval(cur, workspace_id, approval_id)
                if found is None:
                    continue
                task = store.lock_task(cur, ideas, workspace_id, found["taskId"])
                approval = store.load_approval(cur, workspace_id, approval_id, lock=True)
                if task is not None and approval is not None and approval["state"] == "pending":
                    approvals.expire(cur, ideas, task, approval)
                    counts["approvals"] += 1
        for task_id, workspace_id in expired_tasks:
            if time.monotonic() - started > budget_seconds or not flags.enabled_for(workspace_id, getattr(runtime, "cfg", None)):
                continue
            with store.service_tx(runtime.service, workspace_id, skip_locked=True) as cur:
                if cur is None:
                    continue
                capped = expire_task(cur, ideas, workspace_id, task_id)
                counts["tasks"] += 1
                counts["observersCapped"] += capped
    except Exception as error:  # noqa: BLE001
        counts["error"] = type(error).__name__
    return counts


def expire_task(cur, ideas, workspace_id: str, task_id: str) -> int:
    from . import checkpoints
    task = store.lock_task(cur, ideas, workspace_id, task_id)
    if task is None or task["state"] in model.TERMINAL_STATES:
        return 0
    cur.execute("SELECT hard_expires_at <= now() FROM public.pr_agent_tasks WHERE id::text=%s", (task_id,))
    hard = bool(cur.fetchone()[0])
    capped = 0
    steps = store.load_steps(cur, workspace_id, task_id, lock=True)
    for step in steps:
        if step["state"] not in ("queued", "awaiting_approval", "blocked"):
            continue
        if step["observesExternal"]:
            if hard:
                # The queue still holds the job; Rafii can't confirm the outcome. The job link stays on the step.
                store.set_step(cur, step, state="failed", reason_code="outcome_unknown", reason="Rafii can't confirm this yet; check the post in your queue.")
                capped += 1
            continue
        store.set_step(cur, step, state="cancelled", reason_code="task_expired", reason="This task waited too long and was closed.")
    store.close_pending_approvals(cur, workspace_id, task_id, "expired")
    if not any(s["observesExternal"] and s["state"] in model.OPEN_STATES for s in steps):
        checkpoints.discard_live(cur, workspace_id, task_id, "task_expired")
    updated = store.refresh(cur, ideas, task)
    if updated["state"] in model.OPEN_STATES and not any(s["state"] in ("running",) or (s["observesExternal"] and s["state"] in model.OPEN_STATES)
                                                         for s in store.load_steps(cur, workspace_id, task_id)):
        # Nothing can move any more (an empty plan, or only steps no executor runs): close it as expired.
        cur.execute("UPDATE public.pr_agent_tasks SET state='cancelled',reason_code='task_expired',finished_at=now(),version=version+1,updated_at=now() "
                    "WHERE id::text=%s", (task_id,))
        updated = store.load_task(cur, workspace_id, task_id)
        store.mirror_anchor(cur, updated, store.load_steps(cur, workspace_id, task_id))
    store.emit(cur, ideas, updated, "task_state", state=updated["state"], reasonCode="task_expired")
    return capped


# --- the cron claim loop (phase 4; only on /api/cron/agent-tasks with RAFII_AGENT_TASKS_BACKGROUND) --------------------
def claim_loop(runtime, *, budget_seconds: float = 40.0, max_claims: int = 50) -> dict:
    from . import flags
    started = time.monotonic()
    counts = {"claimed": 0, "handled": 0, "executed": 0, "deferred": 0}
    with runtime.service.repository.connection_factory() as db, db.cursor() as scan:
        scan.execute("SELECT DISTINCT s.workspace_id::text FROM public.pr_agent_steps s WHERE s.state='queued' AND s.background_allowed "
                     "AND s.next_attempt_at <= now() LIMIT 50")
        workspaces = [r[0] for r in scan.fetchall()]
    for workspace_id in workspaces:
        if not flags.background_for(workspace_id, getattr(runtime, "cfg", None)):
            continue
        while counts["claimed"] < max_claims:
            left = budget_seconds - (time.monotonic() - started)
            if left <= 5:
                counts["deferred"] += 1
                return counts
            owner = lease_owner("cron")
            with store.service_tx(runtime.service, workspace_id, skip_locked=True) as cur:
                if cur is None:
                    counts["deferred"] += 1
                    break
                claimed = claim_next(cur, runtime.service.ideas, workspace_id=workspace_id, executor="cron", principal=None, task_id=None,
                                     seconds_left=left, owner=owner, config=getattr(runtime, "cfg", None))
            if claimed is None:
                break
            counts["claimed"] += 1
            if claimed == "handled":
                counts["handled"] += 1
                continue
            execute(runtime, claimed, token=None, seconds_left=left)
            counts["executed"] += 1
    return counts
