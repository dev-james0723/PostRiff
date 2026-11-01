"""Cloud-only P0 transactions and RLS. All Discord responses are synthetic.

This executable is loaded only by postriff_disposable_postgres.py. Passing it
does not establish production schema compatibility or real Discord acceptance.
"""
import copy
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the approved cloud disposable-PostgreSQL harness.')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import DiscordProvider
from postriff_phase2.discord import authorization as auth
from test_discord_publish_authorization import SyntheticWire, fixture, GUILD, APP, BOT, USER, FIRST, SECOND

DSN = 'host=127.0.0.1 port=55438 dbname=postgres user=postriff_test'
LOCAL, CHECKS, TOKENS = threading.local(), [], {}


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert (db.info.host, db.info.port, db.info.dbname, db.info.user) == ('127.0.0.1', 55438, 'postgres', 'postriff_test')
        pids = getattr(LOCAL, 'pids', None)
        if pids is not None:
            pids.put(db.info.backend_pid)
        yield db


# OAuth transaction expiry is created with PostgreSQL now(). Use that same
# clock for this real-SQL harness; the offline unit fixture's fixed future NOW
# would immediately expire a freshly created OAuth transaction here.
with connection() as db:
    NOW = int(db.execute('SELECT extract(epoch from now())').fetchone()[0]) // 60 * 60


def verify(token):
    if token not in TOKENS:
        raise AlphaError('Synthetic session required.', 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: 'synthetic-' + token
verify.auth_time = lambda token, principal: NOW


class DiscordWire(SyntheticWire):
    def __call__(self, method, url, **kwargs):
        if url == DiscordProvider.API + '/oauth2/token' and method == 'POST':
            return {'status': 200, 'body': {'access_token': 'synthetic-identity-token',
                    'scope': 'identify bot', 'guild': {'id': GUILD, 'name': 'Synthetic server'}}, 'headers': {}}
        if url == DiscordProvider.API + '/users/@me' and kwargs.get('headers', {}).get('Authorization') == 'Bearer synthetic-identity-token':
            return {'status': 200, 'body': {'id': USER}, 'headers': {}}
        if url == DiscordProvider.API + '/oauth2/token/revoke':
            return {'status': 200, 'body': {}, 'headers': {}}
        return super().__call__(method, url, **kwargs)


class Fixture:
    def __init__(self):
        self.user, self.token, self.wire = str(uuid4()), uuid4().hex, DiscordWire()
        TOKENS[self.token] = self.user
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))
        self.provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                                        transport=self.wire, production_reviewed=True)
        self.provider.authorization_v2_enabled = True
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: NOW,
                    vault=CredentialVault(CredentialVault.generate_key()), providers={'discord': self.provider},
                    public_base_url='https://rafii.example.invalid')
        self.workspace = self.service.bootstrap(self.token, 'studio')['workspaceId']
        self.oauth = self.service.oauth
        self.connection_id = self.connect()
        self.oauth.choose_destination(self.workspace, self.token, self.connection_id, FIRST)
        self.oauth.choose_destination(self.workspace, self.token, self.connection_id, SECOND)
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (self.workspace,)).fetchone()[0]
            _, _, _, variant = fixture()
            state['variants'].append(copy.deepcopy(variant))
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), self.workspace))
        self.social = HostedSocial(self.oauth, {'discord': self.provider})

    def connect(self):
        started = self.oauth.start(self.workspace, self.token, 'discord', 'publish')
        state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
        connected = self.oauth.complete(self.workspace, self.token, 'discord', state, 'synthetic-code')
        assert connected['connected']
        return connected['connectionId']

    def snapshot(self):
        return self.service.repository.get(self.workspace, self.token)

    def job(self):
        snapshot = self.snapshot()
        destination = auth.destination_id(self.workspace, self.connection_id, GUILD, FIRST)
        snapshot = self.service.repository.mutate(self.workspace, self.token, snapshot['revision'], 'p2_review',
            {'variantId': 'synthetic-draft', 'channelId': self.connection_id, 'destinationId': destination,
             'localTime': datetime.fromtimestamp(NOW + 300, timezone.utc).strftime('%Y-%m-%dT%H:%M'), 'timeZone': 'UTC', 'acknowledgedWarnings': []})
        # Keep the fixture aligned with the exact NOW + 300 future minute.
        review = snapshot['state']['phase2']['reviews'][-1]
        assert review['manifest']['timing']['timestamp'] == NOW + 300
        snapshot = self.service.repository.mutate(self.workspace, self.token, snapshot['revision'], 'p2_approve',
                 {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})
        return copy.deepcopy(snapshot['state']['phase2']['jobs'][-1])

    def worker(self, name='worker-a'):
        return PostgresWorker(connection, self.social, clock=lambda: NOW + 301, worker_id=name)

    def claim(self, job, worker=None):
        worker = worker or self.worker()
        claimed = worker.claim(workspace_id=self.workspace, job_id=job['id'],
            approval_digest=job['approvalDigest'], dispatch_principal=self.user)
        assert claimed, 'Fixture job must be claimable'
        claimed['discordPrepared'] = self.social.prepare_discord_dispatch(job['manifest'])
        return worker, claimed


def denied(action):
    try:
        action()
    except AlphaError as error:
        assert error.status in (403, 404, 409), error.status
        return
    raise AssertionError('Tenant or stale-approval operation was accepted.')


def wait_for_lock(pids, blocker):
    seen, deadline = [], time.monotonic() + 5
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
    raise AssertionError('Real PostgreSQL row-lock conflict was not observed.')


def blocked_handoff(change, label):
    f = Fixture(); job = f.job(); worker, claimed = f.claim(job)
    pids = Queue()
    def handoff():
        LOCAL.pids = pids
        try: return worker.authorize_dispatch(claimed)
        finally: LOCAL.pids = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection() as blocker:
            state = blocker.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f.workspace,)).fetchone()[0]
            future = pool.submit(handoff)
            wait_for_lock(pids, blocker.info.backend_pid)
            change(f, blocker, state, job)
            blocker.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), f.workspace))
        assert future.result(timeout=10) is False
    assert not any(call[0] == 'POST' for call in f.wire.calls)
    assert not f.snapshot()['state']['phase2']['jobs'][0].get('discordDispatchIntents')
    CHECKS.append(label)


started = time.monotonic()
with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    assert db.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='public.pr_encrypted_credentials'::regclass AND attname='authorization_generation' AND NOT attisdropped)").fetchone()[0]

# Billing is a separate gate; actual membership, RLS, row locks, encrypted grant,
# approval commands, worker and transport paths are exercised without mocking SQL.
with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
    a, b = Fixture(), Fixture(); job = a.job()
    denied(lambda: a.service.repository.get(a.workspace, b.token))
    denied(lambda: a.oauth.choose_destination(a.workspace, b.token, a.connection_id, FIRST))
    denied(lambda: a.oauth.remove_discord_destination(a.workspace, b.token, a.connection_id, job['manifest']['destinationId']))
    denied(lambda: a.service.repository.mutate(a.workspace, b.token, a.snapshot()['revision'], 'p2_approve',
                       {'reviewId': a.snapshot()['state']['phase2']['reviews'][-1]['id'], 'digest': job['approvalDigest'], 'confirmed': True}))
    denied(lambda: a.worker().execute_job(a.service.repository, a.workspace, b.token, job['id'], job['approvalDigest']))
    with connection() as db:
        db.execute('SET LOCAL ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (b.user,))
        assert db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=%s', (a.workspace,)).fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM public.pr_channels WHERE workspace_id=%s', (a.workspace,)).fetchone()[0] == 0
        for sql, params in [('UPDATE public.pr_workspaces SET state=\'{}\'::jsonb WHERE id=%s', (a.workspace,)),
                            ('SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s', (a.workspace,))]:
            try:
                with db.transaction(): db.execute(sql, params)
            except psycopg.errors.InsufficientPrivilege: pass
            else: raise AssertionError('Authenticated browser modified or read service-only state.')
    CHECKS.append('two-tenant API ownership, browser RLS and credential denial')

    worker, claimed = a.claim(job)
    a.oauth.choose_destination(a.workspace, a.token, a.connection_id, SECOND)
    assert worker.authorize_dispatch(claimed)
    receipt = a.social.submit_discord_authorized(claimed['job']['manifest'], claimed['discordDispatch'])
    assert receipt['reference'] == FIRST + '/4444444'
    assert worker.complete(claimed, receipt)
    durable = a.snapshot()['state']['phase2']['jobs'][0]
    assert len(durable['discordDispatchIntents']) == 1 and len(durable['discordReceipts']) == 1
    assert durable['manifest'] == job['manifest']
    assert 'synthetic-bot' not in json.dumps(durable) and 'accessToken' not in json.dumps(durable)
    CHECKS.append('real SQL original-default mutation regression and durable sanitized receipt')

    def remove(f, db, state, job):
        channel = next(c for c in state['phase2']['channels'] if c['id'] == f.connection_id)
        auth.revoke_destination(state, channel, job['manifest']['destinationId'], f.user, NOW + 301)
    blocked_handoff(remove, 'destination removal commits before handoff; real lock wait; zero POST')
    def edit(f, db, state, job):
        state['variants'][-1].update(text='Concurrent edit', revision=2)
    blocked_handoff(edit, 'content edit commits before handoff; real lock wait; zero POST')
    def rotate(f, db, state, job):
        db.execute('UPDATE public.pr_encrypted_credentials SET authorization_generation=gen_random_uuid() WHERE workspace_id=%s AND connection_id=%s', (f.workspace, f.connection_id))
    blocked_handoff(rotate, 'credential rotation with identical envelope blocks final handoff')
    def disconnect(f, db, state, job):
        db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (f.workspace, f.connection_id))
    blocked_handoff(disconnect, 'credential revocation blocks final handoff')

    f = Fixture(); job = f.job(); gate = threading.Barrier(8)
    def collide(index):
        worker = f.worker('worker-' + str(index)); gate.wait(timeout=10)
        claimed = worker.claim(workspace_id=f.workspace, job_id=job['id'], approval_digest=job['approvalDigest'], dispatch_principal=f.user)
        return worker, claimed
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collide, range(8)))
    winners = [(w, c) for w, c in results if c]
    assert len(winners) == 1, 'Eight concurrent workers must own one lease'
    worker, claimed = winners[0]
    claimed['discordPrepared'] = f.social.prepare_discord_dispatch(claimed['job']['manifest'])
    assert worker.authorize_dispatch(claimed)
    assert not worker.authorize_dispatch(claimed), 'A durable intent cannot be created twice'
    assert len(f.snapshot()['state']['phase2']['jobs'][0]['discordDispatchIntents']) == 1
    CHECKS.append('eight actual SQL claims; one owner and one durable intent')

    f = Fixture(); job = f.job(); worker, claimed = f.claim(job)
    assert worker.authorize_dispatch(claimed)
    receipt = f.social.submit_discord_authorized(claimed['job']['manifest'], claimed['discordDispatch'])
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f.workspace,)).fetchone()[0]
        state['phase2']['jobs'][0].update(leaseOwner='new-worker', leaseId='new-lease', leaseUntil=NOW + 900, state='uncertain')
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), f.workspace))
    assert worker.complete(claimed, receipt) is False
    current = f.snapshot()['state']['phase2']['jobs'][0]
    assert (current['leaseOwner'], current['leaseId'], current['state']) == ('new-worker', 'new-lease', 'uncertain')
    assert current['discordReceipts'][-1]['late'] and current['discordReceipts'][-1]['reference'] == FIRST + '/4444444'
    CHECKS.append('accepted late receipt retained without stealing newer lease')

print(json.dumps({'status': 'PASS', 'execution': 'cloud-disposable-postgres-synthetic-discord',
                  'checks': CHECKS, 'durationSeconds': round(time.monotonic() - started, 3),
                  'productionSchemaCompatibility': 'NOT_RUN', 'realDiscordAcceptance': 'NOT_RUN'}))
