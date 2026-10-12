"""Cloud-only: 1,000 isolated tenants, real SQL/worker/custody, synthetic LinkedIn.

This does not prove LinkedIn consent, a live publication, provider quotas or
production load. Every provider endpoint is replaced by an explicit zero-network
transport. Approval states are cloned from a fully exercised disposable workflow.
"""
import copy
import json
import math
import os
import statistics
import sys
import threading
import time
from unittest.mock import patch
from uuid import UUID, uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Use the disposable JCB/Depot PostgreSQL harness; no local execution.')

import postgres_repository as fixture
from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker, due_workspaces_sql
from postriff_phase2.linkedin_fleet import tick as fleet_tick
from postriff_phase2.oauth import CredentialVault, OAuthService
from test_linkedin_publishing_recovery import approved_member_app

COUNT, CONCURRENCY = 1000, 8
NOW = fixture.clock[0]
WORKSPACES = [str(uuid4()) for _ in range(COUNT)]
USERS = [str(uuid4()) for _ in range(COUNT)]
CHANNELS = ['linkedin-scale-' + str(i).zfill(8) for i in range(COUNT)]
ACCOUNTS = ['urn:li:person:synthetic_' + str(i) for i in range(COUNT)]
TOKENS = {'scale-session-' + str(i): USERS[i] for i in range(COUNT)}
BASE = fixture.service.repository.get(fixture.wid, 'fixture-one')['state']
THRESHOLDS = {'seedSeconds': 60, 'dispatchSeconds': 300, 'dispatchP95Ms': 5000,
              'queryExecutionMs': 2000, 'duplicateCreates': 0, 'foreignReads': 0}
metrics = {'execution': 'synthetic-provider-real-cloud-postgres', 'tenants': COUNT,
           'concurrency': CONCURRENCY, 'realLinkedInPosts': 0, 'realConsent': False,
           'providerQuotaAcceptance': False, 'productionLoadAcceptance': False,
           'thresholds': THRESHOLDS}


def verify(token):
    if token not in TOKENS:
        raise AlphaError('Verified session required', 401)
    return TOKENS[token]


def connection():
    import psycopg
    return psycopg.connect(fixture.DSN, client_encoding='utf8', connect_timeout=5,
                           options='-c statement_timeout=15000 -c lock_timeout=10000')


def tenant_state(index):
    # Replace complete identifiers, retaining the exact content/brand/source
    # digests from the accepted workflow. Never disable approval/current checks.
    encoded = json.dumps(BASE).replace(fixture.wid, WORKSPACES[index]).replace(fixture.one, USERS[index])
    old_channel = BASE['phase2']['channels'][0]
    encoded = encoded.replace(old_channel['id'], CHANNELS[index]).replace(old_channel['providerAccountId'], ACCOUNTS[index])
    state = json.loads(encoded)
    state['syntheticLinkedInScale'] = True
    channel = state['phase2']['channels'][0]
    channel.update(expiresAt=NOW + 7200, verifiedAt=NOW, enabledPermissionGroups=['identity', 'publish'])
    manifest = copy.deepcopy(state['phase2']['jobs'][0]['manifest'])
    manifest['actor'] = USERS[index]
    manifest['workspaceId'] = WORKSPACES[index]
    manifest['expiresAt'] = NOW + 3600
    manifest['timing']['timestamp'] = NOW - 1
    manifest.pop('idempotencyKey', None)
    manifest['idempotencyKey'] = digest(manifest)
    state['phase2']['jobs'] = [{'id': 'scale-job-' + str(index), 'manifest': manifest,
        'approvalDigest': digest(manifest), 'approvedBy': USERS[index], 'approvedAt': NOW - 1,
        'state': 'approved', 'nextAt': NOW - 1, 'checks': 0, 'events': [], 'attempts': [],
        'leaseOwner': None, 'leaseUntil': 0, 'cancelRequested': False}]
    state['phase2']['reviews'] = []
    return state


vault = CredentialVault(CredentialVault.generate_key())
states = [tenant_state(i) for i in range(COUNT)]
started = time.monotonic()
with connection() as db:
    with db.cursor().copy('COPY auth.users(id) FROM STDIN') as writer:
        for user in USERS:
            writer.write_row((user,))
    with db.cursor().copy('COPY public.pr_profiles(user_id,display_name) FROM STDIN') as writer:
        for i, user in enumerate(USERS):
            writer.write_row((user, 'Synthetic LinkedIn tenant ' + str(i)))
    with db.cursor().copy('COPY public.pr_workspaces(id,state) FROM STDIN') as writer:
        for wid, state in zip(WORKSPACES, states):
            writer.write_row((wid, json.dumps(state)))
    with db.cursor().copy('COPY public.pr_memberships(workspace_id,user_id,role,status) FROM STDIN') as writer:
        for wid, user in zip(WORKSPACES, USERS):
            writer.write_row((wid, user, 'owner', 'active'))
    with db.cursor().copy('COPY public.pr_trials(user_id,workspace_id,plan,expires_at) FROM STDIN') as writer:
        from datetime import datetime, timezone
        expiry = datetime.fromtimestamp(NOW + 86400, timezone.utc)
        for wid, user in zip(WORKSPACES, USERS):
            writer.write_row((user, wid, 'studio', expiry))
    with db.cursor().copy('''COPY public.pr_encrypted_credentials(workspace_id,connection_id,provider,
        provider_account_id,access_ciphertext,key_id,scopes,access_expires_at,refresh_supported) FROM STDIN''') as writer:
        expiry = datetime.fromtimestamp(NOW + 7200, timezone.utc)
        for i, wid in enumerate(WORKSPACES):
            encrypted, key = vault.encrypt('synthetic-scale-token:' + str(i))
            writer.write_row((wid, CHANNELS[i], 'linkedin', ACCOUNTS[i], encrypted, key,
                              '{openid,profile,w_member_social}', expiry, False))
    db.execute('ANALYZE public.pr_workspaces')
    db.execute('ANALYZE public.pr_encrypted_credentials')
    row = db.execute('SELECT count(*),count(DISTINCT provider_account_id),count(DISTINCT access_ciphertext) FROM public.pr_encrypted_credentials WHERE workspace_id=ANY(%s::uuid[])', (WORKSPACES,)).fetchone()
    assert row == (COUNT, COUNT, COUNT), row
    metrics['postgresVersion'] = db.execute('SHOW server_version').fetchone()[0]
metrics['seedSeconds'] = round(time.monotonic() - started, 4)
assert metrics['seedSeconds'] <= THRESHOLDS['seedSeconds'], metrics

repository = PostgresWorkspaceRepository(connection, verify, fixture.service.commands)
# Commands are unnecessary for reads; retaining the hosted service's engine
# below still verifies all immutable approval/current-source predicates.
provider = approved_member_app()
provider.official_social_enabled = True
lock = threading.Lock()
creates, introspections = {}, []


def introspect(method, url, **kwargs):
    assert method == 'POST' and url == 'https://www.linkedin.com/oauth/v2/introspectToken'
    token = kwargs.get('form', {}).get('token', '')
    assert token.startswith('synthetic-scale-token:')
    with lock:
        introspections.append(int(token.split(':')[1]))
    return {'status': 200, 'body': {'active': True, 'client_id': provider.client_id,
                                  'scope': 'openid profile w_member_social'}, 'headers': {}}


def publish(method, url, **kwargs):
    assert method == 'POST' and url == 'https://api.linkedin.com/rest/posts', (method, url)
    token = kwargs['headers']['Authorization'].removeprefix('Bearer ')
    index = int(token.removeprefix('synthetic-scale-token:'))
    assert kwargs['body']['author'] == ACCOUNTS[index], 'Cross-tenant token/author mismatch'
    with lock:
        creates[index] = creates.get(index, 0) + 1
        assert creates[index] == 1, 'Duplicate create for tenant ' + str(index)
    return {'status': 201, 'body': {}, 'headers': {'x-restli-id': 'urn:li:share:' + str(9000000 + index)}}


provider.transport = introspect
oauth = OAuthService(repository, fixture.service.commands, vault, {'linkedin': provider},
                     provider.public_origin, clock=lambda: NOW)
social = HostedSocial(oauth, {'linkedin': provider}, transport=publish)
isolation_started = time.monotonic()
for i, wid in enumerate(WORKSPACES):
    assert repository.get(wid, 'scale-session-' + str(i))['state']['workspace']['id'] == wid
    try:
        repository.get(WORKSPACES[(i + 1) % COUNT], 'scale-session-' + str(i))
    except AlphaError as error:
        assert error.status in (403, 404)
    else:
        raise AssertionError('Foreign workspace readable')
metrics['foreignReadDenials'] = COUNT
metrics['isolationSeconds'] = round(time.monotonic() - isolation_started, 4)
assert not introspections and not creates
with connection() as db:
    plan = db.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ' + due_workspaces_sql(linkedin_only=True), (NOW, NOW)).fetchone()[0][0]
    metrics['queryPlan'] = {'planningMs': plan['Planning Time'], 'executionMs': plan['Execution Time'],
                           'actualRows': plan['Plan']['Actual Rows']}
    assert plan['Plan']['Actual Rows'] <= 100
    assert plan['Execution Time'] <= THRESHOLDS['queryExecutionMs']
    db.execute('SET LOCAL ROLE authenticated')
    for i in range(COUNT):
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (USERS[i],))
        visible = db.execute('SELECT id FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,)).fetchall()
        assert visible == [(UUID(WORKSPACES[i]),)], 'RLS tenant leak'
metrics['rlsIsolatedUsers'] = COUNT

durations = []
dispatch_started = time.monotonic()


class ObservedWorker(PostgresWorker):
    """Time the unchanged production dispatch; all SQL/authorization is real."""
    def step(self, *args, **kwargs):
        before = time.monotonic()
        result = super().step(*args, **kwargs)
        elapsed = (time.monotonic() - before) * 1000
        if result:
            with lock:
                durations.append(elapsed)
        return result


base_worker = PostgresWorker(connection, social=social, clock=lambda: NOW)
batches = []
with patch('postriff_phase2.linkedin_fleet.PostgresWorker', ObservedWorker):
    while len(creates) < COUNT:
        assert time.monotonic() - dispatch_started < THRESHOLDS['dispatchSeconds'], 'Fleet dispatch time budget exceeded'
        assert len(batches) < 10, 'Production cron cannot drain 1,000 due jobs within ten bounded invocations'
        batch_started = time.monotonic()
        result = fleet_tick(base_worker, {'POSTRIFF_LINKEDIN_FLEET_ENABLED': 'true'})
        assert not result['errors'], result
        assert result['budget'] == dict(enabled=True, workers=8, maxJobs=25, maxSeconds=45)
        assert 0 < result['processed'] <= 200, result
        batches.append({'processed': result['processed'], 'seconds': round(time.monotonic() - batch_started, 4),
                        'workerProcessed': [item['processed'] for item in result['workers']]})
metrics['productionFleet'] = {'workers': CONCURRENCY, 'maxJobsPerWorker': 25, 'maxSecondsPerWorker': 45,
                              'cronIntervalSeconds': 60, 'invocationsToDrain': len(batches), 'batches': batches,
                              'enabledInProduction': False}
metrics['dispatchSeconds'] = round(time.monotonic() - dispatch_started, 4)
metrics['dispatchP95Ms'] = round(sorted(durations)[max(0, math.ceil(len(durations) * .95) - 1)], 4)
metrics['dispatchP50Ms'] = round(statistics.median(durations), 4)
metrics['syntheticCreates'] = len(creates)
metrics['duplicateCreates'] = sum(max(0, count - 1) for count in creates.values())
metrics['tokenAuthorBindings'] = len(set(introspections))
assert len(creates) == COUNT and set(creates.values()) == {1}
assert metrics['dispatchSeconds'] <= THRESHOLDS['dispatchSeconds']
assert metrics['dispatchP95Ms'] <= THRESHOLDS['dispatchP95Ms']
with connection() as db:
    saved = db.execute('SELECT state FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,)).fetchall()
    for row in saved:
        state = row[0]
        job = state['phase2']['jobs'][0]
        assert job['state'] == 'provider_accepted', job
        assert len(job['attempts']) == 1
        assert job.get('providerReference'), job
        assert job['manifest']['workspaceId'] == state['workspace']['id']
        # Accepted create is explicitly not a verified/live provider publication.
        assert not any(event['state'] == 'verified' for event in job['events'])
    metrics['durableAcceptedReceipts'] = len(saved)

# Restart/reconcile a sample without a restricted read grant. The worker may
# preserve acceptance or hold for manual verification; it must never create again.
before = dict(creates)
for i in range(8):
    worker = PostgresWorker(connection, social=social, clock=lambda: NOW + 120, worker_id='scale-restart-' + str(i))
    worker.step(workspace_id=WORKSPACES[i], job_id='scale-job-' + str(i),
                approval_digest=states[i]['phase2']['jobs'][0]['approvalDigest'], dispatch_principal=USERS[i])
assert creates == before
metrics['restartChecksWithoutDuplicateCreate'] = 8
metrics['status'] = 'pass'
print(json.dumps(metrics, indent=2, sort_keys=True))
