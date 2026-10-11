"""Explicit Channel DM consent, observed-topic discovery and scoped destination selection."""
import json
import uuid
from postriff_alpha.domain import AlphaError
from ..permissions import require
from .content import fields, integer, fail
from .publishing import snapshot
from .capabilities import compute, provider_capabilities


class ChannelDirectMessages:
    def __init__(self,telegram):
        self.telegram=telegram;self.repository=telegram.repository;self.vault=telegram.vault

    def parent(self,workspace,token,connection):
        provider,session,_,actor=self.telegram.grant(workspace,token,connection,'manage_connections')
        if session.get('business_connection_id'):fail('Business connections do not grant Channel DM access.')
        chat,member=snapshot(provider,session)
        if chat.get('type')!='channel' or member.get('can_manage_direct_messages') is not True:
            raise AlphaError('Select a connected channel with current can_manage_direct_messages permission.',409)
        return provider,session,chat,member,actor

    def authorize(self,workspace,token,connection,body):
        body=fields(body,('confirmed','enabled'),'Channel DM consent')
        if 'enabled' in body and type(body['enabled']) is not bool:fail('Choose whether Channel DM discovery is enabled.')
        provider,session,chat,member,actor=self.parent(workspace,token,connection)
        enabled=body.get('enabled',True)
        preview={'parentChatId':str(chat['id']),'title':chat.get('title'),'botId':provider.me()['id'],'requiredRight':'can_manage_direct_messages','effect':'Receive accessible Channel DM conversations after consent' if enabled else 'Stop discovery of new Channel DM conversations'}
        if body.get('confirmed') is not True:return {'preview':preview,'requiresConfirmation':True}
        from ..hosted import _membership,audit
        with self.repository.transaction(token,workspace) as (cur,row,actor):
            require(_membership(row),'manage_connections');self.repository.assert_fresh(token,actor);self.telegram.ready(cur)
            cur.execute('INSERT INTO public.pr_telegram_dm_access(workspace_id,parent_connection_id,bot_id,parent_chat_id,enabled) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,parent_connection_id) DO UPDATE SET enabled=excluded.enabled,updated_at=now()', (workspace,connection,provider.me()['id'],chat['id'],enabled))
            audit(cur,workspace,actor,'telegram.channel_dm.consent',connection,{'enabled':enabled,'parentChatId':chat['id']})
        return {'enabled':enabled,'parentConnectionId':connection,'coverage':'updates_after_explicit_consent','unreadState':'unavailable'}

    def list(self,workspace,token):
        with self.repository.transaction(token,workspace) as (cur,_,_):
            self.telegram.ready(cur)
            cur.execute("SELECT DISTINCT ON(i.parent_connection_id,i.chat_id,i.topic_id) i.parent_connection_id,i.chat_id,i.topic_id,i.chat_identity,i.date FROM public.pr_telegram_dm_inbox i JOIN public.pr_telegram_dm_access a USING(workspace_id,parent_connection_id) JOIN public.pr_encrypted_credentials c ON(c.workspace_id=i.workspace_id AND c.connection_id=i.parent_connection_id) WHERE i.workspace_id=%s AND a.enabled=true AND c.revoked_at IS NULL AND i.date >= extract(epoch from now() - make_interval(days=>coalesce((SELECT retention_days FROM pr_telegram_automation_controls WHERE workspace_id=i.workspace_id),7))) ORDER BY i.parent_connection_id,i.chat_id,i.topic_id,i.date DESC LIMIT 100",(workspace,))
            return {'conversations':[{'parentConnectionId':r[0],'chatId':str(r[1]),'topicId':r[2],'title':r[3].get('title'),'lastIncomingAt':r[4]} for r in cur.fetchall()],'coverage':'updates_after_explicit_consent','unreadState':'unavailable'}

    def select(self,workspace,token,connection,body):
        body=fields(body,('chatId','topicId','confirmed'),'Channel DM destination')
        chat_id=integer(body.get('chatId'),-2**52,2**52,'Channel DM chat ID');topic=integer(body.get('topicId'),1,2**52,'Channel DM topic')
        provider,session,parent,member,actor=self.parent(workspace,token,connection)
        with self.repository.transaction(token,workspace) as (cur,_,_):
            self.telegram.ready(cur)
            cur.execute('SELECT i.chat_identity FROM public.pr_telegram_dm_inbox i JOIN public.pr_telegram_dm_access a USING(workspace_id,parent_connection_id) WHERE i.workspace_id=%s AND i.parent_connection_id=%s AND i.chat_id=%s AND i.topic_id=%s AND a.enabled=true LIMIT 1',(workspace,connection,chat_id,topic))
            observed=cur.fetchone()
            if not observed:raise AlphaError('Select a Channel DM topic observed after explicit consent.',404)
        chat=provider.call('getChat',{'chat_id':chat_id})
        if not isinstance(chat,dict) or chat.get('id')!=chat_id or chat.get('is_direct_messages') is not True or (chat.get('parent_chat') or {}).get('id')!=parent['id']:raise AlphaError('Channel DM destination does not belong to the authorized parent channel.',409)
        preview={'chatId':str(chat_id),'topicId':topic,'parentChatId':str(parent['id']),'title':chat.get('title'),'effect':'Authorize this Channel DM topic for Rafii replies'}
        if body.get('confirmed') is not True:return {'preview':preview,'requiresConfirmation':True}
        cid=uuid.uuid4().hex
        target={'v':1,'workspace':workspace,'chat':chat_id,'dm_topic':topic,'parentConnectionId':connection}
        if session.get('botRef'):target['botRef']=session['botRef']
        encrypted,key=self.vault.encrypt(json.dumps(target));rights=[k for k,v in member.items() if k.startswith('can_') and v is True]
        caps=compute(chat,member,**provider_capabilities(provider,chat_id,workspace_id=workspace,actor_id=actor))
        channel={'id':cid,'platform':'Telegram','account':f"{parent.get('title',parent['id'])} · DM topic {topic}",'accountType':'channel_dm','scopes':rights,'verifiedAt':self.telegram.clock(),'expiresAt':self.telegram.clock()+5*365*86400,'capabilityVersion':2,'providerAccountId':str(chat_id)}
        from ..hosted import audit
        from .updates import save_message
        def after(cur,state,actor):
            cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'telegram',%s,%s,%s,%s)",(workspace,cid,str(chat_id),encrypted,key,rights))
            cur.execute("INSERT INTO public.pr_telegram_destinations(workspace_id,connection_id,bot_id,chat_id,mode,snapshot,verified_at) VALUES(%s,%s,%s,%s,'bot',%s::jsonb,now())",(workspace,cid,provider.me()['id'],chat_id,json.dumps({'chat':chat,'directMessagesTopicId':topic,'parentConnectionId':connection})))
            cur.execute('SELECT message_ciphertext,key_id FROM public.pr_telegram_dm_inbox WHERE workspace_id=%s AND parent_connection_id=%s AND chat_id=%s AND topic_id=%s AND date >= extract(epoch from now() - make_interval(days=>coalesce((SELECT retention_days FROM pr_telegram_automation_controls WHERE workspace_id=pr_telegram_dm_inbox.workspace_id),7))) ORDER BY date DESC LIMIT 100',(workspace,connection,chat_id,topic))
            for row in cur.fetchall():save_message(cur,self.vault,workspace,cid,provider.me()['id'],json.loads(self.vault.decrypt(*row)))
            audit(cur,workspace,actor,'telegram.channel_dm.topic.selected',cid,preview)
        snap=self.repository.get(workspace,token)
        self.repository.command(workspace,token,snap['revision'],lambda s,p:self.telegram.oauth.commands.upsert_verified_channel(s,p,channel,capability_verified=caps['channel_dm']['enabled'] and caps['publish']['enabled']),requirement='manage_connections',after=after)
        self.telegram.inspect(workspace,token,cid)
        return {'connectionId':cid,'revision':self.repository.get(workspace,token)['revision'],'directMessagesTopicId':topic}
