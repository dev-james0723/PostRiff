"""Rafii agent observability (P0.7): correlated, content-free traces and metrics for one request.

    request ─▶ plan ─▶ authz ─▶ tool ─▶ mutation ─▶ verify ─▶ response        (+ approval, provider_auth, recovery)

Correlation reuses the ids that already exist; nothing new is minted:
- `requestId`: hosted_app's `postriff.request_id` (the X-Request-ID header, the request.completed and cron.completed lines),
  bound for the request by `bind_request`; every event emitted while it is bound carries it.
- `traceId`: the turn's `trace_<32 hex>` (contracts.new_trace_id): the same id as pr_agent_runs.artifact.trace.traceId, the
  run.started event in pr_agent_events, the Agents SDK trace, pr_usage_ledger meta.traceId and pr_ai_call_events attempt ids.
- `runId` (pr_agent_runs / pr_agent_events), and for CF-3 tasks `taskId` / `stepKey`.
- GenUI keeps its own `genui.validation_rejected` line (ui_stream). Its persisted outcomes (pr_ui_artifacts/pr_ui_attempts,
  linked by parent_run_id) are counted by the founder view, never logged a second time here.

Content-free by construction. Every event goes through `clean()`: a fixed key allowlist with one validator per key (ids by
exact pattern, enums by set, codes by a bounded lowercase pattern that also refuses anything shaped like a credential,
bounded numbers). Anything else is dropped and only counted (`dropped`). The builders read codes, enums, counts and timings
only, never a prompt, message, answer, title, label, reason sentence, email, URL, token or provider payload. A redaction
test (tests/test_agent_observability.py) pushes secrets through every emitter.

Never in the way. Emitters never raise, do no I/O except one log line on the `postriff.agent_observability` logger, and
never change an argument or a return value. Metrics go to the bounded in-process recorder in `agent_metrics` (flushed off
the request path to public.pr_agent_metrics). Kill switch: POSTRIFF_AGENT_OBSERVABILITY=0 (no lines, no metrics).

Emitter API for other lanes (stable names; every argument optional except where noted):
- `permission_decision(ctx, outcome=, reason=, mode=, capability_id=, risk=, category=, tool=, surface=, would_outcome=)`:
  CF-2 §14's one JSON line per decision, `agent.authz` (shadow: `agent.authz.shadow` with `wouldOutcome`). R0 allows are
  counted but not logged (they go only to the run trace, CF-2 §14). Lane B1 calls it from `authz.gate`.
- `task_event(name, trace_id=, task_id=, step_key=, state=, reason=, attempt=, run_id=, latency_ms=)`: CF-3 §16's
  `agent_task.<name>` lines (lane A2).
- `approval_decided(surface=, outcome=, proposal_type=, wait_ms=, verified=, trace_id=, run_id=, kind=)`.
- `provider_authorization_failed(provider=, reason=, ctx=|trace_id=, tool=)`.
- `retry(kind, ...)`, `recovery(kind, result, ...)`.
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
import re
import threading
import time

LOGGER = "postriff.agent_observability"
log = logging.getLogger(LOGGER)
log.setLevel(logging.INFO)   # like postriff.request: INFO lines reach the platform log

PHASES = ("request", "plan", "authz", "approval", "tool", "mutation", "verify", "response")
EVENTS = {
    "agent.request": "request",
    "agent.plan": "plan",
    "agent.authz": "authz",
    "agent.authz.shadow": "authz",
    "agent.provider_auth": "authz",
    "agent.approval": "approval",
    "agent.tool": "tool",
    "agent.mutation": "mutation",
    "agent.verify": "verify",
    "agent.recovery": "verify",
    "agent.retry": "tool",
    "agent.response": "response",
}
# CF-3 §16 task engine lines (lane A2): agent_task.<name>.
TASK_EVENTS = {"created": "plan", "step_claimed": "tool", "step_finished": "verify", "step_reclaimed": "tool", "approval_requested": "approval",
               "approval_decided": "approval", "approval_expired": "approval", "cancelled": "response", "revoked": "authz",
               "compensation_applied": "mutation", "tick": "plan"}
EVENTS.update({"agent_task." + name: phase for name, phase in TASK_EVENTS.items()})

EFFECTS = frozenset({"READ", "CREATE_DRAFT", "MUTATE_REVERSIBLE", "PREPARE_EXTERNAL", "EXTERNAL_EFFECT", "DESTRUCTIVE", "SECRET"})
MODALITIES = frozenset({"text", "voice", "image"})
MODES = frozenset({"off", "shadow", "enforce", "legacy"})   # legacy: today's checks in tool_adapter.execute (role, voice, tenant, scope)
COST_STATES = frozenset({"known", "unknown", "none", "scripted"})
TENANTS = frozenset({"workspace", "founder"})

# Planning tools (the Manager's own plan; CF-1 R0) and today's authorization refusals in tool_adapter.execute.
PLAN_TOOLS = frozenset({"task_plan", "task_update"})
LEGACY_AUTHZ_CODES = frozenset({"tool_forbidden", "forbidden", "voice_not_allowed", "tool_tenant", "tool_out_of_scope", "youtube_analytics_read_only"})
# CF-2 refusals: counted through permission_decision (lane B1), so a tool line carrying one is not counted twice.
CF2_AUTHZ_CODES = frozenset({"agent_permission_denied", "agent_permission_revoked", "needs_confirmation", "native_only", "approval_stale"})
# Provider authorization failures by code -> (provider or None, reason). CF-2 §8.4 reasons plus today's connector codes.
PROVIDER_AUTH_CODES = {
    "youtube_revoked_oauth": ("youtube", "revoked"), "youtube_reconnect_required": ("youtube", "reconnect_required"),
    "youtube_connection_changed": ("youtube", "connection_changed"), "youtube_agentic_scope_required": ("youtube", "scope_missing"),
    "youtube_agentic_consent_required": ("youtube", "consent_required"), "youtube_authorization_schema": ("youtube", "authorization_unavailable"),
    "connector_reauthorization_required": (None, "reauthorization_required"), "connector_scope_missing": (None, "scope_missing"),
    "reauthorization_required": (None, "reauthorization_required"), "token_scope_denied": (None, "scope_missing"),
    "provider_not_connected": (None, "not_connected"), "provider_reauth_required": (None, "reauthorization_required"),
    "provider_scope_missing": (None, "scope_missing"), "provider_lane_mismatch": (None, "lane_mismatch"),
    "provider_capability_unsupported": (None, "capability_unsupported"), "provider_disconnected": (None, "disconnected"),
    "provider_grant_missing": (None, "grant_missing"),
}
PROVIDERS = frozenset({"youtube", "instagram", "facebook", "threads", "tiktok", "linkedin", "x", "bluesky", "pinterest", "reddit", "mastodon",
                       "pixelfed", "google_business_profile", "weibo", "zhihu", "bilibili", "douyin", "kuaishou", "xiaohongshu", "discord",
                       "telegram", "line_official_account", "gmail", "notion", "google_calendar", "google_drive", "outlook", "slack",
                       "openai", "gateway", "stripe", "twilio", "telnyx", "resend"})
TOOL_STATUSES = frozenset({"verified", "unverified", "failed", "blocked"})
RECOVERABLE_FALLBACKS = frozenset({"model_error", "timeout", "max_turns", "guardrail_output", "guardrail_input", "turn_time"})

# --- validators ------------------------------------------------------------------------------------------------------------
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_REQUEST = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
_TRACE = re.compile(r"^trace_[0-9a-f]{32}$")
_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STEP = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,39}$")
_CLASS = re.compile(r"^[A-Z][A-Za-z0-9_]{0,63}$")
_RISK = re.compile(r"^R[0-3]$")
# Shapes of credentials and identifiers that must never ride in a "code": long hex or digit runs (keys, ids, phone numbers),
# well-known token prefixes followed by a body, and bearer schemes.
_SECRET = re.compile(r"[0-9a-f]{16,}|[0-9]{7,}|(?:^|[^a-z0-9])(?:sk|pk|rk|ghp|gho|ghs|ghu|ghr|xox[a-z]|whsec|glpat|akia|aiza|ya29|bearer)[_.:-][a-z0-9]{3,}"
                     r"|(?:^|[^a-z0-9])eyj[a-z0-9_-]{8,}")
MAX_NUMBER = 10 ** 12
MAX_COUNTS = 40


def _code(value):
    if not isinstance(value, str) or not _CODE.match(value) or _SECRET.search(value):
        return None
    return value


def _ident(rx):
    # Ids are random by design: matched exactly, never secret-screened (a uuid is hex).
    return lambda value: value if isinstance(value, str) and rx.match(value) else None


def _enum(values):
    return lambda value: value if isinstance(value, str) and value in values else None


def _integer(low, high):
    return lambda value: value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None


def _number(low, high):
    def check(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or not low <= value <= high:
            return None
        return round(float(value), 1)
    return check


def _boolean(value):
    return value if isinstance(value, bool) else None


def _counts(value):
    if not isinstance(value, dict):
        return None
    out = {}
    for key, count in list(value.items())[:MAX_COUNTS]:
        key, count = _code(key), _integer(0, 10 ** 7)(count)
        if key is not None and count is not None:
            out[key] = count
    return out


def _name(value):
    return value if isinstance(value, str) and _NAME.match(value) and not _SECRET.search(value) else None


def _error_class(value):
    """A Python exception class name (type(error).__name__): CamelCase with lowercase letters, never an all-caps key."""
    if not isinstance(value, str) or not _CLASS.match(value) or not re.search(r"[a-z]", value) or re.search(r"[A-Z0-9]{6,}", value):
        return None
    return None if _SECRET.search(value.lower()) else value


FIELDS = {
    "traceId": _ident(_TRACE), "runId": _ident(_UUID), "taskId": _ident(_UUID), "approvalId": _ident(_UUID), "requestId": _ident(_REQUEST),
    "stepKey": lambda v: v if isinstance(v, str) and _STEP.match(v) and not _SECRET.search(v) else None,
    "seq": _integer(0, 10 ** 6), "attempt": _integer(0, 10 ** 4),
    "tool": _name, "specialist": _name, "capabilityId": _code, "category": _code, "effect": _enum(EFFECTS),
    "status": _code, "outcome": _code, "wouldOutcome": _code, "code": _code, "reason": _code, "fallback": _code, "mode": _enum(MODES),
    "risk": lambda v: v if isinstance(v, str) and _RISK.match(v) else None, "modality": _enum(MODALITIES), "surface": _code, "path": _code,
    "tenant": _enum(TENANTS), "composedBy": _code, "proposalType": _code, "provider": _code, "kind": _code, "result": _code, "state": _code,
    "workload": _code, "command": _code, "genui": _code, "preset": _code, "costState": _enum(COST_STATES),
    "latencyMs": _number(0, MAX_NUMBER), "e2eMs": _number(0, MAX_NUMBER), "waitMs": _number(0, MAX_NUMBER),
    "costUsdMicro": _integer(0, MAX_NUMBER), "modelRequests": _integer(0, 10 ** 5), "httpStatus": _integer(100, 599), "attachments": _integer(0, 100),
    "verified": _boolean, "shadow": _boolean, "delegated": _boolean, "hasConversation": _boolean, "widened": _boolean,
    "errorClass": _error_class, "counts": _counts,
}


def clean(fields: dict) -> tuple[dict, int]:
    """(allowlisted and validated fields, number dropped). None values are absent, not dropped."""
    out, dropped = {}, 0
    for key, value in (fields or {}).items():
        if value is None:
            continue
        check = FIELDS.get(key)
        safe = check(value) if check is not None else None
        if safe is None:
            dropped += 1
        elif safe != {}:
            out[key] = safe
    return out, dropped


def code_or(value, default="other"):
    return _code(value) or default


# --- switches and correlation ----------------------------------------------------------------------------------------------
def enabled(environ=None) -> bool:
    return str((os.environ if environ is None else environ).get("POSTRIFF_AGENT_OBSERVABILITY", "0")).strip().lower() in ("1", "true", "yes", "on")


REQUEST_ID: contextvars.ContextVar = contextvars.ContextVar("postriff_agent_request_id", default=None)
SCOPE: contextvars.ContextVar = contextvars.ContextVar("postriff_agent_turn_scope", default=None)


def bind_request(request_id):
    """Bind the request id for this request's events (hosted_app.__call__). Returns the token for `release_request`."""
    try:
        return REQUEST_ID.set(request_id if isinstance(request_id, str) and _REQUEST.match(request_id) else None)
    except Exception:  # noqa: BLE001 — correlation is never a reason for a request to fail
        return None


def release_request(token) -> None:
    if token is None:
        return
    try:
        REQUEST_ID.reset(token)
    except Exception:  # noqa: BLE001
        pass


class Scope:
    """One runtime turn's correlation and accumulators. Shared by reference with tool threads (asyncio.to_thread copies the
    context, not the object), so every mutation holds the lock."""

    def __init__(self, modality, trace_id):
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.modality = modality
        self.trace_id = trace_id
        self.seq = 0
        self.snapshot = None          # the persisted run's outcome summary (run_persisted)
        self.tools = {}               # tool -> [calls, last status ok?]
        self.authz = {}               # "mode:outcome" -> count
        self.provider_auth = 0
        self.approvals = 0

    def next_seq(self) -> int:
        with self.lock:
            self.seq += 1
            return self.seq

    def note_tool(self, tool: str, ok: bool) -> tuple[int, bool, bool]:
        """(attempt number, is a retry after a failure, recovered by this call)."""
        with self.lock:
            calls, last_ok = self.tools.get(tool, (0, True))
            retry = calls > 0 and not last_ok
            self.tools[tool] = (calls + 1, ok)
            return calls + 1, retry, retry and ok

    def unrecovered(self) -> int:
        with self.lock:
            return sum(1 for calls, ok in self.tools.values() if calls > 1 and not ok)


def emit(event: str, **fields) -> dict | None:
    """One content-free JSON line. Returns the record written (tests), or None. Never raises."""
    if event not in EVENTS or not enabled():
        return None
    try:
        body, dropped = clean(fields)
        record = {"event": event, "phase": EVENTS[event], **body}
        request_id = REQUEST_ID.get()
        if request_id and "requestId" not in record:
            record["requestId"] = request_id
        scope = SCOPE.get()
        if scope is not None:
            if scope.trace_id and "traceId" not in record:
                record["traceId"] = scope.trace_id
            record["seq"] = scope.next_seq()
        if dropped:
            record["dropped"] = dropped
        log.info(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
        return record
    except Exception:  # noqa: BLE001 — telemetry never changes the request
        return None


def _metric(name, label, value=None, count=1):
    try:
        from . import agent_metrics
        agent_metrics.RECORDER.record(name, label, value, count)
    except Exception:  # noqa: BLE001
        pass


def _learn_trace(scope, trace_id) -> None:
    """A turn whose request carried no trace id learns it from the first tool or stored run (contracts.new_trace_id)."""
    if scope is not None and not scope.trace_id and isinstance(trace_id, str) and _TRACE.match(trace_id):
        with scope.lock:
            scope.trace_id = scope.trace_id or trace_id


def _ids(ctx):
    return {"traceId": getattr(ctx, "trace_id", None), "runId": getattr(ctx, "run_id", None)}


def _tenant(ctx) -> str:
    extra = getattr(ctx, "extra", None)
    return "founder" if isinstance(extra, dict) and isinstance(extra.get("founder"), dict) and extra.get("founder") else "workspace"


# --- emitters: tools, authz, providers, approvals, tasks -------------------------------------------------------------------
def tool_activity(ctx, record) -> None:
    """One tool call as the gate recorded it (context.RafiiRunContext.activity): plan, authz, tool or mutation phase."""
    if not enabled() or not isinstance(record, dict):
        return
    try:
        tool = _name(record.get("tool")) or "unknown"
        status = record.get("status") if record.get("status") in TOOL_STATUSES else "other"
        code = _code(record.get("code"))
        effect = record.get("effect") if record.get("effect") in EFFECTS else None
        latency = record.get("latencyMs")
        scope = SCOPE.get()
        _learn_trace(scope, getattr(ctx, "trace_id", None))
        attempt, retried, recovered = scope.note_tool(tool, status == "verified") if scope is not None else (None, False, False)
        common = {**_ids(ctx), "tool": tool, "effect": effect, "status": status, "code": code, "latencyMs": latency,
                  "specialist": record.get("specialist"), "attempt": attempt, "tenant": _tenant(ctx), "modality": getattr(ctx, "modality", None)}
        if status == "blocked" and code in LEGACY_AUTHZ_CODES:
            emit("agent.authz", **common, outcome="deny", reason=code, mode="legacy")
            _metric("agent.authz", f"legacy:deny:{code}")
        elif tool in PLAN_TOOLS:
            emit("agent.plan", **common)
        elif effect not in (None, "READ"):
            emit("agent.mutation", **common, verified=status == "verified")
        else:
            emit("agent.tool", **common)
        _metric("agent.tool", f"{tool}:{status}", latency)
        if status != "verified":
            _metric("agent.tool.error", f"{tool}:{code or status}")
        if code in PROVIDER_AUTH_CODES:
            provider, reason = PROVIDER_AUTH_CODES[code]
            provider_authorization_failed(provider=provider or _provider_of(tool), reason=reason, ctx=ctx, tool=tool)
        if retried:
            retry("tool_repeat", ctx=ctx, tool=tool)
            if recovered:
                recovery("tool_retry", "recovered", ctx=ctx, tool=tool)
    except Exception:  # noqa: BLE001
        return


def _provider_of(tool) -> str:
    head = str(tool or "").split("_", 1)[0]
    if head in PROVIDERS:
        return head
    return next((p for p in PROVIDERS if str(tool or "").startswith(p + "_")), "other")


def permission_decision(ctx=None, *, outcome, reason=None, mode="enforce", capability_id=None, risk=None, category=None, tool=None, surface=None,
                        would_outcome=None, trace_id=None, run_id=None) -> None:
    """CF-2 §14: one line per authorization decision. In shadow mode the line is `agent.authz.shadow`, `outcome` is what the
    person actually got (allow) and `wouldOutcome` what enforce would have returned. R0 allows are counted, not logged."""
    if not enabled():
        return
    try:
        mode = mode if mode in MODES else "enforce"
        shadow = mode == "shadow"
        decided = code_or(would_outcome if shadow and would_outcome else outcome, "unknown")
        label_reason = code_or(reason, "none")
        _metric("agent.authz", f"{mode}:{decided}:{label_reason}")
        scope = SCOPE.get()
        if scope is not None:
            with scope.lock:
                scope.authz[f"{mode}:{decided}"] = scope.authz.get(f"{mode}:{decided}", 0) + 1
        if decided == "allow" and (risk in (None, "R0")):
            return
        ids = _ids(ctx) if ctx is not None else {"traceId": trace_id, "runId": run_id}
        emit("agent.authz.shadow" if shadow else "agent.authz", **ids, outcome="allow" if shadow else decided, wouldOutcome=decided if shadow else None,
             reason=reason, mode=mode, capabilityId=capability_id, risk=risk, category=category, tool=tool, surface=surface,
             tenant=_tenant(ctx) if ctx is not None else None, shadow=shadow)
    except Exception:  # noqa: BLE001
        return


def provider_authorization_failed(*, provider=None, reason=None, ctx=None, trace_id=None, run_id=None, tool=None) -> None:
    """A provider refused or lost this workspace's authorization (revoked, reconnect needed, scope missing)."""
    if not enabled():
        return
    try:
        provider = provider if provider in PROVIDERS else "other"
        reason = code_or(reason, "unknown")
        _metric("agent.provider_auth", f"{provider}:{reason}")
        scope = SCOPE.get()
        if scope is not None:
            with scope.lock:
                scope.provider_auth += 1
        ids = _ids(ctx) if ctx is not None else {"traceId": trace_id, "runId": run_id}
        emit("agent.provider_auth", **ids, provider=provider, reason=reason, tool=tool, outcome="failed")
    except Exception:  # noqa: BLE001
        return


def retry(kind, *, ctx=None, trace_id=None, run_id=None, tool=None, attempt=None) -> None:
    if not enabled():
        return
    kind = code_or(kind, "other")
    _metric("agent.retry", kind)
    ids = _ids(ctx) if ctx is not None else {"traceId": trace_id, "runId": run_id}
    emit("agent.retry", **ids, kind=kind, tool=tool, attempt=attempt)


def recovery(kind, result, *, ctx=None, trace_id=None, run_id=None, tool=None) -> None:
    """A failure Rafii worked around (a retried tool that then succeeded, a deterministic answer after a model failure, a
    stalled turn closed). `result` is recovered | unrecovered | delivered | closed."""
    if not enabled():
        return
    kind, result = code_or(kind, "other"), code_or(result, "unknown")
    _metric("agent.recovery", f"{kind}:{result}")
    ids = _ids(ctx) if ctx is not None else {"traceId": trace_id, "runId": run_id}
    emit("agent.recovery", **ids, kind=kind, result=result, tool=tool)


def approval_decided(*, surface, outcome, proposal_type=None, wait_ms=None, verified=None, trace_id=None, run_id=None, kind="proposal",
                     code=None, approval_id=None) -> None:
    """A person decided a proposal or approval: how long it waited, on which surface, and whether the re-read matched."""
    if not enabled():
        return
    try:
        surface, outcome = code_or(surface, "other"), code_or(outcome, "unknown")
        _metric("agent.approval", f"{surface}:{outcome}", wait_ms)
        scope = SCOPE.get()
        if scope is not None:
            with scope.lock:
                scope.approvals += 1
        emit("agent.approval", traceId=trace_id, runId=run_id, surface=surface, outcome=outcome, proposalType=proposal_type, waitMs=wait_ms,
             verified=verified, kind=kind, code=code, approvalId=approval_id)
    except Exception:  # noqa: BLE001
        return


def task_event(name, *, trace_id=None, task_id=None, step_key=None, state=None, reason=None, attempt=None, run_id=None, latency_ms=None,
               approval_id=None, capability_id=None) -> None:
    """CF-3 §16: `agent_task.<name>` (created, step_claimed, step_finished, step_reclaimed, approval_requested|decided|expired,
    cancelled, revoked, compensation_applied, tick). Labels are never the plan's text: state and reason codes only."""
    if not enabled() or name not in TASK_EVENTS:
        return
    try:
        _metric("agent.task", f"{name}:{code_or(state or reason, 'none')}", latency_ms)
        emit("agent_task." + name, traceId=trace_id, taskId=task_id, stepKey=step_key, state=state, reason=reason, attempt=attempt, runId=run_id,
             latencyMs=latency_ms, approvalId=approval_id, capabilityId=capability_id)
    except Exception:  # noqa: BLE001
        return


# --- turn lifecycle --------------------------------------------------------------------------------------------------------
def instrument_turn(fn):
    """Decorates AgentRuntimeService.turn: request and response phases, end-to-end latency and the turn's metrics. The wrapped
    call gets exactly its own arguments and its result or exception passes through untouched."""
    @functools.wraps(fn)
    def turn(runtime, workspace_id, token, payload, *args, **kwargs):
        opened = _open(payload)
        try:
            out = fn(runtime, workspace_id, token, payload, *args, **kwargs)
        except BaseException as error:
            _close(runtime, opened, None, error)
            raise
        _close(runtime, opened, out, None)
        return out
    return turn


def _open(payload):
    if not enabled():
        return None
    try:
        payload = payload if isinstance(payload, dict) else {}
        modality = payload.get("modality") if payload.get("modality") in MODALITIES else "text"
        trace = payload.get("traceId") if isinstance(payload.get("traceId"), str) and _TRACE.match(payload["traceId"]) else None
        scope = Scope(modality, trace)
        token = SCOPE.set(scope)
        emit("agent.request", modality=modality, traceId=trace, hasConversation=bool(payload.get("conversationId")),
             attachments=len(payload["attachments"]) if isinstance(payload.get("attachments"), list) else 0,
             delegated=bool(payload.get("delegationId")), command=_command(payload.get("command")))
        return scope, token
    except Exception:  # noqa: BLE001
        return None


def _command(raw):
    """The slash command's name from the allowlist (commands.NAMES), 'other' for anything else; never its arguments."""
    if not isinstance(raw, dict):
        return None
    from .agent_runtime_v2 import commands
    name = raw.get("name")
    return name.strip().lower() if isinstance(name, str) and name.strip().lower() in commands.NAMES else "other"


def _close(runtime, opened, out, error) -> None:
    if opened is None:
        return
    scope, token = opened
    try:
        e2e = round((time.monotonic() - scope.started) * 1000, 1)
        with scope.lock:
            snapshot = dict(scope.snapshot or {})
            authz = dict(scope.authz)
            provider_auth, approvals = scope.provider_auth, scope.approvals
        out = out if isinstance(out, dict) else {}
        result = out.get("result") if isinstance(out.get("result"), dict) else {}
        site_agent = error is None and "fallback" in out and "siteAgent" in out
        if error is not None:
            status_code = getattr(error, "status", None)
            status = "refused" if isinstance(status_code, int) and 400 <= status_code < 500 else "error"
        else:
            status = code_or(out.get("status"), "unknown")
        path = "site_agent" if site_agent else (snapshot.get("path") or "unknown")
        fallback = code_or(out.get("fallback"), None) if site_agent else snapshot.get("fallback")
        trace = out.get("traceId") or result.get("traceId") or scope.trace_id
        run_id = out.get("runId")
        _metric("agent.turn", f"{path}:{status}", e2e)
        if fallback:
            _metric("agent.turn.fallback", fallback)
        counts = dict(snapshot.get("counts") or {})
        if snapshot:
            if snapshot.get("costState") == "known":
                _metric("agent.turn.cost", path, snapshot.get("costUsdMicro"))
            elif snapshot.get("costState") == "unknown":
                _metric("agent.turn.cost", f"{path}:unknown")
            _metric("agent.outcome", snapshot.get("outcome") or "no_change")
            for label in ("verified", "unverified"):
                if counts.get("changes_" + label):
                    _metric("agent.change", label, count=min(int(counts["changes_" + label]), 1000))
            if snapshot.get("genui"):
                _metric("agent.genui", snapshot["genui"])
            if fallback in RECOVERABLE_FALLBACKS and status == "completed":
                recovery("deterministic_answer", "delivered", trace_id=trace, run_id=run_id)
        unrecovered = scope.unrecovered()
        if unrecovered:
            _metric("agent.recovery", "tool_retry:unrecovered", count=min(unrecovered, 1000))
        counts.update({"authz_" + key.replace(":", "_"): value for key, value in authz.items()})
        counts.update({key: value for key, value in (("provider_auth", provider_auth), ("approvals", approvals), ("tool_unrecovered", unrecovered)) if value})
        emit("agent.response", traceId=trace, runId=run_id, path=path, status=status, e2eMs=e2e, fallback=fallback, outcome=snapshot.get("outcome"),
             composedBy=snapshot.get("composedBy") or code_or(result.get("composedBy"), None), costUsdMicro=snapshot.get("costUsdMicro"),
             costState=snapshot.get("costState"), modelRequests=snapshot.get("modelRequests"), tenant=snapshot.get("tenant"), modality=scope.modality,
             errorClass=type(error).__name__ if error is not None else None, httpStatus=getattr(error, "status", None) if error is not None else None,
             code=getattr(error, "code", None) if error is not None else None, counts=counts)
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            SCOPE.reset(token)
        except Exception:  # noqa: BLE001
            pass
        _flush(getattr(runtime, "service", None))


def _flush(service) -> None:
    try:
        from . import agent_metrics
        agent_metrics.maybe_flush(service)
    except Exception:  # noqa: BLE001
        pass


def path_of(trace: dict) -> str:
    """Which runtime path persisted a run, from its own trace keys (service._persist callers)."""
    if "founder" in trace:
        return "founder"
    if "command" in trace:
        return "command"
    if "approval" in trace:
        return "decide"
    if trace.get("fallback") == "turn_stalled":
        return "stalled"
    if trace.get("fallback") == "phone_interrupted":
        return "phone_interrupted"
    if "runtime" in trace or "workload" in trace:
        return "manager"
    if trace.get("fallback") == "internal_error":
        return "aborted"
    return "deterministic"


def outcome_summary(result: dict, trace: dict, status: str) -> dict:
    """Counts and codes of one persisted run: tool outcomes, changes and their verification, approvals, task steps, cost.
    Reads no text field of the result."""
    result = result if isinstance(result, dict) else {}
    trace = trace if isinstance(trace, dict) else {}
    tools = [a for a in result.get("toolActivity") or [] if isinstance(a, dict)]
    counts = {"tools": len(tools)}
    for activity in tools:
        state = activity.get("status") if activity.get("status") in TOOL_STATUSES else "other"
        counts["tools_" + state] = counts.get("tools_" + state, 0) + 1
    mutations = [a for a in tools if a.get("effect") in EFFECTS and a.get("effect") != "READ"]
    changes = [c for c in result.get("changedEntities") or [] if isinstance(c, dict)]
    verified_changes = sum(1 for c in changes if c.get("verified") is True)
    counts.update({"mutations": len(mutations), "mutations_unverified": sum(1 for a in mutations if a.get("status") == "unverified"),
                   "changes_verified": verified_changes, "changes_unverified": len(changes) - verified_changes,
                   "pending_approvals": len(result.get("pendingApprovals") or []), "assets": len(result.get("generatedAssets") or []),
                   "errors": len(result.get("errors") or []), "warnings": len(result.get("warnings") or []),
                   "specialists": len(trace.get("specialists") or []), "guardrails": len(trace.get("guardrails") or []),
                   "interruptions": len(trace.get("interruptions") or [])})
    task = result.get("task") if isinstance(result.get("task"), dict) else None
    if task:
        steps = task.get("counts") if isinstance(task.get("counts"), dict) else {}
        counts.update({"steps_done": int(steps.get("done") or 0), "steps_failed": int(steps.get("failed") or 0),
                       "steps_open": sum(int(steps.get(k) or 0) for k in ("planned", "running", "needs_user", "blocked"))})
    if status == "failed":
        outcome = "failed"
    elif status == "cancelled":
        outcome = "cancelled"
    elif counts["changes_unverified"] or counts["mutations_unverified"]:
        outcome = "unverified"
    elif verified_changes or any(a.get("status") == "verified" for a in mutations):
        outcome = "verified"
    elif counts["pending_approvals"]:
        outcome = "pending_approval"
    else:
        outcome = "no_change"
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cost = usage.get("costUsdMicro")
    billing = usage.get("billing")
    cost_state = "known" if isinstance(cost, int) and not isinstance(cost, bool) else ("scripted" if billing == "scripted" else "unknown" if billing == "metered" else "none")
    ui = result.get("ui") if isinstance(result.get("ui"), dict) else None
    genui = None if ui is None else ("eligible" if ui.get("eligible") else code_or(ui.get("reason"), "not_eligible"))
    codes = sorted({c for c in (code_or((e or {}).get("code"), None) for e in (result.get("errors") or []) if isinstance(e, dict)) if c})[:5]
    return {"path": path_of(trace), "status": code_or(status, "unknown"), "outcome": outcome, "composedBy": code_or(result.get("composedBy"), None),
            "fallback": code_or(trace.get("fallback"), None), "workload": code_or(trace.get("workload"), None), "costUsdMicro": cost if cost_state == "known" else None,
            "costState": cost_state, "modelRequests": usage.get("modelRequests") if isinstance(usage.get("modelRequests"), int) else None,
            "genui": genui, "tenant": "founder" if "founder" in trace else "workspace", "counts": counts, "errorCodes": codes}


def run_persisted(runtime, *, run_id, status, result, trace) -> None:
    """service._persist's last step: the verify phase of one stored run. Inside a turn the summary also feeds the response
    line; a run persisted outside one (a stalled turn closed by the reaper, an interrupted phone call) is recorded alone."""
    if not enabled():
        return
    try:
        summary = outcome_summary(result, trace, status)
        trace_id = (trace or {}).get("traceId") if isinstance(trace, dict) else None
        emit("agent.verify", traceId=trace_id, runId=run_id, path=summary["path"], status=summary["status"], outcome=summary["outcome"],
             composedBy=summary["composedBy"], fallback=summary["fallback"], workload=summary["workload"], tenant=summary["tenant"],
             verified=summary["outcome"] == "verified", counts=summary["counts"], genui=summary["genui"],
             code=summary["errorCodes"][0] if summary["errorCodes"] else None)
        scope = SCOPE.get()
        if summary["path"] in ("stalled", "phone_interrupted"):
            # Another run, closed on the way: a turn the platform killed (reaper) or a phone call that dropped mid-request.
            _metric("agent.run.closed", f"{summary['path']}:{summary['status']}")
            recovery("stalled_turn" if summary["path"] == "stalled" else "interrupted_call", "closed", trace_id=trace_id, run_id=run_id)
        elif scope is not None:
            _learn_trace(scope, trace_id)
            with scope.lock:
                scope.snapshot = summary
            return
        else:
            _metric("agent.run.closed", f"{summary['path']}:{summary['status']}")
            _metric("agent.outcome", summary["outcome"])
        if scope is None:
            _flush(getattr(runtime, "service", None))
    except Exception:  # noqa: BLE001
        return


def instrument_approval(fn):
    """Decorates approvals.decide (panel buttons, a bound typed/spoken yes, cancel's dismiss): approval phase with how long the
    proposal waited and whether the re-read matched. Arguments and result pass through untouched."""
    @functools.wraps(fn)
    def decide(service, *args, **kwargs):
        try:
            out = fn(service, *args, **kwargs)
        except BaseException as error:
            _approval(service, kwargs, None, error)
            raise
        _approval(service, kwargs, out, None)
        return out
    return decide


def _approval(service, kwargs, out, error) -> None:
    if not enabled():
        return
    try:
        scope = SCOPE.get()
        surface = "panel" if scope is None else ("voice" if scope.modality == "voice" else "chat")
        proposal = (out or {}).get("proposal") if isinstance(out, dict) and isinstance(out.get("proposal"), dict) else {}
        created = proposal.get("createdAt")
        if not isinstance(created, (int, float)) and isinstance(proposal.get("expiresAt"), (int, float)):
            # The browser view of a proposal drops createdAt; every proposal lives exactly TTL_SECONDS (site_agent.proposals).
            from .site_agent.proposals import TTL_SECONDS
            created = proposal["expiresAt"] - TTL_SECONDS
        clock = getattr(service, "clock", None)
        now = clock() if callable(clock) else time.time()
        wait = round((now - float(created)) * 1000, 1) if isinstance(created, (int, float)) and not isinstance(created, bool) and now >= created else None
        if error is not None:
            outcome, verified, code = "refused", None, getattr(error, "code", None) or type(error).__name__.lower()
        else:
            outcome = code_or((out or {}).get("outcome"), "unknown")
            verified = (out or {}).get("verified") if isinstance((out or {}).get("verified"), bool) else None
            code = None
        decision = kwargs.get("decision")
        approval_decided(surface=surface, outcome=outcome, proposal_type=proposal.get("type"), wait_ms=wait, verified=verified,
                         trace_id=scope.trace_id if scope is not None else None, kind=decision if decision in ("apply", "dismiss") else "proposal", code=code)
        if scope is None and outcome == "applied" and verified is not None:
            # Panel decisions have no turn result: the applied change's verification is counted here (a turn counts its own).
            _metric("agent.change", "verified" if verified else "unverified")
            _flush(service)
    except Exception:  # noqa: BLE001
        return
