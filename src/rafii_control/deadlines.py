"""Request-local deadline shared by DB operations; no global mutable budget."""
from contextvars import ContextVar
from time import monotonic
from .auth import ControlError

deadline = ContextVar('control_request_deadline', default=None)


def remaining(default=5.0):
    end = deadline.get()
    budget = default if end is None else min(default, end-monotonic())
    if budget <= 0:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return budget
