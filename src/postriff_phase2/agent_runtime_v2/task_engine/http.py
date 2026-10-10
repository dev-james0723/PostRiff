"""Task Center routes under /api/workspaces/{w}/agent/ (CF-3 §17.1). Session token only (checked by the agent route before this
module is reached), same Origin and guard checks, zero model calls on list/get/diagnostics.

    GET  tasks?view=&scope=&limit=&cursor=       the caller's tasks ('mine' by default; owners may ask for the workspace)
    POST tasks/{task}/cancel                     the creator or an owner-class member
    POST tasks/{task}/steps/{step}/retry         the creator; 202
    POST tasks/{task}/steps/{step}/undo          the creator
    POST tasks/{task}/continue                   the creator; 201
    GET  tasks/{task}/diagnostics                the creator or an owner-class member; content-free
    POST approvals/{approvalId}/decide           the one decision route for every engine approval

`handle` returns None when the engine is off for the workspace or the path is not one of these, so the caller's existing routes
(`GET tasks/{task}`, the legacy `POST approvals/decide`) and its 404 answer exactly as today.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from . import actions, approvals, errors, flags, store, views


def _query(environ) -> dict:
    parsed = parse_qs(environ.get("QUERY_STRING") or "", keep_blank_values=False)
    return {k: v[-1] for k, v in parsed.items() if v}


def handle(app, environ, start_response, runtime, token, method, workspace_id, resource, rest):
    if resource not in ("tasks", "approvals") or not flags.enabled_for(workspace_id, getattr(runtime, "cfg", None)):
        return None
    request_id = environ.get("postriff.request_id")
    if resource == "approvals":
        if len(rest) == 2 and rest[1] == "decide" and rest[0] != "decide" and method == "POST":
            body = app._body(environ)
            surface = body.get("surface") if isinstance(body, dict) and body.get("surface") in ("panel", "task_center", "genui") else "task_center"
            return app._json(start_response, 200, approvals.resolve_approval(runtime, workspace_id, token, rest[0], body, surface=surface))
        return None
    if not rest and method == "GET":
        query = _query(environ)
        try:
            limit = int(query.get("limit") or 20)
        except ValueError:
            raise errors.AlphaError("Choose a limit from 1 to 50.", 400) from None
        with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = runtime.service.ideas._member(row)
            body = views.list_tasks(cur, workspace_id, principal, member, view=query.get("view") or "open", scope=query.get("scope") or "mine", limit=limit,
                                    cursor=query.get("cursor"))
        return app._json(start_response, 200, body)
    if len(rest) == 2 and rest[1] == "cancel" and method == "POST":
        return app._json(start_response, 200, actions.cancel(runtime, workspace_id, token, rest[0], app._body(environ)))
    if len(rest) == 2 and rest[1] == "continue" and method == "POST":
        return app._json(start_response, 201, actions.continue_task(runtime, workspace_id, token, rest[0], app._body(environ), request_id=request_id))
    if len(rest) == 2 and rest[1] == "diagnostics" and method == "GET":
        with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            task = store.load_task(cur, workspace_id, rest[0])
            if task is None:
                raise errors.error("task_unavailable")
            return app._json(start_response, 200, views.diagnostics(cur, task, principal, runtime.service.ideas._member(row)))
    if len(rest) == 4 and rest[1] == "steps" and method == "POST":
        if rest[3] == "retry":
            return app._json(start_response, 202, actions.retry(runtime, workspace_id, token, rest[0], rest[2], app._body(environ), request_id=request_id))
        if rest[3] == "undo":
            return app._json(start_response, 200, actions.undo(runtime, workspace_id, token, rest[0], rest[2], app._body(environ)))
    return None


def engine_block(runtime, cur, workspace_id: str, task_id: str, principal: str, member) -> dict | None:
    """The `engine` key of the existing GET tasks/{task} response (None when the engine is off: the key is then absent)."""
    if not flags.enabled_for(workspace_id, getattr(runtime, "cfg", None)):
        return None
    task = store.load_task(cur, workspace_id, task_id)
    if task is None:
        return {"state": "untracked"}
    return views.engine_block(cur, task, principal, member, config=getattr(runtime, "cfg", None))
