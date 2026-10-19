"""Source-stamping tests use fresh temporary Git repositories, never production."""
import importlib.util
import fnmatch
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
        (self.root / 'non-witness.txt').write_text('tracked outside the witness set\n')
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

    def test_existing_receipt_requires_clean_matching_git_head(self):
        self.module.stamp(self.root)
        self.assertEqual(self.module.build_source_proof({}, self.root)['sourceRevision'], self.head)

    def test_existing_receipt_rejects_advanced_head_with_unchanged_witnesses(self):
        self.module.stamp(self.root)
        receipt = self.root / provenance.MANIFEST_PATH
        before = receipt.read_bytes()
        (self.root / 'non-witness.txt').write_text('new committed non-witness content\n')
        self.git('add', 'non-witness.txt')
        self.git('commit', '-qm', 'advance only non-witness source')
        self.assertTrue(provenance.release_source_proof({}, root=self.root)['verifiedSelectedRuntimeFiles'])
        with self.assertRaises(ValueError):
            self.module.build_source_proof({}, self.root)
        self.assertEqual(receipt.read_bytes(), before)

    def test_existing_receipt_rejects_dirty_non_witness_tracked_source(self):
        self.module.stamp(self.root)
        before = (self.root / provenance.MANIFEST_PATH).read_bytes()
        (self.root / 'non-witness.txt').write_text('dirty outside the witness set\n')
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    self.git('add', 'non-witness.txt')
                with self.assertRaises(ValueError):
                    self.module.build_source_proof({}, self.root)
        self.assertEqual((self.root / provenance.MANIFEST_PATH).read_bytes(), before)

    def test_existing_receipt_rejects_unreadable_git_metadata(self):
        self.module.stamp(self.root)
        with patch.object(self.module, '_git', side_effect=ValueError('unreadable Git')):
            with self.assertRaises(ValueError):
                self.module.build_source_proof({}, self.root)

    def test_valid_packaged_receipt_without_git_is_accepted(self):
        self.module.stamp(self.root)
        # Hide only the ephemeral fixture's Git marker; never touch this worktree's Git.
        (self.root / '.git').rename(self.root / 'fixture-git-metadata')
        self.assertEqual(self.module.build_source_proof({}, self.root)['sourceRevision'], self.head)

    def test_release_main_requires_source_for_every_environment(self):
        spec = importlib.util.spec_from_file_location('release_main_under_test', ROOT / 'runtime/verify_release_target.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        for environment in (None, '', 'unknown', 'development', 'preview', 'production'):
            values = {} if environment is None else {'VERCEL_ENV': environment}
            with self.subTest(environment=environment), patch.dict(os.environ, values, clear=True), patch.object(
                verifier, 'verify', return_value={}), patch.object(
                verifier, 'verify_source', side_effect=ValueError('PRIVATE_SOURCE_FAILURE')) as source, patch('builtins.print') as output:
                self.assertEqual(verifier.main(), 1)
                source.assert_called_once_with(os.environ)
                self.assertNotIn('PRIVATE_SOURCE_FAILURE', str(output.call_args_list))

    def test_release_main_reports_verified_source_without_environment(self):
        spec = importlib.util.spec_from_file_location('release_main_success', ROOT / 'runtime/verify_release_target.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        source_proof = self.module.stamp(self.root)
        with patch.dict(os.environ, {}, clear=True), patch.object(verifier, 'verify', return_value={}), patch.object(
            verifier, 'verify_source', return_value=source_proof) as source, patch('builtins.print') as output:
            self.assertEqual(verifier.main(), 0)
            source.assert_called_once_with(os.environ)
            self.assertEqual(json.loads(output.call_args.args[0])['sourceProvenance'], source_proof)

    def test_build_failure_is_sanitized(self):
        spec = importlib.util.spec_from_file_location('release_target_under_test', ROOT / 'runtime/verify_release_target.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        self.assertTrue(hasattr(verifier, 'verify_source'), 'Release build does not enforce source receipt validation')
        with patch.dict(os.environ, {'VERCEL_ENV': 'production'}, clear=True), patch.object(verifier, 'verify', return_value={}), patch.object(verifier, 'verify_source', side_effect=ValueError('PRIVATE_DETAIL')), patch('builtins.print') as output:
            self.assertEqual(verifier.main(), 1)
        self.assertNotIn('PRIVATE_DETAIL', str(output.call_args_list))

    def test_upload_config_retains_all_fixed_witnesses_and_receipt(self):
        # Git's ignore engine checks upload-filter intent only, never a Vercel bundle.
        names = (*provenance.WITNESS_PATHS, provenance.MANIFEST_PATH)
        self.assertEqual(len(names), 13)
        (self.root / '.gitignore').write_bytes((ROOT / '.vercelignore').read_bytes())
        result = subprocess.run(['git', '-C', str(self.root), 'check-ignore', '--no-index', '--stdin'],
                                input='\n'.join(names) + '\n', env=self.env, capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, '')
        for name in ('.env.local', 'tests/private.py', '.source-provenance-local/red.log'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('synthetic excluded data')
            with self.subTest(excluded=name):
                self.assertEqual(subprocess.run(
                    ['git', '-C', str(self.root), 'check-ignore', '--no-index', '-q', name],
                    env=self.env, capture_output=True, timeout=5).returncode, 0)

    def test_api_packaging_config_does_not_exclude_fixed_witnesses_or_receipt(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        service = config['services']['postriff_api']
        self.assertEqual(service['root'], '.')
        self.assertEqual(service['runtime'], 'python')
        self.assertEqual(service['entrypoint'], 'api.index:app')
        function = service['functions']['api/index.py']
        # Bound this check to the existing flat brace-list glob syntax; it does
        # not emulate tracing, runtime file layout or actual function packaging.
        expression = function['excludeFiles']
        self.assertTrue(expression.startswith('{') and expression.endswith('}'))
        patterns = expression[1:-1].split(',')
        self.assertTrue(all(pattern and not any(char in pattern for char in '{}!') for pattern in patterns))
        for name in (*provenance.WITNESS_PATHS, provenance.MANIFEST_PATH):
            with self.subTest(packaging_candidate=name):
                self.assertFalse(any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns))
        self.assertNotIn('includeFiles', function, 'Adding includeFiles requires separately verified schema/docs support')

    def test_build_command_guards_before_renderer_and_storage_provisioning(self):
        command = json.loads((ROOT / 'vercel.json').read_text())['services']['postriff_api']['buildCommand']
        self.assertEqual(command.split(' && '), [
            'python3 runtime/verify_release_target.py',
            'python3 runtime/build_document_renderer.py',
            'python3 runtime/provision_video_storage.py',
        ])


    def test_build_rejects_an_old_commit_even_when_selected_witnesses_match(self):
        self.module.stamp(self.root)
        receipt = self.root / provenance.MANIFEST_PATH
        before = receipt.read_bytes()
        (self.root / 'source-note.txt').write_text('new tracked source outside the selected witnesses')
        self.git('add', 'source-note.txt')
        self.git('commit', '-qm', 'advance source without changing selected witnesses')
        self.assertTrue(provenance.release_source_proof({}, root=self.root)['verifiedSelectedRuntimeFiles'])
        with self.assertRaises(ValueError):
            self.module.build_source_proof({}, self.root)
        self.assertEqual(receipt.read_bytes(), before)


    def test_build_rejects_tracked_drift_outside_the_selected_witnesses(self):
        self.module.stamp(self.root)
        (self.root / '.gitignore').write_text('/' + provenance.MANIFEST_PATH + '\n# uncommitted source change\n')
        self.assertTrue(provenance.release_source_proof({}, root=self.root)['verifiedSelectedRuntimeFiles'])
        with self.assertRaises(ValueError):
            self.module.build_source_proof({}, self.root)


if __name__ == '__main__':
    unittest.main()
