"""Founder AI & API cost slice (CONTRACTS §8.B): registration, fixed statements, honest states, the P2 outcome ratio and
forecast, Demo parity and the rollup/purge cron stages — with a reader-store stub (no PostgreSQL)."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import unittest
import uuid

import psycopg

from rafii_control import demo_metrics, founder_cron, founder_metrics_ai as ai, live_metrics
from rafii_control.auth import ControlError
from rafii_control.intelligence import ACTIVATED, PACK, Catalog, QueryService
from rafii_control.store import MetricStatement

ROOT = Path(__file__).resolve().parents[2]
TZ = 'America/Indiana/Indianapolis'
INTERVAL = dict(start='2026-09-01T04:00:00Z', end='2026-10-01T04:00:00Z', timeZone=TZ)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
METRICS = ('ai_calls', 'ai_tokens', 'ai_latency', 'ai_fallback_retry_rate', 'ai_cost_per_call', 'cost_per_useful_outcome', 'ai_cost_forecast')


def query(metric, group_by=(), filters=(), comparison='none', interval=INTERVAL):
    return dict(metricIds=[metric], interval=dict(interval), groupBy=list(group_by), filters=list(filters), comparison=comparison, limit=1000)


def aggregate(value, known=1, unknown=0, numerator=None, denominator=None, watermark='2026-09-30T23:00:00+00:00', sample_count=1, **extra):
    row = dict(value=value, known=known, unknown=unknown, numerator=numerator, denominator=denominator, watermark=watermark, sample_count=sample_count)
    row.update({(key if key.startswith(('d_', 'm_')) else 'd_' + key): value for key, value in extra.items()})
    return row


class Store:
    """Reader stub: records each fixed statement, answers the collecting-since and ledger-origin probes, and raises
    UndefinedTable for a projection listed in `missing` (a source that is not configured)."""
    environment = 'local'

    def __init__(self):
        self.receipts, self.statements, self.sources = [], [], []
        self.rows, self.first, self.origin, self.missing = {}, None, None, set()

    def read(self, kind, identifier=None): return list(self.sources) if kind == 'sources' else []
    def receipt(self, receipt): self.receipts.append(receipt)

    def metric_rows(self, statement, params, limit=1000):
        if not isinstance(statement, MetricStatement): raise AssertionError('statements must come from the registry')
        self.statements.append((statement.metric_id, statement.sql, list(params)))
        if any(view in statement.sql for view in self.missing): raise psycopg.errors.UndefinedTable('missing')
        if statement.metric_id == 'probe':
            if 'business_ai_calls' in statement.sql: return [dict(first=self.first)]
            if 'business_usage_v2' in statement.sql: return [dict(first=self.origin)]
            return [dict(instrumented=False)]
        handler = self.rows.get(statement.metric_id)
        rows = handler(statement.sql, params) if callable(handler) else list(handler or [])
        aliases = re.findall(r'AS "([dm]_[A-Za-z0-9_]+)"', statement.sql)
        return [{**{alias: (0 if alias.startswith('m_') else None) for alias in aliases}, **row} for row in rows]


class Base(unittest.TestCase):
    def setUp(self):
        live_metrics.load_extensions()
        self.catalog = Catalog()
        self.store = Store()
        self.service = QueryService(self.store, self.catalog, clock=lambda: NOW)
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query']},
                          'session': {'environment': 'local', 'id': str(uuid.uuid4())}}

    def run_query(self, metric_query, mode='live', **kwargs):
        return self.service.metric_query(metric_query, self.principal, str(uuid.uuid4()), mode=mode, **kwargs)


class Registration(Base):
    def test_catalog_rows_are_activated_and_served_live_and_demo(self):
        rows = json.loads((PACK / 'catalogs/metrics.d/ai.json').read_text())
        self.assertEqual([row['id'] for row in rows], list(METRICS))
        required = {'id', 'version', 'title', 'grain', 'unit', 'definition', 'source_contract', 'allowed_dimensions', 'query_template_ref', 'default_exclusions',
                    'data_state_required', 'currency_policy', 'zero_denominator', 'refresh_target', 'limitations', 'status', 'activation'}
        for row in rows:
            with self.subTest(metric=row['id']):
                self.assertEqual(set(row), required)
                self.assertEqual(row['status'], ACTIVATED)
                self.assertTrue(self.catalog.activated(row['id']))
                self.assertTrue(live_metrics.known(row['id']))
                self.assertEqual(live_metrics.METRIC_SOURCES[row['id']], 'database')
                self.assertIn(row['id'], demo_metrics.CUSTOM)
                self.assertEqual(set(row['activation']) >= {'definitionVersion', 'liveAdapter', 'demoAdapter', 'migration', 'prd'}, True)
        # The attempt metrics share one grain, so the AI cost page can read them in one receipt.
        self.assertEqual({self.catalog.metrics[m]['grain'] for m in METRICS[:5]}, {'provider attempt'})
        self.assertEqual(self.catalog.metrics['ai_latency']['status'], ACTIVATED, 'the proposed ai_latency id is activated by the slice row')
        names = [name for name, _ in founder_cron.STAGES]
        self.assertIn('usage_rollups', names)
        self.assertIn('ai_usage_purge', names)

    def test_ledger_feature_mapping_equals_the_054_projection(self):
        sql = (ROOT / 'migrations/postriff/054_rafii_control_founder_views.sql').read_text()
        mapping = re.findall(r"when '([a-z-]+)' then '([a-z_]+)'", sql)
        self.assertEqual(tuple(mapping), ai.LEDGER_FEATURES)
        self.assertIn("ELSE 'other' END", ai.ledger_feature_sql())

    def test_views_migration_only_touches_control_objects_and_grants_no_membership(self):
        sql = (ROOT / 'migrations/postriff/064_founder_ai_views.sql').read_text().lower()
        body = '\n'.join(line.split('--', 1)[0] for line in sql.splitlines())
        self.assertNotRegex(body, r'create\s+table')
        self.assertNotRegex(body, r'grant\s+rafii_control_[a-z_]+\s+to')
        self.assertNotIn('dedupe_key', body)
        self.assertEqual(body.count('owner to rafii_control_business_projection'), 1)
        for view in ('business_ai_calls', 'business_usage_rollups', 'business_price_versions'):
            self.assertIn(f"'{view}'", body)


class Statements(Base):
    def test_every_statement_is_fixed_parameterised_half_open_and_excluding(self):
        for metric_id, spec in ai.SPECS.items():
            dims = self.catalog.metrics[metric_id]['allowed_dimensions']
            with self.subTest(metric=metric_id):
                filters = [dict(dimension=dims[0], operator='in', values=["x' OR 1=1 --"])]
                statement, params, group_by = ai.compose(metric_id, spec, query(metric_id, dims[:2] + ['window'], filters), INTERVAL)
                self.assertEqual(statement.sql.count('%s'), len(params))
                self.assertNotIn('1=1', statement.sql)
                self.assertIn(["x' OR 1=1 --"], params)
                self.assertEqual(params[:2], [INTERVAL['start'], INTERVAL['end']])
                self.assertEqual(params[-1], live_metrics.MAX_POINTS + 1)
                self.assertIn('ac.at >= %s::timestamptz AND ac.at < %s::timestamptz', statement.sql)
                self.assertIn('NOT ac."aiUsageExempt"', statement.sql)
                self.assertIn("c.kind IN ('internal','test','demo') AND c.workspace_id::text=ac.\"workspaceId\"", statement.sql)
                self.assertIn("to_char(date_trunc('day', b.at AT TIME ZONE %s),'YYYY-MM-DD')", statement.sql)
                self.assertIn(TZ, params)
                self.assertTrue(statement.sql.startswith('WITH base AS (SELECT'))
                with self.assertRaises(ControlError):
                    ai.compose(metric_id, spec, query(metric_id, ['plan']), INTERVAL)
        latency = ai.compose('ai_latency', ai.SPECS['ai_latency'], query('ai_latency', ['model']), INTERVAL)[0].sql
        self.assertIn('percentile_cont(0.95) WITHIN GROUP (ORDER BY b.latency)', latency)
        self.assertIn('percentile_cont(0.5) WITHIN GROUP (ORDER BY b.latency)', latency)
        self.assertNotIn('avg(', latency, 'percentiles are computed per group, never averaged')
        self.assertIn('ac."audioSeconds" IS NULL', latency)
        tokens = ai.compose('ai_tokens', ai.SPECS['ai_tokens'], query('ai_tokens', ['token_type']), INTERVAL)[0].sql
        for token_type in ('input', 'cached', 'output', 'reasoning'):
            self.assertIn(f"('{token_type}',", tokens)
        self.assertIn('count(*)-count(b.tokens) AS unknown', tokens)


class AttemptMetrics(Base):
    def test_not_instrumented_until_the_first_row_then_collecting_since(self):
        row = self.run_query(query('ai_calls'))['rows'][0]
        self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'not_instrumented'))
        self.assertNotIn('collectingSince', row)
        self.store.first = '2026-09-20T15:00:00+00:00'
        self.store.rows['ai_calls'] = [aggregate(42, known=42, sample_count=42, m_ok=40, m_unknownOutcome=2)]
        row = self.run_query(query('ai_calls'))['rows'][0]
        self.assertEqual((row['value'], row['dataState'], row['reason'], row['collectingSince']), (42, 'partial', 'collecting_since', '2026-09-20T15:00:00Z'))
        self.assertEqual((row['measures']['ok'], row['measures']['unknownOutcome']), (40, 2))
        later = dict(start='2026-09-25T04:00:00Z', end='2026-10-01T04:00:00Z', timeZone=TZ)
        self.assertEqual(self.run_query(query('ai_calls', interval=later))['rows'][0]['dataState'], 'measured')
        before = dict(start='2026-08-01T04:00:00Z', end='2026-09-01T04:00:00Z', timeZone=TZ)
        old = self.run_query(query('ai_calls', interval=before))['rows'][0]
        self.assertEqual((old['value'], old['dataState'], old['reason'], old['collectingSince']), (None, 'unavailable', 'not_instrumented', '2026-09-20T15:00:00Z'))

    def test_window_rows_are_partial_only_where_collection_started(self):
        self.store.first = '2026-09-20T15:00:00+00:00'
        self.store.rows['ai_calls'] = [aggregate(3, window='2026-09-20'), aggregate(5, window='2026-09-21')]
        rows = self.run_query(query('ai_calls', ['window']))['rows']
        self.assertEqual([(row['dimensions']['window'], row['dataState']) for row in rows], [('2026-09-20', 'partial'), ('2026-09-21', 'measured')])

    def test_source_not_configured_is_never_zero(self):
        self.store.missing = {'business_ai_calls'}
        for metric_id in ai.SPECS:
            row = self.run_query(query(metric_id))['rows'][0]
            self.assertEqual((row['value'], row['dataState'], row['reason']), (None, 'unavailable', 'source_not_configured'), metric_id)

    def test_tokens_unknown_types_are_coverage_never_zero(self):
        self.store.first = '2026-08-01T00:00:00+00:00'
        self.store.rows['ai_tokens'] = [aggregate(9000, known=10, unknown=0, token_type='input'), aggregate(0, known=0, unknown=10, token_type='cached')]
        rows = {row['dimensions']['token_type']: row for row in self.run_query(query('ai_tokens', ['token_type']))['rows']}
        self.assertEqual((rows['input']['value'], rows['input']['dataState']), (9000, 'measured'))
        self.assertEqual((rows['cached']['dataState'], rows['cached']['reason'], rows['cached']['coverage']['unknown']), ('partial', 'tokens_not_reported', 10))

    def test_latency_percentiles_and_small_samples(self):
        self.store.first = '2026-08-01T00:00:00+00:00'
        self.store.rows['ai_latency'] = [aggregate(2400.5, known=12, sample_count=12, model='gpt-6-sol', m_p50Ms=800, m_p95Ms=2400.5),
                                         aggregate(1900, known=300, sample_count=300, model='gpt-6-luna', m_p50Ms=600, m_p95Ms=1900)]
        rows = {row['dimensions']['model']: row for row in self.run_query(query('ai_latency', ['model']))['rows']}
        self.assertEqual((rows['gpt-6-sol']['value'], rows['gpt-6-sol']['measures'], rows['gpt-6-sol']['reason']), (2400.5, {'p50Ms': 800, 'p95Ms': 2400.5}, 'small_sample'))
        self.assertEqual((rows['gpt-6-sol']['sampleCount'], rows['gpt-6-sol']['dataState']), (12, 'measured'))
        self.assertIsNone(rows['gpt-6-luna']['reason'])
        self.store.rows['ai_latency'] = [aggregate(None, known=0, sample_count=0)]
        empty = self.run_query(query('ai_latency'))['rows'][0]
        self.assertEqual((empty['value'], empty['dataState'], empty['reason']), (None, 'not_applicable', 'no_attempts'))

    def test_ratios_and_cost_per_call(self):
        self.store.first = '2026-08-01T00:00:00+00:00'
        self.store.rows['ai_fallback_retry_rate'] = [aggregate(0.25, known=8, numerator=2, denominator=8, sample_count=8, m_fallbackAttempts=1, m_retryAttempts=1)]
        rate = self.run_query(query('ai_fallback_retry_rate'))['rows'][0]
        self.assertEqual((rate['value'], rate['coverage']['numerator'], rate['coverage']['denominator'], rate['unit']), (0.25, 2, 8, 'ratio'))
        self.store.rows['ai_fallback_retry_rate'] = [aggregate(None, known=0, numerator=0, denominator=0, sample_count=0)]
        none = self.run_query(query('ai_fallback_retry_rate'))['rows'][0]
        self.assertEqual((none['value'], none['dataState'], none['reason']), (None, 'not_applicable', 'zero_denominator'))
        self.store.rows['ai_cost_per_call'] = [aggregate('1250.5', known=4, unknown=1, numerator='5002', denominator=4, sample_count=5, m_costUsdMicro='5002', m_attempts=5)]
        cost = self.run_query(query('ai_cost_per_call'))['rows'][0]
        self.assertEqual((cost['value'], cost['dataState'], cost['reason'], cost['currency'], cost['unit']), (1250.5, 'partial', 'cost_unknown_attempts', 'USD', 'usd_micro'))
        self.store.rows['ai_cost_per_call'] = [aggregate(None, known=0, unknown=3, numerator=0, denominator=0, sample_count=3)]
        unknown = self.run_query(query('ai_cost_per_call'))['rows'][0]
        self.assertEqual((unknown['value'], unknown['dataState'], unknown['reason']), (None, 'unavailable', 'cost_unknown_attempts'))

    def test_comparison_uses_the_previous_interval(self):
        self.store.first = '2026-07-01T00:00:00+00:00'
        self.store.rows['ai_calls'] = lambda sql, params: [aggregate(10 if params[0] == INTERVAL['start'] else 4)]
        row = self.run_query(query('ai_calls', comparison='previous_equal_elapsed'))['rows'][0]
        self.assertEqual((row['value'], row['comparison']['value']), (10, 4))


class CostPerOutcome(Base):
    def outcomes(self, sql, params):
        if 'business_usage_v2' in sql: return [aggregate('600000', known=6, plan='Studio'), aggregate('100000', known=1, unknown=1, plan='Assist')]
        if 'business_time_savings' in sql: return [aggregate(12, plan='Studio'), aggregate(0, plan='Assist')]
        if 'business_learning_events' in sql: return [aggregate(30, plan='Studio')]
        raise AssertionError(sql)

    def test_cost_divided_by_the_named_outcome_proxy(self):
        self.store.rows['cost_per_useful_outcome'] = self.outcomes
        rows = {row['dimensions']['plan']: row for row in self.run_query(query('cost_per_useful_outcome', ['plan']))['rows']}
        self.assertEqual((rows['Studio']['value'], rows['Studio']['measures']['basis'], rows['Studio']['coverage']['denominator']), (50000, 'time_back_accepted_outcomes', 12))
        self.assertEqual((rows['Assist']['value'], rows['Assist']['dataState'], rows['Assist']['reason']), (None, 'not_applicable', 'zero_denominator'))
        both = self.run_query(query('cost_per_useful_outcome', ['outcome_proxy', 'plan']))['rows']
        learning = next(row for row in both if row['dimensions'] == {'outcome_proxy': 'learning_events', 'plan': 'Studio'})
        self.assertEqual((learning['value'], learning['measures']['basis']), (20000, 'learning_approvals_publishes'))
        only = self.run_query(query('cost_per_useful_outcome', ['outcome_proxy'], [dict(dimension='outcome_proxy', operator='in', values=['learning_events'])]))['rows']
        self.assertEqual({row['dimensions']['outcome_proxy'] for row in only}, {'learning_events'})

    def test_missing_learning_projection_marks_only_that_proxy(self):
        self.store.rows['cost_per_useful_outcome'] = self.outcomes
        self.store.missing = {'business_learning_events'}
        rows = self.run_query(query('cost_per_useful_outcome', ['outcome_proxy']))['rows']
        states = {row['dimensions']['outcome_proxy']: (row['dataState'], row['reason']) for row in rows}
        self.assertEqual(states['learning_events'], ('unavailable', 'source_not_configured'))
        self.assertNotEqual(states['time_back'][0], 'unavailable')
        self.store.missing = {'business_usage_v2'}
        self.assertEqual(self.run_query(query('cost_per_useful_outcome'))['rows'][0]['reason'], 'source_not_configured')


class Forecast(Base):
    def test_insufficient_history_names_what_it_has(self):
        scenario, history = ai.forecast({}, first_day=date(2026, 9, 10), today=date(2026, 10, 1), month_start=date(2026, 10, 1), month_end=date(2026, 11, 1))
        self.assertIsNone(scenario)
        self.assertEqual(history, {'availableDays': 21, 'requiredDays': 56})

    def test_ols_line_projects_the_rest_of_the_month(self):
        today = date(2026, 10, 15)
        daily = {today - timedelta(days=offset): 1000 + 10 * (56 - offset) for offset in range(1, 57)}   # rising 10/day
        daily[today] = 400                                                                                   # today so far
        scenario, history = ai.forecast(daily, first_day=date(2026, 7, 1), today=today, month_start=date(2026, 10, 1), month_end=date(2026, 11, 1))
        self.assertEqual(history['availableDays'], (today - date(2026, 7, 1)).days)
        intercept, slope = ai.fit_line([daily[today - timedelta(days=56 - x)] for x in range(56)])
        self.assertAlmostEqual(slope, 10.0)
        points = {day: (kind, value, total) for day, kind, value, total in scenario['points']}
        self.assertEqual(points[date(2026, 10, 14)][0], 'actual')
        self.assertEqual(points[today][:2], ('projection', round(intercept + slope * 56)), 'today is the larger of its actual so far and the line')
        self.assertEqual(points[date(2026, 10, 31)][1], round(intercept + slope * (56 + 16)))
        mtd = sum(daily[date(2026, 10, d)] for d in range(1, 16))
        self.assertEqual(scenario['mtd'], mtd)
        self.assertEqual(scenario['total'], points[date(2026, 10, 31)][2])
        falling = {today - timedelta(days=offset): max(0, 50 * (offset - 20)) for offset in range(1, 57)}
        floor, _ = ai.forecast(falling, first_day=date(2026, 1, 1), today=today, month_start=date(2026, 10, 1), month_end=date(2026, 11, 1))
        self.assertTrue(all(value >= 0 for _, _, value, _ in floor['points']), 'a falling line floors at zero')

    def test_live_forecast_rows_carry_scenario_budget_and_history(self):
        today = date(2026, 10, 1)
        self.store.origin = '2026-06-01T12:00:00+00:00'

        def rows(sql, params):
            if 'business_budgets' in sql: return [dict(stop='100000000', warn='60000000', status='approved')]
            return [aggregate(str(5000), window=(today - timedelta(days=offset)).isoformat()) for offset in range(1, 57)]
        self.store.rows['ai_cost_forecast'] = rows
        row = self.run_query(query('ai_cost_forecast'))['rows'][0]
        self.assertEqual(row['measures']['basis'], 'scenario')
        self.assertEqual(row['measures']['method'], ai.FORECAST_METHOD)
        self.assertEqual((row['measures']['budgetStopUsdMicro'], row['measures']['budgetStatus']), (100000000, 'approved'))
        self.assertEqual(row['value'], 5000 * 31, 'a flat 56-day line projects the same daily cost over the month')
        self.assertEqual(row['history'], {'availableDays': 122, 'requiredDays': 56})
        series = self.run_query(query('ai_cost_forecast', ['window']))['rows']
        self.assertEqual(len(series), 31)
        self.assertEqual({row['measures']['kind'] for row in series}, {'projection'})
        self.assertEqual(series[-1]['value'], 5000 * 31)
        with self.assertRaises(ControlError):
            self.run_query(query('ai_cost_forecast', comparison='previous_equal_elapsed', group_by=['window']))
        compared = self.run_query(query('ai_cost_forecast', comparison='previous_equal_elapsed'))['rows'][0]
        self.assertEqual(compared['comparison']['dataState'], 'unavailable', 'a scenario has no comparison')
        self.store.origin = '2026-09-20T00:00:00+00:00'
        short = self.run_query(query('ai_cost_forecast'))['rows'][0]
        self.assertEqual((short['value'], short['reason'], short['history']['requiredDays']), (None, 'insufficient_history', 56))


class Demo(Base):
    def test_demo_parity(self):
        from rafii_control.demo_dataset import sample_data
        data = sample_data()
        demo_interval = dict(start='2026-09-01T04:00:00Z', end='2026-10-02T04:00:00Z', timeZone=TZ)   # the Demo snapshot is 2026-10-01T12:00Z
        for metric_id in METRICS[:6]:
            row = self.run_query(query(metric_id, interval=demo_interval), mode='demo', demo_data=data)['rows'][0]
            self.assertEqual((row['value'], row['dataState'], row['reason'], row['fixture']), (None, 'unavailable', 'demo_not_simulated', True), metric_id)
        forecast = self.run_query(query('ai_cost_forecast', interval=demo_interval), mode='demo', demo_data=data)['rows'][0]
        self.assertEqual((forecast['dataState'], forecast['reason'], forecast['history']['requiredDays'], forecast['fixture']), ('unavailable', 'insufficient_history', 56, True))


class FakeCursor:
    def __init__(self, script):
        self.script, self.executed, self.rowcount = script, [], 0

    def __enter__(self): return self
    def __exit__(self, *_): return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.rowcount = self.script.get('rowcount', {}).get(sql.split()[0], 0)

    def fetchone(self):
        sql = self.executed[-1][0]
        if 'to_regclass' in sql: return tuple([self.script.get('present', True)] * sql.count('to_regclass'))
        if 'pg_try_advisory_xact_lock' in sql: return (self.script.get('lock', True),)
        if 'max(computed_at)' in sql: return (self.script.get('last'),)
        raise AssertionError(sql)


class FakeConnection:
    def __init__(self, script):
        self.cursor_ = FakeCursor(script)
        self.commits = 0

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def cursor(self): return self.cursor_
    def commit(self): self.commits += 1


class Stages(Base):
    def consumer(self, script):
        connection = FakeConnection(script)
        return type('Service', (), {'connection_factory': staticmethod(lambda: connection)})(), connection

    def test_rollups_recompute_three_local_days_idempotently(self):
        service, connection = self.consumer({'rowcount': {'DELETE': 7, 'WITH': 9}})
        now = datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc).timestamp()     # still 30 Sep in Indianapolis
        result = ai.usage_rollups_stage(None, service, {}, now)
        self.assertEqual(result['days'], ['2026-09-28', '2026-09-29', '2026-09-30'])
        self.assertEqual((result['rows'], result['replaced'], result['status'], result['timeZone']), (9, 7, 'ok', TZ))
        executed = connection.cursor_.executed
        delete = next(entry for entry in executed if entry[0].startswith('DELETE'))
        self.assertEqual(delete[1], ('2026-09-28', '2026-10-01'), 'half-open local days')
        insert = next(entry for entry in executed if entry[0].startswith('WITH'))
        self.assertEqual(insert[1]['tz'], TZ)
        self.assertIn('FULL JOIN ledger l USING (day, wid, uid, feature, model, provider, actor_class)', insert[0])
        self.assertIn("e.status IN ('failed','rate_limited','timeout')", insert[0])
        self.assertEqual(connection.commits, 1)
        json.dumps(result)

    def test_rollups_skip_when_fresh_locked_or_missing_and_never_raise(self):
        now = 1_790_000_000.0
        self.assertEqual(ai.usage_rollups_stage(None, self.consumer({'last': now - 60})[0], {}, now)['skipped'], 'fresh')
        self.assertEqual(ai.usage_rollups_stage(None, self.consumer({'lock': False})[0], {}, now)['skipped'], 'locked')
        self.assertEqual(ai.usage_rollups_stage(None, self.consumer({'present': False})[0], {}, now), {'status': 'unavailable', 'reason': 'table_missing'})
        self.assertEqual(ai.usage_rollups_stage(None, object(), {}, now), {'status': 'unavailable', 'error': 'ControlError'})
        self.assertEqual(ai.purge_stage(None, object(), {}, now), {'status': 'unavailable', 'error': 'ControlError'})

    def test_purge_keeps_400_days(self):
        service, connection = self.consumer({'rowcount': {'DELETE': 3}})
        now = 1_790_000_000.0
        result = ai.purge_stage(None, service, {}, now)
        self.assertEqual((result['status'], result['retentionDays'], result['deletedCallEvents'], result['more']), ('ok', 400, 3, False))
        events = next(entry for entry in connection.cursor_.executed if 'DELETE FROM public.pr_ai_call_events' in entry[0])
        self.assertEqual(events[1], (now - 400 * 86400, ai.PURGE_BATCH))


if __name__ == '__main__':
    unittest.main()
