"""Read-only approved Brand Brain export, with no provider or database dependency."""
import copy
import hashlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase2 import brand_brain, memory
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands, HostedWorkspaceService


class BrandBrainExportTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_phase2_state('w', 'owner', 'Owner', 'studio', 100)
        self.commands = HostedPhase2Commands(clock=lambda: 200)
        self.index = 0
        self.service = SimpleNamespace(commands=self.commands, clock=lambda: 200, get=self.get)

    def get(self, workspace, token):
        if workspace != 'w' or token not in ('owner', 'editor', 'viewer'):
            raise AlphaError('Workspace unavailable.', 403)
        return {'state': copy.deepcopy(self.state), 'revision': 22}

    def act(self, action, **payload):
        self.index += 1
        self.commands(self.state, 'owner', action, {**payload, 'requestId': f'brand-export-test-{self.index:04}'})

    def manual(self):
        self.act('brand_brain_manual', mode='personal', context={'purpose': 'Share practice', 'audience': 'Readers', 'subject': 'Practice', 'speaker': 'Owner'}, tone='direct')

    def approve(self):
        brain = brand_brain.projection(self.state)
        self.act('brand_brain_approve', proposalDigest=brain['proposalDigest'], impactDigest=brain['impact']['impactDigest'], confirmed=True)

    def export(self, token='owner'):
        return zipfile.ZipFile(io.BytesIO(HostedWorkspaceService.export_profile(self.service, 'w', token)))

    def test_canonical_approved_snapshot_omits_pending_raw_and_private_values(self):
        self.manual()
        self.approve()
        self.act('brand_brain_identity', confirmed=True, fields={'audience': 'Updated readers'})
        self.act('brand_brain_boundaries', confirmed=True, fields=[
            {'id': f'boundary-{privacy}', 'label': privacy, 'value': f'SECRET-{privacy}', 'privacy': privacy}
            for privacy in ('public', 'workspace_only', 'private', 'local_only', 'excluded')])
        self.state['profile']['fields'].append({'id': 'boundary-unlabelled', 'value': 'SECRET-unlabelled'})
        active = memory.active_profile(self.state)
        active['profile']['writingExample'] = 'RAW-SAMPLE-DO-NOT-EXPORT'
        self.manual()
        self.state['speaker']['provisional']['observations'] = ['PENDING-DO-NOT-EXPORT']
        before = copy.deepcopy(self.state)
        archive = self.export()
        manifest = json.loads(archive.read('manifest.json'))
        self.assertTrue(set(memory.FILE_ORDER).issubset(archive.namelist()))
        self.assertEqual(manifest['schema'], 'rafii.brand-brain.export.v1')
        self.assertEqual(manifest['profileRevision'], 1)
        self.assertEqual(manifest['workspaceRevision'], 22)
        self.assertFalse(any(manifest['permissions'].values()))
        self.assertIn('Updated readers', archive.read('IDENTITY.md').decode())
        content = '\n'.join(archive.read(name).decode() for name in archive.namelist())
        for secret in ('RAW-SAMPLE-DO-NOT-EXPORT', 'PENDING-DO-NOT-EXPORT', 'SECRET-private', 'SECRET-local_only', 'SECRET-excluded', 'SECRET-unlabelled'):
            self.assertNotIn(secret, content)
        for name, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
        self.assertEqual(self.state, before)

    def test_unapproved_or_revoked_active_voice_cannot_export(self):
        self.manual()
        with self.assertRaises(AlphaError):
            self.export()
        self.approve()
        memory.active_profile(self.state)['stale'] = True
        with self.assertRaises(AlphaError) as denied:
            self.export()
        self.assertEqual(denied.exception.status, 409)

    def test_current_evidence_permission_is_rechecked_at_export(self):
        self.act('brand_brain_import', text='Hello friends. A short update.', authorshipConfirmed=True, retentionConfirmed=True)
        sid = self.state['sources'][-1]['id']
        self.act('voice_sample_select', sourceId=sid, selected=True)
        self.act('voice_sample_grant', sourceId=sid, confirmed=True, grants=[{'purpose': 'analysis', 'route': 'local-rules'}])
        self.act('brand_brain_analyze', sourceIds=[sid])
        self.approve()
        self.assertIn('VOICE.md', self.export().namelist())
        self.act('voice_sample_revoke', sourceId=sid, confirmed=True)
        with self.assertRaises(AlphaError):
            self.export()

    def test_read_members_keep_export_access_and_foreign_members_remain_denied(self):
        self.manual()
        self.approve()
        for token in ('owner', 'editor', 'viewer'):
            self.assertIn('VOICE.md', self.export(token).namelist())
        with self.assertRaises(AlphaError) as denied:
            self.export('foreign')
        self.assertEqual(denied.exception.status, 403)

    def test_legacy_field_package_keeps_original_contract(self):
        self.manual()
        self.approve()
        active = memory.active_profile(self.state)
        active.pop('activationSource')
        active['profile'].update(packageSchema='postriff.personal-voice.v1', fields=[], review=[])
        archive = self.export()
        self.assertEqual(json.loads(archive.read('manifest.json'))['schema'], 'postriff.personal-voice.v1')
        self.assertIn('review.md', archive.namelist())


if __name__ == '__main__':
    unittest.main()
