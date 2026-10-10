"""Bounded durable trend worker. No provider call occurs under a database lock.

The queue is server-owned. Registry admission, current policy and every dispatch
switch are checked before claiming, immediately before I/O, and at commit.
Maintenance is independent of rollout switches, including after rollback.
"""
from __future__ import annotations
from .providers.base import monetary

from dataclasses import fields
from decimal import Decimal
import logging
import random
import time
import urllib.error
import uuid

from . import config, retention, source_health, analytics_runtime, frontier_runtime
from .contracts import ContractError, digest, instant
from .jobs import TrendJobs, partition_key
from .planner import FrontierPlanner
from .frontier import DiscoveryFrontier
from .retry import fail_attempt
from . import quarantine
from .policy import SourcePolicy, admit
from .providers.base import Batch
from .providers.registry import ProviderRegistry, contract_runtime_version
from .providers.meta_runtime import MetaCollector
from .providers.meta_public import MetaTransportError
from .store import TrendStore, row, rows, utcnow

LOG = logging.getLogger('postriff.trends')


def cursor_partition(cap, policy, payload):
    filters={'operation':policy.operation,'scope':policy.scope_key,'filter':payload.get('filter',{})}
    if 'discovery_request_id' in payload:
        # An immutable user selection owns its own pagination checkpoint. Neither
        # another query nor the operator's scheduled selection may reuse it.
        filters.update(discovery_request_id=payload['discovery_request_id'],
                       coverage_epoch=payload.get('coverage_epoch'))
    return partition_key(instance_id=cap.endpoint,protocol_version=cap.version,
                         filter_digest=digest(filters))


def _scope_enabled(store, scope_key, values):
    if scope_key.startswith('workspace:'):
        return config.workspace_allowed(scope_key[10:], values)
    # Shared ingestion needs an entitled, explicitly allowlisted customer. An
    # enabled shared scope alone must not spend against an empty rollout.
    with store.transaction() as cur:
        cur.execute('''SELECT workspace_id FROM public.pr_trend_entitlements
            WHERE scope_key=%s AND revoked_at IS NULL AND expires_at>clock_timestamp()
            AND 'retrieve'=ANY(operations) LIMIT 1001''', (scope_key,))
        return any(config.workspace_allowed(r['workspace_id'], values) for r in rows(cur))


def configured_registry(store):
    """Load only reviewed policies for implemented operations; never invent rights.

    Registering the implementation is not live qualification. Unknown adapters,
    paid archive access and operations without a runtime binding remain closed.
    """
    from .providers import bluesky, runtime
    registry = ProviderRegistry()
    with store.transaction() as cur:
        cur.execute('''SELECT p.manifest,p.provider_contract_version,c.manifest AS contract_manifest
            FROM public.pr_trend_source_policies p
            JOIN public.pr_trend_provider_contracts c
              ON (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
            WHERE p.readiness='ready' AND p.revoked_at IS NULL AND p.valid_from<=clock_timestamp()
            AND p.expires_at>clock_timestamp() AND c.revoked_at IS NULL
            AND c.valid_from<=clock_timestamp() AND c.expires_at>clock_timestamp()
            ORDER BY p.scope_key,p.provider_id,p.version LIMIT 100''')
        policies = rows(cur)
    keys = {f.name for f in fields(SourcePolicy)}
    for item in policies:
        p = item['manifest']
        try:
            policy = SourcePolicy(**{k: v for k, v in p.items() if k in keys})
            contract_manifest = item.get('contract_manifest') or {}
            runtime_version = contract_runtime_version(item['provider_contract_version'], contract_manifest)
            if ((p.get('provider_id'), p.get('operation'), runtime_version) ==
                    ('bluesky', 'live_sample', bluesky.PROTOCOL)
                    and contract_manifest.get('endpoint') == bluesky.CAPABILITY.endpoint
                    and contract_manifest.get('billable_unit') == bluesky.CAPABILITY.billable_unit):
                selected = (bluesky.CAPABILITY, _bluesky)
            else:
                selected = runtime.binding(store, p, runtime_version)
            if selected:
                registry.register(selected[0], policy, selected[1])
        except (TypeError, ValueError):
            LOG.warning('trend.policy_configuration_invalid')
    return registry


def _bluesky(*, policy, cursor, now, payload, reservation_microusd):
    from .providers.bluesky import collect
    return collect(policy=policy, enabled=True, entitlement_current=True,
                   received_at=now, available_at=now,
                   coverage_epoch=payload['coverage_epoch'], cursor=cursor or None,
                   max_items=payload.get('max_items', 100), seconds=payload.get('seconds', 5))


class TrendWorker:
    def __init__(self, store, *, registry=None, values=None, clock=utcnow, monotonic=time.monotonic):
        self.store = store
        self.jobs = TrendJobs(store)
        self.registry = registry
        self.values = values
        self.clock = clock
        self.monotonic = monotonic
        self.worker_id = 'trend-' + str(uuid.uuid4())

    def available(self):
        with self.store.transaction() as cur:
            cur.execute("SELECT to_regclass('public.pr_trend_jobs') IS NOT NULL AS ready")
            return row(cur)['ready']

    def _admission(self, job, registry):
        payload = job['payload']
        operation = payload.get('operation')
        if (job['kind'] != 'trend.ingest' or not _scope_enabled(self.store, job['scope_key'], self.values)
                or not config.dispatch_allowed(job['provider_id'], operation, self.values)):
            raise ContractError('dispatch_disabled')
        capability, policy, adapter = registry.resolve(job['provider_id'], operation,
            job['scope_key'], job['source_policy_version'], at=self.clock())
        if (policy.provider_id, policy.operation) == ('web', 'corroborate'):
            from .providers.runtime import workspace_state
            workspace_state(self.store, policy)
        if hasattr(adapter, 'assert_current'):
            adapter.assert_current(policy, self.clock())
        # A cost cap is explicit even for currently unmetered traffic. Positive
        # priced calls also require the reviewed attempt cap and price reference.
        budget_keys = payload.get('budget_keys')
        amount = payload.get('reservation_microusd')
        if (not isinstance(budget_keys, list) or not 2 <= len(budget_keys) <= 4
                or any(not isinstance(k, str) or not k or len(k) > 160 for k in budget_keys)
                or type(amount) is not int or amount < 0):
            raise ContractError('dispatch_budget_required')
        if not isinstance(payload.get('coverage_epoch'), str) or not 1 <= len(payload['coverage_epoch']) <= 160:
            raise ContractError('coverage_epoch_required')
        admit(capability, policy, at=self.clock(), requested_scope=job['scope_key'], enabled=True,
              item_limit=payload.get('max_items', 100), byte_limit=capability.max_response_bytes,
              reservation_microusd=amount, entitlement_current=True,
              billable=monetary(capability))
        with self.store.transaction() as cur:
            cur.execute('''SELECT status,next_allowed_at FROM public.pr_trend_source_health
                WHERE scope_key=%s AND provider_id=%s''', (job['scope_key'], job['provider_id']))
            health = row(cur)
            if health and (health['status'] == 'revoked' or health.get('next_allowed_at')
                    and instant(health['next_allowed_at']) > instant(self.clock())):
                raise ContractError('source_paused')
        return capability, policy, adapter, amount, budget_keys

    def tick(self, *, max_jobs=2, max_seconds=20):
        if type(max_jobs) is not int or not 1 <= max_jobs <= 5 or not 1 <= max_seconds <= 30:
            raise ContractError('worker_bounds')
        if not self.available():
            return {'status': 'migration_pending', 'dispatched': 0}
        started = self.monotonic()
        result = {'status': 'ok', 'dispatched': 0, 'completed': 0, 'failed': 0, 'blocked': 0}
        result['recovered'] = self.jobs.recover_expired(limit=20)
        result['frontier_maintenance'] = frontier_runtime.maintenance(self.store, limit=25)
        result['maintenance'] = analytics_runtime.maintain(self.store, limit=25)
        if config.enabled('INTELLIGENCE', self.values):
            from .pipeline import TrendPipeline
            from .outbox import TrendOutbox
            pipeline = TrendPipeline(self.store)
            outbox = TrendOutbox(self.store)
            processed = 0
            for _ in range(max_jobs):
                if self.monotonic() - started >= max_seconds:
                    break
                event = outbox.claim('trend.pipeline.v1', self.worker_id)
                if not event:
                    break
                outbox.consume(event, pipeline.consume)
                processed += 1
            result['processed'] = processed
            if self.monotonic() - started < max_seconds:
                result['verification'] = pipeline.verify_pending(limit=5)
        if not all(config.enabled(x, self.values) for x in ('INTELLIGENCE', 'RADAR', 'PROVIDER_OPERATIONS')):
            return {**result, 'status': 'dispatch_disabled'}
        registry = self.registry or configured_registry(self.store)
        if self.monotonic() - started >= max_seconds:
            return result
        result['planner'] = FrontierPlanner(self.store, registry, values=self.values, clock=self.clock).tick(limit=20)
        frontier = DiscoveryFrontier(self.store, registry, values=self.values, clock=self.clock)
        result['frontier'] = frontier.tick(limit=20)
        if self.monotonic() - started >= max_seconds:
            return result
        with self.store.transaction() as cur:
            cur.execute('''SELECT * FROM public.pr_trend_jobs
                WHERE state IN ('queued','retry_wait') AND kind='trend.ingest'
                AND due_at<=clock_timestamp() AND NOT cancellation_requested
                ORDER BY priority DESC,due_at,job_id LIMIT %s''', (max_jobs * 4,))
            candidates = rows(cur)
        for candidate in candidates:
            if result['dispatched'] >= max_jobs or self.monotonic() - started >= max_seconds:
                break
            try:
                cap, policy, adapter, amount, budget_keys = self._admission(candidate, registry)
                if 'frontier' in candidate['payload']:
                    frontier.dispatch_context(candidate)
            except ContractError:
                result['blocked'] += 1
                continue
            operation_seconds = cap.timeout_seconds
            if (cap.provider_id, policy.operation) == ('bluesky', 'live_sample'):
                operation_seconds = candidate['payload'].get('seconds', 5) + 1
            if self.monotonic() - started + operation_seconds > max_seconds:
                break
            claim = self.jobs.claim(self.worker_id, job_id=candidate['job_id'],
                scope_key=candidate['scope_key'], kind='trend.ingest', budget_keys=budget_keys,
                amount_micro_usd=amount, lease_seconds=60)
            if not claim:
                continue
            dispatched = False
            accounting = None
            batch = None
            attempt_started = self.monotonic()
            try:
                self._admission(claim, registry)
                if 'frontier' in claim['payload']:
                    route = frontier.dispatch_context(claim)
                    partition, checkpoint = route['partition_key'], route['checkpoint']
                else:
                    partition = cursor_partition(cap,policy,claim['payload'])
                    checkpoint = self.jobs.get_cursor(claim['scope_key'], cap.provider_id, partition)
                claim = self.jobs.start(claim)
                # Configuration may change while a cursor/start transaction waits.
                # No external attempt occurred yet, so denial here can release it.
                self._admission(claim, registry)
                if 'frontier' in claim['payload']:
                    frontier.dispatch_context(claim)
                dispatched = True
                result['dispatched'] += 1
                # start() has committed. Adapter I/O is bounded and outside all locks.
                batch = adapter(policy=policy, cursor=checkpoint['cursor_value'], now=self.clock(),
                                payload=claim['payload'], reservation_microusd=amount)
                if (not isinstance(batch, Batch) or len(batch.observations) > claim['payload'].get('max_items', 100)
                        or len(batch.observations) > cap.max_items or type(batch.bytes_received) is not int
                        or not 0 <= batch.bytes_received <= cap.max_response_bytes
                        or batch.cost_microusd is not None and
                        (type(batch.cost_microusd) is not int or batch.cost_microusd < 0)):
                    raise ContractError('adapter_contract_mismatch')
                # Acquisition uses the existing usage ledger too. A later trust
                # rejection must never roll back already incurred external cost.
                from ..usage import UsageEvent
                accounting = self.jobs.account_attempt(claim['scope_key'], claim['reservation_id'], UsageEvent(
                    task='trend.ingest', model='source/' + cap.provider_id, route='primary', status='ok',
                    provider=cap.provider_id, latency_ms=max(0, round((self.monotonic()-attempt_started)*1000)),
                    workspace_id=claim['scope_key'][10:] if claim['scope_key'].startswith('workspace:') else None,
                    cost_usd=Decimal(batch.cost_microusd) / Decimal(1_000_000) if batch.cost_microusd is not None else None,
                    cost_source='table:trend-provider-contract-v1' if batch.cost_microusd is not None else 'unknown'))
                self._admission(claim, registry)
                completeness = 'gap' if batch.quarantined else batch.completeness
                with self.store.transaction() as cur:
                    if hasattr(adapter, 'assert_current'):
                        adapter.assert_current(policy, self.clock(), cursor=cur)
                    if 'frontier' in claim['payload']:
                        frontier.dispatch_context(claim, cursor=cur)
                    from .revocation import revoke_author
                    for marker in batch.markers:
                        if marker.get('kind') == 'account' and marker.get('active') is False:
                            revoke_author(self.store, cap.provider_id, cap.provider_id + ':' + marker['did'], cursor=cur)
                    quarantine.record_batch(self.store, claim, partition_key=partition,
                        expected_generation=checkpoint['generation'], quarantined=batch.quarantined,
                        accepted_count=len(batch.observations), cursor=cur)
                    self.jobs.complete_batch(claim, partition_key=partition,
                        expected_generation=checkpoint['generation'], batch_key=digest([claim['job_id'], claim['lease_generation']]),
                        observations=batch.observations, cursor_value=batch.cursor or {},
                        terminal_page=batch.terminal_page, coverage_state=completeness,
                        outbox_events=[{'event_key': 'batch:' + claim['job_id'], 'event_type': 'trend.ingested',
                            'payload': {'observation_ids': [o['observation_id'] for o in batch.observations],
                                        'provider_id': cap.provider_id,
                                        'coverage_epoch': claim['payload']['coverage_epoch'],
                                        'completeness': completeness, 'markers': list(batch.markers)}}],
                        actual_micro_usd=accounting['actual_micro_usd'], usage_event_id=accounting['usage_event_id'], cursor=cur)
                    if isinstance(adapter,MetaCollector) and 'discovery_request_id' in claim['payload']:
                        from . import meta_discovery
                        meta_discovery.record_batch(self.store,claim,batch,cursor=cur)
                    source_health.record(self.store, claim['scope_key'], cap.provider_id,
                        status='gap' if completeness == 'gap' else 'partial',
                        reason_code=batch.reason_code or 'bounded_sample', cursor=cur)
                result['completed'] += 1
            except Exception as exc:
                # Never log provider response text, URLs, account IDs or evidence.
                code = exc.code if isinstance(exc, ContractError) else 'provider_or_commit_failure'
                # Only our server-owned collector may report the actual I/O boundary.
                if isinstance(adapter, MetaCollector) and dispatched and adapter.http_attempts == 0:
                    dispatched = False
                    result['dispatched'] -= 1
                    if code == 'meta_provider_quota_exhausted':
                        self.jobs.defer_local(claim, code=code)
                        result['blocked'] += 1
                        continue
                LOG.warning('trend.job_failed code=%s dispatched=%s', code, dispatched)
                try:
                    unmetered = not monetary(cap) and amount == 0
                    if dispatched and accounting is None:
                        from ..usage import UsageEvent
                        self.jobs.account_attempt(claim['scope_key'], claim['reservation_id'], UsageEvent(
                            task='trend.ingest', model='source/' + cap.provider_id, route='primary', status=code,
                            provider=cap.provider_id, latency_ms=max(0, round((self.monotonic()-attempt_started)*1000)),
                            workspace_id=claim['scope_key'][10:] if claim['scope_key'].startswith('workspace:') else None,
                            cost_usd=0 if unmetered else None,
                            cost_source='table:trend-provider-contract-v1' if unmetered else 'unknown'))
                    fail_attempt(self.store, claim,
                        status=exc.status if isinstance(exc, MetaTransportError) else exc.code if isinstance(exc, urllib.error.HTTPError) else None,
                        headers=({'Retry-After': str(exc.retry_after_seconds)} if exc.retry_after_seconds is not None else None)
                        if isinstance(exc, MetaTransportError) else exc.headers if isinstance(exc, urllib.error.HTTPError) else None,
                        dispatched=dispatched, proven_unbilled=not dispatched or unmetered,
                        jitter=random.random(), now=self.clock())
                except ContractError:
                    # A concurrent revocation/fence expiry owns cleanup. The reservation
                    # stays exposed until recover_expired or explicit reconciliation.
                    pass
                result['failed'] += 1
        return result


def cron(service):
    repository = getattr(service, 'repository', None)
    if repository is None or not getattr(repository, 'connection_factory', None):
        return {'status': 'unavailable', 'dispatched': 0}
    try:
        started = time.monotonic()
        store = TrendStore(repository.connection_factory, meta_vault=getattr(getattr(service, 'oauth', None), 'vault', None))
        result = TrendWorker(store).tick()
        if result['status'] == 'migration_pending':
            return result
        from .media_jobs import MediaJobs
        result['media_maintenance'] = MediaJobs(service,store=store).sweep(limit=20)
        if (time.monotonic() - started < 18 and
                all(config.enabled(name) for name in ('INTELLIGENCE', 'RADAR'))):
            from .opportunities import refresh_workspace_candidates
            result['workspace_candidates'] = refresh_workspace_candidates(service, max_workspaces=5, trend_limit=20)
        if (time.monotonic() - started < 16 and
                all(config.enabled(name) for name in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','MODEL_ENRICHMENT'))):
            from .generation import TrendGeneration
            generation=TrendGeneration(service,store=store)
            result['generation_planner']=generation.plan_current(max_jobs=2,max_workspaces=2)
            remaining=25-(time.monotonic()-started)
            if remaining>=3:
                result['generation']=generation.tick(max_jobs=1,max_seconds=min(6,remaining))
        if (time.monotonic() - started < 16 and
                all(config.enabled(name) for name in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS', 'MODEL_ENRICHMENT'))):
            from .enrichment import TrendEnrichment
            enrichment = TrendEnrichment(service, store=store)
            result['enrichment_planner'] = enrichment.plan_current(max_jobs=2, max_workspaces=2)
            remaining = 25 - (time.monotonic() - started)
            if remaining >= 3:
                result['enrichment'] = enrichment.tick(max_jobs=1, max_seconds=min(6, remaining))
        if (time.monotonic() - started < 19 and
                all(config.enabled(name) for name in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','MODEL_ENRICHMENT','OPPORTUNITY_LAB'))):
            from .lab_enrichment import TrendLabEnrichment
            remaining=25-(time.monotonic()-started)
            if remaining>=3:
                result['lab_enrichment']=TrendLabEnrichment(service,store=store).tick(max_jobs=1,max_seconds=min(6,remaining))
        if (time.monotonic() - started < 17 and
                all(config.enabled(name) for name in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS')) and
                any(config.enabled(name) for name in ('GRAPH_GENOME', 'SATURATION', 'FORECASTS', 'WHITESPACE','MODEL_ENRICHMENT'))):
            from .advanced_pipeline import AdvancedPipeline
            advanced = AdvancedPipeline(store)
            result['advanced_planner'] = advanced.plan_current(max_workspaces=1, trend_limit=2)
            remaining = 25 - (time.monotonic() - started)
            if remaining > 0:
                result['advanced'] = advanced.tick(limit=2, max_seconds=min(8, remaining))
        if (time.monotonic() - started < 20 and
                all(config.enabled(name) for name in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','WHITESPACE'))):
            from .whitespace_admission import WhitespaceAdmission
            result['whitespace_planner'] = WhitespaceAdmission(store).plan_current(max_workspaces=1,trend_limit=2)
        if (time.monotonic() - started < 25 and
                all(config.enabled(name) for name in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS', 'NOTIFICATIONS'))):
            from .notifications import tick as notify
            result['notifications'] = notify(store, limit=20)
        from .operations import snapshot
        result['operations'] = snapshot(store)
        LOG.info('trend.tick completed=%s failed=%s blocked=%s operations=%s',
            result.get('completed', 0), result.get('failed', 0), result.get('blocked', 0),
            result['operations']['reason_codes'])
        return result
    except Exception:
        LOG.error('trend.maintenance_unavailable')
        return {'status': 'unavailable', 'dispatched': 0}
