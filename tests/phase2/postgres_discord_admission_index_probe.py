"""Actual PG17 query diagnostic only; never capacity or real Discord acceptance.

Loads the existing P0-P4 chain once in its owned disposable cluster. Retained
history is synthetic. Candidate indexes exist only in that cluster and are
removed after measurements. No production migration or provider I/O.
"""
import hashlib
import ast
import json
import os
from pathlib import Path
import runpy
import statistics
import sys
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Lock

if (sys.platform != 'linux' or os.environ.get('CI') != 'true'
        or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1'):
    raise SystemExit('Cloud-only owned synthetic database diagnostic.')

ROOT = Path(__file__).resolve().parents[2]
prior = runpy.run_path(str(Path(__file__).with_name('postgres_discord_rate_limits.py')))
connection = prior['connection']
from postriff_phase2.discord.rate_limits import RequestIdentity, SharedPostgresBudget, _digest, route_identity

ROWS, ROUNDS = 600000, 5
APP = '744400000000000001'
identity = RequestIdentity.make(APP, 'bot', 'synthetic-index-probe')
app, auth, credential = _digest(APP), identity.auth_key, identity.credential_key
route, major = route_identity('GET', '/channels/844400000000000001/messages/944400000000000001')
route = _digest(route)
alias = '50:' + _digest('synthetic-index-alias')
other_alias = '50:' + _digest('synthetic-other-alias')
scopes = ['00:' + app, '10:' + auth, '11:' + credential,
          '20:' + _digest('synthetic-index-egress'), '40:' + major, alias]
started = time.monotonic()

with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database(),current_user').fetchone() == (
        '127.0.0.1', 55438, 'postgres', 'postriff_test')
    initial_security = db.execute("SELECT relname,relrowsecurity,relforcerowsecurity,relacl::text FROM pg_class WHERE oid IN ('public.pr_discord_rate_state'::regclass,'public.pr_discord_route_buckets'::regclass,'public.pr_discord_request_admissions'::regclass) ORDER BY relname").fetchall()

# Bound each insertion rather than building a 600k-row Python object. All IDs,
# grants, credentials and history below are artificial and local to this DB.
for offset in range(0, ROWS, 50000):
    with connection() as db:
        db.execute("SET LOCAL statement_timeout='30000ms'")
        db.execute('''INSERT INTO public.pr_discord_request_admissions
            (id,application_key,auth_key,credential_key,credential_kind,method,path_key,
             route_key,major_key,bucket_key,scope_keys,state,reserved_at,expires_at,outcome_at)
            SELECT md5('synthetic-index-history:'||g)::uuid,%s,%s,%s,'bot','GET',%s,
                %s,md5((g%%10000)::text)||md5((g%%10000)::text),%s,
                ARRAY[%s,%s,%s,%s,%s,'50:'||md5((g%%10000)::text)||md5((g%%10000)::text)],
                'observed',clock_timestamp()-interval '20 minutes',clock_timestamp()-interval '19 minutes',clock_timestamp()
            FROM generate_series(%s::integer,%s::integer) AS g''',
            (app,auth,credential,_digest('synthetic-path'),route,_digest('synthetic-bucket'),
             *scopes[:5],offset+1,offset+50000))

with connection() as db:
    db.execute('''INSERT INTO public.pr_discord_request_admissions
        (id,application_key,auth_key,credential_key,credential_kind,method,path_key,
         route_key,major_key,bucket_key,scope_keys,state,reserved_at,expires_at)
        SELECT md5('synthetic-index-open:'||g)::uuid,%s,%s,%s,'bot','GET',%s,%s,%s,%s,
            ARRAY[%s,%s,%s,%s,%s,CASE WHEN g%%2=0 THEN %s ELSE %s END],
            (ARRAY['reserved','sealed','sent','uncertain'])[1+(g-1)%%4],
            clock_timestamp()-interval '30 seconds',
            CASE WHEN ((g-1)/4)%%2=0 THEN clock_timestamp()-interval '20 seconds'
                 ELSE clock_timestamp()+interval '30 minutes' END
        FROM generate_series(1,32) AS g''',
        (app,auth,credential,_digest('synthetic-path'),route,major,_digest('synthetic-bucket'),*scopes[:5],alias,other_alias))
    assert db.execute('SELECT count(*) FROM public.pr_discord_request_admissions WHERE application_key=%s',(app,)).fetchone()[0] == ROWS+32
    now = float(db.execute('SELECT extract(epoch FROM clock_timestamp())').fetchone()[0])


class Capture:
    def execute(self, query, parameters):
        self.query, self.parameters = query, parameters
    def fetchone(self):
        return (0, 0)


queries = {}
for name, key in [('global-pending',scopes[0]),('alias-pending',alias)]:
    capture=Capture();SharedPostgresBudget._pending(None,capture,key,now)
    queries[name]=(capture.query,capture.parameters,(24,) if name=='global-pending' else (12,))
capture=Capture()
SharedPostgresBudget._alias_pending(None,capture,alias,
    SimpleNamespace(id='00000000-0000-0000-0000-000000000001',identity=identity),(route,major),now)
queries['alias-union']=(capture.query,capture.parameters,(24,12))


def measure():
    results={}
    with connection() as db:
        db.execute('ANALYZE public.pr_discord_request_admissions')
    for name,(query,parameters,expected) in queries.items():
        records=[]
        for _ in range(ROUNDS):
            with connection() as db:
                assert db.execute(query,parameters).fetchone()==expected,(name,expected)
                records.append(db.execute('EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) '+query,parameters).fetchone()[0][0])
        results[name]={'expectedCounts':list(expected),'querySha256':hashlib.sha256(query.encode()).hexdigest(),
            'medianExecutionMs':statistics.median(x['Execution Time'] for x in records),'plans':records}
    return results


before=measure()
index_names=('pr_discord_admission_active_scopes_probe','pr_discord_admission_active_route_probe')
with connection() as db:
    db.execute("CREATE INDEX pr_discord_admission_active_scopes_probe ON public.pr_discord_request_admissions USING gin(scope_keys) WHERE state IN ('reserved','sealed','sent','uncertain')")
    db.execute("CREATE INDEX pr_discord_admission_active_route_probe ON public.pr_discord_request_admissions(auth_key,route_key,major_key,request_seq) WHERE state IN ('reserved','sealed','sent','uncertain')")
after=measure()
with connection() as db:
    sizes=dict(db.execute("SELECT relname,pg_relation_size(oid) FROM pg_class WHERE relname=ANY(%s::text[])",(list(index_names),)).fetchall())
    for name in index_names:
        db.execute('DROP INDEX public.'+name)
    final_security=db.execute("SELECT relname,relrowsecurity,relforcerowsecurity,relacl::text FROM pg_class WHERE oid IN ('public.pr_discord_rate_state'::regclass,'public.pr_discord_route_buckets'::regclass,'public.pr_discord_request_admissions'::regclass) ORDER BY relname").fetchall()
    assert final_security==initial_security
    for query,parameters,expected in queries.values():
        assert db.execute(query,parameters).fetchone()==expected


def used_indexes(node):
    found=[node['Index Name']] if 'Index Name' in node else []
    for child in node.get('Plans',[]):found+=used_indexes(child)
    return found


comparisons={name:{'beforeMedianMs':before[name]['medianExecutionMs'],'afterMedianMs':after[name]['medianExecutionMs'],
    'speedup':before[name]['medianExecutionMs']/max(after[name]['medianExecutionMs'],.000001),
    'candidateIndexesUsed':sorted(set(i for plan in after[name]['plans'] for i in used_indexes(plan['Plan']) if i in index_names))}
    for name in queries}
supported=any(v['speedup']>=1.2 and v['candidateIndexesUsed'] for v in comparisons.values())
warm_seed=None
locked_clock=None
scope_store=None
clock_mode=os.environ.get('RAFII_DISCORD_LOCKED_CLOCK_PROBE')=='1'
store_mode=os.environ.get('RAFII_DISCORD_SCOPE_STORE_PROBE')=='1'
if os.environ.get('RAFII_DISCORD_WARM_SEED_PROBE')=='1' or clock_mode or store_mode:
    from postriff_phase2.postgres_pool import PooledPostgresFactory
    from test_discord_rate_limits import synthetic_policy
    baseline_class=SharedPostgresBudget
    if clock_mode or store_mode:
        import postriff_phase2.discord.rate_limits as rate_module
        baseline_path=ROOT/'tests/phase2/fixtures/discord_rate_limits_baseline_ee30.py.txt'
        baseline_raw=baseline_path.read_bytes()
        assert hashlib.sha256(baseline_raw).hexdigest()=='2d9313b91e98444cdd389a22b780761d32f7bf7336e31a5679d199cc5742cad5'
        original=next(node for node in ast.parse(baseline_raw).body if isinstance(node,ast.ClassDef) and node.name=='SharedPostgresBudget')
        namespace=dict(rate_module.__dict__)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[original],type_ignores=[])),str(baseline_path),'exec'),namespace)
        baseline_class=namespace['SharedPostgresBudget']
    trials=[]
    # All locks, clocks, policy checks, debits, durable admissions, observations
    # and role resets run in both modes; use the pinned class for runtime changes.
    for trial,mode in enumerate(('baseline','candidate','candidate','baseline')):
        application=str(755500000000000000+trial)
        who=RequestIdentity.make(application,'bot','synthetic-warm-seed-'+str(trial))
        pool=PooledPostgresFactory(prior['DSN'],max_size=16,max_waiting=32,timeout=8,
            options='-c statement_timeout=10000 -c lock_timeout=5000')
        policy=synthetic_policy(prior['db_now']())
        policy.update(app_capacity=100000,app_window_seconds=60,unknown_window_seconds=10,
            permit_ttl_seconds=2,invalid_capacity=100000,egress_scope='synthetic-warm-seed-'+str(trial))
        counters={'seedStatements':0,'baselinePredicateRemoved':0,'standaloneClockStatements':0};count_lock=Lock()
        class Cursor:
            def __init__(self,inner):self.inner=inner
            def __enter__(self):self.inner.__enter__();return self
            def __exit__(self,*args):return self.inner.__exit__(*args)
            def __getattr__(self,key):return getattr(self.inner,key)
            def execute(self,query,parameters=None):
                if query.startswith('SELECT extract(epoch from clock_timestamp()'):
                    with count_lock:counters['standaloneClockStatements']+=1
                if query.startswith('WITH scope_seed('):
                    needle='WHERE EXISTS(SELECT 1 FROM scope_seed AS needed WHERE NOT EXISTS(SELECT 1 FROM public.pr_discord_rate_state AS existing WHERE existing.scope_key=needed.scope_key))'
                    if not (clock_mode or store_mode):assert query.count(needle)==1,'The exact reviewed warm-seed query is required'
                    with count_lock:
                        counters['seedStatements']+=1
                        if mode=='baseline' and not (clock_mode or store_mode):counters['baselinePredicateRemoved']+=1
                    if mode=='baseline' and not (clock_mode or store_mode):query=query.replace(needle,'')
                return self.inner.execute(query,parameters)
        class Database:
            def __init__(self,inner):self.inner=inner
            def cursor(self):return Cursor(self.inner.cursor())
            def __getattr__(self,key):return getattr(self.inner,key)
        @contextmanager
        def factory():
            with pool() as db:yield Database(db)
        budget_class=baseline_class if (clock_mode or store_mode) and mode=='baseline' else SharedPostgresBudget
        limiter=budget_class(factory,application,policy=policy)
        paths=['/channels/'+str(855500000000000000+i)+'/messages/955500000000000000' for i in range(16)]
        response={'status':200,'headers':{'X-RateLimit-Bucket':'synthetic-warm-seed-bucket',
            'X-RateLimit-Limit':'10000','X-RateLimit-Remaining':'9999','X-RateLimit-Reset-After':'60'}}
        try:
            with connection() as db:
                versions_before=int(db.execute('SELECT coalesce(sum(revision),0) FROM public.pr_discord_rate_state').fetchone()[0])
            for path in paths:
                permit=limiter.reserve_read('GET',path,identity=who);limiter.observe(permit,response)
            ready=Barrier(16);latencies=[];latency_lock=Lock()
            def reads(index):
                ready.wait(8)
                for _ in range(64):
                    began=time.monotonic()
                    permit=limiter.reserve_read('GET',paths[index],identity=who)
                    limiter.observe(permit,response)
                    with latency_lock:latencies.append(time.monotonic()-began)
            began=time.monotonic()
            with ThreadPoolExecutor(max_workers=16) as executor:list(executor.map(reads,range(16)))
            elapsed=time.monotonic()-began
            with connection() as db:
                states=db.execute('SELECT state,count(*) FROM public.pr_discord_request_admissions WHERE application_key=%s GROUP BY state',(_digest(application),)).fetchall()
                assert states==[('observed',1040)],states
                versions_after=int(db.execute('SELECT coalesce(sum(revision),0) FROM public.pr_discord_rate_state').fetchone()[0])
            assert len(latencies)==1024 and counters['seedStatements']==2080
            assert counters['baselinePredicateRemoved']==(2080 if mode=='baseline' and not (clock_mode or store_mode) else 0)
            if clock_mode:assert counters['standaloneClockStatements']==(3104 if mode=='baseline' else 1040),counters
            if store_mode:assert counters['standaloneClockStatements']==3104,counters
            trials.append({'mode':mode,'trial':trial,'replicas':16,'measuredRequests':1024,'warmupRequests':16,
                'elapsedSeconds':elapsed,'requestsPerSecond':1024/elapsed,
                'latencyMedianSeconds':statistics.median(latencies),'latencyMaxSeconds':max(latencies),
                'allAdmissionsObserved':True,'counters':dict(counters),'scopeRowsWritten':versions_after-versions_before,'httpRequests':0})
        finally:
            pool.close()
        assert pool.stats()['closed'] is True
    ratio=statistics.median(t['elapsedSeconds'] for t in trials if t['mode']=='baseline')/statistics.median(t['elapsedSeconds'] for t in trials if t['mode']=='candidate')
    comparison_result={'status':'PASS','candidateSupport':'SUPPORTED' if ratio>=1.10 else 'REJECTED',
        'supportThreshold':1.10,'baselineToCandidateElapsedRatio':ratio,'trials':trials,
        'baseline':'SHA-pinned original ee30 coordinator class' if (clock_mode or store_mode) else 'Exact warm-presence predicate removed only',
        'capacityAcceptance':'NOT_RUN','safetyLogic':'Real guards and post-admission clocks retained; temporary indexes removed before all trials'}
    if clock_mode:locked_clock=comparison_result
    elif store_mode:
        write_ratio=statistics.median(t['scopeRowsWritten'] for t in trials if t['mode']=='candidate')/statistics.median(t['scopeRowsWritten'] for t in trials if t['mode']=='baseline')
        comparison_result['candidateToBaselineRowWriteRatio']=write_ratio
        if write_ratio>.80:comparison_result['candidateSupport']='REJECTED'
        scope_store=comparison_result
    else:warm_seed=comparison_result
result={'status':'PASS','execution':'Actual disposable PostgreSQL17 diagnostic only; no capacity qualification',
    'candidateSupport':'SUPPORTED' if supported else 'REJECTED','syntheticCompletedHistory':ROWS,'unresolvedRows':32,'rounds':ROUNDS,
    'comparison':comparisons,'before':before,'after':after,'indexBytes':sizes,'securityMetadataUnchanged':True,
    'candidateIndexesRemoved':True,'priorRateGroups':len(prior['checks']),'priorWorkerGroups':len(prior['result']['workerChecks']),
    'warmSeedComparison':warm_seed,'lockedClockComparison':locked_clock,'scopeStoreComparison':scope_store,'realDiscordRequests':0,'productionDatabaseWrites':0,'productionReady':'NO','elapsedSeconds':time.monotonic()-started}
output=ROOT/'.depot/discord-admission-index-probe.json';output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(result,indent=2)+'\n')
print('RAFII_DISCORD_INDEX_DIAGNOSTIC '+json.dumps({k:v for k,v in result.items() if k not in ('before','after')}),flush=True)
