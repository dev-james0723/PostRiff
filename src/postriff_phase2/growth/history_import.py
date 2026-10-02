"""History import (growth Phase 0): the connected account's own posts from the last 90 days.

A person with manage_connections asks for it explicitly (`request`, interactive session, `confirmed: true`). The cron
step (`tick`) then pages through the account's posts with the server-side token, stores metadata only in
pr_owned_posts (caption length, never caption text or a hash of it: a hash of a short caption can be guessed),
and schedules one 'backfill' reading per post in
pr_metric_reads, which MetricScheduler reads like any other. Each page and its cursor are written in one transaction
fenced on the run's lease. Reading needs the connection's analytics capability to be Direct (its grant carries
threads_basic / instagram_business_basic, which list the account's own posts), so no new scope is requested.

Off unless POSTRIFF_HISTORY_IMPORT and POSTRIFF_METRIC_READS are both "1". Before enabling it in production the
consent copy that says analytics reads "posts Rafii created" must be updated (docs/design/growth-phase0/CONTRACTS.md).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError

from ..providers import GRAPH_VERSION
from . import metric_schedule
from .credit_admission import funding_mode, require_qualified_entry

FLAG = "POSTRIFF_HISTORY_IMPORT"
WINDOW_DAYS = 90
PAGE_LIMIT = 25
MAX_PAGES = 12                  # at most 300 posts per run
PAGES_PER_TICK = 3
LEASE_SECONDS = 120
MAX_ATTEMPTS = 5
BACKFILL = (("backfill", 0),)


def enabled(env):
    env = env or {}
    return env.get(FLAG) == "1" and metric_schedule.enabled(env)


class HistoryHTTP(Exception):
    def __init__(self, status):
        super().__init__(f"history page status {status}")
        self.status = status


def _timestamp(value):
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value.replace("Z", "+0000"), fmt).timestamp()
        except ValueError:
            continue
    return None


def _short(value, limit):
    return value[:limit] if isinstance(value, str) and value else None


def list_page(transport, provider, access_token, cursor=None):
    """One page of the account's own posts, newest first: {"posts": [...], "next": cursor | None, "incomplete": bool}.
    `incomplete` means the provider announced a next page without a usable cursor: this page's posts are still good,
    but coverage cannot continue, so the run must not report itself complete."""
    if provider == "threads":
        params = {"fields": "id,timestamp,media_type,permalink,text", "limit": PAGE_LIMIT, "access_token": access_token}
        if cursor:
            params["after"] = cursor
        response = transport("GET", f"https://graph.threads.net/{GRAPH_VERSION}/me/threads?" + urlencode(params))
        text_field = "text"
    elif provider == "instagram":
        params = {"fields": "id,caption,timestamp,media_type,media_product_type,permalink", "limit": PAGE_LIMIT}
        if cursor:
            params["after"] = cursor
        response = transport("GET", f"https://graph.instagram.com/{GRAPH_VERSION}/me/media?" + urlencode(params),
                             headers={"Authorization": f"Bearer {access_token}"})
        text_field = "caption"
    else:
        raise ValueError(f"history import does not support {provider}")
    if response.get("status") != 200 or not isinstance(response.get("body"), dict):
        raise HistoryHTTP(response.get("status"))
    body = response["body"]
    posts = []
    for item in body.get("data") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        caption = item.get(text_field) if isinstance(item.get(text_field), str) else ""
        permalink = item.get("permalink") if isinstance(item.get("permalink"), str) and item["permalink"].startswith("https://") else None
        posts.append({
            "id": str(item["id"])[:200],
            "publishedAt": _timestamp(item.get("timestamp")),
            "mediaType": _short(item.get("media_type"), 40),
            "mediaProductType": _short(item.get("media_product_type"), 40),
            "permalink": _short(permalink, 500),
            "captionChars": len(caption),
        })
    paging = body.get("paging") if isinstance(body.get("paging"), dict) else {}
    if not paging.get("next"):
        return {"posts": posts, "next": None, "incomplete": False}
    cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
    after = cursors.get("after")
    if not isinstance(after, str) or not after or len(after) > 500:
        return {"posts": posts, "next": None, "incomplete": True}
    return {"posts": posts, "next": after, "incomplete": False}


def purge_connection(cur, workspace_id, connection_id, imports_only=False):
    """Remove what history import stored for this connection. Safe before migration 035 is applied.

    Runs in its own transaction, never inside the disconnect's (which holds the workspace row FOR UPDATE while the
    import and metric steps take their own rows first and then a key-share lock on that workspace row for their
    inserts: purging there could deadlock). Locks follow the import step's order: run rows, owned posts, readings.
    Deleting the import's job-less reading rows before the observations fences an in-flight metric completion: it
    either committed first (its observations are deleted below) or finds its row gone and writes nothing. Readings
    of Rafii's own published posts (job_id set) are never deleted; unless `imports_only`, every pending reading of
    the connection is cancelled."""
    cur.execute("SELECT to_regclass('public.pr_owned_posts') IS NOT NULL")
    if not cur.fetchone()[0]:
        return 0
    key = (workspace_id, connection_id)
    cur.execute("SELECT 1 FROM public.pr_history_imports WHERE workspace_id=%s AND connection_id=%s FOR UPDATE", key)
    cur.execute("SELECT 1 FROM public.pr_owned_posts WHERE workspace_id=%s AND connection_id=%s AND source='history_import' FOR UPDATE", key)
    cur.execute("DELETE FROM public.pr_metric_reads WHERE workspace_id=%s AND connection_id=%s AND source='history_import' AND job_id IS NULL", key)
    if not imports_only:
        cur.execute("UPDATE public.pr_metric_reads SET status='cancelled', lease_owner=NULL, lease_until=NULL, updated_at=now() "
                    "WHERE workspace_id=%s AND connection_id=%s AND status IN ('pending','claimed')", key)
    cur.execute("UPDATE public.pr_history_imports SET status='cancelled', lease_owner=NULL, lease_until=NULL, updated_at=now() "
                "WHERE workspace_id=%s AND connection_id=%s AND status IN ('pending','running')", key)
    cur.execute("""DELETE FROM public.pr_metric_observations o USING public.pr_owned_posts p
                   WHERE p.workspace_id=%s AND p.connection_id=%s AND p.source='history_import' AND o.workspace_id=p.workspace_id
                     AND o.provider=p.provider AND o.provider_post_id=p.provider_post_id AND o.job_id IS NULL""", key)
    cur.execute("DELETE FROM public.pr_owned_posts WHERE workspace_id=%s AND connection_id=%s AND source='history_import'", key)
    return cur.rowcount


purge_pending = metric_schedule.purge_pending


def mark_for_purge(cur, workspace_id, connection_id):
    """oauth.disconnect, inside its transaction: record that this connection's imported history must go. One small
    insert, no locks the import or metric steps hold; from its commit on, nothing new is imported or read for the
    connection. `requested_at` keeps the first time a purge was owed. Never raises (own savepoint, logged)."""
    return metric_schedule.guarded(cur, lambda: cur.execute(
        """INSERT INTO public.pr_growth_purges(workspace_id,connection_id) VALUES(%s,%s)
           ON CONFLICT (workspace_id,connection_id) DO UPDATE SET next_attempt_at=now(), attempts=0, failure_class=NULL""",
        (workspace_id, connection_id)) if _purges_table(cur) else None, "history_import.purge_mark_failed")


def _purges_table(cur):
    cur.execute("SELECT to_regclass('public.pr_growth_purges') IS NOT NULL")
    return cur.fetchone()[0]


def purge_after_disconnect(connection_factory, workspace_id, connection_id):
    """oauth.disconnect, after its transaction committed: purge this connection now, in a fresh transaction. If it
    fails the marker stays and the cron sweep retries. Never raises."""
    return _sweep(connection_factory, limit=1, only=(workspace_id, connection_id), imports_only=False)


def sweep_pending_purges(connection_factory, limit=10, max_seconds=10.0, monotonic=time.monotonic):
    """Cron: retry owed purges whatever the growth flags say. One transaction per marker (lock timeout 2 s, statement
    timeout 5 s) and a step deadline, so it never stalls the cron handler; a failing marker backs off
    (metric_schedule.backoff) so it cannot starve newer ones; one connection when there is nothing to do. Imports and
    readings were blocked since the marker was set, so all import-derived data goes. Never raises."""
    return _sweep(connection_factory, limit=limit, only=None, imports_only=True, max_seconds=max_seconds, monotonic=monotonic)


def _sweep(connection_factory, *, limit, only, imports_only, max_seconds=10.0, monotonic=time.monotonic):
    counts = {"status": "ok", "purged": 0, "failed": 0}
    deadline = monotonic() + max_seconds
    try:
        for index in range(limit):
            if monotonic() >= deadline:
                counts["deferred"] = True
                break
            with connection_factory() as db, db.cursor() as cur:
                if index == 0 and not _purges_table(cur):
                    return {"status": "not_migrated"}
                cur.execute("SET LOCAL lock_timeout = '2s'")
                cur.execute("SET LOCAL statement_timeout = '5s'")
                if only is None:
                    cur.execute("""SELECT workspace_id::text, connection_id, attempts FROM public.pr_growth_purges
                                   WHERE next_attempt_at <= now() ORDER BY next_attempt_at LIMIT 1 FOR UPDATE SKIP LOCKED""")
                else:
                    cur.execute("""SELECT workspace_id::text, connection_id, attempts FROM public.pr_growth_purges
                                   WHERE workspace_id=%s AND connection_id=%s FOR UPDATE SKIP LOCKED""", only)
                marker = cur.fetchone()
                if marker is None:
                    break
                workspace_id, connection_id, attempts = marker
                failures = []
                done = metric_schedule.guarded(cur, lambda: purge_connection(cur, workspace_id, connection_id, imports_only=imports_only),
                                               "history_import.purge_failed", failures)
                if done is None:
                    counts["failed"] += 1
                    cur.execute("""UPDATE public.pr_growth_purges SET attempts=attempts+1, failure_class=%s,
                                          next_attempt_at=now() + make_interval(secs => %s) WHERE workspace_id=%s AND connection_id=%s""",
                                ((failures[-1] if failures else "unknown")[:80], metric_schedule.backoff(f"{workspace_id}:{connection_id}", attempts + 1),
                                 workspace_id, connection_id))
                else:
                    counts["purged"] += 1
                    cur.execute("DELETE FROM public.pr_growth_purges WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
                db.commit()
    except Exception as error:  # noqa: BLE001 - never fail the disconnect or the cron steps after this one
        metric_schedule._note("history_import.purge_sweep_failed", error)
        counts["status"] = "unavailable"
    return counts


class HistoryImporter:
    def __init__(self, connection_factory, oauth, *, transport, clock=time.time, monotonic=time.monotonic, worker_id=None):
        self.connection_factory = connection_factory
        self.oauth = oauth
        self.transport = transport
        self.clock = clock
        self.monotonic = monotonic
        self.worker_id = worker_id or f"hi-{uuid.uuid4().hex[:12]}"

    # --- customer surface ----------------------------------------------------------------------------------------------
    def request(self, workspace_id, token, connection_id, payload):
        from ..api_tokens import is_api_token
        from ..hosted import _membership, throttle
        from ..permissions import require
        if is_api_token(token):
            raise AlphaError("An interactive sign-in is required to import post history.", 403)
        if not isinstance(payload, dict) or payload.get("confirmed") is not True:
            raise AlphaError("Confirm reading the last 90 days of this account's posts and their metrics.", 400)
        with self.oauth.repository.transaction(token, workspace_id) as (cur, row, actor):
            require(_membership(row), "manage_connections")
            require_qualified_entry(cur,workspace_id)
            throttle(cur, f"history-import:{workspace_id}:{actor}", 5, 3600)
            cur.execute("SELECT provider FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL",
                        (workspace_id, connection_id))
            found = cur.fetchone()
            if not found or found[0] not in ("threads", "instagram"):
                raise AlphaError("History import is available for connected Threads and Instagram accounts.", 404)
            if not metric_schedule.analytics_direct(cur, workspace_id, connection_id):
                raise AlphaError("Connect this account for insights first.", 409, code="analytics_required")
            if purge_pending(cur, workspace_id, connection_id):
                raise AlphaError("Rafii is still removing this account's earlier imported history. Try again in a few minutes.", 409,
                                 code="history_purge_pending")
            cur.execute("""INSERT INTO public.pr_history_imports(workspace_id,connection_id,provider,requested_by) VALUES(%s,%s,%s,%s)
                           ON CONFLICT (workspace_id,connection_id) WHERE status IN ('pending','running') DO NOTHING""",
                        (workspace_id, connection_id, found[0], actor))
            return self._status(cur, workspace_id, connection_id)

    def status(self, workspace_id, token, connection_id):
        from ..hosted import _membership
        from ..permissions import require
        with self.oauth.repository.transaction(token, workspace_id) as (cur, row, actor):
            require(_membership(row), "read")
            return self._status(cur, workspace_id, connection_id)

    @staticmethod
    def _status(cur, workspace_id, connection_id):
        cur.execute("""SELECT id::text,status,pages,posts,failure_class,extract(epoch from created_at)::float8 FROM public.pr_history_imports
                       WHERE workspace_id=%s AND connection_id=%s ORDER BY created_at DESC LIMIT 1""", (workspace_id, connection_id))
        row = cur.fetchone()
        if not row:
            return {"connectionId": connection_id, "status": "none"}
        return {"connectionId": connection_id, "importId": row[0], "status": row[1], "pages": row[2], "posts": row[3],
                "failure": row[4], "requestedAt": row[5], "windowDays": WINDOW_DAYS}

    # --- cron step --------------------------------------------------------------------------------------------------
    def claim(self, limit):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("""UPDATE public.pr_history_imports h SET status='running', lease_owner=%s, lease_until=now() + make_interval(secs => %s),
                                  attempts=attempts+1, updated_at=now()
                           WHERE h.id IN (SELECT id FROM public.pr_history_imports
                                          WHERE status='pending' OR (status='running' AND (lease_until IS NULL OR lease_until < now()))
                                          ORDER BY updated_at LIMIT %s FOR UPDATE SKIP LOCKED)
                           RETURNING h.id::text, h.workspace_id::text, h.connection_id, h.provider, h.cursor, h.pages, h.attempts,
                                     extract(epoch from h.created_at)::float8""", (self.worker_id, LEASE_SECONDS, limit))
            rows = cur.fetchall()
            db.commit()
        keys = ("id", "workspaceId", "connectionId", "provider", "cursor", "pages", "attempts", "createdAt")
        return [dict(zip(keys, r)) for r in rows]

    def _eligible(self, run):
        with self.connection_factory() as db, db.cursor() as cur:
            if funding_mode(cur,run["workspaceId"])!='legacy': return False
            cur.execute("SELECT state ? 'accountDeletion' FROM public.pr_workspaces WHERE id=%s", (run["workspaceId"],))
            found = cur.fetchone()
            return (bool(found) and not found[0] and metric_schedule.analytics_direct(cur, run["workspaceId"], run["connectionId"])
                    and not purge_pending(cur, run["workspaceId"], run["connectionId"]))

    def _finish(self, run, status, failure=None, backoff_seconds=None, refund=False):
        """Close the run, or (with backoff_seconds) hand it back keeping its cursor. `refund` returns the attempt the
        claim took when the run was handed back without trying (deadline), so deferral never fails a run."""
        with self.connection_factory() as db, db.cursor() as cur:
            if backoff_seconds is not None:   # keep the run and its cursor; claimable again once the lease lapses
                cur.execute("""UPDATE public.pr_history_imports SET lease_until=now() + make_interval(secs => %s), lease_owner=NULL, failure_class=%s,
                                      attempts=CASE WHEN %s THEN greatest(0, attempts-1) ELSE attempts END, updated_at=now()
                               WHERE id=%s::uuid AND lease_owner=%s AND status='running'""",
                            (backoff_seconds, failure, refund, run["id"], self.worker_id))
            else:
                cur.execute("""UPDATE public.pr_history_imports SET status=%s, failure_class=%s, lease_owner=NULL, lease_until=NULL, updated_at=now()
                               WHERE id=%s::uuid AND lease_owner=%s AND status='running'""", (status, failure, run["id"], self.worker_id))
            db.commit()

    def _store_page(self, run, page, cutoff, done, failure=None):
        """Posts, their backfill readings and the cursor in one transaction fenced on the lease. `failure` stores the
        page and then fails the run with that class. Returns the stored count, or None if the lease was lost."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT 1 FROM public.pr_history_imports WHERE id=%s::uuid AND lease_owner=%s AND status='running' FOR UPDATE",
                        (run["id"], self.worker_id))
            if not cur.fetchone() or purge_pending(cur, run["workspaceId"], run["connectionId"]):
                db.rollback()   # lease lost, or the account was disconnected: store nothing more
                return None
            stored = 0
            for post in page["posts"]:
                if post["publishedAt"] is None or post["publishedAt"] < cutoff:
                    continue
                cur.execute("""INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,published_at,media_type,
                                                                 media_product_type,permalink,caption_chars,source)
                               VALUES(%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,'history_import')
                               ON CONFLICT (workspace_id,provider,provider_post_id) DO UPDATE SET connection_id=excluded.connection_id,
                                 media_type=excluded.media_type, media_product_type=excluded.media_product_type, permalink=excluded.permalink,
                                 caption_chars=excluded.caption_chars, updated_at=now()""",
                            (run["workspaceId"], run["connectionId"], run["provider"], post["id"], post["publishedAt"], post["mediaType"],
                             post["mediaProductType"], post["permalink"], post["captionChars"]))
                metric_schedule.schedule(cur, run["workspaceId"], run["connectionId"], run["provider"], post["id"], None,
                                         post["publishedAt"], "history_import", BACKFILL)   # due at once; anchor = publish time
                stored += 1
            cur.execute("""UPDATE public.pr_history_imports SET cursor=%s, pages=pages+1, posts=posts+%s, status=%s, failure_class=%s,
                                  attempts=0, updated_at=now(), lease_owner=CASE WHEN %s THEN NULL ELSE lease_owner END,
                                  lease_until=CASE WHEN %s THEN NULL ELSE lease_until END
                           WHERE id=%s::uuid""",   # a failure always has done=True (no next page), so `done` closes the lease
                        (page["next"], stored, "failed" if failure else ("done" if done else "running"), failure, done, done, run["id"]))
            db.commit()
        return stored

    def run_one(self, run, deadline):
        """Advance one run by up to PAGES_PER_TICK pages. Returns a short outcome string; never raises."""
        try:
            if not self._eligible(run):
                self._finish(run, "cancelled", "not_eligible")
                return "cancelled"
            grant = self.oauth.token_for_worker(run["workspaceId"], run["connectionId"])
        except AlphaError as error:
            if getattr(error, "status", None) in (404, 409):
                self._finish(run, "failed", "credential")
                return "failed"
            return self._retry(run, "transport")
        except Exception:  # noqa: BLE001 - one run must not stop the step
            return self._retry(run, "error")
        cutoff = run["createdAt"] - WINDOW_DAYS * 86400
        cursor, pages = run["cursor"], run["pages"]
        for _ in range(PAGES_PER_TICK):
            if self.monotonic() >= deadline:
                break
            try:
                if not self._eligible(run):
                    self._finish(run,"cancelled","not_eligible")
                    return "cancelled"
                page = list_page(self.transport, run["provider"], grant["accessToken"], cursor)
            except HistoryHTTP as error:
                if error.status in (400, 401, 403, 404):
                    self._finish(run, "failed", f"http_{error.status}")
                    return "failed"
                return self._retry(run, f"http_{error.status}")
            except AlphaError:
                return self._retry(run, "transport")
            except Exception:  # noqa: BLE001
                return self._retry(run, "error")
            pages += 1
            oldest = min((p["publishedAt"] for p in page["posts"] if p["publishedAt"] is not None), default=None)
            exhausted = pages >= MAX_PAGES or (oldest is not None and oldest < cutoff)   # nothing further is wanted
            done = page["next"] is None or exhausted
            failure = "incomplete_paging" if page["incomplete"] and not exhausted else None
            try:
                stored = self._store_page(run, page, cutoff, done, failure)
            except Exception as error:  # noqa: BLE001 - the page's transaction rolled back; retry from the same cursor
                metric_schedule._note("history_import.store_failed", error)
                return self._retry(run, "store")
            if stored is None:
                return "lost_lease"
            run["attempts"] = 0          # the stored page reset the run's attempts; keep the in-memory copy in step
            if failure:
                return "failed"
            if done:
                return "done"
            cursor = page["next"]
        self._finish(run, "running", None, backoff_seconds=0)
        return "continued"

    def _retry(self, run, failure):
        if run["attempts"] >= MAX_ATTEMPTS:
            self._finish(run, "failed", failure)
            return "failed"
        self._finish(run, "running", failure, backoff_seconds=metric_schedule.backoff(run["id"], run["attempts"]))
        return "retry"

    def tick(self, max_runs=2, max_seconds=20.0):
        counts = {"status": "ok", "claimed": 0}
        try:
            deadline = self.monotonic() + max_seconds
            runs = self.claim(max_runs)
            counts["claimed"] = len(runs)
            for run in runs:
                if self.monotonic() >= deadline:
                    self._finish(run, "running", None, backoff_seconds=0, refund=True)
                    counts["deferred"] = counts.get("deferred", 0) + 1
                    continue
                outcome = self.run_one(run, deadline)
                counts[outcome] = counts.get(outcome, 0) + 1
        except Exception as error:  # noqa: BLE001 - later cron steps must still run
            metric_schedule._note("history_import.tick_failed", error)
            counts["status"] = "unavailable"
        return counts
