"""Local contract tests with synthetic transport; no real image/provider calls."""
import base64
import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_requests import CreditRequests
from postriff_phase2.image_runtime import GatewayImageRuntime, ImageGenerationError

NOW = 1_800_000_000
MODEL = 'openai/gpt-image-2'
PNG = b'\x89PNG\r\n\x1a\nsynthetic'


def policy(**changes):
    value = {'model': MODEL, 'provider': 'vercel-ai-gateway', 'count': 1,
             'size': '1024x1024', 'ceilingUsdMicro': 100_000,
             'expiresAt': NOW + 3600, 'qualification': 'operator-approved-ceiling',
             'evidenceRef': 'synthetic-fixture-v1', 'executionProviders': ['openai']}
    return {**value, **changes}


def response(*, status=200, gateway=0.04, usage=None, valid_image=True):
    body = {'providerMetadata': {'gateway': {'cost': gateway,
            'routing': {'finalProvider': 'openai'}}}}
    if usage is not None:
        body['usage'] = usage
    if valid_image:
        body['data'] = [{'b64_json': base64.b64encode(PNG).decode()}]
    return {'status': status, 'body': body}


class ImageCreditContracts(unittest.TestCase):
    def runtime(self, reply=None, approved=None):
        calls = []
        kwargs = {'transport': lambda *args, **kw: calls.append(kw) or reply}
        if approved is not None:
            # Missing policy support is an assertion RED, not an unrelated fixture error.
            import inspect
            self.assertIn('credit_policy', inspect.signature(GatewayImageRuntime).parameters)
            kwargs.update(credit_policy=approved, clock=lambda: NOW)
        runtime = GatewayImageRuntime('synthetic-key', MODEL, **kwargs)
        return runtime, calls

    def basis(self, runtime):
        get = getattr(runtime, 'credit_basis', None)
        self.assertTrue(callable(get), 'A guessed legacy image estimate cannot qualify credit pricing')
        return get()

    def test_legacy_guess_does_not_qualify_credit_estimate(self):
        runtime, calls = self.runtime()
        self.assertIsNone(self.basis(runtime))
        self.assertEqual(calls, [])

    def test_exact_bounded_server_policy_qualifies_without_provider_call(self):
        runtime, calls = self.runtime(approved=policy())
        basis = self.basis(runtime)
        self.assertEqual(basis['ceilingUsdMicro'], 100_000)
        self.assertEqual(basis['basis'], 'approved_image_ceiling')
        self.assertNotIn('evidenceRef', basis)
        self.assertEqual(calls, [])

    def test_wrong_expired_unbounded_or_incomplete_policy_is_unqualified(self):
        for changes in ({'model': 'other/image'}, {'provider': 'other'}, {'count': 2},
                        {'size': '2048x2048'}, {'ceilingUsdMicro': True},
                        {'ceilingUsdMicro': 0}, {'ceilingUsdMicro': 1_000_001},
                        {'expiresAt': NOW}, {'expiresAt': NOW + 32 * 86400},
                        {'qualification': 'candidate'}, {'evidenceRef': ''},
                        {'executionProviders': ['other']}):
            with self.subTest(changes=changes):
                runtime, calls = self.runtime(approved=policy(**changes))
                self.assertIsNone(self.basis(runtime))
                self.assertEqual(calls, [])

    def test_paid_image_does_not_select_or_price_the_cli_writer(self):
        runtime, _ = self.runtime(approved=policy())
        def writer(_model):
            self.fail('The independently paid image route must not select a writer for pricing')
        ideas = SimpleNamespace(image_runtime=runtime, _select_runtime=writer,
                                _wants_image=lambda p: p.get('imageGeneration') is True)
        request = {'text': 'A piano', 'imageGeneration': True, 'research': False,
                   'model': 'local-cli:writer'}
        try:
            selected, model = CreditRequests(ideas)._validate(request)
        except AlphaError as error:
            self.fail('Qualified images must use their own credit route: ' + str(error))
        self.assertIs(selected, runtime)
        self.assertEqual(model, MODEL)

    def test_gateway_cost_has_one_authoritative_charge(self):
        runtime, calls = self.runtime(response(usage={'cost': 0.03}))
        result = runtime.generate('A piano')
        self.assertEqual(result['usage']['costUsd'], 0.04)
        self.assertEqual(len(calls), 1)

    def test_explicit_invalid_gateway_cost_stays_unknown_despite_usage_overlap(self):
        for bad in (None, -1, True, float('nan'), float('inf'), 1e308, 1e13, 'bad'):
            with self.subTest(cost=bad):
                runtime, _ = self.runtime(response(gateway=bad, usage={'cost': 0.03}))
                result = runtime.generate('A piano')
                self.assertIsNone(result['usage']['costUsd'])
                self.assertEqual(result['usage']['provenance'], 'provider_cost_pending')

    def test_absent_gateway_cost_allows_valid_usage_fallback_including_zero(self):
        for value in (0, 0.03):
            with self.subTest(cost=value):
                reply = response(usage={'cost': value})
                del reply['body']['providerMetadata']['gateway']['cost']
                runtime, _ = self.runtime(reply)
                self.assertEqual(runtime.generate('A piano')['usage']['costUsd'], value)

    def test_known_failed_envelope_keeps_provider_charge(self):
        for reply in (response(status=500), response(valid_image=False)):
            with self.subTest(response=reply):
                runtime, _ = self.runtime(reply)
                with self.assertRaises(ImageGenerationError) as caught:
                    runtime.generate('A piano')
                self.assertEqual(caught.exception.cost_usd, 0.04)
                self.assertFalse(caught.exception.uncertain)

    def test_qualified_route_needs_actual_execution_identity(self):
        reply = response()
        del reply['body']['providerMetadata']['gateway']['routing']
        runtime, _ = self.runtime(reply, approved=policy())
        with self.assertRaises(ImageGenerationError) as caught:
            runtime.generate('A piano')
        self.assertEqual(caught.exception.cost_usd, 0.04)
        self.assertIn('verified', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
