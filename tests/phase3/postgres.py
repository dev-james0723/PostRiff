"""Disposable PostgreSQL only; never reads application environment credentials."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import psycopg
from postriff_phase3.hosted import HostedRuntimeService
from postriff_alpha.domain import initial_state,AlphaError
root=Path(__file__).resolve().parents[2]
pg=Path('/opt/homebrew/opt/postgresql@17/bin')
with tempfile.TemporaryDirectory(prefix='postriff-p3-pg-') as tmp:
 data=Path(tmp)/'data';sock=Path(tmp)/'socket';sock.mkdir()
 subprocess.run([str(pg/'initdb'),'-D',str(data),'-A','trust','--no-locale'],check=True,stdout=subprocess.DEVNULL)
 subprocess.run([str(pg/'pg_ctl'),'-D',str(data),'-l',str(Path(tmp)/'postgres.log'),'-o',f'-k {sock} -p 55439 -h ""','-w','start'],check=True,stdout=subprocess.DEVNULL)
 try:
  dsn=f'host={sock} port=55439 dbname=postgres'
  subprocess.run([str(pg/'psql'),dsn,'-f',str(root/'tests/phase2/rls.sql')],check=True,stdout=subprocess.DEVNULL)
  subprocess.run([str(pg/'psql'),dsn,'-v','ON_ERROR_STOP=1','-f',str(root/'migrations/postriff/003_phase3_runtime.sql')],check=True,stdout=subprocess.DEVNULL)
  connection=lambda:psycopg.connect(dsn,client_encoding="utf8")
  one='00000000-0000-0000-0000-000000000001';two='00000000-0000-0000-0000-000000000002'
  def verify(token):
   if token not in ('one','two'):raise AlphaError('Session unavailable.',401)
   return one if token=='one' else two
  with connection() as db:
   db.execute("update public.pr_memberships set status='active',role='owner'")
   wid=str(db.execute('select workspace_id from public.pr_memberships where user_id=%s',(one,)).fetchone()[0]);foreign=str(db.execute('select workspace_id from public.pr_memberships where user_id=%s',(two,)).fetchone()[0])
   db.execute('update public.pr_workspaces set state=%s::jsonb where id=%s',(json.dumps(initial_state(wid)),wid))
   revision=db.execute('select revision from public.pr_workspaces where id=%s',(wid,)).fetchone()[0]
  service=HostedRuntimeService(connection,verify)
  r=service.mutate(wid,'one',revision,'enroll',{'name':'PG desktop'})
  e=r['result']['enrollment'];r=service.mutate(wid,'one',r['revision'],'pair',{'enrollmentId':e['id'],'code':e['code'],'confirmedWorkspace':wid,'confirmedName':e['name']},desktop=True)
  device=r['result'];assert service.device(wid,device['deviceId'],device['deviceCredential'],'heartbeat',{})['status']=='online'
  assert device['deviceCredential'] not in json.dumps(service.get(wid,'one'))
  for call in [lambda:service.get(foreign,'one'),lambda:service.mutate(wid,'two',r['revision'],'select',{'route':'fixture'}),lambda:service.device(foreign,device['deviceId'],device['deviceCredential'],'heartbeat',{}),lambda:service.mutate(wid,'one',revision,'select',{'route':'fixture'})]:
   try:call()
   except AlphaError:pass
   else:raise AssertionError('Tenant/revision check failed')
  with connection() as db:
   db.execute("set role authenticated")
   db.execute("select set_config('request.jwt.claim.sub',%s,false)",(one,))
   try:db.execute('select * from public.pr_runtime')
   except psycopg.errors.InsufficientPrivilege:db.rollback()
   else:raise AssertionError('Browser can read credential hashes')
  with connection() as db:db.execute("update public.pr_memberships set status='revoked' where user_id=%s",(one,))
  try:service.device(wid,device['deviceId'],device['deviceCredential'],'heartbeat',{})
  except AlphaError:pass
  else:raise AssertionError('Revoked membership can act')
  print(json.dumps({'status':'pass','execution':'disposable-local-postgresql','pairing':'single-use','isolation':'two users/workspaces','directBrowserRead':'denied','membershipRevocation':'denied','hostedAcceptance':False}))
 finally:subprocess.run([str(pg/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'],check=True,stdout=subprocess.DEVNULL)
