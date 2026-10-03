"""Own a disposable loopback cluster and run one explicitly selected script group.

LOCAL TEST ONLY. POSTRIFF_TEST_PG_PORT selects1024..65535 (default55438).
Refuse an occupied target before init/start; never adopt/stop another cluster.
The parent owns real PG execution. All child logs are streamed in full.
"""
from __future__ import annotations

from contextlib import contextmanager
import ast
import json
import hashlib
import os
import shlex
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/phase2'))
from local_pg_target import selected_target

PG = Path(os.environ.get('POSTRIFF_PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))


@contextmanager
def owned_cluster(target, pg, env, *, baseline=True, migrations=(), state=None):
    env = target.child_env(env)  # Direct callers also refuse redirects before I/O.
    state = {} if state is None else state
    state.update(stage='preflight', started=False, start_attempted=False,
                 stop_attempted=False, stopped=False)
    target.assert_available()  # No initdb/temp data before admission/ownership.
    tmp = tempfile.mkdtemp(prefix='postriff-test-pg-')
    data, log = Path(tmp) / 'data', Path(tmp) / 'postgres.log'
    state['data_directory'] = str(data)
    primary = None
    try:
        state['stage'] = 'initdb'
        subprocess.run([str(pg / 'initdb'), '-D', str(data), '-A', 'trust',
                        '--no-locale', '-E', 'UTF8'], check=True,
                       env=env, stdout=subprocess.DEVNULL)
        state['stage'] = 'prestart'
        target.assert_available()  # Catch a listener acquired during initdb.
        state.update(stage='start', start_attempted=True)
        subprocess.run([str(pg / 'pg_ctl'), '-D', str(data), '-l', str(log),
                        '-o', shlex.join(['-h', '127.0.0.1', '-p', str(target.port), '-k', tmp]), '-w', 'start'],
                       check=True, env=env, stdout=subprocess.DEVNULL)
        state['started'] = True
        if baseline:
            state['stage'] = 'baseline'
            subprocess.run([str(pg / 'psql'), target.dsn(), '-X', '-v', 'ON_ERROR_STOP=1',
                            '-q', '-f', str(ROOT / 'tests/phase2/rls.sql')],
                           check=True, env=env, stdout=subprocess.DEVNULL)
        for path in migrations:
            state['stage'] = 'migration'
            subprocess.run([str(pg / 'psql'), target.dsn(), '-X', '-v', 'ON_ERROR_STOP=1',
                            '-q', '-f', str(path)], check=True, env=env,
                           stdout=subprocess.DEVNULL)
        state['stage'] = 'children'
        yield
    except BaseException as error:
        primary = error
        state['error'] = error_detail(error)
        if isinstance(error, subprocess.CalledProcessError):
            try:
                if log.exists():
                    print(log.read_text(), flush=True)
            except OSError as diagnostic_error:
                state['diagnostic_error'] = error_detail(diagnostic_error)
        raise
    finally:
        if state['started']:
            state['stop_attempted'] = True
            try:
                subprocess.run([str(pg / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'],
                               check=True, env=env, stdout=subprocess.DEVNULL)
                state['stopped'] = True
            except BaseException as cleanup_error:
                state['cleanup_error'] = error_detail(cleanup_error)
                state['retained_directory'] = tmp
                if primary is None:
                    raise
                primary.add_note('Owned cluster stop also failed: ' + type(cleanup_error).__name__)
        # A failed pg_ctl start can leave ownership uncertain. Retain only our
        # random directory for parent reconciliation; never adopt/stop a listener.
        if state['stopped'] or not state['start_attempted']:
            try:
                shutil.rmtree(tmp)
                state['directory_removed'] = True
            except OSError as removal_error:
                state['directory_cleanup_error'] = error_detail(removal_error)
                state['retained_directory'] = tmp
                if primary is None:
                    raise
                primary.add_note('Owned directory cleanup also failed: ' + type(removal_error).__name__)
        else:
            state['retained_directory'] = tmp


def error_detail(error):
    """Record identity/type and exit without echoing supplied inputs or argv."""
    result = {'type': type(error).__name__}
    if isinstance(error, subprocess.CalledProcessError):
        result['returncode'] = error.returncode
    return result


def child_environment(target, environ):
    env = target.child_env(environ)
    # C locale is required for the macOS PG17 postmaster. Provider research stays
    # under existing caller/fixture policy; no lease/grant approval is invented.
    env['LC_ALL'] = 'C'
    env.setdefault('POSTRIFF_RESEARCH', '0')
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'tests'),
                                       str(ROOT / 'tests/phase2'), env.get('PYTHONPATH', '')])
    return env


# Parent-integrated catalogue fixture is absent at the worker's exact base.
# Referencing its group name does not create/edit that concurrently owned file.
GROWTH_PARENT_GROUPS = frozenset({
    'postgres_growth_credit_rewrite', 'postgres_growth_base_check_catalog',
    'postgres_growth_genome_catalog', 'postgres_pricing_beta_events',
})
GROWTH_SCHEMA = ('020_credit_quotes.sql', '021_credit_purchases.sql',
                 '022_credit_payment_lifecycle.sql', '048_pricing_credit_catalog_v2.sql',
                 '050_free_lifecycle_bootstrap.sql', '051_pricing_public_four_plans.sql', '052_fixed_plan_checkout_approval.sql')


def group_migrations(paths, env):
    if not any(path.stem in GROWTH_PARENT_GROUPS for path in paths):
        return ()
    if env.get('POSTRIFF_TEST_OWNED_PG') != 'task9-growth':
        raise RuntimeError('Parent exclusive disposable-PG marker task9-growth required')
    result = tuple(ROOT / 'migrations/postriff' / name for name in GROWTH_SCHEMA)
    if any(not path.is_file() for path in result):
        raise ValueError('required parent Growth test schema migration missing')
    return result


def source_bindings(paths):
    sources = {ROOT / 'scripts/postriff_pg_suite.py',
               ROOT / 'scripts/postriff_disposable_postgres.py',
               ROOT / 'tests/phase2/local_pg_target.py', ROOT / 'tests/phase2/rls.sql', *paths}
    # Bind the actual baseline migration sources, including psql's relative \ir inputs.
    sources.update((ROOT / 'migrations/postriff').glob('*.sql'))
    sources.add(ROOT / 'tests/local_pg_target.py')
    # Actual nested admission consumers are part of the selected test graph.
    sources.update(ROOT / ('tests/test_trend_' + name + '.py') for name in (
        'pipeline', 'planner', 'advanced_pipeline', 'forecast_postgres', 'media_jobs',
        'whitespace_admission', 'enrichment', 'integration', 'notifications'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}


def emit_receipt(target, paths, before, results, argv, clusters, *, execution,
                 binder, error=None):
    after, binding_error = None, None
    try:
        after = binder(paths)
    except Exception as failure:
        binding_error = error_detail(failure)
    failed = [r['script'] for r in results if r.get('exit', r.get('exitCode', 0))]
    unchanged = after is not None and before == after
    failure = bool(failed) or not unchanged or error is not None or binding_error is not None
    print(json.dumps({'status': 'fail' if failure else 'pass', 'execution': execution,
                      'partial': error is not None or binding_error is not None,
                      'target': target.label(), 'results': results, 'failed': failed,
                      'argv': argv, 'source_before': before, 'source_after': after,
                      'source_unchanged': unchanged, 'error': error_detail(error) if error is not None else None,
                      'source_after_error': binding_error, 'clusters': clusters}), flush=True)
    return int(failure)


def failure_receipt(*args, error, **kwargs):
    # Receipt I/O failures must never mask the original setup/stop exception.
    try:
        emit_receipt(*args, error=error, **kwargs)
    except Exception as receipt_error:
        error.add_note('Partial receipt could not be emitted: ' + type(receipt_error).__name__)


def resolve_scripts(names):
    if not names:
        raise ValueError('No selected PostgreSQL tests')
    paths = []
    for name in names:
        path = (ROOT / name).resolve()
        if (path.parent != ROOT / 'tests/phase2' or not path.name.startswith('postgres_')
                or path.suffix != '.py' or not path.is_file()):
            raise ValueError('select only existing tests/phase2/postgres_*.py scripts')
        if path in paths:
            raise ValueError('duplicate PostgreSQL script selection')
        paths.append(path)
    return paths


def validate_script_targets(paths, target):
    """Refuse legacy module DSN constants before any cluster/process admission.

    Recovery bases can contain older unowned purchase fixtures. Keep their
    source/assertions intact, but never execute a known fixed foreign DSN.
    This inspects source only; it does not import or alter fixture code.
    """
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(n, ast.Name) and n.id in ('DSN', 'BASE_DSN') for n in node.targets)
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                try:
                    target.validate_dsn(node.value.value)
                except ValueError as error:
                    raise ValueError('legacy fixture ' + path.name + ' has a nonselected constant DSN; parent adaptation required') from error


def main(scripts: list[str]) -> int:
    target = selected_target()  # Must precede socket, binary lookup and psql.
    paths = resolve_scripts(scripts)
    validate_script_targets(paths, target)
    if not (PG / 'initdb').is_file():
        print(json.dumps({'status': 'validation_unavailable', 'cause': f'{PG}/initdb not found'}))
        return 3
    env = child_environment(target, os.environ)
    migrations = group_migrations(paths, env)
    before = source_bindings(paths)
    results = []
    # migration013 owns a minimal blank schema; it cannot share a baseline group.
    if any(p.name == 'postgres_migration_013.py' for p in paths) and len(paths) != 1:
        raise ValueError('migration013 requires its own blank-cluster group')
    clusters = [{}]
    receipt = dict(execution='disposable-local-postgres', binder=source_bindings)
    args = (target, paths, before, results, [sys.executable, str(Path(__file__).resolve()), *scripts], clusters)
    try:
        with owned_cluster(target, PG, env, baseline=paths[0].name != 'postgres_migration_013.py',
                           migrations=migrations, state=clusters[0]):
            for path in paths:
                print('RUN ' + str(path.relative_to(ROOT)), flush=True)
                run = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env)
                results.append({'script': str(path.relative_to(ROOT)), 'exit': run.returncode})
    except BaseException as error:
        failure_receipt(*args, error=error, **receipt)
        raise
    return emit_receipt(*args, **receipt)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
