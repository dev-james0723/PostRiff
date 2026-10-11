"""Synthetic fixed-field erasure contracts. No provider/model or database I/O."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.youtube import agent, privacy_erasure as private
from postriff_phase2.youtube.service import YouTubeCreatorService, fingerprint

NOW = 1800000000
WORKSPACE, CONNECTION = 'workspace-one', 'youtube-connection-one'
CHANNEL, VIDEO = 'UC' + 'a' * 22, 'abcdefghijk'


def fixture(connection=CONNECTION, workspace=WORKSPACE):
    manifest = {'workspaceId': workspace, 'platform': 'YouTube', 'channelId': connection,
                'account': 'API channel title', 'providerAccountId': CHANNEL,
                'capability': {'verifiedAt': NOW, 'scopes': ['youtube.readonly']},
                'actor': 'owner', 'idempotencyKey': 'application-operation',
                'payload': {'text': 'User text quoting ' + CHANNEL},
                'media': [{'id': 'user-media', 'hash': 'original-media-digest'}],
                'publishOptions': {'title': 'My title ' + VIDEO, 'playlistIds': ['user-selected-playlist']}}
    draft = {'id': 'draft-one', 'connectionId': connection, 'channelId': CHANNEL,
             'assetId': 'user-media', 'assetHash': 'original-media-digest', 'variantId': 'variant-one',
             'publishOptions': copy.deepcopy(manifest['publishOptions']), 'createdAt': NOW,
             'createdBy': 'owner', 'status': 'queued', 'jobId': 'job-one'}
    draft['digest'] = agent.draft_digest(draft)
    policy = {'id': 'policy-one', 'connectionId': connection, 'channelId': CHANNEL,
              'drafts': [{'id': draft['id'], 'digest': draft['digest']}], 'assetIds': ['user-media'],
              'createdAt': NOW, 'status': 'active', 'grantedBy': 'owner', 'grantedAt': NOW,
              'authorizationGeneration': 'application-generation'}
    policy['digest'] = agent.policy_digest(policy)
    return {'phase2': {'reviews': [{'id': 'review-one', 'manifest': copy.deepcopy(manifest), 'digest': digest(manifest),
                                   'status': 'approved', 'createdAt': NOW}],
                       'jobs': [{'id': 'job-one', 'manifest': manifest, 'approvalDigest': digest(manifest),
                                 'approvedBy': 'owner', 'approvedAt': NOW, 'state': 'processing',
                                 'leaseOwner': 'worker', 'leaseId': 'lease', 'leaseUntil': NOW + 45}]},
            'youtubeAgent': {'drafts': [draft], 'policies': [policy]},
            'userNotes': 'My independently entered ID ' + CHANNEL}


class PrivacyErasureTests(unittest.TestCase):
    def test_exact_fixed_slots_preserve_original_digests_actor_time_and_user_content(self):
        state = fixture()
        before = copy.deepcopy(state)
        counts = private.scrub_workspace(state, WORKSPACE, CONNECTION, NOW)
        self.assertEqual(counts, {'reviews': 1, 'jobs': 1, 'drafts': 1, 'policies': 1})
        for family, digest_key in (('reviews', 'digest'), ('jobs', 'approvalDigest')):
            saved, old = state['phase2'][family][0], before['phase2'][family][0]
            self.assertEqual(saved[digest_key], old[digest_key])
            self.assertNotEqual(digest(saved['manifest']), saved[digest_key])
            for key in ('payload', 'media', 'publishOptions', 'actor', 'channelId'):
                self.assertEqual(saved['manifest'][key], old['manifest'][key])
            self.assertNotIn('providerAccountId', saved['manifest'])
            self.assertNotIn('account', saved['manifest'])
            self.assertTrue(saved['privacyErased'] and saved['manifest']['privacyErased'])
        for family in ('drafts', 'policies'):
            saved, old = state['youtubeAgent'][family][0], before['youtubeAgent'][family][0]
            self.assertEqual(saved['digest'], old['digest'])
            self.assertEqual(saved['channelId'], '')
            for key in ('id', 'connectionId', 'createdAt'):
                self.assertEqual(saved[key], old[key])
        self.assertEqual(state['userNotes'], before['userNotes'])
        self.assertIn(CHANNEL, json.dumps(state['phase2']['jobs'][0]['manifest']['payload']))
        self.assertEqual(state['phase2']['jobs'][0]['state'], 'held')
        self.assertEqual(state['phase2']['jobs'][0]['leaseUntil'], 0)
        self.assertEqual(private.scrub_workspace(state, WORKSPACE, CONNECTION, NOW + 1), dict.fromkeys(counts, 0))

    def test_foreign_workspace_connection_and_other_platform_remain_unchanged(self):
        for state, workspace, connection in ((fixture(), 'another-workspace', 'another-connection'),
                                             (fixture(connection='foreign-connection'), WORKSPACE, CONNECTION)):
            before = copy.deepcopy(state)
            self.assertFalse(any(private.scrub_workspace(state, workspace, connection, NOW).values()))
            self.assertEqual(state, before)
        state = fixture()
        for family in ('reviews', 'jobs'):
            state['phase2'][family][0]['manifest']['platform'] = 'Gmail'
        before = copy.deepcopy(state['phase2'])
        private.scrub_workspace(state, WORKSPACE, CONNECTION, NOW)
        self.assertEqual(state['phase2'], before)

    def test_source_clock_not_recent_approval_or_unknown_clock_extends_retention(self):
        state = fixture()
        state['phase2']['jobs'][0]['manifest']['capability']['verifiedAt'] = NOW - private.RETENTION_SECONDS
        counts = private.scrub_workspace(state, WORKSPACE, CONNECTION, NOW, expired_only=True)
        self.assertEqual(counts, {'reviews': 0, 'jobs': 1, 'drafts': 0, 'policies': 0})
        self.assertTrue(private._expired({}, NOW))
        self.assertTrue(private._expired({'createdAt': NOW + 1}, NOW))
        self.assertFalse(private._expired({'createdAt': NOW}, NOW))
        self.assertTrue(private._expired({'createdAt': False}, NOW))

    def test_erased_agent_approvals_never_reactivate_dispatch_or_use_existing_job(self):
        state = fixture()
        private.scrub_workspace(state, WORKSPACE, CONNECTION, NOW)
        draft, policy = state['youtubeAgent']['drafts'][0], state['youtubeAgent']['policies'][0]
        commands = Mock()
        for call in (lambda: agent.assert_draft_current(state, draft, NOW),
                     lambda: agent.activate_policy(state, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest']}, 'owner', NOW),
                     lambda: agent.assert_policy(state, policy, draft, NOW),
                     lambda: agent.queue_draft(commands, state, CONNECTION, draft['id'], 'owner', NOW)):
            with self.assertRaises(AlphaError) as caught:
                call()
            self.assertEqual(caught.exception.code, 'youtube_privacy_erased')
        commands.assert_not_called()

    def test_erased_action_returns_exact_error_before_provider_or_manifest_access(self):
        cursor = Mock()
        cursor.fetchone.return_value = ({'privacyErased': True, 'action': 'playlist.create'}, 'old-approved-digest', 'privacy_erased', None, 'owner')
        @contextmanager
        def transaction(*args):
            yield cursor, (1, {}, 'owner'), 'owner'
        creator = object.__new__(YouTubeCreatorService)
        creator.repository = SimpleNamespace(transaction=transaction)
        creator._api = Mock(side_effect=AssertionError('No provider dispatch'))
        with self.assertRaises(AlphaError) as caught:
            creator.approve(WORKSPACE, 'synthetic-session', CONNECTION, 'action-one', {'confirmed': True, 'digest': 'old-approved-digest'})
        self.assertEqual(caught.exception.code, 'youtube_privacy_erased')
        creator._api.assert_not_called()

    def test_old_api_revocation_error_carries_exact_generation(self):
        creator = object.__new__(YouTubeCreatorService)
        creator.oauth = SimpleNamespace(mark_youtube_revoked=Mock())
        error = AlphaError('Synthetic revoked authorization', 409, code='youtube_revoked_oauth')
        creator.operational_error(WORKSPACE, CONNECTION, error, 'videos.list',
                                  expected_access_token='same-token', expected_generation='old-consent')
        creator.oauth.mark_youtube_revoked.assert_called_once_with(WORKSPACE, CONNECTION,
            expected_access_token='same-token', expected_generation='old-consent')

    def test_late_success_or_error_cannot_restore_erased_action_receipt(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                plan = {'method': 'playlists.insert', 'body': {'snippet': {'title': 'User title'}}}
                manifest = {'action': 'playlist.create', 'eligibilityProbe': False, 'destructive': False,
                            'approvalExpiresAt': NOW + 600, 'channelId': CHANNEL, 'inputs': {}, 'plan': plan}
                cursor = Mock()
                cursor.fetchone.return_value = (manifest, fingerprint(manifest), 'prepared', None, 'owner')
                def execute(sql, params=()):
                    cursor.rowcount = 0 if 'privacy_erased_at IS NULL' in sql else 1
                cursor.execute.side_effect = execute
                @contextmanager
                def transaction(*args):
                    yield cursor, (1, {}, 'owner'), 'owner'
                @contextmanager
                def connection():
                    yield SimpleNamespace(cursor=lambda: cursor)
                cursor.__enter__ = Mock(return_value=cursor)
                cursor.__exit__ = Mock(return_value=False)
                api = SimpleNamespace(grant={'authorizationGeneration': 'consent-one'},
                    provider=SimpleNamespace(real_transport=False), plan=Mock(return_value=plan),
                    execute=Mock(side_effect=OSError('synthetic network loss') if failed else None, return_value={'id': VIDEO}))
                creator = object.__new__(YouTubeCreatorService)
                creator.repository = SimpleNamespace(transaction=transaction)
                creator.service = SimpleNamespace(connection_factory=connection)
                creator.clock = lambda: NOW
                creator._member = Mock(return_value=('owner', CHANNEL, {}))
                creator._api, creator._allow = Mock(return_value=api), Mock()
                creator.never_published = Mock(return_value=False)
                creator.journal = SimpleNamespace(assert_authorized=Mock())
                creator.verify_action = Mock(side_effect=AssertionError('Erased action must stop before readback'))
                with patch('postriff_phase2.hosted.throttle'):
                    result = creator.approve(WORKSPACE, 'synthetic-session', CONNECTION, 'action-one',
                                             {'confirmed': True, 'digest': fingerprint(manifest)})
                self.assertEqual(result['status'], 'privacy_erased')
                self.assertIsNone(result['receipt'])
                self.assertTrue(result['dataRemoved'])
                creator.verify_action.assert_not_called()
                self.assertTrue(any('privacy_erased_at IS NULL' in call.args[0] for call in cursor.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
