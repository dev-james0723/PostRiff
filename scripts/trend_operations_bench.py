"""Explicit local-only G13 storage load/fault measurement; never contacts providers.

Use a fresh trend_* database containing the disposable tests/phase2/rls.sql
baseline. Static population setup uses typed SQL copies; the measured burst,
reads, outbox/pipeline and faults use the real storage interfaces.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from postriff_phase2.growth.trends.contracts import PERMISSIONS, SCHEMA_VERSION, canonical, digest, iso
from postriff_phase2.growth.trends.store import TrendStore, TrendStorageError, utcnow
from postriff_phase2.growth.trends.jobs import TrendJobs, partition_key
from postriff_phase2.growth.trends.outbox import TrendOutbox
from postriff_phase2.growth.trends import operations, retention, revocation


def percentiles(values):
    values=sorted(values)
    def point(p):return round(values[max(0,math.ceil(p*len(values))-1)],3) if values else None
    return {'samples':len(values),'p50_ms':point(.5),'p95_ms':point(.95),'p99_ms':point(.99),'max_ms':max(values) if values else None}


def validate_local_dsn(dsn, *, environ=None):
    """Reject libpq redirection before any fixture writes or connection attempt."""
    environ=os.environ if environ is None else environ
    if any(name in environ for name in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS')):
        raise ValueError('local_g13_environment_override')
    if not isinstance(dsn,str):
        raise ValueError('dedicated_local_g13_database_required')
    try:
        params=conninfo_to_dict(dsn)
    except (psycopg.Error,TypeError,ValueError):
        raise ValueError('dedicated_local_g13_database_required') from None
    if (set(params)-{'host','port','dbname','user'} or params.get('host')!='127.0.0.1'
        or params.get('port')!='56451' or not re.fullmatch(r'trend_[A-Za-z0-9_]+',params.get('dbname',''))):
        raise ValueError('dedicated_local_g13_database_required')
    return params


def run(args):
    validate_local_dsn(args.dsn)
    if not 100<=args.population<=100000 or not 20<=args.workspaces<=1000 or not 20<=args.burst<=1000:
        raise ValueError('declared_fixture_bounds')
    source_paths=sorted((ROOT/'src/postriff_phase2/growth/trends').rglob('*.py'))+[
        Path(__file__).resolve(),ROOT/'migrations/postriff/040_social_trend_intelligence.sql']
    def source_hashes():
        return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    report={'execution':'local_postgresql_synthetic_no_external_calls','provider_calls':0,'model_calls':0,
        'source_sha256':source_hashes(),
        'schema_sha256':hashlib.sha256((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_bytes()).hexdigest(),
        'declared':{'stored_observations':args.population,'active_workspaces':args.workspaces,'burst_observations':args.burst,
                    'burst_target_seconds':60,'read_results':20,'concurrent_readers':4,'read_requests':80,
                    'read_p95_target_ms':500,'receipt_p95_target_ms':750,'pipeline_p95_target_ms':120000,
                    'population_setup':'typed_sql_fixture_copy_not_measured_ingestion','retention_days':5,
                    'planner_statistics':'explicit_ANALYZE_after_static_setup_before_measured_reads_and_burst'},
        'limitations':['loopback database; excludes HTTP/network/provider delay',
            'stored read fixtures use singleton-source dependencies; the 700-source pipeline lineage is measured separately',
            'capacity conditional on analyzed existing population; cold bulk-import statistics failure retained separately',
            'five-day fixture; 3M rows at 30-day retention and sustained 24-hour throughput are not tested',
            'method qualification remains shadow; performance does not qualify claims'],
        'fault_checks':[]}
    print(json.dumps({'declared':report['declared']}),flush=True)
    def checkpoint(stage):
        report['stage']=stage
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    checkpoint('declared')
    role='trend_load_'+uuid.uuid4().hex[:12]
    tenants=[(str(uuid.uuid4()),str(uuid.uuid4())) for _ in range(args.workspaces)]
    s='shared:load-'+uuid.uuid4().hex[:8]; provider='fixture-load'
    with psycopg.connect(args.dsn) as db:
        if db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            raise ValueError('fresh_baseline_without_040_required')
        db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        db.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER NOBYPASSRLS INHERIT').format(sql.Identifier(role)))
        db.execute(sql.SQL('GRANT service_role TO {}').format(sql.Identifier(role)))
        for table in ('pr_workspaces','pr_memberships','pr_profiles'):
            db.execute(sql.SQL('CREATE POLICY trend_load_service ON {} FOR ALL TO service_role USING(true) WITH CHECK(true)').format(sql.Identifier(table)))
        for wid,actor in tenants:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)',(actor,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(actor,))
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)',(wid,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(wid,actor))
    def connect():
        db=psycopg.connect(args.dsn)
        db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
        db.execute("SET statement_timeout='120s'")
        return db
    store=TrendStore(connect);jobs=TrendJobs(store);outbox=TrendOutbox(store)
    now=datetime.now(timezone.utc);start=iso(now-timedelta(days=1));end=iso(now+timedelta(days=5))
    rights={p:{'state':'allow','policy_ref':'load-v1','audience_scope':s,'expires_at':end} for p in PERMISSIONS}
    store.ensure_scope(s)
    for wid,_ in tenants:
        store.ensure_scope('workspace:'+wid)
        store.grant_entitlement(wid,s,['retrieve','derive_metrics','share_across_workspaces'],end)
    store.register_contract(provider,'v1',list(PERMISSIONS),start,end,{})
    store.register_policy({'scope_key':s,'provider_id':provider,'version':'v1','rights':rights,
        'effective_at':start,'expires_at':end,'retention_seconds':5*86400,'readiness':'ready'},provider_contract_version='v1')
    def observation(n):
        payload={'platform':'bluesky','native_id':'item-'+str(n),'author_status':'known','author_key':'did:fixture:'+str(n%100),
            'text':'Synthetic music rhythm conversation','canonical_url':'https://fixture.invalid/'+str(n),'language':'en'}
        return {'observation_id':str(uuid.uuid4()),'scope_key':s,'provider_id':provider,'provider_contract_version':'v1',
            'source_policy_version':'v1','source_identity':'item-'+str(n),'revision_identity':'r1','revision_sequence':1,
            'kind':'raw_post','operation':'create','event_at':iso(now-timedelta(minutes=1)),'received_at':utcnow(),'available_at':utcnow(),
            'time_basis':'provider_event','coverage_epoch':'load1','provenance':{'access_method':'fixture'},'retention_until':end,
            'rights':rights,'deletion_key':'item-'+str(n),'payload':payload,'payload_digest':digest(payload),'schema_version':SCHEMA_VERSION}
    template=observation(0);store.put_observation(template)
    # Fixture copies exercise real constraints and indexes at the declared size.
    # They are intentionally excluded from measured normalization throughput.
    with store.transaction() as cur:
        cur.execute("INSERT INTO pr_trend_nodes SELECT scope_key,md5('load-seed-'||g)::uuid,node_kind,available_at,retention_until,validity FROM pr_trend_nodes CROSS JOIN generate_series(1,%s) g WHERE node_id=%s",(args.population-1,template['observation_id']))
        cur.execute('SELECT * FROM pr_trend_observations LIMIT 0');columns=[c.name for c in cur.description]
        overrides={'observation_id':"md5('load-seed-'||g)::uuid",'source_identity':"'load-seed-'||g",
            'source_identity_digest':"encode(sha256(convert_to('load-seed-'||g,'UTF8')),'hex')",'native_item_id':"'load-seed-'||g",
            'deletion_key':"'load-seed-'||g",'payload':"jsonb_set(o.payload,'{native_id}',to_jsonb('load-seed-'||g))",
            'payload_digest':"encode(sha256(convert_to(replace(%s,'__load_native__','load-seed-'||g),'UTF8')),'hex')"}
        select=[sql.SQL(overrides[c]) if c in overrides else sql.Identifier('o',c) for c in columns]
        cur.execute(sql.SQL('INSERT INTO pr_trend_observations ({}) SELECT {} FROM pr_trend_observations o CROSS JOIN generate_series(1,%s) g WHERE observation_id=%s').format(
            sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(select)),
            (canonical({**template['payload'],'native_id':'__load_native__'}),args.population-1,template['observation_id']))
        cur.execute('INSERT INTO pr_trend_source_heads SELECT scope_key,provider_id,source_identity_digest,revision_sequence,observation_id FROM pr_trend_observations ON CONFLICT DO NOTHING')
    print('typed fixture population ready',flush=True)
    artifact=digest({'load_fixture_method':1});store.put_method('fixture.load','v1',artifact,{})
    cutoff=utcnow();manifest=store.put_manifest(s,[{'scope_key':s,'node_id':template['observation_id']}],decision_cutoff=cutoff,available_at=cutoff,retention_until=end)
    common={'scope_key':s,'revision':1,'manifest_id':manifest['manifest_id'],'method_id':'fixture.load','method_version':'v1',
        'decision_cutoff':cutoff,'available_at':cutoff,'retention_until':end}
    receipt_payload={'schema':'rafii.trend-trust-receipt.v2','inferred':{'data_state':'insufficient'},'observed':{'count':1}}
    rid=store.put_receipt({**common,'receipt_id':str(uuid.uuid4()),'payload':receipt_payload})
    store.record_verification(s,rid,recomputed_digest=digest(receipt_payload),input_manifest_digest=manifest['digest'],method_artifact_digest=artifact)
    # This receipt tests durable preverified read latency, not scientific accuracy.
    objects=[]
    with store.transaction() as cur:
        for n in range(100):
            obj=str(uuid.uuid4());objects.append(obj)
            store.put_projection({**common,'kind':'trend','object_id':obj,'receipt_id':rid,
                'payload':{'canonical_topic':'Synthetic music','platform':'bluesky','language':'en','stage':None}},cursor=cur)
    # Static SQL loading is fixture preparation, not the declared 700-row burst.
    # Normal planner statistics are an explicit prerequisite for an existing
    # 100k population. Never hide the separately archived cold-import failure.
    with psycopg.connect(args.dsn) as db:
        for table in ('pr_workspaces','pr_memberships','pr_profiles','pr_trend_scopes','pr_trend_entitlements',
                      'pr_trend_provider_contracts','pr_trend_source_policies','pr_trend_method_versions',
                      'pr_trend_nodes','pr_trend_observations','pr_trend_source_heads','pr_trend_dependencies',
                      'pr_trend_input_manifests','pr_trend_manifest_inputs','pr_trend_trust_receipts','pr_trend_projections'):
            db.execute(sql.SQL('ANALYZE {}').format(sql.Identifier(table)))
    print('static population ANALYZE complete; measured reads and burst begin',flush=True)
    times={'list':[],'detail':[],'receipt':[]}
    def read(i):
        wid,actor=tenants[i%len(tenants)];found={}
        for name,fn in [('list',lambda:store.list_projections(wid,actor,limit=20)),
                        ('detail',lambda:store.get_projection(wid,actor,'trend',objects[i%len(objects)])),
                        ('receipt',lambda:store.get_receipt(wid,actor,rid))]:
            t=time.perf_counter();value=fn();found[name]=(time.perf_counter()-t)*1000
            assert len(value['items'])==20 if name=='list' else value['validity']=='valid'
        return found
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(read,range(80)):
            for key,value in result.items():times[key].append(value)
    report['stored_reads']={k:percentiles(v) for k,v in times.items()}
    checkpoint('stored_reads')
    print(json.dumps({'stored_reads':report['stored_reads']}),flush=True)
    # Burst uses actual admission/fence/normalization/cursor/outbox transaction.
    controls=jobs.enqueue(s,'trend.ingest',{},idempotency_key='load-burst',provider_id=provider,source_policy_version='v1')
    claim=jobs.start(jobs.claim('load',job_id=controls['job_id'],lease_seconds=300))
    burst=[observation(i+args.population) for i in range(args.burst)]
    part=partition_key(instance_id='fixture.invalid',protocol_version='v1',filter_digest='load')
    began=time.perf_counter()
    jobs.complete_batch(claim,partition_key=part,expected_generation=0,batch_key='load-burst',observations=burst,cursor_value={'page':1},
        terminal_page=True,coverage_state='complete',outbox_events=[{'event_key':'load-ingested','event_type':'trend.ingested',
            'payload':{'observation_ids':[o['observation_id'] for o in burst],'coverage_epoch':'load1','completeness':'complete'}}])
    report['burst']={'rows':args.burst,'seconds':round(time.perf_counter()-began,3)}
    checkpoint('burst')
    # Real bounded consumer and continuation processing, no synthetic HTTP adapter.
    from postriff_phase2.growth.trends.pipeline import TrendPipeline
    pipeline=TrendPipeline(store,max_observations=args.burst,max_new_memberships=100,max_episodes=1)
    pipeline_times=[];pipeline_started=time.perf_counter();consumed=0
    pipeline_error=None
    try:
        while consumed<20:
            event=outbox.claim('load-pipeline','load',lease_seconds=300)
            if not event:break
            t=time.perf_counter();outbox.consume(event,pipeline.consume);pipeline_times.append((time.perf_counter()-t)*1000);consumed+=1
    except (psycopg.Error,ValueError) as exc:
        pipeline_error=getattr(exc,'code',type(exc).__name__)
    assert consumed<20,'continuation_not_bounded'
    report['pipeline']={'events':consumed,'consumer':percentiles(pipeline_times),'error':pipeline_error,
        'burst_to_final_seconds':round(time.perf_counter()-pipeline_started,3)}
    checkpoint('pipeline')
    print(json.dumps({'burst':report['burst'],'pipeline':report['pipeline']}),flush=True)
    # An expired lease cannot commit any transactional downstream effect.
    outbox.enqueue(s,'load-fault','trend.fixture',{})
    ev=outbox.claim('load-fault','crashed',lease_seconds=1)
    with connect() as db:db.execute("UPDATE pr_trend_outbox_consumers SET lease_until=clock_timestamp()-interval '1 second' WHERE consumer='load-fault'")
    try:outbox.consume(ev,lambda cur,e:jobs.enqueue(s,'trend.local',{},idempotency_key='must-not-commit',cursor=cur))
    except TrendStorageError:pass
    else:raise AssertionError('stale_consumer_committed')
    with connect() as db:assert db.execute("SELECT count(*) FROM pr_trend_jobs WHERE idempotency_key='must-not-commit'").fetchone()[0]==0
    report['fault_checks'].append('zero_stale_outbox_effects')
    t=time.perf_counter();clean=retention.sweep(store,limit=100)
    report['maintenance_no_invalid']={'seconds':round(time.perf_counter()-t,3),'purged_nodes':clean['purged_nodes']}
    assert clean['purged_nodes']==0,'valid_population_purged'
    checkpoint('maintenance_no_invalid')
    t=time.perf_counter();revocation.revoke_source(store,s,provider,'item-0',purge_deadline=end)
    wid,actor=tenants[0];assert store.get_projection(wid,actor,'trend',objects[0])['payload'] is None
    report['fault_checks'].append('immediate_revocation_read_suppression')
    for _ in range(20):
        purged=retention.sweep(store,limit=100)
        if not purged['purged_nodes']:break
    with connect() as db:
        assert db.execute('SELECT payload FROM pr_trend_observations WHERE observation_id=%s',(template['observation_id'],)).fetchone()[0]=={}
        assert db.execute('SELECT payload,verification_record FROM pr_trend_trust_receipts WHERE receipt_id=%s',(rid,)).fetchone()==({},{})
    report['fault_checks'].append('bounded_physical_purge_receipt_and_observation')
    report['purge_seconds']=round(time.perf_counter()-t,3)
    t=time.perf_counter();report['operations']=operations.snapshot(store)
    report['operations_ms']=round((time.perf_counter()-t)*1000,3)
    assert not any(value in json.dumps(report['operations']) for value in ('did:fixture:','fixture.invalid','Synthetic music',s,tenants[0][0]))
    with connect() as db:assert db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()==(False,False)
    report['fault_checks'].append('non_owner_non_bypass_forced_rls')
    # Guard the code actually imported by this run. Concurrent owners may edit
    # unrelated trend modules; this benchmark makes no claim about those files.
    used={str(Path(m.__file__).resolve().relative_to(ROOT)) for name,m in list(sys.modules.items())
        if name.startswith('postriff_phase2.growth.trends') and getattr(m,'__file__',None)
        and Path(m.__file__).resolve().is_relative_to(ROOT)}
    used.update({'scripts/trend_operations_bench.py','migrations/postriff/040_social_trend_intelligence.sql'})
    # implementation_methods also binds source artifacts even when a particular
    # Python module is not executed on this synthetic branch.
    used.update('src/postriff_phase2/growth/trends/'+name+'.py' for name in (
        'contracts','metrics','methods','receipts','clustering','embeddings','membership','pipeline','service',
        'baselines','momentum','lifecycle','confidence'))
    report['source_sha256']={k:v for k,v in report['source_sha256'].items() if k in used}
    final_hashes=source_hashes()
    report['source_hash_scope']='imported_trend_modules_and_pipeline_method_bound_artifacts_plus_benchmark_and_040'
    report['source_guard_unchanged']=all(final_hashes.get(k)==v for k,v in report['source_sha256'].items()) and used<=report['source_sha256'].keys()
    report['target_results']={'list':report['stored_reads']['list']['p95_ms']<=500,
        'detail':report['stored_reads']['detail']['p95_ms']<=500,'receipt':report['stored_reads']['receipt']['p95_ms']<=750,
        'burst':report['burst']['seconds']<=60,
        'pipeline':not pipeline_error and report['pipeline']['burst_to_final_seconds']<=120,
        'maintenance_no_invalid':report['maintenance_no_invalid']['seconds']<=6,
        'source_guard_unchanged':report['source_guard_unchanged']}
    report['status']='pass_declared_local_load' if all(report['target_results'].values()) else 'targets_missed'
    checkpoint('complete')
    print(json.dumps({'status':report['status'],'targets':report['target_results'],'output':str(args.output)}),flush=True)
    return 0 if report['status']=='pass_declared_local_load' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn',default=os.environ.get('TREND_TEST_DSN',''))
    parser.add_argument('--population',type=int,default=100000)
    parser.add_argument('--workspaces',type=int,default=1000)
    parser.add_argument('--burst',type=int,default=700)
    parser.add_argument('--output',type=Path,required=True)
    sys.exit(run(parser.parse_args()))
