"""Synthetic reply approvals and comment reads against disposable local PostgreSQL only."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
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
print(json.dumps({"status":"pass","execution":"disposable local PostgreSQL; synthetic transport only","checks":["reply history and counts survive reload","starter line label","record approval with sender disabled","enabling sender cannot replay old approvals","explicit reconfirmation permits synthetic send","ingestion failure preserves transaction"]}))
