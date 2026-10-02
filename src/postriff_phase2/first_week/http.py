"""`/api/workspaces/{id}/first-week/…` — session-only (API tokens never reach program routes)."""
from postriff_alpha.domain import AlphaError

from .service import FirstWeekService


def ensure(hosted):
    if getattr(hosted, "first_week", None) is None:
        hosted.first_week = FirstWeekService(hosted)
    return hosted.first_week


def handle(app, environ, start_response, hosted, token, method, parts):
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    if method == "GET" and rest == []:
        value = service.view(workspace_id, token)
    elif method == "POST" and rest == ["continuations"]:
        value = service.import_continuation(workspace_id, token, app._body(environ))
    elif method == "POST" and rest == ["start"]:
        value = service.start_from_text(workspace_id, token, app._body(environ))
    elif method == "POST" and rest == ["context"]:
        value = service.set_context(workspace_id, token, app._body(environ))
    elif method == "POST" and rest == ["accept"]:
        value = service.accept_draft(workspace_id, token, app._body(environ))
    elif method == "POST" and rest == ["plan"]:
        value = service.plan(workspace_id, token, app._body(environ))
    elif method == "POST" and rest == ["scope"]:
        value = service.approve_scope(workspace_id, token, app._body(environ))
    elif method == "POST" and rest == ["draft"]:
        value = service.draft_week(workspace_id, token, app._body(environ))
    elif method == "POST" and len(rest) == 3 and rest[0] == "slots" and rest[2] in ("write", "handoff"):
        body = {**app._body(environ), "slotId": rest[1]}
        value = service.write_slot(workspace_id, token, body) if rest[2] == "write" else service.handoff(workspace_id, token, body)
    else:
        raise AlphaError("First-week route unavailable.", 404)
    return app._json(start_response, 200, value)
