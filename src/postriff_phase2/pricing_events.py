"""Private Task11 observations in migration 025's service-only product event store.

No client payloads, payment identifiers, provider details or content are properties.
Sources are hashed with their workspace and kind because event/dedupe is GLOBAL.
Callers own the transaction: observations commit with the authoritative mutation.
No sale, budget or provider activation is performed here.
"""
import hashlib
import json
import math
from uuid import UUID

from .credit_meter import SUPPORTED_POLICY_VERSIONS

MAX = 2**63 - 1
VARIANTS = frozenset(('creator-49-v1', 'creator-59-v1', 'creator-79-v1'))
CANCELLATION_REASONS = frozenset(('too_expensive', 'missing_features', 'switched_service',
    'unused', 'customer_service', 'too_complex', 'low_quality', 'other',
    'cancellation_requested', 'payment_failed', 'payment_disputed'))
KINDS = frozenset(('price_assignment', 'checkout_session', 'billing_event', 'invoice',
                   'usage_ledger', 'credit_lot', 'agent_run', 'weekly_pack', 'model_usage'))
ENUMS = {
    'package': frozenset(('creator', 'starter', 'studio', 'free', 'legacy')),
    'priceVariant': VARIANTS | {None},
    'policy': frozenset(SUPPORTED_POLICY_VERSIONS) | {None},
    'cohort': frozenset(('paid_invoice', 'legacy_paid_invoice')),
    'currency': frozenset(('usd', 'hkd', 'eur', 'gbp', 'cad', 'aud', 'other')),
    'state': frozenset(('unknown', 'completed', 'failed')),
    'funding': frozenset(('free_preview', 'failed_operation', 'platform', 'managed', 'legacy', 'unclassified')),
    'grantSource': frozenset(('subscription', 'purchased', 'other')),
    'metric': frozenset(('cumulative_lot_projection', 'physical_attempt_detail')),
    'cancellationReason': CANCELLATION_REASONS,
    'route': frozenset(('primary', 'fallback')),
    'costSource': frozenset(('gateway', 'table', 'unknown')),
}
NUMBERS = frozenset(('revenueCents', 'grantedMilliCredits', 'heldMilliCredits', 'usedMilliCredits',
    'releasedMilliCredits', 'absorbedMilliCredits', 'expiredMilliCredits', 'actualUsdMicro', 'variants'))
TIMES = frozenset(('effectiveExpiresAt', 'observedAt'))
PRICE = frozenset(('package', 'priceVariant'))
SCHEMAS = {
    'price.assigned': PRICE,
    'checkout.started': PRICE,
    'checkout.completed': PRICE,
    'subscription.paid': PRICE | {'revenueCents', 'currency', 'cohort'},
    'renewal.paid': PRICE | {'revenueCents', 'currency', 'cohort'},
    'subscription.cancelled': PRICE | {'cancellationReason'},
    'first_value.completed': frozenset(('variants',)),
    'weekly_pack.adopted': frozenset(),
    'credits.granted': frozenset(('grantedMilliCredits', 'policy', 'grantSource', 'effectiveExpiresAt')),
    'credits.held': frozenset(('heldMilliCredits', 'policy')),
    'credits.pending': frozenset(('heldMilliCredits', 'policy', 'state', 'actualUsdMicro')),
    'credits.settled': frozenset(('usedMilliCredits', 'releasedMilliCredits', 'policy', 'state', 'actualUsdMicro')),
    'credits.expired': frozenset(('expiredMilliCredits', 'heldMilliCredits', 'policy',
        'metric', 'lotReference', 'effectiveExpiresAt', 'observedAt')),
    'platform.cost': frozenset(('funding', 'state', 'actualUsdMicro')),
    'platform.absorbed': frozenset(('absorbedMilliCredits', 'actualUsdMicro', 'policy')),
    'growth.usage_recorded': frozenset(('actualUsdMicro', 'state', 'route', 'costSource', 'metric')),
}


def reference(workspace, kind, source):
    return hashlib.sha256(json.dumps([str(UUID(str(workspace))), kind, str(source)],
                                     separators=(',', ':')).encode()).hexdigest()


def emit(cur, workspace, event, kind, source, properties, occurred_at=None):
    if event not in SCHEMAS or kind not in KINDS or not source:
        raise ValueError('Unknown Task11 event/source.')
    if not isinstance(properties, dict) or set(properties) - SCHEMAS[event]:
        raise ValueError('Task11 properties must be allow-listed.')
    for key, value in properties.items():
        if key in ENUMS:
            if not isinstance(value, (str, type(None))) or value not in ENUMS[key]:
                raise ValueError('Unknown Task11 category.')
        elif key in NUMBERS:
            if value is None and key == 'actualUsdMicro':
                continue
            if type(value) is not int or not 0 <= value <= MAX:
                raise ValueError('Task11 amount out of bounds.')
        elif key in TIMES:
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX):
                raise ValueError('Task11 time out of bounds.')
        elif key == 'lotReference':
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Task11 lot reference must be hashed.')
        else:
            raise ValueError('Unvalidated Task11 property.')
    if occurred_at is not None and (type(occurred_at) not in (int, float) or not math.isfinite(occurred_at) or not 0 <= occurred_at <= MAX):
        raise ValueError('Invalid Task11 occurrence time.')
    workspace = str(UUID(str(workspace)))
    ref = reference(workspace, kind, source)
    # Older deployments may lack 025. A missing table is a read-only no-op, not a
    # caught SQL error that would poison the caller's financial transaction.
    cur.execute("SELECT to_regclass('public.pr_product_events') IS NOT NULL")
    row = cur.fetchone()
    if not row or not row[0]:
        return
    payload = dict(properties, sourceKind=kind, sourceReference=ref, schemaVersion=1)
    cur.execute("INSERT INTO public.pr_product_events(workspace_id,event,properties,dedupe_key,occurred_at) "
                "VALUES(%s,%s,%s::jsonb,%s,coalesce(to_timestamp(%s),now())) ON CONFLICT DO NOTHING",
                (workspace, event, json.dumps(payload, allow_nan=False), 'task11:' + ref, occurred_at))


def price_facts(terms, variant=None):
    package = {'creator-v1': 'creator', 'starter-v1': 'starter', 'studio-v2': 'studio', 'free-v1': 'free'}.get(terms, 'legacy')
    return {'package': package, 'priceVariant': variant if variant in VARIANTS else None}


def assigned(cur, workspace, variant, experiment):
    emit(cur, workspace, 'price.assigned', 'price_assignment', experiment,
         price_facts(variant['planTermsId'], variant['priceVariantId']))


def first_value(cur, workspace, run_id, variants):
    """First actually saved useful Ideas result, under the repository workspace lock."""
    if not variants:
        return
    cur.execute("SELECT to_regclass('public.pr_product_events') IS NOT NULL")
    row = cur.fetchone()
    if not row or not row[0]:
        return
    # Product events have a 400-day TTL. The existing append-only audit preserves
    # the first-value latch across that retention boundary, under the same lock.
    cur.execute("SELECT 1 FROM public.pr_audit_events WHERE workspace_id=%s AND kind='pricing.first_value_completed' LIMIT 1", (workspace,))
    if not cur.fetchone():
        emit(cur, workspace, 'first_value.completed', 'agent_run', run_id, {'variants': variants})
        cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,NULL,'pricing.first_value_completed',%s,%s::jsonb)",
                    (workspace, reference(workspace, 'agent_run', run_id), json.dumps({'variants': variants})))


def signed_billing(cur, event, provider):
    """Only call after verified reconciliation accepted the signed package facts.

    Invoice identity dedupes across event deliveries; revenue is signed amountPaid,
    including discounts, never a current catalog amount or assignment lookup.
    """
    if provider != 'stripe' or not event.get('workspaceId'):
        return
    workspace, kind = event['workspaceId'], event.get('stripeType')
    facts = price_facts(event.get('planTermsId'), event.get('priceVariantId'))
    if kind == 'checkout.session.completed':
        # Session identity is immutable even if Stripe redelivers with another event id.
        if event.get('checkoutSessionId'):
            emit(cur, workspace, 'checkout.completed', 'checkout_session', event['checkoutSessionId'], facts, event['createdAt'])
    if kind == 'invoice.paid' and event.get('invoicePaid') and event.get('invoiceId'):
        amount, currency = event.get('amountPaid'), event.get('currency')
        if type(amount) is not int or not 0 <= amount <= MAX or not isinstance(currency, str) or not currency:
            return
        facts.update(revenueCents=amount, currency=currency if currency in ENUMS['currency'] else 'other',
                     cohort='paid_invoice' if facts['package'] != 'legacy' else 'legacy_paid_invoice')
        emit(cur, workspace, 'subscription.paid', 'invoice', event['invoiceId'], facts, event['createdAt'])
        if event.get('billingReason') == 'subscription_cycle':
            emit(cur, workspace, 'renewal.paid', 'invoice', event['invoiceId'], facts, event['createdAt'])
    if event.get('type') == 'subscription.cancelled' or event.get('cancelAtPeriodEnd'):
        reason = event.get('cancellationReason')
        if reason in CANCELLATION_REASONS:
            emit(cur, workspace, 'subscription.cancelled', 'billing_event', event['id'],
                 dict(facts, cancellationReason=reason), event['createdAt'])


def settled(cur, workspace, source, outcome, actual, reserved, credit, meta):
    reserved, meta = reserved or {}, meta or {}
    policy = reserved.get('policy')
    policy = policy if policy in SUPPORTED_POLICY_VERSIONS else None
    if outcome == 'unknown':
        emit(cur, workspace, 'credits.pending', 'usage_ledger', source,
             {'heldMilliCredits': reserved.get('maximum', 0), 'policy': policy,
              'state': 'unknown', 'actualUsdMicro': None})
        return
    if credit:
        emit(cur, workspace, 'credits.settled', 'usage_ledger', source,
             {'usedMilliCredits': credit['used'], 'releasedMilliCredits': credit['released'],
              'policy': policy, 'state': outcome, 'actualUsdMicro': actual})
        if credit.get('absorbed'):
            # Difference in verified cost, not rounded credit value as dollars.
            paid_micro = credit['used'] * 1_000_000 // 300_000
            emit(cur, workspace, 'platform.absorbed', 'usage_ledger', source,
                 {'absorbedMilliCredits': credit['absorbed'], 'actualUsdMicro': max(0, actual - paid_micro), 'policy': policy})
    if meta.get('platformPreview') or meta.get('aiUsageExempt') or outcome == 'failed':
        funding = 'free_preview' if meta.get('platformPreview') else 'failed_operation' if outcome == 'failed' else 'platform'
        emit(cur, workspace, 'platform.cost', 'usage_ledger', source,
             {'funding': funding, 'state': outcome, 'actualUsdMicro': actual})


def observe_expiry(cur, workspace, rows, now):
    """Cumulative lot snapshots. Select latest per lotReference; NEVER sum snapshots.

    Held credits stay held across expiry. Later release/settlement produces a new
    source-linked projection, without modifying or inventing a ledger debit.
    """
    from .credit_wallet import project_credit_wallet
    wallet = project_credit_wallet(rows, now)
    grants = {r['id']: r['credits'] for r in rows if r['credits']['op'] == 'grant'}
    frontier = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for lot in wallet['lots']:
        expiry = lot['expiresAt']
        if expiry is None or expiry > now:
            continue
        c = grants[lot['grantId']]
        emit(cur, workspace, 'credits.expired', 'credit_lot', f"{lot['grantId']}:{expiry}:{frontier}",
             {'expiredMilliCredits': max(0, lot['milli'] - lot['reversed'] - lot['used'] - lot['held']),
              'heldMilliCredits': lot['held'], 'policy': c.get('policy') if c.get('policy') in SUPPORTED_POLICY_VERSIONS else None,
              'metric': 'cumulative_lot_projection', 'lotReference': reference(workspace, 'credit_lot', lot['grantId']),
              'effectiveExpiresAt': expiry, 'observedAt': now})


def growth_usage(cur, event, row_id):
    if not event.workspace_id:
        return
    # A physical attempt is detail, not a second task cost. Ledger settlement owns
    # managed/platform aggregates, including usage arriving after content rejection.
    emit(cur, event.workspace_id, 'growth.usage_recorded', 'model_usage', row_id,
         {'actualUsdMicro': event.cost_usd_micro(), 'state': 'unknown' if event.cost_usd_micro() is None else
          'completed' if event.status == 'ok' else 'failed', 'route': event.route,
          'costSource': 'gateway' if event.cost_source == 'gateway' else 'unknown' if event.cost_source == 'unknown' else 'table',
          'metric': 'physical_attempt_detail'})
