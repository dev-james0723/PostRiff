"""Offline source-receipt regressions; never live customer/release evidence."""
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REVISION = '1234567890abcdef1234567890abcdef12345678'


class ReleaseProvenanceTests(unittest.TestCase):
    def setUp(self):
        target = ROOT / 'src/postriff_phase2/release_provenance.py'
        self.assertTrue(target.is_file(), 'CLI deployment has no packaged source receipt verifier')
        self.module = importlib.import_module('postriff_phase2.release_provenance')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        files = {}
        for name in self.module.WITNESS_PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ('synthetic witness: ' + name + '\n').encode()
            path.write_bytes(raw)
            files[name] = hashlib.sha256(raw).hexdigest()
        self.manifest = {'schemaVersion': 1, 'sourceRevision': REVISION,
                         'coverage': 'selected_runtime_files', 'files': files}
        self.receipt = self.root / self.module.MANIFEST_PATH

    def write_receipt(self):
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        self.receipt.write_text(json.dumps(self.manifest), encoding='utf-8')

    def proof(self, values=None):
        return self.module.release_source_proof(values or {}, root=self.root)

    def assert_unverified(self, result):
        self.assertFalse(result['verifiedSelectedRuntimeFiles'])
        self.assertIsNone(result['sourceRevision'])

    def test_missing_receipt_does_not_invent_revision(self):
        result = self.proof()
        self.assert_unverified(result)
        self.assertEqual(result['status'], 'missing')

    def test_git_metadata_alone_remains_explicitly_unverified(self):
        result = self.proof({'VERCEL_GIT_COMMIT_SHA': REVISION})
        self.assertFalse(result['verifiedSelectedRuntimeFiles'])
        self.assertEqual(result['status'], 'metadata_only')
        self.assertEqual(result['sourceRevision'], REVISION)

    def test_valid_cli_receipt_works_without_git_environment(self):
        self.write_receipt()
        result = self.proof()
        self.assertTrue(result['verifiedSelectedRuntimeFiles'])
        self.assertEqual(result['sourceRevision'], REVISION)
        self.assertEqual(result['witnessCount'], len(self.module.WITNESS_PATHS))
        self.assertEqual(result['coverage'], 'selected_runtime_files')
        self.assertEqual(result['receiptSha256'], hashlib.sha256(self.receipt.read_bytes()).hexdigest())
        self.assertNotIn('customerValidated', result)
        self.assertNotIn('publicReady', result)

    def test_matching_git_metadata_is_consistent(self):
        self.write_receipt()
        self.assertTrue(self.proof({'VERCEL_GIT_COMMIT_SHA': REVISION})['verifiedSelectedRuntimeFiles'])

    def test_conflicting_git_metadata_refuses_receipt(self):
        self.write_receipt()
        self.assert_unverified(self.proof({'VERCEL_GIT_COMMIT_SHA': 'a' * 40}))

    def test_malformed_git_metadata_cannot_verify_a_receipt(self):
        self.write_receipt()
        self.assert_unverified(self.proof({'VERCEL_GIT_COMMIT_SHA': 'not-a-commit'}))

    def test_other_environment_strings_are_never_source_proof(self):
        self.assert_unverified(self.proof({'SOURCE_REVISION': REVISION, 'RAFII_CAPTURE_SOURCE_SHA': REVISION}))

    def test_changed_witness_is_rejected(self):
        self.write_receipt()
        (self.root / self.module.WITNESS_PATHS[0]).write_text('changed')
        self.assert_unverified(self.proof())

    def test_missing_witness_is_rejected(self):
        self.write_receipt()
        (self.root / self.module.WITNESS_PATHS[0]).unlink()
        self.assert_unverified(self.proof())

    def test_omitted_witness_is_rejected(self):
        self.manifest['files'].pop(self.module.WITNESS_PATHS[0])
        self.write_receipt()
        self.assert_unverified(self.proof())

    def test_extra_or_traversal_paths_are_rejected(self):
        for name in ('../private.env', '/private.env', 'src/extra.py'):
            with self.subTest(name=name):
                self.manifest['files'][name] = 'a' * 64
                self.write_receipt()
                self.assert_unverified(self.proof())
                del self.manifest['files'][name]

    def test_invalid_schema_is_rejected(self):
        for value in (True, '1', 0, 2, None):
            self.manifest['schemaVersion'] = value
            self.write_receipt()
            self.assert_unverified(self.proof())

    def test_invalid_commit_is_rejected(self):
        for value in (None, 42, 'a' * 39, 'A' * 40, '0' * 40, 'a' * 40 + '\n'):
            self.manifest['sourceRevision'] = value
            self.write_receipt()
            self.assert_unverified(self.proof())

    def test_invalid_witness_digest_is_rejected(self):
        name = self.module.WITNESS_PATHS[0]
        for value in (None, 123, 'A' * 64, 'a' * 63, 'a' * 64 + '\n'):
            self.manifest['files'][name] = value
            self.write_receipt()
            self.assert_unverified(self.proof())

    def test_wrong_coverage_cannot_be_presented_as_full_attestation(self):
        self.manifest['coverage'] = 'entire_production_is_verified'
        self.write_receipt()
        self.assert_unverified(self.proof())

    def test_invalid_json_and_oversize_receipts_fail_closed(self):
        for raw in ('not-json', '[]', 'null', '{"private":"NEVER_OUTPUT_THIS"}', ' ' * 65537):
            self.receipt.write_text(raw)
            result = self.proof()
            self.assert_unverified(result)
            self.assertNotIn('NEVER_OUTPUT_THIS', json.dumps(result))
            self.assertNotIn(str(self.root), json.dumps(result))

    def test_duplicate_json_keys_are_rejected(self):
        self.write_receipt()
        raw = self.receipt.read_text()
        self.receipt.write_text('{"schemaVersion": 99, ' + raw[1:])
        self.assert_unverified(self.proof())

    def test_unknown_manifest_fields_are_rejected_without_disclosure(self):
        self.manifest['credential'] = 'NEVER_OUTPUT_THIS'
        self.write_receipt()
        result = self.proof()
        self.assert_unverified(result)
        self.assertNotIn('NEVER_OUTPUT_THIS', json.dumps(result))

    def test_symlink_witness_is_rejected(self):
        self.write_receipt()
        path = self.root / self.module.WITNESS_PATHS[0]
        copy = self.root / 'copy.txt'
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        self.assert_unverified(self.proof())

    def test_symlink_receipt_is_rejected(self):
        self.write_receipt()
        copy = self.root / 'receipt-copy.json'
        self.receipt.rename(copy)
        self.receipt.symlink_to(copy)
        self.assert_unverified(self.proof())

    def test_receipt_read_failure_is_sanitized(self):
        self.write_receipt()
        with patch.object(os, 'open', side_effect=PermissionError('PRIVATE_PATH')):
            result = self.proof()
        self.assert_unverified(result)
        self.assertNotIn('PRIVATE_PATH', json.dumps(result))

    def assert_replacement_before_open_rejected(self, replacement):
        path = self.root / self.module.WITNESS_PATHS[0]
        copy = self.root / 'symlink-target'
        copy.write_bytes(path.read_bytes())
        original_open = os.open
        original_path_open = Path.open
        swapped = False
        followed = []

        def swap():
            nonlocal swapped
            if not swapped:
                path.unlink()
                if replacement == 'fifo':
                    os.mkfifo(path)
                else:
                    path.symlink_to(copy)
                swapped = True

        def descriptor_open(name, flags, *args, **kwargs):
            if str(name) in (str(path), path.name):
                swap()
            return original_open(name, flags, *args, **kwargs)

        def pathname_open(target, *args, **kwargs):
            if target == path:
                swap()
                stream = original_path_open(target, *args, **kwargs)
                followed.append(True)
                return stream
            return original_path_open(target, *args, **kwargs)

        def deadline(*_):
            raise AssertionError('read_regular blocked opening a swapped FIFO')

        handler = signal.signal(signal.SIGALRM, deadline)
        try:
            signal.setitimer(signal.ITIMER_REAL, 1)
            with patch.object(os, 'open', side_effect=descriptor_open), patch.object(Path, 'open', pathname_open):
                with self.assertRaises((ValueError, OSError)):
                    self.module.read_regular(self.root, self.module.WITNESS_PATHS[0], 1024)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, handler)
        self.assertTrue(swapped, 'Regression must exercise replacement immediately before open')
        self.assertFalse(followed, 'A swapped symlink must be refused before it is opened')

    def test_fifo_swapped_before_open_cannot_block(self):
        self.assert_replacement_before_open_rejected('fifo')

    def test_symlink_swapped_before_open_is_never_followed(self):
        self.assert_replacement_before_open_rejected('symlink')

    def test_default_root_cache_explicitly_assumes_immutable_bundle(self):
        self.module._packaged_proof.cache_clear()
        self.addCleanup(self.module._packaged_proof.cache_clear)
        with patch.object(self.module, '_ROOT', self.root):
            missing = self.module.release_source_proof({})
            self.write_receipt()
            self.assertEqual(self.module.release_source_proof({}), missing)
            self.assertTrue(self.proof()['verifiedSelectedRuntimeFiles'])
            self.module._packaged_proof.cache_clear()
            verified = self.module.release_source_proof({})
            verified['status'] = 'caller mutation'
            self.assertEqual(self.module.release_source_proof({})['status'], 'verified')
            (self.root / self.module.WITNESS_PATHS[0]).write_text('mutable tree changed')
            self.assertTrue(self.module.release_source_proof({})['verifiedSelectedRuntimeFiles'])
            self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])
            self.module._packaged_proof.cache_clear()
            self.assertFalse(self.module.release_source_proof({})['verifiedSelectedRuntimeFiles'])


class HealthProofRegression(unittest.TestCase):
    def test_health_separates_source_metadata_from_customer_qualification(self):
        from postriff_phase2.hosted_app import HostedApplication
        state = {}
        def start(status, headers):
            state['status'] = status
        environ = {'PATH_INFO': '/api/health', 'REQUEST_METHOD': 'GET',
                   'wsgi.input': io.BytesIO(b'')}
        with patch.dict(os.environ, {'VERCEL_GIT_COMMIT_SHA': REVISION}, clear=True), patch(
            'postriff_phase2.hosted_app.runtime_from_environment',
            side_effect=AssertionError('Health must not contact the database')):
            result = json.loads(b''.join(HostedApplication()(environ, start)))
        self.assertEqual(state['status'], '200 OK')
        self.assertIn('sourceProvenance', result)
        self.assertFalse(result['sourceProvenance']['verifiedSelectedRuntimeFiles'])
        self.assertFalse(result['customerValidated'])
        self.assertIn('productionBindings', result)


if __name__ == '__main__':
    unittest.main()
