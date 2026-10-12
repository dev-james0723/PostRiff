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
import time
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
    id, platform, capability_version = "telegram", "Telegram", 2
    API = "https://api.telegram.org"
    CODE_PREFIX = "rafii-connect-"
    CODE = re.compile(r"rafii-connect-[A-Z2-7]{16}")
    # Bot authorization is membership/admin rights, not OAuth scopes. The destination
    # matrix, not a universal requested-right list, controls publication.
    SCOPES = {"identity": [], "publish": [], "schedule": []}
    EXPLAIN = {"identity": "Add Rafii's bot to the channel/group you control, then send the one-time code there. Rafii reads its actual membership and rights.",
               "publish": "Choose the channel, group or topic Rafii may control. Grant only the rights you need; each post requires an exact approval."}
    account_requirement = "A Telegram channel/group you control, or a private chat you started with the bot."
    publish_scope = "can_post_messages"
    publish_required = frozenset({"can_post_messages"})
    connect_kind = "bot_code"
    non_expiring = True
    # Revoking makes Rafii's one bot leave the channel, which every workspace connected to that channel shares.
    shared_remote = True
    server_schedule = True
    ALLOWED_UPDATES = ["managed_bot", "message", "edited_message", "channel_post", "edited_channel_post", "message_reaction", "message_reaction_count", "poll", "poll_answer", "business_connection", "business_message", "edited_business_message", "deleted_business_messages", "my_chat_member", "chat_member", "chat_join_request", "callback_query"]
    # Telegram bot authorization is destination-scoped. There is no Instagram-style app review.
    # The publisher additionally requires fresh actual rights and real acceptance evidence.
    account_scoped_direct = True
    ACCEPTANCE_VERSION = 'rafii.telegram.bot.v2'

    def __init__(self, bot_token, webhook_secret, public_base_url, transport=None, production_reviewed=False):
        self.client_id = self.client_secret = None
        self.bot_token, self.webhook_secret = bot_token, webhook_secret
        self.public_base_url = public_base_url.rstrip("/")
        self.transport = transport or default_transport()
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True
        self._me, self._webhook_ready = None, False
        self.acceptance = {}
        self.candidate_mode = False
        self.candidate_scope = {}
        self.file_check = None
        self.credential_resolver = None
        self.bot_ref = None
        self.business_resolver = None
        self.destination_authorizer=None

    def for_session(self, session):
        if not session.get("botRef"): return self
        if not self.credential_resolver or not session.get("workspace"):
            raise AlphaError("Bot credential unavailable.", 409)
        return self.credential_resolver(session["workspace"], session["botRef"])

    def qualified(self, chat_id, mode="bot", business_id=None):
        from .telegram.qualification import release_capabilities, proven
        # New destinations reuse a real-tested release, with live authorization
        # and action rights still checked separately before every operation.
        released = release_capabilities(self.acceptance.get('_release'), mode)
        evidence = self.acceptance.get(str(chat_id), {})
        if not isinstance(evidence, dict) or evidence.get("source") != "telegram_real_e2e" or evidence.get("botId") != self.me()["id"] or evidence.get('qualificationVersion') != self.ACCEPTANCE_VERSION:
            return released
        cases = evidence.get('cases', [])
        if not isinstance(cases, list):
            return released
        return released | {case["capability"] for case in cases if proven(case)
                and case.get("connectionType", "bot") == mode and (mode != "business" or case.get("businessConnectionId") == business_id)
                and isinstance(case.get('capability'),str) and case.get("passed") is True and type(case.get("messageId")) is int and case["messageId"] > 0
                }

    def candidate_capabilities(self, chat_id, mode="bot", business_id=None, *, workspace_id=None, actor_id=None):
        """A bounded owner canary is not evidence of a public production release."""
        from .telegram.capabilities import CATALOG
        scope = self.candidate_scope
        if (not scope or scope.get('expiresAt', 0) <= time.time()
                or not workspace_id or str(workspace_id) != scope.get('workspaceId')
                or not actor_id or str(actor_id) != scope.get('actorId')
                or scope.get('botId') != self.me()['id']):
            return set()
        for destination in scope.get('destinations', []):
            if (str(destination.get('chatId')) == str(chat_id) and destination.get('mode') == mode
                    and (mode != 'business' or destination.get('businessConnectionId') == business_id)):
                return {name for name in destination.get('capabilities', [])
                        if name in CATALOG and CATALOG[name].implemented}
        return set()

    @classmethod
    def mount(cls, values, transport=None):
        token, secret, base = values.get("POSTRIFF_TELEGRAM_BOT_TOKEN"), values.get("POSTRIFF_TELEGRAM_WEBHOOK_SECRET"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        presence = {"clientId": token is not None, "clientSecret": secret is not None}
        missing = [name for name, present in (("POSTRIFF_TELEGRAM_BOT_TOKEN", token is not None), ("POSTRIFF_TELEGRAM_WEBHOOK_SECRET", secret is not None), ("POSTRIFF_PUBLIC_BASE_URL", bool(base))) if not present]
        valid = (isinstance(token, str) and re.fullmatch(r"\d{5,16}:[A-Za-z0-9_-]{30,64}", token) is not None
                 and isinstance(secret, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,256}", secret) is not None and _https_origin(base))
        state = "not_configured" if token is None and secret is None else "partial_configuration" if missing else "configured" if valid else "invalid_configuration"
        diagnostic = {"configurationState": state, "credentialPresence": presence, "missingVariables": missing}
        adapter = cls(token, secret, base, transport=transport) if state == "configured" else None
        if adapter is None and token is None and secret is None and values.get('POSTRIFF_TELEGRAM_BYOB_ENABLED','').lower() == 'true' and _https_origin(base):
            adapter = cls('', '', base, transport=transport)
            diagnostic.update(configurationState='own_bot_only', managedBotAvailable=False, missingVariables=[])
        if adapter and values.get("POSTRIFF_TELEGRAM_ACCEPTANCE_JSON"):
            try:
                raw = values['POSTRIFF_TELEGRAM_ACCEPTANCE_JSON']
                evidence = json.loads(raw) if isinstance(raw, str) and len(raw) <= 65536 else None
                if isinstance(evidence, dict): adapter.acceptance = evidence
            except (ValueError, TypeError):
                diagnostic['acceptanceState'] = 'unavailable'
        elif adapter and values.get("POSTRIFF_TELEGRAM_ACCEPTANCE_FILE"):
            try:
                from pathlib import Path
                path = Path(values["POSTRIFF_TELEGRAM_ACCEPTANCE_FILE"])
                if path.stat().st_size <= 65536:
                    evidence = json.loads(path.read_text())
                    if isinstance(evidence, dict): adapter.acceptance = evidence
            except (OSError, ValueError, TypeError):
                diagnostic["acceptanceState"] = "unavailable"
        # Issue #179: the old staging QA grant is deliberately ignored. Owner
        # acceptance runs on the verified production service with a default-off,
        # expiring server manifest. It never enables another member or workspace.
        if adapter and values.get('POSTRIFF_TELEGRAM_CANARY_ENABLED') == 'true':
            adapter.candidate_mode = True
            try:
                from .telegram.qualification import positive_number
                from .social_release import require_production_binding
                from uuid import UUID
                require_production_binding(values)
                if values.get('VERCEL_ENV') != 'production':
                    raise ValueError('Owner canary requires a held production service build.')
                raw = values.get('POSTRIFF_TELEGRAM_CANARY_SCOPE', '')
                scope = json.loads(raw) if isinstance(raw, str) and len(raw) <= 8192 else None
                if (isinstance(scope, dict) and type(scope.get('botId')) is int
                        and 0 < scope['botId'] < 2**52
                        and all(isinstance(scope.get(k), str) and str(UUID(scope[k])) == scope[k] for k in ('workspaceId', 'actorId'))
                        and positive_number(scope.get('expiresAt')) and time.time() < scope['expiresAt'] <= time.time() + 86400
                        and isinstance(scope.get('destinations'), list) and 0 < len(scope['destinations']) <= 4
                        and all(isinstance(d, dict) and type(d.get('chatId')) is int
                                and 0 < abs(d['chatId']) < 2**52
                                and d.get('mode') in ('bot', 'business')
                                and isinstance(d.get('capabilities'), list)
                                and all(isinstance(n, str) for n in d['capabilities'])
                                and (d['mode'] != 'business' or isinstance(d.get('businessConnectionId'), str) and bool(d['businessConnectionId']))
                                for d in scope['destinations'])):
                    adapter.candidate_scope = scope
                    diagnostic['candidateExecution'] = True
            except (TypeError, ValueError):
                diagnostic['candidateExecution'] = False
        return adapter, diagnostic

    def request(self, method, payload=None, files=None):
        """The raw Bot API response, so a publisher can tell a definite rejection from an unknown outcome."""
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,80}", method):
            raise AlphaError("Unsupported Telegram operation.", 400)
        if not self.bot_token: raise AlphaError("The managed Rafii bot is not configured. Select an encrypted BotFather bot instead.", 409)
        try:
            if files:
                data, content_type = multipart([(k, json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v)) for k, v in (payload or {}).items()], files)
                return self.transport("POST", f"{self.API}/bot{self.bot_token}/{method}", headers={"Content-Type": content_type}, data=data)
            return self.transport("POST", f"{self.API}/bot{self.bot_token}/{method}", body=payload or {})
        except Exception:
            # The token is part of the request URL. Transport exceptions are confidential.
            raise AlphaError("Telegram transport is unavailable; the request outcome may be unknown.", 502, code="telegram_transport_unknown") from None

    def call(self, method, payload=None):
        response = self.request(method, payload)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or body.get("ok") is not True:
            raise AlphaError("Telegram didn't accept Rafii's request.", 502 if response.get("status", 500) >= 500 else 409)
        return body.get("result")

    def webhook_url(self):
        return self.public_base_url + ("/api/telegram/bots/" + self.bot_ref + "/webhook" if self.bot_ref else "/api/telegram/webhook")

    def me(self):
        if self._me is None:
            result = self.call("getMe")
            if not isinstance(result, dict) or not isinstance(result.get("id"), int) or not isinstance(result.get("username"), str):
                raise AlphaError("Telegram didn't confirm Rafii's bot.", 502)
            self._me = result
        return self._me

    def ensure_webhook(self, force=False):
        if self._webhook_ready and not force:
            return
        info = self.call("getWebhookInfo")
        if force or not isinstance(info, dict) or info.get("url") != self.webhook_url() or not set(self.ALLOWED_UPDATES) <= set(info.get("allowed_updates", [])):
            self.call("setWebhook", {"url": self.webhook_url(), "secret_token": self.webhook_secret, "allowed_updates": self.ALLOWED_UPDATES})
        self._webhook_ready = True

    def new_code(self):
        alphabet = string.ascii_uppercase + "234567"  # RFC 4648 base32
        return self.CODE_PREFIX + "".join(secrets.choice(alphabet) for _ in range(16))

    def connect_instructions(self):
        self.ensure_webhook()
        username = "@" + self.me()["username"]
        return {"botUsername": username,
                "openTelegramUrl": "https://t.me/" + self.me()["username"],
                "instructions": [f"Add {username} to the channel or group you control.",
                                 "Channels need Post Messages; groups need permission to send the selected content. Editing, pinning, topics and moderation require separate rights.",
                                 "Send the code below as a destination administrator (or in your own private bot chat). Rafii removes it only where deletion is allowed.",
                                 "Come back here and choose Check connection."]}

    def observe(self, update):
        """(code, chat, message id) for a channel post carrying a Rafii connect code; otherwise None."""
        post = (update.get("channel_post") or update.get("message")) if isinstance(update, dict) else None
        if not isinstance(post, dict) or not isinstance(post.get("text"), str):
            return None
        match = self.CODE.search(post["text"])
        chat = post.get("chat") if isinstance(post.get("chat"), dict) else {}
        if ('channel_post' in update) != (chat.get('type') == 'channel'): return None
        if not match or chat.get("type") not in ("channel", "group", "supergroup", "private") or not isinstance(chat.get("id"), int) or not isinstance(post.get("message_id"), int):
            return None
        return match.group(0), {"id": chat["id"], "title": chat.get("title"), "username": chat.get("username"), "type": chat.get("type"), "thread": post.get("message_thread_id"), "userId": (post.get("from") or {}).get("id"), 'senderChatId':(post.get('sender_chat') or {}).get('id')}, post["message_id"]

    def delete_message(self, chat_id, message_id):
        try:
            self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except AlphaError:
            pass

    def bot_rights(self, chat_id):
        member = self.call("getChatMember", {"chat_id": chat_id, "user_id": self.me()["id"]})
        if isinstance(member, dict) and member.get("status") in ("creator", "administrator", "member", "restricted"):
            return sorted(k for k, v in member.items() if k.startswith("can_") and v is True)
        return []

    def grant_from_context(self, context):
        chat = context.get("chat") if isinstance(context.get("chat"), dict) else {}
        if not isinstance(chat.get("id"), int):
            raise AlphaError("Post the code in your channel first.", 409)
        destination = self.call("getChat", {"chat_id": chat["id"]})
        if not isinstance(destination, dict) or destination.get("id") != chat["id"]:
            raise AlphaError("Telegram destination could not be confirmed.", 409)
        if destination.get('type') in ('group','supergroup') and chat.get('senderChatId')!=chat['id']:
            sender=chat.get('userId')
            if type(sender) is not int or sender<=0:raise AlphaError('Have a group administrator send the destination connection code.',409)
            try:member=self.call('getChatMember',{'chat_id':chat['id'],'user_id':sender})
            except AlphaError:raise AlphaError('Rafii could not verify the group administrator who sent the code. Verify bot access and send a fresh code.',409) from None
            if not isinstance(member,dict) or member.get('status') not in ('creator','administrator'):raise AlphaError('Only a group administrator may authorize this destination in Rafii.',403)
        session = {"v": 1, "chat": chat["id"]}
        if context.get("botRef"):
            session.update(botRef=context["botRef"], workspace=context["workspace"])
        if chat.get("thread"): session["thread"] = chat["thread"]
        if destination.get("type") == "private" and chat.get("userId") == chat["id"]: session["telegram_user_id"] = chat["userId"]
        return {"accessToken": json.dumps(session), "refreshToken": None, "expiresIn": None, "scopes": self.bot_rights(chat["id"])}

    @staticmethod
    def session(access_token):
        session = _load(access_token)
        if not isinstance(session.get("chat"), int):
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def identity(self, access_token):
        session = self.session(access_token)
        adapter = self.for_session(session)
        if session.get("business_connection_id"):
            if not adapter.business_resolver: raise AlphaError("Business connection unavailable.", 409)
            _, chat, _ = adapter.business_resolver(session["workspace"], session["business_connection_id"], session["chat"])
            return {"providerAccountId": str(chat["id"]), "handle": str(chat.get("first_name") or chat["id"]), "accountType": "business_conversation"}
        chat = adapter.call("getChat", {"chat_id": session["chat"]})
        if not isinstance(chat, dict) or chat.get("type") not in ("channel", "group", "supergroup", "private") or not isinstance(chat.get("id"), int):
            raise AlphaError("Telegram could not confirm this destination right now.", 502)
        handle = "@" + chat["username"] if isinstance(chat.get("username"), str) else str(chat.get("title") or chat["id"])
        return {"providerAccountId": str(chat["id"]), "handle": handle, "accountType": chat["type"]}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self.session(access_token)
        chat = session["chat"]
        if expected_account_id and str(chat) != str(expected_account_id):
            return None
        try:
            if session.get("business_connection_id"):
                adapter = self.for_session(session)
                business, _, _ = adapter.business_resolver(session["workspace"], session["business_connection_id"], chat)
                return sorted(k for k, v in business.get("rights", {}).items() if v is True)
            return self.for_session(session).bot_rights(chat)
        except AlphaError:
            return None

    def revoke(self, token):
        # Disconnecting makes Rafii's bot leave the channel.
        try:
            session = self.session(token)
            if session.get("business_connection_id") or session.get('thread') or session.get('dm_topic'):
                return False  # Local destination revoke only; never claim a global remote revocation or leave its parent chat.
            return self.for_session(session).call("leaveChat", {"chat_id": session["chat"]}) is True
        except AlphaError:
            return False
