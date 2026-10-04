"""Task6 projection on owned disposable PG17. Funding and identities are synthetic."""
from local_pg_target import selected_target
import json
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from test_postriff_phase2_hosted import FakeWorker, invoke

ROOT = Path(__file__).resolve().parents[2]
NOW = int(time.time())
JAMES = 'b167161d-37f4-4bc3-ae22-2482c982e5a0'


def connection():
    return psycopg.connect(selected_target().dsn(), client_encoding='utf8')


class OldSchema(unittest.TestCase):
    def test_old_schema_default_off_keeps_legacy_usage(self):
        service = HostedWorkspaceService(connection, lambda token: '00000000-0000-0000-0000-000000000001')
        wid = service.bootstrap('fixture')['workspaceId']
        view = service.usage(wid, 'fixture')
        self.assertEqual(view.get('billingMode'), 'legacy_allowances')
        self.assertIsNone(view['credits'])
        self.assertIsNone(view.get('freePreview'))
        self.assertEqual(view['entitlement']['writingBatchesRemaining'], 10)
        self.assertEqual(view['subscription']['status'], 'trial')
        self.assertIn('assist-v1', {p['id'] for p in view['planTerms']})


class UsageCatalogV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == selected_target().port
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '089_pricing_credit_catalog_v2.sql', '090_free_lifecycle_bootstrap.sql', '091_pricing_public_four_plans.sql', '092_fixed_plan_checkout_approval.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def setUp(self):
        self.now = [float(NOW)]
        self.actor = str(uuid.uuid4())
        self.tokens = {'fixture': self.actor}
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
            db.execute("UPDATE pr_plan_terms SET status='proposed',new_checkout_enabled=false WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='proposed',provider_price_id=NULL")
            db.execute("UPDATE pr_plan_terms SET entitlements=entitlements - 'providerKey' - 'cohort' - 'budgetUsdMicro' WHERE id='creator-v1'")
        def verify(token):
            if token not in self.tokens: raise AlphaError('Verified session required.', 401)
            return self.tokens[token]
        self.verify = verify
        self.service = self.make_service()
        self.wid = self.service.bootstrap('fixture')['workspaceId']
        self.service.growth = GrowthService(self.service, env={'POSTRIFF_GROWTH': '1', 'POSTRIFF_POST_DOCTOR': '1', 'POSTRIFF_GENOME': '1'})
        # Consent is real persisted state; funding approval deliberately absent/default OFF.
        with connection() as db:
            db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{growthConsent}',%s::jsonb) WHERE id=%s",
                       (json.dumps({'routes': ['cloud:vercel-ai-gateway:google/gemini-2.5-flash-lite']}), self.wid))

    def make_service(self, *, credits=True, v2=True):
        return HostedWorkspaceService(connection, self.verify, clock=lambda: self.now[0],
                                      credits_enabled=credits, pricing_v2_enabled=v2)

    def paid(self, terms='creator-v1', variant='creator-49-v1'):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active' WHERE id=%s", (terms,))
            ent = db.execute('SELECT entitlements FROM pr_plan_terms WHERE id=%s', (terms,)).fetchone()[0]
            self.service.billing._reconcile_entitlement(db.cursor(), self.wid, terms, ent, NOW + 600)
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,current_period_end,provider_subscription_id,price_variant_id) "
                       "VALUES(%s,%s,'stripe','active',to_timestamp(%s),%s,%s)",
                       (self.wid, terms, NOW + 600, 'sub_' + self.wid, variant if terms == 'creator-v1' else None))

    def grant(self, key, milli, expiry=None, source='local-synthetic'):
        with connection() as db:
            return self.service.ledger._credit_book.grant(db.cursor(), self.wid, self.actor, key, milli, expiry, source=source)['entryId']

    def view(self, token='fixture'):
        try:
            return self.service.usage(self.wid, token)
        except AlphaError as error:
            if token not in self.tokens: raise
            self.fail('Existing usage must remain readable: ' + str(error))

    def test_free_uses_real_preview_and_no_wallet_or_fake_grant(self):
        view = self.view()
        self.assertEqual(view.get('billingMode'), 'free_preview')
        self.assertIsNone(view['credits'])
        self.assertEqual(view.get('freePreview'), self.service.growth.preview_status(self.wid, 'fixture'))
        for action in view['freePreview'].values():
            self.assertEqual((action['remaining'], action['eligible'], action['reason']), (1, False, 'funding_unavailable'))
        self.assertEqual(view['freePreview']['genome']['maxPosts'], 20)
        with connection() as db:
            db.execute("INSERT INTO pr_post_doctor_runs(workspace_id,request_key,kind,status,fingerprint,context_fingerprint,created_by) "
                       "VALUES(%s,%s,'check','failed','synthetic','synthetic',%s)", (self.wid, str(uuid.uuid4()), self.actor))
        self.assertEqual(self.view()['freePreview']['postDoctor'], {'remaining': 0, 'eligible': False, 'reason': 'used'})

    def test_normal_catalog_is_sanitized_free_creator_only(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET entitlements=entitlements || %s::jsonb WHERE id='creator-v1'",
                       (json.dumps({'providerKey': 'private-marker', 'cohort': ['private-marker'], 'budgetUsdMicro': 123}),))
        view = self.view()
        self.assertEqual({p['id'] for p in view['planTerms']}, {'free-v1', 'starter-v1', 'creator-v1', 'studio-v2'})
        creator = next(p for p in view['planTerms'] if p['id'] == 'creator-v1')
        self.assertEqual((creator['priceCents'], creator['defaultPriceCents'], creator['priceVariantId']), (5900, 5900, 'creator-59-v1'))
        self.assertEqual(creator['entitlements']['monthlyCredits'], 3500)
        self.assertEqual((creator['catalogState'], creator['newCheckoutEnabled'], creator['checkoutAvailable'], creator['status']), ('public', False, False, 'proposed'))
        self.assertNotIn('private-marker', json.dumps(view))
        self.assertNotIn('provider_price_id', json.dumps(view))
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET entitlements=entitlements - 'providerKey' - 'cohort' - 'budgetUsdMicro' WHERE id='creator-v1'")

    def test_current_legacy_19_and_39_visible_but_not_for_sale(self):
        for terms, cents in (('studio-v1', 1900), ('assist-v1', 3900)):
            with self.subTest(terms=terms):
                if terms == 'assist-v1':
                    with connection() as db:
                        db.execute('DELETE FROM pr_subscriptions WHERE workspace_id=%s', (self.wid,))
                self.paid(terms)
                view = self.view()
                self.assertEqual(view.get('billingMode'), 'legacy_allowances')
                self.assertEqual(view['subscription']['priceCents'], cents)
                row = next(p for p in view['planTerms'] if p['id'] == terms)
                self.assertEqual((row['priceCents'], row['catalogState'], row['current'], row['newCheckoutEnabled'], row['checkoutAvailable']), (cents, 'legacy', True, False, False))
                self.assertEqual({p['id'] for p in view['planTerms']}, {'free-v1', 'starter-v1', 'creator-v1', 'studio-v2', terms})

    def test_managed_actual_variant_never_base_price_or_catalog_grant(self):
        self.paid()
        for amount in (49, 59, 79):
            with self.subTest(amount=amount), connection() as db:
                db.execute('UPDATE pr_subscriptions SET price_variant_id=%s WHERE workspace_id=%s', (f'creator-{amount}-v1', self.wid))
            view = self.view()
            self.assertEqual(view.get('billingMode'), 'managed_credits')
            self.assertEqual((view['subscription']['priceCents'], view['subscription']['priceVariantId']), (amount * 100, f'creator-{amount}-v1'))
            creator = next(p for p in view['planTerms'] if p['id'] == 'creator-v1')
            self.assertEqual(creator['priceCents'], amount * 100)
            self.assertEqual(creator['entitlements']['monthlyCredits'], 3500)
            self.assertIsNone(view['credits']['currentPeriodGrantMilliCredits'])
            self.assertIsNone(view['credits']['currentPeriodExpiresAt'])
            self.assertEqual(view['credits']['policy'], V2_POLICY_VERSION)
            self.assertFalse(view['credits']['textOnly'])
        self.assertIsNone(view['freePreview'])

    def test_existing_assignment_stable_when_experiment_off(self):
        with connection() as db:
            db.execute("INSERT INTO pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) VALUES(%s,'creator-beta-v1','creator-79-v1','synthetic')", (self.wid,))
        prices = [next(p for p in self.view()['planTerms'] if p['id'] == 'creator-v1')['priceCents'] for _ in range(2)]
        self.assertEqual(prices, [7900, 7900])

    def test_wallet_gross_verified_period_lifetime_used_hold_purchased_and_debt(self):
        self.paid()
        old = self.grant('old-period', 2000, NOW - 1)
        current = self.grant('current-period', 9000, NOW + 600, 'verified-stripe-invoice')
        purchased = self.grant('purchase', 4000, None, 'verified-stripe-checkout')
        with connection() as db:
            db.execute("INSERT INTO pr_credit_subscription_grants(invoice_id,workspace_id,subscription_id,plan_terms_id,billing_reason,period_start,period_end,amount_cents,currency,millicredits,grant_id,livemode) "
                       "VALUES(%s,%s,%s,'creator-v1','subscription_cycle',%s,%s,4900,'usd',9000,%s,false)",
                       ('in_' + self.wid, self.wid, 'sub_' + self.wid, NOW - 60, NOW + 600, current))
            def entry(key, credit, reservation=None):
                return db.execute("INSERT INTO pr_usage_ledger(workspace_id,kind,dimension,cost_state,idempotency_key,meta,reservation_id) VALUES(%s,'adjust','action','actual',%s,%s::jsonb,%s) RETURNING id::text",
                                  (self.wid, key, json.dumps({'credits': credit}), reservation)).fetchone()[0]
            entry('old-used', {'op': 'settle', 'allocations': [{'grantId': old, 'milli': 1500}]}, str(uuid.uuid4()))
            entry('held', {'op': 'reserve', 'allocations': [{'grantId': current, 'milli': 3000}]})
            entry('current-used', {'op': 'settle', 'allocations': [{'grantId': current, 'milli': 4000}]}, str(uuid.uuid4()))
            entry('refund', {'op': 'reverse', 'grantId': current, 'milli': 5000})
        balance = self.view()['credits']
        self.assertEqual((balance['currentPeriodGrantMilliCredits'], balance['currentPeriodExpiresAt']), (9000, NOW + 600))
        self.assertEqual((balance['usedMilliCredits'], balance['heldMilliCredits'], balance['availableMilliCredits'], balance['debtMilliCredits']), (5500, 3000, 1000, 0))
        self.assertNotIn('lots', balance, 'Customer usage must not expose accounting lots or grant IDs')
        self.assertEqual(balance['purchasedCredits'], [{'available': 1000, 'held': 0, 'expiresAt': None}])
        self.assertNotIn(old, json.dumps(balance)); self.assertNotIn(current, json.dumps(balance)); self.assertNotIn(purchased, json.dumps(balance))

    def test_read_paused_proposed_and_flag_off_keeps_wallet_but_spend_refused(self):
        self.paid()
        self.grant('fund', 10000)
        for status, enabled in (('retired', True), ('proposed', True), ('active', False)):
            with self.subTest(status=status, credits_enabled=enabled):
                with connection() as db:
                    db.execute("UPDATE pr_plan_terms SET status=%s WHERE id='creator-v1'", (status,))
                self.service = self.make_service(credits=enabled)
                view = self.view()
                self.assertEqual(view.get('billingMode'), 'managed_credits')
                self.assertEqual(view['credits']['availableMilliCredits'], 10000)
                self.assertIn('spendAvailable', view['credits'])
                self.assertFalse(view['credits']['spendAvailable'])
                self.assertEqual(view['credits']['spendUnavailableReason'], 'credits_disabled' if not enabled else 'policy_inactive')
                with connection() as db, self.assertRaises(AlphaError):
                    self.service.ledger.reserve(db.cursor(), self.wid, self.actor, 'text_model', 10000, str(uuid.uuid4()), charge_batch=True)

    def test_operator_pause_read_and_no_spend(self):
        self.paid()
        self.grant('fund', 10000)
        with patch.dict('os.environ', {'POSTRIFF_AI_PAUSED': '1'}):
            view = self.view()
            self.assertEqual(view['credits']['availableMilliCredits'], 10000)
            self.assertIn('spendAvailable', view['credits'])
            self.assertFalse(view['credits']['spendAvailable'])
            self.assertEqual(view['credits']['spendUnavailableReason'], 'ai_paused')

    def test_owner_cost_privacy_and_member_prices_balances(self):
        self.paid()
        self.grant('fund', 10000)
        editor = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (editor,))
            db.execute('SELECT pr_bootstrap(%s,\'studio\')', (editor,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.wid, editor))
            db.execute("INSERT INTO pr_usage_ledger(workspace_id,kind,dimension,cost_state,idempotency_key,estimated_usd_micro,actual_usd_micro) VALUES(%s,'adjust','text_model','actual','cost',20000,10000)", (self.wid,))
        self.tokens['editor'] = editor
        owner, member = self.view(), self.view('editor')
        self.assertIsNotNone(owner['budget'])
        self.assertTrue(any('actualUsdMicro' in row for row in owner['ledger']))
        self.assertIsNone(member['budget'])
        self.assertTrue(all('actualUsdMicro' not in row and 'estimatedUsdMicro' not in row for row in member['ledger']))
        self.assertEqual(member['credits'], owner['credits'])
        self.assertEqual(member['subscription']['priceCents'], 4900)
        self.assertFalse(member['billing']['checkoutAvailable'])
        self.assertTrue(all(not p['checkoutAvailable'] for p in member['planTerms']))
        with self.assertRaises(AlphaError): self.view('foreign-token')

    def test_actual_james_exemption_keeps_mode_and_no_credit_charge_authority(self):
        self.paid()
        self.grant('fund', 10000)
        self.tokens['james'] = JAMES
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (JAMES,))
            db.execute('SELECT pr_bootstrap(%s,\'studio\')', (JAMES,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.wid, JAMES))
        with patch.dict('os.environ', {'RAFII_AI_UNLIMITED_USER_IDS': JAMES}):
            view = self.view('james')
            self.assertTrue(view['aiUsageExempt'])
            self.assertEqual(view.get('billingMode'), 'managed_credits')
            self.assertIsNone(view['credits'])
            self.assertFalse(self.view()['aiUsageExempt'])
            with connection() as db, self.assertRaises(AlphaError):
                self.service.ledger.reserve(db.cursor(), self.wid, JAMES, 'text_model', 10000, str(uuid.uuid4()), charge_batch=True)

    def test_first_expired_view_uses_existing_lifecycle_before_projection(self):
        self.paid()
        self.grant('fund', 10000, NOW + 600)
        with connection() as db:
            db.execute('UPDATE pr_subscriptions SET cancel_at_period_end=true WHERE workspace_id=%s', (self.wid,))
        self.now[0] = NOW + 601
        view = self.view()
        self.assertEqual(view.get('billingMode'), 'free_preview')
        self.assertEqual(view['entitlement']['planTermsId'], 'free-v1')
        self.assertIsNone(view['credits'])

    def test_usage_http_keeps_exact_contract(self):
        app = HostedApplication(self.service, FakeWorker(), {'provider': 'dev', 'flow': 'dev'}, 'c' * 24)
        token = 't' * 32
        self.tokens[token] = self.actor
        status, _, body = invoke(app, 'GET', f'/api/workspaces/{self.wid}/usage', headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(status, 200)
        self.assertEqual(body.get('billingMode'), 'free_preview')
        self.assertEqual(body.get('freePreview'), self.service.growth.preview_status(self.wid, token))


if __name__ == '__main__':
    unittest.main(verbosity=2)
