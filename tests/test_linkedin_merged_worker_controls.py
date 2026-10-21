"""Merged LinkedIn worker controls with in-memory SQL; no native DB or live provider proof."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from test_hosted_job_dispatch import Repository, TOKEN
import test_youtube_worker_refresh as controls

NOW, worker_for = controls.NOW, controls.worker_for


def linkedin_worker():
    worker, db, now, order, reverify = worker_for(1)
    channel = db.state['phase2']['channels'][0]
    channel.update(platform='LinkedIn', expiresAt=NOW + 7200, scopes=['w_member_social'])
    job = db.state['phase2']['jobs'][0]
    job['manifest'].update(platform='LinkedIn', capability={'scopes': ['w_member_social'], 'version': 1})
    job['approvalDigest'] = digest(job['manifest'])
    worker.social = SimpleNamespace(oauth=worker.social.youtube.oauth,
                                   submit=worker.social.submit, reconcile=worker.social.reconcile)
    return worker, db, now, order, reverify


class LinkedInMergedWorkerControls(unittest.TestCase):
    setUp = controls.YouTubeWorkerRefreshTests.setUp

    @patch('postriff_phase2.billing.require_publishing')
    def test_stale_identity_reverified_outside_locks_before_one_submission(self, _billing):
        worker, db, _, order, _ = linkedin_worker()
        frozen = copy.deepcopy(db.state['phase2']['jobs'][0]['manifest'])
        self.assertTrue(worker.step(linkedin_only=True))
        self.assertEqual(order, [('verify', 'connection-0'), ('submit', 'connection-0')])
        saved = db.state['phase2']['jobs'][0]
        self.assertEqual(saved['manifest'], frozen)
        self.assertEqual(saved['approvalDigest'], digest(frozen))
        self.assertEqual(len(saved['attempts']), 1)

    @patch('postriff_phase2.billing.require_publishing')
    def test_cancel_during_reverification_wins_without_submission(self, _billing):
        worker, db, _, _, reverify = linkedin_worker()
        def cancel(workspace, connection):
            result = reverify(workspace, connection)
            db.state['phase2']['jobs'][0]['cancelRequested'] = True
            return result
        worker.social.oauth.reverify_for_worker.side_effect = cancel
        self.assertTrue(worker.step(linkedin_only=True))
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'canceled')
        worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_identity_scope_version_and_approval_drift_block_dispatch(self, _billing):
        for field, value in [('providerAccountId', 'other-account'), ('scopes', ['openid']), ('capabilityVersion', 2), ('revoked', True)]:
            with self.subTest(field=field):
                worker, db, _, _, reverify = linkedin_worker()
                def changed(workspace, connection):
                    result = reverify(workspace, connection)
                    db.state['phase2']['channels'][0][field] = value
                    return result
                worker.social.oauth.reverify_for_worker.side_effect = changed
                self.assertTrue(worker.step(linkedin_only=True))
                self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')
                worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_approval_expiry_during_reverification_never_extended(self, _billing):
        worker, db, now, _, reverify = linkedin_worker()
        original = db.state['phase2']['jobs'][0]['manifest']['expiresAt']
        def expired(workspace, connection):
            result = reverify(workspace, connection)
            now[0] = original + 1
            return result
        worker.social.oauth.reverify_for_worker.side_effect = expired
        worker.step(linkedin_only=True)
        self.assertEqual(db.state['phase2']['jobs'][0]['manifest']['expiresAt'], original)
        worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_unknown_provider_outcome_reconciles_after_lease_expiry_without_create(self, _billing):
        worker, db, now, _, _ = linkedin_worker()
        worker.social.submit.side_effect = TimeoutError('Synthetic response lost')
        self.assertTrue(worker.step(crash='after_provider', linkedin_only=True))
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'submitting')
        now[0] += 181
        self.assertTrue(worker.step(linkedin_only=True))
        worker.social.submit.assert_called_once()
        worker.social.reconcile.assert_called_once()
        self.assertEqual(len(db.state['phase2']['jobs'][0]['attempts']), 1)

    @patch('postriff_phase2.billing.require_publishing')
    def test_future_canceled_and_mismatched_approval_cannot_dispatch(self, _billing):
        for change in ('future', 'canceled', 'digest', 'actor'):
            with self.subTest(change=change):
                worker, db, _, _, _ = linkedin_worker()
                job = db.state['phase2']['jobs'][0]
                if change == 'future': job['nextAt'] = NOW + 60
                elif change == 'canceled': job['cancelRequested'] = True
                elif change == 'digest': job['approvalDigest'] = 'f' * 64
                else: job['approvedBy'] = 'other-member'
                worker.step(linkedin_only=True)
                worker.social.submit.assert_not_called()

    def test_interactive_linkedin_dispatch_binds_workspace_content_and_role(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        repo = Repository()
        repo.job['manifest']['platform'] = 'LinkedIn'
        repo.job['approvalDigest'] = digest(repo.job['manifest'])
        worker = PostgresWorker(None)
        worker.step = Mock(return_value=True)
        worker.execute_job(repo, 'workspace-one', TOKEN, 'job-one', repo.job['approvalDigest'])
        worker.step.assert_called_once_with(workspace_id='workspace-one', job_id='job-one',
            approval_digest=repo.job['approvalDigest'], dispatch_principal='member-one')
        for change in ('content', 'tenant', 'role'):
            with self.subTest(change=change):
                worker.step.reset_mock()
                repo = Repository()
                repo.job['manifest']['platform'] = 'LinkedIn'
                repo.job['approvalDigest'] = digest(repo.job['manifest'])
                if change == 'content': repo.job['manifest']['payload']['text'] = 'Changed'
                elif change == 'tenant': repo.job['manifest']['workspaceId'] = 'foreign'
                else: repo.role = 'viewer'
                with self.assertRaises(AlphaError):
                    worker.execute_job(repo, 'workspace-one', TOKEN, 'job-one', repo.job['approvalDigest'])
                worker.step.assert_not_called()
