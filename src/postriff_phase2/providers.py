"""OAuth provider adapters for the selected launch connectors (connector-audit.md, D12).

LinkedIn member posting, Threads, Instagram professional. Each adapter only builds
requests and parses responses through an injected transport; nothing is mounted unless
its client credentials exist in server secrets, and `production_reviewed` is true only
when the provider's review gate has been passed and the flag is set explicitly.
"""
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from postriff_alpha.domain import AlphaError

GRAPH_VERSION = "v24.0"  # current Graph API version read in the 2026-09-15 audit; re-verify at review time


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise AlphaError("Provider redirects are not allowed.", 502)


def http_transport(method, url, headers=None, form=None, body=None):
    """Bounded HTTPS transport: 20 s timeout, no redirects, 256 KB response cap, JSON or form."""
    if not url.startswith("https://"):
        raise AlphaError("Provider requests must use HTTPS.", 502)
    data = urlencode(form).encode() if form is not None else (json.dumps(body).encode() if body is not None else None)
    request_headers = {"Accept": "application/json", **(headers or {})}
    if form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20, context=ssl.create_default_context()) as response:
            raw = response.read(262145)
            status, response_headers = response.status, dict(response.headers)
    except HTTPError as error:
        raw, status, response_headers = error.read(262144), error.code, dict(error.headers)
    except (URLError, TimeoutError, OSError) as error:
        raise AlphaError("The provider is temporarily unreachable.", 503) from error
    if len(raw) > 262144:
        raise AlphaError("Provider response limit exceeded.", 502)
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = {"raw": raw[:2000].decode("utf-8", "replace")}
    return {"status": status, "headers": {k.lower(): v for k, v in response_headers.items()}, "body": parsed}


class OAuthProvider:
    id = ""
    platform = ""
    capability_version = 1
    native_schedule = False
    assisted_fallback = True
    SCOPES = {}
    EXPLAIN = {}

    def __init__(self, client_id, client_secret, transport=None, production_reviewed=False):
        if not client_id or not client_secret:
            raise AlphaError(f"{self.platform} client credentials are required.", 503)
        self.client_id, self.client_secret = client_id, client_secret
        self.transport = transport or http_transport
        self.production_reviewed = bool(production_reviewed)

    def capability_scopes(self, capability):
        return list(self.SCOPES.get(capability, []))

    def explain(self, capability):
        return self.EXPLAIN.get(capability, "PostRiff will act on this account only when you approve an exact action.")

    def revoke(self, token):
        return False

    @staticmethod
    def _ok(response, *keys):
        body = response.get("body", {})
        if response.get("status") != 200 or not isinstance(body, dict) or any(not body.get(k) for k in keys):
            raise AlphaError("The provider did not complete this authorization step.", 502)
        return body


class LinkedInProvider(OAuthProvider):
    id, platform, capability_version = "linkedin", "LinkedIn", 4
    AUTH = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
    REVOKE = "https://www.linkedin.com/oauth/v2/revoke"
    USERINFO = "https://api.linkedin.com/v2/userinfo"
    # Member posting is self-serve ("Share on LinkedIn"); org/analytics/comments need the Community Management API, not held.
    SCOPES = {"identity": ["openid", "profile"], "publish": ["openid", "profile", "w_member_social"], "schedule": ["openid", "profile", "w_member_social"]}
    EXPLAIN = {"publish": "PostRiff will publish posts to your LinkedIn member profile only when you approve each exact post. Organization pages and analytics are not requested."}

    def authorize_url(self, redirect, state, challenge, scopes):
        # LinkedIn's documented flow has no PKCE parameter; the verifier still binds our transaction server-side.
        return self.AUTH + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect, "state": state, "scope": " ".join(scopes)})

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": self.client_id, "client_secret": self.client_secret}), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token"), "expiresIn": body.get("expires_in"), "scopes": (body.get("scope") or "").split() or None}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.USERINFO, headers={"Authorization": "Bearer " + access_token}), "sub")
        return {"providerAccountId": "urn:li:person:" + str(body["sub"]), "handle": body.get("name") or str(body["sub"]), "accountType": "member"}

    def refresh(self, refresh_token):
        # Refresh tokens are issued only to approved partners; otherwise the customer re-authorizes every 60 days.
        body = self._ok(self.transport("POST", self.TOKEN, form={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id, "client_secret": self.client_secret}), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token", refresh_token), "expiresIn": body.get("expires_in")}

    def revoke(self, token):
        return self.transport("POST", self.REVOKE, form={"client_id": self.client_id, "client_secret": self.client_secret, "token": token}).get("status") == 200


class ThreadsProvider(OAuthProvider):
    id, platform, capability_version = "threads", "Threads", 1
    AUTH = "https://threads.net/oauth/authorize"
    TOKEN = "https://graph.threads.net/oauth/access_token"
    LONG_LIVED = "https://graph.threads.net/access_token"
    REFRESH = "https://graph.threads.net/refresh_access_token"
    ME = f"https://graph.threads.net/{GRAPH_VERSION}/me"
    SCOPES = {"identity": ["threads_basic"], "publish": ["threads_basic", "threads_content_publish"], "schedule": ["threads_basic", "threads_content_publish"], "analytics": ["threads_basic", "threads_manage_insights"], "comments_read": ["threads_basic", "threads_read_replies"], "reply": ["threads_basic", "threads_manage_replies"]}
    EXPLAIN = {"publish": "PostRiff will create Threads posts on this profile only when you approve each exact post.", "analytics": "PostRiff will read views, likes, replies, reposts and quotes for posts it created.", "comments_read": "PostRiff will read replies to your posts.", "reply": "PostRiff will post replies only after you approve the exact text."}

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "scope": ",".join(scopes), "response_type": "code", "state": state})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}), "access_token", "user_id")
        long_lived = self._ok(self.transport("GET", self.LONG_LIVED + "?" + urlencode({"grant_type": "th_exchange_token", "client_secret": self.client_secret, "access_token": short["access_token"]})), "access_token")
        # Long-lived tokens (60 days) refresh with themselves; we store the same value as the refresh secret.
        return {"accessToken": long_lived["access_token"], "refreshToken": long_lived["access_token"], "expiresIn": long_lived.get("expires_in", 5184000), "scopes": None, "userId": str(short["user_id"])}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"fields": "id,username", "access_token": access_token})), "id")
        return {"providerAccountId": str(body["id"]), "handle": "@" + body["username"] if body.get("username") else str(body["id"]), "accountType": "profile"}

    def refresh(self, refresh_token):
        body = self._ok(self.transport("GET", self.REFRESH + "?" + urlencode({"grant_type": "th_refresh_token", "access_token": refresh_token})), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body["access_token"], "expiresIn": body.get("expires_in", 5184000)}


class InstagramProvider(OAuthProvider):
    id, platform, capability_version = "instagram", "Instagram", 1
    AUTH = "https://www.instagram.com/oauth/authorize"
    TOKEN = "https://api.instagram.com/oauth/access_token"
    LONG_LIVED = "https://graph.instagram.com/access_token"
    REFRESH = "https://graph.instagram.com/refresh_access_token"
    ME = f"https://graph.instagram.com/{GRAPH_VERSION}/me"
    SCOPES = {"identity": ["instagram_business_basic"], "publish": ["instagram_business_basic", "instagram_business_content_publish"], "schedule": ["instagram_business_basic", "instagram_business_content_publish"], "analytics": ["instagram_business_basic", "instagram_business_manage_insights"], "comments_read": ["instagram_business_basic", "instagram_business_manage_comments"], "reply": ["instagram_business_basic", "instagram_business_manage_comments"]}
    EXPLAIN = {"publish": "PostRiff will publish image posts to this professional account only when you approve each exact post (limit 100 per 24 hours).", "analytics": "PostRiff will read reach, views, likes, comments, saves and shares for posts it created.", "comments_read": "PostRiff will read comments on your posts.", "reply": "PostRiff will reply only after you approve the exact text."}

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "scope": ",".join(scopes), "response_type": "code", "state": state})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}), "access_token", "user_id")
        long_lived = self._ok(self.transport("GET", self.LONG_LIVED + "?" + urlencode({"grant_type": "ig_exchange_token", "client_secret": self.client_secret, "access_token": short["access_token"]})), "access_token")
        return {"accessToken": long_lived["access_token"], "refreshToken": long_lived["access_token"], "expiresIn": long_lived.get("expires_in", 5184000), "scopes": short.get("permissions") if isinstance(short.get("permissions"), list) else None, "userId": str(short["user_id"])}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"fields": "id,username,account_type", "access_token": access_token})), "id")
        return {"providerAccountId": str(body["id"]), "handle": "@" + body["username"] if body.get("username") else str(body["id"]), "accountType": (body.get("account_type") or "professional").lower()}

    def refresh(self, refresh_token):
        body = self._ok(self.transport("GET", self.REFRESH + "?" + urlencode({"grant_type": "ig_refresh_token", "access_token": refresh_token})), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body["access_token"], "expiresIn": body.get("expires_in", 5184000)}


ADAPTERS = {"linkedin": LinkedInProvider, "threads": ThreadsProvider, "instagram": InstagramProvider}


def registry_from_environment(values, transport=None):
    """Mount an adapter only when its client credentials exist. Reviewed flag is explicit."""
    registry = {}
    for provider_id, cls in ADAPTERS.items():
        prefix = f"POSTRIFF_OAUTH_{provider_id.upper()}_"
        client_id, secret = values.get(prefix + "CLIENT_ID"), values.get(prefix + "CLIENT_SECRET")
        if client_id and secret:
            registry[provider_id] = cls(client_id, secret, transport=transport, production_reviewed=values.get(prefix + "REVIEWED", "").lower() == "true")
    return registry
