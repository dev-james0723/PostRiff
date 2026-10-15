"""Tiny inert P8 controls; no SQL, users, real provider calls or load cohort."""
import sys
import ast
import copy
import hashlib
import re
import threading
import time
from collections import Counter
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2.postgres_discord_capacity import (
    DSN, Incomplete, FixtureCancelled, FixtureLedger, HarnessInterrupted, Runtime, accounting, arrivals, budget_lower_bound,
    collect_fixture_cohort, connection_diagnostic_profile, configure_candidate_provider,
    diagnostic, diagnostic_phase, distribution, fingerprint, MockDiscord, TimedCursor,
    profile, rate_metadata, require_fixture, sql_metadata, validate_fence,
)


class CapacityControls(unittest.TestCase):
    def test_actual_learning_formula_preserves_quota_and_conservative_pending_debits(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'src/postriff_phase2/discord/rate_limits.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observation_remaining')
        scope={'RateCoordinatorUnavailable':Incomplete}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'actual-quota-learning','exec'),scope)
        calc=scope['observation_remaining']
        self.assertEqual(calc(0,249,first=True,pending=0),249)
        self.assertEqual(calc(0,249,first=True,pending=4),245)
        self.assertEqual(calc(200,249,first=False,pending=5,newly_mapped=2,current_unmapped=1),197)
        self.assertEqual(calc(200,249,first=False,pending=5,newly_mapped=0,current_unmapped=0),200)
        self.assertEqual(calc(0,249,first=False,pending=0),0)
        for change in ({'pending':True},{'newly_mapped':1},{'current_unmapped':2},{'first':1}):
            with self.assertRaises(Incomplete):calc(0,249,**({'first':True,'pending':0}|change))

    def test_new_denial_scope_metadata_is_allowlisted(self):
        for name in ('application','discovery','learned_route','unknown_route','embargo','permit','unknown'):
            result=rate_metadata(SimpleNamespace(rate_cause='rate_budget',rate_scope_kind=name,retry_after_seconds=.1))
            self.assertEqual(result['scope'],name)
        result=rate_metadata(SimpleNamespace(rate_cause='rate_budget',rate_scope_kind='private tenant/channel/token'))
        self.assertEqual(result,{'cause':'rate_budget','scope':'unknown'})

    def test_atomic_admission_statement_diagnostic_keeps_only_safe_category(self):
        observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private SQL/parameter values')
        raw=SimpleNamespace(execute=fail)
        metrics=SimpleNamespace(count=lambda *a:None,timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(raw,metrics)
        with self.assertRaises(RuntimeError):
            cursor.execute('WITH reservation_clock AS MATERIALIZED (SELECT clock_timestamp() AS at) '
                'INSERT INTO public.pr_discord_request_admissions SELECT private_parameter',('private-token',42.0))
        self.assertEqual(observed,[('admission_insert',42.0)])

    def test_pending_lock_statement_categories_never_emit_query_or_parameters(self):
        observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private admission/SQL/parameter')
        metrics=SimpleNamespace(count=lambda *a:None,timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        for name in ('locked_alias','locked_pending'):
            with self.assertRaises(RuntimeError):
                cursor.execute('WITH '+name+' AS MATERIALIZED (SELECT private_admission FOR UPDATE)',('private-token',))
        self.assertEqual(observed,[('alias_pending_lock',None),('pending_lock',None)])

    def test_successful_scope_batch_counts_are_allowlisted_without_values(self):
        counts=Counter()
        metrics=SimpleNamespace(count=lambda key:counts.update([key]),timing=lambda *a:None)
        cursor=TimedCursor(SimpleNamespace(execute=lambda *a,**kw:None),metrics)
        for name in ('seed','lock','store'):
            cursor.execute('WITH scope_'+name+' AS MATERIALIZED (SELECT private_value)',('private-token',))
        cursor.execute('WITH scope_customer_secret AS MATERIALIZED (SELECT private_value)',('private-token',))
        self.assertEqual(counts,Counter({'sqlStatements':4,'sqlOperation.scope_seed_batch':1,
            'sqlOperation.scope_lock_batch':1,'sqlOperation.scope_store_batch':1,'sqlOperation.other':1}))

    def test_failed_scope_batch_counts_keep_category_and_omit_sql_and_values(self):
        counts=Counter();observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private SQL/parameter')
        metrics=SimpleNamespace(count=lambda key:counts.update([key]),timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        for name in ('seed','lock','store'):
            with self.assertRaises(RuntimeError):
                cursor.execute('WITH scope_'+name+' AS MATERIALIZED (SELECT private_value)',('private-token',))
        self.assertEqual(observed,[(name,None) for name in ('scope_seed_batch','scope_lock_batch','scope_store_batch')])
        self.assertEqual(counts['sqlStatements'],3)
        self.assertEqual(sum(v for k,v in counts.items() if k.startswith('sqlOperation.')),3)
        self.assertNotIn('private',str(counts)+str(observed))

    def test_sql_metadata_is_catalog_symbols_only(self):
        error = RuntimeError('private credential and SQL must never appear')
        error.sqlstate = '23514'
        error.diag = SimpleNamespace(constraint_name='pr_discord_request_admissions_check',
            message_detail='private failing row', statement='private SQL')
        self.assertEqual(sql_metadata(error), {'sqlstate': '23514', 'constraint': 'pr_discord_request_admissions_check'})
        error.diag.constraint_name = 'customer_private_value'
        error.sqlstate = 'private'
        self.assertEqual(sql_metadata(error), {})
        error.diag.constraint_name = 'pr_discord_rate_state_window_seconds_check'
        self.assertEqual(sql_metadata(error), {'constraint': error.diag.constraint_name})

    def test_rate_metadata_rejects_untrusted_cause_and_invalid_wait(self):
        error = SimpleNamespace(rate_cause='permit_expired', retry_after_seconds=.05)
        self.assertEqual(rate_metadata(error), {'cause': 'permit_expired', 'waitSeconds': .05})
        for wait in (float('nan'), float('inf'), -1, True, 'private'):
            error.rate_cause, error.retry_after_seconds = 'private-secret', wait
            self.assertEqual(rate_metadata(error), {'cause': 'unknown'})

    def test_fixture_failure_and_cancellation_keep_every_planned_actor(self):
        ledger = FixtureLedger(4)
        ledger.begin(0); ledger.finish(0, 'completed')
        ledger.begin(1); ledger.finish(1, 'failed', Incomplete('private-text'))
        ledger.begin(2); ledger.finish(2, 'cancelled')
        ledger.cancel_queued()
        result = ledger.summary()
        self.assertEqual({k: result[k] for k in ('planned','attempted','completed','failed','cancelled')},
                         {'planned': 4, 'attempted': 3, 'completed': 1, 'failed': 1, 'cancelled': 2})
        self.assertEqual((result['cancelledBeforeStart'], result['cancelledAfterStart'], result['unaccounted']), (1,1,0))
        self.assertFalse(result['complete'])
        self.assertNotIn('private-text', str(result))
        with self.assertRaises(Incomplete): ledger.begin(3)
        with self.assertRaises(Incomplete): ledger.finish(0, 'completed')

    def test_fatal_fixture_stops_queued_and_active_control_actors(self):
        ledger, abort = FixtureLedger(8), threading.Event()
        def build(index):
            if index == 0: raise Incomplete('synthetic fatal control')
            if abort.wait(.2): raise FixtureCancelled('control stopped')
            raise Incomplete('cooperative stop did not arrive')
        runtime = SimpleNamespace(p={'producerConcurrency': 1}, fixture_ledger=ledger,
            fixture_abort=abort, build_fixture=build, fixtures=[])
        with self.assertRaises(Incomplete): collect_fixture_cohort(runtime, range(8))
        result = ledger.summary()
        self.assertTrue(abort.is_set())
        self.assertEqual((result['failed'], result['completed'], result['queued'], result['running']), (1,0,0,0))
        self.assertEqual(result['cancelled'], 7)
        self.assertFalse(result['complete'])

    def test_connection_diagnostic_preserves_full_profiles_and_blocks_publish(self):
        hashes = {'a': 'fe939c0d1a8b55b2f68ad48f25b7f9caad7e63259ca954d97f5fd9cafe513836',
                  'b': '1c76fcd6054dd4d5fb473bcd416c0bde8d6d65961556deb50a41c62d345f7e31'}
        p = connection_diagnostic_profile()
        self.assertEqual((p['users'], p['serialUsers'], p['parallelUsers'], p['producerConcurrency']), (32,16,16,16))
        self.assertEqual(p['totalHarnessDeadlineSeconds'], 480)
        self.assertFalse(p['publishingAllowed'])
        self.assertEqual(p['mock'], profile('a')['mock'])
        counted = []
        metrics = SimpleNamespace(count=lambda key: counted.append(key))
        runtime = SimpleNamespace(p=p, m=metrics, create_oracle=lambda *a: self.fail('Publish oracle entered'))
        wire = MockDiscord(runtime)
        with self.assertRaises(Incomplete):
            wire('POST', 'https://discord.com/api/v10/channels/123456789/messages', body={})
        self.assertEqual(counted, ['diagnosticPublishDenied'])
        self.assertFalse(wire.attempts or wire.creates)
        self.assertEqual({s: fingerprint(profile(s)) for s in ('a','b')}, hashes)

    def test_main_deadline_outside_future_cancels_before_waiting_for_shutdown(self):
        for stop_on_failure in (True, False):
            ledger, abort = FixtureLedger(4), threading.Event()
            def build(index):
                if abort.wait(.2): raise FixtureCancelled('control stopped')
                raise Incomplete('cooperative cancellation missing')
            runtime = SimpleNamespace(p={'producerConcurrency': 1}, fixture_ledger=ledger,
                fixture_abort=abort, build_fixture=build, fixtures=[])
            with patch('phase2.postgres_discord_capacity.as_completed', side_effect=Incomplete('control deadline')):
                with self.assertRaises(Incomplete):
                    collect_fixture_cohort(runtime, range(4), stop_on_failure=stop_on_failure)
            result = ledger.summary()
            self.assertTrue(abort.is_set())
            self.assertEqual((result['cancelled'], result['running'], result['queued']), (4,0,0))
            self.assertFalse(result['complete'])

    def test_runtime_guard_stops_before_new_io_after_fatal_fixture(self):
        runtime = Runtime.__new__(Runtime)
        runtime.fixture_abort = threading.Event()
        runtime.fixture_abort.set()
        with self.assertRaises(FixtureCancelled): runtime.guard()

    def test_serial_main_interrupt_is_not_swallowed_as_actor_failure(self):
        ledger = FixtureLedger(2)
        def build(index): raise HarnessInterrupted('control main deadline')
        metrics = SimpleNamespace(lock=threading.RLock(), counters=Counter(), timings={}, peak=Counter(),
                                  event=lambda *args, **kwargs: None)
        runtime = SimpleNamespace(p={'producerConcurrency': 1}, m=metrics, fixture_ledger=ledger,
            fixture_abort=threading.Event(), build_fixture=build, fixtures=[], setup_deadline=time.monotonic()+5)
        with self.assertRaises(HarnessInterrupted): diagnostic_phase(runtime, 'serial', range(2), parallel=False)
        result = ledger.summary()
        self.assertEqual((result['attempted'], result['failed'], result['cancelled'], result['queued']), (1,0,1,1))
        self.assertFalse(result['complete'])

    def test_mock_bucket_headers_pass_the_actual_coordinator_parser(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'src/postriff_phase2/discord/rate_limits.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SharedPostgresBudget')
        observe = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'observe')
        parse = next(n for n in observe.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'new_bucket' for t in n.targets))
        hold = next(n for n in ast.walk(observe) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == 'raw_bucket is not None and new_bucket is None')
        code = compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(parse), copy.deepcopy(hold)],
                           type_ignores=[])), 'actual-rate-bucket-parser', 'exec')
        def held(bucket):
            scope = {'raw_bucket': bucket, 'row': {'hold': False}, 're': re,
                     '_digest': lambda value: hashlib.sha256(value.encode()).hexdigest()}
            exec(code, scope)
            return scope['row']['hold']
        self.assertTrue(held('fixture-/oauth2/@me'))  # Original mock caused a durable hold.
        p = profile('a')
        p['mock'].update(latencyBaseSeconds=0, latencyJitterSeconds=0)
        metrics = SimpleNamespace(count=lambda *args: None, timing=lambda *args: None,
                                  running=lambda *args: nullcontext())
        wire = MockDiscord(SimpleNamespace(p=p, m=metrics))
        wire.route = lambda *args: {}  # Inert responses; no SQL, tokens or real transport.
        paths = ['/oauth2/@me', '/users/@me', '/oauth2/token', '/guilds/123456789/channels',
                 '/channels/123456789', '/channels/987654321']
        buckets = {path: wire('POST' if path == '/oauth2/token' else 'GET',
                              'https://discord.com/api/v10' + path)['headers']['X-RateLimit-Bucket']
                   for path in paths}
        for bucket in buckets.values():
            self.assertFalse(held(bucket))
        self.assertEqual(buckets['/channels/123456789'], buckets['/channels/987654321'])
        self.assertNotEqual(buckets['/oauth2/@me'], buckets['/users/@me'])
        again = wire('GET', 'https://discord.com/api/v10/oauth2/@me')['headers']['X-RateLimit-Bucket']
        self.assertEqual(buckets['/oauth2/@me'], again)

    def test_real_oauth_mount_keeps_the_policy_instead_of_an_inert_coordinator(self):
        # Execute the ACTUAL constructor's rate block with inert dependencies.
        # No application-module imports, SQL, provider calls or data cohorts.
        # This fails with the old helper, which supplied only rate_limiter.
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'src/postriff_phase2/oauth.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OAuthService')
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        rate = next(n for n in init.body if isinstance(n, ast.If) and 'rate_v1_enabled' in ast.unparse(n.test))
        rate = copy.deepcopy(rate)
        rate.body = [n for n in rate.body if not isinstance(n, ast.ImportFrom)]
        module = ast.fix_missing_locations(ast.Module(body=[rate], type_ignores=[]))
        class Budget:
            def __init__(self, factory, application, *, policy):
                self.policy = policy
        raw = {'version': 1, 'revision': 'synthetic-regression', 'app_capacity': 1000}
        adapter = SimpleNamespace(client_id='718000000000000001', rate_policy_raw=None, rate_limiter=object())
        adapter.rate_v1_enabled = True
        scope = {'discord': adapter, 'repository': SimpleNamespace(connection_factory=lambda: None),
                 'SharedPostgresBudget': Budget, 'RateCoordinatorUnavailable': Incomplete}
        exec(compile(module, 'actual-oauth-rate-mount', 'exec'), scope)
        self.assertIsNone(adapter.rate_limiter.policy)  # Reproduce the broken mounting contract.
        configure_candidate_provider(adapter, raw)
        exec(compile(module, 'actual-oauth-rate-mount', 'exec'), scope)
        self.assertEqual(adapter.rate_limiter.policy, raw)
        self.assertIsNotNone(adapter.rate_limiter.policy)
        self.assertFalse(adapter.rate_coordinator_degraded)
        raw['app_capacity'] = 1
        self.assertEqual(adapter.rate_limiter.policy['app_capacity'], 1000)

    def test_failure_diagnostics_never_emit_secret_message_or_sql(self):
        error = RuntimeError('fixture-secret must not appear')
        error.code = 'discord_rate_coordinator_unavailable'
        error.status = 503
        error.sqlstate = '42601'
        data = diagnostic(error)
        self.assertEqual(data['code'], error.code)
        self.assertEqual(data['status'], 503)
        self.assertEqual(data['sqlstate'], '42601')
        self.assertNotIn('fixture-secret', str(data))
        error.code = 'unsafe credential value /'
        self.assertNotIn('code', diagnostic(error))

    def test_missing_latencies_are_undefined_in_full_denominator(self):
        data = distribution([.1, None, .3], requested=5)
        self.assertEqual((data['requested'], data['observed'], data['undefined']), (5, 2, 3))
        self.assertEqual((data['p95'], data['p99']), (.3, .3))
        self.assertIsNone(distribution([None])['p95'])

    def test_tail_latency_and_invalid_numbers_cannot_be_hidden(self):
        self.assertEqual(distribution([0] * 98 + [2, 10])['p99'], 2)
        for data in ([-1], [True], [float('nan')], [float('inf')]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                distribution(data)
        with self.assertRaises(ValueError):
            distribution([1, 2], requested=1)

    def test_partial_or_nonterminal_work_is_not_complete(self):
        self.assertTrue(accounting(3, 3, ['verified', 'held', 'uncertain'])['complete'])
        for requested, admitted, states in ((3, 2, ['verified'] * 2), (3, 3, ['verified']),
                (1, 2, ['verified'] * 2), (1, 1, ['provider_accepted']), (1, 1, ['scheduled'])):
            with self.subTest(states=states):
                self.assertFalse(accounting(requested, admitted, states)['complete'])

    def test_distinct_user_and_destination_counts_required(self):
        p = profile('a')
        good = {'users': 1000, 'profiles': 1000, 'memberships': 1000, 'workspaces': 1000,
                'distinctPrincipals': 1000, 'identities': 1000, 'connections': 2000,
                'grants': 3000, 'destinations': 6000, 'distinctDestinationIds': 6000}
        self.assertEqual(require_fixture(p, good)['grants'], 3000)
        for key in good:
            with self.subTest(key=key), self.assertRaises(Incomplete):
                require_fixture(p, {**good, key: good[key] - 1})
        with self.assertRaises(Incomplete):
            require_fixture(p, {**good, 'distinctPrincipals': 1})

    def test_stage_profile_preserves_scale_seed_time_and_no_nonce_cache(self):
        for stage, users, steady in (('a', 1000, 900), ('b', 10000, 1800)):
            p = profile(stage)
            self.assertEqual(p['users'], users)
            self.assertEqual(p['guildsPerUser'] * p['destinationsPerGuild'], 6)
            self.assertEqual((p['rampSeconds'], p['steadySeconds']), (300, steady))
            self.assertEqual(p['comparisonReplicas'] + [p['referenceReplicas']], [1, 4, 8])
            self.assertEqual(p['mock']['nonceDedupWindowSeconds'], 0)
            self.assertEqual(len(fingerprint(p)), 64)
        with self.assertRaises(ValueError):
            profile('')
        self.assertNotEqual(fingerprint(profile('a')), fingerprint(profile('b')))

    def test_steady_arrivals_cover_whole_interval_not_shortened_sample(self):
        p = profile('a')
        values = arrivals(p)
        self.assertEqual(len(values), 2130)
        self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
        self.assertEqual(sum(v >= 300 for v in values), 1800)
        self.assertGreater(values[-1], 1199)
        self.assertEqual(len(arrivals(profile('b'))), 9825)

    def test_infeasible_profile_is_blocked_without_shortening_it(self):
        a, b = profile('a'), profile('b')
        self.assertEqual(budget_lower_bound(a)['status'], 'PASS')
        self.assertEqual(budget_lower_bound(b)['status'], 'BLOCKED')
        self.assertGreater(budget_lower_bound(b)['minimumSeconds'], b['totalHarnessDeadlineSeconds'])
        self.assertEqual(b['steadySeconds'], 1800)

    def test_mac_missing_ci_and_foreign_dsn_are_refused(self):
        env = {'CI': 'true', 'RAFII_DISCORD_SYNTHETIC_FENCE': '1', 'POSTRIFF_TEST_DSN': DSN}
        validate_fence('linux', env)
        for platform, changed in (('darwin', env), ('linux', {**env, 'CI': 'false'}),
                ('linux', {**env, 'RAFII_DISCORD_SYNTHETIC_FENCE': '0'}),
                ('linux', {**env, 'POSTRIFF_TEST_DSN': 'host=buoyhkbodnhzngaotoel.supabase.co'}),
                ('linux', {**env, 'POSTRIFF_TEST_DSN': 'host=staging.example'})):
            with self.subTest(platform=platform), self.assertRaises(Incomplete):
                validate_fence(platform, changed)

    def test_owned_cluster_schema_and_transport_proof_cannot_be_skipped(self):
        env = {'CI': 'true', 'RAFII_DISCORD_SYNTHETIC_FENCE': '1', 'POSTRIFF_TEST_DSN': DSN}
        database = {'host': '127.0.0.1', 'port': 55438, 'name': 'postgres', 'user': 'postriff_test',
                    'directory': '/tmp/postriff-cw-pg-synthetic/data', 'majorVersion': 17, 'authColumns': ['id']}
        validate_fence('linux', env, database)
        for key, value in (('host', 'remote.example'), ('port', 5432), ('user', 'postgres'),
                ('directory', '/tmp/foreign/data'), ('directory', 'postriff-cw-pg-synthetic/data'),
                ('majorVersion', 16), ('authColumns', ['id', 'email'])):
            with self.subTest(key=key), self.assertRaises(Incomplete):
                validate_fence('linux', env, {**database, key: value})
        class UnknownTransport:
            synthetic_only = True
        with self.assertRaises(Incomplete):
            validate_fence('linux', env, database, UnknownTransport())


class ReorderedHeaderHarnessControls(unittest.TestCase):
    def test_mapping_query_uses_durable_route_hash_after_real_response_reordering(self):
        from phase2.postgres_discord_capacity import Runtime
        from postriff_phase2.discord.rate_limits import route_identity
        r=Runtime.__new__(Runtime);entered=threading.Event();lock=threading.Lock();calls=[]
        path='/guilds/123456789012345678';route,major=route_identity('GET',path)
        expected_route=hashlib.sha256(route.encode()).hexdigest()
        expected_bucket=hashlib.sha256(('fixture-'+hashlib.sha256(path.encode()).hexdigest()).encode()).hexdigest()
        wire=SimpleNamespace(reordered_entered=entered,reordered_finishes=[],set_fault=lambda *args:None)
        def request(method,url):
            with lock:index=len(calls);calls.append(url)
            if index==0:entered.set();time.sleep(.02)
            wire.reordered_finishes.append({'path':url,'old':index==0})
            return {'status':200}
        def execute(query,params):
            self.assertEqual(params,('synthetic-auth-hash',expected_route,major))
            return SimpleNamespace(fetchone=lambda:(expected_bucket,2) if query.startswith('SELECT bucket_key') else (2,))
        r.wire=wire;r.connection=lambda:nullcontext(SimpleNamespace(execute=execute))
        provider=SimpleNamespace(_bot=request,_rate_identity=lambda kind:SimpleNamespace(auth_key='synthetic-auth-hash'))
        result=r.rate_reordering({'provider':provider,'guilds':['123456789012345678'],'destinations':[('connection','guild','channel')]})
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(len(calls),2)


class SqlAuthorizationProbeControls(unittest.TestCase):
    def test_expected_denial_is_thread_scoped_and_never_hides_other_errors(self):
        from phase2.postgres_discord_capacity import Telemetry
        counters=Counter();failures=[]
        metrics=SimpleNamespace(_expected_sql=threading.local(),count=lambda key:counters.update([key]),
            sql_failure=lambda *args:failures.append(type(args[0]).__name__),timing=lambda *args:None)
        class SqlFailure(Exception):pass
        def fail(*args):
            error=SqlFailure('synthetic');error.sqlstate=state[0];raise error
        state=['42501'];cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        with Telemetry.expected_sqlstate(metrics,'42501'):
            with self.assertRaises(SqlFailure):cursor.execute('SELECT synthetic')
            state[0]='23514'
            with self.assertRaises(SqlFailure):cursor.execute('SELECT synthetic')
        state[0]='42501'
        with self.assertRaises(SqlFailure):cursor.execute('SELECT synthetic')
        self.assertEqual(counters['expectedSqlAuthorizationDenials'],1)
        self.assertEqual(counters['sqlErrors.SqlFailure'],2)
        self.assertEqual(len(failures),2)


class ExtendedResourcePlanTests(unittest.TestCase):
    def test_original_profiles_and_all_workloads_targets_are_preserved(self):
        from phase2.postgres_discord_capacity import selected_profile
        a,b=profile('a'),profile('b')
        self.assertEqual(fingerprint(a),'fe939c0d1a8b55b2f68ad48f25b7f9caad7e63259ca954d97f5fd9cafe513836')
        self.assertEqual(fingerprint(b),'1c76fcd6054dd4d5fb473bcd416c0bde8d6d65961556deb50a41c62d345f7e31')
        extended=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-v2'})
        for key,value in b.items():
            if key not in ('version','setupDeadlineSeconds','totalHarnessDeadlineSeconds'):
                self.assertEqual(extended[key],value,key)
        self.assertEqual(arrivals(extended),arrivals(b))
        self.assertEqual(budget_lower_bound(b)['status'],'BLOCKED')
        self.assertEqual(budget_lower_bound(extended)['status'],'PASS')
    def test_extended_resources_are_explicit_bounded_and_reject_unknown_plans(self):
        from phase2.postgres_discord_capacity import selected_profile
        e=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-v2'})
        self.assertEqual((e['cpu'],e['memoryGiB'],e['jobTimeoutMinutes']),(32,128,225))
        self.assertLess(e['setupDeadlineSeconds']+e['rampSeconds']+e['steadySeconds'],e['totalHarnessDeadlineSeconds'])
        self.assertLess(e['totalHarnessDeadlineSeconds'],e['policyLifetimeSeconds'])
        self.assertLess(e['policyLifetimeSeconds'],31*86400)
        for stage,name in [('a','b-extended-v2'),('b','unknown')]:
            with self.assertRaises(Incomplete):selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':name})


if __name__ == '__main__':
    unittest.main()
