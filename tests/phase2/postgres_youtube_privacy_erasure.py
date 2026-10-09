"""Cloud-only disposable PostgreSQL API-copy erasure; synthetic Google only.

Uses real SQL transactions, the privileged audit function, journal callback and
OAuth reconnect. No production/staging database or external provider is used.
"""
import copy
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube import agent, privacy_erasure as private
from postriff_phase2.youtube.journal import purge_authorized_data
from postriff_phase2.youtube.model import READ
from postriff_phase2.youtube.provider import YouTubeProvider
from youtube_policy_fixture import register_synthetic_policy, accept_synthetic_policy

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = time.time()
OLD = NOW - 31 * 86400
CHANNEL, VIDEO = 'UC' + 'e' * 22, 'abcdefghijk'
USERS = {token: str(uuid4()) for token in ('one', 'two')}
CLIENT = 'synthetic-erasure.apps.googleusercontent.com'
CHECKS = []


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=5000') as db:
        assert db.info.host == '127.0.0.1' and db.info.port == 55438 and db.info.dbname == 'postgres'
        yield db


def verify(token):
    return USERS[token]


verify.auth_time = lambda token, actor: NOW
verify.session_id = lambda token, actor: 'synthetic-erasure-' + token


class Google:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url))
        if method == 'POST' and url == YouTubeProvider.TOKEN:
            return {'status': 200, 'body': {'access_token': 'synthetic-access-' + str(len(self.calls)),
                'refresh_token': 'synthetic-refresh', 'expires_in': 3600, 'scope': READ}}
        if method == 'GET' and url.startswith(YouTubeProvider.TOKENINFO + '?'):
            return {'status': 200, 'body': {'aud': CLIENT, 'scope': READ}}
        if method == 'GET' and urlsplit(url).path == '/youtube/v3/channels':
            return {'status': 200, 'body': {'items': [{'id': CHANNEL, 'snippet': {'title': 'SYNTHETIC API title'},
                'statistics': {'viewCount': '1'}, 'status': {}, 'contentDetails': {}}]}}
        if method == 'GET' and urlsplit(url).path == '/youtube/v3/playlistItems':
            return {'status': 200, 'body': {'items': []}}
        if method == 'POST' and url == YouTubeProvider.REVOKE:
            return {'status': 200, 'body': {}}
        raise AssertionError(('Unexpected synthetic Google request; no network', method, url))


google = Google()
vault = CredentialVault(CredentialVault.generate_key())
provider = YouTubeProvider(CLIENT, 'synthetic-secret', transport=google)
provider.creator_enabled = True
service = HostedWorkspaceService(connection, verify, vault=vault, providers={'youtube': provider},
                                 public_base_url='https://rafii.example', clock=lambda: NOW)
with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    for user in USERS.values():
        db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
ONE = service.bootstrap('one', 'studio')['workspaceId']
TWO = service.bootstrap('two', 'studio')['workspaceId']
register_synthetic_policy(connection, 'https://rafii.example')
RECEIPTS = {workspace: accept_synthetic_policy(service, workspace, token)['receipt']
            for workspace, token in ((ONE, 'one'), (TWO, 'two'))}


def connect(workspace=ONE, token='one'):
    started = service.oauth.start(workspace, token, 'youtube', 'identity')
    state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
    return service.oauth.complete(workspace, token, 'youtube', state, 'synthetic-code')['connectionId']


CONNECTION = connect()
assert connect(TWO, 'two') == CONNECTION, 'Deterministic connection IDs remain tenant scoped.'


def snapshot(workspace=ONE):
    with connection() as db:
        return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,)).fetchone()[0]


def seed(workspace, *, created=NOW):
    actor = USERS['one' if workspace == ONE else 'two']
    state = snapshot(workspace)
    manifest = {'workspaceId': workspace, 'platform': 'YouTube', 'channelId': CONNECTION,
                'providerAccountId': CHANNEL, 'account': 'SYNTHETIC API title', 'actor': actor,
                'idempotencyKey': 'application-operation', 'capability': {'verifiedAt': created, 'scopes': [READ]},
                'payload': {'text': 'Keep the user-authored literal ' + CHANNEL},
                'media': [{'id': 'user-media', 'hash': 'original-user-hash'}],
                'publishOptions': {'title': 'My title', 'playlistIds': ['submitted-list-id']}}
    state['phase2']['reviews'] = [{'id': str(uuid4()), 'manifest': copy.deepcopy(manifest), 'digest': digest(manifest),
                                   'status': 'approved', 'createdAt': created}]
    state['phase2']['jobs'] = [{'id': str(uuid4()), 'manifest': manifest, 'approvalDigest': digest(manifest),
                               'approvedBy': actor, 'approvedAt': created, 'state': 'processing', 'leaseOwner': 'worker',
                               'leaseId': 'application-lease', 'leaseUntil': NOW + 45, 'providerReference': VIDEO}]
    draft = {'id': str(uuid4()), 'connectionId': CONNECTION, 'channelId': CHANNEL, 'assetId': 'user-media',
             'assetHash': 'original-user-hash', 'variantId': 'user-variant', 'createdAt': created, 'createdBy': actor,
             'status': 'queued', 'jobId': state['phase2']['jobs'][0]['id'], 'publishOptions': manifest['publishOptions']}
    draft['digest'] = agent.draft_digest(draft)
    policy = {'id': str(uuid4()), 'connectionId': CONNECTION, 'channelId': CHANNEL,
              'drafts': [{'id': draft['id'], 'digest': draft['digest']}], 'assetIds': ['user-media'],
              'createdAt': created, 'status': 'active', 'grantedAt': created, 'grantedBy': actor}
    policy['digest'] = agent.policy_digest(policy)
    state['youtubeAgent'] = {'drafts': [draft], 'policies': [policy]}
    state['userNotes'] = 'Keep independently submitted note ' + VIDEO
    action = str(uuid4())
    inputs = {'id': VIDEO, 'patch': {'snippet': {'title': 'Exactly submitted title ' + CHANNEL}}}
    action_manifest = {'channelId': CHANNEL, 'connectionId': CONNECTION, 'workspaceId': workspace,
                       'action': 'video.edit', 'inputs': inputs,
                       'plan': {'body': {'id': VIDEO, 'snippet': {'title': 'Merged API title', 'description': 'API description'}}}}
    with connection() as db:
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), workspace))
        db.execute("INSERT INTO public.pr_youtube_actions(id,workspace_id,connection_id,actor,operation_key,manifest,manifest_digest,status,receipt,secret_ciphertext,secret_key_id,created_at) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,'accepted',%s::jsonb,'synthetic-secret','synthetic-key',to_timestamp(%s))",
                   (action, workspace, CONNECTION, actor, action, json.dumps(action_manifest), digest(action_manifest), json.dumps({'result': {'id': VIDEO}}), created))
        db.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta,at) VALUES(%s,%s,'youtube.action_prepared',%s,%s::jsonb,to_timestamp(%s)),(%s,%s,'youtube.agent_draft_prepared',%s,%s::jsonb,to_timestamp(%s)),(%s,%s,'youtube.upload_resumed',%s,%s::jsonb,to_timestamp(%s))",
                   (workspace, actor, action, json.dumps({'channelId': CHANNEL, 'digest': digest(action_manifest)}), created,
                    workspace, actor, CONNECTION, json.dumps({'channelId': CHANNEL, 'draftId': draft['id']}), created,
                    workspace, actor, state['phase2']['jobs'][0]['id'], json.dumps({'videoId': VIDEO, 'operationKey': 'application-operation'}), created))
    return state, action, action_manifest


BEFORE, ACTION, ACTION_MANIFEST = seed(ONE)
FOREIGN, FOREIGN_ACTION, _ = seed(TWO)
with connection() as db:
    # Deliberately ambiguous historical provenance remains visible as a limit.
    db.execute("INSERT INTO public.pr_audit_events(workspace_id,kind,subject,meta) VALUES(%s,'youtube.action_result','orphan-application-id',%s::jsonb),(%s,'youtube.stream_secret_viewed','legacy-api-stream-id','{}')",
               (ONE, json.dumps({'resourceId': 'ambiguous-api-id'}), ONE))
    generation = db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()[0]
    db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
    db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL WHERE workspace_id=%s AND connection_id=%s", (ONE, CONNECTION))
    first = private.purge_connection(db.cursor(), ONE, CONNECTION, NOW)
    assert first == {'reviews': 1, 'jobs': 1, 'drafts': 1, 'policies': 1, 'actions': 1, 'audit': 3, 'bindings': 1, 'credentials': 1}, first
    db.rollback()
assert snapshot() == BEFORE, 'A rolled-back erasure must not persist partial state.'
with connection() as db:
    assert db.execute('SELECT provider_account_id,revoked_at IS NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone() == (CHANNEL, True)
CHECKS.append('atomic rollback preserves approval, credential, policy binding and audit source')

before_calls = len(google.calls)
with connection() as db:
    db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
    db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL WHERE workspace_id=%s AND connection_id=%s", (ONE, CONNECTION))
    purge_authorized_data(db.cursor(), ONE, CONNECTION)
assert len(google.calls) == before_calls
erased = snapshot()
for family, digest_key in (('reviews', 'digest'), ('jobs', 'approvalDigest')):
    saved, original = erased['phase2'][family][0], BEFORE['phase2'][family][0]
    assert saved['privacyErased'] and saved['manifest']['privacyErased']
    assert saved[digest_key] == original[digest_key] and digest(saved['manifest']) != saved[digest_key]
    assert 'providerAccountId' not in saved['manifest'] and 'account' not in saved['manifest']
    for key in ('payload', 'media', 'publishOptions', 'actor', 'channelId'):
        assert saved['manifest'][key] == original['manifest'][key]
for family in ('drafts', 'policies'):
    assert erased['youtubeAgent'][family][0]['channelId'] == ''
    assert erased['youtubeAgent'][family][0]['digest'] == BEFORE['youtubeAgent'][family][0]['digest']
assert erased['userNotes'] == BEFORE['userNotes'] and snapshot(TWO) == FOREIGN
with connection() as db:
    assert db.execute('SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()[0] == ''
    assert db.execute('SELECT count(*) FROM public.pr_youtube_policy_bindings WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()[0] == 0
    rows = db.execute("SELECT kind,subject,meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'youtube.%%'", (ONE,)).fetchall()
    assert sum(meta.get('privacyErased') is True for _, _, meta in rows) == 3
    assert any(subject == 'orphan-application-id' and meta['resourceId'] == 'ambiguous-api-id' for _, subject, meta in rows)
    assert any(subject == 'legacy-api-stream-id' for _, subject, _ in rows)
    assert db.execute('SELECT meta FROM public.pr_audit_events WHERE workspace_id=%s AND subject=%s', (TWO, FOREIGN_ACTION)).fetchone()[0]['channelId'] == CHANNEL
CHECKS.append('journal hook erases exact identities and audit keys while original digests/user content/foreign tenant survive')

assert connect() == CONNECTION
with connection() as db:
    renewed = db.execute('SELECT provider_account_id,authorization_generation::text,revoked_at IS NULL,youtube_identity_ingested_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()
    assert renewed[0] == CHANNEL and renewed[1] != generation and renewed[2:] == (True, True)
    assert db.execute('SELECT count(*) FROM public.pr_youtube_policy_bindings WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()[0] == 1
try:
    service.oauth.start(ONE, 'two', 'youtube', 'identity')
    raise AssertionError('Foreign actor adopted another workspace connection')
except AlphaError as error:
    assert error.status == 403
assert not service.commands.engine.current(snapshot(), erased['phase2']['jobs'][0]['manifest'])
for call in (lambda: service.youtube.worker_api(erased['phase2']['jobs'][0]['manifest']),
             lambda: agent.queue_draft(service.commands, erased, CONNECTION, erased['youtubeAgent']['drafts'][0]['id'], USERS['one'], NOW)):
    before_calls = len(google.calls)
    try:
        call()
        raise AssertionError('Erased approval became executable after reconnect')
    except AlphaError as error:
        assert error.code == 'youtube_privacy_erased'
    assert len(google.calls) == before_calls
CHECKS.append('real synthetic OAuth reconnect rotates generation/restores binding; foreign adoption and erased dispatch stay blocked')

# Keep a submitted-input record after action expiry; never revive its original
# operation key or use its now-erased plan to repeat a write.
_, EXPIRED_ACTION, EXPIRED_MANIFEST = seed(ONE, created=OLD)
before_calls = len(google.calls)
with connection() as db:
    private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
    value = db.execute('SELECT manifest,manifest_digest,status,user_inputs,receipt,secret_ciphertext,secret_key_id FROM public.pr_youtube_actions WHERE id=%s', (EXPIRED_ACTION,)).fetchone()
    assert value[0]['privacyErased'] and 'plan' not in value[0] and 'channelId' not in value[0]
    assert value[1] == digest(EXPIRED_MANIFEST) and value[2] == 'privacy_erased'
    assert value[3] == EXPIRED_MANIFEST['inputs'] and value[4:] == (None, None, None)
    inserted = db.execute("INSERT INTO public.pr_youtube_actions(workspace_id,connection_id,actor,operation_key,manifest,manifest_digest,status) VALUES(%s,%s,%s,%s,'{}','new','prepared') ON CONFLICT(workspace_id,connection_id,operation_key) DO NOTHING RETURNING id", (ONE, CONNECTION, USERS['one'], EXPIRED_ACTION)).fetchone()
    assert inserted is None
try:
    service.youtube.approve(ONE, 'one', CONNECTION, EXPIRED_ACTION, {'confirmed': True, 'digest': digest(EXPIRED_MANIFEST)})
    raise AssertionError('Expired creator action executed again')
except AlphaError as error:
    assert error.code == 'youtube_privacy_erased'
assert len(google.calls) == before_calls
CHECKS.append('30-day action tombstone preserves submitted inputs/original digest and fences duplicate operation without Google')

# The old creation clock remains authoritative for an unstamped legacy identity;
# neither recent token rotation nor updated_at extends it.
with connection() as db:
    db.execute("UPDATE public.pr_encrypted_credentials SET youtube_identity_ingested_at=NULL,created_at=to_timestamp(%s),rotated_at=now(),updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (OLD, ONE, CONNECTION))
before_calls = len(google.calls)
try:
    with connection() as db:
        private.purge_expired(db.cursor(), NOW)
    raise AssertionError('Missing provenance callback allowed active expiry')
except RuntimeError as error:
    assert 'callback' in str(error)
with connection() as db:
    assert db.execute('SELECT revoked_at IS NULL,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone() == (True, CHANNEL)
    outcome = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
    assert outcome['activeRevoked'] == 1
    assert db.execute('SELECT revoked_at IS NOT NULL,provider_account_id,access_ciphertext,refresh_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone() == (True, '', '', None)
assert len(google.calls) == before_calls
assert snapshot(TWO) == FOREIGN
CHECKS.append('legacy created_at active expiry requires callback, revokes locally and erases under locks without provider calls')

assert connect() == CONNECTION
with connection() as db:
    db.execute('UPDATE public.pr_encrypted_credentials SET youtube_identity_ingested_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s', (OLD, ONE, CONNECTION))


class RefreshBeforeLock:
    """Real PG scheduling seam: renew after selection, before workspace lock."""
    def __init__(self, cursor):
        self.cursor, self.renew = cursor, False

    def execute(self, sql, params=()):
        self.renew = sql.startswith('SELECT w.id::text FROM public.pr_workspaces')
        self.cursor.execute(sql, params)

    def fetchall(self):
        rows = self.cursor.fetchall()
        if self.renew:
            self.renew = False
            assert ONE in [row[0] for row in rows]
            assert connect() == CONNECTION
        return rows

    def __getattr__(self, key):
        return getattr(self.cursor, key)


with connection() as db:
    assert private.purge_expired(RefreshBeforeLock(db.cursor()), NOW, purge_authorized=purge_authorized_data)['activeRevoked'] == 0
    assert db.execute('SELECT revoked_at IS NULL,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone() == (True, CHANNEL)
CHECKS.append('OAuth renewal between candidate selection and lock survives old-consent expiry recheck')

with connection() as db:
    current_generation = db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION)).fetchone()[0]
plan = {'method': 'playlists.insert', 'body': {'snippet': {'title': 'Submitted title'}}, 'action': 'playlist.create'}
def late_result(*args, **kwargs):
    with connection() as db:
        db.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
        private.purge_connection(db.cursor(), ONE, CONNECTION, NOW)
    return {'id': 'PL-synthetic-late-result'}
api = SimpleNamespace(grant={'authorizationGeneration': current_generation}, provider=SimpleNamespace(real_transport=False),
                      plan=Mock(return_value=plan), execute=Mock(side_effect=late_result))
before_calls = len(google.calls)
with patch.object(service.youtube, '_api', return_value=api), patch.object(service.youtube, '_allow'), \
        patch.object(service.youtube, '_member', return_value=(USERS['one'], CHANNEL, snapshot())), \
        patch.object(service.youtube, 'never_published', return_value=False), \
        patch.object(service.youtube, 'verify_action', side_effect=AssertionError('No late readback')):
    prepared = service.youtube.preview(ONE, 'one', CONNECTION, {'action': 'playlist.create', 'inputs': {'title': 'Exactly submitted title'}})
    late = service.youtube.approve(ONE, 'one', CONNECTION, prepared['id'], {'confirmed': True, 'digest': prepared['digest']})
assert late['status'] == 'privacy_erased' and late['receipt'] is None and late['dataRemoved']
assert api.execute.call_count == 1 and len(google.calls) == before_calls
with connection() as db:
    assert db.execute('SELECT status,receipt,secret_ciphertext FROM public.pr_youtube_actions WHERE id=%s', (prepared['id'],)).fetchone() == ('privacy_erased', None, None)
CHECKS.append('actual Creator approve cannot persist an injected API result after concurrent exact action erasure')

with connection() as db:
    assert db.execute("SELECT has_function_privilege('authenticated','public.pr_youtube_erase_audit_fields(uuid,text,double precision)','EXECUTE'),has_function_privilege('anon','public.pr_youtube_erase_audit_fields(uuid,text,double precision)','EXECUTE')").fetchone() == (False, False)
    assert db.execute("SELECT has_function_privilege('service_role','public.pr_youtube_erase_audit_fields(uuid,text,double precision)','EXECUTE'),has_table_privilege('service_role','public.pr_audit_events','UPDATE'),has_table_privilege('service_role','public.pr_audit_events','DELETE')").fetchone() == (True, False, False)
    db.execute('SET LOCAL ROLE authenticated')
    try:
        with db.transaction():
            db.execute('SELECT public.pr_youtube_erase_audit_fields(%s,%s,NULL)', (ONE, CONNECTION))
        raise AssertionError('Browser role executed privileged audit erasure')
    except psycopg.errors.InsufficientPrivilege:
        pass
with connection() as db:
    db.execute('SET LOCAL ROLE service_role')
    assert db.execute('SELECT public.pr_youtube_erase_audit_fields(%s,%s,NULL)', (ONE, 'foreign-unrelated-connection')).fetchone()[0] == 0
CHECKS.append('service-only fixed-field audit function; no broad audit UPDATE/DELETE; wrong connection and ambiguous rows excluded')

# Apply the additive migration twice; no document activation or receipt changes.
with psycopg.connect(DSN, autocommit=True) as db:
    before_policy = db.execute('SELECT count(*) FROM public.pr_youtube_policy_revisions').fetchone()[0]
    for _ in range(2):
        db.execute((ROOT / 'migrations/postriff/100_youtube_api_privacy_erasure.sql').read_text(), prepare=False)
    assert db.execute('SELECT count(*) FROM public.pr_youtube_policy_revisions').fetchone()[0] == before_policy
CHECKS.append('100 migration idempotent with no legal policy seed')

with connection() as db:
    for _ in range(private.BATCH_SIZE + 3):
        identifier = str(uuid4())
        db.execute("INSERT INTO public.pr_youtube_actions(workspace_id,connection_id,actor,operation_key,manifest,manifest_digest,status,created_at) VALUES(%s,%s,%s,%s,%s::jsonb,'original-digest','prepared',to_timestamp(%s))",
                   (ONE, CONNECTION, USERS['one'], identifier, json.dumps({'action': 'playlist.create',
                    'inputs': {'title': 'Keep submitted title'}, 'plan': {'body': {'id': 'synthetic-api-id'}}}), OLD))
with connection() as db:
    first_actions = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
with connection() as db:
    second_actions = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
with connection() as db:
    third_actions = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
assert first_actions['actions'] == 100 and second_actions['actions'] == 3 and third_actions['actions'] == 0
CHECKS.append('100-action per-connection expiry advances through a larger batch')

bulk = []
with connection() as db:
    for _ in range(private.BATCH_SIZE + 3):
        workspace = str(uuid4())
        bulk.append(workspace)
        manifest = {'workspaceId': workspace, 'platform': 'YouTube', 'channelId': 'bulk-connection',
                    'account': 'API title', 'providerAccountId': CHANNEL}
        state = {'phase2': {'reviews': [{'id': str(uuid4()), 'createdAt': OLD, 'manifest': manifest, 'digest': digest(manifest)}]}}
        db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (workspace, json.dumps(state)))
with connection() as db:
    first = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
with connection() as db:
    second = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
with connection() as db:
    third = private.purge_expired(db.cursor(), NOW, purge_authorized=purge_authorized_data)
    assert first['workspaces'] == 100 and second['workspaces'] == 3 and third['workspaces'] == 0, (first, second, third)
    assert db.execute("SELECT count(*) FROM public.pr_workspaces WHERE id=ANY(%s::uuid[]) AND state#>>'{phase2,reviews,0,privacyErased}'='true'", (bulk,)).fetchone()[0] == len(bulk)
CHECKS.append('100-workspace bounded sweep advances beyond first batch without starvation')

print(json.dumps({'result': 'PASS', 'checks': CHECKS, 'execution': 'disposable-cloud-PG-synthetic-provider-only'}, indent=2))
