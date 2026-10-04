"""Revalidate an existing managed hold before each physical paid attempt.

This does not authorize new spending: the caller already obtained a quote and
committed its reservation. No database lock survives a provider request.
"""
from postriff_alpha.domain import AlphaError
from .billing import ai_paused, active_budget_policy
from .credit_meter import millicredits


def unavailable(message='This task funding changed. Review the credit limit again.', status=409):
    return AlphaError(message, status, code='credit_funding_changed')


def guard_credit_call(ledger, connection_factory, workspace_id, reservation_id, *,
                      next_usd_micro, spent_usd_micro, unknown=False, model=None, provider=None):
    if unknown:
        raise unavailable('Reconcile the pending usage before another paid attempt.')
    if (type(next_usd_micro) is not int or type(spent_usd_micro) is not int
            or min(next_usd_micro, spent_usd_micro) < 0
            or next_usd_micro + spent_usd_micro > 10**15):
        raise unavailable('The next paid attempt has no bounded price basis.', 503)
    if ai_paused():
        raise unavailable('Paid AI is paused. No further request was sent.', 503)
    with connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
        if cur.fetchone() is None:
            raise unavailable()
        ledger.ensure_entitlement(cur, workspace_id, None)
        book = ledger.credits
        policy = book.policy(cur, workspace_id) if book else None
        cur.execute("SELECT estimated_usd_micro,model,provider,meta,run_id::text FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve'", (workspace_id, reservation_id))
        original = cur.fetchone()
        credit = original[3].get('credits') if original else None
        if (not policy or not isinstance(credit, dict) or credit.get('policy') != policy
                or (model is not None and model != original[1])
                or (provider is not None and provider != original[2])):
            raise unavailable()
        total = next_usd_micro + spent_usd_micro
        maximum = credit.get('maximum')
        if (type(maximum) is not int or total > original[0] or millicredits(total) > maximum):
            raise unavailable('The next attempt exceeds the approved total. Review a fresh limit.', 402)
        current_budget = active_budget_policy()
        if current_budget and total > current_budget['requestMax']:
            raise unavailable('The operator tightened the request limit.', 402)
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release') LIMIT 1", (workspace_id, reservation_id))
        if cur.fetchone():
            raise unavailable('This attempt is terminal or its usage is pending.')
        run_id = original[4]
        if run_id:
            cur.execute('SELECT status FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s UNION ALL SELECT status FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND id::text=%s', (workspace_id, run_id, workspace_id, run_id))
            runs = cur.fetchall()
            if len(runs) != 1 or runs[0][0] != 'running':
                raise unavailable('This task is no longer active.')
        scopes = original[3].get('budgetScopes')
        if not isinstance(scopes, list) or not scopes or any(not isinstance(scope, str) for scope in scopes):
            raise unavailable('The platform funding approval is unavailable.', 503)
        for scope in sorted(scopes):
            cur.execute('SELECT status,stop_usd_micro,spent_usd_micro,reserved_usd_micro FROM public.pr_budgets WHERE scope=%s FOR UPDATE', (scope,))
            budget = cur.fetchone()
            if (not budget or budget[0] != 'approved' or type(budget[1]) is not int
                    or budget[1] <= 0 or budget[3] < original[0] or budget[2] + budget[3] > budget[1]):
                raise unavailable('The platform budget no longer covers this task.', 402)
