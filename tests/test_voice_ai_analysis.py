"""Evidence-bound AI analysis using an injected transport; never a paid model call."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import voice_sources
from postriff_phase2.model_runtime import ServerModelRuntime
from test_postriff_voice_analysis import add_sample


class VoiceAIRegressionTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state('w')
        self.sid = add_sample(self.state, 'Hello friends. A quiet opening.', 'one')
        self.model = 'openai/gpt-4.1-mini'
        self.route = 'cloud:vercel-ai-gateway:' + self.model
        voice_sources.apply_action(self.state, 'voice_sample_grant', {'sourceId': self.sid, 'grants': [{'purpose': 'analysis', 'route': self.route}], 'confirmed': True}, 'owner', 103)
        self.projection = voice_sources.project(self.state, [self.sid], 'analysis', self.route)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('postriff_phase2.voice_ai'), 'Provide a real, consented AI analysis route')
        from postriff_phase2 import voice_ai
        return voice_ai

    def output(self):
        return {'dimensions': [{'id': 'openings', 'observation': 'Opens with a friendly greeting.', 'support': [self.sid], 'counterEvidence': [], 'quotes': [{'sourceId': self.sid, 'text': 'Hello friends.'}]}]}

    def runtime(self, output=None, status=200):
        self.calls = []
        def transport(method, url, headers=None, body=None, timeout=None):
            self.calls.append(body)
            return {'status': status, 'body': {'choices': [{'message': {'content': json.dumps(output if output is not None else self.output())}}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}}
        return ServerModelRuntime('SYNTHETIC_KEY', model=self.model, transport=transport)

    def test_ai_uses_exact_route_and_returns_a_nonactive_evidence_bound_proposal(self):
        module = self.module()
        runtime = self.runtime()
        self.assertTrue(callable(getattr(runtime, 'analyze_voice', None)))
        result = runtime.analyze_voice(self.projection, self.model, 'Compare openings; do not invent personality traits.')
        proposal = module.proposal_from_output(result['output'], self.projection, 'owner', 200, self.model, runtime.provider)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(proposal['analysisMethod'], 'ai')
        self.assertEqual(proposal['status'], 'proposed')
        self.assertIsNone(proposal['tone'])
        self.assertEqual(proposal['writingExample'], '')
        self.assertEqual(proposal['evidenceSourceIds'], [self.sid])
        self.assertGreater(result['usage']['costUsd'], 0)
        self.assertNotIn('SYNTHETIC_KEY', json.dumps(proposal))

    def test_runtime_rejects_wrong_route_before_network(self):
        self.module()
        runtime = self.runtime()
        for projection in ({**self.projection, 'route': 'local-rules'}, {**self.projection, 'purpose': 'generation'}, {**self.projection, 'excluded': [{'id': 'foreign'}]}):
            with self.assertRaises(AlphaError):
                runtime.analyze_voice(projection, self.model, '')
        self.assertEqual(self.calls, [])

    def test_foreign_citations_and_invented_quotes_fail_closed(self):
        module = self.module()
        for quote in ({'sourceId': 'foreign', 'text': 'Hello friends.'}, {'sourceId': self.sid, 'text': 'Never written by this author.'}):
            output = self.output()
            output['dimensions'][0]['quotes'] = [quote]
            with self.subTest(quote=quote), self.assertRaises(AlphaError):
                module.proposal_from_output(output, self.projection, 'owner', 200, self.model, 'provider')

    def test_unknown_dimension_does_not_become_an_approved_style_trait(self):
        module = self.module()
        output = self.output()
        output['dimensions'][0]['id'] = 'health_diagnosis'
        with self.assertRaises(AlphaError):
            module.proposal_from_output(output, self.projection, 'owner', 200, self.model, 'provider')

    def test_oversized_context_is_refused_without_truncating_selected_samples(self):
        self.module()
        runtime = self.runtime()
        large = {**self.projection, 'samples': [{**self.projection['samples'][0], 'text': 'x' * 70000}]}
        with self.assertRaises(AlphaError):
            runtime.analyze_voice(large, self.model, '')
        self.assertEqual(self.calls, [])

    def test_rate_limit_does_not_automatically_repeat_a_paid_call(self):
        self.module()
        runtime = self.runtime(status=429)
        with self.assertRaises(AlphaError):
            runtime.analyze_voice(self.projection, self.model, '')
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
