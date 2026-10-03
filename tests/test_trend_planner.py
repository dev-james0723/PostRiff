"""Offline frontier admission and optional isolated local PostgreSQL persistence."""
import copy
from contextlib import contextmanager
from dataclasses import asdict, replace
import os
from pathlib import Path
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from test_trend_contracts import OfflineTest, NOW, BEFORE, AFTER, WORKSPACE, SCOPE, policy, permissions
from postriff_phase2.growth.trends.contracts import ContractError
from postriff_phase2.growth.trends.policy import ProviderCapability
from postriff_phase2.growth.trends.planner import FrontierPlanner, schedule_controls
from postriff_phase2.growth.trends.providers.registry import ProviderRegistry
from postriff_phase2.growth.trends.jobs import TrendJobs, partition_key
from postriff_phase2.growth.trends.store import TrendStore
from postriff_phase2.growth.trends.contracts import digest

PERMISSIONS = permissions()
CAP = ProviderCapability('fixture', 'sample', 'fixture-v1', ('raw_post',),
    'https://fixture.invalid', 'synthetic', 'fixture', ('read',), 20, 4096, 10, 3,
    'synthetic_unit', 'fixture-delete')
FLAGS = {'RAFII_TREND_' + n + '_ENABLED': True for n in ('INTELLIGENCE', 'RADAR', 'PROVIDER_OPERATIONS')}
FLAGS.update(RAFII_TREND_WORKSPACE_ALLOWLIST=WORKSPACE, RAFII_TREND_ALLOWED_OPERATIONS='fixture:sample')


def schedule(**overrides):
    value = dict(enabled=True, start_at=NOW, interval_seconds=60, max_samples=2,
                 max_items=10, seconds=5, budget_keys=['sys', 'provider', 'workspace'], reservation_microusd=25)
    value.update(overrides)
    return value


class FakeCursor:
    description = []
    def __init__(self, store):
        self.store, self.result = store, []

    def execute(self, sql, args=None):
        if 'pg_advisory_xact_lock' in sql:
            self.result = []
        elif 'pr_trend_source_health' in sql:
            self.result = [self.store.health] if self.store.health else []
        elif 'pr_trend_budget_limits' in sql:
            self.result = copy.deepcopy(self.store.budgets)
        elif 'pr_trend_entitlements' in sql:
            self.result = copy.deepcopy(self.store.entitlements)
        elif 'FROM public.pr_trend_source_policies' in sql:
            self.result = [{'scope_key': self.store.p.scope_key, 'provider_id': 'fixture', 'version': 'fixture-v1'}]
        else:
            raise AssertionError('Unexpected fixture SQL: ' + sql)

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        value, self.result = self.result, []
        return value


class FakeStore:
    def __init__(self, p=None):
        self.p = p or policy(rights=copy.deepcopy(PERMISSIONS))
        self.manifest = {**asdict(self.p), 'schedule': schedule()}
        self.contract_version = CAP.version
        self.health = None
        self.entitlements = [{'workspace_id': WORKSPACE}]
        self.budgets = [dict(budget_key=k, dimension=d, cap_micro_usd=100,
            reserved_micro_usd=0, settled_micro_usd=0, unknown_micro_usd=0,
            period_start=BEFORE, period_end=AFTER) for k, d in
            [('sys', 'system'), ('provider', 'provider'), ('workspace', 'workspace')]]
        self.transactions = 0
        self.denied = False

    @contextmanager
    def transaction(self, cursor=None):
        self.transactions += 1
        yield cursor or FakeCursor(self)

    def _policy(self, cur, scope, provider, version, at):
        if self.denied:
            raise ContractError('source_policy_denied')
        return {'manifest': copy.deepcopy(self.manifest), 'provider_contract_version': self.contract_version}


class FrontierTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.store = FakeStore()
        self.registry = ProviderRegistry()
        self.adapter = Mock(side_effect=AssertionError('No dispatch from planner'))
        self.registry.register(CAP, self.store.p, self.adapter)
        self.values = dict(FLAGS)
        self.planner = FrontierPlanner(self.store, self.registry, values=self.values, clock=lambda: NOW)
        self.saved = {}
        def enqueue(scope, kind, payload, **kwargs):
            self.assertIsInstance(kwargs['cursor'], FakeCursor)
            key = kwargs['idempotency_key']
            result = dict(job_id=str(len(self.saved)), scope_key=scope, kind=kind, payload=payload, **kwargs)
            return self.saved.setdefault(key, result)
        self.planner.jobs.enqueue = Mock(side_effect=enqueue)

    def tearDown(self):
        self.adapter.assert_not_called()
        super().tearDown()

    def plan(self):
        return self.planner.plan_one(self.store.p.scope_key, 'fixture', 'fixture-v1')

    def test_real_job_controls_are_deterministic_and_budgets_are_referenced(self):
        first = self.plan(); second = self.plan()
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(first['kind'], 'trend.ingest')
        self.assertEqual(first['payload']['reservation_microusd'], 25)
        self.assertEqual(first['payload']['budget_keys'], ['provider', 'sys', 'workspace'])
        self.assertEqual(first['max_attempts'], 3)
        self.assertEqual(first['source_policy_version'], 'fixture-v1')

    def test_next_slot_new_key_and_total_schedule_stops(self):
        first = self.plan()
        self.planner.clock = lambda: '2026-09-27T12:01:00Z'
        self.assertNotEqual(self.plan()['job_id'], first['job_id'])
        self.planner.clock = lambda: '2026-09-27T12:02:00Z'
        self.assertIsNone(self.plan())
        self.assertEqual(len(self.saved), 2)

    def test_missed_slots_are_not_backfilled(self):
        self.planner.clock = lambda: '2026-09-27T12:01:59Z'
        self.assertEqual(len(self.planner.tick()['jobs']), 1)
        self.assertEqual(len(self.saved), 1)

    def test_future_schedule_does_not_enqueue(self):
        self.store.manifest['schedule']['start_at'] = AFTER
        self.assertIsNone(self.plan())

    def test_flags_off_does_not_even_open_database(self):
        for flag in ('INTELLIGENCE', 'RADAR', 'PROVIDER_OPERATIONS'):
            with self.subTest(flag=flag):
                self.values['RAFII_TREND_' + flag + '_ENABLED'] = False
                before = self.store.transactions
                self.assertEqual(self.planner.tick()['status'], 'disabled')
                self.assertEqual(self.store.transactions, before)
                self.values.update(FLAGS)

    def test_preview_ignores_production_flags(self):
        with patch.dict(os.environ, {**{k: str(v).lower() for k, v in FLAGS.items()}, 'VERCEL_ENV': 'preview'}, clear=True):
            planner = FrontierPlanner(self.store, self.registry, clock=lambda: NOW)
            self.assertEqual(planner.tick()['status'], 'disabled')
            self.assertEqual(self.store.transactions, 0)

    def test_empty_allowlist_wildcard_or_operation_mismatch_denied(self):
        for key, value in [('RAFII_TREND_WORKSPACE_ALLOWLIST', ''),
                           ('RAFII_TREND_WORKSPACE_ALLOWLIST', '*'),
                           ('RAFII_TREND_ALLOWED_OPERATIONS', 'fixture:other')]:
            with self.subTest(key=key, value=value):
                self.values.update(FLAGS); self.values[key] = value
                self.reject(self.plan)
        self.assertFalse(self.saved)

    def test_missing_or_nonliteral_optin_denied(self):
        for value in (None, {}, {'enabled': 'true'}, schedule(enabled=False), schedule(enabled=1)):
            self.store.manifest['schedule'] = value
            self.reject(self.plan)

    def test_strict_schedule_bounds_and_no_arbitrary_query_payload(self):
        for key, value in [('interval_seconds', 0), ('max_samples', True), ('max_items', float('nan')),
                           ('seconds', 0), ('reservation_microusd', True), ('query', 'private source body')]:
            with self.subTest(key=key):
                self.reject(schedule_controls, {'schedule': schedule(**{key: value})})

    def test_capability_item_time_and_contract_boundaries(self):
        for change in ({'max_items': 21}, {'seconds': 11}):
            self.store.manifest['schedule'] = schedule(**change)
            self.reject(self.plan)
        self.store.manifest['schedule'] = schedule()
        self.store.contract_version = 'other-v2'
        self.reject(self.plan)

    def test_persisted_rights_changes_cannot_use_stale_registry(self):
        self.store.manifest['rights']['retrieve']['state'] = 'unknown'
        self.reject(self.plan)
        self.assertFalse(self.saved)

    def test_policy_revocation_is_rechecked(self):
        self.store.denied = True
        self.reject(self.plan)

    def test_unknown_paid_exposure_counts_against_budget(self):
        self.store.budgets[0]['unknown_micro_usd'] = 80
        self.reject(self.plan)

    def test_expired_and_missing_budget_dimensions_denied(self):
        self.store.budgets[0]['period_end'] = NOW
        self.reject(self.plan)
        self.store.budgets[0]['period_end'] = AFTER
        self.store.budgets[2]['dimension'] = 'run'
        self.reject(self.plan)
        self.store.budgets.pop()
        self.reject(self.plan)

    def test_budget_must_be_explicit_unique_and_within_reviewed_price_cap(self):
        for value in ([], ['x', 'x'], ['system', 'provider', 'workspace', 'run', 'extra']):
            self.store.manifest['schedule'] = schedule(budget_keys=value)
            self.reject(self.plan)
        self.store.manifest['schedule'] = schedule(reservation_microusd=101)
        self.reject(self.plan)

    def test_health_pause_and_future_backoff_stop_scheduling(self):
        for health in ({'status': 'revoked'}, {'status': 'unavailable', 'next_allowed_at': AFTER}):
            self.store.health = health
            self.reject(self.plan)

    def test_shared_scope_requires_current_allowlisted_entitlement(self):
        shared = policy(scope_key='shared:synthetic')
        self.store = FakeStore(shared)
        registry = ProviderRegistry(); registry.register(CAP, shared, self.adapter)
        self.planner = FrontierPlanner(self.store, registry, values=self.values, clock=lambda: NOW)
        self.planner.jobs.enqueue = Mock(return_value={'job_id': 'shared-job'})
        self.assertEqual(self.plan()['job_id'], 'shared-job')
        self.store.entitlements = []
        self.reject(self.plan)

    def test_invalid_candidate_does_not_abort_other_planner_work(self):
        self.store.manifest['schedule'] = schedule(max_items=100)
        self.assertEqual(self.planner.tick(), {'status': 'ok', 'jobs': [], 'blocked': 1})


PG_DSN = os.environ.get('TREND_PLANNER_TEST_DSN') or os.environ.get('POSTRIFF_TEST_DSN', '')


def dedicated_test_dsn(environ=None):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from local_pg_target import selected_target
    env = os.environ if environ is None else environ
    target = selected_target(env, validate_fixture_dsns=False)
    if any(env.get(k) for k in ('PGSERVICE', 'PGHOSTADDR')):
        raise ValueError('libpq service/address overrides are forbidden')
    dedicated = env.get('TREND_PLANNER_TEST_DSN')
    raw = dedicated or env.get('POSTRIFF_TEST_DSN')
    if not raw:
        raise ValueError('Explicit disposable planner test DSN required')
    params = conninfo_to_dict(raw)
    if set(params) - {'host', 'port', 'dbname', 'user'}:
        raise ValueError('Only explicit host/port/dbname/user test DSN fields permitted')
    valid = (params.get('host') == '127.0.0.1' and
        ((params.get('port') == '56447' and params.get('dbname', '').startswith('trend_planner_retry_'))
         if dedicated else (params.get('port') == str(target.port) and params.get('dbname') == 'postgres')))
    if not valid:
        raise ValueError('Assigned planner database or exact disposable runner required')
    return make_conninfo(**params, connect_timeout='5')


class PlannerDsnGuards(OfflineTest):
    def test_only_explicit_disposable_targets_no_application_or_address_overrides(self):
        dedicated = 'host=127.0.0.1 port=56447 dbname=trend_planner_retry_test'
        runner = 'host=127.0.0.1 port=55438 dbname=postgres'
        self.assertIn('56447', dedicated_test_dsn({'TREND_PLANNER_TEST_DSN': dedicated}))
        self.assertIn('55438', dedicated_test_dsn({'POSTRIFF_TEST_DSN': runner}))
        for env in ({}, {'POSTRIFF_DATABASE_URL': runner}, {'POSTRIFF_TEST_DSN': dedicated},
                    {'TREND_PLANNER_TEST_DSN': runner}, {'TREND_PLANNER_TEST_DSN': dedicated + ' hostaddr=198.51.100.1'},
                    {'POSTRIFF_TEST_DSN': runner, 'PGSERVICE': 'app'},
                    {'POSTRIFF_TEST_DSN': runner, 'PGHOSTADDR': '198.51.100.1'},
                    {'POSTRIFF_TEST_DSN': runner.replace('127.0.0.1', 'db.example.com')},
                    {'POSTRIFF_TEST_DSN': runner.replace('55438', '5432')}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                dedicated_test_dsn(env)


class PostgresFixture(OfflineTest):
    """Only the explicitly allocated disposable database; never app/prod DSNs."""
    @classmethod
    def setUpClass(cls):
        import psycopg
        dsn = dedicated_test_dsn()
        cls.connect = staticmethod(lambda: psycopg.connect(dsn))
        with cls.connect() as db:
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((Path(__file__).resolve().parents[1] / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())

    def setUp(self):
        super().setUp()
        for target in ('postriff_phase2.growth.trends.store.utcnow', 'postriff_phase2.growth.trends.jobs.utcnow'):
            clock_patch = patch(target, return_value=NOW)
            clock_patch.start(); self.addCleanup(clock_patch.stop)
        self.workspace = str(uuid.uuid4())
        self.scope = 'workspace:' + self.workspace
        self.keys = [self.workspace + ':' + d for d in ('system', 'provider', 'workspace')]
        with self.connect() as db:
            db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (self.workspace,))
        self.store = TrendStore(self.connect, offline_replay=True)
        self.jobs = TrendJobs(self.store)
        self.p = policy(scope_key=self.scope)
        self.controls = schedule(budget_keys=self.keys)
        self.store.register_contract('fixture', CAP.version, list(PERMISSIONS), BEFORE, AFTER)
        self.store.register_policy({**asdict(self.p), 'schedule': self.controls,
            'quarantine_recovery': {'enabled': True, 'max_replays': 1}}, provider_contract_version=CAP.version)
        for key, dimension in zip(self.keys, ('system', 'provider', 'workspace')):
            self.jobs.configure_budget(key, dimension, 100, BEFORE, AFTER)
        self.adapter = Mock(side_effect=AssertionError('Unexpected live provider'))
        self.registry = ProviderRegistry(); self.registry.register(CAP, self.p, self.adapter)
        self.flags = {**FLAGS, 'RAFII_TREND_WORKSPACE_ALLOWLIST': self.workspace}
        self.planner = FrontierPlanner(self.store, self.registry, values=self.flags, clock=lambda: NOW)
        self.partition = partition_key(instance_id=CAP.endpoint, protocol_version=CAP.version,
            filter_digest=digest({'operation': self.p.operation, 'scope': self.scope, 'filter': {}}))

    def tearDown(self):
        self.adapter.assert_not_called()
        super().tearDown()

    def plan(self):
        return self.planner.plan_one(self.scope, 'fixture', CAP.version)

    def start(self, job=None):
        job = job or self.plan()
        claim = self.jobs.claim('synthetic-worker', job_id=job['job_id'], scope_key=self.scope,
            budget_keys=self.keys, amount_micro_usd=25)
        self.assertIsNotNone(claim)
        return self.jobs.start(claim)

    def fetch(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).fetchone()


@unittest.skipUnless(PG_DSN, 'Explicit isolated local PostgreSQL DSN not configured')
class PlannerPostgresTests(PostgresFixture):
    def test_concurrent_ticks_persist_exactly_one_slot_then_one_next_slot(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.plan()['job_id'], range(8)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.fetch('SELECT count(*) FROM public.pr_trend_jobs WHERE scope_key=%s', (self.scope,))[0], 1)
        self.planner.clock = lambda: '2026-09-27T12:01:00Z'
        self.assertNotEqual(self.plan()['job_id'], ids[0])
        self.planner.clock = lambda: '2026-09-27T12:02:00Z'
        self.assertIsNone(self.plan())

    def test_current_revocation_blocks_stale_registry_and_preserves_existing_job(self):
        job = self.plan()
        with self.connect() as db:
            db.execute('UPDATE public.pr_trend_source_policies SET revoked_at=clock_timestamp() WHERE scope_key=%s', (self.scope,))
        self.reject(self.plan)
        self.assertEqual(self.fetch('SELECT state FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s',
                                   (self.scope, job['job_id']))[0], 'queued')

    def test_unknown_exposure_counts_against_actual_multi_dimension_budget(self):
        reserved = self.jobs.reserve(self.scope, 'synthetic-unknown', str(uuid.uuid4()), 80, self.keys)
        self.jobs.settle(self.scope, reserved['reservation_id'])
        self.reject(self.plan)
        self.assertEqual(self.fetch('SELECT count(*) FROM public.pr_trend_jobs WHERE scope_key=%s', (self.scope,))[0], 0)


if __name__ == '__main__':
    unittest.main()
