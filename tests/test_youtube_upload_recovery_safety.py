"""Synthetic recovery races; no provider calls, servers or production acceptance."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.youtube.agent import queue_draft, root, revoke_connection_authority
from postriff_phase2.youtube.service import YouTubeCreatorService
from test_youtube_agent import CHANNEL, CONNECTION, NOW, body, draft_and_policy, prepare_draft, state


class RecoveryDatabase:
    def __init__(self, value, upload):
        self.state, self.upload, self.role, self.revision = value, upload, 'owner', 1
        self.result, self.credential, self.fail_commit = None, True, False
        self.assert_fresh = Mock()

    @contextmanager
    def transaction(self, _token, _workspace):
        before = copy.deepcopy((self.state, self.upload, self.revision))
        try:
            yield self, (self.revision, copy.deepcopy(self.state), self.role, False, False, False, False), 'owner'
        except Exception:
            self.state, self.upload, self.revision = before
            raise

    def execute(self, sql, params=()):
        if sql.startswith('SELECT 1 FROM public.pr_encrypted_credentials'):
            self.result = (1,) if self.credential else None
        elif sql.startswith('SELECT state FROM public.pr_youtube_uploads'):
            self.result = (copy.deepcopy(self.upload),) if self.upload else None
        elif sql.startswith('UPDATE public.pr_youtube_uploads SET state='):
            self.upload = json.loads(params[0])
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            if self.fail_commit:
                raise RuntimeError('Synthetic workspace write failure')
            self.state, self.revision = json.loads(params[0]), self.revision + 1
        else:
            raise AssertionError('Unexpected recovery fixture operation')

    def fetchone(self):
        return self.result


class RecoveryJournal:
    def __init__(self, database):
        self.database, self.save = database, Mock()

    @contextmanager
    def lock(self, _key):
        yield

    def load(self, _key):
        return copy.deepcopy(self.database.upload)


def recovery_fixture(*, autopilot=False, accepted=True):
    value = state()
    if autopilot:
        draft, policy = draft_and_policy(value)
    else:
        draft, policy = prepare_draft(value, CONNECTION, body(), 'owner', NOW), None
    commands = HostedPhase2Commands(clock=lambda: NOW)
    queue_draft(commands, value, CONNECTION, draft['id'], 'owner', NOW, policy=policy)
    job = value['phase2']['jobs'][0]
    job['state'] = 'held'
    upload = {'stage': 'held', 'options': copy.deepcopy(job['manifest']['publishOptions']),
              'bytesSent': 1000 if accepted else 0, 'totalBytes': 1000,
              'videoId': 'abcdefghijk' if accepted else None,
              'sessionCiphertext': None if accepted else 'synthetic-encrypted-session'}
    database = RecoveryDatabase(value, upload)
    creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
    creator.repository, creator.clock = database, lambda: NOW
    creator.service = SimpleNamespace(commands=commands)
    creator.journal, creator.worker_api = RecoveryJournal(database), Mock()
    creator._member = Mock(side_effect=lambda *_args, **_kwargs: ('owner', CHANNEL, copy.deepcopy(database.state)))
    return creator, database, job['manifest']['idempotencyKey']


def preview(creator, operation):
    return creator.upload_recovery('workspace', 'session', CONNECTION, operation)


def approve(creator, operation, review):
    with patch('postriff_phase2.hosted.audit'):
        return creator.upload_recovery('workspace', 'session', CONNECTION, operation,
                                       {'confirmed': True, 'digest': review['digest']})


class UploadRecoverySafetyTests(unittest.TestCase):
    def test_terminal_or_canceled_jobs_and_nonheld_journals_cannot_resume(self):
        for mutation in ({'state': 'canceled'}, {'state': 'failed'}, {'state': 'verified'},
                         {'state': 'provider_accepted'}, {'cancelRequested': True}, {'approvedBy': 'another-owner'}):
            with self.subTest(job=mutation):
                creator, database, operation = recovery_fixture()
                database.state['phase2']['jobs'][0].update(mutation)
                before = copy.deepcopy((database.state, database.upload))
                review = preview(creator, operation)
                self.assertFalse(review['manifest']['canResume'])
                with self.assertRaises(AlphaError):
                    approve(creator, operation, review)
                self.assertEqual((database.state, database.upload), before)
                creator.worker_api.assert_not_called()
        for stage in ('failed', 'canceled', 'session_expired', 'native_scheduled', 'uploading'):
            with self.subTest(stage=stage):
                creator, database, operation = recovery_fixture()
                database.upload['stage'] = stage
                self.assertFalse(preview(creator, operation)['manifest']['canResume'])

    def test_cancel_after_preflight_cannot_resurrect_job_or_change_upload(self):
        for mutation in ({'state': 'canceled', 'cancelRequested': True}, {'cancelRequested': True}, {'state': 'verified'}):
            with self.subTest(change=mutation):
                creator, database, operation = recovery_fixture()
                review = preview(creator, operation)
                before_upload = copy.deepcopy(database.upload)
                creator.worker_api.side_effect = lambda _manifest: database.state['phase2']['jobs'][0].update(mutation)
                with self.assertRaises(AlphaError):
                    approve(creator, operation, review)
                for key, value in mutation.items():
                    self.assertEqual(database.state['phase2']['jobs'][0][key], value)
                self.assertNotIn('youtubeRecoveryApproval', database.state['phase2']['jobs'][0])
                self.assertEqual(database.upload, before_upload)
                creator.journal.save.assert_not_called()

    def test_final_role_freshness_and_original_approver_are_rechecked(self):
        for change in ('viewer', 'another-approver', 'step-up'):
            with self.subTest(change=change):
                creator, database, operation = recovery_fixture()
                review = preview(creator, operation)
                before_upload = copy.deepcopy(database.upload)
                def change_authorization(_manifest):
                    if change == 'viewer':
                        database.role = 'viewer'
                    elif change == 'another-approver':
                        database.state['phase2']['jobs'][0]['approvedBy'] = 'another-owner'
                    else:
                        database.assert_fresh.side_effect = AlphaError('Sign in again.', 403)
                creator.worker_api.side_effect = change_authorization
                with self.assertRaises(AlphaError):
                    approve(creator, operation, review)
                self.assertEqual(database.state['phase2']['jobs'][0]['state'], 'held')
                self.assertEqual(database.upload, before_upload)

    def test_paused_revoked_or_owner_demoted_autopilot_requires_current_owner_authority(self):
        for change in ('pause', 'revoke', 'demote'):
            with self.subTest(change=change):
                creator, database, operation = recovery_fixture(autopilot=True)
                review = preview(creator, operation)
                self.assertTrue(review['manifest']['canResume'])
                before_upload = copy.deepcopy(database.upload)
                def change_policy(_manifest):
                    if change == 'demote':
                        database.role = 'approver'
                    elif change == 'pause':
                        root(database.state)['policies'][0]['status'] = 'paused'
                    else:
                        revoke_connection_authority(database.state, CONNECTION, 'owner', NOW, reason='connection_disconnected')
                creator.worker_api.side_effect = change_policy
                with self.assertRaises(AlphaError):
                    approve(creator, operation, review)
                self.assertEqual(database.state['phase2']['jobs'][0]['state'], 'held')
                self.assertEqual(database.upload, before_upload)
                self.assertNotIn('youtubeRecoveryApproval', database.state['phase2']['jobs'][0])

    def test_purged_or_changed_upload_is_not_recreated_from_stale_preview(self):
        for change in ('purge', 'cancel', 'reconcile'):
            with self.subTest(change=change):
                creator, database, operation = recovery_fixture()
                review = preview(creator, operation)
                def change_journal(_manifest):
                    if change == 'purge':
                        database.upload = None
                    elif change == 'cancel':
                        database.upload['cancelRequested'] = True
                    else:
                        database.upload['stage'] = 'native_scheduled'
                creator.worker_api.side_effect = change_journal
                with self.assertRaises(AlphaError):
                    approve(creator, operation, review)
                self.assertEqual(database.state['phase2']['jobs'][0]['state'], 'held')
                if change == 'purge':
                    self.assertIsNone(database.upload)
                else:
                    self.assertNotIn('recoveryAttempts', database.upload)
                creator.journal.save.assert_not_called()

    def test_job_write_failure_rolls_back_the_upload_recovery_update(self):
        creator, database, operation = recovery_fixture()
        review = preview(creator, operation)
        before = copy.deepcopy((database.state, database.upload, database.revision))
        database.fail_commit = True
        with self.assertRaises(RuntimeError):
            approve(creator, operation, review)
        self.assertEqual((database.state, database.upload, database.revision), before)
        creator.journal.save.assert_not_called()

    def test_valid_recovery_preserves_same_session_or_video_and_commits_exact_job_once(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                creator, database, operation = recovery_fixture(accepted=accepted)
                review = preview(creator, operation)
                before = copy.deepcopy(database.upload)
                result = approve(creator, operation, review)
                self.assertTrue(result['resumed'])
                self.assertFalse(result['replacementUpload'])
                self.assertEqual(database.upload['videoId'], before['videoId'])
                self.assertEqual(database.upload['sessionCiphertext'], before['sessionCiphertext'])
                self.assertEqual(database.upload['bytesSent'], before['bytesSent'])
                self.assertEqual(database.upload['stage'], 'uploaded_private' if accepted else 'uploading')
                job = database.state['phase2']['jobs'][0]
                self.assertEqual(job['state'], 'provider_accepted')
                self.assertEqual(job['manifest']['idempotencyKey'], operation)
                self.assertEqual(job['youtubeRecoveryApproval']['expiresAt'], NOW + 36 * 3600)
                self.assertEqual(len(database.state['phase2']['jobs']), 1)
                self.assertFalse(preview(creator, operation)['manifest']['canResume'])
                creator.journal.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
