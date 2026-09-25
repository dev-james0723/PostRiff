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
import re
from urllib.parse import quote, urlencode, urlsplit
from postriff_alpha.domain import AlphaError
from .provider_base import GRAPH_VERSION, OAuthProvider, default_transport
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
    native_schedule = True
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
class YouTubeProvider(OAuthProvider):
    id, platform, capability_version = "youtube", "YouTube", 1
    AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN = "https://oauth2.googleapis.com/token"
    REVOKE = "https://oauth2.googleapis.com/revoke"
    TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
    API = "https://www.googleapis.com/youtube/v3"
    UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
    UPLOAD_SCOPE, READ_SCOPE = "https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"
    SCOPES = {"identity": [READ_SCOPE], "publish": [UPLOAD_SCOPE, READ_SCOPE], "schedule": [UPLOAD_SCOPE, READ_SCOPE]}
    EXPLAIN = {"identity": "Connect your YouTube channel. Rafii reads only the channel's name.",
               "publish": "Rafii will upload videos to this channel only when you approve each exact upload. Until Google audits Rafii, YouTube keeps every upload private."}
    account_requirement = "A Google account with a YouTube channel."
    read_scope, publish_scope = READ_SCOPE, UPLOAD_SCOPE
    publish_required = frozenset({UPLOAD_SCOPE})
    refresh_margin = 300  # Google access tokens last an hour

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect, "scope": " ".join(scopes),
                                            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                                            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = _scopes(body.get("scope"), r"\s+") or []
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes}), "refreshToken": body.get("refresh_token") or refresh_token,
                "expiresIn": body.get("expires_in"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, form={"code": code, "client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": redirect,
                                                                 "grant_type": "authorization_code", "code_verifier": verifier}), "access_token")
        return self._grant(body)

    def refresh(self, refresh_token):
        body = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret,
                                                                 "refresh_token": refresh_token, "grant_type": "refresh_token"}), "access_token")
        return self._grant(body, refresh_token)  # Google keeps the refresh token unless it sends a new one

    @staticmethod
    def bearer(access_token):
        return _load(access_token)["at"]

    def api(self, access_token, method, url, **kwargs):
        headers = {"Authorization": "Bearer " + self.bearer(access_token), **kwargs.pop("headers", {})}
        return self.transport(method, url, headers=headers, **kwargs)

    def identity(self, access_token):
        body = self._ok(self.api(access_token, "GET", f"{self.API}/channels?" + urlencode({"part": "snippet", "mine": "true"})))
        items = body.get("items") if isinstance(body.get("items"), list) else []
        if not items or not isinstance(items[0], dict) or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", str(items[0].get("id", ""))):
            raise AlphaError("This Google account has no YouTube channel. Create one, then connect again.", 409)
        snippet = items[0].get("snippet") if isinstance(items[0].get("snippet"), dict) else {}
        thumbnail = ((snippet.get("thumbnails") or {}).get("default") or {}).get("url")
        return {"providerAccountId": items[0]["id"], "handle": str(snippet.get("customUrl") or snippet.get("title") or items[0]["id"]),
                "accountType": "channel", "pictureUrl": thumbnail if isinstance(thumbnail, str) else None}

    def inspect_scopes(self, access_token, expected_account_id=None):
        """Google's tokeninfo: the live grant, and proof it belongs to Rafii's client."""
        response = self.transport("GET", self.TOKENINFO + "?" + urlencode({"access_token": self.bearer(access_token)}))
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or body.get("aud") != self.client_id or not isinstance(body.get("scope"), str):
            return None
        return sorted(set(_scopes(body["scope"], r"\s+")))

    def revoke(self, token):
        # Revoking an access token also revokes its refresh token (Google OAuth 2.0 for web server apps).
        return self.transport("POST", self.REVOKE, form={"token": self.bearer(token)}).get("status") == 200


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

    def authorize_url(self, redirect, state, challenge, scopes):
        # The env names say CLIENT_ID; TikTok calls the same value client_key.
        return self.AUTH + "?" + urlencode({"client_key": self.client_id, "scope": ",".join(scopes), "response_type": "code", "redirect_uri": redirect,
                                            "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = _scopes(body.get("scope")) or []
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes, "openId": body.get("open_id")}),
                "refreshToken": body.get("refresh_token") or refresh_token, "expiresIn": body.get("expires_in"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", f"{self.API}/v2/oauth/token/", form={"client_key": self.client_id, "client_secret": self.client_secret, "code": code,
                                                                                   "grant_type": "authorization_code", "redirect_uri": redirect, "code_verifier": verifier}), "access_token")
        return self._grant(body)

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
    SCOPES = {"identity": ["user_accounts:read"], "publish": ["user_accounts:read", "boards:read", "pins:read", "pins:write"],
              "schedule": ["user_accounts:read", "boards:read", "pins:read", "pins:write"]}
    EXPLAIN = {"identity": "Connect your Pinterest account. Rafii reads only your profile.",
               "publish": "Rafii will create Pins on the board you choose only when you approve each exact Pin."}
    account_requirement = "A Pinterest account with at least one board."
    publish_scope = "pins:write"
    publish_required = frozenset({"pins:write", "boards:read"})
    refresh_margin = 300
    has_destinations = True
    destination_scope, destination_label = "post", "Board"

    def __init__(self, client_id, client_secret, sandbox=False, transport=None, production_reviewed=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        # Trial access writes to Pinterest's sandbox; boards there are separate from the live account's boards.
        self.sandbox = bool(sandbox)

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        sandbox = str(values.get("POSTRIFF_PINTEREST_SANDBOX", "")).lower() == "true"
        return (cls(client_id, secret, sandbox=sandbox, transport=transport) if valid else None), diagnostic

    @property
    def content_api(self):
        return self.SANDBOX if self.sandbox else self.API

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "response_type": "code", "scope": ",".join(scopes), "state": state})

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = _scopes(body.get("scope")) or []
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes}), "refreshToken": body.get("refresh_token") or refresh_token,
                "expiresIn": body.get("expires_in"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", f"{self.API}/v5/oauth/token", headers={"Authorization": _basic(self.client_id, self.client_secret)},
                                       form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}), "access_token")
        return self._grant(body)

    def refresh(self, refresh_token):
        body = self._ok(self.transport("POST", f"{self.API}/v5/oauth/token", headers={"Authorization": _basic(self.client_id, self.client_secret)},
                                       form={"grant_type": "refresh_token", "refresh_token": refresh_token}), "access_token")
        return self._grant(body, refresh_token)

    @staticmethod
    def bearer(access_token):
        return _load(access_token)["at"]

    def api(self, access_token, method, path, content=False, **kwargs):
        headers = {"Authorization": "Bearer " + self.bearer(access_token), **kwargs.pop("headers", {})}
        return self.transport(method, (self.content_api if content else self.API) + path, headers=headers, **kwargs)

    def identity(self, access_token):
        body = self._ok(self.api(access_token, "GET", "/v5/user_account"), "username")
        account = str(body.get("id") or body["username"])
        return {"providerAccountId": account, "handle": "@" + str(body["username"]), "accountType": str(body.get("account_type") or "profile").lower(),
                "pictureUrl": body.get("profile_image") if isinstance(body.get("profile_image"), str) else None}

    def inspect_scopes(self, access_token, expected_account_id=None):
        """Pinterest offers no token introspection: the scopes its own token response granted."""
        try:
            scopes = _load(access_token).get("scope")
        except AlphaError:
            return None
        return sorted(set(scopes)) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else None

    def destinations(self, access_token):
        """This person's own boards (sandbox boards while in Trial), for choosing one per Pin."""
        response = self.api(access_token, "GET", "/v5/boards?" + urlencode({"page_size": "100"}), content=True)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or not isinstance(body.get("items"), list):
            raise AlphaError("Pinterest didn't list your boards. Try again.", 502)
        return [{"id": str(b["id"]), "name": str(b.get("name") or b["id"]), "kind": "board", "selected": False}
                for b in body["items"] if isinstance(b, dict) and re.fullmatch(r"\d{1,30}", str(b.get("id", "")))]
