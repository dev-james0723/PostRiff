"""Rafii Account Protection v2, RAP-137: the retention worker for session-security records.

One call per cron tick of public.pr_security_retention_purge (migration 127): login events, per-session security
state and old browsers past RAFII_SECURITY_RETENTION_DAYS (default 400, never below 90) are removed for people with no
open incident and no active hold. Incidents and account controls are never removed here.

RAFII_SECURITY_RETENTION is `off` (the default: nothing runs, no statement), `dry_run` (counts what would go and
records the run, deletes nothing) or `on`. Any failure (migration 127 not applied, privilege drift) reports
`unavailable` and never breaks the cron tick.
"""
from __future__ import annotations

import json
import logging

DEFAULT_DAYS = 400
MIN_DAYS = 90
MAX_DAYS = 3650
BATCH = 5000


def mode(values=None):
    from .coworker import flags
    value = str(flags._source(values).get("RAFII_SECURITY_RETENTION", "")).strip().lower()
    return value if value in ("dry_run", "on") else "off"


def days(values=None):
    from .coworker import flags
    raw = str(flags._source(values).get("RAFII_SECURITY_RETENTION_DAYS", "") or "").strip()
    return min(MAX_DAYS, max(MIN_DAYS, int(raw))) if raw.isdigit() else DEFAULT_DAYS


def run(connection_factory, values=None, dry_run=None):
    """{"status": "off"} unless enabled; otherwise the purge's counts. `dry_run` overrides the mode (tests, operators)."""
    selected = mode(values)
    if selected == "off" and dry_run is None:
        return {"status": "off"}
    dry = selected != "on" if dry_run is None else bool(dry_run)
    try:
        with connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT public.pr_security_retention_purge(%s,%s,%s)", (days(values), dry, BATCH))
            counts = cur.fetchone()[0]
    except Exception as error:  # noqa: BLE001 - retention never breaks the cron tick
        logging.getLogger("postriff.account_protection").warning(json.dumps({"event": "security_retention.unavailable", "error": type(error).__name__}))
        return {"status": "unavailable"}
    counts = counts if isinstance(counts, dict) else json.loads(counts)
    counts.pop("cutoff", None)
    return {"status": "ok", **counts}
