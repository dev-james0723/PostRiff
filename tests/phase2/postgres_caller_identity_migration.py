"""Rehearse the pinned migration 045 runner in a disposable PostgreSQL cluster."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "migrate_045", ROOT / "docs/releases/caller-identity-045/migrate_045.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def main() -> None:
    dsn = os.environ["POSTRIFF_TEST_DSN"]
    sql = runner.SQL_PATH.read_text()
    with psycopg.connect(dsn, autocommit=True, prepare_threshold=None) as db:
        runner.verify(db)
        runner.run(db, sql, apply=False)

        db.execute("DROP TABLE public.pr_phone_auth_challenges")
        try:
            runner.run(db, sql, apply=True)
        except AssertionError as error:
            assert "partial 045 shape" in str(error)
        else:
            raise AssertionError("partial migration was not refused")

        db.execute("DROP TABLE public.pr_phone_trusted_callers")
        db.execute("ALTER TABLE public.pr_phone_inbound_sessions DROP COLUMN pairing_started_at")
        runner.run(db, sql, apply=False)
        runner.run(db, sql, apply=True)
        runner.run(db, sql, apply=True)

    print("PASS migration 045 plan, apply, shape/RLS/grants, idempotency and partial-state refusal")


if __name__ == "__main__":
    main()
