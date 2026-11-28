"""Run the video WSGI integration using an existing PGlite package. No server or network.

This optional sequential QA driver exercises SQL under a single embedded engine. Use the
ordinary postgres_creative_video suite for psycopg, connection isolation and native PostgreSQL.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from contextlib import contextmanager

from postgres_creative_video import run, FOUNDER_TEST_PREREQUISITES


class Engine:
    def __init__(self, node, package):
        self.process = subprocess.Popen(
            [node, Path(__file__).with_suffix(".mjs"), package], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )

    def query(self, sql, params=(), *, script=False):
        self.process.stdin.write(json.dumps({"sql": sql, "params": params, "script": script}, default=str) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Embedded PostgreSQL exited before responding.")
        reply = json.loads(line)
        if "error" in reply:
            message = f"PostgreSQL {reply.get('code')}: {reply['error']}"
            print(message, file=sys.stderr, flush=True)
            raise RuntimeError(message)
        return reply

    @contextmanager
    def connect(self):
        self.query("BEGIN")
        try:
            yield Connection(self)
        except BaseException:
            self.query("ROLLBACK")
            raise
        else:
            self.query("COMMIT")

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=15)
        self.process.stdout.close()
        if self.process.returncode:
            raise RuntimeError(f"Embedded PostgreSQL exited with status {self.process.returncode}.")


class Cursor:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        indexes = iter(range(1, len(params) + 1))
        reply = self.engine.query(re.sub("%s", lambda _: f"${next(indexes)}", sql), params)
        self.rows = iter(reply["rows"])
        self.rowcount = reply["count"]
        return self

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)


class Connection:
    def __init__(self, engine):
        self.engine = engine

    def cursor(self):
        return Cursor(self.engine)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--pglite", type=Path, required=True)
    args.add_argument("--node", default="node")
    args.add_argument("--receipt", type=Path)
    args.add_argument("--sample-export", type=Path, help="Write the independently composed end-to-end export")
    options = args.parse_args()
    engine = Engine(options.node, options.pglite.resolve())
    try:
        harness = Path(__file__).with_name("rls.sql")
        sql = harness.read_text()
        engine.query(sql.split("\\ir", 1)[0].split("\n", 1)[1], script=True)
        imports = re.findall(r"^\\ir (.+)$", sql, re.MULTILINE)
        # The native test suite applies this optional credit policy after the shared fixture migrations.
        imports.append("../../migrations/postriff/020_credit_quotes.sql")
        for name in imports:
            engine.query((harness.parent / name).read_text(), script=True)
        engine.query(FOUNDER_TEST_PREREQUISITES, script=True)
        engine.query((harness.parent / "../../migrations/postriff/133_founder_creative_video.sql").read_text(), script=True)
        imports.append("../../migrations/postriff/133_founder_creative_video.sql")
        version = engine.query("SELECT version()")["rows"][0][0]
        print(f"{version} with {len(imports)} Rafii migration imports", flush=True)
        result = {**run(engine.connect, sample_export=options.sample_export), "engine": version, "migrationImports": len(imports)}
        if options.receipt:
            options.receipt.write_text(json.dumps(result, indent=2) + "\n")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
