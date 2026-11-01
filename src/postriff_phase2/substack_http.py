"""Substack routes inside Rafii's existing authenticated WSGI boundary."""
from postriff_alpha.domain import AlphaError


def handle(app, environ, start_response, service, token, method, parts):
    substack = getattr(service, "substack", None)
    if substack is None or not substack.enabled:
        raise AlphaError("Substack integration is not enabled.", 404, code="feature_disabled")
    workspace_id, tail = parts[2], parts[4:]
    if method == "GET" and tail in (["workspace"], ["capabilities"]):
        call = substack.workspace if tail[0] == "workspace" else substack.capabilities
        return app._json(start_response, 200, call(workspace_id, token))
    if method == "POST" and tail == ["connections"]:
        return app._json(start_response, 200, substack.connect(workspace_id, token, app._body(environ)))
    if method == "POST" and len(tail) == 3 and tail[0] == "connections" and tail[2] in ("disconnect", "refresh"):
        call = substack.disconnect if tail[2] == "disconnect" else substack.refresh
        return app._json(start_response, 200, call(workspace_id, token, tail[1], app._body(environ)))
    if method == "POST" and tail == ["drafts"]:
        return app._json(start_response, 201, substack.save_draft(workspace_id, token, app._body(environ)))
    if method == "PATCH" and len(tail) == 2 and tail[0] == "drafts":
        return app._json(start_response, 200, substack.save_draft(workspace_id, token, app._body(environ), draft_id=tail[1]))
    if method == "DELETE" and len(tail) == 2 and tail[0] == "drafts":
        return app._json(start_response, 200, substack.delete_draft(workspace_id, token, tail[1], app._body(environ)))
    if method == "POST" and len(tail) == 3 and tail[0] == "drafts" and tail[2] in ("approve", "handoff", "cancel"):
        call = {"approve": substack.approve, "handoff": substack.handoff, "cancel": substack.cancel}[tail[2]]
        return app._json(start_response, 200, call(workspace_id, token, tail[1], app._body(environ)))
    # In particular, there are no publish, OAuth-start, callback or token routes.
    raise AlphaError("Substack operation unavailable.", 404, code="unsupported_substack_operation")
