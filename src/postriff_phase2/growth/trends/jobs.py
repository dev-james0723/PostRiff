"""Dedicated durable jobs and spend admission. External work happens between start and completion.

Unknown provider outcomes retain exposure. No external transport or publisher is implemented here.
"""
from __future__ import annotations

from datetime import timedelta
from dataclasses import replace
import uuid as uuidlib
from .contracts import digest, instant, iso, scope, uuid
from .store import TrendStorageError, bounded_json, row, rows, utcnow, trust_lock


def micro_usd(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise TrendStorageError('invalid_micro_usd')
    return value


def partition_key(*, instance_id, protocol_version, filter_digest):
    if not all(isinstance(v,str) and v for v in (instance_id,protocol_version,filter_digest)):
        raise TrendStorageError('cursor_partition_required')
    return digest({'instance_id':instance_id,'protocol_version':protocol_version,'filter_digest':filter_digest})


def validate_job_controls(value):
    """Job payloads hold bounded controls/opaque references, not a second source store."""
    forbidden = {'text','body','caption','excerpt','content','author','author_key','did','native_id','source_identity',
                 'observations','source_revisions','normalized_inputs','markers','raw_response'}
    if isinstance(value,dict):
        if any(k.lower() in forbidden for k in value):
            raise TrendStorageError('job_payload_requires_observation_reference')
        for child in value.values():
            validate_job_controls(child)
    elif isinstance(value,(list,tuple)):
        for child in value:
            validate_job_controls(child)


class TrendJobs:
    def __init__(self, store):
        self.store = store

    def configure_budget(self, budget_key, dimension, cap_micro_usd, period_start, period_end, *, cursor=None):
        micro_usd(cap_micro_usd); instant(period_start); instant(period_end)
        with self.store.transaction(cursor) as cur:
            cur.execute("""INSERT INTO public.pr_trend_budget_limits(budget_key,dimension,cap_micro_usd,period_start,period_end)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING budget_key""",(budget_key,dimension,cap_micro_usd,period_start,period_end))
            if not row(cur):
                cur.execute('SELECT dimension,cap_micro_usd,period_start,period_end FROM public.pr_trend_budget_limits WHERE budget_key=%s',(budget_key,))
                if row(cur)!={'dimension':dimension,'cap_micro_usd':cap_micro_usd,'period_start':iso(instant(period_start)),'period_end':iso(instant(period_end))}:
                    raise TrendStorageError('budget_period_conflict')

    def reserve(self, scope_key, logical_call_id, physical_attempt_id, amount_micro_usd, budget_keys, *, cursor=None):
        micro_usd(amount_micro_usd); scope(scope_key); uuid(physical_attempt_id)
        if len(set(budget_keys))!=len(budget_keys) or not budget_keys:
            raise TrendStorageError('budget_dimensions_required')
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(scope_key+'|attempt|'+physical_attempt_id,))
            cur.execute('SELECT * FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND physical_attempt_id=%s',(scope_key,physical_attempt_id))
            existing = row(cur)
            if existing:
                cur.execute('SELECT budget_key FROM public.pr_trend_reservation_dimensions WHERE scope_key=%s AND reservation_id=%s ORDER BY budget_key',(scope_key,existing['reservation_id']))
                if existing['amount_micro_usd']!=amount_micro_usd or existing['logical_call_id']!=logical_call_id or [r['budget_key'] for r in rows(cur)]!=sorted(budget_keys):
                    raise TrendStorageError('reservation_identity_conflict')
                return existing
            cur.execute('SELECT * FROM public.pr_trend_budget_limits WHERE budget_key=ANY(%s) ORDER BY budget_key FOR UPDATE',(sorted(budget_keys),))
            budgets = rows(cur); now = instant(utcnow())
            if len(budgets)!=len(budget_keys) or not {'system','provider'}<= {b['dimension'] for b in budgets}:
                raise TrendStorageError('budget_dimensions_required')
            if scope_key.startswith('workspace:') and 'workspace' not in {b['dimension'] for b in budgets}:
                raise TrendStorageError('workspace_budget_required')
            for b in budgets:
                if not instant(b['period_start'])<=now<instant(b['period_end']):
                    raise TrendStorageError('budget_period_inactive')
                if b['settled_micro_usd']+b['reserved_micro_usd']+b['unknown_micro_usd']+amount_micro_usd>b['cap_micro_usd']:
                    raise TrendStorageError('budget_exhausted')
            rid = str(uuidlib.uuid4())
            cur.execute('INSERT INTO public.pr_trend_budget_reservations(scope_key,reservation_id,logical_call_id,physical_attempt_id,amount_micro_usd) VALUES(%s,%s,%s,%s,%s) RETURNING *',(scope_key,rid,logical_call_id,physical_attempt_id,amount_micro_usd))
            result = row(cur)
            for b in budgets:
                cur.execute('UPDATE public.pr_trend_budget_limits SET reserved_micro_usd=reserved_micro_usd+%s WHERE budget_key=%s',(amount_micro_usd,b['budget_key']))
                cur.execute('INSERT INTO public.pr_trend_reservation_dimensions(scope_key,reservation_id,budget_key) VALUES(%s,%s,%s)',(scope_key,rid,b['budget_key']))
            return result

    def settle(self, scope_key, reservation_id, *, actual_micro_usd=None, usage_event_id=None, proven_unbilled=False, cursor=None):
        if actual_micro_usd is not None:
            micro_usd(actual_micro_usd)
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT * FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s FOR UPDATE',(scope_key,reservation_id))
            r = row(cur)
            if not r:
                raise TrendStorageError('reservation_unavailable')
            desired = 'released' if proven_unbilled else 'unknown' if actual_micro_usd is None else 'settled'
            if proven_unbilled and actual_micro_usd not in (None,0):
                raise TrendStorageError('unbilled_cost_conflict')
            if r['state'] in ('released','settled'):
                if desired!=r['state'] or (desired=='settled' and r['actual_micro_usd']!=actual_micro_usd):
                    raise TrendStorageError('settlement_conflict')
                return r
            if r['state']=='unknown' and desired=='unknown':
                return r
            cur.execute('SELECT budget_key FROM public.pr_trend_reservation_dimensions WHERE scope_key=%s AND reservation_id=%s ORDER BY budget_key',(scope_key,reservation_id))
            keys = [x['budget_key'] for x in rows(cur)]
            cur.execute('SELECT budget_key FROM public.pr_trend_budget_limits WHERE budget_key=ANY(%s) ORDER BY budget_key FOR UPDATE',(keys,)); cur.fetchall()
            reserved_delta = 0 if r['state']=='unknown' else -r['amount_micro_usd']
            unknown_delta = (r['amount_micro_usd'] if desired=='unknown' else 0)-(r['amount_micro_usd'] if r['state']=='unknown' else 0)
            for key in keys:
                cur.execute('UPDATE public.pr_trend_budget_limits SET reserved_micro_usd=reserved_micro_usd+%s,settled_micro_usd=settled_micro_usd+%s,unknown_micro_usd=unknown_micro_usd+%s WHERE budget_key=%s',
                    (reserved_delta,actual_micro_usd if desired=='settled' else 0,unknown_delta,key))
            cur.execute('UPDATE public.pr_trend_budget_reservations SET state=%s,actual_micro_usd=%s,usage_event_id=%s WHERE scope_key=%s AND reservation_id=%s RETURNING *',(desired,actual_micro_usd,usage_event_id,scope_key,reservation_id))
            return row(cur)

    def enqueue(self, scope_key, kind, payload, *, idempotency_key, provider_id=None, source_policy_version=None, due_at=None, priority=0, max_attempts=3, cursor=None):
        scope(scope_key)
        validate_job_controls(payload)
        if not kind.startswith('trend.') or not idempotency_key or len(idempotency_key)>256:
            raise TrendStorageError('invalid_job_identity')
        with self.store.transaction(cursor) as cur:
            job_id = str(uuidlib.uuid4())
            cur.execute("""INSERT INTO public.pr_trend_jobs(scope_key,job_id,kind,payload,idempotency_key,provider_id,source_policy_version,due_at,priority,max_attempts)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_key,idempotency_key) DO NOTHING RETURNING *""",
                (scope_key,job_id,kind,bounded_json(payload),idempotency_key,provider_id,source_policy_version,due_at or utcnow(),priority,max_attempts))
            result = row(cur)
            if result:
                return result
            cur.execute('SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND idempotency_key=%s',(scope_key,idempotency_key))
            result = row(cur)
            if (result['kind'],result['provider_id'],result['source_policy_version'])!=(kind,provider_id,source_policy_version):
                raise TrendStorageError('job_idempotency_conflict')
            # A terminal key is sealed permanently. Content has been erased;
            # replay returns its execution receipt and can never dispatch again.
            if result['state'] not in ('succeeded','failed_terminal','cancelled','outcome_unknown') and result['payload']!=payload:
                raise TrendStorageError('job_idempotency_conflict')
            return result

    def _abandon_reservation(self, scope_key, reservation_id, *, proven_unbilled, cursor):
        # Usage may already have committed while result attachment failed.
        # Cancellation/lease recovery must not replace that authoritative cost.
        cursor.execute('SELECT * FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s FOR UPDATE',
                       (scope_key,reservation_id))
        existing = row(cursor)
        if existing and existing['state'] in ('settled','released'):
            return existing
        return self.settle(scope_key,reservation_id,proven_unbilled=proven_unbilled,cursor=cursor)

    def recover_expired(self, *, limit=100, cursor=None):
        with self.store.transaction(cursor) as cur:
            cur.execute("SELECT * FROM public.pr_trend_jobs WHERE state IN ('leased','running') AND lease_until<=clock_timestamp() ORDER BY lease_until LIMIT %s FOR UPDATE SKIP LOCKED",(limit,))
            expired = rows(cur)
            for job in expired:
                dispatched = job['state']=='running'
                if job['reservation_id']:
                    self._abandon_reservation(job['scope_key'],job['reservation_id'],proven_unbilled=not dispatched,cursor=cur)
                state = 'outcome_unknown' if dispatched else 'failed_terminal' if job['attempts']>=job['max_attempts'] else 'queued'
                cur.execute("UPDATE public.pr_trend_jobs SET state=%s,payload=CASE WHEN %s IN ('outcome_unknown','failed_terminal') THEN '{}'::jsonb ELSE payload END,lease_owner=NULL,lease_until=NULL,error_code=%s WHERE scope_key=%s AND job_id=%s",
                    (state,state,'expired_dispatch_unknown' if dispatched else 'expired_before_dispatch',job['scope_key'],job['job_id']))
            return len(expired)

    def claim(self, worker_id, *, scope_key=None, kind=None, job_id=None, lease_seconds=60, budget_keys=None, amount_micro_usd=0, provider_concurrency=1, cursor=None):
        micro_usd(amount_micro_usd)
        if type(lease_seconds) is not int or not 1<=lease_seconds<=300 or not worker_id:
            raise TrendStorageError('invalid_lease')
        with self.store.transaction(cursor) as cur:
            self.recover_expired(cursor=cur)
            cur.execute("""SELECT j.* FROM public.pr_trend_jobs j JOIN public.pr_trend_scopes s USING(scope_key)
                WHERE s.enabled AND j.state IN ('queued','retry_wait') AND j.due_at<=clock_timestamp()
                AND NOT j.cancellation_requested AND j.attempts<j.max_attempts
                AND (%s::text IS NULL OR j.scope_key=%s) AND (%s::text IS NULL OR j.kind=%s)
                AND (%s::uuid IS NULL OR j.job_id=%s)
                AND NOT EXISTS(SELECT 1 FROM public.pr_trend_source_health h WHERE h.scope_key=j.scope_key AND h.provider_id=j.provider_id
                AND (h.status='revoked' OR h.next_allowed_at>clock_timestamp()))
                ORDER BY j.priority DESC,j.due_at,j.job_id LIMIT 1 FOR UPDATE OF j SKIP LOCKED""",(scope_key,scope_key,kind,kind,job_id,job_id))
            job = row(cur)
            if not job:
                return None
            if job['provider_id']:
                cur.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS locked',('trend-provider|'+job['scope_key']+'|'+job['provider_id'],))
                if not row(cur)['locked']:
                    return None
                cur.execute("SELECT count(*) AS n FROM public.pr_trend_jobs WHERE scope_key=%s AND provider_id=%s AND state IN ('leased','running') AND lease_until>clock_timestamp()",(job['scope_key'],job['provider_id']))
                if row(cur)['n']>=provider_concurrency:
                    return None
                self.store._policy(cur,job['scope_key'],job['provider_id'],job['source_policy_version'])
            fence = job['lease_generation']+1; reservation = None
            if amount_micro_usd or budget_keys:
                reservation = self.reserve(job['scope_key'],job['idempotency_key'],str(uuidlib.uuid5(uuidlib.UUID(job['job_id']),str(fence))),amount_micro_usd,budget_keys or [],cursor=cur)
            cur.execute("""UPDATE public.pr_trend_jobs SET state='leased',lease_owner=%s,lease_until=clock_timestamp()+%s*interval '1 second',
                lease_generation=%s,attempts=attempts+1,reservation_id=%s WHERE scope_key=%s AND job_id=%s RETURNING *""",
                (worker_id,lease_seconds,fence,reservation['reservation_id'] if reservation else None,job['scope_key'],job['job_id']))
            return row(cur)

    def _fence(self, cur, claim, *, revalidate_policy=True):
        cur.execute("""SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s AND lease_owner=%s
            AND lease_generation=%s AND lease_until>clock_timestamp() AND state IN ('leased','running')
            AND NOT cancellation_requested FOR UPDATE""",(claim['scope_key'],claim['job_id'],claim['lease_owner'],claim['lease_generation']))
        job = row(cur)
        if not job:
            raise TrendStorageError('stale_job_fence')
        if job['provider_id'] and revalidate_policy:
            self.store._policy(cur,job['scope_key'],job['provider_id'],job['source_policy_version'])
        return job

    def start(self, claim, *, cursor=None):
        with self.store.transaction(cursor) as cur:
            job = self._fence(cur,claim)
            if job['state']!='leased':
                raise TrendStorageError('dispatch_already_started')
            if job['reservation_id']:
                cur.execute("UPDATE public.pr_trend_budget_reservations SET state='dispatched' WHERE scope_key=%s AND reservation_id=%s AND state='reserved' RETURNING reservation_id",(job['scope_key'],job['reservation_id']))
                if not row(cur):
                    raise TrendStorageError('reservation_not_dispatchable')
            cur.execute("UPDATE public.pr_trend_jobs SET state='running' WHERE scope_key=%s AND job_id=%s RETURNING *",(job['scope_key'],job['job_id']))
            return row(cur)

    def get_cursor(self, scope_key, provider_id, partition_key, *, cursor=None):
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT * FROM public.pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',(scope_key,provider_id,partition_key))
            return row(cur) or {'scope_key':scope_key,'provider_id':provider_id,'partition_key':partition_key,'generation':0,'cursor_value':{},'coverage_state':'partial'}

    def finish_local(self, claim, *, cursor=None):
        with self.store.transaction(cursor) as cur:
            job = self._fence(cur,claim)
            if job['reservation_id'] or job['provider_id']:
                raise TrendStorageError('local_job_has_external_reservation')
            cur.execute("UPDATE public.pr_trend_jobs SET state='succeeded',payload='{}',lease_until=NULL,lease_owner=NULL WHERE scope_key=%s AND job_id=%s RETURNING *",(job['scope_key'],job['job_id']))
            return row(cur)

    def account_attempt(self, scope_key, reservation_id, usage_event, *, cursor=None):
        """Record the existing UsageSink once, even when its output is no longer usable.

        Deliberately independent of job/source fences. Commit this accounting
        transaction before attempting the fenced result-attachment transaction.
        """
        from ..usage import UsageEvent, PostgresUsageSink
        if not isinstance(usage_event,UsageEvent):
            raise TrendStorageError('usage_event_required')
        expected_workspace = scope_key[10:] if scope_key.startswith('workspace:') else None
        if usage_event.workspace_id!=expected_workspace:
            raise TrendStorageError('usage_scope_mismatch')
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT * FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s FOR UPDATE',(scope_key,reservation_id))
            reservation = row(cur)
            if not reservation or reservation['state'] not in ('dispatched','unknown','settled'):
                raise TrendStorageError('attempt_not_dispatched')
            if reservation['usage_event_id']:
                return {'usage_event_id':reservation['usage_event_id'],'actual_micro_usd':reservation['actual_micro_usd'],'replayed':True}
            subject = digest({'scope_key':scope_key,'reservation_id':str(reservation_id)})
            event = replace(usage_event,subject=subject)
            PostgresUsageSink(cur).record(event)
            cur.execute('SELECT id FROM public.pr_model_usage_events WHERE subject=%s AND task=%s ORDER BY created_at DESC,id DESC LIMIT 1',(subject,event.task))
            usage_id = row(cur)['id']
            amount = event.cost_usd_micro()
            self.settle(scope_key,reservation_id,actual_micro_usd=amount,usage_event_id=usage_id,cursor=cur)
            # An already unknown settlement is idempotent and may return early.
            cur.execute('UPDATE public.pr_trend_budget_reservations SET usage_event_id=%s WHERE scope_key=%s AND reservation_id=%s',(usage_id,scope_key,reservation_id))
            return {'usage_event_id':usage_id,'actual_micro_usd':amount,'replayed':False}

    def finish_external(self, claim, *, actual_micro_usd, usage_event_id, cursor=None):
        """Complete a model/external job without any ingestion/cursor side effect."""
        with self.store.transaction(cursor) as cur:
            job = self._fence(cur,claim)
            if job['state']!='running' or not job['reservation_id']:
                raise TrendStorageError('external_reservation_required')
            cur.execute('SELECT state,usage_event_id FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s FOR UPDATE',(job['scope_key'],job['reservation_id']))
            reservation = row(cur)
            if not reservation or reservation['state'] not in ('dispatched','unknown','settled'):
                raise TrendStorageError('attempt_not_dispatched')
            if not usage_event_id or reservation['usage_event_id']!=str(usage_event_id):
                raise TrendStorageError('durable_usage_required')
            self.settle(job['scope_key'],job['reservation_id'],actual_micro_usd=actual_micro_usd,usage_event_id=usage_event_id,cursor=cur)
            self._fence(cur,claim)
            cur.execute("UPDATE public.pr_trend_jobs SET state='succeeded',payload='{}',lease_until=NULL,lease_owner=NULL WHERE scope_key=%s AND job_id=%s RETURNING *",(job['scope_key'],job['job_id']))
            return row(cur)

    def complete_batch(self, claim, *, partition_key, expected_generation, batch_key, observations, cursor_value,
                       terminal_page=False, coverage_state='partial', outbox_events=(), actual_micro_usd=None, usage_event_id=None, cursor=None):
        if len(observations)>1000 or type(expected_generation) is not int or expected_generation<0:
            raise TrendStorageError('invalid_batch_bounds')
        with self.store.transaction(cursor) as cur:
            # Acquire the write side first for a deletion page, before policy
            # validation takes a shared trust lock; competing upgrades can deadlock.
            if any(o.get('operation')=='delete' for o in observations):
                trust_lock(cur,exclusive=True)
            job = self._fence(cur,claim)
            if not job['provider_id']:
                raise TrendStorageError('batch_provider_required')
            cur.execute('INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(job['scope_key'],job['provider_id'],partition_key))
            cur.execute('SELECT generation FROM public.pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE',(job['scope_key'],job['provider_id'],partition_key))
            if row(cur)['generation']!=expected_generation:
                raise TrendStorageError('stale_cursor_fence')
            for observation in observations:
                if (observation['scope_key'],observation['provider_id'],observation['source_policy_version'])!=(job['scope_key'],job['provider_id'],job['source_policy_version']):
                    raise TrendStorageError('batch_scope_mismatch')
                self.store.put_observation(observation,cursor=cur)
            cur.execute('SELECT clock_timestamp() AS decision_cutoff')
            decision_cutoff = row(cur)['decision_cutoff']
            from .outbox import TrendOutbox
            outbox = TrendOutbox(self.store)
            for event in outbox_events:
                payload = dict(event.get('payload',{}))
                if event['event_type']=='trend.ingested':
                    if not self.store.offline_replay or not payload.get('decision_cutoff'):
                        payload['decision_cutoff'] = decision_cutoff
                    payload['provider_id'] = job['provider_id']
                outbox.enqueue(job['scope_key'],event['event_key'],event['event_type'],payload,node_id=event.get('node_id'),cursor=cur)
            # A large batch may outlast its lease while rows are being normalized.
            self._fence(cur,claim)
            cur.execute("""INSERT INTO public.pr_trend_ingestion_batches(scope_key,provider_id,partition_key,batch_key,job_id,fence,previous_generation,next_generation,item_count,digest,terminal_page)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(job['scope_key'],job['provider_id'],partition_key,batch_key,job['job_id'],job['lease_generation'],expected_generation,expected_generation+1,len(observations),
                digest({'job_id':job['job_id'],'fence':job['lease_generation'],'generation':expected_generation+1,'item_count':len(observations)}),terminal_page))
            cur.execute('UPDATE public.pr_trend_provider_cursors SET generation=generation+1,cursor_value=%s,coverage_state=%s,updated_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',
                (bounded_json(cursor_value),coverage_state,job['scope_key'],job['provider_id'],partition_key))
            if job['reservation_id']:
                self.settle(job['scope_key'],job['reservation_id'],actual_micro_usd=actual_micro_usd,usage_event_id=usage_event_id,cursor=cur)
            cur.execute("UPDATE public.pr_trend_jobs SET state='succeeded',payload='{}',lease_until=NULL,lease_owner=NULL WHERE scope_key=%s AND job_id=%s",(job['scope_key'],job['job_id']))
            return {'batch_key':batch_key,'generation':expected_generation+1,'item_count':len(observations),'cost_state':'known' if actual_micro_usd is not None else 'unknown'}

    def defer_local(self, claim, *, code, delay_seconds=60, cursor=None):
        """Return a proven pre-HTTP capacity denial without consuming an attempt.

        Caller owns the trusted transport boundary. Never use after any I/O.
        A new lease generation/reservation is required for the next attempt.
        """
        if code != 'meta_provider_quota_exhausted' or type(delay_seconds) is not int or not 1 <= delay_seconds <= 86400:
            raise TrendStorageError('invalid_local_deferral')
        with self.store.transaction(cursor) as cur:
            job = self._fence(cur, claim, revalidate_policy=False)
            if job['reservation_id']:
                self._abandon_reservation(job['scope_key'],job['reservation_id'],proven_unbilled=True,cursor=cur)
            cur.execute("""UPDATE public.pr_trend_jobs SET state='retry_wait',attempts=greatest(0,attempts-1),
                error_code=%s,due_at=clock_timestamp()+%s*interval '1 second',lease_owner=NULL,lease_until=NULL,
                reservation_id=NULL WHERE scope_key=%s AND job_id=%s RETURNING *""",
                (code,delay_seconds,job['scope_key'],job['job_id']))
            return row(cur)

    def fail(self, claim, *, code, retry_after_seconds=None, proven_unbilled=False, cursor=None):
        if not code.replace('_','').isalnum() or len(code)>80:
            raise TrendStorageError('unsafe_error_code')
        with self.store.transaction(cursor) as cur:
            # Accounting survives a policy revocation after dispatch; no new call is authorized.
            job = self._fence(cur,claim,revalidate_policy=False)
            unknown = job['state']=='running' and not proven_unbilled
            if job['reservation_id']:
                self._abandon_reservation(job['scope_key'],job['reservation_id'],proven_unbilled=not unknown,cursor=cur)
            retry = not unknown and retry_after_seconds is not None and job['attempts']<job['max_attempts']
            if retry_after_seconds is not None and (type(retry_after_seconds) is not int or not 0<=retry_after_seconds<=86400):
                raise TrendStorageError('invalid_retry_after')
            state = 'outcome_unknown' if unknown else 'retry_wait' if retry else 'failed_terminal'
            cur.execute("UPDATE public.pr_trend_jobs SET state=%s,payload=CASE WHEN %s='retry_wait' THEN payload ELSE '{}'::jsonb END,error_code=%s,due_at=clock_timestamp()+%s*interval '1 second',lease_owner=NULL,lease_until=NULL WHERE scope_key=%s AND job_id=%s RETURNING *",(state,state,code,retry_after_seconds or 0,job['scope_key'],job['job_id']))
            return row(cur)

    def cancel(self, scope_key, job_id, *, cursor=None):
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s FOR UPDATE',(scope_key,job_id))
            job = row(cur)
            if not job or job['state'] in ('succeeded','failed_terminal','cancelled'):
                return job
            if job['reservation_id']:
                self._abandon_reservation(scope_key,job['reservation_id'],proven_unbilled=job['state'] not in ('running','outcome_unknown'),cursor=cur)
            cur.execute("UPDATE public.pr_trend_jobs SET cancellation_requested=true,state='cancelled',payload='{}',lease_generation=lease_generation+1,lease_owner=NULL,lease_until=NULL WHERE scope_key=%s AND job_id=%s RETURNING *",(scope_key,job_id))
            return row(cur)
