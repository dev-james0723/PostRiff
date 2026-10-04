"""Growth Phase 0 history import and verified-job backfill on the disposable PostgreSQL loaded by rls.sql.

A confirmed request by a connection manager creates one import run per connection; the cron step pages through the
account's own posts (synthetic transport), keeps metadata and caption length only (no text, no hash), schedules one
backfill reading per post inside the 90-day window, and the metric step then reads them. Rate limits keep the cursor,
401 fails the run, and disconnecting purges what was imported. The operator backfill schedules one reading for
recent verified jobs that have none, dry-run by default.

    POSTRIFF_PG_BIN=... python scripts/postriff_pg_suite.py postgres_growth_history
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import account_pictures
from postriff_phase2.growth import backfill as B
from postriff_phase2.growth import history_import as H
from postriff_phase2.growth import metric_schedule as M
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.providers import ThreadsProvider

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TOKENS = {"fixture-one": ONE}
CONN = "conn-threads-history"
checks = []
now = time.time()


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required", 401)
    return TOKENS[token]


def refused(status, call):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return error
    raise AssertionError(f"expected HTTP {status}")


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(ts))


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
service = HostedWorkspaceService(connection, verify)
service.oauth.providers["threads"] = ThreadsProvider("synthetic-client", "synthetic-secret", production_reviewed=True)
service.oauth.token_for_worker = lambda ws, conn: {"accessToken": "synthetic-token", "provider": "threads", "scopes": sorted(M.NATIVE_ANALYTICS_SCOPES["threads"])}


class Transport:
    def __init__(self):
        self.replies, self.urls = [], []

    def __call__(self, method, url, **kw):
        self.urls.append((url, kw.get("headers")))
        return self.replies.pop(0)


transport = Transport()
importer = H.HistoryImporter(connection, service.oauth, transport=transport, worker_id="hi-a")

refused(400, lambda: importer.request(wid, "fixture-one", CONN, {}))
refused(404, lambda: importer.request(wid, "fixture-one", CONN, {"confirmed": True}))
with connection() as db:
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) "
               "VALUES(%s,%s,'threads','acct','sealed','k1',ARRAY['threads_basic','threads_manage_insights'])", (wid, CONN))
assert refused(409, lambda: importer.request(wid, "fixture-one", CONN, {"confirmed": True})).code == "analytics_required"
with connection() as db:
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')", (wid, CONN))
first = importer.request(wid, "fixture-one", CONN, {"confirmed": True})
second = importer.request(wid, "fixture-one", CONN, {"confirmed": True})
assert first["status"] == "pending" and second["importId"] == first["importId"], (first, second)
assert importer.status(wid, "fixture-one", CONN)["importId"] == first["importId"]
refused(401, lambda: importer.status(wid, "stranger", CONN))
checks.append("an import needs a confirmed request, a live Threads/Instagram credential and Direct analytics; one active run per connection")

caption = "今日練琴三個鐘 private words"
page1 = {"status": 200, "body": {"data": [{"id": "h1", "timestamp": iso(now - 3600), "media_type": "TEXT_POST", "permalink": "https://www.threads.net/@a/post/h1", "text": caption},
                                         {"id": "h2", "timestamp": iso(now - 5 * 86400), "media_type": "IMAGE", "permalink": "http://insecure.example/h2"}],
                                "paging": {"cursors": {"after": "CUR1"}, "next": "https://graph.threads.net/next"}}}
page2 = {"status": 200, "body": {"data": [{"id": "h3", "timestamp": iso(now - 80 * 86400), "media_type": "TEXT_POST", "text": "x"},
                                         {"id": "h4", "timestamp": iso(now - 120 * 86400), "media_type": "TEXT_POST", "text": "old"}],
                                "paging": {"cursors": {"after": "CUR2"}, "next": "https://graph.threads.net/next2"}}}
transport.replies = [{"status": 429, "body": {}}]
assert importer.tick()["retry"] == 1
with connection() as db:
    run = db.execute("SELECT status, cursor, failure_class, lease_until > now() FROM public.pr_history_imports").fetchone()
    db.execute("UPDATE public.pr_history_imports SET lease_until=now() - interval '1 second'")
assert run == ("running", None, "http_429", True), run
transport.replies = [page1, page2]
result = importer.tick()
assert result.get("done") == 1, result
with connection() as db:
    owned = db.execute("SELECT provider_post_id, caption_chars, permalink FROM public.pr_owned_posts ORDER BY provider_post_id").fetchall()
    columns = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_name='pr_owned_posts'").fetchall()}
    reads = db.execute("SELECT provider_post_id, read_offset, source, due_at <= now(), job_id FROM public.pr_metric_reads ORDER BY provider_post_id").fetchall()
    run = db.execute("SELECT status, pages, posts, cursor FROM public.pr_history_imports").fetchone()
    stored_text = db.execute("SELECT count(*) FROM public.pr_owned_posts WHERE row_to_json(pr_owned_posts)::text LIKE '%%private words%%'").fetchone()[0]
assert [o[0] for o in owned] == ["h1", "h2", "h3"], owned
assert owned[0][1] == len(caption) and owned[1][2] is None and stored_text == 0, owned
assert not any("caption" in c and c != "caption_chars" for c in columns), columns
assert reads == [(p, "backfill", "history_import", True, None) for p in ("h1", "h2", "h3")], reads
assert run == ("done", 2, 3, "CUR2"), run
assert "/me/threads?" in transport.urls[1][0] and "after=CUR1" in transport.urls[2][0]
checks.append("the import pages newest-first, stops at the 90-day window, keeps metadata and caption length only (no text, no guessable hash, no insecure link) and schedules one backfill reading per post")

metric_transport = Transport()
metric_transport.replies = [{"status": 200, "body": {"data": [{"name": "views", "total_value": {"value": n}}]}} for n in (10, 20, 30)]
readings = M.MetricScheduler(connection, service.oauth, transport=metric_transport, workspace_allowlist={wid}).tick()
with connection() as db:
    obs = db.execute("SELECT provider_post_id, value FROM public.pr_metric_observations WHERE metric='views' AND read_offset='backfill' AND job_id IS NULL ORDER BY value").fetchall()
assert readings["done"] == 3 and len(obs) == 3, (readings, obs)
checks.append("the metric step reads the imported posts; their observations carry read_offset backfill and no job")

with connection() as db:
    db.execute("UPDATE public.pr_history_imports SET status='done'")
    db.execute("INSERT INTO public.pr_history_imports(workspace_id,connection_id,provider) VALUES(%s,%s,'threads')", (wid, CONN))
transport.replies = [{"status": 401, "body": {}}]
assert importer.tick().get("failed") == 1
with connection() as db:
    failed = db.execute("SELECT status, failure_class FROM public.pr_history_imports WHERE status='failed'").fetchone()
assert failed == ("failed", "http_401"), failed
checks.append("a 401 fails the run instead of retrying")

def fresh_run(attempts):
    with connection() as db:
        db.execute("UPDATE public.pr_history_imports SET status='done' WHERE status IN ('pending','running')")
        return db.execute("INSERT INTO public.pr_history_imports(workspace_id,connection_id,provider,attempts) VALUES(%s,%s,'threads',%s) RETURNING id::text",
                          (wid, CONN, attempts)).fetchone()[0]


def run_state(run_id):
    with connection() as db:
        return db.execute("SELECT status, attempts, failure_class, pages FROM public.pr_history_imports WHERE id::text=%s", (run_id,)).fetchone()


more = {"status": 200, "body": {"data": [{"id": "h5", "timestamp": iso(now - 7200), "text": "y"}],
                                "paging": {"cursors": {"after": "N1"}, "next": "https://graph.threads.net/n"}}}
run_id = fresh_run(H.MAX_ATTEMPTS - 1)                 # four earlier failures; this claim is the fifth attempt
transport.replies = [more, {"status": 503, "body": {}}]
assert importer.tick().get("retry") == 1
assert run_state(run_id)[:3] == ("running", 0, "http_503"), run_state(run_id)
checks.append("progress resets a run's attempts: a transient error right after a stored page retries instead of failing the run")

run_id = fresh_run(2)
late = H.HistoryImporter(connection, service.oauth, transport=transport, worker_id="hi-b", monotonic=iter([0.0, 100.0, 100.0]).__next__)
assert late.tick(max_seconds=20).get("deferred") == 1
assert run_state(run_id)[:2] == ("running", 2), run_state(run_id)
checks.append("a run handed back at the step's deadline keeps its attempt count")

with connection() as db:
    db.execute("UPDATE public.pr_history_imports SET lease_until=now() - interval '1 second' WHERE id::text=%s", (run_id,))
broken = H.HistoryImporter(connection, service.oauth, transport=transport, worker_id="hi-c")
def explode(*args):
    raise psycopg.errors.CheckViolation("synthetic")
broken._store_page = explode
transport.replies = [more]
result = broken.tick()
assert result["status"] == "ok" and result.get("retry") == 1 and run_state(run_id)[:3] == ("running", 3, "store"), (result, run_state(run_id))
checks.append("a database error while storing a page retries that run from the same cursor without failing the cron step")

with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "h9", None, now, "history_import", (("backfill", 0),))
    cur.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,source) VALUES(%s,%s,'threads','h9','history_import')", (wid, CONN))
    removed = account_pictures.guarded(cur, H.purge_connection, wid, CONN)
    db.commit()
with connection() as db:
    left = db.execute("SELECT (SELECT count(*) FROM public.pr_owned_posts), (SELECT count(*) FROM public.pr_metric_observations WHERE job_id IS NULL), "
                      "(SELECT status FROM public.pr_metric_reads WHERE provider_post_id='h9')").fetchone()
assert removed == 5 and left == (0, 0, None), (removed, left)   # h1-h3, h5, h9; the import's reading rows are deleted
checks.append("disconnect purges imported posts, their observations and their reading rows, and cancels other pending readings")

run_id = fresh_run(0)
transport.replies = [{"status": 200, "body": {"data": [{"id": "h1", "timestamp": iso(now - 3600), "text": "again"}], "paging": {}}}]
assert importer.tick().get("done") == 1
with connection() as db:
    again = db.execute("SELECT status, source FROM public.pr_metric_reads WHERE provider_post_id='h1'").fetchall()
assert again == [("pending", "history_import")], again
checks.append("after disconnect and reconnect a new import schedules readings for the same posts again")

reader = M.MetricScheduler(connection, service.oauth, transport=metric_transport, workspace_allowlist={wid}, worker_id="mr-race")
late_rows = [r for r in reader.claim(10) if r["postId"] == "h1"]
with connection() as db, db.cursor() as cur:
    H.purge_connection(cur, wid, CONN)                        # disconnect lands while the reading is in flight
    db.commit()
assert reader.complete(late_rows[0], {"state": "done", "found": {"views": 1}, "endpoint": "x"}) is False
with connection() as db:
    leaked = db.execute("SELECT count(*) FROM public.pr_metric_observations WHERE provider_post_id='h1' AND job_id IS NULL").fetchone()[0]
assert leaked == 0, leaked
with connection() as db, db.cursor() as cur:
    cur.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,source) VALUES(%s,%s,'threads','hr','history_import')", (wid, CONN))
    M.schedule(cur, wid, CONN, "threads", "hr", None, now, "history_import", (("backfill", 0),))
    db.commit()
first = [r for r in reader.claim(10) if r["postId"] == "hr"]
assert reader.complete(first[0], {"state": "done", "found": {"views": 3}, "endpoint": "x"}) is True   # completes first
with connection() as db, db.cursor() as cur:
    H.purge_connection(cur, wid, CONN)
    db.commit()
    leaked = db.execute("SELECT count(*) FROM public.pr_metric_observations WHERE provider_post_id='hr'").fetchone()[0]
assert leaked == 0, leaked
checks.append("a reading completing around a disconnect never leaves observations behind, in either order")

with connection() as db, db.cursor() as cur:
    cur.execute("DELETE FROM public.pr_auth_throttle")   # this script makes more import requests than one person's hourly allowance
    cur.execute("UPDATE public.pr_history_imports SET status='done' WHERE status IN ('pending','running')")
    cur.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,source,updated_at) VALUES(%s,%s,'threads','old-imp','history_import',now() - interval '1 hour')", (wid, CONN))
    cur.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,source) VALUES(%s,%s,'threads','new-imp','history_import')", (wid, CONN))
    M.schedule(cur, wid, CONN, "threads", "own-post", "job-own", now, "verification", (("24h", 86400),))
    cur.execute("INSERT INTO public.pr_growth_purges(workspace_id,connection_id,requested_at) VALUES(%s,%s,now() - interval '20 minutes')", (wid, CONN))
    db.commit()
assert refused(409, lambda: importer.request(wid, "fixture-one", CONN, {"confirmed": True})).code == "history_purge_pending"
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "blocked-imp", None, now - 60, "history_import", (("backfill", 0),))
    M.schedule(cur, wid, CONN, "threads", "rafii-post", "job-rafii", now - 60, "backfill", (("backfill", 0),))
    cur.execute("UPDATE public.pr_metric_reads SET status='cancelled' WHERE provider_post_id='rafii-post'")
    M.schedule(cur, wid, CONN, "threads", "rafii-post", None, now - 60, "history_import", (("backfill", 0),))   # an import lists Rafii's post
    db.commit()
    kept_source = db.execute("SELECT source, job_id FROM public.pr_metric_reads WHERE provider_post_id='rafii-post'").fetchone()
assert kept_source == ("backfill", "job-rafii"), kept_source
blocked = M.MetricScheduler(connection, service.oauth, transport=metric_transport, workspace_allowlist={wid}, worker_id="mr-blocked").tick()
with connection() as db:
    states = dict(db.execute("SELECT provider_post_id, status FROM public.pr_metric_reads WHERE provider_post_id IN ('blocked-imp','rafii-post')").fetchall())
    waiting = db.execute("SELECT failure_class, due_at > now() FROM public.pr_metric_reads WHERE provider_post_id='rafii-post'").fetchone()
assert states == {"blocked-imp": "cancelled", "rafii-post": "pending"} and waiting == ("purge_pending", True), (states, waiting, blocked)
with connection() as db:
    stuck = db.execute("INSERT INTO public.pr_history_imports(workspace_id,connection_id,provider,status) VALUES(%s,%s,'threads','running') RETURNING id::text", (wid, CONN)).fetchone()[0]
assert importer.tick().get("cancelled") == 1 and run_state(stuck)[0] == "cancelled", run_state(stuck)
from postriff_phase2.operational_signals import snapshot
assert snapshot(connection)["counts"]["historyPurgesPending"] == 1, "owed purges are visible whatever the flags say"
swept = H.sweep_pending_purges(connection)
with connection() as db:
    imported = db.execute("SELECT count(*) FROM public.pr_owned_posts WHERE connection_id=%s AND source='history_import'", (CONN,)).fetchone()[0]
    own = db.execute("SELECT status FROM public.pr_metric_reads WHERE provider_post_id='own-post'").fetchone()[0]
    markers = db.execute("SELECT count(*) FROM public.pr_growth_purges").fetchone()[0]
assert swept == {"status": "ok", "purged": 1, "failed": 0} and (imported, own, markers) == (0, "pending", 0), (swept, imported, own, markers)
with connection() as db:
    rafii = db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE provider_post_id='rafii-post'").fetchone()[0]
assert rafii == 1, "a reading of Rafii's own post is never deleted as import data"
assert importer.request(wid, "fixture-one", CONN, {"confirmed": True})["status"] == "pending"
checks.append("an owed disconnect purge blocks imports and cancels import readings while Rafii's own readings wait and retry; it is retried by the flag-independent cron sweep, removes all import-derived data but never the readings of Rafii's own posts (reviving a row never relabels a job's reading), then imports work again")

with connection() as db:
    db.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,source,updated_at) VALUES(%s,'conn-busy-000','threads','busy','history_import',now() - interval '1 hour')", (wid,))
    db.execute("INSERT INTO public.pr_growth_purges(workspace_id,connection_id) VALUES(%s,'conn-busy-000')", (wid,))
holder = connection()
holder.execute("SELECT 1 FROM public.pr_owned_posts WHERE provider_post_id='busy' FOR UPDATE")   # another session holds the rows
started = time.monotonic()
busy = H.sweep_pending_purges(connection)
holder.rollback()
holder.close()
with connection() as db:
    marker = db.execute("SELECT attempts, failure_class, next_attempt_at > now() + interval '30 seconds' FROM public.pr_growth_purges WHERE connection_id='conn-busy-000'").fetchone()
assert busy["failed"] == 1 and marker == (1, "LockNotAvailable", True) and time.monotonic() - started < 8, (busy, marker)
again = H.sweep_pending_purges(connection)
assert again == {"status": "ok", "purged": 0, "failed": 0}, again   # backing off: not retried every minute
checks.append("a purge blocked by another session gives up after the 2 s lock timeout, records why and backs off instead of stalling the cron")

run_id = fresh_run(0)
transport.replies = [{"status": 200, "body": {"data": [{"id": "hk", "timestamp": iso(now - 600)}], "paging": {"next": "https://graph.threads.net/n"}}}]
assert importer.tick().get("failed") == 1 and run_state(run_id) == ("failed", 0, "incomplete_paging", 1), run_state(run_id)
with connection() as db:
    kept = db.execute("SELECT count(*) FROM public.pr_owned_posts WHERE provider_post_id='hk'").fetchone()[0]
assert kept == 1
checks.append("a next page without a cursor keeps that page's posts, then fails the run instead of reporting a partial import as done")

jobs = [
    {"id": "j-recent", "providerReference": "v1", "verification": {"at": now - 10 * 86400}, "manifest": {"platform": "Threads", "channelId": CONN}},
    {"id": "j-old", "providerReference": "v2", "verification": {"at": now - 100 * 86400}, "manifest": {"platform": "Threads", "channelId": CONN}},
    {"id": "j-read", "providerReference": "v-read", "verification": {"at": now - 86400}, "manifest": {"platform": "Threads", "channelId": CONN}},
    {"id": "j-linkedin", "providerReference": "v3", "verification": {"at": now - 86400}, "manifest": {"platform": "LinkedIn", "channelId": CONN}},
    {"id": "j-unverified", "providerReference": "v4", "verification": None, "manifest": {"platform": "Threads", "channelId": CONN}},
]
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state = jsonb_set(coalesce(state,'{}'::jsonb), '{phase2}', %s::jsonb) WHERE id=%s",
               (json.dumps({"jobs": jobs}), wid))
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "v-read", "j-read", now - 86400, "verification")   # already has readings
    db.commit()
dry = B.backfill_verified_jobs(connection, now=now)
with connection() as db:
    none_yet = db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE provider_post_id='v1'").fetchone()[0]
applied = B.backfill_verified_jobs(connection, now=now, apply=True)
again = B.backfill_verified_jobs(connection, now=now, apply=True)
with connection() as db:
    v1 = db.execute("SELECT read_offset, source, job_id, extract(epoch from anchor_at)::bigint FROM public.pr_metric_reads WHERE provider_post_id='v1'").fetchall()
assert (dry["eligible"], dry["scheduled"], none_yet) == (1, 0, 0), (dry, none_yet)
assert (applied["candidates"], applied["scheduled"], again["eligible"]) == (2, 1, 0), (applied, again)
assert [r[:3] for r in v1] == [("backfill", "backfill", "j-recent")] and abs(v1[0][3] - (now - 10 * 86400)) <= 1, v1
with connection() as db:
    two = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", ("00000000-0000-0000-0000-000000000002",)).fetchone()[0])
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')", (two, CONN))
    db.execute("UPDATE public.pr_workspaces SET state = jsonb_set(coalesce(state,'{}'::jsonb), '{phase2}', %s::jsonb) WHERE id=%s",
               (json.dumps({"jobs": [dict(jobs[0], id="j-two", providerReference="w2")]}), two))
paged = B.backfill_verified_jobs(connection, now=now, batch_size=1, apply=True)
assert paged["batches"] >= 2 and paged["scheduled"] == 1, paged
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE workspace_id=%s AND provider_post_id='w2'", (two,)).fetchone()[0] == 1
checks.append("the operator backfill is dry-run by default and schedules one reading only for recent verified Threads/Instagram jobs without readings")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres; synthetic transport only", "checks": checks}, indent=2))
