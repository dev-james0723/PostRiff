"""Full actual local PostgreSQL catalogue; full logs; a new owned cluster/group."""
import json
import os
from pathlib import Path
import sys
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/phase2'))
from local_pg_target import selected_target
from postriff_disposable_postgres import (
    child_environment, owned_cluster, group_migrations, source_bindings,
    emit_receipt, failure_receipt, validate_script_targets,
)

PG = Path(os.environ.get('POSTRIFF_PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))
SEQUENCES = {
    'postgres_plan_guards': ('postgres_repository', 'postgres_plan_guards'),
    'postgres_instagram_lifecycle': ('postgres_instagram_lifecycle', 'postgres_safety'),
}


def selected_groups(names=()):
    catalogue = {p.stem: p for p in sorted((ROOT / 'tests/phase2').glob('postgres_*.py'))}
    # These are sequence members, not exclusions from executable coverage.
    standalone = {k: v for k, v in catalogue.items() if k not in ('postgres_repository', 'postgres_safety')}
    if names:
        if len(set(names)) != len(names) or set(names) - set(standalone):
            raise ValueError('Unknown, duplicate or sequence-only PostgreSQL selection')
        standalone = {k: v for k, v in standalone.items() if k in names}
    if not standalone:
        raise ValueError('No selected PostgreSQL tests')
    return [tuple(catalogue[name] for name in SEQUENCES.get(key, (key,))) for key in standalone]


def main():
    target = selected_target()  # Fail invalid/conflicting input before any I/O.
    groups = selected_groups(sys.argv[1:])
    paths = [p for group in groups for p in group]
    validate_script_targets(paths, target)
    if not (PG / 'initdb').is_file():
        print(json.dumps({'status': 'VALIDATION_UNAVAILABLE',
                          'reason': f'{PG}/initdb missing; set POSTRIFF_PG_BIN'}))
        return 3
    env = child_environment(target, os.environ)
    env['POSTRIFF_RESEARCH'] = '0'
    setups = [group_migrations(group, env) for group in groups]  # All admission before sockets.
    before = source_bindings(paths)
    results = []
    clusters = []
    receipt = dict(execution='local-db; synthetic external services', binder=source_bindings)
    args = (target, paths, before, results, [sys.executable, *sys.argv], clusters)
    try:
        for group, migrations in zip(groups, setups):
            state = {'scripts': [str(p.relative_to(ROOT)) for p in group]}
            clusters.append(state)
            with owned_cluster(target, PG, env, baseline=group[0].stem != 'postgres_migration_013',
                               migrations=migrations, state=state):
                for path in group:
                    print('RUN ' + str(path.relative_to(ROOT)), flush=True)
                    start = time.monotonic()
                    result = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env)
                    results.append({'script': str(path.relative_to(ROOT)), 'exitCode': result.returncode,
                                    'seconds': round(time.monotonic() - start, 2)})
    except BaseException as error:
        failure_receipt(*args, error=error, **receipt)
        raise
    return emit_receipt(*args, **receipt)


if __name__ == '__main__':
    sys.exit(main())
