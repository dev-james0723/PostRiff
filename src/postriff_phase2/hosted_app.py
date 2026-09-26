"""WSGI API candidate for hosted Phase 2 composition.

It initializes lazily so build and health checks do not require credentials.
"""
import hmac
import logging
import json
import re
import os
import ssl
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from postriff_alpha.domain import AlphaError
from postriff_alpha.generation import routes
from postriff_alpha.profiles import metadata
from postriff_alpha.templates import catalog
from .hosted import HostedWorkspaceService
from .hosted_storage import PrivateAssetService, SupabaseStorage
from .hosted_identity import SupabaseIdentityAdmin, verified_aal, verified_auth_time, verified_session_id
from .hosted_worker import PostgresWorker
from .provider_candidates import SupabaseSessionCandidate
from .time_savings import with_time_back
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


def supabase_verifier(project_url, publishable_key, connection_factory=None, get_user=None):
    """`get_user` is the server transport to Supabase getUser; tests inject one, production uses HTTPS."""
    if not isinstance(publishable_key, str) or len(publishable_key) < 20:
        raise ValueError("POSTRIFF_SUPABASE_PUBLISHABLE_KEY is required.")

    def https_get_user(url, token):
        request = Request(url, headers={"Authorization": "Bearer " + token, "apikey": publishable_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=12, context=ssl.create_default_context()) as response:
                return {"status": response.status, "body": json.loads(response.read(262144))}
        except HTTPError as error:
            error.read(65536)
            return {"status": error.code, "body": {}}
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("The identity service is temporarily unavailable.", 503) from error

    candidate = SupabaseSessionCandidate(project_url, get_user or https_get_user)

    def verify(access_token):
        principal = candidate.verify(access_token)
        session_id = verified_session_id(access_token, principal)
        if connection_factory is not None:
            with connection_factory() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_account_tombstones WHERE user_id=%s), EXISTS(SELECT 1 FROM public.pr_session_revocations WHERE user_id=%s AND session_id=%s), EXISTS(SELECT 1 FROM public.pr_mfa_enforcement WHERE user_id=%s)", (principal, principal, session_id, principal))
                    deleted, revoked, mfa_required = cur.fetchone()
            if deleted or revoked:
                raise AlphaError("This session expired or was revoked. Sign in again.", 401)
            # Someone who turned on two-factor authentication must present it on every session:
            # the UI hides nothing the API would not also refuse.
            if mfa_required and verified_aal(access_token, principal) != "aal2":
                raise AlphaError("Two-factor verification required.", 403, code="mfa_required")
        return principal

    verify.session_id = lambda access_token, principal: verified_session_id(access_token, principal)
    verify.auth_time = lambda access_token, principal: verified_auth_time(access_token, principal)
    verify.aal = lambda access_token, principal: verified_aal(access_token, principal)
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


# Legacy alpha actions that wrote drafts with the template writer directly; refused on the hosted HTTP route.
RETIRED_WRITING_ACTIONS = frozenset({"generate", "preview_update"})


def ideas_runtime_from_environment(values):
    """Mount the paid model route only with a gateway key (AI_GATEWAY_API_KEY); never by default.
    POSTRIFF_MODEL_ID picks the default model; POSTRIFF_MODEL_IDS (comma list) the selectable set;
    POSTRIFF_MODEL_PRICES a JSON object {model: [inputUsdPerMTok, outputUsdPerMTok]} for estimates."""
    key = values.get("AI_GATEWAY_API_KEY")
    if not key:
        return None
    from .model_runtime import DEFAULT_MODEL, ServerModelRuntime, provider_map
    model = values.get("POSTRIFF_MODEL_ID") or DEFAULT_MODEL
    models = [m.strip() for m in (values.get("POSTRIFF_MODEL_IDS") or "").split(",") if m.strip()] or [model]
    prices = None
    if values.get("POSTRIFF_MODEL_PRICES"):
        try:
            prices = {k: (float(v[0]), float(v[1])) for k, v in json.loads(values["POSTRIFF_MODEL_PRICES"]).items()}
        except (ValueError, TypeError, IndexError) as error:
            raise ValueError("POSTRIFF_MODEL_PRICES must be a JSON object of model → [input, output] USD per million tokens.") from error
    endpoint = values.get("AI_GATEWAY_ENDPOINT") or None
    allowed = provider_map(values) or None
    return ServerModelRuntime(key, model=model, models=models, prices=prices, allowed_providers=allowed, **({"endpoint": endpoint} if endpoint else {}))


# Real charges need the merchant's own legal facts on record. None is ever inferred, and a "[to be confirmed]"
# placeholder counts as missing (web/src/config/legal.ts carries the same placeholders on the legal pages).
LEGAL_FACTS = ("POSTRIFF_LEGAL_ENTITY", "POSTRIFF_LEGAL_ADDRESS", "POSTRIFF_GOVERNING_LAW")


def live_charges_missing(values):
    """What still blocks live-mode charges: each legal fact not recorded, and the explicit
    POSTRIFF_LIVE_CHARGES_ENABLED=1 switch. Stripe test-mode keys never charge and are not gated."""
    missing = [name for name in LEGAL_FACTS if not (values.get(name) or "").strip() or "[" in (values.get(name) or "")]
    if values.get("POSTRIFF_LIVE_CHARGES_ENABLED") != "1":
        missing.append("POSTRIFF_LIVE_CHARGES_ENABLED")
    return missing


def billing_from_environment(values):
    """Stripe mounts only with both secrets; otherwise billing is disabled (never the public-secret fixture).
    A live-mode key additionally needs live_charges_missing() to be empty; until then nothing can be bought.
    Email mounts with Resend when RESEND_API_KEY is set, which then requires EMAIL_FROM and the public base URL."""
    from .billing import DisabledPaymentProvider
    from .billing_stripe import StripePaymentProvider, key_mode
    from .email import Mailer, NullTransport, ResendTransport
    stripe_key, stripe_secret = values.get("STRIPE_SECRET_KEY"), values.get("STRIPE_WEBHOOK_SECRET")
    if stripe_key and stripe_secret and key_mode(stripe_key) and live_charges_missing(values):
        provider = DisabledPaymentProvider("Real charges are off until the merchant's legal details are recorded.")
    else:
        provider = StripePaymentProvider(stripe_key, stripe_secret) if stripe_key and stripe_secret else DisabledPaymentProvider()
    resend_key = values.get("RESEND_API_KEY")
    base_url = values.get("POSTRIFF_PUBLIC_BASE_URL")
    if resend_key:
        if not values.get("EMAIL_FROM") or not base_url:
            raise ValueError("EMAIL_FROM and POSTRIFF_PUBLIC_BASE_URL are required when RESEND_API_KEY is set.")
        return provider, Mailer(ResendTransport(resend_key), values["EMAIL_FROM"], base_url)
    return provider, Mailer(NullTransport(), "Rafii <no-reply@postriff.invalid>", base_url or "https://postriff.invalid")


def runtime_from_environment(environ=None):
    from .deployment import isolated_environment
    values = isolated_environment(os.environ if environ is None else environ)
    database = postgres_factory(values.get("POSTRIFF_DATABASE_URL"))
    project_url = values.get("POSTRIFF_SUPABASE_URL")
    publishable = values.get("POSTRIFF_SUPABASE_PUBLISHABLE_KEY")
    secret = values.get("POSTRIFF_SUPABASE_SECRET_KEY")
    verify = supabase_verifier(project_url, publishable, database)
    storage = PrivateAssetService(SupabaseStorage(project_url, secret))
    identity = SupabaseIdentityAdmin(project_url, publishable, secret)
    from .oauth import CredentialVault
    from .providers import registry_from_environment, http_transport
    from .hosted_social import HostedSocial
    # Adapters mount only with client credentials; live execution only when a provider is
    # explicitly marked reviewed. Otherwise the worker stays fail-closed (DisabledHostedSocial).
    providers = registry_from_environment(values)
    billing_provider, mailer = billing_from_environment(values)
    from .image_runtime import from_environment as image_runtime_from_environment
    service = HostedWorkspaceService(database, verify, storage, identity=identity, vault=CredentialVault(values.get("POSTRIFF_CREDENTIAL_KEY")), providers=providers, public_base_url=values.get("POSTRIFF_PUBLIC_BASE_URL"), billing_provider=billing_provider, mailer=mailer, audience_transport=http_transport, ideas_runtime=ideas_runtime_from_environment(values), image_runtime=image_runtime_from_environment(values), credits_enabled=values.get("POSTRIFF_CREDITS_ENABLED") == "1", credit_purchases_enabled=values.get("POSTRIFF_CREDIT_PURCHASES_ENABLED") == "1")
    from .learning_model import extractor_from_environment
    # Preference learning C2: the person's CLI where the host has one, else the gateway key; consent is checked per workspace.
    service.learning.extractor = extractor_from_environment(values)
    social = HostedSocial(service.oauth, providers, storage) if any(p.production_reviewed for p in providers.values()) else None
    # Automations promise publishing only where live transport exists (capabilities.publish_route).
    service.publishing_live = social is not None
    # A verified publication fans out to comment ingestion and then Time Back; neither can unverify it.
    worker = PostgresWorker(database, social=social, on_verified=with_time_back(service.audience.on_post_verified, service.time_savings))
    # Rafii coworker (notifications, weekly operator, research, overlays…): every feature is off unless its RAFII_* flag is on.
    from .coworker import runtime as coworker_runtime
    coworker_runtime.attach(service, values)
    return service, worker, {"projectUrl": project_url, "publishableKey": publishable, "provider": "supabase", "flow": "pkce"}


_ID_SEGMENT = re.compile(r"^(?:[0-9a-fA-F-]{16,}|\d+|[A-Za-z0-9_-]{24,})$")


def route_pattern(path):
    """The request path with identifiers masked, for correlating failures without logging who or what."""
    return "/".join(":id" if _ID_SEGMENT.match(part) else part for part in (path or "/").split("/"))[:160]


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
        # Behind a reverse proxy (Vercel, the Next.js dev server) the browser-facing host arrives forwarded.
        host = (environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_HOST", "")).split(",")[0].strip()
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
        if resource == "credit-quotes" and len(parts) == 5 and method == "POST":
            return self._json(start_response, 201, ideas.credit_requests.issue(workspace_id, token, self._body(environ)))
        if resource == "credit-estimates" and len(parts) == 5 and method == "POST":
            return self._json(start_response, 200, ideas.credit_requests.estimate(workspace_id, token, self._body(environ)))
        if resource == "quick-start" and len(parts) == 5 and method == "POST":
            body = self._body(environ)
            return self._json(start_response, 201, ideas.quick_start(workspace_id, token, body.get("expectedRevision"), body))
        if resource == "conversations":
            if len(parts) == 5 and method == "GET":
                return self._json(start_response, 200, ideas.conversations(workspace_id, token))
            if len(parts) == 5 and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 201, ideas.create_conversation(workspace_id, token, body.get("title", "")))
            if len(parts) == 7 and parts[6] == "onboarding" and method == "POST":
                from .onboarding_chat import respond
                return self._json(start_response, 201, respond(ideas, workspace_id, token, parts[5], self._body(environ)))
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

    def _site_agent(self, environ, start_response, service, token, method, parts):
        """The Rafii side panel (site agent spec §13.1). Turns and composes are cursor-replayable runs; the SSE form of
        run events is the Ideas route. API tokens have no site-agent scope (api_tokens.route_scope)."""
        workspace_id, resource = parts[2], parts[4]
        agent = service.site_agent
        if resource == "turns" and len(parts) == 5 and method == "POST":
            return self._json(start_response, 201, agent.turn(workspace_id, token, self._body(environ)))
        if resource == "runs" and len(parts) == 7 and method == "POST":
            run_id, verb = parts[5], parts[6]
            if verb == "compose":
                self._body(environ)
                return self._json(start_response, 200, agent.compose(workspace_id, token, run_id))
            if verb == "cancel":
                self._body(environ)
                return self._json(start_response, 200, agent.cancel(workspace_id, token, run_id))
        if resource == "runs" and len(parts) == 7 and parts[6] == "events" and method == "GET":
            return self._json(start_response, 200, agent.events(workspace_id, token, parts[5], self._query_int(environ, "cursor")))
        if resource == "proposals" and len(parts) == 6 and method == "POST":
            body = self._body(environ)
            if parts[5] == "apply":
                return self._json(start_response, 200, agent.apply_proposal(workspace_id, token, body))
            if parts[5] == "dismiss":
                return self._json(start_response, 200, agent.dismiss_proposal(workspace_id, token, body))
        if resource == "compound" and len(parts) == 6 and parts[5] == "continue" and method == "POST":
            # A compound request whose writing run finished after the turn: save, link and propose scheduling now.
            return self._json(start_response, 200, agent.compound_continue(workspace_id, token, self._body(environ)))
        if resource == "feedback" and len(parts) == 5 and method == "POST":
            return self._json(start_response, 200, agent.feedback(workspace_id, token, self._body(environ)))
        if resource == "help" and method == "GET":
            if len(parts) == 5:
                return self._json(start_response, 200, agent.help_catalogue(workspace_id, token))
            if len(parts) == 6:
                return self._json(start_response, 200, agent.help_document(workspace_id, token, parts[5]))
        if resource == "insights" and len(parts) == 5 and method == "GET":
            return self._json(start_response, 200, agent.insights(workspace_id, token))
        raise AlphaError("This hosted route is unavailable.", 404)

    def __call__(self, environ, start_response):
        request_id = uuid.uuid4().hex
        environ['postriff.request_id'] = request_id
        started = time.monotonic()
        status_code = 500
        def respond(status, headers, exc_info=None):
            nonlocal status_code
            status_code = int(status.split()[0])
            headers = [(key,value) for key,value in headers if key.lower() != 'x-request-id']
            headers.append(('X-Request-ID', request_id))
            return start_response(status, headers, exc_info) if exc_info else start_response(status, headers)
        try:
            return self._handle(environ, respond)
        finally:
            # No URL, body, identity, exception text, query, headers or credential is logged.
            method = environ.get('REQUEST_METHOD','GET').upper()
            logger = logging.getLogger('postriff.request')
            logger.setLevel(logging.INFO)
            logger.log(logging.ERROR if status_code >= 500 else logging.INFO, json.dumps({
                'event':'request.completed', 'requestId':request_id,
                'method':method if method in ('GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD') else 'OTHER',
                'status':status_code, 'durationMs':round((time.monotonic()-started)*1000,2),
                'route':'cron' if environ.get('PATH_INFO')=='/api/cron/worker' else 'billing_webhook' if environ.get('PATH_INFO')=='/api/billing/webhook' else 'api',
            **environ.get('postriff.failure', {})
            }))

    def _handle(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        mutation = method in ("POST", "PUT", "PATCH", "DELETE")
        try:
            bearer = environ.get("HTTP_AUTHORIZATION", "")
            api_bearer = bearer.startswith("Bearer prt_")
            if api_bearer:
                self._runtime().repository.api_tokens.authorize(self._token(environ), method, path.strip("/").split("/"), client_label(environ))
            if path == "/api/health" and method == "GET":
                configured = self.service is not None or all(os.environ.get(key) for key in ("POSTRIFF_DATABASE_URL", "POSTRIFF_SUPABASE_URL", "POSTRIFF_SUPABASE_PUBLISHABLE_KEY", "POSTRIFF_SUPABASE_SECRET_KEY"))
                return self._json(start_response, 200, {"status": "ok", "execution": "phase2-hosted-candidate", "configured": bool(configured), "phase0": "incomplete", "customerValidated": False})
            if path == "/api/catalog" and method == "GET":
                provider = (self.public_auth or {}).get("provider", "supabase")
                return self._json(start_response, 200, {"templates": catalog(), "routes": routes(), "profileMetadata": metadata(), "phase2": True, "authMode": "dev" if provider == "dev" else "supabase", "execution": (self.public_auth or {}).get("execution", "hosted")})
            if path == "/api/privacy/notice" and method == "GET":
                from . import privacy
                return self._json(start_response, 200, privacy.notice())
            # Email-provider webhook and one-click unsubscribe authenticate by signature/token, before the origin guard.
            from .coworker import http as coworker_http
            if (routed := coworker_http.public(self, environ, start_response, method, path)) is not None:
                return routed
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
                # Every route this deployment can write with (fixture, a local CLI where one is installed…).
                try:
                    model_catalog = getattr(self._runtime().ideas, "model_catalog", None)
                except AlphaError:
                    model_catalog = None
                if model_catalog is None:
                    runtime = FixtureAgentRuntime()
                    return self._json(start_response, 200, {"models": runtime.list_supported_models(), "reasoning": runtime.list_supported_reasoning(), "agents": []})
                return self._json(start_response, 200, model_catalog())
            if path == "/api/tools" and method == "GET":
                return self._json(start_response, 200, {"tools": tools.catalog(), "isolation": tools.isolation_status()})
            if path in ("/api/oauth/bluesky/client-metadata.json", "/api/oauth/bluesky/jwks.json") and method == "GET":
                # Bluesky servers fetch Rafii's client identity here (client_id is this URL).
                return self._json(start_response, 200, self._runtime().oauth.bluesky_document(path.rsplit("/", 1)[1]))
            if path == "/api/telegram/webhook" and method == "POST":
                # Authenticated by the secret token Telegram echoes, before the origin guard (like the billing webhook).
                service = self._runtime()
                length = int(environ.get("CONTENT_LENGTH") or "0")
                if not 0 < length <= 65536:
                    raise AlphaError("Webhook body size invalid.", 413)
                raw = environ["wsgi.input"].read(length)
                return self._json(start_response, 200, service.oauth.telegram_webhook(environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", ""), raw))
            oauth_parts = path.strip("/").split("/")
            if len(oauth_parts) == 4 and oauth_parts[:2] == ["api", "oauth"] and oauth_parts[3] == "callback" and method == "GET":
                # Public provider callback: redirect state/code to the signed-in app; never exchange here.
                from urllib.parse import parse_qs
                from .oauth import OAuthService
                query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
                from .providers import ADAPTERS
                if oauth_parts[2] not in ADAPTERS:
                    raise AlphaError('Unknown OAuth provider.', 404)
                # Never send a code to a Host/X-Forwarded-Host supplied by the request.
                configured_base = getattr(getattr(self.service, 'oauth', None), 'public_base_url', None)
                if configured_base is None:
                    configured_base = os.environ.get('POSTRIFF_PUBLIC_BASE_URL', '')
                callback_config = OAuthService(None, None, None, {}, configured_base)
                callback_config.callback_uri(oauth_parts[2])  # fixed HTTPS origin validation; no provider call
                location = OAuthService.callback_redirect(callback_config.public_base_url, oauth_parts[2], query)
                start_response("302 Found", [("Location", location), ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"), ("Content-Length", "0")])
                return [b""]
            if path == "/api/cron/worker" and method == "GET":
                service = self._runtime()
                expected = self.cron_secret or ""
                supplied = environ.get("HTTP_AUTHORIZATION", "")
                if len(expected) < 16 or not hmac.compare_digest(supplied, "Bearer " + expected):
                    raise AlphaError("Cron authorization failed.", 401)
                result = self.worker.tick()
                ideas = getattr(service, 'ideas', None)
                if ideas is not None:
                    site_agent = getattr(service, 'site_agent', None)
                    if site_agent is not None:
                        result['siteAgentRecovery'] = site_agent.recover_stalled()
                    result['writingRecovery'] = ideas.recover_stalled()
                    from .campaign_worker import CampaignWorker
                    result['campaignPreparation'] = CampaignWorker(service).tick_many()
                result["reminders"] = service.run_reminders()
                from .coworker import runtime as coworker_runtime
                result["coworker"] = coworker_runtime.cron(service)
                learning = getattr(service, "learning", None)
                if learning is not None:
                    result["learning"] = learning.sweep()
                time_savings = getattr(service, "time_savings", None)
                if time_savings is not None:
                    result["timeSavings"] = time_savings.maintain()
                if getattr(service, 'identity', None) is not None:
                    from .account_deletion import reconcile_identity
                    result['identityDeletion'] = reconcile_identity(service)
                from .operational_signals import snapshot as operational_snapshot
                try:
                    result['operations'] = operational_snapshot(service.repository.connection_factory)
                except Exception:
                    result['operations'] = {'status':'unavailable', 'notificationDelivery':'not_configured'}
                try:
                    coworker_steps = coworker_runtime.summary(result.get('coworker'))
                except Exception:
                    coworker_steps = {'status': 'unavailable'}
                logging.getLogger('postriff.request').log(logging.INFO if result['operations']['status']=='ok' else logging.WARNING,
                    json.dumps({'event':'cron.completed', 'requestId':environ.get('postriff.request_id'), **result['operations'], 'coworker': coworker_steps}))
                return self._json(start_response, 200, result)
            if not api_bearer:
                self._origin(environ, mutation)
            service = self._runtime()
            token = self._token(environ)
            if path == "/api/ideas/models/rescan" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 200, service.ideas.rescan_models(body.get("workspaceId"), token))
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
                return self._json(start_response, 200, service.sessions(token, client_label=client_label(environ)))
            if path == "/api/auth/sessions/revoke-others" and method == "POST":
                self._body(environ)
                return self._json(start_response, 200, service.revoke_other_sessions(token))
            if path == "/api/auth/mfa" and method in ("POST", "DELETE"):
                self._body(environ)
                return self._json(start_response, 200, service.enable_mfa(token) if method == "POST" else service.disable_mfa(token))
            if path == "/api/me" and method == "GET":
                return self._json(start_response, 200, service.me(token, client_label=client_label(environ)))
            if path == "/api/me" and method == "PATCH":
                return self._json(start_response, 200, service.update_profile(token, self._body(environ)))
            if path == "/api/me/channels" and method == "GET":
                return self._json(start_response, 200, service.my_channels(token))
            if path == "/api/me/security-events" and method == "GET":
                return self._json(start_response, 200, service.security_events(token))
            if path == "/api/me/invitations" and method == "GET":
                return self._json(start_response, 200, service.my_invitations(token))
            if path == "/api/workspaces" and method == "GET":
                return self._json(start_response, 200, service.workspaces(token))
            if path == "/api/invitations/accept" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 200, service.accept_invitation(token, body.get("token"), client=client_address(environ)))
            parts = path.strip("/").split("/")
            if len(parts) in (4, 5) and parts[:2] == ["api", "workspaces"] and parts[3] == "tokens":
                tokens = service.repository.api_tokens
                if len(parts) == 4 and method == "GET":
                    return self._json(start_response, 200, tokens.list(parts[2], token))
                if len(parts) == 4 and method == "POST":
                    return self._json(start_response, 201, tokens.create(parts[2], token, self._body(environ)))
                if len(parts) == 5 and method == "DELETE":
                    return self._json(start_response, 200, tokens.revoke(parts[2], token, parts[4]))
            if len(parts) == 5 and parts[:3] == ["api", "me", "invitations"] and parts[4] in ("accept", "decline") and method == "POST":
                self._body(environ)
                settle = service.accept_my_invitation if parts[4] == "accept" else service.decline_my_invitation
                return self._json(start_response, 200, settle(token, parts[3]))
            if len(parts) == 4 and parts[:2] == ["api", "tools"] and parts[3] == "invoke" and method == "POST":
                body = self._body(environ)
                return self._json(start_response, 200, tools.invoke(parts[2], body.get("version"), body.get("input", {})))
            if len(parts) >= 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "ideas":
                return self._ideas(environ, start_response, service, token, method, parts)
            if len(parts) >= 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "site-agent":
                return self._site_agent(environ, start_response, service, token, method, parts)
            if len(parts) >= 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "agent":
                # The Rafii Agent Runtime (text, voice, images); its routes live in agent_runtime_v2/http.py.
                from .agent_runtime_v2.http import handle as agent_runtime_handle
                return agent_runtime_handle(self, environ, start_response, service, token, method, parts)
            if len(parts) >= 4 and parts[:2] == ["api", "workspaces"] and parts[3] in coworker_http.RESOURCES:
                return coworker_http.handle(self, environ, start_response, service, token, method, parts)
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3:] == ["billing", "credit-packs"] and method == "GET":
                return self._json(start_response, 200, service.billing_credit_packs(parts[2], token))
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "billing" and method == "POST":
                body = self._body(environ)
                if parts[4] == "credit-checkout":
                    return self._json(start_response, 201, service.billing_credit_checkout(parts[2], token, body.get("packId"), body.get("requestId")))
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
            if len(parts) in (4, 5) and parts[:2] == ["api", "workspaces"] and parts[3] == "time-savings":
                # Time Back: the person's own estimate, a separate endpoint from platform analytics (time_savings.py).
                if len(parts) == 4 and method == "GET":
                    from urllib.parse import parse_qs
                    range_key = parse_qs(environ.get("QUERY_STRING", "")).get("range", ["30d"])[0]
                    return self._json(start_response, 200, service.time_savings.summary(parts[2], token, range_key))
                if len(parts) == 5 and parts[4] == "activity" and method == "POST":
                    return self._json(start_response, 200, service.time_savings.activity(parts[2], token, self._body(environ)))
                if len(parts) == 5 and parts[4] == "calibrations" and method == "POST":
                    return self._json(start_response, 200, service.time_savings.calibrate(parts[2], token, self._body(environ)))
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
                    extra = {"inputs": body["input"]} if body.get("input") is not None else {}
                    return self._json(start_response, 201, oauth.start(parts[2], token, parts[4], body.get("capability", "identity"), **extra))
                if len(parts) == 7 and parts[5] == "oauth" and parts[6] == "complete" and method == "POST":
                    body = self._body(environ)
                    extra = {"iss": body["iss"]} if body.get("iss") is not None else {}
                    return self._json(start_response, 200, oauth.complete(parts[2], token, parts[4], body.get("state"), body.get("code"), body.get("error"), **extra))
                if len(parts) == 6 and parts[5] == "destinations" and method == "GET":
                    return self._json(start_response, 200, oauth.destinations(parts[2], token, parts[4]))
                if len(parts) == 6 and parts[5] == "creator-info" and method == "GET":
                    return self._json(start_response, 200, oauth.creator_info(parts[2], token, parts[4]))
                if len(parts) == 6 and parts[5] == "destination" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 200, oauth.choose_destination(parts[2], token, parts[4], body.get("destinationId")))
                if len(parts) == 6 and parts[5] == 'posts' and method == 'POST':
                    return self._json(start_response, 200, oauth.history.preview(parts[2], token, parts[4], self._body(environ)))
                if len(parts) == 7 and parts[5:] == ['posts', 'import'] and method == 'POST':
                    saved = oauth.history.retain(parts[2], token, parts[4], self._body(environ))
                    return self._json(start_response, 200, service._present(saved))
                if len(parts) == 6 and parts[5] == "verify" and method == "POST":
                    self._body(environ)
                    return self._json(start_response, 200, oauth.verify(parts[2], token, parts[4]))
                if len(parts) == 6 and parts[5] == "picture" and method == "GET":
                    # The account's profile picture for previews; the web app asks with ?v=<digest>, so a new picture is a new URL.
                    raw, digest = oauth.picture(parts[2], token, parts[4])
                    start_response("200 OK", [("Content-Type", "image/jpeg"), ("Content-Length", str(len(raw))), ("Cache-Control", "private, max-age=86400"), ("ETag", f'"{digest}"'), ("X-Content-Type-Options", "nosniff")])
                    return [raw]
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
            if len(parts) in (5, 6, 7) and parts[:2] == ["api", "workspaces"] and parts[3] == "memory":
                # Learned preferences (preference-learning design §6): proposals a person decides, versions they manage.
                workspace_id, learning = parts[2], service.learning
                if len(parts) == 5 and parts[4] == "proposals" and method == "GET":
                    return self._json(start_response, 200, learning.proposals(service.repository, workspace_id, token))
                if len(parts) == 7 and parts[4] == "proposals" and parts[6] == "decide" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 200, learning.decide(service.repository, workspace_id, token, body.get("expectedRevision"), parts[5], body.get("decision"), body.get("statement")))
                if len(parts) == 6 and parts[4] == "versions" and method == "PATCH":
                    body = self._body(environ)
                    return self._json(start_response, 200, learning.update_version(service.repository, workspace_id, token, body.get("expectedRevision"), parts[5], body.get("status")))
                raise AlphaError("This hosted route is unavailable.", 404)
            if len(parts) in (3, 4) and parts[:2] == ["api", "workspaces"]:
                workspace_id = parts[2]
                if len(parts) == 3 and method == "GET":
                    return self._json(start_response, 200, service.get(workspace_id, token))
                if len(parts) == 4 and parts[3] == "members" and method == "GET":
                    return self._json(start_response, 200, service.members(workspace_id, token))
                if len(parts) == 4 and parts[3] == "audit" and method == "GET":
                    return self._json(start_response, 200, service.audit_events(workspace_id, token))
                if len(parts) == 4 and parts[3] == "memory" and method == "GET":
                    return self._json(start_response, 200, service.ideas.memory_files(workspace_id, token))
                if len(parts) == 4 and parts[3] == "invitations" and method == "GET":
                    return self._json(start_response, 200, service.invitations(workspace_id, token))
                if len(parts) == 4 and parts[3] == "invitations" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 201, service.invite(workspace_id, token, body.get("email"), body.get("role"), body.get("permissions", {})))
                if len(parts) == 4 and parts[3] == "leave" and method == "POST":
                    self._body(environ)
                    return self._json(start_response, 200, service.leave_workspace(workspace_id, token))
                if len(parts) == 4 and parts[3] == "transfer-ownership" and method == "POST":
                    body = self._body(environ)
                    return self._json(start_response, 200, service.transfer_ownership(workspace_id, token, body.get("newOwnerId")))
                if len(parts) == 4 and parts[3] == "actions" and method == "POST":
                    body = self._body(environ)
                    action, payload, revision = body.get("action"), body.get("payload", {}), body.get("expectedRevision")
                    if action in RETIRED_WRITING_ACTIONS:
                        # The alpha template writer (FixtureAdapter) behind these bypassed Rafii's writer; drafts come from
                        # ideas turns, which choose the writer the person picked (or the managed default).
                        raise AlphaError("This way of drafting was retired. Write from Home or ask Rafii.", 410, code="action_retired")
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
            return self._json(start_response, error.status, {"error": str(error), "code": error.code})
        except Exception as error:
            # Exception text/tracebacks may contain third-party payloads or credentials: only the class and a
            # route pattern with identifiers masked are kept for correlation.
            environ["postriff.failure"] = {"exceptionType": type(error).__name__, "routePattern": route_pattern(path)}
            return self._json(start_response, 500, {"error": "Something went wrong on our side. Check what was saved before trying again.", "code": "internal_error"})


app = HostedApplication()
