"""Lane F — founder-scoped Generative UI (J09) under /api/control/v2/agent/ui/* (A-DECISIONS D-A22).

Frozen entry point (dispatched by rafii_control.http.ControlApplication.founder, capability `copilot.use`):
- handle(consumer, principal, method, path, body, query, request_id, *, control) -> dict
  Routes: POST presentations | GET presentations/{id} | GET presentations/{id}/events?after= | POST presentations/{id}/cancel |
  POST presentations/{id}/edits | POST presentations/{id}/state | GET messages/{id} | POST queries.
  Founder transport is a blocking POST + polling replay of durable checkpoints (ControlApplication returns one JSON body).
  Founder scope only (`founder:<mode>:<env>` artifacts); read-only manifest; never accepts a client founder flag.

How the scope is established (never from a request field):
1. `founder_agent._prepare` re-verifies the control principal (founder role, AAL2, copilot.use + control.read + metrics.query,
   live session of this environment) and builds the FounderAgentRuntime on the ops workspace through
   `automation_runs.principal_repository` (the capability object is the token; every transaction re-checks membership).
2. The data mode (Live/Demo) of a request is the mode its run or artifact was created in: a founder run's key
   `agent:founder:<mode>:<env>:…`, an artifact's stored scope key. The runtime is then rebuilt for exactly that namespace, so
   `ui_http.ui_transaction` derives scope='founder', scope_key='founder:<mode>:<env>' from `runtime.founder` (server code).
3. Every store read filters by that scope: a consumer artifact is 404 here and a founder artifact is 404 on consumer routes.

Idempotency keys are namespaced per founder scope (`fdr_` + sha256(scope:key)), so a key can never collide with a consumer key
in the ops workspace or with the other data mode. Founder manifests are read-only: there is no actions route here, and the
store refuses a founder revision that names an action.
"""
from __future__ import annotations

import hashlib
import io
import json
import re

from postriff_alpha.domain import AlphaError

from .auth import ControlError

PREFIX = "/agent/ui/"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
# What a founder client may send to create a presentation; `surface` is fixed server-side to 'founder'.
PRESENTATION_KEYS = ("parentRunId", "slot", "idempotencyKey", "retryOfAttemptId", "conversationId")
_FRAME_LIMIT = 2 * 1024 * 1024        # bytes of SSE drained from one blocking founder presentation (source bound + framing)


def scoped_key(scope_key: str, key: str) -> str:
    """The attempt idempotency key of a founder request: deterministic per (founder namespace, client key), within the contract's
    key alphabet, and never equal to a consumer key or to the same key in the other data mode."""
    return "fdr_" + hashlib.sha256(f"{scope_key}:{key}".encode("utf-8")).hexdigest()[:48]


def _uuid(value, what="VALIDATION_FAILED") -> str:
    if not isinstance(value, str) or not _UUID.match(value):
        raise ControlError(what, 400 if what == "VALIDATION_FAILED" else 404)
    return value.lower()


def _routes(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith(PREFIX):
        raise ControlError("SCOPE_DENIED", 404)
    rest = [p for p in path[len(PREFIX):].split("/") if p]
    if not rest:
        raise ControlError("SCOPE_DENIED", 404)
    return rest


class _Scope:
    """One founder request's runtime for exactly one data mode (founder:<mode>:<env>)."""

    def __init__(self, consumer, principal, control, request_id, mode):
        from . import founder_agent
        self.principal, self.ops, self.founder, self.runtime, self.capability = founder_agent._prepare(
            consumer, principal, mode=mode, control=control, context={}, request_id=request_id, values=None)
        self.mode = mode
        self.environment = self.principal["session"]["environment"]
        self.namespace = self.founder["namespace"]
        self.operator = self.principal["operator"]["user_id"]

    def flags(self) -> dict:
        try:
            return self.runtime.cfg.genui_for(self.ops, founder=True)
        except (AttributeError, TypeError):
            return {"enabled": False, "actions": False, "edits": False}

    def transaction(self):
        return self.runtime.service.repository.transaction(self.capability, self.ops)


def _mode_of_namespace(namespace: str, environment: str) -> str | None:
    parts = str(namespace or "").split(":")
    if len(parts) == 3 and parts[0] == "founder" and parts[1] in ("live", "demo") and parts[2] == environment:
        return parts[1]
    return None


def _artifact_mode(scope: _Scope, artifact_id: str) -> str:
    """The data mode an artifact was created in; anything that is not this operator's founder artifact of this environment is
    the same 404 as a missing one."""
    with scope.transaction() as (cur, _row, _principal):
        cur.execute("SELECT scope, scope_key, actor::text FROM public.pr_ui_artifacts WHERE id::text=%s AND workspace_id=%s", (artifact_id, scope.ops))
        row = cur.fetchone()
    mode = _mode_of_namespace(row[1], scope.environment) if row and row[0] == "founder" and row[2] == scope.operator else None
    if mode is None:
        raise ControlError("SOURCE_UNAVAILABLE", 404)
    return mode


def _run_mode(scope: _Scope, run_id: str) -> str:
    from . import founder_agent
    with scope.transaction() as (cur, _row, _principal):
        found = founder_agent._founder_run(cur, scope.ops, run_id, scope.operator)
    if found is None or found[1] != scope.environment:
        raise ControlError("SOURCE_UNAVAILABLE", 404)
    return found[0]


def _message_mode(scope: _Scope, message_id: str) -> str:
    with scope.transaction() as (cur, _row, _principal):
        cur.execute("SELECT run_id::text FROM public.pr_messages WHERE id::text=%s AND workspace_id=%s", (message_id, scope.ops))
        row = cur.fetchone()
    if not row or not row[0]:
        raise ControlError("SOURCE_UNAVAILABLE", 404)
    return _run_mode(scope, row[0])


def drain(iterable) -> dict:
    """Consume a presentation's text/event-stream (the founder transport is one JSON response): run it to its end and keep only
    identity and the terminal event. Durable events were written by the producer, so the polling client already saw progress."""
    buffer, total, first, terminal = b"", 0, None, None
    try:
        for chunk in iterable:
            if not chunk:
                continue
            total += len(chunk)
            if total > _FRAME_LIMIT:
                break
            buffer += chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
            while b"\n\n" in buffer:
                frame, buffer = buffer.split(b"\n\n", 1)
                data = [line[5:].lstrip() for line in frame.split(b"\n") if line.startswith(b"data:")]
                if not data:
                    continue
                try:
                    event = json.loads(b"\n".join(data).decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                if not isinstance(event, dict):
                    continue
                first = first or event
                if event.get("kind") in ("ui.ready", "ui.failed", "ui.canceled", "ui.interrupted"):
                    terminal = event
    finally:
        close = getattr(iterable, "close", None)
        if callable(close):
            close()
    reason = (terminal or {}).get("payload", {}).get("reason") if isinstance((terminal or {}).get("payload"), dict) else None
    return {"artifactId": (terminal or first or {}).get("artifactId"), "attemptId": (terminal or first or {}).get("attemptId"),
            "terminal": {"kind": terminal.get("kind"), "reason": reason if isinstance(reason, str) else None, "seq": terminal.get("seq")} if terminal else None}


def _environ(path: str) -> dict:
    return {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/control/v2" + path, "QUERY_STRING": "", "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""), "rafii.founder": True}


def _start_response(_status, _headers, _exc_info=None):
    return lambda _data: None


def _after(query) -> int:
    raw = (query or {}).get("after", ["0"])
    raw = raw[0] if isinstance(raw, list) and raw else raw
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        raise ControlError("VALIDATION_FAILED", 400) from None
    if value < 0 or value > 10**9:
        raise ControlError("VALIDATION_FAILED", 400)
    return value


def _require(flags: dict, what: str = "enabled"):
    from .founder_agent import PolicyDisabled
    if not flags.get("enabled") or not flags.get(what):
        raise PolicyDisabled("genui_disabled")


def handle(consumer, principal, method, path, body, query, request_id, *, control):
    """Founder Generative UI routes. Returns the `data` of the control envelope (`_dataState` is popped by the dispatcher)."""
    from postriff_phase2.agent_runtime_v2 import ui_contracts as contracts, ui_store
    from . import founder_agent
    rest = _routes(path)
    body = body if isinstance(body, dict) else {}
    if any(k in body for k in ("isFounder", "founder", "scope", "scopeKey", "surface", "mode")) and method == "POST":
        # Scope and surface are server decisions; a client that tries to name them is refused, not ignored.
        raise ControlError("VALIDATION_FAILED", 400)
    try:
        base = _Scope(consumer, principal, control, request_id, "live")
        if rest == ["presentations"] and method == "POST":
            request = contracts.validate_presentation_request({k: body[k] for k in PRESENTATION_KEYS if k in body})
            scope = _Scope(consumer, principal, control, request_id, _run_mode(base, request["parentRunId"]))
            _require(scope.flags())
            request = {**request, "surface": "founder", "idempotencyKey": scoped_key(scope.namespace, request["idempotencyKey"])}
            from postriff_phase2.agent_runtime_v2 import ui_stream
            outcome = drain(ui_stream.create_presentation(scope.runtime, _environ(path), _start_response, scope.ops, scope.capability, request))
            out = {"outcome": outcome, "mode": scope.mode, "namespace": scope.namespace}
            if outcome.get("artifactId"):
                out["view"] = ui_store.snapshot_http(scope.runtime, scope.ops, scope.capability, outcome["artifactId"])
            return {**out, "_dataState": "not_applicable"}
        if rest[0] == "presentations" and len(rest) >= 2:
            artifact_id = _uuid(rest[1], "SOURCE_UNAVAILABLE")
            scope = _Scope(consumer, principal, control, request_id, _artifact_mode(base, artifact_id))
            tail = rest[2:]
            if not tail and method == "GET":
                return {**ui_store.snapshot_http(scope.runtime, scope.ops, scope.capability, artifact_id), "_dataState": "not_applicable"}
            if tail == ["events"] and method == "GET":
                # Polling replay of durable events (no streaming in the control app); never dispatches a provider.
                from postriff_phase2.agent_runtime_v2.ui_http import ui_transaction
                with ui_transaction(scope.runtime, scope.capability, scope.ops, "read") as (cur, auth):
                    replay = ui_store.replay_view(cur, auth, artifact_id, _after(query))
                return {**replay, "_dataState": "not_applicable"}
            if tail == ["cancel"] and method == "POST":
                from postriff_phase2.agent_runtime_v2 import ui_stream
                return {**ui_stream.cancel_http(scope.runtime, scope.ops, scope.capability, artifact_id), "_dataState": "not_applicable"}
            if tail == ["edits"] and method == "POST":
                _require(scope.flags(), "edits")
                request = contracts.validate_patch({k: v for k, v in body.items() if k != "artifactId"}, founder=True)
                request = {**request, "artifactId": artifact_id, "idempotencyKey": scoped_key(scope.namespace, request["idempotencyKey"])}
                from postriff_phase2.agent_runtime_v2 import ui_stream
                outcome = drain(ui_stream.create_edit(scope.runtime, _environ(path), _start_response, scope.ops, scope.capability, artifact_id, request))
                view = ui_store.snapshot_http(scope.runtime, scope.ops, scope.capability, artifact_id)
                return {"outcome": outcome, "view": view, "_dataState": "not_applicable"}
            if tail == ["state"] and method == "POST":
                request = contracts.validate_state_patch(body)
                return {**ui_store.persist_state_http(scope.runtime, scope.ops, scope.capability, artifact_id, request), "_dataState": "not_applicable"}
            raise ControlError("SCOPE_DENIED", 404)
        if rest[0] == "messages" and len(rest) == 2 and method == "GET":
            message_id = _uuid(rest[1], "SOURCE_UNAVAILABLE")
            scope = _Scope(consumer, principal, control, request_id, _message_mode(base, message_id))
            return {**ui_store.by_message_http(scope.runtime, scope.ops, scope.capability, message_id), "_dataState": "not_applicable"}
        if rest == ["queries"] and method == "POST":
            request = contracts.validate_query(body)
            scope = _Scope(consumer, principal, control, request_id, _artifact_mode(base, request["artifactId"]))
            _require(scope.flags())
            from postriff_phase2.agent_runtime_v2 import ui_queries
            result = ui_queries.query_http(scope.runtime, scope.ops, scope.capability, request)
            state = result.get("state") if isinstance(result, dict) else None
            return {**(result if isinstance(result, dict) else {}), "_dataState": "measured" if state == "available" else "partial" if state in ("partial", "stale")
                    else "not_applicable"}
        raise ControlError("SCOPE_DENIED", 404)
    except ui_store.StateConflict:
        # The control envelope carries no body on errors: the client re-reads the snapshot and re-applies its dirty fields.
        raise ControlError("STALE_PREVIEW", 409) from None
    except AlphaError as error:
        raise founder_agent.control_error(error) from None
