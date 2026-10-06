"""Activated v1 Live metrics: fixed SQL shapes, row contract, receipts and the Overview, with the ReadStore stub."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unittest
import uuid

from rafii_control.auth import ControlError
from rafii_control.intelligence import Catalog, QueryService, PACK, ACTIVATED
from rafii_control import live_metrics
from rafii_control.live_metrics import SPECS, compose, previous_interval, overview, unknown_reservations, SOURCE_IDS
from rafii_control.store import MetricStatement

ROOT = Path(__file__).resolve().parents[2]
DOCS_PACK = ROOT / 'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2'
INTERVAL = dict(start='2026-09-01T00:00:00Z', end='2026-10-01T00:00:00Z', timeZone='America/Indiana/Indianapolis')
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def query(metric, group_by=(), filters=(), comparison='none', interval=INTERVAL):
    return dict(metricIds=[metric], interval=dict(interval), groupBy=list(group_by), filters=list(filters), comparison=comparison, limit=1000)


class ReadStore:
    """The existing stub pattern plus the reader-role metric helper; every statement is recorded for shape assertions."""
    environment = 'local'

    def __init__(self):
        self.receipts, self.statements, self.sources = [], [], []
        self.rows, self.instrumented = {}, set()

    def read(self, kind, identifier=None): return list(self.sources) if kind == 'sources' else []
    def receipt(self, receipt): self.receipts.append(receipt)

    def metric_rows(self, statement, params, limit=1000):
        if not isinstance(statement, MetricStatement): raise AssertionError('statements must come from the registry')
        self.statements.append((statement.metric_id, statement.sql, list(params)))
        if statement.metric_id == 'probe':
            return [dict(instrumented=any(view in statement.sql for view in self.instrumented))]
        # PostgreSQL returns every selected alias; canned rows default the dimension/measure aliases the statement names.
        aliases = re.findall(r'AS "([dm]_[a-z_A-Z]+)"', statement.sql)
        return [{**{alias: (0 if alias.startswith('m_') else None) for alias in aliases}, **row} for row in self.rows.get(statement.metric_id, [])]


def aggregate(value, known=1, unknown=0, numerator=None, denominator=None, watermark='2026-09-30T23:00:00+00:00', sample_count=1, **dims):
    row = dict(value=value, known=known, unknown=unknown, numerator=numerator, denominator=denominator, watermark=watermark, sample_count=sample_count)
    row.update({f'd_{key}': value for key, value in dims.items()})
    return row


class LiveMetricTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.store = ReadStore()
        self.service = QueryService(self.store, self.catalog, clock=lambda: NOW)
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query', 'customers.read', 'workspaces.read']},
                          'session': {'environment': 'local', 'id': str(uuid.uuid4())}}

    def run_query(self, metric_query, mode='live', **kwargs):
        return self.service.metric_query(metric_query, self.principal, str(uuid.uuid4()), mode=mode, **kwargs)

    def test_pack_lives_in_package_and_catalog_activates_without_editing_proposed_entries(self):
        self.assertEqual(PACK, Path(live_metrics.__file__).resolve().parent / 'pack')
        docs = json.loads((DOCS_PACK / 'catalogs/metrics.json').read_text())
        shipped = json.loads((PACK / 'catalogs/metrics.json').read_text())
        self.assertEqual(len(docs), 63)
        self.assertEqual(shipped[:63], docs)
        # P0 activations follow the 63 proposed rows in metrics.json; P1/P2 slices add theirs in catalogs/metrics.d/*.json.
        extensions = [row for path in sorted((PACK / 'catalogs/metrics.d').glob('*.json')) for row in json.loads(path.read_text())]
        activated = {row['id'] for row in shipped[63:] + extensions}
        live_metrics.load_extensions()
        self.assertEqual(activated, set(live_metrics.METRIC_SOURCES))
        self.assertTrue(all(row['status'] == ACTIVATED for row in shipped[63:] + extensions))
        self.assertTrue(all(self.catalog.activated(metric_id) for metric_id in activated))
        # Definitions the PRD rules out for this release stay proposed (§7.1: no CAC, LTV or payback).
        self.assertEqual(self.catalog.metrics['cac']['status'], 'proposed_definition_not_activated')
        # The structural schema now admits exactly the catalog ids and dimensions.
        self.catalog.validate('metric-query', query('phone_calls', ['kind', 'window']))
        with self.assertRaises(ControlError): self.catalog.validate('metric-query', query('not_a_metric'))

    def test_every_registry_statement_is_fixed_parameterised_half_open_and_excluding(self):
        for metric_id, spec in SPECS.items():
            with self.subTest(metric=metric_id):
                dims = self.catalog.metrics[metric_id]['allowed_dimensions']
                filters = [dict(dimension=dims[0], operator='in', values=["x' OR 1=1 --"])] if dims else []
                statement, params, group_by, history = compose(metric_id, query(metric_id, dims[:3], filters))
                self.assertEqual(statement.sql.count('%s'), len(params))
                self.assertNotIn("1=1", statement.sql)
                self.assertIn(["x' OR 1=1 --"], params)
                self.assertTrue(statement.sql.startswith('WITH base AS (SELECT'))
                self.assertIn('LIMIT %s', statement.sql)
                self.assertEqual(params[-1], live_metrics.MAX_POINTS + 1)
                if spec['interval_params']:
                    self.assertIn('>= %s::timestamptz AND', statement.sql)
                    self.assertIn('< %s::timestamptz', statement.sql)
                    self.assertEqual(params[:2], [INTERVAL['start'], INTERVAL['end']])
                if metric_id == 'founder_ops_cost':
                    # Founder ops cost includes exactly what customer metrics exclude: exempt rows, the ops cost centre and internal/test/demo workspaces.
                    self.assertIn('"aiUsageExempt" OR u."costCenter"=\'founder_ops\'', statement.sql)
                    self.assertIn("OR EXISTS (SELECT 1 FROM rafii_control.workspace_classifications c WHERE c.kind IN ('internal','test','demo')", statement.sql)
                    self.assertNotIn('NOT EXISTS (SELECT 1 FROM rafii_control.workspace_classifications', statement.sql)
                elif self.catalog.metrics[metric_id]['default_exclusions']:
                    self.assertIn("c.kind IN ('internal','test','demo')", statement.sql)
                if 'business_usage_v2' in statement.sql and metric_id != 'founder_ops_cost': self.assertIn('NOT u."aiUsageExempt"', statement.sql)
                if 'business_usage_v2 u' in statement.sql:
                    # An unknown row whose reservation was later settled/released is reconciled, never counted twice (billing.Ledger.unknown_reservations).
                    self.assertIn('NOT (u."costState"=\'estimated_unknown\' AND EXISTS (SELECT 1 FROM rafii_control.business_usage_v2 t WHERE t."workspaceId"=u."workspaceId" AND t."reservationId"=u."reservationId" AND t."costState" IN (\'actual\',\'released\')))', statement.sql)
                if 'business_subscriptions_v2 s' in statement.sql and spec.get('snapshot'): self.assertIn("provider<>'fixture'", statement.sql)
                if 'window' in dims[:3]:
                    self.assertIn("to_char(date_trunc('day', b.at AT TIME ZONE %s),'YYYY-MM-DD')", statement.sql)
                    self.assertIn(INTERVAL['timeZone'], params)

    def test_window_series_for_snapshot_metrics_reads_daily_snapshots(self):
        statement, params, _, history = compose('paid_customers', query('paid_customers', ['window']))
        self.assertTrue(history)
        self.assertIn('rafii_control.business_subscription_snapshots h', statement.sql)
        self.assertIn('AT TIME ZONE %s)::date', statement.sql)
        self.assertEqual(params[:5], [INTERVAL['timeZone'], INTERVAL['start'], INTERVAL['timeZone'], INTERVAL['end'], INTERVAL['timeZone']])
        with self.assertRaises(ControlError): compose('budget_remaining', query('budget_remaining', ['window']))
        with self.assertRaises(ControlError): compose('phone_calls', query('phone_calls', ['suite']))

    def test_previous_intervals_align_to_calendar_month_only_for_previous_complete(self):
        mtd = query('cash_collected', ['currency'], comparison='previous_complete', interval=dict(start='2026-10-01T04:00:00Z', end='2026-10-15T04:00:00Z', timeZone='America/Indiana/Indianapolis'))
        previous = previous_interval(mtd)
        self.assertEqual(previous['start'], '2026-09-01T04:00:00Z')
        self.assertEqual(previous['end'], '2026-09-15T04:00:00Z')
        equal = previous_interval({**mtd, 'comparison': 'previous_equal_elapsed'})
        self.assertEqual((equal['start'], equal['end']), ('2026-09-17T04:00:00Z', '2026-10-01T04:00:00Z'))
        for bad in (query('ai_cost_actual', comparison='cohort_age_aligned'), query('ai_cost_actual', ['window'], comparison='previous_equal_elapsed')):
            with self.assertRaises(ControlError): self.run_query(bad)

    def test_rows_follow_contract_and_missing_data_is_never_zero(self):
        self.store.rows['ai_cost_actual'] = [aggregate('123456', known=4, unknown=2, feature='writer'), aggregate('1000', known=1, feature='agent')]
        self.store.rows['ai_cost_actual'][0]['m_unknownEstimateUsdMicro'] = '777'
        self.store.instrumented = {'business_usage_v2', 'business_billing_notices'}
        result = self.run_query(query('ai_cost_actual', ['feature']))
        rows = result['rows']
        self.assertEqual(result['executionState'], 'admitted_operational')
        self.assertEqual({row['dataState'] for row in rows}, {'partial', 'measured'})
        self.assertEqual(rows[0]['value'], 123456)
        self.assertEqual(rows[0]['coverage'], dict(known=4, unknown=2, numerator=None, denominator=None))
        self.assertEqual(rows[0]['reason'], 'unsettled_cost_rows')
        self.assertEqual(rows[0]['measures'], dict(unknownEstimateUsdMicro=777))
        self.assertEqual((rows[0]['currency'], rows[0]['unit'], rows[0]['definitionVersion']), ('USD', 'usd_micro', 'v1'))
        self.assertEqual(rows[0]['interval'], INTERVAL)
        self.assertEqual(rows[0]['dimensions'], dict(feature='writer'))
        self.assertEqual(result['dataState'], 'partial')
        # Instrumented source with no events: a measured zero. Not instrumented: unavailable with no value.
        self.store.rows['payment_failures'] = [aggregate(0, known=0, sample_count=0, watermark=None)]
        zero = self.run_query(query('payment_failures'))['rows'][0]
        self.assertEqual((zero['value'], zero['dataState']), (0, 'measured'))
        self.store.rows['publish_outcomes'] = [aggregate(0, known=0, sample_count=0, watermark=None)]
        missing = self.run_query(query('publish_outcomes'))['rows'][0]
        self.assertEqual((missing['value'], missing['dataState'], missing['reason']), (None, 'unavailable', 'not_instrumented'))
        self.assertEqual(self.store.statements[-1][0], 'probe')
        self.assertIn('business_notification_events', self.store.statements[-1][1])

    def test_receipt_path_rejects_mixed_definitions_and_keeps_proposed_behaviour(self):
        self.store.rows['paid_customers'] = [aggregate(12, known=12)]
        result = self.run_query(query('paid_customers'))
        receipt = self.store.receipts[-1]
        self.assertEqual(receipt['executionState'], 'admitted_operational')
        self.assertEqual(receipt['metricVersions'], {'paid_customers': 1})
        self.assertEqual(receipt['rows'][0]['value'], 12)
        self.assertEqual(result['sourceVersions']['adapter'], 'live_metrics/v1')
        self.assertEqual(result['mode'], 'live')
        with self.assertRaises(ControlError): self.run_query({**query('paid_customers'), 'metricIds': ['paid_customers', 'mrr']})
        proposed = self.run_query(query('cac', ['currency']))   # PRD §7.1: CAC stays a proposed definition
        self.assertEqual(proposed['executionState'], 'policy_unavailable')
        self.assertIsNone(proposed['rows'][0]['value'])
        with self.assertRaises(ControlError): self.run_query(query('paid_customers'), mode='staging')
        self.principal['operator']['capabilities'] = ['control.read']
        with self.assertRaises(ControlError): self.run_query(query('paid_customers'))

    def test_dispatch_carries_mode_beside_the_query(self):
        self.store.rows['paid_customers'] = [aggregate(3, known=3)]
        body = {**query('paid_customers'), 'mode': 'live'}
        result = self.service.dispatch('/metrics/query', body, self.principal, str(uuid.uuid4()))
        self.assertEqual(result['rows'][0]['value'], 3)
        with self.assertRaises(ControlError): self.service.dispatch('/metrics/query', {**body, 'mode': 'production'}, self.principal, str(uuid.uuid4()))

    def test_stale_sources_and_heartbeat_and_source_health_rows(self):
        # One vocabulary: the ids the founder cron probes are the ids the metrics read (founder_sources), and every consumer-DB metric hangs off 'database'.
        from rafii_control import founder_cron, founder_sources
        self.assertEqual(SOURCE_IDS, founder_sources.SOURCE_IDS)
        self.assertEqual(set(live_metrics.METRIC_SOURCES.values()) <= set(SOURCE_IDS), True)
        live_metrics.load_extensions()
        self.assertEqual(set(live_metrics.METRIC_SOURCES), set(SPECS) | live_metrics.COMPOSITE | live_metrics.PYTHON_ONLY | set(live_metrics.CUSTOM))
        self.assertEqual(live_metrics.METRIC_SOURCES['paid_customers'], 'database')

        class Probed:
            written = {}
            def ping(self): return True
            def upsert_source_health(self, source_id, state, reason_code, checked_at, watermark=None): self.written[source_id] = (state, reason_code)
        probed = Probed()
        founder_cron.probe(probed, object(), {}, 0)
        self.assertEqual(set(probed.written), set(SOURCE_IDS), 'the cron writes exactly the ids the metrics read')
        self.store.sources = [dict(source_id='database', state='stale', watermark='2026-09-20T00:00:00+00:00', checked_at='2026-09-30T00:00:00+00:00', reason_code='lagging'),
                              dict(source_id='cron', state='measured', watermark='2026-10-01T11:58:00+00:00', checked_at='2026-10-01T11:58:00+00:00', reason_code='qualified')]
        self.store.rows['paid_customers'] = [aggregate(12, known=12)]
        row = self.run_query(query('paid_customers'))['rows'][0]
        self.assertEqual((row['dataState'], row['reason'], row['value']), ('stale', 'source_stale', 12))
        # A source recorded 'measured' but last probed longer ago than the heartbeat threshold is not current either.
        self.store.sources[0] = dict(source_id='database', state='measured', watermark='2026-10-01T11:00:00+00:00', checked_at='2026-10-01T11:00:00+00:00', reason_code='qualified')
        row = self.run_query(query('paid_customers'))['rows'][0]
        self.assertEqual((row['dataState'], row['reason']), ('stale', 'source_stale'))
        health = {row['dimensions']['source']: row for row in self.run_query(query('source_health', ['source', 'state', 'reason']))['rows']}
        self.assertEqual((health['database']['dataState'], health['database']['dimensions']['state'], health['database']['reason']), ('stale', 'stale', 'lagging'))
        self.assertEqual((health['cron']['dataState'], health['phone_provider']['dataState'], health['phone_provider']['reason']), ('measured', 'unavailable', 'no_probe_recorded'))
        self.store.sources[0]['checked_at'] = '2026-10-01T11:59:00+00:00'
        self.assertEqual(self.run_query(query('paid_customers'))['rows'][0]['dataState'], 'measured')
        heartbeat = self.run_query(query('cron_heartbeat'))['rows'][0]
        self.assertEqual((heartbeat['value'], heartbeat['dataState'], heartbeat['unit']), (120, 'measured', 'seconds'))
        self.store.sources[1]['checked_at'] = '2026-10-01T11:00:00+00:00'
        self.assertEqual(self.run_query(query('cron_heartbeat'))['rows'][0]['dataState'], 'stale')
        self.store.sources = []
        self.assertEqual(self.run_query(query('cron_heartbeat'))['rows'][0]['dataState'], 'unavailable')
        health = self.run_query(query('source_health', ['source', 'state']))['rows']
        self.assertEqual([row['dimensions']['source'] for row in health], list(SOURCE_IDS))
        self.assertTrue(all(row['dataState'] == 'unavailable' and row['value'] is None for row in health))

    def test_comparison_rows_match_dimensions_and_snapshot_history(self):
        self.store.rows['cash_collected'] = [aggregate('5000', known=2, currency='USD')]
        rows = self.run_query(query('cash_collected', ['currency'], comparison='previous_equal_elapsed'))['rows']
        self.assertEqual(rows[0]['comparison']['value'], 5000)
        self.assertEqual(rows[0]['comparison']['interval']['start'], '2026-08-02T00:00:00Z')
        self.assertEqual(rows[0]['dataState'], 'partial')
        self.assertEqual(rows[0]['reason'], 'invoices_before_instrumentation_not_recorded')   # cash_collected v2 (slice-revenue, metrics.d/revenue.json)
        self.assertEqual(rows[0]['definitionVersion'], 'v2')
        self.store.rows['paid_workspaces'] = [aggregate(9, known=9)]
        self.store.instrumented = {'business_subscriptions_v2', 'business_subscription_snapshots'}
        rows = self.run_query(query('paid_workspaces', comparison='previous_equal_elapsed'))['rows']
        history = [entry for entry in self.store.statements if entry[0] == 'paid_workspaces' and 'business_subscription_snapshots' in entry[1]]
        self.assertEqual(len(history), 1)
        self.assertEqual(rows[0]['comparison']['value'], 9)

    def test_cost_vs_cash_ratio_uses_usd_only_and_zero_denominator_is_not_applicable(self):
        self.store.rows['cash_collected'] = [aggregate('200', known=1, currency='USD'), aggregate('900', known=1, currency='GBP')]
        self.store.rows['ai_cost_actual'] = [aggregate('1000000', known=3)]
        rows = self.run_query(query('cost_vs_cash', ['currency']))['rows']
        usd = next(row for row in rows if row['currency'] == 'USD')
        self.assertAlmostEqual(usd['value'], 1000000 / 2000000)
        self.assertEqual((usd['coverage']['numerator'], usd['coverage']['denominator'], usd['unit']), (1000000, 2000000, 'ratio'))
        gbp = next(row for row in rows if row['currency'] == 'GBP')
        self.assertEqual((gbp['value'], gbp['dataState']), (None, 'not_applicable'))
        self.store.rows['cash_collected'] = [aggregate('0', known=0, sample_count=0, currency='USD')]
        self.store.instrumented = {'business_payments_v2', 'business_usage_v2'}
        self.assertEqual(self.run_query(query('cost_vs_cash', ['currency']))['rows'][0]['dataState'], 'not_applicable')

    def test_overview_live_contract(self):
        self.store.instrumented = {'business_subscriptions_v2', 'business_payments_v2', 'business_usage_v2', 'business_notification_events', 'business_billing_notices',
                                   'business_budgets', 'business_data_requests_v2', 'business_agent_runs', 'business_subscription_snapshots'}
        self.store.rows.update(paid_customers=[aggregate(10, known=10)], cash_collected=[aggregate('4000', known=3, currency='USD')], ai_cost_actual=[aggregate('250000', known=5)],
                               publish_outcomes=[aggregate(10, known=9, unknown=1, numerator=8, denominator=10)], payment_failures=[aggregate(6, known=6)], ai_cost_unknown=[aggregate('99', known=2)],
                               budget_remaining=[aggregate('50000', known=1, numerator='950000', denominator='1000000', scope='global')],
                               data_requests_backlog=[aggregate(2, known=2, kind='export', age_band='over_7d')], active_workspaces=[aggregate(4, known=4)])
        self.store.sources = [dict(source_id='cron', state='measured', watermark='2026-10-01T11:59:00+00:00', checked_at='2026-10-01T11:59:00+00:00', reason_code='qualified')]
        result = overview(self.principal, 'live', '30d', self.service)
        self.assertEqual([tile['id'] for tile in result['pulse']], ['paid_customers', 'mrr', 'cash_collected', 'ai_cost_actual', 'publish_outcomes'])
        for tile in result['pulse']:
            self.assertEqual(set(tile) >= {'id', 'label', 'value', 'unit', 'currency', 'delta', 'deltaPeriod', 'sparkline', 'dataState', 'coverage', 'receiptId', 'href'}, True)
        self.assertEqual(result['pulse'][1]['dataState'], 'unavailable')
        self.assertIsNone(result['pulse'][1]['value'])
        self.assertAlmostEqual(result['pulse'][4]['value'], 0.8)
        self.assertEqual(result['pulse'][2]['delta'], 0)
        ids = [item['id'] for item in result['attention']]
        self.assertEqual(ids[:2], ['budget_global', 'data_requests_backlog'])
        self.assertIn('payment_failures_7d', ids)
        self.assertLessEqual(len(result['attention']), 5)
        self.assertTrue(all(set(item) >= {'id', 'severity', 'title', 'scope', 'count', 'since', 'href', 'actions'} for item in result['attention']))
        # §3 actions are objects the page can render; 'open' carries the item's href, and an ack always names incident + version.
        failures = next(item for item in result['attention'] if item['id'] == 'payment_failures_7d')
        self.assertEqual([(a['id'], a['kind'], a['label']) for a in failures['actions']], [('explain', 'explain', 'Explain'), ('open', 'open', 'Open'), ('draft_reminder', 'draft_reminder', 'Draft reminder')])
        self.assertEqual(failures['actions'][1]['href'], '/founder/revenue?tab=payments')
        incident_actions = live_metrics._actions(('explain', 'open', 'ack'), '/founder/operations?incident=i1', incident={'id': 'i1', 'version': 3})
        self.assertEqual(incident_actions[2], dict(id='ack', label='Acknowledge', kind='ack', href=None, incidentId='i1', version=3))
        self.assertEqual([a['kind'] for a in live_metrics._actions(('explain', 'ack'), '/x', incident={'id': 'i1'})], ['explain'], 'no version, no ack')
        self.assertEqual(set(result['trends']), {'revenueVsCost', 'activeVsPublish'})
        trend = result['trends']['revenueVsCost']
        self.assertEqual((trend['id'], trend['title'], trend['period'], trend['unit'], trend['currency']), ('revenue_vs_cost', 'Revenue vs AI cost', '30d', 'usd_micro', 'USD'))
        self.assertEqual([series['id'] for series in trend['series']], ['cash_collected', 'ai_cost_actual'])
        self.assertTrue(all({'id', 'label', 'unit', 'points', 'dataState', 'receiptId'} <= set(series) for series in trend['series']))
        self.assertTrue(all({'t', 'value', 'dataState'} == set(point) for series in trend['series'] for point in series['points']))
        self.assertIsInstance(trend['dataState'], str)
        self.assertEqual(trend['receiptIds'], [series['receiptId'] for series in trend['series']])
        self.assertEqual(trend['receiptId'], trend['receiptIds'][0])
        self.assertEqual([series['id'] for series in result['trends']['activeVsPublish']['series']], ['active_workspaces', 'publish_outcomes'])
        self.assertEqual([tile['href'] for tile in result['pulse'][:2]], ['/founder/customers', '/founder/revenue?tab=mrr-bridge'])
        self.assertEqual([row['sourceId'] for row in result['sourceHealth']], list(SOURCE_IDS))
        self.assertTrue(result['brief']['text'].startswith('Live overview'))
        self.assertEqual(result['brief']['receiptIds'], result['_receiptIds'])
        self.assertEqual(len(result['_receiptIds']), len(self.store.receipts))
        with self.assertRaises(ControlError): overview(self.principal, 'live', '12d', self.service)
        with self.assertRaises(ControlError): overview(self.principal, 'staging', '30d', self.service)

    def test_overview_instrumented_empty_publish_interval_keeps_null_rate_and_receipts(self):
        self.store.instrumented = {'business_notification_events'}
        self.store.rows['publish_outcomes'] = [aggregate(0, known=0, unknown=0, numerator=0, denominator=0, sample_count=0, watermark=None)]
        result = overview(self.principal, 'live', '30d', self.service)
        publishing = next(tile for tile in result['pulse'] if tile['id'] == 'publish_outcomes')
        self.assertIsNone(publishing['value'])
        self.assertIsNone(publishing['delta'])
        self.assertEqual(publishing['dataState'], 'measured')
        self.assertEqual(publishing['coverage'], dict(known=0, unknown=0, numerator=0, denominator=0))
        self.assertIn('Publishing success (7d): no events in this interval.', result['brief']['text'])
        self.assertNotIn('Publishing success (7d): 0.0%', result['brief']['text'])
        self.assertEqual(set(result['trends']), {'revenueVsCost', 'activeVsPublish'})
        self.assertEqual(len(result['_receiptIds']), 16)
        self.assertEqual(len(set(result['_receiptIds'])), 16)
        self.assertEqual(result['brief']['receiptIds'], result['_receiptIds'])
        self.assertEqual([receipt['id'] for receipt in self.store.receipts], result['_receiptIds'])
        receipt = next(receipt for receipt in self.store.receipts if receipt['id'] == publishing['receiptId'])
        self.assertEqual(receipt['normalizedQuery']['metricIds'], ['publish_outcomes'])
        self.assertEqual(receipt['normalizedQuery']['comparison'], 'previous_equal_elapsed')
        self.assertEqual((receipt['rows'][0]['value'], receipt['rows'][0]['coverage']['denominator']), (0, 0))

    def test_overview_brief_requires_nonempty_all_measured_sources_for_current_claim(self):
        current = dict(sourceId='database', state='measured')
        text = live_metrics._brief([], [], [current], 'live', '30d')
        self.assertIn('All probed sources are current.', text)
        for state in ('partial', 'stale', 'unavailable', 'suppressed', 'not_applicable'):
            with self.subTest(state=state):
                text = live_metrics._brief([], [], [current, dict(sourceId='phone_provider', state=state)], 'live', '30d')
                self.assertNotIn('All probed sources are current.', text)
                self.assertIn('Sources not current: phone provider.', text)
        text = live_metrics._brief([], [], [], 'live', '30d')
        self.assertNotIn('All probed sources are current.', text)
        self.assertIn('no source observations were returned', text)

    def test_unknown_reservations_is_a_fixed_reader_statement(self):
        self.store.rows['unknown_reservations'] = [dict(id='u1', workspaceId='w1', runId=None, kind='reserve', dimension='text_model', provider='p', model='m', feature='writer', estimatedUsdMicro=5, at='2026-09-30T00:00:00+00:00')]
        result = unknown_reservations(self.principal, 'live', self.service, limit=50)
        self.assertEqual(result['rows'][0]['id'], 'u1')
        self.assertEqual(self.store.statements[-1][2], [51])
        self.assertIn("u.\"costState\"='estimated_unknown' AND NOT u.\"aiUsageExempt\"", self.store.statements[-1][1])
        self.assertIn('t."reservationId"=u."reservationId"', self.store.statements[-1][1], 'reconciled reservations leave the queue')
        with self.assertRaises(ControlError): unknown_reservations(self.principal, 'live', self.service, limit=0)
        with self.assertRaises(ControlError): unknown_reservations(self.principal, 'nope', self.service)


if __name__ == '__main__':
    unittest.main()
