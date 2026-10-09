"""Synthetic reply approvals and comment reads against disposable local PostgreSQL only."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(1, str(Path(__file__).resolve().parents[2] / "tests"))
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.contracts import digest
from postriff_alpha.domain import AlphaError
DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
def connection():
    return psycopg.connect(DSN, client_encoding="utf8")
def verify(token):
    assert token == "synthetic"
    return ONE
verify.session_id = lambda token, principal: "audience-synthetic-session-12345"
verify.auth_time = lambda token, principal: time.time()
service = HostedWorkspaceService(connection, verify)
with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
service.bootstrap("synthetic", "studio")
with connection() as db:
    thread = str(db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,'test-channel','threads','123','456','Synthetic comment') RETURNING id", (wid,)).fetchone()[0])
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'test-channel','reply','Direct'),(%s,'test-channel','comments_read','Direct')", (wid,wid))
audience = service.audience
# A suggestion comes only from Rafii's managed AI writer (never fixed text); this harness mounts none, so it is refused
# and nothing is saved.
for origin in ("ai", "ai_fixture"):
    try:
        audience.draft_reply(wid, "synthetic", thread, {"origin": origin})
        raise AssertionError("a suggestion without an AI writer must be refused")
    except AlphaError as error:
        assert error.status == 409 and error.code == "reply_writer_unavailable", (error.status, error.code)
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_reply_drafts WHERE thread_id=%s", (thread,)).fetchone()[0] == 0
draft = audience.draft_reply(wid, "synthetic", thread, {"origin": "manual", "text": "Thanks for coming to the recital!"})
assert draft["label"] == "Your reply" and draft["origin"] == "manual"
manifest = {"provider":"threads","providerAccountId":"123","connectionId":"test-channel","text":draft["text"],"replyToCommentId":"456"}
preview = {"manifest":manifest,"digest":digest(manifest),"replyLevel":"Direct"}
audience.reply_preview = lambda *args: preview
approved = audience.approve_reply(wid, "synthetic", draft["draftId"], preview["digest"], True)
assert approved["requiresReconfirmation"] is True
read = audience.threads(wid, "synthetic")
assert read["counts"] == {"all":1,"replied":1,"unanswered":0}
assert read["threads"][0]["replies"][0]["status"] == "approved"
assert read["threads"][0]["replies"][0]["requiresReconfirmation"] is True
calls = []
def transport(method, url, **kwargs):
    calls.append(method)
    return {"status":200,"body":{"id":"789"}}
audience.transport = transport
audience.oauth.token_for_worker = lambda *args: {"accessToken":"synthetic"}
with connection() as db:
    assert audience.send_approved(db.cursor(),wid,draft["draftId"],time.time())["state"] == "held"
assert calls == []
audience.reply_sender_enabled = True  # test-only; production runtime never enables this
with connection() as db:
    assert audience.send_approved(db.cursor(),wid,draft["draftId"],time.time())["state"] == "held"
assert calls == []
# Reconfirmation is an explicit second approval of this exact manifest.
assert audience.approve_reply(wid,"synthetic",draft["draftId"],preview["digest"],True)["requiresReconfirmation"] is False
with connection() as db:
    assert audience.send_approved(db.cursor(),wid,draft["draftId"],time.time())["state"] == "submitted"
assert calls == ["POST","POST"]
# Ingestion runs only for reviewed supported providers and a SQL failure cannot poison verification.
audience.oauth.providers = {"threads":SimpleNamespace(platform="Threads",production_reviewed=True)}
job = {"manifest":{"platform":"Threads","channelId":"test-channel"},"providerReference":"123"}
with connection() as db:
    def failed_ingest(cur,*args):
        cur.execute("SELECT nonexistent_audience_column")
    audience.ingest_replies = failed_ingest
    audience.on_post_verified(db.cursor(),wid,job)
    assert job["comments"]["availability"] == "unavailable"
    assert db.execute("SELECT 1").fetchone()[0] == 1
# A copilot draft saved before replies were AI-written (a template starter) reads back as a starter, never AI-written.
with connection() as db:
    older = str(db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,'test-channel','threads','123','457','Older comment') RETURNING id", (wid,)).fetchone()[0])
    db.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status,events) VALUES(%s,%s,%s,'copilot','Thanks for asking! [ANSWER: price]','draft',%s::jsonb)",
               (wid, older, ONE, json.dumps([{"state": "draft", "by": "engagement_copilot", "provenance": {"route": {"kind": "deterministic_starter", "methodApplied": False}}}])))
older_thread = next(t for t in audience.threads(wid, "synthetic")["threads"] if t["threadId"] == older)
assert [r["origin"] for r in older_thread["replies"]] == ["ai_fixture"], older_thread["replies"]
growth_checks = []
# Growth Audience: Instagram comments on owned posts, re-synced by the native reading step (growth/comment_sync).
from urllib.parse import urlparse
from postriff_phase2.growth import metric_schedule as M
from postriff_phase2.growth.comment_sync import COMMENT_SCOPES
from postriff_phase2.growth.service import GrowthService
from growth_phase2_fixtures import ENV
TWO = "00000000-0000-0000-0000-000000000002"
IG = "ig-channel"
IG_SCOPES = sorted(M.NATIVE_ANALYTICS_SCOPES["instagram"] | COMMENT_SCOPES["instagram"])
now = time.time()
def stamp(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(time.time() - seconds_ago))
def own_instagram(state, actor):
    state.setdefault("phase2", {})["channels"] = [{"id": IG, "platform": "Instagram", "account": "Synthetic studio", "revoked": False}]
    state["phase2"]["jobs"] = [{"id": "job-ig-1", "state": "verified", "providerReference": "ig-post-1", "verification": {"at": now - 3660, "method": "fixture_lookup"},
                                "manifest": {"platform": "Instagram", "channelId": IG, "payload": {"text": "Synthetic recital notes", "language": "en"}}}]
    return state
service.repository.command(wid, "synthetic", service.repository.get(wid, "synthetic")["revision"], own_instagram)
with connection() as db:
    other = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (TWO,)).fetchone()[0])
    for capability in ("analytics", "comments_read"):
        db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,%s,'Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'", (wid, IG, capability))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'instagram','synthetic-ig','sealed','k1',%s)", (wid, IG, IG_SCOPES))
    db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,%s,'instagram','ig-post-1','igc-2','Another workspace comment')", (other, IG))
pages = {"comments": None}
urls = []
def ig_transport(method, url, **kwargs):
    urls.append(url)
    if urlparse(url).path.endswith("/comments"):
        return pages["comments"]
    return {"status": 200, "body": {"data": [{"name": "reach", "values": [{"value": 0}]}, {"name": "views", "values": [{"value": 3}]}]}}
ig_oauth = SimpleNamespace(providers={"instagram": SimpleNamespace(platform="Instagram", account_scoped_direct=True)},
                           token_for_worker=lambda ws, conn: {"accessToken": "synthetic-ig-token", "provider": "instagram", "scopes": IG_SCOPES})
reader = M.MetricScheduler(connection, ig_oauth, transport=ig_transport, workspace_allowlist={wid}, worker_id="mr-audience")
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, IG, "instagram", "ig-post-1", "job-ig-1", now - 3660, "verification")
    db.commit()
pages["comments"] = {"status": 200, "body": {"data": [
    {"id": "igc-1", "text": "How long do you practise each day?", "username": "never_requested", "timestamp": stamp(1800)},
    {"id": "igc-2", "text": "Which etude should I start with?"}]}}
counts = reader.tick()
assert (counts["done"], counts["missed"], counts["commentsStored"]) == (1, 1, 2), counts
assert all("username" not in u for u in urls) and sum(urlparse(u).path.endswith("/comments") for u in urls) == 1, urls
with connection() as db:
    rows = db.execute("SELECT provider_comment_id,author_handle,text,created_at_provider IS NOT NULL FROM public.pr_audience_threads WHERE workspace_id=%s AND provider='instagram' ORDER BY provider_comment_id", (wid,)).fetchall()
    windows = dict(db.execute("SELECT read_offset,status || ':' || coalesce(failure_class,'') FROM public.pr_metric_reads WHERE workspace_id=%s AND provider_post_id='ig-post-1'", (wid,)).fetchall())
assert rows == [("igc-1", "", "How long do you practise each day?", True), ("igc-2", "", "Which etude should I start with?", False)], rows
assert windows["t0"] == "unavailable:window_missed" and windows["1h"] == "done:", windows
growth_checks.append("the reading step re-reads one bounded Instagram comment page with the 1h reading (the missed t0 window makes no call); no author handle is requested or stored")

with connection() as db:
    db.execute("UPDATE public.pr_audience_threads SET tombstoned_at=now() WHERE workspace_id=%s AND provider_comment_id='igc-1'", (wid,))
    db.execute("UPDATE public.pr_metric_reads SET due_at=now()-interval '1 second' WHERE workspace_id=%s AND provider_post_id='ig-post-1' AND read_offset='24h'", (wid,))
    kept = db.execute("SELECT ingested_at FROM public.pr_audience_threads WHERE workspace_id=%s AND provider_comment_id='igc-2'", (wid,)).fetchone()[0]
pages["comments"] = {"status": 200, "body": {"data": [
    {"id": "igc-1", "text": "Edited after removal"}, {"id": "igc-2", "text": "Which etude should I start with?"}, {"id": "igc-3", "text": "Could you film a slow version?"}]}}
counts = reader.tick()
assert (counts["done"], counts["commentsStored"]) == (1, 1), counts
with connection() as db:
    rows = dict(db.execute("SELECT provider_comment_id,text FROM public.pr_audience_threads WHERE workspace_id=%s AND provider='instagram'", (wid,)).fetchall())
    tombstoned = db.execute("SELECT tombstoned_at IS NOT NULL FROM public.pr_audience_threads WHERE workspace_id=%s AND provider_comment_id='igc-1'", (wid,)).fetchone()[0]
    again = db.execute("SELECT ingested_at FROM public.pr_audience_threads WHERE workspace_id=%s AND provider_comment_id='igc-2'", (wid,)).fetchone()[0]
    theirs = db.execute("SELECT text FROM public.pr_audience_threads WHERE workspace_id=%s AND provider='instagram'", (other,)).fetchall()
assert rows == {"igc-1": "How long do you practise each day?", "igc-2": "Which etude should I start with?", "igc-3": "Could you film a slow version?"}, rows
assert tombstoned and again == kept and theirs == [("Another workspace comment",)], (tombstoned, again, kept, theirs)
growth_checks.append("re-sync is idempotent: a tombstoned comment is never revived or edited, unchanged text is not rewritten, only new comments are added, another workspace is untouched")

with connection() as db:
    db.execute("UPDATE public.pr_metric_reads SET due_at=now()-interval '1 second' WHERE workspace_id=%s AND provider_post_id='ig-post-1' AND read_offset='7d'", (wid,))
race = next(r for r in reader.claim(10) if r["postId"] == "ig-post-1" and r["offset"] == "7d")
pages["comments"] = {"status": 200, "body": {"data": [{"id": "igc-4", "text": "Arrived while access was being removed"}]}}
race_outcome = reader.read(race, {})
assert race_outcome["state"] == "done" and race_outcome["comments"], race_outcome
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s AND capability='comments_read'", (wid, IG))
assert reader.complete(race, race_outcome) is True
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audience_threads WHERE workspace_id=%s AND provider_comment_id='igc-4'", (wid,)).fetchone()[0] == 0
    db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id=%s AND capability='comments_read'", (wid, IG))
growth_checks.append("comment reading revoked between the provider read and commit blocks the comment write inside the fenced completion")

growth = GrowthService(service, env=ENV)
seen = growth.closed_loop.audience(wid, "synthetic")
assert (seen["eligibleComments"], seen["reason"]) == (2, "growth_consent_required"), seen
assert seen["sources"] == {"connections": 1, "commentsReadable": 1, "ownedPosts": 1}, seen["sources"]
assert "Instagram" in seen["coverage"] and "unavailable" not in seen["coverage"], seen["coverage"]
with service.repository.transaction("synthetic", wid) as (cur, row, _):
    texts = [c["text"] for c in growth.closed_loop._comments(cur, wid, row[1], 30)]
assert sorted(texts) == ["Could you film a slow version?", "Which etude should I start with?"] and "Another workspace comment" not in texts, texts
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s AND capability='comments_read'", (wid, IG))
seen = growth.closed_loop.audience(wid, "synthetic")
assert (seen["eligibleComments"], seen["reason"]) == (0, "comments_permission_required"), seen
growth_checks.append("Audience reads Instagram comments on the workspace's own posts only, never another workspace's, and names the missing permission when comment reading is revoked")

print(json.dumps({"status":"pass","execution":"disposable local PostgreSQL; synthetic transport only","checks":["AI suggestions without a managed writer are refused (409 reply_writer_unavailable) and nothing is saved","a template copilot draft reads back as a starter, never AI-written","manual reply labelled 'Your reply'","reply history and counts survive reload","record approval with sender disabled","enabling sender cannot replay old approvals","explicit reconfirmation permits synthetic send","ingestion failure preserves transaction",*growth_checks]}))
