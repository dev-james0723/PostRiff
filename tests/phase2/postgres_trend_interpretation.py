"""Portable040-only interpretation acceptance; every SQL case must run."""
from pathlib import Path
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main():
    previous = list(sys.path)
    prior_dsn = os.environ.get('TREND_INTERPRETATION_TEST_DSN')
    try:
        sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        raw = os.environ.get('POSTRIFF_TEST_DSN')
        if not raw or any(k in os.environ for k in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR', 'PGOPTIONS')):
            raise ValueError('explicit isolated CI DSN required; libpq overrides forbidden')
        params = conninfo_to_dict(raw)
        if (set(params) - {'host', 'port', 'dbname', 'user'}
                or (params.get('host'), params.get('port'), params.get('dbname')) != ('127.0.0.1', '55438', 'postgres')):
            raise ValueError('only canonical fresh runner127.0.0.1:55438/postgres allowed')
        with psycopg.connect(raw) as db:
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                raise RuntimeError('canonical rls.sql baseline required; use scripts/postriff_pg_suite.py')
            if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:
                raise RuntimeError('003/pr_runtime must be absent')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        os.environ['TREND_INTERPRETATION_TEST_DSN'] = raw
        suite = unittest.defaultTestLoader.loadTestsFromName('test_trend_interpretation_context')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() and not result.skipped else 1
    finally:
        sys.path[:] = previous
        if prior_dsn is None:
            os.environ.pop('TREND_INTERPRETATION_TEST_DSN', None)
        else:
            os.environ['TREND_INTERPRETATION_TEST_DSN'] = prior_dsn


if __name__ == '__main__':
    raise SystemExit(main())
