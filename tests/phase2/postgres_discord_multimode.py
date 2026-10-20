"""Disposable PostgreSQL custody/replay/RLS candidate. Synthetic Discord only."""
import json
import os
import runpy
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the approved Linux disposable PostgreSQL harness; never a hosted DSN.')
root = Path(__file__).resolve().parents[2]
# Existing P0–P3 chain once, on its strictly fenced loopback database.
prior = runpy.run_path(str(Path(__file__).with_name('postgres_discord_worker.py')))
base = prior['base']; connection = base['connection']
connection.bounded = lambda _timeout: connection()  # same fenced loopback harness, no hosted DSN
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.interactions import DiscordInteractions
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_multimode import HookWire, APP, USER, GUILD, FIRST, HOOK, SECRET
from test_discord_oauth_lifecycle import LifecycleWire

with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    db.execute((root / 'migrations/postriff/124_discord_rate_limits.sql').read_text())
    db.execute((root / 'migrations/postriff/125_discord_service_grants.sql').read_text())
    db.execute((root / 'migrations/postriff/131_discord_interactions.sql').read_text())
    now = float(db.execute('SELECT extract(epoch from now())').fetchone()[0])
checks = []

class Wire(LifecycleWire):
    def __init__(self):
        super().__init__(); self.hooks = HookWire()
    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path.removeprefix('/api/v10')
        if path.startswith('/webhooks/'): return self.hooks(method, url, **kwargs)
        if path == '/oauth2/token' and kwargs.get('form', {}).get('code') == 'webhook-code':
            assert len(kwargs['form']['code_verifier']) >= 43
            self.tokens['synthetic-webhook-bearer'] = ['identify']
            return {'status': 200, 'body': {'access_token': 'synthetic-webhook-bearer', 'token_type': 'Bearer', 'expires_in': 3600,
                'scope': 'webhook.incoming', 'webhook': {'id': HOOK, 'token': SECRET, 'type': 1, 'application_id': APP, 'guild_id': GUILD, 'channel_id': FIRST}}}
        return super().__call__(method, url, **kwargs)

actor, token = str(uuid4()), uuid4().hex
base['TOKENS'][token] = actor
with connection() as db: db.execute('INSERT INTO auth.users(id) VALUES(%s)', (actor,))
wire = Wire()
provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=wire, production_reviewed=True)
provider.authorization_v2_enabled = provider.connections_v2_enabled = provider.webhook_v1_enabled = True
service = HostedWorkspaceService(connection, base['verify'], clock=lambda: now, vault=CredentialVault(CredentialVault.generate_key()), providers={'discord': provider}, public_base_url='https://rafii.example.invalid')
workspace = service.bootstrap(token, 'studio')['workspaceId']; oauth = service.oauth

def begin(purpose, **kwargs):
    started = oauth.start(workspace, token, 'discord', 'identity' if purpose == 'identity' else 'publish', {'discordPurpose': purpose, **kwargs})
    return parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]

pending = begin('webhook', channelId=FIRST)
result = oauth.complete(workspace, token, 'discord', pending, 'webhook-code', iss='https://discord.com')
hook_connection = result['connectionId']
with connection() as db:
    credential = db.execute('SELECT access_ciphertext,key_id,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (workspace, hook_connection)).fetchone()
    envelope = json.loads(oauth.vault.decrypt(credential[0], credential[1]))
assert envelope['kind'] == 'webhook' and envelope['secret'] == SECRET and envelope['workspaceId'] == workspace
assert envelope['authorization']['bearerScopes'] == ['identify'] and 'webhook.incoming' in credential[2]
assert SECRET not in json.dumps(oauth.channels(workspace, token))
try: oauth.complete(workspace, token, 'discord', pending, 'webhook-code', iss='https://discord.com')
except AlphaError: pass
else: raise AssertionError('replayed callback accepted')
assert not wire.hooks.message
assert oauth.channels(workspace, token)['channels'][0]['capabilities']['publish']['level'] == 'Unsupported'
oauth.choose_destination(workspace, token, hook_connection, FIRST)
assert oauth.channels(workspace, token)['channels'][0]['capabilities']['publish']['level'] == 'Direct'
checks.append('single-use OAuth, independent proof, encrypted custody, no message, separate destination consent')

identity = oauth.complete(workspace, token, 'discord', begin('identity'), 'identity-code')['connectionId']
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
key = Ed25519PrivateKey.generate()
provider.user_install_v1_enabled = True
provider.interaction_config_raw = {'applicationId': APP, 'publicKey': key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex(),
    'commandId': '88112233', 'commandVersion': '77112233', 'commandName': 'rafii-drafts', 'integrationTypes': [1], 'contexts': [1, 2],
    'qualified': True, 'endpoint': 'https://rafii.example.invalid/api/discord/interactions'}
endpoint = DiscordInteractions(provider, connection, oauth.public_base_url, clock=lambda: now)
endpoint.bind(oauth.discord_connections, workspace, token, identity)
assert endpoint.resolve(USER) == [{'workspaceId': workspace, 'memberId': actor, 'identityId': identity}]
packet = {'id': '99112234', 'application_id': APP, 'type': 2, 'context': 2, 'user': {'id': USER},
          'authorizing_integration_owners': {'1': USER}, 'data': {'id': '88112233', 'type': 1, 'name': 'rafii-drafts'},
          'token': 'synthetic-never-retained'}
raw = json.dumps(packet).encode(); timestamp = str(int(now))
response = endpoint.receive(raw, timestamp, key.sign(timestamp.encode() + raw).hex())
assert response['data']['flags'] == 64 and '/app/queue/discord?' in response['data']['content']
assert 'synthetic-never-retained' not in json.dumps(response)
with ThreadPoolExecutor(max_workers=2) as pool:
    outcomes = list(pool.map(lambda _: endpoint.claim(APP, '99112233'), range(2)))
assert sorted(outcomes) == [False, True]
checks.append('persistent explicit mapping and concurrent unique replay claim')

foreign, foreign_token = str(uuid4()), uuid4().hex
base['TOKENS'][foreign_token] = foreign
with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (foreign,))
other_workspace = service.bootstrap(foreign_token, 'studio')['workspaceId']
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'admin','active')", (workspace, foreign))
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'admin','active')", (other_workspace, actor))
try: endpoint.bind(oauth.discord_connections, workspace, foreign_token, identity)
except AlphaError: pass
else: raise AssertionError('another member adopted private identity')
for role in ('anon', 'authenticated'):
    for table in ('pr_discord_interaction_links', 'pr_discord_interaction_replays'):
        try:
            with connection() as db:
                db.execute('SET LOCAL ROLE ' + role)
                db.execute('SELECT * FROM public.' + table)
        except base['psycopg'].errors.InsufficientPrivilege: pass
        else: raise AssertionError('private table exposed to browser role')
try: oauth.discord_grant_for_worker(other_workspace, hook_connection)
except AlphaError: pass
else: raise AssertionError('same actor borrowed foreign-workspace webhook custody')
checks.append('foreign member, same-actor foreign workspace and browser-role SQL isolation')

oauth.discord_connections.disconnect_identity(workspace, token, identity)
assert endpoint.resolve(USER) == []
oauth.disconnect(workspace, token, hook_connection)
try: oauth.discord_grant_for_worker(workspace, hook_connection)
except AlphaError: pass
else: raise AssertionError('revoked webhook credential returned')
assert not wire.hooks.message
checks.append('disconnect invalidates mappings and custody without remote mutation')
print('RAFII_DISCORD_MULTIMODE_SQL_JSON ' + json.dumps({'status': 'PASS', 'execution': 'disposable-postgres-synthetic-provider', 'checks': checks, 'realDiscordAcceptance': 'NOT_RUN'}))

# Exercise the new webhook lane against the actual PostgreSQL admission and
# worker schema, not MemoryDatabase/MemoryLedger. Provider HTTP remains synthetic.
import copy
import hashlib
import time
from contextlib import contextmanager
from threading import Barrier, Lock
from unittest.mock import patch
from postriff_phase2.discord.rate_limits import SharedPostgresBudget
from test_discord_rate_limits import synthetic_policy

@contextmanager
def worker_connection():
    with connection() as db:
        db.execute('SET LOCAL ROLE service_role')
        assert db.execute('SELECT current_user').fetchone()[0] == 'service_role'
        yield db

class QualifiedWire(Wire):
    def __init__(self):
        super().__init__()
        self.mode = 'normal'
        self.post_count = 0
        self.post_lock = Lock()
    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path.removeprefix('/api/v10')
        if self.mode == 'permission_removed' and path == '/guilds/' + GUILD + '/members/' + USER:
            response = {'status': 404, 'body': {}}
        elif method == 'POST' and path.startswith('/webhooks/'):
            with self.post_lock:
                self.post_count += 1
            if self.mode == 'unknown':
                raise TimeoutError('Synthetic ambiguous webhook acceptance')
            if self.mode == '429':
                return {'status': 429, 'headers': {'X-RateLimit-Bucket':'synthetic-hook-rate', 'X-RateLimit-Scope':'shared', 'Retry-After':'60'}, 'body':{'retry_after':60,'global':False}}
            response = super().__call__(method, url, **kwargs)
        else:
            response = super().__call__(method, url, **kwargs)
        response['headers'] = {'X-RateLimit-Bucket': hashlib.sha256((method+path).encode()).hexdigest(),
            'X-RateLimit-Limit':'1000', 'X-RateLimit-Remaining':'999', 'X-RateLimit-Reset-After':'60'}
        return response


def webhook_worker_fixture(label):
    f = base['Fixture']()
    w = QualifiedWire()
    f.provider.connections_v2_enabled = f.provider.webhook_v1_enabled = True
    f.provider.transport = w
    request = f.oauth.start(f.workspace, f.token, 'discord', 'publish', {'discordPurpose':'webhook', 'channelId':FIRST})
    state_value = parse_qs(urlsplit(request['authorizeUrl']).query)['state'][0]
    result = f.oauth.complete(f.workspace, f.token, 'discord', state_value, 'webhook-code', iss='https://discord.com')
    f.connection_id = result['connectionId']
    f.oauth.choose_destination(f.workspace, f.token, f.connection_id, FIRST)
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f.workspace,)).fetchone()[0]
        state['variants'][-1]['text'] = 'Synthetic webhook SQL acceptance ' + label
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state),f.workspace))
    job = f.job()
    with connection() as db:
        now = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
    policy = synthetic_policy(now)
    policy.update(app_capacity=1000,invalid_capacity=100,failure_threshold=5,permit_ttl_seconds=15,
                  revision='synthetic-webhook-sql-'+label,egress_scope='synthetic-webhook-sql-'+label)
    f.provider.rate_limiter = SharedPostgresBudget(worker_connection, APP, policy=policy)
    f.provider.rate_v1_enabled = True
    f.provider.rate_coordinator_degraded = False
    return f, w, job


def actual_job(f, job):
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (f.workspace,)).fetchone()[0]
        return next(j for j in state['phase2']['jobs'] if j['id'] == job['id'])


def close_case(f, job):
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f.workspace,)).fetchone()[0]
        current = next(j for j in state['phase2']['jobs'] if j['id'] == job['id'])
        # Preserve frozen authority, intents, admissions and receipts. Only keep
        # finished test work out of later deliberately unscoped worker ticks.
        current.update(state='held',leaseOwner=None,leaseUntil=0)
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state),f.workspace))

sql_worker_cases = []
with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
    for scenario in ('concurrent', 'canceled', 'revoked', 'permission_removed', 'unknown', '429'):
        f, transport, approved = webhook_worker_fixture(scenario)
        worker = base['PostgresWorker'](worker_connection, f.social, clock=time.time,
                                       worker_id='multimode-sql-'+scenario, discord_workers=True)
        if scenario == 'canceled':
            current = f.snapshot()
            f.service.repository.mutate(f.workspace, f.token, current['revision'], 'p2_cancel', {'jobId':approved['id']})
        elif scenario == 'revoked':
            f.oauth.disconnect(f.workspace, f.token, f.connection_id)
        elif scenario == 'permission_removed':
            transport.mode = 'permission_removed'
        elif scenario in ('unknown','429'):
            transport.mode = scenario
        if scenario == 'concurrent':
            barrier = Barrier(3)
            def tick(index):
                peer = base['PostgresWorker'](worker_connection, f.social, clock=time.time,
                                             worker_id='multimode-collision-'+str(index), discord_workers=True)
                barrier.wait(timeout=10)
                return peer.tick_discord(max_jobs=1)
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(tick, range(3)))
        else:
            worker.tick_discord(max_jobs=1)
        worker.tick_discord(max_jobs=1)
        saved = actual_job(f, approved)
        assert saved['manifest'] == approved['manifest'] and saved['approvalDigest'] == approved['approvalDigest']
        if scenario == 'concurrent':
            assert saved['state'] == 'verified', (scenario,saved['state'])
            assert transport.post_count == 1
        elif scenario in ('canceled','revoked','permission_removed'):
            assert transport.post_count == 0, scenario
            assert saved['state'] in ('canceled','held'), (scenario,saved['state'])
        elif scenario == 'unknown':
            assert transport.post_count == 1 and saved['state'] == 'uncertain', (scenario,saved['state'])
        else:
            assert transport.post_count == 1, (scenario,transport.post_count,saved['state'])
            assert saved['state'] != 'verified'
            assert saved.get('nextAt',0) > time.time() or saved['state'] in ('held','uncertain')
        with connection() as db:
            rows = db.execute('SELECT credential_kind,state,intent_id,workspace_id::text,publication_id FROM public.pr_discord_request_admissions WHERE workspace_id=%s AND publication_id=%s AND method=%s', (f.workspace,approved['id'],'POST')).fetchall()
        if transport.post_count:
            assert len(rows) == 1 and rows[0][0] == 'webhook' and rows[0][2], (scenario,rows)
            assert len(saved.get('discordDispatchIntents',[])) == 1
        assert SECRET not in json.dumps(saved) and SECRET not in json.dumps(rows)
        sql_worker_cases.append({'scenario':scenario,'state':saved['state'],'webhookPosts':transport.post_count,
            'sqlAdmissions':len(rows),'executionRole':'service_role','frozenApprovalPreserved':True})
        close_case(f, approved)
print('RAFII_DISCORD_MULTIMODE_WORKER_SQL_JSON ' + json.dumps({'status':'PASS','execution':'real-postgres-service-role-synthetic-provider','cases':sql_worker_cases,'realDiscordAcceptance':'NOT_RUN'}))
