"""Cloud-only isolated fleet claims/crash recovery; synthetic data, no provider calls."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Fleet acceptance requires disposable cloud PostgreSQL; never run on the Mac.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube.agent import YouTubePublishingAgent, prepare_draft, prepare_policy, activate_policy
from postriff_phase2.youtube.capacity import CapacityController, CapacityPolicy
from postriff_phase2.youtube.fleet import claim_planner, release_planner
from postriff_phase2.youtube.model import READ, UPLOAD, MANAGE, YouTubeError
from postriff_phase2.youtube.service import YouTubeCreatorService

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
TENANTS, THREADS, CLAIMS_PER_THREAD = 100, 8, 8
WORKSPACES = ['00000000-0000-0000-2000-' + format(index, '012x') for index in range(TENANTS)]
OTHER_WORKSPACES = ['00000000-0000-0000-2001-' + format(index, '012x') for index in range(8)]
CONNECTION, OWNER = 'synthetic-fleet-connection', str(uuid4())
PROJECT = 'synthetic-fleet-' + str(uuid4())
CLOCK = {'now': 1_800_000_000}
THRESHOLDS = {'stageDeadlineSeconds': 30, 'successfulClaimsPerStage': THREADS * CLAIMS_PER_THREAD,
              'claimP95Ms': 2000, 'claimMaxMs': 5000}


def connection():
    return psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                           options='-c statement_timeout=10000 -c lock_timeout=5000')


def clock():
    return CLOCK['now']


def channel(index):
    return 'UC' + hashlib.sha256(('synthetic-fleet-channel:' + str(index)).encode()).hexdigest()[:22]


def upload_job(workspace, index, platform_name='YouTube'):
    key = hashlib.sha256((workspace + ':' + platform_name).encode()).hexdigest()
    return {'id': 'synthetic-fleet-' + platform_name.lower() + '-' + str(index), 'state': 'processing',
        'manifest': {'workspaceId': workspace, 'channelId': CONNECTION, 'providerAccountId': channel(index),
                     'platform': platform_name, 'idempotencyKey': key},
        'progress': {'version': 2, 'stage': 'uploading', 'bytesSent': 3, 'totalBytes': 6},
        'attempts': [{'number': 1, 'idempotencyKey': key, 'startedAt': clock() - 60}],
        'events': [], 'nextAt': 0, 'leaseUntil': 0}


def state_for(workspace, index):
    """Use real local planning functions; this fixture never dispatches its proposed plans."""
    state = initial_phase2_state(workspace, OWNER, 'Synthetic owner', 'studio', clock(), execution='local-fixtures')
    state['syntheticFleet'] = True
    state['speaker']['activeRevision'] = 1
    state['phase2']['channels'] = [{'id': CONNECTION, 'platform': 'YouTube', 'account': 'Synthetic channel',
        'providerAccountId': channel(index), 'configured': True, 'identityVerified': True,
        'capabilityVerified': True, 'revoked': False, 'expiresAt': clock() + 7200, 'verifiedAt': clock(),
        'capabilityVersion': 1, 'evidenceSource': 'synthetic', 'scopes': [READ, UPLOAD, MANAGE]}]
    asset_id = uuid4().hex
    state['phase2']['assets'] = [{'id': asset_id, 'hash': hashlib.sha256(b'synthetic-fleet-asset').hexdigest(),
        'mime': 'video/mp4', 'processing': 'ready', 'originalFilename': 'synthetic-fleet.mp4',
        'width': 1080, 'height': 1920, 'bytes': 6, 'duration': 60, 'durationSource': 'container',
        'bucket': 'postriff-video', 'objectName': asset_id + '.mp4', 'etag': 'synthetic-immutable',
        'verified': {'container': True, 'locationChecked': True}, 'deleted': False}]
    local_time = datetime.fromtimestamp(clock() + 7200, timezone.utc).strftime('%Y-%m-%dT%H:%M')
    draft = prepare_draft(state, CONNECTION, {'assetId': asset_id, 'rightsConfirmed': True,
        'localTime': local_time, 'timeZone': 'UTC', 'fold': 0,
        'publishOptions': {'title': 'Synthetic fleet plan', 'description': 'Claim-only database acceptance',
            'privacyStatus': 'private', 'madeForKids': False, 'containsSyntheticMedia': False}}, OWNER, clock())
    policy = prepare_policy(state, CONNECTION, {'draftIds': [draft['id']], 'maxDaily': 1,
        'timeZone': 'UTC', 'endsAt': clock() + 86400}, OWNER, clock())
    activate_policy(state, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest'],
        'confirmationChannelId': channel(index)}, OWNER, clock())
    state['phase2']['jobs'] = [upload_job(workspace, index, 'LinkedIn'), upload_job(workspace, index)]
    return state


class NoProvider:
    calls = 0
    youtube = object()
    def submit(self, *_):
        self.calls += 1
        raise AssertionError('Fleet fixture must not submit provider content')
    def reconcile(self, *_):
        self.calls += 1
        raise AssertionError('Fleet fixture must not contact a provider')


SOCIAL = NoProvider()


def worker():
    result = PostgresWorker(connection, social=SOCIAL, clock=clock)
    result.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda _: None))
    return result


def concurrent_claims(factory):
    """Eight independent callers; bounded retries for short transaction contention."""
    deadline = time.monotonic() + THRESHOLDS['stageDeadlineSeconds']
    def collect(index):
        attempt, selected, durations = factory(index), [], []
        for _ in range(128):
            if len(selected) == CLAIMS_PER_THREAD or time.monotonic() >= deadline:
                break
            started = time.monotonic()
            result = attempt()
            if result:
                selected.append(result)
                durations.append((time.monotonic() - started) * 1000)
            else:
                time.sleep(.005)
        assert len(selected) == CLAIMS_PER_THREAD, 'A fleet caller did not make bounded claim progress'
        return selected, durations
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        groups = list(pool.map(collect, range(THREADS)))
    claims = [item for selected, _ in groups for item in selected]
    times = [value for _, durations in groups for value in durations]
    summary = {'threads': THREADS, 'claims': len(claims), 'elapsedSeconds': round(time.monotonic() - started, 4),
        'p50Ms': round(statistics.median(times), 4),
        'p95Ms': round(sorted(times)[math.ceil(len(times) * .95) - 1], 4), 'maxMs': round(max(times), 4)}
    assert summary['p95Ms'] <= THRESHOLDS['claimP95Ms'] and summary['maxMs'] <= THRESHOLDS['claimMaxMs'], summary
    return claims, summary


def upload_acceptance(metrics):
    def factory(_):
        owner = worker()
        def attempt():
            claimed = owner.claim(youtube_only=True)
            return (owner, claimed) if claimed else None
        return attempt
    # A locked tenant must not prevent a different tenant's fenced claim.
    with connection() as locked:
        locked.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (WORKSPACES[0],))
        claims, summary = concurrent_claims(factory)
    selected = [claimed for _, claimed in claims]
    assert len({c['workspaceId'] for c in selected}) == len(selected)
    assert len({c['job']['leaseId'] for c in selected}) == len(selected)
    assert all(c['workspaceId'] in WORKSPACES[1:] and c['job']['manifest']['platform'] == 'YouTube'
               and c['job']['manifest']['workspaceId'] == c['workspaceId'] for c in selected)
    with connection() as db:
        states = db.execute('SELECT state FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])',
                            (WORKSPACES + OTHER_WORKSPACES,)).fetchall()
        untouched = [j for (state,) in states for j in state['phase2']['jobs'] if j['manifest']['platform'] != 'YouTube']
        assert len(untouched) == TENANTS + len(OTHER_WORKSPACES)
        assert all(j['leaseUntil'] == 0 and 'leaseId' not in j and j['events'] == [] for j in untouched)
        # Isolate one discarded claim for deterministic crash/expiry recovery.
        for workspace, raw in db.execute('SELECT id::text,state FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,)).fetchall():
            for job in raw['phase2']['jobs']:
                if job['manifest']['platform'] == 'YouTube':
                    job['nextAt'] = 0 if workspace == WORKSPACES[0] else clock() + 10000
                    if workspace == WORKSPACES[0]:
                        job['state'] = 'submitting'
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(raw), workspace))
    crashed = worker()
    assert crashed.step(crash='after_claim', youtube_only=True)
    with connection() as db:
        saved = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[0],)).fetchone()[0]
        abandoned = next(j for j in saved['phase2']['jobs'] if j['manifest']['platform'] == 'YouTube')
        journal_before = db.execute('SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s', (WORKSPACES[0],)).fetchone()[0]
    assert abandoned['leaseOwner'] == crashed.worker_id and abandoned['state'] == 'uncertain'
    assert worker().claim(youtube_only=True) is None
    CLOCK['now'] += 46
    recovered = worker()
    fresh = recovered.claim(youtube_only=True)
    assert fresh and fresh['workspaceId'] == WORKSPACES[0] and fresh['reconciliation'] is True
    assert fresh['job']['leaseId'] != abandoned['leaseId']
    assert fresh['job']['manifest'] == abandoned['manifest'] and fresh['job']['progress'] == abandoned['progress']
    stale = {'workspaceId': WORKSPACES[0], 'job': copy.deepcopy(abandoned), 'reconciliation': True}
    assert crashed.complete(stale, {'state': 'uncertain', 'confirmed': 'Synthetic stale completion'}) is False
    with connection() as db:
        assert db.execute('SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s', (WORKSPACES[0],)).fetchone()[0] == journal_before
    summary.update(distinctTenants=len(selected), duplicateLeases=0, otherPlatformJobsUntouched=len(untouched),
                   lockedTenantSkipped=True, expiredLeaseRecovered=True, staleCompletionRejected=True, journalPreserved=True)
    metrics['uploadClaims'] = summary


def planner_acceptance(metrics):
    agent = YouTubePublishingAgent.__new__(YouTubePublishingAgent)
    agent.service, agent.clock = SimpleNamespace(connection_factory=connection), clock
    claims, summary = concurrent_claims(lambda _: lambda: claim_planner(agent))
    assert len({candidate[0] for candidate in claims}) == len(claims)
    assert len({candidate[4] for candidate in claims}) == len(claims)
    assert all(candidate[0] in WORKSPACES and candidate[1] == CONNECTION for candidate in claims)
    target, candidate = claims[0][0], claims[0]
    with connection() as db:
        for workspace, state in db.execute('SELECT id::text,state FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,)).fetchall():
            if workspace != target:
                for policy in state['youtubeAgent']['policies']:
                    policy['status'] = 'paused'
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), workspace))
    assert claim_planner(agent) is None, 'An unexpired planner lease was duplicated'
    CLOCK['now'] += 121
    assert claim_planner(agent, excluded=(target,)) is None
    fresh = claim_planner(agent)
    assert fresh and fresh[0] == target and fresh[4] != candidate[4]
    release_planner(agent, candidate)
    with connection() as db:
        lease = db.execute("SELECT state#>'{youtubeAgent,fleetLease}' FROM public.pr_workspaces WHERE id=%s", (target,)).fetchone()[0]
        assert lease['id'] == fresh[4], 'Stale planner release cleared a newer fence'
    release_planner(agent, fresh)
    with connection() as db:
        assert db.execute("SELECT state#>'{youtubeAgent,fleetLease}' FROM public.pr_workspaces WHERE id=%s", (target,)).fetchone()[0] is None
    summary.update(distinctTenants=len(claims), duplicateLeases=0, expiryRecovered=True,
                   excludedWorkspaceHonored=True, staleReleaseRejected=True, claimsOnly=True)
    metrics['plannerClaims'] = summary


def identity_acceptance(metrics):
    creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
    creator.service = SimpleNamespace(connection_factory=connection)
    claims, summary = concurrent_claims(lambda _: lambda: creator.claim_identity())
    assert len(set(claims)) == len(claims)
    assert all(workspace in WORKSPACES and name == CONNECTION for workspace, name in claims)
    target = claims[0]
    with connection() as db:
        db.execute("""INSERT INTO public.pr_youtube_cache(workspace_id,connection_id,cache_key,source,data,expires_at)
            SELECT id,%s,'authorization-check','synthetic fleet recovery','{}'::jsonb,now()+interval '1 day'
            FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])
            ON CONFLICT(workspace_id,connection_id,cache_key) DO UPDATE SET expires_at=excluded.expires_at""", (CONNECTION, WORKSPACES))
    assert creator.claim_identity() is None, 'An active identity lease was duplicated'
    with connection() as db:
        db.execute("UPDATE public.pr_youtube_cache SET expires_at=now()-interval '1 second' WHERE workspace_id=%s AND connection_id=%s AND cache_key='authorization-check'", target)
    assert creator.claim_identity(excluded=(target,)) is None
    assert creator.claim_identity() == target
    assert creator.claim_identity() is None
    summary.update(distinctConnections=len(claims), duplicateLeases=0, expiryRecovered=True,
                   batchExclusionHonored=True, claimsOnly=True)
    metrics['identityClaims'] = summary


def shared_budget_acceptance(metrics):
    policy = CapacityPolicy(PROJECT, {'videoUploads': 7, 'search': 100, 'general': 10000},
                            {'videoUploads': 2, 'search': 20, 'general': 2000})
    controllers = [CapacityController(connection, policy, clock=clock) for _ in range(THREADS)]
    def reserve(index):
        try:
            controllers[index % THREADS].record(WORKSPACES[index], CONNECTION, 'videos.insert', 'videoUploads', 1)
            return True
        except YouTubeError as error:
            assert error.category == 'capacity_delay' and error.capacity_reason == 'project_daily'
            return False
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        results = list(pool.map(reserve, range(24)))
    assert sum(results) == 7
    with connection() as db:
        row = db.execute("SELECT used_units,admitted_requests,denied_requests FROM public.pr_youtube_quota_daily WHERE project_key=%s AND scope_key='project' AND bucket='videoUploads'", (PROJECT,)).fetchone()
        assert row == (7, 7, 17)
    metrics['sharedProjectAdmission'] = {'independentControllers': THREADS, 'attempts': len(results),
        'projectBudgetUnits': 7, 'admitted': sum(results), 'denied': len(results) - sum(results)}


started = time.monotonic()
seeded = False
metrics = {'execution': 'synthetic-cloud-postgres-fleet', 'status': 'running', 'tenants': TENANTS,
    'threads': THREADS, 'providerCalls': 0, 'productionAcceptance': False, 'productionLoadAcceptance': False,
    'realAccountConsent': False, 'realUploadAcceptance': False, 'thresholds': THRESHOLDS,
    'runtime': {'system': platform.system(), 'architecture': platform.machine(),
                'logicalCpuCount': os.cpu_count(), 'pythonVersion': platform.python_version()}}
try:
    vault = CredentialVault(CredentialVault.generate_key())
    with connection() as db:
        # Explicit inet::text retains /32; host(inet) returns only the address.
        # https://www.postgresql.org/docs/16/functions-net.html
        server = db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone()
        observed = tuple(value[:64] if isinstance(value, str) else value for value in server)
        assert server == ('127.0.0.1', 55438, 'postgres'), f'Disposable server guard mismatch (host, port, database): {observed!r}'
        # Both established runners name their disposable data roots explicitly;
        # a Linux+CI flag alone must not authorize touching an unrelated cluster.
        directory = Path(db.execute("SELECT current_setting('data_directory')").fetchone()[0])
        assert directory.parent.name.startswith(('postriff-cw-pg-', 'consumer-pg-')), 'A fresh disposable runner cluster is required'
        for table in ('pr_worker_tenants', 'pr_youtube_cache', 'pr_youtube_uploads', 'pr_youtube_quota_daily'):
            assert db.execute('SELECT to_regclass(%s)', ('public.' + table,)).fetchone()[0], 'Apply reviewed 089/097 before fleet acceptance'
        assert db.execute("SELECT count(*) FROM public.pr_encrypted_credentials WHERE provider='youtube'").fetchone()[0] == 0, 'Use a fresh cluster, not prior provider fixtures'
        assert db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES + OTHER_WORKSPACES,)).fetchone()[0] == 0
        metrics['runtime']['postgresVersion'] = db.execute('SHOW server_version').fetchone()[0]
        for index, workspace in enumerate(WORKSPACES):
            state = state_for(workspace, index)
            db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (workspace, json.dumps(state)))
            access, key = vault.encrypt('synthetic-unusable-fleet-access:' + str(index))
            db.execute("""INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
                access_ciphertext,key_id,scopes,refresh_supported) VALUES(%s,%s,'youtube',%s,%s,%s,%s,false)""",
                (workspace, CONNECTION, channel(index), access, key, [READ, UPLOAD, MANAGE]))
            journal = {'version': 2, 'stage': 'uploading', 'bytesSent': 3, 'totalBytes': 6, 'syntheticMarker': index}
            db.execute('INSERT INTO public.pr_youtube_uploads(workspace_id,connection_id,operation_key,state) VALUES(%s,%s,%s,%s::jsonb)',
                (workspace, CONNECTION, state['phase2']['jobs'][1]['manifest']['idempotencyKey'], json.dumps(journal)))
        for index, workspace in enumerate(OTHER_WORKSPACES):
            db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)',
                (workspace, json.dumps({'phase2': {'channels': [], 'reviews': [], 'jobs': [upload_job(workspace, index, 'LinkedIn')]}})))
    seeded = True
    upload_acceptance(metrics)
    planner_acceptance(metrics)
    identity_acceptance(metrics)
    shared_budget_acceptance(metrics)
    assert SOCIAL.calls == 0
    metrics['status'] = 'pass'
except Exception as error:
    metrics.update(status='fail', failureType=type(error).__name__)
    raise
finally:
    cleanup_error = None
    try:
        if seeded:
            with connection() as db:
                db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES + OTHER_WORKSPACES,))
                db.execute('DELETE FROM public.pr_youtube_quota_daily WHERE project_key=%s', (PROJECT,))
    except Exception as error:
        cleanup_error = error
        metrics.update(status='fail', cleanupFailureType=type(error).__name__)
    metrics.update(providerCalls=SOCIAL.calls, elapsedSeconds=round(time.monotonic() - started, 4))
    artifacts = ROOT / '.jcb-artifacts'
    artifacts.mkdir(exist_ok=True)
    (artifacts / 'youtube-fleet-acceptance.json').write_text(json.dumps(metrics, indent=2) + '\n')
    print('RAFII_YOUTUBE_FLEET_EVIDENCE ' + json.dumps(metrics, separators=(',', ':')))
    if cleanup_error:
        raise cleanup_error
