"""Portable real SQL service, enrichment, notification and platform acceptance.

Only the existing disposable runner's exact target is accepted. No production
credentials,003 runtime installation, provider calls or skipped DB tests.
"""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    dsn = os.environ.get('POSTRIFF_TEST_DSN', '')
    params = conninfo_to_dict(dsn)
    if (set(params) - {'host','port','dbname','user'} or params.get('host') != '127.0.0.1'
            or params.get('port') != '55438' or params.get('dbname') != 'postgres'
            or any(os.environ.get(k) for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'))):
        raise ValueError('use scripts/postriff_pg_suite.py with its exact disposable local DSN')
    original_path = list(sys.path)
    env_names = ('TREND_SERVICE_TEST_DSN', 'TREND_ENRICHMENT_TEST_DSN', 'TREND_NOTIFICATIONS_TEST_DSN', 'TREND_EXPOSURE_TEST_DSN')
    original_env = {k: os.environ.get(k) for k in env_names}
    try:
        with psycopg.connect(dsn) as db:
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                raise RuntimeError('canonical disposable rls.sql baseline required')
            if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0] is not None:
                raise RuntimeError('canonical production dependency proof must not contain003/pr_runtime')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        for k in env_names:
            os.environ[k] = dsn
        sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
        suite = unittest.defaultTestLoader.loadTestsFromNames([
            'test_trend_integration', 'test_trend_enrichment', 'test_trend_exposures',
            'test_trend_notifications', 'test_trend_platform_states', 'test_trend_pools',
            'test_trend_learning', 'test_trend_analytics_retention', 'test_trend_analytics_runtime'])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() and not result.skipped else 1
    finally:
        sys.path[:] = original_path
        for k, v in original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == '__main__':
    sys.exit(main())
