"""Creator-owned, metered SDK continuation attempts (CF-3 §7.4)."""
from __future__ import annotations
import time
from . import authz_seam, executor, model, store
from .spend import TaskLedger
from ... import leases


def begin(runtime, workspace_id, token, task_id, run_id, trace_id):
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        task = store.lock_task(cur, runtime.service.ideas, workspace_id, task_id)
        member = runtime.service.ideas._member(row)
        if task is None or task['createdBy'] != principal or not member.allows('edit') or task['cancelRequestedAt'] is not None or task['attemptsLeft'] <= 0:
            return None
        steps = store.load_steps(cur, workspace_id, task_id, lock=True)
        if any(s['kind'] == 'continuation' and s['state'] in ('running', 'awaiting_approval') for s in steps):
            return None
        queued = next((s for s in steps if s['kind'] == 'continuation' and s['state'] == 'queued'), None)
        if queued:
            step = queued
            sid, key, effect = step['stepId'], step['stepKey'], step['effectKey']
        else:
            if len(steps) >= model.MAX_STEPS:
                return None
            key = 's' + str(len(steps) + 1)
            effect = model.effect_key(task_id, key, 1)
            cur.execute("INSERT INTO public.pr_agent_steps(task_id,workspace_id,step_key,label,kind,state,risk_class,effect,retry_class,max_attempts,timeout_seconds,effect_key,started_at) "
                        "VALUES(%s,%s,%s,'Continue the conversation','continuation','queued','R0','READ','manual',1,200,%s,now()) RETURNING id::text", (task_id,workspace_id,key,effect))
            sid = cur.fetchone()[0]
            step = store.load_step(cur,workspace_id,task_id,key)
        verdict = authz_seam.decide_for_step(cur,task,step,actor=authz_seam.Actor('continuation',principal),now=time.time(),config=runtime.cfg)
        if verdict.verdict != 'allow':
            store.set_step(cur,step,state='blocked',reason_code=verdict.reason_code or 'permission_missing')
            store.refresh(cur,runtime.service.ideas,task)
            return None
        owner=executor.lease_owner('inline')
        attempt_no = executor._next_attempt_no(cur, step)
        aid=executor._insert_attempt(cur,task,step,attempt_no,'inline',owner,verdict,trace_id,None,run_id)
        for approval in store.approvals_for(cur, workspace_id, task_id):
            if approval['stepId'] == sid and approval['kind'] == 'spend' and approval['state'] == 'approved':
                executor.consume_approval(cur, approval)
        cur.execute('UPDATE public.pr_agent_tasks SET attempts_left=attempts_left-1 WHERE id::text=%s',(task_id,))
        store.set_step(cur,step,state='running',attempts=step['attempts']+1)
        store.refresh(cur,runtime.service.ideas,task)
        binding={'workspaceId':workspace_id,'principal':principal,'taskId':task_id,'stepId':sid,'stepKey':key,'effectKey':effect,
                 'attemptId':aid,'attemptNo':attempt_no,'leaseOwner':owner,'traceId':trace_id}
    return binding,TaskLedger(runtime.service.ledger,binding)


def finish(runtime,binding,*,ok,code=None,spend_limit=None):
    with store.service_tx(runtime.service,binding['workspaceId']) as cur:
        if not leases.still_owned(cur,'pr_agent_step_attempts',binding['attemptId'],lease_owner=binding['leaseOwner']):
            return
        task=store.lock_task(cur,runtime.service.ideas,binding['workspaceId'],binding['taskId'])
        step=store.load_step(cur,binding['workspaceId'],binding['taskId'],binding['stepKey'])
        executor._finish_attempt(cur,binding['attemptId'],'succeeded' if ok else 'failed',None if ok else 'budget' if code=='budget_ceiling' else 'permanent',code)
        if code == 'budget_ceiling' and type(spend_limit) is int and spend_limit > 0:
            from .approvals import request_approval
            verdict = authz_seam.StepVerdict('approve', 'spend', 'budget', 'cost_limit', task['authzToken'])
            # This server-only budget subject is not a tool capability or authority
            # to run a tool. Every resumed model tool still passes its own CF2 gate.
            inputs = {'taskId': task['taskId'], 'stepKey': step['stepKey']}
            subject = {**step, 'capabilityId': 'task.continuation', 'inputs': inputs,
                       'inputDigest': model.input_digest('task.continuation', inputs)}
            request_approval(cur, runtime.service.ideas, task, step, verdict, gated=subject,
                             trace_id=binding['traceId'], spend_limit=spend_limit)
        else:
            store.set_step(cur,step,state='completed' if ok else 'blocked' if code=='budget_ceiling' else 'failed',verified=ok,reason_code='budget' if code=='budget_ceiling' else None)
        store.refresh(cur,runtime.service.ideas,task)
