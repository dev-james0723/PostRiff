"""Executable original-language context candidates; no network or model calls."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from postriff_phase2.growth.trends import advanced_pipeline as advanced, contracts, text_context
from test_trend_advanced_pipeline import sealed_fixture, NOW


class TextContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = sealed_fixture()['manifest']

    def setUp(self):
        for name in ('socket.create_connection', 'socket.socket.connect', 'socket.getaddrinfo', 'urllib.request.urlopen'):
            guard = patch(name, side_effect=AssertionError('external I/O forbidden'))
            mock = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mock.assert_not_called)

    def inputs(self):
        m = deepcopy(self.manifest)
        return advanced.build_inputs(m, now=NOW, current_policies=deepcopy(m['policy_versions']),
            current_source_rights={o['observation_id']: deepcopy(o['rights']) for o in m['source_revisions']})

    def test_native_spans_and_actual_relations_remain_uninterpreted(self):
        inputs = self.inputs()
        sid = inputs['common']['sources'][-1]['source_id']
        text = '係咪要慢啲練？🎹 piano... 唔係「放棄」！\nSecond line'
        inputs['facts'][sid]['text'] = text
        inputs['common']['sources'][-1]['language'] = 'yue'
        raw, visible = text_context.reconstruct(inputs)
        seed = next(s for s in raw['seeds'] if s['evidence_refs'] == [sid])
        span = seed['original_spans'][0]
        self.assertEqual(span['text'], text[:span['end']])
        self.assertEqual(seed['language'], 'yue')
        self.assertEqual(seed['stance'], 'unknown')
        self.assertIsNone(seed['claim'])
        self.assertTrue(seed['provisional'])
        self.assertEqual(raw['origin'], 'unknown')
        bundle = next(b for b in raw['bundles'] if b['root_id'] == sid)
        self.assertEqual(len(bundle['member_ids']), 2)
        self.assertEqual(bundle['relations'][0]['relation_type'], 'reply')
        self.assertEqual(bundle['context_completeness'], 'partial')
        self.assertEqual(raw['observed_original_count'], len(inputs['common']['sources']))
        self.assertIn(seed, visible)

    def test_future_evidence_does_not_rewrite_seed_digest(self):
        inputs = self.inputs()
        before = contracts.digest(text_context.reconstruct(inputs))
        future = deepcopy(inputs['common']['sources'][-1])
        future.update(source_id='future-source', available_at='2026-10-01T00:00:00Z', event_at='2026-10-01T00:00:00Z')
        inputs['common']['sources'].append(future)
        inputs['facts']['future-source'] = {**deepcopy(inputs['facts'][inputs['common']['sources'][0]['source_id']]),
                                           'source_identity': 'future', 'text': 'future knowledge'}
        self.assertEqual(before, contracts.digest(text_context.reconstruct(inputs)))

    def test_missing_target_and_long_text_fail_to_partial_not_complete(self):
        inputs = self.inputs()
        sid = inputs['common']['sources'][0]['source_id']
        inputs['facts'][sid]['relations'] = [{'type': 'reply', 'target': 'uncollected'}]
        raw, _ = text_context.reconstruct(inputs)
        bundle = next(b for b in raw['bundles'] if b['root_id'] == sid)
        self.assertIn('uncollected_relation_target', bundle['missing_context'])
        inputs['facts'][sid]['text'] = '長' * 5000
        raw, _ = text_context.reconstruct(inputs)
        self.assertFalse(any(sid in s['evidence_refs'] for s in raw['seeds']))
        self.assertTrue(all(b['context_completeness'] == 'partial' for b in raw['bundles']))

    def test_display_and_raw_rights_are_independent(self):
        inputs = self.inputs()
        for s in inputs['common']['sources']:
            s['rights']['display'] = False
        raw, visible = text_context.reconstruct(inputs)
        self.assertTrue(raw['seeds'])
        self.assertEqual(visible, [])
        self.assertEqual(advanced.build_projection('genome', inputs, now=NOW)['payload']['narrative_variants'], [])
        for s in inputs['common']['sources']:
            s['rights']['creative'] = False
        raw, visible = text_context.reconstruct(inputs)
        self.assertEqual(raw['seeds'], [])
        self.assertEqual(raw['bundles'], [])

    def test_repeat_question_requires_independent_creators_and_never_qualifies_gap(self):
        inputs = self.inputs()
        for s in inputs['common']['sources']:
            inputs['facts'][s['source_id']]['text'] = '慢啲 practice 係咪好啲？'
        out = advanced.build_projection('whitespace_candidate', inputs, now=NOW)
        self.assertEqual(len(out['details']['candidates']), 1)
        candidate = out['details']['candidates'][0]
        self.assertEqual(candidate['known_creator_count'], 2)
        self.assertEqual(candidate['observed_original_count'], 2)
        self.assertFalse(candidate['gap_qualified'])
        self.assertEqual(out['payload']['opportunities'], [])
        self.assertIn('supply_context_incomplete', candidate['reasons'])
        self.assertNotIn('慢啲', contracts.canonical(out))
        for s in inputs['common']['sources']:
            s['creator_key'] = None
        self.assertEqual(text_context.question_candidates(inputs)['candidates'], [])

    def test_unknown_semantic_dimensions_are_preserved(self):
        out = advanced.build_projection('genome', self.inputs(), now=NOW)
        self.assertTrue(out['details']['context_and_seeds']['seeds'])
        self.assertEqual(out['details']['dimensions']['topic_narrative']['state'], 'unknown')
        self.assertLessEqual(len(out['payload']['narrative_variants']), 3)
        self.assertTrue(all(v.startswith('Observed wording (meaning and stance unreviewed):')
                            for v in out['payload']['narrative_variants']))


if __name__ == '__main__':
    unittest.main()
