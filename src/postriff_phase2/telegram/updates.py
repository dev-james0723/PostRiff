"""Atomic update deduplication and observations routed only to selected destinations."""
import hashlib
import json
from postriff_alpha.domain import AlphaError

MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post", "business_message", "edited_business_message")


def save_message(cur, vault, workspace, connection, bot_id, message, *, update_id=None, job=None, api_path=None):
    if type(message.get("message_id")) is not int or type((message.get("chat") or {}).get("id")) is not int or type(message.get("date")) is not int:
        raise AlphaError("Invalid Telegram Message observation.", 400)
    chat_id, mid = message["chat"]["id"], message["message_id"]
    ciphertext, key = vault.encrypt(json.dumps(message))
    cur.execute("INSERT INTO public.pr_telegram_messages(workspace_id,connection_id,bot_id,chat_id,message_id,date,edit_date,message_thread_id,direct_messages_topic_id,reply_to_message_id,media_group_id,business_connection_id,poll_id,rafii_job_id,source_variant_id,api_path,url,message_ciphertext,key_id,source_update_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,connection_id,chat_id,message_id) DO UPDATE SET message_ciphertext=excluded.message_ciphertext,key_id=excluded.key_id,edit_date=excluded.edit_date,source_update_id=excluded.source_update_id WHERE coalesce(excluded.edit_date,excluded.date)>=coalesce(pr_telegram_messages.edit_date,pr_telegram_messages.date)",
                (workspace, connection, bot_id, chat_id, mid, message["date"], message.get("edit_date"), message.get("message_thread_id"), (message.get("direct_messages_topic") or {}).get("topic_id"), (message.get("reply_to_message") or {}).get("message_id"), message.get("media_group_id"), message.get("business_connection_id"), (message.get("poll") or {}).get("id"), job.get("id") if job else None, (job.get("manifest") or {}).get("variantId") if job else None, api_path, None, ciphertext, key, update_id))
    origin = message.get("forward_origin") or {}
    if message.get("is_automatic_forward") and origin.get("type") == "channel":
        source = origin.get("chat") or {}
        cur.execute("UPDATE public.pr_telegram_messages SET discussion_chat_id=%s,discussion_message_id=%s WHERE workspace_id=%s AND chat_id=%s AND message_id=%s AND rafii_job_id IS NOT NULL", (chat_id, mid, workspace, source.get("id"), origin.get("message_id")))
    thread = message.get("message_thread_id")
    dm = (message.get("direct_messages_topic") or {}).get("topic_id")
    if thread or dm:
        service = message.get("forum_topic_created") or message.get("forum_topic_edited") or {}
        cur.execute("INSERT INTO public.pr_telegram_topics(workspace_id,connection_id,thread_id,kind,title,closed,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,connection_id,thread_id,kind) DO UPDATE SET title=coalesce(excluded.title,pr_telegram_topics.title),closed=CASE WHEN %s THEN true WHEN %s THEN false ELSE pr_telegram_topics.closed END,observed_at=greatest(pr_telegram_topics.observed_at,excluded.observed_at)", (workspace, connection, thread or dm, "forum" if thread else "channel_dm", service.get("name"), "forum_topic_closed" in message, message.get("edit_date", message["date"]), "forum_topic_closed" in message, "forum_topic_reopened" in message))
    for kind in ("photo", "video", "animation", "audio", "voice", "video_note", "document", "live_photo"):
        value = message.get(kind)
        if isinstance(value, list): value = value[-1] if value else None
        if not isinstance(value, dict) or not isinstance(value.get("file_id"), str): continue
        cur.execute("INSERT INTO public.pr_telegram_files(workspace_id,bot_id,file_id,kind,descriptor) VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(workspace_id,bot_id,file_id) DO NOTHING", (workspace, bot_id, value["file_id"], kind, json.dumps({k: v for k, v in value.items() if k in ("file_unique_id", "file_size", "width", "height", "duration", "mime_type", "file_name", "title", "performer")})))


def ingest(service, provider, update, raw):
    uid = update.get("update_id") if isinstance(update, dict) else None
    if type(uid) is not int or uid < 0: raise AlphaError("Invalid Telegram update ID.", 400)
    kinds = [k for k in update if k != "update_id"]
    if len(kinds) != 1: raise AlphaError("Invalid Telegram update shape.", 400)
    kind, event = kinds[0], update[kinds[0]]
    if not isinstance(event, dict): raise AlphaError("Invalid Telegram update object.", 400)
    if kind == 'deleted_business_messages' and (not isinstance(event.get('message_ids'),list) or any(type(mid) is not int or mid <= 0 for mid in event['message_ids'])):
        raise AlphaError('Invalid Telegram deleted-message identifiers.',400)
    from .canary_worker import ingress_scope, accepts_event
    canary, scope = ingress_scope(provider, service.clock())
    if canary and (not scope or not accepts_event(scope, kind, event)):
        return {'ok': True, 'canaryIgnored': True}
    bot = provider.me()["id"]
    if canary and scope['botId'] != bot:
        return {'ok': True, 'canaryIgnored': True}
    fingerprint = hashlib.sha256(raw).hexdigest()
    with service.repository.connection_factory() as db:
        with db.cursor() as cur:
            service.ready(cur)
            if canary:
                from .canary_worker import owner_active
                if not owner_active(cur, scope):
                    return {'ok': True, 'canaryIgnored': True}
            if canary and kind in ('business_connection', 'managed_bot'):
                # Only metadata for this verified owner may establish a new
                # native connection. No message body is persisted by this check.
                native_user = (event.get('user') or {}).get('id')
                if type(native_user) is not int or not 0 < native_user < 2**52:
                    return {'ok': True, 'canaryIgnored': True}
                cur.execute("SELECT 1 FROM public.pr_telegram_identities WHERE workspace_id=%s AND member_id=%s AND telegram_user_id=%s AND revoked_at IS NULL",
                            (scope['workspaceId'], scope['actorId'], native_user))
                if not cur.fetchone():
                    return {'ok': True, 'canaryIgnored': True}
            cur.execute("INSERT INTO public.pr_telegram_updates(bot_id,update_id,digest,update_type) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING update_id", (bot, uid, fingerprint, kind))
            if not cur.fetchone():
                cur.execute("SELECT digest FROM public.pr_telegram_updates WHERE bot_id=%s AND update_id=%s", (bot, uid))
                if cur.fetchone()[0] != fingerprint: raise AlphaError("Conflicting Telegram update replay.", 409)
                return {"ok": True, "duplicate": True}
            if kind == 'managed_bot':
                from .managed import observe
                observe(cur, bot, uid, event)
            chat_id = (event.get("chat") or {}).get("id")
            if kind == "callback_query": chat_id = ((event.get("message") or {}).get("chat") or {}).get("id")
            if kind in ("poll", "poll_answer"):
                limit = ' AND m.workspace_id=%s AND m.chat_id=ANY(%s::bigint[])' if canary else ''
                params = (bot, event.get("id") if kind == "poll" else event.get("poll_id"))
                if canary: params += (scope['workspaceId'], [d['chatId'] for d in scope['destinations']])
                cur.execute("SELECT DISTINCT m.workspace_id::text,m.connection_id,NULL::jsonb FROM public.pr_telegram_messages m JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) JOIN public.pr_workspaces w ON w.id=m.workspace_id WHERE m.bot_id=%s AND m.poll_id=%s AND c.revoked_at IS NULL AND w.state->'accountDeletion' IS NULL AND w.state->'accountBlock' IS NULL" + limit, params)
            elif kind == "business_connection":
                limit = ' AND d.workspace_id=%s' if canary else ''
                params = (bot, str((event.get("user") or {}).get("id"))) + ((scope['workspaceId'],) if canary else ())
                cur.execute("SELECT d.workspace_id::text,d.connection_id,d.snapshot FROM public.pr_telegram_destinations d JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) JOIN public.pr_workspaces w ON w.id=d.workspace_id WHERE d.bot_id=%s AND d.revoked_at IS NULL AND c.revoked_at IS NULL AND d.snapshot->>'telegramUserId'=%s AND w.state->'accountDeletion' IS NULL AND w.state->'accountBlock' IS NULL" + limit, params)
            else:
                limit = ' AND d.workspace_id=%s' if canary else ''
                params = (bot, chat_id) + ((scope['workspaceId'],) if canary else ())
                cur.execute("SELECT d.workspace_id::text,d.connection_id,d.snapshot FROM public.pr_telegram_destinations d JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) JOIN public.pr_workspaces w ON w.id=d.workspace_id WHERE d.bot_id=%s AND d.chat_id=%s AND d.revoked_at IS NULL AND c.revoked_at IS NULL AND w.state->'accountDeletion' IS NULL AND w.state->'accountBlock' IS NULL AND (d.snapshot->>'parentConnectionId' IS NULL OR EXISTS(SELECT 1 FROM public.pr_telegram_destinations pd JOIN public.pr_encrypted_credentials pc USING(workspace_id,connection_id) WHERE pd.workspace_id=d.workspace_id AND pd.connection_id=d.snapshot->>'parentConnectionId' AND pd.revoked_at IS NULL AND pc.revoked_at IS NULL))" + limit, params)
            destinations = cur.fetchall()
            if kind == 'business_connection' and destinations and event.get('is_enabled') is True:
                # Update delivery may be concurrent/out of order, and update IDs
                # can restart randomly after an idle week. Re-read current state
                # instead of restoring permissions from a delayed enable event.
                # Revocations apply immediately without requiring a network read.
                current = provider.call('getBusinessConnection', {'business_connection_id': event.get('id')})
                if not isinstance(current, dict) or current.get('id') != event.get('id') or (current.get('user') or {}).get('id') != (event.get('user') or {}).get('id'):
                    raise AlphaError('Business connection identity could not be revalidated.', 409)
                event = current
            if kind in ('message','edited_message') and isinstance(event.get('direct_messages_topic'),dict):
                dm_chat=provider.call('getChat',{'chat_id':chat_id})
                parent=(dm_chat.get('parent_chat') or {}) if isinstance(dm_chat,dict) else {}
                if dm_chat.get('is_direct_messages') is True and dm_chat.get('id')==chat_id and type(parent.get('id')) is int:
                    limit = ' AND a.workspace_id=%s' if canary else ''
                    params = (bot,parent['id']) + ((scope['workspaceId'],) if canary else ())
                    cur.execute("SELECT a.workspace_id::text,a.parent_connection_id FROM public.pr_telegram_dm_access a JOIN public.pr_encrypted_credentials c ON(c.workspace_id=a.workspace_id AND c.connection_id=a.parent_connection_id) JOIN public.pr_workspaces w ON w.id=a.workspace_id WHERE a.bot_id=%s AND a.parent_chat_id=%s AND a.enabled=true AND c.revoked_at IS NULL AND w.state->'accountDeletion' IS NULL AND w.state->'accountBlock' IS NULL" + limit,params)
                    consented=cur.fetchall()
                    if consented:
                        rights=provider.call('getChatMember',{'chat_id':parent['id'],'user_id':bot})
                        topic=event['direct_messages_topic'].get('topic_id')
                        if rights.get('can_manage_direct_messages') is True and type(topic) is int and type(event.get('message_id')) is int and type(event.get('date')) is int:
                            for workspace,parent_connection in consented:
                                encrypted,key=service.vault.encrypt(json.dumps(event))
                                cur.execute("INSERT INTO public.pr_telegram_dm_inbox(workspace_id,parent_connection_id,chat_id,topic_id,message_id,date,edit_date,chat_identity,message_ciphertext,key_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(workspace_id,parent_connection_id,chat_id,message_id) DO UPDATE SET message_ciphertext=excluded.message_ciphertext,key_id=excluded.key_id,edit_date=excluded.edit_date WHERE coalesce(excluded.edit_date,excluded.date)>=coalesce(pr_telegram_dm_inbox.edit_date,pr_telegram_dm_inbox.date)",(workspace,parent_connection,chat_id,topic,event['message_id'],event['date'],event.get('edit_date'),json.dumps({'id':chat_id,'title':dm_chat.get('title'),'parentChatId':parent['id']}),encrypted,key))
            if kind in ("business_message", "edited_business_message", "deleted_business_messages"):
                limit = ' AND b.workspace_id=%s' if canary else ''
                params = (bot, event.get("business_connection_id")) + ((scope['workspaceId'],) if canary else ())
                cur.execute("SELECT b.workspace_id::text FROM public.pr_telegram_business_connections b JOIN public.pr_workspaces w ON w.id=b.workspace_id WHERE b.bot_id=%s AND b.business_connection_id=%s AND b.enabled=true AND b.rafii_consented=true AND w.state->'accountDeletion' IS NULL AND w.state->'accountBlock' IS NULL" + limit, params)
                for (workspace,) in cur.fetchall():
                    if kind == "deleted_business_messages":
                        for mid in event.get("message_ids", []):
                            cur.execute("UPDATE public.pr_telegram_business_inbox SET deleted=true WHERE workspace_id=%s AND bot_id=%s AND business_connection_id=%s AND chat_id=%s AND message_id=%s", (workspace, bot, event.get("business_connection_id"), chat_id, mid))
                    elif type(event.get("message_id")) is int and type(event.get("date")) is int and type(chat_id) is int:
                        encrypted, key = service.vault.encrypt(json.dumps(event))
                        cur.execute("INSERT INTO public.pr_telegram_business_inbox(workspace_id,bot_id,business_connection_id,chat_id,message_id,date,edit_date,message_ciphertext,key_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,bot_id,business_connection_id,chat_id,message_id) DO UPDATE SET message_ciphertext=excluded.message_ciphertext,key_id=excluded.key_id,edit_date=excluded.edit_date WHERE coalesce(excluded.edit_date,excluded.date)>=coalesce(pr_telegram_business_inbox.edit_date,pr_telegram_business_inbox.date)", (workspace, bot, event["business_connection_id"], chat_id, event["message_id"], event["date"], event.get('edit_date'), encrypted, key))
            for workspace, connection, destination in destinations:
                if kind in MESSAGE_KEYS:
                    if destination and destination.get('messageThreadId') and destination['messageThreadId']!=event.get('message_thread_id'):continue
                    if destination and destination.get('directMessagesTopicId') and destination['directMessagesTopicId']!=(event.get('direct_messages_topic') or {}).get('topic_id'):continue
                    # Business events cannot enter ordinary channel permissions or another connection.
                    if kind.startswith(("business_", "edited_business_")) and (not destination or destination.get("businessConnectionId") != event.get("business_connection_id")): continue
                    if not kind.startswith(("business_", "edited_business_")) and destination and destination.get('businessConnectionId'): continue
                    save_message(cur, service.vault, workspace, connection, bot, event, update_id=uid)
                elif kind == "deleted_business_messages":
                    if destination.get("businessConnectionId") != event.get("business_connection_id"): continue
                    for mid in event.get("message_ids", []):
                        if type(mid) is int: cur.execute("UPDATE public.pr_telegram_messages SET deleted=true WHERE workspace_id=%s AND connection_id=%s AND chat_id=%s AND message_id=%s AND business_connection_id=%s", (workspace, connection, chat_id, mid, event.get("business_connection_id")))
                elif kind == "business_connection":
                    cur.execute("INSERT INTO public.pr_telegram_business_connections(workspace_id,bot_id,business_connection_id,user_id,identity,enabled) VALUES(%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(workspace_id,bot_id,business_connection_id) DO UPDATE SET identity=excluded.identity,enabled=excluded.enabled,updated_at=now()", (workspace, bot, event["id"], event["user"]["id"], json.dumps(event), event.get("is_enabled") is True))
                    cur.execute("UPDATE public.pr_telegram_destinations SET snapshot=jsonb_set(snapshot,'{businessState}',%s::jsonb),revoked_at=CASE WHEN %s THEN revoked_at ELSE now() END WHERE workspace_id=%s AND bot_id=%s AND snapshot->>'businessConnectionId'=%s", (json.dumps({"isEnabled": event.get("is_enabled"), "rights": event.get("rights", {})}), event.get("is_enabled") is True, workspace, bot, event["id"]))
                elif kind == "my_chat_member":
                    member = event.get("new_chat_member") or {}
                    if member.get('can_manage_direct_messages') is not True:
                        cur.execute('UPDATE public.pr_telegram_dm_access SET enabled=false,updated_at=now() WHERE workspace_id=%s AND bot_id=%s AND parent_chat_id=%s',(workspace,bot,chat_id))
                        cur.execute("UPDATE public.pr_telegram_destinations SET revoked_at=now() WHERE workspace_id=%s AND bot_id=%s AND snapshot->>'parentConnectionId'=%s",(workspace,bot,connection))
                    cur.execute("UPDATE public.pr_telegram_destinations SET snapshot=jsonb_set(snapshot,'{membership}',%s::jsonb),revoked_at=CASE WHEN %s THEN now() ELSE revoked_at END WHERE workspace_id=%s AND connection_id=%s", (json.dumps(member.get("status")), member.get("status") in ("left", "kicked"), workspace, connection))
                    # Fail closed immediately; reauthorization restores the capability.
                    cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Telegram membership changed; verify again.' WHERE workspace_id=%s AND connection_id=%s AND capability<>'identity'", (workspace, connection))
                    cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,channels}',(SELECT jsonb_agg(CASE WHEN c->>'id'=%s THEN jsonb_set(c,'{capabilityVerified}','false'::jsonb) ELSE c END) FROM jsonb_array_elements(state->'phase2'->'channels') c)),revision=revision+1 WHERE id=%s", (connection,workspace))
                elif kind in ("message_reaction", "message_reaction_count", "poll", "poll_answer"):
                    mid = event.get("message_id")
                    if destination and (destination.get('messageThreadId') or destination.get('directMessagesTopicId')) and kind in ('message_reaction','message_reaction_count'):
                        cur.execute('SELECT message_id FROM public.pr_telegram_messages WHERE workspace_id=%s AND connection_id=%s AND chat_id=%s AND message_id=%s',(workspace,connection,chat_id,mid))
                        if not cur.fetchone():continue
                    if kind in ("poll", "poll_answer"):
                        cur.execute("SELECT chat_id,message_id FROM public.pr_telegram_messages WHERE workspace_id=%s AND connection_id=%s AND poll_id=%s LIMIT 1", (workspace, connection, event.get("id") or event.get("poll_id")))
                        row = cur.fetchone()
                        if not row: continue
                        chat_id, mid = row
                    metric = "reactions" if kind == "message_reaction_count" else "poll_results" if kind == "poll" else "reaction_event:" + str(uid) if kind == "message_reaction" else "poll_vote_event:" + str(uid)
                    # No reactor/voter identities in the analytics surface.
                    value = event.get("reactions", []) if kind == "message_reaction_count" else {"old": event.get("old_reaction", []), "new": event.get("new_reaction", [])} if kind == "message_reaction" else {"totalVoterCount": event.get("total_voter_count"), "options": event.get("options", []), "closed": event.get("is_closed")} if kind == "poll" else {"optionIds": event.get("option_ids", [])}
                    date = event.get("date") or int(service.clock())
                    cur.execute("INSERT INTO public.pr_telegram_engagement(workspace_id,connection_id,chat_id,message_id,metric,value,observed_at,source) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,'bot_observed') ON CONFLICT(workspace_id,connection_id,chat_id,message_id,metric) DO UPDATE SET value=excluded.value,observed_at=excluded.observed_at WHERE excluded.observed_at>=pr_telegram_engagement.observed_at", (workspace, connection, chat_id, mid, metric, json.dumps(value), date))
    return {"ok": True}
