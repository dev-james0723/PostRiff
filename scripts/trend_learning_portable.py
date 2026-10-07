"""Run learning joins in a fresh socket-only PostgreSQL; never use port55438.

Uses existing installed PostgreSQL/Python dependencies. No downloads or providers.
Only this process's temporary cluster is stopped. Refuses conflicting socket/PG
service overrides; creates a distinct synthetic database and deletes it on exit.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
PG = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
PORT = "56447"
TEMP_ROOT = Path("/private/tmp" if sys.platform == "darwin" else "/tmp")


def hashes():
    paths = ["src/postriff_phase2/coworker/service.py", "src/postriff_phase2/coworker/http.py",
             "src/postriff_phase2/growth/scout_runtime.py", "src/postriff_phase2/growth/trends/learning.py", "tests/test_trend_learning.py",
             "tests/test_trend_integration.py", "src/postriff_phase2/growth/trends/store.py",
             "src/postriff_phase2/growth/trends/exposures.py", "src/postriff_phase2/coworker/performance.py",
             "migrations/postriff/040_social_trend_intelligence.sql", "scripts/trend_learning_portable.py"]
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def main():
    if any(k in os.environ for k in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGOPTIONS")):
        raise ValueError("PG service/options/hostaddr overrides forbidden")
    if (TEMP_ROOT / (".s.PGSQL." + PORT)).exists():
        raise RuntimeError("isolated test port already occupied; no existing cluster will be used")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(LC_ALL="C", POSTRIFF_RESEARCH="0", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src") + ":" + str(ROOT / "tests"))
    before = hashes()
    with tempfile.TemporaryDirectory(prefix="trend-learning-pg-", dir=TEMP_ROOT) as tmp:
        data, log = Path(tmp) / "data", Path(tmp) / "postgres.log"
        subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], env=env, check=True, stdout=subprocess.DEVNULL)
        started = False
        try:
            subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(log), "-o", f"-h '' -k {TEMP_ROOT} -p {PORT}", "-w", "start"], env=env, check=True, stdout=subprocess.DEVNULL)
            started = True
            database = "trend_pipeline_service_learning_" + uuid.uuid4().hex[:12]
            subprocess.run([str(PG / "createdb"), "-h", str(TEMP_ROOT), "-p", PORT, database], env=env, check=True)
            env["TREND_SERVICE_TEST_DSN"] = f"host={TEMP_ROOT} port={PORT} dbname={database}"
            subprocess.run([str(PG / "psql"), env["TREND_SERVICE_TEST_DSN"], "-v", "ON_ERROR_STOP=1", "-q", "-f",
                            str(ROOT / "tests/phase2/rls.sql")], env=env, check=True, stdout=subprocess.DEVNULL)
            code = """import socket,sys,unittest,json
def deny(*a,**k): raise RuntimeError('network forbidden in learning SQL tests')
socket.create_connection=deny; socket.getaddrinfo=deny
original_connect=socket.socket.connect
def connect(s,address):
    if s.family!=socket.AF_UNIX: return deny()
    return original_connect(s,address)
socket.socket.connect=connect
suite=unittest.defaultTestLoader.loadTestsFromName('test_trend_learning.LearningSQL')
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}))
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
"""
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env)
        finally:
            if started:
                subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], env=env, check=True, stdout=subprocess.DEVNULL)
    after = hashes()
    drift = [p for p in before if before[p] != after[p]]
    print(json.dumps({"execution": "actual_socket_only_disposable_PostgreSQL_synthetic_history", "port": PORT,
        "exit_code": result.returncode, "before": before, "after": after, "source_drift": drift,
        "provider_calls": 0, "model_calls": 0, "production_strategy_adopted": False,
        "synthetic_strategy_adoption_tested": True}), flush=True)
    return int(bool(result.returncode or drift))


if __name__ == "__main__":
    sys.exit(main())
