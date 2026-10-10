"""Founder slice 8.D on a disposable PostgreSQL: 060 (public instrumentation) and 066 (rafii_control projections and the
watchdog role), the request-metrics writer, the cron stages, the source probes, the watchdog and every ops metric through
the restricted reader role.

Skipped without RAFII_CONTROL_TEST_DSN. scripts/rafii_control_pg.py applies every founder migration twice in number order.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import time
import types
import unittest
import uuid
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import make_conninfo

from rafii_control import founder_cron, founder_sources
from rafii_control import founder_metrics_ops as ops
from rafii_control.auth import CAPABILITIES
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

TZ = 'America/Indiana/Indianapolis'
TABLES = ('pr_request_metrics', 'pr_operational_snapshots', 'pr_connection_health')
VIEWS = ('business_request_metrics', 'business_operational_snapshots', 'business_connection_health')
NOW = datetime(2026, 10, 1, 12, 5, 30, tzinfo=timezone.utc)   # 08:05:30 local: inside the hourly connection refresh window
BUCKETS_EMPTY = [0] * 20


def local_epoch(text):
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(TZ)).timestamp()


def buckets(**counts):
    values = list(BUCKETS_EMPTY)
    for index, count in counts.items():
        values[int(index[1:])] = count
    return values


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderOpsPostgresTests(unittest.TestCase):
    def connect(self, role=None, **kwargs):
        con = psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None, **kwargs)
        if role:
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def factory(self):
        return psycopg.connect(self.dsn, prepare_threshold=None)

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        owner = self.connect()
        if owner.execute("SELECT to_regclass('public.pr_request_metrics') IS NULL OR to_regclass('rafii_control.business_request_metrics') IS NULL").fetchone()[0]:
            self.skipTest('migrations 060/066 not applied by this harness')
        self.user = str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))
        self.workspace = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0])
        self.clean(owner)
        self.addCleanup(self.clean)
        ops.PAUSED.clear()
        ops.LOGGED.clear()

    def clean(self, owner=None):
        with psycopg.connect(self.dsn, autocommit=True) as con:
            for table in TABLES:
                con.execute(f'DELETE FROM public.{table}')
            con.execute('DELETE FROM public.pr_data_requests WHERE workspace_id=%s', (self.workspace,))
            con.execute('DELETE FROM public.pr_notification_events WHERE workspace_id=%s', (self.workspace,))
            con.execute('DELETE FROM public.pr_channel_capabilities WHERE workspace_id=%s', (self.workspace,))
            con.execute("DELETE FROM public.pr_billing_events WHERE event_id LIKE 'evt_ops_%%'")
            con.execute("DELETE FROM rafii_control.source_health WHERE environment IN ('local','staging')")

    # ---- 060 ------------------------------------------------------------------------------------------------------------
    def test_public_tables_force_rls_service_only_and_request_metrics_are_unlogged(self):
        owner = self.connect()
        for table in TABLES:
            with self.subTest(table=table):
                flags = owner.execute("SELECT c.relrowsecurity, c.relforcerowsecurity, c.relpersistence FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                      "WHERE n.nspname='public' AND c.relname=%s", (table,)).fetchone()
                self.assertEqual(tuple(flags), (True, True, 'u' if table == 'pr_request_metrics' else 'p'))
                policies = owner.execute("SELECT policyname, roles::text FROM pg_policies WHERE schemaname='public' AND tablename=%s", (table,)).fetchall()
                self.assertEqual([tuple(row) for row in policies], [('service_only', '{service_role}')])
                for role in ('anon', 'authenticated', 'rafii_control_reader', 'rafii_control_session', 'rafii_control_watchdog'):
                    self.assertFalse(owner.execute("SELECT has_table_privilege(%s, %s, 'SELECT,INSERT,UPDATE,DELETE')", (role, 'public.' + table)).fetchone()[0], role)
                self.assertTrue(owner.execute("SELECT has_table_privilege('service_role', %s, 'INSERT')", ('public.' + table,)).fetchone()[0])
        indexes = {row[0] for row in owner.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public'").fetchall()}
        self.assertLessEqual({'pr_usage_ledger_settled_at_idx', 'pr_billing_events_recency_idx', 'pr_connection_health_refreshed_idx'}, indexes)

    def test_checks_reject_raw_paths_payloads_and_unknown_states(self):
        owner = self.connect()
        insert = 'INSERT INTO public.pr_request_metrics(minute,route_pattern,status_class,request_count,duration_sum_ms,duration_buckets) VALUES(now(),%s,%s,1,10,%s)'
        owner.execute(insert, ('GET /api/workspaces/:id/members', '2xx', buckets(b0=1)))
        for route in ('GET /api/workspaces/5f0c1a52-8f3e-4b8e-9a53-0f5c2e1f9a10', 'GET /api/health?token=x', 'GET /api/Users', 'get /api/health',
                      'GET https://example.com/api', 'GET /api/me/someone@example.com', 'GET /api/' + 'a' * 30):
            with self.subTest(route=route), self.assertRaises(psycopg.errors.CheckViolation):
                owner.execute(insert, (route, '2xx', buckets(b0=1)))
        for value in ([0] * 19, [-1] + [0] * 19):
            with self.assertRaises(psycopg.errors.CheckViolation):
                owner.execute(insert, ('GET /api/health', '2xx', value))
        with self.assertRaises(psycopg.errors.CheckViolation):
            owner.execute(insert, ('GET /api/health', '6xx', buckets(b0=1)))
        snapshot = "INSERT INTO public.pr_operational_snapshots(minute,observed_at,status,counts) VALUES(now()-%s::interval,now(),'ok',%s::jsonb)"
        owner.execute(snapshot, ('1 minute', '{"queueDelayed":1,"sms.backlogOver10m":0}'))
        for index, counts in enumerate(('{"a":"x"}', '{"a":-1}', '{"a":[1]}', '{"a":{"b":1}}', '{"a":true}')):
            with self.subTest(counts=counts), self.assertRaises(psycopg.errors.CheckViolation):
                owner.execute(snapshot, (f'{index + 2} minutes', counts))
        health = ("INSERT INTO public.pr_connection_health(workspace_id,connection_id,capability,provider,level,state,connection_state) "
                  "VALUES(%s,%s,%s,%s,%s,%s,'read_verified')")
        owner.execute(health, (self.workspace, 'c' * 32, 'publish', 'linkedin', 'Direct', 'ok'))
        for connection_id, capability, provider, level, state in (('has space', 'publish', 'linkedin', 'Direct', 'ok'), ('d' * 32, 'publish', 'LinkedIn', 'Direct', 'ok'),
                                                                  ('d' * 32, 'publish', 'linkedin', 'Direct', 'broken'), ('d' * 32, 'tokens', 'linkedin', 'Direct', 'ok'),
                                                                  ('d' * 32, 'publish', 'linkedin', 'Great', 'ok')):
            with self.subTest(state=state, provider=provider), self.assertRaises(psycopg.errors.CheckViolation):
                owner.execute(health, (self.workspace, connection_id, capability, provider, level, state))

    def test_writer_flushes_merge_across_instances_and_never_store_identifiers(self):
        from postriff_phase2.request_metrics import Recorder
        at = local_epoch('2026-10-01T08:00:10')
        first, second = Recorder(clock=lambda: at, spawn=lambda work: work()), Recorder(clock=lambda: at, spawn=lambda work: work())
        first.record('GET', f'/api/workspaces/{self.workspace}/members', 200, 0.004)
        first.record('GET', f'/api/workspaces/{uuid.uuid4()}/members', 200, 0.120)
        second.record('GET', f'/api/workspaces/{self.workspace}/members', 200, 0.120)
        second.record('POST', '/api/control/v2/incidents/12345/ack', 503, 31.0)
        self.assertTrue(first.maybe_flush(self.factory))
        self.assertTrue(second.maybe_flush(self.factory))
        owner = self.connect()
        rows = owner.execute('SELECT route_pattern,status_class,request_count,duration_sum_ms,duration_buckets FROM public.pr_request_metrics ORDER BY 1,2').fetchall()
        self.assertEqual([(row[0], row[1], row[2]) for row in rows], [('GET /api/workspaces/:id/members', '2xx', 3), ('POST /api/control/v2/incidents/:id/ack', '5xx', 1)])
        self.assertEqual((rows[0][4][0], rows[0][4][5], round(rows[0][3], 1)), (1, 2, 244.0), 'buckets add element-wise across instances')
        self.assertEqual(rows[1][4][-1], 1)
        self.assertNotIn(self.workspace, json.dumps([list(map(str, row)) for row in rows]))

    def test_writer_treats_a_missing_privilege_as_not_installed(self):
        from postriff_phase2.request_metrics import NOT_INSTALLED_PAUSE, Recorder

        def as_reader():
            con = psycopg.connect(self.dsn, prepare_threshold=None)
            con.execute('SET ROLE rafii_control_reader')
            return con
        recorder = Recorder(clock=lambda: 1_790_000_040.0, spawn=lambda work: work())
        recorder.record('GET', '/api/health', 200, 0.01)
        with self.assertLogs('postriff.request_metrics', level='WARNING') as logs:
            recorder.maybe_flush(as_reader)
        self.assertEqual(json.loads(logs.records[0].getMessage())['error'], 'InsufficientPrivilege')
        self.assertEqual(recorder.paused_until, 1_790_000_040.0 + NOT_INSTALLED_PAUSE)

    # ---- 066 ------------------------------------------------------------------------------------------------------------
    def test_projections_are_projection_owned_reader_readable_and_column_bounded(self):
        owner = self.connect()
        for view in VIEWS:
            with self.subTest(view=view):
                row = owner.execute("SELECT pg_get_userbyid(c.relowner), c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                    "WHERE n.nspname='rafii_control' AND c.relname=%s AND c.relkind='v'", (view,)).fetchone()
                self.assertEqual(row[0], 'rafii_control_business_projection')
                self.assertIn('security_barrier=true', row[1])
                for role in ('anon', 'authenticated', 'service_role', 'rafii_control_watchdog'):
                    self.assertFalse(owner.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (role, 'rafii_control.' + view)).fetchone()[0])
        columns = {row[0] for row in owner.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='rafii_control' AND table_name='business_connection_health'").fetchall()}
        self.assertEqual(columns, {'workspaceId', 'connectionId', 'provider', 'capability', 'level', 'state', 'connectionState', 'expiresAt', 'lastSyncAt', 'refreshedAt'})
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',false)")
        for view in VIEWS:
            reader.execute(f'SELECT * FROM rafii_control.{view} LIMIT 1').fetchall()
        for table in TABLES:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute(f'SELECT * FROM public.{table}')

    def test_watchdog_role_is_nologin_and_sees_only_its_environments_source_health(self):
        owner = self.connect()
        role = owner.execute("SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname='rafii_control_watchdog'").fetchone()
        self.assertEqual(tuple(role), (False, False, False, False))
        self.assertEqual(owner.execute("SELECT count(*) FROM pg_auth_members WHERE roleid='rafii_control_watchdog'::regrole OR member='rafii_control_watchdog'::regrole").fetchone()[0], 0,
                         'the migration grants no role membership')
        relations = owner.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relkind IN ('r','v')").fetchall()
        readable = {row[0] for row in relations if owner.execute("SELECT has_table_privilege('rafii_control_watchdog', %s, 'SELECT')", ('rafii_control.' + row[0],)).fetchone()[0]}
        self.assertEqual(readable, {'source_health'})
        self.assertFalse(owner.execute("SELECT has_table_privilege('rafii_control_watchdog','rafii_control.source_health','INSERT,UPDATE,DELETE,TRUNCATE')").fetchone()[0])
        for environment, source in (('local', 'cron'), ('staging', 'cron'), ('local', 'database')):
            owner.execute("INSERT INTO rafii_control.source_health(source_id,environment,state,watermark,checked_at,reason_code) VALUES(%s,%s,'measured',now(),now(),'qualified')",
                          (source, environment))
        watchdog = self.connect('rafii_control_watchdog')
        watchdog.execute("SELECT set_config('rafii_control.environment','local',false)")
        self.assertEqual(sorted(row[0] for row in watchdog.execute('SELECT source_id FROM rafii_control.source_health').fetchall()), ['cron', 'database'])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            watchdog.execute("INSERT INTO rafii_control.source_health(source_id,environment,state,reason_code) VALUES('x','local','measured','qualified')")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            watchdog.execute('SELECT * FROM rafii_control.founder_incidents')

    def test_watchdog_main_through_a_member_login(self):
        owner = self.connect()
        login = 'ops_watchdog_' + uuid.uuid4().hex[:8]
        owner.execute(psycopg.sql.SQL('CREATE ROLE {} LOGIN IN ROLE rafii_control_watchdog').format(psycopg.sql.Identifier(login)))   # test-only login
        self.addCleanup(lambda: psycopg.connect(self.dsn, autocommit=True).execute(psycopg.sql.SQL('DROP ROLE IF EXISTS {}').format(psycopg.sql.Identifier(login))))
        owner.execute("INSERT INTO rafii_control.source_health(source_id,environment,state,watermark,checked_at,reason_code) VALUES('cron','local','measured',now(),now(),'qualified')")
        environ = {'RAFII_WATCHDOG_DSN': make_conninfo(self.dsn, user=login), 'RAFII_WATCHDOG_ENVIRONMENT': 'local'}
        out = []
        self.assertEqual(founder_sources.watchdog_main(environ, out=out.append), 0, out)
        owner.execute("UPDATE rafii_control.source_health SET checked_at=now()-interval '11 minutes' WHERE source_id='cron' AND environment='local'")
        out = []
        self.assertEqual(founder_sources.watchdog_main(environ, out=out.append), 1)
        self.assertTrue(any(line.startswith('::error title=Founder cron heartbeat (local)::The cron heartbeat is') for line in out), out)
        out = []
        self.assertEqual(founder_sources.watchdog_main({'RAFII_WATCHDOG_DSN': self.dsn, 'RAFII_WATCHDOG_ENVIRONMENT': 'local'}, out=out.append), 1, 'a superuser DSN is refused')
        self.assertIn('refused', out[0])

    # ---- probes and stages -------------------------------------------------------------------------------------------------
    def test_probe_writes_every_source_through_the_restricted_stores(self):
        owner = self.connect()
        processed = local_epoch('2026-10-01T07:00:00')
        owner.execute("INSERT INTO public.pr_billing_events(provider,event_id,kind,event_at,payload_digest,outcome,processed_at) "
                      "VALUES('stripe','evt_ops_1','invoice.paid',now(),repeat('a',64),'applied',to_timestamp(%s))", (processed,))
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        fstore = founder_cron.PostgresFounderStore(store)
        service = types.SimpleNamespace(connection_factory=self.factory, billing=types.SimpleNamespace(provider=types.SimpleNamespace(id='stripe')), phone=None, notifications=None)
        written = founder_cron.probe(fstore, service, {}, time.time())
        self.assertEqual(set(written), set(founder_sources.SOURCE_IDS))
        self.assertEqual((written['database'], written['control_database'], written['control_reader'], written['stripe_webhooks']), ('measured',) * 4)
        self.assertIn(written['email_provider'], ('partial', 'not_applicable'))
        rows = {row['source_id']: row for row in store.read('sources')}
        self.assertEqual(set(rows), set(founder_sources.SOURCE_IDS))
        self.assertAlmostEqual(datetime.fromisoformat(rows['stripe_webhooks']['watermark']).timestamp(), processed, places=0)

    def test_stages_snapshot_project_and_purge(self):
        owner = self.connect()
        now = NOW.timestamp()
        snapshot = {'status': 'attention', 'observedAt': now, 'counts': {'queueDelayed': 2, 'modelStuck': 0}, 'sms': {'backlogOver10m': 1}, 'notificationDelivery': 'rafii_v2'}
        result = ops.operational_snapshot_stage(None, types.SimpleNamespace(connection_factory=self.factory, last_operational_snapshot=snapshot), {}, now)
        self.assertEqual(result['status'], 'ok', result)
        row = owner.execute('SELECT status,notification_delivery,counts FROM public.pr_operational_snapshots').fetchone()
        self.assertEqual(tuple(row), ('attention', 'rafii_v2', {'queueDelayed': 2, 'modelStuck': 0, 'sms.backlogOver10m': 1}))
        computed = ops.operational_snapshot_stage(None, types.SimpleNamespace(connection_factory=self.factory), {}, now + 60)
        self.assertEqual((computed['status'], computed.get('source')), ('ok', 'computed'), computed)
        # Connection health from workspace channel state: no handle, account id or scope list reaches the projection.
        original = owner.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
        self.addCleanup(lambda: psycopg.connect(self.dsn, autocommit=True).execute('UPDATE public.pr_workspaces SET state=%s WHERE id=%s', (json.dumps(original), self.workspace)))
        channels = [{'id': 'c' * 32, 'platform': 'LinkedIn', 'account': 'private-handle', 'configured': True, 'identityVerified': True, 'revoked': False,
                     'providerAccountId': 'urn:li:person:private', 'expiresAt': now + 3 * 86400, 'scopes': ['w_member_social'], 'capabilityVerified': True, 'verifiedAt': now - 60},
                    {'id': 'd' * 32, 'platform': 'X', 'account': 'other-handle', 'configured': True, 'identityVerified': True, 'revoked': True,
                     'providerAccountId': 'x-private', 'expiresAt': now + 99 * 86400, 'scopes': ['tweet.write'], 'capabilityVerified': False, 'verifiedAt': now - 60}]

        def set_channels(items):
            owner.execute("UPDATE public.pr_workspaces SET state=state || jsonb_build_object('phase2', coalesce(state->'phase2','{}'::jsonb) || jsonb_build_object('channels', %s::jsonb)) WHERE id=%s",
                          (json.dumps(items), self.workspace))
        set_channels(channels)
        owner.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) "
                      "VALUES(%s,%s,'identity','Direct','Account confirmed.',1,now()),(%s,%s,'publish','Direct','Granted.',1,now())", (self.workspace, 'c' * 32, self.workspace, 'c' * 32))
        result = ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=self.factory), {}, now)
        self.assertEqual((result['status'], result['rows']), ('ok', 3), result)
        rows = owner.execute('SELECT connection_id,capability,provider,level,state,connection_state FROM public.pr_connection_health ORDER BY 1,2').fetchall()
        self.assertEqual([tuple(row) for row in rows], [('c' * 32, 'identity', 'linkedin', 'Direct', 'expiring', 'publish_verified'),
                                                        ('c' * 32, 'publish', 'linkedin', 'Direct', 'expiring', 'publish_verified'),
                                                        ('d' * 32, 'identity', 'x', 'unknown', 'blocked', 'reauthorization_required')])
        dump = json.dumps([list(map(str, row)) for row in owner.execute('SELECT * FROM public.pr_connection_health').fetchall()])
        self.assertNotIn('private', dump)
        self.assertNotIn('w_member_social', dump)
        self.assertEqual(ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=self.factory), {}, now + 60)['reason'], 'not_due')
        set_channels(channels[:1])
        result = ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=self.factory), {}, now + 3600)
        self.assertEqual((result['rows'], result['removed']), (2, 1), result)
        # Daily purge at 03:00 local: 30-day request metrics and snapshots, 7-day connection rows.
        purge_at = local_epoch('2026-10-02T03:02:00')
        owner.execute("INSERT INTO public.pr_request_metrics(minute,route_pattern,status_class,request_count,duration_sum_ms,duration_buckets) "
                      "VALUES(to_timestamp(%s),'GET /api/health','2xx',1,1,%s),(to_timestamp(%s),'GET /api/health','2xx',1,1,%s)",
                      (int((purge_at - 31 * 86400) // 60) * 60, buckets(b0=1), int((purge_at - 3600) // 60) * 60, buckets(b0=1)))
        owner.execute("INSERT INTO public.pr_operational_snapshots(minute,observed_at,status,counts) VALUES(to_timestamp(%s),to_timestamp(%s),'ok','{}')",
                      (int((purge_at - 40 * 86400) // 60) * 60, purge_at - 40 * 86400))
        owner.execute("UPDATE public.pr_connection_health SET refreshed_at=to_timestamp(%s) WHERE capability='publish'", (purge_at - 8 * 86400,))
        result = ops.reliability_purge_stage(None, types.SimpleNamespace(connection_factory=self.factory), {}, purge_at)
        self.assertEqual(result, {'status': 'ok', 'deleted': {'pr_request_metrics': 1, 'pr_operational_snapshots': 1, 'pr_connection_health': 1}})
        self.assertEqual(owner.execute('SELECT count(*) FROM public.pr_request_metrics').fetchone()[0], 1)

    def test_youtube_vault_overlay_projects_inside_the_060_check(self):
        """A YouTube credential whose refresh grant is retained but disabled classifies client_binding_missing. The projection must
        store it inside the 060 connection_state CHECK (as reauthorization_required) or the hourly upsert aborts for everyone.
        Channels the projection skips (invalid id, duplicate id, configured but neither verified, revoked nor tied to an account)
        are filtered in SQL, so the stage cap counts projectable connections only."""
        owner = self.connect()
        now = NOW.timestamp()
        created = owner.execute("SELECT to_regclass('public.pr_encrypted_credentials') IS NULL").fetchone()[0]
        if created:   # the Control harness applies founder migrations only; 006 owns the real table (same columns)
            owner.execute('CREATE TABLE public.pr_encrypted_credentials(workspace_id uuid NOT NULL, connection_id text NOT NULL, provider text NOT NULL, '
                          'provider_account_id text NOT NULL, access_ciphertext text NOT NULL, refresh_ciphertext text, key_id text NOT NULL, scopes text[] NOT NULL, '
                          'access_expires_at timestamptz, refresh_supported boolean NOT NULL DEFAULT false, revoked_at timestamptz, '
                          'PRIMARY KEY(workspace_id, connection_id))')
            self.addCleanup(lambda: psycopg.connect(self.dsn, autocommit=True).execute('DROP TABLE IF EXISTS public.pr_encrypted_credentials'))
        else:
            self.addCleanup(lambda: psycopg.connect(self.dsn, autocommit=True).execute('DELETE FROM public.pr_encrypted_credentials WHERE workspace_id=%s', (self.workspace,)))
        original = owner.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
        self.addCleanup(lambda: psycopg.connect(self.dsn, autocommit=True).execute('UPDATE public.pr_workspaces SET state=%s WHERE id=%s', (json.dumps(original), self.workspace)))
        youtube = lambda cid: {'id': cid, 'platform': 'YouTube', 'configured': True, 'identityVerified': True, 'revoked': False, 'providerAccountId': 'UC-private',
                               'expiresAt': now - 60, 'scopes': ['https://www.googleapis.com/auth/youtube.readonly'], 'capabilityVerified': False}
        channels = [youtube('yt-binding-0001'), youtube('yt-refresh-0002'),
                    {'id': 'bad id with spaces', 'platform': 'X', 'configured': True, 'identityVerified': True},
                    {'id': 'li-unverified-03', 'platform': 'LinkedIn', 'configured': True, 'identityVerified': False},
                    youtube('yt-refresh-0002')]
        owner.execute("UPDATE public.pr_workspaces SET state=state || jsonb_build_object('phase2', coalesce(state->'phase2','{}'::jsonb) || jsonb_build_object('channels', %s::jsonb)) WHERE id=%s",
                      (json.dumps(channels), self.workspace))
        for cid, refresh, supported in (('yt-binding-0001', 'retained-ciphertext', False), ('yt-refresh-0002', 'refresh-ciphertext', True)):
            owner.execute('INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,refresh_ciphertext,key_id,scopes,'
                          'access_expires_at,refresh_supported) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s)',
                          (self.workspace, cid, 'youtube', 'UC-private', 'access-ciphertext', refresh, 'k1', ['youtube.readonly'], now - 60, supported))
        result = ops.connection_health_stage(None, types.SimpleNamespace(connection_factory=self.factory), {}, now)
        self.assertEqual((result['status'], result['connections'], result['youtubeOverlay']), ('ok', 2, 'applied'), result)
        rows = owner.execute('SELECT connection_id,state,connection_state,expires_at FROM public.pr_connection_health WHERE workspace_id=%s ORDER BY 1', (self.workspace,)).fetchall()
        self.assertEqual([tuple(row) for row in rows], [('yt-binding-0001', 'blocked', 'reauthorization_required', datetime.fromtimestamp(now - 60, timezone.utc)),
                                                        ('yt-refresh-0002', 'ok', 'read_verified', None)])

    # ---- metrics through the reader ----------------------------------------------------------------------------------------
    def test_every_ops_metric_round_trips_through_the_reader_role(self):
        owner = self.connect()
        minute = int((NOW.timestamp() - 600) // 60) * 60
        owner.execute("INSERT INTO public.pr_request_metrics(minute,route_pattern,status_class,request_count,duration_sum_ms,duration_buckets) VALUES"
                      "(to_timestamp(%s),'GET /api/health','2xx',98,980,%s),(to_timestamp(%s),'GET /api/health','5xx',2,20,%s),"
                      "(to_timestamp(%s),'GET /api/cron/worker','5xx',1,5000,%s)",
                      (minute, buckets(b0=50, b5=48), minute, buckets(b0=2), minute, buckets(b14=1)))
        owner.execute("INSERT INTO public.pr_operational_snapshots(minute,observed_at,status,counts) VALUES(to_timestamp(%s),to_timestamp(%s),'attention',%s::jsonb),"
                      "(to_timestamp(%s),to_timestamp(%s),'ok',%s::jsonb)",
                      (minute, minute, '{"queueDelayed":3,"sms.backlogOver10m":1}', minute + 60, minute + 60, '{"queueDelayed":1,"sms.backlogOver10m":0}'))
        owner.execute("INSERT INTO public.pr_connection_health(workspace_id,connection_id,capability,provider,level,state,connection_state,refreshed_at) "
                      "VALUES(%s,%s,'publish','linkedin','Direct','expiring','publish_verified',to_timestamp(%s))", (self.workspace, 'c' * 32, NOW.timestamp() - 300))
        owner.execute("INSERT INTO public.pr_data_requests(workspace_id,requested_by,kind,status,requested_at) VALUES(%s,%s,'export','requested',to_timestamp(%s))",
                      (self.workspace, self.user, NOW.timestamp() - 2 * 86400))
        for index, event in enumerate(('publish.verified', 'publish.verified', 'publish.failed')):
            owner.execute("INSERT INTO public.pr_notification_events(workspace_id,scope_key,event_type,category,severity,payload,dedupe_key,occurred_at) "
                          "VALUES(%s,'workspace',%s,'publishing','info',%s::jsonb,%s,to_timestamp(%s))",
                          (self.workspace, event, json.dumps({'platform': 'linkedin'}), f'ops-{uuid.uuid4()}', NOW.timestamp() - 900 - index))
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        service = QueryService(store, clock=lambda: NOW)
        principal = {'operator': {'user_id': self.user, 'capabilities': sorted(CAPABILITIES)}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}
        interval = dict(start=(NOW - timedelta(hours=6)).isoformat().replace('+00:00', 'Z'), end=NOW.isoformat().replace('+00:00', 'Z'), timeZone=TZ)

        def run(metric, group_by=(), filters=()):
            result = service.metric_query(dict(metricIds=[metric], interval=interval, groupBy=list(group_by), filters=list(filters), comparison='none', limit=1000),
                                          principal, str(uuid.uuid4()))
            self.assertEqual(result['executionState'], 'admitted_operational')
            return result['rows']
        errors = run('api_error_rate')[0]
        self.assertEqual((errors['coverage']['numerator'], errors['coverage']['denominator']), (3, 101))
        self.assertEqual(errors['dataState'], 'partial', 'collection started inside the interval')
        by_route = {row['dimensions']['route']: row for row in run('api_error_rate', ['route'])}
        self.assertAlmostEqual(by_route['GET /api/health']['value'], 0.02)
        latency = {row['dimensions']['percentile']: row for row in run('api_latency', ['route'], [dict(dimension='route', operator='in', values=['GET /api/health'])])}
        self.assertEqual((latency['p50']['value'], latency['p95']['value']), (9.6, 144.8), 'interpolated inside the summed 2xx+5xx histogram')
        queue = {row['dimensions']['counter']: row for row in run('queue_health', ['queue'])}
        self.assertEqual((queue['queueDelayed']['value'], queue['queueDelayed']['measures']['latest'], queue['queueDelayed']['dimensions']['queue']), (3, 1, 'publishing'))
        self.assertEqual(queue['sms.backlogOver10m']['dimensions']['queue'], 'sms')
        health = run('connection_health', ['provider', 'state'])[0]
        self.assertEqual((health['dimensions'], health['value'], health['measures']), ({'provider': 'linkedin', 'state': 'expiring'}, 1, {'workspaces': 1}))
        support = run('support_aging', ['kind', 'age_band'])
        self.assertEqual([(row['dimensions'], row['value'], row['measures']['ticketSource']) for row in support], [({'kind': 'export', 'age_band': '1d_to_3d'}, 1, 'not_collected')])
        support = run('support_aging', ['source'])
        self.assertEqual([(row['dimensions'], row['value'], row['dataState']) for row in support],
                         [({'source': 'data_requests'}, 1, 'measured'), ({'source': 'support_tickets'}, None, 'unavailable')])
        publish = run('publish_by_provider')[0]
        self.assertEqual((publish['dimensions'], round(publish['value'], 4)), ({'provider': 'linkedin'}, 0.6667))
        burn = {(row['dimensions']['slo'], row['dimensions']['burn_window']): row for row in run('slo_burn')}
        api_30m = burn[('api_availability', '30m')]
        self.assertEqual((api_30m['coverage']['denominator'], api_30m['coverage']['numerator'], api_30m['value']), (100, 2, 4.0), 'cron requests are outside the API availability SLO')
        self.assertEqual(burn[('api_availability', '5m')]['dataState'], 'not_applicable')
        self.assertEqual(burn[('publish_success', '30m')]['reason'], 'low_traffic')
        self.assertEqual(burn[('api_availability', '1h')]['measures']['label'], 'proposed SLO, not approved')


if __name__ == '__main__':
    unittest.main()
