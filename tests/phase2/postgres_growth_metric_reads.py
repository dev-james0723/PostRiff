"""Growth Phase 0 metric readings on the disposable PostgreSQL loaded by rls.sql (migration 035).

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
        return {"accessToken": "synthetic-token", "provider": "threads", "scopes": sorted(M.NATIVE_ANALYTICS_SCOPES["threads"])}


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
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'threads','synthetic-account','sealed','k1',%s)", (wid, CONN, sorted(M.NATIVE_ANALYTICS_SCOPES['threads'])))
    migration = (ROOT / "migrations/postriff/035_growth_metric_reads.sql").read_text(encoding="utf-8")
db = psycopg.connect(DSN, autocommit=True)
db.execute(migration)
db.execute(migration)
db.close()
checks.append("migration 035 applies on top of rls.sql and re-applies as a no-op")

oauth, transport = OAuth(), Transport()
mono = [0.0]
scheduler = M.MetricScheduler(connection, oauth, transport=transport, workspace_allowlist={wid}, clock=time.time, monotonic=lambda: mono[0], worker_id="mr-a")
now = time.time()


def job(ref, platform="Threads", channel=CONN):
    return {"id": "job-" + ref, "providerReference": ref, "verification": {"method": "api", "at": now},
            "manifest": {"platform": platform, "channelId": channel}}


with connection() as db, db.cursor() as cur:
    scheduler.on_post_verified(cur, wid, job("p1"))
    scheduler.on_post_verified(cur, wid, job("p1"))                      # replay: idempotent
    scheduler.on_post_verified(cur, wid, job("p2", platform="LinkedIn"))  # no insights for LinkedIn
    scheduler.on_post_verified(cur, wid, job("p3", channel="no-analytics"))
    broken = M.MetricScheduler(connection, None, transport=transport, workspace_allowlist={wid})
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
b = M.MetricScheduler(connection, oauth, transport=transport, workspace_allowlist={wid}, worker_id="mr-b")
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

import os
from postriff_phase2.operational_signals import snapshot
os.environ.pop(M.FLAG, None)
os.environ.pop(M.WORKSPACE_ALLOWLIST, None)
assert snapshot(connection)["counts"]["metricReadsOverdue"] == 0, "flag off: leftover rows are not an incident"
os.environ[M.FLAG] = "1"
os.environ[M.WORKSPACE_ALLOWLIST] = wid
before = snapshot(connection)["counts"]
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "late-fresh", "job-late", now - 1200, "verification", (("t0", 0),))
    M.schedule(cur, wid, CONN, "threads", "late-import", None, now - 30 * 86400, "history_import", (("backfill", 0),))
    db.commit()
after = snapshot(connection)
assert after["counts"]["metricReadsOverdue"] == before["metricReadsOverdue"] + 1 and after["status"] == "attention", after
assert after["counts"]["metricBackfillStale"] == before["metricBackfillStale"], "a fresh import's old anchors are not overdue"
os.environ.pop(M.FLAG, None)
os.environ.pop(M.WORKSPACE_ALLOWLIST, None)
checks.append("the operations snapshot counts only fresh readings overdue by 10 minutes, and only while metric reads are on")

with connection() as db, db.cursor() as cur:
    for i in range(30):
        M.schedule(cur, wid, CONN, "threads", f"imp{i}", None, now - 60 * 86400, "history_import", (("backfill", 0),))
    M.schedule(cur, wid, CONN, "threads", "fresh", "job-fresh", now - 5, "verification", (("t0", 0),))
    db.commit()
with connection() as db:
    db.execute("UPDATE public.pr_metric_reads SET status='claimed', lease_owner='mr-dead', lease_until=now() - interval '1 second' WHERE provider_post_id='imp0'")
claimed = M.MetricScheduler(connection, oauth, transport=transport, workspace_allowlist={wid}, worker_id="mr-prio").claim(10)
order = [r["postId"] for r in claimed]
assert order[0] == "imp0" and {"fresh", "late-fresh"} <= set(order[1:4]) and len(order) == 10, order
checks.append("claims take crashed leases, then fresh verification readings, then a large import's backfill, however old its anchors")

with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "p1", "job-p1", now, "verification")
    db.commit()
    revived = dict(db.execute("SELECT read_offset, status FROM public.pr_metric_reads WHERE provider_post_id='p1'").fetchall())
assert revived == {"t0": "done", "1h": "unavailable", "24h": "unavailable", "7d": "pending"}, revived
with connection() as db:
    fresh_mark = db.execute("SELECT scheduled_at > now() - interval '1 minute', created_at < scheduled_at FROM public.pr_metric_reads WHERE provider_post_id='p1' AND read_offset='7d'").fetchone()
assert fresh_mark == (True, True), fresh_mark
checks.append("rescheduling revives only cancelled readings; finished ones are kept")

with connection() as db, db.cursor() as cur:
    insights.record_observations(cur, wid, CONN, "threads", "p8", "job-p8", {"views": 70}, insights.insights_endpoint("threads", "p8"), now, read_offset="24h")
    cur.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at) "
                "VALUES(%s,%s,'threads','legacy1','job-l','views','2026-09',5,'count','available',now())", (wid, CONN))
    display = {p["providerPostId"]: p for p in insights.summary(cur, wid, [], now)["posts"]}
    alike = {p["providerPostId"]: p for p in insights.summary(cur, wid, [], now, basis=insights.COMPARISON_BASIS)["posts"]}
    db.commit()
assert display["p8"]["metrics"]["views"]["value"] == 70.0 and "p1" in display, display["p8"]["metrics"]["views"]
assert alike["p8"]["metrics"]["views"] == dict(alike["p8"]["metrics"]["views"], value=70.0, readOffset="24h")
assert "p1" not in alike and alike["legacy1"]["metrics"]["views"]["value"] == 5.0, sorted(alike)
from postriff_phase2.learning_service import latest_metrics_by_job
with connection() as db, db.cursor() as cur:
    by_job = latest_metrics_by_job(cur, wid)
    trigger = {p["providerPostId"]: p for p in insights.summary(cur, wid, [], now, basis=insights.TRIGGER_BASIS)["posts"]}
assert by_job["job-p8"] == {"views": 70.0} and by_job["job-l"] == {"views": 5.0} and "job-p1" not in by_job, by_job
assert trigger["p8"]["metrics"]["likes"]["value"] == 9.0 and trigger["p8"]["metrics"]["likes"]["readOffset"] == "1h"
checks.append("cross-post consumers read every post at +24h and the strong-post trigger at +1h (legacy rows keep today's behaviour); learning notes compare jobs the same way")

# A warm cron process can reclaim its own expired lease. Worker identity alone
# must not let the earlier invocation write or release the newer attempt.
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "threads", "same-worker-race", "job-race", now - 2, "verification", (("t0", 0),))
first = next(r for r in scheduler.claim(100) if r['postId'] == 'same-worker-race')
with connection() as db:
    db.execute("UPDATE pr_metric_reads SET lease_until=now()-interval '1 second' WHERE id=%s", (first['id'],))
second = next(r for r in scheduler.claim(100) if r['id'] == first['id'])
assert scheduler.complete(first, {'state': 'done', 'found': {'views': 999}, 'endpoint': 'fixture'}) is False
scheduler.release([first])
with connection() as db:
    assert db.execute("SELECT status,attempts FROM pr_metric_reads WHERE id=%s", (second['id'],)).fetchone() == ('claimed', second['attempts'])
    assert db.execute("SELECT count(*) FROM pr_metric_observations WHERE provider_post_id='same-worker-race'").fetchone()[0] == 0
checks.append('same-worker reclamation fences both late completion and stale release by attempt')

with connection() as db:
    db.execute("UPDATE pr_metric_reads SET lease_until=now()-interval '1 second' WHERE id=%s", (second['id'],))
assert scheduler.complete(second, {'state': 'done', 'found': {'views': 999}, 'endpoint': 'fixture'}) is False
checks.append('expired lease cannot append even before another worker reclaims it')

third = next(r for r in scheduler.claim(100) if r['id'] == first['id'])
with connection() as db:
    db.execute("DELETE FROM pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", (wid, CONN))
assert scheduler.complete(third, {'state': 'done', 'found': {'views': 999}, 'endpoint': 'fixture'}) is True
with connection() as db:
    assert db.execute("SELECT status FROM pr_metric_reads WHERE id=%s", (third['id'],)).fetchone()[0] == 'cancelled'
    assert db.execute("SELECT count(*) FROM pr_metric_observations WHERE provider_post_id='same-worker-race'").fetchone()[0] == 0
checks.append('revocation between provider read and commit cancels without appending observations')

with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, 'threads', 'beta-fence', None, now - 10, 'backfill', (('backfill', 0),))
old = next(r for r in scheduler.claim(100) if r['postId'] == 'beta-fence')
with connection() as db:
    db.execute("UPDATE pr_metric_reads SET lease_until=now()-interval '1 second' WHERE id=%s", (old['id'],))
new = next(r for r in scheduler.claim(100) if r['postId'] == 'beta-fence')
outcome = {'state': 'done', 'found': {'views': 999}, 'endpoint': 'fixture://insights'}
assert scheduler.complete(old, outcome) is False, 'same-worker stale attempt must not append'
scheduler.release([old])
with connection() as db:
    assert db.execute('SELECT status,attempts FROM pr_metric_reads WHERE id=%s', (new['id'],)).fetchone() == ('claimed', new['attempts'])
    db.execute("UPDATE pr_metric_reads SET lease_until=now()-interval '1 second' WHERE id=%s", (new['id'],))
assert scheduler.complete(new, outcome) is False, 'expired completion must not append'
new = next(r for r in scheduler.claim(100) if r['postId'] == 'beta-fence')
with connection() as db:
    db.execute("UPDATE pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", (wid, CONN))
assert scheduler.complete(new, outcome) is True
with connection() as db:
    assert db.execute("SELECT count(*) FROM pr_metric_observations WHERE provider_post_id='beta-fence'").fetchone()[0] == 0
    assert db.execute('SELECT status FROM pr_metric_reads WHERE id=%s', (new['id'],)).fetchone()[0] == 'cancelled'
checks.append('same-worker generation and expiry fence completion/release; revocation during HTTP suppresses append')

# Stage 3A admission is independent of the global switch. Even a second tenant with
# genuine-looking Direct capabilities and native grant metadata is never claimed.
with connection() as db, db.cursor() as cur:
    cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'", (other, CONN))
    cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'threads','other-synthetic-account','sealed','k1',%s)", (other, CONN, sorted(M.NATIVE_ANALYTICS_SCOPES['threads'])))
    M.schedule(cur, other, CONN, 'threads', 'denied-tenant', 'job-denied', now-10, 'verification', (('t0', 0),))
    cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'", (wid, CONN))
    scheduler.on_post_verified(cur, other, job('denied-hook'))
assert M.MetricScheduler(connection, oauth, transport=transport).claim(100) == []
assert all(r['workspaceId'] == wid for r in scheduler.claim(100))
with connection() as db:
    denied = db.execute("SELECT status,attempts FROM pr_metric_reads WHERE workspace_id=%s AND provider_post_id='denied-tenant'", (other,)).fetchone()
    denied_hook = db.execute("SELECT count(*) FROM pr_metric_reads WHERE workspace_id=%s AND provider_post_id='denied-hook'", (other,)).fetchone()[0]
assert denied == ('pending', 0) and denied_hook == 0
checks.append('empty allowlist does no work; a Direct-analytics second workspace is never scheduled, claimed or charged an attempt')

row = {'workspaceId': wid, 'connectionId': CONN, 'provider': 'threads', 'postId': 'rights-guard'}
for reason in ('review', 'paused', 'stored_scope', 'credential_provider', 'revoked'):
    with connection() as db:
        db.execute("UPDATE pr_encrypted_credentials SET provider='threads',scopes=%s,revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s", (sorted(M.NATIVE_ANALYTICS_SCOPES['threads']), wid, CONN))
        if reason == 'stored_scope':
            db.execute("UPDATE pr_encrypted_credentials SET scopes=ARRAY['threads_basic'] WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
        elif reason == 'credential_provider':
            db.execute("UPDATE pr_encrypted_credentials SET provider='instagram' WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
        elif reason == 'revoked':
            db.execute("UPDATE pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
    oauth.providers['threads'].production_reviewed = reason != 'review'
    oauth.providers['threads'].execution_enabled = reason != 'paused'
    before_tokens, before_reads = oauth.calls, len(transport.urls)
    assert scheduler.read(row, {})['state'] == 'cancelled', reason
    assert (oauth.calls, len(transport.urls)) == (before_tokens, before_reads), reason
checks.append('provider review/pause, stored native scopes, provider binding and credential revocation suppress token and insights calls')
oauth.providers['threads'].production_reviewed = True
oauth.providers['threads'].execution_enabled = True
with connection() as db:
    db.execute("UPDATE pr_encrypted_credentials SET scopes=%s,revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s", (sorted(M.NATIVE_ANALYTICS_SCOPES['threads']), wid, CONN))

# A real zero is an available observation, while absent native fields remain NULL.
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, 'threads', 'zero-native', 'job-zero-native', now-10, 'verification', (('t0', 0),))
zero_row = next(r for r in scheduler.claim(100) if r['postId'] == 'zero-native')
transport.replies = [{'status': 200, 'body': {'data': [{'name': 'views', 'values': [{'value': 0}]}]}}]
zero_outcome = scheduler.read(zero_row, {})
assert zero_outcome['state'] == 'done', zero_outcome
assert scheduler.complete(zero_row, zero_outcome) is True
with connection() as db:
    actual = dict((m, (a, v)) for m,a,v in db.execute("SELECT metric,availability,value FROM pr_metric_observations WHERE provider_post_id='zero-native'").fetchall())
assert actual['views'] == ('available', 0) and actual['likes'] == ('unavailable', None)
assert scheduler.complete(zero_row, zero_outcome) is False
with connection() as db:
    assert db.execute("SELECT count(*) FROM pr_metric_observations WHERE provider_post_id='zero-native'").fetchone()[0] == 6
checks.append('native observed zero stays available; missing fields stay NULL; completion replay appends nothing')

# Revocation after HTTP cannot commit observations or report a successful read.
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, 'threads', 'scope-race', 'job-scope-race', now-10, 'verification', (('t0', 0),))
race_row = next(r for r in scheduler.claim(100) if r['postId'] == 'scope-race')
transport.replies = [INSIGHTS]
race_outcome = scheduler.read(race_row, {})
with connection() as db:
    db.execute("UPDATE pr_encrypted_credentials SET scopes=ARRAY['threads_basic'] WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
assert scheduler.complete(race_row, race_outcome) is True
assert race_outcome['state'] == 'cancelled'
with connection() as db:
    assert db.execute("SELECT count(*) FROM pr_metric_observations WHERE provider_post_id='scope-race'").fetchone()[0] == 0
    assert db.execute("SELECT status FROM pr_metric_reads WHERE id=%s", (race_row['id'],)).fetchone()[0] == 'cancelled'
checks.append('scope revoked during HTTP prevents append and is counted as cancelled, not done')

# Pinterest reuses this same worker and lease/observation path, with separate enablement and schema gates.
from postriff_phase2.wave3_connectors import PinterestProvider
from postriff_phase2.pinterest_analytics import SCOPES as PIN_SCOPES
from test_hosted_wave1_connectors import Wire, ok
pin_wire = Wire([])
pin_provider = PinterestProvider('1615884', 'SYNTHETIC', transport=pin_wire, production_reviewed=True, analytics_enabled=True)
pin_token = json.dumps({'v':1,'at':'SYNTHETIC','environment':'production','clientId':'1615884','accountId':'1234567','scope':sorted(PIN_SCOPES)})
class PinOAuth:
    providers = {'pinterest':pin_provider}
    calls = 0
    def token_for_worker(self, workspace_id, connection_id):
        self.calls += 1
        return {'provider':'pinterest','accessToken':pin_token,'scopes':sorted(PIN_SCOPES)}
    def _provider_for_access(self, provider, token):
        assert provider == 'pinterest'
        pin_provider._bound(token, 'at')
        return pin_provider
pin_oauth = PinOAuth()
pin_scheduler = M.MetricScheduler(connection, pin_oauth, transport=lambda *a,**k: (_ for _ in ()).throw(AssertionError('raw transport bypass')),
    workspace_allowlist={wid}, worker_id='mr-pin')
assert not pin_scheduler.provider_allowed('pinterest')
with connection() as db:
    db.execute("UPDATE pr_metric_reads SET status='cancelled',lease_owner=NULL,lease_until=NULL WHERE provider='threads' AND status IN ('pending','claimed')")
    db.execute("INSERT INTO pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'conn-pinterest-1','analytics','Direct')", (wid,))
    db.execute("INSERT INTO pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,'conn-pinterest-1','pinterest','1234567','sealed','k1',%s)", (wid,sorted(PIN_SCOPES)))
    assert db.execute("SELECT count(*) FROM pr_metric_reads WHERE provider='pinterest'").fetchone()[0] == 0
migration_pin = (ROOT/'migrations/postriff/20261017_pinterest_metric_reads.sql').read_text()
rollback_pin = (ROOT/'migrations/postriff/20261017_pinterest_metric_reads.rollback.sql').read_text()
with psycopg.connect(DSN,autocommit=True) as db:
    db.execute(migration_pin); db.execute(migration_pin)
    assert pin_scheduler.provider_allowed('pinterest')
    db.execute(rollback_pin)
    assert not pin_scheduler.provider_allowed('pinterest')
    db.execute(migration_pin)
assert pin_scheduler.provider_allowed('pinterest')
with connection() as db,db.cursor() as cur:
    pin_scheduler.on_post_verified(cur,wid,job('1234567',platform='Pinterest',channel='conn-pinterest-1'))
    pin_scheduler.on_post_verified(cur,wid,job('1234567',platform='Pinterest',channel='conn-pinterest-1'))
with connection() as db:
    assert db.execute("SELECT count(*) FROM pr_metric_reads WHERE provider='pinterest'").fetchone()[0] == 4
pin_provider.transport = Wire([ok({'id':'1234567','username':'synthetic'}),ok({'all':{'summary_metrics':{'IMPRESSION':10,'SAVE':0,'PIN_CLICK':3,'OUTBOUND_CLICK':2}}})])
# Transport remains the provider's bound transport, never the generic Meta transport.
result_pin = pin_scheduler.tick(max_reads=1)
assert result_pin['done'] == 1,result_pin
with connection() as db:
    native = db.execute("SELECT metric,availability,value,definition_version,period_start IS NOT NULL FROM pr_metric_observations WHERE provider='pinterest' ORDER BY metric").fetchall()
assert len(native)==4 and all(r[3]=='pinterest-pin-utc-window-v1' and r[4] for r in native),native
assert next(r for r in native if r[0]=='saves')[1:3] == ('available',0)
with connection() as db:
    db.execute("UPDATE pr_metric_reads SET due_at=now()-interval '1second' WHERE provider='pinterest' AND read_offset='1h'")
pin_claim = pin_scheduler.claim(1)[0]
pin_provider.transport = Wire([ok({'id':'1234567','username':'synthetic'}),ok({'all':{'summary_metrics':{'IMPRESSION':15}}})])
pin_outcome = pin_scheduler.read(pin_claim,{})
with connection() as db:
    db.execute("UPDATE pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id='conn-pinterest-1'",(wid,))
assert pin_scheduler.complete(pin_claim,pin_outcome) is True
assert pin_outcome['state']=='cancelled'
with connection() as db:
    assert db.execute("SELECT count(*) FROM pr_metric_observations WHERE provider='pinterest'").fetchone()[0] == 4
before_pin_calls = pin_oauth.calls
other_result = pin_scheduler.read({**pin_claim,'workspaceId':other},{})
assert other_result['state']=='cancelled' and pin_oauth.calls==before_pin_calls
with psycopg.connect(DSN,autocommit=True) as db:
    try:
        db.execute(rollback_pin)
        raise AssertionError('Rollback must preserve existing Pinterest metric rows')
    except psycopg.errors.RaiseException:
        db.execute('ROLLBACK')
assert pin_scheduler.provider_allowed('pinterest')
checks.append('Pinterest flags/review/schema gate, migration idempotency and empty rollback, four idempotent worker offsets, native zero/definitions, existing lease revocation fence, tenant denial, and data-preserving rollback refusal PASS; synthetic provider only')

# Real disposable SQL coverage for analytics result receipts, distinct from provider traffic.
# Restore only this synthetic credential; all existing worker/revocation checks above stay intact.
with connection() as db, db.cursor() as cur:
    cur.execute("UPDATE pr_encrypted_credentials SET revoked_at=NULL WHERE workspace_id=%s AND connection_id='conn-pinterest-1'", (wid,))
    cur.execute("UPDATE pr_metric_reads SET status='cancelled',lease_owner=NULL,lease_until=NULL WHERE provider='pinterest' AND status IN ('pending','claimed')")
    M.schedule(cur,wid,'conn-pinterest-1','pinterest','11223344','job-11223344',time.time()-10,'verification',(('t0',0),))
pin_provider.transport = Wire([ok({'id':'1234567','username':'synthetic'}),ok({'message':'SYNTHETIC_SECRET'})])
failed_pin = pin_scheduler.tick(max_reads=1)
assert failed_pin['retry']==1 and failed_pin['done']==0 and failed_pin['pinterestAnalytics']['read_failed']==1,failed_pin
with connection() as db, db.cursor() as cur:
    cur.execute("SELECT status,failure_class,last_http_status,due_at>now() FROM pr_metric_reads WHERE workspace_id=%s AND provider='pinterest' AND provider_post_id='11223344'", (wid,))
    assert cur.fetchone()==('pending','invalid_response',200,True)
    cur.execute("SELECT count(*) FROM pr_metric_observations WHERE workspace_id=%s AND provider='pinterest' AND provider_post_id='11223344'", (wid,))
    assert cur.fetchone()[0]==0
    receipts,available=insights.latest_read_outcomes(cur,wid)
    first=next(r for r in receipts if r['provider']=='pinterest' and r['providerPostId']=='11223344')
    assert available=='available' and first['outcome']=='read_failed' and first['connectionId']=='conn-pinterest-1' and first['jobId']=='job-11223344',first
    assert 'SYNTHETIC_SECRET' not in json.dumps(receipts)
    # Same provider/post/account-shaped ids in another tenant must not share a receipt.
    cur.execute("""INSERT INTO pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,job_id,read_offset,source,anchor_at,due_at,status,attempts,failure_class,observed_at)
                   VALUES(%s,'conn-pinterest-1','pinterest','11223344','other-job','t0','verification',now(),now(),'done',1,'no_data',now())""", (other,))
    other_receipts,other_available=insights.latest_read_outcomes(cur,other)
    same=next(r for r in other_receipts if r['provider']=='pinterest' and r['providerPostId']=='11223344')
    assert other_available=='available' and same['outcome']=='no_data' and same['jobId']=='other-job'
    own_receipts,_=insights.latest_read_outcomes(cur,wid)
    assert all(r.get('jobId')!='other-job' for r in own_receipts)
    # Hold this retry in the future so the next claim deterministically exercises the existing Pin.
    cur.execute("UPDATE pr_metric_reads SET due_at=now()+interval '1 day' WHERE workspace_id=%s AND provider='pinterest' AND provider_post_id='11223344'", (wid,))
    cur.execute("UPDATE pr_metric_reads SET status='pending',attempts=0,observed_at=NULL,failure_class=NULL,lease_owner=NULL,lease_until=NULL,due_at=now()-interval '1 second' WHERE workspace_id=%s AND provider='pinterest' AND provider_post_id='1234567' AND read_offset='24h'", (wid,))
pin_provider.transport = Wire([ok({'id':'1234567','username':'synthetic'}),ok({'all':{'summary_metrics':{}}})])
empty_pin=pin_scheduler.tick(max_reads=1)
assert empty_pin['done']==1 and empty_pin['providerErrors']==0 and empty_pin['pinterestAnalytics']['no_data']==1,empty_pin
with connection() as db, db.cursor() as cur:
    cur.execute("SELECT status,failure_class,last_http_status FROM pr_metric_reads WHERE workspace_id=%s AND provider='pinterest' AND provider_post_id='1234567' AND read_offset='24h'", (wid,))
    assert cur.fetchone()==('done','no_data',200)
    cur.execute("SELECT availability,value FROM pr_metric_observations WHERE workspace_id=%s AND provider='pinterest' AND provider_post_id='1234567' AND read_offset='24h'", (wid,))
    empty_values=cur.fetchall()
    assert len(empty_values)==4 and all(r==('unavailable',None) for r in empty_values),empty_values
    # A different connection/job with the same provider Pin cannot replace this post's metadata.
    cur.execute("""INSERT INTO pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,job_id,read_offset,source,anchor_at,due_at,status,attempts,failure_class,last_http_status)
                   VALUES(%s,'other-connection','pinterest','1234567','wrong-job','backfill','backfill',now(),now(),'unavailable',1,'http_403',403)""", (wid,))
    summary=insights.summary(cur,wid,[job('1234567',platform='Pinterest',channel='conn-pinterest-1')],time.time())
    native_post=next(p for p in summary['posts'] if p['provider']=='pinterest' and p['providerPostId']=='1234567')
    assert native_post['metrics']['saves']['value']==0 and native_post['metrics']['saves']['availability']=='available',native_post
    assert native_post['latestRead']['outcome']=='no_data' and native_post['latestRead']['jobId']=='job-1234567' and native_post['latestRead']['connectionId']=='conn-pinterest-1',native_post
    assert any(r['providerPostId']=='11223344' and r['outcome']=='read_failed' for r in summary['readOutcomes'])
    assert not any(p['provider']=='pinterest' and p['providerPostId']=='11223344' for p in summary['posts'])
    by_window,available=insights.latest_read_outcomes(cur,wid,basis='24h')
    assert available=='available' and by_window and all(r['readOffset']=='24h' for r in by_window)
# Rename is transaction-local and rolled back: emulate migration 035's absence while
# proving the helper savepoint keeps the outer transaction and old observations usable.
with connection() as db, db.cursor() as cur:
    cur.execute('ALTER TABLE public.pr_metric_reads RENAME TO pr_metric_reads_optional_fixture')
    fallback=insights.summary(cur,wid,[],time.time())
    assert fallback['readOutcomeAvailability']=='unavailable' and fallback['readOutcomes']==[],fallback
    native_post=next(p for p in fallback['posts'] if p['provider']=='pinterest' and p['providerPostId']=='1234567')
    assert native_post['metrics']['saves']['value']==0
    cur.execute('SELECT 1')
    assert cur.fetchone()==(1,)
    db.rollback()
with connection() as db:
    assert db.execute("SELECT to_regclass('public.pr_metric_reads') IS NOT NULL").fetchone()[0]
    db.execute("UPDATE pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id='conn-pinterest-1'", (wid,))
    db.execute("UPDATE pr_metric_reads SET status='cancelled',lease_owner=NULL,lease_until=NULL WHERE provider='pinterest' AND status IN ('pending','claimed')")
checks.append('Pinterest first failed200 persists retry receipt with zero observations; no_data persists done marker and unavailable rather than fabricated zero; prior native zero remains visible; workspace/connection/Pin/job and reporting-window bindings stay separate; missing optional queue schema rolls back only helper savepoint and preserves outer transaction/metrics; synthetic provider only')

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres; synthetic transport only", "checks": checks}, indent=2))
