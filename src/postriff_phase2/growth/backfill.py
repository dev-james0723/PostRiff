"""Backfill (growth Phase 0): one reading for Rafii-verified posts from the last 90 days that predate scheduling.

Posts verified before POSTRIFF_METRIC_READS was on have no schedule rows. `backfill_verified_jobs` finds verified
Threads/Instagram jobs in each workspace's state (plain SELECT, no row locks on pr_workspaces, so the publishing
worker is never blocked; every workspace, in keyset-paginated batches), and schedules one 'backfill' reading anchored at the verification time for any post that
has no reading yet, on connections whose analytics capability is Direct. It is idempotent and bounded, and runs only
when an operator invokes it:

    python -m postriff_phase2.growth.backfill [--apply] [--days 90] [--batch-size 200]

Without --apply it reports what it would schedule and writes nothing. It needs POSTRIFF_DATABASE_URL (never printed);
running it against production is a separate, approved operation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import metric_schedule

WINDOW_DAYS = 90
PROVIDERS = {"Threads": "threads", "Instagram": "instagram"}
BACKFILL = (("backfill", 0),)


def candidates(state, now, window_days=WINDOW_DAYS):
    """(job_id, connection_id, provider, post_id, verified_at) for verified jobs inside the window."""
    jobs = ((state or {}).get("phase2") or {}).get("jobs") or []
    cutoff = now - window_days * 86400
    out = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        verification = job.get("verification") or {}
        at = verification.get("at") if isinstance(verification, dict) else None
        manifest = job.get("manifest") or {}
        provider = PROVIDERS.get(manifest.get("platform"))
        if provider and job.get("providerReference") and manifest.get("channelId") and isinstance(at, (int, float)) and cutoff <= at <= now:
            out.append((job.get("id"), manifest["channelId"], provider, str(job["providerReference"]), float(at)))
    return out


def backfill_verified_jobs(connection_factory, *, now=None, window_days=WINDOW_DAYS, batch_size=200, apply=False):
    """Walk every workspace in id order, `batch_size` at a time (keyset pagination, one transaction per batch), so
    no workspace is skipped however many there are. Returns totals; `scheduled` is 0 unless `apply`."""
    now = time.time() if now is None else now
    report = {"workspaces": 0, "batches": 0, "candidates": 0, "eligible": 0, "scheduled": 0, "applied": apply}
    after = "00000000-0000-0000-0000-000000000000"
    while True:
        with connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT id::text, state FROM public.pr_workspaces
                           WHERE id > %s::uuid AND state ? 'phase2' AND NOT state ? 'accountDeletion' ORDER BY id LIMIT %s""",
                        (after, batch_size))
            workspaces = cur.fetchall()
            if not workspaces:
                break
            report["batches"] += 1
            for workspace_id, raw in workspaces:
                _one_workspace(cur, workspace_id, raw, now, window_days, apply, report)
            if apply:
                db.commit()
            else:
                db.rollback()
        after = workspaces[-1][0]
        if len(workspaces) < batch_size:
            break
    return report


def _one_workspace(cur, workspace_id, raw, now, window_days, apply, report):
    state = json.loads(raw) if isinstance(raw, str) else raw
    found = candidates(state, now, window_days)
    report["workspaces"] += 1
    report["candidates"] += len(found)
    direct = {}
    for job_id, connection_id, provider, post_id, verified_at in found:
        if connection_id not in direct:
            direct[connection_id] = metric_schedule.analytics_direct(cur, workspace_id, connection_id)
        if not direct[connection_id]:
            continue
        # A cancelled row (lost analytics, disconnect) is revived by schedule(); anything else already has a reading.
        cur.execute("SELECT 1 FROM public.pr_metric_reads WHERE workspace_id=%s AND provider=%s AND provider_post_id=%s AND status<>'cancelled' LIMIT 1",
                    (workspace_id, provider, post_id))
        if cur.fetchone():
            continue
        report["eligible"] += 1
        if apply:
            report["scheduled"] += metric_schedule.schedule(cur, workspace_id, connection_id, provider, post_id, job_id,
                                                            verified_at, "backfill", BACKFILL)


def main(argv=None, *, env=None, connect=None, out=sys.stdout):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="python -m postriff_phase2.growth.backfill")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args(argv)
    if not 1 <= args.days <= WINDOW_DAYS:
        print(f"error: --days must be 1..{WINDOW_DAYS}", file=out)
        return 2
    if connect is None:
        dsn = env.get("POSTRIFF_DATABASE_URL")
        if not dsn:
            print("error: POSTRIFF_DATABASE_URL is not set", file=out)
            return 2
        import psycopg
        connect = lambda: psycopg.connect(dsn)   # noqa: E731
    if not 1 <= args.batch_size <= 1000:
        print("error: --batch-size must be 1..1000", file=out)
        return 2
    report = backfill_verified_jobs(connect, window_days=args.days, batch_size=args.batch_size, apply=args.apply)
    print(json.dumps(report), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
