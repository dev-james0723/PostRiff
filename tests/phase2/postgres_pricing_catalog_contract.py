"""Pricing v2 contract fixture on disposable PG17 (PRD AC05: public, app, checkout and API catalogs agree).

`docs/design/rafii-product-growth/contracts/pricing-catalog-v2.json` is the v2 public catalog exactly as
`plan_pricing.public_catalog` projects it from the rows migration 048 seeds. The web catalog module
(`web/src/config/plans.ts`, tested by `web/tests/pricing-catalog.test.mjs`) must equal the same file, so the database,
the fixture and the public pages cannot drift apart silently.

Breaks caught: a seeded price, credit grant, entitlement, checkout state or note changing in SQL or Python without the
public pages; the in-app Creator offer or plan list disagreeing with the public catalog; the fixture drifting from the
commercial rules (Free US$0 with 0 credits, Creator US$59 with 3,500 credits, 300 credits per US$1, no top-ups).
"""
import json
import time
import unittest
import uuid
from pathlib import Path

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.plan_pricing import CATALOG_VERSION_V2, CREDITS_PER_USD, public_catalog

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'docs/design/rafii-product-growth/contracts/pricing-catalog-v2.json'
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = int(time.time())


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def fixture():
    return json.loads(FIXTURE.read_text())


class PricingCatalogContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == 55438
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '048_pricing_credit_catalog_v2.sql', '050_free_lifecycle_bootstrap.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def test_ac05_seeded_v2_catalog_equals_the_contract_fixture(self):
        with connection() as db:
            catalog = public_catalog(db.cursor(), True)
        self.assertEqual(catalog, fixture())

    def test_contract_fixture_holds_the_commercial_rules(self):
        value = fixture()
        self.assertEqual((value['catalogVersion'], value['pricing'], value['creditsPerUsd']), (CATALOG_VERSION_V2, 'v2', CREDITS_PER_USD))
        self.assertEqual(value['creditsPerUsd'], 300)
        self.assertEqual([p['id'] for p in value['plans']], ['free-v1', 'creator-v1'], 'Free and Creator alone are for sale')
        free, creator = value['plans']
        self.assertEqual((free['priceCents'], free['monthlyCredits'], free['checkout']), (0, 0, 'not_applicable'))
        self.assertEqual(free['firstValue'], {'postDoctorRuns': 1, 'genomeAnalyses': 1, 'genomeMaxPosts': 20})
        self.assertEqual((free['entitlements']['connectedAccounts'], free['entitlements']['brands'], free['entitlements']['members']), (1, 1, 1))
        self.assertEqual((creator['priceCents'], creator['currency'], creator['interval'], creator['monthlyCredits']), (5900, 'USD', 'month', 3500))
        self.assertEqual(creator['priceVariantId'], 'creator-59-v1')
        self.assertEqual(creator['checkout'], 'not_yet_available', 'seeded Creator is proposed: no checkout until activation')
        for plan in value['plans']:
            self.assertEqual(plan['entitlements']['overage'], 'stop')
            self.assertEqual((plan['entitlements']['writingBatches'], plan['entitlements']['mediaCredits']), (0, 0))
        self.assertEqual(value['topUps'], {'available': False, 'reason': 'not_activated'})
        text = json.dumps(value)
        for stale in ('1900', '3900', 'studio', 'assist', 'starter', 'trial'):
            self.assertNotIn(stale, text)

    def test_ac05_in_app_plans_and_creator_offer_agree_with_the_fixture(self):
        owner = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (owner,))
            workspace = str(db.execute('SELECT pr_bootstrap_free(%s)', (owner,)).fetchone()[0])

        def verify(token):
            if token != 'owner':
                raise AlphaError('Denied', 403)
            return owner
        verify.session_id = lambda token, principal: 'contract-' + principal
        verify.auth_time = lambda token, principal: float(NOW)
        service = HostedWorkspaceService(connection, verify, clock=lambda: float(NOW), public_base_url='https://app.example.test',
                                         email_lookup=lambda actor: 'owner@example.test', credits_enabled=True, pricing_v2_enabled=True)
        view = service.usage(workspace, 'owner')
        expected = fixture()
        creator = next(p for p in expected['plans'] if p['plan'] == 'creator')
        self.assertEqual(view['catalogVersion'], expected['catalogVersion'])
        self.assertEqual(view['billingMode'], 'free_preview')
        self.assertEqual({t['id'] for t in view['planTerms']}, {p['id'] for p in expected['plans']})
        self.assertEqual(view['creatorOffer'], {'planTermsId': creator['id'], 'priceVariantId': creator['priceVariantId'],
                                                'amountCents': creator['priceCents'], 'currency': creator['currency']})
        for terms in view['planTerms']:
            plan = next(p for p in expected['plans'] if p['id'] == terms['id'])
            self.assertEqual((terms['plan'], terms['label'], terms['catalogState']), (plan['plan'], plan['label'], 'public'))
            self.assertEqual(terms['entitlements'].get('monthlyCredits', 0), plan['monthlyCredits'])


if __name__ == '__main__':
    unittest.main()
