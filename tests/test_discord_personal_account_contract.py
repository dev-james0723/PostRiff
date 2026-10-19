"""Personal identity presentation and consent, with synthetic in-memory custody."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError, initial_state
from test_discord_oauth_lifecycle import service, context
from test_discord_publish_authorization import APP, USER, NOW, WORKSPACE, ACTOR


CAPABILITIES = {
    'connectionKind': 'identity', 'senderKind': 'none', 'canPublish': False,
    'canSchedule': False, 'postAsPersonalUser': False,
    'capabilityReason': 'discord_identity_only',
}


def linked(**overrides):
    return {'id': 'synthetic-personal-identity', 'workspaceId': WORKSPACE,
            'authorizedBy': ACTOR, 'account': 'Synthetic customer', 'userId': USER,
            'status': 'linked', 'expiresAt': NOW + 3600, 'discoverGuilds': False,
            **overrides}


def readable(records):
    s, wire = service()
    state = initial_state(WORKSPACE)
    state['phase2'] = {'discordIdentityLinks': copy.deepcopy(records)}
    @contextmanager
    def transaction(token, workspace):
        yield Mock(), ('synthetic-workspace-row', json.dumps(state)), ACTOR
    s.oauth.repository = SimpleNamespace(transaction=transaction)
    return s, wire, state


class PersonalAccountContract(unittest.TestCase):
    def test_identity_projection_explicitly_denies_all_publishing(self):
        s, wire, state = readable([linked(canPublish=True, canSchedule=True,
            postAsPersonalUser=True, senderKind='user', capabilityReason='forged')])
        before = copy.deepcopy(state)
        result, = s.public_identities(WORKSPACE, 'synthetic-session')
        self.assertEqual({key: result.get(key) for key in CAPABILITIES}, CAPABILITIES)
        self.assertEqual(result['account'], 'Synthetic customer')
        self.assertEqual(state, before)
        self.assertEqual(wire.lifecycle_calls, [])

    def test_projection_excludes_foreign_workspace_member_and_unbound_legacy_record(self):
        own = linked()
        unbound = linked(id='synthetic-unbound'); del unbound['workspaceId']
        s, _, _ = readable([own, linked(id='foreign-workspace', workspaceId='foreign'),
            linked(id='foreign-member', authorizedBy='foreign'), unbound, None])
        result = s.public_identities(WORKSPACE, 'synthetic-session')
        self.assertEqual([value['id'] for value in result], [own['id']])

    def test_public_identity_requires_an_authenticated_session(self):
        s, wire, _ = readable([linked()])
        with self.assertRaises(AlphaError):
            s.public_identities(WORKSPACE, None)
        self.assertEqual(wire.lifecycle_calls, [])

    def test_projection_never_contains_private_custody_fields(self):
        s, _, _ = readable([linked(access_token='synthetic-access-private',
            refresh_token='synthetic-refresh-private', at='synthetic-bearer-private',
            key_id='synthetic-key-private', authorizationGeneration='private-generation',
            refreshClaim='private-claim', envelope={'secret': 'private'})])
        result, = s.public_identities(WORKSPACE, 'synthetic-session')
        self.assertEqual(set(result), {'id', 'account', 'userId', 'status', 'expiresAt',
            'discoverGuilds', *CAPABILITIES})
        self.assertNotIn('private', json.dumps(result))

    def test_save_identity_returns_no_publishing_authority_or_channel(self):
        s, wire = service()
        state = initial_state(WORKSPACE)
        state['phase2'] = {'discordIdentityLinks': [], 'channels': [], 'jobs': [], 'reviews': []}
        cur = Mock()
        @contextmanager
        def local(*args):
            yield cur, state, ACTOR
        s.local = local
        s.upsert = Mock(return_value='synthetic-generation')
        s.save_state = Mock()
        result = s.save_identity(WORKSPACE, 'synthetic-session',
            {**context(), 'identityGenerations': {}},
            {'access_token': 'synthetic-access', 'expires_in': 3600},
            {'id': USER, 'username': 'Synthetic customer'}, ['identify'])
        self.assertTrue(result['connected'])
        self.assertEqual({key: result.get(key) for key in CAPABILITIES}, CAPABILITIES)
        self.assertEqual(state['phase2']['channels'], [])
        self.assertEqual(state['phase2']['jobs'], [])
        self.assertEqual(state['phase2']['reviews'], [])
        self.assertEqual(wire.lifecycle_calls, [])

    def test_identity_start_requests_only_explicit_scopes_and_explains_sender_limit(self):
        for discover in (False, True):
            with self.subTest(discover=discover):
                s, wire = service()
                cur = Mock(); cur.fetchone.return_value = ('synthetic-transaction',)
                @contextmanager
                def local(*args):
                    yield cur, initial_state(WORKSPACE), ACTOR
                s.local = local
                with patch('postriff_phase2.hosted.audit'), patch('postriff_phase2.hosted.throttle'):
                    result = s.start(WORKSPACE, 'synthetic-session', 'identity',
                        {'discordPurpose': 'identity', 'discoverGuilds': discover})
                query = parse_qs(urlsplit(result['authorizeUrl']).query)
                self.assertEqual(query['scope'], ['identify guilds' if discover else 'identify'])
                self.assertNotIn('bot', result['scopes'])
                self.assertNotIn('webhook.incoming', result['scopes'])
                self.assertNotIn('integration_type', query)
                self.assertIn('does not authorize publishing as you', result['permissionExplanation'])
                self.assertIn('server list' if discover else 'profile only', result['permissionExplanation'])
                self.assertEqual(wire.lifecycle_calls, [])


if __name__ == '__main__':
    unittest.main()
