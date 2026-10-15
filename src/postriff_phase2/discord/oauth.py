"""Discord identity, installation and destination custody in Rafii's existing DB.

No new tables, provider secrets, scheduler or inbound events. Network calls take
place between short workspace transactions. Ordinary refresh preserves consent
generation; reconnect/revocation fences every dependent installation.
"""
import copy
import hashlib
import json
import math
import secrets
import uuid
from contextlib import contextmanager
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from .authorization import digest, snowflake


def fail(message='Reconnect Discord and authorize the server and channel again.', status=409):
    raise AlphaError(message, status, code='discord_connection_required')


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
    expected = ['identify', 'guilds'] if purpose == 'identity' and context.get('discoverGuilds') else ['identify'] if purpose == 'identity' else ['identify', 'bot']
    if (purpose not in ('identity', 'installation') or context.get('v') != 1
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
            raise error
        return response.get('body')

    def verified_user(self, bearer, required, user_id=None):
        info = self._response('GET', '/oauth2/@me', bearer, user_id=user_id)
        verified_id = (info.get('user') or {}).get('id') if isinstance(info, dict) else None
        if not snowflake(verified_id) or user_id is not None and verified_id != user_id:
            fail('Discord did not verify the expected identity.')
        user = self._response('GET', '/users/@me', bearer, user_id=verified_id)
        if (not isinstance(info, dict) or not isinstance(user, dict)
                or (info.get('application') or {}).get('id') != self.adapter.client_id
                or not snowflake(user.get('id')) or (info.get('user') or {}).get('id') != user['id']
                or not isinstance(info.get('scopes'), list) or not set(required).issubset(info['scopes'])):
            fail('Discord did not verify the requested identity and application.')
        return user, list(info['scopes'])

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
        if purpose not in ('identity', 'installation') or capability != ('identity' if purpose == 'identity' else 'publish'):
            fail('Choose identity linking or server installation.', 400)
        discover = inputs.get('discoverGuilds') is True
        scopes = ['identify', 'guilds'] if purpose == 'identity' and discover else ['identify'] if purpose == 'identity' else ['identify', 'bot']
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
            if purpose == 'installation':
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
            state_value = secrets.token_urlsafe(32)
            ciphertext, key = self.oauth.vault.encrypt(json.dumps(context))
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,'discord',%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>600)) RETURNING id::text", (workspace, actor, capability, redirect, scopes, hashlib.sha256(state_value.encode()).hexdigest(), ciphertext, key))
            transaction = cur.fetchone()[0]
            audit(cur, workspace, actor, 'oauth.started', transaction, {'provider': 'discord', 'purpose': purpose})
        params = {'client_id': adapter.client_id, 'response_type': 'code', 'redirect_uri': redirect,
                  'scope': ' '.join(scopes), 'state': state_value}
        if purpose == 'installation':
            params.update(permissions=str(adapter.PERMISSIONS), integration_type='0', guild_id=inputs['guildId'], disable_guild_select='true')
        return {'transactionId': transaction, 'provider': 'discord', 'platform': 'Discord', 'capability': capability,
                'discordPurpose': purpose, 'scopes': scopes, 'expiresAt': self.oauth.clock() + 600,
                'permissionExplanation': 'Link your Discord identity and selected server permissions.' if purpose == 'identity' else 'Install Rafii’s bot in the selected server. Authorize each channel separately.',
                'authorizeUrl': adapter.AUTH + '?' + urlencode(params)}

    def complete(self, workspace, token, state_value, code, error=None):
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
            if row[3] != context['redirectUri']:
                fail('The Discord callback changed. Start again.')
            cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome=%s WHERE id::text=%s", ('denied' if error or not code else 'exchange_started', row[0]))
            audit(cur, workspace, actor, 'oauth.exchange_claimed', row[0], {'provider': 'discord', 'purpose': purpose})
        # Committed single use BEFORE provider exchange, including ambiguous failures.
        if error or not code:
            return {'connected': False, 'reason': 'denied', 'discordPurpose': purpose}
        if purpose == 'installation' and not context.get('connectionId'):
            self.oauth._admit_identity(workspace, adapter)
        body = self.token_body(self._response('POST', '/oauth2/token', form={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': context['redirectUri']}))
        user, scopes = self.verified_user(body['access_token'], row[4], context.get('expectedUserId') or context.get('userId'))
        if context.get('expectedUserId') and user['id'] != context['expectedUserId']:
            fail('Reconnect the original Discord identity.')
        if purpose == 'installation':
            if user['id'] != context.get('userId') or (body.get('guild') or {}).get('id') != context.get('guildId'):
                fail('Discord authorized a different identity or server. Start again.')
            envelope = {'v': 2, 'kind': 'installation', 'applicationId': adapter.client_id,
                        'botUserId': adapter._bot_identity(), 'user': user['id'], 'guild': context['guildId'], 'channel': None,
                        'identityConnectionId': context['identityConnectionId'], 'identityGeneration': context['identityGeneration']}
            guild = adapter._json(adapter._bot('GET', '/guilds/' + context['guildId']), dict)
            if guild.get('id') != context['guildId']:
                fail()
            # Fresh bot/user membership and effective permissions; channel consent stays independent.
            adapter.destinations(json.dumps(envelope))
            result = self.save_installation(workspace, token, context, envelope, scopes, guild)
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
        return {'connected': True, 'connectionId': connection, 'account': record['account'], 'discordPurpose': 'identity', 'missingScopes': []}

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
                user, _ = self.verified_user(fast['bearer'], fast['scopes'], fast['userId'])
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
        # Never retry an ambiguous rotating-token exchange automatically.
        try:
            body = self.token_body(self._response('POST', '/oauth2/token', user_id=envelope['user'], form={'grant_type': 'refresh_token', 'refresh_token': refresh}))
            user, scopes = self.verified_user(body['access_token'], row[5], envelope['user'])
            if user['id'] != envelope['user']:
                fail('Discord refreshed a different identity. Reconnect.')
        except Exception:
            with self.local(workspace, token) as (cur, state, actor):
                record = identity_record(state, connection, actor)
                if record.get('refreshClaim') == claim and record.get('authorizationGeneration') == row[4]:
                    record['status'] = 'reconnect_required'
                    self.invalidate_dependents(cur, workspace, state, connection)
                    self.save_state(cur, workspace, state)
            fail('Discord refresh could not be confirmed. Reconnect before publishing.')
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
        with self.oauth.repository.transaction(token, workspace) as (_, row, actor):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            return [{k: x[k] for k in ('id', 'account', 'userId', 'status', 'expiresAt', 'discoverGuilds') if k in x}
                    for x in state.get('phase2', {}).get('discordIdentityLinks', []) if x.get('authorizedBy') == actor]

    def installation_identity(self, workspace, connection):
        with self.local(workspace, None) as (cur, _, _):
            _, envelope = self.read_credential(cur, workspace, connection)
            if envelope.get('kind') != 'installation' or not envelope.get('identityConnectionId'):
                fail('Reconnect this legacy installation through a linked Discord identity.')
        self._fresh_identity(workspace, None, envelope['identityConnectionId'])

    def validate_installation(self, cur, workspace, envelope):
        if envelope.get('kind') != 'installation' or not envelope.get('identityConnectionId'):
            fail('An identity grant cannot publish. Reconnect the server installation.')
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
        row = cur.fetchone()
        if not row:
            fail()
        state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        record = identity_record(state, envelope['identityConnectionId'])
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
