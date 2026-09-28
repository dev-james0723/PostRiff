"""Portable local advanced consumer acceptance; discovered by postriff_pg_suite.

Applies040 only on the guarded disposable target after the baseline schema.
Requires every pure/real-PG case to run: any skip is a failed acceptance run.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main():
    original = list(sys.path)
    try:
        sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
        import psycopg
        from test_trend_advanced_pipeline import dedicated_test_dsn
        dsn = dedicated_test_dsn()
        with psycopg.connect(dsn) as db:
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                raise RuntimeError('Disposable rls.sql baseline required; use scripts/postriff_pg_suite.py')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        suite = unittest.defaultTestLoader.loadTestsFromName('test_trend_advanced_pipeline')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() and not result.skipped else 1
    finally:
        sys.path[:] = original


if __name__ == '__main__':
    sys.exit(main())
