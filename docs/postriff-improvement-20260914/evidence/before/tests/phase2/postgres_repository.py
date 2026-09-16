"""Run after rls.sql against the disposable database. No hosted credentials."""
import json
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService, PostgresWorkspaceRepository
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_alpha.domain import Store, initial_state, AlphaError

DSN='host=127.0.0.1 port=55438 dbname=postgres'
one='00000000-0000-0000-0000-000000000001'
two='00000000-0000-0000-0000-000000000002'

def connection():return psycopg.connect(DSN,client_encoding='utf8')
def verify(token):
    if token not in ('fixture-one','fixture-two'):raise AlphaError('Verified session required',401)
    return one if token=='fixture-one' else two

# Pure Phase 1 command logic; no SQLite store is constructed or imported.
engine=Store.__new__(Store)
def commands(state,principal,action,payload):
    engine._apply(state,action,payload)
    return state
repo=PostgresWorkspaceRepository(connection,verify,commands)
with connection() as db:
    wid=str(db.execute('select workspace_id from public.pr_memberships where user_id=%s',(one,)).fetchone()[0])
    foreign=str(db.execute('select workspace_id from public.pr_memberships where user_id=%s',(two,)).fetchone()[0])
    db.execute('update public.pr_workspaces set state=%s::jsonb where id=%s',(json.dumps(initial_state(wid)),wid))
before=repo.get(wid,'fixture-one')
changed=repo.mutate(wid,'fixture-one',before['revision'],'mode',{'mode':'hybrid'})
assert changed['state']['brandHub']['mode']=='hybrid'
assert repo.get(wid,'fixture-one')['revision']==before['revision']+1
assert len(changed['state']['skillInstances'])==3
for call in (lambda:repo.get(foreign,'fixture-one'),lambda:repo.get(wid,'fixture-two'),lambda:repo.get(wid,'forged'),lambda:repo.mutate(wid,'fixture-one',before['revision'],'mode',{'mode':'business'})):
    try:call()
    except AlphaError:pass
    else:raise AssertionError('Isolation or stale revision was accepted')
def broken(state,principal):
    state['brandHub']['mode']='business'
    raise AlphaError('Injected failure')
try:repo.command(wid,'fixture-one',changed['revision'],broken)
except AlphaError:pass
assert repo.get(wid,'fixture-one')['state']['brandHub']['mode']=='hybrid'
with connection() as db:
    db.execute("update public.pr_memberships set role='viewer' where user_id=%s",(one,))
try:repo.mutate(wid,'fixture-one',changed['revision'],'mode',{'mode':'business'})
except AlphaError:pass
else:raise AssertionError('Viewer mutation accepted')
with connection() as db:db.execute("update public.pr_memberships set role='owner' where user_id=%s",(one,))

# Full hosted command composition and worker recovery, still with a zero-network adapter.
clock=[time.time()]
with connection() as db:db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s",(wid,))
service=HostedWorkspaceService(connection,verify,clock=lambda:clock[0])
snapshot=service.bootstrap('fixture-one','studio')
assert snapshot['state']['phase2']['execution']=='hosted-candidate'
def act(action,payload):
    global snapshot
    snapshot=service.mutate(wid,'fixture-one',snapshot['revision'],action,payload)
act('mode',{'mode':'personal'})
act('context',{'purpose':'Make community learning accessible','audience':'Curious beginners','subject':'Community workshops','speaker':'My voice','layers':[]})
act('source',{'kind':'sample'})
source=snapshot['state']['sources'][-1]
act('approve_source',{'sourceId':source['id'],'factIds':[fact['id'] for fact in source['facts']]})
act('source_done',{})
act('profile_propose',{'writing':'A small step can be a useful beginning.','tone':'warm'})
act('profile_decide',{'decision':'approve'})
act('runtime',{'selected':'deterministic-preview'})
act('generate',{'platform':'LinkedIn','language':'English'})
variant=snapshot['state']['variants'][0]
act('p2_variant_review',{'variantId':variant['id'],'variantRevision':variant['revision'],'confirmed':True,'excludedUnknowns':variant['unknowns']})
channel={'id':uuid.uuid4().hex,'platform':'LinkedIn','account':'Verified test member','accountType':'member','language':'English','scopes':['w_member_social'],'verifiedAt':clock[0],'expiresAt':clock[0]+86400,'capabilityVersion':1,'providerAccountId':'urn:li:person:test'}
saved=service.repository.command(wid,'fixture-one',snapshot['revision'],lambda state,actor:service.commands.upsert_verified_channel(state,actor,channel))
snapshot=service.commands.present(saved['state'],saved['revision'])
act('p2_review',{'channelId':channel['id'],'variantId':variant['id'],'localTime':datetime.fromtimestamp(clock[0]+60,timezone.utc).replace(tzinfo=None).isoformat(),'timeZone':'UTC','acknowledgedWarnings':variant['warnings']})
review=snapshot['state']['phase2']['reviews'][-1]
act('p2_approve',{'reviewId':review['id'],'digest':review['digest'],'confirmed':True})
assert snapshot['state']['phase2']['jobs'][0]['manifest']['execution']=='hosted-live'

class Social:
    def __init__(self):self.submits=0;self.reconciles=0
    def submit(self,manifest):
        self.submits+=1
        return {'state':'provider_accepted','confirmed':'Disposable adapter accepted','reference':'disposable-1'}
    def reconcile(self,manifest,job):
        self.reconciles+=1
        return {'state':'verified','confirmed':'Disposable lookup matched','verification':'disposable_lookup'}
social=Social();worker=PostgresWorker(connection,social=social,clock=lambda:clock[0],worker_id='disposable-worker')
clock[0]+=61
assert worker.step(crash='after_provider')
clock[0]+=46
assert worker.step()
finished=service.get(wid,'fixture-one')['state']['phase2']['jobs'][0]
assert finished['state']=='verified' and len(finished['attempts'])==1
assert social.submits==1 and social.reconciles==1

print(json.dumps({'status':'pass','driver':psycopg.__version__,'checks':['real PostgreSQL command persistence','existing alpha command reuse without SQLite','two-user membership denial','stale revision rejection','transaction rollback','viewer write denial','hosted bootstrap and full Phase 2 command composition','PostgreSQL worker lease recovery without duplicate submit'],'execution':'disposable-local-postgres'},indent=2))
