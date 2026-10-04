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
ones close the schedule row only. Everything is off unless POSTRIFF_METRIC_READS is "1" and the workspace is in
POSTRIFF_METRIC_WORKSPACE_ALLOWLIST. Adapter review and exact native grant scopes are required at every boundary.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from postriff_alpha.domain import AlphaError

from .. import insights
from .observation_windows import OFFSETS, missed

FLAG = "POSTRIFF_METRIC_READS"
WORKSPACE_ALLOWLIST = "POSTRIFF_METRIC_WORKSPACE_ALLOWLIST"
NATIVE_ANALYTICS_SCOPES = {
    "threads": frozenset({"threads_basic", "threads_manage_insights"}),
    "instagram": frozenset({"instagram_business_basic", "instagram_business_manage_insights"}),
}
LEASE_SECONDS = 120            # token_for_worker plus one insights GET can take 40 s
MAX_BACKOFF = 3600
TERMINAL_HTTP = (400, 401, 403, 404)
logger = logging.getLogger("postriff.growth.metric_reads")
logger.setLevel(logging.INFO)


def enabled(env):
    return (env or {}).get(FLAG) == "1"


def allowed_workspaces(env):
    """Explicit UUID admission only. An empty, wildcard or malformed list admits nobody."""
    raw = (env or {}).get(WORKSPACE_ALLOWLIST, "")
    if not isinstance(raw, str) or not raw.strip():
        return frozenset()
    try:
        return frozenset(str(uuid.UUID(value.strip())) for value in raw.split(","))
    except (ValueError, AttributeError):
        return frozenset()


def workspace_enabled(scheduler, workspace_id):
    """The UI must use the same admission as the worker; mounting is not tenant enablement."""
    return bool(scheduler and scheduler.workspace_allowed(workspace_id))


def backoff(row_id, attempts):
    jitter = int(hashlib.sha256(f"{row_id}:{attempts}".encode()).hexdigest()[:4], 16) % 30
    return min(60 * (2 ** max(0, attempts - 1)), MAX_BACKOFF) + jitter


def _note(event, error=None, **fields):
    # Ids, counts and classes only: exception text can carry tokens or third-party payloads.
    logger.warning(json.dumps({"event": event, **({"exceptionType": type(error).__name__} if error else {}), **fields}))


def guarded(cur, operation, event, failures=None):
    """Run `operation` in its own savepoint; roll only it back on failure. Returns the result or None; never raises.
    `failures`, when given, collects the exception class names."""
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
        if failures is not None:
            failures.append(type(error).__name__)
        _note(event, error)
        return None
    try:
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        _note(event, error)
        return None
    return result


def analytics_direct(cur, workspace_id, connection_id, *, lock=False):
    cur.execute("SELECT level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'" +
                (" FOR SHARE" if lock else ""),
                (workspace_id, connection_id))
    row = cur.fetchone()
    return bool(row) and row[0] == "Direct"


def purge_pending(cur, workspace_id, connection_id):
    """True while a disconnect purge is still owed for this connection (growth/history_import). Nothing new is read
    or imported for it until the purge has run. False before migration 035."""
    cur.execute("SELECT to_regclass('public.pr_growth_purges') IS NOT NULL")
    if not cur.fetchone()[0]:
        return False
    cur.execute("SELECT 1 FROM public.pr_growth_purges WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
    return cur.fetchone() is not None


def schedule(cur, workspace_id, connection_id, provider, provider_post_id, job_id, anchor_at, source, offsets=OFFSETS):
    """Insert schedule rows (due = anchor + offset). An existing row for the same post and offset is kept, unless it
    was cancelled (connection lost Direct analytics, or was disconnected): then it is revived with fresh attempts,
    so reconnecting and re-importing reads the posts again. Returns the number of rows inserted or revived."""
    inserted = 0
    for name, seconds in offsets:
        cur.execute("""INSERT INTO public.pr_metric_reads(workspace_id,job_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s))
                       ON CONFLICT (workspace_id,provider,provider_post_id,read_offset) DO UPDATE
                         SET status='pending', attempts=0, scheduled_at=now(), connection_id=excluded.connection_id,
                             -- a reading of a Rafii job keeps its source: it must never become purgeable import data
                             source=CASE WHEN public.pr_metric_reads.job_id IS NULL THEN excluded.source ELSE public.pr_metric_reads.source END,
                             job_id=coalesce(excluded.job_id, public.pr_metric_reads.job_id), anchor_at=excluded.anchor_at,
                             due_at=excluded.due_at, lease_owner=NULL, lease_until=NULL, failure_class=NULL, updated_at=now()
                         WHERE public.pr_metric_reads.status='cancelled'""",
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
    def __init__(self, connection_factory, oauth, *, transport, workspace_allowlist=(), customer_access=None, clock=time.time, monotonic=time.monotonic, worker_id=None):
        self.connection_factory = connection_factory
        self.oauth = oauth
        self.transport = transport
        self.clock = clock
        self.monotonic = monotonic
        self.worker_id = worker_id or f"mr-{uuid.uuid4().hex[:12]}"
        self.workspace_allowlist = frozenset(str(wid) for wid in workspace_allowlist)
        self.customer_access = customer_access

    def workspace_allowed(self, workspace_id, *, cursor=None):
        if self.customer_access:return self.customer_access.allowed(workspace_id,cursor=cursor)
        return str(workspace_id) in self.workspace_allowlist

    def provider_allowed(self, provider):
        adapter = (getattr(self.oauth, "providers", None) or {}).get(provider)
        reviewed_or_scoped = bool(adapter and (
            getattr(adapter, "production_reviewed", False) is True or
            (self.customer_access is None and getattr(adapter, "account_scoped_direct", False) is True)
        ))
        return bool(provider in NATIVE_ANALYTICS_SCOPES and reviewed_or_scoped
                    and getattr(adapter, "execution_enabled", True) is True)

    # --- scheduling (SQL only, inside the verification transaction) ---------------------------------------------------
    def provider_for(self, platform):
        for pid, adapter in (getattr(self.oauth, "providers", None) or {}).items():
            if adapter.platform == platform and self.provider_allowed(pid):
                return pid
        return None

    def on_post_verified(self, cur, workspace_id, job):
        def operation():
            if not self.workspace_allowed(workspace_id,cursor=cur):
                return 0
            manifest = job.get("manifest") or {}
            provider = self.provider_for(manifest.get("platform"))
            reference, verification = job.get("providerReference"), job.get("verification") or {}
            if provider is None or not reference or not isinstance(verification.get("at"), (int, float)):
                return 0
            if self._eligibility(cur, {"workspaceId": workspace_id, "connectionId": manifest.get("channelId"),
                                      "provider": provider, "jobId": job.get("id")}) != "read":
                return 0
            return schedule(cur, workspace_id, manifest["channelId"], provider, str(reference), job.get("id"),
                            float(verification["at"]), "verification")
        guarded(cur, operation, "metric_reads.schedule_failed")

    # --- cron step --------------------------------------------------------------------------------------------------
    CLAIM_ORDER = (  # (filter, order) — each a range scan on its own partial index (migration 035)
        ("status='claimed' AND lease_until < now()", "lease_until"),                           # crashed work first
        ("status='pending' AND source='verification' AND due_at <= now()", "due_at"),          # fresh readings
        ("status='pending' AND source<>'verification' AND due_at <= now()", "due_at"),         # imports and backfills
    )

    def claim(self, limit):
        """Up to `limit` rows: expired leases, then due fresh verification readings, then due backfill readings. A
        300-post import (all due at once, anchored weeks back) never delays any workspace's t0/1h/24h/7d readings,
        and no step scans rows that are not yet due."""
        rows = []
        if not self.workspace_allowlist and self.customer_access is None:
            return rows
        with self.connection_factory() as db, db.cursor() as cur:
            admitted=self.customer_access.workspaces(cursor=cur) if self.customer_access else sorted(self.workspace_allowlist)
            if not admitted:return rows
            for where, order in self.CLAIM_ORDER:
                if len(rows) >= limit:
                    break
                cur.execute(f"""UPDATE public.pr_metric_reads r SET status='claimed', lease_owner=%s, lease_until=now() + make_interval(secs => %s),
                                       attempts=attempts+1, updated_at=now()
                                WHERE r.id IN (SELECT id FROM public.pr_metric_reads WHERE {where}
                                  AND workspace_id=ANY(%s::uuid[]) ORDER BY {order} LIMIT %s FOR UPDATE SKIP LOCKED)
                                RETURNING r.id::text, r.workspace_id::text, r.job_id, r.connection_id, r.provider, r.provider_post_id,
                                          r.read_offset, extract(epoch from r.anchor_at)::float8, r.attempts, r.max_attempts""",
                            (self.worker_id, LEASE_SECONDS, admitted, limit - len(rows)))
                rows += cur.fetchall()
            db.commit()
        keys = ("id", "workspaceId", "jobId", "connectionId", "provider", "postId", "offset", "anchorAt", "attempts", "maxAttempts")
        return [dict(zip(keys, r)) for r in rows]

    def _eligible(self, row):
        """"read", "cancel", or "wait". While a disconnect purge is owed, import readings are cancelled (the purge
        deletes them anyway) but a reading of Rafii's own post waits and retries: the purge never touches it, and a
        cancelled t0/1h/24h reading could never be taken again."""
        with self.connection_factory() as db, db.cursor() as cur:
            return self._eligibility(cur, row)

    def _eligibility(self, cur, row, *, lock=False):
        # Completion serializes with workspace disconnect/deletion commands;
        # provider I/O still runs outside this short transaction.
        if not self.provider_allowed(row["provider"]):
            return "cancel"
        cur.execute("SELECT state ? 'accountDeletion' FROM public.pr_workspaces WHERE id=%s" +
                    (" FOR UPDATE" if lock else ""), (row["workspaceId"],))
        found = cur.fetchone()
        if not found or found[0]:
            return "cancel"
        if not self.workspace_allowed(row['workspaceId'],cursor=cur):return 'cancel'
        cur.execute("SELECT provider,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL" +
                    (" FOR SHARE" if lock else ""), (row["workspaceId"], row["connectionId"]))
        credential = cur.fetchone()
        if (not credential or credential[0] != row["provider"] or
                not NATIVE_ANALYTICS_SCOPES[row["provider"]] <= set(credential[1] or [])):
            return "cancel"
        if not analytics_direct(cur, row["workspaceId"], row["connectionId"], lock=lock):
            return "cancel"
        if purge_pending(cur, row["workspaceId"], row["connectionId"]):
            return "wait" if row.get("jobId") else "cancel"
        return "read"

    def read(self, row, grants):
        """Outcome dict: {"state": "done"|"transient"|"unavailable"|"cancelled", ...}. Never raises."""
        requested = False
        try:
            if missed(row,self.clock()):return {'state':'unavailable','failure':'horizon_missed'}
            if not self.workspace_allowed(row["workspaceId"]) or not self.provider_allowed(row["provider"]):
                return {"state": "cancelled", "failure": "not_admitted"}
            eligibility = self._eligible(row)
            if eligibility == "cancel":
                return {"state": "cancelled", "failure": "not_eligible"}
            if eligibility == "wait":
                return {"state": "transient", "failure": "purge_pending", "http": None}
            key = (row["workspaceId"], row["connectionId"])
            if key not in grants:
                grants[key] = self.oauth.token_for_worker(*key)
            grant = grants[key]
            if (grant.get("provider") != row["provider"] or
                    not NATIVE_ANALYTICS_SCOPES[row["provider"]] <= set(grant.get("scopes") or [])):
                return {"state": "cancelled", "failure": "analytics_scope_missing"}
            # Introspection can reveal a revoked scope. A reused grant never replaces current DB rights.
            eligibility = self._eligible(row)
            if eligibility == "wait":
                return {"state": "transient", "failure": "purge_pending", "http": None}
            if eligibility != "read":
                return {"state": "cancelled", "failure": "not_eligible"}
            if missed(row,self.clock()):return {'state':'unavailable','failure':'horizon_missed'}
            requested = True
            fetched = insights.fetch_post_insights(self.transport, grant["accessToken"], row["provider"], row["postId"])
        except AlphaError as error:
            status = getattr(error, "status", None)
            if status in (404, 409):            # revoked grant, or an attempted native request rejected by the transport
                return {"state": "unavailable", "failure": f"http_{status}" if requested else "credential",
                        "http": status if requested else None, "providerRead": requested}
            return {"state": "transient", "failure": "transport", "http": None, "providerRead": requested}
        except Exception as error:  # noqa: BLE001 - one bad row must not stop the step
            _note("metric_reads.read_failed", error)
            return {"state": "transient", "failure": "error", "http": None, "providerRead": requested}
        status = fetched["status"]
        if status == 200:
            at=self.clock()
            return {"state": "unavailable" if missed(row,at) else "done", "found": fetched["found"], "endpoint": fetched["endpoint"], "http": 200, "providerRead": True,
                    'observedAt':at,**({'failure':'horizon_missed'} if missed(row,at) else {})}
        if status in TERMINAL_HTTP:
            return {"state": "unavailable", "failure": f"http_{status}", "http": status, "providerRead": True}
        return {"state": "transient", "failure": f"http_{status}", "http": status, "providerRead": True}

    def complete(self, row, outcome):
        """Fence on this claim generation, unexpired lease and current rights."""
        state = outcome["state"]
        if state=='done' and missed(row,outcome.get('observedAt',self.clock())):
            state='unavailable'
            outcome.update(state=state,failure='horizon_missed')
        with self.connection_factory() as db, db.cursor() as cur:
            snapshot=state=='unavailable' and outcome.get('failure')=='horizon_missed' and 'found' in outcome
            if state == "done" or snapshot:
                eligibility = self._eligibility(cur, row, lock=True)
                if eligibility != "read":
                    state = "cancelled" if eligibility == "cancel" else "transient"
                    snapshot=False
                    outcome.update(state=state, failure="not_eligible" if eligibility == "cancel" else "purge_pending")
            fence = (row["id"], self.worker_id, row["attempts"])
            if state == "done":
                cur.execute("""UPDATE public.pr_metric_reads SET status='done', observed_at=now(), last_http_status=200, failure_class=NULL,
                                      lease_owner=NULL, lease_until=NULL, updated_at=now() WHERE id=%s::uuid AND lease_owner=%s
                                      AND attempts=%s AND lease_until>clock_timestamp() AND status='claimed'""", fence)
                recorded = cur.rowcount == 1
                if recorded:
                    insights.record_observations(cur, row["workspaceId"], row["connectionId"], row["provider"], row["postId"], row["jobId"],
                                                 outcome["found"], outcome["endpoint"], outcome.get('observedAt',self.clock()), read_offset=row["offset"],
                                                 period_start=row["anchorAt"])
            elif state == "transient" and row["attempts"] < row["maxAttempts"]:
                cur.execute("""UPDATE public.pr_metric_reads SET status='pending', due_at=now() + make_interval(secs => %s), last_http_status=%s,
                                      failure_class=%s, lease_owner=NULL, lease_until=NULL, updated_at=now()
                               WHERE id=%s::uuid AND lease_owner=%s AND attempts=%s AND lease_until>clock_timestamp() AND status='claimed'""",
                            (backoff(row["id"], row["attempts"]), outcome.get("http"), outcome.get("failure"), *fence))
                recorded = cur.rowcount == 1
            else:
                final = {"transient": "dead", "unavailable": "unavailable", "cancelled": "cancelled"}.get(state, "dead")
                cur.execute("""UPDATE public.pr_metric_reads SET status=%s, last_http_status=%s, failure_class=%s, lease_owner=NULL, lease_until=NULL,
                                      updated_at=now() WHERE id=%s::uuid AND lease_owner=%s AND attempts=%s
                                      AND lease_until>clock_timestamp() AND status='claimed'""",
                            (final, outcome.get("http"), outcome.get("failure"), *fence))
                recorded = cur.rowcount == 1
                if recorded and snapshot:
                    insights.record_observations(cur,row['workspaceId'],row['connectionId'],row['provider'],row['postId'],row['jobId'],
                        outcome['found'],outcome['endpoint'],outcome.get('observedAt',self.clock()),read_offset=None,period_start=row['anchorAt'])
            db.commit()
        return recorded

    def release(self, rows):
        """Give back rows claimed but not read before the step's deadline, without spending an attempt."""
        if not rows:
            return
        with self.connection_factory() as db, db.cursor() as cur:
            for row in rows:
                cur.execute("""UPDATE public.pr_metric_reads SET status='pending', attempts=greatest(0, attempts-1), lease_owner=NULL, lease_until=NULL,
                                      updated_at=now() WHERE id=%s::uuid AND lease_owner=%s AND attempts=%s
                                      AND lease_until>clock_timestamp() AND status='claimed'""",
                            (row["id"], self.worker_id, row["attempts"]))
            db.commit()

    def tick(self, max_reads=10, max_seconds=15.0):
        """Bounded cron step. Returns a status dict of counts; never raises."""
        counts = {"status": "ok", "claimed": 0, "done": 0, "retry": 0, "unavailable": 0, "cancelled": 0, "dead": 0, "deferred": 0}
        counts.update(providerReads=0, providerErrors=0, costUnknownReads=0)
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
                if outcome.get("providerRead"):
                    counts["providerReads"] += 1
                    counts["costUnknownReads"] += 1  # native response reports no invoice; never assert zero
                    counts["providerErrors"] += int(outcome["state"] != "done")
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
        logger.info(json.dumps({"event": "metric_reads.tick", **counts, "costUsd": None, "costSource": "unknown"}))
        return counts
