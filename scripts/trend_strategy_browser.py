"""Real browser/API/SQL strategy adoption proof with explicit synthetic history.

Reuses the canonical dev host and Trend browser seed; no provider/model or
external publication. Only this process's fresh PostgreSQL cluster is touched.
"""
import argparse, copy, hashlib, importlib.util, json, os
from pathlib import Path
import shutil, signal, socket, subprocess, sys, threading, time, urllib.request, uuid
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
ROOT=Path(__file__).resolve().parents[1]


def _retryable_google_font_loader_failure(log: str) -> bool:
    """Only the witnessed upstream Next Google CSS parser transient qualifies."""
    return all(signature in log for signature in (
        'An error occurred in `next/font`',
        'next/dist/compiled/@next/font/dist/google/loader.js',
        "Cannot read properties of null (reading '1')",
    ))


def seed_history(service, connect, row):
    from postriff_phase2.growth.trends import contracts, learning, opportunities
    from postriff_phase2.coworker import performance
    now=time.time();wid=row['workspace_id']
    with connect() as db, db.cursor() as cur:
        state=cur.execute('SELECT state FROM pr_workspaces WHERE id=%s FOR UPDATE',(wid,)).fetchone()[0]
        source=next(s for s in state['sources'] if s['id']==row['source_id'])
        binding=source['origin']['trendLineage'];binding['accepted_at']=opportunities.iso(now-40*86400)
        # Explicit fixture chronology, never an application publishing operation.
        cur.execute("UPDATE pr_trend_projections SET payload=jsonb_set(payload,'{recorded_at}',to_jsonb(%s::text)) WHERE scope_key=%s AND kind='exposure'",
                    (opportunities.iso(now-41*86400),'workspace:'+wid))
        cur.execute('UPDATE pr_trend_opportunity_decisions SET created_at=to_timestamp(%s) WHERE workspace_id=%s',(now-40*86400,wid))
        learning.record_metric_choice(state,row['principal'],{'selection_digest':binding['selection_digest'],
            'channel_id':row['channel_id'],'provider':'threads','metric':'views','definition_version':'2026-09',
            'window':'24h','objective':'reach'},now-39*86400)
        jobs=[]
        for n in range(12):
            at=now-(n+2)*86400;jid=str(uuid.uuid4());text='Why this?' if n%2 else 'Observed statement'
            manifest={'channelId':row['channel_id'],'platform':'Threads','variantId':jid,'payload':{'text':text,'language':'en'},
                'contentType':{'id':'opinion'},'timing':{'timestamp':at},'paidPromotion':False,'trendLineage':[copy.deepcopy(binding)],
                'trendPublication':{'variantRevision':1,'textDigest':contracts.digest(text),'channelId':row['channel_id'],
                                    'platform':'Threads','treatmentChanged':False}}
            native='synthetic-native-'+jid
            jobs.append({'id':jid,'state':'verified','providerReference':native,'verifiedAt':at,'manifest':manifest,'execution':'synthetic-test-only'})
            cur.execute("""INSERT INTO pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,
                value,unit,availability,observed_at,ingested_at,read_offset) VALUES(%s,%s,'threads',%s,%s,'views','2026-09',%s,'count','available',
                to_timestamp(%s),to_timestamp(%s),'24h')""",(wid,row['channel_id'],native,jid,900 if n%2 else 400,at+86400,at+86401))
        state['phase2']['jobs']=jobs
        cur.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),wid))
        from postriff_phase2.growth.trends.store import TrendStore
        report=learning.report(cur,wid,row['principal'],now,store=TrendStore(connect))
        assert report['outcome_states']=={'measured':12},report['outcome_states']
        performance.refresh(cur,wid,state,now,trend_report=report)
        row['hypothesis_id']=cur.execute("SELECT id::text FROM pr_strategy_hypotheses WHERE workspace_id=%s AND left(dimension,6)='trend_' ORDER BY id LIMIT 1",(wid,)).fetchone()[0]
        row['state_digest']=contracts.digest(state)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--skip-build',action='store_true',help='Reuse only the exact prior source-bound build in this output directory')
    p.add_argument('--api-port',type=int,default=4498);p.add_argument('--web-port',type=int,default=4499);p.add_argument('--pg-port',type=int,default=56469)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    prior=json.loads((out/'receipt.json').read_text()) if args.skip_build else None
    # Previous fixture IPC belongs to a destroyed isolated database.
    for marker in (*out.glob('revoke-*.json'),*out.glob('revoked-*.json')):marker.unlink()
    safe={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','BROWSER_EXECUTABLE','POSTRIFF_PG_BIN')}
    os.environ.clear();os.environ.update(safe,LC_ALL='C',POSTRIFF_RESEARCH='0',POSTRIFF_LOCAL_CLI='0',PYTHONDONTWRITEBYTECODE='1')
    for port in (args.api_port,args.web_port,args.pg_port):
        with socket.socket() as probe:probe.bind(('127.0.0.1',port))
    blocked=[]
    def audit(event,values):
        host=values[1][0] if event=='socket.connect' and isinstance(values[1],tuple) else values[0] if event=='socket.getaddrinfo' else None
        if host is not None and host not in ('127.0.0.1','::1','localhost'):
            blocked.append(event);raise RuntimeError('Strategy proof denies external network')
    sys.addaudithook(audit)
    from postriff_dev_hosted import start_postgres,DevVerifier,PG
    import psycopg
    from postriff_phase2.hosted import HostedWorkspaceService
    from postriff_phase2.hosted_app import HostedApplication
    from postriff_phase2.coworker.runtime import attach
    from postriff_phase2.growth.trends import config,contracts
    spec=importlib.util.spec_from_file_location('strategy_seed',ROOT/'tests/phase2/seed_trend_browser.py')
    seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
    sources=[str(p.relative_to(ROOT)) for folder in ('src','web/src') for p in (ROOT/folder).rglob('*') if p.suffix in ('.py','.tsx','.ts','.css')]
    sources+=['scripts/trend_strategy_browser.py','web/tests/trend-strategy-live-api-browser.cjs']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
    receipt={'execution':'real_browser_API_PostgreSQL_synthetic_publication_and_metric_history','source_start':hashes(),
             'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'provider_calls':0,'model_calls':0,'production_verified':False,'api_interception':False}
    data=None;server=None;proc=None;worker=None;stop=threading.Event();errors=[];dist='.next-trend-strategy';code=1
    try:
        dsn,data=start_postgres(args.pg_port);connect=lambda:psycopg.connect(dsn,client_encoding='utf8')
        with connect() as db:db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        service=HostedWorkspaceService(connect,DevVerifier(connect));rows=seed.seed_browser(service,connect,scenario='learning')
        flags={name:'0' for name in config.FLAG_NAMES}
        flags.update({f'RAFII_TREND_{k}_ENABLED':'1' for k in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS')})
        flags.update(RAFII_TREND_WORKSPACE_ALLOWLIST=','.join(r['workspace_id'] for r in rows),
            RAFII_TREND_CURSOR_SIGNING_KEY='synthetic-strategy-local-test-key-only',RAFII_PERFORMANCE_LEARNING_ENABLED='1',RAFII_ADAPTIVE_SKILLS_ENABLED='1')
        attach(service,flags);seed.seed_learning_sources(service,connect,rows)
        for row in rows:seed_history(service,connect,row)
        class Server(ThreadingMixIn,WSGIServer):daemon_threads=True
        class Quiet(WSGIRequestHandler):
            def log_message(self,*_):pass
        server=make_server('127.0.0.1',args.api_port,HostedApplication(service,public_auth={'provider':'dev','execution':'dev-synthetic','flow':'dev'}),server_class=Server,handler_class=Quiet)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        (out/'seed.json').write_text(json.dumps(rows))
        env=dict(os.environ,NEXT_TELEMETRY_DISABLED='1',NEXT_PUBLIC_SENTRY_DISABLED='1',POSTRIFF_DIST_DIR=dist,
            POSTRIFF_API_ORIGIN=f'http://127.0.0.1:{args.api_port}',POSTRIFF_DEV_SSR='1',
            TREND_WEB_URL=f'http://127.0.0.1:{args.web_port}',TREND_EVIDENCE_DIR=str(out))
        if args.skip_build:
            assert all(prior['source_start'][p]==digest for p,digest in receipt['source_start'].items() if p.startswith('web/src/')),'Frontend sources differ from saved build'
            assert prior['build_id']==(ROOT/'web'/dist/'BUILD_ID').read_text().strip()
            manifest=json.loads((ROOT/'web'/dist/'routes-manifest.json').read_text())
            assert any(r['destination']==env['POSTRIFF_API_ORIGIN']+'/api/:path*' for r in manifest['rewrites']['afterFiles'])
        else:
            # Next.js 16.3.8 Google font CSS metadata occasionally returns an
            # incomplete response. This is a narrow one-time network recovery,
            # not a generic CI retry or an acceptance/test bypass.
            build_command = ['npm', 'run', 'build', '--', '--webpack']
            build_log = out/'build.log'
            with build_log.open('w') as log:
                build = subprocess.run(build_command, cwd=ROOT/'web', env=env,
                    stdout=log, stderr=subprocess.STDOUT, check=False, timeout=600)
            if build.returncode and _retryable_google_font_loader_failure(build_log.read_text()):
                with build_log.open('a') as log:
                    log.write('\\n[ci] Retry 1/1: exact transient next/font Google metadata parser signature\\n')
                    build = subprocess.run(build_command, cwd=ROOT/'web', env=env,
                        stdout=log, stderr=subprocess.STDOUT, check=False, timeout=600)
            if build.returncode:
                raise subprocess.CalledProcessError(build.returncode, build_command)
        receipt['build_id']=(ROOT/'web'/dist/'BUILD_ID').read_text().strip()
        with (out/'web.log').open('w') as log:
            proc=subprocess.Popen(['node','node_modules/next/dist/bin/next','start','-p',str(args.web_port),'--hostname','127.0.0.1'],cwd=ROOT/'web',env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            for _ in range(120):
                try:
                    with urllib.request.urlopen(env['TREND_WEB_URL']+'/auth/sign-in',timeout=2) as response:
                        if response.status==200:break
                except Exception:time.sleep(.25)
            else:raise RuntimeError('Next readiness timeout')
            def revocations():
                pending=list(rows)
                try:
                    while pending and not stop.wait(.05):
                        for row in list(pending):
                            if (out/f"revoke-{row['width']}.json").exists():
                                seed.revoke_learning_fixture(connect,row)
                                (out/f"revoked-{row['width']}.json").write_text('{}');pending.remove(row)
                except Exception as e:errors.append(str(e))
            worker=threading.Thread(target=revocations,daemon=True);worker.start()
            code=subprocess.call(['node','web/tests/trend-strategy-live-api-browser.cjs'],cwd=ROOT,env=env)
        with connect() as db:
            saved=[]
            for row in rows:
                state=db.execute('SELECT state FROM pr_workspaces WHERE id=%s',(row['workspace_id'],)).fetchone()[0]
                h=db.execute('SELECT status,causal,experiment,decided_by::text FROM pr_strategy_hypotheses WHERE id::text=%s',(row['hypothesis_id'],)).fetchone()
                assert contracts.digest(state)==row['state_digest'],'Strategy must not rewrite workspace/voice/plans'
                if code==0:assert h[0]=='supported' and h[1] is False and h[2]['planningAccepted'] and h[2]['supportDigest'] and h[3]==row['principal']
                saved.append({'width':row['width'],'status':h[0],'causal':h[1],'owner_bound':h[3]==row['principal'],'workspace_unchanged':True})
            for table in ('pr_model_usage_events','pr_trend_budget_reservations','pr_trend_jobs'):
                assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table
            receipt['persistence']=saved
        assert not blocked and not errors,(blocked,errors)
        receipt['status']='PASS' if code==0 else 'FAIL';return code
    finally:
        stop.set()
        if worker:worker.join(timeout=5)
        if server:server.shutdown();server.server_close()
        if proc and proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=15)
        if data:
            subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'],check=True,stdout=subprocess.DEVNULL)
            shutil.rmtree(data.parent)
        cfg=ROOT/'web/tsconfig.json';v=json.loads(cfg.read_text());v['include']=[x for x in v.get('include',[]) if not x.startswith(dist+'/')];cfg.write_text(json.dumps(v,indent=2)+'\n')
        receipt['source_end']=hashes();receipt['source_drift']=[p for p in sources if receipt['source_start'][p]!=receipt['source_end'][p]]
        if receipt['source_drift']:receipt['status']='FAIL'
        receipt['blocked_external_attempts']=blocked;receipt['fixture_errors']=errors
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        if receipt['source_drift']:raise RuntimeError('Source changed during strategy browser acceptance')


if __name__=='__main__':sys.exit(main())
