"""P0.7 agent observability on a disposable PostgreSQL: migration 110 (public.pr_agent_metrics and the founder projections over
it and over the 102 GenUI tables), the agent_metrics writer as service_role, and GET /reliability/agent through the restricted
reader role end to end.

Skipped without RAFII_CONTROL_TEST_DSN. scripts/rafii_control_pg.py applies the founder migrations 049-099; this module applies
102 (create-if-not-exists) and 110 itself, twice, because reapplication must be safe.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import types
import unittest
from unittest import mock
import uuid

import psycopg

from postriff_phase2 import agent_metrics
from rafii_control import founder_agent_observability as fao
from rafii_control.store import PostgresStore, connection_factory

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'migrations/postriff/110_agent_observability.sql'
VIEWS = ('business_agent_metrics', 'business_genui_artifacts', 'business_genui_attempts')
NOW = datetime(2026, 10, 10, 12, 0, 30, tzinfo=timezone.utc).timestamp()
PRINCIPAL = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read']}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class AgentObservabilityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        with psycopg.connect(cls.dsn, autocommit=True) as owner:
            owner.execute((ROOT / 'migrations/postriff/102_agent_ui_artifacts.sql').read_text())
            for _ in (0, 1):
                owner.execute(MIGRATION.read_text())

    def connect(self, role=None):
        con = psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None)
        if role:
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def service_factory(self):
        """The consumer runtime's connection as the writer uses it: service_role, not a superuser."""
        con = psycopg.connect(self.dsn, prepare_threshold=None)
        con.execute('SET ROLE service_role')
        return con

    def setUp(self):
        with psycopg.connect(self.dsn, autocommit=True) as owner:
            owner.execute('DELETE FROM public.pr_agent_metrics')
        self.addCleanup(self.forget, None)

    def forget(self, workspace):
        """Leave nothing behind for later suites in this database: the metrics, and the seeded workspace (its runs and views cascade)."""
        with psycopg.connect(self.dsn, autocommit=True) as owner:
            owner.execute('DELETE FROM public.pr_agent_metrics')
            if workspace:
                try:
                    owner.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (workspace,))
                except psycopg.Error:
                    pass

    def test_table_forces_rls_is_unlogged_and_only_service_role_writes(self):
        owner = self.connect()
        flags = owner.execute("SELECT relrowsecurity, relforcerowsecurity, relpersistence FROM pg_class WHERE oid='public.pr_agent_metrics'::regclass").fetchone()
        self.assertEqual(tuple(flags), (True, True, 'u'))
        policies = owner.execute("SELECT policyname, roles::text FROM pg_policies WHERE schemaname='public' AND tablename='pr_agent_metrics'").fetchall()
        self.assertEqual([tuple(row) for row in policies], [('service_only', '{service_role}')])
        for role in ('anon', 'authenticated', 'rafii_control_reader', 'rafii_control_session'):
            self.assertFalse(owner.execute("SELECT has_table_privilege(%s, 'public.pr_agent_metrics', 'SELECT,INSERT,UPDATE,DELETE')", (role,)).fetchone()[0], role)
        for role in ('anon', 'authenticated'):
            with self.subTest(role=role), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.connect(role).execute('SELECT * FROM public.pr_agent_metrics')

    def test_checks_refuse_text_ids_and_malformed_histograms(self):
        owner = self.connect()
        insert = 'INSERT INTO public.pr_agent_metrics(minute,metric,label,event_count,value_sum,value_buckets) VALUES(now()-%s::interval,%s,%s,1,0,%s)'
        owner.execute(insert, ('1 minute', 'agent.tool', 'library_search:verified', [0] * 20))
        bad = (('agent.tool', 'Write a post about my album'), ('agent.tool', 'james@example.com'), ('agent.tool', 'Library_Search:verified'),
               ('agent.tool', ''), ('tool', 'x:y'), ('agent.Tool', 'x'), ('agent.tool', 'x' * 121), ('agent.tool', 'https://example.com/a'))
        for index, (metric, label) in enumerate(bad):
            with self.subTest(label=label), self.assertRaises(psycopg.errors.CheckViolation):
                owner.execute(insert, (f'{index + 2} minutes', metric, label, [0] * 20))
        for index, value in enumerate(([0] * 19, [-1] + [0] * 19)):
            with self.assertRaises(psycopg.errors.CheckViolation):
                owner.execute(insert, (f'{index + 20} minutes', 'agent.tool', 'x:y', value))

    def test_writer_merges_flushes_as_service_role(self):
        at = NOW - 120
        first, second = (agent_metrics.Recorder(clock=lambda: at, spawn=lambda work: work()) for _ in (0, 1))
        first.record('agent.turn', 'manager:completed', 1200)
        second.record('agent.turn', 'manager:completed', 64000)
        second.record('agent.authz', 'shadow:deny:category_off')
        self.assertTrue(first.maybe_flush(self.service_factory))
        self.assertTrue(second.maybe_flush(self.service_factory))
        rows = self.connect().execute('SELECT metric,label,event_count,value_sum,value_buckets FROM public.pr_agent_metrics ORDER BY 1,2').fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [('agent.authz', 'shadow:deny:category_off', 1), ('agent.turn', 'manager:completed', 2)])
        turn = rows[1]
        self.assertEqual((round(turn[3]), turn[4][agent_metrics.bucket_index(1200)], turn[4][agent_metrics.bucket_index(64000)]), (65200, 1, 1),
                         'buckets add element-wise across instances')

    def test_writer_treats_a_missing_privilege_as_not_installed(self):
        def as_reader():
            con = psycopg.connect(self.dsn, prepare_threshold=None)
            con.execute('SET ROLE rafii_control_reader')
            return con
        recorder = agent_metrics.Recorder(clock=lambda: NOW, spawn=lambda work: work(), logger=mock.Mock())
        recorder.record('agent.turn', 'manager:completed', 10)
        recorder.maybe_flush(as_reader)
        self.assertEqual(recorder.paused_until, NOW + agent_metrics.NOT_INSTALLED_PAUSE)
        self.assertEqual(self.connect().execute('SELECT count(*) FROM public.pr_agent_metrics').fetchone()[0], 0)

    def test_projections_are_projection_owned_reader_readable_and_column_bounded(self):
        owner = self.connect()
        for view in VIEWS:
            with self.subTest(view=view):
                row = owner.execute("SELECT pg_get_userbyid(c.relowner), c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                    "WHERE n.nspname='rafii_control' AND c.relname=%s AND c.relkind='v'", (view,)).fetchone()
                self.assertEqual(row[0], 'rafii_control_business_projection')
                self.assertIn('security_barrier=true', row[1])
                for role in ('anon', 'authenticated', 'service_role', 'rafii_control_session'):
                    self.assertFalse(owner.execute('SELECT has_table_privilege(%s, %s, \'SELECT\')', (role, 'rafii_control.' + view)).fetchone()[0], role)
        reader = self.connect('rafii_control_reader')
        columns = {view: [d.name for d in reader.execute(f'SELECT * FROM rafii_control.{view} LIMIT 0').description] for view in VIEWS}
        self.assertEqual(columns['business_agent_metrics'], ['minute', 'metric', 'label', 'eventCount', 'valueSum', 'valueBuckets'])
        self.assertEqual(columns['business_genui_artifacts'], ['id', 'workspaceId', 'scope', 'surface', 'generationState', 'validationState', 'reasonCode',
                                                               'revision', 'createdAt', 'updatedAt'])
        self.assertEqual(columns['business_genui_attempts'], ['id', 'artifactId', 'workspaceId', 'kind', 'state', 'reasonCode', 'providerAttempts', 'costState',
                                                              'createdAt', 'readyAt', 'finishedAt'])
        for query in ('SELECT instruction FROM public.pr_ui_attempts', 'SELECT fallback_text FROM public.pr_ui_artifacts', 'SELECT * FROM public.pr_agent_metrics'):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.connect('rafii_control_reader').execute(query)

    def test_summary_through_the_reader_role_end_to_end(self):
        owner = self.connect()
        user = str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
        workspace = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        self.addCleanup(self.forget, workspace)
        conversation = owner.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'PRIVATE conversation title') RETURNING id::text",
                                     (workspace, user)).fetchone()[0]
        run = owner.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key) "
                            "VALUES(%s,%s,%s,'completed','rafii-agent','standard',%s,%s,%s) RETURNING id::text",
                            (conversation, workspace, user, 'a' * 64, 'b' * 64, 'agent:' + uuid.uuid4().hex)).fetchone()[0]
        at = datetime.fromtimestamp(NOW - 600, tz=timezone.utc)
        artifact = owner.execute("INSERT INTO public.pr_ui_artifacts(workspace_id,conversation_id,parent_run_id,actor,surface,generation_state,validation_state,reason,"
                                 "fallback_text,manifest,created_at) VALUES(%s,%s,%s,%s,'panel','failed','rejected','validation_failed','PRIVATE fallback text',"
                                 "'{\"secret\":\"PRIVATE\"}',%s) RETURNING id::text", (workspace, conversation, run, user, at)).fetchone()[0]
        owner.execute("INSERT INTO public.pr_ui_attempts(artifact_id,workspace_id,kind,target_revision,state,reason,idempotency_key,lease_owner,lease_expires_at,"
                      "instruction,provider_attempts,created_at) VALUES(%s,%s,'generate',1,'failed','Free text with PRIVATE words',%s,'owner',now(),'PRIVATE instruction',2,%s)",
                      (artifact, workspace, uuid.uuid4().hex, at))
        recorder = agent_metrics.Recorder(clock=lambda: NOW - 300, spawn=lambda work: work())
        for label, value in (('manager:completed', 4000), ('manager:completed', 9000), ('manager:failed', 3000)):
            recorder.record('agent.turn', label, value)
        recorder.record('agent.tool', 'library_search:verified', 120)
        recorder.record('agent.tool', 'draft_create:unverified', 900)
        recorder.record('agent.authz', 'legacy:deny:tool_forbidden')
        recorder.record('agent.outcome', 'verified')
        recorder.record('agent.outcome', 'unverified')
        self.assertTrue(recorder.maybe_flush(self.service_factory))
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        app = types.SimpleNamespace(queries=types.SimpleNamespace(store=store))
        out = fao.summary(app, PRINCIPAL, dict(method='GET', path='/reliability/agent', body={}, query={'window': ['1h']}, match=(), mode='live', now=NOW,
                                               requestId=str(uuid.uuid4()), environ={}))
        agent = out['sections']['agent']
        self.assertEqual(agent['dataState'], 'measured')
        self.assertEqual((agent['turns']['total'], agent['turns']['completed'], agent['turns']['successRate']), (3, 2, 0.6667))
        self.assertEqual((agent['tools']['calls'], agent['tools']['errors']), (2, 1))
        self.assertEqual(agent['permissions']['byReason'], [{'mode': 'legacy', 'outcome': 'deny', 'reason': 'tool_forbidden', 'count': 1}])
        self.assertEqual(agent['completionAccuracy']['verifiedShare'], 0.5)
        genui = out['sections']['genui']
        self.assertEqual(genui['artifacts']['validation'].get('rejected'), 1)
        self.assertEqual(genui['artifacts']['rejectionReasons'], [{'reason': 'validation_failed', 'count': 1}])
        failed = next(a for a in genui['attempts'] if a['kind'] == 'generate')
        self.assertEqual((failed['states'].get('failed'), failed['providerRetries']), (1, 1))
        self.assertIn(out['sections']['providerCalls']['dataState'], ('measured', 'not_instrumented'))
        self.assertIn(out['sections']['runs']['dataState'], ('measured', 'not_instrumented'))
        text = json.dumps(out)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn(workspace, text)
        self.assertNotIn(user, text)
        reason = self.connect('rafii_control_reader').execute('SELECT "reasonCode" FROM rafii_control.business_genui_attempts WHERE "artifactId"=%s', (artifact,)).fetchone()[0]
        self.assertIsNone(reason, 'free text in a reason column reads NULL')

    def test_group_limit_sentinel_withholds_truncated_totals(self):
        with self.service_factory() as con:
            con.execute("INSERT INTO public.pr_agent_metrics(minute,metric,label,event_count,value_sum,value_buckets) "
                        "SELECT to_timestamp(%s),'agent.tool','tool_' || i::text || ':verified',1,0,%s::bigint[] "
                        "FROM generate_series(1,%s) AS i", (NOW - 120, [0] * 20, fao.LIMIT + 1))
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        out = fao.summary(types.SimpleNamespace(queries=types.SimpleNamespace(store=store)), PRINCIPAL,
                          dict(query={'window': ['1h']}, mode='live', now=NOW))
        self.assertEqual(out['sections']['agent'], {'dataState': 'partial', 'reason': 'source_truncated',
                                                    'groupLimit': fao.LIMIT, 'totalsAvailable': False})
        self.assertEqual(out['_dataState'], 'partial')


if __name__ == '__main__':
    unittest.main()
