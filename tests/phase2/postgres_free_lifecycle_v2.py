"""Task4: synthetic-only PG lifecycle, bootstrap security, before-IO, reenrollment."""
from local_pg_target import selected_target
import hashlib
import io
import zipfile
import hmac
import json
import time
import unittest
import uuid
from pathlib import Path
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.model_runtime import ServerModelRuntime
from consumer_fixtures import approve_budgets

ROOT = Path(__file__).resolve().parents[2]
NOW = int(time.time())
DSN = selected_target().dsn()
MIGRATION = ROOT / 'migrations/postriff/050_free_lifecycle_bootstrap.sql'


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class FreeLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == selected_target().port
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql',
                         '022_credit_payment_lifecycle.sql', '048_pricing_credit_catalog_v2.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())
            if MIGRATION.exists():
                db.execute(MIGRATION.read_text())

    def setUp(self):
        self.clock = [float(NOW)]
        self.actor = str(uuid.uuid4())
        self.sent, self.stripe_calls = [], []
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='active',provider_price_id='price_task4_'||variant_key")
        def verify(token):
            if token != 'fixture': raise AlphaError('Verified session required.', 401)
            return self.actor
        verify.session_id = lambda token, actor: 'task4-' + self.actor
        verify.auth_time = lambda token, actor: self.clock[0]
        self.verify = verify
        def stripe_transport(method, url, headers=None, form=None):
            self.stripe_calls.append((url, form))
            return {'status': 200, 'body': {'id': 'cs_task4', 'url': 'https://checkout.stripe.com/c/synthetic'}}
        def writer_transport(method, url, headers=None, body=None):
            self.sent.append(body)
            return {'status': 200, 'body': {'choices': [{'message': {'content': json.dumps({'variants': [{'platform': 'LinkedIn', 'language': 'en-US', 'text': 'Synthetic draft', 'sourceIds': []}]})}}], 'usage': {'cost': 0.01}}}
        self.provider = StripePaymentProvider('sk_test_synthetic', 'whsec_synthetic', transport=stripe_transport, clock=lambda: self.clock[0])
        self.runtime = ServerModelRuntime('synthetic-test-key', model='test/cloud', models=['test/cloud'], prices={'test/cloud': (3, 15)}, transport=writer_transport)
        self.service = self.make_service()
        self.wid = None

    def make_service(self, enabled=True, experiment=False):
        return HostedWorkspaceService(connection, self.verify, clock=lambda: self.clock[0],
            billing_provider=self.provider, public_base_url='https://app.example.test',
            email_lookup=lambda actor: 'owner@example.test', credits_enabled=True,
            ideas_runtime=self.runtime, pricing_v2_enabled=enabled,
            creator_experiment_enabled=experiment, creator_experiment_cohort=(self.wid,) if experiment and self.wid else ())

    def bootstrap(self, enabled=True):
        self.service = self.make_service(enabled)
        snap = self.service.bootstrap('fixture')
        self.wid = snap['workspaceId']
        return snap

    def entitlement(self):
        with connection() as db:
            return db.execute('SELECT plan_terms_id,source,writing_batches_remaining,media_credits_remaining FROM pr_entitlements WHERE workspace_id=%s', (self.wid,)).fetchone()

    def seed_creator(self, *, status='active', end=NOW + 300, cancel=False, grace=None, variant='49'):
        self.bootstrap(False)
        with connection() as db:
            cur = db.cursor()
            self.service.ledger.ensure_entitlement(cur, self.wid, None)
            ent = db.execute("SELECT entitlements FROM pr_plan_terms WHERE id='creator-v1'").fetchone()[0]
            self.service.billing._reconcile_entitlement(cur, self.wid, 'creator-v1', ent, end)
            db.execute("UPDATE pr_subscriptions SET plan_terms_id='creator-v1',provider='stripe',provider_customer_id=%s,provider_subscription_id=%s,price_variant_id=%s,status=%s,current_period_end=to_timestamp(%s),cancel_at_period_end=%s,grace_until=to_timestamp(%s),last_event_at=to_timestamp(%s) WHERE workspace_id=%s",
                ('cus_' + self.wid, 'sub_old_' + self.wid, 'creator-' + variant + '-v1', status, end, cancel, grace, NOW - 30, self.wid))
        self.service = self.make_service()
        return self.service.get(self.wid, 'fixture')

    def request(self):
        return {'text': 'A small creative habit.', 'ownContent': True, 'confirmUse': True,
                'model': 'test/cloud', 'reasoning': 'quick', 'research': False,
                'timeZone': 'UTC', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}

    def webhook(self, subscription, *, customer=None, variant='49', kind='customer.subscription.created', created=None, workspace=None):
        obj = {'id': subscription, 'status': 'active', 'customer': customer or 'cus_' + self.wid,
               'metadata': {'workspace_id': workspace or self.wid, 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-' + variant + '-v1'},
               'current_period_end': NOW + 600, 'items': {'data': [{'price': {'id': 'price_task4_' + variant}}]}}
        body = json.dumps({'id': 'evt_' + str(uuid.uuid4()), 'type': kind, 'created': NOW if created is None else created,
                          'livemode': False, 'data': {'object': obj}}).encode()
        timestamp = int(self.clock[0])
        mac = hmac.new(b'whsec_synthetic', f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
        return self.service.billing_webhook(f't={timestamp},v1={mac}', body)

    def test_new_v2_free_no_trials_subscriptions_or_wallet(self):
        snap = self.bootstrap()
        self.assertNotIn('trial', snap['state']['phase2'])
        view = self.service.usage(self.wid, 'fixture')
        self.assertEqual(view['entitlement']['planTermsId'], 'free-v1')
        self.assertEqual(view['entitlement']['source'], 'free')
        self.assertIsNone(view['subscription'])
        self.assertIsNone(view['credits'])
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_trials WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)
            ent = db.execute("SELECT entitlements FROM pr_plan_terms WHERE id='free-v1'").fetchone()[0]
            self.assertNotIn('creditPolicy', ent)
            self.assertNotIn('monthlyCredits', ent)
        self.assertEqual(self.stripe_calls, [])
        self.assertEqual(self.sent, [])

    def test_flag_off_new_acquisition_is_still_legacy_trial(self):
        snap = self.bootstrap(False)
        self.assertEqual(snap['state']['phase2']['trial']['writingGrant'], 10)
        view = self.service.usage(self.wid, 'fixture')
        self.assertEqual(view['entitlement']['planTermsId'], 'trial-v1')
        self.assertEqual(view['subscription']['status'], 'trial')

    def test_repeat_bootstrap_and_rollback_keep_free_without_fake_trial(self):
        snap = self.bootstrap()
        for enabled in (True, False, True):
            service = self.make_service(enabled)
            again = service.bootstrap('fixture')
            self.assertEqual(again['workspaceId'], self.wid)
            self.assertEqual(again['revision'], snap['revision'])
            self.assertNotIn('trial', again['state']['phase2'])
            try:
                explicit = service.bootstrap('fixture', 'free')
            except AlphaError as error:
                self.fail('Existing Free explicit bootstrap must survive rollback: ' + str(error))
            self.assertEqual(explicit['workspaceId'], self.wid)
            self.assertNotIn('trial', explicit['state']['phase2'])
            self.assertIsNone(service.usage(self.wid, 'fixture')['subscription'])
        self.assertEqual(self.entitlement()[:2], ('free-v1', 'free'))

    def test_old_unexpired_trial_grandfathered_then_exact_expiry_free_first_response(self):
        self.bootstrap(False)
        with connection() as db:
            end = float(db.execute('SELECT extract(epoch from expires_at) FROM pr_trials WHERE workspace_id=%s', (self.wid,)).fetchone()[0])
        self.service = self.make_service()
        self.clock[0] = end - 0.001
        self.assertEqual(self.service.usage(self.wid, 'fixture')['entitlement']['planTermsId'], 'trial-v1')
        self.clock[0] = end
        view = self.service.usage(self.wid, 'fixture')
        self.assertEqual(view['entitlement']['planTermsId'], 'free-v1')
        self.assertEqual(view['subscription']['status'], 'expired')
        self.assertTrue(view['lifecycle']['exportAvailable'])
        self.assertEqual(self.stripe_calls, [])

    def test_expired_trial_without_usage_denies_direct_paid_io(self):
        snap = self.bootstrap(False)
        with connection() as db:
            db.execute('UPDATE pr_trials SET expires_at=to_timestamp(%s) WHERE workspace_id=%s', (NOW, self.wid))
        self.service = self.make_service()
        approve_budgets(connection, self.wid)
        with self.assertRaises(AlphaError) as caught:
            self.service.ideas.quick_start(self.wid, 'fixture', snap['revision'], self.request())
        self.assertEqual(caught.exception.status, 402)
        self.assertEqual(self.sent, [])

    def test_expired_trial_estimate_positive_no_batch_direct_reservation_denied(self):
        self.bootstrap(False)
        with connection() as db:
            db.execute('UPDATE pr_trials SET expires_at=to_timestamp(%s) WHERE workspace_id=%s', (NOW, self.wid))
        self.service = self.make_service()
        approve_budgets(connection, self.wid)
        with connection() as db, self.assertRaises(AlphaError) as caught:
            self.service.ledger.reserve(db.cursor(), self.wid, self.actor, 'text_model', 10_000, 'paid-no-batch', charge_batch=False)
        self.assertEqual(caught.exception.status, 402)

    def test_legacy_19_39_active_subscription_and_allowances_unchanged(self):
        self.bootstrap(False)
        self.service = self.make_service()
        for terms, batches in (('studio-v1', 0), ('assist-v1', 100)):
            with connection() as db:
                self.service.ledger.ensure_entitlement(db.cursor(), self.wid, None)
                db.execute("UPDATE pr_entitlements SET source='trial' WHERE workspace_id=%s", (self.wid,))
                ent = db.execute('SELECT entitlements FROM pr_plan_terms WHERE id=%s', (terms,)).fetchone()[0]
                self.service.billing._reconcile_entitlement(db.cursor(), self.wid, terms, ent, NOW + 100)
                db.execute("UPDATE pr_subscriptions SET plan_terms_id=%s,status='active' WHERE workspace_id=%s", (terms, self.wid))
            view = self.service.usage(self.wid, 'fixture')
            self.assertEqual(view['entitlement']['planTermsId'], terms)
            self.assertEqual(view['entitlement']['writingBatchesRemaining'], batches)
            self.assertEqual(view['subscription']['priceCents'], 1900 if terms == 'studio-v1' else 3900)

    def test_cancel_at_period_end_retains_creator_then_free(self):
        self.seed_creator(cancel=True, end=NOW + 10)
        self.clock[0] = NOW + 9.999
        self.assertEqual(self.service.usage(self.wid, 'fixture')['entitlement']['planTermsId'], 'creator-v1')
        self.clock[0] = NOW + 10
        view = self.service.usage(self.wid, 'fixture')
        self.assertEqual(view['entitlement']['planTermsId'], 'free-v1')
        self.assertIsNone(view['credits'])
        with connection() as db:
            self.assertEqual(db.execute('SELECT plan_terms_id,price_variant_id,status FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone(), ('creator-v1', 'creator-49-v1', 'cancelled'))
        self.assertEqual(self.stripe_calls, [])

    def test_failure_grace_retained_until_exact_end(self):
        for status in ('past_due', 'grace'):
            with self.subTest(status=status):
                if not self.wid: self.seed_creator(status=status, end=NOW - 20, grace=NOW + 10)
                else:
                    with connection() as db:
                        db.execute("UPDATE pr_subscriptions SET status=%s,grace_until=to_timestamp(%s) WHERE workspace_id=%s", (status, NOW + 10, self.wid))
                        db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
                self.clock[0] = NOW + 9.999
                self.assertEqual(self.service.usage(self.wid, 'fixture')['entitlement']['planTermsId'], 'creator-v1')
                self.clock[0] = NOW + 10
                self.assertEqual(self.service.usage(self.wid, 'fixture')['entitlement']['planTermsId'], 'free-v1')

    def test_ended_creator_under_rollback_still_free(self):
        self.seed_creator(status='expired')
        self.service = self.make_service(False)
        self.assertEqual(self.service.usage(self.wid, 'fixture')['entitlement']['planTermsId'], 'free-v1')

    def test_historical_nonexpiring_lot_and_live_quote_cannot_spend_after_end(self):
        snap = self.seed_creator(cancel=True, end=NOW + 5)
        approve_budgets(connection, self.wid)
        with connection() as db:
            grant = self.service.ledger.credits.grant(db.cursor(), self.wid, self.actor, 'historical-purchase', 5_000_000, None, source='verified-stripe-checkout', policy_version='credits-v2-2026-09-28')
        body = {'operation': 'quick-start', 'expectedRevision': snap['revision'], 'maxMilliCredits': 3_000_000, 'request': self.request()}
        quote = self.service.ideas.credit_requests.issue(self.wid, 'fixture', body)
        with connection() as db:
            before = db.execute("SELECT id::text,meta FROM pr_usage_ledger WHERE workspace_id=%s AND id::text=%s", (self.wid, grant['entryId'])).fetchone()
        self.clock[0] = NOW + 5
        with self.assertRaises(AlphaError) as caught:
            self.service.ideas.quick_start(self.wid, 'fixture', snap['revision'], {**self.request(), 'creditQuoteId': quote['quoteId']})
        self.assertEqual(caught.exception.status, 402)
        self.assertEqual(self.sent, [])
        with connection() as db:
            self.assertEqual(before, db.execute("SELECT id::text,meta FROM pr_usage_ledger WHERE workspace_id=%s AND id::text=%s", (self.wid, grant['entryId'])).fetchone())
            self.assertIsNone(db.execute('SELECT reservation_id FROM pr_credit_quotes WHERE id::text=%s', (quote['quoteId'],)).fetchone()[0])
        # A separate new quote transaction must derive Free too; a denied write need not persist its lifecycle.
        with self.assertRaises(AlphaError):
            self.service.ideas.credit_requests.issue(self.wid, 'fixture', body)

    def test_existing_reservation_replay_cannot_reauthorize_after_end(self):
        self.seed_creator(cancel=True, end=NOW + 5)
        approve_budgets(connection, self.wid)
        with connection() as db:
            book = self.service.ledger.credits
            book.grant(db.cursor(), self.wid, self.actor, 'replay-funding', 100_000)
            quote = book.issue(db.cursor(), self.wid, self.actor, 1, 'a' * 64, 'm', 'test', 10_000)
            authority = book.authorize(db.cursor(), self.wid, self.actor, 1, 'a' * 64, quote['quoteId'])
            self.service.ledger.reserve(db.cursor(), self.wid, self.actor, 'text_model', 10_000,
                'before-end', charge_batch=True, model='m', provider='test', credit_authority=authority)
        self.clock[0] = NOW + 5
        with connection() as db, self.assertRaises(AlphaError) as caught:
            self.service.ledger.reserve(db.cursor(), self.wid, self.actor, 'text_model', 10_000,
                'before-end', charge_batch=True, model='m', provider='test', credit_authority=authority)
        self.assertEqual(caught.exception.status, 402)

    def test_ended_creator_legacy_action_denied_even_with_unexpired_historical_trial(self):
        snap = self.seed_creator(status='cancelled')
        for action in ('generate', 'adapt'):
            with self.subTest(action=action), self.assertRaises(AlphaError) as caught:
                self.service.mutate(self.wid, 'fixture', snap['revision'], action, {})
            self.assertEqual(caught.exception.status, 402)
        self.assertEqual(self.sent, [])

    def test_free_manual_edit_privacy_export_and_history_retained(self):
        snap = self.seed_creator(status='expired')
        self.service.usage(self.wid, 'fixture')
        variant = {'id': 'manual-draft', 'revision': 1, 'text': 'Original private draft',
                   'revisions': [], 'unknowns': [], 'sourceIds': [], 'platform': 'LinkedIn',
                   'language': 'en-US', 'needsReview': True, 'voiceRevision': None}
        source = {'id': 'retained-source', 'text': 'My private evidence', 'active': True,
                  'facts': [], 'kind': 'own', 'title': 'Own source'}
        def save(state, actor):
            state['variants'].append(variant)
            state['sources'].append(source)
            state['historyMarker'] = {'private': 'retained'}
            return state
        saved = self.service.repository.command(self.wid, 'fixture', snap['revision'], save)
        edited = self.service.mutate(self.wid, 'fixture', saved['revision'], 'variant_edit',
            {'variantId': 'manual-draft', 'variantRevision': 1, 'text': 'My manual edit'})
        self.assertEqual(edited['state']['variants'][0]['text'], 'My manual edit')
        private = self.service.mutate(self.wid, 'fixture', edited['revision'], 'memory_egress', {'cloud': False, 'confirmed': True})
        self.assertEqual(private['state']['sources'][0]['text'], 'My private evidence')
        with zipfile.ZipFile(io.BytesIO(self.service.export(self.wid, 'fixture'))) as archive:
            exported = json.loads(archive.read('phase2/workspace.json'))
        self.assertEqual(exported['variants'][0]['text'], 'My manual edit')
        self.assertEqual(exported['historyMarker'], {'private': 'retained'})
        self.assertEqual(self.stripe_calls, [])
        self.assertEqual(self.sent, [])

    def test_ended_creator_reenrollment_same_paid_variant_and_customer(self):
        self.seed_creator(status='cancelled', variant='49')
        self.service.usage(self.wid, 'fixture')
        self.service = self.make_service(experiment=True)
        try:
            result = self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        except AlphaError as error:
            self.fail('Ended Creator needs explicit same-variant checkout: ' + str(error))
        self.assertEqual(result['sessionId'], 'cs_task4')
        form = self.stripe_calls[-1][1]
        self.assertEqual(form['line_items[0][price]'], 'price_task4_49')
        self.assertEqual(form['customer'], 'cus_' + self.wid)
        self.assertEqual(form['subscription_data[metadata][price_variant_id]'], 'creator-49-v1')
        self.assertEqual(self.webhook('sub_new_' + self.wid)['outcome'], 'applied')
        self.assertEqual(self.entitlement()[0], 'creator-v1')
        with connection() as db:
            self.assertEqual(db.execute('SELECT price_variant_id,provider_subscription_id FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone(), ('creator-49-v1', 'sub_new_' + self.wid))
            self.assertEqual(db.execute('SELECT count(*) FROM pr_price_experiment_assignments WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_active_grace_past_due_replacement_denied(self):
        self.seed_creator()
        for status in ('active', 'grace', 'past_due'):
            with connection() as db: db.execute('UPDATE pr_subscriptions SET status=%s WHERE workspace_id=%s', (status, self.wid))
            with self.subTest(status=status), self.assertRaises(AlphaError):
                self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
            self.assertEqual(self.webhook('sub_foreign_' + self.wid)['outcome'], 'rejected')
        self.assertEqual(self.stripe_calls, [])

    def test_ended_replacement_denies_stale_foreign_variant_update_only_and_old_events(self):
        self.seed_creator(status='cancelled')
        for kw in ({'created': NOW - 31}, {'customer': 'cus_foreign'}, {'variant': '79'}, {'kind': 'customer.subscription.updated'}):
            with self.subTest(kw=kw):
                self.assertEqual(self.webhook('sub_new_' + self.wid, **kw)['outcome'], 'rejected')
        self.assertEqual(self.webhook('sub_new_' + self.wid)['outcome'], 'applied')
        self.assertEqual(self.webhook('sub_old_' + self.wid, created=NOW + 1)['outcome'], 'rejected')
        with connection() as db:
            self.assertEqual(db.execute('SELECT provider_subscription_id FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 'sub_new_' + self.wid)

    def test_ended_reenroll_still_requires_catalog_price_and_checkout_gates(self):
        self.seed_creator(status='expired')
        with connection() as db: db.execute("UPDATE pr_plan_terms SET new_checkout_enabled=false WHERE id='creator-v1'")
        with self.assertRaises(AlphaError): self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET new_checkout_enabled=true WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='proposed',provider_price_id=NULL WHERE id='creator-49-v1'")
        with self.assertRaises(AlphaError): self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        self.assertEqual(self.stripe_calls, [])

    def test_bootstrap_sql_service_only_verified_and_deleted_identity_denial(self):
        with connection() as db:
            exists = db.execute("SELECT to_regprocedure('public.pr_bootstrap_free(uuid)') IS NOT NULL").fetchone()[0]
            self.assertTrue(exists, 'Free needs a service-only bootstrap that never creates a trial')
            for role in ('anon', 'authenticated'):
                self.assertFalse(db.execute("SELECT has_function_privilege(%s,'public.pr_bootstrap_free(uuid)','execute')", (role,)).fetchone()[0])
            self.assertTrue(db.execute("SELECT has_function_privilege('service_role','public.pr_bootstrap_free(uuid)','execute')").fetchone()[0])
            for actor in (str(uuid.uuid4()), self.actor):
                if actor == self.actor:
                    db.execute("INSERT INTO pr_account_tombstones(user_id,plan,trial_started_at) VALUES(%s,'studio',now())", (actor,))
                with self.assertRaises(psycopg.errors.RaiseException), db.transaction():
                    db.execute('SELECT pr_bootstrap_free(%s)', (actor,))

    def test_summary_free_creator_and_ended_creator_truthful(self):
        self.bootstrap()
        self.assertEqual(self.service.workspaces('fixture')['workspaces'][0]['plan'], 'free')
        with connection() as db:
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,current_period_end,cancel_at_period_end) VALUES(%s,'creator-v1','stripe','active',to_timestamp(%s),true)", (self.wid, NOW + 1))
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
        self.assertEqual(self.service.workspaces('fixture')['workspaces'][0]['plan'], 'creator')
        self.clock[0] = NOW + 1
        self.assertEqual(self.service.workspaces('fixture')['workspaces'][0]['plan'], 'free')


if __name__ == '__main__':
    unittest.main(verbosity=2)
