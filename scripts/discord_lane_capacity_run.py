#!/usr/bin/env python3
"""W-02 Discord lane capacity harness: real time, separate OS processes, real application code.

What runs (all on this machine, synthetic data only, no network beyond 127.0.0.1):

  PostgreSQL   a throwaway cluster from --pg-bin (or an external one: --admin-database-url for setup and sampling,
               --database-url for the application, e.g. PostgreSQL 17 behind a real pooler on CI), with the tested
               tree's own production migration set (scripts/discord_lane_cap_cluster.py).
  pooler       scripts/discord_lane_cap_pooler.py: transaction-mode pool of --max-db-connections server connections,
               --db-latency-ms per round trip, connection setup round trips; measures waits, holds, SQLSTATEs.
  mock Discord scripts/discord_lane_cap_mock.py: the routes the sender uses, latency distribution, hard global ceiling
               of 50/s (429 global above it), per-channel create buckets, nonce and post-id duplicate counting,
               isolation check, failure injections, full request log.
  seeding      scripts/discord_lane_cap_seed.py: workspaces, Discord identity + installation + authorized channel,
               approved scheduled posts, all made by the application's own commands.
  system       scripts/discord_lane_cap_invoke.py: every cron invocation is a fresh OS process that imports the
  under test   tested tree's api/index.py and serves one GET /api/cron/discord-worker/<n> or /api/cron/worker
               through the WSGI app with the cron secret, every --cron-period-seconds (60, as Vercel), each up to its
               own budget, killed at the function limit (300 s), sharing nothing with any other invocation.
  analysis     scripts/discord_lane_cap_analysis.py: JSON and a Markdown receipt against docs/w02/capacity-standard.json,
               with every way this run differs from production stated first.

  nice -n 10 python3 scripts/discord_lane_capacity_run.py run --scenario S1 --source-tree TREE --out DIR
  python3 scripts/discord_lane_capacity_run.py profile --name release --source-tree TREE --out DIR
  python3 scripts/discord_lane_capacity_run.py analyze RUN_DIR
  python3 scripts/discord_lane_capacity_run.py scenarios

Use the project's Python with psycopg (e.g. /opt/prvenv/bin/python); POSTRIFF_PG_BIN names the server binaries.
"""
import argparse
import copy
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
SCRIPTS = HARNESS / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import discord_lane_cap_analysis as analysis  # noqa: E402
import discord_lane_cap_cluster as cluster_tools  # noqa: E402
import discord_lane_cap_mock as mock_tools  # noqa: E402

STANDARD = HARNESS / 'docs/w02/capacity-standard.json'
ACTIVE = []
PRESPAWN_SECONDS = 8.0

# --- scenarios -----------------------------------------------------------------------------------------------------
# Times in injections, stalls and kills are minutes (or seconds where named) relative to the due time T.
BASE = dict(workspaces=2000, posts=5000, hot_posts=0, per_minute=0, minutes=0, due_second_jitter_share=0.0,
            lane=True, lane_max_seconds=50, lane_max_steps=None, shards=None, minute_worker=True,
            worker_max_jobs=25, worker_max_seconds=40, policy_capacity=25, information_only=False,
            mock_latency='uniform:50:150', mock_tail_probability=0.0, mock_tail_ms=0.0, mock_read_limit='50:1',
            double_accept_every=0, db_latency_ms=2.0, db_connect_rtts=4, max_db_connections=20,
            max_client_connections=200, pool_wait_timeout=60.0, db_statement_timeout_ms=0,
            cron_period=60, cron_jitter=(0.0, 1.0), max_duration=300, invocation_mode='cold',
            lead_seconds=90, max_run_minutes=75, fixed_run_minutes=None, stall_detect_minutes=10,
            stall=None, flag_off=None, kills=None, kill_at_create=0, lock_injection=None, misroute_every=0,
            expiry_in_minutes=None, injections=None, seed_processes=4, expect=())

SCENARIOS = {
    'smoke': dict(workspaces=10, posts=30, cron_period=20, lane_max_seconds=15, shards=4, lead_seconds=10,
                  max_run_minutes=4, seed_processes=1, stall_detect_minutes=2,
                  description='Tiny end-to-end check of the harness itself: 30 posts in 10 workspaces, 20-second '
                              'cron period, 4 shards. Not a capacity measurement.',
                  expect=('all_verified', 'no_duplicates', 'no_late_sends', 'isolation', 'clean_workers')),
    'S1': dict(description='5,000 posts due in the same minute, spread over 2,000 workspaces (standard section 4).',
               expect=('standard', 'isolation', 'clean_workers')),
    'S2': dict(hot_posts=3000, max_run_minutes=80,
               description='The same 5,000 posts, one hot workspace holding 3,000 and 2,000 spread over 1,999 '
                           'workspaces (fairness).', expect=('standard', 'isolation', 'clean_workers')),
    'S3': dict(workspaces=2000, posts=13000, max_run_minutes=80,
               description='13,000 posts due in the same minute: where approval expiry starts holding posts.',
               expect=('standard', 'isolation', 'clean_workers')),
    'S0-100': dict(per_minute=100, minutes=20, workspaces=2000, due_second_jitter_share=0.3, max_run_minutes=45,
                   description='Normal load: 100 posts due per minute for 20 minutes (70% on the minute, 30% at a '
                               'random second), crons with delivery jitter.', expect=('normal_load', 'isolation', 'clean_workers')),
    'S0-250': dict(per_minute=250, minutes=20, workspaces=2000, due_second_jitter_share=0.3, max_run_minutes=60,
                   description='Normal load: 250 posts due per minute for 20 minutes.',
                   expect=('normal_load', 'isolation', 'clean_workers')),
    'baseline': dict(lane=False, fixed_run_minutes=10,
                     description='The frozen minute worker (lane flag off) on the S1 data for 10 minutes: its real '
                                 'Discord posts per minute.', expect=('baseline', 'no_duplicates', 'no_late_sends', 'isolation')),
    'F429': dict(workspaces=1000, posts=1000, max_run_minutes=20, stall_detect_minutes=4,
                 injections=[{'kind': 'global429', 'at': 1.5, 'seconds': 1.0, 'retryAfter': 5},
                             {'kind': 'global429', 'at': 3.0, 'seconds': 1.0, 'retryAfter': 3},
                             {'kind': 'route429', 'route': 'POST /channels/{id}/messages', 'after': 2.0, 'count': 5,
                              'retryAfter': 3},
                             {'kind': 'route429', 'route': 'GET /guilds/{id}', 'after': 2.5, 'count': 5,
                              'retryAfter': 2},
                             {'kind': 'html429', 'route': 'GET /guilds/{id}/channels', 'after': 4.0, 'count': 2}],
                 description='Discord 429s under load: two global 429 windows (Retry-After 5 s and 3 s), per-route '
                             '429 on 5 creates and 5 guild reads, and a Cloudflare-style HTML 429 (ban page, no '
                             'retry hint) on 2 channel-list reads.', expect=('f429', 'no_duplicates', 'no_late_sends', 'isolation')),
    'F5xx': dict(workspaces=1000, posts=1000, max_run_minutes=25,
                 injections=[{'kind': 'create500', 'landed': True, 'after': 1.0, 'count': 4},
                             {'kind': 'create500', 'landed': False, 'after': 1.5, 'count': 4},
                             {'kind': 'createTimeout', 'landed': True, 'after': 2.0, 'count': 3, 'delay': 25},
                             {'kind': 'createTimeout', 'landed': False, 'after': 2.5, 'count': 3, 'delay': 25}],
                 description='Discord 5xx and timeouts on create, with and without the message having landed.',
                 expect=('f5xx', 'no_duplicates', 'no_late_sends', 'isolation')),
    'Fcrash': dict(kills=[3, 5, 8, 11, 14, 17], kill_at_create=4, max_run_minutes=75,
                   injections=[{'kind': 'holdCreate', 'landed': True, 'after': 2.0, 'count': 2, 'hold': 4},
                               {'kind': 'holdCreate', 'landed': True, 'after': 7.0, 'count': 2, 'hold': 4}],
                   description='S1 with worker crashes: six SIGKILLs of a random shard process at T+3..17 min and '
                               'four SIGKILLs of the shard whose create the mock holds in flight.',
                   expect=('fcrash', 'no_duplicates', 'no_late_sends', 'isolation')),
    'Fdb': dict(workspaces=1000, posts=1500, max_db_connections=6, db_latency_ms=8.0, db_statement_timeout_ms=1500,
                lock_injection={'start': 1.0, 'every': 20.0, 'hold': 2.5, 'workspaceRows': 3}, max_run_minutes=40,
                description='Database contention: a 6-connection pool, 8 ms per round trip, a 1.5 s statement '
                            'timeout, and every 20 s the coordinator\'s application row and three workspace rows '
                            'locked for 2.5 s.', expect=('fdb', 'no_duplicates', 'no_late_sends', 'isolation')),
    'Fexpiry': dict(workspaces=1500, posts=3000, expiry_in_minutes=4, max_run_minutes=12,
                    description='A burst whose approvals expire 4 minutes after the run starts (seeded through the '
                                'seeder\'s clock: approved and scheduled one hour earlier).',
                    expect=('fexpiry', 'no_duplicates', 'no_late_sends', 'isolation')),
    'Fstall': dict(workspaces=1500, posts=3000, stall=[0, 10], max_run_minutes=55,
                   description='Backlog recovery: no cron fires for the first 10 minutes after T, then normal.',
                   expect=('fstall', 'no_duplicates', 'no_late_sends', 'isolation')),
    'Fflip': dict(workspaces=1000, posts=2000, flag_off=[2, 6], max_run_minutes=40,
                  description='Flag flip: the lane flag is off from T+2 to T+6 min (the minute worker takes Discord '
                              'back), then on again.', expect=('fflip', 'no_duplicates', 'no_late_sends', 'isolation')),
    'Nmisroute': dict(workspaces=200, posts=200, misroute_every=10, max_run_minutes=12, stall_detect_minutes=4,
                      description='Negative control: the harness rewrites about one create in ten to another '
                                  'tenant\'s channel at the wire; the isolation check must fire.',
                      expect=('negative_misroute',)),
    'Ndup': dict(workspaces=200, posts=200, double_accept_every=25, max_run_minutes=12,
                 description='Negative control: the mock accepts every 25th create twice; the duplicate counters '
                             'must fire.', expect=('negative_duplicates',)),
    'Nceiling': dict(workspaces=600, posts=1200, policy_capacity=100, information_only=True, mock_latency='uniform:5:20',
                     max_run_minutes=20,
                     description='Negative control and information-only sensitivity: the coordinator policy raised '
                                 'to 100/s (not a reviewed setting); the 25/s and 50/s counters must fire.',
                     expect=('negative_ceiling',)),
}
PROFILES = {
    'release': ['smoke', 'S1', 'S2', 'S0-100', 'S0-250', 'baseline', 'F429', 'F5xx', 'Fcrash', 'Fdb', 'Fexpiry',
                'Fstall', 'Fflip', 'Nmisroute', 'Ndup', 'Nceiling'],
    'stress': ['S1', 'S2'],
    'failures': ['F429', 'F5xx', 'Fcrash', 'Fdb', 'Fexpiry', 'Fstall', 'Fflip'],
    'controls': ['Nmisroute', 'Ndup', 'Nceiling'],
}


def now_iso(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def git(tree, *args):
    try:
        return subprocess.run(['git', '-C', str(tree), *args], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


def load1():
    try:
        return float(open('/proc/loadavg').read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def proc_cpu(pid):
    try:
        fields = open('/proc/%d/stat' % pid).read().rsplit(')', 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')
    except (OSError, ValueError, IndexError):
        return None


def postgres_cpu(postmaster):
    if not postmaster:
        return None
    total = 0.0
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        try:
            raw = open('/proc/%s/stat' % name).read()
            fields = raw.rsplit(')', 1)[1].split()
            if int(name) == postmaster or int(fields[1]) == postmaster:
                total += (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')
        except (OSError, ValueError, IndexError):
            continue
    return total


def socket_owner(port, peer_port, pids):
    """The pid among `pids` owning the TCP socket 127.0.0.1:port -> :peer_port (/proc/net/tcp and fd links)."""
    inode = None
    try:
        for line in open('/proc/net/tcp').read().splitlines()[1:]:
            parts = line.split()
            local, remote = parts[1], parts[2]
            if int(local.split(':')[1], 16) == port and int(remote.split(':')[1], 16) == peer_port:
                inode = parts[9]
                break
    except (OSError, ValueError, IndexError):
        return None
    if not inode:
        return None
    target = 'socket:[%s]' % inode
    for pid in pids:
        try:
            for fd in os.listdir('/proc/%d/fd' % pid):
                try:
                    if os.readlink('/proc/%d/fd/%s' % (pid, fd)) == target:
                        return pid
                except OSError:
                    continue
        except OSError:
            continue
    return None


class Harness:
    def __init__(self, args, settings, scenario, run_dir):
        self.args, self.s, self.scenario, self.dir = args, settings, scenario, Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / 'invocations').mkdir(exist_ok=True)
        (self.dir / 'mock').mkdir(exist_ok=True)
        self.log_handle = open(self.dir / 'harness.log', 'a')
        self.children = []          # every process we started (for cleanup)
        self.invocations = {}       # name -> dict(proc, path, scheduled, spawned)
        self.inv_lock = threading.Lock()
        self.stop = threading.Event()
        self.cron_stop = threading.Event()
        self.cluster = None
        self.events = open(self.dir / 'invocations.jsonl', 'a')
        self.events_lock = threading.Lock()
        self.kills = []
        self.lock_windows = []
        self.config = {}

    # -- utilities ----------------------------------------------------------------------------------------------

    def log(self, message):
        line = '%s %s' % (now_iso(), message)
        print(line, flush=True)
        self.log_handle.write(line + '\n')
        self.log_handle.flush()

    def event(self, **fields):
        with self.events_lock:
            self.events.write(json.dumps(fields) + '\n')
            self.events.flush()

    def start_child(self, argv, *, name, stdout=None, env=None):
        handle = open(self.dir / ('%s.out' % name), 'a') if stdout is None else stdout
        process = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT, env=env, cwd='/tmp',
                                   start_new_session=False)
        self.children.append(process)
        return process

    def wait_ready(self, name, word, timeout=60):
        deadline = time.time() + timeout
        path = self.dir / ('%s.out' % name)
        while time.time() < deadline:
            if path.exists() and word in path.read_text():
                return
            time.sleep(0.1)
        raise RuntimeError('%s did not become ready: %s' % (name, path.read_text()[-2000:] if path.exists() else ''))

    def admin(self):
        import psycopg
        return psycopg.connect(self.admin_dsn, autocommit=True, connect_timeout=10)

    # -- setup --------------------------------------------------------------------------------------------------

    def prepare(self):
        s, args = self.s, self.args
        # Children run from a copy of the harness taken now, so editing the harness during a run changes nothing.
        self.scripts = self.dir / 'harness'
        self.scripts.mkdir(exist_ok=True)
        for source in sorted(SCRIPTS.glob('discord_lane_cap*.py')) + [SCRIPTS / 'discord_lane_capacity_run.py']:
            shutil.copy2(source, self.scripts / source.name)
        tree = Path(args.source_tree).resolve()
        self.tree = tree
        sha = git(tree, 'rev-parse', 'HEAD')
        dirty = git(tree, 'status', '--porcelain', '--untracked-files=no')
        harness_sha = git(HARNESS, 'rev-parse', 'HEAD')
        harness_dirty = git(HARNESS, 'status', '--porcelain', '--untracked-files=no', '--', 'scripts', 'docs/w02', 'tests')
        uptime = open('/proc/loadavg').read().strip() if os.path.exists('/proc/loadavg') else ''
        crons = []
        vercel = tree / 'vercel.json'
        if vercel.exists():
            crons = [c['path'] for c in json.loads(vercel.read_text()).get('crons', [])
                     if c['path'] == '/api/cron/worker' or c['path'].startswith('/api/cron/discord-worker/')]
        if s['shards'] is not None:
            crons = [c for c in crons if not c.startswith('/api/cron/discord-worker/')]
            crons += ['/api/cron/discord-worker/%d' % n for n in range(s['shards'])]
        if not s['minute_worker']:
            crons = [c for c in crons if c != '/api/cron/worker']
        has_lane = (tree / 'src/postriff_phase2/discord/lane.py').exists()
        self.routes = crons
        self.config.update(
            scenario=self.scenario, label=args.label or self.scenario, description=s.get('description', ''),
            sourceTree=str(tree), sourceSha=sha, sourceDirty=bool(dirty), harnessSha=harness_sha,
            harnessDirty=bool(harness_dirty), startedAt=time.time(), startedAtIso=now_iso(), loadAtStart=uptime,
            routes=crons, laneCodePresent=has_lane, settings={k: v for k, v in s.items() if k != 'expect'},
            expect=list(s['expect']), python=sys.version.split()[0], machine=machine_description(),
            cronPeriodSeconds=s['cron_period'], policyCeiling=25, informationOnly=s['information_only'])
        if s['lane'] and not has_lane:
            raise SystemExit('the source tree has no W-02 lane (src/postriff_phase2/discord/lane.py); run it with '
                             '--scenario baseline or --lane off')
        if not sha:
            raise SystemExit('the source tree is not a git checkout; record its SHA by using a detached worktree')
        self.log('run %s: scenario %s on %s (%s)%s; harness %s; load %s' % (
            self.dir.name, self.scenario, tree, sha[:12], ' DIRTY' if dirty else '', harness_sha[:12], uptime))

    def database(self):
        s, args = self.s, self.args
        if args.admin_database_url:
            # One fresh database per run on the external server (each scenario needs an empty schema); the
            # application's URL (through the external pooler) is pointed at the same database name.
            import psycopg
            self.external_db = 'capacity_' + re.sub(r'[^a-z0-9]', '_', self.dir.name.lower())[:40]
            self.admin_dsn = cluster_tools.fresh_database(args.admin_database_url, self.external_db)
            if args.database_url:
                info = psycopg.conninfo.conninfo_to_dict(args.database_url)
                info['dbname'] = self.external_db
                self.external_app_dsn = psycopg.conninfo.make_conninfo(**info)
            else:
                self.external_app_dsn = self.admin_dsn
            self.config['database'] = 'external server, database %s' % self.external_db
        else:
            pg_bin = args.pg_bin or os.environ.get('POSTRIFF_PG_BIN')
            if not pg_bin:
                raise SystemExit('set --pg-bin or POSTRIFF_PG_BIN, or give --admin-database-url')
            self.cluster = cluster_tools.LocalCluster(pg_bin, max_connections=max(100, s['max_db_connections'] + 40),
                                                      log=self.log)
            self.admin_dsn = self.cluster.dsn
            self.config['database'] = 'local throwaway cluster'
            self.config['clusterDirectory'] = self.cluster.tmp
            self.config['clusterPort'] = self.cluster.port
            self.config['clusterPgBin'] = str(self.cluster.pg_bin)
        cluster_tools.apply_schema(self.admin_dsn, self.tree, log=self.log)
        with self.admin() as db:
            self.config['serverVersion'] = db.execute('SHOW server_version').fetchone()[0]
            self.config['serverMaxConnections'] = int(db.execute('SHOW max_connections').fetchone()[0])
            self.config['pgStatStatements'] = db.execute(
                "SELECT count(*) FROM pg_extension WHERE extname='pg_stat_statements'").fetchone()[0] == 1

    def pgbouncer(self):
        """A real PgBouncer (transaction mode, pool --max-db-connections) in front of the throwaway cluster."""
        s, args = self.s, self.args
        folder = self.dir / 'pgbouncer'
        folder.mkdir(exist_ok=True)
        port = cluster_tools.free_port()
        ini = folder / 'pgbouncer.ini'
        (folder / 'userlist.txt').write_text('"postgres" ""\n')
        timeout = (" connect_query='SET statement_timeout=%d'" % s['db_statement_timeout_ms']) if s['db_statement_timeout_ms'] else ''
        ini.write_text('\n'.join([
            '[databases]', '* = host=%s port=%d user=postgres%s' % (self.cluster.sock, self.cluster.port, timeout), '',
            '[pgbouncer]', 'listen_addr = 127.0.0.1', 'listen_port = %d' % port, 'unix_socket_dir =',
            'auth_type = trust', 'auth_file = %s' % (folder / 'userlist.txt'), 'pool_mode = transaction',
            'default_pool_size = %d' % s['max_db_connections'], 'reserve_pool_size = 0',
            'max_client_conn = %d' % s['max_client_connections'], 'server_reset_query =',
            'ignore_startup_parameters = extra_float_digits,options', 'query_wait_timeout = %d' % int(s['pool_wait_timeout']),
            'admin_users = postgres', 'stats_users = postgres', 'logfile = %s' % (folder / 'pgbouncer.log'),
            'pidfile = %s' % (folder / 'pgbouncer.pid'), '']))
        runas = []
        if os.geteuid() == 0:  # PgBouncer refuses to run as root
            shutil.chown(folder, 'postgres', 'postgres')
            for item in folder.iterdir():
                shutil.chown(item, 'postgres', 'postgres')
            runas = ['runuser', '-u', 'postgres', '--']
        self.bouncer_process = self.start_child([*runas, args.pgbouncer_bin, str(ini)], name='pgbouncer')
        deadline = time.time() + 20
        import socket as _socket
        while time.time() < deadline:
            try:
                _socket.create_connection(('127.0.0.1', port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError('PgBouncer did not start; see %s' % (self.dir / 'pgbouncer.out'))
        self.args.pooler_admin_url = 'host=127.0.0.1 port=%d dbname=pgbouncer user=postgres sslmode=disable' % port
        self.pool_database = 'postgres'
        return port

    def pooler(self):
        s, args = self.s, self.args
        port = cluster_tools.free_port()
        stats = self.dir / 'pooler.json'
        self.pool_database = getattr(self, 'external_db', None) or 'postgres'
        if self.cluster is not None and args.pooler == 'pgbouncer':
            bouncer = self.pgbouncer()
            argv = [sys.executable, '-B', str(self.scripts / 'discord_lane_cap_pooler.py'), '--mode', 'relay',
                    '--listen-port', str(port), '--upstream-host', '127.0.0.1', '--upstream-port', str(bouncer),
                    '--latency-ms', str(s['db_latency_ms']), '--stats', str(stats)]
            self.app_dsn = 'host=127.0.0.1 port=%d dbname=postgres user=postgres sslmode=disable' % port
            self.config['pooler'] = 'PgBouncer %s, transaction mode, pool %d, behind the harness relay adding %.1f ms per round trip' % (
                args.pgbouncer_bin, s['max_db_connections'], s['db_latency_ms'])
            self.config['poolSize'] = s['max_db_connections']
        elif self.cluster is not None:
            argv = [sys.executable, '-B', str(self.scripts / 'discord_lane_cap_pooler.py'), '--mode', 'pool',
                    '--listen-port', str(port), '--upstream-socket', self.cluster.socket_path,
                    '--pool-size', str(s['max_db_connections']), '--max-clients', str(s['max_client_connections']),
                    '--latency-ms', str(s['db_latency_ms']), '--connect-rtts', str(s['db_connect_rtts']),
                    '--wait-timeout', str(s['pool_wait_timeout']), '--stats', str(stats)]
            if s['db_statement_timeout_ms']:
                argv += ['--server-options', '-c statement_timeout=%d' % s['db_statement_timeout_ms']]
            self.app_dsn = 'host=127.0.0.1 port=%d dbname=postgres user=postgres sslmode=disable' % port
            self.config['pooler'] = 'harness transaction pooler (pool %d, %.1f ms per round trip)' % (
                s['max_db_connections'], s['db_latency_ms'])
        elif args.database_url and s['db_latency_ms']:
            import psycopg
            info = psycopg.conninfo.conninfo_to_dict(self.external_app_dsn)
            argv = [sys.executable, '-B', str(self.scripts / 'discord_lane_cap_pooler.py'), '--mode', 'relay',
                    '--listen-port', str(port), '--upstream-host', info.get('host', '127.0.0.1'),
                    '--upstream-port', str(info.get('port', 5432)), '--latency-ms', str(s['db_latency_ms']),
                    '--stats', str(stats)]
            info.update(host='127.0.0.1', port=str(port))
            self.app_dsn = psycopg.conninfo.make_conninfo(**info)
            self.config['pooler'] = 'external pooler at --database-url, harness relay adds %.1f ms' % s['db_latency_ms']
        else:
            self.app_dsn = getattr(self, 'external_app_dsn', None) or self.admin_dsn
            self.config['pooler'] = 'external (--database-url), no harness relay'
            self.pooler_process = None
            return
        self.pooler_process = self.start_child(argv, name='pooler')
        self.wait_ready('pooler', 'pooler.ready')
        self.config['poolerPid'] = self.pooler_process.pid
        # The application's own path to the database must work before anything is seeded.
        import psycopg
        try:
            with psycopg.connect(self.app_dsn, prepare_threshold=None, connect_timeout=10) as db:
                db.execute('SELECT 1').fetchone()
                db.commit()
        except Exception as error:
            tail = ''
            for name in ('pgbouncer/pgbouncer.log', 'pgbouncer.out', 'pooler.out'):
                if (self.dir / name).exists():
                    tail += '\n--- %s\n%s' % (name, (self.dir / name).read_text(errors='replace')[-1500:])
            raise RuntimeError('the application cannot reach the database through the pooler: %s%s' % (error, tail))

    def mock(self):
        s = self.s
        self.mock_port = cluster_tools.free_port()
        argv = [sys.executable, '-B', str(self.scripts / 'discord_lane_cap_mock.py'), '--port', str(self.mock_port),
                '--out', str(self.dir / 'mock'), '--workspaces', str(self.workspace_count()),
                '--latency', s['mock_latency'], '--tail-probability', str(s['mock_tail_probability']),
                '--tail-ms', str(s['mock_tail_ms']), '--read-limit', s['mock_read_limit'],
                '--double-accept-every', str(s['double_accept_every'])]
        self.mock_injection_file = None
        if s['injections']:
            self.mock_injection_file = self.dir / 'mock-injections.json'
            argv += ['--injections', str(self.mock_injection_file)]
        self.mock_argv = argv

    def start_mock(self):
        if self.mock_injection_file is not None:
            rules = []
            for rule in self.s['injections']:
                rule = dict(rule)
                for key in ('at', 'after'):
                    if key in rule:
                        rule[key] = self.reference + 60 * rule[key]
                rules.append(rule)
            self.mock_injection_file.write_text(json.dumps(rules))
            self.config['mockInjections'] = rules
        self.mock_process = self.start_child(self.mock_argv, name='mock')
        self.wait_ready('mock', 'mock.ready')
        self.config['mockPid'] = self.mock_process.pid

    def workspace_count(self):
        return max(self.s['workspaces'], 1) + 2

    def environment(self, *, lane_on, policy):
        s = self.s
        env = {
            'POSTRIFF_DATABASE_URL': self.app_dsn,
            'POSTRIFF_SUPABASE_URL': 'https://capacity-harness-synthetic.supabase.co',  # shape only; DNS is fenced
            'POSTRIFF_SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_capacity_harness_synthetic_000',
            'POSTRIFF_SUPABASE_SECRET_KEY': 'sb_secret_capacity_harness_synthetic_000000',
            'POSTRIFF_CREDENTIAL_KEY': self.credential_key,
            'POSTRIFF_PUBLIC_BASE_URL': 'https://rafii.example.invalid',
            'POSTRIFF_OAUTH_DISCORD_CLIENT_ID': mock_tools.APP,
            'POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET': 'cap-client-secret-synthetic-0000000000',
            'POSTRIFF_DISCORD_BOT_TOKEN': mock_tools.BOT_TOKEN,
            'POSTRIFF_OAUTH_DISCORD_REVIEWED': 'true',
            'POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED': 'true',
            'POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED': 'true',
            'POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED': 'true',
            'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true',
            'POSTRIFF_DISCORD_RATE_POLICY': policy,
            'POSTRIFF_DISCORD_CONNECT_WORKSPACES': '*',
            'POSTRIFF_DISCORD_GUILD_CAP': '10000',
            'POSTRIFF_WORKER_MAX_JOBS': str(s['worker_max_jobs']),
            'POSTRIFF_WORKER_MAX_SECONDS': str(s['worker_max_seconds']),
            'CRON_SECRET': self.cron_secret,
        }
        if lane_on:
            env['POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED'] = 'true'
            env['POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS'] = str(s['lane_max_seconds'])
            if s['lane_max_steps'] is not None:
                env['POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_STEPS'] = str(s['lane_max_steps'])
        if s['misroute_every']:
            env['CAP_MISROUTE_EVERY'] = str(s['misroute_every'])
        return env

    def policies(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('cap_rate_policy_tool', self.tree / 'scripts/discord_rate_policy.py')
        tool = importlib.util.module_from_spec(spec)
        saved = list(sys.path)
        try:
            spec.loader.exec_module(tool)  # it puts the tested tree's src first and imports SafetyPolicy from it
        finally:
            sys.path[:] = saved
            for name in [n for n in sys.modules if n == 'postriff_phase2' or n.startswith(('postriff_phase2.', 'postriff_alpha'))]:
                del sys.modules[name]
        now = time.time()
        run = tool.build(now, days=1, revision='cap-run-' + self.dir.name[-24:].replace('_', '-'),
                         app_capacity=self.s['policy_capacity'])
        seed = tool.build(now, days=1, revision='cap-seed-' + self.dir.name[-23:].replace('_', '-'),
                          app_capacity=20000)
        return json.dumps(run), json.dumps(seed), run

    def write_environments(self):
        from cryptography.fernet import Fernet
        self.credential_key = Fernet.generate_key().decode()
        self.cron_secret = 'cap-cron-' + os.urandom(16).hex()
        run_policy, seed_policy, policy = self.policies()
        self.config['ratePolicy'] = policy
        on = self.environment(lane_on=self.s['lane'], policy=run_policy)
        off = self.environment(lane_on=False, policy=run_policy)
        seed = self.environment(lane_on=False, policy=seed_policy)
        seed['POSTRIFF_DATABASE_URL'] = self.admin_dsn
        for name, values in (('env-run.json', on), ('env-flag-off.json', off), ('env-seed.json', seed)):
            path = self.dir / name
            path.write_text(json.dumps(values))
            os.chmod(path, 0o600)
        self.env_run, self.env_off, self.env_seed = self.dir / 'env-run.json', self.dir / 'env-flag-off.json', self.dir / 'env-seed.json'
        self.config['environmentNames'] = sorted(on)

    # -- seeding ------------------------------------------------------------------------------------------------

    def plan(self):
        s = self.s
        rng = random.Random(20261023)
        layout = []  # (index, [due offsets in seconds relative to T])
        if s['per_minute']:
            total = s['per_minute'] * s['minutes']
            offsets = []
            for minute in range(s['minutes']):
                for _ in range(s['per_minute']):
                    second = rng.randrange(60) if rng.random() < s['due_second_jitter_share'] else 0
                    offsets.append(minute * 60 + second)
            buckets = [[] for _ in range(s['workspaces'])]
            for position, offset in enumerate(offsets):
                buckets[position % s['workspaces']].append(offset)
            layout = [(i, sorted(b)) for i, b in enumerate(buckets) if b]
            del total
        elif s['hot_posts']:
            rest = s['posts'] - s['hot_posts']
            others = max(1, s['workspaces'] - 1)
            layout = [(0, [0] * s['hot_posts'])]
            base, extra = divmod(rest, others)
            layout += [(1 + i, [0] * (base + (1 if i < extra else 0))) for i in range(others) if base + (i < extra)]
        else:
            base, extra = divmod(s['posts'], s['workspaces'])
            layout = [(i, [0] * (base + (1 if i < extra else 0))) for i in range(s['workspaces'])
                      if base + (1 if i < extra else 0)]
        return layout

    def seed(self):
        """Phase 1 connects every workspace in parallel processes; then T is chosen from the measured rate so that it
        lies the lead time after seeding; phase 2 approves the posts for T."""
        s = self.s
        layout = self.plan()
        posts = sum(len(d) for _, d in layout)
        hot = max((len(d) for _, d in layout), default=0)
        workers = max(1, min(s['seed_processes'], len(layout)))
        period = s['cron_period']
        lead = s['lead_seconds']
        expiry_seam = s['expiry_in_minutes'] is not None
        started = time.time()
        connect_deadline = started + 600 + len(layout) * 2.0 / workers
        plan = {'workspacesTotal': self.workspace_count(), 'runTag': self.dir.name, 'deadline': connect_deadline + 900,
                'workspaces': [[index, offsets] for index, offsets in layout]}
        plan_path = self.dir / 'seed-plan.json'
        plan_path.write_text(json.dumps(plan))
        self.log('seeding %d posts in %d workspaces with %d processes: connecting' % (posts, len(layout), workers))
        processes = []
        for part in range(workers):
            out = self.dir / ('seed-%d.jsonl' % part)
            argv = [sys.executable, '-I', '-B', str(self.scripts / 'discord_lane_cap_seed.py'),
                    '--source-tree', str(self.tree), '--admin-dsn', self.admin_dsn, '--env', str(self.env_seed),
                    '--plan', str(plan_path), '--out', str(out), '--slice', '%d/%d' % (part, workers)]
            processes.append((self.start_child(argv, name='seed-%d' % part), out))
        # Release every slice at once (each waits for seed-plan.json.go after its imports).
        while not all(Path(str(out) + '.ready').exists() for _, out in processes):
            for process, _ in processes:
                if process.poll() is not None and process.returncode:
                    self.seed_failure(processes, 'while starting')
            if time.time() > connect_deadline:
                raise RuntimeError('the seeding processes did not start in time')
            time.sleep(0.1)
        Path(str(plan_path) + '.go').write_text(json.dumps({'at': time.time()}))
        while not all(Path(str(out) + '.connected').exists() for _, out in processes):
            for process, _ in processes:
                if process.poll() is not None and process.returncode:
                    self.seed_failure(processes, 'while connecting the workspaces')
            if time.time() > connect_deadline:
                raise RuntimeError('seeding could not connect the workspaces in time')
            time.sleep(0.5)
        connected = time.time()
        estimate = 10 + posts * 0.006 / workers + (hot ** 2) * 5e-6 + hot * 0.02
        now = time.time()
        if expiry_seam:
            # Approvals expire `expiry_in_minutes` after the run's first cron: scheduled an hour earlier and approved
            # by the seeder's own clock set back accordingly (the tested code runs on the real clock).
            first = math.ceil((now + estimate * 2 + lead) / period) * period
            T = math.floor((first + 60 * s['expiry_in_minutes'] - 3600) / 60) * 60
            clock_offset = (T - 300) - now
            self.first_cron_floor = first
        else:
            granularity = 60 if period >= 60 else period
            T = math.ceil((now + estimate * 2 + lead) / granularity) * granularity
            clock_offset = 0.0
            self.first_cron_floor = None
        self.T = T
        self.reference = self.first_cron_floor if expiry_seam else T
        deadline = self.reference - max(8, lead * 0.25)
        due_path = Path(str(plan_path) + '.due')
        due_path.write_text(json.dumps({'due': T, 'clockOffset': clock_offset, 'deadline': deadline}))
        self.config.update(dueAt=T, dueAtIso=now_iso(T), referenceAt=self.reference,
                           seedConnectSeconds=round(connected - started, 1), seedScheduleEstimateSeconds=round(estimate, 1),
                           seededWorkspaces=len(layout), seededPosts=posts, hotPosts=s['hot_posts'],
                           seedClockOffsetSeconds=clock_offset)
        self.log('connected %d workspaces in %.0f s; T = %s%s' % (
            len(layout), connected - started, now_iso(T),
            ' (approval expiry seam: approvals expire at %s)' % now_iso(T + 3600) if expiry_seam else ''))
        for process, _ in processes:
            while process.poll() is None:
                if time.time() > deadline + 20:
                    raise RuntimeError('seeding overran T; rerun with a larger --lead-seconds')
                if any(other.poll() for other, _ in processes):
                    break  # another slice already failed: report it now, not after this one finishes
                time.sleep(0.25)
            if any(other.poll() for other, _ in processes):
                self.seed_failure(processes, 'while approving the posts')
        with open(self.dir / 'seed-manifest.jsonl', 'w') as manifest:
            for _, out in processes:
                manifest.write(Path(out).read_text())
                Path(out).unlink()
                Path(str(out) + '.connected').unlink()
                Path(str(out) + '.ready').unlink()
        done = time.time()
        rows = analysis.load_jsonl(self.dir / 'seed-manifest.jsonl')
        if len(rows) != posts or len({r['nonce'] for r in rows}) != posts:
            raise RuntimeError('seed manifest has %d rows (%d distinct nonces), expected %d' % (
                len(rows), len({r['nonce'] for r in rows}), posts))
        with self.admin() as db:
            counted = db.execute("""SELECT count(*) FROM public.pr_workspaces w CROSS JOIN LATERAL
                jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
                WHERE j#>>'{manifest,platform}'='Discord' AND j->>'state'='scheduled'""").fetchone()[0]
            credentials = db.execute("SELECT count(*) FROM public.pr_encrypted_credentials WHERE provider='discord'").fetchone()[0]
            seed_admissions = dict(db.execute(
                'SELECT state,count(*) FROM public.pr_discord_request_admissions GROUP BY state').fetchall())
            if self.config.get('pgStatStatements'):
                db.execute('SELECT pg_stat_statements_reset()')
        self.config['seedAdmissionsByState'] = seed_admissions
        if counted != posts:
            raise RuntimeError('the database holds %d scheduled Discord jobs, expected %d' % (counted, posts))
        open_slots = {k: v for k, v in seed_admissions.items() if k in ('sent', 'uncertain')}
        if open_slots:
            # A sent or uncertain admission keeps its slot of the application budget (it never expires): the measured
            # run would start with less than the reviewed capacity.
            raise RuntimeError('seeding left request admissions open %s; the run would start with a reduced budget'
                               % json.dumps(open_slots, sort_keys=True))
        self.config.update(seedingSeconds=round(done - started, 1), seedingEndedAt=done,
                           leadSecondsActual=round(self.reference - done, 1), discordCredentials=credentials)
        self.log('seeded in %.0f s: %d scheduled jobs, %d Discord credentials; lead to T %.0f s' % (
            done - started, counted, credentials, self.reference - done))

    def seed_failure(self, processes, phase):
        """Name every failed seeding process with its exit code and the end of its own output (stdout and stderr go
        to seed-<n>.out), in harness.log and in the error, so a failure is diagnosable from the artifact alone."""
        failed = []
        for number, (process, _) in enumerate(processes):
            code = process.poll()
            if code:
                path = self.dir / ('seed-%d.out' % number)
                tail = path.read_text(errors='replace')[-4000:] if path.exists() else '(no output file)'
                failed.append((number, code, tail.strip()))
        for number, code, tail in failed:
            self.log('seeding process seed-%d exited with %s %s; the end of seed-%d.out:\n%s' % (
                number, code, phase, number, tail))
        if not failed:
            raise RuntimeError('a seeding process failed %s; see %s' % (phase, self.dir))
        number, code, tail = failed[0]
        last = [line for line in tail.splitlines() if line.strip()]
        raise RuntimeError('a seeding process failed %s (%s); seed-%d.out ends with: %s' % (
            phase, ', '.join('seed-%d exit %s' % (n, c) for n, c, _ in failed), number,
            ' | '.join(last[-6:])[-1500:]))

    def seed_check(self):
        """Only the seeding path of a scenario (its layout, its seed processes, the manifest and database checks), on a
        throwaway cluster, then clean up: no mock, no pooler, no cron. A fast check of multi-process seeding."""
        started = time.time()
        try:
            self.prepare()
            self.database()
            self.app_dsn = self.admin_dsn
            self.write_environments()
            self.seed()
            summary = {'event': 'seed_check.done', 'scenario': self.scenario, 'dir': str(self.dir),
                       'workspaces': self.config.get('seededWorkspaces'), 'posts': self.config.get('seededPosts'),
                       'processes': max(1, min(self.s['seed_processes'], self.config.get('seededWorkspaces') or 1)),
                       'connectSeconds': self.config.get('seedConnectSeconds'),
                       'seedingSeconds': self.config.get('seedingSeconds'),
                       'credentials': self.config.get('discordCredentials'),
                       'slices': [json.loads(line) for n in range(8) if (self.dir / ('seed-%d.out' % n)).exists()
                                  for line in (self.dir / ('seed-%d.out' % n)).read_text(errors='replace').splitlines()
                                  if line.startswith('{"event": "seed.slice_done"')],
                       'seconds': round(time.time() - started, 1)}
            self.log(json.dumps(summary))
            return summary
        except BaseException as error:
            self.config['harnessError'] = '%s: %s' % (type(error).__name__, error)
            self.log('seed check failed: %s' % error)
            raise
        finally:
            self.stop.set()
            self.cron_stop.set()
            self.cleanup()
            (self.dir / 'config.json').write_text(json.dumps(self.config, indent=1, default=str))

    # -- the cron emulator --------------------------------------------------------------------------------------

    def env_for(self, scheduled):
        flip = self.s['flag_off']
        if flip and self.reference + 60 * flip[0] <= scheduled < self.reference + 60 * flip[1]:
            return self.env_off
        return self.env_run

    def stalled(self, scheduled):
        stall = self.s['stall']
        return bool(stall and self.reference + 60 * stall[0] <= scheduled < self.reference + 60 * stall[1])

    def spawn(self, path, scheduled):
        name = '%d-%s' % (int(scheduled), path.strip('/').replace('/', '-'))
        out = self.dir / 'invocations' / (name + '.json')
        env = dict(os.environ)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['CAP_SPAWNED_AT'] = repr(time.time())
        argv = [sys.executable, '-I', '-B', str(self.scripts / 'discord_lane_cap_invoke.py'), '--source-tree', str(self.tree),
                '--path', path, '--env', str(self.env_for(scheduled)), '--mock-port', str(self.mock_port),
                '--start-at', repr(scheduled), '--out', str(out)]
        if self.s['invocation_mode'] == 'warm':
            argv.append('--warm')
        handle = open(self.dir / 'invocations' / (name + '.log'), 'w')
        process = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT, env=env, cwd='/tmp')
        handle.close()
        with self.inv_lock:
            self.invocations[name] = {'process': process, 'path': path, 'scheduled': scheduled,
                                      'spawned': time.time(), 'out': out, 'flagOff': self.env_for(scheduled) == self.env_off}
        self.event(event='spawned', name=name, path=path, scheduled=scheduled, pid=process.pid,
                   flagOff=self.env_for(scheduled) == self.env_off)

    def cron(self):
        s = self.s
        period = s['cron_period']
        rng = random.Random(7)
        start = math.ceil((time.time() + PRESPAWN_SECONDS + 2) / period) * period
        if self.first_cron_floor:
            start = max(start, self.first_cron_floor)
        self.config['firstCronAt'] = start
        self.log('cron emulator: %d routes every %d s from %s' % (len(self.routes), period, now_iso(start)))
        boundary = start
        while not self.cron_stop.is_set():
            wake = boundary - PRESPAWN_SECONDS
            while time.time() < wake and not self.cron_stop.is_set():
                time.sleep(min(0.5, max(0.01, wake - time.time())))
                self.reap()
            if self.cron_stop.is_set():
                break
            if self.stalled(boundary):
                self.event(event='stalled', boundary=boundary)
            else:
                for path in self.routes:
                    self.spawn(path, boundary + rng.uniform(*s['cron_jitter']))
            boundary += period
        self.log('cron emulator stopped')

    def reap(self):
        with self.inv_lock:
            items = list(self.invocations.items())
        for name, item in items:
            process = item['process']
            code = process.poll()
            if code is None:
                if time.time() > item['scheduled'] + self.s['max_duration']:
                    process.kill()
                    self.event(event='killed', name=name, reason='function_limit', at=time.time())
                continue
            if 'exit' not in item:
                item['exit'] = code
                self.event(event='exited', name=name, code=code, at=time.time())

    def alive(self, lane_only=False):
        with self.inv_lock:
            return [(n, i) for n, i in self.invocations.items() if i['process'].poll() is None
                    and (not lane_only or i['path'].startswith('/api/cron/discord-worker/'))]

    # -- injectors ----------------------------------------------------------------------------------------------

    def crash_injector(self):
        s = self.s
        kills = sorted(s['kills'] or [])
        rng = random.Random(11)
        announcements = self.dir / 'mock' / 'kill-requests.jsonl'
        seen = 0
        while not self.stop.is_set():
            now = time.time()
            if kills and now >= self.reference + 60 * kills[0]:
                kills.pop(0)
                candidates = [(n, i) for n, i in self.alive(lane_only=True) if now > i['scheduled']]
                if candidates:
                    name, item = rng.choice(candidates)
                    item['process'].kill()
                    record = {'kind': 'random', 'name': name, 'pid': item['process'].pid, 'at': now}
                    self.kills.append(record)
                    self.event(event='killed', reason='injected_random', **record)
                    self.log('crash injector: SIGKILL %s (random)' % name)
            if s['kill_at_create'] and announcements.exists():
                lines = announcements.read_text().splitlines()
                for line in lines[seen:]:
                    seen += 1
                    request = json.loads(line)
                    pids = [i['process'].pid for _, i in self.alive()]
                    pid = None
                    for _ in range(20):
                        pid = socket_owner(request['port'], self.mock_port, pids)
                        if pid:
                            break
                        time.sleep(0.05)
                    if pid:
                        os.kill(pid, signal.SIGKILL)
                        name = next((n for n, i in self.alive() if i['process'].pid == pid), str(pid))
                        record = {'kind': 'at_create', 'pid': pid, 'name': name, 'post': request.get('post'),
                                  'nonce': request.get('nonce'), 'landed': request.get('landed'), 'at': time.time()}
                        self.kills.append(record)
                        self.event(event='killed', reason='injected_at_create', **record)
                        self.log('crash injector: SIGKILL pid %d during the create of %s' % (pid, request.get('post')))
                    else:
                        self.kills.append({'kind': 'at_create_missed', 'post': request.get('post'), 'at': time.time()})
            self.stop.wait(0.2)

    def lock_injector(self):
        spec = self.s['lock_injection']
        next_at = self.reference + 60 * spec['start']
        while not self.stop.is_set():
            if time.time() >= next_at:
                next_at += spec['every']
                try:
                    with self.admin() as db:
                        db.autocommit = False
                        began = time.time()
                        db.execute("SELECT 1 FROM public.pr_discord_rate_state WHERE kind='policy' FOR UPDATE")
                        rows = db.execute("""SELECT id FROM public.pr_workspaces WHERE state ? 'phase2'
                            ORDER BY random() LIMIT %s FOR UPDATE SKIP LOCKED""", (spec.get('workspaceRows', 0),)).fetchall()
                        time.sleep(spec['hold'])
                        db.commit()
                        self.lock_windows.append({'from': began, 'to': time.time(), 'workspaces': len(rows)})
                except Exception as error:
                    self.lock_windows.append({'error': type(error).__name__, 'at': time.time()})
            self.stop.wait(0.2)

    # -- sampling and the end condition ---------------------------------------------------------------------------

    PENDING_SQL = """SELECT count(*) FILTER (WHERE j->>'state' NOT IN ('verified','held','failed','canceled')
              AND NOT (j->>'state'='uncertain' AND coalesce((j->>'nextAt')::float8,0) > extract(epoch from now())+3600)),
            count(*) FILTER (WHERE j->>'state'='verified'), count(*) FILTER (WHERE j->>'state'='held'),
            count(*) FILTER (WHERE j->>'state'='uncertain'), count(*) FILTER (WHERE j->>'state'='failed'),
            count(*)
        FROM public.pr_workspaces w CROSS JOIN LATERAL jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
        WHERE j#>>'{manifest,platform}'='Discord'"""

    def sampler(self):
        postmaster = self.cluster.postmaster_pid() if self.cluster else None
        handle = open(self.dir / 'samples.jsonl', 'a')
        db = None
        last_states = 0.0
        while not self.stop.is_set():
            began = time.time()
            sample = {'at': began, 'load1': load1()}
            try:
                if db is None or db.closed:
                    db = self.admin()
                row = db.execute("""SELECT count(*) FILTER (WHERE backend_type='client backend'),
                        count(*) FILTER (WHERE backend_type='client backend' AND state='active'),
                        max(extract(epoch from clock_timestamp()-query_start)) FILTER (WHERE backend_type='client backend' AND state='active'),
                        count(*) FILTER (WHERE wait_event_type='Lock')
                        FROM pg_stat_activity WHERE pid<>pg_backend_pid()""").fetchone()
                sample['db'] = {'backends': row[0], 'active': row[1], 'longestActiveSeconds': float(row[2] or 0),
                                'lockWaits': row[3]}
                if began - last_states >= 10:
                    last_states = began
                    pending, verified, held, uncertain, failed, total = db.execute(self.PENDING_SQL).fetchone()
                    sample['jobs'] = {'pending': pending, 'verified': verified, 'held': held, 'uncertain': uncertain,
                                      'failed': failed, 'total': total}
                    self.latest_jobs = sample['jobs']
            except Exception as error:
                sample['dbError'] = type(error).__name__
                try:
                    db.close()
                except Exception:
                    pass
                db = None
            if self.args.pooler_admin_url:
                sample['pgbouncer'] = self.pgbouncer_pools()
            try:
                sample['pooler'] = json.loads((self.dir / 'pooler.json').read_text())
                sample['pooler'] = {k: sample['pooler'].get(k) for k in ('clients', 'assigned', 'waiting', 'transactions', 'waitTimeouts')}
            except (OSError, ValueError):
                pass
            alive = self.alive()
            sample['alive'] = len(alive)
            sample['cpu'] = {'postgres': postgres_cpu(postmaster), 'mock': proc_cpu(getattr(self, 'mock_process', None).pid) if getattr(self, 'mock_process', None) else None,
                             'pooler': proc_cpu(self.pooler_process.pid) if getattr(self, 'pooler_process', None) else None}
            handle.write(json.dumps(sample) + '\n')
            handle.flush()
            self.stop.wait(max(0.05, 1.0 - (time.time() - began)))
        handle.close()
        if db is not None:
            db.close()

    def pgbouncer_pools(self):
        """SHOW POOLS on a PgBouncer admin console (simple query protocol): client and server counts, longest wait."""
        try:
            import psycopg
            if getattr(self, '_bouncer', None) is None or self._bouncer.closed:
                self._bouncer = psycopg.connect(self.args.pooler_admin_url, autocommit=True, connect_timeout=5)
            cur = psycopg.ClientCursor(self._bouncer)
            cur.execute('SHOW POOLS')
            names = [c.name for c in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
            mine = [r for r in rows if r.get('database') == self.pool_database]
            pick = lambda key: sum(int(r.get(key) or 0) for r in mine)
            return {'clActive': pick('cl_active'), 'clWaiting': pick('cl_waiting'), 'svActive': pick('sv_active'),
                    'svIdle': pick('sv_idle'), 'maxWait': max((float(r.get('maxwait') or 0) + float(r.get('maxwait_us') or 0) / 1e6
                                                               for r in mine), default=0.0)}
        except Exception as error:
            self._bouncer = None
            return {'error': type(error).__name__}

    def mock_stats(self):
        try:
            return json.loads((self.dir / 'mock' / 'mock-live.json').read_text())
        except (OSError, ValueError):
            return None

    def watch(self):
        s = self.s
        period = s['cron_period']
        self.latest_jobs = None
        last_progress, last_signature = time.time(), None
        reason = None
        while reason is None:
            time.sleep(5)
            self.reap()
            now = time.time()
            if getattr(self, 'end_requested', False):
                reason = 'ended early on request (SIGUSR1)'
                break
            jobs = self.latest_jobs
            stats = self.mock_stats()
            signature = (json.dumps(jobs, sort_keys=True), (stats or {}).get('counters', {}).get('requests'))
            if signature != last_signature:
                last_signature, last_progress = signature, now
            reference = self.reference
            stall = s['stall']
            if stall and now < reference + 60 * stall[1] + 60:
                last_progress = now  # an intentional stall is not a lack of progress
            if s['fixed_run_minutes'] is not None:
                if now >= reference + 60 * s['fixed_run_minutes']:
                    reason = 'fixed duration (%d min after T)' % s['fixed_run_minutes']
                continue
            if jobs and now > reference + 30 and jobs['pending'] == 0 and (
                    not s['per_minute'] or now > reference + 60 * s['minutes']):
                self.config['allTerminalAt'] = now
                reason = 'every post terminal'
            elif now > reference + 60 * s['max_run_minutes']:
                reason = 'time limit (%d min after T)' % s['max_run_minutes']
            elif now > reference + 120 and now - last_progress > 60 * s['stall_detect_minutes']:
                reason = 'no progress for %d min' % s['stall_detect_minutes']
            if int(now) % 60 < 5 and jobs:
                self.log('T%+.1f min: %s; mock %s; alive %d; load %s' % (
                    (now - reference) / 60, json.dumps(jobs), json.dumps({k: (stats or {}).get('counters', {}).get(k) for k in (
                        'requests', 'creates', 'readbacks', 'global429', 'route429', 'aboveGlobalBot')}),
                    len(self.alive()), load1()))
        self.config['endReason'] = reason
        self.config['endedAt'] = time.time()
        self.log('ending: %s' % reason)
        del period

    # -- collection ---------------------------------------------------------------------------------------------

    def collect(self):
        rows = []
        with self.admin() as db:
            jobs = db.execute("""SELECT j->>'id',j->>'state',(j#>'{discordWorker,deadLetter}') IS NOT NULL,
                    coalesce((j->>'checks')::int,0),j->>'nextAction',coalesce(jsonb_array_length(j->'discordDispatchIntents'),0)
                FROM public.pr_workspaces w CROSS JOIN LATERAL jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
                WHERE j#>>'{manifest,platform}'='Discord'""").fetchall()
            admissions = dict(db.execute('SELECT state,count(*) FROM public.pr_discord_request_admissions GROUP BY state').fetchall())
            holds = db.execute("""SELECT kind,count(*) FILTER (WHERE manual_hold),count(*) FILTER (WHERE blocked_until>clock_timestamp()),
                count(*) FILTER (WHERE circuit_until>clock_timestamp()),count(*) FROM public.pr_discord_rate_state GROUP BY kind""").fetchall()
            # The coordinator's own clock: every admission reserved during the run (rows still in the table at the end).
            start = self.config.get('runStartedAt') or 0
            admitted = [float(t) for (t,) in db.execute(
                """SELECT extract(epoch from reserved_at)::double precision FROM public.pr_discord_request_admissions
                   WHERE reserved_at >= to_timestamp(%s) ORDER BY 1""", (start,)).fetchall()]
            by_kind = dict(db.execute("""SELECT coalesce(credential_kind,'?'),count(*) FROM public.pr_discord_request_admissions
                   WHERE reserved_at >= to_timestamp(%s) GROUP BY 1""", (start,)).fetchall())
            # Admission to observation (d): while a request is in flight its admission stays pending, and a window
            # restart charges it again (cap - pending), so the usable rate is about cap / (1 + mean d).
            held = [float(d) for (d,) in db.execute(
                """SELECT extract(epoch from outcome_at - reserved_at)::double precision
                   FROM public.pr_discord_request_admissions
                   WHERE reserved_at >= to_timestamp(%s) AND outcome_at IS NOT NULL AND state = 'observed'""",
                (start,)).fetchall()]  # answered requests only: a blocked permit was never in flight
            admission_window = {'count': len(admitted), 'byCredential': by_kind,
                                'peakTrailingSecond': analysis.peak_trailing(admitted, 1.0),
                                'peakCalendarSecond': analysis.peak_calendar_second(admitted),
                                'admissionToOutcomeSeconds': analysis.describe(held) if held else None}
            slow = []
            if self.config.get('pgStatStatements'):
                try:
                    slow = [{'query': q, 'calls': c, 'meanMs': m, 'maxMs': x} for q, c, m, x in db.execute(
                        """SELECT query,calls,mean_exec_time,max_exec_time FROM pg_stat_statements
                           ORDER BY max_exec_time DESC LIMIT 15""").fetchall()]
                except Exception:
                    slow = []
        manifest = analysis.load_jsonl(self.dir / 'seed-manifest.jsonl')
        by_job = {row['job']: row['post'] for row in manifest}
        by_post, notes = {}, {}
        dead = 0
        for job_id, state, dead_letter, checks, next_action, intents in jobs:
            post = by_job.get(job_id)
            if post is None:
                continue
            by_post[post] = state
            dead += bool(dead_letter)
            if state != 'verified':
                notes[post] = {'state': state, 'checks': checks, 'nextAction': next_action, 'intents': intents}
        (self.dir / 'final-states.json').write_text(json.dumps({'byPost': by_post, 'deadLetters': dead, 'notVerified': notes}))
        log_errors, slow_lines = {}, 0
        if self.cluster is not None and self.cluster.logfile.exists():
            text = self.cluster.logfile.read_text(errors='replace')
            shutil.copy(self.cluster.logfile, self.dir / 'postgres.log')
            for line in text.splitlines():
                match = re.match(r'^\S+ \S+ \S+ \[\d+\] (\w{5}) (ERROR|FATAL|PANIC):', line)
                if match and match.group(1) != '00000':
                    log_errors[match.group(1)] = log_errors.get(match.group(1), 0) + 1
                if 'duration:' in line:
                    slow_lines += 1
        extra = {'admissionsByState': admissions, 'rateStateHolds': [
            {'kind': k, 'manualHold': h, 'blocked': b, 'circuit': c, 'rows': n} for k, h, b, c, n in holds],
            'slowestStatements': slow, 'logErrorsBySqlstate': log_errors, 'statementsOverOneSecond': slow_lines,
            'lockInjections': self.lock_windows, 'kills': self.kills, 'admissionWindow': admission_window}
        (self.dir / 'database-final.json').write_text(json.dumps(extra, default=str))

    def shutdown_children(self):
        self.cron_stop.set()
        deadline = time.time() + 120
        while self.alive() and time.time() < deadline:
            self.reap()
            time.sleep(1)
        for name, item in self.alive():
            item['process'].kill()
            self.event(event='killed', name=name, reason='end_of_run', at=time.time())
        self.reap()
        if getattr(self, 'mock_process', None) and self.mock_process.poll() is None:
            try:
                import urllib.request
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                opener.open('http://127.0.0.1:%d/__harness/shutdown' % self.mock_port, timeout=10).read()
            except Exception:
                self.mock_process.terminate()
            try:
                self.mock_process.wait(60)
            except subprocess.TimeoutExpired:
                self.mock_process.kill()
        try:
            mock_cpu = json.loads((self.dir / 'mock' / 'mock-process.json').read_text())['cpuSeconds']
            self.config['mockCpuSeconds'] = mock_cpu
        except (OSError, ValueError, KeyError):
            pass
        if getattr(self, 'bouncer_process', None) and self.bouncer_process.poll() is None:
            self.bouncer_process.terminate()
        if getattr(self, 'pooler_process', None) and self.pooler_process.poll() is None:
            self.pooler_process.terminate()
            try:
                self.pooler_process.wait(30)
            except subprocess.TimeoutExpired:
                self.pooler_process.kill()

    def cleanup(self):
        for process in self.children:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        with self.inv_lock:
            for item in self.invocations.values():
                if item['process'].poll() is None:
                    try:
                        item['process'].kill()
                    except OSError:
                        pass
        if self.cluster is not None:
            self.cluster.close()
            self.cluster = None
        if getattr(self, 'external_db', None) and not self.args.keep_database:
            try:
                cluster_tools.drop_database(self.args.admin_database_url, self.external_db)
            except Exception as error:
                self.log('could not drop %s: %s' % (self.external_db, error))

    # -- the run ------------------------------------------------------------------------------------------------

    def run(self):
        threads = []
        try:
            self.prepare()
            self.database()
            self.pooler()
            self.write_environments()
            self.mock()
            self.seed()
            self.start_mock()
            self.config['runStartedAt'] = time.time()
            (self.dir / 'config.json').write_text(json.dumps(self.config, indent=1, default=str))
            for target in [self.sampler, self.cron] + ([self.crash_injector] if (self.s['kills'] or self.s['kill_at_create']) else []) + \
                    ([self.lock_injector] if self.s['lock_injection'] else []):
                thread = threading.Thread(target=target, name=target.__name__, daemon=True)
                thread.start()
                threads.append(thread)
            self.watch()
            self.shutdown_children()
            self.stop.set()
            for thread in threads:
                thread.join(timeout=30)
            self.collect()
            self.config['loadAtEnd'] = open('/proc/loadavg').read().strip()
            (self.dir / 'config.json').write_text(json.dumps(self.config, indent=1, default=str))
        except BaseException as error:
            self.config['harnessError'] = '%s: %s' % (type(error).__name__, error)
            self.log('harness error: %s\n%s' % (error, traceback.format_exc()))
            raise
        finally:
            self.stop.set()
            self.cron_stop.set()
            self.cleanup()
            (self.dir / 'config.json').write_text(json.dumps(self.config, indent=1, default=str))
        return finish(self.dir)


def machine_description():
    """Where this run executes, from the environment (a receipt must not misdescribe its machine)."""
    machine = {'cpus': os.cpu_count(), 'memGb': round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2 ** 30, 1)}
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        machine.update(kind='github-actions', runnerEnvironment=os.environ.get('RUNNER_ENVIRONMENT') or 'unknown',
                       runnerName=os.environ.get('RUNNER_NAME'), runnerOs=os.environ.get('RUNNER_OS'),
                       runnerArch=os.environ.get('RUNNER_ARCH'), image=os.environ.get('ImageOS'),
                       imageVersion=os.environ.get('ImageVersion'))
    else:
        machine['kind'] = 'local'
    return machine


def machine_line(result, config):
    m = config.get('machine') or {}
    load = 'one-minute load %s at start, peak %s during the run' % ((config.get('loadAtStart') or '?').split()[0],
                                                                    result.get('machineLoad1Max'))
    if m.get('kind') == 'github-actions':
        where = ('a GitHub Actions runner (%s; runner %s, %s %s, image %s %s), %s vCPU and %s GB' % (
            'GitHub-hosted: a fresh VM for this job alone' if m.get('runnerEnvironment') == 'github-hosted'
            else 'runner environment %s' % m.get('runnerEnvironment'), m.get('runnerName'), m.get('runnerOs'),
            m.get('runnerArch'), m.get('image'), m.get('imageVersion'), m.get('cpus'), m.get('memGb')))
    else:
        where = ('a %s-core, %s GB machine outside GitHub Actions (the development sandbox is shared with other '
                 'agents, so its throughput figures are not evidence)' % (m.get('cpus'), m.get('memGb')))
    return ('Machine: %s; %s. Every process of the run (database, pooler, mock Discord, every invocation) shares it; '
            'Vercel runs each invocation on its own instance. CPU contention here can only slow the lane.' % (where, load))


def differences(result, config):
    s = config['settings']
    items = [
        machine_line(result, config),
        'Database: %s, PostgreSQL %s, on the same machine (production: Supabase PostgreSQL 17.6 on Micro compute, '
        'max_connections 60, across the network). Pooler: %s; production uses Supavisor in transaction mode with TLS. '
        'Network latency is emulated at %.1f ms per round trip with %d round trips per new connection; real '
        'Supabase latency and its variance were not measured.' % (
            config.get('database'), config.get('serverVersion'), config.get('pooler'), s['db_latency_ms'], s['db_connect_rtts']),
        'Discord: a mock on 127.0.0.1 (%s ms per request, plain HTTP, no TLS); it implements a 50/s global limit per '
        'trailing second, 5 creates per 5 s per channel and %s per read route. Real Discord latency, its real bucket '
        'sizes, Cloudflare and shared egress IPs were not exercised.' % (s['mock_latency'], s['mock_read_limit']),
        'Invocations: fresh OS processes started %.0f s before their cron time and importing api/index.py first; '
        'the runtime itself is built inside the request (cold %s). Vercel cold starts (container start, network '
        'attach), Fluid compute co-location of invocations and cron delivery delays were not reproduced (cron jitter '
        'here: uniform %s s).' % (PRESPAWN_SECONDS, s['invocation_mode'] == 'cold', list(s['cron_jitter'])),
        'Data: synthetic workspaces made by the application\'s own connect, review and approval code; one text '
        'channel per server; no media; no other provider\'s jobs compete in the minute worker; workspace documents '
        'are smaller than long-lived production ones.',
        'Rate policy: app_capacity %d per %s-second fixed window (%s); production policy uses the same tool and '
        'defaults.' % (config['ratePolicy']['app_capacity'], config['ratePolicy']['app_window_seconds'],
                       'INFORMATION ONLY, not a reviewed setting' if config.get('informationOnly') else 'the reviewed value'),
    ]
    if config.get('sourceDirty'):
        items.insert(0, 'The source tree had uncommitted changes: this receipt does not describe a commit.')
    if result['scenario'] not in ('S1', 'S2', 'S3'):
        items.append('Scenario %s is not the section 4 stress scenario; section 4 PASS/FAIL lines are NOT APPLICABLE '
                     'unless listed.' % result['scenario'])
    return items


def recover(run_dir):
    """Collect what an interrupted run left (a container restart kills every process but keeps /tmp): restart the
    throwaway cluster from its data directory, read the final job states and database figures, stop it, and use the
    mock's checkpointed request log. The receipt then says PARTIAL and where the run was cut."""
    run_dir = Path(run_dir)
    config = json.loads((run_dir / 'config.json').read_text())
    directory = config.get('clusterDirectory')
    if not directory or not Path(directory, 'data').exists():
        raise SystemExit('no throwaway cluster directory left for %s' % run_dir)
    mock_dir = run_dir / 'mock'
    if not (mock_dir / 'mock-requests.jsonl').exists() and (mock_dir / 'mock-requests.partial.jsonl').exists():
        shutil.copy(mock_dir / 'mock-requests.partial.jsonl', mock_dir / 'mock-requests.jsonl')
    if not (mock_dir / 'mock-summary.json').exists() and (mock_dir / 'mock-live.json').exists():
        shutil.copy(mock_dir / 'mock-live.json', mock_dir / 'mock-summary.json')
    runas = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else []
    pg_ctl = str(Path(config['clusterPgBin']) / 'pg_ctl')
    data = str(Path(directory) / 'data')
    try:
        os.unlink(Path(data) / 'postmaster.pid')
    except OSError:
        pass
    subprocess.run([*runas, pg_ctl, '-D', data, '-l', str(Path(directory) / 'postgres.log'), '-w', '-t', '60', 'start'],
                   check=True, stdout=subprocess.DEVNULL)
    try:
        shell = Harness.__new__(Harness)
        shell.dir, shell.config, shell.kills, shell.lock_windows = run_dir, config, [], []
        shell.cluster = type('C', (), {'logfile': Path(directory) / 'postgres.log'})()
        shell.admin_dsn = 'host=%s port=%s dbname=postgres user=postgres' % (Path(directory) / 'sock', config['clusterPort'])
        if not (run_dir / 'final-states.json').exists():
            Harness.collect(shell)
    finally:
        subprocess.run([*runas, pg_ctl, '-D', data, '-m', 'immediate', '-w', 'stop'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    shutil.rmtree(directory, ignore_errors=True)
    config.pop('harnessError', None)
    config['endReason'] = 'INTERRUPTED (partial: %s); collected afterwards' % config.get('interruptedNote', 'the run was cut short')
    config['partial'] = True
    (run_dir / 'config.json').write_text(json.dumps(config, indent=1, default=str))
    return finish(run_dir)


def finish(run_dir):
    run_dir = Path(run_dir)
    config = json.loads((run_dir / 'config.json').read_text())
    if config.get('harnessError') or not (run_dir / 'final-states.json').exists():
        (run_dir / 'RECEIPT.md').write_text('# Capacity receipt: %s\n\nThe harness did not complete: %s\n\nNothing was '
                                            'measured; no PASS is claimed.\n' % (config.get('label'), config.get('harnessError')))
        return {'scenario': config.get('scenario'), 'error': config.get('harnessError')}
    result = analysis.analyse(str(run_dir))
    standard = json.loads(STANDARD.read_text())
    verdicts = analysis.judge(result, standard)
    expectations = analysis.expectations(result, config, standard)
    result['verdicts'] = verdicts
    result['expectations'] = expectations
    text = analysis.receipt(result, verdicts, config, differences(result, config), expectations)
    for private in [key for key in result if key.startswith('_')]:
        del result[private]
    (run_dir / 'result.json').write_text(json.dumps(result, indent=1, default=str))
    (run_dir / 'RECEIPT.md').write_text(text)
    return result


def settings_for(name, overrides):
    if name not in SCENARIOS:
        raise SystemExit('unknown scenario %s; choose from %s' % (name, ', '.join(SCENARIOS)))
    settings = copy.deepcopy(BASE)
    settings.update(copy.deepcopy(SCENARIOS[name]))
    for key, value in overrides.items():
        if value is not None:
            settings[key] = value
    return settings


def overrides_from(args):
    keys = ('workspaces', 'posts', 'hot_posts', 'lane_max_seconds', 'lane_max_steps', 'shards', 'policy_capacity',
            'mock_latency', 'mock_tail_probability', 'mock_tail_ms', 'mock_read_limit', 'db_latency_ms',
            'db_connect_rtts', 'max_db_connections', 'pool_wait_timeout', 'cron_period', 'max_duration',
            'invocation_mode', 'lead_seconds', 'max_run_minutes', 'fixed_run_minutes', 'seed_processes',
            'double_accept_every', 'worker_max_jobs', 'worker_max_seconds', 'db_statement_timeout_ms')
    values = {key: getattr(args, key, None) for key in keys}
    if getattr(args, 'lane', None) is not None:
        values['lane'] = args.lane == 'on'
    if getattr(args, 'cron_jitter', None):
        low, high = (float(x) for x in args.cron_jitter.split(':'))
        values['cron_jitter'] = (low, high)
    if getattr(args, 'information_only', False):
        values['information_only'] = True
    for item in getattr(args, 'set', None) or []:
        key, _, raw = item.partition('=')
        if key not in BASE:
            raise SystemExit('--set: unknown setting %s' % key)
        values[key] = json.loads(raw)  # e.g. --set 'stall=[0,4]' --set 'kills=[1,2]' (a scaled-down validation)
    return values


def run_one(args, name):
    settings = settings_for(name, overrides_from(args))
    if name == 'baseline' and getattr(args, 'baseline_source_tree', None):
        args = copy.copy(args)
        args.source_tree = args.baseline_source_tree
    if settings['policy_capacity'] != 25:
        settings['information_only'] = True
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_dir = Path(args.out) / ('%s-%s-%s' % (stamp, name, (args.label or 'run').replace(' ', '_')))
    harness = Harness(args, settings, name, run_dir)
    ACTIVE.append(harness)
    try:
        result = harness.run()
    finally:
        ACTIVE.remove(harness)
    print(json.dumps({'event': 'run.done', 'dir': str(run_dir), 'scenario': name,
                      'verdicts': [(v['id'], v['verdict']) for v in result.get('verdicts', [])],
                      'expectations': [(e['id'], e['verdict']) for e in result.get('expectations', [])]}), flush=True)
    return run_dir, result


def suite_receipt(out, profile, runs, planned):
    lines = ['# Capacity suite receipt: profile `%s`' % profile, '',
             'Generated %s by `scripts/discord_lane_capacity_run.py profile`. One line per planned scenario; a scenario '
             'that did not run says NOT RUN and claims nothing.' % now_iso(), '',
             '| Scenario | Run | Source SHA | Standard (PASS/FAIL/NOT MEASURED) | Expected behaviour | Load peak |',
             '|---|---|---|---|---|---|']
    for name in planned:
        entry = runs.get(name)
        if not entry:
            lines.append('| %s | NOT RUN | | | | |' % name)
            continue
        run_dir, result = entry
        if result.get('error') or 'verdicts' not in result:
            lines.append('| %s | `%s` | | HARNESS ERROR: %s | | |' % (name, run_dir.name, result.get('error')))
            continue
        counts = {}
        for v in result['verdicts']:
            counts[v['verdict']] = counts.get(v['verdict'], 0) + 1
        expect = {}
        for e in result['expectations']:
            expect[e['verdict']] = expect.get(e['verdict'], 0) + 1
        lines.append('| %s | `%s` | `%s` | %s | %s | %s |' % (
            name, run_dir.name, (result.get('sourceSha') or '')[:12],
            ', '.join('%s %d' % item for item in sorted(counts.items()) if item[0] != 'NOT APPLICABLE'),
            ', '.join('%s %d' % item for item in sorted(expect.items())), result.get('machineLoad1Max')))
    lines.append('')
    Path(out, 'SUITE-%s.md' % profile).write_text('\n'.join(lines) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    def common(p):
        p.add_argument('--source-tree', required=True, help='checkout of the SHA under test (read only)')
        p.add_argument('--out', required=True, help='directory for run directories')
        p.add_argument('--label')
        p.add_argument('--pg-bin', help='PostgreSQL server binaries (default POSTRIFF_PG_BIN)')
        p.add_argument('--admin-database-url', help='external database for setup, seeding and sampling (superuser)')
        p.add_argument('--database-url', help='external database URL the application uses (e.g. through a pooler)')
        p.add_argument('--keep-database', action='store_true', help='external mode: keep the per-run database')
        p.add_argument('--pooler-admin-url', help='PgBouncer admin console URL to sample SHOW POOLS each second')
        p.add_argument('--pooler', choices=('harness', 'pgbouncer'), default='harness',
                       help='local cluster only: the harness transaction pooler (default) or a real PgBouncer')
        p.add_argument('--pgbouncer-bin', default='/usr/sbin/pgbouncer')
        for name, kind in (('workspaces', int), ('posts', int), ('hot-posts', int), ('lane-max-seconds', float),
                           ('lane-max-steps', int), ('shards', int), ('policy-capacity', int), ('mock-latency', str),
                           ('mock-tail-probability', float), ('mock-tail-ms', float), ('mock-read-limit', str),
                           ('db-latency-ms', float), ('db-connect-rtts', float), ('max-db-connections', int),
                           ('pool-wait-timeout', float), ('cron-period', int), ('max-duration', float),
                           ('lead-seconds', float), ('max-run-minutes', float), ('fixed-run-minutes', float),
                           ('seed-processes', int), ('double-accept-every', int), ('worker-max-jobs', int),
                           ('worker-max-seconds', float), ('db-statement-timeout-ms', int)):
            p.add_argument('--' + name, type=kind)
        p.add_argument('--invocation-mode', choices=('cold', 'warm'))
        p.add_argument('--lane', choices=('on', 'off'))
        p.add_argument('--cron-jitter', help='LOW:HIGH seconds of cron delivery delay (default 0:1)')
        p.add_argument('--information-only', action='store_true')
        p.add_argument('--set', action='append', help="override any scenario setting with JSON, e.g. --set 'stall=[0,4]'")
    run = sub.add_parser('run', help='run one scenario')
    run.add_argument('--scenario', required=True, choices=sorted(SCENARIOS))
    common(run)
    check = sub.add_parser('seed-check', help="only a scenario's seeding (its layout and seed processes), then clean up")
    check.add_argument('--scenario', required=True, choices=sorted(SCENARIOS))
    common(check)
    profile = sub.add_parser('profile', help='run a list of scenarios and write SUITE-<name>.md')
    profile.add_argument('--name', required=True, choices=sorted(PROFILES))
    profile.add_argument('--only', help='comma-separated subset of the profile')
    profile.add_argument('--baseline-source-tree', help='the frozen tree for the baseline scenario (RC1)')
    common(profile)
    again = sub.add_parser('analyze', help='recompute result.json and RECEIPT.md for a finished run directory')
    again.add_argument('run_dir')
    again.add_argument('--recover', action='store_true',
                       help='an interrupted run: restart its leftover throwaway cluster, collect, then analyse (PARTIAL)')
    sub.add_parser('scenarios', help='list scenarios and profiles')
    args = parser.parse_args(argv)
    if args.command == 'scenarios':
        for name, spec in SCENARIOS.items():
            print('%-10s %s' % (name, spec.get('description', '')))
        for name, items in PROFILES.items():
            print('profile %-9s %s' % (name, ', '.join(items)))
        return 0
    if args.command == 'analyze':
        result = recover(args.run_dir) if args.recover else finish(args.run_dir)
        print(json.dumps({'verdicts': [(v['id'], v['verdict']) for v in result.get('verdicts', [])],
                          'expectations': [(e['id'], e['verdict']) for e in result.get('expectations', [])]}))
        return 0

    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)

    def end_early(signum, frame):  # stop the crons now, then collect and analyse what ran
        for harness in list(ACTIVE):
            harness.end_requested = True
    signal.signal(signal.SIGUSR1, end_early)
    os.makedirs(args.out, exist_ok=True)
    if args.command == 'run':
        run_one(args, args.scenario)
        return 0
    if args.command == 'seed-check':
        settings = settings_for(args.scenario, overrides_from(args))
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run_dir = Path(args.out) / ('%s-seedcheck-%s-%s' % (stamp, args.scenario, (args.label or 'run').replace(' ', '_')))
        harness = Harness(args, settings, args.scenario, run_dir)
        ACTIVE.append(harness)
        try:
            print(json.dumps(harness.seed_check()), flush=True)
        finally:
            ACTIVE.remove(harness)
        return 0
    planned = PROFILES[args.name] if not args.only else [n for n in args.only.split(',') if n]
    runs = {}
    for name in planned:
        try:
            runs[name] = run_one(args, name)
        except KeyboardInterrupt:
            break
        except Exception as error:  # the suite goes on; the receipt says this scenario errored
            runs[name] = (Path(args.out) / name, {'error': '%s: %s' % (type(error).__name__, error)})
        suite_receipt(args.out, args.name, runs, planned)
    suite_receipt(args.out, args.name, runs, planned)
    return 0


if __name__ == '__main__':
    sys.exit(main())
