"""Build and exercise a credential-free copy of the real web UI. No install/deploy.

Uses existing node_modules and a unique temporary directory; never touches an
existing dev server, .next output or .env file. Browser APIs are synthetic.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    node = shutil.which('node')
    if not node:
        raise RuntimeError('A local Node executable is required.')
    work = Path(tempfile.mkdtemp(prefix='rafii-social-acceptance-'))
    dest, evidence = work / 'web', work / 'evidence'
    evidence.mkdir()
    def ignored(directory, names):
        return [name for name in names if name.startswith(('.env', '.next')) or name in ('node_modules', '.git', 'tsconfig.tsbuildinfo')]
    shutil.copytree(ROOT / 'web', dest, ignore=ignored)
    (dest / 'node_modules').symlink_to(ROOT / 'web/node_modules', target_is_directory=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {key: value for key, value in os.environ.items() if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'TERM', 'BROWSER_EXECUTABLE')}
    env.update(NEXT_PUBLIC_APP_URL=base, NEXT_PUBLIC_SUPABASE_URL='', NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='', NEXT_PUBLIC_SENTRY_DISABLED='1', NEXT_TELEMETRY_DISABLED='1', POSTRIFF_DEV_SSR='0', LC_ALL='C', SOCIAL_WEB_URL=base, SOCIAL_EVIDENCE_DIR=str(evidence))
    print(json.dumps({'isolatedCopy': str(dest), 'evidence': str(evidence), 'externalAccounts': False}), flush=True)
    built = subprocess.run([node, 'node_modules/next/dist/bin/next', 'build', '--webpack'], cwd=dest, env=env, capture_output=True, text=True, timeout=240)
    (evidence / 'build.log').write_text(built.stdout + '\n' + built.stderr)
    print(json.dumps({'buildExit': built.returncode, 'output': (built.stdout + '\n' + built.stderr)[-9000:]}), flush=True)
    if built.returncode:
        return built.returncode
    server = None
    with (evidence / 'server.log').open('w') as log:
        try:
            server = subprocess.Popen([node, 'node_modules/next/dist/bin/next', 'start', '-H', '127.0.0.1', '-p', str(port)], cwd=dest, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError('Isolated Next server exited; inspect its credential-free log.')
                try:
                    with urllib.request.urlopen(base + '/auth/sign-in', timeout=2) as response:
                        if response.status == 200:
                            break
                except (OSError, TimeoutError):
                    time.sleep(.25)
            else:
                raise RuntimeError('Isolated Next server readiness deadline exceeded.')
            test = subprocess.run([node, 'web/tests/social-learning-browser.cjs'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
            (evidence / 'browser.log').write_text(test.stdout + '\n' + test.stderr)
            print(json.dumps({'browserExit': test.returncode, 'output': (test.stdout + '\n' + test.stderr)[-9000:], 'evidence': str(evidence)}), flush=True)
            return test.returncode
        finally:
            if server is not None and server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()


if __name__ == '__main__':
    sys.exit(main())
