"""Audience (architecture §16): truthful limited state. Threads/comments are ingested only for
connections whose `comments_read` capability is Direct; replies need `can_reply` and a Direct
`reply` capability; AI drafts are labelled and never sent by default; sending requires exact
approval (account, thread, final text) and produces separate submit/verify receipts.
"""
import json
from urllib.parse import quote, urlencode
from postriff_alpha.domain import AlphaError, clean, uid
from .contracts import digest
from .permissions import require
from .providers import GRAPH_VERSION

REPLY_LIMIT = 500
COMMENT_READ_PROVIDERS = ("threads",)


class AudienceService:
    def __init__(self, repository, oauth, clock, transport=None, reply_sender_enabled=False):
        self.repository, self.oauth, self.clock, self.transport = repository, oauth, clock, transport
        self.reply_sender_enabled = reply_sender_enabled

    @staticmethod
    def _member(row):
        from .permissions import Membership
        return Membership.from_row(*row[2:7])

    def _capability(self, cur, workspace_id, connection_id, capability):
        cur.execute("SELECT level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s AND capability=%s", (workspace_id, connection_id, capability))
        row = cur.fetchone()
        return row[0] if row else "Unsupported"

    # --- ingestion (server-only) ---------------------------------------------------
    def ingest_replies(self, cur, workspace_id, connection_id, provider, provider_post_id, now):
        if provider not in COMMENT_READ_PROVIDERS or self.transport is None:
            return {"availability": "not_supported", "reason": "Only Threads replies are readable in this release."}
        if self._capability(cur, workspace_id, connection_id, "comments_read") != "Direct":
            return {"availability": "unavailable", "reason": "comments_read is not Direct for this connection."}
        grant = self.oauth.token_for_worker(workspace_id, connection_id)
        response = self.transport("GET", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(provider_post_id)}/replies?" + urlencode({"fields": "id,text,username,timestamp", "access_token": grant["accessToken"]}))
        count = 0
        for item in (response.get("body", {}).get("data", []) if response.get("status") == 200 else []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            cur.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,provider,provider_comment_id) DO UPDATE SET text=excluded.text,ingested_at=now()", (workspace_id, connection_id, provider, provider_post_id, str(item["id"]), clean(item.get("username", ""), 100), clean(item.get("text", ""), 4000)))
            count += 1
        return {"availability": "available" if response.get("status") == 200 else "unavailable", "ingested": count}

    def on_post_verified(self, cur, workspace_id, job):
        manifest = job["manifest"]
        provider = next((pid for pid, adapter in self.oauth.providers.items() if adapter.platform == manifest["platform"] and adapter.production_reviewed), None)
        if provider not in COMMENT_READ_PROVIDERS:
            return
        # A failed ingestion must not abort the transaction that stores publication verification.
        cur.execute("SAVEPOINT audience_ingestion")
        try:
            job["comments"] = self.ingest_replies(cur, workspace_id, manifest["channelId"], provider, job["providerReference"], self.clock())
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT audience_ingestion")
            job["comments"] = {"availability": "unavailable", "reason": "Comment ingestion failed."}
        finally:
            cur.execute("RELEASE SAVEPOINT audience_ingestion")

    # --- customer surface ------------------------------------------------------------
    def threads(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            cur.execute("SELECT id::text,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,extract(epoch from ingested_at),tombstoned_at IS NOT NULL,extract(epoch from created_at_provider) FROM public.pr_audience_threads WHERE workspace_id=%s ORDER BY ingested_at DESC LIMIT 200", (workspace_id,))
            items = []
            for r in cur.fetchall():
                reply_level = self._capability(cur, workspace_id, r[1], "reply")
                cur.execute("SELECT id::text,status,text,origin,extract(epoch from updated_at),coalesce((approval->>'requiresReconfirmation')::boolean,true) FROM public.pr_reply_drafts WHERE workspace_id=%s AND thread_id::text=%s ORDER BY created_at", (workspace_id, r[0]))
                replies = [{"draftId": d[0], "status": d[1], "text": d[2], "origin": d[3], "updatedAt": float(d[4]), "requiresReconfirmation": d[5]} for d in cur.fetchall()]
                items.append({"threadId": r[0], "connectionId": r[1], "provider": r[2], "providerPostId": r[3], "commentId": r[4], "author": r[5], "text": r[6], "ingestedAt": float(r[7]), "tombstoned": bool(r[8]), "replyAvailable": reply_level == "Direct" and self._member(row).allows("reply"), "replyLevel": reply_level, "createdAtProvider": float(r[9]) if r[9] is not None else None, "replies": replies})
            cur.execute("SELECT connection_id,level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability='comments_read'", (workspace_id,))
            capability = [{"connectionId": c, "commentsRead": l} for c, l in cur.fetchall()]
            cur.execute("SELECT count(*),count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.pr_reply_drafts d WHERE d.workspace_id=t.workspace_id AND d.thread_id=t.id AND d.status IN ('approved','submitting','submitted','verified','uncertain'))) FROM public.pr_audience_threads t WHERE workspace_id=%s", (workspace_id,))
            total, answered = cur.fetchone()
            return {"counts": {"all": total, "replied": answered, "unanswered": total - answered}, "replySendingEnabled": self.reply_sender_enabled, "threads": items, "capabilities": capability, "limits": "Automated or bulk replies and moderation are not available in this release; each reply is approved individually."}

    def draft_reply(self, workspace_id, token, thread_id, payload):
        origin = payload.get("origin", "manual")
        if origin not in ("manual", "ai_fixture"):
            raise AlphaError("Choose a manual draft or starter line.")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            cur.execute("SELECT text,author_handle FROM public.pr_audience_threads WHERE id::text=%s AND workspace_id=%s AND tombstoned_at IS NULL", (thread_id, workspace_id))
            thread = cur.fetchone()
            if not thread:
                raise AlphaError("Thread unavailable.", 404)
            if origin == "manual":
                text = clean(payload.get("text", ""), REPLY_LIMIT)
                if not text:
                    raise AlphaError("Write a reply first.")
            else:
                # Deterministic labelled draft; no model call. The user's own text is never overwritten.
                text = clean(f"Thanks for adding this, @{thread[1] or 'there'}. What would you want to see next?", REPLY_LIMIT)
            cur.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status) VALUES(%s,%s,%s,%s,%s,'draft') RETURNING id::text", (workspace_id, thread_id, principal, origin, text))
            return {"draftId": cur.fetchone()[0], "origin": origin, "text": text, "label": "Starter line (not written by AI)" if origin == "ai_fixture" else "Your reply"}

    def reply_preview(self, workspace_id, token, draft_id):
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT d.text,d.status,t.connection_id,t.provider,t.provider_post_id,t.provider_comment_id FROM public.pr_reply_drafts d JOIN public.pr_audience_threads t ON t.id=d.thread_id WHERE d.id::text=%s AND d.workspace_id=%s", (draft_id, workspace_id))
            r = cur.fetchone()
            if not r:
                raise AlphaError("Draft unavailable.", 404)
            cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, r[2]))
            account = cur.fetchone()
            manifest = {"schema": "postriff.reply-approval.v1", "workspaceId": workspace_id, "draftId": draft_id, "connectionId": r[2], "providerAccountId": account[0] if account else None, "provider": r[3], "threadPostId": r[4], "replyToCommentId": r[5], "text": r[0], "textDigest": digest(r[0])}
            return {"manifest": manifest, "digest": digest(manifest), "action": f"Record approval for this reply as {account[0] if account else 'an unconnected account'}", "replyLevel": self._capability(cur, workspace_id, r[2], "reply")}

    def approve_reply(self, workspace_id, token, draft_id, manifest_digest, confirmed):
        preview = self.reply_preview(workspace_id, token, draft_id)
        if preview["digest"] != manifest_digest or confirmed is not True:
            raise AlphaError("Review and confirm this exact reply, account and thread.", 409)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "reply")
            if preview["replyLevel"] != "Direct" or not preview["manifest"]["providerAccountId"]:
                raise AlphaError("Replies are not available for this connection (capability is not Direct).", 409)
            cur.execute("UPDATE public.pr_reply_drafts SET status='approved',approval=%s::jsonb,events=events||%s::jsonb,updated_at=now() WHERE id::text=%s AND workspace_id=%s AND (status='draft' OR (status='approved' AND %s AND coalesce((approval->>'requiresReconfirmation')::boolean,true)))", (json.dumps({"digest": manifest_digest, "approvedBy": principal, "at": self.clock(), "manifest": preview["manifest"], "requiresReconfirmation": not self.reply_sender_enabled}), json.dumps([{"at": self.clock(), "state": "approved"}]), draft_id, workspace_id, self.reply_sender_enabled))
            if cur.rowcount != 1:
                raise AlphaError("This draft was already approved or changed.", 409)
            from .hosted import audit
            audit(cur, workspace_id, principal, "reply.approved", draft_id, {"provider": preview["manifest"]["provider"]})
            return {"draftId": draft_id, "status": "approved", "requiresReconfirmation": not self.reply_sender_enabled, "note": "Approval recorded. Sending is not enabled; confirm this reply again before it can be sent." if not self.reply_sender_enabled else "Approval recorded for sending; provider verification is separate."}

    # --- executor (worker path) -----------------------------------------------------
    def send_approved(self, cur, workspace_id, draft_id, now):
        cur.execute("SELECT approval FROM public.pr_reply_drafts WHERE id::text=%s AND workspace_id=%s AND status='approved' FOR UPDATE", (draft_id, workspace_id))
        row = cur.fetchone()
        if not row:
            return {"state": "held", "confirmed": "No approved reply"}
        if not self.reply_sender_enabled or row[0].get("requiresReconfirmation", True):
            return {"state": "held", "confirmed": "Reconfirm this exact reply after sending is enabled."}
        manifest = row[0]["manifest"]
        if digest(manifest) != row[0]["digest"]:
            return {"state": "held", "confirmed": "Approval digest mismatch"}
        cur.execute("UPDATE public.pr_reply_drafts SET status='submitting',events=events||%s::jsonb,updated_at=now() WHERE id::text=%s", (json.dumps([{"at": now, "state": "submitting"}]), draft_id))
        if manifest["provider"] != "threads" or self.transport is None:
            outcome = {"state": "held", "confirmed": "No reply transport for this provider"}
        else:
            try:
                grant = self.oauth.token_for_worker(workspace_id, manifest["connectionId"])
                user = manifest["providerAccountId"]
                container = self.transport("POST", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(user)}/threads", form={"media_type": "TEXT", "text": manifest["text"], "reply_to_id": manifest["replyToCommentId"], "access_token": grant["accessToken"]})
                cid = str(container.get("body", {}).get("id", ""))
                if container.get("status") == 200 and cid.isdigit():
                    publish = self.transport("POST", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(user)}/threads_publish", form={"creation_id": cid, "access_token": grant["accessToken"]})
                    mid = str(publish.get("body", {}).get("id", ""))
                    outcome = {"state": "submitted", "reference": mid, "confirmed": "Threads returned a reply id; verification pending"} if publish.get("status") == 200 and mid.isdigit() else {"state": "uncertain", "confirmed": f"Reply container {cid} inconclusive; do not resend"}
                elif container.get("status") in (401, 403):
                    outcome = {"state": "held", "confirmed": "Permission rejected"}
                else:
                    outcome = {"state": "uncertain", "confirmed": "No conclusive container; do not resend"}
            except AlphaError as error:
                outcome = {"state": "uncertain", "confirmed": f"Send inconclusive: {error}"}
        cur.execute("UPDATE public.pr_reply_drafts SET status=%s,provider_reference=%s,events=events||%s::jsonb,updated_at=now() WHERE id::text=%s", (outcome["state"], outcome.get("reference"), json.dumps([{"at": now, "state": outcome["state"], "message": outcome["confirmed"]}]), draft_id))
        return outcome
