"""Source-stamping tests use fresh temporary Git repositories, never production."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from postriff_phase2 import release_provenance as provenance

ROOT = Path(__file__).resolve().parents[1]


class SourceStampTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'runtime/stamp_release_source.py'
        self.assertTrue(path.is_file(), 'No clean-source stamping path exists for CLI uploads')
        spec = importlib.util.spec_from_file_location('source_stamp_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.root), 'LC_ALL': 'C'}
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic source test')
        self.git('config', 'user.email', 'source-test@example.invalid')
        for name in provenance.WITNESS_PATHS:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('synthetic tracked content: ' + name + '\n')
        (self.root / '.gitignore').write_text('/' + provenance.MANIFEST_PATH + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic fixture')
        self.head = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.root), *args], env=self.env,
                                capture_output=True, text=True, timeout=5, check=True)
        return result.stdout

    def test_stamp_matches_actual_git_head_and_runtime_bytes(self):
        proof = self.module.stamp(self.root)
        self.assertTrue(proof['verifiedSelectedRuntimeFiles'])
        self.assertEqual(proof['sourceRevision'], self.head)
        self.assertEqual(proof, provenance.release_source_proof({}, root=self.root))

    def test_stamp_is_deterministic_for_unchanged_commit(self):
        first = self.module.stamp(self.root)
        self.assertEqual(self.module.stamp(self.root), first)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_dirty_tracked_file_is_refused_without_receipt(self):
        (self.root / provenance.WITNESS_PATHS[0]).write_text('dirty')
        with self.assertRaises(ValueError):
            self.module.stamp(self.root)
        self.assertFalse((self.root / provenance.MANIFEST_PATH).exists())

    def test_staged_change_is_refused(self):
        (self.root / provenance.WITNESS_PATHS[0]).write_text('staged')
        self.git('add', provenance.WITNESS_PATHS[0])
        with self.assertRaises(ValueError):
            self.module.stamp(self.root)

    def test_untracked_witness_cannot_be_certified_by_head(self):
        name = provenance.WITNESS_PATHS[0]
        self.git('rm', '--cached', name)
        self.git('commit', '-qm', 'remove witness from tracked source')
        with self.assertRaises(ValueError):
            self.module.stamp(self.root)

    def test_no_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(ValueError):
            self.module.stamp(Path(empty))

    def test_receipt_symlink_is_not_overwritten(self):
        target = self.root / 'untouched.json'
        target.write_text('preserve me')
        (self.root / provenance.MANIFEST_PATH).symlink_to(target)
        with self.assertRaises(ValueError):
            self.module.stamp(self.root)
        self.assertEqual(target.read_text(), 'preserve me')

    def test_build_can_stamp_a_clean_git_checkout(self):
        proof = self.module.build_source_proof({'VERCEL_GIT_COMMIT_SHA': self.head}, self.root)
        self.assertTrue(proof['verifiedSelectedRuntimeFiles'])

    def test_build_refuses_mismatched_declared_revision(self):
        with self.assertRaises(ValueError):
            self.module.build_source_proof({'VERCEL_GIT_COMMIT_SHA': 'a' * 40}, self.root)

    def test_build_refuses_stale_receipt_instead_of_rewriting_it(self):
        self.module.stamp(self.root)
        receipt = self.root / provenance.MANIFEST_PATH
        before = receipt.read_bytes()
        (self.root / provenance.WITNESS_PATHS[0]).write_text('changed since stamping')
        with self.assertRaises(ValueError):
            self.module.build_source_proof({}, self.root)
        self.assertEqual(receipt.read_bytes(), before)

    def test_packaged_build_without_git_requires_a_valid_receipt(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(ValueError):
            self.module.build_source_proof({}, Path(empty))

    def test_build_failure_is_sanitized(self):
        spec = importlib.util.spec_from_file_location('release_target_under_test', ROOT / 'runtime/verify_release_target.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        self.assertTrue(hasattr(verifier, 'verify_source'), 'Release build does not enforce source receipt validation')
        with patch.dict(os.environ, {'VERCEL_ENV': 'production'}, clear=True), patch.object(verifier, 'verify', return_value={}), patch.object(verifier, 'verify_source', side_effect=ValueError('PRIVATE_DETAIL')), patch('builtins.print') as output:
            self.assertEqual(verifier.main(), 1)
        self.assertNotIn('PRIVATE_DETAIL', str(output.call_args_list))


if __name__ == '__main__':
    unittest.main()
