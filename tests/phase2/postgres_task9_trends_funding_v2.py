"""Focused actual PostgreSQL funding regressions; all external I/O is synthetic.

No cluster startup or port probe. The parent supplies the disposable rls.sql
baseline. Only this class runs; the existing enrichment fixture supplies setup,
not its unrelated tests. Catalog identities come from committed migrations.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row, tuple_row

from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from postriff_phase2.growth.trends import contracts, credit_admission, enrichment
from postriff_phase2.growth.trends.jobs import TrendJobs
from postriff_phase2.growth.trends.policy import ProviderCapability, SourcePolicy
from postriff_phase2.growth.trends.providers import bluesky, runtime as provider_runtime
from postriff_phase2.growth.trends.providers.base import Batch
from postriff_phase2.growth.trends.providers.registry import ProviderRegistry
from postriff_phase2.growth.trends.store import TrendStore
from postriff_phase2.growth.trends.worker import TrendWorker
from test_trend_enrichment import EnrichmentPostgresTests

SCHEMA = (
    ('020_credit_quotes.sql', 'public.pr_credit_quotes'),
    ('021_credit_purchases.sql', 'public.pr_credit_packs'),
    ('022_credit_payment_lifecycle.sql', 'public.pr_credit_payment_inbox'),
    ('040_social_trend_intelligence.sql', 'public.pr_trend_jobs'),
    ('089_pricing_credit_catalog_v2.sql', None),
    ('090_free_lifecycle_bootstrap.sql', None),
)
SCENARIO_COUNT = 10
PG_ENV_OVERRIDES = (
    'PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR', 'PGOPTIONS', 'PGHOST', 'PGPORT',
    'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGPASSFILE', 'PGSSLMODE',
)


def selected_port(env=None):
    env = os.environ if env is None else env
    value = env.get('POSTRIFF_TEST_PG_PORT', '55438')
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError('POSTRIFF_TEST_PG_PORT must be an explicit decimal port')
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be between 1024 and 65535')
    return port


def validated_dsn(env=None):
    env = os.environ if env is None else env
    port = selected_port(env)
    dsn = env.get('POSTRIFF_TEST_DSN', f'host=127.0.0.1 port={port} dbname=postgres')
    params = conninfo_to_dict(dsn)
    if (set(params) - {'host', 'port', 'dbname', 'user'}
            or (params.get('host'), params.get('port'), params.get('dbname'))
            != ('127.0.0.1', str(port), 'postgres')
            or any(k in env for k in PG_ENV_OVERRIDES)):
        raise ValueError('exact loopback disposable DSN must match the selected port')
    return dsn


def connection(*, row_factory=tuple_row, service=False):
    db = psycopg.connect(validated_dsn(), client_encoding='utf8',
        row_factory=row_factory, connect_timeout=3, passfile='/dev/null',
        options='-c statement_timeout=10000 -c lock_timeout=750')
    if (db.info.host, db.info.port, db.info.dbname) != ('127.0.0.1', selected_port(), 'postgres'):
        db.close()
        raise ValueError('connected database differs from the selected disposable target')
    if service:
        db.execute('SET ROLE service_role')
    return db


def apply_schema():
    """Parent entry: existing baseline, then existing missing migrations in order."""
    with connection() as db:
        db.autocommit = True
        if (not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]
                or not db.execute("SELECT to_regclass('public.pr_entitlements')").fetchone()[0]):
            raise RuntimeError('parent disposable tests/phase2/rls.sql baseline required')
        if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:
            raise RuntimeError('003/pr_runtime dependency is forbidden')
        for name, marker in SCHEMA:
            if marker is None or not db.execute('SELECT to_regclass(%s)', (marker,)).fetchone()[0]:
                db.execute((ROOT / 'migrations' / 'postriff' / name).read_text())
            print(json.dumps({'schemaEntry': name, 'existingMarker': marker}), flush=True)


class TrendsFundingPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.psycopg = psycopg
        cls.dsn = validated_dsn()
        # Reuse the already-defined service_role; no new roles, RLS policies or
        # permission edits are needed for this funding fixture.
        cls.connect = staticmethod(lambda: connection(service=True))
        with connection() as db:
            for table in ('pr_trend_jobs', 'pr_trend_budget_reservations', 'pr_model_usage_events',
                          'pr_entitlements', 'pr_plan_terms', 'pr_trend_entitlements'):
                if not db.execute('SELECT to_regclass(%s)', ('public.' + table,)).fetchone()[0]:
                    raise RuntimeError('required existing schema missing: ' + table)

    def setUp(self):
        EnrichmentPostgresTests.setUp(self)
        # The real dispatch guard now derives lifecycle from trusted server
        # authority. Bind the synthetic legacy-control host explicitly; this
        # does not activate v2 or grant source/model/provider funding.
        from types import SimpleNamespace
        self.hosted.billing=SimpleNamespace(pricing_v2_enabled=False)
        self.hosted.clock=lambda:self.at.timestamp()
        self.store.hosted=self.hosted
        self.entitle('studio-v1')
        self.provider_calls = []

    def enqueue(self, key='run-1'):
        return EnrichmentPostgresTests.enqueue(self, key)

    def usage(self):
        return EnrichmentPostgresTests.usage(self)

    def entitle(self, terms, wid=None):
        """Set effective server records using existing terms, never a client plan."""
        with connection() as db:
            changed = db.execute("""INSERT INTO public.pr_entitlements
                (workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,
                 connected_accounts,members,storage_mb,source)
                SELECT %s,id,0,0,(entitlements->>'connectedAccounts')::int,
                    (entitlements->>'members')::int,(entitlements->>'storageMb')::int,'manual'
                FROM public.pr_plan_terms WHERE id=%s
                ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=excluded.plan_terms_id,
                    source='manual',version=pr_entitlements.version+1,updated_at=clock_timestamp()""",
                (wid or self.wid, terms))
            self.assertEqual(changed.rowcount, 1, 'existing catalog terms required')

    def hold(self, job_id):
        with connection() as db:
            return db.execute("""SELECT j.state,j.attempts,r.state,r.amount_micro_usd,
                r.actual_micro_usd,r.usage_event_id IS NOT NULL
                FROM public.pr_trend_jobs j LEFT JOIN public.pr_trend_budget_reservations r
                USING(scope_key,reservation_id) WHERE j.job_id=%s""", (job_id,)).fetchone()

    def budgets(self):
        keys = enrichment.reviewed_config({'manifest': self.policy}, 'workspace_fit', self.wid)['budget_keys']
        with connection() as db:
            rows = db.execute("""SELECT reserved_micro_usd,unknown_micro_usd,settled_micro_usd
                FROM public.pr_trend_budget_limits WHERE budget_key=ANY(%s) ORDER BY budget_key""",
                (keys,)).fetchall()
        self.assertEqual(len(rows), 3)
        return rows

    def refusal(self, call, error=AlphaError):
        with self.assertRaises(error) as caught:
            call()
        self.assertEqual((caught.exception.status, caught.exception.code),
                         (503, credit_admission.UNAVAILABLE))

    def unlocked(self, *, scope_key=None):
        # Independent actual connection: NOWAIT fails if a guard transaction
        # still owns entitlement, catalog, or shared-beneficiary row locks.
        with connection() as db:
            db.execute('SELECT workspace_id FROM public.pr_entitlements WHERE workspace_id=%s FOR UPDATE NOWAIT', (self.wid,)).fetchall()
            db.execute("""SELECT p.id FROM public.pr_plan_terms p JOIN public.pr_entitlements e
                ON e.plan_terms_id=p.id WHERE e.workspace_id=%s FOR UPDATE OF p NOWAIT""", (self.wid,)).fetchall()
            if scope_key:
                db.execute('SELECT workspace_id FROM public.pr_trend_entitlements WHERE scope_key=%s FOR UPDATE NOWAIT', (scope_key,)).fetchall()

    def assert_unbilled(self, queued):
        self.assertEqual(self.calls, [])
        self.assertEqual(self.usage(), [])
        self.assertEqual(self.hold(queued['job_id']), ('failed_terminal', 1, 'released', 1000, None, False))
        self.assertEqual(self.budgets(), [(0, 0, 0)] * 3)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_credit_quotes WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND meta ? 'credits'", (self.wid,)).fetchone()[0], 0)

    def second_workspace(self, terms):
        from postriff_phase2.auth import initial_phase2_state
        wid = str(uuid.uuid4())
        state = initial_phase2_state(wid, self.actor, 'Synthetic beneficiary', 'studio', self.at.timestamp())
        with connection() as db:
            db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (wid, json.dumps(state)))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')", (wid, self.actor))
        self.entitle(terms, wid)
        self.store.grant_entitlement(wid, self.scope, ['retrieve', 'derive_metrics', 'share_across_workspaces'], self.end)
        return wid

    def paid_capability(self):
        return ProviderCapability(self.provider, 'read', '1', ('raw_post',),
            'https://example.invalid/synthetic', 'synthetic', 'public', (),
            10, 4096, 3, 1, 'request', 'synthetic-delete')

    def provider_worker(self, cap, amount):
        version = 'task9-' + uuid.uuid4().hex
        manifest = {**self.policy, 'id': version, 'version': version,
            'provider_id': cap.provider_id, 'operation': cap.operation,
            'price_ref': 'synthetic-test-price', 'approved_attempt_cap_microusd': 1000}
        self.store.register_contract(cap.provider_id, cap.version, list(contracts.PERMISSIONS), self.start, self.end)
        self.store.register_policy(manifest, provider_contract_version=cap.version)
        policy = SourcePolicy(**{k: manifest[k] for k in SourcePolicy.__dataclass_fields__ if k in manifest})
        registry = ProviderRegistry()
        def transport(**kwargs):
            self.unlocked(scope_key=self.scope)
            self.provider_calls.append(kwargs)
            return Batch(observations=(), cursor={'synthetic': 1}, completeness='partial', bytes_received=2, cost_microusd=0)
        registry.register(cap, policy, transport)
        keys = enrichment.reviewed_config({'manifest': self.policy}, 'workspace_fit', self.wid)['budget_keys']
        job = TrendJobs(self.store).enqueue(self.scope, 'trend.ingest',
            {'operation': cap.operation, 'coverage_epoch': 'synthetic-task9', 'max_items': 2,
             'seconds': 1, 'reservation_microusd': amount, 'budget_keys': keys},
            idempotency_key=version, provider_id=cap.provider_id, source_policy_version=version,
            max_attempts=cap.max_attempts)
        values = {**self.values, 'RAFII_TREND_PROVIDER_OPERATIONS_ENABLED': '1',
                  'RAFII_TREND_ALLOWED_OPERATIONS': cap.provider_id + ':' + cap.operation}
        worker = TrendWorker(self.store, registry=registry, values=values, monotonic=lambda: 0)
        return worker, job

    def test_actual_join_tuple_and_dict_rows_follow_server_terms(self):
        # Existing studio-v1 and studio-v2 deliberately share plan='studio';
        # the persisted policy, not plan spelling or price, distinguishes them.
        for factory in (tuple_row, dict_row):
            for terms, expected in (('studio-v1', 'legacy'), ('trial-v1', 'legacy'),
                                    ('free-v1', 'free'), ('creator-v1', 'managed_credits'),
                                    ('studio-v2', 'managed_credits')):
                with self.subTest(cursor=factory.__name__, terms=terms):
                    self.entitle(terms)
                    with connection(row_factory=factory, service=True) as db:
                        self.assertEqual(credit_admission.funding_mode(db.cursor(), self.wid), expected)
                    store = TrendStore(lambda: connection(row_factory=factory, service=True), hosted=self.hosted)
                    if expected == 'legacy':
                        credit_admission.require_dispatch(store, self.wid)
                    else:
                        self.refusal(lambda: credit_admission.require_dispatch(store, self.wid))
                    self.unlocked()
                    # Reuse the same native cursor after lifecycle admission;
                    # the caller must retain its requested SQL row shape.
                    with store.transaction() as cur:
                        if expected == 'legacy':
                            credit_admission.require_qualified_entry(cur,self.wid,store=store)
                        else:
                            self.refusal(lambda:credit_admission.require_qualified_entry(cur,self.wid,store=store))
                        cur.execute('SELECT plan_terms_id FROM public.pr_entitlements WHERE workspace_id=%s',(self.wid,))
                        self.assertIsInstance(cur.fetchone(),dict if factory is dict_row else tuple)
                    self.unlocked()
        with connection() as db:
            policy = db.execute("SELECT entitlements->>'creditPolicy' FROM public.pr_plan_terms WHERE id='creator-v1'").fetchone()[0]
        self.assertEqual(policy, V2_POLICY_VERSION)
        self.assertEqual(self.calls, [])

    def test_actual_share_locks_exist_and_dispatch_boundary_releases_them(self):
        with self.store.transaction() as cur:
            self.assertEqual(credit_admission.funding_mode(cur, self.wid), 'legacy')
            for sql in (
                'SELECT workspace_id FROM public.pr_entitlements WHERE workspace_id=%s FOR UPDATE NOWAIT',
                "SELECT p.id FROM public.pr_plan_terms p JOIN public.pr_entitlements e ON e.plan_terms_id=p.id WHERE e.workspace_id=%s FOR UPDATE OF p NOWAIT",
            ):
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    with connection() as db:
                        db.execute(sql, (self.wid,))
        self.unlocked()
        credit_admission.require_dispatch(self.store, self.wid)
        self.unlocked()
        self.entitle('creator-v1')  # Actual update commits after the boundary.
        self.refusal(lambda: credit_admission.require_dispatch(self.store, self.wid))
        self.unlocked()

    def test_paid_shared_worker_checks_all_current_free_and_v2_beneficiaries(self):
        other = self.second_workspace('free-v1')
        worker, job = self.provider_worker(self.paid_capability(), 80)
        for terms in ('free-v1', 'creator-v1'):
            with self.subTest(beneficiary=terms):
                self.entitle(terms, other)
                result = worker.tick(max_jobs=1)
                self.assertEqual((result['status'], result.get('reason_code'), result['dispatched']),
                                 ('funding_unavailable', credit_admission.UNAVAILABLE, 0))
                self.assertEqual(self.hold(job['job_id']), ('queued', 0, None, None, None, False))
                self.assertEqual(self.provider_calls, [])
                # Exercise actual dict beneficiary rows as well as worker tuples.
                store = TrendStore(lambda: connection(row_factory=dict_row, service=True), hosted=self.hosted)
                self.refusal(lambda: credit_admission.require_provider_dispatch(store, self.scope, self.paid_capability(), 80))
                self.unlocked(scope_key=self.scope)
        with connection() as db:
            db.execute('UPDATE public.pr_trend_entitlements SET revoked_at=clock_timestamp() WHERE scope_key=%s AND workspace_id=%s', (self.scope, other))
        credit_admission.require_provider_dispatch(self.store, self.scope, self.paid_capability(), 80)
        worker.jobs.cancel(self.scope, job['job_id'])

    def test_only_exact_server_jetstream_zero_capability_dispatches_for_v2(self):
        self.entitle('free-v1')
        self.second_workspace('creator-v1')
        worker, job = self.provider_worker(bluesky.CAPABILITY, 0)
        result = worker.tick(max_jobs=1)
        self.assertEqual((result['dispatched'], result['completed']), (1, 1), result)
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(self.hold(job['job_id']), ('succeeded', 1, 'settled', 0, 0, True))
        self.assertEqual(self.budgets(), [(0, 0, 0)] * 3)
        self.refusal(lambda: credit_admission.require_provider_dispatch(
            self.store, self.scope, replace(bluesky.CAPABILITY, endpoint='wss://example.invalid/forged'), 0))
        self.refusal(lambda: credit_admission.require_provider_dispatch(self.store, self.scope, bluesky.CAPABILITY, 1))
        self.refusal(lambda: credit_admission.require_provider_dispatch(
            self.store, self.scope, replace(self.paid_capability(), billable_unit='unmetered_live_bytes_bounded'), 0))

    def test_queued_model_current_free_and_v2_terms_refuse_before_claim(self):
        for terms in ('free-v1', 'creator-v1'):
            with self.subTest(terms=terms):
                self.entitle('studio-v1')
                queued = self.enqueue(uuid.uuid4().hex)
                self.entitle(terms)
                result = self.worker.tick()
                self.assertEqual((result['status'], result.get('reason_code'), result['provider_attempts']),
                                 ('funding_unavailable', credit_admission.UNAVAILABLE, 0))
                self.assertEqual(self.hold(queued['job_id']), ('cancelled', 0, None, None, None, False))
                self.assertEqual(self.usage(), [])
                self.assertEqual(self.calls, [])
                self.assertEqual(self.budgets(), [(0, 0, 0)] * 3)

    def test_transition_after_real_claim_commit_releases_preio_hold(self):
        queued = self.enqueue()
        repository = self.hosted.repository
        original = repository.transaction
        changed = []
        @contextmanager
        def transaction(*args, **kwargs):
            with original(*args, **kwargs) as value:
                yield value
            if not changed:
                changed.append(True)
                self.assertEqual(self.hold(queued['job_id']), ('running', 1, 'dispatched', 1000, None, False))
                self.assertEqual(self.budgets(), [(1000, 0, 0)] * 3)
                self.unlocked()
                self.entitle('creator-v1')
        with patch.object(repository, 'transaction', transaction):
            result = self.worker.tick()
        self.assertEqual((result['status'], result['provider_attempts']), ('funding_unavailable', 0))
        self.assertEqual(changed, [True])
        self.assert_unbilled(queued)

    def test_transition_after_initial_model_guard_is_rechecked_at_transport(self):
        queued = self.enqueue()
        funded = self.worker._funded_model
        changed = []
        def after_initial_guard(*args, **kwargs):
            runtime = funded(*args, **kwargs)
            self.unlocked()
            self.entitle('free-v1')
            changed.append(True)
            return runtime
        with patch.object(self.worker, '_funded_model', after_initial_guard):
            result = self.worker.tick()
        self.assertEqual((result['status'], result.get('reason_code'), result['provider_attempts']),
                         ('funding_unavailable', credit_admission.UNAVAILABLE, 0))
        self.assertEqual(changed, [True])
        self.assert_unbilled(queued)

    def test_web_each_physical_post_uses_current_terms_and_releases_locks(self):
        backend = provider_runtime.BoundedExaSearch(
            provider_runtime.research.DEFAULT_EXA_URL,
            authorize=lambda: credit_admission.require_dispatch(self.store, self.wid))
        attempts = []
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.headers = {}
        response.read.return_value = b'{"synthetic":true}'
        def open_request(*args, **kwargs):
            self.unlocked()
            attempts.append(True)
            self.entitle('creator-v1')
            return response
        opener = Mock(open=Mock(side_effect=open_request))
        with patch.object(provider_runtime.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(backend._post({}, b'{"method":"initialize"}')[0], 200)
            self.refusal(lambda: backend._post({}, b'{"method":"tools/call"}'))
        self.assertEqual(attempts, [True])
        self.assertEqual(opener.open.call_count, 1)
        self.unlocked()

    def test_unknown_attempt_survives_transition_as_exposure_without_retry(self):
        queued = self.enqueue()
        self.cost = None
        def during_io():
            self.unlocked()
            self.entitle('creator-v1')
        self.side_effect = during_io
        result = self.worker.tick()
        self.assertEqual((result['provider_attempts'], result['discarded']), (1, 1))
        self.assertEqual(self.usage(), [('ok', None)])
        self.assertEqual(self.hold(queued['job_id']), ('outcome_unknown', 1, 'unknown', 1000, None, True))
        self.assertEqual(self.budgets(), [(0, 1000, 0)] * 3)
        self.assertIsNone(self.store.get_projection(self.wid, self.actor, 'model_judgment', queued['result_id']))
        self.assertEqual(self.worker.tick()['provider_attempts'], 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.usage(), [('ok', None)])
        self.assertEqual(self.budgets(), [(0, 1000, 0)] * 3)

    def test_stored_cached_and_local_pack_reads_survive_v2_without_paid_io(self):
        queued = self.enqueue()
        self.side_effect = self.unlocked
        self.assertEqual(self.worker.tick()['attached'], 1)
        self.assertEqual(self.usage(), [('ok', 100)])
        self.assertEqual(self.hold(queued['job_id']), ('succeeded', 1, 'settled', 1000, 100, True))
        self.assertEqual(self.budgets(), [(0, 0, 100)] * 3)
        for terms in ('free-v1', 'creator-v1'):
            with self.subTest(terms=terms):
                self.entitle(terms)
                self.assertEqual(self.enqueue(uuid.uuid4().hex)['status'], 'cached')
                self.assertEqual(self.store.get_receipt(self.wid, self.actor, self.rid)['verification_state'], 'verified')
                saved = self.store.get_projection(self.wid, self.actor, 'model_judgment', queued['result_id'])
                self.assertEqual(saved['validity'], 'valid')
                with self.store.transaction() as cur:
                    loaded = self.worker._load(cur, self.wid, self.actor, self.rid, 'workspace_fit', self.state)
                    self.assertEqual(loaded['receipt']['verification_state'], 'verified')
                    self.assertTrue(loaded['pack']['evidence'])
                    self.assertGreater(enrichment.estimate_tokens(loaded['pack']), 0)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.usage(), [('ok', 100)])
                self.assertEqual(self.budgets(), [(0, 0, 100)] * 3)


def main():
    validated_dsn()  # Refuse a foreign target before opening any connection.
    apply_schema()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TrendsFundingPG)
    if suite.countTestCases() != SCENARIO_COUNT:
        raise RuntimeError('focused scenario count changed')
    def forbidden(*args, **kwargs):
        raise AssertionError('real provider/Python socket I/O forbidden in this fixture')
    with ExitStack() as guards:
        for target in ('socket.create_connection', 'socket.socket.connect',
                       'urllib.request.urlopen', 'urllib.request.build_opener'):
            guards.enter_context(patch(target, side_effect=forbidden))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'execution': 'actual-disposable-pg; synthetic-external-only',
                      'port': selected_port(), 'scenarios': result.testsRun,
                      'skips': len(result.skipped), 'success': result.wasSuccessful()}), flush=True)
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    sys.exit(main())
