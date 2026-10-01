"""Cron step (``growth_v2_routes.CRON``): store each recipient's weekly brief and alert within the delivery caps.

Bounded (a few recipients per tick, each re-checked at most every six hours), flag-gated (off: no database effect)
and isolated (one recipient's failure is counted, never raised). It reads stored evidence only.
"""
from __future__ import annotations

from . import enabled

MAX_RECIPIENTS = 10


def tick(hosted, deadline):
    if not enabled():
        return {"status": "disabled"}
    from .http import ensure
    return ensure(hosted).cron(deadline, MAX_RECIPIENTS)
