"""Pricing v2 Task 10 on disposable PG17 (PRD R-COM-01, AC01): top-up candidates stay unsellable. Neither the purchase
flag nor an operator activating a v2 pack row (with a price id) makes one listable or orderable; activation needs a
separate commercial decision and code change."""
import unittest
import uuid
from pathlib import Path

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_purchases import CreditPurchases
from postriff_phase2.credit_wallet import CreditBook

ROOT = Path(__file__).resolve().parents[2]
DSN = "host=127.0.0.1 port=55438 dbname=postgres"


def connection():
    return psycopg.connect(DSN)


class Provider:
    def __init__(self, live):
        self.live = live


class TopUpsDisabled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            for name in ("020_credit_quotes.sql", "021_credit_purchases.sql", "022_credit_payment_lifecycle.sql",
                         "048_pricing_credit_catalog_v2.sql", "050_free_lifecycle_bootstrap.sql"):
                db.execute((ROOT / "migrations/postriff" / name).read_text())
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")
            user = str(uuid.uuid4())
            db.execute("INSERT INTO auth.users(id) VALUES(%s)", (user,))
            cls.wid = str(db.execute("SELECT pr_bootstrap_free(%s)", (user,)).fetchone()[0])
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (cls.wid,))
            cls.actor = user

    def purchases(self, live):
        return CreditPurchases(CreditBook(), Provider(live))

    def test_ac01_v2_packs_are_not_listed_even_when_activated(self):
        for live in (False, True):
            with connection() as db, db.cursor() as cur:
                self.assertEqual(self.purchases(live).packs(cur, self.wid), [])
        with connection() as db:
            db.execute("UPDATE pr_credit_packs SET active=true,price_id='price_synthetic_'||id,livemode=false WHERE policy_id='credits-v2-2026-09-28'")
        with connection() as db, db.cursor() as cur:
            self.assertEqual(self.purchases(False).packs(cur, self.wid), [])

    def test_ac01_ordering_a_v2_pack_is_refused_before_any_checkout(self):
        with connection() as db:
            db.execute("UPDATE pr_credit_packs SET active=true,price_id='price_synthetic_'||id,livemode=false WHERE policy_id='credits-v2-2026-09-28'")
        for pack in ("credits-1000-v2", "credits-2000-v2"):
            with connection() as db, db.cursor() as cur:
                with self.assertRaises(AlphaError) as caught:
                    self.purchases(False).prepare_order(cur, self.wid, self.actor, pack, uuid.uuid4().hex)
                self.assertEqual(caught.exception.status, 409)
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_credit_orders WHERE workspace_id=%s", (self.wid,)).fetchone()[0], 0)

    def test_seeded_v2_packs_cannot_be_activated_without_a_price(self):
        with connection() as db:
            with self.assertRaises(psycopg.errors.CheckViolation):
                db.execute("UPDATE pr_credit_packs SET active=true,price_id=NULL WHERE id='credits-1000-v2'")


if __name__ == "__main__":
    unittest.main()
