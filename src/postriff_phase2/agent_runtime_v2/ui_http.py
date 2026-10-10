"""HTTP seam of Rafii Generative UI under /api/workspaces/{id}/agent/ui/ (A-owned; 02-CONTRACTS §3-4).

Reached from agent_runtime_v2/http.py when `parts[4] == "ui"`, i.e. after hosted_app has applied the API-token refusal,
the request guard and Origin check, and resolved the bearer session token. This module only routes; it never decides
authority. Each handler opens its own short `ui_transaction` (verified session, active membership, workspace row lock)
and the lane module behind it re-checks the requirement class it needs.

    POST presentations                       B  ui_stream.create_presentation   (text/event-stream)
    GET  presentations/{a}                   F  ui_store.snapshot_http
    GET  presentations/{a}/events?after=     B  ui_stream.replay                (text/event-stream; never dispatches a provider)
    POST presentations/{a}/cancel            B  ui_stream.cancel_http
    POST presentations/{a}/edits             B  ui_stream.create_edit           (text/event-stream; explicit, metered)
    POST presentations/{a}/state             F  ui_store.persist_state_http
    GET  messages/{m}                        F  ui_store.by_message_http        (artifact refs of one assistant message)
    POST queries                             D  ui_queries.query_http
    POST actions/activate                    D  ui_actions.activate_http
    POST actions                             D  ui_actions.execute_http
    GET  diagnostics/stream                  B  ui_stream.probe                 (three spaced frames, zero model cost)

Kill switch: when RAFII_GENUI_ENABLED is off (or the workspace is outside the canary allowlist) every route answers 404
`ui_disabled` except snapshot/by-message/replay/state, which keep serving already persisted artifacts read-only so old
messages still show their native fallback; queries and actions are refused (no new data or writes while disabled).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

from postriff_alpha.domain import AlphaError

from . import ui_contracts as contracts


@dataclass(frozen=True)
class UiAuth:
    """The authenticated caller of one UI request. `principal` comes from the verified session, never from a body."""
    workspace_id: str
    principal: str
    member: object                 # permissions.Membership
    role: str
    scope: str = "workspace"       # 'workspace' | 'founder'
    scope_key: str = ""            # '' for workspace; 'founder:<mode>:<env>' for founder artifacts
    workspace_revision: int | None = None
    grants: object = None
    config: object = None
    authz_mode: str = "off"
    authz_state: dict = field(default_factory=dict, repr=False)
    now: float | None = None

    def allows(self, requirement: str) -> bool:
        return bool(self.member.allows(requirement))


@contextmanager
def ui_transaction(runtime, token, workspace_id, need: str = "read"):
    """One short authorized transaction: verified session + active membership + workspace row lock (hosted.transaction).
    Never hold it across provider I/O. Yields (cur, UiAuth)."""
    from ..permissions import require
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        member = runtime.service.ideas._member(row)
        require(member, need)
        # Founder scope is decided by server code only: the founder route family runs with a FounderAgentRuntime whose
        # `.founder` namespace (founder:<mode>:<env>) it built from the verified control principal. Never from a client field.
        founder = getattr(runtime, "founder", None)
        scope, scope_key = ("founder", str(founder.get("namespace") or "")) if isinstance(founder, dict) and founder.get("namespace") else ("workspace", "")
        from . import authz
        mode = "off" if scope == "founder" else authz.mode_for(runtime.cfg, workspace_id)
        at = runtime.clock() if callable(getattr(runtime, "clock", None)) else __import__("time").time()
        grants = None
        if mode != "off":
            try:
                grants = authz.load_grants(cur, workspace_id, str(principal), now=at, mode=mode)
            except Exception as error:
                if mode == "enforce":
                    raise authz.AuthzError("Rafii's permissions could not be checked.", "agent_permission_denied") from error
        yield cur, UiAuth(workspace_id=workspace_id, principal=str(principal), member=member, role=getattr(member, "role", "") or "",
                          scope=scope, scope_key=scope_key, workspace_revision=row[0] if row else None,
                          grants=grants, config=runtime.cfg, authz_mode=mode, authz_state=runtime.service.ideas._state(row) if mode != "off" else {}, now=at)


def flags_for(runtime, workspace_id) -> dict:
    return runtime.cfg.genui_for(workspace_id)


def _require_enabled(runtime, workspace_id, what: str = "enabled") -> dict:
    flags = flags_for(runtime, workspace_id)
    if not flags.get(what):
        raise AlphaError("Interactive views are not available here.", 404, code="ui_disabled")
    return flags


def _artifact_id(value) -> str:
    if not contracts.valid_uuid(value):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    return value


def _after(app, environ) -> int:
    after = app._query_int(environ, "after", 0) if hasattr(app, "_query_int") else 0
    header = contracts.parse_event_id(environ.get("HTTP_LAST_EVENT_ID"))
    return max(int(after or 0), int(header or 0))


def _body(app, environ) -> dict:
    """JSON body with the UI-specific outer cap applied before parsing per-field bounds."""
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > contracts.BOUNDS["requestBodyBytes"]:
        raise AlphaError("This request is too large.", 413, code="ui_body_too_large")
    return app._body(environ)


def handle(app, environ, start_response, runtime, token, method, workspace_id, rest):
    """Dispatch `rest` (path parts after `/agent/ui/`). Returns a WSGI iterable."""
    from . import ui_actions, ui_queries, ui_store, ui_stream
    head = rest[:1]
    if head == ["presentations"]:
        if len(rest) == 1 and method == "POST":
            _require_enabled(runtime, workspace_id)
            return ui_stream.create_presentation(runtime, environ, start_response, workspace_id, token, contracts.validate_presentation_request(_body(app, environ)))
        if len(rest) >= 2:
            artifact_id = _artifact_id(rest[1])
            tail = rest[2:]
            if not tail and method == "GET":
                return app._json(start_response, 200, ui_store.snapshot_http(runtime, workspace_id, token, artifact_id))
            if tail == ["events"] and method == "GET":
                return ui_stream.replay(runtime, environ, start_response, workspace_id, token, artifact_id, _after(app, environ))
            if tail == ["cancel"] and method == "POST":
                _body_optional(app, environ)
                return app._json(start_response, 200, ui_stream.cancel_http(runtime, workspace_id, token, artifact_id))
            if tail == ["edits"] and method == "POST":
                _require_enabled(runtime, workspace_id, "edits")
                return ui_stream.create_edit(runtime, environ, start_response, workspace_id, token, artifact_id, contracts.validate_patch(_body(app, environ)))
            if tail == ["state"] and method == "POST":
                try:
                    saved = ui_store.persist_state_http(runtime, workspace_id, token, artifact_id, contracts.validate_state_patch(_body(app, environ)))
                except ui_store.StateConflict as conflict:
                    # 409 with the stored state so the other tab merges its dirty fields (02-CONTRACTS §5); nothing was overwritten.
                    return app._json(start_response, 409, {"error": str(conflict), "code": conflict.code, "current": conflict.current})
                return app._json(start_response, 200, saved)
    if head == ["messages"] and len(rest) == 2 and method == "GET":
        if not contracts.valid_uuid(rest[1]):
            raise AlphaError("That message is unavailable.", 404, code="ui_message")
        return app._json(start_response, 200, ui_store.by_message_http(runtime, workspace_id, token, rest[1]))
    if rest == ["queries"] and method == "POST":
        _require_enabled(runtime, workspace_id)
        return app._json(start_response, 200, ui_queries.query_http(runtime, workspace_id, token, contracts.validate_query(_body(app, environ))))
    if rest == ["actions", "activate"] and method == "POST":
        _require_enabled(runtime, workspace_id, "actions")
        return app._json(start_response, 201, ui_actions.activate_http(runtime, workspace_id, token, contracts.validate_activation(_body(app, environ))))
    if rest == ["actions"] and method == "POST":
        _require_enabled(runtime, workspace_id, "actions")
        return app._json(start_response, 200, ui_actions.execute_http(runtime, workspace_id, token, contracts.validate_action(_body(app, environ))))
    if rest == ["diagnostics", "stream"] and method == "GET":
        return ui_stream.probe(runtime, environ, start_response, workspace_id, token)
    raise AlphaError("This hosted route is unavailable.", 404)


def _body_optional(app, environ) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    return _body(app, environ) if length else {}
