"""Hosted adapters for X, Mastodon, Discord and Telegram (Rafii Hosted Channels Plan, Wave 1).

Grants these adapters store are small versioned JSON documents, encrypted like any token by oauth.CredentialVault:
- X: the bearer token plus the scopes X's own token response granted (X offers no user-token introspection).
- Mastodon: the token plus the server and the client this workspace registered there (needed to revoke).
- Discord: the server (and later the channel) Rafii's bot was added to; the bot token lives in server secrets.
- Telegram: the channel Rafii's bot administers; the bot token lives in server secrets.
Provider error text and tokens never reach an AlphaError message.
"""
import base64
import json
import re
import secrets
import socket
import string
from urllib.parse import quote, urlencode, urlsplit
from postriff_alpha.domain import AlphaError
from .net_guard import assert_public, public_host, pinned_public_json_transport
from .mastodon_protocol import discover, instance_host, refuse_rate_limited_registration
from .mastodon_release import write_qualified as mastodon_write_qualified
from .provider_base import OAuthProvider, _credential_shape, default_transport


def multipart(fields, files):
    """(body, content type) for multipart/form-data; files are (field, filename, content type, bytes)."""
    boundary = "rafii" + secrets.token_hex(12)
    chunks = []
    for name, value in fields:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, filename, content_type, raw in files:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode() + raw + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _load(token):
    try:
        value = json.loads(token)
    except (TypeError, ValueError) as error:
        raise AlphaError("This account needs to be reconnected.", 409) from error
    if not isinstance(value, dict) or value.get("v") != 1:
        raise AlphaError("This account needs to be reconnected.", 409)
    return value


def _https_origin(value):
    parts = urlsplit(value or "")
    return parts.scheme == "https" and bool(parts.hostname) and not parts.path.strip("/") and not parts.query


# --- X --------------------------------------------------------------------------------------------------------
class XProvider(OAuthProvider):
    id, platform, capability_version = "x", "X", 1
    AUTH = "https://x.com/i/oauth2/authorize"
    TOKEN = "https://api.x.com/2/oauth2/token"
    REVOKE = "https://api.x.com/2/oauth2/revoke"
    ME = "https://api.x.com/2/users/me"
    SCOPES = {"identity": ["tweet.read", "users.read", "offline.access"],
              "publish": ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access"],
              "schedule": ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access"]}
    EXPLAIN = {"identity": "Connect your X account. Rafii reads nothing else from it.",
               "publish": "Rafii will post to this X account only when you approve each exact post. X charges Rafii for every post and read."}
    account_requirement = "An X account."
    publish_scope = "tweet.write"
    publish_required = frozenset({"tweet.write"})
    refresh_margin = 300  # X access tokens last two hours

    def _basic(self):
        return "Basic " + base64.b64encode(f"{quote(self.client_id, safe='')}:{quote(self.client_secret, safe='')}".encode()).decode()

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect, "scope": " ".join(scopes),
                                            "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})

    @staticmethod
    def _grant(body):
        scopes = body["scope"].split() if isinstance(body.get("scope"), str) else []
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes}), "refreshToken": body.get("refresh_token"),
                "expiresIn": body.get("expires_in"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, headers={"Authorization": self._basic()},
                                       form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "code_verifier": verifier, "client_id": self.client_id}), "access_token")
        return self._grant(body)

    @staticmethod
    def bearer(access_token):
        return _load(access_token)["at"]

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"user.fields": "profile_image_url"}), headers={"Authorization": "Bearer " + self.bearer(access_token)}), "data")
        data = body["data"] if isinstance(body["data"], dict) else {}
        if not re.fullmatch(r"\d{1,25}", str(data.get("id", ""))):
            raise AlphaError("The provider did not complete this authorization step.", 502)
        username = data.get("username") if isinstance(data.get("username"), str) else None
        return {"providerAccountId": str(data["id"]), "handle": "@" + username if username else str(data["id"]), "accountType": "profile", "pictureUrl": data.get("profile_image_url")}

    def inspect_scopes(self, access_token, expected_account_id=None):
        """X has no user-token introspection: these are the scopes X's own token response granted, not requests."""
        try:
            scopes = _load(access_token).get("scope")
        except AlphaError:
            return None
        return sorted(set(scopes)) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else None

    def refresh(self, refresh_token):
        body = self._ok(self.transport("POST", self.TOKEN, headers={"Authorization": self._basic()},
                                       form={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id}), "access_token")
        grant = self._grant(body)
        grant["refreshToken"] = grant["refreshToken"] or refresh_token
        return grant

    def revoke(self, token):
        return self.transport("POST", self.REVOKE, headers={"Authorization": self._basic()},
                              form={"token": self.bearer(token), "token_type_hint": "access_token", "client_id": self.client_id}).get("status") == 200

    def api(self, access_token, method, path, **kwargs):
        headers = {"Authorization": "Bearer " + self.bearer(access_token), **kwargs.pop("headers", {})}
        return self.transport(method, "https://api.x.com" + path, headers=headers, **kwargs)


# --- Mastodon ---------------------------------------------------------------------------------------------------
class MastodonProvider(OAuthProvider):
    id, platform, capability_version = "mastodon", "Mastodon", 3
    SCOPES = {"identity": ["read:accounts"],
              "publish": ["read:accounts", "read:statuses", "write:statuses", "write:media"],
              "schedule": ["read:accounts", "read:statuses", "write:statuses", "write:media"],
              "posts_read": ["read:accounts", "read:statuses"],
              "analytics": ["read:accounts", "read:statuses"],
              "comments_read": ["read:accounts", "read:statuses", "read:notifications"],
              "reply": ["read:accounts", "read:statuses", "write:statuses"],
              "moderate": ["read:accounts", "read:statuses", "read:filters", "write:mutes", "write:blocks", "write:reports", "write:filters"],
              "profile": ["read:accounts", "write:accounts"],
              "interactions": ["read:accounts", "read:statuses", "read:follows", "read:lists", "read:bookmarks",
                               "write:follows", "write:lists", "write:bookmarks", "write:favourites", "write:statuses"],
              "management": ["read:accounts", "read:statuses", "read:notifications", "read:follows",
                             "read:lists", "read:bookmarks", "read:favourites", "read:mutes", "read:blocks",
                             "write:statuses", "write:media", "write:accounts", "write:follows", "write:lists",
                             "write:bookmarks", "write:favourites", "write:mutes", "write:blocks", "read:filters", "write:filters", "write:reports"]}
    EXPLAIN = {"identity": "Connect your Mastodon account. Rafii registers itself on your server and reads only your profile.",
               "publish": "Rafii will post to this Mastodon account only when you approve each exact post."}
    account_requirement = "An account on any Mastodon server."
    publish_scope = "write:statuses"
    publish_required = frozenset({"write:statuses"})
    start_input = {"name": "instance", "label": "Mastodon server", "placeholder": "mastodon.social"}
    non_expiring = True
    server_schedule = True
    read_scope = "read:statuses"

    def __init__(self, website, transport=None, production_reviewed=False, resolver=socket.getaddrinfo):
        self.client_id = self.client_secret = None
        self.website = website.rstrip("/")
        self.transport = transport or (lambda method, url, **kw: pinned_public_json_transport(
            method, url, resolver=self.resolver, **kw))
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True
        self.resolver = resolver
        self.application_cache = None

    @classmethod
    def mount(cls, values, transport=None):
        flag, base = values.get("POSTRIFF_OAUTH_MASTODON_ENABLED"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        presence = {"clientId": flag is not None, "clientSecret": bool(base)}
        missing = [name for name, present in (("POSTRIFF_OAUTH_MASTODON_ENABLED", flag is not None), ("POSTRIFF_PUBLIC_BASE_URL", bool(base))) if not present]
        state = ("not_configured" if flag is None else "partial_configuration" if missing
                 else "configured" if str(flag).lower() == "true" and _https_origin(base) else "invalid_configuration")
        diagnostic = {"configurationState": state, "credentialPresence": presence, "missingVariables": missing}
        return (cls(base, transport=transport) if state == "configured" else None), diagnostic

    def _server(self, value):
        return assert_public(instance_host(value), self.resolver)

    def begin(self, redirect, state, verifier, challenge, scopes, instance):
        host = self._server(instance)
        # Pixelfed has its own compatibility probe and authorization contract.
        capabilities = discover(self.transport, host) if self.id == "mastodon" else None
        supported = (capabilities or {}).get("scopesSupported")
        if supported is not None and set(scopes) == set(self.SCOPES.get('management', [])):
            scopes = [s for s in scopes if s in supported]
        if supported is not None and not set(scopes) <= set(supported):
            raise AlphaError("This server does not support the requested permissions. Choose a narrower connection.", 409)
        body = self.application_cache(host, redirect, scopes) if self.application_cache else None
        if body is None:
            response = self.transport("POST", f"https://{host}/api/v1/apps", form={"client_name": "Rafii", "redirect_uris": redirect, "scopes": " ".join(scopes), "website": self.website})
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            refuse_rate_limited_registration(response)
            if response.get("status") != 200:
                raise AlphaError("That server didn't accept Rafii. Check the server name or choose fewer permissions.", 502)
        if not _credential_shape(body.get("client_id")) or not _credential_shape(body.get("client_secret")):
            raise AlphaError("That Mastodon server didn't accept Rafii. Check the server name.", 502)
        pkce = capabilities.get("pkce", False) if capabilities else True
        parameters = {"response_type": "code", "client_id": body["client_id"], "redirect_uri": redirect,
                      "scope": " ".join(scopes), "state": state, "force_login": "true"}
        if pkce:
            parameters.update({"code_challenge": challenge, "code_challenge_method": "S256"})
        authorize = f"https://{host}/oauth/authorize?" + urlencode(parameters)
        return {"authorizeUrl": authorize, "scopes": scopes, "context": {"instance": host, "clientId": body["client_id"],
                "clientSecret": body["client_secret"], "pkce": pkce, "redirect": redirect, "capabilities": capabilities}}

    def exchange(self, code, verifier, redirect):
        try:
            context = json.loads(verifier)
        except (TypeError, ValueError) as error:
            raise AlphaError("Connection request unavailable.", 404) from error
        if not isinstance(context, dict) or not all(isinstance(context.get(k), str) for k in ("verifier", "instance", "clientId", "clientSecret")):
            raise AlphaError("Connection request unavailable.", 404)
        host = self._server(context["instance"])
        if context.get("redirect", redirect) != redirect:
            raise AlphaError("This authorization callback does not match the connection request.", 409)
        form = {"grant_type": "authorization_code", "code": code, "client_id": context["clientId"],
                "client_secret": context["clientSecret"], "redirect_uri": redirect}
        if context.get("pkce", True):
            form["code_verifier"] = context["verifier"]
        body = self._ok(self.transport("POST", f"https://{host}/oauth/token", form=form), "access_token")
        if not _credential_shape(body.get('access_token')):
            raise AlphaError('This Mastodon server returned an invalid access token.', 502)
        expires = body.get('expires_in')
        if expires is not None and (type(expires) is not int or not 1 <= expires <= 315360000):
            raise AlphaError('This Mastodon server returned an invalid token lifetime.', 502)
        scopes = body["scope"].split() if isinstance(body.get("scope"), str) else []
        session = {"v": 1, "at": body["access_token"], "instance": host, "clientId": context["clientId"], "clientSecret": context["clientSecret"], "scope": scopes,
                   "capabilities": context.get("capabilities")}
        return {"accessToken": json.dumps(session), "refreshToken": None, "expiresIn": expires, "scopes": scopes}

    def session(self, access_token):
        session = _load(access_token)
        session["instance"] = self._server(session.get("instance"))
        return session

    def api(self, session, method, path, **kwargs):
        if not isinstance(path, str) or not path.startswith("/api/") or "\\" in path or "#" in path or any(ord(c) < 32 for c in path):
            raise AlphaError("Unsupported Mastodon API path.", 400)
        # Check again at the actual bearer dispatch, after any earlier grant/read work.
        # App registration, token exchange and revoke use separate OAuth transports.
        if self.id == 'mastodon' and method not in ('GET', 'HEAD', 'OPTIONS') and not mastodon_write_qualified(self):
            raise AlphaError('Mastodon account writes await independent publishing acceptance. Nothing was sent.',
                             409, code='mastodon_write_release_required')
        host = self._server(session.get("instance"))
        extra = kwargs.pop("headers", {})
        if any(k.lower() in ("authorization", "host") for k in extra):
            raise AlphaError("Provider request headers cannot override account identity.", 400)
        headers = {**extra, "Authorization": "Bearer " + session["at"]}
        return self.transport(method, f"https://{host}{path}", headers=headers, **kwargs)

    @staticmethod
    def _verification_cooldown(response):
        if response.get('status') in (429, 500, 502, 503, 504):
            error = AlphaError('Mastodon verification is temporarily unavailable. Retry after its cooldown.', 503,
                               code='mastodon_verification_unavailable')
            error.mastodon_retry_headers = {str(k).lower(): str(v)[:80] for k, v in (response.get('headers') or {}).items()
                                           if str(k).lower() in ('retry-after', 'x-ratelimit-reset')}
            raise error

    def identity(self, access_token):
        session = self.session(access_token)
        response = self.api(session, "GET", "/api/v1/accounts/verify_credentials")
        if response.get('status') == 401:
            raise AlphaError('Mastodon revoked or rejected this access token. Reconnect this exact account.', 409, code='mastodon_authorization_revoked')
        self._verification_cooldown(response)
        body = self._ok(response, "id")
        if not re.fullmatch(r"\d{1,40}", str(body.get("id", ""))):
            raise AlphaError("This server returned an invalid account identity.", 502)
        username = body.get("username") if isinstance(body.get("username"), str) else str(body["id"])
        restricted = ('account_suspended' if body.get('suspended') is True else
                      'account_moved' if body.get('moved') is not None else
                      'account_memorialized' if body.get('memorial') is True else None)
        return {"providerAccountId": f"{body['id']}@{session['instance']}", "handle": f"@{username}@{session['instance']}", "accountType": "profile",
                **({'restriction': restricted} if restricted else {})}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self.session(access_token)
        if expected_account_id is not None:
            identity = self.identity(access_token)
            if identity.get('restriction'):
                return []  # Inactive origin accounts cannot retain write authority.
            if identity['providerAccountId'] != expected_account_id:
                return None
        response = self.api(session, "GET", "/api/v1/apps/verify_credentials")
        self._verification_cooldown(response)
        body = response.get("body")
        if response.get("status") != 200 or not isinstance(body, dict):
            return None
        live = body.get("scopes")
        if isinstance(live, list) and all(isinstance(s, str) for s in live):
            # The endpoint describes the registered APP, not the access token's grant.
            # Intersection can narrow a token; an app scope must never widen it.
            from .mastodon_protocol import has_scopes
            return sorted(s for s in set(session.get("scope") or []) if has_scopes(live, (s,)))
        # Servers before Mastodon 4.3 do not echo scopes; the token just worked for the app that was granted them.
        return sorted(set(session.get("scope") or []))

    def revoke(self, token):
        session = self.session(token)
        return self.transport("POST", f"https://{session['instance']}/oauth/revoke",
                              form={"client_id": session["clientId"], "client_secret": session["clientSecret"], "token": session["at"]}).get("status") == 200


# --- Discord ----------------------------------------------------------------------------------------------------
class DiscordProvider(OAuthProvider):
    id, platform, capability_version = "discord", "Discord", 1
    AUTH = "https://discord.com/oauth2/authorize"
    API = "https://discord.com/api/v10"
    # View Channel, Send Messages, Embed Links, Attach Files.
    PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 14) | (1 << 15)
    SCOPES = {"identity": ["identify", "bot"], "publish": ["identify", "bot"], "schedule": ["identify", "bot"]}
    EXPLAIN = {"identity": "Add Rafii's bot to a server you manage. It can post only in the channel you choose.",
               "publish": "Add Rafii's bot to a server you manage. Rafii posts in your chosen channel only when you approve each exact post."}
    account_requirement = "A Discord server where you have Manage Server permission."
    publish_scope = "bot"
    publish_required = frozenset({"bot"})
    non_expiring = True
    has_destinations = True
    # Revoking removes Rafii's one bot from the server, which every workspace connected to that server shares.
    shared_remote = True
    ADMINISTRATOR, VIEW_CHANNEL, SEND_MESSAGES = 1 << 3, 1 << 10, 1 << 11
    ALL_PERMISSIONS = (1 << 64) - 1

    def __init__(self, client_id, client_secret, bot_token, website, transport=None, production_reviewed=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        self.bot_token, self.website = bot_token, website.rstrip("/")

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, pair_valid, diagnostic = cls.credential_pair(values)
        bot, base = values.get("POSTRIFF_DISCORD_BOT_TOKEN"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        missing = list(diagnostic["missingVariables"]) + [name for name, present in (("POSTRIFF_DISCORD_BOT_TOKEN", bot is not None), ("POSTRIFF_PUBLIC_BASE_URL", bool(base))) if not present]
        anything = diagnostic["configurationState"] != "not_configured" or bot is not None
        valid = pair_valid and _credential_shape(bot) and _https_origin(base)
        state = "not_configured" if not anything else "partial_configuration" if missing else "configured" if valid else "invalid_configuration"
        diagnostic = {**diagnostic, "configurationState": state, "missingVariables": missing}
        return (cls(client_id, secret, bot, base, transport=transport) if state == "configured" else None), diagnostic

    def _basic(self):
        return "Basic " + base64.b64encode(f"{quote(self.client_id, safe='')}:{quote(self.client_secret, safe='')}".encode()).decode()

    def _bot(self, method, path, **kwargs):
        headers = {"Authorization": "Bot " + self.bot_token, "User-Agent": f"DiscordBot ({self.website}, 1)", **kwargs.pop("headers", {})}
        return self.transport(method, self.API + path, headers=headers, **kwargs)

    def authorize_url(self, redirect, state, challenge, scopes):
        # Discord's code grant has no PKCE parameter; the verifier still binds the transaction server-side.
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "response_type": "code", "redirect_uri": redirect, "scope": " ".join(scopes),
                                            "state": state, "permissions": str(self.PERMISSIONS), "integration_type": "0"})

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.API + "/oauth2/token", headers={"Authorization": self._basic()},
                                       form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}), "access_token")
        guild = body.get("guild") if isinstance(body.get("guild"), dict) else {}
        if not re.fullmatch(r"\d{5,25}", str(guild.get("id", ""))):
            raise AlphaError("Choose a server to add Rafii's bot to.", 409)
        # Who connected: channel choices are limited to channels this person can see (destinations()).
        me = self.transport("GET", self.API + "/users/@me", headers={"Authorization": "Bearer " + body["access_token"], "User-Agent": f"DiscordBot ({self.website}, 1)"})
        user_id = str(me.get("body", {}).get("id", "")) if isinstance(me.get("body"), dict) else ""
        if me.get("status") != 200 or not re.fullmatch(r"\d{5,25}", user_id):
            raise AlphaError("Discord did not confirm who is connecting. Try again.", 502)
        try:
            # Rafii posts with its bot; the person's own Discord token is not kept.
            self.transport("POST", self.API + "/oauth2/token/revoke", headers={"Authorization": self._basic()}, form={"token": body["access_token"], "token_type_hint": "access_token"})
        except AlphaError:
            pass
        scopes = body["scope"].split() if isinstance(body.get("scope"), str) else []
        return {"accessToken": json.dumps({"v": 1, "guild": str(guild["id"]), "channel": None, "user": user_id}), "refreshToken": None, "expiresIn": None, "scopes": scopes}

    @staticmethod
    def session(access_token):
        session = _load(access_token)
        if not re.fullmatch(r"\d{5,25}", str(session.get("guild", ""))):
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def identity(self, access_token):
        session = self.session(access_token)
        body = self._ok(self._bot("GET", f"/guilds/{session['guild']}"), "id")
        picture = f"https://cdn.discordapp.com/icons/{body['id']}/{body['icon']}.png" if isinstance(body.get("icon"), str) and re.fullmatch(r"[a-f0-9_]{1,64}", body["icon"]) else None
        return {"providerAccountId": str(body["id"]), "handle": str(body.get("name") or body["id"]), "accountType": "server", "pictureUrl": picture}

    def inspect_scopes(self, access_token, expected_account_id=None):
        """The bot is still in the server; the scopes are the ones Discord granted when it was added."""
        try:
            identity = self.identity(access_token)
        except AlphaError:
            return None
        if expected_account_id and identity["providerAccountId"] != expected_account_id:
            return None
        return ["bot", "identify"]

    def _json(self, response, kind):
        body = response.get("body")
        value = body.get("raw") if isinstance(body, dict) and "raw" in body else body
        if response.get("status") != 200 or not isinstance(value, kind):
            raise AlphaError("Discord didn't answer. Try again.", 502)
        return value

    def _permissions(self, guild, member_roles, member_id, channel=None):
        """Discord's documented permission algorithm: @everyone and member roles, then channel overwrites."""
        if str(guild.get("owner_id")) == str(member_id):
            return self.ALL_PERMISSIONS
        roles = {str(r.get("id")): int(r.get("permissions") or 0) for r in guild.get("roles") or [] if isinstance(r, dict)}
        base = roles.get(str(guild["id"]), 0)
        for role in member_roles:
            base |= roles.get(str(role), 0)
        if base & self.ADMINISTRATOR:
            return self.ALL_PERMISSIONS
        if channel is None:
            return base
        overwrites = {str(o.get("id")): o for o in channel.get("permission_overwrites") or [] if isinstance(o, dict)}
        everyone = overwrites.get(str(guild["id"]))
        if everyone:
            base = (base & ~int(everyone.get("deny") or 0)) | int(everyone.get("allow") or 0)
        allow = deny = 0
        for role in member_roles:
            overwrite = overwrites.get(str(role))
            if overwrite and overwrite.get("type") in (0, "0", "role"):
                allow |= int(overwrite.get("allow") or 0)
                deny |= int(overwrite.get("deny") or 0)
        base = (base & ~deny) | allow
        member = overwrites.get(str(member_id))
        if member and member.get("type") in (1, "1", "member"):
            base = (base & ~int(member.get("deny") or 0)) | int(member.get("allow") or 0)
        return base

    def _member_roles(self, guild_id, user_id):
        response = self._bot("GET", f"/guilds/{guild_id}/members/{user_id}")
        if response.get("status") == 404:
            return None
        member = self._json(response, dict)
        return [str(role) for role in member.get("roles") or []]

    def destinations(self, access_token):
        """Text and announcement channels where Rafii's bot can view and send and the person who connected can view."""
        session = self.session(access_token)
        guild = self._json(self._bot("GET", f"/guilds/{session['guild']}"), dict)
        bot_id = str(self._json(self._bot("GET", "/users/@me"), dict).get("id", ""))
        bot_roles = self._member_roles(session["guild"], bot_id) or []
        user_id = session.get("user")
        user_roles = self._member_roles(session["guild"], user_id) if user_id else []
        if user_id and user_roles is None:
            return []  # the person who connected has left the server
        channels = self._json(self._bot("GET", f"/guilds/{session['guild']}/channels"), list)
        usable = []
        for channel in channels:
            if not isinstance(channel, dict) or channel.get("type") not in (0, 5) or not re.fullmatch(r"\d{5,25}", str(channel.get("id", ""))):
                continue
            bot = self._permissions(guild, bot_roles, bot_id, channel)
            viewer = self._permissions(guild, user_roles, user_id, channel) if user_id else self._permissions(guild, [], None, channel)
            if bot & self.VIEW_CHANNEL and bot & self.SEND_MESSAGES and viewer & self.VIEW_CHANNEL:
                usable.append(channel)
        usable.sort(key=lambda c: (c.get("position") or 0, str(c.get("name"))))
        return [{"id": str(c["id"]), "name": "#" + str(c.get("name") or c["id"]), "kind": "announcement" if c.get("type") == 5 else "text",
                 "selected": str(c["id"]) == str(session.get("channel"))} for c in usable]

    def with_destination(self, access_token, destination_id):
        session = self.session(access_token)
        if not any(d["id"] == str(destination_id) for d in self.destinations(access_token)):
            raise AlphaError("Choose a text channel in this server.", 409)
        return json.dumps({**session, "channel": str(destination_id)})

    def revoke(self, token):
        # Disconnecting removes Rafii's bot from the server.
        return self._bot("DELETE", f"/users/@me/guilds/{self.session(token)['guild']}").get("status") in (200, 204)


# --- Telegram ---------------------------------------------------------------------------------------------------
class TelegramConnector(OAuthProvider):
    id, platform, capability_version = "telegram", "Telegram", 1
    API = "https://api.telegram.org"
    CODE_PREFIX = "rafii-connect-"
    CODE = re.compile(r"rafii-connect-[A-Z2-7]{16}")
    SCOPES = {"identity": ["can_post_messages"], "publish": ["can_post_messages"], "schedule": ["can_post_messages"]}
    EXPLAIN = {"identity": "Add Rafii's bot to your channel as an admin that can post, then post the code Rafii shows you.",
               "publish": "Rafii's bot posts in your channel only when you approve each exact post."}
    account_requirement = "A Telegram channel where you are an admin."
    publish_scope = "can_post_messages"
    publish_required = frozenset({"can_post_messages"})
    connect_kind = "bot_code"
    non_expiring = True
    # Revoking makes Rafii's one bot leave the channel, which every workspace connected to that channel shares.
    shared_remote = True

    def __init__(self, bot_token, webhook_secret, public_base_url, transport=None, production_reviewed=False):
        self.client_id = self.client_secret = None
        self.bot_token, self.webhook_secret = bot_token, webhook_secret
        self.public_base_url = public_base_url.rstrip("/")
        self.transport = transport or default_transport()
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True
        self._me, self._webhook_ready = None, False

    @classmethod
    def mount(cls, values, transport=None):
        token, secret, base = values.get("POSTRIFF_TELEGRAM_BOT_TOKEN"), values.get("POSTRIFF_TELEGRAM_WEBHOOK_SECRET"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        presence = {"clientId": token is not None, "clientSecret": secret is not None}
        missing = [name for name, present in (("POSTRIFF_TELEGRAM_BOT_TOKEN", token is not None), ("POSTRIFF_TELEGRAM_WEBHOOK_SECRET", secret is not None), ("POSTRIFF_PUBLIC_BASE_URL", bool(base))) if not present]
        valid = (isinstance(token, str) and re.fullmatch(r"\d{5,16}:[A-Za-z0-9_-]{30,64}", token) is not None
                 and isinstance(secret, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,256}", secret) is not None and _https_origin(base))
        state = "not_configured" if token is None and secret is None else "partial_configuration" if missing else "configured" if valid else "invalid_configuration"
        diagnostic = {"configurationState": state, "credentialPresence": presence, "missingVariables": missing}
        return (cls(token, secret, base, transport=transport) if state == "configured" else None), diagnostic

    def request(self, method, payload=None):
        """The raw Bot API response, so a publisher can tell a definite rejection from an unknown outcome."""
        return self.transport("POST", f"{self.API}/bot{self.bot_token}/{method}", body=payload or {})

    def call(self, method, payload=None):
        response = self.request(method, payload)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or body.get("ok") is not True:
            raise AlphaError("Telegram didn't accept Rafii's request.", 502 if response.get("status", 500) >= 500 else 409)
        return body.get("result")

    def webhook_url(self):
        return self.public_base_url + "/api/telegram/webhook"

    def me(self):
        if self._me is None:
            result = self.call("getMe")
            if not isinstance(result, dict) or not isinstance(result.get("id"), int) or not isinstance(result.get("username"), str):
                raise AlphaError("Telegram didn't confirm Rafii's bot.", 502)
            self._me = result
        return self._me

    def ensure_webhook(self):
        if self._webhook_ready:
            return
        info = self.call("getWebhookInfo")
        if not isinstance(info, dict) or info.get("url") != self.webhook_url():
            self.call("setWebhook", {"url": self.webhook_url(), "secret_token": self.webhook_secret, "allowed_updates": ["channel_post", "my_chat_member"]})
        self._webhook_ready = True

    def new_code(self):
        alphabet = string.ascii_uppercase + "234567"  # RFC 4648 base32
        return self.CODE_PREFIX + "".join(secrets.choice(alphabet) for _ in range(16))

    def connect_instructions(self):
        self.ensure_webhook()
        username = "@" + self.me()["username"]
        return {"botUsername": username,
                "instructions": [f"In your Telegram channel, open Administrators and add {username}.",
                                 "Allow it to post messages. It needs no other rights.",
                                 "Post the code below in the channel. Rafii's bot deletes it within seconds.",
                                 "Come back here and choose Check connection."]}

    def observe(self, update):
        """(code, chat, message id) for a channel post carrying a Rafii connect code; otherwise None."""
        post = update.get("channel_post") if isinstance(update, dict) else None
        if not isinstance(post, dict) or not isinstance(post.get("text"), str):
            return None
        match = self.CODE.search(post["text"])
        chat = post.get("chat") if isinstance(post.get("chat"), dict) else {}
        if not match or chat.get("type") != "channel" or not isinstance(chat.get("id"), int) or not isinstance(post.get("message_id"), int):
            return None
        return match.group(0), {"id": chat["id"], "title": chat.get("title"), "username": chat.get("username")}, post["message_id"]

    def delete_message(self, chat_id, message_id):
        try:
            self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except AlphaError:
            pass

    def bot_rights(self, chat_id):
        member = self.call("getChatMember", {"chat_id": chat_id, "user_id": self.me()["id"]})
        if isinstance(member, dict) and member.get("status") == "administrator" and member.get("can_post_messages") is True:
            return ["can_post_messages"]
        return []

    def grant_from_context(self, context):
        chat = context.get("chat") if isinstance(context.get("chat"), dict) else {}
        if not isinstance(chat.get("id"), int):
            raise AlphaError("Post the code in your channel first.", 409)
        return {"accessToken": json.dumps({"v": 1, "chat": chat["id"]}), "refreshToken": None, "expiresIn": None, "scopes": self.bot_rights(chat["id"])}

    @staticmethod
    def session(access_token):
        session = _load(access_token)
        if not isinstance(session.get("chat"), int):
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def identity(self, access_token):
        chat = self.call("getChat", {"chat_id": self.session(access_token)["chat"]})
        if not isinstance(chat, dict) or chat.get("type") != "channel" or not isinstance(chat.get("id"), int):
            raise AlphaError("Telegram could not confirm this channel right now.", 502)
        handle = "@" + chat["username"] if isinstance(chat.get("username"), str) else str(chat.get("title") or chat["id"])
        return {"providerAccountId": str(chat["id"]), "handle": handle, "accountType": "channel"}

    def inspect_scopes(self, access_token, expected_account_id=None):
        chat = self.session(access_token)["chat"]
        if expected_account_id and str(chat) != str(expected_account_id):
            return None
        try:
            return self.bot_rights(chat)
        except AlphaError:
            return None

    def revoke(self, token):
        # Disconnecting makes Rafii's bot leave the channel.
        try:
            return self.call("leaveChat", {"chat_id": self.session(token)["chat"]}) is True
        except AlphaError:
            return False
