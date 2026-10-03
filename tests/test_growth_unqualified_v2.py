"""Synthetic recording: unqualified acquisition cannot precede v2 funding admission."""
from contextlib import contextmanager
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from postriff_phase2.radar.service import Radar
from postriff_phase2.growth import history_import, scout_runtime


class Cursor:
    def __init__(self, mode):
        self.mode, self.sql = mode, ''
        self.writes = []

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def execute(self, sql, params=None):
        self.sql = sql
        if sql.startswith(('INSERT', 'UPDATE')): self.writes.append(sql)

    def fetchone(self):
        if self.sql.startswith('SELECT id FROM public.pr_workspaces'): return ('workspace',)
        if self.sql.startswith('SELECT status,extract'): return ('active', None, False, None, 'studio-v1')
        if self.sql.startswith('SELECT plan_terms_id'): return ('studio-v1',)
        if 'pr_entitlements' in self.sql:
            return ('free', None) if self.mode == 'free' else ('creator', V2_POLICY_VERSION) if self.mode == 'managed' else ('pro', None)
        if "state ? 'accountDeletion'" in self.sql: return (False,)
        if 'SELECT state FROM' in self.sql: return ({},)
        if 'pr_encrypted_credentials' in self.sql: return ('threads',)
        if 'INSERT INTO public.pr_radar_runs' in self.sql: return ('run',)
        return None

    def fetchall(self): return []


class Database:
    def __init__(self, cur): self.cur = cur
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self.cur
    def commit(self): pass


class UnsupportedV2(unittest.TestCase):
    def radar(self, mode, status='quoted'):
        cur = Cursor(mode)
        sources = SimpleNamespace(catalog=lambda: [{'id': 'exa', 'status': 'ready'}], ceiling=lambda source: 200_000,
                                  search=Mock(return_value={'items': [], 'costUsdMicro': 1, 'costSource': 'provider'}))
        host = SimpleNamespace(connection_factory=lambda: Database(cur),
                               billing=SimpleNamespace(pricing_v2_enabled=True), clock=lambda: 1_000_000)
        growth = SimpleNamespace(hosted=host, repository=None, clock=lambda: 1_000_000,
                                 env={'POSTRIFF_RADAR_CREDIT_BILLING': '0'}, reserve=Mock(), cap=lambda key: 1_000_000)
        r = Radar(growth, sources)
        body = {'mode': 'quick', 'query': 'piano practice', 'sources': ['exa'], 'useAi': False,
                'maximumUsdMicro': 1_000_000, 'quoteExpiresAt': 1_000_100, 'spentCeiling': 0,
                'steps': [], 'items': [], 'judgments': {}, 'genome': {}, 'usage': {'knownUsdMicro': 0, 'unknownAttempts': 0}}
        @contextmanager
        def tx(*args): yield cur, (1, {}), 'actor'
        r.tx = tx; r.permitted = lambda *args: None; r.context = lambda state: 'context'
        r.visible = lambda row: {'status': row[1]}; r.load = lambda *args: ('run', status, 'context', body, None, None, 'actor')
        r.next_step = lambda body: 'source:exa'
        r.save = Mock(); r.finish = Mock(return_value={'status': 'done'})
        return r, cur, growth, sources

    def refusal(self, function):
        with self.assertRaises(AlphaError) as caught: function()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, 'growth_credit_bridge_unavailable')

    @patch('postriff_phase2.radar.service._membership', return_value={})
    @patch('postriff_phase2.radar.service.require')
    def test_radar_new_paid_quote_has_no_customer_authority(self, *_):
        for mode in ('free', 'managed'):
            with self.subTest(mode=mode):
                r, cur, _, source = self.radar(mode)
                self.refusal(lambda: r.quote('workspace', 'token', {'mode': 'quick', 'query': 'piano', 'sources': ['exa'], 'requestKey': 'recording-request-key'}))
                self.assertFalse(cur.writes); source.search.assert_not_called()

    @patch('postriff_phase2.radar.service._membership', return_value={})
    @patch('postriff_phase2.radar.service.require')
    def test_radar_old_quote_cannot_start_after_v2_transition(self, *_):
        for mode in ('free', 'managed'):
            with self.subTest(mode=mode):
                r, _, growth, source = self.radar(mode)
                self.refusal(lambda: r.start('workspace', 'token', 'run', {'confirmed': True}))
                growth.reserve.assert_not_called(); source.search.assert_not_called()

    @patch('postriff_phase2.radar.service._membership', return_value={})
    @patch('postriff_phase2.radar.service.require')
    def test_radar_running_paid_scan_cannot_acquire_after_v2_transition(self, *_):
        for mode in ('free', 'managed'):
            with self.subTest(mode=mode):
                r, _, _, source = self.radar(mode, 'running')
                self.refusal(lambda: r.advance('workspace', 'token', 'run'))
                source.search.assert_not_called()

    @patch('postriff_phase2.growth.scout_runtime.complete', return_value=None)
    @patch('postriff_phase2.growth.scout_runtime.reserve', return_value={'query': 'piano'})
    @patch('postriff_phase2.growth.trends.config.workspace_allowed', return_value=False)
    def test_scout_refuses_before_claim_or_retrieval(self, _, claim, __):
        for mode in ('free', 'managed'):
            with self.subTest(mode=mode):
                claim.reset_mock(); cur = Cursor(mode)
                broker = SimpleNamespace(search_items=Mock(return_value={'status': 'unavailable'}))
                host = SimpleNamespace(connection_factory=lambda: Database(cur),
                                       billing=SimpleNamespace(pricing_v2_enabled=True), clock=lambda: 1_000_000)
                service = SimpleNamespace(clock=host.clock, values={}, hosted=host, _broker=lambda state: broker)
                result = scout_runtime.run_workspace(service, 'workspace', time.monotonic() + 1000, broker=broker)
                self.assertEqual(result.get('reason'), 'growth_credit_bridge_unavailable')
                claim.assert_not_called(); broker.search_items.assert_not_called(); self.assertFalse(cur.writes)

    @patch('postriff_phase2.radar.service._membership', return_value={})
    @patch('postriff_phase2.radar.service.require')
    def test_explicit_server_zero_source_quote_needs_no_credits(self, *_):
        for mode in ('free', 'managed'):
            r, _, _, sources = self.radar(mode)
            sources.ceiling = lambda source: 0
            r.g.env['POSTRIFF_RADAR_CREDIT_BILLING'] = '1'
            r.book.issue = Mock(side_effect=AssertionError('Zero-price collection must not request paid credit funding.'))
            result = r.quote('workspace', 'token', {'mode': 'quick', 'query': 'piano', 'sources': ['exa'], 'useAi': False, 'requestKey': 'recording-zero-key'})
            self.assertEqual(result['status'], 'quoted'); r.book.issue.assert_not_called()

    @patch('postriff_phase2.radar.service._membership', return_value={})
    @patch('postriff_phase2.radar.service.require')
    def test_legacy_paid_quote_keeps_old_authority(self, *_):
        r, _, _, _ = self.radar('legacy')
        self.assertEqual(r.quote('workspace', 'token', {'mode': 'quick', 'query': 'piano', 'sources': ['exa'], 'requestKey': 'recording-legacy-key'})['status'], 'quoted')

    @patch('postriff_phase2.growth.history_import.metric_schedule.analytics_direct', return_value=True)
    @patch('postriff_phase2.growth.history_import.purge_pending', return_value=False)
    def test_history_worker_denied_before_credentials_or_remote_page(self, *_):
        for mode in ('free', 'managed'):
            with self.subTest(mode=mode):
                cur = Cursor(mode); oauth = SimpleNamespace(token_for_worker=Mock(return_value={'accessToken': 'synthetic'})); transport = Mock(return_value={'status': 200, 'body': {'data': []}})
                host = SimpleNamespace(billing=SimpleNamespace(pricing_v2_enabled=True), clock=lambda: 1_000_000)
                importer = history_import.HistoryImporter(lambda: Database(cur), oauth, transport=transport, hosted=host)
                importer._finish = Mock(); importer._store_page = Mock(return_value=0)
                result = importer.run_one({'workspaceId': 'workspace', 'connectionId': 'connection', 'provider': 'threads', 'createdAt': 1_000_000, 'cursor': None, 'pages': 0}, time.monotonic() + 10)
                self.assertEqual(result, 'cancelled'); oauth.token_for_worker.assert_not_called(); transport.assert_not_called()

    @patch('postriff_phase2.growth.history_import.metric_schedule.analytics_direct', return_value=True)
    @patch('postriff_phase2.growth.history_import.purge_pending', return_value=False)
    @patch('postriff_phase2.hosted.throttle')
    @patch('postriff_phase2.hosted._membership', return_value={})
    @patch('postriff_phase2.permissions.require')
    def test_history_request_does_not_enqueue_unpriced_v2_work(self, *_):
        for mode in ('free', 'managed'):
            with self.subTest(mode=mode):
                cur = Cursor(mode)
                @contextmanager
                def transaction(*args): yield cur, (1, {}), 'actor'
                oauth = SimpleNamespace(repository=SimpleNamespace(transaction=transaction))
                host = SimpleNamespace(billing=SimpleNamespace(pricing_v2_enabled=True), clock=lambda: 1_000_000)
                importer = history_import.HistoryImporter(lambda: Database(cur), oauth, transport=Mock(), hosted=host)
                importer._status = lambda *args: {'status': 'pending'}
                self.refusal(lambda: importer.request('workspace', 'session', 'connection', {'confirmed': True}))
                self.assertFalse(cur.writes)


if __name__ == '__main__': unittest.main()
