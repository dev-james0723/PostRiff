#!/usr/bin/env python3
"""Finite local stdio MCP integration. No tools execute on import or startup."""
import json
import os
import re
import sys
from urllib.request import Request,urlopen
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_phase3.integration import TOOLS

def serve(source=sys.stdin,sink=sys.stdout):
 wid=os.environ.get('POSTRIFF_TOOL_WORKSPACE','');device=os.environ.get('POSTRIFF_TOOL_DEVICE','');run=os.environ.get('POSTRIFF_TOOL_RUN','');token=os.environ.get('POSTRIFF_TOOL_DEVICE_CREDENTIAL','')
 attempt=None
 def call(action,payload):
  if not all(re.fullmatch(r'[a-f0-9]{32}',v) for v in (wid,device,run)) or not re.fullmatch(r'[A-Za-z0-9_-]{32,200}',token):raise ValueError('A host-provided scoped device identity and run are required.')
  request=Request('http://127.0.0.1:4330/api/device/action',method='POST',data=json.dumps({'workspaceId':wid,'deviceId':device,'action':action,'payload':{'runId':run,**payload}}).encode(),headers={'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha','Authorization':'Bearer '+token})
  with urlopen(request,timeout=10) as response:return json.loads(response.read(262144))
 while True:
  line=source.readline(65537)
  if not line:break
  message={}
  try:
   if len(line)>65536:raise ValueError('Request too large.')
   message=json.loads(line)
   if not isinstance(message,dict):message={};raise ValueError('Expected an object.')
   method=message.get('method')
   if method=='notifications/initialized':continue
   if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'postriff-candidate-tools','version':'0.3.0'}}
   elif method=='tools/list':result={'tools':[{'name':name,'description':'Scoped candidate-only PostRiff operation. No publishing authority.','inputSchema':{'type':'object','properties':{'variants':{'type':'array'}} if name=='submit_candidate' else {},'additionalProperties':False}} for name in TOOLS]}
   elif method=='tools/call':
    params=message.get('params',{});name=params.get('name');arguments=params.get('arguments',{})
    if name=='read_selected_context':
     value=call('claim',{});attempt=value.get('attempt',attempt)
    elif name=='submit_candidate':
     if not attempt:raise ValueError('Read selected context before submitting a candidate.')
     value=call('complete',{'attempt':attempt,'artifact':arguments})
    elif name=='review_link':call('events',{'cursor':0});value={'reviewPath':'/#runtime-'+run,'status':'candidate-only'}
    else:raise ValueError('Unsupported tool.')
    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
   else:raise ValueError('Unsupported MCP method.')
   reply={'jsonrpc':'2.0','id':message.get('id'),'result':result}
  except Exception:reply={'jsonrpc':'2.0','id':message.get('id'),'error':{'code':-32602,'message':'Scoped operation unavailable. Review identity, source approval, lease and run state in PostRiff.'}}
  sink.write(json.dumps(reply,ensure_ascii=False)+'\n');sink.flush()
if __name__=='__main__':serve()
