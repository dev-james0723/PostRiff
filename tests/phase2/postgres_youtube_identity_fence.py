"""Cloud-only real PostgreSQL identity fences with synthetic OAuth and picture I/O.

Run as an isolated disposable group after the complete migration chain (098-100).
No executable PostgreSQL fixture is imported; no Google/model request is sent.
"""
import copy
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from PIL import Image
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube.model import READ, UPLOAD
from postriff_phase2.youtube.provider import YouTubeProvider
from youtube_policy_fixture import accept_synthetic_policy, register_synthetic_policy

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
CLIENT = 'synthetic-identity.apps.googleusercontent.com'
CHANNEL, DRIFT = 'UC' + 'i' * 22, 'UC' + 'j' * 22
ACCESS, SCOPES = 'synthetic-identical-google-access-token', [READ, UPLOAD]
PICTURE_URL = 'https://yt3.ggpht.com/synthetic-identity.jpg'
LOCAL, WORKSPACES, CHECKS = threading.local(), [], []


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert db.info.host == '127.0.0.1' and db.info.port == 55438 and db.info.dbname == 'postgres'
        tracked = getattr(LOCAL, 'pids', None)
        if tracked is not None:
            tracked.put(db.info.backend_pid)
        yield db
        before_commit = getattr(LOCAL, 'before_commit', None)
        if before_commit is not None:
            LOCAL.before_commit = None
            before_commit(db)


def png(color):
    output = io.BytesIO()
    Image.new('RGB', (2, 2), color).save(output, format='PNG')
    return output.getvalue()


OLD_PICTURE, NEW_PICTURE = png('red'), png('blue')


class SyntheticGoogle:
    """Exact allowlist: real provider code, constant access token across new consents."""
    def __init__(self):
        self.calls, self.title, self.on_channels = [], 'Current synthetic creator', None

    def __call__(self, method, url, **kwargs):
        parsed = urlsplit(url)
        self.calls.append((method, parsed.netloc, parsed.path))
        if method == 'POST' and url == 'https://oauth2.googleapis.com/token':
            assert kwargs['form']['grant_type'] in ('authorization_code', 'refresh_token')
            return {'status': 200, 'body': {'access_token': ACCESS, 'refresh_token': 'synthetic-refresh',
                                           'expires_in': 3600, 'scope': ' '.join(SCOPES)}}
        if method == 'GET' and url.startswith('https://oauth2.googleapis.com/tokeninfo?'):
            return {'status': 200, 'body': {'aud': CLIENT, 'scope': ' '.join(SCOPES)}}
        if method == 'POST' and url == 'https://oauth2.googleapis.com/revoke':
            return {'status': 200, 'body': {}}
        if method == 'GET' and parsed.netloc == 'www.googleapis.com' and parsed.path == '/youtube/v3/channels':
            observed = {'id': CHANNEL, 'snippet': {'title': self.title}, 'status': {'longUploadsStatus': 'allowed'}}
            callback, self.on_channels = self.on_channels, None
            if callback is not None:
                replacement = callback()
                if replacement is not None:
                    observed['id'] = replacement
            return {'status': 200, 'body': {'items': [observed]}}
        raise AssertionError(('Unexpected provider request; no network transport exists.', method, url))


class Fixture:
    def __init__(self):
        self.user, self.token, self.google = str(uuid4()), 'synthetic-identity-session-' + uuid4().hex, SyntheticGoogle()
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))

        def verify(token):
            assert token == self.token
            return self.user

        verify.auth_time = lambda *_: time.time()
        verify.session_id = lambda *_: self.token
        self.vault = CredentialVault(CredentialVault.generate_key())
        self.provider = YouTubeProvider(CLIENT, 'synthetic-secret', transport=self.google, creator_enabled=True)
        assert not self.provider.real_transport and self.provider.transport is self.google
        self.service = HostedWorkspaceService(connection, verify, vault=self.vault,
            providers={'youtube': self.provider}, public_base_url='https://rafii.example')
        self.oauth = self.service.oauth
        self.workspace = self.service.bootstrap(self.token, 'studio')['workspaceId']
        WORKSPACES.append(self.workspace)
        register_synthetic_policy(connection, self.oauth.public_base_url)
        accept_synthetic_policy(self.service, self.workspace, self.token)
        self.connection = self.authorize()
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (self.workspace,)).fetchone()[0]
            state['customerNotes'] = 'Original user note mentioning ' + CHANNEL
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))

    def authorize(self):
        started = self.oauth.start(self.workspace, self.token, 'youtube', 'publish')
        state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
        result = self.oauth.complete(self.workspace, self.token, 'youtube', state, 'synthetic-code')
        assert result['connected'] and result['providerAccountId'] == CHANNEL
        return result['connectionId']

    def credential(self):
        with connection() as db:
            return db.execute("SELECT authorization_generation::text,revoked_at IS NULL,access_ciphertext,key_id,scopes,provider_account_id,youtube_identity_ingested_at,refresh_supported FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s",
                              (self.workspace, self.connection)).fetchone()

    def durable(self):
        with connection() as db:
            row = db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()
            caps = db.execute('SELECT capability,level,evidence,verified_at FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s ORDER BY capability',
                              (self.workspace, self.connection)).fetchall()
            pictures = db.execute('SELECT connection_id,digest FROM public.pr_channel_pictures WHERE workspace_id=%s ORDER BY connection_id', (self.workspace,)).fetchall()
        return copy.deepcopy((row, self.credential(), caps, pictures))

    def pictures(self):
        with connection() as db:
            return db.execute('SELECT digest FROM public.pr_channel_pictures WHERE workspace_id=%s AND connection_id=%s',
                              (self.workspace, self.connection)).fetchall()

    def disconnect(self):
        assert self.oauth.disconnect(self.workspace, self.token, self.connection)['disconnected']

    def picture(self, generation, data=OLD_PICTURE):
        self.oauth.picture_fetch = lambda url: (200, 'image/png', data)
        self.oauth._keep_picture(self.workspace, self.token, self.connection,
                                 {'pictureUrl': PICTURE_URL}, youtube_generation=generation)


def expect_changed(action):
    try:
        action()
    except AlphaError as error:
        assert error.code == 'youtube_connection_changed', error.code
    else:
        raise AssertionError('A stale identity/profile write was accepted.')


def wait_for_lock(pids, blocker):
    deadline, seen = time.monotonic() + 5, []
    with connection() as monitor:
        monitor.autocommit = True
        while time.monotonic() < deadline:
            try:
                while True:
                    seen.append(pids.get_nowait())
            except Empty:
                pass
            if seen and monitor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=ANY(%s) AND wait_event_type='Lock' AND %s=ANY(pg_blocking_pids(pid)))", (seen, blocker)).fetchone()[0]:
                return
            time.sleep(.01)
    raise AssertionError('The expected real PostgreSQL workspace lock conflict was not observed.')


with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    assert db.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('public.pr_encrypted_credentials') AND attname='youtube_identity_ingested_at' AND NOT attisdropped)").fetchone()[0], 'Apply migration 100 in the disposable harness.'


try:
    # The observed token stays identical while ACTUAL OAuth consent rotates its
    # generation and updates the canonical profile. Both manual and worker paths
    # must preserve that new grant across every old identity outcome.
    for manual in (True, False):
        for outcome in ('match', 'drift', 'error'):
            fixture, expected = Fixture(), []
            old = fixture.credential()

            def replaced_during_identity():
                fixture.google.title = 'New consent must win'
                assert fixture.authorize() == fixture.connection
                fresh = fixture.credential()
                assert fresh[0] != old[0] and fresh[1]
                assert fixture.vault.decrypt(fresh[2], fresh[3]) == fixture.vault.decrypt(old[2], old[3]), 'Exercise identical custody plaintext as well as identical Google bearer.'
                assert fixture.provider.bearer(fixture.vault.decrypt(fresh[2], fresh[3])) == ACCESS
                assert fixture.provider.bearer(fixture.vault.decrypt(old[2], old[3])) == ACCESS
                expected.append(fixture.durable())
                if outcome == 'error':
                    raise AlphaError('Synthetic identity failure.', 503, code='synthetic_identity_error')
                return DRIFT if outcome == 'drift' else CHANNEL

            fixture.google.on_channels = replaced_during_identity
            if manual:
                expect_changed(lambda: fixture.oauth.verify(fixture.workspace, fixture.token, fixture.connection))
            elif outcome == 'error':
                assert not fixture.oauth.reverify_for_worker(fixture.workspace, fixture.connection)['ready']
            else:
                expect_changed(lambda: fixture.oauth.reverify_for_worker(fixture.workspace, fixture.connection))
            assert len(expected) == 1 and fixture.durable() == expected[0]
            assert not fixture.oauth.mark_youtube_revoked(fixture.workspace, fixture.connection,
                expected_access_token=fixture.vault.decrypt(old[2], old[3]), expected_generation=old[0])
            assert fixture.durable() == expected[0]
            CHECKS.append(('manual' if manual else 'worker') + ' old ' + outcome + ' preserves actual same-token replacement consent')

    # Complete's token transaction has committed, but its separate profile save
    # has not started. The after-callback must reject and roll back the UPDATE,
    # even though get() deliberately observes the new canonical revision.
    for replacement in (False, True):
        fixture = Fixture()
        entered, release = threading.Event(), threading.Event()
        original_get = fixture.oauth.repository.get

        def pause_before_get(*args, **kwargs):
            if getattr(LOCAL, 'pause_profile', False):
                LOCAL.pause_profile = False
                entered.set()
                assert release.wait(6), 'Late profile-save latch was not released.'
            return original_get(*args, **kwargs)

        def late_complete():
            LOCAL.pause_profile = True
            return fixture.authorize()

        with patch.object(fixture.oauth.repository, 'get', side_effect=pause_before_get), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(late_complete)
            try:
                assert entered.wait(6), 'Consent did not reach the post-custody profile save.'
                if replacement:
                    fixture.google.title = 'Replacement profile survives rollback'
                    fixture.authorize()
                else:
                    fixture.disconnect()
                expected = fixture.durable()
            finally:
                release.set()
            expect_changed(lambda: pending.result(timeout=8))
        assert fixture.durable() == expected, 'Rejected profile save must roll back state, revision and side effects.'
        CHECKS.append('late consent profile save rolls back after ' + ('replacement consent' if replacement else 'real OAuth disconnect'))

    # Picture fetch starts without a DB lock. Real disconnect/new consent wins
    # while the synthetic fetch is paused; the late bytes must never be inserted.
    for replacement in (False, True):
        fixture = Fixture()
        observed = fixture.credential()[0]
        fixture.picture(observed)
        assert fixture.pictures()
        entered, release = threading.Event(), threading.Event()

        def blocked_fetch(url):
            assert url == PICTURE_URL
            entered.set()
            assert release.wait(6), 'Picture-fetch latch was not released.'
            return 200, 'image/png', OLD_PICTURE

        fixture.oauth.picture_fetch = blocked_fetch
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(fixture.oauth._keep_picture, fixture.workspace, fixture.token, fixture.connection,
                                  {'pictureUrl': PICTURE_URL}, youtube_generation=observed)
            try:
                assert entered.wait(6)
                fixture.disconnect()
                if replacement:
                    fixture.authorize()
                    fixture.picture(fixture.credential()[0], NEW_PICTURE)
                expected = fixture.durable()
            finally:
                release.set()
            pending.result(timeout=8)
        assert fixture.durable() == expected
        assert bool(fixture.pictures()) == replacement
        CHECKS.append('late picture bytes preserve ' + ('new consent picture' if replacement else 'disconnect deletion'))

    # Reverse ordering: a picture store holds the real workspace/credential
    # fence; disconnect is observed waiting, then removes the committed picture.
    fixture = Fixture()
    entered, release, waiting = Queue(), threading.Event(), Queue()

    def disconnect_waiter():
        LOCAL.pids = waiting
        return fixture.disconnect()

    # Read generation before arming the commit latch: it belongs to the picture
    # transaction, not a preceding SELECT used only by this fixture.
    generation = fixture.credential()[0]

    def store_current_first():
        def paused_commit(db):
            entered.put(db.info.backend_pid)
            assert release.wait(6), 'Picture-commit latch was not released.'
        LOCAL.before_commit = paused_commit
        return fixture.picture(generation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        stored = pool.submit(store_current_first)
        blocker = entered.get(timeout=6)
        disconnected = pool.submit(disconnect_waiter)
        try:
            wait_for_lock(waiting, blocker)
        finally:
            release.set()
        stored.result(timeout=8)
        disconnected.result(timeout=8)
    assert not fixture.pictures()
    CHECKS.append('picture-first workspace-to-credential transaction completes; waiting real disconnect removes it')

    fixture = Fixture()
    original = fixture.credential()[0]
    fixture.google.title = 'Fresh verified identity'
    assert fixture.oauth.verify(fixture.workspace, fixture.token, fixture.connection)['state'] == 'read_verified'
    assert fixture.oauth.reverify_for_worker(fixture.workspace, fixture.connection)['state'] == 'read_verified'
    assert fixture.credential()[0] == original and fixture.credential()[6] is not None
    fixture.picture(original)
    assert fixture.pictures()
    CHECKS.append('current consent complete, manual/worker identity refresh and picture store succeed')

    # Shared non-YouTube behavior has no authorization-generation requirement.
    ordinary_connection, ordinary_account = 'synthetic-linkedin', 'synthetic-linkedin-account'
    ordinary_provider = SimpleNamespace(id='linkedin', execution_enabled=True,
        identity=lambda _access: {'providerAccountId': ordinary_account, 'handle': 'Ordinary current account'},
        inspect_scopes=lambda *_: ['synthetic.linkedin.read'])
    fixture.oauth.providers['linkedin'] = ordinary_provider
    with connection() as db:
        db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (fixture.workspace,))
        ciphertext, key_id = fixture.vault.encrypt('synthetic-linkedin-access')
        db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes,access_expires_at) VALUES(%s,%s,'linkedin',%s,%s,%s,%s,now()+interval '1 hour')",
                   (fixture.workspace, ordinary_connection, ordinary_account, ciphertext, key_id, ['synthetic.linkedin.read']))
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (fixture.workspace,)).fetchone()[0]
        state['phase2']['channels'].append({'id': ordinary_connection, 'platform': 'LinkedIn',
            'providerAccountId': ordinary_account, 'account': 'Ordinary account', 'scopes': ['synthetic.linkedin.read'],
            'configured': True, 'identityVerified': True, 'capabilityVerified': True, 'verifiedAt': time.time(),
            'expiresAt': time.time() + 3600, 'revoked': False, 'capabilityVersion': 1})
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), fixture.workspace))
    assert fixture.oauth.verify(fixture.workspace, fixture.token, ordinary_connection)['state'] == 'read_verified'
    fixture.oauth._keep_picture(fixture.workspace, fixture.token, ordinary_connection, {'pictureUrl': PICTURE_URL})
    with connection() as db:
        assert db.execute('SELECT count(*) FROM public.pr_channel_pictures WHERE workspace_id=%s AND connection_id=%s',
                          (fixture.workspace, ordinary_connection)).fetchone()[0] == 1
    CHECKS.append('ordinary non-YouTube verification and picture storage remain unchanged')

    current = fixture.credential()
    assert fixture.oauth.mark_youtube_revoked(fixture.workspace, fixture.connection,
        expected_access_token=fixture.vault.decrypt(current[2], current[3]), expected_generation=current[0])
    assert not fixture.credential()[1] and not fixture.pictures()
    with connection() as db:
        assert db.execute('SELECT count(*) FROM public.pr_channel_pictures WHERE workspace_id=%s AND connection_id=%s',
                          (fixture.workspace, ordinary_connection)).fetchone()[0] == 1
    CHECKS.append('current generation revocation succeeds and preserves ordinary-provider pictures')

    print(json.dumps({'script': 'postgres_youtube_identity_fence', 'status': 'passed',
        'execution': 'disposable_postgres_synthetic_oauth_and_pictures', 'externalProviderCalls': 0,
        'checks': CHECKS}), flush=True)
finally:
    # Exactly this isolated group's synthetic workspaces; harness owns users.
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,))
