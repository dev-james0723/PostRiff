"""Offline adversarial worker-boundary tests (T14/T15/T17/T31).

Synthetic policies name every PERMISSIONS grant; NOW is fixed UTC. Injected
adapters, jobs and transaction probes exercise worker orchestration, not actual
PostgreSQL atomicity/concurrency or provider qualification. Those have separate
integration owners. Network attempts fail even when the worker catches them.
"""
import builtins
import copy
import os
import sys
from contextlib import contextmanager, ExitStack
from dataclasses import replace
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import test_trend_contracts as F
from postriff_phase2.growth.trends import worker as W
from postriff_phase2.growth.trends.contracts import ContractError, PERMISSIONS
from postriff_phase2.growth.trends.policy import ProviderCapability
from postriff_phase2.growth.trends.providers.base import Batch
from postriff_phase2.growth.trends.providers.registry import ProviderRegistry

NOW = F.NOW
PACKAGE = "postriff_phase2.growth.trends"
JOB_ONE = "33333333-3333-4333-8333-333333333333"
JOB_TWO = "44444444-4444-4444-8444-444444444444"


def switches():
    return {"RAFII_TREND_INTELLIGENCE_ENABLED": "true",
            "RAFII_TREND_RADAR_ENABLED": "true",
            "RAFII_TREND_PROVIDER_OPERATIONS_ENABLED": "true",
            "RAFII_TREND_WORKSPACE_ALLOWLIST": F.WORKSPACE,
            "RAFII_TREND_ALLOWED_OPERATIONS": "fixture:sample"}


def capability():
    return ProviderCapability(provider_id="fixture", operation="sample", version="fixture-v1",
                              evidence_kinds=("raw_post",), endpoint="https://example.com/events",
                              protocol="synthetic-v1", credential_class="synthetic",
                              required_scopes=("read",), max_items=10, max_response_bytes=4096,
                              timeout_seconds=5, max_attempts=1, billable_unit="request",
                              deletion_mechanism="typed_delete_and_account")


def job(job_id=JOB_ONE, *, amount=80, scope_key=F.SCOPE):
    return {"job_id": job_id, "kind": "trend.ingest", "scope_key": scope_key,
            "provider_id": "fixture", "source_policy_version": "fixture-v1",
            "state": "queued", "lease_generation": 0, "attempts": 0, "max_attempts": 2,
            "idempotency_key": "fixture-job:" + job_id,
            "payload": {"operation": "sample", "coverage_epoch": "fixture-epoch",
                        "max_items": 2, "reservation_microusd": amount,
                        "budget_keys": ["system-day", "provider-day", "workspace-day"],
                        "filter": {"language": "yue"}}}


class ProbeCursor:
    """Accept only the worker's read queries; no permissive fake SQL engine."""
    description = ()

    def __init__(self, store):
        self.store = store
        self.result = []

    def execute(self, sql, params=None):
        self.store.queries.append((sql, params))
        if "to_regclass" in sql:
            self.result = [{"ready": self.store.ready}]
        elif "FROM public.pr_trend_jobs" in sql:
            self.result = copy.deepcopy(self.store.candidates)
        elif "FROM public.pr_trend_entitlements" in sql:
            self.result = [{"workspace_id": wid} for wid in self.store.entitled_workspaces]
        elif "FROM public.pr_trend_source_policies" in sql:
            self.result = []  # No schedule opt-in in this manually queued fixture.
        elif "FROM public.pr_trend_source_health" in sql:
            self.result = [self.store.health] if self.store.health else []
        elif "pg_advisory_xact_lock" in sql:
            self.result = []
        else:
            raise AssertionError("Unexpected worker SQL: " + sql)

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class ProbeStore:
    def __init__(self, events):
        self.events = events
        self.candidates = [job()]
        self.entitled_workspaces = []
        self.ready = True
        self.depth = 0
        self.queries = []
        self.active_cursor = None
        self.health = None

    @contextmanager
    def transaction(self, cursor=None):
        if cursor is not None:
            assert cursor is self.active_cursor
            yield cursor
            return
        previous = self.active_cursor
        cur = ProbeCursor(self)
        self.active_cursor = cur
        self.depth += 1
        try:
            yield cur
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.depth -= 1
            self.active_cursor = previous


class WorkerHarness(F.OfflineTest):
    def setUp(self):
        super().setUp()
        self.events = []
        self.store = ProbeStore(self.events)
        self.values = switches()
        self.source_policy = F.policy()
        self.assertEqual(set(self.source_policy.rights), set(PERMISSIONS))
        self.cap = capability()
        self.batch = Batch(observations=(F.row(),), cursor={"sequence": 11},
                           completeness="partial", bytes_received=200, cost_microusd=30)
        self.adapter = Mock(side_effect=self.call_adapter)
        self.checkpoint = {"generation": 7, "cursor_value": {"sequence": 10}}
        self.jobs = SimpleNamespace(
            recover_expired=Mock(side_effect=self.recover), claim=Mock(side_effect=self.claim),
            get_cursor=Mock(side_effect=self.get_cursor), start=Mock(side_effect=self.start),
            account_attempt=Mock(side_effect=self.account),
            complete_batch=Mock(side_effect=self.complete), fail=Mock(return_value={"state": "outcome_unknown"}))
        self.patch(W, "TrendJobs", return_value=self.jobs)
        from postriff_phase2.growth.trends import retry
        self.patch(retry, "TrendJobs", return_value=self.jobs)
        self.maintenance = self.patch(W.analytics_runtime, "maintain", side_effect=self.sweep)
        self.frontier_maintenance = self.patch(W.frontier_runtime, 'maintenance', side_effect=lambda *a,**kw: self.events.append('frontier_maintenance') or {'cancelled':0})
        self.frontier = SimpleNamespace(tick=Mock(side_effect=lambda **kw: self.events.append('frontier_tick') or {}), dispatch_context=Mock())
        self.frontier_factory = self.patch(W, 'DiscoveryFrontier', return_value=self.frontier)
        self.health = self.patch(W.source_health, "record")
        from postriff_phase2.growth.trends import revocation
        self.revoke = self.patch(revocation, "revoke_author", side_effect=self.revoke_author)
        self.pipeline = SimpleNamespace(consume=Mock(), verify_pending=Mock(side_effect=self.verify))
        self.pending_events = []
        self.outbox = SimpleNamespace(claim=Mock(side_effect=self.claim_event),
                                      consume=Mock(side_effect=self.consume_event))
        pipeline_module = ModuleType(PACKAGE + ".pipeline")
        pipeline_module.TrendPipeline = Mock(return_value=self.pipeline)
        outbox_module = ModuleType(PACKAGE + ".outbox")
        outbox_module.TrendOutbox = Mock(return_value=self.outbox)
        p = patch.dict(sys.modules, {pipeline_module.__name__: pipeline_module,
                                     outbox_module.__name__: outbox_module})
        p.start(); self.addCleanup(p.stop)
        self.pipeline_factory = pipeline_module.TrendPipeline
        self.reset_registry()
        self.worker = W.TrendWorker(self.store, registry=self.registry, values=self.values,
                                    clock=lambda: NOW, monotonic=lambda: 0)

    def patch(self, target, name, **kwargs):
        p = patch.object(target, name, **kwargs)
        value = p.start(); self.addCleanup(p.stop)
        return value

    def reset_registry(self):
        self.registry = ProviderRegistry()
        self.registry.register(self.cap, self.source_policy, self.adapter)
        if hasattr(self, "worker"):
            self.worker.registry = self.registry

    def recover(self, **kwargs):
        self.events.append("recover")
        return 1

    def sweep(self, *args, **kwargs):
        self.events.append("maintenance")
        return {"deleted": 1}

    def claim_event(self, *args):
        return self.pending_events.pop(0) if self.pending_events else None

    def consume_event(self, event, handler):
        self.events.append("outbox")
        handler(event)

    def verify(self, **kwargs):
        self.events.append("verify")
        return {"verified": 0}

    def claim(self, worker_id, **kwargs):
        self.assertEqual(self.store.depth, 0)
        # Deliberately require the job ID: scope/kind alone cannot bind cost.
        selected = next(j for j in self.store.candidates if j["job_id"] == kwargs["job_id"])
        with self.store.transaction():
            result = copy.deepcopy(selected)
            result.update(state="leased", lease_owner=worker_id, lease_generation=1,
                          reservation_id="synthetic-reservation:" + result["job_id"], attempts=1)
        self.events.append("claimed:" + result["job_id"])
        return result

    def get_cursor(self, *args):
        with self.store.transaction():
            return copy.deepcopy(self.checkpoint)

    def start(self, claim):
        with self.store.transaction():
            result = dict(claim, state="running")
        self.events.append("start_committed")
        return result

    def call_adapter(self, **kwargs):
        self.assertEqual(self.store.depth, 0, "provider call must occur outside DB transaction")
        self.events.append("adapter")
        return self.batch

    def complete(self, claim, **kwargs):
        self.assertEqual(self.store.depth, 1)
        self.assertIs(kwargs["cursor"], self.store.active_cursor)
        self.events.append("complete")
        return {"generation": 8}

    def account(self, scope_key, reservation_id, event):
        self.assertEqual(self.store.depth, 0, "usage accounting commits outside result attachment")
        self.events.append("accounted")
        return {"usage_event_id": "synthetic-usage", "actual_micro_usd": event.cost_usd_micro(), "replayed": False}

    def revoke_author(self, *args, **kwargs):
        self.assertEqual(self.store.depth, 1)
        self.assertIs(kwargs["cursor"], self.store.active_cursor)
        self.events.append("revoke")

    def assert_no_dispatch(self, result):
        self.assertEqual(result["dispatched"], 0)
        self.adapter.assert_not_called()
        self.jobs.start.assert_not_called()
        self.jobs.complete_batch.assert_not_called()

    def assert_unknown_failure(self, result):
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 0)
        self.assertFalse(self.jobs.fail.call_args.kwargs["proven_unbilled"])
        self.assertIsNone(self.jobs.fail.call_args.kwargs["retry_after_seconds"])


class WorkerAdmission(WorkerHarness):
    def test_source_pause_after_claim_prevents_dispatch(self):
        def paused(worker_id, **kwargs):
            claimed = self.claim(worker_id, **kwargs)
            self.store.health = {"status": "revoked", "next_allowed_at": None}
            return claimed
        self.jobs.claim.side_effect = paused
        self.assert_no_dispatch(self.worker.tick())

    def test_current_source_backoff_prevents_claim(self):
        self.store.health = {"status": "unavailable", "next_allowed_at": F.AFTER}
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_default_off_does_not_import_pipeline_or_dispatch_but_maintains(self):
        self.values.clear()
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            self.assertNotIn(name, ("pipeline", PACKAGE + ".pipeline"))
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            result = self.worker.tick()
        self.assert_no_dispatch(result)
        self.assertEqual(result["status"], "dispatch_disabled")
        self.pipeline_factory.assert_not_called()
        self.jobs.claim.assert_not_called()
        self.jobs.recover_expired.assert_called_once_with(limit=20)
        self.maintenance.assert_called_once_with(self.store, limit=25)
        self.frontier_maintenance.assert_called_once_with(self.store, limit=25)
        self.assertLess(self.events.index("frontier_maintenance"), self.events.index("maintenance"))
        self.frontier_factory.assert_not_called()

    def test_radar_off_stops_new_ingestion_and_keeps_maintenance(self):
        self.values["RAFII_TREND_RADAR_ENABLED"] = "false"
        result = self.worker.tick()
        self.assert_no_dispatch(result)
        self.jobs.claim.assert_not_called()
        self.maintenance.assert_called_once()

    def test_provider_flag_off_stops_new_ingestion(self):
        self.values["RAFII_TREND_PROVIDER_OPERATIONS_ENABLED"] = "false"
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_preview_cannot_dispatch_even_with_all_enabled_values(self):
        self.values["VERCEL_ENV"] = "preview"
        # Explicit values are already-isolated hosted settings. Exercise the
        # actual environment path so this tests preview isolation, not a bypass
        # of its documented input contract.
        self.worker.values = None
        with patch.dict(os.environ, self.values, clear=True), patch.object(W.config.flags, "_values", None):
            self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_missing_workspace_allowlist_is_nobody(self):
        del self.values["RAFII_TREND_WORKSPACE_ALLOWLIST"]
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_operation_allowlist_is_exact_not_publishing_or_provider_wildcard(self):
        for allowed in ("", "fixture", "fixture:*", "fixture:publish", "other:sample"):
            with self.subTest(allowed=allowed):
                self.values["RAFII_TREND_ALLOWED_OPERATIONS"] = allowed
                self.assert_no_dispatch(self.worker.tick())
                self.jobs.claim.assert_not_called()

    def test_unknown_retrieve_right_cannot_reserve_or_dispatch(self):
        self.source_policy = F.policy(rights=F.permissions(retrieve="unknown"))
        self.reset_registry()
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_expired_revoked_or_wrong_audience_right_cannot_dispatch(self):
        cases = [F.policy(expires_at=NOW), F.policy(revoked_at=F.BEFORE),
                 F.policy(rights=F.permissions("workspace:" + F.OTHER))]
        expired_grants = F.permissions()
        expired_grants["retrieve"]["expires_at"] = NOW
        cases.append(F.policy(rights=expired_grants))
        for source in cases:
            with self.subTest(source=source):
                self.source_policy = source; self.reset_registry()
                self.assert_no_dispatch(self.worker.tick())
                self.jobs.claim.assert_not_called()

    def test_unknown_policy_version_or_scope_does_not_fall_back(self):
        self.store.candidates[0]["source_policy_version"] = "unreviewed-v2"
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_missing_migration_never_initializes_pipeline_or_dispatch(self):
        self.store.ready = False
        self.assertEqual(self.worker.tick(), {"status": "migration_pending", "dispatched": 0})
        self.pipeline_factory.assert_not_called()
        self.adapter.assert_not_called()

    def test_missing_priced_cap_or_price_reference_blocks_reservation(self):
        for source in (F.policy(price_ref=None), F.policy(approved_attempt_cap_microusd=None)):
            with self.subTest(source=source):
                self.source_policy = source; self.reset_registry()
                self.assert_no_dispatch(self.worker.tick())
                self.jobs.claim.assert_not_called()

    def test_invalid_budget_and_item_limits_are_rejected_before_claim(self):
        probes = [("reservation_microusd", value) for value in (None, True, -1, 0, 101, 1.5)]
        probes += [("budget_keys", value) for value in (None, [], ["one"], ["x"] * 5, ["a", 1])]
        probes += [("max_items", value) for value in (0, True, 1.5, 11)]
        probes += [("coverage_epoch", value) for value in (None, "", "x" * 161)]
        for key, value in probes:
            with self.subTest(key=key, value=value):
                self.store.candidates = [job()]
                self.store.candidates[0]["payload"][key] = value
                self.assert_no_dispatch(self.worker.tick())
                self.jobs.claim.assert_not_called()

    def test_shared_scope_needs_current_entitled_allowlisted_workspace(self):
        shared = "shared:synthetic"
        self.source_policy = F.policy(shared)
        self.store.candidates = [job(scope_key=shared)]
        self.reset_registry()
        for workspaces in ([], [F.OTHER]):
            with self.subTest(workspaces=workspaces):
                self.store.entitled_workspaces = workspaces
                self.assert_no_dispatch(self.worker.tick())
                self.jobs.claim.assert_not_called()

    def test_shared_scope_unknown_sharing_right_cannot_dispatch(self):
        shared = "shared:synthetic"
        self.source_policy = F.policy(shared, rights=F.permissions(shared, share_across_workspaces="unknown"))
        self.store.candidates = [job(scope_key=shared)]
        self.store.entitled_workspaces = [F.WORKSPACE]
        self.reset_registry()
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_postclaim_rollback_cutoff_proves_no_adapter_call(self):
        def claim_then_rollback(worker_id, **kwargs):
            claimed = self.claim(worker_id, **kwargs)
            self.values["RAFII_TREND_PROVIDER_OPERATIONS_ENABLED"] = "false"
            return claimed
        self.jobs.claim.side_effect = claim_then_rollback
        result = self.worker.tick()
        self.assert_no_dispatch(result)
        self.assertTrue(self.jobs.fail.call_args.kwargs["proven_unbilled"])

    def test_rollback_during_cursor_read_prevents_new_adapter_dispatch(self):
        def cursor_then_rollback(*args):
            checkpoint = self.get_cursor(*args)
            self.values["RAFII_TREND_PROVIDER_OPERATIONS_ENABLED"] = "false"
            return checkpoint
        self.jobs.get_cursor.side_effect = cursor_then_rollback
        result = self.worker.tick()
        self.adapter.assert_not_called()
        self.jobs.complete_batch.assert_not_called()
        self.assertEqual(result["dispatched"], 0)

    def test_rollback_during_start_transaction_prevents_new_adapter_dispatch(self):
        def start_then_rollback(claim):
            started = self.start(claim)
            self.values["RAFII_TREND_RADAR_ENABLED"] = "false"
            return started
        self.jobs.start.side_effect = start_then_rollback
        result = self.worker.tick()
        self.adapter.assert_not_called()
        self.jobs.complete_batch.assert_not_called()
        self.assertEqual(result["dispatched"], 0)


class WorkerDispatch(WorkerHarness):
    def test_planner_runs_before_queue_selection_with_bounded_limit(self):
        with patch.object(W, "FrontierPlanner") as planner:
            planner.return_value.tick.return_value = {"status": "ok", "jobs": [], "blocked": 0}
            planner.return_value.tick.side_effect = lambda **kw: self.events.append("planned") or {"status": "ok"}
            self.worker.tick()
        planner.return_value.tick.assert_called_once_with(limit=20)
        self.assertLess(self.events.index("planned"), self.events.index("claimed:" + JOB_ONE))

    def test_frontier_plan_precedes_claim_and_binds_each_dispatch_boundary(self):
        self.store.candidates[0]['payload']['frontier']={'request_id':'opaque'}
        route={'partition_key':'reviewed-frontier-partition','checkpoint':{'generation':19,'cursor_value':{'page':'reviewed'}},'request_id':'opaque'}
        calls=[]
        def current(candidate, **kwargs):
            calls.append((candidate['state'],bool(kwargs)))
            self.events.append('frontier_commit_check' if kwargs else 'frontier_check')
            if kwargs:
                self.assertIs(kwargs['cursor'],self.store.active_cursor)
                self.assertIn('accounted',self.events)
            return copy.deepcopy(route)
        self.frontier.dispatch_context.side_effect=current
        result=self.worker.tick()
        self.assertEqual(result['completed'],1)
        self.frontier.tick.assert_called_once_with(limit=20)
        self.assertLess(self.events.index('frontier_tick'),self.events.index('claimed:'+JOB_ONE))
        self.assertEqual(calls,[('queued',False),('leased',False),('running',False),('running',True)])
        self.jobs.get_cursor.assert_not_called()
        self.assertEqual(self.adapter.call_args.kwargs['cursor'],route['checkpoint']['cursor_value'])
        attached=self.jobs.complete_batch.call_args.kwargs
        self.assertEqual((attached['partition_key'],attached['expected_generation']),('reviewed-frontier-partition',19))
        self.assertLess(self.events.index('accounted'),self.events.index('frontier_commit_check'))
        self.assertLess(self.events.index('frontier_commit_check'),self.events.index('complete'))

    def test_frontier_denial_before_claim_never_reserves_or_dispatches(self):
        self.store.candidates[0]['payload']['frontier']={'request_id':'opaque'}
        self.frontier.dispatch_context.side_effect=ContractError('frontier_cursor_changed')
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.claim.assert_not_called()

    def test_frontier_revocation_after_start_never_calls_adapter(self):
        self.store.candidates[0]['payload']['frontier']={'request_id':'opaque'}
        route={'partition_key':'reviewed','checkpoint':self.checkpoint,'request_id':'opaque'}
        self.frontier.dispatch_context.side_effect=[route,route,ContractError('frontier_source_revoked')]
        result=self.worker.tick()
        self.assertEqual(result['dispatched'],0)
        self.adapter.assert_not_called()
        self.jobs.complete_batch.assert_not_called()
        self.assertTrue(self.jobs.fail.call_args.kwargs['proven_unbilled'])

    def test_frontier_postaccount_revocation_keeps_spend_without_attaching_data(self):
        self.store.candidates[0]['payload']['frontier']={'request_id':'opaque'}
        route={'partition_key':'reviewed','checkpoint':self.checkpoint,'request_id':'opaque'}
        self.frontier.dispatch_context.side_effect=[route,route,route,ContractError('frontier_source_revoked')]
        self.assert_unknown_failure(self.worker.tick())
        self.jobs.account_attempt.assert_called_once()
        self.assertEqual(self.jobs.account_attempt.call_args.args[2].cost_usd_micro(),30)
        self.jobs.complete_batch.assert_not_called()

    def test_quarantine_and_cursor_share_transaction_and_force_gap(self):
        self.batch = replace(self.batch, completeness="partial",
                             quarantined=({"index": 1, "reason_code": "invalid_record"},))
        def record(store, claim, **kwargs):
            self.assertEqual(store.depth, 1)
            self.assertIs(kwargs["cursor"], store.active_cursor)
            self.assertEqual(kwargs["expected_generation"], 7)
            self.assertEqual(kwargs["quarantined"], self.batch.quarantined)
            self.events.append("quarantine")
        with patch.object(W.quarantine, "record_batch", side_effect=record):
            self.assertEqual(self.worker.tick()["completed"], 1)
        self.assertLess(self.events.index("quarantine"), self.events.index("complete"))
        kw = self.jobs.complete_batch.call_args.kwargs
        self.assertEqual(kw["coverage_state"], "gap")
        self.assertEqual(kw["outbox_events"][0]["payload"]["completeness"], "gap")
        self.assertEqual(self.health.call_args.kwargs["status"], "gap")

    def test_deadline_never_starts_operation_that_cannot_fit(self):
        self.cap = replace(self.cap, timeout_seconds=25)
        self.reset_registry()
        self.assert_no_dispatch(self.worker.tick(max_seconds=20))
        self.jobs.claim.assert_not_called()

    def test_exact_job_id_binds_its_cost_and_budget_dimensions(self):
        self.store.candidates = [job(amount=40), job(JOB_TWO, amount=90)]
        self.store.candidates[1]["payload"]["budget_keys"] = ["system-day", "provider-hour", "workspace-month"]
        result = self.worker.tick(max_jobs=2)
        self.assertEqual(result["completed"], 2)
        self.assertEqual([call.kwargs["job_id"] for call in self.jobs.claim.call_args_list], [JOB_ONE, JOB_TWO])
        self.assertEqual([call.kwargs["amount_micro_usd"] for call in self.jobs.claim.call_args_list], [40, 90])
        self.assertEqual([call.kwargs["budget_keys"] for call in self.jobs.claim.call_args_list],
                         [j["payload"]["budget_keys"] for j in self.store.candidates])
        self.assertEqual([call.kwargs["reservation_microusd"] for call in self.adapter.call_args_list], [40, 90])

    def test_adapter_executes_after_start_commit_outside_all_transactions(self):
        result = self.worker.tick()
        self.assertEqual(result["completed"], 1)
        self.assertLess(self.events.index("start_committed"), self.events.index("adapter"))
        self.assertLess(self.events.index("adapter"), self.events.index("complete"))
        self.assertLess(self.events.index("accounted"), self.events.index("complete"))
        self.adapter.assert_called_once()
        self.assertEqual(self.adapter.call_args.kwargs["now"], NOW)
        self.assertEqual(self.adapter.call_args.kwargs["cursor"], {"sequence": 10})
        self.assertEqual(self.store.depth, 0)

    def test_cursor_and_batch_outbox_commit_use_same_generation_and_transaction(self):
        self.assertEqual(self.worker.tick()["completed"], 1)
        kw = self.jobs.complete_batch.call_args.kwargs
        self.assertEqual(kw["expected_generation"], 7)
        self.assertEqual(kw["cursor_value"], {"sequence": 11})
        self.assertEqual(kw["actual_micro_usd"], 30)
        self.assertEqual(kw["outbox_events"][0]["payload"]["observation_ids"], [F.row()["observation_id"]])
        self.assertIs(kw["cursor"], self.health.call_args.kwargs["cursor"])

    def test_unavailable_exact_claim_never_dispatches_another_job(self):
        self.jobs.claim.side_effect = None
        self.jobs.claim.return_value = None
        self.assert_no_dispatch(self.worker.tick())
        self.jobs.fail.assert_not_called()

    def test_outbox_and_bounded_verification_precede_ingestion(self):
        event = {"event_id": "synthetic-event"}
        self.pending_events = [event]
        self.assertEqual(self.worker.tick()["completed"], 1)
        self.assertLess(self.events.index("outbox"), self.events.index("verify"))
        self.assertLess(self.events.index("verify"), self.events.index("adapter"))
        self.pipeline.verify_pending.assert_called_once_with(limit=5)
        self.pipeline.consume.assert_called_once_with(event)

    def test_outbox_work_is_bounded_by_tick_limit(self):
        self.pending_events = [{"event_id": str(i)} for i in range(5)]
        self.worker.tick(max_jobs=2)
        self.assertEqual(self.outbox.consume.call_count, 2)
        self.assertEqual(len(self.pending_events), 3)

    def test_max_jobs_bounds_dispatch_even_with_more_candidates(self):
        self.store.candidates = [job(), job(JOB_TWO)]
        self.assertEqual(self.worker.tick(max_jobs=1)["dispatched"], 1)
        self.adapter.assert_called_once()

    def test_elapsed_tick_budget_prevents_new_claim(self):
        # The deadline now covers local outbox/verification work as well as I/O.
        from itertools import chain, repeat
        self.worker.monotonic = Mock(side_effect=chain([0], repeat(21)))
        self.assert_no_dispatch(self.worker.tick(max_seconds=20))
        self.jobs.claim.assert_not_called()

    def test_protocol_host_scope_and_filter_partition_cursors(self):
        self.worker.tick()
        first = self.jobs.get_cursor.call_args.args[2]
        self.store.candidates[0]["payload"]["filter"] = {"language": "en"}
        self.worker.tick()
        second = self.jobs.get_cursor.call_args.args[2]
        self.cap = replace(self.cap, endpoint="https://example.org/other", version="fixture-v2")
        self.reset_registry(); self.worker.tick()
        third = self.jobs.get_cursor.call_args.args[2]
        self.assertEqual(len({first, second, third}), 3)

    def test_adapter_cannot_exceed_admitted_job_item_count(self):
        self.batch = replace(self.batch, observations=tuple(F.row(source_identity=str(i)) for i in range(3)))
        result = self.worker.tick()
        self.jobs.complete_batch.assert_not_called()
        self.assert_unknown_failure(result)

    def test_adapter_cannot_exceed_capability_response_byte_limit(self):
        self.batch = replace(self.batch, bytes_received=self.cap.max_response_bytes + 1)
        result = self.worker.tick()
        self.jobs.complete_batch.assert_not_called()
        self.assert_unknown_failure(result)


class WorkerRecoveryAndDeletion(WorkerHarness):
    def test_paid_http_rate_limit_is_not_proof_of_zero_cost(self):
        from urllib.error import HTTPError
        self.adapter.side_effect = HTTPError("https://example.com", 429, "bounded", {"Retry-After": "15"}, None)
        self.assert_unknown_failure(self.worker.tick())
        event = self.jobs.account_attempt.call_args.args[2]
        self.assertIsNone(event.cost_usd)
        self.assertEqual(self.health.call_args.kwargs["reason_code"], "provider_outcome_unknown")

    def test_auth_failure_persists_pause_without_retry(self):
        from urllib.error import HTTPError
        self.adapter.side_effect = HTTPError("https://example.com", 403, "bounded", {}, None)
        self.assert_unknown_failure(self.worker.tick())
        self.assertEqual(self.health.call_args.kwargs["status"], "revoked")
        self.assertEqual(self.health.call_args.kwargs["reason_code"], "provider_access_denied")

    def test_known_accounting_commits_before_revoked_output_is_rejected(self):
        def revoked(**kwargs):
            self.values["RAFII_TREND_RADAR_ENABLED"] = "false"
            return self.call_adapter(**kwargs)
        self.adapter.side_effect = revoked
        self.worker.tick()
        self.jobs.account_attempt.assert_called_once()
        self.assertEqual(self.jobs.account_attempt.call_args.args[2].cost_usd_micro(), 30)
        self.jobs.complete_batch.assert_not_called()
        self.assertIn("accounted", self.events)

    def test_charged_timeout_retains_unknown_exposure_without_retry(self):
        self.adapter.side_effect = TimeoutError("synthetic timeout after acceptance")
        result = self.worker.tick()
        self.assert_unknown_failure(result)
        self.adapter.assert_called_once()
        self.jobs.complete_batch.assert_not_called()

    def test_process_crash_leaves_dispatch_unsettled_for_lease_recovery(self):
        self.adapter.side_effect = SystemExit("synthetic process crash")
        with self.assertRaises(SystemExit):
            self.worker.tick()
        self.jobs.start.assert_called_once()
        self.jobs.fail.assert_not_called()
        self.jobs.complete_batch.assert_not_called()
        self.assertEqual(self.store.depth, 0)

    def test_start_acknowledgment_failure_never_invokes_adapter(self):
        def uncertain_start(claim):
            self.start(claim)
            raise ConnectionError("synthetic lost acknowledgment of committed running state")
        self.jobs.start.side_effect = uncertain_start
        result = self.worker.tick()
        self.adapter.assert_not_called()
        self.jobs.complete_batch.assert_not_called()
        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(result["failed"], 1)
        # DB state may be uncertain, but external invocation has not happened.
        # This differs from the separate crash-after-adapter-invocation test.
        self.assertTrue(self.jobs.fail.call_args.kwargs["proven_unbilled"])

    def test_before_start_failure_is_proven_unbilled_and_retryable(self):
        self.jobs.get_cursor.side_effect = ContractError("cursor_unavailable")
        result = self.worker.tick()
        self.assert_no_dispatch(result)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(self.jobs.fail.call_args.kwargs["proven_unbilled"])
        self.assertIn(self.jobs.fail.call_args.kwargs["retry_after_seconds"], range(3, 6))

    def test_commit_failure_keeps_cost_unknown_and_cursor_unacknowledged(self):
        self.jobs.complete_batch.side_effect = ContractError("stale_cursor_fence")
        result = self.worker.tick()
        self.assert_unknown_failure(result)
        self.assertIn("rollback", self.events)
        self.assertEqual(self.checkpoint, {"generation": 7, "cursor_value": {"sequence": 10}})

    def test_concurrent_fence_revocation_does_not_force_release_or_retry(self):
        self.adapter.side_effect = TimeoutError("synthetic timeout")
        self.jobs.fail.side_effect = ContractError("stale_job_fence")
        self.assert_unknown_failure(self.worker.tick())
        self.jobs.fail.assert_called_once()
        self.adapter.assert_called_once()

    def test_unknown_cost_success_is_not_converted_to_free(self):
        self.batch = replace(self.batch, cost_microusd=None)
        self.assertEqual(self.worker.tick()["completed"], 1)
        self.assertIsNone(self.jobs.complete_batch.call_args.kwargs["actual_micro_usd"])

    def test_midflight_flag_rollback_blocks_commit_retains_unknown_cost(self):
        def rollback(**kwargs):
            self.values["RAFII_TREND_RADAR_ENABLED"] = "false"
            return self.call_adapter(**kwargs)
        self.adapter.side_effect = rollback
        self.assert_unknown_failure(self.worker.tick())
        self.jobs.complete_batch.assert_not_called()

    def test_midflight_right_revocation_blocks_commit(self):
        def revoke(**kwargs):
            self.source_policy = F.policy(revoked_at=NOW)
            self.reset_registry()
            # The admitted registry instance must observe current revocation.
            self.worker.registry.resolve = Mock(side_effect=ContractError("source_right_not_permitted"))
            old_registry.resolve = self.worker.registry.resolve
            return self.call_adapter(**kwargs)
        old_registry = self.registry
        self.adapter.side_effect = revoke
        self.assert_unknown_failure(self.worker.tick())
        self.jobs.complete_batch.assert_not_called()

    def test_error_logs_never_include_provider_response_or_private_text(self):
        self.adapter.side_effect = RuntimeError("SYNTHETIC_SECRET https://private.invalid/private-evidence")
        with self.assertLogs("postriff.trends", level="WARNING") as logs:
            result = self.worker.tick()
        self.assert_unknown_failure(result)
        self.assertNotIn("SYNTHETIC_SECRET", " ".join(logs.output))
        self.assertNotIn("private.invalid", " ".join(logs.output))

    def test_delete_tombstone_preserved_with_source_identity_and_cursor(self):
        deleted = F.row(operation="delete", payload={}, revision_identity="rev-2", sequence=2)
        self.batch = replace(self.batch, observations=(deleted,))
        self.assertEqual(self.worker.tick()["completed"], 1)
        saved = self.jobs.complete_batch.call_args.kwargs["observations"][0]
        self.assertEqual(saved, deleted)
        self.assertEqual(saved["payload"], {})
        self.assertEqual(saved["deletion_key"], deleted["source_identity"])

    def test_inactive_account_revocation_shares_batch_commit_transaction(self):
        marker = {"kind": "account", "did": "did:plc:synthetic", "active": False, "sequence": 11}
        self.batch = replace(self.batch, observations=(), markers=(marker,))
        self.assertEqual(self.worker.tick()["completed"], 1)
        complete = self.jobs.complete_batch.call_args.kwargs
        self.revoke.assert_called_once_with(self.store, "fixture", "fixture:did:plc:synthetic", cursor=complete["cursor"])
        self.assertLess(self.events.index("revoke"), self.events.index("complete"))
        self.assertEqual(complete["outbox_events"][0]["payload"]["markers"], [marker])

    def test_active_identity_sync_and_gap_markers_are_preserved_without_revocation(self):
        markers = ({"kind": "account", "did": "did:plc:synthetic", "active": True},
                   {"kind": "identity", "did": "did:plc:synthetic"},
                   {"kind": "sync", "sequence": 11}, {"kind": "gap", "from": 10, "to": 12})
        self.batch = replace(self.batch, markers=markers, completeness="gap", reason_code="stream_gap")
        self.assertEqual(self.worker.tick()["completed"], 1)
        self.revoke.assert_not_called()
        kw = self.jobs.complete_batch.call_args.kwargs
        self.assertEqual(kw["coverage_state"], "gap")
        self.assertEqual(kw["outbox_events"][0]["payload"]["markers"], list(markers))
        self.assertEqual(self.health.call_args.kwargs["status"], "gap")

    def test_account_revocation_failure_prevents_batch_or_cursor_commit(self):
        self.batch = replace(self.batch, markers=({"kind": "account", "did": "did:plc:synthetic", "active": False},))
        self.revoke.side_effect = ContractError("synthetic_revocation_failure")
        self.assert_unknown_failure(self.worker.tick())
        self.jobs.complete_batch.assert_not_called()
        self.assertIn("rollback", self.events)


class CronCapabilityBoundary(F.OfflineTest):
    def run_cron(self, enabled, *, status='disabled', elapsed=0):
        from postriff_phase2.growth.trends import operations, opportunities, notifications
        events = []
        advanced = SimpleNamespace(
            plan_current=Mock(side_effect=lambda **kw: events.append('advanced_plan') or {}),
            tick=Mock(side_effect=lambda **kw: events.append('advanced_tick') or {}))
        module = ModuleType(PACKAGE + '.advanced_pipeline')
        module.AdvancedPipeline = Mock(return_value=advanced)
        model = SimpleNamespace(plan_current=Mock(return_value={}), tick=Mock(return_value={}))
        model_module = ModuleType(PACKAGE + '.enrichment')
        model_module.TrendEnrichment = Mock(return_value=model)
        generation=SimpleNamespace(plan_current=Mock(return_value={}),tick=Mock(return_value={}))
        generation_module=ModuleType(PACKAGE+'.generation')
        generation_module.TrendGeneration=Mock(return_value=generation)
        lab=SimpleNamespace(tick=Mock(return_value={}))
        lab_module=ModuleType(PACKAGE+'.lab_enrichment')
        lab_module.TrendLabEnrichment=Mock(return_value=lab)
        media=SimpleNamespace(sweep=Mock(side_effect=lambda **kw: events.append('media_maintenance') or {}),run=Mock())
        media_module=ModuleType(PACKAGE+'.media_jobs')
        media_module.MediaJobs=Mock(return_value=media)
        whitespace=SimpleNamespace(plan_current=Mock(side_effect=lambda **kw:events.append('whitespace_plan') or {}))
        whitespace_module=ModuleType(PACKAGE+'.whitespace_admission')
        whitespace_module.WhitespaceAdmission=Mock(return_value=whitespace)
        instance = SimpleNamespace(tick=Mock(side_effect=lambda: events.append('pipeline') or {'status': status}))
        service = SimpleNamespace(repository=SimpleNamespace(connection_factory=Mock()))
        clock = iter([0] + [elapsed]*20)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {module.__name__: module, model_module.__name__: model_module,
                generation_module.__name__:generation_module,media_module.__name__:media_module,lab_module.__name__:lab_module,whitespace_module.__name__:whitespace_module}))
            stack.enter_context(patch.object(W, 'TrendStore', return_value=object()))
            stack.enter_context(patch.object(W, 'TrendWorker', return_value=instance))
            stack.enter_context(patch.object(W.time, 'monotonic', side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(W.config, 'enabled', side_effect=lambda name: name in enabled))
            fit = stack.enter_context(patch.object(opportunities, 'refresh_workspace_candidates', return_value={}))
            notify = stack.enter_context(patch.object(notifications, 'tick', return_value={}))
            stack.enter_context(patch.object(operations, 'snapshot', return_value={'reason_codes': []}))
            result = W.cron(service)
        self.enrichment_factory, self.enrichment = model_module.TrendEnrichment, model
        self.generation_factory,self.generation=generation_module.TrendGeneration,generation
        self.whitespace_factory,self.whitespace=whitespace_module.WhitespaceAdmission,whitespace
        self.media=media
        self.lab_factory,self.lab=lab_module.TrendLabEnrichment,lab
        return result, events, module.AdvancedPipeline, advanced, fit, notify

    def test_off_and_trust_off_never_construct_advanced_workers(self):
        for enabled in (set(), {'INTELLIGENCE', 'RADAR', 'GRAPH_GENOME', 'FORECASTS', 'NOTIFICATIONS'}):
            result, _, factory, _, _, notify = self.run_cron(enabled)
            factory.assert_not_called(); notify.assert_not_called()
            self.enrichment_factory.assert_not_called()
            self.generation_factory.assert_not_called()
            self.media.sweep.assert_called_once_with(limit=20)
            self.media.run.assert_not_called()
            self.assertNotIn('advanced', result)

    def test_verified_pipeline_precedes_bounded_local_advanced_jobs(self):
        result, events, factory, worker, _, _ = self.run_cron({'INTELLIGENCE','RADAR','TRUST_RECEIPTS','GRAPH_GENOME'})
        self.assertEqual(events, ['pipeline', 'media_maintenance', 'advanced_plan', 'advanced_tick'])
        worker.plan_current.assert_called_once_with(max_workspaces=1, trend_limit=2)
        worker.tick.assert_called_once_with(limit=2, max_seconds=8)
        self.assertIn('advanced', result)

    def test_missing_migration_and_elapsed_budget_do_not_start_optional_jobs(self):
        enabled = {'INTELLIGENCE','RADAR','TRUST_RECEIPTS','GRAPH_GENOME','NOTIFICATIONS'}
        for kwargs in ({'status':'migration_pending'}, {'elapsed':26}):
            _, _, factory, _, fit, notify = self.run_cron(enabled, **kwargs)
            factory.assert_not_called(); fit.assert_not_called(); notify.assert_not_called()
            self.enrichment_factory.assert_not_called()

    def test_model_worker_is_separately_gated_and_one_attempt_bounded(self):
        enabled = {'INTELLIGENCE','RADAR','TRUST_RECEIPTS','MODEL_ENRICHMENT'}
        result, _, advanced, _, _, _ = self.run_cron(enabled)
        advanced.assert_called_once()  # Native pattern extraction is local under this flag.
        self.generation.plan_current.assert_called_once_with(max_jobs=2,max_workspaces=2)
        self.generation.tick.assert_called_once_with(max_jobs=1,max_seconds=6)
        self.media.run.assert_not_called()  # Staging belongs to the explicit bounded run route.
        self.enrichment.plan_current.assert_called_once_with(max_jobs=2,max_workspaces=2)
        self.enrichment.tick.assert_called_once_with(max_jobs=1,max_seconds=6)
        self.assertIn('enrichment',result)
        self.run_cron(enabled-{'TRUST_RECEIPTS'})
        self.enrichment_factory.assert_not_called()
        self.run_cron(enabled,elapsed=18)
        self.enrichment_factory.assert_not_called()

    def test_explicit_lab_queue_is_independently_gated_bounded_and_never_planned(self):
        enabled={'INTELLIGENCE','RADAR','TRUST_RECEIPTS','MODEL_ENRICHMENT','OPPORTUNITY_LAB'}
        result,*_=self.run_cron(enabled)
        self.lab.tick.assert_called_once_with(max_jobs=1,max_seconds=6)
        self.assertIn('lab_enrichment',result)
        for omitted in ('OPPORTUNITY_LAB','TRUST_RECEIPTS','MODEL_ENRICHMENT'):
            self.run_cron(enabled-{omitted})
            self.lab_factory.assert_not_called()

    def test_whitespace_planner_after_source_consumers_and_flag_elapsed_gates(self):
        enabled={'INTELLIGENCE','RADAR','TRUST_RECEIPTS','WHITESPACE'}
        result,events,*_=self.run_cron(enabled)
        self.assertLess(events.index('advanced_tick'),events.index('whitespace_plan'))
        self.whitespace.plan_current.assert_called_once_with(max_workspaces=1,trend_limit=2)
        self.assertIn('whitespace_planner',result)
        for missing in ('WHITESPACE','TRUST_RECEIPTS','INTELLIGENCE'):
            self.run_cron(enabled-{missing});self.whitespace_factory.assert_not_called()
        self.run_cron(enabled,elapsed=21);self.whitespace_factory.assert_not_called()
