"""Disposable PostgreSQL acceptance with a synthetic Google transport. Never real E2E."""
import copy
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube.model import READ, UPLOAD, MANAGE, ANALYTICS, MONEY
from postriff_phase2.youtube.provider import YouTubeProvider
from postriff_phase2.youtube.journal import purge_authorized_data

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE, TWO = ('00000000-0000-0000-0000-00000000000' + str(n) for n in (1, 2))
CHANNEL = 'UC' + 'a' * 22

def connection():
    return psycopg.connect(DSN, client_encoding='utf8')

def verify(token):
    return {'one': ONE, 'two': TWO}[token]
verify.session_id = lambda token, actor: 'synthetic-youtube-session-' + token
verify.auth_time = lambda token, actor: time.time()

with connection() as db:
    db.execute((ROOT / 'migrations/postriff/089_youtube_creator.sql').read_text())
    db.execute((ROOT / 'migrations/postriff/089_youtube_creator.sql').read_text())
    db.execute((ROOT / 'migrations/postriff/097_youtube_capacity.sql').read_text())
    db.execute((ROOT / 'migrations/postriff/097_youtube_capacity.sql').read_text())
    db.execute('DELETE FROM public.pr_account_tombstones WHERE user_id=%s', (TWO,))
    db.execute("UPDATE public.pr_memberships SET status='active' WHERE user_id=%s", (TWO,))
    db.execute('UPDATE public.pr_profiles SET deleted_at=NULL WHERE user_id=%s', (TWO,))
    workspaces = {str(user): str(wid) for user, wid in db.execute('SELECT user_id,workspace_id FROM public.pr_memberships')}
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id IN (%s,%s)", (workspaces[ONE], workspaces[TWO]))

class Google:
    scopes = [READ, UPLOAD, MANAGE, ANALYTICS]
    fail_exchange, fail_refresh, omit_refresh, fail_write = False, False, False, False
    writes, exchanges, revocations = 0, 0, 0
    playlists = {}
    action_id = None
    hub_forms = []

    def __call__(self, method, url, **kwargs):
        path, q = urlsplit(url).path, parse_qs(urlsplit(url).query)
        if url == 'https://pubsubhubbub.appspot.com/subscribe':
            self.hub_forms.append(kwargs['form'])
            return {'status': 204, 'body': {}}
        if path == '/token':
            form = kwargs['form']
            if form['grant_type'] == 'authorization_code':
                # Observe through another connection: a rollback can never resurrect the one-use state.
                with connection() as db:
                    assert db.execute("SELECT count(*) FROM public.pr_oauth_transactions WHERE outcome='exchange_started' AND consumed_at IS NOT NULL").fetchone()[0] >= 1
                self.exchanges += 1
                if self.fail_exchange:
                    raise AlphaError('Synthetic network loss.', 503)
                assert form['code_verifier'] and form['redirect_uri'] == 'https://rafii.example/api/oauth/youtube/callback'
            elif self.fail_refresh:
                return {'status': 400, 'body': {'error': 'invalid_grant'}}
            body = {'access_token': 'synthetic-access-' + str(self.exchanges), 'expires_in': 3600, 'scope': ' '.join(self.scopes)}
            if not self.omit_refresh:
                body['refresh_token'] = 'synthetic-refresh'
            return {'status': 200, 'body': body}
        if path == '/tokeninfo':
            return {'status': 200, 'body': {'aud': 'synthetic.apps.googleusercontent.com', 'scope': ' '.join(self.scopes)}}
        if path == '/revoke':
            self.revocations += 1
            return {'status': 200, 'body': {}}
        if path.endswith('/channels'):
            return {'status': 200, 'body': {'items': [{'id': CHANNEL, 'snippet': {'title': 'Synthetic ordinary creator', 'description': ''}, 'statistics': {'viewCount': '12'}, 'status': {'longUploadsStatus': 'allowed'}, 'contentDetails': {'relatedPlaylists': {'uploads': 'UU' + 'a' * 22}}}]}}
        if path.endswith('/playlists'):
            if method == 'POST':
                with connection() as db:
                    assert db.execute('SELECT status FROM public.pr_youtube_actions WHERE id::text=%s', (self.action_id,)).fetchone()[0] == 'started'
                self.writes += 1
                if self.fail_write:
                    raise AlphaError('Synthetic ambiguous write.', 503)
                item = {'id': 'PLsynthetic-' + str(self.writes), **copy.deepcopy(kwargs['body'])}
                item['snippet']['channelId'] = CHANNEL
                self.playlists[item['id']] = item
                return {'status': 200, 'body': item}
            if method == 'DELETE':
                self.writes += 1
                self.playlists.pop(q['id'][0], None)
                return {'status': 204, 'body': {}}
            return {'status': 200, 'body': {'items': [self.playlists[q['id'][0]]] if q.get('id') and q['id'][0] in self.playlists else []}}
        raise AssertionError(('Unexpected synthetic API request', method, path))

google = Google()
provider = YouTubeProvider('synthetic.apps.googleusercontent.com', 'synthetic-secret', transport=google, creator_enabled=True)
vault = CredentialVault(CredentialVault.generate_key())
service = HostedWorkspaceService(connection, verify, vault=vault, providers={'youtube': provider}, public_base_url='https://rafii.example')
for token, plan in (('one', 'studio'), ('two', 'assist')):
    service.bootstrap(token, plan)
wid, foreign = workspaces[ONE], workspaces[TWO]

def authorize(workspace, token, feature='publish', conn=None):
    started = service.oauth.start(workspace, token, 'youtube', feature, {'connectionId': conn} if conn else {})
    state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
    result = service.oauth.complete(workspace, token, 'youtube', state, 'synthetic-code')
    before = google.exchanges
    try:
        service.oauth.complete(workspace, token, 'youtube', state, 'synthetic-code')
        raise AssertionError('OAuth state replay accepted')
    except AlphaError as error:
        assert error.status == 404
    assert google.exchanges == before
    return result['connectionId']

conn = authorize(wid, 'one')
assert authorize(foreign, 'two') == conn  # canonical channel identity is workspace-scoped.
with connection() as db:
    row = db.execute('SELECT access_ciphertext,refresh_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (wid, conn)).fetchone()
    assert 'synthetic-access' not in row[0] and 'synthetic-refresh' not in row[1]
    assert json.loads(vault.decrypt(row[1], row[2])) == {'clientId': provider.client_id, 'authorizationLane': provider.authorization_lane, 'rt': 'synthetic-refresh', 'v': 2}

google.omit_refresh = True
assert authorize(wid, 'one', 'manage_video', conn) == conn
with connection() as db:
    row = db.execute('SELECT refresh_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (wid, conn)).fetchone()
    assert json.loads(vault.decrypt(row[0], row[1]))['rt'] == 'synthetic-refresh'
    db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=now()-interval '1 second' WHERE workspace_id=%s AND connection_id=%s", (wid, conn))
assert service.oauth.token_for_worker(wid, conn)['scopes'] == sorted(google.scopes)
overview = service.youtube.overview(wid, 'one', conn)
assert len(overview['capabilities']) == 37
assert overview['capabilities']['public_publish']['state'] == 'BLOCKED — GOOGLE APPROVAL'
assert overview['capabilities']['monetary_analytics']['state'] == 'NOT AUTHORIZED'
assert not any(c['state'] == 'READY' for c in overview['capabilities'].values())
try:
    service.youtube.overview(foreign, 'one', conn)
    raise AssertionError('Foreign workspace accepted')
except AlphaError as error:
    assert error.status in (403, 404)
try:
    service.oauth.start(wid, 'one', 'youtube', 'monetary_analytics', {'connectionId': conn, 'enableSensitive': True})
    raise AssertionError('Unrequested monetary access accepted')
except AlphaError as error:
    assert error.status == 403

def action(name, inputs, key):
    return service.youtube.preview(wid, 'one', conn, {'action': name, 'inputs': inputs, 'operationKey': key})

review = action('playlist.create', {'snippet': {'title': 'Exact reviewed title', 'description': 'Line 1\nLine 2'}, 'privacyStatus': 'private'}, 'playlist-one')
google.action_id = review['id']
accepted = service.youtube.approve(wid, 'one', conn, review['id'], {'confirmed': True, 'digest': review['digest']})
assert accepted['status'] == 'verified' and accepted['receipt']['execution'] == 'transport-injected'
playlist = accepted['receipt']['result']['id']
count = google.writes
repeated = service.youtube.approve(wid, 'one', conn, review['id'], {'confirmed': True, 'digest': review['digest']})
assert repeated['retried'] is False and google.writes == count
service.youtube.reconcile_action(wid, 'one', conn, review['id'])
assert google.writes == count

delete = action('playlist.delete', {'id': playlist}, 'playlist-delete')
try:
    service.youtube.approve(wid, 'one', conn, delete['id'], {'confirmed': True, 'digest': delete['digest'], 'confirmationTarget': 'wrong'})
    raise AssertionError('Wrong destructive resource accepted')
except AlphaError as error:
    assert error.status == 400
deleted = service.youtube.approve(wid, 'one', conn, delete['id'], {'confirmed': True, 'digest': delete['digest'], 'confirmationTarget': playlist})
assert deleted['status'] == 'verified' and playlist not in google.playlists

ambiguous = action('playlist.create', {'snippet': {'title': 'Ambiguous'}, 'privacyStatus': 'private'}, 'playlist-unknown')
google.action_id, google.fail_write = ambiguous['id'], True
unknown = service.youtube.approve(wid, 'one', conn, ambiguous['id'], {'confirmed': True, 'digest': ambiguous['digest']})
assert unknown['status'] == 'outcome_unknown'
count = google.writes
service.youtube.approve(wid, 'one', conn, ambiguous['id'], {'confirmed': True, 'digest': ambiguous['digest']})
service.youtube.reconcile_action(wid, 'one', conn, ambiguous['id'])
assert google.writes == count
google.fail_write = False

# Server-only tables reject both ordinary signed-in SQL and anonymous SQL, even for owned IDs.
tables = ('uploads', 'actions', 'usage', 'settings', 'cache', 'chat_cursor', 'reporting_coverage', 'push')
for role in ('authenticated', 'anon'):
    for name in tables:
        with connection() as db:
            db.execute('SET ROLE ' + role)
            try:
                db.execute('SELECT * FROM public.pr_youtube_' + name)
                raise AssertionError('Browser-readable creator data: ' + name)
            except psycopg.errors.InsufficientPrivilege:
                pass
with connection() as db:
    db.execute('SET ROLE service_role')
    assert db.execute('SELECT count(*) FROM public.pr_youtube_actions').fetchone()[0] >= 3
with connection() as db:
    try:
        db.execute("INSERT INTO public.pr_youtube_settings(workspace_id,connection_id) VALUES(%s,'foreign-connection')", (wid,))
        raise AssertionError('Orphan creator credential accepted')
    except psycopg.errors.ForeignKeyViolation:
        pass

# Failed exchange remains consumed after its transaction rolls back.
failed = service.oauth.start(wid, 'one', 'youtube', 'identity')
failed_state = parse_qs(urlsplit(failed['authorizeUrl']).query)['state'][0]
google.fail_exchange = True
try:
    service.oauth.complete(wid, 'one', 'youtube', failed_state, 'synthetic-code')
    raise AssertionError('Expected synthetic exchange failure')
except AlphaError:
    pass
google.fail_exchange = False
count = google.exchanges
try:
    service.oauth.complete(wid, 'one', 'youtube', failed_state, 'synthetic-code')
    raise AssertionError('Failed exchange replayed')
except AlphaError as error:
    assert error.status == 404
assert google.exchanges == count

# Background authorization refresh and content expiry are bounded to one creator per tick.
maintenance = service.youtube.maintenance()
assert maintenance['enabled'] and maintenance['authorizationChecked']
assert service.youtube._cached(wid, conn, 'authorization-check') or service.youtube._cached(foreign, conn, 'authorization-check')
service.youtube.sensitive(wid, 'one', conn, {'capability': 'monetary', 'enabled': False, 'confirmed': True})
service.youtube.record_eligibility(wid, conn, CHANNEL, 'thumbnail', 'synthetic-readback')
assert service.youtube.overview(wid, 'one', conn)['capabilities']['thumbnail']['state'] != 'READY'
with connection() as db:
    db.execute("UPDATE public.pr_memberships SET role='viewer',can_publish=false WHERE workspace_id=%s AND user_id=%s", (wid, ONE))
assert service.youtube.overview(wid, 'one', conn)['capabilities']['private_publish']['canExecute'] is False
with connection() as db:
    db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s", (wid, ONE))

# A reviewed, encrypted subscription cannot duplicate, accept a foreign challenge or trust an unsigned feed.
push = service.youtube.notifications.preview(wid, 'one', conn, {'mode': 'subscribe', 'automaticRenewal': True})
assert not google.hub_forms
requested = service.youtube.notifications.approve(wid, 'one', conn, push['id'], {'confirmed': True, 'digest': push['digest']})
assert requested['status'] == 'awaiting_verification'
service.youtube.notifications.approve(wid, 'one', conn, push['id'], {'confirmed': True, 'digest': push['digest']})
assert len(google.hub_forms) == 1
form = google.hub_forms[0]
challenge = {'hub.mode': 'subscribe', 'hub.topic': form['hub.topic'], 'hub.challenge': 'synthetic-challenge', 'hub.verify_token': form['hub.verify_token'], 'hub.lease_seconds': '86400'}
from urllib.parse import urlencode
assert service.youtube.notifications.callback(push['id'], 'GET', urlencode(challenge)) == b'synthetic-challenge'
try:
    service.youtube.notifications.callback(push['id'], 'GET', urlencode(challenge | {'hub.verify_token': 'foreign'}))
    raise AssertionError('Foreign challenge accepted')
except AlphaError as error:
    assert error.status == 403
feed = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:channelId>'
        + CHANNEL + '</yt:channelId><yt:videoId>abcdefghijk</yt:videoId><updated>2026-10-05T00:00:00Z</updated></entry></feed>').encode()
signature = 'sha1=' + hmac.new(form['hub.secret'].encode(), feed, hashlib.sha1).hexdigest()
try:
    service.youtube.notifications.callback(push['id'], 'POST', '', feed, 'sha1=foreign')
    raise AssertionError('Unsigned notification accepted')
except AlphaError as error:
    assert error.status == 403
service.youtube.notifications.callback(push['id'], 'POST', '', feed, signature)
service.youtube.notifications.callback(push['id'], 'POST', '', feed, signature)
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s AND cache_key LIKE 'push-event:%%'", (wid, conn)).fetchone()[0] == 1
    encrypted = db.execute('SELECT secret_ciphertext FROM public.pr_youtube_push WHERE id::text=%s', (push['id'],)).fetchone()[0]
    assert form['hub.secret'] not in encrypted and form['hub.verify_token'] not in encrypted

# Aged API comments disappear from reads before maintenance, including approval previews.
# Retention remains active with creator execution disabled; no Google calls are needed.
from postriff_phase2.youtube.comments import reply_target
with connection() as db:
    aged = db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text,ingested_at) VALUES(%s,%s,'youtube','synthetic-video','aged-comment','old API text',now()-interval '31 days') RETURNING id::text", (wid, conn)).fetchone()[0]
    fresh = db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,%s,'youtube','synthetic-video','fresh-comment','fresh API text') RETURNING id::text", (wid, conn)).fetchone()[0]
    other = db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text,ingested_at) VALUES(%s,%s,'instagram','synthetic-post','unrelated-aged','keep other provider',now()-interval '31 days') RETURNING id::text", (wid, conn)).fetchone()[0]
    aged_draft = db.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status) VALUES(%s,%s,%s,'manual','saved draft','draft') RETURNING id::text", (wid, aged, ONE)).fetchone()[0]
view = service.audience.threads(wid, 'one')
ids = {item['threadId'] for item in view['threads']}
assert aged not in ids and fresh in ids and other in ids
assert view['counts']['all'] == len(ids)
assert reply_target(connection, wid, aged) is None
assert reply_target(connection, wid, fresh)['commentId'] == 'fresh-comment'
for operation in (
    lambda: service.audience.draft_reply(wid, 'one', aged, {'origin': 'manual', 'text': 'blocked'}),
    lambda: service.audience.reply_preview(wid, 'one', aged_draft),
):
    try:
        operation()
        raise AssertionError('Expired YouTube context was exposed')
    except AlphaError as error:
        assert error.status == 404
provider.creator_enabled = False
before_calls = (google.writes, google.exchanges, google.revocations)
from postriff_phase2.hosted_worker import PostgresWorker, DisabledHostedSocial
cleanup_worker = PostgresWorker(connection, youtube_maintenance=service.youtube)
assert isinstance(cleanup_worker.social, DisabledHostedSocial)
cleanup_worker.step = lambda: False
assert cleanup_worker.tick(max_jobs=1, max_seconds=1)['youtubeMaintenance'] == {'enabled': False, 'dataCleanup': True}
assert before_calls == (google.writes, google.exchanges, google.revocations)
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_audience_threads WHERE id::text=%s', (aged,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM public.pr_reply_drafts WHERE id::text=%s', (aged_draft,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM public.pr_audience_threads WHERE id::text IN (%s,%s)', (fresh, other)).fetchone()[0] == 2
assert service.youtube.maintenance()['dataCleanup']  # safe replay after deletion
provider.creator_enabled = True

service.youtube._cache(wid, conn, 'private-test', {'secretCreatorData': 'synthetic'})
service.youtube._cache(foreign, conn, 'private-test', {'secretCreatorData': 'other-workspace'})
# A distinct Brand Channel ID cannot prove that Google project/account revocation is isolated.
with connection() as db:
    db.execute("UPDATE public.pr_encrypted_credentials SET provider_account_id=%s WHERE workspace_id=%s AND connection_id=%s", ('UC' + 'b' * 22, foreign, conn))
disconnected = service.oauth.disconnect(wid, 'one', conn)
assert disconnected['disconnected'] and disconnected['remoteRevoked'] is False and disconnected['remoteRevocationDeferred'] is True and google.revocations == 0
with connection() as db:
    db.execute("UPDATE public.pr_encrypted_credentials SET provider_account_id=%s WHERE workspace_id=%s AND connection_id=%s", (CHANNEL, foreign, conn))
    assert db.execute('SELECT count(*) FROM public.pr_youtube_cache WHERE workspace_id=%s', (wid,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM public.pr_youtube_actions WHERE workspace_id=%s', (wid,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM public.pr_youtube_cache WHERE workspace_id=%s', (foreign,)).fetchone()[0] >= 1
    db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=now()-interval '1 second' WHERE workspace_id=%s AND connection_id=%s", (foreign, conn))
google.fail_refresh = True
try:
    service.oauth.token_for_worker(foreign, conn)
    raise AssertionError('Revoked refresh grant accepted')
except AlphaError as error:
    assert error.code == 'youtube_revoked_oauth'
with connection() as db:
    row = db.execute('SELECT revoked_at,access_ciphertext,refresh_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (foreign, conn)).fetchone()
    assert row[0] is not None and row[1] == '' and row[2] is None
    assert db.execute('SELECT count(*) FROM public.pr_youtube_cache WHERE workspace_id=%s', (foreign,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE %s", (wid, 'youtube.%')).fetchone()[0] >= 5

print(json.dumps({'status': 'pass', 'execution': 'disposable local PostgreSQL; synthetic Google transport; NOT real E2E',
                  'checks': ['idempotent migration', 'one-use OAuth state committed before exchange and survives rollback', 'encrypted tokens', 'incremental refresh preservation', 'refresh recovery', '37 independent capability gates', 'monetary access off', 'two-workspace isolation', 'browser SQL denied', 'credential foreign keys', 'write intent committed before API call', 'destructive target confirmation', 'readback and read-only reconciliation', 'ambiguous write never repeated', 'bounded authorization revalidation', 'viewer cannot execute creator writes', 'encrypted signed push subscription and duplicate delivery', 'shared-workspace disconnect preserves other grant', 'revocation purges authorized data', 'aged comment read/approval denial', 'feature-disabled retention and cascading draft cleanup']}))
