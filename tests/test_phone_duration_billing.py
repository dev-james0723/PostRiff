"""Offline credit-authority scope checks; no database or provider transport."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_phase2.phone import billing


class PhoneDurationQuoteTest(unittest.TestCase):
    def test_duration_is_part_of_both_component_credit_authorities(self):
        book = Mock()
        book.policy.return_value = True
        book.view.return_value = {'availableMilliCredits': 1_000_000}
        book.issue.return_value = {'quoteId': 'synthetic-quote'}
        phone = SimpleNamespace(
            config=SimpleNamespace(cap_seconds=3600),
            provider=SimpleNamespace(name='fake'),
            agent=lambda: SimpleNamespace(cfg=SimpleNamespace(route=lambda *_args, **_kwargs: SimpleNamespace(model='synthetic-live'))),
            hosted=SimpleNamespace(ledger=SimpleNamespace(credits=book)),
        )

        def bindings(**options):
            book.reset_mock()
            billing.authorities(phone, Mock(), 'workspace', 'principal', 1,
                maximum=100_000, conversation_id='conversation', number_hash='synthetic-number-hash',
                kind='explicit', reason='explicit', costs=(20_000, 10_000), **options)
            self.assertEqual(book.issue.call_count, 2)
            self.assertEqual(book.authorize.call_count, 2)
            return [call.args[4] for call in book.issue.call_args_list]

        with patch.object(billing, 'ai_usage_exempt', return_value=False):
            default = bindings()
            full_hour = bindings(cap_seconds=3600)
            bounded = bindings(cap_seconds=60)
            longer = bindings(cap_seconds=90)

        self.assertEqual(default, full_hour)
        self.assertTrue(all(short != full for short, full in zip(bounded, full_hour)))
        self.assertTrue(all(short != long for short, long in zip(bounded, longer)))


if __name__ == '__main__':
    unittest.main()
