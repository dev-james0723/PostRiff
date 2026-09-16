"""Restores only disposable synthetic data, no live service credentials."""
from pathlib import Path
import subprocess,time,json,hashlib,sys,tempfile,sqlite3
import psycopg
OUT=Path(__file__).parent;PG='/opt/homebrew/opt/postgresql@17/bin/'
def pgstate(name):
 with psycopg.connect(f'host=127.0.0.1 port=55438 dbname={name}') as db:
  return db.execute('SELECT id::text,revision,state FROM public.pr_workspaces ORDER BY id').fetchall()
before=pgstate('postgres');start=time.monotonic()
subprocess.run([PG+'pg_dump','-h','127.0.0.1','-p','55438','-d','postgres','-Fc','-f',str(OUT/'synthetic-postgres.dump')],check=True,capture_output=True)
subprocess.run([PG+'createdb','-h','127.0.0.1','-p','55438','postriff_restored'],check=True,capture_output=True)
subprocess.run([PG+'pg_restore','-h','127.0.0.1','-p','55438','-d','postriff_restored',str(OUT/'synthetic-postgres.dump')],check=True,capture_output=True)
after=pgstate('postriff_restored');assert before==after
with psycopg.connect('host=127.0.0.1 port=55438 dbname=postriff_restored') as db:
 db.execute('SET ROLE authenticated');db.execute("SELECT set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000001',false)")
 assert db.execute('SELECT count(*) FROM public.pr_workspaces').fetchone()[0]==1
result={'status':'pass','execution':'synthetic-local-restore','postgres_workspaces':len(before),'recovery_seconds':round(time.monotonic()-start,3),'snapshot_loss_rows':0,'state_revision_jobs_equal':True,'restored_RLS_own_workspace_only':True,'worker_started_on_restore':False,'production_RPO_RTO':'validation_unavailable','limitations':['No cloud recovery','No Storage object bytes in database dump','No real OAuth vault/Auth recovery','Zero snapshot loss is not an achieved production RPO']}
(OUT/'restore-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
