"""Full hosted migration ledger, populated upgrade/replay, RLS and measured DB restore."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psycopg
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from postriff_migrate import apply,plan,migrations
PG=Path(os.environ.get('POSTRIFF_PG_BIN','/opt/homebrew/opt/postgresql@17/bin'))
DSN='host=127.0.0.1 port=55438 dbname=postgres'
with psycopg.connect(DSN,autocommit=True) as admin:
    admin.execute('CREATE DATABASE migration_candidate')
    admin.execute('CREATE DATABASE migration_restore')
setup=(ROOT/'tests/phase2/rls.sql').read_text().split('\\ir ')[0].replace('\\set ON_ERROR_STOP on','')
# Roles already exist cluster-wide from the independent suite harness.
setup='\n'.join(line for line in setup.splitlines() if not line.startswith('create role '))
base='host=127.0.0.1 port=55438 dbname=migration_candidate'
paths=migrations()
with psycopg.connect(base,autocommit=True) as db:
    db.execute(setup,prepare=False)
    old=[p for p in paths if int(p.name[:3])<=12]
    assert len(apply(db,old))==11
    db.execute("INSERT INTO auth.users VALUES ('00000000-0000-0000-0000-000000000011')")
    wid=db.execute("SELECT public.pr_bootstrap('00000000-0000-0000-0000-000000000011','studio')").fetchone()[0]
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps({'recoveryMarker':'繁中保留','approval':{'hash':'immutable-original'}}),wid))
    before=db.execute('SELECT id::text,state,revision FROM public.pr_workspaces').fetchall()
    upgrade=apply(db)
    assert [r['name'] for r in upgrade if r['status']=='PENDING']==[p.name for p in paths if int(p.name[:3])>12]
    assert before==db.execute('SELECT id::text,state,revision FROM public.pr_workspaces').fetchall()
    assert all(r['status']=='APPLIED' for r in apply(db))
    assert db.execute('SELECT count(*) FROM postriff_private.schema_migrations').fetchone()[0]==len(paths)
    # Tenant with no membership cannot enumerate owner-only cost or planning rows.
    db.execute('SET ROLE authenticated')
    db.execute("SELECT set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000099',false)")
    for table in ('pr_campaigns','pr_recurring_tasks','pr_recurring_occurrences','pr_suggestions','pr_usage_ledger'):
        assert db.execute(f'SELECT count(*) FROM public.{table}').fetchone()[0]==0
    db.execute('RESET ROLE')
    assert db.execute("SELECT has_table_privilege('authenticated','public.pr_research_requests','select')").fetchone()[0] is False
    # Deliberately changed ledger is refused without rewriting history.
    db.execute("UPDATE postriff_private.schema_migrations SET sha256='tampered' WHERE name=%s",(paths[-1].name,))
    try:plan(db)
    except ValueError:pass
    else:raise AssertionError('checksum drift accepted')
    db.execute('UPDATE postriff_private.schema_migrations SET sha256=%s WHERE name=%s',(hashlib.sha256(paths[-1].read_bytes()).hexdigest(),paths[-1].name))
    with tempfile.TemporaryDirectory(prefix='consumer-restore-') as tmp:
        dump=Path(tmp)/'backup.dump';start=time.monotonic()
        subprocess.run([str(PG/'pg_dump'),base,'-Fc','-f',str(dump)],check=True)
        backup_seconds=time.monotonic()-start; start=time.monotonic()
        target='host=127.0.0.1 port=55438 dbname=migration_restore'
        subprocess.run([str(PG/'pg_restore'),'-d',target,'--exit-on-error',str(dump)],check=True)
        restore_seconds=time.monotonic()-start
        with psycopg.connect(target,autocommit=True) as restored:
            assert before==restored.execute('SELECT id::text,state,revision FROM public.pr_workspaces').fetchall()
            assert all(r['status']=='APPLIED' for r in plan(restored))
            assert restored.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.pr_campaigns'::regclass").fetchone()[0]
        print(json.dumps({'status':'PASS','execution':'disposable PostgreSQL only','hostedMigrations':len(paths),'backupBytes':dump.stat().st_size,'backupSeconds':round(backup_seconds,3),'restoreSeconds':round(restore_seconds,3),'RPO':'0 for quiescent synthetic snapshot','productionRPO':'NOT_RUN','objectStorageRestore':'NOT_RUN'}))
# Fresh install from no PostRiff schema is independently exercised too.
with psycopg.connect(DSN,autocommit=True) as admin:admin.execute('CREATE DATABASE migration_fresh')
with psycopg.connect('host=127.0.0.1 port=55438 dbname=migration_fresh',autocommit=True) as fresh:
    fresh.execute(setup,prepare=False)
    assert all(r['status']=='PENDING' for r in apply(fresh))
    assert all(r['status']=='APPLIED' for r in plan(fresh))
print('PASS: fresh 001–019 excluding local-only 003; populated upgrade; ledger replay; checksum refusal; restore')
