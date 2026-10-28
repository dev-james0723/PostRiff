"""The sender-name settings routes over an in-memory store of SEVERAL workspaces, members, sessions and credentials.

The code under test is the real DiscordConnections / SenderNames code, including its credential reads, custody checks,
membership checks, throttles and audit writes: only the database is replaced by a cursor that answers the exact
statements those code paths issue (and refuses any other). Transactions roll back when the code raises, as in
production. The real-PostgreSQL equivalents are in test_discord_sender_name_postgres.py.
"""
import copy
import json
import math
import secrets
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import discord_sender_name_fixture as F
from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.permissions import Membership, require
from test_discord_oauth_lifecycle import service

APP, BOT, USER, NOW = F.APP, F.BOT, F.USER, F.NOW


class Member:
    def __init__(self, user, role, **flags):
        self.user, self.role, self.flags = user, role, flags
        self.status, self.deleted = 'active', False


class Workspace:
    def __init__(self, workspace_id):
        self.id = workspace_id
        self.state = initial_state(workspace_id)
        self.state['phase2'] = {'channels': [], 'assets': [], 'reviews': [], 'jobs': [], 'discordIdentityLinks': []}
        self.members = {}


class Cursor:
    """Answers exactly the statements the sender-name code issues. Writes stay pending until the block exits cleanly."""
    def __init__(self, world, workspace):
        self.world, self.workspace, self.result = world, workspace, None
        self.states, self.audit, self.throttle, self.revoked = {}, [], {}, []

    def execute(self, sql, params=()):
        world, text = self.world, ' '.join(sql.split())
        self.result = None
        if text.startswith('SELECT access_ciphertext,key_id'):
            workspace, connection = params
            credential = world.credentials.get((workspace, connection))
            self.result = None if credential is None or credential['revoked'] else credential['row']
        elif text.startswith('SELECT state FROM public.pr_workspaces WHERE id='):
            self.result = (json.dumps(world.workspaces[params[0]].state),)
        elif text.startswith('SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships'):
            member = world.active(params[0], params[1])
            self.result = None if member is None else (member.role, member.flags.get('can_publish', False),
                member.flags.get('can_reply', False), member.flags.get('can_moderate', False),
                member.flags.get('can_manage_connections', False))
        elif text.startswith('SELECT m.role,m.can_manage_connections FROM public.pr_memberships'):
            member = world.active(params[0], params[1])
            self.result = None if member is None else (member.role, member.flags.get('can_manage_connections', False))
        elif text.startswith('UPDATE public.pr_encrypted_credentials SET revoked_at=now()'):
            self.revoked.append(tuple(params))
        elif text.startswith('INSERT INTO public.pr_channel_capabilities'):
            pass
        elif text.startswith('SELECT pg_advisory_xact_lock('):
            world.locks.append(params[0])
        elif text.startswith('UPDATE public.pr_workspaces SET state='):
            self.states[params[1]] = json.loads(params[0])
        elif text.startswith('INSERT INTO public.pr_audit_events'):
            self.audit.append({'workspace': params[0], 'actor': params[1], 'kind': params[2], 'subject': params[3],
                               'meta': json.loads(params[4])})
        elif text.startswith('INSERT INTO public.pr_auth_throttle'):
            bucket, window = params[0], params[1]
            start, count = self.throttle.get(bucket) or world.throttles.get(bucket) or (world.now, 0)
            start, count = (world.now, 1) if start < world.now - window else (start, count + 1)
            self.throttle[bucket] = (start, count)
            self.result = (count,)
        elif text.startswith('SELECT greatest(1, ceil(extract(epoch FROM (window_start + make_interval(secs=>%s) - now())))) FROM public.pr_auth_throttle WHERE bucket='):
            window, bucket = params
            entry = self.throttle.get(bucket) or world.throttles.get(bucket)
            self.result = None if entry is None else (max(1, math.ceil(entry[0] + window - world.now)),)
        elif text.startswith("SELECT count(*) FROM public.pr_encrypted_credentials WHERE provider='discord' AND provider_account_id="):
            guild, workspace, connection = params
            self.result = (sum(1 for (w, c), cred in world.credentials.items()
                               if cred['row'][6] == guild and 'bot' in cred['row'][5] and not cred['revoked']
                               and (w, c) != (workspace, connection)),)
        else:
            raise AssertionError('Unexpected SQL in the settings world: ' + text[:140])

    def fetchone(self):
        return self.result

    def commit(self):
        for workspace, state in self.states.items():
            self.world.workspaces[workspace].state = state
        self.world.audit.extend(self.audit)
        for key in self.revoked:
            self.world.credentials[tuple(key)]['revoked'] = True
        self.world.throttles.update(self.throttle)


class Settings:
    def __init__(self):
        self.s, _ = service()
        self.now = NOW
        self.s.oauth.clock = lambda: self.now
        self.hooks = F.Hooks([])
        self.s.adapter.transport = self.hooks
        self.s.adapter.webhook_v1_enabled = True
        self.workspaces, self.credentials, self.tokens = {}, {}, {}
        self.stale, self.audit, self.throttles, self.locks = set(), [], {}, []
        self.s.local = self._local
        self.s._fresh_identity = Mock()      # identity refresh has its own suite
        self.s.oauth.repository = SimpleNamespace(assert_fresh=self._assert_fresh)
        self.s.oauth.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda *_: None))

    # -- the store ----------------------------------------------------------------------------------------------------
    def active(self, workspace, user):
        member = self.workspaces[workspace].members.get(user)
        return member if member and member.status == 'active' and not member.deleted else None

    @contextmanager
    def _local(self, workspace, token):
        if token is None:
            yield Cursor(self, workspace), copy.deepcopy(self.workspaces[workspace].state), None
            return
        principal = self.tokens.get(token)
        if principal is None:
            raise AlphaError('This session expired or was revoked. Sign in again.', 401)
        member = self.active(workspace, principal) if workspace in self.workspaces else None
        if member is None:
            raise AlphaError('Workspace unavailable.', 403)
        state = copy.deepcopy(self.workspaces[workspace].state)
        if state.get('accountDeletion'):
            raise AlphaError('Account deletion is pending. Only deletion can continue.', 409, code='account_deletion_pending')
        if state.get('accountBlock'):
            raise AlphaError('This account is blocked.', 403, code='account_blocked')
        require(Membership.from_row(member.role, **member.flags), 'manage_connections')
        cursor = Cursor(self, workspace)
        yield cursor, state, principal
        cursor.commit()

    def _assert_fresh(self, token, principal):
        if token in self.stale:
            raise AlphaError('Sign in again to confirm this sensitive action.', 403, code='step_up_required')

    def snapshot(self):
        """Everything a denial must leave alone: every workspace's state, the audit log, the Discord side."""
        return json.dumps({'states': {w.id: w.state for w in self.workspaces.values()}, 'audit': self.audit,
                           'calls': self.hooks.calls, 'posts': self.hooks.posts,
                           'patches': {g: c.patches for g, c in self.hooks.guild_config.items()},
                           'credentials': {f'{k[0]}/{k[1]}': [v['row'][4], v['revoked']] for k, v in self.credentials.items()}},
                          sort_keys=True, default=str)

    # -- building ------------------------------------------------------------------------------------------------------
    def workspace(self, number):
        workspace_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-settings-workspace-{number}.example.invalid'))
        self.workspaces[workspace_id] = Workspace(workspace_id)
        return workspace_id

    def user(self, number):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-settings-user-{number}.example.invalid'))

    def member(self, workspace, user, role='owner', **flags):
        """Add a member and return a fresh session for them (generated at run time)."""
        self.workspaces[workspace].members[user] = Member(user, role, **flags)
        return self.session(user)

    def session(self, user):
        value = 'synthetic-' + secrets.token_urlsafe(24)
        self.tokens[value] = user
        return value

    def _store(self, workspace, connection, envelope, scopes, account, generation):
        ciphertext, key_id = self.s.oauth.vault.encrypt(json.dumps(envelope))
        self.credentials[(workspace, connection)] = {
            'revoked': False, 'envelope': envelope,
            'row': (ciphertext, key_id, None, NOW + 3600.0, generation, list(scopes), account)}

    def webhook(self, workspace, number, authorizer, *, name=None, guild=None):
        """One webhook connection authorized by `authorizer`, with its own server, channel and webhook."""
        ids = SimpleNamespace(connection=f'discord-webhook-{number:04d}-{workspace[:8]}', hook=str(8300000 + number),
                              guild=guild or str(6300000 + number), channel=str(7300000 + number),
                              generation=str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-settings-gen-{workspace}-{number}.example.invalid')),
                              credential=secrets.token_urlsafe(32))
        scopes = ['identify', 'webhook.incoming']
        channel = {'id': ids.connection, 'platform': 'Discord', 'account': 'Rafii webhook', 'accountType': 'webhook',
                   'providerAccountId': ids.hook, 'scopes': scopes, 'configured': True, 'capabilityVerified': True,
                   'enabledPermissionGroups': ['identity', 'publish'], 'discordConnectionKind': 'webhook',
                   'discordAuthorizedBy': authorizer, 'discordLinkedUserId': USER, 'discordWebhookChannelId': ids.channel,
                   'discordAuthorizationGeneration': ids.generation, 'discordDestinations': [], 'revoked': False}
        if name is not None:
            channel['discordSenderName'] = name
        self.workspaces[workspace].state['phase2']['channels'].append(channel)
        self._store(workspace, ids.connection, {
            'v': 2, 'kind': 'webhook', 'workspaceId': workspace, 'memberId': authorizer, 'applicationId': APP,
            'webhookId': ids.hook, 'secret': ids.credential, 'guild': ids.guild, 'channel': ids.channel, 'user': USER,
            'connectionId': ids.connection}, scopes, ids.hook, ids.generation)
        self.hooks.by_hook[ids.hook] = SimpleNamespace(hook=ids.hook, hook_credential=ids.credential, guild=ids.guild,
                                                       channel=ids.channel, workspace=workspace, name=name, kind='webhook')
        self.hooks.tenants[ids.guild] = self.hooks.by_hook[ids.hook]
        return ids

    def installation(self, workspace, number, authorizer, *, guild):
        """A bot installation of `guild` authorized by `authorizer` through a linked Discord identity."""
        identity = f'discord-identity-{number:04d}-{workspace[:8]}'
        identity_generation = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-settings-ident-{workspace}-{number}.example.invalid'))
        ids = SimpleNamespace(connection=f'discord-install-{number:04d}-{workspace[:8]}', guild=guild, identity=identity,
                              generation=str(uuid.uuid5(uuid.NAMESPACE_DNS, f'sn-settings-gen-{workspace}-i{number}.example.invalid')))
        scopes = ['bot', 'identify']
        state = self.workspaces[workspace].state['phase2']
        state['discordIdentityLinks'].append({'id': identity, 'workspaceId': workspace, 'applicationId': APP, 'authorizedBy': authorizer,
                                              'userId': USER, 'status': 'linked', 'authorizationGeneration': identity_generation})
        state['channels'].append({'id': ids.connection, 'platform': 'Discord', 'account': 'Synthetic server', 'accountType': 'server',
                                  'providerAccountId': guild, 'scopes': scopes, 'configured': True, 'capabilityVerified': True,
                                  'enabledPermissionGroups': ['identity', 'publish'], 'discordConnectionKind': 'installation',
                                  'discordIdentityConnectionId': identity, 'discordAuthorizationGeneration': ids.generation,
                                  'discordDestinations': [], 'revoked': False})
        self._store(workspace, identity, {'v': 1, 'kind': 'identity', 'applicationId': APP, 'memberId': authorizer,
                                          'user': USER, 'at': 'synthetic-' + secrets.token_urlsafe(12)},
                    ['identify', 'guilds'], USER, identity_generation)
        self._store(workspace, ids.connection, {
            'v': 2, 'kind': 'installation', 'workspaceId': workspace, 'memberId': authorizer, 'applicationId': APP,
            'botUserId': BOT, 'user': USER, 'guild': guild, 'channel': None, 'identityConnectionId': identity,
            'identityGeneration': identity_generation, 'connectionId': ids.connection}, scopes, guild, ids.generation)
        self.hooks.guild_config.setdefault(guild, F.GuildConfig())
        return ids

    def rewrite_envelope(self, workspace, connection, **changes):
        """Change fields of a stored credential envelope (re-encrypted), as a corrupted or foreign record would look."""
        entry = self.credentials[(workspace, connection)]
        row = entry['row']
        self._store(workspace, connection, {**entry['envelope'], **changes}, row[5], row[6], row[4])

    def set_row(self, workspace, connection, index, value):
        """Replace one column of the stored credential row (3 expiry, 4 generation, 5 scopes, 6 account)."""
        entry = self.credentials[(workspace, connection)]
        entry['row'] = entry['row'][:index] + (value,) + entry['row'][index + 1:]

    def use_limiter(self, *, by_id=False):
        """Route the adapter's requests through a scriptable stand-in for the shared request coordinator."""
        limiter = (F.FakeLimiterWithIds if by_id else F.FakeLimiter)(lambda: self.now)
        self.s.adapter.rate_v1_enabled, self.s.adapter.rate_limiter = True, limiter
        return limiter

    def revoke(self, workspace, connection):
        """What a disconnect does to the credential row and the card."""
        self.credentials[(workspace, connection)]['revoked'] = True
        for channel in self.workspaces[workspace].state['phase2']['channels']:
            if channel['id'] == connection:
                channel['revoked'] = True

    def channel(self, workspace, connection):
        return next(c for c in self.workspaces[workspace].state['phase2']['channels'] if c['id'] == connection)

    # -- calls ---------------------------------------------------------------------------------------------------------
    def get(self, workspace, token, connection):
        return self.s.sender_profile(workspace, token, connection)

    def post(self, workspace, token, connection, body):
        return self.s.set_sender_name(workspace, token, connection, body)

    def attempt(self, call, *args):
        """(status, code, message) of a refusal, or ('ok', None, result)."""
        try:
            return ('ok', None, call(*args))
        except AlphaError as error:
            return (error.status, error.code, str(error), getattr(error, 'public_fields', None))
