"""Migrations 058 + 064 on a disposable PostgreSQL: service-only tables, the price seed, the write helper's savepoint against a
real missing table, Live metric round trips through the reader projections, and the rollup and purge cron stages.

Skipped without RAFII_CONTROL_TEST_DSN. The harness applies 058 and 064 (twice) after 054; see scripts/rafii_control_pg.py.
"""
import os
import time
import unittest
import uuid
from unittest import mock

import psycopg

from postriff_phase2 import ai_call_events
from rafii_control import founder_metrics_ai as ai
from rafii_control.auth import Boundary, Config, VerifiedIdentity, CAPABILITIES
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

TZ = 'America/Indiana/Indianapolis'
MAY = dict(start='2026-05-01T04:00:00Z', end='2026-06-01T04:00:00Z', timeZone=TZ)
TABLES = ('pr_ai_call_events', 'pr_ai_call_settlements', 'pr_price_versions', 'pr_usage_rollups')
VIEWS = ('business_ai_calls', 'business_usage_rollups', 'business_price_versions')


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderAiMigrationTests(unittest.TestCase):
    def connect(self, role=None, autocommit=True):
        con = psycopg.connect(self.dsn, autocommit=autocommit, prepare_threshold=None)
        if role: con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        owner = self.connect()
        if owner.execute("SELECT to_regclass('rafii_control.business_ai_calls') IS NULL").fetchone()[0]:
            self.skipTest('migration 064 not applied by this harness')
        ai_call_events._STATE.update(disabled_until=0.0, logged=False)
        self.addCleanup(ai_call_events._STATE.update, disabled_until=0.0, logged=False)
        self.user, self.other, self.exempt = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)', (self.user, self.other))
        self.workspace = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0])
        self.internal = str(owner.execute("SELECT public.pr_bootstrap(%s,'assist')", (self.other,)).fetchone()[0])
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)", (self.user, list(CAPABILITIES)))
        owner.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,environment) VALUES(%s,'internal','founder ops test','local') "
                      "ON CONFLICT (workspace_id) DO UPDATE SET kind='internal'", (self.internal,))

    def tearDown(self):
        import hashlib
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.request_budgets WHERE bucket=%s', (hashlib.sha256(b'exchange:global').hexdigest(),))
            for workspace in (getattr(self, 'workspace', None), getattr(self, 'internal', None)):
                if workspace:
                    for table in ('pr_ai_call_events', 'pr_usage_rollups', 'pr_usage_ledger', 'pr_time_savings_ledger'):
                        con.execute(f'DELETE FROM public.{table} WHERE workspace_id=%s', (workspace,))
                    con.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,))
            con.execute("DELETE FROM public.pr_ai_call_events WHERE workspace_id IS NULL AND feature='pgtest'")

    # --- helpers ------------------------------------------------------------------------------------------------------------
    def record(self, workspace, attempts, user=None, feature='agent'):
        with psycopg.connect(self.dsn, prepare_threshold=None) as con, con.cursor() as cur:
            written = ai_call_events.write_attempts({'workspace_id': workspace, 'user_id': user or self.user, 'feature': feature}, attempts, cursor=cur)
            con.commit()
        return written

    def seed(self):
        """Customer attempts in May (A–D), an exempt user's and an internal workspace's (excluded), and an April row in the
        internal workspace so collection started before May."""
        base = dict(provider='openai', model='gpt-6-sol', route='primary', attempt_no=1)
        self.assertEqual(self.record(self.workspace, [
            {**base, 'physical_attempt_id': 'a', 'status': 'ok', 'latency_ms': 100, 'input_tokens': 1000, 'cached_input_tokens': 200, 'output_tokens': 300, 'reasoning_tokens': 50,
             'cost_usd_micro': 5400, 'cost_source': 'table:' + ai_call_events.AGENT_V2, 'started_at': 1778414400.0},                       # 2026-05-10T12:00Z
            {**base, 'physical_attempt_id': 'b', 'status': 'ok', 'latency_ms': 300, 'input_tokens': 500, 'output_tokens': 100, 'cost_usd_micro': 2000,
             'cost_source': 'gateway', 'started_at': 1778500800.0},                                                                        # 2026-05-11T12:00Z
            {**base, 'physical_attempt_id': 'c', 'model': 'gpt-6-luna', 'status': 'rate_limited', 'http_status': 429, 'latency_ms': 20, 'input_tokens': 0, 'cached_input_tokens': 0,
             'output_tokens': 0, 'reasoning_tokens': 0, 'cost_usd_micro': 0, 'cost_source': 'provider', 'started_at': 1778504400.0},
            {**base, 'physical_attempt_id': 'd', 'route': 'fallback', 'attempt_no': 2, 'status': 'ok', 'latency_ms': 500, 'started_at': 1778587200.0},  # 2026-05-12T12:00Z
        ]), 4)
        with mock.patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': self.exempt}):
            self.record(self.workspace, [{**base, 'physical_attempt_id': 'e', 'status': 'ok', 'latency_ms': 9999, 'cost_usd_micro': 99999, 'cost_source': 'gateway',
                                          'started_at': 1778500800.0}], user=self.exempt)
        self.record(self.internal, [{**base, 'physical_attempt_id': 'f', 'status': 'ok', 'latency_ms': 7777, 'cost_usd_micro': 77777, 'cost_source': 'gateway',
                                     'started_at': 1778500800.0},
                                    {**base, 'physical_attempt_id': 'g', 'status': 'ok', 'latency_ms': 1, 'started_at': 1775044800.0}], user=self.other)   # 2026-04-01

    def live_service(self):
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), store, lambda token: VerifiedIdentity(self.user, 'aal2', 'synthetic-upstream-' + self.user, time.time()))
        token, _ = boundary.exchange('synthetic-identity', 'http://localhost:4449')
        return QueryService(store), boundary.authorize(token, 'metrics.query')

    def metric(self, service, principal, metric_id, group_by=(), interval=MAY, filters=()):
        query = dict(metricIds=[metric_id], interval=interval, groupBy=list(group_by), filters=list(filters), comparison='none', limit=1000)
        return service.metric_query(query, principal, str(uuid.uuid4()))['rows']

    # --- schema -------------------------------------------------------------------------------------------------------------
    def test_tables_are_service_only_with_forced_rls_and_the_seed_is_present(self):
        owner = self.connect()
        for table in TABLES:
            with self.subTest(table=table):
                flags = owner.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='public' AND relname=%s",
                                      (table,)).fetchone()
                self.assertEqual(tuple(flags), (True, True))
                self.assertEqual(owner.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename=%s AND policyname='service_only'", (table,)).fetchone()[0], 1)
                for role in ('anon', 'authenticated', 'rafii_control_reader', 'rafii_control_session'):
                    self.assertFalse(owner.execute('SELECT has_table_privilege(%s, %s, %s)', (role, 'public.' + table, 'SELECT')).fetchone()[0], role)
                self.assertTrue(owner.execute("SELECT has_table_privilege('service_role', %s, 'INSERT')", ('public.' + table,)).fetchone()[0])
        versions = {row[0] for row in owner.execute('SELECT version FROM public.pr_price_versions').fetchall()}
        self.assertEqual(versions, set(ai_call_events.PRICE_VERSIONS), 'seeded once although 058 was applied twice')
        with self.assertRaises(psycopg.errors.CheckViolation):
            owner.execute("INSERT INTO public.pr_ai_call_events(feature,provider,model,cost_usd_micro,cost_source,status,dedupe_key) VALUES('pgtest','x','m',5,'unknown','ok',repeat('a',64))")

    def test_views_are_projection_owned_column_bounded_and_reader_only(self):
        owner = self.connect()
        for view in VIEWS:
            with self.subTest(view=view):
                row = owner.execute("SELECT pg_get_userbyid(c.relowner), c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' "
                                    "AND c.relname=%s AND c.relkind='v'", (view,)).fetchone()
                self.assertEqual(row[0], 'rafii_control_business_projection')
                self.assertIn('security_barrier=true', row[1])
        columns = {row[0] for row in owner.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='rafii_control' AND table_name='business_ai_calls'").fetchall()}
        self.assertFalse(columns & {'dedupe_key', 'dedupeKey', 'physicalAttemptId'})
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',false)")
        for view in VIEWS:
            reader.execute(f'SELECT * FROM rafii_control.{view} LIMIT 1').fetchall()
        self.assertEqual(reader.execute('SELECT count(*) FROM rafii_control.business_price_versions').fetchone()[0], 4)
        for statement in ('SELECT * FROM public.pr_ai_call_events', 'SELECT * FROM public.pr_usage_rollups'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute(statement)
        for role in ('anon', 'authenticated', 'service_role'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.connect(role).execute('SELECT * FROM rafii_control.business_ai_calls')

    # --- the write helper on a real connection --------------------------------------------------------------------------------
    def test_missing_table_rolls_back_only_the_savepoint_and_backs_off(self):
        key = 'pgtest:' + uuid.uuid4().hex
        con = psycopg.connect(self.dsn, prepare_threshold=None)
        try:
            with con.cursor() as cur:
                cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,cost_state,idempotency_key,estimated_usd_micro) VALUES(%s,'reserve','text_model','estimated',%s,10)",
                            (self.workspace, key))
                cur.execute('ALTER TABLE public.pr_ai_call_events RENAME TO pr_ai_call_events_hidden')
                with self.assertLogs('postriff.ai_call_events', 'WARNING') as logged:
                    self.assertEqual(ai_call_events.write_attempts({'workspace_id': self.workspace, 'feature': 'agent'}, [{'status': 'ok', 'model': 'm'}], cursor=cur), 0)
                cur.execute('ALTER TABLE public.pr_ai_call_events_hidden RENAME TO pr_ai_call_events')
                cur.execute("UPDATE public.pr_usage_ledger SET meta='{}'::jsonb WHERE idempotency_key=%s", (key,))   # the transaction is still usable
            con.commit()
        finally:
            con.rollback()
            con.close()
        self.assertIn('UndefinedTable', logged.output[0])
        self.assertFalse(ai_call_events.installed())
        owner = self.connect()
        self.assertEqual(owner.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE idempotency_key=%s', (key,)).fetchone()[0], 1, 'the ledger write committed')
        self.assertIsNotNone(owner.execute("SELECT to_regclass('public.pr_ai_call_events')").fetchone()[0])
        ai_call_events._STATE.update(disabled_until=0.0, logged=False)
        authenticated = psycopg.connect(self.dsn, prepare_threshold=None)
        try:
            with authenticated.cursor() as cur:
                cur.execute('SET LOCAL ROLE authenticated')
                with self.assertLogs('postriff.ai_call_events', 'WARNING'):
                    self.assertEqual(ai_call_events.write_attempts({'feature': 'pgtest'}, [{'status': 'ok', 'model': 'm'}], cursor=cur), 0)
                cur.execute('SELECT 1')
        finally:
            authenticated.rollback()
            authenticated.close()

    def test_recording_twice_is_one_row_and_a_late_cost_settles_in_the_sidecar(self):
        attempt = {'physical_attempt_id': 'phone-live:1', 'provider': 'openai', 'model': 'gpt-live-1', 'status': 'unknown', 'started_at': 1778500800.0}
        self.assertEqual(self.record(self.workspace, [attempt], feature='phone'), 1)
        self.assertEqual(self.record(self.workspace, [{**attempt, 'status': 'ok', 'cost_usd_micro': 75000, 'cost_source': 'table:' + ai_call_events.MEDIA_CONSTANTS,
                                                       'audio_seconds': 90}], feature='phone'), 0)
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',false)")
        rows = reader.execute('SELECT "costUsdMicro","costSource","lateSettled","audioSeconds",status FROM rafii_control.business_ai_calls WHERE "workspaceId"=%s', (self.workspace,)).fetchall()
        self.assertEqual([tuple(row) for row in rows], [(75000, 'table:' + ai_call_events.MEDIA_CONSTANTS, True, 90, 'unknown')])

    # --- Live metrics through the reader ------------------------------------------------------------------------------------
    def test_live_attempt_metrics_exclude_exempt_and_internal_and_never_average_percentiles(self):
        self.seed()
        service, principal = self.live_service()
        [calls] = self.metric(service, principal, 'ai_calls')
        self.assertEqual((calls['value'], calls['dataState'], calls['collectingSince']), (4, 'measured', '2026-04-01T12:00:00Z'))
        self.assertEqual((calls['measures']['ok'], calls['measures']['rateLimited']), (3, 1))
        tokens = {row['dimensions']['token_type']: row for row in self.metric(service, principal, 'ai_tokens', ['token_type'])}
        self.assertEqual((tokens['input']['value'], tokens['input']['coverage']['unknown'], tokens['input']['dataState']), (1300, 1, 'partial'))
        self.assertEqual((tokens['cached']['value'], tokens['cached']['coverage']['unknown']), (200, 2))
        self.assertEqual((tokens['output']['value'], tokens['reasoning']['value']), (350, 50))
        [latency] = self.metric(service, principal, 'ai_latency')
        self.assertAlmostEqual(latency['value'], 470.0)
        self.assertAlmostEqual(latency['measures']['p50Ms'], 200.0)
        self.assertEqual((latency['sampleCount'], latency['reason']), (4, 'small_sample'))
        [rate] = self.metric(service, principal, 'ai_fallback_retry_rate')
        self.assertEqual((rate['value'], rate['measures']['fallbackAttempts'], rate['measures']['retryAttempts']), (0.25, 1, 1))
        [cost] = self.metric(service, principal, 'ai_cost_per_call')
        self.assertAlmostEqual(cost['value'], 7400 / 3)
        self.assertEqual((cost['coverage']['known'], cost['coverage']['unknown'], cost['dataState']), (3, 1, 'partial'))
        by_route = {row['dimensions']['route']: row['value'] for row in self.metric(service, principal, 'ai_calls', ['route', 'window'])}
        self.assertEqual(by_route.get('fallback'), 1)
        by_basis = {row['dimensions']['cost_basis']: row['value'] for row in self.metric(service, principal, 'ai_calls', ['cost_basis'])}
        self.assertEqual(by_basis, {'price_table': 1, 'reported': 2, 'unknown': 1})
        early = dict(start='2026-03-01T05:00:00Z', end='2026-04-15T04:00:00Z', timeZone=TZ)
        self.assertEqual(self.metric(service, principal, 'ai_calls', interval=early)[0]['reason'], 'collecting_since')
        before = dict(start='2026-02-01T05:00:00Z', end='2026-03-01T05:00:00Z', timeZone=TZ)
        self.assertEqual(self.metric(service, principal, 'ai_calls', interval=before)[0]['reason'], 'not_instrumented')

    def test_cost_per_useful_outcome_and_forecast_read_the_canonical_ledger(self):
        owner = self.connect()
        for key, actual, at in (('agent:pg-1', 6000, '2026-05-10T12:00:00Z'), ('run:pg-2', 3000, '2026-05-11T12:00:00Z')):
            owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,at) "
                          "VALUES(%s,'settle','text_model','openai','gpt-6-sol',100,%s,'actual',%s,%s)", (self.workspace, actual, key, at))
        for index in range(3):
            owner.execute("INSERT INTO public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,saved_seconds,"
                          "baseline_source,baseline_version,confidence,calculator_version,occurred_at) VALUES(%s,%s,'draft','accepted_draft',%s,%s,600,600,'raffi_default','v1',"
                          "'estimated','v1','2026-05-15T12:00:00Z')", (self.workspace, self.user, f'draft:{index}', uuid.uuid4().hex * 2))
        service, principal = self.live_service()
        [row] = self.metric(service, principal, 'cost_per_useful_outcome')
        self.assertEqual((row['value'], row['measures']['basis'], row['coverage']['numerator'], row['coverage']['denominator']), (3000, 'time_back_accepted_outcomes', 9000, 3))
        proxies = {r['dimensions']['outcome_proxy']: r for r in self.metric(service, principal, 'cost_per_useful_outcome', ['outcome_proxy'])}
        self.assertEqual(set(proxies), {'time_back', 'learning_events'})
        self.assertIn(proxies['learning_events']['dataState'], ('not_applicable', 'unavailable'))
        october = dict(start='2026-09-01T04:00:00Z', end='2026-10-01T04:00:00Z', timeZone=TZ)
        [forecast] = self.metric(service, principal, 'ai_cost_forecast', interval=october)
        self.assertEqual(forecast['measures']['basis'], 'scenario')
        if forecast['reason'] == 'insufficient_history':
            self.assertLess(forecast['history']['availableDays'], 56)
        else:
            self.assertGreaterEqual(forecast['history']['availableDays'], 56)
            self.assertGreaterEqual(forecast['value'], 0)

    # --- cron stages --------------------------------------------------------------------------------------------------------
    def consumer(self):
        dsn = self.dsn
        return type('Service', (), {'connection_factory': staticmethod(lambda: psycopg.connect(dsn, prepare_threshold=None))})()

    def test_rollups_are_idempotent_and_purge_keeps_400_days(self):
        now = time.time()
        owner = self.connect()
        self.record(self.workspace, [{'physical_attempt_id': 'r1', 'provider': 'openai', 'model': 'gpt-6-sol', 'status': 'ok', 'input_tokens': 10, 'output_tokens': 5,
                                      'cost_usd_micro': 70, 'cost_source': 'gateway', 'started_at': now - 3600},
                                     {'physical_attempt_id': 'r2', 'provider': 'openai', 'model': 'gpt-6-sol', 'status': 'failed', 'started_at': now - 3600}])
        owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,at) "
                      "VALUES(%s,'settle','text_model','openai','gpt-6-sol',100,1234,'actual',%s,now()-interval '1 hour')", (self.workspace, 'agent:roll-' + uuid.uuid4().hex))
        first = ai.usage_rollups_stage(None, self.consumer(), {}, now)
        self.assertEqual(first['status'], 'ok')

        def rollups():
            return owner.execute('SELECT feature,actor_class,sum(calls),sum(ok),sum(failed),sum(input_tokens),sum(actual_usd_micro),count(*) FROM public.pr_usage_rollups '
                                 'WHERE workspace_id=%s GROUP BY 1,2 ORDER BY 1,2', (self.workspace,)).fetchall()
        before = rollups()
        self.assertEqual([tuple(row[:7]) for row in before], [('agent', 'customer', 2, 1, 1, 10, 1234)])
        self.assertEqual(ai.usage_rollups_stage(None, self.consumer(), {}, now)['skipped'], 'fresh')
        owner.execute("UPDATE public.pr_usage_rollups SET computed_at=computed_at-interval '2 hours' WHERE workspace_id=%s", (self.workspace,))
        self.assertEqual(ai.usage_rollups_stage(None, self.consumer(), {}, now)['status'], 'ok')
        self.assertEqual(rollups(), before, 'a recompute replaces the same days, never doubles them')
        self.record(self.workspace, [{'physical_attempt_id': 'old', 'provider': 'openai', 'model': 'gpt-6-sol', 'status': 'ok', 'started_at': now - 401 * 86400}])
        purged = ai.purge_stage(None, self.consumer(), {}, now)
        self.assertEqual((purged['status'], purged['deletedCallEvents']), ('ok', 1))
        self.assertEqual(owner.execute('SELECT count(*) FROM public.pr_ai_call_events WHERE workspace_id=%s', (self.workspace,)).fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
