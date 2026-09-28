"""Portable040-only durable local media acceptance (no003, no live services)."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]

def main():
    previous=list(sys.path)
    try:
        sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
        import psycopg
        from test_trend_media_jobs import dedicated_test_dsn
        with psycopg.connect(dedicated_test_dsn()) as db:
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                raise RuntimeError('Canonical rls.sql baseline required; use scripts/postriff_pg_suite.py')
            if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:
                raise RuntimeError('003 must be absent')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['test_trend_media_jobs','test_trend_media_storage','test_trend_media_http']))
        return 0 if result.wasSuccessful() and not result.skipped else 1
    finally:
        sys.path[:]=previous

if __name__=='__main__':
    raise SystemExit(main())
