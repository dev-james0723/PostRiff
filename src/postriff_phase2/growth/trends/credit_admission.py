"""Internal before-I/O boundary for trends without a qualified customer bridge.

Derive current lifecycle and read server entitlements on every attempt. Experimental
source/model budgets, client plan labels and quota exemptions are not funding
authority. Stored processing does not call this module's dispatch guards.
"""
from postriff_alpha.domain import AlphaError
from ...credit_meter import V2_POLICY_VERSION
from ..credit_admission import refresh_lifecycle
from .contracts import ContractError, scope, uuid
from .store import row, rows

UNAVAILABLE = 'growth_credit_bridge_unavailable'


class DispatchFundingUnavailable(ContractError):
    """Do not let model adapters reinterpret a pre-I/O denial as paid failure."""
    status = 503

    def __init__(self):
        super().__init__(UNAVAILABLE)


def unavailable():
    return AlphaError('This trend route has no qualified credit funding bridge. No further paid request was sent.',
                      503, code=UNAVAILABLE)


def funding_mode(cur, workspace_id):
    cur.execute("""/* trends:funding */ SELECT p.plan,p.entitlements->>'creditPolicy' AS credit_policy
        FROM public.pr_entitlements e JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id
        WHERE e.workspace_id=%s FOR SHARE OF e,p""", (uuid(workspace_id),))
    current = row(cur)
    # Match Ledger.growth_mode's historical no-row branch. Missing terms do not
    # identify v2; existing source/consent/operator gates still govern legacy.
    # Never infer from prices, blobs, experiments or an AI-usage exemption.
    if not current:
        return 'legacy'
    if current['plan'] == 'free':
        return 'free'
    if current['credit_policy'] == V2_POLICY_VERSION:
        return 'managed_credits'
    return 'legacy'


def require_qualified_entry(cur, workspace_id, *, store=None):
    refresh_lifecycle(cur, workspace_id, getattr(store, 'hosted', None))
    if funding_mode(cur, workspace_id) != 'legacy':
        raise unavailable()


def require_dispatch(store, workspace_id):
    """The guard transaction commits/releases its row locks BEFORE external I/O."""
    with store.transaction() as cur:
        require_qualified_entry(cur, workspace_id, store=store)


def require_model_dispatch(store, workspace_id):
    try:
        require_dispatch(store, workspace_id)
    except AlphaError as exc:
        if exc.code == UNAVAILABLE:
            raise DispatchFundingUnavailable() from None
        raise


def require_provider_dispatch(store, scope_key, capability, amount):
    # Only this existing pinned server capability establishes unmetered traffic.
    # An arbitrary zero reservation or a copied billable-unit label does not.
    from .providers.bluesky import CAPABILITY
    if capability == CAPABILITY and type(amount) is int and amount == 0:
        return
    scope_key = scope(scope_key)
    with store.transaction() as cur:
        if scope_key.startswith('workspace:'):
            require_qualified_entry(cur, scope_key[10:], store=store)
            return
        cur.execute("""/* trends:beneficiaries */ SELECT workspace_id::text AS workspace_id
            FROM public.pr_trend_entitlements WHERE scope_key=%s AND revoked_at IS NULL
            AND expires_at>clock_timestamp() AND 'retrieve'=ANY(operations)
            ORDER BY workspace_id LIMIT 1001 FOR SHARE""", (scope_key,))
        beneficiaries = rows(cur)
        if not beneficiaries or len(beneficiaries) > 1000:
            raise unavailable()
        # Shared acquisition cannot silently allocate costs to v2 customers or
        # subsidize them through a legacy beneficiary's experimental budget.
        for beneficiary in beneficiaries:
            require_qualified_entry(cur, beneficiary['workspace_id'], store=store)
