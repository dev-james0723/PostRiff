"""Run Substack regressions against a fresh, private PostgreSQL cluster.

Example (no application credentials or network listener):
  python scripts/substack_pg_test.py --pg-bin /path/to/postgres/bin \
      --python-target /path/to/pinned/test/dependencies --output /tmp/result.json

Supply real PostgreSQL binaries and the repository-pinned psycopg driver. This
runner does not install packages, reuse a running server, read an application
DSN, or start Docker. PostgreSQL runs under an unprivileged OS identity, with a
unique Unix socket and no TCP listener. Only its own cluster is stopped.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import pwd
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_SCRIPT = ROOT / "tests/phase2/postgres_substack.py"
CLUSTER_PREFIX = "rafii-substack-pg-test-"
DATABASE_USER = "rafii_substack_test"
FIXTURES = (
    ROOT / "tests/phase2/rls.sql",
    ROOT / "migrations/postriff/016_api_tokens.sql",
    ROOT / "migrations/postriff/062_founder_admin_actions.sql",
)


def source_hashes():
    paths = [TEST_SCRIPT, Path(__file__).resolve(), *FIXTURES]
    paths.extend(ROOT / "src/postriff_phase2" / name for name in (
        "substack.py", "substack_service.py", "hosted.py", "hosted_worker.py",
        "api_tokens.py", "permissions.py", "operator_actions.py", "substack_notifications.py",
        "notifications/service.py", "notifications/store.py", "notifications/planner.py", "notifications/catalog.py",
    ))
    paths.extend(sorted((ROOT / "migrations/postriff").glob("*.sql")))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


@contextmanager
def private_cluster_directory():
    cluster = Path(tempfile.mkdtemp(prefix=CLUSTER_PREFIX, dir="/tmp"))
    try:
        yield cluster
    finally:
        if not (cluster / ".preserve-running").exists():
            shutil.rmtree(cluster)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--python-target", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    pg = args.pg_bin.resolve()
    if not all((pg / tool).is_file() for tool in ("postgres", "initdb", "pg_ctl", "psql")):
        parser.error("--pg-bin must contain postgres, initdb, pg_ctl, and psql")
    if not TEST_SCRIPT.is_file():
        parser.error("tests/phase2/postgres_substack.py is required")
    owner = None
    if os.geteuid() == 0:
        for name in ("postgres", "nobody"):
            try:
                candidate = pwd.getpwnam(name)
            except KeyError:
                continue
            if candidate.pw_uid != 0:
                owner = candidate
                break
        if owner is None:
            parser.error("root needs an existing unprivileged postgres or nobody OS identity")

    # Do not inherit production DSNs, provider tokens, cloud-writer settings,
    # PostgreSQL service files, or local client credential configuration.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PGPASSFILE": os.devnull,
        "PGSERVICEFILE": os.devnull,
        "PGSYSCONFDIR": "/nonexistent",
        "POSTRIFF_RESEARCH": "0",
        "RAFII_AGENT_PERMISSIONS_MODE": "off",
        "RAFII_DEVICE_TRUST_V2": "0",
        "RAFII_SECURITY_INCIDENT_HOLD": "0",
    }
    paths = [str(ROOT / "src")]
    if args.python_target:
        paths.insert(0, str(args.python_target.resolve()))
    env["PYTHONPATH"] = os.pathsep.join(paths)
    version = subprocess.run(
        [str(pg / "postgres"), "--version"], check=True,
        capture_output=True, text=True, env=env,
    ).stdout.strip()
    result = {
        "status": "fail", "execution": "disposable-scratch-postgresql",
        "postgresVersion": version, "tcpListening": False,
        "script": str(TEST_SCRIPT.relative_to(ROOT)), "clusterStopped": False,
        "liveProviderAcceptance": False,
        "acceptanceLimitations": [
            "Sessions, users, feeds, and notification transports are synthetic; PostgreSQL, RLS, locks, memberships, audit, and notification outbox rows are real.",
            "No Substack OAuth, account eligibility, live provider read/write, email delivery, or publishing acceptance was exercised.",
            "The isolated PostgreSQL version below does not establish compatibility with the deployed Supabase PostgreSQL version.",
            "The canonical production database was not connected to or modified by this runner.",
        ],
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "fixtures": [str(path.relative_to(ROOT)) for path in FIXTURES],
        "sourceSHA256": source_hashes(),
    }
    with private_cluster_directory() as cluster:
        data, socket_dir, log = cluster / "data", cluster / "socket", cluster / "postgres.log"
        socket_dir.mkdir(mode=0o700)
        marker = cluster / ".rafii-substack-disposable"
        marker.write_text(str(data) + "\n", encoding="utf-8")
        empty_auth = cluster / "empty-client-auth"
        empty_auth.touch(mode=0o600)
        port = 10000 + secrets.randbelow(50000)
        dsn = f"host={socket_dir} port={port} dbname=postgres user={DATABASE_USER}"
        env.update({
            "POSTRIFF_TEST_DSN": dsn,
            "RAFII_SUBSTACK_TEST_CLUSTER_DIR": str(cluster),
            "PGHOST": str(socket_dir), "PGPORT": str(port),
            "PGDATABASE": "postgres", "PGUSER": DATABASE_USER,
            "PGPASSFILE": str(empty_auth), "PGSERVICEFILE": str(empty_auth),
        })
        server_options = {"cwd": str(cluster), "env": env}
        if owner:
            for owned in (cluster, socket_dir, marker, empty_auth):
                os.chown(owned, owner.pw_uid, owner.pw_gid)
            server_options.update(user=owner.pw_uid, group=owner.pw_gid, extra_groups=[])
        attempted_start = False
        try:
            subprocess.run(
                [str(pg / "initdb"), "-D", str(data), "-U", DATABASE_USER,
                 "--auth-local=trust", "--auth-host=reject", "--no-locale", "-E", "UTF8"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, **server_options,
            )
            attempted_start = True
            subprocess.run(
                [str(pg / "pg_ctl"), "-D", str(data), "-l", str(log),
                 "-o", f"-h '' -k {socket_dir} -p {port} -c shared_buffers=16MB -c max_connections=12",
                 "-t", "30", "-w", "start"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, **server_options,
            )
            for fixture in FIXTURES:
                subprocess.run(
                    [str(pg / "psql"), "-X", dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(fixture)],
                    check=True, capture_output=True, text=True, cwd=ROOT, env=env,
                )
            completed = subprocess.run(
                [sys.executable, str(TEST_SCRIPT)], capture_output=True,
                text=True, cwd=ROOT, env=env,
            )
            result.update(exit=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
            result["status"] = "pass" if completed.returncode == 0 else "fail"
            if completed.returncode == 0:
                result["testSummary"] = json.loads(completed.stdout.strip().splitlines()[-1])
        except subprocess.CalledProcessError as error:
            result.update(
                cause="fixture_or_runtime_failed", exit=error.returncode,
                stdout=error.stdout or "", stderr=error.stderr or "",
            )
        finally:
            if attempted_start:
                stop = subprocess.run(
                    [str(pg / "pg_ctl"), "-D", str(data), "-m", "fast", "-t", "30", "-w", "stop"],
                    capture_output=True, text=True, **server_options,
                )
                if stop.returncode:
                    running = subprocess.run(
                        [str(pg / "pg_ctl"), "-D", str(data), "status"],
                        capture_output=True, text=True, **server_options,
                    )
                    if running.returncode == 0:
                        stop = subprocess.run(
                            [str(pg / "pg_ctl"), "-D", str(data), "-m", "immediate", "-t", "30", "-w", "stop"],
                            capture_output=True, text=True, **server_options,
                        )
                        if stop.returncode:
                            result["status"] = "fail"
                            result["cleanupError"] = stop.stderr[-2000:]
                            # Do not remove a directory belonging to a live server.
                            (cluster / ".preserve-running").touch()
                            raise RuntimeError("The disposable PostgreSQL cluster did not stop")
                result["clusterStopped"] = True
            if log.exists() and result["status"] != "pass":
                result["postgresLogTail"] = log.read_text(errors="replace")[-8000:]
    result["sourceUnchangedDuringRun"] = result["sourceSHA256"] == source_hashes()
    result["finishedAt"] = datetime.now(timezone.utc).isoformat()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(main())
