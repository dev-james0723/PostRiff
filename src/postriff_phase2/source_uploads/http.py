"""`/api/workspaces/{workspaceId}/source-uploads/…` (registered in growth_v2_routes.RESOURCES; session-only).

    GET    limits                      ceilings, supported formats and storage/transcription availability (shown before upload)
    GET    ?cursor=&limit=             recent uploads, newest first (25, at most 50)
    POST   (begin)                     {kind, name, mime, bytes, durationSeconds?, idempotencyKey} → upload + signed PUT target
    POST   transcripts                 {name, format: srt|vtt|txt, text, idempotencyKey} → text ready for review
    GET    {id}                        status: upload, job state/reason/progress, quote state, next action
    DELETE {id}                        delete the upload, its text and corrections (a source made from it is kept)
    POST   {id}/commit                 verify the stored file (size, sha256, real type, duration) and queue its job
    POST   {id}/process                run its queued job now, bounded, through the worker's lease
    POST   {id}/cancel                 stop the intake; nothing it produced is kept
    GET    {id}/quote                  transcription cost estimate and ceiling (reads only)
    POST   {id}/transcribe             {maxMilliCredits, idempotencyKey}: accept the quote, reserve credits, queue
    POST   {id}/pages                  {from, to, idempotencyKey}: choose PDF pages when over a limit
    GET    {id}/text                   the text to review (untrusted data) with corrections, flags and coverage
    POST   {id}/text                   {expectedRevision, text, idempotencyKey}: save a correction (new revision)
    POST   {id}/review                 {expectedRevision}: confirm the text was read as it is
    POST   {id}/source                 {idempotencyKey, expectedRevision, title?, originUrl?, confirmReviewed?} → source
"""
from postriff_alpha.domain import AlphaError

from .service import ensure


def _body(app, environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = -1
    return {} if length == 0 else app._body(environ)


def handle(app, environ, start_response, hosted, token, method, parts):
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    ok = lambda value, status=200: app._json(start_response, status, value)  # noqa: E731
    if rest == ["limits"] and method == "GET":
        return ok(service.limits_view(workspace_id, token))
    if not rest:
        if method == "GET":
            return ok(service.list(workspace_id, token, app._query_str(environ, "cursor"), app._query_int(environ, "limit", 25)))
        if method == "POST":
            return ok(service.begin(workspace_id, token, app._body(environ)), 201)
    if rest == ["transcripts"] and method == "POST":
        return ok(service.add_transcript(workspace_id, token, app._body(environ)), 201)
    if len(rest) == 1:
        if method == "GET":
            return ok(service.status(workspace_id, token, rest[0]))
        if method == "DELETE":
            _body(app, environ)
            return ok(service.delete(workspace_id, token, rest[0]))
    if len(rest) == 2:
        upload_id, action = rest
        if method == "GET" and action == "text":
            return ok(service.text(workspace_id, token, upload_id))
        if method == "GET" and action == "quote":
            return ok(service.quote(workspace_id, token, upload_id))
        if method == "POST":
            body = _body(app, environ)
            routes = {
                "commit": lambda: service.commit(workspace_id, token, upload_id, body),
                "process": lambda: service.process(workspace_id, token, upload_id),
                "cancel": lambda: service.cancel(workspace_id, token, upload_id),
                "transcribe": lambda: service.transcribe(workspace_id, token, upload_id, body),
                "pages": lambda: service.select_pages(workspace_id, token, upload_id, body),
                "text": lambda: service.save_text(workspace_id, token, upload_id, body),
                "review": lambda: service.review(workspace_id, token, upload_id, body),
                "source": lambda: service.create_source(workspace_id, token, upload_id, body),
            }
            if action in routes:
                return ok(routes[action](), 201 if action == "source" else 200)
    raise AlphaError("Source upload route unavailable.", 404)
