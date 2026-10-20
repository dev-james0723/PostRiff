"""Offline regressions for installation consent versus user bearer scopes.

The real connection/provider logic runs against synthetic SQL custody and a
strict fake Discord transport. No network or database is contacted.
"""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.oauth import OAuthService
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import (
    fixture, APP, BOT, USER, GUILD, NOW, WORKSPACE, ACTOR, GENERATION, FIRST, SECOND,
)


def reverify_fixture(*, ready=False, scopes=None, consent_proof=True):
    connections, wire = service()
    _, state, channel, _ = fixture()
    scopes = scopes if scopes is not None else ['applications.commands', 'bot', 'identify']
    identity_id, identity_generation = 'synthetic-identity', 'synthetic-identity-generation'
    record = {'id': identity_id, 'workspaceId': WORKSPACE, 'applicationId': APP,
              'authorizedBy': ACTOR, 'userId': USER, 'status': 'linked',
              'authorizationGeneration': identity_generation}
    state['phase2']['discordIdentityLinks'] = [record]
    channel.update(discordConnectionKind='installation', discordIdentityConnectionId=identity_id,
                   scopes=list(scopes), capabilityVerified=ready, verifiedAt=NOW - 7200,
                   enabledPermissionGroups=['identity', 'publish'])
    envelope = {'v': 2, 'kind': 'installation', 'applicationId': APP, 'botUserId': BOT,
                'guild': GUILD, 'user': USER, 'channel': SECOND,
                'identityConnectionId': identity_id, 'identityGeneration': identity_generation}
    if consent_proof:
        envelope['authorization'] = {'bearerScopes': ['identify'], 'installationScopes': ['bot']}
    identity_envelope = {'v': 1, 'kind': 'identity', 'applicationId': APP, 'memberId': ACTOR,
                         'user': USER, 'at': 'synthetic-access'}
    installation_ct, installation_key = connections.oauth.vault.encrypt(json.dumps(envelope))
    identity_ct, identity_key = connections.oauth.vault.encrypt(json.dumps(identity_envelope))
    credentials = {
        channel['id']: [installation_ct, installation_key, None, None, GENERATION, list(scopes), GUILD],
        identity_id: [identity_ct, identity_key, None, NOW + 3600, identity_generation, ['identify', 'guilds'], USER],
    }
    envelopes = {channel['id']: envelope, identity_id: identity_envelope}
    wire.tokens['synthetic-access'] = ['identify', 'guilds']
    cursor = Mock()
    last_sql = ['']
    def fetchone():
        # A real installation needs an active Rafii connection authorizer.
        # The synthetic owner is active; removed/downgraded cases have their
        # own negative regressions in test_discord_hybrid_review_regressions.
        return ('owner', True) if last_sql[0].startswith('SELECT m.role,m.can_manage_connections') else (state,)
    cursor.fetchone.side_effect = fetchone
    cursor.rowcount = 1

    def execute(sql, params):
        last_sql[0] = sql
        if sql.startswith('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,scopes=%s'):
            ciphertext, refresh_ct, key, granted, expires, workspace, connection, generation, old_ct = params
            if workspace != WORKSPACE or credentials[connection][0] != old_ct:
                raise AssertionError('Refresh custody changed')
            credentials[connection] = [ciphertext, key, refresh_ct, expires, generation, granted, USER]
            envelopes[connection] = json.loads(connections.oauth.vault.decrypt(ciphertext, key))

    cursor.execute.side_effect = execute

    @contextmanager
    def local(workspace, token):
        if workspace != WORKSPACE:
            raise AssertionError('Foreign workspace')
        yield cursor, state, ACTOR if token is not None else None

    def read_credential(cur, workspace, connection):
        if workspace != WORKSPACE or connection not in credentials:
            raise AlphaError('Synthetic connection unavailable.', 404)
        return copy.deepcopy(credentials[connection]), copy.deepcopy(envelopes[connection])

    connections.local = local
    connections.read_credential = read_credential
    connections.save_state = Mock()
    connections.oauth.commands = HostedPhase2Commands(clock=lambda: NOW)
    connections.oauth._capabilities = OAuthService._capabilities
    connections.oauth.WORKER_REVERIFIED = OAuthService.WORKER_REVERIFIED
    return connections, wire, state, channel, credentials, envelopes, cursor


class InstallationReverification(unittest.TestCase):
    def verify(self, connections, channel, *, manual=True):
        with patch('postriff_phase2.hosted.audit'):
            return connections.reverify_installation(WORKSPACE, channel['id'],
                **({'token': 'synthetic-session'} if manual else {}))

    def assert_no_scope_or_publication_write(self, wire, cursor):
        self.assertFalse(any('SET scopes=' in call.args[0] for call in cursor.execute.call_args_list))
        self.assertFalse(any(method in ('POST', 'PUT', 'PATCH', 'DELETE')
                             for method, _ in wire.lifecycle_calls))

    def test_three_installation_scopes_and_two_bearer_scopes_restore_manual_readiness(self):
        s, wire, state, channel, credentials, _, cur = reverify_fixture()
        saved_scopes = list(channel['scopes'])
        destinations = copy.deepcopy(channel['discordDestinations'])
        result = self.verify(s, channel)
        self.assertEqual(result['state'], 'read_verified')
        self.assertTrue(result['ready'])
        self.assertTrue(channel['capabilityVerified'])
        self.assertEqual(channel['scopes'], saved_scopes)
        self.assertEqual(credentials[channel['id']][5], saved_scopes)
        self.assertEqual(channel['discordDestinations'], destinations)
        self.assertEqual(state['phase2']['jobs'], [])
        self.assertEqual(state['phase2']['reviews'], [])
        levels = {call.args[1][2]: call.args[1][3] for call in cur.execute.call_args_list
                  if call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')}
        self.assertEqual(levels['publish'], 'Direct')
        self.assertEqual(levels['schedule'], 'Direct')
        self.assertIn(('GET', '/oauth2/@me'), wire.lifecycle_calls)
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_previously_downgraded_legacy_envelope_preserves_two_stored_scopes(self):
        s, wire, _, channel, credentials, _, cur = reverify_fixture(
            scopes=['bot', 'identify'], consent_proof=False)
        self.assertTrue(self.verify(s, channel)['ready'])
        self.assertEqual(channel['scopes'], ['bot', 'identify'])
        self.assertEqual(credentials[channel['id']][5], ['bot', 'identify'])
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_worker_never_restores_downgraded_capability(self):
        s, wire, _, channel, _, _, cur = reverify_fixture(ready=False)
        result = self.verify(s, channel, manual=False)
        self.assertEqual(result['state'], 'read_verified')
        self.assertFalse(result['ready'])
        self.assertFalse(channel['capabilityVerified'])
        self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')
                             for call in cur.execute.call_args_list))
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_worker_can_renew_existing_authority_without_scope_drift(self):
        s, wire, _, channel, _, _, cur = reverify_fixture(ready=True)
        self.assertTrue(self.verify(s, channel, manual=False)['ready'])
        self.assertEqual(channel['verifiedAt'], NOW)
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_manual_verification_cannot_restore_disabled_publish_consent(self):
        for groups in ([], ['identity']):
            with self.subTest(groups=groups):
                s, wire, _, channel, _, _, cur = reverify_fixture()
                channel['enabledPermissionGroups'] = groups
                result = self.verify(s, channel)
                self.assertEqual(result['state'], 'consent_missing')
                self.assertFalse(result['ready'])
                self.assertFalse(channel['capabilityVerified'])
                self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')
                                     for call in cur.execute.call_args_list))
                self.assert_no_scope_or_publication_write(wire, cur)

    def test_expired_linked_identity_can_use_existing_refresh_before_installation_commit(self):
        s, wire, state, channel, credentials, _, cur = reverify_fixture()
        identity_id = channel['discordIdentityConnectionId']
        credentials[identity_id][3] = NOW - 1
        credentials[identity_id][2] = s.oauth.vault.encrypt('synthetic-refresh')[0]
        result = self.verify(s, channel)
        self.assertTrue(result['ready'])
        self.assertEqual(wire.refresh_count, 1)
        self.assertGreater(credentials[identity_id][3], NOW)
        self.assertNotIn('refreshClaim', state['phase2']['discordIdentityLinks'][0])
        self.assertEqual(credentials[channel['id']][5], ['applications.commands', 'bot', 'identify'])
        self.assertFalse(any(method == 'POST' and path.startswith('/channels/')
                             for method, path in wire.lifecycle_calls))

    def test_missing_recorded_bot_consent_is_not_inferred_from_bot_membership(self):
        s, wire, _, channel, _, _, cur = reverify_fixture(scopes=['identify'])
        with self.assertRaises(AlphaError):
            self.verify(s, channel)
        self.assertFalse(channel['capabilityVerified'])
        self.assertEqual(wire.lifecycle_calls, [])
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_missing_live_user_scope_blocks_and_invalidates_dependents(self):
        s, wire, state, channel, _, _, cur = reverify_fixture()
        wire.tokens['synthetic-access'] = ['guilds']
        result = self.verify(s, channel)
        self.assertFalse(result['ready'])
        self.assertFalse(channel['capabilityVerified'])
        self.assertEqual(state['phase2']['discordIdentityLinks'][0]['status'], 'reconnect_required')
        self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')
                             for call in cur.execute.call_args_list))

    def test_unrelated_live_channel_does_not_restore_revoked_destination_permissions(self):
        s, wire, _, channel, _, _, cur = reverify_fixture(ready=True)
        wire.allowed = {FIRST}
        result = self.verify(s, channel)
        self.assertEqual(result['state'], 'permission_missing')
        self.assertFalse(result['ready'])
        self.assertFalse(channel['capabilityVerified'])
        self.assertEqual(channel['verifiedAt'], NOW - 7200)
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_provider_outage_does_not_extend_freshness_or_erase_authority(self):
        for route in ('/oauth2/@me', '/guilds/' + GUILD + '/channels'):
            with self.subTest(route=route):
                s, wire, _, channel, _, _, cur = reverify_fixture(ready=True)
                wire.route_overrides[('GET', route)] = {'status': 503, 'body': {}}
                before = copy.deepcopy(channel)
                result = self.verify(s, channel)
                self.assertEqual(result['state'], 'verification_unavailable')
                self.assertFalse(result['ready'])
                self.assertEqual(channel, before)
                s.save_state.assert_not_called()
                self.assert_no_scope_or_publication_write(wire, cur)

    def test_transient_409_read_admission_is_unavailable_not_reauthorization(self):
        s, wire, _, channel, _, _, cur = reverify_fixture(ready=True)
        before = copy.deepcopy(channel)
        s.verified_authorization = Mock(side_effect=AlphaError('Synthetic read admission delay.', 409,
                                                               code='discord_read_delayed'))
        result = self.verify(s, channel)
        self.assertEqual(result['state'], 'verification_unavailable')
        self.assertFalse(result['ready'])
        self.assertEqual(channel, before)
        s.save_state.assert_not_called()
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_unexpected_transport_exception_preserves_connection(self):
        s, wire, _, channel, _, _, cur = reverify_fixture(ready=True)
        before = copy.deepcopy(channel)
        s.verified_authorization = Mock(side_effect=RuntimeError('Synthetic transport unavailable'))
        result = self.verify(s, channel)
        self.assertEqual(result['state'], 'verification_unavailable')
        self.assertFalse(result['ready'])
        self.assertEqual(channel, before)
        s.save_state.assert_not_called()
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_older_success_cannot_overwrite_newer_permission_denial(self):
        for initially_ready in (False, True):
            with self.subTest(initially_ready=initially_ready):
                s, wire, _, channel, _, _, cur = reverify_fixture(ready=initially_ready)
                original = s.adapter.destinations
                nested = []

                def destinations(access):
                    # Capture the older successful observation, then commit a
                    # newer denial before the old observation may commit.
                    result = original(access)
                    if not nested:
                        nested.append(True)
                        s.adapter.destinations = Mock(return_value=[])
                        newer = self.verify(s, channel)
                        self.assertEqual(newer['state'], 'permission_missing')
                        self.assertFalse(newer['ready'])
                    return result

                s.adapter.destinations = destinations
                result = self.verify(s, channel)
                self.assertEqual(result['state'], 'verification_unavailable')
                self.assertFalse(result['ready'])
                self.assertFalse(channel['capabilityVerified'])
                self.assertTrue(channel['discordVerificationGeneration'])
                self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')
                                     for call in cur.execute.call_args_list))
                self.assert_no_scope_or_publication_write(wire, cur)

    def test_generation_change_during_provider_read_cannot_restore_capability(self):
        for changed in ('installation', 'identity', 'destination'):
            with self.subTest(changed=changed):
                s, wire, state, channel, credentials, _, cur = reverify_fixture()
                original = s.adapter.transport

                def transport(method, url, **kwargs):
                    response = original(method, url, **kwargs)
                    if url.endswith('/guilds/' + GUILD + '/channels'):
                        if changed == 'installation':
                            credentials[channel['id']][4] = 'changed-installation-generation'
                            channel['discordAuthorizationGeneration'] = 'changed-installation-generation'
                        elif changed == 'identity':
                            record = state['phase2']['discordIdentityLinks'][0]
                            credentials[record['id']][4] = 'changed-identity-generation'
                            record['authorizationGeneration'] = 'changed-identity-generation'
                        else:
                            channel['discordDestinations'][0]['resourceGeneration'] = 'changed-destination-generation'
                    return response

                s.adapter.transport = transport
                result = self.verify(s, channel)
                self.assertEqual(result['state'], 'verification_unavailable')
                self.assertFalse(result['ready'])
                self.assertFalse(channel['capabilityVerified'])
                self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_channel_capabilities')
                                     for call in cur.execute.call_args_list))
                self.assert_no_scope_or_publication_write(wire, cur)

    def test_malformed_separated_consent_does_not_fall_back_to_inferred_scopes(self):
        s, wire, _, channel, _, envelopes, cur = reverify_fixture()
        envelopes[channel['id']]['authorization']['installationScopes'] = []
        with self.assertRaises(AlphaError):
            self.verify(s, channel)
        self.assertFalse(channel['capabilityVerified'])
        self.assertEqual(wire.lifecycle_calls, [])
        self.assert_no_scope_or_publication_write(wire, cur)

    def test_generic_token_custody_cannot_overwrite_modern_installation_scopes(self):
        s, wire, _, channel, credentials, _, _ = reverify_fixture()
        row = credentials[channel['id']]
        cursor = Mock()
        cursor.fetchone.return_value = ('discord', row[0], None, row[1], None, False, False,
                                        row[5], GUILD, NOW)

        @contextmanager
        def cursor_context():
            yield cursor

        @contextmanager
        def database_context():
            yield SimpleNamespace(cursor=cursor_context)

        oauth = OAuthService.__new__(OAuthService)
        oauth.repository = SimpleNamespace(connection_factory=database_context)
        oauth.vault = s.oauth.vault
        with self.assertRaises(AlphaError) as error:
            oauth._token_for_worker(WORKSPACE, channel['id'])
        self.assertEqual(error.exception.code, 'discord_installation_verification_required')
        self.assertFalse(any(call.args[0].startswith('UPDATE') for call in cursor.execute.call_args_list))
        self.assertEqual(wire.lifecycle_calls, [])


if __name__ == '__main__':
    unittest.main()
