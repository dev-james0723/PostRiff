"""One `public.pr_ai_call_events` row per AI provider attempt (Founder Admin CONTRACTS §8.B; PRD §8.0, §8.1, §8.9).

Every metered provider attempt — writer drafts and revisions, gateway images, preference-learning extraction, Agent Runtime
generations (Manager, specialists, vision, follow-up chips) and images, GPT-Live voice and phone audio, growth evaluations —
becomes one row: feature, workload, model, route (primary|fallback), attempt number, token counts (input including cached,
cached, output including reasoning, reasoning: OpenAI semantics, PRD §8.0), images, audio seconds, latency, status, HTTP
status, the provider's request id and the cost. A cost is the provider's report (`gateway`/`provider`), a price-table figure
computed when the attempt is recorded (`table:<version>`; history is never re-priced) or NULL when unknown — never zero. A
cost learned later goes to `pr_ai_call_settlements`; the original row never changes.

Recording can never break or slow a customer request:
- `write(rows, cursor=cur)` inserts inside the caller's own transaction under a savepoint (psycopg `conn.transaction()`), so a
  failed insert rolls back only itself; `scope(...)` collects the attempts a run makes (`attempt(...)`, no I/O) and writes them
  once, when the run ends, on a short connection of its own with a 2 s statement timeout. One bounded statement, no retries.
- Any failure is swallowed and logged by exception class only. A missing table, column or privilege (migration 058 not yet
  applied) stops every write for ten minutes and is logged once per process.
Rows hold ids, enums, counts, amounts and timestamps only — never a prompt, an output, a provider payload or customer text.
Workspaces classified internal/test/demo and aiUsageExempt users are recorded like everyone else; the founder views exclude
them, never this writer.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import math
import re
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation

LOG = logging.getLogger("postriff.ai_call_events")
STATUSES = frozenset({"ok", "failed", "cancelled", "rate_limited", "timeout", "unknown"})
ROUTES = frozenset({"primary", "fallback"})
COLUMNS = ("workspace_id", "user_id", "feature", "workload", "run_id", "reservation_id", "attempt_no", "physical_attempt_id", "provider", "model", "route",
           "provider_request_id", "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "images", "audio_seconds", "cost_usd_micro",
           "cost_source", "price_version", "status", "http_status", "latency_ms", "ai_usage_exempt", "started_at", "dedupe_key")
# Price tables seeded by migration 058 (public.pr_price_versions); a cost computed from one names it in cost_source/price_version.
GATEWAY_LIST = "gateway-list-2026-09-24"         # model_runtime.DEFAULT_PRICES (+ the image route estimate)
AGENT_V2 = "agent-v2-2026-09-24"                  # agent_runtime_v2.config.DEFAULT_PRICES
MEDIA_CONSTANTS = "media-constants-2026-09-24"    # per-image estimates and the GPT-Live per-minute rate
CUSTOMER_PRICING = "pricing-provisional-2026-09-24"
CONFIGURED = "configured"                          # a deployment override (POSTRIFF_/RAFII_ price env); not a seeded table
PRICE_VERSIONS = (GATEWAY_LIST, AGENT_V2, MEDIA_CONSTANTS, CUSTOMER_PRICING)
# The billing account behind a route (who is paid), so the same provider is never counted under two names.
PROVIDER_ALIASES = {"gateway": "vercel-ai-gateway", "ai-gateway": "vercel-ai-gateway", "vercel": "vercel-ai-gateway"}
NOT_INSTALLED = frozenset({"UndefinedTable", "UndefinedColumn", "InsufficientPrivilege", "UndefinedObject", "InvalidSchemaName"})
BACKOFF_SECONDS = 600
STATEMENT_TIMEOUT_MS = 2000
MAX_ROWS = 200                 # per write; an Agent turn records at most a few dozen attempts
MAX_SCOPE_ATTEMPTS = 50        # per scope (a writer run makes at most three)
SAVEPOINT = "pr_ai_call_events_write"

_FEATURE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_WORKLOAD = re.compile(r"^[a-z][a-z0-9_.]{0,59}$")
_PROVIDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,59}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$")
_OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,199}$")
_SOURCE = re.compile(r"^(gateway|provider|table:[A-Za-z0-9._-]{1,60})$")
_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
_INT_MAX = 2**31 - 1

_STATE = {"disabled_until": 0.0, "logged": False}
_SCOPE: contextvars.ContextVar = contextvars.ContextVar("postriff_ai_call_scope", default=None)


# --- values -------------------------------------------------------------------------------------------------------------
def usd_micro(value):
    """A provider-reported USD amount as whole micro-dollars, rounded up (exact for decimal strings); None when unusable."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def table_cost(cost_usd_micro, version):
    """(cost, cost_source, price_version) for a figure computed from a price table; unknown when there is no figure."""
    if type(cost_usd_micro) is not int or cost_usd_micro < 0 or not isinstance(version, str) or not _VERSION.match(version):
        return None, "unknown", None
    return cost_usd_micro, "table:" + version, version


def provider_name(value):
    text = value.strip().lower() if isinstance(value, str) else ""
    text = PROVIDER_ALIASES.get(text, text)
    return text if _PROVIDER.match(text or "") else "unknown"


def _uuid(value):
    if value is None or value == "":
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _count(value, cap=_INT_MAX):
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        value = int(value)
    return value if type(value) is int and 0 <= value <= cap else None


def _stamp(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return datetime.fromtimestamp(float(value), timezone.utc)
    return datetime.now(timezone.utc)


def _exempt(user_id):
    if not user_id:
        return False
    try:
        from .developer_usage import ai_usage_exempt
        return bool(ai_usage_exempt(user_id))
    except Exception:  # noqa: BLE001 - an unreadable allowlist exempts nobody
        return False


def build(base, fields, *, index=None, scope_id=None):
    """One normalised row. Anything outside its column's bounds becomes NULL (or a safe default), never an error, so one odd
    value can't cost the attempt its record. A cost without a valid source is recorded as unknown."""
    merged = {**(base or {}), **(fields or {})}
    workspace, user = _uuid(merged.get("workspace_id")), _uuid(merged.get("user_id"))
    feature = merged.get("feature") if isinstance(merged.get("feature"), str) and _FEATURE.match(merged["feature"]) else "other"
    workload = merged.get("workload") if isinstance(merged.get("workload"), str) and _WORKLOAD.match(merged["workload"]) else None
    run, reservation = _uuid(merged.get("run_id")), _uuid(merged.get("reservation_id"))
    attempt_no = _count(merged.get("attempt_no"), 100) or 1
    physical = merged.get("physical_attempt_id")
    physical = str(physical) if physical is not None and _OPAQUE.match(str(physical)) and len(str(physical)) <= 120 else None
    if physical is None and scope_id and index is not None:
        physical = f"{scope_id}:{index}"
    model = merged.get("model") if isinstance(merged.get("model"), str) and _MODEL.match(merged["model"]) else "unknown"
    route = merged.get("route") if merged.get("route") in ROUTES else "primary"
    request_id = merged.get("provider_request_id")
    request_id = request_id if isinstance(request_id, str) and _OPAQUE.match(request_id) else None
    audio = merged.get("audio_seconds")
    audio = round(float(audio), 3) if isinstance(audio, (int, float)) and not isinstance(audio, bool) and math.isfinite(audio) and 0 <= audio < 10_000_000 else None
    status = merged.get("status") if merged.get("status") in STATUSES else "unknown"
    http = _count(merged.get("http_status"), 599)
    http = http if http is not None and http >= 100 else None
    latency = merged.get("latency_ms")
    latency = _count(round(latency) if isinstance(latency, float) and math.isfinite(latency) else latency)
    cost, source, version = _count(merged.get("cost_usd_micro"), 2**62), merged.get("cost_source"), merged.get("price_version")
    if cost is None or not isinstance(source, str) or not _SOURCE.match(source):
        cost, source, version = None, "unknown", None
    elif source.startswith("table:"):
        version = source[len("table:"):]
    else:
        version = version if isinstance(version, str) and _VERSION.match(version) else None
    stable = physical or request_id
    identity = "|".join((workspace or "-", feature, run or "-", reservation or "-", workload or "-", str(attempt_no), physical or "-", request_id or "-",
                         "" if stable else uuid.uuid4().hex))
    return {"workspace_id": workspace, "user_id": user, "feature": feature, "workload": workload, "run_id": run, "reservation_id": reservation,
            "attempt_no": attempt_no, "physical_attempt_id": physical, "provider": provider_name(merged.get("provider")), "model": model, "route": route,
            "provider_request_id": request_id, "input_tokens": _count(merged.get("input_tokens")), "output_tokens": _count(merged.get("output_tokens")),
            "cached_input_tokens": _count(merged.get("cached_input_tokens")), "reasoning_tokens": _count(merged.get("reasoning_tokens")),
            "images": _count(merged.get("images"), 100), "audio_seconds": audio, "cost_usd_micro": cost, "cost_source": source, "price_version": version,
            "status": status, "http_status": http, "latency_ms": latency, "ai_usage_exempt": _exempt(user), "started_at": _stamp(merged.get("started_at")),
            "dedupe_key": hashlib.sha256(identity.encode()).hexdigest()}


# --- writing ------------------------------------------------------------------------------------------------------------
def installed():
    """False while a recent write found the tables, a column or the privilege missing (re-checked after BACKOFF_SECONDS)."""
    return time.monotonic() >= _STATE["disabled_until"]


def _failed(error):
    name = type(error).__name__
    if name in NOT_INSTALLED:
        _STATE["disabled_until"] = time.monotonic() + BACKOFF_SECONDS
        if not _STATE["logged"]:
            _STATE["logged"] = True
            LOG.warning(json.dumps({"event": "ai_call_events.not_installed", "errorClass": name, "retryAfterSeconds": BACKOFF_SECONDS}))
        return
    LOG.warning(json.dumps({"event": "ai_call_events.write_failed", "errorClass": name}))


def _insert(cur, rows):
    placeholders = ",".join("(" + ",".join(["%s"] * len(COLUMNS)) + ")" for _ in rows)
    cur.execute(f"INSERT INTO public.pr_ai_call_events({','.join(COLUMNS)}) VALUES {placeholders} ON CONFLICT (dedupe_key) DO NOTHING",
                [row[column] for row in rows for column in COLUMNS])
    inserted = getattr(cur, "rowcount", None)
    costed = [row for row in rows if row["cost_usd_micro"] is not None]
    if costed:
        # A late cost (the same attempt recorded again once its usage is known) settles an unknown-cost row in the sidecar;
        # the original row is never changed (PRD §8.1). A row inserted just now with its cost needs no settlement.
        values = ",".join(["(%s::text,%s::bigint,%s::text,%s::numeric)"] * len(costed))
        cur.execute("INSERT INTO public.pr_ai_call_settlements(call_event_id,cost_usd_micro,source,audio_seconds) "
                    f"SELECT e.id,v.cost,v.source,v.audio FROM (VALUES {values}) AS v(dedupe_key,cost,source,audio) "
                    "JOIN public.pr_ai_call_events e ON e.dedupe_key=v.dedupe_key WHERE e.cost_usd_micro IS NULL "
                    "ON CONFLICT (call_event_id,source) DO NOTHING",
                    [value for row in costed for value in (row["dedupe_key"], row["cost_usd_micro"], row["cost_source"], row["audio_seconds"])])
    return inserted if type(inserted) is int and inserted >= 0 else len(rows)


def _in_savepoint(cursor, rows):
    nested = getattr(getattr(cursor, "connection", None), "transaction", None)
    if callable(nested):
        with nested():   # psycopg: SAVEPOINT inside the caller's open transaction; ROLLBACK TO it (and re-raise) on failure
            return _insert(cursor, rows)
    cursor.execute(f"SAVEPOINT {SAVEPOINT}", ())
    try:
        inserted = _insert(cursor, rows)
    except BaseException:
        try:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {SAVEPOINT}", ())
            cursor.execute(f"RELEASE SAVEPOINT {SAVEPOINT}", ())
        except Exception:  # noqa: BLE001 - the original failure is what gets reported
            pass
        raise
    cursor.execute(f"RELEASE SAVEPOINT {SAVEPOINT}", ())
    return inserted


def _on_own_connection(connect, rows):
    with connect() as db:
        with db.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}", ())
            inserted = _insert(cur, rows)
        db.commit()
    return inserted


def write(rows, *, cursor=None, connect=None):
    """Insert built rows; returns how many were new. Never raises. With `cursor` the rows join the caller's transaction (and
    commit with it) under a savepoint; with `connect` (a connection factory) they commit on a short connection of their own."""
    rows = [row for row in (rows or []) if isinstance(row, dict)][:MAX_ROWS]
    if not rows or not installed() or (cursor is None and connect is None):
        return 0
    try:
        return _in_savepoint(cursor, rows) if cursor is not None else _on_own_connection(connect, rows)
    except Exception as error:  # noqa: BLE001 - recording never fails the customer's request
        _failed(error)
        return 0


def write_attempts(base, attempts, *, cursor=None, connect=None, scope_id=None):
    """Build and write attempt dicts against shared `base` fields (workspace, user, feature, run, reservation). Never raises."""
    try:
        rows = [build(base, item, index=index, scope_id=scope_id) for index, item in enumerate(list(attempts or [])[:MAX_ROWS]) if isinstance(item, dict)]
    except Exception as error:  # noqa: BLE001
        _failed(error)
        return 0
    return write(rows, cursor=cursor, connect=connect)


# --- scopes: a run's attempts, written once when the run ends -----------------------------------------------------------
@dataclass
class Scope:
    base: dict
    connect: object = None
    cursor: object = None
    attempts: list = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


def active():
    return _SCOPE.get() is not None


@contextmanager
def scope(*, feature, workspace_id=None, user_id=None, run_id=None, reservation_id=None, connect=None, cursor=None):
    """Attribute every `attempt(...)` made inside this block to one workspace/user/feature/run/reservation and write them when the
    block ends — also when it ends with an exception, which is exactly when a failed attempt matters most."""
    current = Scope(base={"workspace_id": workspace_id, "user_id": user_id, "feature": feature, "run_id": run_id, "reservation_id": reservation_id},
                    connect=connect, cursor=cursor)
    token = _SCOPE.set(current)
    try:
        yield current
    finally:
        try:
            _SCOPE.reset(token)
        except ValueError:   # reset from another context (a generator finalised elsewhere): the block is over either way
            pass
        if current.attempts:
            write_attempts(current.base, current.attempts, cursor=current.cursor, connect=current.connect, scope_id=current.id)


def attempt(**fields):
    """Note one provider attempt in the active scope (no I/O: the scope writes when it ends). Outside a scope: nothing."""
    current = _SCOPE.get()
    if current is not None and len(current.attempts) < MAX_SCOPE_ATTEMPTS:
        current.attempts.append(dict(fields))


def sink_scope(emit, *, feature):
    """The scope for a run whose events go through a run sink's bound `emit` (ideas.RunSink: workspace_id, run_id,
    outcome{reservationId, actor}, service.repository.connection_factory). An already active scope wins; anything else gets
    a no-op context, so an unattributable attempt is simply not recorded."""
    if _SCOPE.get() is not None:
        return nullcontext()
    owner = getattr(emit, "__self__", None)
    try:
        outcome = owner.outcome
        connect = owner.service.repository.connection_factory
        workspace_id, run_id = owner.workspace_id, owner.run_id
    except AttributeError:
        return nullcontext()
    if not isinstance(outcome, dict) or not callable(connect) or not _uuid(workspace_id):
        return nullcontext()
    return scope(feature=feature, workspace_id=workspace_id, user_id=outcome.get("actor"), run_id=run_id, reservation_id=outcome.get("reservationId"),
                 connect=connect)
