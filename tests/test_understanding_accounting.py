"""Offline helper accounting regression; no provider calls or legacy cost recovery."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import ai_call_events
from postriff_phase2.ideas import IdeasService
from postriff_phase2.learning_model import GatewayCall
from postriff_phase2.permissions import Membership

WID = '00000000-0000-4000-8000-000000000201'
AID = '00000000-0000-4000-8000-000000000202'
RESERVATION = '00000000-0000-4000-8000-000000000203'


def response(content='{}', cost='0.006589', status=200):
    return {'status': status, 'body': {'id': 'gen_offline_helper', 'choices': [{'message': {'content': content}}],
                                     'usage': {'prompt_tokens': 6184, 'completion_tokens': 81, 'cost': cost}}}


class HelperAccounting(unittest.TestCase):
    def call(self, answer):
        return GatewayCall('offline-key', transport=lambda *args, **kwargs: answer)

    def service(self):
        service = IdeasService.__new__(IdeasService)
        service.clock = lambda: 1800000000
        service._member = lambda _: Membership('owner')
        service.ledger = Mock()
        service.ledger.reserve.return_value = {'reservationId': RESERVATION}

        @contextmanager
        def transaction(*args):
            yield Mock(), (1, {}, 'owner'), AID

        service.repository = SimpleNamespace(transaction=transaction, connection_factory=Mock())
        return service

    def test_reported_decimal_string_cost_is_preserved(self):
        result = self.call(response())('system', 'user', {})
        self.assertEqual(result.cost_usd_micro, 6589)

    def test_unparseable_answer_carries_measured_cost_without_content(self):
        with self.assertRaises(AlphaError) as failed:
            self.call(response('PRIVATE invalid json'))('system', 'user', {})
        self.assertEqual(failed.exception.cost_usd_micro, 6589)
        self.assertEqual(failed.exception.cost_source, 'gateway')
        self.assertNotIn('PRIVATE', str(failed.exception))

    def test_unknown_or_invalid_reported_cost_is_not_promoted_to_measured(self):
        for cost in (float('nan'), float('inf'), -1, '-0.01', 'NaN', True, None):
            with self.subTest(cost=cost), patch('postriff_phase2.model_runtime.DEFAULT_PRICES', {}):
                self.assertIsNone(self.call(response(cost=cost))('system', 'user', {}).cost_usd_micro)

    def test_failed_reading_settles_known_cost_and_emits_bound_attempt(self):
        service = self.service()
        call = self.call(response('not json'))
        with patch('postriff_phase2.request_model.call_for', return_value=call), \
                patch('postriff_phase2.request_model.user_prompt', return_value='offline input'), \
                patch('postriff_phase2.request_model.schema', return_value={}), \
                patch('postriff_phase2.request_model.price_quote_micro', return_value=10000), \
                patch.object(ai_call_events, 'write_attempts') as write:
            answer = service._read_request(WID, 'offline-session', 'Schedule later', 'UTC', object())
        self.assertIsNone(answer)
        self.assertEqual(service.ledger.settle.call_args.args[1:], (WID, RESERVATION, 'completed', 6589))
        base, attempts = write.call_args.args
        self.assertEqual((base['workspace_id'], base['user_id'], base['reservation_id'], base['feature']),
                         (WID, AID, RESERVATION, 'understanding'))
        self.assertEqual(len(attempts), 1)
        self.assertEqual((attempts[0]['provider_request_id'], attempts[0]['cost_usd_micro'], attempts[0]['cost_source']),
                         ('gen_offline_helper', 6589, 'gateway'))
        self.assertNotIn('not json', repr(attempts))
        self.assertFalse(ai_call_events.active())

    def test_provider_refusal_records_known_zero_but_transport_unknown_stays_unknown(self):
        with self.assertRaises(AlphaError) as refused:
            self.call(response(status=429))('system', 'user', {})
        self.assertEqual(refused.exception.cost_usd_micro, 0)
        call = GatewayCall('offline-key', transport=Mock(side_effect=AlphaError('Transport unavailable.', 503)))
        with self.assertRaises(AlphaError) as unknown:
            call('system', 'user', {})
        self.assertIsNone(unknown.exception.cost_usd_micro)


if __name__ == '__main__':
    unittest.main()
