"""Synthetic lifecycle boundaries. Full execution belongs in approved cloud CI."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord.oauth import DiscordConnections, stable_id, validate_context
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import SyntheticWire, APP, BOT, USER, GUILD, NOW, WORKSPACE, ACTOR

SECOND_GUILD = '666666'


class LifecycleWire(SyntheticWire):
    def __init__(self):
        super().__init__()
        self.lifecycle_calls = []
        self.tokens = {}
        self.refresh_count = 0
        self.user = USER
        self.install_guild = None
        self.token_fault = False
        self.identity_revoked = False

    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path.removeprefix('/api/v10')
        self.lifecycle_calls.append((method, path))
        bearer = kwargs.get('headers', {}).get('Authorization', '').removeprefix('Bearer ')
        if path == '/oauth2/token':
            form = kwargs['form']
            if self.token_fault:
                return {'status': 400, 'body': {'error': 'invalid_grant'}}
            if form['grant_type'] == 'refresh_token':
                self.refresh_count += 1
                scopes, guild = ['identify', 'guilds'], None
            elif form['code'].startswith('install-'):
                scopes, guild = ['identify', 'bot'], self.install_guild or form['code'].split('-', 1)[1]
            else:
                scopes, guild = ['identify', 'guilds'], None
            access = 'synthetic-access-' + str(len(self.tokens))
            self.tokens[access] = scopes
            body = {'access_token': access, 'token_type': 'Bearer', 'scope': ' '.join(scopes), 'expires_in': 3600, 'refresh_token': 'synthetic-refresh'}
            if guild:
                body['guild'] = {'id': guild}
            return {'status': 200, 'body': body}
        if path == '/oauth2/@me':
            if self.identity_revoked:
                return {'status': 401, 'body': {'message': 'Synthetic revoked identity'}}
            return {'status': 200, 'body': {'application': {'id': APP}, 'user': {'id': self.user}, 'scopes': self.tokens[bearer]}}
        if path == '/users/@me' and kwargs.get('headers', {}).get('Authorization', '').startswith('Bearer '):
            return {'status': 200, 'body': {'id': self.user, 'username': 'Synthetic identity'}}
        if path == '/users/@me/guilds':
            return {'status': 200, 'body': [{'id': GUILD, 'name': 'Synthetic first guild', 'permissions': '32'},
                                          {'id': SECOND_GUILD, 'name': 'Synthetic second guild', 'permissions': '32'},
                                          {'id': '999888', 'name': 'Not managed', 'permissions': '1024'}]}
        if SECOND_GUILD in url:
            result = super().__call__(method, url.replace(SECOND_GUILD, GUILD), **kwargs)
            result['body'] = json.loads(json.dumps(result['body']).replace(GUILD, SECOND_GUILD))
            return result
        return super().__call__(method, url, **kwargs)


def service():
    wire = LifecycleWire()
    adapter = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=wire, production_reviewed=True)
    adapter.connections_v2_enabled = adapter.authorization_v2_enabled = True
    oauth = SimpleNamespace(_provider=lambda _: adapter, callback_uri=lambda _: 'https://rafii.example.invalid/api/oauth/discord/callback',
                            clock=lambda: NOW, vault=CredentialVault(CredentialVault.generate_key()))
    return DiscordConnections(oauth), wire


def context(purpose='identity'):
    return {'v': 1, 'purpose': purpose, 'workspaceId': WORKSPACE, 'memberId': ACTOR, 'applicationId': APP,
            'redirectUri': 'https://rafii.example.invalid/api/oauth/discord/callback', 'discoverGuilds': True}


class Lifecycle(unittest.TestCase):
    def test_server_state_binds_tenant_member_application_callback_purpose_and_scope(self):
        s, _ = service(); c = context()
        args = (WORKSPACE, ACTOR, s.adapter, s.oauth.callback_uri('discord'), ['identify', 'guilds'], 'identity')
        self.assertEqual(validate_context(c, *args), 'identity')
        for key, value in [('workspaceId', 'foreign'), ('memberId', 'foreign'), ('applicationId', '999999'),
                           ('redirectUri', 'https://evil.example/callback'), ('purpose', 'installation'), ('v', 2)]:
            with self.subTest(key=key), self.assertRaises(AlphaError):
                validate_context({**c, key: value}, *args)
        with self.assertRaises(AlphaError):
            validate_context(c, WORKSPACE, ACTOR, s.adapter, args[3], ['bot', 'identify'], 'identity')

    def test_connection_ids_are_durable_tenant_and_member_scoped(self):
        a = stable_id('identity', WORKSPACE, APP, USER, ACTOR)
        self.assertEqual(a, stable_id('identity', WORKSPACE, APP, USER, ACTOR))
        self.assertNotEqual(a, stable_id('identity', 'foreign-workspace', APP, USER, ACTOR))
        self.assertNotEqual(a, stable_id('identity', WORKSPACE, APP, USER, 'foreign-member'))
        self.assertNotEqual(stable_id('install', WORKSPACE, APP, GUILD), stable_id('install', WORKSPACE, APP, SECOND_GUILD))
        self.assertLessEqual(len(a), 80)

    def test_identity_envelope_never_reaches_publishing_sql(self):
        s, _ = service(); cur = Mock()
        with self.assertRaises(AlphaError):
            s.validate_installation(cur, WORKSPACE, {'kind': 'identity', 'at': 'synthetic-access'})
        cur.execute.assert_not_called()

    def test_expiry_response_is_strict_and_provider_errors_are_sanitized(self):
        s, wire = service()
        for expiry in (None, True, -1, 0, float('nan'), float('inf')):
            with self.subTest(expiry=expiry), self.assertRaises(AlphaError):
                s.token_body({'access_token': 'synthetic-access', 'token_type': 'Bearer', 'expires_in': expiry, 'scope': 'identify'})
        wire.token_fault = True
        with self.assertRaises(AlphaError) as error:
            s._response('POST', '/oauth2/token', form={'code': 'identity'})
        self.assertNotIn('invalid_grant', str(error.exception))

    def test_grant_scope_and_user_are_independently_observed(self):
        s, wire = service(); wire.tokens['synthetic-access'] = ['identify']
        user, _ = s.verified_user('synthetic-access', ['identify'])
        self.assertEqual(user['id'], USER)
        with self.assertRaises(AlphaError):
            s.verified_user('synthetic-access', ['identify', 'guilds'])

    def test_server_listing_excludes_unmanaged_guild_and_requires_explicit_scope(self):
        s, _ = service()
        self.assertEqual([x['id'] for x in s.user_guilds({'scopes': ['guilds'], 'bearer': 'synthetic-access', 'userId': USER})], [GUILD, SECOND_GUILD])
        with self.assertRaises(AlphaError):
            s.user_guilds({'scopes': ['identify'], 'bearer': 'synthetic-access'})

    def test_callback_single_use_commits_before_uncertain_exchange(self):
        s, _ = service(); encrypted, key = s.oauth.vault.encrypt(json.dumps(context()))
        row = ['transaction', ACTOR, 'identity', s.oauth.callback_uri('discord'), ['identify', 'guilds'], encrypted, key, NOW + 60, False]
        cur = Mock(); cur.fetchone.side_effect = lambda: tuple(row)
        def execute(sql, params):
            if sql.startswith('UPDATE public.pr_oauth_transactions SET consumed_at'):
                row[8] = True
        cur.execute.side_effect = execute
        @contextmanager
        def local(*_):
            yield cur, initial_state(WORKSPACE), ACTOR
        s.local = local
        with patch('postriff_phase2.hosted.audit'), patch.object(s, '_response', side_effect=AlphaError('Synthetic timeout', 503)) as remote:
            with self.assertRaises(AlphaError):
                s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'synthetic-code')
            self.assertTrue(row[8])
            with self.assertRaises(AlphaError):
                s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'synthetic-code')
            self.assertEqual(remote.call_count, 1)

    def test_wrong_member_expired_or_denied_callback_does_not_exchange(self):
        s, _ = service(); encrypted, key = s.oauth.vault.encrypt(json.dumps(context()))
        for member, expiry, denied in [('foreign-member', NOW + 60, False), (ACTOR, NOW - 1, False), (ACTOR, NOW + 60, True)]:
            with self.subTest(member=member, expiry=expiry, denied=denied):
                cur = Mock(); cur.fetchone.return_value = ('transaction', member, 'identity', s.oauth.callback_uri('discord'), ['identify', 'guilds'], encrypted, key, expiry, False)
                @contextmanager
                def local(*_):
                    yield cur, initial_state(WORKSPACE), ACTOR
                s.local = local
                with patch('postriff_phase2.hosted.audit'), patch.object(s, '_response') as remote:
                    if denied:
                        self.assertFalse(s.complete(WORKSPACE, 'session', 's' * 32, None, 'access_denied')['connected'])
                    else:
                        with self.assertRaises(AlphaError):
                            s.complete(WORKSPACE, 'session', 's' * 32, 'code')
                    remote.assert_not_called()

    def test_new_disconnect_path_cannot_uninstall_shared_bot(self):
        s, wire = service()
        with self.assertRaises(AlphaError):
            s.adapter.revoke(json.dumps({'v': 2, 'guild': GUILD}))
        self.assertFalse(any(method == 'DELETE' for method, _ in wire.lifecycle_calls))

    def test_public_methods_never_treat_missing_session_as_worker_authority(self):
        s, wire = service()
        actions = [lambda: s.start(WORKSPACE, None, 'identity', {}),
                   lambda: s.complete(WORKSPACE, None, 's' * 32, 'code'),
                   lambda: s.guilds(WORKSPACE, None, 'identity'),
                   lambda: s.disconnect_identity(WORKSPACE, None, 'identity')]
        for action in actions:
            with self.assertRaises(AlphaError):
                action()
        self.assertEqual(wire.lifecycle_calls, [])

    def test_unexpired_remotely_revoked_identity_holds_dependents(self):
        s, _ = service(); state = initial_state(WORKSPACE)
        record = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'status': 'linked', 'authorizationGeneration': 'generation'}
        state['phase2'] = {'discordIdentityLinks': [record]}
        @contextmanager
        def local(*_):
            yield Mock(), state, ACTOR
        s.local = local
        s.bind_identity = Mock(return_value=(('ciphertext', 'key', None, NOW + 3600, 'generation', ['identify'], USER), {'user': USER, 'at': 'synthetic-access'}))
        revoked = AlphaError('Synthetic revoked authorization', 409); revoked.discord_permanent = True
        s.verified_user = Mock(side_effect=revoked); s.invalidate_dependents = Mock(); s.save_state = Mock()
        with self.assertRaises(AlphaError):
            s._fresh_identity(WORKSPACE, 'session', 'identity')
        self.assertEqual(record['status'], 'reconnect_required')
        s.invalidate_dependents.assert_called_once()

    def test_identity_disconnect_step_up_precedes_every_mutation(self):
        s, _ = service(); state = initial_state(WORKSPACE)
        record = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'status': 'linked'}
        state['phase2'] = {'discordIdentityLinks': [record]}
        @contextmanager
        def local(*_):
            yield Mock(), state, ACTOR
        s.local = local; s.oauth.repository = SimpleNamespace(assert_fresh=Mock(side_effect=AlphaError('Fresh session required', 403)))
        s.invalidate_dependents = Mock()
        with self.assertRaises(AlphaError):
            s.disconnect_identity(WORKSPACE, 'session', 'identity')
        self.assertEqual(record['status'], 'linked'); s.invalidate_dependents.assert_not_called()

    def test_turning_off_workflow_holds_new_installation_and_identity_grants(self):
        from postriff_phase2.oauth import OAuthService
        s, _ = service(); adapter = s.adapter; adapter.connections_v2_enabled = False
        oauth = OAuthService(SimpleNamespace(), SimpleNamespace(), s.oauth.vault, {'discord': adapter}, 'https://rafii.example.invalid')
        for kind in ('installation', 'identity'):
            encrypted, key = s.oauth.vault.encrypt(json.dumps({'v': 2, 'kind': kind}))
            cur = Mock(); cur.fetchone.return_value = (encrypted, key, ['identify', 'bot'], 'generation')
            with self.subTest(kind=kind), self.assertRaises(AlphaError):
                oauth.discord_grant_for_worker(WORKSPACE, 'connection', cur=cur)


if __name__ == '__main__':
    unittest.main()
