"""Run after postgres_repository.py, against its disposable loopback fixtures only."""
import copy,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import psycopg
from postriff_phase2.hosted_worker import PostgresWorker
DSN='host=127.0.0.1 port=55438 dbname=postgres'
def connection(): return psycopg.connect(DSN)
with connection() as db:
 wid,base=db.execute("SELECT id::text,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchone()
actor=base['phase2']['jobs'][0]['approvedBy'];clock=[time.time()+120]
class Broken:
 def __init__(self): self.submits=0
 def submit(self,*_):self.submits+=1;return {'state':'uncertain','confirmed':'Ambiguous fixture'}
 def reconcile(self,*_):return {'state':'scheduled','confirmed':'Unsafe retry suggestion'}
def reset():
 s=copy.deepcopy(base);job=s['phase2']['jobs'][0]
 job.update(state='scheduled',attempts=[],checks=0,nextAt=0,leaseUntil=0,leaseOwner=None,cancelRequested=False)
 with connection() as db:
  db.execute("UPDATE public.pr_workspaces SET state=%s WHERE id=%s",(json.dumps(s),wid))
  db.execute("UPDATE public.pr_memberships SET status='active',role='owner' WHERE user_id=%s",(actor,))
def job():
 with connection() as db:return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]['phase2']['jobs'][0]
checks=[]
reset();social=Broken();worker=PostgresWorker(connection,social=social,clock=lambda:clock[0])
for _ in range(4):worker.step();clock[0]+=61
assert social.submits==1 and job()['state']=='uncertain';checks.append('unknown reconciliation cannot requeue submission')
reset()
with connection() as db:db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE user_id=%s",(actor,))
worker.step();assert job()['state']=='held' and not job()['attempts'];checks.append('revoked approver blocked at durable claim')
reset()
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE user_id=%s",(actor,))
worker.step();assert job()['state']=='held';checks.append('read-only approver blocked at durable claim')
reset()
claimed=worker.claim()
with connection() as db:
 s=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
 s['phase2']['jobs'][0].update(cancelRequested=True,state='uncertain')
 db.execute('UPDATE public.pr_workspaces SET state=%s WHERE id=%s',(json.dumps(s),wid))
worker.complete(claimed,{'state':'scheduled','confirmed':'Rejected before acceptance'})
assert job()['state']=='canceled';checks.append('cancel and rate-limit completion race')
reset();claimed=worker.claim();worker.complete(claimed,{'state':'verified','confirmed':'Missing verification reference'})
assert job()['state']=='uncertain';checks.append('incomplete publication evidence rejected')
print(json.dumps({'status':'pass','execution':'disposable-local-postgres','checks':checks},indent=2))
