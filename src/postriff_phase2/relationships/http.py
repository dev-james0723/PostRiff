"""``/api/workspaces/{w}/relationships/…`` (registered in ``growth_v2_routes.RESOURCES``). Session-only; the flag answers
404 ``feature_disabled`` before anything else, so the web hides the feature.

    GET    /relationships                              list (state, due, owner, thread, cursor, limit)
    POST   /relationships                              create (idempotencyKey; optional threadId)
    GET    /relationships/{id}                         detail: linked threads, suggestion, history
    PATCH  /relationships/{id}                         name, contact, interest, next action, due
    POST   /relationships/{id}/transition              {to, wonResultId?, suggestionKey?}
    POST   /relationships/{id}/reopen                  undo close / won
    POST   /relationships/{id}/snooze | /unsnooze
    POST   /relationships/{id}/assign                  {ownerId | null}
    POST   /relationships/{id}/threads                 {threadId}            DELETE /relationships/{id}/threads/{threadId}
    POST   /relationships/{id}/notes                   {text}                DELETE /relationships/{id}/notes/{noteId}
    POST   /relationships/{id}/dismiss-followup | /restore-followup | /dismiss-suggestion
Every change takes ``expectedRevision``; creates take ``idempotencyKey``.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from . import service as relationships

QUERY_KEYS = ("state", "due", "owner", "thread", "cursor", "limit")
ACTIONS = {
    "transition": "transition", "reopen": "reopen", "snooze": "snooze", "unsnooze": "unsnooze", "assign": "assign",
    "threads": "link_thread", "notes": "add_note", "dismiss-followup": "dismiss_followup", "restore-followup": "restore_followup",
    "dismiss-suggestion": "dismiss_suggestion",
}


def ensure(hosted):
    if getattr(hosted, "relationships", None) is None:
        hosted.relationships = relationships.RelationshipService(hosted)
    return hosted.relationships


def _query(environ):
    parsed = parse_qs(environ.get("QUERY_STRING", ""))
    return {key: parsed[key][0] for key in QUERY_KEYS if parsed.get(key)}


def handle(app, environ, start_response, hosted, token, method, parts):
    relationships.require_enabled()
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    status = 200
    if not rest and method == "GET":
        value = service.list(workspace_id, token, _query(environ))
    elif not rest and method == "POST":
        value = service.create(workspace_id, token, app._body(environ))
        status = 200 if value.get("replayed") else 201
    elif len(rest) == 1 and method == "GET":
        value = service.detail(workspace_id, token, rest[0])
    elif len(rest) == 1 and method == "PATCH":
        value = service.update(workspace_id, token, rest[0], app._body(environ))
    elif len(rest) == 2 and method == "POST" and rest[1] in ACTIONS:
        value = getattr(service, ACTIONS[rest[1]])(workspace_id, token, rest[0], app._body(environ))
    elif len(rest) == 3 and method == "DELETE" and rest[1] == "threads":
        value = service.unlink_thread(workspace_id, token, rest[0], rest[2], app._body(environ))
    elif len(rest) == 3 and method == "DELETE" and rest[1] == "notes":
        value = service.remove_note(workspace_id, token, rest[0], rest[2], app._body(environ))
    else:
        raise AlphaError("Relationship route unavailable.", 404)
    return app._json(start_response, status, value)
