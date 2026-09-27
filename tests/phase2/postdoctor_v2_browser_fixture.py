"""Seed only the disposable Post Doctor v2 browser harness. All publications/metrics here are fixtures."""
import json
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.contracts import digest
from postriff_phase2.growth.performance import on_verified

kind,port,principal,wid=sys.argv[1:5]
assert port=='55797','Only the Post Doctor v2 disposable harness port is permitted'
uuid.UUID(principal);uuid.UUID(wid)
def connection():return psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres')
host=HostedWorkspaceService(connection,lambda token:principal)
saved=host.repository.get(wid,'fixture')
def command(state,actor):
    if kind=='draft':
        state['variants']=[{'id':'growth-browser-draft','text':'One idea. Another idea!','platform':'Threads','language':'en','revision':1,
                            'sourceIds':[],'revisions':[],'warnings':[],'unknowns':[],'needsReview':True,'voiceRevision':None,'blockedByRetraction':False}]
    elif kind=='feedback':
        v=state['variants'][0];now=time.time();conn='growth-browser-account'
        state['phase2']['channels']=[{'id':conn,'platform':'Threads','account':'Fixture account','accountType':'profile','scopes':['threads_basic','threads_manage_insights'],
                                      'verifiedAt':now,'expiresAt':now+86400,'capabilityVersion':1,'configured':True,'evidenceSource':'synthetic','revoked':False,
                                      'identityVerified':True,'capabilityVerified':True}]
        jobs=[]
        for i in range(4):
            manifest={'channelId':conn,'platform':'Threads','account':'Fixture account','variantId':v['id'],'contentRevision':v['revision'],
                      'payload':{'text':v['text'],'language':v['language']},'payloadDigest':digest(v['text']),
                      'contentType':{'formatId':'text'},'timing':{'timestamp':now-86400,'timeZone':'UTC'},
                      'execution':'synthetic','idempotencyKey':digest(str(i))}
            if i==3:manifest['postDoctor']=v.get('postDoctor',{})
            jobs.append({'id':str(uuid.uuid4()),'state':'verified','stateReason':'Fixture verification only','providerReference':'fixture-post-'+str(i),
                         'verification':{'at':now,'method':'fixture_lookup'},'manifest':manifest,'events':[],'attempts':[]})
        state['phase2']['jobs']=jobs
    else:raise ValueError('Unknown fixture')
    return state
result=host.repository.command(wid,'fixture',saved['revision'],command)
if kind=='feedback':
    with connection() as db,db.cursor() as cur:
        cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'growth-browser-account','analytics','Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'",(wid,))
        for i,job in enumerate(result['state']['phase2']['jobs']):
            on_verified(cur,wid,job)
            cur.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,read_offset) VALUES(%s,'growth-browser-account','threads',%s,%s,'likes','fixture-native-v1',%s,'count','available',now(),'24h')",(wid,job['providerReference'],job['id'],[5,10,15,30][i]))
    print(json.dumps({'jobId':result['state']['phase2']['jobs'][-1]['id']}))
else:print(json.dumps({'variantId':'growth-browser-draft'}))
