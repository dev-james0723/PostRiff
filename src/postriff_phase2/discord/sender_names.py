"""Connection-owned webhook names and explicitly shared, per-guild bot nicknames.

No personal-user writes or global bot identity changes. Provider IO is outside
workspace transactions; custody is checked again at the transport boundary.
"""
import copy
import unicodedata
import uuid

from postriff_alpha.domain import AlphaError
from .authorization import digest, snowflake


def fail(message='Discord sender settings changed. Reload and review the name again.', status=409):
    raise AlphaError(message, status, code='discord_sender_name_required')


def validate_name(name, kind):
    limit = 80 if kind == 'webhook' else 32
    if (not isinstance(name, str) or not name.strip() or name != name.strip()
            or len(name) > limit or unicodedata.normalize('NFC', name) != name
            or any(unicodedata.category(c).startswith('C') or c in '\u2028\u2029' for c in name)
            or kind == 'webhook' and any(word in name.casefold() for word in ('discord', 'clyde'))):
        fail(f'Choose a name of 1–{limit} characters without surrounding spaces, control characters or reserved webhook names.', 400)
    return name


class SenderNames:
    def __init__(self, connections, workspace, token, connection):
        if token is None:
            fail('Sign in to manage Discord sender names.', 401)
        self.s, self.workspace, self.token, self.connection = connections, workspace, token, connection

    def custody(self, cur, state, actor, *, fresh=True):
        from .oauth import identity_record
        if (not actor or state.get('workspace', {}).get('id') != self.workspace
                or state.get('accountDeletion') or state.get('accountBlock')):
            fail('This workspace cannot change Discord sender settings.', 403)
        channel = next((c for c in state.get('phase2', {}).get('channels', [])
                        if c.get('id') == self.connection and c.get('platform') == 'Discord'), None)
        if not channel or channel.get('revoked'):
            fail('This Discord connection is unavailable.', 404)
        row, envelope = self.s.read_credential(cur, self.workspace, self.connection)
        kind = envelope.get('kind')
        required = {'identify', 'webhook.incoming' if kind == 'webhook' else 'bot'}
        if (kind not in ('webhook', 'installation') or channel.get('discordConnectionKind') != kind
                or envelope.get('applicationId') != self.s.adapter.client_id
                or not row[4] or row[4] != channel.get('discordAuthorizationGeneration')
                or not required.issubset(row[5] or []) or set(row[5]) != set(channel.get('scopes') or [])
                or any(not snowflake(envelope.get(k)) for k in ('guild', 'user'))):
            fail('Reconnect this Discord connection before changing its sender name.')
        if kind == 'webhook':
            if (envelope.get('workspaceId') != self.workspace or envelope.get('memberId') != actor
                    or envelope.get('connectionId') != self.connection
                    or channel.get('discordAuthorizedBy') != actor
                    or channel.get('discordLinkedUserId') != envelope['user']
                    or envelope.get('webhookId') != row[6] or row[6] != channel.get('providerAccountId')
                    or envelope.get('channel') != channel.get('discordWebhookChannelId')):
                fail('Only this webhook’s authorizing member can change its sender name.', 403)
            self.s.validate_webhook(cur, self.workspace, envelope)
            identity = None
        else:
            identity = identity_record(state, envelope.get('identityConnectionId'), actor)
            if (envelope['guild'] != row[6] or row[6] != channel.get('providerAccountId')
                    or channel.get('discordIdentityConnectionId') != identity['id']
                    or identity.get('authorizationGeneration') != envelope.get('identityGeneration')
                    or identity.get('userId') != envelope['user'] or identity.get('status') != 'linked'
                    or not snowflake(envelope.get('botUserId'))):
                fail('The Discord installation’s authorizing identity changed.')
            if fresh:
                self.s.validate_installation(cur, self.workspace, envelope)
        fields = ('id', 'platform', 'providerAccountId', 'discordConnectionKind', 'scopes', 'revoked',
                  'discordIdentityConnectionId', 'discordAuthorizationGeneration', 'discordAuthorizedBy',
                  'discordLinkedUserId', 'discordWebhookChannelId', 'defaultDestinationId', 'discordDestinations',
                  'discordSenderName', 'discordSenderRevision', 'discordSenderEdit', 'enabledPermissionGroups')
        stamp = digest({'workspace': self.workspace, 'actor': actor,
                        'channel': {k: channel.get(k) for k in fields},
                        'credential': [row[0], row[4], envelope],
                        'identity': {k: identity.get(k) for k in ('id', 'authorizedBy', 'userId', 'status', 'authorizationGeneration')} if identity else None})
        return channel, copy.deepcopy(envelope), stamp

    def guard(self, stamp):
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            _, _, current = self.custody(cur, state, actor)
            if current != stamp:
                fail()
        return True

    def observe(self, *, reconcile=False):
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, envelope, _ = self.custody(cur, state, actor, fresh=False)
            claim = copy.deepcopy(channel.get('discordSenderEdit'))
            if claim and (not reconcile or not isinstance(claim, dict)
                    or type(claim.get('expiresAt')) not in (int, float) or self.s.oauth.clock() < claim['expiresAt']):
                raise AlphaError('A sender-name change is pending. Wait two minutes, then reload to verify it.',
                                 409, code='discord_sender_edit_pending')
        if envelope['kind'] == 'webhook':
            self.s.reverify_webhook(self.workspace, self.connection, token=self.token)
        else:
            self.s.reverify_installation(self.workspace, self.connection, token=self.token)
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, envelope, stamp = self.custody(cur, state, actor)
            if channel.get('discordSenderEdit') != claim:
                fail()
            saved = channel.get('discordSenderName')
        adapter = self.s.adapter
        read = lambda: self.guard(stamp)
        if envelope['kind'] == 'webhook':
            from .webhooks import verify_resource
            resource = verify_resource(adapter, envelope, read_authorize=read)
            name = saved if saved is not None else resource.get('senderName')
            kind, scope = 'webhook', 'connection'
        else:
            bot = adapter._bot_identity(read_authorize=read)
            if bot != envelope['botUserId']:
                fail('Discord returned a different bot.')
            guild = adapter._json(adapter._bot('GET', '/guilds/' + envelope['guild'], read_authorize=read), dict)
            if guild.get('id') != envelope['guild']:
                fail('Discord returned a different server.')
            roles = adapter._member_roles(envelope['guild'], envelope['user'], read_authorize=read)
            bot_roles = adapter._member_roles(envelope['guild'], bot, read_authorize=read)
            if (roles is None or bot_roles is None
                    or not adapter._permissions(guild, roles, envelope['user']) & (1 << 27)
                    or not adapter._permissions(guild, bot_roles, bot) & (1 << 26)):
                fail('The authorizer needs Manage Nicknames and the bot needs Change Nickname in this server.', 403)
            member = adapter._json(adapter._bot('GET', f'/guilds/{envelope["guild"]}/members/{bot}', read_authorize=read), dict)
            if (member.get('user') or {}).get('id') != bot:
                fail('Discord did not confirm this bot member.')
            name = member.get('nick') or (member.get('user') or {}).get('global_name') or (member.get('user') or {}).get('username')
            kind, scope = 'bot', 'server'
        if not isinstance(name, str) or not name or len(name) > 80:
            fail('Discord did not return a valid current sender name.')
        self.guard(stamp)
        if claim:
            # Explicit GET after the bounded write deadline observes Discord
            # before retiring an interrupted/uncertain local claim. A POST
            # cannot silently clear it or replay the old provider write.
            from ..hosted import audit
            with self.s.local(self.workspace, self.token) as (cur, state, actor):
                channel, _, current = self.custody(cur, state, actor)
                if (current != stamp or channel.get('discordSenderEdit') != claim
                        or self.s.oauth.clock() < claim['expiresAt']):
                    fail()
                if claim.get('rateAdmissionId'):
                    from .rate_limits import Permit, _digest
                    limiter = self.s.adapter.rate_limiter
                    if not self.s.adapter.rate_v1_enabled or limiter is None:
                        fail('Discord request coordination must be restored before this name change can be reconciled.')
                    permit = Permit(claim['rateAdmissionId'], limiter.application_key, 'PATCH',
                                    _digest(f'/guilds/{envelope["guild"]}/members/@me'),
                                    self.s.adapter._rate_identity('bot'), None, claim['rateExpiresAt'])
                    limiter.reconcile_nickname(cur, permit, envelope['guild'])
                channel.pop('discordSenderEdit', None)
                channel.update(discordSenderName=name, discordSenderRevision=str(uuid.uuid4()))
                self.s.save_state(cur, self.workspace, state)
                audit(cur, self.workspace, actor, 'discord.sender_name_reconciled', self.connection,
                      {'scope': 'server', 'guildId': envelope['guild']})
                _, _, stamp = self.custody(cur, state, actor)
        profile = {'connectionId': self.connection, 'senderKind': kind, 'scope': scope,
                   'guildId': envelope['guild'], 'name': name, 'maxLength': 80 if kind == 'webhook' else 32,
                   'fingerprint': digest([stamp, name]), 'state': 'verified'}
        return profile, envelope, stamp

    def get(self):
        return self.observe(reconcile=True)[0]

    def write_guard(self, stamp, claim_id):
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, _, current = self.custody(cur, state, actor)
            claim = channel.get('discordSenderEdit') or {}
            if current != stamp or claim.get('id') != claim_id or self.s.oauth.clock() >= claim.get('expiresAt', 0):
                fail()
        return True

    def set(self, body):
        if (not isinstance(body, dict) or set(body) - {'name', 'fingerprint', 'confirmed', 'sharedServerConfirmed'}
                or body.get('confirmed') is not True or not isinstance(body.get('fingerprint'), str)):
            fail('Review and confirm the sender name before saving.', 400)
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            self.custody(cur, state, actor, fresh=False)
            self.s.oauth.repository.assert_fresh(self.token, actor)
        profile, envelope, stamp = self.observe()
        name = validate_name(body.get('name'), profile['senderKind'])
        if body['fingerprint'] != profile['fingerprint']:
            fail()
        if profile['senderKind'] == 'bot':
            if body.get('sharedServerConfirmed') is not True:
                fail('Confirm that this bot nickname is shared by everyone in this server.', 400)
            claim_id = str(uuid.uuid4())
            with self.s.local(self.workspace, self.token) as (cur, state, actor):
                channel, _, current = self.custody(cur, state, actor)
                if current != stamp or channel.get('discordSenderEdit'):
                    fail()
                channel['discordSenderEdit'] = {'id': claim_id, 'name': name,
                                               'expiresAt': self.s.oauth.clock() + 120}
                self.s.save_state(cur, self.workspace, state)
                _, _, stamp = self.custody(cur, state, actor)
            def admitted(permit):
                nonlocal stamp
                with self.s.local(self.workspace, self.token) as (cur, state, actor):
                    channel, _, current = self.custody(cur, state, actor)
                    if current != stamp or (channel.get('discordSenderEdit') or {}).get('id') != claim_id:
                        fail()
                    channel['discordSenderEdit'].update(rateAdmissionId=permit.id, rateExpiresAt=permit.expires_at)
                    self.s.save_state(cur, self.workspace, state)
                    _, _, stamp = self.custody(cur, state, actor)
            try:
                response = self.s.adapter._bot('PATCH', f'/guilds/{envelope["guild"]}/members/@me',
                    body={'nick': name}, write_authorize=lambda: self.write_guard(stamp, claim_id), write_admitted=admitted)
            except Exception:
                raise AlphaError('Discord did not confirm the nickname change. Wait two minutes, then reload its current value.',
                                 409, code='discord_sender_edit_pending') from None
            member = response.get('body')
            if (response.get('status') != 200 or not isinstance(member, dict)
                    or (member.get('user') or {}).get('id') != envelope['botUserId'] or member.get('nick') != name):
                fail('Discord did not confirm the new nickname. Reload to check its current value before trying again.')
            observed = self.s.adapter._json(self.s.adapter._bot('GET',
                f'/guilds/{envelope["guild"]}/members/{envelope["botUserId"]}', read_authorize=lambda: self.guard(stamp)), dict)
            if (observed.get('user') or {}).get('id') != envelope['botUserId'] or observed.get('nick') != name:
                fail('The server nickname changed during verification. Reload before trying again.')
        from ..hosted import audit
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, _, current = self.custody(cur, state, actor)
            if current != stamp:
                fail()
            channel.update(discordSenderName=name, discordSenderRevision=str(uuid.uuid4()))
            channel.pop('discordSenderEdit', None)
            self.s.save_state(cur, self.workspace, state)
            audit(cur, self.workspace, actor, 'discord.sender_name_updated', self.connection,
                  {'senderKind': profile['senderKind'], 'scope': profile['scope'], 'guildId': envelope['guild']})
            _, _, saved_stamp = self.custody(cur, state, actor)
        return {**profile, 'name': name, 'fingerprint': digest([saved_stamp, name])}
