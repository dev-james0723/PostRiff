"""Effective entitlement admission for acquisitions without a qualified credit bridge.

This module grants no funding. Saved/manual operations do not call this guard.
"""
import math

from postriff_alpha.domain import AlphaError
from ..credit_meter import V2_POLICY_VERSION
from ..free_lifecycle import lifecycle


def unavailable():
    return AlphaError('This acquisition is unavailable until its provider cost and credit funding are qualified. '
                      'Saved results and manual work remain available.', 503, code='growth_credit_bridge_unavailable')


def refresh_lifecycle(cur, workspace_id, hosted):
    """Use bound server authority under the workspace lock, before every paid attempt.

    Missing host configuration cannot classify a stored trial as funded legacy.
    The caller releases this transaction before any external I/O.
    """
    enabled = getattr(getattr(hosted, 'billing', None), 'pricing_v2_enabled', None)
    clock = getattr(hosted, 'clock', None)
    if type(enabled) is not bool or not callable(clock):
        raise unavailable()
    cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
    if not cur.fetchone():
        raise unavailable()
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise unavailable()
    # Lifecycle reads positional subscription columns, including two epoch
    # expressions. Keep them distinct for a native dictionary cursor, and
    # restore its original factory for the caller's following funding reads.
    if hasattr(cur, 'row_factory'):
        from psycopg.rows import tuple_row
        previous_factory = cur.row_factory
        try:
            cur.row_factory = tuple_row
            lifecycle(cur, workspace_id, now, pricing_v2_enabled=enabled)
        finally:
            cur.row_factory = previous_factory
    else:
        lifecycle(cur, workspace_id, now, pricing_v2_enabled=enabled)


def funding_mode(cur, workspace_id, *, hosted=None):
    # Unbound reads are diagnostics only; paid admission always refreshes below.
    if hosted is not None:
        refresh_lifecycle(cur, workspace_id, hosted)
    cur.execute("SELECT p.plan,p.entitlements->>'creditPolicy' FROM public.pr_entitlements e "
                "JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id WHERE e.workspace_id=%s", (workspace_id,))
    row = cur.fetchone()
    if row and row[0] == 'free': return 'free'
    if row and row[1] == V2_POLICY_VERSION: return 'managed_credits'
    return 'legacy'


def require_qualified_entry(cur, workspace_id, *, unpriced=True, hosted=None):
    if not unpriced:
        return
    refresh_lifecycle(cur, workspace_id, hosted)
    if funding_mode(cur, workspace_id) != 'legacy':
        raise unavailable()
