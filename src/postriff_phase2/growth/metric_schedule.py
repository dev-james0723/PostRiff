"""Scheduled post metric readings (growth Phase 0): t0, +1h, +24h and +7d after a verified publication.

Two halves, so no HTTP ever runs inside the publishing worker's transaction:
- `on_post_verified(cur, workspace_id, job)` is SQL only. It runs inside the worker's verification transaction, in
  its own savepoint, inserts the four schedule rows and never raises.
- `tick()` is the cron step. It claims due rows with FOR UPDATE SKIP LOCKED and commits, reads insights outside
  any transaction, then records the observations and closes the row in one transaction fenced on the lease, so a
  crash-recovered re-claim cannot double-write.

Only Threads and Instagram posts on connections whose analytics capability is Direct are scheduled or read; both
are re-checked before every read (a disconnect or account deletion stops readings). A failed read never writes an
'unavailable' observation that would hide an earlier real value: transient failures retry with backoff; terminal
ones close the schedule row only. Everything is off unless POSTRIFF_METRIC_READS is "1".
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from postriff_alpha.domain import AlphaError

from .. import insights

FLAG = "POSTRIFF_METRIC_READS"
OFFSETS = (("t0", 0), ("1h", 3600), ("24h", 86400), ("7d", 7 * 86400))
LEASE_SECONDS = 120            # token_for_worker plus one insights GET can take 40 s
MAX_BACKOFF = 3600
TERMINAL_HTTP = (400, 401, 403, 404)
logger = logging.getLogger("postriff.growth.metric_reads")


def enabled(env):
    return (env or {}).get(FLAG) == "1"


def backoff(row_id, attempts):
    jitter = int(hashlib.sha256(f"{row_id}:{attempts}".encode()).hexdigest()[:4], 16) % 30
    return min(60 * (2 ** max(0, attempts - 1)), MAX_BACKOFF) + jitter


def _note(event, error=None, **fields):
    # Ids, counts and classes only: exception text can carry tokens or third-party payloads.
    logger.warning(json.dumps({"event": event, **({"exceptionType": type(error).__name__} if error else {}), **fields}))


def guarded(cur, operation, event):
    """Run `operation` in its own savepoint; roll only it back on failure. Returns the result or None; never raises."""
    mark = "metric_reads_" + uuid.uuid4().hex[:8]
    try:
        cur.execute(f"SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001 - the transaction is already unusable; its owner decides
        _note(event, error)
        return None
    try:
        result = operation()
    except Exception as error:  # noqa: BLE001 - scheduling must never fail the verification that triggered it
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
            cur.execute(f"RELEASE SAVEPOINT {mark}")
        except Exception:  # noqa: BLE001
            pass
        _note(event, error)
        return None
    try:
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        _note(event, error)
        return None
    return result


def analytics_direct(cur, workspace_id, connection_id):
    cur.execute("SELECT level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'",
                (workspace_id, connection_id))
    row = cur.fetchone()
    return bool(row) and row[0] == "Direct"


def schedule(cur, workspace_id, connection_id, provider, provider_post_id, job_id, anchor_at, source, offsets=OFFSETS):
    """Insert schedule rows (due = anchor + offset); existing rows for the same post and offset are kept. Returns count."""
    inserted = 0
    for name, seconds in offsets:
        cur.execute("""INSERT INTO public.pr_metric_reads(workspace_id,job_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s))
                       ON CONFLICT (workspace_id,provider,provider_post_id,read_offset) DO NOTHING""",
                    (workspace_id, job_id, connection_id, provider, provider_post_id, name, source, anchor_at, anchor_at + seconds))
        inserted += cur.rowcount or 0
    return inserted


def then_schedule(on_verified, scheduler):
    """Chain the worker's verified hook with scheduling, like with_time_back: the existing hook runs first and its
    error still reaches the worker; scheduling runs even when it fails and never raises itself."""
    def hook(cur, workspace_id, job):
        try:
            if on_verified is not None:
                on_verified(cur, workspace_id, job)
        finally:
            scheduler.on_post_verified(cur, workspace_id, job)
    return hook


class MetricScheduler:
    def __init__(self, connection_factory, oauth, *, transport, clock=time.time, monotonic=time.monotonic, worker_id=None):
        self.connection_factory = connection_factory
        self.oauth = oauth
        self.transport = transport
        self.clock = clock
        self.monotonic = monotonic
        self.worker_id = worker_id or f"mr-{uuid.uuid4().hex[:12]}"

    # --- scheduling (SQL only, inside the verification transaction) ---------------------------------------------------
    def provider_for(self, platform):
        for pid, adapter in (getattr(self.oauth, "providers", None) or {}).items():
            if adapter.platform == platform and adapter.production_reviewed and pid in insights.INSIGHT_METRICS:
                return pid
        return None

    def on_post_verified(self, cur, workspace_id, job):
        def operation():
            manifest = job.get("manifest") or {}
            provider = self.provider_for(manifest.get("platform"))
            reference, verification = job.get("providerReference"), job.get("verification") or {}
            if provider is None or not reference or not isinstance(verification.get("at"), (int, float)):
                return 0
            if not analytics_direct(cur, workspace_id, manifest.get("channelId")):
                return 0
            return schedule(cur, workspace_id, manifest["channelId"], provider, str(reference), job.get("id"),
                            float(verification["at"]), "verification")
        guarded(cur, operation, "metric_reads.schedule_failed")

    # --- cron step --------------------------------------------------------------------------------------------------
    def claim(self, limit):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("""UPDATE public.pr_metric_reads r SET status='claimed', lease_owner=%s, lease_until=now() + make_interval(secs => %s),
                                  attempts=attempts+1, updated_at=now()
                           WHERE r.id IN (SELECT id FROM public.pr_metric_reads
                                          WHERE (status='pending' AND due_at <= now()) OR (status='claimed' AND lease_until < now())
                                          ORDER BY due_at LIMIT %s FOR UPDATE SKIP LOCKED)
                           RETURNING r.id::text, r.workspace_id::text, r.job_id, r.connection_id, r.provider, r.provider_post_id,
                                     r.read_offset, extract(epoch from r.anchor_at)::float8, r.attempts, r.max_attempts""",
                        (self.worker_id, LEASE_SECONDS, limit))
            rows = cur.fetchall()
            db.commit()
        keys = ("id", "workspaceId", "jobId", "connectionId", "provider", "postId", "offset", "anchorAt", "attempts", "maxAttempts")
        return [dict(zip(keys, r)) for r in rows]

    def _eligible(self, row):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT state ? 'accountDeletion' FROM public.pr_workspaces WHERE id=%s", (row["workspaceId"],))
            found = cur.fetchone()
            if not found or found[0]:
                return False
            return analytics_direct(cur, row["workspaceId"], row["connectionId"])

    def read(self, row, grants):
        """Outcome dict: {"state": "done"|"transient"|"unavailable"|"cancelled", ...}. Never raises."""
        try:
            if not self._eligible(row):
                return {"state": "cancelled", "failure": "not_eligible"}
            key = (row["workspaceId"], row["connectionId"])
            if key not in grants:
                grants[key] = self.oauth.token_for_worker(*key)
            fetched = insights.fetch_post_insights(self.transport, grants[key]["accessToken"], row["provider"], row["postId"])
        except AlphaError as error:
            status = getattr(error, "status", None)
            if status in (404, 409):            # credential revoked or connection gone
                return {"state": "unavailable", "failure": "credential", "http": None}
            return {"state": "transient", "failure": "transport", "http": None}
        except Exception as error:  # noqa: BLE001 - one bad row must not stop the step
            _note("metric_reads.read_failed", error)
            return {"state": "transient", "failure": "error", "http": None}
        status = fetched["status"]
        if status == 200:
            return {"state": "done", "found": fetched["found"], "endpoint": fetched["endpoint"], "http": 200}
        if status in TERMINAL_HTTP:
            return {"state": "unavailable", "failure": f"http_{status}", "http": status}
        return {"state": "transient", "failure": f"http_{status}", "http": status}

    def complete(self, row, outcome):
        """Fenced on the lease. Returns True when this worker's outcome was recorded."""
        state = outcome["state"]
        with self.connection_factory() as db, db.cursor() as cur:
            fence = (row["id"], self.worker_id)
            if state == "done":
                cur.execute("""UPDATE public.pr_metric_reads SET status='done', observed_at=now(), last_http_status=200, failure_class=NULL,
                                      lease_owner=NULL, lease_until=NULL, updated_at=now() WHERE id::text=%s AND lease_owner=%s AND status='claimed'""", fence)
                recorded = cur.rowcount == 1
                if recorded:
                    insights.record_observations(cur, row["workspaceId"], row["connectionId"], row["provider"], row["postId"], row["jobId"],
                                                 outcome["found"], outcome["endpoint"], self.clock(), read_offset=row["offset"],
                                                 period_start=row["anchorAt"])
            elif state == "transient" and row["attempts"] < row["maxAttempts"]:
                cur.execute("""UPDATE public.pr_metric_reads SET status='pending', due_at=now() + make_interval(secs => %s), last_http_status=%s,
                                      failure_class=%s, lease_owner=NULL, lease_until=NULL, updated_at=now()
                               WHERE id::text=%s AND lease_owner=%s AND status='claimed'""",
                            (backoff(row["id"], row["attempts"]), outcome.get("http"), outcome.get("failure"), *fence))
                recorded = cur.rowcount == 1
            else:
                final = {"transient": "dead", "unavailable": "unavailable", "cancelled": "cancelled"}.get(state, "dead")
                cur.execute("""UPDATE public.pr_metric_reads SET status=%s, last_http_status=%s, failure_class=%s, lease_owner=NULL, lease_until=NULL,
                                      updated_at=now() WHERE id::text=%s AND lease_owner=%s AND status='claimed'""",
                            (final, outcome.get("http"), outcome.get("failure"), *fence))
                recorded = cur.rowcount == 1
            db.commit()
        return recorded

    def release(self, rows):
        """Give back rows claimed but not read before the step's deadline, without spending an attempt."""
        if not rows:
            return
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("""UPDATE public.pr_metric_reads SET status='pending', attempts=greatest(0, attempts-1), lease_owner=NULL, lease_until=NULL,
                                  updated_at=now() WHERE id::text = ANY(%s) AND lease_owner=%s AND status='claimed'""",
                        ([r["id"] for r in rows], self.worker_id))
            db.commit()

    def tick(self, max_reads=10, max_seconds=15.0):
        """Bounded cron step. Returns a status dict of counts; never raises."""
        counts = {"status": "ok", "claimed": 0, "done": 0, "retry": 0, "unavailable": 0, "cancelled": 0, "dead": 0, "deferred": 0}
        try:
            deadline = self.monotonic() + max_seconds
            rows = self.claim(max_reads)
            counts["claimed"] = len(rows)
            grants = {}
            for index, row in enumerate(rows):
                if self.monotonic() >= deadline:
                    self.release(rows[index:])
                    counts["deferred"] = len(rows) - index
                    break
                outcome = self.read(row, grants)
                try:
                    recorded = self.complete(row, outcome)
                except Exception as error:  # noqa: BLE001 - the row stays claimed and is re-read after its lease lapses
                    _note("metric_reads.complete_failed", error)
                    counts["error"] = counts.get("error", 0) + 1
                    continue
                if not recorded:
                    continue
                state = outcome["state"]
                if state == "transient":
                    counts["retry" if row["attempts"] < row["maxAttempts"] else "dead"] += 1
                else:
                    counts[state] += 1
        except Exception as error:  # noqa: BLE001 - the cron handler's later steps must still run
            _note("metric_reads.tick_failed", error)
            counts["status"] = "unavailable"
        return counts
