"""Cloud-only disposable PostgreSQL revocation races; Google I/O is synthetic.

Run after tests/phase2/rls.sql (including 089, 097, 098). This executes real
OAuth/journal/worker paths against the private CI database, not real Google
acceptance. Do not import postgres_youtube_creator: it executes a whole suite.
"""
import copy
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube.model import ANALYTICS, MANAGE, READ, UPLOAD
from postriff_phase2.youtube.provider import YouTubeProvider
from postriff_phase2.youtube.uploads import UploadEngine
from youtube_policy_fixture import register_synthetic_policy, accept_synthetic_policy

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
USER = str(uuid4())
TOKEN = 'synthetic-revocation-session-' + uuid4().hex
CHANNEL, VIDEO = 'UC' + 'z' * 22, 'abcdefghijk'
CLIENT = 'synthetic-revocation.apps.googleusercontent.com'
LOCAL = threading.local()
WORKSPACE = CONNECTION = None


@contextmanager
def connection():
    # An environment variable cannot redirect this fixture to another database.
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert db.info.host == '127.0.0.1' and db.info.port == 55438 and db.info.dbname == 'postgres'
        tracked = getattr(LOCAL, 'connections', None)
        if tracked is not None:
            tracked.put(db.info.backend_pid)
        wrap_connection = getattr(LOCAL, 'wrap_connection', None)
        yield wrap_connection(db) if wrap_connection else db
        # Deterministic latch before a real OAuth transaction commits. It
        # changes neither the production SQL nor its transaction boundary.
        before_commit = getattr(LOCAL, 'before_commit', None)
        if before_commit is not None:
            before_commit(db)


def verify(token):
    assert token == TOKEN, 'Only this fixture synthetic session is accepted.'
    return USER


verify.session_id = lambda token, actor: TOKEN
verify.auth_time = lambda token, actor: time.time()


class Google:
    """Exact allowlist; unexpected requests fail without any network I/O."""
    scopes = [READ, UPLOAD, MANAGE, ANALYTICS]

    def __init__(self):
        self.calls = []
        self.exchanges = self.refreshes = self.revocations = 0
        self.offset = 0
        self.on_initialize = self.on_channels = None

    def __call__(self, method, url, **kwargs):
        parsed = urlsplit(url)
        self.calls.append((method, parsed.path, copy.deepcopy(kwargs.get('headers', {}))))
        if url == 'https://oauth2.googleapis.com/token' and method == 'POST':
            form = kwargs['form']
            if form['grant_type'] == 'authorization_code':
                assert form['code_verifier'] and form['redirect_uri'] == 'https://rafii.example/api/oauth/youtube/callback'
                self.exchanges += 1
            else:
                assert form['grant_type'] == 'refresh_token' and form['refresh_token'] == 'synthetic-refresh'
                self.refreshes += 1
            return {'status': 200, 'body': {
                'access_token': f'synthetic-access-{self.exchanges}-{self.refreshes}',
                'refresh_token': 'synthetic-refresh', 'expires_in': 3600, 'scope': ' '.join(self.scopes)}}
        if url.startswith('https://oauth2.googleapis.com/tokeninfo?') and method == 'GET':
            return {'status': 200, 'body': {'aud': CLIENT, 'scope': ' '.join(self.scopes)}}
        if url == 'https://oauth2.googleapis.com/revoke' and method == 'POST':
            self.revocations += 1
            return {'status': 200, 'body': {}}
        if parsed.netloc == 'www.googleapis.com' and parsed.path == '/youtube/v3/channels' and method == 'GET':
            callback, self.on_channels = self.on_channels, None
            if callback:
                callback()
            return {'status': 200, 'body': {'items': [{
                'id': CHANNEL, 'snippet': {'title': 'Synthetic revocation creator'},
                'statistics': {'viewCount': '12'}, 'status': {'longUploadsStatus': 'allowed'},
                'contentDetails': {'relatedPlaylists': {'uploads': 'UU' + 'z' * 22}}}]}}
        if parsed.netloc == 'www.googleapis.com' and parsed.path == '/upload/youtube/v3/videos':
            query = parse_qs(parsed.query)
            if method == 'POST' and query.get('uploadType') == ['resumable']:
                assert kwargs['body']['status']['privacyStatus'] == 'private'
                self.offset = 0
                callback, self.on_initialize = self.on_initialize, None
                if callback:
                    callback()
                return {'status': 200, 'headers': {'location':
                    'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=synthetic-revocation'}, 'body': {}}
            if method == 'PUT' and query.get('upload_id') == ['synthetic-revocation']:
                content_range = kwargs['headers']['Content-Range']
                if content_range.startswith('bytes */'):
                    assert kwargs['data'] == b''
                    return {'status': 308, 'headers': {'range': f'bytes=0-{self.offset - 1}'} if self.offset else {}, 'body': {}}
                self.offset += len(kwargs['data'])
                assert self.offset == 6, 'This fixture transfers only six synthetic bytes.'
                return {'status': 200, 'headers': {}, 'body': {'id': VIDEO}}
        raise AssertionError(('Unexpected synthetic provider request; network disabled', method, url))

    def upload_counts(self):
        calls = [(method, headers) for method, path, headers in self.calls if path == '/upload/youtube/v3/videos']
        return (sum(method == 'POST' for method, _ in calls),
                sum(method == 'PUT' and headers['Content-Range'].startswith('bytes */') for method, headers in calls),
                sum(method == 'PUT' and not headers['Content-Range'].startswith('bytes */') for method, headers in calls))


def authorize():
    started = service.oauth.start(WORKSPACE, TOKEN, 'youtube', 'publish',
                                  {'connectionId': CONNECTION} if CONNECTION else {})
    state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
    result = service.oauth.complete(WORKSPACE, TOKEN, 'youtube', state, 'synthetic-code')
    assert result['connected'] and result['providerAccountId'] == CHANNEL
    if CONNECTION:
        assert result['connectionId'] == CONNECTION
    return result['connectionId']


def credential():
    with connection() as db:
        return db.execute('SELECT authorization_generation::text,revoked_at IS NULL,access_ciphertext '
                          'FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',
                          (WORKSPACE, CONNECTION)).fetchone()


def counts():
    with connection() as db:
        rows = db.execute('SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s',
                          (WORKSPACE, CONNECTION)).fetchall()
        retained = 0
        for (state,) in rows:
            if state.get('youtubeProviderDataRemoved'):
                assert set(state) <= {'version', 'stage', 'youtubeProviderDataRemoved', 'dataRemovalReason', 'removedAt', 'manifestDigest'}
                assert state['version'] == 2 and state['stage'] == 'held'
                assert state['youtubeProviderDataRemoved'] is True
                assert state['dataRemovalReason'] in ('youtube_disconnected_data_removed', 'youtube_expired_data_removed')
                assert isinstance(state['removedAt'], (int, float))
            else:
                retained += 1
        cached = db.execute('SELECT count(*) FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s',
                            (WORKSPACE, CONNECTION)).fetchone()[0]
        return retained, cached


def clear_content():
    with connection() as db:
        for table in ('pr_youtube_uploads', 'pr_youtube_cache'):
            db.execute(f'DELETE FROM public.{table} WHERE workspace_id=%s AND connection_id=%s', (WORKSPACE, CONNECTION))


def disconnect():
    result = service.oauth.disconnect(WORKSPACE, TOKEN, CONNECTION)
    assert result['disconnected'] and not credential()[1]
    return result


def seed_cache(label):
    service.youtube._cache(WORKSPACE, CONNECTION, label, {'synthetic': label},
                           authorization_generation=credential()[0])


def expect_fence(call, *, changed=False):
    try:
        call()
    except AlphaError as error:
        assert getattr(error, 'youtube_authorization_fence', False), error
        assert error.youtube_authorization_changed is changed
    else:
        raise AssertionError('A stale or revoked authorization was accepted.')


def wait_for_lock(pids, blocker):
    """Observe an actual PostgreSQL waiter, not a timing-only race assertion."""
    deadline, seen = time.monotonic() + 5, []
    with connection() as monitor:
        monitor.autocommit = True
        while time.monotonic() < deadline:
            try:
                while True:
                    seen.append(pids.get_nowait())
            except Empty:
                pass
            if seen and monitor.execute('SELECT EXISTS(SELECT 1 FROM pg_stat_activity '
                                        "WHERE pid=ANY(%s) AND wait_event_type='Lock' "
                                        'AND %s=ANY(pg_blocking_pids(pid)))', (seen, blocker)).fetchone()[0]:
                return
            time.sleep(.01)
    raise AssertionError('The intended credential-lock conflict was not observed.')


def manifest(operation):
    return {'workspaceId': WORKSPACE, 'channelId': CONNECTION, 'providerAccountId': CHANNEL,
            'idempotencyKey': operation, 'platform': 'YouTube',
            'publishOptions': {'title': 'Synthetic revocation test', 'description': 'Synthetic only',
                              'privacyStatus': 'private', 'madeForKids': False, 'containsSyntheticMedia': False},
            'media': [{'id': 'a' * 32, 'mime': 'video/mp4', 'bytes': 6, 'width': 1080, 'height': 1920, 'duration': 1}],
            'payload': {'text': 'Synthetic only'}}


def upload(operation, reader=None):
    # Real service API binds the OAuth grant generation; only storage bytes
    # and provider transport are synthetic. The journal is actual PostgreSQL.
    engine = UploadEngine(journal, lambda item: service.youtube._api(WORKSPACE, CONNECTION, CHANNEL),
                          reader or (lambda _item, _offset, size: b'x' * size), chunk_size=256 * 1024)
    return engine.step(manifest(operation))


def assert_held(receipt, *, changed=False):
    assert receipt['state'] == 'held' and receipt['progress']['stage'] == 'held'
    assert receipt['progress']['errorCategory'] == ('authorization_changed' if changed else 'revoked_oauth')


# Refuse a real Supabase database even if somebody tunnels it to this port:
# the disposable harness has auth.users(id) only, unlike hosted Auth schemas.
with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns "
                      "WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    assert db.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('public.pr_encrypted_credentials') "
                      "AND attname='authorization_generation' AND NOT attisdropped)").fetchone()[0], 'Apply migration 098 in the harness first.'
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (USER,))

google = Google()
provider = YouTubeProvider(CLIENT, 'synthetic-secret', transport=google, creator_enabled=True)
assert provider.transport is google and not provider.real_transport
vault = CredentialVault(CredentialVault.generate_key())
service = HostedWorkspaceService(connection, verify, vault=vault, providers={'youtube': provider},
                                 public_base_url='https://rafii.example')
journal = service.youtube.journal
checks = []
try:
    WORKSPACE = service.bootstrap(TOKEN, 'studio')['workspaceId']
    register_synthetic_policy(connection, service.oauth.public_base_url)
    accept_synthetic_policy(service, WORKSPACE, TOKEN)
    CONNECTION = authorize()
    key = (WORKSPACE, CONNECTION, 'synthetic-journal-transaction')

    # Caller rollback must roll back the journal write in that SAME transaction.
    class RollbackProbe(Exception):
        pass

    with journal.lock(key):
        try:
            with connection() as db, db.cursor() as cursor:
                journal.save(key, {'stage': 'must-roll-back'}, cursor=cursor)
                assert cursor.execute('SELECT count(*) FROM public.pr_youtube_uploads WHERE workspace_id=%s',
                                      (WORKSPACE,)).fetchone()[0] == 1
                raise RollbackProbe()
        except RollbackProbe:
            pass
        assert counts() == (0, 0)
        with connection() as db, db.cursor() as cursor:
            cursor.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (WORKSPACE,))
            cursor.execute('SELECT 1 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s '
                           'FOR NO KEY UPDATE', key[:2])
            journal.save(key, {'stage': 'same-cursor-recovery'}, cursor=cursor)
    assert counts() == (1, 0)
    checks.append('same-cursor save commits atomically and caller rollback leaves no journal')

    # Real OAuth refresh during an operation must preserve its grant generation.
    clear_content()
    with journal.lock(key):
        before = service.oauth.token_for_worker(WORKSPACE, CONNECTION)
        with connection() as db:
            db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=now()-interval '1 second' "
                       'WHERE workspace_id=%s AND connection_id=%s', key[:2])
        refreshed = service.oauth.token_for_worker(WORKSPACE, CONNECTION)
        assert google.refreshes == 1 and before['accessToken'] != refreshed['accessToken']
        assert before['authorizationGeneration'] == refreshed['authorizationGeneration'] == credential()[0]
        journal.assert_current(key)
        journal.save(key, {'stage': 'same-operation-after-refresh'})
    assert counts() == (1, 0)
    checks.append('real OAuth refresh preserves active generation and in-flight operation')

    clear_content()
    with journal.lock(key):
        previous = credential()[0]
        assert authorize() == CONNECTION
        replacement = credential()[0]
        assert replacement != previous
        seed_cache('fresh-consent')
        expect_fence(lambda: journal.save(key, {'stage': 'stale-consent'}), changed=True)
        assert credential()[:2] == (replacement, True) and counts() == (0, 1)
    checks.append('real OAuth consent rotates generation; stale save preserves fresh grant and cache')

    # Save-first: pause AFTER the real fence acquired its locks but BEFORE the
    # child INSERT. Starting real disconnect here exposes the historical cycle:
    # save owns credential -> disconnect owns workspace -> FK waits workspace.
    # Workspace-first fencing completes both transactions without that cycle.
    clear_content()
    seed_cache('save-first')
    with journal.lock(key), ThreadPoolExecutor(max_workers=2) as pool:
        waiting, before_insert, release_insert = Queue(), Queue(), threading.Event()
        context = copy_context()

        class PausedInsertCursor:
            def __init__(self, cursor, backend_pid, table='pr_youtube_uploads'):
                self.cursor, self.backend_pid = cursor, backend_pid
                self.table = table

            def __enter__(self):
                self.cursor.__enter__()
                return self

            def __exit__(self, *args):
                return self.cursor.__exit__(*args)

            def execute(self, statement, *args, **kwargs):
                if isinstance(statement, str) and statement.lstrip().startswith(f'INSERT INTO public.{self.table}'):
                    before_insert.put(self.backend_pid)
                    assert release_insert.wait(6), 'The database insert latch was not released.'
                return self.cursor.execute(statement, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.cursor, name)

        def save_before_disconnect():
            with connection() as db, db.cursor() as cursor:
                journal.save(key, {'stage': 'save-before-disconnect'},
                             cursor=PausedInsertCursor(cursor, db.info.backend_pid))

        def disconnect_later():
            LOCAL.connections = waiting
            try:
                return disconnect()
            finally:
                del LOCAL.connections

        writing = pool.submit(context.run, save_before_disconnect)
        try:
            writer_pid = before_insert.get(timeout=5)
            pending = pool.submit(disconnect_later)
            wait_for_lock(waiting, writer_pid)
        finally:
            release_insert.set()
        writing.result(timeout=5)
        pending.result(timeout=5)
    assert counts() == (0, 0)
    checks.append('save-first real OAuth disconnect and child FK insertion complete without lock-order deadlock')

    # Disconnect-first: pause the actual OAuth transaction after its purge and
    # before commit. A copied genuine lock context waits and then rejects the
    # committed revoked row. This exercises workspace AND credential ordering.
    authorize()
    try:
        with journal.lock(key):
            raise AssertionError('A new consent must not replay a privacy-erased upload operation.')
    except AlphaError as error:
        assert error.code == 'youtube_data_removed'
    checks.append('content-free disconnect tombstone rejects replay even under a new consent generation')
    clear_content()  # Start the next independent SQL race with an empty synthetic fixture.
    with journal.lock(key), ThreadPoolExecutor(max_workers=2) as pool:
        paused, release, waiting = threading.Event(), threading.Event(), Queue()
        blocked_by = Queue()

        def pause_disconnect(db):
            row = db.execute('SELECT revoked_at IS NOT NULL FROM public.pr_encrypted_credentials '
                             'WHERE workspace_id=%s AND connection_id=%s', key[:2]).fetchone()
            if row and row[0]:
                LOCAL.before_commit = None
                blocked_by.put(db.info.backend_pid)
                paused.set()
                assert release.wait(6), 'The disconnect commit latch was not released.'

        def paused_disconnect():
            LOCAL.before_commit = pause_disconnect
            try:
                return disconnect()
            finally:
                del LOCAL.before_commit

        context = copy_context()

        def stale_save():
            LOCAL.connections = waiting
            try:
                return context.run(journal.save, key, {'stage': 'save-after-disconnect'})
            finally:
                del LOCAL.connections

        pending_disconnect = pool.submit(paused_disconnect)
        try:
            assert paused.wait(5), 'Real OAuth disconnect did not reach its commit latch.'
            pending_save = pool.submit(stale_save)
            wait_for_lock(waiting, blocked_by.get(timeout=1))
        finally:
            release.set()
        pending_disconnect.result(timeout=5)
        expect_fence(lambda: pending_save.result(timeout=5))
    assert counts() == (0, 0)
    checks.append('disconnect-first real transaction waits then rejects stale save without resurrection')

    # The first identity claim has no cache/FK row yet. Its workspace lock must
    # precede credential selection and cache insertion, just like journal saves.
    # The actual claim runs unchanged through a cursor latch before its INSERT.
    authorize()
    assert counts() == (0, 0)
    with connection() as db:
        excluded = tuple(db.execute("SELECT workspace_id::text,connection_id FROM public.pr_encrypted_credentials "
                                    "WHERE provider='youtube' AND NOT (workspace_id=%s AND connection_id=%s)",
                                    key[:2]).fetchall())
    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting, before_insert, release_insert = Queue(), Queue(), threading.Event()

        class IdentityClaimConnection:
            def __init__(self, db):
                self.db = db

            def cursor(self, *args, **kwargs):
                return PausedInsertCursor(self.db.cursor(*args, **kwargs), self.db.info.backend_pid,
                                          table='pr_youtube_cache')

            def __getattr__(self, name):
                return getattr(self.db, name)

        def claim_first_identity():
            LOCAL.wrap_connection = IdentityClaimConnection
            try:
                return service.youtube.claim_identity(excluded=excluded)
            finally:
                del LOCAL.wrap_connection

        before_provider = len(google.calls)
        claiming = pool.submit(claim_first_identity)
        try:
            claim_pid = before_insert.get(timeout=5)
            assert counts() == (0, 0), 'The first claim has not inserted its lease yet.'
            # A NOWAIT row-lock probe proves the claim owns the workspace lock
            # before its first cache INSERT; credential-only ordering fails here.
            try:
                with connection() as db:
                    db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE NOWAIT', (WORKSPACE,))
            except psycopg.errors.LockNotAvailable:
                pass
            else:
                raise AssertionError('Identity claim did not acquire its workspace lock before cache insertion.')
            pending = pool.submit(disconnect_later)
            wait_for_lock(waiting, claim_pid)
            assert len(google.calls) == before_provider, 'Claim-only and blocked disconnect cannot dispatch provider I/O.'
        finally:
            release_insert.set()
        assert claiming.result(timeout=5) == key[:2]
        pending.result(timeout=5)
    assert counts() == (0, 0) and not credential()[1]
    checks.append('first identity claim and real OAuth disconnect complete without deadlock or retained cache lease')

    # Late resumable-session response cannot resurrect the journal or send I/O.
    authorize()
    seed_cache('initialization')
    before = google.upload_counts()
    google.on_initialize = disconnect
    assert_held(upload('disconnect-initialization'))
    assert tuple(a - b for a, b in zip(google.upload_counts(), before)) == (1, 0, 0)
    assert counts() == (0, 0)
    checks.append('disconnect during initialization prevents journal resurrection and further requests')

    # Disconnect during private-byte read must fence the very next chunk PUT.
    authorize()
    seed_cache('private-media-read')
    before = google.upload_counts()

    def disconnected_reader(_item, _offset, size):
        disconnect()
        return b'x' * size

    held = upload('disconnect-media-read', disconnected_reader)
    assert_held(held)
    assert tuple(a - b for a, b in zip(google.upload_counts(), before)) == (1, 1, 0)
    assert counts() == (0, 0)
    checks.append('disconnect after media read fences next chunk and leaves authorized storage purged')

    # A provider response arriving after disconnect cannot repopulate cache.
    authorize()
    api = service.youtube._api(WORKSPACE, CONNECTION, CHANNEL)
    google.on_channels = disconnect
    expect_fence(lambda: service.youtube.identity(WORKSPACE, CONNECTION, api))
    assert counts() == (0, 0)
    checks.append('provider readback after disconnect cannot repopulate authorized cache')

    # Old responses must not mark a new consent revoked or purge its fresh data.
    authorize()
    api = service.youtube._api(WORKSPACE, CONNECTION, CHANNEL)
    old_generation = credential()[0]

    def reconnect():
        disconnect()
        authorize()
        seed_cache('new-grant-survives')

    google.on_channels = reconnect
    expect_fence(lambda: service.youtube.identity(WORKSPACE, CONNECTION, api), changed=True)
    assert credential()[1] and credential()[0] != old_generation and counts() == (0, 1)
    assert service.oauth.token_for_worker(WORKSPACE, CONNECTION)['authorizationGeneration'] == credential()[0]
    checks.append('stale readback after reconnect rejects old generation and preserves fresh authorization')

    clear_content()
    before = google.upload_counts()
    old_generation = credential()[0]

    def reconnected_reader(_item, _offset, size):
        reconnect()
        return b'x' * size

    assert_held(upload('reconnect-media-read', reconnected_reader), changed=True)
    assert tuple(a - b for a, b in zip(google.upload_counts(), before)) == (1, 1, 0)
    assert credential()[1] and credential()[0] != old_generation and counts() == (0, 1)
    checks.append('reconnect during media read blocks old chunk and retains fresh grant/cache')

    clear_content()
    generation = credential()[0]
    before = google.upload_counts()

    def refreshed_reader(_item, _offset, size):
        with connection() as db:
            db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=now()-interval '1 second' "
                       'WHERE workspace_id=%s AND connection_id=%s', key[:2])
        assert service.oauth.token_for_worker(WORKSPACE, CONNECTION)['authorizationGeneration'] == generation
        return b'x' * size

    completed = upload('refresh-media-read', refreshed_reader)
    assert completed['progress']['stage'] == 'uploaded_private' and completed['reference'] == VIDEO
    assert tuple(a - b for a, b in zip(google.upload_counts(), before)) == (1, 1, 1)
    assert credential()[:2] == (generation, True) and counts() == (1, 0)
    checks.append('normal OAuth refresh during media read permits same private upload operation')

    # Actual worker claim/dispatch, with unrelated workspaces row-locked so
    # SKIP LOCKED cannot let this regression mutate another fixture's work.
    state = service.repository.get(WORKSPACE, TOKEN)['state']
    held_job = {'id': uuid4().hex, 'state': 'held', 'nextAt': 0, 'leaseUntil': 0,
                'manifest': manifest('held-never-redispatched'), 'result': held}
    state['phase2']['jobs'] = [held_job]
    with connection() as db:
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                   (json.dumps(state), WORKSPACE))

    class NoDispatch:
        calls = 0

        def submit(self, _manifest):
            self.calls += 1
            raise AssertionError('Held operation reached provider dispatch.')

        reconcile = submit

    social = NoDispatch()
    before_provider = len(google.calls)
    with connection() as protected:
        protected.execute('SELECT id FROM public.pr_workspaces WHERE id<>%s FOR UPDATE', (WORKSPACE,)).fetchall()
        worker = PostgresWorker(connection, social=social)
        assert worker.tick_youtube(max_jobs=1, max_seconds=2)['processed'] == 0
    assert social.calls == 0 and len(google.calls) == before_provider
    assert service.repository.get(WORKSPACE, TOKEN)['state']['phase2']['jobs'] == [held_job]
    checks.append('held job is not claimed or redispatched by actual PostgreSQL worker')

    print(json.dumps({'execution': 'CLOUD_SYNTHETIC', 'externalProviderCalls': 0,
                      'oauthExchanges': google.exchanges, 'oauthRefreshes': google.refreshes,
                      'checks': checks}))
finally:
    # Remove only this unique workspace; CI teardown owns the synthetic user/trial.
    if WORKSPACE:
        with connection() as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (WORKSPACE,))
