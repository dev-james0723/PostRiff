"""Demo parity: the activated v1 metric ids computed from the real Demo dataset, including the cost_anomaly scenario."""
from collections import defaultdict
import copy
import socket
import unittest
import uuid
from unittest.mock import patch

from rafii_control.auth import ControlError
from rafii_control.demo_dataset import sample_data
from rafii_control.demo_metrics import compute, NOT_SIMULATED
from rafii_control.founder_preview_scenarios import apply_scenario, ANOMALY_FACTOR, ANOMALY_DAYS, ANOMALY_STRIDE
from rafii_control.intelligence import Catalog, QueryService
from rafii_control.live_metrics import overview, SOURCE_IDS, unknown_reservations

TZ = 'America/Indiana/Indianapolis'
AS_OF = '2026-10-01T12:00:00Z'
AFTER = '2026-10-01T12:00:01Z'
NOW = '2026-10-01T14:00:00Z'


def query(metric, group_by=(), filters=(), comparison='none', start='2026-08-01T00:00:00Z', end=AFTER):
    return dict(metricIds=[metric], interval=dict(start=start, end=end, timeZone=TZ), groupBy=list(group_by), filters=list(filters), comparison=comparison, limit=1000)


class ReadStore:
    environment = 'local'
    def __init__(self): self.receipts = []
    def read(self, kind, identifier=None): return []
    def receipt(self, receipt): self.receipts.append(receipt)


class DemoMetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = sample_data()
        cls.catalog = Catalog()

    def setUp(self):
        self.data = copy.deepcopy(self.canonical)
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('real egress is forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def rows(self, metric_query, data=None):
        metrics = self.catalog.validate_query(metric_query)
        rows, coverage, versions = compute(data or self.data, metric_query, metrics)
        return rows

    def test_every_activated_id_returns_contract_rows_marked_fixture(self):
        for metric_id in self.catalog.metrics:
            if not self.catalog.activated(metric_id): continue
            with self.subTest(metric=metric_id):
                group_by = ['currency'] if self.catalog.metrics[metric_id]['currency_policy'] == 'native_currency_separate' else []
                rows = self.rows(query(metric_id, group_by))
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(set(row) >= {'metricId', 'definitionVersion', 'interval', 'dimensions', 'value', 'unit', 'dataState', 'coverage', 'sourceWatermark'}, True)
                    version = (self.catalog.metrics[metric_id].get('activation') or {}).get('definitionVersion') or 'v1'
                    self.assertEqual((row['metricId'], row['definitionVersion'], row['fixture']), (metric_id, version, True))
                    self.assertEqual(set(row['coverage']), {'known', 'unknown', 'numerator', 'denominator'})
                    if metric_id in NOT_SIMULATED:
                        self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'demo_not_simulated'))
                    elif row['dataState'] == 'unavailable':
                        # A slice may honestly say its records are not simulated in Demo, or that the definition needs more
                        # history than the Demo snapshot holds; never a zero, never another reason.
                        self.assertIsNone(row['value'])
                        self.assertIn(row['reason'], ('demo_not_simulated', 'insufficient_history'))
                    else:
                        self.assertIn(row['dataState'], ('measured', 'partial', 'not_applicable'))

    def test_paid_counts_and_plan_distribution_match_the_dataset(self):
        summary, distribution = self.data['summary'], {row['plan']: row['subscribers'] for row in self.data['analytics']['planDistribution']}
        self.assertEqual(self.rows(query('paid_customers'))[0]['value'], summary['customers'])
        self.assertEqual(self.rows(query('paid_workspaces'))[0]['value'], summary['currentPaidSubscriptions'])
        by_plan = {row['dimensions']['plan']: row['value'] for row in self.rows(query('subscriptions_by_plan_status', ['plan', 'status']))}
        self.assertEqual(by_plan, distribution)
        self.assertTrue(all(row['dimensions']['status'] == 'active' for row in self.rows(query('subscriptions_by_plan_status', ['plan', 'status']))))
        filtered = self.rows(query('paid_workspaces', ['plan'], [dict(dimension='plan', operator='eq', values=['Studio'])]))
        self.assertEqual([(row['dimensions'], row['value']) for row in filtered], [({'plan': 'Studio'}, distribution['Studio'])])
        series = self.rows(query('paid_customers', ['window'], start='2026-09-28T00:00:00Z'))
        self.assertEqual([row['dimensions']['window'] for row in series], ['2026-09-27', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01'])
        self.assertTrue(all(row['value'] == summary['customers'] for row in series))

    def test_cash_collected_by_day_matches_the_revenue_trend_and_half_open_intervals(self):
        trend = {row['period']: row['cashMinor'] for row in self.data['analytics']['revenueTrend']}
        rows = self.rows(query('cash_collected', ['currency', 'window'], start='2026-07-01T00:00:00Z'))
        by_month = defaultdict(int)
        for row in rows: by_month[row['dimensions']['window'][:7]] += row['value']
        self.assertEqual(dict(by_month), {month: cash for month, cash in trend.items() if cash})
        self.assertTrue(all(row['currency'] == 'USD' and row['unit'] == 'currency_minor' and row['dataState'] == 'measured' for row in rows))
        # The October payments are stamped 08:xx UTC on 2026-10-01, which is still 2026-10-01 in Indiana.
        october = [row for row in rows if row['dimensions']['window'] == '2026-10-01']
        self.assertEqual(len(october), 1)
        # A grouped query over an empty period returns no groups (SQL semantics); an ungrouped count returns a measured zero.
        self.assertEqual(self.rows(query('cash_collected', ['currency'], start='2026-10-01T00:00:00Z', end='2026-10-01T08:00:00Z')), [])
        empty = self.rows(query('payment_failures', start='2026-10-01T00:00:00Z', end='2026-10-01T08:00:00Z'))[0]
        self.assertEqual((empty['value'], empty['dataState'], empty['sampleCount']), (0, 'measured', 0))
        with self.assertRaises(ControlError): self.rows(query('cash_collected'))  # native currency requires the currency dimension

    def test_ai_cost_uses_the_snapshot_bound_and_cost_vs_cash_divides_usd_micro(self):
        expected_cost = sum(row['estimatedUsdMicro'] for row in self.data['usage'])
        at_as_of = self.rows(query('ai_cost_actual', end=AS_OF))[0]
        self.assertEqual((at_as_of['value'], at_as_of['sampleCount']), (0, 0))
        included = self.rows(query('ai_cost_actual'))[0]
        self.assertEqual((included['value'], included['currency'], included['unit'], included['dataState']), (expected_cost, 'USD', 'usd_micro', 'measured'))
        self.assertEqual(included['coverage'], dict(known=len(self.data['usage']), unknown=0, numerator=None, denominator=None))
        by_feature = self.rows(query('ai_cost_by_feature'))
        self.assertEqual([row['dimensions'] for row in by_feature], [{'feature': 'writer'}])
        cash = self.rows(query('cash_collected', ['currency'], start='2026-10-01T00:00:00Z'))[0]['value']
        ratio = self.rows(query('cost_vs_cash', ['currency'], start='2026-10-01T00:00:00Z'))[0]
        self.assertAlmostEqual(ratio['value'], expected_cost / (cash * 10000))
        self.assertEqual((ratio['coverage']['numerator'], ratio['coverage']['denominator']), (expected_cost, cash * 10000))
        empty = self.rows(query('cost_vs_cash', ['currency'], start='2026-10-02T00:00:00Z', end='2026-10-03T00:00:00Z'))[0]
        self.assertEqual((empty['value'], empty['dataState']), (None, 'not_applicable'))
        self.assertEqual(self.rows(query('ai_cost_unknown'))[0]['value'], 0)

    def test_backlog_activity_sources_and_heartbeat(self):
        backlog = self.rows(query('data_requests_backlog', ['kind']))
        self.assertEqual(sum(row['value'] for row in backlog), self.data['summary']['openRequests'])
        self.assertEqual({row['dimensions']['kind'] for row in backlog}, {'billing', 'support'})
        active = self.rows(query('active_workspaces'))[0]
        self.assertEqual(active['value'], self.data['summary']['workspaces'])
        sources = self.rows(query('source_health', ['source', 'state']))
        self.assertEqual([row['dimensions']['source'] for row in sources], list(SOURCE_IDS))
        self.assertTrue(all(row['dataState'] == 'measured' and row['value'] == 0 for row in sources))
        heartbeat = self.rows(query('cron_heartbeat'))[0]
        self.assertEqual((heartbeat['value'], heartbeat['dataState']), (0, 'measured'))
        self.assertEqual(self.rows(query('notification_delivery'))[0]['value'], 0)
        self.assertEqual(self.rows(query('phone_calls'))[0]['value'], 0)

    def test_comparison_and_rejections(self):
        # September in Indiana local time is [Sep 1 04:00Z, Oct 1 04:00Z); previous_complete aligns to August 1 00:00 local.
        september = dict(start='2026-09-01T04:00:00Z', end='2026-10-01T04:00:00Z')
        rows = self.rows(query('cash_collected', ['currency'], comparison='previous_complete', **september))
        self.assertEqual(rows[0]['value'], self.data['analytics']['revenueTrend'][1]['cashMinor'])
        self.assertEqual(rows[0]['comparison']['value'], self.data['analytics']['revenueTrend'][0]['cashMinor'])
        self.assertEqual(rows[0]['comparison']['interval']['start'], '2026-08-01T04:00:00Z')
        # previous_equal_elapsed shifts by the elapsed length instead: [Aug 2 04:00Z, Sep 1 04:00Z) holds no Demo payment.
        shifted = self.rows(query('cash_collected', ['currency'], comparison='previous_equal_elapsed', **september))
        self.assertEqual((shifted[0]['comparison']['value'], shifted[0]['comparison']['dataState']), (None, 'unavailable'))
        for bad in (query('ai_cost_actual', comparison='cohort_age_aligned'), query('ai_cost_actual', ['window'], comparison='previous_complete')):
            with self.assertRaises(ControlError): self.rows(bad)
        with self.assertRaises(ControlError): compute({'mode': 'live'}, query('ai_cost_actual'), [self.catalog.metrics['ai_cost_actual']])

    def test_scenarios_flow_through_the_same_definitions(self):
        apply_scenario(self.data, 'payment_failure', now=NOW)
        failures = self.rows(query('payment_failures', ['payment_type']))
        self.assertEqual([(row['dimensions'], row['value']) for row in failures], [({'payment_type': 'subscription'}, 1)])
        deliveries = self.rows(query('notification_delivery', ['channel', 'status'], start='2026-10-01T00:00:00Z', end='2026-10-02T00:00:00Z'))
        self.assertEqual([(row['dimensions'], row['value']) for row in deliveries], [({'channel': 'email', 'status': 'queued'}, 1)])
        apply_scenario(self.data, 'stale_data', now='2026-10-01T15:00:00Z')
        stale = self.rows(query('ai_cost_actual'))[0]
        self.assertEqual((stale['dataState'], stale['reason']), ('stale', 'source_stale'))
        self.assertTrue(all(row['dataState'] == 'stale' for row in self.rows(query('source_health', ['source']))))
        self.assertEqual(self.rows(query('cron_heartbeat'))[0]['dataState'], 'stale')

    def test_cost_anomaly_scenario_raises_cost_for_three_days_and_opens_an_incident(self):
        baseline = sum(row['estimatedUsdMicro'] for row in self.data['usage'])
        selected = self.data['usage'][::ANOMALY_STRIDE]
        selected_cost = sum(row['estimatedUsdMicro'] for row in selected)
        result = apply_scenario(self.data, 'cost_anomaly', now=NOW)
        self.assertEqual(result['scenario'], 'cost_anomaly')
        self.assertEqual(result['costAnomaly']['factor'], ANOMALY_FACTOR)
        self.assertEqual(result['costAnomaly']['rows'], len(selected))
        incident = next(row for row in self.data['incidents'] if row['id'] == result['incidentId'])
        self.assertEqual((incident['detectorFamily'], incident['state'], incident['classification']), ('demo_cost_anomaly', 'open', 'simulated_cost_anomaly'))
        self.assertEqual(incident['affectedCount'], len({row['workspaceId'] for row in selected}))
        self.assertEqual(incident['evidence']['observedUsdMicro'], selected_cost * ANOMALY_FACTOR)
        self.assertEqual(self.data['usageState'], 'simulated_cost_anomaly')
        total = self.rows(query('ai_cost_actual'))[0]['value']
        self.assertEqual(total, baseline + selected_cost * (ANOMALY_FACTOR - 1))
        series = self.rows(query('ai_cost_actual', ['window'], start='2026-09-25T00:00:00Z'))
        days = [row['dimensions']['window'] for row in series]
        self.assertEqual(days, ['2026-09-29', '2026-09-30', '2026-10-01'])
        self.assertEqual(len(days), ANOMALY_DAYS)
        self.assertTrue(all(row['value'] > 0 for row in series))
        self.assertIn(incident['id'], [row['incidentId'] for row in self.data['notificationEvents']])
        # Replay is idempotent; recovery resolves the incident and restores the cost; normal keeps the history.
        self.assertTrue(apply_scenario(self.data, 'cost_anomaly', now=NOW)['replayed'])
        apply_scenario(self.data, 'recovery', now='2026-10-01T15:00:00Z')
        self.assertEqual(incident['state'], 'resolved')
        self.assertEqual(self.rows(query('ai_cost_actual'))[0]['value'], baseline)
        self.assertEqual(sum(row['at'] == AS_OF for row in self.data['usage']), len(self.data['usage']))
        apply_scenario(self.data, 'normal', now='2026-10-01T16:00:00Z')
        self.assertEqual(self.data['usageState'], self.canonical['usageState'])
        self.assertEqual(len(self.data['incidents']), 1)
        apply_scenario(self.data, 'cost_anomaly', now='2026-10-01T17:00:00Z')
        apply_scenario(self.data, 'notification_failure', now='2026-10-01T17:30:00Z')
        self.assertEqual(self.data['incidents'][-1]['detectorFamily'], 'demo_cost_anomaly')
        self.assertEqual(self.data['incidents'][-1]['notificationState'], 'failed')
        self.assertEqual(self.rows(query('ai_cost_actual'))[0]['value'], baseline + selected_cost * (ANOMALY_FACTOR - 1))

    def test_demo_metric_query_receipt_and_overview(self):
        store = ReadStore()
        service = QueryService(store, self.catalog)
        principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query']}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}
        result = service.metric_query(query('paid_customers'), principal, str(uuid.uuid4()), mode='demo', demo_data=self.data)
        self.assertEqual((result['executionState'], result['mode'], result['rows'][0]['value']), ('demo_dataset', 'demo', 10000))
        self.assertEqual(store.receipts[-1]['executionState'], 'demo_dataset')
        self.assertEqual(result['sourceVersions']['seed'], self.data['manifest']['seed'])
        self.assertEqual(result['sourceVersions']['receipt'], self.data['receipt']['id'])
        apply_scenario(self.data, 'cost_anomaly', now=NOW)
        service.demo_data = lambda principal: self.data
        store.receipts = []
        page = overview(principal, 'demo', '30d', service)
        tiles = {tile['id']: tile for tile in page['pulse']}
        self.assertEqual(tiles['paid_customers']['value'], 10000)
        self.assertEqual(tiles['paid_customers']['delta'], 0)
        self.assertEqual(len(tiles['paid_customers']['sparkline']), 31)
        self.assertEqual(tiles['cash_collected']['value'], self.data['summary']['cashThisMonthMinor'])
        self.assertEqual(tiles['cash_collected']['currency'], 'USD')
        self.assertEqual(tiles['ai_cost_actual']['unit'], 'usd_micro')
        self.assertGreater(tiles['ai_cost_actual']['value'], 0)
        # MRR is activated (CONTRACTS §8.A): the Demo computes it from the candidate catalog and says so on the tile.
        self.assertEqual(tiles['mrr']['dataState'], 'measured')
        self.assertIn('Candidate v2 catalog', tiles['mrr'].get('note') or '')
        self.assertEqual(tiles['publish_outcomes']['dataState'], 'unavailable')
        self.assertIn('incident_' + self.data['incidents'][-1]['id'], [item['id'] for item in page['attention']])
        self.assertTrue(any(item['id'] == 'data_requests_backlog' for item in page['attention']))
        self.assertEqual(page['_dataState'], 'synthetic')
        self.assertEqual(len(page['sourceHealth']), len(SOURCE_IDS))
        self.assertTrue(page['brief']['text'].startswith('Demo dataset overview'))
        cost_series = next(series for series in page['trends']['revenueVsCost']['series'] if series['id'] == 'ai_cost_actual')
        self.assertEqual(cost_series['points'][-1]['t'], '2026-10-01')
        self.assertIn(page['trends']['revenueVsCost']['dataState'], ('measured', 'partial', 'stale', 'unavailable'), 'one metric-level state per trend, like the tiles')
        incident_item = next(item for item in page['attention'] if item['id'] == 'incident_' + self.data['incidents'][-1]['id'])
        self.assertEqual([action['kind'] for action in incident_item['actions']], ['explain', 'open'], 'Demo incidents carry no live version, so no ack action')
        self.assertEqual(len(page['_receiptIds']), len(store.receipts))
        queue = unknown_reservations(principal, 'demo', service, demo_data=self.data)
        self.assertEqual((queue['rows'], queue['_dataState']), ([], 'synthetic'))


if __name__ == '__main__':
    unittest.main()
