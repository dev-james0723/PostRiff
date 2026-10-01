"""Migrations 059/065 and the product slice on a disposable PostgreSQL: projections, grants and RLS, the product event
writer inside a real customer transaction, and Live round trips of the funnel, time to value, adoption, retention, Time
back, correlations, the funnel drill-down and the learning rollup stage.

Skipped without RAFII_CONTROL_TEST_DSN (scripts/rafii_control_pg.py applies 049–056 and every founder migration twice).
Seeded workspaces are created in February 2024, an interval no other test writes, and removed afterwards."""
import os
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from postriff_phase2 import product_events
from rafii_control import founder_metrics_product as product
from rafii_control.auth import Boundary, CAPABILITIES, Config, VerifiedIdentity
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

VIEWS = ('business_product_events', 'business_learning_events', 'business_workspace_starts', 'business_channel_audit', 'business_learning_rollups')
INTERVAL = dict(start='2024-02-01T05:00:00Z', end='2024-03-01T05:00:00Z', timeZone='America/Indiana/Indianapolis')
DAY = timedelta(days=1)
OUTSIDE = '2023-06-05T15:00:00Z'   # tests other than the round trip create their workspaces outside INTERVAL


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderProductPostgresTests(unittest.TestCase):
    def connect(self, role=None, autocommit=True):
        con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], autocommit=autocommit, prepare_threshold=None)
        if role: con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        owner = self.connect()
        if owner.execute("SELECT to_regclass('rafii_control.business_product_events') IS NULL").fetchone()[0]:
            self.skipTest('migration 065 not applied by this harness')
        product_events.reset()
        self.addCleanup(product_events.reset)
        self.operator = str(uuid.uuid4())
        self.workspaces = []
        owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.operator,))
        owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.operator,))   # identity_active needs the operator's profile
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)", (self.operator, list(CAPABILITIES)))
        self.addCleanup(self.cleanup)

    def workspace(self, created_at):
        owner = self.connect()
        user = str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
        workspace = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        owner.execute('UPDATE public.pr_workspaces SET created_at=%s WHERE id=%s', (created_at, workspace))
        self.workspaces.append(workspace)
        return workspace, user

    def cleanup(self):
        import hashlib
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.request_budgets WHERE bucket=%s', (hashlib.sha256(b'exchange:global').hexdigest(),))
            for workspace in self.workspaces:
                for table in ('pr_product_events', 'pr_learning_events', 'pr_learning_daily_rollups', 'pr_audit_events', 'pr_notification_events', 'pr_time_savings_ledger'):
                    con.execute(f'DELETE FROM public.{table} WHERE workspace_id=%s', (workspace,))
                con.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,))
                try:   # best effort: the seeded workspace itself, so a later test's cohort never contains it
                    con.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (workspace,))
                except psycopg.Error:
                    pass
            con.execute('DROP TABLE IF EXISTS public.founder_product_scratch')

    def service(self):
        if getattr(self, '_session', None):
            return self._session
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), store, lambda token: VerifiedIdentity(self.operator, 'aal2', 'synthetic-upstream-' + self.operator, time.time()))
        token, _ = boundary.exchange('synthetic-identity', 'http://localhost:4449')
        self._session = QueryService(store), boundary.authorize(token, 'metrics.query')
        return self._session

    def query(self, metric, group_by=(), filters=()):
        service, principal = self.service()
        return service.metric_query(dict(metricIds=[metric], interval=INTERVAL, groupBy=list(group_by), filters=list(filters), comparison='none', limit=1000),
                                    principal, str(uuid.uuid4()))

    # -- migrations ------------------------------------------------------------------------------------------------------
    def test_projections_are_owned_barriered_reader_readable_and_allowlisted(self):
        owner = self.connect()
        for view in VIEWS:
            with self.subTest(view=view):
                row = owner.execute("SELECT pg_get_userbyid(c.relowner), c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relname=%s AND c.relkind='v'",
                                    (view,)).fetchone()
                self.assertEqual(row[0], 'rafii_control_business_projection')
                self.assertIn('security_barrier=true', row[1])
        workspace, user = self.workspace(OUTSIDE)
        owner.execute("INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key,occurred_at) VALUES(%s,%s,'draft.created',%s::jsonb,'pg:allowlist',now())",
                      (workspace, user, '{"feature": "Free text, not an enum", "voice": "personalized", "deliveryId": "secret-id"}'))
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',false)")
        for view in VIEWS: reader.execute(f'SELECT * FROM rafii_control.{view} LIMIT 1').fetchall()
        row = reader.execute('SELECT * FROM rafii_control.business_product_events WHERE "workspaceId"=%s', (workspace,)).fetchone()
        columns = [column.name for column in reader.execute('SELECT * FROM rafii_control.business_product_events LIMIT 0').description]
        self.assertEqual(columns, ['id', 'event', 'workspaceId', 'userId', 'occurredAt', 'feature', 'voice', 'surface', 'outcome', 'source', 'provider', 'cause', 'via', 'kind',
                                   'schedule', 'plan', 'platform'])
        values = dict(zip(columns, row))
        self.assertEqual((values['feature'], values['voice']), (None, 'personalized'), 'a non-enum value reads NULL')
        self.assertNotIn('secret-id', str(row))
        for statement in ('SELECT properties FROM public.pr_product_events', 'SELECT subject FROM public.pr_learning_events', 'SELECT * FROM public.pr_learning_daily_rollups',
                          'SELECT subject FROM public.pr_audit_events'):
            with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute(statement)
        flags = owner.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='public.pr_learning_daily_rollups'::regclass").fetchone()
        self.assertEqual(tuple(flags), (True, True))
        self.assertEqual(owner.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='pr_learning_daily_rollups' AND policyname='service_only'").fetchone()[0], 1)
        for role in ('anon', 'authenticated'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.connect(role).execute('SELECT * FROM public.pr_learning_daily_rollups')
        owner.execute("INSERT INTO public.pr_learning_daily_rollups(day,workspace_id,kind,events,first_at) VALUES('2024-02-05',%s,'draft.approved',2,'2024-02-05T16:00:00Z')", (workspace,))
        self.assertEqual(str(owner.execute('SELECT expires_at FROM public.pr_learning_daily_rollups WHERE workspace_id=%s', (workspace,)).fetchone()[0]), '2025-03-11')

    # -- the writer inside a real customer transaction ---------------------------------------------------------------------
    def test_a_failing_event_write_never_rolls_back_the_customer_transaction(self):
        workspace, user = self.workspace(OUTSIDE)
        owner = self.connect()
        owner.execute('CREATE TABLE IF NOT EXISTS public.founder_product_scratch(id int)')
        con = self.connect(autocommit=False)
        with con.cursor() as cur:
            cur.execute('INSERT INTO public.founder_product_scratch(id) VALUES(1)')   # the customer's own write
            cur.execute('SET LOCAL ROLE authenticated')                                 # no grant on pr_product_events
            self.assertFalse(product_events.record(cur, workspace, user, 'humanizer.applied', 'v' * 32, 1, {'surface': 'weekly', 'outcome': 'ready'}))
            self.assertTrue(product_events.suspended(), 'InsufficientPrivilege reads as not installed yet')
            cur.execute('RESET ROLE')
            cur.execute('INSERT INTO public.founder_product_scratch(id) VALUES(2)')
        con.commit()
        self.assertEqual([row[0] for row in owner.execute('SELECT id FROM public.founder_product_scratch ORDER BY id').fetchall()], [1, 2])
        self.assertEqual(owner.execute("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s", (workspace,)).fetchone()[0], 0)
        product_events.reset()
        with self.connect(autocommit=False) as writer, writer.cursor() as cur:
            self.assertTrue(product_events.record(cur, workspace, user, 'humanizer.applied', 'v' * 32, 1, {'surface': 'weekly', 'outcome': 'ready', 'text': 'never stored'}))
            self.assertFalse(product_events.record(cur, workspace, user, 'humanizer.applied', 'v' * 32, 1, {'surface': 'weekly'}), 'the dedupe key makes a replay a no-op')
        stored = owner.execute('SELECT event,properties,dedupe_key,user_id::text FROM public.pr_product_events WHERE workspace_id=%s', (workspace,)).fetchall()
        self.assertEqual(stored, [('humanizer.applied', {'outcome': 'ready', 'surface': 'weekly'}, f"humanizer.applied:{'v' * 32}:1", user)])

    # -- Live round trips ----------------------------------------------------------------------------------------------
    def seed(self):
        owner = self.connect()
        anchor, anchor_user = self.workspace('2023-01-02T15:00:00Z')   # outside the interval: makes voice.created collected since 2023
        ws1, u1 = self.workspace('2024-02-05T15:00:00Z')
        ws2, u2 = self.workspace('2024-02-06T15:00:00Z')
        ws3, u3 = self.workspace('2024-02-07T15:00:00Z')
        internal, _ = self.workspace('2024-02-08T15:00:00Z')
        owner.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,environment) VALUES(%s,'internal','pg test','local')", (internal,))

        def event(workspace, user, name, at, properties='{}'):
            owner.execute('INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key,occurred_at) VALUES(%s,%s,%s,%s::jsonb,%s,%s)',
                          (workspace, user, name, properties, f'pg:{name}:{uuid.uuid4().hex}', at))
        event(anchor, anchor_user, 'voice.created', '2023-01-03T15:00:00Z')
        event(ws1, u1, 'voice.created', '2024-02-07T15:00:00Z')
        event(ws2, u2, 'channel.connected', '2024-02-09T15:00:00Z', '{"provider": "linkedin"}')
        event(internal, u1, 'voice.created', '2024-02-09T15:00:00Z')
        owner.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,at) VALUES(%s,%s,'channel.connected','conn-1','2024-02-06T15:00:00Z')", (ws1, u1))
        for workspace, kind, at in ((ws1, 'draft.approved', '2024-02-09T15:00:00Z'), (ws3, 'post.published', '2024-02-08T15:00:00Z')):
            owner.execute('INSERT INTO public.pr_learning_events(workspace_id,actor,kind,created_at,expires_at) VALUES(%s,%s,%s,%s,%s)', (workspace, u1, kind, at, '2099-01-01T00:00:00Z'))
        owner.execute("INSERT INTO public.pr_notification_events(workspace_id,scope_key,event_type,category,severity,dedupe_key,occurred_at) VALUES(%s,%s,'publish.verified','publishing','info',%s,'2024-02-10T15:00:00Z')",
                      (ws1, 'workspace:' + ws1, 'pg:' + uuid.uuid4().hex))
        owner.execute("INSERT INTO public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,saved_seconds,baseline_source,"
                      "baseline_version,confidence,calculator_version,occurred_at) VALUES(%s,%s,'draft','accepted_draft','variant:pg',%s,480,480,'raffi_default','v1','estimated','v1','2024-02-08T15:00:00Z')",
                      (ws1, u1, uuid.uuid4().hex * 2))
        return ws1, ws2, ws3

    def test_live_round_trips_over_the_projections(self):
        ws1, ws2, ws3 = self.seed()
        funnel = {row['dimensions']['step']: row for row in self.query('activation_funnel', ['step'])['rows']}
        self.assertEqual(funnel['workspace_created']['value'], 3, 'the internal workspace is excluded')
        self.assertEqual((funnel['channel_connected']['value'], funnel['channel_connected']['dataState'], funnel['channel_connected']['measures']['source']),
                         (2, 'partial', 'transition_proxy'))
        self.assertEqual((funnel['voice_activated']['value'], funnel['voice_activated']['coverage']['denominator'], funnel['voice_activated']['dataState']), (1, 3, 'measured'))
        self.assertEqual((funnel['draft_created']['dataState'], funnel['draft_created']['reason']), ('unavailable', 'not_instrumented'))
        self.assertEqual((funnel['draft_approved']['value'], funnel['draft_approved']['measures']['proxyReached']), (1, 1))
        # ws1 by its publish notification, ws3 by its learning post.published (both transition proxies).
        self.assertEqual((funnel['publish_verified']['value'], funnel['voice_activated']['measures']['stuckFromPrevious']), (2, 1))
        ttv = self.query('time_to_value')['rows'][0]
        self.assertEqual((ttv['value'], ttv['sampleCount'], ttv['coverage']['denominator'], ttv['measures']['p25'], ttv['measures']['p75']), (172800, 2, 3, 129600, 216000))
        self.assertEqual(ttv['measures']['firstValueSources'], {'time_back': 1, 'taxonomy': 0, 'transition_proxy': 1})
        adoption = {row['dimensions']['feature']: row for row in self.query('feature_adoption', ['feature'])['rows']}
        self.assertEqual((adoption['voice']['value'], adoption['voice']['coverage']['denominator'], adoption['voice']['dataState']), (0.5, 2, 'measured'))
        self.assertEqual((adoption['publishing']['value'], adoption['publishing']['dataState']), (0.5, 'partial'))
        retention = {(row['dimensions']['cohort'], row['dimensions']['week']): row for row in self.query('retention_weekly', ['cohort', 'week'])['rows']}
        self.assertEqual(set(cohort for cohort, _ in retention), {'2024-02-05'})
        self.assertEqual((retention[('2024-02-05', 0)]['coverage']['numerator'], retention[('2024-02-05', 0)]['coverage']['denominator']), (2, 3))
        self.assertEqual((retention[('2024-02-05', 1)]['value'], retention[('2024-02-05', 12)]['dataState']), (0.0, 'measured'))
        time_back = self.query('time_back')['rows']
        self.assertEqual([(row['dimensions'], row['value']) for row in time_back], [({'confidence': 'estimated'}, 480)])
        correlations = {row['dimensions']['feature']: row for row in self.query('retention_correlations', ['feature'])['rows']}
        self.assertEqual((correlations['voice']['dataState'], correlations['voice']['reason'], correlations['voice']['measures']['adopters']), ('suppressed', 'sample_too_small', 1))
        service, principal = self.service()
        app = type('App', (), {'queries': service})()
        stuck = product.stuck_workspaces(app, principal, dict(mode='live', query={'step': ['voice_activated'], 'start': [INTERVAL['start']], 'end': [INTERVAL['end']]}))
        self.assertEqual([row['workspaceId'] for row in stuck['rows']], [ws2])

    def test_the_rollup_stage_keeps_learning_history_idempotently(self):
        workspace, user = self.workspace(OUTSIDE)
        owner = self.connect()
        recent = datetime.now(timezone.utc) - DAY
        for _ in range(2):
            owner.execute("INSERT INTO public.pr_learning_events(workspace_id,actor,kind,created_at) VALUES(%s,%s,'draft.approved',%s)", (workspace, user, recent))
        owner.execute("INSERT INTO public.pr_learning_daily_rollups(day,workspace_id,kind,events,first_at) VALUES('2023-01-01',%s,'draft.approved',1,'2023-01-01T15:00:00Z')", (workspace,))
        consumer = type('Service', (), {'connection_factory': staticmethod(lambda: psycopg.connect(self.dsn, prepare_threshold=None))})()
        owner.execute('UPDATE public.pr_learning_daily_rollups SET computed_at=now()-interval \'2 hours\'')
        summary = product.rollup_stage(None, consumer, {}, time.time())
        self.assertEqual(summary['status'], 'ok')
        rows = owner.execute('SELECT day,kind,events FROM public.pr_learning_daily_rollups WHERE workspace_id=%s ORDER BY day', (workspace,)).fetchall()
        self.assertEqual([(kind, events) for _, kind, events in rows], [('draft.approved', 2)], 'the expired 2023 row is purged; the recent day is rolled up')
        self.assertEqual(product.rollup_stage(None, consumer, {}, time.time()), {'status': 'ok', 'skipped': 'fresh'})
        owner.execute('UPDATE public.pr_learning_daily_rollups SET computed_at=now()-interval \'2 hours\'')
        product.rollup_stage(None, consumer, {}, time.time())
        self.assertEqual(owner.execute('SELECT sum(events) FROM public.pr_learning_daily_rollups WHERE workspace_id=%s', (workspace,)).fetchone()[0], 2, 'a recompute never double counts')
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',false)")
        self.assertEqual(reader.execute('SELECT events FROM rafii_control.business_learning_rollups WHERE "workspaceId"=%s', (workspace,)).fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
