"""Disposable cloud DB: 1,000 synthetic tenants, no real AT accounts or network.

All 1,000 logical clients are submitted concurrently; the backend connection
pool is bounded at 24. This is not 1,000 PostgreSQL sockets or production proof.
"""
import base64
import copy
import hashlib
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Use the disposable JCB cloud PostgreSQL harness.')
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'src')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.store import Phase2Store

NOW, COUNT, POOL = 1_800_000_000, 1000, 24
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
WORKSPACES = ['00000000-0000-0000-2000-' + format(i, '012x') for i in range(COUNT)]
CONNECTION = 'same-connection-id-in-each-tenant'
scopes = list(BlueskyProvider.SCOPES['publish'])
mode = ['success']

def connection():
    return psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                          options='-c statement_timeout=10000 -c lock_timeout=5000')

def did(i):
    return 'did:plc:' + base64.b32encode(hashlib.sha256(str(i).encode()).digest()).decode().lower()[:24]

def transport(method, url, headers=None, **_):
    assert method == 'GET' and url.endswith('/xrpc/com.atproto.server.getSession'), url
    if mode[0] == 'outage':
        return {'status': 503, 'body': {}}
    if mode[0] == 'revoked':
        return {'status': 401, 'body': {'error': 'ExpiredToken'}}
    index = int(headers['Authorization'].split(':')[-1])
    return {'status': 200, 'body': {'did': did(index), 'handle': f'synthetic-{index}.bsky.social'}}

provider = BlueskyProvider(generate_jwk(kid='synthetic-client'), 'https://rafii.io', transport=transport,
    production_reviewed=True, clock=lambda: NOW,
    resolver=lambda *_args, **_kwargs: [(2, 1, 6, '', ('93.184.216.34', 443))])
vault = CredentialVault(CredentialVault.generate_key())
engine = Phase2Store.__new__(Phase2Store)
engine.clock, engine.hosted_entitlements = lambda: NOW, True
commands = SimpleNamespace(engine=engine)
repository = PostgresWorkspaceRepository(connection, lambda _: None, commands, clock=lambda: NOW)
oauth = OAuthService(repository, commands, vault, {'bluesky': provider}, 'https://rafii.io', clock=lambda: NOW)
proof_key = generate_jwk()

def grant(index):
    context = {'did': did(index), 'pds': 'https://pds.example.com', 'issuer': 'https://auth.example.com',
        'tokenEndpoint': 'https://auth.example.com/token', 'dpopJwk': proof_key, 'clientId': provider.client_id,
        'clientKeyId': provider.client_jwk['kid'], 'clientKeyThumbprint': provider._client_thumbprint()}
    result = provider._session({'access_token': f'synthetic-at:{index}', 'refresh_token': f'synthetic-rt:{index}',
        'token_type': 'DPoP', 'scope': ' '.join(scopes), 'sub': did(index), 'expires_in': 900}, context, None)
    access, key = vault.encrypt(result['accessToken'])
    return access, vault.encrypt(result['refreshToken'])[0], key

def state(workspace, index):
    return {'syntheticBlueskyLoad': True, 'phase2': {'reviews': [], 'jobs': [], 'channels': [{
        'id': CONNECTION, 'platform': 'Bluesky', 'providerAccountId': did(index), 'configured': True,
        'identityVerified': True, 'capabilityVerified': True, 'refreshSupported': True, 'revoked': False,
        'scopes': scopes, 'verifiedAt': NOW, 'expiresAt': NOW + 900, 'capabilityVersion': 2}]}}

started = time.monotonic()
with connection() as db:
    with db.cursor().copy('COPY public.pr_workspaces(id,state) FROM STDIN') as writer:
        for index, workspace in enumerate(WORKSPACES):
            writer.write_row((workspace, json.dumps(state(workspace, index))))
    with db.cursor().copy('''COPY public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
        access_ciphertext,refresh_ciphertext,key_id,scopes,refresh_supported,access_expires_at) FROM STDIN''') as writer:
        from datetime import datetime, timezone
        for index, workspace in enumerate(WORKSPACES):
            access, refresh, key = grant(index)
            writer.write_row((workspace, CONNECTION, 'bluesky', did(index), access, refresh, key,
                '{' + ','.join(scopes) + '}', True, datetime.fromtimestamp(NOW + 900, timezone.utc)))

def read(index):
    start = time.monotonic()
    result = oauth.token_for_worker(WORKSPACES[index], CONNECTION)
    assert result['providerAccountId'] == did(index)
    assert json.loads(result['accessToken'])['did'] == did(index)
    assert result['scopes'] == sorted(scopes) and result['refreshSupported']
    return (time.monotonic() - start) * 1000

with ThreadPoolExecutor(max_workers=POOL) as pool:
    pending = [pool.submit(read, index) for index in range(COUNT)]
    durations = [future.result() for future in pending]
assert time.monotonic() - started < 120
assert sorted(durations)[949] < 2000, max(durations)

# A refreshable short access lifetime is displayed as a renewable connection,
# not automatically erased; a transient live check cannot clear its scopes.
mode[0] = 'outage'
try:
    oauth.token_for_worker(WORKSPACES[0], CONNECTION)
    raise AssertionError('Outage accepted')
except AlphaError as error:
    assert error.code == 'bluesky_verification_unavailable', error.code
with connection() as db:
    row = db.execute('SELECT scopes,revoked_at IS NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (WORKSPACES[0], CONNECTION)).fetchone()
    assert set(row[0]) == set(scopes) and row[1]

# Conditional invalidation may never erase a newly consented replacement grant.
with connection() as db:
    old = db.execute('SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (WORKSPACES[0], CONNECTION)).fetchone()[0]
    replacement, _, _ = grant(0)
    db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s WHERE workspace_id=%s AND connection_id=%s', (replacement, WORKSPACES[0], CONNECTION))
assert oauth.mark_bluesky_reconnect(WORKSPACES[0], CONNECTION, old) is False
mode[0] = 'revoked'
try:
    oauth.token_for_worker(WORKSPACES[0], CONNECTION)
    raise AssertionError('Revoked grant accepted')
except AlphaError as error:
    assert error.code == 'reauthorization_required', error.code
with connection() as db:
    row = db.execute('SELECT access_ciphertext,refresh_ciphertext,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (WORKSPACES[0], CONNECTION)).fetchone()
    assert row == ('', None, True), row
    saved = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[0],)).fetchone()[0]
    assert saved['phase2']['channels'][0]['revoked']
    other = db.execute('SELECT revoked_at IS NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (WORKSPACES[1], CONNECTION)).fetchone()[0]
    assert other
mode[0] = 'success'

# The state consumption survives a failed external code exchange in a real
# transaction. Replaying the callback must not issue a second exchange.
with connection() as db:
    principal = str(db.execute('SELECT user_id FROM public.pr_memberships LIMIT 1').fetchone()[0])
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_manage_connections) VALUES(%s,%s,'owner','active',true)", (WORKSPACES[1], principal))
repository.verify_session = lambda _token: principal
context = {'did': did(1), 'issuer': 'https://auth.example.com', 'clientId': provider.client_id,
    'clientKeyId': provider.client_jwk['kid'], 'clientKeyThumbprint': provider._client_thumbprint()}
callback_state = 'synthetic-one-time-callback-state'
sealed, key = vault.encrypt(json.dumps(context))
with connection() as db:
    db.execute('''INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,
        scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,'bluesky','identity',%s,%s,%s,%s,%s,to_timestamp(%s))''',
        (WORKSPACES[1], principal, 'https://rafii.io/api/oauth/bluesky/callback', ['atproto'],
         hashlib.sha256(callback_state.encode()).hexdigest(), sealed, key, NOW + 600))
provider.exchange = Mock(side_effect=AlphaError('Injected transport interruption', 503))
for attempt in range(2):
    try:
        oauth.complete(WORKSPACES[1], 'synthetic-session', 'bluesky', callback_state, 'synthetic-code', iss=context['issuer'])
        raise AssertionError('Interrupted exchange accepted')
    except AlphaError as error:
        assert error.status == (503 if attempt == 0 else 404), error.status
assert provider.exchange.call_count == 1
with connection() as db:
    consumed = db.execute('SELECT consumed_at IS NOT NULL,outcome FROM public.pr_oauth_transactions WHERE state_hash=%s', (hashlib.sha256(callback_state.encode()).hexdigest(),)).fetchone()
    assert consumed == (True, 'exchange_started'), consumed

# Two accounts under the same tenant retain independent DID authority.
with connection() as db:
    access, refresh, key = grant(COUNT)
    db.execute('''INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
        access_ciphertext,refresh_ciphertext,key_id,scopes,refresh_supported,access_expires_at)
        VALUES(%s,'second-account','bluesky',%s,%s,%s,%s,%s,true,to_timestamp(%s))''',
        (WORKSPACES[1], did(COUNT), access, refresh, key, scopes, NOW + 900))
assert oauth.token_for_worker(WORKSPACES[1], 'second-account')['providerAccountId'] == did(COUNT)
try:
    oauth.token_for_worker(WORKSPACES[2], 'second-account')
    raise AssertionError('Foreign account accepted')
except AlphaError as error:
    assert error.status == 404

# Production queue selection against 1,000 tenants; restarts must not lose
# durable fairness or produce duplicate claims. Accepted posts only reconcile.
with connection() as db:
    for index, workspace in enumerate(WORKSPACES):
        saved = state(workspace, index)
        saved['phase2']['jobs'] = [{'id': f'synthetic-{index}-{number}', 'state': 'provider_accepted',
            'manifest': {'workspaceId': workspace, 'channelId': CONNECTION, 'platform': 'Bluesky', 'providerAccountId': did(index)},
            'attempts': [], 'events': [], 'nextAt': 0, 'leaseUntil': 0} for number in range(2)]
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(saved), workspace))
    db.execute('ANALYZE public.pr_workspaces')
claims, claim_times = [], []
for _ in range(64):
    worker = PostgresWorker(connection, social=SimpleNamespace(), clock=lambda: NOW)
    worker.commands = commands
    start = time.monotonic()
    claimed = worker.claim()
    assert claimed and claimed['reconciliation']
    assert claimed['job']['manifest']['workspaceId'] == claimed['workspaceId']
    claims.append(claimed['workspaceId'])
    claim_times.append((time.monotonic() - start) * 1000)
assert len(set(claims)) == 64
assert max(claim_times) < 5000
print(json.dumps({'execution': 'synthetic-cloud-postgres', 'realAccountConsent': False, 'realPublishing': False,
    'productionLoadAcceptance': False, 'logicalClients': COUNT, 'backendPool': POOL,
    'credentialReads': COUNT, 'readP50Ms': round(statistics.median(durations), 2),
    'readP95Ms': round(sorted(durations)[949], 2), 'distinctFairClaims': len(set(claims)),
    'claimMaxMs': round(max(claim_times), 2), 'seconds': round(time.monotonic() - started, 2),
    'checks': ['tenant-DID isolation', 'multi-account isolation', 'transient scope preservation',
               'concurrent reconsent wins', 'revoked credential erasure', 'callback state replay after interruption', 'durable fair queue claims']}))
