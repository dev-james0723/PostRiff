"""Routes for customer business results (plan G2-OUT), mounted by ``growth_v2_routes``.

Public (before the browser origin guard; the signature or the opaque slug is the only authority):
  POST /api/results/webhook/{connectionId}   signed first-party event (header ``X-Rafii-Signature``)
  GET  /api/l/{slug}                         tracking redirect (302)
Session-only, under /api/workspaces/{w}/results/:
  GET  summary?from=&to=                     per-class summary, coverage, clicks
  GET  events?provenance=&type=&attribution=&status=&cursor=&limit=
  POST events                                declare            POST events/{id}/amend | events/{id}/reverse
  GET  connections                           POST connections   POST connections/{id}/rotate|pause|resume|remove
  GET  links?cursor=&limit=                  POST links         POST links/{id}/disable|enable
Everything answers 404 ``feature_disabled`` while RAFII_RESULTS_ENABLED is off.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from . import service, signing


def ensure(hosted):
    if not hasattr(hosted, "results"):
        hosted.results = service.ResultsService(hosted)
    return hosted.results


def _text(start_response, status, message):
    raw = message.encode()
    start_response(status, [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"),
                            ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("X-Robots-Tag", "noindex, nofollow")])
    return [raw]


def public(app, environ, start_response, method, path):
    if path.startswith(service.WEBHOOK_PREFIX):
        connection_id = path[len(service.WEBHOOK_PREFIX):]
        if method != "POST" or not connection_id or "/" in connection_id:
            return app._json(start_response, 404, {"error": "Not found.", "code": "not_found"})
        if not service.enabled():
            return app._json(start_response, 404, {"error": "Not found.", "code": "feature_disabled"})
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        if length > signing.MAX_BODY_BYTES:   # refused before a single byte is read
            return app._json(start_response, 413, {"error": f"The event must be at most {signing.MAX_BODY_BYTES} bytes.", "code": "result_body_too_large"})
        if length <= 0:
            return app._json(start_response, 400, {"error": "The body must be one JSON object.", "code": "result_payload_invalid"})
        raw = environ["wsgi.input"].read(length)
        delivery = ensure(app._runtime()).ingest(connection_id, environ.get("HTTP_X_RAFII_SIGNATURE"), raw)
        return app._json(start_response, delivery.status, delivery.body, delivery.headers)
    if path.startswith(service.LINK_PREFIX):
        slug = path[len(service.LINK_PREFIX):]
        if method not in ("GET", "HEAD") or not slug or "/" in slug or not service.enabled():
            return _text(start_response, "404 Not Found", "This link isn't available.")
        purpose = environ.get("HTTP_SEC_PURPOSE") or environ.get("HTTP_PURPOSE") or environ.get("HTTP_X_PURPOSE")
        location = ensure(app._runtime()).redirect(slug, method, environ.get("HTTP_USER_AGENT"), purpose)
        if location is None:
            return _text(start_response, "404 Not Found", "This link isn't available.")
        start_response("302 Found", [("Location", location), ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"),
                                     ("X-Robots-Tag", "noindex, nofollow"), ("Content-Length", "0")])
        return [b""]
    return None


def _number(query, key):
    value = query.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except ValueError:
        raise AlphaError(f"Invalid {key}.", 400, code="invalid_request") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise AlphaError(f"Invalid {key}.", 400, code="invalid_request")
    return number


def handle(app, environ, start_response, hosted, token, method, parts):
    service.require_enabled()
    results = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    query = {key: values[0] for key, values in parse_qs(environ.get("QUERY_STRING", "")).items()}
    status = 200
    if method == "GET" and rest == ["summary"]:
        value = results.summary(workspace_id, token, _number(query, "from"), _number(query, "to"))
    elif method == "GET" and rest == ["events"]:
        value = results.events(workspace_id, token, query)
    elif method == "POST" and rest == ["events"]:
        value = results.declare(workspace_id, token, app._body(environ))
        status = 200 if value.get("replayed") else 201
    elif method == "POST" and len(rest) == 3 and rest[0] == "events" and rest[2] in ("amend", "reverse"):
        act = results.amend if rest[2] == "amend" else results.reverse
        value = act(workspace_id, token, rest[1], app._body(environ))
    elif method == "GET" and rest == ["connections"]:
        value = results.connections(workspace_id, token)
    elif method == "POST" and rest == ["connections"]:
        value = results.create_connection(workspace_id, token, app._body(environ))
        status = 200 if value.get("replayed") else 201
    elif method == "POST" and len(rest) == 3 and rest[0] == "connections" and rest[2] in ("rotate", "pause", "resume", "remove"):
        value = results.connection_action(workspace_id, token, rest[1], rest[2], app._body(environ))
    elif method == "GET" and rest == ["links"]:
        value = results.links(workspace_id, token, query)
    elif method == "POST" and rest == ["links"]:
        value = results.create_link(workspace_id, token, app._body(environ))
        status = 200 if value.get("replayed") else 201
    elif method == "POST" and len(rest) == 3 and rest[0] == "links" and rest[2] in ("disable", "enable"):
        value = results.link_action(workspace_id, token, rest[1], rest[2], app._body(environ))
    else:
        raise AlphaError("Results route unavailable.", 404)
    return app._json(start_response, status, value)
