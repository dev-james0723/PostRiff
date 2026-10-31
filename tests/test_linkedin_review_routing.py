"""Real worker/HostedSocial routing under the shared official-social flag; fake I/O."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import contextmanager

from postriff_phase2.contracts import digest
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.wave3_connectors import PinterestProvider
from test_linkedin_publishing_recovery import approved_member_app
from test_official_social import response
import test_youtube_worker_refresh as controls
import test_pinterest_schedule_reverification as pinterest_controls
import test_youtube_creator as creator_controls
import test_pinterest_trial_visibility as trial_controls
from postriff_phase2.youtube.model import YouTubeError


def shared_youtube_worker(*args, **kw):
    result = original_youtube_worker(*args, **kw)
    result[0].social.official_enabled = Mock(return_value=True)
    result[0].social.advance_official = Mock(side_effect=AssertionError('Legacy YouTube takeover'))
    return result


original_youtube_worker = controls.worker_for
original_pinterest_worker = pinterest_controls.pinterest_worker


def shared_pinterest_worker():
    result = original_pinterest_worker()
    result[0].social.providers = {'pinterest': SimpleNamespace(official_social_enabled=True)}
    result[0].social.advance_official = Mock(side_effect=AssertionError('Legacy Pinterest takeover'))
    return result


class SharedFlagRouting(unittest.TestCase):
    setUp = controls.YouTubeWorkerRefreshTests.setUp

    def test_shared_flag_preserves_youtube_cancel_lease_takeover_and_reconnect_fences(self):
        with patch.object(controls, 'worker_for', shared_youtube_worker):
            controls.YouTubeWorkerRefreshTests.test_new_cancellation_or_changed_fence_during_refresh_stops_forward_work(self)
            controls.YouTubeWorkerRefreshTests.test_disconnect_hold_or_terminal_state_survives_reconnect_during_refresh(self)
            controls.YouTubeWorkerRefreshTests.test_revoked_grant_identity_scope_digest_and_approval_changes_block(self)

    def test_shared_flag_preserves_youtube_owner_pause(self):
        with patch.object(controls, 'worker_for', shared_youtube_worker):
            controls.YouTubeWorkerRefreshTests.test_autopilot_pause_before_claim_and_during_refresh_stops_forward_work(self)

    def test_shared_flag_keeps_private_trial_policy_locked_body_and_visibility(self):
        host, provider, contexts = trial_controls.fixture()
        provider.official_social_enabled = True
        host.official.additional.pinterest = Mock(side_effect=AssertionError('Legacy takeover'))
        manifest = trial_controls.manifest()
        context = {'leaseId': 'synthetic-lease', 'leaseOwner': 'worker'}
        result = host.submit(manifest, dispatch_context=context)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(result['visibility'], 'creator_only_trial')
        provider.trial_policy.require_manifest.assert_called_with(manifest)
        self.assertEqual(contexts[0]['fence'], context)
        self.assertEqual(contexts[0]['kwargs']['trial_pin'], provider.api.call_args.kwargs['body'])
        host.official.additional.pinterest.assert_not_called()

    def test_shared_flag_preserves_pinterest_cancel_reconnect_and_lease_takeover(self):
        with patch.object(pinterest_controls, 'pinterest_worker', shared_pinterest_worker):
            pinterest_controls.PinterestScheduleReverification.test_disconnect_reconnect_cancel_and_lease_takeover_during_read_never_post(self)

    def test_shared_flag_hosted_youtube_reaches_real_quota_delayed_journal_without_transport(self):
        case = creator_controls.UploadTests(); case.setup_engine()
        case.m['platform'] = 'YouTube'
        def denied(*args):
            raise YouTubeError('capacity_delay', 'Synthetic quota denial', status=429, retry_at=case.clock[0]+60)
        case.engine.account_usage = denied
        provider = SimpleNamespace(official_social_enabled=True, execution_enabled=True, creator_enabled=True)
        host = HostedSocial(SimpleNamespace(), {'youtube': provider})
        host.youtube = SimpleNamespace(upload=case.engine.step)
        host.official.additional.youtube = Mock(side_effect=AssertionError('Legacy takeover'))
        result = host.submit(case.m)
        self.assertEqual(result['progress']['stage'], 'quota_delayed')
        self.assertEqual(case.wire.calls, [])
        self.assertNotIn('session_open_attempted', [item['stage'] for item in case.journal.saves])
        host.official.additional.youtube.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_real_worker_routes_youtube_pinterest_and_linkedin_to_their_own_dispatchers(self, _billing):
        for platform in ('YouTube', 'Pinterest', 'LinkedIn'):
            with self.subTest(platform=platform):
                worker, db, _, _, _ = controls.worker_for(1)
                channel = db.state['phase2']['channels'][0]
                channel.update(platform=platform, verifiedAt=controls.NOW, expiresAt=controls.NOW+3600)
                manifest = db.state['phase2']['jobs'][0]['manifest']
                manifest['platform'] = platform
                db.state['phase2']['jobs'][0]['approvalDigest'] = digest(manifest)
                oauth = worker.social.youtube.oauth
                provider = SimpleNamespace(official_social_enabled=True)
                host = HostedSocial(oauth, {platform.lower(): provider})
                if platform == 'YouTube': host.youtube = worker.social.youtube
                host.submit = Mock(return_value={'state': 'provider_accepted'})
                host.advance_official = Mock(return_value={'state': 'provider_accepted'})
                worker.social = host
                self.assertTrue(worker.step())
                if platform == 'LinkedIn':
                    host.advance_official.assert_called_once()
                    host.submit.assert_not_called()
                else:
                    host.submit.assert_called_once()
                    host.advance_official.assert_not_called()
                if platform == 'Pinterest':
                    self.assertEqual(host.submit.call_args.kwargs['dispatch_context']['leaseOwner'], worker.worker_id)

    def test_hosted_youtube_reconcile_keeps_journal_path_even_with_old_upload_fields(self):
        provider = SimpleNamespace(official_social_enabled=True, execution_enabled=True, creator_enabled=True)
        host = HostedSocial(SimpleNamespace(token_for_worker=lambda *a: {'accessToken': 'synthetic-only', 'scopes': []}), {'youtube': provider})
        host.youtube = SimpleNamespace(upload=Mock(return_value={'state': 'processing'}))
        host.official.additional.youtube = Mock(side_effect=AssertionError('Legacy takeover'))
        manifest = {'platform': 'YouTube', 'workspaceId': 'W', 'channelId': 'C', 'payload': {'text': 'Approved'}, 'publishOptions': {}}
        result = host.reconcile(manifest, {'providerUpload': {'old': True}, 'progress': {'version': 2}, 'cancelRequested': True})
        self.assertEqual(result['state'], 'processing')
        host.youtube.upload.assert_called_once_with(manifest, cancel=True, reconciliation=True)
        host.official.additional.youtube.assert_not_called()

    def test_hosted_pinterest_submit_keeps_locked_dispatch_visibility_and_actual_section(self):
        provider = PinterestProvider('synthetic-app', 'synthetic-secret')
        provider.official_social_enabled = provider.production_reviewed = True
        provider.identity = Mock(return_value={'providerAccountId': '12345'})
        provider.destinations = Mock(return_value=[{'id': '12345', 'eligible': True}])
        provider.sections = Mock(return_value=[{'id': '67890'}])
        provider.api = Mock(return_value=response({'id': '123456789'}, 201))
        dispatches = []
        @contextmanager
        def locked(manifest, token, context, **kw):
            dispatches.append((copy.deepcopy(manifest), context))
            yield {}
        oauth = SimpleNamespace(token_for_worker=lambda *a: {'accessToken': 'synthetic-only', 'scopes': list(provider.publish_required)}, pinterest_dispatch=locked)
        host = HostedSocial(oauth, {'pinterest': provider})
        host._image_url = Mock(return_value='https://media.example.invalid/image.jpg')
        host.official.additional.pinterest = Mock(side_effect=AssertionError('Legacy takeover'))
        manifest = {'platform': 'Pinterest', 'workspaceId': 'W', 'channelId': 'C', 'providerAccountId': '12345',
            'payload': {'text': 'Approved'}, 'publishOptions': {'boardId': '12345', 'boardSectionId': '67890', 'title': '', 'link': ''},
            'media': [{'mime': 'image/jpeg', 'bytes': 100, 'width': 600, 'height': 900, 'alt': 'Approved alt'}]}
        context = {'leaseId': 'synthetic-lease', 'leaseOwner': 'worker'}
        result = host.submit(manifest, dispatch_context=context)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(dispatches[0][1], context)
        self.assertEqual(provider.api.call_args.kwargs['body']['board_section_id'], '67890')
        self.assertIn(result['visibility'], ('creator_only_sandbox', 'unverified'))
        host.official.additional.pinterest.assert_not_called()
