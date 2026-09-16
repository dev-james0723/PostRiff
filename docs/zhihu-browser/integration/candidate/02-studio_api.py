"""Same-origin workspace, editorial and local handoff API. No remote authority."""
from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
from contextlib import asynccontextmanager
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException

from .studio import MAX_ASSET_BYTES, StudioError, StudioStore, VERSION

MAX_JSON_REQUEST_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_ASSET_BYTES + 64 * 1024
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
}


def _error(code, message, status):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=SECURITY_HEADERS)


class LocalOwnerBoundary:
    """DNS-rebinding/CSRF boundary, not isolation against same-user processes.

    A per-process token is delivered only as an HttpOnly cookie after a local
    document navigation. It never appears in JSON, source files, logs or storage.
    Every API read except health needs this token. Mutations additionally need the
    exact request Origin, custom header and same-origin Fetch Metadata if present.
    """

    def __init__(self, app, port):
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.token = secrets.token_urlsafe(48)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        raw_headers = scope.get("headers", [])
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in raw_headers}
        host = headers.get("host", "")
        origin = headers.get("origin")
        site = headers.get("sec-fetch-site")
        method = scope["method"]
        path = scope["path"]

        async def fail(code, message, status):
            await _error(code, message, status)(scope, receive, send)

        if sum(key.lower() == b"host" for key, _ in raw_headers) != 1 or host not in self.hosts:
            await fail("host_not_allowed", "Use this Studio's exact loopback address.", 403)
            return
        if origin is not None and origin != "http://" + host:
            await fail("origin_not_allowed", "Requests must originate from this Studio window.", 403)
            return
        # OAuth returns from a different origin. Permit only a clean top-level
        # document navigation, never an API call, iframe, mutation or query data.
        safe_connection_return = (method == 'GET' and path == '/connection-return'
                                  and not scope.get('query_string')
                                  and headers.get('sec-fetch-mode') == 'navigate'
                                  and headers.get('sec-fetch-dest') == 'document')
        if site is not None and site not in ("none", "same-origin") and not safe_connection_return:
            await fail("cross_site_request", "Cross-site requests are not permitted.", 403)
            return
        if method == "OPTIONS":
            await fail("cross_origin_not_supported", "Studio does not expose a cross-origin API.", 403)
            return
        is_api = path.startswith("/api/") or path == "/api"
        is_health = path == "/api/health" and method == "GET"
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
            supplied = cookie.get("studio_session")
            authenticated = bool(supplied and hmac.compare_digest(supplied.value, self.token))
        except (CookieError, ValueError, TypeError):
            authenticated = False
        if is_api and not is_health and not authenticated:
            await fail("local_session_required", "Open or reload the Studio window to establish this local session.", 401)
            return
        if method not in ("GET", "HEAD"):
            if not authenticated:
                await fail("local_session_required", "Open the Studio window first.", 401)
                return
            if headers.get("x-studio-request") != "1" or origin != "http://" + host:
                await fail("mutation_guard_required", "A same-origin Studio request is required for local changes.", 403)
                return
        # Bound the raw body before multipart parsers can spool data to disk.
        limit = MAX_UPLOAD_REQUEST_BYTES if path == "/api/assets" else MAX_JSON_REQUEST_BYTES
        if "content-length" in headers:
            try:
                length = int(headers["content-length"])
            except ValueError:
                length = -1
            if length < 0 or length > limit:
                await fail("request_size_limit", "The local request exceeds its size limit.", 413)
                return
        messages, total = [], 0
        if method not in ("GET", "HEAD"):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                total += len(message.get("body", b""))
                if total > limit:
                    await fail("request_size_limit", "The local request exceeds its size limit.", 413)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
        index = 0

        async def guarded_receive():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        mint_session = (not is_api and method == "GET" and headers.get("sec-fetch-dest", "document") == "document"
                        and headers.get("sec-fetch-mode", "navigate") == "navigate")

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                outgoing = list(message.get("headers", []))
                existing = {key.lower() for key, _ in outgoing}
                outgoing.extend((key.lower().encode(), value.encode()) for key, value in SECURITY_HEADERS.items()
                                if key.lower().encode() not in existing)
                if mint_session and message["status"] == 200:
                    outgoing.append((b"set-cookie", f"studio_session={self.token}; HttpOnly; SameSite=Strict; Path=/".encode()))
                message = {**message, "headers": outgoing}
            await send(message)

        await self.app(scope, guarded_receive, guarded_send)


async def _body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise StudioError("json_required", "This local operation requires JSON.", 422)
    def reject_constant(_constant):
        raise ValueError("nonfinite_json")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(await request.body(), parse_constant=reject_constant, object_pairs_hook=unique_keys)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise StudioError("invalid_json", "The request is not valid JSON.", 422) from None
    if not isinstance(value, dict):
        raise StudioError("json_object_required", status=422)
    return value


def create_app(data_dir: Path, project_root: Path, port: int = 4310, provider=None, delivery_supervisor=None, connection_broker=None):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("invalid_loopback_port")
    store = StudioStore(data_dir, project_root)
    service = None
    if provider is not None:
        from .studio_agent import AgentService
        service = AgentService(store, provider)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            if connection_broker is not None:
                connection_broker.start()
            if delivery_supervisor is not None:
                delivery_supervisor.start()
            tiktok_publishing.start()
            yield
        finally:
            tiktok_publishing.shutdown()
            try:
                if delivery_supervisor is not None:
                    delivery_supervisor.shutdown()
            finally:
                if connection_broker is not None:
                    connection_broker.shutdown()
                if service is not None:
                    service.shutdown()

    app = FastAPI(title="James Au Studio", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store
    app.state.agent_service = service
    app.add_middleware(LocalOwnerBoundary, port=port)

    @app.exception_handler(StudioError)
    async def studio_error(_request, exc):
        return _error(exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        return _error("invalid_request", "The request fields are not valid.", 422)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return _error("not_found" if exc.status_code == 404 else "request_rejected", "This local operation is unavailable.", exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(_request, _exc):
        # Never serialize database paths, draft content or internal exception text.
        return _error("local_operation_failed", "The local operation could not complete. Your last saved revision remains in the database.", 500)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "phase": "D-connection", "version": VERSION, "app": "james-au-studio"}

    @app.get("/api/bootstrap")
    def bootstrap():
        result = store.bootstrap()
        result['capabilities']['agentBridge'] = service is not None
        if connection_broker is not None:
            states={
                'bluesky': connection_broker.status(),
                'youtube': connection_broker.youtube_status(),
                'instagram': connection_broker.instagram_status(),
                'tiktok': connection_broker.tiktok_status(),
                'threads': connection_broker.threads_status(),
                'pinterest': connection_broker.pinterest_status(),
                'reddit': connection_broker.reddit_status(),
                'xiaohongshu': connection_broker.xiaohongshu_status(),
            }
            for channel in result['channels']:
                if channel['id'] in states and states[channel['id']]['state'] in {'connected_identity', 'connected_browser_identity', 'identity_connected'}:
                    channel['connection']='connected_identity'
                    channel['publishReady']=states[channel['id']].get('publishReady') is True
            result['capabilities']['publishing']=any(channel['publishReady'] for channel in result['channels'])
            result['capabilities']['scheduling']=bool(states['youtube'].get('publishReady'))
        return result

    @app.get("/api/drafts")
    def drafts(archived: bool = False):
        return {"drafts": store.list_drafts(archived)}

    @app.post("/api/drafts", status_code=201)
    async def create_draft(request: Request):
        return {"draft": store.create_draft(await _body(request))}

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str):
        return {"draft": store.get_draft(draft_id)}

    @app.put("/api/drafts/{draft_id}")
    async def update_draft(draft_id: str, request: Request):
        data = await _body(request)
        revision = data.pop("expectedRevision", None)
        return {"draft": store.update_draft(draft_id, data, revision)}

    @app.post("/api/drafts/{draft_id}/archive")
    async def archive_draft(draft_id: str, request: Request):
        data = await _body(request)
        if set(data) != {"expectedRevision", "archived"}:
            raise StudioError("invalid_archive_fields", status=422)
        return {"draft": store.archive_draft(draft_id, data["expectedRevision"], data["archived"])}

    @app.get("/api/drafts/{draft_id}/export")
    def export_draft(draft_id: str):
        content = store.export_draft(draft_id)
        # The server-generated id cannot inject response headers or file paths.
        return Response(content, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="studio-draft-{draft_id}.md"'})

    @app.get("/api/templates")
    def templates():
        return {"templates": store.list_templates()}

    @app.post("/api/templates", status_code=201)
    async def create_template(request: Request):
        return {"template": store.create_template(await _body(request))}

    @app.post("/api/templates/{template_id}/versions")
    async def template_version(template_id: str, request: Request):
        data = await _body(request)
        expected_version = data.pop("expectedVersion", None)
        return {"template": store.version_template(template_id, data, expected_version)}

    @app.post("/api/assets", status_code=201)
    async def create_asset(request: Request):
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
            raise StudioError("multipart_required", "Choose a local image file.", 422)
        try:
            async with request.form(max_files=1, max_fields=1, max_part_size=MAX_ASSET_BYTES) as form:
                if set(form) - {"file", "alt"} or len(form.getlist("file")) != 1 or len(form.getlist("alt")) > 1:
                    raise StudioError("invalid_upload_fields", status=422)
                file = form.get("file")
                if not file or not hasattr(file, "read") or not isinstance(form.get("alt", ""), str):
                    raise StudioError("image_file_required", status=422)
                data = await file.read(MAX_ASSET_BYTES + 1)
                return {"asset": store.add_asset(data, file.filename or "image", form.get("alt", ""), file.content_type)}
        except (ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, StudioError):
                raise
            raise StudioError("invalid_upload", "The local image upload could not be read.", 422) from None

    @app.get("/api/assets/{asset_id}/content")
    def asset_content(asset_id: str):
        data, mime = store.asset_content(asset_id)
        return Response(data, media_type=mime, headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/api/backup")
    def backup():
        return Response(store.backup(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="james-au-studio-backup.zip"'})

    if service is not None:
        from .studio_agent_api import register_agent_routes
        register_agent_routes(app, service)

    from .studio_delivery_api import register_delivery_routes
    register_delivery_routes(app, store, _body)

    from .studio_tiktok_publish import register_tiktok_publishing
    tiktok_publishing = register_tiktok_publishing(app, store, _body)
    app.state.tiktok_publishing = tiktok_publishing

    from .studio_setup import register_setup_routes
    register_setup_routes(app, _body, connection_broker)

    from .zhihu_browser import register_routes as register_zhihu_routes
    register_zhihu_routes(app, data_dir, _body)
    from .studio_connections import ConnectionBroker, register_connection_routes
    register_connection_routes(app, connection_broker or ConnectionBroker(project_root, data_dir, port), _body)

    from .studio_bilibili import register_bilibili_routes
    register_bilibili_routes(app, project_root)

    @app.get("/{file_path:path}")
    def frontend(file_path: str):
        if file_path == "api" or file_path.startswith("api/"):
            raise StudioError("operation_unavailable", "This local operation does not exist in this release.", 404)
        build = (Path(project_root) / "studio/web/dist").resolve()
        if any(part in (".", "..") for part in Path(file_path).parts) or "\\" in file_path:
            raise StudioError("invalid_static_path", status=404)
        requested = build / file_path
        if requested.is_symlink() or not requested.resolve().is_relative_to(build):
            raise StudioError("invalid_static_path", status=404)
        path = requested if file_path and requested.is_file() else build / "index.html"
        if not path.is_file():
            if file_path:
                raise StudioError("frontend_not_built", status=404)
            return HTMLResponse("<!doctype html><html lang='en'><meta charset='utf-8'><title>James Au Studio</title>"
                                "<main><h1>James Au Studio</h1><p>The local API is ready. Build the Studio frontend to open the workspace.</p>"
                                "<p>No channel connections or automatic publishing enabled.</p></main></html>")
        if path.is_symlink() or not path.resolve().is_relative_to(build):
            raise StudioError("invalid_static_path", status=404)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return Response(path.read_bytes(), media_type=mime)

    return app
