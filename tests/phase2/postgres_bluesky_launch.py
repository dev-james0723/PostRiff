"""Cloud-only Bluesky launch checks on a disposable PostgreSQL: refresh safety (B3) and synthetic load (D1).

Real production token custody (OAuthService.token_for_worker, row lock, rotation) and the real connect-start
throttle run against 1,000 synthetic tenants. The Bluesky token endpoint is a local fake: no egress, no real
account, and not production HTTP load acceptance.
"""
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Run through the disposable cloud PostgreSQL harness.')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_phase2.hosted import throttle
from postriff_phase2.oauth import BLUESKY_STARTS_PER_MINUTE, CredentialVault, OAuthService

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
COUNT, SQL_CONCURRENCY = 1000, 32
NOW = 1800000000
WORKSPACES = [str(uuid4()) for _ in range(COUNT)]
USERS = [str(uuid4()) for _ in range(COUNT)]
CONNECTION = 'synthetic-bluesky-launch'
SCOPES = ['atproto', BlueskyProvider.POST_SCOPE, BlueskyProvider.IMAGE_SCOPE]
vault = CredentialVault(CredentialVault.generate_key())
proof = generate_jwk()


def connection():
    return psycopg.connect(DSN, connect_timeout=5, options='-c statement_timeout=10000 -c lock_timeout=5000')


def did(index):
    return 'did:plc:' + format(index, '024d').translate(str.maketrans('0123456789', 'abcdefghij'))


def session(index, generation):
    common = {'v': 1, 'did': did(index), 'pds': 'https://pds.example.com', 'iss': 'https://auth.example.com',
              'tokenEndpoint': 'https://auth.example.com/oauth/token', 'revocationEndpoint': None, 'jwk': proof}
    return ({**common, 'at': f'synthetic-at:{index}:{generation}', 'rt': f'synthetic-rt:{index}:{generation}', 'scope': SCOPES, 'nonce': None},
            {**common, 'rt': f'synthetic-rt:{index}:{generation}', 'nonce': None})


class FakeTokenEndpoint:
    """Counts refreshes; `mode` decides the token endpoint's answer for a tenant."""
    def __init__(self):
        self.calls, self.lock, self.mode = {}, threading.Lock(), {}

    def __call__(self, refresh_token):
        stored = json.loads(refresh_token)
        index = int(stored['rt'].split(':')[1])
        with self.lock:
            self.calls[index] = self.calls.get(index, 0) + 1
            generation = self.calls[index]
        time.sleep(0.05)  # widen the race window between concurrent callers
        mode = self.mode.get(index, 'ok')
        if mode == 'revoked':
            raise AlphaError('Bluesky access expired; reconnect the account.', 409, code='reauthorization_required')
        if mode == 'outage':
            raise AlphaError('Bluesky did not renew access right now. Try again shortly.', 503, code='provider_unavailable')
        access, refresh = session(index, generation)
        return {'accessToken': json.dumps(access), 'refreshToken': json.dumps(refresh), 'expiresIn': 900, 'scopes': SCOPES}


provider = BlueskyProvider(generate_jwk(kid='synthetic-launch'), 'https://rafii.io', production_reviewed=True,
                           clock=lambda: NOW, resolver=lambda *_a, **_k: [(2, 1, 6, '', ('93.184.216.34', 443))])
endpoint = FakeTokenEndpoint()
provider.refresh = endpoint
provider.inspect_scopes = lambda access, account=None: sorted(SCOPES)
oauth = object.__new__(OAuthService)
oauth.repository = SimpleNamespace(connection_factory=connection)
oauth.vault, oauth.providers, oauth.clock = vault, {'bluesky': provider}, lambda: NOW


def stored(index):
    with connection() as db, db.cursor() as cur:
        cur.execute("SELECT refresh_supported,refresh_ciphertext,key_id,extract(epoch from access_expires_at)::float8,rotated_at IS NOT NULL "
                    "FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s", (WORKSPACES[index], CONNECTION))
        return cur.fetchone()


started = time.monotonic()
with connection() as db:
    with db.cursor().copy('COPY auth.users(id) FROM STDIN') as copy:
        for user in USERS: copy.write_row((user,))
    with db.cursor().copy('COPY public.pr_profiles(user_id) FROM STDIN') as copy:
        for user in USERS: copy.write_row((user,))
    with db.cursor().copy('COPY public.pr_workspaces(id,state) FROM STDIN') as copy:
        for index, workspace in enumerate(WORKSPACES):
            copy.write_row((workspace, json.dumps({'workspace': {'id': workspace}, 'phase2': {'channels': [
                {'id': CONNECTION, 'platform': 'Bluesky', 'providerAccountId': did(index)}], 'jobs': [], 'reviews': []}})))
    with db.cursor().copy('COPY public.pr_memberships(workspace_id,user_id,role,status) FROM STDIN') as copy:
        for workspace, user in zip(WORKSPACES, USERS): copy.write_row((workspace, user, 'owner', 'active'))
    with db.cursor().copy('COPY public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,'
                          'refresh_ciphertext,key_id,scopes,access_expires_at,refresh_supported) FROM STDIN') as copy:
        for index, workspace in enumerate(WORKSPACES):
            access, refresh = session(index, 0)
            access_ct, key = vault.encrypt(json.dumps(access))
            copy.write_row((workspace, CONNECTION, 'bluesky', did(index), access_ct, vault.encrypt(json.dumps(refresh))[0], key, SCOPES,
                            '2027-01-15 07:00:00+00', True))  # moved to NOW - 60 below: every access token has expired
    db.execute("UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE connection_id=%s", (NOW - 60, CONNECTION))
    db.execute('ANALYZE public.pr_encrypted_credentials')
seed_seconds = time.monotonic() - started
metrics = {'seedSeconds': round(seed_seconds, 3)}

try:
    # B3: two concurrent callers on one expired grant refresh exactly once and both get the rotated token.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: oauth.token_for_worker(WORKSPACES[0], CONNECTION), range(2)))
    assert endpoint.calls[0] == 1, endpoint.calls[0]
    assert results[0]['accessToken'] == results[1]['accessToken'] and ':0:1"' in results[0]['accessToken']
    supported, refresh_ct, key, expires, rotated = stored(0)
    assert supported and rotated and expires == NOW + 900
    assert json.loads(vault.decrypt(refresh_ct, key))['rt'] == 'synthetic-rt:0:1'

    # A definitive refusal marks only that grant as non-renewing (card asks for Reconnect); nothing else changes.
    before = stored(1)
    endpoint.mode[1] = 'revoked'
    try:
        oauth.token_for_worker(WORKSPACES[1], CONNECTION)
        raise AssertionError('A revoked grant returned a token.')
    except AlphaError as error:
        assert error.code == 'reauthorization_required'
    after = stored(1)
    assert after[0] is False and after[1] == before[1] and after[3] == before[3]

    # An outage leaves the grant renewing and untouched.
    before = stored(2)
    endpoint.mode[2] = 'outage'
    try:
        oauth.token_for_worker(WORKSPACES[2], CONNECTION)
        raise AssertionError('An outage returned a token.')
    except AlphaError as error:
        assert error.code == 'provider_unavailable'
    assert stored(2) == before
    metrics['refreshSafety'] = {'concurrentCallers': 2, 'refreshCalls': 1, 'revokedMarksNonRenewing': True, 'outageLeavesGrant': True}

    # D1 (database share): 997 tenants renew at once through 32 SQL workers.
    timings, failures, lock = [], [], threading.Lock()

    def renew(index):
        begin = time.monotonic()
        try:
            grant = oauth.token_for_worker(WORKSPACES[index], CONNECTION)
            assert f':{index}:1"' in grant['accessToken']
        except Exception as error:  # noqa: BLE001
            with lock: failures.append(f'{index}:{type(error).__name__}:{error}')
        finally:
            with lock: timings.append((time.monotonic() - begin) * 1000)

    begin = time.monotonic()
    with ThreadPoolExecutor(max_workers=SQL_CONCURRENCY) as pool:
        list(pool.map(renew, range(3, COUNT)))
    elapsed = time.monotonic() - begin
    assert not failures, failures[:5]
    assert all(endpoint.calls[index] == 1 for index in range(3, COUNT))
    metrics['renewal'] = {'tenants': COUNT - 3, 'sqlConcurrency': SQL_CONCURRENCY, 'failures': 0,
                          'p95Ms': round(sorted(timings)[math.ceil(len(timings) * .95) - 1], 3), 'maxMs': round(max(timings), 3),
                          'elapsedSeconds': round(elapsed, 3), 'fakeEndpointDelayMs': 50}

    # D3 under load: a burst of 1,000 Bluesky connect starts meets the site-wide cap exactly.
    def start(_index):
        try:
            with connection() as db, db.cursor() as cur:
                throttle(cur, 'oauth-start:bluesky', BLUESKY_STARTS_PER_MINUTE, 60)
            return 'admitted'
        except AlphaError as error:
            assert error.status == 429
            return 'deferred'

    with ThreadPoolExecutor(max_workers=SQL_CONCURRENCY) as pool:
        outcomes = list(pool.map(start, range(COUNT)))
    assert outcomes.count('admitted') == BLUESKY_STARTS_PER_MINUTE, outcomes.count('admitted')
    metrics['connectBurst'] = {'starts': COUNT, 'admitted': outcomes.count('admitted'), 'deferred': outcomes.count('deferred'),
                               'capPerMinute': BLUESKY_STARTS_PER_MINUTE}
    metrics.update(execution='cloud-synthetic-disposable-postgres', providerCalls=0, realAccountAcceptance=False,
                   productionHttpLoadAcceptance=False, elapsedSeconds=round(time.monotonic() - started, 3))
    path = ROOT / '.jcb-artifacts/bluesky-launch/CLOUD-SYNTHETIC-launch.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2) + '\n')
    print('RAFII_BLUESKY_LAUNCH ' + json.dumps(metrics, separators=(',', ':')))
finally:
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,))
        db.execute('DELETE FROM public.pr_profiles WHERE user_id=ANY(%s::uuid[])', (USERS,))
        db.execute('DELETE FROM auth.users WHERE id=ANY(%s::uuid[])', (USERS,))
        db.execute("DELETE FROM public.pr_auth_throttle WHERE true")
