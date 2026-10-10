"""Short, workspace/key-scoped admission for legacy turns in authoritative mode.

The session advisory lock is released immediately after the run and usage.request
fingerprint commit, before any model/provider call. It serializes the interval
that previously created duplicate empty conversations before INSERTing a run.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from . import flags, model
from ...permissions import require

_request = ContextVar("agent_task_request", default=None)


@contextmanager
def admit(runtime, workspace_id, token, payload):
    key = str(payload.get("idempotencyKey") or "").strip()[:100] if isinstance(payload, dict) else ""
    if not key or not flags.enabled_for(workspace_id, runtime.cfg):
        yield
        return
    with runtime.service.repository.transaction(token, workspace_id) as (_cur, row, principal):
        require(runtime.service.ideas._member(row), "read")
    canonical = {k: v for k, v in payload.items() if k not in ("traceId", "idempotencyKey")}
    fingerprint = {"principal": principal, "digest": model.sha256(json.dumps([principal, canonical], sort_keys=True, separators=(",", ":"), ensure_ascii=False))}
    db = runtime.service.repository.connection_factory()
    lock = "pr_agent_turn_admission:" + workspace_id + ":" + key
    state = {"db": db, "lock": lock, "request": fingerprint}
    reset = _request.set(state)
    try:
        with db.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (lock,))
        db.commit()
        yield
    finally:
        release()
        _request.reset(reset)


def fingerprint():
    return (_request.get() or {}).get("request")


def record(cur, run_id):
    request = fingerprint()
    if request:
        cur.execute("UPDATE public.pr_agent_runs SET usage=coalesce(usage,'{}'::jsonb)||jsonb_build_object('request',%s::jsonb) WHERE id::text=%s",
                    (json.dumps(request), run_id))


def release():
    state = _request.get()
    if not state or state.get("db") is None:
        return
    db, state["db"] = state["db"], None
    try:
        with db.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (state["lock"],))
        db.commit()
    finally:
        db.close()
