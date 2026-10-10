"""Synthetic worker boundaries; no HTTP, vault or provider authorization."""
from unittest.mock import Mock
from test_trend_worker import WorkerHarness
from test_trend_meta_public import policy
from postriff_phase2.growth.trends.providers import meta_public as M
from postriff_phase2.growth.trends.providers.meta_runtime import MetaCollector
from postriff_phase2.growth.trends.contracts import ContractError
from postriff_phase2.growth.trends import worker as W

class ProbeMeta(MetaCollector):
    def __init__(self, error, attempts):
        self.error, self.http_attempts = error, attempts
    def assert_current(self, *args, **kw): pass
    def __call__(self, **kw): raise self.error

class MetaWorker(WorkerHarness):
    def setup_meta(self, error, attempts):
        self.source_policy=policy('threads')
        self.cap=M.CAPABILITIES['threads','keyword_search']
        self.values['RAFII_TREND_ALLOWED_OPERATIONS']='threads:keyword_search'
        candidate=self.store.candidates[0]
        candidate.update(provider_id='threads',max_attempts=1)
        candidate['payload'].update(operation='keyword_search',reservation_microusd=0)
        candidate['payload'].pop('filter',None)
        self.adapter=ProbeMeta(error,attempts)
        self.jobs.defer_local=Mock(return_value={'state':'retry_wait','attempts':0})
        self.failure=self.patch(W,'fail_attempt')
        self.reset_registry()

    def test_first_quota_denial_defers_without_attempt_or_usage(self):
        self.setup_meta(ContractError('meta_provider_quota_exhausted'),0)
        result=self.worker.tick()
        self.assertEqual(result['dispatched'],0)
        self.jobs.account_attempt.assert_not_called()
        self.jobs.defer_local.assert_called_once()
        self.failure.assert_not_called()

    def test_second_request_denial_keeps_prior_external_attempt(self):
        self.setup_meta(ContractError('meta_provider_quota_exhausted'),1)
        result=self.worker.tick()
        self.assertEqual(result['dispatched'],1)
        self.jobs.account_attempt.assert_called_once()
        self.jobs.defer_local.assert_not_called()
        self.assertTrue(self.failure.call_args.kwargs['dispatched'])

    def test_sanitized_status_and_retry_reach_single_retry_owner(self):
        for status in (401,403,429):
            with self.subTest(status=status):
                self.setup_meta(M.MetaTransportError('meta_provider_unavailable',status=status,retry_after_seconds=37),1)
                self.worker.tick()
                self.assertEqual(self.failure.call_args.kwargs['status'],status)
                self.assertEqual(self.failure.call_args.kwargs['headers'],{'Retry-After':'37'})

class MetaRateLimit(WorkerHarness):
    def test_exhausted_job_still_blocks_next_provider_job_until_retry_after(self):
        from test_trend_planner import FakeStore
        from test_trend_contracts import SCOPE,NOW
        from postriff_phase2.growth.trends import retry
        self.patch(retry,'TrendJobs')
        health=self.patch(retry.source_health,'record')
        retry.fail_attempt(FakeStore(),dict(scope_key=SCOPE,provider_id='threads',attempts=1,max_attempts=1),
            status=429,headers={'Retry-After':'120'},dispatched=True,proven_unbilled=True,now=NOW)
        self.assertEqual(health.call_args.kwargs['next_allowed_at'],'2026-09-27T12:02:00Z')
