"""Synthetic storage/failure contracts; no native capture or playback is executed."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from agent_team import continuous_capture as capture


class CaptureStorageTests(unittest.TestCase):
    def test_preexisting_unowned_directory_is_never_enrolled(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'personal.mp4').write_bytes(b'untouched')
            with self.assertRaisesRegex(ValueError,'not_owned'):capture.prepare(root)
            self.assertEqual((root/'personal.mp4').read_bytes(),b'untouched')

    def test_failed_native_artifact_counts_toward_retention_but_not_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=capture.prepare(directory)
            def native(args, **kwargs):
                Path(args[2]).write_bytes(b'incomplete actual output')
                return subprocess.CompletedProcess(args,3,json.dumps({'executionState':'failed',
                    'reason':'private arbitrary data', 'phase':'recording_finalization',
                    'captureFailure':'recordingFailed','errorCode':3}), '')
            with patch.object(capture.subprocess,'run',side_effect=native):
                with self.assertRaises(capture.CaptureError) as result:capture.capture(root,Path('/helper'),1)
            row=result.exception.artifact
            self.assertEqual(str(result.exception),'native_capture_failed')
            self.assertEqual(row['byteCount'],len(b'incomplete actual output'))
            self.assertNotIn('durationSeconds',row)
            state={'chunks':[],'failedAttempts':[row]};capture.retain(root,state)
            self.assertEqual(state['retainedBytes'],row['byteCount'])
            with patch.object(capture,'MAX_BYTES',0):capture.retain(root,state)
            self.assertEqual(row['retentionState'],'retention_removed')
            self.assertFalse((root/row['path']).exists())

    def test_recovered_orphan_has_hash_and_unknown_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            root=capture.prepare(directory);name='11111111-2222-3333-4444-555555555555.mp4'
            (root/name).write_bytes(b'interrupted')
            state={'chunks':[]};capture.reconcile_artifacts(root,state)
            row=state['failedAttempts'][0]
            self.assertEqual(row['executionState'],'unverified_native_artifact')
            self.assertEqual(len(row['sha256']),64)
            self.assertNotIn('durationSeconds',row)
            capture.reconcile_artifacts(root,state)
            self.assertEqual(len(state['failedAttempts']),1)

    def test_retention_rejects_replaced_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=capture.prepare(directory);identifier='11111111-2222-3333-4444-555555555555'
            path=root/(identifier+'.mp4');path.write_bytes(b'original')
            row=capture.stored_artifact(root,identifier);row['storedAt']=time.time()-capture.RETENTION_SECONDS-1
            path.write_bytes(b'replaced')
            with self.assertRaisesRegex(ValueError,'identity_conflict'):
                capture.retain(root,{'chunks':[row]})
            self.assertEqual(path.read_bytes(),b'replaced')

    def test_persisted_retry_ceiling_prevents_new_native_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=capture.prepare(directory)
            capture.save(root/'manifest.json',{'chunks':[],'gaps':[],
                'consecutiveFailures':capture.MAX_CONSECUTIVE_FAILURES})
            with patch.object(capture,'capture') as native:
                with self.assertRaisesRegex(ValueError,'retry_ceiling'):
                    capture.run(root,Path('/helper'),1)
                native.assert_not_called()

    def test_storage_preflight_cannot_exhaust_native_retry_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=capture.prepare(directory)
            with patch.object(capture,'capture',side_effect=ValueError('capture_storage_reserve_unavailable')):
                with self.assertRaisesRegex(ValueError,'storage_reserve'):
                    capture.run(root,Path('/helper'),1)
            state=json.loads((root/'manifest.json').read_text())
            self.assertEqual(state['executionState'],'waiting_external')
            self.assertEqual(state['consecutiveFailures'],0)

if __name__=='__main__':unittest.main()
