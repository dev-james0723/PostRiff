"""Audience (architecture §16): truthful limited state. Threads/comments are ingested only for
connections whose `comments_read` capability is Direct; replies need `can_reply` and a Direct
`reply` capability; AI drafts are labelled and never sent by default; sending requires exact
approval (account, thread, final text) and produces separate submit/verify receipts.
"""
import json
from postriff_alpha.domain import AlphaError, clean, uid
from .contracts import digest
from .permissions import require
from .inbox_providers import adapter_for

REPLY_LIMIT = 500
COMMENT_READ_PROVIDERS = ("threads",)


class AudienceService:
    def __init__(self, repository, oauth, clock, transport=None, reply_sender_enabled=False, sync_enabled=False):
        self.repository, self.oauth, self.clock, self.transport = repository, oauth, clock, transport
        self.reply_sender_enabled = reply_sender_enabled
        self.sync_enabled = sync_enabled
        self.engagement_enabled = False
        self._service = None   # set by HostedWorkspaceService; the writer for reply suggestions

    def sync(self, workspace_id, token):
        from .audience_sync import AudienceSync
        return AudienceSync(self).manual(workspace_id, token)

    def scheduled_sync(self, max_connections=2):
        from .audience_sync import AudienceSync
        return AudienceSync(self).scheduled(max_connections)

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
        adapter = adapter_for(provider)
        if adapter is None or self.transport is None:
            return {"availability": "not_supported", "reason": "Only Threads replies are readable in this release."}
        if self._capability(cur, workspace_id, connection_id, "comments_read") != "Direct":
            return {"availability": "unavailable", "reason": "comments_read is not Direct for this connection."}
        grant = self.oauth.token_for_worker(workspace_id, connection_id)
        response = adapter.list_comments(provider_post_id, grant["accessToken"], self.transport)
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
    def threads(self, workspace_id, token, cursor=None, limit=50):
        """One bounded page with batched capability and reply history. Counts cover the workspace."""
        import base64
        import uuid
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AlphaError("Choose a page size from 1 to 100.")
        before = None
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 200:
                    raise ValueError()
                decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if not isinstance(decoded, list) or len(decoded) != 2:
                    raise ValueError()
                before = (float(decoded[0]), str(uuid.UUID(decoded[1])))
            except (ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error):
                raise AlphaError("This Inbox page cursor is invalid.", 400) from None
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            sql = ("SELECT id::text,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,"
                   "extract(epoch from ingested_at),tombstoned_at IS NOT NULL,extract(epoch from created_at_provider),permalink,"
                   "extract(epoch from coalesce(created_at_provider,ingested_at)) "
                   "FROM public.pr_audience_threads WHERE workspace_id=%s")
            params = [workspace_id]
            if before:
                sql += " AND (coalesce(created_at_provider,ingested_at),id)<(to_timestamp(%s),%s::uuid)"
                params.extend(before)
            sql += " ORDER BY coalesce(created_at_provider,ingested_at) DESC,id DESC LIMIT %s"
            params.append(limit + 1)
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            ids = [r[0] for r in rows]
            cur.execute("SELECT connection_id,capability,level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability IN ('reply','comments_read')", (workspace_id,))
            levels = {(connection_id, capability): level for connection_id, capability, level in cur.fetchall()}
            replies_by_thread = {ident: [] for ident in ids}
            if ids:
                cur.execute("SELECT thread_id::text,id::text,status,text,CASE WHEN origin='copilot' AND events->0->'provenance'->'route'->>'kind'='deterministic_starter' THEN 'ai_fixture' ELSE origin END,extract(epoch from updated_at),coalesce((approval->>'requiresReconfirmation')::boolean,true),provider_reference,events FROM public.pr_reply_drafts WHERE workspace_id=%s AND thread_id=ANY(%s::uuid[]) ORDER BY created_at,id", (workspace_id, ids))
                for thread_id, draft_id, status, body, origin, updated, reconfirm, reference, events in cur.fetchall():
                    replies_by_thread[thread_id].append({"draftId": draft_id, "status": status, "text": body, "origin": origin,
                                                          "updatedAt": float(updated), "requiresReconfirmation": reconfirm,
                                                          "providerReference": reference, "events": events if isinstance(events, list) else json.loads(events)})
            items = []
            for r in rows:
                item = {"threadId": r[0], "connectionId": r[1], "provider": r[2], "providerPostId": r[3],
                        "commentId": r[4], "author": r[5], "text": r[6], "ingestedAt": float(r[7]),
                        "tombstoned": bool(r[8]), "replyLevel": levels.get((r[1], "reply"), "Unsupported") if adapter_for(r[2]) else "Unsupported",
                        "createdAtProvider": float(r[9]) if r[9] is not None else None, "permalink": r[10],
                        "replies": replies_by_thread[r[0]]}
                item["replyAvailable"] = item["replyLevel"] == "Direct" and self._member(row).allows("reply")
                if self.engagement_enabled and not item["tombstoned"]:
                    from .coworker.engagement import triage_item
                    item["triage"] = triage_item(item, self.clock())
                items.append(item)
            cur.execute("SELECT count(*),count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.pr_reply_drafts d WHERE d.workspace_id=t.workspace_id AND d.thread_id=t.id AND d.status IN ('approved','submitting','submitted','verified','uncertain'))),count(*) FILTER (WHERE t.tombstoned_at IS NULL AND NOT EXISTS (SELECT 1 FROM public.pr_reply_drafts d WHERE d.workspace_id=t.workspace_id AND d.thread_id=t.id AND d.status IN ('approved','submitting','submitted','verified','uncertain'))) FROM public.pr_audience_threads t WHERE workspace_id=%s", (workspace_id,))
            total, answered, unanswered = cur.fetchone()
            cur.execute("SELECT connection_id,extract(epoch from last_synced_at),last_error_code,last_result FROM public.pr_audience_sync WHERE workspace_id=%s", (workspace_id,))
            sync = [{"connectionId": c, "lastSyncAt": float(at) if at is not None else None, "errorCode": code,
                     "result": result if isinstance(result, dict) else json.loads(result)} for c, at, code, result in cur.fetchall()]
            known_sync = {item["connectionId"] for item in sync}
            sync.extend({"connectionId": connection, "lastSyncAt": None, "errorCode": None, "result": {}}
                        for (connection, name), level in levels.items()
                        if name == "comments_read" and level == "Direct" and connection not in known_sync)
            next_cursor = None
            if has_more and rows:
                next_cursor = base64.urlsafe_b64encode(json.dumps([float(rows[-1][11]), rows[-1][0]]).encode()).decode().rstrip("=")
            capability = [{"connectionId": c, "commentsRead": level} for (c, name), level in levels.items() if name == "comments_read"]
            return {"counts": {"all": total, "replied": answered, "unanswered": unanswered},
                    "replySendingEnabled": self.reply_sender_enabled, "engagementEnabled": self.engagement_enabled,
                    "threads": items, "nextCursor": next_cursor, "capabilities": capability, "sync": sync,
                    "limits": "Automated or bulk replies and moderation are not available in this release; each reply is approved individually."}

    def draft_reply(self, workspace_id, token, thread_id, payload):
        """`manual`: the person's own text. `ai` (or the retired `ai_fixture`): a suggestion written by Rafii's managed
        AI writer (reply_writer), saved as origin `copilot`; never fixed text."""
        origin = payload.get("origin", "manual")
        if origin in ("ai", "ai_fixture"):
            if self._service is None:
                raise AlphaError("Rafii's AI writer isn't available here, so no reply was suggested. Write the reply yourself.", 409, code="reply_writer_unavailable")
            from .coworker.engagement import classify
            with self.repository.transaction(token, workspace_id) as (cur, row, _):
                require(self._member(row), "edit")
                cur.execute("SELECT text FROM public.pr_audience_threads WHERE id::text=%s AND workspace_id=%s AND tombstoned_at IS NULL", (thread_id, workspace_id))
                source = cur.fetchone()
                if not source:
                    raise AlphaError("Thread unavailable.", 404)
                if classify(source[0]) in ("spam", "abusive"):
                    raise AlphaError("Rafii does not suggest replies to spam or abusive comments.", 409)
        if origin not in ("manual", "ai", "ai_fixture"):
            raise AlphaError("Choose your own reply or a suggestion from Rafii.")
        if origin != "manual":
            from . import reply_writer
            written = reply_writer.write(self._service, workspace_id, token, thread_id, model=payload.get("model") if isinstance(payload.get("model"), str) else None)
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(self._member(row), "edit")
                cur.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status,events) VALUES(%s,%s,%s,'copilot',%s,'draft',%s::jsonb) RETURNING id::text",
                            (workspace_id, thread_id, principal, written["text"], json.dumps([{"at": self.clock(), "state": "draft", "by": "inbox_suggestion", "provenance": written["provenance"]}])))
                draft_id = cur.fetchone()[0]
            return {"draftId": draft_id, "origin": "copilot", "text": written["text"], "needs": written["needs"], "label": "Suggested by Rafii's AI writer"}
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            cur.execute("SELECT 1 FROM public.pr_audience_threads WHERE id::text=%s AND workspace_id=%s AND tombstoned_at IS NULL", (thread_id, workspace_id))
            if not cur.fetchone():
                raise AlphaError("Thread unavailable.", 404)
            text = clean(payload.get("text", ""), REPLY_LIMIT)
            if not text:
                raise AlphaError("Write a reply first.")
            cur.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status) VALUES(%s,%s,%s,%s,%s,'draft') RETURNING id::text", (workspace_id, thread_id, principal, origin, text))
            return {"draftId": cur.fetchone()[0], "origin": origin, "text": text, "label": "Your reply"}

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
        # Retained for internal callers that have not migrated. Provider I/O inside the
        # caller's transaction cannot survive a crash without duplicate-send risk.
        # Only AudienceReplyWorker may dispatch an approved reply.
        return {"state": "held", "confirmed": "Use the fenced Inbox reply worker."}
