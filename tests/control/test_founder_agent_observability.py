"""Founder reliability: GET /reliability/agent (P0.7). No PostgreSQL: a reader stub answers the fixed statements with canned
rows. The projections and grants are proven in test_founder_agent_observability_pg.py; the writer in tests/test_agent_observability.py.
"""
from datetime import datetime, timezone
import json
import re
import types
import unittest
import uuid

import psycopg

from rafii_control import founder_agent_observability as fao, http, slices
from rafii_control.auth import ControlError
from rafii_control.store import MetricStatement

NOW = datetime(2026, 10, 10, 12, 0, 30, tzinfo=timezone.utc).timestamp()
PRINCIPAL = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read']}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}


def buckets(**at):
    values = [0] * 20
    for index, count in at.items():
        values[int(index[1:])] = count
    return values


AGENT_ROWS = [
    {'metric': 'agent.turn', 'label': 'manager:completed', 'events': 8, 'total': 80000.0, 'buckets': buckets(b8=6, b10=2)},
    {'metric': 'agent.turn', 'label': 'manager:failed', 'events': 2, 'total': 9000.0, 'buckets': buckets(b6=2)},
    {'metric': 'agent.turn', 'label': 'site_agent:completed', 'events': 5, 'total': 2500.0, 'buckets': buckets(b3=5)},
    {'metric': 'agent.turn.fallback', 'label': 'model_error', 'events': 2, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.tool', 'label': 'library_search:verified', 'events': 30, 'total': 3000.0, 'buckets': buckets(b1=30)},
    {'metric': 'agent.tool', 'label': 'draft_create:unverified', 'events': 1, 'total': 900.0, 'buckets': buckets(b4=1)},
    {'metric': 'agent.tool', 'label': 'draft_create:verified', 'events': 3, 'total': 2700.0, 'buckets': buckets(b4=3)},
    {'metric': 'agent.tool', 'label': 'youtube_analytics_summary:failed', 'events': 2, 'total': 100.0, 'buckets': buckets(b0=2)},
    {'metric': 'agent.tool', 'label': 'draft_get:blocked', 'events': 1, 'total': 1.0, 'buckets': buckets(b0=1)},
    {'metric': 'agent.tool.error', 'label': 'youtube_analytics_summary:youtube_revoked_oauth', 'events': 2, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.authz', 'label': 'legacy:deny:tool_forbidden', 'events': 1, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.authz', 'label': 'shadow:deny:category_off', 'events': 4, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.authz', 'label': 'enforce:allow:allowed', 'events': 40, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.approval', 'label': 'panel:applied', 'events': 3, 'total': 180000.0, 'buckets': buckets(b14=3)},
    {'metric': 'agent.approval', 'label': 'chat:dismissed', 'events': 1, 'total': 5000.0, 'buckets': buckets(b7=1)},
    {'metric': 'agent.provider_auth', 'label': 'youtube:revoked', 'events': 2, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.retry', 'label': 'tool_repeat', 'events': 3, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.recovery', 'label': 'tool_retry:recovered', 'events': 2, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.recovery', 'label': 'tool_retry:unrecovered', 'events': 1, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.recovery', 'label': 'stalled_turn:closed', 'events': 1, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.outcome', 'label': 'verified', 'events': 6, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.outcome', 'label': 'unverified', 'events': 1, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.outcome', 'label': 'no_change', 'events': 7, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.change', 'label': 'verified', 'events': 9, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.change', 'label': 'unverified', 'events': 1, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.turn.cost', 'label': 'manager', 'events': 8, 'total': 36000.0, 'buckets': buckets()},
    {'metric': 'agent.turn.cost', 'label': 'manager:unknown', 'events': 1, 'total': 0, 'buckets': buckets()},
    {'metric': 'agent.genui', 'label': 'eligible', 'events': 3, 'total': 0, 'buckets': buckets()},
]
CALL_ROWS = [{'feature': 'agent', 'workload': 'standard_reasoning', 'calls': 12, 'ok': 10, 'failed': 2, 'refused': 1, 'retries': 1, 'known_usd_micro': 54000, 'unknown_cost': 1},
             {'feature': 'image', 'workload': 'image_quality', 'calls': 2, 'ok': 2, 'failed': 0, 'refused': 0, 'retries': 0, 'known_usd_micro': 80000, 'unknown_cost': 0}]
RUN_ROWS = [{'kind': 'agent', 'status': 'completed', 'runs': 9, 'p50_seconds': '7.5', 'p95_seconds': '31.0'},
            {'kind': 'agent', 'status': 'failed', 'runs': 1, 'p50_seconds': '2', 'p95_seconds': '2'},
            {'kind': 'task', 'status': 'running', 'runs': 2, 'p50_seconds': '60', 'p95_seconds': '60'}]
ART_ROWS = [{'surface': 'panel', 'validation': 'accepted', 'generation': 'ready', 'reason': None, 'artifacts': 9},
            {'surface': 'panel', 'validation': 'rejected', 'generation': 'failed', 'reason': 'validation_failed', 'artifacts': 1}]
ATT_ROWS = [{'kind': 'generate', 'state': 'ready', 'reason': None, 'attempts': 9, 'provider_retries': 1},
            {'kind': 'repair', 'state': 'ready', 'reason': None, 'attempts': 1, 'provider_retries': 0},
            {'kind': 'generate', 'state': 'failed', 'reason': 'validation_failed', 'attempts': 1, 'provider_retries': 0}]


class Store:
    def __init__(self, missing=()):
        self.missing, self.statements = set(missing), []

    def metric_rows(self, statement, params, limit=1000):
        if not isinstance(statement, MetricStatement):
            raise AssertionError('fixed statements only')
        self.statements.append((statement.sql, list(params)))
        if any(view in statement.sql for view in self.missing):
            raise psycopg.errors.UndefinedTable('relation does not exist')
        if 'business_agent_metrics' in statement.sql:
            return [dict(earliest='2026-10-09T00:00:00+00:00', latest='2026-10-10T11:59:00+00:00')] if 'min(m.minute)' in statement.sql else AGENT_ROWS
        if 'business_ai_calls' in statement.sql:
            return CALL_ROWS
        if 'business_agent_runs' in statement.sql:
            return RUN_ROWS
        if 'business_genui_artifacts' in statement.sql:
            return ART_ROWS
        if 'business_genui_attempts' in statement.sql:
            return ATT_ROWS
        raise AssertionError('unexpected statement')


def app(store):
    return types.SimpleNamespace(queries=types.SimpleNamespace(store=store))


def request(window=None, mode='live'):
    return dict(method='GET', path='/reliability/agent', body={}, query={'window': [window]} if window else {}, match=(), mode=mode, now=NOW,
                requestId=str(uuid.uuid4()), environ={})


class SummaryTests(unittest.TestCase):
    def test_route_is_read_only_control_read_and_loaded_by_the_slice_registry(self):
        self.assertIn('founder_agent_observability', slices.SLICES)
        routes = [r for r in http.EXTENSION_ROUTES if r[3] == 'founder_agent_observability']
        self.assertEqual([(r[0], r[1].pattern, r[2], r[5]) for r in routes], [('GET', r'/reliability/agent', 'control.read', {})])
        self.assertEqual(http.ControlApplication._capability('/reliability/agent', 'GET'), 'control.read')
        with self.assertRaises(ControlError):
            http.ControlApplication._capability('/reliability/agent', 'POST')

    def test_summary_measures_every_section(self):
        store = Store()
        out = fao.summary(app(store), PRINCIPAL, request('24h'))
        self.assertEqual(out['_dataState'], 'measured')
        self.assertEqual(out['interval'], {'start': '2026-10-09T12:01:00Z', 'end': '2026-10-10T12:01:00Z', 'window': '24h'})
        agent = out['sections']['agent']
        self.assertEqual((agent['turns']['total'], agent['turns']['completed'], agent['turns']['failedOrError'], agent['turns']['successRate']), (15, 13, 2, 0.8667))
        manager = next(p for p in agent['turns']['byPath'] if p['path'] == 'manager')
        self.assertEqual(manager['statuses'], {'completed': 8, 'failed': 2})
        self.assertEqual(manager['latency']['samples'], 10)
        self.assertTrue(5000 < manager['latency']['p50Ms'] <= 7500)
        self.assertEqual(agent['turns']['fallbacks'], [{'reason': 'model_error', 'count': 2}])
        tools = agent['tools']
        self.assertEqual((tools['calls'], tools['errors'], tools['blocked'], tools['errorRate']), (37, 3, 1, 0.0811))
        self.assertEqual(tools['mostFailing'][0]['tool'], 'youtube_analytics_summary')
        perms = agent['permissions']
        self.assertEqual((perms['decisions'], perms['denials'], perms['shadowWouldDeny']), (45, 5, 4))
        self.assertEqual(perms['byReason'][0], {'mode': 'shadow', 'outcome': 'deny', 'reason': 'category_off', 'count': 4})
        panel = next(s for s in agent['approvals']['bySurface'] if s['surface'] == 'panel')
        self.assertEqual(panel['outcomes'], {'applied': 3})
        self.assertTrue(45000 < panel['wait']['p50Ms'] <= 60000)
        self.assertEqual(agent['providerAuthorization'], {'failures': 2, 'byProvider': [{'provider': 'youtube', 'reason': 'revoked', 'count': 2}]})
        self.assertEqual(agent['retries']['total'], 3)
        retry = next(r for r in agent['recoveries'] if r['kind'] == 'tool_retry')
        self.assertEqual((retry['results'], retry['successRate']), ({'recovered': 2, 'unrecovered': 1}, 0.6667))
        accuracy = agent['completionAccuracy']
        self.assertEqual((accuracy['verifiedShare'], accuracy['changesVerifiedShare']), (0.8571, 0.9))
        self.assertEqual(agent['cost'], {'byPath': [{'path': 'manager', 'turns': 8, 'usdMicro': 36000}], 'unknownCostTurns': 1})
        self.assertEqual(agent['collectingSince'], '2026-10-09T00:00:00+00:00')
        calls = out['sections']['providerCalls']
        self.assertEqual((calls['calls'], calls['authorizationRefusals'], calls['retries'], calls['knownUsdMicro'], calls['unknownCostCalls']), (14, 1, 1, 134000, 1))
        runs = out['sections']['runs']['byKind']
        self.assertEqual(runs[0], {'kind': 'agent', 'statuses': {'completed': 9, 'failed': 1}, 'p50Seconds': 7.5, 'p95Seconds': 31.0, 'successRate': 0.9})
        genui = out['sections']['genui']
        self.assertEqual(genui['artifacts']['acceptedShare'], 0.9)
        self.assertEqual(genui['artifacts']['rejectionReasons'], [{'reason': 'validation_failed', 'count': 1}])
        repair = next(a for a in genui['attempts'] if a['kind'] == 'repair')
        self.assertEqual(repair['readyShare'], 1.0)
        json.dumps(out, allow_nan=False)

    def test_every_statement_is_parameterised_over_allowlisted_views(self):
        store = Store()
        fao.summary(app(store), PRINCIPAL, request('7d'))
        views = set()
        for sql, params in store.statements:
            views.update(re.findall(r'rafii_control\.(\w+)', sql))
            self.assertNotIn('public.', sql, 'founder reads go through projections only')
            self.assertEqual(sql.count('%s'), len(params))
        self.assertEqual(views, {'business_agent_metrics', 'business_ai_calls', 'business_agent_runs', 'business_genui_artifacts',
                                 'business_genui_attempts', 'workspace_classifications'})

    def test_missing_projections_are_source_not_configured_and_never_zero(self):
        store = Store(missing={'business_agent_metrics', 'business_genui_artifacts', 'business_genui_attempts'})
        out = fao.summary(app(store), PRINCIPAL, request())
        self.assertEqual(out['sections']['agent'], {'dataState': 'source_not_configured', 'source': 'rafii_control.business_agent_metrics'})
        self.assertEqual(out['sections']['genui']['dataState'], 'source_not_configured')
        self.assertEqual(out['sections']['providerCalls']['dataState'], 'measured')
        self.assertEqual(out['_dataState'], 'partial')
        self.assertEqual(out['interval']['window'], '24h')

    def test_a_failing_source_is_unavailable_by_class_only(self):
        class Broken(Store):
            def metric_rows(self, statement, params, limit=1000):
                raise RuntimeError('PRIVATE dsn postgres://user:pass@host')
        out = fao.summary(app(Broken()), PRINCIPAL, request())
        self.assertEqual(out['_dataState'], 'unavailable')
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.assertEqual(out['sections']['agent'], {'dataState': 'unavailable', 'reason': 'source_error', 'errorClass': 'RuntimeError'})

    def test_empty_window_is_not_instrumented(self):
        class Empty(Store):
            def metric_rows(self, statement, params, limit=1000):
                return []
        out = fao.summary(app(Empty()), PRINCIPAL, request('1h'))
        self.assertEqual({k: v['dataState'] for k, v in out['sections'].items()},
                         {'agent': 'not_instrumented', 'providerCalls': 'not_instrumented', 'runs': 'not_instrumented', 'genui': 'not_instrumented'})

    def test_group_limit_is_partial_without_sampled_totals(self):
        class Many(Store):
            def metric_rows(self, statement, params, limit=1000):
                group_limit = fao.GROUP_LIMITS.get(statement.sql)
                if group_limit:
                    self.asserted_limit = limit
                    return [{'metric': 'agent.tool', 'label': f'tool_{i}:verified', 'events': 1} for i in range(group_limit + 1)]
                return []

        store = Many()
        out = fao.summary(app(store), PRINCIPAL, request())
        self.assertEqual(out['_dataState'], 'partial')
        for section, limit in (('agent', 1000), ('providerCalls', 200), ('runs', 100), ('genui', 200)):
            self.assertEqual(out['sections'][section], {'dataState': 'partial', 'reason': 'source_truncated',
                                                       'groupLimit': limit, 'totalsAvailable': False})
        self.assertEqual(store.asserted_limit, 201)

    def test_exact_group_limit_keeps_complete_totals(self):
        class Exact(Store):
            def metric_rows(self, statement, params, limit=1000):
                if statement.sql == fao.AGENT_SQL:
                    return [{'metric': 'agent.tool', 'label': f'tool_{i}:verified', 'events': 1} for i in range(fao.LIMIT)]
                return super().metric_rows(statement, params, limit)

        out = fao.summary(app(Exact()), PRINCIPAL, request())
        self.assertEqual(out['sections']['agent']['dataState'], 'measured')
        self.assertEqual(out['sections']['agent']['tools']['calls'], fao.LIMIT)

    def test_demo_is_not_simulated_and_window_is_validated(self):
        store = Store()
        out = fao.summary(app(store), PRINCIPAL, request(mode='demo'))
        self.assertEqual((out['mode'], out['reason'], out['_dataState'], out['sections']), ('demo', 'demo_not_simulated', 'not_applicable', {}))
        self.assertEqual(store.statements, [], 'Demo never reads Live')
        with self.assertRaises(ControlError) as raised:
            fao.summary(app(store), PRINCIPAL, request('30d'))
        self.assertEqual(raised.exception.status, 400)

    def test_percentiles_come_from_buckets_never_averages(self):
        self.assertEqual(fao.percentile(buckets(b0=1), 0.5), (25.0, False))
        self.assertEqual(fao.percentile(buckets(b19=4), 0.95), (3600000.0, True))
        self.assertEqual(fao.percentile([0] * 20, 0.5), (None, False))


if __name__ == '__main__':
    unittest.main()
