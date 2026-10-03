"""Founder ops workspace (CONTRACTS §8.H): resolution order, one-time creation, idempotency and its PostgreSQL round trip."""
import os
import time
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
        self.visible, self.last = bool(ops), ''

    @contextmanager
    def transaction(self, read=False):
        if self.fail:
            raise RuntimeError('relation "rafii_control.founder_settings" does not exist')
        yield self

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        self.last = sql
        if sql.startswith('INSERT INTO rafii_control.founder_settings'):
            self.ops = params[2]
        return self

    def fetchone(self):
        if self.last.startswith('SELECT kind,environment'):
            return Row(kind='internal', environment=self.environment)
        if self.last.startswith('SELECT w.id'):
            return Row(role='owner', status='active', deleted=False, kind='internal', environment=self.environment) if self.visible else None
        return Row(ops=self.ops) if self.ops else None


class FakeCursor:
    def __init__(self, log, store=None):
        self.log, self.last, self.store = log, None, store

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=()):
        self.log.append((sql, params))
        self.last = sql

    def fetchone(self):
        if self.last.startswith('SELECT 1 FROM public.pr_profiles'):
            return (1,)
        if self.last.startswith('INSERT INTO public.pr_workspaces'):
            return None if self.store and self.store.visible else ('11111111-2222-4333-8444-555555555555',)
        if self.last.startswith('SELECT role,status,can_publish'):
            return ('owner', 'active', False, False, False, False)
        if self.last.startswith('SELECT EXISTS'):
            return (False,)
        return None


class FakeConnection:
    def __init__(self, log, store=None): self.log, self.committed, self.store = log, False, store
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def cursor(self): return FakeCursor(self.log, self.store)
    def commit(self):
        self.committed = True
        if self.store:
            self.store.visible = True


class FakeService:
    def __init__(self):
        self.log = []
        self.connection_factory = lambda: FakeConnection(self.log)


class FakeApp:
    def __init__(self, store, flags=None, runtime=True):
        self.queries = type('Q', (), {'store': store})()
        self.flags = dict(flags or {})
        self.service = FakeService()
        self.service.connection_factory = lambda: FakeConnection(self.service.log, store)
        self.runtime = (lambda: self.service) if runtime else None

    def consumer(self):
        return self.runtime()


class ResolveTests(unittest.TestCase):
    def test_the_deployment_variable_wins_then_the_stored_setting(self):
        store = FakeSettingsStore(ops='22222222-3333-4444-8555-666666666666')
        env = {'RAFII_FOUNDER_OPS_WORKSPACE_ID': '33333333-4444-4555-8666-777777777777'}
        self.assertEqual(founder_ops.resolve(env, store, OPERATOR), ('33333333-4444-4555-8666-777777777777', 'environment'))
        self.assertEqual(founder_ops.resolve({}, store, OPERATOR), ('22222222-3333-4444-8555-666666666666', 'settings'))
        with self.assertRaises(ControlError):
            founder_ops.resolve({'RAFII_FOUNDER_OPS_WORKSPACE_ID': 'not-a-uuid'}, FakeSettingsStore(), OPERATOR)

    def test_unavailable_settings_never_look_unconfigured(self):
        with self.assertRaises(ControlError) as caught:
            founder_ops.resolve({}, FakeSettingsStore(fail=True), OPERATOR)
        self.assertEqual((caught.exception.code, caught.exception.status), ('SOURCE_UNAVAILABLE', 503))


class CreateTests(unittest.TestCase):
    def test_creates_one_internal_workspace_with_unlimited_owner_entitlement_and_remembers_it(self):
        store = FakeSettingsStore()
        app = FakeApp(store)
        out = founder_ops.create_ops(app, PRINCIPAL, {'mode': 'live', 'now': 0})
        self.assertEqual((out['created'], out['source'], out['name']), (True, 'settings', founder_ops.OPS_NAME))
        sql = [statement for statement, _ in app.service.log]
        self.assertTrue(any(s.startswith('INSERT INTO public.pr_workspaces') for s in sql))
        membership = next(params for statement, params in app.service.log if statement.startswith('INSERT INTO public.pr_memberships'))
        self.assertEqual(membership, (out['workspaceId'], OPERATOR))
        self.assertIn("'owner','active',true,true,true,true", next(s for s in sql if s.startswith('INSERT INTO public.pr_memberships')))
        self.assertTrue(any('pr_audit_events' in s for s in sql), 'creation is audited in the consumer audit trail')
        self.assertFalse(any(s.startswith('INSERT') and ('pr_trials' in s or 'pr_subscriptions' in s) for s in sql), 'no trial or subscription is ever created')
        self.assertTrue(any("'internal'" in s for s, _ in store.statements), 'the workspace is classified internal')
        self.assertEqual(store.ops, out['workspaceId'])

    def test_a_second_call_returns_the_existing_workspace_and_demo_or_no_runtime_is_refused(self):
        store = FakeSettingsStore(ops='22222222-3333-4444-8555-666666666666')
        app = FakeApp(store)
        again = founder_ops.create_ops(app, PRINCIPAL, {'mode': 'live', 'now': 0})
        self.assertEqual((again['created'], again['workspaceId']), (False, '22222222-3333-4444-8555-666666666666'))
        self.assertFalse(any('INSERT INTO public.pr_memberships' in s for s, _ in app.service.log))
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
            # New accounting tests must not leak their synthetic settlements
            # into later whole-database projection fixtures.
            ids = [str(row[0]) for row in owner.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (self.user,)).fetchall()]
            for workspace in ids:
                owner.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (workspace,))
                owner.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,))
            owner.execute('DELETE FROM rafii_control.founder_settings WHERE operator_id=%s', (self.user,))

    def app(self):
        import psycopg
        app = FakeApp(self.store)
        app.service = type('Service', (), {'connection_factory': staticmethod(lambda: psycopg.connect(self.dsn))})()
        app.runtime = lambda: app.service
        return app

    def test_concurrent_requests_converge_without_customer_kpi_or_trial_growth(self):
        import psycopg
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: founder_ops.create_ops(self.app(), self.principal, {'mode': 'live'}), range(2)))
        self.assertEqual(len({r['workspaceId'] for r in results}), 1)
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_memberships WHERE user_id=%s', (self.user,)).fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trials WHERE user_id=%s', (self.user,)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_subscriptions s JOIN public.pr_memberships m ON m.workspace_id=s.workspace_id WHERE m.user_id=%s', (self.user,)).fetchone()[0], 0)

    def test_crash_before_consumer_write_keeps_an_internal_identity_and_resume_reuses_it(self):
        import psycopg
        app = self.app()
        def unavailable():
            raise RuntimeError('synthetic consumer unavailable')
        app.service.connection_factory = unavailable
        with self.assertRaises(ControlError):
            founder_ops.create_ops(app, self.principal, {'mode': 'live'})
        with psycopg.connect(self.dsn) as db:
            row = db.execute('SELECT s.ops_workspace_id,c.kind FROM rafii_control.founder_settings s JOIN rafii_control.workspace_classifications c ON c.workspace_id=s.ops_workspace_id WHERE s.operator_id=%s', (self.user,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], 'internal')
            reserved = str(row[0])
            self.assertIsNone(db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s', (reserved,)).fetchone())
        self.assertIsNone(founder_ops.resolve({}, self.store, self.user)[0], 'reserved is not a usable runtime workspace')
        self.assertEqual(founder_ops.create_ops(self.app(), self.principal, {'mode': 'live'})['workspaceId'], reserved)

    def test_customer_or_foreign_environment_override_is_refused(self):
        with self.assertRaises(ControlError):
            founder_ops.resolve({founder_ops.ENV: self.primary}, self.store, self.user)

    def test_internal_ai_has_unlimited_entitlement_and_durable_daily_spend_guard(self):
        import psycopg
        from unittest.mock import patch
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.billing import Ledger, require_plan_capacity, require_publishing
        from rafii_control import founder_policy
        app = self.app()
        wid = founder_ops.create_ops(app, self.principal, {'mode': 'live'})['workspaceId']
        changed = founder_policy.save_policy(app, self.principal, {'body': {'mode': 'live', 'revision': 1, 'changes': {'dailySpendUsdMicro': 150}}})
        self.assertEqual(changed['revision'], 2)
        with self.assertRaises(ControlError):
            founder_policy.save_policy(app, self.principal, {'body': {'mode': 'live', 'revision': 1, 'changes': {}}})
        ledger = Ledger(credits_enabled=True)
        with patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': self.user, 'POSTRIFF_BUDGET_POLICY': 'launch-2026-09-24'}), psycopg.connect(self.dsn) as db:
            cur = db.cursor()
            reservation = ledger.reserve(cur, wid, self.user, 'text_model', 100, 'synthetic:bounded', charge_batch=True)
            self.assertTrue(reservation['entitlement']['unlimited'])
            ident = reservation['reservationId']
            ledger.settle(cur, wid, ident, 'completed')
            self.assertTrue(ledger.settle(cur, wid, ident, 'unknown', idempotency_key='another-key')['duplicate'])
            self.assertEqual(cur.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE reservation_id::text=%s AND cost_state='estimated_unknown'", (ident,)).fetchone()[0], 1)
            with self.assertRaises(AlphaError):
                ledger.reserve(cur, wid, self.user, 'text_model', 100, 'synthetic:over-daily-cap', charge_batch=False)
            # Unknown cost and a full cap do not block cost-free work or publishing entitlement.
            ledger.reserve(cur, wid, self.user, 'action', 0, 'synthetic:free-action', charge_batch=True)
            require_plan_capacity(cur, wid, 'connected_accounts')
            require_publishing(cur, wid, time.time())
            ledger.reconcile_unknown(cur, wid, ident, 'completed', 70, operator='synthetic-test', evidence='synthetic-provider-receipt')
            for kind, meta in cur.execute('SELECT kind,meta FROM public.pr_usage_ledger WHERE reservation_id::text=%s ORDER BY at', (ident,)).fetchall():
                self.assertTrue(meta['aiUsageExempt'])
                self.assertEqual((meta['actorClass'], meta['costCenter'], meta['environment'], meta['attributionVersion']), ('founder', 'founder_ops', 'local', 2))
            self.assertTrue(ledger.settle(cur, wid, ident, 'completed', 70)['duplicate'])
            allowed = ledger.reserve(cur, wid, self.user, 'text_model', 80, 'synthetic:remaining-daily-cap', charge_batch=False)
            self.assertTrue(allowed['warnings'])
            with self.assertRaises(AlphaError):
                ledger.reserve(cur, wid, self.user, 'tool', 1, 'synthetic:exhausted', charge_batch=False)
            self.assertEqual(cur.execute('SELECT count(*) FROM public.pr_subscriptions WHERE workspace_id=%s', (wid,)).fetchone()[0], 0)
            self.assertEqual(cur.execute('SELECT count(*) FROM public.pr_entitlements WHERE workspace_id=%s', (wid,)).fetchone()[0], 0)

    def test_cancelled_dead_turn_keeps_founder_attribution_and_unknown_spend_hold(self):
        import psycopg
        from types import SimpleNamespace
        from unittest.mock import patch
        from postriff_phase2.agent_runtime_v2.config import RuntimeConfig
        from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
        from postriff_phase2.billing import Ledger
        from postriff_phase2.founder_policy import policy_from_marker, spending
        wid = founder_ops.create_ops(self.app(), self.principal, {'mode': 'live'})['workspaceId']
        ledger = Ledger()
        runtime = AgentRuntimeService(SimpleNamespace(ledger=ledger), RuntimeConfig.from_environment({}))
        with patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': self.user}), psycopg.connect(self.dsn) as db:
            cur = db.cursor()
            conversation = str(cur.execute('INSERT INTO public.pr_conversations(workspace_id,created_by) VALUES(%s,%s) RETURNING id', (wid, self.user)).fetchone()[0])
            run = str(cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,updated_at) "
                                  "VALUES(%s,%s,%s,'cancelled','rafii-agent','standard',%s,%s,%s,now()-interval '1 hour') RETURNING id",
                                  (conversation, wid, self.user, 'a' * 64, 'b' * 64, 'agent:' + uuid.uuid4().hex)).fetchone()[0])
            reservation = ledger.reserve(cur, wid, self.user, 'text_model', 50_000, 'agent:' + run,
                                         charge_batch=True, provider='openai', model='gpt-6-sol', run_id=run)
            marker = cur.execute("SELECT state->'founderOps' FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
            before = spending(cur, wid, policy_from_marker(marker))
            runtime._reap_stale_turns(cur, wid)
            runtime._reap_stale_turns(cur, wid)
            entries = cur.execute("SELECT cost_state,actual_usd_micro,estimated_usd_micro,meta->>'actorClass',meta->>'costCenter',meta->>'aiUsageExempt' "
                                  "FROM public.pr_usage_ledger WHERE reservation_id::text=%s AND kind='settle'", (reservation['reservationId'],)).fetchall()
            self.assertEqual(entries, [('estimated_unknown', None, 50_000, 'founder', 'founder_ops', 'true')])
            self.assertEqual(spending(cur, wid, policy_from_marker(marker)), before)
            self.assertEqual((before['actualUsdMicro'], before['heldUsdMicro']), (0, 50_000))

    def test_settings_unlimited_mode_and_concurrent_cost_holds_are_serialized(self):
        import psycopg
        from concurrent.futures import ThreadPoolExecutor
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.billing import Ledger
        from rafii_control import founder_policy
        app = self.app()
        wid = founder_ops.create_ops(app, self.principal, {'mode': 'live'})['workspaceId']
        founder_policy.save_policy(app, self.principal, {'body': {'mode': 'live', 'revision': 1, 'changes': {'dailySpendUsdMicro': 100}}})
        def reserve(key):
            try:
                with psycopg.connect(self.dsn) as db:
                    with db.cursor() as cur:
                        Ledger().reserve(cur, wid, self.user, 'tool', 80, key, charge_batch=False)
                return 'reserved'
            except AlphaError:
                return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(reserve, ['synthetic:concurrent1', 'synthetic:concurrent2'])), ['blocked', 'reserved'])
        result = founder_policy.get_policy(app, self.principal, {})
        self.assertEqual(result['spending']['heldUsdMicro'], 80)
        self.assertEqual(result['settings']['replyTo'], 'jamesau0723@gmail.com')
        founder_policy.save_policy(app, self.principal, {'body': {'mode': 'live', 'revision': 2, 'changes': {'dailySpendMode': 'unlimited'}}})
        self.assertEqual(reserve('synthetic:unlimited'), 'reserved')

    def test_browser_and_phone_contacts_share_one_owner_slot_without_double_counting_phone_runs(self):
        import psycopg
        from concurrent.futures import ThreadPoolExecutor
        from postriff_phase2.phone.store import active_founder_contacts
        wid = founder_ops.create_ops(self.app(), self.principal, {'mode': 'live'})['workspaceId']
        def claim(key):
            with psycopg.connect(self.dsn) as db:
                with db.cursor() as cur:
                    cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('phone:' + self.user,))
                    if active_founder_contacts(cur, self.user, wid) >= 1:
                        return 'blocked'
                    cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Synthetic contact') RETURNING id", (wid, self.user))
                    conversation = cur.fetchone()[0]
                    cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                                "VALUES(%s,%s,%s,'running','synthetic','quick',repeat('a',64),repeat('b',64),%s,'{\"voice\":{\"capSeconds\":600}}') RETURNING id",
                                (conversation, wid, self.user, key))
                    run = cur.fetchone()[0]
                    if key.startswith('voice:phone:'):
                        cur.execute("INSERT INTO public.pr_phone_calls(user_id,workspace_id,conversation_id,voice_run_id,kind,reason_key,provider,state,idempotency_key,number_hash,max_seconds,reserved_usd_micro) "
                                    "VALUES(%s,%s,%s,%s,'explicit','synthetic','fake','requested',%s,'synthetic',600,0)", (self.user, wid, conversation, run, key))
            return 'admitted'
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(claim, ['voice:founder:synthetic', 'voice:phone:synthetic'])), ['admitted', 'blocked'])
        with psycopg.connect(self.dsn) as db, db.cursor() as cur:
            self.assertEqual(active_founder_contacts(cur, self.user, wid), 1)
            cur.execute('DELETE FROM public.pr_phone_calls WHERE workspace_id=%s', (wid,))
            cur.execute('DELETE FROM public.pr_agent_runs WHERE workspace_id=%s', (wid,))
        self.assertEqual(claim('voice:phone:synthetic'), 'admitted')
        self.assertEqual(claim('voice:founder:synthetic'), 'blocked')
        with psycopg.connect(self.dsn) as db, db.cursor() as cur:
            self.assertEqual(active_founder_contacts(cur, self.user, wid), 1)
            cur.execute('SELECT id::text FROM public.pr_phone_calls WHERE workspace_id=%s', (wid,))
            call_id = cur.fetchone()[0]
            self.assertEqual(active_founder_contacts(cur, self.user, wid, exclude_call_id=call_id), 0)

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
            self.assertEqual(tuple(member), ('owner', 'active', True))
            # The second membership never becomes the default: bootstrap answers the trial workspace every time.
            for _ in range(3):
                self.assertEqual(str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0]), self.primary)
        self.assertFalse(founder_ops.create_ops(app, self.principal, {'mode': 'live', 'now': 0})['created'])


if __name__ == '__main__':
    unittest.main()
