"""Timestamp regressions over native SQL shapes; no network or paid work."""
import copy
import unittest
from unittest.mock import patch

from postriff_phase2 import insights
from postriff_phase2.contracts import digest
from postriff_phase2.coworker import performance as hypotheses
from postriff_phase2.growth import postmortem
from test_rafii_analytics_acceptance import native_fixture, outputs, postmortem_fixture, NOW


class EvidenceTests(unittest.TestCase):
    def test_unrelated_refresh_does_not_change_primary_binding(self):
        fixture = native_fixture(unrelated_time=True)
        _, before, _ = outputs(fixture)
        changed = copy.deepcopy(fixture)
        changed['rows'] = [(*r[:8], r[8] + 20, r[9] + 20, *r[10:]) if r[3] == 'comments' else r for r in changed['rows']]
        _, after, _ = outputs(changed)
        self.assertEqual(before, after)
        self.assertEqual(before[0].get('ingestedAt'), fixture['rows'][1][9])
        self.assertEqual(before[0].get('definitionVersion'), insights.DEFINITION_VERSION)
        changed['rows'][1] = (*changed['rows'][1][:8], NOW - 50, NOW - 49, *changed['rows'][1][10:])
        self.assertNotEqual(digest(before), digest(outputs(changed)[1]))

    def test_legacy_lesson_does_not_invent_publication_period(self):
        _, _, report = postmortem_fixture()
        for lesson in report['lessons']:
            self.assertEqual(lesson.get('periodState'), 'legacy_period_unavailable')
            self.assertIsNone(lesson.get('supportPublicationPeriod'))
            self.assertTrue(lesson.get('supportBindings'))
            self.assertTrue(lesson.get('counterEvidenceBindings'))
            self.assertTrue(all(b['horizon'] == '24h' for b in lesson['supportBindings']))

    def test_lesson_periods_bind_exact_metric_and_digest_changes(self):
        posts, predictions, _ = postmortem_fixture()
        for p in posts:
            reading = p['readings']['24h']['shares']
            p.update(provider='threads', providerPostId='native-' + p['id'], publishedAt=reading['observedAt'] - 86400,
                     publicationDigest='manifest-' + p['id'])
            reading.update(observationId='obs-' + p['id'], ingestedAt=reading['observedAt'] + 1, readOffset='24h', unit='count')
        job = {'id': posts[-1]['id'], 'manifest': {'payload': {'text': 'Synthetic'}}}
        before = postmortem.build(job, predictions[job['id']], posts, predictions, '24h')
        lesson = before['lessons'][0]
        self.assertEqual(lesson.get('periodState'), 'available')
        self.assertEqual(lesson['supportObservationPeriod']['bounds'], 'closed')
        self.assertEqual(lesson['supportPublicationPeriod']['timezone'], 'UTC')
        self.assertTrue(all(b['observationId'].startswith('obs-') for b in lesson['supportBindings']))
        posts[0]['readings']['24h']['shares']['ingestedAt'] += 1
        self.assertNotEqual(digest(before), digest(postmortem.build(job, predictions[job['id']], posts, predictions, '24h')))

    def test_invalid_values_do_not_become_numbers_in_summary(self):
        fixture = native_fixture(1)
        for value in (True, False, '0', float('nan'), float('inf'), -1):
            rows = [(*fixture['rows'][0][:5], value, *fixture['rows'][0][6:])]
            with patch.object(insights, 'latest_observations', return_value=rows):
                metric = insights.summary(None, 'synthetic', fixture['state']['phase2']['jobs'], NOW)['posts'][0]['metrics']['reach']
            self.assertIsNone(metric['value'])


if __name__ == '__main__':
    unittest.main()
