"""Official YouTube PubSubHubbub subscriptions. Feeds wake read-back; they never prove publication."""
import hashlib
import hmac
import json
import secrets
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit
from xml.etree import ElementTree

from postriff_alpha.domain import AlphaError
from .model import resource_id

HUB = 'https://pubsubhubbub.appspot.com/subscribe'
FEED = 'https://www.youtube.com/feeds/videos.xml'
LEASE_SECONDS = 86400
MAX_FEED_BYTES = 256 * 1024


def feed_entries(raw, channel_id):
    if not isinstance(raw, bytes) or len(raw) > MAX_FEED_BYTES or b'\x00' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise AlphaError('Invalid notification document.', 400)
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise AlphaError('Invalid notification document.', 400) from None
    namespaces = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
    if root.tag != '{http://www.w3.org/2005/Atom}feed':
        raise AlphaError('Invalid notification document.', 400)
    entries = []
    for entry in root.findall('atom:entry', namespaces):
        if entry.findtext('yt:channelId', namespaces=namespaces) != channel_id:
            raise AlphaError('Notification channel mismatch.', 403)
        video = resource_id(entry.findtext('yt:videoId', namespaces=namespaces), 'video')
        entries.append({'videoId': video, 'updated': entry.findtext('atom:updated', namespaces=namespaces)})
    return entries


def verified_signature(raw, header, secret):
    algorithm, _, digest = str(header).partition('=')
    if algorithm not in ('sha1', 'sha256') or not digest:
        return False
    expected = hmac.new(secret.encode(), raw, getattr(hashlib, algorithm)).hexdigest()
    return hmac.compare_digest(expected, digest)


class PushNotifications:
    def __init__(self, creator):
        self.creator = creator
        self.service, self.clock, self.vault = creator.service, creator.clock, creator.oauth.vault

    def _topic(self, channel):
        return FEED + '?' + urlencode({'channel_id': resource_id(channel, 'channel')})

    def preview(self, workspace, token, connection, body):
        actor, channel, _ = self.creator._member(workspace, token, connection, 'manage_connections', fresh=True)
        api = self.creator._api(workspace, connection, channel)
        self.creator._allow(workspace, connection, api, 'identity')
        mode = body.get('mode')
        if mode not in ('subscribe', 'unsubscribe') or type(body.get('automaticRenewal', False)) is not bool:
            raise AlphaError('Choose a notification subscription action.', 400)
        base = self.service.public_base_url
        parsed = urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AlphaError('Official notifications require a configured public HTTPS callback.', 409)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT id::text,status,callback FROM public.pr_youtube_push WHERE workspace_id=%s AND connection_id=%s FOR UPDATE', (workspace, connection))
            row = cur.fetchone()
            if row and row[1] in ('requested', 'outcome_unknown', 'awaiting_verification'):
                raise AlphaError('A subscription request is awaiting reconciliation. It will not be submitted twice.', 409)
            if mode == 'unsubscribe' and not row:
                raise AlphaError('There is no recorded subscription to remove.', 404)
            ident = row[0] if row else str(uuid.uuid4())
            callback = row[2] if row else base.rstrip('/') + '/api/youtube/notifications/' + ident
            plan = {'mode': mode, 'channelId': channel, 'topic': self._topic(channel), 'hub': HUB, 'callback': callback,
                    'automaticRenewal': body.get('automaticRenewal', False) if mode == 'subscribe' else False,
                    'leaseSeconds': LEASE_SECONDS, 'actor': actor, 'expiresAt': self.clock() + 600,
                    'coverage': 'Uploads and title/description changes; every event requires official API read-back.'}
            from .service import fingerprint
            digest = fingerprint(plan)
            verify_token, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            ciphertext, key = self.vault.encrypt(json.dumps({'verifyToken': verify_token, 'secret': secret}))
            cur.execute("""INSERT INTO public.pr_youtube_push(id,workspace_id,connection_id,channel_id,callback,topic,status,secret_ciphertext,secret_key_id,review,review_digest)
                VALUES(%s,%s,%s,%s,%s,%s,'prepared',%s,%s,%s::jsonb,%s)
                ON CONFLICT(workspace_id,connection_id) DO UPDATE SET status='prepared',review=excluded.review,review_digest=excluded.review_digest,
                pending_secret_ciphertext=excluded.secret_ciphertext,pending_secret_key_id=excluded.secret_key_id,updated_at=now()""",
                (ident, workspace, connection, channel, callback, self._topic(channel), ciphertext, key, json.dumps(plan), digest))
        return {'id': ident, 'digest': digest, 'manifest': plan, 'executed': False}

    def approve(self, workspace, token, connection, ident, body):
        self.creator._member(workspace, token, connection, 'manage_connections', fresh=True)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT review,review_digest,status FROM public.pr_youtube_push WHERE workspace_id=%s AND connection_id=%s AND id::text=%s FOR UPDATE', (workspace, connection, ident))
            row = cur.fetchone()
            if not row or body.get('confirmed') is not True or body.get('digest') != row[1]:
                raise AlphaError('Approve the exact notification review.', 400)
            if row[2] != 'prepared':
                return {'id': ident, 'status': row[2], 'retried': False}
            if row[0]['expiresAt'] < self.clock():
                raise AlphaError('The subscription review expired.', 409)
            cur.execute("""UPDATE public.pr_youtube_push SET status='requested',automatic_renewal=%s,
                secret_ciphertext=CASE WHEN review->>'mode'='subscribe' THEN coalesce(pending_secret_ciphertext,secret_ciphertext) ELSE secret_ciphertext END,
                secret_key_id=CASE WHEN review->>'mode'='subscribe' THEN coalesce(pending_secret_key_id,secret_key_id) ELSE secret_key_id END,
                pending_secret_ciphertext=NULL,pending_secret_key_id=NULL,updated_at=now() WHERE id::text=%s""", (row[0]['automaticRenewal'], ident))
        return self._submit(ident)

    def _submit(self, ident):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT workspace_id::text,connection_id,review,secret_ciphertext,secret_key_id FROM public.pr_youtube_push WHERE id::text=%s', (ident,))
            row = cur.fetchone()
        if not row:
            raise AlphaError('Subscription unavailable.', 404)
        workspace, connection, plan, ciphertext, key = row
        api = self.creator._api(workspace, connection, plan['channelId'])
        secret = json.loads(self.vault.decrypt(ciphertext, key))
        form = {'hub.mode': plan['mode'], 'hub.callback': plan['callback'], 'hub.topic': plan['topic'], 'hub.verify': 'async',
                'hub.verify_token': secret['verifyToken'], 'hub.secret': secret['secret'], 'hub.lease_seconds': str(LEASE_SECONDS)}
        try:
            response = api.provider.transport('POST', HUB, form=form)
            status = 'awaiting_verification' if response.get('status') in (202, 204) else 'failed'
        except AlphaError:
            status = 'outcome_unknown'
        from ..hosted import audit
        with self.service.connection_factory() as db, db.cursor() as cur:
            # The async challenge can arrive before the hub submission response.
            cur.execute("UPDATE public.pr_youtube_push SET status=%s,updated_at=now() WHERE id::text=%s AND status='requested'", (status, ident))
            cur.execute('SELECT status FROM public.pr_youtube_push WHERE id::text=%s', (ident,))
            saved = cur.fetchone()
            status = saved[0] if saved else 'unavailable'
            audit(cur, workspace, plan['actor'], 'youtube.notification_requested', ident, {'mode': plan['mode'], 'status': status})
        return {'id': ident, 'status': status, 'source': 'Official YouTube PubSubHubbub hub', 'verified': status in ('active', 'inactive')}

    def callback(self, ident, method, query, raw=b'', signature=''):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT workspace_id::text,connection_id,channel_id,topic,review,status,secret_ciphertext,secret_key_id FROM public.pr_youtube_push WHERE id::text=%s', (ident,))
            row = cur.fetchone()
        if not row:
            raise AlphaError('Notification subscription unavailable.', 410)
        workspace, connection, channel, topic, review, status, ciphertext, key = row
        secret = json.loads(self.vault.decrypt(ciphertext, key))
        if method == 'GET':
            x = parse_qs(query, keep_blank_values=True)
            if any(len(values) != 1 for values in x.values()):
                raise AlphaError('Invalid notification challenge.', 400)
            value = lambda name: x.get(name, [''])[0]
            challenge = value('hub.challenge')
            if (value('hub.mode') != review['mode'] or value('hub.topic') != topic or not challenge or len(challenge) > 4096
                    or not hmac.compare_digest(value('hub.verify_token'), secret['verifyToken'])
                    or status not in ('requested', 'awaiting_verification', 'outcome_unknown')):
                raise AlphaError('Notification challenge denied.', 403)
            try:
                lease = int(value('hub.lease_seconds') or LEASE_SECONDS)
                if not 1 <= lease <= 31 * 86400:
                    raise ValueError()
            except ValueError:
                raise AlphaError('Invalid notification lease.', 400) from None
            state = 'active' if review['mode'] == 'subscribe' else 'inactive'
            with self.service.connection_factory() as db, db.cursor() as cur:
                cur.execute('UPDATE public.pr_youtube_push SET status=%s,lease_expires_at=now()+make_interval(secs=>%s),updated_at=now() WHERE id::text=%s', (state, lease, ident))
            return challenge.encode()
        if method != 'POST' or status not in ('active', 'prepared', 'requested', 'awaiting_verification') or len(raw) > MAX_FEED_BYTES:
            raise AlphaError('Notification delivery denied.', 403)
        if not verified_signature(raw, signature, secret['secret']):
            raise AlphaError('Notification signature denied.', 403)
        entries = feed_entries(raw, channel)
        digest = hashlib.sha256(raw).hexdigest()
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("""INSERT INTO public.pr_youtube_cache(workspace_id,connection_id,cache_key,source,data,expires_at)
                VALUES(%s,%s,%s,'YouTube official push notification','{}'::jsonb,now()+interval '1 day')
                ON CONFLICT(workspace_id,connection_id,cache_key) DO NOTHING RETURNING cache_key""", (workspace, connection, 'push-event:' + digest))
            if not cur.fetchone():
                return b''
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
            saved = cur.fetchone()
            state = saved[0] if saved else {}
            if isinstance(state, str):
                state = json.loads(state)
            ids, changed = {entry['videoId'] for entry in entries}, False
            for job in state.get('phase2', {}).get('jobs', []):
                manifest, progress = job.get('manifest', {}), job.get('progress', {})
                if (manifest.get('channelId') == connection and progress.get('videoId') in ids
                        and job.get('state') in ('provider_accepted', 'uncertain')):
                    job['nextAt'] = self.clock()
                    changed = True
            if changed:
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), workspace))
            cur.execute("DELETE FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s AND (cache_key LIKE 'videos:%%' OR cache_key LIKE 'identity:%%')", (workspace, connection))
        return b''

    def renew_one(self):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT id::text FROM public.pr_youtube_push WHERE status='active' AND automatic_renewal
                AND lease_expires_at<now()+interval '6 hours' ORDER BY lease_expires_at LIMIT 1 FOR UPDATE SKIP LOCKED""")
            row = cur.fetchone()
            if not row:
                return False
            cur.execute("UPDATE public.pr_youtube_push SET status='requested',updated_at=now() WHERE id::text=%s", (row[0],))
        self._submit(row[0])
        return True
