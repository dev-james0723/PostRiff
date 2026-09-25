"""Own and clean up loopback web/API/DB processes for real local browser integration."""
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
    OUT.mkdir(parents=True,exist_ok=True)
    # Refuse occupied ports; never attach to or terminate another developer's servers. SO_REUSEADDR, as the
    # servers themselves use, lets a port whose last server just stopped (connections in TIME_WAIT) count as
    # free, while a port that something is listening on still refuses; a port being released gets 30 s.
    for port in (4438,4439,55479):
        deadline=time.monotonic()+30
        while True:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                try:probe.bind(('127.0.0.1',port));break
                except OSError:
                    if time.monotonic()>deadline:
                        print(json.dumps({'status':'VALIDATION_UNAVAILABLE','reason':f'loopback port {port} occupied'}));return 3
            time.sleep(1)
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','TERM','POSTRIFF_PG_BIN','PLAYWRIGHT_MODULE','BROWSER_EXECUTABLE')}
    env.update(LC_ALL='C',POSTRIFF_LOCAL_CLI='0',POSTRIFF_RESEARCH='0',POSTRIFF_DEV_WEB_ORIGIN='http://127.0.0.1:4439')
    env.setdefault('PLAYWRIGHT_MODULE',str(ROOT/'.codex/consumer-ready/web/node_modules/playwright'))
    processes=[];logs=[]
    try:
        commands=[('backend',[sys.executable,'scripts/postriff_dev_hosted.py','--port','4438','--pg-port','55479']),('frontend',[sys.executable,'scripts/consumer_ready_web.py','npm','run','start','--','-p','4439','-H','127.0.0.1'])]
        for name,command in commands:
            log=(OUT/f'durable-{name}.log').open('w');logs.append(log)
            processes.append(subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
        for port,path in ((4438,'/api/catalog'),(4439,'/auth/sign-in')):
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if any(p.poll() is not None for p in processes):raise RuntimeError('A local server exited; inspect durable-*.log')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=2) as response:
                        if response.status==200:break
                except Exception:time.sleep(.25)
            else:raise RuntimeError('Local server readiness deadline exceeded')
        test = 'consumer-performance-browser.cjs' if '--performance' in sys.argv else 'consumer-durable-browser.cjs'
        return subprocess.call(['node','web/tests/' + test],cwd=ROOT,env=env)
    finally:
        import signal
        for p in processes:
            if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        for log in logs:log.close()
if __name__=='__main__':sys.exit(main())
