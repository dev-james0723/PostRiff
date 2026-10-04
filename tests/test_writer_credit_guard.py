"""Synthetic writer physical-attempt accounting and trusted managed credit guard."""
import json
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.model_runtime import ServerModelRuntime, ProviderFailure
from test_postriff_model_runtime import Recording, context, completion, GOOD, DESTS


def answer(cost=0.01, *, malformed=False, provider='anthropic'):
    value = completion(GOOD)
    if malformed:
        value['body']['choices'] = []
    value['body']['providerMetadata'] = {'gateway': {'cost': cost, 'routing': {'finalProvider': provider}}}
    return value


class WriterCreditGuard(unittest.TestCase):
    def runtime(self, replies):
        transport = Recording(replies)
        return ServerModelRuntime('synthetic-key', transport=transport), transport

    def request(self, **changes):
        return {'context': context(), 'idea': 'Announce the seed swap', 'destinations': DESTS, **changes}

    def test_malformed_envelope_preserves_known_cost_before_legacy_retry(self):
        runtime, transport = self.runtime([answer(0.04, malformed=True), answer()])
        result = runtime.start_turn(self.request(), lambda e: None)
        self.assertEqual(result['usage']['costUsd'], 0.05)
        self.assertEqual((len(transport.calls), result['usage']['modelRequests']), (2, 2))

    def test_malformed_revise_preserves_both_known_charges(self):
        runtime, transport = self.runtime([answer(), answer(0.02, malformed=True)])
        result = runtime.start_turn(self.request(reasoning='deep'), lambda e: None)
        self.assertEqual(result['usage']['costUsd'], 0.03)
        self.assertTrue(result['usage']['reasoning']['reviseFailed'])
        self.assertEqual(len(transport.calls), 2)

    def test_malformed_unapproved_serving_provider_cannot_retry(self):
        runtime, transport = self.runtime([answer(0.04, malformed=True, provider='runware'), answer()])
        with self.assertRaises(ProviderFailure) as caught:
            runtime.start_turn(self.request(), lambda e: None)
        self.assertEqual(caught.exception.cost_usd, 0.04)
        self.assertEqual(len(transport.calls), 1)

    def test_managed_unknown_stops_before_another_physical_attempt(self):
        runtime, transport = self.runtime([answer(None, malformed=True), answer()])
        guards = []
        def guard(**values):
            guards.append(values)
            if values['unknown']:
                raise AlphaError('Reconcile this hold before another call.', 409)
        with self.assertRaises(ProviderFailure) as caught:
            runtime.start_turn(self.request(_creditGuard=guard), lambda e: None)
        self.assertIsNone(caught.exception.cost_usd)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual([v['unknown'] for v in guards], [False, True])

    def test_known_cost_is_preserved_when_next_attempt_exceeds_remaining_cap(self):
        runtime, transport = self.runtime([answer(0.04, malformed=True), answer()])
        guards = []
        def guard(**values):
            guards.append(values)
            if values['spent_usd_micro'] >= 40_000:
                raise AlphaError('The next call exceeds the approved total.', 402)
        with self.assertRaises(ProviderFailure) as caught:
            runtime.start_turn(self.request(_creditGuard=guard), lambda e: None)
        self.assertEqual(caught.exception.cost_usd, 0.04)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual([v['spent_usd_micro'] for v in guards], [0, 40_000])

    def test_known_server_error_keeps_reported_cost_without_retry(self):
        failed = answer(0.02)
        failed['status'] = 500
        runtime, transport = self.runtime([failed])
        with self.assertRaises(ProviderFailure) as caught:
            runtime.start_turn(self.request(), lambda e: None)
        self.assertEqual(caught.exception.cost_usd, 0.02)
        self.assertEqual(len(transport.calls), 1)

    def test_positive_submicro_cost_is_not_falsely_zero(self):
        runtime, transport = self.runtime([answer(0.0000001)])
        result = runtime.start_turn(self.request(), lambda e: None)
        self.assertEqual(result['usage']['costUsd'], 0.000001)
        self.assertEqual(len(transport.calls), 1)

    def test_guard_is_called_before_dispatch_and_never_egressed(self):
        runtime, transport = self.runtime([answer()])
        guards = []
        def guard(**values):
            self.assertEqual(len(transport.calls), 0)
            self.assertGreater(values['next_usd_micro'], 0)
            guards.append(values)
        result = runtime.start_turn(self.request(_creditGuard=guard), lambda e: None)
        self.assertEqual(len(guards), 1)
        self.assertNotIn('_creditGuard', json.dumps(transport.calls[0]['body']))
        self.assertEqual(result['usage']['costUsd'], 0.01)


if __name__ == '__main__':
    unittest.main()
