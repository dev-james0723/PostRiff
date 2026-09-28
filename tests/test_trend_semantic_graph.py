"""Pure graph adapter tests; synthetic reviewed annotations, no DB/model I/O."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from postriff_phase2.growth.trends import graph, semantic_admission, semantic_graph as S, text_context
import test_trend_text_context as fixture

NOW = '2026-09-27T20:01:00Z'
MODEL_AT = '2026-09-27T20:00:30Z'


class SemanticGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TextContextTests.setUpClass()
        cls.fixture = fixture.TextContextTests()

    def setUp(self):
        for target in ('socket.create_connection', 'socket.socket.connect', 'socket.getaddrinfo', 'urllib.request.urlopen'):
            guard = patch(target, side_effect=AssertionError('no provider/network calls'))
            mock = guard.start(); self.addCleanup(guard.stop); self.addCleanup(mock.assert_not_called)
        self.inputs = self.fixture.inputs()
        self.raw, _ = text_context.reconstruct(self.inputs)
        self.seed = self.raw['seeds'][0]
        self.sid = self.seed['evidence_refs'][0]

    def annotation(self, seed=None, **overrides):
        return {**deepcopy(seed or self.seed), 'concept': '練習', 'claim': '慢練有助準確', 'stance': 'support',
                'available_at': MODEL_AT, 'expires_at': self.inputs['expires_at'], 'review_status': 'cohort_reviewed',
                'derivation_kind': 'model_interpretation', 'method_version': 'synthetic-reviewed-method', **overrides}

    def semantic(self, annotations=None, **overrides):
        return {'annotations': [self.annotation()] if annotations is None else annotations, 'conflicts': [],
                'expires_at': self.inputs['expires_at'], 'source_decision_cutoff': self.inputs['common']['decision_cutoff'],
                'decision_cutoff': NOW, **overrides}

    def build(self, semantic=None, now=NOW):
        return S.build_graph_input(self.inputs, self.raw, semantic, now=now)

    @staticmethod
    def interpreted(result):
        return [n for n in result['nodes'] if n['node_type'] in ('topic', 'narrative_episode')]

    def test_exact_native_literal_fallback_is_not_semantic_qualification(self):
        native = '係咪要慢啲練？🎹 piano...  唔係「放棄」！\nSecond line'
        source = next(s for s in self.inputs['common']['sources'] if s['source_id'] == self.sid)
        source['language'] = 'yue'; self.inputs['facts'][self.sid]['text'] = native
        self.raw, _ = text_context.reconstruct(self.inputs)
        result = self.build()
        phrase = next(n for n in result['nodes'] if n['node_type'] == 'phrase' and n['evidence_refs'] == [self.sid])
        self.assertEqual(phrase['label'], native.splitlines()[0])
        self.assertEqual(phrase['language'], 'yue'); self.assertEqual(phrase['platform'], source['platform'])
        self.assertEqual(phrase['scope_key'], source['scope_key'])
        self.assertEqual(phrase['original_spans'][0]['text'], phrase['label'])
        self.assertEqual(self.interpreted(result), []); self.assertEqual(result['semantic_state'], 'literal_only')
        self.assertEqual(result['claims'], []); self.assertEqual(result['origin'], 'unknown')

    def test_reviewed_topic_episode_and_edges_project_with_evidence_and_no_causality(self):
        result = self.build(self.semantic()); output = graph.project_graph(result)
        self.assertEqual({n['node_type'] for n in self.interpreted(result)}, {'topic', 'narrative_episode'})
        self.assertEqual(len(self.interpreted(output)), 2)
        hypotheses = [e for e in output['edges'] if e['evidence_kind'] == 'model_hypothesis']
        self.assertEqual(len(hypotheses), 2)
        for edge in hypotheses:
            self.assertEqual(edge['evidence_refs'], [self.sid]); self.assertEqual(edge['available_at'], MODEL_AT)
            self.assertEqual(edge['claim_type'], 'hypothesis'); self.assertEqual(edge['edge_type'], 'co_occurrence')
        self.assertFalse(output['causal_claims']); self.assertEqual(output['origin'], 'unknown')
        self.assertFalse(any(e['edge_type'] in {'explicit_identity', 'possible_adaptation', 'continuity', 'reply'} for e in result['edges']))

    def test_model_availability_is_separate_from_source_and_current_cutoffs(self):
        result = self.build(self.semantic())
        self.assertEqual(result['decision_cutoff'], NOW)
        self.assertEqual(result['source_decision_cutoff'], self.inputs['common']['decision_cutoff'])
        for node in self.interpreted(result):
            self.assertEqual(node['available_at'], MODEL_AT); self.assertEqual(node['computed_at'], NOW)
        past = graph.project_graph({**result, 'decision_cutoff': result['source_decision_cutoff']})
        self.assertEqual(self.interpreted(past), [])

    def test_future_missing_or_expired_model_time_cannot_backdate_interpretation(self):
        for change in ({'available_at': '2026-09-28T00:00:00Z'}, {'available_at': None},
                       {'expires_at': '2026-09-27T20:00:45Z'}):
            with self.subTest(change=change):
                result = self.build(self.semantic([self.annotation(**change)]))
                self.assertEqual(self.interpreted(result), [])
                self.assertTrue(any(n['node_type'] == 'phrase' for n in result['nodes']))

    def test_current_rights_revoke_exact_support_without_inventing_aggregate_permission(self):
        original = deepcopy(self.inputs)
        for permission in ('analysis', 'creative', 'display'):
            with self.subTest(permission=permission):
                self.inputs = deepcopy(original)
                source = next(s for s in self.inputs['common']['sources'] if s['source_id'] == self.sid)
                source['rights'][permission] = False
                result = self.build(self.semantic())
                self.assertFalse(any(self.sid in n['evidence_refs'] for n in result['nodes']))
                self.assertFalse(any(self.sid in e['evidence_refs'] for e in result['edges']))
                self.assertFalse(any(s['source_id'] == self.sid for s in result['sources']))

    def test_llm_denial_keeps_permitted_literal_wording_only(self):
        source = next(s for s in self.inputs['common']['sources'] if s['source_id'] == self.sid)
        source['rights']['llm'] = False
        result = self.build(self.semantic())
        self.assertEqual(self.interpreted(result), [])
        self.assertTrue(any(n['node_type'] == 'phrase' and self.sid in n['evidence_refs'] for n in result['nodes']))

    def test_source_expiry_after_acquisition_before_read_hides_its_nodes(self):
        source = next(s for s in self.inputs['common']['sources'] if s['source_id'] == self.sid)
        source['expires_at'] = '2026-09-27T20:00:45Z'
        self.assertFalse(any(self.sid in n['evidence_refs'] for n in self.build(self.semantic())['nodes']))
        self.inputs['expires_at'] = '2026-09-27T20:00:45Z'
        self.assertEqual(self.build()['nodes'], [])

    def test_future_source_availability_cannot_enter_earlier_acquisition_snapshot(self):
        source = next(s for s in self.inputs['common']['sources'] if s['source_id'] == self.sid)
        source['available_at'] = MODEL_AT
        result = self.build(self.semantic())
        self.assertFalse(any(self.sid in n['evidence_refs'] for n in result['nodes']))

    def test_unreviewed_metadata_or_dimension_only_claims_do_not_create_topics(self):
        for change in ({'review_status': 'unqualified'}, {'review_status': None}, {'derivation_kind': 'provider'},
                       {'method_version': ''}, {'stance': 'endorsement_guessed'}):
            with self.subTest(change=change):
                self.assertEqual(self.interpreted(self.build(self.semantic([self.annotation(**change)]))), [])
        self.assertEqual(self.interpreted(self.build({'dimensions': {'topic_narrative': {'value': 'self-attested'}}})), [])

    def test_conflicting_annotations_abstain_in_both_orders_and_keep_literal(self):
        annotations = [self.annotation(), self.annotation(stance='oppose')]
        first = self.build(self.semantic(annotations)); second = self.build(self.semantic(annotations[::-1]))
        self.assertEqual(first, second); self.assertEqual(self.interpreted(first), [])
        self.assertIn(self.seed['seed_id'], first['conflicted_seed_ids'])
        self.assertTrue(any(n['node_type'] == 'phrase' for n in first['nodes']))
        declared = self.semantic(conflicts=[{'seed_id': self.seed['seed_id'], 'reason': 'conflicting_reviewed_interpretations'}])
        self.assertEqual(self.interpreted(self.build(declared)), [])

    def test_independent_seed_stances_and_episodes_are_not_silently_merged(self):
        other = self.raw['seeds'][1]
        annotations = [self.annotation(), self.annotation(other, stance='oppose')]
        result = self.build(self.semantic(annotations))
        episodes = [n for n in result['nodes'] if n['node_type'] == 'narrative_episode']
        self.assertEqual(len(episodes), 2); self.assertEqual({n['stance'] for n in episodes}, {'support', 'oppose'})
        first_id = self.interpreted(self.build(self.semantic()))
        self.inputs['episode_id'] = self.raw['episode_id'] = 'separate-recurrence'
        second_id = self.interpreted(self.build(self.semantic()))
        self.assertNotEqual(next(n['node_id'] for n in first_id if n['node_type'] == 'narrative_episode'),
                            next(n['node_id'] for n in second_id if n['node_type'] == 'narrative_episode'))

    def test_exact_concept_and_stance_changes_have_distinct_episode_identity(self):
        def episode(ann): return next(n['node_id'] for n in self.build(self.semantic([ann]))['nodes'] if n['node_type'] == 'narrative_episode')
        ids = {episode(self.annotation()), episode(self.annotation(concept='另一概念')), episode(self.annotation(stance='oppose'))}
        self.assertEqual(len(ids), 3)

    def test_same_native_text_in_different_language_platform_cohorts_is_not_one_phrase(self):
        first, second = self.inputs['common']['sources'][:2]
        for source, platform, language in ((first, 'bluesky', 'yue'), (second, 'mastodon', 'zh-Hant')):
            source.update(platform=platform, language=language)
            self.inputs['facts'][source['source_id']]['text'] = '同一句 native words'
        self.raw, _ = text_context.reconstruct(self.inputs)
        phrases = [n for n in self.build()['nodes'] if n['node_type'] == 'phrase' and n['label'] == '同一句 native words']
        self.assertEqual(len(phrases), 2); self.assertEqual(len({n['node_id'] for n in phrases}), 2)
        self.assertEqual({(n['platform'], n['language']) for n in phrases}, {('bluesky', 'yue'), ('mastodon', 'zh-Hant')})

    def test_tampered_native_span_or_foreign_annotation_support_never_labels_topic(self):
        annotation = self.annotation(); annotation['original_spans'][0]['text'] = 'invented English gloss'
        self.assertEqual(self.interpreted(self.build(self.semantic([annotation]))), [])
        for change in ({'scope_key': 'shared:foreign'}, {'language': 'wrong'}, {'evidence_refs': ['missing-source']}):
            self.assertEqual(self.interpreted(self.build(self.semantic([self.annotation(**change)]))), [])
        self.seed['original_spans'][0]['text'] = 'invented native quotation'
        self.assertFalse(any(self.sid in n['evidence_refs'] for n in self.build()['nodes']))

    def test_reconstruction_scope_episode_and_cutoff_cannot_be_substituted(self):
        for key, value in (('scope_key', 'shared:other'), ('episode_id', 'other'), ('decision_cutoff', NOW)):
            original = self.raw[key]; self.raw[key] = value
            with self.assertRaisesRegex(ValueError, 'reconstruction_binding'): self.build()
            self.raw[key] = original
        with self.assertRaisesRegex(ValueError, 'current_cutoff'): self.build(now='2026-09-27T19:00:00Z')

    def test_conflicting_bundle_or_seed_serialization_abstains_independent_of_order(self):
        original = deepcopy(self.raw)
        bundle = next(b for b in self.raw['bundles'] if b['bundle_id'] in self.seed['bundle_ids'])
        self.raw['bundles'].append({**deepcopy(bundle), 'member_ids': ['foreign-source']})
        first = self.build(self.semantic()); self.raw['bundles'].reverse()
        self.assertEqual(first, self.build(self.semantic()))
        self.assertFalse(any(self.sid in n['evidence_refs'] for n in first['nodes']))
        self.raw = original
        other = deepcopy(self.raw['seeds'][1]); other['seed_id'] = self.seed['seed_id']
        self.raw['seeds'].append(other)
        first = self.build(self.semantic()); self.raw['seeds'].reverse()
        self.assertEqual(first, self.build(self.semantic()))
        self.assertEqual(self.interpreted(first), [])

    def test_current_revocation_and_invalid_annotation_shapes_keep_only_literal(self):
        for change in ({'revoked': True}, {'deleted': True}, {'original_spans': None}, {'original_spans': {}}):
            with self.subTest(change=change):
                self.assertEqual(self.interpreted(self.build(self.semantic([self.annotation(**change)]))), [])
        for change in ({'revoked': True}, {'deleted': True}, {'source_decision_cutoff': NOW},
                       {'decision_cutoff': '2026-09-27T20:02:00Z'}):
            with self.subTest(change=change):
                self.assertEqual(self.interpreted(self.build(self.semantic(**change))), [])

    def test_does_not_mutate_source_reconstruction_or_reviewed_annotations(self):
        semantic = self.semantic(); before = deepcopy((self.inputs, self.raw, semantic))
        self.build(semantic)
        self.assertEqual((self.inputs, self.raw, semantic), before)

    def test_order_and_duplicate_agreement_do_not_change_output_or_availability(self):
        annotations = [self.annotation(), self.annotation(method_version='second-reviewed', available_at='2026-09-27T20:00:40Z')]
        before = self.build(self.semantic(annotations))
        self.inputs['common']['sources'].reverse(); self.raw['seeds'].reverse(); self.raw['bundles'].reverse()
        after = self.build(self.semantic(annotations[::-1]))
        self.assertEqual(before, after)
        self.assertTrue(all(n['available_at'] == '2026-09-27T20:00:40Z' for n in self.interpreted(after)))

    def test_bounded_adversarial_serialization_and_no_dangling_edges(self):
        # All spans remain real; multiplying exact subspans cannot overflow the
        # graph even if a serialized reconstruction contains many small spans.
        for source in self.inputs['common']['sources']:
            self.inputs['facts'][source['source_id']]['text'] = ''.join(chr(0x4e00+i) for i in range(240))
        self.raw, _ = text_context.reconstruct(self.inputs)
        for seed in self.raw['seeds']:
            sid = seed['evidence_refs'][0]; text = self.inputs['facts'][sid]['text']
            seed['original_spans'] = [{'source_id': sid, 'start': i*10, 'end': i*10+10, 'text': text[i*10:i*10+10]} for i in range(20)]
        result = self.build(); ids = {n['node_id'] for n in result['nodes']}
        self.assertEqual(len(ids), S.MAX_NODES); self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['edges']), S.MAX_EDGES)
        self.assertTrue(all(e['source_id'] in ids and e['target_id'] in ids for e in result['edges']))
        self.assertLessEqual(len(graph.project_graph(result)['nodes']), 100)

    def test_oversized_collections_refused_and_upstream_truncation_preserved(self):
        with self.assertRaises(ValueError): self.build(self.semantic([self.annotation()] * 1001))
        self.raw['truncated'] = True
        self.assertTrue(self.build()['truncated'])
        self.inputs['common']['sources'] *= 167
        with self.assertRaises(ValueError): self.build()

    def test_actual_semantic_adapter_preserves_real_time_and_conflict_abstention(self):
        source = next(s for s in self.inputs['common']['sources'] if s['source_id'] == self.sid)
        text = self.inputs['facts'][self.sid]['text']
        item = {'id': 'synthetic-reviewed', 'concept': 'Practice', 'claim': 'Slow practice helps precision', 'stance': 'supports',
                'language': source['language'], 'uncertainties': ['Synthetic fixture, not live qualification'],
                'evidence_spans': [{'observation_id': self.sid, 'start': 0, 'end': len(text), 'text': text}]}
        entry = {'task': 'semantic_label_generate', 'qualified': True, 'available_at': MODEL_AT, 'expires_at': self.inputs['expires_at'],
                 'result': {'task': 'trend.semantic_label_generate', 'status': 'ok', 'executed_model': 'synthetic',
                            'input_digest': 'a'*64, 'items': [item]}}
        adapted = semantic_admission.adapt(self.inputs, [entry], NOW)
        self.assertTrue(self.interpreted(self.build(adapted)))
        self.assertTrue(all(n['available_at'] == MODEL_AT for n in self.interpreted(self.build(adapted))))
        entry['result']['items'].append({**deepcopy(item), 'id': 'opposite', 'stance': 'opposes'})
        adapted = semantic_admission.adapt(self.inputs, [entry], NOW)
        self.assertEqual(self.interpreted(self.build(adapted)), [])


if __name__ == '__main__': unittest.main()
