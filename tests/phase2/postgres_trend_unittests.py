"""DSN-gated trend unittest coverage guard, discovered by scripts/postriff_pg_suite.py.

ci-python runs ``unittest discover`` WITHOUT a database, so every trend module
gated on POSTRIFF_TEST_DSN or a TREND_*_TEST_DSN skips there. Those modules are
only real coverage if a tests/phase2/postgres_*.py wrapper loads them under the
disposable DSN and fails on any skip. This guard keeps that true:

* statically maps every gated tests/test_trend_*.py module (and class, when a
  wrapper loads classes) to the wrappers that load it;
* fails if a wrapper loads gated tests without failing on skipped tests;
* runs every gated module/class that no wrapper loads, under the disposable
  DSN, and fails on any failure or skip (e.g. a missing-DSN skip).

Only the runner's exact disposable target is accepted. No provider, model,
network or production credential is used.
"""
import json
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
GATE = re.compile(r'\b(POSTRIFF_TEST_DSN|TREND_[A-Z_]+_TEST_DSN|PG_DSN|dedicated_test_dsn)\b')
ENV = re.compile(r'^(POSTRIFF_TEST_DSN|TREND_[A-Z_]+_TEST_DSN)$')
LOADED = re.compile(r"""['"](test_trend_[a-z0-9_]+)(?:\.([A-Za-z_][A-Za-z0-9_]*))?['"]""")
SKIP_FAILS = re.compile(r'result\.skipped|\bskips\b')


def disposable_dsn():
    from psycopg.conninfo import conninfo_to_dict
    dsn = os.environ.get('POSTRIFF_TEST_DSN', '')
    params = conninfo_to_dict(dsn) if dsn else {}
    if (not dsn or set(params) - {'host', 'port', 'dbname', 'user'}
            or (params.get('host'), params.get('port'), params.get('dbname')) != ('127.0.0.1', '55438', 'postgres')
            or any(os.environ.get(k) for k in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR', 'PGOPTIONS'))):
        raise ValueError('use scripts/postriff_pg_suite.py with its exact disposable local DSN')
    return dsn


def gated_modules():
    """Module name -> sorted DSN environment names it is gated on."""
    result = {}
    for path in sorted((ROOT / 'tests').glob('test_trend_*.py')):
        names = sorted(set(GATE.findall(path.read_text())))
        if names:
            result[path.stem] = names
    return result


def wrapper_coverage():
    """Module -> {'all': bool, 'classes': set, 'wrappers': list, 'unsafe': list}."""
    coverage = {}
    for path in sorted((ROOT / 'tests/phase2').glob('postgres_*.py')):
        if path.resolve() == SELF:
            continue
        text = path.read_text()
        for module, cls in LOADED.findall(text):
            item = coverage.setdefault(module, {'all': False, 'classes': set(), 'wrappers': [], 'unsafe': []})
            if cls:
                item['classes'].add(cls)
            else:
                item['all'] = True
            if path.name not in item['wrappers']:
                item['wrappers'].append(path.name)
            if not SKIP_FAILS.search(text) and path.name not in item['unsafe']:
                item['unsafe'].append(path.name)
    return coverage


def test_classes(module):
    found = []
    for name in sorted(dir(module)):
        value = getattr(module, name)
        if (isinstance(value, type) and issubclass(value, unittest.TestCase) and value.__module__ == module.__name__
                and unittest.defaultTestLoader.getTestCaseNames(value)):
            found.append(name)
    return found


def main():
    dsn = disposable_dsn()
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    import importlib
    import psycopg
    gated, coverage = gated_modules(), wrapper_coverage()
    report, uncovered, unsafe, env_names = {}, [], [], set()
    for module_name, names in gated.items():
        item = coverage.get(module_name, {'all': False, 'classes': set(), 'wrappers': [], 'unsafe': []})
        unsafe.extend(module_name + ' via ' + w for w in item['unsafe'])
        if item['all']:
            missing = []
        else:
            missing = [c for c in test_classes(importlib.import_module(module_name)) if c not in item['classes']]
            uncovered.extend(module_name + '.' + c for c in missing)
            if missing:
                env_names.update(n for n in names if ENV.match(n))
        report[module_name] = {'gates': names, 'wrappers': item['wrappers'],
                               'loaded': 'module' if item['all'] else sorted(item['classes']), 'run_here': missing}
    if uncovered:
        with psycopg.connect(dsn) as db:
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                raise RuntimeError('canonical disposable rls.sql baseline required')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    original = {name: os.environ.get(name) for name in env_names}
    try:
        for name in env_names:
            os.environ[name] = dsn
        suite = unittest.defaultTestLoader.loadTestsFromNames(uncovered)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    print(json.dumps({'execution': 'disposable_postgresql_coverage_guard', 'gated_modules': len(gated),
                      'run_here': uncovered, 'tests': result.testsRun, 'failures': len(result.failures),
                      'errors': len(result.errors), 'skips': len(result.skipped),
                      'wrappers_without_skip_failure': unsafe, 'coverage': report}, indent=1, sort_keys=True), flush=True)
    if not gated:
        print('NO_GATED_TREND_MODULES_FOUND', flush=True)
        return 1
    return 0 if result.wasSuccessful() and not result.skipped and not unsafe else 1


if __name__ == '__main__':
    sys.exit(main())
