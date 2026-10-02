import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
# A script import must not shadow src packages for later discovery tests. Restore the exact search path after loading.
_path = sys.path[:]
try:
    sys.path.insert(0, str(SCRIPTS))
    import product_growth_release_migrate as release
finally:
    sys.path[:] = _path


class ProductGrowthMigrationRelease(unittest.TestCase):
    def test_reviewed_digests_are_the_files_in_this_tree(self):
        for name, expected in release.REVIEWED.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ROOT / 'migrations/postriff' / name).read_bytes()).hexdigest(), expected)

    def test_every_program_migration_is_reviewed(self):
        program = {p.name for p in (ROOT / 'migrations/postriff').glob('08[0-9]_*.sql')}
        self.assertLessEqual(program, set(release.REVIEWED))

    def test_connection_must_name_exact_project_and_session_port(self):
        ref = release.PROJECTS['staging']
        params = {'host': 'db.' + ref + '.supabase.co', 'user': 'postgres', 'dbname': 'postgres', 'port': '5432'}
        release.validate_identity(params, 'staging')
        for change in ({'host': 'localhost'}, {'port': '6543'}, {'user': 'postgres.' + release.PROJECTS['production']}, {'dbname': 'other'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                release.validate_identity({**params, **change}, 'staging')
        with self.assertRaises(ValueError):
            release.validate_identity(params, 'production')

    def test_plan_refuses_an_unreviewed_pending_migration(self):
        rows = [{'name': '057_founder_invoices.sql', 'sha256': 'a' * 64, 'status': 'PENDING'}]
        with patch.object(release.migrations, 'plan', return_value=rows):
            with self.assertRaisesRegex(ValueError, 'unreviewed_migration_dependency'):
                release.make_plan(None, 'staging')

    def test_plan_refuses_a_changed_reviewed_file(self):
        rows = [{'name': '081_relationships.sql', 'sha256': '0' * 64, 'status': 'PENDING'}]
        with patch.object(release.migrations, 'plan', return_value=rows):
            with self.assertRaisesRegex(ValueError, 'reviewed_migration_digest_mismatch'):
                release.make_plan(None, 'staging')

    def test_plan_digest_binds_complete_ledger_and_target(self):
        rows = [{'name': '001_init.sql', 'sha256': 'c' * 64, 'status': 'APPLIED'},
                {'name': '080_customer_results.sql', 'sha256': release.REVIEWED['080_customer_results.sql'], 'status': 'PENDING'}]
        with patch.object(release.migrations, 'plan', return_value=rows):
            plan = release.make_plan(None, 'staging')
        self.assertEqual(plan['digest'], release.digest({k: v for k, v in plan.items() if k != 'digest'}))
        plan['migrations'][0]['sha256'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'migration_plan_digest_mismatch'):
            release.apply_plan(None, plan)


if __name__ == '__main__':
    unittest.main()
