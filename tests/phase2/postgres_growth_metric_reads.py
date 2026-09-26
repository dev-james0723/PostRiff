"""Growth Phase 0 metric readings on the disposable PostgreSQL loaded by rls.sql (migration 032).

Scheduling at verification is idempotent and never aborts the verification transaction; the cron step reads due
rows with a synthetic transport, records observations tagged with their read offset, retries transient failures
without writing 'unavailable' rows, closes terminal ones, respects capability and account deletion, is fenced on
its lease and gives back rows it had no time for. RLS: members read their own schedule rows; the browser role cannot
write them or see the AI usage ledger.

    POSTRIFF_PG_BIN=... python scripts/postriff_pg_suite.py postgres_growth_metric_reads
"""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth import metric_schedule as M
from postriff_phase2.growth.usage import PostgresUsageSink, UsageEvent

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
CONN = "conn-threads-1"


def connection():
    return psycopg.connect(DSN)


class OAuth:
    def __init__(self):
        self.providers = {"threads": SimpleNamespace(platform="Threads", production_reviewed=True),
                          "linkedin": SimpleNamespace(platform="LinkedIn", production_reviewed=True)}
        self.calls, self.fail = 0, None

    def token_for_worker(self, workspace_id, connection_id):
        self.calls += 1
        if self.fail:
            raise self.fail
        return {"accessToken": "synthetic-token"}


class Transport:
    def __init__(self):
        self.replies, self.urls = [], []

    def __call__(self, method, url, **kw):
        self.urls.append(url)
        return self.replies.pop(0)


INSIGHTS = {"status": 200, "body": {"data": [{"name": "views", "total_value": {"value": 120}}, {"name": "likes", "values": [{"value": 7}]}]}}
checks = []

with connection() as db:
    wid = db.execute("SELECT workspace_id::text FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0]
    other = db.execute("SELECT workspace_id::text FROM public.pr_memberships WHERE user_id=%s", (TWO,)).fetchone()[0]
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')", (wid, CONN))
    migration = (ROOT / "migrations/postriff/032_growth_metric_reads.sql").read_text(encoding="utf-8")
db = psycopg.connect(DSN, autocommit=True)
db.execute(migration)
db.execute(migration)
db.close()
checks.append("migration 032 applies on top of rls.sql and re-applies as a no-op")

oauth, transport = OAuth(), Transport()
mono = [0.0]
scheduler = M.MetricScheduler(connection, oauth, transport=transport, clock=time.time, monotonic=lambda: mono[0], worker_id="mr-a")
now = time.time()


def job(ref, platform="Threads", channel=CONN):
    return {"id": "job-" + ref, "providerReference": ref, "verification": {"method": "api", "at": now},
            "manifest": {"platform": platform, "channelId": channel}}


with connection() as db, db.cursor() as cur:
    scheduler.on_post_verified(cur, wid, job("p1"))
    scheduler.on_post_verified(cur, wid, job("p1"))                      # replay: idempotent
    scheduler.on_post_verified(cur, wid, job("p2", platform="LinkedIn"))  # no insights for LinkedIn
    scheduler.on_post_verified(cur, wid, job("p3", channel="no-analytics"))
    broken = M.MetricScheduler(connection, None, transport=transport)
    broken.provider_for = lambda platform: 1 / 0                            # a fault inside the hook
    broken.on_post_verified(cur, wid, job("p4"))
    cur.execute("SELECT 1")                                                 # the outer transaction is still usable
    db.commit()
with connection() as db:
    rows = db.execute("SELECT provider_post_id, read_offset, extract(epoch from due_at - anchor_at)::int FROM public.pr_metric_reads ORDER BY 3").fetchall()
assert rows == [("p1", "t0", 0), ("p1", "1h", 3600), ("p1", "24h", 86400), ("p1", "7d", 604800)], rows
checks.append("verification schedules t0/1h/24h/7d once per post, only for Direct-analytics insight providers; a failing hook never aborts the verification transaction")

transport.replies = [INSIGHTS]
result = scheduler.tick()
assert (result["claimed"], result["done"]) == (1, 1), result
with connection() as db:
    obs = db.execute("SELECT metric, availability, value, read_offset, job_id, period_start IS NOT NULL FROM public.pr_metric_observations WHERE provider_post_id='p1' ORDER BY metric").fetchall()
    status = db.execute("SELECT status, last_http_status FROM public.pr_metric_reads WHERE read_offset='t0'").fetchone()
assert len(obs) == 6 and ("views", "available", 120, "t0", "job-p1", True) in obs and ("likes", "available", 7, "t0", "job-p1", True) in obs, obs
assert ("shares", "unavailable", None, "t0", "job-p1", True) in obs and status == ("done", 200), (obs, status)
assert "access_token=synthetic-token" in transport.urls[0] and "/p1/insights" in transport.urls[0]
checks.append("the t0 reading is taken by the cron step and recorded per metric with read_offset t0 and period_start; missing metrics are unavailable, never zero")


def make_due(offset):
    with connection() as db:
        db.execute("UPDATE public.pr_metric_reads SET due_at=now() - interval '1 second' WHERE read_offset=%s", (offset,))


make_due("1h")
transport.replies = [{"status": 429, "body": {}}]
result = scheduler.tick()
with connection() as db:
    row = db.execute("SELECT status, attempts, due_at > now(), failure_class FROM public.pr_metric_reads WHERE read_offset='1h'").fetchone()
    count = db.execute("SELECT count(*) FROM public.pr_metric_observations").fetchone()[0]
assert result["retry"] == 1 and row == ("pending", 1, True, "http_429") and count == 6, (result, row, count)
checks.append("a 429 retries later with backoff and writes no 'unavailable' observations")

make_due("1h")
transport.replies = [{"status": 401, "body": {}}]
scheduler.tick()
make_due("24h")
oauth.fail = AlphaError("revoked", 404)
scheduler.tick()
oauth.fail = None
with connection() as db:
    states = dict(db.execute("SELECT read_offset, status || ':' || coalesce(failure_class,'') FROM public.pr_metric_reads WHERE read_offset IN ('1h','24h')").fetchall())
    count = db.execute("SELECT count(*) FROM public.pr_metric_observations").fetchone()[0]
assert states == {"1h": "unavailable:http_401", "24h": "unavailable:credential"} and count == 6, (states, count)
checks.append("401 and a revoked credential close the reading as unavailable without hiding the earlier real values")

with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", (wid, CONN))
make_due("7d")
calls = oauth.calls
scheduler.tick()
with connection() as db:
    cancelled = db.execute("SELECT status FROM public.pr_metric_reads WHERE read_offset='7d'").fetchone()[0]
    db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", (wid, CONN))
assert cancelled == "cancelled" and oauth.calls == calls, cancelled
checks.append("a connection that lost Direct analytics is cancelled before any token or provider call")

with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "p5", None, now - 10, "backfill", (("backfill", 0),))
    db.commit()
a_rows = scheduler.claim(5)
with connection() as db:
    db.execute("UPDATE public.pr_metric_reads SET lease_until=now() - interval '1 second' WHERE provider_post_id='p5'")
b = M.MetricScheduler(connection, oauth, transport=transport, worker_id="mr-b")
b_rows = b.claim(5)
transport.replies = [INSIGHTS]
assert b.complete(b_rows[0], b.read(b_rows[0], {})) is True
assert scheduler.complete(a_rows[0], {"state": "done", "found": {"views": 1}, "endpoint": "x"}) is False
with connection() as db:
    p5 = db.execute("SELECT count(*), sum(value) FROM public.pr_metric_observations WHERE provider_post_id='p5' AND availability='available'").fetchone()
assert p5 == (2, 127), p5
checks.append("completion is fenced on the lease: an expired worker's late completion writes nothing")

with connection() as db, db.cursor() as cur:
    for ref in ("p6", "p7"):
        M.schedule(cur, wid, CONN, "threads", ref, None, now - 10, "backfill", (("backfill", 0),))
    db.commit()


def slow_read(row, grants):
    mono[0] += 20
    return {"state": "done", "found": {}, "endpoint": "x"}


original, scheduler.read = scheduler.read, slow_read
result = scheduler.tick(max_reads=5, max_seconds=15)
scheduler.read = original
with connection() as db:
    left = db.execute("SELECT status, attempts FROM public.pr_metric_reads WHERE provider_post_id IN ('p6','p7') ORDER BY status").fetchall()
assert result["deferred"] == 1 and left == [("done", 1), ("pending", 0)], (result, left)
checks.append("the step stops at its time budget and gives back unread rows without spending an attempt")

with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state = state || '{\"accountDeletion\": {}}'::jsonb WHERE id=%s", (wid,))
make_due("backfill")
with connection() as db:
    db.execute("UPDATE public.pr_metric_reads SET status='pending' WHERE provider_post_id='p7'")
calls = oauth.calls
scheduler.tick()
with connection() as db:
    p7 = db.execute("SELECT status FROM public.pr_metric_reads WHERE provider_post_id='p7'").fetchone()[0]
    db.execute("UPDATE public.pr_workspaces SET state = state - 'accountDeletion' WHERE id=%s", (wid,))
assert p7 == "cancelled" and oauth.calls == calls, p7
checks.append("a workspace being deleted is never read")

with connection() as db, db.cursor() as cur:
    M.schedule(cur, other, "conn-two", "threads", "q1", None, now, "backfill", (("backfill", 0),))
    PostgresUsageSink(cur).record(UsageEvent(task="postdoctor.judge", model="typesafe-ai/jev", route="primary", status="ok", latency_ms=5,
                                             cost_usd=0.0000042, cost_source="gateway", workspace_id=wid))
    PostgresUsageSink(cur).record(UsageEvent(task="postdoctor.judge", model="typesafe-ai/jev", route="primary", status="timeout", latency_ms=3000,
                                             workspace_id=wid))
    db.commit()
    try:
        cur.execute("INSERT INTO public.pr_model_usage_events(task,model,route,cost_usd_micro,cost_source,latency_ms,status) VALUES('t','m','primary',5,'unknown',1,'ok')")
        raise AssertionError("an unknown cost with a value was accepted")
    except psycopg.errors.CheckViolation:
        db.rollback()
with connection() as db:
    micro = db.execute("SELECT cost_usd_micro, cost_source FROM public.pr_model_usage_events ORDER BY latency_ms").fetchall()
assert micro == [(5, "gateway"), (None, "unknown")], micro
checks.append("the usage ledger stores micro-dollars, keeps unknown cost NULL and rejects a value labelled unknown")

with connection() as db:
    db.execute("set role authenticated")
    db.execute("select set_config('request.jwt.claim.sub', %s, false)", (ONE,))
    mine = db.execute("SELECT count(*) FROM public.pr_metric_reads").fetchone()[0]
    theirs = db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE workspace_id=%s", (other,)).fetchone()[0]
    denied = []
    for statement in ("SELECT count(*) FROM public.pr_model_usage_events",
                      "INSERT INTO public.pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at) VALUES('" + wid + "','c','threads','x','t0','backfill',now(),now())",
                      "INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,source) VALUES('" + wid + "','c','threads','x','history_import')"):
        try:
            db.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            denied.append(True)
            db.rollback()
            db.execute("set role authenticated")
            db.execute("select set_config('request.jwt.claim.sub', %s, false)", (ONE,))
    db.execute("reset role")
assert mine == 7 and theirs == 0 and denied == [True, True, True], (mine, theirs, denied)
checks.append("members read only their own workspace's readings; the browser role cannot write readings or owned posts, or read the usage ledger")

from postriff_phase2 import insights
with connection() as db, db.cursor() as cur:
    endpoint = insights.insights_endpoint("threads", "p8")
    insights.record_observations(cur, wid, CONN, "threads", "p8", "job-p8", {"views": 50, "likes": 2}, endpoint, now - 3600, read_offset="t0")
    insights.record_observations(cur, wid, CONN, "threads", "p8", "job-p8", {"likes": 9}, endpoint, now, read_offset="1h")
    posts = {p["providerPostId"]: p for p in insights.summary(cur, wid, [], now)["posts"]}
    db.commit()
p8 = posts["p8"]["metrics"]
assert (p8["views"]["value"], p8["views"]["readOffset"]) == (50.0, "t0"), p8["views"]
assert (p8["likes"]["value"], p8["likes"]["readOffset"]) == (9.0, "1h"), p8["likes"]
assert p8["shares"]["availability"] == "unavailable" and p8["shares"]["value"] is None
checks.append("analytics keep the latest available value per metric (a later reading missing it never hides it) and say which offset each value was read at")

from postriff_phase2.operational_signals import snapshot
before = snapshot(connection)["counts"]
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "late", None, now - 1200, "backfill", (("backfill", 0),))
    db.commit()
after = snapshot(connection)
assert after["counts"]["metricReadsOverdue"] == before["metricReadsOverdue"] + 1 and after["status"] == "attention", after
assert {"metricReadsDead24h", "historyImportsFailed24h"} <= set(after["counts"]), after["counts"]
checks.append("the cron operations snapshot counts readings overdue by 10 minutes (ids-free aggregate)")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres; synthetic transport only", "checks": checks}, indent=2))
