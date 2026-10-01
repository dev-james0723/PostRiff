"""Cron step (``growth_v2_routes.CRON``): recompute recent proof periods so late data becomes a new revision.

Bounded (a few workspaces per tick, each re-checked at most every six hours), flag-gated (off: no database effect),
system-triggered and isolated; it reads stored records only and sends nothing (the existing recap notifications
are unchanged).
"""
from __future__ import annotations

from . import enabled

MAX_WORKSPACES = 10


def tick(hosted, deadline):
    if not enabled():
        return {"status": "disabled"}
    from .http import ensure
    return ensure(hosted).cron(deadline, MAX_WORKSPACES)
