"""Review fixes on actual hosted+PG callers. All transports are in-process doubles."""
import hashlib
import hmac
import json
import unittest
import uuid
from urllib.parse import parse_qs, urlparse

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault
import postgres_free_lifecycle_v2 as lifecycle_tests

connection = lifecycle_tests.connection
NOW = lifecycle_tests.NOW


class SocialDouble:
    platform = 'LinkedIn'
    capability_version = 1
    production_reviewed = True
    native_schedule = False
    assisted_fallback = True

    def __init__(self):
        self.account = 'first'
        self.calls = []

    def capability_scopes(self, capability):
        return ['openid', 'w_member_social']

    def explain(self, capability):
        return 'Synthetic connection for local capacity validation.'

    def authorize_url(self, redirect, state, challenge, scopes):
        return 'https://provider.example.test/auth?state=' + state

    def exchange(self, code, verifier, redirect):
        assert code == 'synthetic-code' and len(verifier) >= 43
        self.calls.append(('exchange', self.account))
        return {'accessToken': 'synthetic-access', 'scopes': ['openid', 'w_member_social'], 'expiresIn': 3600}

    def identity(self, token):
        assert token == 'synthetic-access'
        self.calls.append(('identity', self.account))
        return {'providerAccountId': 'synthetic-' + self.account, 'handle': self.account, 'accountType': 'member'}


class ReviewFixes(unittest.TestCase):
    # Reuse only the existing fixture methods, not its already-verified test matrix.
    setUp = lifecycle_tests.FreeLifecycle.setUp
    make_service = lifecycle_tests.FreeLifecycle.make_service
    bootstrap = lifecycle_tests.FreeLifecycle.bootstrap
    seed_creator = lifecycle_tests.FreeLifecycle.seed_creator
    entitlement = lifecycle_tests.FreeLifecycle.entitlement
    webhook = lifecycle_tests.FreeLifecycle.webhook

    @classmethod
    def setUpClass(cls):
        lifecycle_tests.FreeLifecycle.setUpClass()

    def legacy_prices(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active',provider_price_id='price_fix_'||id WHERE id IN ('studio-v1','assist-v1')")

    def checkout_headers(self):
        captured = []
        transport = self.provider.transport
        def record(method, url, headers=None, form=None):
            if method != 'GET':   # checkout sessions only; the earlier-subscription status read carries no key
                captured.append(headers)
            return transport(method, url, headers=headers, form=form)
        self.provider.transport = record
        return captured

    def signed_event(self, kind, obj, created=None):
        body = json.dumps({'id': 'evt_fix_' + str(uuid.uuid4()), 'type': kind,
            'created': NOW if created is None else created, 'livemode': False,
            'data': {'object': obj}}).encode()
        timestamp = int(self.clock[0])
        signature = hmac.new(b'whsec_synthetic', f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
        return self.service.billing_webhook(f't={timestamp},v1={signature}', body)

    def test_ended_creator_incompatible_legacy_checkout_refused_in_both_flags(self):
        self.seed_creator(status='cancelled')
        self.legacy_prices()
        for enabled in (False, True):
            self.service = self.make_service(enabled)
            for terms in ('studio-v1', 'assist-v1'):
                with self.subTest(enabled=enabled, terms=terms):
                    before = len(self.stripe_calls)
                    with self.assertRaises(AlphaError) as caught:
                        self.service.billing_checkout(self.wid, 'fixture', terms)
                    self.assertEqual(caught.exception.status, 409)
                    self.assertEqual(len(self.stripe_calls), before)
        with connection() as db:
            self.assertEqual(db.execute('SELECT plan_terms_id,price_variant_id,provider_customer_id,provider_subscription_id FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone(),
                ('creator-v1', 'creator-49-v1', 'cus_' + self.wid, 'sub_old_' + self.wid))

    def test_defaultoff_genuine_legacy_acquisition_and_ended_replacement_still_work(self):
        self.bootstrap(False)
        self.legacy_prices()
        first = self.service.billing_checkout(self.wid, 'fixture', 'studio-v1')
        self.assertEqual(first['sessionId'], 'cs_task4')
        self.assertEqual(self.stripe_calls[-1][1]['line_items[0][price]'], 'price_fix_studio-v1')
        self.assertIn('customer_email', self.stripe_calls[-1][1])
        with connection() as db:
            self.service.ledger.ensure_entitlement(db.cursor(), self.wid, None)
            db.execute("UPDATE pr_subscriptions SET provider='stripe',plan_terms_id='studio-v1',status='cancelled',provider_customer_id='cus_legacy_fix',provider_subscription_id='sub_legacy_ended' WHERE workspace_id=%s", (self.wid,))
        replacement = self.service.billing_checkout(self.wid, 'fixture', 'assist-v1')
        self.assertEqual(replacement['sessionId'], 'cs_task4')
        self.assertEqual(self.stripe_calls[-1][1]['customer'], 'cus_legacy_fix')
        self.assertEqual(self.stripe_calls[-1][1]['line_items[0][price]'], 'price_fix_assist-v1')

    def test_distinct_ended_bindings_same_hour_have_distinct_keys_and_retry_is_stable(self):
        self.seed_creator(status='cancelled')
        self.clock[0] = NOW // 3600 * 3600 + 100
        headers = self.checkout_headers()
        for _ in range(2): self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        first = headers[-1]['Idempotency-Key']
        self.assertEqual(first, headers[-2]['Idempotency-Key'])
        with connection() as db:
            db.execute('UPDATE pr_subscriptions SET provider_subscription_id=%s WHERE workspace_id=%s', ('sub_second_ended_' + self.wid, self.wid))
        self.clock[0] += 60
        for _ in range(2): self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        second = headers[-1]['Idempotency-Key']
        self.assertEqual(second, headers[-2]['Idempotency-Key'])
        self.assertNotEqual(first, second)
        self.assertRegex(second, r'^[0-9a-f]{64}$')
        self.assertNotIn(self.wid, second)
        self.assertEqual(self.stripe_calls[0][1], self.stripe_calls[-1][1])

    def test_same_ended_binding_retry_across_hour_keeps_key(self):
        self.seed_creator(status='cancelled')
        headers = self.checkout_headers()
        self.clock[0] = NOW // 3600 * 3600 + 3590
        self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        self.clock[0] += 20
        self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        self.assertEqual(headers[0]['Idempotency-Key'], headers[1]['Idempotency-Key'])

    def test_initial_purchase_and_ended_replacement_same_hour_cannot_collide(self):
        self.bootstrap()
        self.clock[0] = NOW // 3600 * 3600 + 100
        headers = self.checkout_headers()
        self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        with connection() as db:
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,provider_customer_id,provider_subscription_id,price_variant_id) VALUES(%s,'creator-v1','stripe','cancelled',%s,%s,'creator-59-v1')",
                (self.wid, 'cus_' + self.wid, 'sub_initial_ended_' + self.wid))
        self.clock[0] += 60
        self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        self.assertNotEqual(headers[0]['Idempotency-Key'], headers[1]['Idempotency-Key'])
        self.assertIn('customer_email', self.stripe_calls[0][1])
        self.assertEqual(self.stripe_calls[1][1]['customer'], 'cus_' + self.wid)

    def completion_then_start(self, invoice=False):
        self.seed_creator(status='cancelled')
        self.service.billing_checkout(self.wid, 'fixture', 'creator-v1')
        new = 'sub_after_completion_' + self.wid
        customer = 'cus_' + self.wid
        metadata = {'workspace_id': self.wid, 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-49-v1'}
        with connection() as db:
            before = db.execute('SELECT plan_terms_id,price_variant_id,provider_customer_id,provider_subscription_id,status,last_event_at FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone()
        result = self.signed_event('checkout.session.completed', {'id': 'cs_completion_fix', 'mode': 'subscription',
            'client_reference_id': self.wid, 'metadata': metadata, 'customer': customer, 'subscription': new})
        self.assertEqual(result['outcome'], 'rejected')
        with connection() as db:
            self.assertEqual(before, db.execute('SELECT plan_terms_id,price_variant_id,provider_customer_id,provider_subscription_id,status,last_event_at FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM pr_credit_subscription_grants WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)
        if invoice:
            result = self.signed_event('invoice.paid', {'id': 'in_verified_synthetic_' + self.wid,
                'subscription': new, 'customer': customer, 'status': 'paid', 'paid': True,
                'amount_paid': 4900, 'currency': 'usd', 'billing_reason': 'subscription_create',
                'subscription_details': {'metadata': metadata},
                'lines': {'data': [{'price': 'price_task4_49', 'period': {'start': NOW, 'end': NOW + 300}}]}}, created=NOW + 1)
        else:
            result = self.webhook(new, created=NOW + 1)
        self.assertEqual(result['outcome'], 'applied')
        with connection() as db:
            self.assertEqual(db.execute('SELECT provider_subscription_id,price_variant_id,status FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,)).fetchone(), (new, 'creator-49-v1', 'active'))
            self.assertEqual(db.execute('SELECT count(*) FROM pr_credit_subscription_grants WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1 if invoice else 0)
        self.assertEqual(self.entitlement()[0], 'creator-v1')

    def test_completion_alone_no_binding_or_grant_matching_subscription_start_fulfills(self):
        self.completion_then_start()

    def test_completion_alone_no_binding_or_grant_matching_create_invoice_fulfills(self):
        self.completion_then_start(invoice=True)

    def social_trial(self, enabled=True):
        self.bootstrap(False)
        with connection() as db:
            self.service.ledger.ensure_entitlement(db.cursor(), self.wid, None)
        self.service = self.make_service(enabled)
        self.adapter = SocialDouble()
        self.service.oauth.providers = {'linkedin': self.adapter}
        self.service.oauth.vault = CredentialVault(CredentialVault.generate_key())

    def connect(self, account):
        self.adapter.account = account
        started = self.service.oauth.start(self.wid, 'fixture', 'linkedin', 'publish')
        state = parse_qs(urlparse(started['authorizeUrl']).query)['state'][0]
        return self.service.oauth.complete(self.wid, 'fixture', 'linkedin', state, 'synthetic-code')

    def expire_trial(self):
        with connection() as db:
            db.execute('UPDATE pr_trials SET expires_at=to_timestamp(%s) WHERE workspace_id=%s', (NOW + 10, self.wid))
            db.execute('UPDATE pr_subscriptions SET current_period_end=to_timestamp(%s) WHERE workspace_id=%s', (NOW + 10, self.wid))
        self.clock[0] = NOW + 10

    def test_expired_trial_direct_second_oauth_account_before_usage_denied(self):
        self.social_trial()
        first = self.connect('first')
        self.expire_trial()
        with self.assertRaises(AlphaError) as caught:
            self.connect('second')
        self.assertEqual(caught.exception.code, 'plan_limit_reached')
        with connection() as db:
            self.assertEqual(db.execute('SELECT connection_id FROM pr_encrypted_credentials WHERE workspace_id=%s AND revoked_at IS NULL', (self.wid,)).fetchall(), [(first['connectionId'],)])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.stripe_calls, [])

    def test_expired_trial_existing_oauth_account_reauthorization_keeps_history_and_free(self):
        self.social_trial()
        first = self.connect('first')
        self.expire_trial()
        second = self.connect('first')
        self.assertEqual(first['connectionId'], second['connectionId'])
        self.assertEqual(self.entitlement()[:2], ('free-v1', 'free'))
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_encrypted_credentials WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)

    def test_active_trial_second_oauth_account_retains_two_account_allowance(self):
        self.social_trial()
        self.assertTrue(self.connect('first')['connected'])
        self.assertTrue(self.connect('second')['connected'])
        with self.assertRaises(AlphaError): self.connect('third')
        self.assertEqual(self.entitlement()[0], 'trial-v1')

    def test_active_legacy_second_third_oauth_accounts_and_existing_reauth_retained(self):
        self.social_trial()
        with connection() as db:
            ent = db.execute("SELECT entitlements FROM pr_plan_terms WHERE id='assist-v1'").fetchone()[0]
            self.service.billing._reconcile_entitlement(db.cursor(), self.wid, 'assist-v1', ent, NOW + 300)
            db.execute("UPDATE pr_subscriptions SET plan_terms_id='assist-v1',status='active' WHERE workspace_id=%s", (self.wid,))
        for name in ('first', 'second', 'third'): self.assertTrue(self.connect(name)['connected'])
        with self.assertRaises(AlphaError): self.connect('fourth')
        self.assertTrue(self.connect('first')['connected'])
        self.assertEqual(self.entitlement()[0], 'assist-v1')

    def test_defaultoff_expired_trial_connection_retains_legacy_path(self):
        self.social_trial(False)
        self.connect('first')
        self.expire_trial()
        self.assertTrue(self.connect('second')['connected'])
        self.assertEqual(self.entitlement()[0], 'trial-v1')

    def record_capacity_derivation(self):
        values = []
        original = self.service.ledger.ensure_entitlement
        def record(cur, wid, plan):
            result = original(cur, wid, plan)
            values.append(result['planTermsId'])
            return result
        self.service.ledger.ensure_entitlement = record
        return values

    def test_expired_trial_member_invite_uses_configured_free_ledger(self):
        self.social_trial()
        self.expire_trial()
        values = self.record_capacity_derivation()
        with self.assertRaises(AlphaError) as caught:
            self.service.invite(self.wid, 'fixture', 'synthetic@example.test', 'viewer', {})
        self.assertEqual(caught.exception.code, 'plan_limit_reached')
        self.assertEqual(values, ['free-v1'])
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_invitations WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_expired_trial_member_join_uses_configured_free_ledger(self):
        self.social_trial()
        self.expire_trial()
        values = self.record_capacity_derivation()
        guest = str(uuid.uuid4())
        raw = 'synthetic-invitation-token-for-task4-fix'
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (guest,))
            db.execute("INSERT INTO pr_invitations(workspace_id,email,role,permissions,token_hash,created_by,expires_at) VALUES(%s,'synthetic@example.test','viewer','{}',%s,%s,now()+interval '1 hour')", (self.wid, hashlib.sha256(raw.encode()).hexdigest(), self.actor))
        original = self.verify
        self.service.verify_session = lambda token: guest if token == 'guest' else original(token)
        with self.assertRaises(AlphaError) as caught:
            self.service.accept_invitation('guest', raw)
        self.assertEqual(caught.exception.code, 'plan_limit_reached')
        self.assertEqual(values, ['free-v1'])
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_memberships WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)
            self.assertIsNone(db.execute('SELECT accepted_at FROM pr_invitations WHERE workspace_id=%s', (self.wid,)).fetchone()[0])

    def test_active_creator_no_trial_legacy_command_stays_guarded_truthfully(self):
        snap = self.bootstrap()
        with connection() as db:
            ent = db.execute("SELECT entitlements FROM pr_plan_terms WHERE id='creator-v1'").fetchone()[0]
            self.service.billing._reconcile_entitlement(db.cursor(), self.wid, 'creator-v1', ent, NOW + 300)
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',to_timestamp(%s))", (self.wid, NOW + 300))
        for action in ('generate', 'adapt'):
            with self.subTest(action=action), self.assertRaises(AlphaError) as caught:
                self.service.mutate(self.wid, 'fixture', snap['revision'], action, {})
            self.assertEqual(caught.exception.status, 402)
            self.assertNotIn('Free', str(caught.exception))
            self.assertIn('dedicated', str(caught.exception).lower())
        self.assertEqual(self.entitlement()[0], 'creator-v1')
        self.assertNotIn('trial', self.service.get(self.wid, 'fixture')['state']['phase2'])
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
