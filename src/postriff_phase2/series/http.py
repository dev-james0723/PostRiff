"""Routes: /api/workspaces/{w}/series/… (session only; flag RAFII_SERIES_ENABLED, default off → 404 feature_disabled).

GET  series                                         list (limit ≤ 50, cursor, archived=1)
POST series                                         create from an eligible old post or a source (201)
GET  series/candidates                              eligible posts (kind=post, minAgeDays) or sources (kind=source)
GET  series/{id}                                    one series: episodes, coverage, freshness, decisions, next action
POST series/{id}/plan                               plan more episodes (count)
POST series/{id}/status                             active | paused | completed | archived
POST series/{id}/episodes/{eid}/angle               accept | reject | do_not_repeat (level angle | role)
POST series/{id}/episodes/{eid}/approve             approve as the next episode
POST series/{id}/episodes/{eid}/drafts              link an existing draft (acknowledgedWarnings)
GET  series/{id}/episodes/{eid}/drafts/{vid}/check  duplicate refusal or warnings, no change
POST series/{id}/episodes/{eid}/drafts/{vid}/unlink remove a draft from the episode
POST series/{id}/episodes/{eid}/assets              reference a Library image (assetId)
POST series/{id}/episodes/{eid}/assets/{aid}/unlink remove that image reference
POST series/{id}/claims/{cid}                       reviewed | update | remove a fact
POST series/{id}/decisions/{did}/revoke             stop a decision shaping future plans

Every POST carries `idempotencyKey`; every POST on an existing series carries `expectedRevision`.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from . import model as m
from .service import ensure


def _id(value):
    if not m._ID.match(value or ""):
        raise AlphaError("Series route unavailable.", 404)
    return value


def handle(app, environ, start_response, hosted, token, method, parts):
    m.require_enabled()
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    body = app._body(environ) if method == "POST" else None
    status = 200
    if method == "GET" and rest == []:
        value = service.list(workspace_id, token, limit=app._query_int(environ, "limit", 25), cursor=app._query_str(environ, "cursor"),
                             archived=app._query_str(environ, "archived") in ("1", "true"))
    elif method == "POST" and rest == []:
        value = service.create(workspace_id, token, body)
        status = 200 if value.get("replayed") else 201
    elif method == "GET" and rest == ["candidates"]:
        value = service.candidates(workspace_id, token, kind=app._query_str(environ, "kind") or "post", limit=app._query_int(environ, "limit", 25),
                                   cursor=app._query_str(environ, "cursor"), min_age_days=app._query_int(environ, "minAgeDays", m.DEFAULT_MIN_AGE))
    elif method == "GET" and len(rest) == 1:
        value = service.get(workspace_id, token, _id(rest[0]))
    elif method == "POST" and len(rest) == 2 and rest[1] == "plan":
        value = service.plan(workspace_id, token, _id(rest[0]), body)
    elif method == "POST" and len(rest) == 2 and rest[1] == "status":
        value = service.set_status(workspace_id, token, _id(rest[0]), body)
    elif method == "POST" and len(rest) == 4 and rest[1] == "episodes" and rest[3] == "angle":
        value = service.decide(workspace_id, token, _id(rest[0]), _id(rest[2]), body)
    elif method == "POST" and len(rest) == 4 and rest[1] == "episodes" and rest[3] == "approve":
        value = service.approve(workspace_id, token, _id(rest[0]), _id(rest[2]), body)
    elif method == "POST" and len(rest) == 4 and rest[1] == "episodes" and rest[3] == "drafts":
        value = service.link(workspace_id, token, _id(rest[0]), _id(rest[2]), body)
    elif method == "GET" and len(rest) == 6 and rest[1] == "episodes" and rest[3] == "drafts" and rest[5] == "check":
        value = service.draft_check(workspace_id, token, _id(rest[0]), _id(rest[2]), _id(rest[4]))
    elif method == "POST" and len(rest) == 6 and rest[1] == "episodes" and rest[3] == "drafts" and rest[5] == "unlink":
        value = service.unlink(workspace_id, token, _id(rest[0]), _id(rest[2]), _id(rest[4]), body)
    elif method == "POST" and len(rest) == 4 and rest[1] == "episodes" and rest[3] == "assets":
        value = service.link_asset(workspace_id, token, _id(rest[0]), _id(rest[2]), body)
    elif method == "POST" and len(rest) == 6 and rest[1] == "episodes" and rest[3] == "assets" and rest[5] == "unlink":
        value = service.unlink_asset(workspace_id, token, _id(rest[0]), _id(rest[2]), _id(rest[4]), body)
    elif method == "POST" and len(rest) == 3 and rest[1] == "claims":
        value = service.claim(workspace_id, token, _id(rest[0]), _id(rest[2]), body)
    elif method == "POST" and len(rest) == 4 and rest[1] == "decisions" and rest[3] == "revoke":
        value = service.revoke(workspace_id, token, _id(rest[0]), _id(rest[2]), body)
    else:
        raise AlphaError("Series route unavailable.", 404)
    return app._json(start_response, status, value)
