"""Own and clean up loopback web/API/DB processes for real local browser integration."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/consumer-ready/evidence'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--founder',action='store_true',help='consolidated Founder UI and synthetic identities against the real local API/database')
    parser.add_argument('--tour',action='store_true',help='record a short local Demo workflow instead of the full Founder acceptance suite')
    parser.add_argument('--customers',action='store_true',help='run only the Founder Customer 360 browser acceptance')
    parser.add_argument('--performance',action='store_true')
    parser.add_argument('--api-port',type=int,default=4438)
    parser.add_argument('--web-port',type=int,default=4439)
    parser.add_argument('--pg-port',type=int,default=55479)
    parser.add_argument('--evidence-dir',type=Path,default=OUT)
    args=parser.parse_args()
    ports=(args.api_port,args.web_port,args.pg_port)
    if any(not 1024<=port<=65535 for port in ports) or len(set(ports))!=3:parser.error('Three distinct loopback ports from 1024 to 65535 are required')
    if args.founder and args.performance:parser.error('Choose Founder or consumer performance acceptance')
    if args.tour and not args.founder:parser.error('--tour requires --founder')
    if args.customers and (not args.founder or args.tour):parser.error('--customers requires --founder and cannot run with --tour')
    # Next bakes rewrites into the build. Runtime flags alone cannot change which API a test reaches.
    manifest=ROOT/'.codex/consumer-ready/web/.next/routes-manifest.json'
    try:
        rewrites=json.loads(manifest.read_text())['rewrites']
        if isinstance(rewrites,dict):rewrites=[item for group in rewrites.values() for item in group]
        for route in ('/api/:path*','/dev/:path*'):
            matches=[item for item in rewrites if item['source']==route]
            if len(matches)!=1 or matches[0]['destination']!=f'http://127.0.0.1:{args.api_port}'+route:raise ValueError('API build binding differs')
    except (OSError,KeyError,TypeError,ValueError):
        print(json.dumps({'status':'VALIDATION_UNAVAILABLE','reason':'Build the isolated web copy with matching --api-port and --web-port before browser acceptance'}));return 3
    out=args.evidence_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    # Refuse occupied ports; never attach to or terminate another developer's servers. SO_REUSEADDR, as the
    # servers themselves use, lets a port whose last server just stopped (connections in TIME_WAIT) count as
    # free, while a port that something is listening on still refuses; a port being released gets 30 s.
    for port in ports:
        deadline=time.monotonic()+30
        while True:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                try:probe.bind(('127.0.0.1',port));break
                except OSError:
                    if time.monotonic()>deadline:
                        print(json.dumps({'status':'VALIDATION_UNAVAILABLE','reason':f'loopback port {port} occupied'}));return 3
            time.sleep(1)
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','TERM','POSTRIFF_PG_BIN','PLAYWRIGHT_MODULE','BROWSER_EXECUTABLE','PLAYWRIGHT_BROWSERS_PATH','RAFII_CHROMIUM_PATH')}
    env.update(LC_ALL='C',POSTRIFF_LOCAL_CLI='0',POSTRIFF_RESEARCH='0',POSTRIFF_DEV_WEB_ORIGIN=f'http://127.0.0.1:{args.web_port}')
    if args.founder:
        env.update(RAFII_AGENT_HARNESS='1',RAFII_FOUNDER_WEB_ORIGINS=f'http://localhost:{args.web_port},http://127.0.0.1:{args.web_port}',RAFII_WEB_URL=f'http://localhost:{args.web_port}',RAFII_API_URL=f'http://127.0.0.1:{args.api_port}',FOUNDER_EVIDENCE_DIR=str(out))
    env.setdefault('PLAYWRIGHT_MODULE',str(ROOT/'.codex/consumer-ready/web/node_modules/playwright'))
    processes=[];logs=[]
    try:
        local_ports=['--api-port',str(args.api_port),'--web-port',str(args.web_port)]
        commands=[('backend',[sys.executable,'scripts/postriff_dev_hosted.py','--port',str(args.api_port),'--pg-port',str(args.pg_port)]+(['--founder-fixture'] if args.founder else [])),('frontend',[sys.executable,'scripts/consumer_ready_web.py',*local_ports,'npm','run','start','--','-p',str(args.web_port),'-H','127.0.0.1'])]
        for name,command in commands:
            log=(out/f'durable-{name}.log').open('w');logs.append(log)
            processes.append(subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
        for port,path in ((args.api_port,'/api/catalog'),(args.web_port,'/founder/sign-in' if args.founder else '/auth/sign-in')):
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if any(p.poll() is not None for p in processes):raise RuntimeError('A local server exited; inspect durable-*.log')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=2) as response:
                        if response.status==200:break
                except Exception:time.sleep(.25)
            else:raise RuntimeError('Local server readiness deadline exceeded')
        test = 'founder-tour.cjs' if args.tour else 'founder-browser.cjs' if args.founder else 'consumer-performance-browser.cjs' if args.performance else 'consumer-durable-browser.cjs'
        return subprocess.call(['node','web/tests/' + test]+(['--customers'] if args.customers else []),cwd=ROOT,env=env)
    finally:
        import signal
        for p in processes:
            if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        for log in logs:log.close()
if __name__=='__main__':sys.exit(main())
