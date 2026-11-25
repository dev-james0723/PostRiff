"""Real hosted API/database in explicit cloud or macOS-local mode; synthetic identity/providers."""
import json
import os
import pwd
import shutil
import signal
import tempfile
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import postriff_dev_hosted as harness

# Only PostgreSQL subprocesses drop OS privileges when the ephemeral CI runner
# itself is root. Python/Next remain the runner user; no project files are chowned.
_run = subprocess.run
_local = os.environ.get("BRAND_BRAIN_EXECUTION") == "local"
_local_clusters = set()
def fixture_run(command, *arguments, **options):
    command = list(command)
    if Path(command[0]).name == 'pg_ctl' and command[-1] == 'start':
        # Minimal CI images may not provide /var/run/postgresql. Keep the socket
        # beside this fixture's mode-0700 disposable data, never in a global path.
        socket_directory = Path(command[command.index('-D') + 1]).parent
        command[command.index('-o') + 1] += " -c unix_socket_directories=''" if _local else f' -k {socket_directory}'
    if _local and Path(command[0]).name == 'pg_ctl' and command[-1] == 'stop':
        # Do not let the underlying harness delete a cluster after a failed stop.
        command[-1:-1] = ['-t', '15']
        options.update(check=True, timeout=20)
    if Path(command[0]).name == 'initdb':
        command.extend(['-U', 'postriff_test'])
        if _local:
            _local_clusters.add(Path(command[command.index('-D') + 1]))
    if os.geteuid() == 0 and Path(command[0]).name in ('initdb', 'pg_ctl'):
        owner = pwd.getpwnam('postgres')
        if owner.pw_uid == 0:
            raise RuntimeError('Disposable PostgreSQL requires an unprivileged OS account.')
        directory = Path(command[command.index('-D') + 1]).parent
        if Path(command[0]).name == 'initdb':
            os.chown(directory, owner.pw_uid, owner.pw_gid)
        options.update(user=owner.pw_uid, group=owner.pw_gid, extra_groups=[], cwd=directory)
    return _run(command, *arguments, **options)
harness.subprocess = type('FixtureProcess', (), {'run': staticmethod(fixture_run), 'DEVNULL': subprocess.DEVNULL,
    'CalledProcessError': subprocess.CalledProcessError, 'TimeoutExpired': subprocess.TimeoutExpired})
def cleanup_local_clusters():
    """Also stop a cluster when startup/migration fails before harness.main installs its cleanup."""
    for data in _local_clusters:
        parent = data.parent
        if not parent.exists():
            continue
        if (not parent.name.startswith('postriff-dev-pg-') or parent.is_symlink()
                or not parent.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
                or parent.stat().st_uid != os.geteuid()):
            raise RuntimeError('Refusing cleanup outside this local fixture temporary cluster')
        if (data / 'postmaster.pid').exists():
            result = _run([str(harness.PG / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-t', '15', '-w', 'stop'],
                          stdout=subprocess.DEVNULL, timeout=20)
            if result.returncode:
                raise RuntimeError('Local PostgreSQL cleanup failed; cluster retained at ' + str(data))
        shutil.rmtree(parent)


class BrowserScopeFixtureProvider(harness.DevProvider):
    """A named fake provider grant, only in this disposable browser fixture.

    Ordinary dev codes still report unknown scopes, which OAuth must fail closed.
    No provider request or posting action is performed by this grant.
    """
    def exchange(self, code, verifier, redirect):
        grant = super().exchange(code, verifier, redirect)
        if code == "browser-publish-scope-fixture":
            grant["scopes"] = list(self.capability_scopes("publish"))
        return grant


harness.DevProvider = BrowserScopeFixtureProvider


if __name__ == '__main__':
    mode = os.environ.get('BRAND_BRAIN_EXECUTION', 'cloud')
    if mode == 'local':
        if sys.platform != 'darwin' or os.geteuid() == 0:
            raise SystemExit('Local browser database fixture requires unprivileged macOS.')
    elif mode != 'cloud' or sys.platform != 'linux' or os.environ.get('CI', '').lower() not in ('1', 'true'):
        raise SystemExit('Default browser database fixture requires cloud Linux CI; opt in explicitly for local macOS.')
    print(json.dumps({'execution': ('LOCAL' if _local else 'CLOUD') + ' SYNTHETIC BRAND BRAIN APPLICATION FIXTURE',
                      'realProviderE2E': False, 'credentials': 'generated test strings only'}), flush=True)
    if _local:
        def stop(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            harness.main()
        finally:
            cleanup_local_clusters()
    else:
        harness.main()
