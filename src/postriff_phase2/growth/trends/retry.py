"""One persisted retry owner, bounded Retry-After and explicit billing certainty.

HTTP status never proves a request was unbilled. Unknown dispatched attempts are
terminal outcome_unknown with exposure retained, even for 429/5xx or timeouts.
No sleeping, network calls, raw headers or provider error bodies are persisted.
"""
from dataclasses import dataclass
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
import math

from . import source_health
from .contracts import ContractError, instant, iso
from .jobs import TrendJobs
from .planner import integer
from .store import row, utcnow, trust_lock


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
    """
    now = now or utcnow()
    decision = decide(status=status, headers=headers, now=now, attempt=claim['attempts'],
        max_attempts=claim['max_attempts'], dispatched=dispatched, proven_unbilled=proven_unbilled,
        jitter=jitter, deadline=deadline, base_seconds=base_seconds, ceiling_seconds=ceiling_seconds)
    with store.transaction(cursor) as cur:
        if status in (401,403) and (claim.get('provider_id'),claim.get('payload',{}).get('operation')) in (
                ('threads','keyword_search'),('instagram','hashtag_discovery'),('facebook','page_public_posts')):
            # Known permission failure withdraws public evidence under the same
            # fence held by JEV pre-egress and result attachment.
            trust_lock(cur,exclusive=True)
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
            # Provider cooldown outlives a terminal job's attempt budget. Otherwise
            # a new scheduled job can immediately repeat a rate-limited request.
            health_delay = decision.delay_seconds
            if status == 429:
                health_delay = max(health_delay or 0, retry_after(headers, now=now) or base_seconds)
            if prior and prior.get('next_allowed_at'):
                health_delay = max(health_delay or 0, math.ceil((instant(prior['next_allowed_at'])-instant(now)).total_seconds()))
            source_health.record(store, claim['scope_key'], claim['provider_id'],
                status='revoked' if decision.pause else 'unavailable', reason_code=decision.code,
                observed_at=now, next_allowed_at=iso(instant(now) + timedelta(seconds=health_delay))
                if health_delay is not None else None, cursor=cur)
        return {'job': result, 'decision': decision}
