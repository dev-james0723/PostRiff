"""Hosted runtime repository candidate. Uses existing verified membership transaction."""
import json
import time
from . import contracts as c
from postriff_phase2.hosted import PostgresWorkspaceRepository

class HostedRuntimeService:
 def __init__(self,connection_factory,verify_session,clock=time.time):
  self.repo=PostgresWorkspaceRepository(connection_factory,verify_session)
  self.factory=connection_factory;self.clock=clock
 @staticmethod
 def load(cur,wid):
  cur.execute('SELECT state FROM public.pr_runtime WHERE workspace_id=%s FOR UPDATE',(wid,));row=cur.fetchone()
  return (json.loads(row[0]) if isinstance(row[0],str) else row[0]) if row else c.initial()
 @staticmethod
 def save(cur,wid,data):cur.execute('INSERT INTO public.pr_runtime(workspace_id,state) VALUES (%s,%s::jsonb) ON CONFLICT(workspace_id) DO UPDATE SET state=excluded.state,updated_at=now()',(wid,json.dumps(data)))
 def get(self,wid,token):
  with self.repo.transaction(token,wid) as (cur,_,actor):
   data=self.load(cur,wid);c.reconcile(data,self.clock());return c.projection(data,self.clock())
 def mutate(self,wid,token,revision,action,payload,desktop=False):
  with self.repo.transaction(token,wid) as (cur,row,actor):
   c.require(row[2] in ('owner','editor'),'Read-only membership.',403)
   c.require(type(revision) is int and revision==row[0],'Workspace changed; preserve local edits and reload.',409)
   state=json.loads(row[1]) if isinstance(row[1],str) else row[1];data=self.load(cur,wid)
   # A trusted native confirmation verifier must set desktop; never accept a client boolean.
   result=c.apply(state,data,actor,action,payload,self.clock(),desktop)
   self.save(cur,wid,data)
   cur.execute('UPDATE public.pr_workspaces SET revision=revision+1,state=%s::jsonb WHERE id=%s',(json.dumps(state),wid))
   return {'revision':revision+1,'runtime':c.projection(data,self.clock()),'result':result}
 def device(self,wid,device_id,credential,action,payload):
  with self.factory() as db:
   with db.cursor() as cur:
    cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(wid,));row=cur.fetchone();c.require(row is not None)
    data=self.load(cur,wid);device=next((d for d in data['devices'] if d['id']==device_id),None);c.require(device is not None)
    cur.execute("SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND m.role IN ('owner','editor') AND p.deleted_at IS NULL",(wid,device['actor']));c.require(cur.fetchone() is not None)
    state=json.loads(row[0]) if isinstance(row[0],str) else row[0]
    result=c.device_action(state,data,device_id,credential,action,payload,self.clock());self.save(cur,wid,data);return result
