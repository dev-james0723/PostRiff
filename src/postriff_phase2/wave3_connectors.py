"""Hosted adapters for Facebook Pages, YouTube, TikTok and Pinterest (Rafii Hosted Channels Plan, Wave 3).

Stored grants are small versioned JSON documents, encrypted like any token by oauth.CredentialVault:
- Facebook: the person's long-lived user token and, once chosen, one Page and its Page token (Page tokens made from a
  long-lived user token do not expire, so publishing outlives the 60-day user token).
- YouTube, TikTok, Pinterest: the access token plus the scopes the provider's own token response granted.
Upload URLs a provider returns are used only on that provider's own hosts. Provider error text and tokens never reach an
AlphaError message.
"""
import base64
import hashlib
import hmac
import json
import math
import re
import time
from urllib.parse import quote, urlencode, urlsplit
from postriff_alpha.domain import AlphaError
from .provider_base import GRAPH_VERSION, OAuthProvider, default_transport, fixed_https_origin
from .social_connectors import _load


def _basic(client_id, client_secret):
    return "Basic " + base64.b64encode(f"{quote(client_id, safe='')}:{quote(client_secret, safe='')}".encode()).decode()


def _scopes(value, separator=None):
    if isinstance(value, str):
        return [s for s in re.split(separator or r"[\s,]+", value.strip()) if s]
    return None


def provider_host(url, allowed):
    """An upload URL a provider handed back, accepted only on the provider's own HTTPS hosts."""
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        port = parts.port if parts else None
    except ValueError:
        parts, port = None, None
    host = (parts.hostname or "").lower() if parts else ""
    if not parts or parts.scheme != "https" or port not in (None, 443) or parts.username or parts.password \
            or not any(host == a or (a.startswith(".") and host.endswith(a)) for a in allowed):
        raise AlphaError("The provider returned an upload address Rafii can't use.", 502)
    return url


# --- Facebook Pages ---------------------------------------------------------------------------------------------
class FacebookPagesProvider(OAuthProvider):
    id, platform, capability_version = "facebook", "Facebook", 1
    GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
    AUTH = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
    SCOPES = {"identity": ["pages_show_list", "business_management"],
              "publish": ["pages_show_list", "business_management", "pages_read_engagement", "pages_manage_posts"],
              "schedule": ["pages_show_list", "business_management", "pages_read_engagement", "pages_manage_posts"]}
    EXPLAIN = {"identity": "Connect your Facebook account and choose a Page. Rafii posts nothing until you approve a post.",
               "publish": "Rafii will post to the Facebook Page you choose only when you approve each exact post."}
    account_requirement = "A Facebook Page where you can create content."
    publish_scope = "pages_manage_posts"
    publish_required = frozenset({"pages_manage_posts", "pages_read_engagement"})
    # Rafii's worker publishes at the approved time; nothing is scheduled on Facebook itself.
    native_schedule = False
    non_expiring = True
    has_destinations = True
    destination_scope, destination_label = "connection", "Page"
    # Revoking removes Rafii for this Facebook person, which every workspace they connected shares.
    shared_remote = True

    def __init__(self, client_id, client_secret, config_id=None, transport=None, production_reviewed=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        self.config_id = config_id

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        config = values.get("POSTRIFF_FACEBOOK_LOGIN_CONFIG_ID")
        if config is not None and not re.fullmatch(r"\d{5,25}", str(config)):
            return None, {**diagnostic, "configurationState": "invalid_configuration"}
        return (cls(client_id, secret, config_id=config, transport=transport) if valid else None), diagnostic

    def _proof(self, access_token):
        # appsecret_proof binds every Graph call to Rafii's app, so a leaked token alone is not enough.
        return hmac.new(self.client_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()

    def graph(self, method, path, access_token, params=None, form=None):
        query = {**(params or {}), "access_token": access_token, "appsecret_proof": self._proof(access_token)}
        if method in ("GET", "DELETE"):
            return self.transport(method, f"{self.GRAPH}{path}?" + urlencode(query))
        return self.transport(method, f"{self.GRAPH}{path}", form={**(form or {}), **query})

    def authorize_url(self, redirect, state, challenge, scopes):
        params = {"client_id": self.client_id, "redirect_uri": redirect, "state": state, "response_type": "code"}
        if self.config_id:
            params["config_id"] = self.config_id  # Facebook Login for Business: the configuration names the permissions
        else:
            params["scope"] = ",".join(scopes)
        return self.AUTH + "?" + urlencode(params)

    def _pages(self, user_token):
        response = self.graph("GET", "/me/accounts", user_token, {"fields": "id,name,tasks,access_token", "limit": "100"})
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or not isinstance(body.get("data"), list):
            raise AlphaError("Facebook didn't list your Pages. Try again.", 502)
        return [{"id": str(p["id"]), "name": str(p.get("name") or p["id"]), "token": p["access_token"]}
                for p in body["data"] if isinstance(p, dict) and re.fullmatch(r"\d{5,25}", str(p.get("id", "")))
                and "CREATE_CONTENT" in (p.get("tasks") or []) and isinstance(p.get("access_token"), str)]

    def _granted(self, user_token):
        response = self.graph("GET", "/me/permissions", user_token)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or not isinstance(body.get("data"), list):
            return None
        return sorted({p["permission"] for p in body["data"] if isinstance(p, dict) and p.get("status") == "granted" and isinstance(p.get("permission"), str)})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", f"{self.GRAPH}/oauth/access_token", form={"client_id": self.client_id, "client_secret": self.client_secret,
                                                                                        "redirect_uri": redirect, "code": code}), "access_token")
        long = self._ok(self.transport("POST", f"{self.GRAPH}/oauth/access_token", form={"grant_type": "fb_exchange_token", "client_id": self.client_id,
                                                                                       "client_secret": self.client_secret, "fb_exchange_token": short["access_token"]}), "access_token")
        user_token = long["access_token"]
        me = self._ok(self.graph("GET", "/me", user_token, {"fields": "id,name"}), "id")
        session = {"v": 1, "user": str(me["id"]), "name": me.get("name"), "ut": user_token, "scope": self._granted(user_token) or [], "page": None}
        pages = self._pages(user_token)
        if len(pages) == 1:
            session["page"] = pages[0]  # the only Page this person granted: no choice to make
        return {"accessToken": json.dumps(session), "refreshToken": None, "expiresIn": None, "scopes": session["scope"] or None}

    @staticmethod
    def session(access_token):
        session = _load(access_token)
        if not re.fullmatch(r"\d{1,25}", str(session.get("user", ""))) or not isinstance(session.get("ut"), str):
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def identity(self, access_token):
        """The connection is the Facebook person; once a Page is chosen its own token proves access."""
        session = self.session(access_token)
        page = session.get("page")
        if isinstance(page, dict):
            body = self._ok(self.graph("GET", f"/{page['id']}", page["token"], {"fields": "id,name"}), "id")
            if str(body["id"]) != page["id"]:
                raise AlphaError("The provider did not complete this authorization step.", 502)
            return {"providerAccountId": session["user"], "handle": str(body.get("name") or page["name"]), "accountType": "page"}
        body = self._ok(self.graph("GET", "/me", session["ut"], {"fields": "id,name"}), "id")
        if str(body["id"]) != session["user"]:
            raise AlphaError("The connected Facebook account changed. Reconnect it.", 409)
        return {"providerAccountId": session["user"], "handle": str(body.get("name") or session["user"]), "accountType": "person"}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self.session(access_token)
        if expected_account_id and session["user"] != expected_account_id:
            return None
        live = self._granted(session["ut"])
        if live is not None:
            return live
        # The 60-day user token may have lapsed while the Page token keeps working: then the grant recorded at connect
        # time stands, but only after the Page token itself answers.
        if isinstance(session.get("page"), dict):
            try:
                self.identity(access_token)
            except AlphaError:
                return None
            return sorted(set(session.get("scope") or []))
        return None

    def destinations(self, access_token):
        session = self.session(access_token)
        chosen = (session.get("page") or {}).get("id")
        return [{"id": p["id"], "name": p["name"], "kind": "page", "selected": p["id"] == chosen} for p in self._pages(session["ut"])]

    def with_destination(self, access_token, destination_id):
        session = self.session(access_token)
        page = next((p for p in self._pages(session["ut"]) if p["id"] == str(destination_id)), None)
        if page is None:
            raise AlphaError("Choose a Page you can create content on.", 409)
        return json.dumps({**session, "page": page})

    def revoke(self, token):
        response = self.graph("DELETE", "/me/permissions", self.session(token)["ut"])
        return response.get("status") == 200 and isinstance(response.get("body"), dict) and response["body"].get("success") is True


# --- YouTube ----------------------------------------------------------------------------------------------------
from .youtube.provider import YouTubeProvider  # stable adapter import for the shared provider registry


# --- TikTok -----------------------------------------------------------------------------------------------------
class TikTokProvider(OAuthProvider):
    id, platform, capability_version = "tiktok", "TikTok", 1
    AUTH = "https://www.tiktok.com/v2/auth/authorize/"
    API = "https://open.tiktokapis.com"
    SCOPES = {"identity": ["user.info.basic"], "publish": ["user.info.basic", "video.publish"], "schedule": ["user.info.basic", "video.publish"]}
    EXPLAIN = {"identity": "Connect your TikTok account. Rafii reads only your display name and avatar.",
               "publish": "Rafii will post to this TikTok account only when you approve each exact post. Until TikTok audits Rafii, posts are private: only you can see them."}
    account_requirement = "A TikTok account. Until TikTok audits Rafii, posts are private."
    publish_scope = "video.publish"
    publish_required = frozenset({"video.publish"})
    refresh_margin = 300  # access tokens last 24 hours
    UPLOAD_HOSTS = (".tiktokapis.com",)
    MIN_CHUNK, MAX_CHUNK = 5 * 1024 * 1024, 64 * 1024 * 1024

    def __init__(self, client_id, client_secret, hex_pkce=False, transport=None, production_reviewed=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        # TikTok's Web Login Kit documents no PKCE; its desktop PKCE hex-encodes SHA-256(verifier) instead of RFC 7636's
        # base64url. Off by default; POSTRIFF_TIKTOK_HEX_PKCE=true turns the hex form on if the Sandbox shows it is needed.
        self.hex_pkce = bool(hex_pkce)

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        hex_pkce = str(values.get("POSTRIFF_TIKTOK_HEX_PKCE", "")).lower() == "true"
        return (cls(client_id, secret, hex_pkce=hex_pkce, transport=transport) if valid else None), diagnostic

    @staticmethod
    def hex_challenge(challenge):
        """The same SHA-256 digest as the RFC 7636 challenge Rafii made, written in hex the way TikTok's desktop flow wants."""
        return base64.urlsafe_b64decode(challenge + "=" * (-len(challenge) % 4)).hex()

    def authorize_url(self, redirect, state, challenge, scopes):
        # The env names say CLIENT_ID; TikTok calls the same value client_key. `state` is bound server-side to the
        # transaction (member, workspace, single use), which is what protects this redirect without PKCE.
        params = {"client_key": self.client_id, "scope": ",".join(scopes), "response_type": "code", "redirect_uri": redirect, "state": state}
        if self.hex_pkce:
            params.update(code_challenge=self.hex_challenge(challenge), code_challenge_method="S256")
        return self.AUTH + "?" + urlencode(params)

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = _scopes(body.get("scope")) or []
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes, "openId": body.get("open_id")}),
                "refreshToken": body.get("refresh_token") or refresh_token, "expiresIn": body.get("expires_in"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        form = {"client_key": self.client_id, "client_secret": self.client_secret, "code": code, "grant_type": "authorization_code", "redirect_uri": redirect}
        if self.hex_pkce:
            form["code_verifier"] = verifier
        return self._grant(self._ok(self.transport("POST", f"{self.API}/v2/oauth/token/", form=form), "access_token"))

    def refresh(self, refresh_token):
        body = self._ok(self.transport("POST", f"{self.API}/v2/oauth/token/", form={"client_key": self.client_id, "client_secret": self.client_secret,
                                                                                   "grant_type": "refresh_token", "refresh_token": refresh_token}), "access_token")
        return self._grant(body, refresh_token)

    @staticmethod
    def bearer(access_token):
        return _load(access_token)["at"]

    def api(self, access_token, method, path, **kwargs):
        headers = {"Authorization": "Bearer " + self.bearer(access_token), **kwargs.pop("headers", {})}
        if kwargs.get("body") is not None:
            headers.setdefault("Content-Type", "application/json; charset=UTF-8")
        return self.transport(method, self.API + path, headers=headers, **kwargs)

    def identity(self, access_token):
        response = self.api(access_token, "GET", "/v2/user/info/?" + urlencode({"fields": "open_id,avatar_url,display_name"}))
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        user = ((body.get("data") or {}).get("user") or {}) if isinstance(body.get("data"), dict) else {}
        if response.get("status") != 200 or not isinstance(user.get("open_id"), str) or not user["open_id"]:
            raise AlphaError("TikTok could not confirm this account right now.", 502)
        return {"providerAccountId": user["open_id"], "handle": str(user.get("display_name") or user["open_id"]), "accountType": "profile",
                "pictureUrl": user.get("avatar_url") if isinstance(user.get("avatar_url"), str) else None}

    def inspect_scopes(self, access_token, expected_account_id=None):
        """TikTok offers no token introspection: the scopes its own token response granted, for the same account."""
        try:
            session = _load(access_token)
        except AlphaError:
            return None
        if expected_account_id and session.get("openId") and session["openId"] != expected_account_id:
            return None
        scopes = session.get("scope")
        return sorted(set(scopes)) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else None

    def revoke(self, token):
        return self.transport("POST", f"{self.API}/v2/oauth/revoke/", form={"client_key": self.client_id, "client_secret": self.client_secret,
                                                                           "token": self.bearer(token)}).get("status") == 200

    def creator_info(self, access_token):
        """What TikTok lets this creator do right now (Content Sharing Guidelines: query before rendering and before posting)."""
        response = self.api(access_token, "POST", "/v2/post/publish/creator_info/query/", body={})
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        if response.get("status") != 200 or error.get("code") not in (None, "ok"):
            return {"ok": False, "status": response.get("status"), "code": error.get("code"), "message": error.get("message")}
        options = [o for o in data.get("privacy_level_options") or [] if isinstance(o, str)]
        return {"ok": True, "nickname": str(data.get("creator_nickname") or ""), "username": str(data.get("creator_username") or ""),
                "avatarUrl": data.get("creator_avatar_url") if isinstance(data.get("creator_avatar_url"), str) else None,
                "privacyLevelOptions": options, "commentDisabled": data.get("comment_disabled") is True,
                "duetDisabled": data.get("duet_disabled") is True, "stitchDisabled": data.get("stitch_disabled") is True,
                "maxVideoPostDurationSec": data.get("max_video_post_duration_sec") if isinstance(data.get("max_video_post_duration_sec"), int) else None}

    @classmethod
    def chunks(cls, size):
        """TikTok FILE_UPLOAD chunking: one chunk under 5 MB, else 5-64 MB chunks with the remainder folded into the last."""
        if size <= 0:
            raise AlphaError("The video is empty.", 409)
        if size < cls.MIN_CHUNK:
            return size, 1
        chunk = min(cls.MAX_CHUNK, size)
        count = max(1, size // chunk)
        return chunk, count


# --- Pinterest --------------------------------------------------------------------------------------------------
class PinterestProvider(OAuthProvider):
    id, platform, capability_version = "pinterest", "Pinterest", 1
    AUTH = "https://www.pinterest.com/oauth/"
    API, SANDBOX = "https://api.pinterest.com", "https://api-sandbox.pinterest.com"
    SCOPES = {"identity": ["user_accounts:read"], "boards_read": ["user_accounts:read", "boards:read"], "publish": ["user_accounts:read", "boards:read", "pins:read", "pins:write"],
              "schedule": ["user_accounts:read", "boards:read", "pins:read", "pins:write"],
              "analytics": ["user_accounts:read", "boards:read", "pins:read"]}
    EXPLAIN = {"identity": "Connect your Pinterest account. Rafii reads only your profile.",
               "boards_read": "Rafii reads your Pinterest profile and boards. This connection cannot publish or schedule Pins.",
               "publish": "Rafii will create Pins on the board you choose only when you approve each exact Pin.",
               "analytics": "Read available impressions, saves, Pin clicks and outbound clicks for your own Pins. No ads access or comment/reply permission."}
    account_requirement = "An eligible Pinterest account with a board. Personal account data may require Pinterest approval; business accounts are recommended."
    publish_scope = "pins:write"
    publish_required = frozenset({"user_accounts:read", "pins:read", "pins:write", "boards:read"})
    refresh_margin = 300
    native_schedule = False
    server_schedule = True  # Existing Rafii durable worker dispatches the approved Pin when due.
    has_destinations = True
    destination_scope, destination_label = "post", "Board"

    def __init__(self, client_id, client_secret, sandbox=False, transport=None, production_reviewed=False, analytics_enabled=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        self.analytics_enabled = analytics_enabled is True
        # Trial access writes to Pinterest's sandbox; boards there are separate from the live account's boards.
        self.sandbox = bool(sandbox)

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        sandbox = str(values.get("POSTRIFF_PINTEREST_SANDBOX", "")).lower() == "true"
        readonly = values.get("POSTRIFF_PINTEREST_TRIAL_READONLY") == "1"
        callback = values.get('POSTRIFF_OAUTH_PINTEREST_CALLBACK_ORIGIN')
        if callback is not None and not fixed_https_origin(callback):
            return None, {**diagnostic, 'configurationState': 'invalid_configuration'}
        # An official production-API Trial read needs an explicit server-side selection.
        trial_environment = values.get('POSTRIFF_PINTEREST_TRIAL_API_ENVIRONMENT', 'sandbox')
        if readonly and (trial_environment not in ('sandbox', 'production') or sandbox != (trial_environment == 'sandbox')):
            return None, {**diagnostic, "configurationState": "invalid_configuration"}
        policy = None
        if readonly and valid:
            from .pinterest_pilot import PinterestTrialPolicy
            try:
                policy = PinterestTrialPolicy.from_environment(values)
            except AlphaError:
                return None, {**diagnostic, 'configurationState': 'invalid_configuration'}
            from .pinterest_trial_evidence import PinterestReadOnlyEvidenceTransport
            def record(receipt):
                print(json.dumps({"pinterestTrialRequest": receipt}, sort_keys=True), flush=True)
            transport = PinterestReadOnlyEvidenceTransport(record, environment=trial_environment, mock_transport=transport)
        adapter = cls(client_id, secret, sandbox=sandbox, transport=transport,
                      analytics_enabled=values.get("POSTRIFF_PINTEREST_ANALYTICS_ENABLED") == "1" and not readonly) if valid else None
        if adapter:
            adapter.trial_readonly = readonly
            adapter.trial_api_environment = trial_environment if readonly else None
            adapter.trial_policy = policy
        return adapter, diagnostic

    def capability_scopes(self, capability):
        if capability == 'analytics' and not self.analytics_enabled:
            return []
        return super().capability_scopes(capability)

    def pin_analytics(self, access_token, pin_id, *, start_at, end_at):
        from .pinterest_analytics import fetch
        return fetch(self, access_token, pin_id, start_at=start_at, end_at=end_at)

    def assert_trial_context(self, workspace_id, actor_id=None, *, scopes=None, now=None):
        if not getattr(self, 'trial_readonly', False):
            return
        policy = getattr(self, 'trial_policy', None)
        if policy is None:
            raise AlphaError('Pinterest Trial configuration is unavailable.', 503)
        policy.require(workspace_id, actor_id, now=now)
        if scopes is not None:
            policy.require_scopes(scopes)

    def _admit_request(self, method, path, account_id=None):
        if getattr(self, 'trial_readonly', False):
            self.trial_policy.require(self.trial_policy.workspace_id)
            if method != 'GET' and path != '/v5/oauth/token':
                raise AlphaError('This Pinterest Trial cannot change provider content.', 403, code='pinterest_trial_readonly')
        if getattr(self, 'quota_required', False):
            gate = getattr(self, 'rate_gate', None)
            if gate is None:
                raise AlphaError('Pinterest rate budgets are unavailable. Requests are paused.', 503)
            gate(method, path, account_id)

    @property
    def content_api(self):
        return self.SANDBOX if self.sandbox else self.API

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "response_type": "code", "scope": ",".join(scopes), "state": state})

    @property
    def environment(self):
        return "sandbox" if self.sandbox else "production"

    def _bound(self, token, field):
        value = _load(token)
        if (value.get('v') != 1 or value.get("environment") != self.environment or value.get("clientId") != self.client_id
                or not isinstance(value.get(field), str) or not value[field].strip()
                or any(ord(c) < 32 for c in value[field])):
            # Legacy grants have no environment provenance. Re-consent; never guess or migrate them.
            raise AlphaError("Reconnect Pinterest in this environment before using this grant.", 409)
        return value

    def _grant(self, body, refresh_token=None):
        token, renewed = body.get("access_token"), body.get("refresh_token")
        scopes = _scopes(body.get("scope")) or []
        expires = body.get("expires_in")
        refresh_expires = body.get('refresh_token_expires_in')
        if (not isinstance(token, str) or not token.strip() or any(ord(c) < 32 for c in token)
                or not scopes or (renewed is not None and (not isinstance(renewed, str) or not renewed.strip()
                                                         or any(ord(c) < 32 for c in renewed)))
                or (expires is not None and (isinstance(expires, bool) or not isinstance(expires, (int, float))
                                             or not math.isfinite(expires) or expires <= 0))):
            raise AlphaError("Pinterest returned an invalid authorization grant. Reconnect.", 502)
        token_type = body.get('token_type', 'bearer')
        if not isinstance(token_type, str) or token_type.lower() != 'bearer':
            raise AlphaError('Pinterest returned an unsupported token type. Reconnect.', 502)
        if refresh_expires is not None and (type(refresh_expires) not in (int, float) or not math.isfinite(refresh_expires) or refresh_expires <= 0):
            raise AlphaError('Pinterest returned an invalid refresh expiry. Reconnect.', 502)
        if getattr(self, 'trial_readonly', False):
            from .pinterest_pilot import PinterestTrialPolicy
            PinterestTrialPolicy.require_scopes(scopes)
        binding = {"v": 1, "environment": self.environment, "clientId": self.client_id}
        refresh_binding = {**binding, 'rt': renewed, **({'expiresAt': time.time() + refresh_expires} if refresh_expires else {})}
        return {"accessToken": json.dumps({**binding, "at": token, "scope": scopes}),
                "refreshToken": json.dumps(refresh_binding) if renewed else refresh_token,
                "expiresIn": expires, "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        self._admit_request("POST", "/v5/oauth/token")
        body = self._ok(self.transport("POST", f"{self.content_api}/v5/oauth/token", headers={"Authorization": _basic(self.client_id, self.client_secret)},
                                       form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}), "access_token")
        return self._grant(body)

    def refresh(self, refresh_token):
        envelope = self._bound(refresh_token, 'rt')
        expires = envelope.get('expiresAt')
        if expires is not None and (type(expires) not in (int, float) or not math.isfinite(expires) or expires <= time.time()):
            raise AlphaError('Pinterest refresh authorization expired. Reconnect this account.', 409, code='pinterest_reconnect_required')
        raw = envelope['rt']
        self._admit_request('POST', '/v5/oauth/token')
        body = self._ok(self.transport("POST", f"{self.content_api}/v5/oauth/token", headers={"Authorization": _basic(self.client_id, self.client_secret)},
                                       form={"grant_type": "refresh_token", "refresh_token": raw}), "access_token")
        return self._grant(body, refresh_token)

    def bearer(self, access_token):
        return self._bound(access_token, "at")["at"]

    def api(self, access_token, method, path, content=False, **kwargs):
        if not isinstance(path, str) or not path.startswith('/v5/') or '#' in path or '\\' in path:
            raise AlphaError('Invalid Pinterest API path.', 400)
        headers = {**kwargs.pop('headers', {}), "Authorization": "Bearer " + self.bearer(access_token)}
        envelope = self._bound(access_token, 'at')
        if getattr(self, 'trial_readonly', False):
            self.trial_policy.require_scopes(envelope.get('scope'))
        if method == 'GET' and path.startswith('/v5/boards') and 'boards:read' not in envelope.get('scope', []):
            raise AlphaError('Reconnect Pinterest with board read permission to choose a board.', 403, code='pinterest_boards_scope_required')
        self._admit_request(method, path, envelope.get('accountId'))
        # The grant came from this environment; never use a Sandbox token against production.
        return self.transport(method, self.content_api + path, headers=headers, **kwargs)

    def preserve_destination(self, previous, renewed):
        old, new = self._bound(previous, 'at'), self._bound(renewed, 'at')
        if old.get('accountId'):
            new['accountId'] = old['accountId']
        return json.dumps(new)

    def identity(self, access_token):
        body = self._ok(self.api(access_token, "GET", "/v5/user_account"), "username")
        account = body.get('id')
        if not isinstance(account, str) or not re.fullmatch(r'\d{1,30}', account):
            raise AlphaError('Pinterest did not return a stable account ID. Reconnect; this account cannot publish yet.', 409)
        identity = {"providerAccountId": account, "handle": "@" + str(body["username"]), "accountType": str(body.get("account_type") or "profile").lower(),
                    "pictureUrl": body.get("profile_image") if isinstance(body.get("profile_image"), str) else None}
        if getattr(self, 'trial_readonly', False):
            self.trial_policy.require_identity(identity)
            identity['pictureUrl'] = None  # No CDN download/storage in this narrow pilot.
        return identity

    def inspect_scopes(self, access_token, expected_account_id=None):
        """Pinterest offers no token introspection: the scopes its own token response granted."""
        try:
            scopes = self._bound(access_token, "at").get("scope")
        except AlphaError:
            return None
        return sorted(set(scopes)) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else None

    MAX_BOARD_PAGES = 10

    @staticmethod
    def _read_error(response):
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        # Never return arbitrary provider messages, which can contain credential or personal data.
        if response.get('status') == 403 and (body.get('code') == 'PINNER_DATA_ACCESS_DENIED' or body.get('message') == 'PINNER_DATA_ACCESS_DENIED'):
            return AlphaError('Pinterest has not approved data access for this personal account. Try an eligible business account or ask Pinterest to approve access.', 403, code='pinterest_account_ineligible')
        if response.get('status') == 401:
            return AlphaError('Pinterest authorization expired or was revoked. Reconnect this account.', 409, code='pinterest_reconnect_required')
        if response.get('status') == 429:
            return AlphaError('Pinterest rate limit reached. Wait before trying again.', 429, code='pinterest_rate_limited')
        return AlphaError('Pinterest could not return these destinations. Check permissions and try again.', 502)

    def _items(self, access_token, path):
        items, bookmark, seen = [], None, set()
        for _ in range(self.MAX_BOARD_PAGES):
            query = {'page_size': '100', **({'bookmark': bookmark} if bookmark else {})}
            response = self.api(access_token, 'GET', path + '?' + urlencode(query), content=True)
            body = response.get('body') if isinstance(response.get('body'), dict) else {}
            if response.get('status') != 200 or not isinstance(body.get('items'), list):
                raise self._read_error(response)
            if any(not isinstance(item, dict) or not re.fullmatch(r'\d{1,30}', str(item.get('id', ''))) for item in body['items']):
                raise AlphaError('Pinterest returned invalid destination data. No complete list is available.', 502)
            items.extend(body['items'])
            bookmark = body.get('bookmark')
            if bookmark is None or bookmark == '':
                return items
            if not isinstance(bookmark, str) or len(bookmark) > 2048 or bookmark in seen:
                raise AlphaError('Pinterest destination pagination was invalid or repeated. No complete list is available.', 502)
            seen.add(bookmark)
        raise AlphaError('Pinterest destination pagination exceeded the safe limit. No complete list is available.', 502)

    def destinations(self, access_token):
        """This person's own boards (sandbox boards while in Trial), for choosing one per Pin. Follows Pinterest's
        bookmark pagination, so checking a chosen board never misses one past the first page."""
        if getattr(self, 'trial_readonly', False):
            self.identity(access_token)  # Reconfirm the exact approved account before returning any boards.
        return [{'id': str(b['id']), 'name': str(b.get('name') or b['id']), 'kind': 'board', 'selected': False,
                 'privacy': b.get('privacy') or 'UNKNOWN',
                 'eligible': b.get('privacy') == 'PUBLIC' and b.get('is_ads_only') is not True}
                for b in self._items(access_token, '/v5/boards')]

    def sections(self, access_token, board_id):
        if getattr(self, 'trial_readonly', False):
            raise AlphaError('Board sections are outside this read-only Trial approval.', 403, code='pinterest_trial_readonly')
        if not isinstance(board_id, str) or not re.fullmatch(r'\d{1,30}', board_id):
            raise AlphaError('Choose a valid Pinterest board.', 400)
        if not any(b['id'] == board_id and b['eligible'] for b in self.destinations(access_token)):
            raise AlphaError('Choose an accessible public board. Secret and ad-only boards are unavailable in Rafii v1.', 409)
        return [{'id': str(s['id']), 'name': str(s.get('name') or s['id']), 'kind': 'section',
                 'boardId': board_id, 'selected': False} for s in self._items(access_token, f'/v5/boards/{board_id}/sections')]
