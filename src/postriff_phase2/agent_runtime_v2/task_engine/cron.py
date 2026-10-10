"""Cron entry points (CF-3 §5.3, EX-12). Phases are isolated and never raise out; phases 1–3 make zero provider requests; the
summary is counts only (never workspace ids or text).

P0 placement:
- `recover_for_worker(service)` runs phases 1–3 (recover, expire, adopt + reap stalled agent turns) inside the existing
  /api/cron/worker, within ≤ 10 s, only when the engine is enabled for at least one workspace;
- `tick(service)` is the dedicated /api/cron/agent-tasks route (auth before init, CRON_SECRET, hmac.compare_digest). It adds
  phase 4 (background claims: R0 reads, delegate polls, waits) only with RAFII_AGENT_TASKS_BACKGROUND. The route ships
  unscheduled: it stays out of vercel.json until DP-12.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from . import bridge, executor, flags

STALE_TURN_SECONDS = 600


def _light_runtime(service):
    from ..config import RuntimeConfig
    existing = getattr(service, "_agent_runtime_v2", None)
    return SimpleNamespace(service=service, cfg=getattr(existing, "cfg", None) or RuntimeConfig.from_environment(), clock=getattr(service, "clock", time.time))


def _phase(counts: dict, name: str, fn) -> None:
    try:
        counts[name] = fn()
    except Exception as error:  # noqa: BLE001 — one phase never stops the others
        counts[name] = {"status": "unavailable", "error": type(error).__name__}


def recover_for_worker(service, *, budget_seconds: float = executor.RECOVERY_BUDGET_SECONDS) -> dict | None:
    """None when the engine is off everywhere (the worker's result then carries no new key: today's output unchanged)."""
    runtime = _light_runtime(service)
    if not flags.anywhere(runtime.cfg):
        # Rollback exception: settle only expired attempts left by a previous on mode.
        with service.repository.connection_factory() as db:
            if not db.execute("SELECT to_regclass('public.pr_agent_step_attempts')").fetchone()[0]:
                return None
            if not db.execute("SELECT 1 FROM public.pr_agent_step_attempts WHERE state='running' AND lease_expires_at<now() LIMIT 1").fetchone():
                return None
        return {"providerRequests": 0, "recover": executor.recover(runtime, budget_seconds=budget_seconds)}
    started = time.monotonic()
    counts: dict = {"providerRequests": 0}
    _phase(counts, "recover", lambda: executor.recover(runtime, budget_seconds=budget_seconds / 2))
    _phase(counts, "expire", lambda: executor.expire(runtime, budget_seconds=max(1.0, budget_seconds - (time.monotonic() - started))))
    _phase(counts, "adopted", lambda: bridge.adopt_some(service, limit=50))
    _phase(counts, "staleTurns", lambda: reap_stale_turns(service))
    from . import notifications
    _phase(counts, "notifications", lambda: notifications.scan(runtime))
    counts["ms"] = round((time.monotonic() - started) * 1000)
    return counts


def reap_stale_turns(service, *, max_workspaces: int = 20) -> int:
    """The agent-turn reaper (service._reap_stale_turns) is lazy today; run it for allowlisted workspaces with stalled turns."""
    with service.repository.connection_factory() as db, db.cursor() as scan:
        scan.execute("SELECT DISTINCT workspace_id::text FROM public.pr_agent_runs WHERE idempotency_key LIKE 'agent:%%' AND status='running' "
                     "AND updated_at < now()-make_interval(secs => %s) LIMIT %s", (STALE_TURN_SECONDS, max_workspaces * 4))
        candidates = [r[0] for r in scan.fetchall()]
    candidates = [w for w in candidates if flags.enabled_for(w)][:max_workspaces]
    if not candidates:
        return 0
    from ..http import runtime_for
    from . import store
    runtime = runtime_for(service)
    reaped = 0
    for workspace_id in candidates:
        with store.service_tx(service, workspace_id, skip_locked=True) as cur:
            if cur is None:
                continue
            runtime._reap_stale_turns(cur, workspace_id)
            reaped += 1
    return reaped


def tick(service) -> dict:
    """/api/cron/agent-tasks: phases 1–3, then background claims when RAFII_AGENT_TASKS_BACKGROUND is on."""
    counts = recover_for_worker(service) or {"status": "disabled"}
    if flags.background():
        from ..http import runtime_for
        from ...workflow_recipes import runner as recipes
        _phase(counts, "recipes", lambda: recipes.scan(runtime_for(service)))
        _phase(counts, "claims", lambda: executor.claim_loop(runtime_for(service)))
    else:
        counts["claims"] = {"status": "background_off"}
    return counts
