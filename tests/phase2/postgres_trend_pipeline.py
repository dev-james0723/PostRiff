"""Disposable PostgreSQL pipeline acceptance, automatically found by postriff_pg_suite.

The runner applies rls.sql/035 first; this wrapper applies040 when absent and runs
real300-source ingestion, crash/retry, sealed verification and deletion/purge tests.
All content is synthetic. No provider/model/network client is used.
"""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from test_trend_pipeline import dedicated_test_dsn


def main():
    dsn=dedicated_test_dsn()
    with psycopg.connect(dsn) as db:
        if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
            raise RuntimeError('Run through scripts/postriff_pg_suite.py; the disposable rls.sql baseline is required')
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    suite=unittest.defaultTestLoader.loadTestsFromName('test_trend_pipeline')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    # CI acceptance must never quietly replace durable coverage with skipped tests.
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__=='__main__':sys.exit(main())
