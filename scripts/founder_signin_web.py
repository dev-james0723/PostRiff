"""Credential-free build/runner for the real Founder sign-in browser tests; never targets a hosted service."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '.codex/founder-signin/web'
PORT = 4499


def main():
    if os.environ.get('VERCEL_ENV'):
        raise SystemExit('The sign-in fixture is local/CI only.')
    args = sys.argv[1:]
    if args and args[0] == '--prepare':
        args = args[1:]
        def ignored(directory, names):
            return [name for name in names if name.startswith(('.env', '.next')) or name in ('node_modules', '.git', 'tsconfig.tsbuildinfo')]
        shutil.copytree(ROOT / 'web', DEST, dirs_exist_ok=True, ignore=ignored)
    env = {key: value for key, value in os.environ.items() if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'TERM', 'CI', 'PLAYWRIGHT_BROWSERS_PATH', 'RAFII_CHROMIUM_PATH')}
    env.update(NEXT_PUBLIC_APP_URL=f'http://localhost:{PORT}', NEXT_PUBLIC_SUPABASE_URL='https://founder-fixture.supabase.co',
               NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='sb_publishable_local_fixture', NEXT_PUBLIC_PASSKEY_SIGN_IN='true',
               NEXT_PUBLIC_SENTRY_DISABLED='1', NEXT_TELEMETRY_DISABLED='1', POSTRIFF_API_ORIGIN='http://127.0.0.1:9',
               NODE_OPTIONS='--max-old-space-size=3072', LC_ALL='C')
    if not args:
        return 0
    if args != ['--test']:
        return subprocess.call(args, cwd=DEST, env=env)
    with socket.socket() as check:
        try:
            check.bind(('127.0.0.1', PORT))
        except OSError:
            raise SystemExit('The fixture port is already in use; existing processes are left untouched.')
    evidence = ROOT / '.founder-signin-evidence'
    evidence.mkdir(exist_ok=True)
    env.update(FOUNDER_SIGNIN_WEB_URL=f'http://localhost:{PORT}', FOUNDER_SIGNIN_EVIDENCE_DIR=str(evidence))
    with (evidence / 'web.log').open('w') as log:
        server = subprocess.Popen(['npm', 'run', 'start', '--', '-p', str(PORT)], cwd=DEST, env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            end = time.monotonic() + 60
            while time.monotonic() < end:
                if server.poll() is not None:
                    raise RuntimeError('The isolated web server stopped before it was ready; inspect the local log.')
                try:
                    with urlopen(f'http://localhost:{PORT}/founder/sign-in', timeout=2) as response:
                        if response.status == 200:
                            break
                except (URLError, OSError):
                    time.sleep(0.5)
            else:
                raise RuntimeError('The isolated web server did not become ready.')
            return subprocess.call(['node', 'web/tests/founder-sign-in-browser.cjs'], cwd=ROOT, env=env)
        finally:
            if server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()


if __name__ == '__main__':
    sys.exit(main())
