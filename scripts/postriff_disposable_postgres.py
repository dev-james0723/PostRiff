"""Start a disposable PostgreSQL, load the RLS harness, run scripts, stop.

Usage:
  python scripts/postriff_disposable_postgres.py tests/phase2/postgres_repository.py tests/phase2/postgres_safety.py

Binds 127.0.0.1:55438 so the existing phase-2 scripts' DSN works unchanged.
Never reads application credentials; the data directory is deleted on exit.
Linux CI supplies POSTRIFF_PG_BIN; root drops server privileges to postgres.
"""
from __future__ import annotations

import json
import os
import pwd
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PG = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
PORT = 55438
USER = "postriff_test"
# macOS: without a fixed C locale the postmaster aborts with "became multithreaded during startup".
os.environ.setdefault("LC_ALL", "C")


def main(scripts: list[str]) -> int:
    if not scripts or not all((ROOT / script).is_file() for script in scripts):
        print(json.dumps({"status": "validation_unavailable", "cause": "existing regression scripts are required"}))
        return 3
    if not all((PG / tool).is_file() for tool in ("initdb", "pg_ctl", "psql", "postgres")):
        print(json.dumps({"status": "validation_unavailable", "cause": f"{PG}/initdb not found"}))
        return 3
    owner = None
    if os.geteuid() == 0:
        try:
            owner = pwd.getpwnam("postgres")
            if owner.pw_uid == 0:
                raise KeyError("postgres must be unprivileged")
        except KeyError:
            print(json.dumps({"status": "validation_unavailable", "cause": "root requires an unprivileged postgres OS account"}))
            return 3
    # Refuse a collision before loading any fixture data into a database.
    try:
        with socket.socket() as probe:
            # Closed fixture connections can leave TIME_WAIT after pg_ctl -w stop.
            # Reuse permits those ports, while an active listener still conflicts;
            # SO_REUSEPORT is deliberately not enabled.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", PORT))
    except OSError:
        print(json.dumps({"status": "validation_unavailable", "cause": f"loopback port {PORT} is already in use"}))
        return 3
    version = subprocess.run([str(PG / "postgres"), "--version"], check=True, capture_output=True, text=True).stdout.strip()
    dsn = f"host=127.0.0.1 port={PORT} dbname=postgres user={USER}"
    test_env = {**os.environ, "PGUSER": USER, "PGHOST": "127.0.0.1", "PGPORT": str(PORT), "PGDATABASE": "postgres",
                "PGPASSFILE": os.devnull, "PGSERVICEFILE": os.devnull, "POSTRIFF_TEST_DSN": dsn, "POSTRIFF_RESEARCH": "0"}
    results = []
    # Runner temp roots may be private to root; /tmp lets the dropped server UID
    # traverse to its own mode-0700 cluster directory without opening the venv.
    with tempfile.TemporaryDirectory(prefix="postriff-cw-pg-", dir="/tmp" if owner else None) as tmp:
        data, log = Path(tmp) / "data", Path(tmp) / "postgres.log"
        server_options = {"cwd": tmp, "env": test_env}
        if owner:
            os.chown(tmp, owner.pw_uid, owner.pw_gid)
            server_options.update(user=owner.pw_uid, group=owner.pw_gid, extra_groups=[])
        attempted_start = False
        try:
            # UTF8 explicitly: --no-locale alone yields SQL_ASCII and rejects unicode drafts.
            subprocess.run([str(PG / "initdb"), "-D", str(data), "-U", USER, "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL, **server_options)
            attempted_start = True
            subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(log), "-o", f"-h 127.0.0.1 -p {PORT} -c unix_socket_directories=''", "-t", "30", "-w", "start"], check=True, stdout=subprocess.DEVNULL, **server_options)
            subprocess.run([str(PG / "psql"), "-X", dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / "tests/phase2/rls.sql")], check=True, stdout=subprocess.DEVNULL, env=test_env)
            for script in scripts:
                # One cluster, sequential processes, synthetic transports and research disabled.
                run = subprocess.run([sys.executable, str(ROOT / script)], capture_output=True, text=True, env=test_env)
                results.append({"script": script, "exit": run.returncode, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]})
                print(f"== {script} exit={run.returncode}")
                print(run.stdout[-4000:])
                if run.returncode:
                    print(run.stderr[-4000:], file=sys.stderr)
        finally:
            if attempted_start:
                stopped = subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-t", "30", "-w", "stop"], stdout=subprocess.DEVNULL, **server_options)
                if stopped.returncode:
                    running = subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **server_options)
                    if running.returncode == 0:
                        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "immediate", "-t", "30", "-w", "stop"], check=True, stdout=subprocess.DEVNULL, **server_options)
    failed = [r["script"] for r in results if r["exit"]]
    execution = "disposable-cloud-postgres" if sys.platform.startswith("linux") and os.environ.get("CI", "").lower() in ("1", "true") else "disposable-local-postgres"
    print(json.dumps({"status": "pass" if not failed else "fail", "execution": execution, "postgresVersion": version, "failed": failed, "scripts": scripts}))
    return 1 if failed else 0


if __name__ == "__main__":
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)  # Run cluster teardown on CI cancellation.
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main(sys.argv[1:]))
