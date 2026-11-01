"""Privacy-safe durable provider health and circuit admission; no provider traffic.

``next_allowed_at`` is monotonic: a later write never replaces a later pause with
NULL or an earlier time (a transient 5s backoff cannot shorten a breaker
cooldown). Only the explicit success path (``clear_pause=True``, used after a
committed batch) clears it, still guarded by ``observed_at`` ordering.
"""
from .store import TrendStorageError, row, utcnow
from .contracts import instant


def record(store, scope_key, provider_id, *, status, reason_code, observed_at=None, next_allowed_at=None,
           latency_ms=None, freshness_lag_seconds=None, clear_pause=False, cursor=None):
    if status not in ('healthy','partial','gap','unavailable','revoked') or not reason_code.replace('_','').isalnum() or len(reason_code)>80:
        raise TrendStorageError('invalid_health_code')
    if type(clear_pause) is not bool:
        raise TrendStorageError('invalid_health_code')
    observed_at = observed_at or utcnow(); instant(observed_at)
    if next_allowed_at:
        instant(next_allowed_at)
    with store.transaction(cursor) as cur:
        # greatest() ignores NULL: NULL+X -> X, X+NULL -> X, X+Y -> the later pause.
        cur.execute("""INSERT INTO public.pr_trend_source_health(scope_key,provider_id,status,observed_at,next_allowed_at,latency_ms,freshness_lag_seconds,notes_code)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_key,provider_id) DO UPDATE SET
            status=excluded.status,observed_at=excluded.observed_at,
            next_allowed_at=CASE WHEN %s::boolean THEN excluded.next_allowed_at
                ELSE greatest(pr_trend_source_health.next_allowed_at,excluded.next_allowed_at) END,
            latency_ms=excluded.latency_ms,freshness_lag_seconds=excluded.freshness_lag_seconds,notes_code=excluded.notes_code
            WHERE pr_trend_source_health.observed_at<=excluded.observed_at RETURNING *""",
            (scope_key,provider_id,status,observed_at,next_allowed_at,latency_ms,freshness_lag_seconds,reason_code,clear_pause))
        return row(cur)


def get(store, scope_key, provider_id, *, cursor=None):
    with store.transaction(cursor) as cur:
        cur.execute('SELECT * FROM public.pr_trend_source_health WHERE scope_key=%s AND provider_id=%s',(scope_key,provider_id))
        return row(cur)
