"""Inbox refresh against disposable PostgreSQL and synthetic Threads pages only."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    assert token == "synthetic"
    return ONE


verify.session_id = lambda token, principal: "inbox-sync-synthetic-session"
verify.auth_time = lambda token, principal: clock[0]


class Threads:
    platform = "Threads"
    production_reviewed = True

    def capability_scopes(self, capability):
        return ["threads_basic", "threads_read_replies"] if capability == "comments_read" else []


service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], providers={"threads": Threads()})
with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
service.bootstrap("synthetic", "studio")
job = {"state": "verified", "manifest": {"platform": "Threads", "channelId": "threads-account"},
       "providerReference": "123", "verification": {"at": clock[0]}}
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,jobs}',%s::jsonb,true) WHERE id=%s", (json.dumps([job]), wid))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,'threads-account','threads','111','synthetic','synthetic',%s)", (wid, ["threads_basic", "threads_read_replies"]))
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'threads-account','comments_read','Direct')", (wid,))
service.oauth.token_for_worker = lambda *args: {"accessToken": "synthetic-secret", "scopes": ["threads_basic", "threads_read_replies"]}
calls = []
overlap = []


def transport(method, url):
    assert method == "GET" and "graph.threads.net" in url
    calls.append(url)
    if len(calls) == 1:
        overlap.append(service.audience.sync(wid, "synthetic"))
    if "after=cursor-1" in url:
        return {"status": 200, "body": {"data": [{"id": "456", "text": "How much?", "username": "visitor", "timestamp": "2026-09-28T12:00:00Z"}, {"id": "457", "text": "Thanks!"}], "paging": {}}}
    return {"status": 200, "body": {"data": [{"id": "456", "text": "How much?", "username": "visitor"}, {"id": "456", "text": "How much?"}], "paging": {"cursors": {"after": "cursor-1"}}}}


service.audience.transport = transport
first = service.audience.sync(wid, "synthetic")
assert first["availability"] == "available" and first["checkedPosts"] == 1 and first["pagesRead"] == 2 and first["ingested"] == 2, first
assert overlap[0]["availability"] == "unavailable" and overlap[0]["connections"][0]["availability"] == "cooldown"
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_threads WHERE workspace_id=%s", (wid,)).fetchone()[0] == 2
    stamp = db.execute("SELECT extract(epoch from last_synced_at),last_error_code FROM public.pr_audience_sync WHERE workspace_id=%s", (wid,)).fetchone()
assert stamp[0] is not None and stamp[1] is None

clock[0] += 61
second = service.audience.sync(wid, "synthetic")
assert second["availability"] == "available" and second["ingested"] == 0
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_threads WHERE workspace_id=%s", (wid,)).fetchone()[0] == 2

clock[0] += 61
service.audience.transport = lambda *args: {"status": 429, "body": {"error": "rate limited"}}
failed = service.audience.sync(wid, "synthetic")
assert failed["availability"] == "unavailable" and failed["connections"][0]["errorCode"] == "provider_429", failed
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_threads WHERE workspace_id=%s AND tombstoned_at IS NOT NULL", (wid,)).fetchone()[0] == 0
    assert db.execute("SELECT last_error_code FROM public.pr_audience_sync WHERE workspace_id=%s", (wid,)).fetchone()[0] == "provider_429"

clock[0] += 61
service.audience.transport = lambda *args: (_ for _ in ()).throw(ConnectionError("secret provider token"))
transport_failure = service.audience.sync(wid, "synthetic")
assert transport_failure["connections"][0]["errorCode"] == "provider_transport_error"
assert "secret provider token" not in json.dumps(transport_failure)
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_threads WHERE workspace_id=%s AND tombstoned_at IS NOT NULL", (wid,)).fetchone()[0] == 0

clock[0] += 61
def removed_during_provider_call(method, url):
    with connection() as db:
        db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id='threads-account'", (wid,))
    return {"status": 200, "body": {"data": [{"id": "999", "text": "Should not land"}]}}


service.audience.transport = removed_during_provider_call
removed_mid_sync = service.audience.sync(wid, "synthetic")
assert removed_mid_sync["availability"] == "unavailable" and removed_mid_sync["connections"][0]["errorCode"] == "connection_changed"
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_threads WHERE workspace_id=%s AND provider_comment_id='999'", (wid,)).fetchone()[0] == 0
service.audience.sync_enabled = True
removed = service.audience.scheduled_sync()
assert removed["processed"] == 0, removed
assert service.audience.sync(wid, "synthetic")["availability"] == "unavailable"

new_jobs = [{"state": "verified", "manifest": {"platform": "Threads", "channelId": f"threads-extra-{n}"},
             "providerReference": str(123 + n), "verification": {"at": clock[0]}} for n in (2, 3, 4)]
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    state["phase2"]["jobs"].extend(new_jobs)
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
    for n in (2, 3, 4):
        cid = f"threads-extra-{n}"
        db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'threads',%s,'synthetic','synthetic',%s)",
                   (wid, cid, str(111 + n), ["threads_basic", "threads_read_replies"]))
        db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'comments_read','Direct')", (wid, cid))


def extra_transport(method, url):
    post = url.split("/replies?", 1)[0].rsplit("/", 1)[-1]
    return {"status": 200, "body": {"data": [{"id": post + "99", "text": "A later account"}]}}


service.audience.transport = extra_transport
clock[0] += 61
first_pair = service.audience.sync(wid, "synthetic")
assert first_pair["checkedPosts"] == 2
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_sync WHERE workspace_id=%s AND connection_id LIKE 'threads-extra-%%' AND last_synced_at IS NOT NULL", (wid,)).fetchone()[0] == 2
second_pair = service.audience.sync(wid, "synthetic")
assert any(item["connectionId"] == "threads-extra-4" and item["availability"] == "available" for item in second_pair["connections"]), second_pair
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_sync WHERE workspace_id=%s AND connection_id LIKE 'threads-extra-%%' AND last_synced_at IS NOT NULL", (wid,)).fetchone()[0] == 3
assert len(service.audience.threads(wid, "synthetic")["sync"]) >= 3

with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    assert db.execute("SELECT count(*) FROM public.pr_audience_sync WHERE workspace_id=%s", (wid,)).fetchone()[0] == 4
    try:
        db.execute("DELETE FROM public.pr_audience_sync WHERE workspace_id=%s", (wid,))
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
    else:
        raise AssertionError("Browser role changed sync state")

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL and synthetic Threads pages", "checks": ["manual and concurrent refresh fence", "bounded two-page cursor", "duplicate comment upsert", "durable server freshness", "429 and transport failure never tombstone", "provider exception does not leak secrets", "connection revoked during provider call inserts nothing", "revoked connection excluded from scheduled and manual refresh", "manual bounded refresh rotates through third eligible account", "forced RLS read and write denial"]}))
