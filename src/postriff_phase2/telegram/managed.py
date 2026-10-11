"""Official managed bot creation links and event-bound owner authorization."""
import re
import json
from contextlib import contextmanager
from urllib.parse import urlencode
from postriff_alpha.domain import AlphaError
from ..permissions import require
from .content import fields


class ManagedBots:
    def __init__(self, telegram):
        self.telegram, self.repository = telegram, telegram.repository

    def manager(self):
        provider = self.telegram.oauth._provider('telegram')
        me = provider.me()
        if me.get('can_manage_bots') is not True:
            raise AlphaError('Managed Bots must be enabled for Rafii in BotFather.', 409)
        return provider, me

    @contextmanager
    def owned(self, workspace, token, bot_id):
        """Recheck the member's verified owner while excluding transfer events."""
        from ..hosted import _membership
        if not isinstance(bot_id, str) or not re.fullmatch(r'[1-9][0-9]{0,15}', bot_id):
            raise AlphaError('Select a managed bot.', 400)
        provider, me = self.manager()
        with self.repository.connection_factory() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                       ('rafii-managed:'+str(me['id'])+':'+bot_id,))
            with self.repository.transaction(token, workspace) as (cur, row, actor):
                require(_membership(row), 'manage_connections')
                self.repository.assert_fresh(token, actor)
                cur.execute('''SELECT b.owner_user_id,b.last_update_id,b.username
                    FROM pr_telegram_managed_bots b WHERE b.manager_bot_id=%s AND b.bot_id=%s
                    AND EXISTS(SELECT 1 FROM pr_telegram_identities i WHERE i.workspace_id=%s
                    AND i.member_id=%s AND i.bot_id=b.manager_bot_id::text
                    AND i.telegram_user_id=b.owner_user_id AND i.revoked_at IS NULL)''',
                    (me['id'], int(bot_id), workspace, actor))
                owner = cur.fetchone()
                if not owner:
                    raise AlphaError('Managed bot unavailable for this verified owner.', 404)
                yield provider, me, owner, actor, cur

    @staticmethod
    def normalize_access(raw):
        if not isinstance(raw, dict) or type(raw.get('is_access_restricted')) is not bool:
            raise AlphaError('Telegram returned invalid managed bot access settings.', 502)
        users = raw.get('added_users', []) if raw['is_access_restricted'] else []
        if not isinstance(users, list) or len(users) > 10 or any(
                not isinstance(user, dict) or type(user.get('id')) is not int
                or not 0 < user['id'] < 2**52 for user in users):
            raise AlphaError('Telegram returned invalid managed bot access settings.', 502)
        return {'restricted': raw['is_access_restricted'], 'addedUserIds': sorted({u['id'] for u in users})}

    def access(self, workspace, token, bot_id):
        with self.owned(workspace, token, bot_id) as (provider, _, owner, _, _):
            settings = self.normalize_access(provider.call('getManagedBotAccessSettings', {'user_id': int(bot_id)}))
            return {'botId': bot_id, 'username': owner[2], **settings, 'ownerAlwaysHasAccess': True}

    def prepare_access(self, workspace, token, bot_id, body):
        body = fields(body, ('restricted', 'addedUserIds'), 'managed bot access preview')
        restricted, users = body.get('restricted'), body.get('addedUserIds', [])
        if type(restricted) is not bool or not isinstance(users, list) or len(users) > 10 or any(
                type(user) is not int or not 0 < user < 2**52 for user in users):
            raise AlphaError('Choose bot access and up to ten Telegram user IDs.', 400)
        if not restricted and users:
            raise AlphaError('A public bot cannot specify a restricted access list.', 400)
        after = {'restricted': restricted, 'addedUserIds': sorted(set(users))}
        with self.owned(workspace, token, bot_id) as (provider, me, owner, actor, _):
            before = self.normalize_access(provider.call('getManagedBotAccessSettings', {'user_id': int(bot_id)}))
            payload = {'workspace': workspace, 'actor': actor, 'botId': bot_id, 'managerId': me['id'],
                       'ownerId': owner[0], 'ownerVersion': owner[1], 'before': before, 'after': after,
                       'expiresAt': self.telegram.clock()+300}
            proof, key_id = self.telegram.vault.encrypt(json.dumps(payload))
            return {'preview': {'botId': bot_id, 'username': owner[2], 'before': before,
                                'after': after, 'ownerAlwaysHasAccess': True}, 'proof': proof, 'keyId': key_id}

    def execute_access(self, workspace, token, bot_id, body):
        from ..hosted import audit
        body = fields(body, ('proof', 'keyId', 'confirmed'), 'managed bot access confirmation')
        if body.get('confirmed') is not True or not isinstance(body.get('proof'), str) or len(body['proof']) > 8192 or not isinstance(body.get('keyId'), str):
            raise AlphaError('Confirm the exact managed bot access preview.', 403)
        try:
            payload = json.loads(self.telegram.vault.decrypt(body['proof'], body['keyId']))
        except (ValueError, TypeError, AlphaError):
            raise AlphaError('Managed bot access preview is invalid. Prepare it again.', 403) from None
        with self.owned(workspace, token, bot_id) as (provider, me, owner, actor, cur):
            if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in (
                    ('workspace', workspace), ('actor', actor), ('botId', bot_id), ('managerId', me['id']),
                    ('ownerId', owner[0]), ('ownerVersion', owner[1]))) or payload.get('expiresAt', 0) <= self.telegram.clock():
                raise AlphaError('Managed bot owner or preview changed. Prepare it again.', 409)
            current = self.normalize_access(provider.call('getManagedBotAccessSettings', {'user_id': int(bot_id)}))
            if current == payload['after']:
                return {'state': 'confirmed', 'settings': current, 'reconciled': True}
            if current != payload['before']:
                raise AlphaError('Telegram access settings changed. Review a new preview.', 409)
            desired = payload['after']
            result = provider.call('setManagedBotAccessSettings', {'user_id': int(bot_id),
                                   'is_access_restricted': desired['restricted'], 'added_user_ids': desired['addedUserIds']})
            if result is not True:
                raise AlphaError('Telegram did not confirm the managed bot access change. Inspect its settings before retrying.', 502)
            observed = self.normalize_access(provider.call('getManagedBotAccessSettings', {'user_id': int(bot_id)}))
            if observed != desired:
                raise AlphaError('Managed bot access result needs review. Inspect settings before retrying.', 409)
            audit(cur, workspace, actor, 'telegram.managed.access_changed', bot_id,
                  {'restricted': observed['restricted'], 'additionalUsers': len(observed['addedUserIds'])})
            return {'state': 'confirmed', 'settings': observed, 'reconciled': False}

    def status(self, workspace, token):
        from ..hosted import _membership
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), 'manage_connections')
            cur.execute('SELECT username,name,expires_at FROM pr_telegram_managed_requests WHERE workspace_id=%s AND member_id=%s AND expires_at>now() AND completed_at IS NULL', (workspace, actor))
            requests = [{'username':r[0],'name':r[1],'expiresAt':r[2].isoformat()} for r in cur.fetchall()]
            cur.execute('''SELECT DISTINCT b.bot_id,b.username FROM pr_telegram_managed_bots b
                JOIN pr_telegram_identities i ON(i.bot_id=b.manager_bot_id::text AND i.telegram_user_id=b.owner_user_id)
                WHERE i.workspace_id=%s AND i.member_id=%s AND i.revoked_at IS NULL''', (workspace, actor))
            bots = [{'botId':str(r[0]), 'username':r[1]} for r in cur.fetchall()]
        provider = self.telegram.oauth.providers.get('telegram')
        try:
            available = bool(provider and provider.me().get('can_manage_bots') is True)
        except AlphaError:
            available = False
        return {'available':available,'requests':requests,'bots':bots,'requiresVerifiedIdentity':True}

    def start(self, workspace, token, body):
        from ..hosted import _membership, audit
        body = fields(body, ('username','name','identityId','confirmed'), 'managed bot creation')
        username, name = body.get('username'), body.get('name')
        if body.get('confirmed') is not True or not isinstance(username,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{1,28}bot',username,re.I) or not 5<=len(username)<=32 or not isinstance(name,str) or not 1<=len(name.strip())<=64:
            raise AlphaError('Confirm a valid managed bot name and username ending in bot.',400)
        _, me = self.manager()
        with self.repository.transaction(token,workspace) as (cur,row,actor):
            require(_membership(row),'manage_connections');self.repository.assert_fresh(token,actor)
            cur.execute('SELECT telegram_user_id FROM pr_telegram_identities WHERE workspace_id=%s AND member_id=%s AND id=%s AND revoked_at IS NULL AND bot_id=%s',(workspace,actor,body.get('identityId'),str(me['id'])))
            identity=cur.fetchone()
            if not identity:raise AlphaError('Connect and select your Telegram identity first.',403)
            cur.execute("INSERT INTO pr_telegram_managed_requests(workspace_id,member_id,manager_bot_id,owner_user_id,username,name,expires_at) VALUES(%s,%s,%s,%s,%s,%s,now()+interval '15 minutes') ON CONFLICT(manager_bot_id,owner_user_id,username) DO UPDATE SET workspace_id=excluded.workspace_id,member_id=excluded.member_id,name=excluded.name,expires_at=excluded.expires_at,completed_at=NULL",(workspace,actor,me['id'],identity[0],username.lower(),name.strip()))
            audit(cur,workspace,actor,'telegram.managed.creation_requested',username,{})
        return {'creationUrl':'https://t.me/newbot/'+me['username']+'/'+username+'?'+urlencode({'name':name.strip()}),'username':username,'status':'awaiting_telegram_confirmation','botCreated':False}

    def connect(self, workspace, token, body):
        from ..hosted import _membership
        body=fields(body,('username','confirmed'),'managed bot connection')
        if body.get('confirmed') is not True or not isinstance(body.get('username'),str):raise AlphaError('Confirm the selected managed bot and Rafii webhook.',403)
        provider,me=self.manager()
        with self.repository.transaction(token,workspace) as (cur,row,actor):
            require(_membership(row),'manage_connections');self.repository.assert_fresh(token,actor)
            cur.execute('''SELECT b.bot_id,b.owner_user_id FROM pr_telegram_managed_requests r JOIN pr_telegram_managed_bots b ON(b.manager_bot_id=r.manager_bot_id AND b.owner_user_id=r.owner_user_id AND b.username=r.username) JOIN pr_telegram_identities i ON(i.workspace_id=r.workspace_id AND i.member_id=r.member_id AND i.telegram_user_id=r.owner_user_id AND i.bot_id=r.manager_bot_id::text AND i.revoked_at IS NULL) WHERE r.workspace_id=%s AND r.member_id=%s AND r.manager_bot_id=%s AND r.username=%s AND r.expires_at>now()''',(workspace,actor,me['id'],body['username'].lower()))
            owned=cur.fetchone()
            if not owned:raise AlphaError('Await the authorized managed bot creation update from Telegram.',409)
        # Serialize credential retrieval and grant creation with owner/rotation events.
        # The event handler takes this same lock before revoking an earlier grant.
        with self.repository.connection_factory() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('rafii-managed:'+str(me['id'])+':'+str(owned[0]),))
            owner=db.execute('SELECT owner_user_id FROM pr_telegram_managed_bots WHERE manager_bot_id=%s AND bot_id=%s',(me['id'],owned[0])).fetchone()
            if not owner or owner[0]!=owned[1]:raise AlphaError('Managed bot ownership changed. Start again.',409)
            raw=provider.call('getManagedBotToken',{'user_id':owned[0]})
            if not isinstance(raw,str):raise AlphaError('Telegram did not return a managed bot credential.',502)
            result=self.telegram.connect_bot(workspace,token,{'token':raw,'botId':str(owned[0]),'confirmed':True})
        with self.repository.transaction(token,workspace) as (cur,_,_):
            cur.execute('UPDATE pr_telegram_managed_requests SET completed_at=now() WHERE workspace_id=%s AND member_id=%s AND username=%s',(workspace,actor,body['username'].lower()))
        return result


def observe(cur, manager_id, update_id, event):
    """Only authenticated Bot API updates may call this. Transfer/rotation revokes old grants."""
    user,bot=event.get('user'),event.get('bot')
    if not isinstance(user,dict) or not isinstance(bot,dict) or type(user.get('id')) is not int or user.get('is_bot') is True or type(bot.get('id')) is not int or bot.get('is_bot') is not True or not isinstance(bot.get('username'),str):
        raise AlphaError('Invalid managed bot owner update.',400)
    cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('rafii-managed:'+str(manager_id)+':'+str(bot['id']),))
    cur.execute('SELECT owner_user_id,last_update_id FROM pr_telegram_managed_bots WHERE manager_bot_id=%s AND bot_id=%s FOR UPDATE',(manager_id,bot['id']))
    prior=cur.fetchone()
    if prior and update_id<=prior[1]:return
    if prior:
        # Never leave an earlier owner's or earlier token's destinations dispatchable.
        cur.execute("UPDATE pr_encrypted_credentials SET revoked_at=now() WHERE provider='telegram' AND workspace_id IN(SELECT workspace_id FROM pr_telegram_bot_grants WHERE bot_id=%s) AND connection_id IN(SELECT connection_id FROM pr_telegram_destinations WHERE bot_id=%s)",(bot['id'],bot['id']))
        cur.execute('UPDATE pr_telegram_destinations SET revoked_at=now() WHERE bot_id=%s',(bot['id'],))
        cur.execute("UPDATE pr_telegram_bot_grants SET revoked_at=now(),token_ciphertext='',webhook_ciphertext='',key_id='' WHERE bot_id=%s",(bot['id'],))
        if prior[0]!=user['id']:
            cur.execute('DELETE FROM pr_telegram_bot_grants WHERE bot_id=%s AND revoked_at IS NOT NULL',(bot['id'],))
    cur.execute('INSERT INTO pr_telegram_managed_bots(manager_bot_id,bot_id,owner_user_id,username,last_update_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(manager_bot_id,bot_id) DO UPDATE SET owner_user_id=excluded.owner_user_id,username=excluded.username,last_update_id=excluded.last_update_id WHERE excluded.last_update_id>pr_telegram_managed_bots.last_update_id',(manager_id,bot['id'],user['id'],bot['username'].lower(),update_id))
