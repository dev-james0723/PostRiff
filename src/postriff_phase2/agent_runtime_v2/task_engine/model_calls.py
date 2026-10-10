"""Lease and effect keys for tools inside the owner's legacy model step.

The Manager still controls its plan text. Every effect has a server-bound key,
current authorization and one attempt; SDK checkpoint replay cannot repeat it.
"""
from __future__ import annotations
import copy
import time
from postriff_alpha.domain import AlphaError
from . import authz_seam, errors, executor, model, store, targets


def dispatch(ctx, tool, args):
    from .. import capability_registry, task_state, tool_adapter
    capability = capability_registry.for_tool(tool.name)
    agent = executor.dispatch_agent(tool.name)
    clean = {k: v for k, v in args.items() if k != "stepId"}
    digest = model.input_digest(tool.name, clean)
    with ctx.workspace() as (cur, _row, principal, _member, _state):
        task = store.lock_task(cur, ctx.service.ideas, ctx.workspace_id, ctx.task.task_id)
        step = store.load_step(cur, ctx.workspace_id, task["taskId"], args["stepId"], lock=True)
        if task["createdBy"] != principal:
            raise errors.error("task_forbidden")
        key = model.effect_key(task["taskId"], step["stepKey"], step["generation"]) + ":" + model.sha256(tool.name + "|" + digest)[:16]
        receipt = store.receipt(cur, ctx.workspace_id, key, lock=True)
        if receipt and receipt["state"] == "done" and receipt["outcome"] == "applied" and receipt["inputDigest"] == digest:
            return {"ok": bool(receipt["verified"]), "verified": bool(receipt["verified"]), "replayed": True,
                    "changedRefs": (receipt["result"] or {}).get("changedRefs", []), "taskId": task["taskId"], "stepId": step["stepKey"]}
        if task["cancelRequestedAt"] is not None or step["state"] in model.TERMINAL_STATES:
            raise errors.error("task_terminal")
        all_steps = store.load_steps(cur, ctx.workspace_id, task["taskId"])
        if any(s["stepKey"] in step["dependsOn"] and s["state"] != "completed" for s in all_steps):
            raise errors.error("task_conflict")
        if task["attemptsLeft"] <= 0:
            raise errors.error("retry_budget_exhausted")
        refs = targets.planned_refs(ctx, clean, state=_state)
        if not targets.all_present(cur, ctx.workspace_id, refs):
            raise errors.error("task_conflict")
        remaining = ctx.remaining()
        if (240 if remaining is None else remaining) < capability.timeout_seconds + 30:
            store.set_step(cur,step,state="blocked",reason_code="needs_conversation",reason="Continue when there is time to finish this step.")
            store.refresh(cur,ctx.service.ideas,task)
            return {"ok":False,"needsUser":True,"code":"task_conflict"}
        subject = {**step, "kind": "tool", "capabilityId": tool.name, "inputs": clean, "inputDigest": digest, "effect": tool.spec.effect,
                   "riskClass": capability.risk, "targetRefs": refs, "effectKey": key,
                   "timeoutSeconds": int(capability.timeout_seconds)}
        actor = authz_seam.Actor("agent" if ctx.request_text else "continuation", principal, ctx.request_text)
        evidence = executor._approval_evidence(cur, task, subject)
        if evidence:
            actor = authz_seam.Actor("approval", principal, "", evidence)
        verdict = authz_seam.decide_for_step(cur, task, subject, actor=actor, now=ctx.now(), allowed_before=store.allowed_before(cur,ctx.workspace_id,task["taskId"]),config=ctx.config)
        if verdict.verdict in ("approve", "step_up"):
            from .approvals import request_approval
            request_approval(cur,ctx.service.ideas,task,subject,verdict,trace_id=ctx.trace_id)
            store.refresh(cur,ctx.service.ideas,task)
            ctx.task = task_state.load(cur,ctx.workspace_id,task["taskId"])
            return {"ok": False,"needsUser": True,"code": "needs_panel_confirmation"}
        if verdict.verdict != "allow":
            store.set_step(cur,step,state="blocked",reason_code=verdict.reason_code or "permission_missing")
            executor.revoke_for_step(cur,ctx.service.ideas,task,step,verdict)
            store.refresh(cur,ctx.service.ideas,task)
            return {"ok":False,"code":"agent_permission_revoked"}
        cur.execute("SELECT 1 FROM public.pr_agent_step_attempts WHERE step_id::text=%s AND state='running'",(step["stepId"],))
        if cur.fetchone():
            raise errors.error("task_conflict")
        attempt_no = executor._next_attempt_no(cur,step)
        owner = executor.lease_owner("inline")
        store.set_step(cur,step,state="running",attempts=step["attempts"]+1)
        cur.execute("UPDATE public.pr_agent_tasks SET attempts_left=attempts_left-1 WHERE id::text=%s",(task["taskId"],))
        aid = executor._insert_attempt(cur,task,subject,attempt_no,"inline",owner,verdict,ctx.trace_id,None,ctx.run_id)
        if tool.spec.effect != "READ":
            mode,_ = store.receipt_begin(cur,task,subject,aid,ctx.trace_id)
            if mode == "conflict":
                raise errors.error("idempotency_conflict")
        if evidence:
            executor.consume_approval(cur,evidence)
    bound = copy.copy(ctx)
    bound.step_binding = {"taskId":task["taskId"],"stepId":step["stepId"],"stepKey":step["stepKey"],"effectKey":key,
                          "attemptId":aid,"attemptNo":attempt_no,"leaseOwner":owner,"inputDigest":digest,"workspaceId":ctx.workspace_id,
                          "principal":ctx.principal,"traceId":ctx.trace_id,"modelCall":True,"capabilityId":tool.name,"riskClass":subject["riskClass"],"inputs":clean,"approvalId":(evidence or {}).get("approvalId")}
    def cancelled():
        from ... import leases
        if ctx.cancelled():
            return True
        with store.service_tx(ctx.service, ctx.workspace_id) as cur:
            current = store.load_task(cur, ctx.workspace_id, task["taskId"])
            current_step = store.load_step(cur, ctx.workspace_id, task["taskId"], step["stepKey"])
            return (current is None or current["cancelRequestedAt"] is not None or current_step["state"] in ("blocked", "cancelled")
                    or not leases.still_owned(cur, "pr_agent_step_attempts", aid, lease_owner=owner))
    bound.cancelled = cancelled
    from .spend import bind_service
    bind_service(bound)
    changed_start = len(ctx.ledger.changed)
    started = time.monotonic()
    nested_args = args if "stepId" in (tool.schema.get("properties") or {}) else clean
    result = tool_adapter.execute(bound,tool,nested_args,agent=agent)
    with store.service_tx(ctx.service,ctx.workspace_id) as cur:
        from ... import leases
        if not leases.still_owned(cur,"pr_agent_step_attempts",aid,lease_owner=owner):
            return {"ok":False,"code":"task_conflict","error":"This attempt no longer owns the step."}
        if result.get("code") == "budget_ceiling":
            from .approvals import request_approval
            executor._finish_attempt(cur,aid,"failed","budget","budget_ceiling")
            verdict = authz_seam.StepVerdict("approve","spend","budget","cost_limit",task["authzToken"])
            request_approval(cur,ctx.service.ideas,task,subject,verdict,trace_id=ctx.trace_id,spend_limit=result.get("requiredBudgetCeilingUsdMicro"))
            store.refresh(cur,ctx.service.ideas,task)
            ctx.task = task_state.load(cur,ctx.workspace_id,task["taskId"])
            return result
        ok = bool(result.get("ok",True)) and not result.get("needsUser")
        executor._finish_attempt(cur,aid,"succeeded" if ok else "failed",None if ok else executor._category(result,subject),result.get("code"),{"ms":round((time.monotonic()-started)*1000)})
        if tool.spec.effect != "READ" and ok:
            refs = [{"type":c.get("type"),"id":c.get("id"),"change":c.get("change")} for c in ctx.ledger.changed[changed_start:] if c.get("id")]
            store.receipt_done(cur,ctx.workspace_id,key,outcome="applied",verified=bool(result.get("verified",False)),result={"changedRefs":refs,"checks":result.get("checks") or []})
        current_step = store.load_step(cur,ctx.workspace_id,task["taskId"],step["stepKey"])
        if not ok and not result.get("needsUser"):
            category = executor._category(result,subject)
            outcome = leases.classify(category,retry_class="manual",attempts=1,max_attempts=1)
            store.set_step(cur,current_step,state=outcome.state,reason_code=outcome.reason_code,reason=model.clip(result.get("error"),300))
            if tool.spec.effect != "READ":
                store.receipt_done(cur,ctx.workspace_id,key,outcome="unknown" if category=="outcome_unknown" else "failed",verified=False,result={})
        elif ok and not result.get("verified",False) and tool.spec.effect != "READ":
            store.set_step(cur,current_step,state="failed",reason_code="outcome_unknown",verified=False,reason="The result could not be verified.")
        current = store.load_task(cur,ctx.workspace_id,task["taskId"])
        store.refresh(cur,ctx.service.ideas,current)
        ctx.task = task_state.load(cur,ctx.workspace_id,task["taskId"])
    return result
