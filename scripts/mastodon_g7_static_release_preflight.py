"""HISTORICAL G7 OFFLINE source + checksum ledger forensic comparison.

READ-ONLY on project files and an operator-provided JSON snapshot of the
Production custom migration ledger. No network, API, credentials, or database
write path. A PASS does NOT authorize remote migration or public deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REF = "buoyhkbodnhzngaotoel"
EXACT_SQL = {
    "131_mastodon_management.sql": "c85e2d27f79947692a1bf28a7087fcbe7b0d3ea9d3c57e2e0fe2dd654bacf694",
    "132_mastodon_native_metrics.sql": "c3a887b379958bdb32282120f6b9dc5515b02882da279898453fedb8f7886d3b",
    "133_mastodon_connection_health.sql": "eeae6a4f48fb7616ce168f672c05d6ba7e169aa91951c17fc1c4c187fb437905",
}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def examine(ledger_path: pathlib.Path) -> dict:
    snapshot = json.loads(ledger_path.read_text())
    assert snapshot.get("project_ref") == PROJECT_REF, "Wrong Production project"
    assert snapshot.get("source", "").startswith("read-only SELECT"), "Unverified ledger source"
    items = snapshot.get("rows")
    assert isinstance(items, list) and len(items) == 62, "Expected exact 62 applied migrations"
    assert all(
        isinstance(x, dict)
        and re.fullmatch(r"[0-9]{3}_[A-Za-z0-9_]+\.sql", str(x.get("name", "")))
        and re.fullmatch(r"[0-9a-f]{64}", str(x.get("sha256", "")))
        for x in items
    ), "Bad or unverified custom ledger input"
    ledger = {x["name"]: x["sha256"] for x in items}
    assert len(ledger) == len(items), "Duplicate applied migrations"
    directory = ROOT / "migrations" / "postriff"
    migrations = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    prefixes: set[str] = set()
    for path in migrations:
        prefix = path.name[:3]
        assert prefix not in prefixes, f"Duplicate source migration number: {prefix}"
        prefixes.add(prefix)
    missing, drift = [], []
    for name, digest in ledger.items():
        path = directory / name
        if not path.is_file():
            missing.append(name)
        elif sha256(path) != digest:
            drift.append(name)
    legacy = ROOT / 'tests/fixtures/mastodon_legacy_g7_20261017'
    sql = {}
    for name, digest in EXACT_SQL.items():
        path = legacy / name
        assert path.is_file(), f"Missing historical unapplied source: {name}"
        assert sha256(path) == digest, f"Mastodon migration drift: {name}"
        assert name not in ledger, f"Migration already applied in selected ledger: {name}"
        sql[name] = digest
    app_sql = (legacy / "131_mastodon_management.sql").read_text().lower()
    health_sql = (legacy / "133_mastodon_connection_health.sql").read_text().lower()
    assert app_sql.count("force row level security") >= 2
    assert health_sql.count("force row level security") >= 1
    assert "revoke all" in app_sql and "revoke all" in health_sql
    assert "service_role" in app_sql and "service_role" in health_sql
    result = {
        "execution": "historical_g7_offline_forensic_only",
        "current_acceptance": False,
        "auto_discovery_excluded": True,
        "canonical_production_ref": PROJECT_REF,
        "applied_migrations_in_snapshot": len(items),
        "applied_source_matches": len(items) - len(missing) - len(drift),
        "missing_from_source": missing,
        "applied_hash_mismatch": drift,
        "historical_unapplied_mastodon_sources": sql,
        "new_tables_force_rls_and_service_only_source": True,
        "independent_restore_verified": False,
        "real_oauth_verified": False,
        "production_migration_authorized": False,
        "public_connect_go": False,
    }
    assert not missing and not drift, "Historical Production SQL mismatch; STOP"
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--historical-g7-only", action="store_true", help="Acknowledge retired source comparison; never current acceptance")
    p.add_argument("--ledger", required=True, type=pathlib.Path)
    p.add_argument("--output", type=pathlib.Path, default=None)
    args = p.parse_args()
    if not args.historical_g7_only:
        p.error('Retired G7 source only: --historical-g7-only is required; not current release acceptance')
    try:
        result = examine(args.ledger)
    except (AssertionError, OSError, json.JSONDecodeError, KeyError) as err:
        print(json.dumps({"result": "FAIL_CLOSED", "error": str(err)[:240]}))
        return 2
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
