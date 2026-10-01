"""Routes under ``/api/workspaces/{id}/briefs`` (registered in ``growth_v2_routes.RESOURCES``).

GET  …/briefs/current                       this person's brief, composed from stored evidence (no writes, no research)
GET  …/briefs/editions?cursor=&limit=       stored editions for this person (25 by default, at most 50)
GET  …/briefs/editions/{editionId}          one stored edition with its actions
POST …/briefs/items/{itemId}/action         accept | save_idea | dismiss | not_relevant | restore (idempotent)

Session tokens only; the workspace id in the path selects, the repository transaction authorizes.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from . import require as require_enabled


def ensure(hosted):
    if getattr(hosted, "briefs", None) is None:
        from .service import BriefService
        hosted.briefs = BriefService(hosted)
    return hosted.briefs


def _query(environ, key):
    return (parse_qs(environ.get("QUERY_STRING", "")).get(key) or [None])[0]


def handle(app, environ, start_response, hosted, token, method, parts):
    require_enabled()
    if str(token).startswith("prt_"):
        raise AlphaError("API tokens can't use Rafii briefs.", 403)
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    if method == "GET" and rest == ["current"]:
        return app._json(start_response, 200, service.current(workspace_id, token))
    if method == "GET" and rest == ["editions"]:
        return app._json(start_response, 200, service.history(workspace_id, token, _query(environ, "cursor"), _query(environ, "limit")))
    if method == "GET" and len(rest) == 2 and rest[0] == "editions":
        return app._json(start_response, 200, service.edition(workspace_id, token, rest[1]))
    if method == "POST" and len(rest) == 3 and rest[0] == "items" and rest[2] == "action":
        return app._json(start_response, 200, service.action(workspace_id, token, rest[1], app._body(environ)))
    raise AlphaError("Brief route unavailable.", 404)
