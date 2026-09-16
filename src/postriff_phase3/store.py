"""Separate SQLite runtime state; existing founder and Phase 2 databases unchanged."""
import copy
import json
import time
from postriff_alpha.domain import AlphaError
from postriff_phase2.store import Phase2Store
from . import contracts as c

class Phase3Store(Phase2Store):
 def __init__(self,path,clock=time.time):
  super().__init__(path,clock)
  with self.connect() as db:
   db.execute('CREATE TABLE IF NOT EXISTS p3_runtime(workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE, state TEXT NOT NULL)')

 def load_runtime(self,db,wid):
  row=db.execute('SELECT state FROM p3_runtime WHERE workspace_id=?',(wid,)).fetchone()
  return json.loads(row['state']) if row else c.initial()

 def save_runtime(self,db,wid,data):
  db.execute('INSERT INTO p3_runtime VALUES (?,?) ON CONFLICT(workspace_id) DO UPDATE SET state=excluded.state',(wid,json.dumps(data)))

 def get(self,wid,token):
  result=super().get(wid,token)
  if wid not in self.samples:
   with self.connect() as db:
    data=self.load_runtime(db,wid);c.reconcile(data,self.clock())
    result['state']['phase3']=c.projection(data,self.clock())
  return result

 def mutate(self,wid,token,expected_revision,action,payload):
  if isinstance(action,str) and action.startswith('p3_'):
   return self.runtime_action(wid,token,expected_revision,action[3:],payload)
  result=super().mutate(wid,token,expected_revision,action,payload)
  if action=='p2_delete_account':
   with self.connect() as db: db.execute('DELETE FROM p3_runtime WHERE workspace_id=?',(wid,))
  elif wid not in self.samples: result=self.get(wid,token)
  return result

 def runtime_action(self,wid,token,revision,action,p,desktop=False):
  c.require(wid not in self.samples,'Runtime jobs require a signed-in local workspace.',403)
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');row=self._row(db,wid,token)
   c.require(type(revision) is int and revision==row['revision'],'Workspace changed. Reload; your unsent edits remain on this device.',409)
   member=db.execute("SELECT d.user_id,m.role FROM alpha_devices d JOIN alpha_memberships m ON m.workspace_id=d.workspace_id AND m.user_id=d.user_id WHERE d.workspace_id=? AND d.credential_hash=? AND d.status='active' AND m.status='active'",(wid,__import__('hashlib').sha256(token.encode()).hexdigest())).fetchone()
   c.require(member is not None and member["role"] in ("owner","editor"),"Read-only or revoked membership.",403)
   actor=member["user_id"]
   data=self.load_runtime(db,wid);s=json.loads(row['state'])
   extra=c.apply(s,data,actor,action,p,self.clock(),desktop) or {}
   self.invalidate(s)
   self.save_runtime(db,wid,data)
   db.execute('UPDATE workspaces SET revision=revision+1,state=? WHERE id=?',(json.dumps(s),wid))
   result=self._present(s,revision+1);result['state']['phase3']=c.projection(data,self.clock());result['runtimeResult']=extra
   return result

 def device(self,wid,device_id,credential,action,p):
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   data=self.load_runtime(db,wid)
   d=next((x for x in data['devices'] if x['id']==device_id),None)
   c.require(d is not None)
   member=db.execute("SELECT 1 FROM alpha_memberships WHERE workspace_id=? AND user_id=? AND status='active' AND role IN ('owner','editor')",(wid,d['actor'])).fetchone()
   c.require(member is not None)
   row=db.execute('SELECT state FROM workspaces WHERE id=?',(wid,)).fetchone();c.require(row is not None)
   result=c.device_action(json.loads(row['state']),data,device_id,credential,action,p,self.clock())
   self.save_runtime(db,wid,data)
   return result

 def fixture_step(self):
  """One bounded synthetic job; real routes never enter this worker."""
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   for row in db.execute('SELECT r.workspace_id,r.state,w.state AS workspace FROM p3_runtime r JOIN workspaces w ON w.id=r.workspace_id').fetchall():
    data=json.loads(row['state']);s=json.loads(row['workspace']);c.reconcile(data,self.clock())
    job=next((j for j in data['jobs'] if j['route']=='fixture' and j['deviceId'] is None and j['status'] in ('waiting','running')),None)
    if job:
     member=db.execute("SELECT 1 FROM alpha_memberships WHERE workspace_id=? AND user_id=? AND status='active' AND role IN ('owner','editor')",(row['workspace_id'],job['actor'])).fetchone()
     valid=bool(member)
     try: valid=valid and job['inputHash']==c.digest(c.snapshot(s,data,[x['id'] for x in job['manifest']['sources']],job['manifest']['operation']))
     except AlphaError: valid=False
     if not valid:job['status']='interrupted';c.event(job,'interrupted',self.clock(),'Source or membership changed; candidate retained.')
     elif job['status']=='waiting':
      job.update({'status':'running','leaseUntil':self.clock()+30,'attempt':c.uid()});c.event(job,'running',self.clock())
     elif not any(e['type']=='text' for e in job['events']):
      c.event(job,'text',self.clock(),'Synthetic preview is assembling two independent draft candidates.')
     elif job['manifest']['operation']=='profile':
      job['artifact']={'schema':'postriff.personal-voice.v1','fields':[{'key':'voiceTraits','value':'Clear and practical','evidence':'agent_proposed_needs_confirmation','privacy':'local_only','sourceIds':[x['id'] for x in job['manifest']['sources']],'confidence':'low','selfDescribed':False}]}
      job['artifactHash']=c.digest(job['artifact']);job['status']='completed';c.event(job,'completed',self.clock())
     else:
      from .adapters import FixtureRuntime
      job['artifact']=c.artifact(FixtureRuntime().generate(job['manifest']),job['manifest']);job['artifactHash']=c.digest(job['artifact']);job['usage']={'provenance':'measured_locally','modelRequests':0};job['status']='completed';c.event(job,'completed',self.clock())
    self.save_runtime(db,row['workspace_id'],data)

 def export(self,wid,token):
  import io,zipfile
  original=super().export(wid,token)
  if wid in self.samples:return original
  with self.connect() as db:
   self._row(db,wid,token);runtime=c.projection(self.load_runtime(db,wid),self.clock())
  archive=io.BytesIO(original)
  with zipfile.ZipFile(archive,'a',zipfile.ZIP_DEFLATED) as out:out.writestr('runtime-review.json',json.dumps(runtime,ensure_ascii=False,indent=2))
  return archive.getvalue()
