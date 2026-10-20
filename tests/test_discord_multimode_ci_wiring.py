"""Inert regression for routing multi-mode SQL through its owned Linux fixture."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('multimode_pg_runner', ROOT / 'scripts/postriff_pg_suite.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class MultimodeCIWiring(unittest.TestCase):
    def test_generic_cluster_does_not_run_owned_multimode_fixture(self):
        ordinary = ROOT / 'tests/phase2/postgres_repository.py'
        owned = ROOT / 'tests/phase2/postgres_discord_multimode.py'
        self.assertEqual(RUNNER.select_scripts([ordinary, owned], []), [ordinary])

    def test_explicit_generic_selection_routes_to_guarded_batch(self):
        with self.assertRaisesRegex(ValueError, 'discord-multimode-validation-cloud.sh'):
            RUNNER.select_scripts([ROOT / 'tests/phase2/postgres_discord_multimode.py'], ['postgres_discord_multimode'])

    def test_cloud_workflow_executes_source_pinned_multimode_without_deploy(self):
        path = ROOT / '.github/workflows/discord-multimode-qualification.yml'
        self.assertTrue(path.is_file(), 'No actual cloud route for the multi-mode acceptance script')
        text = path.read_text()
        self.assertIn('ubuntu-24.04', text)
        self.assertIn('codex/discord-personal-account-20261019', text)
        self.assertIn('discord-multimode-validation-cloud.sh', text)
        self.assertIn('Fail-fast fenced multi-mode PostgreSQL acceptance', text)
        self.assertIn('github.sha', text)
        for forbidden in ('vercel deploy', 'vercel --prod', 'workflow_run:', 'pull_request_target:', 'actions/upload-artifact', 'cache: npm', 'depot.dev', 'secrets.'):
            self.assertNotIn(forbidden, text)



class CheckoutSafetyRegressions(unittest.TestCase):
    def test_broken_legacy_gitlink_cannot_break_exact_sha_checkout(self):
        content=(ROOT / '.github/workflows/discord-multimode-qualification.yml').read_text()
        self.assertNotIn('actions/checkout@', content)
        self.assertIn('git init .', content)
        self.assertIn('git -c protocol.version=2 fetch --depth=1 origin "$SOURCE_SHA"', content)
        self.assertIn('git checkout --detach FETCH_HEAD', content)
        self.assertIn('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"', content)

if __name__ == '__main__':
    unittest.main()
