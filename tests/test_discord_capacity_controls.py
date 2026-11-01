"""Tiny inert P8 controls; no SQL, users, real provider calls or load cohort."""
import sys
import ast
import copy
import hashlib
import io
import json
import re
import threading
import time
from collections import Counter
import unittest
from contextlib import nullcontext,redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2.postgres_discord_capacity import (
    DSN, Incomplete, FixtureCancelled, FixtureLedger, HarnessInterrupted, Runtime, accounting, arrivals, burst_offsets, budget_lower_bound,
    collect_fixture_cohort, connection_diagnostic_profile, configure_candidate_provider,
    diagnostic, diagnostic_phase, distribution, fingerprint, MockDiscord, TimedCursor,
    profile, rate_metadata, require_fixture, sql_metadata, validate_fence,
    SpawnMockTransport, Telemetry, absorb_worker_metrics, combined_transport_fence,
    send_worker_message, receive_worker_message, validate_worker_summary,
    reap_owned_workers, start_owned_worker,
    selected_profile, validate_worker_budget, planned_worker_groups,planned_api_groups,
    admission_diagnostic_profile, admission_margin, sql_statement_category, _sql_statement_category,
    api_fixture,api_preview,api_result,api_event,valid_api_request,combined_api_fence,
)


class CapacityControls(unittest.TestCase):
    def test_full_api_resource_plan_preserves_targets_and_requires_all_process_proofs(self):
        expected={'a':'7c6b59ce388ba905bc58c32b953a50a872d9b69235fcc13faa36a09074dccd0b',
            'pipeline-qualification':'c35cf3d859973627e56ee869e2fd7d93cb4c0125f23846b7ea83cccd94b05c00',
            'b':'3979e3fac0e2f939be77922d3dc552d13cf3219dc1c46f4b8611c8e5713738e3'}
        resources={'version','resourcePlan','resourceChange','parentPoolSize','aggregateConnectionCap',
            'apiReplicas','apiPoolSize','runnerSize','cpu','memoryGiB','computeUsdPerSecond','jobTimeoutMinutes'}
        for stage,digest in expected.items():
            p=selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':
                'b-extended-workers16-api12-v5' if stage=='b' else 'workers16-api12-v5'})
            historical=selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':
                'b-extended-workers16-parent16-v4' if stage=='b' else 'workers16-parent16-v4'})
            self.assertEqual(fingerprint(p),digest)
            self.assertEqual({k:v for k,v in p.items() if k not in resources},
                {k:v for k,v in historical.items() if k not in resources})
            self.assertEqual(validate_worker_budget(p),1)
            self.assertEqual(planned_worker_groups(p),[('comparison-1',1),('comparison-4',4),('burst',16),('sustained',16)])
            self.assertEqual(planned_api_groups(p),[(phase,12) for phase in ('comparison-1','comparison-4','burst','sustained')])
            for key,value in [('apiReplicas',13),('apiPoolSize',2),('parentPoolSize',5),('aggregateConnectionCap',33),('stage','safety')]:
                bad=copy.deepcopy(p);bad[key]=value
                with self.assertRaises(Incomplete):validate_worker_budget(bad)
        template=SimpleNamespace(p=admission_diagnostic_profile(api=True),api_summaries=[],api_child_fences=[])
        for phase,_ in planned_api_groups(p):
            workers=[{'pid':n+1,'status':'PASS','error':None,'poolStats':{'closed':True,'maxConnections':1},
                'transportFence':{'unexpectedAttempts':0,'expectedSelfCheckDenials':4}} for n in range(12)]
            template.api_summaries.append({'phase':phase,'replicas':12,'status':'PASS','parentConnectionCap':4,
                'aggregateConnectionCap':32,'perReplicaConnectionCap':1,'workers':workers,
                'cleanup':{'forcedCount':0,'killCount':0,'survivingPids':[],'unfinishedBrokers':0,'errors':[]}})
            template.api_child_fences.extend({'phase':phase,'pid':n+1,'unexpectedAttempts':0,'expectedSelfCheckDenials':4} for n in range(12))
        template.p=p
        self.assertEqual(combined_api_fence(template)['expectedApiProcesses'],48)
        self.assertEqual(combined_api_fence(template)['status'],'PASS')
        for mutate in (lambda r:r.api_summaries.pop(),lambda r:r.api_child_fences.pop(),
                lambda r:r.api_summaries[3]['workers'][0]['poolStats'].update(closed=False),
                lambda r:r.api_summaries[3]['cleanup'].update(forcedCount=1)):
            bad=copy.deepcopy(template);mutate(bad)
            self.assertEqual(combined_api_fence(bad)['status'],'FAIL')

    def test_api_process_boundaries_and_complete_evidence(self):
        p=admission_diagnostic_profile(api=True)
        self.assertEqual((p['apiReplicas'],p['apiPoolSize'],p['parentPoolSize'],p['workerPoolSize'],p['aggregateConnectionCap']),
            (12,1,4,1,32))
        self.assertEqual(validate_worker_budget(p),1)
        self.assertEqual(planned_worker_groups(p),[('admission-smoke',16),('admission-burst',16)])
        for key,value in [('apiReplicas',13),('apiReplicas',True),('apiPoolSize',2),('parentPoolSize',5),('aggregateConnectionCap',33),('stage','b')]:
            changed=copy.deepcopy(p);changed[key]=value
            with self.assertRaises(Incomplete):validate_worker_budget(changed)
        f={'index':0,'workspace':'workspace-a','user':'user-a','token':'synthetic-session',
            'destinations':[('connection-a','guild-a','channel-a')]*6,'service':object(),'lock':object()}
        packed=api_fixture(f)
        self.assertEqual(set(packed),{'index','workspace','user','token','destinations'})
        packed['destinations'].append(('other','other','other'));self.assertEqual(len(f['destinations']),6)
        request={'index':0,'alias':'admission-burst-0','due':100.,'phase':'admission-burst',
            'arrival':80.,'destination':0,'submittedAt':80.}
        self.assertTrue(valid_api_request(request,'admission-burst',{0}))
        for key,value in [('index',1),('index',True),('destination',True),('destination',6),('due',float('nan')),
                ('phase','other'),('token','private-input'),('alias','invalid / alias')]:
            bad=copy.deepcopy(request);bad[key]=value
            self.assertFalse(valid_api_request(bad,'admission-burst',{0}))
        manifest={'workspaceId':'workspace-a','actor':'user-a','platform':'Discord','channelId':'connection-a',
            'idempotencyKey':'synthetic-idempotency','timing':{'timestamp':100.},
            'discord':{'publicationId':'job-a','target':{'guildId':'guild-a','channelId':'channel-a',
                'applicationId':'718000000000000001','botUserId':'718000000000000002','linkedUserId':'720000000000000000'}}}
        record={'alias':'admission-burst-0','phase':'admission-burst','fixture':f,'due':100.,'frozen':None}
        nonce=hashlib.sha256(manifest['idempotencyKey'].encode()).hexdigest()[:25]
        preview={'alias':record['alias'],'nonce':nonce,'manifest':manifest,'expectedJobId':'job-a'}
        self.assertEqual(api_preview(record,preview,0),(nonce,manifest,'job-a'))
        mutations=[lambda v:v.update(alias='other'),lambda v:v.update(nonce='other'),lambda v:v.update(expectedJobId='other'),
            lambda v:v['manifest'].update(workspaceId='foreign'),lambda v:v['manifest'].update(actor='foreign'),
            lambda v:v['manifest'].update(channelId='other'),lambda v:v['manifest']['timing'].update(timestamp=101.)]
        for key in ('guildId','channelId','applicationId','botUserId','linkedUserId'):
            mutations.append(lambda v,key=key:v['manifest']['discord']['target'].update({key:'foreign'}))
        for mutate in mutations:
            bad=copy.deepcopy(preview);mutate(bad)
            with self.assertRaises(Incomplete):api_preview(record,bad,0)
        registered={**record,'manifest':manifest,'expectedJobId':'job-a'}
        with self.assertRaises(Incomplete):api_preview(registered,preview,0)
        completed={'alias':record['alias'],'jobId':'job-a','approvedAt':90.,'frozen':{'digest':'a'*64},'processing':.2,'error':None}
        self.assertEqual(api_result(registered,completed)['jobId'],'job-a')
        for key,value in [('alias','other'),('jobId','other'),('approvedAt',True),('processing',float('nan')),('frozen',None),('error','RuntimeError')]:
            bad=copy.deepcopy(completed);bad[key]=value
            with self.assertRaises(Incomplete):api_result(registered,bad)
        observed={**registered,'frozen':{'digest':'b'*64}}
        with self.assertRaises(Incomplete):api_result(observed,completed)
        failed={'alias':record['alias'],'jobId':None,'approvedAt':None,'frozen':None,'processing':None,'error':'AlphaError'}
        self.assertIsNone(api_result(registered,failed)['jobId'])
        with self.assertRaises(Incomplete):api_result(observed,failed)
        event={'name':'approval','fields':{'alias':record['alias'],'phase':record['phase'],
            'payloadHash':'a'*64,'authorizationHash':'b'*64}}
        self.assertEqual(api_event(record,event,record['phase'])[0],'approval')
        bad=copy.deepcopy(event);bad['fields']['payloadHash']='private-input'
        with self.assertRaises(Incomplete):api_event(record,bad,record['phase'])
        failed_event={'name':'approval-failed','fields':{'alias':record['alias'],'phase':record['phase'],
            'error':{'type':'RuntimeError','frames':[{'file':'api.py','line':1,'function':'run'}]}}}
        self.assertEqual(api_event(record,failed_event,record['phase'])[0],'approval-failed')
        failed_event['fields']['error']['message']='private-input'
        with self.assertRaises(Incomplete):api_event(record,failed_event,record['phase'])
        groups=[];fences=[]
        for phase in ('admission-smoke','admission-burst'):
            workers=[{'pid':n+1,'status':'PASS','error':None,'poolStats':{'closed':True,'maxConnections':1},
                'transportFence':{'unexpectedAttempts':0,'expectedSelfCheckDenials':4}} for n in range(12)]
            groups.append({'phase':phase,'replicas':12,'status':'PASS','parentConnectionCap':4,
                'aggregateConnectionCap':32,'perReplicaConnectionCap':1,'workers':workers,
                'cleanup':{'forcedCount':0,'killCount':0,'survivingPids':[],'unfinishedBrokers':0,'errors':[]}})
            fences.extend({'phase':phase,'pid':n+1,'unexpectedAttempts':0,'expectedSelfCheckDenials':4} for n in range(12))
        runtime=SimpleNamespace(p=p,api_summaries=groups,api_child_fences=fences)
        self.assertEqual(combined_api_fence(runtime)['status'],'PASS')
        for mutate in [lambda r:r.api_summaries.pop(),lambda r:r.api_child_fences.pop(),
                lambda r:r.api_summaries[0]['cleanup'].update(forcedCount=1),
                lambda r:r.api_summaries[0]['workers'][0]['poolStats'].update(closed=False),
                lambda r:r.api_summaries[0]['workers'][0]['poolStats'].update(maxConnections=2),
                lambda r:r.api_summaries[0]['workers'][0].update(pid=2),
                lambda r:r.api_child_fences[0].update(unexpectedAttempts=1)]:
            bad=copy.deepcopy(runtime);mutate(bad)
            self.assertEqual(combined_api_fence(bad)['status'],'FAIL')

    def test_cached_sql_categories_keep_each_invocations_expiry_and_error(self):
        observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private parameter must not enter evidence')
        metrics=SimpleNamespace(count=lambda *a:None,timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        query='WITH scope_store AS (SELECT 1), inserted_admission AS (SELECT 1) SELECT 1'
        _sql_statement_category.cache_clear()
        for expiry in (42.,43.,float('nan'),True):
            with self.assertRaises(RuntimeError):cursor.execute(query,('private-token',expiry))
        self.assertEqual(observed,[('reservation_commit_batch',42.),('reservation_commit_batch',43.),
            ('reservation_commit_batch',None),('reservation_commit_batch',None)])
        self.assertGreaterEqual(_sql_statement_category.cache_info().hits,3)
        self.assertNotIn('private',str(observed))

    def test_sql_template_cache_has_fixed_entry_and_byte_bounds(self):
        _sql_statement_category.cache_clear()
        sql_statement_category('SELECT '+(' ' * 17000))
        self.assertEqual(_sql_statement_category.cache_info().currsize,0)
        for n in range(300):self.assertEqual(sql_statement_category('SELECT '+str(n)),'other')
        self.assertEqual(_sql_statement_category.cache_info().currsize,256)

    def test_atomic_sql_observer_preserves_concurrent_denominators_and_failures(self):
        metrics=Telemetry(capture_events=False)
        errors=[]
        def work():
            try:
                def execute(_query,index):
                    if index==0:raise RuntimeError('private SQL/parameter')
                cursor=TimedCursor(SimpleNamespace(execute=execute),metrics)
                for n in range(50):
                    try:cursor.execute('SELECT observer_control',n)
                    except RuntimeError:pass
            except BaseException as error:errors.append(type(error).__name__)
        threads=[threading.Thread(target=work) for _ in range(8)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=2)
        self.assertFalse(errors or any(thread.is_alive() for thread in threads))
        self.assertEqual(metrics.counters['sqlStatements'],400)
        self.assertEqual(metrics.counters['sqlOperation.other'],400)
        self.assertEqual(metrics.counters['sqlErrors.RuntimeError'],8)
        self.assertEqual(len(metrics.timings['sqlExecuteSeconds']),400)
        self.assertEqual(metrics.sql_operation_seconds['other']['count'],400)
        self.assertEqual(metrics.phase_sql_operation_seconds['fixture']['other']['count'],400)
        self.assertEqual(len(metrics.sql_failures),8)
        self.assertNotIn('private',json.dumps(metrics.summary()))

    def test_pool_reset_is_an_observed_statement_without_dropped_cost(self):
        runtime=SimpleNamespace(m=Telemetry(capture_events=False))
        Runtime.pool_statement(runtime,'pool_reset',.25,None)
        self.assertEqual(runtime.m.counters['sqlStatements'],1)
        self.assertEqual(runtime.m.timings['sqlExecuteSeconds'],[.25])
        self.assertEqual(runtime.m.phase_sql_operation_seconds['fixture']['pool_reset'],
            {'count':1,'totalSeconds':.25,'maxSeconds':.25})

    def test_admission_probe_cannot_substitute_for_full_geometry_or_profiles(self):
        env={'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'workers16-parent16-v4'}
        before={stage:fingerprint(selected_profile(stage,env)) for stage in ('a','pipeline-qualification')}
        b=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-workers16-parent16-v4'})
        p=admission_diagnostic_profile()
        self.assertEqual((p['stage'],p['users'],p['burstJobs']),('admission-diagnostic',1000,10000))
        self.assertEqual((p['burstScheduleLeadSeconds'],p['burstSubmissionSeconds'],p['burstDrainSeconds']),
            (b['burstScheduleLeadSeconds'],b['burstSubmissionSeconds'],b['burstDrainSeconds']))
        self.assertEqual(p['mock'],b['mock']);self.assertEqual(p['targets'],b['targets'])
        self.assertEqual(p['minimumApprovalMarginSeconds'],15)
        self.assertEqual(planned_worker_groups(p),[('admission-burst',16)])
        self.assertNotEqual(fingerprint(p),fingerprint(b))
        self.assertEqual(before,{stage:fingerprint(selected_profile(stage,env)) for stage in before})
        self.assertIn('NOT_RUN',p['purpose'])

    def test_approval_margin_keeps_missing_and_late_work_in_denominator(self):
        records=[{'jobId':'a','due':60.,'approvedAt':40.},{'jobId':'b','due':60.,'approvedAt':44.}]
        self.assertEqual(admission_margin(records,2),16.)
        self.assertIsNone(admission_margin(records,3))
        for bad in (None,float('nan'),True):
            changed=copy.deepcopy(records);changed[1]['approvedAt']=bad
            self.assertIsNone(admission_margin(changed,2))
        records[1]['approvedAt']=65.
        self.assertEqual(admission_margin(records,2),-5.)
        records[1]['jobId']=None
        self.assertIsNone(admission_margin(records,2))

    def test_burst_producer_keeps_full_cohort_inside_original_window_with_timer_jitter(self):
        jitter = .001614
        self.assertGreaterEqual(9999 * 10 / 10000 + jitter, 10.)
        for count, seconds in ((8, 1), (1000, 5), (10000, 10)):
            with self.subTest(count=count, seconds=seconds):
                offsets = burst_offsets(count, seconds)
                self.assertEqual(len(offsets), count)
                self.assertEqual(offsets[0], 0.)
                self.assertTrue(all(a < b for a, b in zip(offsets, offsets[1:])))
                self.assertLess(offsets[-1] + jitter, seconds)
        for count, seconds in ((0, 10), (True, 10), (1, 0), (1, float('nan')), (1, float('inf'))):
            with self.assertRaises(ValueError):
                burst_offsets(count, seconds)

    def test_admission_burst_enforces_original_latency_drain_and_submission_gates(self):
        runtime=Runtime.__new__(Runtime)
        runtime.p=admission_diagnostic_profile();runtime.m=SimpleNamespace(event=lambda *args,**kwargs:None)
        records=[{'alias':str(n),'jobId':str(n),'due':100.,'postAt':101.,
            'approvedAt':80.,'requestedAt':70.,'submittedAt':float(n),'processing':.1}
            for n in range(2)]
        states={str(n):'verified' for n in range(2)}
        def observe(now):
            with patch('phase2.postgres_discord_capacity.time.time',return_value=now):
                return Runtime.cohort_result(runtime,'admission-burst',records,states,400.,16,True)
        result=observe(102.)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(set(result['gates']),{'accountingAndEligibleDelivery',
            'dispatchP95','dispatchP99','drain','submissionWindow'})
        for limit in (10.,10.000613927841187,11.):
            records[1]['submittedAt']=limit
            result=observe(102.)
            self.assertFalse(result['gates']['submissionWindow'])
            self.assertEqual(result['status'],'FAIL')
        records[1]['submittedAt']=1.
        for now in (400.,401.):
            result=observe(now)
            self.assertFalse(result['gates']['drain'])
            self.assertEqual(result['status'],'FAIL')
        records[1]['postAt']=341.
        result=observe(102.)
        self.assertFalse(result['gates']['dispatchP95'])
        self.assertFalse(result['gates']['dispatchP99'])
        self.assertEqual(result['status'],'FAIL')

    def test_full_burst_cannot_reuse_a_smaller_fixture(self):
        runtime=SimpleNamespace(fixtures=[object()],p={'seed':1,'stage':'b'})
        with self.assertRaises(Incomplete):Runtime.burst(runtime,16,'burst',2)

    def test_compact_state_observation_preserves_missing_and_unrequested_jobs(self):
        runtime=Runtime.__new__(Runtime);runtime.m=Telemetry(capture_events=False)
        calls=[]
        def execute(query,parameters):
            calls.append(parameters)
            return SimpleNamespace(fetchall=lambda:[('one','verified'),('two','held'),('unrequested','verified')])
        runtime.connection=lambda:nullcontext(SimpleNamespace(execute=execute))
        records=[{'jobId':'one','alias':'first','fixture':{'workspace':'workspace-a'}},
                 {'jobId':'two','alias':'second','fixture':{'workspace':'workspace-b'}},
                 {'jobId':'missing','alias':'third','fixture':{'workspace':'workspace-a'}},
                 {'jobId':None,'alias':'unadmitted','fixture':{'workspace':'workspace-c'}}]
        observed=runtime.job_states(records)
        self.assertEqual(observed,{'first':'verified','second':'held'})
        self.assertEqual(len(calls),1);self.assertEqual(set(calls[0][0]),{'workspace-a','workspace-b'})
        self.assertFalse(accounting(4,3,observed.values())['complete'])
        self.assertEqual(runtime.m.counters['capacityJobStatePolls'],1)
        self.assertEqual(runtime.m.counters['capacityJobStatePollRows'],3)
        self.assertEqual(len(runtime.m.timings['capacityJobStatePollSeconds']),1)
        self.assertEqual(runtime.job_states([records[-1]]),{})
        self.assertEqual(len(calls),1)

    def test_post_start_failure_is_registered_before_cancellation_restores(self):
        for fail_on_start in (False,True):
            owned,registry,reported,order=[],{},set(),[]
            process=SimpleNamespace(pid=None)
            def start():
                process.pid=123
                if fail_on_start:raise Incomplete('synthetic post-start failure')
            process.start=start
            def close():
                self.assertEqual(owned,[process]);self.assertIs(registry[123],process)
                order.append('registered-close')
                raise Incomplete('synthetic close failure')
            def mask(action,values):
                if order:
                    self.assertIs(registry[123],process);order.append('restored')
                return set()
            with patch('phase2.postgres_discord_capacity.signal.pthread_sigmask',side_effect=mask):
                with self.assertRaises(Incomplete):start_owned_worker(process,SimpleNamespace(close=close),owned,registry,threading.RLock(),reported)
            self.assertEqual(order,['registered-close','restored'])

    def test_owned_worker_cleanup_has_shared_deadlines_and_reports_survivors(self):
        class Handle:
            def __init__(self,pid,unkillable=False):
                self.pid,self.unkillable=pid,unkillable
                self.alive=True;self.exitcode=None;self.actions=[]
            def join(self,timeout):clock[0]+=timeout if self.alive else 0
            def is_alive(self):return self.alive
            def terminate(self):self.actions.append('terminate')
            def kill(self):
                self.actions.append('kill')
                if not self.unkillable:self.alive=False;self.exitcode=-9
        for unkillable in (False,True):
            clock=[0.];handles=[Handle(i,unkillable) for i in range(8)]
            with patch('phase2.postgres_discord_capacity.time.monotonic',side_effect=lambda:clock[0]):
                result=reap_owned_workers(handles,[])
            self.assertLessEqual(clock[0],18.)
            self.assertEqual((result['forcedCount'],result['killCount']),(8,8))
            self.assertEqual(result['survivingPids'],list(range(8)) if unkillable else [])
            self.assertTrue(all(h.actions==['terminate','kill'] for h in handles))

    def test_spawn_transport_response_identity_and_route_are_fail_closed(self):
        class Channel:
            def __init__(self):self.sent=[];self.response=['response',{'requestId':2,'response':{}}]
            def send_bytes(self, value):self.sent.append(json.loads(value))
            def poll(self, _timeout):return True
            def recv_bytes(self, _maximum):return json.dumps(self.response).encode()
        channel=Channel();metrics=Telemetry(capture_events=False)
        transport=SpawnMockTransport(channel,metrics)
        with self.assertRaises(Incomplete):transport('GET','https://discord.com/api/v10/guilds/123')
        self.assertEqual(metrics.counters['unexpectedTransport'],1)
        self.assertEqual(channel.sent[0][1]['requestId'],1)
        with self.assertRaises(Incomplete):transport('POST','https://foreign.example.invalid/messages')
        self.assertEqual(len(channel.sent),1)
        channel.response=['response',{'requestId':2,'response':{'status':200}}]
        self.assertEqual(transport('GET','https://discord.com/api/v10/guilds/123'),{'status':200})

    def test_worker_protocol_bounds_and_metric_merge_preserve_denominators(self):
        class Channel:
            def __init__(self):self.values=[]
            def send_bytes(self,value):self.values.append(value)
            def recv_bytes(self,maximum):return self.values.pop(0)
        channel=Channel()
        with patch('phase2.postgres_discord_capacity.WORKER_PIPE_BYTES',32):
            with self.assertRaises(Incomplete):send_worker_message(channel,'http','x'*64)
        send_worker_message(channel,'step-start',None)
        self.assertEqual(receive_worker_message(channel),['step-start',None])
        metrics=Telemetry(capture_events=False);metrics.timing('workerStepSeconds',10.)
        payload={'counters':{'sqlStatements':2},'timings':{'workerStepSeconds':[1.,3.]},
            'peak':{'databaseConnections':2},'sqlFailures':[],
            'sqlOperations':{'scope_lock_batch':{'count':2,'totalSeconds':.5,'maxSeconds':.3}}}
        absorb_worker_metrics(metrics,payload,'burst')
        self.assertEqual(metrics.timings['workerStepSeconds'],[10.,1.,3.])
        self.assertEqual(metrics.counters['sqlStatements'],2)
        self.assertEqual(metrics.peak['databaseConnections'],0)
        self.assertEqual(metrics.phase_sql_operation_seconds['burst']['scope_lock_batch']['count'],2)
        payload['timings']['private tenant secret']=[1.]
        with self.assertRaises(Incomplete):absorb_worker_metrics(metrics,payload,'burst')
        self.assertEqual(metrics.counters['sqlStatements'],2)

    def test_child_fence_missing_evidence_cannot_pass(self):
        summary={'pid':123,'worker':'p8-burst-0','status':'PASS','cpuSeconds':1.,'counters':{},
            'poolStats':{'closed':True,'maxConnections':2},
            'transportFence':{'unexpectedAttempts':0,'expectedSelfCheckDenials':4},
            'metrics':{},'error':None,'perProcessPeakConcurrency':{}}
        validate_worker_summary(summary,123)
        for mutate in (lambda s:s['transportFence'].update(unexpectedAttempts=1),
                       lambda s:s['poolStats'].update(closed=False),lambda s:s.pop('transportFence')):
            invalid=copy.deepcopy(summary);mutate(invalid)
            with self.assertRaises(Incomplete):validate_worker_summary(invalid,123)
        runtime=SimpleNamespace(p=profile('a'),child_fences=[],worker_summaries=[])
        parent=SimpleNamespace(_unexpected=0,_expected=4)
        self.assertIsNone(combined_transport_fence(runtime,parent)['unexpectedAttempts'])
        next_pid=123
        for phase,replicas in planned_worker_groups(runtime.p):
            workers=[{'pid':pid} for pid in range(next_pid,next_pid+replicas)]
            runtime.worker_summaries.append({'phase':phase,'replicas':replicas,'workers':workers,
                'status':'PASS','parentConnectionCap':4,'aggregateConnectionCap':20,'perReplicaConnectionCap':2})
            runtime.child_fences.extend({'phase':phase,'pid':worker['pid'],**summary['transportFence']} for worker in workers)
            next_pid+=replicas
        result=combined_transport_fence(runtime,parent)
        self.assertEqual((result['unexpectedAttempts'],result['observedReplicaProofs']),(0,21))
        # Deriving the expected count from only the surviving groups would
        # wrongly accept these complete-looking but truncated reports.
        runtime.worker_summaries.pop();runtime.child_fences=runtime.child_fences[:-8]
        self.assertIsNone(combined_transport_fence(runtime,parent)['unexpectedAttempts'])

    def test_capacity_progress_emits_only_allowlisted_aggregates(self):
        runtime=Runtime.__new__(Runtime)
        runtime.started=time.monotonic()-1
        runtime.progress_phase='private-token-or-tenant'
        runtime.fixtures=['private-user-one','private-user-two']
        runtime.m=SimpleNamespace(lock=threading.RLock(),records={'private-job':{'content':'private-body'}},
            counters=Counter({'mockHttpAttempts':17,'private-secret':99}))
        output=io.StringIO()
        with redirect_stdout(output):runtime.emit_progress({'pipelineQueueDepth':3,'unsentEligibleQueueDepth':2,
            'oldestFrozenDueLagSeconds':1.25,'private-token':'never-log'})
        line=output.getvalue()
        self.assertNotIn('private',line)
        value=json.loads(line.removeprefix('RAFII_DISCORD_CAPACITY_PROGRESS '))
        self.assertEqual(set(value),{'phase','elapsedSeconds','fixturesCompleted','jobRequests','mockHttpAttempts',
            'pipelineQueueDepth','unsentEligibleQueueDepth','oldestFrozenDueLagSeconds'})
        self.assertEqual((value['phase'],value['fixturesCompleted'],value['jobRequests'],value['mockHttpAttempts']),('unknown',2,1,17))
        self.assertEqual((value['pipelineQueueDepth'],value['unsentEligibleQueueDepth'],value['oldestFrozenDueLagSeconds']),(3,2,1.25))

    def test_owned_runner_streams_only_exact_fenced_capacity_script(self):
        source=Path(__file__).resolve().parents[1]/'scripts/postriff_disposable_postgres.py'
        function=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='run_script')
        calls=[];pipe=object()
        scope={'subprocess':SimpleNamespace(PIPE=pipe,run=lambda *args,**kwargs:calls.append((args,kwargs))),
            'sys':SimpleNamespace(executable='synthetic-python'),'ROOT':Path('/synthetic-root')}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'actual-runner-output-policy','exec'),scope)
        for script in ('tests/phase2/postgres_discord_capacity.py','tests/phase2/postgres_discord_rate_limits.py',
                       'tests/phase2/./postgres_discord_capacity.py'):
            scope['run_script'](script,{'CI':'true'})
        self.assertEqual([kw['stdout'] for _,kw in calls],[None,pipe,pipe])
        self.assertTrue(all(kw['stderr'] is pipe and kw['text'] is True and kw['env']=={'CI':'true'} for _,kw in calls))

    def test_actual_learning_formula_preserves_quota_and_conservative_pending_debits(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'src/postriff_phase2/discord/rate_limits.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observation_remaining')
        scope={'RateCoordinatorUnavailable':Incomplete}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'actual-quota-learning','exec'),scope)
        calc=scope['observation_remaining']
        self.assertEqual(calc(0,249,first=True,pending=0),249)
        self.assertEqual(calc(0,249,first=True,pending=4),245)
        self.assertEqual(calc(200,249,first=False,pending=5,newly_mapped=2,current_unmapped=1),197)
        self.assertEqual(calc(200,249,first=False,pending=5,newly_mapped=0,current_unmapped=0),200)
        self.assertEqual(calc(0,249,first=False,pending=0),0)
        for change in ({'pending':True},{'newly_mapped':1},{'current_unmapped':2},{'first':1}):
            with self.assertRaises(Incomplete):calc(0,249,**({'first':True,'pending':0}|change))


    def test_new_denial_scope_metadata_is_allowlisted(self):
        for name in ('application','discovery','learned_route','unknown_route','embargo','permit','unknown'):
            result=rate_metadata(SimpleNamespace(rate_cause='rate_budget',rate_scope_kind=name,retry_after_seconds=.1))
            self.assertEqual(result['scope'],name)
        result=rate_metadata(SimpleNamespace(rate_cause='rate_budget',rate_scope_kind='private tenant/channel/token'))
        self.assertEqual(result,{'cause':'rate_budget','scope':'unknown'})

    def test_atomic_admission_statement_diagnostic_keeps_only_safe_category(self):
        observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private SQL/parameter values')
        raw=SimpleNamespace(execute=fail)
        metrics=SimpleNamespace(count=lambda *a:None,timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(raw,metrics)
        with self.assertRaises(RuntimeError):
            cursor.execute('WITH reservation_clock AS MATERIALIZED (SELECT clock_timestamp() AS at) '
                'INSERT INTO public.pr_discord_request_admissions SELECT private_parameter',('private-token',42.0))
        self.assertEqual(observed,[('admission_insert',42.0)])

    def test_pending_lock_statement_categories_never_emit_query_or_parameters(self):
        observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private admission/SQL/parameter')
        metrics=SimpleNamespace(count=lambda *a:None,timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        for name in ('locked_alias','locked_pending'):
            with self.assertRaises(RuntimeError):
                cursor.execute('WITH '+name+' AS MATERIALIZED (SELECT private_admission FOR UPDATE)',('private-token',))
        self.assertEqual(observed,[('alias_pending_lock',None),('pending_lock',None)])

    def test_successful_scope_batch_counts_are_allowlisted_without_values(self):
        counts=Counter()
        metrics=SimpleNamespace(count=lambda key:counts.update([key]),timing=lambda *a:None)
        cursor=TimedCursor(SimpleNamespace(execute=lambda *a,**kw:None),metrics)
        for name in ('seed','lock','store'):
            cursor.execute('WITH scope_'+name+' AS MATERIALIZED (SELECT private_value)',('private-token',))
        cursor.execute('WITH scope_customer_secret AS MATERIALIZED (SELECT private_value)',('private-token',))
        self.assertEqual(counts,Counter({'sqlStatements':4,'sqlOperation.scope_seed_batch':1,
            'sqlOperation.scope_lock_batch':1,'sqlOperation.scope_store_batch':1,'sqlOperation.other':1}))

    def test_failed_scope_batch_counts_keep_category_and_omit_sql_and_values(self):
        counts=Counter();observed=[]
        def fail(*args,**kwargs):raise RuntimeError('private SQL/parameter')
        metrics=SimpleNamespace(count=lambda key:counts.update([key]),timing=lambda *a:None,
            sql_failure=lambda error,operation,start,expiry:observed.append((operation,expiry)))
        cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        for name in ('seed','lock','store'):
            with self.assertRaises(RuntimeError):
                cursor.execute('WITH scope_'+name+' AS MATERIALIZED (SELECT private_value)',('private-token',))
        self.assertEqual(observed,[(name,None) for name in ('scope_seed_batch','scope_lock_batch','scope_store_batch')])
        self.assertEqual(counts['sqlStatements'],3)
        self.assertEqual(sum(v for k,v in counts.items() if k.startswith('sqlOperation.')),3)
        self.assertNotIn('private',str(counts)+str(observed))

    def test_sql_metadata_is_catalog_symbols_only(self):
        error = RuntimeError('private credential and SQL must never appear')
        error.sqlstate = '23514'
        error.diag = SimpleNamespace(constraint_name='pr_discord_request_admissions_check',
            message_detail='private failing row', statement='private SQL')
        self.assertEqual(sql_metadata(error), {'sqlstate': '23514', 'constraint': 'pr_discord_request_admissions_check'})
        error.diag.constraint_name = 'customer_private_value'
        error.sqlstate = 'private'
        self.assertEqual(sql_metadata(error), {})
        error.diag.constraint_name = 'pr_discord_rate_state_window_seconds_check'
        self.assertEqual(sql_metadata(error), {'constraint': error.diag.constraint_name})

    def test_rate_metadata_rejects_untrusted_cause_and_invalid_wait(self):
        error = SimpleNamespace(rate_cause='permit_expired', retry_after_seconds=.05)
        self.assertEqual(rate_metadata(error), {'cause': 'permit_expired', 'waitSeconds': .05})
        for wait in (float('nan'), float('inf'), -1, True, 'private'):
            error.rate_cause, error.retry_after_seconds = 'private-secret', wait
            self.assertEqual(rate_metadata(error), {'cause': 'unknown'})

    def test_fixture_failure_and_cancellation_keep_every_planned_actor(self):
        ledger = FixtureLedger(4)
        ledger.begin(0); ledger.finish(0, 'completed')
        ledger.begin(1); ledger.finish(1, 'failed', Incomplete('private-text'))
        ledger.begin(2); ledger.finish(2, 'cancelled')
        ledger.cancel_queued()
        result = ledger.summary()
        self.assertEqual({k: result[k] for k in ('planned','attempted','completed','failed','cancelled')},
                         {'planned': 4, 'attempted': 3, 'completed': 1, 'failed': 1, 'cancelled': 2})
        self.assertEqual((result['cancelledBeforeStart'], result['cancelledAfterStart'], result['unaccounted']), (1,1,0))
        self.assertFalse(result['complete'])
        self.assertNotIn('private-text', str(result))
        with self.assertRaises(Incomplete): ledger.begin(3)
        with self.assertRaises(Incomplete): ledger.finish(0, 'completed')

    def test_fatal_fixture_stops_queued_and_active_control_actors(self):
        ledger, abort = FixtureLedger(8), threading.Event()
        def build(index):
            if index == 0: raise Incomplete('synthetic fatal control')
            if abort.wait(.2): raise FixtureCancelled('control stopped')
            raise Incomplete('cooperative stop did not arrive')
        runtime = SimpleNamespace(p={'producerConcurrency': 1}, fixture_ledger=ledger,
            fixture_abort=abort, build_fixture=build, fixtures=[])
        with self.assertRaises(Incomplete): collect_fixture_cohort(runtime, range(8))
        result = ledger.summary()
        self.assertTrue(abort.is_set())
        self.assertEqual((result['failed'], result['completed'], result['queued'], result['running']), (1,0,0,0))
        self.assertEqual(result['cancelled'], 7)
        self.assertFalse(result['complete'])

    def test_connection_diagnostic_preserves_full_profiles_and_blocks_publish(self):
        hashes = {'a': 'fe939c0d1a8b55b2f68ad48f25b7f9caad7e63259ca954d97f5fd9cafe513836',
                  'b': '1c76fcd6054dd4d5fb473bcd416c0bde8d6d65961556deb50a41c62d345f7e31'}
        p = connection_diagnostic_profile()
        self.assertEqual((p['users'], p['serialUsers'], p['parallelUsers'], p['producerConcurrency']), (32,16,16,16))
        self.assertEqual(p['totalHarnessDeadlineSeconds'], 480)
        self.assertFalse(p['publishingAllowed'])
        self.assertEqual(p['mock'], profile('a')['mock'])
        counted = []
        metrics = SimpleNamespace(count=lambda key: counted.append(key))
        runtime = SimpleNamespace(p=p, m=metrics, create_oracle=lambda *a: self.fail('Publish oracle entered'))
        wire = MockDiscord(runtime)
        with self.assertRaises(Incomplete):
            wire('POST', 'https://discord.com/api/v10/channels/123456789/messages', body={})
        self.assertEqual(counted, ['diagnosticPublishDenied'])
        self.assertFalse(wire.attempts or wire.creates)
        self.assertEqual({s: fingerprint(profile(s)) for s in ('a','b')}, hashes)

    def test_main_deadline_outside_future_cancels_before_waiting_for_shutdown(self):
        for stop_on_failure in (True, False):
            ledger, abort = FixtureLedger(4), threading.Event()
            def build(index):
                if abort.wait(.2): raise FixtureCancelled('control stopped')
                raise Incomplete('cooperative cancellation missing')
            runtime = SimpleNamespace(p={'producerConcurrency': 1}, fixture_ledger=ledger,
                fixture_abort=abort, build_fixture=build, fixtures=[])
            with patch('phase2.postgres_discord_capacity.as_completed', side_effect=Incomplete('control deadline')):
                with self.assertRaises(Incomplete):
                    collect_fixture_cohort(runtime, range(4), stop_on_failure=stop_on_failure)
            result = ledger.summary()
            self.assertTrue(abort.is_set())
            self.assertEqual((result['cancelled'], result['running'], result['queued']), (4,0,0))
            self.assertFalse(result['complete'])

    def test_runtime_guard_stops_before_new_io_after_fatal_fixture(self):
        runtime = Runtime.__new__(Runtime)
        runtime.fixture_abort = threading.Event()
        runtime.fixture_abort.set()
        with self.assertRaises(FixtureCancelled): runtime.guard()

    def test_serial_main_interrupt_is_not_swallowed_as_actor_failure(self):
        ledger = FixtureLedger(2)
        def build(index): raise HarnessInterrupted('control main deadline')
        metrics = SimpleNamespace(lock=threading.RLock(), counters=Counter(), timings={}, peak=Counter(),
                                  event=lambda *args, **kwargs: None)
        runtime = SimpleNamespace(p={'producerConcurrency': 1}, m=metrics, fixture_ledger=ledger,
            fixture_abort=threading.Event(), build_fixture=build, fixtures=[], setup_deadline=time.monotonic()+5)
        with self.assertRaises(HarnessInterrupted): diagnostic_phase(runtime, 'serial', range(2), parallel=False)
        result = ledger.summary()
        self.assertEqual((result['attempted'], result['failed'], result['cancelled'], result['queued']), (1,0,1,1))
        self.assertFalse(result['complete'])

    def test_mock_bucket_headers_pass_the_actual_coordinator_parser(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'src/postriff_phase2/discord/rate_limits.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SharedPostgresBudget')
        observe = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'observe')
        parse = next(n for n in observe.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'new_bucket' for t in n.targets))
        observe_once = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_observe_once')
        hold = next(n for n in ast.walk(observe_once) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == 'raw_bucket is not None and new_bucket is None')
        code = compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(parse), copy.deepcopy(hold)],
                           type_ignores=[])), 'actual-rate-bucket-parser', 'exec')
        def held(bucket):
            scope = {'raw_bucket': bucket, 'row': {'hold': False}, 're': re,
                     '_digest': lambda value: hashlib.sha256(value.encode()).hexdigest()}
            exec(code, scope)
            return scope['row']['hold']
        self.assertTrue(held('fixture-/oauth2/@me'))  # Original mock caused a durable hold.
        p = profile('a')
        p['mock'].update(latencyBaseSeconds=0, latencyJitterSeconds=0)
        metrics = SimpleNamespace(count=lambda *args: None, timing=lambda *args: None,
                                  running=lambda *args: nullcontext())
        wire = MockDiscord(SimpleNamespace(p=p, m=metrics))
        wire.route = lambda *args: {}  # Inert responses; no SQL, tokens or real transport.
        paths = ['/oauth2/@me', '/users/@me', '/oauth2/token', '/guilds/123456789/channels',
                 '/channels/123456789', '/channels/987654321']
        buckets = {path: wire('POST' if path == '/oauth2/token' else 'GET',
                              'https://discord.com/api/v10' + path)['headers']['X-RateLimit-Bucket']
                   for path in paths}
        for bucket in buckets.values():
            self.assertFalse(held(bucket))
        self.assertEqual(buckets['/channels/123456789'], buckets['/channels/987654321'])
        self.assertNotEqual(buckets['/oauth2/@me'], buckets['/users/@me'])
        again = wire('GET', 'https://discord.com/api/v10/oauth2/@me')['headers']['X-RateLimit-Bucket']
        self.assertEqual(buckets['/oauth2/@me'], again)

    def test_real_oauth_mount_keeps_the_policy_instead_of_an_inert_coordinator(self):
        # Execute the ACTUAL constructor's rate block with inert dependencies.
        # No application-module imports, SQL, provider calls or data cohorts.
        # This fails with the old helper, which supplied only rate_limiter.
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'src/postriff_phase2/oauth.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OAuthService')
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        rate = next(n for n in init.body if isinstance(n, ast.If) and 'rate_v1_enabled' in ast.unparse(n.test))
        rate = copy.deepcopy(rate)
        rate.body = [n for n in rate.body if not isinstance(n, ast.ImportFrom)]
        module = ast.fix_missing_locations(ast.Module(body=[rate], type_ignores=[]))
        class Budget:
            def __init__(self, factory, application, *, policy):
                self.policy = policy
        raw = {'version': 1, 'revision': 'synthetic-regression', 'app_capacity': 1000}
        adapter = SimpleNamespace(client_id='718000000000000001', rate_policy_raw=None, rate_limiter=object())
        adapter.rate_v1_enabled = True
        scope = {'discord': adapter, 'repository': SimpleNamespace(connection_factory=lambda: None),
                 'SharedPostgresBudget': Budget, 'RateCoordinatorUnavailable': Incomplete}
        exec(compile(module, 'actual-oauth-rate-mount', 'exec'), scope)
        self.assertIsNone(adapter.rate_limiter.policy)  # Reproduce the broken mounting contract.
        configure_candidate_provider(adapter, raw)
        exec(compile(module, 'actual-oauth-rate-mount', 'exec'), scope)
        self.assertEqual(adapter.rate_limiter.policy, raw)
        self.assertIsNotNone(adapter.rate_limiter.policy)
        self.assertFalse(adapter.rate_coordinator_degraded)
        raw['app_capacity'] = 1
        self.assertEqual(adapter.rate_limiter.policy['app_capacity'], 1000)

    def test_failure_diagnostics_never_emit_secret_message_or_sql(self):
        error = RuntimeError('fixture-secret must not appear')
        error.code = 'discord_rate_coordinator_unavailable'
        error.status = 503
        error.sqlstate = '42601'
        data = diagnostic(error)
        self.assertEqual(data['code'], error.code)
        self.assertEqual(data['status'], 503)
        self.assertEqual(data['sqlstate'], '42601')
        self.assertNotIn('fixture-secret', str(data))
        error.code = 'unsafe credential value /'
        self.assertNotIn('code', diagnostic(error))

    def test_missing_latencies_are_undefined_in_full_denominator(self):
        data = distribution([.1, None, .3], requested=5)
        self.assertEqual((data['requested'], data['observed'], data['undefined']), (5, 2, 3))
        self.assertEqual((data['p95'], data['p99']), (.3, .3))
        self.assertIsNone(distribution([None])['p95'])

    def test_tail_latency_and_invalid_numbers_cannot_be_hidden(self):
        self.assertEqual(distribution([0] * 98 + [2, 10])['p99'], 2)
        for data in ([-1], [True], [float('nan')], [float('inf')]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                distribution(data)
        with self.assertRaises(ValueError):
            distribution([1, 2], requested=1)

    def test_partial_or_nonterminal_work_is_not_complete(self):
        self.assertTrue(accounting(3, 3, ['verified', 'held', 'uncertain'])['complete'])
        for requested, admitted, states in ((3, 2, ['verified'] * 2), (3, 3, ['verified']),
                (1, 2, ['verified'] * 2), (1, 1, ['provider_accepted']), (1, 1, ['scheduled'])):
            with self.subTest(states=states):
                self.assertFalse(accounting(requested, admitted, states)['complete'])

    def test_distinct_user_and_destination_counts_required(self):
        p = profile('a')
        good = {'users': 1000, 'profiles': 1000, 'memberships': 1000, 'workspaces': 1000,
                'distinctPrincipals': 1000, 'identities': 1000, 'connections': 2000,
                'grants': 3000, 'destinations': 6000, 'distinctDestinationIds': 6000}
        self.assertEqual(require_fixture(p, good)['grants'], 3000)
        for key in good:
            with self.subTest(key=key), self.assertRaises(Incomplete):
                require_fixture(p, {**good, key: good[key] - 1})
        with self.assertRaises(Incomplete):
            require_fixture(p, {**good, 'distinctPrincipals': 1})

    def test_stage_profile_preserves_scale_seed_time_and_no_nonce_cache(self):
        for stage, users, steady in (('a', 1000, 900), ('b', 10000, 1800)):
            p = profile(stage)
            self.assertEqual(p['users'], users)
            self.assertEqual(p['guildsPerUser'] * p['destinationsPerGuild'], 6)
            self.assertEqual((p['rampSeconds'], p['steadySeconds']), (300, steady))
            self.assertEqual(p['comparisonReplicas'] + [p['referenceReplicas']], [1, 4, 8])
            self.assertEqual(p['mock']['nonceDedupWindowSeconds'], 0)
            self.assertEqual(len(fingerprint(p)), 64)
        with self.assertRaises(ValueError):
            profile('')
        self.assertNotEqual(fingerprint(profile('a')), fingerprint(profile('b')))

    def test_steady_arrivals_cover_whole_interval_not_shortened_sample(self):
        p = profile('a')
        values = arrivals(p)
        self.assertEqual(len(values), 2130)
        self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
        self.assertEqual(sum(v >= 300 for v in values), 1800)
        self.assertGreater(values[-1], 1199)
        self.assertEqual(len(arrivals(profile('b'))), 9825)

    def test_infeasible_profile_is_blocked_without_shortening_it(self):
        a, b = profile('a'), profile('b')
        self.assertEqual(budget_lower_bound(a)['status'], 'PASS')
        self.assertEqual(budget_lower_bound(b)['status'], 'BLOCKED')
        self.assertGreater(budget_lower_bound(b)['minimumSeconds'], b['totalHarnessDeadlineSeconds'])
        self.assertEqual(b['steadySeconds'], 1800)

    def test_mac_missing_ci_and_foreign_dsn_are_refused(self):
        env = {'CI': 'true', 'RAFII_DISCORD_SYNTHETIC_FENCE': '1', 'POSTRIFF_TEST_DSN': DSN}
        validate_fence('linux', env)
        for platform, changed in (('darwin', env), ('linux', {**env, 'CI': 'false'}),
                ('linux', {**env, 'RAFII_DISCORD_SYNTHETIC_FENCE': '0'}),
                ('linux', {**env, 'POSTRIFF_TEST_DSN': 'host=buoyhkbodnhzngaotoel.supabase.co'}),
                ('linux', {**env, 'POSTRIFF_TEST_DSN': 'host=staging.example'})):
            with self.subTest(platform=platform), self.assertRaises(Incomplete):
                validate_fence(platform, changed)

    def test_owned_cluster_schema_and_transport_proof_cannot_be_skipped(self):
        env = {'CI': 'true', 'RAFII_DISCORD_SYNTHETIC_FENCE': '1', 'POSTRIFF_TEST_DSN': DSN}
        database = {'host': '127.0.0.1', 'port': 55438, 'name': 'postgres', 'user': 'postriff_test',
                    'directory': '/tmp/postriff-cw-pg-synthetic/data', 'majorVersion': 17, 'authColumns': ['id']}
        validate_fence('linux', env, database)
        for key, value in (('host', 'remote.example'), ('port', 5432), ('user', 'postgres'),
                ('directory', '/tmp/foreign/data'), ('directory', 'postriff-cw-pg-synthetic/data'),
                ('majorVersion', 16), ('authColumns', ['id', 'email'])):
            with self.subTest(key=key), self.assertRaises(Incomplete):
                validate_fence('linux', env, {**database, key: value})
        class UnknownTransport:
            synthetic_only = True
        with self.assertRaises(Incomplete):
            validate_fence('linux', env, database, UnknownTransport())


class ReorderedHeaderHarnessControls(unittest.TestCase):
    def test_mapping_query_uses_durable_route_hash_after_real_response_reordering(self):
        from phase2.postgres_discord_capacity import Runtime
        from postriff_phase2.discord.rate_limits import route_identity
        r=Runtime.__new__(Runtime);entered=threading.Event();lock=threading.Lock();calls=[]
        path='/guilds/123456789012345678';route,major=route_identity('GET',path)
        expected_route=hashlib.sha256(route.encode()).hexdigest()
        expected_bucket=hashlib.sha256(('fixture-'+hashlib.sha256(path.encode()).hexdigest()).encode()).hexdigest()
        wire=SimpleNamespace(reordered_entered=entered,reordered_finishes=[],set_fault=lambda *args:None)
        def request(method,url):
            with lock:index=len(calls);calls.append(url)
            if index==0:entered.set();time.sleep(.02)
            wire.reordered_finishes.append({'path':url,'old':index==0})
            return {'status':200}
        def execute(query,params):
            self.assertEqual(params,('synthetic-auth-hash',expected_route,major))
            return SimpleNamespace(fetchone=lambda:(expected_bucket,2) if query.startswith('SELECT bucket_key') else (2,))
        r.wire=wire;r.connection=lambda:nullcontext(SimpleNamespace(execute=execute))
        provider=SimpleNamespace(_bot=request,_rate_identity=lambda kind:SimpleNamespace(auth_key='synthetic-auth-hash'))
        result=r.rate_reordering({'provider':provider,'guilds':['123456789012345678'],'destinations':[('connection','guild','channel')]})
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(len(calls),2)


class SqlAuthorizationProbeControls(unittest.TestCase):
    def test_expected_denial_is_thread_scoped_and_never_hides_other_errors(self):
        from phase2.postgres_discord_capacity import Telemetry
        counters=Counter();failures=[]
        metrics=SimpleNamespace(_expected_sql=threading.local(),count=lambda key:counters.update([key]),
            sql_failure=lambda *args:failures.append(type(args[0]).__name__),timing=lambda *args:None)
        class SqlFailure(Exception):pass
        def fail(*args):
            error=SqlFailure('synthetic');error.sqlstate=state[0];raise error
        state=['42501'];cursor=TimedCursor(SimpleNamespace(execute=fail),metrics)
        with Telemetry.expected_sqlstate(metrics,'42501'):
            with self.assertRaises(SqlFailure):cursor.execute('SELECT synthetic')
            state[0]='23514'
            with self.assertRaises(SqlFailure):cursor.execute('SELECT synthetic')
        state[0]='42501'
        with self.assertRaises(SqlFailure):cursor.execute('SELECT synthetic')
        self.assertEqual(counters['expectedSqlAuthorizationDenials'],1)
        self.assertEqual(counters['sqlErrors.SqlFailure'],2)
        self.assertEqual(len(failures),2)


class ExtendedResourcePlanTests(unittest.TestCase):
    def test_parent16_plan_preserves_all_workload_and_strict_process_evidence(self):
        changed={'version','resourcePlan','parentPoolSize','aggregateConnectionCap','resourceChange'}
        for stage in ('a','pipeline-qualification','b'):
            base='b-extended-workers16-v3' if stage=='b' else 'workers16-v3'
            name='b-extended-workers16-parent16-v4' if stage=='b' else 'workers16-parent16-v4'
            old=selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':base})
            plan=selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':name})
            self.assertEqual(set(old),set(plan))
            for key,value in old.items():
                if key not in changed:self.assertEqual(plan[key],value,(stage,key))
            self.assertEqual(arrivals(old),arrivals(plan))
            self.assertEqual(validate_worker_budget(plan),1)
            self.assertEqual((plan['parentPoolSize'],plan['aggregateConnectionCap']),(16,32))
            for key,value in [('referenceReplicas',8),('workerPoolSize',2),('parentPoolSize',4),
                              ('parentPoolSize',True),('aggregateConnectionCap',33),('version',3),
                              ('resourcePlan','unrecognized')]:
                invalid=copy.deepcopy(plan);invalid[key]=value
                with self.assertRaises(Incomplete):validate_worker_budget(invalid)
            runtime=SimpleNamespace(p=plan,child_fences=[],worker_summaries=[])
            next_pid=123
            for phase,replicas in planned_worker_groups(plan):
                workers=[{'pid':pid} for pid in range(next_pid,next_pid+replicas)]
                runtime.worker_summaries.append({'phase':phase,'replicas':replicas,'workers':workers,
                    'status':'PASS','parentConnectionCap':16,'aggregateConnectionCap':32,'perReplicaConnectionCap':1})
                runtime.child_fences.extend({'phase':phase,'pid':worker['pid'],'unexpectedAttempts':0,
                    'expectedSelfCheckDenials':4} for worker in workers)
                next_pid+=replicas
            parent=SimpleNamespace(_unexpected=0,_expected=4)
            self.assertEqual(combined_transport_fence(runtime,parent)['unexpectedAttempts'],0)
            for key,value in [('parentConnectionCap',4),('aggregateConnectionCap',20),('perReplicaConnectionCap',2)]:
                invalid=copy.deepcopy(runtime);invalid.worker_summaries[0][key]=value
                self.assertIsNone(combined_transport_fence(invalid,parent)['unexpectedAttempts'])

    def test_workers16_plan_preserves_workload_targets_and_binds_all_37_proofs(self):
        env={'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'workers16-v3'}
        plan=selected_profile('a',env)
        changed={'version','referenceReplicas'}
        for stage in ('a','pipeline-qualification','burst-diagnostic'):
            old=selected_profile(stage,{})
            new=selected_profile(stage,env)
            for key,value in old.items():
                if key not in changed:self.assertEqual(new[key],value,(stage,key))
            self.assertEqual(validate_worker_budget(new),1)
            self.assertEqual(planned_worker_groups(new),[('comparison-1',1),('comparison-4',4),('burst',16),('sustained',16)])
        old_b=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-v2'})
        new_b=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-workers16-v3'})
        for key,value in old_b.items():
            if key not in changed|{'resourcePlan'}:self.assertEqual(new_b[key],value,key)
        self.assertEqual(arrivals(old_b),arrivals(new_b))
        self.assertEqual(budget_lower_bound(new_b)['status'],'PASS')
        for key,value in [('referenceReplicas',True),('referenceReplicas',17),('workerPoolSize',True),
                          ('workerPoolSize',2),('parentPoolSize',True),('aggregateConnectionCap',21)]:
            invalid=copy.deepcopy(plan);invalid[key]=value
            with self.assertRaises(Incomplete):validate_worker_budget(invalid)
        for replicas in (True,0,17):
            with self.assertRaises(Incomplete):validate_worker_budget(plan,replicas)
        runtime=SimpleNamespace(p=plan,child_fences=[],worker_summaries=[])
        next_pid=123
        for phase,replicas in planned_worker_groups(plan):
            workers=[{'pid':pid} for pid in range(next_pid,next_pid+replicas)]
            runtime.worker_summaries.append({'phase':phase,'replicas':replicas,'workers':workers,
                'status':'PASS','parentConnectionCap':4,'aggregateConnectionCap':20,'perReplicaConnectionCap':1})
            runtime.child_fences.extend({'phase':phase,'pid':worker['pid'],'unexpectedAttempts':0,'expectedSelfCheckDenials':4} for worker in workers)
            next_pid+=replicas
        parent=SimpleNamespace(_unexpected=0,_expected=4)
        proof=combined_transport_fence(runtime,parent)
        self.assertEqual((proof['unexpectedAttempts'],proof['expectedReplicaProcesses'],proof['observedReplicaProofs']),(0,37,37))
        reused=copy.deepcopy(runtime)
        for group in reused.worker_summaries:
            for index,worker in enumerate(group['workers']):worker['pid']=123+index
        reused.child_fences=[{'phase':group['phase'],'pid':worker['pid'],
            'unexpectedAttempts':0,'expectedSelfCheckDenials':4}
            for group in reused.worker_summaries for worker in group['workers']]
        self.assertEqual(combined_transport_fence(reused,parent)['unexpectedAttempts'],0)
        for mutate in (lambda r:r.child_fences.pop(),lambda r:r.worker_summaries.pop(),
                       lambda r:r.worker_summaries.reverse(),lambda r:r.worker_summaries[0].update(replicas=True),
                       lambda r:r.worker_summaries[0].update(perReplicaConnectionCap=2),
                       lambda r:r.child_fences[-1].update(phase=r.child_fences[0]['phase'],pid=r.child_fences[0]['pid'])):
            invalid=copy.deepcopy(runtime);mutate(invalid)
            self.assertIsNone(combined_transport_fence(invalid,parent)['unexpectedAttempts'])
        summary={'pid':123,'worker':'p8-burst-0','status':'PASS','cpuSeconds':1.,'counters':{},
            'poolStats':{'closed':True,'maxConnections':1},
            'transportFence':{'unexpectedAttempts':0,'expectedSelfCheckDenials':4},
            'metrics':{},'error':None,'perProcessPeakConcurrency':{}}
        validate_worker_summary(summary,123,1)
        for value in (True,2):
            invalid=copy.deepcopy(summary);invalid['poolStats']['maxConnections']=value
            with self.assertRaises(Incomplete):validate_worker_summary(invalid,123,1)

    def test_original_profiles_and_all_workloads_targets_are_preserved(self):
        from phase2.postgres_discord_capacity import selected_profile
        a,b=profile('a'),profile('b')
        self.assertEqual(fingerprint(a),'fe939c0d1a8b55b2f68ad48f25b7f9caad7e63259ca954d97f5fd9cafe513836')
        self.assertEqual(fingerprint(b),'1c76fcd6054dd4d5fb473bcd416c0bde8d6d65961556deb50a41c62d345f7e31')
        extended=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-v2'})
        for key,value in b.items():
            if key not in ('version','setupDeadlineSeconds','totalHarnessDeadlineSeconds'):
                self.assertEqual(extended[key],value,key)
        self.assertEqual(arrivals(extended),arrivals(b))
        self.assertEqual(budget_lower_bound(b)['status'],'BLOCKED')
        self.assertEqual(budget_lower_bound(extended)['status'],'PASS')
    def test_extended_resources_are_explicit_bounded_and_reject_unknown_plans(self):
        from phase2.postgres_discord_capacity import selected_profile
        e=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-v2'})
        self.assertEqual((e['cpu'],e['memoryGiB'],e['jobTimeoutMinutes']),(32,128,225))
        self.assertLess(e['setupDeadlineSeconds']+e['rampSeconds']+e['steadySeconds'],e['totalHarnessDeadlineSeconds'])
        self.assertLess(e['totalHarnessDeadlineSeconds'],e['policyLifetimeSeconds'])
        self.assertLess(e['policyLifetimeSeconds'],31*86400)
        for stage,name in [('a','b-extended-v2'),('b','unknown')]:
            with self.assertRaises(Incomplete):selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':name})


if __name__ == '__main__':
    unittest.main()
