"""Real restricted-role assertions, run only against an explicitly disposable cluster."""
import os
import unittest
import psycopg
from rafii_control.auth import Boundary, Config, VerifiedIdentity, ControlError
from rafii_control.store import PostgresStore, connection_factory
from rafii_control.intelligence import QueryService
from control.test_boundary import CAPS
import time
import uuid
import json
from pathlib import Path


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class DatabaseTests(unittest.TestCase):
    def connect(self, role=None):
        con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], autocommit=True, prepare_threshold=None)
        if role:
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def test_control_tables_force_rls_and_never_grant_browser_access(self):
        owner = self.connect()
        rows = owner.execute("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='rafii_control' AND relkind='r'").fetchall()
        self.assertGreaterEqual(len(rows), 6)
        self.assertTrue(all(row[1] and row[2] for row in rows))
        for role in ('anon', 'authenticated', 'service_role'):
            con = self.connect(role)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                con.execute('SELECT * FROM rafii_control.platform_operators')

    def test_reader_cannot_read_customer_content_or_mutate_any_source(self):
        reader = self.connect('rafii_control_reader')
        users = reader.execute('SELECT * FROM rafii_control.safe_users LIMIT 200').fetchall()
        self.assertTrue(users)
        for query in ('SELECT state FROM public.pr_workspaces', 'SELECT body FROM public.pr_jobs',
                      'SELECT * FROM rafii_control.founder_sessions', 'DELETE FROM public.pr_profiles',
                      'UPDATE rafii_control.source_health SET state=\'measured\''):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): reader.execute(query)
        self.assertFalse(reader.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()[0])

    def test_session_role_cannot_change_operator_or_audit_history(self):
        con = self.connect('rafii_control_session')
        for query in ('UPDATE rafii_control.platform_operators SET auth_epoch=2',
                      'DELETE FROM rafii_control.admin_audit_log', 'UPDATE rafii_control.admin_audit_log SET result=\'allowed\'',
                      'SELECT state FROM public.pr_workspaces'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): con.execute(query)

    def test_function_acl_and_search_path_are_fixed(self):
        owner = self.connect()
        config = owner.execute("SELECT proconfig FROM pg_proc WHERE oid='rafii_control.identity_active(uuid,text)'::regprocedure").fetchone()[0]
        self.assertIn('search_path=""', config)
        for role in ('anon', 'authenticated', 'service_role', 'rafii_control_reader'):
            self.assertFalse(owner.execute('SELECT has_function_privilege(%s, %s, \'EXECUTE\')', (role, 'rafii_control.identity_active(uuid,text)')).fetchone()[0])
        session = self.connect('rafii_control_session')
        self.assertTrue(session.execute("SELECT rafii_control.identity_active('00000000-0000-0000-0000-000000000001', 'local-upstream-session-0001')").fetchone()[0])

    def store(self):
        dsn=os.environ['RAFII_CONTROL_TEST_DSN']
        return PostgresStore(connection_factory(dsn,'rafii_control_session','local'),connection_factory(dsn,'rafii_control_reader','local'),'local')

    def test_real_store_boundary_safe_projection_receipts_and_idempotency(self):
        owner=self.connect()
        user='00000000-0000-0000-0000-000000000001'
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s) ON CONFLICT(user_id,environment) DO UPDATE SET status='active',capabilities=excluded.capabilities",(user,CAPS))
        owner.execute("UPDATE public.pr_workspaces SET state='{"+'"privateCanary":"DO_NOT_DISCLOSE_CUSTOMER_SECRET_8675309"'+"}'::jsonb")
        store=self.store()
        boundary=Boundary(Config(True,'local','http://localhost:4449'),store,lambda token:VerifiedIdentity(user,'aal2','synthetic-upstream-session-001',time.time()))
        token,_=boundary.exchange('synthetic-test-identity','http://localhost:4449')
        principal=boundary.authorize(token,'customers.read')
        queries=QueryService(store)
        result=queries.dispatch('/users/'+user,{},principal,str(uuid.uuid4()))
        self.assertEqual(result['privateContent']['dataState'],'suppressed')
        self.assertNotIn('DO_NOT_DISCLOSE',str(result))
        request={'requestId':str(uuid.uuid4()),'conversationId':str(uuid.uuid4()),'message':'Inspect check failures','contextEvidenceIds':[],'modality':'text'}
        first=queries.copilot_turn(request,principal)
        second=queries.copilot_turn(request,principal)
        self.assertEqual(first['runId'],second['runId'])
        self.assertTrue(store.read('receipt',first['queryReceiptIds'][0]))
        request['message']='Different request under same key'
        with self.assertRaisesRegex(ControlError,'IDEMPOTENCY_CONFLICT'): queries.copilot_turn(request,principal)
        owner.execute("UPDATE rafii_control.platform_operators SET auth_epoch=auth_epoch+1 WHERE user_id=%s",(user,))
        with self.assertRaises(ControlError): boundary.authorize(token,'control.read')

    def test_atomic_rate_budget_and_unsafe_factory_fail_closed(self):
        store=self.store()
        actor=str(uuid.uuid4())
        store.budget('metrics.query',actor,1)
        with self.assertRaisesRegex(ControlError,'RATE_LIMITED'):store.budget('metrics.query',actor,1)
        bad=PostgresStore(lambda: self.connect(),lambda:self.connect(),'local')
        with self.assertRaisesRegex(ControlError,'SOURCE_UNAVAILABLE'): bad.read('users')

    def test_ingestion_dedupe_cursor_and_fixture_environment_isolation(self):
        from rafii_control.projections import Projector
        dsn=os.environ['RAFII_CONTROL_TEST_DSN']
        projector=Projector(connection_factory(dsn,'rafii_control_ingest','local'),'local')
        pack=Path(__file__).resolve().parents[2]/'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2'
        event=json.loads((pack/'examples/event-envelope.json').read_text())
        event.update(environment='local',eventType='control.source.stale',payload={'sourceId':'sentry','reasonCode':'lagging'})
        self.assertTrue(projector.ingest(event))
        replay={**event,'receivedAt':'2026-09-29T12:00:01Z','eventId':str(uuid.uuid4())}
        self.assertFalse(projector.ingest(replay))
        with self.assertRaisesRegex(ControlError,'IDEMPOTENCY_CONFLICT'):projector.ingest({**event,'payload':{'sourceId':'sentry','reasonCode':'provider_unavailable'}})
        con=self.connect()
        self.assertEqual(con.execute('SELECT count(*) FROM rafii_control.normalized_events').fetchone()[0],1)
        self.assertTrue(con.execute('SELECT received_watermark FROM rafii_control.ingestion_cursors').fetchone()[0])
        reader=self.connect('rafii_control_reader')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):reader.execute('DELETE FROM rafii_control.normalized_events')
        ingest=self.connect('rafii_control_ingest')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):ingest.execute('SELECT state FROM public.pr_workspaces')
