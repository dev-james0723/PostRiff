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
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.oauth import CredentialVault, OAuthService
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
        self.install_token_scopes = ['identify', 'bot']
        self.install_bearer_scopes = ['identify']
        self.token_overrides = {}
        self.application = APP
        self.profile_user = None
        self.route_overrides = {}

    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path.removeprefix('/api/v10')
        self.lifecycle_calls.append((method, path))
        if (method, path) in self.route_overrides:
            return copy.deepcopy(self.route_overrides[(method, path)])
        bearer = kwargs.get('headers', {}).get('Authorization', '').removeprefix('Bearer ')
        if path == '/oauth2/token':
            form = kwargs['form']
            if self.token_fault:
                return {'status': 400, 'body': {'error': 'invalid_grant'}}
            if form['grant_type'] == 'refresh_token':
                self.refresh_count += 1
                scopes, guild = ['identify', 'guilds'], None
            elif form['code'].startswith('install-'):
                scopes, guild = self.install_token_scopes, self.install_guild or form['code'].split('-', 1)[1]
            else:
                scopes, guild = ['identify', 'guilds'], None
            access = 'synthetic-access-' + str(len(self.tokens))
            # Code-exchange consent and live bearer introspection are
            # independent provider evidence, including bot passthrough scope.
            self.tokens[access] = copy.deepcopy(self.install_bearer_scopes if guild else scopes)
            body = {'access_token': access, 'token_type': 'Bearer', 'scope': ' '.join(scopes), 'expires_in': 3600, 'refresh_token': 'synthetic-refresh'}
            if guild:
                body['guild'] = {'id': guild}
            body.update(copy.deepcopy(self.token_overrides))
            return {'status': 200, 'body': body}
        if path == '/oauth2/@me':
            if self.identity_revoked:
                return {'status': 401, 'body': {'message': 'Synthetic revoked identity'}}
            return {'status': 200, 'body': {'application': {'id': self.application}, 'user': {'id': self.user}, 'scopes': self.tokens[bearer]}}
        if path == '/users/@me' and kwargs.get('headers', {}).get('Authorization', '').startswith('Bearer '):
            return {'status': 200, 'body': {'id': self.profile_user or self.user, 'username': 'Synthetic identity'}}
        if path == '/users/@me/guilds':
            return {'status': 200, 'body': [{'id': GUILD, 'name': 'Synthetic first guild', 'permissions': '32'},
                                          {'id': SECOND_GUILD, 'name': 'Synthetic second guild', 'permissions': '32'},
                                          {'id': '999888', 'name': 'Not managed', 'permissions': '1024'}]}
        if SECOND_GUILD in url:
            result = super().__call__(method, url.replace(SECOND_GUILD, GUILD), **kwargs)
            result['body'] = json.loads(json.dumps(result['body']).replace(GUILD, SECOND_GUILD))
            return result
        return super().__call__(method, url, **kwargs)


def service(*, with_vault=True):
    wire = LifecycleWire()
    adapter = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=wire, production_reviewed=True)
    adapter.connections_v2_enabled = adapter.authorization_v2_enabled = True
    oauth = SimpleNamespace(_provider=lambda _: adapter, callback_uri=lambda _: 'https://rafii.example.invalid/api/oauth/discord/callback',
                            clock=lambda: NOW, vault=CredentialVault(CredentialVault.generate_key()) if with_vault else None)
    return DiscordConnections(oauth), wire


def context(purpose='identity'):
    return {'v': 1, 'purpose': purpose, 'workspaceId': WORKSPACE, 'memberId': ACTOR, 'applicationId': APP,
            'redirectUri': 'https://rafii.example.invalid/api/oauth/discord/callback', 'discoverGuilds': True}


def installation_callback():
    """Run real callback/custody/capability code over a synthetic locked store.

    SQL isolation and commits are covered by the separate disposable-PG suite.
    """
    s, wire = service()
    state = initial_state(WORKSPACE)
    generation = 'synthetic-identity-generation'
    record = {'id': 'synthetic-identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR,
              'status': 'linked', 'authorizationGeneration': generation}
    state['phase2'] = {'channels': [], 'assets': [], 'reviews': [], 'jobs': [],
                       'discordIdentityLinks': [record]}
    c = {**context('installation'), 'identityConnectionId': record['id'], 'identityGeneration': generation,
         'userId': USER, 'guildId': GUILD}
    encrypted, key = s.oauth.vault.encrypt(json.dumps(c))
    row = ['synthetic-transaction', ACTOR, 'publish', s.oauth.callback_uri('discord'),
           ['identify', 'bot'], encrypted, key, NOW + 60, False]
    cur = Mock()
    last_sql = ['']
    def execute(sql, params):
        last_sql[0] = sql
        if sql.startswith('UPDATE public.pr_oauth_transactions SET consumed_at'):
            row[8] = True
    cur.execute.side_effect = execute
    cur.fetchone.side_effect = lambda: tuple(row) if last_sql[0].startswith('SELECT id::text,member_id') else ('synthetic-installation-generation',)
    @contextmanager
    def local(*_):
        yield cur, state, ACTOR
    s.local = local
    s.bind_identity = Mock(return_value=(('synthetic-ciphertext', 'synthetic-key', None, NOW + 3600,
                                          generation, ['identify', 'guilds'], USER), {'user': USER}))
    s.oauth._admit_identity = Mock()
    s.oauth.commands = HostedPhase2Commands(clock=lambda: NOW)
    s.oauth._capabilities = OAuthService._capabilities
    s.save_state = Mock()
    return s, wire, state, row, cur


class InstallationCallback(unittest.TestCase):
    def complete(self, s):
        with patch('postriff_phase2.hosted.audit'):
            return s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'install-' + GUILD)

    def assert_no_installation(self, wire, state, cur):
        self.assertEqual(state['phase2']['channels'], [])
        self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_encrypted_credentials')
                             for call in cur.execute.call_args_list))
        self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')
                             for call in cur.execute.call_args_list))
        self.assertFalse(any(method == 'POST' and path.startswith('/channels/')
                             for method, path in wire.lifecycle_calls))

    def test_passthrough_installation_keeps_bearer_proof_separate_and_does_not_approve_destination(self):
        for token_scopes in (['identify', 'bot'], ['bot']):
            with self.subTest(token_scopes=token_scopes):
                s, wire, state, row, cur = installation_callback()
                wire.install_token_scopes = token_scopes
                self.assertTrue(self.complete(s)['connected'])
                channel, = state['phase2']['channels']
                self.assertTrue(channel['capabilityVerified'])
                self.assertEqual(channel['discordConnectionKind'], 'installation')
                self.assertEqual(channel['scopes'], ['bot', 'identify'])
                self.assertFalse(channel.get('defaultDestinationId'))
                self.assertFalse(channel.get('discordDestinations'))
                insert, = [call for call in cur.execute.call_args_list
                            if call.args[0].startswith('INSERT INTO public.pr_encrypted_credentials')]
                params = insert.args[1]
                envelope = json.loads(s.oauth.vault.decrypt(params[3], params[5]))
                self.assertEqual(envelope['authorization'], {'bearerScopes': ['identify'], 'installationScopes': ['bot']})
                self.assertEqual((envelope['guild'], envelope['channel']), (GUILD, None))
                self.assertNotIn('at', envelope)
                self.assertNotIn('synthetic-access-', json.dumps(envelope))
                self.assertIsNone(params[4])  # No transient refresh token retained.
                matrix = {call.args[1][2]: call.args[1][3] for call in cur.execute.call_args_list
                          if call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')}
                self.assertEqual((matrix['publish'], matrix['schedule']), ('Direct', 'Direct'))
                self.assertIn(('GET', '/oauth2/@me'), wire.lifecycle_calls)
                self.assertIn(('GET', '/users/@me'), wire.lifecycle_calls)
                self.assertIn(('GET', '/guilds/' + GUILD + '/members/' + USER), wire.lifecycle_calls)
                self.assertTrue(row[8])
                with self.assertRaises(AlphaError):
                    self.complete(s)
                self.assertEqual(wire.lifecycle_calls.count(('POST', '/oauth2/token')), 1)
                self.assertFalse(any(method == 'POST' and path.startswith('/channels/')
                                     for method, path in wire.lifecycle_calls))

    def test_installation_still_requires_live_identify_and_well_formed_scope_evidence(self):
        for scopes in ([], ['bot'], None, 'identify', [{'name': 'identify'}]):
            with self.subTest(scopes=scopes):
                s, wire, state, row, cur = installation_callback()
                wire.install_bearer_scopes = scopes
                with self.assertRaises(AlphaError) as error:
                    self.complete(s)
                self.assertIn('required user permissions', str(error.exception))
                self.assertTrue(row[8])
                self.assertNotIn(('GET', '/guilds/' + GUILD), wire.lifecycle_calls)
                self.assert_no_installation(wire, state, cur)

    def test_wrong_application_subject_or_independent_profile_cannot_install(self):
        for field in ('application', 'user', 'profile_user'):
            with self.subTest(field=field):
                s, wire, state, _, cur = installation_callback()
                setattr(wire, field, '999888')
                with self.assertRaises(AlphaError) as error:
                    self.complete(s)
                self.assertNotIn('999888', str(error.exception))
                self.assertNotIn('synthetic-access', str(error.exception))
                self.assert_no_installation(wire, state, cur)

    def test_missing_malformed_or_different_exchange_guild_cannot_install(self):
        for guild in (None, [], {}, {'id': SECOND_GUILD}):
            with self.subTest(guild=guild):
                s, wire, state, _, cur = installation_callback()
                wire.token_overrides = {'guild': guild}
                with self.assertRaises(AlphaError):
                    self.complete(s)
                self.assertNotIn(('GET', '/guilds/' + GUILD), wire.lifecycle_calls)
                self.assert_no_installation(wire, state, cur)

    def test_removed_bot_wrong_bot_application_and_lost_membership_are_not_installation_proof(self):
        cases = [('/guilds/' + GUILD, 403, {}),
                 ('/oauth2/applications/@me', 200, {'id': '999888'}),
                 ('/guilds/' + GUILD + '/members/' + BOT, 404, {}),
                 ('/guilds/' + GUILD + '/members/' + USER, 404, {})]
        for path, status, body in cases:
            with self.subTest(path=path):
                s, wire, state, _, cur = installation_callback()
                wire.route_overrides[('GET', path)] = {'status': status, 'body': body, 'headers': {}}
                with self.assertRaises(AlphaError):
                    self.complete(s)
                self.assert_no_installation(wire, state, cur)

    def test_restricted_user_or_no_permitted_channel_cannot_create_publish_capability(self):
        for restriction in ('pending', 'no_channels', 'no_manage_server'):
            with self.subTest(restriction=restriction):
                s, wire, state, _, cur = installation_callback()
                if restriction == 'pending':
                    wire.restricted = {'pending': True}
                elif restriction == 'no_channels':
                    wire.allowed = set()
                else:
                    wire.route_overrides[('GET', '/guilds/' + GUILD)] = {'status': 200, 'body': {
                        'id': GUILD, 'name': 'Synthetic server', 'owner_id': BOT,
                        'roles': [{'id': GUILD, 'permissions': str(DiscordProvider.PERMISSIONS)}]}}
                with self.assertRaises(AlphaError):
                    self.complete(s)
                self.assert_no_installation(wire, state, cur)

    def test_changed_or_expired_linked_identity_cannot_commit_installation(self):
        for change in ('generation', 'expired'):
            with self.subTest(change=change):
                s, wire, state, _, cur = installation_callback()
                if change == 'generation':
                    state['phase2']['discordIdentityLinks'][0]['authorizationGeneration'] = 'changed-generation'
                else:
                    row, envelope = s.bind_identity.return_value
                    s.bind_identity.return_value = ((*row[:3], NOW - 1, *row[4:]), envelope)
                with self.assertRaises(AlphaError):
                    self.complete(s)
                self.assert_no_installation(wire, state, cur)

    def test_installation_request_cannot_drop_bot_or_change_to_user_only_consent(self):
        s, wire, state, row, cur = installation_callback()
        row[4] = ['identify']
        with self.assertRaises(AlphaError):
            self.complete(s)
        self.assertEqual(wire.lifecycle_calls, [])
        self.assert_no_installation(wire, state, cur)


class Lifecycle(unittest.TestCase):
    def test_current_authorization_verifies_live_identity_without_discarded_profile_read(self):
        s, wire = service(with_vault=False)
        wire.tokens['synthetic-access'] = ['identify', 'guilds']
        user, scopes = s.verified_authorization('synthetic-access', ['identify', 'guilds'], USER)
        self.assertEqual((user['id'], scopes), (USER, ['identify', 'guilds']))
        self.assertEqual(wire.lifecycle_calls, [('GET', '/oauth2/@me')])
        wire.identity_revoked = True
        with self.assertRaises(AlphaError):
            s.verified_authorization('synthetic-access', ['identify', 'guilds'], USER)
        self.assertEqual(wire.lifecycle_calls, [('GET', '/oauth2/@me'), ('GET', '/oauth2/@me')])

    def test_direct_rafii_scheduling_requires_the_secure_connection_workflow(self):
        s, wire = service(with_vault=False)
        adapter = s.adapter
        self.assertFalse(adapter.native_schedule)
        for authorization, connections in ((False, False), (False, True), (True, False)):
            with self.subTest(authorization=authorization, connections=connections):
                adapter.authorization_v2_enabled = authorization
                adapter.connections_v2_enabled = connections
                matrix = OAuthService._capabilities(adapter, 'publish', ['identify', 'bot'], [], NOW)
                self.assertNotEqual(matrix['schedule']['level'], 'Direct')
        self.assertEqual(wire.lifecycle_calls, [])

    def test_current_authorization_rejects_missing_or_mismatched_grant_evidence(self):
        valid = {'application': {'id': APP}, 'user': {'id': USER}, 'scopes': ['identify', 'guilds']}
        for override in ({'user': None}, {'user': {'id': '999888'}}, {'application': {'id': '999888'}},
                         {'scopes': ['identify']}, {'scopes': [{'name': 'identify'}]}, {'application': None}):
            with self.subTest(override=override):
                s, _ = service(with_vault=False)
                s._response = Mock(return_value={**valid, **override})
                with self.assertRaises(AlphaError):
                    s.verified_authorization('synthetic-access', ['identify', 'guilds'], USER)
                s._response.assert_called_once_with('GET', '/oauth2/@me', 'synthetic-access', user_id=USER)

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
        s.verified_authorization = Mock(side_effect=revoked); s.invalidate_dependents = Mock(); s.save_state = Mock()
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
