"""Task11 portable actual-PG17 fixture; parent executes on its owned loopback.

No PG startup/probing, external network, live payment or provider calls. All signed
payments, funding and content are synthetic; SQL/transactions/locks/RLS are real.
Requires task11_pricing_beta_setup.sql (or parent's equivalent existing base).
--validate-only lists tests without connecting; it is NOT actual-PG evidence.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from consumer_fixtures import approve_budgets
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.coworker import flags
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.growth.usage import MemoryUsageSink, UsageEvent
from postriff_phase2 import pricing_events as events


def test_port(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1024 <= int(value) <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be an integer in 1024..65535.')
    return int(value)


PORT = test_port(os.environ.get('POSTRIFF_TEST_PG_PORT', '55438'))
DSN = f'host=127.0.0.1 port={PORT} dbname=postgres'
NOW = int(time.time())


def connection():
    db = psycopg.connect(DSN, client_encoding='utf8')
    assert db.info.host == '127.0.0.1' and db.info.port == PORT
    assert 170000 <= db.info.server_version < 180000, 'Task11 requires the parent PG17 fixture'
    return db


class Transport:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers=None, form=None):
        assert method == 'POST' and url == 'https://api.stripe.com/v1/checkout/sessions'
        self.calls.append((headers, form))
        source = hashlib.sha256(headers['Idempotency-Key'].encode()).hexdigest()
        return {'status': 200, 'body': {'id': 'cs_synthetic_' + source, 'url': 'https://checkout.stripe.com/c/synthetic'}}


class PricingBetaActualPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.execute("SELECT to_regclass('public.pr_product_events'),to_regclass('public.pr_plan_price_variants'),to_regclass('public.pr_credit_subscription_grants')").fetchone() == ('pr_product_events', 'pr_plan_price_variants', 'pr_credit_subscription_grants')
            cls.original_terms = db.execute("SELECT status,new_checkout_enabled FROM pr_plan_terms WHERE id='creator-v1'").fetchone()
            cls.original_prices = db.execute('SELECT id,status,provider_price_id FROM pr_plan_price_variants').fetchall()

    @classmethod
    def tearDownClass(cls):
        # Restore only the exact catalog fixture values captured above. Keep all
        # synthetic source/events for parent review; no ledger/workspace cleanup.
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status=%s,new_checkout_enabled=%s WHERE id='creator-v1'", cls.original_terms)
            for variant, status, price in cls.original_prices:
                db.execute('UPDATE pr_plan_price_variants SET status=%s,provider_price_id=%s WHERE id=%s', (status, price, variant))

    def setUp(self):
        self.actor = str(uuid.uuid4())
        self.clock = [float(NOW)]
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
        def verify(token):
            if token != 'fixture':
                raise AlphaError('Verified fixture session required.', 401)
            return self.actor
        verify.session_id = lambda token, principal: 'task11-' + self.actor
        verify.auth_time = lambda token, principal: self.clock[0]
        self.transport = Transport()
        self.provider = StripePaymentProvider('sk_test_synthetic', 'whsec_synthetic', transport=self.transport, clock=lambda: self.clock[0])
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: self.clock[0],
            billing_provider=self.provider, public_base_url='https://app.example.test',
            email_lookup=lambda actor: 'fixture@example.test', credits_enabled=True)
        self.snapshot = self.service.bootstrap('fixture', 'studio')
        self.wid = self.snapshot['workspaceId']

    def activate_fixture(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='active',provider_price_id='price_task11_'||variant_key")

    def rows(self, name, wid=None):
        with connection() as db:
            return db.execute('SELECT properties FROM pr_product_events WHERE workspace_id=%s AND event=%s ORDER BY id', (wid or self.wid, name)).fetchall()

    def signed(self, kind, obj, event_id=None, created=None):
        body = json.dumps({'id': event_id or 'evt_synthetic_' + str(uuid.uuid4()), 'type': kind,
            'created': created if created is not None else int(self.clock[0]), 'livemode': False, 'data': {'object': obj}}).encode()
        stamp = int(self.clock[0])
        mac = hmac.new(b'whsec_synthetic', f'{stamp}.'.encode() + body, hashlib.sha256).hexdigest()
        return f't={stamp},v1={mac}', body

    def sub(self, variant='49'):
        return {'id': 'sub_synthetic_' + self.wid, 'customer': 'cus_synthetic_' + self.wid, 'status': 'active',
            'metadata': {'workspace_id': self.wid, 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-' + variant + '-v1'},
            'current_period_end': NOW + 300, 'items': {'data': [{'price': 'price_task11_' + variant}]}}

    def invoice(self, variant='49', paid=None, reason='subscription_cycle'):
        return {'id': 'in_synthetic_' + variant + self.wid, 'customer': 'cus_synthetic_' + self.wid,
            'subscription': 'sub_synthetic_' + self.wid, 'status': 'paid', 'paid': True,
            'amount_paid': paid if paid is not None else int(variant)*100, 'currency': 'usd', 'billing_reason': reason,
            'subscription_details': {'metadata': {'workspace_id': self.wid, 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-' + variant + '-v1'}},
            'lines': {'data': [{'type': 'subscription', 'price': 'price_task11_' + variant,
                                'period': {'start': NOW - 10, 'end': NOW + 300}}]}}

    def activate_paid(self, variant='49'):
        self.activate_fixture()
        self.assertEqual(self.service.billing_webhook(*self.signed('customer.subscription.updated', self.sub(variant)))['outcome'], 'applied')
        self.assertEqual(self.service.billing_webhook(*self.signed('invoice.paid', self.invoice(variant)))['outcome'], 'applied')
        approve_budgets(connection, self.wid)

    def reserve(self, key, maximum=9000):
        digest = hashlib.sha256(key.encode()).hexdigest()
        with connection() as db:
            cur = db.cursor()
            quote = self.service.ledger.credits.issue(cur, self.wid, self.actor, 1, digest, 'fixture', 'fixture', maximum)
            return self.service.ledger.reserve(cur, self.wid, self.actor, 'tool', 10000, key,
                charge_batch=False, model='fixture', provider='fixture',
                credit_authority={'quoteId': quote['quoteId'], 'requestDigest': digest})['reservationId']

    def settle(self, reservation, outcome, actual):
        with connection() as db:
            return self.service.ledger.settle(db.cursor(), self.wid, reservation, outcome, actual)

    def test_00_rollout_flags_catalog_and_pack_sales_are_off(self):
        self.assertFalse(self.service.billing.pricing_v2_enabled)
        with connection() as db:
            self.assertEqual(db.execute("SELECT new_checkout_enabled FROM pr_plan_terms WHERE id IN ('free-v1','starter-v1','studio-v2') ORDER BY id").fetchall(), [(False,)]*3)
            self.assertEqual(db.execute("SELECT entitlements->>'monthlyCredits' FROM pr_plan_terms WHERE id='creator-v1'").fetchone()[0], '3500')
            self.assertEqual(db.execute("SELECT count(*) FROM pr_credit_packs WHERE id IN ('credits-1000-v2','credits-2000-v2') AND active").fetchone()[0], 0)

    def test_assignment_race_actual_global_dedupe_and_default_preview_not_exposure(self):
        with connection() as db:
            self.assertEqual(self.service.billing.assign_creator_price(db.cursor(), self.wid)['priceVariantId'], 'creator-59-v1')
        self.assertFalse(self.rows('price.assigned'))
        from postriff_phase2.plan_pricing import PlanPricing
        pricing = PlanPricing(True, (self.wid,))
        def assign(_):
            with connection() as db:
                return pricing.assign(db.cursor(), self.wid)['priceVariantId']
        with ThreadPoolExecutor(max_workers=4) as pool:
            variants = list(pool.map(assign, range(12)))
        self.assertEqual(len(set(variants)), 1)
        self.assertEqual(len(self.rows('price.assigned')), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)

    def test_actual_checkout_observes_session_without_new_default_assignment(self):
        self.activate_fixture()
        self.service.billing.pricing_v2_enabled = True
        before = len(self.rows('price.assigned'))
        with connection() as db:
            self.service.billing.availability(db.cursor(), self.wid)
        self.assertEqual(len(self.rows('price.assigned')), before)
        one = self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        two = self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        self.assertEqual(one, two)
        self.assertEqual(len(self.rows('checkout.started')), 1)
        self.assertFalse(self.rows('price.assigned'))
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)
        self.assertEqual(self.rows('checkout.started')[0][0]['priceVariant'], 'creator-59-v1')
        self.assertNotIn(one['sessionId'], repr(self.rows('checkout.started')))

    def test_signed_actual_49_59_79_invoice_same_3500_replay_and_stale(self):
        self.activate_fixture()
        for variant in ('49', '59', '79'):
            with self.subTest(variant=variant):
                # Each paid variant has its own actual workspace/source binding.
                if variant != '49':
                    self.setUp()
                self.assertEqual(self.service.billing_webhook(*self.signed('customer.subscription.updated', self.sub(variant), created=NOW+50))['outcome'], 'applied')
                invoice = self.invoice(variant, paid=int(variant)*100-200)
                signed = self.signed('invoice.paid', invoice, created=NOW)
                self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'stale')
                self.assertEqual(self.service.billing_webhook(*signed)['outcome'], 'duplicate')
                self.service.billing_webhook(*self.signed('invoice.paid', invoice, created=NOW))
                revenue = self.rows('renewal.paid')
                self.assertEqual(len(revenue), 1)
                self.assertEqual((revenue[0][0]['priceVariant'], revenue[0][0]['revenueCents']), ('creator-'+variant+'-v1', int(variant)*100-200))
                self.assertEqual(self.rows('credits.granted')[0][0]['grantedMilliCredits'], 3500000)
                with connection() as db:
                    self.assertEqual(db.execute('SELECT millicredits FROM pr_credit_subscription_grants WHERE invoice_id=%s', (invoice['id'],)).fetchone()[0], 3500000)

    def test_signed_checkout_complete_different_delivery_same_session_and_private_fields(self):
        self.activate_fixture()
        obj = {'id': 'cs_synthetic_PRIVATE', 'mode': 'subscription', 'client_reference_id': self.wid,
               'metadata': self.sub()['metadata'], 'subscription': self.sub()['id'], 'customer': self.sub()['customer'],
               'url': 'https://PRIVATE', 'customer_details': {'email': 'PRIVATE@example.test'}}
        for _ in range(2):
            self.assertEqual(self.service.billing_webhook(*self.signed('checkout.session.completed', obj))['outcome'], 'applied')
        self.assertEqual(len(self.rows('checkout.completed')), 1)
        self.assertNotIn('PRIVATE', repr(self.rows('checkout.completed')))
        self.assertFalse(self.rows('credits.granted'))

    def test_rejected_signature_and_conflicting_invoice_produce_no_analytics(self):
        self.activate_fixture()
        signed = self.signed('invoice.paid', self.invoice())
        with self.assertRaises(AlphaError):
            self.service.billing_webhook('t=1,v1=bad', signed[1])
        invoice = self.invoice()
        invoice['subscription_details']['metadata']['price_variant_id'] = 'creator-79-v1'
        self.assertEqual(self.service.billing_webhook(*self.signed('invoice.paid', invoice))['outcome'], 'rejected')
        self.assertFalse(self.rows('subscription.paid'))
        self.assertFalse(self.rows('credits.granted'))

    def test_cancellation_category_and_missing_reason_truthful(self):
        self.activate_paid()
        obj = {**self.sub(), 'status': 'canceled', 'cancellation_details': {'feedback': 'too_expensive', 'comment': 'PRIVATE'}}
        self.service.billing_webhook(*self.signed('customer.subscription.deleted', obj))
        self.assertEqual(self.rows('subscription.cancelled')[0][0]['cancellationReason'], 'too_expensive')
        obj['cancellation_details'] = {'comment': 'PRIVATE'}
        self.service.billing_webhook(*self.signed('customer.subscription.deleted', obj))
        self.assertEqual(len(self.rows('subscription.cancelled')), 1)
        self.assertNotIn('PRIVATE', repr(self.rows('subscription.cancelled')))

    def test_legacy_paid_invoice_keeps_price_allowance_and_trial_history(self):
        terms = 'task11-legacy-' + self.wid
        ent = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200}
        with connection() as db:
            trial = db.execute('SELECT expires_at FROM pr_trials WHERE workspace_id=%s', (self.wid,)).fetchone()
            version = db.execute("SELECT max(version)+1 FROM pr_plan_terms WHERE plan='studio'").fetchone()[0]
            db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,catalog_state,new_checkout_enabled,provider_price_id,entitlements) VALUES(%s,'studio',%s,'Synthetic legacy',1900,'active','legacy',false,%s,%s::jsonb)",
                       (terms,version,'price_task11_legacy_'+self.wid,json.dumps(ent)))
        obj = {'id':'sub_legacy_'+self.wid,'customer':'cus_legacy_'+self.wid,'status':'active',
               'metadata':{'workspace_id':self.wid,'plan_terms_id':terms},'current_period_end':NOW+300,
               'items':{'data':[{'price':'price_task11_legacy_'+self.wid}]}}
        self.assertEqual(self.service.billing_webhook(*self.signed('customer.subscription.updated',obj))['outcome'],'applied')
        invoice = {'id':'in_legacy_'+self.wid,'subscription':obj['id'],'customer':obj['customer'],
                   'status':'paid','paid':True,'amount_paid':1900,'currency':'usd','billing_reason':'subscription_cycle',
                   'lines':{'data':[{'type':'subscription','price':'price_task11_legacy_'+self.wid,
                                    'period':{'start':NOW-10,'end':NOW+300}}]}}
        self.assertEqual(self.service.billing_webhook(*self.signed('invoice.paid',invoice))['outcome'],'applied')
        props = self.rows('renewal.paid')[0][0]
        self.assertEqual((props['package'],props['priceVariant'],props['revenueCents'],props['cohort']),('legacy',None,1900,'legacy_paid_invoice'))
        self.assertFalse(self.rows('credits.granted'))
        with connection() as db:
            self.assertEqual(db.execute('SELECT price_cents FROM pr_plan_terms WHERE id=%s',(terms,)).fetchone()[0],1900)
            self.assertEqual(db.execute('SELECT expires_at FROM pr_trials WHERE workspace_id=%s',(self.wid,)).fetchone(),trial)
            self.assertEqual(db.execute('SELECT plan_terms_id,writing_batches_remaining FROM pr_entitlements WHERE workspace_id=%s',(self.wid,)).fetchone(),(terms,10))

    def test_unknown_failure_and_overmax_actual_wallet_idempotency(self):
        self.activate_paid()
        pending = self.reserve('pending')
        self.settle(pending, 'unknown', None)
        self.assertEqual(self.rows('credits.pending')[0][0]['actualUsdMicro'], None)
        self.assertEqual(self.rows('credits.held')[0][0]['heldMilliCredits'], 9000)
        self.assertFalse(self.rows('credits.settled'))
        failed = self.reserve('failed')
        self.settle(failed, 'failed', 5000)
        self.assertEqual(self.rows('credits.settled')[0][0]['usedMilliCredits'], 0)
        self.assertEqual(self.rows('platform.cost')[0][0]['actualUsdMicro'], 5000)
        self.settle(failed, 'completed', 1000000)
        self.assertEqual(len(self.rows('platform.cost')), 1)
        over = self.reserve('over')
        self.settle(over, 'completed', 40000)
        self.assertEqual(self.rows('platform.absorbed')[0][0]['actualUsdMicro'], 10000)
        self.assertEqual(self.rows('platform.absorbed')[0][0]['absorbedMilliCredits'], 3000)
        self.settle(pending, 'completed', 13000)
        with connection() as db:
            wallet = self.service.ledger.credits.view(db.cursor(), self.wid)
            self.assertEqual((wallet['heldMilliCredits'], wallet['usedMilliCredits']), (0, 12900))

    def test_expiry_is_cumulative_observation_and_held_releases_after_expiry(self):
        self.activate_paid()
        reservation = self.reserve('expiry')
        self.clock[0] = NOW+301
        with connection() as db:
            before = db.execute('SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s', (self.wid,)).fetchone()[0]
            wallet = self.service.ledger.credits.view(db.cursor(), self.wid)
            self.assertEqual((wallet['availableMilliCredits'], wallet['heldMilliCredits']), (0,9000))
            self.assertEqual(db.execute('SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s', (self.wid,)).fetchone()[0], before)
        self.assertEqual(self.rows('credits.expired')[0][0]['expiredMilliCredits'], 3491000)
        self.settle(reservation, 'failed', 5000)
        with connection() as db:
            self.service.ledger.credits.view(db.cursor(), self.wid)
            self.service.ledger.credits.view(db.cursor(), self.wid)
        rows = self.rows('credits.expired')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1][0]['expiredMilliCredits'], 3500000)
        self.assertEqual(rows[0][0]['lotReference'], rows[1][0]['lotReference'])

    def test_actual_ideas_saved_first_value_not_generation_or_wrong_artifact(self):
        quick = self.service.ideas.quick_start(self.wid, 'fixture', self.snapshot['revision'], {
            'text': 'Synthetic local source for a useful first draft.', 'ownContent': True, 'confirmUse': True,
            'destinations': [{'platform': 'LinkedIn', 'language': 'English'}]})
        self.assertEqual(quick['usage']['modelRequests'], 0)
        self.assertFalse(self.rows('first_value.completed'))
        with self.assertRaises(AlphaError):
            self.service.ideas.apply(self.wid, 'fixture', quick['revision'], quick['runId'], 'wrong')
        self.assertFalse(self.rows('first_value.completed'))
        self.service.ideas.apply(self.wid, 'fixture', quick['revision'], quick['runId'], quick['artifactHash'])
        self.service.ideas.apply(self.wid, 'fixture', quick['revision'], quick['runId'], quick['artifactHash'])
        self.assertEqual(len(self.rows('first_value.completed')), 1)

    def test_actual_weekly_accept_is_adopted_and_queue_approval_separate(self):
        week = {'id': 'task11-week', 'state': 'ready_for_review', 'slots': [
            {'id': 'slot-a', 'status': 'ready', 'variantId': 'synthetic-draft'},
            {'id': 'slot-b', 'status': 'ready', 'variantId': 'synthetic-draft2'}]}
        def store(state, actor):
            state.setdefault('coworker', {})['weekly'] = {'weeks': [week], 'recipes': [], 'revision': 0}
            return state
        self.service.repository.command(self.wid, 'fixture', self.snapshot['revision'], store)
        coworker = CoworkerService(self.service, values={'RAFII_WEEKLY_OPERATOR_ENABLED': '1'}, clock=lambda:self.clock[0])
        with patch.object(flags, '_values', {'RAFII_WEEKLY_OPERATOR_ENABLED': '1'}):
            with self.assertRaises(AlphaError):
                coworker.weekly_slot(self.wid, 'fixture', 'task11-week', 'missing', 'accept')
            self.assertFalse(self.rows('weekly_pack.adopted'))
            one = coworker.weekly_slot(self.wid, 'fixture', 'task11-week', 'slot-a', 'accept')
            coworker.weekly_slot(self.wid, 'fixture', 'task11-week', 'slot-b', 'accept')
            self.assertEqual(len(self.rows('weekly_pack.adopted')), 1)
            self.assertIn('approve', one['next'])
            self.assertFalse(self.service.get(self.wid, 'fixture')['state']['phase2']['jobs'])

    def test_late_cancelled_growth_accounting_once_and_gateway_cost_not_tokens(self):
        run, reservation = str(uuid.uuid4()), str(uuid.uuid4())
        # Synthetic funding authority row, explicitly NOT real Preview authorization
        # or provider execution. Actual late Growth _finish/sink/settlement follows.
        with connection() as db:
            db.execute("INSERT INTO pr_usage_ledger(id,reservation_id,workspace_id,kind,dimension,estimated_usd_micro,cost_state,idempotency_key,meta) VALUES(%s,%s,%s,'reserve','tool',20000,'estimated',%s,%s::jsonb)",
                (reservation,reservation,self.wid,'late-'+run,json.dumps({'budgetScopes': [], 'platformPreview': {'synthetic': True}})))
            db.execute("INSERT INTO pr_post_doctor_runs(id,workspace_id,request_key,kind,status,fingerprint,context_fingerprint,created_by) VALUES(%s,%s,%s,'check','cancelled','synthetic','synthetic',%s)", (run,self.wid,'late-'+run,self.actor))
        growth = object.__new__(GrowthService)
        growth.hosted = self.service
        sink = MemoryUsageSink()
        sink.record(UsageEvent('postdoctor.judge','fixture','primary','ok',1,workspace_id=self.wid,
            cost_usd=.013,cost_source='gateway',input_tokens=1000000,output_tokens=1000000))
        request = {'id':run,'reservationId':reservation,'funding':True}
        with self.assertRaises(AlphaError):
            growth._finish(self.wid,'fixture',request,sink,{'PRIVATE':'draft'})
        growth._finish(self.wid,'fixture',request,sink,{'PRIVATE':'draft'})
        self.assertEqual(len(self.rows('growth.usage_recorded')), 1)
        self.assertEqual(len(self.rows('platform.cost')), 1)
        self.assertEqual(self.rows('platform.cost')[0][0]['actualUsdMicro'],13000)
        self.assertEqual(self.rows('growth.usage_recorded')[0][0]['metric'],'physical_attempt_detail')
        self.assertNotIn('PRIVATE',repr(self.rows('platform.cost')))

    def test_global_dedupe_cross_workspace_race_and_customer_rls_denial(self):
        other = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (other,))
        def record(wid):
            with connection() as db:
                events.emit(db.cursor(),wid,'credits.held','usage_ledger','same-source',{'heldMilliCredits':9000})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(record,[self.wid,other]*6))
        self.assertEqual(len(self.rows('credits.held')),1)
        self.assertEqual(len(self.rows('credits.held',other)),1)
        with connection() as db:
            db.execute('SET LOCAL ROLE authenticated')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute('SELECT * FROM pr_product_events')


if __name__ == '__main__':
    if '--validate-only' in sys.argv:
        names = unittest.defaultTestLoader.getTestCaseNames(PricingBetaActualPG)
        print('validation_unavailable: actual PG not run; parent owns PG17 on loopback. Tests:', len(names))
        print('\n'.join(names))
    else:
        unittest.main(verbosity=2)
