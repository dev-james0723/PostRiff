"""OAuth provider adapters for the selected launch connectors (connector-audit.md, D12).

LinkedIn member posting, Threads, Instagram professional. Each adapter only builds
requests and parses responses through an injected transport; nothing is mounted unless
its client credentials exist in server secrets, and `production_reviewed` is true only
when the provider's review gate has been passed and the flag is set explicitly.
"""
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
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
        with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=20) as response:
            raw = response.read(262145)
            status, response_headers = response.status, dict(response.headers)
    except HTTPError as error:
        with error:
            raw, status, response_headers = error.read(262145), error.code, dict(error.headers)
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
        self.execution_enabled = True

    def capability_scopes(self, capability):
        return list(self.SCOPES.get(capability, []))

    def explain(self, capability):
        return self.EXPLAIN.get(capability, "Rafii will act on this account only when you approve an exact action.")

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
    EXPLAIN = {"publish": "Rafii will publish posts to your LinkedIn member profile only when you approve each exact post. Organization pages and analytics are not requested."}

    history_approved = False

    def capability_scopes(self, capability):
        if capability == "posts_read":
            return ["openid", "profile", "r_member_social"] if self.history_approved else []
        return super().capability_scopes(capability)

    def explain(self, capability):
        if capability == "identity":
            return "Connect your LinkedIn member identity only. This does not grant publishing or historical-post access."
        if capability == "posts_read":
            return "Read your own LinkedIn posts for a sample picker. You separately choose and approve samples for voice analysis. This requires LinkedIn's restricted r_member_social approval; no publishing permission is requested."
        return super().explain(capability)

    def authorize_url(self, redirect, state, challenge, scopes):
        # LinkedIn's documented flow has no PKCE parameter; the verifier still binds our transaction server-side.
        return self.AUTH + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect, "state": state, "scope": " ".join(scopes)})

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": self.client_id, "client_secret": self.client_secret}), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token"), "expiresIn": body.get("expires_in"), "scopes": re.split(r'[\s,]+', body['scope'].strip()) if isinstance(body.get('scope'), str) and body['scope'].strip() else None}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.USERINFO, headers={"Authorization": "Bearer " + access_token}), "sub")
        # `picture` is part of the OpenID `profile` claims already requested; previews draw it (account_pictures.py).
        return {"providerAccountId": "urn:li:person:" + str(body["sub"]), "handle": body.get("name") or str(body["sub"]), "accountType": "member", "pictureUrl": body.get("picture")}

    def inspect_scopes(self, access_token, expected_account_id):
        # Identity is independently checked by the caller. Introspection binds token to this app.
        body = self._ok(self.transport("POST", "https://www.linkedin.com/oauth/v2/introspectToken", form={"client_id": self.client_id, "client_secret": self.client_secret, "token": access_token}))
        if body.get("active") is not True or body.get("client_id") != self.client_id or not isinstance(body.get("scope"), str):
            return None
        return list(dict.fromkeys(scope for scope in re.split(r"[,\s]+", body["scope"].strip()) if scope))

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
    EXPLAIN = {"publish": "Rafii will create Threads posts on this profile only when you approve each exact post.", "analytics": "Rafii will read views, likes, replies, reposts and quotes for posts it created.", "comments_read": "Rafii will read replies to your posts.", "reply": "Rafii will post replies only after you approve the exact text."}

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "scope": ",".join(scopes), "response_type": "code", "state": state})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}), "access_token", "user_id")
        long_lived = self._ok(self.transport("GET", self.LONG_LIVED + "?" + urlencode({"grant_type": "th_exchange_token", "client_secret": self.client_secret, "access_token": short["access_token"]})), "access_token")
        # Long-lived tokens (60 days) refresh with themselves; we store the same value as the refresh secret.
        return {"accessToken": long_lived["access_token"], "refreshToken": long_lived["access_token"], "expiresIn": long_lived.get("expires_in", 5184000), "scopes": None, "userId": str(short["user_id"])}

    def inspect_scopes(self, access_token, expected_account=None):
        # Meta's official Threads Postman collection documents /debug_token with OAuth bearer auth.
        response = self.transport('GET', 'https://graph.threads.net/debug_token?' + urlencode({'input_token':access_token}), headers={'Authorization':'Bearer ' + access_token})
        data = response.get('body', {}).get('data', {})
        scopes = data.get('scopes') if isinstance(data, dict) else None
        if response.get('status') != 200 or data.get('is_valid') is not True or not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            return None
        if expected_account and str(data.get('user_id')) != str(expected_account):
            return None
        return sorted(set(scopes))

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"fields": "id,username,threads_profile_picture_url", "access_token": access_token})), "id")
        return {"providerAccountId": str(body["id"]), "handle": "@" + body["username"] if body.get("username") else str(body["id"]), "accountType": "profile", "pictureUrl": body.get("threads_profile_picture_url")}

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
    EXPLAIN = {"publish": "Rafii will publish image posts to this professional account only when you approve each exact post (limit 100 per 24 hours).", "analytics": "Rafii will read reach, views, likes, comments, saves and shares for posts it created.", "comments_read": "Rafii will read comments on your posts.", "reply": "Rafii will reply only after you approve the exact text."}

    def capability_scopes(self, capability):
        if capability == "posts_read":
            return ["instagram_business_basic"]
        return super().capability_scopes(capability)

    def explain(self, capability):
        if capability in ("identity", "posts_read"):
            return "Connect your Instagram Creator or Business account and read its profile and media. No Facebook Page or publishing permission is requested. Selecting samples and allowing AI processing are separate choices."
        return super().explain(capability)

    def verify_read_access(self, access_token, expected_account_id):
        """Prove basic media read access, not undocumented publish/insight scopes.

        Instagram Login is not Facebook Login: do not invent a Facebook app-token
        introspection call. An authenticated account match and a successful bounded
        media read prove only instagram_business_basic. Never infer write permissions.
        """
        from .social_history import fetch_page
        identity = self.identity(access_token)
        if identity['providerAccountId'] != expected_account_id:
            raise AlphaError("The connected Instagram account changed. Reconnect it.", 409)
        fetch_page(self, access_token, expected_account_id, limit=1)
        return ['instagram_business_basic']

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "scope": ",".join(scopes), "response_type": "code", "state": state})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}), "access_token", "user_id")
        long_lived = self._ok(self.transport("GET", self.LONG_LIVED + "?" + urlencode({"grant_type": "ig_exchange_token", "client_secret": self.client_secret, "access_token": short["access_token"]})), "access_token")
        return {"accessToken": long_lived["access_token"], "refreshToken": long_lived["access_token"], "expiresIn": long_lived.get("expires_in", 5184000), "scopes": short.get("permissions") if isinstance(short.get("permissions"), list) else None, "userId": str(short["user_id"])}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"fields": "id,username,account_type,profile_picture_url", "access_token": access_token})), "id")
        return {"providerAccountId": str(body["id"]), "handle": "@" + body["username"] if body.get("username") else str(body["id"]), "accountType": (body.get("account_type") or "professional").lower(), "pictureUrl": body.get("profile_picture_url")}

    def refresh(self, refresh_token):
        body = self._ok(self.transport("GET", self.REFRESH + "?" + urlencode({"grant_type": "ig_refresh_token", "access_token": refresh_token})), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body["access_token"], "expiresIn": body.get("expires_in", 5184000)}


ADAPTERS = {"linkedin": LinkedInProvider, "threads": ThreadsProvider, "instagram": InstagramProvider}


class ProviderRegistry(dict):
    """Adapters plus presence-only diagnostics, including when no adapter can mount."""
    def __init__(self):
        super().__init__()
        self.diagnostics = {}


def _credential_shape(value):
    # Shape is not provider authentication. Never include the supplied value in an error.
    return (isinstance(value, str) and 0 < len(value) <= 8192
            and not any(character.isspace() for character in value)
            and not value.startswith('<')
            and value.lower() not in {'change-me', 'changeme', 'replace-me', 'placeholder', 'todo'})


def registry_from_environment(values, transport=None):
    """Only valid-shaped complete pairs mount. Review is an explicit operator declaration."""
    registry = ProviderRegistry()
    for provider_id, cls in ADAPTERS.items():
        prefix = f"POSTRIFF_OAUTH_{provider_id.upper()}_"
        client_id, secret = values.get(prefix + "CLIENT_ID"), values.get(prefix + "CLIENT_SECRET")
        presence = {'clientId': client_id is not None, 'clientSecret': secret is not None}
        missing = [prefix + suffix for suffix, present in (('CLIENT_ID', presence['clientId']), ('CLIENT_SECRET', presence['clientSecret'])) if not present]
        valid = _credential_shape(client_id) and _credential_shape(secret)
        state = 'not_configured' if len(missing) == 2 else 'partial_configuration' if missing else 'configured' if valid else 'invalid_configuration'
        registry.diagnostics[provider_id] = {'configurationState': state, 'credentialPresence': presence, 'missingVariables': missing}
        if valid:
            registry[provider_id] = cls(client_id, secret, transport=transport, production_reviewed=str(values.get(prefix + "REVIEWED", "")).lower() == "true")
            registry[provider_id].execution_enabled = str(values.get(prefix + "DISABLED", "")).lower() != "true"
            if provider_id == "linkedin":
                # Allows requesting the restricted scope, never substitutes for a real grant.
                registry[provider_id].history_approved = str(values.get(prefix + "HISTORY_APPROVED", "")).lower() == "true"
    return registry
