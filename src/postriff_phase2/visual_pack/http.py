"""`/api/workspaces/{w}/visual-packs/…` (registered in growth_v2_routes.RESOURCES). Session-only; the service derives
workspace and actor authority, runs the flag gate (404 `feature_disabled` while RAFII_VISUAL_PACK_ENABLED is off) and
checks `edit` / `approve`.

GET  visual-packs?cursor=&limit=                      list (25 by default, at most 50)
POST visual-packs                                     prepare from a draft {idempotencyKey, variantId, campaignId?, settings?}
GET  visual-packs/{id}                                read the current revision, its checks, render, facts and handoff options
POST visual-packs/{id}/revisions                      edit → a new revision {idempotencyKey, expectedRevision, slides?, order?,
                                                      caption?, settings?, source?: keep|resplit}
POST visual-packs/{id}/render | accept | export | confirm-used | queue   {expectedRevision, …}
GET  visual-packs/{id}/revisions/{n}/slides/{1-6}      one rendered PNG
GET  visual-packs/{id}/revisions/{n}/export            the assisted-export zip (each download recorded)
"""
from postriff_alpha.domain import AlphaError

from .service import ensure, enabled

_ACTIONS = {"render": "render", "accept": "accept", "export": "export", "confirm-used": "confirm_used", "queue": "queue"}


def _int(value):
    return int(value) if isinstance(value, str) and value.isdigit() and len(value) <= 6 else None


def handle(app, environ, start_response, hosted, token, method, parts):
    if not enabled():
        raise AlphaError("This feature is not available.", 404, code="feature_disabled")
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    if not rest:
        if method == "GET":
            return app._json(start_response, 200, service.list(workspace_id, token, app._query_str(environ, "cursor"), app._query_int(environ, "limit", 25)))
        if method == "POST":
            return app._json(start_response, 201, service.prepare(workspace_id, token, app._body(environ)))
    elif len(rest) == 1 and method == "GET":
        return app._json(start_response, 200, service.get(workspace_id, token, rest[0]))
    elif len(rest) == 2 and method == "POST" and rest[1] == "revisions":
        return app._json(start_response, 201, service.edit(workspace_id, token, rest[0], app._body(environ)))
    elif len(rest) == 2 and method == "POST" and rest[1] in _ACTIONS:
        return app._json(start_response, 200, getattr(service, _ACTIONS[rest[1]])(workspace_id, token, rest[0], app._body(environ)))
    elif len(rest) == 5 and method == "GET" and rest[1] == "revisions" and rest[3] == "slides" and _int(rest[2]) and _int(rest[4]):
        raw, sha = service.slide(workspace_id, token, rest[0], _int(rest[2]), _int(rest[4]))
        start_response("200 OK", [("Content-Type", "image/png"), ("Content-Length", str(len(raw))), ("Cache-Control", "private, max-age=86400"),
                                  ("ETag", f'"{sha}"'), ("X-Content-Type-Options", "nosniff")])
        return [raw]
    elif len(rest) == 4 and method == "GET" and rest[1] == "revisions" and rest[3] == "export" and _int(rest[2]):
        raw, filename = service.download(workspace_id, token, rest[0], _int(rest[2]))
        start_response("200 OK", [("Content-Type", "application/zip"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"),
                                  ("Content-Disposition", f'attachment; filename="{filename}"'), ("X-Content-Type-Options", "nosniff")])
        return [raw]
    raise AlphaError("This visual pack route is unavailable.", 404)
