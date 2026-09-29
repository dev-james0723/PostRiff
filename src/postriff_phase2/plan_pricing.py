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
        cur.execute("SELECT status,provider_subscription_id,plan_terms_id FROM public.pr_subscriptions WHERE workspace_id=%s", (workspace_id,))
        prior = cur.fetchone()
        if prior and (prior[0] in ('active', 'past_due', 'grace') or prior[1] or prior[2] not in ('trial-v1', 'free-v1')):
            raise AlphaError('This workspace already has a subscription. Use the billing portal.', 409)
        variant = self.assign(cur, workspace_id)
        if variant['planTermsId'] != terms_id or variant['status'] != 'active' or not (variant['priceId'] or '').strip():
            raise AlphaError('This server price is not yet available for purchase.', 409)
        cur.execute('SELECT id FROM public.pr_plan_price_variants WHERE provider_price_id=%s UNION ALL SELECT id FROM public.pr_plan_terms WHERE provider_price_id=%s', (variant['priceId'], variant['priceId']))
        if len(cur.fetchall()) != 1:
            raise AlphaError('The server price mapping is ambiguous.', 409)
        return variant

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
        cur.execute('SELECT plan_terms_id,price_variant_id,provider_subscription_id,provider_customer_id,provider,extract(epoch from last_event_at) FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE', (workspace,))
        prior = cur.fetchone()
        if prior and prior[4] == 'stripe':
            if subscription and prior[2] and subscription != prior[2]:
                return False
            if event.get('customerId') and prior[3] and event['customerId'] != prior[3]:
                return False
        if subscription:
            cur.execute('SELECT workspace_id::text FROM public.pr_subscriptions WHERE provider=\'stripe\' AND provider_subscription_id=%s', (subscription,))
            if any(row[0] != workspace for row in cur.fetchall()):
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
        historical_legacy_invoice = bool(
            same_subscription and event.get('stripeType') == 'invoice.paid' and event.get('invoicePaid')
            and price_id and mapped_variant is None and terms_id != prior[0]
            and prior[5] is not None and float(event['createdAt']) < float(prior[5]))
        if prior and prior[1] and not historical_legacy_invoice:
            if terms_id != prior[0] or variant_id != prior[1]:
                return False
        if not terms_id:
            return False
        cur.execute('SELECT catalog_state FROM public.pr_plan_terms WHERE id=%s', (terms_id,))
        package = cur.fetchone()
        if not package:
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
