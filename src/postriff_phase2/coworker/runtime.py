"""Wiring for the coworker upgrade (architecture lock §3): one `attach` at hosted-app construction, one `cron`
step. Both are safe with every flag off: `attach` only stores configuration and registers hooks that return
immediately, and `cron` returns {"status": "disabled"} for each feature that is off.
"""
from __future__ import annotations

import json
import logging
import time

from . import flags

log = logging.getLogger("postriff.coworker")


def attach(service, values):
    """Called once from hosted_app.runtime_from_environment with the isolated environment. `values=None` (tests,
    the dev harness) keeps whatever flag source is already in effect."""
    if values is not None:
        flags.attach(values)
    if getattr(service, "notifications", None) is None:
        from ..notifications.service import NotificationService
        service.notifications = NotificationService(service, values)
        if service.notifications.effect not in service.repository.effects:
            service.repository.effects.append(service.notifications.effect)
    if getattr(service, "coworker", None) is None:
        from .service import CoworkerService
        service.coworker = CoworkerService(service, values)
    return service


def ensure(service):
    """For hosts constructed without runtime_from_environment (tests, the dev harness)."""
    if getattr(service, "notifications", None) is None or getattr(service, "coworker", None) is None:
        attach(service, None)
    return service


def cron(service, max_seconds=120):
    """One bounded, isolated coworker step of /api/cron/worker (the function may run 300 s; this step takes at most
    `max_seconds` of it). Each step gets what is left of the budget. Never raises; with every flag off it does nothing."""
    if not any(flags.snapshot().values()):
        return {"status": "disabled"}
    try:
        ensure(service)
    except Exception as error:  # noqa: BLE001 - a host without the coworker's dependencies simply skips it
        return {"status": "unavailable", "error": type(error).__name__}
    result = {}
    deadline = time.monotonic() + max_seconds
    left = lambda reserve=0: max(0.0, deadline - reserve - time.monotonic())  # noqa: E731
    for name, step in (("notifications", lambda: service.notifications.cron(max_seconds=max(5, min(20, int(left()))))),
                       ("weekly", lambda: service.coworker.weekly_cron(max_seconds=left(10), deadline=deadline - 10)),
                       ("learning", lambda: service.coworker.performance_cron(deadline=deadline - 5)),
                       ("listening", lambda: service.coworker.listening_cron(deadline=deadline - 5)),
                       ("retention", lambda: service.coworker.retention_sweep())):
        if name != "notifications" and left() <= 0:
            result[name] = {"status": "deferred", "reason": "the coworker cron budget is used up; the next minute continues"}
            continue
        try:
            result[name] = step()
        except Exception as error:  # noqa: BLE001 - one failing step never stops the others or the worker
            result[name] = {"error": type(error).__name__}
            log.warning(json.dumps({"event": "coworker.cron_step_failed", "step": name, "error": type(error).__name__}))
    return result
