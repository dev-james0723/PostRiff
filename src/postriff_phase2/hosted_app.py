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
from .hosted_identity import SupabaseIdentityAdmin, verified_auth_time, verified_session_id
from .hosted_worker import PostgresWorker
from .provider_candidates import SupabaseSessionCandidate
from .content_types import formats, public_catalog, public_packs
from . import tools
from .agent_runtime import FixtureAgentRuntime


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
    verify.auth_time = lambda access_token, principal: verified_auth_time(access_token, principal)
    return verify


def client_address(environ):
    """First hop of X-Forwarded-For (set by the platform edge) or the socket peer."""
    forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
    value = forwarded.split(",")[0].strip() if forwarded else environ.get("REMOTE_ADDR", "")
    return value[:64] or None


def client_label(environ):
    """Coarse, non-identifying product token from the User-Agent for the device list."""
    agent = environ.get("HTTP_USER_AGENT", "")
    label = "".join(ch for ch in agent.split("/")[0] if ch.isalnum() or ch in " .-_")[:40].strip()
    return label or "unknown"


def billing_from_environment(values):
    """Stripe mounts only with both secrets; otherwise billing is disabled (never the public-secret fixture).
    Email mounts with Resend when RESEND_API_KEY is set, which then requires EMAIL_FROM and the public base URL."""
    from .billing import DisabledPaymentProvider
    from .billing_stripe import StripePaymentProvider
    from .email import Mailer, NullTransport, ResendTransport
    stripe_key, stripe_secret = values.get("STRIPE_SECRET_KEY"), values.get("STRIPE_WEBHOOK_SECRET")
    provider = StripePaymentProvider(stripe_key, stripe_secret) if stripe_key and stripe_secret else DisabledPaymentProvider()
    resend_key = values.get("RESEND_API_KEY")
    base_url = values.get("POSTRIFF_PUBLIC_BASE_URL")
    if resend_key:
        if not values.get("EMAIL_FROM") or not base_url:
            raise ValueError("EMAIL_FROM and POSTRIFF_PUBLIC_BASE_URL are required when RESEND_API_KEY is set.")
        return provider, Mailer(ResendTransport(resend_key), values["EMAIL_FROM"], base_url)
    return provider, Mailer(NullTransport(), "PostRiff <no-reply@postriff.invalid>", base_url or "https://postriff.invalid")


def runtime_from_environment(environ=None):
    values = environ or os.environ
    database = postgres_factory(values.get("POSTRIFF_DATABASE_URL"))
    project_url = values.get("POSTRIFF_SUPABASE_URL")
    publishable = values.get("POSTRIFF_SUPABASE_PUBLISHABLE_KEY")
    secret = values.get("POSTRIFF_SUPABASE_SECRET_KEY")
    verify = supabase_verifier(project_url, publishable, database)
    storage = PrivateAssetService(SupabaseStorage(project_url, secret))
    identity = SupabaseIdentityAdmin(project_url, publishable, secret)
    from .oauth import CredentialVault
    from .providers import registry_from_environment
    from .hosted_social import HostedSocial
    # Adapters mount only with client credentials; live execution only when a provider is
    # explicitly marked reviewed. Otherwise the worker stays fail-closed (DisabledHostedSocial).
    providers = registry_from_environment(values)
    billing_provider, mailer = billing_from_environment(values)
    service = HostedWorkspaceService(database, verify, storage, identity=identity, vault=CredentialVault(values.get("POSTRIFF_CREDENTIAL_KEY")), providers=providers, public_base_url=values.get("POSTRIFF_PUBLIC_BASE_URL"), billing_provider=billing_provider, mailer=mailer)
    social = HostedSocial(service.oauth, providers, storage) if any(p.production_reviewed for p in providers.values()) else None
    worker = PostgresWorker(database, social=social)
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
        labels = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type", 429: "Too Many Requests", 500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable"}
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

    @staticmethod
    def _query_int(environ, key, default=0):
        from urllib.parse import parse_qs
        value = parse_qs(environ.get("QUERY_STRING", "")).get(key, [None])[0]
        if value is None:
            return default
        if not value.isdigit():
            raise AlphaError(f"Invalid {key}.", 400)
        return int(value)

    def _ideas(self, environ, start_response, service, token, method, parts):
        """Architecture §21 Ideas routes. Events are cursor-replayable; SSE replays stored events then closes."""
        workspace_id, resource = parts[2], parts[4]
        ideas = service.ideas
        if resource == "quick-start" and len(parts) == 5 and method == "POST":
            body = self._body(environ)
            return self._json(start_response, 201, ideas.quick_start(workspace_id, token, body.get("expectedRevision"), body))
        if resource == "conversations":
            if len(parts) == 5 and method == "GET":
                return self._json(start_response, 200, ideas.conversations(workspace_id, token))
            if len(parts) == 5 and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 201, ideas.create_conversation(workspace_id, token, body.get("title", "")))
            if len(parts) == 7 and parts[6] == "turns" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 201, ideas.turn(workspace_id, token, parts[5], body))
            if len(parts) == 7 and parts[6] == "messages" and method == "GET":
                return self._json(start_response, 200, ideas.messages(workspace_id, token, parts[5], self._query_int(environ, "cursor")))
            if len(parts) == 7 and parts[6] == "attachments" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 201, ideas.attach(workspace_id, token, parts[5], body))
        if resource == "runs" and len(parts) == 7:
            run_id, verb = parts[5], parts[6]
            if verb == "events" and method == "GET":
                cursor = self._query_int(environ, "cursor")
                last = environ.get("HTTP_LAST_EVENT_ID", "")
                if last and ":" in last and last.rsplit(":", 1)[1].isdigit():
                    cursor = max(cursor, int(last.rsplit(":", 1)[1]))
                result = ideas.events(workspace_id, token, run_id, cursor)
                if "text/event-stream" in environ.get("HTTP_ACCEPT", ""):
                    chunks = [f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps({k: v for k, v in e.items() if k not in ('id', 'type')}, ensure_ascii=False)}\n\n" for e in result["events"]]
                    chunks.append(f"event: run.status\ndata: {json.dumps({'runId': run_id, 'status': result['status'], 'cursor': result['cursor']})}\nretry: 2000\n\n")
                    raw = "".join(chunks).encode()
                    start_response("200 OK", [("Content-Type", "text/event-stream; charset=utf-8"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"), ("X-Accel-Buffering", "no")])
                    return [raw]
                return self._json(start_response, 200, result)
            if verb == "cancel" and method == "POST":
                self._body(environ)
                return self._json(start_response, 200, ideas.cancel(workspace_id, token, run_id))
            if verb == "apply" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 200, ideas.apply(workspace_id, token, body.get("expectedRevision"), run_id, body.get("artifactHash")))
        raise AlphaError("This hosted route is unavailable.", 404)

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        mutation = method in ("POST", "PUT", "PATCH", "DELETE")
        try:
            if path == "/api/health" and method == "GET":
                configured = self.service is not None or all(os.environ.get(key) for key in ("POSTRIFF_DATABASE_URL", "POSTRIFF_SUPABASE_URL", "POSTRIFF_SUPABASE_PUBLISHABLE_KEY", "POSTRIFF_SUPABASE_SECRET_KEY"))
                return self._json(start_response, 200, {"status": "ok", "execution": "phase2-hosted-candidate", "configured": bool(configured), "phase0": "incomplete", "customerValidated": False})
            if path == "/api/catalog" and method == "GET":
                provider = (self.public_auth or {}).get("provider", "supabase")
                return self._json(start_response, 200, {"templates": catalog(), "routes": routes(), "profileMetadata": metadata(), "phase2": True, "authMode": "dev" if provider == "dev" else "supabase", "execution": (self.public_auth or {}).get("execution", "hosted")})
            if path == "/api/privacy/notice" and method == "GET":
                from . import privacy
                return self._json(start_response, 200, privacy.notice())
            if path == "/api/billing/webhook" and method == "POST":
                service = self._runtime()
                length = int(environ.get("CONTENT_LENGTH") or "0")
                if not 0 < length <= 65536:
                    raise AlphaError("Webhook body size invalid.", 413)
                raw = environ["wsgi.input"].read(length)
                signature = environ.get("HTTP_STRIPE_SIGNATURE") or environ.get("HTTP_X_POSTRIFF_BILLING_SIGNATURE", "")
                return self._json(start_response, 200, service.billing_webhook(signature, raw))
            if method == "GET" and path in ("/api/content-types", "/api/content-formats", "/api/content-type-packs"):
                response = {"/api/content-types": public_catalog, "/api/content-formats": formats, "/api/content-type-packs": public_packs}[path]()
                return self._json(start_response, 200, response)
            if path == "/api/auth/config" and method == "GET":
                self._runtime()
                return self._json(start_response, 200, self.public_auth)
            if path == "/api/ideas/models" and method == "GET":
                runtime = FixtureAgentRuntime()
                return self._json(start_response, 200, {"models": runtime.list_supported_models(), "reasoning": runtime.list_supported_reasoning()})
            if path == "/api/tools" and method == "GET":
                return self._json(start_response, 200, {"tools": tools.catalog(), "isolation": tools.isolation_status()})
            oauth_parts = path.strip("/").split("/")
            if len(oauth_parts) == 4 and oauth_parts[:2] == ["api", "oauth"] and oauth_parts[3] == "callback" and method == "GET":
                # Public provider callback: redirect state/code to the signed-in app; never exchange here.
                from urllib.parse import parse_qs
                from .oauth import OAuthService
                query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
                proto = environ.get("HTTP_X_FORWARDED_PROTO", environ.get("wsgi.url_scheme", "https")).split(",")[0].strip()
                location = OAuthService.callback_redirect(f"{proto}://{environ.get('HTTP_HOST', '')}", oauth_parts[2], query)
                start_response("302 Found", [("Location", location), ("Cache-Control", "no-store"), ("Content-Length", "0")])
                return [b""]
            if path == "/api/cron/worker" and method == "GET":
                service = self._runtime()
                expected = self.cron_secret or ""
                supplied = environ.get("HTTP_AUTHORIZATION", "")
                if len(expected) < 16 or not hmac.compare_digest(supplied, "Bearer " + expected):
                    raise AlphaError("Cron authorization failed.", 401)
                result = self.worker.tick()
                result["reminders"] = service.run_reminders()
                return self._json(start_response, 200, result)
            self._origin(environ, mutation)
            service = self._runtime()
            token = self._token(environ)
            if path == "/api/auth/verify" and method == "POST":
                body = self._body(environ)
                created = service.bootstrap(token, body.get("plan", "studio"), client=client_address(environ), client_label=client_label(environ))
                if isinstance(created, dict):
                    created.pop("token", None)  # Sessions remain in the Authorization boundary.
                return self._json(start_response, 201, created)
            if path == "/api/auth/logout" and method == "POST":
                self._body(environ)
                return self._json(start_response, 200, service.logout(token))
            if path == "/api/auth/sessions" and method == "GET":
                return self._json(start_response, 200, service.sessions(token))
            if path == "/api/workspaces" and method == "GET":
                return self._json(start_response, 200, service.workspaces(token))
            if path == "/api/invitations/accept" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 200, service.accept_invitation(token, body.get("token"), client=client_address(environ)))
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "tools"] and parts[3] == "invoke" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 200, tools.invoke(parts[2], body.get("version"), body.get("input", {})))
            if len(parts) >= 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "ideas":
                return self._ideas(environ, start_response, service, token, method, parts)
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "billing" and method == "POST":
                body = self._body(environ)
                if parts[4] == "checkout":
                    return self._json(start_response, 201, service.billing_checkout(parts[2], token, body.get("planTermsId"), body.get("successPath"), body.get("cancelPath")))
                if parts[4] == "portal":
                    return self._json(start_response, 200, service.billing_portal(parts[2], token, body.get("returnPath")))
            if len(parts) == 4 and parts[:2] == ["api", "workspaces"] and parts[3] in ("usage", "subscription") and method == "GET":
                return self._json(start_response, 200, service.usage(parts[2], token))
            if len(parts) == 4 and parts[:2] == ["api", "workspaces"] and parts[3] == "data-requests":
                if method == "GET":
                    return self._json(start_response, 200, service.data_requests.list(parts[2], token))
                body = self._body(environ)
                return self._json(start_response, 201, service.data_request(parts[2], token, body.get("kind"), body))
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "analytics" and parts[4] in ("summary", "posts") and method == "GET":
                return self._json(start_response, 200, service.analytics(parts[2], token))
            if len(parts) >= 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "audience":
                audience = service.audience
                if len(parts) == 5 and parts[4] == "threads" and method == "GET":
                    return self._json(start_response, 200, audience.threads(parts[2], token))
                if len(parts) == 7 and parts[4] == "threads" and parts[6] == "reply-drafts" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 201, audience.draft_reply(parts[2], token, parts[5], body))
                if len(parts) == 7 and parts[4] == "reply-drafts" and parts[6] == "reply-preview" and method == "POST":
                    self._body(environ)
                    return self._json(start_response, 200, audience.reply_preview(parts[2], token, parts[5]))
                if len(parts) == 7 and parts[4] == "reply-drafts" and parts[6] == "reply" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 200, audience.approve_reply(parts[2], token, parts[5], body.get("digest"), body.get("confirmed")))
            if len(parts) >= 4 and parts[:2] == ["api", "workspaces"] and parts[3] == "channels":
                oauth = service.oauth
                if len(parts) == 4 and method == "GET":
                    return self._json(start_response, 200, oauth.channels(parts[2], token))
                if len(parts) == 7 and parts[5] == "oauth" and parts[6] == "start" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 201, oauth.start(parts[2], token, parts[4], body.get("capability", "publish")))
                if len(parts) == 7 and parts[5] == "oauth" and parts[6] == "complete" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 200, oauth.complete(parts[2], token, parts[4], body.get("state"), body.get("code"), body.get("error")))
                if len(parts) == 6 and parts[5] == "verify" and method == "POST":
                    self._body(environ)
                    return self._json(start_response, 200, oauth.verify(parts[2], token, parts[4]))
                if len(parts) == 5 and method == "DELETE":
                    self._body(environ)
                    return self._json(start_response, 200, oauth.disconnect(parts[2], token, parts[4]))
            if len(parts) == 4 and parts[:3] == ["api", "auth", "sessions"] and method == "DELETE":
                self._body(environ)
                return self._json(start_response, 200, service.revoke_session(token, parts[3]))
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "media" and method == "GET":
                raw, mime = service.media(parts[2], token, parts[4])
                start_response("200 OK", [("Content-Type", mime), ("Content-Length", str(len(raw))), ("Cache-Control", "private, no-store"), ("X-Content-Type-Options", "nosniff")])
                return [raw]
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "members" and method in ("PATCH", "DELETE"):
                body = self._body(environ)
                if method == "PATCH":
                    return self._json(start_response, 200, service.update_member(parts[2], token, parts[4], body.get("role"), body.get("permissions", {})))
                return self._json(start_response, 200, service.remove_member(parts[2], token, parts[4]))
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "invitations" and method == "DELETE":
                self._body(environ)
                return self._json(start_response, 200, service.revoke_invitation(parts[2], token, parts[4]))
            if len(parts) in (3, 4) and parts[:2] == ["api", "workspaces"]:
                workspace_id = parts[2]
                if len(parts) == 3 and method == "GET":
                    return self._json(start_response, 200, service.get(workspace_id, token))
                if len(parts) == 4 and parts[3] == "members" and method == "GET":
                    return self._json(start_response, 200, service.members(workspace_id, token))
                if len(parts) == 4 and parts[3] == "audit" and method == "GET":
                    return self._json(start_response, 200, service.audit_events(workspace_id, token))
                if len(parts) == 4 and parts[3] == "invitations" and method == "GET":
                    return self._json(start_response, 200, service.invitations(workspace_id, token))
                if len(parts) == 4 and parts[3] == "invitations" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 201, service.invite(workspace_id, token, body.get("email"), body.get("role"), body.get("permissions", {})))
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
