"""Draft edit route (brand intelligence spec 5.4): POST /api/workspaces/{workspaceId}/drafts/{variantId}/edits.

`handle` maps a request to `DraftEdits.request` and returns its body, or None when the path is not a route; `respond`
is the glue hosted_app.py calls. The route answers 404 `feature_disabled` unless POSTRIFF_DRAFT_EDITS mounted the
service (`service.draft_edits`, draft_edits.mount). The role (edit) is checked by DraftEdits.request inside the
workspace transaction, before any run, conversation or model call exists.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _disabled():
    return AlphaError("One-click draft edits are not enabled.", 404, code="feature_disabled")


def handle(service, workspace_id, token, parts, method, body, query):
    """`parts` is the path below /drafts (a list: the draft id, then "edits"); `body` the parsed JSON body or None;
    `query` the parsed query string (unused: the route reads its body only). Returns the response body, or None when
    this is not a draft edit route."""
    edits = getattr(service, "draft_edits", None)
    if edits is None:
        raise _disabled()
    parts = list(parts or [])
    if len(parts) == 2 and parts[1] == "edits" and parts[0] and method == "POST":
        return edits.request(workspace_id, token, parts[0], body)
    return None


def respond(app, environ, start_response, service, token, method, parts):
    """hosted_app.py: refuse while the flag is off (before reading anything), read the body, dispatch, answer."""
    if getattr(service, "draft_edits", None) is None:
        raise _disabled()
    rest = parts[4:]
    body = app._body(environ) if method == "POST" else None
    result = handle(service, parts[2], token, rest, method, body, None)
    if result is None:
        raise AlphaError("This hosted route is unavailable.", 404)
    return app._json(start_response, 200, result)
