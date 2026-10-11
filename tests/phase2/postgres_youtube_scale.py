"""Cloud-only 10,000 synthetic tenants: database scale, never provider acceptance."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Scale acceptance requires the disposable cloud PostgreSQL harness; never run on the Mac.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_phase2.hosted_worker import PostgresWorker, due_workspaces_sql
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube.capacity import CapacityController, CapacityPolicy
from postriff_phase2.youtube.model import YouTubeError

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
COUNT, CLAIMS, NOW = 10_000, 40, 1_800_000_000
PROJECT = 'synthetic-scale-' + str(uuid4())
# These IDs precede ordinary randomly allocated disposable fixtures. No real DB
# connection string, environment credential or provider transport is accepted.
WORKSPACES = ['00000000-0000-0000-1000-' + format(index, '012x') for index in range(COUNT)]
CONNECTION = 'synthetic-scale-connection'
THRESHOLDS = {'seedSeconds': 60, 'claimP95Ms': 2000, 'claimMaxMs': 5000, 'queryPlanExecutionMs': 2000,
              'concurrentReservationsSeconds': 30, 'distinctFairTenants': CLAIMS}


def connection():
    return psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                           options='-c statement_timeout=10000 -c lock_timeout=5000')


def channel_id(index):
    return 'UC' + hashlib.sha256(('synthetic-scale-channel:' + str(index)).encode()).hexdigest()[:22]


def tenant_state(workspace, index):
    channel = channel_id(index)
    return {'workspace': {'id': workspace}, 'syntheticScale': True,
        'phase2': {'reviews': [], 'channels': [{'id': CONNECTION, 'platform': 'YouTube', 'providerAccountId': channel}],
            'jobs': [{'id': 'synthetic-scale-job-' + str(index) + '-' + str(number), 'state': 'processing',
                'manifest': {'workspaceId': workspace, 'channelId': CONNECTION, 'providerAccountId': channel,
                    'platform': 'YouTube', 'idempotencyKey': hashlib.sha256((workspace + ':' + str(number)).encode()).hexdigest()},
                'progress': {'version': 2, 'stage': 'native_scheduled'}, 'attempts': [], 'events': [],
                'leaseUntil': 0, 'nextAt': 0} for number in range(2)]}}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def nodes(plan):
    yield {key: plan[key] for key in ('Node Type', 'Plan Rows', 'Actual Rows', 'Actual Total Time',
                                     'Shared Hit Blocks', 'Shared Read Blocks') if key in plan}
    for child in plan.get('Plans', []):
        yield from nodes(child)


class NoProvider:
    def submit(self, *_):
        raise AssertionError('Scale fixture must never submit provider content')
    def reconcile(self, *_):
        raise AssertionError('Scale fixture measures fenced claims, not provider readback')


started = time.monotonic()
metrics = {'execution': 'synthetic-cloud-postgres', 'providerCalls': 0, 'realAccountConsent': False,
           'realUploadAcceptance': False, 'productionLoadAcceptance': False, 'tenants': COUNT,
           'channels': COUNT, 'dueJobs': COUNT * 2, 'thresholds': THRESHOLDS,
           'runtime': {'system': platform.system(), 'architecture': platform.machine(), 'logicalCpuCount': os.cpu_count(),
                       'pythonVersion': platform.python_version()}}
vault = CredentialVault(CredentialVault.generate_key())
try:
    seed_started = time.monotonic()
    with connection() as db:
        with db.cursor().copy('COPY public.pr_workspaces(id,state) FROM STDIN') as copy:
            for index, workspace in enumerate(WORKSPACES):
                copy.write_row((workspace, json.dumps(tenant_state(workspace, index))))
        with db.cursor().copy('''COPY public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
            access_ciphertext,refresh_ciphertext,key_id,scopes,refresh_supported) FROM STDIN''') as copy:
            for index, workspace in enumerate(WORKSPACES):
                access, key = vault.encrypt('synthetic-unusable-access:' + str(index))
                refresh, _ = vault.encrypt('synthetic-unusable-refresh:' + str(index))
                copy.write_row((workspace, CONNECTION, 'youtube', channel_id(index), access, refresh, key, '{}', True))
        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,'00000000-0000-0000-0000-000000000001','owner','active')", (WORKSPACES[0],))
        db.execute('ANALYZE public.pr_workspaces')
        db.execute('ANALYZE public.pr_encrypted_credentials')
        db.execute('ANALYZE public.pr_worker_tenants')
        count = db.execute('''SELECT count(*),count(DISTINCT c.provider_account_id)
            FROM public.pr_encrypted_credentials c JOIN public.pr_workspaces w ON w.id=c.workspace_id
            WHERE w.state ? 'syntheticScale' ''').fetchone()
        assert count == (COUNT, COUNT), count
        for index in (0, COUNT - 1):
            row = db.execute('SELECT access_ciphertext,key_id,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',
                             (WORKSPACES[index], CONNECTION)).fetchone()
            assert vault.decrypt(row[0], row[1]) == 'synthetic-unusable-access:' + str(index)
            assert row[2] == channel_id(index)
        metrics['runtime']['postgresVersion'] = db.execute('SHOW server_version').fetchone()[0]
        metrics['runtime']['postgresMaxConnections'] = int(db.execute('SHOW max_connections').fetchone()[0])
    metrics['seedSeconds'] = round(time.monotonic() - seed_started, 4)
    assert metrics['seedSeconds'] <= THRESHOLDS['seedSeconds'], metrics

    # Explain the exact production selection. No copied/drifting query contract.
    with connection() as db:
        plan = db.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ' + due_workspaces_sql(), (NOW, NOW)).fetchone()[0][0]
        metrics['queryPlan'] = {'planningMs': plan['Planning Time'], 'executionMs': plan['Execution Time'],
                                'nodes': list(nodes(plan['Plan']))}
    assert plan['Plan']['Actual Rows'] <= 100, plan
    assert plan['Execution Time'] <= THRESHOLDS['queryPlanExecutionMs'], metrics

    # Two due jobs per tenant make this a fairness test: the first tenant still
    # has due work after its lease, but durable rotation selects a new tenant.
    claimed, durations = [], []
    for _ in range(CLAIMS):
        # Restart the worker each time: fairness cannot rely on process memory.
        worker = PostgresWorker(connection, social=NoProvider(), clock=lambda: NOW)
        worker.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda _: None))
        claim_started = time.monotonic()
        result = worker.claim()
        durations.append((time.monotonic() - claim_started) * 1000)
        assert result and result['workspaceId'] in WORKSPACES, result
        assert result['job']['manifest']['workspaceId'] == result['workspaceId']
        assert result['job']['manifest']['providerAccountId'] == channel_id(WORKSPACES.index(result['workspaceId']))
        claimed.append(result['workspaceId'])
    assert len(set(claimed)) == CLAIMS, claimed
    metrics['fairClaim'] = {'claims': CLAIMS, 'distinctTenants': len(set(claimed)),
        'p50Ms': round(statistics.median(durations), 4), 'p95Ms': round(percentile(durations, .95), 4),
        'maxMs': round(max(durations), 4)}
    assert metrics['fairClaim']['p95Ms'] <= THRESHOLDS['claimP95Ms'], metrics
    assert metrics['fairClaim']['maxMs'] <= THRESHOLDS['claimMaxMs'], metrics
    with connection() as db:
        assert db.execute('SELECT count(*) FROM public.pr_worker_tenants WHERE workspace_id=ANY(%s::uuid[])', (WORKSPACES,)).fetchone()[0] == CLAIMS
        assert db.execute("SELECT count(*) FROM public.pr_workspaces WHERE state ? 'syntheticScale' AND (state#>>'{phase2,jobs,0,leaseUntil}')::float8>%s", (NOW,)).fetchone()[0] == CLAIMS

    controller = CapacityController(connection, CapacityPolicy(PROJECT,
        {'videoUploads': 100, 'search': 100, 'general': 50},
        {'videoUploads': 5, 'search': 20, 'general': 2}), clock=lambda: NOW)
    for _ in range(2): controller.record(WORKSPACES[0], CONNECTION, 'channels.list', 'general', 1)
    try:
        controller.record(WORKSPACES[0], CONNECTION, 'channels.list', 'general', 1)
        raise AssertionError('One tenant bypassed its own budget')
    except YouTubeError as error:
        assert error.capacity_reason == 'workspace_daily'

    def reserve(index):
        try:
            controller.record(WORKSPACES[index % 60], CONNECTION, 'channels.list', 'general', 1)
            return True
        except YouTubeError as error:
            assert error.category == 'capacity_delay'
            return False

    admission_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        reservations = list(pool.map(reserve, range(120)))
    metrics['concurrentAdmission'] = {'attempts': 123, 'threads': 8, 'admitted': sum(reservations) + 2,
                                    'denied': 121 - sum(reservations),
                                    'elapsedSeconds': round(time.monotonic() - admission_started, 4)}
    assert metrics['concurrentAdmission']['admitted'] == 50, metrics
    assert metrics['concurrentAdmission']['denied'] == 73, metrics
    assert metrics['concurrentAdmission']['elapsedSeconds'] <= THRESHOLDS['concurrentReservationsSeconds'], metrics
    with connection() as db:
        project = db.execute("SELECT used_units,admitted_requests,denied_requests FROM public.pr_youtube_quota_daily WHERE project_key=%s AND scope_key='project'", (PROJECT,)).fetchone()
        assert project == (50, 50, 73), project
        assert db.execute("SELECT coalesce(max(used_units),0) FROM public.pr_youtube_quota_daily WHERE project_key=%s AND scope_key<>'project'", (PROJECT,)).fetchone()[0] <= 2
    assert controller.snapshot(WORKSPACES[0])['workspaceUsageToday']['general']['reservedUnits'] == 2

    # Database isolation with the full fixture present, no browser credential
    # enumeration. This is not 10,000 independent Google OAuth account consent.
    for role in ('anon', 'authenticated'):
        with connection() as db:
            db.execute('SET ROLE ' + role)
            try:
                db.execute('SELECT access_ciphertext FROM public.pr_encrypted_credentials')
                raise AssertionError('Browser role enumerated creator credentials')
            except psycopg.errors.InsufficientPrivilege:
                pass
    with connection() as db:
        db.execute('SET ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000001',true)")
        visible = db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,)).fetchone()[0]
        assert visible == 1, visible
        assert db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[-1],)).fetchone() is None
    metrics['authenticatedVisibleScaleWorkspaces'] = visible
    metrics.update(status='pass', elapsedSeconds=round(time.monotonic() - started, 4),
                   fixtureProcessPeakRssKiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(metrics, separators=(',', ':')))
finally:
    with connection() as db:
        db.execute("SET LOCAL statement_timeout='60s'")
        db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,))
        db.execute('DELETE FROM public.pr_youtube_quota_daily WHERE project_key=%s', (PROJECT,))
