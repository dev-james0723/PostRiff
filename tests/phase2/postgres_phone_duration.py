"""Clock-advanced one-hour phone funding and signed handoff. Real DB, zero external calls."""
from local_pg_target import selected_target
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.agent_runtime_v2 import config
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.phone import billing, contracts, resume, store
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
from consumer_fixtures import approve_budgets
import sys
sys.path.insert(0,'scripts')
from launch_credit_fixture import configure

DSN=selected_target(require_dsn=True).dsn()
# PostgreSQL timestamps have microsecond precision. Use exact whole seconds so
# the 50/60/3600s boundary assertions cannot drift just below a threshold after
# a float timestamp is rounded by the database.
now=[int(time.time())]
user=str(uuid.uuid4())
def connection(): return psycopg.connect(DSN)
def verify(token):
    if token!=user: raise AlphaError('Denied',403)
    return user
verify.auth_time=lambda *_:now[0]
verify.session_id=lambda *_:'local-duration-session'
service=HostedWorkspaceService(connection,verify,vault=CredentialVault(CredentialVault.generate_key()),clock=lambda:now[0])
with connection() as db: db.execute('INSERT INTO auth.users VALUES(%s)',(user,))
configure(service,connection)
wid=service.bootstrap(user,'studio')['workspaceId']
approve_budgets(connection,wid)
cfg=config.RuntimeConfig.from_environment({'OPENAI_API_KEY':'synthetic','RAFII_AGENT_V2_ENABLED':'1','RAFII_VOICE_ENABLED':'1'})
runtime=AgentRuntimeService(service,cfg,clock=lambda:now[0])
provider=FakeTelephonyProvider()
phone=PhoneService(service,{**{k:'1' for k in contracts.FLAGS},'RAFII_PHONE_MAX_SECONDS':'60','RAFII_PHONE_USD_MICRO_PER_MINUTE':'10000'},provider=provider,runtime=runtime)
phone.start_verification(wid,user,{'number':'+12025550123'})
phone.confirm_verification(wid,user,{'code':'123456'})
phone.save_preferences(wid,user,{'enabled':True})
def sql(q,*a):
    with connection() as db:
        c=db.execute(q,a)
        return c.fetchall() if c.description else []
def read(cid):
    with connection() as db:return store.call(db.cursor(),cid)
def denied(fn):
    try:fn()
    except AlphaError:return
    raise AssertionError('Unexpected authorization')
def begin(key,**payload):
    v=phone.request(wid,user,{'idempotencyKey':key,**payload})
    sql("UPDATE pr_phone_calls SET state='live',answered_at=to_timestamp(%s),media_claimed_at=to_timestamp(%s) WHERE id=%s",now[0],now[0],v['id'])
    return v['id']

# The first minute is affordable, the next is not. Pending holds from this call count.
cid=begin('balance-exhaustion',useAvailableCredits=True)
assert read(cid)['max_seconds']==3600 and read(cid)['funded_seconds']==60
start=now[0]
now[0]=start+50
denied(lambda:billing.renew(phone,cid))
assert read(cid)['funded_seconds']==60
assert sql("SELECT count(*) FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(2,)]
now[0]=start+60
scoped,cap,_=phone.scoped_runtime(cid)
denied(lambda:scoped.service.get(wid,cap))
phone.finish(cid,'completed',60,live_seconds=60)
with connection() as db:
    wallet=service.ledger.credits.view(db.cursor(),wid)
assert wallet['heldMilliCredits']==0 and wallet['usedMilliCredits']<=50000,wallet

# Developer uses no credit limit or grants even with the exhausted credit wallet.
os.environ['RAFII_AI_UNLIMITED_USER_IDS'] = user
before_developer = wallet.copy()
from unittest.mock import patch
from postriff_phase2.phone import inbound
phone.provider.originating_number = '+12025550100'
with patch.object(inbound, 'require_available'):
    ticket = inbound.issue(phone, wid, user, {})
assert len(ticket['code']) == 12
cid=begin('developer-no-credit-limit')
start=now[0]
now[0]=start+50
billing.renew(phone,cid)
assert read(cid)['funded_seconds']==120
phone.finish(cid,'completed',65,live_seconds=65)
with connection() as db:
    after_developer=service.ledger.credits.view(db.cursor(),wid)
assert after_developer['usedMilliCredits']==before_developer['usedMilliCredits']
assert after_developer['heldMilliCredits']==0
assert sql("SELECT count(*) FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND meta ? 'credits'",cid)==[(0,)]
os.environ.pop('RAFII_AI_UNLIMITED_USER_IDS')

# A funded call crosses both former 60s/600s cutoffs, without reserving an hour up front.
with connection() as db:service.ledger.credits.grant(db.cursor(),wid,user,'duration-grant',2_000_000,source='synthetic-only')
cid=begin('full-hour-credits',useAvailableCredits=True)
start=now[0]
scoped,cap,_=phone.scoped_runtime(cid)
now[0]=start+50
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:billing.renew(phone,cid),range(2)))
assert read(cid)['funded_seconds']==120
assert sql("SELECT count(*) FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(4,)]
for seconds in range(110,3600,60):
    now[0]=start+seconds
    billing.renew(phone,cid)
    scoped.service.get(wid,cap)
assert read(cid)['funded_seconds']==3600
now[0]=start+3599
scoped.service.get(wid,cap)
now[0]=start+3600
denied(lambda:scoped.service.get(wid,cap))
phone.finish(cid,'completed',3600,live_seconds=3600)
with connection() as db: wallet=service.ledger.credits.view(db.cursor(),wid)
assert wallet['heldMilliCredits']==0,wallet
before=wallet['usedMilliCredits']
phone.finish(cid,'completed',3600,live_seconds=3600)
with connection() as db:assert service.ledger.credits.view(db.cursor(),wid)['usedMilliCredits']==before
assert sql("SELECT count(*) FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(120,)]

# Only an intentional handoff can resume. Old capability is fenced; no new call or consent replay.
now[0]+=1
cid=begin('handoff-binding',useAvailableCredits=True)
old,oldcap,_=phone.scoped_runtime(cid)
ref=read(cid)['provider_call_ref']
from postriff_phase2.phone.providers.dial import DialProvider
provider.local_call_id=DialProvider({}).local_call_id
sql("UPDATE pr_phone_calls SET provider='dial' WHERE id=%s",cid)
meta={'direction':'outbound','to':'+12025550123','instruction':DialProvider.instruction(cid)}
denied(lambda:resume.claim(phone,ref,meta))
resume.prepare(phone,cid,0,20)
denied(lambda:old.service.get(wid,oldcap))
with ThreadPoolExecutor(max_workers=2) as pool:
    def claim(_):
        try:return resume.claim(phone,ref,meta)
        except AlphaError:return None
    claims=list(pool.map(claim,range(2)))
assert claims.count(cid)==1 and claims.count(None)==1,claims
assert read(cid)['media_generation']==1 and read(cid)['media_usage_seconds']==20
denied(lambda:old.service.get(wid,oldcap))
new,cap,_=phone.scoped_runtime(cid)
new.service.get(wid,cap)
resume.prepare(phone,cid,1,5)
now[0]+=21
denied(lambda:resume.claim(phone,ref,meta))
phone.finish(cid,'completed',41,live_seconds=25)

def expect_status(fn,status,code=None):
    try:fn()
    except AlphaError as error:
        assert error.status==status,error
        if code:assert error.code==code,error
        return
    raise AssertionError('Expected rejection')

# A normal authenticated request can choose its own lower ceiling without a
# setting change. The immutable row drives the response, delivery and all holds.
with connection() as db:service.ledger.credits.grant(db.cursor(),wid,user,'per-call-duration-grant',2_000_000,source='synthetic-only')
before_creates=provider.create_count
bounded=phone.request(wid,user,{'idempotencyKey':'per-call-duration-60','callDurationLimitSeconds':60,'useAvailableCredits':True})
cid=bounded['id']
assert bounded['maxSeconds']==read(cid)['max_seconds']==60
assert phone.config.cap_seconds==3600 and provider.calls['fake_'+cid]['cap']==60
assert sql("SELECT (meta->>'capSeconds')::int FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(60,),(60,)]
for extra in ({},{'callDurationLimitSeconds':60}):
    retry=phone.request(wid,user,{'idempotencyKey':'per-call-duration-60',**extra})
    assert retry['id']==cid and retry['maxSeconds']==60
expect_status(lambda:phone.request(wid,user,{'idempotencyKey':'per-call-duration-60','callDurationLimitSeconds':120}),409,'phone_duration_conflict')
expect_status(lambda:phone.request(wid,user,{'idempotencyKey':'full-hour-credits','callDurationLimitSeconds':60}),409,'phone_duration_conflict')
assert provider.create_count==before_creates+1
sql("UPDATE pr_phone_calls SET state='live',answered_at=to_timestamp(%s),media_claimed_at=to_timestamp(%s) WHERE id=%s",now[0],now[0],cid)
start=now[0]
scoped,cap,_=phone.scoped_runtime(cid)
now[0]=start+50
billing.renew(phone,cid)
assert read(cid)['funded_seconds']==60
assert sql("SELECT count(*) FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(2,)]
now[0]=start+59
scoped.service.get(wid,cap)
now[0]=start+60
expect_status(lambda:scoped.service.get(wid,cap),409,'phone_expired')
phone.finish(cid,'completed',60,live_seconds=60)
assert read(cid)['duration_seconds']==60 and phone.view(wid,user,cid)['maxSeconds']==60
with connection() as db:assert service.ledger.credits.view(db.cursor(),wid)['heldMilliCredits']==0

# A non-minute-aligned ceiling clips renewal rather than funding to 120 seconds.
cid=begin('per-call-duration-90',callDurationLimitSeconds=90,useAvailableCredits=True)
start=now[0]
now[0]=start+50
billing.renew(phone,cid)
assert read(cid)['funded_seconds']==90
assert sql("SELECT DISTINCT (meta->>'capSeconds')::int FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(90,)]
assert sql("SELECT DISTINCT (meta->>'throughSeconds')::int FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND meta ? 'throughSeconds'",cid)==[(90,)]
now[0]=start+89
billing.renew(phone,cid)
assert read(cid)['funded_seconds']==90
phone.finish(cid,'completed',90,live_seconds=90)

# Concurrent retries share one admission. A conflicting supplied cap is never
# reported as applied, and neither a retry nor a conflict creates another call.
before_creates=provider.create_count
def attempt_duration(seconds):
    try:return ('accepted',phone.request(wid,user,{'idempotencyKey':'per-call-duration-race','callDurationLimitSeconds':seconds,'useAvailableCredits':True}))
    except AlphaError as error:return ('denied',error.status,error.code)
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt_duration,(60,120)))
accepted=[result[1] for result in results if result[0]=='accepted']
assert len(accepted)==1 and [result[1:] for result in results if result[0]=='denied']==[(409,'phone_duration_conflict')],results
winner=accepted[0]
assert read(winner['id'])['max_seconds']==winner['maxSeconds']
assert provider.calls['fake_'+winner['id']]['cap']==winner['maxSeconds']
assert provider.create_count==before_creates+1
phone.hangup(winner['id'])

# Lost provider acceptance stays ambiguous. Lowering a hint or choosing a new
# key cannot authorize another dial or release the original component holds.
provider.outcome='ambiguous'
before_creates=provider.create_count
uncertain=phone.request(wid,user,{'idempotencyKey':'per-call-duration-ambiguous','callDurationLimitSeconds':60,'useAvailableCredits':True})
cid=uncertain['id']
assert uncertain['state']=='ambiguous' and uncertain['maxSeconds']==60
retry=phone.request(wid,user,{'idempotencyKey':'per-call-duration-ambiguous'})
assert retry['id']==cid and retry['state']=='ambiguous' and retry['maxSeconds']==60
expect_status(lambda:phone.request(wid,user,{'idempotencyKey':'per-call-duration-ambiguous','callDurationLimitSeconds':120}),409,'phone_duration_conflict')
expect_status(lambda:phone.request(wid,user,{'idempotencyKey':'per-call-duration-new-key','callDurationLimitSeconds':60,'useAvailableCredits':True}),409,'call_active')
assert provider.create_count==before_creates+1
assert sql("SELECT count(*) FROM pr_usage_ledger WHERE meta->>'phoneCallId'=%s AND kind='reserve'",cid)==[(2,)]
with connection() as db:assert service.ledger.credits.view(db.cursor(),wid)['heldMilliCredits']>0
assert phone.hangup(cid)=={'ended':False,'state':'ending'}
from postriff_phase2.phone import delivery
delivery.reconcile(phone,cid)
assert provider.create_count==before_creates+1 and read(cid)['state']=='cancelled'
with connection() as db:assert service.ledger.credits.view(db.cursor(),wid)['heldMilliCredits']==0
print('PASS real PostgreSQL: balance exhaustion/atomic rollback, concurrent renewal once, 60/600/3600s boundaries, all minute holds settled once, signed handoff fencing, authenticated per-call limits with reservation/renewal/provider binding and conflict-safe ambiguous retries; realCalls=0')
