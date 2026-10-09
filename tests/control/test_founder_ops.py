"""Founder slice 8.D (CONTRACTS §8.D): reliability, operations and support metrics, source probes, cron stages and the
independent watchdog. No PostgreSQL: a reader stub answers each fixed statement with canned rows, and scripted consumer
connections answer the probes and stages. The PG round trip lives in test_founder_ops_pg.py.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import types
import unittest
from unittest import mock
import uuid

import psycopg

from rafii_control import demo_metrics, founder_cron, founder_sources, live_metrics, slices
from rafii_control import founder_metrics_ops as ops
from rafii_control.auth import ControlError
from rafii_control.demo_dataset import sample_data
from rafii_control.intelligence import ACTIVATED, PACK, Catalog, QueryService
from rafii_control.store import MetricStatement

ROOT = Path(__file__).resolve().parents[2]
TZ = 'America/Indiana/Indianapolis'
INTERVAL = dict(start='2026-09-24T04:00:00Z', end='2026-10-01T04:00:00Z', timeZone=TZ)
RECENT = dict(start='2026-10-01T11:00:00Z', end='2026-10-01T12:00:00Z', timeZone=TZ)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()
PRINCIPAL = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query']}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}
FULL = dict(earliest='2026-09-01T12:00:00+00:00', latest='2026-10-01T11:59:00+00:00')


def query(metric, group_by=(), filters=(), comparison='none', interval=INTERVAL):
    return dict(metricIds=[metric], interval=dict(interval), groupBy=list(group_by), filters=list(filters), comparison=comparison, limit=1000)


def where(dimension, *values):
    return dict(dimension=dimension, operator='in', values=list(values))


class OpsStore:
    """The reader stub: canned rows per statement id (coverage probes are '<metric>:coverage'), every statement recorded."""
    environment = 'local'

    def __init__(self):
        self.receipts, self.statements, self.sources = [], [], []
        self.rows, self.instrumented, self.missing = {}, set(), set()

    def read(self, kind, identifier=None):
        return list(self.sources) if kind == 'sources' else []

    def receipt(self, receipt):
        self.receipts.append(receipt)

    def metric_rows(self, statement, params, limit=1000):
        if not isinstance(statement, MetricStatement):
            raise AssertionError('statements must come from the registry')
        self.statements.append((statement.metric_id, statement.sql, list(params)))
        if any(view in statement.sql for view in self.missing):
            raise psycopg.errors.UndefinedTable('relation does not exist')
        if statement.metric_id == 'probe':
            return [dict(instrumented=any(view in statement.sql for view in self.instrumented))]
        aliases = re.findall(r'AS "([dm]_[a-zA-Z_]+)"', statement.sql)
        rows = [{**{alias: (0 if alias.startswith('m_') else None) for alias in aliases}, **row} for row in self.rows.get(statement.metric_id, [])]
        if len(rows) > limit:
            raise ControlError('BUDGET_EXCEEDED', 400)
        return rows

    def last(self, metric_id):
        return [entry for entry in self.statements if entry[0] == metric_id][-1]


class Base(unittest.TestCase):
    def setUp(self):
        slices.load()
        self.store = OpsStore()
        self.service = QueryService(self.store, Catalog(), clock=lambda: NOW)

    def run_query(self, metric_query, mode='live', **kwargs):
        return self.service.metric_query(metric_query, PRINCIPAL, str(uuid.uuid4()), mode=mode, **kwargs)

    def rows(self, metric_query):
        return self.run_query(metric_query)['rows']


class RegistrationTests(Base):
    def test_catalog_rows_are_complete_activated_extensions(self):
        rows = json.loads((PACK / 'catalogs/metrics.d/ops.json').read_text())
        self.assertEqual([row['id'] for row in rows], list(ops.LIVE_IDS))
        catalog = Catalog()
        fields = {'id', 'version', 'title', 'grain', 'unit', 'definition', 'source_contract', 'allowed_dimensions', 'query_template_ref', 'default_exclusions',
                  'data_state_required', 'currency_policy', 'zero_denominator', 'refresh_target', 'limitations', 'status', 'activation'}
        for row in rows:
            with self.subTest(metric=row['id']):
                self.assertEqual(set(row), fields)
                self.assertEqual(row['status'], ACTIVATED)
                self.assertTrue(catalog.activated(row['id']))
                self.assertEqual(set(row['activation']), {'definitionVersion', 'liveAdapter', 'demoAdapter', 'migration', 'snapshot', 'prd'})
                self.assertEqual(row['activation']['liveAdapter'], 'rafii_control.founder_metrics_ops')
                catalog.validate_query(query(row['id'], row['allowed_dimensions'][:3]))   # new dimension names are admitted by the schema
        burn = next(row for row in rows if row['id'] == 'slo_burn')
        self.assertIn('proposed 99.5% SLO, not approved', burn['title'])
        self.assertIn('not_collected', next(row for row in rows if row['id'] == 'support_aging')['definition'])
        # api_latency and slo_burn were proposed in metrics.json; the activated rows govern their ids, the proposed text stays.
        proposed = {row['id']: row for row in json.loads((PACK / 'catalogs/metrics.json').read_text())[:63]}
        self.assertEqual(proposed['slo_burn']['status'], 'proposed_definition_not_activated')
        self.assertEqual(catalog.metrics['slo_burn']['unit'], 'multiple')
        # Grain-sharing pairs the Operations page queries together.
        self.assertEqual(catalog.metrics['api_error_rate']['grain'], catalog.metrics['api_latency']['grain'])
        self.assertEqual(catalog.metrics['support_aging']['grain'], catalog.metrics['data_requests_backlog']['grain'])

    def test_live_demo_sources_and_stages_are_registered(self):
        self.assertIn('founder_metrics_ops', slices.SLICES)
        self.assertNotIn('founder_metrics_ops', slices.load())
        for metric_id in ops.LIVE_IDS:
            with self.subTest(metric=metric_id):
                self.assertTrue(live_metrics.known(metric_id))
                self.assertIn(live_metrics.METRIC_SOURCES[metric_id], founder_sources.SOURCE_IDS)
                self.assertIn(metric_id, demo_metrics.CUSTOM)
        self.assertEqual(live_metrics.METRIC_SOURCES['queue_health'], 'cron')
        self.assertIn('publish_by_provider', live_metrics.SPECS)
        self.assertLessEqual({'operational_snapshot', 'connection_health', 'reliability_purge'}, {name for name, _ in founder_cron.STAGES})
        with self.assertRaises(ValueError):
            live_metrics.register(custom={'api_latency': {'rows': ops.api_latency_rows}})

    def test_source_vocabulary(self):
        self.assertEqual(founder_sources.SOURCE_IDS, ('cron', 'database', 'control_database', 'control_reader', 'phone_provider', 'notifications',
                                                      'stripe_webhooks', 'email_provider', 'model_gateway', 'product_writer', 'ai_writer'))
        self.assertEqual(founder_sources.REQUIRED_SOURCES, ('cron', 'database', 'control_database'), 'no 8.D source pages on its own')
        self.assertEqual(founder_sources.EVENT_SOURCE_IDS, ('stripe_webhooks', 'email_provider', 'model_gateway'))
        self.assertIs(live_metrics.SOURCE_IDS, founder_sources.SOURCE_IDS)


class RequestMetricTests(Base):
    def test_unavailable_until_installed_and_collected(self):
        self.store.missing = {'business_request_metrics'}
        for metric_id in ('api_error_rate', 'api_latency'):
            row = self.rows(query(metric_id))[0]
            self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'source_not_configured'))
        self.store.missing = set()
        self.store.rows['api_error_rate:coverage'] = [dict(earliest=None, latest=None)]
        row = self.rows(query('api_error_rate'))[0]
        self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'not_instrumented'))
        # The interval ends before the first retained minute: nothing was collected for it, so no number, and the date it starts.
        self.store.rows['api_error_rate:coverage'] = [dict(earliest='2026-10-01T05:00:00+00:00', latest='2026-10-01T11:59:00+00:00')]
        row = self.rows(query('api_error_rate'))[0]
        self.assertEqual((row['value'], row['dataState'], row['reason'], row['collectingSince']), (None, 'unavailable', 'collecting_since', '2026-10-01T05:00:00+00:00'))
        self.assertEqual([entry[0] for entry in self.store.statements], ['api_error_rate:coverage', 'api_latency:coverage'] + ['api_error_rate:coverage'] * 2,
                         'no metric statement without coverage')

    def test_error_rate_ratio_coverage_and_collecting_since(self):
        self.store.rows['api_error_rate:coverage'] = [dict(earliest='2026-09-28T00:00:00+00:00', latest='2026-10-01T11:59:00+00:00')]
        self.store.rows['api_error_rate'] = [dict(requests='200', errors='3', client_errors='10', watermark='2026-10-01T03:59:00+00:00', sample_count='50')]
        row = self.rows(query('api_error_rate'))[0]
        self.assertEqual((row['value'], row['unit'], row['dataState'], row['reason'], row['collectingSince']), (0.015, 'ratio', 'partial', 'collecting_since', '2026-09-28T00:00:00+00:00'))
        self.assertEqual(row['coverage'], dict(known=200, unknown=0, numerator=3, denominator=200))
        self.assertEqual(row['measures'], {'requests': 200, 'serverErrors': 3, 'clientErrors': 10})
        self.store.rows['api_error_rate:coverage'] = [FULL]
        row = self.rows(query('api_error_rate'))[0]
        self.assertEqual((row['dataState'], row['reason'], row.get('collectingSince')), ('measured', None, None))
        # Older than the 30-day retention: partial because the purge removed the start of the interval.
        old = dict(start='2026-08-01T04:00:00Z', end='2026-10-01T04:00:00Z', timeZone=TZ)
        self.assertEqual(self.rows(query('api_error_rate', interval=old))[0]['reason'], 'retention_limited')

    def test_zero_requests_is_not_applicable_never_zero_percent(self):
        self.store.rows['api_error_rate:coverage'] = [FULL]
        self.store.rows['api_error_rate'] = [dict(requests=None, errors=0, client_errors=0, watermark=None, sample_count=0)]
        row = self.rows(query('api_error_rate'))[0]
        self.assertEqual((row['value'], row['dataState'], row['reason'], row['coverage']['denominator']), (None, 'not_applicable', 'no_requests', 0))
        self.store.rows['api_error_rate'] = []
        self.assertEqual(self.rows(query('api_error_rate', ['route'])), [])

    def test_statements_are_fixed_parameterised_half_open_and_bounded(self):
        self.store.rows['api_error_rate:coverage'] = [FULL]
        self.store.rows['api_error_rate'] = [dict(d_route='GET /api/health', d_hour='2026-09-30T10:00', requests=10, errors=1, client_errors=0, watermark='2026-09-30T14:59:00+00:00', sample_count=10)]
        rows = self.rows(query('api_error_rate', ['route', 'hour'], [where('route', "x' OR 1=1 --")]))
        self.assertEqual(rows[0]['dimensions'], {'route': 'GET /api/health', 'hour': '2026-09-30T10:00'})
        _, sql, params = self.store.last('api_error_rate')
        self.assertEqual(sql.count('%s'), len(params))
        self.assertEqual(params[:2], [INTERVAL['start'], INTERVAL['end']])
        self.assertIn('r.minute >= %s::timestamptz AND r.minute < %s::timestamptz', sql)
        self.assertIn(["x' OR 1=1 --"], params)
        self.assertNotIn('1=1', sql)
        self.assertIn(TZ, params)
        self.assertIn("date_trunc('hour', b.at AT TIME ZONE %s)", sql)
        self.assertEqual(params[-1], live_metrics.MAX_POINTS + 1)
        self.assertTrue(sql.startswith('WITH base AS (SELECT'))
        with self.assertRaises(ControlError):
            self.run_query(query('api_error_rate', ['hour'], comparison='previous_equal_elapsed'))
        with self.assertRaises(ControlError):
            self.run_query(query('api_error_rate', ['provider']))

    def test_lagging_writer_and_stale_database_source(self):
        self.store.rows['api_error_rate:coverage'] = [dict(FULL, latest='2026-10-01T11:20:00+00:00')]
        self.store.rows['api_error_rate'] = [dict(requests=10, errors=0, client_errors=0, watermark='2026-10-01T11:20:00+00:00', sample_count=10)]
        row = self.rows(query('api_error_rate', interval=RECENT))[0]
        self.assertEqual((row['dataState'], row['reason']), ('stale', 'request_metrics_lagging'))
        self.assertEqual(self.rows(query('api_error_rate'))[0]['dataState'], 'measured', 'a historical interval is not judged by today\'s lag')
        self.store.rows['api_error_rate:coverage'] = [FULL]
        self.store.sources = [dict(source_id='database', state='stale', watermark='2026-10-01T10:00:00+00:00', checked_at='2026-10-01T10:00:00+00:00', reason_code='lagging')]
        row = self.rows(query('api_error_rate', interval=RECENT))[0]
        self.assertEqual((row['dataState'], row['reason']), ('stale', 'source_stale'))

    def test_percentile_interpolates_inside_the_rank_bucket_and_is_never_an_average(self):
        buckets = [0] * 20
        buckets[0], buckets[5] = 50, 50
        self.assertEqual(ops.percentile(buckets, 0.5), (10.0, False))
        self.assertEqual(ops.percentile(buckets, 0.95), (145.0, False))
        self.assertEqual(ops.percentile([0] * 19 + [10], 0.95), (30000.0, True))
        self.assertEqual(ops.percentile([0] * 20, 0.5), (None, False))
        self.assertEqual(ops.percentile(None, 0.5), (None, False))
        fast, slow = [0] * 20, [0] * 20
        fast[1], fast[9], slow[12] = 95, 5, 100
        p_fast, p_slow = ops.percentile(fast, 0.95)[0], ops.percentile(slow, 0.95)[0]
        combined = ops.percentile([a + b for a, b in zip(fast, slow)], 0.95)[0]
        self.assertEqual((p_fast, p_slow, combined), (25.0, 1975.0, 1950.0))
        self.assertNotEqual(combined, (p_fast + p_slow) / 2)

    def test_latency_rows_carry_both_percentiles_and_flag_small_samples(self):
        self.store.rows['api_latency:coverage'] = [FULL]
        big, small = [0] * 20, [0] * 20
        big[3], small[6] = 40, 5
        self.store.rows['api_latency'] = [dict(d_route='GET /api/health', buckets=[str(value) for value in big], watermark='2026-10-01T03:59:00+00:00'),
                                          dict(d_route='POST /api/workspaces/:id/actions', buckets=small, watermark='2026-10-01T03:58:00+00:00')]
        rows = self.rows(query('api_latency', ['route']))
        self.assertEqual([(row['dimensions']['route'], row['dimensions']['percentile'], row['value'], row['dataState']) for row in rows],
                         [('GET /api/health', 'p50', 62.5, 'measured'), ('GET /api/health', 'p95', 73.8, 'measured'),
                          ('POST /api/workspaces/:id/actions', 'p50', 175.0, 'partial'), ('POST /api/workspaces/:id/actions', 'p95', 197.5, 'partial')])
        self.assertEqual((rows[2]['reason'], rows[2]['sampleCount'], rows[0]['unit'], rows[0]['measures']), ('small_sample', 5, 'milliseconds', {'requests': 40, 'openEnded': False}))
        _, sql, params = self.store.last('api_latency')
        self.assertIn('unnest(b.buckets) WITH ORDINALITY', sql)
        self.assertIn('array_agg(total ORDER BY i)', sql)
        self.assertNotIn('avg(', sql.lower())
        self.assertEqual(sql.count('%s'), len(params))
        self.assertEqual(params[-1], live_metrics.MAX_POINTS // 2 + 1)
        only = self.rows(query('api_latency', ['route'], [where('percentile', 'p95')]))
        self.assertEqual({row['dimensions']['percentile'] for row in only}, {'p95'})
        self.store.rows['api_latency'] = [dict(buckets=None, watermark=None)]
        empty = self.rows(query('api_latency'))
        self.assertEqual([(row['dimensions'], row['dataState']) for row in empty], [({'percentile': 'p50'}, 'not_applicable'), ({'percentile': 'p95'}, 'not_applicable')])


class OperationsMetricTests(Base):
    def test_queue_health_peaks_per_counter_with_the_latest_reading(self):
        self.store.rows['queue_health:coverage'] = [FULL]
        self.store.rows['queue_health'] = [dict(d_counter='queueDelayed', d_queue='publishing', peak='4', latest='1', latest_at='2026-10-01T03:59:00+00:00',
                                                watermark='2026-10-01T03:59:00+00:00', sample_count='1440')]
        row = self.rows(query('queue_health', ['queue']))[0]
        self.assertEqual((row['value'], row['dimensions'], row['measures']['latest'], row['measures']['snapshots']), (4, {'counter': 'queueDelayed', 'queue': 'publishing'}, 1, 1440))
        _, sql, params = self.store.last('queue_health')
        self.assertIn("WHEN 'queueDelayed' THEN 'publishing'", sql)
        self.assertIn("starts_with(k.key, 'sms.')", sql)
        self.assertIn('jsonb_each(s.counts)', sql)
        self.assertIn('GROUP BY "d_counter", "d_queue"', sql)
        self.assertEqual(sql.count('%s'), len(params))
        self.store.rows['queue_health:coverage'] = [dict(FULL, latest='2026-10-01T11:30:00+00:00')]
        self.assertEqual(self.rows(query('queue_health', interval=RECENT))[0]['reason'], 'snapshots_lagging')

    def test_connection_health_is_a_customer_snapshot_with_refresh_lag(self):
        self.store.rows['connection_health:coverage'] = [dict(earliest='2026-10-01T11:05:00+00:00', latest='2026-10-01T11:05:00+00:00')]
        self.store.rows['connection_health'] = [dict(d_provider='linkedin', d_capability='publish', d_state='expiring', value='3', workspaces='2',
                                                     watermark='2026-10-01T11:05:00+00:00', sample_count='3')]
        result = self.run_query(query('connection_health', ['provider', 'capability', 'state'], comparison='previous_equal_elapsed'))
        row = result['rows'][0]
        self.assertEqual((row['value'], row['measures'], row['dataState']), (3, {'workspaces': 2}, 'measured'))
        self.assertEqual(row['comparison']['dataState'], 'unavailable', 'a current projection has no history to compare')
        _, sql, params = self.store.last('connection_health')
        self.assertIn("c.kind IN ('internal','test','demo')", sql)
        self.assertEqual(params, [live_metrics.MAX_POINTS + 1], 'the interval does not filter a snapshot')
        self.store.rows['connection_health:coverage'] = [dict(earliest='2026-10-01T07:00:00+00:00', latest='2026-10-01T07:00:00+00:00')]
        row = self.rows(query('connection_health'))[0]
        self.assertEqual((row['dataState'], row['reason']), ('stale', 'projection_lagging'))
        self.store.rows['connection_health:coverage'] = [dict(earliest=None, latest=None)]
        self.assertEqual(self.rows(query('connection_health'))[0]['reason'], 'not_instrumented')

    def test_publish_by_provider_is_a_registry_statement_with_customer_exclusions(self):
        statement, params, group_by, _ = live_metrics.compose('publish_by_provider', query('publish_by_provider', ['window'], [where('provider', 'linkedin')]))
        self.assertEqual(group_by, ['provider', 'window'])
        self.assertIn("c.kind IN ('internal','test','demo')", statement.sql)
        self.assertEqual((params[:2], statement.sql.count('%s')), ([INTERVAL['start'], INTERVAL['end']], len(params)))
        self.store.instrumented = {'business_notification_events'}
        self.store.rows['publish_by_provider'] = [dict(d_provider='linkedin', value=0.8, known=9, unknown=1, numerator=8, denominator=10, watermark='2026-09-30T00:00:00+00:00',
                                                      sample_count=10, m_verified=8, m_failed=1, m_uncertain=1)]
        row = self.rows(query('publish_by_provider'))[0]
        self.assertEqual((row['value'], row['dataState'], row['reason'], row['measures']), (0.8, 'partial', 'uncertain_publish_outcomes', {'verified': 8, 'failed': 1, 'uncertain': 1}))
        self.store.rows['publish_by_provider'] = []
        self.store.instrumented = set()
        row = self.rows(query('publish_by_provider'))[0]
        self.assertEqual((row['value'], row['reason']), (None, 'not_instrumented'))

    def test_slo_burn_is_labelled_proposed_and_alerts_only_when_both_windows_burn(self):
        self.store.rows['slo_burn:coverage'] = [FULL]
        self.store.rows['slo_burn:api'] = [dict(total_5m=100, bad_5m=10, total_30m=600, bad_30m=6, total_1h=1200, bad_1h=120, total_6h=7200, bad_6h=36,
                                                watermark='2026-10-01T11:59:00+00:00')]
        rows = self.rows(query('slo_burn', interval=RECENT))
        api = {row['dimensions']['burn_window']: row for row in rows if row['dimensions']['slo'] == 'api_availability'}
        self.assertEqual({name: row['value'] for name, row in api.items()}, {'5m': 20.0, '30m': 2.0, '1h': 20.0, '6h': 1.0})
        self.assertEqual({name: row['measures']['alerting'] for name, row in api.items()}, {'5m': True, '30m': False, '1h': True, '6h': False})
        self.assertEqual({row['measures']['threshold'] for row in api.values()}, {14.4, 6.0})
        for row in api.values():
            self.assertEqual((row['dataState'], row['reason'], row['unit']), ('measured', 'proposed_slo_not_approved', 'multiple'))
            self.assertEqual((row['measures']['basis'], row['measures']['sloStatus'], row['measures']['label'], row['measures']['sloTarget']),
                             ('proposed_slo', 'proposed_not_approved', 'proposed SLO, not approved', 0.995))
        publish = [row for row in rows if row['dimensions']['slo'] == 'publish_success']
        self.assertEqual([(row['dataState'], row['reason']) for row in publish], [('unavailable', 'not_instrumented')])
        _, sql, params = self.store.last('slo_burn:api')
        self.assertEqual(sql.count('%s'), len(params))
        self.assertEqual((params[0], params[-2], params[-1]), ('2026-10-01T11:55:00Z', '2026-10-01T06:00:00Z', '2026-10-01T12:00:00Z'))
        self.assertIn("split_part(r.\"routePattern\", '/', 3) NOT IN ('cron','control')", sql)
        # Few events never page: under 20 is low_traffic and the pair stops alerting; no events is not_applicable.
        self.store.rows['slo_burn:api'] = [dict(total_5m=5, bad_5m=5, total_30m=0, bad_30m=0, total_1h=1200, bad_1h=120, total_6h=7200, bad_6h=36)]
        api = {row['dimensions']['burn_window']: row for row in self.rows(query('slo_burn', filters=[where('slo', 'api_availability')]))}
        self.assertEqual((api['5m']['dataState'], api['5m']['reason'], api['5m']['measures']['alerting']), ('partial', 'low_traffic', False))
        self.assertEqual((api['30m']['value'], api['30m']['dataState'], api['30m']['reason']), (None, 'not_applicable', 'no_events'))
        self.store.instrumented = {'business_notification_events'}
        self.store.rows['slo_burn:publish'] = [dict(total_5m=0, bad_5m=0, total_30m=40, bad_30m=2, total_1h=80, bad_1h=2, total_6h=400, bad_6h=4)]
        publish = self.rows(query('slo_burn', filters=[where('slo', 'publish_success'), where('burn_window', '30m', '6h')]))
        self.assertEqual([(row['dimensions']['burn_window'], row['value']) for row in publish], [('30m', 10.0), ('6h', 2.0)])
        _, sql, _ = self.store.last('slo_burn:publish')
        self.assertIn("c.kind IN ('internal','test','demo')", sql)
        # The request writer stopped 40 minutes ago: the API burn is stale, never a reassuring low number.
        self.store.rows['slo_burn:coverage'] = [dict(FULL, latest='2026-10-01T11:20:00+00:00')]
        api = self.rows(query('slo_burn', interval=RECENT, filters=[where('slo', 'api_availability'), where('burn_window', '1h')]))
        self.assertEqual([(row['dataState'], row['reason']) for row in api], [('stale', 'request_metrics_lagging')])

    def test_support_aging_bands_kinds_and_the_ticket_source_not_collected(self):
        self.store.rows['support_aging'] = [dict(d_kind='export', d_age_band='3d_to_7d', value='2', oldest='500000.5', watermark='2026-09-27T00:00:00+00:00', sample_count='2'),
                                            dict(d_kind='deletion', d_age_band='over_30d', value='1', oldest='3000000', watermark='2026-08-01T00:00:00+00:00', sample_count='1')]
        rows = self.rows(query('support_aging', ['kind', 'age_band']))
        self.assertEqual([(row['dimensions'], row['value'], row['dataState']) for row in rows],
                         [({'kind': 'export', 'age_band': '3d_to_7d'}, 2, 'measured'), ({'kind': 'deletion', 'age_band': 'over_30d'}, 1, 'measured')])
        self.assertEqual(rows[0]['measures'], {'oldestSeconds': 500000, 'ticketSource': 'not_collected'})
        _, sql, params = self.store.last('support_aging')
        self.assertEqual(params[0], '2026-10-01T12:00:00Z')
        self.assertIn("interval '30 days' THEN '14d_to_30d'", sql)
        self.assertIn("ELSE 'over_30d'", sql)
        self.assertIn("c.kind IN ('internal','test','demo')", sql)
        self.assertEqual(sql.count('%s'), len(params))
        # Grouping by source shows the ticket source as its own row: unavailable, not_collected (D7), never a zero.
        rows = self.rows(query('support_aging', ['source', 'kind']))
        self.assertEqual([(row['dimensions'], row['value'], row['dataState'], row['reason']) for row in rows][-1],
                         ({'kind': None, 'source': 'support_tickets'}, None, 'unavailable', 'not_collected'))
        self.assertEqual(rows[-1]['measures'], {'decision': 'D7'})
        self.assertEqual({row['dimensions']['source'] for row in rows[:-1]}, {'data_requests'})
        statements = len(self.store.statements)
        rows = self.rows(query('support_aging', filters=[where('source', 'support_tickets')]))
        self.assertEqual(([row['dimensions']['source'] for row in rows], len(self.store.statements)), (['support_tickets'], statements), 'no data-request statement')
        self.store.rows['support_aging'] = [dict(value=0, oldest=None, watermark=None, sample_count=0)]
        self.store.instrumented = {'business_data_requests_v2'}
        rows = self.rows(query('support_aging'))
        self.assertEqual([(row['dimensions'], row['value'], row['dataState']) for row in rows], [({}, 0, 'measured')])
        self.store.instrumented = set()
        self.assertEqual(self.rows(query('support_aging'))[0]['reason'], 'not_instrumented')

    def test_demo_parity_support_aging_from_the_demo_inbox_and_never_a_zero_elsewhere(self):
        data = sample_data()
        open_tickets = sum(row['status'] == 'open' for row in data['tickets'])
        result = self.run_query(query('support_aging', ['age_band']), mode='demo', demo_data=data)
        self.assertEqual(sum(row['value'] for row in result['rows']), open_tickets)
        self.assertTrue(all(row['fixture'] and row['dataState'] == 'measured' and row['measures']['ticketSource'] == 'not_collected' for row in result['rows']))
        self.assertEqual(result['executionState'], 'demo_dataset')
        by_source = self.run_query(query('support_aging', ['source']), mode='demo', demo_data=data)['rows']
        self.assertEqual([(row['dimensions'], row['value'], row['reason']) for row in by_source],
                         [({'source': 'data_requests'}, open_tickets, None), ({'source': 'support_tickets'}, None, 'not_collected')])
        for metric_id in ('api_error_rate', 'api_latency', 'queue_health', 'connection_health', 'publish_by_provider', 'slo_burn'):
            row = self.run_query(query(metric_id), mode='demo', demo_data=data)['rows'][0]
            self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'demo_not_simulated'))


class IncidentRouteTests(unittest.TestCase):
    """GET /incidents/{id}?mode= (control.read): the Operations timeline of one incident, Live or Demo, never a write."""
    def test_route_is_registered_read_only_beside_the_ack(self):
        from rafii_control import http
        slices.load()
        route, match = http.extension_route('/incidents/incident-demo-cost-abc-1', 'GET')
        self.assertEqual((route[2], route[3], route[4], match.groups()), ('control.read', 'founder_metrics_ops', 'incident_detail', ('incident-demo-cost-abc-1',)))
        self.assertEqual(http.extension_route('/incidents/abc/ack', 'GET'), (None, None))
        self.assertEqual(http.extension_route('/incidents/abc', 'POST'), (None, None))
        self.assertEqual(http.ControlApplication._capability('/incidents/abc', 'GET'), 'control.read')
        self.assertEqual(http.ControlApplication._capability('/incidents/abc/ack', 'POST'), 'incidents.ack')

    def test_demo_reads_the_demo_dataset_and_live_reads_the_session_store(self):
        data = {'incidents': [{'id': 'incident-demo-1', 'title': 'Simulated publishing outage', 'timeline': [{'id': 'e1', 'type': 'opened', 'at': '2026-10-01T12:00:00Z'}]}],
                'receipt': {'id': 'demo-receipt-1'}}

        def no_live():
            raise AssertionError('Demo never reads the live store')
        app = types.SimpleNamespace(queries=types.SimpleNamespace(demo_data=lambda principal: data), founder_store=no_live)
        result = ops.incident_detail(app, PRINCIPAL, dict(match=('incident-demo-1',), mode='demo'))
        self.assertEqual((result['incident']['id'], result['_dataState'], result['_receiptIds']), ('incident-demo-1', 'synthetic', ['demo-receipt-1']))
        with self.assertRaises(ControlError) as missing:
            ops.incident_detail(app, PRINCIPAL, dict(match=('incident-demo-404',), mode='demo'))
        self.assertEqual(missing.exception.status, 404)

        class Store:
            environment = 'local'

            def incident(self, incident_id):
                return {'id': incident_id, 'detector': 'cost_anomaly', 'scope': 'global', 'episode_key': 'k', 'severity': 'critical', 'state': 'open', 'opened_at': NOW_EPOCH - 60,
                        'acknowledged_at': None, 'resolved_at': None, 'evidence': {'todayUsdMicro': 9}, 'affected_count': 1, 'version': 2} if incident_id == 'i-1' else None

            def incident_events(self, incident_id):
                return [{'id': 'ev-1', 'kind': 'opened', 'at': NOW_EPOCH - 60, 'body': {'severity': 'critical'}}]
        live = types.SimpleNamespace(founder_store=Store)
        result = ops.incident_detail(live, PRINCIPAL, dict(match=('i-1',), mode='live'))
        self.assertEqual((result['incident']['version'], [event['kind'] for event in result['incident']['timeline']]), (2, ['opened']))
        with self.assertRaises(ControlError):
            ops.incident_detail(live, PRINCIPAL, dict(match=('i-404',), mode='live'))


# ---- probes ----------------------------------------------------------------------------------------------------------------
class ScriptedCursor:
    def __init__(self, db):
        self.db, self.result, self.rowcount = db, [], -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.db.statements.append((sql, params))
        if self.db.fail and self.db.fail[0] in sql:
            raise self.db.fail[1]
        for needle, answer in self.db.script:
            if needle in sql:
                self.result = list(answer(sql, params) if callable(answer) else answer)
                self.rowcount = self.db.deleted if sql.startswith('DELETE') else len(self.result)
                return
        self.result, self.rowcount = [], (self.db.deleted if sql.startswith('DELETE') else 0)

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class ScriptedDB:
    """A consumer connection: answers to_regclass from `tables`, other statements from (needle, rows) pairs."""
    def __init__(self, script=(), tables=(), deleted=0, fail=None):
        self.tables, self.deleted, self.fail = set(tables), deleted, fail
        self.script = [('to_regclass(%s)', self.regclass)] + list(script)
        self.statements, self.commits, self.savepoints = [], 0, 0

    def regclass(self, sql, params):
        present = params[0] in self.tables
        return [(present,)] if 'IS NOT NULL' in sql else [(params[0] if present else None,)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def cursor(self):
        return ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    @contextmanager
    def transaction(self):
        self.savepoints += 1
        yield


class ResendTransport:
    """Named like the mounted email transport; probes read the class name only."""


class ServerModelRuntime:
    """Named like the gateway runtime."""


class ReaderCon:
    def __init__(self, ok=1):
        self.ok = ok

    def execute(self, sql, params=None):
        return types.SimpleNamespace(fetchone=lambda: {'ok': self.ok})


class ReaderStore:
    def __init__(self, fail=False):
        self.fail, self.reads = fail, []

    @contextmanager
    def transaction(self, read=False):
        self.reads.append(read)
        if self.fail:
            raise ControlError('SOURCE_UNAVAILABLE', 503)
        yield ReaderCon()


class Probed:
    def __init__(self, store=None):
        self.store, self.written = store, {}

    def ping(self):
        return True

    def upsert_source_health(self, source_id, state, reason_code, checked_at, watermark=None):
        self.written[source_id] = (state, reason_code, watermark)


class ProbeTests(unittest.TestCase):
    def service(self, db, *, billing='stripe', transport=ResendTransport, runtime=ServerModelRuntime):
        return types.SimpleNamespace(connection_factory=lambda: db, billing=types.SimpleNamespace(provider=types.SimpleNamespace(id=billing)),
                                     mailer=types.SimpleNamespace(transport=transport()), ideas=types.SimpleNamespace(runtimes=[runtime()]),
                                     phone=None, notifications=None)

    def test_probe_writes_every_source_with_event_recency_watermarks(self):
        db = ScriptedDB([('pr_billing_events WHERE', [(1790000000.0,)]), ('pr_notification_provider_events WHERE', [(None,)]), ('pr_usage_ledger WHERE', [(1789990000.0,)])],
                        tables={'public.pr_billing_events', 'public.pr_notification_provider_events', 'public.pr_usage_ledger'})
        fstore = Probed(ReaderStore())
        written = founder_cron.probe(fstore, self.service(db), {}, NOW_EPOCH)
        self.assertEqual(set(written), set(founder_sources.SOURCE_IDS))
        self.assertEqual(fstore.written['stripe_webhooks'], ('measured', 'qualified', 1790000000.0))
        self.assertEqual(fstore.written['email_provider'], ('partial', 'lagging', None), 'mounted, but no good event recorded yet')
        self.assertEqual(fstore.written['model_gateway'], ('measured', 'qualified', 1789990000.0))
        self.assertEqual(fstore.written['control_reader'], ('measured', 'qualified', NOW_EPOCH))
        self.assertEqual(fstore.written['database'], ('measured', 'qualified', NOW_EPOCH))
        self.assertEqual(fstore.written['phone_provider'], ('not_applicable', 'not_configured', None))
        self.assertEqual(fstore.store.reads, [True], 'the reader probe runs as the read-only reader role')
        self.assertEqual(db.savepoints, 5, 'independent event and writer probes retain their own savepoints')
        self.assertEqual(fstore.written['product_writer'], ('partial', 'not_configured', None))
        self.assertEqual(fstore.written['ai_writer'], ('partial', 'not_configured', None))
        self.assertTrue(all('payload' not in sql for sql, _ in db.statements))

    def test_unmounted_missing_and_failing_event_sources(self):
        db = ScriptedDB([('pr_billing_events WHERE', [(1790000000.0,)])], tables={'public.pr_billing_events', 'public.pr_usage_ledger'},
                        fail=('pr_usage_ledger WHERE', psycopg.errors.QueryCanceled('statement timeout')))
        fstore = Probed()
        founder_cron.probe(fstore, self.service(db, billing='disabled', transport=object, runtime=object), {}, NOW_EPOCH)
        self.assertEqual(fstore.written['stripe_webhooks'], ('not_applicable', 'not_configured', 1790000000.0), 'unmounted keeps its last event')
        self.assertEqual(fstore.written['email_provider'], ('not_applicable', 'not_configured', None), 'table not installed')
        self.assertEqual(fstore.written['model_gateway'], ('unavailable', 'provider_unavailable', None))
        self.assertEqual(fstore.written['control_reader'], ('unavailable', 'not_configured', None))
        self.assertEqual(founder_sources.event_state(None, None), ('partial', 'lagging', None))
        # The consumer database itself unreachable: every consumer-side source is unavailable, the probe still writes all ids.
        fstore = Probed(ReaderStore(fail=True))
        founder_cron.probe(fstore, object(), {}, NOW_EPOCH)
        self.assertEqual(set(fstore.written), set(founder_sources.SOURCE_IDS))
        self.assertEqual({fstore.written[name][0] for name in ('database', 'stripe_webhooks', 'email_provider', 'model_gateway', 'control_reader')}, {'unavailable'})

    def test_configured_reads_mounted_objects_never_credentials(self):
        self.assertIsNone(founder_sources.configured('stripe_webhooks', object()))
        self.assertFalse(founder_sources.configured('email_provider', types.SimpleNamespace(mailer=types.SimpleNamespace(transport=object()))))
        self.assertIsNone(founder_sources.configured('model_gateway', types.SimpleNamespace(ideas=types.SimpleNamespace(runtime=object()))))
        self.assertTrue(founder_sources.configured('model_gateway', types.SimpleNamespace(ideas=types.SimpleNamespace(runtime=ServerModelRuntime()))))


# ---- watchdog --------------------------------------------------------------------------------------------------------------
class WatchConnection:
    def __init__(self, rows, *, privileged=False, writable=False, fail=None):
        self.rows, self.privileged, self.writable, self.fail, self.sql = rows, privileged, writable, fail, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if self.fail:
            raise self.fail
        rows = [(self.privileged,)] if 'rolsuper' in sql else [(self.writable,)] if 'has_table_privilege' in sql else self.rows if 'FROM rafii_control.source_health' in sql else [(None,)]
        return types.SimpleNamespace(fetchone=lambda: rows[0] if rows else None, fetchall=lambda: list(rows))


def heartbeat(age, state='measured'):
    return [('cron', state, 'qualified', NOW_EPOCH - age, NOW_EPOCH - age), ('database', 'measured', 'qualified', NOW_EPOCH - 30, NOW_EPOCH - 30)]


class WatchdogTests(unittest.TestCase):
    def main(self, connection=None, **environ):
        out = []
        code = founder_sources.watchdog_main({'RAFII_WATCHDOG_DSN': 'postgresql://watchdog:secret@db.invalid/postgres', **environ},
                                             connect=(lambda: connection) if connection else None, clock=lambda: NOW_EPOCH, out=out.append)
        return code, out

    def test_not_configured_passes_with_a_notice(self):
        out = []
        self.assertEqual(founder_sources.watchdog_main({}, out=out.append), 0)
        self.assertTrue(out[0].startswith('::notice title=Founder watchdog not configured::'))
        self.assertEqual(founder_sources.watchdog_main({'RAFII_WATCHDOG_DSN': '  '}, out=out.append), 0)

    def test_default_connector_uses_bundled_supabase_root_for_verify_full(self):
        connection = WatchConnection(heartbeat(30))
        dsn = 'host=pooler.example dbname=postgres user=watchdog password=secret sslmode=verify-full'
        from rafii_control import store
        with mock.patch('psycopg.connect', return_value=connection) as connect:
            rows = founder_sources.read_source_health(dsn, 'production')
        self.assertEqual(rows[0]['source_id'], 'cron')
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs.get('sslrootcert'), str(store.SUPABASE_ROOT))
        self.assertEqual(kwargs.get('application_name'), 'rafii-founder-watchdog')
        self.assertNotIn('secret', repr(kwargs))

    def test_current_heartbeat_passes_through_the_read_only_watchdog_role(self):
        connection = WatchConnection(heartbeat(120))
        code, out = self.main(connection)
        self.assertEqual(code, 0)
        statements = [sql for sql, _ in connection.sql]
        self.assertEqual(statements[0], 'SET TRANSACTION READ ONLY')
        self.assertIn('SET LOCAL ROLE rafii_control_watchdog', statements)
        self.assertIn(("SELECT set_config('rafii_control.environment',%s,true)", ('production',)), connection.sql)
        self.assertTrue(out[-1].startswith('::notice title=Founder cron heartbeat (production)::'))
        self.assertIn('cron: measured (qualified), checked 120 s ago', out)
        self.assertNotIn('secret', ' '.join(out))

    def test_stale_unmeasured_missing_privileged_or_unreadable_fails_loudly(self):
        for name, connection, message in (
                ('stale', WatchConnection(heartbeat(601)), 'The cron heartbeat is 601 s old (limit 600 s).'),
                ('unmeasured', WatchConnection(heartbeat(30, 'unavailable')), 'The cron probe is unavailable (qualified), not measured.'),
                ('missing', WatchConnection(heartbeat(30)[1:]), 'No cron heartbeat row is recorded for this environment.'),
                ('privileged', WatchConnection(heartbeat(30), privileged=True), 'Use the dedicated read-only watchdog login, not a privileged role.'),
                ('writable', WatchConnection(heartbeat(30), writable=True), 'The watchdog role can write source_health; it must be SELECT-only.'),
                ('unreadable', WatchConnection([], fail=psycopg.OperationalError('connection to server at "db.invalid" (password=secret) failed')), 'OperationalError')):
            with self.subTest(name):
                code, out = self.main(connection)
                self.assertEqual(code, 1)
                self.assertTrue(any(line.startswith('::error') and line.endswith(message) for line in out), out)
                self.assertNotIn('secret', ' '.join(out))
        code, out = self.main(WatchConnection(heartbeat(30)), RAFII_WATCHDOG_ENVIRONMENT='prod')
        self.assertEqual((code, out[0].startswith('::error title=Founder watchdog misconfigured::')), (1, True))

    def test_verdict_and_step_summary(self):
        ok, problems, lines = founder_sources.watchdog_verdict([{'source_id': 'cron', 'state': 'measured', 'reason_code': 'qualified', 'checked_at': NOW_EPOCH - 10}], NOW_EPOCH)
        self.assertEqual((ok, problems, lines), (True, [], ['cron: measured (qualified), checked 10 s ago']))
        self.assertFalse(founder_sources.watchdog_verdict([{'source_id': 'cron', 'state': 'measured', 'checked_at': None}], NOW_EPOCH)[0])
        with mock.patch('builtins.open', mock.mock_open()) as opened:
            self.main(WatchConnection(heartbeat(30)), GITHUB_STEP_SUMMARY='/tmp/summary.md')
        written = ''.join(call.args[0] for call in opened().write.call_args_list)
        self.assertIn('## Founder watchdog (production): heartbeat current', written)

    def test_workflow_runs_every_ten_minutes_with_the_secret_only(self):
        workflow = (ROOT / '.github/workflows/founder-watchdog.yml').read_text()
        self.assertIn("- cron: '*/10 * * * *'", workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('permissions:\n  contents: read', workflow)
        self.assertIn('RAFII_WATCHDOG_DSN: ${{ secrets.RAFII_WATCHDOG_DSN }}', workflow)
        self.assertNotIn('persist-credentials: false', workflow)
        self.assertIn('from rafii_control.founder_sources import watchdog_main', workflow)
        self.assertEqual(workflow.count('secrets.'), 1)
        self.assertNotIn('vercel', workflow.lower().replace('vercel sso', ''))


# ---- cron stages -----------------------------------------------------------------------------------------------------------
def local_epoch(text):
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(TZ)).timestamp()


class StageTests(unittest.TestCase):
    def setUp(self):
        ops.PAUSED.clear()
        ops.LOGGED.clear()
        self.addCleanup(ops.PAUSED.clear)
        self.addCleanup(ops.LOGGED.clear)

    def test_operational_snapshot_persists_the_cron_snapshot_counters_only(self):
        db = ScriptedDB(tables={'public.pr_operational_snapshots'})
        snapshot = {'status': 'attention', 'observedAt': NOW_EPOCH - 5, 'notificationDelivery': 'rafii_v2',
                    'counts': {'queueDelayed': 2, 'modelStuck': 0, 'weird': True, 'negative': -1, 'bad key!': 3, 'fraction': 1.5, 'text': 'x'},
                    'sms': {'backlogOver10m': 1}}
        service = types.SimpleNamespace(connection_factory=lambda: db, last_operational_snapshot=snapshot)
        result = ops.operational_snapshot_stage(None, service, {}, NOW_EPOCH)
        self.assertEqual(result, {'status': 'ok', 'minute': int((NOW_EPOCH - 5) // 60) * 60, 'counters': 3, 'source': 'cron_result'})
        sql, params = next((sql, params) for sql, params in db.statements if sql.startswith('INSERT INTO public.pr_operational_snapshots'))
        self.assertIn('ON CONFLICT (minute) DO UPDATE', sql)
        self.assertEqual(json.loads(params[4]), {'modelStuck': 0, 'queueDelayed': 2, 'sms.backlogOver10m': 1})
        self.assertEqual(params[2:4], ('attention', 'rafii_v2'))
        self.assertEqual(db.commits, 1)
        computed = {'status': 'ok', 'observedAt': NOW_EPOCH, 'counts': {'queueDelayed': 0}, 'sms': {}, 'notificationDelivery': 'not_configured'}
        with mock.patch('postriff_phase2.operational_signals.snapshot', return_value=computed) as compute:
            stale = dict(snapshot, observedAt=NOW_EPOCH - 600)
            result = ops.operational_snapshot_stage(None, types.SimpleNamespace(connection_factory=lambda: db, last_operational_snapshot=stale), {}, NOW_EPOCH)
        self.assertEqual((result['source'], result['counters']), ('computed', 1))
        compute.assert_called_once()

    def test_projection_classifies_with_the_customer_connection_state(self):
        from postriff_phase2.channels import connection_state
        now, day = NOW_EPOCH, 86400
        channels = [('w1', 'c-ok', 'LinkedIn', True, False, True, True, now + 30 * day, 2, True, now - 100),
                    ('w1', 'c-soon', 'X', True, False, True, True, now + 3 * day, 1, False, None),
                    ('w2', 'c-expired', 'Google Business Profile', True, False, True, True, now - 10, 1, True, None),
                    ('w2', 'c-revoked', 'Threads', True, True, True, True, now + 99 * day, 1, True, None),
                    ('w3', 'c-scopes', 'Bluesky', True, False, True, True, now + 99 * day, 0, False, None),
                    ('w3', 'c-unverified', 'Mastodon', True, False, False, True, now + 99 * day, 1, False, None),
                    ('w3', 'c-off', 'Reddit', False, False, True, True, now + 99 * day, 1, True, None),
                    ('w3', 'bad id!', 'Reddit', True, False, True, True, now + 99 * day, 1, True, None)]
        levels = {('w1', 'c-ok'): {'identity': 'Direct', 'publish': 'Direct', 'bogus': 'Direct'}, ('w1', 'c-soon'): {'publish': 'Weird'}}
        rows = ops.project_connections(channels, levels, now, connection_state)
        self.assertEqual({key: (row[3], row[4], row[5], row[6]) for key, row in rows.items()}, {
            ('w1', 'c-ok', 'identity'): ('linkedin', 'Direct', 'ok', 'publish_verified'),
            ('w1', 'c-ok', 'publish'): ('linkedin', 'Direct', 'ok', 'publish_verified'),
            ('w1', 'c-soon', 'publish'): ('x', 'unknown', 'expiring', 'read_verified'),
            ('w2', 'c-expired', 'identity'): ('google_business_profile', 'unknown', 'expired', 'token_expired'),
            ('w2', 'c-revoked', 'identity'): ('threads', 'unknown', 'blocked', 'reauthorization_required'),
            ('w3', 'c-scopes', 'identity'): ('bluesky', 'unknown', 'blocked', 'scope_missing'),
            ('w3', 'c-unverified', 'identity'): ('mastodon', 'unknown', 'blocked', 'identity_known')})
        self.assertEqual(rows[('w1', 'c-ok', 'identity')][8], now - 100)

    def test_projection_overlays_youtube_vault_facts_like_the_channels_card(self):
        """An expired hourly access token with a working refresh grant is a connected channel, not an expired one; a retained
        but disabled refresh grant needs new consent (client_binding_missing -> blocked). Without vault facts nothing changes."""
        from postriff_phase2.channels import connection_state
        now = NOW_EPOCH
        channels = [('w1', 'yt-refresh', 'YouTube', True, False, True, True, now - 60, 3, False, None),
                    ('w1', 'yt-binding', 'YouTube', True, False, True, True, now - 60, 3, False, None),
                    ('w2', 'yt-none', 'YouTube', True, False, True, True, now - 60, 3, False, None),
                    ('w2', 'li', 'LinkedIn', True, False, True, True, now - 60, 3, False, None)]
        status = {('w1', 'yt-refresh'): {'refreshSupported': True, 'refreshBindingRequired': False, 'accessTokenExpiresAt': now - 60, 'revoked': False},
                  ('w1', 'yt-binding'): {'refreshSupported': False, 'refreshBindingRequired': True, 'accessTokenExpiresAt': now - 60, 'revoked': False}}
        rows = ops.project_connections(channels, {}, now, connection_state, status)
        got = {key[1]: (row[5], row[6]) for key, row in rows.items()}
        self.assertEqual(got, {'yt-refresh': ('ok', 'read_verified'), 'yt-binding': ('blocked', 'client_binding_missing'),
                               'yt-none': ('expired', 'token_expired'), 'li': ('expired', 'token_expired')})
        revoked = ops.project_connections([('w3', 'yt-revoked', 'YouTube', True, False, True, True, now + 3600, 3, False, None)], {}, now, connection_state,
                                          {('w3', 'yt-revoked'): {'refreshSupported': True, 'refreshBindingRequired': False, 'accessTokenExpiresAt': now + 3600, 'revoked': True}})
        self.assertEqual([(r[5], r[6]) for r in revoked.values()], [('blocked', 'reauthorization_required')], 'a vault-revoked grant needs reauthorization')
        soon = now + 2 * 86400
        near = ops.project_connections([('w4', 'yt-r', 'YouTube', True, False, True, True, soon, 3, False, None),
                                        ('w4', 'yt-n', 'YouTube', True, False, True, True, now + 30 * 86400, 3, False, None)], {}, now, connection_state,
                                       {('w4', 'yt-r'): {'refreshSupported': True, 'refreshBindingRequired': False, 'accessTokenExpiresAt': soon, 'revoked': False},
                                        ('w4', 'yt-n'): {'refreshSupported': False, 'refreshBindingRequired': False, 'accessTokenExpiresAt': soon, 'revoked': False}})
        self.assertEqual({k[1]: (r[5], r[7]) for k, r in near.items()}, {'yt-r': ('ok', soon), 'yt-n': ('expiring', soon)},
                         'refreshable grants never read expiring; a non-refreshable one uses the vault deadline, not stale channel JSON')
        legacy = ops.project_connections(channels, {}, now, connection_state)
        self.assertEqual({key[1]: row[5] for key, row in legacy.items()}, {'yt-refresh': 'expired', 'yt-binding': 'expired', 'yt-none': 'expired', 'li': 'expired'})

    def test_youtube_overlay_failure_never_aborts_the_refresh(self):
        """The optional vault overlay runs in a savepoint: a privilege error rolls back to it and the refresh still commits
        with the plain channel classification; on success the overlay reaches the projection."""
        now = local_epoch('2026-10-01T08:05:30')
        wid = '11111111-1111-1111-1111-111111111111'
        channels = [(wid, 'yt', 'YouTube', True, False, True, True, now - 60, 3, False, None)]
        script = [('max(refreshed_at)', [(None,)]), ('pg_try_advisory_xact_lock', [(True,)]), ('FROM public.pr_workspaces w CROSS JOIN LATERAL', channels),
                  ('FROM public.pr_encrypted_credentials', [(wid, 'yt', True, True, now - 60, False)])]
        tables = {'public.pr_connection_health', 'public.pr_encrypted_credentials'}
        failing = ScriptedDB(script, tables=tables, fail=('FROM public.pr_encrypted_credentials', psycopg.errors.InsufficientPrivilege('denied')))
        result = ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: failing), {}, now)
        self.assertEqual((result['status'], result['rows'], failing.commits), ('ok', 1, 1))
        self.assertTrue(any(sql == 'ROLLBACK TO SAVEPOINT youtube_overlay' for sql, _ in failing.statements))
        self.assertEqual(result['youtubeOverlay'], 'unavailable', 'the fallback is reported, not silent')
        upsert = next(params for sql, params in failing.statements if sql.startswith('INSERT INTO public.pr_connection_health'))
        self.assertEqual(upsert[6], ['expired'], 'without vault facts the classification is the previous one')
        working = ScriptedDB(script, tables=tables)
        ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: working), {}, now)
        upsert = next(params for sql, params in working.statements if sql.startswith('INSERT INTO public.pr_connection_health'))
        self.assertEqual((upsert[6], upsert[7]), (['ok'], ['read_verified']), 'a refreshable YouTube grant is not an expired connection')
        self.assertTrue(any(sql == 'RELEASE SAVEPOINT youtube_overlay' for sql, _ in working.statements))
        self.assertEqual(ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: ScriptedDB(script, tables=tables)), {}, now)['youtubeOverlay'], 'applied')

    def test_connection_health_refreshes_hourly_and_removes_vanished_connections(self):
        now = local_epoch('2026-10-01T08:05:30')
        channels = [('11111111-1111-1111-1111-111111111111', 'c-ok', 'LinkedIn', True, False, True, True, now + 30 * 86400, 2, True, now - 100)]

        def db(latest=None, lock=True):
            return ScriptedDB([('max(refreshed_at)', [(latest,)]), ('pg_try_advisory_xact_lock', [(lock,)]), ('FROM public.pr_workspaces w CROSS JOIN LATERAL', channels),
                               ('FROM public.pr_channel_capabilities', [('11111111-1111-1111-1111-111111111111', 'c-ok', 'publish', 'Direct')])],
                              tables={'public.pr_connection_health', 'public.pr_channel_capabilities'}, deleted=2)
        fresh = db()
        result = ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: fresh), {}, now)
        self.assertEqual(result, {'status': 'ok', 'connections': 1, 'rows': 1, 'removed': 2, 'truncated': False, 'youtubeOverlay': 'not_needed'})
        sql, params = next((sql, params) for sql, params in fresh.statements if sql.startswith('INSERT INTO public.pr_connection_health'))
        self.assertEqual(params[0], now)
        self.assertEqual([column[0] for column in params[1:]], ['11111111-1111-1111-1111-111111111111', 'c-ok', 'publish', 'linkedin', 'Direct', 'ok', 'publish_verified',
                                                               now + 30 * 86400, now - 100])
        self.assertIn(('DELETE FROM public.pr_connection_health WHERE refreshed_at < to_timestamp(%s)', (now,)), fresh.statements)
        self.assertIn(('SET LOCAL statement_timeout = 20000', None), fresh.statements)
        self.assertEqual(fresh.commits, 1)
        recent = db(latest=now - 60)
        self.assertEqual(ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: recent), {}, now), {'status': 'skipped', 'reason': 'not_due'})
        empty = db()
        self.assertEqual(ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: empty), {}, now + 15 * 60)['reason'], 'not_due',
                         'an empty projection waits for the hourly window instead of scanning every minute')
        busy = db(lock=False)
        self.assertEqual(ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=lambda: busy), {}, now)['reason'], 'refresh_in_progress')

    def test_purge_runs_daily_at_three_with_retention_cutoffs(self):
        at = local_epoch('2026-10-01T03:04:00')
        db = ScriptedDB(tables={'public.pr_request_metrics', 'public.pr_operational_snapshots', 'public.pr_connection_health'}, deleted=5)
        result = ops.reliability_purge_stage(None, types.SimpleNamespace(connection_factory=lambda: db), {}, at)
        self.assertEqual(result, {'status': 'ok', 'deleted': {'pr_request_metrics': 5, 'pr_operational_snapshots': 5, 'pr_connection_health': 5}})
        deletes = [(sql, params) for sql, params in db.statements if sql.startswith('DELETE')]
        self.assertEqual(deletes, [('DELETE FROM public.pr_request_metrics WHERE minute < to_timestamp(%s)', (at - 30 * 86400,)),
                                   ('DELETE FROM public.pr_operational_snapshots WHERE minute < to_timestamp(%s)', (at - 30 * 86400,)),
                                   ('DELETE FROM public.pr_connection_health WHERE refreshed_at < to_timestamp(%s)', (at - 7 * 86400,))])
        self.assertEqual(ops.reliability_purge_stage(None, types.SimpleNamespace(connection_factory=lambda: db), {}, local_epoch('2026-10-01T03:10:00')),
                         {'status': 'skipped', 'reason': 'not_due'})
        partial = ScriptedDB(tables={'public.pr_request_metrics'}, deleted=1)
        self.assertEqual(ops.reliability_purge_stage(None, types.SimpleNamespace(connection_factory=lambda: partial), {}, at)['deleted'],
                         {'pr_request_metrics': 1, 'pr_operational_snapshots': 'table_missing', 'pr_connection_health': 'table_missing'})

    def test_stages_pause_when_not_installed_log_once_and_never_raise(self):
        purge_at = local_epoch('2026-10-01T03:01:00')
        service = types.SimpleNamespace(connection_factory=lambda: ScriptedDB())
        with self.assertLogs('rafii_control.founder_ops', level='WARNING') as logs:
            first = ops.operational_snapshot_stage(None, service, {}, purge_at)
            second = ops.operational_snapshot_stage(None, service, {}, purge_at + 60)
            health = ops.connection_health_stage(None, service, {}, purge_at)
            purge = ops.reliability_purge_stage(None, service, {}, purge_at)
        self.assertEqual(first, {'status': 'unavailable', 'reason': 'not_installed', 'cause': 'table_missing'})
        self.assertEqual(second, {'status': 'skipped', 'reason': 'not_installed'})
        self.assertEqual((health['reason'], purge['reason']), ('not_installed', 'not_installed'))
        self.assertEqual([json.loads(record.getMessage())['stage'] for record in logs.records], ['operational_snapshot', 'connection_health', 'reliability_purge'])
        with self.assertNoLogs('rafii_control.founder_ops', level='WARNING'):
            again = ops.operational_snapshot_stage(None, service, {}, purge_at + ops.NOT_INSTALLED_PAUSE + 1)
        self.assertEqual(again['reason'], 'not_installed', 'tried again after ten minutes, logged only once per process')
        ops.PAUSED.clear()
        raising = ScriptedDB(tables={'public.pr_operational_snapshots'}, fail=('INSERT INTO public.pr_operational_snapshots', psycopg.errors.UndefinedColumn('no column')))
        snapshot = {'status': 'ok', 'observedAt': NOW_EPOCH, 'counts': {}}
        result = ops.operational_snapshot_stage(None, types.SimpleNamespace(connection_factory=lambda: raising, last_operational_snapshot=snapshot), {}, NOW_EPOCH)
        self.assertEqual(result, {'status': 'unavailable', 'reason': 'not_installed', 'cause': 'UndefinedColumn'})
        ops.PAUSED.clear()
        broken = ScriptedDB(tables={'public.pr_operational_snapshots'}, fail=('INSERT INTO', RuntimeError('postgres://secret')))
        result = ops.operational_snapshot_stage(None, types.SimpleNamespace(connection_factory=lambda: broken, last_operational_snapshot=snapshot), {}, NOW_EPOCH)
        self.assertEqual(result, {'status': 'unavailable', 'error': 'RuntimeError'})
        for stage in (ops.operational_snapshot_stage, ops.connection_health_stage):
            self.assertEqual(stage(None, object(), {}, NOW_EPOCH), {'status': 'unavailable', 'reason': 'consumer_database_not_configured'})

    def test_registered_stages_run_inside_the_founder_tick_without_breaking_it(self):
        class Store:
            environment = 'local'

            def founder_operators(self):
                return []
        with mock.patch.object(founder_cron, 'probe', return_value={}), mock.patch.object(founder_cron, 'subscription_snapshot', return_value={}), \
             mock.patch.object(founder_cron, 'incidents_stage', return_value={}), mock.patch.object(founder_cron, 'schedules_stage', return_value={}), \
             mock.patch.object(founder_cron, 'reconcile_stage', return_value={}):
            result = founder_cron.tick(types.SimpleNamespace(connection_factory=lambda: ScriptedDB()), {'RAFII_CONTROL_ENABLED': '1'}, fstore=Store(),
                                       observe=lambda *a: {}, clock=lambda: NOW_EPOCH)
        for stage in ('operational_snapshot', 'connection_health', 'reliability_purge'):
            with self.subTest(stage):
                self.assertNotIn('error', result[stage])
                self.assertIn(result[stage]['status'], ('ok', 'skipped', 'unavailable'))


if __name__ == '__main__':
    unittest.main()
