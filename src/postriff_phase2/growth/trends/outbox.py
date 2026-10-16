"""Transactional outbox. Consumers perform existing domain effects; this module never publishes."""
import uuid as uuidlib
from .contracts import instant, iso, uuid
from .store import TrendStorageError, bounded_json, row

# Bounded effect summary returned by consume(); never content, IDs or free text.
EFFECT_STATES = frozenset(('complete', 'ignored', 'suppressed', 'replayed', 'unknown'))
EFFECT_REASONS = frozenset(('different_event_type', 'no_current_sources', 'no_eligible_posts',
                            'no_eligible_membership', 'event_node_invalid'))
# Explicit gap reasons kept as marker counts (gap_<reason>) so a re-anchored or
# clamped stream is visible in the durable event without storing raw markers.
GAP_REASONS = frozenset(('cursor_too_old', 'cursor_outdated', 'cursor_future', 'cursor_clamped'))
MARKER_COUNT_KEYS = frozenset(('account', 'sync', 'gap', 'identity')) | frozenset('gap_' + r for r in GAP_REASONS)


def effect_summary(value):
    state = value.get('state') if isinstance(value, dict) else None
    reason = value.get('reason') if isinstance(value, dict) else None
    return {'state': state if isinstance(state, str) and state in EFFECT_STATES else 'unknown',
            'reason': reason if isinstance(reason, str) and reason in EFFECT_REASONS else None}


def ingestion_payload(payload):
    """Persist references and coverage controls, never raw account/sync markers."""
    result = {}
    for name in ('provider_id','coverage_epoch'):
        if name in payload:
            if not isinstance(payload[name],str) or not 1<=len(payload[name])<=160:
                raise TrendStorageError('invalid_ingestion_metadata')
            result[name] = payload[name]
    if 'decision_cutoff' in payload:
        result['decision_cutoff'] = iso(instant(payload['decision_cutoff']))
    if 'observation_ids' in payload:
        ids = payload['observation_ids']
        if not isinstance(ids,list) or len(ids)>1000:
            raise TrendStorageError('invalid_ingestion_references')
        result['observation_ids'] = [uuid(item) for item in ids]
    if 'pending_observation_indices' in payload:
        pending = payload['pending_observation_indices']
        ids = result.get('observation_ids')
        if (ids is None or not isinstance(pending,list) or len(pending)>len(ids)
            or any(type(i) is not int or not 0<=i<len(ids) for i in pending)
            or len(set(pending))!=len(pending)):
            raise TrendStorageError('invalid_ingestion_references')
        result['pending_observation_indices'] = list(pending)
    if 'completeness' in payload:
        if payload['completeness'] not in ('complete','complete_within_scope','partial','truncated','gap','unknown'):
            raise TrendStorageError('invalid_ingestion_completeness')
        result['completeness'] = payload['completeness']
    if payload.get('coverage_interval'):
        result['coverage_interval'] = {k:iso(instant(payload['coverage_interval'][k])) for k in ('start','end')}
    counts = {}
    for marker in payload.get('markers',[]):
        kind = marker.get('kind') if isinstance(marker,dict) else None
        if kind in ('account','sync','gap','identity'):
            counts[kind] = counts.get(kind,0)+1
            reason = marker.get('reason_code') if kind=='gap' else None
            if isinstance(reason,str) and reason in GAP_REASONS:
                counts['gap_'+reason] = counts.get('gap_'+reason,0)+1
    for kind,count in payload.get('marker_counts',{}).items():
        if isinstance(kind,str) and kind in MARKER_COUNT_KEYS and type(count) is int and 0<=count<=10000:
            counts[kind] = counts.get(kind,0)+count
    if counts:
        result['marker_counts'] = counts
    return result


class TrendOutbox:
    def __init__(self, store):
        self.store = store

    def enqueue(self, scope_key, event_key, event_type, payload, *, node_id=None, cursor=None):
        if event_type=='trend.ingested':
            payload = ingestion_payload(payload)
        elif event_type=='trend.quarantined':
            # Only this strict content-free operational receipt may survive
            # without an evidence node. Lazy import avoids the recovery cycle.
            from .quarantine import sanitize_receipt
            payload = sanitize_receipt(payload)
        elif payload and node_id is None:
            raise TrendStorageError('content_event_dependency_required')
        with self.store.transaction(cursor) as cur:
            cur.execute('INSERT INTO public.pr_trend_outbox(scope_key,event_id,event_key,event_type,payload,node_id) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_key,event_key) DO NOTHING RETURNING *',
                (scope_key,str(uuidlib.uuid4()),event_key,event_type,bounded_json(payload),node_id))
            result = row(cur)
            if result:
                return result
            cur.execute('SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s AND event_key=%s',(scope_key,event_key))
            result = row(cur)
            if (result['event_type'],result['payload'],result['node_id'])!=(event_type,payload,node_id):
                raise TrendStorageError('outbox_idempotency_conflict')
            return result

    def claim(self, consumer, worker_id, *, lease_seconds=60, cursor=None):
        if type(lease_seconds) is not int or not 1<=lease_seconds<=300:
            raise TrendStorageError('invalid_lease')
        with self.store.transaction(cursor) as cur:
            cur.execute("""SELECT e.* FROM public.pr_trend_outbox e WHERE NOT EXISTS(
                SELECT 1 FROM public.pr_trend_outbox_consumers c WHERE c.consumer=%s AND(c.scope_key,c.event_id)=(e.scope_key,e.event_id)
                AND(c.state IN ('done','suppressed') OR c.lease_until>clock_timestamp()))
                ORDER BY e.created_at,e.event_id LIMIT 1 FOR UPDATE OF e SKIP LOCKED""",(consumer,))
            event = row(cur)
            if not event:
                return None
            valid = True
            if event['node_id']:
                cur.execute('SELECT postriff_private.trend_node_valid(%s,%s) AS valid',(event['scope_key'],event['node_id']))
                valid = row(cur)['valid']
            cur.execute("""INSERT INTO public.pr_trend_outbox_consumers(consumer,scope_key,event_id,state,lease_owner,lease_until)
                VALUES(%s,%s,%s,%s,%s,clock_timestamp()+%s*interval '1 second')
                ON CONFLICT(consumer,scope_key,event_id) DO UPDATE SET state=excluded.state,lease_owner=excluded.lease_owner,
                lease_until=excluded.lease_until,lease_generation=pr_trend_outbox_consumers.lease_generation+1
                WHERE pr_trend_outbox_consumers.state='leased'
                AND pr_trend_outbox_consumers.lease_until<=clock_timestamp() RETURNING *""",
                (consumer,event['scope_key'],event['event_id'],'leased' if valid else 'suppressed',worker_id,lease_seconds))
            claim = row(cur)
            return {**event,**claim} if valid and claim else None

    def consume(self, claim, effect, *, cursor=None):
        """effect(cursor,event) must be a transactional local domain mutation, never external HTTP.

        External delivery uses the existing notification worker and provider idempotency semantics.
        Returns the consumer state plus a bounded ``effect`` {state, reason} summary
        (e.g. suppressed/no_current_sources) so callers can count and log outcomes.
        """
        with self.store.transaction(cursor) as cur:
            cur.execute("""SELECT * FROM public.pr_trend_outbox_consumers WHERE consumer=%s AND scope_key=%s AND event_id=%s FOR UPDATE""",
                (claim['consumer'],claim['scope_key'],claim['event_id']))
            current = row(cur)
            if current and current['state']=='done':
                return {'state':'done','replayed':True,'effect':{'state':'replayed','reason':None}}
            cur.execute("""SELECT 1 FROM public.pr_trend_outbox_consumers WHERE consumer=%s AND scope_key=%s AND event_id=%s
                AND state='leased' AND lease_owner=%s AND lease_generation=%s AND lease_until>clock_timestamp()""",
                (claim['consumer'],claim['scope_key'],claim['event_id'],claim['lease_owner'],claim['lease_generation']))
            if not cur.fetchone():
                raise TrendStorageError('stale_outbox_fence')
            cur.execute('SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s AND event_id=%s',(claim['scope_key'],claim['event_id']))
            event = row(cur); valid = True
            if event['node_id']:
                cur.execute('SELECT postriff_private.trend_node_valid(%s,%s) AS valid',(event['scope_key'],event['node_id']))
                valid = row(cur)['valid']
            summary = (effect_summary(effect(cur,event)) if valid
                       else {'state':'suppressed','reason':'event_node_invalid'})
            state = 'done' if valid else 'suppressed'
            cur.execute('''UPDATE public.pr_trend_outbox_consumers SET state=%s,completed_at=clock_timestamp(),lease_until=NULL
                WHERE consumer=%s AND scope_key=%s AND event_id=%s AND state='leased'
                AND lease_owner=%s AND lease_generation=%s AND lease_until>clock_timestamp()''',
                (state,claim['consumer'],claim['scope_key'],claim['event_id'],claim['lease_owner'],claim['lease_generation']))
            if cur.rowcount!=1:
                raise TrendStorageError('stale_outbox_fence')
            return {'state':state,'replayed':False,'effect':summary}
