"""Refresh-aware channel projection; synthetic vault facts, no Google or DB calls."""
import copy
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_phase2.channels import connection_state
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import OAuthService


NOW, WORKSPACE, CONNECTION = 1_800_000_000, 'workspace', 'channel'


class ProjectionRepository:
    def __init__(self, *, refresh=True, present=True, expires=NOW + 3480, revoked=False, scopes=None):
        self.channel = {'id': CONNECTION, 'platform': 'YouTube', 'account': 'Synthetic creator', 'accountType': 'channel',
                        'configured': True, 'identityVerified': True, 'capabilityVerified': False, 'revoked': False,
                        'providerAccountId': 'UC' + 'a' * 22, 'scopes': ['youtube.readonly'] if scopes is None else scopes,
                        'expiresAt': NOW + 1}  # Snapshot expiry is stale; the vault is authoritative.
        self.credential = (WORKSPACE, CONNECTION, refresh, present, expires, revoked)
        self.executed, self.rows = [], []

    def get(self, workspace, token):
        return {'state': {'phase2': {'channels': [copy.deepcopy(self.channel)]}}}

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if sql.startswith('SELECT workspace_id::text,connection_id,refresh_supported'):
            self.rows = [self.credential]
        elif sql.startswith('SELECT m.workspace_id::text'):
            self.rows = [(WORKSPACE, 'owner', 'active', False, False, False, 'Workspace', [copy.deepcopy(self.channel)])]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows

    @contextmanager
    def transaction(self, token, workspace):
        yield self, None, None

    @contextmanager
    def connection_factory(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self


class YouTubeRefreshProjectionTests(unittest.TestCase):
    def test_vault_refresh_and_revocation_facts_reach_both_channel_views(self):
        cases = (
            ({}, 'read_verified', True),
            ({'expires': NOW - 1}, 'read_verified', True),
            ({'present': False}, 'read_verified', False),
            ({'present': False, 'expires': NOW - 1}, 'token_expired', False),
            ({'refresh': False, 'expires': NOW - 1}, 'token_expired', False),
            ({'revoked': True}, 'reauthorization_required', False),
            ({'scopes': []}, 'scope_missing', True),
        )
        for inputs, expected_state, expected_refresh in cases:
            with self.subTest(inputs=inputs):
                repo = ProjectionRepository(**inputs)
                original = copy.deepcopy(repo.channel)
                oauth = OAuthService(repo, None, None, {}, 'https://rafii.example', clock=lambda: NOW)
                oauth.provider_catalog = Mock(return_value=[])
                with patch('postriff_phase2.oauth.account_pictures.guarded', return_value={}):
                    channel = oauth.channels(WORKSPACE, 'session')['channels'][0]
                hosted = SimpleNamespace(verify_session=lambda _: 'actor', clock=lambda: NOW, connection_factory=repo.connection_factory)
                with patch('postriff_phase2.hosted.Membership.from_row', return_value=SimpleNamespace(allows=lambda _: True)):
                    profile = HostedWorkspaceService.my_channels(hosted, 'session')['channels'][0]
                for view in (channel, profile):
                    self.assertEqual(view['connectionState'], expected_state)
                    self.assertIs(view['refreshSupported'], expected_refresh)
                    self.assertEqual(view['accessTokenExpiresAt'], repo.credential[4])
                    self.assertEqual(view['expiresAt'], repo.credential[4])
                    self.assertNotIn('refresh_ciphertext', view)
                self.assertEqual(repo.channel, original)
                self.assertFalse(any(sql.startswith(('UPDATE ', 'INSERT ', 'DELETE ')) for sql, _ in repo.executed))
                self.assertTrue(any("provider='youtube'" in sql and "refresh_ciphertext IS NOT NULL" in sql for sql, _ in repo.executed))

    def test_refresh_metadata_does_not_change_other_provider_expiry(self):
        channel = {**ProjectionRepository().channel, 'platform': 'Instagram', 'refreshSupported': True, 'expiresAt': NOW - 1}
        self.assertEqual(connection_state(channel, NOW), 'token_expired')


if __name__ == '__main__':
    unittest.main()
