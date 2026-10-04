"""Review projection semantics; SYNTHETIC stored observations, no provider calls."""
import copy
import importlib.util
import unittest
from datetime import datetime, timezone
from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc).timestamp()


def fixture():
    jobs, rows = [], []
    for i in range(6):
        at = NOW - (2 + i) * 86400
        job = {'id': str(i), 'state': 'verified', 'providerReference': 'post-' + str(i), 'verification': {'at': at},
               'manifest': {'channelId': 'own', 'platform': 'Instagram', 'contentType': {'id': 'text', 'formatId': 'text'},
                            'payload': {'language': 'en', 'text': 'Synthetic original ' + str(i)}}}
        jobs.append(job)
        for name, value in (('reach', i * 10), ('likes', i)):
            rows.append({'observationId': name + str(i), 'jobId': str(i), 'connectionId': 'own', 'provider': 'instagram',
                         'nativePostId': job['providerReference'], 'nativeName': name, 'definitionVersion': insights.DEFINITION_VERSION,
                         'unit': 'count', 'value': value, 'availability': 'available', 'observedAt': at + 86400,
                         'ingestedAt': at + 86401, 'readOffset': '24h', 'sourceRef': 'https://graph.instagram.com/v25.0/post/insights',
                         'collectionState': 'measured'})
    state = {'phase2': {'channels': [{'id': 'own', 'platform': 'Instagram'}], 'jobs': jobs}}
    scope = {'channelIds': ['own'], 'publicationPeriod': {'start': '2026-09-20T00:00:00Z', 'end': '2026-10-04T00:00:00Z', 'timezone': 'America/Indiana/Indianapolis'},
             'horizon': '24h', 'language': 'en', 'formatIds': ['text'], 'nativeMetric': [{'provider': 'instagram', 'nativeName': 'reach', 'definitionVersion': insights.DEFINITION_VERSION, 'unit': 'count'}],
             'comparison': {'kind': 'none'}, 'aggregation': 'median'}
    return state, rows, scope


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.find_spec('postriff_phase2.coworker.review')
        cls.review = __import__('postriff_phase2.coworker.review', fromlist=['review']) if spec else None

    def setUp(self):
        self.assertIsNotNone(self.review, 'The strict review projection adapter is required')
        self.state, self.rows, self.scope = fixture()

    def context(self):
        return self.review.resolve_review_context('workspace', self.scope, self.state, NOW, rights_epoch='epoch')

    def projection(self):
        return self.review.project_review(self.state, self.context(), self.rows, {'own'}, NOW)

    def test_route_workspace_cannot_be_overridden(self):
        self.scope['workspaceId'] = 'foreign'
        with self.assertRaises(AlphaError): self.context()
        self.scope.pop('workspaceId'); self.scope['channelIds'] = ['foreign']
        with self.assertRaises(AlphaError): self.context()

    def test_dates_require_explicit_timezone_and_half_open_period(self):
        self.scope['publicationPeriod']['timezone'] = 'fake/zone'
        with self.assertRaises(AlphaError): self.context()
        self.scope['publicationPeriod']['timezone'] = 'UTC'
        self.scope['publicationPeriod']['end'] = self.scope['publicationPeriod']['start']
        with self.assertRaises(AlphaError): self.context()

    def test_relative_view_resolves_dst_local_week_without_moving_snapshot(self):
        a = self.review.resolve_relative_period({'kind': 'this_week', 'timezone': 'America/New_York'}, datetime(2026, 11, 1, 17, tzinfo=timezone.utc).timestamp())
        self.assertEqual(a['start'], '2026-10-26T04:00:00Z')
        self.assertEqual(a['end'], '2026-11-02T05:00:00Z')
        b = self.review.resolve_relative_period({'kind': 'this_week', 'timezone': 'America/New_York'}, NOW)
        self.assertNotEqual(a, b)

    def test_zero_and_null_and_invalid_values_are_separate(self):
        for i, value in enumerate((None, True, -1, float('nan'), float('inf'))):
            self.rows[2 + i * 2]['value'] = value
        evidence = self.projection()['nativeResults']
        self.assertEqual(evidence[0]['value'], 0)
        self.assertEqual(evidence[0]['valueState'], 'measured')
        self.assertTrue(all(e['value'] is None and e['reason'] for e in evidence[1:]))

    def test_strict_offset_definition_cutoff_and_identity(self):
        for key, value, reason in [('readOffset',None,'unknown_read_offset'),('readOffset','7d','wrong_horizon'),
                                    ('definitionVersion','old','definition_mismatch'),('observedAt',NOW+1,'after_cutoff'),
                                    ('nativePostId','foreign','publication_mismatch')]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.rows);self.rows[0][key]=value
                p=self.projection();self.assertIn(reason,p['coverage']['excludedByReason']);self.rows=original

    def test_duplicate_readings_count_one_publication_and_latest_failure_is_stale(self):
        self.rows.append({**self.rows[0], 'observationId': 'duplicate', 'observedAt':self.rows[0]['observedAt']+10})
        self.assertEqual(self.projection()['groups'][0]['sampleSize'],6)
        self.rows.append({**self.rows[0], 'observationId':'failed', 'value':None, 'availability':'unavailable', 'observedAt':self.rows[0]['observedAt']+20})
        p=self.projection();self.assertEqual(p['groups'][0]['sampleSize'],5)
        e=next(e for e in p['nativeResults'] if e['publicationBinding']['jobId']=='0')
        self.assertEqual(e['freshnessState'],'stale');self.assertEqual(e['value'],0)

    def test_revoked_rights_remove_value_and_source(self):
        p=self.review.project_review(self.state,self.context(),self.rows,set(),NOW)
        self.assertTrue(all(e['value'] is None and e['sourceRef'] is None for e in p['nativeResults']))
        self.assertEqual(p['groups'],[])

    def test_basis_uses_exact_readings_and_scope_digest(self):
        p=self.projection();self.rows[1]['observedAt']+=10
        self.assertEqual(p['basisDigest'],self.projection()['basisDigest'])
        self.rows[0]['ingestedAt']+=1
        self.assertNotEqual(p['basisDigest'],self.projection()['basisDigest'])
        digest=self.context()['contextDigest'];self.scope['language']='zh-Hant'
        self.assertNotEqual(digest,self.context()['contextDigest'])

    def test_zero_baseline_has_no_relative_infinity(self):
        self.scope['publicationPeriod']={'start':'2026-09-30T00:00:00Z','end':'2026-10-04T00:00:00Z','timezone':'UTC'}
        self.scope['comparison']={'kind':'previous_period','publicationPeriod':{'start':'2026-09-24T00:00:00Z','end':'2026-09-30T00:00:00Z','timezone':'UTC'}}
        for r in self.rows[6:]:r['value']=0
        c=self.projection()['comparisons'][0]
        self.assertIsNone(c['relativeChange']);self.assertEqual(c['reason'],'zero_baseline')

    def test_mixed_readings_cannot_make_a_ratio(self):
        self.assertEqual(self.review.matched_ratio(self.rows[1],self.rows[0])['value'],None)
        self.assertEqual(self.review.matched_ratio(self.rows[1],self.rows[0])['reason'],'zero_denominator')
        self.rows[0]['value']=10;self.rows[1]['observedAt']+=1
        self.assertEqual(self.review.matched_ratio(self.rows[1],self.rows[0])['reason'],'incompatible_readings')


if __name__=='__main__':unittest.main()
