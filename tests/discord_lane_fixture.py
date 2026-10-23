"""Real-PostgreSQL fixtures for the W-02 Discord lane: a disposable cluster, synthetic tenants, a mock Discord.

Nothing here reads application credentials or reaches a network: the cluster is started in a temporary directory from
the server binaries named by POSTRIFF_PG_BIN and listens on a unix socket only; Discord is an in-process object. The
schema is the repository's own (tests/phase2/rls.sql plus the Discord migrations 124, 126 and 128), so claims, triggers,
leases and the shared request coordinator run exactly as in production. Billing is the only boundary replaced (no
plan rows exist for synthetic tenants). Every id, name and text is synthetic.
"""
import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).resolve().parent)]
import test_discord_publish_authorization as P  # noqa: E402
from postriff_phase2.discord import lane as discord_lane  # noqa: E402
from postriff_phase2.discord.rate_limits import SharedPostgresBudget  # noqa: E402
from postriff_phase2.hosted_social import HostedSocial  # noqa: E402
from postriff_phase2.hosted_worker import PostgresWorker  # noqa: E402
from postriff_phase2.social_connectors import DiscordProvider  # noqa: E402

try:
    import psycopg
except ImportError:  # pragma: no cover - the dependency set always has it in CI
    psycopg = None

PG_BIN = os.environ.get('POSTRIFF_PG_BIN')
FENCED = '1' in (os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE'), os.environ.get('RAFII_LINKEDIN_SYNTHETIC_FENCE'))
AVAILABLE = bool(PG_BIN and psycopg and (Path(PG_BIN) / 'initdb').exists())
SKIP_FENCED = 'the synthetic transport fence refuses any database but the guarded runner\'s; these tests run in the unfenced suite'
SKIP_UNAVAILABLE = 'needs PostgreSQL server binaries (POSTRIFF_PG_BIN) and psycopg'
APP, BOT, USER, ACTOR = P.APP, P.BOT, P.USER, P.ACTOR
LANE_ENV = {'POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED': 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}
MIGRATIONS = ('124_discord_rate_limits.sql', '126_discord_worker_projection.sql', '128_discord_lease_protocol_fence.sql')


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Cluster:
    """A throwaway PostgreSQL with the repository schema; nothing else can reach it."""
    def __init__(self):
        self.runas = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else []
        self.tmp = tempfile.mkdtemp(prefix='prlane-', dir='/tmp')  # short path: unix socket names are length limited
        os.chmod(self.tmp, 0o755)
        if self.runas:
            shutil.chown(self.tmp, 'postgres', 'postgres')
        self.data, self.sock = Path(self.tmp) / 'data', Path(self.tmp) / 'sock'
        self.port = _free_port()
        self.dsn = f'host={self.sock} port={self.port} dbname=postgres' + (' user=postgres' if self.runas else '')
        try:
            self._run('mkdir', str(self.sock))
            self._run(str(Path(PG_BIN) / 'initdb'), '-D', str(self.data), '-A', 'trust', '--no-locale', '-E', 'UTF8')
            self._run(str(Path(PG_BIN) / 'pg_ctl'), '-D', str(self.data), '-l', str(Path(self.tmp) / 'postgres.log'),
                      '-o', f'-k {self.sock} -p {self.port} -h "" -c max_connections=200', '-w', 'start')
            for script in [ROOT / 'tests/phase2/rls.sql', *(ROOT / 'migrations/postriff' / name for name in MIGRATIONS)]:
                done = subprocess.run([str(Path(PG_BIN) / 'psql'), self.dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f', str(script)],
                                      cwd=script.parent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                if done.returncode:
                    raise RuntimeError(f'{script.name} failed: {done.stderr.strip()[-2000:]}')
        except BaseException:
            self.close()
            raise

    def _run(self, *args):
        done = subprocess.run([*self.runas, *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if done.returncode:
            raise RuntimeError(f'{args[0]} failed ({done.returncode}): {done.stderr.strip()}')

    def connect(self, **options):
        return psycopg.connect(self.dsn, **options)

    def factory(self, tracker=None):
        """The production factory's shape: one connection per transaction, committed on a clean exit."""
        def open_connection():
            connection = psycopg.connect(self.dsn, prepare_threshold=None)
            return tracker.wrap(connection) if tracker else connection
        return open_connection

    def now(self):
        with self.connect(autocommit=True) as db:
            return float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])

    def close(self):
        try:
            if (self.data / 'postmaster.pid').exists():
                subprocess.run([*self.runas, str(Path(PG_BIN) / 'pg_ctl'), '-D', str(self.data), '-m', 'immediate', '-w', 'stop'],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def reset(self):
        with self.connect(autocommit=True) as db:
            db.execute('TRUNCATE public.pr_discord_rate_state, public.pr_discord_route_buckets, '
                       'public.pr_discord_request_admissions')
            db.execute('DELETE FROM public.pr_worker_tenants')
            db.execute('DELETE FROM public.pr_memberships WHERE user_id=%s', (ACTOR,))
            db.execute("DELETE FROM public.pr_workspaces WHERE state ? 'phase2'")


class ConnectionTracker:
    """Counts connections open at the same time, overall and per thread."""
    def __init__(self):
        self.lock = threading.Lock()
        self.open, self.peak, self.by_thread, self.thread_peak, self.opened = 0, 0, defaultdict(int), 0, 0

    def wrap(self, connection):
        tracker = self
        with self.lock:
            self.open += 1
            self.opened += 1
            self.peak = max(self.peak, self.open)
            thread = threading.get_ident()
            self.by_thread[thread] += 1
            self.thread_peak = max(self.thread_peak, self.by_thread[thread])
        original = connection.close

        def close():
            if not connection.closed:
                with tracker.lock:
                    tracker.open -= 1
                    tracker.by_thread[thread] -= 1
            original()
        connection.close = close
        return connection


class Tenant:
    def __init__(self, index, guild=None, channel=None):
        self.id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'w02-tenant-%d.example.invalid' % index))
        self.guild = guild or str(6000000 + index)
        self.channel = channel or str(7000000 + index)


def _review(engine, state, channel, variant, tenant, at):
    """P.review with a to-the-second local time, so a test can place an approval's expiry (scheduled time + 1 h)."""
    from datetime import datetime, timezone
    payload = {'variantId': variant['id'], 'channelId': channel['id'],
               'destinationId': P.auth.destination_id(tenant.id, channel['id'], tenant.guild, tenant.channel),
               'localTime': datetime.fromtimestamp(int(at), timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
               'timeZone': 'UTC', 'acknowledgedWarnings': []}
    engine.apply_phase2(None, state, 'review', payload, {'user_id': ACTOR})
    return state['phase2']['reviews'][-1]


def build_state(tenant, count, *, now, at=None, text='Synthetic lane post'):
    """One workspace with `count` approved Discord posts, made by the real review and approval commands."""
    with patch.object(P, 'WORKSPACE', tenant.id), patch.object(P, 'NOW', now), \
            patch.object(P, 'GUILD', tenant.guild), patch.object(P, 'FIRST', tenant.channel), \
            patch.object(P, 'SECOND', str(int(tenant.channel) + 500000)):
        engine, state, channel, variant = P.fixture()
        # The production connection kind: setup age alone never holds an unchanged approval.
        channel.update(discordConnectionKind='installation', qualification='server_verified', evidenceSource='live_provider')
        state['variants'].remove(variant)
        for number in range(count):
            draft = copy.deepcopy(variant)
            draft.update(id='synthetic-draft-%d' % number, text='%s %d for %s' % (text, number, tenant.guild))
            state['variants'].append(draft)
            P.approve(engine, state, _review(engine, state, channel, draft, tenant, now + 300 if at is None else at))
    return state


def seed(cluster, tenants, count, *, now=None, at=None):
    """Insert synthetic workspaces (each with `count` due posts) and the approver's membership."""
    now = cluster.now() - 360 if now is None else now
    states = {}
    with cluster.connect() as db:
        db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (ACTOR,))
        db.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (ACTOR,))
        for tenant in tenants:
            state = build_state(tenant, count, now=now, at=at)
            states[tenant.id] = state
            db.execute('INSERT INTO public.pr_workspaces(id,revision,state) VALUES(%s,1,%s::jsonb)',
                       (tenant.id, json.dumps(state)))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply) "
                       "VALUES(%s,%s,'owner','active',true,true)", (tenant.id, ACTOR))
    return states


def nonce(job):
    """The create's nonce, as the sender derives it: one approval, one nonce."""
    return hashlib.sha256(job['manifest']['idempotencyKey'].encode()).hexdigest()[:25]


def jobs(cluster):
    with cluster.connect(autocommit=True) as db:
        rows = db.execute("SELECT id::text,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall()
    return {(workspace, job['id']): job for workspace, state in rows for job in state['phase2']['jobs']}


class Grants:
    """The worker's credential read for every synthetic tenant; no provider I/O, like the real one."""
    def __init__(self, tenants):
        self.by_workspace = {tenant.id: tenant for tenant in tenants}

    def discord_grant_for_worker(self, workspace, connection, *, cur=None):
        tenant = self.by_workspace.get(workspace)
        if tenant is None or connection != 'discord-connection':
            raise P.AlphaError('Synthetic grant unavailable.', 409)
        return {'provider': 'discord', 'scopes': ['bot', 'identify'], 'authorizationGeneration': P.GENERATION,
                'accessToken': json.dumps({'v': 2, 'guild': tenant.guild, 'user': USER, 'channel': tenant.channel,
                                           'applicationId': APP, 'botUserId': BOT})}


class MockDiscord:
    """Discord as the coordinator sees it. In-process; records every request.

    Each route answers with bucket headers (a create: five per channel per five seconds, like a bot's channel limit;
    reads: fifty per second per route and resource). A request over a bucket gets a 429. `ceiling` counts (it does
    not refuse) requests beyond that many in any trailing second. `fail` lets a test answer a request itself.
    """
    LIMITS = {'create': (5, 5.0)}

    def __init__(self, tenants, *, latency=0.0, ceiling=None, read_limit=(50, 1.0), clock=time.monotonic, sleep=time.sleep):
        self.tenants = {tenant.guild: tenant for tenant in tenants}
        self.channels = {tenant.channel: tenant for tenant in tenants}
        self.latency, self.ceiling, self.read_limit, self.clock, self.sleep = latency, ceiling, read_limit, clock, sleep
        self.lock = threading.Lock()
        self.calls, self.creates, self.messages, self.windows = [], defaultdict(list), {}, {}
        self.recent, self.over_ceiling, self.peak_second, self.route429 = [], 0, 0, 0
        self.fail = self.after = None  # fail(method, path) may answer or raise; after(method, path, answer) may raise
        self.sequence = 900000000000000000

    def _bucket(self, name, major, limit, window, now):
        start, used = self.windows.get((name, major), (now, 0))
        if now >= start + window:
            start, used = now, 0
        if used >= limit:
            return False, {'x-ratelimit-bucket': name, 'x-ratelimit-limit': str(limit), 'x-ratelimit-remaining': '0',
                           'x-ratelimit-reset-after': '%.3f' % (start + window - now), 'x-ratelimit-scope': 'user',
                           'retry-after': '%.3f' % max(.001, start + window - now)}
        self.windows[(name, major)] = (start, used + 1)
        return True, {'x-ratelimit-bucket': name, 'x-ratelimit-limit': str(limit),
                      'x-ratelimit-remaining': str(limit - used - 1),
                      'x-ratelimit-reset-after': '%.3f' % max(.001, start + window - now)}

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        path = url.removeprefix(DiscordProvider.API)
        if self.latency:
            self.sleep(self.latency)
        with self.lock:
            now = self.clock()
            self.recent = [t for t in self.recent if t > now - 1.0] + [now]
            self.peak_second = max(self.peak_second, len(self.recent))
            if self.ceiling is not None and len(self.recent) > self.ceiling:
                self.over_ceiling += 1
            self.calls.append((now, method, path))
            if self.fail is not None:
                answer = self.fail(method, path)
                if answer is not None:
                    return answer
            answer = self._answer(method, path, body, now)
        if self.after is not None:
            self.after(method, path, answer)
        return answer

    def _answer(self, method, path, body, now):
        parts = path.strip('/').split('/')
        permissions = str(DiscordProvider.PERMISSIONS | DiscordProvider.MANAGE_GUILD)
        if method == 'POST' and len(parts) == 3 and parts[0] == 'channels' and parts[2] == 'messages':
            ok, headers = self._bucket('create', parts[1], *self.LIMITS['create'], now)
            if not ok:
                self.route429 += 1
                return {'status': 429, 'headers': headers, 'body': {'message': 'You are being rate limited.',
                                                                    'retry_after': float(headers['retry-after']), 'global': False}}
            self.sequence += 1
            message = {'id': str(self.sequence), 'channel_id': parts[1], 'content': (body or {}).get('content'),
                       'author': {'id': BOT, 'bot': True}, 'mention_everyone': False, 'mentions': [],
                       'mention_roles': [], 'attachments': []}
            self.messages[message['id']] = message
            self.creates[(body or {}).get('nonce')].append((now, parts[1], time.time()))
            return {'status': 200, 'headers': headers, 'body': message}
        major = parts[1] if len(parts) > 1 else 'none'
        # Discord bucket ids are opaque [A-Za-z0-9_-] strings; the coordinator holds a route on anything else.
        template = method + ':' + '/'.join(p if not p.isdigit() else '{id}' for p in parts)
        ok, headers = self._bucket(hashlib.sha256(template.encode()).hexdigest()[:20], major, *self.read_limit, now)
        if not ok:
            self.route429 += 1
            return {'status': 429, 'headers': headers, 'body': {'message': 'You are being rate limited.',
                                                                'retry_after': float(headers['retry-after']), 'global': False}}
        if path == '/oauth2/applications/@me':
            result = {'id': APP}
        elif path == '/users/@me':
            result = {'id': BOT, 'bot': True}
        elif parts[0] == 'guilds' and parts[1] in self.tenants:
            guild = parts[1]
            if len(parts) == 2:
                result = {'id': guild, 'name': 'Synthetic server', 'owner_id': '1000001',
                          'roles': [{'id': guild, 'permissions': permissions}]}
            elif len(parts) == 4 and parts[2] == 'members' and parts[3] in (BOT, USER):
                result = {'user': {'id': parts[3]}, 'roles': [], 'pending': False, 'communication_disabled_until': None}
            elif len(parts) == 3 and parts[2] == 'channels':
                result = [{'id': self.tenants[guild].channel, 'guild_id': guild, 'name': 'synthetic', 'type': 0,
                           'permission_overwrites': []}]
            else:
                return {'status': 404, 'headers': headers, 'body': {'message': 'Unknown'}}
        elif method == 'GET' and len(parts) == 4 and parts[0] == 'channels' and parts[3] in self.messages:
            result = self.messages[parts[3]]
        else:
            return {'status': 404, 'headers': headers, 'body': {'message': 'Unknown'}}
        return {'status': 200, 'headers': headers, 'body': result}

    def duplicates(self):
        return sum(len(times) - 1 for times in self.creates.values() if len(times) > 1)

    def requests(self, *, method=None):
        return [call for call in self.calls if method is None or call[1] == method]


def policy(now, *, capacity=25, **overrides):
    import importlib.util
    spec = importlib.util.spec_from_file_location('discord_rate_policy', ROOT / 'scripts/discord_rate_policy.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return json.dumps(tool.build(now, days=1, revision='w02-lane-test', app_capacity=capacity, **overrides))


def social(cluster, tenants, wire, *, capacity=25, tracker=None, **policy_overrides):
    provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot-token', 'https://rafii.example.invalid',
                               transport=wire, production_reviewed=True)
    provider.authorization_v2_enabled = provider.connections_v2_enabled = provider.rate_v1_enabled = True
    provider.rate_limiter = SharedPostgresBudget(cluster.factory(tracker), APP,
                                                 policy=policy(cluster.now(), capacity=capacity, **policy_overrides))
    return HostedSocial(Grants(tenants), {'discord': provider})


def base_worker(cluster, hosted, tracker=None, name='w02-base'):
    return PostgresWorker(cluster.factory(tracker), social=hosted, worker_id=name, discord_workers=True)


@contextmanager
def no_billing():
    with patch('postriff_phase2.billing.require_publishing', return_value=None):
        yield


def run_lanes(worker, count, *, seconds=20, steps=5000, env=None, crash=None, sleep=time.sleep):
    """`count` concurrent lane invocations (one per shard), as K cron entries would start them."""
    values = {**LANE_ENV, 'POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS': str(seconds),
              'POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_STEPS': str(steps), **(env or {})}
    results, failures = [None] * count, []
    start = threading.Barrier(count, timeout=60)

    def one(number):
        try:
            start.wait()
            results[number] = discord_lane.run(worker, number, values, sleep=sleep)
        except BaseException as error:  # a crash a test injected, or a real failure the test reports
            failures.append((number, error))

    threads = [threading.Thread(target=one, args=(n,)) for n in range(count)]
    with no_billing():
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=seconds + 200)
    return results, failures
