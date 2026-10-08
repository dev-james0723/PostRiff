"""Cloud disposable SQL concurrency/RLS/fairness acceptance. Synthetic, no Google."""
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_phase2.youtube.capacity import CapacityPolicy, CapacityController
from postriff_phase2.youtube.model import YouTubeError
from postriff_phase2.hosted_worker import PostgresWorker

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
PROJECT = 'synthetic-capacity-' + str(uuid4())
WORKSPACES = [str(uuid4()), str(uuid4())]
FAIR = ['00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000102']
NOW = 1800000000


def connection():
    return psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5)


with connection() as db:
    db.execute((ROOT / 'migrations/postriff/097_youtube_capacity.sql').read_text())
    db.execute((ROOT / 'migrations/postriff/097_youtube_capacity.sql').read_text())
    for wid in WORKSPACES + FAIR:
        db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (wid,))
    for wid in WORKSPACES:
        db.execute("""INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes)
            VALUES(%s,'synthetic-connection','youtube',%s,'synthetic-encrypted','synthetic-key','{}')""", (wid, 'UC' + ('a' if wid == WORKSPACES[0] else 'b') * 22))

policy = CapacityPolicy(PROJECT, {'videoUploads': 5, 'search': 100, 'general': 10000},
                        {'videoUploads': 3, 'search': 20, 'general': 2000}, requests_per_minute=120)
controller = CapacityController(connection, policy, clock=lambda: NOW)


def reserve(index):
    wid = WORKSPACES[index % 2]
    try:
        controller.record(wid, 'synthetic-connection', 'videos.insert', 'videoUploads', 1)
        return wid, True
    except YouTubeError as error:
        assert error.category == 'capacity_delay' and error.retry_at > NOW
        return wid, False


try:
    with ThreadPoolExecutor(max_workers=6) as pool:
        attempts = list(pool.map(reserve, range(12)))
    assert sum(ok for _, ok in attempts) == 5, attempts
    assert all(sum(ok and wid == target for wid, ok in attempts) <= 3 for target in WORKSPACES)
    with connection() as db:
        project = db.execute('SELECT used_units,admitted_requests,denied_requests FROM public.pr_youtube_quota_daily WHERE project_key=%s AND scope_key=\'project\' AND bucket=\'videoUploads\'', (PROJECT,)).fetchone()
        assert project == (5, 5, 7), project
        assert db.execute('SELECT sum(estimated_units),count(*) FILTER(WHERE admitted),count(*) FILTER(WHERE NOT admitted) FROM public.pr_youtube_usage WHERE project_key=%s', (PROJECT,)).fetchone() == (5, 5, 7)
    own = controller.snapshot(WORKSPACES[0])['workspaceUsageToday']['videoUploads']
    assert own['admittedRequests'] == sum(ok and wid == WORKSPACES[0] for wid, ok in attempts)
    assert own['delayedRequests'] == sum(not ok and wid == WORKSPACES[0] for wid, ok in attempts)

    rate = CapacityController(connection, replace(policy, project_key=PROJECT + '-rate', requests_per_minute=2), clock=lambda: NOW)
    for _ in range(2): rate.record(WORKSPACES[0], 'synthetic-connection', 'resumable.status', 'videoUploads', None)
    try:
        rate.record(WORKSPACES[0], 'synthetic-connection', 'resumable.status', 'videoUploads', None)
        raise AssertionError('Rate admission was bypassed')
    except YouTubeError as error:
        assert error.capacity_reason == 'workspace_rate'
    # Independent tenant retains its own rate allowance.
    rate.record(WORKSPACES[1], 'synthetic-connection', 'resumable.status', 'videoUploads', None)

    # Initial OAuth discovery has no persisted channel connection yet. Reserve
    # durable general quota without fabricating a connection-linked usage row.
    identity_policy = replace(policy, project_key=PROJECT + '-identity',
                              limits={'videoUploads': 5, 'search': 100, 'general': 2},
                              workspace_limits={'videoUploads': 3, 'search': 20, 'general': 2})
    identity = CapacityController(connection, identity_policy, clock=lambda: NOW)
    for _ in range(2): identity.record_identity(WORKSPACES[0])
    try:
        identity.record_identity(WORKSPACES[0])
        raise AssertionError('OAuth identity discovery bypassed project capacity')
    except YouTubeError as error:
        assert error.capacity_reason == 'project_daily'
    with connection() as db:
        assert db.execute("SELECT used_units,admitted_requests,denied_requests FROM public.pr_youtube_quota_daily WHERE project_key=%s AND scope_key='project' AND bucket='general'", (PROJECT + '-identity',)).fetchone() == (2, 2, 1)
        assert db.execute('SELECT count(*) FROM public.pr_youtube_usage WHERE project_key=%s', (PROJECT + '-identity',)).fetchone()[0] == 0
    assert identity.snapshot(WORKSPACES[0])['workspaceUsageToday']['general'] == {
        'reservedUnits': 2, 'admittedRequests': 2, 'delayedRequests': 1}

    for role in ('anon', 'authenticated'):
        for table in ('pr_youtube_quota_daily', 'pr_youtube_rate_windows', 'pr_worker_tenants'):
            with connection() as db:
                db.execute('SET ROLE ' + role)
                try:
                    db.execute('SELECT * FROM public.' + table)
                    raise AssertionError('Browser role could read server admission state')
                except psycopg.errors.InsufficientPrivilege:
                    pass

    # Actual worker SQL selects the other due tenant after the first dispatch,
    # regardless of restarted worker ID. Provider/billing/approval are not invoked.
    with connection() as db:
        for index, wid in enumerate(FAIR):
            state = {'phase2': {'channels': [], 'jobs': [{'id': 'synthetic-job-' + str(index), 'state': 'processing',
                      'manifest': {'platform': 'LinkedIn'}, 'events': [], 'nextAt': 0, 'leaseUntil': 0}]}}
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), wid))
    worker = PostgresWorker(connection, clock=lambda: NOW)
    worker.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda _: None))
    first = worker.claim()
    assert first['workspaceId'] == FAIR[0], first
    restarted = PostgresWorker(connection, clock=lambda: NOW)
    restarted.commands = worker.commands
    second = restarted.claim()
    assert second['workspaceId'] == FAIR[1], second

    # Simulate an unapplied097 dispatch table in this disposable cluster only.
    # Existing non-YouTube readback continues; YouTube has no lease or attempt.
    with connection() as db:
        missing_schema_state = {'phase2': {'channels': [], 'jobs': [
            {'id': 'youtube-preserved', 'state': 'processing', 'manifest': {'platform': 'YouTube'}, 'events': [], 'attempts': []},
            {'id': 'linkedin-continues', 'state': 'processing', 'manifest': {'platform': 'LinkedIn'}, 'events': []}]}}
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(missing_schema_state), FAIR[0]))
        db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (FAIR[1],))
        db.execute('ALTER TABLE public.pr_worker_tenants RENAME TO pr_worker_tenants_capacity_fixture')
    try:
        fallback = PostgresWorker(connection, clock=lambda: NOW)
        fallback.commands = worker.commands
        continued = fallback.claim()
        assert continued['job']['id'] == 'linkedin-continues', continued
        assert fallback.capacity_intervention['youtubeDispatch'] == 'paused'
        with connection() as db:
            preserved = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (FAIR[0],)).fetchone()[0]['phase2']['jobs'][0]
            assert preserved['state'] == 'processing' and preserved['attempts'] == [] and 'leaseId' not in preserved
            assert preserved['nextAt'] == NOW + 60 and preserved['capacityIntervention']['code'] == 'youtube_capacity_schema'
    finally:
        with connection() as db:
            db.execute('ALTER TABLE public.pr_worker_tenants_capacity_fixture RENAME TO pr_worker_tenants')

    # Tenant deletion purges its private counters but cannot refund consumed
    # project capacity or let another tenant repeat those uploads.
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[0],))
        assert db.execute('SELECT count(*) FROM public.pr_youtube_quota_daily WHERE workspace_id=%s', (WORKSPACES[0],)).fetchone()[0] == 0
        assert db.execute('SELECT used_units FROM public.pr_youtube_quota_daily WHERE project_key=%s AND scope_key=\'project\' AND bucket=\'videoUploads\'', (PROJECT,)).fetchone()[0] == 5
    print('PASS: synthetic atomic concurrent admission, preconnection identity budget, denial metering, isolated rates, server-only RLS, durable fair worker claim, missing097 platform isolation and deletion without quota refund. No real Google calls or load acceptance.')
finally:
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES + FAIR,))
        db.execute('DELETE FROM public.pr_youtube_quota_daily WHERE project_key IN (%s,%s,%s)', (PROJECT, PROJECT + '-rate', PROJECT + '-identity'))
