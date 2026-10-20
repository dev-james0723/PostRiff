"""Reproducible source-bound X acceptance: local-only SQL, synthetic X, production-built UI.

Run with an isolated environment containing requirements-dev.txt and requirements-x-tests.txt,
web npm dependencies, Playwright Chromium/WebKit, and PostgreSQL 17. No deployment,
production secrets, real provider requests or paid AI calls are used by this runner.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def source_identity():
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    files = {}
    for name in sorted(set(paths)):
        p = ROOT / name
        if name and p.is_file() and not p.is_symlink():
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'sourceTreeSha256': hashlib.sha256(encoded).hexdigest(), 'files': files}


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def wait_http(url, child, seconds=180, log_path=None):
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if child.poll() is not None:
            message = 'Fixture server exited before readiness.'
            if log_path is not None:
                try:
                    # Only a synthetic fixture log; never stream raw data into public CI.
                    lines = Path(log_path).read_text(errors='replace').splitlines()[-20:]
                    diagnostics = []
                    for line in lines:
                        if re.search(r'(?i)secret|token|password|authorization|bearer|cookie|api[_-]?key|(?:state|code)=', line):
                            diagnostics.append('[redacted potentially sensitive line]')
                        else:
                            diagnostics.append(re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '?', line)[:300])
                    message += '\nSynthetic fixture startup diagnostics (redacted):\n' + '\n'.join(diagnostics)[-3000:]
                except (OSError, UnicodeError):
                    message += ' Synthetic fixture log unavailable.'
            raise RuntimeError(message)
        try:
            with urlopen(url, timeout=3) as response:
                if response.status == 200: return
        except (OSError, URLError):
            pass
        time.sleep(.5)
    raise TimeoutError('Local fixture server readiness timed out.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--skip-web-contracts', action='store_true', help='Use only when separately recorded full web contracts already passed')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    if ROOT == out or ROOT in out.parents:
        raise SystemExit('Evidence must be outside this source worktree.')
    pg = Path(os.environ.get('POSTRIFF_PG_BIN') or subprocess.check_output(['pg_config', '--bindir'], text=True).strip())
    node = os.environ.get('RAFII_X_NODE') or shutil.which('node')
    if not node or not (pg / 'initdb').is_file(): raise SystemExit('Installed Node and PostgreSQL are required.')
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'PLAYWRIGHT_BROWSERS_PATH')}
    env.update(PYTHONPATH=str(ROOT / 'src') + os.pathsep + str(ROOT / 'tests'),
        POSTRIFF_RESEARCH='0', POSTRIFF_LOCAL_CLI='0', OPENAI_AGENTS_DISABLE_TRACING='1',
        NEXT_TELEMETRY_DISABLED='1', OPENUI_TELEMETRY_DISABLED='1', DO_NOT_TRACK='1',
        NEXT_PUBLIC_SENTRY_DISABLED='1', POSTRIFF_PG_BIN=str(pg), PYTHONUNBUFFERED='1',
        POSTRIFF_TEST_PYTHON=sys.executable)
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + str(Path(node).parent) + os.pathsep + env.get('PATH', '')
    before = source_identity(); (out / 'source-before.json').write_text(json.dumps(before, indent=2))
    report = {'status': 'RUNNING', 'evidenceClass': 'synthetic-provider application acceptance',
              'publicReady': False, 'providerCalls': 0, 'head': before['head'],
              'sourceTreeSha256': before['sourceTreeSha256'], 'stages': []}
    children, handles = [], []
    cluster = Path(tempfile.mkdtemp(prefix='rafii-x-g14-pg-acceptance-', dir='/tmp'))
    (cluster / 'socket').mkdir(); pg_started = False
    def run(name, command, cwd=ROOT, overrides=None, timeout=900):
        started = time.monotonic()
        with (out / (name + '.log')).open('w') as log:
            result = subprocess.run(command, cwd=cwd, env={**env, **(overrides or {})}, stdout=log, stderr=log, timeout=timeout)
        report['stages'].append({'name': name, 'exitCode': result.returncode, 'seconds': round(time.monotonic() - started, 2)})
        print(name + ': exit ' + str(result.returncode), flush=True)
        (out / 'result.json').write_text(json.dumps(report, indent=2))
        if result.returncode: raise RuntimeError(name + ' failed; inspect ' + str(out / (name + '.log')))
    def server(name, command, cwd, variables):
        log = (out / (name + '.log')).open('w'); handles.append(log)
        child = subprocess.Popen(command, cwd=cwd, env={**env, **variables}, stdout=log, stderr=log)
        children.append(child); return child
    try:
        run('initdb', [str(pg / 'initdb'), '-D', str(cluster / 'data'), '-A', 'trust', '--no-locale', '-E', 'UTF8'])
        run('pg-start', [str(pg / 'pg_ctl'), '-D', str(cluster / 'data'), '-l', str(cluster / 'server.log'), '-o',
            f"-h '' -k {cluster}/socket -c shared_buffers=32MB -c max_connections=40", '-w', 'start'])
        pg_started = True
        dsn = f'host={cluster}/socket dbname=postgres connect_timeout=5'
        run('pg-roles', [str(pg / 'psql'), dsn, '-v', 'ON_ERROR_STOP=1', '-c',
            'CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN;'])
        xmodules = sorted(p.stem for p in (ROOT / 'tests').glob('test_x_*.py'))
        cross = ['test_hosted_wave1_connectors', 'test_hosted_wave3_connectors', 'test_agent_capability_registry',
                 'test_site_agent', 'test_rafii_creation_capabilities', 'test_postriff_orchestration',
                 'test_postriff_platforms_x', 'test_postriff_skills', 'test_rafii_skill_registry', 'test_founder_product_events']
        cross += sorted(p.stem for p in (ROOT / 'tests').glob('test_pinterest*.py'))
        run('python-x-and-regression', [sys.executable, '-m', 'unittest', *xmodules, *cross, '-v'],
            overrides={'RAFII_X_TEST_DATABASE_DSN': dsn, 'RAFII_X_TEST_COST_DSN': dsn, 'RAFII_X_LOCAL_OAUTH_E2E': '1'})
        web = ROOT / 'web'
        run('lint', [node, 'node_modules/oxlint/bin/oxlint', 'src'], cwd=web)
        if not args.skip_web_contracts:
            tests = sorted(str(p.relative_to(ROOT)) for glob in ('*.test.cjs', '*.test.mjs') for p in (web / 'tests').glob(glob))
            run('web-contracts', [node, '--test', *tests, 'web/src/lib/locales/core.test.mjs'])
        api_port, web_port, pg_port = free_port(), free_port(), free_port()
        base = f'http://127.0.0.1:{web_port}'
        control = out / ('fixture-control-' + str(os.getpid()) + '.json')
        api = server('api', [sys.executable, 'scripts/x_direct_browser_fixture.py', '--port', str(api_port), '--pg-port', str(pg_port)], ROOT,
            {'POSTRIFF_DEV_WEB_ORIGIN': base, 'RAFII_X_FIXTURE_CONTROL_FILE': str(control)})
        wait_http(f'http://127.0.0.1:{api_port}/api/auth/config', api, log_path=out / 'api.log')
        # Local-only build with loopback routing. NEVER deploy this test artifact.
        web_env = {'POSTRIFF_API_ORIGIN': f'http://127.0.0.1:{api_port}'}
        run('production-build-local-fixture', [node, 'node_modules/next/dist/bin/next', 'build'], cwd=web, overrides=web_env)
        run('typecheck', [node, 'node_modules/typescript/bin/tsc', '--noEmit'], cwd=web)
        frontend = server('web', [node, 'node_modules/next/dist/bin/next', 'start', '-p', str(web_port), '-H', '127.0.0.1'], web, web_env)
        wait_http(base + '/api/auth/config', frontend)
        browser_env = {'RAFII_X_FIXTURE_CONTROL_FILE': str(control), 'RAFII_X_BROWSER_BASE': base,
                       'RAFII_X_BROWSER_EVIDENCE_DIR': str(out / 'browser')}
        for key in ('RAFII_X_CHROMIUM_EXECUTABLE', 'RAFII_X_WEBKIT_EXECUTABLE'):
            if os.environ.get(key): browser_env[key] = os.environ[key]
        run('connected-desktop-mobile', [node, 'tests/x-direct-connected-browser.cjs'], cwd=web, overrides=browser_env, timeout=360)
        after = source_identity()
        changed = [name for name in before['files'].keys() | after['files'].keys() if before['files'].get(name) != after['files'].get(name)]
        report['sourceChanged'] = changed
        if changed: raise RuntimeError('Source changed during acceptance: ' + ', '.join(changed))
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=str(error))
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    report['cleanupWarning'] = 'Task-owned fixture did not terminate gracefully; no unrelated processes were stopped.'
        for handle in handles: handle.close()
        if pg_started:
            result = subprocess.run([str(pg / 'pg_ctl'), '-D', str(cluster / 'data'), '-m', 'fast', '-w', 'stop'], capture_output=True, timeout=30)
            report['localPostgresStopped'] = result.returncode == 0
        for p in out.glob('fixture-control-*.json'): p.unlink()  # ephemeral fixture secret only
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}), flush=True)
    return 0 if report['status'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
