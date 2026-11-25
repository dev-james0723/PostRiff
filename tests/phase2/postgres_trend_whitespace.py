"""Portable whitespace and semantic-current-read SQL acceptance, baseline040/no003.

Run through scripts/postriff_pg_suite.py postgres_trend_whitespace. All source
and independently reviewed qualification records are explicitly synthetic.
"""
from local_pg_target import selected_target
from pathlib import Path
import datetime
import hashlib
import json
import os
import sys
import time
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main():
    selected_target(require_dsn=True)  # Before any nested validator/connection.
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    started = time.monotonic()
    # Capture before lazy imports, then retain the actual imported source graph
    # plus all trend method-artifact inputs, including interpretation_context.
    paths = set(ROOT.joinpath('src').rglob('*.py')) | set(ROOT.joinpath('tests').rglob('*.py'))
    paths |= set(ROOT.joinpath('tests/fixtures/trends').rglob('*.json'))
    paths |= {ROOT / p for p in ('tests/phase2/rls.sql','migrations/postriff/040_social_trend_intelligence.sql',
                               'scripts/postriff_pg_suite.py', 'scripts/postriff_disposable_postgres.py', 'tests/phase2/local_pg_target.py')}
    before_all = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    previous = os.environ.get('TREND_WHITESPACE_TEST_DSN')
    os.environ['TREND_WHITESPACE_TEST_DSN'] = os.environ.get('POSTRIFF_TEST_DSN', '')
    try:
        from test_trend_whitespace_admission import dedicated_test_dsn
        dsn = dedicated_test_dsn()  # No connection may precede admission.
        import psycopg
        with psycopg.connect(dsn) as db:
            version = db.execute('SHOW server_version').fetchone()[0]
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                raise RuntimeError('Use the disposable runner and canonical rls.sql baseline')
            if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:
                raise RuntimeError('Current production-shaped proof requires no003/pr_runtime')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        suite = unittest.defaultTestLoader.loadTestsFromName('test_trend_whitespace_admission')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        imported = {Path(m.__file__).resolve() for m in tuple(sys.modules.values())
                    if getattr(m, '__file__', None) and str(m.__file__).endswith('.py')}
        imported = {p for p in imported if p.is_relative_to(ROOT)}
        guarded = imported | {p for p in paths if ('/growth/trends/' in str(p)
            or '/tests/fixtures/trends/' in str(p) or p.suffix == '.sql')}
        guarded |= {Path(__file__).resolve(), ROOT / 'scripts/postriff_pg_suite.py', ROOT / 'scripts/postriff_disposable_postgres.py', ROOT / 'tests/phase2/local_pg_target.py'}
        before = {str(p.relative_to(ROOT)): before_all.get(str(p.relative_to(ROOT))) for p in sorted(guarded)}
        after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(guarded)}
        from postriff_phase2.growth.trends import advanced_pipeline, pipeline, whitespace_admission
        method_graph = {'pipeline': pipeline.implementation_methods(),
            'advanced': {k: advanced_pipeline._method(k) for k in ('genome','graph','saturation','whitespace_candidate')},
            'whitespace': whitespace_admission.WhitespaceAdmission(None)._method()}
        receipt = {'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'execution_state': 'actual_disposable_postgresql_synthetic_source_generation_and_review_records',
            'target': selected_target(require_dsn=True).label(), 'postgres_version': version, 'python_version': sys.version,
            'command': [sys.executable, 'scripts/postriff_pg_suite.py', 'postgres_trend_whitespace'],
            'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
            'seconds': round(time.monotonic()-started,3), 'source_guard_before': before, 'source_guard_after': after,
            'source_guard_unchanged': before == after, 'method_graph': method_graph,
            'provider_model_calls': 0, 'generation_transport': 'injected ServerModelRuntime synthetic responses only',
            'limitations': ['Synthetic positive review fixtures do not establish empirical qualification or M3 completion',
                'No production data, registry, migration, deployment or flags modified'],
            'coverage': ['All original29 cases retained; exact DSN admission refuses libpq redirects before connecting',
                'Real service typed current get/stored/list hides operator reviews; superseding review blocks accept/replay/apply/queue',
                'Actual advanced enqueue/run genome/saturation/graph; reviewed semantics and literal native phrases; no global qualification',
                'Current review registry/config gates; viewer current reads without edit dependency locks; owner review authority remains active',
                'NOSUPERUSER NOBYPASSRLS runtime; canonical baseline040 only, no003/pr_runtime']}
        path = Path(str(Path(tempfile.gettempdir()) / 'trend-whitespace-portable-receipt.json'))
        path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
        print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_guard_before','source_guard_after','method_graph')}),flush=True)
        print('SOURCE_BOUND_RECEIPT '+str(path),flush=True)
        return 0 if result.wasSuccessful() and not result.skipped and before == after else 1
    finally:
        if previous is None:
            os.environ.pop('TREND_WHITESPACE_TEST_DSN',None)
        else:
            os.environ['TREND_WHITESPACE_TEST_DSN'] = previous


if __name__ == '__main__':
    sys.exit(main())
