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
WORKFLOW=Path('.depot/workflows/discord-capacity-stage-b-v2.yml')
STAGE_A='fe939c0d1a8b55b2f68ad48f25b7f9caad7e63259ca954d97f5fd9cafe513836'
STAGE_B='dbf0252804259fa31f0409ebe732aa02e7e8ddd4d01b0ce0169a42476ff20f53'
PIPELINE='05fa895bbfac8ad5ff5d193aa12c80c06057d7930871a0ab8138992e2f728847'
ORG='jf34f85hr0'


def qualified(path, stage, users, profile, frozen_root):
    match=re.fullmatch(r'p8-([a-z0-9]+)-discord-capacity-results.json',path.name)
    if path.resolve().parent!=EVIDENCE.resolve() or not match:
        raise SystemExit('Use recovered native capacity evidence from this mission.')
    reconciliation=EVIDENCE/('p8-'+match[1]+'-reconciliation.json')
    receipt=json.loads(reconciliation.read_text())
    raw=path.read_bytes()
    actual_sha=hashlib.sha256(raw).hexdigest()
    if (receipt.get('runId')!=match[1] or receipt.get('status')!='PASS'
            or receipt.get('native')!='finished' or receipt.get('controllerExit')!=0
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


def setup():
    sys.path.insert(0,str(Path.home()/'Documents/James-Cloud-Build/scripts'))
    import jcb
    cfg=jcb.detect(ROOT,json.loads((ROOT/'.james-cloud-build.json').read_text()),task='test')
    if (cfg.get('envAllowlist') or cfg.get('localFallback') is not False
            or cfg.get('transportMode')!='remote_patch'):
        raise SystemExit('Reviewed secret-free cloud-only JCB transport is required.')
    if (ROOT/jcb.WORKFLOW).read_text()!=jcb.workflow(cfg):
        raise SystemExit('Standard JCB workflow/config drift; reconcile before submission.')
    cfg['tasks']={'test':'test:discord:capacity:jcb'}
    cfg['taskArgs']={'test':['--stage-b-extended-v2']}
    cfg['runner']={'validation':'depot-ubuntu-24.04-32','build':'depot-ubuntu-24.04-32'}
    cfg['cacheScope']='rafii-discord-release-20261015-stage-b-v2'
    workflow=jcb.workflow(cfg)
    if workflow.count('    timeout-minutes: 45')!=1:
        raise SystemExit('Unexpected extended workflow shape.')
    workflow=workflow.replace('name: James Cloud Build','name: Rafii Discord extended Stage B')
    workflow=workflow.replace('    timeout-minutes: 45','    timeout-minutes: 225')
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
    p.add_argument('--journal',type=Path,required=True)
    args=p.parse_args()
    if args.journal.resolve().parent!=EVIDENCE.resolve():
        raise SystemExit('Use a new scoped implementation-evidence journal.')
    with submission_lock():return controlled_main(args)


def controlled_main(args):
    if args.reconcile:return reconcile(args)
    canonical=json.loads(STATE.read_text()) if STATE.exists() else None
    if canonical and canonical.get('status') not in ('NATIVE_FAILED',):
        raise SystemExit('Canonical StageB attempt is active/unknown/finished; reconcile it, never submit a duplicate.')
    if args.journal.exists():
        old=json.loads(args.journal.read_text())
        if old.get('runId') or old.get('status') not in ('PREPARED',):
            raise SystemExit('Existing attempt must be reconciled; never duplicate an uncertain submission.')
    plan=json.loads((EVIDENCE/'P8-STAGE-B-RESOURCE-PLAN-V2.json').read_text())
    actual_plan=hashlib.sha256(json.dumps(plan['profile'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if plan.get('profileSha256')!=STAGE_B or actual_plan!=STAGE_B or plan['profile'].get('jobTimeoutMinutes')!=225:
        raise SystemExit('Predeclared extended B plan drift.')
    approvals={}
    if args.submit:
        if not args.stage_a_evidence or not args.pipeline_evidence:
            raise SystemExit('Pass actual full StageA and pipeline result files.')
    jcb,cfg,workflow=setup()
    (ROOT/WORKFLOW).write_text(workflow)
    record={'status':'PREPARED','recordedAt':datetime.now(timezone.utc).isoformat(),
        'execution':'native Depot CI using JCB safe remote_patch snapshot',
        'authority':'discord-remaining-gates-human-authorization-20261015.json',
        'workflow':str(WORKFLOW),'workflowSha256':hashlib.sha256(workflow.encode()).hexdigest(),
        'profileSha256':STAGE_B,'prerequisiteEvidence':approvals,'org':ORG,
        'cpu':32,'memoryGiB':128,'maximumMinutes':225,'computeCeilingProxyUsd':21.60,
        'actualCost':'UNKNOWN','realDiscordRequests':0,'productionReady':'NO'}
    write_record(args.journal,record)
    if args.prepare:
        print(json.dumps({'status':'PREPARED_NOT_SUBMITTED','workflow':str(WORKFLOW),
            'profileSha256':STAGE_B,'jobTimeoutMinutes':225}));return 0
    # Native CLI uploads only the already filtered temporary JCB snapshot.
    # No --follow: reconcile native status/logs on this same run ID separately.
    with jcb.Snapshot(ROOT,cfg.get('baseRef'),cfg.get('inputExcludes'),'remote_patch') as snapshot:
        if (snapshot.path/WORKFLOW).read_text()!=workflow:
            raise SystemExit('Snapshot does not contain the reviewed workflow.')
        materialize_qualification_sources(snapshot,jcb)
        # Qualify against the captured bytes, never the subsequently mutable
        # worktree. Reject subset manifests and altered pipeline profiles.
        approvals['stageA']=qualified(args.stage_a_evidence,'a',1000,STAGE_A,snapshot.path)
        approvals['pipeline']=qualified(args.pipeline_evidence,'pipeline-qualification',32,PIPELINE,snapshot.path)
        record.update(status='SUBMISSION_IN_PROGRESS',snapshot=snapshot.manifest,
            journal=str(args.journal.resolve()),prerequisiteEvidence=approvals,
            previousAttempt=({'runId':canonical.get('runId'),'journal':canonical.get('journal'),
                'status':canonical.get('status')} if canonical else None))
        write_record(STATE,record);write_record(args.journal,record)
        command=['depot','ci','run','--workflow',str(WORKFLOW),'--job','test','--org',ORG]
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
