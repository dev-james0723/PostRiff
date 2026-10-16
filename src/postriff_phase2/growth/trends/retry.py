"""One persisted retry owner, bounded Retry-After and explicit billing certainty.

HTTP status never proves a request was unbilled. Unknown dispatched attempts are
terminal outcome_unknown with exposure retained, even for 429/5xx or timeouts.
No sleeping, network calls, raw headers or provider error bodies are persisted.
"""
from dataclasses import dataclass
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
import logging
import math
import re

from . import source_health
from .contracts import ContractError, instant, iso
from .jobs import TrendJobs
from .planner import integer
from .store import row, utcnow

LOG = logging.getLogger('postriff.trends')
# Circuit breaker cooldown per consecutive opening since the last committed
# batch: 15 minutes, 1 hour, 6 hours, then capped at 24 hours.
COOLDOWN_SECONDS = (900, 3600, 21600, 86400)


def cooldown_seconds(openings):
    integer(openings, 1, 2**31 - 1, 'invalid_breaker_openings')
    return COOLDOWN_SECONDS[min(openings, len(COOLDOWN_SECONDS)) - 1]


def safe_label(value):
    """Bounded log label for an operator-configured identifier (never content)."""
    return value if isinstance(value, str) and re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,39}', value) else 'other'


def breaker_openings(cur, scope_key, provider_id):
    """Consecutive breaker openings since the last committed batch; bounded, no migration.

    Terminal ingest failures closer together than the minimum cooldown belong to
    the same opening (several partitions failing in one window, or the pre-breaker
    every-five-minutes failure loop). A failed half-open probe after a lapsed
    cooldown starts a new opening, which escalates the next cooldown.
    """
    cur.execute('''WITH last_batch AS (SELECT max(b.committed_at) AS at FROM public.pr_trend_ingestion_batches b
            WHERE b.scope_key=%s AND b.provider_id=%s),
        failures AS (SELECT j.due_at FROM public.pr_trend_jobs j CROSS JOIN last_batch
            WHERE j.scope_key=%s AND j.provider_id=%s AND j.kind='trend.ingest'
            AND j.state IN ('failed_terminal','outcome_unknown')
            AND j.due_at>coalesce(last_batch.at,'-infinity'::timestamptz)
            ORDER BY j.due_at DESC LIMIT 1000),
        spaced AS (SELECT due_at-lag(due_at) OVER (ORDER BY due_at) AS gap FROM failures)
        SELECT count(*) FILTER (WHERE gap IS NULL OR gap>=interval '14 minutes') AS trips FROM spaced''',
        (scope_key, provider_id, scope_key, provider_id))
    found = row(cur)
    trips = found.get('trips') if found else None
    return max(1, trips) if type(trips) is int else 1


@dataclass(frozen=True)
class RetryDecision:
    code: str
    delay_seconds: int | None
    pause: bool
    outcome_unknown: bool


def retry_after(headers, *, now, ceiling=86400):
    integer(ceiling, 1, 86400, 'retry_bounds')
    if headers is None:
        return None
    # Accept a bounded Mapping-like headers object. Duplicate spellings fail
    # closed; no unbounded iteration or exception body parsing.
    try:
        if len(headers) > 64:
            return None
        values = [v for k, v in headers.items() if isinstance(k, str) and k.lower() == 'retry-after']
        if len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 128:
            return None
        value = values[0].strip()
        if value.isascii() and value.isdigit():
            return min(ceiling, int(value))
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return min(ceiling, max(0, math.ceil((date.astimezone(timezone.utc) - instant(now)).total_seconds())))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None


def decide(*, status=None, headers=None, now, attempt, max_attempts,
           dispatched, proven_unbilled=False, jitter=0.5, base_seconds=5,
           ceiling_seconds=3600, deadline=None):
    integer(attempt, 1, 3, 'retry_bounds'); integer(max_attempts, 1, 3, 'retry_bounds')
    integer(base_seconds, 1, 3600, 'retry_bounds'); integer(ceiling_seconds, base_seconds, 86400, 'retry_bounds')
    if type(dispatched) is not bool or type(proven_unbilled) is not bool:
        raise ContractError('retry_certainty_required')
    if type(jitter) not in (int, float) or not math.isfinite(jitter) or not 0 <= jitter <= 1:
        raise ContractError('invalid_retry_jitter')
    if status is not None:
        integer(status, 100, 599, 'invalid_http_status')
    instant(now)
    unknown = dispatched and not proven_unbilled
    pause = status in (401, 402, 403)
    code = {401: 'authentication_required', 402: 'provider_budget_paused', 403: 'provider_access_denied'}.get(status)
    if pause:
        return RetryDecision(code, None, True, unknown)
    if unknown:
        return RetryDecision('provider_outcome_unknown', None, False, True)
    transient = status is None or status == 429 or status >= 500
    if not transient:
        return RetryDecision('provider_request_terminal', None, False, False)
    if attempt >= max_attempts:
        return RetryDecision('provider_attempts_exhausted', None, False, False)
    exponential = min(ceiling_seconds, base_seconds * 2 ** (attempt - 1))
    delay = math.ceil(exponential * (0.5 + jitter / 2))
    after = retry_after(headers, now=now, ceiling=86400)
    # A provider minimum outside the bounded horizon means stop, never retry
    # earlier than that minimum simply because a local cap is smaller.
    if after is not None:
        if after >= 86400 or after > ceiling_seconds:
            return RetryDecision('retry_horizon_exceeded', None, False, False)
        delay = max(delay, after)
    if deadline is not None and instant(now) + timedelta(seconds=delay) >= instant(deadline):
        return RetryDecision('retry_horizon_exceeded', None, False, False)
    return RetryDecision('provider_rate_limited' if status == 429 else 'provider_transient', delay, False, False)


def fail_attempt(store, claim, *, status=None, headers=None, dispatched,
                 proven_unbilled=False, jitter=0.5, now=None, deadline=None,
                 base_seconds=5, ceiling_seconds=3600, cursor=None):
    """Atomically fence failure, settle exposure and persist source pause/backoff.

    Call with the latest claim from jobs.start(), and the worker's actual
    dispatch boundary. Only trusted transport/accounting may prove unbilled.
    Explicit operator repair of source health is required after auth/budget pause.
    A terminal failure of a dispatched provider attempt opens the circuit breaker
    with an escalating cooldown; only a later committed batch clears it.
    """
    now = now or utcnow()
    decision = decide(status=status, headers=headers, now=now, attempt=claim['attempts'],
        max_attempts=claim['max_attempts'], dispatched=dispatched, proven_unbilled=proven_unbilled,
        jitter=jitter, deadline=deadline, base_seconds=base_seconds, ceiling_seconds=ceiling_seconds)
    with store.transaction(cursor) as cur:
        result = TrendJobs(store).fail(claim, code=decision.code, retry_after_seconds=decision.delay_seconds,
                                     proven_unbilled=not dispatched or proven_unbilled, cursor=cur)
        if claim.get('provider_id'):
            # Serialize absence as well as an existing health row. A later
            # transient response must never undo an authentication/budget pause.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                        ('trend-retry-health|' + claim['scope_key'] + '|' + claim['provider_id'],))
            cur.execute('SELECT * FROM public.pr_trend_source_health WHERE scope_key=%s AND provider_id=%s FOR UPDATE',
                        (claim['scope_key'], claim['provider_id']))
            prior = row(cur)
            if prior and prior['status'] == 'revoked':
                return {'job': result, 'decision': decision}
            next_allowed_at = (iso(instant(now) + timedelta(seconds=decision.delay_seconds))
                               if decision.delay_seconds is not None else None)
            opened = None
            if decision.delay_seconds is None and not decision.pause and dispatched:
                # A NULL here let planner/frontier recreate failing jobs forever
                # (2026-10-05..09: 576 jobs/day). Pause with an escalating cooldown.
                opened = cooldown_seconds(breaker_openings(cur, claim['scope_key'], claim['provider_id']))
                next_allowed_at = iso(instant(now) + timedelta(seconds=opened))
            source_health.record(store, claim['scope_key'], claim['provider_id'],
                status='revoked' if decision.pause else 'unavailable', reason_code=decision.code,
                observed_at=now, next_allowed_at=next_allowed_at, cursor=cur)
            if opened is not None:
                # One bounded line per opening; admission blocks every job until it lapses.
                LOG.warning('trend.circuit_open provider=%s reason=%s cooldown_seconds=%d',
                            safe_label(claim['provider_id']), decision.code, opened)
        return {'job': result, 'decision': decision}
