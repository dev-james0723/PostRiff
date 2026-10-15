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
from threading import Barrier,Event
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
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_discord_route_buckets WHERE auth_key=%s',
        (identity.auth_key,)).fetchone()[0]==1
checks.append('combined local timeouts preserved;existing/cold locked mapping has one durable row')

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
    expect_denied(lambda:faulty.reserve('GET',path,identity=identity),RateCoordinatorUnavailable)
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

limiter,identity,path,policy=setup(unknown_window_seconds=.05)
class LateInsert(SharedPostgresBudget):
    def _insert(self,cur,*args):
        cur.execute('SELECT pg_sleep(.08)')  # deterministic owned-DB timing, no real API
        return super()._insert(cur,*args)
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
    for change in ('none','destination','grant','membership','expiry','foreign-permit'):
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
        if change=='foreign-permit':
            from dataclasses import replace
            claimed['discordPrepared']['ratePermit']=replace(claimed['discordPrepared']['ratePermit'],binding_hash='f'*64)
            assert not w.authorize_dispatch(claimed)
        else:
            assert w.authorize_dispatch(claimed)
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

result={'status':'PASS','execution':'owned-cloud-PG17-synthetic',
    'checks':checks,'coordinationMetrics':metrics,'elapsedSeconds':time.monotonic()-started,
    'targets':{'unauthorizedPosts':0,'automaticDuplicateCreates':0,'learnedSlots':3,'maxContentionSeconds':8},
    'realDiscordRequests':0,'productionDatabaseWrites':0,'stage1000Users':'NOT_RUN','stage10000Users':'NOT_RUN'}
# The owned runner keeps only the last4000stdout characters. Preserve the full
# safe aggregate for chunked cloud recovery instead of losing regression groups.
evidence_path=TASK_ROOT/'.depot/discord-p4-coordinator-results.json'
evidence_path.parent.mkdir(exist_ok=True)
evidence_path.write_text(json.dumps(result,sort_keys=True)+'\n')
print('RAFII_DISCORD_P4_SQL_JSON '+json.dumps(result))
