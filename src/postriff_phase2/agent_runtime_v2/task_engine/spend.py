"""Task-scoped ledger attribution and conservative ceilings, using the existing ledger.

Only a server-created step binding can install this proxy. Reservations retain the
normal ledger's role, price, credits and provider limits. Unknown spend is held.
"""
from __future__ import annotations
import copy
from postriff_alpha.domain import AlphaError
from . import store


class TaskLedger:
    def __init__(self, ledger, binding):
        self._ledger, self.binding = ledger, binding

    def __getattr__(self, name):
        return getattr(self._ledger, name)

    def reserve(self, cur, workspace_id, member_id, dimension, estimated_usd_micro, idempotency_key, **kwargs):
        b = self.binding
        if workspace_id != b["workspaceId"] or str(member_id) != b["principal"]:
            raise AlphaError("Task usage identity changed.", 403, code="agent_permission_revoked")
        cur.execute("SELECT budget_ceiling_usd_micro FROM public.pr_agent_tasks WHERE id::text=%s AND workspace_id=%s FOR UPDATE",
                    (b["taskId"], workspace_id))
        row = cur.fetchone()
        if row is None:
            raise AlphaError("Task unavailable.", 404, code="task_unavailable")
        ceiling = row[0]
        # Each reservation is counted once at its terminal actual cost, or at its
        # conservative estimate while open/unknown. Never count an unknown as zero.
        cur.execute("SELECT coalesce(sum(coalesce(s.actual_usd_micro,CASE WHEN s.cost_state='released' THEN 0 ELSE r.estimated_usd_micro END)),0) "
                    "FROM public.pr_usage_ledger r LEFT JOIN LATERAL (SELECT actual_usd_micro,cost_state FROM public.pr_usage_ledger "
                    "WHERE workspace_id=r.workspace_id AND reservation_id=r.id AND kind='settle' "
                    "ORDER BY CASE WHEN cost_state IN ('actual','released') THEN 0 ELSE 1 END,at DESC LIMIT 1) s ON true "
                    "WHERE r.workspace_id=%s AND r.run_id=%s AND r.kind='reserve'", (workspace_id, b["taskId"]))
        committed = int(cur.fetchone()[0])
        key = b["effectKey"] + ":a" + str(b["attemptNo"])
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
        duplicate = cur.fetchone() is not None
        if not duplicate and ceiling is not None and committed + estimated_usd_micro > int(ceiling):
            raise AlphaError("This task needs a higher spending limit before it can continue.", 403, code="budget_ceiling")
        meta = {**(kwargs.pop("meta", None) or {}), "traceId": b["traceId"], "taskId": b["taskId"], "stepKey": b["stepKey"]}
        kwargs.update(run_id=b["taskId"], job_id=b["attemptId"], meta=meta)
        reservation = self._ledger.reserve(cur, workspace_id, member_id, dimension, estimated_usd_micro, key, **kwargs)
        cur.execute("UPDATE public.pr_agent_step_attempts SET reservation_id=%s,cost_state='estimated' WHERE id::text=%s AND state='running'",
                    (reservation["reservationId"], b["attemptId"]))
        return reservation

    def settle(self, cur, workspace_id, reservation_id, outcome, actual_usd_micro=None, idempotency_key=None):
        result = self._ledger.settle(cur, workspace_id, reservation_id, outcome, actual_usd_micro, idempotency_key)
        b = self.binding
        cur.execute("UPDATE public.pr_agent_step_attempts SET cost_state=CASE WHEN %s THEN 'unknown' ELSE 'known' END "
                    "WHERE id::text=%s AND reservation_id=%s", (outcome == 'unknown' or actual_usd_micro is None, b["attemptId"], reservation_id))
        cur.execute("UPDATE public.pr_agent_tasks SET spent_usd_micro=(SELECT coalesce(sum(actual_usd_micro),0) FROM public.pr_usage_ledger "
                    "WHERE workspace_id=%s AND run_id=%s AND kind='settle' AND cost_state='actual'), "
                    "spend_unknown=EXISTS(SELECT 1 FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.run_id=%s AND r.kind='reserve' "
                    "AND NOT EXISTS(SELECT 1 FROM public.pr_usage_ledger s WHERE s.workspace_id=r.workspace_id AND s.reservation_id=r.id "
                    "AND s.cost_state IN ('actual','released'))) WHERE id::text=%s",
                    (workspace_id,b["taskId"],workspace_id,b["taskId"],b["taskId"]))
        return result


def bind_service(ctx):
    b = getattr(ctx, "step_binding", None)
    ledger = getattr(ctx.service, "ledger", None)
    if not b or not b.get("effectKey") or ledger is None:
        return
    service = copy.copy(ctx.service)
    service.ledger = TaskLedger(ledger, b)
    service.ideas = copy.copy(ctx.service.ideas)
    service.ideas.ledger = service.ledger
    ctx.service = service
