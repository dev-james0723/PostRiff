"""Synthetic dispatch probes; no PostgreSQL, credentials or external I/O.

The old worker's adversarial cases are inherited with one explicit new server
entitlement query fixture. They still execute the real worker and retry path.
"""
import copy
import io
import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from postriff_phase2.growth.jev import JevService, DEFAULT_MODEL, EVALUATE_ENDPOINT
from postriff_phase2.growth.usage import MemoryUsageSink
from postriff_phase2.model_runtime import ServerModelRuntime
from postriff_phase2.growth.trends import contracts, enrichment, generation, lab_enrichment, media_jobs
from postriff_phase2.growth.trends.providers import runtime as provider_runtime, bluesky, web
import test_trend_contracts as F
import test_trend_worker as original_worker
import test_trend_generation as original_generation

CODE = 'growth_credit_bridge_unavailable'
LEGACY = {'plan': 'studio', 'credit_policy': 'credits-candidate-2026-09-23-v1'}
MANAGED = {'plan': 'creator', 'credit_policy': V2_POLICY_VERSION}
FREE = {'plan': 'free', 'credit_policy': None}


class FundingCursor:
    description = [SimpleNamespace(name='plan'), SimpleNamespace(name='credit_policy')]

    def __init__(self, store):
        self.store = store
        self.result = []

    def execute(self, sql, params=None):
        self.store.queries.append((sql, params))
        if '/* trends:funding */' in sql:
            self.result = [copy.deepcopy(self.store.terms)] if self.store.terms else []
        elif '/* trends:beneficiaries */' in sql:
            self.description = [SimpleNamespace(name='workspace_id')]
            self.result = [{'workspace_id': w} for w in self.store.beneficiaries]
        else:
            raise AssertionError('Unexpected funding SQL: ' + sql)
        if self.store.on_query:
            self.store.on_query(sql)

    def fetchone(self):
        value = self.result[0] if self.result else None
        if value is not None and self.store.tuple_rows:
            return tuple(value[c.name] for c in self.description)
        return value

    def fetchall(self):
        return self.result


class FundingStore:
    def __init__(self, terms=LEGACY, *, tuple_rows=False):
        self.terms = copy.deepcopy(terms)
        self.depth = 0
        self.queries = []
        self.beneficiaries = [F.WORKSPACE]
        self.on_query = None
        self.tuple_rows = tuple_rows

    @contextmanager
    def transaction(self, cursor=None):
        self.depth += 1
        try:
            yield cursor or FundingCursor(self)
        finally:
            self.depth -= 1


def install_worker_funding_probe(test):
    test.store.terms = copy.deepcopy(LEGACY)
    original = original_worker.ProbeCursor.execute

    def execute(cur, sql, params=None):
        if '/* trends:funding */' in sql:
            cur.store.queries.append((sql, params))
            cur.result = [copy.deepcopy(cur.store.terms)] if cur.store.terms else []
        elif '/* trends:beneficiaries */' in sql:
            cur.result = [{'workspace_id': w} for w in cur.store.entitled_workspaces]
        else:
            original(cur, sql, params)
    # A function (rather than a mock descriptor) preserves the actual cursor.
    p = patch.object(original_worker.ProbeCursor, 'execute', execute)
    p.start(); test.addCleanup(p.stop)


class WorkerFunding(original_worker.WorkerHarness):
    def setUp(self):
        super().setUp()
        install_worker_funding_probe(self)

    def test_v2_and_free_paid_worker_never_claim_or_dispatch(self):
        for terms in (MANAGED, FREE):
            with self.subTest(terms=terms):
                self.store.terms = copy.deepcopy(terms)
                result = self.worker.tick()
                self.assertEqual(result['dispatched'], 0)
                self.assertEqual(result.get('reason_code'), CODE)
                self.jobs.claim.assert_not_called()
                self.adapter.assert_not_called()

    def test_current_plan_change_after_start_blocks_physical_dispatch(self):
        start = self.start
        def changed(claim):
            value = start(claim)
            self.store.terms = copy.deepcopy(MANAGED)
            return value
        self.jobs.start.side_effect = changed
        result = self.worker.tick()
        self.assertEqual(result['dispatched'], 0)
        self.adapter.assert_not_called()
        self.jobs.fail.assert_called_once()
        self.assertTrue(self.jobs.fail.call_args.kwargs['proven_unbilled'])

    def test_retry_wait_uses_current_plan_not_original_operator_budget(self):
        self.store.candidates[0].update(state='retry_wait', attempts=1)
        self.store.terms = copy.deepcopy(FREE)
        self.assertEqual(self.worker.tick()['dispatched'], 0)
        self.jobs.claim.assert_not_called()

    def test_zero_amount_or_unmetered_label_does_not_qualify_unknown_route(self):
        self.store.terms = copy.deepcopy(MANAGED)
        self.store.candidates[0]['payload']['reservation_microusd'] = 0
        self.cap = replace(self.cap, billable_unit='unmetered_live_bytes_bounded')
        self.reset_registry()
        self.assertEqual(self.worker.tick()['dispatched'], 0)
        self.adapter.assert_not_called()

    def test_shared_paid_scan_cannot_subsidize_v2_beneficiary(self):
        shared = 'shared:funding-probe'
        self.store.candidates = [original_worker.job(scope_key=shared)]
        self.source_policy = F.policy(scope_key=shared)
        self.store.entitled_workspaces = [F.WORKSPACE]
        self.store.terms = copy.deepcopy(MANAGED)
        self.reset_registry()
        self.assertEqual(self.worker.tick()['dispatched'], 0)
        self.adapter.assert_not_called()


def evaluator_pack():
    pack = {'scope_key': F.SCOPE, 'evidence_is_untrusted_data': True,
            'evidence': [{'observation_id': F.WORKSPACE, 'text': 'Synthetic native text.'}]}
    pack['input_digest'] = contracts.digest(pack)
    return pack


class ModelFunding(F.OfflineTest):
    def setUp(self):
        super().setUp()
        self.store = FundingStore()
        self.hosted = SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda: None))
        self.calls = []

    def transport(self, method, url, *, headers, body, timeout):
        self.assertEqual(self.store.depth, 0)
        self.calls.append(copy.deepcopy(body))
        answers = {}
        for k, q in body.get('questions', {}).items():
            choice = next(iter(q['criteria']))
            answers[k] = {'type':'choice', 'choice':choice,
                          'probabilities':{c:float(c == choice) for c in q['criteria']}}
        return {'status':200, 'body':{'model':body['model'], 'answers':answers,
                'usage':{'inputTokens':10, 'outputTokens':2},
                'providerMetadata':{'gateway':{'cost':'0.0001', 'routing':{'finalProvider':'synthetic'}}}}}

    def execute_evaluator(self, worker_type=enrichment.TrendEnrichment):
        worker = worker_type(self.hosted, store=self.store)
        model = JevService('synthetic', endpoint=EVALUATE_ENDPOINT, model=DEFAULT_MODEL, transport=self.transport)
        pack = evaluator_pack()
        loaded = {'pack':pack, 'config':{'model':DEFAULT_MODEL, 'approved_attempt_cap_microusd':1000}}
        if worker_type is lab_enrichment.TrendLabEnrichment:
            pack.update(draft={'id':F.WORKSPACE, 'revision':1, 'text':'Synthetic draft.'},
                        draft_spans=lab_enrichment.spans('Synthetic draft.'),
                        own_history={'comparable':False, 'reason':'synthetic'},
                        workspace_context={'approved_facts':[]})
            loaded.update(lab={'object_id':F.WORKSPACE, 'payload':{'frozen_run':{}}}, receipt={'object_id':F.WORKSPACE})
        return worker.execute(model, loaded, 'workspace_fit', F.WORKSPACE, MemoryUsageSink())

    def test_semantic_model_and_lab_reject_v2_before_transport(self):
        for terms in (MANAGED, FREE):
            for worker_type in (enrichment.TrendEnrichment, lab_enrichment.TrendLabEnrichment):
                self.store.terms = copy.deepcopy(terms)
                self.calls.clear()
                with self.subTest(terms=terms, worker=worker_type.__name__):
                    with self.assertRaises(AlphaError) as caught:
                        self.execute_evaluator(worker_type)
                    self.assertEqual(caught.exception.status, 503)
                    self.assertEqual(caught.exception.code, CODE)
                    self.assertEqual(self.calls, [])

    def test_generation_rejects_v2_before_writer_transport_and_usage(self):
        for terms in (MANAGED, FREE):
            self.store.terms = copy.deepcopy(terms)
            worker = generation.TrendGeneration(self.hosted, store=self.store)
            sink = MemoryUsageSink()
            loaded = {'config':original_generation.review(), 'pack':original_generation.pack(),
                      'task':'culture_explain', 'context_revision':'context'}
            def transport(*args, **kwargs):
                self.assertEqual(self.store.depth, 0)
                self.calls.append(kwargs['body'])
                return {'status':200, 'body':{'model':original_generation.MODEL,
                        'usage':{'cost':.001}, 'choices':[{'message':{'content':json.dumps(
                        original_generation.output('culture_explain', loaded['pack']))}}]}}
            runtime = ServerModelRuntime('synthetic', model=original_generation.MODEL, transport=transport)
            self.calls.clear()
            with self.subTest(terms=terms):
                with self.assertRaises(AlphaError) as caught:
                    worker.execute(runtime, loaded, 'culture_explain', F.WORKSPACE, sink)
                self.assertEqual(caught.exception.code, CODE)
                self.assertEqual(self.calls, [])
                self.assertEqual(sink.events, [])

    def test_legacy_semantic_and_lab_keep_existing_one_attempt(self):
        for worker_type in (enrichment.TrendEnrichment, lab_enrichment.TrendLabEnrichment):
            with self.subTest(worker=worker_type.__name__):
                result = self.execute_evaluator(worker_type)
                self.assertEqual(result['executed_model'], DEFAULT_MODEL)
        self.assertEqual(len(self.calls), 2)

    def test_plan_change_at_model_transport_does_not_dispatch_or_book_fake_usage(self):
        from postriff_phase2.growth.trends import credit_admission
        self.store.on_query = lambda sql: setattr(self.store, 'terms', copy.deepcopy(MANAGED))
        with self.assertRaises(credit_admission.DispatchFundingUnavailable) as caught:
            self.execute_evaluator()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.calls, [])

    def test_all_model_queue_producers_refuse_v2_without_preparation(self):
        for worker_type in (enrichment.TrendEnrichment, generation.TrendGeneration, lab_enrichment.TrendLabEnrichment):
            worker = worker_type(self.hosted, store=self.store)
            self.store.terms = copy.deepcopy(MANAGED)
            with self.subTest(worker=worker_type.__name__), self.assertRaises(AlphaError) as caught:
                worker._enqueue_loaded(FundingCursor(self.store), F.WORKSPACE, F.OTHER, F.WORKSPACE,
                                       'workspace_fit', {}, 'synthetic')
            self.assertEqual(caught.exception.code, CODE)

    def test_generation_transport_plan_change_retains_no_usage_or_attempt(self):
        from postriff_phase2.growth.trends import credit_admission
        self.store.on_query = lambda sql: setattr(self.store, 'terms', copy.deepcopy(FREE))
        worker = generation.TrendGeneration(self.hosted, store=self.store)
        runtime = ServerModelRuntime('synthetic', model=original_generation.MODEL, transport=self.transport)
        sink = MemoryUsageSink()
        loaded = {'config':original_generation.review(), 'pack':original_generation.pack(),
                  'task':'culture_explain', 'context_revision':'context'}
        with self.assertRaises(credit_admission.DispatchFundingUnavailable):
            worker.execute(runtime, loaded, 'culture_explain', F.WORKSPACE, sink)
        self.assertEqual(self.calls, [])
        self.assertEqual(sink.events, [])

    def test_legacy_generation_timeout_records_unknown_usage_once(self):
        worker = generation.TrendGeneration(self.hosted, store=self.store)
        calls = []
        def transport(*args, **kwargs):
            self.assertEqual(self.store.depth, 0)
            calls.append(kwargs['body'])
            raise TimeoutError('synthetic timeout')
        runtime = ServerModelRuntime('synthetic', model=original_generation.MODEL, transport=transport)
        sink = MemoryUsageSink()
        loaded = {'config':original_generation.review(), 'pack':original_generation.pack(),
                  'task':'culture_explain', 'context_revision':'context'}
        with self.assertRaises(Exception):
            worker.execute(runtime, loaded, 'culture_explain', F.WORKSPACE, sink)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(sink.events), 1)
        self.assertIsNone(sink.events[0].cost_usd)


class LegacyWorkerAdmission(original_worker.WorkerAdmission):
    def setUp(self):
        super().setUp()
        install_worker_funding_probe(self)


class LegacyWorkerDispatch(original_worker.WorkerDispatch):
    def setUp(self):
        super().setUp()
        install_worker_funding_probe(self)


class LegacyWorkerRecovery(original_worker.WorkerRecoveryAndDeletion):
    def setUp(self):
        super().setUp()
        install_worker_funding_probe(self)


class LegacyGeneration(original_generation.GenerationUnitTests):
    def setUp(self):
        p = patch.object(enrichment, 'TrendStore', return_value=FundingStore())
        p.start(); self.addCleanup(p.stop)


class GuardContract(F.OfflineTest):
    def test_exact_server_policy_or_free_only_for_both_cursor_shapes(self):
        from postriff_phase2.growth.trends import credit_admission as guard
        for tuple_rows in (False, True):
            for terms, expected in ((FREE, 'free'), (MANAGED, 'managed_credits'), (LEGACY, 'legacy'),
                    ({'plan':'creator', 'credit_policy':'rafii-pricing-credits-v2'}, 'legacy'),
                    ({'plan':'creator', 'credit_policy':None}, 'legacy')):
                store = FundingStore(terms, tuple_rows=tuple_rows)
                with self.subTest(terms=terms, tuple_rows=tuple_rows):
                    self.assertEqual(guard.funding_mode(FundingCursor(store), F.WORKSPACE), expected)
                    sql, params = store.queries[-1]
                    self.assertIn('JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id', sql)
                    self.assertIn('FOR SHARE OF e,p', sql)
                    self.assertEqual(params, (F.WORKSPACE,))

    def test_missing_terms_do_not_invent_v2_and_keep_original_legacy_branch(self):
        from postriff_phase2.growth.trends import credit_admission as guard
        store = FundingStore(None)
        self.assertEqual(guard.funding_mode(FundingCursor(store), F.WORKSPACE), 'legacy')
        guard.require_dispatch(store, F.WORKSPACE)

    def test_only_pinned_unmetered_bluesky_zero_path_needs_no_paid_authority(self):
        from postriff_phase2.growth.trends import credit_admission as guard
        store = FundingStore(FREE)
        store.transaction = Mock(side_effect=AssertionError('zero path must remain independent of paid admission'))
        guard.require_provider_dispatch(store, F.SCOPE, bluesky.CAPABILITY, 0)
        denied = FundingStore(MANAGED)
        for cap, amount in ((bluesky.CAPABILITY, 1), (replace(bluesky.CAPABILITY, version='unreviewed'), 0),
                            (replace(bluesky.CAPABILITY, endpoint='wss://other.invalid'), 0)):
            with self.subTest(cap=cap, amount=amount), self.assertRaises(AlphaError):
                guard.require_provider_dispatch(denied, F.SCOPE, cap, amount)

    def test_shared_paid_route_with_no_beneficiaries_fails_closed(self):
        from postriff_phase2.growth.trends import credit_admission as guard
        store = FundingStore()
        store.beneficiaries = []
        with self.assertRaises(AlphaError):
            guard.require_provider_dispatch(store, 'shared:synthetic', web.CAPABILITY, 1)


class TransportAndMediaFunding(F.OfflineTest):
    def test_web_second_physical_request_rechecks_changed_entitlement(self):
        store = FundingStore()
        manifest = asdict(F.policy(provider_id='web', operation='corroborate'))
        manifest.update(broker_provider_id='exa_search', corroboration_endpoint=provider_runtime.research.DEFAULT_EXA_URL)
        _, adapter = provider_runtime.binding(store, manifest, web.VERSION)
        calls = []
        class Response(io.BytesIO):
            status = 200
            headers = {}
        def opened(*args, **kwargs):
            self.assertEqual(store.depth, 0)
            calls.append(args)
            store.terms = copy.deepcopy(MANAGED)
            return Response(b'{}')
        opener = Mock()
        opener.open.side_effect = opened
        with patch.object(provider_runtime, 'workspace_state', return_value={'researchEgress':{'web':True}}), \
                patch.object(provider_runtime.research, 'enabled', return_value=True), \
                patch.object(provider_runtime.research, 'hosted', return_value=True), \
                patch.object(provider_runtime, 'safe_url', side_effect=lambda url, **kw:url), \
                patch.object(provider_runtime.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(AlphaError) as caught:
                adapter(policy=F.policy(provider_id='web', operation='corroborate'), cursor={}, now=F.NOW,
                        payload={'query':'synthetic', 'coverage_epoch':'e'}, reservation_microusd=10)
        self.assertEqual(caught.exception.code, CODE)
        self.assertEqual(len(calls), 1)

    def test_remote_media_staging_v2_denied_before_first_head(self):
        store = FundingStore(MANAGED)
        coordinator = media_jobs.MediaJobs(SimpleNamespace(), store=store)
        loaded = {'runtime':{'clips':[{'clip_id':'clip', 'media_sha256':hashlib.sha256(b'abc').hexdigest()}]}, 'media':{'clip':{
                  'objectName':'synthetic.mp4', 'bytes':3, 'mime':'video/mp4', 'etag':'e'}}}
        storage = Mock()
        storage.object_info.return_value = {'bytes':3, 'mime':'video/mp4', 'etag':'e'}
        storage.read_range.return_value = {'data':b'abc', 'ranged':True}
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(AlphaError) as caught:
            coordinator._stage(directory, F.WORKSPACE, loaded, lambda _: None, storage)
        self.assertEqual(caught.exception.code, CODE)
        storage.object_info.assert_not_called()
        storage.read_range.assert_not_called()

    def test_media_each_head_and_range_rechecks_plan_and_releases_lock(self):
        for change_at in ('head', 'range', None):
            with self.subTest(change_at=change_at):
                store = FundingStore()
                coordinator = media_jobs.MediaJobs(SimpleNamespace(), store=store)
                loaded = {'runtime':{'clips':[{'clip_id':'clip', 'media_sha256':hashlib.sha256(b'abc').hexdigest()}]},
                          'media':{'clip':{'objectName':'synthetic.mp4', 'bytes':3, 'mime':'video/mp4', 'etag':'e'}}}
                calls = []
                def head(*args):
                    self.assertEqual(store.depth, 0)
                    calls.append('head')
                    if change_at == 'head': store.terms = copy.deepcopy(FREE)
                    return {'bytes':3, 'mime':'video/mp4', 'etag':'e'}
                def ranged(*args):
                    self.assertEqual(store.depth, 0)
                    calls.append('range')
                    if change_at == 'range': store.terms = copy.deepcopy(MANAGED)
                    return {'data':b'abc', 'ranged':True}
                storage = SimpleNamespace(object_info=head, read_range=ranged)
                with tempfile.TemporaryDirectory() as directory:
                    if change_at:
                        with self.assertRaises(AlphaError):
                            coordinator._stage(directory, F.WORKSPACE, loaded, lambda _: None, storage)
                        self.assertEqual(list(Path(directory).iterdir()), [])
                    else:
                        result = coordinator._stage(directory, F.WORKSPACE, loaded, lambda _: None, storage)
                        self.assertEqual(Path(directory, result['clip']['media']).read_bytes(), b'abc')
                self.assertEqual(calls, ['head'] if change_at == 'head' else
                                 ['head', 'range'] if change_at == 'range' else ['head', 'range', 'head'])


class QueuedModelFunding(F.OfflineTest):
    def harness(self, worker_type, terms=MANAGED, cached=False, change_after_start=False):
        class QueueCursor(FundingCursor):
            def execute(cur, sql, params=None):
                if '/* trends:' in sql:
                    return super().execute(sql, params)
                if "SELECT * FROM pr_trend_jobs WHERE kind=" in sql:
                    cur.result = [copy.deepcopy(cur.store.pending)]
                elif 'SELECT state FROM pr_trend_jobs' in sql:
                    cur.result = [('queued',)]
                elif 'SELECT 1 FROM pr_trend_jobs' in sql:
                    cur.result = []
                else:
                    raise AssertionError('Unexpected queue SQL: ' + sql)
        class QueueStore(FundingStore):
            @contextmanager
            def transaction(store, cursor=None):
                store.depth += 1
                try: yield cursor or QueueCursor(store)
                finally: store.depth -= 1
        store = QueueStore(terms)
        actor = '22222222-2222-4222-8222-222222222222'
        controls = {'workspace_id':F.WORKSPACE, 'actor_id':actor, 'receipt_id':F.WORKSPACE,
                    'task':'workspace_fit', 'cache_key':'key', 'context_revision':'context',
                    'policy_digest':'policy', 'result_id':'result'}
        store.pending = {'kind':worker_type.kind, 'scope_key':F.SCOPE, 'job_id':F.WORKSPACE, 'payload':controls}
        @contextmanager
        def transaction(*args):
            with store.transaction() as cur:
                yield cur, (None, {}), actor
        repository = SimpleNamespace(transaction=transaction)
        hosted = SimpleNamespace(repository=repository)
        values = {'RAFII_TREND_'+n+'_ENABLED':'1' for n in (*enrichment.REQUIRED_FLAGS, 'OPPORTUNITY_LAB')}
        values['RAFII_TREND_WORKSPACE_ALLOWLIST'] = F.WORKSPACE
        worker = worker_type(hosted, store=store, values=values, monotonic=lambda:0)
        loaded = {'key':'key', 'context_revision':'context', 'policy_digest':'policy', 'result_id':'result',
                  'config':{'budget_keys':['synthetic'], 'approved_attempt_cap_microusd':1000}}
        worker._load = Mock(return_value=loaded)
        worker._cached = Mock(return_value={'stored':True} if cached else None)
        worker._model = Mock(return_value=Mock())
        worker.prepare_model = Mock()
        worker.execute = Mock(side_effect=AssertionError('queued v2 must not reach execution'))
        claim = {'scope_key':F.SCOPE, 'job_id':F.WORKSPACE, 'reservation_id':'synthetic'}
        def start(value, **kwargs):
            if change_after_start: store.terms = copy.deepcopy(FREE)
            return value
        worker.jobs = SimpleNamespace(claim=Mock(return_value=claim), start=Mock(side_effect=start),
                                     cancel=Mock(), fail=Mock(), finish_local=Mock(), account_attempt=Mock())
        p = patch.object(enrichment, 'principal_repository', return_value=(repository, 'synthetic-capability'))
        p.start(); self.addCleanup(p.stop)
        return worker, store

    def test_all_queued_paid_kinds_recheck_effective_plan_before_model_resolution(self):
        for worker_type in (enrichment.TrendEnrichment, generation.TrendGeneration, lab_enrichment.TrendLabEnrichment):
            with self.subTest(worker=worker_type.__name__):
                worker, store = self.harness(worker_type)
                result = worker.tick()
                self.assertEqual(result['provider_attempts'], 0)
                self.assertEqual(result.get('reason_code'), CODE)
                worker._model.assert_not_called()
                worker.jobs.claim.assert_not_called()
                worker.jobs.account_attempt.assert_not_called()
                self.assertEqual(store.depth, 0)

    def test_plan_change_after_start_releases_claim_without_fake_paid_accounting(self):
        worker, store = self.harness(enrichment.TrendEnrichment, LEGACY, change_after_start=True)
        result = worker.tick()
        self.assertEqual(result['provider_attempts'], 0)
        worker.execute.assert_not_called()
        worker.jobs.fail.assert_called_once()
        self.assertTrue(worker.jobs.fail.call_args.kwargs['proven_unbilled'])
        worker.jobs.account_attempt.assert_not_called()
        self.assertEqual(store.depth, 0)

    def test_v2_cached_result_still_finishes_locally_without_funding_or_model(self):
        worker, store = self.harness(enrichment.TrendEnrichment, FREE, cached=True)
        result = worker.tick()
        self.assertEqual(result['cached'], 1)
        self.assertEqual(result['provider_attempts'], 0)
        worker.jobs.finish_local.assert_called_once()
        worker._model.assert_not_called()
        self.assertFalse(any('/* trends:funding */' in sql for sql, _ in store.queries))

