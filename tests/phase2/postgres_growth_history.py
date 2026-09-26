"""Growth Phase 0 history import and verified-job backfill on the disposable PostgreSQL loaded by rls.sql.

A confirmed request by a connection manager creates one import run per connection; the cron step pages through the
account's own posts (synthetic transport), keeps metadata and a caption hash but never caption text, schedules one
backfill reading per post inside the 90-day window, and the metric step then reads them. Rate limits keep the cursor,
401 fails the run, and disconnecting purges what was imported. The operator backfill schedules one reading for
recent verified jobs that have none, dry-run by default.

    POSTRIFF_PG_BIN=... python scripts/postriff_pg_suite.py postgres_growth_history
"""
import hashlib
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
service.oauth.token_for_worker = lambda ws, conn: {"accessToken": "synthetic-token"}


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
    owned = db.execute("SELECT provider_post_id, caption_sha256, caption_chars, permalink FROM public.pr_owned_posts ORDER BY provider_post_id").fetchall()
    reads = db.execute("SELECT provider_post_id, read_offset, source, due_at <= now(), job_id FROM public.pr_metric_reads ORDER BY provider_post_id").fetchall()
    run = db.execute("SELECT status, pages, posts, cursor FROM public.pr_history_imports").fetchone()
    stored_text = db.execute("SELECT count(*) FROM public.pr_owned_posts WHERE row_to_json(pr_owned_posts)::text LIKE '%%private words%%'").fetchone()[0]
assert [o[0] for o in owned] == ["h1", "h2", "h3"], owned
assert owned[0][1] == hashlib.sha256(caption.encode()).hexdigest() and owned[0][2] == len(caption) and owned[1][3] is None and stored_text == 0, owned
assert reads == [(p, "backfill", "history_import", True, None) for p in ("h1", "h2", "h3")], reads
assert run == ("done", 2, 3, "CUR2"), run
assert "/me/threads?" in transport.urls[1][0] and "after=CUR1" in transport.urls[2][0]
checks.append("the import pages newest-first, stops at the 90-day window, keeps metadata and a caption hash (never the text, never an insecure link) and schedules one backfill reading per post")

metric_transport = Transport()
metric_transport.replies = [{"status": 200, "body": {"data": [{"name": "views", "total_value": {"value": n}}]}} for n in (10, 20, 30)]
readings = M.MetricScheduler(connection, service.oauth, transport=metric_transport).tick()
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
assert removed == 5 and left == (0, 0, "cancelled"), (removed, left)   # h1-h3, h5 and h9
checks.append("disconnect purges imported posts and their observations and cancels pending readings")

jobs = [
    {"id": "j-recent", "providerReference": "v1", "verification": {"at": now - 10 * 86400}, "manifest": {"platform": "Threads", "channelId": CONN}},
    {"id": "j-old", "providerReference": "v2", "verification": {"at": now - 100 * 86400}, "manifest": {"platform": "Threads", "channelId": CONN}},
    {"id": "j-read", "providerReference": "h1", "verification": {"at": now - 86400}, "manifest": {"platform": "Threads", "channelId": CONN}},
    {"id": "j-linkedin", "providerReference": "v3", "verification": {"at": now - 86400}, "manifest": {"platform": "LinkedIn", "channelId": CONN}},
    {"id": "j-unverified", "providerReference": "v4", "verification": None, "manifest": {"platform": "Threads", "channelId": CONN}},
]
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state = jsonb_set(coalesce(state,'{}'::jsonb), '{phase2}', %s::jsonb) WHERE id=%s",
               (json.dumps({"jobs": jobs}), wid))
dry = B.backfill_verified_jobs(connection, now=now)
with connection() as db:
    none_yet = db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE provider_post_id='v1'").fetchone()[0]
applied = B.backfill_verified_jobs(connection, now=now, apply=True)
again = B.backfill_verified_jobs(connection, now=now, apply=True)
with connection() as db:
    v1 = db.execute("SELECT read_offset, source, job_id, extract(epoch from anchor_at)::bigint FROM public.pr_metric_reads WHERE provider_post_id='v1'").fetchall()
assert (dry["eligible"], dry["scheduled"], none_yet) == (1, 0, 0), (dry, none_yet)
assert (applied["candidates"], applied["scheduled"], again["eligible"]) == (2, 1, 0), (applied, again)
assert v1 == [("backfill", "backfill", "j-recent", int(now - 10 * 86400))], v1
checks.append("the operator backfill is dry-run by default and schedules one reading only for recent verified Threads/Instagram jobs without readings")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres; synthetic transport only", "checks": checks}, indent=2))
