"""Synthetic multi-tenant webhook world for the sender-name tests: tenants with real review and approval commands, and an
in-process Discord whose execute-webhook route records exactly what each request carried.

Nothing here reaches a network or reads an application credential. Every id, name and credential is generated or
synthetic; webhook credentials are produced at run time, never written down.
"""
import copy
import hashlib
import json
import re
import secrets
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import test_discord_publish_authorization as P
from postriff_phase2.discord import authorization as auth
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.social_connectors import DiscordProvider

APP, BOT, USER, ACTOR, NOW, GENERATION = P.APP, P.BOT, P.USER, P.ACTOR, P.NOW, P.GENERATION
DEFAULT_HOOK_NAME = 'Spare Webhook'
SECOND_USER = '4242425'


class Tenant:
    """One workspace with one webhook connection (or one bot installation) and its own server, channel and webhook."""
    def __init__(self, index, name=None, *, kind='webhook', now=None):
        self.index, self.kind, self.name = index, kind, name
        self.now = NOW if now is None else now
        self.workspace = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-tenant-{index}.example.invalid'))
        self.guild, self.channel = str(6100000 + index), str(7100000 + index)
        self.hook = str(8100000 + index)
        self.hook_credential = secrets.token_urlsafe(32)   # generated per run
        self.connection = f'discord-{kind}-{index:04d}'
        self.generation = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-generation-{index}.example.invalid'))
        self.engine = self.state = self.channel_record = self.variant = None

    # -- build ------------------------------------------------------------------------------------------------------
    def patched(self):
        stack = [patch.object(P, 'WORKSPACE', self.workspace), patch.object(P, 'GUILD', self.guild),
                 patch.object(P, 'FIRST', self.channel), patch.object(P, 'SECOND', str(int(self.channel) + 500000)),
                 patch.object(P, 'GENERATION', self.generation), patch.object(P, 'NOW', self.now)]
        return _Stack(stack)

    def build(self, *, text='Synthetic sender-name post'):
        with self.patched():
            engine, state, channel, variant = P.fixture()
        channel.update(id=self.connection, discordAuthorizationGeneration=self.generation)
        if self.kind == 'webhook':
            channel.update(scopes=['identify', 'webhook.incoming'], discordConnectionKind='webhook', providerAccountId=self.hook,
                           discordAuthorizedBy=ACTOR, discordLinkedUserId=USER, discordWebhookChannelId=self.channel)
            channel['discordDestinations'] = []
            auth.register_destination(state, channel, {
                'senderKind': 'webhook', 'credentialKind': 'webhook', 'webhookId': self.hook, 'applicationId': APP,
                'linkedUserId': USER, 'guildId': self.guild, 'channelId': self.channel, 'guildName': self.guild,
                'channelName': self.channel, 'kind': 'webhook'}, self.generation, ACTOR, self.now)
        else:
            channel.update(discordConnectionKind='installation', qualification='server_verified', evidenceSource='live_provider')
            channel['discordDestinations'] = []
            auth.register_destination(state, channel, {
                'applicationId': APP, 'botUserId': BOT, 'linkedUserId': USER, 'guildId': self.guild,
                'channelId': self.channel, 'guildName': self.guild, 'channelName': self.channel, 'kind': 'text'},
                self.generation, ACTOR, self.now)
        variant['text'] = text
        if self.name is not None:
            channel['discordSenderName'] = self.name
        self.engine, self.state, self.channel_record, self.variant = engine, state, channel, variant
        return self

    def review(self, *, at=None):
        at = self.now + 300 if at is None else at
        payload = {'variantId': self.variant['id'], 'channelId': self.channel_record['id'],
                   'destinationId': auth.destination_id(self.workspace, self.connection, self.guild, self.channel),
                   'localTime': datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M'),
                   'timeZone': 'UTC', 'acknowledgedWarnings': []}
        with self.patched():
            self.engine.apply_phase2(None, self.state, 'review', payload, {'user_id': ACTOR})
        return self.state['phase2']['reviews'][-1]

    def approve(self, entry=None):
        entry = entry or self.review()
        with self.patched():
            self.engine.apply_phase2(None, self.state, 'approve', {'reviewId': entry['id'], 'digest': entry['digest'],
                                                                  'confirmed': True}, {'user_id': ACTOR})
        return next(j for j in self.state['phase2']['jobs'] if j['id'] == entry['jobId'])

    # -- credentials ------------------------------------------------------------------------------------------------
    def session(self):
        if self.kind == 'webhook':
            return {'v': 2, 'kind': 'webhook', 'applicationId': APP, 'webhookId': self.hook, 'secret': self.hook_credential,
                    'guild': self.guild, 'channel': self.channel, 'user': USER, 'memberId': ACTOR,
                    'workspaceId': self.workspace, 'destinationAuthorized': True}
        return {'v': 2, 'guild': self.guild, 'user': USER, 'channel': self.channel, 'applicationId': APP, 'botUserId': BOT}

    def grant(self):
        scopes = ['identify', 'webhook.incoming'] if self.kind == 'webhook' else ['bot', 'identify']
        return {'provider': 'discord', 'accessToken': json.dumps(self.session()), 'scopes': scopes,
                'authorizationGeneration': self.generation}


class _Stack:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


class World:
    """Tenants plus the provider and social facade that serve them all, as one process of the hosted app would."""
    def __init__(self, tenants, wire=None):
        self.tenants = {t.workspace: t for t in tenants}
        self.wire = wire or Hooks(tenants)
        self.provider = DiscordProvider(APP, 'synthetic-oauth-client', 'synthetic-bot', 'https://rafii.example.invalid',
                                        transport=self.wire, production_reviewed=True)
        self.provider.authorization_v2_enabled = self.provider.connections_v2_enabled = True
        self.provider.webhook_v1_enabled = True
        self.generations = {}
        oauth = SimpleNamespace(discord_grant_for_worker=self._grant)
        self.social = HostedSocial(oauth, {'discord': self.provider})

    def _grant(self, workspace, connection, *, cur=None):
        tenant = self.tenants.get(workspace)
        if tenant is None or connection != tenant.connection:
            raise P.AlphaError('Synthetic grant unavailable.', 409)
        return copy.deepcopy(tenant.grant())

    def dispatch(self, job, *, lease='synthetic-lease'):
        """The worker's own two calls: preflight (outside locks), then the authorized create with the sealed intent."""
        manifest = job['manifest']
        prepared = self.social.prepare_discord_dispatch(manifest)
        prepared['intent'] = {'id': lease, 'manifestDigest': auth.digest(manifest), 'publicationId': job['id']}
        return self.social.submit_discord_authorized(manifest, prepared)


class Hooks:
    """Discord for many synthetic webhooks and servers. Thread safe; every execute request is recorded whole."""
    def __init__(self, tenants, *, reject_usernames=True):
        self.tenants = {t.guild: t for t in tenants}
        self.by_hook = {t.hook: t for t in tenants if t.kind == 'webhook'}
        self.lock = threading.Lock()
        self.calls, self.posts = [], []
        self.messages, self.deleted, self.sequence = {}, set(), 900000000000000000
        self.reject_usernames = reject_usernames
        self.rewrite_username = None   # callable(str) -> str, to model a provider that sanitizes the name
        self.fail_post = None          # callable(tenant, body) -> response dict, raise, or None
        self.guild_config = {}         # guild -> GuildConfig for the nickname routes (otherwise the plain preflight answers)
        self.before_patch = self.after_read = None   # one-shot hooks: callable() run before a nickname PATCH / after a read
        self.lose_patch_response = False             # one-shot: Discord applies the nickname PATCH, the response never arrives
        self.rate_headers = None                     # callable(method, path) -> headers, for runs through the real coordinator
        self.bot_id = BOT                            # what GET /users/@me says the bot's id is
        self.webhook_name = DEFAULT_HOOK_NAME        # what GET /webhooks/{id}/{token} says the webhook's own name is

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        response = self._route(method, url, headers, form, body, data)
        if self.rate_headers is not None and not response.get('headers'):
            response = {**response, 'headers': self.rate_headers(method, urlsplit(url).path.removeprefix('/api/v10'))}
        return response

    @staticmethod
    def bucket_headers(method, path):
        """Plausible rate-limit headers: one bucket per route template, generous limits."""
        template = method + re.sub(r'[0-9]{5,}', '{id}', path.split('?')[0])
        return {'x-ratelimit-bucket': hashlib.sha256(template.encode()).hexdigest()[:24], 'x-ratelimit-limit': '100',
                'x-ratelimit-remaining': '90', 'x-ratelimit-reset-after': '2'}

    def _route(self, method, url, headers, form, body, data):
        path = urlsplit(url).path.removeprefix('/api/v10')
        parts = path.strip('/').split('/')
        with self.lock:
            self.calls.append((method, path))
        if path == '/oauth2/applications/@me':
            return {'status': 200, 'body': {'id': APP}, 'headers': {}}
        if path == '/users/@me':
            return {'status': 200, 'body': {'id': self.bot_id, 'bot': True}, 'headers': {}}
        if parts[0] == 'guilds' and parts[1] in self.guild_config:
            return self._configured_guild(method, parts, body, headers)
        if parts[0] == 'guilds' and parts[1] in self.tenants:
            guild = parts[1]
            if len(parts) == 2:
                return self._ok({'id': guild, 'name': 'Synthetic server', 'owner_id': '1000001',
                                 'roles': [{'id': guild, 'permissions': str(DiscordProvider.PERMISSIONS | DiscordProvider.MANAGE_GUILD),
                                            'position': 0}]})
            if len(parts) == 4 and parts[2] == 'members' and parts[3] in (BOT, USER):
                return self._ok({'user': {'id': parts[3]}, 'roles': [], 'pending': False, 'communication_disabled_until': None})
            if len(parts) == 3 and parts[2] == 'channels':
                return self._ok([{'id': self.tenants[guild].channel, 'guild_id': guild, 'name': 'synthetic', 'type': 0,
                                  'permission_overwrites': []}])
        if parts[0] == 'webhooks' and len(parts) >= 3:
            return self._webhook(method, parts, body)
        if method == 'POST' and parts[0] == 'channels' and parts[-1] == 'messages':
            return self._bot_create(parts, body)
        raise AssertionError('Unexpected synthetic route: ' + method + ' ' + path)

    @staticmethod
    def _ok(value):
        return {'status': 200, 'body': value, 'headers': {}}

    def _configured_guild(self, method, parts, body, headers=None):
        config = self.guild_config[parts[1]]
        guild = parts[1]
        if method == 'PATCH' and parts[2:] == ['members', '@me']:
            if self.before_patch is not None:
                action, self.before_patch = self.before_patch, None
                action()
            config.patches.append(copy.deepcopy(body))
            config.patch_headers.append(dict(headers or {}))
            if config.reject_patch:
                return {'status': 403, 'body': {'message': 'Missing Permissions', 'code': 50013}, 'headers': {}}
            config.nick = body['nick']
            if self.lose_patch_response:
                self.lose_patch_response = False
                raise TimeoutError('synthetic lost response')
            if config.patch_response is not None:
                return config.patch_response(copy.deepcopy(body))
            return self._ok({'user': {'id': BOT, 'username': 'Rafii'}, 'nick': config.nick, 'roles': []})
        if method != 'GET':
            raise AssertionError('Unexpected synthetic guild route')
        if len(parts) == 2:
            answer = self._ok({'id': config.report_guild_id or guild, 'name': 'Synthetic server', 'owner_id': config.owner_id, 'roles': [
                {'id': guild, 'permissions': str(DiscordProvider.PERMISSIONS), 'position': 0},
                {'id': '11223344', 'permissions': str(config.user_permissions), 'position': config.user_position},
                {'id': '22334455', 'permissions': str(config.bot_permissions), 'position': config.bot_position}]})
        elif len(parts) == 4 and parts[2] == 'members' and parts[3] == USER:
            if config.user_member_missing:
                return {'status': 404, 'body': {'message': 'Unknown Member', 'code': 10007}, 'headers': {}}
            answer = self._ok({'user': {'id': USER}, 'roles': ['11223344'], 'pending': False, 'communication_disabled_until': None})
        elif len(parts) == 4 and parts[2] == 'members' and parts[3] == BOT:
            if config.bot_member_missing:
                return {'status': 404, 'body': {'message': 'Unknown Member', 'code': 10007}, 'headers': {}}
            named = {'global_name': config.bot_global_name} if config.bot_global_name else {}
            answer = self._ok({'user': {'id': config.readback_user_id if config.readback_user_id and config.patches else BOT,
                                        'username': 'Rafii', **named},
                               'roles': ['22334455'], 'nick': config.nick, 'pending': False, 'communication_disabled_until': None})
        elif len(parts) == 3 and parts[2] == 'channels' and guild in self.tenants:
            answer = self._ok([{'id': self.tenants[guild].channel, 'guild_id': guild, 'name': 'synthetic', 'type': 0,
                                'permission_overwrites': []}])
        else:
            raise AssertionError('Unexpected synthetic guild route: ' + '/'.join(parts))
        if self.after_read is not None:
            action, self.after_read = self.after_read, None
            action()
        return answer

    def _webhook(self, method, parts, body):
        hook, credential = parts[1], parts[2]
        tenant = self.by_hook.get(hook)
        if tenant is None or credential != tenant.hook_credential or hook in self.deleted:
            return {'status': 404, 'body': {'message': 'Unknown Webhook', 'code': 10015}, 'headers': {}}
        if method == 'GET' and len(parts) == 3:
            return self._ok({'id': hook, 'application_id': APP, 'guild_id': tenant.guild, 'channel_id': tenant.channel,
                             'type': 1, 'name': self.webhook_name})
        if method == 'GET' and len(parts) == 5 and parts[3] == 'messages':
            message = self.messages.get(parts[4])
            return self._ok(copy.deepcopy(message)) if message else {'status': 404, 'body': {}, 'headers': {}}
        if method == 'POST' and len(parts) == 3:
            return self._execute(tenant, body)
        raise AssertionError('Unexpected synthetic webhook route')

    def _execute(self, tenant, body):
        record = {'workspace': tenant.workspace, 'hook': tenant.hook, 'guild': tenant.guild, 'channel': tenant.channel,
                  'body': copy.deepcopy(body)}
        with self.lock:
            self.posts.append(record)
        if self.fail_post is not None:
            answer = self.fail_post(tenant, body)
            if answer is not None:
                return answer
        username = (body or {}).get('username')
        if username is not None and self.reject_usernames and any(w in username.casefold() for w in ('clyde', 'discord')):
            return {'status': 400, 'body': {'message': 'Invalid Form Body', 'code': 50035}, 'headers': {}}
        if username is not None and self.rewrite_username is not None:
            username = self.rewrite_username(username)
        with self.lock:
            self.sequence += 1
            message_id = str(self.sequence)
            message = {'id': message_id, 'channel_id': tenant.channel, 'webhook_id': tenant.hook,
                       'author': {'id': tenant.hook, 'bot': True, 'username': username if username is not None else DEFAULT_HOOK_NAME},
                       'content': (body or {}).get('content'), 'mentions': [], 'mention_roles': [], 'mention_everyone': False,
                       'attachments': [], 'embeds': []}
            self.messages[message_id] = message
        return self._ok(copy.deepcopy(message))

    def _bot_create(self, parts, body):
        tenant = next((t for t in self.tenants.values() if t.channel == parts[1]), None)
        record = {'workspace': tenant.workspace if tenant else None, 'bot_channel': parts[1], 'body': copy.deepcopy(body)}
        with self.lock:
            self.posts.append(record)
            self.sequence += 1
            message_id = str(self.sequence)
            message = {'id': message_id, 'channel_id': parts[1], 'content': (body or {}).get('content'),
                       'author': {'id': BOT, 'bot': True}, 'mention_everyone': False, 'mentions': [], 'mention_roles': [],
                       'attachments': []}
            self.messages[message_id] = message
        return self._ok(copy.deepcopy(message))


class GuildConfig:
    """What the nickname routes read of one server, and the nickname writes it received."""
    def __init__(self):
        self.user_permissions = (1 << 27) | (1 << 5)    # Manage Nicknames and Manage Server
        self.bot_permissions = (1 << 26) | (1 << 5)     # Change Nickname and Manage Server
        self.user_position, self.bot_position = 5, 2
        self.owner_id = '1000001'
        self.nick = None
        self.patches, self.patch_headers = [], []
        self.reject_patch = False
        self.patch_response = None        # callable(body) -> response, to answer a nickname PATCH differently from Discord
        self.report_guild_id = None       # the id the server read answers with, when it should be another server
        self.user_member_missing = self.bot_member_missing = False
        self.bot_global_name = None       # the bot user's global display name, when it has no nickname
        self.readback_user_id = None      # the user id the member read answers with once a PATCH happened


class FakeLimiter:
    """The slice of the shared request coordinator that a nickname write touches, with every outcome scriptable.

    It keeps the real coordinator's contract wherever the nickname flow depends on it: one Permit per admission, the states
    reserved -> sent -> observed / uncertain / blocked, `reconcile_nickname` only for the same bot credential and only after the
    admission has aged out. The real coordinator, on PostgreSQL, is exercised in test_discord_sender_name_postgres.py."""
    application_key = 'a' * 64

    def __init__(self, clock):
        self.clock, self.policy = clock, SimpleNamespace(read_attempts=1)
        self.admissions, self.calls, self.reconciled = {}, [], []
        # exceptions raised for the nickname PATCH only
        self.reserve_error = self.consume_error = None
        self.after_consume = None      # callable() run right after an admission turned `sent`

    # -- admission ------------------------------------------------------------------------------------------------------
    def _admit(self, method, path, identity, state):
        from postriff_phase2.discord.rate_limits import Permit, _digest
        permit = Permit(str(uuid.uuid4()), self.application_key, method, _digest(path), identity, None, self.clock() + 30)
        self.admissions[permit.id] = {'permit': permit, 'state': state, 'reserved': self.clock(), 'method': method, 'path': path}
        return permit

    def reserve_read(self, method, path, *, identity):
        self.calls.append(('reserve_read', path))
        return self._admit(method, path, identity, 'sent')

    def reserve(self, method, path, *, identity, binding=None, valid_until=None):
        self.calls.append(('reserve', path))
        if method == 'PATCH' and self.reserve_error is not None:
            raise self.reserve_error
        return self._admit(method, path, identity, 'reserved')

    def consume(self, permit, method, path, *, binding=None, intent_id=None, authorize=None):
        self.calls.append(('consume', path))
        if method == 'PATCH' and self.consume_error is not None:
            raise self.consume_error
        self.admissions[permit.id]['state'] = 'sent'
        if method == 'PATCH' and self.after_consume is not None:
            action, self.after_consume = self.after_consume, None
            action()

    def observe(self, permit, response, *, transport_failure=False):
        self.calls.append(('observe', permit.method, response.get('status')))
        self.admissions[permit.id]['state'] = 'uncertain' if transport_failure else 'observed'
        return {'status': response.get('status'), 'retryAfterSeconds': 0, 'retryHintMalformed': False}

    def note_transport_failure(self, permit):
        return self.observe(permit, {'status': 503, 'headers': {}}, transport_failure=True)

    def abandon_unsent_read(self, permit):
        self.admissions[permit.id]['state'] = 'blocked'

    def abandon_unsent_nickname(self, permit):
        from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable
        row = self.admissions[permit.id]
        if row['state'] in ('observed', 'blocked'):
            return
        if row['state'] != 'sent':
            raise RateCoordinatorUnavailable()
        row['state'] = 'blocked'

    # -- reconciliation -------------------------------------------------------------------------------------------------
    def _reconcile(self, row, guild_id):
        from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, _digest
        if (row['method'] != 'PATCH' or row['permit'].path_key != _digest(f'/guilds/{guild_id}/members/@me')
                or row['state'] in ('reserved', 'sent', 'uncertain') and
                (row['reserved'] + 120 > self.clock() or row['permit'].expires_at > self.clock())):
            raise RateCoordinatorUnavailable()
        if row['state'] in ('reserved', 'sent', 'uncertain'):
            row['state'] = 'observed'

    def reconcile_nickname(self, cur, permit, guild_id):
        """The Permit-based method of the coordinator as shipped: it needs the bot credential's own identity."""
        from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable
        row = self.admissions.get(permit.id)
        if row is None or row['permit'].identity != permit.identity:
            raise RateCoordinatorUnavailable()
        self.reconciled.append(('permit', permit.id))
        self._reconcile(row, guild_id)

    def state_of(self, admission_id):
        return self.admissions[admission_id]['state']

    def patch_admissions(self):
        return [row for row in self.admissions.values() if row['method'] == 'PATCH']


class FakeLimiterWithIds(FakeLimiter):
    """What the coordinator offers once it can retire a nickname admission by id (docs/sender-name/REQUESTS-TO-RATE-LIMITER.md R2)."""
    def reconcile_nickname_by_id(self, cur, admission_id, guild_id):
        from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable
        row = self.admissions.get(admission_id)
        if row is None:
            raise RateCoordinatorUnavailable()
        self.reconciled.append(('id', admission_id))
        self._reconcile(row, guild_id)
