"""Pinned additive caller-identity migration runner. Default mode is read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import psycopg


ROOT = Path(__file__).resolve().parents[3]
SQL_PATH = ROOT / "migrations/postriff/045_phone_caller_identity.sql"
SQL_SHA = "1d672f5df62ae9209671d1b8505fe3729a6e6713e22a840b8db8edb0f76e1014"
PROJECT = "buoyhkbodnhzngaotoel"
VERCEL_PROJECT = "prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L"
TABLES = ("pr_phone_trusted_callers", "pr_phone_auth_challenges")

EXPECTED_COLUMNS = {
    TABLES[0]: {
        "id": ("uuid", "NO", "gen_random_uuid()"),
        "user_id": ("uuid", "NO", None),
        "workspace_id": ("uuid", "NO", None),
        "caller_hash": ("text", "NO", None),
        "created_from_code_id": ("uuid", "YES", None),
        "verified_at": ("timestamp with time zone", "NO", None),
        "last_used_at": ("timestamp with time zone", "YES", None),
        "revoked_at": ("timestamp with time zone", "YES", None),
        "suppressed_until": ("timestamp with time zone", "YES", None),
        "created_at": ("timestamp with time zone", "NO", "now()"),
        "updated_at": ("timestamp with time zone", "NO", "now()"),
    },
    TABLES[1]: {
        "id": ("uuid", "NO", "gen_random_uuid()"),
        "provider_call_ref": ("text", "NO", None),
        "trusted_caller_id": ("uuid", "NO", None),
        "user_id": ("uuid", "NO", None),
        "workspace_id": ("uuid", "NO", None),
        "caller_hash": ("text", "NO", None),
        "state": ("text", "NO", "'pending'::text"),
        "created_at": ("timestamp with time zone", "NO", None),
        "expires_at": ("timestamp with time zone", "NO", None),
        "ceremony_attempts": ("integer", "NO", "0"),
        "factor_id": ("uuid", "YES", None),
        "factor_challenge_id": ("uuid", "YES", None),
        "ceremony_session_id": ("text", "YES", None),
        "ceremony_started_at": ("timestamp with time zone", "YES", None),
        "verification_used": ("boolean", "NO", "false"),
        "approved_at": ("timestamp with time zone", "YES", None),
        "consumed_at": ("timestamp with time zone", "YES", None),
        "approved_session_id": ("text", "YES", None),
        "approved_factor_kind": ("text", "YES", None),
        "call_id": ("uuid", "YES", None),
        "maximum_millicredits": ("bigint", "YES", None),
        "use_available_credits": ("boolean", "NO", "false"),
    },
}

CONSTRAINT_FRAGMENTS = {
    TABLES[0]: (
        "PRIMARY KEY (id)",
        "UNIQUE (user_id, workspace_id, caller_hash)",
        "CHECK ((caller_hash ~ '^[0-9a-f]{64}$'::text))",
        "FOREIGN KEY (user_id) REFERENCES pr_profiles(user_id) ON DELETE CASCADE",
        "FOREIGN KEY (workspace_id) REFERENCES pr_workspaces(id) ON DELETE CASCADE",
        "FOREIGN KEY (created_from_code_id) REFERENCES pr_phone_inbound_codes(id) ON DELETE SET NULL",
    ),
    TABLES[1]: (
        "PRIMARY KEY (id)",
        "UNIQUE (provider_call_ref)",
        "UNIQUE (factor_challenge_id)",
        "UNIQUE (call_id)",
        "CHECK ((caller_hash ~ '^[0-9a-f]{64}$'::text))",
        "FOREIGN KEY (provider_call_ref) REFERENCES pr_phone_inbound_sessions(provider_call_ref) ON DELETE CASCADE",
        "FOREIGN KEY (trusted_caller_id) REFERENCES pr_phone_trusted_callers(id) ON DELETE CASCADE",
        "FOREIGN KEY (user_id) REFERENCES pr_profiles(user_id) ON DELETE CASCADE",
        "FOREIGN KEY (workspace_id) REFERENCES pr_workspaces(id) ON DELETE CASCADE",
        "FOREIGN KEY (call_id) REFERENCES pr_phone_calls(id) ON DELETE SET NULL",
    ),
}


def say(**data: object) -> None:
    print("CALLER-IDENTITY-045: " + json.dumps(data, sort_keys=True), flush=True)


def presence(db: psycopg.Connection) -> tuple[bool, bool, bool]:
    tables = tuple(
        bool(db.execute("SELECT to_regclass(%s)", ("public." + table,)).fetchone()[0])
        for table in TABLES
    )
    pairing = bool(
        db.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='pr_phone_inbound_sessions' AND column_name='pairing_started_at'"
        ).fetchone()
    )
    return tables + (pairing,)


def verify(db: psycopg.Connection) -> None:
    for table in TABLES:
        columns = {
            row[0]: (row[1], row[2], row[3])
            for row in db.execute(
                "SELECT column_name,data_type,is_nullable,column_default "
                "FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
                (table,),
            )
        }
        assert columns == EXPECTED_COLUMNS[table], f"unexpected columns for {table}"

        flags = db.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
            ("public." + table,),
        ).fetchone()
        assert flags == (True, True), f"RLS is not forced for {table}"

        policies = list(
            db.execute(
                "SELECT policyname,roles::text,cmd,qual,with_check FROM pg_policies "
                "WHERE schemaname='public' AND tablename=%s ORDER BY policyname",
                (table,),
            )
        )
        assert policies == [("service_only", "{service_role}", "ALL", "true", "true")]

        grants = {
            role: tuple(
                db.execute(
                    "SELECT has_table_privilege(%s,%s,%s)",
                    (role, "public." + table, privilege),
                ).fetchone()[0]
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
            )
            for role in ("anon", "authenticated", "service_role")
        }
        assert grants["anon"] == (False,) * 4 and grants["authenticated"] == (False,) * 4
        assert grants["service_role"] == (True,) * 4

        constraints = {
            row[0]
            for row in db.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid=%s::regclass",
                ("public." + table,),
            )
        }
        for fragment in CONSTRAINT_FRAGMENTS[table]:
            assert fragment in constraints, f"missing constraint on {table}: {fragment}"

    indexes = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' "
            "AND tablename=ANY(%s) ORDER BY indexname",
            (list(TABLES),),
        )
    }
    assert "WHERE (revoked_at IS NULL)" in indexes["pr_phone_trusted_caller_lookup"]
    assert "(user_id, created_at DESC)" in indexes["pr_phone_auth_user_time"]

    pairing = db.execute(
        "SELECT data_type,is_nullable,column_default FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='pr_phone_inbound_sessions' "
        "AND column_name='pairing_started_at'"
    ).fetchone()
    assert pairing == ("timestamp with time zone", "YES", None)


def run(db: psycopg.Connection, sql: str, *, apply: bool = False) -> None:
    with db.transaction():
        if apply:
            db.execute("SET LOCAL lock_timeout='10s'")
            db.execute("SET LOCAL statement_timeout='60s'")
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        else:
            db.execute("SET TRANSACTION READ ONLY")

        prerequisites = (
            "pr_profiles",
            "pr_workspaces",
            "pr_phone_inbound_codes",
            "pr_phone_inbound_sessions",
            "pr_phone_calls",
        )
        assert all(
            db.execute("SELECT to_regclass(%s) IS NOT NULL", ("public." + table,)).fetchone()[0]
            for table in prerequisites
        ), "prerequisite missing"

        before = presence(db)
        ledger = bool(
            db.execute("SELECT to_regclass('postriff_private.schema_migrations')").fetchone()[0]
        )
        say(step="before", objects=before, ledger=ledger)
        assert not any(before) or all(before), "partial 045 shape; refusing changes"

        if all(before):
            verify(db)
            say(step="verified", applied=False, already_present=True)
            return
        if not apply:
            say(step="plan", pending=[SQL_PATH.name])
            return

        db.execute(sql, prepare=False)
        verify(db)
        if ledger:
            row = db.execute(
                "SELECT sha256 FROM postriff_private.schema_migrations WHERE name=%s",
                (SQL_PATH.name,),
            ).fetchone()
            assert not row or row[0] == SQL_SHA, "ledger checksum conflict"
            if not row:
                db.execute(
                    "INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)",
                    (SQL_PATH.name, SQL_SHA),
                )
        say(step="verified", applied=True, already_present=False)
    say(step="committed", migration=SQL_PATH.name, sha256=SQL_SHA)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw = SQL_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SQL_SHA, "SQL checksum mismatch"
    dsn = os.environ["POSTRIFF_DATABASE_URL"]
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    host, user = params.get("host", ""), params.get("user", "")
    assert host == "db." + PROJECT + ".supabase.co" or (
        host.endswith(".pooler.supabase.com") and user == "postgres." + PROJECT
    ), "unexpected database target"
    assert os.environ.get("VERCEL_ENV") == "production", "runner requires production environment"
    assert os.environ.get("VERCEL_PROJECT_ID") == VERCEL_PROJECT, "unexpected Vercel project"
    say(step="target", project=PROJECT, mode="apply" if args.apply else "read-only")
    with psycopg.connect(dsn, autocommit=True, prepare_threshold=None, connect_timeout=15) as db:
        run(db, raw.decode(), apply=args.apply)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        say(step="error", error_type=type(error).__name__)
        sys.exit(1)
