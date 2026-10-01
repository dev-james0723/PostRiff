"""Control-only, uniquely ported disposable PostgreSQL harness. Never accepts production DSNs."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PG = Path(os.environ.get('POSTRIFF_PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))


def main():
    if not (PG / 'initdb').is_file():
        print(f'validation_unavailable: {PG}/initdb missing')
        return 3
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='rafii-control-pg-') as directory:
        data, log = Path(directory) / 'data', Path(directory) / 'postgres.log'
        env = {**os.environ, 'LC_ALL': 'C', 'PYTHONPATH': str(ROOT / 'src') + ':' + str(ROOT / 'tests'),
               'RAFII_CONTROL_TEST_DSN': f'host=127.0.0.1 port={port} dbname=postgres', 'POSTRIFF_RESEARCH': '0'}
        for key in tuple(env):
            if key!='RAFII_CONTROL_TEST_DSN' and (key.startswith('RAFII_CONTROL_') or any(term in key for term in ('API_KEY','DATABASE_URL','SUPABASE','STRIPE_SECRET','OAUTH_CLIENT_SECRET','SENTRY_AUTH_TOKEN'))):
                env.pop(key)
        subprocess.run([str(PG / 'initdb'), '-D', str(data), '-A', 'trust', '--no-locale', '-E', 'UTF8'], check=True, stdout=subprocess.DEVNULL, env=env)
        subprocess.run([str(PG / 'pg_ctl'), '-D', str(data), '-l', str(log), '-o', f'-h 127.0.0.1 -p {port}', '-w', 'start'], check=True, stdout=subprocess.DEVNULL, env=env)
        try:
            migration = ROOT / 'migrations/postriff/049_rafii_control_foundation.sql'
            workflow = ROOT / 'migrations/postriff/051_rafii_control_read_workflow.sql'
            founder_views = ROOT / 'migrations/postriff/054_rafii_control_founder_views.sql'
            founder_contact = ROOT / 'migrations/postriff/055_rafii_control_founder_contact.sql'
            files = [ROOT / 'tests/phase2/rls.sql', migration, migration, workflow, workflow, ROOT/'migrations/postriff/052_rafii_control_investigations.sql', ROOT/'migrations/postriff/052_rafii_control_investigations.sql', ROOT/'migrations/postriff/053_rafii_control_business_workspace.sql', ROOT/'migrations/postriff/053_rafii_control_business_workspace.sql', founder_views, founder_views, founder_contact, founder_contact]  # Reapplication must be safe.
            for file in files:
                subprocess.run([str(PG / 'psql'), env['RAFII_CONTROL_TEST_DSN'], '-v', 'ON_ERROR_STOP=1', '-q', '-f', str(file)], check=True, stdout=subprocess.DEVNULL, env=env)
            result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/control', '-p', 'test_*.py', '-v'], cwd=ROOT, env=env) if '--browser-only' not in sys.argv else None
            if result and result.returncode:return result.returncode
            if '--browser' not in sys.argv:return 0
            if '--capture' in sys.argv:env['RAFII_CONTROL_TEST_CAPTURE']=str(Path(sys.argv[sys.argv.index('--capture')+1]).resolve(strict=True))
            if '--evidence-dir' in sys.argv:env['RAFII_CONTROL_TEST_EVIDENCE_DIR']=str(Path(sys.argv[sys.argv.index('--evidence-dir')+1]).resolve())
            return browser(env)
        finally:
            subprocess.run([str(PG / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'], check=True, stdout=subprocess.DEVNULL, env=env)


def browser(env):
    # Both servers are local test children and are stopped before the disposable database is removed.
    children=[]
    out=Path(env.get('RAFII_CONTROL_TEST_EVIDENCE_DIR',ROOT/'docs/rafii-control-v2/evidence/raw/read-workflow'))
    out.mkdir(parents=True,exist_ok=True)
    node=Path('/opt/homebrew/opt/node@24/bin/node')
    if not node.is_file(): node=Path('node')
    browser_env={**env,'RAFII_CONTROL_ENABLED':'1','RAFII_CONTROL_ORIGIN':'http://localhost:4549','RAFII_CONTROL_LOCAL_API':'http://127.0.0.1:4550','PLAYWRIGHT_BROWSERS_PATH':os.environ.get('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.control-browsers'))}
    env={**env,'RAFII_CONTROL_TEST_ORIGIN':'http://localhost:4549','RAFII_CONTROL_TEST_API_PORT':'4550'}
    try:
        with (out/'api.log').open('w') as api_log,(out/'next.log').open('w') as next_log:
            children.append(subprocess.Popen([sys.executable,'tests/control/serve.py'],cwd=ROOT,env=env,stdout=api_log,stderr=api_log))
            children.append(subprocess.Popen([str(node),'node_modules/next/dist/bin/next','start','-p','4549'],cwd=ROOT/'control-web',env=browser_env,stdout=next_log,stderr=next_log))
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if any(child.poll() is not None for child in children): raise RuntimeError('Browser server exited; inspect evidence/raw logs')
                try:
                    with urlopen('http://localhost:4549/sign-in',timeout=1) as response:
                        if response.status==200: break
                except OSError: time.sleep(.15)
            else: raise RuntimeError('Browser servers failed to become ready')
            return subprocess.run([str(node),'tests/founder-home-browser.cjs' if '--home-browser' in sys.argv else 'tests/workspace-browser.cjs'],cwd=ROOT/'control-web',env=browser_env).returncode
    finally:
        for child in children: child.terminate()
        for child in children:
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__ == '__main__':
    sys.exit(main())
