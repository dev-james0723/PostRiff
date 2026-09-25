"""HTTP routes of the Agent Runtime under /api/workspaces/{id}/agent/ (spec §26).

Mounted by hosted_app with the same session, request guard, origin checks and JSON conventions as every other route
(the handler receives the application's own `_json` / `_body` helpers). API tokens have no agent scope.

    GET  status                              flags, routes, voice availability (never a credential)
    POST turns                               one Rafii turn (text | voice | image); 201
    GET  runs/{run}                          the stored surface-neutral result of a turn
    POST runs/{run}/cancel                   stop a running turn before its next change
    GET  conversations/{c}/state             active task, conversation images, pending approvals
    GET  tasks/{task}?cursor=                task plan + step events (cursor replay)
    POST approvals/decide                    apply | dismiss an agent proposal (site agent apply path + verification)
    POST attachments                         add an image to the conversation (private media path)
    POST voice/sessions                      start GPT-Live: SDP offer in, SDP answer out (server-held key)
    POST voice/sessions/{v}/transcript       text of what was said (no audio)
    POST voice/sessions/{v}/end              end and settle the session
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def runtime_for(service):
    """One runtime per hosted service, created on first use (the SDK is imported only when the agent is used)."""
    runtime = getattr(service, "_agent_runtime_v2", None)
    if runtime is None:
        from .service import AgentRuntimeService
        runtime = AgentRuntimeService(service)
        service._agent_runtime_v2 = runtime
    return runtime


def handle(app, environ, start_response, service, token, method, parts):
    from . import service as runtime_service
    from .api_guard import require_session_token
    require_session_token(token)
    workspace_id, resource = parts[2], parts[4]
    runtime = runtime_for(service)
    rest = parts[5:]
    if resource == "status" and not rest and method == "GET":
        return app._json(start_response, 200, runtime.status(workspace_id, token))
    if resource == "turns" and not rest and method == "POST":
        return app._json(start_response, 201, runtime.turn(workspace_id, token, app._body(environ)))
    if resource == "runs" and len(rest) == 1 and method == "GET":
        with service.repository.transaction(token, workspace_id) as (cur, row, _principal):
            from ..permissions import require
            require(service.ideas._member(row), "read")
            return app._json(start_response, 200, runtime._stored(cur, workspace_id, rest[0]))
    if resource == "runs" and len(rest) == 2 and rest[1] == "cancel" and method == "POST":
        app._body(environ)
        return app._json(start_response, 200, runtime.cancel(workspace_id, token, rest[0]))
    if resource == "conversations" and len(rest) == 2 and rest[1] == "state" and method == "GET":
        return app._json(start_response, 200, runtime_service.conversation_task(runtime, workspace_id, token, rest[0]))
    if resource == "tasks" and len(rest) == 1 and method == "GET":
        return app._json(start_response, 200, runtime_service.task_view(runtime, workspace_id, token, rest[0], app._query_int(environ, "cursor")))
    if resource == "approvals" and rest == ["decide"] and method == "POST":
        return app._json(start_response, 200, runtime_service.decide(runtime, workspace_id, token, app._body(environ)))
    if resource == "attachments" and not rest and method == "POST":
        return app._json(start_response, 201, runtime_service.attach_upload(runtime, workspace_id, token, app._body(environ)))
    if resource == "voice" and rest[:1] == ["sessions"] and method == "POST":
        from .live import VoiceSessions
        voice = VoiceSessions(runtime, transport=runtime.live_transport)
        if len(rest) == 1:
            return app._json(start_response, 201, voice.start(workspace_id, token, app._body(environ)))
        if len(rest) == 3 and rest[2] == "transcript":
            return app._json(start_response, 200, voice.transcript(workspace_id, token, rest[1], app._body(environ)))
        if len(rest) == 3 and rest[2] == "end":
            return app._json(start_response, 200, voice.end(workspace_id, token, rest[1], app._body(environ)))
    raise AlphaError("This hosted route is unavailable.", 404)
