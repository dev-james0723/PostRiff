"""Portable forecast acceptance: fresh baseline+040, no003, no skipped cases."""
from pathlib import Path
import datetime
import hashlib
import json
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main():
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    paths = list((ROOT / 'src/postriff_phase2/growth/trends').rglob('*.py'))
    paths += [ROOT / p for p in ('tests/test_trend_forecast_postgres.py', 'tests/phase2/postgres_trend_forecast.py',
        'tests/test_trend_advanced_pipeline.py', 'tests/test_trend_forecast.py', 'tests/test_trend_metrics.py',
        'tests/test_trend_receipts.py', 'tests/phase2/rls.sql', 'migrations/postriff/040_social_trend_intelligence.sql',
        'scripts/postriff_pg_suite.py')]
    paths += list((ROOT / 'tests/fixtures/trends').rglob('*.json'))
    def hashes():
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    before = hashes(); started = time.monotonic()
    from test_trend_forecast_postgres import dedicated_test_dsn
    dsn = dedicated_test_dsn()  # Before any connection, including migration setup.
    import psycopg
    with psycopg.connect(dsn) as db:
        version = db.execute('SHOW server_version').fetchone()[0]
        if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
            raise RuntimeError('Use scripts/postriff_pg_suite.py with its disposable rls.sql baseline')
        if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:
            raise RuntimeError('Acceptance requires current production-shaped no003 baseline')
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('test_trend_forecast_postgres'))
    after = hashes()
    receipt = {'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'execution_state': 'actual_disposable_postgresql_with_explicit_synthetic_reviewed_sql_fixtures',
        'postgres_version': version, 'python_version': sys.version, 'target': '127.0.0.1:55438/postgres',
        'command': 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests:/private/tmp/rafii-trend-release-deps '
                   '/Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python scripts/postriff_pg_suite.py postgres_trend_forecast',
        'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
        'seconds': round(time.monotonic()-started, 3), 'source_guard_before': before, 'source_guard_after': after,
        'source_guard_unchanged': before == after, 'provider_model_calls': 0,
        'limitations': ['All source activity and review records are synthetic; positive qualification is not live qualification',
                       'No production registry, database, migrations, flags or deployment changed',
                       'No M3 completion claim'],
        'coverage': ['Current040/no003; actual producer->chunked candidate; real evaluator and current registry',
                     'Preregistered complete slots; actual rolling arithmetic; synthetic review->admission->persist->read->retry',
                     'NOSUPERUSER NOBYPASSRLS runtime, browser SQL denial and authenticated tenant/reviewer gates',
                     'Current revocation, raw-storage denial, method downgrade, late preregistration, missing DAG, chunk tamper']}
    name = '/private/tmp/trend-forecast-postgres-validation.json'
    Path(name).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('source_guard_before', 'source_guard_after')}), flush=True)
    print('SOURCE_BOUND_RECEIPT ' + name, flush=True)
    return 0 if result.wasSuccessful() and not result.skipped and before == after else 1


if __name__ == '__main__': sys.exit(main())
