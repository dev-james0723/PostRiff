"""Voice import routes (spec 5.1), under /api/workspaces/{workspaceId}/voice-imports.

`handle` maps a request to the importer and returns its body, or None when the path is not a route; `status_code`
says which answers are 202; `respond` is the glue hosted_app.py calls. Every route answers 404 `feature_disabled`
unless POSTRIFF_VOICE_IMPORT mounted the importer (`service.voice_import`). Roles are enforced by the importer inside
the workspace transaction: reading is for members, importing needs manage_connections, correcting a post needs edit.

The analysis route belongs to the corpus analysis service (voice_corpus.VoiceCorpusAnalysis, owner only): it is used
when one is mounted as `service.<ANALYSIS_ATTRIBUTE>`, with `status`, `quote` and `start`. A quote is answered as
`{quote}`, a start as the service's `{analysis}` (202), and `GET /voice-imports` carries the service's status fields
(`analysis`, `analyses`) at its top level, or `analysis: null` when no analysis service is mounted.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from . import voice_import

ANALYSIS_ATTRIBUTE = "voice_corpus_analysis"
POST_FILTERS = ("provider", "accountKey", "status", "cursor", "ids")
_NOT_AN_IMPORT = ("posts", "analysis")


def _disabled():
    return AlphaError("Voice import is not enabled.", 404, code="feature_disabled")


def _analysis(service, workspace_id, token, body):
    analysis = getattr(service, ANALYSIS_ATTRIBUTE, None)
    if analysis is None:
        raise AlphaError("AI analysis of imported posts is not available here.", 404, code="voice_analysis_unavailable")
    group, quote, quote_id = (body.get("groupKey"), body.get("quote"), body.get("quoteId")) if isinstance(body, dict) else (5, None, None)
    if group is not None and not isinstance(group, str):
        raise AlphaError("Choose the voice to analyse.", 400)
    if quote is True and quote_id is None:
        return {"quote": analysis.quote(workspace_id, token, group)}           # the service returns the bare quote
    if quote is None and isinstance(quote_id, str) and quote_id:
        return analysis.start(workspace_id, token, group, quote_id)
    raise AlphaError("Ask for a quote first, then start the analysis with that quote.", 400)


def handle(service, workspace_id, token, parts, method, body, query):
    """`parts` is the path below /voice-imports (a list, possibly empty); `body` the parsed JSON body or None; `query`
    the parsed query string. Returns the response body, or None when this is not a voice-import route."""
    importer = getattr(service, "voice_import", None)
    if importer is None:
        raise _disabled()
    parts = list(parts or [])
    if not parts:
        if method == "GET":
            analysis = getattr(service, ANALYSIS_ATTRIBUTE, None)
            # The analysis service's own status fields (`analysis`, `analyses`) sit at the top level, where the panel reads them.
            return {**importer.status(workspace_id, token), **(analysis.status(workspace_id, token) if analysis is not None else {"analysis": None})}
        return importer.request(workspace_id, token, body) if method == "POST" else None
    head = parts[0]
    if head == "posts":
        if len(parts) == 1 and method == "GET":
            wanted = {}
            for key in POST_FILTERS:
                value = (query or {}).get(key)
                value = value[0] if isinstance(value, list) and value else value
                if isinstance(value, str):
                    wanted[key] = value
            return importer.posts(workspace_id, token, wanted)
        return importer.correct_post(workspace_id, token, parts[1], body) if len(parts) == 2 and method == "POST" else None
    if head == "analysis":
        return _analysis(service, workspace_id, token, body) if len(parts) == 1 and method == "POST" else None
    if len(parts) == 1:
        return importer.delete(workspace_id, token, head) if method == "DELETE" else None
    if len(parts) == 2 and method == "POST":
        if parts[1] == "items":
            return importer.items(workspace_id, token, head, body)
        if parts[1] == "cancel":
            return importer.cancel(workspace_id, token, head)
        if parts[1] == "refresh":
            return importer.refresh(workspace_id, token, head, body)
    return None


def status_code(parts, method, result):
    """202 for work that continues in the background: a requested or refreshed import, a started analysis."""
    parts = list(parts or [])
    if method != "POST":
        return 200
    if not parts or (len(parts) == 2 and parts[0] not in _NOT_AN_IMPORT and parts[1] == "refresh"):
        return 202
    if parts == ["analysis"] and isinstance(result, dict) and "analysis" in result:
        return 202
    return 200


def respond(app, environ, start_response, service, token, method, parts):
    """hosted_app.py: read the body (an upload batch is refused above 512 kB before it is read), dispatch, answer.
    A DELETE may come without a body (the web client sends none); a body that is sent must be a JSON object."""
    if getattr(service, "voice_import", None) is None:
        raise _disabled()
    rest = parts[4:]
    body = None
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        if method == "POST" and len(rest) == 2 and rest[1] == "items":
            try:
                length = int(environ.get("CONTENT_LENGTH") or "0")
            except ValueError as error:
                raise AlphaError("Invalid request length.") from error
            if length > voice_import.MAX_BATCH_BYTES:
                raise AlphaError("This batch is larger than 512 kB. Send fewer posts at a time.", 413, code="voice_import_batch_too_large")
        if method != "DELETE" or (environ.get("CONTENT_LENGTH") or "0").strip() != "0":
            body = app._body(environ)
    result = handle(service, parts[2], token, rest, method, body, parse_qs(environ.get("QUERY_STRING", "")))
    if result is None:
        raise AlphaError("This hosted route is unavailable.", 404)
    return app._json(start_response, status_code(rest, method, result), result)
