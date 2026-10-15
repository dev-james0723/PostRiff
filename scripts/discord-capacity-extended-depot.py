"""Local control plane for the predeclared extended B cloud job.

JCB's standard job timeout is45minutes; the unshortened B workload cannot fit.
Reuse JCB's secret-filtered snapshot and native Depot CI transport with a
reviewable repository-only225minute workflow. Never performs local tests/SQL.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
if ROOT.parent.name!='.worktrees' or ROOT.name!='rafii-discord-release-20261015':
    raise SystemExit('Use the reviewed isolated Discord release worktree.')
EVIDENCE=ROOT.parents[1]/'docs/discord-integration-20261012/implementation'
STATE=EVIDENCE/'p8-stage-b-extended-submission-state.json'
LOCK=EVIDENCE/'p8-stage-b-extended-submission.lock'
WORKFLOW=Path('.depot/workflows/discord-capacity-stage-b-workers16-v3.yml')
STAGE_A='9969648414b93a5c057a19772c358bf1869ffdb0cb32d500acf5804b335463da'
STAGE_B='e932a215a3f3226905988b4370feafe30dc2ce9e9199963e659d757081d45637'
PIPELINE='bf1859ec092392dcdb08a6ee8d1d786db1ccaaf6094a4405548edf07ffda9e2c'
ORG='jf34f85hr0'
RESOURCE_PLANS={
    'workers16-v3':{'workflow':WORKFLOW,'stageA':STAGE_A,'stageB':STAGE_B,'pipeline':PIPELINE,
        'planFile':'P8-STAGE-B-RESOURCE-PLAN-WORKERS16-V3.json','flag':'--stage-b-workers16-v3',
        'workflowName':'Rafii Discord Stage B workers16 v3'},
    'workers16-parent16-v4':{'workflow':Path('.depot/workflows/discord-capacity-stage-b-workers16-parent16-v4.yml'),
        'stageA':'f92b46b3039d8022abe3596c93867b06e42973f6c8ed8e3fd8d3115a22f4495e',
        'stageB':'5b5a5d0d6ef54e1d0f4ad771b26d57f29009e0379660fe0c58e99e1a93ab7575',
        'pipeline':'c77a644efe881ef8a0d2aaf192cd7f6157b18cae5f074fbf50b4bc26ee776c05',
        'planFile':'P8-STAGE-B-RESOURCE-PLAN-PARENT16-V4.json','flag':'--stage-b-workers16-parent16-v4',
        'workflowName':'Rafii Discord Stage B workers16 parent16 v4'},
}


def stream_failure_kind(controller_log):
    if type(controller_log) is not bytes:return None
    for line in controller_log.decode('utf-8').splitlines():
        if line.startswith('failed to stream logs: invalid_argument: protocol error: incomplete envelope: http2: server sent GOAWAY'):
            return 'http2_log_stream_goaway'
        if re.fullmatch(r'failed to stream logs: invalid_argument: protocol error: incomplete envelope: read tcp [0-9a-fA-F.:\[\]]+->[0-9a-fA-F.:\[\]]+: read: operation timed out',line):
            return 'http2_log_stream_read_timeout'
    return None


def completed_follower_retirement(controller, controller_log):
    """Classify a stopped viewer only; caller must prove native success first."""
    return (type(controller_log) is bytes
        and type(controller.get('exitCode')) is int and controller['exitCode']==-15
        and type(controller.get('submissionExitCode')) is int and controller['submissionExitCode']==-15
        and controller.get('remoteExitCode') is None
        and b'Waiting for logs from job "test" (status: finished)...' in controller_log.splitlines())


def completed_native_prerequisite(run, receipt, controller, status, metrics, controller_log):
    """Positive native completion, including one known post-submit stream fault.

    Never turns a failed/pending test into success or rewrites controller exits.
    Profile, artifact, accounting and frozen-source gates remain in qualified().
    """
    try:
        if (type(controller_log) is not bytes or receipt['status']!='PASS' or receipt['native']!='finished' or receipt['capacityCriticalHashesMatch'] is not True
                or receipt['runId']!=run or controller['runId']!=run or controller['orgId']!=ORG
                or status['run_id']!=run or status['org_id']!=ORG or status['status']!='finished'
                or metrics['run']['run_id']!=run or metrics['run']['status']!='finished'
                or len(status['workflows'])!=1 or len(metrics['workflows'])!=1):return False
        workflow=status['workflows'][0];measured=metrics['workflows'][0]
        if (workflow['status']!='finished' or measured['workflow']['status']!='finished'
                or workflow['workflow_id']!=measured['workflow']['workflow_id']
                or len(workflow['jobs'])!=1 or len(measured['jobs'])!=1):return False
        job=workflow['jobs'][0];sample=measured['jobs'][0]
        last=max(job['attempts'],key=lambda row:row['attempt'])
        observed=max(sample['attempts'],key=lambda row:row['attempt']['attempt'])['attempt']
        if (job['job_key'].split(':',1)[-1]!='test' or job['job_id']!=sample['job']['job_id']
                or job['status']!='finished' or sample['job']['status']!='finished'
                or sample['job']['conclusion']!='success' or last['status']!='finished'
                or last['attempt_id']!=observed['attempt_id'] or last['attempt']!=observed['attempt']
                or observed['status']!='finished' or observed['conclusion']!='success'
                or receipt['nativeJobConclusion']!='success' or receipt['nativeAttemptConclusion']!='success'
                or type(receipt['nativeRemoteExitCode']) is not int or receipt['nativeRemoteExitCode']!=0):return False
        for key in ('sourceHead','sourceFingerprint','includedFileCount'):
            value=receipt['sourceProof'][key]
            if value is None or value!=controller['snapshot'][key] or value!=controller['transport']['remoteSource'][key]:return False
        code=controller['exitCode']
        if type(code) is not int or type(receipt['controllerExit']) is not int or receipt['controllerExit']!=code:return False
        if code==0:return type(controller.get('remoteExitCode')) is int and controller['remoteExitCode']==0
        if code==-15:
            # Retiring a reader of a completed native job is not a failed test.
            # Keep that exit visible; all positive native/source checks above
            # and full artifact/profile/source gates in qualified still apply.
            return (completed_follower_retirement(controller,controller_log)
                and receipt.get('controllerTransportFailure')=='completed_log_follower_terminated'
                and receipt.get('controllerLogSha256')==hashlib.sha256(controller_log).hexdigest())
        failure=stream_failure_kind(controller_log)
        return (code==1 and type(controller.get('submissionExitCode')) is int and controller['submissionExitCode']==1 and controller.get('remoteExitCode') is None
                and failure is not None and receipt.get('controllerTransportFailure')==failure
                and receipt.get('controllerLogSha256')==hashlib.sha256(controller_log).hexdigest())
    except (KeyError,TypeError,ValueError,AttributeError):
        return False


def qualified(path, stage, users, profile, frozen_root):
    match=re.fullmatch(r'p8-([a-z0-9]+)-discord-capacity-results.json',path.name)
    if path.resolve().parent!=EVIDENCE.resolve() or not match:
        raise SystemExit('Use recovered native capacity evidence from this mission.')
    reconciliation=EVIDENCE/('p8-'+match[1]+'-reconciliation.json')
    receipt=json.loads(reconciliation.read_text())
    raw=path.read_bytes()
    actual_sha=hashlib.sha256(raw).hexdigest()
    controller=json.loads(Path(receipt['receipt']).read_text())
    status=json.loads((EVIDENCE/('p8-'+match[1]+'-status.json')).read_text())
    metrics=json.loads((EVIDENCE/('p8-'+match[1]+'-metrics.json')).read_text())
    log_path=EVIDENCE/receipt['controllerLog']
    if log_path.resolve().parent!=EVIDENCE.resolve():
        raise SystemExit('Controller log must stay in this mission evidence directory.')
    if (receipt.get('runId')!=match[1] or receipt.get('status')!='PASS'
            or receipt.get('native')!='finished'
            or not completed_native_prerequisite(match[1],receipt,controller,status,metrics,log_path.read_bytes())
            or receipt.get('capacityCriticalHashesMatch') is not True
            or receipt.get('artifactSha256',{}).get('discord-capacity-results.json')!=actual_sha):
        raise SystemExit('Native recovered PASS/source/artifact reconciliation is required.')
    result=json.loads(raw)
    if (result.get('status')!='PASS' or result.get('profile',{}).get('stage')!=stage
            or result['profile'].get('users')!=users
            or result.get('profileSha256')!=profile
            or not result.get('totalJobAccounting',{}).get('complete')
            or not result.get('logicalWorkloadAccounting',{}).get('complete')
            or result.get('safetyAccounting',{}).get('status')!='PASS'
            or any(p.get('status')!='PASS' for p in result.get('phases',{}).values())):
        raise SystemExit('Actual complete '+stage+' PASS evidence is required before extended B.')
    actual_profile=hashlib.sha256(json.dumps(result['profile'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    phases=result['phases'];fixture=result.get('fixtureAccounting',{});observed=phases.get('fixture',{}).get('observed',{})
    expected_jobs=3217 if stage=='a' else 47
    if (actual_profile!=result.get('profileSha256')
            or set(phases)!={'fixture','comparison-1','comparison-4','burst','sustained','safety'}
            or not fixture.get('complete') or fixture.get('completed')!=users
            or fixture.get('failed')!=0 or fixture.get('cancelled')!=0
            or observed.get('users')!=users or observed.get('destinations')!=users*6
            or result.get('plannedJobRequests')!=expected_jobs
            or result['logicalWorkloadAccounting'].get('requested')!=expected_jobs
            or result['totalJobAccounting'].get('observed')!=expected_jobs
            or not result.get('sourceSha256')):
        raise SystemExit('Incomplete or inconsistent '+stage+' fixture/workload/source evidence.')
    safety=result['safetyAccounting']
    if any(safety.get(k)!=0 for k in ('unsafeCreates','duplicateCreates','acceptedClaimCollisions','unexpectedTransport')):
        raise SystemExit('Unsafe or missing prior evidence cannot authorize a B workload.')
    expected_paths=runpy.run_path(str(frozen_root/'scripts/discord_capacity_sources.py'))['source_paths'](frozen_root)
    if set(result['sourceSha256'])!=set(expected_paths):
        raise SystemExit('Prior qualification must cover the complete reviewed source manifest.')
    for name in expected_paths:
        expected=result['sourceSha256'][name]
        source=(frozen_root/name).resolve()
        if not source.is_relative_to(frozen_root.resolve()) or not source.is_file():
            raise SystemExit('Qualification source escaped the frozen snapshot.')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise SystemExit('Prior qualification source changed: '+name)
    return {'file':str(path),'sha256':actual_sha,
            'profileSha256':result['profileSha256']}


def write_record(path, value):
    temporary=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    with temporary.open('w') as output:
        output.write(json.dumps(value,indent=2)+'\n');output.flush();os.fsync(output.fileno())
    os.replace(temporary,path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


@contextmanager
def submission_lock():
    with LOCK.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another StageB controller owns the mission submission lock.')
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def reconcile(args):
    if not STATE.exists():raise SystemExit('No canonical StageB submission exists to reconcile.')
    record=json.loads(STATE.read_text())
    if record.get('journal')!=str(args.journal.resolve()):
        raise SystemExit('Reconcile the actual canonical attempt journal, never a substitute.')
    run=record.get('runId')
    if not run:raise SystemExit('Submission outcome lacks a run ID; reconcile native evidence before any retry.')
    response=subprocess.run(['depot','ci','status',run,'--org',ORG,'--output','json'],
        text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    if response.returncode:raise SystemExit('Native status is unavailable; canonical attempt remains blocked.')
    native=json.loads(response.stdout)
    if native.get('run_id')!=run or native.get('org_id')!=ORG:
        raise SystemExit('Native reconciliation identity mismatch.')
    write_record(args.journal.with_suffix('.native-status.json'),native)
    status=native.get('status')
    jobs=[j for w in native.get('workflows',[]) for j in w.get('jobs',[])]
    terminal=('failed','finished','cancelled','canceled','skipped')
    fully_terminal=bool(jobs) and all(j.get('status') in terminal and
        (j.get('status')=='skipped' or isinstance(j.get('attempts'),list) and bool(j['attempts']) and
         all(a.get('status') in terminal and isinstance(a.get('attempt_id'),str) and a['attempt_id']
             for a in j['attempts'])) for j in jobs)
    if status in ('failed','cancelled','canceled') and fully_terminal:
        record['status']='NATIVE_FAILED'
    elif status=='finished':
        # Native success alone does not establish capacity acceptance. Keep the
        # mission blocked against an unnecessary second paid B submission.
        record['status']='NATIVE_FINISHED_REQUIRES_CAPACITY_EVIDENCE'
    record.update(nativeStatus=status,reconciledAt=datetime.now(timezone.utc).isoformat())
    write_record(args.journal,record);write_record(STATE,record)
    print(json.dumps({'status':record['status'],'runId':run,'nativeStatus':status}))
    return 0


def runner_local_capacity_cache(workflow):
    """Optional durable-cache services cannot gate this Python-only workload."""
    cache_steps = ['Mount durable package cache', 'Mount durable Next.js cache',
                   'Connect framework cache', 'Observe cache before', 'Observe cache after']
    remaining, removed, skipping = [], [], False
    for line in workflow.splitlines(keepends=True):
        if line.startswith('      - '):
            name = line[len('      - name: '):].strip() if line.startswith('      - name: ') else None
            skipping = name in cache_steps
            if skipping:
                removed.append(name)
        if not skipping:
            remaining.append(line)
    if removed != cache_steps:
        raise SystemExit('Unexpected optional-cache workflow shape.')
    result = ''.join(remaining)
    original = '      NPM_CONFIG_CACHE: "/mnt/jcb-package-cache"\n'
    install = '      - name: Frozen dependency install\n'
    if result.count(original) != 1 or result.count(install) != 1:
        raise SystemExit('Unexpected runner-local cache configuration.')
    result = result.replace(original, '      NPM_CONFIG_CACHE: "${{ runner.temp }}/rafii-discord-b-npm"\n')
    result = result.replace(install, '      - name: Prepare runner-local package cache\n'
        '        run: install -d -m 700 "$NPM_CONFIG_CACHE"\n' + install)
    if 'depot/cache-mount@' in result or '/mnt/jcb-' in result:
        raise SystemExit('Unexpected durable-cache dependency remains.')
    return result


def setup(plan_name='workers16-v3'):
    plan=RESOURCE_PLANS[plan_name]
    sys.path.insert(0,str(Path.home()/'Documents/James-Cloud-Build/scripts'))
    import jcb
    cfg=jcb.detect(ROOT,json.loads((ROOT/'.james-cloud-build.json').read_text()),task='test')
    if (cfg.get('envAllowlist') or cfg.get('localFallback') is not False
            or cfg.get('transportMode')!='remote_patch'):
        raise SystemExit('Reviewed secret-free cloud-only JCB transport is required.')
    if (ROOT/jcb.WORKFLOW).read_text()!=jcb.workflow(cfg):
        raise SystemExit('Standard JCB workflow/config drift; reconcile before submission.')
    cfg['tasks']={'test':'test:discord:capacity:jcb'}
    cfg['taskArgs']={'test':[plan['flag']]}
    cfg['runner']={'validation':'depot-ubuntu-24.04-32','build':'depot-ubuntu-24.04-32'}
    cfg['cacheScope']='rafii-discord-release-20261015-stage-b-'+plan_name
    workflow=jcb.workflow(cfg)
    if workflow.count('    timeout-minutes: 45')!=1:
        raise SystemExit('Unexpected extended workflow shape.')
    workflow=workflow.replace('name: James Cloud Build','name: '+plan['workflowName'])
    workflow=workflow.replace('    timeout-minutes: 45','    timeout-minutes: 225')
    if plan_name=='workers16-parent16-v4':
        workflow=runner_local_capacity_cache(workflow)
    return jcb,cfg,workflow


def materialize_qualification_sources(snapshot, jcb):
    """Materialize only regular source blobs from the frozen sparse Git index.

    JCB leaves unchanged public base files absent with skip-worktree. Never
    substitute mutable source-worktree bytes, restore deletions or fetch media.
    """
    def git_bytes(*arguments, data=None):
        return subprocess.run(['git','-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false',*arguments],
            cwd=snapshot.path,env=jcb.clean_env(),input=data,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,check=True,timeout=20).stdout
    entries={}
    for entry in git_bytes('ls-files','--stage','-z').split(b'\0'):
        if not entry:continue
        metadata,name=entry.split(b'\t',1);mode,_oid,stage=metadata.decode().split()
        if stage!='0':raise SystemExit('Unmerged frozen index cannot qualify capacity.')
        entries[name.decode()]=mode
    deleted={n.decode() for n in git_bytes('ls-files','--deleted','-z').split(b'\0') if n}
    wanted={name for name in entries if (name.startswith('src/') and name.endswith('.py')
        or name.startswith('migrations/postriff/') and name.endswith('.sql')) and name not in deleted}
    contract=snapshot.path/'scripts/discord_capacity_sources.py'
    if not contract.is_file():raise SystemExit('Frozen source-coverage contract must be materialized.')
    wanted.update(runpy.run_path(str(contract))['source_paths'](snapshot.path))
    missing=[]
    for name in sorted(wanted):
        source=snapshot.path/name
        if name in deleted or entries.get(name) not in ('100644','100755'):
            raise SystemExit('Missing/deleted/nonregular qualification source: '+name)
        if not source.exists():missing.append(name)
    if missing:
        git_bytes('checkout-index','--ignore-skip-worktree-bits','-z','--stdin',
            data=b''.join(n.encode()+b'\0' for n in missing))
    patch=git_bytes('diff','--binary','--no-ext-diff','--no-textconv',snapshot.manifest['baseSha'])
    if hashlib.sha256(patch).hexdigest()!=snapshot.manifest['patchSha256']:
        raise SystemExit('Frozen source materialization altered the reviewed upload patch.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--submit',action='store_true')
    mode.add_argument('--reconcile',action='store_true')
    p.add_argument('--stage-a-evidence',type=Path);p.add_argument('--pipeline-evidence',type=Path)
    p.add_argument('--resource-plan',choices=tuple(RESOURCE_PLANS),default='workers16-v3')
    p.add_argument('--journal',type=Path,required=True)
    args=p.parse_args()
    if args.journal.resolve().parent!=EVIDENCE.resolve():
        raise SystemExit('Use a new scoped implementation-evidence journal.')
    with submission_lock():return controlled_main(args)


def controlled_main(args):
    if args.reconcile:return reconcile(args)
    plan_name=getattr(args,'resource_plan','workers16-v3')
    binding=RESOURCE_PLANS[plan_name]
    workflow_path=binding['workflow']
    canonical=json.loads(STATE.read_text()) if STATE.exists() else None
    if canonical and canonical.get('status') not in ('NATIVE_FAILED',):
        raise SystemExit('Canonical StageB attempt is active/unknown/finished; reconcile it, never submit a duplicate.')
    if args.journal.exists():
        old=json.loads(args.journal.read_text())
        if old.get('runId') or old.get('status') not in ('PREPARED',):
            raise SystemExit('Existing attempt must be reconciled; never duplicate an uncertain submission.')
    plan=json.loads((EVIDENCE/binding['planFile']).read_text())
    actual_plan=hashlib.sha256(json.dumps(plan['profile'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if plan.get('profileSha256')!=binding['stageB'] or actual_plan!=binding['stageB'] or plan['profile'].get('jobTimeoutMinutes')!=225:
        raise SystemExit('Predeclared extended B plan drift.')
    approvals={}
    if args.submit:
        if not args.stage_a_evidence or not args.pipeline_evidence:
            raise SystemExit('Pass actual full StageA and pipeline result files.')
    jcb,cfg,workflow=setup(plan_name)
    (ROOT/workflow_path).write_text(workflow)
    record={'status':'PREPARED','recordedAt':datetime.now(timezone.utc).isoformat(),
        'execution':'native Depot CI using JCB safe remote_patch snapshot',
        'authority':'discord-remaining-gates-human-authorization-20261015.json',
        'workflow':str(workflow_path),'workflowSha256':hashlib.sha256(workflow.encode()).hexdigest(),
        'profileSha256':binding['stageB'],'resourcePlan':plan_name,'prerequisiteEvidence':approvals,'org':ORG,
        'cpu':32,'memoryGiB':128,'maximumMinutes':225,'computeCeilingProxyUsd':21.60,
        'actualCost':'UNKNOWN','realDiscordRequests':0,'productionReady':'NO'}
    write_record(args.journal,record)
    if args.prepare:
        print(json.dumps({'status':'PREPARED_NOT_SUBMITTED','workflow':str(workflow_path),
            'profileSha256':binding['stageB'],'jobTimeoutMinutes':225}));return 0
    # Native CLI uploads only the already filtered temporary JCB snapshot.
    # No --follow: reconcile native status/logs on this same run ID separately.
    with jcb.Snapshot(ROOT,cfg.get('baseRef'),cfg.get('inputExcludes'),'remote_patch') as snapshot:
        if (snapshot.path/workflow_path).read_text()!=workflow:
            raise SystemExit('Snapshot does not contain the reviewed workflow.')
        materialize_qualification_sources(snapshot,jcb)
        # Qualify against the captured bytes, never the subsequently mutable
        # worktree. Reject subset manifests and altered pipeline profiles.
        approvals['stageA']=qualified(args.stage_a_evidence,'a',1000,binding['stageA'],snapshot.path)
        approvals['pipeline']=qualified(args.pipeline_evidence,'pipeline-qualification',32,binding['pipeline'],snapshot.path)
        record.update(status='SUBMISSION_IN_PROGRESS',snapshot=snapshot.manifest,
            journal=str(args.journal.resolve()),prerequisiteEvidence=approvals,
            previousAttempt=({'runId':canonical.get('runId'),'journal':canonical.get('journal'),
                'status':canonical.get('status')} if canonical else None))
        write_record(STATE,record);write_record(args.journal,record)
        command=['depot','ci','run','--workflow',str(workflow_path),'--job','test','--org',ORG]
        try:
            response=subprocess.run(command,cwd=snapshot.path,env=jcb.clean_env(),text=True,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
            output,code=response.stdout,response.returncode
        except subprocess.TimeoutExpired as error:
            output=error.stdout or ''
            if isinstance(output,bytes):output=output.decode(errors='replace')
            code=None  # Never infer that a timed-out submission did not run.
        except OSError:
            output='Native submission launch failed; reconcile before any retry.';code=None
        evidence={}
        for line in output.splitlines():jcb.observe_run(line,evidence)
        run=evidence.get('runId')
        record.update(status='SUBMITTED' if run else 'SUBMISSION_UNKNOWN',runId=run,
            submissionExitCode=code,transport=evidence)
        write_record(STATE,record);write_record(args.journal,record)
        args.journal.with_suffix('.submission.log').write_text(output)
        print(json.dumps({'status':record['status'],'runId':run,'submissionExitCode':code}))
        return 0 if run and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
