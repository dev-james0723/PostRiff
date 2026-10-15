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
    # View Channel, Send Messages, Attach Files and Read Message History (receipt lookup).
    PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 15) | (1 << 16)
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
    MANAGE_GUILD, ATTACH_FILES, READ_HISTORY = 1 << 5, 1 << 15, 1 << 16
    ALL_PERMISSIONS = (1 << 64) - 1

    def __init__(self, client_id, client_secret, bot_token, website, transport=None, production_reviewed=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        self.bot_token, self.website = bot_token, website.rstrip("/")
        # Local candidate stays off until a separately approved rollout.
        self.authorization_v2_enabled = False
        self.connections_v2_enabled = False
        self.rate_v1_enabled = False
        self.rate_policy_raw = None
        self.rate_limiter = None
        self.rate_coordinator_degraded = False
        self._bot_identity_cache = None

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, pair_valid, diagnostic = cls.credential_pair(values)
        bot, base = values.get("POSTRIFF_DISCORD_BOT_TOKEN"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        missing = list(diagnostic["missingVariables"]) + [name for name, present in (("POSTRIFF_DISCORD_BOT_TOKEN", bot is not None), ("POSTRIFF_PUBLIC_BASE_URL", bool(base))) if not present]
        anything = diagnostic["configurationState"] != "not_configured" or bot is not None
        valid = pair_valid and _credential_shape(bot) and _https_origin(base)
        state = "not_configured" if not anything else "partial_configuration" if missing else "configured" if valid else "invalid_configuration"
        diagnostic = {**diagnostic, "configurationState": state, "missingVariables": missing}
        adapter = cls(client_id, secret, bot, base, transport=transport) if state == 'configured' else None
        if adapter is not None:
            adapter.authorization_v2_enabled = values.get('POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED') == 'true'
            adapter.connections_v2_enabled = values.get('POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED') == 'true'
            adapter.rate_v1_enabled = values.get('POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED') == 'true'
            adapter.rate_policy_raw = values.get('POSTRIFF_DISCORD_RATE_POLICY')
        return adapter, diagnostic

    def _basic(self):
        return "Basic " + base64.b64encode(f"{quote(self.client_id, safe='')}:{quote(self.client_secret, safe='')}".encode()).decode()

    def _rate_identity(self, kind, bearer=None, user_id=None):
        from .discord.rate_limits import RequestIdentity
        credential = self.bot_token if kind == 'bot' else bearer if kind == 'user' else self.client_secret
        return RequestIdentity.make(self.client_id, kind, credential, user_id)

    def admit_bot_request(self, method, path, *, binding=None, valid_until=None):
        """Reserve one atomic global/route slot before an irreversible publication intent."""
        from .discord.rate_limits import RateCoordinatorUnavailable
        if not self.rate_v1_enabled:
            return None  # historical local fixtures; production worker requires P4
        if self.rate_coordinator_degraded or self.rate_limiter is None:
            raise RateCoordinatorUnavailable()
        return self.rate_limiter.reserve(method, path, identity=self._rate_identity('bot'),
                                         binding=binding, valid_until=valid_until)

    def _bot(self, method, path, **kwargs):
        extra = kwargs.pop('headers',{})
        if any(k.lower() in ('authorization','user-agent') for k in extra):
            raise AlphaError('Discord request credentials cannot be overridden.',409)
        headers = {"Authorization": "Bot " + self.bot_token, "User-Agent": f"DiscordBot ({self.website}, 1)", **extra}
        return self._discord_http(method, path, headers=headers, credential_kind='bot', **kwargs)

    def _discord_http(self, method, path, *, credential_kind, bearer=None, user_id=None, **kwargs):
        from .discord.rate_limits import Permit, RateDelayed, RateCoordinatorUnavailable, UnconsumedPublishPermit, ReadAdmissionDelayed
        rate_permit = kwargs.pop('rate_permit', None)
        binding = kwargs.pop('rate_binding', None)
        intent_id = kwargs.pop('rate_intent_id', None)
        authorize = kwargs.pop('rate_authorize', None)
        if (self.rate_v1_enabled and method == 'POST'
                and path.startswith('/channels/') and path.endswith('/messages')
                and (rate_permit is None or binding is None or not callable(authorize))):
            # A message create requires pre-seal admission, never an implicit
            # allocation after the P0 intent has already committed.
            raise RateCoordinatorUnavailable()
        if self.rate_v1_enabled:
            if self.rate_coordinator_degraded or self.rate_limiter is None:
                raise RateCoordinatorUnavailable()
            policy = self.rate_limiter.policy
            if policy is None:
                raise RateCoordinatorUnavailable()
            # These denials precede transport. In particular, an OAuth code is
            # not exchanged again and a message permit is never reallocated.
            resumable = (rate_permit is None and binding is None and
                         (method == 'GET' or method == 'POST' and path in ('/oauth2/token','/oauth2/token/revoke')))
            attempts = policy.read_attempts if resumable else 1
            wait_deadline = time.monotonic() + 1
            for attempt in range(attempts):
                try:
                    permit = rate_permit if isinstance(rate_permit, Permit) else (
                        self.rate_limiter.reserve(method, path, identity=self._rate_identity(credential_kind,bearer,user_id))
                        if rate_permit is None else None)
                    if permit is None or permit.identity != self._rate_identity(credential_kind,bearer,user_id):
                        raise RateCoordinatorUnavailable()
                    self.rate_limiter.consume(permit, method, path, binding=binding, intent_id=intent_id, authorize=authorize)
                    break
                except RateDelayed as error:
                    if (isinstance(rate_permit, Permit) and binding is not None
                            and error.rate_cause == 'permit_expired'):
                        # Mint only around admission/consume, before transport.
                        # A transport exception can never acquire this proof.
                        raise UnconsumedPublishPermit(rate_permit.id, error.retry_after_seconds) from error
                    wait = max(error.retry_after_seconds, .005 * 2 ** attempt) + secrets.randbelow(26) / 1000
                    if not resumable or attempt + 1 >= attempts or time.monotonic() + wait > wait_deadline:
                        if method == 'GET':
                            raise ReadAdmissionDelayed(error) from error
                        raise
                    time.sleep(wait)
        elif rate_permit is not None:
            raise RateCoordinatorUnavailable()
        try:
            response = self.transport(method, self.API + path, **kwargs)
        except Exception:
            if self.rate_v1_enabled:
                try:
                    self.rate_limiter.note_transport_failure(permit)
                except Exception:
                    self.rate_coordinator_degraded = True
            raise
        if self.rate_v1_enabled:
            try:
                observation = self.rate_limiter.observe(permit, response)
            except Exception:
                self.rate_coordinator_degraded = True
                # A POST may already have been accepted. Preserve the provider
                # message ID/receipt instead of hiding it behind a ledger error.
                if method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
                    raise RateCoordinatorUnavailable()
            if response.get('status') == 429 and method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
                # Read/preflight requests are proven rejected and may defer
                # without spending a Discord publication attempt.
                if observation['retryHintMalformed']:
                    raise RateCoordinatorUnavailable()
                raise RateDelayed(observation['retryAfterSeconds'], cause='provider_429')
            if response.get('status') in (401,403,404) and method == 'GET':
                error = AlphaError('Discord access was removed. Reconnect or authorize this exact destination again.',409,
                                   code='discord_connection_required')
                error.discord_permanent = True
                raise error
        return response

    def authorize_url(self, redirect, state, challenge, scopes):
        # Current Web API code-grant docs do not document PKCE parameters. Do not
        # infer support from the separate Social SDK; retain server-side state binding.
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "response_type": "code", "redirect_uri": redirect, "scope": " ".join(scopes),
                                            "state": state, "permissions": str(self.PERMISSIONS), "integration_type": "0"})

    def exchange(self, code, verifier, redirect):
        body = self._ok(self._discord_http("POST", "/oauth2/token", credential_kind='oauth', headers={"Authorization": self._basic()},
                                       form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}), "access_token")
        guild = body.get("guild") if isinstance(body.get("guild"), dict) else {}
        if not re.fullmatch(r"\d{5,25}", str(guild.get("id", ""))):
            raise AlphaError("Choose a server to add Rafii's bot to.", 409)
        # Who connected: channel choices are limited to channels this person can see (destinations()).
        me = self._discord_http("GET", "/users/@me", credential_kind='user', bearer=body['access_token'], headers={"Authorization": "Bearer " + body["access_token"], "User-Agent": f"DiscordBot ({self.website}, 1)"})
        user_id = str(me.get("body", {}).get("id", "")) if isinstance(me.get("body"), dict) else ""
        if me.get("status") != 200 or not re.fullmatch(r"\d{5,25}", user_id):
            raise AlphaError("Discord did not confirm who is connecting. Try again.", 502)
        try:
            # Rafii posts with its bot; the person's own Discord token is not kept.
            self._discord_http("POST", "/oauth2/token/revoke", credential_kind='oauth', headers={"Authorization": self._basic()}, form={"token": body["access_token"], "token_type_hint": "access_token"})
        except AlphaError:
            pass
        scopes = body["scope"].split() if isinstance(body.get("scope"), str) else []
        bot_id = self._bot_identity()
        return {"accessToken": json.dumps({"v": 2, "applicationId": self.client_id, 'botUserId': bot_id,
                "guild": str(guild["id"]), "channel": None, "user": user_id}),
                "refreshToken": None, "expiresIn": None, "scopes": scopes}

    @staticmethod
    def session(access_token):
        try:
            session = json.loads(access_token)
        except (TypeError, ValueError):
            raise AlphaError('This Discord connection needs to be reconnected.', 409) from None
        if not isinstance(session, dict) or type(session.get('v')) is not int or session['v'] not in (1, 2):
            raise AlphaError('This Discord connection needs to be reconnected.', 409)
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
        from .discord.authorization import snowflake
        roles_raw = guild.get('roles')
        if (not snowflake(str(guild.get('id', ''))) or not snowflake(str(guild.get('owner_id', '')))
                or not isinstance(roles_raw, list) or not isinstance(member_roles, list)
                or not snowflake(str(member_id))):
            raise AlphaError('Discord permission evidence is incomplete. Reconnect or restore access.', 409)
        roles = {}
        for role in roles_raw:
            if (not isinstance(role, dict) or not snowflake(str(role.get('id', '')))
                    or not re.fullmatch(r'[0-9]+', str(role.get('permissions', '')))
                    or str(role['id']) in roles):
                raise AlphaError('Discord role evidence is incomplete.', 409)
            roles[str(role['id'])] = int(role['permissions'])
        if str(guild['id']) not in roles or any(str(role) not in roles for role in member_roles):
            raise AlphaError('Discord role evidence is incomplete.', 409)
        overwrites = {}
        if channel is not None:
            if channel.get('guild_id') != str(guild['id']) or not isinstance(channel.get('permission_overwrites'), list):
                raise AlphaError('Discord channel permission evidence is incomplete.', 409)
            for overwrite in channel['permission_overwrites']:
                if (not isinstance(overwrite, dict) or not snowflake(str(overwrite.get('id', '')))
                        or type(overwrite.get('type')) is not int or overwrite['type'] not in (0, 1)
                        or any(not re.fullmatch(r'[0-9]+', str(overwrite.get(k, ''))) for k in ('allow', 'deny'))
                        or (str(overwrite['id']), overwrite['type']) in overwrites):
                    raise AlphaError('Discord channel overwrite evidence is incomplete.', 409)
                overwrites[(str(overwrite['id']), overwrite['type'])] = overwrite
        if str(guild.get("owner_id")) == str(member_id):
            return self.ALL_PERMISSIONS
        base = roles.get(str(guild["id"]), 0)
        for role in member_roles:
            base |= roles.get(str(role), 0)
        if base & self.ADMINISTRATOR:
            return self.ALL_PERMISSIONS
        if channel is None:
            return base
        everyone = overwrites.get((str(guild["id"]), 0))
        if everyone:
            base = (base & ~int(everyone.get("deny") or 0)) | int(everyone.get("allow") or 0)
        allow = deny = 0
        for role in member_roles:
            overwrite = overwrites.get((str(role), 0))
            if overwrite and overwrite.get("type") in (0, "0", "role"):
                allow |= int(overwrite.get("allow") or 0)
                deny |= int(overwrite.get("deny") or 0)
        base = (base & ~deny) | allow
        member = overwrites.get((str(member_id), 1))
        if member and member.get("type") in (1, "1", "member"):
            base = (base & ~int(member.get("deny") or 0)) | int(member.get("allow") or 0)
        return base

    def _member_roles(self, guild_id, user_id):
        response = self._bot("GET", f"/guilds/{guild_id}/members/{user_id}")
        if response.get("status") == 404:
            return None
        member = self._json(response, dict)
        if (not isinstance(member.get('roles'), list)
                or (member.get('user') or {}).get('id') != str(user_id)
                or any(not re.fullmatch(r'[0-9]{5,25}', str(role)) for role in member['roles'])):
            raise AlphaError('Discord did not confirm this server membership.', 409)
        if 'pending' in member and type(member['pending']) is not bool:
            raise AlphaError('Discord membership screening evidence is invalid.', 409)
        if member.get('pending') is True:
            return None
        timeout = member.get('communication_disabled_until')
        if timeout is not None:
            from datetime import datetime, timezone
            try:
                until = datetime.fromisoformat(timeout.replace('Z', '+00:00'))
                if until.tzinfo is None:
                    raise ValueError()
            except (AttributeError, TypeError, ValueError):
                raise AlphaError('Discord membership restriction evidence is invalid.', 409) from None
            if until > datetime.now(timezone.utc):
                return None
        return [str(role) for role in member['roles']]

    def _bot_identity(self):
        from .discord.rate_limits import _digest, RateCoordinatorUnavailable
        cache_enabled = self.authorization_v2_enabled and self.connections_v2_enabled and self.rate_v1_enabled
        if cache_enabled and (self.rate_coordinator_degraded or self.rate_limiter is None
                              or self.rate_limiter.policy is None):
            raise RateCoordinatorUnavailable()
        key = (self.client_id, _digest(self.bot_token))
        cached = self._bot_identity_cache
        now = time.monotonic()
        if cache_enabled and cached and cached[:2] == key and 0 <= now-cached[3] < 60:
            return cached[2]
        application = self._json(self._bot('GET', '/oauth2/applications/@me'), dict)
        me = self._json(self._bot('GET', '/users/@me'), dict)
        if (str(application.get('id')) != self.client_id or me.get('bot') is not True
                or not re.fullmatch(r'[0-9]{5,25}', str(me.get('id', '')))):
            raise AlphaError('The Discord bot and application do not match. Ask the workspace owner to reconnect.', 409)
        if cache_enabled:
            # Only immutable bot/application IDs are retained, never permission
            # evidence. Every destination operation still rechecks live guild,
            # membership and channel permissions through the shared coordinator.
            self._bot_identity_cache = (*key, str(me['id']), time.monotonic())
        return str(me['id'])

    def destinations(self, access_token):
        """Explicit installation, server-manager and effective channel permission evidence."""
        session = self.session(access_token)
        if (session.get('v') != 2 or session.get('applicationId') != self.client_id
                or any(not re.fullmatch(r'[0-9]{5,25}', str(session.get(k, ''))) for k in ('botUserId', 'user', 'guild'))):
            raise AlphaError('Reconnect Discord to bind the application, bot and authorizing user before choosing channels.', 409)
        guild = self._json(self._bot("GET", f"/guilds/{session['guild']}"), dict)
        bot_id = self._bot_identity()
        if (guild.get('id') != session['guild'] or session.get('applicationId') != self.client_id
                or session.get('botUserId') != bot_id):
            raise AlphaError('Reconnect this Discord installation before authorizing channels.', 409)
        bot_roles = self._member_roles(session["guild"], bot_id)
        user_id = session.get("user")
        if not re.fullmatch(r'[0-9]{5,25}', str(user_id or '')):
            raise AlphaError('Reconnect to confirm the Discord user who authorizes this server.', 409)
        user_roles = self._member_roles(session['guild'], user_id)
        if bot_roles is None or user_roles is None:
            return []
        if not self._permissions(guild, user_roles, user_id) & self.MANAGE_GUILD:
            return []
        channels = self._json(self._bot("GET", f"/guilds/{session['guild']}/channels"), list)
        usable = []
        for channel in channels:
            if not isinstance(channel, dict) or channel.get("type") not in (0, 5) or not re.fullmatch(r"\d{5,25}", str(channel.get("id", ""))):
                continue
            bot = self._permissions(guild, bot_roles, bot_id, channel)
            viewer = self._permissions(guild, user_roles, user_id, channel)
            required = self.VIEW_CHANNEL | self.SEND_MESSAGES | self.READ_HISTORY
            if bot & required == required and viewer & (self.VIEW_CHANNEL | self.SEND_MESSAGES) == (self.VIEW_CHANNEL | self.SEND_MESSAGES):
                usable.append({**channel, 'botPermissions': bot})
        usable.sort(key=lambda c: (c.get("position") or 0, str(c.get("name"))))
        return [{"id": str(c["id"]), "name": "#" + str(c.get("name") or c["id"]), "kind": "announcement" if c.get("type") == 5 else "text",
                 "selected": str(c["id"]) == str(session.get("channel")), 'applicationId': self.client_id,
                 'botUserId': bot_id, 'linkedUserId': user_id, 'guildId': session['guild'],
                 'guildName': str(guild.get('name') or session['guild']), 'channelId': str(c['id']),
                 'channelName': '#' + str(c.get('name') or c['id']), 'botPermissions': c['botPermissions']} for c in usable]

    def with_destination(self, access_token, destination_id):
        session = self.session(access_token)
        evidence = next((d for d in self.destinations(access_token) if d['id'] == str(destination_id)), None)
        if evidence is None:
            raise AlphaError("Choose a text channel in this server.", 409)
        return json.dumps({**session, "channel": str(destination_id), 'destinationEvidence': evidence})

    def authorize_destination(self, access_token, target, *, media=False):
        evidence = next((d for d in self.destinations(access_token) if d['id'] == target['channelId']), None)
        if (not evidence or any(evidence.get(k) != target.get(k) for k in
                               ('applicationId', 'botUserId', 'linkedUserId', 'guildId', 'channelId'))
                or media and not evidence['botPermissions'] & self.ATTACH_FILES):
            raise AlphaError('The approved Discord destination is unavailable or lacks permission. Nothing was posted.', 409)
        return evidence

    def revoke(self, token):
        if self.connections_v2_enabled:
            raise AlphaError('Use workspace-local disconnect; removing the shared bot requires separate server administration.', 409)
        # Legacy operator-only removal; v2 user disconnect never reaches this path.
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
