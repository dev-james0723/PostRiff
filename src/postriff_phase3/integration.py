"""Minimal external-agent surface: selected context and candidate submission only.

The caller provides a scoped paired device credential. No account mutation,
approval, publishing, shell, filesystem, global skills or URL-opening tool exists.
"""
from .contracts import require
TOOLS=('read_selected_context','submit_candidate','review_link')
class AgentIntegration:
 def __init__(self,service,workspace_id,device_id,credential,run_id,attempt):
  self.service=service;self.wid=workspace_id;self.device=device_id;self.secret=credential;self.run=run_id;self.attempt=attempt
 def call(self,name,payload):
  require(name in TOOLS,'Unsupported integration tool.',403)
  require(isinstance(payload,dict),'Expected a structured tool request.',400)
  if name=='read_selected_context':
   # Context requires the same authenticated, non-replayed claim contract.
   return self.service.device(self.wid,self.device,self.secret,'claim',{'runId':self.run})
  if name=='submit_candidate':
   return self.service.device(self.wid,self.device,self.secret,'complete',{'runId':self.run,'attempt':self.attempt,'artifact':payload})
  self.service.device(self.wid,self.device,self.secret,'events',{'runId':self.run,'cursor':0})
  return {'reviewPath':'/#runtime-'+self.run,'approval':'candidate-only','opensAutomatically':False}
