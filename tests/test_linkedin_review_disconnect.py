"""Workspace-lock disconnect/reconnect controls; native PostgreSQL races are UNVERIFIED."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import OAuthService
from postriff_phase2.store import Phase2Store
from test_linkedin_review_regressions import NOW
import test_linkedin_merged_worker_controls as worker_controls


class DisconnectRepository:
    def __init__(self):
        self.depth, self.revision, self.result = 0, 1, None
        self.credential, self.capability = 'synthetic-old-cipher', 'Direct'
        self.state = {'phase2': {'channels': [{'id': 'C', 'platform': 'LinkedIn',
            'providerAccountId': 'urn:li:person:abc', 'capabilityVersion': 1,
            'revoked': False, 'identityVerified': True, 'capabilityVerified': True}],
            'reviews': [{'status': 'needs_review', 'manifest': {'channelId': 'C', 'platform': 'LinkedIn'}}],
            'jobs': [{'id': state, 'state': state, 'manifest': {'channelId': 'C', 'platform': 'LinkedIn'},
                      'leaseOwner': 'old-worker', 'leaseId': 'old-lease', 'leaseUntil': NOW+45,
                      'attempts': [], 'events': []} for state in ('approved', 'scheduled', 'claimed', 'submitting')],
            'nativeSocialActions': [{'id': 'native-preview', 'state': 'preview', 'manifest': {'connectionId': 'C', 'platform': 'LinkedIn'}},
                                    {'id': 'native-inflight', 'state': 'submitting', 'manifest': {'connectionId': 'C', 'platform': 'LinkedIn'}}]}}
        self.mutate = Mock(side_effect=AlphaError('Synthetic revision conflict', 409))
        self.connection_factory = Mock(side_effect=AssertionError('No real database'))
        self.committed = []

    @contextmanager
    def transaction(self, *args):
        self.depth += 1
        before = copy.deepcopy((self.state, self.credential, self.capability))
        try:
            yield self, [self.revision, copy.deepcopy(self.state), 'owner', False, False, False, False], 'owner'
        except BaseException:
            self.state, self.credential, self.capability = before
            raise
        else:
            self.committed.append(copy.deepcopy((self.state, self.credential, self.capability)))
        finally:
            self.depth -= 1

    def execute(self, sql, params=()):
        if sql.startswith('SELECT provider,access_ciphertext,key_id'):
            self.result = ('linkedin', self.credential, 'synthetic-key') if self.credential else None
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET revoked_at'):
            self.credential = None
        elif sql.startswith('UPDATE public.pr_channel_capabilities'):
            self.capability = 'Unsupported'
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.state = json.loads(params[0]); self.revision += 1
        elif sql.startswith('INSERT INTO public.pr_audit_events'):
            pass
        else:
            raise AssertionError(sql)

    def fetchone(self): return self.result
    def assert_fresh(self, *a): pass
    def get(self, *a): return {'state': copy.deepcopy(self.state), 'revision': self.revision}

    def reconnect(self):
        assert self.depth == 0
        self.credential, self.capability = 'synthetic-new-cipher', 'Direct'
        channel = self.state['phase2']['channels'][0]
        channel.update(revoked=False, identityVerified=True, capabilityVerified=True,
                       capabilityVersion=channel['capabilityVersion']+1)
        self.revision += 1


class LinkedInAtomicDisconnect(unittest.TestCase):
    def setUp(self):
        self.repo = DisconnectRepository()
        self.oauth = OAuthService.__new__(OAuthService)
        self.oauth.repository, self.oauth.clock = self.repo, lambda: NOW
        self.oauth.vault = SimpleNamespace(decrypt=Mock(side_effect=lambda ciphertext, key: ciphertext))
        self.provider = SimpleNamespace(revoke=Mock(return_value=True))
        self.oauth._provider_for_access = Mock(return_value=self.provider)
        self.oauth._shared_elsewhere = Mock(return_value=False)
        engine = Phase2Store.__new__(Phase2Store)
        engine.clock = lambda: NOW
        engine.current = lambda state, manifest: not state['phase2']['channels'][0]['revoked']
        # The repair must explicitly hold pending jobs even if the old invalidator
        # fails to recognize changed channel authority.
        engine.invalidate = Mock()
        self.oauth.commands = SimpleNamespace(engine=engine)
        for name in ('postriff_phase2.account_pictures.guarded',
                     'postriff_phase2.growth.history_import.mark_for_purge',
                     'postriff_phase2.product_events.record'):
            p = patch(name); p.start(); self.addCleanup(p.stop)
        p = patch('postriff_phase2.growth.history_import.purge_after_disconnect')
        self.purge = p.start(); self.addCleanup(p.stop)

    def disconnect(self):
        return self.oauth.disconnect('W', 'session', 'C')

    def assert_old_authority_held(self, state):
        data = state['phase2']
        self.assertEqual(data['reviews'][0]['status'], 'stale')
        for item in data['jobs'][:3]:
            self.assertEqual(item['state'], 'held')
            self.assertIsNone(item['leaseId'])
        self.assertEqual(data['jobs'][3]['state'], 'uncertain')
        self.assertEqual([a['state'] for a in data['nativeSocialActions']], ['held', 'uncertain'])

    def test_credentials_capabilities_channel_and_pending_authority_commit_together(self):
        result = self.disconnect()
        state, credential, capability = self.repo.committed[0]
        self.assertIsNone(credential)
        self.assertEqual(capability, 'Unsupported')
        self.assertTrue(state['phase2']['channels'][0]['revoked'])
        self.assertFalse(state['phase2']['channels'][0]['capabilityVerified'])
        self.assertGreater(state['phase2']['channels'][0]['capabilityVersion'], 1)
        self.assert_old_authority_held(state)
        self.repo.mutate.assert_not_called()
        self.assertTrue(result['disconnected'])

    def test_disconnect_then_reconnect_preserves_new_grant_without_delayed_mutation(self):
        self.purge.side_effect = lambda *a: self.repo.reconnect()
        result = self.disconnect()
        self.assertEqual(self.repo.credential, 'synthetic-new-cipher')
        self.assertFalse(self.repo.state['phase2']['channels'][0]['revoked'])
        self.assert_old_authority_held(self.repo.state)
        self.repo.mutate.assert_not_called()
        self.assertEqual(result['revision'], self.repo.revision)
        self.provider.revoke.assert_not_called()

    def test_reconnect_then_disconnect_removes_current_local_authority(self):
        self.repo.reconnect()
        self.disconnect()
        self.assertIsNone(self.repo.credential)
        self.assertTrue(self.repo.state['phase2']['channels'][0]['revoked'])
        self.assert_old_authority_held(self.repo.state)
        self.repo.mutate.assert_not_called()

    def test_remote_revoke_is_explicitly_deferred_to_protect_concurrent_renewal(self):
        result = self.disconnect()
        self.assertFalse(result['remoteRevoked'])
        self.assertTrue(result['remoteRevocationDeferred'])
        self.provider.revoke.assert_not_called()
        self.assertIn('LinkedIn', result['note'])

    def test_transaction_failure_restores_all_local_authority(self):
        original = self.repo.execute
        def fail(sql, params=()):
            if sql.startswith('UPDATE public.pr_workspaces SET state='):
                raise RuntimeError('Synthetic state write failure')
            original(sql, params)
        self.repo.execute = fail
        with self.assertRaises(RuntimeError): self.disconnect()
        self.assertEqual(self.repo.credential, 'synthetic-old-cipher')
        self.assertEqual(self.repo.capability, 'Direct')
        self.assertFalse(self.repo.state['phase2']['channels'][0]['revoked'])
        self.provider.revoke.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_reconnect_with_same_scopes_and_adapter_version_cannot_restore_revoked_job(self, _billing):
        worker, db, _, _, _ = worker_controls.linkedin_worker()
        self.oauth._revoke_linkedin_authority(db.state, 'connection-0', NOW)
        # Callback capability versions describe the adapter, and may return to 1.
        db.state['phase2']['channels'][0].update(revoked=False, identityVerified=True, capabilityVerified=True,
            capabilityVersion=1, verifiedAt=NOW, expiresAt=NOW+3600)
        db.state['phase2']['jobs'][0].update(state='approved', nextAt=NOW)
        self.assertTrue(worker.step())
        worker.social.submit.assert_not_called()
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')

    def test_processing_jobs_stop_forward_work_and_other_platform_records_are_preserved(self):
        data = self.repo.state['phase2']
        data['jobs'][0].update(state='processing', container='accepted-upload', progress={'stage': 'container_ready'})
        foreign = {'id': 'unrelated', 'state': 'approved', 'manifest': {'channelId': 'other', 'platform': 'Pinterest'}}
        data['jobs'].append(copy.deepcopy(foreign))
        self.disconnect()
        data = self.repo.state['phase2']
        self.assertEqual(data['jobs'][0]['state'], 'uncertain')
        self.assertEqual(data['jobs'][0]['container'], 'accepted-upload')
        self.assertEqual(data['jobs'][0]['approvalRevokedAt'], NOW)
        self.assertEqual(data['jobs'][-1], foreign)
