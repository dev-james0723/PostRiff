"""Disposable CI only: recorded production schema upgrade and synthetic restore.

The baseline contains migration names/hashes, no data or credentials. This does
not attest the hosted pool, production backup, provider or release acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if sys.platform != 'linux' or os.environ.get('CI') != 'true':
    raise SystemExit('Telegram schema upgrade validation requires disposable cloud Linux CI.')

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from postriff_migrate import apply

PG = Path(os.environ['POSTRIFF_PG_BIN'])
ledger = json.loads((ROOT / 'scripts/telegram/production_schema_baseline.json').read_text())
paths = []
for row in ledger:
    path = ROOT / 'migrations/postriff' / row['name']
    if path.parent != ROOT / 'migrations/postriff' or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        raise SystemExit('Production baseline source checksum mismatch; no database created.')
    paths.append(path)
telegram = [ROOT / 'migrations/postriff/116_telegram_identity_controls.sql',
            ROOT / 'migrations/postriff/117_telegram_capabilities.sql']
bootstrap = (ROOT / 'tests/phase2/rls.sql').read_text().split('\\ir ')[0].replace('\\set ON_ERROR_STOP on', '')
result = {'execution': 'disposable_cloud_schema_and_synthetic_restore',
          'realTelegramE2E': False, 'productionChanges': 'NONE', 'baselineMigrations': len(paths)}

with tempfile.TemporaryDirectory(prefix='telegram-upgrade-ci-') as tmp:
    data, sock = Path(tmp) / 'data', Path(tmp) / 'socket'
    sock.mkdir()
    subprocess.run([str(PG / 'initdb'), '-D', str(data), '-A', 'trust', '--no-locale', '-E', 'UTF8'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(PG / 'pg_ctl'), '-D', str(data), '-l', str(Path(tmp) / 'server.log'),
                    '-o', f'-k {sock} -h "" -p 56598', '-w', 'start'], check=True, stdout=subprocess.DEVNULL)
    try:
        base = f'host={sock} port=56598 dbname=postgres'
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(bootstrap, prepare=False)
            apply(db, paths)
            # This intentionally models the recorded old schema without generic
            # Agent permission/task migrations or unrelated pending migrations.
            assert db.execute("SELECT to_regclass('public.pr_agent_permission_state'),to_regclass('public.pr_agent_tasks')").fetchone() == (None, None)
            uid = '00000000-0000-4000-8000-000000000011'
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (uid,))
            wid = db.execute("SELECT public.pr_bootstrap(%s,'studio')", (uid,)).fetchone()[0]
            state = {'syntheticRestoreMarker': '繁中保留', 'approval': {'hash': 'immutable-original'}}
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), wid))
            before = db.execute('SELECT id::text,state,revision FROM public.pr_workspaces ORDER BY id').fetchall()
            backup = Path(tmp) / 'before.dump'
            started = time.monotonic()
            subprocess.run([str(PG / 'pg_dump'), base, '-Fc', '-f', str(backup)], check=True)
            result['syntheticBackupSeconds'] = round(time.monotonic() - started, 3)
            upgraded = apply(db, paths + telegram)
            assert [r['name'] for r in upgraded if r['status'] == 'PENDING'] == [p.name for p in telegram]
            assert before == db.execute('SELECT id::text,state,revision FROM public.pr_workspaces ORDER BY id').fetchall()
            assert all(r['status'] == 'APPLIED' for r in apply(db, paths + telegram))
            tables = db.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'pr_telegram%' ORDER BY relname").fetchall()
            assert len(tables) == 17 and all(rls and forced for _, rls, forced in tables)
            for table, _, _ in tables:
                for role in ('anon', 'authenticated'):
                    assert not any(db.execute('SELECT has_table_privilege(%s,%s,%s)', (role, 'public.' + table, action)).fetchone()[0] for action in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'))
                assert db.execute('SELECT has_table_privilege(%s,%s,%s)', ('service_role', 'public.' + table, 'SELECT')).fetchone()[0]
            db.execute('CREATE DATABASE telegram_restore_ci')
        target = f'host={sock} port=56598 dbname=telegram_restore_ci'
        started = time.monotonic()
        subprocess.run([str(PG / 'pg_restore'), '-d', target, '--exit-on-error', str(backup)], check=True)
        result['syntheticRestoreSeconds'] = round(time.monotonic() - started, 3)
        with psycopg.connect(target, autocommit=True) as restored:
            assert before == restored.execute('SELECT id::text,state,revision FROM public.pr_workspaces ORDER BY id').fetchall()
            assert restored.execute("SELECT to_regclass('public.pr_telegram_destinations')").fetchone()[0] is None
            assert restored.execute('SELECT count(*) FROM postriff_private.schema_migrations').fetchone()[0] == len(paths)
        result.update(status='PASS', additiveUpgradePreservesExistingState=True, ledgerReplayIdempotent=True,
                      telegramTablesWithForcedRls=len(tables), browserCrudPrivileges=False,
                      rollbackRestoresSyntheticBaseline=True, productionBackup='NOT_RUN', hostedSchemaDrift='NOT_ATTESTED')
    finally:
        subprocess.run([str(PG / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'], check=True, stdout=subprocess.DEVNULL)

out = ROOT / '.jcb-artifacts/telegram'
out.mkdir(parents=True, exist_ok=True)
(out / 'production-upgrade-tests.json').write_text(json.dumps(result, indent=2) + '\n')
print('TELEGRAM_PRODUCTION_UPGRADE ' + json.dumps(result))
