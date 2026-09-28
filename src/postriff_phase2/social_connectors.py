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
from .net_guard import assert_public, public_host
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
    id, platform, capability_version = "mastodon", "Mastodon", 1
    SCOPES = {"identity": ["read:accounts"],
              "publish": ["read:accounts", "read:statuses", "write:statuses", "write:media"],
              "schedule": ["read:accounts", "read:statuses", "write:statuses", "write:media"]}
    EXPLAIN = {"identity": "Connect your Mastodon account. Rafii registers itself on your server and reads only your profile.",
               "publish": "Rafii will post to this Mastodon account only when you approve each exact post."}
    account_requirement = "An account on any Mastodon server."
    publish_scope = "write:statuses"
    publish_required = frozenset({"write:statuses"})
    start_input = {"name": "instance", "label": "Mastodon server", "placeholder": "mastodon.social"}
    non_expiring = True

    def __init__(self, website, transport=None, production_reviewed=False, resolver=socket.getaddrinfo):
        self.client_id = self.client_secret = None
        self.website = website.rstrip("/")
        self.transport = transport or default_transport()
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True
        self.resolver = resolver

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
        return assert_public(public_host(value), self.resolver)

    def begin(self, redirect, state, verifier, challenge, scopes, instance):
        host = self._server(instance)
        response = self.transport("POST", f"https://{host}/api/v1/apps", form={"client_name": "Rafii", "redirect_uris": redirect, "scopes": " ".join(scopes), "website": self.website})
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or not isinstance(body.get("client_id"), str) or not isinstance(body.get("client_secret"), str):
            raise AlphaError("That Mastodon server didn't accept Rafii. Check the server name.", 502)
        authorize = f"https://{host}/oauth/authorize?" + urlencode({"response_type": "code", "client_id": body["client_id"], "redirect_uri": redirect, "scope": " ".join(scopes),
                                                                    "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
        return {"authorizeUrl": authorize, "context": {"instance": host, "clientId": body["client_id"], "clientSecret": body["client_secret"]}}

    def exchange(self, code, verifier, redirect):
        try:
            context = json.loads(verifier)
        except (TypeError, ValueError) as error:
            raise AlphaError("Connection request unavailable.", 404) from error
        if not isinstance(context, dict) or not all(isinstance(context.get(k), str) for k in ("verifier", "instance", "clientId", "clientSecret")):
            raise AlphaError("Connection request unavailable.", 404)
        host = self._server(context["instance"])
        body = self._ok(self.transport("POST", f"https://{host}/oauth/token", form={"grant_type": "authorization_code", "code": code, "client_id": context["clientId"],
                                                                                 "client_secret": context["clientSecret"], "redirect_uri": redirect, "code_verifier": context["verifier"]}), "access_token")
        scopes = body["scope"].split() if isinstance(body.get("scope"), str) else []
        session = {"v": 1, "at": body["access_token"], "instance": host, "clientId": context["clientId"], "clientSecret": context["clientSecret"], "scope": scopes}
        return {"accessToken": json.dumps(session), "refreshToken": None, "expiresIn": None, "scopes": scopes}

    def session(self, access_token):
        session = _load(access_token)
        session["instance"] = self._server(session.get("instance"))
        return session

    def api(self, session, method, path, **kwargs):
        headers = {"Authorization": "Bearer " + session["at"], **kwargs.pop("headers", {})}
        return self.transport(method, f"https://{session['instance']}{path}", headers=headers, **kwargs)

    def identity(self, access_token):
        session = self.session(access_token)
        body = self._ok(self.api(session, "GET", "/api/v1/accounts/verify_credentials"), "id")
        username = body.get("username") if isinstance(body.get("username"), str) else str(body["id"])
        return {"providerAccountId": f"{body['id']}@{session['instance']}", "handle": f"@{username}@{session['instance']}", "accountType": "profile"}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self.session(access_token)
        response = self.api(session, "GET", "/api/v1/apps/verify_credentials")
        body = response.get("body")
        if response.get("status") != 200 or not isinstance(body, dict):
            return None
        live = body.get("scopes")
        if isinstance(live, list) and all(isinstance(s, str) for s in live):
            return sorted(set(live))
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
