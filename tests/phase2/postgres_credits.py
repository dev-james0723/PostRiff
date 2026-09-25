"""Opt-in credit ledger on disposable PostgreSQL only; all funding is synthetic."""
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.credit_meter import POLICY_VERSION
from consumer_fixtures import approve_budgets

DSN='host=127.0.0.1 port=55438 dbname=postgres'
ONE='00000000-0000-0000-0000-000000000001'
clock=[time.time()]
def connection(): return psycopg.connect(DSN,client_encoding='utf8')
def verify(token):
    if token!='one': raise AlphaError('No access',403)
    return ONE
verify.session_id=lambda token,principal:'credits-synthetic-session'
verify.auth_time=lambda token,principal:clock[0]
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2]/'migrations/postriff/020_credit_quotes.sql').read_text())
service=HostedWorkspaceService(connection,verify,clock=lambda:clock[0])
snap=service.bootstrap('one','studio');wid=snap['workspaceId']
ledger=Ledger(credits_enabled=True,clock=lambda:clock[0])
with connection() as db:
    cur=db.cursor();ledger.ensure_entitlement(cur,wid,None)
    assert ledger.credits.policy(cur,wid) is None
    ent={'writingBatches':10,'mediaCredits':1,'members':1,'connectedAccounts':3,'storageMb':200,'creditPolicy':POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('credits-test','studio',999,'Synthetic credits',0,'active',%s::jsonb)",(json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='credits-test' WHERE workspace_id=%s",(wid,))
    first=ledger.credits.grant(cur,wid,ONE,'funding-fixture',30000,clock[0]+60)
    assert ledger.credits.grant(cur,wid,ONE,'funding-fixture',30000,clock[0]+60)['duplicate']
approve_budgets(connection,wid)

def reserve(key, maximum=9000):
    with connection() as db:
        cur=db.cursor()
        q=ledger.credits.issue(cur,wid,ONE,snap['revision'],'a'*64,'fixture-model','fixture-provider',maximum)
        authority=ledger.credits.authorize(cur,wid,ONE,snap['revision'],'a'*64,q['quoteId'])
        r=ledger.reserve(cur,wid,ONE,'text_model',10000,key,charge_batch=True,provider='fixture-provider',model='fixture-model',credit_authority=authority)
        duplicate=ledger.reserve(cur,wid,ONE,'text_model',10000,key,charge_batch=True,provider='fixture-provider',model='fixture-model',credit_authority=authority)
        assert duplicate['duplicate']
        return r

r=reserve('use-first')
with connection() as db:
    cur=db.cursor();view=ledger.credits.view(cur,wid)
    assert (view['availableMilliCredits'],view['heldMilliCredits'])==(21000,9000),view
    ledger.settle(cur,wid,r['reservationId'],'completed',10000)
with connection() as db:
    cur=db.cursor();view=ledger.credits.view(cur,wid)
    assert (view['availableMilliCredits'],view['heldMilliCredits'],view['usedMilliCredits'])==(27000,0,3000),view
    assert ledger.settle(cur,wid,r['reservationId'],'completed',10000)['duplicate']
    assert ledger.ensure_entitlement(cur,wid,None)['writingBatchesRemaining']==10
unknown=reserve('unknown-task')
with connection() as db:
    ledger.settle(db.cursor(),wid,unknown['reservationId'],'unknown')
with connection() as db:
    assert ledger.credits.view(db.cursor(),wid)['heldMilliCredits']==9000
    ledger.settle(db.cursor(),wid,unknown['reservationId'],'failed',5000)
with connection() as db:
    assert ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==27000

def competing(index):
    try: return reserve('race-'+str(index),16000)
    except AlphaError as error:
        assert error.status==402,error
        return None
with ThreadPoolExecutor(max_workers=2) as pool: races=list(pool.map(competing,range(2)))
assert sum(r is not None for r in races)==1,races
with connection() as db:
    winner=next(r for r in races if r)
    ledger.settle(db.cursor(),wid,winner['reservationId'],'failed',0)
    cur=db.cursor();q=ledger.credits.issue(cur,wid,ONE,snap['revision'],'b'*64,'fixture-model','fixture-provider',9000)
    try: ledger.credits.authorize(cur,wid,ONE,snap['revision'],'c'*64,q['quoteId'])
    except AlphaError as error: assert error.status==409
    else: raise AssertionError('Changed payload accepted')
clock[0]+=61
with connection() as db:
    assert ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==0
    db.execute('SET LOCAL ROLE authenticated')
    try:
        with db.transaction(): db.execute('SELECT * FROM pr_credit_quotes')
    except psycopg.errors.InsufficientPrivilege: pass
    else: raise AssertionError('Raw quotes readable by client')
print('PASS: legacy isolation, funding replay, durable hold/settle, unknown, concurrency, request binding, expiry, permissions')

# Full hosted drafting with a synthetic paid transport: no external calls.
from postriff_phase2.model_runtime import ServerModelRuntime
calls=[]
def transport(method,url,headers=None,body=None):
    calls.append(body['model'])
    return {'status':200,'body':{'choices':[{'message':{'content':json.dumps({'variants':[{'platform':'LinkedIn','language':'en-US','text':'A small creative habit.','sourceIds':[]}]})}}],'usage':{'cost':0.01,'prompt_tokens':10,'completion_tokens':20}}}
runtime=ServerModelRuntime('synthetic-test-key',model='test/cloud',models=['test/cloud'],prices={'test/cloud':(1,1)},transport=transport)
service=HostedWorkspaceService(connection,verify,clock=lambda:clock[0],ideas_runtime=runtime,credits_enabled=True)
with connection() as db:
    service.ledger.credits.grant(db.cursor(),wid,ONE,'flow-funding',100000,None)
snap=service.get(wid,'one')
payload={'text':'A small creative habit.','ownContent':True,'confirmUse':True,'model':'test/cloud','reasoning':'quick','research':False,'timeZone':'UTC','destinations':[{'platform':'LinkedIn','language':'en-US'}]}
try: service.ideas.quick_start(wid,'one',snap['revision'],payload)
except AlphaError as error: assert error.status==402,error
else: raise AssertionError('Credit model ran without approval')
assert calls==[]
quote=service.ideas.credit_requests.issue(wid,'one',{'request':payload,'expectedRevision':snap['revision'],'maxMilliCredits':90000})
result=service.ideas.quick_start(wid,'one',snap['revision'],{**payload,'creditQuoteId':quote['quoteId']})
assert result['status']=='completed',result
assert calls==['test/cloud'],calls
with connection() as db:
    view=service.ledger.credits.view(db.cursor(),wid)
    assert view['availableMilliCredits']==97000,view
    assert view['heldMilliCredits']==0,view
assert service.usage(wid,'one')['credits']['availableMilliCredits']==97000
print('PASS: real Hosted service -> approved quote -> synthetic cloud -> durable credits settled once')

# A disabled feature must not switch a credit-plan user to an older allowance.
with connection() as db:
    try:
        Ledger().reserve(db.cursor(),wid,ONE,'text_model',1,'disabled-feature-check',charge_batch=True)
    except AlphaError as error:
        assert error.status==503,error
    else:
        raise AssertionError('Disabled credit plans must refuse new paid requests')

# Settlement must still work after pausing creation of new credit tasks.
paused_run=reserve('settle-after-pause')
with connection() as db:
    Ledger().settle(db.cursor(),wid,paused_run['reservationId'],'completed',10000)
with connection() as db:
    assert service.ledger.credits.view(db.cursor(),wid)['heldMilliCredits']==0

with connection() as db:
    cur=db.cursor()
    q=service.ledger.credits.issue(cur,wid,ONE,snap['revision'],'e'*64,'test/cloud',runtime.provider,10000)
    same_authority={'quoteId':q['quoteId'],'requestDigest':'e'*64}
def same_request(_):
    with connection() as db:
        return service.ledger.reserve(db.cursor(),wid,ONE,'text_model',10000,'parallel-same-request',charge_batch=True,provider=runtime.provider,model='test/cloud',credit_authority=same_authority)
with ThreadPoolExecutor(max_workers=8) as pool:
    repeated=list(pool.map(same_request,range(8)))
assert len({row['reservationId'] for row in repeated})==1
assert sum(not row['duplicate'] for row in repeated)==1
print('PASS: pausing does not prevent reconciliation; identical concurrent requests share one reservation')

# Regenerating the same brief preserves the existing source and requires a new credit approval.
with connection() as db:
    service.ledger.credits.grant(db.cursor(),wid,ONE,'regeneration-fixture-funding',200000,None)
existing_sources=len(service.get(wid,'one')['state']['sources'])
for index in range(2):
    latest=service.get(wid,'one')
    approval=service.ideas.credit_requests.issue(wid,'one',{'request':payload,'expectedRevision':latest['revision'],'maxMilliCredits':90000})
    regenerated=service.ideas.quick_start(wid,'one',latest['revision'],{**payload,'creditQuoteId':approval['quoteId']})
    assert regenerated['status']=='completed',regenerated
    assert len(service.get(wid,'one')['state']['sources'])==existing_sources
print('PASS: explicit regenerate reuses the source while every model run requires its own credit approval')

# The current brief is task input, not a permanent grant to stored sources.
seen=[]
previous_transport=runtime.transport
def capture_brief(*args, **kwargs):
    sent=json.loads(kwargs['body']['messages'][1]['content'].split('\n\n')[0])
    seen.append(sent)
    return previous_transport(*args, **kwargs)
runtime.transport=capture_brief
latest=service.get(wid,'one')
current_request={**payload,'text':'Tonight our class begins at 18:30 in Hall A.','ownContent':False}
approval=service.ideas.credit_requests.issue(wid,'one',{'request':current_request,'expectedRevision':latest['revision'],'maxMilliCredits':90000})
service.ideas.quick_start(wid,'one',latest['revision'],{**current_request,'creditQuoteId':approval['quoteId']})
assert seen[-1]['idea']==current_request['text'], 'The managed writer must receive the current brief, not a stale stored idea.'
assert seen[-1]['approvedFacts']==[], 'A current brief cannot grant access to stored unapproved sources.'
print('PASS: current brief reaches cloud drafting without granting stored-source access')
