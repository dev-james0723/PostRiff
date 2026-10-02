"""Effective entitlement admission for acquisitions without a qualified credit bridge.

This module grants no funding. Saved/manual operations do not call this guard.
"""
from postriff_alpha.domain import AlphaError
from ..credit_meter import V2_POLICY_VERSION


def funding_mode(cur, workspace_id):
    cur.execute("SELECT p.plan,p.entitlements->>'creditPolicy' FROM public.pr_entitlements e "
                "JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id WHERE e.workspace_id=%s", (workspace_id,))
    row = cur.fetchone()
    if row and row[0] == 'free': return 'free'
    if row and row[1] == V2_POLICY_VERSION: return 'managed_credits'
    return 'legacy'


def require_qualified_entry(cur, workspace_id, *, unpriced=True):
    if unpriced and funding_mode(cur, workspace_id) != 'legacy':
        raise AlphaError('This acquisition is unavailable until its provider cost and credit funding are qualified. '
                         'Saved results and manual work remain available.', 503, code='growth_credit_bridge_unavailable')
