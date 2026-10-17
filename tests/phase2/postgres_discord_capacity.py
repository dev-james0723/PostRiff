"""Prepared P8 cloud harness: actual Rafii SQL/commands/worker, synthetic REST.

Importing this module is inert and supports a tiny pure control test on the Mac.
run() requires the separately approved, runner-owned Linux PostgreSQL cluster.
No scheduler, production feature, permanent mock deduplication or live HTTP.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import multiprocessing
import os
import random
import re
import runpy
import signal
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres user=postriff_test'
APP, BOT = '718000000000000001', '718000000000000002'
SHARED_GUILD = '718000000000000003'
DRAFT_SHA = '91bc2b004468d4f265ea1f4532d2f90c485ff8e8ce2c24d994015f1c6ea12e61'
RESULT = ROOT / '.depot/discord-capacity-results.json'
EVENTS = ROOT / '.depot/discord-capacity-events.jsonl'
TERMINAL = frozenset(('verified', 'held', 'failed', 'canceled', 'uncertain'))
WORKER_PIPE_BYTES = 32 * 1024 * 1024
WORKER_SIGNALS = frozenset((signal.SIGINT, signal.SIGTERM, signal.SIGALRM))


def start_owned_worker(process, child_channel, owned_processes, registry, lock, reported_pids):
    # Deliver cancellation only after a launched child is in BOTH registries.
    # The child restores these signals at its own entry point after spawn.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, WORKER_SIGNALS)
    try:
        owned_processes.append(process)
        try:
            process.start()
        finally:
            if process.pid is not None:
                with lock:
                    registry[process.pid] = process
                    reported_pids.discard(process.pid)
            child_channel.close()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def send_worker_message(channel, kind, value):
    raw = json.dumps([kind, value], separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > WORKER_PIPE_BYTES:
        raise Incomplete('Owned worker message exceeded its fixed bound')
    channel.send_bytes(raw)


def receive_worker_message(channel):
    value = json.loads(channel.recv_bytes(WORKER_PIPE_BYTES))
    if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str):
        raise Incomplete('Malformed owned worker message')
    return value


def reap_owned_workers(processes, brokers):
    """Only supplied owned handles; fixed group deadlines, never N timeouts."""
    errors = []
    def join_group(handles, seconds):
        deadline = time.monotonic() + seconds
        for handle in handles:
            try:handle.join(timeout=max(0., deadline-time.monotonic()))
            except Exception as error:errors.append(type(error).__name__)
    processes = [process for process in processes if process.pid is not None]
    join_group(processes, 12)
    forced = [process for process in processes if process.is_alive()]
    for process in forced:
        try:process.terminate()
        except Exception as error:errors.append(type(error).__name__)
    join_group(forced, 2)
    surviving = [process for process in forced if process.is_alive()]
    for process in surviving:
        try:process.kill()
        except Exception as error:errors.append(type(error).__name__)
    join_group(surviving, 2)
    join_group(brokers, 2)
    remaining = [process.pid for process in processes if process.is_alive() or process.exitcode is None]
    return {'forcedCount': len(forced), 'killCount': len(surviving), 'survivingPids': remaining,
            'unfinishedBrokers': sum(thread.is_alive() for thread in brokers), 'errors': errors}


class Incomplete(RuntimeError):
    """A missing phase/fixture/observation must never become a passing zero."""


class FixtureCancelled(Incomplete):
    """Cooperative stop before another fixture operation; no forced SQL kill."""


class HarnessInterrupted(BaseException):
    """Main-thread deadline/cancellation is never an ordinary actor failure."""


def sql_metadata(error):
    """Only catalog symbols from the candidate rate schema, never PG detail."""
    result = {}
    state = getattr(error, 'sqlstate', None)
    if isinstance(state, str) and re.fullmatch(r'[A-Z0-9]{5}', state):
        result['sqlstate'] = state
    constraint = getattr(getattr(error, 'diag', None), 'constraint_name', None)
    allowed = set()
    for table, columns in {
        'pr_discord_rate_state': ('scope_key', 'kind', 'limit_count', 'remaining', 'window_seconds',
                                  'error_streak', 'observation_seq', 'revision', 'policy_revision'),
        'pr_discord_route_buckets': ('auth_key', 'route_key', 'major_key', 'bucket_key', 'observation_seq'),
        'pr_discord_request_admissions': ('application_key', 'auth_key', 'credential_key', 'credential_kind',
            'method', 'path_key', 'route_key', 'major_key', 'bucket_key', 'scope_keys', 'binding_hash',
            'publication_id', 'manifest_digest', 'authorization_digest', 'approval_digest', 'worker_key',
            'lease_key', 'channel_key', 'intent_id', 'state', 'status_code', 'rate_scope'),
    }.items():
        allowed.update(table + '_check' + (str(i) if i else '') for i in range(32))
        allowed.update(table + '_' + column + '_check' for column in columns)
    if isinstance(constraint, str) and constraint in allowed:
        result['constraint'] = constraint
    return result


def rate_metadata(error):
    cause = getattr(error, 'rate_cause', None)
    result = {'cause': cause if cause in ('rate_budget', 'window_expiring', 'permit_expired') else 'unknown'}
    wait = getattr(error, 'retry_after_seconds', None)
    if type(wait) in (int, float) and math.isfinite(wait) and 0 <= wait <= 253402300799:
        result['waitSeconds'] = wait
    scope = getattr(error, 'rate_scope_kind', None)
    if scope is not None:
        result['scope'] = scope if scope in ('application','discovery','learned_route','unknown_route',
                                           'embargo','permit','unknown') else 'unknown'
    return result


class FixtureLedger:
    """Every planned synthetic actor has one accounted outcome, including stops."""
    def __init__(self, planned):
        if type(planned) is not int or planned < 1:
            raise ValueError('Positive fixture denominator required')
        self.lock = threading.RLock()
        self.states = {i: 'queued' for i in range(planned)}
        self.attempted = set()
        self.failures = []

    def begin(self, index):
        with self.lock:
            if self.states.get(index) != 'queued':
                raise Incomplete('Fixture actor reused or already canceled')
            self.states[index] = 'running'
            self.attempted.add(index)

    def finish(self, index, state, error=None):
        with self.lock:
            prior = self.states.get(index)
            if state not in ('completed', 'failed', 'cancelled') or not (
                    prior == 'running' or prior == 'queued' and state == 'cancelled'):
                raise Incomplete('Invalid fixture outcome transition')
            self.states[index] = state
            if error is not None and len(self.failures) < 8:
                self.failures.append({'actor': index, 'state': state, **diagnostic(error)})

    def cancel_queued(self):
        with self.lock:
            for index, state in self.states.items():
                if state == 'queued':
                    self.states[index] = 'cancelled'

    def summary(self, indices=None):
        with self.lock:
            wanted = set(self.states if indices is None else indices)
            if not wanted <= self.states.keys():
                raise ValueError('Unknown fixture actor')
            counts = Counter(self.states[i] for i in wanted)
            cancelled = {i for i in wanted if self.states[i] == 'cancelled'}
            return {'planned': len(wanted), 'attempted': len(wanted & self.attempted),
                    **{k: counts[k] for k in ('completed', 'failed', 'cancelled', 'queued', 'running')},
                    'cancelledBeforeStart': len(cancelled - self.attempted),
                    'cancelledAfterStart': len(cancelled & self.attempted),
                    'unaccounted': len(wanted) - sum(counts.values()),
                    'complete': counts['completed'] == len(wanted),
                    'failureExamples': [x for x in self.failures if x['actor'] in wanted]}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def configure_candidate_provider(adapter, policy):
    """Give the existing OAuth mount its policy; it owns coordinator creation."""
    if not isinstance(policy, dict) or policy.get('version') != 1:
        raise Incomplete('Versioned synthetic rate policy required')
    adapter.authorization_v2_enabled = adapter.connections_v2_enabled = adapter.rate_v1_enabled = True
    adapter.rate_policy_raw = copy.deepcopy(policy)
    return adapter


def diagnostic(error):
    """Safe symbolic failure context, without exception messages/SQL/values."""
    import traceback
    result = {'type': type(error).__name__}
    for field, pattern in (('code', r'[a-z][a-z0-9_]{0,63}'), ('sqlstate', r'[A-Z0-9]{5}')):
        value = getattr(error, field, None)
        if isinstance(value, str) and re.fullmatch(pattern, value):
            result[field] = value
    status = getattr(error, 'status', None)
    if type(status) is int and 100 <= status <= 599:
        result['status'] = status
    result['frames'] = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                        for f in traceback.extract_tb(error.__traceback__)[-8:]]
    return result


def observe_dispatch_preflight(social, metrics):
    """Retain symbolic origins before the real worker converts a failure to held.

    No exception message, token, provider response or tenant identifier is emitted.
    This observation does not change the returned value or raised exception.
    """
    original = social.prepare_discord_dispatch
    def observed(manifest):
        try:
            return original(manifest)
        except Exception as error:
            detail = diagnostic(error)
            metrics.count('dispatchPreflightClass.' + detail['type'])
            if detail.get('code'):
                metrics.count('dispatchPreflightCode.' + detail['code'])
            for frame in detail['frames'][-4:]:
                metrics.count('dispatchPreflightFrame.' + frame['file'] + ':'
                              + frame['function'] + ':' + str(frame['line']))
            raise
    social.prepare_discord_dispatch = observed


def profile(stage):
    if stage not in ('a', 'b'):
        raise ValueError('Explicit stage a or b required')
    users = 1000 if stage == 'a' else 10000
    return {
        'version': 1, 'stage': stage, 'seed': 2026101401 if stage == 'a' else 2026101402,
        'users': users, 'guildsPerUser': 2, 'destinationsPerGuild': 3,
        'sharedGuildEvery': 10, 'sharedBotApplications': 1,
        'producerConcurrency': 16, 'comparisonReplicas': [1, 4],
        'comparisonJobsEach': 32, 'comparisonDrainSeconds': 60,
        'referenceReplicas': 8, 'burstJobs': users,
        'burstSubmissionSeconds': 5 if stage == 'a' else 10,
        'burstDrainSeconds': 180 if stage == 'a' else 300,
        'rampSeconds': 300, 'steadySeconds': 900 if stage == 'a' else 1800,
        'rampStartJobsPerSecond': .2 if stage == 'a' else .5,
        'steadyJobsPerSecond': 2 if stage == 'a' else 5,
        'sustainedDrainSeconds': 60, 'totalHarnessDeadlineSeconds': 2520,
        'setupDeadlineSeconds': 600, 'safetyCaseDeadlineSeconds': 60,
        'mock': {'totalRequestsPerSecond': 1000, 'createsPerSecond': 100,
                 'routeRequestsPerSecond': 250, 'nonceDedupWindowSeconds': 0,
                 'latencyBaseSeconds': .002, 'latencyJitterSeconds': .003,
                 'bulkFaultFraction': 0, 'faultCohort': 'explicit-safety-cases',
                 'quotaClaim': 'experiment parameters, not Discord quotas'},
        'plannedSafetyJobRequests': 23,
        # Conservative subset of actual REST: identity token/@me/user (3),
        # installation token/@me/user (3 each), five permission-evidence GETs
        # per destination. Guild listing/channel listing/refresh are omitted
        # here, so this is a LOWER bound, never a setup-time prediction.
        'bootstrapRequestLowerBoundPerUser': 3 + 2 * 3 + 6 * 5,
        'burstScheduleLeadSeconds': 60, 'comparisonScheduleLeadSeconds': 5,
        'targets': {'processingP95': .5, 'processingP99': 1.5,
                    'steadyDispatchP95': 10, 'steadyDispatchP99': 30,
                    'burstDispatchP95': 30 if stage == 'a' else 180,
                    'burstDispatchP99': 60 if stage == 'a' else 240,
                    'unsafeCreates': 0, 'duplicateCreates': 0,
                    'acceptedClaimCollisions': 0, 'unaccountedJobs': 0},
        'excluded': ['real Discord', 'browser OAuth concurrency', 'paid AI',
                     'production database', 'production cost prediction', 'two-hour soak'],
    }



def selected_profile(stage, environment=None):
    """Preserve historical profiles; name every resource change before execution."""
    environment=os.environ if environment is None else environment
    plan=environment.get('RAFII_DISCORD_CAPACITY_RESOURCE_PLAN','')
    if plan in ('workers16-api12-v5','b-extended-workers16-api12-v5'):
        if ((plan=='workers16-api12-v5' and stage not in ('a','pipeline-qualification'))
                or (plan=='b-extended-workers16-api12-v5' and stage!='b')):
            raise Incomplete('Unknown full API capacity stage')
        base='b-extended-workers16-parent16-v4' if stage=='b' else 'workers16-parent16-v4'
        p=selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':base})
        p.update(version=5,resourcePlan=plan,parentPoolSize=4,apiReplicas=12,apiPoolSize=1,
            aggregateConnectionCap=32,runnerSize='depot-ubuntu-24.04-32',cpu=32,memoryGiB=128,
            computeUsdPerSecond=.0016,jobTimeoutMinutes=225 if stage=='b' else 45,
            resourceChange='12 one-connection API replicas plus4 parent and16 one-connection worker replicas; aggregate32; original workloads, timing, quotas and targets unchanged')
        validate_worker_budget(p)
        return p
    if plan in ('workers16-parent16-v4','b-extended-workers16-parent16-v4'):
        base='b-extended-workers16-v3' if plan.startswith('b-extended-') else 'workers16-v3'
        p=selected_profile(stage,{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':base})
        p.update(version=4,resourcePlan=plan,parentPoolSize=16,aggregateConnectionCap=32,
            resourceChange='16 existing one-connection worker replicas; parent pool4 to16 and aggregate20 to32; workload, quotas, compute and targets unchanged')
        validate_worker_budget(p)
        return p
    if stage in ('pipeline-qualification','dispatch-diagnostic'):
        if plan not in ('','workers16-v3'):raise Incomplete('Unknown pipeline resource plan')
        p=profile('a')
        p.update(stage=stage,users=32,comparisonJobsEach=4,comparisonDrainSeconds=30,
            burstJobs=8,burstSubmissionSeconds=1,burstScheduleLeadSeconds=3,
            burstDrainSeconds=30,rampSeconds=2,steadySeconds=3,
            setupDeadlineSeconds=300,totalHarnessDeadlineSeconds=480,
            purpose='functional pipeline and full safety-case qualification only;capacity A/B NOT_RUN')
        if stage == 'dispatch-diagnostic':
            p.update(forceExpiredIdentityBeforeDispatch=True,
                     purpose='forced-expiry identity dispatch diagnosis only; capacity A/B NOT_RUN')
    elif stage=='burst-diagnostic':
        if plan not in ('','workers16-v3'):raise Incomplete('Unknown burst resource plan')
        p=profile('a')
        p.update(stage=stage,rampSeconds=2,steadySeconds=3,totalHarnessDeadlineSeconds=1200,
            purpose='1000-user burst diagnosis with original A burst targets;full capacity A/B NOT_RUN')
    else:
        p=profile(stage)
    if not plan:return p
    if plan=='workers16-v3' and stage in ('a','pipeline-qualification','burst-diagnostic','dispatch-diagnostic'):
        p.update(version=3,resourcePlan=plan,referenceReplicas=16,workerPoolSize=1,
            parentPoolSize=4,aggregateConnectionCap=20,
            resourceChange='16 existing worker replicas with one connection each; workload, quotas and latency targets unchanged')
        validate_worker_budget(p)
        return p
    if plan not in ('b-extended-v2','b-extended-workers16-v3') or stage!='b':
        raise Incomplete('Unknown capacity resource plan')
    p.update(version=2,resourcePlan='b-extended-v2',setupDeadlineSeconds=6000,
        totalHarnessDeadlineSeconds=12000,policyLifetimeSeconds=12300,
        runnerSize='depot-ubuntu-24.04-32',cpu=32,memoryGiB=128,
        computeUsdPerSecond=.0016,jobTimeoutMinutes=225,
        originalVersionOneStatus='BLOCKED: minimum2560s exceeds original2520s deadline',
        workloadAndTargets='UNCHANGED from version1;extended compute and time declared before execution')
    if plan=='b-extended-workers16-v3':
        p.update(version=3,resourcePlan=plan,referenceReplicas=16,workerPoolSize=1,
            parentPoolSize=4,aggregateConnectionCap=20,
            resourceChange='16 existing worker replicas with one connection each; B-v2 workload, resources, quotas and latency targets unchanged')
        validate_worker_budget(p)
    return p


def validate_worker_budget(p, replicas=None):
    """Bind process/pool arithmetic before spawn; booleans are never counts."""
    reference,pool=p['referenceReplicas'],p.get('workerPoolSize',2)
    parent,cap=p.get('parentPoolSize',4),p.get('aggregateConnectionCap',20)
    expanded=p.get('resourcePlan') in ('workers16-parent16-v4','b-extended-workers16-parent16-v4')
    api=p.get('resourcePlan') in ('admission-api-replicas-v1','workers16-api12-v5','b-extended-workers16-api12-v5')
    api_stage={'admission-api-replicas-v1':('admission-api-diagnostic',),
        'workers16-api12-v5':('a','pipeline-qualification'),'b-extended-workers16-api12-v5':('b',)}
    api_count,api_pool=p.get('apiReplicas',0),p.get('apiPoolSize',0)
    if (any(type(value) is not int for value in (reference,pool,parent,cap))
            or not 1<=reference<=16 or pool not in (1,2)
            or (api and (p.get('stage') not in api_stage[p['resourcePlan']] or p.get('version')!=5
                or any(type(v) is not int for v in (api_count,api_pool))
                or (reference,pool,parent,cap,api_count,api_pool)!=(16,1,4,32,12,1)))
            or (not api and (api_count!=0 or api_pool!=0))
            or (expanded and (p.get('version')!=4 or (reference,pool,parent,cap)!=(16,1,16,32)))
            or (not expanded and not api and (parent,cap)!=(4,20))
            or parent+reference*pool+api_count*api_pool>cap):
        raise Incomplete('Fixed worker/database connection budget exceeded')
    if replicas is not None and (type(replicas) is not int or not 1<=replicas<=reference
                                or parent+replicas*pool+api_count*api_pool>cap):
        raise Incomplete('Fixed worker-process budget exceeded')
    return pool


def planned_worker_groups(p):
    if p['stage']=='connection-diagnostic':return []
    validate_worker_budget(p)
    if p['stage'] in ('admission-diagnostic','admission-api-diagnostic'):
        if (p['comparisonReplicas']!=[] or p['users']!=1000 or p['burstJobs']!=10000
                or p['producerConcurrency']!=16 or p['referenceReplicas']!=16
                or p['stage']=='admission-api-diagnostic' and p.get('apiSmokeJobs')!=48):
            raise Incomplete('Unknown admission diagnostic workload')
        return ([('admission-smoke',16)] if p['stage']=='admission-api-diagnostic' else [])+[('admission-burst',16)]
    if p['comparisonReplicas']!=[1,4] or any(type(n) is not int for n in p['comparisonReplicas']):
        raise Incomplete('Unknown comparison worker plan')
    return [('comparison-1',1),('comparison-4',4),
            ('burst',p['referenceReplicas']),('sustained',p['referenceReplicas'])]


def admission_diagnostic_profile(api=False):
    """A deliberately nonqualifying multi-post stress probe before full A/B."""
    p=selected_profile('b',{'RAFII_DISCORD_CAPACITY_RESOURCE_PLAN':'b-extended-workers16-parent16-v4'})
    p.update(stage='admission-diagnostic',users=1000,comparisonReplicas=[],comparisonJobsEach=0,
        rampSeconds=0,steadySeconds=0,plannedSafetyJobRequests=0,
        setupDeadlineSeconds=600,totalHarnessDeadlineSeconds=1200,policyLifetimeSeconds=1500,
        jobTimeoutMinutes=45,minimumApprovalMarginSeconds=15,
        purpose='1000 connected tenants/10000 actual approval jobs; diagnostic only, full capacity A/B NOT_RUN',
        workloadAndTargets='Separate diagnostic; full A/B profiles remain unchanged')
    p.pop('originalVersionOneStatus',None)
    if api:
        p.update(version=5,stage='admission-api-diagnostic',resourcePlan='admission-api-replicas-v1',
            parentPoolSize=4,apiReplicas=12,apiPoolSize=1,apiSmokeJobs=48,
            purpose='1000 connected tenants/10000 approval jobs plus48 API-smoke jobs; diagnostic only,full capacity A/B NOT_RUN',
            resourceChange='12 owned one-connection API replicas plus4 parent and16 worker connections; aggregate32 and32CPU unchanged')
    planned_worker_groups(p)
    return p


def planned_api_groups(p):
    validate_worker_budget(p)
    if not p.get('apiReplicas'):return []
    return [(phase,p['apiReplicas']) for phase,_ in planned_worker_groups(p)]


def admission_margin(records,planned):
    if type(planned) is not int or planned<1 or len(records)!=planned:return None
    margins=[]
    for record in records:
        due,approved=record.get('due'),record.get('approvedAt')
        if (not record.get('jobId') or any(type(v) not in (int,float) or not math.isfinite(v)
                for v in (due,approved))):return None
        margins.append(due-approved)
    return min(margins)


def api_fixture(f):
    return {key:copy.deepcopy(f[key]) for key in ('index','user','token','workspace','destinations')}


def valid_api_request(value,phase,indices):
    return (isinstance(value,dict)
        and set(value)=={'index','alias','due','phase','arrival','destination','submittedAt'}
        and value['phase']==phase and type(value['index']) is int and value['index'] in indices
        and type(value['destination']) is int and 0<=value['destination']<6
        and type(value['alias']) is str and re.fullmatch('[a-z0-9-]{1,100}',value['alias']) is not None
        and all(type(value[k]) in (int,float) and math.isfinite(value[k]) for k in ('due','arrival','submittedAt')))


def api_event(record,value,phase):
    if (record is None or not isinstance(value,dict) or set(value)!={'name','fields'}
            or value['name'] not in ('approval','approval-failed') or not isinstance(value['fields'],dict)
            or value['fields'].get('alias')!=record['alias'] or value['fields'].get('phase')!=phase):
        raise Incomplete('Unexpected API event')
    name,fields=value['name'],value['fields']
    if name=='approval':
        valid=(set(fields)=={'alias','phase','payloadHash','authorizationHash'}
            and all(type(fields[k]) is str and re.fullmatch('[a-f0-9]{64}',fields[k]) for k in ('payloadHash','authorizationHash')))
    else:
        error=fields.get('error');valid=(set(fields)=={'alias','phase','error'} and isinstance(error,dict)
            and {'type','frames'}<=set(error)<={'type','frames','code','sqlstate','status'}
            and type(error['type']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,80}',error['type'])
            and isinstance(error['frames'],list) and len(error['frames'])<=8)
        if valid:
            valid=all(isinstance(f,dict) and set(f)=={'file','line','function'}
                and type(f['line']) is int and f['line']>0
                and type(f['file']) is str and re.fullmatch('[A-Za-z0-9_.-]{1,100}',f['file'])
                and type(f['function']) is str and re.fullmatch('[A-Za-z_<>][A-Za-z0-9_<>]{0,100}',f['function'])
                for f in error['frames'])
            for key,pattern in (('code','[a-z][a-z0-9_]{0,63}'),('sqlstate','[A-Z0-9]{5}')):
                if key in error:valid=valid and type(error[key]) is str and re.fullmatch(pattern,error[key]) is not None
            if 'status' in error:valid=valid and type(error['status']) is int and 100<=error['status']<=599
    if not valid:raise Incomplete('Unsafe API event fields')
    return name,fields


def api_preview(record,value,destination):
    """An IPC preview is an oracle registration, never publishing authority."""
    if (not isinstance(value,dict) or set(value)!={'alias','nonce','expectedJobId','manifest'}
            or value['alias']!=record['alias'] or record.get('manifest') is not None):
        raise Incomplete('Duplicate or mismatched API preview')
    f=record['fixture'];manifest=value['manifest']
    try:
        connection,guild,channel=f['destinations'][destination]
        target=manifest['discord']['target']
        valid=(manifest['workspaceId']==f['workspace'] and manifest['actor']==f['user']
            and manifest['platform']=='Discord' and manifest['channelId']==connection
            and (target['guildId'],target['channelId'])==(guild,channel)
            and target['applicationId']==APP and target['botUserId']==BOT
            and target['linkedUserId']==str(720000000000000000+f['index'])
            and type(manifest['timing']['timestamp']) in (int,float)
            and math.isfinite(manifest['timing']['timestamp'])
            and abs(manifest['timing']['timestamp']-record['due'])<.00001
            and type(value['expectedJobId']) is str and 0<len(value['expectedJobId'])<256
            and value['expectedJobId']==manifest['discord']['publicationId']
            and value['nonce']==hashlib.sha256(manifest['idempotencyKey'].encode()).hexdigest()[:25])
    except (KeyError,TypeError,ValueError,IndexError,AttributeError):valid=False
    if not valid:raise Incomplete('API preview differs from the requested tenant or destination')
    return value['nonce'],copy.deepcopy(manifest),value['expectedJobId']


def api_result(record,value):
    if (not isinstance(value,dict) or set(value)!={'alias','jobId','approvedAt','frozen','processing','error'}
            or value['alias']!=record['alias']):raise Incomplete('Mismatched API completion')
    if value['jobId'] is None:
        if (record.get('frozen') is not None or any(value[key] is not None for key in ('approvedAt','frozen','processing'))
                or type(value['error']) is not str or not re.fullmatch('[A-Za-z][A-Za-z0-9_.]{0,80}',value['error'])):
            raise Incomplete('Invalid failed API completion')
    elif (value['error'] is not None or value['jobId']!=record.get('expectedJobId')
            or not isinstance(value['frozen'],dict)
            or any(type(value[key]) not in (int,float) or not math.isfinite(value[key]) or value[key]<0
                for key in ('approvedAt','processing'))
            or record.get('manifest') is None
            or record.get('frozen') is not None and record['frozen']!=value['frozen']):
        raise Incomplete('API completion differs from the registered approval')
    return {key:copy.deepcopy(value[key]) for key in ('jobId','approvedAt','frozen','processing','error')}


def connection_diagnostic_profile():
    base = profile('a')
    return {'version': 1, 'stage': 'connection-diagnostic', 'purpose': 'diagnostic only; no capacity qualification',
            'seed': 2026101402, 'users': 32, 'serialUsers': 16, 'parallelUsers': 16,
            'guildsPerUser': 2, 'destinationsPerGuild': 3, 'sharedGuildEvery': base['sharedGuildEvery'],
            'sharedBotApplications': 1, 'producerConcurrency': 16, 'publishingAllowed': False,
            'totalHarnessDeadlineSeconds': 480, 'setupDeadlineSeconds': 480,
            'mock': copy.deepcopy(base['mock']),
            'phaseState': 'Shared coordinator/mock state retained from serial to parallel; cohorts differ',
            'capacityAcceptance': 'NOT_RUN', 'realDiscordAcceptance': 'NOT_RUN'}


def distribution(values, requested=None):
    """Nearest-rank quantiles; missing observations remain in the denominator."""
    values = list(values)
    requested = len(values) if requested is None else requested
    if type(requested) is not int or requested < len(values):
        raise ValueError('Invalid quantile denominator')
    if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0)
           for v in values):
        raise ValueError('Invalid latency')
    observed = sorted(v for v in values if v is not None)
    def q(fraction):
        return observed[math.ceil(fraction * len(observed)) - 1] if observed else None
    return {'requested': requested, 'observed': len(observed),
            'undefined': requested - len(observed), 'p95': q(.95), 'p99': q(.99),
            'max': observed[-1] if observed else None, 'method': 'nearest-rank'}


def accounting(requested, admitted, states):
    counts = Counter(states)
    known = sum(counts.values())
    complete = (type(requested) is int and type(admitted) is int
                and requested >= 0 and admitted == requested and known == admitted
                and all(k in TERMINAL for k in counts))
    return {'requested': requested, 'admitted': admitted, 'observed': known,
            'states': dict(counts), 'unadmitted': max(0, requested - admitted),
            'unobserved': max(0, admitted - known), 'complete': complete}


def require_fixture(p, observed):
    expected = {'users': p['users'], 'profiles': p['users'], 'memberships': p['users'],
                'workspaces': p['users'], 'distinctPrincipals': p['users'],
                'identities': p['users'], 'connections': p['users'] * 2,
                'grants': p['users'] * 3, 'destinations': p['users'] * 6,
                'distinctDestinationIds': p['users'] * 6}
    if any(observed.get(k) != v for k, v in expected.items()):
        raise Incomplete('Incomplete or reused tenant fixture')
    return expected


def validate_fence(platform, environment, database=None, transport=None):
    if (platform != 'linux' or environment.get('CI') != 'true'
            or environment.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1'
            or environment.get('POSTRIFF_TEST_DSN') != DSN):
        raise Incomplete('Approved owned Linux CI harness required')
    if database is not None:
        if (database.get('host'), database.get('port'), database.get('name'), database.get('user')) != (
                '127.0.0.1', 55438, 'postgres', 'postriff_test'):
            raise Incomplete('Foreign database refused')
        directory = Path(database.get('directory', ''))
        if (directory.name != 'data' or not directory.parent.name.startswith('postriff-cw-pg-')
                or not directory.is_absolute() or database.get('authColumns') != ['id']
                or database.get('majorVersion') != 17):
            raise Incomplete('Disposable cluster ownership/schema proof missing')
    if transport is not None and (type(transport).__name__ != 'MockDiscord'
                                  or getattr(transport, 'synthetic_only', False) is not True):
        raise Incomplete('Live or unknown transport refused')


def burst_offsets(count, seconds):
    """Finish the full producer cohort inside its unchanged strict window."""
    if (type(count) is not int or count < 1 or type(seconds) not in (int, float)
            or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError('Burst count and submission window must be positive and finite')
    # The last B arrival previously left only 1ms for sleep/submit jitter.
    # Reserve producer time; actual timestamps and the deadline gate stay strict.
    span = seconds - min(.1, seconds * .01)
    return [index * span / count for index in range(count)]


def arrivals(p):
    """Fixed logical arrival times, never a retrospective shorter steady phase."""
    offsets, accumulated, emitted = [], 0.0, 0
    for second in range(p['rampSeconds'] + p['steadySeconds']):
        rate = (p['rampStartJobsPerSecond'] + (p['steadyJobsPerSecond'] - p['rampStartJobsPerSecond'])
                * (second + .5) / p['rampSeconds']
                if second < p['rampSeconds'] else p['steadyJobsPerSecond'])
        accumulated += rate
        count = math.floor(accumulated + 1e-9) - emitted
        offsets.extend(second + (i + 1) / (count + 1) for i in range(count))
        emitted += count
    return offsets


def budget_lower_bound(p):
    minimum = (p['users'] * p['bootstrapRequestLowerBoundPerUser'] / p['mock']['totalRequestsPerSecond']
               + p['rampSeconds'] + p['steadySeconds'] + p['burstScheduleLeadSeconds']
               + len(p['comparisonReplicas']) * p['comparisonScheduleLeadSeconds'])
    return {'status': 'BLOCKED' if minimum >= p['totalHarnessDeadlineSeconds'] else 'PASS',
            'minimumSeconds': minimum, 'deadlineSeconds': p['totalHarnessDeadlineSeconds'],
            'excludedFromLowerBound': ['SQL time', 'Python/PG installation', 'safety cases', 'queue drain', 'cleanup'],
            'meaning': 'PASS is feasibility only; runtime capacity remains NOT_RUN'}


class Telemetry:
    def __init__(self, *, capture_events=True):
        self.lock = threading.RLock()
        self._expected_sql=threading.local()
        self.counters = Counter()
        self.timings = {}
        self.active = Counter()
        self.peak = Counter()
        self.records = {}
        self.samples = []
        self.sql_failures = []
        self.sql_operation_seconds = {}
        self.phase,self.phase_sql_operation_seconds='fixture',{}
        self.events = EVENTS.open('w') if capture_events else None

    def count(self, key, n=1):
        with self.lock:
            self.counters[key] += n

    def timing(self, key, value):
        with self.lock:
            self.timings.setdefault(key, []).append(value)

    def sql_timing(self, operation, elapsed):
        with self.lock:
            for stats in (self.sql_operation_seconds,self.phase_sql_operation_seconds.setdefault(self.phase,{})):
                row=stats.setdefault(operation,{'count':0,'totalSeconds':0.,'maxSeconds':0.})
                row['count']+=1;row['totalSeconds']+=elapsed;row['maxSeconds']=max(row['maxSeconds'],elapsed)

    def observe_sql(self, operation, elapsed):
        # Count every statement and retain every timing. Observer contention
        # must not serialize otherwise independent approval requests.
        with self.lock:
            self.counters['sqlStatements']+=1
            self.counters['sqlOperation.'+operation]+=1
            self.timings.setdefault('sqlExecuteSeconds',[]).append(elapsed)
            for stats in (self.sql_operation_seconds,self.phase_sql_operation_seconds.setdefault(self.phase,{})):
                row=stats.setdefault(operation,{'count':0,'totalSeconds':0.,'maxSeconds':0.})
                row['count']+=1;row['totalSeconds']+=elapsed;row['maxSeconds']=max(row['maxSeconds'],elapsed)

    @contextmanager
    def running(self, key):
        with self.lock:
            self.active[key] += 1
            self.peak[key] = max(self.peak[key], self.active[key])
        try:
            yield
        finally:
            with self.lock:
                self.active[key] -= 1

    def event(self, kind, **safe):
        # Callers supply aliases/counts/hashes only. No tokens, headers or bodies.
        with self.lock:
            if self.events is None:
                raise Incomplete('Child event output is forbidden')
            self.events.write(canonical({'kind': kind, 'at': time.time(), **safe}) + '\n')
            self.events.flush()

    def delay(self, error, action):
        safe = rate_metadata(error)
        self.count('admissionDelay.' + action + '.' + safe['cause'])
        if 'scope' in safe:
            self.count('admissionDelayScope.' + action + '.' + safe['scope'])
        if 'waitSeconds' in safe:
            self.timing('admissionWaitSeconds.' + action + '.' + safe['cause'], safe['waitSeconds'])

    @contextmanager
    def expected_sqlstate(self, state):
        if state!='42501':raise ValueError('Only explicit authorization probes may expect permission denial')
        previous=getattr(self._expected_sql,'state',None)
        self._expected_sql.state=state
        try:yield
        finally:self._expected_sql.state=previous

    def sql_failure(self, error, operation, started, expiry):
        safe = {'type': type(error).__name__, 'operation': operation,
                'statementSeconds': time.monotonic() - started, **sql_metadata(error)}
        if expiry is not None:
            safe['permitLeadAfterStatementSeconds'] = expiry - time.time()
        with self.lock:
            if len(self.sql_failures) < 24:
                self.sql_failures.append(safe)
        self.count('sqlFailureOperation.' + operation)

    def summary(self):
        with self.lock:
            return {'counters': dict(self.counters), 'actualPeakConcurrency': dict(self.peak),
                    'peakConcurrencyScopes': {key: ('parent broker-observed lifecycle overlap across spawned replicas'
                        if key == 'workerSteps' else 'parent control plane only; per-replica peaks are in worker summaries')
                        for key in self.peak},
                    'latencies': {k: distribution(v, self.counters['mockHttpAttempts'] if k == 'mockHttpSeconds' else len(v))
                                  for k, v in self.timings.items()},
                    'resourceSamples': self.samples, 'sqlFailureExamples': list(self.sql_failures),
                    'sqlObserver':{'templateCache':_sql_statement_category.cache_info()._asdict(),
                        'scope':'Process-local template categories only; no parameters,expiry,authorization or results cached',
                        'timing':'SQL execute elapsed ends before observer counter updates; dispatch wall clocks unchanged'},
                    'sqlOperationSeconds': copy.deepcopy(self.sql_operation_seconds),
                    'phaseSqlOperationSeconds':copy.deepcopy(self.phase_sql_operation_seconds)}


@lru_cache(maxsize=256)
def _sql_statement_category(query):
    """Cache a template's category only; no parameters, expiry or results."""
    if re.match(r'\s*WITH scope_store\b',query) and 'inserted_admission AS (' in query:
        return 'reservation_commit_batch'
    if re.match(r'\s*WITH scope_store\b',query) and 'observed_admission AS (' in query:
        return 'observation_commit_batch'
    if (re.match(r'\s*INSERT INTO public\.pr_discord_request_admissions\b',query)
            or re.match(r'\s*WITH reservation_clock AS MATERIALIZED\b',query)
            and re.search(r'\bINSERT INTO public\.pr_discord_request_admissions\b',query)):
        return 'admission_insert'
    if re.match(r'\s*WITH locked_alias AS MATERIALIZED\b',query):return 'alias_pending_lock'
    if re.match(r'\s*WITH locked_pending AS MATERIALIZED\b',query):return 'pending_lock'
    batch=re.match(r'\s*WITH scope_(seed|lock|store)\b',query)
    if batch:return 'scope_'+batch.group(1)+'_batch'
    if 'FROM public.pr_workspaces w' in query and 'SKIP LOCKED' in query:return 'worker_due_selection'
    if re.match(r'\s*SELECT .* FROM public\.pr_workspaces WHERE id=',query,re.S):return 'workspace_snapshot'
    if re.match(r'\s*UPDATE public\.pr_workspaces SET state=',query):return 'workspace_state_write'
    if ('FROM public.pr_discord_route_buckets' in query
            or re.match(r'\s*INSERT INTO public\.pr_discord_route_buckets\b',query)):
        return 'route_mapping_lock'
    if 'FROM public.pr_discord_request_admissions' in query:return 'admission_read'
    if 'UPDATE public.pr_discord_request_admissions' in query:return 'admission_write'
    if 'clock_timestamp()' in query:return 'database_clock'
    return 'other'


def sql_statement_category(query):
    # Bound retained template bytes as well as entry count. Unknown/oversized
    # inputs still receive exactly the same classification without caching.
    if type(query) is str and len(query)<=16384:return _sql_statement_category(query)
    return _sql_statement_category.__wrapped__(query)


class TimedCursor:
    def __init__(self, raw, metrics):
        self.raw, self.metrics = raw, metrics

    def __getattr__(self, key):
        return getattr(self.raw, key)

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, *args):
        return self.raw.__exit__(*args)

    def execute(self, *args, **kwargs):
        started = time.monotonic()
        # Inspect ONLY a known statement category and its expiry number. Never
        # emit SQL, arguments, epochs, credential identifiers or PG messages.
        query = args[0] if args and isinstance(args[0], str) else ''
        operation,expiry=sql_statement_category(query),None
        if operation in ('reservation_commit_batch','admission_insert'):
            values = args[1] if len(args) > 1 else None
            if isinstance(values, (tuple, list)) and values:
                candidate = values[-1]
                if type(candidate) in (int, float) and math.isfinite(candidate):
                    expiry = candidate
        try:
            self.raw.execute(*args, **kwargs)
            return self
        except Exception as error:
            expected=getattr(getattr(self.metrics,'_expected_sql',None),'state',None)
            if expected is not None and getattr(error,'sqlstate',None)==expected:
                self.metrics.count('expectedSqlAuthorizationDenials')
            else:
                self.metrics.count('sqlErrors.' + type(error).__name__)
                self.metrics.sql_failure(error, operation, started, expiry)
            raise
        finally:
            elapsed=time.monotonic()-started
            observe=getattr(self.metrics,'observe_sql',None)
            if callable(observe):observe(operation,elapsed)
            else:
                self.metrics.count('sqlStatements')
                self.metrics.count('sqlOperation.' + operation)
                self.metrics.timing('sqlExecuteSeconds',elapsed)
                if callable(getattr(self.metrics,'sql_timing',None)):self.metrics.sql_timing(operation,elapsed)


class TimedDatabase:
    def __init__(self, raw, metrics):
        self.raw, self.metrics = raw, metrics

    def __getattr__(self, key):
        return getattr(self.raw, key)

    def cursor(self, *args, **kwargs):
        return TimedCursor(self.raw.cursor(*args, **kwargs), self.metrics)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)


class MockDiscord:
    """Finite synthetic REST, independent admission accounting, no nonce dedup."""
    synthetic_only = True

    def __init__(self, runtime):
        self.r = runtime
        self.lock = threading.RLock()
        self.codes, self.tokens, self.refresh = {}, {}, {}
        self.guilds, self.channels = {}, {}
        self.faults, self.messages = {}, {}
        self.revoked_identity_indices = set()
        self.request_windows, self.create_windows, self.route_windows = Counter(), Counter(), Counter()
        self.accepted_request_windows = Counter()
        self.attempts, self.creates = [], []
        self.sequence = 0
        self.reordered_entered = threading.Event()
        self.reordered_finishes = []

    def register(self, index, user, guilds):
        with self.lock:
            for guild in guilds:
                self.guilds.setdefault(guild, {'members': set(), 'channels': []})['members'].add(user)
                if not self.guilds[guild]['channels']:
                    ids = [str(int(guild) + 100 + i) for i in range(3)]
                    self.guilds[guild]['channels'] = ids
                    for cid in ids:
                        self.channels[cid] = guild
            self.r.discord_users[index] = (user, guilds)

    def code(self, index, purpose, guild=None):
        with self.lock:
            self.sequence += 1
            code = 'fixture-code-' + str(self.sequence)
            self.codes[code] = (index, purpose, guild)
            return code

    def set_fault(self, cid, mode, times=1):
        with self.lock:
            self.faults[cid] = [mode, times]

    def __call__(self, method, url, **kwargs):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'discord.com'
                or not parsed.path.startswith('/api/v10/') or method not in ('GET', 'POST')):
            self.r.m.count('unexpectedTransport')
            raise Incomplete('Unexpected mocked provider route')
        path = parsed.path.removeprefix('/api/v10')
        if (method == 'GET' and path in ('/oauth2/@me','/users/@me')
                and kwargs.get('headers',{}).get('Authorization','').startswith('Bearer ')):
            phase=getattr(self.r,'progress_phase','unknown')
            if phase not in ('fixture','comparison-1','comparison-4','burst','sustained','safety','admission-smoke','admission-burst'):
                phase='unknown'
            kind='authorization' if path=='/oauth2/@me' else 'profile'
            self.r.m.count('mockBearerReads.'+kind+'.'+phase)
        start = time.monotonic()
        stamp = time.time()
        delayed_old_header = False
        if method == 'GET' and path.startswith('/guilds/'):
            with self.lock:
                guild = path.split('/')[2]
                cid = (self.guilds.get(guild, {}).get('channels') or [None])[0]
                fault = self.faults.get(cid)
                if fault and fault[0] == 'reordered-headers' and fault[1]:
                    fault[1] -= 1
                    delayed_old_header = True
                    self.reordered_entered.set()
            if delayed_old_header:
                # The earlier reserved request returns AFTER the later one.
                # Sleeping outside the response lock permits real reordering.
                time.sleep(.15)
        create = method == 'POST' and path.startswith('/channels/') and path.endswith('/messages')
        if create and self.r.p.get('stage') == 'connection-diagnostic':
            self.r.m.count('diagnosticPublishDenied')
            raise Incomplete('Publishing forbidden in connection diagnostic')
        # SQL oracle must not hold the provider's global response lock. Real
        # replicas can enter this transport concurrently rather than being
        # serialized by an artificial mock-wide database transaction.
        attempt = self.r.create_oracle(path.split('/')[2], kwargs.get('body') or {}, stamp) if create else None
        jitter = int(hashlib.sha256((method + path).encode()).hexdigest()[:4], 16) / 65535
        time.sleep(self.r.p['mock']['latencyBaseSeconds'] + jitter * self.r.p['mock']['latencyJitterSeconds'])
        with self.r.m.running('mockHttp'), self.lock:
            window = int(stamp)
            self.request_windows[window] += 1
            self.r.m.count('mockHttpAttempts')
            route = '/'.join(path.split('/')[:3])
            self.route_windows[(route, window)] += 1
            limit = self.r.p['mock']['routeRequestsPerSecond']
            if create:
                self.create_windows[window] += 1
            # Opaque bucket identifiers must not contain raw URL path characters.
            headers = {'X-RateLimit-Bucket': 'fixture-' + ('channel-shared' if path.startswith('/channels/') else hashlib.sha256(route.encode()).hexdigest()),
                       'X-RateLimit-Limit': str(limit),
                       'X-RateLimit-Remaining': str(max(0, limit - self.route_windows[(route, window)])),
                       'X-RateLimit-Reset-After': str(max(.001, window + 1 - time.time()))}
            if delayed_old_header:
                headers.update({'X-RateLimit-Bucket': 'fixture-stale-alias',
                                'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset-After': '.1'})
            # Every attempted create is captured, even if rejected or timed out.
            if create:
                self.attempts.append(attempt)
                self.r.m.event('mock-create-attempt', **attempt)
            status, response = 200, None
            if self.request_windows[window] > self.r.p['mock']['totalRequestsPerSecond']:
                status, response = 429, {'retry_after': max(.001, window + 1 - time.time()), 'global': True}
                headers.update({'X-RateLimit-Global': 'true', 'X-RateLimit-Scope': 'global'})
            elif create and self.create_windows[window] > self.r.p['mock']['createsPerSecond']:
                status, response = 429, {'retry_after': max(.001, window + 1 - time.time()), 'global': False}
                headers['X-RateLimit-Scope'] = 'shared'
            elif self.route_windows[(route, window)] > limit:
                status, response = 429, {'retry_after': max(.001, window + 1 - time.time()), 'global': False}
                headers['X-RateLimit-Scope'] = 'shared'
            cid = path.split('/')[2] if path.startswith('/channels/') else None
            guild = path.split('/')[2] if path.startswith('/guilds/') else self.channels.get(cid)
            fault_cid = cid or (self.guilds.get(guild, {}).get('channels') or [None])[0]
            fault = self.faults.get(fault_cid, [None, 0])
            mode = fault[0] if fault[1] else None
            bearer = kwargs.get('headers', {}).get('Authorization', '').removeprefix('Bearer ')
            if path == '/oauth2/@me' and bearer in self.tokens and self.tokens[bearer][0] in self.revoked_identity_indices:
                status, response = 401, {'message': 'Synthetic identity revoked'}
            preflight = method == 'GET' and path.startswith('/guilds/')
            if mode in ('removed-bot', 'permission-loss') and preflight:
                if mode == 'removed-bot' and '/members/' + BOT in path:
                    status, response = 404, {'message': 'Synthetic bot removed'}
                if mode == 'permission-loss' and path.endswith('/channels'):
                    status, response = 200, []
            elif mode in ('preflight-global-429', 'preflight-shared-429', 'preflight-timeout') and preflight:
                fault[1] -= 1
                if mode == 'preflight-timeout':
                    self.r.m.count('mockTimeouts')
                    raise TimeoutError('Synthetic preflight timeout')
                status, response = 429, {'retry_after': .2, 'global': mode == 'preflight-global-429'}
                headers.update({'Retry-After': '.2', 'X-RateLimit-Scope': 'global' if response['global'] else 'shared'})
                if response['global']:
                    headers['X-RateLimit-Global'] = 'true'
            elif create and mode in ('create-400', 'create-401', 'create-403', 'create-404', 'create-429', 'create-500'):
                fault[1] -= 1
                status = int(mode.split('-')[1])
                response = {'retry_after': .2, 'global': False} if status == 429 else {'message': 'Synthetic rejection'}
                if status == 429:
                    headers.update({'Retry-After': '.2', 'X-RateLimit-Scope': 'shared'})
            if response is None:
                response = self.route(method, path, kwargs, attempt)
                if create and mode in ('lost-create-response', 'unexpected-create-receipt'):
                    fault[1] -= 1
                    if mode == 'lost-create-response':
                        self.r.m.count('mockTimeouts')
                        raise TimeoutError('Synthetic lost create response')
                    response = {**response, 'content': 'Synthetic unexpected receipt'}
            if attempt is not None:
                attempt['status'] = status
            if status == 429:
                self.r.m.count('http429.' + headers.get('X-RateLimit-Scope', 'user'))
            else:
                self.accepted_request_windows[window] += 1
            self.r.m.timing('mockHttpSeconds', time.monotonic() - start)
            if path.startswith('/guilds/') and path.endswith(str(guild)):
                self.reordered_finishes.append({'at': time.time(), 'path': path, 'old': delayed_old_header})
            return {'status': status, 'body': response, 'headers': headers}

    def route(self, method, path, args, attempt):
        bearer = args.get('headers', {}).get('Authorization', '').removeprefix('Bearer ')
        if path == '/oauth2/token':
            form = args['form']
            if form['grant_type'] == 'refresh_token':
                index, purpose, guild = self.refresh[form['refresh_token']]
                self.r.m.count('oauthRefreshes')
            else:
                index, purpose, guild = self.codes.pop(form['code'])
            user, _ = self.r.discord_users[index]
            self.sequence += 1
            access, refresh = 'fixture-access-' + str(self.sequence), 'fixture-refresh-' + str(self.sequence)
            scopes = ['identify', 'guilds'] if purpose == 'identity' else ['identify', 'bot']
            self.tokens[access] = (index, scopes)
            self.refresh[refresh] = (index, purpose, guild)
            body = {'access_token': access, 'refresh_token': refresh, 'token_type': 'Bearer',
                    'expires_in': 3600, 'scope': ' '.join(scopes)}
            if guild:
                body['guild'] = {'id': guild}
            return body
        if path == '/oauth2/token/revoke':
            return {}
        if path == '/oauth2/applications/@me':
            return {'id': APP}
        if path == '/oauth2/@me':
            index, scopes = self.tokens[bearer]
            return {'application': {'id': APP}, 'user': {'id': self.r.discord_users[index][0]}, 'scopes': scopes}
        if path == '/users/@me':
            return {'id': self.r.discord_users[self.tokens[bearer][0]][0], 'username': 'Synthetic'} if bearer in self.tokens else {'id': BOT, 'bot': True}
        if path == '/users/@me/guilds':
            return [{'id': g, 'name': 'Synthetic guild', 'permissions': '32'} for g in self.r.discord_users[self.tokens[bearer][0]][1]]
        if path.startswith('/guilds/'):
            pieces = path.split('/')
            guild = pieces[2]
            record = self.guilds[guild]
            if len(pieces) == 3:
                return {'id': guild, 'name': 'Synthetic guild', 'owner_id': '718000000000000004',
                        'roles': [{'id': guild, 'permissions': str(self.r.Provider.PERMISSIONS | self.r.Provider.MANAGE_GUILD)}]}
            if pieces[3] == 'members':
                uid = pieces[4]
                if uid != BOT and uid not in record['members']:
                    raise Incomplete('Unexpected synthetic guild member')
                return {'user': {'id': uid}, 'roles': [], 'pending': False, 'communication_disabled_until': None}
            if pieces[3] == 'channels':
                return [{'id': c, 'guild_id': guild, 'name': 'synthetic', 'type': 0, 'position': i,
                         'permission_overwrites': []} for i, c in enumerate(record['channels'])]
        if method == 'POST' and attempt is not None:
            self.sequence += 1
            msg = {'id': str(719000000000000000 + self.sequence), 'channel_id': path.split('/')[2],
                   'content': args['body'].get('content'), 'author': {'id': BOT, 'bot': True},
                   'mention_everyone': False, 'mentions': [], 'mention_roles': [], 'attachments': []}
            self.messages[(msg['channel_id'], msg['id'])] = msg
            self.creates.append({**attempt, 'messageId': msg['id']})
            self.r.m.event('mock-created', alias=attempt['alias'], messageId=msg['id'],
                           payloadHash=attempt['payloadHash'], safe=attempt['safe'])
            return msg
        if method == 'GET' and path.startswith('/channels/') and '/messages/' in path:
            parts = path.split('/')
            self.r.m.count('knownMessageLookups')
            return copy.deepcopy(self.messages[(parts[2], parts[4])])
        self.r.m.count('unexpectedTransport')
        raise Incomplete('Unexpected synthetic REST route')


class Runtime:
    def __init__(self, p, metrics):
        # Heavy/application imports exist only AFTER the environment fence.
        validate_fence(sys.platform, os.environ)
        sys.path[:0] = [str(ROOT / 'src')]
        import psycopg
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.hosted import HostedWorkspaceService
        from postriff_phase2.hosted_social import HostedSocial
        from postriff_phase2.hosted_worker import PostgresWorker
        from postriff_phase2.oauth import CredentialVault
        from postriff_phase2.social_connectors import DiscordProvider
        from postriff_phase2.discord import authorization
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget, RateDelayed
        from postriff_phase2.postgres_pool import PooledPostgresFactory
        self.psycopg, self.Error, self.Provider, self.Worker = psycopg, AlphaError, DiscordProvider, PostgresWorker
        self.Service, self.Social, self.Vault, self.auth = HostedWorkspaceService, HostedSocial, CredentialVault, authorization
        self.RateDelayed, self.Budget = RateDelayed, SharedPostgresBudget
        self.p, self.m, self.started = p, metrics, time.monotonic()
        self.progress_phase,self.next_progress='fixture',self.started
        self.tokens, self.discord_users, self.fixtures, self.nonces = {}, {}, [], {}
        self.observed_claims, self.worker_summaries = {}, []
        self.api_summaries,self.api_child_fences,self.api_process_ids=[],[],set()
        self.worker_failure = threading.Event()
        self.worker_processes, self.reported_worker_pids = {}, set()
        self.finished_worker_cpu = 0.
        self.child_fences = []
        self.selector_plans = []
        self.safety_completed = False
        self.lock = threading.RLock()
        self.stop_sample = threading.Event()
        self.fixture_abort = threading.Event()
        self.fixture_ledger = FixtureLedger(p['users'])
        self.setup_deadline = None
        self.wire = MockDiscord(self)
        validate_fence(sys.platform, os.environ, transport=self.wire)
        # Connection resources are explicit profile inputs, never inferred from
        # load. Historical profiles retain4 parent/20 aggregate connections.
        self.database_factory = PooledPostgresFactory(DSN, max_size=p.get('parentPoolSize',4), max_waiting=64,
            options='-c statement_timeout=10000 -c lock_timeout=8000', observer=self.pool_statement)
        with self.connection() as db:
            row = db.execute("SELECT host(inet_server_addr()),inet_server_port(),current_database(),current_user,current_setting('data_directory'),current_setting('server_version_num')").fetchone()
            columns = db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0]
            self.database = {'host': row[0], 'port': row[1], 'name': row[2], 'user': row[3],
                             'directory': row[4], 'authColumns': columns, 'majorVersion': int(row[5]) // 10000}
            validate_fence(sys.platform, os.environ, self.database)
            self.postmaster_pid = int((Path(row[4]) / 'postmaster.pid').read_text().splitlines()[0])
            draft = ROOT / 'migrations/postriff/124_discord_rate_limits.sql'
            if hashlib.sha256(draft.read_bytes()).hexdigest() != DRAFT_SHA:
                raise Incomplete('Qualified migration draft drift')
            db.execute(draft.read_text())  # Only inside this runner-owned cluster.
            grants=ROOT/'migrations/postriff/125_discord_service_grants.sql'
            if hashlib.sha256(grants.read_bytes()).hexdigest()!='a0086cd1d01195c6114aba53de72cf5819d4c19b890b1716b453b33dc850c645':
                raise Incomplete('Qualified worker grant migration drift')
            db.execute(grants.read_text())
            db.execute((ROOT/'migrations/postriff/126_discord_worker_projection.sql').read_text())
            db.execute((ROOT/'migrations/postriff/128_discord_lease_protocol_fence.sql').read_text())
        now = time.time()
        self.policy = {'version': 1, 'revision': 'synthetic-p8-' + p['stage'],
                       'issued_at': now - 1, 'expires_at': now + p.get('policyLifetimeSeconds',3600),
                       'egress_scope': 'synthetic-p8', 'app_capacity': p['mock']['totalRequestsPerSecond'],
                       'app_window_seconds': 1, 'unknown_window_seconds': .05,
                       'invalid_capacity': 100, 'invalid_window_seconds': 60,
                       'failure_threshold': 3, 'circuit_seconds': .5,
                       'permit_ttl_seconds': 2, 'read_attempts': 3}
        def verify(token):
            return self.tokens[token]
        verify.session_id = lambda token, principal: 'synthetic-' + principal
        verify.auth_time = lambda token, principal: time.time()
        self.verify = verify
        self.synthetic_vault_key = self.Vault.generate_key()
        self.vault = self.Vault(self.synthetic_vault_key)
        self.sampler = threading.Thread(target=self.sample, name='p8-metrics', daemon=True)
        self.sampler.start()

    @contextmanager
    def connection(self):
        started = time.monotonic()
        with self.m.running('databaseConnections'):
            with self.database_factory() as db:
                if (db.info.host, db.info.port, db.info.dbname, db.info.user) != ('127.0.0.1', 55438, 'postgres', 'postriff_test'):
                    raise Incomplete('Unexpected database connection')
                self.m.timing('sqlConnectSeconds', time.monotonic() - started)
                yield TimedDatabase(db, self.m)

    def pool_statement(self, operation, elapsed, error):
        # These explicit reset statements execute outside TimedCursor. Include
        # their work rather than making connection reuse look artificially free.
        self.m.observe_sql('pool_reset',elapsed)
        if error is not None:
            self.m.count('sqlErrors.' + error)
            with self.m.lock:
                if len(self.m.sql_failures) < 24:
                    self.m.sql_failures.append({'type': error, 'operation': 'pool_reset', 'statementSeconds': elapsed})

    def guard(self, minimum_remaining=0):
        if getattr(self, 'worker_failure', None) is not None and self.worker_failure.is_set():
            raise Incomplete('Owned worker process failed')
        if self.fixture_abort.is_set():
            raise FixtureCancelled('Fixture work cooperatively canceled')
        if self.setup_deadline is not None and time.monotonic() + minimum_remaining >= self.setup_deadline:
            raise Incomplete('Fixture setup deadline exceeded')
        if self.m.counters['unsafeCreateAttempts'] or self.m.counters['unexpectedTransport']:
            raise Incomplete('Unsafe authorization or unexpected transport observed; stop workload')
        if time.monotonic() - self.started + minimum_remaining >= self.p['totalHarnessDeadlineSeconds']:
            raise Incomplete('Fixed workload exceeds remaining approved deadline')

    def retry_read(self, action):
        for _ in range(8):
            self.guard()
            try:
                return action()
            except self.RateDelayed as error:
                self.m.count('provenUnsentReadDelays')
                self.m.delay(error, 'read')
                self.guard(error.retry_after_seconds + 1)
                self.fixture_abort.wait(error.retry_after_seconds)
                self.guard()
        raise Incomplete('Connection workflow admission exhausted')

    def provider(self):
        adapter = self.Provider(APP, 'synthetic-client-secret', 'synthetic-shared-bot',
                                'https://rafii.example.invalid', transport=self.wire, production_reviewed=True)
        return configure_candidate_provider(adapter, self.policy)

    def oauth_flow(self, f, purpose, guild=None, reconnect=None):
        from urllib.parse import parse_qs, urlsplit
        for _ in range(8):
            inputs = {'discordPurpose': purpose}
            if purpose == 'identity':
                inputs['discoverGuilds'] = True
            else:
                inputs.update(identityConnectionId=f['identity'], guildId=guild)
            if reconnect:
                inputs['connectionId'] = reconnect
            start = self.retry_read(lambda: f['service'].oauth.start(f['workspace'], f['token'], 'discord',
                                    'identity' if purpose == 'identity' else 'publish', inputs))
            state = parse_qs(urlsplit(start['authorizeUrl']).query)['state'][0]
            code = self.wire.code(f['index'], purpose, guild)
            try:
                result = f['service'].oauth.complete(f['workspace'], f['token'], 'discord', state, code)
                if result.get('connected') is not True:
                    raise Incomplete('Synthetic OAuth callback did not connect')
                self.m.count('oauthCallbacksCompleted')
                return result['connectionId']
            except self.RateDelayed as error:
                # Callback states remain consumed; explicitly start a fresh
                # synthetic consent. Never retry a consumed code/state.
                self.m.count('oauthCallbacksRateDenied')
                self.m.delay(error, 'oauth_' + purpose)
                self.guard(error.retry_after_seconds + 1)
                self.fixture_abort.wait(error.retry_after_seconds)
                self.guard()
        raise Incomplete('Synthetic OAuth connection incomplete')

    def build_fixture(self, index):
        begun = time.monotonic()
        with self.m.running('connectionProducers'):
            self.guard()
            if self.setup_deadline is not None and self.setup_deadline < time.monotonic():
                raise Incomplete('Fixture setup deadline exceeded')
            uid = str(uuid5(NAMESPACE_URL, 'rafii-p8-' + str(self.p['seed']) + ':' + str(index)))
            token = 'fixture-session-' + str(index)
            user = str(720000000000000000 + index)
            guilds = [str(721000000000000000 + index * 1000),
                      SHARED_GUILD if index % self.p['sharedGuildEvery'] == 0 else str(722000000000000000 + index * 1000)]
            self.tokens[token] = uid
            self.wire.register(index, user, guilds)
            with self.connection() as db:
                db.execute('INSERT INTO auth.users(id) VALUES(%s)', (uid,))
            adapter = self.provider()
            service = self.Service(self.connection, self.verify, clock=time.time, vault=self.vault,
                                   providers={'discord': adapter}, public_base_url='https://rafii.example.invalid')
            if (adapter.rate_coordinator_degraded or adapter.rate_limiter is None
                    or adapter.rate_limiter.policy is None
                    or adapter.rate_policy_raw != self.policy):
                raise Incomplete('OAuth mount lost the reviewed synthetic rate policy')
            social = self.Social(service.oauth, {'discord': adapter})
            observe_dispatch_preflight(social, self.m)
            f = {'index': index, 'user': uid, 'token': token, 'guilds': guilds,
                 'service': service, 'provider': adapter, 'social': social}
            f['workspace'] = service.bootstrap(token, 'studio')['workspaceId']
            f['identity'] = self.oauth_flow(f, 'identity')
            f['connections'], f['destinations'] = [], []
            for guild in guilds:
                installed = self.oauth_flow(f, 'installation', guild)
                f['connections'].append(installed)
                for cid in self.wire.guilds[guild]['channels']:
                    self.retry_read(lambda c=cid, i=installed: service.oauth.choose_destination(f['workspace'], token, i, c))
                    f['destinations'].append((installed, guild, cid))
            f['lock'] = threading.Lock()
            self.m.timing('connectionWorkflowSeconds', time.monotonic() - begun)
            self.m.count('fixturesBuilt')
            return f

    def fixture_counts(self):
        users = [f['user'] for f in self.fixtures]
        workspaces = [f['workspace'] for f in self.fixtures]
        with self.connection() as db:
            result = {}
            for label, sql, ids in (
                ('users', 'SELECT count(*) FROM auth.users WHERE id=ANY(%s::uuid[])', users),
                ('profiles', 'SELECT count(*) FROM public.pr_profiles WHERE user_id=ANY(%s::uuid[])', users),
                ('memberships', "SELECT count(*) FROM public.pr_memberships WHERE user_id=ANY(%s::uuid[]) AND status='active'", users),
                ('distinctPrincipals', 'SELECT count(DISTINCT user_id) FROM public.pr_memberships WHERE user_id=ANY(%s::uuid[])', users),
                ('workspaces', 'SELECT count(*) FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', workspaces),
                ('grants', 'SELECT count(*) FROM public.pr_encrypted_credentials WHERE workspace_id=ANY(%s::uuid[])', workspaces)):
                result[label] = int(db.execute(sql, (ids,)).fetchone()[0])
            states = db.execute('SELECT state FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (workspaces,)).fetchall()
        identities = [i for row in states for i in row[0]['phase2'].get('discordIdentityLinks', [])]
        connections = [c for row in states for c in row[0]['phase2']['channels']]
        destinations = [d for c in connections for d in c.get('discordDestinations', [])]
        result.update(identities=len(identities), connections=len(connections), destinations=len(destinations),
                      distinctDestinationIds=len({d['id'] for d in destinations}))
        require_fixture(self.p, result)
        return result

    def state(self, f):
        with self.connection() as db:
            return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (f['workspace'],)).fetchone()[0]

    def job_states(self, records):
        wanted = {r['jobId']: r['alias'] for r in records if r['jobId']}
        workspaces = list({r['fixture']['workspace'] for r in records if r['jobId']})
        if not workspaces:
            return {}
        started=time.monotonic()
        with self.connection() as db:
            # Observe the same transaction snapshot without transferring and
            # decoding every frozen payload/intent/receipt in the parent. The
            # observer shares its process with synthetic HTTP brokers; full
            # job documents would make observation itself a load generator.
            rows = db.execute("""SELECT job->>'id',job->>'state'
                FROM public.pr_workspaces w CROSS JOIN LATERAL
                jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) job
                WHERE w.id=ANY(%s::uuid[])""", (workspaces,)).fetchall()
        self.m.count('capacityJobStatePolls')
        self.m.count('capacityJobStatePollRows',len(rows))
        self.m.timing('capacityJobStatePollSeconds',time.monotonic()-started)
        return {wanted[job_id]: state for job_id,state in rows if job_id in wanted}

    def change(self, f, update):
        # Synthetic scenario fault injection only; never changes approval data.
        with self.connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f['workspace'],)).fetchone()[0]
            update(state)
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                       (canonical(state), f['workspace']))

    def job(self, record):
        expected=record.get('jobId') or record.get('expectedJobId')
        return next(j for j in self.state(record['fixture'])['phase2']['jobs'] if j['id'] == expected)

    def command(self, f, revision, action, payload):
        # Client CAS conflicts caused by worker bookkeeping may reload the same
        # command. Retry only this explicit pre-mutation conflict; never alter
        # the preview digest, ignore authorization errors or replay uncertain IO.
        for _ in range(5):
            try:
                return f['service'].repository.mutate(f['workspace'], f['token'], revision, action, payload)
            except self.Error as error:
                if error.code != 'workspace_revision_conflict':
                    raise
                self.m.count('workspaceRevisionConflictsRetried')
                revision = f['service'].repository.get(f['workspace'], f['token'])['revision']
        raise Incomplete('Bounded revision reload exhausted')

    def approve(self, f, alias, due, phase, arrival=None, destination=0, submitted_at=None):
        self.guard()
        requested = time.time() if arrival is None else arrival
        with self.lock:
            if alias in self.m.records:
                raise Incomplete('Duplicate logical request alias')
            record = {'alias': alias, 'phase': phase, 'requestedAt': requested, 'due': due,
                      'submittedAt': requested if submitted_at is None else submitted_at,
                      'fixture': f, 'jobId': None, 'approvedAt': None, 'postAt': None}
            self.m.records[alias] = record
        admitted = time.time()
        self.m.timing('requestToAdmissionSeconds', max(0, admitted - requested))
        self.m.timing('submissionJitterSeconds', max(0, record['submittedAt'] - requested))
        self.m.timing('queueAdmissionSeconds', max(0, admitted - record['submittedAt']))
        started = time.monotonic()
        with self.m.running('approvalProducers'), f['lock']:
            try:
                variant = {'id': alias, 'platform': 'Discord', 'text': 'Synthetic capacity ' + alias,
                           'language': 'en', 'revision': 1, 'voiceRevision': None, 'briefRevision': 1,
                           'sourceIds': [], 'needsReview': False, 'blockedByRetraction': False,
                           'unknowns': [], 'warnings': [], 'contentTypeId': 'unclassified',
                           'contentTypeVersion': 'legacy', 'formatId': None, 'revisions': []}
                self.change(f, lambda s: s['variants'].append(variant))
                connection, guild, cid = f['destinations'][destination]
                snap = f['service'].repository.get(f['workspace'], f['token'])
                review = self.command(f, snap['revision'], 'p2_review',
                    {'variantId': alias, 'channelId': connection,
                     'destinationId': self.auth.destination_id(f['workspace'], connection, guild, cid),
                     'localTime': datetime.fromtimestamp(due, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f'),
                     'timeZone': 'UTC', 'acknowledgedWarnings': []})
                entry = review['state']['phase2']['reviews'][-1]
                # Register the exact preview identity before its approval can
                # become visible to a concurrent worker. This grants nothing:
                # create_oracle still reads durable approval, intent and sent
                # admission from SQL before accepting any mock delivery.
                preview=copy.deepcopy(entry['manifest'])
                expected_id=preview['discord']['publicationId']
                nonce=hashlib.sha256(preview['idempotencyKey'].encode()).hexdigest()[:25]
                record.update(expectedJobId=expected_id,manifest=preview,frozen=None)
                with self.lock:
                    if nonce in self.nonces:
                        raise Incomplete('Synthetic nonce collision')
                    self.nonces[nonce]=record
                approved = self.command(f, review['revision'], 'p2_approve',
                    {'reviewId': entry['id'], 'digest': entry['digest'], 'confirmed': True})
                # Repository responses are independent snapshots. The earlier
                # review object cannot acquire the jobId written at approval.
                confirmed=next(r for r in approved['state']['phase2']['reviews'] if r['id']==entry['id'])
                if confirmed.get('jobId')!=expected_id:
                    raise Incomplete('Approved publication differs from the exact preview')
                job=next(j for j in approved['state']['phase2']['jobs'] if j['id']==expected_id)
                if job['manifest']!=preview:
                    raise Incomplete('Approved manifest differs from the exact preview')
                with self.lock:
                    if record['frozen'] is not None and record['frozen']!=job['discordAuthorization']:
                        raise Incomplete('Concurrent delivery changed frozen approval')
                    record.update(jobId=job['id'],approvedAt=time.time(),frozen=copy.deepcopy(job['discordAuthorization']),
                                  processing=time.monotonic()-started)
                self.m.event('approval', alias=alias, phase=phase, payloadHash=job['manifest']['payloadDigest'],
                             authorizationHash=fingerprint(job['discordAuthorization']))
            except Exception as error:
                record['error'] = type(error).__name__
                self.m.count('approvalErrors.' + type(error).__name__)
                self.m.event('approval-failed', alias=alias, phase=phase, error=diagnostic(error))
        return record

    def create_oracle(self, cid, payload, at):
        nonce = payload.get('nonce')
        with self.lock:
            record = self.nonces.get(nonce)
        safe = False
        if record is not None:
            job = self.job(record)
            manifest = job['manifest']
            target = manifest['discord']['target']
            # Independently read durable intent and frozen consent from SQL.
            # An edit racing AFTER consumption cannot change this sent payload.
            intents = job.get('discordDispatchIntents', [])
            intent = intents[0] if len(intents) == 1 else {}
            digest_text = lambda value: hashlib.sha256(str(value).encode()).hexdigest()
            with self.connection() as db:
                consumed = db.execute("""SELECT manifest_digest,authorization_digest,approval_digest,
                    worker_key,lease_key,channel_key,state FROM public.pr_discord_request_admissions
                    WHERE workspace_id=%s AND publication_id=%s AND intent_id=%s AND id=%s::uuid""",
                    (record['fixture']['workspace'], job['id'], intent.get('id'), intent.get('rateAdmissionId'))).fetchone()
            expected = (fingerprint(manifest), job['discordAuthorization']['digest'], job['approvalDigest'],
                        digest_text(job.get('leaseOwner')), digest_text(job.get('leaseId')), digest_text(cid), 'sent')
            expected_authorization=record.get('frozen') or self.auth.approval(job)
            safe = (job['discordAuthorization'] == expected_authorization == self.auth.approval(job)
                    and manifest == record['manifest'] and job['approvedBy'] == record['fixture']['user']
                    and manifest['workspaceId'] == record['fixture']['workspace']
                    and manifest['actor'] == job['approvedBy'] and target['channelId'] == cid
                    and target['applicationId'] == APP and target['botUserId'] == BOT
                    and target['linkedUserId'] == self.discord_users[record['fixture']['index']][0]
                    and (manifest['channelId'], target['guildId'], cid) in record['fixture']['destinations']
                    and payload.get('content') == self.auth.wire_content(manifest)['content']
                    and payload.get('allowed_mentions') == {'parse': []}
                    and len(intents) == 1 and consumed == expected
                    and job.get('leaseUntil', 0) > at)
            with self.lock:
                if safe and record['frozen'] is None:
                    record['frozen']=copy.deepcopy(job['discordAuthorization'])
                elif safe and record['frozen']!=job['discordAuthorization']:
                    safe=False
                if record['postAt'] is None:
                    record['postAt'] = at
            alias = record['alias']
        else:
            alias = 'unrecognized'
        if not safe:
            self.m.count('unsafeCreateAttempts')
        return {'alias': alias, 'at': at, 'safe': safe, 'channelAlias': fingerprint(cid)[:16],
                'payloadHash': fingerprint(payload), 'status': None}

    def worker(self, replica, phase):
        f = self.fixtures[0]
        return self.Worker(self.connection, f['social'], worker_id='p8-' + phase + '-' + str(replica), discord_workers=True)

    @contextmanager
    def workers(self, replicas, phase, *, api=False):
        validate_worker_budget(self.p)
        pool_size=self.p['apiPoolSize'] if api else validate_worker_budget(self.p,replicas)
        if (api and ((phase,replicas) not in planned_api_groups(self.p) or pool_size!=1)
                or not api and (phase,replicas) not in planned_worker_groups(self.p)):
            raise Incomplete('Unplanned worker process group')
        context = multiprocessing.get_context('spawn')
        stop = context.Event()
        summaries, processes, brokers, channels, ready = [], [], [], [], []
        slots=[{'lock':threading.Lock(),'done':threading.Event(),'record':None,'destination':None} for _ in range(replicas)]
        def broker(channel, process, started, slot):
            active = False
            received = False
            request_id = 0
            try:
                while True:
                    if not channel.poll(.2):
                        if not process.is_alive():
                            raise Incomplete('Worker exited without complete evidence')
                        continue
                    kind, value = receive_worker_message(channel)
                    if kind == 'http':
                        if (not started.is_set() or not isinstance(value, dict)
                                or set(value) != {'requestId', 'method', 'url', 'kwargs'}
                                or type(value['requestId']) is not int or value['requestId'] != request_id + 1):
                            raise Incomplete('Invalid synthetic request identity')
                        request_id = value['requestId']
                        try:
                            response = self.wire(value['method'], value['url'], **value['kwargs'])
                        except TimeoutError:
                            send_worker_message(channel, 'timeout', {'requestId': request_id})
                        except BaseException:
                            self.worker_failure.set()
                            send_worker_message(channel, 'failure', {'requestId': request_id})
                        else:
                            send_worker_message(channel, 'response', {'requestId': request_id, 'response': response})
                        if self.m.counters['unsafeCreateAttempts'] or self.m.counters['unexpectedTransport']:
                            self.worker_failure.set()
                            stop.set()
                    elif kind == 'ready':
                        if started.is_set() or value != process.pid:
                            raise Incomplete('Invalid child readiness')
                        started.set()
                    elif kind == 'api-preview' and api:
                        record=slot['record']
                        if not started.is_set() or record is None:raise Incomplete('Unexpected API preview')
                        nonce,manifest,job_id=api_preview(record,value,slot['destination'])
                        with self.lock:
                            if nonce in self.nonces:raise Incomplete('Duplicate global API nonce')
                            record.update(manifest=manifest,expectedJobId=job_id)
                            self.nonces[nonce]=record
                        send_worker_message(channel,'api-preview-ack',{'alias':record['alias']})
                    elif kind == 'api-event' and api:
                        name,fields=api_event(slot['record'],value,phase)
                        self.m.event(name,**fields)
                    elif kind == 'api-result' and api:
                        record=slot['record']
                        if record is None or slot['done'].is_set():raise Incomplete('Duplicate API completion')
                        changes=api_result(record,value)
                        if changes['jobId'] is not None:changes['approvedAt']=time.time()
                        with self.lock:record.update(changes)
                        slot['done'].set()
                    elif kind in ('step-start', 'step-finish'):
                        if not started.is_set() or active == (kind == 'step-start'):
                            raise Incomplete('Invalid child step lifecycle')
                        with self.m.lock:
                            active = kind == 'step-start'
                            self.m.active['workerSteps'] += 1 if active else -1
                            self.m.peak['workerSteps'] = max(self.m.peak['workerSteps'], self.m.active['workerSteps'])
                    elif kind == 'summary':
                        if active or api and slot['record'] is not None and not slot['done'].is_set():
                            raise Incomplete('Child finished with active work')
                        validate_worker_summary(value, process.pid,pool_size)
                        absorb_worker_metrics(self.m, value.pop('metrics'), phase)
                        with self.lock:
                            self.reported_worker_pids.add(process.pid)
                            self.finished_worker_cpu += value['cpuSeconds']
                            fences=self.api_child_fences if api else self.child_fences
                            fences.append({'phase':phase,'pid':process.pid,**value['transportFence']})
                            summaries.append(value)
                        received = True
                        if value['status'] != 'PASS':
                            self.worker_failure.set()
                        break
                    else:
                        raise Incomplete('Unknown child protocol')
            except BaseException as error:
                self.worker_failure.set()
                self.m.event('worker-process-failed', phase=phase, error=diagnostic(error))
            finally:
                if active:
                    with self.m.lock:self.m.active['workerSteps'] -= 1
                if not received:self.worker_failure.set()
                channel.close()
        try:
            for index in range(replicas):
                parent, child = context.Pipe(duplex=True)
                channels.append(parent)
                worker_id = 'p8-' + ('api-' if api else '') + phase + '-' + str(index)
                arguments=(child,stop,worker_id,self.policy,self.synthetic_vault_key,
                    self.database,self.started+self.p['totalHarnessDeadlineSeconds'],pool_size)
                if api:arguments+=(self.p,phase,[api_fixture(f) for f in self.fixtures if f['index']%replicas==index])
                process = context.Process(target=process_api if api else process_worker,name=worker_id,args=arguments)
                try:start_owned_worker(process,child,processes,self.worker_processes,self.lock,self.reported_worker_pids)
                finally:
                    if api and process.pid is not None:
                        with self.lock:self.api_process_ids.add(process.pid)
                started = threading.Event()
                ready.append(started)
                thread = threading.Thread(target=broker,args=(parent,process,started,slots[index]),name=worker_id+'-mock',daemon=True)
                brokers.append(thread)
                thread.start()
            readiness_deadline = time.monotonic() + 30
            while not all(event.is_set() for event in ready):
                self.guard()
                if time.monotonic() >= readiness_deadline:
                    raise Incomplete('Worker process readiness deadline exceeded')
                stop.wait(.02)
            def approve(f,alias,due,selected_phase,arrival=None,destination=0,submitted_at=None):
                self.guard()
                if selected_phase!=phase:raise Incomplete('API request crossed workload phases')
                slot=slots[f['index']%replicas]
                while not slot['lock'].acquire(timeout=.1):self.guard()
                try:
                    self.guard()
                    requested=time.time() if arrival is None else arrival
                    record={'alias':alias,'phase':phase,'requestedAt':requested,'due':due,
                        'submittedAt':requested if submitted_at is None else submitted_at,
                        'fixture':f,'jobId':None,'approvedAt':None,'postAt':None}
                    with self.lock:
                        if alias in self.m.records:raise Incomplete('Duplicate API request alias')
                        self.m.records[alias]=record
                    slot.update(record=record,destination=destination);slot['done'].clear()
                    with self.m.running('apiRequests'):
                        send_worker_message(channels[f['index']%replicas],'api-approve',{'index':f['index'],
                            'alias':alias,'due':due,'phase':phase,'arrival':requested,'destination':destination,'submittedAt':record['submittedAt']})
                        while not slot['done'].wait(.1):self.guard()
                    return record
                finally:
                    slot['record']=None
                    slot['lock'].release()
            yield approve if api else processes
            self.guard()
        except BaseException:
            self.worker_failure.set()
            raise
        finally:
            stop.set()
            # Brokers remain alive until in-flight mock I/O and result collection
            # finish. One deadline for the group, never N unbounded joins.
            cleanup = reap_owned_workers(processes, brokers)
            for channel in channels:channel.close()
            with self.lock:
                for process in processes:
                    if process.pid not in cleanup['survivingPids']:
                        self.worker_processes.pop(process.pid, None)
                        if api:self.api_process_ids.discard(process.pid)
            complete = (len(summaries) == replicas and not cleanup['forcedCount']
                        and not cleanup['survivingPids'] and not cleanup['unfinishedBrokers'] and not cleanup['errors']
                        and all(p.exitcode == 0 for p in processes)
                        and all(s['status'] == 'PASS' for s in summaries))
            groups=self.api_summaries if api else self.worker_summaries
            groups.append({'phase': phase, 'replicas': replicas,
                'execution': 'spawned-processes', 'aggregateConnectionCap': self.p.get('aggregateConnectionCap',20),
                'parentConnectionCap': self.p.get('parentPoolSize',4), 'perReplicaConnectionCap': pool_size,
                'status': 'PASS' if complete else 'FAIL', 'cleanup': cleanup, 'workers': summaries})
            if not complete:
                self.worker_failure.set()
                self.m.count('workerShutdownUnfinished')
                raise Incomplete('Worker process shutdown or evidence incomplete')

    def wait_records(self, records, deadline):
        while True:
            self.guard()
            observed = self.job_states(records)
            if all(v in TERMINAL for v in observed.values()) or time.time() >= deadline:
                return observed
            time.sleep(.2)

    def job_probe(self, record):
        """Only aliases, reason categories, counts and relative clocks; no content/IDs."""
        job=self.job(record);now=time.time()
        reasons={
            'Discord reserved rate slot expired after sealing. No POST was started; manual review required before any fresh approval.':'slot_expired_after_seal',
            'Discord delivery is uncertain. Reconcile before any further publication.':'ambiguous_transport_or_guard',
            'No conclusive Discord create response; reconcile without resubmitting.':'ambiguous_provider_status'}
        reasons.update({
            'Discord authority changed during renewal; no new dispatch is permitted':'renewal_authority_changed',
            'Discord destination, grant, media or rollout verification is unavailable. Nothing was posted.':'preflight_unavailable',
            'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.':'lookup_unavailable',
            'Discord read-back did not match the approved message, author, channel and mention policy.':'lookup_mismatch',
            'Provider outcome is unknown; reconcile before retry':'adapter_exception',
            'Invalid provider retry delay; reconcile before retry':'invalid_retry_envelope'})
        operation=job.get('discordWorker') or {}
        result={'alias':record['alias'],'phase':record['phase'],'state':job.get('state'),
            'reason':reasons.get(job.get('providerConfirmed') or (job.get('events') or [{}])[-1].get('message'),'other'),
            'nextInSeconds':job.get('nextAt',now)-now,'leaseRemainingSeconds':job.get('leaseUntil',now)-now,
            'approvalRemainingSeconds':job['manifest']['expiresAt']-now,
            'workerStage':operation.get('stage'),'unsentFailures':operation.get('unsentFailures'),
            'rateReadRetries':operation.get('rateReadRetries'),'attemptCount':len(job.get('attempts',[])),
            'intentCount':len(job.get('discordDispatchIntents',[])),'receiptCount':len(job.get('discordReceipts',[])),
            'hasReference':bool(job.get('providerReference')),'manifestUnchanged':job['manifest']==record['manifest'],
            'authorizationUnchanged':job.get('discordAuthorization')==record.get('frozen')}
        intents=job.get('discordDispatchIntents',[])
        if len(intents)==1 and intents[0].get('rateAdmissionId'):
            with self.connection() as db:
                row=db.execute("SELECT state,extract(epoch from expires_at-clock_timestamp())::double precision,sent_at IS NOT NULL,outcome_at IS NOT NULL FROM public.pr_discord_request_admissions WHERE id=%s::uuid AND workspace_id=%s AND publication_id=%s AND intent_id=%s",(intents[0]['rateAdmissionId'],record['fixture']['workspace'],job['id'],intents[0]['id'])).fetchone()
            if row:result['admission']={'state':row[0],'expiresInSeconds':row[1],'sentRecorded':row[2],'outcomeRecorded':row[3]}
        return result

    def cohort_result(self, phase, records, states, deadline, replicas, reference, measurement_seconds=None):
        summary = accounting(len(records), sum(r['jobId'] is not None for r in records), states.values())
        requested = len(records)
        delays = distribution((None if r['postAt'] is None else max(0, r['postAt'] - r['due']) for r in records), requested)
        processing = distribution((r.get('processing') for r in records), requested)
        admission = distribution((None if r['approvedAt'] is None else max(0, r['approvedAt'] - r['requestedAt']) for r in records), requested)
        earliest = min((r['due'] for r in records), default=time.time())
        elapsed = max(0, time.time() - earliest)
        safety = summary['complete'] and summary['states'].get('verified', 0) == requested
        gates = {'accountingAndEligibleDelivery': safety}
        if reference:
            prefix = 'steady' if phase == 'steady' else 'burst'
            for q in ('p95', 'p99'):
                target = self.p['targets'][prefix + 'Dispatch' + q.upper()]
                gates['dispatch' + q.upper()] = delays[q] is not None and delays[q] < target and delays['undefined'] == 0
                if phase == 'steady':
                    gates['processing' + q.upper()] = processing[q] is not None and processing[q] < self.p['targets']['processing' + q.upper()] and processing['undefined'] == 0
            if phase in ('burst', 'admission-burst'):
                gates['drain'] = elapsed < self.p['burstDrainSeconds']
                gates['submissionWindow'] = max(r['submittedAt'] for r in records) - min(r['submittedAt'] for r in records) < self.p['burstSubmissionSeconds']
        result = {'phase': phase, 'replicas': replicas, 'referencePerformanceGates': reference,
                  'status': 'PASS' if all(gates.values()) else 'FAIL', 'gates': gates,
                  'accounting': summary, 'dispatchDelaySeconds': delays, 'processingSeconds': processing,
                  'requestToApprovedSeconds': admission, 'drainSeconds': elapsed,
                  'actualSubmissionWindowSeconds': max(r['submittedAt'] for r in records) - min(r['submittedAt'] for r in records),
                  'throughputMeasurementSeconds': elapsed if measurement_seconds is None else measurement_seconds,
                  'throughputJobsPerSecond': summary['states'].get('verified', 0) / max(.001, elapsed if measurement_seconds is None else measurement_seconds),
                  'latencyExclusions': 'No POST => undefined; held/failed/uncertain remain in denominator'}
        if result['status']!='PASS':
            result['failureExamples']=[self.job_probe(r) for r in records if r.get('jobId') and states.get(r['alias'])!='verified'][:8]
        self.m.event('cohort-result', **result)
        return result

    def selector_probe(self, due_at, count):
        """EXPLAIN only: future query parameters cannot claim or dispatch work."""
        from statistics import median
        from postriff_phase2.hosted_worker import due_workspaces_sql
        result={'workspacesWithBurstJobs':count,'clock':'future EXPLAIN only;worker clock/approvals unchanged','variants':{}}
        for projected in (False,True):
            samples=[];indexes=set();nodes=set()
            for _ in range(3):
                query=due_workspaces_sql(discord_only=True,discord_projected=projected)
                with self.connection() as db:
                    plan=db.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query,(due_at+1,due_at+1,[])).fetchone()[0][0]
                samples.append(plan['Execution Time'])
                def walk(node):
                    nodes.add(node['Node Type'])
                    if node.get('Index Name'):indexes.add(node['Index Name'])
                    for child in node.get('Plans',[]):walk(child)
                walk(plan['Plan'])
            result['variants']['projected' if projected else 'legacy']={
                'medianExecutionMilliseconds':median(samples),'indexes':sorted(indexes),'nodeTypes':sorted(nodes)}
        self.selector_plans.append(result)

    def burst(self, replicas, phase, count, comparison=False):
        selected = list(self.fixtures)
        random.Random(self.p['seed'] + replicas).shuffle(selected)
        if count>len(selected):
            if self.p['stage'] not in ('admission-diagnostic','admission-api-diagnostic'):
                raise Incomplete('Full workload exceeds distinct planned fixtures')
            selected=(selected*math.ceil(count/len(selected)))[:count]
        else:selected=selected[:count]
        duration = self.p['burstSubmissionSeconds'] if not comparison else 1
        drain = self.p['comparisonDrainSeconds'] if comparison else self.p['burstDrainSeconds']
        records = []
        with self.workers(replicas,phase),ThreadPoolExecutor(max_workers=self.p['producerConcurrency']) as pool,ExitStack() as actors:
            approve=actors.enter_context(self.workers(self.p['apiReplicas'],phase,api=True)) if self.p.get('apiReplicas') else self.approve
            started = time.time()
            due = started + (self.p['burstScheduleLeadSeconds'] if not comparison else self.p['comparisonScheduleLeadSeconds'])
            futures = []
            for index, offset in enumerate(burst_offsets(count, duration)):
                f = selected[index]
                arrival = started + offset
                time.sleep(max(0, arrival - time.time()))
                futures.append(pool.submit(approve,f,phase+'-'+str(index),due,phase,arrival,submitted_at=time.time()))
            records = [future.result() for future in futures]
            if not comparison:
                # Reproduce the default-channel exploit against already approved
                # posts; other five authorized destinations receive no broadcast.
                def edit_default(record):
                    f = record['fixture']
                    self.retry_read(lambda: f['service'].oauth.choose_destination(f['workspace'], f['token'],
                                          f['connections'][0], f['destinations'][1][2]))
                    if self.job(record)['discordAuthorization'] != record['frozen']:
                        raise Incomplete('Default edit changed frozen approval')
                list(pool.map(edit_default, [r for r in records[:64] if r['jobId']]))
                self.m.count('approvedDefaultsChanged', sum(r['jobId'] is not None for r in records[:64]))
                self.selector_probe(due,len({r['fixture']['workspace'] for r in records if r['jobId']}))
            states = self.wait_records(records, due + drain)
        return self.cohort_result(phase, records, states, due + drain, replicas, not comparison)

    def sustained(self):
        duration = self.p['rampSeconds'] + self.p['steadySeconds']
        self.guard(duration + self.p['sustainedDrainSeconds'] + 35)
        offsets = arrivals(self.p)
        selected = list(self.fixtures)
        random.Random(self.p['seed']).shuffle(selected)
        with self.workers(self.p['referenceReplicas'], 'sustained'), ThreadPoolExecutor(max_workers=self.p['producerConcurrency']) as pool,ExitStack() as actors:
            approve=actors.enter_context(self.workers(self.p['apiReplicas'],'sustained',api=True)) if self.p.get('apiReplicas') else self.approve
            started = time.time()
            futures = []
            for index, offset in enumerate(offsets):
                self.guard()
                arrival = started + offset
                time.sleep(max(0, arrival - time.time()))
                f = selected[index % len(selected)]
                futures.append(pool.submit(approve, f, 'sustained-' + str(index), arrival + 2, 'sustained', arrival, index % 6, submitted_at=time.time()))
            # Retain the full declared steady interval even if all work finished.
            time.sleep(max(0, started + duration - time.time()))
            records = [future.result() for future in futures]
            states = self.wait_records(records, started + duration + self.p['sustainedDrainSeconds'])
        results = []
        for phase in ('ramp', 'steady'):
            cohort = [r for r in records if (r['requestedAt'] < started + self.p['rampSeconds']) == (phase == 'ramp')]
            subset = {r['alias']: states[r['alias']] for r in cohort if r['alias'] in states}
            results.append(self.cohort_result(phase, cohort, subset, started + duration + self.p['sustainedDrainSeconds'], self.p['referenceReplicas'], phase == 'steady',
                                             self.p['rampSeconds'] if phase == 'ramp' else self.p['steadySeconds']))
        return {'status': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL',
                'declaredRampSeconds': self.p['rampSeconds'], 'declaredSteadySeconds': self.p['steadySeconds'],
                'actualDurationSeconds': time.time() - started, 'logicalRequested': len(offsets), 'cohorts': results}

    def exact_worker(self, f, label):
        return self.Worker(self.connection, f['social'], worker_id='p8-safety-' + label, discord_workers=True)

    def drive(self, record, seconds=None, known_receipt=False):
        end = time.time() + (self.p['safetyCaseDeadlineSeconds'] if seconds is None else seconds)
        worker = self.exact_worker(record['fixture'], record['alias'])
        while time.time() < end:
            self.guard()
            job = self.job(record)
            if job['state'] in TERMINAL and not (known_receipt and job['state'] == 'uncertain' and job.get('providerReference')):
                return job
            worker.step(workspace_id=record['fixture']['workspace'], job_id=job['id'],
                        approval_digest=job['approvalDigest'], dispatch_principal=record['fixture']['user'], discord_only=True)
            time.sleep(.1)
        self.m.event('safety-timeout',**self.job_probe(record))
        raise Incomplete('Safety case did not reach terminal state')

    def denied(self, label, action):
        try:
            result = action()
        except self.Error as error:
            if error.status not in (403, 404, 409):
                raise
            self.m.count('deniedAuthorizationAttempts')
            return {'action': label, 'status': 'PASS', 'denied': True}
        if result is False:
            self.m.count('deniedAuthorizationAttempts')
            return {'action': label, 'status': 'PASS', 'denied': True}
        raise Incomplete('Forbidden tenant/approval operation accepted')

    def safety(self):
        """Actual API/SQL rejection and fault cohorts, never fixture row-count PASS."""
        checks = []
        a, b = self.fixtures[:2]
        record = self.approve(a, 'safety-foreign', time.time() + 3, 'safety')
        if not record['jobId']:
            raise Incomplete('Safety approval incomplete')
        job = self.job(record)
        repo, oauth = a['service'].repository, a['service'].oauth
        review = self.state(a)['phase2']['reviews'][-1]
        actions = {
            'read': lambda: repo.get(a['workspace'], b['token']),
            'edit': lambda: repo.mutate(a['workspace'], b['token'], repo.get(a['workspace'], a['token'])['revision'],
                                     'variant_edit', {'variantId': record['alias'], 'variantRevision': 1, 'text': 'Synthetic foreign edit'}),
            'approve': lambda: repo.mutate(a['workspace'], b['token'], repo.get(a['workspace'], a['token'])['revision'],
                                         'p2_approve', {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True}),
            'dispatch': lambda: self.exact_worker(a, 'foreign').execute_job(repo, a['workspace'], b['token'], job['id'], job['approvalDigest']),
            'destination': lambda: oauth.remove_discord_destination(a['workspace'], b['token'], a['connections'][0], job['manifest']['destinationId']),
        }
        for label, action in actions.items():
            checks.append(self.denied('foreign-' + label, action))
        with self.connection() as db:
            db.execute('SET LOCAL ROLE authenticated')
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (b['user'],))
            for table, column in [('pr_workspaces', 'id'), ('pr_channels', 'workspace_id')]:
                if db.execute('SELECT count(*) FROM public.' + table + ' WHERE ' + column + '=%s', (a['workspace'],)).fetchone()[0] != 0:
                    raise Incomplete('Cross-tenant RLS read exposed data')
            for sql in ('UPDATE public.pr_workspaces SET state=\'{}\'::jsonb WHERE id=%s',
                        'SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s'):
                try:
                    with self.m.expected_sqlstate('42501'), db.transaction():
                        db.execute(sql, (a['workspace'],))
                except self.psycopg.errors.InsufficientPrivilege:
                    self.m.count('deniedRlsAttempts')
                else:
                    raise Incomplete('Browser read service credential or wrote tenant state')
        checks.append({'action': 'owned-db-rls', 'status': 'PASS'})
        self.drive(record)
        checks.append(self.fault_case(2, 'approved-content-edit', edit=True))
        checks.append(self.fault_case(3, 'removed-destination', remove=True))
        checks.append(self.fault_case(4, 'grant-disconnect', disconnect=True))
        checks.append(self.fault_case(5, 'member-revoked', member=True))
        for index, mode in enumerate(('removed-bot', 'permission-loss', 'preflight-global-429',
                'preflight-shared-429', 'reordered-headers', 'create-400', 'create-401',
                'create-403', 'create-404', 'create-429', 'create-500', 'lost-create-response',
                'unexpected-create-receipt', 'preflight-timeout'), 6):
            # All synthetic workspaces share one bot credential. Its 401 must
            # remain blocked across tenants, so test revocation only after all
            # other cases that legitimately need that credential have finished.
            if mode not in ('create-401','lost-create-response'):
                checks.append(self.fault_case(index, mode, mode=mode))
        # Refresh uses the real encrypted identity flow; compare consent generation.
        f = self.fixtures[21]
        with self.connection() as db:
            generation = db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (f['workspace'], f['identity'])).fetchone()[0]
            db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=clock_timestamp()-interval '1 second' WHERE workspace_id=%s AND connection_id=%s", (f['workspace'], f['identity']))
        before = self.m.counters['oauthRefreshes']
        self.retry_read(lambda: f['service'].oauth.discord_grant_for_worker(f['workspace'], f['connections'][0]))
        with self.connection() as db:
            after_generation = db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (f['workspace'], f['identity'])).fetchone()[0]
        if self.m.counters['oauthRefreshes'] != before + 1 or generation != after_generation:
            raise Incomplete('Refresh bypassed or changed original authorization')
        checks.append({'action': 'expiration-refresh', 'status': 'PASS'})
        checks.extend(self.lease_cases(self.fixtures[22]))
        checks.extend(self.concurrent_edit(self.fixtures[23]))
        checks.extend(self.oauth_state_cases(self.fixtures[24], b))
        checks.append(self.fault_case(25, 'remote-identity-revoked', remote_identity=True))
        checks.append(self.unapproved_target(self.fixtures[26]))
        checks.append(self.rate_reordering(self.fixtures[27]))
        # An ambiguous cold POST retains its discovery debit. Exercise it only
        # after all new-route cases. Do not clear that evidence or refund quota.
        checks.append(self.fault_case(17, 'lost-create-response', mode='lost-create-response'))
        # The earlier 400 learned this exact target's bucket. Credential shutdown
        # can then be tested on a known route without bypassing cold-route hold.
        checks.append(self.fault_case(11, 'create-401', mode='create-401'))
        self.safety_completed = True
        return {'status': 'PASS', 'checks': checks, 'scope': 'actual SQL/API, bounded synthetic negative cohort'}

    def fault_case(self, index, label, *, mode=None, edit=False, remove=False, disconnect=False, member=False, remote_identity=False):
        f = self.fixtures[index]
        record = self.approve(f, 'safety-' + label, time.time() + 2, 'safety')
        if not record['jobId']:
            raise Incomplete('Fault cohort missing approval')
        cid = f['destinations'][0][2]
        if edit:
            snap = f['service'].repository.get(f['workspace'], f['token'])
            f['service'].repository.mutate(f['workspace'], f['token'], snap['revision'], 'variant_edit',
                                         {'variantId': record['alias'], 'variantRevision': 1, 'text': 'Synthetic changed content'})
        if remove:
            f['service'].oauth.remove_discord_destination(f['workspace'], f['token'], f['connections'][0], record['manifest']['destinationId'])
        if disconnect:
            f['service'].oauth.disconnect(f['workspace'], f['token'], f['connections'][0])
        if member:
            with self.connection() as db:
                db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (f['workspace'], f['user']))
        if mode:
            self.wire.set_fault(cid, mode, 3 if mode == 'preflight-timeout' else 100 if mode in ('removed-bot', 'permission-loss') else 1)
        if remote_identity:
            self.wire.revoked_identity_indices.add(f['index'])
        if mode=='reordered-headers':
            self.rate_reordering(f)  # Two actual concurrent responses, then publish.
        # Membership loss must be observed by the autonomous tenant worker,
        # rather than accidentally relying on an authenticated user's endpoint.
        if member:
            worker = self.exact_worker(f, label)
            deadline = time.time() + self.p['safetyCaseDeadlineSeconds']
            while time.time() < deadline and self.job(record)['state'] not in TERMINAL:
                worker.step(discord_only=True)
                time.sleep(.1)
            current = self.job(record)
        else:
            current = self.drive(record, known_receipt=mode == 'unexpected-create-receipt')
        attempts = [x for x in self.wire.attempts if x['alias'] == record['alias']]
        creates = [x for x in self.wire.creates if x['alias'] == record['alias']]
        success = mode in ('preflight-global-429', 'preflight-shared-429', 'reordered-headers', 'unexpected-create-receipt')
        expected_creates = 1 if success or mode == 'lost-create-response' else 0
        # Run an additional exact step AFTER a terminal/uncertain outcome. This
        # must never generate a new POST; no mock nonce cache can hide one.
        original_posts = len(attempts)
        if not member:
            w = self.exact_worker(f, 'retry-' + label)
            w.step(workspace_id=f['workspace'], job_id=current['id'], approval_digest=current['approvalDigest'],
                   dispatch_principal=f['user'], discord_only=True)
        after_posts = sum(x['alias'] == record['alias'] for x in self.wire.attempts)
        expected_state = 'verified' if success else 'uncertain' if mode in ('create-500', 'lost-create-response') else None
        if (len(creates) != expected_creates or after_posts != original_posts
                or current['state'] not in TERMINAL or (expected_state and current['state'] != expected_state)
                or current['discordAuthorization'] != record['frozen']):
            raise Incomplete('Fault/authorization/retry outcome failed: ' + label)
        if mode == 'preflight-timeout' and (current['state'] != 'failed' or not current.get('discordWorker', {}).get('deadLetter')):
            raise Incomplete('Unsent failure did not reach durable dead letter')
        result = {'action': label, 'status': 'PASS', 'state': current['state'],
                  'postAttempts': after_posts, 'createdMessages': len(creates), 'authorizationUnchanged': True}
        self.m.event('safety-case', **result)
        return result

    def oauth_state_cases(self, f, foreign):
        from urllib.parse import parse_qs, urlsplit
        oauth = f['service'].oauth
        def start():
            value = oauth.start(f['workspace'], f['token'], 'discord', 'identity',
                                {'discordPurpose': 'identity', 'discoverGuilds': True, 'connectionId': f['identity']})
            return parse_qs(urlsplit(value['authorizeUrl']).query)['state'][0]
        state = start()
        code = self.wire.code(f['index'], 'identity')
        checks = [self.denied('oauth-foreign-member', lambda: oauth.complete(f['workspace'], foreign['token'], 'discord', state, code)),
                  self.denied('oauth-foreign-workspace', lambda: oauth.complete(foreign['workspace'], foreign['token'], 'discord', state, code)),
                  self.denied('oauth-state-tamper', lambda: oauth.complete(f['workspace'], f['token'], 'discord', state + 'tampered', code))]
        # Complete only the original bound consent; replay consumes no new token.
        connected = oauth.complete(f['workspace'], f['token'], 'discord', state, code)
        if connected.get('connected') is not True:
            raise Incomplete('Bound OAuth callback rejected')
        checks.append(self.denied('oauth-state-replay', lambda: oauth.complete(f['workspace'], f['token'], 'discord', state, code)))
        pending = start()
        oauth.discord_connections.disconnect_identity(f['workspace'], f['token'], f['identity'])
        checks.append(self.denied('late-callback-after-disconnect', lambda: oauth.complete(f['workspace'], f['token'], 'discord', pending,
                                               self.wire.code(f['index'], 'identity'))))
        return checks

    def unapproved_target(self, f):
        record = self.approve(f, 'safety-unapproved-target', time.time() + 1, 'safety')
        if not record['jobId']:
            raise Incomplete('Unapproved-target control missing original approval')
        time.sleep(max(0, record['due'] - time.time()) + .01)
        worker = self.exact_worker(f, 'unapproved-target')
        job = self.job(record)
        claimed = worker.claim(workspace_id=f['workspace'], job_id=job['id'], approval_digest=job['approvalDigest'],
                               dispatch_principal=f['user'], discord_only=True)
        if not claimed:
            raise Incomplete('Original target not claimable')
        prepared = f['social'].prepare_discord_dispatch(job['manifest'])
        prepared['ratePermit'] = f['social'].reserve_discord_send(job['manifest'], job=claimed['job'],
                                     workspace_id=f['workspace'], worker_id=worker.worker_id)
        claimed['discordPrepared'] = prepared
        if not worker.authorize_dispatch(claimed):
            raise Incomplete('Original target did not seal')
        changed = copy.deepcopy(job['manifest'])
        changed['discord']['target']['channelId'] = f['destinations'][2][2]
        response = f['social'].submit_discord_authorized(changed, claimed['discordDispatch'])
        worker.complete(claimed, response)
        if response['state'] != 'held' or any(x['alias'] == record['alias'] for x in self.wire.attempts):
            raise Incomplete('Unapproved target reached message transport')
        return {'action': 'unapproved-target-reusing-original-dispatch', 'status': 'PASS', 'postAttempts': 0}

    def rate_reordering(self, f):
        from postriff_phase2.discord.rate_limits import route_identity
        path = '/guilds/' + f['guilds'][0]
        cid = f['destinations'][0][2]
        self.wire.reordered_entered.clear()
        before = len(self.wire.reordered_finishes)
        self.wire.set_fault(cid, 'reordered-headers')
        with ThreadPoolExecutor(max_workers=2) as pool:
            earlier = pool.submit(f['provider']._bot, 'GET', path)
            if not self.wire.reordered_entered.wait(5):
                raise Incomplete('Delayed-header request never entered transport')
            later = pool.submit(f['provider']._bot, 'GET', path)
            later.result(timeout=5)
            earlier.result(timeout=5)
        finishes = [r for r in self.wire.reordered_finishes[before:] if r['path'] == path]
        if len(finishes) != 2 or finishes[0]['old'] or not finishes[1]['old']:
            raise Incomplete('Out-of-order response fixture did not reorder')
        identity = f['provider']._rate_identity('bot')
        route, major = route_identity('GET', path)
        route=hashlib.sha256(route.encode()).hexdigest()
        with self.connection() as db:
            bucket, observation = db.execute('SELECT bucket_key,observation_seq FROM public.pr_discord_route_buckets WHERE auth_key=%s AND route_key=%s AND major_key=%s',
                                             (identity.auth_key, route, major)).fetchone()
            maximum = db.execute('SELECT max(request_seq) FROM public.pr_discord_request_admissions WHERE auth_key=%s AND route_key=%s AND major_key=%s',
                                 (identity.auth_key, route, major)).fetchone()[0]
        expected = hashlib.sha256(('fixture-' + hashlib.sha256(path.encode()).hexdigest()).encode()).hexdigest()
        if observation != maximum or bucket != expected:
            raise Incomplete('Older header replaced a newer shared bucket observation')
        return {'action': 'real-concurrent-delayed-old-header', 'status': 'PASS',
                'responses': 2, 'newerAliasRetained': True}

    def lease_cases(self, f):
        record = self.approve(f, 'safety-lease', time.time() + 1, 'safety')
        if not record['jobId']:
            raise Incomplete('Lease approval missing')
        time.sleep(max(0, record['due'] - time.time()) + .01)
        job = self.job(record)
        barrier = threading.Barrier(8)
        def collide(index):
            w = self.exact_worker(f, 'collision-' + str(index))
            barrier.wait(timeout=10)
            claimed = w.claim(workspace_id=f['workspace'], job_id=job['id'],
                              approval_digest=job['approvalDigest'], dispatch_principal=f['user'], discord_only=True)
            return w, claimed
        with ThreadPoolExecutor(max_workers=8) as pool:
            pairs = list(pool.map(collide, range(8)))
        winners = [(w, c) for w, c in pairs if c]
        self.m.count('competingClaimAttempts', 8)
        self.m.count('acceptedClaimCollisions', max(0, len(winners) - 1))
        if len(winners) != 1:
            raise Incomplete('Concurrent worker collision bypassed lease')
        owner, claim = winners[0]
        if not owner.renew_discord_lease(claim):
            raise Incomplete('Lease renewal failed')
        stale = copy.deepcopy(claim)
        stale['job']['leaseId'] = 'synthetic-stale'
        if owner.renew_discord_lease(stale):
            raise Incomplete('Stale lease renewed')
        owner.request_shutdown()
        if not owner.release_discord_unsent(claim):
            raise Incomplete('Shutdown could not release unsent work')
        # Simulate a process dying after claim, then expire only its lease, never
        # its frozen approval or original scheduled time/provider budget.
        time.sleep(1.05)
        survivor = self.exact_worker(f, 'before-restart')
        claimed = survivor.claim(workspace_id=f['workspace'], job_id=job['id'],
                                 approval_digest=job['approvalDigest'], dispatch_principal=f['user'], discord_only=True)
        if not claimed:
            raise Incomplete('Released job not claimable')
        self.change(f, lambda s: next(j for j in s['phase2']['jobs'] if j['id'] == job['id']).update(leaseUntil=time.time() - 1))
        current = self.drive(record)
        if current['state'] != 'verified' or len(current.get('discordDispatchIntents', [])) != 1:
            raise Incomplete('Restart/expiry recovery was unsafe or unfinished')
        return [{'action': 'eight-contender-collision-renewal-shutdown-expiry-restart', 'status': 'PASS',
                 'acceptedOwners': 1, 'staleRenewal': False, 'dispatchIntents': 1}]

    def concurrent_edit(self, f):
        record = self.approve(f, 'safety-concurrent-edit', time.time() + 1, 'safety')
        if not record['jobId']:
            raise Incomplete('Concurrent edit approval missing')
        time.sleep(max(0, record['due'] - time.time()) + .01)
        barrier = threading.Barrier(2)
        def edit():
            snap = f['service'].repository.get(f['workspace'], f['token'])
            barrier.wait(timeout=10)
            try:
                return f['service'].repository.mutate(f['workspace'], f['token'], snap['revision'], 'variant_edit',
                       {'variantId': record['alias'], 'variantRevision': 1, 'text': 'Synthetic concurrent changed content'})
            except self.Error as error:
                if error.status != 409:
                    raise
                self.m.count('concurrentEditRevisionConflicts')
        def dispatch():
            barrier.wait(timeout=10)
            return self.drive(record)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(edit), pool.submit(dispatch)
            a.result(timeout=65)
            job = b.result(timeout=65)
        creates = [x for x in self.wire.creates if x['alias'] == record['alias']]
        if len(creates) > 1 or any(not c['safe'] for c in creates) or job['discordAuthorization'] != record['frozen']:
            raise Incomplete('Concurrent edit changed sent authorization')
        return [{'action': 'concurrent-edit-vs-dispatch', 'status': 'PASS', 'state': job['state'],
                 'createdMessages': len(creates), 'linearization': 'CAS edit or sealed original approval'}]

    def emit_progress(self, sample):
        phase=self.progress_phase
        if phase not in ('fixture','comparison-1','comparison-4','burst','sustained','safety','cleanup','admission-smoke','admission-burst'):
            phase='unknown'
        with self.m.lock:
            progress={'phase':phase,'elapsedSeconds':round(time.monotonic()-self.started,3),
                'fixturesCompleted':len(self.fixtures),'jobRequests':len(self.m.records),
                'mockHttpAttempts':int(self.m.counters['mockHttpAttempts']),
                'pipelineQueueDepth':int(sample['pipelineQueueDepth']),
                'unsentEligibleQueueDepth':int(sample['unsentEligibleQueueDepth']),
                'oldestFrozenDueLagSeconds':round(float(sample['oldestFrozenDueLagSeconds']),3)}
        # Explicit fields only; never serialize records, IDs, payloads or SQL.
        print('RAFII_DISCORD_CAPACITY_PROGRESS '+canonical(progress),flush=True)

    def sample(self):
        # Linux /proc process CPU/RSS, actual SQL wait/lock/deadlock counters.
        # Child CPU and individual pool/concurrency scopes are retained too.
        while not self.stop_sample.is_set():
            try:
                process = self.process_resources()
                with self.connection() as db:
                    waits = db.execute("SELECT count(*) FILTER(WHERE wait_event_type='Lock'),count(*) FILTER(WHERE state='active') FROM pg_stat_activity WHERE datname='postgres'").fetchone()
                    stats = db.execute("SELECT xact_commit,xact_rollback,deadlocks,temp_bytes FROM pg_stat_database WHERE datname='postgres'").fetchone()
                    queue = db.execute("""WITH observed AS (SELECT extract(epoch FROM clock_timestamp()) AS at),
                        jobs AS (SELECT j FROM public.pr_workspaces w CROSS JOIN LATERAL
                        jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
                        WHERE j#>>'{manifest,platform}'='Discord')
                        SELECT count(*) FILTER(WHERE j->>'state' NOT IN ('verified','held','failed','canceled')),
                        count(*) FILTER(WHERE j->>'state' IN ('scheduled','retrying') AND
                          coalesce((j->>'nextAt')::numeric,0)<=observed.at AND coalesce((j->>'leaseUntil')::numeric,0)<=observed.at),
                        coalesce(max(greatest(0,observed.at-(j#>>'{manifest,timing,timestamp}')::numeric))
                          FILTER(WHERE j->>'state' NOT IN ('verified','held','failed','canceled')),0)
                        FROM jobs CROSS JOIN observed""").fetchone()
                sample={'elapsedSeconds': time.monotonic() - self.started,
                        **process, 'lockWaiters': int(waits[0]), 'activeDatabaseSessions': int(waits[1]),
                        'transactionsCommitted': int(stats[0]), 'transactionsRolledBack': int(stats[1]),
                        'databaseDeadlocks': int(stats[2]), 'databaseTempBytes': int(stats[3]),
                        'pipelineQueueDepth': int(queue[0]), 'unsentEligibleQueueDepth': int(queue[1]),
                        'oldestFrozenDueLagSeconds': float(queue[2]), 'queueScope': 'all synthetic workspaces, includes read-back/uncertain work'}
                with self.m.lock:self.m.samples.append(sample)
                if time.monotonic()>=self.next_progress:
                    self.emit_progress(sample)
                    self.next_progress=time.monotonic()+30
            except Exception as error:
                self.m.count('metricSampleErrors.' + type(error).__name__)
            self.stop_sample.wait(5)

    def process_resources(self):
        processes = {}
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                data = path.read_text()
                fields = data[data.rfind(')') + 2:].split()
                processes[int(path.parent.name)] = (int(fields[1]), (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                                                    int(fields[21]) * os.sysconf('SC_PAGE_SIZE'))
            except (OSError, ValueError, IndexError):
                continue
        owned = {self.postmaster_pid}
        for _ in range(6):
            owned.update(pid for pid, v in processes.items() if v[0] in owned)
        own = processes.get(os.getpid())
        with self.lock:
            replica_ids = set(self.worker_processes)
            api_ids=set(getattr(self,'api_process_ids',set()))
            reported = set(self.reported_worker_pids)
            finished_cpu = self.finished_worker_cpu
        replicas = [v for pid, v in processes.items() if pid in replica_ids and v[0] == os.getpid()]
        active_cpu = sum(v[1] for pid, v in processes.items() if pid in replica_ids - reported and v[0] == os.getpid())
        database = [v for pid, v in processes.items() if pid in owned]
        return {'workerProcessCpuSeconds': own[1] + finished_cpu + active_cpu if own else None,
                'workerProcessRssBytes': own[2] + sum(v[2] for v in replicas) if own else None,
                'controlPlaneCpuSeconds': own[1] if own else None,
                'liveWorkerReplicas':sum(pid not in api_ids for pid in replica_ids if pid in processes and processes[pid][0]==os.getpid()),
                'liveApiReplicas':sum(pid in api_ids for pid in replica_ids if pid in processes and processes[pid][0]==os.getpid()),
                'databaseProcesses': len(database), 'databaseCpuSeconds': sum(v[1] for v in database) if database else None,
                'databaseRssBytes': sum(v[2] for v in database) if database else None,
                'rssMethod': 'sum of owned parent/replica or PostgreSQL process RSS; shared pages can be counted twice',
                'cpuMethod': 'control plane plus live and completed owned replicas; cumulative per-process CPU'}

    def final_safety(self):
        attempts = Counter(x['alias'] for x in self.wire.attempts)
        creates = Counter(x['alias'] for x in self.wire.creates)
        unsafe = sum(not c['safe'] for c in self.wire.creates)
        duplicates = sum(max(0, n - 1) for n in creates.values())
        repeated = sum(max(0, n - 1) for n in attempts.values())
        checks = {'unsafeCreates': unsafe, 'unsafeCreateAttempts': self.m.counters['unsafeCreateAttempts'],
                  'duplicateCreates': duplicates, 'repeatPostAttempts': repeated,
                  'acceptedClaimCollisions': self.m.counters['acceptedClaimCollisions'],
                  'unexpectedTransport': self.m.counters['unexpectedTransport'],
                  'workerShutdownUnfinished': self.m.counters['workerShutdownUnfinished']}
        accepted_creates = Counter(int(x['at']) for x in self.wire.creates)
        checks['sharedCreateLimitBypass'] = max(0, max(accepted_creates.values(), default=0) - self.p['mock']['createsPerSecond'])
        checks['sharedRequestLimitBypass'] = max(0, max(self.wire.accepted_request_windows.values(), default=0) - self.p['mock']['totalRequestsPerSecond'])
        coverage = (self.safety_completed and bool(self.wire.attempts)
            and self.m.counters['competingClaimAttempts'] == 8
            and sum(r['phase']=='safety' for r in self.m.records.values())==self.p['plannedSafetyJobRequests'])
        return {'status': 'FAIL' if any(checks.values()) else 'PASS' if coverage else 'NOT_RUN', **checks,
                'scenarioCoverageComplete': coverage,
                'postAttempts': len(self.wire.attempts), 'createdMessages': len(self.wire.creates),
                'postAttemptAmplification': len(self.wire.attempts) / max(1, len(attempts)),
                'postAttemptToCreatedRatio': len(self.wire.attempts) / max(1, len(creates)),
                'nonceDedupWindowSeconds': 0, 'exactlyOnceClaim': False,
                'collisionEvidence': 'eight simultaneous real SQL contenders plus immutable single-intent/receipt checks' if coverage else 'NOT_RUN',
                'sharedApplication': {'requestCeiling': self.p['mock']['totalRequestsPerSecond'],
                    'createCeiling': self.p['mock']['createsPerSecond'],
                    'maxObservedRequestsInOneSecond': max(self.wire.request_windows.values(), default=0),
                    'maxAcceptedRequestsInOneSecond': max(self.wire.accepted_request_windows.values(), default=0),
                    'maxAttemptedCreatesInOneSecond': max(self.wire.create_windows.values(), default=0),
                    'maxAcceptedCreatesInOneSecond': max(accepted_creates.values(), default=0)},
                'readBackLookups': self.m.counters['knownMessageLookups']}

    def close(self):
        survivors = False
        with self.lock:remaining = list(self.worker_processes.values())
        if remaining:
            cleanup = reap_owned_workers(remaining, [])
            with self.lock:
                for process in remaining:
                    if process.pid not in cleanup['survivingPids']:
                        self.worker_processes.pop(process.pid, None)
            survivors = bool(cleanup['survivingPids'])
        self.stop_sample.set()
        self.sampler.join(timeout=12)
        if self.sampler.is_alive():
            raise Incomplete('Resource sampler shutdown incomplete')
        if survivors:
            raise Incomplete('Owned test worker survived final cleanup')


def worker_metric_payload(metrics):
    with metrics.lock:
        return {'counters': dict(metrics.counters), 'timings': copy.deepcopy(metrics.timings),
                'peak': dict(metrics.peak), 'sqlFailures': list(metrics.sql_failures),
                'sqlOperations': copy.deepcopy(metrics.sql_operation_seconds)}


def absorb_worker_metrics(metrics, payload, phase):
    if (not isinstance(payload, dict)
            or set(payload) != {'counters', 'timings', 'peak', 'sqlFailures', 'sqlOperations'}):
        raise Incomplete('Worker metric evidence is incomplete')
    for collection in ('counters', 'timings', 'peak', 'sqlOperations'):
        if (not isinstance(payload[collection], dict)
                or any(not isinstance(key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{0,100}', key)
                       for key in payload[collection])):
            raise Incomplete('Invalid worker metric category')
    numeric = lambda value: type(value) in (int, float) and math.isfinite(value) and value >= 0
    if (any(type(value) is not int or value < 0 for name in ('counters', 'peak') for value in payload[name].values())
            or any(not isinstance(values, list) or not all(numeric(x) for x in values) for values in payload['timings'].values())
            or not isinstance(payload['sqlFailures'], list) or len(payload['sqlFailures']) > 24):
        raise Incomplete('Invalid worker numeric evidence')
    for row in payload['sqlOperations'].values():
        if (not isinstance(row, dict) or set(row) != {'count', 'totalSeconds', 'maxSeconds'}
                or type(row['count']) is not int or row['count'] < 0
                or not numeric(row['totalSeconds']) or not numeric(row['maxSeconds'])):
            raise Incomplete('Invalid worker SQL timing evidence')
    with metrics.lock:
        metrics.counters.update(payload['counters'])
        for key, values in payload['timings'].items():metrics.timings.setdefault(key, []).extend(values)
        metrics.sql_failures.extend(payload['sqlFailures'][:max(0, 24-len(metrics.sql_failures))])
        for operation, value in payload['sqlOperations'].items():
            for collection in (metrics.sql_operation_seconds, metrics.phase_sql_operation_seconds.setdefault(phase, {})):
                row = collection.setdefault(operation, {'count': 0, 'totalSeconds': 0., 'maxSeconds': 0.})
                row['count'] += value['count']
                row['totalSeconds'] += value['totalSeconds']
                row['maxSeconds'] = max(row['maxSeconds'], value['maxSeconds'])
        # Per-process peaks are retained in worker summaries. Adding unrelated
        # peaks would invent simultaneous checkout concurrency.


def validate_worker_summary(value, pid, pool_size=2):
    fields = {'pid', 'worker', 'status', 'cpuSeconds', 'counters', 'poolStats',
              'transportFence', 'metrics', 'error', 'perProcessPeakConcurrency'}
    if (not isinstance(value, dict) or set(value) != fields or value['pid'] != pid
            or value['status'] not in ('PASS', 'FAIL')
            or type(value['cpuSeconds']) not in (int, float) or not math.isfinite(value['cpuSeconds'])
            or value['cpuSeconds'] < 0 or not isinstance(value['poolStats'], dict)
            or not isinstance(value['transportFence'], dict)):
        raise Incomplete('Missing owned worker evidence')
    fence, pool = value['transportFence'], value['poolStats']
    if (type(pool_size) is not int or pool_size not in (1,2)
            or type(fence.get('unexpectedAttempts')) is not int or fence['unexpectedAttempts']!=0
            or type(fence.get('expectedSelfCheckDenials')) is not int or fence['expectedSelfCheckDenials']!=4
            or pool.get('closed') is not True or type(pool.get('maxConnections')) is not int
            or pool['maxConnections'] != pool_size):
        raise Incomplete('Worker fence or pool cleanup failed')
    if value['status'] == 'PASS' and value['error'] is not None:
        raise Incomplete('Worker error cannot be passing evidence')


class SpawnMockTransport:
    """One in-flight synthetic request per child, over its owned bounded pipe."""
    synthetic_only = True

    def __init__(self, channel, metrics):
        self.channel, self.metrics, self.request_id = channel, metrics, 0

    def refuse(self):
        self.metrics.count('unexpectedTransport')
        raise Incomplete('Owned synthetic transport protocol failed')

    def __call__(self, method, url, **kwargs):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if (method not in ('GET', 'POST') or parsed.scheme != 'https' or parsed.netloc != 'discord.com'
                or not parsed.path.startswith('/api/v10/')):
            self.refuse()
        self.request_id += 1
        send_worker_message(self.channel, 'http', {'requestId': self.request_id, 'method': method,
                                                  'url': url, 'kwargs': kwargs})
        if not self.channel.poll(15):
            self.refuse()
        kind, value = receive_worker_message(self.channel)
        if (kind not in ('response', 'timeout', 'failure') or not isinstance(value, dict)
                or type(value.get('requestId')) is not int or value['requestId'] != self.request_id
                or set(value) != ({'requestId', 'response'} if kind == 'response' else {'requestId'})):
            self.refuse()
        if kind == 'timeout':raise TimeoutError('Synthetic transport timeout')
        if kind == 'failure':self.refuse()
        return value['response']


def process_api(channel,stop,worker_id,policy,synthetic_vault_key,expected_database,deadline,pool_size,p,phase,fixtures):
    """One independently fenced API process/pool, using the same real commands."""
    signal.pthread_sigmask(signal.SIG_UNBLOCK,WORKER_SIGNALS)
    validate_fence(sys.platform,os.environ)
    import sitecustomize
    sitecustomize.self_check()
    replica=None;error=None;stack=ExitStack()
    class ApiMetrics(Telemetry):
        def event(self,name,**fields):
            if name not in ('approval','approval-failed'):raise Incomplete('Unscoped API event')
            send_worker_message(channel,'api-event',{'name':name,'fields':fields})
    metrics=ApiMetrics(capture_events=False);metrics.phase=phase
    try:
        if pool_size!=1 or (phase,p.get('apiReplicas')) not in planned_api_groups(p):
            raise Incomplete('Unknown API process budget')
        validate_worker_budget(p)
        sys.path[:0]=[str(ROOT/'src')]
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.hosted import HostedWorkspaceService
        from postriff_phase2.oauth import CredentialVault
        from postriff_phase2.social_connectors import DiscordProvider
        from postriff_phase2.postgres_pool import PooledPostgresFactory
        from postriff_phase2.discord import authorization
        from unittest.mock import patch
        stack.enter_context(patch('postriff_phase2.billing.require_publishing',return_value=None))
        stack.enter_context(patch('postriff_phase2.billing.require_plan_capacity',return_value=None))
        class Replica:
            connection=Runtime.connection
            pool_statement=Runtime.pool_statement
            approve=Runtime.approve
            command=Runtime.command
            change=Runtime.change
            state=Runtime.state
            def guard(self):
                if stop.is_set() or time.monotonic()>=deadline:
                    raise Incomplete('Owned API stopped or fixed deadline exceeded')
        replica=Replica();replica.m=metrics;replica.Error=AlphaError;replica.auth=authorization
        replica.lock=threading.RLock()
        replica.database_factory=PooledPostgresFactory(DSN,max_size=1,max_waiting=8,
            options='-c statement_timeout=10000 -c lock_timeout=8000',observer=replica.pool_statement)
        with replica.connection() as db:
            row=db.execute("SELECT host(inet_server_addr()),inet_server_port(),current_database(),current_user,current_setting('data_directory'),current_setting('server_version_num')").fetchone()
            columns=db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0]
            database={'host':row[0],'port':row[1],'name':row[2],'user':row[3],
                'directory':row[4],'authColumns':columns,'majorVersion':int(row[5])//10000}
            validate_fence(sys.platform,os.environ,database)
            if database!=expected_database:raise Incomplete('API database differs from owned parent')
        by_index={f['index']:f for f in fixtures}
        if len(by_index)!=len(fixtures):raise Incomplete('Duplicate API fixture ownership')
        tokens={f['token']:f['user'] for f in fixtures}
        if len(tokens)!=len(fixtures):raise Incomplete('Duplicate API principal mapping')
        def verify(token):return tokens[token]
        verify.session_id=lambda token,principal:'synthetic-'+principal
        verify.auth_time=lambda token,principal:time.time()
        transport=SpawnMockTransport(channel,metrics)
        provider=configure_candidate_provider(DiscordProvider(APP,'synthetic-client-secret','synthetic-shared-bot',
            'https://rafii.example.invalid',transport=transport,production_reviewed=True),policy)
        service=HostedWorkspaceService(replica.connection,verify,clock=time.time,
            vault=CredentialVault(synthetic_vault_key),providers={'discord':provider},public_base_url='https://rafii.example.invalid')
        class Nonces(dict):
            def __setitem__(self,nonce,record):
                send_worker_message(channel,'api-preview',{'alias':record['alias'],'nonce':nonce,
                    'manifest':record['manifest'],'expectedJobId':record['expectedJobId']})
                if not channel.poll(15):raise Incomplete('API preview acknowledgement missing')
                kind,value=receive_worker_message(channel)
                if kind!='api-preview-ack' or value!={'alias':record['alias']}:
                    raise Incomplete('API preview acknowledgement differs')
                super().__setitem__(nonce,record)
        replica.nonces=Nonces()
        for f in fixtures:f.update(service=service,lock=threading.Lock())
        send_worker_message(channel,'ready',os.getpid())
        while not stop.is_set():
            if time.monotonic()>=deadline:raise Incomplete('Fixed API deadline exceeded')
            if not channel.poll(.1):continue
            if stop.is_set():break
            kind,value=receive_worker_message(channel)
            if kind!='api-approve' or not valid_api_request(value,phase,by_index):
                raise Incomplete('Unscoped API approval request')
            record=replica.approve(by_index[value['index']],value['alias'],value['due'],phase,
                value['arrival'],value['destination'],submitted_at=value['submittedAt'])
            send_worker_message(channel,'api-result',{'alias':record['alias'],
                **{key:record.get(key) for key in ('jobId','approvedAt','frozen','processing','error')}})
    except BaseException as failure:
        error=diagnostic(failure);stop.set()
    finally:
        pool={}
        if replica is not None:
            try:
                if metrics.active['databaseConnections']:raise Incomplete('API database checkout remains active')
                replica.database_factory.close();pool=replica.database_factory.stats()
            except BaseException as failure:error=diagnostic(failure)
        summary={'pid':os.getpid(),'worker':worker_id,'status':'FAIL' if error else 'PASS',
            'cpuSeconds':time.process_time(),'counters':{},'poolStats':pool,
            'transportFence':{'unexpectedAttempts':getattr(sitecustomize,'_unexpected',None),
                'expectedSelfCheckDenials':getattr(sitecustomize,'_expected',None)},
            'metrics':worker_metric_payload(metrics),'error':error,'perProcessPeakConcurrency':dict(metrics.peak)}
        send_worker_message(channel,'summary',summary)
        channel.close();stack.close()


def process_worker(channel, stop, worker_id, policy, synthetic_vault_key, expected_database, deadline, pool_size=2):
    """Spawn target: constructs every application/DB object in this process."""
    signal.pthread_sigmask(signal.SIG_UNBLOCK, WORKER_SIGNALS)
    validate_fence(sys.platform, os.environ)
    import sitecustomize
    sitecustomize.self_check()
    metrics = Telemetry(capture_events=False)
    stack = ExitStack()
    replica, worker, watcher = None, None, None
    watcher_done = threading.Event()
    error = None
    try:
        if type(pool_size) is not int or pool_size not in (1,2):
            raise Incomplete('Unknown owned worker pool size')
        sys.path[:0] = [str(ROOT / 'src')]
        from postriff_phase2.hosted import HostedWorkspaceService
        from postriff_phase2.hosted_social import HostedSocial
        from postriff_phase2.hosted_worker import PostgresWorker
        from postriff_phase2.oauth import CredentialVault
        from postriff_phase2.social_connectors import DiscordProvider
        from postriff_phase2.postgres_pool import PooledPostgresFactory
        from unittest.mock import patch
        # Match the parent fixture's documented billing-only exclusion. All
        # tenant/RLS/approval/lease/credential/rate checks remain actual SQL.
        stack.enter_context(patch('postriff_phase2.billing.require_publishing', return_value=None))
        stack.enter_context(patch('postriff_phase2.billing.require_plan_capacity', return_value=None))
        class Replica:
            connection = Runtime.connection
            pool_statement = Runtime.pool_statement
        replica = Replica()
        replica.m = metrics
        replica.database_factory = PooledPostgresFactory(DSN, max_size=pool_size, max_waiting=8,
            options='-c statement_timeout=10000 -c lock_timeout=8000', observer=replica.pool_statement)
        with replica.connection() as db:
            row = db.execute("SELECT host(inet_server_addr()),inet_server_port(),current_database(),current_user,current_setting('data_directory'),current_setting('server_version_num')").fetchone()
            columns = db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0]
            database = {'host': row[0], 'port': row[1], 'name': row[2], 'user': row[3],
                        'directory': row[4], 'authColumns': columns, 'majorVersion': int(row[5])//10000}
            validate_fence(sys.platform, os.environ, database)
            if database != expected_database:
                raise Incomplete('Child database ownership differs from parent')
        transport = SpawnMockTransport(channel, metrics)
        provider = configure_candidate_provider(DiscordProvider(APP, 'synthetic-client-secret', 'synthetic-shared-bot',
            'https://rafii.example.invalid', transport=transport, production_reviewed=True), policy)
        def no_client_session(_token):
            raise Incomplete('Background replica cannot impersonate a client session')
        service = HostedWorkspaceService(replica.connection, no_client_session, clock=time.time,
            vault=CredentialVault(synthetic_vault_key), providers={'discord': provider},
            public_base_url='https://rafii.example.invalid')
        social = HostedSocial(service.oauth, {'discord': provider})
        observe_dispatch_preflight(social, metrics)
        worker = PostgresWorker(replica.connection, social, worker_id=worker_id, discord_workers=True)
        def watch_shutdown():
            while not watcher_done.wait(.05):
                if stop.is_set():
                    worker.request_shutdown()
                    return
        watcher = threading.Thread(target=watch_shutdown, name='owned-stop')
        watcher.start()
        send_worker_message(channel, 'ready', os.getpid())
        while not stop.is_set():
            if time.monotonic() >= deadline:
                raise Incomplete('Fixed owned worker deadline exceeded')
            send_worker_message(channel, 'step-start', None)
            try:
                with metrics.running('workerSteps'):
                    started = time.monotonic()
                    changed = worker.step(discord_only=True)
                    metrics.timing('workerStepSeconds', time.monotonic()-started)
                    if metrics.counters['unexpectedTransport']:
                        raise Incomplete('Child synthetic transport evidence failed')
            finally:
                send_worker_message(channel, 'step-finish', None)
            if not changed:stop.wait(.05)
    except BaseException as failure:
        error = diagnostic(failure)
        stop.set()
    finally:
        if worker is not None:worker.request_shutdown()
        watcher_done.set()
        if watcher is not None:watcher.join(timeout=1)
        pool = {}
        if replica is not None:
            try:
                if metrics.active['databaseConnections']:
                    raise Incomplete('Child database checkout remains active')
                replica.database_factory.close()
                pool = replica.database_factory.stats()
            except BaseException as failure:error = diagnostic(failure)
        fence = {'unexpectedAttempts': getattr(sitecustomize, '_unexpected', None),
                 'expectedSelfCheckDenials': getattr(sitecustomize, '_expected', None)}
        summary = {'pid': os.getpid(), 'worker': worker_id, 'status': 'FAIL' if error else 'PASS',
                   'cpuSeconds': time.process_time(), 'counters': dict(worker.discord_stats) if worker else {},
                   'poolStats': pool, 'transportFence': fence, 'metrics': worker_metric_payload(metrics),
                   'error': error, 'perProcessPeakConcurrency': dict(metrics.peak)}
        send_worker_message(channel, 'summary', summary)
        channel.close()
        stack.close()


def combined_transport_fence(runtime, parent_fence):
    children = runtime.child_fences if runtime is not None else []
    planned=planned_worker_groups(runtime.p) if runtime is not None else []
    expected=sum(replicas for _,replicas in planned)
    groups=runtime.worker_summaries if runtime is not None else []
    pool=validate_worker_budget(runtime.p) if planned else None
    identities=[(group.get('phase'),worker['pid']) for group in groups for worker in group.get('workers',[])]
    group_proofs=(len(groups)==len(planned) and all(
        group.get('phase')==phase and type(group.get('replicas')) is int and group['replicas']==replicas
        and group.get('status')=='PASS' and group.get('aggregateConnectionCap')==runtime.p.get('aggregateConnectionCap',20)
        and group.get('parentConnectionCap')==runtime.p.get('parentPoolSize',4) and group.get('perReplicaConnectionCap')==pool
        and len(group.get('workers',[]))==replicas
        for group,(phase,replicas) in zip(groups,planned)))
    parent_unexpected = getattr(parent_fence, '_unexpected', None)
    # A PID may be reused after a previous phase has reaped all its workers.
    # Phase/PID identities must be unique; simultaneous PIDs still cannot repeat.
    complete = (group_proofs and len(children)==expected and len(identities)==expected
        and all(type(pid) is int and pid>0 for _,pid in identities) and len(set(identities))==expected
        and set(identities)=={(row.get('phase'),row.get('pid')) for row in children}
        and all(type(row.get('unexpectedAttempts')) is int and row['unexpectedAttempts']==0
                and type(row.get('expectedSelfCheckDenials')) is int and row['expectedSelfCheckDenials']==4
                for row in children))
    return {'unexpectedAttempts': parent_unexpected + sum(row['unexpectedAttempts'] for row in children)
                if type(parent_unexpected) is int and complete else None,
            'expectedSelfCheckDenials': getattr(parent_fence, '_expected', None),
            'expectedReplicaProcesses': expected, 'observedReplicaProofs': len(children),
            'replicaProofsComplete': complete,
            'replicaExpectedSelfCheckDenials': sum(row['expectedSelfCheckDenials'] for row in children) if complete else None}


def combined_api_fence(runtime):
    expected=planned_api_groups(runtime.p)
    expected_count=sum(replicas for _,replicas in expected)
    groups=runtime.api_summaries;children=runtime.api_child_fences
    identities=[(g.get('phase'),w.get('pid')) for g in groups for w in g.get('workers',[])]
    complete=(bool(expected) and len(groups)==len(expected) and len(children)==expected_count
        and len(identities)==expected_count and len(set(identities))==expected_count
        and set(identities)=={(f.get('phase'),f.get('pid')) for f in children}
        and all(type(pid) is int and pid>0 for _,pid in identities)
        and all(g.get('phase')==phase and g.get('replicas')==replicas and g.get('status')=='PASS'
            and g.get('parentConnectionCap')==4 and g.get('aggregateConnectionCap')==32
            and g.get('perReplicaConnectionCap')==1 and len(g.get('workers',[]))==replicas
            and g.get('cleanup',{}).get('forcedCount')==0 and g['cleanup'].get('killCount')==0
            and g['cleanup'].get('survivingPids')==[] and g['cleanup'].get('unfinishedBrokers')==0
            and g['cleanup'].get('errors')==[]
            and all(w.get('status')=='PASS' and w.get('error') is None
                and w.get('poolStats',{}).get('closed') is True and w['poolStats'].get('maxConnections')==1
                and w.get('transportFence',{}).get('unexpectedAttempts')==0
                and w['transportFence'].get('expectedSelfCheckDenials')==4 for w in g['workers'])
            for g,(phase,replicas) in zip(groups,expected))
        and all(type(f.get('unexpectedAttempts')) is int and f['unexpectedAttempts']==0
            and type(f.get('expectedSelfCheckDenials')) is int and f['expectedSelfCheckDenials']==4 for f in children))
    return {'status':'PASS' if complete else 'FAIL','expectedApiProcesses':expected_count,'observedApiProofs':len(children),
        'proofsComplete':complete,'unexpectedAttempts':sum(f['unexpectedAttempts'] for f in children) if complete else None,
        'expectedSelfCheckDenials':expected_count*4 if complete else None,'aggregateConfiguredConnections':32,
        'roles':{'parent':4,'api':12,'worker':16}}


def close_pool(runtime, result):
    """After final SQL observations, before evidence output and runner teardown."""
    try:
        if runtime.m.active['databaseConnections']:
            raise Incomplete('Database connections remain checked out at pool shutdown')
        runtime.database_factory.close()
        result['databasePool'] = runtime.database_factory.stats()
        if not result['databasePool']['closed']:
            raise Incomplete('Database pool shutdown incomplete')
    except Exception as error:
        result.update(status='FAIL', poolCleanupError=diagnostic(error))


def build_tracked_fixture(runtime, index):
    runtime.fixture_ledger.begin(index)
    try:
        result = runtime.build_fixture(index)
    except BaseException as error:
        runtime.fixture_ledger.finish(index, 'cancelled' if isinstance(error, (FixtureCancelled, HarnessInterrupted)) else 'failed', error)
        raise
    runtime.fixture_ledger.finish(index, 'completed')
    return result


def collect_fixture_cohort(runtime, indices, *, stop_on_failure=True):
    """On fatal capacity failure cancel queued actors, then unwind active work."""
    pool = ThreadPoolExecutor(max_workers=runtime.p['producerConcurrency'])
    futures = {}
    try:
        for index in indices:
            futures[pool.submit(build_tracked_fixture, runtime, index)] = index
        for future in as_completed(futures):
            try:
                runtime.fixtures.append(future.result())
            except BaseException as error:
                actor_error = (future.done() and not future.cancelled()
                               and future.exception() is error)
                if stop_on_failure or not actor_error or not isinstance(error, Exception):
                    raise
                # Diagnostic actors are independent. Retain every outcome;
                # a main-thread deadline/cancellation must never be swallowed.
    except BaseException:
        runtime.fixture_abort.set()
        for pending, index in futures.items():
            if pending.cancel():
                runtime.fixture_ledger.finish(index, 'cancelled')
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=runtime.fixture_abort.is_set())
        if runtime.fixture_abort.is_set():
            runtime.fixture_ledger.cancel_queued()


def diagnostic_phase(runtime, name, indices, *, parallel):
    begun = time.monotonic()
    with runtime.m.lock:
        prior = runtime.m.counters.copy()
        positions = {k: len(v) for k, v in runtime.m.timings.items()}
    if parallel:
        collect_fixture_cohort(runtime, indices, stop_on_failure=False)
    else:
        for index in indices:
            if time.monotonic() >= runtime.setup_deadline:
                runtime.fixture_abort.set()
                break
            try:
                runtime.fixtures.append(build_tracked_fixture(runtime, index))
            except Exception:
                pass  # Outcome and sanitized context already recorded.
    with runtime.m.lock:
        delta = {k: v - prior[k] for k, v in runtime.m.counters.items() if v != prior[k]}
        latencies = {k: distribution(v[positions.get(k, 0):]) for k, v in runtime.m.timings.items()
                     if len(v) > positions.get(k, 0)}
    outcome = runtime.fixture_ledger.summary(indices)
    result = {'status': 'PASS' if outcome['complete'] else 'FAIL', 'accounting': outcome,
              'elapsedSeconds': time.monotonic() - begun, 'counters': delta, 'latencies': latencies,
              'concurrencyLimit': runtime.p['producerConcurrency'] if parallel else 1,
              'actualConnectionProducerPeak': runtime.m.peak['connectionProducers']}
    runtime.m.event('connection-diagnostic-phase', phase=name, status=result['status'], accounting=outcome)
    return result


def run_connection_diagnostic():
    validate_fence(sys.platform, os.environ)
    p = connection_diagnostic_profile()
    result = {'status': 'NOT_RUN', 'execution': 'disposable-cloud-postgres-mocked-discord',
              'purpose': p['purpose'], 'profile': p, 'profileSha256': fingerprint(p), 'phases': {},
              'capacityStageA': 'NOT_RUN', 'capacityStageB': 'NOT_RUN',
              'realDiscordAcceptance': 'NOT_RUN', 'productionReady': 'NO',
              'plannedPublicationRequests': 0,
              'fixedCapacityProfileSha256': {s: fingerprint(profile(s)) for s in ('a', 'b')},
              'cost': {'actualCost': 'UNKNOWN', 'comparisonBaseline': None, 'savings': 'UNKNOWN'}}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    metrics, runtime = None, None
    started = time.monotonic()
    try:
        import sitecustomize
        sitecustomize.self_check()
        from unittest.mock import patch
        metrics = Telemetry()
        runtime = Runtime(p, metrics)
        runtime.setup_deadline = runtime.started + p['setupDeadlineSeconds']
        result['sourceSha256'] = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in (
            'src/postriff_phase2/discord/rate_limits.py', 'src/postriff_phase2/oauth.py',
            'migrations/postriff/124_discord_rate_limits.sql', 'tests/phase2/postgres_discord_capacity.py')}
        # Match the existing capacity exclusion of billing/generation only.
        # Real tenant checks, OAuth/grants, RLS and coordinator SQL remain live.
        with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
            result['phases']['serial'] = diagnostic_phase(runtime, 'serial', range(16), parallel=False)
            result['phases']['parallel'] = diagnostic_phase(runtime, 'parallel', range(16, 32), parallel=True)
        runtime.fixtures.sort(key=lambda f: f['index'])
        if runtime.fixture_ledger.summary()['complete']:
            result['observedFixtureGeometry'] = runtime.fixture_counts()
        result['status'] = 'PASS' if (all(v['status'] == 'PASS' for v in result['phases'].values())
            and not any(v for k, v in metrics.counters.items() if k.startswith('sqlErrors.'))
            and not metrics.counters['diagnosticPublishDenied'] and metrics.samples) else 'FAIL'
    except BaseException as error:
        result.update(status='FAIL', error=diagnostic(error))
        if runtime:
            runtime.fixture_abort.set()
    finally:
        if runtime:
            runtime.fixture_ledger.cancel_queued()
            result['fixtureAccounting'] = runtime.fixture_ledger.summary()
            try:
                # Aggregate only the owned synthetic coordinator; no tokens,
                # workspace/customer IDs, request paths or raw rows emitted.
                with runtime.connection() as db:
                    rows = db.execute('''SELECT state,count(*),min(extract(epoch FROM expires_at-reserved_at)),
                        max(extract(epoch FROM expires_at-reserved_at)) FROM public.pr_discord_request_admissions
                        GROUP BY state ORDER BY state''').fetchall()
                    result['admissionLifetimeByState'] = [
                        {'state': row[0], 'count': row[1], 'minSeconds': float(row[2]), 'maxSeconds': float(row[3])}
                        for row in rows]
            except Exception as error:
                result.update(status='FAIL', aggregateObservationError=diagnostic(error))
            try:
                runtime.close()
            except Exception as error:
                result.update(status='FAIL', cleanupError=diagnostic(error))
            result['publicationRequests'] = len(runtime.wire.attempts)
            result['createdMessages'] = len(runtime.wire.creates)
            if result['publicationRequests'] or result['createdMessages']:
                result['status'] = 'FAIL'
        for required in ('serial', 'parallel'):
            result['phases'].setdefault(required, {'status': 'NOT_RUN', 'reason': 'Prior failure or deadline'})
        if runtime:
            close_pool(runtime, result)
        if metrics:
            fence = sys.modules.get('sitecustomize')
            result['transportFence'] = combined_transport_fence(runtime, fence)
            if result['transportFence']['unexpectedAttempts'] != 0:
                result['status'] = 'FAIL'
            result['metrics'] = metrics.summary()
            metrics.events.close()
            result['eventsSha256'] = hashlib.sha256(EVENTS.read_bytes()).hexdigest()
        result['elapsedSeconds'] = time.monotonic() - started
        RESULT.write_text(json.dumps(result, indent=2) + '\n')
        print('RAFII_DISCORD_CAPACITY_RESULT ' + canonical({'status': result['status'],
            'stage': 'connection-diagnostic', 'profileSha256': result['profileSha256'],
            'resultFile': str(RESULT.relative_to(ROOT)), 'elapsedSeconds': result['elapsedSeconds'],
            'capacityAcceptance': 'NOT_RUN', 'productionReady': 'NO'}), flush=True)
    return 0 if result['status'] == 'PASS' else 1


def run_admission_diagnostic(api=False):
    """Measure the observed approval bottleneck, never qualify full A/B."""
    validate_fence(sys.platform,os.environ)
    p=admission_diagnostic_profile(api)
    planned_jobs=p['burstJobs']+p.get('apiSmokeJobs',0)
    result={'status':'NOT_RUN','execution':'disposable-cloud-postgres-mocked-discord',
        'profile':p,'profileSha256':fingerprint(p),'phases':{},'plannedJobRequests':planned_jobs,
        'capacityAcceptance':'NOT_RUN','fullSafetyAcceptance':'NOT_RUN',
        'realDiscordAcceptance':'NOT_RUN','productionReady':'NO','diagnosticOnly':True,
        'cost':{'actualCost':'UNKNOWN','comparisonBaseline':None,'savings':'UNKNOWN'}}
    RESULT.parent.mkdir(parents=True,exist_ok=True)
    metrics,runtime=None,None
    started=time.monotonic()
    try:
        import sitecustomize
        sitecustomize.self_check()
        from unittest.mock import patch
        metrics=Telemetry()
        runtime=Runtime(p,metrics)
        critical=runpy.run_path(str(ROOT/'scripts/discord_capacity_sources.py'))['source_paths'](ROOT)
        result['sourceSha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in critical}
        with patch('postriff_phase2.billing.require_publishing',return_value=None),patch('postriff_phase2.billing.require_plan_capacity',return_value=None):
            setup_started=time.monotonic()
            runtime.setup_deadline=setup_started+p['setupDeadlineSeconds']
            runtime.fixtures.append(build_tracked_fixture(runtime,0))
            collect_fixture_cohort(runtime,range(1,p['users']))
            runtime.setup_deadline=None
            runtime.fixtures.sort(key=lambda f:f['index'])
            result['phases']['fixture']={'status':'PASS','observed':runtime.fixture_counts(),
                'setupSeconds':time.monotonic()-setup_started,'logicalOutcomeAccounting':runtime.fixture_ledger.summary()}
            if api:
                runtime.progress_phase=metrics.phase='admission-smoke'
                smoke=runtime.burst(p['referenceReplicas'],'admission-smoke',p['apiSmokeJobs'],comparison=True)
                result['phases']['admission-smoke']=smoke
                if smoke['status']!='PASS':raise Incomplete('API process smoke failed; full diagnostic not started')
            runtime.progress_phase=metrics.phase='admission-burst'
            burst=runtime.burst(p['referenceReplicas'],'admission-burst',p['burstJobs'])
            result['phases']['admission-burst']=burst
            records=[r for r in metrics.records.values() if r['phase']=='admission-burst']
            result['minimumObservedApprovalMarginSeconds']=admission_margin(records,p['burstJobs'])
            result['approvalMarginGate']=(result['minimumObservedApprovalMarginSeconds'] is not None
                and result['minimumObservedApprovalMarginSeconds']>=p['minimumApprovalMarginSeconds'])
            result['status']='PASS' if burst['status']=='PASS' and result['approvalMarginGate'] else 'FAIL'
    except BaseException as error:
        result.update(status='FAIL',error=diagnostic(error))
    finally:
        if runtime:
            runtime.progress_phase='cleanup'
            runtime.fixture_ledger.cancel_queued()
            result['fixtureAccounting']=runtime.fixture_ledger.summary()
            try:runtime.close()
            except Exception as error:result.update(status='FAIL',cleanupError=diagnostic(error))
            # Full negative/safety coverage is deliberately NOT_RUN. Preserve
            # independently observed delivery counters without claiming it ran.
            safety=runtime.final_safety()
            keys=('unsafeCreates','unsafeCreateAttempts','duplicateCreates','repeatPostAttempts',
                'acceptedClaimCollisions','unexpectedTransport','workerShutdownUnfinished',
                'sharedCreateLimitBypass','sharedRequestLimitBypass')
            result['deliverySafetyCounters']={key:safety[key] for key in keys}
            result['workers']=runtime.worker_summaries
            if api:
                result['apiWorkers']=runtime.api_summaries
                result['apiTransportFence']=combined_api_fence(runtime)
                if result['apiTransportFence']['status']!='PASS':result['status']='FAIL'
            records=list(metrics.records.values())
            try:states=list(runtime.job_states(records).values())
            except Exception:
                states=[]
                metrics.count('finalJobReadErrors')
            result['totalJobAccounting']=accounting(len(records),sum(bool(r['jobId']) for r in records),states)
            if (len(records)!=planned_jobs or not result['totalJobAccounting']['complete']
                    or any(result['deliverySafetyCounters'].values())
                    or not result['fixtureAccounting']['complete']):result['status']='FAIL'
        for required in (('fixture','admission-smoke','admission-burst') if api else ('fixture','admission-burst')):
            if required not in result['phases']:
                result['phases'][required]={'status':'NOT_RUN','reason':'Prior failure; diagnostic incomplete'}
                result['status']='FAIL'
        if runtime:close_pool(runtime,result)
        if metrics:
            result['transportFence']=combined_transport_fence(runtime,sys.modules.get('sitecustomize'))
            if result['transportFence']['unexpectedAttempts']!=0 or not metrics.samples:
                result['status']='FAIL'
            result['metrics']=metrics.summary()
            metrics.events.close()
            result['eventsSha256']=hashlib.sha256(EVENTS.read_bytes()).hexdigest()
        result['elapsedSeconds']=time.monotonic()-started
        result['cost']['computeTimingProxyUsd']=result['elapsedSeconds']*p['computeUsdPerSecond']
        RESULT.write_text(json.dumps(result,indent=2)+'\n')
        print('RAFII_DISCORD_CAPACITY_RESULT '+canonical({'status':result['status'],
            'stage':p['stage'],'profileSha256':result['profileSha256'],
            'elapsedSeconds':result['elapsedSeconds'],'capacityAcceptance':'NOT_RUN',
            'fullSafetyAcceptance':'NOT_RUN','productionReady':'NO'}),flush=True)
    return 0 if result['status']=='PASS' else 1


def run(stage):
    if stage == 'connection-diagnostic':
        return run_connection_diagnostic()
    if stage == 'admission-diagnostic':
        return run_admission_diagnostic()
    if stage == 'admission-api-diagnostic':
        return run_admission_diagnostic(api=True)
    validate_fence(sys.platform, os.environ)  # Refuse before any output/fixture creation.
    p = selected_profile(stage)
    result = {'status': 'NOT_RUN', 'execution': 'disposable-cloud-postgres-mocked-discord',
              'profile': p, 'profileSha256': fingerprint(p), 'phases': {},
              'budgetPreflight': budget_lower_bound(p),
              'capacityAcceptance':'NOT_RUN' if stage in ('pipeline-qualification','burst-diagnostic','dispatch-diagnostic') else 'full fixed profile',
              'realDiscordAcceptance': 'NOT_RUN', 'productionReady': 'NO',
              'cost': {'actualCost': 'UNKNOWN', 'comparisonBaseline': None, 'savings': 'UNKNOWN'}}
    result['plannedJobRequests'] = p['comparisonJobsEach'] * len(p['comparisonReplicas']) + p['burstJobs'] + len(arrivals(p)) + p['plannedSafetyJobRequests']
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    metrics, runtime = None, None
    started = time.monotonic()
    try:
        validate_fence(sys.platform, os.environ)
        if result['budgetPreflight']['status'] == 'BLOCKED':
            result['status'] = 'BLOCKED'
            raise Incomplete('Full fixed profile cannot fit; separate phase/resource plan required before StageB')
        import sitecustomize
        sitecustomize.self_check()
        from unittest.mock import patch
        metrics = Telemetry()
        runtime = Runtime(p, metrics)
        critical = runpy.run_path(str(ROOT/'scripts/discord_capacity_sources.py'))['source_paths'](ROOT)
        result['sourceSha256'] = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in critical}
        # Billing/generation are explicitly excluded, never mocked tenant/RLS/
        # approval/claims/leases/credentials/rate SQL or provider-send guards.
        with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
            setup_started = time.monotonic()
            runtime.setup_deadline = setup_started + p['setupDeadlineSeconds']
            runtime.fixtures.append(build_tracked_fixture(runtime, 0))  # Warm actual APIs once.
            collect_fixture_cohort(runtime, range(1, p['users']))
            runtime.setup_deadline = None
            runtime.fixtures.sort(key=lambda f: f['index'])
            result['phases']['fixture'] = {'status': 'PASS', 'observed': runtime.fixture_counts(),
                'setupSeconds': time.monotonic() - setup_started, 'logicalConnections': p['users'],
                'actualProducerConcurrency': metrics.peak['connectionProducers'],
                'browserConcurrencyClaim': False}
            if p.get('forceExpiredIdentityBeforeDispatch'):
                # Diagnostic fixtures only, in the already fenced disposable DB.
                # Keep application/database clocks, consent generations, grants,
                # permissions and all publication timing/authorization unchanged.
                with runtime.connection() as db:
                    for f in runtime.fixtures:
                        db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=clock_timestamp()-interval '1 second' WHERE workspace_id=%s AND connection_id=%s",
                                   (f['workspace'], f['identity']))
                        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',
                                           (f['workspace'],)).fetchone()[0]
                        for channel in state['phase2']['channels']:
                            channel['verifiedAt'] = time.time() - 7200
                        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                                   (canonical(state), f['workspace']))
                result['diagnosticFixtureChange'] = '32 linked identity expiries and installation observation ages only; no consent/destination/content/clock or capacity-target changes'
            for replicas in p['comparisonReplicas']:
                name = 'comparison-' + str(replicas)
                runtime.progress_phase=metrics.phase=name
                result['phases'][name] = runtime.burst(replicas, name, p['comparisonJobsEach'], comparison=True)
            runtime.progress_phase=metrics.phase='burst'
            result['phases']['burst'] = runtime.burst(p['referenceReplicas'], 'burst', p['burstJobs'])
            runtime.progress_phase=metrics.phase='sustained'
            result['phases']['sustained'] = runtime.sustained()
            runtime.progress_phase=metrics.phase='safety'
            result['phases']['safety'] = runtime.safety()
        if (not metrics.samples or not any(s['workerProcessRssBytes'] is not None and s['databaseRssBytes'] is not None for s in metrics.samples)
                or metrics.counters['finalJobReadErrors'] or metrics.counters['unexpectedTransport']):
            raise Incomplete('Required observation or provider fence is incomplete')
        result['status'] = 'PASS' if all(v['status'] == 'PASS' for v in result['phases'].values()) else 'FAIL'
    except BaseException as error:
        result.update(status='BLOCKED' if result['budgetPreflight']['status'] == 'BLOCKED' else 'FAIL', error={**diagnostic(error),
            'reason': str(error) if isinstance(error, Incomplete) else 'Harness or concrete assertion failure; inspect sanitized case events'})
    finally:
        if runtime:
            runtime.progress_phase='cleanup'
            runtime.fixture_ledger.cancel_queued()
            result['fixtureAccounting'] = runtime.fixture_ledger.summary()
            try:
                runtime.close()
            except Exception as error:
                result.update(status='FAIL', cleanupError=type(error).__name__)
            result['safetyAccounting'] = runtime.final_safety()
            result['workers'] = runtime.worker_summaries
            if p.get('apiReplicas'):
                result['apiWorkers']=runtime.api_summaries
                result['apiTransportFence']=combined_api_fence(runtime)
                if result['apiTransportFence']['status']!='PASS':result['status']='FAIL'
            result['selectorPlans'] = runtime.selector_plans
            if result['safetyAccounting']['status'] != 'PASS':
                result['status'] = 'FAIL'
            all_records = list(metrics.records.values())
            try:
                states = list(runtime.job_states(all_records).values())
            except Exception:
                states = []
                metrics.count('finalJobReadErrors')
            result['totalJobAccounting'] = accounting(len(all_records), sum(bool(r['jobId']) for r in all_records), states)
            result['logicalWorkloadAccounting'] = {'planned': result['plannedJobRequests'],
                'requested': len(all_records), 'notRequestedDueFailure': max(0, result['plannedJobRequests'] - len(all_records)),
                'complete': len(all_records) == result['plannedJobRequests']}
            if not result['totalJobAccounting']['complete']:
                result['status'] = 'FAIL'
            if not result['logicalWorkloadAccounting']['complete']:
                result['status'] = 'FAIL'
        for required in ('fixture', 'comparison-1', 'comparison-4', 'burst', 'sustained', 'safety'):
            result['phases'].setdefault(required, {'status': 'NOT_RUN', 'reason': 'Prior failure/deadline; cannot waive this required gate'})
        if runtime:
            close_pool(runtime, result)
        if metrics:
            fence = sys.modules.get('sitecustomize')
            result['transportFence'] = combined_transport_fence(runtime, fence)
            if result['transportFence']['unexpectedAttempts'] != 0:
                result['status'] = 'FAIL' if result['status'] != 'BLOCKED' else 'BLOCKED'
            result['metrics'] = metrics.summary()
            metrics.events.close()
            result['eventsSha256'] = hashlib.sha256(EVENTS.read_bytes()).hexdigest()
        result['elapsedSeconds'] = time.monotonic() - started
        result['cost']['computeTimingProxyUsd'] = result['elapsedSeconds'] * p.get('computeUsdPerSecond',.0004)
        result['cost']['proxyBasis'] = ('Declared runner public compute rate $'+str(p.get('computeUsdPerSecond',.0004))+'/s; harness time only, not invoice or total billable duration')
        RESULT.write_text(json.dumps(result, indent=2) + '\n')
        print('RAFII_DISCORD_CAPACITY_RESULT ' + canonical({'status': result['status'], 'stage': stage,
              'profileSha256': result['profileSha256'], 'resultFile': str(RESULT.relative_to(ROOT)),
              'elapsedSeconds': result['elapsedSeconds'], 'productionReady': 'NO'}), flush=True)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    def terminate(signum, _frame):
        raise HarnessInterrupted('Harness deadline or cancellation: ' + str(signum))
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGALRM, terminate)
    stage=os.environ.get('RAFII_DISCORD_CAPACITY_STAGE','')
    signal.alarm(480 if stage=='connection-diagnostic' else
        admission_diagnostic_profile(api=stage=='admission-api-diagnostic')['totalHarnessDeadlineSeconds'] if stage in ('admission-diagnostic','admission-api-diagnostic') else
        selected_profile(stage)['totalHarnessDeadlineSeconds'])
    sys.exit(run(os.environ.get('RAFII_DISCORD_CAPACITY_STAGE', '')))
