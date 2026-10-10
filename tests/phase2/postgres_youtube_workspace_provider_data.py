"""Cloud-only disposable PostgreSQL workspace-output privacy regression.

Runs real worker completion, OAuth disconnect, journal and retention code. All
credentials/content are synthetic; no Google, model or external DB is called.
"""
import copy
import hashlib
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
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube import privacy_erasure as identity_private, workspace_provider_data as private
from postriff_phase2.youtube.journal import UploadJournal, purge_authorized_data
from postriff_phase2.youtube.provider import YouTubeProvider
from postriff_phase2.youtube.uploads import UploadEngine

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = time.time()
USERS = {token: str(uuid4()) for token in ('one', 'two')}
CHANNEL, OTHER_CHANNEL, VIDEO = 'UC' + 'w' * 22, 'UC' + 'x' * 22, 'abcdefghijk'
CONNECTION, OTHER_CONNECTION, OPERATION = 'youtube-workspace-output', 'youtube-other-output', 'a' * 64
LOCAL = threading.local()
HOOKS, PROVIDER_CALLS = [], []


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert db.info.host == '127.0.0.1' and db.info.port == 55438 and db.info.dbname == 'postgres'
        tracked = getattr(LOCAL, 'pids', None)
        if tracked is not None:
            tracked.put(db.info.backend_pid)
        yield db
        callback = getattr(LOCAL, 'before_commit', None)
        if callback is not None:
            LOCAL.before_commit = None
            callback(db)


def verify(token):
    return USERS[token]


verify.auth_time = lambda token, actor: NOW
verify.session_id = lambda token, actor: 'synthetic-workspace-output-' + token


def no_provider(*args, **kwargs):
    PROVIDER_CALLS.append(args)
    raise AssertionError('External provider I/O is forbidden in this fixture.')


with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    for user in USERS.values():
        db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))

vault = CredentialVault(CredentialVault.generate_key())
provider = YouTubeProvider('synthetic-workspace.apps.googleusercontent.com', 'synthetic-secret', transport=no_provider)
service = HostedWorkspaceService(connection, verify, vault=vault, providers={'youtube': provider},
                                 public_base_url='https://rafii.example', clock=lambda: NOW)
ONE = service.bootstrap('one', 'studio')['workspaceId']
TWO = service.bootstrap('two', 'studio')['workspaceId']


def channel(connection_id=CONNECTION, identifier=CHANNEL, *, ingested=NOW):
    return {'id': connection_id, 'platform': 'YouTube', 'providerAccountId': identifier, 'account': 'Synthetic API channel ' + identifier,
            'configured': True, 'identityVerified': True, 'capabilityVerified': True, 'revoked': False,
            'scopes': [], 'verifiedAt': NOW, 'expiresAt': NOW + 3600, 'capabilityVersion': 1,
            'evidenceSource': 'live_provider', private.IDENTITY_INGESTED: ingested}


def make_job(workspace=ONE, connection_id=CONNECTION, identifier=CHANNEL, actor=None):
    actor = actor or USERS['one' if workspace == ONE else 'two']
    manifest = {'workspaceId': workspace, 'channelId': connection_id, 'providerAccountId': identifier,
                'account': 'Approved API channel ' + identifier, 'platform': 'YouTube', 'actor': actor,
                'idempotencyKey': OPERATION, 'expiresAt': NOW + 3600,
                'payload': {'text': 'Original customer draft quoting ' + VIDEO, 'language': 'en'},
                'media': [{'id': 'customer-original', 'hash': 'original-bytes-hash'}],
                'publishOptions': {'title': 'My original title', 'playlistIds': ['customer-selected-playlist']}}
    return {'id': 'job-' + connection_id, 'manifest': manifest, 'approvalDigest': digest(manifest),
            'approvedBy': actor, 'approvedAt': NOW, 'state': 'processing', 'events': [{'state': 'approved', 'message': 'Exact approval recorded'}],
            'attempts': [{'number': 1, 'idempotencyKey': OPERATION, 'startedAt': NOW}], 'checks': 1,
            'leaseOwner': 'privacy-worker', 'leaseId': uuid4().hex, 'leaseUntil': NOW + 45, 'nextAt': 0,
            'providerReference': VIDEO, 'url': 'https://www.youtube.com/watch?v=' + VIDEO,
            'progress': {'version': 2, 'stage': 'native_scheduled', 'bytesSent': 6, 'totalBytes': 6, 'videoId': VIDEO,
                         'steps': {'caption': {'source': 'YouTube Data API', 'resourceId': 'provider-caption-id',
                                              'result': {'id': 'provider-caption-id', 'snippet': {'channelId': identifier, 'videoId': VIDEO}},
                                              'plan': {'targetId': VIDEO}}}}}


def raw_journal(saved, ingested=NOW):
    return {'version': 2, 'manifestDigest': hashlib.sha256(json.dumps(saved['manifest'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'stage': 'native_scheduled', 'videoId': VIDEO, 'createdAt': ingested, private.INGESTED: ingested,
            'sessionCiphertext': 'synthetic-session-ciphertext', 'sessionKeyId': 'synthetic-session-key',
            'uploadReceipt': {'source': 'YouTube Data API', 'videoId': VIDEO, 'receivedAt': ingested},
            'steps': saved['progress']['steps'], 'options': saved['manifest']['publishOptions']}


def seed_credential(cur, workspace, connection_id, identifier):
    ciphertext, key_id = vault.encrypt('synthetic-not-a-google-token')
    return cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'youtube',%s,%s,%s,ARRAY[]::text[]) RETURNING authorization_generation::text",
                       (workspace, connection_id, identifier, ciphertext, key_id)).fetchone()[0]


generations = {}
with connection() as db:
    for workspace, connection_id, identifier in ((ONE, CONNECTION, CHANNEL), (ONE, OTHER_CONNECTION, OTHER_CHANNEL), (TWO, CONNECTION, CHANNEL)):
        generations[workspace, connection_id] = seed_credential(db, workspace, connection_id, identifier)
    for workspace in (ONE, TWO):
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,)).fetchone()[0]
        state['customerNotes'] = 'A user authored ID ' + VIDEO
        state['phase2']['assets'] = [{'id': 'customer-original', 'originalFilename': VIDEO + '.mp4', 'description': 'Keep my Library note ' + CHANNEL}]
        state['phase2']['channels'] = [channel()]
        state['phase2']['jobs'] = []
        if workspace == ONE:
            state['phase2']['channels'].append(channel(OTHER_CONNECTION, OTHER_CHANNEL))
        for connection_id, identifier in ((CONNECTION, CHANNEL), (OTHER_CONNECTION, OTHER_CHANNEL)) if workspace == ONE else ((CONNECTION, CHANNEL),):
            saved = make_job(workspace, connection_id, identifier)
            saved.update(state='verified', leaseOwner=None, leaseUntil=0)
            saved[private.KEY] = private.source(workspace, saved, generations[workspace, connection_id], NOW)
            state['phase2']['jobs'].append(saved)
            db.execute('INSERT INTO public.pr_youtube_uploads(workspace_id,connection_id,operation_key,state) VALUES(%s,%s,%s,%s::jsonb)',
                       (workspace, connection_id, OPERATION, json.dumps(raw_journal(saved))))
        state['phase2']['reviews'] = [{'id': 'approved-review', 'status': 'approved', 'manifest': copy.deepcopy(state['phase2']['jobs'][0]['manifest']),
                                       'digest': state['phase2']['jobs'][0]['approvalDigest']}]
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), workspace))


def snapshot(workspace=ONE):
    with connection() as db:
        return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,)).fetchone()[0]


def current_job(workspace=ONE, connection_id=CONNECTION):
    return next(saved for saved in snapshot(workspace)['phase2']['jobs'] if saved['manifest']['channelId'] == connection_id)


def journal_state(workspace=ONE, connection_id=CONNECTION):
    with connection() as db:
        return db.execute('SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s AND operation_key=%s',
                          (workspace, connection_id, OPERATION)).fetchone()[0]


def assert_removed(saved):
    assert saved[private.REMOVED] and saved['state'] == 'held' and saved['leaseOwner'] is None and saved['leaseUntil'] == 0
    assert 'providerReference' not in saved and 'url' not in saved and 'videoId' not in saved['progress']
    assert 'provider-caption-id' not in json.dumps(saved) and 'leaseId' not in saved and saved['nextAt'] == 0
    # Identity erasure replaces nextAction after runtime cleanup, while the
    # accepted-schedule notice must survive in the provider notice and timeline.
    assert saved['providerConfirmed'] == private.NOTICE and 'not canceled' in saved['providerConfirmed']
    assert any(event.get('execution') == 'server-data-cleanup' and event.get('state') == 'held'
               and event.get('message') == saved['providerConfirmed']
               and event.get('dataRemovalReason') == saved['youtubeDataRemovalReason']
               for event in saved['events'])
    if saved.get('privacyErased'):
        assert saved['nextAction'] == identity_private.NOTICE and saved['cancelRequested'] is True
        original = make_job(saved['manifest']['workspaceId'], saved['manifest']['channelId'], actor=saved['approvedBy'])
        assert saved['approvalDigest'] == original['approvalDigest'], 'Preserve the ORIGINAL digest; never re-sign redacted data.'
        assert saved['manifest']['privacyErased'] and 'account' not in saved['manifest'] and 'providerAccountId' not in saved['manifest']
        assert digest(saved['manifest']) != saved['approvalDigest'], 'The erased approval must remain unusable.'
        assert saved['approvedBy'] == original['approvedBy'] and saved['approvedAt'] == original['approvedAt']
        for field in ('actor', 'payload', 'media', 'publishOptions', 'idempotencyKey'):
            assert saved['manifest'][field] == original['manifest'][field]
    else:
        assert saved['nextAction'] == private.NOTICE
        assert digest(saved['manifest']) == saved['approvalDigest'], 'Runtime-only cleanup does not rewrite approvals.'


def assert_tombstone(value):
    assert set(value) == {'version', 'stage', private.REMOVED, 'dataRemovalReason', 'removedAt', 'manifestDigest'}
    assert value[private.REMOVED] and value['stage'] == 'held'
    assert VIDEO not in json.dumps(value) and CHANNEL not in json.dumps(value)


def reset_target(*, lease=True, ingested=NOW):
    """Explicit independent synthetic fixture setup, never production recovery."""
    with connection() as db:
        db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
        generation = db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=NULL,provider_account_id=%s,youtube_identity_ingested_at=to_timestamp(%s),authorization_generation=gen_random_uuid() WHERE workspace_id=%s AND connection_id=%s RETURNING authorization_generation::text',
                                (CHANNEL, NOW, ONE, CONNECTION)).fetchone()[0]
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (ONE,)).fetchone()[0]
        saved = make_job()
        saved[private.KEY] = private.source(ONE, saved, generation, ingested)
        if not lease:
            saved.update(leaseOwner=None, leaseUntil=0)
        state['phase2']['jobs'] = [item for item in state['phase2']['jobs'] if item['manifest']['channelId'] != CONNECTION] + [saved]
        state['phase2']['channels'] = [item for item in state['phase2']['channels'] if item['id'] != CONNECTION] + [channel()]
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), ONE))
        db.execute('UPDATE public.pr_youtube_uploads SET state=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND operation_key=%s',
                   (json.dumps(raw_journal(saved, ingested)), ONE, CONNECTION, OPERATION))
    return {'workspaceId': ONE, 'job': copy.deepcopy(saved), 'reconciliation': True, 'youtubeAuthorizationGeneration': generation}


def worker():
    value = PostgresWorker(connection, social=SimpleNamespace(youtube=object()), clock=lambda: NOW, worker_id='privacy-worker',
                           on_verified=lambda cur, workspace, saved: HOOKS.append(('verified', saved['id'])))
    value.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda _: None))
    return value


RESULT = {'state': 'verified', 'confirmed': 'Synthetic exact API readback', 'reference': VIDEO,
          'url': 'https://www.youtube.com/watch?v=' + VIDEO, 'verification': 'provider_lookup',
          'progress': {'version': 2, 'stage': 'published', 'bytesSent': 6, 'totalBytes': 6, 'videoId': VIDEO,
                       'steps': {'caption': {'source': 'YouTube Data API', 'result': {'id': 'provider-caption-id', 'snippet': {'channelId': CHANNEL}}}}}}


def disconnect():
    answer = service.oauth.disconnect(ONE, 'one', CONNECTION)
    assert answer['disconnected']
    return answer


def wait_for_lock(pids, blocker):
    deadline, seen = time.monotonic() + 5, []
    with connection() as monitor:
        monitor.autocommit = True
        while time.monotonic() < deadline:
            try:
                while True: seen.append(pids.get_nowait())
            except Empty:
                pass
            if seen and monitor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=ANY(%s) AND wait_event_type='Lock' AND %s=ANY(pg_blocking_pids(pid)))", (seen, blocker)).fetchone()[0]:
                return
            time.sleep(.01)
    raise AssertionError('The intended real PostgreSQL lock conflict was not observed.')


def pause_commit(entered, release):
    def paused(db):
        entered.put(db.info.backend_pid)
        assert release.wait(6), 'The transaction commit latch was not released.'
    return paused


checks = []
baseline, foreign, unrelated = snapshot(), snapshot(TWO), current_job(connection_id=OTHER_CONNECTION)
before_journal = journal_state()
try:
    with connection() as db, db.cursor() as cur:
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
        cur.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION))
        purge_authorized_data(cur, ONE, CONNECTION)
        state = cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (ONE,)).fetchone()[0]
        assert_removed(next(saved for saved in state['phase2']['jobs'] if saved['manifest']['channelId'] == CONNECTION))
        raise RuntimeError('Synthetic rollback after runtime cleanup.')
except RuntimeError as error:
    assert str(error) == 'Synthetic rollback after runtime cleanup.'
assert snapshot() == baseline and journal_state() == before_journal
checks.append('same-transaction rollback preserves canonical workspace and journal')

disconnect()
removed = snapshot()
assert_removed(current_job())
assert_tombstone(journal_state())
assert removed['customerNotes'] == baseline['customerNotes'] and removed['phase2']['assets'] == baseline['phase2']['assets']
review, prior_review = removed['phase2']['reviews'][0], baseline['phase2']['reviews'][0]
assert review['digest'] == prior_review['digest'] and review['privacyErased'] and review['status'] == 'privacy_erased'
assert 'account' not in review['manifest'] and 'providerAccountId' not in review['manifest']
for field in ('actor', 'payload', 'media', 'publishOptions', 'idempotencyKey'):
    assert review['manifest'][field] == prior_review['manifest'][field]
assert current_job(connection_id=OTHER_CONNECTION) == unrelated and snapshot(TWO) == foreign
profile = next(item for item in removed['phase2']['channels'] if item['id'] == CONNECTION)
assert 'providerAccountId' not in profile and CHANNEL not in profile['account']
checks.append('exact API copies erased; foreign tenant, other channel, user Library and ORIGINAL approval evidence preserved')

with patch('postriff_phase2.hosted_worker.record_published', side_effect=lambda *args: HOOKS.append(('learning', None))), \
     patch('postriff_phase2.product_events.publish_outcome', side_effect=lambda *args: HOOKS.append(('outcome', None))):
    # Actual claim includes the exact generation even for native read-only work.
    reset_target(lease=False)
    selected = worker().claim(youtube_only=True)
    assert selected['workspaceId'] == ONE and 'youtubeForward' not in selected
    with connection() as db:
        assert selected['youtubeAuthorizationGeneration'] == db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()[0]
    assert worker().complete(selected, RESULT)
    checks.append('real native read-only claim captures generation and current completion retains output')

    # Completion-first: real OAuth waits for the worker's workspace/credential
    # transaction. After that commit, disconnect removes every runtime copy.
    selected = reset_target()
    HOOKS.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        entered, release, waiting = Queue(), threading.Event(), Queue()
        def complete_first():
            LOCAL.before_commit = pause_commit(entered, release)
            return worker().complete(selected, RESULT)
        completed = pool.submit(complete_first)
        pid = entered.get(timeout=6)
        def disconnect_waiter():
            LOCAL.pids = waiting
            return disconnect()
        disconnected = pool.submit(disconnect_waiter)
        try:
            wait_for_lock(waiting, pid)
        finally:
            release.set()
        assert completed.result(timeout=8) and disconnected.result(timeout=8)['disconnected']
    assert_removed(current_job())
    assert_tombstone(journal_state())
    assert [name for name, _ in HOOKS] == ['verified', 'learning', 'outcome']
    checks.append('completion-first real OAuth lock ordering removes committed output')

    # Disconnect-first: an already returned synthetic API result waits behind
    # real OAuth, then cannot persist IDs/receipts or invoke any downstream hook.
    selected = reset_target()
    HOOKS.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        entered, release, waiting = Queue(), threading.Event(), Queue()
        def disconnect_first():
            LOCAL.before_commit = pause_commit(entered, release)
            return disconnect()
        disconnected = pool.submit(disconnect_first)
        pid = entered.get(timeout=6)
        def complete_waiter():
            LOCAL.pids = waiting
            return worker().complete(selected, RESULT)
        completed = pool.submit(complete_waiter)
        try:
            wait_for_lock(waiting, pid)
        finally:
            release.set()
        assert disconnected.result(timeout=8)['disconnected'] and completed.result(timeout=8) is False
    assert_removed(current_job())
    assert_tombstone(journal_state())
    assert not HOOKS
    checks.append('disconnect-first late returned result cannot restore data or stale hooks')

    selected = reset_target()
    with connection() as db:
        db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
        replacement = db.execute('UPDATE public.pr_encrypted_credentials SET authorization_generation=gen_random_uuid() WHERE workspace_id=%s AND connection_id=%s RETURNING authorization_generation::text', (ONE, CONNECTION)).fetchone()[0]
    HOOKS.clear()
    assert worker().complete(selected, RESULT) is False and not HOOKS
    assert_removed(current_job())
    with connection() as db:
        assert db.execute('SELECT authorization_generation::text,revoked_at IS NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone() == (replacement, True)
    checks.append('replacement generation refuses stale output and preserves new grant')

    ordinary = make_job()
    ordinary['id'] = 'ordinary-social-job'
    ordinary['manifest'].update(platform='LinkedIn', channelId='linkedin-fixture', providerAccountId='customer-linkedin', account='Customer LinkedIn')
    ordinary['approvalDigest'] = digest(ordinary['manifest'])
    for field in ('providerReference', 'url', 'progress'):
        ordinary.pop(field, None)
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,)).fetchone()[0]
        state['phase2']['jobs'].append(ordinary)
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), ONE))
    selected_ordinary = {'workspaceId': ONE, 'job': copy.deepcopy(ordinary), 'reconciliation': True}
    assert worker().complete(selected_ordinary, {'state': 'verified', 'confirmed': 'Synthetic ordinary receipt', 'reference': 'ordinary-post', 'verification': 'provider_lookup'})
    ordinary_saved = next(item for item in snapshot()['phase2']['jobs'] if item['id'] == ordinary['id'])
    assert ordinary_saved['providerReference'] == 'ordinary-post' and private.KEY not in ordinary_saved and private.REMOVED not in ordinary_saved
    checks.append('ordinary non-YouTube worker completion remains unaffected')

# Expiry fences an operation that already owns the advisory lock, and remains
# irreversible for that operation key even after a new authorization generation.
selected = reset_target()
journal = UploadJournal(connection, vault)
key = (ONE, CONNECTION, OPERATION)
with journal.lock(key):
    prior = journal.load(key)
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,)).fetchone()[0]
        saved = next(item for item in state['phase2']['jobs'] if item['manifest']['channelId'] == CONNECTION)
        saved[private.KEY] = private.source(ONE, saved, selected['youtubeAuthorizationGeneration'], NOW - 31 * 86400)
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), ONE))
        expired = {**prior, private.INGESTED: NOW - 31 * 86400}
        db.execute('UPDATE public.pr_youtube_uploads SET state=%s::jsonb WHERE workspace_id=%s AND connection_id=%s', (json.dumps(expired), ONE, CONNECTION))
    with connection() as db, db.cursor() as cur:
        private.purge_expired(cur, now=NOW)
    assert_removed(current_job())
    assert_tombstone(journal_state())
    for operation in (lambda: journal.save(key, prior), lambda: journal.assert_current(key)):
        try:
            operation()
        except AlphaError as error:
            assert error.code == 'youtube_data_removed'
        else:
            raise AssertionError('Expired runtime data was resurrected by an active operation.')
with connection() as db:
    db.execute('UPDATE public.pr_encrypted_credentials SET authorization_generation=gen_random_uuid() WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION))
engine = UploadEngine(journal, no_provider, no_provider)
try:
    engine.step(selected['job']['manifest'])
except AlphaError as error:
    assert error.code == 'youtube_data_removed'
else:
    raise AssertionError('New consent reinitialized an expired operation.')
checks.append('30-day expiry blocks active saves/API guards and new-consent replay without reupload')

# Genuine profile ingestion, rather than a fresh scope-only verifiedAt, controls
# metadata expiry. Separate privacy-erasure acceptance covers approval snapshots.
reset_target()
with connection() as db:
    state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,)).fetchone()[0]
    profile = next(item for item in state['phase2']['channels'] if item['id'] == CONNECTION)
    profile[private.IDENTITY_INGESTED], profile['verifiedAt'] = NOW - 31 * 86400, NOW
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), ONE))
with connection() as db, db.cursor() as cur:
    private.purge_expired(cur, now=NOW)
assert_removed(current_job())
assert_tombstone(journal_state())
assert 'providerAccountId' not in next(item for item in snapshot()['phase2']['channels'] if item['id'] == CONNECTION)
checks.append('fresh verifiedAt cannot prolong stale provider profile retention')

# Missing legacy metadata clocks only inherit the exact active credential's
# original creation time. No verifiedAt/updated_at/now fallback is allowed.
legacy_clock = int(NOW)
legacy_cases = [
    ('matching', 10, True, CHANNEL, CHANNEL, True),
    ('exact-age', 30, True, CHANNEL, CHANNEL, False),
    ('too-old', 31, True, CHANNEL, CHANNEL, False),
    ('revoked', 10, False, CHANNEL, CHANNEL, False),
    ('different-channel', 10, True, CHANNEL, OTHER_CHANNEL, False),
    ('foreign-credential', 10, True, CHANNEL, None, False),
    ('noncanonical-channel', 10, True, 'not-a-canonical-channel', 'not-a-canonical-channel', False),
]
legacy_workspaces = {}
with connection() as db:
    for name, age, active, profile_id, credential_id, preserved in legacy_cases:
        workspace = legacy_workspaces[name] = str(uuid4())
        profile = channel(identifier=profile_id)
        profile.pop(private.IDENTITY_INGESTED)
        state = {'phase2': {'channels': [profile], 'jobs': [], 'reviews': []}, 'customerNotes': 'Keep my original ' + VIDEO}
        db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (workspace, json.dumps(state)))
        if credential_id is not None:
            seed_credential(db, workspace, CONNECTION, credential_id)
            db.execute('UPDATE public.pr_encrypted_credentials SET created_at=to_timestamp(%s),updated_at=now(),revoked_at=' + ('NULL' if active else 'now()') + ' WHERE workspace_id=%s AND connection_id=%s',
                       (legacy_clock - age * 86400, workspace, CONNECTION))
    foreign_source = str(uuid4())
    db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (foreign_source,))
    seed_credential(db, foreign_source, CONNECTION, CHANNEL)
with connection() as db, db.cursor() as cur:
    private.purge_expired(cur, now=legacy_clock)
for name, age, active, profile_id, credential_id, preserved in legacy_cases:
    state = snapshot(legacy_workspaces[name])
    profile = state['phase2']['channels'][0]
    assert state['customerNotes'] == 'Keep my original ' + VIDEO
    if preserved:
        assert profile['providerAccountId'] == CHANNEL and not profile.get(private.REMOVED)
        assert profile[private.IDENTITY_INGESTED] == legacy_clock - age * 86400
    else:
        assert profile[private.REMOVED] and 'providerAccountId' not in profile
checks.append('legacy profile fallback requires exact active canonical credential and expires inclusively at 30 days')

# More than one batch: already scrubbed workspaces/tombstones must not keep
# being selected and starve later legacy runtime outputs.
extra = [str(uuid4()) for _ in range(105)]
with connection() as db:
    for workspace in extra:
        saved = make_job(workspace, actor=USERS['one'])
        saved['approvedAt'] = NOW - 31 * 86400
        state = {'phase2': {'channels': [channel()], 'reviews': [], 'jobs': [saved]}, 'customerNotes': 'Keep ' + VIDEO}
        db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (workspace, json.dumps(state)))
with connection() as db, db.cursor() as cur:
    private.purge_expired(cur, now=NOW)
with connection() as db:
    count = db.execute("SELECT count(*) FROM public.pr_workspaces WHERE id=ANY(%s::uuid[]) AND state#>>'{phase2,jobs,0,youtubeProviderDataRemoved}'='true'", (extra,)).fetchone()[0]
assert count == 100, ('The cron workspace batch must be bounded.', count)
with connection() as db, db.cursor() as cur:
    private.purge_expired(cur, now=NOW)
with connection() as db:
    count = db.execute("SELECT count(*) FROM public.pr_workspaces WHERE id=ANY(%s::uuid[]) AND state#>>'{phase2,jobs,0,youtubeProviderDataRemoved}'='true'", (extra,)).fetchone()[0]
assert count == 105, 'Scrubbed records must not starve the second batch.'
assert snapshot(TWO) == foreign and current_job(connection_id=OTHER_CONNECTION) == unrelated
assert not PROVIDER_CALLS, 'No external provider operation is permitted in this fixture.'
checks.append('105 legacy-output tenants advance across bounded 100-workspace batches')

print(json.dumps({'script': 'postgres_youtube_workspace_provider_data', 'status': 'passed',
                  'execution': 'disposable_postgres_synthetic_providers', 'providerRequests': len(PROVIDER_CALLS),
                  'cases': checks, 'residual': 'API identifiers in immutable approvals/audit and unattributable legacy freeform text remain unresolved.'}), flush=True)
