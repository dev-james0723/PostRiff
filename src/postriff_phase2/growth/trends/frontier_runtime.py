"""Durable, flag-independent frontier privacy cleanup; no permission creation.

Worker order: maintenance(store), then analytics_runtime.maintain(store), which
owns the canonical physical purge. This adapter commits cleanup and its cursor
atomically; it neither calls providers nor changes any policy/entitlement.
"""
import json
import re

from .contracts import ContractError, scope
from .frontier import DiscoveryFrontier, EVENT
from .planner import integer
from .store import row, trust_lock

SCOPE = 'shared:rafii-frontier-maintenance'
PROVIDER = 'rafii.local.frontier'
PARTITION = 'privacy-retention-v1'
LOCK = 'trend-frontier-maintenance-v1'


def _after(value):
    if not isinstance(value, dict) or set(value)-{'after'}:
        raise ContractError('frontier_maintenance_cursor_invalid')
    after = value.get('after')
    if after is None:
        return None
    if not isinstance(after, str) or len(after)>512:
        raise ContractError('frontier_maintenance_cursor_invalid')
    saved_scope, separator, key = after.partition('|')
    if not separator or not re.fullmatch(r'frontier-(?:allocation|decision|request):[a-f0-9]{64}',key):
        raise ContractError('frontier_maintenance_cursor_invalid')
    scope(saved_scope)
    return after


def maintenance(store, *, limit=25):
    """Bounded global privacy page, then durable progress, in one transaction.

    No frontier events means no maintenance namespace/cursor writes. Restore
    blocks both erasure and cursor advancement. Operation flags and temporary
    provider health pauses cannot disable privacy cleanup. A busy worker leaves
    progress to the transaction holding the lock; exceptions roll everything back.
    """
    integer(limit,1,100,'frontier_maintenance_bound')
    with store.transaction() as cur:
        cur.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS locked',(LOCK,))
        locked = row(cur)
        if not locked or locked['locked'] is not True:
            return {'status':'busy','cancelled':0}
        # Restore/deletion takes this same trust lock exclusively. Acquire it
        # before the guard row lock to preserve that global lock order.
        trust_lock(cur)
        cur.execute('SELECT reads_ready FROM public.pr_trend_runtime_guard WHERE singleton FOR SHARE')
        guard = row(cur)
        if not guard or guard['reads_ready'] is not True:
            return {'status':'restore_deferred','cancelled':0}
        cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_trend_outbox WHERE event_type=%s AND payload<>'{}'::jsonb) AS present",(EVENT,))
        if not row(cur)['present']:
            return {'status':'idle','cancelled':0}
        store.ensure_scope(SCOPE,cursor=cur)
        cur.execute('INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                    (SCOPE,PROVIDER,PARTITION))
        cur.execute('SELECT cursor_value,generation FROM public.pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE',
                    (SCOPE,PROVIDER,PARTITION))
        saved = row(cur)
        after = _after(saved['cursor_value'])
        result = DiscoveryFrontier(store,None,values={}).maintenance(limit=limit,after=after,cursor=cur)
        if result.get('status') == 'restore_deferred':
            return result
        if result.get('status') != 'ok' or type(result.get('cancelled')) is not int or result['cancelled']<0:
            raise ContractError('frontier_maintenance_result_invalid')
        next_key = _after({'after':result.get('next_key')})
        cur.execute('''UPDATE public.pr_trend_provider_cursors SET cursor_value=%s::jsonb,
            generation=generation+1,updated_at=clock_timestamp()
            WHERE scope_key=%s AND provider_id=%s AND partition_key=%s''',
            (json.dumps({'after':next_key}),SCOPE,PROVIDER,PARTITION))
        return {**result,'cursor_generation':saved['generation']+1}
