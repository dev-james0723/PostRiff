"""HTTP routes for Rafii agent permissions under /api/workspaces/{id}/agent/permissions (rafii-agent-authz/1, CF-2 §16).

Mounted by agent_runtime_v2/http.py behind the same session-only guard, request guard and Origin check as every agent
route (API tokens never reach here). Each route runs in `repository.transaction`, which re-reads the membership and
locks the workspace row, so a change and an in-flight tool effect serialize. A person reads and writes only their own
row; owners and admins may read who chose what, and a member's change history.

    GET  permissions                     the signed-in person's choices, their effect, presets, copy and reminder
    PUT  permissions                     choose a preset or custom scopes (confirmation for widening, step-up for Full)
    POST permissions/revoke              turn scopes off, or everything (narrowing only)
    POST permissions/reminder            the reminder was shown or set aside ("Not now" stores only this)
    GET  permissions/history             own receipts, newest first (?cursor=&limit=; owners/admins: &member=<userId>)
    GET  permissions/members             owners and admins: each member's current choice

With the permissions mode off for the workspace, every route answers 404 `agent_permissions_unavailable`.
"""
from __future__ import annotations

import re
import time

from postriff_alpha.domain import AlphaError

from ..permissions import require
from . import agent_permissions, authz

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _now(service) -> float:
    clock = getattr(service, "clock", None)
    return float(clock()) if callable(clock) else time.time()


def handle(app, environ, start_response, runtime, token, method, workspace_id, rest):
    try:
        return app._json(start_response, *_route(app, environ, runtime, token, method, workspace_id, rest))
    except authz.AuthzError as error:
        return app._json(start_response, error.status, error.body())


def _route(app, environ, runtime, token, method, workspace_id, rest):
    mode = authz.mode_for(runtime.cfg, workspace_id)
    if mode == "off":
        raise agent_permissions.unavailable()
    service = runtime.service
    body = app._body(environ) if method in ("PUT", "POST") else None
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        member = service.ideas._member(row)
        require(member, "read")
        state = service.ideas._state(row)
        now = _now(service)
        if not rest and method == "GET":
            return 200, agent_permissions.view(cur, workspace_id, principal, member, state, mode=mode, now=now)
        if not rest and method == "PUT":
            def step_up():
                return authz.require_step_up(service.repository, token, principal, now=now, window=authz.R3_REAUTH_SECONDS,
                                             reason="full" if (body or {}).get("preset") == "full" else "sensitive_assist")
            receipt = agent_permissions.apply_decision(cur, workspace_id=workspace_id, principal=principal, member=member, state=state, token=token,
                                                       payload=body, now=now, step_up=step_up, mode=mode)
            return 200, {**agent_permissions.view(cur, workspace_id, principal, member, state, mode=mode, now=now), "receipt": receipt}
        if rest == ["revoke"] and method == "POST":
            receipt = agent_permissions.revoke(cur, workspace_id=workspace_id, principal=principal, member=member, state=state, token=token,
                                               payload=body, now=now, mode=mode)
            return 200, {**agent_permissions.view(cur, workspace_id, principal, member, state, mode=mode, now=now), "receipt": receipt}
        if rest == ["reminder"] and method == "POST":
            return 200, agent_permissions.remind(cur, workspace_id=workspace_id, principal=principal, token=token, payload=body, now=now)
        if rest == ["history"] and method == "GET":
            subject = app._query_str(environ, "member") or principal
            if subject != principal:
                if not isinstance(subject, str) or not _UUID.match(subject):
                    raise AlphaError("Invalid member.", 400)
                require(member, "manage_members")
            limit = app._query_int(environ, "limit", agent_permissions.HISTORY_LIMIT)
            return 200, agent_permissions.history(cur, workspace_id, subject, viewer=principal, cursor=app._query_str(environ, "cursor"), limit=limit)
        if rest == ["members"] and method == "GET":
            require(member, "manage_members")
            return 200, agent_permissions.members_overview(cur, workspace_id)
    raise AlphaError("This hosted route is unavailable.", 404)
