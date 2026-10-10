"""Evidence projections: real domain functions with synthetic stored records; no providers."""
import copy
import json
import types
import unittest
from unittest.mock import patch

from postriff_phase2 import evidence, insights
from postriff_phase2.coworker import fact_pack
from postriff_phase2.agent_runtime_v2.ui_domain import analytics, drafts


class EvidenceModeTests(unittest.TestCase):
    def setUp(self):
        self.now = 1791633600
        self.post = {'provider': 'threads', 'platform': 'Threads', 'providerPostId': 'post-1', 'connectionId': 'account-1', 'jobId': 'job-1'}
        self.reading = {'value': 0, 'availability': 'available', 'unit': 'count', 'observedAt': self.now - 60,
                        'ingestedAt': self.now - 30, 'periodStart': self.now - 3600, 'definitionVersion': insights.DEFINITION_VERSION}

    def test_metric_native_zero_and_exact_collection_sync_not_query_time(self):
        result = evidence.metric('workspace-a', self.post, 'views', self.reading)
        self.assertEqual(result['classification'], 'observed')
        self.assertEqual(result['source']['entityId'], 'post-1')
        self.assertEqual(result['collectionPeriod']['start'], evidence.instant(self.now - 3600))
        self.assertEqual(result['collectionPeriod']['end'], evidence.instant(self.now - 60))
        self.assertEqual(result['lastSuccessfulSync'], evidence.instant(self.now - 30))
        self.assertEqual(result['definition']['version'], insights.DEFINITION_VERSION)

    def test_unavailable_does_not_claim_sync_or_invent_collection_start(self):
        result = evidence.metric('workspace-a', self.post, 'reach', {'availability': 'not_supported', 'observedAt': self.now, 'ingestedAt': self.now})
        self.assertEqual(result['availability'], 'not_supported')
        self.assertIsNone(result['lastSuccessfulSync'])
        self.assertIsNone(result['collectionPeriod']['start'])
        self.assertTrue(result['uncertainty'])

    def test_projection_refuses_cross_workspace_and_founder_rows(self):
        for foreign in ({'workspaceId': 'workspace-b'}, {'scope': 'founder'}):
            with self.assertRaises(ValueError):
                evidence.metric('workspace-a', {**self.post, **foreign}, 'views', self.reading)
            with self.assertRaises(ValueError):
                evidence.source('workspace-a', {'id': 'source', **foreign})

    def test_factpack_disputed_and_snippet_status_kept_without_hash_mutation(self):
        sources = [{'id': 's1', 'title': 'Report A', 'text': 'The bakery sold 400 loaves on Saturday in Kennedy Town.', 'provenance': {'evidenceType': 'page_text', 'host': 'a.example', 'retrievedAt': self.now}},
                   {'id': 's2', 'title': 'Report B', 'text': 'The bakery sold 900 loaves on Saturday in Kennedy Town.', 'provenance': {'evidenceType': 'page_text', 'host': 'b.example'}},
                   {'id': 's3', 'title': 'Snippet', 'text': 'Another company is planning a festival this November.', 'provenance': {'evidenceType': 'search_snippet'}}]
        pack = fact_pack.build(sources, self.now)
        before = copy.deepcopy(pack)
        result = evidence.fact_pack('workspace-a', pack, sources)
        self.assertEqual(pack, before)
        self.assertEqual({r['evidence']['availability'] for r in result}, {'disputed', 'unverified'})
        self.assertTrue(all(r['evidence']['lastSuccessfulSync'] is None for r in result))
        self.assertTrue(all(r['evidence']['definition']['version'] == 'rafii.factpack.v1' for r in result))

    def test_retracted_source_does_not_claim_available(self):
        result = evidence.source('workspace-a', {'id': 's1', 'retracted': True, 'origin': {'retrievedAt': self.now}})
        self.assertEqual(result['availability'], 'unavailable')
        self.assertIsNone(result['lastSuccessfulSync'])

    def test_analytics_query_keeps_unsupported_and_workspace_scope(self):
        job = {'id': 'job-1', 'state': 'verified', 'publishedAt': self.now - 3600, 'manifest': {}}
        ctx = types.SimpleNamespace(workspace_id='workspace-a', now=self.now, zone='UTC', state={'phase2': {'jobs': [job]}})
        post = {**self.post, 'metrics': {'all': {'value': None, 'availability': 'not_supported', 'observedAt': self.now - 60}}}
        with patch.object(analytics, '_summary', return_value={'posts': [post]}):
            result = analytics.analytics_posts(ctx, {'metric': 'reach'}, None)['data']
        reading = result['posts'][0]['metrics']['reach']
        self.assertIsNone(reading['value'])
        self.assertEqual(reading['availability'], 'not_supported')
        self.assertEqual(reading['evidence']['workspaceId'], result['workspaceId'])
        self.assertNotEqual(reading['evidence']['collectionPeriod']['end'], result['endUtc'])

    def test_full_page_stays_bounded_and_preserves_cursor(self):
        jobs, posts = [], []
        for i in range(100):
            jobs.append({'id': f'job-{i}', 'state': 'verified', 'publishedAt': self.now - 3600, 'manifest': {}})
            posts.append({**self.post, 'jobId': f'job-{i}', 'providerPostId': f'post-{i}', 'metrics': {m: self.reading for m in analytics.METRICS}})
        ctx = types.SimpleNamespace(workspace_id='workspace-a', now=self.now, zone='UTC', state={'phase2': {'jobs': jobs}})
        with patch.object(analytics, '_summary', return_value={'posts': posts}):
            result = analytics.analytics_posts(ctx, {'limit': 100}, None)
            next_page = analytics.analytics_posts(ctx, {'limit': 100}, result['nextCursor'])
        self.assertEqual(len(result['data']['posts']), 20)
        self.assertEqual(next_page['data']['offset'], 20)
        self.assertLess(len(json.dumps(result).encode()), 256 * 1024)

    def test_insights_reads_bound_workspace_and_preserves_native_availability(self):
        class Cursor:
            def execute(self, sql, args):
                self.sql, self.args = sql, args
            def fetchall(self):
                return [('threads', 'p', 'j', 'all', '2026-09', None, 'count', 'not_supported', 100, 101, 'c', None, None),
                        ('threads', 'p', 'j', 'views', '2026-09', 0, 'count', 'available', 99, 100, 'c', '1h', 50)]
        cur = Cursor()
        with patch.object(insights, 'read_offset_column', return_value='o.read_offset'):
            result = insights.summary(cur, 'workspace-a', [], 999)
        self.assertEqual(cur.args, ('workspace-a',))
        self.assertIn('WHERE workspace_id=%s', cur.sql)
        self.assertIn('period_start', cur.sql)
        metrics = result['posts'][0]['metrics']
        self.assertEqual(metrics['all']['availability'], 'not_supported')
        self.assertEqual(metrics['views']['periodStart'], 50)
        self.assertEqual(metrics['views']['ingestedAt'], 100)

    def test_draft_uses_only_linked_active_sources_and_linked_factpack(self):
        state = {'variants': [{'id': 'v1', 'sourceIds': ['s1'], 'revision': 1}],
                 'sources': [{'id': 's1', 'title': 'Allowed', 'active': True}],
                 'coworker': {'sourceCampaigns': [{'sourceId': 'foreign', 'source': {'id': 'f', 'title': 'DO NOT LEAK'}, 'factPack': {'claims': []}}]}}
        ctx = types.SimpleNamespace(workspace_id='workspace-a', now=self.now, state=state, site_context=lambda: None)
        from postriff_phase2.agent_runtime_v2 import graph
        from postriff_phase2.site_agent import reads
        with patch.object(drafts, '_variant', return_value=state['variants'][0]), patch.object(graph, 'neighbours', return_value={}), patch.object(reads, 'voice_check', return_value={'data': {}}):
            data = drafts.draft_evidence(ctx, {'draftId': 'v1'}, None)['data']
        self.assertEqual(data['workspaceId'], 'workspace-a')
        self.assertEqual(data['sources'][0]['evidence']['source']['document'], 'Allowed')
        self.assertNotIn('DO NOT LEAK', str(data))
        self.assertEqual(data['sources'][0]['claims'], [])

    def test_draft_budget_counts_relationships_across_sources_and_reports_truncation(self):
        source_rows = [{'id': 's1', 'active': True}, {'id': 's2', 'active': True}]
        state = {'sources': source_rows, 'coworker': {'sourceCampaigns': []}}
        for row in source_rows:
            pack = {'schema': 'rafii.factpack.v1', 'claims': [
                {'claimId': f'claim-{i}', 'status': 'attributed', 'evidence': [{'sourceId': row['id'], 'relation': 'supports'}] * 2}
                for i in range(10)]}
            state['coworker']['sourceCampaigns'].append({'sourceId': row['id'], 'source': row, 'factPack': pack})
        ctx = types.SimpleNamespace(workspace_id='workspace-a', now=self.now, state=state, site_context=lambda: None)
        from postriff_phase2.agent_runtime_v2 import graph
        from postriff_phase2.site_agent import reads
        with patch.object(drafts, '_variant', return_value={'id': 'v1', 'sourceIds': ['s1', 's2']}), patch.object(graph, 'neighbours', return_value={}), patch.object(reads, 'voice_check', return_value={'data': {}}):
            data = drafts.draft_evidence(ctx, {'draftId': 'v1'}, None)['data']
        self.assertTrue(data['claimsTruncated'])
        self.assertEqual([len(source['claims']) for source in data['sources']], [20, 10])


if __name__ == '__main__':
    unittest.main()
