"""Approvals: suspend and resume through one path (CF-3 §10; CF-2 §9, E7, E8; corrections 2, 4, 17).

`request_approval` suspends a step on a pr_agent_approvals row requested for the task's creator. `resolve_approval` is the
only executor of a decision, whatever the surface (task center / native card route `POST approvals/{id}/decide`, the legacy
panel body, a typed or spoken "yes"):

- an `agent_action`/`spend` approval only moves its step to `queued` (or completes an explicit `approval` step); the work
  then runs solely through the engine's claim → decide_for_step → receipt → lease path, inline in the creator's request;
- a legacy proposal is applied through the existing proposal apply path, unchanged, under the decider's own approve right;
- only the creator's request ever continues the creator's task: another member's approval completes the approved step and
  leaves `needsMe.kind='continue'` for the creator (no continuation, no reservation and no creator-private detail in the
  decider's response);
- a replay with the same decider and key returns the stored outcome once; the key reused by anyone else is 409.
"""
from __future__ import annotations

import time

from postriff_alpha.domain import AlphaError

from . import authz_seam, errors, model, store

STEP_UP_SECONDS = 300
_DECISIONS = ("approve", "reject")


def request_approval(cur, ideas, task: dict, step: dict, verdict: authz_seam.StepVerdict | None, *, kind: str = "agent_action",
                     gated: dict | None = None, trace_id: str | None = None, spend_limit: int | None = None) -> str:
    """Suspend `step` on a new approval for the task's creator. For an explicit `approval` step, `gated` is the tool step it
    approves (its capability, inputs and targets are what the digest binds)."""
    subject = gated or step
    risk = subject["riskClass"] if subject["riskClass"] in ("R1", "R2", "R3") else "R1"
    kind = (verdict.approval_kind if verdict is not None and verdict.approval_kind else kind)
    if kind == "proposal":
        kind = "agent_action"      # a new engine row is never a legacy proposal (those are wrapped by ensure_proposal_approval)
    step_up = kind == "step_up_action" or bool(verdict and verdict.requires_step_up)
    if step_up:
        risk, kind = "R3", "step_up_action"
    digest = model.approval_digest(subject["capabilityId"] or "", subject["inputDigest"] or "", subject["targetRefs"], risk, int(subject["generation"]))
    summary = {"what": "agent_action", "capabilityId": subject["capabilityId"], "risk": risk,
               "step": {"label": subject["label"], "note": "The person's own plan label, quoted as data."},
               "targets": [{"type": t.get("type"), "id": t.get("id")} for t in subject["targetRefs"]][:10]}
    if kind == "spend" and isinstance(spend_limit, int) and spend_limit > 0:
        summary["budgetCeilingUsdMicro"] = spend_limit
        summary["what"] = "increase_task_spending_limit"
    approval_id = store.insert_approval(
        cur, task=task, step=step, kind=kind, risk=risk, confirmation="approval_step_up" if step_up else "native", digest=digest, summary=summary,
        required_permission=(verdict.required_permission if verdict and verdict.required_permission in ("edit", "approve", "owner") else "edit"),
        approver_policy="task_owner" if kind in ("agent_action", "spend") else (verdict.approver_policy if verdict else "task_owner"),
        authz_token=(verdict.token if verdict else task["authzToken"]),
        ttl_seconds=model.STEP_UP_APPROVAL_TTL_SECONDS if step_up else model.APPROVAL_TTL_SECONDS,
        capability_id=subject["capabilityId"], input_digest=subject["inputDigest"], inputs=subject["inputs"] or {}, target_refs=subject["targetRefs"],
        trace_id=trace_id, requires_step_up=step_up)
    store.set_step(cur, step, state="awaiting_approval", reason_code=None, reason="Waiting for your approval.")
    store.emit(cur, ideas, task, "approval", approvalId=approval_id, stepKey=step["stepKey"], state="pending", approvalKind=kind)
    store.log_event("approval_requested", taskId=task["taskId"], stepKey=step["stepKey"], approvalId=approval_id, kind=kind, traceId=trace_id)
    return approval_id


def ensure_proposal_approval(cur, ideas, task: dict, step: dict, item: dict, *, just_decided: bool = False) -> dict | None:
    """Wrap a legacy site-agent proposal a task step waits on (X1): one row per proposal; its digest, type, summary and expiry are
    the proposal's own; decided under today's role rule (`role_approve`)."""
    proposal = (item or {}).get("proposal") or {}
    if not proposal.get("id") or proposal.get("type") not in model.LEGACY_PROPOSAL_TYPES or not proposal.get("digest"):
        return None
    found = store.approval_by_proposal(cur, task["workspaceId"], proposal["id"])
    if found is not None:
        return found if found["taskId"] == task["taskId"] else None
    if proposal.get("status") != "proposed" and not just_decided:
        # Decided on the legacy path before any row existed, by someone this module cannot name: no row is invented.
        return None
    required = proposal.get("requiredPermission") if proposal.get("requiredPermission") in ("edit", "approve", "owner") else "approve"
    digest = str(proposal.get("digest"))
    if len(digest) != 64:
        digest = model.sha256(digest)
    expires = float(proposal.get("expiresAt") or (time.time() + model.APPROVAL_TTL_SECONDS))
    approval_id = store.insert_approval(
        cur, task=task, step=step, kind="proposal", risk="R2", confirmation="proposal", digest=digest,
        summary={"what": "proposal", "type": proposal.get("type"), "lines": [str(x)[:200] for x in proposal.get("summary") or []][:6]},
        required_permission=required, approver_policy="role_approve", authz_token=task["authzToken"], ttl_seconds=model.APPROVAL_TTL_SECONDS,
        proposal_id=proposal["id"], proposal_type=proposal["type"], conversation_id=task["conversationId"], message_id=item.get("messageId"),
        expires_at=expires)
    return store.load_approval(cur, task["workspaceId"], approval_id)


# --- the one resolver ------------------------------------------------------------------------------------------------------
def _visible(approval: dict, principal: str, member) -> bool:
    if approval["requestedFor"] == principal:
        return True
    policy = approval["approverPolicy"]
    if policy == "role_approve":
        return member.allows(approval["requiredPermission"] if approval["requiredPermission"] in ("approve", "owner") else "approve")
    if policy == "role_owner":
        return member.allows("owner")
    return False


def _may_decide(approval: dict, principal: str, member) -> bool:
    policy = approval["approverPolicy"]
    if policy == "task_owner":
        return principal == approval["requestedFor"]
    if policy == "role_approve":
        return member.allows(approval["requiredPermission"] if approval["requiredPermission"] in ("edit", "approve", "owner") else "approve")
    return member.allows("owner")


def _fresh_sign_in(service, token, principal, window=STEP_UP_SECONDS) -> bool:
    auth_time = getattr(getattr(service.repository, "verify_session", None), "auth_time", None)
    verified_at = auth_time(token, principal) if auth_time else 0
    return time.time() - float(verified_at or 0) <= window


def _gated_step(cur, task: dict, approval: dict) -> tuple[dict, dict | None]:
    """(the approval's own step, the tool step it gates when the approval step is an explicit `approval` step)."""
    steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
    own = next(s for s in steps if s["stepId"] == approval["stepId"])
    if own["kind"] == "approval":
        key = (own.get("inputs") or {}).get("approves")
        return own, next((s for s in steps if s["stepKey"] == key), None)
    return own, None


def _targets_present(cur, task: dict, refs: list) -> bool:
    from . import targets
    return targets.all_present(cur, task["workspaceId"], refs)


def validate_payload(payload) -> tuple[str, str, str]:
    if not isinstance(payload, dict) or payload.get("decision") not in _DECISIONS or not isinstance(payload.get("digest"), str):
        raise AlphaError("Send the decision, the digest you saw and an idempotency key.", 400)
    key = payload.get("idempotencyKey")
    if not isinstance(key, str) or not (16 <= len(key) <= 120):
        raise AlphaError("Send an idempotency key of 16 to 120 characters.", 400)
    return payload["decision"], payload["digest"], key


def resolve_approval(runtime, workspace_id: str, token: str, approval_id: str, payload: dict, *, surface: str = "task_center") -> dict:
    """POST approvals/{approvalId}/decide. Returns the decision response; raises the frozen CF-2 §13.1 codes."""
    from . import views
    started = time.monotonic()
    decision, digest, decision_key = validate_payload(payload)
    service, ideas = runtime.service, runtime.service.ideas
    deferred: AlphaError | None = None
    outcome: dict = {}
    proposal_apply = None
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        member = ideas._member(row)
        found = store.load_approval(cur, workspace_id, approval_id)
        if found is None:
            raise errors.error("approval_unavailable")
        task = store.lock_task(cur, ideas, workspace_id, found["taskId"])
        approval = store.load_approval(cur, workspace_id, approval_id, lock=True)
        if task is None or approval is None or not _visible(approval, principal, member):
            raise errors.error("approval_unavailable")
        cur.execute("SELECT id::text,decided_by::text FROM public.pr_agent_approvals WHERE workspace_id=%s AND decision_key=%s", (workspace_id, decision_key))
        reused = cur.fetchone()
        if reused and (reused[0] != approval["approvalId"] or reused[1] != principal):
            raise errors.error("idempotency_conflict")
        if approval["state"] != "pending":
            if approval["decidedBy"] == principal and approval["decisionKey"] == decision_key:
                stored = dict(approval.get("decisionOutcome") or {})
                return {**stored, "approvalId": approval["approvalId"], "replayed": True,
                        "task": views.task_for_decider(cur, task, principal, member)}
            raise errors.error("approval_closed")
        if surface in ("text", "voice") and not (approval["kind"] == "proposal" and approval["proposalType"] in model.LEGACY_PROPOSAL_TYPES):
            # Correction 17 / DP-5: a typed or spoken "yes" never decides a new approval kind. Zero state change.
            return {"approvalId": approval["approvalId"], "state": approval["state"], "outcome": "needs_panel_confirmation", "verified": False, "checks": [],
                    "task": views.task_ref(task), "resumed": "none", "speakableSummary": "Confirm on screen."}
        cur.execute("SELECT expires_at <= now() FROM public.pr_agent_approvals WHERE id::text=%s", (approval_id,))
        past_expiry = bool(cur.fetchone()[0])
        own, gated = _gated_step(cur, task, approval)
        if past_expiry:
            expire(cur, ideas, task, approval)
            deferred = errors.error("approval_expired")
        elif digest != approval["digest"]:
            raise errors.error("approval_stale")
        elif approval["kind"] != "proposal" and not _targets_present(cur, task, approval["targetRefs"]):
            store.close_approval(cur, approval, "revoked", surface="system")
            store.set_step(cur, own, state="blocked", reason_code="target_changed", reason="What this approval was about has changed or moved.")
            store.refresh(cur, ideas, task)
            deferred = errors.error("approval_stale")
        elif not _may_decide(approval, principal, member):
            raise errors.error("approval_forbidden")
        elif approval["requiresStepUp"] and not _fresh_sign_in(service, token, principal):
            raise AlphaError("Sign in again to confirm this.", 403, code="step_up_required")
        else:
            subject = gated or own
            if own["kind"] == "model":
                subject = {**own, "kind": "tool", "capabilityId": approval["capabilityId"], "inputs": approval["inputs"],
                           "inputDigest": approval["inputDigest"], "targetRefs": approval["targetRefs"], "riskClass": approval["riskClass"]}
            verdict = authz_seam.decide_for_step(cur, task, subject, actor=authz_seam.Actor("approval", task["createdBy"], "",
                                                                                         {"approvalId": approval["approvalId"], "digest": digest}),
                                                 now=time.time(), allowed_before=True, config=getattr(runtime, "cfg", None))
            if (verdict.verdict not in ("allow", "approve") or (verdict.verdict == "step_up" and not approval["requiresStepUp"])) and decision == "approve":
                store.close_approval(cur, approval, "revoked", surface="system")
                store.set_step(cur, own, state="blocked", reason_code=verdict.reason_code or "permission_revoked", reason="Rafii is no longer allowed to do this.")
                store.emit(cur, ideas, task, "revocation", stepKey=own["stepKey"], reasonCode=verdict.reason_code)
                store.refresh(cur, ideas, task)
                deferred = errors.error("agent_permission_revoked")
            elif approval["kind"] == "proposal":
                proposal_apply = {"approval": approval, "task": task, "own": own, "principal": principal}
            elif decision == "reject":
                outcome = {"state": "rejected", "outcome": "rejected", "verified": True, "checks": []}
                store.close_approval(cur, approval, "rejected", surface=surface, decided_by=principal, decision_key=decision_key, outcome=outcome)
                _reject_step(cur, ideas, task, own, gated)
            else:
                limit = (approval.get("summary") or {}).get("budgetCeilingUsdMicro")
                if approval["kind"] == "spend" and isinstance(limit, int) and limit > 0:
                    cur.execute("UPDATE public.pr_agent_tasks SET budget_ceiling_usd_micro=greatest(budget_ceiling_usd_micro,%s) WHERE id::text=%s", (limit, task["taskId"]))
                outcome = {"state": "approved", "outcome": "approved", "verified": True, "checks": []}
                store.close_approval(cur, approval, "approved", surface=surface, decided_by=principal, decision_key=decision_key, outcome=outcome)
                if own["kind"] == "approval":
                    store.set_step(cur, own, state="completed", verified=True, reason=None, reason_code=None)
                else:
                    store.set_step(cur, own, state="queued", next_attempt_at=time.time(), reason=None, reason_code=None)
                store.emit(cur, ideas, task, "approval", approvalId=approval["approvalId"], stepKey=own["stepKey"], state="approved")
                store.refresh(cur, ideas, task)
            store.log_event("approval_decided", taskId=task["taskId"], approvalId=approval["approvalId"], decision=decision, surface=surface,
                            traceId=task["rootTraceId"])
    if deferred is not None:
        raise deferred
    if proposal_apply is not None:
        return _resolve_proposal(runtime, workspace_id, token, proposal_apply, decision, digest, decision_key, surface, zone=payload.get("timeZone"))
    creator = task["createdBy"] == principal
    resumed, executed = "none", []
    if creator and decision == "approve":
        from . import executor
        applied_model = execute_approved_model(runtime, workspace_id, token, task, approval, seconds_left=240-(time.monotonic()-started))
        executed = [applied_model] if applied_model is not None else executor.drive_inline(runtime, workspace_id, token, principal, task["taskId"], actor_kind="approval", seconds=max(0,240-(time.monotonic()-started)))
        resumed = "inline" if executed else "none"
        if _has_checkpoint(runtime, workspace_id, task["taskId"]):
            resumed = continue_after_decision(runtime, workspace_id, token, task["taskId"], decision_key, seconds_left=240-(time.monotonic()-started)).get("resumed", "needs_continue")
    with service.repository.transaction(token, workspace_id) as (cur, row, _principal):
        member = ideas._member(row)
        current = store.load_task(cur, workspace_id, task["taskId"])
        task_view = views.task_for_decider(cur, current, principal, member)
    spoken = ("Approved. Rafii is doing it now." if resumed == "inline" else "Approved." if decision == "approve" else "Okay, Rafii won't do it.")
    return {"approvalId": approval_id, **outcome, "task": task_view, "resumed": resumed, "executed": executed, "speakableSummary": spoken}


def _reject_step(cur, ideas, task, own, gated) -> None:
    store.set_step(cur, own, state="cancelled", reason_code="approval_rejected", reason="You decided not to do this.")
    steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
    store.cancel_dependents(cur, steps, own["stepKey"])
    store.emit(cur, ideas, task, "approval", approvalId=None, stepKey=own["stepKey"], state="rejected")
    store.refresh(cur, ideas, task)


def expire(cur, ideas, task: dict, approval: dict) -> None:
    """An approval past its expiry: expired (system), its step failed/approval_expired, dependents cancelled."""
    store.close_approval(cur, approval, "expired", surface="system")
    steps = store.load_steps(cur, task["workspaceId"], task["taskId"], lock=True)
    own = next((s for s in steps if s["stepId"] == approval["stepId"]), None)
    if own is not None and own["state"] == "awaiting_approval":
        store.set_step(cur, own, state="failed", reason_code="approval_expired", reason="Nobody decided in time, so nothing was done.")
        store.cancel_dependents(cur, steps, own["stepKey"])
    store.emit(cur, ideas, task, "approval", approvalId=approval["approvalId"], stepKey=own["stepKey"] if own else None, state="expired")
    store.refresh(cur, ideas, task)
    store.log_event("approval_expired", taskId=task["taskId"], approvalId=approval["approvalId"])


def _has_checkpoint(runtime, workspace_id, task_id) -> bool:
    from . import checkpoints
    with store.service_tx(runtime.service, workspace_id) as cur:
        return checkpoints.available(cur, workspace_id, task_id) is not None


def _resolve_proposal(runtime, workspace_id, token, ctx: dict, decision, digest, decision_key, surface, *, zone=None) -> dict:
    """A legacy proposal decided on the native route: the existing apply/dismiss path (site agent checks, re-read verified),
    then the same record and resume rule as every other surface."""
    from .. import approvals as legacy
    approval = ctx["approval"]
    decided = legacy.decide(runtime.service, workspace_id, token, conversation_id=approval["conversationId"], message_id=approval["messageId"],
                            proposal_id=approval["proposalId"], digest=digest, decision="apply" if decision == "approve" else "dismiss", zone=zone)
    record = record_proposal_decision(runtime, workspace_id, token, approval["proposalId"], decided, wants="apply" if decision == "approve" else "dismiss",
                                      surface=surface, decision_key=decision_key)
    runtime._resolve_task_steps(workspace_id, token, approval["conversationId"], approval["proposalId"],
                                decided["outcome"] if decision == "approve" else "dismissed", verified=decided["verified"])
    if decided.get("outcome") == "applied" and decided.get("verified"):
        continuation = continue_after_decision(runtime, workspace_id, token, approval["taskId"], decision_key)
        record["resumed"] = continuation["resumed"]
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        from . import views
        task = store.load_task(cur, workspace_id, approval["taskId"])
        task_view = views.task_for_decider(cur, task, principal, runtime.service.ideas._member(row))
    return {"approvalId": approval["approvalId"], "state": record.get("state"), "outcome": decided["outcome"], "verified": decided["verified"],
            "checks": [{"name": c.get("what"), "ok": bool(c.get("verified"))} for c in decided.get("checks") or []], "task": task_view,
            "resumed": record.get("resumed", "none"), "speakableSummary": "Done, and I checked it in your workspace." if decided["outcome"] == "applied" and decided["verified"] else
            "Okay, I left it. Nothing was changed." if decision == "reject" else "It wasn't fully confirmed. Please check it."}


def record_proposal_decision(runtime, workspace_id, token, proposal_id, decided: dict, *, wants: str, surface: str, decision_key: str | None = None) -> dict:
    """After the legacy apply/dismiss path decided a proposal (any surface): record it on the engine row (if a task step waits on
    it), and say who continues. Returns {approvalId, state, resumed, creator}. Never raises for bookkeeping."""
    from . import checkpoints
    service, ideas = runtime.service, runtime.service.ideas
    try:
        with service.repository.transaction(token, workspace_id) as (cur, _row, principal):
            approval = store.approval_by_proposal(cur, workspace_id, proposal_id)
            if approval is None:
                approval = _wrap_for_waiting_step(cur, ideas, workspace_id, proposal_id)
            if approval is None:
                return {"resumed": "none", "creator": None}
            task = store.lock_task(cur, ideas, workspace_id, approval["taskId"])
            approval = store.load_approval(cur, workspace_id, approval["approvalId"], lock=True)
            if approval["state"] == "pending":
                outcome = decided.get("outcome")
                state = "consumed" if outcome == "applied" else "rejected" if wants == "dismiss" else None
                closed_surface = surface if (surface not in ("text", "voice") or approval["proposalType"] in model.LEGACY_PROPOSAL_TYPES) else "panel"
                if state is not None:
                    store.close_approval(cur, approval, state, surface=closed_surface, decided_by=principal, decision_key=decision_key,
                                         outcome={"state": state, "outcome": outcome, "verified": bool(decided.get("verified"))})
                elif outcome in ("expired", "superseded", "failed"):
                    store.close_approval(cur, approval, "expired" if outcome == "expired" else "superseded", surface="system", outcome={"outcome": outcome})
            creator = task["createdBy"] == principal
            resumed = "none"
            if decided.get("outcome") == "applied" and checkpoints.available(cur, workspace_id, task["taskId"]) is not None:
                if creator and surface in ("text", "voice"):
                    resumed = "inline"            # _decide_turn resumes it in this request (the creator's own)
                else:
                    checkpoints.needs_continue(cur, ideas, task)
                    resumed = "needs_continue" if creator else "none"
            store.refresh(cur, ideas, task)
            return {"approvalId": approval["approvalId"], "state": approval["state"], "resumed": resumed, "creator": task["createdBy"]}
    except AlphaError:
        raise
    except Exception as error:  # noqa: BLE001 — the decision itself already happened on the legacy path
        store.log_event("approval_record_failed", errorClass=type(error).__name__)
        return {"resumed": "none", "creator": None}


def _wrap_for_waiting_step(cur, ideas, workspace_id, proposal_id):
    """The engine task whose step waits on this proposal (by the legacy plan's own record), wrapped now (lazy X1)."""
    from .. import approvals as legacy
    cur.execute("SELECT t.id::text FROM public.pr_agent_tasks t JOIN public.pr_agent_runs r ON r.id=t.id WHERE t.workspace_id=%s "
                "AND r.artifact->'task'->'steps' @> %s::jsonb ORDER BY t.created_at DESC LIMIT 1",
                (workspace_id, '[{"approvals": ["' + str(proposal_id).replace('"', '') + '"]}]'))
    row = cur.fetchone()
    if not row:
        return None
    task = store.load_task(cur, workspace_id, row[0])
    cur.execute("SELECT artifact->'task'->'steps' FROM public.pr_agent_runs WHERE id::text=%s", (task["taskId"],))
    legacy_steps = cur.fetchone()[0] or []
    key = next((s.get("id") for s in legacy_steps if isinstance(s, dict) and proposal_id in (s.get("approvals") or [])), None)
    step = store.load_step(cur, workspace_id, task["taskId"], key) if key else None
    if step is None:
        return None
    item = legacy.find(cur, workspace_id, task["conversationId"], proposal_id)
    return ensure_proposal_approval(cur, ideas, task, step, item, just_decided=True) if item else None


def continue_after_decision(runtime, workspace_id, token, task_id, key, *, seconds_left=240):
    """All native surfaces share the creator-only continuation rule.

    The checkpoint claim is atomic; replays and other members cannot reserve or
    run a second continuation. A short request leaves the visible Continue action.
    """
    from . import checkpoints, actions
    with runtime.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
        task = store.lock_task(cur, runtime.service.ideas, workspace_id, task_id)
        if task is None or task["createdBy"] != principal:
            return {"resumed": "none"}
        checkpoint = checkpoints.available(cur, workspace_id, task_id)
        if checkpoint is None:
            return {"resumed": "none"}
        checkpoints.needs_continue(cur, runtime.service.ideas, task)
        store.refresh(cur, runtime.service.ideas, task)
    if seconds_left < 215:
        return {"resumed": "needs_continue"}
    return actions._resume(runtime, workspace_id, token, task, checkpoint, "approval:" + model.sha256(key)[:64])


def request_from_context(ctx, capability, args, decision):
    """CF2 E8 adapter: suspend a concrete, creator-owned call before execution."""
    from . import flags, targets
    from .. import task_state
    if not flags.enabled_for(ctx.workspace_id, ctx.config):
        return None
    name = capability.name
    clean = {k:v for k,v in args.items() if k != 'stepId'}
    refs = targets.planned_refs(ctx, clean)
    with ctx.workspace() as (cur, _row, principal, _member, _state):
        task = store.lock_task(cur,ctx.service.ideas,ctx.workspace_id,ctx.task.task_id) if ctx.task else None
        if task is None:
            task,_ = store.create_task(cur,ctx.service.ideas,workspace_id=ctx.workspace_id,conversation_id=ctx.conversation_id,created_by=principal,
                                      origin='chat',title='Confirm Rafii action',request_key='approval:'+ctx.trace_id,
                                      payload={'capability':name,'inputs':clean},steps=[{'label':'Confirm action','kind':'model'}],trace_id=ctx.trace_id)
        if task['createdBy'] != principal or not targets.all_present(cur,ctx.workspace_id,refs):
            raise errors.error('task_forbidden')
        key=args.get('stepId')
        if key:
            own=store.load_step(cur,ctx.workspace_id,task['taskId'],key)
            if own is None:
                raise errors.error('step_unknown')
        else:
            steps=store.load_steps(cur,ctx.workspace_id,task['taskId'])
            own=next((s for s in steps if s['kind']=='model' and s['state'] in ('queued','running')),None)
            if own is None:
                store.add_steps(cur,task,[{'label':'Confirm action','kind':'model'}])
                own=store.load_steps(cur,ctx.workspace_id,task['taskId'])[-1]
        subject={**own,'kind':'tool','capabilityId':name,'riskClass':capability.risk,'inputs':clean,
                 'inputDigest':model.input_digest(name,clean),'targetRefs':refs}
        digest=model.approval_digest(name,subject['inputDigest'],refs,capability.risk if capability.risk in ('R1','R2','R3') else 'R1',int(subject['generation']))
        prior=next((a for a in store.approvals_for(cur,ctx.workspace_id,task['taskId']) if a['stepId']==own['stepId'] and a['state']=='pending' and a['digest']==digest),None)
        if prior is None:
            verdict=authz_seam.StepVerdict('approve','agent_action',None,decision.reason,decision.token,
                                          capability.permission,'task_owner',False)
            aid=request_approval(cur,ctx.service.ideas,task,subject,verdict,trace_id=ctx.trace_id)
            prior=store.load_approval(cur,ctx.workspace_id,aid)
        store.refresh(cur,ctx.service.ideas,task)
        ctx.task=task_state.load(cur,ctx.workspace_id,task['taskId'])
        return {k:prior[k] for k in ('approvalId','summary','expiresAt')}


def install():
    """Install the actual E8 callback. Readiness remains an integration decision."""
    try:
        from .. import authz
    except ModuleNotFoundError as error:
        if error.name != 'postriff_phase2.agent_runtime_v2.authz':
            raise
        return False
    except ImportError:
        # The pre-CF2 package has no authz module.
        from importlib.util import find_spec
        if find_spec('postriff_phase2.agent_runtime_v2.authz') is not None:
            raise
        return False
    authz.register_approval_requester(request_from_context)
    resolver = getattr(authz, "register_approval_actor_resolver", None)
    if resolver:
        resolver(resolve_bound_actor)
        authz.ENFORCEMENT_POINTS.add("E8")
    return True


def authority_record(approval):
    """The canonical, content-free view consumed by CF2's pure decision function."""
    from .. import capability_registry
    capability=capability_registry.for_tool(approval['capabilityId'])
    return {'approvalId':approval['approvalId'],'capabilityId':capability.capability_id,'digest':approval['digest'],
            'state':approval['state'],'requestedFor':approval['requestedFor'],'expiresAt':approval['expiresAt'],'consumedAt':approval['consumedAt']}


def resolve_bound_actor(cur, ctx, capability, args, now):
    """CF2 E1/E2: a consumed approval belongs only to its still-live server attempt.

    Consumption excludes other claims. This projection lets that one claim finish
    while every work transaction still rechecks current grants and its live lease.
    No request-supplied evidence is accepted.
    """
    b=getattr(ctx,'step_binding',None)
    if not isinstance(b,dict) or not b.get('approvalId'):
        return None
    if b.get('workspaceId') != ctx.workspace_id or b.get('principal') != ctx.principal:
        return None
    name=capability.name
    clean={k:v for k,v in (args or {}).items() if k != 'stepId'}
    approval=store.load_approval(cur,ctx.workspace_id,b['approvalId'])
    if (not approval or approval['taskId'] != b.get('taskId') or approval['requestedFor'] != ctx.principal
            or approval['capabilityId'] != name or approval['inputDigest'] != model.input_digest(name,clean)
            or approval['state'] != 'consumed' or approval['expiresAt'] <= now):
        return None
    cur.execute("SELECT a.generation,s.generation,a.started_at<=p.consumed_at FROM public.pr_agent_step_attempts a "
                "JOIN public.pr_agent_steps s ON s.id=a.step_id JOIN public.pr_agent_approvals p ON p.id::text=%s "
                "WHERE a.id::text=%s AND a.task_id::text=%s AND a.step_id::text=%s AND a.workspace_id=%s AND a.actor=%s "
                "AND a.state='running' AND a.lease_owner=%s AND a.lease_expires_at>now()",
                (b['approvalId'],b.get('attemptId'),b.get('taskId'),b.get('stepId'),ctx.workspace_id,ctx.principal,b.get('leaseOwner')))
    row=cur.fetchone()
    if not row or row[0] != approval['generation'] or row[1] != row[0] or not row[2]:
        return None
    record=authority_record(approval)
    record.update(state='approved',consumedAt=None)
    return authz_seam.Actor('approval',ctx.principal,'',{'approvalId':approval['approvalId'],'approval':record,'digest':approval['digest']})


def execute_approved_model(runtime,workspace_id,token,task,approval,*,seconds_left=240):
    """An owner decision can run exactly the stored approved call without another model."""
    from .. import domain_tools,task_state,tool_adapter
    from ..context import RafiiRunContext
    domain_tools.ensure_registered()
    with runtime.service.repository.transaction(token,workspace_id) as (cur,row,principal):
        own,gated=_gated_step(cur,task,approval)
        current=store.load_approval(cur,workspace_id,approval['approvalId'])
        if own['kind'] != 'model' or principal != task['createdBy'] or not current or current['state'] != 'approved' or approval['kind']=='proposal':
            return None
        tool=tool_adapter.REGISTRY.get(approval['capabilityId'])
        if tool is None:
            return None
        plan=task_state.load(cur,workspace_id,task['taskId'])
        member=runtime.service.ideas._member(row)
    ctx=RafiiRunContext(runtime.service,workspace_id,token,principal,member,task['conversationId'],executor_trace(),task=plan,config=runtime.cfg)
    ctx.deadline=time.monotonic()+max(0,seconds_left)
    for ref in approval['targetRefs']:
        ctx.ledger.reference(ref['type'],ref['id'])
    from .model_calls import dispatch
    result=dispatch(ctx,tool,{**(approval['inputs'] or {}),'stepId':own['stepKey']})
    with store.service_tx(runtime.service,workspace_id) as cur:
        current=store.load_step(cur,workspace_id,task['taskId'],own['stepKey'])
        if result.get('verified') and result.get('ok', True) and current['state'] == 'running':
            store.set_step(cur,current,state='completed',verified=True,reason_code=None,reason=None)
            store.refresh(cur,runtime.service.ideas,store.load_task(cur,workspace_id,task['taskId']))
        state=current['state']
    return {'stepKey':own['stepKey'],'state':state,'verified':bool(result.get('verified'))}


def executor_trace():
    from .executor import new_trace
    return new_trace()
