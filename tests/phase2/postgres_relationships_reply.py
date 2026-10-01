"""AC14/AC15 through the relationship flow on disposable PostgreSQL with a synthetic Threads transport.

A follow-up adds no sender: the reply to a follow-up's conversation is the existing Inbox path (draft → exact preview /
digest → approve → fenced worker → provider read-back). Changing the text, the account or the reply capability voids an
approval; an uncertain outcome is never resent; a channel without an Inbox reply adapter is assisted and never reported
as a direct success. No real provider is contacted."""
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import flags
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import AudienceReplyWorker
from postriff_phase2.relationships import http as rel_http
from postriff_phase2.relationships import service as rel

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
OWNER = str(uuid.uuid4())
offset = [0.0]
checks = []


def now():
    return time.time() + offset[0]


def connection():
    return psycopg.connect(DSN)


def verify(token):
    if token != OWNER:
        raise AlphaError("Session required.", 401)
    return token


verify.auth_time = lambda *_: time.time()
verify.session_id = lambda token, _principal: "relationships-reply-session-" + token


class Threads:
    production_reviewed = True

    def capability_scopes(self, capability):
        return {"reply": ["threads_basic", "threads_manage_replies"], "comments_read": ["threads_basic", "threads_read_replies"]}.get(capability, [])


def sql(query, *args):
    with connection() as db:
        cur = db.execute(query, args)
        return cur.fetchall() if cur.description else []


def refused(fn, status):
    try:
        fn()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return error
    raise AssertionError(f"expected a {status} refusal")


flags.attach({rel.FLAG: "1"})
hosted = HostedWorkspaceService(connection, verify, clock=now, providers={"threads": Threads()})
service = rel_http.ensure(hosted)
audience = hosted.audience
sql("INSERT INTO auth.users VALUES(%s)", OWNER)
W = hosted.bootstrap(OWNER, "assist")["workspaceId"]
T = sql("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text) "
        "VALUES(%s,'threads-account','threads','123','456','mei','How much is a private lesson?') RETURNING id::text", W)[0][0]
TI = sql("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,permalink) "
         "VALUES(%s,'ig-account','instagram','900','901','lee','Do you teach on weekends?','https://www.instagram.com/p/abc/') RETURNING id::text", W)[0][0]
sql("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) "
    "VALUES(%s,'threads-account','threads','111','synthetic','synthetic',%s),(%s,'ig-account','instagram','333','synthetic','synthetic',%s)",
    W, ["threads_basic", "threads_read_replies", "threads_manage_replies"], W, ["instagram_basic"])
sql("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'threads-account','reply','Direct'),"
    "(%s,'threads-account','comments_read','Direct'),(%s,'ig-account','reply','Direct')", W, W, W)
hosted.oauth.token_for_worker = lambda *args: {"accessToken": "synthetic-secret", "scopes": ["threads_basic", "threads_manage_replies", "threads_read_replies"]}
calls = []
outcome = {"mode": "ok"}


def transport(method, url, **kwargs):
    calls.append((method, url))
    if method == "GET":
        return {"status": 200, "body": {"data": [{"id": "789", "text": "A private lesson is $80.", "replied_to": {"id": "456"}, "is_reply_owned_by_me": True}]}}
    if outcome["mode"] == "inconclusive":
        return {"status": 503, "body": {}}
    return {"status": 200, "body": {"id": "777" if url.endswith("/threads") else "789"}}


audience.transport = transport
worker_a, worker_b = AudienceReplyWorker(audience), AudienceReplyWorker(audience)

follow_up = service.create(W, OWNER, {"idempotencyKey": "rel-reply-0001", "threadId": T, "nextAction": "Quote the lesson price"})["relationship"]
route = follow_up["threads"][0]
assert route["threadId"] == T and route["replyRoute"] == {"kind": "direct", "provider": "threads", "approval": "exact"}


def draft(text):
    made = audience.draft_reply(W, OWNER, route["threadId"], {"origin": "manual", "text": text})
    return made["draftId"], audience.reply_preview(W, OWNER, made["draftId"])


# Exact approval of the follow-up's reply (sender off: recorded, needs reconfirmation, nothing sent).
first_id, first_preview = draft("A private lesson is $80.")
assert first_preview["manifest"]["replyToCommentId"] == "456" and first_preview["manifest"]["providerAccountId"] == "111"
assert audience.approve_reply(W, OWNER, first_id, first_preview["digest"], True)["requiresReconfirmation"] is True
assert worker_a.tick() == {"processed": 0, "execution": "disabled"} and not calls
checks.append("AC14 the follow-up's reply uses the existing draft → exact preview → approval; nothing is sent while the sender is off")

# Editing the text is a new draft: the old digest approves nothing.
edited_id, edited_preview = draft("A private lesson is $85.")
refused(lambda: audience.approve_reply(W, OWNER, edited_id, first_preview["digest"], True), 409)
refused(lambda: audience.approve_reply(W, OWNER, edited_id, edited_preview["digest"], False), 409)
# A different account (destination) changes the digest.
sql("UPDATE public.pr_encrypted_credentials SET provider_account_id='222' WHERE workspace_id=%s AND connection_id='threads-account'", W)
refused(lambda: audience.approve_reply(W, OWNER, edited_id, edited_preview["digest"], True), 409)
sql("UPDATE public.pr_encrypted_credentials SET provider_account_id='111' WHERE workspace_id=%s AND connection_id='threads-account'", W)
# A revoked reply capability refuses approval.
sql("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id='threads-account' AND capability='reply'", W)
refused(lambda: audience.approve_reply(W, OWNER, edited_id, audience.reply_preview(W, OWNER, edited_id)["digest"], True), 409)
assert service.detail(W, OWNER, follow_up["id"])["relationship"]["threads"][0]["replyRoute"]["kind"] == "assisted"
sql("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id='threads-account' AND capability='reply'", W)
checks.append("AC14 changed text, changed account and revoked reply capability each void approval; the follow-up shows the reply as assisted while revoked")

# Sender on: reconfirm the exact manifest; an inconclusive provider outcome is uncertain and never resent.
audience.reply_sender_enabled = True   # test-only; the production switch stays off until its own approval
assert audience.approve_reply(W, OWNER, first_id, audience.reply_preview(W, OWNER, first_id)["digest"], True)["requiresReconfirmation"] is False
outcome["mode"] = "inconclusive"
claimed = worker_a.claim()
assert claimed and claimed["draftId"] == first_id and worker_b.claim() is None
assert worker_a.dispatch(claimed) and len(calls) == 1
assert worker_b.tick()["processed"] == 0 and len(calls) == 1
assert sql("SELECT status FROM public.pr_reply_drafts WHERE id=%s", first_id)[0][0] == "uncertain"
detail = service.detail(W, OWNER, follow_up["id"])["relationship"]
assert detail["threads"][0]["lastReply"]["status"] == "uncertain" and detail["threads"][0]["lastSentAt"] is None
assert detail["suggestion"] is None or detail["suggestion"]["reason"] != "reply_sent"
checks.append("AC14 fenced worker: one claim, an inconclusive outcome stays uncertain with zero resends; the follow-up never counts it as sent")

# Capability revoked between approval and dispatch: held, no provider call.
held_id, held_preview = draft("Weekend lessons are available.")
audience.approve_reply(W, OWNER, held_id, held_preview["digest"], True)
claimed = worker_a.claim()
sql("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id='threads-account' AND capability='reply'", W)
before = len(calls)
assert worker_a.dispatch(claimed) is False and len(calls) == before
assert sql("SELECT status FROM public.pr_reply_drafts WHERE id=%s", held_id)[0][0] == "held"
sql("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id='threads-account' AND capability='reply'", W)
checks.append("AC14 a capability revoked mid-flight holds the reply without any provider call")

# A verified send: read back from the provider; the follow-up may only suggest "replied", never apply it.
outcome["mode"] = "ok"
sent_id, sent_preview = draft("A private lesson is $80.")
audience.approve_reply(W, OWNER, sent_id, sent_preview["digest"], True)
claimed = worker_a.claim()
assert claimed["draftId"] == sent_id and worker_a.dispatch(claimed)
assert worker_b.reconcile() == 1
assert sql("SELECT status,provider_reference FROM public.pr_reply_drafts WHERE id=%s", sent_id)[0] == ("verified", "789")
detail = service.detail(W, OWNER, follow_up["id"])["relationship"]
assert detail["state"] == "new" and detail["threads"][0]["lastSentAt"] is not None
assert (detail["suggestion"]["state"], detail["suggestion"]["reason"], detail["suggestion"]["evidence"]["threadId"]) == ("replied", "reply_sent", T)
applied = service.transition(W, OWNER, follow_up["id"], {"to": "replied", "suggestionKey": detail["suggestion"]["key"], "expectedRevision": detail["revision"]})["relationship"]
assert applied["state"] == "replied"
assert sql("SELECT meta FROM public.pr_relationship_events WHERE relationship_id=%s AND to_state='replied'", follow_up["id"])[0][0] == {"fromSuggestion": True}
checks.append("AC14 a verified reply (exact read-back) lets the follow-up suggest 'replied'; only the person applies it")

# AC15: a channel without an Inbox reply adapter is assisted — even with a Direct capability row it is never a direct success.
other = service.create(W, OWNER, {"idempotencyKey": "rel-reply-0002", "threadId": TI})["relationship"]
instagram = other["threads"][0]
assert instagram["replyRoute"]["kind"] == "assisted" and instagram["replyRoute"]["reason"] == "unsupported_provider"
assert instagram["replyRoute"]["href"] == "https://www.instagram.com/p/abc/" and other["replyRoute"]["kind"] == "assisted"
ig_draft = audience.draft_reply(W, OWNER, TI, {"origin": "manual", "text": "Yes, Saturdays."})["draftId"]
audience.approve_reply(W, OWNER, ig_draft, audience.reply_preview(W, OWNER, ig_draft)["digest"], True)
before = len(calls)
held = worker_a.claim()
assert held == {"held": True, "draftId": ig_draft} and len(calls) == before
assert sql("SELECT status FROM public.pr_reply_drafts WHERE id=%s", ig_draft)[0][0] == "held"
after = service.detail(W, OWNER, other["id"])["relationship"]["threads"][0]
assert after["lastReply"]["status"] == "held" and after["lastSentAt"] is None and after["replyRoute"]["kind"] == "assisted"
checks.append("AC15 an Instagram follow-up is assisted with an honest provider link; an approval there is held with zero provider calls, never shown as sent")

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL; synthetic Threads transport; no live provider", "checks": checks}))
