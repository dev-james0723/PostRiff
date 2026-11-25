"""The automatic per-request credit limit is a bounded deployment setting; anything else leaves explicit approval on."""
import unittest

from postriff_phase2.credit_wallet import AUTO_LIMIT_ENV, automatic_limit


class AutomaticLimitSetting(unittest.TestCase):
    def test_whole_credits_within_bounds_turn_it_on(self):
        for raw, expected in (('1', 1_000), ('100', 100_000), (' 250 ', 250_000), ('1000', 1_000_000)):
            with self.subTest(raw=raw):
                self.assertEqual(automatic_limit({AUTO_LIMIT_ENV: raw}), expected)

    def test_anything_else_leaves_explicit_approval_in_place(self):
        for raw in ('', '0', '-5', '1001', '10.5', '1e3', '0100', 'abc', '\u0661\u0660\u0660', '100 credits'):
            with self.subTest(raw=raw):
                self.assertIsNone(automatic_limit({AUTO_LIMIT_ENV: raw}))
        self.assertIsNone(automatic_limit({}))


class AutomaticApprovalBoundary(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from postriff_phase2.credit_requests import CreditRequests

        class Untouchable:
            def transaction(self, *args, **kwargs):
                raise AssertionError('refused before any database access')

        self.requests = CreditRequests(SimpleNamespace(ledger=SimpleNamespace(credits=object()), repository=Untouchable()))

    def test_api_tokens_cannot_ask_for_automatic_approval(self):
        from postriff_alpha.domain import AlphaError
        with self.assertRaises(AlphaError) as raised:
            self.requests.authorize('w', 'prt_synthetic', 1, {'creditApproval': 'automatic', 'research': False}, 'turn', 'c')
        self.assertEqual(raised.exception.status, 403)

    def test_a_quote_and_automatic_approval_cannot_both_be_sent(self):
        from postriff_alpha.domain import AlphaError
        with self.assertRaises(AlphaError) as raised:
            self.requests.authorize('w', 'session', 1, {'creditApproval': 'automatic', 'creditQuoteId': 'q', 'research': False}, 'turn', 'c')
        self.assertEqual(raised.exception.status, 400)


if __name__ == '__main__':
    unittest.main()
