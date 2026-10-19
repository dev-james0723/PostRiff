"""Offline Twitch custody and common OAuth integration; synthetic transports only.

SQL fixtures model transaction rollback, tenant predicates and lock ordering.
They are not a substitute for production PostgreSQL/RLS or live Twitch acceptance.
"""
import copy
import hashlib
import json
import threading
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.twitch_oauth import CALLBACK, TwitchProvider

NOW = 1_800_000_000
ACCOUNT = '123456'
CHAT = 'user:write:chat'


class Wire:
    def __init__(self, scopes=()):
        self.calls = []
        self.scopes = list(scopes)
        self.user = ACCOUNT
        self.client = 'twitch-test-client'
        self.profile_user = ACCOUNT
        self.token_status = self.validate_status = self.users_status = 200
        self.token_count = 0
        self.raise_transport = False
        self.expiry = 7200
        self.validate_body = None
        self.refresh_user = None
        self.on_refresh = None

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.raise_transport:
            raise RuntimeError('synthetic secret must not appear in an error')
        if url == TwitchProvider.TOKEN:
            self.token_count += 1
            if kwargs['form']['grant_type'] == 'refresh_token':
                if self.on_refresh:
                    self.on_refresh()
                if self.refresh_user:
                    self.user = self.refresh_user
            return {'status': self.token_status, 'body': {'access_token': 'synthetic-access-' + str(self.token_count),
                'refresh_token': 'synthetic-refresh-' + str(self.token_count),
                'expires_in': self.expiry, 'token_type': 'bearer',
                'scope': [CHAT, 'channel:manage:broadcast']}}  # Deliberately untrusted declared scopes.
        if url == TwitchProvider.VALIDATE:
            body = {'user_id': self.user, 'client_id': self.client, 'login': 'synthetic_user',
                    'scopes': list(self.scopes), 'expires_in': self.expiry}
            if self.validate_body is not None:
                body = self.validate_body
            return {'status': self.validate_status, 'body': body}
        if url == TwitchProvider.USERS:
            return {'status': self.users_status,
                    'body': {'data': [{'id': self.profile_user, 'broadcaster_type': 'affiliate',
                                     'email': 'synthetic-private@example.invalid'}]}}
        if url == TwitchProvider.REVOKE:
            return {'status': 200, 'body': {}}
        raise AssertionError('Unexpected synthetic Twitch route')


def provider(wire=None, **kwargs):
    return TwitchProvider('twitch-test-client', 'synthetic-secret', transport=wire or Wire(),
        clock=lambda: NOW, public_connect_enabled=True, commercial_approved=True, **kwargs)


class Repository:
    """Small semantic SQL fixture, with real lock serialization and rollback."""
    def __init__(self):
        self.states = {'workspace': {'phase2': {'channels': []}}, 'other': {'phase2': {'channels': []}}}
        self.members = {('alice', 'workspace'): ('alice', 'owner'), ('bob', 'workspace'): ('bob', 'admin'),
                        ('alice', 'other'): ('alice', 'owner'), ('viewer', 'workspace'): ('viewer', 'viewer')}
        self.transactions, self.credentials = {}, {}
        self.lock = threading.RLock()
        self.result, self.rowcount = None, 0
        self.sql, self.lock_order, self.completed = [], [], []
        self.before_command = None
        self.assert_fresh = Mock()

    @contextmanager
    def _atomic(self):
        with self.lock:
            snapshot = copy.deepcopy((self.states, self.transactions, self.credentials))
            try:
                yield
            except Exception:
                self.states, self.transactions, self.credentials = snapshot
                raise

    @contextmanager
    def connection_factory(self):
        with self._atomic():
            yield self

    @contextmanager
    def cursor(self):
        yield self

    @contextmanager
    def transaction(self, token, workspace):
        with self._atomic():
            member = self.members.get((token, workspace))
            if not member:
                raise AlphaError('Workspace unavailable.', 404)
            yield self, (1, self.states[workspace], member[1]), member[0]

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        self.result, self.rowcount = None, 0
        if sql.startswith('INSERT INTO public.pr_oauth_transactions'):
            t = {'workspace': params[0], 'actor': params[1], 'provider': params[2], 'capability': params[3],
                 'callback': params[4], 'scopes': params[5], 'hash': params[6], 'verifier': params[7],
                 'key': params[8], 'consumed': False, 'expires': NOW + 600,
                 'id': 'txn-' + str(len(self.transactions) + 1)}
            self.transactions[(params[0], params[6])] = t
            self.result = (t['id'],)
        elif sql.startswith('SELECT id::text,member_id::text,provider,extract'):
            t = self.transactions.get(tuple(params))
            if t:
                self.result = (t['id'], t['actor'], t['provider'], t['expires'], t['consumed'], t['verifier'], t['key'], t['scopes'])
        elif sql.startswith('SELECT id::text,member_id::text,provider,capability'):
            t = self.transactions.get((params[1], params[0]))
            if t:
                self.result = (t['id'], t['actor'], t['provider'], t['capability'], t['callback'], t['scopes'],
                               t['verifier'], t['key'], t['expires'], t['consumed'])
        elif sql.startswith('UPDATE public.pr_oauth_transactions'):
            for t in self.transactions.values():
                if t['id'] == params[0]:
                    t['consumed'] = True
        elif sql.startswith('SELECT provider_account_id,scopes FROM'):
            c = self.credentials.get(tuple(params))
            if c and c['provider'] == 'twitch':
                self.result = (c['account'], c['scopes'])
        elif sql.startswith('INSERT INTO public.pr_encrypted_credentials'):
            self.credentials[(params[0], params[1])] = dict(provider=params[2], account=params[3],
                access=params[4], refresh=params[5], key=params[6], scopes=params[7], expires=params[8],
                refresh_supported=params[9], revoked=False)
        elif sql.startswith('INSERT INTO public.pr_channel_capabilities') or sql.startswith('UPDATE public.pr_channel_capabilities'):
            pass
        elif sql.startswith('SELECT connection_id,capability,level,evidence'):
            self.result = []
        elif sql.startswith('SELECT workspace_id::text,connection_id,refresh_supported'):
            self.result = []
            if "provider='twitch'" in sql:
                self.result = [(ws, conn, c['refresh_supported'], bool(c['refresh']), c['expires'], c['revoked'],
                                c['scopes'], c['account'], c['access'], c['key'])
                               for (ws, conn), c in self.credentials.items() if ws in params[0] and c['provider'] == 'twitch']
        elif sql.startswith('SELECT id FROM public.pr_workspaces'):
            self.lock_order.append('workspace')
            self.result = (params[0],) if params[0] in self.states else None
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.lock_order.append('workspace')
            self.result = (self.states[params[0]],) if params[0] in self.states else None
        elif sql.startswith('SELECT workspace_id::text,connection_id FROM'):
            keys = sorted(k for k, c in self.credentials.items() if not c['revoked'] and c['provider'] == 'twitch')
            if len(params) == 3:
                keys = [k for k in keys if k > tuple(params[:2])]
            self.result = keys[:params[-1]]
        elif sql.startswith('SELECT provider FROM public.pr_encrypted_credentials'):
            c = self.credentials.get(tuple(params))
            self.result = (c['provider'],) if c and not c['revoked'] else None
        elif sql.startswith('SELECT provider,access_ciphertext,refresh_ciphertext'):
            self.lock_order.append('credential')
            assert self.lock_order[-2:] == ['workspace', 'credential']
            c = self.credentials.get(tuple(params))
            if c:
                self.result = (c['provider'], c['access'], c['refresh'], c['key'], c['expires'],
                               c['refresh_supported'], c['revoked'], c['scopes'], c['account'], NOW - 3600)
        elif sql.startswith('SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials'):
            self.lock_order.append('credential')
            c = self.credentials.get(tuple(params))
            if c and not c['revoked']:
                self.result = (c['access'], c['key'])
        elif sql.startswith('SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials'):
            c = self.credentials.get(tuple(params))
            if c and not c['revoked']:
                self.result = (c['provider'], c['access'], c['key'])
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET access_ciphertext='):
            c = self.credentials[tuple(params[-2:])]
            c.update(access=params[0], refresh=params[1], key=params[2], expires=params[3])
            self.rowcount = 1
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET scopes='):
            c = self.credentials[tuple(params[-2:])]
            c.update(scopes=params[0], expires=params[1])
            self.rowcount = 1
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET revoked_at='):
            c = self.credentials[tuple(params)]
            c.update(revoked=True, access='', refresh=None)
            if "scopes='{}'" in sql:
                c.update(scopes=[], refresh_supported=False)
            self.rowcount = 1
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.states[params[-1]] = json.loads(params[0])
            self.rowcount = 1
        else:
            raise AssertionError('Unexpected custody SQL: ' + sql[:100])

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def get(self, workspace, token):
        if (token, workspace) not in self.members:
            raise AlphaError('Workspace unavailable.', 404)
        return {'revision': 1, 'state': copy.deepcopy(self.states[workspace])}

    def command(self, workspace, token, revision, change, **kwargs):
        if self.before_command:
            self.before_command()
        with self.transaction(token, workspace) as (cur, _, principal):
            change(self.states[workspace], principal)
            if kwargs.get('after'):
                kwargs['after'](cur, self.states[workspace], principal)
        return self.get(workspace, token)


class TwitchProviderTests(unittest.TestCase):
    def test_defaults_cannot_start_or_exchange(self):
        wire = Wire()
        p = TwitchProvider('client', 'secret', transport=wire)
        with self.assertRaises(AlphaError):
            p.exchange('code', 'ignored-verifier', CALLBACK)
        self.assertEqual(wire.calls, [])

    def test_registry_requires_both_independent_flags(self):
        for connect, commercial in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(connect=connect, commercial=commercial):
                values = {'POSTRIFF_OAUTH_TWITCH_CLIENT_ID': 'client', 'POSTRIFF_OAUTH_TWITCH_CLIENT_SECRET': 'secret',
                          'RAFII_TWITCH_PUBLIC_CONNECT': str(connect).lower(),
                          'RAFII_TWITCH_COMMERCIAL_APPROVED': str(commercial).lower(),
                          'POSTRIFF_OAUTH_TWITCH_ENABLED': 'true', 'POSTRIFF_OAUTH_TWITCH_REVIEWED': 'true'}
                registry = registry_from_environment(values, transport=Wire())
                self.assertEqual(registry['twitch'].execution_enabled, connect and commercial)
                self.assertEqual(registry.diagnostics['twitch']['productionEnabled'], connect and commercial)

    def test_malformed_credentials_do_not_mount_or_leak(self):
        r = registry_from_environment({'POSTRIFF_OAUTH_TWITCH_CLIENT_ID': 'private client with spaces',
            'POSTRIFF_OAUTH_TWITCH_CLIENT_SECRET': 'private-secret'}, transport=Wire())
        self.assertNotIn('twitch', r)
        self.assertNotIn('private', json.dumps(r.diagnostics))

    def test_callback_is_exact_and_ignores_request_input(self):
        for bad in ('http://rafii.io/api/oauth/twitch/callback', CALLBACK + '?x=1', CALLBACK + '/',
                    'https://rafii.io.attacker.invalid/api/oauth/twitch/callback',
                    'https://rafii.io:443/api/oauth/twitch/callback', 'https://preview.example/api/oauth/twitch/callback'):
            with self.subTest(callback=bad), self.assertRaises(AlphaError):
                provider().authorize_url(bad, 's' * 32, 'unused', [])

    def test_cold_callback_and_authorization_use_the_same_canonical_origin(self):
        for origin in ('https://preview.example', 'https://rafii.io.attacker.invalid', 'https://rafii.io:443', 'http://rafii.io', ''):
            oauth = OAuthService(None, None, None, {'twitch': provider()}, origin)
            with self.subTest(origin=origin):
                with self.assertRaises(AlphaError):
                    oauth.callback_uri('twitch')
                with self.assertRaises(AlphaError):
                    OAuthService(None, None, None, {}, origin).callback_base_url('twitch')
        cold = OAuthService(None, None, None, {}, 'https://rafii.io')
        self.assertEqual(cold.callback_base_url('twitch'), 'https://rafii.io')
        self.assertEqual(cold.callback_uri('twitch'), CALLBACK)

    def test_registry_rejects_conflicting_callback_pin(self):
        base = {'POSTRIFF_OAUTH_TWITCH_CLIENT_ID': 'client', 'POSTRIFF_OAUTH_TWITCH_CLIENT_SECRET': 'secret'}
        for key in ('POSTRIFF_OAUTH_TWITCH_REDIRECT_URI', 'POSTRIFF_OAUTH_TWITCH_CALLBACK_ORIGIN'):
            r = registry_from_environment({**base, key: 'https://other.invalid'}, transport=Wire())
            self.assertNotIn('twitch', r)

    def test_minimal_identity_authorize_has_no_pkce_or_email(self):
        p = provider()
        q = parse_qs(urlsplit(p.authorize_url(CALLBACK, 's' * 32, 'not-sent', [])).query, keep_blank_values=True)
        self.assertEqual(q['scope'], [''])
        self.assertEqual(q['response_type'], ['code'])
        self.assertEqual(q['force_verify'], ['true'])
        self.assertFalse({'code_challenge', 'code_challenge_method', 'nonce'} & set(q))

    def test_progressive_native_scopes_only(self):
        p = provider()
        self.assertEqual(p.capability_scopes('twitch.chat.send'), [CHAT])
        q = parse_qs(urlsplit(p.authorize_url(CALLBACK, 's' * 32, 'unused', [CHAT])).query)
        self.assertEqual(q['scope'], [CHAT])
        with self.assertRaises(AlphaError):
            p.authorize_url(CALLBACK, 's' * 32, 'unused', ['made:up:scope'])
        self.assertEqual(p.capability_scopes('publish'), [])
        self.assertFalse(p.supports_capability('twitch.fake.feed.post'))

    def test_eventsub_consent_is_selected_subtype_only(self):
        from postriff_phase2.twitch_eventsub import EVENT_TYPES
        p = provider()
        for name, spec in EVENT_TYPES.items():
            capability = 'twitch.eventsub.subscribe.' + name
            with self.subTest(event=name):
                self.assertTrue(p.supports_capability(capability))
                self.assertEqual(set(p.capability_scopes(capability)), set(spec['scopes']))
                url = p.authorize_url(CALLBACK, 's' * 32, 'unused', p.capability_scopes(capability))
                self.assertIn('client_id=', url)
        self.assertFalse(p.supports_capability('twitch.eventsub.subscribe.nonexistent.event'))
        self.assertFalse(p.supports_capability('twitch.eventsub.subscribe'))

    def test_envelope_version_must_be_an_integer(self):
        p = provider()
        envelope = json.loads(p.exchange('code', 'unused', CALLBACK)['accessToken'])
        envelope['v'] = True
        with self.assertRaises(AlphaError):
            p.raw_access_token(json.dumps(envelope))

    def test_exchange_uses_validate_scopes_and_seals_both_tokens(self):
        wire = Wire([])
        p = provider(wire)
        grant = p.exchange('code', 'server-verifier', CALLBACK)
        self.assertEqual(grant['scopes'], [])
        self.assertEqual(grant['providerAccountId'], ACCOUNT)
        access, refresh = json.loads(grant['accessToken']), json.loads(grant['refreshToken'])
        self.assertEqual(access['generation'], refresh['generation'])
        self.assertEqual(access['clientId'], p.client_id)
        self.assertEqual(access['sub'], ACCOUNT)
        self.assertNotIn('server-verifier', json.dumps(wire.calls))
        vault = CredentialVault(CredentialVault.generate_key())
        for secret in (grant['accessToken'], grant['refreshToken']):
            ct, key = vault.encrypt(secret)
            self.assertNotIn('synthetic', ct)
            self.assertEqual(vault.decrypt(ct, key), secret)

    def test_wrong_client_rejected_before_helix_identity(self):
        wire = Wire()
        wire.client = 'different-client'
        with self.assertRaises(AlphaError) as exc:
            provider(wire).exchange('code', 'unused', CALLBACK)
        self.assertEqual(exc.exception.code, 'twitch_revoked_oauth')
        self.assertNotIn(TwitchProvider.USERS, [call[1] for call in wire.calls])

    def test_app_token_without_user_cannot_be_a_user_connection(self):
        wire = Wire()
        wire.user = None
        with self.assertRaises(AlphaError):
            provider(wire).exchange('code', 'unused', CALLBACK)

    def test_identity_checks_token_subject_and_never_returns_email(self):
        wire = Wire()
        p = provider(wire)
        grant = p.exchange('code', 'unused', CALLBACK)
        ident = p.identity(grant['accessToken'])
        self.assertEqual(ident, {'providerAccountId': ACCOUNT, 'handle': '@synthetic_user', 'accountType': 'affiliate'})
        wire.profile_user = '9999'
        with self.assertRaises(AlphaError):
            p.identity(grant['accessToken'])

    def test_token_validation_subject_matches_saved_connection(self):
        p = provider()
        grant = p.exchange('code', 'unused', CALLBACK)
        with self.assertRaises(AlphaError):
            p.inspect_scopes(grant['accessToken'], '9999')

    def test_refresh_preserves_generation_and_subject(self):
        wire = Wire([CHAT])
        p = provider(wire)
        grant = p.exchange('code', 'unused', CALLBACK)
        refreshed = p.refresh(grant['refreshToken'])
        self.assertEqual(refreshed['authorizationGeneration'], grant['authorizationGeneration'])
        self.assertNotEqual(refreshed['accessToken'], grant['accessToken'])
        self.assertNotEqual(refreshed['refreshToken'], grant['refreshToken'])

    def test_refresh_rejects_changed_subject(self):
        wire = Wire()
        p = provider(wire)
        grant = p.exchange('code', 'unused', CALLBACK)
        wire.refresh_user = '9999'
        with self.assertRaises(AlphaError):
            p.refresh(grant['refreshToken'])

    def test_refresh_and_access_envelopes_cannot_be_swapped(self):
        p = provider()
        grant = p.exchange('code', 'unused', CALLBACK)
        with self.assertRaises(AlphaError):
            p.refresh(grant['accessToken'])
        with self.assertRaises(AlphaError):
            p.raw_access_token(grant['refreshToken'])
        with self.assertRaises(AlphaError):
            p.refresh('raw-refresh-is-unbound')

    def test_client_rotation_rejects_old_vault_envelope_without_network(self):
        old = provider().exchange('code', 'unused', CALLBACK)
        wire = Wire()
        new = TwitchProvider('new-client', 'secret', transport=wire,
                             public_connect_enabled=True, commercial_approved=True)
        with self.assertRaises(AlphaError):
            new.refresh(old['refreshToken'])
        self.assertEqual(wire.calls, [])

    def test_token_shapes_and_scope_shapes_fail_closed(self):
        for patch_body in ({'scopes': 'user:write:chat'}, {'scopes': [None]}, {'expires_in': True},
                           {'expires_in': 0}, {'user_id': 123}, {'login': 'bad\nlogin'}):
            wire = Wire()
            wire.validate_body = {'user_id': ACCOUNT, 'client_id': 'twitch-test-client',
                'login': 'synthetic_user', 'scopes': [], 'expires_in': 7200, **patch_body}
            with self.subTest(body=patch_body), self.assertRaises(AlphaError):
                provider(wire).exchange('code', 'unused', CALLBACK)

    def test_transport_error_and_upstream_body_are_not_exposed(self):
        wire = Wire()
        wire.raise_transport = True
        with self.assertRaises(AlphaError) as exc:
            provider(wire).exchange('synthetic-code', 'unused', CALLBACK)
        self.assertNotIn('synthetic', str(exc.exception))
        self.assertEqual(exc.exception.code, 'twitch_validation_unavailable')

    def test_cleanup_revoke_allowed_even_while_release_paused(self):
        wire = Wire()
        p = provider(wire)
        grant = p.exchange('code', 'unused', CALLBACK)
        p.execution_enabled = False
        self.assertTrue(p.revoke(grant['accessToken']))
        call = wire.calls[-1]
        self.assertEqual(call[1], TwitchProvider.REVOKE)
        self.assertEqual(call[2]['form'], {'client_id': p.client_id, 'token': 'synthetic-access-1'})


class TwitchCustodyTests(unittest.TestCase):
    def setUp(self):
        self.wire = Wire()
        self.provider = provider(self.wire)
        self.repository = Repository()
        self.vault = CredentialVault(CredentialVault.generate_key())
        commands = SimpleNamespace(upsert_verified_channel=self._upsert, engine=SimpleNamespace(invalidate=lambda _: None))
        self.service = OAuthService(self.repository, commands, self.vault, {'twitch': self.provider},
                                    'https://rafii.io', clock=lambda: NOW)
        self.events = []
        self.service.twitch_lifecycle = lambda _cur, ws, conn, event, gen: self.events.append((ws, conn, event, gen))
        self.service._keep_picture = Mock()
        for target in ('postriff_phase2.hosted.audit', 'postriff_phase2.hosted.throttle',
                       'postriff_phase2.billing.require_plan_capacity', 'postriff_phase2.product_events.record',
                       'postriff_phase2.account_pictures.guarded', 'postriff_phase2.growth.history_import.mark_for_purge',
                       'postriff_phase2.growth.history_import.purge_after_disconnect'):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _upsert(state, actor, channel, **_kwargs):
        state['phase2']['channels'] = [item for item in state['phase2']['channels'] if item['id'] != channel['id']]
        state['phase2']['channels'].append({**channel, 'configured': True, 'identityVerified': True, 'revoked': False})

    def start(self, capability='identity', inputs=None):
        started = self.service.start('workspace', 'alice', 'twitch', capability, inputs)
        state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
        return started, state

    def connect(self, capability='identity'):
        _, state = self.start(capability)
        return self.service.complete('workspace', 'alice', 'twitch', state, 'synthetic-code')

    def stored(self, connection_id):
        return self.repository.credentials[('workspace', connection_id)]

    def test_common_flow_encrypts_tokens_and_returns_no_credentials(self):
        result = self.connect()
        stored = self.stored(result['connectionId'])
        self.assertNotIn('synthetic-access', stored['access'])
        self.assertNotIn('synthetic-refresh', stored['refresh'])
        self.assertNotIn('accessToken', json.dumps(result))
        self.assertNotIn('refreshToken', json.dumps(result))
        self.assertEqual(result['capabilities']['identity']['level'], 'Direct')
        self.assertEqual(result['capabilities']['publish']['level'], 'Unsupported')
        self.assertEqual(result['capabilities']['schedule']['level'], 'Unsupported')
        self.assertEqual(self.events[-1][2], 'connected')

    def test_cross_workspace_callback_cannot_exchange(self):
        _, state = self.start()
        with self.assertRaises(AlphaError) as exc:
            self.service.complete('other', 'alice', 'twitch', state, 'code')
        self.assertEqual(exc.exception.status, 404)
        self.assertEqual(self.wire.calls, [])
        self.assertFalse(next(iter(self.repository.transactions.values()))['consumed'])

    def test_other_member_callback_cannot_exchange(self):
        _, state = self.start()
        with self.assertRaises(AlphaError):
            self.service.complete('workspace', 'bob', 'twitch', state, 'code')
        self.assertEqual(self.wire.calls, [])

    def test_viewer_cannot_request_native_scopes(self):
        with self.assertRaises(AlphaError) as exc:
            self.service.start('workspace', 'viewer', 'twitch', 'twitch.chat.send')
        self.assertEqual(exc.exception.status, 403)
        self.assertEqual(self.repository.transactions, {})

    def test_state_replay_never_reexchanges(self):
        _, state = self.start()
        self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        count = len(self.wire.calls)
        with self.assertRaises(AlphaError):
            self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertEqual(len(self.wire.calls), count)

    def test_failed_provider_exchange_stays_consumed(self):
        _, state = self.start()
        self.wire.token_status = 503
        with self.assertRaises(AlphaError):
            self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertTrue(next(iter(self.repository.transactions.values()))['consumed'])
        self.wire.token_status = 200
        with self.assertRaises(AlphaError):
            self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertEqual(self.repository.credentials, {})
        self.assertEqual(self.wire.token_count, 1)

    def test_configuration_change_after_start_rejected_before_exchange(self):
        _, state = self.start()
        self.provider.client_id = 'replacement-client'
        with self.assertRaises(AlphaError):
            self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertEqual(self.wire.calls, [])

    def test_reconnect_is_bound_to_selected_account(self):
        first = self.connect()
        original = copy.deepcopy(self.stored(first['connectionId']))
        _, state = self.start('twitch.chat.send', {'connectionId': first['connectionId']})
        self.wire.user = self.wire.profile_user = '99999'
        with self.assertRaises(AlphaError) as exc:
            self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertEqual(exc.exception.code, 'twitch_account_changed')
        self.assertEqual(self.stored(first['connectionId']), original)
        self.assertEqual(len(self.repository.credentials), 1)

    def test_native_upgrade_preserves_and_displays_old_granted_scopes(self):
        self.wire.scopes = ['channel:manage:broadcast']
        first = self.connect('twitch.channel.update')
        started, _ = self.start('twitch.chat.send', {'connectionId': first['connectionId']})
        self.assertEqual(set(started['scopes']), {CHAT, 'channel:manage:broadcast'})
        self.assertNotIn('moderator:manage:banned_users', started['scopes'])

    def test_foreign_connection_id_does_not_expand_scopes(self):
        with self.assertRaises(AlphaError):
            self.start('twitch.chat.send', {'connectionId': 'unknown-other-workspace'})
        self.assertEqual(self.repository.transactions, {})

    def test_reconnect_replaces_consent_generation(self):
        first = self.connect()
        first_generation = self.events[-1][3]
        _, state = self.start('identity', {'connectionId': first['connectionId']})
        second = self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertEqual(second['connectionId'], first['connectionId'])
        self.assertNotEqual(first_generation, self.events[-1][3])

    def test_disconnect_before_profile_save_prevents_stale_restoration(self):
        _, state = self.start()
        def revoke():
            for c in self.repository.credentials.values():
                c['revoked'] = True
        self.repository.before_command = revoke
        with self.assertRaises(AlphaError) as exc:
            self.service.complete('workspace', 'alice', 'twitch', state, 'code')
        self.assertEqual(exc.exception.code, 'twitch_connection_changed')
        self.assertEqual(self.repository.states['workspace']['phase2']['channels'], [])

    def test_every_worker_access_validates_including_new_process(self):
        result = self.connect()
        before = len([c for c in self.wire.calls if c[1] == TwitchProvider.VALIDATE])
        one = self.service.token_for_worker('workspace', result['connectionId'])
        two = self.service.token_for_worker('workspace', result['connectionId'])
        self.assertEqual(len([c for c in self.wire.calls if c[1] == TwitchProvider.VALIDATE]), before + 2)
        self.assertEqual(one['authorizationGeneration'], two['authorizationGeneration'])
        self.assertEqual(one['nextValidationAt'], NOW + 3600)

    def test_expired_token_rotates_both_credentials_atomically(self):
        result = self.connect()
        stored = self.stored(result['connectionId'])
        before = copy.deepcopy(stored)
        stored['expires'] = NOW - 1
        grant = self.service.token_for_worker('workspace', result['connectionId'])
        after = self.stored(result['connectionId'])
        self.assertNotEqual(after['access'], before['access'])
        self.assertNotEqual(after['refresh'], before['refresh'])
        self.assertEqual(grant['authorizationGeneration'], self.provider.credential_generation(self.vault.decrypt(before['access'], before['key'])))
        self.assertEqual(after['expires'], NOW + self.wire.expiry)

    def test_concurrent_refresh_is_serialized_once(self):
        result = self.connect()
        self.stored(result['connectionId'])['expires'] = NOW - 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.service.token_for_worker, 'workspace', result['connectionId']) for _ in range(2)]
            grants = [f.result() for f in futures]
        self.assertEqual(self.wire.token_count, 2)  # one original exchange + one refresh
        self.assertEqual(grants[0]['accessToken'], grants[1]['accessToken'])

    def test_wrong_refresh_subject_invalidates_only_local_generation(self):
        result = self.connect()
        self.stored(result['connectionId'])['expires'] = NOW - 1
        self.wire.refresh_user = '99999'
        with self.assertRaises(AlphaError):
            self.service.token_for_worker('workspace', result['connectionId'])
        self.assertTrue(self.stored(result['connectionId'])['revoked'])
        self.assertEqual(self.events[-1][2], 'revoked')
        self.assertEqual(self.repository.states['workspace']['phase2']['channels'][0]['scopes'], [])

    def test_new_consent_cannot_be_erased_by_stale_revocation(self):
        first = self.connect()
        old = self.stored(first['connectionId'])['access']
        self.connect()
        current = copy.deepcopy(self.stored(first['connectionId']))
        self.assertFalse(self.service.mark_twitch_revoked('workspace', first['connectionId'], expected_ciphertext=old))
        self.assertEqual(self.stored(first['connectionId']), current)

    def test_scope_loss_is_recorded_and_invalidates_queued_authority(self):
        self.wire.scopes = [CHAT]
        result = self.connect('twitch.chat.send')
        self.wire.scopes = []
        grant = self.service.token_for_worker('workspace', result['connectionId'])
        self.assertEqual(grant['scopes'], [])
        self.assertEqual(self.stored(result['connectionId'])['scopes'], [])
        self.assertEqual(self.events[-1][2], 'scope_changed')

    def test_transient_validation_failure_preserves_tokens_and_scopes(self):
        self.wire.scopes = [CHAT]
        result = self.connect('twitch.chat.send')
        before = copy.deepcopy(self.stored(result['connectionId']))
        self.wire.validate_status = 503
        with self.assertRaises(AlphaError) as exc:
            self.service.token_for_worker('workspace', result['connectionId'])
        self.assertEqual(exc.exception.code, 'twitch_validation_unavailable')
        self.assertEqual(self.stored(result['connectionId']), before)

    def test_revoked_refresh_persists_local_disconnect(self):
        result = self.connect()
        self.stored(result['connectionId'])['expires'] = NOW - 1
        self.wire.token_status = 400
        with self.assertRaises(AlphaError):
            self.service.token_for_worker('workspace', result['connectionId'])
        stored = self.stored(result['connectionId'])
        self.assertTrue(stored['revoked'])
        self.assertIsNone(stored['refresh'])
        self.assertEqual(stored['access'], '')

    def test_disconnected_token_is_unavailable_across_tenants(self):
        result = self.connect()
        before = len(self.wire.calls)
        with self.assertRaises(AlphaError):
            self.service._twitch_token_for_worker('other', result['connectionId'])
        self.assertEqual(len(self.wire.calls), before)

    def test_hourly_sweep_validates_active_and_never_calls_when_paused(self):
        self.connect()
        outcome = self.service.validate_twitch_connections(limit=1)
        self.assertEqual(outcome, {'validated': 1, 'blocked': 0, 'next': None, 'enabled': True})
        count = len(self.wire.calls)
        self.provider.execution_enabled = False
        self.assertEqual(self.service.validate_twitch_connections()['validated'], 0)
        self.assertEqual(len(self.wire.calls), count)

    def test_disconnect_revokes_refresh_custody_and_native_jobs_atomically(self):
        result = self.connect()
        answer = self.service.disconnect('workspace', 'alice', result['connectionId'])
        self.assertTrue(answer['disconnected'])
        self.assertTrue(answer['remoteRevoked'])
        self.assertIsNone(self.stored(result['connectionId'])['refresh'])
        self.assertEqual(self.events[-1][2], 'disconnected')
        self.assertTrue(self.repository.states['workspace']['phase2']['channels'][0]['revoked'])
        self.repository.assert_fresh.assert_called_once_with('alice', 'alice')

    def channel_view(self):
        with patch('postriff_phase2.account_pictures.guarded', return_value=None):
            return self.service.channels('workspace', 'alice')['channels'][0]

    def test_channels_project_current_expiry_refresh_and_scope_loss_without_network(self):
        self.wire.scopes = [CHAT]
        result = self.connect('twitch.chat.send')
        persisted = self.repository.states['workspace']['phase2']['channels'][0]
        persisted['expiresAt'] = NOW - 600
        self.wire.scopes = []
        self.service.token_for_worker('workspace', result['connectionId'])
        before = len(self.wire.calls)
        view = self.channel_view()
        self.assertEqual(view['connectionState'], 'read_verified')
        self.assertTrue(view['refreshSupported'])
        self.assertEqual(view['accessTokenExpiresAt'], NOW + 7200)
        self.assertEqual(view['scopes'], [])
        self.assertEqual(len(self.wire.calls), before)
        self.assertNotIn('synthetic-access', json.dumps(view))
        self.assertEqual(persisted['expiresAt'], NOW - 600)  # projection did not mutate shared state

    def test_expired_twitch_access_is_refreshable_without_inventing_publish(self):
        result = self.connect()
        self.stored(result['connectionId'])['expires'] = NOW - 1
        view = self.channel_view()
        self.assertEqual(view['connectionState'], 'read_verified')
        self.assertTrue(view['refreshSupported'])
        self.assertEqual(view['capabilities']['publish']['level'], 'Unsupported')
        self.assertEqual(view['capabilities']['schedule']['level'], 'Unsupported')

    def test_missing_refresh_does_not_hide_expired_access(self):
        result = self.connect()
        self.stored(result['connectionId']).update(refresh=None, expires=NOW - 1)
        view = self.channel_view()
        self.assertFalse(view['refreshSupported'])
        self.assertEqual(view['connectionState'], 'token_expired')

    def test_stale_channel_cannot_hide_revoked_or_missing_custody(self):
        result = self.connect()
        stored = self.stored(result['connectionId'])
        stored['revoked'] = True
        view = self.channel_view()
        self.assertEqual(view['connectionState'], 'reauthorization_required')
        self.assertFalse(view['refreshSupported'])
        self.assertEqual(view['scopes'], [])
        del self.repository.credentials[('workspace', result['connectionId'])]
        self.assertEqual(self.channel_view()['connectionState'], 'reauthorization_required')

    def test_app_rotation_projects_reconnect_without_exposing_or_using_old_tokens(self):
        result = self.connect()
        stored = copy.deepcopy(self.stored(result['connectionId']))
        self.provider.client_id = 'new-client'
        before = len(self.wire.calls)
        view = self.channel_view()
        self.assertEqual(view['connectionState'], 'client_binding_missing')
        self.assertFalse(view['refreshSupported'])
        self.assertTrue(view['refreshBindingRequired'])
        self.assertEqual(view['scopes'], [])
        self.assertEqual(self.stored(result['connectionId']), stored)
        self.assertEqual(len(self.wire.calls), before)

    def test_current_twitch_metadata_remains_workspace_bound(self):
        result = self.connect()
        foreign = copy.deepcopy(self.stored(result['connectionId']))
        foreign.update(scopes=['foreign:scope'], expires=NOW + 999999)
        self.repository.credentials[('other', result['connectionId'])] = foreign
        view = self.channel_view()
        self.assertNotIn('foreign:scope', view['scopes'])
        self.assertEqual(view['expiresAt'], NOW + 7200)


if __name__ == '__main__':
    unittest.main()
