"""Credit admission wiring; real claims and settlement live in the PostgreSQL test."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError
from postriff_phase2.voice_ai import HostedVoiceAnalysis
from test_social_voice_services import Repository
from test_postriff_voice_analysis import add_sample
from postriff_phase2 import voice_sources


class BrainCreditQuoteTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository()
        sid = add_sample(self.repo.state, 'Hello friends. An update.', 'one')
        self.payload = {'requestId': 'brain-credit-quote-01', 'sourceIds': [sid],
                        'model': 'test-model', 'route': 'cloud:test-provider:test-model'}
        voice_sources.apply_action(self.repo.state, 'voice_sample_grant', {
            'sourceId': sid, 'grants': [{'purpose': 'analysis', 'route': self.payload['route']}], 'confirmed': True}, 'owner', 100)
        self.credits = SimpleNamespace(policy=Mock(return_value='test-policy'), issue=Mock(return_value={
            'quoteId': 'credit-quote-id', 'maxMilliCredits': 300, 'policy': 'test-policy'}), authorize=Mock())
        self.runtime = SimpleNamespace(provider='test-provider', quote_voice_analysis=Mock(return_value=1000), analyze_voice=Mock())
        self.ledger = SimpleNamespace(credits=self.credits, ensure_entitlement=Mock(), reserve=Mock())
        self.service = SimpleNamespace(repository=self.repo, clock=lambda: 200, ledger=self.ledger,
            ideas=SimpleNamespace(_select_runtime=lambda model: self.runtime), _present=lambda result: result)
        self.handler = HostedVoiceAnalysis(self.service)

    def test_quote_binds_existing_credit_limit_to_saved_revision_and_exact_request(self):
        result = self.handler.quote('workspace', 'session', 1, self.payload)
        quote = result['state']['speaker']['analysisQuote']
        self.credits.issue.assert_called_once_with(self.repo.cur, 'workspace', 'owner', 2,
            self.handler.credit_digest(quote), 'test-model', 'test-provider', 300)
        self.assertEqual(quote['creditLimit']['maxMilliCredits'], 300)
        self.runtime.analyze_voice.assert_not_called()
        self.ledger.reserve.assert_not_called()

    def test_legacy_allowance_quotes_do_not_issue_credit_limits(self):
        self.credits.policy.return_value = None
        result = self.handler.quote('workspace', 'session', 1, self.payload)
        self.assertNotIn('creditLimit', result['state']['speaker']['analysisQuote'])
        self.credits.issue.assert_not_called()

    def test_credit_authority_rejection_stops_reservation_and_transport(self):
        quote = self.handler.quote('workspace', 'session', 1, self.payload)['state']['speaker']['analysisQuote']
        self.credits.authorize.side_effect = AlphaError('Credit approval is used or expired.', 409)
        with self.assertRaisesRegex(AlphaError, 'used or expired'):
            self.handler.run('workspace', 'session', 2, {**self.payload, 'confirmed': True, 'quoteId': quote['id']}, require_quote=True)
        self.credits.authorize.assert_called_once_with(self.repo.cur, 'workspace', 'owner', 2,
            self.handler.credit_digest(quote), 'credit-quote-id')
        self.ledger.reserve.assert_not_called()
        self.runtime.analyze_voice.assert_not_called()


if __name__ == '__main__':
    unittest.main()
