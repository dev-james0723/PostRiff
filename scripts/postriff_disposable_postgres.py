"""Start a disposable local PostgreSQL, load the RLS harness, run scripts, stop.

Usage:
  python scripts/postriff_disposable_postgres.py tests/phase2/postgres_repository.py tests/phase2/postgres_safety.py

Binds 127.0.0.1:55438 so the existing phase-2 scripts' DSN works unchanged.
Never reads application credentials; the data directory is deleted on exit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PG = Path("/opt/homebrew/opt/postgresql@17/bin")
PORT = 55438
# macOS: without a fixed C locale the postmaster aborts with "became multithreaded during startup".
os.environ.setdefault("LC_ALL", "C")


def main(scripts: list[str]) -> int:
    if not (PG / "initdb").exists():
        print(json.dumps({"status": "validation_unavailable", "cause": f"{PG}/initdb not found"}))
        return 3
    results = []
    with tempfile.TemporaryDirectory(prefix="postriff-cw-pg-") as tmp:
        data, log = Path(tmp) / "data", Path(tmp) / "postgres.log"
        # UTF8 explicitly: --no-locale alone yields SQL_ASCII, which rejects unicode draft text.
        subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(log), "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
        try:
            dsn = f"host=127.0.0.1 port={PORT} dbname=postgres"
            subprocess.run([str(PG / "psql"), dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / "tests/phase2/rls.sql")], check=True, stdout=subprocess.DEVNULL)
            for script in scripts:
                # Tests never reach the web: research is off unless a run sets POSTRIFF_RESEARCH itself.
                run = subprocess.run([sys.executable, str(ROOT / script)], capture_output=True, text=True, env={**os.environ, "POSTRIFF_RESEARCH": os.environ.get("POSTRIFF_RESEARCH", "0")})
                results.append({"script": script, "exit": run.returncode, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]})
                print(f"== {script} exit={run.returncode}")
                print(run.stdout[-4000:])
                if run.returncode:
                    print(run.stderr[-4000:], file=sys.stderr)
        finally:
            subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True, stdout=subprocess.DEVNULL)
    failed = [r["script"] for r in results if r["exit"]]
    print(json.dumps({"status": "pass" if not failed else "fail", "execution": "disposable-local-postgres", "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
