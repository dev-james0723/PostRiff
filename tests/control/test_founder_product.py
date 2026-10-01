"""Founder product analytics (CONTRACTS §8.C) without PostgreSQL: catalog and registration, fixed SQL shapes, the row
contract of every metric (funnel sources and unknowns, time to value, adoption, retention cells, Time back by confidence,
hypothesis correlations), honest states, Demo parity, the learning rollup cron stage and the funnel drill-down route."""
from datetime import datetime, timezone
import json
import re
import unittest
import uuid

import psycopg

from rafii_control import demo_metrics, founder_cron, founder_metrics_product as product, http, live_metrics
from rafii_control.auth import ControlError
from rafii_control.intelligence import ACTIVATED, PACK, Catalog, QueryService

INTERVAL = dict(start='2026-08-01T04:00:00Z', end='2026-09-01T04:00:00Z', timeZone='America/Indiana/Indianapolis')
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
METRICS = ('activation_funnel', 'time_to_value', 'feature_adoption', 'retention_weekly', 'time_back', 'retention_correlations')


def query(metric, group_by=(), filters=(), comparison='none', interval=INTERVAL, limit=1000):
    return dict(metricIds=[metric], interval=dict(interval), groupBy=list(group_by), filters=list(filters), comparison=comparison, limit=limit)


class Store:
    """Reader-role stub: canned rows per statement name, UndefinedTable for 'missing' projections, every statement kept."""
    environment = 'local'

    def __init__(self):
        self.rows, self.missing, self.statements, self.receipts, self.sources = {}, set(), [], [], []

    def read(self, kind, identifier=None):
        return list(self.sources) if kind == 'sources' else []

    def receipt(self, receipt):
        self.receipts.append(receipt)

    def metric_rows(self, statement, params, limit=1000):
        self.statements.append((statement.metric_id, statement.sql, list(params)))
        if any(view in statement.sql for view in self.missing):
            raise psycopg.errors.UndefinedTable('relation does not exist')
        rows = self.rows.get(statement.metric_id, [])
        rows = rows(statement, params) if callable(rows) else rows
        if len(rows) > limit:
            raise ControlError('BUDGET_EXCEEDED', 400)
        return [dict(row) for row in rows]


def pattern(n, *, matured=True, flags=(), covered=(), cohort=None, since=None, watermark='2026-08-20T00:00:00+00:00'):
    """One aggregate funnel row: flags like {'t2','p1'} reached, covered like {2, 4} (started after that step's taxonomy)."""
    row = dict(cohort=cohort, matured=matured, n=n, watermark=watermark)
    for name, _ in product.FLAG_SOURCES:
        row[name] = name in flags
    for index in range(1, len(product.STEPS)):
        row[f'c{index}'] = index in covered
        row[f's{index}'] = (since or {}).get(index)
    return row


SINCE = {2: '2026-08-15T00:00:00+00:00', 4: '2026-07-01T00:00:00+00:00'}


class ProductMetricTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.store = Store()
        self.service = QueryService(self.store, self.catalog, clock=lambda: NOW)
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query', 'customers.read', 'workspaces.read']},
                          'session': {'environment': 'local', 'id': str(uuid.uuid4())}}

    def run_query(self, metric_query, mode='live', **kwargs):
        return self.service.metric_query(metric_query, self.principal, str(uuid.uuid4()), mode=mode, **kwargs)

    # -- registration and catalog --------------------------------------------------------------------------------------
    def test_catalog_entries_are_activated_and_registered_live_and_demo(self):
        rows = json.loads((PACK / 'catalogs/metrics.d/product.json').read_text())
        self.assertEqual([row['id'] for row in rows], list(METRICS))
        for row in rows:
            with self.subTest(metric=row['id']):
                self.assertEqual(row['status'], ACTIVATED)
                self.assertTrue(self.catalog.activated(row['id']))
                self.assertTrue(live_metrics.known(row['id']))
                self.assertEqual(live_metrics.METRIC_SOURCES[row['id']], 'database')
                self.assertIn(row['id'], demo_metrics.CUSTOM)
                self.assertEqual(set(row) >= {'id', 'version', 'title', 'grain', 'unit', 'definition', 'source_contract', 'allowed_dimensions', 'query_template_ref',
                                              'default_exclusions', 'data_state_required', 'currency_policy', 'zero_denominator', 'refresh_target', 'limitations',
                                              'status', 'activation'}, True)
                self.assertEqual(set(row['activation']) >= {'definitionVersion', 'liveAdapter', 'demoAdapter', 'migration', 'prd'}, True)
        # The structural query schema admits the new dimensions.
        self.catalog.validate('metric-query', query('activation_funnel', ['step', 'cohort']))
        self.catalog.validate('metric-query', query('retention_weekly', ['cohort', 'week']))
        self.catalog.validate('metric-query', query('time_back', ['confidence', 'task_type', 'window']))
        with self.assertRaises(ControlError):
            self.run_query(query('feature_adoption', ['week']))
        self.assertIn(('product_rollups', product.rollup_stage), founder_cron.STAGES)
        route, _ = http.extension_route('/product/funnel/stuck', 'GET')
        self.assertEqual((route[2], route[3], route[4]), ('customers.read', 'founder_metrics_product', 'stuck_workspaces'))

    def test_every_statement_is_fixed_parameterised_half_open_and_excluding(self):
        as_of = '2026-10-01T12:00:00Z'
        builders = {'funnel': lambda q, r: product._funnel_sql(q, r, INTERVAL, as_of, True), 'ttv': lambda q, r: product._ttv_sql(q, r, INTERVAL, as_of, False),
                    'adoption': lambda q, r: product._adoption_sql(q, r, INTERVAL), 'correlations': lambda q, r: product._correlation_sql(q, r, INTERVAL, as_of),
                    'retention': lambda q, r: product._retention_sql(q, INTERVAL, as_of), **{f'stuck{index}': (lambda q, r, index=index: product._stuck_sql(q, r, INTERVAL, as_of, index))
                                                                                             for index in range(1, len(product.STEPS))}}
        for name, build in builders.items():
            for rollups in (True, False):
                with self.subTest(statement=name, rollups=rollups):
                    q = product.Q()
                    sql = build(q, rollups)
                    self.assertEqual(sql.count('%s'), len(q.params))
                    self.assertTrue(sql.startswith('WITH '))
                    self.assertTrue(sql.endswith('LIMIT %s'))
                    self.assertIn("c.kind IN ('internal','test','demo')", sql)
                    self.assertIn(INTERVAL['start'], q.params)
                    self.assertNotRegex(sql, r"'20\d\d-")   # dates only ever travel as parameters
                    self.assertEqual('business_learning_rollups' in sql, rollups and name != 'retention')
                    # Every timestamp window is half-open: each lower bound `>= %s` pairs with an upper bound `< %s`
                    # (the only `<=` compares a window end with asOf, i.e. maturity).
                    self.assertEqual(sql.count('>= %s::timestamptz'), sql.count('< %s::timestamptz'))
                    self.assertGreater(sql.count('>= %s::timestamptz'), 0)
                    self.assertEqual(len(re.findall(r'<= %s::timestamptz', sql)), 0 if name in ('adoption', 'retention') else 1)
        statement, params, group_by, _ = live_metrics.compose('time_back', query('time_back', ['task_type']))
        self.assertEqual(group_by, ['confidence', 'task_type'], 'confidence is never merged')
        self.assertIn('t."occurredAt" >= %s::timestamptz AND t."occurredAt" < %s::timestamptz', statement.sql)
        self.assertEqual(statement.sql.count('%s'), len(params))

    # -- activation funnel ---------------------------------------------------------------------------------------------
    def funnel_rows(self, rows, group_by=('step',), filters=()):
        self.store.rows['activation_funnel'] = rows
        return {row['dimensions']['step']: row for row in self.run_query(query('activation_funnel', group_by, filters))['rows']}

    def test_funnel_steps_name_their_source_and_never_turn_unknown_into_not_reached(self):
        rows = self.funnel_rows([
            pattern(4, flags={'p1', 't2', 't4', 'p4', 'p6'}, covered={2, 4}, since=SINCE),
            pattern(3, flags={'p1', 'p4'}, covered={2, 4}, since=SINCE),
            pattern(3, flags=(), covered={4}, since=SINCE),
            pattern(2, matured=False, flags={'t2'}, covered={2, 4}, since=SINCE)])
        self.assertEqual(list(rows), [step for step, _, _ in product.STEPS])
        anchor = rows['workspace_created']
        self.assertEqual((anchor['value'], anchor['dataState'], anchor['measures']['immature'], anchor['measures']['source']), (10, 'measured', 2, 'workspace_start'))
        channel = rows['channel_connected']
        self.assertEqual((channel['value'], channel['coverage']['numerator'], channel['coverage']['denominator'], channel['dataState'], channel['reason']),
                         (7, 7, 10, 'partial', 'transition_proxy'))
        self.assertEqual((channel['measures']['source'], channel['measures']['proxy'], channel['measures']['proxyReached'], channel['measures']['stuckFromPrevious']),
                         ('transition_proxy', 'audit:channel.connected', 7, 3))
        self.assertAlmostEqual(channel['measures']['dropFromPrevious'], 0.3)
        voice = rows['voice_activated']
        self.assertEqual((voice['value'], voice['coverage']['denominator'], voice['coverage']['unknown'], voice['dataState'], voice['reason'], voice['collectingSince']),
                         (4, 7, 3, 'partial', 'collecting_since_after_cohort_start', '2026-08-15T00:00:00Z'))
        self.assertEqual(voice['measures']['stuckFromPrevious'], 3)
        draft = rows['draft_created']
        self.assertEqual((draft['value'], draft['dataState'], draft['reason']), (None, 'unavailable', 'not_instrumented'))
        approved = rows['draft_approved']
        self.assertEqual((approved['value'], approved['dataState'], approved['measures']['source'], approved['measures']['taxonomyReached'], approved['measures']['dropFromPrevious']),
                         (7, 'measured', 'taxonomy', 4, None))
        published = rows['publish_verified']
        self.assertEqual((published['value'], published['dataState'], published['measures']['source']), (4, 'partial', 'transition_proxy'))
        self.assertTrue(all(row['interval'] == INTERVAL and row['unit'] == 'count' for row in rows.values()))

    def test_funnel_cohort_grouping_filters_empty_and_missing_sources(self):
        rows = self.store.rows['activation_funnel'] = [pattern(2, cohort='2026-08-03', flags={'p1'}), pattern(1, cohort='2026-08-10')]
        grouped = self.run_query(query('activation_funnel', ['step', 'cohort'], [dict(dimension='step', operator='in', values=['channel_connected'])]))['rows']
        self.assertEqual([(row['dimensions'], row['value']) for row in grouped], [({'step': 'channel_connected', 'cohort': '2026-08-03'}, 2),
                                                                                  ({'step': 'channel_connected', 'cohort': '2026-08-10'}, 0)])
        del rows[:]
        empty = self.funnel_rows([])
        self.assertEqual((empty['workspace_created']['value'], empty['workspace_created']['dataState']), (0, 'measured'))
        self.assertEqual({row['dataState'] for step, row in empty.items() if step != 'workspace_created'}, {'not_applicable'})
        self.store.missing = {'business_workspace_starts'}
        missing = self.run_query(query('activation_funnel', ['step']))['rows']
        self.assertEqual([(row['value'], row['dataState'], row['reason']) for row in missing], [(None, 'unavailable', 'source_not_configured')])

    def test_a_missing_learning_rollup_falls_back_to_live_learning_events(self):
        self.store.missing = {'business_learning_rollups'}
        self.store.rows['activation_funnel'] = [pattern(1, flags={'p4'}, covered={4}, since=SINCE)]
        rows = self.funnel_rows(self.store.rows['activation_funnel'])
        self.assertEqual(rows['draft_approved']['value'], 1)
        tried = [sql for name, sql, _ in self.store.statements if name == 'activation_funnel']
        self.assertEqual(['business_learning_rollups' in sql for sql in tried], [True, False])

    # -- time to value -------------------------------------------------------------------------------------------------
    def test_time_to_value_is_a_median_with_n_quartiles_and_censored_count(self):
        self.store.rows['time_to_value'] = [dict(cohort=None, cohort_n=10, immature=2, n=6, median='3600.0', p25=1800.0, p75='7200.4', via_time_back=4, via_taxonomy=0,
                                                 via_proxy=2, watermark='2026-08-20T00:00:00+00:00')]
        row = self.run_query(query('time_to_value'))['rows'][0]
        self.assertEqual((row['value'], row['unit'], row['dataState'], row['sampleCount'], row['coverage']['numerator'], row['coverage']['denominator']),
                         (3600, 'seconds', 'measured', 6, 6, 10))
        self.assertEqual((row['measures']['noFirstValue'], row['measures']['p25'], row['measures']['p75'], row['measures']['immature']), (4, 1800, 7200, 2))
        self.assertEqual(row['measures']['firstValueSources'], {'time_back': 4, 'taxonomy': 0, 'transition_proxy': 2})
        self.store.rows['time_to_value'] = [dict(cohort=None, cohort_n=5, immature=0, n=0, median=None, p25=None, p75=None, via_time_back=0, via_taxonomy=0, via_proxy=0, watermark=None)]
        none = self.run_query(query('time_to_value'))['rows'][0]
        self.assertEqual((none['value'], none['dataState'], none['reason']), (None, 'not_applicable', 'no_first_value_in_window'))
        self.store.rows['time_to_value'] = []
        empty = self.run_query(query('time_to_value'))['rows'][0]
        self.assertEqual((empty['value'], empty['dataState'], empty['reason']), (None, 'not_applicable', 'no_matured_workspaces'))

    # -- feature adoption ----------------------------------------------------------------------------------------------
    def test_adoption_uses_the_eligible_denominator_and_says_when_collection_began(self):
        self.store.rows['feature_adoption'] = [dict(feature=None, adopters=0, taxonomy=0, proxy=0, watermark=None, eligible=20),
                                               dict(feature='voice', adopters=5, taxonomy=5, proxy=0, watermark='2026-08-20T00:00:00+00:00', eligible=20),
                                               dict(feature='review', adopters=8, taxonomy=2, proxy=7, watermark='2026-08-21T00:00:00+00:00', eligible=20),
                                               dict(feature='research', adopters=1, taxonomy=1, proxy=0, watermark='2026-08-22T00:00:00+00:00', eligible=20)]
        self.store.rows['product_since'] = [dict(event=event, since={'voice.created': '2026-07-01T00:00:00+00:00', 'review.approved': '2026-08-10T00:00:00+00:00',
                                                                     'research.completed': '2026-08-15T00:00:00+00:00'}.get(event)) for event in product.TAXONOMY_EVENTS]
        rows = {row['dimensions']['feature']: row for row in self.run_query(query('feature_adoption', ['feature']))['rows']}
        self.assertEqual(list(rows), list(product.FEATURE_IDS))
        self.assertEqual((rows['voice']['value'], rows['voice']['dataState'], rows['voice']['coverage']['denominator']), (0.25, 'measured', 20))
        self.assertEqual((rows['review']['value'], rows['review']['dataState'], rows['review']['reason'], rows['review']['measures']['source']),
                         (0.4, 'partial', 'transition_proxy', 'taxonomy+transition_proxy'))
        self.assertEqual((rows['research']['dataState'], rows['research']['reason'], rows['research']['collectingSince']),
                         ('partial', 'collecting_since_after_interval_start', '2026-08-15T00:00:00Z'))
        self.assertEqual((rows['brand']['value'], rows['brand']['dataState'], rows['brand']['reason']), (None, 'unavailable', 'not_instrumented'))
        self.assertEqual((rows['publishing']['value'], rows['publishing']['measures']['source']), (0.0, 'transition_proxy'))
        self.store.rows['feature_adoption'] = [dict(feature=None, adopters=0, taxonomy=0, proxy=0, watermark=None, eligible=0)]
        nobody = self.run_query(query('feature_adoption', ['feature'], [dict(dimension='feature', operator='eq', values=['voice'])]))['rows']
        self.assertEqual([(row['dimensions'], row['dataState'], row['reason']) for row in nobody], [({'feature': 'voice'}, 'not_applicable', 'no_active_workspaces')])

    # -- retention -----------------------------------------------------------------------------------------------------
    def test_retention_returns_matured_cells_with_n_and_d_and_grey_cells_without_a_value(self):
        self.store.rows['product_history'] = [dict(first='2026-01-01T00:00:00+00:00')]
        self.store.rows['retention_weekly'] = [dict(cohort='2026-08-03', week=None, n=10, watermark=None), dict(cohort='2026-08-03', week=0, n=6, watermark='2026-08-05T00:00:00+00:00'),
                                               dict(cohort='2026-08-03', week=1, n=4, watermark='2026-08-12T00:00:00+00:00'), dict(cohort='2026-09-21', week=None, n=5, watermark=None),
                                               dict(cohort='2026-09-21', week=0, n=3, watermark='2026-09-22T00:00:00+00:00')]
        result = self.run_query(query('retention_weekly', ['cohort', 'week'], interval=dict(INTERVAL, end='2026-10-01T04:00:00Z')))
        cells = {(row['dimensions']['cohort'], row['dimensions']['week']): row for row in result['rows']}
        self.assertEqual(len(cells), 2 * (product.RETENTION_WEEKS + 1))
        first = cells[('2026-08-03', 0)]
        self.assertEqual((first['value'], first['coverage']['numerator'], first['coverage']['denominator'], first['dataState']), (0.6, 6, 10, 'measured'))
        self.assertEqual((cells[('2026-08-03', 2)]['value'], cells[('2026-08-03', 2)]['dataState']), (0.0, 'measured'), 'a matured week without activity is a measured zero')
        self.assertEqual((cells[('2026-08-03', 7)]['dataState'], cells[('2026-08-03', 8)]['dataState'], cells[('2026-08-03', 8)]['reason']), ('measured', 'not_applicable', 'cell_not_matured'))
        self.assertIsNone(cells[('2026-08-03', 8)]['value'])
        self.assertEqual((cells[('2026-09-21', 0)]['value'], cells[('2026-09-21', 1)]['reason']), (0.6, 'cell_not_matured'))
        self.assertEqual(result['rows'][0].get('comparison'), None)
        self.store.rows['product_history'] = [dict(first='2026-09-01T00:00:00+00:00')]
        early = self.run_query(query('retention_weekly', ['cohort', 'week']))['rows']
        self.assertEqual([(row['value'], row['dataState'], row['reason'], row['history']) for row in early], [(None, 'unavailable', 'insufficient_history', {'availableDays': 30, 'requiredDays': 56})])
        with self.assertRaises(ControlError):
            self.run_query(query('retention_weekly', ['cohort'], comparison='cohort_age_aligned'))

    # -- Time back -----------------------------------------------------------------------------------------------------
    def test_time_back_keeps_confidence_apart(self):
        self.store.rows['time_back'] = [dict(d_confidence='estimated', value='1200', known=3, unknown=0, numerator=None, denominator=None, watermark='2026-08-30T00:00:00+00:00', sample_count=3),
                                        dict(d_confidence='measured', value='300', known=1, unknown=0, numerator=None, denominator=None, watermark='2026-08-31T00:00:00+00:00', sample_count=1)]
        rows = self.run_query(query('time_back'))['rows']
        self.assertEqual([(row['dimensions'], row['value'], row['unit'], row['dataState']) for row in rows],
                         [({'confidence': 'estimated'}, 1200, 'seconds', 'measured'), ({'confidence': 'measured'}, 300, 'seconds', 'measured')])
        self.assertIn('rafii_control.business_time_savings t', self.store.statements[-1][1])

    # -- correlations ----------------------------------------------------------------------------------------------------
    def test_correlations_are_hypotheses_with_n_and_suppress_small_groups(self):
        self.store.rows['product_history'] = [dict(first='2026-01-01T00:00:00+00:00')]
        self.store.rows['retention_correlations'] = [
            dict(feature='voice', since='2026-01-10T00:00:00+00:00', population=40, adopters=15, adopters_retained=9, non_adopters=25, non_adopters_retained=10),
            dict(feature='review', since=None, population=30, adopters=5, adopters_retained=4, non_adopters=25, non_adopters_retained=10),
            dict(feature='quick_start', since='2026-09-20T00:00:00+00:00', population=0, adopters=0, adopters_retained=0, non_adopters=0, non_adopters_retained=0)]
        rows = {row['dimensions']['feature']: row for row in self.run_query(query('retention_correlations', ['feature']))['rows']}
        voice = rows['voice']
        self.assertEqual((voice['value'], voice['dataState'], voice['coverage']['numerator'], voice['coverage']['denominator']), (0.6, 'measured', 9, 15))
        self.assertEqual((voice['measures']['basis'], voice['measures']['nonAdopters'], voice['measures']['nonAdopterShare']), ('hypothesis', 25, 0.4))
        self.assertAlmostEqual(voice['measures']['difference'], 0.2)
        self.assertEqual((rows['review']['value'], rows['review']['dataState'], rows['review']['reason']), (None, 'suppressed', 'sample_too_small'))
        self.assertEqual((rows['quick_start']['dataState'], rows['quick_start']['reason'], rows['quick_start']['history']['requiredDays']),
                         ('unavailable', 'insufficient_history', 56))
        self.assertEqual((rows['brand']['reason'], rows['brand']['measures']['basis']), ('not_instrumented', 'hypothesis'))
        self.assertTrue(all(row['measures']['basis'] == 'hypothesis' for row in rows.values()))
        self.store.rows['product_history'] = [dict(first='2026-09-15T00:00:00+00:00')]
        early = self.run_query(query('retention_correlations', ['feature']))['rows']
        self.assertEqual([(row['reason'], row['measures']['basis']) for row in early], [('insufficient_history', 'hypothesis')])

    # -- Demo parity ---------------------------------------------------------------------------------------------------
    def test_demo_computes_the_anchor_and_says_the_rest_is_not_simulated(self):
        data = dict(mode='demo', asOf='2026-10-01T12:00:00Z', schemaVersion='demo', manifest={'seed': 's'}, receipt={'id': 'demo-receipt'},
                    workspaces=[dict(id='workspace-1', createdAt='2026-08-05T09:00:00Z'), dict(id='workspace-2', createdAt='2026-08-20T09:00:00Z'),
                                dict(id='workspace-3', createdAt='2026-09-25T09:00:00Z'), dict(id='workspace-4', createdAt='2025-01-01T09:00:00Z')])
        funnel = self.run_query(query('activation_funnel', ['step']), mode='demo', demo_data=data)
        self.assertEqual(funnel['executionState'], 'demo_dataset')
        rows = {row['dimensions']['step']: row for row in funnel['rows']}
        self.assertEqual((rows['workspace_created']['value'], rows['workspace_created']['fixture']), (2, True))
        self.assertEqual({row['reason'] for step, row in rows.items() if step != 'workspace_created'}, {'demo_not_simulated'})
        for metric in METRICS[1:]:
            with self.subTest(metric=metric):
                group = {'feature_adoption': ['feature'], 'retention_correlations': ['feature'], 'retention_weekly': ['cohort', 'week']}.get(metric, [])
                result = self.run_query(query(metric, group), mode='demo', demo_data=data)
                self.assertEqual([(row['value'], row['dataState'], row['reason']) for row in result['rows']], [(None, 'unavailable', 'demo_not_simulated')])
        correlations = self.run_query(query('retention_correlations', ['feature']), mode='demo', demo_data=data)['rows'][0]
        self.assertEqual(correlations['measures'], {'basis': 'hypothesis'})


class RollupStageTests(unittest.TestCase):
    class Connection:
        def __init__(self, table=True, last=None, latest=None):
            self.table, self.last, self.latest, self.statements, self.committed, self.rowcount = table, last, latest, [], False, 3
            self.result = None

        def __enter__(self): return self
        def __exit__(self, *_): return False
        def cursor(self): return self
        def commit(self): self.committed = True

        def execute(self, sql, params=None):
            self.statements.append((' '.join(sql.split()), params))
            if 'to_regclass' in sql: self.result = ('public.pr_learning_daily_rollups' if self.table else None,)
            elif 'max(computed_at)' in sql: self.result = (self.last, self.latest)
            else: self.result = None

        def fetchone(self): return self.result

    def stage(self, connection, now=NOW.timestamp()):
        return product.rollup_stage(None, type('Service', (), {'connection_factory': staticmethod(lambda: connection)})(), {}, now)

    def test_backfills_then_recomputes_recent_days_idempotently_and_purges(self):
        empty = self.Connection()
        summary = self.stage(empty)
        self.assertEqual((summary['status'], summary['from'], summary['upserted']), ('ok', '2026-04-03', 3), 'first run: the whole 180-day TTL window')
        insert = next(params for sql, params in empty.statements if sql.startswith('INSERT INTO public.pr_learning_daily_rollups'))
        self.assertEqual(insert[0], live_metrics.TIME_ZONE)
        self.assertEqual(insert[1].date().isoformat(), summary['from'])
        self.assertEqual((NOW.date() - insert[1].date()).days, product.BACKFILL_DAYS)
        self.assertEqual(set(insert[2]), set(product.ROLLUP_KINDS))
        self.assertIn('ON CONFLICT (day, workspace_id, kind) DO UPDATE', next(sql for sql, _ in empty.statements if sql.startswith('INSERT')))
        self.assertTrue(any(sql.startswith('DELETE FROM public.pr_learning_daily_rollups WHERE expires_at <') for sql, _ in empty.statements))
        self.assertTrue(empty.committed)
        recent = self.Connection(last=NOW.timestamp() - 7200, latest=datetime(2026, 9, 30).date())
        summary = self.stage(recent)
        self.assertEqual(summary['from'], '2026-09-29', 'the last three local days (or from the latest rolled day if older)')
        stale = self.Connection(last=NOW.timestamp() - 7200, latest=datetime(2026, 9, 20).date())
        self.assertEqual(self.stage(stale)['from'], '2026-09-20', 'a gap since the latest rolled day is recomputed')
        fresh = self.Connection(last=NOW.timestamp() - 60, latest=datetime(2026, 10, 1).date())
        self.assertEqual(self.stage(fresh), {'status': 'ok', 'skipped': 'fresh'})
        self.assertFalse(any(sql.startswith('INSERT') for sql, _ in fresh.statements))
        self.assertEqual(self.stage(self.Connection(table=False)), {'status': 'unavailable', 'reason': 'table_missing'})
        self.assertEqual(product.rollup_stage(None, object(), {}, NOW.timestamp()), {'status': 'unavailable', 'reason': 'consumer_connection_missing'})


class StuckRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.service = QueryService(self.store, Catalog(), clock=lambda: NOW)
        self.app = type('App', (), {'queries': self.service})()
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query', 'customers.read', 'workspaces.read']},
                          'session': {'environment': 'local', 'id': str(uuid.uuid4())}}

    def call(self, mode='live', **params):
        values = {'step': 'voice_activated', 'start': INTERVAL['start'], 'end': INTERVAL['end'], **params}
        return product.stuck_workspaces(self.app, self.principal, dict(mode=mode, query={key: [value] for key, value in values.items()}))

    def test_lists_workspaces_stuck_before_a_step_with_names_and_bounds(self):
        self.store.rows['activation_funnel.stuck'] = [dict(wid=f'w{i}', started='2026-08-0%dT10:00:00+00:00' % (i + 1)) for i in range(3)]
        self.store.rows['activation_funnel.stuck_names'] = [dict(id='w0', name='Fern Studio', plan='Studio', status='active')]
        result = self.call()
        self.assertEqual((result['step'], result['previousStep'], result['truncated'], result['_dataState']), ('voice_activated', 'channel_connected', False, 'partial'))
        self.assertEqual(result['rows'][0], dict(workspaceId='w0', name='Fern Studio', plan='Studio', status='active', createdAt='2026-08-01T10:00:00Z'))
        sql = next(sql for name, sql, _ in self.store.statements if name == 'activation_funnel.stuck')
        self.assertIn('AND NOT (w.t2) AND coalesce(w.started >= since.s2, false)', sql)
        self.store.rows['activation_funnel.stuck'] = [dict(wid=f'w{i}', started='2026-08-01T10:00:00+00:00') for i in range(product.STUCK_LIMIT + 1)]
        many = self.call(step='draft_created')
        self.assertEqual((len(many['rows']), many['truncated'], many['_dataState']), (product.STUCK_LIMIT, True, 'measured'))

    def test_validation_capabilities_demo_and_missing_sources(self):
        for bad in (dict(step='workspace_created'), dict(step='nope'), dict(start='2026-09-01T00:00:00Z', end='2026-08-01T00:00:00Z'), dict(start='yesterday'),
                    dict(start='2025-01-01T00:00:00Z', end='2026-09-01T00:00:00Z'), dict(timeZone='Mars/Base')):
            with self.subTest(params=bad), self.assertRaises(ControlError):
                self.call(**bad)
        self.principal['operator']['capabilities'].remove('workspaces.read')
        with self.assertRaises(ControlError):
            self.call()
        demo_data = dict(mode='demo', asOf='2026-10-01T12:00:00Z', receipt={'id': 'demo-r'})
        self.service.demo_data = lambda principal: demo_data
        demo = self.call(mode='demo')
        self.assertEqual((demo['rows'], demo['reason'], demo['_dataState'], demo['_receiptIds']), ([], 'demo_not_simulated', 'unavailable', ['demo-r']))
        self.principal['operator']['capabilities'].append('workspaces.read')
        self.store.missing = {'business_product_events'}
        missing = self.call()
        self.assertEqual((missing['rows'], missing['reason'], missing['_dataState']), ([], 'source_not_configured', 'unavailable'))


if __name__ == '__main__':
    unittest.main()
