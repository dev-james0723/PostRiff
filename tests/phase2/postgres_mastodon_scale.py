"""Cloud-only 1,000 concurrent connected-user requests, with bounded SQL workers.

This measures the real database admission and Queue selector. It is neither
production HTTP load acceptance nor live provider publication. No egress.
"""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Run through the disposable cloud PostgreSQL harness.')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_phase2.hosted import throttle
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import MastodonProvider
from postriff_alpha.domain import AlphaError

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
COUNT, SQL_CONCURRENCY, CLAIMS = 1000, 32, 40
NOW = 1800000000
WORKSPACES = [str(uuid4()) for _ in range(COUNT)]
USERS = [str(uuid4()) for _ in range(COUNT)]
CONNECTION = 'synthetic-mastodon-scale'
SCOPES = ['read:accounts', 'read:statuses', 'write:statuses']
vault = CredentialVault(CredentialVault.generate_key())
provider = MastodonProvider('https://rafii.io', resolver=lambda *_a, **_k: [(2, 1, 6, '', ('93.184.216.34', 443))])


def connection():
    return psycopg.connect(DSN, connect_timeout=5, options='-c statement_timeout=10000 -c lock_timeout=5000')


def identity(index):
    return f'{10000 + index}@mastodon.' + ('social' if index % 2 else 'online')


def state(index):
    workspace = WORKSPACES[index]
    return {'workspace': {'id': workspace}, 'syntheticMastodonScale': True,
        'phase2': {'channels': [{'id': CONNECTION, 'platform': 'Mastodon', 'providerAccountId': identity(index)}],
                  'reviews': [], 'jobs': [{
                    'id': f'synthetic-native-{index}-{number}', 'state': 'processing', 'leaseUntil': 0, 'nextAt': 0,
                    'manifest': {'workspaceId': workspace, 'channelId': CONNECTION, 'providerAccountId': identity(index),
                                 'platform': 'Mastodon', 'idempotencyKey': hashlib.sha256(f'{workspace}:{number}'.encode()).hexdigest()},
                    'progress': {'version': 3, 'stage': 'native_scheduled', 'reference': str(20000 + index * 2 + number)},
                    'events': [], 'attempts': []} for number in range(2)]}}


class NoEgress:
    def submit(self, *_a): raise AssertionError('Scale validation cannot publish.')
    def reconcile(self, *_a): raise AssertionError('Scale validation cannot call a provider.')


started = time.monotonic()
with connection() as db:
    with db.cursor().copy('COPY auth.users(id) FROM STDIN') as copy:
        for user in USERS: copy.write_row((user,))
    with db.cursor().copy('COPY public.pr_profiles(user_id) FROM STDIN') as copy:
        for user in USERS: copy.write_row((user,))
    with db.cursor().copy('COPY public.pr_workspaces(id,state) FROM STDIN') as copy:
        for index, workspace in enumerate(WORKSPACES): copy.write_row((workspace, json.dumps(state(index))))
    with db.cursor().copy('COPY public.pr_memberships(workspace_id,user_id,role,status) FROM STDIN') as copy:
        for workspace, user in zip(WORKSPACES, USERS): copy.write_row((workspace, user, 'owner', 'active'))
    with db.cursor().copy('COPY public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes,refresh_supported) FROM STDIN') as copy:
        for index, workspace in enumerate(WORKSPACES):
            encrypted, key = vault.encrypt(json.dumps({'v': 1, 'at': 'synthetic-scale-' + str(index),
                'instance': identity(index).split('@')[1], 'scope': SCOPES}))
            copy.write_row((workspace, CONNECTION, 'mastodon', identity(index), encrypted, key, SCOPES, False))
    db.execute('ANALYZE public.pr_workspaces'); db.execute('ANALYZE public.pr_encrypted_credentials')
seed_seconds = time.monotonic() - started
assert seed_seconds <= 30, seed_seconds
sql_counts = {'active': 0, 'peak': 0}
sql_lock = threading.Lock()


def admission(index):
    try:
        with connection() as db, db.cursor() as cur:
            with sql_lock:
                sql_counts['active'] += 1
                sql_counts['peak'] = max(sql_counts['peak'], sql_counts['active'])
            try:
                cur.execute("SELECT c.provider_account_id,c.access_ciphertext,c.key_id FROM public.pr_encrypted_credentials c JOIN public.pr_memberships m USING(workspace_id) JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE c.workspace_id=%s AND c.connection_id=%s AND c.provider='mastodon' AND c.revoked_at IS NULL AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (WORKSPACES[index], CONNECTION, USERS[index]))
                row = cur.fetchone(); assert row and row[0] == identity(index)
                session = provider.session(vault.decrypt(row[1], row[2]))
                assert session['at'] == 'synthetic-scale-' + str(index)
                assert session['instance'] == identity(index).split('@')[1]
                # Exact production admission function; no substitute controller.
                throttle(cur, 'mastodon-worker-instance:' + session['instance'], 200, 300)
                throttle(cur, 'mastodon-worker-account:' + WORKSPACES[index] + CONNECTION, 20, 300)
            finally:
                with sql_lock: sql_counts['active'] -= 1
        return 'admitted'
    except AlphaError as error:
        assert error.status == 429
        return 'deferred'


async def workload():
    gate, all_ready = asyncio.Event(), asyncio.Event()
    slots = asyncio.Semaphore(SQL_CONCURRENCY)
    active = sql_active = peak = sql_peak = ready = 0
    elapsed, responses = [], []
    pool = ThreadPoolExecutor(max_workers=SQL_CONCURRENCY)
    async def user_request(index):
        nonlocal active, sql_active, peak, sql_peak, ready
        active += 1; ready += 1; peak = max(peak, active)
        if ready == COUNT: all_ready.set()
        await gate.wait()
        beginning = time.monotonic()
        try:
            async with slots:
                sql_active += 1; sql_peak = max(sql_peak, sql_active)
                try:
                    responses.append(await asyncio.get_running_loop().run_in_executor(pool, admission, index))
                finally:
                    sql_active -= 1
        finally:
            elapsed.append((time.monotonic() - beginning) * 1000); active -= 1
    tasks = [asyncio.create_task(user_request(index)) for index in range(COUNT)]
    await asyncio.wait_for(all_ready.wait(), 10)
    assert peak == COUNT and len(tasks) == COUNT
    gate.set(); await asyncio.wait_for(asyncio.gather(*tasks), 60)
    pool.shutdown(wait=True)
    assert responses.count('admitted') == 400 and responses.count('deferred') == 600, responses.count('admitted')
    assert sql_peak == SQL_CONCURRENCY and active == sql_active == 0
    return {'simulatedConnectedUsers': COUNT, 'concurrentPendingRequestsPeak': peak,
        'pendingSqlOperationsPeak': sql_peak, 'actualSqlConnectionsPeak': sql_counts['peak'], 'completedRequests': len(responses),
        'admitted': responses.count('admitted'), 'deferred': responses.count('deferred'),
        'requestP95Ms': round(sorted(elapsed)[math.ceil(len(elapsed)*.95)-1], 3),
        'requestMaxMs': round(max(elapsed), 3)}


try:
    metrics = asyncio.run(workload())
    # Per-account bound uses the exact production function, including rejection.
    for _ in range(20):
        with connection() as db, db.cursor() as cur:
            throttle(cur, 'mastodon-worker-account:isolated-scale-account', 20, 300)
    try:
        with connection() as db, db.cursor() as cur:
            throttle(cur, 'mastodon-worker-account:isolated-scale-account', 20, 300)
        raise AssertionError('An account exceeded its budget.')
    except AlphaError as error: assert error.status == 429
    claimed, timings = [], []
    for _ in range(CLAIMS):
        worker = PostgresWorker(connection, social=NoEgress(), clock=lambda: NOW)
        begin = time.monotonic(); result = worker.claim(); timings.append((time.monotonic() - begin) * 1000)
        assert result and result['workspaceId'] in WORKSPACES
        index = WORKSPACES.index(result['workspaceId'])
        assert result['job']['manifest']['providerAccountId'] == identity(index)
        claimed.append(result['workspaceId'])
    assert len(set(claimed)) == CLAIMS
    metrics['queue'] = {'seededJobs': COUNT*2, 'fencedClaims': CLAIMS, 'distinctFairTenants': len(set(claimed)),
                        'claimP95Ms': round(sorted(timings)[math.ceil(CLAIMS*.95)-1], 3)}
    assert metrics['queue']['claimP95Ms'] <= 2000
    # Three concurrent cron lanes (main + two publish lanes) share the queue: no job is claimed twice and every lane
    # makes progress while the claim lock is contended.
    LANES, PER_LANE = 3, 20
    lane_claims, lane_busy = [[] for _ in range(LANES)], [0] * LANES
    def lane(index):
        worker = PostgresWorker(connection, social=NoEgress(), clock=lambda: NOW)
        for _ in range(PER_LANE * 20):
            if len(lane_claims[index]) >= PER_LANE:
                break
            result = worker.claim()
            if result:
                lane_claims[index].append((result['workspaceId'], result['job']['id']))
            elif worker.last_claim_busy:
                lane_busy[index] += 1; time.sleep(0.01)
            else:
                break
    threads = [threading.Thread(target=lane, args=(i,)) for i in range(LANES)]
    lane_started = time.monotonic()
    for thread in threads: thread.start()
    for thread in threads: thread.join(60)
    all_lane_claims = [c for claims in lane_claims for c in claims]
    assert len(all_lane_claims) == len(set(all_lane_claims)) == LANES * PER_LANE, (len(all_lane_claims), len(set(all_lane_claims)))
    metrics['lanes'] = {'lanes': LANES, 'claimsPerLane': [len(c) for c in lane_claims], 'busyRetries': lane_busy,
                        'duplicateClaims': 0, 'elapsedMs': round((time.monotonic() - lane_started) * 1000, 3)}
    metrics.update(execution='cloud-synthetic-connected-users-and-disposable-sql', providerCalls=0,
                   realAccountAcceptance=False, productionHttpLoadAcceptance=False, seedSeconds=round(seed_seconds, 3),
                   elapsedSeconds=round(time.monotonic()-started, 3), sqlConcurrencyBound=SQL_CONCURRENCY)
    path = ROOT/'.jcb-artifacts/mastodon-capacity/CLOUD-SYNTHETIC-capacity.json'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2)+'\n')
    print('RAFII_MASTODON_CAPACITY ' + json.dumps(metrics, separators=(',', ':')))
finally:
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,))
        db.execute('DELETE FROM public.pr_profiles WHERE user_id=ANY(%s::uuid[])', (USERS,))
        db.execute('DELETE FROM auth.users WHERE id=ANY(%s::uuid[])', (USERS,))
