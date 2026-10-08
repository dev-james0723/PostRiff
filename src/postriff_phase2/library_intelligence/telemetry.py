"""Content-free Library intelligence metrics, operator logs and the status view (engineering spec §12; T12; A073).

`record(cur, feature, event, value, dims)` appends one row to pr_library_metrics inside the caller's transaction under a
savepoint and never raises. `log(event, **fields)` prints one JSON line for operators. Both accept only shapes that cannot
carry content: numbers, booleans, lowercase codes, opaque ids (32-hex, UUID), model/processor identifiers and ISO times.
Free text, URLs, e-mail addresses, prompts, titles, snippets and secrets are dropped, whatever the field is called, so a
mistaken call site leaks nothing. An exception is reduced to its class name.

Call sites (one line each; they never fail the request):
    jobs                 outcome, retry, queue age, stale lease, bytes processed, cost by kind      (wired in jobs.py)
    lifecycle            deletion/revocation receipts, backfill checkpoints/progress                 (wired in lifecycle.py)
    search.search_http   `with telemetry.timed(ctx, "library.search"):`                              (C; patch requested)
    answers.answer_http  `with telemetry.timed(ctx, "library.answer"):`                              (C; patch requested)
    citations.viewer_http  count(ctx, "library.citations", "locator_failed", code=error.code)        (C; patch requested)
    policy.require       count(ctx, "library.policy", "denied", reason=decision.reason)              (coordinator)
    source packs         count(ctx, "library.packs", "attached_to_draft")                            (E)
    artifacts            count(ctx, "library.artifacts", "duplicate_suppressed")                     (E)
    suggestions          count(ctx, "library.suggestions", "dismissed", category=...)                (D)
"""
from __future__ import annotations

import json
import math
import re
import time
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError

from . import policy, versions

NAME = re.compile(r"^[a-z][a-z0-9_.]{0,60}$")
DIM_KEY = re.compile(r"^[a-z][A-Za-z0-9_]{0,40}$")
CODE = re.compile(r"^[a-z][a-z0-9_.]{0,79}$")
HEX = re.compile(r"^[0-9a-f]{32}$|^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,119}$")  # model and processor identifiers
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
EXCEPTION = re.compile(r"^[A-Z][A-Za-z0-9_]{0,80}$")
# Field names that describe content or credentials: never recorded, whatever the value looks like.
CONTENT_KEYS = frozenset({"text", "title", "name", "filename", "prompt", "query", "q", "body", "content", "snippet", "summary", "note", "detail",
                          "message", "url", "href", "uri", "email", "token", "secret", "password", "key", "apikey", "authorization", "header",
                          "headers", "cookie", "path", "quote", "answer", "caption", "transcript"})
SECRETISH = re.compile(r"(?i)(sk[-_]|pk[-_]|rk[-_]|ghp_|gho_|xox[abp]-|bearer|basic |eyj[a-z0-9_-]{8,}|akia[0-9a-z]{12,}|://|@.+\.)")
MAX_DIMS = 16


def _safe_value(value):
    """The value itself when it cannot carry content, else None (dropped)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if abs(value) < 2 ** 62 else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, BaseException):
        name = type(value).__name__
        return name if EXCEPTION.fullmatch(name) else None
    if not isinstance(value, str) or not value or len(value) > 120 or SECRETISH.search(value):
        return None
    if CODE.fullmatch(value) or HEX.fullmatch(value) or UUID.fullmatch(value) or ISO.fullmatch(value):
        return value
    if IDENT.fullmatch(value) and ("/" in value or "-" in value) and not value.isupper() and sum(ch.isdigit() for ch in value) < 24:
        return value  # model/processor identifiers such as local/visual-perceptual-v1 or openai/text-embedding-3-large
    return None


def safe_dims(dims) -> dict:
    out = {}
    for key, value in (dims or {}).items():
        if len(out) >= MAX_DIMS or not isinstance(key, str) or not DIM_KEY.fullmatch(key) or key.lower() in CONTENT_KEYS:
            continue
        safe = _safe_value(value)
        if safe is not None:
            out[key] = safe
    return out


def record(cur, feature: str, event: str, value=None, dims=None, *, workspace_id=None) -> bool:
    """Append one content-free metric row in the caller's transaction. Returns False (never raises) when refused or failed."""
    if not isinstance(feature, str) or not NAME.fullmatch(feature) or not isinstance(event, str) or not NAME.fullmatch(event):
        return False
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))):
        return False
    try:
        cur.execute("SAVEPOINT library_metric")
    except Exception:
        return False
    try:
        cur.execute("/*lit:metrics.insert*/ INSERT INTO public.pr_library_metrics(workspace_id,feature,event,value,dims) VALUES(%s,%s,%s,%s,%s::jsonb)",
                    (str(workspace_id) if workspace_id else None, feature, event, None if value is None else float(value), json.dumps(safe_dims(dims))))
        cur.execute("RELEASE SAVEPOINT library_metric")
        return True
    except Exception as error:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT library_metric")
        except Exception:
            pass
        log("library_intelligence.metric_failed", error=error)
        return False


def count(ctx, feature: str, event: str, value=1, **dims) -> bool:
    """One-line counter for request handlers: workspace from the verified context."""
    return record(ctx.cur, feature, event, value, dims, workspace_id=ctx.workspace_id)


@contextmanager
def timed(ctx, feature: str, event: str = "latency_ms", **dims):
    """Latency of a request handler, labelled ok or by the AlphaError code. The metric never changes the outcome."""
    started = time.monotonic()
    outcome = {"status": "ok"}
    try:
        yield outcome
    except AlphaError as error:
        outcome["status"] = error.code or f"http_{error.status}"
        raise
    except Exception as error:
        outcome["status"] = type(error).__name__
        raise
    finally:
        record(ctx.cur, feature, event, round((time.monotonic() - started) * 1000, 3), {**dims, **outcome}, workspace_id=ctx.workspace_id)


def log(event: str, **fields):
    """One operator log line with only content-free fields. Never raises."""
    try:
        line = {"event": event if isinstance(event, str) and NAME.fullmatch(event) else "library_intelligence.log"}
        for key, value in fields.items():
            if isinstance(key, str) and DIM_KEY.fullmatch(key) and key.lower() not in CONTENT_KEYS:
                safe = _safe_value(value)
                if safe is not None:
                    line[key] = safe
        print(json.dumps(line, sort_keys=True), flush=True)
    except Exception:
        pass


# --- status ------------------------------------------------------------------------------------------------------------
QUEUE = ("/*lit:status.queue*/ SELECT count(*) FILTER (WHERE status='queued'),count(*) FILTER (WHERE status='processing'),count(*) FILTER (WHERE status='failed'),"
         "extract(epoch from now()-min(created_at) FILTER (WHERE status='queued')),count(*) FILTER (WHERE status='processing' AND lease_expires_at<now()) "
         "FROM public.pr_library_jobs WHERE workspace_id=%s")
CAPS = "/*lit:status.caps*/ SELECT asset_key,capability,state FROM public.pr_library_capabilities WHERE workspace_id=%s"
COSTS = ("/*lit:status.costs*/ SELECT coalesce(sum(CASE WHEN a.value->>'kind'='actual' THEN (a.value->>'usdMicro')::bigint END),0),"
         "coalesce(sum(CASE WHEN a.value->>'kind'='estimated' THEN (a.value->>'usdMicro')::bigint END),0),count(*) FILTER (WHERE a.value->>'kind'='unknown') "
         "FROM public.pr_library_jobs j CROSS JOIN LATERAL jsonb_each(coalesce(j.cost->'byAttempt','{}'::jsonb)) a WHERE j.workspace_id=%s")
AI_TABLE = "/*lit:status.ai_table*/ SELECT to_regclass('public.pr_ai_call_events') IS NOT NULL"
AI_COSTS = ("/*lit:status.ai*/ SELECT coalesce(sum(cost_usd_micro) FILTER (WHERE cost_source IN ('gateway','provider')),0),"
            "coalesce(sum(cost_usd_micro) FILTER (WHERE cost_source LIKE 'table:%%'),0),count(*) FILTER (WHERE cost_source='unknown') "
            "FROM public.pr_ai_call_events WHERE workspace_id=%s AND feature='library_intelligence'")
INDEX_CAPABILITIES = ("extract", "transcribe", "embed_text", "embed_visual")


def _providers(ctx) -> dict:
    intelligence = getattr(ctx.service, "library_intelligence", None)
    seam = getattr(intelligence, "providers", None) if intelligence is not None else None
    if seam is None:
        from .providers import Providers
        seam = Providers()
    try:
        return {name: {"available": bool(s.get("available")), "reason": s.get("reason"), "model": s.get("model")} for name, s in seam.status().items()}
    except Exception as error:
        log("library_intelligence.status_providers_failed", error=error)
        return {}


def _coverage(ctx, generation: int) -> dict:
    accessible = versions.accessible_keys(ctx)
    ctx.cur.execute(CAPS, (ctx.workspace_id,))
    states: dict[str, dict] = {}
    for key, capability, state in ctx.cur.fetchall():
        states.setdefault(key, {})[capability] = state
    out = {"accessible": len(accessible), "indexed": 0, "pending": 0, "failed": 0, "notIndexed": 0, "indexGeneration": generation}
    for key in accessible:
        caps = states.get(key, {})
        if any(caps.get(cap) in ("ready", "partial") for cap in INDEX_CAPABILITIES):
            out["indexed"] += 1
        elif any(state in ("queued", "processing") for state in caps.values()):
            out["pending"] += 1
        elif any(state == "failed" for state in caps.values()):
            out["failed"] += 1
        else:
            out["notIndexed"] += 1
    return out


def _costs(ctx) -> dict:
    ctx.cur.execute(COSTS, (ctx.workspace_id,))
    actual, estimated, unknown = ctx.cur.fetchone() or (0, 0, 0)
    out = {"actualUsdMicro": int(actual or 0), "estimatedUsdMicro": int(estimated or 0), "unknownCount": int(unknown or 0), "source": "library_jobs",
           "providerAttempts": None}
    ctx.cur.execute(AI_TABLE)
    row = ctx.cur.fetchone()
    if row and row[0]:
        ctx.cur.execute(AI_COSTS, (ctx.workspace_id,))
        a, e, u = ctx.cur.fetchone() or (0, 0, 0)
        out["providerAttempts"] = {"actualUsdMicro": int(a or 0), "estimatedUsdMicro": int(e or 0), "unknownCount": int(u or 0), "source": "pr_ai_call_events"}
    return out


def status_http(ctx, request):
    """GET …/library/intelligence/status. Workspace-scoped; cost data for editors and owners only."""
    ctx.require("read")
    from . import lifecycle
    revs = policy.revisions(ctx, fresh=True)
    ctx.cur.execute(QUEUE, (ctx.workspace_id,))
    queued, processing, failed, oldest, stale = ctx.cur.fetchone() or (0, 0, 0, None, 0)
    out = {"flags": policy.flag_state(), "providers": _providers(ctx), "revisions": revs,
           "queue": {"queued": int(queued or 0), "processing": int(processing or 0), "failed": int(failed or 0),
                     "oldestQueuedSeconds": int(oldest) if oldest is not None else None, "staleLeases": int(stale or 0)},
           "coverage": _coverage(ctx, revs["indexGeneration"]), "backfill": {"paused": lifecycle.backfill_paused()},
           "costsVisible": ctx.allows("edit"), "costs": None}
    if out["costsVisible"]:
        out["costs"] = _costs(ctx)
    return out
