"""Hosted adapters for Facebook Pages, YouTube, TikTok and Pinterest (Rafii Hosted Channels Plan, Wave 3).

Stored grants are small versioned JSON documents, encrypted like any token by oauth.CredentialVault:
- Facebook: the person's long-lived user token and one explicitly selected Page. A Page token is optional for
  basic connection; operations that act as the Page require their own grant, task and current Page token.
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
    SCOPES = {"identity": ["pages_show_list"],
              "publish": ["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
              "schedule": ["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
              "analytics": ["pages_show_list", "pages_read_engagement", "read_insights"],
              "comments_read": ["pages_show_list", "pages_read_engagement", "pages_read_user_content"],
              "reply": ["pages_show_list", "pages_read_engagement", "pages_manage_engagement"],
              "moderate": ["pages_show_list", "pages_read_engagement", "pages_manage_engagement"],
              "messaging": ["pages_show_list", "pages_messaging"]}
    EXPLAIN = {"identity": "Connect your Facebook account and choose a Page. Rafii posts nothing until you approve a post.",
               "publish": "Rafii will post to the Facebook Page you choose only when you approve each exact post."}
    account_requirement = "A Facebook account with access to an eligible Page. Choose the Page after consent."
    publish_scope = "pages_manage_posts"
    publish_required = frozenset({"pages_manage_posts", "pages_read_engagement"})
    # Rafii's worker publishes at the approved time; nothing is scheduled on Facebook itself.
    native_schedule = False
    # The person token has a real lifetime even if a separately issued Page token does not.
    non_expiring = False
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
            # Business Login configurations have fixed permissions. Reusing a broad
            # publishing/Messenger config for identity would violate progressive consent.
            configured = getattr(self, "login_configs", {}).get(tuple(sorted(scopes)))
            if not configured:
                raise AlphaError("Configure a Facebook Login for Business configuration for these exact permissions.", 409)
            params["config_id"] = configured
        else:
            params["scope"] = ",".join(scopes)
        return self.AUTH + "?" + urlencode(params)

    def _pages(self, user_token, include_tokens=False):
        pages, cursor, seen = {}, None, set()
        for _ in range(10):
            params = {"fields": "id,name,tasks" + (",access_token" if include_tokens else ""), "limit": "100"}
            if cursor: params['after'] = cursor
            response = self.graph("GET", "/me/accounts", user_token, params)
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            if response.get("status") != 200 or not isinstance(body.get("data"), list):
                raise AlphaError("Facebook didn't list your Pages. Try again.", 502)
            for p in body['data']:
                if isinstance(p, dict) and re.fullmatch(r'\d{5,25}', str(p.get('id', ''))):
                    page = {'id': str(p['id']), 'name': str(p.get('name') or p['id']),
                            'tasks': [task for task in p.get('tasks', []) if isinstance(task, str)] if isinstance(p.get('tasks'), list) else []}
                    if include_tokens and isinstance(p.get('access_token'), str) and p['access_token']:
                        page['token'] = p['access_token']
                    pages[page['id']] = page
            paging = body.get('paging') or {}
            if not paging.get('next'): return list(pages.values())
            cursor = (paging.get('cursors') or {}).get('after')
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096 or cursor in seen: break
            seen.add(cursor)
        raise AlphaError('Page discovery exceeded its safe pagination bound; select a narrower Business account.', 409)

    def _granted(self, user_token):
        response = self.graph("GET", "/me/permissions", user_token)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or not isinstance(body.get("data"), list):
            return None
        return sorted({p["permission"] for p in body["data"] if isinstance(p, dict) and p.get("status") == "granted" and isinstance(p.get("permission"), str)})

    def _validated_token(self, user_token, expected_user):
        # Meta's documented debug_token metadata binds the token to this app and person.
        # Authorization stays in the header; neither token nor metadata is customer-visible.
        response = self.transport("GET", f"{self.GRAPH}/debug_token?" + urlencode({'input_token': user_token}),
                                  headers={'Authorization': f'Bearer {self.client_id}|{self.client_secret}'})
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        data = body.get('data') if isinstance(body.get('data'), dict) else {}
        if (response.get('status') != 200 or data.get('is_valid') is not True
                or str(data.get('app_id')) != self.client_id or str(data.get('user_id')) != expected_user):
            return None
        for field in ('expires_at', 'data_access_expires_at'):
            expiry = data.get(field)
            if expiry is not None and (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                                       or not math.isfinite(expiry) or expiry < 0 or (expiry and expiry <= time.time())):
                return None
        return data

    @staticmethod
    def _needs_page_token(session):
        return bool(set(session.get('scope') or []) & {'pages_read_engagement', 'pages_manage_posts',
                    'pages_manage_engagement', 'pages_messaging', 'pages_read_user_content', 'read_insights'})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", f"{self.GRAPH}/oauth/access_token", form={"client_id": self.client_id, "client_secret": self.client_secret,
                                                                                        "redirect_uri": redirect, "code": code}), "access_token")
        long = self._ok(self.transport("POST", f"{self.GRAPH}/oauth/access_token", form={"grant_type": "fb_exchange_token", "client_id": self.client_id,
                                                                                       "client_secret": self.client_secret, "fb_exchange_token": short["access_token"]}), "access_token")
        user_token = long["access_token"]
        me = self._ok(self.graph("GET", "/me", user_token, {"fields": "id,name"}), "id")
        metadata = self._validated_token(user_token, str(me['id']))
        if metadata is None:
            raise AlphaError('Facebook could not verify this authorization for Rafii. Reconnect your account.', 409)
        session = {"v": 1, "user": str(me["id"]), "name": me.get("name"), "ut": user_token, "scope": self._granted(user_token) or [], "page": None}
        self._pages(user_token)  # Verify discovery without silently choosing a destination, even for one Page.
        expiries = [value - time.time() for field in ('expires_at', 'data_access_expires_at')
                    if (value := metadata.get(field))]
        lifetime = long.get('expires_in')
        if isinstance(lifetime, (int, float)) and not isinstance(lifetime, bool) and math.isfinite(lifetime) and lifetime > 0:
            expiries.append(lifetime)
        return {"accessToken": json.dumps(session), "refreshToken": None,
                "expiresIn": min(expiries) if expiries else None, "scopes": session["scope"] or None}

    @staticmethod
    def session(access_token):
        session = _load(access_token)
        if not re.fullmatch(r"\d{1,25}", str(session.get("user", ""))) or not isinstance(session.get("ut"), str):
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def identity(self, access_token):
        """A fresh /me/accounts entry proves the selected Page without requesting write permissions."""
        session = self.session(access_token)
        page = session.get("page")
        if isinstance(page, dict):
            current = next((p for p in self._pages(session['ut']) if p['id'] == page.get('id')), None)
            if current is None:
                raise AlphaError('The selected Facebook Page is no longer available. Reconnect and choose a Page.', 409)
            return {"providerAccountId": session["user"], "handle": current['name'], "accountType": "page"}
        body = self._ok(self.graph("GET", "/me", session["ut"], {"fields": "id,name"}), "id")
        if str(body["id"]) != session["user"]:
            raise AlphaError("The connected Facebook account changed. Reconnect it.", 409)
        return {"providerAccountId": session["user"], "handle": str(body.get("name") or session["user"]), "accountType": "person"}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self.session(access_token)
        if expected_account_id and session["user"] != expected_account_id:
            return None
        if self._validated_token(session['ut'], session['user']) is None:
            return None
        live = self._granted(session["ut"])
        if live is not None:
            return live
        # A surviving Page token proves identity, not that historic permissions
        # remain granted. Reconnect when the live grant cannot be inspected.
        return None

    def destinations(self, access_token):
        session = self.session(access_token)
        chosen = (session.get("page") or {}).get("id")
        return [{"id": p["id"], "name": p["name"], "kind": "page", "tasks": p.get("tasks", []), "selected": p["id"] == chosen} for p in self._pages(session["ut"])]

    def with_destination(self, access_token, destination_id):
        session = self.session(access_token)
        page = next((p for p in self._pages(session["ut"], self._needs_page_token(session)) if p["id"] == str(destination_id)), None)
        if page is None:
            raise AlphaError("This Facebook account did not grant that Page. Reconnect, allow the intended Page, then choose again.", 409)
        return json.dumps({**session, "page": page})

    def revalidate_page(self, access_token, task):
        session = self.session(access_token)
        selected = (session.get("page") or {}).get("id")
        page = next((p for p in self._pages(session["ut"], include_tokens=True) if p["id"] == selected), None)
        if page is None or (task and not ({task, "PROFILE_PLUS_"+task, "MANAGE", "PROFILE_PLUS_FULL_CONTROL"} & set(page.get("tasks", [])))):
            raise AlphaError("The selected Page no longer grants the required task. Reconnect and review.", 409)
        if not page.get('token'):
            raise AlphaError('Additional Facebook Page permission is required for this operation. Your basic connection is retained.', 409)
        return page

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
    SCOPES = {**SCOPES,
              "posts_read": [READ_SCOPE],
              "analytics": [READ_SCOPE, "https://www.googleapis.com/auth/yt-analytics.readonly"],
              "monetary_analytics": [READ_SCOPE, "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"],
              "comments_read": [READ_SCOPE],
              "reply": [READ_SCOPE, "https://www.googleapis.com/auth/youtube.force-ssl"],
              "moderate": [READ_SCOPE, "https://www.googleapis.com/auth/youtube.force-ssl"],
              "manage": [READ_SCOPE, "https://www.googleapis.com/auth/youtube.force-ssl"],
              "memberships": [READ_SCOPE, "https://www.googleapis.com/auth/youtube.channel-memberships.creator"]}
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
    SCOPES = {**SCOPES, "posts_read": ["user.info.basic", "video.list"], "upload_inbox": ["user.info.basic", "video.upload"]}
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
    SCOPES = {"identity": ["user_accounts:read"], "publish": ["user_accounts:read", "boards:read", "pins:read", "pins:write"],
              "schedule": ["user_accounts:read", "boards:read", "pins:read", "pins:write"]}
    SCOPES = {**SCOPES,
              "posts_read": ["user_accounts:read", "pins:read"],
              "analytics": ["user_accounts:read", "pins:read"],
              "boards": ["user_accounts:read", "boards:read", "boards:write"],
              "trends": ["user_accounts:read"],
              'commerce':['user_accounts:read','catalogs:read'],
              'commerce_write':['user_accounts:read','catalogs:read','catalogs:write'],
              'product_tag':['user_accounts:read','boards:read','boards:write','pins:read','pins:write'],
              'audience_insights':['user_accounts:read','ads:read']}
    EXPLAIN = {"identity": "Connect your Pinterest account. Rafii reads only your profile.",
               "publish": "Rafii will create Pins on the board you choose only when you approve each exact Pin."}
    account_requirement = "An eligible Pinterest business account. A board is needed only when publishing Pins."
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

    MAX_BOARD_PAGES = 10

    def destinations(self, access_token):
        """This person's own boards (sandbox boards while in Trial), for choosing one per Pin. Follows Pinterest's
        bookmark pagination, so checking a chosen board never misses one past the first page."""
        boards, bookmark = [], None
        for _ in range(self.MAX_BOARD_PAGES):
            query = {"page_size": "100", **({"bookmark": bookmark} if bookmark else {})}
            response = self.api(access_token, "GET", "/v5/boards?" + urlencode(query), content=True)
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            if response.get("status") != 200 or not isinstance(body.get("items"), list):
                raise AlphaError("Pinterest didn't list your boards. Try again.", 502)
            boards += [{"id": str(b["id"]), "name": str(b.get("name") or b["id"]), "kind": "board", "selected": False}
                       for b in body["items"] if isinstance(b, dict) and re.fullmatch(r"\d{1,30}", str(b.get("id", "")))]
            bookmark = body.get("bookmark") if isinstance(body.get("bookmark"), str) and body.get("bookmark") else None
            if not bookmark:
                break
        return boards
