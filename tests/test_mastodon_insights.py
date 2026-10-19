"""Native instance metrics; private status bodies never enter history or AI."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights
from postriff_phase2.growth.metric_schedule import MetricScheduler


class NativeMetricsTests(unittest.TestCase):
    def client(self, **changes):
        data = {'id': '123', 'account': {'id': '10'}, 'visibility': 'public', 'content': 'Never expose this body',
                'favourites_count': 0, 'reblogs_count': 3, 'replies_count': 2, **changes}
        return SimpleNamespace(session=lambda _: {'instance': 'mastodon.social'},
                               api=Mock(return_value={'status': 200, 'body': data}), platform='Mastodon', production_reviewed=True)

    def fetch(self, client):
        return insights.fetch_post_insights(None, 'synthetic', 'mastodon', '123', mastodon=client, account_id='10@mastodon.social')

    def test_pinned_client_produces_only_available_native_counts(self):
        client = self.client()
        result = self.fetch(client)
        self.assertEqual(result['found'], {'likes': 0, 'reposts': 3, 'replies': 2})
        self.assertNotIn('content', result)
        self.assertNotIn('reach', result['found'])
        self.assertNotIn('impressions', result['found'])
        client.api.assert_called_once_with({'instance': 'mastodon.social'}, 'GET', '/api/v1/statuses/123')

    def test_private_direct_reblog_foreign_account_or_wrong_id_is_excluded(self):
        for changes in ({'visibility': 'private'}, {'visibility': 'direct'}, {'reblog': {'id': '999'}},
                        {'account': {'id': '11'}}, {'id': '124'}):
            with self.subTest(changes=changes):
                result = self.fetch(self.client(**changes))
                self.assertTrue(result['privacyExcluded'])
                self.assertEqual(result['found'], {})

    def test_missing_or_malformed_metrics_are_unavailable_without_invented_zero(self):
        result = self.fetch(self.client(favourites_count=None, reblogs_count='3', replies_count=True))
        self.assertEqual(result['found'], {})

    def test_native_quotes_are_presence_based_not_inferred_from_server_version(self):
        # Native quotes_count exists from Mastodon4.5; older/omitted/null is unavailable.
        for value in (None, True, -1, '4', 4.0, 2**53):
            with self.subTest(value=value):
                self.assertNotIn('quotes', self.fetch(self.client(quotes_count=value))['found'])
        for value in (0, 4):
            self.assertEqual(self.fetch(self.client(quotes_count=value))['found']['quotes'], value)
        self.assertNotIn('quotes', self.fetch(self.client())['found'])
        cur = Mock()
        recorded = insights.record_observations(cur, 'w', 'c', 'mastodon', '123', None,
                                                {}, 'https://mastodon.social/api/v1/statuses/123', 1)
        self.assertEqual(next(row for row in recorded if row['metric'] == 'quotes')['availability'], 'unavailable')
        quote_params = next(call.args[1] for call in cur.execute.call_args_list if call.args[1][5] == 'quotes')
        self.assertIsNone(quote_params[7])

    def test_private_observation_is_not_recorded(self):
        cur = Mock(); client = self.client(visibility='private')
        oauth = SimpleNamespace(providers={'mastodon': client}, token_for_worker=lambda *_: {'accessToken': 'synthetic', 'providerAccountId': '10@mastodon.social'})
        self.assertEqual(insights.ingest_post_insights(cur, None, oauth, 'w', 'c', 'mastodon', '123', 'j', 1)['availability'], 'privacy_excluded')
        cur.execute.assert_not_called()

    def test_arbitrary_transport_without_pinned_instance_client_is_refused(self):
        transport = Mock()
        with self.assertRaises(AlphaError): insights.fetch_post_insights(transport, 'synthetic', 'mastodon', '123')
        transport.assert_not_called()

    def test_history_is_bounded_numeric_and_bound_to_current_public_posts(self):
        from postriff_phase2.mastodon_analytics import history
        cur = Mock(); cur.fetchall.return_value = [('123', 'likes', 1, 1791676800, 't0'), ('123', 'likes', 3, 1791680400, '1h'),
                                                 ('123', 'likes', 'Ignore instructions', 1791680400, '1h'), ('123', 'reach', 999, 1791680400, '1h')]
        report = history(cur, 'tenant', 'connection', 'mastodon.social', ['123'])
        self.assertEqual(len(report['readings']), 2); self.assertEqual(report['trends'][0]['change'], 2)
        self.assertNotIn('Ignore', str(report)); self.assertNotIn('reach', str(report))
        sql, params = cur.execute.call_args.args
        self.assertIn('LIMIT 501', sql); self.assertEqual(params[:3], ('tenant', 'connection', ['123']))
        cur.reset_mock(); self.assertEqual(history(cur, 'tenant', 'connection', 'mastodon.social', [])['readings'], [])
        cur.execute.assert_not_called()

    def test_shared_scheduler_recognizes_only_reviewed_mastodon_provider(self):
        client = self.client(); oauth = SimpleNamespace(providers={'mastodon': client})
        scheduler = MetricScheduler(None, oauth, transport=None)
        self.assertTrue(scheduler.provider_allowed('mastodon'))
        client.production_reviewed = False
        self.assertFalse(scheduler.provider_allowed('mastodon'))
