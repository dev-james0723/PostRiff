"""PREPARED ONLY: P0–P3 ONCE, then P4 against owned synthetic PostgreSQL17.

Never run locally or against production. Runner owns127.0.0.1:55438/postgres,
postriff_test and the temp cluster lifecycle. All provider responses are mocked.
This is coordination qualification, not1,000/10,000-user capacity/acceptance.
"""
import copy
import hashlib
import json
import os
import runpy
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier,Event,Lock
from unittest.mock import patch
from urllib.parse import urlsplit

if sys.platform!='linux' or os.environ.get('CI')!='true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE')!='1':
    raise SystemExit('P4 SQL requires separate cloud/disposable-database approval.')
TASK_ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(TASK_ROOT/'src'),str(TASK_ROOT/'tests')]
import psycopg
from postriff_phase2.discord.rate_limits import (
    SharedPostgresBudget,RequestIdentity,RateDelayed,RateCoordinatorUnavailable,route_identity,_digest,
)
from test_discord_rate_limits import synthetic_policy

DSN='host=127.0.0.1 port=55438 dbname=postgres user=postriff_test'
@contextmanager
def connection():
    with psycopg.connect(DSN,connect_timeout=5,options='-c statement_timeout=10000 -c lock_timeout=5000') as db:
        assert (db.info.host,db.info.port,db.info.dbname,db.info.user)==('127.0.0.1',55438,'postgres','postriff_test')
        yield db

with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone()==('127.0.0.1',55438,'postgres')
    assert int(db.execute("SELECT current_setting('server_version_num')").fetchone()[0])//10000==17

# Existing fixtures perform their prior chain once. No second cluster or import.
prior=runpy.run_path(str(Path(__file__).with_name('postgres_discord_worker.py')))
base,Fixture=prior['base'],prior['Fixture']
PostgresWorker=prior['PostgresWorker']
draft=TASK_ROOT/'migrations/postriff/124_discord_rate_limits.sql'
DRAFT_SHA='91bc2b004468d4f265ea1f4532d2f90c485ff8e8ce2c24d994015f1c6ea12e61'
assert hashlib.sha256(draft.read_bytes()).hexdigest()==DRAFT_SHA,'Draft drift; no SQL application allowed'
with connection() as db:db.execute(draft.read_text())

checks=[];metrics=[];case=0
started=time.monotonic()

# Reproduce the canonical Supabase default grant, then prove migration125
# removes routine destructive access while preserving coordinator writes.
grants=TASK_ROOT/'migrations/postriff/125_discord_service_grants.sql'
assert hashlib.sha256(grants.read_bytes()).hexdigest()=='a0086cd1d01195c6114aba53de72cf5819d4c19b890b1716b453b33dc850c645'
with connection() as db:
    db.execute('GRANT ALL ON public.pr_discord_rate_state,public.pr_discord_route_buckets,public.pr_discord_request_admissions TO service_role')
    db.execute('GRANT ALL ON SEQUENCE public.pr_discord_request_admissions_request_seq_seq TO service_role')
    assert db.execute("SELECT has_table_privilege('service_role','public.pr_discord_rate_state','DELETE')").fetchone()[0]
    db.execute(grants.read_text())
    for table in ('pr_discord_rate_state','pr_discord_route_buckets','pr_discord_request_admissions'):
        rights=db.execute("SELECT has_table_privilege('service_role',%s,'SELECT'),has_table_privilege('service_role',%s,'INSERT'),has_table_privilege('service_role',%s,'UPDATE'),has_table_privilege('service_role',%s,'DELETE'),has_table_privilege('service_role',%s,'TRUNCATE')",('public.'+table,)*5).fetchone()
        assert rights==(True,True,True,False,False),rights
    assert db.execute("SELECT has_sequence_privilege('service_role','public.pr_discord_request_admissions_request_seq_seq','UPDATE')").fetchone()[0] is False
checks.append('canonical default service_role ALL reproduced;125 preserves SELECT/INSERT/UPDATE and revokes DELETE/TRUNCATE/sequence UPDATE')
def db_now():
    with connection() as db:return float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
def setup(**changes):
    global case
    case+=1
    app=str(700000000000000000+case)
    policy=synthetic_policy(db_now());policy.update(app_capacity=1000,app_window_seconds=60,unknown_window_seconds=10,
        permit_ttl_seconds=2,invalid_capacity=100,egress_scope='synthetic-case-'+str(case))
    policy.update(changes)
    limiter=SharedPostgresBudget(connection,app,policy=policy)
    identity=RequestIdentity.make(app,'bot','synthetic-bot-'+str(case))
    path='/channels/'+str(800000000000000000+case)+'/messages/999999999999999999'
    return limiter,identity,path,policy

def send(limiter,identity,path,response):
    p=limiter.reserve('GET',path,identity=identity)
    limiter.consume(p,'GET',path);limiter.observe(p,response);return p

def learn(limiter,identity,path,bucket='synthetic-bucket',cap=3):
    return send(limiter,identity,path,{'status':200,'headers':{
        'X-RateLimit-Bucket':bucket,'X-RateLimit-Limit':str(cap),
        'X-RateLimit-Remaining':str(cap-1),'X-RateLimit-Reset-After':'30'}})

def roll_route(identity,path,bucket='synthetic-bucket',*,method='GET'):
    _,major=route_identity(method,path)
    key='50:'+_digest(identity.auth_key+':'+_digest(bucket)+':'+major)
    with connection() as db:
        changed=db.execute("UPDATE public.pr_discord_rate_state SET reset_at=clock_timestamp()-interval '1 second' WHERE scope_key=%s AND learned AND fresh_after IS NULL",(key,))
        assert changed.rowcount==1,'Only a learned synthetic provider window may advance'
    return key

def expect_denied(action,error=(RateDelayed,RateCoordinatorUnavailable)):
    try:action()
    except error as exc:return exc
    raise AssertionError('Expected safe admission denial')

limiter,identity,path,policy=setup()
template,major=route_identity('GET',path)
with limiter._transaction() as cur:
    cur.execute("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')")
    assert cur.fetchone()==('2s','5s'),'Both transaction-local safety timeouts remain active'
    assert limiter._map(cur,identity,_digest(template),major)==(None,0)
    assert limiter._map(cur,identity,_digest(template),major)==(None,0)
    cur.execute('UPDATE public.pr_discord_route_buckets SET bucket_key=%s,observation_seq=17 WHERE auth_key=%s AND route_key=%s AND major_key=%s',(_digest('retained-synthetic-bucket'),identity.auth_key,_digest(template),major))
    assert limiter._map(cur,identity,_digest(template),major)==(_digest('retained-synthetic-bucket'),17)
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_discord_route_buckets WHERE auth_key=%s',
        (identity.auth_key,)).fetchone()[0]==1
checks.append('combined local timeouts preserved;existing/cold locked mapping has one durable row;bucket and sequence retained')

# Exercise the same optional factory used by hosted_app and the capacity
# harness. Session-scoped settings are intentional fault injection here.
from postriff_phase2.postgres_pool import PooledPostgresFactory
from postriff_alpha.domain import AlphaError
pooled=PooledPostgresFactory(DSN,max_size=1,max_waiting=2,timeout=.2)
try:
    with pooled() as db:
        first_pid=db.execute('SELECT pg_backend_pid()').fetchone()[0]
        db.execute('SET ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub','pool-synthetic-principal',false)")
    with pooled() as db:
        row=db.execute("SELECT pg_backend_pid(),current_user,current_setting('request.jwt.claim.sub',true)").fetchone()
        assert row[0]==first_pid and row[1]=='postriff_test' and row[2] in (None,'')
    try:
        with pooled() as db:
            db.execute('SET ROLE authenticated')
            db.execute("SELECT set_config('request.jwt.claim.sub','pool-rollback-principal',false)")
            raise RuntimeError('Synthetic rollback')
    except RuntimeError:pass
    with pooled() as db:
        assert db.execute('SELECT current_user').fetchone()[0]=='postriff_test'
        def exhausted():
            try:
                with pooled():raise AssertionError('Exceeded one-connection pool bound')
            except AlphaError as error:
                assert error.status==503 and error.code=='database_capacity_unavailable'
        with ThreadPoolExecutor(max_workers=1) as executor:executor.submit(exhausted).result(timeout=2)
    left,right=Fixture(),Fixture()
    for own,foreign in ((left,right),(right,left)):
        with pooled() as db:
            db.execute('SET LOCAL ROLE authenticated')
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true),set_config('request.jwt.claims',%s,true)",
                (own.user,json.dumps({'sub':own.user,'session_id':'synthetic-pool-session','aal':'aal2'})))
            assert db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=%s',(own.workspace,)).fetchone()[0]==1
            assert db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=%s',(foreign.workspace,)).fetchone()[0]==0
    with pooled() as db:db.close()
    with pooled() as db:
        assert db.execute('SELECT current_user').fetchone()[0]=='postriff_test'
    assert pooled.stats()['counters']['connections_num']>=2
finally:pooled.close()
assert pooled.stats()['closed']
checks.append('bounded shared pool reuses connections;commit/rollback role+claims reset;two-tenant RLS;busy503;broken connection discarded;closed')

# Exercise a real failed RESET ALL, after RESET ROLE has run in the same
# transaction. Its rollback restores the dirty session, so only discarding the
# backend can make the next borrow safe. The production reset callback runs.
class FailResetOnce(PooledPostgresFactory):
    fail_reset=True
    def _reset(self,raw):
        owner=self
        class ResetProxy:
            def transaction(self):return raw.transaction()
            def execute(self,statement):
                if statement=='RESET ALL' and owner.fail_reset:
                    owner.fail_reset=False
                    return raw.execute('SELECT 1/0')
                return raw.execute(statement)
        return super()._reset(ResetProxy())
reset_observations=[]
faulty=FailResetOnce(DSN,max_size=1,max_waiting=2,timeout=2,
    observer=lambda operation,elapsed,error:reset_observations.append((operation,elapsed,error)))
try:
    with faulty() as db:
        discarded_pid=db.execute('SELECT pg_backend_pid()').fetchone()[0]
        db.execute('SET ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub','pool-reset-failure-principal',false)")
        db.execute("SELECT set_config('request.jwt.claims','{\"sub\":\"pool-reset-failure-principal\"}',false)")
    with faulty() as db:
        clean=db.execute("SELECT pg_backend_pid(),current_user,current_setting('request.jwt.claim.sub',true),current_setting('request.jwt.claims',true)").fetchone()
        assert clean[0]!=discarded_pid and clean[1]=='postriff_test' and clean[2] in (None,'') and clean[3] in (None,''),clean
    reset_failures=[error for operation,elapsed,error in reset_observations if error]
    assert reset_failures==['DivisionByZero'],reset_failures
    assert faulty.stats()['counters']['connections_num']>=2
finally:faulty.close()
assert faulty.stats()['closed']
metrics.append({'case':'failed-pool-reset','replacementBackend':True,'roleAndClaimsClean':True,
    'recordedFailureClasses':reset_failures,'closed':True})
checks.append('actual failed RESET ALL after committed dirty role+claims discards backend;replacement role+claims clean;safe error telemetry;closed')

# New batching regressions are PREPARED, not executed by local approval.
# Wrap actual PG cursors to count only public operation labels and inject a
# deliberately bad driver result AFTER real SQL. The surrounding transaction
# must undo every state/mapping write; no provider transport is involved.
class ScopeCursor:
    def __init__(self,raw,mode,trace):
        self.raw,self.mode,self.trace=raw,mode,trace
        self.buffer=None;self.count_override=None
    def __getattr__(self,name):return getattr(self.raw,name)
    @property
    def rowcount(self):return self.raw.rowcount if self.count_override is None else self.count_override
    def execute(self,query,params=()):
        self.buffer=None;self.count_override=None
        if self.mode=='delete-before-lock' and query.lstrip().startswith('WITH scope_lock AS MATERIALIZED'):
            self.raw.execute('DELETE FROM public.pr_discord_rate_state WHERE scope_key=%s',(params[0][0],))
        self.raw.execute(query,params)
        operation=next((name for name,prefix in (('seed','WITH scope_seed('),('lock','WITH scope_lock AS MATERIALIZED'),
            ('store','WITH scope_store(')) if query.lstrip().startswith(prefix)),None)
        if operation:self.trace.append(operation)
        if operation=='lock' and self.mode=='lock-missing':self.buffer=self.raw.fetchall()[1:]
        if operation=='store' and self.mode=='store-count':self.count_override=self.raw.rowcount-1
        if operation=='store' and self.mode=='store-key':
            self.buffer=self.raw.fetchall();self.buffer[0]=('99:'+'0'*64,)
        return self
    def fetchall(self):
        if self.buffer is None:return self.raw.fetchall()
        result,self.buffer=self.buffer,None;return result
class ScopeDatabase:
    def __init__(self,raw,mode,trace):self.raw,self.mode,self.trace=raw,mode,trace
    @contextmanager
    def cursor(self):
        with self.raw.cursor() as cur:yield ScopeCursor(cur,self.mode,self.trace)
def scope_connection(mode,trace):
    @contextmanager
    def session():
        with connection() as db:yield ScopeDatabase(db,mode,trace)
    return session

limiter,identity,path,policy=setup(permit_ttl_seconds=10)
trace=[];batched=SharedPostgresBudget(scope_connection(None,trace),limiter.application_id,policy=policy)
p=batched.reserve('GET',path,identity=identity);batched.consume(p,'GET',path)
batched.observe(p,{'status':200,'headers':{'X-RateLimit-Bucket':'scope-batch',
    'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'2','X-RateLimit-Reset-After':'30'}})
assert trace==['seed','lock','store']*2,'Each reserve/observe must perform exactly3scope operations'
template,major=route_identity('GET',path);keys=limiter._keys(identity,_digest(template),major,None)
with connection() as db:
    nullable=db.execute("SELECT limit_count,remaining,window_seconds FROM public.pr_discord_rate_state "
        "WHERE scope_key=ANY(%s::text[]) AND kind IN ('global','credential','resource')",(list(keys),)).fetchall()
assert len(nullable)==3 and all(row==(None,None,None) for row in nullable)
checks.append('batchedscope seed/orderedlock/store:exactly3operations perreserve/observe;nullableglobals preserved')

for mode in ('lock-missing','store-count','store-key'):
    limiter,identity,path,policy=setup(permit_ttl_seconds=10)
    trace=[];faulty=SharedPostgresBudget(scope_connection(mode,trace),limiter.application_id,policy=policy)
    # The reservation writes the scope states and the admission in ONE statement (_store_and_insert): a short row count
    # is read as an expired permit, a short wait that rolls everything back; a wrong returned key or a missing lock row
    # is still a coordinator fault.
    expect_denied(lambda:faulty.reserve('GET',path,identity=identity),RateDelayed if mode=='store-count' else RateCoordinatorUnavailable)
    template,major=route_identity('GET',path);keys=limiter._keys(identity,_digest(template),major,None)
    with connection() as db:
        assert db.execute('SELECT count(*) FROM public.pr_discord_rate_state WHERE scope_key=ANY(%s::text[])',
            (list(keys),)).fetchone()[0]==0,'Bad batch result must roll back all seeded/debited state'
        assert db.execute('SELECT count(*) FROM public.pr_discord_route_buckets WHERE auth_key=%s',
            (identity.auth_key,)).fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM public.pr_discord_request_admissions WHERE auth_key=%s',
            (identity.auth_key,)).fetchone()[0]==0
    assert limiter.reserve('GET',path,identity=identity),'Rolledback batch must not burn its cold admission'
checks.append('batch missingrow/count/returnedkey faults roll back all SQL state/mapping;normal retry retains its slot')

# A visible warm key can disappear after the seed snapshot. The complete
# locked reread must reject the missing guard, rolling back the actual deletion
# and preserving the prior observed evidence; no new admission may escape.
limiter,identity,path,policy=setup(permit_ttl_seconds=10)
sent=limiter.reserve_read('GET',path,identity=identity)
limiter.observe(sent,{'status':200,'headers':{'X-RateLimit-Bucket':'missing-seed-warm',
    'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}})
template,major=route_identity('GET',path)
warm_keys=limiter._keys(identity,_digest(template),major,_digest('missing-seed-warm'))
def seed_snapshot():
    with connection() as db:
        return (db.execute('SELECT to_jsonb(s)::text FROM public.pr_discord_rate_state s WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key',(list(warm_keys),)).fetchall(),
            db.execute('SELECT to_jsonb(r)::text FROM public.pr_discord_route_buckets r WHERE auth_key=%s ORDER BY route_key,major_key',(identity.auth_key,)).fetchall(),
            db.execute('SELECT to_jsonb(a)::text FROM public.pr_discord_request_admissions a WHERE auth_key=%s ORDER BY request_seq',(identity.auth_key,)).fetchall())
before=seed_snapshot();trace=[]
faulty=SharedPostgresBudget(scope_connection('delete-before-lock',trace),limiter.application_id,policy=policy)
expect_denied(lambda:faulty.reserve_read('GET',path,identity=identity),RateCoordinatorUnavailable)
assert trace==['seed','lock'] and seed_snapshot()==before,'Missing locked guard must roll back deletion, mappings, quota and any new admission'
checks.append('warm seed snapshot followed by actual guard deletion fails complete locked cardinality;SQL rollback restores guard/mapping/prior admission,none new')

# Cold responses still lock every guard, but an unchanged common guard must not
# acquire a new heap/index version solely for an unused response sequence.
limiter,identity,path,policy=setup(permit_ttl_seconds=10)
sent=limiter.reserve_read('GET',path,identity=identity)
with connection() as db:
    common=db.execute("SELECT scope_key,revision,updated_at,observation_seq,limit_count,remaining,"
        "blocked_until,circuit_until,error_streak,manual_hold FROM public.pr_discord_rate_state "
        "WHERE scope_key=ANY((SELECT scope_keys FROM public.pr_discord_request_admissions WHERE id=%s)::text[]) "
        "AND kind IN ('policy','global','credential','invalid','resource') ORDER BY scope_key",(sent.id,)).fetchall()
limiter.observe(sent,{'status':200,'headers':{'X-RateLimit-Bucket':'cold-version-check',
    'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}})
with connection() as db:
    after=db.execute("SELECT scope_key,revision,updated_at,observation_seq,limit_count,remaining,"
        "blocked_until,circuit_until,error_streak,manual_hold FROM public.pr_discord_rate_state "
        "WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key",([row[0] for row in common],)).fetchall()
    assert len(common)==5 and after==common,'Cold response rewrote unchanged guards or refunded quota'
    admission=db.execute('SELECT state,request_seq,scope_keys FROM public.pr_discord_request_admissions WHERE id=%s',(sent.id,)).fetchone()
    assert admission[0]=='observed'
    sequences=db.execute("SELECT observation_seq FROM public.pr_discord_rate_state WHERE scope_key=ANY(%s::text[]) AND kind='route'",(admission[2],)).fetchall()
    assert len(sequences)==2 and all(row[0]==admission[1] for row in sequences),'Both aliases retain response-order fences'
checks.append('cold successful observation keeps5common guard heap/index versions and quota unchanged;both route sequences and observed outcome persist')

limiter,identity,path,policy=setup(permit_ttl_seconds=10)
sent=limiter.reserve_read('GET',path,identity=identity)
template,major=route_identity('GET',path)
keys=set(limiter._keys(identity,_digest(template),major,None))
keys.add('50:'+_digest(identity.auth_key+':'+_digest('rollback-cold-alias')+':'+major))
def observation_snapshot():
    with connection() as db:
        return (db.execute('SELECT to_jsonb(s)::text FROM public.pr_discord_rate_state s WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key',(list(keys),)).fetchall(),
            db.execute('SELECT to_jsonb(r)::text FROM public.pr_discord_route_buckets r WHERE auth_key=%s ORDER BY route_key,major_key',(identity.auth_key,)).fetchall(),
            db.execute('SELECT to_jsonb(a)::text FROM public.pr_discord_request_admissions a WHERE id=%s',(sent.id,)).fetchall())
before=observation_snapshot()
trace=[];faulty=SharedPostgresBudget(scope_connection('store-count',trace),limiter.application_id,policy=policy)
expect_denied(lambda:faulty.observe(sent,{'status':429,'headers':{'X-RateLimit-Bucket':'rollback-cold-alias',
    'X-RateLimit-Global':'true','Retry-After':'2'},'body':{'retry_after':2,'global':True}}),RateCoordinatorUnavailable)
assert observation_snapshot()==before,'Partial changed-row observation must roll back new alias,guard changes and outcome'
checks.append('partial changed-row cold429 observation rolls back every guard/mapping/alias/outcome;sent evidence remains unresolved')

# Retain all previously qualified coordinator groups. They require a NEW
# approved remote execution after batching; prior results cover prior source.
# Keep provider quotas small and account every permit; no HTTP is invoked.
limiter,identity,path,policy=setup(permit_ttl_seconds=10)
barrier=Barrier(16)
def cold_attempt(_index):
    barrier.wait(timeout=10)
    try:return limiter.reserve('GET',path,identity=identity)
    except RateDelayed:return None
with ThreadPoolExecutor(max_workers=16) as pool:cold=list(pool.map(cold_attempt,range(16)))
assert sum(p is not None for p in cold)==1,'Cold discovery permits must remain shared'
first=next(p for p in cold if p is not None);limiter.consume(first,'GET',path)
limiter.observe(first,{'status':200,'headers':{'X-RateLimit-Bucket':'first-learning',
    'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'2','X-RateLimit-Reset-After':'30'}})
barrier=Barrier(16)
def learned_attempt(_index):
    barrier.wait(timeout=10)
    try:return limiter.reserve('GET',path,identity=identity)
    except RateDelayed:return None
with ThreadPoolExecutor(max_workers=16) as pool:learned=list(pool.map(learned_attempt,range(16)))
assert sum(p is not None for p in learned)==2,'First valid header must expose exactly the remaining2slots'
checks.append('concurrent first learning:16cold contenders admit1;16learned contenders admit2;total3,no bypass')

limiter,identity,path,policy=setup(permit_ttl_seconds=10)
learn(limiter,identity,path,cap=5)
waiting=limiter.reserve('GET',path,identity=identity)
other=path.rsplit('/',1)[0]
probe=limiter.reserve('GET',other,identity=identity);limiter.consume(probe,'GET',other)
template,major=route_identity('GET',other)
alias='50:'+_digest(identity.auth_key+':'+_digest('synthetic-bucket')+':'+major)
with connection() as db,db.cursor() as cur:
    assert limiter._alias_pending(cur,alias,probe,(_digest(template),major),db_now())==(1,0)
limiter.observe(probe,{'status':200,'headers':{'X-RateLimit-Bucket':'synthetic-bucket',
    'X-RateLimit-Limit':'5','X-RateLimit-Remaining':'3','X-RateLimit-Reset-After':'30'}})
with connection() as db:
    assert db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',(alias,)).fetchone()[0]==2
    scope_keys=db.execute('SELECT scope_keys FROM public.pr_discord_request_admissions WHERE id=%s::uuid',(waiting.id,)).fetchone()[0]
    assert scope_keys.count(alias)==1,'Mapped pending admission must not be duplicated'
    probe_keys=db.execute('SELECT scope_keys FROM public.pr_discord_request_admissions WHERE id=%s::uuid',(probe.id,)).fetchone()[0]
    assert probe_keys.count(alias)==1
checks.append('learning another route charges observer once, conserves pendingknownquota and maps alias once')

limiter,identity,path,policy=setup(permit_ttl_seconds=10)
learn(limiter,identity,path,cap=10)
early,later=[limiter.reserve('GET',path,identity=identity) for _ in range(2)]
for p in (early,later):limiter.consume(p,'GET',path)
limiter.observe(later,{'status':200,'headers':{'X-RateLimit-Bucket':'synthetic-bucket',
    'X-RateLimit-Limit':'10','X-RateLimit-Remaining':'6','X-RateLimit-Reset-After':'30'}})
_,major=route_identity('GET',path);alias='50:'+_digest(identity.auth_key+':'+_digest('synthetic-bucket')+':'+major)
with connection() as db:before=db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',(alias,)).fetchone()[0]
limiter.observe(early,{'status':200,'headers':{'X-RateLimit-Bucket':'older-unseen-alias',
    'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}})
with connection() as db:
    assert db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',(alias,)).fetchone()[0]<=before
    assert db.execute('SELECT bucket_key FROM public.pr_discord_route_buckets WHERE auth_key=%s AND route_key=%s AND major_key=%s',
        (identity.auth_key,_digest(route_identity('GET',path)[0]),major)).fetchone()[0]==_digest('synthetic-bucket')
checks.append('older higherremaining/alias response cannot refill activequota or replace newer route mapping')

limiter,identity,path,policy=setup(permit_ttl_seconds=10)
learn(limiter,identity,path,cap=3);roll_route(identity,path)
permit=limiter.reserve('GET',path,identity=identity);limiter.consume(permit,'GET',path)
observed_at=db_now()
limiter.observe(permit,{'status':200,'headers':{'X-RateLimit-Bucket':'fresh-after-roll',
    'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'2','X-RateLimit-Reset-After':'1'}})
_,major=route_identity('GET',path)
alias='50:'+_digest(identity.auth_key+':'+_digest('fresh-after-roll')+':'+major)
with connection() as db:
    remaining,reset,fresh_after=db.execute('SELECT remaining,extract(epoch FROM reset_at)::double precision,fresh_after '
        'FROM public.pr_discord_rate_state WHERE scope_key=%s',(alias,)).fetchone()
assert remaining==2 and fresh_after is None
assert observed_at<reset<observed_at+2,'Fresh bucket must replace policy-expiry sentinel with its observed1sreset'
roll_route(identity,path,bucket='fresh-after-roll')
assert limiter.reserve('GET',path,identity=identity)
checks.append('learnedA -> rolledwindow -> freshB replaces sentinelreset;realproviderdeadline controls next admission')

# Pause consume AFTER its last valid clock check, before its state update.
# Observation starts after expiry and must lock/re-read the resulting sent row
# before allocating the smaller alias. No provider HTTP is performed.
limiter,identity,path,policy=setup(permit_ttl_seconds=2)
learn(limiter,identity,path,cap=10)
waiting,observer=[limiter.reserve('GET',path,identity=identity) for _ in range(2)]
limiter.consume(observer,'GET',path)
paused,release=Event(),Event()
race={}
class PausedCursor:
    def __init__(self,raw):self.raw=raw
    def __getattr__(self,name):return getattr(self.raw,name)
    def execute(self,query,params=()):
        if "SET state='sent'" in query and params[0]==waiting.id:
            race['consumerPid']=self.raw.connection.info.backend_pid
            paused.set()
            if not release.wait(6):raise AssertionError('Owned consume race release timed out')
        return self.raw.execute(query,params)
class PausedDatabase:
    def __init__(self,raw):self.raw=raw
    @contextmanager
    def cursor(self):
        with self.raw.cursor() as cur:yield PausedCursor(cur)
@contextmanager
def paused_connection():
    with connection() as db:yield PausedDatabase(db)
consumer=SharedPostgresBudget(paused_connection,limiter.application_id,policy=policy)
with ThreadPoolExecutor(max_workers=2) as pool:
    consuming=pool.submit(consumer.consume,waiting,'GET',path)
    try:
        assert paused.wait(3),'Consume must reach its final successful clock check'
        time.sleep(max(0,waiting.expires_at-db_now())+.05)  # REMOTE owned fixture only
        observing=pool.submit(limiter.observe,observer,{'status':200,'headers':{
            'X-RateLimit-Bucket':'smaller-race-alias','X-RateLimit-Limit':'3',
            'X-RateLimit-Remaining':'2','X-RateLimit-Reset-After':'30'}})
        blocked=False;deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            with connection() as db:
                blocked=db.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' "
                    'AND %s=ANY(pg_blocking_pids(pid)))',(race['consumerPid'],)).fetchone()[0]
            if blocked:break
            time.sleep(.01)
        assert blocked,'Observation must wait for the in-flight admission transition'
    finally:release.set()
    consuming.result(timeout=3);observing.result(timeout=3)
_,major=route_identity('GET',path)
alias='50:'+_digest(identity.auth_key+':'+_digest('smaller-race-alias')+':'+major)
with connection() as db:
    assert db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',(alias,)).fetchone()[0]==1
    state,keys=db.execute('SELECT state,scope_keys FROM public.pr_discord_request_admissions WHERE id=%s::uuid',
        (waiting.id,)).fetchone()
    assert state=='sent' and keys.count(alias)==1
assert limiter.reserve('GET',path,identity=identity)
expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateDelayed)
checks.append('expiry/consume/aliasrace re-readssentrow:smallerbucket3 retains1slot;count and mapping agree,no excesspermit')

# A permit lives as long as the policy's permit_ttl_seconds (no window ends it any more), so the short-life cases ask for the
# shortest life the policy accepts (0.05 s): the 0.08 s delays below then outlive the permit.
limiter,identity,path,policy=setup(unknown_window_seconds=.05,permit_ttl_seconds=.05)
class LateInsert(SharedPostgresBudget):
    def _store_and_insert(self,cur,*args,**kwargs):
        # The admission is written inside the combined store+insert statement (and by _insert only when no scope state
        # changed); delaying the combined call covers both.
        cur.execute('SELECT pg_sleep(.08)')  # deterministic owned-DB timing, no real API
        return super()._store_and_insert(cur,*args,**kwargs)
late=LateInsert(connection,limiter.application_id,policy=policy)
error=expect_denied(lambda:late.reserve('GET',path,identity=identity),RateDelayed)
assert error.rate_cause=='permit_expired' and error.rate_scope_kind=='permit'
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_discord_request_admissions WHERE application_key=%s',(_digest(limiter.application_id),)).fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM public.pr_discord_route_buckets WHERE auth_key=%s',(identity.auth_key,)).fetchone()[0]==0
permit=limiter.reserve('GET',path,identity=identity)
with connection() as db:
    reserved,expires=db.execute('SELECT extract(epoch FROM reserved_at)::double precision,extract(epoch FROM expires_at)::double precision '
        'FROM public.pr_discord_request_admissions WHERE id=%s::uuid',(permit.id,)).fetchone()
    assert reserved<expires and abs(expires-permit.expires_at)<.000002
checks.append('late expired INSERT creates no admission/mapping and rolls backdebits;frozenexpiry is neverextended')

for replicas in (1,8,16):
    limiter,identity,path,policy=setup();learn(limiter,identity,path);roll_route(identity,path)
    # All contenders start together; even one replica attempts16 calls in order.
    barrier=Barrier(replicas)
    def attempt(index):
        if index<replicas:barrier.wait(timeout=10)
        replica=SharedPostgresBudget(connection,limiter.application_id,policy=policy)
        begin=time.monotonic()
        try:
            replica.reserve('GET',path,identity=identity);return True,time.monotonic()-begin
        except RateDelayed:return False,time.monotonic()-begin
    with ThreadPoolExecutor(max_workers=replicas) as pool:results=list(pool.map(attempt,range(16)))
    assert sum(ok for ok,_ in results)==3,results
    delays=sorted(d for _,d in results)
    metrics.append({'workers':replicas,'attempted':16,'admitted':3,'deferred':13,
        'maxReservationSeconds':max(delays),'p95ReservationSeconds':delays[14],
        'safetyTarget':'exactly3 learned slots;0 quota bypass','contentionTargetSeconds':8})
    assert max(delays)<8
checks.append('1/8/16 replicas:16 attempts share exactly3 learned slots before synthetic window reset')

limiter,identity,path,policy=setup();other=path.rsplit('/',1)[0]
learn(limiter,identity,path);learn(limiter,identity,other);roll_route(identity,path)
for target in (path,other,path):limiter.reserve('GET',target,identity=identity)
expect_denied(lambda:limiter.reserve('GET',other,identity=identity),RateDelayed)
independent=path.replace(path.split('/')[2],'666666666666666666')
assert limiter.reserve('GET',independent,identity=identity)
checks.append('learned route aliases share bucket; exact major resource stays independent')

for scope in ('global','shared'):
    limiter,identity,path,policy=setup();learn(limiter,identity,path);roll_route(identity,path)
    unused=limiter.reserve('GET',path,identity=identity)
    p=limiter.reserve('GET',path,identity=identity);limiter.consume(p,'GET',path)
    limiter.observe(p,{'status':429,'headers':{'X-RateLimit-Scope':scope,'Retry-After':'172800.25'},'body':{}})
    expect_denied(lambda:limiter.consume(unused,'GET',path))
    next_identity=RequestIdentity.make(limiter.application_id,'user','synthetic-user-grant','555555555555555555') if scope=='shared' else identity
    target=path if scope=='shared' else path.replace(path.split('/')[2],'444444444444444444')
    delayed=expect_denied(lambda:limiter.reserve('GET',target,identity=next_identity),RateDelayed)
    assert delayed.retry_after_seconds>172799
    with connection() as db:
        invalid=db.execute("SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s",('20:'+_digest(policy['egress_scope']),)).fetchone()[0]
    assert invalid==policy['invalid_capacity']-(scope=='global')
checks.append('global/shared429 stop unused permits; sharedresource crosses auth scopes;2day wait unshortened;invalid accounting exact')

limiter,identity,path,policy=setup();learn(limiter,identity,path);roll_route(identity,path)
early,later=[limiter.reserve('GET',path,identity=identity) for _ in range(2)]
for p in (early,later):limiter.consume(p,'GET',path)
limiter.observe(later,{'status':429,'headers':{'X-RateLimit-Bucket':'synthetic-bucket','Retry-After':'7.25'},'body':{}})
limiter.observe(early,{'status':200,'headers':{'X-RateLimit-Bucket':'stale-alias','X-RateLimit-Limit':'99',
    'X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'1'}})
assert expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateDelayed).retry_after_seconds>6.5
with connection() as db:
    assert db.execute('SELECT bucket_key FROM public.pr_discord_route_buckets WHERE auth_key=%s',(identity.auth_key,)).fetchone()[0]==_digest('synthetic-bucket')
checks.append('late/reordered headers cannot inflate allowance, remap a newer bucket or shorten fractional cooldown')

limiter,identity,path,policy=setup()
send(limiter,identity,path,{'status':429,'headers':{'Retry-After':'NaN'},'body':{}})
expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
expired={**policy,'issued_at':db_now()-100,'expires_at':db_now()-1}
expect_denied(lambda:SharedPostgresBudget(connection,limiter.application_id,policy=expired).reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
expect_denied(lambda:SharedPostgresBudget(connection,limiter.application_id).reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
@contextmanager
def unavailable():raise ConnectionError('Synthetic DB outage');yield
expect_denied(lambda:SharedPostgresBudget(unavailable,limiter.application_id,policy=policy).reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
checks.append('malformed429,missing/expired policy and DB outage deny before transport')

limiter,identity,path,policy=setup();learn(limiter,identity,path);roll_route(identity,path)
p=limiter.reserve('GET',path,identity=identity);limiter.consume(p,'GET',path);limiter.note_transport_failure(p)
limiter.reserve('GET',path,identity=identity);limiter.reserve('GET',path,identity=identity)
expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateDelayed)
checks.append('ambiguous request retains spent slot;no automatic refund or stalecountdown refill')

limiter,identity,path,policy=setup()
send(limiter,identity,path,{'status':401,'headers':{}})
expect_denied(lambda:limiter.reserve('GET',path.replace(path.split('/')[2],'333333333333333333'),identity=identity),RateCoordinatorUnavailable)
renewed={**policy,'revision':'renewed-401','issued_at':db_now()-1,'expires_at':db_now()+3600}
expect_denied(lambda:SharedPostgresBudget(connection,limiter.application_id,policy=renewed).reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
checks.append('bot401 stops credential scope across replicas/resources')

for scope in ('global','shared'):
    limiter,identity,path,policy=setup(expires_at=db_now()+.5)
    p=limiter.reserve('GET',path,identity=identity);limiter.consume(p,'GET',path)
    time.sleep(.65)  # REMOTE ONLY: let the issuing policy expire during fake HTTP
    limiter.observe(p,{'status':429,'headers':{'X-RateLimit-Scope':scope,'Retry-After':'20'},'body':{}})
    renewed={**policy,'revision':'renewed-after-late429','issued_at':db_now()-1,'expires_at':db_now()+3600}
    replica=SharedPostgresBudget(connection,limiter.application_id,policy=renewed)
    identity2=RequestIdentity.make(limiter.application_id,'user','synthetic-late-grant','222222222222222222') if scope=='shared' else identity
    target=path if scope=='shared' else path.replace(path.split('/')[2],'111111111111111111')
    assert expect_denied(lambda:replica.reserve('GET',target,identity=identity2),RateDelayed).retry_after_seconds>19
checks.append('policy expiry blocks forward work but late429 persists embargo before renewed replica admission')

for stop in ('manual','circuit'):
    limiter,identity,path,policy=setup(failure_threshold=1);learn(limiter,identity,path);roll_route(identity,path)
    early,later=[limiter.reserve('GET',path,identity=identity) for _ in range(2)]
    for p in (early,later):limiter.consume(p,'GET',path)
    limiter.observe(early,{'status':200,'headers':{'X-RateLimit-Limit':'NaN'}} if stop=='manual' else {'status':503,'headers':{}})
    limiter.observe(later,{'status':200,'headers':{'X-RateLimit-Bucket':'new-after-stop','X-RateLimit-Limit':'3',
        'X-RateLimit-Remaining':'3','X-RateLimit-Reset-After':'1'}})
    roll_route(identity,path,'new-after-stop')
    expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateCoordinatorUnavailable if stop=='manual' else RateDelayed)
checks.append('bucket alias inherits manualhold and open circuit from an older bucket')

for old_first in (True,False):
    limiter,identity,path,policy=setup(failure_threshold=3)
    _,major=route_identity('GET',path)
    oldkey='50:'+_digest(identity.auth_key+':'+_digest('initial')+':'+major)
    newbucket=next('ordering-'+str(i) for i in range(100) if
        ((oldkey<'50:'+_digest(identity.auth_key+':'+_digest('ordering-'+str(i))+':'+major))==old_first))
    newkey='50:'+_digest(identity.auth_key+':'+_digest(newbucket)+':'+major)
    learn(limiter,identity,path,'initial');roll_route(identity,path,'initial')
    early,later=[limiter.reserve('GET',path,identity=identity) for _ in range(2)]
    for p in (early,later):limiter.consume(p,'GET',path)
    limiter.observe(early,{'status':503,'headers':{}})
    limiter.observe(later,{'status':503,'headers':{'X-RateLimit-Bucket':newbucket,'X-RateLimit-Limit':'3',
        'X-RateLimit-Remaining':'1','X-RateLimit-Reset-After':'1'}})
    with connection() as db:
        streak,circuit=db.execute('SELECT error_streak,circuit_until FROM public.pr_discord_rate_state WHERE scope_key=%s',(newkey,)).fetchone()
        assert streak==2 and circuit is None
checks.append('alias observations count each failure once in both hashed lock orders')

limiter,identity,path,policy=setup();learn(limiter,identity,path);roll_route(identity,path)
for _ in range(3):send(limiter,identity,path,{'status':200,'headers':{}})
expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateDelayed)
with connection() as db:
    _template,major=route_identity('GET',path)
    routekey='50:'+_digest(identity.auth_key+':'+_digest('synthetic-bucket')+':'+major)
    assert db.execute('SELECT learned,fresh_after IS NOT NULL FROM public.pr_discord_rate_state WHERE scope_key=%s',(routekey,)).fetchone()==(True,True)
checks.append('ResetAfter countdown needs fresh response headers before another learnedwindow refill')

limiter,identity,path,policy=setup(invalid_capacity=2,egress_scope='synthetic-shared-egress')
send(limiter,identity,path,{'status':403,'headers':{}})
other=SharedPostgresBudget(connection,'600000000000000099',policy=policy)
other_identity=RequestIdentity.make(other.application_id,'user','synthetic-other-user','333333333333333333')
send(other,other_identity,path.replace(path.split('/')[2],'222222222222222222'),{'status':403,'headers':{}})
expect_denied(lambda:other.reserve('GET','/users/@me',identity=other_identity),RateDelayed)
checks.append('invalidrequest breaker is shared across authentication/application scopes on reviewed egress')

for role in ('anon','authenticated'):
    for table in ('pr_discord_rate_state','pr_discord_route_buckets','pr_discord_request_admissions'):
        try:
            with connection() as db:
                db.execute('SET LOCAL ROLE '+role)
                db.execute('SELECT count(*) FROM public.'+table)
        except psycopg.errors.InsufficientPrivilege:pass
        else:raise AssertionError('Customer role accessed shared rate evidence')
with connection() as db:
    flags=db.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s)",
        (['pr_discord_rate_state','pr_discord_route_buckets','pr_discord_request_admissions'],)).fetchall()
    assert len(flags)==3 and all(a and b for _,a,b in flags)
    db.execute('SET LOCAL ROLE service_role')
    assert db.execute('SELECT count(*) FROM public.pr_discord_request_admissions').fetchone()[0]>0
checks.append('3 tables forcedRLS;anon/authenticated denied;trustedservice readable')

# P4 worker path uses the existing real credential/workspace/approval transactions.
with patch('postriff_phase2.billing.require_publishing',return_value=None),patch('postriff_phase2.billing.require_plan_capacity',return_value=None):
    for change in ('none','destination','grant','membership','expiry','foreign-permit',
                   'expired-unsent','expired-revoked','expired-replaced-lease',
                   'sent-recovery-denied','sent-no-ack-recovery-denied','consume-recovery-race','expired-before-seal'):
        f=Fixture();job=f.job();w=PostgresWorker(base['connection'],f.social,worker_id='p4-'+change,discord_workers=True)
        f.social.prepare_discord_dispatch(job['manifest'])
        routes=sorted({urlsplit(url).path.removeprefix('/api/v10') for method,url,_ in f.wire.calls if method=='GET'})
        policy=synthetic_policy(db_now());policy.update(app_capacity=1000,app_window_seconds=60,unknown_window_seconds=10,
            invalid_capacity=100,egress_scope='synthetic-worker')
        coordinator=SharedPostgresBudget(base['connection'],f.provider.client_id,policy=policy)
        ident=RequestIdentity.make(f.provider.client_id,'bot',f.provider.bot_token)
        # Learn mock provider headers, then advance only their synthetic windows.
        learned=set()
        for path in routes:
            template,_major=route_identity('GET',path);bucket='fixture-'+hashlib.sha256(template.encode()).hexdigest()[:16]
            if (template,_major) in learned:continue
            learned.add((template,_major))
            learn(coordinator,ident,path,bucket,100);roll_route(ident,path,bucket)
        original_wire=f.provider.transport
        def rated_wire(method,url,**kwargs):
            result=original_wire(method,url,**kwargs)
            route=urlsplit(url).path.removeprefix('/api/v10');template,_major=route_identity(method,route)
            return {**result,'headers':{'X-RateLimit-Bucket':'fixture-'+hashlib.sha256(template.encode()).hexdigest()[:16],
                'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}}
        f.provider.transport=rated_wire;f.provider.rate_limiter=coordinator;f.provider.rate_v1_enabled=True
        f.wire.calls.clear()
        claimed=w.claim(workspace_id=f.workspace,job_id=job['id'],approval_digest=job['approvalDigest'],dispatch_principal=f.user)
        assert claimed
        claimed['discordPrepared']=f.social.prepare_discord_dispatch(claimed['job']['manifest'])
        claimed['discordPrepared']['ratePermit']=f.social.reserve_discord_send(claimed['job']['manifest'],job=claimed['job'],workspace_id=f.workspace,worker_id=w.worker_id)
        if change=='expired-before-seal':
            time.sleep(max(0,claimed['discordPrepared']['ratePermit'].expires_at-db_now())+.03)
            assert not w.authorize_dispatch(claimed)
            current=prior['job_of'](f)
            assert current['state']=='scheduled' and not current.get('discordDispatchIntents')
            assert current['discordWorker']['ratePermitRetries']==1
            assert not any(call[0]=='POST' for call in f.wire.calls)
            time.sleep(max(0,current['nextAt']-db_now())+.02)
            w.step(workspace_id=f.workspace,job_id=job['id'],approval_digest=job['approvalDigest'],dispatch_principal=f.user,discord_only=True)
            current=prior['job_of'](f)
            assert current['state']=='provider_accepted'
            assert len([call for call in f.wire.calls if call[0]=='POST'])==1
            for key in ('manifest','discordAuthorization','approvalDigest','approvedBy','approvedAt'):assert current[key]==job[key]
            prior['finish_fixture'](f)
            continue
        if change=='foreign-permit':
            from dataclasses import replace
            claimed['discordPrepared']['ratePermit']=replace(claimed['discordPrepared']['ratePermit'],binding_hash='f'*64)
            assert not w.authorize_dispatch(claimed)
        else:
            assert w.authorize_dispatch(claimed)
            if change in ('expired-unsent','expired-revoked','expired-replaced-lease',
                          'sent-recovery-denied','sent-no-ack-recovery-denied','consume-recovery-race'):
                from postriff_phase2.discord.rate_limits import UnconsumedPublishPermit
                rate=claimed['discordPrepared'];create_path='/channels/'+job['manifest']['discord']['target']['channelId']+'/messages'
                if change in ('sent-recovery-denied','sent-no-ack-recovery-denied','consume-recovery-race'):
                    if change=='sent-recovery-denied':
                        accepted=f.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
                        assert accepted['state']=='provider_accepted',accepted
                    elif change=='sent-no-ack-recovery-denied':
                        coordinator.consume(rate['ratePermit'],'POST',create_path,binding=rate['rateBinding'],
                            intent_id=claimed['discordIntent']['id'],authorize=rate['rateAuthorize'])
                    else:
                        waiting=rate['ratePermit'];paused.clear();release.clear();race.clear()
                        consumer=SharedPostgresBudget(paused_connection,f.provider.client_id,policy=policy)
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            consuming=pool.submit(consumer.consume,waiting,'POST',create_path,binding=rate['rateBinding'],
                                intent_id=claimed['discordIntent']['id'],authorize=rate['rateAuthorize'])
                            try:
                                assert paused.wait(3)
                                time.sleep(max(0,waiting.expires_at-db_now())+.03)
                                recovering=pool.submit(expect_denied,lambda:w.release_discord_expired_permit(claimed,
                                    UnconsumedPublishPermit(waiting.id,.05)),AlphaError)
                                blocked=False;deadline=time.monotonic()+1
                                while time.monotonic()<deadline:
                                    with connection() as db:
                                        blocked=db.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND %s=ANY(pg_blocking_pids(pid)))",(race['consumerPid'],)).fetchone()[0]
                                    if blocked:break
                                    time.sleep(.01)
                                assert blocked,'Recovery must wait for consume, not infer unsent from an expired snapshot'
                            finally:release.set()
                            consuming.result(timeout=3);recovering.result(timeout=3)
                    signal=UnconsumedPublishPermit(claimed['discordPrepared']['ratePermit'].id,.05)
                else:
                    time.sleep(max(0,claimed['discordPrepared']['ratePermit'].expires_at-db_now())+.03)
                    try:
                        f.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
                    except UnconsumedPublishPermit as error:signal=error
                    else:raise AssertionError('Expired admission reached transport')
                    assert not any(call[0]=='POST' for call in f.wire.calls)
                    if change=='expired-revoked':
                        with base['connection']() as db:
                            db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=clock_timestamp() WHERE workspace_id=%s AND connection_id=%s AND provider='discord'",(f.workspace,f.connection_id))
                    elif change=='expired-replaced-lease':
                        # A valid newer worker rotates the durable marker with
                        # its lease. A legacy mismatched claim is now DB-denied.
                        marker=copy.deepcopy(prior['job_of'](f)['discordWorker'])
                        marker['leaseId']='synthetic-replaced-lease'
                        prior['change_job'](f,leaseId=marker['leaseId'],discordWorker=marker)
                if change=='expired-unsent':
                    def recover_once():
                        try:return w.release_discord_expired_permit(claimed,signal)
                        except AlphaError:return False
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        assert sorted(pool.map(lambda _:recover_once(),range(2)))==[False,True]
                    current=prior['job_of'](f)
                    assert current['state']=='scheduled' and not current['discordDispatchIntents']
                    assert len(current['discordUnsentDispatches'])==1
                    assert current['discordUnsentDispatches'][0]['id']==claimed['discordIntent']['id']
                    with base['connection']() as db:
                        assert db.execute('SELECT state,sent_at IS NULL FROM public.pr_discord_request_admissions WHERE id=%s::uuid',(signal.permit_id,)).fetchone()==('blocked',True)
                    # A paused old sender cannot consume the now-fenced permit.
                    expect_denied(lambda:coordinator.consume(claimed['discordPrepared']['ratePermit'],'POST',
                        '/channels/'+job['manifest']['discord']['target']['channelId']+'/messages',
                        binding=claimed['discordPrepared']['rateBinding'],intent_id=claimed['discordIntent']['id'],
                        authorize=claimed['discordPrepared']['rateAuthorize']),RateCoordinatorUnavailable)
                    time.sleep(max(0,current['nextAt']-db_now())+.02)
                    w.step(workspace_id=f.workspace,job_id=job['id'],approval_digest=job['approvalDigest'],dispatch_principal=f.user,discord_only=True)
                    current=prior['job_of'](f)
                    assert current['state']=='provider_accepted',current['state']
                    assert len(current['discordUnsentDispatches'])==1 and len(current['discordDispatchIntents'])==1
                    assert current['discordDispatchIntents'][0]['id']!=claimed['discordIntent']['id']
                    assert current['discordWorker']['ratePermitRetries']==1
                else:
                    expect_denied(lambda:w.release_discord_expired_permit(claimed,signal),AlphaError)
                    current=prior['job_of'](f)
                    assert len(current['discordDispatchIntents'])==1 and not current.get('discordUnsentDispatches')
                for key in ('manifest','discordAuthorization','approvalDigest','approvedBy','approvedAt'):
                    assert current[key]==job[key],key
                posts=[call for call in f.wire.calls if call[0]=='POST']
                assert len(posts)==(change in ('expired-unsent','sent-recovery-denied')),(change,len(posts))
                print('RAFII_DISCORD_P4_WORKER_CASE '+json.dumps({'case':change,'status':'PASS','mockPosts':len(posts)}))
                prior['finish_fixture'](f)
                continue
            with base['connection']() as db:
                state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(f.workspace,)).fetchone()[0]
                current=next(j for j in state['phase2']['jobs'] if j['id']==claimed['job']['id'])
                assert current['approvedBy']==f.user
                if change=='destination':
                    connection_record=next(c for c in state['phase2']['channels'] if c['id']==current['manifest']['channelId'])
                    destination_record=next(d for d in connection_record['discordDestinations'] if d['id']==current['manifest']['destinationId'])
                    assert destination_record['channelId']==current['manifest']['discord']['target']['channelId']
                    destination_record['status']='revoked'
                elif change=='grant':
                    changed_grant=db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=clock_timestamp() WHERE workspace_id=%s AND connection_id=%s AND provider='discord'",(f.workspace,f.connection_id))
                    assert changed_grant.rowcount==1,'Exact fixture grant must be revoked'
                elif change=='membership':
                    # Owners retain role authority even with can_publish=false.
                    # Revoke the membership, so the active-member guard must deny.
                    revoked=db.execute("UPDATE public.pr_memberships SET status='revoked',can_publish=false WHERE workspace_id=%s AND user_id=%s RETURNING role,status,can_publish",(f.workspace,f.user)).fetchone()
                    assert revoked==('owner','revoked',False),('membership-fixture',revoked)
                elif change=='expiry':current['leaseUntil']=db_now()-1
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),f.workspace))
            result=f.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
            if change=='none':
                assert result['state']=='provider_accepted',result
                f.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
                # Guard fixtures deliberately share one bot/channel. Advance
                # only this learned synthetic POST window before the later
                # authorization scenarios; these are not capacity measurements.
                create_path='/channels/'+claimed['job']['manifest']['discord']['target']['channelId']+'/messages'
                template,_major=route_identity('POST',create_path)
                roll_route(ident,create_path,'fixture-'+hashlib.sha256(template.encode()).hexdigest()[:16],method='POST')
            else:assert result['state']=='uncertain',(change,result)
        posts=[call for call in f.wire.calls if call[0]=='POST']
        assert len(posts)==(change=='none'),(change,len(posts))
        current=prior['job_of'](f)
        for key in ('manifest','discordAuthorization','approvalDigest','approvedBy','approvedAt'):assert current[key]==job[key]
        assert len(current.get('discordDispatchIntents',[]))==(change!='foreign-permit')
        print('RAFII_DISCORD_P4_WORKER_CASE '+json.dumps({'case':change,'status':'PASS','mockPosts':len(posts),'intents':len(current.get('discordDispatchIntents',[]))}))
        prior['finish_fixture'](f)
checks.append('SQL worker permit+intent atomic;postcommit destination/grant/membership/expiry/forgery guards;onePOST maximum;frozen authority preserved')
checks.append('expired unconsumed permit:old admission fenced,intent archived,same frozen approval resumes;revoked grant and sent admission never reopen')
checks.append('expired reserved permit before intent releases only proven unsent managed job;same frozen approval resumes withonePOST')

# Cold discovery is serialized per authentication + top-level major resource,
# while the reviewed application ceiling still coordinates all replicas.
for label,majorless in (('same-major',False),('majorless',True)):
    limiter,identity,path,policy=setup()
    options=[('GET','/users/@me'),('GET','/oauth2/applications/@me')] if majorless else [
        ('GET',path),('GET','/channels/'+path.split('/')[2]),('POST','/channels/'+path.split('/')[2]+'/messages')]
    barrier=Barrier(16)
    def cold_claim(index):
        replica=SharedPostgresBudget(connection,limiter.application_id,policy=policy)
        barrier.wait(8)
        method,candidate=options[index%len(options)]
        try:return replica.reserve(method,candidate,identity=identity)
        except RateDelayed:return None
    with ThreadPoolExecutor(max_workers=16) as pool:reserved=list(pool.map(cold_claim,range(16)))
    assert sum(item is not None for item in reserved)==1,(label,reserved)
    metrics.append({'case':'cold-discovery-'+label,'replicas':16,'attempted':16,'admitted':1})
checks.append('16 real SQL replicas serialize cold aliases within one auth+major;majorless routes remain grouped')

limiter,identity,path,policy=setup(app_capacity=3)
barrier=Barrier(16)
def independent_cold_claim(index):
    replica=SharedPostgresBudget(connection,limiter.application_id,policy=policy)
    candidate='/channels/'+str(810000000000000000+index)+'/messages/999999999999999999'
    barrier.wait(8)
    try:return replica.reserve('GET',candidate,identity=identity)
    except RateDelayed:return None
with ThreadPoolExecutor(max_workers=16) as pool:reserved=list(pool.map(independent_cold_claim,range(16)))
assert sum(item is not None for item in reserved)==3,'Cold resource independence bypassed shared application budget'
metrics.append({'case':'cold-discovery-independent-majors','replicas':16,'attempted':16,'admitted':3,'applicationSlots':3})
checks.append('16 real SQL cold-resource contenders share exactly3 application slots,without an auth-wide one-probe bottleneck')

limiter,identity,path,policy=setup()
other='/channels/820000000000000001/messages/999999999999999999'
first=limiter.reserve('GET',path,identity=identity);second=limiter.reserve('GET',other,identity=identity)
limiter.consume(first,'GET',path)
limiter.observe(first,{'status':429,'headers':{'X-RateLimit-Scope':'global','Retry-After':'172800.25'},'body':{'global':True}})
try:limiter.consume(second,'GET',other)
except (RateDelayed,RateCoordinatorUnavailable):pass
else:raise AssertionError('Global429 did not stop an independently reserved cold major')
checks.append('global429 blocks outstanding independent-major cold permit across shared SQL;two-day Retry-After retained')

# GET admission can debit and cross the pre-transport authorization boundary
# in one commit. It never admits a mutation or reuses a sent permit.
limiter,identity,path,policy=setup()
permit=limiter.reserve_read('GET',path,identity=identity)
with connection() as db:
    row=db.execute("SELECT state,is_publish,binding_hash,sent_at=reserved_at,sent_at IS NOT NULL FROM public.pr_discord_request_admissions WHERE id=%s",(permit.id,)).fetchone()
    assert row==('sent',False,None,True,True),row
expect_denied(lambda:limiter.consume(permit,'GET',path),RateCoordinatorUnavailable)
expect_denied(lambda:limiter.reserve_read('POST','/channels/'+path.split('/')[2]+'/messages',identity=identity),RateCoordinatorUnavailable)
limiter.note_transport_failure(permit)
with connection() as db:
    db.execute("UPDATE public.pr_discord_rate_state SET reset_at=clock_timestamp()-interval '1 second' WHERE scope_key=ANY(%s::text[]) AND kind='discovery'",([k for k in limiter._keys(identity,_digest(route_identity('GET',path)[0]),route_identity('GET',path)[1],None) if k.startswith('30:')],))
# A transport failure on a READ is resolved at once, as an observed 503 (a read has no effect to be unsure of; commit 6e3ad9af,
# finding A2): its discovery debit does not outlive the reset. A write (a bound create, a nickname PATCH) stays uncertain and
# retains the debit; that half is pinned by test_discord_rate_ceiling_postgres.py and test_discord_rate_limits.py.
assert limiter.reserve_read('GET','/channels/'+path.split('/')[2],identity=identity),'A failed read must not retain its discovery debit'
checks.append('atomic GET admission commits sent state with debit;POST/reuse denied;a failed read is resolved at once and retains no major discovery debit across reset')

limiter,identity,path,policy=setup(unknown_window_seconds=.05,permit_ttl_seconds=.05)
late=LateInsert(connection,limiter.application_id,policy=policy)
expired_read_keys=sorted(limiter._keys(identity,_digest(route_identity('GET',path)[0]),route_identity('GET',path)[1],None))
with connection() as db:
    expired_read_before=db.execute('SELECT * FROM public.pr_discord_rate_state WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key',(expired_read_keys,)).fetchall()
error=expect_denied(lambda:late.reserve_read('GET',path,identity=identity),RateDelayed)
assert error.rate_cause=='permit_expired'
with connection() as db:
    assert db.execute('SELECT * FROM public.pr_discord_rate_state WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key',(expired_read_keys,)).fetchall()==expired_read_before
    assert db.execute('SELECT count(*) FROM public.pr_discord_request_admissions WHERE application_key=%s',(_digest(limiter.application_id),)).fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM public.pr_discord_route_buckets WHERE auth_key=%s',(identity.auth_key,)).fetchone()[0]==0
checks.append('late atomic GET insert rolls back admission,mapping and every debit before any provider request')

limiter,identity,path,policy=setup(app_capacity=3)
barrier=Barrier(16)
def fast_cold_claim(index):
    replica=SharedPostgresBudget(connection,limiter.application_id,policy=policy)
    barrier.wait(8)
    try:return replica.reserve_read('GET','/channels/'+str(830000000000000000+index),identity=identity)
    except RateDelayed:return None
with ThreadPoolExecutor(max_workers=16) as pool:reserved=list(pool.map(fast_cold_claim,range(16)))
assert sum(p is not None for p in reserved)==3,'Atomic GET admission bypassed shared application limit'
checks.append('16 atomic GET contenders across independent majors admit exactly3 shared application slots')

limiter,identity,path,policy=setup()
learn(limiter,identity,path,cap=6)
sent=limiter.reserve_read('GET',path,identity=identity)
waiting=limiter.reserve('GET',path,identity=identity)
limiter.observe(sent,{'status':200,'headers':{'X-RateLimit-Bucket':'synthetic-bucket',
    'X-RateLimit-Limit':'2','X-RateLimit-Remaining':'1','X-RateLimit-Reset-After':'30'}})
_,major=route_identity('GET',path)
alias='50:'+_digest(identity.auth_key+':'+_digest('synthetic-bucket')+':'+major)
with connection() as db:
    assert db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',(alias,)).fetchone()[0]==0
    assert db.execute('SELECT state FROM public.pr_discord_request_admissions WHERE id=%s',(waiting.id,)).fetchone()[0]=='reserved'
expect_denied(lambda:limiter.reserve_read('GET',path,identity=identity),RateDelayed)
checks.append('stable learned bucket tightening retains other reserved debit;reported remaining1 cannot expose an extra shared slot')

def coordinator_snapshot(limiter,identity,path,extra=()):
    template,major=route_identity('GET',path)
    keys=set(limiter._keys(identity,_digest(template),major,None))|set(extra)
    with connection() as db:
        admissions=db.execute('SELECT * FROM public.pr_discord_request_admissions WHERE application_key=%s ORDER BY request_seq',(_digest(limiter.application_id),)).fetchall()
        for row in db.execute('SELECT scope_keys FROM public.pr_discord_request_admissions WHERE application_key=%s',(_digest(limiter.application_id),)):
            keys.update(row[0])
        return (db.execute('SELECT * FROM public.pr_discord_rate_state WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key',(sorted(keys),)).fetchall(),
            db.execute('SELECT * FROM public.pr_discord_route_buckets WHERE auth_key=%s ORDER BY route_key,major_key',(identity.auth_key,)).fetchall(),admissions)

# Delay inside the actual scope UPDATE. The frozen permit clock must be
# checked after storage before admission INSERT; suppressed rows roll back.
for suppress in (False,True):
    limiter,identity,path,policy=setup(unknown_window_seconds=.05,permit_ttl_seconds=.05)
    before=coordinator_snapshot(limiter,identity,path)
    with connection() as db:
        db.execute("""CREATE FUNCTION public.pr_discord_test_scope_write() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.scope_key=TG_ARGV[0] THEN
                IF TG_ARGV[1]='suppress' THEN RETURN NULL; END IF;
                PERFORM pg_sleep(.08);
            END IF; RETURN NEW; END $$""")
        from psycopg import sql
        db.execute(sql.SQL('CREATE TRIGGER pr_discord_test_scope_write BEFORE UPDATE ON public.pr_discord_rate_state FOR EACH ROW EXECUTE FUNCTION public.pr_discord_test_scope_write({},{})').format(
            sql.Literal('00:'+_digest(limiter.application_id)),sql.Literal('suppress' if suppress else 'delay')))
    try:
        if suppress:
            expect_denied(lambda:limiter.reserve_read('GET',path,identity=identity),RateCoordinatorUnavailable)
            assert coordinator_snapshot(limiter,identity,path)==before,'Storage failure committed a debit,mapping or admission'
        else:
            # The scope UPDATE and the admission INSERT are ONE statement and its clock is read before the UPDATE runs, so a slow
            # UPDATE no longer refuses the INSERT; the frozen expiry still ends the permit at its use: nothing can be sent with it.
            permit=limiter.reserve('GET',path,identity=identity)
            error=expect_denied(lambda:limiter.consume(permit,'GET',path),RateDelayed)
            assert error.rate_cause=='permit_expired',error.rate_cause   # consume() names no scope for an expired permit
    finally:
        with connection() as db:
            db.execute('DROP TRIGGER pr_discord_test_scope_write ON public.pr_discord_rate_state')
            db.execute('DROP FUNCTION public.pr_discord_test_scope_write()')
checks.append('real UPDATE trigger delay inside the combined statement:permit is admitted but dead at use(consume refuses permit_expired);missing UPDATE row fails closed and rolls back scopes,mapping,admission')

# Stable reservation reads every guard under the same locks but must not create
# new heap/index versions for unchanged guards. Renewals and holds still apply.
limiter,identity,path,policy=setup()
learn(limiter,identity,path,cap=100)
guard_keys=['10:'+identity.auth_key,'11:'+identity.credential_key,'40:'+route_identity('GET',path)[1]]
def guard_versions():
    with connection() as db:
        return db.execute('SELECT scope_key,revision,updated_at,policy_revision,policy_expires_at FROM public.pr_discord_rate_state WHERE scope_key=ANY(%s::text[]) ORDER BY scope_key',(guard_keys,)).fetchall()
before=guard_versions()
limiter.reserve_read('GET',path,identity=identity)
assert guard_versions()==before,'Unchanged guard versions were rewritten'
from postriff_phase2.discord.rate_limits import SafetyPolicy
renewed={**policy,'revision':'synthetic-scope-renewal','expires_at':policy['expires_at']+1}
limiter.policy=SafetyPolicy.parse(renewed)
limiter.reserve_read('GET',path,identity=identity)
after=guard_versions()
assert all(new[1]==old[1]+1 and new[3]=='synthetic-scope-renewal' and new[4]>old[4] for old,new in zip(before,after))
with connection() as db:
    db.execute('UPDATE public.pr_discord_rate_state SET manual_hold=true WHERE scope_key=%s',(guard_keys[0],))
before=coordinator_snapshot(limiter,identity,path)
# A hold is a wait for a read (a read has no effect to be unsure of) and a refusal for anything that is reserved to be used later.
error=expect_denied(lambda:limiter.reserve_read('GET',path,identity=identity),RateDelayed)
assert error.rate_cause=='hold',error.rate_cause
expect_denied(lambda:limiter.reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
assert coordinator_snapshot(limiter,identity,path)==before,'Guard hold bypassed or committed a reservation'
checks[-1]+=';unchanged guard versions retained,policy renewal stored,held guard blocks without writes'

limiter,identity,path,policy=setup()
learn(limiter,identity,path,cap=6)
sent=limiter.reserve_read('GET',path,identity=identity)
waiting=limiter.reserve('GET',path,identity=identity)
limiter.observe(sent,{'status':429,'headers':{'X-RateLimit-Bucket':'batch-embargo-alias','X-RateLimit-Scope':'user',
    'Retry-After':'.2'},'body':{'retry_after':.2,'global':False}})
_,major=route_identity('GET',path)
alias='50:'+_digest(identity.auth_key+':'+_digest('batch-embargo-alias')+':'+major)
with connection() as db:
    own=db.execute('SELECT state,scope_keys FROM public.pr_discord_request_admissions WHERE id=%s',(sent.id,)).fetchone()
    other=db.execute('SELECT state,scope_keys FROM public.pr_discord_request_admissions WHERE id=%s',(waiting.id,)).fetchone()
    assert own[0]=='observed' and own[1].count(alias)==1
    assert other[0]=='blocked' and other[1].count(alias)==1
checks.append('alias propagation adds each scope once;subsequent429 embargo blocks unused permit and preserves observed receipt')

# Successful learned GET observers share unchanged common guards. Real SQL
# overlap is proved with both transactions paused AFTER all scope locks.
limiter,identity,path,policy=setup(permit_ttl_seconds=10)
paths=[path,'/channels/850000000000000001/messages/999999999999999999']
for target in paths:learn(limiter,identity,target,cap=100)
permits=[limiter.reserve_read('GET',target,identity=identity) for target in paths]
response={'status':200,'headers':{'X-RateLimit-Bucket':'synthetic-bucket',
    'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'98','X-RateLimit-Reset-After':'30'}}
shared_ready=Barrier(3);shared_release=Event();forward_entered=Event();observer_pids=[]
class SharedPaused(SharedPostgresBudget):
    def _locked(self,cur,keys,*,shared_keys=()):
        rows=super()._locked(cur,keys,shared_keys=shared_keys)
        assert shared_keys,'Warm success unexpectedly used exclusive locks'
        observer_pids.append(cur.connection.info.backend_pid)
        shared_ready.wait(3)
        if not shared_release.wait(3):raise AssertionError('Shared observation release timed out')
        return rows
class ForwardTracked(SharedPostgresBudget):
    def _locked(self,cur,keys,**kwargs):
        forward_entered.set()
        return super()._locked(cur,keys,**kwargs)
with connection() as db:
    app_before=db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',
        ('00:'+limiter.application_key,)).fetchone()[0]
with ThreadPoolExecutor(max_workers=3) as pool:
    observing=[pool.submit(SharedPaused(connection,limiter.application_id,policy=policy).observe,p,response) for p in permits]
    forward=None
    try:
        shared_ready.wait(3)
        assert len(set(observer_pids))==2,'Two real PostgreSQL sessions must overlap'
        forward=pool.submit(ForwardTracked(connection,limiter.application_id,policy=policy).reserve_read,
            'GET','/channels/850000000000000002',identity=identity)
        assert forward_entered.wait(1)
        blocked=False;deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            with connection() as db:
                blocked=db.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' "
                    'AND pg_blocking_pids(pid)&&%s::integer[])',(observer_pids,)).fetchone()[0]
            if blocked:break
            time.sleep(.01)
        assert blocked and not forward.done(),'Reservation bypassed retained common SHARE guards'
    finally:shared_release.set()
    for future in observing:future.result(timeout=3)
    assert forward is not None;forward.result(timeout=3)
with connection() as db:
    assert db.execute('SELECT remaining FROM public.pr_discord_rate_state WHERE scope_key=%s',
        ('00:'+limiter.application_key,)).fetchone()[0]==app_before-1,'Observations refunded application credit'
checks.append('two learnedGET observers overlap actual commonSHARE locks;forward reservation waits on them and debits exactly once')

# Reviewer counterexample: expired C(discoveryD,H2), later uncertain X(H1,H2).
# A holds D+H1 and B holds H2. A must retain app00 exclusive, preventing the
# historical alias/discovery admission locks from creating A-X-B-C-A.
limiter,identity,path,policy=setup(permit_ttl_seconds=10)
learn(limiter,identity,path,bucket='history-h2',cap=100)
b=limiter.reserve_read('GET',path,identity=identity)
a_path=path.rsplit('/',1)[0]
a=limiter.reserve_read('GET',a_path,identity=identity)
_,major=route_identity('GET',path)
h1='50:'+_digest(identity.auth_key+':'+_digest('history-h1')+':'+major)
h2='50:'+_digest(identity.auth_key+':'+_digest('history-h2')+':'+major)
d='30:'+_digest(identity.auth_key+':'+major)
with connection() as db:
    c=db.execute("INSERT INTO public.pr_discord_request_admissions(id,application_key,auth_key,credential_key,credential_kind,"
        "method,path_key,route_key,major_key,bucket_key,scope_keys,reserved_at,expires_at,state) "
        "SELECT gen_random_uuid(),application_key,auth_key,credential_key,credential_kind,method,path_key,route_key,major_key,"
        "bucket_key,scope_keys||ARRAY[%s,%s]::text[],clock_timestamp()-interval '2 seconds',clock_timestamp()-interval '1 second','reserved' "
        'FROM public.pr_discord_request_admissions WHERE id=%s RETURNING id',(d,h2,b.id)).fetchone()[0]
    x=db.execute("INSERT INTO public.pr_discord_request_admissions(id,application_key,auth_key,credential_key,credential_kind,"
        "method,path_key,route_key,major_key,bucket_key,scope_keys,reserved_at,expires_at,state) "
        "SELECT gen_random_uuid(),application_key,auth_key,credential_key,credential_kind,method,path_key,route_key,major_key,"
        "bucket_key,scope_keys||ARRAY[%s]::text[],clock_timestamp()-interval '2 seconds',clock_timestamp()-interval '1 second','uncertain' "
        'FROM public.pr_discord_request_admissions WHERE id=%s RETURNING id',(h1,b.id)).fetchone()[0]
entered,release=Event(),Event();a_shared=[]
class HistoricalPaused(SharedPostgresBudget):
    def _locked(self,cur,keys,*,shared_keys=()):
        rows=super()._locked(cur,keys,shared_keys=shared_keys)
        a_shared.append(bool(shared_keys));entered.set()
        if not release.wait(3):raise AssertionError('Historical observation release timed out')
        return rows
with ThreadPoolExecutor(max_workers=2) as pool:
    first=pool.submit(HistoricalPaused(connection,limiter.application_id,policy=policy).observe,a,
        {'status':200,'headers':{'X-RateLimit-Bucket':'history-h1','X-RateLimit-Limit':'100',
            'X-RateLimit-Remaining':'97','X-RateLimit-Reset-After':'30'}})
    second=None
    try:
        assert entered.wait(2) and a_shared==[False],'Discovery-bearing observer must retain app00 UPDATE'
        second=pool.submit(limiter.observe,b,{'status':200,'headers':{'X-RateLimit-Bucket':'history-h2',
            'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'97','X-RateLimit-Reset-After':'30'}})
        time.sleep(.05);assert not second.done()
    finally:release.set()
    first.result(timeout=3);assert second is not None;second.result(timeout=3)
with connection() as db:
    states=dict(db.execute('SELECT id::text,state FROM public.pr_discord_request_admissions WHERE id=ANY(%s::uuid[])',
        ([str(c),str(x),a.id,b.id],)).fetchall())
    assert states[str(c)]=='reserved' and states[str(x)]=='uncertain'
    assert states[a.id]==states[b.id]=='observed'
checks.append('historical expiredC(discoveryD,H2)+uncertainX(H1,H2) concurrent observations finish without deadlock;discovery stays exclusive,uncertainty retained')

# Real held-guard and malformed-hint fallback must rollback before acquiring
# the full exclusive set. Record lock mode, never secret/provider data.
for scenario in ('global-hold','route-circuit','bad-hint'):
    limiter,identity,path,policy=setup(permit_ttl_seconds=10)
    learn(limiter,identity,path,cap=100)
    sent=limiter.reserve_read('GET',path,identity=identity)
    waiting=limiter.reserve('GET',path,identity=identity)
    if scenario!='bad-hint':
        with connection() as db:
            if scenario=='global-hold':db.execute('UPDATE public.pr_discord_rate_state SET manual_hold=true WHERE scope_key=%s',('10:'+identity.auth_key,))
            else:db.execute("UPDATE public.pr_discord_rate_state SET circuit_until=clock_timestamp()+interval '30 seconds' WHERE scope_key=%s",(next(k for k in limiter._keys(identity,_digest(route_identity('GET',path)[0]),route_identity('GET',path)[1],_digest('synthetic-bucket')) if k.startswith('50:')),))
    modes=[]
    class FallbackTracked(SharedPostgresBudget):
        def _locked(self,cur,keys,*,shared_keys=()):
            modes.append(bool(shared_keys));return super()._locked(cur,keys,shared_keys=shared_keys)
    result_response=copy.deepcopy(response)
    if scenario=='bad-hint':result_response['headers']['X-RateLimit-Remaining']='malformed'
    FallbackTracked(connection,limiter.application_id,policy=policy).observe(sent,result_response)
    assert modes==[True,False],(scenario,modes)
    with connection() as db:
        assert db.execute('SELECT state FROM public.pr_discord_request_admissions WHERE id=%s',(waiting.id,)).fetchone()[0]=='blocked'
checks.append('realSQL globalhold/routecircuit/malformedhint shared attempt fully rolls back then exclusive retry preserves hold and fences unused permits')

# One common 60000-record observed history is retained across paired cases.
# The test-only reference disables sharing, leaving every production debit,
# pending count and transaction boundary identical. No real provider requests.
observer_comparison=[]
limiter,identity,path,policy=setup(app_capacity=100000,app_window_seconds=600,permit_ttl_seconds=10)
bench_pool=PooledPostgresFactory(DSN,max_size=12,max_waiting=32,timeout=8,
    options='-c statement_timeout=10000 -c lock_timeout=5000')
class ExclusiveObserver(SharedPostgresBudget):
    @staticmethod
    def _share_get_observation(*args):return False
warm_paths=['/channels/'+str(860000000000000000+i)+'/messages/999999999999999999' for i in range(8)]
bench_response={'status':200,'headers':{'X-RateLimit-Bucket':'shared-bench','X-RateLimit-Limit':'100000',
    'X-RateLimit-Remaining':'99999','X-RateLimit-Reset-After':'600'}}
try:
    measured=SharedPostgresBudget(bench_pool,limiter.application_id,policy=policy)
    for target in warm_paths:
        p=measured.reserve_read('GET',target,identity=identity);measured.observe(p,bench_response)
    with connection() as db:
        db.execute("INSERT INTO public.pr_discord_request_admissions(id,application_key,auth_key,credential_key,credential_kind,"
            "method,path_key,route_key,major_key,bucket_key,scope_keys,reserved_at,expires_at,state,status_code,outcome_at) "
            "SELECT md5(%s||i::text)::uuid,application_key,auth_key,credential_key,credential_kind,method,path_key,route_key,major_key,"
            "bucket_key,scope_keys,reserved_at,expires_at,'observed',200,clock_timestamp() "
            'FROM public.pr_discord_request_admissions CROSS JOIN generate_series(1,60000) AS history(i) WHERE id=%s',
            (limiter.application_id,p.id))
    for temperature in ('warm','cold'):
        for mode,kind in (('exclusive-reference',ExclusiveObserver),('shared-candidate',SharedPostgresBudget)):
            replicas=[kind(bench_pool,limiter.application_id,policy=policy) for _ in range(8)]
            ready=Barrier(8)
            def observed_reads(index):
                ready.wait(8)
                for number in range(128):
                    target=warm_paths[index] if temperature=='warm' else '/channels/'+str(870000000000000000+(0 if mode=='exclusive-reference' else 10000)+index*128+number)
                    p=replicas[index].reserve_read('GET',target,identity=identity)
                    replicas[index].observe(p,bench_response)
            began=time.monotonic()
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(observed_reads,range(8)))
            elapsed=time.monotonic()-began
            observer_comparison.append({'mode':mode,'temperature':temperature,'replicas':8,'getRequests':1024,
                'observedHistory':60000,'elapsedSeconds':elapsed,'requestsPerSecond':1024/elapsed,'httpRequests':0})
finally:bench_pool.close()
metrics.append({'case':'shared-get-observation-paired-history','results':observer_comparison,
    'meaning':'bounded coordinator comparison;not1000user capacity or Discord acceptance'})
checks.append('same60000observedhistory warm/cold8replica1024GET reference/candidate comparison completes with unchanged production safety math')

# Bounded synthetic coordinator comparison,not capacity/provider acceptance.
# Same learned routes,8replicas,256GETs per mode and no HTTP. Record timings;
# exact transaction counts prove the removed phase independently of timing noise.
read_bench=[]
for mode in ('reserve-then-consume','atomic-read'):
    limiter,identity,path,policy=setup(app_capacity=100000)
    pool=PooledPostgresFactory(DSN,max_size=12,max_waiting=32,timeout=8,
        options='-c statement_timeout=10000 -c lock_timeout=5000')
    transaction_count=[0];counter_lock=Lock()
    @contextmanager
    def counted_connection():
        with counter_lock:transaction_count[0]+=1
        with pool() as db:yield db
    measured=SharedPostgresBudget(counted_connection,limiter.application_id,policy=policy)
    paths=['/channels/'+str(840000000000000000+i)+'/messages/999999999999999999' for i in range(8)]
    headers={'X-RateLimit-Bucket':'synthetic-read-bench','X-RateLimit-Limit':'10000','X-RateLimit-Remaining':'9999','X-RateLimit-Reset-After':'60'}
    try:
        for candidate in paths:
            p=measured.reserve('GET',candidate,identity=identity);measured.consume(p,'GET',candidate);measured.observe(p,{'status':200,'headers':headers})
        transaction_count[0]=0;ready=Barrier(8)
        def reads(index):
            ready.wait(8)
            for _ in range(32):
                if mode=='atomic-read':p=measured.reserve_read('GET',paths[index],identity=identity)
                else:
                    p=measured.reserve('GET',paths[index],identity=identity);measured.consume(p,'GET',paths[index])
                measured.observe(p,{'status':200,'headers':headers})
        began=time.monotonic()
        with ThreadPoolExecutor(max_workers=8) as executor:list(executor.map(reads,range(8)))
        elapsed=time.monotonic()-began
        expected=256*(2 if mode=='atomic-read' else 3)
        assert transaction_count[0]==expected,(mode,transaction_count[0],expected)
        read_bench.append({'mode':mode,'replicas':8,'getRequests':256,'databaseTransactions':transaction_count[0],
            'elapsedSeconds':elapsed,'requestsPerSecond':256/elapsed,'httpRequests':0,'capacityAcceptance':'NOT_RUN'})
    finally:pool.close()
metrics.append({'case':'atomic-get-transaction-comparison','results':read_bench,
    'speedRatio':read_bench[0]['elapsedSeconds']/read_bench[1]['elapsedSeconds'],'meaning':'bounded coordinator timing only;not1000user capacity'})
checks.append('bounded8replica256GET comparison:existing3transactions/request versus atomic2,with observation and no HTTP')

result={'status':'PASS','execution':'owned-cloud-PG17-synthetic',
    'workerChecks':prior['checks'],'exactScopedDispatchRegression':any(x.startswith('scoped claim selects only requested job;') for x in prior['checks']),
    'checks':checks,'coordinationMetrics':metrics,'elapsedSeconds':time.monotonic()-started,
    'targets':{'unauthorizedPosts':0,'automaticDuplicateCreates':0,'learnedSlots':3,'maxContentionSeconds':8},
    'realDiscordRequests':0,'productionDatabaseWrites':0,'stage1000Users':'NOT_RUN','stage10000Users':'NOT_RUN'}
# The owned runner keeps only the last4000stdout characters. Preserve the full
# safe aggregate for chunked cloud recovery instead of losing regression groups.
evidence_path=TASK_ROOT/'.depot/discord-p4-coordinator-results.json'
evidence_path.parent.mkdir(exist_ok=True)
evidence_path.write_text(json.dumps(result,sort_keys=True)+'\n')
print('RAFII_DISCORD_P4_SQL_JSON '+json.dumps(result))
