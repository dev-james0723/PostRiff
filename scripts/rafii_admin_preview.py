"""Persistent, loopback-only Rafii Admin review runtime. No hosted configuration is admitted.

Run after control-web has been built. Ctrl-C stops only this launcher's children and
its uniquely created PostgreSQL cluster; logs are retained in its private directory.
Synthetic identity lives in the test harness, not the hosted Control application.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rafii_control_pg import PG

ROOT = Path(__file__).resolve().parents[1]
NODE = Path('/opt/homebrew/opt/node@24/bin/node')
PYTHON = Path('/Users/ouxianxing/.codex/worktrees/rafii-founder-control-v2/James-Au-Studio/.control-venv/bin/python')
MIGRATIONS = (
    'tests/phase2/rls.sql',
    'migrations/postriff/049_rafii_control_foundation.sql',
    'migrations/postriff/051_rafii_control_read_workflow.sql',
    'migrations/postriff/052_rafii_control_investigations.sql',
    'migrations/postriff/053_rafii_control_business_workspace.sql',
)
SAFE_ENVIRONMENT = frozenset({'PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'TZ'})


def safe_environment(values: dict[str, str]) -> dict[str, str]:
    """Only process necessities survive, never inherited provider/database secrets."""
    if values.get('VERCEL') or values.get('VERCEL_ENV'):
        raise ValueError('Local preview cannot run in a deployment environment')
    return {
        **{key: value for key, value in values.items() if key in SAFE_ENVIRONMENT},
        'LC_ALL': 'C',
        'PYTHONDONTWRITEBYTECODE': '1',
        'POSTRIFF_RESEARCH': '0',
        'NEXT_TELEMETRY_DISABLED': '1',
    }


def free_port(preferred: int = 0, *, excluded: frozenset[int] = frozenset()) -> int:
    if not 0 <= preferred <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    candidates = [preferred] if preferred else []
    for candidate in [*candidates, 0]:
        if candidate in excluded:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('127.0.0.1', candidate))
            except OSError:
                if candidate:
                    continue
                raise
            selected = sock.getsockname()[1]
            if selected not in excluded:
                return selected
    raise RuntimeError('No distinct loopback port available')


def runtime_environment(base: dict[str, str], *, web_port: int, api_port: int, pg_port: int) -> tuple[dict[str, str], dict[str, str]]:
    if len({web_port, api_port, pg_port}) != 3 or any(not 1 <= port <= 65535 for port in (web_port, api_port, pg_port)):
        raise ValueError('Three distinct valid local ports required')
    origin = f'http://localhost:{web_port}'
    api_env = {
        **base,
        'PYTHONPATH': str(ROOT / 'src') + ':' + str(ROOT / 'tests'),
        'RAFII_CONTROL_TEST_DSN': f'host=127.0.0.1 port={pg_port} dbname=postgres',
        'RAFII_CONTROL_TEST_ORIGIN': origin,
        'RAFII_CONTROL_TEST_API_PORT': str(api_port),
    }
    web_env = {
        **base,
        'RAFII_CONTROL_ENABLED': '1',
        'RAFII_CONTROL_ENVIRONMENT': 'local',
        'RAFII_CONTROL_ORIGIN': origin,
        'RAFII_CONTROL_LOCAL_API': f'http://127.0.0.1:{api_port}',
        'RAFII_CONTROL_LOCAL_PREVIEW': '1',
        # Consumed only by the dynamically gated server page. Not a real identity.
        'RAFII_CONTROL_LOCAL_PREVIEW_TOKEN': 'synthetic-founder-aal2',
    }
    return api_env, web_env


def prerequisites(python: Path, pg: Path, node: Path) -> None:
    required = [python, node, pg / 'initdb', pg / 'pg_ctl', pg / 'psql', ROOT / 'control-web/node_modules/next/dist/bin/next', ROOT / 'control-web/.next/BUILD_ID', ROOT / 'tests/control/serve.py', *[ROOT / file for file in MIGRATIONS]]
    missing = [str(file) for file in required if not file.is_file()]
    if missing:
        raise RuntimeError('validation_unavailable: required preview inputs missing: ' + ', '.join(missing))
    # Next automatically loads these files. Refuse rather than silently inherit a
    # later-added production or provider configuration after sanitizing the shell.
    for name in ('.env', '.env.local', '.env.production', '.env.production.local'):
        if (ROOT / 'control-web' / name).exists():
            raise ValueError('Local preview refuses control-web environment files: ' + name)


def wait_until_ready(children: list[subprocess.Popen], origin: str, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(child.poll() is not None for child in children):
            raise RuntimeError('Preview server exited; inspect retained api.log / next.log')
        try:
            with urlopen(origin + '/demo-access', timeout=1) as response:
                page_ready = response.status == 200
            # Unauthorized is the expected healthy response from the real boundary.
            try:
                with urlopen(Request(origin + '/api/control/v2/session'), timeout=1):
                    api_ready = False
            except HTTPError as response:
                api_ready = response.code == 401
            if page_ready and api_ready:
                return
        except (OSError, URLError):
            pass
        time.sleep(.15)
    raise RuntimeError('Preview readiness timed out; inspect retained api.log / next.log')


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def launch(args: argparse.Namespace) -> int:
    base = safe_environment(dict(os.environ))
    python, pg, node = args.python, args.pg_bin, args.node
    prerequisites(python, pg, node)
    if args.check:
        print(json.dumps({'state': 'preflight_passed', 'execution': 'local_only_no_servers_started'}), flush=True)
        return 0
    web_port = free_port(args.web_port)
    api_port = free_port(args.api_port, excluded=frozenset({web_port}))
    pg_port = free_port(excluded=frozenset({web_port, api_port}))
    api_env, web_env = runtime_environment(base, web_port=web_port, api_port=api_port, pg_port=pg_port)
    runtime = Path(tempfile.mkdtemp(prefix='rafii-admin-preview-', dir='/private/tmp'))
    runtime.chmod(0o700)
    data = runtime / 'postgres'
    origin = web_env['RAFII_CONTROL_ORIGIN']
    children: list[subprocess.Popen] = []
    pg_started = False
    stopped = False
    metadata = {'state': 'starting', 'execution': 'local_fictional_demo_real_control_boundary', 'url': origin + '/demo-access', 'origin': origin, 'apiPort': api_port, 'postgresPort': pg_port, 'runtimeDirectory': str(runtime), 'launcherPid': os.getpid(), 'providerCalls': 0, 'productionPromotion': 'awaiting_user_review'}
    manifest = runtime / 'preview.json'

    def save() -> None:
        manifest.write_text(json.dumps(metadata, indent=2) + '\n')

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    save()
    try:
        with (runtime / 'postgres-setup.log').open('w') as setup_log:
            subprocess.run([str(pg / 'initdb'), '-D', str(data), '-A', 'trust', '--no-locale', '-E', 'UTF8'], check=True, stdout=setup_log, stderr=setup_log, env=base)
            pg_started = True
            subprocess.run([str(pg / 'pg_ctl'), '-D', str(data), '-l', str(runtime / 'postgres.log'), '-o', f'-h 127.0.0.1 -p {pg_port} -k {runtime}', '-w', 'start'], check=True, stdout=setup_log, stderr=setup_log, env=base)
            for migration in MIGRATIONS:
                subprocess.run([str(pg / 'psql'), api_env['RAFII_CONTROL_TEST_DSN'], '-v', 'ON_ERROR_STOP=1', '-q', '-f', str(ROOT / migration)], check=True, stdout=setup_log, stderr=setup_log, env=base)
        with (runtime / 'api.log').open('w') as api_log, (runtime / 'next.log').open('w') as next_log:
            children.append(subprocess.Popen([str(python), 'tests/control/serve.py'], cwd=ROOT, env=api_env, stdout=api_log, stderr=api_log))
            children.append(subprocess.Popen([str(node), 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', str(web_port)], cwd=ROOT / 'control-web', env=web_env, stdout=next_log, stderr=next_log))
            metadata['childPids'] = [child.pid for child in children]
            save()
            wait_until_ready(children, origin)
            metadata['state'] = 'ready'
            save()
            print(json.dumps(metadata), flush=True)
            while not stopped:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError('Owned preview server stopped; inspect retained logs')
                time.sleep(.25)
        return 0
    finally:
        stop_children(children)
        if pg_started:
            subprocess.run([str(pg / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=base)
        metadata['state'] = 'stopped'
        save()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-port', type=int, default=4649)
    parser.add_argument('--api-port', type=int, default=4650)
    parser.add_argument('--python', type=Path, default=PYTHON)
    parser.add_argument('--node', type=Path, default=NODE)
    parser.add_argument('--pg-bin', type=Path, default=PG)
    parser.add_argument('--check', action='store_true', help='Validate local inputs without starting anything')
    try:
        return launch(parser.parse_args())
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
