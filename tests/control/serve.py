"""Synthetic identity injection exists only in disposable tests, never in the deployment artifact."""
import os
import time
import json
import hashlib
import subprocess
import psycopg
from control.test_boundary import CAPS
from pathlib import Path
from datetime import datetime,timezone,timedelta
from rafii_control.snapshot_store import import_snapshot
from rafii_control.github_source import capture_response
from wsgiref.simple_server import make_server, WSGIRequestHandler
from rafii_control.auth import Boundary, Config, VerifiedIdentity, ControlError, CAPABILITIES
from rafii_control.http import ControlApplication
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory
from control.synthetic_workflow import seed

class Quiet(WSGIRequestHandler):
    def log_message(self, format, *args): pass

def main():
    if os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'): raise RuntimeError('Local tests only')
    dsn=os.environ['RAFII_CONTROL_TEST_DSN']
    if not dsn.startswith('host=127.0.0.1 port='): raise RuntimeError('Disposable loopback cluster only')
    with psycopg.connect(dsn,autocommit=True) as owner:
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES('00000000-0000-0000-0000-000000000001','local','founder','active',%s) ON CONFLICT(user_id,environment) DO UPDATE SET status='active',capabilities=excluded.capabilities",(list(CAPABILITIES),))
        owner.execute('DELETE FROM rafii_control.request_budgets')
    seed(dsn,'synthetic-browser')
    factory=connection_factory(dsn,'rafii_control_ingest','local')
    if os.environ.get('RAFII_CONTROL_TEST_CAPTURE'):
        observed=json.loads(Path(os.environ['RAFII_CONTROL_TEST_CAPTURE']).read_text())
        import_snapshot(factory,observed,admit=True)
    now=datetime.now(timezone.utc)
    original=json.loads((Path(__file__).parent/'fixtures/github-observed-be140fd.json').read_text())
    for scenario,conclusions,age in [('zero-one',['success','failure'],0),('partial-infra',['skipped','timed_out'],0),('stale',['success','failure'],20)]:
        stamp=(now-timedelta(minutes=age)).isoformat()
        body={'total_count':2,'workflow_runs':[{**run,'conclusion':conclusion,'updated_at':stamp} for run,conclusion in zip(original['workflowRuns'],conclusions)]}
        synthetic=capture_response({**body,'workflow_runs':[{**r,'head_sha':'a'*40} for r in body['workflow_runs']]},'a'*40,stamp,stamp)
        synthetic['provenance']='synthetic'
        import_snapshot(factory,synthetic)
    root=Path(__file__).resolve().parents[2]
    delivery={'state':'local_candidate','localCandidate':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'localBranch':subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip(),'workingTree':'tracked_changes' if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root,text=True).strip() else 'clean_tracked_source','remotePRHead':'be140fdbaad9e13093b3d42215b66ed0a2347a69','targetBranch':'consumer-saas; last read 1acd88a8b77c5e8a3f2b877dd927e755c2900a56','ciSHA':'be140fdbaad9e13093b3d42215b66ed0a2347a69','localCandidateCI':'not_run','documentSpecSHA256':'1ababaaff637a04be105fa41caf1eb57f071c1e57819eb39116c030fea993002','hostedControlDeployment':None}
    runtime_files=sorted([*root.joinpath('src/rafii_control').glob('*.py'),*root.joinpath('control-web/app').rglob('*.tsx'),*root.joinpath('control-web/app').rglob('*.ts'),root/'control-web/query-state.mjs',root/'control-web/app/globals.css'])
    delivery['runtimeSourceSHA256']=hashlib.sha256(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime_files},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    delivery['nextBuildId']=(root/'control-web/.next/BUILD_ID').read_text().strip()
    store=PostgresStore(connection_factory(dsn,'rafii_control_session','local'),connection_factory(dsn,'rafii_control_reader','local'),'local')
    founders={'synthetic-founder-aal2':'00000000-0000-0000-0000-000000000001',
              'synthetic-founder-mobile-aal2':'00000000-0000-0000-0000-000000000010',
              'synthetic-founder-error-aal2':'00000000-0000-0000-0000-000000000011'}
    def verify(token):
        user=founders.get(token)
        if token=='synthetic-non-founder-aal2':user='00000000-0000-0000-0000-000000000002'
        if not user:raise ControlError('AUTH_REQUIRED',401)
        return VerifiedIdentity(user,'aal2','synthetic-browser-session-'+user,time.time())
    origin=os.environ.get('RAFII_CONTROL_TEST_ORIGIN','http://localhost:4449')
    user='00000000-0000-0000-0000-000000000001'
    from postriff_phase2.hosted import PostgresWorkspaceRepository
    repository=PostgresWorkspaceRepository(lambda:psycopg.connect(dsn,prepare_threshold=None),lambda token:user)
    with psycopg.connect(dsn,autocommit=True) as owner:
        owner.execute('DELETE FROM rafii_control.request_budgets')
        workspace=str(owner.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s AND status=\'active\' LIMIT 1',(user,)).fetchone()[0])
        owner.execute("UPDATE rafii_control.platform_operators SET status='active',capabilities=%s WHERE user_id=%s AND environment='local'",(list(CAPABILITIES),user))
        # Separate fictional identities isolate browser acceptance cases without changing production limits.
        for actor in founders.values():
            owner.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING',(actor,))
            owner.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING',(actor,))
            owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s) ON CONFLICT(user_id,environment) DO UPDATE SET status='active',capabilities=excluded.capabilities",(actor,list(CAPABILITIES)))
            owner.execute("INSERT INTO rafii_control.test_workspace_grants VALUES(%s,'local',%s,'synthetic-browser-only',now()+interval '1 hour') ON CONFLICT DO NOTHING",(actor,workspace))
    snapshot=repository.get(workspace,'synthetic-owner')
    repository.command(workspace,'synthetic-owner',snapshot['revision'],lambda state,actor:{**state,'workspace':{'id':workspace,'name':'Fictional Browser Workspace'}})
    application=ControlApplication(Boundary(Config(True,'local',origin),store,verify),QueryService(store,synthetic=True,delivery=delivery))
    print('CONTROL_TEST_DELIVERY '+json.dumps(delivery,sort_keys=True),flush=True)
    def fixture(environ,start_response):
        if environ.get('PATH_INFO')=='/synthetic/rafii/workspace' and environ.get('HTTP_AUTHORIZATION')=='Bearer synthetic-owner':
            start_response('200 OK',[('Content-Type','application/json'),('Cache-Control','no-store')])
            return [json.dumps(repository.get(workspace,'synthetic-owner')).encode()]
        return application(environ,start_response)
    with make_server('127.0.0.1',int(os.environ.get('RAFII_CONTROL_TEST_API_PORT','4450')),fixture,handler_class=Quiet) as server: server.serve_forever()

if __name__=='__main__': main()
