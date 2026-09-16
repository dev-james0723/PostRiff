"""Durable externally authorized worker. Not started by the local fixture launcher.

The operator must supply an exact reviewed ExecutionPermit and a configured
adapter. No renderer field or installed/authenticated CLI supplies this permit.
"""
import json
from . import contracts as c

class AuthorizedWorker:
 def __init__(self,store,adapter):self.store=store;self.adapter=adapter
 def execute(self,wid,token,run_id,permit):
  from .adapters import ExecutionPermit
  c.require(isinstance(permit,ExecutionPermit),'Execution permit required.',403)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');row=self.store._row(db,wid,token)
   state=json.loads(row['state']);data=self.store.load_runtime(db,wid);job=c.item(data['jobs'],run_id)
   import hashlib
   member=db.execute("SELECT d.user_id,m.role FROM alpha_devices d JOIN alpha_memberships m ON m.workspace_id=d.workspace_id AND m.user_id=d.user_id WHERE d.workspace_id=? AND d.credential_hash=? AND d.status='active' AND m.status='active'",(wid,hashlib.sha256(token.encode()).hexdigest())).fetchone()
   c.require(member and member['role'] in ('owner','editor') and member['user_id']==job['actor'] and job['deviceId'] is None,'Run authority unavailable.',403)
   c.require(job['status']=='prepared' and job['route']==permit.route and permit.input_hash==job['inputHash'] and permit.expires_at>self.store.clock(),'Run already started, changed or authorization expired. Reconcile before retry.',409)
   m=job['manifest'];c.require(job['inputHash']==c.digest(c.snapshot(state,data,[s['id'] for s in m['sources']],m['operation'],job['route']=='managed')),'Source snapshot changed.',409)
   trial=state['phase2']['trial']
   reservations=sum(j['route']=='managed' and j['status']=='running' for j in data['jobs'])
   c.require(trial['expiresAt']>self.store.clock() and trial['writingUsed']+reservations<trial['writingGrant'],'Writing allowance unavailable.',409)
   job.update({'status':'running','attempt':c.uid(),'leaseUntil':self.store.clock()+60,'authorization':{'model':permit.model,'maxCostUsd':permit.max_cost_usd,'qualification':permit.qualification_id}});attempt=job['attempt'];c.event(job,'running',self.store.clock());self.store.save_runtime(db,wid,data)
  def emit(e):
   if e.get('type')!='text':return
   with self.store.connect() as db:
    db.execute('BEGIN IMMEDIATE');data=self.store.load_runtime(db,wid);current=c.item(data['jobs'],run_id)
    if current['status']=='running' and current['attempt']==attempt:c.event(current,'text',self.store.clock(),e.get('text',''));self.store.save_runtime(db,wid,data)
  result=None;failed=False
  try:result=self.adapter.start(m,permit,emit)
  except Exception:failed=True
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');row=self.store._row(db,wid,token);state=json.loads(row['state']);data=self.store.load_runtime(db,wid);job=c.item(data['jobs'],run_id)
   # Preserve provider-incurred cost separately even when result cannot be accepted.
   job['providerCost']={'provenance':'Unavailable','maxAuthorizedUsd':permit.max_cost_usd}
   if result and isinstance(result,dict) and 'usage' in result:job['usage']=result['usage']
   valid=job['status']=='running' and job['attempt']==attempt and job['expiresAt']>self.store.clock() and job['leaseUntil']>self.store.clock()
   try:valid=valid and job['inputHash']==c.digest(c.snapshot(state,data,[s['id'] for s in m['sources']],m['operation'],job['route']=='managed'))
   except Exception:valid=False
   if valid and not failed and result and result.get('artifact'):
    job['artifact']=c.artifact(result['artifact'],m);job['artifactHash']=c.digest(job['artifact']);job['status']='completed'
    if job['route']=='managed' and not job['allowanceCharged']:
     state['phase2']['trial']['writingUsed']+=1;job['allowanceCharged']=True
     db.execute('UPDATE workspaces SET revision=revision+1,state=? WHERE id=?',(json.dumps(state),wid))
    c.event(job,'completed',self.store.clock())
   elif job['status']=='running':job['status']='interrupted';c.event(job,'interrupted',self.store.clock(),'No accepted result. Provider cost may exist; reconcile before another request.')
   self.store.save_runtime(db,wid,data)
   return {'status':job['status'],'usage':job['usage'],'allowanceCharged':job['allowanceCharged']}
