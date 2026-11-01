"""Scoped cloud-only real SQL/RLS controls. All Discord IO is synthetic.

No production migration, real credential, capacity workload or actual message.
"""
import copy
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the approved cloud disposable PostgreSQL harness.')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import DiscordProvider
from postriff_phase2.discord.engagement import KEY
from test_discord_engagement import EngagementWire, CHILD, POST
from test_discord_oauth_lifecycle import LifecycleWire
from test_discord_publish_authorization import APP, GUILD, FIRST, SECOND
from test_discord_rate_limits import synthetic_policy

DSN = 'host=127.0.0.1 port=55438 dbname=postgres user=postriff_test'
TOKENS, CHECKS = {}, []

@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert (db.info.host, db.info.port, db.info.dbname, db.info.user) == ('127.0.0.1', 55438, 'postgres', 'postriff_test')
        yield db

with connection() as db:
    assert int(db.execute("SELECT current_setting('server_version_num')").fetchone()[0]) // 10000 == 17
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    for name in ('124_discord_rate_limits.sql', '125_discord_service_grants.sql',
                 '126_discord_worker_projection.sql', '128_discord_lease_protocol_fence.sql'):
        db.execute((ROOT / 'migrations/postriff' / name).read_text())

def verify(token):
    if token not in TOKENS: raise AlphaError('Synthetic session required.', 401)
    return TOKENS[token]
verify.auth_time = lambda token, actor: time.time()
verify.session_id = lambda token, actor: 'synthetic-' + token

class SQLWire(EngagementWire, LifecycleWire):
    pass

class Fixture:
    def __init__(self):
        self.user, self.token = str(uuid4()), uuid4().hex
        TOKENS[self.token] = self.user
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))
            # Deliberately approve two minutes before the authoritative worker
            # DB clock. The resulting exact minute is due without mutating a
            # manifest, weakening a lease or sleeping in this harness.
            self.now = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0]) - 120
        self.wire = SQLWire()
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                                   transport=self.wire, production_reviewed=True)
        provider.authorization_v2_enabled = provider.connections_v2_enabled = True
        provider.rate_v1_enabled = provider.engagement_v1_enabled = True
        policy = synthetic_policy(time.time())
        policy.update(app_capacity=10000, invalid_capacity=1000)
        provider.rate_policy_raw = policy
        self.provider = provider
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: self.now,
            vault=CredentialVault(CredentialVault.generate_key()), providers={'discord': provider},
            public_base_url='https://rafii.example.invalid')
        self.workspace = self.service.bootstrap(self.token, 'studio')['workspaceId']
        oauth = self.service.oauth
        started = oauth.start(self.workspace, self.token, 'discord', 'identity', {'discordPurpose': 'identity', 'discoverGuilds': True})
        state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
        identity = oauth.complete(self.workspace, self.token, 'discord', state, 'identity-code')['connectionId']
        started = oauth.start(self.workspace, self.token, 'discord', 'publish',
                              {'discordPurpose': 'installation', 'identityConnectionId': identity, 'guildId': GUILD})
        state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
        self.connection = oauth.complete(self.workspace, self.token, 'discord', state, 'install-' + GUILD)['connectionId']
        oauth.choose_destination(self.workspace, self.token, self.connection, FIRST)
        self.engagement = self.service.discord_engagement
        self.destination = self.engagement.status(self.workspace, self.token, self.connection)['destinations'][0]['target']['id']
        self.social = HostedSocial(oauth, {'discord': provider})

    def grant(self, **permissions):
        status = self.engagement.status(self.workspace, self.token, self.connection)
        selected = next(d for d in status['destinations'] if d['target']['id'] == self.destination)
        return self.engagement.consent(self.workspace, self.token, self.connection,
            {'destinationId': self.destination, 'targetDigest': selected['targetDigest'], 'confirmed': True,
             'permissions': {'analytics': True, 'inbox': True, 'reply': True, **permissions}})

    def preview(self):
        return self.engagement.preview(self.workspace, self.token, self.connection,
            {'destinationId': self.destination, 'parentMessageId': CHILD, 'text': 'Exact SQL-tested reply.'})

    def approval(self, review):
        return {'reviewId': review['reviewId'], 'digest': review['digest'], 'confirmed': True}

    def approve(self, review):
        return self.engagement.approve(self.workspace, self.token, self.connection, self.approval(review))

    def worker(self):
        return PostgresWorker(connection, self.social, worker_id='engagement-' + uuid4().hex, discord_workers=True)

    def state(self):
        return self.service.repository.get(self.workspace, self.token)['state']

def denied(action):
    try: action()
    except AlphaError: return
    raise AssertionError('Expected authorization denial')

# Billing is a separate existing gate. Membership, credentials, consent, shared
# ledger, SQL locks, leases, role changes and worker/transport code are real here.
with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
    a, b = Fixture(), Fixture()
    a.grant()
    denied(lambda: a.engagement.read(a.workspace, b.token, a.connection, {'kind': 'inbox', 'destinationId': a.destination}))
    with connection() as db:
        db.execute('SET LOCAL ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (b.user,))
        db.execute("SELECT set_config('request.jwt.claim.session_id',%s,true)", ('synthetic-' + b.token,))
        assert db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=%s', (a.workspace,)).fetchone()[0] == 0
        for sql in ('SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s',
                    "UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s"):
            try:
                with db.transaction(): db.execute(sql, (a.workspace,))
            except psycopg.errors.InsufficientPrivilege: pass
            else: raise AssertionError('Browser gained service-only credential or consent write access')
    CHECKS.append('cross-tenant denial and existing credential/state RLS with real PostgreSQL')

    # A provider-side callback interleaves a committed revoke after the page GET.
    # The final gate must throw, not return data, and no next GET may occur.
    a.wire.on_page = lambda: a.grant(analytics=False, inbox=False, reply=False)
    denied(lambda: a.engagement.read(a.workspace, a.token, a.connection, {'kind': 'analytics', 'destinationId': a.destination}))
    assert not any('with_counts' in p for _, p, *_ in a.wire.calls)
    assert 'Please clarify' not in json.dumps(a.state())
    CHECKS.append('committed revoke during REST read suppresses result and subsequent requests; no provider content retained')

    f = Fixture(); f.grant(); review = f.preview()
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET role='editor',can_publish=false,can_reply=true WHERE workspace_id=%s AND user_id=%s", (f.workspace, f.user))
    gate = Barrier(2)
    def approve_once(_):
        gate.wait(timeout=8)
        try: return f.approve(review)
        except AlphaError as error:
            assert error.code == 'workspace_revision_conflict'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve_once, range(2)))
    jobs = [j for j in f.state()['phase2']['jobs'] if j['manifest'].get('operation') == 'discord.reply']
    assert len(jobs) == 1 and sum(x is not None for x in outcomes) >= 1
    assert f.approve(review)['jobId'] == jobs[0]['id']
    worker = f.worker()
    assert worker.step(discord_only=True)
    stored = f.state()['phase2']['jobs'][0]
    assert stored['state'] == 'provider_accepted' and len(stored['discordDispatchIntents']) == 1
    assert sum(method == 'POST' for method, *_ in f.wire.calls) == 1
    # This is a cloud-only real DB test: wait for the existing five-second
    # reconciliation deadline; never mutate the manifest or dispatch clock.
    with connection() as db:
        database_now = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
    time.sleep(max(0, stored['nextAt'] - database_now + .1))
    assert worker.step(discord_only=True)
    assert f.state()['phase2']['jobs'][0]['state'] == 'verified'
    CHECKS.append('two concurrent exact approvals create one durable job; can_reply without can_publish sends and verifies once through real ledger/worker')

    f = Fixture(); f.grant(); job = f.approve(f.preview()); worker = f.worker()
    claimed = worker.claim(discord_only=True); assert claimed
    claimed['discordPrepared'] = f.social.prepare_discord_dispatch(claimed['job']['manifest'], read_authorize=worker._discord_reply_read_guard(claimed))
    claimed['discordPrepared']['ratePermit'] = f.social.reserve_discord_send(claimed['job']['manifest'], job=claimed['job'], workspace_id=f.workspace, worker_id=worker.worker_id)
    f.grant(analytics=False, inbox=False, reply=False)
    assert not worker.authorize_dispatch(claimed)
    assert not any(method == 'POST' for method, *_ in f.wire.calls)
    CHECKS.append('committed consent revocation after claim blocks durable handoff and provider write')

    f = Fixture(); f.grant(); job = f.approve(f.preview()); worker = f.worker()
    claimed = worker.claim(discord_only=True); assert claimed
    with connection() as db:
        db.execute('UPDATE public.pr_memberships SET can_reply=false WHERE workspace_id=%s AND user_id=%s', (f.workspace, f.user))
        db.execute("UPDATE public.pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s", (f.workspace, f.user))
    denied(worker._discord_reply_read_guard(claimed))
    assert not worker.authorize_dispatch(claimed)
    CHECKS.append('live can_reply role removal after claim fences reads and send')

    f = Fixture(); f.grant(); job = f.approve(f.preview()); f.wire.fail_post = True
    assert f.worker().step(discord_only=True)
    stored = f.state()['phase2']['jobs'][0]
    assert stored['state'] == 'uncertain' and len(stored['discordDispatchIntents']) == 1
    denied(f.preview)
    assert sum(method == 'POST' for method, *_ in f.wire.calls) == 1
    CHECKS.append('unknown provider result retains original intent and blocks a newly approved duplicate')

print('RAFII_DISCORD_ENGAGEMENT_SQL ' + json.dumps({'status': 'PASS', 'execution': 'cloud-disposable-postgres17-synthetic-provider',
      'checks': CHECKS, 'realDiscordRequests': 0, 'productionDatabaseWrites': 0, 'billingGate': 'mocked separately'}))
