"""Fenced reply worker against disposable PostgreSQL and synthetic Threads transport."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import AudienceReplyWorker

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    assert token == "synthetic"
    return ONE


verify.session_id = lambda token, principal: "inbox-worker-synthetic-session"
verify.auth_time = lambda token, principal: clock[0]


class Threads:
    production_reviewed = True

    def capability_scopes(self, capability):
        return {"reply": ["threads_basic", "threads_manage_replies"],
                "comments_read": ["threads_basic", "threads_read_replies"]}.get(capability, [])


service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], providers={"threads": Threads()})
with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
service.bootstrap("synthetic", "studio")
with connection() as db:
    thread = str(db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,'threads-account','threads','123','456','How much?') RETURNING id", (wid,)).fetchone()[0])
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,'threads-account','threads','111','synthetic','synthetic',%s)", (wid, ["threads_basic", "threads_read_replies", "threads_manage_replies"]))
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'threads-account','reply','Direct'),(%s,'threads-account','comments_read','Direct')", (wid, wid))
service.oauth.token_for_worker = lambda *args: {"accessToken": "synthetic-secret", "scopes": ["threads_basic", "threads_manage_replies", "threads_read_replies"]}
calls = []


def transport(method, url, **kwargs):
    calls.append((method, url))
    if method == "GET":
        return {"status": 200, "body": {"data": [{"id": "789", "text": "The price is $10.", "replied_to": {"id": "456"}, "is_reply_owned_by_me": True}]}}
    return {"status": 200, "body": {"id": "777" if url.endswith("/threads") else "789"}}


service.audience.transport = transport
worker_a = AudienceReplyWorker(service.audience)
worker_b = AudienceReplyWorker(service.audience)


def make_draft(text="The price is $10."):
    draft = service.audience.draft_reply(wid, "synthetic", thread, {"origin": "manual", "text": text})
    preview = service.audience.reply_preview(wid, "synthetic", draft["draftId"])
    return draft["draftId"], preview


draft_id, preview = make_draft()
assert service.audience.approve_reply(wid, "synthetic", draft_id, preview["digest"], True)["requiresReconfirmation"] is True
assert worker_a.tick() == {"processed": 0, "execution": "disabled"} and not calls
service.audience.reply_sender_enabled = True
assert worker_a.claim() is None and not calls  # old approval cannot replay
assert service.audience.approve_reply(wid, "synthetic", draft_id, preview["digest"], True)["requiresReconfirmation"] is False
claimed = worker_a.claim()
assert claimed and claimed["draftId"] == draft_id and worker_b.claim() is None
with connection() as db:
    assert db.execute("SELECT status,dispatch_started_at IS NOT NULL FROM public.pr_reply_drafts WHERE id=%s", (draft_id,)).fetchone() == ("submitting", True)
assert calls == []  # durable submitting precedes provider I/O
assert worker_a.dispatch(claimed)
assert [kind for kind, _ in calls] == ["POST", "POST"]
with connection() as db:
    assert db.execute("SELECT status,provider_reference FROM public.pr_reply_drafts WHERE id=%s", (draft_id,)).fetchone() == ("submitted", "789")
assert worker_b.reconcile() == 1
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (draft_id,)).fetchone()[0] == "verified"

second_id, second_preview = make_draft("Another exact reply")
service.audience.approve_reply(wid, "synthetic", second_id, second_preview["digest"], True)
crashed = worker_a.claim()
assert crashed["draftId"] == second_id
before = len(calls)
clock[0] += 181
assert worker_b.recover_stale() == 1
assert worker_b.claim() is None and len(calls) == before
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (second_id,)).fetchone()[0] == "uncertain"

third_id, third_preview = make_draft("Permission check")
service.audience.approve_reply(wid, "synthetic", third_id, third_preview["digest"], True)
third = worker_a.claim()
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id='threads-account' AND capability='reply'", (wid,))
before = len(calls)
assert worker_a.dispatch(third) is False and len(calls) == before
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (third_id,)).fetchone()[0] == "held"

with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id='threads-account' AND capability='reply'", (wid,))
fourth_id, fourth_preview = make_draft("Crash after provider")
service.audience.approve_reply(wid, "synthetic", fourth_id, fourth_preview["digest"], True)
fourth = worker_a.claim()
before = len(calls)
assert worker_a.dispatch(fourth, crash="after_provider")
assert len(calls) == before + 2
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (fourth_id,)).fetchone()[0] == "submitting"
clock[0] += 181
assert worker_b.recover_stale() == 1
assert worker_b.claim() is None and len(calls) == before + 2
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (fourth_id,)).fetchone()[0] == "uncertain"

fifth_id, fifth_preview = make_draft("Inconclusive response")
service.audience.approve_reply(wid, "synthetic", fifth_id, fifth_preview["digest"], True)
fifth = worker_a.claim()
service.audience.transport = lambda method, url, **kwargs: (calls.append((method, url)) or {"status": 503, "body": {}})
before = len(calls)
assert worker_a.dispatch(fifth)
assert len(calls) == before + 1 and worker_b.claim() is None
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (fifth_id,)).fetchone()[0] == "uncertain"

sixth_id, sixth_preview = make_draft("Comment removed")
service.audience.approve_reply(wid, "synthetic", sixth_id, sixth_preview["digest"], True)
sixth = worker_a.claim()
with connection() as db:
    db.execute("UPDATE public.pr_audience_threads SET tombstoned_at=now() WHERE id=%s", (thread,))
before = len(calls)
assert worker_a.dispatch(sixth) is False and len(calls) == before
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (sixth_id,)).fetchone()[0] == "held"

with connection() as db:
    db.execute("UPDATE public.pr_audience_threads SET tombstoned_at=NULL WHERE id=%s", (thread,))
seventh_id, seventh_preview = make_draft("Digest changed")
service.audience.approve_reply(wid, "synthetic", seventh_id, seventh_preview["digest"], True)
with connection() as db:
    db.execute("UPDATE public.pr_reply_drafts SET approval=jsonb_set(approval,'{digest}','\"wrong\"'::jsonb) WHERE id=%s", (seventh_id,))
before = len(calls)
assert worker_a.claim()["held"] is True and len(calls) == before
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (seventh_id,)).fetchone()[0] == "held"

eighth_id, eighth_preview = make_draft("Workspace closed")
service.audience.approve_reply(wid, "synthetic", eighth_id, eighth_preview["digest"], True)
eighth = worker_a.claim()
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{accountDeletion}','{}'::jsonb,true) WHERE id=%s", (wid,))
before = len(calls)
assert worker_a.dispatch(eighth) is False and len(calls) == before
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_reply_drafts WHERE id=%s", (eighth_id,)).fetchone()[0] == "held"

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL; synthetic Threads transport", "checks": ["flag off and old approval fence", "exact reconfirmation", "two workers one claim", "submitting persisted before provider", "two-step send and authoritative read-back", "crash before call becomes uncertain with no resend", "crash after provider becomes uncertain with no resend", "inconclusive provider result has no retry", "capability revoked before dispatch makes zero provider calls", "tombstone before dispatch holds without provider call", "digest mismatch holds without provider call", "workspace deletion fence holds without provider call"]}))
