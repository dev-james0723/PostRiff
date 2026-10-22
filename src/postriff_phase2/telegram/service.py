"""Authenticated Telegram destinations, inbox, operations and secret-free readiness."""
import copy
import hashlib
import json
import hmac
import re
import secrets
import time
import uuid
from postriff_alpha.domain import AlphaError
from ..permissions import require
from ..channels import set_level, unsupported_matrix
from .capabilities import CATALOG, compute, destination_type, provider_capabilities
from .content import fields, formatted, integer, keyboard, fail
from .publishing import snapshot


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TelegramService:
    def __init__(self, oauth, assets=None, clock=time.time):
        self.oauth, self.repository, self.vault = oauth, oauth.repository, oauth.vault
        self.assets, self.clock = assets, clock
        provider = oauth.providers.get("telegram")
        if provider is not None:
            provider.credential_resolver = self.resolve_bot
            provider.file_check = self.check_file
            provider.business_resolver = self.business_context
            provider.destination_authorizer=self.check_destination
        from .direct_messages import ChannelDirectMessages
        self.channel_dms=ChannelDirectMessages(self)
        from .managed import ManagedBots
        self.managed=ManagedBots(self)
        if hasattr(self.repository, 'before_save'):
            self.repository.before_save.append(self.fence_jobs)

    def fence_jobs(self, cur, workspace, before, after, actor):
        """Keep private acceptance jobs invisible to a concurrently running old worker."""
        from .canary_worker import fence_job, owner_active, preserve_fence, selected, worker_scope
        previous = {job['id']: job for job in before.get('phase2', {}).get('jobs', [])}
        jobs = after.get('phase2', {}).get('jobs', [])
        for job in jobs:
            preserve_fence(job, previous.get(job['id']))
        provider = self.oauth.providers.get('telegram')
        if not getattr(provider, 'candidate_mode', False):
            return
        changed = [job for job in jobs if job.get('manifest', {}).get('platform') == 'Telegram'
                   and job.get('state') not in ('verified', 'failed', 'canceled', 'held')
                   and (job['id'] not in previous
                        or job.get('approvalDigest') != previous[job['id']].get('approvalDigest')
                        or job.get('approvedBy') != previous[job['id']].get('approvedBy')
                        or previous[job['id']].get('state') == 'held')]
        if not changed:
            return
        scope = worker_scope(getattr(provider, 'candidate_scope', None), self.clock())
        if (workspace, actor) != (scope['workspaceId'], scope['actorId']) or not owner_active(cur, scope):
            raise AlphaError('This Telegram acceptance approval is unavailable.', 403, code='telegram_canary_actor')
        cur.execute("""SELECT connection_id FROM public.pr_telegram_destinations WHERE workspace_id=%s
            AND bot_id=%s AND chat_id=ANY(%s::bigint[]) AND mode='bot' AND revoked_at IS NULL""",
                    (workspace, scope['botId'], scope['chatIds']))
        connection_ids = [row[0] for row in cur.fetchall()]
        for job in changed:
            if not selected(job, scope, connection_ids):
                raise AlphaError('This Telegram destination is outside owner acceptance.', 403, code='telegram_canary_destination')
            fence_job(job, scope)

    def resolve_bot(self, workspace, bot_ref):
        if not isinstance(bot_ref, str) or not re.fullmatch(r"[0-9a-f-]{36}", bot_ref): raise AlphaError("Bot credential unavailable.", 404)
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                self.ready(cur)
                cur.execute("SELECT token_ciphertext,webhook_ciphertext,key_id FROM public.pr_telegram_bot_grants WHERE workspace_id=%s AND id=%s AND revoked_at IS NULL", (workspace, bot_ref))
                row = cur.fetchone()
                if not row: raise AlphaError("Bot credential unavailable.", 404)
        from ..social_connectors import TelegramConnector
        parent = self.oauth.providers.get("telegram")
        child = TelegramConnector(self.vault.decrypt(row[0], row[2]), self.vault.decrypt(row[1], row[2]), self.oauth.public_base_url, transport=parent.transport if parent else None, production_reviewed=bool(parent and parent.production_reviewed))
        child.bot_ref, child.file_check = bot_ref, self.check_file
        child.business_resolver = self.business_context
        child.destination_authorizer=self.check_destination
        child.acceptance = parent.acceptance if parent else {}
        child.candidate_mode = getattr(parent, 'candidate_mode', False)
        child.candidate_scope = parent.candidate_scope if parent else {}
        return child

    def connect_bot(self, workspace, token, body, *, preview=False):
        from ..hosted import _membership, audit
        from ..social_connectors import TelegramConnector
        body = fields(body, ("token", "botId", "confirmed"), "BotFather bot connection")
        raw = body.get("token")
        if not isinstance(raw, str) or not re.fullmatch(r"\d{5,16}:[A-Za-z0-9_-]{30,64}", raw): fail("Enter the BotFather token in the secure token field.")
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections"); self.ready(cur)
            self.repository.assert_fresh(token, actor)
        hook = secrets.token_urlsafe(32)
        parent = self.oauth.providers.get("telegram")
        child = TelegramConnector(raw, hook, self.oauth.public_base_url, transport=parent.transport if parent else None)
        me = child.me()
        identity = {"botId": str(me["id"]), "username": me["username"], "externalAction": "Configure a Rafii webhook for this bot", "requiredConfirmation": True}
        if preview: return identity
        if body.get("confirmed") is not True or str(body.get("botId")) != str(me["id"]): fail("Confirm the exact BotFather bot shown in the connection preview.")
        ciphertext, key = self.vault.encrypt(raw)
        hook_ct, _ = self.vault.encrypt(hook)
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections")
            cur.execute("SELECT id::text,workspace_id::text,token_ciphertext,key_id,revoked_at FROM public.pr_telegram_bot_grants WHERE bot_id=%s FOR UPDATE", (me["id"],))
            existing = cur.fetchone()
            if existing:
                if existing[1] != workspace: raise AlphaError("Bot connection unavailable.", 409)
                # No duplicate registration/webhook mutation on retries.
                if existing[4] is None and hmac.compare_digest(self.vault.decrypt(existing[2],existing[3]),raw):
                    return {**identity, "botRef": existing[0], "status": "already_registered", "nextAction": "Start destination authorization"}
                bot_ref = existing[0]
                cur.execute("UPDATE public.pr_telegram_bot_grants SET token_ciphertext=%s,webhook_ciphertext=%s,key_id=%s,revoked_at=NULL WHERE workspace_id=%s AND id=%s",(ciphertext,hook_ct,key,workspace,bot_ref))
            else:
                cur.execute("INSERT INTO public.pr_telegram_bot_grants(workspace_id,bot_id,username,token_ciphertext,webhook_ciphertext,key_id) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id::text", (workspace, me["id"], me["username"], ciphertext, hook_ct, key))
                bot_ref = cur.fetchone()[0]
            audit(cur, workspace, actor, "telegram.bot.connected", bot_ref, {"botId": me["id"]})
        child.bot_ref = bot_ref
        try:
            child.ensure_webhook(force=True)
            status = "webhook_confirmed"
        except AlphaError:
            status = "webhook_outcome_unknown"
        return {**identity, "botRef": bot_ref, "status": status, "nextAction": "Start destination authorization" if status == "webhook_confirmed" else "Inspect webhook before retrying configuration"}

    def own_webhook(self, bot_ref, secret, raw):
        if not isinstance(bot_ref,str) or not re.fullmatch(r'[0-9a-f-]{36}',bot_ref): raise AlphaError('Webhook unavailable.',404)
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                self.ready(cur)
                cur.execute("SELECT workspace_id::text,webhook_ciphertext,key_id FROM public.pr_telegram_bot_grants WHERE id=%s AND revoked_at IS NULL", (bot_ref,))
                row = cur.fetchone()
                if not row: raise AlphaError("Webhook unavailable.", 404)
                expected = self.vault.decrypt(row[1], row[2])
                if not isinstance(secret, str) or not hmac.compare_digest(secret, expected): raise AlphaError("Webhook authorization failed.", 401)
        return self.oauth.telegram_webhook(secret, raw, adapter=self.resolve_bot(row[0], bot_ref))

    def bots(self, workspace, token):
        from ..hosted import _membership
        with self.repository.transaction(token,workspace) as (cur,row,_):
            require(_membership(row),'manage_connections'); self.ready(cur)
            cur.execute('SELECT id::text,bot_id,username FROM public.pr_telegram_bot_grants WHERE workspace_id=%s AND revoked_at IS NULL ORDER BY connected_at DESC',(workspace,))
            return {'bots':[{'botRef':r[0],'botId':str(r[1]),'username':r[2]} for r in cur.fetchall()]}

    def disconnect_bot(self, workspace, token, bot_ref, body):
        from ..hosted import _membership, audit
        if fields(body,('confirmed',),'bot revocation').get('confirmed') is not True: fail('Confirm disconnecting this bot and all its Rafii destinations.')
        with self.repository.transaction(token,workspace) as (cur,row,actor):
            require(_membership(row),'manage_connections'); self.repository.assert_fresh(token,actor); self.ready(cur)
            cur.execute('SELECT bot_id,revoked_at FROM public.pr_telegram_bot_grants WHERE workspace_id=%s AND id=%s FOR UPDATE',(workspace,bot_ref))
            grant=cur.fetchone()
            if not grant: raise AlphaError('Bot connection unavailable.',404)
            if grant[1] is not None: return {'disconnected':True,'remoteWebhookState':'not_retried'}
            bot_id=grant[0]
        provider=self.resolve_bot(workspace,bot_ref)
        with self.repository.transaction(token,workspace) as (cur,row,actor):
            require(_membership(row),'manage_connections'); self.repository.assert_fresh(token,actor)
            cur.execute("UPDATE public.pr_telegram_bot_grants SET revoked_at=now(),token_ciphertext='',webhook_ciphertext='',key_id='' WHERE workspace_id=%s AND id=%s AND revoked_at IS NULL RETURNING id",(workspace,bot_ref))
            if not cur.fetchone(): return {'disconnected':True,'remoteWebhookState':'not_retried'}
            cur.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id IN (SELECT connection_id FROM public.pr_telegram_destinations WHERE workspace_id=%s AND bot_id=%s)',(workspace,workspace,bot_id))
            cur.execute('UPDATE public.pr_telegram_destinations SET revoked_at=now() WHERE workspace_id=%s AND bot_id=%s',(workspace,bot_id))
            cur.execute('UPDATE public.pr_telegram_business_connections SET enabled=false,rafii_consented=false WHERE workspace_id=%s AND bot_id=%s',(workspace,bot_id))
            audit(cur,workspace,actor,'telegram.bot.revoked',bot_ref,{'botId':bot_id})
        try:
            remote=provider.call('deleteWebhook',{'drop_pending_updates':False}) is True
        except Exception: remote=False
        return {'disconnected':True,'remoteWebhookState':'confirmed_removed' if remote else 'outcome_unknown','nextStep':'Revoke the token in BotFather if the credential was compromised.'}

    def check_file(self, workspace, file, session):
        provider = self.oauth.providers["telegram"].for_session(session)
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                self.ready(cur)
                cur.execute("SELECT id::text,kind FROM public.pr_telegram_files WHERE workspace_id=%s AND bot_id=%s AND file_id=%s", (workspace, provider.me()["id"], file.get("fileId")))
                row = cur.fetchone()
                return bool(row and row[1] == file.get("kind") and (not file.get("recordId") or row[0] == file["recordId"]))

    def check_destination(self,workspace,session):
        parent=session.get('parentConnectionId')
        if not parent:return True
        with self.repository.connection_factory() as db:
            row=db.execute('SELECT d.connection_id FROM public.pr_telegram_destinations d JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) WHERE d.workspace_id=%s AND d.connection_id=%s AND d.revoked_at IS NULL AND c.revoked_at IS NULL',(workspace,parent)).fetchone()
            return bool(row)

    def files(self, workspace, token, connection):
        provider, _, _, _ = self.grant(workspace, token, connection)
        with self.repository.transaction(token, workspace) as (cur, _, _):
            self.ready(cur)
            cur.execute("SELECT id::text,file_id,kind,descriptor FROM public.pr_telegram_files WHERE workspace_id=%s AND bot_id=%s ORDER BY created_at DESC LIMIT 100", (workspace, provider.me()["id"]))
            return {"files": [{"recordId": r[0], "fileId": r[1], "kind": r[2], "descriptor": r[3]} for r in cur.fetchall()]}

    def business_context(self, workspace, business_id, chat_id):
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                self.ready(cur)
                cur.execute("SELECT identity,bot_id FROM public.pr_telegram_business_connections WHERE workspace_id=%s AND business_connection_id=%s AND enabled=true AND rafii_consented=true", (workspace, business_id))
                row = cur.fetchone()
                if not row: raise AlphaError("Business connection unavailable or revoked.", 409)
                cur.execute("SELECT message_ciphertext,key_id,date FROM public.pr_telegram_business_inbox WHERE workspace_id=%s AND bot_id=%s AND business_connection_id=%s AND chat_id=%s AND deleted=false AND date >= extract(epoch from now() - make_interval(days=>coalesce((SELECT retention_days FROM public.pr_telegram_automation_controls WHERE workspace_id=pr_telegram_business_inbox.workspace_id),7))) ORDER BY date DESC LIMIT 1", (workspace, row[1], business_id, chat_id))
                incoming = cur.fetchone()
                if not incoming: raise AlphaError("Wait for an incoming Business conversation before replying.", 409)
                message = json.loads(self.vault.decrypt(incoming[0], incoming[1]))
                return row[0], message["chat"], incoming[2]

    def authorize_business(self, workspace, token, connection, body):
        body = fields(body, ("businessConnectionId", "confirmed"), "Business connection")
        provider, session, _, actor = self.grant(workspace, token, connection, "manage_connections")
        uid = session.get("telegram_user_id")
        if not uid: raise AlphaError("First connect your own private bot chat to verify the Telegram account controlling Business.", 409)
        business = provider.call("getBusinessConnection", {"business_connection_id": body.get("businessConnectionId")})
        if not isinstance(business, dict) or business.get("id") != body.get("businessConnectionId") or (business.get("user") or {}).get("id") != uid:
            raise AlphaError("Business connection unavailable.", 404)
        preview = {"businessConnectionId": business["id"], "identity": business["user"], "enabled": business.get("is_enabled"), "rights": business.get("rights", {}), "channelAccess": False}
        if body.get("confirmed") is not True: return {"preview": preview, "requiresConfirmation": True}
        from ..hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections"); self.repository.assert_fresh(token, actor); self.ready(cur)
            cur.execute("INSERT INTO public.pr_telegram_business_connections(workspace_id,bot_id,business_connection_id,user_id,identity,enabled,rafii_consented) VALUES(%s,%s,%s,%s,%s::jsonb,%s,true) ON CONFLICT(workspace_id,bot_id,business_connection_id) DO UPDATE SET identity=excluded.identity,enabled=excluded.enabled,rafii_consented=true,updated_at=now()", (workspace, provider.me()["id"], business["id"], uid, json.dumps(business), business.get("is_enabled") is True))
            audit(cur, workspace, actor, "telegram.business.authorized", business["id"], {"botId": provider.me()["id"], "userId": uid})
        return {**preview, "consented": True, "nextAction": "Wait for incoming Business messages, then select conversations."}

    def business_connections(self,workspace,token):
        from ..hosted import _membership
        with self.repository.transaction(token,workspace) as (cur,row,_):
            require(_membership(row),'manage_connections');self.ready(cur)
            cur.execute("SELECT b.business_connection_id,b.identity,b.enabled,b.rafii_consented,d.connection_id FROM public.pr_telegram_business_connections b JOIN public.pr_telegram_destinations d ON(d.workspace_id=b.workspace_id AND d.bot_id=b.bot_id AND d.snapshot->>'telegramUserId'=b.user_id::text) JOIN public.pr_encrypted_credentials c ON(c.workspace_id=d.workspace_id AND c.connection_id=d.connection_id) WHERE b.workspace_id=%s AND d.revoked_at IS NULL AND c.revoked_at IS NULL ORDER BY b.updated_at DESC LIMIT 100",(workspace,))
            return {'connections':[{'businessConnectionId':r[0],'identity':r[1].get('user',{}),'enabled':r[2],'rafiiConsented':r[3],'ownerConnectionId':r[4]} for r in cur.fetchall()],'coverage':'business_connection_updates_for_verified_owner'}

    def business_inbox(self, workspace, token):
        with self.repository.transaction(token, workspace) as (cur, _, _):
            self.ready(cur)
            cur.execute("SELECT b.business_connection_id,b.identity,b.enabled,i.message_ciphertext,i.key_id,i.deleted FROM public.pr_telegram_business_connections b LEFT JOIN public.pr_telegram_business_inbox i USING(workspace_id,bot_id,business_connection_id) WHERE b.workspace_id=%s AND b.rafii_consented=true AND (i.date IS NULL OR i.date >= extract(epoch from now() - make_interval(days=>coalesce((SELECT retention_days FROM pr_telegram_automation_controls WHERE workspace_id=b.workspace_id),7)))) ORDER BY i.date DESC NULLS LAST LIMIT 100", (workspace,))
            return {"conversations": [{"businessConnectionId": r[0], "identity": r[1], "enabled": r[2], "message": json.loads(self.vault.decrypt(r[3], r[4])) if r[3] else None, "deleted": r[5]} for r in cur.fetchall()], "coverage": "incoming_after_consent"}

    def select_business_chat(self, workspace, token, connection, body):
        body = fields(body, ("businessConnectionId", "chatId", "confirmed"), "Business conversation selection")
        provider, session, _, actor = self.grant(workspace, token, connection, "manage_connections")
        business, chat, incoming = self.business_context(workspace, body.get("businessConnectionId"), integer(body.get("chatId"), 1, 2 ** 52, "Business chat ID"))
        if (business.get("user") or {}).get("id") != session.get("telegram_user_id"): raise AlphaError("Business conversation unavailable.", 404)
        if body.get("confirmed") is not True: return {"preview": {"chat": chat, "businessConnectionId": business["id"]}, "requiresConfirmation": True}
        cid = uuid.uuid4().hex
        target = {"v": 1, "chat": chat["id"], "workspace": workspace, "business_connection_id": business["id"], "telegram_user_id": session["telegram_user_id"]}
        if session.get("botRef"): target["botRef"] = session["botRef"]
        encrypted, key = self.vault.encrypt(json.dumps(target))
        caps = compute(chat, {"status": "member"}, mode="business", **provider_capabilities(provider, chat["id"], "business", business["id"], workspace_id=workspace, actor_id=actor), business=business, incoming_at=incoming, now=self.clock())
        rights = [k for k, v in business.get("rights", {}).items() if v is True]
        channel = {"id": cid, "platform": "Telegram", "account": chat.get("first_name") or str(chat["id"]), "accountType": "business_conversation", "scopes": rights, "verifiedAt": self.clock(), "expiresAt": self.clock() + 5 * 365 * 86400, "capabilityVersion": 2, "providerAccountId": str(chat["id"])}
        snap = self.repository.get(workspace, token)
        from ..hosted import _membership, audit
        def after(cur, state, actor):
            cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'telegram',%s,%s,%s,%s)", (workspace, cid, str(chat["id"]), encrypted, key, rights))
            initial = {"chat": chat, "businessConnectionId": business["id"], "telegramUserId": session["telegram_user_id"]}
            cur.execute("INSERT INTO public.pr_telegram_destinations(workspace_id,connection_id,bot_id,chat_id,mode,snapshot,verified_at) VALUES(%s,%s,%s,%s,'business',%s::jsonb,now())", (workspace, cid, provider.me()["id"], chat["id"], json.dumps(initial)))
            audit(cur, workspace, actor, "telegram.business.conversation.selected", cid, {"businessConnectionId": business["id"], "chatId": chat["id"]})
        saved = self.repository.command(workspace, token, snap["revision"], lambda s, p: self.oauth.commands.upsert_verified_channel(s, p, channel, capability_verified=caps["business_messaging"]["enabled"]), requirement="manage_connections", after=after)
        self.inspect(workspace, token, cid)
        return {"connectionId": cid, "revision": self.repository.get(workspace, token)["revision"]}

    def ready(self, cur):
        cur.execute("SELECT to_regclass('public.pr_telegram_destinations') IS NOT NULL")
        if not cur.fetchone()[0]:
            raise AlphaError("Telegram capability migration is not applied.", 503, code="telegram_schema_required")

    def grant(self, workspace, token, connection, requirement="read"):
        from ..hosted import _membership
        with self.repository.transaction(token, workspace) as (cur, row, principal):
            require(_membership(row), requirement)
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            channel = next((c for c in state.get("phase2", {}).get("channels", []) if c.get("id") == connection and c.get("platform") == "Telegram" and not c.get("revoked")), None)
            if channel is None: raise AlphaError("Connection unavailable.", 404)
            cur.execute("SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='telegram' AND revoked_at IS NULL", (workspace, connection))
            found = cur.fetchone()
            if not found: raise AlphaError("Connection unavailable.", 404)
            credential = self.vault.decrypt(found[0], found[1])
        provider = self.oauth._provider("telegram")
        session = provider.session(credential)
        if session.get("workspace") and session["workspace"] != workspace: raise AlphaError("Connection unavailable.", 404)
        if session.get('parentConnectionId'):
            with self.repository.transaction(token,workspace) as (cur,_,_):
                cur.execute('SELECT d.connection_id FROM public.pr_telegram_destinations d JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) WHERE d.workspace_id=%s AND d.connection_id=%s AND d.revoked_at IS NULL AND c.revoked_at IS NULL',(workspace,session['parentConnectionId']))
                if not cur.fetchone():raise AlphaError('The parent channel connection was revoked. Reauthorize this Channel DM destination.',409)
        provider = provider.for_session(session) if hasattr(provider, "for_session") else provider
        return provider, session, credential, principal

    def inspect(self, workspace, token, connection, *, save=True):
        provider, session, _, principal = self.grant(workspace, token, connection, "manage_connections" if save else "read")
        mode = "business" if session.get("business_connection_id") else "bot"
        business, incoming = None, None
        if mode == "business":
            business = provider.call("getBusinessConnection", {"business_connection_id": session["business_connection_id"]})
            with self.repository.transaction(token, workspace) as (cur, _, _):
                self.ready(cur)
                cur.execute("SELECT snapshot FROM public.pr_telegram_destinations WHERE workspace_id=%s AND connection_id=%s", (workspace, connection))
                found = cur.fetchone()
                if not found: raise AlphaError("Business conversation unavailable.", 404)
                stored = found[0]
                chat, member = stored["chat"], {"status": "member"}
            _, chat, incoming = self.business_context(workspace, session["business_connection_id"], session["chat"])
        else:
            chat, member = snapshot(provider, session)
        caps = compute(chat, member, mode=mode, **provider_capabilities(provider, session["chat"], mode, session.get("business_connection_id"), workspace_id=workspace, actor_id=principal), business=business, incoming_at=incoming, now=self.clock())
        rights = {k: v for k, v in member.items() if k.startswith("can_") and type(v) is bool}
        value = {"connectionId": connection, "connectionType": mode, "chatId": str(chat["id"]), "title": chat.get("title") or chat.get("first_name") or str(chat["id"]),
                 "username": chat.get("username"), "destinationType": "business_conversation" if mode == "business" else destination_type(chat),
                 "photo": chat.get("photo"), "membership": member.get("status"), "administrator": member.get("status") in ("administrator", "creator"),
                 "administratorRights": rights, "chatPermissions": chat.get("permissions", {}), "linkedDiscussionChatId": str(chat["linked_chat_id"]) if chat.get("linked_chat_id") else None,
                 "businessConnectionId": session.get("business_connection_id"), "businessState": {"isEnabled": business.get("is_enabled"), "rights": business.get("rights", {})} if isinstance(business, dict) else None,
                 "messageThreadId": session.get("thread"), "directMessagesTopicId": session.get("dm_topic"), "capabilities": caps,
                 "parentConnectionId":session.get('parentConnectionId'),
                 "lastVerifiedAt": self.clock(), "schedulingMode": "rafii", "advancedEnabled": False,
                 "availableCapabilities": sum(v["enabled"] for v in caps.values()), "totalCapabilities": len(caps),
                 "readiness": "candidate" if caps["publish"].get("candidateExecution") and caps["publish"]["enabled"] else "qualified" if caps["publish"]["enabled"] else "permission_required" if caps["publish"]["state"] == "permission_required" else "acceptance_required",
                 "chat": chat, "telegramUserId": session.get("telegram_user_id")}
        if save:
            from ..hosted import _membership, audit
            with self.repository.transaction(token, workspace) as (cur, row, actor):
                require(_membership(row), "manage_connections"); self.ready(cur)
                cur.execute("INSERT INTO public.pr_telegram_destinations(workspace_id,connection_id,bot_id,chat_id,mode,snapshot,verified_at) VALUES(%s,%s,%s,%s,%s,%s::jsonb,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET bot_id=excluded.bot_id,chat_id=excluded.chat_id,mode=excluded.mode,snapshot=excluded.snapshot,verified_at=excluded.verified_at,revoked_at=NULL", (workspace, connection, provider.me()["id"], chat["id"], mode, json.dumps(value), value["lastVerifiedAt"]))
                # A permission refresh may reduce authority. Upgrades remain an explicit reconnect.
                if not caps["publish"]["enabled"]:
                    state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                    c = next(c for c in state["phase2"]["channels"] if c["id"] == connection)
                    c["capabilityVerified"] = False
                    cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace))
                    cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND capability IN ('publish','schedule')", ("Telegram requires destination-specific permission and acceptance evidence.", workspace, connection))
                audit(cur, workspace, actor, "telegram.destination.verified", connection, {"type": value["destinationType"], "ready": value["readiness"], "botId": provider.me()["id"]})
        value.pop("chat", None); value.pop("telegramUserId", None)
        return value

    def list(self, workspace, token):
        with self.repository.transaction(token, workspace) as (cur, _, _):
            self.ready(cur)
            cur.execute("SELECT snapshot FROM public.pr_telegram_destinations d JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) WHERE d.workspace_id=%s AND c.revoked_at IS NULL AND d.revoked_at IS NULL ORDER BY d.verified_at DESC", (workspace,))
            destinations = []
            for (raw,) in cur.fetchall():
                value = copy.deepcopy(raw)
                value.pop("chat", None); value.pop("telegramUserId", None)
                destinations.append(value)
            return {"destinations": destinations, "connectionModes": {"sharedBot": True, "ownBot": True, "business": True, "managedBot": "requires_botfather_flag_and_oidc_identity", "privateUserSessions": "not_supported"}, "productionReady": False}

    def inbox(self, workspace, token, connection):
        self.grant(workspace, token, connection)
        with self.repository.transaction(token, workspace) as (cur, _, _):
            self.ready(cur)
            cur.execute("SELECT message_ciphertext,key_id,deleted,rafii_job_id FROM public.pr_telegram_messages WHERE workspace_id=%s AND connection_id=%s AND date >= extract(epoch from now() - make_interval(days=>coalesce((SELECT retention_days FROM public.pr_telegram_automation_controls WHERE workspace_id=pr_telegram_messages.workspace_id),7))) ORDER BY date DESC,message_id DESC LIMIT 100", (workspace, connection))
            messages = [{"message": json.loads(self.vault.decrypt(row[0], row[1])), "deleted": row[2], "rafiiJobId": row[3]} for row in cur.fetchall()]
            cur.execute("SELECT thread_id,kind,title,closed,observed_at FROM public.pr_telegram_topics WHERE workspace_id=%s AND connection_id=%s ORDER BY observed_at DESC LIMIT 100", (workspace, connection))
            topics = [{"id": str(r[0]), "kind": r[1], "title": r[2], "closed": r[3], "observedAt": r[4]} for r in cur.fetchall()]
        return {"messages": messages, "topics": topics, "coverage": "bot_observed_updates", "historyBackfill": "unavailable", "ordinaryDeletionDetection": "unavailable", "unreadState": "unavailable"}

    def analytics(self, workspace, token, connection):
        self.grant(workspace, token, connection)
        with self.repository.transaction(token, workspace) as (cur, _, _):
            self.ready(cur)
            cur.execute("SELECT message_id,metric,value,observed_at,source FROM public.pr_telegram_engagement WHERE workspace_id=%s AND connection_id=%s ORDER BY observed_at DESC LIMIT 200", (workspace, connection))
            metrics = [{"messageId": str(r[0]), "metric": r[1], "value": r[2], "observedAt": r[3], "source": r[4]} for r in cur.fetchall()]
            cur.execute("SELECT count(*) FILTER (WHERE rafii_job_id IS NOT NULL),count(*) FILTER (WHERE reply_to_message_id IS NOT NULL) FROM public.pr_telegram_messages WHERE workspace_id=%s AND connection_id=%s AND deleted=false", (workspace, connection))
            published, replies = cur.fetchone()
        return {"metrics": metrics, "deliveryReceipts": {"value": published, "source": "rafii_derived"}, "observedReplies": {"value": replies, "source": "bot_observed", "coverage": "incomplete_history"}, "nativeViews": {"value": None, "source": "unavailable", "reason": "not_available_through_bot_api"}, "nativeStatistics": {"value": None, "source": "unavailable"}}

    def prepare(self, workspace, token, connection, request):
        request = fields(request, ("action", "messageId", "text", "parseMode", "entities", "buttons", "reactions", "comment", "sendDate", "media", "destinationConnectionId"), "message operation")
        action = request.get("action")
        method, cap, requirement = {
            "edit_text": ("editMessageText", "edit_own", "approve"), "edit_caption": ("editMessageCaption", "edit_own", "approve"),
            "edit_buttons": ("editMessageReplyMarkup", "edit_own", "approve"), "edit_media": ("editMessageMedia", "edit_own", "approve"),
            "delete": ("deleteMessage", "delete_own", "approve"), "pin": ("pinChatMessage", "pin", "approve"), "unpin": ("unpinChatMessage", "pin", "approve"),
            "stop_poll": ("stopPoll", "poll", "approve"), "react": ("setMessageReaction", "reaction_set", "reply"),
            "reply": ("sendMessage", "reply", "reply"), "forward": ("forwardMessage", "forward", "approve"), "copy": ("copyMessage", "copy", "approve"),
            "approve_suggestion": ("approveSuggestedPost", "approve_suggested_post", "approve"), "decline_suggestion": ("declineSuggestedPost", "decline_suggested_post", "moderate"),
        }.get(action, (None, None, None))
        if method is None: fail("Unsupported message operation.")
        provider, session, _, actor = self.grant(workspace, token, connection, requirement)
        mid = integer(request.get("messageId"), 1, 2 ** 52, "message ID")
        with self.repository.transaction(token, workspace) as (cur, _, _):
            self.ready(cur)
            cur.execute("SELECT message_ciphertext,key_id,rafii_job_id,date,deleted FROM public.pr_telegram_messages WHERE workspace_id=%s AND connection_id=%s AND chat_id=%s AND message_id=%s", (workspace, connection, session["chat"], mid))
            row = cur.fetchone()
            if not row or row[4]: raise AlphaError("Message unavailable.", 404)
            message = json.loads(self.vault.decrypt(row[0], row[1]))
            if action in ("edit_text", "edit_caption", "edit_buttons", "edit_media", "delete", "pin", "unpin", "stop_poll") and not row[2]: fail("This action is limited to recorded Rafii-created posts.")
            if action == "delete" and self.clock() - row[3] >= 48 * 3600: fail("Telegram's ordinary deletion window expired.")
        live = self.inspect(workspace, token, connection, save=False)
        if not live["capabilities"][cap]["enabled"]: raise AlphaError("This Telegram capability needs permission and real acceptance evidence.", 409)
        body = {"chat_id": session["chat"], "message_id": mid}
        target_connection = connection
        if action in ("forward", "copy"):
            if session.get("business_connection_id") or message.get("has_protected_content") or any(k in message for k in ("paid_media", "invoice", "successful_payment")): fail("This Business/protected/monetized message cannot be forwarded or copied.")
            target_connection = request.get("destinationConnectionId")
            target_provider, target, _, _ = self.grant(workspace, token, target_connection, "approve")
            if target_provider.me()['id'] != provider.me()['id']: fail("Forward/copy needs the same authorized bot at both destinations.")
            target_live = self.inspect(workspace, token, target_connection, save=False)
            if target.get("business_connection_id") or not target_live["capabilities"][cap]["enabled"]: fail("The selected destination cannot receive this operation.")
            if target_live["destinationType"] == "forum_supergroup" and not target.get("thread"): fail("Connect the receiving forum topic explicitly.")
            body = {"chat_id": target["chat"], "from_chat_id": session["chat"], "message_id": mid}
            if target.get("thread"): body["message_thread_id"] = target["thread"]
            if target.get("dm_topic"): body["direct_messages_topic_id"] = target["dm_topic"]
        if action == "reply":
            text, es = formatted(request.get("text"), request.get("parseMode"), request.get("entities"))
            if not 1 <= len(text) <= 4096: fail("A Telegram reply allows 1–4096 characters.")
            body = {"chat_id": session["chat"], "text": text, "entities": es, "reply_parameters": {"message_id": mid, "allow_sending_without_reply": False}}
            if message.get("message_thread_id"): body["message_thread_id"] = message["message_thread_id"]
            dm_topic = (message.get("direct_messages_topic") or {}).get("topic_id")
            if dm_topic: body["direct_messages_topic_id"] = dm_topic
        if session.get("business_connection_id"):
            if action == "delete":
                method = "deleteBusinessMessages"; body = {"business_connection_id": session["business_connection_id"], "message_ids": [mid]}
            elif action.startswith("edit_") or action in ("reply", "stop_poll"): body["business_connection_id"] = session["business_connection_id"]
            else: fail("This action is unavailable for Business conversations.")
        if action in ("edit_text", "edit_caption"):
            text, es = formatted(request.get("text"), request.get("parseMode"), request.get("entities"))
            if len(text) > (4096 if action == "edit_text" else 1024): fail("Edited Telegram content is too long.")
            body["text" if action == "edit_text" else "caption"] = text
            body["entities" if action == "edit_text" else "caption_entities"] = es
        if action == "edit_buttons": body["reply_markup"] = keyboard(request.get("buttons"), destination=live["destinationType"], business=bool(session.get("business_connection_id"))) or {"inline_keyboard": []}
        if action == "edit_media":
            media = fields(request.get("media"), ("type", "media", "caption", "caption_entities", "has_spoiler"), "edited media")
            if media.get("type") not in ("photo", "video", "audio", "document"): fail("Unsupported edited-media type.")
            if 'caption_entities' in media and 'caption' not in media:fail('Provide the complete caption when editing its entities.')
            if not provider.file_check or not provider.file_check(workspace, {"fileId": media.get("media"), "kind": media["type"]}, session): fail("Choose a file recorded for this workspace and bot.")
            if message.get("media_group_id") and (("audio" in message and media["type"] != "audio") or ("document" in message and media["type"] != "document") or ("photo" in message or "video" in message) and media["type"] not in ("photo", "video")): fail("The edited media must preserve this album's media family.")
            if "caption" in media: entities = formatted(media["caption"], None, media.get("caption_entities")); media["caption"], media["caption_entities"] = entities
            body["media"] = media
        if action == "react":
            reactions = request.get("reactions")
            if not isinstance(reactions, list) or len(reactions) > 1: fail("Bots may choose at most one supported reaction.")
            for reaction in reactions:
                fields(reaction, ("type", "emoji"), "reaction")
                if reaction.get("type") != "emoji" or not isinstance(reaction.get("emoji"), str) or not 1 <= len(reaction["emoji"]) <= 16: fail("Paid/custom reactions are disabled until separately qualified.")
            body["reaction"] = reactions
        if action in ("approve_suggestion", "decline_suggestion"):
            info = message.get("suggested_post_info")
            if not isinstance(info, dict): fail("This message is not a recorded suggested post.")
            if info.get("price") is not None: fail("Paid suggested-post transactions are disabled.")
            if action == "approve_suggestion" and request.get("sendDate"):
                body["send_date"] = integer(request["sendDate"], int(self.clock()), int(self.clock()) + 2678400, "suggestion send date")
            if action == "decline_suggestion" and "comment" in request:
                if not isinstance(request["comment"], str) or len(request["comment"]) > 128: fail("A suggestion decline comment allows 128 characters.")
                body["comment"] = request["comment"]
        media_entities=(body.get('media') or {}).get('caption_entities',[])
        all_entities=body.get('entities',[])+body.get('caption_entities',[])+media_entities
        if any(e.get('type') == 'custom_emoji' for e in all_entities): fail("Custom emoji eligibility is not enabled.")
        additional=set()
        if all_entities:additional.add('text_formatting')
        if action=='edit_buttons':additional.add('buttons')
        if action=='edit_media':
            additional.add(body['media']['type'])
            if len(body['media'].get('caption',''))>1024:fail('Edited media captions allow 1024 characters after entity parsing.')
            if 'has_spoiler' in body['media'] and (type(body['media']['has_spoiler']) is not bool or body['media']['type'] not in ('photo','video')):fail('Spoilers apply only to edited photo/video media.')
        if action=='reply':
            if body.get('message_thread_id'):additional.add('topics')
            if body.get('direct_messages_topic_id'):additional.add('channel_dm')
        if any(not live['capabilities'][name]['enabled'] for name in additional):raise AlphaError('An additional Telegram payload capability needs permission and real acceptance evidence.',409)
        operation = {"action": action, "method": method, "capability": cap, "additionalCapabilities":sorted(additional),"requirement": requirement, "payload": body, "targetConnectionId": target_connection}
        op_id, signature = uuid.uuid4().hex, digest(operation)
        ciphertext, key = self.vault.encrypt(json.dumps(operation))
        from ..hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), requirement); self.ready(cur)
            cur.execute("INSERT INTO public.pr_telegram_operations(workspace_id,id,connection_id,actor_id,payload_digest,state,api_method,payload_ciphertext,key_id) VALUES(%s,%s,%s,%s,%s,'prepared',%s,%s,%s)", (workspace, op_id, connection, actor, signature, method, ciphertext, key))
            audit(cur, workspace, actor, "telegram.operation.prepared", op_id, {"action": action, "connectionId": connection, "messageId": mid, "digest": signature})
        return {"operationId": op_id, "digest": signature, "preview": operation, "expiresAt": self.clock() + 600}

    def execute(self, workspace, token, connection, request):
        request = fields(request, ("operationId", "digest", "confirmed"), "operation approval")
        if request.get("confirmed") is not True: fail("Confirm the exact Telegram operation preview.")
        provider, session, _, actor = self.grant(workspace, token, connection)
        from ..hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, principal):
            self.ready(cur)
            cur.execute("SELECT payload_digest,state,result,payload_ciphertext,key_id,actor_id::text,extract(epoch from created_at)::float8 FROM public.pr_telegram_operations WHERE workspace_id=%s AND id=%s AND connection_id=%s FOR UPDATE", (workspace, request.get("operationId"), connection))
            op = cur.fetchone()
            if not op or op[0] != request.get("digest") or op[5] != principal: raise AlphaError("Operation approval unavailable.", 404)
            if op[1] != "prepared": return op[2] or {"state": "uncertain", "reason": "Operation already started; do not resubmit."}
            if self.clock() - op[6] > 600: raise AlphaError("Operation preview expired. Review again.", 409)
            approved = json.loads(self.vault.decrypt(op[3], op[4])); require(_membership(row), approved["requirement"])
        live = self.inspect(workspace, token, connection, save=False)
        if any(not live["capabilities"][capability]["enabled"] for capability in [approved['capability']]+approved.get('additionalCapabilities',[])): raise AlphaError("Telegram permission changed. Review again.", 409)
        target_connection = approved.get("targetConnectionId", connection)
        if target_connection != connection:
            target_live = self.inspect(workspace, token, target_connection, save=False)
            if not target_live["capabilities"][approved["capability"]]["enabled"]: raise AlphaError("Receiving destination permission changed.", 409)
        with self.repository.transaction(token, workspace) as (cur, row, principal):
            require(_membership(row), approved["requirement"])
            cur.execute("UPDATE public.pr_telegram_operations SET state='started',updated_at=now() WHERE workspace_id=%s AND id=%s AND state='prepared' RETURNING id", (workspace, request["operationId"]))
            if not cur.fetchone(): return {"state": "uncertain", "reason": "Another worker started this operation; do not resubmit."}
            audit(cur, workspace, principal, "telegram.operation.started", request["operationId"], {"action": approved["action"]})
        try:
            response = provider.request(approved["method"], approved["payload"])
            data = response.get("body") or {}
            ok = response.get("status") == 200 and data.get("ok") is True
            result = {"state": "confirmed" if ok else "failed" if data.get("error_code") in (400, 401, 403, 429) else "uncertain", "apiMethod": approved["method"], "messageId": approved["payload"].get("message_id")}
            actual = data.get("result")
            if ok and actual is not True and not isinstance(actual, dict): result['state'] = 'uncertain'
            if ok and isinstance(actual, dict) and actual.get("message_id"):
                creating = approved["action"] in ("reply", "forward", "copy")
                if not creating and (actual.get("message_id") != approved["payload"].get("message_id") or (actual.get("chat") or {}).get("id") != session["chat"]): result["state"] = "uncertain"
                elif creating and (type(actual['message_id']) is not int or actual['message_id'] <= 0 or approved['action'] != 'copy' and (actual.get('chat') or {}).get('id') != approved['payload']['chat_id']): result['state'] = 'uncertain'
                elif creating: result.update(messageId=actual['message_id'], chatId=str(approved['payload']['chat_id']), contentVerification='message_id_only' if approved['action']=='copy' else 'telegram_message')
                else: result["editDate"] = actual.get("edit_date")
            elif ok and approved['action'] in ('reply','forward','copy','edit_text','edit_caption','edit_media','edit_buttons'):
                result['state'] = 'uncertain'
            if ok and approved['action'] == 'stop_poll' and (not isinstance(actual,dict) or actual.get('id') is None or actual.get('is_closed') is not True): result['state']='uncertain'
            if ok and approved['action'] == 'reply' and isinstance(actual,dict) and (actual.get('text') != approved['payload']['text'] or (actual.get('reply_to_message') or {}).get('message_id') != approved['payload']['reply_parameters']['message_id']):
                result['state']='uncertain'
            if ok and approved['action'] in ('edit_text','edit_caption') and isinstance(actual,dict):
                field = 'text' if approved['action']=='edit_text' else 'caption'
                if actual.get(field,'') != approved['payload'][field]: result['state']='uncertain'
        except Exception:
            result = {"state": "uncertain", "reason": "Telegram outcome is unknown; do not resubmit."}
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("UPDATE public.pr_telegram_operations SET state=%s,result=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id=%s AND state='started'", (result["state"], json.dumps(result), workspace, request["operationId"]))
                if result["state"] == "confirmed" and approved["action"] == "delete":
                    cur.execute("UPDATE public.pr_telegram_messages SET deleted=true WHERE workspace_id=%s AND connection_id=%s AND chat_id=%s AND message_id=%s", (workspace, connection, session["chat"], request_message_id(approved)))
                if result['state'] == 'confirmed' and isinstance(actual, dict) and type(actual.get('date')) is int and actual.get('chat'):
                    from .updates import save_message
                    save_message(cur, self.vault, workspace, target_connection, provider.me()['id'], actual, job={'id': 'operation/' + request['operationId']} if approved['action'] in ('reply','forward') else None, api_path='Bot API/' + approved['method'])
                audit(cur, workspace, actor, "telegram.operation." + result["state"], request["operationId"], {"action": approved["action"]})
        return result


def request_message_id(approved):
    return approved["payload"].get("message_id") or approved["payload"].get("message_ids", [None])[0]
