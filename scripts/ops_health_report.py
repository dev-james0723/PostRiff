"""Operator tool: one read-only look at what needs a person (FINAL-10).

Counts and identifiers only — never post text, prompts, emails or payment details:

- unknownUsage: model or media runs whose provider cost is unknown (finish with reconcile_unknown_usage.py)
- paymentInbox: verified payment events waiting for review (finish with credit_payment_inbox.py)
- publishing: jobs in `uncertain` (the provider may have posted; reconcile before any retry), `held`
  (a person must re-approve or cancel), leases that expired while `processing`/`submitting` (a worker
  stopped mid-run), and `scheduled` jobs more than 15 minutes overdue (the cron or worker is not running)
- budgets: spend windows past their warning or stop line, and budgets still `candidate` (paid calls refused)

  python3 scripts/ops_health_report.py --dsn "host=127.0.0.1 port=55438 dbname=postgres"

The connection is read-only. Only a loopback database is accepted unless --confirm-host names the exact host.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import psycopg
from psycopg.conninfo import conninfo_to_dict
from postriff_phase2.billing import Ledger

OVERDUE_SECONDS = 900
STUCK_STATES = ("processing", "submitting")


def health(cur, now):
    unknown = Ledger().unknown_reservations(cur, None, limit=1000)
    report = {
        "checkedAt": now,
        "unknownUsage": {"count": len(unknown), "oldestSince": min((u["since"] for u in unknown), default=None),
                         "items": [{k: u[k] for k in ("workspaceId", "reservationId", "runId", "model", "estimatedUsdMicro", "since")} for u in unknown[:50]]},
    }
    cur.execute("SELECT to_regclass('public.pr_credit_payment_inbox') IS NOT NULL")
    if cur.fetchone()[0]:
        cur.execute("SELECT count(*), extract(epoch from min(received_at)) FROM public.pr_credit_payment_inbox WHERE status='needs_review'")
        count, oldest = cur.fetchone()
        report["paymentInbox"] = {"needsReview": count, "oldestReceivedAt": float(oldest) if oldest is not None else None}
    else:
        report["paymentInbox"] = {"needsReview": None, "note": "migration 022 not applied"}
    cur.execute(
        "SELECT w.id::text, j->>'id', j->>'state', (j->>'nextAt')::float8, (j->>'leaseUntil')::float8 "
        "FROM public.pr_workspaces w, jsonb_array_elements(coalesce(w.state::jsonb->'phase2'->'jobs','[]'::jsonb)) j "
        "WHERE j->>'state' IN ('uncertain','held','processing','submitting','scheduled')")
    publishing = {"uncertain": [], "held": [], "expiredLease": [], "overdue": []}
    for workspace_id, job_id, state, next_at, lease_until in cur.fetchall():
        item = {"workspaceId": workspace_id, "jobId": job_id}
        if state in ("uncertain", "held"):
            publishing[state].append(item)
        elif state in STUCK_STATES and lease_until and lease_until < now:
            publishing["expiredLease"].append({**item, "state": state, "leaseUntil": lease_until})
        elif state == "scheduled" and next_at and next_at < now - OVERDUE_SECONDS:
            publishing["overdue"].append({**item, "nextAt": next_at})
    report["publishing"] = {key: {"count": len(items), "items": items[:50]} for key, items in publishing.items()}
    cur.execute("SELECT scope, status, spent_usd_micro, reserved_usd_micro, warn_usd_micro, stop_usd_micro FROM public.pr_budgets ORDER BY scope")
    budgets = {"pastStop": [], "pastWarning": [], "notApproved": []}
    for scope, status, spent, reserved, warn, stop in cur.fetchall():
        used = spent + reserved
        row = {"scope": scope, "usedUsdMicro": used, "warnUsdMicro": warn, "stopUsdMicro": stop}
        if used >= stop:
            budgets["pastStop"].append(row)
        elif used >= warn:
            budgets["pastWarning"].append(row)
        if status != "approved":
            budgets["notApproved"].append({"scope": scope, "status": status})
    report["budgets"] = budgets
    report["needsAttention"] = bool(unknown or report["paymentInbox"].get("needsReview") or any(publishing.values()) or budgets["pastStop"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--confirm-host", default="")
    args = parser.parse_args(argv)
    host = conninfo_to_dict(args.dsn).get("host", "")
    if host not in ("127.0.0.1", "localhost", "::1") and args.confirm_host != host:
        raise SystemExit("Refusing a non-loopback database without --confirm-host naming that exact host.")
    with psycopg.connect(args.dsn, client_encoding="utf8") as db:
        db.read_only = True
        with db.cursor() as cur:
            print(json.dumps(health(cur, time.time()), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
