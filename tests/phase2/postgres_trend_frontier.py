"""Frontier acceptance on the suite's fresh local cluster; no second fixed port."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
import psycopg
from psycopg.conninfo import conninfo_to_dict
ROOT = Path(__file__).resolve().parents[2]
PATHS = ['src/postriff_phase2/growth/trends/'+name+'.py' for name in
         ('frontier','frontier_runtime','analytics_runtime','store','jobs')]


def main():
    dsn = os.environ.get('POSTRIFF_TEST_DSN', '')
    params = conninfo_to_dict(dsn)
    if (set(params)-{'host','port','dbname','user'}
            or (params.get('host'), params.get('port'), params.get('dbname')) != ('127.0.0.1','55438','postgres')
            or any(k in os.environ for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'))):
        raise ValueError('exact disposable script runner target required')
    before = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PATHS}
    with psycopg.connect(dsn) as db:
        if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:
            raise ValueError('003 runtime dependency forbidden')
        if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
            raise ValueError('canonical disposable rls.sql baseline required')
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    os.environ['TREND_SERVICE_TEST_DSN'] = dsn
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'test_trend_frontier.FrontierOffline','test_trend_frontier.FrontierSQL',
        'test_trend_frontier_runtime.FrontierRuntimeOffline','test_trend_frontier_runtime.FrontierRuntimeSQL'])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    drift = [p for p, checksum in before.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != checksum]
    print(json.dumps({'execution':'actual_disposable_postgresql_synthetic_sources','tests':result.testsRun,
                      'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'source_drift':drift}))
    return int(not result.wasSuccessful() or bool(result.skipped) or bool(drift))


if __name__ == '__main__':
    sys.exit(main())
