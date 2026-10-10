"""Cloud-only real hosted API/database; synthetic identity and no paid providers."""
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import postriff_dev_hosted as harness

# Only PostgreSQL subprocesses drop OS privileges when the ephemeral CI runner
# itself is root. Python/Next remain the runner user; no project files are chowned.
_run = subprocess.run
def fixture_run(command, *arguments, **options):
    command = list(command)
    if Path(command[0]).name == 'pg_ctl' and command[-1] == 'start':
        # Minimal CI images may not provide /var/run/postgresql. Keep the socket
        # beside this fixture's mode-0700 disposable data, never in a global path.
        socket_directory = Path(command[command.index('-D') + 1]).parent
        command[command.index('-o') + 1] += f' -k {socket_directory}'
    if Path(command[0]).name == 'initdb':
        command.extend(['-U', 'postriff_test'])
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
if __name__ == '__main__':
    if sys.platform != 'linux' or os.environ.get('CI', '').lower() not in ('1', 'true'):
        raise SystemExit('Browser database fixture requires cloud Linux CI; no Mac execution.')
    print(json.dumps({'execution': 'CLOUD BRAND BRAIN APPLICATION FIXTURE', 'realProviderE2E': False, 'credentials': 'generated test strings only'}), flush=True)
    harness.main()
