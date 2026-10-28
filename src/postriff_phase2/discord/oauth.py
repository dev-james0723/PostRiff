"""Discord identity, installation and destination custody in Rafii's existing DB.

No new tables, provider secrets, scheduler or inbound events. Network calls take
place between short workspace transactions. Ordinary refresh preserves consent
generation; reconnect/revocation fences every dependent installation.
"""
import base64
import copy
import hashlib
import json
import math
import secrets
import uuid
from contextlib import contextmanager
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from . import launch_gate
from .authorization import digest, snowflake


def fail(message='Reconnect Discord and authorize the server and channel again.', status=409):
    raise AlphaError(message, status, code='discord_connection_required')


def identity_capabilities():
    """An identity proves the authorizer, never authority to send a message."""
    return {'connectionKind': 'identity', 'senderKind': 'none', 'canPublish': False,
            'canSchedule': False, 'postAsPersonalUser': False,
            'capabilityReason': 'discord_identity_only'}


def stable_id(kind, workspace, application, account, actor=''):
    return 'discord-' + kind + '-' + str(uuid.uuid5(uuid.NAMESPACE_URL,
        'rafii:discord:' + digest([kind, workspace, application, account, actor])))


def identity_record(state, connection, actor=None):
    record = next((x for x in state.get('phase2', {}).get('discordIdentityLinks', [])
                   if x.get('id') == connection and x.get('workspaceId') == state['workspace']['id']), None)
    if not record or actor is not None and record.get('authorizedBy') != actor:
        fail('This Discord identity is unavailable to this workspace member.', 404)
    return record


def validate_context(context, workspace, actor, adapter, redirect, scopes, capability):
    purpose = context.get('purpose') if isinstance(context, dict) else None
    expected = ['identify', 'guilds'] if purpose == 'identity' and context.get('discoverGuilds') else ['identify'] if purpose == 'identity' else ['identify', 'webhook.incoming'] if purpose == 'webhook' else ['identify', 'bot']
    if (purpose not in ('identity', 'installation', 'webhook') or context.get('v') != (2 if purpose == 'webhook' else 1)
            or purpose == 'webhook' and (context.get('v') != 2 or not isinstance(context.get('pkceVerifier'), str) or not 43 <= len(context['pkceVerifier']) <= 128)
            or context.get('workspaceId') != workspace or context.get('memberId') != actor
            or context.get('applicationId') != adapter.client_id or context.get('redirectUri') != redirect
            or sorted(scopes) != sorted(expected) or capability != ('identity' if purpose == 'identity' else 'publish')):
        fail('This Discord authorization request changed. Start again.')
    return purpose


class DiscordConnections:
    def __init__(self, oauth):
        self.oauth = oauth

    @property
    def adapter(self):
        adapter = self.oauth._provider('discord')
        if not getattr(adapter, 'connections_v2_enabled', False) or not getattr(adapter, 'authorization_v2_enabled', False):
            fail('Discord connection authorization is not enabled.', 503)
        if not getattr(adapter, 'execution_enabled', True):
            fail('Discord is paused. Try again when the connection is available.', 503)
        from ..connection_review import public_connection_review
        if hasattr(adapter, 'connection_review') and not public_connection_review(adapter, self.oauth.callback_uri('discord')):
            fail('Discord application review and callback configuration are still pending.')
        return adapter

    @contextmanager
    def local(self, workspace, token):
        """Workspace -> credential lock order; never call the provider here."""
        if token is not None:
            with self.oauth.repository.transaction(token, workspace) as (cur, row, actor):
                from ..hosted import _membership
                from ..permissions import require
                require(_membership(row), 'manage_connections')
                state = json.loads(row[1]) if isinstance(row[1], str) else copy.deepcopy(row[1])
                yield cur, state, actor
        else:
            # Internal worker only. HTTP entry points always supply an authenticated token.
            with self.oauth.repository.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
                row = cur.fetchone()
                if not row:
                    fail('Workspace unavailable.', 404)
                state = json.loads(row[0]) if isinstance(row[0], str) else copy.deepcopy(row[0])
                yield cur, state, None

    def save_state(self, cur, workspace, state):
        self.oauth.commands.engine.invalidate(state)
        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))

    def sender_profile(self, workspace, token, connection):
        from .sender_names import SenderNames
        return SenderNames(self, workspace, token, connection).get()

    def set_sender_name(self, workspace, token, connection, body):
        from .sender_names import SenderNames
        return SenderNames(self, workspace, token, connection).set(body)

    def nickname_contenders(self, cur, workspace, connection, guild):
        """How many OTHER live bot installations of this server exist (any workspace). A count, never an identifier.

        The bot's nickname is one value per server, but any workspace whose authorizer manages the server can hold an
        installation of it. Rafii therefore writes that nickname only while this installation is the server's only live
        one: for two workspaces to both pass this check, each would have to commit its installation row after the other's
        check, which is impossible because a connection is only editable once its own row exists. The check runs in the
        final guard immediately before the provider write. Revoked rows (disconnect, identity loss) do not count.
        """
        self.guild_lock(cur, guild)
        cur.execute("SELECT count(*) FROM public.pr_encrypted_credentials WHERE provider='discord' AND provider_account_id=%s AND 'bot' = ANY(scopes) AND revoked_at IS NULL AND NOT (workspace_id=%s AND connection_id=%s)", (guild, workspace, connection))
        return int(cur.fetchone()[0])

    def guild_lock(self, cur, guild):
        """Orders an authority check against a competing installation of the same server, application-wide.

        Transaction-scoped (released at commit, never held across Discord IO) and taken by BOTH the nickname authority
        check and the installation commit, so a second workspace's installation row cannot appear half-way through a
        check: it commits strictly before or strictly after it. Lock order everywhere: workspace row, then credential
        rows, then this lock, so no cycle exists between two workspaces."""
        key = 'rafii.discord.nickname:' + str(self.adapter.client_id) + ':' + str(guild)
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (key,))

    def read_credential(self, cur, workspace, connection):
        cur.execute("SELECT access_ciphertext,key_id,refresh_ciphertext,extract(epoch from access_expires_at),authorization_generation::text,scopes,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='discord' AND revoked_at IS NULL FOR NO KEY UPDATE", (workspace, connection))
        row = cur.fetchone()
        if not row:
            fail()
        try:
            envelope = json.loads(self.oauth.vault.decrypt(row[0], row[1]))
        except (TypeError, ValueError):
            fail()
        if not isinstance(envelope, dict) or envelope.get('applicationId') != self.adapter.client_id:
            fail()
        return row, envelope

    def bind_identity(self, cur, workspace, record):
        if record.get('status') != 'linked':
            fail('The linked Discord identity needs reconnecting.')
        row, envelope = self.read_credential(cur, workspace, record['id'])
        if (record.get('applicationId') != self.adapter.client_id or envelope.get('kind') != 'identity' or envelope.get('user') != record.get('userId')
                or envelope.get('memberId') != record.get('authorizedBy') or row[4] != record.get('authorizationGeneration')
                or row[6] != record.get('userId') or not snowflake(envelope.get('user'))
                or not isinstance(envelope.get('at'), str) or not envelope['at']):
            fail()
        return row, envelope

    def _response(self, method, path, bearer=None, *, user_id=None, **kwargs):
        adapter = self.adapter
        headers = {'Authorization': 'Bearer ' + bearer if bearer else adapter._basic(),
                   'User-Agent': f'DiscordBot ({adapter.website}, 1)'}
        response = adapter._discord_http(method, path, headers=headers, credential_kind='user' if bearer else 'oauth',
                                         bearer=bearer, user_id=user_id, **kwargs)
        if response.get('status') not in (200, 201, 204):
            error = AlphaError('Discord access is unavailable. Reconnect if permissions were removed.', 409 if response.get('status') in (400, 401, 403) else 503)
            error.discord_permanent = response.get('status') in (400, 401, 403)
            error.discord_status = response.get('status')
            raise error
        return response.get('body')

    def verified_authorization(self, bearer, required, user_id=None):
        """Fresh token/subject/application proof; identify includes the user here."""
        info = self._response('GET', '/oauth2/@me', bearer, user_id=user_id)
        user = info.get('user') if isinstance(info, dict) else None
        verified_id = user.get('id') if isinstance(user, dict) else None
        if not snowflake(verified_id) or user_id is not None and verified_id != user_id:
            fail('Discord did not verify the expected identity.')
        if (not isinstance(info.get('application'), dict)
                or info['application'].get('id') != self.adapter.client_id):
            fail('Discord did not confirm this Rafii application. Start the connection again.')
        if (not isinstance(info.get('scopes'), list)
                or any(not isinstance(scope, str) for scope in info['scopes'])
                or not set(required).issubset(info['scopes'])):
            fail('Discord did not confirm the required user permissions. Link your Discord identity again.')
        return user, list(info['scopes'])

    def verified_user(self, bearer, required, user_id=None):
        # Callback and rotating-token exchange retain an independent profile
        # subject check. The hot path needs only the live authorization proof.
        authorized, scopes = self.verified_authorization(bearer, required, user_id)
        user = self._response('GET', '/users/@me', bearer, user_id=authorized['id'])
        if not isinstance(user, dict) or not snowflake(user.get('id')) or user['id'] != authorized['id']:
            fail('Discord returned a different profile for this authorization. Start again.')
        return user, scopes

    @staticmethod
    def token_body(body):
        if (not isinstance(body, dict) or not isinstance(body.get('access_token'), str) or not body['access_token']
                or body.get('token_type', '').lower() != 'bearer' or type(body.get('expires_in')) not in (int, float)
                or not math.isfinite(body['expires_in']) or not 0 < body['expires_in'] <= 86400 * 365
                or not isinstance(body.get('scope'), str)):
            fail('Discord did not return a valid expiring authorization.')
        return body

    def start(self, workspace, token, capability, inputs):
        if token is None:
            fail('Sign in to manage Discord connections.', 401)
        from ..hosted import audit, throttle
        adapter = self.adapter
        purpose = inputs.get('discordPurpose', 'identity' if capability == 'identity' else 'installation')
        if purpose not in ('identity', 'installation', 'webhook') or capability != ('identity' if purpose == 'identity' else 'publish'):
            fail('Choose identity linking or server installation.', 400)
        if purpose == 'webhook':
            from .webhooks import require_enabled
            require_enabled(adapter)
            if any(k in inputs for k in ('url', 'webhookUrl', 'token', 'secret', 'webhookToken')):
                fail('Use Discord’s official channel authorization.', 400)
            if inputs.get('channelId') is not None and not snowflake(inputs['channelId']):
                fail('Choose a valid Discord channel.', 400)
        discover = inputs.get('discoverGuilds') is True
        scopes = ['identify', 'guilds'] if purpose == 'identity' and discover else ['identify'] if purpose == 'identity' else ['identify', 'webhook.incoming'] if purpose == 'webhook' else ['identify', 'bot']
        redirect = self.oauth.callback_uri('discord')
        identity = None
        if purpose == 'installation':
            if not snowflake(inputs.get('guildId')):
                fail('Select the exact Discord server to authorize.', 400)
            identity = self._fresh_identity(workspace, token, inputs.get('identityConnectionId'))
            if not any(g['id'] == inputs['guildId'] for g in self.user_guilds(identity)):
                fail('This identity cannot manage the selected Discord server.', 403)
        with self.local(workspace, token) as (cur, state, actor):
            throttle(cur, f'oauth-start:{workspace}', 20, 600)
            links = state.get('phase2', {}).get('discordIdentityLinks', [])
            context = {'v': 1, 'purpose': purpose, 'workspaceId': workspace, 'memberId': actor,
                       'applicationId': adapter.client_id, 'redirectUri': redirect, 'discoverGuilds': discover,
                       'identityGenerations': {x['id']: x.get('authorizationGeneration') for x in links if x.get('authorizedBy') == actor},
                       'connectionId': inputs.get('connectionId')}
            if purpose == 'webhook':
                context.update(v=2, pkceVerifier=secrets.token_urlsafe(48), expectedChannelId=inputs.get('channelId'))
                if inputs.get('identityConnectionId'):
                    selected = identity_record(state, inputs['identityConnectionId'], actor)
                    self.bind_identity(cur, workspace, selected)
                    context.update(expectedUserId=selected['userId'], identityConnectionId=selected['id'],
                                   identityGeneration=selected['authorizationGeneration'])
                if inputs.get('connectionId'):
                    prior = next((x for x in state.get('phase2', {}).get('channels', []) if x.get('id') == inputs['connectionId']), None)
                    if not prior or prior.get('discordConnectionKind') != 'webhook' or prior.get('discordAuthorizedBy') != actor:
                        fail('Reconnect your own authorized webhook.', 404)
                    context.update(expectedUserId=prior['discordLinkedUserId'], expectedChannelId=prior['discordWebhookChannelId'],
                                   priorGeneration=prior['discordAuthorizationGeneration'])
            elif purpose == 'installation':
                record = identity_record(state, identity['connectionId'], actor)
                self.bind_identity(cur, workspace, record)
                if record['authorizationGeneration'] != identity['authorizationGeneration']:
                    fail()
                prior = next((x for x in state.get('phase2', {}).get('channels', []) if x['id'] == inputs.get('connectionId')), None)
                if inputs.get('connectionId') and (not prior or prior.get('platform') != 'Discord' or prior.get('providerAccountId') != inputs['guildId']):
                    fail('Reconnect the original Discord server.', 404)
                context.update(identityConnectionId=record['id'], identityGeneration=record['authorizationGeneration'],
                               userId=record['userId'], guildId=inputs['guildId'],
                               installationGeneration=prior.get('discordAuthorizationGeneration') if prior else None)
            elif inputs.get('connectionId'):
                record = identity_record(state, inputs['connectionId'], actor)
                context['expectedUserId'] = record['userId']
            if purpose == 'installation':
                # A brand-new server takes one of the shared bot's limited slots (launch_gate); one the bot already
                # holds a slot for (for example after a disconnect) does not, and neither does a reconnect. Every
                # installation start, a reconnect too, counts toward the few a person may have in flight.
                launch_gate.reserve_capacity(cur, guild_id=inputs.get('guildId'), person=(workspace, actor),
                                             new_server=not inputs.get('connectionId'))
            state_value = secrets.token_urlsafe(32)
            ciphertext, key = self.oauth.vault.encrypt(json.dumps(context))
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,'discord',%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>600)) RETURNING id::text", (workspace, actor, capability, redirect, scopes, hashlib.sha256(state_value.encode()).hexdigest(), ciphertext, key))
            transaction = cur.fetchone()[0]
            audit(cur, workspace, actor, 'oauth.started', transaction, {'provider': 'discord', 'purpose': purpose})
        params = {'client_id': adapter.client_id, 'response_type': 'code', 'redirect_uri': redirect,
                  'scope': ' '.join(scopes), 'state': state_value}
        if purpose == 'webhook':
            params.update(code_challenge=base64.urlsafe_b64encode(hashlib.sha256(context['pkceVerifier'].encode()).digest()).decode().rstrip('='), code_challenge_method='S256')
        if purpose == 'installation':
            params.update(permissions=str(adapter.PERMISSIONS), integration_type='0', guild_id=inputs['guildId'], disable_guild_select='true')
        return {'transactionId': transaction, 'provider': 'discord', 'platform': 'Discord', 'capability': capability,
                'discordPurpose': purpose, 'scopes': scopes, 'expiresAt': self.oauth.clock() + 600,
                'permissionExplanation': ('Link your personal Discord profile' + (' and server list' if discover else ' only') + '. This does not authorize publishing as you. It does not install a bot.') if purpose == 'identity' else 'Authorize creation of a Rafii incoming webhook in the channel selected on Discord. Sending still requires separate channel and message approval; text only, never personal-user authorship.' if purpose == 'webhook' else 'Install Rafii’s bot in the selected server. Messages are sent by the bot, not your personal account. Authorize each channel separately.',
                'authorizeUrl': adapter.AUTH + '?' + urlencode(params)}

    def complete(self, workspace, token, state_value, code, error=None, iss=None):
        if token is None:
            fail('Sign in to manage Discord connections.', 401)
        from ..hosted import audit
        if not isinstance(state_value, str) or not 20 <= len(state_value) <= 128:
            fail('Connection request unavailable.', 404)
        adapter = self.adapter
        with self.local(workspace, token) as (cur, _, actor):
            cur.execute("SELECT id::text,member_id::text,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE workspace_id=%s AND provider='discord' AND state_hash=%s FOR UPDATE", (workspace, hashlib.sha256(state_value.encode()).hexdigest()))
            row = cur.fetchone()
            if not row or row[1] != actor or row[8]:
                fail('Connection request unavailable.', 404)
            if float(row[7]) <= self.oauth.clock():
                fail('This connection request expired. Start again.')
            try:
                context = json.loads(self.oauth.vault.decrypt(row[5], row[6]))
            except (TypeError, ValueError):
                fail('Connection request unavailable.', 404)
            purpose = validate_context(context, workspace, actor, adapter, self.oauth.callback_uri('discord'), row[4], row[2])
            if purpose == 'webhook':
                from .webhooks import require_enabled
                require_enabled(adapter)
            if iss is not None and iss != 'https://discord.com' or context.get('v') == 2 and iss != 'https://discord.com':
                fail('Discord authorization issuer did not match. Start again.')
            if row[3] != context['redirectUri']:
                fail('The Discord callback changed. Start again.')
            cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome=%s WHERE id::text=%s", ('denied' if error or not code else 'exchange_started', row[0]))
            audit(cur, workspace, actor, 'oauth.exchange_claimed', row[0], {'provider': 'discord', 'purpose': purpose})
        # Committed single use BEFORE provider exchange, including ambiguous failures.
        if error or not code:
            return {'connected': False, 'reason': 'denied', 'discordPurpose': purpose}
        if purpose in ('installation', 'webhook') and not context.get('connectionId'):
            self.oauth._admit_identity(workspace, adapter)
        body = self.token_body(self._response('POST', '/oauth2/token', form={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': context['redirectUri'], **({'code_verifier': context['pkceVerifier']} if context.get('v') == 2 else {})}))
        # `bot` is installation consent, not a user bearer permission. The
        # frozen request still requires it; prove installation independently
        # below rather than requiring it in current bearer introspection.
        required = ['identify'] if purpose in ('installation', 'webhook') else row[4]
        user, scopes = self.verified_user(body['access_token'], required, context.get('expectedUserId') or context.get('userId'))
        if context.get('expectedUserId') and user['id'] != context['expectedUserId']:
            fail('Reconnect the original Discord identity.')
        if purpose == 'webhook':
            result = self.save_webhook_callback(workspace, token, context, body, user, scopes)
        elif purpose == 'installation':
            if (user['id'] != context.get('userId') or not isinstance(body.get('guild'), dict)
                    or body['guild'].get('id') != context.get('guildId')):
                fail('Discord authorized a different identity or server. Start again.')
            envelope = {'v': 2, 'kind': 'installation', 'applicationId': adapter.client_id,
                        'botUserId': adapter._bot_identity(), 'user': user['id'], 'guild': context['guildId'], 'channel': None,
                        'identityConnectionId': context['identityConnectionId'], 'identityGeneration': context['identityGeneration']}
            guild = adapter._json(adapter._bot('GET', '/guilds/' + context['guildId']), dict)
            if guild.get('id') != context['guildId']:
                fail()
            # Fresh bot/user membership and effective permissions; channel consent stays independent.
            if not adapter.destinations(json.dumps(envelope)):
                fail('Rafii cannot access a publishable channel in this server. Check bot and server permissions, then reconnect.')
            # Keep observed bearer scopes separate from independently proven
            # installation consent. This envelope contains no bearer token.
            # Connection capabilities combine the two only after all proofs;
            # channel destination approval remains a separate operation.
            envelope['authorization'] = {'bearerScopes': scopes, 'installationScopes': ['bot']}
            connection_scopes = sorted(set(scopes) | set(envelope['authorization']['installationScopes']))
            result = self.save_installation(workspace, token, context, envelope, connection_scopes, guild)
            # Do not revoke this transient token: Discord revocation may invalidate
            # associated identity grants. It is not retained or used to publish.
        else:
            result = self.save_identity(workspace, token, context, body, user, scopes)
        with self.local(workspace, token) as (cur, _, actor):
            cur.execute("UPDATE public.pr_oauth_transactions SET outcome='exchanged' WHERE id::text=%s AND workspace_id=%s", (row[0], workspace))
            audit(cur, workspace, actor, 'discord.' + purpose + '_authorized', result['connectionId'])
        return result

    def upsert(self, cur, workspace, connection, account, envelope, scopes, expires=None, refresh=None):
        ciphertext, key = self.oauth.vault.encrypt(json.dumps(envelope))
        refresh_ct = self.oauth.vault.encrypt(refresh)[0] if refresh else None
        cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at,refresh_supported) VALUES(%s,%s,'discord',%s,%s,%s,%s,%s,to_timestamp(%s),%s) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET provider_account_id=excluded.provider_account_id,access_ciphertext=excluded.access_ciphertext,refresh_ciphertext=excluded.refresh_ciphertext,key_id=excluded.key_id,scopes=excluded.scopes,access_expires_at=excluded.access_expires_at,refresh_supported=excluded.refresh_supported,revoked_at=NULL,authorization_generation=gen_random_uuid(),rotated_at=now(),updated_at=now() RETURNING authorization_generation::text", (workspace, connection, account, ciphertext, refresh_ct, key, scopes, expires, bool(refresh_ct)))
        return cur.fetchone()[0]

    def invalidate_dependents(self, cur, workspace, state, identity_id):
        for channel in state.get('phase2', {}).get('channels', []):
            if channel.get('discordIdentityConnectionId') != identity_id:
                continue
            generation = str(uuid.uuid4())
            channel.update(revoked=True, capabilityVerified=False, defaultDestinationId=None, discordAuthorizationGeneration=generation)
            for target in channel.get('discordDestinations', []):
                target['status'] = 'revoked'
            cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,authorization_generation=%s::uuid,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND provider='discord'", (generation, workspace, channel['id']))

    def save_identity(self, workspace, token, context, body, user, scopes):
        with self.local(workspace, token) as (cur, state, actor):
            if actor != context['memberId']:
                fail()
            connection = stable_id('identity', workspace, self.adapter.client_id, user['id'], actor)
            links = state.setdefault('phase2', {}).setdefault('discordIdentityLinks', [])
            prior = next((x for x in links if x['id'] == connection), None)
            if prior and prior.get('authorizationGeneration') != context['identityGenerations'].get(connection):
                fail('Discord changed during connection. Reload and start again.')
            if prior:
                self.invalidate_dependents(cur, workspace, state, connection)
            expires = self.oauth.clock() + body['expires_in']
            generation = self.upsert(cur, workspace, connection, user['id'], {'v': 1, 'kind': 'identity', 'applicationId': self.adapter.client_id, 'memberId': actor, 'user': user['id'], 'at': body['access_token']}, scopes, expires, body.get('refresh_token'))
            record = {'id': connection, 'workspaceId': workspace, 'applicationId': self.adapter.client_id, 'userId': user['id'],
                      'account': str(user.get('global_name') or user.get('username') or user['id'])[:128],
                      'authorizedBy': actor, 'authorizedAt': self.oauth.clock(), 'authorizationGeneration': generation,
                      'status': 'linked', 'expiresAt': expires, 'discoverGuilds': 'guilds' in scopes}
            if prior:
                prior.clear(); prior.update(record)
            else:
                links.append(record)
            self.save_state(cur, workspace, state)
        return {'connected': True, 'connectionId': connection, 'account': record['account'], 'discordPurpose': 'identity', 'missingScopes': [], **identity_capabilities()}

    def save_installation(self, workspace, token, context, envelope, scopes, guild):
        with self.local(workspace, token) as (cur, state, actor):
            record = identity_record(state, context['identityConnectionId'], actor)
            identity_row, _ = self.bind_identity(cur, workspace, record)
            if record['authorizationGeneration'] != context['identityGeneration'] or not identity_row[3] or float(identity_row[3]) <= self.oauth.clock():
                fail()
            connection = stable_id('install', workspace, self.adapter.client_id, context['guildId'])
            prior = next((x for x in state.get('phase2', {}).get('channels', []) if x['id'] == connection), None)
            if prior and (context.get('connectionId') != connection or prior.get('discordAuthorizationGeneration') != context.get('installationGeneration')):
                fail('This server is already connected or changed meanwhile. Reconnect its existing card.')
            self.guild_lock(cur, context['guildId'])   # orders this installation against a bot-nickname authority check
            generation = self.upsert(cur, workspace, connection, context['guildId'], envelope, scopes)
            now = self.oauth.clock()
            channel = {'id': connection, 'platform': 'Discord', 'account': str(guild.get('name') or context['guildId'])[:128],
                       'accountType': 'server', 'providerAccountId': context['guildId'], 'scopes': scopes,
                       'enabledPermissionGroups': ['identity', 'publish'], 'verifiedAt': now, 'expiresAt': now + 86400 * 365 * 5,
                       'capabilityVersion': self.adapter.capability_version, 'discordAuthorizationGeneration': generation}
            matrix = self.oauth._capabilities(self.adapter, 'publish', scopes, [], now, json.dumps(envelope))
            for name, value in matrix.items():
                cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level=excluded.level,evidence=excluded.evidence,capability_version=excluded.capability_version,verified_at=excluded.verified_at,updated_at=now()", (workspace, connection, name, value['level'], value['evidence'], value['capabilityVersion'], value['verifiedAt']))
            updated = self.oauth.commands.upsert_verified_channel(state, actor, channel, capability_verified=matrix['publish']['level'] == 'Direct')
            saved = next(c for c in updated['phase2']['channels'] if c['id'] == connection)
            saved.update(discordIdentityConnectionId=record['id'], discordConnectionKind='installation')
            self.save_state(cur, workspace, updated)
        return {'connected': True, 'connectionId': connection, 'account': channel['account'], 'discordPurpose': 'installation', 'missingScopes': []}

    def _fresh_identity(self, workspace, token, connection):
        claim, fast = None, None
        with self.local(workspace, token) as (cur, state, actor):
            record = identity_record(state, connection, actor)
            row, envelope = self.bind_identity(cur, workspace, record)
            if record.get('refreshClaim'):
                fail('Discord identity refresh is pending or requires reconnecting.')
            if row[3] and float(row[3]) > self.oauth.clock() + 60:
                fast = {'connectionId': connection, 'authorizationGeneration': row[4], 'userId': envelope['user'], 'bearer': envelope['at'], 'scopes': list(row[5])}
            else:
                if not row[2]:
                    fail('This Discord identity expired. Reconnect it.')
                claim = str(uuid.uuid4())
                record.update(refreshClaim=claim, refreshStartedAt=self.oauth.clock())
                self.save_state(cur, workspace, state)
                refresh = self.oauth.vault.decrypt(row[2], row[1])
        if fast is not None:
            # Local expiry is not proof that Discord still authorizes this user.
            try:
                user, _ = self.verified_authorization(fast['bearer'], fast['scopes'], fast['userId'])
                if user['id'] != fast['userId']:
                    fail('The Discord identity changed. Reconnect.')
            except AlphaError as error:
                if getattr(error, 'discord_permanent', False) or error.code == 'discord_connection_required':
                    with self.local(workspace, token) as (cur, state, actor):
                        record = identity_record(state, connection, actor)
                        current, _ = self.bind_identity(cur, workspace, record)
                        if current[4] == row[4] and current[0] == row[0]:
                            record['status'] = 'reconnect_required'
                            self.invalidate_dependents(cur, workspace, state, connection)
                            self.save_state(cur, workspace, state)
                raise
            with self.local(workspace, token) as (cur, state, actor):
                record = identity_record(state, connection, actor)
                current, _ = self.bind_identity(cur, workspace, record)
                if (current[0] != row[0] or current[4] != row[4] or record.get('refreshClaim')
                        or not current[3] or float(current[3]) <= self.oauth.clock()):
                    fail('Discord changed during identity verification. Try again.')
            return fast
        from .rate_limits import RateCoordinatorUnavailable, RateDelayed

        def reconnect_required():
            with self.local(workspace, token) as (cur, state, actor):
                record = identity_record(state, connection, actor)
                if record.get('refreshClaim') == claim and record.get('authorizationGeneration') == row[4]:
                    record['status'] = 'reconnect_required'
                    self.invalidate_dependents(cur, workspace, state, connection)
                    self.save_state(cur, workspace, state)
            fail('Discord refresh could not be confirmed. Reconnect before publishing.')

        def release_claim():
            with self.local(workspace, token) as (cur, state, actor):
                record = identity_record(state, connection, actor)
                if record.get('refreshClaim') == claim and record.get('authorizationGeneration') == row[4]:
                    record.pop('refreshClaim', None); record.pop('refreshStartedAt', None)
                    self.save_state(cur, workspace, state)

        # Never retry an ambiguous rotating-token exchange automatically.
        try:
            response = self._response('POST', '/oauth2/token', user_id=envelope['user'], form={'grant_type': 'refresh_token', 'refresh_token': refresh})
        except (RateDelayed, RateCoordinatorUnavailable):
            # The shared request coordinator refused BEFORE any request was built or sent, so the rotating refresh token
            # is untouched and nothing is ambiguous. Free the claim and let the caller try again later; revoking here
            # would destroy a healthy connection (and its servers) because of a policy hold, an expired policy or a
            # busy minute.
            release_claim()
            raise
        except AlphaError as refused:
            if getattr(refused, 'discord_status', None) != 429:
                reconnect_required()
            # Discord itself answered 429: the request was rate limited and not processed, so the refresh token is
            # unspent either. Same outcome as a coordinator refusal; any other answer stays ambiguous.
            release_claim()
            raise RateDelayed(cause='provider_429') from refused
        except Exception:
            reconnect_required()
        # From here the old refresh token is spent, so a failure to verify the new one cannot be retried.
        try:
            body = self.token_body(response)
            user, scopes = self.verified_user(body['access_token'], row[5], envelope['user'])
            if user['id'] != envelope['user']:
                fail('Discord refreshed a different identity. Reconnect.')
        except Exception:
            reconnect_required()
        with self.local(workspace, token) as (cur, state, actor):
            record = identity_record(state, connection, actor)
            current, _ = self.bind_identity(cur, workspace, record)
            if record.get('refreshClaim') != claim or current[4] != row[4] or current[0] != row[0]:
                fail('Discord changed while refreshing. Reload the connection.')
            envelope['at'] = body['access_token']
            ciphertext, key = self.oauth.vault.encrypt(json.dumps(envelope))
            refresh_ct = self.oauth.vault.encrypt(body.get('refresh_token') or refresh)[0]
            expires = self.oauth.clock() + body['expires_in']
            cur.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,scopes=%s,access_expires_at=to_timestamp(%s),rotated_at=now(),updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND authorization_generation=%s::uuid AND access_ciphertext=%s AND revoked_at IS NULL", (ciphertext, refresh_ct, key, scopes, expires, workspace, connection, row[4], row[0]))
            if cur.rowcount != 1:
                fail()
            record.pop('refreshClaim', None); record.pop('refreshStartedAt', None)
            record.update(expiresAt=expires, discoverGuilds='guilds' in scopes)
            self.save_state(cur, workspace, state)
        return {'connectionId': connection, 'authorizationGeneration': row[4], 'userId': user['id'], 'bearer': body['access_token'], 'scopes': scopes}

    def user_guilds(self, identity):
        if 'guilds' not in identity['scopes']:
            fail('Reconnect this identity with server-list permission to authorize servers.')
        result, after = [], None
        for _ in range(5):
            page = self._response('GET', '/users/@me/guilds?' + urlencode({'limit': 200, **({'after': after} if after else {})}), identity['bearer'], user_id=identity['userId'])
            if not isinstance(page, list) or len(page) > 200:
                fail('Discord did not return a valid server list.')
            for guild in page:
                if not isinstance(guild, dict) or not snowflake(guild.get('id')):
                    fail('Discord did not return a valid server list.')
                try:
                    allowed = guild.get('owner') is True or int(guild.get('permissions', '0')) & ((1 << 3) | (1 << 5))
                except (TypeError, ValueError):
                    allowed = False
                if allowed:
                    result.append({'id': guild['id'], 'name': str(guild.get('name') or guild['id'])[:128]})
            if len(page) < 200:
                return result
            next_after = page[-1]['id']
            if next_after == after:
                fail('Discord server pagination did not progress.')
            after = next_after
        fail('The server list needs further pagination. Try a narrower authorized account.')

    def guilds(self, workspace, token, connection):
        if token is None:
            fail('Sign in to manage Discord connections.', 401)
        return {'identityConnectionId': connection, 'guilds': self.user_guilds(self._fresh_identity(workspace, token, connection))}

    def public_identities(self, workspace, token):
        if token is None:
            fail('Sign in to manage Discord connections.', 401)
        with self.oauth.repository.transaction(token, workspace) as (_, row, actor):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            return [{**{k: x[k] for k in ('id', 'account', 'userId', 'status', 'expiresAt', 'discoverGuilds') if k in x},
                     **identity_capabilities(),
                     **({'privateDraftsConfigured': x.get('privateDraftsLinked') is True,
                         'privateDraftsLinked': x.get('privateDraftsLinked') is True and x.get('status') == 'linked'
                         and bool(x.get('authorizationGeneration')) and x.get('privateDraftsGeneration') == x.get('authorizationGeneration')}
                        if 'privateDraftsLinked' in x else {})}
                    for x in state.get('phase2', {}).get('discordIdentityLinks', [])
                    if isinstance(x, dict) and x.get('workspaceId') == workspace and x.get('authorizedBy') == actor]

    def installation_identity(self, workspace, connection):
        with self.local(workspace, None) as (cur, state, _):
            _, envelope = self.read_credential(cur, workspace, connection)
            if envelope.get('kind') == 'webhook':
                self.validate_webhook(cur, workspace, envelope)
                return
            if envelope.get('kind') != 'installation' or not envelope.get('identityConnectionId'):
                fail('Reconnect this legacy installation through a linked Discord identity.')
            # An expired *but refreshable* personal token is normal. Check
            # active Rafii membership before Discord IO without treating local
            # token expiry as an authorization-revocation verdict.
            record = identity_record(state, envelope['identityConnectionId'])
            self.require_active_installation_authorizer(cur, workspace, record)
        self._fresh_identity(workspace, None, envelope['identityConnectionId'])

    def reverify_installation(self, workspace, connection, *, token=None,
                              authenticated=None, actor=None, audit_event=None):
        """Preserve installation consent; observe user and destination access.

        Explicit member verification may restore existing publish/schedule
        capability. Worker/composer checks only renew still-verified authority.
        Neither path registers destinations, approves posts or changes scopes.
        """
        from ..hosted import audit
        adapter = self.adapter
        event = audit_event or ('channel.verified' if token is not None else self.oauth.WORKER_REVERIFIED)
        bound_fields = ('providerAccountId', 'discordConnectionKind', 'discordIdentityConnectionId',
                        'discordAuthorizationGeneration', 'scopes', 'revoked',
                        'defaultDestinationId', 'discordDestinations', 'enabledPermissionGroups',
                        'configured', 'identityVerified', 'capabilityVerified', 'verifiedAt',
                        'capabilityVersion', 'discordVerificationGeneration',
                        # Sender settings: a nickname write, a saved name or an edit claim that commits while Discord is
                        # being read is newer than this observation, which must then not be written over it.
                        'discordBotNickname', 'discordSenderEdit', 'discordSenderName', 'discordSenderRevision')

        def installation(cur, state, *, fresh=False):
            if state.get('accountDeletion') or state.get('accountBlock'):
                fail('This workspace cannot verify connections right now.')
            channel = next((c for c in state.get('phase2', {}).get('channels', [])
                            if c.get('id') == connection and c.get('platform') == 'Discord'), None)
            if not channel or channel.get('revoked'):
                fail('This Discord installation is unavailable.', 404)
            row, envelope = self.read_credential(cur, workspace, connection)
            if (envelope.get('kind') != 'installation' or channel.get('discordConnectionKind') != 'installation'
                    or envelope.get('guild') != row[6] or row[6] != channel.get('providerAccountId')
                    or not row[4] or row[4] != channel.get('discordAuthorizationGeneration')
                    or envelope.get('identityConnectionId') != channel.get('discordIdentityConnectionId')):
                fail('The Discord installation binding changed. Reconnect it.')
            scopes = row[5]
            if (not isinstance(scopes, (list, tuple)) or any(not isinstance(s, str) for s in scopes)
                    or not {'bot', 'identify'}.issubset(scopes)):
                fail('The required Discord installation consent is missing. Reconnect it.')
            # New envelopes preserve the callback's two kinds of evidence.
            # Older envelopes retain their recorded credential scopes; never
            # manufacture optional scopes lost by earlier generic verification.
            proof = envelope.get('authorization')
            if proof is not None:
                if (not isinstance(proof, dict)
                        or any(not isinstance(proof.get(k), list)
                               or any(not isinstance(s, str) for s in proof[k])
                               for k in ('bearerScopes', 'installationScopes'))
                        or 'identify' not in proof['bearerScopes'] or 'bot' not in proof['installationScopes']):
                    fail('The Discord installation consent evidence is incomplete. Reconnect it.')
            if fresh:
                self.validate_installation(cur, workspace, envelope)
            else:
                # Capture structural custody before I/O. Expiry is handled by
                # the existing rotating-token path, then rechecked at commit.
                record = identity_record(state, envelope['identityConnectionId'])
                credential, identity = self.bind_identity(cur, workspace, record)
                if (credential[4] != envelope.get('identityGeneration')
                        or identity['user'] != envelope.get('user') or record.get('refreshClaim')):
                    fail('The installation\u2019s linked identity changed. Reconnect.')
            return channel, row, envelope

        with self.local(workspace, token) as (cur, state, member):
            channel, starting, envelope = installation(cur, state)
            before = copy.deepcopy({k: channel.get(k) for k in bound_fields})
            scopes = list(starting[5])
            if token is not None:
                actor = member
        outcome, identity_verified, seen_nickname = 'read_verified', False, None
        try:
            identity = self._fresh_identity(workspace, None, envelope['identityConnectionId'])
            if (identity['authorizationGeneration'] != envelope.get('identityGeneration')
                    or identity['userId'] != envelope.get('user') or 'identify' not in identity['scopes']):
                fail('The linked Discord identity changed. Reconnect it.')
            live = adapter.destinations(json.dumps(envelope))
            if live and 'botNickname' in live[0]:
                seen_nickname = {'value': live[0]['botNickname'], 'observedAt': self.oauth.clock()}
            identity_verified = True
            # A live unrelated channel cannot stand in for a previously
            # approved destination whose permissions have since been removed.
            targets = [d for d in before.get('discordDestinations') or []
                       if d.get('status') == 'authorized']
            for target in targets:
                if (target.get('workspaceId') != workspace or target.get('connectionId') != connection
                        or target.get('authorizationGeneration') != starting[4]
                        or not any(all(e.get(k) == target.get(k) for k in
                                       ('applicationId', 'botUserId', 'linkedUserId', 'guildId', 'channelId'))
                                   for e in live)):
                    outcome = 'permission_missing'
            if not live:
                outcome = 'permission_missing'
            if 'publish' not in (before.get('enabledPermissionGroups') or []):
                outcome = 'consent_missing'
        except Exception as error:
            # Provider transports may raise stdlib, httpx or adapter-specific
            # failures. An unavailable observation never extends authority.
            outcome = ('reauthorization_required' if isinstance(error, AlphaError)
                       and (getattr(error, 'discord_permanent', False)
                            or error.code == 'discord_connection_required' and error.status < 500)
                       else 'verification_unavailable')

        @contextmanager
        def commit():
            if authenticated is not None:
                with self.oauth._reverification_commit(workspace, authenticated) as (cur, row, principal):
                    if not row:
                        fail('Workspace unavailable.', 404)
                    state = json.loads(row[0]) if isinstance(row[0], str) else copy.deepcopy(row[0])
                    yield cur, state, principal
            else:
                with self.local(workspace, token) as locked:
                    yield locked

        with commit() as (cur, state, member):
            actor = member if token is not None or authenticated is not None else actor
            try:
                channel, current, _ = installation(cur, state, fresh=True)
                unchanged = (current[0] == starting[0] and current[4] == starting[4]
                             and list(current[5]) == scopes
                             and {k: channel.get(k) for k in bound_fields} == before)
            except AlphaError:
                unchanged = False
            if not unchanged:
                audit(cur, workspace, actor, event, connection, {'state': 'verification_unavailable', 'reason': 'connection_changed'})
                return {'connectionId': connection, 'state': 'verification_unavailable',
                        'identityVerified': False, 'scopes': scopes, 'ready': False}
            if outcome == 'verification_unavailable':
                # No freshness extension or authority change from an outage.
                audit(cur, workspace, actor, event, connection, {'state': outcome})
                return {'connectionId': connection, 'state': outcome, 'identityVerified': False,
                        'scopes': scopes, 'ready': False}
            channel['identityVerified'] = identity_verified
            if outcome == 'read_verified':
                if set(channel.get('scopes') or []) != set(scopes):
                    outcome = 'scope_changed'
                else:
                    channel['verifiedAt'] = self.oauth.clock()
                    if seen_nickname is not None:
                        channel['discordBotNickname'] = seen_nickname   # what a later review freezes into its approval
                    if token is not None:
                        matrix = self.oauth._capabilities(adapter, 'publish', scopes, [], self.oauth.clock(), json.dumps(envelope))
                        channel['capabilityVerified'] = matrix['publish']['level'] == 'Direct'
                        channel['capabilityVersion'] = adapter.capability_version
                        for name in ('identity', 'publish', 'schedule'):
                            value = matrix[name]
                            cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level=excluded.level,evidence=excluded.evidence,capability_version=excluded.capability_version,verified_at=excluded.verified_at,updated_at=now()", (workspace, connection, name, value['level'], value['evidence'], value['capabilityVersion'], value['verifiedAt']))
            if outcome != 'read_verified':
                channel['capabilityVerified'] = False
                cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Discord identity or destination permissions could not be verified; review the connection.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND capability<>'identity'", (workspace, connection))
            # Fence an older success against a newer denial, even when both
            # observations began with capabilityVerified already false.
            channel['discordVerificationGeneration'] = str(uuid.uuid4())
            self.save_state(cur, workspace, state)
            audit(cur, workspace, actor, event, connection, {'state': outcome, 'proof': 'discord_installation'})
            ready = outcome == 'read_verified' and self.oauth.commands.engine.channel_state(channel) == 'Ready for posting'
            return {'connectionId': connection, 'state': outcome, 'identityVerified': identity_verified,
                    'scopes': scopes, 'ready': ready}

    @staticmethod
    def require_active_installation_authorizer(cur, workspace, record):
        # This check is independent of token expiry; a legitimately expiring
        # Discord bearer must still be able to use the existing safe refresh.
        from ..permissions import Membership
        if record.get('status') != 'linked' or not record.get('authorizedBy'):
            fail('The Discord server authorizer no longer manages this workspace connection.')
        cur.execute("SELECT m.role,m.can_manage_connections FROM public.pr_memberships m "
            "JOIN public.pr_profiles p ON p.user_id=m.user_id "
            "WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' "
            "AND p.deleted_at IS NULL FOR SHARE OF m,p",
            (workspace, record['authorizedBy']))
        member = cur.fetchone()
        if not member or not Membership.from_row(member[0], can_manage_connections=member[1]).allows('manage_connections'):
            fail('The Discord server authorizer no longer manages this workspace connection.')

    def validate_installation(self, cur, workspace, envelope):
        if envelope.get('kind') != 'installation' or not envelope.get('identityConnectionId'):
            fail('An identity grant cannot publish. Reconnect the server installation.')
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
        row = cur.fetchone()
        if not row:
            fail()
        state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        record = identity_record(state, envelope['identityConnectionId'])
        self.require_active_installation_authorizer(cur, workspace, record)
        credential, identity = self.bind_identity(cur, workspace, record)
        if (credential[4] != envelope.get('identityGeneration') or identity['user'] != envelope.get('user')
                or not credential[3] or float(credential[3]) <= self.oauth.clock() or record.get('refreshClaim')):
            fail('The installation’s linked identity changed or expired. Reconnect.')

    def disconnect_identity(self, workspace, token, connection):
        if token is None:
            fail('Sign in to manage Discord connections.', 401)
        from ..hosted import audit
        with self.local(workspace, token) as (cur, state, actor):
            record = identity_record(state, connection, actor)
            self.oauth.repository.assert_fresh(token, actor)
            generation = str(uuid.uuid4())
            record.update(status='disconnected', authorizationGeneration=generation)
            self.invalidate_dependents(cur, workspace, state, connection)
            cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,authorization_generation=%s::uuid,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND provider='discord'", (generation, workspace, connection))
            self.save_state(cur, workspace, state)
            audit(cur, workspace, actor, 'discord.identity_disconnected', connection)
        return {'disconnected': True, 'remoteRevocation': 'not_requested', 'note': 'Disconnected from this workspace. The shared bot stays installed. Remove Rafii in Discord Authorized Apps to revoke the Discord authorization across connected workspaces.'}

    def validate_webhook(self, cur, workspace, envelope):
        from .webhooks import require_enabled, path
        require_enabled(self.adapter)
        path(envelope)
        if (envelope.get('workspaceId') != workspace or envelope.get('applicationId') != self.adapter.client_id
                or any(not snowflake(envelope.get(k)) for k in ('webhookId', 'guild', 'channel', 'user'))):
            fail('Discord webhook custody does not match this workspace.')
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
        stored = cur.fetchone()
        if not stored: fail('Workspace unavailable.')
        state = json.loads(stored[0]) if isinstance(stored[0], str) else stored[0]
        if not stored or state.get('accountDeletion') or state.get('accountBlock'):
            fail('Workspace unavailable.')
        channel = next((c for c in state.get('phase2', {}).get('channels', [])
                        if c.get('id') == envelope.get('connectionId')), None)
        if (not channel or channel.get('revoked') or channel.get('discordConnectionKind') != 'webhook'
                or channel.get('discordAuthorizedBy') != envelope.get('memberId')
                or channel.get('providerAccountId') != envelope.get('webhookId')
                or channel.get('discordLinkedUserId') != envelope.get('user')
                or channel.get('discordWebhookChannelId') != envelope.get('channel')):
            fail('This Discord webhook was revoked or changed.')
        from ..permissions import Membership
        cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace, envelope['memberId']))
        member = cur.fetchone()
        if not member or not Membership.from_row(*member).allows('manage_connections'):
            fail('The webhook authorizer no longer has workspace connection permission.')

    def save_webhook_callback(self, workspace, token, context, body, user, scopes):
        from .webhooks import verify_resource, path
        hook = body.get('webhook')
        if (not isinstance(hook, dict) or 'webhook.incoming' not in body['scope'].split()
                or hook.get('application_id') != self.adapter.client_id or hook.get('type') != 1
                or any(not snowflake(hook.get(k)) for k in ('id', 'guild_id', 'channel_id'))
                or context.get('expectedChannelId') and hook.get('channel_id') != context['expectedChannelId']):
            fail('Discord did not authorize the expected webhook and channel.')
        envelope = {'v': 2, 'kind': 'webhook', 'workspaceId': workspace, 'memberId': context['memberId'],
                    'applicationId': self.adapter.client_id, 'webhookId': hook['id'], 'secret': hook.get('token'),
                    'guild': hook['guild_id'], 'channel': hook['channel_id'], 'user': user['id']}
        path(envelope)
        verify_resource(self.adapter, envelope)  # custody only; destination/dispatch require live permissions
        with self.local(workspace, token) as (cur, state, actor):
            if actor != context['memberId']: fail()
            channels = state.setdefault('phase2', {}).setdefault('channels', [])
            carried_name = None
            if context.get('identityConnectionId'):
                selected = identity_record(state, context['identityConnectionId'], actor)
                selected_row, _ = self.bind_identity(cur, workspace, selected)
                if selected_row[4] != context.get('identityGeneration') or selected['userId'] != user['id']:
                    fail('The selected identity changed during webhook authorization.')
                envelope.update(identityConnectionId=selected['id'], identityGeneration=selected_row[4])
            if context.get('connectionId'):
                prior = next((c for c in channels if c.get('id') == context['connectionId']), None)
                if (not prior or prior.get('discordAuthorizedBy') != actor
                        or prior.get('discordAuthorizationGeneration') != context.get('priorGeneration')):
                    fail('Discord changed during reconnect. Reload.')
                # New OAuth creates a new remote webhook. Revoke only old local authority.
                prior.update(revoked=True, capabilityVerified=False, defaultDestinationId=None)
                for d in prior.get('discordDestinations', []): d['status'] = 'revoked'
                carried_name = prior.get('discordSenderName')   # a Rafii-side setting; same authorizer, same channel
                cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,authorization_generation=gen_random_uuid() WHERE workspace_id=%s AND connection_id=%s AND provider='discord'", (workspace, prior['id']))
            connection = stable_id('webhook', workspace, self.adapter.client_id, hook['id'], actor)
            if any(c.get('id') == connection for c in channels): fail('This webhook is already connected.')
            envelope['connectionId'] = connection
            # Passthrough evidence belongs to the webhook, never invented in bearer introspection.
            envelope['authorization'] = {'bearerScopes': scopes, 'webhookScopes': ['webhook.incoming']}
            observed = sorted(set(scopes) | {'webhook.incoming'})
            generation = self.upsert(cur, workspace, connection, hook['id'], envelope, observed)
            now = self.oauth.clock()
            channels.append({'id': connection, 'platform': 'Discord', 'account': 'Rafii webhook · ' + hook['channel_id'],
                'accountType': 'webhook', 'providerAccountId': hook['id'], 'scopes': observed,
                'configured': True, 'identityVerified': True, 'capabilityVerified': False,
                'enabledPermissionGroups': ['identity', 'publish'], 'verifiedAt': now, 'expiresAt': now + 86400 * 365 * 5,
                'capabilityVersion': self.adapter.capability_version, 'evidenceSource': 'live_provider', 'qualification': 'server_verified',
                'discordConnectionKind': 'webhook', 'discordAuthorizedBy': actor, 'discordLinkedUserId': user['id'],
                'discordWebhookChannelId': hook['channel_id'], 'discordAuthorizationGeneration': generation,
                # Only a webhook explicitly bound to a selected identity becomes
                # dependent on its later disconnect/reconnect. Independent
                # webhook grants preserve their own consent lifecycle.
                **({'discordIdentityConnectionId': context['identityConnectionId']}
                   if context.get('identityConnectionId') else {}),
                'discordDestinations': [], 'revoked': False,
                **({'discordSenderName': carried_name, 'discordSenderRevision': str(uuid.uuid4())} if carried_name is not None else {})})
            self.save_state(cur, workspace, state)
        return {'connected': True, 'connectionId': connection, 'discordPurpose': 'webhook', 'senderKind': 'webhook',
                'account': 'Rafii webhook', 'missingScopes': [], 'requiresDestinationAuthorization': True}

    def webhook_authorizer(self, envelope):
        """Resolve only an explicitly bound, current identity; never widen scopes.

        Legacy/independent webhook envelopes keep the existing bot witness path.
        Fresh provider reads and rotating-token refresh happen outside SQL locks.
        The bearer is transient server-side data, never saved with the webhook.
        """
        connection = envelope.get('identityConnectionId')
        if not connection:
            return None
        workspace = envelope.get('workspaceId')

        def bound(cur, state):
            self.validate_webhook(cur, workspace, envelope)
            _, stored = self.read_credential(cur, workspace, envelope.get('connectionId'))
            if any(stored.get(k) != envelope.get(k) for k in ('identityConnectionId', 'identityGeneration', 'user', 'memberId')):
                fail('The webhook identity binding changed. Reconnect it.')
            channel = next(c for c in state['phase2']['channels'] if c['id'] == envelope['connectionId'])
            record = identity_record(state, connection, envelope.get('memberId'))
            row, identity = self.bind_identity(cur, workspace, record)
            if (channel.get('discordIdentityConnectionId') != connection
                    or row[4] != envelope.get('identityGeneration') or identity['user'] != envelope['user']):
                fail('The webhook identity changed. Reconnect it.')
            self.require_active_installation_authorizer(cur, workspace, record)
            return row, identity

        with self.local(workspace, None) as (cur, state, _):
            row, _ = bound(cur, state)
            if 'guilds' not in row[5]:
                return None
        identity = self._fresh_identity(workspace, None, connection)
        with self.local(workspace, None) as (cur, state, _):
            row, current = bound(cur, state)
            if (row[4] != identity['authorizationGeneration'] or current['at'] != identity['bearer']
                    or not row[3] or float(row[3]) <= self.oauth.clock()):
                fail('The webhook identity changed during verification. Reconnect it.')
        return identity

    def reverify_webhook(self, workspace, connection, *, token=None, authenticated=None, actor=None, audit_event=None):
        """Provider read outside SQL; a late success cannot undo newer revocation."""
        from .webhooks import verify
        from ..hosted import audit
        with self.local(workspace, token) as (cur, state, member):
            row, envelope = self.read_credential(cur, workspace, connection)
            self.validate_webhook(cur, workspace, envelope)
            channel = next(c for c in state['phase2']['channels'] if c['id'] == connection)
            before = digest(channel)
            generation = row[4]
            if token is not None and envelope.get('memberId') != member:
                fail('Only the authorizing member can reverify this webhook.', 403)
        failure = None
        try:
            verify(self.adapter, envelope)
        except AlphaError as error:
            failure = error
        with self.local(workspace, token) as (cur, state, member):
            current, fresh = self.read_credential(cur, workspace, connection)
            self.validate_webhook(cur, workspace, fresh)
            channel = next(c for c in state['phase2']['channels'] if c['id'] == connection)
            if current[4] != generation or current[0] != row[0] or digest(channel) != before:
                fail('Webhook changed during verification. Reload.')
            if failure:
                channel['capabilityVerified'] = False
            else:
                # Read proof cannot authorize a new destination or restore a revoked one.
                authorized = any(d.get('status') == 'authorized' and d.get('authorizationGeneration') == generation
                                 for d in channel.get('discordDestinations', []))
                channel.update(identityVerified=True, capabilityVerified=authorized, verifiedAt=self.oauth.clock())
            channel['discordVerificationGeneration'] = str(uuid.uuid4())
            self.save_state(cur, workspace, state)
            audit(cur, workspace, member or actor, audit_event or 'discord.webhook_verified', connection,
                  {'state': 'verification_unavailable' if failure else 'read_verified'})
        if failure: raise failure
        return {'connectionId': connection, 'state': 'read_verified', 'ready': channel['capabilityVerified'],
                'senderKind': 'webhook', 'scopes': list(row[5])}
