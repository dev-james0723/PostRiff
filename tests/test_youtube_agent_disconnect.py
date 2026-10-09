"""Synthetic disconnect authority fences; no Google calls or real acceptance."""
import copy
import json
import unittest
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.oauth import OAuthService
from postriff_phase2.youtube.agent import (
    activate_policy, assert_job_authority, fleet_authorization_current,
    policy_authorization, prepare_draft, prepare_policy, queue_draft,
    revoke_connection_authority, root,
)
from test_youtube_agent import CHANNEL, CONNECTION, NOW, body, draft_and_policy, state


class AuthorityDatabase:
    """Small transaction fixture; SQL operations affect independent credential/state rows."""
    def __init__(self, value):
        self.state, self.revision, self.result, self.rowcount = value, 1, None, 0
        self.credentials = {CONNECTION: {'provider': 'youtube', 'access': 'synthetic-access', 'revoked': False},
                            'gmail-calendar': {'provider': 'google', 'access': 'synthetic-google-access', 'revoked': False}}
        self.workspace_locked, self.fail_state_write = False, False
        self.assert_fresh, self.mutate = Mock(), Mock(return_value={'revision': 3})

    @contextmanager
    def connection_factory(self):
        before = copy.deepcopy((self.state, self.revision, self.credentials))
        try:
            yield self
        except Exception:
            self.state, self.revision, self.credentials = before
            raise
        finally:
            self.workspace_locked = False

    @contextmanager
    def cursor(self):
        yield self

    @contextmanager
    def transaction(self, _token, _workspace):
        with self.connection_factory():
            self.workspace_locked = True
            yield self, (self.revision, copy.deepcopy(self.state), 'owner', False, False, False, False), 'owner'

    def execute(self, sql, params=()):
        self.rowcount = 1
        if sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.workspace_locked, self.result = True, (copy.deepcopy(self.state),)
        elif sql.startswith('SELECT provider,access_ciphertext,key_id'):
            row = self.credentials.get(params[1])
            self.result = (row['provider'], row['access'], 'synthetic-key') if row and not row['revoked'] else None
        elif sql.startswith('SELECT access_ciphertext,key_id FROM'):
            row = self.credentials.get(params[1])
            self.result = (row['access'], 'synthetic-key') if row and row['provider'] == 'youtube' and not row['revoked'] else None
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET revoked_at='):
            assert self.workspace_locked, 'Credential and policy revocation must share the workspace lock.'
            self.credentials[params[1]].update(access='', revoked=True)
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            assert self.workspace_locked
            if self.fail_state_write:
                raise RuntimeError('Synthetic workspace state failure')
            self.state, self.revision = json.loads(params[0]), self.revision + 1
        elif sql.startswith('UPDATE public.pr_channel_capabilities'):
            pass
        else:
            raise AssertionError('Unexpected authority fixture operation')

    def fetchone(self):
        return self.result

    def get(self, *_args):
        return {'revision': self.revision, 'state': copy.deepcopy(self.state)}


def oauth_fixture(value):
    database = AuthorityDatabase(value)
    oauth = OAuthService.__new__(OAuthService)
    oauth.repository, oauth.clock = database, lambda: NOW
    oauth.vault = SimpleNamespace(decrypt=lambda value, _key: value)
    oauth.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=Mock()))
    oauth._shared_elsewhere = Mock(return_value=True)
    oauth._provider_for_access = Mock()
    return oauth, database


@contextmanager
def disconnect_dependencies(after=None):
    with ExitStack() as stack:
        for target in ('postriff_phase2.hosted.audit', 'postriff_phase2.youtube.journal.purge_authorized_data',
                       'postriff_phase2.account_pictures.guarded', 'postriff_phase2.growth.history_import.mark_for_purge',
                       'postriff_phase2.product_events.record'):
            stack.enter_context(patch(target))
        stack.enter_context(patch('postriff_phase2.social_history.revoke_connection_samples', return_value=0))
        stack.enter_context(patch('postriff_phase2.growth.history_import.purge_after_disconnect', side_effect=after))
        yield


class ConnectionAuthorityTests(unittest.TestCase):
    def test_all_unrevoked_policies_are_fenced_without_removing_plans_receipts_or_other_channel(self):
        value = state()
        draft, policy = draft_and_policy(value)
        queue_draft(HostedPhase2Commands(clock=lambda: NOW), value, CONNECTION, draft['id'], 'owner', NOW, policy=policy)
        value['phase2']['jobs'][0].update(state='provider_accepted', progress={'stage': 'native_scheduled', 'videoId': 'accepted-video'})
        for status in ('prepared', 'paused'):
            root(value)['policies'].append(copy.deepcopy(policy) | {'id': status, 'status': status})
        unrelated = copy.deepcopy(policy) | {'id': 'other-policy', 'connectionId': 'other-channel'}
        root(value)['policies'].append(unrelated)
        unrelated_before = copy.deepcopy(unrelated)
        before_drafts, before_jobs = copy.deepcopy(root(value)['drafts']), copy.deepcopy(value['phase2']['jobs'])
        snapshot = policy_authorization(policy)
        candidate = ('workspace', CONNECTION, policy['id'], draft['id'], 'lease', snapshot)
        root(value)['fleetLease'] = {'id': 'lease', 'until': NOW + 120, 'authorization': snapshot}
        self.assertTrue(fleet_authorization_current(value, candidate))
        self.assertTrue(revoke_connection_authority(value, CONNECTION, 'owner', NOW + 1, reason='connection_disconnected'))
        self.assertFalse(fleet_authorization_current(value, candidate))
        self.assertNotIn('fleetLease', root(value))
        self.assertEqual(root(value)['drafts'], before_drafts)
        self.assertEqual(value['phase2']['jobs'], before_jobs)
        self.assertEqual(root(value)['policies'][-1], unrelated_before)
        with self.assertRaises(AlphaError):
            assert_job_authority(value, value['phase2']['jobs'][0], NOW + 2)
        self.assertTrue(all(p['status'] == 'revoked' for p in root(value)['policies'][:-1]))
        self.assertNotEqual(policy['authorizationGeneration'], snapshot['authorizationGeneration'])
        revoked = copy.deepcopy(root(value)['policies'])
        self.assertFalse(revoke_connection_authority(value, CONNECTION, None, NOW + 2, reason='oauth_revoked'))
        self.assertEqual(root(value)['policies'], revoked)

    def test_reconnect_preserves_manual_plan_but_requires_new_explicit_policy_activation(self):
        value = state()
        draft, policy = draft_and_policy(value)
        revoke_connection_authority(value, CONNECTION, 'owner', NOW + 1, reason='connection_disconnected')
        value['phase2']['channels'][0]['revoked'] = False  # a new OAuth grant restores only the same channel
        with self.assertRaises(AlphaError):
            activate_policy(value, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest'], 'confirmationChannelId': CHANNEL}, 'owner', NOW + 2)
        fresh = prepare_policy(value, CONNECTION, {'draftIds': [draft['id']], 'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': NOW + 86400}, 'owner', NOW + 2)
        activate_policy(value, CONNECTION, fresh['id'], {'confirmed': True, 'digest': fresh['digest'], 'confirmationChannelId': CHANNEL}, 'owner', NOW + 2)
        self.assertEqual(fresh['status'], 'active')
        self.assertEqual(policy['status'], 'revoked')
        self.assertEqual(len(root(value)['drafts']), 1)

    def test_phase2_disconnect_revokes_youtube_only_and_preserves_unrelated_lease(self):
        value = state()
        _, policy = draft_and_policy(value)
        root(value)['fleetLease'] = {'id': 'other-lease', 'authorization': {'policyId': 'other-policy'}}
        commands = HostedPhase2Commands(clock=lambda: NOW)
        commands(value, 'owner', 'p2_channel_disconnect', {'channelId': CONNECTION})
        self.assertEqual(policy['status'], 'revoked')
        self.assertTrue(value['phase2']['channels'][0]['revoked'])
        self.assertEqual(root(value)['fleetLease']['id'], 'other-lease')
        ordinary = state()
        _, active = draft_and_policy(ordinary)
        ordinary['phase2']['channels'].append({'id': 'other-platform', 'platform': 'LinkedIn'})
        commands(ordinary, 'owner', 'p2_channel_disconnect', {'channelId': 'other-platform'})
        self.assertEqual(active['status'], 'active')
        empty = {'phase2': {}}
        self.assertFalse(revoke_connection_authority(empty, CONNECTION, 'owner', NOW, reason='connection_disconnected'))
        self.assertEqual(empty, {'phase2': {}})

    def test_disconnect_transaction_revokes_authority_before_reconnect_and_has_no_late_mutation(self):
        value = state()
        _, policy = draft_and_policy(value)
        oauth, database = oauth_fixture(value)
        google = copy.deepcopy(database.credentials['gmail-calendar'])
        def reconnect(*_args):
            self.assertTrue(database.credentials[CONNECTION]['revoked'])
            self.assertEqual(root(database.state)['policies'][0]['status'], 'revoked')
            database.credentials[CONNECTION].update(access='synthetic-new-access', revoked=False)
            database.state['phase2']['channels'][0]['revoked'] = False
        with disconnect_dependencies(reconnect):
            result = oauth.disconnect('workspace', 'session', CONNECTION)
        self.assertTrue(result['disconnected'])
        self.assertFalse(database.state['phase2']['channels'][0]['revoked'])
        self.assertEqual(root(database.state)['policies'][0]['status'], 'revoked')
        self.assertEqual(database.credentials['gmail-calendar'], google)
        database.mutate.assert_not_called()
        oauth._provider_for_access.assert_not_called()

    def test_provider_revocation_fences_stale_observation_then_revokes_current_policy_atomically(self):
        value = state()
        _, policy = draft_and_policy(value)
        oauth, database = oauth_fixture(value)
        before = copy.deepcopy(database.state)
        with patch('postriff_phase2.hosted.audit'), patch('postriff_phase2.youtube.journal.purge_authorized_data') as purge:
            self.assertFalse(oauth.mark_youtube_revoked('workspace', CONNECTION, expected_access_token='synthetic-stale-access'))
            self.assertEqual(database.state, before)
            self.assertFalse(oauth.mark_youtube_revoked('workspace', CONNECTION))
            purge.assert_not_called()
            self.assertTrue(oauth.mark_youtube_revoked('workspace', CONNECTION, expected_access_token='synthetic-access'))
            purge.assert_called_once_with(database, 'workspace', CONNECTION)
        self.assertTrue(database.credentials[CONNECTION]['revoked'])
        self.assertTrue(database.state['phase2']['channels'][0]['revoked'])
        self.assertEqual(root(database.state)['policies'][0]['status'], 'revoked')
        self.assertFalse(database.credentials['gmail-calendar']['revoked'])
        self.assertEqual(database.revision, 2)

    def test_provider_revocation_rolls_back_if_policy_state_cannot_commit(self):
        value = state()
        draft_and_policy(value)
        oauth, database = oauth_fixture(value)
        before = copy.deepcopy((database.state, database.credentials, database.revision))
        database.fail_state_write = True
        with patch('postriff_phase2.hosted.audit'), patch('postriff_phase2.youtube.journal.purge_authorized_data'):
            with self.assertRaises(RuntimeError):
                oauth.mark_youtube_revoked('workspace', CONNECTION, expected_access_token='synthetic-access')
        self.assertEqual((database.state, database.credentials, database.revision), before)

    def test_generic_provider_disconnect_keeps_legacy_path_and_youtube_authority(self):
        value = state()
        _, policy = draft_and_policy(value)
        oauth, database = oauth_fixture(value)
        database.credentials['linkedin'] = {'provider': 'linkedin', 'access': 'synthetic-linkedin', 'revoked': False}
        with disconnect_dependencies():
            oauth.disconnect('workspace', 'session', 'linkedin')
        database.mutate.assert_called_once_with('workspace', 'session', 1, 'p2_channel_disconnect', {'channelId': 'linkedin'})
        self.assertEqual(root(database.state)['policies'][0]['status'], 'active')
        self.assertFalse(database.credentials[CONNECTION]['revoked'])


if __name__ == '__main__':
    unittest.main()
