"""Current Twitch vault facts reach both real channel projection methods.

Synthetic SQL responses and encrypted fixture credentials only. These tests check
application projection/tenant keys, not PostgreSQL RLS or live provider state.
"""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.twitch_oauth import TwitchProvider


NOW, ACCOUNT, CONNECTION = 1_800_000_000, '123456', 'twitch:123456'
WORKSPACE, SECOND, HIDDEN = 'workspace-one', 'workspace-two', 'workspace-hidden'


class ProjectionRepository:
    def __init__(self):
        self.executed, self.rows = [], []
        self.channels, self.credentials, self.memberships, self.audit = {}, {}, {}, []

    def get(self, workspace, token):
        if token != 'session' or workspace not in self.memberships:
            raise AlphaError('Workspace unavailable.', 404)
        return {'state': {'phase2': {'channels': copy.deepcopy(self.channels[workspace])}}}

    @contextmanager
    def transaction(self, token, workspace):
        self.get(workspace, token)
        yield self, None, None

    @contextmanager
    def connection_factory(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        self.rows = []
        if sql.startswith('SELECT m.workspace_id::text'):
            assert params == ('actor',)
            assert "m.status='active'" in sql and 'p.deleted_at IS NULL' in sql
            self.rows = [(workspace, role, False, False, False, False, workspace, copy.deepcopy(self.channels[workspace]))
                         for workspace, role in self.memberships.items()]
        elif sql.startswith('SELECT DISTINCT ON '):
            assert params == (list(self.memberships),)
            # Mimic the selected SQL shape, so the composite attribution test
            # catches a return to connection-only DISTINCT/lookup semantics.
            if 'DISTINCT ON (e.workspace_id,e.subject)' in sql:
                self.rows = [item for item in self.audit if item[0] in params[0]]
            else:
                newest = {}
                for workspace, connection, actor, display, at in self.audit:
                    if workspace in params[0]:
                        newest[connection] = (connection, actor, display, at)
                self.rows = list(newest.values())
        elif sql.startswith('SELECT workspace_id::text,connection_id,refresh_supported'):
            if "provider='twitch'" in sql:
                self.rows = [(ws, conn, value['refresh'], value['present'], value['expires'], value['revoked'],
                              value['scopes'], value['account'], value['access'], value['key'])
                             for (ws, conn), value in self.credentials.items() if ws in params[0]]
        elif not sql.startswith('SELECT connection_id,capability,level,evidence'):
            raise AssertionError('Unexpected projection SQL: ' + sql[:100])

    def fetchall(self):
        return self.rows


class TwitchRefreshProjectionTests(unittest.TestCase):
    def setUp(self):
        self.repo = ProjectionRepository()
        self.transport = Mock(side_effect=AssertionError('Projection must not call Twitch.'))
        self.provider = TwitchProvider('synthetic-client', 'synthetic-secret', transport=self.transport,
            clock=lambda: NOW, public_connect_enabled=True, commercial_approved=True)
        self.vault = CredentialVault(CredentialVault.generate_key())
        self.oauth = OAuthService(self.repo, None, self.vault, {'twitch': self.provider},
                                  'https://rafii.io', clock=lambda: NOW)
        self.oauth.provider_catalog = Mock(return_value=[])
        self.hosted = SimpleNamespace(verify_session=Mock(return_value='actor'), clock=lambda: NOW,
            connection_factory=self.repo.connection_factory, oauth=self.oauth)
        self.add_workspace(WORKSPACE)

    def add_workspace(self, workspace, role='owner', **overrides):
        channel = {'id': CONNECTION, 'platform': 'Twitch', 'account': 'Synthetic creator', 'accountType': 'user',
                   'configured': True, 'identityVerified': True, 'capabilityVerified': False,
                   'providerAccountId': ACCOUNT, 'scopes': ['user:write:chat'], 'expiresAt': NOW - 600,
                   'revoked': False, 'evidenceSource': 'synthetic'}
        self.repo.channels[workspace] = [channel]
        self.repo.memberships[workspace] = role
        sealed = self.provider._seal('synthetic-access', 'at', ACCOUNT, 'a' * 32)
        encrypted, key = self.vault.encrypt(sealed)
        self.repo.credentials[(workspace, CONNECTION)] = {
            'refresh': True, 'present': True, 'expires': NOW + 7200, 'revoked': False,
            'scopes': [], 'account': ACCOUNT, 'access': encrypted, 'key': key, **overrides}

    def profile(self):
        return HostedWorkspaceService.my_channels(self.hosted, 'session')['channels']

    def workspace(self, workspace=WORKSPACE):
        with patch('postriff_phase2.oauth.account_pictures.guarded', return_value={}):
            return self.oauth.channels(workspace, 'session')['channels'][0]

    def assert_private_read(self, value, before):
        serialized = json.dumps(value)
        self.assertNotIn('synthetic-access', serialized)
        self.assertNotIn('synthetic-secret', serialized)
        self.assertNotIn(self.repo.credentials[(WORKSPACE, CONNECTION)]['access'], serialized)
        self.assertNotIn('access_ciphertext', serialized)
        self.assertNotIn('refresh_ciphertext', serialized)
        self.assertEqual(self.repo.channels, before)
        self.assertFalse(any(sql.startswith(('UPDATE ', 'INSERT ', 'DELETE ')) for sql, _ in self.repo.executed))
        self.transport.assert_not_called()

    def test_current_refresh_expiry_and_zero_scope_identity_reach_both_views(self):
        before = copy.deepcopy(self.repo.channels)
        for view in (self.workspace(), self.profile()[0]):
            self.assertEqual(view['connectionState'], 'read_verified')
            self.assertTrue(view['refreshSupported'])
            self.assertEqual(view['expiresAt'], NOW + 7200)
            self.assertEqual(view['accessTokenExpiresAt'], NOW + 7200)
        self.assertEqual(self.workspace()['scopes'], [])
        self.assertEqual(self.workspace()['capabilities']['publish']['level'], 'Unsupported')
        self.assert_private_read(self.profile(), before)

    def test_expired_refreshable_access_does_not_become_false_reconnect(self):
        self.repo.credentials[(WORKSPACE, CONNECTION)]['expires'] = NOW - 1
        for view in (self.workspace(), self.profile()[0]):
            self.assertEqual(view['connectionState'], 'read_verified')
            self.assertTrue(view['refreshSupported'])
            self.assertEqual(view['expiresAt'], NOW - 1)
        self.transport.assert_not_called()

    def test_missing_or_disabled_refresh_has_the_current_custody_state(self):
        credential = self.repo.credentials[(WORKSPACE, CONNECTION)]
        for values, expected in (({'present': False, 'expires': NOW - 1}, 'token_expired'),
                                 ({'present': True, 'refresh': False}, 'client_binding_missing')):
            with self.subTest(values=values):
                credential.update(values)
                for view in (self.workspace(), self.profile()[0]):
                    self.assertEqual(view['connectionState'], expected)
                    self.assertFalse(view['refreshSupported'])

    def test_revoked_and_absent_custody_override_stale_verified_channel(self):
        self.repo.credentials[(WORKSPACE, CONNECTION)]['revoked'] = True
        for view in (self.workspace(), self.profile()[0]):
            self.assertEqual(view['connectionState'], 'reauthorization_required')
            self.assertFalse(view['refreshSupported'])
        del self.repo.credentials[(WORKSPACE, CONNECTION)]
        for view in (self.workspace(), self.profile()[0]):
            self.assertEqual(view['connectionState'], 'reauthorization_required')
            self.assertFalse(view['refreshSupported'])

    def test_client_rotation_and_wrong_subject_are_local_reconnect_facts(self):
        self.provider.client_id = 'rotated-client'
        for view in (self.workspace(), self.profile()[0]):
            self.assertEqual(view['connectionState'], 'client_binding_missing')
            self.assertTrue(view['refreshBindingRequired'])
        self.provider.client_id = 'synthetic-client'
        self.repo.credentials[(WORKSPACE, CONNECTION)]['account'] = '999999'
        for view in (self.workspace(), self.profile()[0]):
            self.assertEqual(view['connectionState'], 'client_binding_missing')
            self.assertFalse(view['refreshSupported'])
        self.transport.assert_not_called()

    def test_identical_connection_ids_keep_each_workspaces_vault_and_role_facts(self):
        self.add_workspace(SECOND, role='viewer', revoked=True, expires=NOW + 99999)
        self.add_workspace(HIDDEN, role='owner', expires=NOW + 999999)
        del self.repo.memberships[HIDDEN]
        before = copy.deepcopy(self.repo.channels)
        views = {view['workspaceId']: view for view in self.profile()}
        self.assertEqual(set(views), {WORKSPACE, SECOND})
        self.assertEqual(views[WORKSPACE]['connectionState'], 'read_verified')
        self.assertTrue(views[WORKSPACE]['canManage'])
        self.assertEqual(views[WORKSPACE]['expiresAt'], NOW + 7200)
        self.assertEqual(views[SECOND]['connectionState'], 'reauthorization_required')
        self.assertFalse(views[SECOND]['canManage'])
        self.assertEqual(views[SECOND]['expiresAt'], NOW + 99999)
        for sql, params in self.repo.executed:
            if "provider='twitch'" in sql:
                self.assertEqual(params, ([WORKSPACE, SECOND],))
        self.assert_private_read(list(views.values()), before)

    def test_connected_by_is_bound_to_workspace_and_connection_together(self):
        self.add_workspace(SECOND, role='admin')
        self.repo.audit = [(WORKSPACE, CONNECTION, 'actor-one', 'One', NOW - 100),
                           (SECOND, CONNECTION, 'actor-two', 'Two', NOW - 1)]
        views = {view['workspaceId']: view for view in self.profile()}
        self.assertEqual(views[WORKSPACE]['connectedBy'], {'userId': 'actor-one', 'displayName': 'One', 'at': NOW - 100})
        self.assertEqual(views[SECOND]['connectedBy'], {'userId': 'actor-two', 'displayName': 'Two', 'at': NOW - 1})
        self.assertTrue(any('DISTINCT ON (e.workspace_id,e.subject)' in sql for sql, _ in self.repo.executed))

    def test_serialized_mixed_provider_profiles_preserve_unrelated_state(self):
        self.add_workspace(SECOND, role='viewer')
        other = {'id': 'threads:123456', 'platform': 'Threads', 'account': 'Other provider',
                 'configured': True, 'identityVerified': True, 'capabilityVerified': True,
                 'scopes': ['threads_basic'], 'expiresAt': NOW + 500, 'providerAccountId': ACCOUNT}
        self.repo.channels[SECOND] = json.dumps([other, {'configured': False, 'platform': 'Twitch'}])
        views = self.profile()
        self.assertEqual(len(views), 2)
        self.assertEqual(views[1]['platform'], 'Threads')
        self.assertEqual(views[1]['connectionState'], 'publish_verified')
        self.assertEqual(views[1]['expiresAt'], NOW + 500)
        self.assertFalse(views[1]['canManage'])

    def test_failed_session_verification_precedes_any_projection_query(self):
        self.hosted.verify_session.side_effect = AlphaError('Sign in again.', 401)
        with self.assertRaises(AlphaError) as raised:
            self.profile()
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(self.repo.executed, [])
        self.transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
