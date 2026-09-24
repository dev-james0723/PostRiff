"""FINAL-04/05: a failed cloud draft says whether a provider request went out and what it is known to cost.

- Refused before any request (validation, nothing to draft from): not dispatched, cost 0.
- 429 is a refusal before work: known zero cost, retried after a short backoff.
- 4xx rejection: dispatched, cost = what earlier attempts are known to have cost.
- 5xx, no status or an unreachable provider: dispatched, cost unknown (never shown as 0).
- Output that never parses after all attempts: cost known when every attempt reported usage.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_alpha.domain import AlphaError
from postriff_phase2.model_runtime import ProviderFailure, ServerModelRuntime
from test_postriff_model_runtime import DESTS, GOOD, Recording, completion, context


def runtime(responses):
    transport = Recording(responses)
    rt = ServerModelRuntime('key', model='test/cloud', models=['test/cloud'], prices={'test/cloud': (1, 1)}, transport=transport)
    rt.sleep = lambda seconds: None
    return rt, transport


def run(rt, **extra):
    return rt.start_turn({'context': context(), 'idea': 'Announce the seed swap', 'destinations': DESTS, 'reasoning': 'quick', **extra}, lambda e: None)


class ProviderFailureClassification(unittest.TestCase):
    def failure(self, call):
        with self.assertRaises(ProviderFailure) as caught:
            call()
        return caught.exception

    def test_refused_before_any_request_is_not_dispatched_and_free(self):
        rt, transport = runtime([])
        error = self.failure(lambda: rt.start_turn({'context': context(sources=[]), 'idea': '', 'destinations': DESTS}, lambda e: None))
        self.assertEqual((error.dispatched, error.cost_usd, transport.calls), (False, 0.0, []))
        self.assertIsInstance(error, AlphaError)

    def test_rate_limit_is_a_known_zero_cost_refusal(self):
        rt, transport = runtime([{'status': 429, 'body': {}}, completion(GOOD, {'prompt_tokens': 1000, 'completion_tokens': 400})])
        result = run(rt)
        self.assertEqual(len(transport.calls), 2)
        self.assertIsNotNone(result['usage']['costUsd'], 'a 429 before a successful attempt must not make the cost unknown')
        rt, _ = runtime([{'status': 429, 'body': {}}, {'status': 429, 'body': {}}])
        error = self.failure(lambda: run(rt))
        self.assertEqual((error.dispatched, error.cost_usd), (True, 0.0))

    def test_rejection_keeps_the_known_cost_of_earlier_attempts(self):
        bad = {'status': 200, 'body': {'choices': [{'message': {'content': 'not json'}}], 'usage': {'prompt_tokens': 1_000_000, 'completion_tokens': 0}}}
        rt, _ = runtime([bad, {'status': 400, 'body': {'error': 'invalid'}}])
        error = self.failure(lambda: run(rt))
        self.assertTrue(error.dispatched)
        self.assertAlmostEqual(error.cost_usd, 1.0)

    def test_server_errors_and_unreachable_providers_are_unknown(self):
        for response in ({'status': 503, 'body': {}}, {'status': None, 'body': {}}, AlphaError('The model provider is temporarily unreachable.', 503)):
            rt, _ = runtime([response])
            error = self.failure(lambda: run(rt))
            self.assertEqual((error.dispatched, error.cost_usd), (True, None), response)

    def test_unparseable_output_with_reported_usage_has_a_known_cost(self):
        bad = {'status': 200, 'body': {'choices': [{'message': {'content': 'not json'}}], 'usage': {'prompt_tokens': 500_000, 'completion_tokens': 0}}}
        rt, _ = runtime([bad, bad])
        error = self.failure(lambda: run(rt))
        self.assertTrue(error.dispatched)
        self.assertAlmostEqual(error.cost_usd, 1.0)


class DispatchTracking(unittest.TestCase):
    def test_an_error_after_dispatch_is_never_reported_as_free(self):
        rt, _ = runtime([completion(GOOD, {'prompt_tokens': 1000, 'completion_tokens': 400})])
        seen = []

        def emit(event):
            seen.append(event['type'])
            if event['type'] == 'message.delta':
                raise AlphaError('Unsupported client event.', 500)

        with self.assertRaises(ProviderFailure) as caught:
            rt.start_turn({'context': context(), 'idea': 'Announce the seed swap', 'destinations': DESTS, 'reasoning': 'quick'}, emit)
        self.assertEqual((caught.exception.dispatched, caught.exception.cost_usd), (True, None))


class CancelStopsFurtherRequests(unittest.TestCase):
    def test_no_retry_is_sent_after_the_run_was_cancelled(self):
        bad = {'status': 200, 'body': {'choices': [{'message': {'content': 'not json'}}], 'usage': {'prompt_tokens': 1_000_000, 'completion_tokens': 0}}}
        rt, transport = runtime([bad, completion(GOOD)])
        cancelled = {'now': False}

        def emit(event):
            if event['type'] == 'warning.created':
                cancelled['now'] = True  # the person cancels while the first answer is being checked
            return not cancelled['now']

        with self.assertRaises(ProviderFailure) as caught:
            rt.start_turn({'context': context(), 'idea': 'Announce the seed swap', 'destinations': DESTS, 'reasoning': 'quick'}, emit)
        self.assertEqual(len(transport.calls), 1, 'no second paid request after cancel')
        self.assertTrue(caught.exception.dispatched)
        self.assertAlmostEqual(caught.exception.cost_usd, 1.0)


if __name__ == '__main__':
    unittest.main()
