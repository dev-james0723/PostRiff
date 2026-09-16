"""Real local PostgreSQL validation of the candidate contract, synthetic rows only."""
from pathlib import Path
import tempfile,subprocess,socket,json,uuid,datetime
import psycopg
BASE=Path(__file__).parent; BIN=Path('/opt/homebrew/opt/postgresql@17/bin'); PORT=55449
checks=[]
def check(name,value):
 assert value,name
 checks.append(name)
def uid():return str(uuid.uuid4())
with socket.socket() as s:assert s.connect_ex(('127.0.0.1',PORT))!=0,'port occupied; do not touch existing service'
cluster=Path(tempfile.mkdtemp(prefix='postriff-analytics-spec-pg-')); started=False
try:
 init=subprocess.run([str(BIN/'initdb'),'-D',str(cluster),'-A','trust','--no-locale','-E','UTF8'],capture_output=True,text=True);assert init.returncode==0,init.stderr
 start=subprocess.run([str(BIN/'pg_ctl'),'-D',str(cluster),'-l',str(cluster/'server.log'),'-o',f'-p {PORT} -h 127.0.0.1','-w','start'],capture_output=True,text=True);assert start.returncode==0,start.stderr;started=True
 with psycopg.connect(f'host=127.0.0.1 port={PORT} dbname=postgres',autocommit=True) as db:
  db.execute("create role authenticated nologin; create schema auth; create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$; grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;")
  db.execute("create table public.pr_profiles(user_id uuid primary key,deleted_at timestamptz); create table public.pr_workspaces(id uuid primary key); create table public.pr_memberships(workspace_id uuid references public.pr_workspaces,id_dummy text,user_id uuid references public.pr_profiles,role text,status text,primary key(workspace_id,user_id));")
  db.execute((BASE/'contracts/analytics-candidate.sql').read_text());check('candidate DDL applied to disposable PostgreSQL 17',True)
  w1,w2,a1,a2,u1,u2,admin=[uid() for _ in range(7)]
  for u in [u1,u2,admin]:db.execute('insert into public.pr_profiles values(%s,null)',(u,))
  for w in [w1,w2]:db.execute('insert into public.pr_workspaces values(%s)',(w,))
  for w,u in [(w1,u1),(w2,u2)]:db.execute("insert into public.pr_memberships(workspace_id,user_id,role,status) values(%s,%s,'owner','active')",(w,u))
  for w,a,u in [(w1,a1,u1),(w2,a2,u2)]:
   db.execute("insert into pr_analytics.accounts values(%s,%s,'youtube',%s,1,'active')",(w,a,'synthetic-'+a))
   db.execute("insert into pr_analytics.account_grants values(%s,%s,%s,1,true,false,now()+interval '1 hour')",(w,a,u))
  db.execute("insert into pr_analytics.admin_memberships values(%s,'platform_owner','active',1)",(admin,))
  def denied(name,sql,args=()):
   try:db.execute(sql,args)
   except psycopg.Error:check(name,True)
   else:raise AssertionError(name)
  denied('foreign workspace account tuple rejected',"insert into pr_analytics.posts values(%s,%s,%s,'x',now(),'native_imported')",(w1,a2,uid()))
  point,fetch=[uid() for _ in range(2)]
  db.execute("insert into pr_analytics.metric_points values(%s,%s,%s,'channel','youtube.views',1,'period','2026-09-01/08',%s,'provider_api','synthetic')",(point,w1,a1,'0'*64))
  denied('duplicate canonical metric point rejected',"insert into pr_analytics.metric_points select %s,workspace_id,account_id,object_key,metric_key,metric_version,grain,period_key,dimensions_hash,source_kind,execution from pr_analytics.metric_points where id=%s",(uid(),point))
  ins="insert into pr_analytics.metric_revisions values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'synthetic-only')"
  ts='2026-09-09T12:00:00Z'
  db.execute(ins,(uid(),w1,a1,point,fetch,0,'measured',ts,None,None));check('measured zero retained',db.execute('select value from pr_analytics.metric_revisions').fetchone()[0]==0)
  denied('missing status cannot carry invented zero',ins,(uid(),w1,a1,point,uid(),0,'scope_missing',ts,None,None))
  denied('measured status cannot omit value',ins,(uid(),w1,a1,point,uid(),None,'measured',ts,None,None))
  denied('invalid reversed period rejected',ins,(uid(),w1,a1,point,uid(),1,'measured',ts,'2026-09-10','2026-09-01'))
  denied('NaN metric value rejected',ins,(uid(),w1,a1,point,uid(),'NaN','measured',ts,None,None))
  denied('duplicate fetch cannot duplicate observation',ins,(uid(),w1,a1,point,fetch,0,'measured',ts,None,None))
  denied('revision cannot cross account tuple',ins,(uid(),w2,a2,point,uid(),1,'measured',ts,None,None))
  db.execute(ins,(uid(),w1,a1,point,uid(),100,'measured','2026-09-10T12:00:00Z',None,None))
  db.execute(ins,(uid(),w1,a1,point,uid(),9,'measured','2026-09-08T12:00:00Z',None,None))
  check('late older response cannot win latest view',db.execute('select value from pr_analytics.current_metrics').fetchone()[0]==100)
  def actor(u):
   db.execute('reset role');db.execute("select set_config('request.jwt.claim.sub',%s,false)",(u,));db.execute('set role authenticated')
  actor(u1);check('own granted account visible',db.execute('select count(*) from pr_analytics.accounts').fetchone()[0]==1)
  check('other tenant account invisible',db.execute('select count(*) from pr_analytics.accounts where workspace_id=%s',(w2,)).fetchone()[0]==0)
  denied('browser cannot write metric rows','delete from pr_analytics.metric_revisions')
  denied('browser cannot read admin membership table','select * from pr_analytics.admin_memberships')
  actor(u2);check('other tenant cannot read revisions or invoker view',db.execute('select count(*) from pr_analytics.current_metrics').fetchone()[0]==0)
  actor(admin);check('platform owner is not automatic social grant',db.execute('select count(*) from pr_analytics.accounts').fetchone()[0]==0)
  db.execute('reset role');db.execute('update pr_analytics.accounts set consent_epoch=2 where id=%s',(a1,));actor(u1)
  check('stale consent grant loses access immediately',db.execute('select count(*) from pr_analytics.accounts').fetchone()[0]==0)
  db.execute('reset role');db.execute('update pr_analytics.accounts set consent_epoch=1 where id=%s',(a1,));db.execute('update public.pr_profiles set deleted_at=now() where user_id=%s',(u1,));actor(u1)
  check('deleted profile loses analytics access',db.execute('select count(*) from pr_analytics.accounts').fetchone()[0]==0)
  db.execute('reset role');op=uid();ev=uid();args=(ev,w1,op,'draft.saved',1,'synthetic','0'*64,ts)
  db.execute('insert into pr_analytics.event_outbox values(%s,%s,%s,%s,%s,%s,%s,%s)',args)
  denied('event semantic duplicate rejected','insert into pr_analytics.event_outbox values(%s,%s,%s,%s,%s,%s,%s,%s)',(uid(),*args[1:]))
 result={'status':'pass','execution':'disposable-local-postgres-with-synthetic-auth-stub','checks':checks,'test_count':len(checks),'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'limitations':['Not a production migration','Auth stub is only for RLS contract testing, not real JWT verification','Budget, worker, billing and provider API acceptance tests remain implementation work']}
 (BASE/'evidence/sql-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
 if started:
  r=subprocess.run([str(BIN/'pg_ctl'),'-D',str(cluster),'-m','fast','-w','stop'],capture_output=True,text=True)
  with socket.socket() as s:closed=s.connect_ex(('127.0.0.1',PORT))!=0
  (BASE/'evidence/sql-cleanup.json').write_text(json.dumps({'stopped':r.returncode==0,'portClosed':closed,'port':PORT,'cluster':str(cluster),'syntheticOnly':True},indent=2))
