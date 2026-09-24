"""FINAL-04: cloud drafting stays on approved execution providers and records who served it.

Per the AI Gateway docs (provider filtering, 2026-09-11): `providerOptions.gateway.only` restricts routing
and fallbacks to the listed provider slugs, and routing metadata reports `gateway.routing.finalProvider`
and `gateway.cost`. Where exactly the raw Chat Completions response carries that metadata is not verified
against a live call; both spellings are read.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_phase2.hosted_app import ideas_runtime_from_environment
from postriff_phase2.model_runtime import ProviderFailure, ServerModelRuntime
from test_postriff_model_runtime import DESTS, GOOD, Recording, context


def reply(provider=None, cost=None, finish='stop', usage=None, spelling='providerMetadata'):
    body = {'choices': [{'message': {'content': json.dumps({'variants': GOOD})}, 'finish_reason': finish}], 'usage': usage or {'prompt_tokens': 1000, 'completion_tokens': 400}}
    if provider or cost is not None:
        body[spelling] = {'gateway': {'routing': {'finalProvider': provider}, **({'cost': cost} if cost is not None else {})}}
    return {'status': 200, 'body': body}


def runtime(responses, **kwargs):
    transport = Recording(responses)
    rt = ServerModelRuntime('key', model='anthropic/claude-sonnet-5', models=['anthropic/claude-sonnet-5'], prices={'anthropic/claude-sonnet-5': (2, 10)}, transport=transport, **kwargs)
    rt.sleep = lambda seconds: None
    return rt, transport


def run(rt):
    return rt.start_turn({'context': context(), 'idea': 'Announce the seed swap', 'destinations': DESTS, 'reasoning': 'quick'}, lambda e: None)


class GatewayRouting(unittest.TestCase):
    def test_requests_are_restricted_to_the_model_maker_by_default(self):
        rt, transport = runtime([reply()])
        run(rt)
        body = transport.calls[0]['body']
        self.assertEqual(body['providerOptions'], {'gateway': {'only': ['anthropic']}})
        self.assertNotIn('models', body)
        self.assertNotIn('provider', body)

    def test_configured_providers_replace_the_default(self):
        rt, transport = runtime([reply()], allowed_providers={'anthropic/claude-sonnet-5': ['anthropic', 'vertex']})
        run(rt)
        self.assertEqual(transport.calls[0]['body']['providerOptions']['gateway']['only'], ['anthropic', 'vertex'])
        env = ideas_runtime_from_environment({'AI_GATEWAY_API_KEY': 'k', 'POSTRIFF_MODEL_ID': 'anthropic/claude-sonnet-5', 'POSTRIFF_MODEL_PROVIDERS': json.dumps({'anthropic/claude-sonnet-5': ['anthropic', 'bedrock']})})
        self.assertEqual(env.allowed_for('anthropic/claude-sonnet-5'), ['anthropic', 'bedrock'])

    def test_serving_provider_and_gateway_cost_are_recorded(self):
        for spelling in ('providerMetadata', 'provider_metadata'):
            rt, _ = runtime([reply('anthropic', '0.0045', spelling=spelling)])
            usage = run(rt)['usage']
            self.assertEqual(usage['executionProvider'], 'anthropic', spelling)
            self.assertAlmostEqual(usage['costUsd'], 0.0045)
            self.assertEqual(usage['provenance'], 'provider_reported')

    def test_a_cost_computed_from_tokens_records_its_price_table(self):
        rt, _ = runtime([reply()])
        usage = run(rt)['usage']
        self.assertEqual(usage['provenance'], 'estimated_from_tokens')
        self.assertEqual(usage['priceBasis'], {'version': 'configured', 'inputUsdPerMTok': 2, 'outputUsdPerMTok': 10})
        transport = Recording([reply()])
        default = ServerModelRuntime('key', model='anthropic/claude-sonnet-5', models=['anthropic/claude-sonnet-5'], transport=transport)
        self.assertEqual(run(default)['usage']['priceBasis']['version'], 'defaults-2026-09-23')
        rt, _ = runtime([reply('anthropic', '0.0045')])
        self.assertNotIn('priceBasis', run(rt)['usage'], 'a gateway-reported cost needs no price table')

    def test_a_provider_outside_the_approved_set_is_not_used(self):
        rt, _ = runtime([reply('bedrock', '0.004')])
        with self.assertRaises(ProviderFailure) as caught:
            run(rt)
        self.assertTrue(caught.exception.dispatched)
        self.assertAlmostEqual(caught.exception.cost_usd, 0.004)
        self.assertIn('outside', str(caught.exception))

    def test_output_cut_at_the_limit_is_retried_then_reported(self):
        cut = reply(finish='length', usage={'prompt_tokens': 1000, 'completion_tokens': 2400})
        rt, transport = runtime([cut, reply()])
        events = []
        result = rt.start_turn({'context': context(), 'idea': 'Announce the seed swap', 'destinations': DESTS, 'reasoning': 'quick'}, events.append)
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(any('output limit' in (e.get('message') or '') for e in events))
        self.assertIsNotNone(result['usage']['costUsd'])
        rt, _ = runtime([cut, cut])
        with self.assertRaises(ProviderFailure) as caught:
            run(rt)
        self.assertIsNotNone(caught.exception.cost_usd)
        self.assertIn('output limit', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
