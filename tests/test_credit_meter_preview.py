"""Candidate credit arithmetic only. No live wallet, payment or provider is touched."""
import unittest
try:
    from postriff_phase2 import credit_meter
except ImportError:
    credit_meter = None

class CreditMeterTests(unittest.TestCase):
    def meter(self):
        self.assertIsNotNone(credit_meter, 'A versioned credit calculator must exist')
        return credit_meter

    def test_cost_conversion_uses_integer_arithmetic(self):
        meter = self.meter()
        self.assertEqual(meter.millicredits(10_000), 3_000)
        self.assertEqual(meter.millicredits(50_000), 15_000)
        self.assertEqual(meter.millicredits(0), 0)

    def test_round_once_after_aggregating_the_task(self):
        meter = self.meter()
        quote = meter.quote_task([100, 100])
        self.assertEqual(quote['reservedMilliCredits'], 100)
        self.assertEqual(quote['billable'], False)

    def test_invalid_amounts_are_rejected(self):
        meter = self.meter()
        for amount in [-1, True, 1.5, '100', float('nan')]:
            with self.assertRaises(ValueError): meter.millicredits(amount)

    def test_unknown_cost_is_pending_not_zero(self):
        meter = self.meter(); quote = meter.quote_task([50_000])
        result = meter.settle_preview(quote, None, 'unknown')
        self.assertIsNone(result['usedMilliCredits'])
        self.assertEqual(result['heldMilliCredits'], 15_000)

    def test_known_cost_releases_unused_reservation(self):
        meter = self.meter(); quote = meter.quote_task([50_000])
        result = meter.settle_preview(quote, 10_000, 'completed')
        self.assertEqual((result['usedMilliCredits'], result['releasedMilliCredits']), (3_000, 12_000))

    def test_failed_task_does_not_charge_customer(self):
        meter = self.meter(); result = meter.settle_preview(meter.quote_task([50_000]), 10_000, 'failed')
        self.assertEqual(result['usedMilliCredits'], 0)
        self.assertEqual(result['providerCostUsdMicro'], 10_000)

    def test_settlement_never_exceeds_accepted_quote(self):
        meter = self.meter(); result = meter.settle_preview(meter.quote_task([10_000]), 50_000, 'completed')
        self.assertEqual(result['usedMilliCredits'], 3_000)
        self.assertEqual(result['absorbedMilliCredits'], 12_000)

    def test_byok_and_cli_model_cost_is_not_managed_credit_spend(self):
        meter = self.meter()
        for route in ['byok', 'cli']:
            self.assertEqual(meter.quote_task([10_000], route=route)['reservedMilliCredits'], 0)
        with self.assertRaises(ValueError): meter.quote_task([1], route='unknown')
