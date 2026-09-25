"""FINAL-04: image generation stays on approved execution providers and records who served it and the cost.

The AI Gateway docs (image generation, 2026-09-08) show the OpenAI-compatible `/v1/images/generations` body
accepting `providerOptions`, and provider filtering (2026-09-10) documents `providerOptions.gateway.only`.
Whether the images endpoint honours `gateway.only` and where it reports routing metadata is not verified
against a live call; both metadata spellings are read.
"""
import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2.image_runtime import GatewayImageRuntime, ImageGenerationError, from_environment

PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic-image'


class Recording:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({'method': method, 'url': url, **kwargs})
        return self.response


def reply(provider=None, cost=None, usage=None, spelling='providerMetadata'):
    body = {'data': [{'b64_json': base64.b64encode(PNG).decode()}]}
    if usage is not None:
        body['usage'] = usage
    if provider or cost is not None:
        body[spelling] = {'gateway': {'routing': {'finalProvider': provider}, **({'cost': cost} if cost is not None else {})}}
    return {'status': 200, 'body': body}


class ImageRouting(unittest.TestCase):
    def test_requests_are_restricted_to_the_model_maker_by_default(self):
        transport = Recording(reply())
        GatewayImageRuntime('secret', 'openai/gpt-image-2', transport=transport).generate('A red piano')
        self.assertEqual(transport.calls[0]['body']['providerOptions'], {'gateway': {'only': ['openai']}})

    def test_configured_providers_replace_the_default(self):
        runtime = from_environment({'AI_GATEWAY_API_KEY': 'k', 'POSTRIFF_IMAGE_MODEL': 'openai/gpt-image-2', 'POSTRIFF_MODEL_PROVIDERS': json.dumps({'openai/gpt-image-2': ['openai', 'azure'], 'anthropic/claude-sonnet-5': ['anthropic']})})
        self.assertEqual(runtime.allowed_providers, ['openai', 'azure'])
        other = from_environment({'AI_GATEWAY_API_KEY': 'k', 'POSTRIFF_IMAGE_MODEL': 'bfl/flux-2-pro', 'POSTRIFF_MODEL_PROVIDERS': json.dumps({'openai/gpt-image-2': ['openai']})})
        self.assertEqual(other.allowed_providers, ['bfl'], 'a model missing from the map keeps its maker')

    def test_gateway_cost_and_serving_provider_are_recorded(self):
        for spelling in ('providerMetadata', 'provider_metadata'):
            result = GatewayImageRuntime('secret', 'openai/gpt-image-2', transport=Recording(reply('openai', '0.04', spelling=spelling))).generate('A red piano')
            self.assertAlmostEqual(result['usage']['costUsd'], 0.04, msg=spelling)
            self.assertEqual(result['usage']['provenance'], 'provider_reported')
            self.assertEqual(result['usage']['executionProvider'], 'openai')
        # The long-standing `usage.cost` field still wins when present.
        result = GatewayImageRuntime('secret', 'openai/gpt-image-2', transport=Recording(reply('openai', '0.04', usage={'cost': 0.03}))).generate('A red piano')
        self.assertAlmostEqual(result['usage']['costUsd'], 0.03)

    def test_an_image_served_outside_the_approved_set_is_not_kept(self):
        runtime = GatewayImageRuntime('secret', 'openai/gpt-image-2', transport=Recording(reply('runware', '0.05')))
        with self.assertRaises(ImageGenerationError) as caught:
            runtime.generate('A red piano')
        self.assertIn('outside', str(caught.exception))
        self.assertAlmostEqual(caught.exception.cost_usd, 0.05)
        self.assertFalse(caught.exception.uncertain, 'a known cost is booked, not left for reconciliation')
        runtime = GatewayImageRuntime('secret', 'openai/gpt-image-2', transport=Recording(reply('runware')))
        with self.assertRaises(ImageGenerationError) as caught:
            runtime.generate('A red piano')
        self.assertTrue(caught.exception.uncertain, 'served elsewhere at an unknown cost stays for reconciliation')


if __name__ == '__main__':
    unittest.main()
