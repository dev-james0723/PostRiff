"""The corrected fleet growth report on disposable PG17 (PRD R-MET-02, AC32/AC33): cash-paid conversion and retention from
payment history, status counts kept only as an operating view."""
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import psycopg  # noqa: E402
from postriff_phase2.coworker import growth  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
DAY = 86400


def connection():
    return psycopg.connect(DSN)


class FleetV2(unittest.TestCase):
    def report(self):
        with connection() as db, db.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            return growth.fleet(cur)

    def trial_workspace(self, db, *, ended_days_ago, arm="coworker_prepares"):
        user = str(uuid.uuid4())
        db.execute("INSERT INTO auth.users(id) VALUES(%s)", (user,))
        wid = str(db.execute("SELECT pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        db.execute("UPDATE pr_trials SET expires_at=now()-make_interval(days=>%s) WHERE workspace_id=%s", (ended_days_ago, wid))
        db.execute("INSERT INTO pr_experiment_assignments(experiment,subject_key,variant) VALUES('positioning_2026_10',%s,%s)", (wid, arm))
        return wid

    def grant(self, db, wid, invoice, *, days_ago, amount=5900, live=True, period_days=30, reason="subscription_create", intent=None):
        start = int(time.time()) - days_ago * DAY
        db.execute("INSERT INTO pr_credit_subscription_grants(invoice_id,workspace_id,subscription_id,plan_terms_id,billing_reason,period_start,period_end,amount_cents,currency,"
                   "payment_intent_id,millicredits,livemode,recorded_at) VALUES(%s,%s,'sub_'||%s,'creator-v1',%s,%s,%s,%s,'usd',%s,0,%s,to_timestamp(%s))",
                   (invoice, wid, wid, reason, start, start + period_days * DAY, amount, intent or "pi_" + invoice, live, start))

    def test_a_without_payment_history_tables_everything_is_unavailable_not_zero(self):   # runs first: the file shares one database
        with connection() as db:
            self.trial_workspace(db, ended_days_ago=60, arm="manager_generate")
        report = self.report()
        self.assertIsNone(report["paymentEvidence"]["source"])
        rows = report["positioning_2026_10"]["byArm"]["manager_generate"]
        self.assertEqual(rows["legacy_trial_to_paid"]["coverage"]["numerator"], 0)
        self.assertTrue(all(r["status"] == "proposed_definition_not_activated" for r in rows.values()))
        self.assertIn("weekly_return_rate", report)
        self.assertIn("Not completed work", report["weekly_return_rate"]["label"])

    def test_ac32_ac33_cash_paid_conversion_and_retention_from_history(self):
        with connection() as db:
            for name in ("020_credit_quotes.sql", "021_credit_purchases.sql", "022_credit_payment_lifecycle.sql", "048_pricing_credit_catalog_v2.sql"):
                db.execute((ROOT / "migrations/postriff" / name).read_text())
            paid = self.trial_workspace(db, ended_days_ago=120)
            active_unpaid = self.trial_workspace(db, ended_days_ago=120)
            test_mode = self.trial_workspace(db, ended_days_ago=120)
            zero_then_paid = self.trial_workspace(db, ended_days_ago=120)
            # paid: first payment 110 days ago, renewed twice (covers D30 and D60), lapsed before D90
            self.grant(db, paid, "inv_p1", days_ago=110)
            self.grant(db, paid, "inv_p2", days_ago=80, reason="subscription_cycle")
            self.grant(db, paid, "inv_p3", days_ago=50, reason="subscription_cycle")
            # an "active" subscription that never paid: status says active, history says nothing
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status) VALUES(%s,'studio-v1','stripe','active') "
                       "ON CONFLICT(workspace_id) DO UPDATE SET status='active',provider='stripe'", (active_unpaid,))
            self.grant(db, test_mode, "inv_t1", days_ago=110, live=False)
            self.grant(db, zero_then_paid, "inv_z0", days_ago=110, amount=0)
            self.grant(db, zero_then_paid, "inv_z1", days_ago=100, reason="subscription_cycle")
            self.grant(db, zero_then_paid, "inv_z2", days_ago=70, reason="subscription_cycle")   # renewed once: covers D30, lapses before D60
            recent = self.trial_workspace(db, ended_days_ago=5)
            self.grant(db, recent, "inv_r1", days_ago=20)   # D30 is still in the future: immature, excluded
        report = self.report()
        rows = report["positioning_2026_10"]["byArm"]["coworker_prepares"]
        conversion = rows["legacy_trial_to_paid"]
        # paid + zero-then-paid convert; active-unpaid and test-mode do not; the recent trial's window is still open
        self.assertEqual((conversion["coverage"]["numerator"], conversion["coverage"]["denominator"]), (2, 4))
        self.assertEqual(conversion["measures"]["immatureExcluded"], 1)
        d30, d60, d90 = (rows[f"cash_paid_retention_d{n}"] for n in (30, 60, 90))
        self.assertEqual((d30["coverage"]["numerator"], d30["coverage"]["denominator"], d30["measures"]["immatureExcluded"]), (2, 2, 1))
        self.assertEqual((d60["coverage"]["numerator"], d60["coverage"]["denominator"]), (1, 2))
        self.assertEqual((d90["coverage"]["numerator"], d90["coverage"]["denominator"]), (0, 2))   # both lapsed before day 90
        self.assertEqual(report["paymentEvidence"]["source"], "pr_credit_subscription_grants")
        self.assertEqual(conversion["dataState"], "partial")   # legacy-plan invoices are not in the grants table
        self.assertTrue({"legacy_plan_invoices_not_recorded", "credit_plan_grants_only"} & set(conversion["reason"].split(",")))
        self.assertIn("immature_windows_excluded", conversion["reason"].split(","))
        self.assertEqual(report["subscriptions"]["active"], 1)    # the status view still says active — under its own name
        self.assertIn("not conversion", report["subscriptions"]["label"])


if __name__ == "__main__":
    unittest.main()
