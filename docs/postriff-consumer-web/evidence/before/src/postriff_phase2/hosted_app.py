"""WSGI API candidate for hosted Phase 2 composition.

It initializes lazily so build and health checks do not require credentials.
"""
import hmac
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from postriff_alpha.domain import AlphaError
from postriff_alpha.generation import routes
from postriff_alpha.profiles import metadata
from postriff_alpha.templates import catalog
from .hosted import HostedWorkspaceService
from .hosted_storage import PrivateAssetService, SupabaseStorage
from .hosted_identity import SupabaseIdentityAdmin, verified_session_id
from .hosted_worker import PostgresWorker
from .provider_candidates import SupabaseSessionCandidate
from .content_types import formats, public_catalog, public_packs


def postgres_factory(dsn):
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("POSTRIFF_DATABASE_URL is required.")
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("Install the pinned hosted PostgreSQL dependency.") from error
    # Supabase transaction-mode pooling does not support prepared statements.
    # Each invocation gets one bounded connection and TLS is enforced by the DSN.
    return lambda: psycopg.connect(dsn, client_encoding="utf8", prepare_threshold=None, connect_timeout=8)


def supabase_verifier(project_url, publishable_key, connection_factory=None):
    if not isinstance(publishable_key, str) or len(publishable_key) < 20:
        raise ValueError("POSTRIFF_SUPABASE_PUBLISHABLE_KEY is required.")

    def get_user(url, token):
        request = Request(url, headers={"Authorization": "Bearer " + token, "apikey": publishable_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=12, context=ssl.create_default_context()) as response:
                return {"status": response.status, "body": json.loads(response.read(262144))}
        except HTTPError as error:
            error.read(65536)
            return {"status": error.code, "body": {}}
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("The identity service is temporarily unavailable.", 503) from error

    candidate = SupabaseSessionCandidate(project_url, get_user)

    def verify(access_token):
        principal = candidate.verify(access_token)
        session_id = verified_session_id(access_token, principal)
        if connection_factory is not None:
            with connection_factory() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_account_tombstones WHERE user_id=%s), EXISTS(SELECT 1 FROM public.pr_session_revocations WHERE user_id=%s AND session_id=%s)", (principal, principal, session_id))
                    deleted, revoked = cur.fetchone()
            if deleted or revoked:
                raise AlphaError("This session expired or was revoked. Sign in again.", 401)
        return principal

    verify.session_id = lambda access_token, principal: verified_session_id(access_token, principal)
    return verify


def runtime_from_environment(environ=None):
    values = environ or os.environ
    database = postgres_factory(values.get("POSTRIFF_DATABASE_URL"))
    project_url = values.get("POSTRIFF_SUPABASE_URL")
    publishable = values.get("POSTRIFF_SUPABASE_PUBLISHABLE_KEY")
    secret = values.get("POSTRIFF_SUPABASE_SECRET_KEY")
    verify = supabase_verifier(project_url, publishable, database)
    storage = PrivateAssetService(SupabaseStorage(project_url, secret))
    identity = SupabaseIdentityAdmin(project_url, publishable, secret)
    service = HostedWorkspaceService(database, verify, storage, identity=identity)
    worker = PostgresWorker(database)
    return service, worker, {"projectUrl": project_url, "publishableKey": publishable, "provider": "supabase", "flow": "pkce"}


class HostedApplication:
    def __init__(self, service=None, worker=None, public_auth=None, cron_secret=None):
        self.service = service
        self.worker = worker
        self.public_auth = public_auth
        self.cron_secret = cron_secret
        self.setup_error = None

    def _runtime(self):
        if self.service is None and self.setup_error is None:
            try:
                self.service, self.worker, self.public_auth = runtime_from_environment()
                self.cron_secret = os.environ.get("CRON_SECRET")
            except Exception as error:
                self.setup_error = error
        if self.service is None:
            raise AlphaError("Hosted Phase 2 is not configured.", 503)
        return self.service

    @staticmethod
    def _json(start_response, status, body, extra_headers=None):
        raw = json.dumps(body, ensure_ascii=False).encode()
        labels = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type", 500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable"}
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")]
        headers.extend(extra_headers or [])
        start_response(f"{status} {labels.get(status, 'Error')}", headers)
        return [raw]

    @staticmethod
    def _token(environ):
        value = environ.get("HTTP_AUTHORIZATION", "")
        if not value.startswith("Bearer ") or len(value) <= 27:
            raise AlphaError("Verified session required.", 401)
        return value[7:]

    @staticmethod
    def _body(environ):
        if "application/json" not in environ.get("CONTENT_TYPE", ""):
            raise AlphaError("Send a JSON action.", 415)
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError as error:
            raise AlphaError("Invalid request length.") from error
        if not 0 < length <= 12_000_000:
            raise AlphaError("This request exceeds the action size limit.", 413)
        try:
            body = json.loads(environ["wsgi.input"].read(length))
        except (ValueError, UnicodeDecodeError) as error:
            raise AlphaError("The request was not valid JSON.") from error
        if not isinstance(body, dict):
            raise AlphaError("Expected a structured action.")
        return body

    @staticmethod
    def _origin(environ, mutation=False):
        if not mutation:
            return
        if environ.get("HTTP_X_POSTRIFF_REQUEST") != "founder-alpha":
            raise AlphaError("This request is missing the application guard.", 403)
        host = environ.get("HTTP_HOST", "")
        proto = environ.get("HTTP_X_FORWARDED_PROTO", environ.get("wsgi.url_scheme", "https")).split(",")[0].strip()
        origin = environ.get("HTTP_ORIGIN")
        if not host or proto not in ("http", "https") or origin and origin != f"{proto}://{host}":
            raise AlphaError("This origin cannot access the hosted API.", 403)

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        mutation = method in ("POST", "PUT", "PATCH", "DELETE")
        try:
            if path == "/api/health" and method == "GET":
                configured = self.service is not None or all(os.environ.get(key) for key in ("POSTRIFF_DATABASE_URL", "POSTRIFF_SUPABASE_URL", "POSTRIFF_SUPABASE_PUBLISHABLE_KEY", "POSTRIFF_SUPABASE_SECRET_KEY"))
                return self._json(start_response, 200, {"status": "ok", "execution": "phase2-hosted-candidate", "configured": bool(configured), "phase0": "incomplete", "customerValidated": False})
            if path == "/api/catalog" and method == "GET":
                return self._json(start_response, 200, {"templates": catalog(), "routes": routes(), "profileMetadata": metadata(), "phase2": True, "authMode": "supabase"})
            if method == "GET" and path in ("/api/content-types", "/api/content-formats", "/api/content-type-packs"):
                response = {"/api/content-types": public_catalog, "/api/content-formats": formats, "/api/content-type-packs": public_packs}[path]()
                return self._json(start_response, 200, response)
            if path == "/api/auth/config" and method == "GET":
                self._runtime()
                return self._json(start_response, 200, self.public_auth)
            if path == "/api/cron/worker" and method == "GET":
                self._runtime()
                expected = self.cron_secret or ""
                supplied = environ.get("HTTP_AUTHORIZATION", "")
                if len(expected) < 16 or not hmac.compare_digest(supplied, "Bearer " + expected):
                    raise AlphaError("Cron authorization failed.", 401)
                return self._json(start_response, 200, self.worker.tick())
            self._origin(environ, mutation)
            service = self._runtime()
            token = self._token(environ)
            if path == "/api/auth/verify" and method == "POST":
                body = self._body(environ)
                created = service.bootstrap(token, body.get("plan", "studio"))
                if isinstance(created, dict):
                    created.pop("token", None)  # Sessions remain in the Authorization boundary.
                return self._json(start_response, 201, created)
            if path == "/api/auth/logout" and method == "POST":
                self._body(environ)
                return self._json(start_response, 200, service.logout(token))
            parts = path.strip("/").split("/")
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "media" and method == "GET":
                raw, mime = service.media(parts[2], token, parts[4])
                start_response("200 OK", [("Content-Type", mime), ("Content-Length", str(len(raw))), ("Cache-Control", "private, no-store"), ("X-Content-Type-Options", "nosniff")])
                return [raw]
            if len(parts) in (3, 4) and parts[:2] == ["api", "workspaces"]:
                workspace_id = parts[2]
                if len(parts) == 3 and method == "GET":
                    return self._json(start_response, 200, service.get(workspace_id, token))
                if len(parts) == 4 and parts[3] == "actions" and method == "POST":
                    body = self._body(environ)
                    action, payload, revision = body.get("action"), body.get("payload", {}), body.get("expectedRevision")
                    if action == "p2_media_upload":
                        result = service.upload_media(workspace_id, token, revision, payload)
                    elif action == "p2_media_delete":
                        result = service.delete_media(workspace_id, token, revision, payload.get("assetId"))
                    else:
                        result = service.mutate(workspace_id, token, revision, action, payload)
                    return self._json(start_response, 200, result)
                if len(parts) == 4 and parts[3] == "export" and method == "GET":
                    raw = service.export(workspace_id, token)
                    start_response("200 OK", [("Content-Type", "application/zip"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"), ("Content-Disposition", 'attachment; filename="postriff-private-drafts.zip"'), ("X-Content-Type-Options", "nosniff")])
                    return [raw]
                if len(parts) == 4 and parts[3] == "profile-export" and method == "GET":
                    raw = service.export_profile(workspace_id, token)
                    start_response("200 OK", [("Content-Type", "application/zip"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"), ("Content-Disposition", 'attachment; filename="postriff-personal-voice.zip"'), ("X-Content-Type-Options", "nosniff")])
                    return [raw]
                if len(parts) == 4 and parts[3] == "account" and method == "DELETE":
                    body = self._body(environ)
                    return self._json(start_response, 200, service.delete_account(workspace_id, token, body.get("confirmation")))
            raise AlphaError("This hosted route is unavailable.", 404)
        except AlphaError as error:
            return self._json(start_response, error.status, {"error": str(error)})
        except Exception:
            return self._json(start_response, 500, {"error": "The hosted service could not complete this request. Saved state remains authoritative."})


app = HostedApplication()
