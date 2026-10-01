"""Founder revenue slice (CONTRACTS §8.A): catalog rows, fixed SQL shapes, honest states, the MRR bridge arithmetic, credits
through the wallet projection, the forecast scenario, Demo parity, the movements/invoices routes, the catalog-gated
cash_collected v2 and the MRR-recording daily snapshot. Reader statements run against a recording stub; the PG round trip
is test_founder_revenue_pg.py."""
from datetime import datetime, timedelta, timezone
import json
import unittest
import uuid

import psycopg

from rafii_control import demo_dataset, founder_cron, founder_metrics_revenue as revenue, http, live_metrics
from rafii_control.auth import ControlError
from rafii_control.founder_preview_scenarios import apply_scenario
from rafii_control.intelligence import ACTIVATED, PACK, Catalog, QueryService
from rafii_control.store import MetricStatement

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
TZ = 'America/Indiana/Indianapolis'
INTERVAL = dict(start='2026-09-01T04:00:00Z', end='2026-10-01T04:00:00Z', timeZone=TZ)
IDS = ('mrr', 'delinquent_mrr', 'mrr_movements', 'logo_churn', 'credit_grants', 'credit_consumption', 'credit_available', 'mrr_forecast')
DEMO_TOTAL = 4500 * 2900 + 4000 * 5900 + 1500 * 14900


def query(metric, group_by=(), filters=(), comparison='none', interval=INTERVAL):
    return dict(metricIds=[metric], interval=dict(interval), groupBy=list(group_by), filters=list(filters), comparison=comparison, limit=1000)


class RevenueStore:
    """Reader stub: probes answer min() per view, other statements answer canned rows by statement id; listed views are missing."""
    environment = 'local'

    def __init__(self):
        self.receipts, self.statements, self.sources = [], [], []
        self.first, self.rows, self.missing = {}, {}, set()

    def read(self, kind, identifier=None): return list(self.sources) if kind == 'sources' else []
    def receipt(self, receipt): self.receipts.append(receipt)

    def metric_rows(self, statement, params, limit=1000):
        if not isinstance(statement, MetricStatement): raise AssertionError('statements come from the slice registry')
        self.statements.append((statement.metric_id, statement.sql, list(params)))
        if any(view in statement.sql for view in self.missing): raise psycopg.errors.UndefinedTable('missing projection')
        if statement.metric_id == 'probe':
            return [dict(first=next((first for view, first in self.first.items() if f'FROM {view} ' in statement.sql + ' '), None))]
        rows = self.rows.get(statement.metric_id, [])
        if len(rows) > limit: raise ControlError('BUDGET_EXCEEDED', 400)
        return [dict(row) for row in rows]


def principal(*capabilities):
    return {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': list(capabilities or ('control.read', 'metrics.query'))},
            'session': {'environment': 'local', 'id': str(uuid.uuid4())}}


class Base(unittest.TestCase):
    def setUp(self):
        self.store = RevenueStore()
        self.service = QueryService(self.store, Catalog(), clock=lambda: NOW)
        self.principal = principal()

    def run_query(self, metric_query, mode='live', **kwargs):
        return self.service.metric_query(metric_query, self.principal, str(uuid.uuid4()), mode=mode, **kwargs)

    def instrument(self, view=revenue.EVENTS_VIEW, days=120):
        self.store.first[view] = (NOW - timedelta(days=days)).isoformat()


class CatalogAndRegistration(Base):
    def test_revenue_rows_are_activated_registered_and_sourced(self):
        rows = json.loads((PACK / 'catalogs/metrics.d/revenue.json').read_text())
        self.assertEqual([row['id'] for row in rows], list(IDS) + ['cash_collected'])
        catalog = Catalog()
        for row in rows:
            with self.subTest(metric=row['id']):
                self.assertEqual(row['status'], ACTIVATED)
                self.assertTrue(catalog.activated(row['id']))
                self.assertEqual(catalog.metrics[row['id']], row, 'the metrics.d row governs its id')
                self.assertEqual(row['activation']['definitionVersion'], 'v2' if row['id'] == 'cash_collected' else 'v1')
                self.assertTrue(live_metrics.known(row['id']))
                self.assertEqual(live_metrics.METRIC_SOURCES[row['id']], 'database')
                if row['id'] != 'cash_collected': self.assertIn(row['id'], revenue.demo_metrics.CUSTOM)   # cash keeps its P0 Demo branch
                if row['unit'] == 'currency_minor': self.assertEqual(row['currency_policy'], 'native_currency_separate')
        self.assertEqual((catalog.metrics['cash_collected']['version'], catalog.metrics['cash_collected']['source_contract']),
                         (2, 'pr_credit_orders + pr_invoices + pr_credit_subscription_grants'), 'v2 supersedes the metrics.json v1 activation')
        self.assertEqual({catalog.metrics[name]['grain'] for name in ('mrr', 'delinquent_mrr')}, {'subscription snapshot'}, 'MRR and delinquent MRR can share one query')
        route, _ = http.extension_route('/revenue/movements', 'GET')
        self.assertEqual((route[2], route[3], route[4]), ('metrics.query', 'founder_metrics_revenue', 'movements'))
        self.assertEqual(http.ControlApplication._capability('/revenue/invoices', 'GET'), 'metrics.query')
        with self.assertRaises(ControlError): self.run_query(query('mrr'))   # native currencies are never summed together

    def test_monthly_normalization_is_exact_and_rounds_half_up(self):
        self.assertEqual(revenue.monthly(2900, 'month', 1), 2900)
        self.assertEqual(revenue.monthly(34800, 'year', 1), 2900)          # annual / 12
        self.assertEqual(revenue.monthly(8700, 'month', 3), 2900)          # quarterly / 3
        self.assertEqual(revenue.monthly(18, 'year', 1), 2)                # 1.5 rounds up, as PostgreSQL round(numeric) does
        self.assertEqual(revenue.monthly(1000, 'week', 1), 4333)           # 52/12
        self.assertEqual(revenue.monthly(100, 'day', 1), 3042)             # 365/12
        sql = revenue.monthly_sql('n', 'i', 'c')
        self.assertIn("(n)::numeric * (CASE i WHEN 'week' THEN 52 WHEN 'day' THEN 365 ELSE 1 END)", sql)
        self.assertIn("((CASE i WHEN 'month' THEN 1 ELSE 12 END) * c)", sql)


class StatementShapes(Base):
    def test_statements_are_fixed_parameterised_and_exclude_fixture_and_internal_workspaces(self):
        hostile = ["x' OR 1=1 --"]
        instants = revenue._instants(INTERVAL, True)
        for metric_id in ('mrr', 'delinquent_mrr'):
            statement, params, group_by = revenue.mrr_statement(metric_id, query(metric_id, ['currency', 'plan', 'window'], [dict(dimension='plan', operator='in', values=hostile)]), instants)
            self.assertEqual(statement.sql.count('%s'), len(params))
            self.assertIn(hostile, params)
            self.assertNotIn('1=1', statement.sql)
            self.assertIn("e.provider<>'fixture'", statement.sql)
            self.assertIn("c.kind IN ('internal','test','demo')", statement.sql)
            self.assertIn('unnest(%s::timestamptz[], %s::text[])', statement.sql)
            self.assertTrue(statement.sql.endswith('LIMIT %s'))
            self.assertEqual(params[-1], live_metrics.MAX_POINTS + 1)
            self.assertEqual(("FILTER (WHERE b.kind='priced' AND b.status='past_due')" in statement.sql), metric_id == 'delinquent_mrr')
        self.assertEqual(len(instants), 30)
        self.assertEqual((instants[0][1], instants[-1][1]), ('2026-09-01', '2026-09-30'))
        self.assertEqual(instants[-1][0], datetime(2026, 10, 1, 4, tzinfo=timezone.utc))
        bridge = revenue.bridge_statement('mrr_movements')
        self.assertEqual(bridge.sql.count('%s'), len(revenue._bridge_params(INTERVAL)) + 1)
        self.assertIn("h.provider<>'fixture'", bridge.sql)
        for metric_id in ('credit_grants', 'credit_consumption'):
            statement, params, _ = revenue.credit_statement(metric_id, query(metric_id, ['plan', 'window'], [dict(dimension='plan', operator='in', values=hostile)]), INTERVAL)
            self.assertEqual(statement.sql.count('%s'), len(params))
            self.assertIn('NOT k."aiUsageExempt"', statement.sql)
            self.assertIn("c.kind IN ('internal','test','demo')", statement.sql)
        for sql, count in ((revenue.FORECAST_SQL, 5), (revenue.AVAILABLE_SQL, 2), (revenue.MOVEMENT_ROWS_SQL, 7), (revenue.MOVEMENT_EVENTS_SQL, 4), (revenue.INVOICES_SQL, 4),
                           (revenue.snapshot_insert_sql(), 2)):
            self.assertEqual(sql.count('%s'), count)
        # live_metrics.excluded() aliases the classifications as c: an outer alias c would make the exclusion compare c with itself.
        statements = [revenue.mrr_statement('mrr', query('mrr', ['currency']), instants)[0].sql, bridge.sql, revenue.FORECAST_SQL, revenue.AVAILABLE_SQL, revenue.INVOICES_SQL,
                      revenue.MOVEMENT_ROWS_SQL] + [revenue.credit_statement(name, query(name), INTERVAL)[0].sql for name in ('credit_grants', 'credit_consumption')]
        for sql in statements:
            self.assertIn('c.workspace_id::text=', sql)
            self.assertNotIn('c.workspace_id::text=c.', sql)
        with self.assertRaises(ControlError): revenue.mrr_statement('mrr', query('mrr', ['movement']), instants)


class LiveMrr(Base):
    def test_missing_projection_and_no_events_are_unavailable_never_zero(self):
        self.store.missing.add(revenue.EVENTS_VIEW)
        row = self.run_query(query('mrr', ['currency']))['rows'][0]
        self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'source_not_configured'))
        self.store.missing.clear()
        for metric_id in ('mrr', 'delinquent_mrr', 'mrr_movements'):
            row = self.run_query(query(metric_id, ['currency']))['rows'][0]
            self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'not_instrumented'), metric_id)
        self.assertEqual(self.run_query(query('logo_churn'))['rows'][0]['reason'], 'not_instrumented')

    def test_mrr_rows_carry_unknown_coverage_and_collecting_since(self):
        self.instrument()
        self.store.rows['mrr'] = [dict(d_currency='USD', value='1234500', known=40, unknown=2, paying=38, watermark='2026-09-30T10:00:00+00:00', sample_count=42),
                                  dict(d_currency='EUR', value='9900', known=1, unknown=0, paying=1, watermark='2026-09-29T10:00:00+00:00', sample_count=1)]
        result = self.run_query(query('mrr', ['currency']))
        usd, eur = result['rows']
        self.assertEqual((usd['value'], usd['currency'], usd['dataState'], usd['reason']), (1234500, 'USD', 'partial', 'subscriptions_without_priced_event'))
        self.assertEqual(usd['coverage'], dict(known=40, unknown=2, numerator=None, denominator=None))
        self.assertEqual((eur['dataState'], eur['currency'], eur['measures']), ('measured', 'EUR', {'payingSubscriptions': 1}))
        self.assertEqual(usd['collectingSince'], (NOW - timedelta(days=120)).isoformat().replace('+00:00', 'Z'))
        self.assertEqual(result['executionState'], 'admitted_operational')
        statement = next(entry for entry in self.store.statements if entry[0] == 'mrr')
        self.assertEqual(statement[2][0], [datetime(2026, 10, 1, 4, tzinfo=timezone.utc)], 'MRR at the interval end')

    def test_live_overview_mrr_tile_reads_the_slice(self):
        self.store.sources = [dict(source_id='cron', state='measured', watermark=NOW.isoformat(), checked_at=NOW.isoformat(), reason_code='qualified')]
        page = live_metrics.overview(self.principal, 'live', '30d', self.service)
        tile = next(tile for tile in page['pulse'] if tile['id'] == 'mrr')
        self.assertEqual((tile['value'], tile['dataState'], tile['reason']), (None, 'unavailable', 'not_instrumented'))
        self.instrument()
        self.store.rows['mrr'] = [dict(d_currency='USD', value=5900, known=1, unknown=0, paying=1, watermark=None, sample_count=1)]
        tile = next(tile for tile in live_metrics.overview(self.principal, 'live', '30d', self.service)['pulse'] if tile['id'] == 'mrr')
        self.assertEqual((tile['value'], tile['currency'], tile['dataState']), (5900, 'USD', 'measured'))


BRIDGE = [dict(movement='new', currency='USD', plan='Creator', opening_plan='Creator', opening=0, closing=5900, units=1, opening_units=0, closing_units=1),
          dict(movement='expansion', currency='USD', plan='Creator', opening_plan='Starter', opening=2900, closing=5900, units=1, opening_units=1, closing_units=1),
          dict(movement='churn', currency='USD', plan='Studio', opening_plan='Studio', opening=14900, closing=0, units=1, opening_units=1, closing_units=0),
          dict(movement='unchanged', currency='USD', plan='Starter', opening_plan='Starter', opening=5800, closing=5800, units=3, opening_units=2, closing_units=2),
          dict(movement='unknown', currency='USD', plan='Starter', opening_plan='Starter', opening=0, closing=0, units=1, opening_units=0, closing_units=0)]


class Bridge(Base):
    def test_insufficient_history_names_what_is_missing(self):
        self.instrument(days=10)
        row = self.run_query(query('mrr_movements', ['currency', 'movement']))['rows'][0]
        self.assertEqual((row['value'], row['dataState'], row['reason'], row['history']), (None, 'unavailable', 'insufficient_history', dict(availableDays=10, requiredDays=31)))
        self.instrument(days=45)
        old = dict(start='2026-07-01T04:00:00Z', end='2026-08-01T04:00:00Z', timeZone=TZ)
        row = self.run_query(query('logo_churn', interval=old))['rows'][0]
        self.assertEqual((row['reason'], row['history']['availableDays'], row['history']['requiredDays']), ('insufficient_history', 45, 93), 'history must reach the interval start')

    def test_bridge_rows_reconcile_exactly_and_zero_fill_segments(self):
        self.instrument()
        self.store.rows['mrr_movements'] = BRIDGE
        rows = self.run_query(query('mrr_movements', ['currency', 'movement']))['rows']
        values = {row['dimensions']['movement']: row['value'] for row in rows}
        self.assertEqual([row['dimensions']['movement'] for row in rows], list(revenue.BRIDGE_ROWS))
        self.assertEqual(values, dict(opening=23600, new=5900, expansion=3000, reactivation=0, contraction=0, churn=-14900, closing=17600))
        self.assertEqual(values['opening'] + sum(values[name] for name in revenue.MOVEMENTS), values['closing'])
        self.assertTrue(all(row['dataState'] == 'partial' and row['coverage']['unknown'] == 1 for row in rows), 'one customer with unknown MRR is excluded and counted')
        counts = {row['dimensions']['movement']: row['coverage']['known'] for row in rows}
        self.assertEqual((counts['opening'], counts['closing'], counts['churn'], counts['reactivation']), (4, 4, 1, 0))
        net = self.run_query(query('mrr_movements', ['currency']))['rows']
        self.assertEqual([(row['dimensions'], row['value']) for row in net], [({'currency': 'USD'}, -6000)])
        churn = self.run_query(query('mrr_movements', ['currency', 'movement'], [dict(dimension='movement', operator='in', values=['churn'])]))['rows']
        self.assertEqual([(row['dimensions']['movement'], row['value']) for row in churn], [('churn', -14900)])
        by_plan = self.run_query(query('mrr_movements', ['currency', 'plan', 'movement']))['rows']
        self.assertEqual(sum(row['value'] for row in by_plan if row['dimensions']['movement'] == 'closing'), 17600)

    def test_logo_churn_ratio_and_zero_denominator(self):
        self.instrument()
        self.store.rows['logo_churn'] = BRIDGE
        row = self.run_query(query('logo_churn'))['rows'][0]
        self.assertEqual((row['value'], row['coverage']['numerator'], row['coverage']['denominator'], row['unit']), (0.25, 1, 4, 'ratio'))
        by_plan = {row['dimensions']['plan']: row for row in self.run_query(query('logo_churn', ['plan']))['rows']}
        self.assertEqual((by_plan['Studio']['value'], by_plan['Starter']['value'], by_plan['Creator']['dataState']), (1.0, 0.0, 'not_applicable'))
        self.store.rows['logo_churn'] = []
        empty = self.run_query(query('logo_churn'))['rows'][0]
        self.assertEqual((empty['value'], empty['dataState'], empty['reason']), (None, 'not_applicable', 'no_opening_paid_customers'))


class Credits(Base):
    def test_credit_metrics_say_not_instrumented_while_credits_are_off(self):
        for metric_id, dims in (('credit_grants', []), ('credit_consumption', []), ('credit_available', [])):
            row = self.run_query(query(metric_id, dims))['rows'][0]
            self.assertEqual((row['value'], row['reason']), (None, 'not_instrumented'), metric_id)

    def test_grants_and_consumption_sum_ledger_entries(self):
        self.instrument(revenue.CREDITS_VIEW)
        self.store.rows['credit_grants'] = [dict(d_grant_source='subscription', value='8000000', known=1, watermark=None, sample_count=1)]
        row = self.run_query(query('credit_grants', ['grant_source']))['rows'][0]
        self.assertEqual((row['value'], row['unit'], row['dataState'], row['dimensions']), (8000000, 'millicredits', 'measured', {'grant_source': 'subscription'}))
        self.assertIn('collectingSince', row)

    def test_available_credits_use_the_wallet_projection(self):
        self.instrument(revenue.CREDITS_VIEW)
        far = (NOW + timedelta(days=30)).timestamp()
        def entry(entry_id, wid, op, reservation=None, milli=None, allocations=None, expires=None):
            return dict(id=entry_id, wid=wid, reservationId=reservation, op=op, milli=milli, grantId=None, expiresAtEpoch=expires, allocations=allocations, plan='Creator', at='2026-09-02T00:00:00+00:00')
        self.store.rows['credit_available'] = [
            entry('g1', 'w1', 'grant', milli=10000, expires=far), entry('r1', 'w1', 'reserve', 'r1', allocations=[dict(grantId='g1', milli=2000)]),
            entry('r2', 'w1', 'reserve', 'r2', allocations=[dict(grantId='g1', milli=4000)]), entry('s2', 'w1', 'settle', 'r2', allocations=[dict(grantId='g1', milli=3000)]),
            entry('s9', 'w2', 'settle', 'r9', allocations=[dict(grantId='missing', milli=5)])]
        row = self.run_query(query('credit_available'))['rows'][0]
        self.assertEqual((row['value'], row['coverage']['known'], row['coverage']['unknown'], row['dataState']), (5000, 1, 1, 'partial'))
        self.assertEqual(row['measures'], {'heldMilliCredits': 2000, 'debtMilliCredits': 0})
        statement = next(entry for entry in self.store.statements if entry[0] == 'credit_available')
        self.assertEqual(statement[2], [datetime(2026, 10, 1, 4, tzinfo=timezone.utc), revenue.CREDIT_ROW_LIMIT + 1])


class Forecast(Base):
    def test_least_squares_scenario_and_history_rule(self):
        self.assertEqual(revenue.fit_line([(0, 1000), (1, 1010), (2, 1020)]), (10.0, 1000.0))
        start = datetime(2026, 7, 1).date()
        self.store.rows['mrr_forecast'] = [dict(day=(start + timedelta(days=offset)).isoformat(), currency='USD', mrr=1000 + 10 * offset, unknown=0) for offset in range(60)]
        future = dict(start='2026-10-02T04:00:00Z', end='2026-10-05T04:00:00Z', timeZone=TZ)
        rows = self.run_query(query('mrr_forecast', ['currency', 'window'], interval=future))['rows']
        self.assertEqual([(row['dimensions']['window'], row['value']) for row in rows], [('2026-10-02', 1930), ('2026-10-03', 1940), ('2026-10-04', 1950)])
        self.assertEqual((rows[0]['measures']['basis'], rows[0]['measures']['method'], rows[0]['measures']['fitDays']), ('scenario', revenue.FORECAST_METHOD, 60))
        self.assertEqual(rows[0]['collectingSince'], '2026-07-01')
        self.store.rows['mrr_forecast'] = self.store.rows['mrr_forecast'][:30]
        short = self.run_query(query('mrr_forecast', ['currency'], interval=future))['rows'][0]
        self.assertEqual((short['value'], short['reason'], short['history']), (None, 'insufficient_history', dict(availableDays=30, requiredDays=56)))
        self.store.rows['mrr_forecast'] = []
        self.assertEqual(self.run_query(query('mrr_forecast', ['currency']))['rows'][0]['reason'], 'not_instrumented')
        compared = self.run_query(query('mrr_forecast', ['currency'], comparison='previous_equal_elapsed'))['rows'][0]
        self.assertEqual(compared['comparison']['dataState'], 'unavailable', 'a scenario has no comparison period')


class Demo(Base):
    @classmethod
    def setUpClass(cls):
        cls.data = demo_dataset.sample_data()

    def demo(self, metric_query, data=None):
        return self.run_query(metric_query, mode='demo', demo_data=data or self.data)

    def window(self, days=30):
        end = revenue.parse_stamp(self.data['asOf']) + timedelta(seconds=1)
        return dict(start=revenue.stamp(end - timedelta(days=days)), end=revenue.stamp(end), timeZone=TZ)

    def test_demo_mrr_is_the_candidate_catalog_labelled_not_active(self):
        result = self.demo(query('mrr', ['currency'], interval=self.window()))
        row = result['rows'][0]
        self.assertEqual((row['value'], row['currency'], row['dataState'], row['fixture']), (DEMO_TOTAL, 'USD', 'measured', True))
        self.assertEqual(row['value'], self.data['summary']['mrrMinor'])
        self.assertEqual(row['measures']['catalogLabel'], 'Candidate v2 catalog (not active)')
        self.assertEqual(result['executionState'], 'demo_dataset')
        plans = {row['dimensions']['plan']: row['value'] for row in self.demo(query('mrr', ['currency', 'plan'], interval=self.window()))['rows']}
        self.assertEqual(plans, {'Starter': 4500 * 2900, 'Creator': 4000 * 5900, 'Studio': 1500 * 14900})
        series = self.demo(query('mrr', ['currency', 'window'], interval=self.window(7)))['rows']
        # Seven days back from 08:00 local spans eight local days (two partial), one point per local day.
        self.assertEqual((len(series), {row['value'] for row in series}, series[-1]['dimensions']['window']), (8, {DEMO_TOTAL}, '2026-10-01'))
        zero = self.demo(query('delinquent_mrr', ['currency'], interval=self.window()))['rows']
        self.assertEqual([(row['currency'], row['value'], row['dataState'], row['sampleCount']) for row in zero], [('USD', 0, 'measured', 0)],
                         'no past_due subscription in normal operation: a measured zero for the MRR currency')

    def test_demo_payment_failure_moves_one_subscription_into_delinquent_mrr(self):
        data = demo_dataset.sample_data()
        apply_scenario(data, 'payment_failure', now=data['asOf'])
        failed = next(row for row in data['subscriptions'] if row['status'] == 'past_due')
        delinquent = self.demo(query('delinquent_mrr', ['currency'], interval=self.window()), data)['rows'][0]
        self.assertEqual(delinquent['value'], failed['amountMinor'])
        self.assertEqual(self.demo(query('mrr', ['currency'], interval=self.window()), data)['rows'][0]['value'], DEMO_TOTAL, 'past_due still counts in MRR')

    def test_demo_credits_bridge_and_forecast(self):
        grants = self.demo(query('credit_grants', ['grant_source'], interval=self.window()))['rows'][0]
        self.assertEqual((grants['value'], grants['dimensions']), ((4500 * 1000 + 4000 * 3500 + 1500 * 8000) * 1000, {'grant_source': 'subscription'}))
        available = self.demo(query('credit_available', interval=self.window()))['rows'][0]
        self.assertEqual(available['value'], sum(row['creditsRemaining'] for row in self.data['workspaces']) * 1000)
        consumed = self.demo(query('credit_consumption', ['task_type'], interval=self.window()))['rows'][0]
        self.assertEqual((consumed['dimensions'], consumed['value']), ({'task_type': 'writer'}, sum(row['creditsUsed'] for row in self.data['usage']) * 1000))
        for metric_id, dims in (('mrr_movements', ['currency', 'movement']), ('logo_churn', [])):
            row = self.demo(query(metric_id, dims, interval=self.window()))['rows'][0]
            self.assertEqual((row['value'], row['reason'], row['fixture']), (None, 'demo_not_simulated', True), metric_id)
        forecast = self.demo(query('mrr_forecast', ['currency'], interval=self.window()))['rows'][0]
        self.assertEqual((forecast['value'], forecast['measures']['basis'], forecast['measures']['catalogLabel'], forecast['fixture']), (DEMO_TOTAL, 'scenario', revenue.DEMO_CATALOG, True))

    def test_demo_overview_mrr_tile(self):
        class Service(QueryService):
            def demo_data(inner, principal): return self.data
        service = Service(RevenueStore(), Catalog(), clock=lambda: NOW)
        tile = next(tile for tile in live_metrics.overview(self.principal, 'demo', '30d', service)['pulse'] if tile['id'] == 'mrr')
        self.assertEqual((tile['value'], tile['currency'], tile['dataState']), (DEMO_TOTAL, 'USD', 'measured'))


class Routes(Base):
    def app(self, data=None):
        service = self.service
        if data is not None:
            service.demo_data = lambda principal: data
        return type('App', (), {'queries': service, 'query_period': staticmethod(http.ControlApplication.query_period)})()

    def request(self, mode='live', **params):
        return dict(method='GET', path='/revenue/movements', body={}, query={key: [value] for key, value in params.items()}, match=(), mode=mode, now=NOW.timestamp(),
                    requestId=str(uuid.uuid4()), environ={})

    def test_movement_route_states_and_rows(self):
        app = self.app()
        self.assertEqual(revenue.movements(app, self.principal, self.request(period='30d', movement='churn'))['reason'], 'not_instrumented')
        self.instrument(days=10)
        blocked = revenue.movements(app, self.principal, self.request(period='30d'))
        self.assertEqual((blocked['reason'], blocked['history'], blocked['_dataState']), ('insufficient_history', dict(availableDays=10, requiredDays=30), 'unavailable'))
        self.instrument()
        workspace = str(uuid.uuid4())
        owner = str(uuid.uuid4())
        self.store.rows['revenue_movements'] = [dict(unit=workspace, wid=workspace, owner=owner, subs=['sub_1'], currency='USD', plan='Studio', opening_status='active', closing_status='cancelled',
                                                     opening=14900, closing=0, movement='churn')]
        self.store.rows['revenue_movement_events'] = [dict(id='e1', eventId='evt_9', eventType='customer.subscription.deleted', providerSubscriptionId='sub_1', workspaceId=workspace,
                                                           eventAt='2026-09-20T00:00:00+00:00', applied=True, priorStatus='active', newStatus='cancelled', plan='Studio', unitAmountMinor=None,
                                                           quantity=None, interval=None, intervalCount=None, currency=None, discountMinor=None)]
        result = revenue.movements(app, self.principal, self.request(period='30d', movement='churn'))
        row = result['rows'][0]
        self.assertEqual((row['deltaMinor'], row['statusChange'], row['subscriptionIds'], row['customerId'], row['href']),
                         (-14900, dict(opening='active', closing='cancelled'), ['sub_1'], owner, f'/founder/customers?record={owner}'), 'Customer 360 opens by the owner')
        self.assertEqual([event['type'] for event in row['events']], ['customer.subscription.deleted'])
        statement = next(entry for entry in self.store.statements if entry[0] == 'revenue_movements')
        self.assertEqual(statement[2][-2:], [['churn'], revenue.ROUTE_LIMIT + 1])
        for bad in (dict(period='30d', movement='bogus'), dict(period='999d'), dict(start='nope', end='2026-10-01T00:00:00Z'), dict(start='2026-10-01T00:00:00Z', end='2026-09-01T00:00:00Z')):
            with self.assertRaises(ControlError): revenue.movements(app, self.principal, self.request(**bad))
        with self.assertRaises(ControlError): revenue.movements(app, principal('control.read'), self.request(period='30d'))

    def test_demo_routes(self):
        data = demo_dataset.sample_data()
        app = self.app(data)
        moved = revenue.movements(app, self.principal, self.request(mode='demo', period='30d'))
        self.assertEqual((moved['rows'], moved['reason'], moved['catalogLabel']), ([], 'demo_not_simulated', revenue.DEMO_CATALOG))
        later = (NOW + timedelta(days=400)).timestamp()   # Demo periods end at the dataset's asOf, never at wall-clock time
        listed = revenue.invoices(app, self.principal, dict(self.request(mode='demo', period='30d', status='paid'), now=later))
        self.assertEqual(listed['interval']['end'], '2026-10-01T12:00:01Z')
        self.assertEqual((len(listed['rows']), listed['truncated'], listed['_dataState']), (revenue.ROUTE_LIMIT, True, 'synthetic'))
        self.assertTrue(all(row['status'] == 'paid' and row['href'] == f"/founder/customers?record={row['customerId']}&mode=demo" for row in listed['rows']))
        with self.assertRaises(ControlError): revenue.invoices(app, self.principal, self.request(mode='demo', period='30d', status='refunded'))

    def test_live_invoice_route(self):
        app = self.app()
        self.assertEqual(revenue.invoices(app, self.principal, self.request(period='30d'))['reason'], 'not_instrumented')
        self.instrument(revenue.INVOICES_VIEW)
        self.store.rows['revenue_invoices'] = [dict(invoiceId='in_1', workspaceId=None, subscriptionId='sub_1', billingReason='subscription_cycle', periodStart=None, periodEnd=None,
                                                    amountDueMinor=5900, amountPaidMinor=0, currency='USD', status='open', livemode=True, eventAt='2026-09-20T00:00:00+00:00')]
        result = revenue.invoices(app, self.principal, self.request(period='30d', status='open'))
        self.assertEqual((result['rows'][0]['status'], result['rows'][0]['href'], result['_dataState']), ('open', None, 'measured'))
        self.assertEqual(next(entry for entry in self.store.statements if entry[0] == 'revenue_invoices')[2][2], ['open'])


class CashCollectedV2(Base):
    def tearDown(self):
        revenue.activate_cash_collected()   # back to whatever the shipped catalog governs (v2 once revenue.json carries the row)

    def test_v2_serves_only_when_the_governing_catalog_row_is_version_two(self):
        self.assertEqual(revenue.activate_cash_collected(), 2, 'metrics.d/revenue.json carries the v2 row and the catalog lets it supersede v1')
        self.assertEqual(Catalog().metrics['cash_collected'], revenue.CASH_COLLECTED_V2_ROW)
        self.assertIs(live_metrics.SPECS['cash_collected'], live_metrics.CASH_COLLECTED_V2)
        self.assertEqual(revenue.activate_cash_collected(type('Catalog', (), {'metrics': {'cash_collected': {'version': 1}}})()), 1)
        self.assertIs(live_metrics.SPECS['cash_collected'], live_metrics.CASH_COLLECTED_V1)
        self.assertEqual(revenue.activate_cash_collected(type('Catalog', (), {'metrics': {'cash_collected': revenue.CASH_COLLECTED_V2_ROW}})()), 2)
        self.assertIs(live_metrics.SPECS['cash_collected'], live_metrics.CASH_COLLECTED_V2)
        statement, params, _, _ = live_metrics.compose('cash_collected', query('cash_collected', ['currency', 'payment_type', 'window'], [dict(dimension='currency', operator='in', values=["x' --"])]))
        self.assertEqual(statement.sql.count('%s'), len(params))
        self.assertEqual(params[:6], [INTERVAL['start'], INTERVAL['end']] * 3)
        self.assertIn('FROM rafii_control.business_invoices i', statement.sql)
        self.assertIn('NOT EXISTS (SELECT 1 FROM rafii_control.business_invoices d WHERE d."invoiceId"=g."invoiceId" AND d.status=\'paid\')', statement.sql)
        self.assertIn("c.kind IN ('internal','test','demo')", statement.sql)
        row = revenue.CASH_COLLECTED_V2_ROW
        self.assertEqual((row['version'], row['activation']['definitionVersion'], row['status']), (2, 'v2', ACTIVATED))
        self.assertEqual(set(row) >= {'id', 'grain', 'unit', 'allowed_dimensions', 'currency_policy', 'activation'}, True)


class FakeCursor:
    def __init__(self, answers, fail=()):
        self.answers, self.fail, self.executed, self._pending, self.rowcount = answers, fail, [], None, 0
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._pending = None
        if any(needle in sql for needle in self.fail): raise RuntimeError('insert failed')
        self.rowcount = 3 if sql.lstrip().startswith(('WITH n AS', 'INSERT')) else 0
        for needle, rows in self.answers.items():
            if needle in sql:
                self._pending = list(rows)
                break
    def fetchone(self): return self._pending.pop(0) if self._pending else None


class FakeDb:
    def __init__(self, cursor): self._cursor, self.committed = cursor, False
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def cursor(self): return self._cursor
    def commit(self): self.committed = True


class Snapshot(unittest.TestCase):
    def snapshot(self, readiness, fail=()):
        cursor = FakeCursor({"to_regclass('public.pr_subscription_snapshots')": [('pr_subscription_snapshots',)],
                             "to_regclass('public.pr_subscription_events') IS NOT NULL": [readiness]}, fail)
        db = FakeDb(cursor)
        result = founder_cron.subscription_snapshot(type('Service', (), {'connection_factory': staticmethod(lambda: db)})(), NOW.timestamp())
        return result, cursor, db

    def test_snapshot_records_mrr_once_057_is_applied(self):
        result, cursor, db = self.snapshot((True, 4))
        self.assertEqual((result['status'], result['inserted'], result['mrr'], db.committed), ('ok', 3, True, True))
        insert = next((sql, params) for sql, params in cursor.executed if 'mrr_minor' in sql)
        self.assertEqual(insert[1], (NOW.timestamp(), '2026-10-01'))
        self.assertIn('LEFT JOIN LATERAL', insert[0])
        self.assertFalse(any(sql.startswith('INSERT INTO public.pr_subscription_snapshots(day,workspace_id,plan_terms_id,status,provider) ') for sql, _ in cursor.executed))

    def test_snapshot_falls_back_to_plan_and_status(self):
        for readiness, fail in (((True, 2), ()), ((False, 0), ()), ((True, 4), ('mrr_minor',))):
            result, cursor, _ = self.snapshot(readiness, fail)
            self.assertEqual((result['status'], result['mrr']), ('ok', False), readiness)
            self.assertTrue(any(sql.startswith('INSERT INTO public.pr_subscription_snapshots(day,workspace_id,plan_terms_id,status,provider) ') for sql, _ in cursor.executed))
            if fail: self.assertIn('ROLLBACK TO SAVEPOINT founder_snapshot_mrr', [sql for sql, _ in cursor.executed])


if __name__ == '__main__':
    unittest.main()
