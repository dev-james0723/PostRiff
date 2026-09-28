import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
# A script import must not shadow the src/postriff_phase3 package for later
# discovery tests. Restore the exact search path after loading this target.
_path = sys.path[:]
try:
    sys.path.insert(0, str(SCRIPTS))
    import trend_release_migrate as release
finally:
    sys.path[:] = _path


class MigrationRelease(unittest.TestCase):
    def test_connection_must_name_exact_project_and_session_port(self):
        ref = release.PROJECTS['staging']
        params = {'host': 'db.' + ref + '.supabase.co', 'user': 'postgres', 'dbname': 'postgres', 'port': '5432'}
        release.validate_identity(params, 'staging')
        for change in ({'host': 'localhost'}, {'port': '6543'}, {'user': 'postgres.' + release.PROJECTS['production']}, {'dbname': 'other'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                release.validate_identity({**params, **change}, 'staging')
        with self.assertRaises(ValueError):
            release.validate_identity(params, 'production')

    def test_plan_refuses_extra_unreviewed_dependency(self):
        with patch.object(release.migrations, 'plan', return_value=[{'name': '099_other.sql', 'sha256': 'a', 'status': 'PENDING'}]):
            with self.assertRaisesRegex(ValueError, 'unreviewed_migration_dependency'):
                release.make_plan(None, 'staging')

    def test_plan_digest_binds_complete_ledger_and_target(self):
        rows = [{'name': '035_growth_metric_reads.sql', 'sha256': 'a'*64, 'status': 'PENDING'}]
        with patch.object(release.migrations, 'plan', return_value=rows):
            plan = release.make_plan(None, 'staging')
        self.assertEqual(plan['digest'], release.digest({k: v for k, v in plan.items() if k != 'digest'}))
        plan['migrations'][0]['sha256'] = 'b'*64
        with self.assertRaisesRegex(ValueError, 'migration_plan_digest_mismatch'):
            release.apply_plan(None, plan)

    def test_merged_phone_dependency_must_match_reviewed_digest(self):
        name, digest = next(iter(release.COMPATIBILITY_DEPENDENCIES.items()))
        with patch.object(release.migrations, 'plan', return_value=[{'name':name,'sha256':digest,'status':'PENDING'}]):
            self.assertEqual(release.make_plan(None,'staging')['migrations'][0]['sha256'],digest)
        with patch.object(release.migrations, 'plan', return_value=[{'name':name,'sha256':'0'*64,'status':'PENDING'}]):
            with self.assertRaisesRegex(ValueError,'compatibility_migration_digest_mismatch'):
                release.make_plan(None,'staging')
