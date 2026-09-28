"""Portable discovery/retry/quarantine acceptance found by postriff_pg_suite.

All sources/costs are synthetic, provider adapters are forbidden mocks. Only the
exact disposable runner or an explicitly allocated local test DB is accepted.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from test_trend_planner import dedicated_test_dsn


def main():
    dsn = dedicated_test_dsn()
    with psycopg.connect(dsn) as db:
        if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
            raise RuntimeError('Disposable rls.sql baseline required; use scripts/postriff_pg_suite.py')
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_trend_planner', 'test_trend_retry'])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    sys.exit(main())
