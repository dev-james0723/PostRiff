"""Real disposable PostgreSQL acceptance for migration040. All sources and costs are synthetic.

Run after tests/phase2/rls.sql (or 001). Applies040 when absent. Requires explicit
loopback TREND_TEST_DSN or the existing disposable runner's POSTRIFF_TEST_DSN,
never POSTRIFF_DATABASE_URL. A distinct non-bypass role proves non-owner RLS.
"""
from __future__ import annotations
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
import psycopg
from psycopg.conninfo import conninfo_to_dict
from postriff_phase2.growth.trends.contracts import SCHEMA_VERSION,PERMISSIONS,digest,iso
from postriff_phase2.growth.trends.store import TrendStore,TrendStorageError,identity_digest
from postriff_phase2.growth.trends.jobs import TrendJobs,partition_key
from postriff_phase2.growth.trends.outbox import TrendOutbox
from postriff_phase2.growth.trends import revocation,retention,source_health,operations

DSN=os.environ.get('TREND_TEST_DSN') or os.environ.get('POSTRIFF_TEST_DSN','')
params=conninfo_to_dict(DSN)
if (params.get('host') not in ('127.0.0.1','localhost','::1') or not params.get('port','').isdigit()
    or not (params.get('dbname','').startswith('trend_') or (os.environ.get('POSTRIFF_TEST_DSN')==DSN and params.get('dbname')=='postgres'))):
    raise SystemExit('Explicit loopback disposable test DSN required')
PG=Path(os.environ.get('POSTRIFF_PG_BIN','/opt/homebrew/opt/postgresql@17/bin'))
PGARGS=['-h',params['host'],'-p',params['port']]
if params.get('user'):PGARGS+=['-U',params['user']]
TEST_ROLE='trend_fixture_'+uuid.uuid4().hex[:12]
NOW=datetime.now(timezone.utc)
PAST=iso(NOW-timedelta(hours=1)); START=iso(NOW-timedelta(days=1)); END=iso(NOW+timedelta(days=5))
CUT=iso(NOW-timedelta(minutes=5)); AT=iso(NOW-timedelta(minutes=10)); FUTURE=iso(NOW+timedelta(days=1))
A=str(uuid.uuid4()); B=str(uuid.uuid4()); W=str(uuid.uuid4()); V=str(uuid.uuid4())
S='shared:trend-fixture-'+uuid.uuid4().hex[:10]; WS='workspace:'+W; VS='workspace:'+V
PROVIDER='fixture-'+uuid.uuid4().hex[:8]
checks=[]

def check(label,condition):
    assert condition,label
    checks.append(label); print('PASS',label,flush=True)

def denied(fn,label):
    try:fn()
    except (TrendStorageError,psycopg.Error,ValueError):check(label,True)
    else:raise AssertionError(label)

with psycopg.connect(DSN) as db:
    if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
        db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    db.execute('CREATE ROLE '+TEST_ROLE+' NOSUPERUSER NOBYPASSRLS INHERIT')
    db.execute('GRANT service_role TO '+TEST_ROLE)
    # Existing tenancy predates this migration and relies on Supabase's bypass role.
    # Give only those base tables an explicit test SELECT policy so the NEW tables
    # are exercised with FORCE RLS and a non-owner, non-bypass writer.
    for table in ('pr_workspaces','pr_memberships','pr_profiles'):
        db.execute('CREATE POLICY trend_fixture_service_select ON '+table+' FOR ALL TO service_role USING(true) WITH CHECK(true)')
    for actor in (A,B):
        db.execute('INSERT INTO auth.users(id) VALUES(%s)',(actor,))
        db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(actor,))
    for wid,actor in ((W,A),(V,B)):
        db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)',(wid,))
        db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(wid,actor))


def connect(dsn=DSN):
    db=psycopg.connect(dsn)
    db.execute('SET ROLE '+TEST_ROLE)
    return db

store=TrendStore(connect,offline_replay=True); jobs=TrendJobs(store); outbox=TrendOutbox(store)
for s in (S,WS,VS):store.ensure_scope(s)
store.grant_entitlement(W,S,['retrieve','derive_metrics','share_across_workspaces'],END)
store.register_contract(PROVIDER,'v1',list(PERMISSIONS),START,END,{})


def rights(s,denied_ops=()):
    return {p:{'state':'deny' if p in denied_ops else 'allow','policy_ref':'fixture-v1','audience_scope':s,'expires_at':END} for p in PERMISSIONS}

for s in (S,WS,VS):
    store.register_policy({'scope_key':s,'provider_id':PROVIDER,'version':'v1','rights':rights(s),
        'effective_at':START,'expires_at':END,'retention_seconds':5*86400,'readiness':'ready'},provider_contract_version='v1')


def obs(n,*,s=S,revision=1,kind='raw_post',author='did:fixture:author'):
    payload={'platform':'bluesky','native_id':'post-'+str(n),'author_status':'known','author_key':author,'text':'Synthetic source '+str(n),'canonical_url':'https://fixture.invalid/'+str(n),'language':'en'}
    if kind=='aggregate_metric':
        payload={'dataset_id':'query-a','metric_definition':'count-v1','unit':'posts','population':'known sample',
            'aggregation_semantics':'disjoint','window_start':PAST,'window_end':AT,'value':None,'null_reason':'provider_unavailable'}
    return {'observation_id':str(uuid.uuid4()),'scope_key':s,'provider_id':PROVIDER,'provider_contract_version':'v1',
        'source_policy_version':'v1','source_identity':'source-'+str(n),'revision_identity':'r'+str(revision),'revision_sequence':revision,
        'kind':kind,'operation':'create' if revision==1 else 'update','event_at':PAST,'received_at':AT,'available_at':AT,
        'time_basis':'provider_event','coverage_epoch':'epoch1','provenance':{'access_method':'fixture'},'retention_until':FUTURE,
        'rights':rights(s),'deletion_key':'source-'+str(n),'payload':payload,'payload_digest':digest(payload),'schema_version':SCHEMA_VERSION}

base=obs(1); saved=store.put_observation(base)
check('real non-owner service role writes under forced RLS',saved['inserted'])
check('duplicate source revision idempotent',not store.put_observation(base)['inserted'])
collision=copy.deepcopy(base);collision['payload']['text']='tampered';collision['payload_digest']=digest(collision['payload'])
denied(lambda:store.put_observation(collision),'immutable source identity collision rejected')
other=obs(2);other['payload']['text']=base['payload']['text'];other['payload_digest']=digest(other['payload'])
check('same text separate native identities retained',store.put_observation(other)['inserted'])
aggregate=obs(3,kind='aggregate_metric');store.put_observation(aggregate)
with connect() as db:
    r=db.execute('SELECT metric_value,metric_null_reason,native_item_id,author_key FROM pr_trend_observations WHERE observation_id=%s',(aggregate['observation_id'],)).fetchone()
check('typed aggregate unknown remains NULL without synthetic posts',r==(None,'provider_unavailable',None,None))
newer=obs(1,revision=3);older=obs(1,revision=2);store.put_observation(newer);store.put_observation(older)
with connect() as db:r=db.execute('SELECT revision_sequence FROM pr_trend_source_heads WHERE scope_key=%s AND provider_id=%s AND source_identity_digest=%s',(S,PROVIDER,identity_digest('source-1'))).fetchone()
check('out-of-order backfill cannot replace newer head',r[0]==3)

method='fixture-math-'+uuid.uuid4().hex[:8]; artifact=digest({'algorithm':'fixture'})
store.put_method(method,'v1',artifact,{'algorithm':'fixture'})
manifest=store.put_manifest(S,[{'scope_key':S,'node_id':base['observation_id']}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE)
obj=str(uuid.uuid4())
projection={'scope_key':S,'kind':'trend','object_id':obj,'revision':1,'manifest_id':manifest['manifest_id'],
    'method_id':method,'method_version':'v1','decision_cutoff':CUT,'available_at':CUT,'retention_until':FUTURE,
    'payload':{'id':obj,'canonical_topic':'Synthetic culture','platform':'bluesky','language':'en','stage':'emerging','region':'unknown','niche':'music'}}
store.put_projection(projection)
check('projection revision replay returns same durable identity',store.put_projection(projection)==store.put_projection(projection))
denied(lambda:store.put_projection({**projection,'payload':{'canonical_topic':'conflicting'}}),'projection revision cannot change payload on replay')
denied(lambda:store.put_projection({**projection,'revision':3},expected_revision=2),'optimistic projection append rejects stale head')
check('shared projection requires explicit entitlement',store.get_projection(W,A,'trend',obj)['validity']=='valid')
check('other workspace cannot guess shared object',store.get_projection(V,B,'trend',obj) is None)
denied(lambda:store.get_projection(W,B,'trend',obj),'foreign actor rejected even on service connection')
with psycopg.connect(DSN) as db:
    db.execute('SET LOCAL ROLE authenticated');db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)",(A,))
    try:db.execute('SELECT * FROM pr_trend_observations');allowed=True
    except psycopg.errors.InsufficientPrivilege:allowed=False
check('authenticated role cannot enumerate raw observations',not allowed)
with psycopg.connect(DSN) as db:
    db.execute('SET LOCAL ROLE authenticated')
    try:db.execute('SELECT * FROM pr_trend_projections');allowed=True
    except psycopg.errors.InsufficientPrivilege:allowed=False
check('direct browser projection cannot bypass display redaction',not allowed)
private=obs(10,s=VS);store.put_observation(private)
denied(lambda:store.put_manifest(WS,[{'scope_key':VS,'node_id':private['observation_id']}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE),'cross-workspace dependency trigger blocks worker')
denied(lambda:store.add_dependency(S,base['observation_id'],S,manifest['manifest_id']),'dependency cycle rejected')
with connect() as db:
    try:db.execute('INSERT INTO pr_trend_source_heads(scope_key,provider_id,source_identity_digest,revision_sequence,observation_id) VALUES(%s,%s,%s,1,%s)',(VS,PROVIDER,'x',base['observation_id']));allowed=True
    except psycopg.errors.ForeignKeyViolation:allowed=False
check('composite scope foreign key rejects foreign observation',not allowed)

# Snapshot keyset and latest-known revision semantics.
second=str(uuid.uuid4());store.put_projection({**projection,'object_id':second,'payload':{**projection['payload'],'id':second}})
page=store.list_projections(W,A,limit=1,as_of=iso(NOW),filters={'platforms':['bluesky'],'languages':['en'],'query':'Synthetic','since':PAST})
page2=store.list_projections(W,A,limit=1,before=page['next_key'],as_of=page['as_of'])
check('stable keyset yields distinct pages',len(page['items'])==len(page2['items'])==1 and page['items'][0]['object_id']!=page2['items'][0]['object_id'])
store.put_projection({**projection,'revision':2,'available_at':iso(NOW+timedelta(hours=1))})
check('as-of read retains latest revision known at cutoff',store.get_projection(W,A,'trend',obj,as_of=iso(NOW))['revision']==1)

# Atomic independent budget races, unknown exposure, exact settlement.
keys=['system-'+uuid.uuid4().hex,'provider-'+uuid.uuid4().hex]
for key,dimension in zip(keys,['system','provider']):jobs.configure_budget(key,dimension,100,START,END)
barrier=threading.Barrier(2)
def reserve_race(i):
    barrier.wait()
    try:return jobs.reserve(S,'race-'+str(i),str(uuid.uuid4()),70,keys)
    except TrendStorageError:return None
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve_race,(1,2)))
check('concurrent multidimensional last-budget race permits one',sum(x is not None for x in results)==1)
reservation=next(x for x in results if x)
jobs.settle(S,reservation['reservation_id'])
denied(lambda:jobs.reserve(S,'blocked',str(uuid.uuid4()),40,keys),'unknown exposure prevents overspend')
jobs.settle(S,reservation['reservation_id'],actual_micro_usd=50,usage_event_id='existing-usage-ref')
with connect() as db:r=db.execute('SELECT settled_micro_usd,reserved_micro_usd,unknown_micro_usd FROM pr_trend_budget_limits WHERE budget_key=%s',(keys[0],)).fetchone()
check('integer microUSD known settlement clears reservation exactly',r==(50,0,0))

# Queue and fence races; invalid batch rolls back observations, outbox and cursor together.
j=jobs.enqueue(S,'trend.discovery.poll',{},idempotency_key='batch1',provider_id=PROVIDER,source_policy_version='v1')
claim=jobs.claim('worker-a',scope_key=S);claim=jobs.start(claim)
partition=partition_key(instance_id='fixture.social',protocol_version='v2',filter_digest='query1')
bad=obs(30);bad['payload_digest']='0'*64
new=obs(29)
denied(lambda:jobs.complete_batch(claim,partition_key=partition,expected_generation=0,batch_key='bad',observations=[new,bad],cursor_value={'cursor':1}),'bad batch atomically aborts')
with connect() as db:r=db.execute('SELECT count(*) FROM pr_trend_observations WHERE observation_id=%s',(new['observation_id'],)).fetchone()[0]
check('failed batch has neither durable observation nor cursor',r==0 and jobs.get_cursor(S,PROVIDER,partition)['generation']==0)
result=jobs.complete_batch(claim,partition_key=partition,expected_generation=0,batch_key='good',observations=[new],cursor_value={'cursor':1},terminal_page=True,coverage_state='complete',outbox_events=[{'event_key':'new-29','event_type':'trend.observed','payload':{},'node_id':new['observation_id']}],actual_micro_usd=0)
check('batch cursor and outbox commit together',result['generation']==1 and jobs.get_cursor(S,PROVIDER,partition)['cursor_value']=={'cursor':1})
denied(lambda:jobs.complete_batch(claim,partition_key=partition,expected_generation=1,batch_key='stale',observations=[],cursor_value={}), 'completed stale fence cannot commit')
queued=jobs.enqueue(S,'trend.discovery.poll',{},idempotency_key='lease2',provider_id=PROVIDER,source_policy_version='v1');old=jobs.claim('old',scope_key=S)
with connect() as db:db.execute("UPDATE pr_trend_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",(old['job_id'],))
newclaim=jobs.claim('new',scope_key=S)
check('expired unstarted lease increments fence on reclaim',newclaim['lease_generation']>old['lease_generation'])
denied(lambda:jobs.start(old),'expired owner cannot dispatch')
jobs.start(newclaim)
with connect() as db:db.execute("UPDATE pr_trend_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",(newclaim['job_id'],))
jobs.recover_expired()
with connect() as db:r=db.execute('SELECT state FROM pr_trend_jobs WHERE job_id=%s',(newclaim['job_id'],)).fetchone()[0]
check('crashed dispatched job becomes unknown not automatic retry',r=='outcome_unknown')

# Admission selects an exact pre-inspected job; local jobs never consume provider reservations.
first=jobs.enqueue(S,'trend.local',{'selection':1},idempotency_key='local-one',priority=100)
second_local=jobs.enqueue(S,'trend.local',{'selection':2},idempotency_key='local-two')
local=jobs.claim('local-worker',scope_key=S,kind='trend.local',job_id=second_local['job_id'])
check('exact job claim never substitutes higher priority sibling',local['job_id']==second_local['job_id'])
check('fenced local completion requires no provider or reservation',jobs.finish_local(local)['state']=='succeeded')
sealed=jobs.enqueue(S,'trend.local',{'selection':2},idempotency_key='local-two')
check('terminal job erases input and seals idempotency without redispatch',sealed['payload']=={} and sealed['job_id']==second_local['job_id'] and sealed['state']=='succeeded')
denied(lambda:jobs.enqueue(S,'trend.local',{'observations':[base]},idempotency_key='raw-job'),
    'job payload cannot retain raw observations as another source store')
denied(lambda:jobs.finish_local(local),'local completion rejects stale duplicate fence')
jobs.cancel(S,first['job_id'])

# Model attempts use the authoritative usage sink in an independent transaction.
from postriff_phase2.growth.usage import UsageEvent
model_keys=['model-system-'+uuid.uuid4().hex,'model-provider-'+uuid.uuid4().hex]
for key,dimension in zip(model_keys,['system','provider']):jobs.configure_budget(key,dimension,10000,START,END)
def model_claim(key):
    queued=jobs.enqueue(S,'trend.fixture.model',{'selection_digest':'opaque'},idempotency_key=key)
    return jobs.start(jobs.claim('model-fixture',job_id=queued['job_id'],budget_keys=model_keys,amount_micro_usd=100))
def usage(cost=0.00003):
    return UsageEvent(task='trend.fixture.model',model='fixture-no-network',route='primary',status='ok',latency_ms=1,
                      cost_usd=cost,cost_source='unknown' if cost is None else 'gateway')
mc=model_claim('model-account-once')
with ThreadPoolExecutor(max_workers=2) as pool:
    accounted=list(pool.map(lambda _:jobs.account_attempt(S,mc['reservation_id'],usage()),range(2)))
check('concurrent model accounting records authoritative usage exactly once',
    len({x['usage_event_id'] for x in accounted})==1 and sorted(x['replayed'] for x in accounted)==[False,True])
denied(lambda:jobs.finish_external(mc,actual_micro_usd=30,usage_event_id='not-recorded'),
       'external completion requires the recorded usage pointer')
done=jobs.finish_external(mc,actual_micro_usd=accounted[0]['actual_micro_usd'],usage_event_id=accounted[0]['usage_event_id'])
check('external completion clears controls without provider cursor side effects',
      done['state']=='succeeded' and done['payload']=={} and done['provider_id'] is None)
mc=model_claim('model-account-before-expiry');accounted=jobs.account_attempt(S,mc['reservation_id'],usage())
with connect() as db:db.execute("UPDATE pr_trend_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",(mc['job_id'],))
jobs.recover_expired()
denied(lambda:jobs.finish_external(mc,actual_micro_usd=accounted['actual_micro_usd'],usage_event_id=accounted['usage_event_id']),
       'stale model output cannot commit after independent usage accounting')
with connect() as db:r=db.execute('SELECT state,actual_micro_usd,usage_event_id FROM pr_trend_budget_reservations WHERE reservation_id=%s',(mc['reservation_id'],)).fetchone()
check('expiry after accounted attempt preserves known spend and usage receipt',r==('settled',accounted['actual_micro_usd'],accounted['usage_event_id']))
mc=model_claim('model-cancel-before-account');jobs.cancel(S,mc['job_id'])
accounted=jobs.account_attempt(S,mc['reservation_id'],usage())
check('cancelled model output still records and settles incurred usage',accounted['actual_micro_usd']==usage().cost_usd_micro())
mc=model_claim('model-account-before-cancel');jobs.account_attempt(S,mc['reservation_id'],usage());jobs.cancel(S,mc['job_id'])
with connect() as db:r=db.execute('SELECT state FROM pr_trend_budget_reservations WHERE reservation_id=%s',(mc['reservation_id'],)).fetchone()[0]
check('cancellation after usage commit never releases settled spend',r=='settled')
mc=model_claim('model-unknown');accounted=jobs.account_attempt(S,mc['reservation_id'],usage(None))
jobs.finish_external(mc,actual_micro_usd=None,usage_event_id=accounted['usage_event_id'])
with connect() as db:r=db.execute('SELECT state,amount_micro_usd,actual_micro_usd FROM pr_trend_budget_reservations WHERE reservation_id=%s',(mc['reservation_id'],)).fetchone()
check('successful output with unknown price retains full reserved exposure',r==('unknown',100,None))
with connect() as db:r=db.execute("SELECT count(*) FROM pr_model_usage_events WHERE task='trend.fixture.model'").fetchone()[0]
check('five physical model attempts produce five existing usage-ledger events',r==5)

# Operational poison receipts contain no source text and need no evidence node.
quarantine={'schema_version':'trend.quarantine.v1','job_id':mc['job_id'],'lease_generation':1,
    'partition_key':'a'*64,'generation':1,'accepted_count':0,'quarantined_count':1,
    'entries':[{'index':0,'reason_code':'private source string'}],'completeness':'gap'}
qe=outbox.enqueue(S,'quarantine-fixture','trend.quarantined',quarantine)
check('quarantine outbox permits only sanitized content-free receipt without node',
      qe['node_id'] is None and qe['payload']['entries']==[{'index':0,'reason_code':'invalid_record'}])
denied(lambda:outbox.enqueue(S,'quarantine-invalid','trend.quarantined',{**quarantine,'text':'restricted'}),
       'quarantine event rejects any unexpected content-bearing field')

# Production path uses DB persistence timestamps, including a transaction with newly written inputs.
live=TrendStore(connect); livejobs=TrendJobs(live)
livejob=livejobs.enqueue(S,'trend.discovery.poll',{},idempotency_key='live-clock',provider_id=PROVIDER,source_policy_version='v1')
lc=livejobs.start(livejobs.claim('clock-worker',job_id=livejob['job_id']))
liveob=obs(31)
livejobs.complete_batch(lc,partition_key=partition,expected_generation=1,batch_key='live-clock',observations=[liveob],cursor_value={'cursor':2},
    outbox_events=[{'event_key':'clock-cutoff','event_type':'trend.ingested','payload':{'decision_cutoff':AT,'observation_ids':[liveob['observation_id']],
        'markers':[{'kind':'account','did':'did:fixture:deleted-account','active':False}],'text':'must never persist'}}],actual_micro_usd=0)
with connect() as db:
    available=db.execute('SELECT available_at FROM pr_trend_observations WHERE observation_id=%s',(liveob['observation_id'],)).fetchone()[0]
    cutoff=db.execute("SELECT payload->>'decision_cutoff' FROM pr_trend_outbox WHERE event_key='clock-cutoff'").fetchone()[0]
check('ingested cutoff is DB-stamped after observation availability',iso(available)>=iso(NOW) and datetime.fromisoformat(cutoff.replace('Z','+00:00'))>=available)
with connect() as db:
    event_payload=db.execute("SELECT payload FROM pr_trend_outbox WHERE event_key='clock-cutoff'").fetchone()[0]
    job_payload=db.execute('SELECT payload FROM pr_trend_jobs WHERE job_id=%s',(livejob['job_id'],)).fetchone()[0]
check('ingested event retains marker counts without DID or source text',event_payload['marker_counts']=={'account':1} and 'markers' not in event_payload and 'text' not in event_payload and 'did:fixture:' not in json.dumps(event_payload))
check('ingested provider job retains no processed request payload',job_payload=={})
with live.transaction() as cur:
    current=obs(32);saved=live.put_observation(current,cursor=cur)
    cur.execute('SELECT clock_timestamp()');dc=iso(cur.fetchone()[0])
    lm=live.put_manifest(S,[{'scope_key':S,'node_id':current['observation_id']}],decision_cutoff=dc,available_at=AT,retention_until=FUTURE,
        recipe={'codec':'json-string-chunks'},chunks=[{'text':'{"normalized_inputs":["synthetic"]}'}],document_digest=digest({'synthetic':True}),cursor=cur)
    lp={**projection,'object_id':str(uuid.uuid4()),'manifest_id':lm['manifest_id'],'decision_cutoff':dc}
    live.put_projection(lp,cursor=cur)
check('new live observation manifest and projection validate in one transaction',live.get_projection(W,A,'trend',lp['object_id'])['validity']=='valid')
check('full recipe chunks survive manifest roundtrip',live.get_manifest(S,lm['manifest_id'])['chunks'][0]['payload']['text'].startswith('{"normalized_inputs"'))
with connect() as db:
    times=db.execute('SELECT p.available_at,c.available_at FROM pr_trend_source_policies p JOIN pr_trend_provider_contracts c USING(provider_id) WHERE p.scope_key=%s AND p.provider_id=%s',(S,PROVIDER)).fetchone()
check('policy and contract availability cannot inherit a backdated review',all(t>=NOW for t in times))
with live.transaction() as cur:
    policy=live._policy(cur,S,PROVIDER,'v1')
check('pipeline policy manifest inherits durable availability',datetime.fromisoformat(policy['manifest']['available_at'].replace('Z','+00:00'))==max(times))
with live.transaction() as cur:
    denied(lambda:live._policy(cur,S,PROVIDER,'v1',at=AT),'policy cannot authorize a cutoff before its durable availability')

# Held binding locks force deletion to serialize after the accepted mutation transaction.
attempted=threading.Event()
def delete_locked():
    attempted.set()
    return revocation.revoke_source(store,S,PROVIDER,'source-32',purge_deadline=FUTURE)
with ThreadPoolExecutor(max_workers=1) as pool:
    with connect() as db,db.cursor() as cur:
        locked=live.lock_dependencies(W,A,[{'kind':'trend','object_id':lp['object_id'],'revision':1}],cursor=cur)
        pending=pool.submit(delete_locked);attempted.wait(3)
        try:pending.result(timeout=0.15);blocked=False
        except TimeoutError:blocked=True
        check('accepted mutation binding serializes concurrent source tombstone',blocked and locked[0]['validity']=='valid')
    pending.result(timeout=5)
check('deletion wins immediately after mutation transaction releases',live.get_projection(W,A,'trend',lp['object_id'])['payload'] is None)
retention.sweep(store,limit=100)
with connect() as db:
    purged=db.execute('SELECT m.recipe,c.payload FROM pr_trend_input_manifests m JOIN pr_trend_manifest_chunks c USING(scope_key,manifest_id) WHERE m.manifest_id=%s',(lm['manifest_id'],)).fetchone()
check('source deletion purges retained full recomputation recipe and chunks',purged==({},{}))

# Transactional local consumer receipt rollback + retry.
event=outbox.claim('fixture-consumer','worker')
def fail_effect(cur,e):raise ValueError('synthetic_crash')
denied(lambda:outbox.consume(event,fail_effect),'consumer effect failure leaves no success receipt')
seen=[]
def effect(cur,e):seen.append(e['event_id'])
outbox.consume(event,effect);outbox.consume(event,effect)
check('consumer receipt deduplicates committed local effect',len(seen)==1)
expired_event=outbox.claim('lease-expiry-consumer','worker')
def expired_effect(cur,e):
    store.put_watch(W,A,{'trend_id':obj},idempotency_key='expired-effect',cursor=cur)
    cur.execute("UPDATE pr_trend_outbox_consumers SET lease_until=clock_timestamp()-interval '1 second' WHERE consumer=%s AND scope_key=%s AND event_id=%s",
        (expired_event['consumer'],expired_event['scope_key'],expired_event['event_id']))
denied(lambda:outbox.consume(expired_event,expired_effect),'outbox lease expiry during local effect refuses completion')
with connect() as db:r=db.execute("SELECT count(*) FROM pr_trend_watches WHERE workspace_id=%s AND idempotency_key='expired-effect'",(W,)).fetchone()[0]
check('expired outbox completion rolls back its local domain mutation',r==0)

# Watches and same-transaction opportunity saving.
watch=store.put_watch(W,A,{'trend_id':obj},idempotency_key='watch1')
check('watch creation idempotent',store.put_watch(W,A,{'trend_id':obj},idempotency_key='watch1')['watch_id']==watch['watch_id'])
removed=store.delete_watch(W,A,watch['watch_id'],expected_revision=1,idempotency_key='delete1')
check('watch deletion replay stable',not removed['enabled'] and store.delete_watch(W,A,watch['watch_id'],expected_revision=1,idempotency_key='delete1')==removed)
wm=store.put_manifest(WS,[{'scope_key':S,'node_id':base['observation_id']}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE)
op=str(uuid.uuid4());store.put_projection({**projection,'scope_key':WS,'kind':'opportunity','object_id':op,'manifest_id':wm['manifest_id']})
try:
    with connect() as db,db.cursor() as cur:
        store.decide_opportunity(W,A,op,revision=1,decision='save',idempotency_key='save1',result={'source_id':'synthetic-source'},cursor=cur)
        raise ValueError('rollback source and decision')
except ValueError:pass
with connect() as db:r=db.execute('SELECT count(*) FROM pr_trend_opportunity_decisions WHERE workspace_id=%s',(W,)).fetchone()[0]
check('caller transaction controls opportunity decision rollback',r==0)
append_started=threading.Event()
def append_opportunity_head():
    append_started.set()
    return store.put_projection({**projection,'scope_key':WS,'kind':'opportunity','object_id':op,'manifest_id':wm['manifest_id'],'revision':2},expected_revision=1)
with ThreadPoolExecutor(max_workers=1) as pool:
    with store.transaction() as cur:
        store.lock_dependencies(W,A,[{'kind':'opportunity','object_id':op,'revision':1}],cursor=cur)
        appended=pool.submit(append_opportunity_head);append_started.wait(3)
        try:appended.result(timeout=0.15);blocked=False
        except TimeoutError:blocked=True
        check('mutation lock serializes concurrent projection head append',blocked)
    appended.result(timeout=5)
with store.transaction() as cur:
    denied(lambda:store.lock_dependencies(W,A,[{'kind':'opportunity','object_id':op,'revision':1}],cursor=cur),
        'mutation binding rejects a revision superseded before lock acquisition')

# Receipt version and trusted verification persistence.
rid=store.put_receipt({**projection,'receipt_id':str(uuid.uuid4()),'payload':{'schema':'rafii.trend-trust-receipt.v2','observed':{'count':1}}})
vr=store.record_verification(S,rid,recomputed_digest=digest({'schema':'rafii.trend-trust-receipt.v2','observed':{'count':1}}),input_manifest_digest=manifest['digest'],method_artifact_digest=artifact)
check('receipt schema v2 and DB-bound verification survive read',vr['state']=='verified' and store.get_receipt(W,A,rid)['verification_state']=='verified')

# Old pure pipeline receipts may be verified in the DB but lack a membership DAG
# seal. Current reads must close immediately, including indirect private artifacts.
legacy_payload={'schema':'rafii.trend-trust-receipt.v2','pure_receipt':{'fixture':'legacy-membership-binding'}}
legacy_rid=store.put_receipt({**projection,'receipt_id':str(uuid.uuid4()),'payload':legacy_payload})
store.record_verification(S,legacy_rid,recomputed_digest=digest(legacy_payload),input_manifest_digest=manifest['digest'],method_artifact_digest=artifact)
legacy_obj=str(uuid.uuid4())
legacy_pid=store.put_projection({**projection,'object_id':legacy_obj,'receipt_id':legacy_rid})
private_manifest=store.put_manifest(WS,[{'scope_key':S,'node_id':legacy_pid}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE)
private_obj=str(uuid.uuid4())
store.put_projection({**projection,'scope_key':WS,'kind':'model_judgment','object_id':private_obj,'manifest_id':private_manifest['manifest_id']})
legacy_rows=[store.get_receipt(W,A,legacy_rid),store.get_projection(W,A,'trend',legacy_obj),
    store.get_projection(W,A,'model_judgment',private_obj)]
check('legacy pure receipt without membership seal hides receipt trend and indirect workspace artifact',
    all(r['validity']=='method_unavailable' and r['verification_state']=='method_unavailable' and r['payload'] is None for r in legacy_rows))
check('legacy pure receipt without membership seal is excluded from bounded lists',
    store.list_projections(W,A,filters={'object_id':legacy_obj})['items']==[])
malformed_payload={**legacy_payload,'membership_dependency_digest':'not-a-digest','membership_dependency_count':True}
malformed_rid=store.put_receipt({**projection,'receipt_id':str(uuid.uuid4()),'payload':malformed_payload})
store.record_verification(S,malformed_rid,recomputed_digest=digest(malformed_payload),input_manifest_digest=manifest['digest'],method_artifact_digest=artifact)
check('malformed membership binding markers fail closed without changing generic receipts',
    store.get_receipt(W,A,malformed_rid)['payload'] is None and store.get_receipt(W,A,rid)['validity']=='valid')

# Revocation suppresses all derived reads before any purge; recreate cannot resurrect.
revocation.revoke_source(store,S,PROVIDER,'source-1',deletion_sequence=4,purge_deadline=FUTURE)
gone=store.get_projection(W,A,'trend',obj,as_of=iso(NOW))
check('source tombstone immediately denies dependent payload',gone['validity']=='deleted' and gone['payload'] is None)
denied(lambda:store.put_observation(obs(1,revision=5)),'delete-before-replay prevents resurrection')
denied(lambda:store.decide_opportunity(W,A,op,revision=1,decision='save',idempotency_key='save1'),'revoked opportunity cannot be saved')
retention.sweep(store,limit=100)
with connect() as db:r=db.execute('SELECT payload,author_key,payload_digest FROM pr_trend_observations WHERE observation_id=%s',(base['observation_id'],)).fetchone()
check('bounded purge removes raw content identity and payload digest',r==({},None,None))
with connect() as db:r=db.execute('SELECT payload,verification_record,verified_at FROM pr_trend_trust_receipts WHERE receipt_id=%s',(rid,)).fetchone()
check('receipt purge removes source-derived verification hashes',r==({},{},None))
revocation.revoke_author(store,PROVIDER,'did:fixture:never-seen',purge_deadline=FUTURE)
denied(lambda:store.put_observation(obs(100,author='did:fixture:never-seen')),'author tombstone blocks unseen future source across domains')

# Rights and entitlement changes affect cached projections now, regardless of historical as_of.
sig=store.scope_signature(W,A)
revocation.revoke_entitlement(store,W,S)
check('entitlement revocation changes pagination signature and denies shared read',sig!=store.scope_signature(W,A) and store.get_projection(W,A,'trend',second) is None)
store.grant_entitlement(W,S,['retrieve','derive_metrics','share_across_workspaces'],END)

# Real dump/restore of a pre-deletion snapshot, then authoritative tombstones before serving.
restore_obs=obs(400,author='did:fixture:restore');store.put_observation(restore_obs)
evidence=ROOT/'.trend-storage-test';evidence.mkdir(exist_ok=True)
restore_db='trend_restore_'+uuid.uuid4().hex[:8];dump=evidence/(restore_db+'.dump')
subprocess.run([str(PG/'pg_dump'),*PGARGS,'-Fc','-f',str(dump),params['dbname']],check=True)
revocation.revoke_source(store,S,PROVIDER,'source-400',purge_deadline=FUTURE)
bundle=revocation.export_tombstones(store)
subprocess.run([str(PG/'createdb'),*PGARGS,restore_db],check=True)
subprocess.run([str(PG/'pg_restore'),*PGARGS,'--exit-on-error','-d',restore_db,str(dump)],check=True,stdout=subprocess.DEVNULL)
restored_dsn=psycopg.conninfo.make_conninfo(DSN,dbname=restore_db)
restored=TrendStore(lambda:connect(restored_dsn),offline_replay=True)
gen=revocation.begin_restore(restored)
check('restore read gate defers purge rather than destroying retained data',retention.sweep(restored)['deferred']=='restore_in_progress')
with connect(restored_dsn) as db:r=db.execute('SELECT postriff_private.trend_node_valid(%s,%s)',(S,restore_obs['observation_id'])).fetchone()[0]
check('restored database read gate closes before tombstone import',not r)
revocation.restore_tombstones(restored,bundle,generation=gen)
denied(lambda:restored.put_observation(obs(400,revision=2)),'real backup restore cannot resurrect deleted source after tombstone import')
with connect() as db:r=db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
check('test connections were non-superuser and non-bypass throughout',r==(False,False))
# Revoked pending/running controls are erased; unknown monetary exposure survives.
store.register_policy({'scope_key':S,'provider_id':PROVIDER,'version':'revoked-job-test','rights':rights(S),
    'effective_at':START,'expires_at':END,'retention_seconds':5*86400,'readiness':'ready'},provider_contract_version='v1')
private_job=jobs.enqueue(S,'trend.ingest',{'operation':'sample','filter':{'query':'synthetic private control'}},
    idempotency_key='revoked-job-control',provider_id=PROVIDER,source_policy_version='revoked-job-test')
private_claim=jobs.start(jobs.claim('private-control-worker',job_id=private_job['job_id'],budget_keys=keys,amount_micro_usd=10))
revocation.revoke_policy(store,S,PROVIDER,'revoked-job-test')
retention.sweep(store)
with connect() as db:
    erased=db.execute('SELECT payload,state FROM pr_trend_jobs WHERE job_id=%s',(private_job['job_id'],)).fetchone()
    exposed=db.execute('SELECT state,amount_micro_usd FROM pr_trend_budget_reservations WHERE reservation_id=%s',(private_claim['reservation_id'],)).fetchone()
check('policy revocation cancels and erases pending controls without releasing unknown cost',erased==({},'cancelled') and exposed==('unknown',10))
yue_observation=obs(887);yue_observation['payload']['language']='yue';yue_observation['payload_digest']=digest(yue_observation['payload'])
store.put_observation(yue_observation)
yue_manifest=store.put_manifest(S,[{'scope_key':S,'node_id':yue_observation['observation_id']}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE)
store.put_projection({**projection,'object_id':str(uuid.uuid4()),'manifest_id':yue_manifest['manifest_id'],
    'payload':{**projection['payload'],'language':'yue'}})
signals=operations.snapshot(store)
check('operations snapshot covers typed durable counters without source content',
    set(signals)=={'status','reason_codes','jobs','budgets','receipt_verifications','deletion','source_health','notification_delivery','recent'}
    and not any(s in json.dumps(signals) for s in ('Synthetic source','did:fixture:','fixture.invalid')))
check('operations expose quarantine enums, lag samples and explicit cohort qualification gap',
    signals['recent']['quarantine']['reason_counts']==[{'reason_code':'invalid_record','count':1}]
    and signals['recent']['lag_seconds']['ingestion_persistence']['samples']>0
    and signals['recent']['receipt_method_cohorts']['language_qualification']=='unavailable_requires_retained_calibration')
check('operations preserve Cantonese cohort without claiming language qualification',
    any(c['language']=='yue' and c['revisions']==1 for c in signals['recent']['receipt_method_cohorts']['items'])
    and signals['recent']['receipt_method_cohorts']['language_qualification']=='unavailable_requires_retained_calibration')
continuation_payload={'observation_ids':[yue_observation['observation_id']],'pending_observation_indices':[0]}
continuation=outbox.enqueue(S,'safe-continuation-indices','trend.ingested',continuation_payload)
with connect() as db:
    db.execute("UPDATE pr_trend_outbox SET payload=payload||'{\"text\":\"synthetic old marker copy\"}'::jsonb WHERE event_id=%s",(continuation['event_id'],))
retention.sweep(store)
with connect() as db:
    scrubbed=db.execute('SELECT payload FROM pr_trend_outbox WHERE event_id=%s',(continuation['event_id'],)).fetchone()[0]
check('retention scrubs old content while retaining bounded continuation indices and root references',scrubbed==continuation_payload)
# Actual worker admission/accounting with an injected bounded adapter, no I/O.
from postriff_phase2.growth.trends.policy import SourcePolicy,ProviderCapability
from postriff_phase2.growth.trends.providers.registry import ProviderRegistry
from postriff_phase2.growth.trends.providers.base import Batch
from postriff_phase2.growth.trends.worker import TrendWorker
registry=ProviderRegistry();adapter_calls=[]
wp=SourcePolicy(id='fixture-worker',version='v1',provider_id=PROVIDER,operation='sample',scope_key=S,
    rights=rights(S),reviewed_by='fixture',review_ref='fixture',effective_at=START,expires_at=END,
    retention_seconds=5*86400,readiness='ready')
cap=ProviderCapability(provider_id=PROVIDER,operation='sample',version='v1',evidence_kinds=('raw_post',),
    endpoint='https://fixture.invalid',protocol='fixture',credential_class='none',required_scopes=(),
    max_items=1,max_response_bytes=4096,timeout_seconds=1,max_attempts=1,
    billable_unit='unmetered_live_bytes_bounded',deletion_mechanism='fixture')
worker_observation=obs(880)
def fixture_adapter(**kwargs):
    adapter_calls.append(True)
    return Batch(observations=(worker_observation,),cursor={'page':1},completeness='complete',bytes_received=1,terminal_page=True,cost_microusd=0)
registry.register(cap,wp,fixture_adapter)
wj=jobs.enqueue(S,'trend.ingest',{'operation':'sample','budget_keys':model_keys,'reservation_microusd':0,'coverage_epoch':'worker','max_items':1},
    idempotency_key='worker-smoke',provider_id=PROVIDER,source_policy_version='v1')
off=TrendWorker(store,registry=registry,values={}).tick(max_jobs=1,max_seconds=6)
check('actual worker defaults dispatch zero attempts without flags',off['dispatched']==0 and not adapter_calls)
# Earlier independent outbox fixtures are already covered by their own effects.
with connect() as db:
    db.execute("INSERT INTO pr_trend_outbox_consumers(consumer,scope_key,event_id,state,completed_at) SELECT 'trend.pipeline.v1',scope_key,event_id,'done',clock_timestamp() FROM pr_trend_outbox ON CONFLICT DO NOTHING")
enabled={'RAFII_TREND_INTELLIGENCE_ENABLED':'1','RAFII_TREND_RADAR_ENABLED':'1','RAFII_TREND_PROVIDER_OPERATIONS_ENABLED':'1',
    'RAFII_TREND_WORKSPACE_ALLOWLIST':W,'RAFII_TREND_ALLOWED_OPERATIONS':PROVIDER+':sample'}
result=TrendWorker(store,registry=registry,values=enabled).tick(max_jobs=1,max_seconds=6)
check('actual worker injected adapter commits canonical batch plus existing usage sink',
      result['dispatched']==result['completed']==1 and result['failed']==0 and len(adapter_calls)==1)
with connect() as db:
    r=db.execute('SELECT j.state,r.state,r.actual_micro_usd,u.cost_source FROM pr_trend_jobs j JOIN pr_trend_budget_reservations r USING(scope_key,reservation_id) JOIN pr_model_usage_events u ON u.id::text=r.usage_event_id WHERE j.job_id=%s',(wj['job_id'],)).fetchone()
check('worker usage source matches frozen035 ledger with integer zero known cost',r==('succeeded','settled',0,'table:trend-provider-contract-v1'))
# Deep reverse propagation is paged; retained neighbours must never be erased.
deep_source=obs(990);store.put_observation(deep_source)
node_id=deep_source['observation_id'];deep_nodes=[node_id]
for depth in range(12):
    dm=store.put_manifest(S,[{'scope_key':S,'node_id':node_id}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE)
    node_id=store.put_projection({**projection,'object_id':str(uuid.uuid4()),'revision':1,'manifest_id':dm['manifest_id'],
        'payload':{'observed':{'count':depth}}})
    deep_nodes.extend([dm['manifest_id'],node_id])
revocation.revoke_source(store,S,PROVIDER,'source-990',purge_deadline=FUTURE)
purged=0
for _ in range(15):
    page=retention.sweep(store,limit=5);assert page['purged_nodes']<=5;purged+=page['purged_nodes']
    with connect() as db:
        remaining=db.execute("SELECT count(*) FROM pr_trend_nodes WHERE node_id=ANY(%s::uuid[]) AND validity<>'purged'",(deep_nodes,)).fetchone()[0]
    if remaining==0:break
check('deep reverse deletion closure progresses across bounded purge pages',remaining==0 and purged>=len(deep_nodes))
with connect() as db:
    retained=db.execute('SELECT payload,purged_at FROM pr_trend_observations WHERE observation_id=%s',(worker_observation['observation_id'],)).fetchone()
check('purge preselection retains unrelated currently permitted observation',retained[0]==worker_observation['payload'] and retained[1] is None)
# Mutate ONLY isolated disposable fixtures to exercise every current invalidity
# root without waiting days for real policy/contract/grant expirations.
for cause in ('policy_revoked','policy_expired','policy_unknown','observation_grant_expired',
              'derive_grant_expired','contract_expired','scope_disabled','method_withdrawn','node_expired','entitlement_revoked'):
    cs='shared:purge-'+uuid.uuid4().hex[:10];cp='purge-'+uuid.uuid4().hex[:10]
    store.ensure_scope(cs);store.register_contract(cp,'v1',list(PERMISSIONS),START,END,{})
    store.register_policy({'scope_key':cs,'provider_id':cp,'version':'v1','rights':rights(cs),
        'effective_at':START,'expires_at':END,'retention_seconds':5*86400,'readiness':'ready'},provider_contract_version='v1')
    co=obs(1000,s=cs);co['provider_id']=cp;store.put_observation(co)
    target=WS if cause=='entitlement_revoked' else cs
    if target==WS:store.grant_entitlement(W,cs,['retrieve','derive_metrics','share_across_workspaces'],END)
    cm=store.put_manifest(target,[{'scope_key':cs,'node_id':co['observation_id']}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE)
    mid='purge-method-'+uuid.uuid4().hex[:8];store.put_method(mid,'v1',artifact,{})
    child=store.put_projection({**projection,'scope_key':target,'object_id':str(uuid.uuid4()),'revision':1,
        'method_id':mid,'manifest_id':cm['manifest_id']})
    if cause=='policy_revoked':revocation.revoke_policy(store,cs,cp,'v1')
    elif cause=='entitlement_revoked':revocation.revoke_entitlement(store,W,cs)
    else:
        with connect() as db:
            if cause=='policy_expired':db.execute("UPDATE pr_trend_source_policies SET expires_at=clock_timestamp()-interval '1 second' WHERE scope_key=%s",(cs,))
            elif cause=='policy_unknown':db.execute("UPDATE pr_trend_source_policies SET rights=jsonb_set(rights,'{retrieve,state}','\"unknown\"') WHERE scope_key=%s",(cs,))
            elif cause in ('observation_grant_expired','derive_grant_expired'):
                permission='retrieve' if cause=='observation_grant_expired' else 'derive_metrics'
                db.execute("UPDATE pr_trend_observations SET rights=jsonb_set(rights,%s,to_jsonb((clock_timestamp()-interval '1 second')::text)) WHERE scope_key=%s",([permission,'expires_at'],cs))
            elif cause=='contract_expired':db.execute("UPDATE pr_trend_provider_contracts SET expires_at=clock_timestamp()-interval '1 second' WHERE provider_id=%s",(cp,))
            elif cause=='scope_disabled':db.execute('UPDATE pr_trend_scopes SET enabled=false WHERE scope_key=%s',(cs,))
            elif cause=='method_withdrawn':db.execute("UPDATE pr_trend_method_versions SET qualification='withdrawn' WHERE method_id=%s",(mid,))
            elif cause=='node_expired':db.execute("UPDATE pr_trend_nodes SET retention_until=clock_timestamp()-interval '1 second' WHERE node_id=%s",(co['observation_id'],))
    retention.sweep(store,limit=100)
    with connect() as db:
        child_payload=db.execute('SELECT payload FROM pr_trend_projections WHERE projection_id=%s',(child,)).fetchone()[0]
        source_payload=db.execute('SELECT payload FROM pr_trend_observations WHERE observation_id=%s',(co['observation_id'],)).fetchone()[0]
    raw_still_permitted=cause in ('derive_grant_expired','method_withdrawn','entitlement_revoked')
    check('purge discovers current '+cause+' without erasing permitted inputs',child_payload=={} and source_payload==(co['payload'] if raw_still_permitted else {}))
# Independent operation grants: losing raw storage must not leave sealed raw
# recipes readable, nor erase a separate licensed aggregate-only branch.
for loss in ('policy_unknown','observation_expired','contract_operation'):
    rs='shared:storage-'+uuid.uuid4().hex[:10];rp='storage-'+uuid.uuid4().hex[:10]
    store.ensure_scope(rs);store.grant_entitlement(W,rs,['retrieve','derive_metrics','share_across_workspaces'],END)
    store.register_contract(rp,'v1',list(PERMISSIONS),START,END,{})
    store.register_policy({'scope_key':rs,'provider_id':rp,'version':'v1','rights':rights(rs),
        'effective_at':START,'expires_at':END,'retention_seconds':5*86400,'readiness':'ready'},provider_contract_version='v1')
    raw_obs=obs(2000,s=rs);raw_obs['provider_id']=rp;store.put_observation(raw_obs)
    metric_obs=obs(2001,s=rs,kind='aggregate_metric');metric_obs['provider_id']=rp;store.put_observation(metric_obs)
    raw_manifest=store.put_manifest(rs,[{'scope_key':rs,'node_id':raw_obs['observation_id']}],
        decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE,recipe={'raw':raw_obs['payload']},chunks=[{'raw':raw_obs['payload']}])
    metric_manifest=store.put_manifest(rs,[{'scope_key':rs,'node_id':metric_obs['observation_id']}],
        decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE,recipe={'metric':metric_obs['payload']})
    raw_receipt_payload={'schema':'rafii.trend-trust-receipt.v2','raw':raw_obs['payload']}
    raw_receipt=store.put_receipt({**projection,'scope_key':rs,'manifest_id':raw_manifest['manifest_id'],
        'receipt_id':str(uuid.uuid4()),'payload':raw_receipt_payload})
    store.record_verification(rs,raw_receipt,recomputed_digest=digest(raw_receipt_payload),input_manifest_digest=raw_manifest['digest'],method_artifact_digest=artifact)
    raw_obj=str(uuid.uuid4());metric_obj=str(uuid.uuid4())
    store.put_projection({**projection,'scope_key':rs,'object_id':raw_obj,'manifest_id':raw_manifest['manifest_id'],'receipt_id':raw_receipt})
    store.put_projection({**projection,'scope_key':rs,'object_id':metric_obj,'manifest_id':metric_manifest['manifest_id']})
    with connect() as db:
        if loss=='policy_unknown':
            db.execute("UPDATE pr_trend_source_policies SET rights=jsonb_set(rights,'{store_raw,state}','\"unknown\"') WHERE scope_key=%s",(rs,))
        elif loss=='observation_expired':
            db.execute("UPDATE pr_trend_observations SET rights=jsonb_set(rights,'{store_raw,expires_at}',to_jsonb((clock_timestamp()-interval '1 second')::text)) WHERE observation_id=%s",(raw_obs['observation_id'],))
        else:
            db.execute("UPDATE pr_trend_provider_contracts SET operations=array_remove(operations,'store_raw') WHERE provider_id=%s",(rp,))
    denied(lambda:store.get_manifest(rs,raw_manifest['manifest_id']),'current raw '+loss+' blocks full recipe before purge')
    check('current raw '+loss+' suppresses derived text while independent aggregate stays readable',
        store.get_receipt(W,A,raw_receipt)['payload'] is None and store.get_projection(W,A,'trend',raw_obj)['payload'] is None
        and store.get_projection(W,A,'trend',metric_obj)['validity']=='valid'
        and store.get_manifest(rs,metric_manifest['manifest_id'])['recipe']=={'metric':metric_obs['payload']})
    denied(lambda:store.put_manifest(rs,[{'scope_key':rs,'node_id':raw_obs['observation_id']}],decision_cutoff=CUT,available_at=CUT,retention_until=FUTURE),
        'current raw '+loss+' blocks new retained recipes at commit')
    bounded=True
    for _ in range(10):
        swept=retention.sweep(store,limit=3);bounded &= swept['purged_nodes']<=3
        if not swept['purged_nodes']:break
    with connect() as db:
        raw_saved=db.execute('SELECT payload,author_key,payload_digest FROM pr_trend_observations WHERE observation_id=%s',(raw_obs['observation_id'],)).fetchone()
        raw_recipe=db.execute('SELECT recipe,document_digest FROM pr_trend_input_manifests WHERE manifest_id=%s',(raw_manifest['manifest_id'],)).fetchone()
        raw_chunk=db.execute('SELECT payload,digest FROM pr_trend_manifest_chunks WHERE manifest_id=%s',(raw_manifest['manifest_id'],)).fetchone()
        raw_verification=db.execute('SELECT payload,verification_record FROM pr_trend_trust_receipts WHERE receipt_id=%s',(raw_receipt,)).fetchone()
        aggregate_saved=db.execute('SELECT payload,purged_at FROM pr_trend_observations WHERE observation_id=%s',(metric_obs['observation_id'],)).fetchone()
    check('current raw '+loss+' bounded purge removes raw identity recipe chunks and receipt seal only',
        bounded and raw_saved==({},None,None) and raw_recipe==({},None) and raw_chunk==({},None) and raw_verification==({},{})
        and aggregate_saved==(metric_obs['payload'],None) and store.get_projection(W,A,'trend',metric_obj)['validity']=='valid')
subprocess.run([str(PG/'dropdb'),*PGARGS,restore_db],check=True)
dump.unlink()
print(json.dumps({'execution':'disposable_postgresql_synthetic','passed':len(checks),'port':int(params['port']),'provider_calls':0}))
