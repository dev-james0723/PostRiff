#!/usr/bin/env python3
"""Fleet growth report (adaptive coworker spec §23; ROLLOUT step 7): weekly return, trial → paid and 30/60/90-day paid
retention per positioning arm, and experiment exposure. Read-only; counts and rates only, no per-person data.

    POSTRIFF_DATABASE_URL=postgresql://... PYTHONPATH=src python scripts/rafii_growth_report.py

It refuses a non-local database unless --remote is given, so a local run never reads production by accident.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", action="store_true", help="allow a non-local database (read-only queries)")
    args = parser.parse_args()
    url = os.environ.get("POSTRIFF_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set POSTRIFF_DATABASE_URL.")
    if urlparse(url).hostname not in ("127.0.0.1", "localhost", "::1") and not args.remote:
        sys.exit("Refusing a non-local database without --remote.")
    import psycopg
    from postriff_phase2.coworker import growth
    with psycopg.connect(url) as db, db.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        print(json.dumps(growth.fleet(cur), indent=2, default=str))


if __name__ == "__main__":
    main()
