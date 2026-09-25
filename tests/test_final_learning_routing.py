"""FINAL-04: the background preference-learning extraction is a cloud call like drafting, so it carries the
same approved-provider restriction, records the gateway-reported cost exactly, and does not use an answer
served outside the approved providers. One `POSTRIFF_MODEL_PROVIDERS` map serves drafting, images and
learning. Synthetic transports only.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase2.learning_model import CLOUD_MODEL, GatewayCall
from postriff_phase2.model_runtime import provider_map


class Recording:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append(kwargs['body'])
        return self.response


def answer(provider=None, cost=None, usage=None):
    body = {'choices': [{'message': {'content': json.dumps({'observations': []})}}], 'usage': usage or {'prompt_tokens': 100, 'completion_tokens': 20}}
    if provider or cost is not None:
        body['providerMetadata'] = {'gateway': {'routing': {'finalProvider': provider}, **({'cost': cost} if cost is not None else {})}}
    return {'status': 200, 'body': body}


class LearningRouting(unittest.TestCase):
    def test_extraction_is_restricted_to_the_model_maker_by_default(self):
        transport = Recording(answer())
        GatewayCall('key', transport=transport)('system', 'user', {'type': 'object'})
        self.assertEqual(transport.calls[0]['providerOptions'], {'gateway': {'only': [CLOUD_MODEL.split('/')[0]]}})

    def test_configured_providers_apply(self):
        transport = Recording(answer())
        GatewayCall('key', transport=transport, allowed_providers=['anthropic', 'bedrock'])('system', 'user', {})
        self.assertEqual(transport.calls[0]['providerOptions']['gateway']['only'], ['anthropic', 'bedrock'])
        mapping = provider_map({'POSTRIFF_MODEL_PROVIDERS': json.dumps({CLOUD_MODEL: ['anthropic', 'vertex']})})
        self.assertEqual(mapping[CLOUD_MODEL], ['anthropic', 'vertex'])
        self.assertEqual(provider_map({}), {})
        with self.assertRaises(ValueError):
            provider_map({'POSTRIFF_MODEL_PROVIDERS': '[1, 2]'})

    def test_gateway_cost_is_recorded_exactly(self):
        response = GatewayCall('key', transport=Recording(answer('anthropic', '0.0045')))('system', 'user', {})
        self.assertEqual(response.cost_usd_micro, 4500)

    def test_an_answer_from_outside_the_approved_set_is_not_used(self):
        with self.assertRaises(AlphaError) as caught:
            GatewayCall('key', transport=Recording(answer('bedrock', '0.004')))('system', 'user', {})
        self.assertIn('outside', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
