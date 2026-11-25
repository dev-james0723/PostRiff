"""Actual owned PostgreSQL: one isolated synthetic known overrun stops future spending.

This scenario intentionally exhausts the shared global budget, so its cluster is
separate from the other image/writer scenarios. No production/provider calls.
"""
import unittest
import postgres_image_credits_v2 as fixtures


class LargeActualCost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ImageCreditV2.setUpClass()

    def test_storage_safe_large_known_overrun_settles_actual_platform_cost(self):
        f = fixtures.ImageCreditV2(methodName='test_free_has_no_general_paid_image_funding')
        f.setUp()
        f.paid()
        f.response['body']['providerMetadata']['gateway']['cost'] = 2_000_000_000.0
        f.run_image(f.quote(f.request()))
        self.assertEqual((f.wallet()['heldMilliCredits'], f.wallet()['usedMilliCredits']), (0, 30_000))
        with fixtures.connection() as db:
            row = db.execute("SELECT actual_usd_micro,meta->'credits'->>'absorbed' FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (f.wid,)).fetchone()
            self.assertEqual(row, (2_000_000_000_000_000, '599999999970000'))
            budget = db.execute("SELECT spent_usd_micro,stop_usd_micro FROM pr_budgets WHERE scope='global'").fetchone()
            self.assertGreater(budget[0], budget[1])
        self.assertEqual(len(f.calls), 1)


if __name__ == '__main__':
    unittest.main()
