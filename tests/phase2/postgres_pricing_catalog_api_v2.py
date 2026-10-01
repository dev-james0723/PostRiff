"""Pricing v2 Task 6 on disposable PG17: one catalog projection and explicit billing modes (PRD AC01, AC05).

Breaks caught: hidden Starter/Studio or legacy packages offered for new sale, a 49/79 subscriber shown 59, billing mode
inferred from a price or a batch count, a non-owner seeing an offer, and public vs in-app catalogs disagreeing.
"""
import time
import unittest
import uuid
from pathlib import Path

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.plan_pricing import CATALOG_VERSION_LEGACY, CATALOG_VERSION_V2, public_catalog

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = int(time.time())


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class CatalogApiV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == 55438
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '048_pricing_credit_catalog_v2.sql', '050_free_lifecycle_bootstrap.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def setUp(self):
        self.owner, self.viewer = str(uuid.uuid4()), str(uuid.uuid4())
        with connection() as db:
            for user in (self.owner, self.viewer):
                db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (self.viewer,))
            self.free = str(db.execute('SELECT pr_bootstrap_free(%s)', (self.owner,)).fetchone()[0])
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (self.free, self.viewer))
            db.execute("UPDATE pr_plan_terms SET status='proposed',catalog_state='public',new_checkout_enabled=false WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='proposed',provider_price_id=NULL")
        self.tokens = {'owner': self.owner, 'viewer': self.viewer}

        def verify(token):
            if token not in self.tokens:
                raise AlphaError('Denied', 403)
            return self.tokens[token]
        verify.session_id = lambda token, principal: 'task6-' + principal
        verify.auth_time = lambda token, principal: float(NOW)
        self.verify = verify

    def service(self, enabled=True):
        return HostedWorkspaceService(connection, self.verify, clock=lambda: float(NOW), public_base_url='https://app.example.test',
                                      email_lookup=lambda actor: 'owner@example.test', credits_enabled=True, pricing_v2_enabled=enabled)

    def catalog(self, enabled=True):
        with connection() as db:
            return public_catalog(db.cursor(), enabled)

    def test_ac01_v2_catalog_is_free_and_creator_only_with_default_59(self):
        with connection() as db:   # even an operator mistake that activates hidden packages must not surface them
            db.execute("UPDATE pr_plan_terms SET status='active' WHERE id IN ('starter-v1','studio-v2')")
        value = self.catalog()
        self.assertEqual(value['catalogVersion'], CATALOG_VERSION_V2)
        self.assertEqual([p['id'] for p in value['plans']], ['free-v1', 'creator-v1'])
        free, creator = value['plans']
        self.assertEqual((free['priceCents'], free['monthlyCredits'], free['checkout']), (0, 0, 'not_applicable'))
        self.assertEqual(free['firstValue'], {'postDoctorRuns': 1, 'genomeAnalyses': 1, 'genomeMaxPosts': 20})
        self.assertEqual((creator['priceCents'], creator['monthlyCredits'], creator['priceVariantId']), (5900, 3500, 'creator-59-v1'))
        self.assertEqual(creator['checkout'], 'not_yet_available')
        self.assertEqual(value['creditsPerUsd'], 300)
        self.assertFalse(value['topUps']['available'])

    def test_ac01_checkout_only_after_full_activation(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")
        self.assertEqual(self.catalog()['plans'][1]['checkout'], 'not_yet_available')   # variant still unmapped
        with connection() as db:
            db.execute("UPDATE pr_plan_price_variants SET status='active',provider_price_id='price_synthetic_'||variant_key")
        self.assertEqual(self.catalog()['plans'][1]['checkout'], 'available')

    def test_legacy_catalog_when_v2_is_off(self):
        value = self.catalog(enabled=False)
        self.assertEqual(value['catalogVersion'], CATALOG_VERSION_LEGACY)
        self.assertEqual({p['id'] for p in value['plans']}, {'trial-v1', 'studio-v1', 'assist-v1'})
        self.assertNotIn('creditsPerUsd', value)

    def test_ac05_usage_mode_terms_and_offer_agree_with_catalog(self):
        view = self.service().usage(self.free, 'owner')
        self.assertEqual(view['billingMode'], 'free_preview')
        self.assertEqual(view['catalogVersion'], CATALOG_VERSION_V2)
        offered = {t['id'] for t in view['planTerms']}
        self.assertEqual(offered, {p['id'] for p in self.catalog()['plans']})
        self.assertNotIn('starter-v1', offered)
        self.assertNotIn('studio-v1', offered)
        self.assertEqual(view['creatorOffer'], {'planTermsId': 'creator-v1', 'priceVariantId': 'creator-59-v1', 'amountCents': 5900, 'currency': 'USD'})

    def test_ac05_non_owner_sees_no_offer_and_no_checkout(self):
        view = self.service().usage(self.free, 'viewer')
        self.assertIsNone(view['creatorOffer'])
        self.assertFalse(view['billing']['checkoutAvailable'])

    def test_ac05_variant_subscriber_sees_their_price_and_managed_credits_mode(self):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")
            db.execute("UPDATE pr_plan_price_variants SET status='active',provider_price_id='price_synthetic_'||variant_key")
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,provider_subscription_id,status,price_variant_id) "
                       "VALUES(%s,'creator-v1','stripe','sub_x','active','creator-79-v1') ON CONFLICT (workspace_id) DO UPDATE SET "
                       "plan_terms_id='creator-v1',status='active',price_variant_id='creator-79-v1',provider='stripe',provider_subscription_id='sub_x'", (self.free,))
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1' WHERE workspace_id=%s", (self.free,))
        view = self.service().usage(self.free, 'owner')
        self.assertEqual(view['billingMode'], 'managed_credits')
        self.assertEqual((view['subscription']['priceCents'], view['subscription']['priceVariantId']), (7900, 'creator-79-v1'))
        self.assertIsNone(view['creatorOffer'])

    def test_legacy_mode_hides_v2_rows(self):
        actor = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (actor,))
            legacy = str(db.execute("SELECT pr_bootstrap(%s,'studio')", (actor,)).fetchone()[0])
        self.tokens['legacy'] = actor
        view = self.service(enabled=False).usage(legacy, 'legacy')
        self.assertEqual(view['billingMode'], 'legacy_allowances')
        self.assertEqual(view['catalogVersion'], CATALOG_VERSION_LEGACY)
        offered = {t['id'] for t in view['planTerms']}
        self.assertFalse(offered & {'free-v1', 'starter-v1', 'creator-v1', 'studio-v2'})
        self.assertIsNone(view['creatorOffer'])


if __name__ == '__main__':
    unittest.main()
