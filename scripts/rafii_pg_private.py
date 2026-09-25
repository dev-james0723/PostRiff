#!/usr/bin/env python3
"""Run tests/phase2 PostgreSQL scripts like scripts/postriff_pg_suite.py, but on a private port, so a suite another
session is running on 55438 is never touched.

    PYTHONPATH=src python scripts/rafii_pg_private.py [script-stem ...]      # e.g. postgres_coworker
    RAFII_PG_PORT=55738 (default) · POSTRIFF_PG_BIN=/opt/homebrew/opt/postgresql@17/bin (default)

The repository is mirrored into a temporary directory: `tests/` and `docs/` are copied (the port is rewritten in the
copied tests), everything else is a symlink. Suites that write evidence files therefore write into the throwaway
mirror, never over another session's committed evidence. To keep the coworker evidence, pass an absolute path:
`RAFII_COWORKER_EVIDENCE=$PWD/docs/design/site-agent/adaptive-social-coworker/evidence/pg-coworker.json`.
Each script gets its own disposable database (initdb, then stop), as in postriff_pg_suite.py.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PORT = os.environ.get("RAFII_PG_PORT", "55738")
PG = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
COPIED = ("tests", "docs")


def mirror(base):
    base.mkdir(parents=True)
    for entry in REPO.iterdir():
        if entry.name in COPIED + (".git",):
            continue
        (base / entry.name).symlink_to(entry)
    for name in COPIED:
        shutil.copytree(REPO / name, base / name, ignore=shutil.ignore_patterns("__pycache__"), symlinks=True)
    for path in (base / "tests").rglob("*"):
        if path.is_file() and path.suffix in (".py", ".sql"):
            text = path.read_text()
            if "55438" in text:
                path.write_text(text.replace("55438", PORT))
    return base


def main(names):
    os.environ.update({"LC_ALL": "C", "POSTRIFF_RESEARCH": "0", "POSTRIFF_LOCAL_CLI": "0"})
    with tempfile.TemporaryDirectory(prefix="rafii-pg-mirror-") as tmp:
        base = mirror(Path(tmp) / "repo")
        # Same grouping as postriff_pg_suite.py: these two run inside other scripts' databases.
        scripts = [p for p in sorted((base / "tests/phase2").glob("*.py")) if p.name not in ("postgres_repository.py", "postgres_safety.py")]
        if names:
            scripts = [p for p in scripts if p.stem in names]
        results = []
        for script in scripts:
            with tempfile.TemporaryDirectory(prefix="rafii-pg-") as ptmp:
                data = Path(ptmp) / "data"
                subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
                subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(Path(ptmp) / "pg.log"), "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start"],
                               check=True, stdout=subprocess.DEVNULL)
                try:
                    subprocess.run([str(PG / "psql"), f"host=127.0.0.1 port={PORT} dbname=postgres", "-v", "ON_ERROR_STOP=1", "-q", "-f", str(base / "tests/phase2/rls.sql")],
                                   check=True, stdout=subprocess.DEVNULL)
                    group = [script]
                    if script.name == "postgres_plan_guards.py":
                        group.insert(0, base / "tests/phase2/postgres_repository.py")
                    if script.name == "postgres_instagram_lifecycle.py":
                        group.append(base / "tests/phase2/postgres_safety.py")
                    for path in group:
                        print("RUN " + str(path.relative_to(base)), flush=True)
                        started = time.monotonic()
                        env = {**os.environ, "PYTHONPATH": f"{base}/src:{base}/tests", "POSTRIFF_TEST_DSN": f"host=127.0.0.1 port={PORT} dbname=postgres"}
                        outcome = subprocess.run([sys.executable, str(path)], cwd=base, env=env)
                        results.append({"script": str(path.relative_to(base)), "exitCode": outcome.returncode, "seconds": round(time.monotonic() - started, 2)})
                finally:
                    subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True, stdout=subprocess.DEVNULL)
        print(json.dumps({"execution": f"local disposable PostgreSQL on port {PORT}; mirrored repository; synthetic external services", "results": results}), flush=True)
        return int(any(r["exitCode"] for r in results))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
