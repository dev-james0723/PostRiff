"""Synthetic regression for the existing active v2 staging plan; no grants or charges."""
import unittest
from unittest.mock import MagicMock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_meter import POLICY_VERSION, V2_POLICY_VERSION, millicredits
from postriff_phase2.credit_wallet import CreditBook


class LiveCallCreditPolicyTests(unittest.TestCase):
    def cursor(self, policy, status='active'):
        cur = MagicMock()
        cur.fetchone.side_effect = [('workspace',), (policy, status)]
        return cur

    def test_existing_active_v2_and_historical_v1_are_supported(self):
        for policy in (POLICY_VERSION, V2_POLICY_VERSION):
            cur = self.cursor(policy)
            self.assertEqual(CreditBook().policy(cur, 'workspace'), policy)

    def test_unknown_and_inactive_terms_still_fail_closed(self):
        for policy, status in ((V2_POLICY_VERSION, 'candidate'), (V2_POLICY_VERSION, 'retired'),
                               ('unknown-v3', 'active')):
            with self.subTest(policy=policy, status=status), self.assertRaises(AlphaError):
                CreditBook().policy(self.cursor(policy, status), 'workspace')

    def test_v2_quote_retains_actual_policy_and_unchanged_credit_arithmetic(self):
        book = CreditBook(clock=lambda: 100)
        cur = self.cursor(V2_POLICY_VERSION)
        cur.fetchone.side_effect = [('workspace',), (V2_POLICY_VERSION, 'active'), ('quote',)]
        with patch.object(book, 'view', return_value={'availableMilliCredits': 100000}):
            quote = book.issue(cur, 'workspace', 'user', 7, 'digest', 'gpt-live-1', 'openai', millicredits(100000))
        self.assertEqual(quote['policy'], V2_POLICY_VERSION)
        self.assertEqual(quote['maxMilliCredits'], 30000)
        self.assertEqual(cur.execute.call_args.args[1][2], V2_POLICY_VERSION)

    def test_v2_reservation_preserves_balance_and_policy_binding(self):
        book = CreditBook()
        quote = {'policy': V2_POLICY_VERSION, 'digest': 'digest', 'model': 'gpt-live-1',
                 'provider': 'openai', 'maximum': 30000}
        wallet = {'debtMilliCredits': 0, 'availableMilliCredits': 40000,
                  'lots': [{'grantId': 'existing-grant', 'available': 40000}]}
        with patch.object(book, 'policy', return_value=V2_POLICY_VERSION), \
             patch.object(book, 'quote', return_value=quote), patch.object(book, 'view', return_value=wallet):
            reservation = book.prepare(MagicMock(), 'workspace', 'user', 100000, 'gpt-live-1', 'openai',
                                       {'quoteId': 'quote', 'requestDigest': 'digest'})
            self.assertEqual(reservation['policy'], V2_POLICY_VERSION)
            self.assertEqual(reservation['allocations'], [{'grantId': 'existing-grant', 'milli': 30000}])
            wallet['availableMilliCredits'] = 0
            with self.assertRaises(AlphaError):
                book.prepare(MagicMock(), 'workspace', 'user', 100000, 'gpt-live-1', 'openai',
                             {'quoteId': 'quote', 'requestDigest': 'digest'})
            quote['policy'] = POLICY_VERSION
            with self.assertRaises(AlphaError):
                book.prepare(MagicMock(), 'workspace', 'user', 100000, 'gpt-live-1', 'openai',
                             {'quoteId': 'quote', 'requestDigest': 'digest'})


if __name__ == '__main__': unittest.main()
