"""A known storage-safe provider overrun cannot exceed the user's approved debit."""
import unittest
from postriff_phase2.credit_wallet import CreditBook
from postriff_phase2.credit_meter import millicredits


class Cursor:
    def execute(self, _query, _params):
        pass
    def fetchone(self):
        return ({'policy': 'credits-v2-2026-09-28', 'maximum': 30_000,
                 'allocations': [{'grantId': 'synthetic-grant', 'milli': 30_000}]},)


class ActualCostDomain(unittest.TestCase):
    def test_storage_safe_large_overrun_keeps_user_cap_and_platform_loss(self):
        try:
            result = CreditBook().settlement(Cursor(), 'synthetic-workspace', 'synthetic-reservation', 'completed', 2_000_000_000_000_000)
        except ValueError as error:
            self.fail('Known bigint-safe actual cost must settle under the user cap: ' + str(error))
        self.assertEqual(result['used'], 30_000)
        self.assertEqual(result['absorbed'], 599_999_999_970_000)
        self.assertEqual(result['released'], 0)

    def test_largest_storage_safe_cost_is_bounded_customer_debit(self):
        try:
            result = CreditBook().settlement(Cursor(), 'synthetic-workspace', 'synthetic-reservation', 'completed', 2**63 - 1)
        except ValueError as error:
            self.fail('The actual-cost domain must match PostgreSQL bigint: ' + str(error))
        self.assertEqual(result['used'], 30_000)
        self.assertGreater(result['absorbed'], 30_000)
        self.assertLess(result['absorbed'], 2**63)

    def test_large_known_failure_is_customer_zero(self):
        result = CreditBook().settlement(Cursor(), 'synthetic-workspace', 'synthetic-reservation', 'failed', 2_000_000_000_000_000)
        self.assertEqual((result['used'], result['released'], result['absorbed']), (0, 30_000, 0))

    def test_new_quote_domain_remains_strict(self):
        with self.assertRaises(ValueError):
            millicredits(10**15 + 1)


if __name__ == '__main__':
    unittest.main()
