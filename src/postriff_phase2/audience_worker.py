"""Fenced one-at-a-time Inbox reply dispatch. Uncertain work is never resent."""
from __future__ import annotations

import json
import time
import uuid

from postriff_alpha.domain import AlphaError
from .contracts import digest
from .permissions import Membership
from .inbox_providers import adapter_for

STALE_SECONDS = 180


class AudienceReplyWorker:
    def __init__(self, audience):
        self.audience = audience
        self.connection_factory = getattr(audience.repository, "connection_factory", None) if hasattr(audience, "repository") else None
        self.clock = getattr(audience, "clock", time.time)

    @staticmethod
    def _approval(value):
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, dict) else {}

    def _valid(self, cur, workspace_id, draft_id, approval, text, thread):
        manifest = approval.get("manifest") if isinstance(approval, dict) else None
        if approval.get("requiresReconfirmation", True) or not isinstance(manifest, dict) or digest(manifest) != approval.get("digest"):
            return False, "Exact approval is missing or requires reconfirmation."
        if (manifest.get("workspaceId") != workspace_id or manifest.get("draftId") != draft_id
                or manifest.get("text") != text or manifest.get("textDigest") != digest(text)
                or manifest.get("connectionId") != thread[0] or manifest.get("provider") != thread[1]
                or manifest.get("replyToCommentId") != thread[2] or thread[3]):
            return False, "Reply text, account, comment or source availability changed."
        if manifest.get("provider") != "threads" or not str(manifest.get("providerAccountId") or "").isdigit():
            return False, "This provider has no verified Inbox reply adapter."
        cur.execute("SELECT NOT (state ? 'accountDeletion') FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
        workspace = cur.fetchone()
        if not workspace or not workspace[0]:
            return False, "Workspace is unavailable for reply sending."
        cur.execute("SELECT level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s AND capability='reply'", (workspace_id, thread[0]))
        capability = cur.fetchone()
        if not capability or capability[0] != "Direct":
            return False, "Reply capability is no longer Direct."
        cur.execute("SELECT provider,provider_account_id,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, thread[0]))
        credential = cur.fetchone()
        if not credential or credential[0] != "threads" or credential[1] != manifest["providerAccountId"]:
            return False, "Connection credential is unavailable or changed."
        adapter = self.audience.oauth.providers.get("threads")
        if adapter_for("threads") is None or adapter is None or not adapter.production_reviewed or not set(adapter.capability_scopes("reply")).issubset(credential[2] or []):
            return False, "Provider review or current reply scope is unavailable."
        cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, approval.get("approvedBy")))
        member = cur.fetchone()
        if not member or not Membership.from_row(*member).allows("reply"):
            return False, "Approver no longer has reply permission."
        return True, None

    @staticmethod
    def _event(cur, workspace_id, draft_id, status, now, message, reference=None, dispatch_id=None):
        cur.execute("UPDATE public.pr_reply_drafts SET status=%s,provider_reference=coalesce(%s,provider_reference),events=events||%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id::text=%s" + (" AND dispatch_id=%s" if dispatch_id else ""),
                    (status, reference, json.dumps([{"at": now, "state": status, "message": message}]), workspace_id, draft_id, *((dispatch_id,) if dispatch_id else ())))
        return cur.rowcount == 1

    def claim(self):
        if not self.audience.reply_sender_enabled:
            return None
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT d.id::text,d.workspace_id::text,d.approval,d.text,t.connection_id,t.provider,t.provider_comment_id,t.tombstoned_at IS NOT NULL FROM public.pr_reply_drafts d JOIN public.pr_audience_threads t ON t.id=d.thread_id WHERE d.status='approved' AND coalesce((d.approval->>'requiresReconfirmation')::boolean,true)=false ORDER BY d.created_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT 1")
                row = cur.fetchone()
                if not row:
                    return None
                draft_id, workspace_id, raw_approval, text, *thread = row
                approval = self._approval(raw_approval)
                valid, reason = self._valid(cur, workspace_id, draft_id, approval, text, thread)
                if not valid:
                    self._event(cur, workspace_id, draft_id, "held", self.clock(), reason)
                    return {"held": True, "draftId": draft_id}
                fence = str(uuid.uuid4())
                now = self.clock()
                cur.execute("UPDATE public.pr_reply_drafts SET status='submitting',dispatch_id=%s,dispatch_started_at=to_timestamp(%s),events=events||%s::jsonb,updated_at=now() WHERE id::text=%s AND workspace_id=%s AND status='approved'",
                            (fence, now, json.dumps([{"at": now, "state": "submitting", "message": "Fenced worker claim; no retry after an uncertain outcome."}]), draft_id, workspace_id))
                if cur.rowcount != 1:
                    return None
                return {"draftId": draft_id, "workspaceId": workspace_id, "dispatchId": fence, "manifest": approval["manifest"]}

    def _preflight(self, claimed):
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT d.approval,d.text,d.status,d.dispatch_id,t.connection_id,t.provider,t.provider_comment_id,t.tombstoned_at IS NOT NULL FROM public.pr_reply_drafts d JOIN public.pr_audience_threads t ON t.id=d.thread_id WHERE d.workspace_id=%s AND d.id::text=%s FOR UPDATE OF d", (claimed["workspaceId"], claimed["draftId"]))
                row = cur.fetchone()
                if not row or row[2] != "submitting" or str(row[3]) != claimed["dispatchId"]:
                    return False
                valid, reason = self._valid(cur, claimed["workspaceId"], claimed["draftId"], self._approval(row[0]), row[1], row[4:])
                if not valid or not self.audience.reply_sender_enabled:
                    self._event(cur, claimed["workspaceId"], claimed["draftId"], "held", self.clock(), reason or "Reply sending was disabled before dispatch.", dispatch_id=claimed["dispatchId"])
                    return False
                return True

    def _finish(self, claimed, outcome):
        state = outcome.get("state")
        if state not in ("submitted", "uncertain", "held"):
            state = "uncertain"
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT status FROM public.pr_reply_drafts WHERE workspace_id=%s AND id::text=%s FOR UPDATE", (claimed["workspaceId"], claimed["draftId"]))
                row = cur.fetchone()
                if not row or row[0] != "submitting":
                    return False
                return self._event(cur, claimed["workspaceId"], claimed["draftId"], state, self.clock(), outcome.get("confirmed", "Provider outcome unavailable."), outcome.get("reference"), claimed["dispatchId"])

    def dispatch(self, claimed, *, crash=None):
        if not claimed or claimed.get("held"):
            return False
        if not self._preflight(claimed):
            return False
        try:
            grant = self.audience.oauth.token_for_worker(claimed["workspaceId"], claimed["manifest"]["connectionId"])
        except AlphaError:
            return self._finish(claimed, {"state": "held", "confirmed": "Credential could not be verified before dispatch."})
        adapter = self.audience.oauth.providers.get("threads")
        if adapter is None or not set(adapter.capability_scopes("reply")).issubset(grant.get("scopes") or []):
            return self._finish(claimed, {"state": "held", "confirmed": "Current token lacks verified reply scope."})
        # The final database check is brief and has committed before provider I/O.
        if not self._preflight(claimed):
            return False
        if crash == "before_provider":
            return True
        manifest = claimed["manifest"]
        try:
            outcome = adapter_for(manifest["provider"]).send_reply(manifest, grant["accessToken"], self.audience.transport)
        except Exception:
            outcome = {"state": "uncertain", "confirmed": "Provider call outcome is unknown; do not resend."}
        if crash == "after_provider":
            return True
        return self._finish(claimed, outcome)

    def recover_stale(self, limit=10):
        now = self.clock()
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT id::text,workspace_id::text,dispatch_id FROM public.pr_reply_drafts WHERE status='submitting' AND dispatch_started_at<to_timestamp(%s) ORDER BY dispatch_started_at,id FOR UPDATE SKIP LOCKED LIMIT %s", (now - STALE_SECONDS, limit))
                rows = cur.fetchall()
                for draft_id, workspace_id, dispatch_id in rows:
                    self._event(cur, workspace_id, draft_id, "uncertain", now, "Worker stopped after dispatch intent; reconcile before any new approval.", dispatch_id=str(dispatch_id))
        return len(rows)

    def reconcile(self, limit=3):
        """Read back the exact reply from its parent thread. Missing/error stays submitted."""
        if not self.audience.reply_sender_enabled:
            return 0
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT d.id::text,d.workspace_id::text,d.provider_reference,d.approval FROM public.pr_reply_drafts d WHERE d.status='submitted' AND d.provider_reference IS NOT NULL ORDER BY d.updated_at,d.id LIMIT %s", (limit,))
                rows = cur.fetchall()
        verified = 0
        for draft_id, workspace_id, reference, raw_approval in rows:
            manifest = self._approval(raw_approval).get("manifest") or {}
            try:
                grant = self.audience.oauth.token_for_worker(workspace_id, manifest["connectionId"])
                if not set(self.audience.oauth.providers["threads"].capability_scopes("comments_read")).issubset(grant.get("scopes") or []):
                    continue
                inbox_adapter = adapter_for(manifest.get("provider"))
                if inbox_adapter is None or not inbox_adapter.reconcile_reply(manifest, reference, grant["accessToken"], self.audience.transport):
                    continue
                with self.connection_factory() as db:
                    with db.cursor() as cur:
                        cur.execute("SELECT status FROM public.pr_reply_drafts WHERE workspace_id=%s AND id::text=%s FOR UPDATE", (workspace_id, draft_id))
                        row = cur.fetchone()
                        if row and row[0] == "submitted" and self._event(cur, workspace_id, draft_id, "verified", self.clock(), "Exact reply was read back from Threads.", reference):
                            verified += 1
            except (AlphaError, KeyError, TypeError, ValueError):
                continue
        return verified

    def tick(self, max_jobs=3):
        if not self.audience.reply_sender_enabled:
            return {"processed": 0, "execution": "disabled"}
        uncertain = self.recover_stale()
        processed = 0
        for _ in range(min(max_jobs, 5)):
            claimed = self.claim()
            if not claimed:
                break
            processed += 1
            self.dispatch(claimed)
        verified = self.reconcile()
        return {"processed": processed, "staleHeldUncertain": uncertain, "verified": verified, "execution": "fenced-inbox-worker"}
