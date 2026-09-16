"""Outbound scoped host loop; never exposes a listener or accepts shell commands."""
from .contracts import require
from .adapters import FixtureRuntime
class OutboundHost:
 def __init__(self,request):self.request=request
 def tick(self):
  self.request('heartbeat',{})
  jobs=self.request('discover',{})['jobs']
  for job in jobs:
   if job['status']!='waiting':continue # Running after reconnect is reconciliation, never restart.
   # No real provider execution is authorized by a pairing credential.
   if job['route']!='fixture':continue
   claim=self.request('claim',{'runId':job['id']})
   if not claim.get('start'):continue
   value=FixtureRuntime().generate(claim['input'])
   self.request('complete',{'runId':job['id'],'attempt':claim['attempt'],'artifact':value})
