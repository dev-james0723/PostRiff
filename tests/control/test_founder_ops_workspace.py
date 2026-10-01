"""Founder ops workspace (CONTRACTS §8.H): resolution order, one-time creation, idempotency and its PostgreSQL round trip."""
import os
import unittest
import uuid
from contextlib import contextmanager

from rafii_control import founder_ops
from rafii_control.auth import ControlError

OPERATOR = '00000000-0000-4000-8000-0000000000aa'
PRINCIPAL = {'operator': {'user_id': OPERATOR, 'capabilities': ['control.read', 'control.settings']}, 'session': {'environment': 'local'}}


class Row(dict):
    pass


class FakeSettingsStore:
    environment = 'local'

    def __init__(self, ops=None, fail=False):
        self.ops, self.fail, self.statements = ops, fail, []

    @contextmanager
    def transaction(self, read=False):
        if self.fail:
            raise RuntimeError('relation "rafii_control.founder_settings" does not exist')
        yield self

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if sql.startswith('INSERT INTO rafii_control.founder_settings'):
            self.ops = params[2]
        return self

    def fetchone(self):
        return Row(ops=self.ops) if self.ops else None


class FakeCursor:
    def __init__(self, log):
        self.log, self.last = log, None

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=()):
        self.log.append((sql, params))
        self.last = sql

    def fetchone(self):
        if self.last.startswith('SELECT 1 FROM public.pr_profiles'):
            return (1,)
        if self.last.startswith('INSERT INTO public.pr_workspaces'):
            return ('11111111-2222-4333-8444-555555555555',)
        return None


class FakeConnection:
    def __init__(self, log): self.log, self.committed = log, False
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def cursor(self): return FakeCursor(self.log)
    def commit(self): self.committed = True


class FakeService:
    def __init__(self):
        self.log = []
        self.connection_factory = lambda: FakeConnection(self.log)


class FakeApp:
    def __init__(self, store, flags=None, runtime=True):
        self.queries = type('Q', (), {'store': store})()
        self.flags = dict(flags or {})
        self.service = FakeService()
        self.runtime = (lambda: self.service) if runtime else None

    def consumer(self):
        return self.runtime()


class ResolveTests(unittest.TestCase):
    def test_the_deployment_variable_wins_then_the_stored_setting(self):
        store = FakeSettingsStore(ops='22222222-3333-4444-8555-666666666666')
        env = {'RAFII_FOUNDER_OPS_WORKSPACE_ID': '33333333-4444-4555-8666-777777777777'}
        self.assertEqual(founder_ops.resolve(env, store, OPERATOR), ('33333333-4444-4555-8666-777777777777', 'environment'))
        self.assertEqual(founder_ops.resolve({}, store, OPERATOR), ('22222222-3333-4444-8555-666666666666', 'settings'))
        self.assertEqual(founder_ops.resolve({'RAFII_FOUNDER_OPS_WORKSPACE_ID': 'not-a-uuid'}, FakeSettingsStore(), OPERATOR), (None, None))

    def test_a_missing_table_or_store_means_not_configured_never_an_error(self):
        self.assertEqual(founder_ops.resolve({}, FakeSettingsStore(fail=True), OPERATOR), (None, None))
        self.assertEqual(founder_ops.resolve({}, None, OPERATOR), (None, None))


class CreateTests(unittest.TestCase):
    def test_creates_one_internal_workspace_with_no_publishing_rights_and_remembers_it(self):
        store = FakeSettingsStore()
        app = FakeApp(store)
        out = founder_ops.create_ops(app, PRINCIPAL, {'mode': 'live', 'now': 0})
        self.assertEqual((out['created'], out['source'], out['name']), (True, 'settings', founder_ops.OPS_NAME))
        sql = [statement for statement, _ in app.service.log]
        self.assertTrue(any(s.startswith('INSERT INTO public.pr_workspaces') for s in sql))
        membership = next(params for statement, params in app.service.log if statement.startswith('INSERT INTO public.pr_memberships'))
        self.assertEqual(membership, (out['workspaceId'], OPERATOR))
        self.assertIn("'owner','active',false,false,false,false", next(s for s in sql if s.startswith('INSERT INTO public.pr_memberships')))
        self.assertTrue(any('pr_audit_events' in s for s in sql), 'creation is audited in the consumer audit trail')
        self.assertFalse(any('pr_trials' in s or 'pr_subscriptions' in s for s in sql), 'no trial or subscription is ever created')
        self.assertTrue(any("'internal'" in s for s, _ in store.statements), 'the workspace is classified internal')
        self.assertEqual(store.ops, out['workspaceId'])

    def test_a_second_call_returns_the_existing_workspace_and_demo_or_no_runtime_is_refused(self):
        store = FakeSettingsStore(ops='22222222-3333-4444-8555-666666666666')
        app = FakeApp(store)
        again = founder_ops.create_ops(app, PRINCIPAL, {'mode': 'live', 'now': 0})
        self.assertEqual((again['created'], again['workspaceId']), (False, '22222222-3333-4444-8555-666666666666'))
        self.assertEqual(app.service.log, [])
        with self.assertRaises(ControlError):
            founder_ops.create_ops(FakeApp(FakeSettingsStore()), PRINCIPAL, {'mode': 'demo', 'now': 0})
        with self.assertRaises(ControlError):
            founder_ops.create_ops(FakeApp(FakeSettingsStore(), runtime=False), PRINCIPAL, {'mode': 'live', 'now': 0})

    def test_get_reports_the_source_and_whether_it_can_be_created(self):
        self.assertEqual(founder_ops.get_ops(FakeApp(FakeSettingsStore()), PRINCIPAL, {})['canCreate'], True)
        configured = founder_ops.get_ops(FakeApp(FakeSettingsStore(), flags={'RAFII_FOUNDER_OPS_WORKSPACE_ID': '33333333-4444-4555-8666-777777777777'}), PRINCIPAL, {})
        self.assertEqual((configured['source'], configured['canCreate']), ('environment', False))


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class OpsWorkspacePostgresTests(unittest.TestCase):
    """069 keeps pr_bootstrap on the user's own trial workspace; 070 stores the setting; creation commits for real."""

    def setUp(self):
        import psycopg
        from rafii_control.auth import CAPABILITIES
        from rafii_control.store import PostgresStore, connection_factory
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        self.user = str(uuid.uuid4())
        with psycopg.connect(self.dsn, autocommit=True) as owner:
            owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))
            owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)", (self.user, sorted(CAPABILITIES)))
            self.primary = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0])
        self.store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        self.principal = {'operator': {'user_id': self.user, 'capabilities': sorted(CAPABILITIES)}, 'session': {'environment': 'local'}}

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.dsn, autocommit=True) as owner:
            owner.execute('DELETE FROM rafii_control.founder_settings WHERE operator_id=%s', (self.user,))

    def test_create_commits_a_classified_internal_workspace_and_bootstrap_keeps_the_trial_workspace(self):
        import psycopg

        class Service:
            def __init__(self, dsn): self.connection_factory = lambda: psycopg.connect(dsn, autocommit=False)

        app = FakeApp(self.store)
        app.service = Service(self.dsn)
        app.runtime = lambda: app.service
        out = founder_ops.create_ops(app, self.principal, {'mode': 'live', 'now': 0})
        self.assertTrue(out['created'])
        self.assertEqual(founder_ops.resolve({}, self.store, self.user), (out['workspaceId'], 'settings'))
        with psycopg.connect(self.dsn, autocommit=True) as owner:
            kind = owner.execute('SELECT kind FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (out['workspaceId'],)).fetchone()[0]
            member = owner.execute('SELECT role,status,can_publish FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s', (out['workspaceId'], self.user)).fetchone()
            self.assertEqual(kind, 'internal')
            self.assertEqual(tuple(member), ('owner', 'active', False))
            # The second membership never becomes the default: bootstrap answers the trial workspace every time.
            for _ in range(3):
                self.assertEqual(str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0]), self.primary)
        self.assertFalse(founder_ops.create_ops(app, self.principal, {'mode': 'live', 'now': 0})['created'])


if __name__ == '__main__':
    unittest.main()
