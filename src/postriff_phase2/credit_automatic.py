"""Automatic credit approval for a person's own Rafii turn (POSTRIFF_CREDIT_AUTO_LIMIT_CREDITS).

A Rafii turn can hold credits more than once: the answer and then its generated view and that view's edits. Like a phone
call's approved limit (phone/billing.manager_approval), every hold on the same run counts against one automatic limit:
settled holds at what they used, open or unknown holds at their full maximum. A step resumed after an approval runs as a
new run (its own request, its own limit). Reached only through AgentRuntimeService._reservation_approval, whose routes
require a signed-in session; scheduled work (the task engine's claim loop) and API tokens never get here.
"""
from .contracts import digest
from .credit_meter import millicredits
from .credit_wallet import automatic_limit
from .developer_usage import ai_usage_exempt


def run_approval(ledger, cur, workspace_id, principal, revision, cost, route, run_id):
    """(authority, extra reservation meta), or (None, {}) when the ledger should decide as before: limit off, no credit
    plan, an exempt developer account, or no run to attach the hold to."""
    book = getattr(ledger, 'credits', None)
    if automatic_limit() is None or book is None or not run_id or ai_usage_exempt(principal):
        return None, {}
    if not book.policy(cur, workspace_id):
        return None, {}
    cur.execute("SELECT r.meta->'credits', (SELECT s.meta->'credits' FROM public.pr_usage_ledger s WHERE s.workspace_id=r.workspace_id "
                "AND s.reservation_id=r.id AND s.cost_state IN ('actual','released') ORDER BY s.at DESC LIMIT 1) "
                "FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' AND r.run_id::text=%s AND r.meta ? 'credits'",
                (workspace_id, str(run_id)))
    committed = sum((settled['used'] if isinstance(settled, dict) else reserved['maximum'])
                    for reserved, settled in cur.fetchall() if isinstance(reserved, dict))
    model, provider = getattr(route, 'model', None) or '', getattr(route, 'provider', None) or ''
    binding = digest({'operation': 'automatic-agent-turn', 'runId': str(run_id), 'cost': cost, 'committed': committed,
                      'model': model, 'provider': provider, 'revision': revision})
    authority = book.automatic_quote(cur, workspace_id, principal, revision, binding, model, provider, millicredits(cost), committed=committed)
    return authority, {'creditApproval': 'automatic'}
