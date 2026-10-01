"""Server-owned Creator pricing. Call inside the workspace transaction.

An active, nonblank catalog mapping is an operator-verified provider Price.
This module never verifies/provisions a Price by calling a payment provider.
"""
import hashlib
from uuid import UUID

from postriff_alpha.domain import AlphaError

DEFAULT_VARIANT = 'creator-59-v1'
EXPERIMENT = 'creator-beta-v1'
VARIANTS = ('creator-49-v1', DEFAULT_VARIANT, 'creator-79-v1')


def pricing_from_environment(values):
    return {
        'pricing_v2_enabled': values.get('POSTRIFF_PRICING_V2_ENABLED') == '1',
        'creator_experiment_enabled': values.get('POSTRIFF_CREATOR_PRICE_EXPERIMENT_ENABLED') == '1',
        'creator_experiment_cohort': tuple(x.strip() for x in values.get('POSTRIFF_CREATOR_PRICE_EXPERIMENT_COHORT', '').split(',') if x.strip()),
    }


class PlanPricing:
    def __init__(self, experiment_enabled=False, cohort=()):
        self.experiment_enabled = experiment_enabled
        # Only explicit, server-configured workspace UUIDs; no state/cookie/client eligibility.
        self.cohort = frozenset(str(UUID(value)) for value in cohort)

    @staticmethod
    def variant(cur, variant_id):
        cur.execute('SELECT id,plan_terms_id,provider_price_id,status,amount_cents,currency FROM public.pr_plan_price_variants WHERE id=%s', (variant_id,))
        row = cur.fetchone()
        if not row:
            raise AlphaError('Unknown server price variant.', 409)
        return dict(zip(('priceVariantId', 'planTermsId', 'priceId', 'status', 'amountCents', 'currency'), row))

    def assign(self, cur, workspace_id):
        try:
            workspace_id = str(UUID(str(workspace_id)))
        except ValueError as error:
            raise AlphaError('Invalid workspace identity.', 400) from error
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
        if not cur.fetchone():
            raise AlphaError('Workspace unavailable.', 404)
        cur.execute('SELECT plan_terms_id,price_variant_id,provider_subscription_id,status FROM public.pr_subscriptions WHERE workspace_id=%s', (workspace_id,))
        prior = cur.fetchone()
        if prior and (prior[2] or prior[3] in ('active', 'past_due', 'grace') or prior[1] or prior[0] not in ('trial-v1', 'free-v1')):
            if prior[1]:
                return self.variant(cur, prior[1])
            raise AlphaError('Existing subscribers keep their paid terms. Use the billing portal.', 409)
        cur.execute('SELECT price_variant_id FROM public.pr_price_experiment_assignments WHERE workspace_id=%s AND experiment_key=%s', (workspace_id, EXPERIMENT))
        existing = cur.fetchone()
        if existing:
            return self.variant(cur, existing[0])
        selected = DEFAULT_VARIANT
        if self.experiment_enabled and str(workspace_id) in self.cohort:
            bucket = int.from_bytes(hashlib.sha256((EXPERIMENT + ':' + str(workspace_id)).encode()).digest()[:8], 'big') % len(VARIANTS)
            selected = VARIANTS[bucket]
            cur.execute('INSERT INTO public.pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) VALUES(%s,%s,%s,%s) ON CONFLICT(workspace_id,experiment_key) DO NOTHING',
                        (workspace_id, EXPERIMENT, selected, 'server-explicit-cohort-v1'))
            cur.execute('SELECT price_variant_id FROM public.pr_price_experiment_assignments WHERE workspace_id=%s AND experiment_key=%s', (workspace_id, EXPERIMENT))
            selected = cur.fetchone()[0]
        return self.variant(cur, selected)

    def checkout(self, cur, workspace_id, terms_id):
        cur.execute('SELECT plan,status,catalog_state,new_checkout_enabled FROM public.pr_plan_terms WHERE id=%s', (terms_id,))
        package = cur.fetchone()
        if terms_id != 'creator-v1' or not package or package != ('creator', 'active', 'public', True):
            raise AlphaError('This plan is not yet available for purchase.', 409)
        cur.execute("SELECT status,provider_subscription_id,plan_terms_id,price_variant_id,provider_customer_id,provider FROM public.pr_subscriptions WHERE workspace_id=%s", (workspace_id,))
        prior = cur.fetchone()
        ended_creator = bool(prior and prior[0] in ('cancelled', 'expired') and prior[2] == terms_id
                             and prior[3] in VARIANTS and prior[1] and prior[4] and prior[5] == 'stripe')
        if prior and not ended_creator and (prior[0] in ('active', 'past_due', 'grace') or prior[1] or prior[2] not in ('trial-v1', 'free-v1')):
            raise AlphaError('This workspace already has a subscription. Use the billing portal.', 409)
        variant = self.assign(cur, workspace_id)
        if variant['planTermsId'] != terms_id or variant['status'] != 'active' or not (variant['priceId'] or '').strip():
            raise AlphaError('This server price is not yet available for purchase.', 409)
        cur.execute('SELECT id FROM public.pr_plan_price_variants WHERE provider_price_id=%s UNION ALL SELECT id FROM public.pr_plan_terms WHERE provider_price_id=%s', (variant['priceId'], variant['priceId']))
        if len(cur.fetchall()) != 1:
            raise AlphaError('The server price mapping is ambiguous.', 409)
        return variant

    @staticmethod
    def invoice_price(cur, event, *, versioned=True):
        """Select one known subscription Price and its period, independent of addon order.

        Explicit addon lines never supply package authority. Multiple known subscription
        Prices or conflicting periods are refused; unknown addon lines may coexist
        with exactly one known package line for legacy invoices.
        """
        lines = event.get('invoicePriceLines')
        if not lines:
            return True
        candidates = []
        has_prices = any(line.get('priceIds') for line in lines)
        for line in lines:
            if line.get('kind') == 'addon' or not line.get('priceIds'):
                continue
            if len(line['priceIds']) != 1:
                return False
            if line.get('subscriptionId') and event.get('subscriptionId') and line['subscriptionId'] != event['subscriptionId']:
                return False
            price_id = line['priceIds'][0]
            if versioned:
                cur.execute('SELECT plan_terms_id,id FROM public.pr_plan_price_variants WHERE provider_price_id=%s UNION ALL SELECT id,NULL FROM public.pr_plan_terms WHERE provider_price_id=%s', (price_id, price_id))
            else:
                cur.execute("SELECT id,NULL FROM public.pr_plan_terms WHERE provider_price_id=%s AND status='active'", (price_id,))
            rows = cur.fetchall()
            if len(rows) > 1:
                return False
            if rows:
                candidates.append((price_id, rows[0], line.get('periodStart'), line.get('periodEnd')))
        if not candidates:
            return not has_prices
        # Include periods: a second line must not silently change the funded paid period.
        if len(set(candidates)) != 1:
            return False
        price_id, mapping, start, end = candidates[0]
        if (event.get('planTermsId') and event['planTermsId'] != mapping[0]
                or event.get('priceVariantId') and event['priceVariantId'] != mapping[1]):
            return False
        event.update(priceId=price_id, periodStart=start, currentPeriodEnd=end)
        return True

    def resolve_event(self, cur, event):
        """Resolve signed facts, including stale invoices, before any mutation/grant.

        Historical mappings do not depend on current new-sale visibility/status.
        Prior paid Creator variants cannot be replaced by an experiment or metadata.
        """
        if event.get('metadataConflict'):
            return False
        workspace = event.get('workspaceId')
        subscription = event.get('subscriptionId')
        if subscription:
            # Serialize the provider identity across workspaces before reading its binding.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('stripe-subscription:' + subscription,))
        if not workspace:
            if not subscription:
                return True  # true orphan: Billing records ignored
            cur.execute('SELECT workspace_id::text FROM public.pr_subscriptions WHERE provider=\'stripe\' AND provider_subscription_id=%s', (subscription,))
            rows = cur.fetchall()
            if len(rows) != 1:
                return True
            workspace = event['workspaceId'] = rows[0][0]
        try:
            workspace = str(UUID(workspace))
        except (ValueError, TypeError, AttributeError):
            return False
        event['workspaceId'] = workspace
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
        if not cur.fetchone():
            return False
        cur.execute('SELECT plan_terms_id,price_variant_id,provider_subscription_id,provider_customer_id,provider,extract(epoch from last_event_at),status FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE', (workspace,))
        prior = cur.fetchone()
        different_subscription = bool(prior and prior[4] == 'stripe' and subscription and prior[2] and subscription != prior[2])
        if prior and prior[4] == 'stripe':
            if event.get('customerId') and prior[3] and event['customerId'] != prior[3]:
                return False
            if different_subscription and prior[3] and event.get('customerId') != prior[3]:
                return False
        if subscription:
            cur.execute('SELECT workspace_id::text FROM public.pr_subscriptions WHERE provider=\'stripe\' AND provider_subscription_id=%s', (subscription,))
            if any(row[0] != workspace for row in cur.fetchall()):
                return False
        if not self.invoice_price(cur, event):
            return False
        terms_id, variant_id, price_id = event.get('planTermsId'), event.get('priceVariantId'), event.get('priceId')
        if price_id:
            cur.execute('SELECT plan_terms_id,id FROM public.pr_plan_price_variants WHERE provider_price_id=%s UNION ALL SELECT id,NULL FROM public.pr_plan_terms WHERE provider_price_id=%s', (price_id, price_id))
            matches = cur.fetchall()
            if len(matches) != 1:
                return False
            mapped_terms, mapped_variant = matches[0]
            if (terms_id and terms_id != mapped_terms) or (variant_id and variant_id != mapped_variant):
                return False
            terms_id, variant_id = mapped_terms, mapped_variant
        if event.get('priceConflict') and (terms_id == 'creator-v1' or variant_id):
            return False
        if variant_id:
            try:
                variant = self.variant(cur, variant_id)
            except AlphaError:
                return False
            if terms_id and terms_id != variant['planTermsId']:
                return False
            if not (variant['priceId'] or '').strip():
                return False
            terms_id = variant['planTermsId']
        # Omitted facts may inherit only from the same established provider subscription.
        same_subscription = bool(prior and prior[4] == 'stripe' and subscription and subscription == prior[2])
        if not terms_id and same_subscription:
            terms_id, variant_id = prior[:2]
        if terms_id == 'creator-v1' and not variant_id and same_subscription and prior[0] == terms_id:
            variant_id = prior[1]
        older_invoice = bool(
            prior and event.get('stripeType') == 'invoice.paid' and event.get('invoicePaid')
            and price_id and prior[5] is not None and float(event['createdAt']) < float(prior[5]))
        historical_legacy_invoice = bool(older_invoice and same_subscription and mapped_variant is None and terms_id != prior[0])
        historical_replaced_invoice = bool(older_invoice and different_subscription)
        if prior and prior[1] and not (historical_legacy_invoice or historical_replaced_invoice):
            if terms_id != prior[0] or variant_id != prior[1]:
                return False
        if not terms_id:
            return False
        cur.execute('SELECT catalog_state,provider_price_id FROM public.pr_plan_terms WHERE id=%s', (terms_id,))
        package = cur.fetchone()
        if not package:
            return False
        if different_subscription and not historical_replaced_invoice:
            # Default-off legacy checkout allows ended subscriptions to start again. Only a
            # fresh verified start can replace that binding; old events cannot resurrect it.
            cur.execute('SELECT catalog_state FROM public.pr_plan_terms WHERE id=%s', (prior[0],))
            old_package = cur.fetchone()
            starts_subscription = (event.get('type') in ('subscription.activated', 'subscription.updated') and (
                event.get('stripeType') in ('checkout.session.completed', 'customer.subscription.created')
                or (event.get('stripeType') == 'invoice.paid' and event.get('invoicePaid')
                    and event.get('billingReason') == 'subscription_create')))
            fresh = prior[5] is None or float(event['createdAt']) >= float(prior[5])
            legacy_replacement = (not prior[1] and old_package and old_package[0] == 'legacy'
                                  and package[0] == 'legacy' and not variant_id and (package[1] or '').strip())
            creator_replacement = (prior[0] == terms_id == 'creator-v1' and prior[1] == variant_id
                                   and variant_id in VARIANTS and prior[3] and event.get('customerId') == prior[3]
                                   and price_id == variant['priceId'])
            if not (prior[6] in ('cancelled', 'expired') and starts_subscription and fresh
                    and (legacy_replacement or creator_replacement)):
                return False
        if terms_id == 'creator-v1':
            if variant_id not in VARIANTS or not subscription:
                return False
            cur.execute('SELECT price_variant_id FROM public.pr_price_experiment_assignments WHERE workspace_id=%s AND experiment_key=%s', (workspace, EXPERIMENT))
            assignment = cur.fetchone()
            if assignment and not (prior and prior[1]) and assignment[0] != variant_id:
                return False
        elif variant_id or package[0] != 'legacy':
            return False
        event['planTermsId'] = terms_id
        if variant_id:
            event['priceVariantId'] = variant_id
        return True


# --- One catalog projection for every customer-visible surface (R-COM-04) -----------------------------------------
CATALOG_VERSION_V2 = 'pricing-v2-2026-09-28'
CATALOG_VERSION_LEGACY = 'legacy-2026-09'
CREDITS_PER_USD = 300
FREE_FIRST_VALUE = {'postDoctorRuns': 1, 'genomeAnalyses': 1, 'genomeMaxPosts': 20}
_PUBLIC_ENTITLEMENTS = ('members', 'connectedAccounts', 'brands', 'storageMb', 'monthlyCredits', 'writingBatches', 'mediaCredits', 'overage')


def _plan_view(row, *, v2, variant=None):
    terms_id, plan, label, price_cents, currency, status, checkout_enabled, entitlements, provider_price = row
    entitlements = entitlements or {}
    view = {'id': terms_id, 'plan': plan, 'label': label, 'priceCents': variant['amountCents'] if variant else price_cents,
            'currency': (variant['currency'] if variant else currency) or 'USD', 'interval': None if plan in ('free', 'trial') else 'month',
            'entitlements': {k: entitlements[k] for k in _PUBLIC_ENTITLEMENTS if k in entitlements}}
    if v2:
        view['monthlyCredits'] = int(entitlements.get('monthlyCredits') or 0)
        if plan == 'free':
            view['firstValue'] = dict(FREE_FIRST_VALUE)
            view['checkout'] = 'not_applicable'
        else:
            purchasable = (status == 'active' and checkout_enabled and variant is not None and variant['status'] == 'active'
                           and bool((variant['priceId'] or '').strip()))
            view['checkout'] = 'available' if purchasable else 'not_yet_available'
            view['priceVariantId'] = variant['priceVariantId'] if variant else None
    else:
        view['checkout'] = 'legacy_flow' if status == 'active' and (provider_price or '').strip() else 'not_yet_available'
    return view


def public_catalog(cur, pricing_v2_enabled):
    """The plans a new customer may see for sale, projected from the server catalog rows.

    Under v2 only `catalog_state='public'` terms appear (Free + Creator); hidden (Starter, Studio v2) and legacy
    packages never do, and Creator shows the default variant's amount. Under legacy the existing new-sale packages
    appear exactly as the current checkout sells them. No client value can change an amount or a Price id."""
    if pricing_v2_enabled:
        cur.execute("SELECT to_regclass('public.pr_plan_price_variants') IS NOT NULL")
        if not cur.fetchone()[0]:   # flag on before migration 048: say so rather than show a wrong catalog
            raise AlphaError('The pricing catalog is not available yet.', 503, code='catalog_unavailable')
        cur.execute("SELECT id,plan,label,price_cents,currency,status,new_checkout_enabled,entitlements,provider_price_id FROM public.pr_plan_terms "
                    "WHERE catalog_state='public' AND status IN ('active','proposed') ORDER BY price_cents,id")
        rows = cur.fetchall()
        default = PlanPricing.variant(cur, DEFAULT_VARIANT)
        plans = [_plan_view(r, v2=True, variant=default if r[1] == 'creator' else None) for r in rows]
        return {'catalogVersion': CATALOG_VERSION_V2, 'pricing': 'v2', 'creditsPerUsd': CREDITS_PER_USD,
                'plans': plans, 'topUps': {'available': False, 'reason': 'not_activated'},
                'notes': ['Free has no monthly credits; it includes one Post Doctor check and one recent-20 Genome analysis.',
                          'Creator credits reset each billing period and do not roll over. Paid work stops at the limit; nothing is charged silently.']}
    # Migration 048 may not be applied where legacy pricing runs (it adds new_checkout_enabled): read it only if present.
    cur.execute("SELECT to_regclass('public.pr_plan_price_variants') IS NOT NULL")
    checkout_column = "new_checkout_enabled" if cur.fetchone()[0] else "false"
    cur.execute(f"SELECT id,plan,label,price_cents,currency,status,{checkout_column},entitlements,provider_price_id FROM public.pr_plan_terms "
                "WHERE id IN ('trial-v1','studio-v1','assist-v1') ORDER BY price_cents,id")
    return {'catalogVersion': CATALOG_VERSION_LEGACY, 'pricing': 'legacy', 'plans': [_plan_view(r, v2=False) for r in cur.fetchall()],
            'topUps': {'available': False, 'reason': 'not_offered'}}


def billing_mode(growth_mode):
    """Ledger.growth_mode → the explicit mode every surface branches on (never inferred from a price or a batch count)."""
    return {'free': 'free_preview', 'managed_credits': 'managed_credits'}.get(growth_mode, 'legacy_allowances')
