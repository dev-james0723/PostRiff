"""Opt-in, bounded discovery scheduling using reviewed immutable policy manifests.

No provider is invoked here. ``manifest.schedule`` explicitly supplies enabled,
start_at, interval_seconds, max_samples (lifetime slots, not catch-up attempts),
max_items, seconds, budget_keys and reservation_microusd. Missed slots are not
replayed. Changing this configuration requires a new reviewed policy version.
Claim/dispatch must still recheck admission and reserve all budget dimensions.
"""
from dataclasses import asdict, fields
from datetime import timedelta

from . import config
from .contracts import ContractError, canonical, digest, instant, iso
from .jobs import TrendJobs, micro_usd
from .policy import SourcePolicy, admit
from .store import row, rows, utcnow


def integer(value, minimum, maximum, code='invalid_schedule'):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(code)
    return value


def schedule_controls(manifest):
    value = manifest.get('schedule')
    if not isinstance(value, dict) or value.get('enabled') is not True:
        raise ContractError('schedule_not_enabled')
    required = {'enabled', 'start_at', 'interval_seconds', 'max_samples', 'max_items',
                'seconds', 'budget_keys', 'reservation_microusd'}
    if set(value) != required:
        raise ContractError('invalid_schedule')
    result = dict(value)
    result['start_at'] = iso(instant(value['start_at']))
    integer(value['interval_seconds'], 1, 31 * 86400)
    integer(value['max_samples'], 1, 10000)
    integer(value['max_items'], 1, 1000)
    integer(value['seconds'], 1, 60)
    keys = value['budget_keys']
    if (not isinstance(keys, list) or not 2 <= len(keys) <= 4
            or any(not isinstance(k, str) or not 1 <= len(k) <= 160 for k in keys)
            or len(set(keys)) != len(keys)):
        raise ContractError('schedule_budget_required')
    micro_usd(value['reservation_microusd'])
    result['budget_keys'] = sorted(keys)
    return result


class FrontierPlanner:
    def __init__(self, store, registry, *, values=None, clock=utcnow):
        self.store, self.registry = store, registry
        self.values, self.clock = values, clock
        self.jobs = TrendJobs(store)

    def _scope_allowed(self, cur, scope_key, at):
        if scope_key.startswith('workspace:'):
            return config.workspace_allowed(scope_key[10:], self.values)
        cur.execute("""SELECT workspace_id FROM public.pr_trend_entitlements
            WHERE scope_key=%s AND revoked_at IS NULL AND expires_at>%s
            AND 'retrieve'=ANY(operations) ORDER BY workspace_id LIMIT 1001 FOR SHARE""", (scope_key, at))
        return any(config.workspace_allowed(r['workspace_id'], self.values) for r in rows(cur))

    def admitted(self, cur, scope_key, provider_id, version, *, at):
        """Return current controls after durable policy, capability and budget checks.

        Exposed for bounded recovery jobs; no caller-provided policy or costs.
        """
        if not self._scope_allowed(cur, scope_key, at):
            raise ContractError('dispatch_disabled')
        stored = self.store._policy(cur, scope_key, provider_id, version, at=at)
        manifest = stored['manifest']
        keys = {f.name for f in fields(SourcePolicy)}
        current = SourcePolicy(**{k: v for k, v in manifest.items() if k in keys})
        controls = schedule_controls(manifest)
        if instant(controls['start_at']) < instant(current.effective_at):
            raise ContractError('schedule_before_policy')
        cap, policy, _adapter = self.registry.resolve(provider_id, current.operation, scope_key, version, at=at)
        if (canonical(asdict(current)) != canonical(asdict(policy))
                or stored['provider_contract_version'] != cap.version):
            raise ContractError('planner_contract_mismatch')
        if controls['seconds'] > cap.timeout_seconds:
            raise ContractError('schedule_timeout_exceeded')
        admit(cap, current, at=at, requested_scope=scope_key,
              enabled=config.dispatch_allowed(provider_id, current.operation, self.values),
              item_limit=controls['max_items'], byte_limit=cap.max_response_bytes,
              reservation_microusd=controls['reservation_microusd'], entitlement_current=True,
              billable=cap.billable_unit != 'unmetered_live_bytes_bounded')
        cur.execute('SELECT * FROM public.pr_trend_source_health WHERE scope_key=%s AND provider_id=%s FOR SHARE',
                    (scope_key, provider_id))
        health = row(cur)
        if health and (health['status'] == 'revoked' or
                       health.get('next_allowed_at') and instant(health['next_allowed_at']) > instant(at)):
            raise ContractError('source_paused')
        cur.execute('SELECT * FROM public.pr_trend_budget_limits WHERE budget_key=ANY(%s) ORDER BY budget_key FOR SHARE',
                    (controls['budget_keys'],))
        budgets = rows(cur)
        required = {'system', 'provider'} | ({'workspace'} if scope_key.startswith('workspace:') else set())
        if len(budgets) != len(controls['budget_keys']) or not required <= {b['dimension'] for b in budgets}:
            raise ContractError('schedule_budget_required')
        for budget in budgets:
            if (not instant(budget['period_start']) <= instant(at) < instant(budget['period_end'])
                    or sum(budget[k] for k in ('reserved_micro_usd', 'settled_micro_usd', 'unknown_micro_usd'))
                    + controls['reservation_microusd'] > budget['cap_micro_usd']):
                raise ContractError('schedule_budget_exhausted')
        return current, cap, controls, manifest

    @staticmethod
    def payload(policy, controls, epoch):
        return {'operation': policy.operation, 'max_items': controls['max_items'],
                'seconds': controls['seconds'], 'budget_keys': controls['budget_keys'],
                'reservation_microusd': controls['reservation_microusd'], 'coverage_epoch': epoch}

    def plan_one(self, scope_key, provider_id, version, *, cursor=None):
        at = self.clock()
        with self.store.transaction(cursor) as cur:
            policy, cap, controls, _ = self.admitted(cur, scope_key, provider_id, version, at=at)
            elapsed = (instant(at) - instant(controls['start_at'])).total_seconds()
            slot = int(elapsed // controls['interval_seconds'])
            if slot < 0 or slot >= controls['max_samples']:
                return None
            identity = digest([scope_key, provider_id, version, controls, slot])
            payload = self.payload(policy, controls, 'scheduled:' + identity)
            # Unique scoped key is the concurrency guard. Repeated ticks return
            # the existing receipt, including terminal receipts; never redispatch.
            return self.jobs.enqueue(scope_key, 'trend.ingest', payload,
                provider_id=provider_id, source_policy_version=version,
                idempotency_key='frontier:' + identity, max_attempts=cap.max_attempts,
                due_at=iso(instant(controls['start_at']) + timedelta(seconds=slot * controls['interval_seconds'])),
                cursor=cur)

    def tick(self, *, limit=20):
        integer(limit, 1, 100, 'planner_bounds')
        if not all(config.enabled(n, self.values) for n in ('INTELLIGENCE', 'RADAR', 'PROVIDER_OPERATIONS')):
            return {'status': 'disabled', 'jobs': [], 'blocked': 0}
        at = self.clock()
        with self.store.transaction() as cur:
            cur.execute("""SELECT scope_key,provider_id,version FROM public.pr_trend_source_policies
                WHERE readiness='ready' AND revoked_at IS NULL AND valid_from<=%s AND expires_at>%s
                AND manifest->'schedule'->'enabled'='true'::jsonb
                ORDER BY scope_key,provider_id,version LIMIT %s""", (at, at, limit))
            candidates = rows(cur)
        result = {'status': 'ok', 'jobs': [], 'blocked': 0}
        for item in candidates:
            try:
                job = self.plan_one(item['scope_key'], item['provider_id'], item['version'])
                if job:
                    result['jobs'].append(job['job_id'])
            except (ContractError, TypeError, KeyError):
                # No manifest, provider text or exception detail is logged.
                result['blocked'] += 1
        return result
