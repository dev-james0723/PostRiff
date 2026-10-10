"""Content-free recovery categories for existing local workers; no scheduler or effects.

Callers must know whether external dispatch started. An exception after a possible
submission never proves rejection, even when its HTTP status normally retries.
"""
from postriff_alpha.domain import AlphaError
from .leases import backoff_seconds


def category(error, *, external_started=False):
    if external_started:
        return 'outcome_unknown'
    status = getattr(error, 'status', None)
    if status in (401, 403):
        return 'permission'
    if status == 402:
        return 'budget'
    if status in (408, 429) or isinstance(status, int) and status >= 500:
        return 'retryable'
    return 'permanent' if isinstance(error, (AlphaError, ValueError, TypeError)) else 'retryable'


def record(kind, attempts, *, max_attempts=3, now=0, retry_after=None):
    retryable = kind == 'retryable' and attempts < max_attempts
    return {'category': kind, 'attempts': attempts, 'maxAttempts': max_attempts,
            'automaticRetry': retryable,
            'retryAt': now + backoff_seconds(attempts, retry_after=retry_after) if retryable else None}
