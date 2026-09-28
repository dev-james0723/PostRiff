"""Bounded aggregate operational signals. Never emits source text or identities."""
from .store import row, rows


LANGUAGES = ['en','zh','zh-Hans','zh-Hant','yue','ja','ko','es','fr','de','pt','ar','hi','und']
PLATFORMS = ['bluesky','mastodon','youtube','reddit','instagram','tiktok','facebook','threads','x','linkedin']


def _lag(cur, source, params, limit):
    # source is a constant SQL expression below, never supplied by a caller.
    cur.execute('''WITH sample AS (''' + source + ''') SELECT count(value) AS samples,
        percentile_cont(.50) WITHIN GROUP(ORDER BY value) AS p50_seconds,
        percentile_cont(.95) WITHIN GROUP(ORDER BY value) AS p95_seconds,
        percentile_cont(.99) WITHIN GROUP(ORDER BY value) AS p99_seconds FROM sample''',params)
    result = row(cur)
    result['sample_limit_reached'] = result['samples'] >= limit
    return result


def _recent_signals(cur, window_seconds, sample_limit):
    # Explicit recent sample caps avoid unbounded per-record payload expansion.
    cur.execute('SELECT clock_timestamp() AS measured_at')
    measured_at = row(cur)['measured_at']
    bounds = (measured_at,window_seconds,sample_limit)
    lag = {}
    lag['ingestion_persistence'] = _lag(cur, '''SELECT greatest(0,extract(epoch FROM available_at-received_at)) AS value
        FROM public.pr_trend_observations WHERE available_at>=%s::timestamptz-%s*interval '1 second'
        ORDER BY available_at DESC LIMIT %s''', bounds, sample_limit)
    lag['queue_due'] = _lag(cur, '''SELECT greatest(0,extract(epoch FROM %s::timestamptz-due_at)) AS value
        FROM public.pr_trend_jobs WHERE state IN ('queued','retry_wait') AND due_at<=%s::timestamptz
        ORDER BY due_at LIMIT %s''', (measured_at,measured_at,sample_limit), sample_limit)
    lag['provider_freshness'] = _lag(cur, '''SELECT freshness_lag_seconds AS value
        FROM public.pr_trend_source_health WHERE observed_at>=%s::timestamptz-%s*interval '1 second'
        AND freshness_lag_seconds IS NOT NULL ORDER BY observed_at DESC LIMIT %s''', bounds, sample_limit)
    lag['outbox_completion'] = _lag(cur, '''SELECT greatest(0,extract(epoch FROM c.completed_at-e.created_at)) AS value
        FROM public.pr_trend_outbox_consumers c JOIN public.pr_trend_outbox e USING(scope_key,event_id)
        WHERE c.state='done' AND c.completed_at>=%s::timestamptz-%s*interval '1 second'
        ORDER BY c.completed_at DESC LIMIT %s''', bounds, sample_limit)
    lag['receipt_verification'] = _lag(cur, '''SELECT greatest(0,extract(epoch FROM r.verified_at-n.available_at)) AS value
        FROM public.pr_trend_trust_receipts r JOIN public.pr_trend_nodes n
        ON(n.scope_key,n.node_id)=(r.scope_key,r.receipt_id)
        WHERE r.verified_at>=%s::timestamptz-%s*interval '1 second'
        ORDER BY r.verified_at DESC LIMIT %s''', bounds, sample_limit)
    # Safe reason enums only. Even legacy malformed audit payloads cannot become
    # arbitrary metric labels or cause a JSON-array cast failure.
    from .quarantine import REASONS
    cur.execute('''WITH sample AS (SELECT payload FROM public.pr_trend_outbox
        WHERE event_type='trend.quarantined' AND created_at>=%s::timestamptz-%s*interval '1 second'
        ORDER BY created_at DESC LIMIT %s), codes AS (
        SELECT CASE WHEN e->>'reason_code'=ANY(%s) THEN e->>'reason_code' ELSE 'invalid_record' END AS reason_code
        FROM sample CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(payload->'entries')='array'
        THEN payload->'entries' ELSE '[]'::jsonb END) e)
        SELECT reason_code,count(*) AS count FROM codes GROUP BY reason_code ORDER BY reason_code''',
        (*bounds,sorted(REASONS)))
    quarantine_reasons = rows(cur)
    cur.execute('''SELECT count(*) AS receipts FROM (SELECT 1 FROM public.pr_trend_outbox
        WHERE event_type='trend.quarantined' AND created_at>=%s::timestamptz-%s*interval '1 second'
        ORDER BY created_at DESC LIMIT %s) s''', bounds)
    quarantine = row(cur)
    quarantine.update(reason_counts=quarantine_reasons,sample_limit_reached=quarantine['receipts']>=sample_limit)
    # Public method artifact hashes are retained independently of source evidence.
    # Cohort labels are fixed enums, never workspace, source, episode or author IDs.
    cur.execute('''WITH sample AS (
        SELECT p.scope_key,p.method_id,p.method_version,p.receipt_id,p.payload
        FROM public.pr_trend_projections p WHERE p.kind='trend'
        AND p.available_at>=%s::timestamptz-%s*interval '1 second'
        ORDER BY p.available_at DESC LIMIT %s), safe AS (
        SELECT m.artifact_digest AS method_artifact_digest,m.qualification AS method_qualification,
        CASE WHEN p.scope_key LIKE 'workspace:%%' THEN 'workspace' ELSE 'shared' END AS scope_class,
        CASE WHEN p.payload->>'language'=ANY(%s) THEN p.payload->>'language' ELSE 'other_or_unknown' END AS language,
        CASE WHEN p.payload->>'platform'=ANY(%s) THEN p.payload->>'platform' ELSE 'other_or_unknown' END AS platform,
        coalesce(r.verification_state,'pending') AS verification_state,
        CASE WHEN r.payload#>>'{inferred,data_state}'=ANY(ARRAY['qualified','provisional','insufficient','partial','gap','unavailable'])
        THEN r.payload#>>'{inferred,data_state}' ELSE 'unknown' END AS data_state
        FROM sample p JOIN public.pr_trend_method_versions m ON(m.method_id,m.version)=(p.method_id,p.method_version)
        LEFT JOIN public.pr_trend_trust_receipts r ON(r.scope_key,r.receipt_id)=(p.scope_key,p.receipt_id))
        SELECT method_artifact_digest,method_qualification,scope_class,language,platform,verification_state,data_state,
        count(*) AS revisions FROM safe GROUP BY 1,2,3,4,5,6,7 ORDER BY revisions DESC,1,2,3,4,5,6,7 LIMIT 250''',
        (*bounds,LANGUAGES,PLATFORMS))
    cohorts = rows(cur)
    return {'measured_at':measured_at,'window_seconds':window_seconds,'sample_limit':sample_limit,
            'lag_seconds':lag,'quarantine':quarantine,
            'receipt_method_cohorts':{'items':cohorts,'population':'recent_stored_trend_revisions',
                'rows_returned':len(cohorts),'group_limit_reached':len(cohorts)==250,
                'sample_limit_reached':sum(c['revisions'] for c in cohorts)>=sample_limit,
                'language_qualification':'unavailable_requires_retained_calibration',
                'warning':'verification_and_method_qualification_do_not_qualify_a_language_cohort'}}


def snapshot(store, *, cursor=None, window_seconds=86400, sample_limit=10000):
    if type(window_seconds) is not int or not 60<=window_seconds<=7*86400 or type(sample_limit) is not int or not 1<=sample_limit<=10000:
        raise ValueError('invalid_operations_window')
    with store.transaction(cursor) as cur:
        cur.execute('''SELECT state,count(*) AS count,
            max(greatest(0,extract(epoch FROM clock_timestamp()-due_at))) FILTER(WHERE state IN ('queued','retry_wait')) AS oldest_due_seconds
            FROM public.pr_trend_jobs GROUP BY state''')
        jobs = rows(cur)
        cur.execute('''SELECT dimension,count(*) AS budgets,sum(cap_micro_usd) AS cap_micro_usd,
            sum(settled_micro_usd) AS settled_micro_usd,sum(reserved_micro_usd) AS reserved_micro_usd,
            sum(unknown_micro_usd) AS unknown_micro_usd
            FROM public.pr_trend_budget_limits WHERE period_start<=clock_timestamp() AND period_end>clock_timestamp() GROUP BY dimension''')
        costs = rows(cur)
        cur.execute('''SELECT verification_state,count(*) AS count FROM public.pr_trend_trust_receipts
            GROUP BY verification_state''')
        receipts = rows(cur)
        cur.execute('''SELECT count(*) AS pending,
            count(*) FILTER(WHERE purge_deadline<clock_timestamp()) AS overdue
            FROM public.pr_trend_deletion_tasks d JOIN public.pr_trend_deletion_tombstones t
            USING(scope_key,provider_id,source_identity_digest) WHERE d.state='queued' ''')
        deletion = row(cur)
        cur.execute('SELECT status,count(*) AS count FROM public.pr_trend_source_health GROUP BY status')
        health = rows(cur)
        recent = _recent_signals(cur,window_seconds,sample_limit)
        reasons = []
        if deletion['overdue']:
            reasons.append('deletion_deadline_exceeded')
        if any(r['verification_state']=='mismatch' and r['count'] for r in receipts):
            reasons.append('receipt_mismatch')
        if any(r['unknown_micro_usd'] for r in costs):
            reasons.append('cost_reconciliation_required')
        if any(r['settled_micro_usd']+r['reserved_micro_usd']+r['unknown_micro_usd']>r['cap_micro_usd'] for r in costs):
            reasons.append('budget_cap_exceeded')
        if recent['quarantine']['receipts']:
            reasons.append('quarantined_records')
        return {'status': 'attention' if reasons else 'ok', 'reason_codes': reasons,
                'jobs': jobs, 'budgets': costs, 'receipt_verifications': receipts,
                'deletion': deletion, 'source_health': health, 'recent':recent,
                'notification_delivery': 'not_dispatched_by_observer'}
