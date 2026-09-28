"""Executed period/lineage construction, not pre-supplied cluster fixtures."""
from copy import deepcopy
import unittest

from postriff_phase2.growth.trends import contracts, narrative_periods, text_context
import test_trend_text_context as fixtures


class NarrativePeriodsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TextContextTests.setUpClass()

    def inputs(self):
        inputs = fixtures.TextContextTests().inputs()
        inputs['common']['decision_cutoff'] = '2026-09-30T22:00:00Z'
        native = '唔係放棄！慢啲 practice 🎹'
        for i, source in enumerate(inputs['common']['sources']):
            source['event_at'] = source['available_at'] = f'2026-09-{27+i//2:02}T12:00:00Z'
            source['language'] = 'yue'
            inputs['facts'][source['source_id']]['text'] = native
            inputs['facts'][source['source_id']]['relations'] = []
        return inputs

    def run_periods(self, inputs, **kwargs):
        raw, _ = text_context.reconstruct(inputs)
        return narrative_periods.project(inputs, raw, **kwargs)

    def test_actual_daily_groups_continuity_and_deduplicated_counts(self):
        inputs = self.inputs()
        out = self.run_periods(inputs)
        self.assertEqual(len(out['clusters']), 3)
        self.assertEqual(len(out['links']), 2)
        self.assertEqual({l['relation'] for l in out['links']}, {'continuation'})
        self.assertEqual(len({c['episode_id'] for c in out['clusters']}), 1)
        for cluster in out['clusters']:
            self.assertEqual(cluster['unique_original_posts'], 2)
            self.assertEqual(cluster['known_creators'], 2)
            self.assertEqual(cluster['mode'], 'exact_native_wording')
            self.assertEqual(cluster['semantic_qualification'], 'unqualified')
        self.assertIsNone(out['clusters'][1]['trajectory']['rate'])
        self.assertFalse(out['clusters'][1]['trajectory']['equal_coverage_established'])
        self.assertEqual(len(out['decisions']), 2)
        self.assertFalse(out['history_rewritten'])
        self.assertFalse(out['automatic_semantic_merges'])

    def test_native_punctuation_language_and_platform_are_not_erased(self):
        inputs = self.inputs()
        inputs['facts'][inputs['common']['sources'][1]['source_id']]['text'] += '？'
        inputs['common']['sources'][3]['language'] = 'zh-Hant'
        inputs['common']['sources'][5]['platform'] = 'mastodon'
        out = self.run_periods(inputs)
        self.assertEqual(len(out['clusters']), 6)
        self.assertEqual({c['language'] for c in out['clusters']}, {'yue', 'zh-Hant'})
        self.assertEqual({c['platform'] for c in out['clusters']}, {'bluesky', 'mastodon'})

    def test_recurrence_starts_new_episode_and_weeks_are_explicit_utc(self):
        inputs = self.inputs()
        for source in inputs['common']['sources'][4:]:
            source['event_at'] = source['available_at'] = '2026-10-10T12:00:00Z'
        inputs['common']['decision_cutoff'] = '2026-10-11T00:00:00Z'
        out = self.run_periods(inputs)
        self.assertEqual(out['links'][-1]['relation'], 'recurrence')
        self.assertNotEqual(out['clusters'][1]['episode_id'], out['clusters'][2]['episode_id'])
        weeks = self.run_periods(inputs, period='week')
        self.assertTrue(all(contracts.instant(c['period_start']).weekday() == 0 for c in weeks['clusters']))

    def test_future_records_and_reordering_leave_earlier_decision_unchanged(self):
        inputs = self.inputs()
        original = contracts.digest(self.run_periods(inputs))
        inputs['common']['sources'].reverse()
        self.assertEqual(original, contracts.digest(self.run_periods(inputs)))
        future = deepcopy(inputs['common']['sources'][0])
        future.update(source_id='future-only', available_at='2026-10-02T00:00:00Z', event_at='2026-10-01T00:00:00Z')
        inputs['common']['sources'].append(future)
        inputs['facts']['future-only'] = deepcopy(inputs['facts'][inputs['common']['sources'][0]['source_id']])
        self.assertEqual(original, contracts.digest(self.run_periods(inputs)))

    def annotations(self, inputs, reconstruction):
        return [{**deepcopy(seed), 'concept': 'Deliberate practice', 'claim': 'Practice slowly',
                 'stance': 'support' if i % 2 else 'oppose', 'available_at': inputs['common']['decision_cutoff'],
                 'expires_at': inputs['expires_at'], 'method_version': 'synthetic-reviewed-annotation-v1'}
                for i, seed in enumerate(reconstruction['seeds'])]

    def test_opposing_stances_never_merge_and_annotations_do_not_self_qualify(self):
        inputs = self.inputs()
        raw, _ = text_context.reconstruct(inputs)
        annotations = self.annotations(inputs, raw)
        out = narrative_periods.project(inputs, raw, annotations=annotations)
        self.assertEqual(len(out['clusters']), 6)
        self.assertEqual({c['stance'] for c in out['clusters']}, {'support', 'oppose'})
        self.assertTrue(all(c['semantic_qualification'] == 'unqualified' for c in out['clusters']))
        self.assertFalse(out['automatic_semantic_merges'])
        reviewed = narrative_periods.project(inputs, raw, annotations=annotations, semantic_qualified=True)
        self.assertTrue(all(c['mode'] == 'reviewed_claim' for c in reviewed['clusters']))
        self.assertEqual(len(reviewed['clusters']), 6)

    def test_annotation_current_right_and_time_checks_and_exact_span_binding(self):
        inputs = self.inputs()
        raw, _ = text_context.reconstruct(inputs)
        annotations = self.annotations(inputs, raw)
        before = narrative_periods.project(inputs, raw)
        for a in annotations:
            a['available_at'] = '2026-10-01T00:00:00Z'
        self.assertEqual(before, narrative_periods.project(inputs, raw, annotations=annotations))
        annotations = self.annotations(inputs, raw)
        for source in inputs['common']['sources']:
            source['rights']['llm'] = False
        self.assertEqual(before, narrative_periods.project(inputs, raw, annotations=annotations))
        annotations[0]['original_spans'][0]['text'] = 'invented quote'
        with self.assertRaisesRegex(ValueError, 'evidence_binding'):
            narrative_periods.project(inputs, raw, annotations=annotations)

    def test_revocation_removes_every_dependent_membership(self):
        inputs = self.inputs()
        raw, _ = text_context.reconstruct(inputs)
        revoked = inputs['common']['sources'][0]['source_id']
        inputs['common']['sources'][0]['rights']['creative'] = False
        out = narrative_periods.project(inputs, raw)
        self.assertFalse(any(revoked in c['evidence_refs'] for c in out['clusters']))
        self.assertFalse(any(revoked in l['evidence_refs'] for l in out['links']))


if __name__ == '__main__':
    unittest.main()
