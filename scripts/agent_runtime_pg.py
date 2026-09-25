"""Run PostgreSQL test scripts on a private disposable cluster at a chosen port (default 55621).

Same isolation as scripts/postriff_pg_suite.py (a new cluster per script, tests/phase2/rls.sql first), but on its own
port so it can run while the full suite (port 55438) runs elsewhere. Test scripts read POSTRIFF_PG_PORT.

    PYTHONPATH=src:tests python scripts/agent_runtime_pg.py tests/phase2/postgres_agent_runtime.py [--port 55621]
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PG = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))


def main(argv):
    port = "55621"
    if "--port" in argv:
        index = argv.index("--port")
        port = argv[index + 1]
        argv = argv[:index] + argv[index + 2:]
    scripts = [Path(a) for a in argv] or sorted((ROOT / "tests/phase2").glob("postgres_agent_runtime*.py"))
    if not (PG / "initdb").is_file():
        print(json.dumps({"status": "VALIDATION_UNAVAILABLE", "reason": f"{PG}/initdb missing; set POSTRIFF_PG_BIN"}))
        return 3
    env = {**os.environ, "LC_ALL": "C", "POSTRIFF_RESEARCH": "0", "POSTRIFF_PG_PORT": port}
    results = []
    for script in scripts:
        with tempfile.TemporaryDirectory(prefix="agent-runtime-pg-") as tmp:
            data = Path(tmp) / "data"
            subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(Path(tmp) / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
            try:
                subprocess.run([str(PG / "psql"), f"host=127.0.0.1 port={port} dbname=postgres", "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / "tests/phase2/rls.sql")],
                               check=True, stdout=subprocess.DEVNULL)
                print("RUN " + str(script), flush=True)
                started = time.monotonic()
                result = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env)
                results.append({"script": str(script), "exitCode": result.returncode, "seconds": round(time.monotonic() - started, 2)})
            finally:
                subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True, stdout=subprocess.DEVNULL)
    print(json.dumps({"execution": "local-db; synthetic external services", "port": port, "results": results}), flush=True)
    return int(any(r["exitCode"] for r in results))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
