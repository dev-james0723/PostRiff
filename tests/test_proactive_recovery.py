"""Pure recovery classification; synthetic exceptions, no provider access."""
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2 import recovery


class RecoveryTests(unittest.TestCase):
    def test_dispatch_uncertainty_always_stops_automatic_retry(self):
        for status in (403, 429, 503):
            kind = recovery.category(AlphaError('synthetic', status), external_started=True)
            self.assertEqual(kind, 'outcome_unknown')
            self.assertFalse(recovery.record(kind, 1)['automaticRetry'])

    def test_before_dispatch_classification(self):
        for status, expected in ((401,'permission'),(403,'permission'),(402,'budget'),(400,'permanent'),(415,'permanent'),(408,'retryable'),(429,'retryable'),(503,'retryable')):
            self.assertEqual(recovery.category(AlphaError('synthetic',status)),expected)
        self.assertEqual(recovery.category(TimeoutError()),'retryable')
        self.assertEqual(recovery.category(ValueError()),'permanent')

    def test_bounded_exponential_delays_and_retry_after(self):
        first, second, third = [recovery.record('retryable',n,now=100) for n in (1,2,3)]
        self.assertTrue(130 <= first['retryAt'] <= 138)
        self.assertTrue(160 <= second['retryAt'] <= 175)
        self.assertIsNone(third['retryAt'])
        self.assertFalse(third['automaticRetry'])
        self.assertEqual(recovery.record('retryable',1,now=100,retry_after=99999)['retryAt'],3700)


if __name__ == '__main__': unittest.main()
