"""Task3: disposable PG17, real transactions and signed events; NO provider network.
Breaks caught: rebucketing, client authority, gating bypass, wrong/ambiguous price,
paid repricing, cross-subscription corruption, replay/races and misbound invoice grants.
"""
import hashlib
import hmac
import inspect
import json
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Billing
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.hosted import HostedWorkspaceService

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = int(time.time())


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class Transport:
    def __init__(self):
        self.calls = []
        self.headers = []

    def __call__(self, method, url, headers=None, form=None):
        self.calls.append((url, form))
        self.headers.append(headers or {})
        return {'status': 200, 'body': {'id': 'cs_synthetic', 'url': 'https://checkout.stripe.com/c/synthetic'}}


class AssignmentV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == 55438
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '048_pricing_credit_catalog_v2.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def setUp(self):
        # Guard constructor assertions make RED show missing behavior, not unexpected TypeErrors.
        self.assertIn('pricing_v2_enabled', inspect.signature(HostedWorkspaceService).parameters,
                      'missing default-off v2 pricing plumbing')
        self.clock = [float(NOW)]
        self.actor = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
            self.wid = str(db.execute("SELECT pr_bootstrap(%s,'studio')", (self.actor,)).fetchone()[0])
            db.execute("UPDATE pr_plan_terms SET status='proposed',catalog_state='public',new_checkout_enabled=false WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='proposed',provider_price_id=NULL")
        def verify(token):
            if token != 'fixture':
                raise AlphaError('Denied', 403)
            return self.actor
        verify.session_id = lambda token, principal: 'task3-' + self.actor
        verify.auth_time = lambda token, principal: self.clock[0]
        self.verify = verify
        self.transport = Transport()
        self.provider = StripePaymentProvider('sk_test_synthetic', 'whsec_synthetic',
            transport=self.transport, clock=lambda: self.clock[0])
        self.service = self.make_service()

    def make_service(self, enabled=True, experiment=False, cohort=()):
        return HostedWorkspaceService(connection, self.verify, clock=lambda: self.clock[0],
            billing_provider=self.provider, public_base_url='https://app.example.test',
            email_lookup=lambda actor: 'owner@example.test', credits_enabled=True,
            pricing_v2_enabled=enabled, creator_experiment_enabled=experiment, creator_experiment_cohort=cohort)

    def activate(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='active',provider_price_id='price_synthetic_'||variant_key")

    def assignment(self, billing=None):
        with connection() as db:
            return (billing or self.service.billing).assign_creator_price(db.cursor(), self.wid)

    def deny_checkout(self, terms='creator-v1'):
        before = len(self.transport.calls)
        with self.assertRaises(AlphaError) as caught:
            self.service.billing_checkout(self.wid, 'fixture', terms)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.transport.calls), before)

    def signed(self, kind, obj, eid=None, created=None):
        body = json.dumps({'id': eid or 'evt_' + str(uuid.uuid4()), 'type': kind,
            'created': created or int(self.clock[0]), 'livemode': False, 'data': {'object': obj}}).encode()
        timestamp = int(self.clock[0])
        mac = hmac.new(b'whsec_synthetic', f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
        return f't={timestamp},v1={mac}', body

    def sub(self, variant='59', *, metadata=True, price=True, subscription='sub_synthetic'):
        obj = {'id': subscription + self.wid, 'status': 'active', 'customer': 'cus_synthetic' + self.wid,
               'metadata': {'workspace_id': self.wid}, 'current_period_end': NOW + 300}
        if metadata:
            obj['metadata'].update(plan_terms_id='creator-v1', price_variant_id='creator-' + variant + '-v1')
        if price:
            obj['items'] = {'data': [{'price': {'id': 'price_synthetic_' + variant}}]}
        return obj

    def webhook(self, obj, kind='customer.subscription.updated', **kw):
        return self.service.billing_webhook(*self.signed(kind, obj, **kw))

    def persisted(self):
        with connection() as db:
            return db.execute('SELECT plan_terms_id,price_variant_id,status FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone()

    def invoice(self, variant='59', invoice='in_synthetic', subscription='sub_synthetic'):
        return {'id': invoice + self.wid, 'subscription': subscription + self.wid, 'customer': 'cus_synthetic' + self.wid,
            'status': 'paid', 'paid': True, 'amount_paid': int(variant) * 100, 'currency': 'usd',
            'billing_reason': 'subscription_cycle', 'subscription_details': {'metadata':
                {'workspace_id': self.wid, 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-' + variant + '-v1'}},
            'lines': {'data': [{'price': 'price_synthetic_' + variant, 'period': {'start': NOW - 10, 'end': NOW + 300}}]}}

    def test_default_is_59_without_an_experiment_row(self):
        self.assertEqual(self.assignment()['priceVariantId'], 'creator-59-v1')
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_experiment_requires_server_cohort(self):
        billing = self.make_service(experiment=True).billing
        self.assertEqual(self.assignment(billing)['priceVariantId'], 'creator-59-v1')
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_concurrent_assignment_is_one_immutable_row_and_survives_toggle(self):
        billing = self.make_service(experiment=True, cohort=(self.wid,)).billing
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda _: self.assignment(billing), range(16)))
        variants = {r['priceVariantId'] for r in rows}
        self.assertEqual(len(variants), 1)
        self.assertTrue(variants <= {'creator-49-v1', 'creator-59-v1', 'creator-79-v1'})
        self.assertEqual(self.assignment()['priceVariantId'], rows[0]['priceVariantId'])
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)
            with self.assertRaises(psycopg.errors.CheckViolation), db.transaction():
                db.execute("UPDATE pr_price_experiment_assignments SET assignment_source='changed' WHERE workspace_id=%s", (self.wid,))

    def test_paid_legacy_never_assigned(self):
        with connection() as db:
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,provider_subscription_id) VALUES(%s,'studio-v1','stripe','active','sub_old')", (self.wid,))
        with self.assertRaises(AlphaError):
            self.assignment(self.make_service(experiment=True, cohort=(self.wid,)).billing)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_checkout_package_gates_independent_of_price(self):
        self.activate()
        for field, value in (('status', 'proposed'), ('catalog_state', 'hidden'), ('catalog_state', 'legacy'), ('new_checkout_enabled', False)):
            with self.subTest(field=field):
                with connection() as db:
                    db.execute(f'UPDATE pr_plan_terms SET {field}=%s WHERE id=\'creator-v1\'', (value,))
                self.deny_checkout()
                with connection() as db:
                    db.execute("UPDATE pr_plan_terms SET status='active',catalog_state='public',new_checkout_enabled=true WHERE id='creator-v1'")

    def test_seeded_checkout_all_off_and_old_sales_refused(self):
        self.deny_checkout()
        for terms in ('starter-v1', 'studio-v2', 'free-v1', 'studio-v1', 'assist-v1'):
            with connection() as db:
                db.execute("UPDATE pr_plan_terms SET status='active',provider_price_id='price_synthetic_old' WHERE id=%s", (terms,))
            self.deny_checkout(terms)
        self.assertFalse(self.service.usage(self.wid, 'fixture')['billing']['checkoutAvailable'])

    def test_checkout_mapping_gate_independent_of_package(self):
        self.activate()
        with connection() as db:
            db.execute("UPDATE pr_plan_price_variants SET status='proposed',provider_price_id=NULL WHERE id='creator-59-v1'")
        self.deny_checkout()
        self.assertFalse(self.service.usage(self.wid, 'fixture')['billing']['checkoutAvailable'])

    def test_checkout_default_server_price_and_defaultoff_block(self):
        self.activate()
        self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        form = self.transport.calls[-1][1]
        self.assertEqual(form['line_items[0][price]'], 'price_synthetic_59')
        self.assertEqual(form['metadata[price_variant_id]'], 'creator-59-v1')
        self.service = self.make_service(enabled=False)
        self.deny_checkout()

    def test_metadata_only_and_provider_price_only_persist_variant(self):
        self.activate()
        self.assertEqual(self.webhook(self.sub('49', price=False))['outcome'], 'applied')
        self.assertEqual(self.persisted()[:2], ('creator-v1', 'creator-49-v1'))
        self.assertEqual(self.webhook(self.sub('49', metadata=False))['outcome'], 'applied')
        self.assertEqual(self.persisted()[1], 'creator-49-v1')

    def test_paid_price_survives_flags_retirement_and_missing_metadata(self):
        self.activate()
        self.webhook(self.sub('79'))
        self.service = self.make_service(enabled=False, experiment=True, cohort=(self.wid,))
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='proposed',new_checkout_enabled=false,catalog_state='hidden' WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='retired'")
        self.assertEqual(self.assignment()['priceVariantId'], 'creator-79-v1')
        self.assertEqual(self.webhook(self.sub('79', metadata=False, price=False))['outcome'], 'applied')
        self.assertEqual(self.persisted()[1], 'creator-79-v1')

    def test_conflicting_variant_plan_price_and_subscription_are_rejected(self):
        self.activate()
        self.webhook(self.sub('59'))
        for obj in (self.sub('49'), self.sub('59', subscription='sub_foreign'), self.sub('59')):
            if obj == self.sub('59'):
                obj['items']['data'][0]['price']['id'] = 'price_unknown'
            with self.subTest(obj=obj):
                self.assertEqual(self.webhook(obj)['outcome'], 'rejected')
                self.assertEqual(self.persisted()[1], 'creator-59-v1')
        obj = self.sub('59'); obj['metadata']['plan_terms_id'] = 'studio-v2'
        self.assertEqual(self.webhook(obj)['outcome'], 'rejected')

    def test_assignment_conflict_on_first_checkout_completion_rejected(self):
        self.activate()
        assigned = self.assignment(self.make_service(experiment=True, cohort=(self.wid,)).billing)['priceVariantId']
        other = '49' if assigned != 'creator-49-v1' else '79'
        self.assertEqual(self.webhook(self.sub(other))['outcome'], 'rejected')
        self.assertIsNone(self.persisted())

    def test_all_prices_grant_exactly_3500_once_even_late(self):
        self.activate()
        for variant in ('49', '59', '79'):
            with self.subTest(variant=variant):
                # Separate actual subscription for each price fixture; no production repricing.
                with connection() as db:
                    db.execute('DELETE FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,))
                self.webhook(self.sub(variant))
                invoice = self.invoice(variant, 'in_' + variant)
                signed = self.signed('invoice.paid', invoice, created=NOW - 5)
                self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'stale')
                self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'duplicate')
                with connection() as db:
                    row = db.execute('SELECT millicredits,grant_id FROM pr_credit_subscription_grants WHERE invoice_id=%s', (invoice['id'],)).fetchone()
                    self.assertEqual(row[0], 3500000)
                    self.assertIsNotNone(row[1])

    def test_conflicting_late_invoice_never_grants(self):
        self.activate(); self.webhook(self.sub('59'))
        invoice = self.invoice('49')
        self.assertEqual(self.webhook(invoice, 'invoice.paid', created=NOW - 5)['outcome'], 'rejected')
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_credit_subscription_grants WHERE invoice_id=%s', (invoice['id'],)).fetchone()[0], 0)

    def test_replayed_webhooks_concurrent_deliveries_are_idempotent(self):
        self.activate()
        signed = self.signed('customer.subscription.updated', self.sub('59'))
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda _: self.service.billing_webhook(*signed)['outcome'], range(6)))
        self.assertEqual(outcomes.count('applied'), 1)
        self.assertEqual(outcomes.count('duplicate'), 5)

    def test_true_legacy_renewal_ignores_new_sale_gates(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='proposed',provider_price_id='price_synthetic_legacy' WHERE id='studio-v1'")
        obj = self.sub(metadata=False)
        obj['items']['data'][0]['price']['id'] = 'price_synthetic_legacy'
        self.assertEqual(self.webhook(obj)['outcome'], 'applied')
        self.assertEqual(self.persisted()[:2], ('studio-v1', None))


    def test_seeded_unmapped_variant_cannot_activate_by_metadata(self):
        self.assertEqual(self.webhook(self.sub(price=False))['outcome'], 'rejected')
        self.assertIsNone(self.persisted())

    def test_ambiguous_known_price_is_refused_before_transport_or_entitlement(self):
        self.activate()
        with connection() as db:
            db.execute("UPDATE pr_plan_price_variants SET provider_price_id='price_synthetic_59' WHERE id='creator-49-v1'")
        self.deny_checkout()
        self.assertEqual(self.webhook(self.sub())['outcome'], 'rejected')
        self.assertIsNone(self.persisted())

    def test_conflicting_signed_carriers_never_mutate_or_grant(self):
        self.activate()
        obj = self.sub(); obj['metadata']['price_variant_id'] = 'creator-49-v1'
        self.assertEqual(self.webhook(obj)['outcome'], 'rejected')
        obj = {'mode': 'subscription', 'client_reference_id': self.wid,
               'subscription': 'sub_synthetic' + self.wid,
               'metadata': {'workspace_id': str(uuid.uuid4()), 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-59-v1'}}
        self.assertEqual(self.webhook(obj, 'checkout.session.completed')['outcome'], 'rejected')
        self.assertIsNone(self.persisted())

    def test_existing_subscriber_recovers_price_and_workspace_with_flag_off(self):
        self.activate(); self.webhook(self.sub('49'))
        self.service = self.make_service(enabled=False)
        obj = self.sub('49', metadata=False); obj['metadata'] = {}
        self.assertEqual(self.webhook(obj)['outcome'], 'applied')
        self.assertEqual(self.persisted()[1], 'creator-49-v1')

    def test_stale_invoice_backfills_known_variant_without_changing_newer_state(self):
        self.activate()
        with connection() as db:
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,provider_subscription_id,last_event_at) "
                       "VALUES(%s,'creator-v1','stripe','past_due',%s,to_timestamp(%s))", (self.wid, 'sub_synthetic' + self.wid, NOW + 10))
            self.service.billing._reconcile_entitlement(db.cursor(), self.wid, 'creator-v1',
                {'writingBatches': 0, 'mediaCredits': 0, 'members': 1, 'connectedAccounts': 6, 'storageMb': 1000}, NOW + 300)
        invoice = self.invoice('49'); invoice['subscription_details']['metadata'].pop('price_variant_id')
        self.assertEqual(self.webhook(invoice, 'invoice.paid', created=NOW)['outcome'], 'stale')
        self.assertEqual(self.persisted(), ('creator-v1', 'creator-49-v1', 'past_due'))

    def test_out_of_order_subscription_cannot_reset_newer_status(self):
        self.activate(); self.webhook(self.sub('59'), created=NOW + 10)
        cancelled = self.sub('59'); cancelled['status'] = 'canceled'
        self.assertEqual(self.webhook(cancelled, 'customer.subscription.deleted', created=NOW)['outcome'], 'stale')
        self.assertEqual(self.persisted(), ('creator-v1', 'creator-59-v1', 'active'))


    def test_historical_paid_without_provider_id_is_never_bucketed(self):
        with connection() as db:
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status) VALUES(%s,'studio-v1','cancelled')", (self.wid,))
        with self.assertRaises(AlphaError):
            self.assignment(self.make_service(experiment=True, cohort=(self.wid,)).billing)

    def test_cross_workspace_subscription_race_cannot_bind_twice(self):
        self.activate()
        actor2 = str(uuid.uuid4())
        shared = 'sub_contended' + self.wid
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (actor2,))
            other = str(db.execute("SELECT pr_bootstrap(%s,'studio')", (actor2,)).fetchone()[0])
            # Real local trigger widens the actual insertion race, without mocking SQL/domain code.
            db.execute("CREATE FUNCTION public.task3_slow_subscription() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.provider_subscription_id LIKE 'sub_contended%' THEN PERFORM pg_sleep(0.2); END IF; RETURN NEW; END $$")
            db.execute("CREATE TRIGGER task3_slow_subscription BEFORE INSERT ON pr_subscriptions FOR EACH ROW EXECUTE FUNCTION public.task3_slow_subscription()")
        obj1 = self.sub(); obj1['id'] = shared
        obj2 = self.sub(); obj2['id'] = shared; obj2['metadata']['workspace_id'] = other
        try:
            from threading import Barrier
            barrier = Barrier(2)
            def deliver(obj):
                barrier.wait(timeout=5)
                return self.webhook(obj)['outcome']
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(deliver, (obj1, obj2)))
            self.assertEqual(sorted(results), ['applied', 'rejected'])
            with connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM pr_subscriptions WHERE provider_subscription_id=%s', (shared,)).fetchone()[0], 1)
        finally:
            with connection() as db:
                db.execute('DROP TRIGGER task3_slow_subscription ON pr_subscriptions')
                db.execute('DROP FUNCTION public.task3_slow_subscription()')

    def test_verified_legacy_addon_invoice_and_portal_are_preserved_under_v2(self):
        self.activate()
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='proposed',provider_price_id='price_synthetic_legacy' WHERE id='studio-v1'")
        obj = self.sub(metadata=False); obj['items']['data'][0]['price']['id'] = 'price_synthetic_legacy'
        self.webhook(obj)
        invoice = self.invoice(); invoice['subscription_details']['metadata'] = {'workspace_id': self.wid, 'plan_terms_id': 'studio-v1'}
        invoice['lines']['data'][0]['price'] = 'price_synthetic_legacy'
        invoice['lines']['data'].append({'price': 'price_synthetic_addon'})
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'applied')
        self.assertEqual(self.persisted()[:2], ('studio-v1', None))
        self.service.billing_portal(self.wid, 'fixture')
        self.assertEqual(self.transport.calls[-1][1]['customer'], 'cus_synthetic' + self.wid)

    def test_creator_multi_price_invoice_and_wrong_customer_are_rejected(self):
        self.activate(); self.webhook(self.sub())
        invoice = self.invoice(); invoice['lines']['data'].append({'price': 'price_synthetic_49'})
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'rejected')
        obj = self.sub(); obj['customer'] = 'cus_foreign'
        self.assertEqual(self.webhook(obj)['outcome'], 'rejected')


    def test_main_flag_off_cannot_enroll_new_experiment_workspace(self):
        self.assertEqual(self.assignment(self.make_service(enabled=False, experiment=True, cohort=(self.wid,)).billing)['priceVariantId'], 'creator-59-v1')
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_late_legacy_and_v2_invoices_retain_actual_funding_policy_across_transition(self):
        self.activate()
        candidate = 'credits-candidate-2026-09-23-v1'
        v2 = 'credits-v2-2026-09-28'
        ent = {'writingBatches': 0, 'mediaCredits': 0, 'members': 1, 'connectedAccounts': 6, 'storageMb': 1000,
               'monthlyCredits': 3500, 'creditPolicy': candidate}
        with connection() as db:
            db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,catalog_state,provider_price_id,entitlements) "
                       "VALUES('task3-candidate','studio',995,'Synthetic historical candidate',4900,'active','legacy','price_synthetic_candidate',%s::jsonb)", (json.dumps(ent),))
        self.webhook(self.sub('59'))
        invoice = self.invoice('49', 'in_candidate')
        invoice['subscription_details']['metadata'] = {'workspace_id': self.wid, 'plan_terms_id': 'task3-candidate'}
        invoice['lines']['data'][0]['price'] = 'price_synthetic_candidate'
        self.assertEqual(self.webhook(invoice, 'invoice.paid', created=NOW - 5)['outcome'], 'stale')
        self.assertEqual(self.persisted()[:2], ('creator-v1', 'creator-59-v1'))
        with connection() as db:
            credit = db.execute("SELECT u.meta->'credits' FROM pr_credit_subscription_grants g JOIN pr_usage_ledger u ON u.id=g.grant_id WHERE g.invoice_id=%s", (invoice['id'],)).fetchone()[0]
            self.assertEqual(credit['policy'], candidate)
            self.assertEqual(credit['milli'], 3500000)
            db.execute('DELETE FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,))
        legacy = self.sub(metadata=False)
        legacy['metadata']['plan_terms_id'] = 'task3-candidate'
        legacy['items']['data'][0]['price']['id'] = 'price_synthetic_candidate'
        self.assertEqual(self.webhook(legacy, created=NOW + 10)['outcome'], 'applied')
        invoice = self.invoice('59', 'in_v2_transition')
        self.assertEqual(self.webhook(invoice, 'invoice.paid', created=NOW)['outcome'], 'stale')
        self.assertEqual(self.persisted()[:2], ('task3-candidate', None))
        with connection() as db:
            credit = db.execute("SELECT u.meta->'credits' FROM pr_credit_subscription_grants g JOIN pr_usage_ledger u ON u.id=g.grant_id WHERE g.invoice_id=%s", (invoice['id'],)).fetchone()[0]
            self.assertEqual(credit['policy'], v2)
            self.assertEqual(credit['milli'], 3500000)


    def test_ended_paid_subscription_cannot_open_an_incompatible_new_checkout(self):
        self.activate(); self.webhook(self.sub('79'))
        with connection() as db:
            db.execute("UPDATE pr_subscriptions SET status='cancelled' WHERE workspace_id=%s", (self.wid,))
        self.assertEqual(self.assignment()['priceVariantId'], 'creator-79-v1')
        self.deny_checkout()


    def prepare_review_legacy(self, status='cancelled'):
        ent = {'writingBatches': 0, 'mediaCredits': 0, 'members': 1, 'connectedAccounts': 3, 'storageMb': 1000,
               'monthlyCredits': 3500, 'creditPolicy': 'credits-candidate-2026-09-23-v1'}
        with connection() as db:
            db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,catalog_state,provider_price_id,entitlements) "
                       "VALUES('task3-review-legacy','studio',994,'Synthetic reviewed legacy',4900,'active','legacy','price_review_legacy',%s::jsonb) ON CONFLICT(id) DO NOTHING", (json.dumps(ent),))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,provider_subscription_id,provider_customer_id,status,last_event_at) "
                       "VALUES(%s,'task3-review-legacy','stripe',%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id) DO UPDATE SET "
                       "plan_terms_id=excluded.plan_terms_id,price_variant_id=NULL,provider=excluded.provider,provider_subscription_id=excluded.provider_subscription_id,"
                       "provider_customer_id=excluded.provider_customer_id,status=excluded.status,last_event_at=excluded.last_event_at",
                       (self.wid, 'sub_old' + self.wid, 'cus_synthetic' + self.wid, status, NOW - 20))
            self.service.billing._reconcile_entitlement(db.cursor(), self.wid, 'task3-review-legacy', ent, NOW + 300)
        self.service = self.make_service(enabled=False)

    def review_legacy_completion(self, subscription='sub_new'):
        return {'mode': 'subscription', 'client_reference_id': self.wid,
                'subscription': subscription + self.wid, 'customer': 'cus_synthetic' + self.wid,
                'metadata': {'workspace_id': self.wid, 'plan_terms_id': 'task3-review-legacy'}}

    def review_legacy_invoice(self, subscription='sub_new', reason='subscription_create'):
        invoice = self.invoice('49', 'in_review_' + subscription, subscription=subscription)
        invoice['billing_reason'] = reason
        invoice['subscription_details']['metadata'] = {'workspace_id': self.wid, 'plan_terms_id': 'task3-review-legacy'}
        invoice['lines']['data'][0]['price'] = 'price_review_legacy'
        return invoice

    def review_binding(self):
        with connection() as db:
            return db.execute('SELECT provider_subscription_id,status,extract(epoch from last_event_at) FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone()

    def test_review_f1_ended_legacy_checkout_completion_activates_replacement(self):
        for status in ('cancelled', 'expired'):
            with self.subTest(status=status):
                self.prepare_review_legacy(status)
                self.service.billing_checkout(self.wid, 'fixture', 'task3-review-legacy')
                self.assertEqual(self.transport.calls[-1][1]['line_items[0][price]'], 'price_review_legacy')
                signed = self.signed('checkout.session.completed', self.review_legacy_completion())
                self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'applied')
                self.assertEqual(self.review_binding()[:2], ('sub_new' + self.wid, 'active'))
                self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'duplicate')

    def test_review_f1_new_paid_invoice_can_arrive_before_checkout_completion(self):
        self.prepare_review_legacy('expired')
        self.service.billing_checkout(self.wid, 'fixture', 'task3-review-legacy')
        invoice = self.review_legacy_invoice()
        signed = self.signed('invoice.paid', invoice)
        self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'applied')
        self.assertEqual(self.review_binding()[:2], ('sub_new' + self.wid, 'active'))
        self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'duplicate')
        with connection() as db:
            credit = db.execute("SELECT u.meta->'credits' FROM pr_credit_subscription_grants g JOIN pr_usage_ledger u ON u.id=g.grant_id WHERE g.invoice_id=%s", (invoice['id'],)).fetchone()[0]
            self.assertEqual((credit['milli'], credit['policy']), (3500000, 'credits-candidate-2026-09-23-v1'))

    def test_review_f1_old_subscription_events_cannot_replace_new_but_stale_invoice_grants_once(self):
        self.prepare_review_legacy()
        self.assertEqual(self.webhook(self.review_legacy_completion(), 'checkout.session.completed')['outcome'], 'applied')
        newer = self.review_binding()
        deleted = {'id': 'sub_old' + self.wid, 'customer': 'cus_synthetic' + self.wid,
                   'metadata': {'workspace_id': self.wid, 'plan_terms_id': 'task3-review-legacy'}}
        self.assertEqual(self.webhook(deleted, 'customer.subscription.deleted', created=NOW - 10)['outcome'], 'rejected')
        self.assertEqual(self.webhook(self.review_legacy_completion('sub_old'), 'checkout.session.completed', created=NOW - 10)['outcome'], 'rejected')
        invoice = self.review_legacy_invoice('sub_old', 'subscription_cycle')
        signed = self.signed('invoice.paid', invoice, created=NOW - 5)
        self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'stale')
        self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'duplicate')
        self.assertEqual(self.review_binding(), newer)
        with connection() as db:
            credits = db.execute("SELECT u.meta->'credits' FROM pr_credit_subscription_grants g JOIN pr_usage_ledger u ON u.id=g.grant_id WHERE g.invoice_id=%s", (invoice['id'],)).fetchall()
            self.assertEqual(len(credits), 1)
            self.assertEqual((credits[0][0]['milli'], credits[0][0]['policy']), (3500000, 'credits-candidate-2026-09-23-v1'))

    def test_review_f1_active_customer_mapping_and_event_order_guards(self):
        for status in ('active', 'past_due', 'grace'):
            with self.subTest(status=status):
                self.prepare_review_legacy(status)
                self.assertEqual(self.webhook(self.review_legacy_completion(), 'checkout.session.completed')['outcome'], 'rejected')
                self.assertEqual(self.review_binding()[0], 'sub_old' + self.wid)
        self.prepare_review_legacy()
        wrong = self.review_legacy_completion(); wrong['customer'] = 'cus_foreign'
        self.assertEqual(self.webhook(wrong, 'checkout.session.completed')['outcome'], 'rejected')
        wrong = self.review_legacy_invoice(); wrong['lines']['data'][0]['price'] = 'price_unknown'
        self.assertEqual(self.webhook(wrong, 'invoice.paid')['outcome'], 'rejected')
        self.assertEqual(self.webhook(self.review_legacy_completion(), 'checkout.session.completed', created=NOW - 30)['outcome'], 'rejected')
        self.assertEqual(self.review_binding()[0], 'sub_old' + self.wid)

    def test_review_f1_cross_workspace_subscription_binding_is_still_rejected(self):
        self.prepare_review_legacy()
        actor2 = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (actor2,))
            other = db.execute("SELECT pr_bootstrap(%s,'studio')", (actor2,)).fetchone()[0]
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,provider_subscription_id,provider_customer_id,status) VALUES(%s,'task3-review-legacy','stripe',%s,%s,'active')",
                       (other, 'sub_new' + self.wid, 'cus_synthetic' + self.wid))
        self.assertEqual(self.webhook(self.review_legacy_completion(), 'checkout.session.completed')['outcome'], 'rejected')
        self.assertEqual(self.review_binding()[0], 'sub_old' + self.wid)


    def review_assignment_for(self, billing, spelling):
        with connection() as db:
            return billing.assign_creator_price(db.cursor(), spelling)

    def test_review_f2_uppercase_first_is_the_same_eligible_uuid_and_replay(self):
        canonical = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        with connection() as db:
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (canonical,))
        billing = self.make_service(experiment=True, cohort=(canonical,)).billing
        upper = self.review_assignment_for(billing, canonical.upper())
        self.assertEqual(upper['priceVariantId'], 'creator-49-v1')
        self.assertEqual(self.review_assignment_for(billing, canonical), upper)
        self.assertEqual(self.review_assignment_for(billing, canonical.upper()), upper)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*),min(workspace_id::text) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (canonical,)).fetchone(), (1, canonical))

    def test_review_f2_hyphenless_first_cannot_bypass_cohort_or_change_bucket(self):
        canonical = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        with connection() as db:
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (canonical,))
        billing = self.make_service(experiment=True, cohort=(canonical,)).billing
        alias = canonical.replace('-', '').upper()
        first = self.review_assignment_for(billing, alias)
        self.assertEqual(first['priceVariantId'], 'creator-49-v1')
        self.assertEqual(self.review_assignment_for(billing, canonical), first)
        self.assertEqual(self.review_assignment_for(billing, canonical.upper()), first)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (canonical,)).fetchone()[0], 1)

    def test_review_f2_mixed_uuid_spellings_share_one_concurrent_immutable_assignment(self):
        canonical = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        with connection() as db:
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (canonical,))
        billing = self.make_service(experiment=True, cohort=(canonical,)).billing
        # All initial arrivals use an alias; a canonical winner must not mask the first-offer bypass.
        spellings = [canonical.upper(), canonical.replace('-', ''), canonical.replace('-', '').upper()] * 8
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda value: self.review_assignment_for(billing, value), spellings))
        self.assertEqual({row['priceVariantId'] for row in rows}, {'creator-49-v1'})
        self.assertEqual(self.review_assignment_for(billing, canonical), rows[0])
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (canonical,)).fetchone()[0], 1)


    def test_review_f2_checkout_uuid_aliases_share_metadata_and_provider_idempotency_key(self):
        self.activate()
        self.service = self.make_service(experiment=True, cohort=(self.wid,))
        for spelling in (self.wid.upper(), self.wid.replace('-', ''), self.wid):
            self.service.billing_checkout(spelling, 'fixture', 'creator-v1')
            self.assertEqual(self.transport.calls[-1][1]['metadata[workspace_id]'], self.wid)
        self.assertEqual(len({headers['Idempotency-Key'] for headers in self.transport.headers}), 1)
        self.assertEqual(len({form['metadata[price_variant_id]'] for _, form in self.transport.calls}), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)


    def review_addon_invoice(self, metadata=True):
        invoice = self.review_legacy_invoice('sub_old', 'subscription_cycle')
        if not metadata:
            invoice['subscription_details']['metadata'] = {}
        invoice['lines']['data'][0].update(type='subscription', subscription='sub_old' + self.wid)
        invoice['lines']['data'].insert(0, {'type': 'invoiceitem', 'price': 'price_unknown_addon',
                                          'period': {'start': NOW - 100, 'end': NOW - 90}})
        return invoice

    def test_review_f3_addon_first_legacy_metadata_binds_actual_package_period(self):
        self.prepare_review_legacy('active')
        invoice = self.review_addon_invoice()
        for order in ('addon-first', 'plan-first'):
            with self.subTest(order=order):
                if order == 'plan-first':
                    invoice['lines']['data'].reverse()
                self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'applied')
                with connection() as db:
                    row = db.execute("SELECT g.period_start,g.period_end,u.meta->'credits' FROM pr_credit_subscription_grants g JOIN pr_usage_ledger u ON u.id=g.grant_id WHERE g.invoice_id=%s", (invoice['id'],)).fetchone()
                    self.assertEqual(row[:2], (NOW - 10, NOW + 300))
                    self.assertEqual((row[2]['milli'], row[2]['expiresAt'], row[2]['policy']), (3500000, NOW + 300, 'credits-candidate-2026-09-23-v1'))
                    self.assertEqual(db.execute('SELECT count(*) FROM pr_credit_subscription_grants WHERE invoice_id=%s', (invoice['id'],)).fetchone()[0], 1)

    def test_review_f3_addon_first_without_plan_metadata_recovers_known_subscription_package(self):
        self.prepare_review_legacy('active')
        for metadata in ({'workspace_id': self.wid}, {}):
            with self.subTest(metadata=metadata):
                invoice = self.review_addon_invoice(metadata=False)
                invoice['subscription_details']['metadata'] = metadata
                self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'applied')
                self.assertEqual(self.persisted()[:2], ('task3-review-legacy', None))
                with connection() as db:
                    row = db.execute('SELECT plan_terms_id,period_end,millicredits FROM pr_credit_subscription_grants WHERE invoice_id=%s', (invoice['id'],)).fetchone()
                    self.assertEqual(row, ('task3-review-legacy', NOW + 300, 3500000))

    def test_review_f3_addon_cannot_authorize_unknown_conflicting_or_ambiguous_subscription_price(self):
        self.prepare_review_legacy('active')
        invoice = self.review_addon_invoice()
        invoice['lines']['data'][0]['price'] = 'price_review_legacy'
        invoice['lines']['data'][1]['price'] = 'price_unknown_subscription'
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'rejected')
        self.activate()
        invoice = self.review_addon_invoice()
        invoice['lines']['data'][1]['price'] = 'price_synthetic_59'
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'rejected')
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET provider_price_id='price_review_other' WHERE id='studio-v1'")
        invoice = self.review_addon_invoice()
        invoice['lines']['data'].append({'type': 'subscription', 'price': 'price_review_other'})
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'rejected')
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_credit_subscription_grants WHERE invoice_id=%s', (invoice['id'],)).fetchone()[0], 0)

    def test_review_f3_v2_addon_first_and_price_carrier_conflicts_remain_denied(self):
        self.activate(); self.webhook(self.sub())
        invoice = self.invoice()
        invoice['lines']['data'].insert(0, {'type': 'invoiceitem', 'price': 'price_unknown_addon'})
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'rejected')
        self.prepare_review_legacy('active')
        invoice = self.review_addon_invoice()
        invoice['lines']['data'][1]['pricing'] = {'price_details': {'price': 'price_unknown_conflicting_carrier'}}
        self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'rejected')


    def test_review_f3_unknown_recurring_addon_cannot_hide_the_unique_known_package(self):
        self.prepare_review_legacy('active')
        for metadata in (True, False):
            with self.subTest(metadata=metadata):
                invoice = self.review_addon_invoice(metadata=metadata)
                invoice['lines']['data'][0].update(type='subscription', subscription='sub_old' + self.wid)
                self.assertEqual(self.webhook(invoice, 'invoice.paid')['outcome'], 'applied')
                self.assertEqual(self.persisted()[:2], ('task3-review-legacy', None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
