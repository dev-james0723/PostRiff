"""Bounded signed HTTP interactions; no token retention, draft reads or sends."""
import json
from contextlib import contextmanager
import re
import time
from urllib.parse import urlencode, urlsplit
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from postriff_alpha.domain import AlphaError
from .authorization import snowflake

COMMAND = {'name': 'rafii-drafts', 'type': 1, 'description': 'Open your private Rafii drafts and review',
           'integration_types': [1], 'contexts': [1, 2],
           'description_localizations': {'zh-TW': '開啟你的私密 Rafii 草稿及審閱', 'zh-CN': '打开你的私密 Rafii 草稿及审核'}}


def deny(message='Discord interaction unavailable. Open Rafii to reconnect.', status=401):
    raise AlphaError(message, status, code='discord_interaction_unavailable')


def configuration(provider, *, verification_only=False):
    raw = getattr(provider, 'interaction_config_raw', None)
    try:
        value = json.loads(raw) if isinstance(raw, str) and len(raw) <= 4096 else raw
        if (not isinstance(value, dict) or value.get('applicationId') != provider.client_id
                or not isinstance(value.get('publicKey'), str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value['publicKey'])
                or urlsplit(value.get('endpoint', '')).scheme != 'https'
                or urlsplit(value['endpoint']).path != '/api/discord/interactions'):
            deny(status=503)
        if not verification_only and (
                not snowflake(value.get('commandId')) or not snowflake(value.get('commandVersion'))
                or value.get('commandName') != COMMAND['name'] or value.get('integrationTypes') != [1]
                or value.get('contexts') != [1, 2]
                or any(type(x) is not int for x in value.get('contexts', []) + value.get('integrationTypes', []))
                or value.get('qualified') is not True):
            deny(status=503)
        if getattr(provider, 'website', None) and value['endpoint'] != provider.website + '/api/discord/interactions':
            deny(status=503)
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        deny(status=503)


def available(provider):
    if not provider or not getattr(provider, 'user_install_v1_enabled', False) or not getattr(provider, 'execution_enabled', True):
        return False
    try:
        configuration(provider)
        return True
    except AlphaError:
        return False


def install_link(provider):
    if not available(provider): deny(status=503)
    return provider.AUTH + '?' + urlencode({'client_id': provider.client_id, 'scope': 'applications.commands', 'integration_type': '1'})


def unique_object(items):
    value = {}
    for key, item in items:
        if key in value: raise ValueError('duplicate key')
        value[key] = item
    return value


class DiscordInteractions:
    def __init__(self, provider, connection_factory, web_base_url, *, clock=None, monotonic=time.monotonic):
        self.provider, self.connection_factory = provider, connection_factory
        self.web_base_url, self.clock, self.monotonic = web_base_url.rstrip('/'), clock or time.time, monotonic

    @contextmanager
    def persistence(self):
        bounded = getattr(self.connection_factory, 'bounded', None)
        if not callable(bounded): deny('Bounded Discord interaction storage is unavailable.', 503)
        with bounded(0.2) as db, db.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300ms'")
            cur.execute("SET LOCAL lock_timeout='100ms'")
            yield cur

    def process(self, subject, interaction):
        # One bounded DB checkout, one committed replay claim and scoped lookup.
        with self.persistence() as cur:
            if not self.claim(self.provider.client_id, interaction, cur=cur):
                deny('This Discord interaction was already used.', 409)
            return self.resolve(subject, cur=cur)

    def claim(self, app, interaction, *, cur=None):
        # Committed one-use ID before response. Raw body/token never enters DB.
        if cur is None:
            with self.persistence() as cursor:
                return self.claim(app, interaction, cur=cursor)
        cur.execute('INSERT INTO public.pr_discord_interaction_replays(application_id,interaction_id) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING interaction_id', (app, interaction))
        return cur.fetchone() is not None

    def resolve(self, subject, *, cur=None):
        if cur is None:
            with self.persistence() as cursor:
                return self.resolve(subject, cur=cursor)
        cur.execute("""SELECT b.workspace_id::text,b.member_id::text,b.identity_connection_id FROM public.pr_discord_interaction_links b
                JOIN public.pr_workspaces w ON w.id=b.workspace_id
                JOIN public.pr_memberships m ON m.workspace_id=b.workspace_id AND m.user_id=b.member_id AND m.status='active'
                JOIN public.pr_profiles p ON p.user_id=m.user_id AND p.deleted_at IS NULL
                JOIN public.pr_encrypted_credentials c ON c.workspace_id=b.workspace_id AND c.connection_id=b.identity_connection_id
                WHERE b.application_id=%s AND b.discord_user_id=%s AND b.revoked_at IS NULL AND c.revoked_at IS NULL
                  AND c.authorization_generation=b.identity_generation AND c.access_expires_at>now()
                  AND NOT (w.state ? 'accountDeletion') AND NOT (w.state ? 'accountBlock')
                  AND EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,discordIdentityLinks}','[]'::jsonb)) x
                    WHERE x->>'id'=b.identity_connection_id AND x->>'workspaceId'=b.workspace_id::text
                    AND x->>'authorizedBy'=b.member_id::text AND x->>'userId'=b.discord_user_id AND x->>'status'='linked'
                    AND x->>'authorizationGeneration'=b.identity_generation::text)
                LIMIT 2""", (self.provider.client_id, subject))
        return [{'workspaceId': r[0], 'memberId': r[1], 'identityId': r[2]} for r in cur.fetchall()]

    def bind(self, connections, workspace, token, identity_id, *, remove=False):
        if not remove and not available(self.provider): deny(status=503)
        if not snowflake(getattr(self.provider, 'client_id', None)): deny(status=503)
        from .oauth import identity_record
        with connections.local(workspace, token) as (cur, state, actor):
            connections.oauth.repository.assert_fresh(token, actor)
            record = identity_record(state, identity_id, actor)
            if remove:
                cur.execute('UPDATE public.pr_discord_interaction_links SET revoked_at=now() WHERE workspace_id=%s AND member_id=%s AND application_id=%s AND discord_user_id=%s', (workspace, actor, self.provider.client_id, record['userId']))
            else:
                row, _ = connections.bind_identity(cur, workspace, record)
                if not row[3] or float(row[3]) <= self.clock(): deny(status=409)
                cur.execute('''INSERT INTO public.pr_discord_interaction_links(workspace_id,member_id,application_id,discord_user_id,identity_connection_id,identity_generation)
                    VALUES(%s,%s,%s,%s,%s,%s::uuid) ON CONFLICT(workspace_id,member_id,application_id,discord_user_id)
                    DO UPDATE SET identity_connection_id=excluded.identity_connection_id,identity_generation=excluded.identity_generation,revoked_at=NULL''',
                    (workspace, actor, self.provider.client_id, record['userId'], identity_id, row[4]))
            record['privateDraftsLinked'] = not remove
            record['privateDraftsGeneration'] = None if remove else row[4]
            connections.save_state(cur, workspace, state)
        return {'linked': not remove, 'senderKind': 'interaction', 'canPublish': False, 'canSchedule': False}

    def review_entry(self, connections, workspace, token, identity):
        from .oauth import identity_record
        with connections.local(workspace, token) as (cur, state, actor):
            record = identity_record(state, identity, actor)
            row, _ = connections.bind_identity(cur, workspace, record)
            if not row[3] or float(row[3]) <= self.clock(): deny(status=409)
            cur.execute('''SELECT true FROM public.pr_discord_interaction_links WHERE workspace_id=%s AND member_id=%s
                AND application_id=%s AND identity_connection_id=%s AND discord_user_id=%s
                AND identity_generation=%s::uuid AND revoked_at IS NULL''',
                (workspace, actor, self.provider.client_id, identity, record['userId'], row[4]))
            if not cur.fetchone(): deny(status=403)
        return {'workspaceId': workspace, 'ready': True}

    def receive(self, raw, timestamp, signature):
        started = self.monotonic()
        if (not self.provider or not getattr(self.provider, 'user_install_v1_enabled', False)
                or not getattr(self.provider, 'execution_enabled', True)): deny(status=503)
        config = configuration(self.provider, verification_only=True)
        if config['endpoint'] != self.web_base_url + '/api/discord/interactions': deny(status=503)
        if (not isinstance(raw, bytes) or not 1 <= len(raw) <= 65536
                or not isinstance(timestamp, str) or not re.fullmatch(r'[0-9]{10,12}', timestamp)
                or abs(self.clock() - int(timestamp)) > 300
                or not isinstance(signature, str) or not re.fullmatch(r'[0-9a-fA-F]{128}', signature)):
            deny()
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(config['publicKey'])).verify(bytes.fromhex(signature), timestamp.encode() + raw)
            packet = json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (InvalidSignature, ValueError, UnicodeError, RecursionError):
            deny()
        if not isinstance(packet, dict) or packet.get('application_id') != self.provider.client_id: deny()
        if type(packet.get('type')) is not int: deny()
        if packet['type'] == 1: return {'type': 1}
        config = configuration(self.provider)  # all useful interactions remain hard-gated
        data = packet.get('data')
        user, member = packet.get('user'), packet.get('member')
        subject = user.get('id') if isinstance(user, dict) else None
        if (packet['type'] != 2 or not snowflake(packet.get('id')) or type(packet.get('context')) is not int
                or packet['context'] not in config['contexts'] or member is not None or packet.get('guild_id') is not None
                or not snowflake(subject) or packet.get('authorizing_integration_owners') != {'1': subject}
                or not isinstance(data, dict) or data.get('id') != config['commandId'] or data.get('name') != COMMAND['name']
                or type(data.get('type')) is not int or data['type'] != 1
                or 'options' in data and data['options'] != [] or data.get('target_id')
                or data.get('guild_id') is not None):
            deny()
        links = self.process(subject, packet['id'])
        origin = urlsplit(self.web_base_url)
        if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password: deny(status=503)
        # Link contains no draft IDs/content or bearer authority; Rafii authenticates
        # its normal session and verifies membership before showing any workspace.
        url = self.web_base_url + '/app/channels?connect=discord'
        text = 'Open Rafii and link or reconnect one account/workspace for private drafts: '
        if len(links) == 1:
            url = self.web_base_url + '/app/queue/discord?' + urlencode({'workspaceId': links[0]['workspaceId'], 'identityId': links[0].get('identityId', '')})
            text = 'Open your private Rafii drafts and review (sign in required): '
        if self.monotonic() - started >= 2.0: deny('Open Rafii to continue. Interaction response deadline reached.', 503)
        return {'type': 4, 'data': {'flags': 64, 'content': text + url, 'allowed_mentions': {'parse': []}}}
