"""Version identities and arithmetic only; no providers or paid plan activation."""
import unittest
from postriff_phase2 import credit_meter
from postriff_phase2 import credit_purchases


class CreditPolicyV2Tests(unittest.TestCase):
    def test_v2_is_distinct_and_both_identifiers_are_explicitly_supported(self):
        self.assertEqual(credit_meter.POLICY_VERSION, 'credits-candidate-2026-09-23-v1')
        self.assertEqual(getattr(credit_meter, 'V2_POLICY_VERSION', None), 'credits-v2-2026-09-28')
        supported = getattr(credit_meter, 'SUPPORTED_POLICY_VERSIONS', None)
        self.assertIsInstance(supported, frozenset)
        self.assertEqual(supported, frozenset({'credits-candidate-2026-09-23-v1', 'credits-v2-2026-09-28'}))

    def test_historical_preview_and_purchase_import_retain_candidate_meaning(self):
        self.assertEqual(credit_purchases.POLICY_VERSION, 'credits-candidate-2026-09-23-v1')
        quote = credit_meter.quote_task([1_000_000])
        self.assertEqual(quote['policyVersion'], 'credits-candidate-2026-09-23-v1')
        self.assertFalse(quote['billable'])
        self.assertEqual(quote['reservedMilliCredits'], 300_000)

    def test_one_usd_and_fractional_task_use_one_rounding_boundary(self):
        self.assertEqual(credit_meter.CREDITS_PER_USD, 300)
        self.assertEqual(credit_meter.millicredits(1_000_000), 300_000)
        self.assertEqual(credit_meter.millicredits(13_000), 3_900)
        quote = credit_meter.quote_task([100, 12_900])
        self.assertEqual(quote['reservedMilliCredits'], 3_900)
        self.assertEqual(sum(credit_meter.millicredits(c) for c in [100, 12_900]), 4_000)
