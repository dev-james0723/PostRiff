"""Founder briefings from receipts (CONTRACTS §8.E; P0 review item 4) and the cost observation through the reader projections.

A scheduled briefing reads its values through QueryService.metric_query as the cron principal — the operator's own
active founder row, capability checks intact — so the report keeps real receipt ids; without a receipt path it falls back
to the cron's unreceipted observations and says why. observe_live reads AI cost through the activated ai_cost_actual
statement over rafii_control.business_usage_v2, so internal/test/demo workspaces and exempt rows are excluded.

In-memory stores only (the ReadStore stub of test_live_metrics answers the fixed metric statements). No PostgreSQL, no
network; test_founder_briefings_pg.py runs the same paths on a disposable database.
"""
import copy
import json
import os
import types
import unittest
import uuid
from datetime import datetime, timezone

import psycopg

os.environ.setdefault('RAFII_PHONE_PROVIDER', 'fake')

from rafii_control import founder_briefings, founder_cron, founder_schedules, live_metrics
from rafii_control.auth import CAPABILITIES
from rafii_control.founder_contact import FLAG

try:
    from test_founder_contact import OPERATOR, PRINCIPAL, MemoryFounderStore
    from test_founder_incidents import FakeDB, FakeNotifications
    from test_live_metrics import ReadStore, aggregate
except ImportError:  # python -m unittest control.test_founder_briefings
    from control.test_founder_contact import OPERATOR, PRINCIPAL, MemoryFounderStore
    from control.test_founder_incidents import FakeDB, FakeNotifications
    from control.test_live_metrics import ReadStore, aggregate


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()


NOW = utc('2026-10-01T12:30:00Z')   # 08:30 on Thursday 1 October in the report time zone (EDT)


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


class ControlStore(ReadStore):
    """The restricted PostgresStore surface a briefing reads through: the operator row, source rows, fixed metric
    statements (canned per metric id), receipts and the content-free audit."""

    def __init__(self, capabilities=None, status='active', role='founder'):
        super().__init__()
        self.operator_row = {'user_id': OPERATOR, 'environment': 'local', 'role': role, 'status': status, 'auth_epoch': 1,
                             'capabilities': sorted(CAPABILITIES) if capabilities is None else list(capabilities)}
        self.audits, self.failing = [], set()
        self.sources = [{'source_id': 'cron', 'state': 'measured', 'watermark': iso(NOW - 30), 'checked_at': iso(NOW - 30), 'reason_code': 'qualified'},
                        {'source_id': 'database', 'state': 'measured', 'watermark': iso(NOW - 30), 'checked_at': iso(NOW - 30), 'reason_code': 'qualified'},
                        {'source_id': 'phone_provider', 'state': 'not_applicable', 'watermark': None, 'checked_at': iso(NOW - 30), 'reason_code': 'not_configured'}]
        self.rows = {'ai_cost_actual': [aggregate(2_500_000, known=3, unknown=1)],
                     'cash_collected': [aggregate(12345, currency='USD'), aggregate(500, currency='EUR')],
                     'payment_failures': [aggregate(2)],
                     'publish_outcomes': [aggregate(12, numerator=12, denominator=12, status='verified'), aggregate(1, numerator=0, denominator=1, status='failed')],
                     'active_workspaces': [], 'paid_customers': [aggregate(7)]}
        self.instrumented = set()   # every canned metric has rows; an empty one is an uninstrumented source

    def operator(self, user, environment):
        row = self.operator_row
        return copy.deepcopy(row) if user == row['user_id'] and environment == row['environment'] else None

    def audit(self, **event):
        self.audits.append(event)

    def metric_rows(self, statement, params, limit=1000):
        if statement.metric_id in self.failing:
            raise RuntimeError('reader connection lost')
        return super().metric_rows(statement, params, limit)


class BriefStore(MemoryFounderStore):
    """The P0 in-memory founder store over a restricted control store, like PostgresFounderStore(PostgresStore)."""

    def __init__(self, control=None, **kwargs):
        super().__init__(**kwargs)
        self.store = control or ControlStore()


def observations(now=NOW):
    return {'sources_probed': True, 'sources': [{'source_id': s, 'state': 'measured', 'checked_at': now - 30, 'watermark': now - 30, 'reason_code': 'qualified'}
                                                for s in ('cron', 'database', 'control_database')],
            'publish': {'available': True, 'failed': 1, 'uncertain': 0, 'verified': 12}, 'cost': {'available': True, 'today_usd_micro': 4_200_000,
            'daily_usd_micro': [1_100_000] * 7, 'budget_stop_reached': False}, 'payments': {'available': False}}


def fallback():
    return founder_cron.briefing_receipts(observations(), NOW)


class CronPrincipalTests(unittest.TestCase):
    def test_principal_is_the_stored_founder_row_and_grants_nothing(self):
        store = ControlStore(capabilities=['control.read', 'metrics.query'])
        principal = founder_briefings.cron_principal(store, OPERATOR, 'local')
        self.assertEqual(principal['operator'], store.operator_row)
        self.assertEqual(principal['session'], {'id': None, 'environment': 'local', 'kind': 'cron'})
        for changes in ({'status': 'revoked'}, {'role': 'workspace_admin'}, {'environment': 'production'}):
            with self.subTest(changes=changes):
                other = ControlStore()
                other.operator_row.update(changes)
                self.assertIsNone(founder_briefings.cron_principal(other, OPERATOR, 'local'))
        self.assertIsNone(founder_briefings.cron_principal(store, str(uuid.uuid4()), 'local'), 'no row for another user')

        class Broken(ControlStore):
            def operator(self, user, environment):
                raise psycopg.OperationalError('server closed the connection')
        self.assertIsNone(founder_briefings.cron_principal(Broken(), OPERATOR, 'local'))


class ReceiptedFactsTests(unittest.TestCase):
    def test_every_line_comes_from_a_receipted_query_run_as_the_founder(self):
        fstore = BriefStore()
        facts, basis = founder_briefings.briefing_facts(fstore, OPERATOR, 'daily', NOW, fallback=fallback)
        store = fstore.store
        self.assertEqual(basis, {'basis': 'metric_receipts', 'receipts': len(founder_briefings.BRIEF_METRICS['daily'])})
        self.assertEqual(len(store.receipts), len(founder_briefings.BRIEF_METRICS['daily']))
        self.assertTrue(all(r['operator'] == OPERATOR and r['executionState'] == 'admitted_operational' for r in store.receipts))
        receipt_ids = {r['id'] for r in store.receipts}
        self.assertTrue(all(f['id'] in receipt_ids for f in facts), 'every fact names the receipt it came from')
        day = founder_briefings.brief_windows(NOW)['day']
        self.assertEqual((day['start'], day['end'], day['timeZone']), ('2026-09-30T04:00:00Z', '2026-10-01T04:00:00Z', live_metrics.TIME_ZONE))
        windows = {(r['normalizedQuery']['metricIds'][0], r['normalizedQuery']['interval']['start']) for r in store.receipts}
        self.assertIn(('ai_cost_actual', '2026-10-01T04:00:00Z'), windows, 'month to date starts at the local month start')
        lines = {f['label']: f for f in facts}
        self.assertEqual((lines['AI cost yesterday (actual)']['value'], lines['AI cost yesterday (actual)']['dataState'], lines['AI cost yesterday (actual)']['detail']),
                         (2_500_000, 'partial', 'unsettled_cost_rows'))
        self.assertEqual((lines['Cash collected yesterday · USD']['value'], lines['Cash collected yesterday · EUR']['currency']), (12345, 'EUR'))
        self.assertEqual((lines['Publish outcomes yesterday · verified']['value'], lines['Publish outcomes yesterday · failed']['value']), (12, 1))
        self.assertEqual((lines['Active workspaces yesterday']['value'], lines['Active workspaces yesterday']['dataState']), (None, 'unavailable'),
                         'an empty uninstrumented source is unavailable, never zero')
        sources = lines['Data sources']['value']
        self.assertTrue(sources.startswith('measured: cron, database; not_applicable: phone_provider (not_configured); unavailable: '), sources)
        self.assertIn('control_database (no_probe_recorded)', sources, 'a source never probed is unavailable, named with its reason')
        self.assertEqual(lines['Data sources']['dataState'], 'partial')
        self.assertLessEqual(len(founder_briefings.format_value('text', sources)), 400)
        self.assertEqual(store.audits, [{'request_id': store.audits[0]['request_id'], 'actor': OPERATOR, 'session': None, 'environment': 'local',
                                         'action': 'metrics.query', 'result': 'allowed', 'error_code': None}])
        brief = founder_briefings.compose_brief('daily', facts, now=NOW, time_zone='America/Indiana/Indianapolis', environment='local', basis=basis)
        self.assertEqual(brief['receipt_ids'], sorted(receipt_ids), 'founder_reports.receipt_ids is never empty when metrics exist')
        self.assertEqual(brief['coverage']['basis'], 'metric_receipts')
        self.assertIn('AI cost yesterday (actual): USD 2.50 (partial) — unsettled_cost_rows', brief['text'])
        self.assertIn('Cash collected yesterday · USD: USD 123.45 (partial)', brief['text'])
        self.assertIn('Basis: 8 receipted metric queries; days are America/Indiana/Indianapolis report days.', brief['text'])
        self.assertTrue(brief['text'].endswith(founder_briefings.CLOSING))

    def test_one_failing_metric_stays_one_unavailable_line(self):
        fstore = BriefStore()
        fstore.store.failing.add('payment_failures')
        facts, basis = founder_briefings.briefing_facts(fstore, OPERATOR, 'weekly', NOW, fallback=fallback)
        self.assertEqual(basis['basis'], 'metric_receipts')
        failed = [f for f in facts if f['metricId'] == 'payment_failures']
        self.assertEqual([(f['id'], f['dataState'], f['detail'], f['label']) for f in failed], [(None, 'unavailable', 'query_failed', 'Payment failures, last 7 days')])
        week = founder_briefings.brief_windows(NOW)['week']
        self.assertIn(('ai_cost_actual', week['start']), {(r['normalizedQuery']['metricIds'][0], r['normalizedQuery']['interval']['start']) for r in fstore.store.receipts})

    def test_capability_check_stays_intact_and_falls_back_honestly(self):
        fstore = BriefStore(ControlStore(capabilities=['control.read', 'copilot.use']))
        facts, basis = founder_briefings.briefing_facts(fstore, OPERATOR, 'daily', NOW, fallback=fallback)
        self.assertEqual(basis, {'basis': 'cron_observations', 'reason': 'metrics_query_not_granted'})
        self.assertEqual(fstore.store.receipts, [], 'no receipt is written for a founder without metrics.query')
        self.assertEqual([(a['action'], a['result'], a['error_code']) for a in fstore.store.audits], [('metrics.query', 'denied', 'SCOPE_DENIED')])
        self.assertTrue(facts and all(f['id'] is None for f in facts))
        brief = founder_briefings.compose_brief('daily', facts, now=NOW, basis=basis)
        self.assertEqual((brief['receipt_ids'], brief['coverage']['basis'], brief['coverage']['basisReason']), ([], 'cron_observations', 'metrics_query_not_granted'))
        self.assertIn('Basis: cron observations without query receipts (metrics_query_not_granted).', brief['text'])
        revoked = BriefStore(ControlStore(status='revoked'))
        self.assertEqual(founder_briefings.briefing_facts(revoked, OPERATOR, 'daily', NOW, fallback=fallback)[1], {'basis': 'cron_observations', 'reason': 'operator_not_active'})
        self.assertEqual(founder_briefings.briefing_facts(MemoryFounderStore(), OPERATOR, 'daily', NOW, fallback=fallback)[1],
                         {'basis': 'cron_observations', 'reason': 'control_store_unavailable'})

        class NoSources(ControlStore):
            def read(self, kind, identifier=None):
                raise RuntimeError('reader down')
        none = BriefStore(NoSources())
        self.assertEqual(founder_briefings.briefing_facts(none, OPERATOR, 'daily', NOW, fallback=fallback)[1], {'basis': 'cron_observations', 'reason': 'no_receipts'})

    def test_values_render_in_their_units(self):
        self.assertEqual(founder_briefings.format_value('currency_minor', 12345, 'EUR'), 'EUR 123.45')
        self.assertEqual(founder_briefings.format_value('seconds', 4210), '4,210 s')
        self.assertEqual(founder_briefings.format_value('usd_micro', 1_234_567), 'USD 1.23')
        empty = founder_briefings._result_facts({'queryReceiptId': 'r-1', 'rows': [], 'dataState': 'measured'}, 'cash_collected', 'Cash collected yesterday', ('currency',))
        self.assertEqual([(f['id'], f['value'], f['dataState']) for f in empty], [('r-1', 'none recorded', 'measured')], 'an instrumented source with no rows says so')
        with self.assertRaises(Exception):
            founder_briefings.compose_brief('daily', [], now=NOW, basis={'basis': 'model_guess'})

    def test_windows_are_report_days_across_dst_and_month_starts(self):
        spring = founder_briefings.brief_windows(utc('2026-03-09T13:00:00Z'))   # the day after the 8 March 2026 spring-forward
        self.assertEqual((spring['day']['start'], spring['day']['end']), ('2026-03-08T05:00:00Z', '2026-03-09T04:00:00Z'), 'a 23-hour local day')
        first = founder_briefings.brief_windows(utc('2026-11-01T04:00:30Z'))       # 00:00:30 local on 1 November (EDT)
        self.assertEqual((first['mtd']['start'], first['mtd']['end']), ('2026-11-01T04:00:00Z', '2026-11-01T04:01:00Z'), 'never an empty interval')


class ScheduledBriefingTests(unittest.TestCase):
    def setUp(self):
        self.notifications = FakeNotifications()
        self.service = types.SimpleNamespace(connection_factory=lambda: FakeDB(self.notifications.emitted), notifications=self.notifications, phone=None)

    def tick(self, fstore, at):
        return founder_cron.tick(self.service, {'RAFII_CONTROL_ENABLED': '1', FLAG: '1'}, fstore=fstore, calls_factory=lambda operator: None, clock=lambda: at,
                                 observe=lambda fstore, service, values, now: observations(now), lease_owner='test-cron')

    def test_cron_briefing_keeps_its_receipt_ids(self):
        fstore = BriefStore()
        schedule = founder_schedules.create_schedule(fstore, PRINCIPAL, {'kind': 'daily', 'localTime': '08:00', 'timeZone': 'America/Indiana/Indianapolis'},
                                                     now=NOW - 3600)['schedule']
        result = self.tick(fstore, schedule['nextAt'] + 20)
        delivered = result['schedules']['delivered']
        self.assertEqual(len(delivered), 1)
        self.assertEqual((delivered[0]['basis'], delivered[0]['receipts']), ('metric_receipts', len(fstore.store.receipts)))
        report = fstore.report(delivered[0]['reportId'])
        self.assertEqual(sorted(report['receipt_ids']), sorted(r['id'] for r in fstore.store.receipts))
        self.assertTrue(report['receipt_ids'])
        self.assertEqual(report['coverage']['basis'], 'metric_receipts')
        self.assertIn('Founder daily briefing', report['text'])
        self.assertEqual([e['event_type'] for e in self.notifications.emitted], ['founder.briefing_ready'])

    def test_store_without_a_receipt_path_keeps_the_p0_briefing(self):
        fstore = MemoryFounderStore()
        schedule = founder_schedules.create_schedule(fstore, PRINCIPAL, {'kind': 'daily', 'localTime': '08:00', 'timeZone': 'UTC'}, now=NOW - 7200)['schedule']
        result = self.tick(fstore, schedule['nextAt'] + 20)
        delivered = result['schedules']['delivered'][0]
        self.assertEqual((delivered['basis'], delivered['receipts']), ('cron_observations', 0))
        report = fstore.report(delivered['reportId'])
        self.assertEqual((report['receipt_ids'], report['coverage']['basisReason'], report['coverage']['dataState']), ([], 'control_store_unavailable', 'partial'))


class ReaderProjectionCostTests(unittest.TestCase):
    """observe_live: AI cost through rafii_control.business_usage_v2 (internal/test/demo and exempt rows excluded)."""

    class Store:
        environment = 'local'

        def __init__(self, rows=(), stop=False, missing=None):
            self.rows, self.stop, self.missing, self.statements = list(rows), stop, missing, []

        def metric_rows(self, statement, params, limit=1000):
            self.statements.append((statement.metric_id, statement.sql, list(params)))
            if self.missing:
                raise self.missing
            if statement.metric_id == 'founder_budget_stop':
                return [{'stop': self.stop}]
            return [dict(row) for row in self.rows]

    class Consumer:
        """The consumer connection: publish and payment counts only. Records every statement it is asked to run."""

        def __init__(self):
            self.statements = []

        def __call__(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return self

        def execute(self, sql, params=None):
            self.statements.append(sql)

        def fetchone(self):
            return (1, 0, 9) if 'publish' in self.statements[-1] else (2,)

    def observe(self, store, consumer=None):
        fstore = types.SimpleNamespace(store=store, source_health=lambda: [])
        consumer = consumer or self.Consumer()
        service = types.SimpleNamespace(connection_factory=consumer, notifications=FakeNotifications())
        return founder_cron.observe_live(fstore, service, {}, NOW), consumer

    def test_cost_is_the_activated_metric_over_the_reader_projection(self):
        rows = [{'d_window': '2026-09-24', 'value': '1000000'}, {'d_window': '2026-09-30', 'value': '3000000'}, {'d_window': '2026-10-01', 'value': '9000000'}]
        store = self.Store(rows, stop=True)
        observed, consumer = self.observe(store)
        cost = observed['cost']
        self.assertEqual((cost['available'], cost['today_usd_micro'], cost['budget_stop_reached'], cost['basis'], cost['time_zone']),
                         (True, 9_000_000, True, 'ai_cost_actual_v1_reader_projection', live_metrics.TIME_ZONE))
        self.assertEqual(cost['daily_usd_micro'], [1_000_000, 0, 0, 0, 0, 0, 3_000_000], 'the seven report days before today, oldest first; no rows is a zero day')
        metric_id, sql, params = store.statements[0]
        self.assertEqual(metric_id, 'ai_cost_actual')
        self.assertIn('FROM rafii_control.business_usage_v2 u', sql)
        self.assertIn("rafii_control.workspace_classifications c WHERE c.kind IN ('internal','test','demo')", sql)
        self.assertIn('NOT u."aiUsageExempt"', sql)
        self.assertEqual(params[:2], ['2026-09-24T04:00:00Z', '2026-10-01T12:30:01Z'])
        self.assertIn(live_metrics.TIME_ZONE, params)
        self.assertIn('rafii_control.business_budgets', store.statements[1][1])
        self.assertFalse(any('pr_usage_ledger' in sql or 'pr_budgets' in sql for sql in consumer.statements), 'cost is never read on the consumer connection')
        self.assertEqual((observed['publish']['failed'], observed['payments']['past_due_new']), (1, 2))
        from rafii_control import founder_incidents
        self.assertTrue(founder_incidents.cost_anomaly(observed, NOW)['evidence']['budgetStop'])
        finding = founder_incidents.cost_anomaly({**observed, 'cost': {**cost, 'budget_stop_reached': False}}, NOW)
        self.assertEqual((finding['severity'], finding['evidence']['basis']), ('warning', 'ai_cost_actual_v1_reader_projection'))

    def test_missing_projection_is_unobserved_not_zero(self):
        observed, _ = self.observe(self.Store(missing=psycopg.errors.UndefinedTable('relation "rafii_control.business_usage_v2" does not exist')))
        self.assertEqual(observed['cost'], {'available': False, 'reason': 'projection_unavailable'})
        observed, _ = self.observe(self.Store(missing=RuntimeError('boom')))
        self.assertEqual(observed['cost'], {'available': False, 'reason': 'projection_error', 'error': 'RuntimeError'})
        fstore = types.SimpleNamespace(source_health=lambda: [])
        service = types.SimpleNamespace(connection_factory=self.Consumer(), notifications=FakeNotifications())
        self.assertEqual(founder_cron.observe_live(fstore, service, {}, NOW)['cost'], {'available': False, 'reason': 'projection_unavailable'})
        from rafii_control import founder_incidents
        self.assertNotIn('cost_anomaly', founder_incidents.observed_detectors(founder_cron.observe_live(fstore, service, {}, NOW)),
                         'an unobserved cost never resolves an open cost episode')


if __name__ == '__main__':
    unittest.main()
