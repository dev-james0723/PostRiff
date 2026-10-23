"""H-07 isolated drills: inject each alert condition into a disposable PostgreSQL with a mock Discord, read it through the
real health payload code (src/postriff_phase2/discord/ops.py; over the real route and loopback HTTP where it matters),
run the evaluator (scripts/discord_ops_check.py) and record: detected in one evaluation, at the expected severity, no
false alarm on the healthy baseline, cleared after recovery. Then the operations: the phone runbook's hold statements
run verbatim in a separate session (as the SQL editor would), and the rollback order.

    POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin PYTHONPATH=src:tests python tests/discord_ops_drills.py --out FILE [--only D1,O1]

Each drill starts from an empty database (re-runnable from scratch); the receipt JSON is rewritten after every drill,
so an interrupted run keeps what finished. Nothing reads a credential or reaches a network except 127.0.0.1. Where a
drill cannot wait (15-minute windows, a quiet minute), it moves the coordinator ledger's timestamps into the past and
says so under `simulated`. The lane's own safety properties (exactly once, rollback, recovery) are the W-02 tests'
(tests/test_discord_parallel_lane_postgres.py) and are referenced, not repeated.
"""
import argparse
import importlib.util
import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import discord_lane_fixture as F  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import request_metrics, security_signals  # noqa: E402
from postriff_phase2.discord import launch_gate, ops  # noqa: E402
from postriff_phase2.discord.oauth import DiscordConnections  # noqa: E402
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, RateDelayed, SharedPostgresBudget  # noqa: E402
from postriff_phase2.hosted import PostgresWorkspaceRepository  # noqa: E402
from postriff_phase2.hosted_social import HostedSocial  # noqa: E402
from postriff_phase2.social_connectors import DiscordProvider  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load('discord_ops_check', ROOT / 'scripts/discord_ops_check.py')
POLICY = _load('discord_rate_policy', ROOT / 'scripts/discord_rate_policy.py')
THRESHOLDS = check.load_thresholds()
RUNBOOK = ROOT / 'docs/ops/PHONE-RUNBOOK.md'
SNAPSHOT_SQL = ROOT / 'docs/ops/discord-ops-snapshot.sql'
SECRET = 'drill-cron-secret-' + 'x' * 16
MIGRATION_060 = ROOT / 'migrations/postriff/060_founder_reliability.sql'


def source_revision():
    try:
        return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:
        return None


VALUES = {**F.LANE_ENV, 'VERCEL_ENV': 'production', 'POSTRIFF_DISCORD_CONNECT_WORKSPACES': '*',
          'POSTRIFF_DISCORD_GUILD_CAP': '10000', 'VERCEL_GIT_COMMIT_SHA': source_revision() or ''}


def runbook_statements(path=RUNBOOK):
    """The labelled SQL blocks of the phone runbook, verbatim."""
    found = {}
    for block in re.findall(r'```sql\n(.*?)```', path.read_text(), re.S):
        match = re.match(r'-- H07:([A-Z_]+)', block)
        if match:
            found[match.group(1)] = block
    return found


def social(cluster, tenants, wire, *, capacity=200, days=20.0, issued=None, reviewed=True, rate_limits=True, **overrides):
    """The fixture's provider with a policy that is valid for `days` from `issued` (the database clock by default)."""
    provider = DiscordProvider(F.APP, 'synthetic-secret', 'synthetic-bot-token', 'https://rafii.example.invalid',
                               transport=wire, production_reviewed=reviewed)
    provider.authorization_v2_enabled = provider.connections_v2_enabled = True
    provider.rate_v1_enabled = rate_limits
    at = cluster.now() if issued is None else issued
    raw = json.dumps(POLICY.build(at, days=days, revision='h07-drill', app_capacity=capacity, **overrides))
    provider.rate_limiter = SharedPostgresBudget(cluster.factory(), F.APP, policy=raw) if rate_limits else None
    return HostedSocial(F.Grants(tenants), {'discord': provider})


class Captured(logging.Handler):
    """The function log lines a drill produced (the 'postriff.request' logger), as text."""
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def __enter__(self):
        logging.getLogger('postriff.request').addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger('postriff.request').removeHandler(self)


class Lab:
    def __init__(self):
        self.cluster = F.Cluster()
        done = subprocess.run([str(Path(F.PG_BIN) / 'psql'), self.cluster.dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f',
                               str(MIGRATION_060)], capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError('migration 060 failed: ' + done.stderr[-500:])
        self.wire = self.hosted = self.worker = None

    def close(self):
        self.cluster.close()

    def fresh(self, tenants=(), posts=0, *, due_ago=30, latency=0.0, **setup):
        self.cluster.reset()
        self.sql('TRUNCATE public.pr_request_metrics, public.pr_operational_snapshots')
        self.sql('DELETE FROM public.pr_memberships')
        tenants = list(tenants)
        if tenants and posts:
            at = self.cluster.now() - due_ago
            F.seed(self.cluster, tenants, posts, now=at - 300, at=at)
        self.tenants = tenants
        self.wire = F.MockDiscord(tenants, latency=latency)
        self.hosted = social(self.cluster, tenants, self.wire, **setup)
        self.worker = F.base_worker(self.cluster, self.hosted)
        return self

    def provider(self):
        return self.hosted.providers['discord']

    def sql(self, statement, params=None):
        """One statement in its own autocommit session, as the Supabase SQL editor runs it."""
        with self.cluster.connect(autocommit=True) as db:
            cur = db.execute(statement, params)
            return cur.fetchall() if cur.description else []

    def look(self, phase='pre_open', values=None, thresholds=None, worker=None):
        snapshot = ops.snapshot(worker or self.worker, values or VALUES)
        alerts = check.evaluate(snapshot, thresholds or THRESHOLDS, now=self.cluster.now(), phase=phase)
        return snapshot, alerts

    def shift_ledger(self, seconds):
        """Simulated time for the coordinator ledger: every admission moves `seconds` into the past."""
        self.sql('''UPDATE public.pr_discord_request_admissions SET reserved_at = reserved_at - make_interval(secs => %(s)s),
                    expires_at = expires_at - make_interval(secs => %(s)s), sealed_at = sealed_at - make_interval(secs => %(s)s),
                    sent_at = sent_at - make_interval(secs => %(s)s), outcome_at = outcome_at - make_interval(secs => %(s)s)''',
                 {'s': seconds})

    def states(self):
        return Counter(job['state'] for job in F.jobs(self.cluster).values())

    def drain(self, loops=4, seconds=30):
        results, failures = F.run_lanes(self.worker, loops, seconds=seconds)
        return results, failures

    def sql_twin(self):
        return self.sql(SNAPSHOT_SQL.read_text())[0][0]


def severities(alerts):
    return {alert['id']: alert['severity'] for alert in alerts}


class Drill:
    def __init__(self, ident, cls, title):
        self.record = {'id': ident, 'class': cls, 'title': title, 'steps': [], 'checks': [], 'simulated': [],
                       'references': []}
        self.started = time.monotonic()

    def step(self, name, alerts, **counts):
        self.record['steps'].append({'step': name, 'alerts': severities(alerts), 'counts': counts})

    def expect(self, name, condition, observed=None):
        self.record['checks'].append({'check': name, 'pass': bool(condition), 'observed': observed})
        return bool(condition)

    def fires(self, alerts, rule, severity, when):
        found = severities(alerts).get(rule)
        return self.expect('%s: %s is %s' % (when, rule, severity), found == severity, found)

    def silent(self, alerts, when, *, allowed=()):
        noisy = {k: v for k, v in severities(alerts).items() if v in ('page', 'warn') and k not in allowed}
        return self.expect('%s: no warn or page alert%s' % (when, (' besides ' + ', '.join(allowed)) if allowed else ''),
                           not noisy, noisy)

    def done(self):
        self.record['seconds'] = round(time.monotonic() - self.started, 1)
        self.record['result'] = 'PASS' if self.record['checks'] and all(c['pass'] for c in self.record['checks']) else 'FAIL'
        return self.record


# --- the drills -------------------------------------------------------------------------------------------------------

def d0_baseline(lab):
    d = Drill('D0', 'BASELINE', 'A healthy run raises nothing; the SQL twin agrees with the payload')
    tenants = [F.Tenant(n) for n in range(6)]
    lab.fresh(tenants, 2)
    results, failures = lab.drain()
    snapshot, alerts = lab.look()
    states = lab.states()
    d.step('after a normal drain', alerts, verified=states.get('verified', 0), creates=snapshot['deliveries']['creates'],
           accepted=snapshot['deliveries']['accepted'], dueWorkspaces=snapshot['queue']['dueWorkspaces'],
           duplicates=lab.wire.duplicates())
    d.expect('every post verified once, no duplicate', states == Counter(verified=12) and lab.wire.duplicates() == 0,
             dict(states))
    d.expect('lane loops ended normally', not failures and {r['stoppedBy'] for r in results} <= {'idle', 'time_budget'},
             sorted({r['stoppedBy'] for r in results}))
    d.silent(alerts, 'healthy baseline')
    d.expect('payload saw 12 accepted creates', snapshot['deliveries']['accepted'] == 12, snapshot['deliveries']['accepted'])
    d.expect('payload sections all observed', snapshot['errors'] == [], snapshot['errors'])
    text = json.dumps(snapshot)
    leaked = [value for t in tenants for value in (t.id, t.guild, t.channel) if value in text]
    d.expect('no workspace, server or channel id in the payload', not leaked, len(leaked))
    twin = lab.sql_twin()
    pairs = {'queue.dueWorkspaces': (twin['queue']['dueWorkspaces'], snapshot['queue']['dueWorkspaces']),
             'deliveries.creates': (twin['deliveries']['creates'], snapshot['deliveries']['creates']),
             'deliveries.accepted': (twin['deliveries']['accepted'], snapshot['deliveries']['accepted']),
             'deliveries.uncertain': (twin['deliveries']['uncertain'], snapshot['deliveries']['uncertain']),
             'traffic.invalid10m': (twin['coordinator']['traffic']['invalid10m'],
                                    snapshot['coordinator']['traffic']['invalid10m']),
             'guards.policy.hold': (twin['coordinator']['guards']['policy']['hold'],
                                    snapshot['coordinator']['guards']['policy']['hold']),
             'guards.invalid.remainingRatio': (float(twin['coordinator']['guards']['invalid']['remainingRatio']),
                                               snapshot['coordinator']['guards']['invalid']['remainingRatio']),
             'servers.used': (twin['servers']['used'], snapshot['config']['servers']['used'])}
    d.expect('the SQL twin reports the same counts as the payload', all(a == b for a, b in pairs.values()),
             {k: list(v) for k, v in pairs.items()})
    age = abs(float(twin['progress']['lastReadbackAgeSeconds']) - snapshot['progress']['lastReadbackAgeSeconds'])
    d.expect('the SQL twin ages agree within 5 s', age < 5, round(age, 2))
    d.silent(check.evaluate(twin, THRESHOLDS, now=lab.cluster.now()), 'the SQL twin on the healthy baseline')
    return d.done()


def d1_backlog(lab):
    d = Drill('D1', 'BACKLOG', 'Late work is detected at warn and page levels while senders still make progress')
    for due_ago, severity in ((1000, 'page'), (400, 'warn')):
        lab.fresh([F.Tenant(n) for n in range(40)], 1, due_ago=due_ago, latency=0.05)
        before, alerts = lab.look()
        d.step('injected: 40 posts due %d s ago, nothing run yet' % due_ago, alerts,
               oldestDueLagSeconds=before['queue']['oldestDueLagSeconds'])
        F.run_lanes(lab.worker, 1, seconds=5)  # one shard for five seconds: progress, but not enough
        snapshot, alerts = lab.look()
        d.step('one shard ran for 5 s', alerts, oldestDueLagSeconds=snapshot['queue']['oldestDueLagSeconds'],
               dueWorkspaces=snapshot['queue']['dueWorkspaces'], lastClaimAgeSeconds=snapshot['progress']['lastClaimAgeSeconds'],
               verified=lab.states().get('verified', 0))
        d.fires(alerts, 'BACKLOG_LAG', severity, 'lag %d s with progress' % due_ago)
        d.expect('lag %d s with progress: not reported as a silent halt' % due_ago,
                 'SILENT_HALT_NO_PROGRESS' not in severities(alerts), severities(alerts).get('SILENT_HALT_NO_PROGRESS'))
        lab.drain(seconds=40)
        snapshot, alerts = lab.look()
        d.step('recovered: four shards drained the queue', alerts, dueWorkspaces=snapshot['queue']['dueWorkspaces'],
               verified=lab.states().get('verified', 0), duplicates=lab.wire.duplicates())
        d.expect('lag %d s: cleared after the drain' % due_ago, 'BACKLOG_LAG' not in severities(alerts), severities(alerts))
        d.silent(alerts, 'after the %d s drill' % due_ago)
    d.record['references'].append('the lane draining a burst exactly once: test_many_loops_create_every_post_exactly_once')
    return d.done()


def d2_delivery(lab):
    d = Drill('D2', 'DELIVERY', 'Uncertain and failed creates are split into system- and customer-caused')
    tenants = [F.Tenant(n) for n in range(10)]
    lab.fresh(tenants, 1)
    lost = {t.channel for t in tenants[:3]}
    refused = {t.channel for t in tenants[3:5]}

    def fail(method, path):
        parts = path.strip('/').split('/')
        if method == 'POST' and len(parts) == 3 and parts[0] == 'channels' and parts[2] == 'messages':
            if parts[1] in lost:
                raise ConnectionResetError('synthetic: the answer to a create was lost')
            if parts[1] in refused:
                return {'status': 403, 'headers': {}, 'body': {'message': 'Missing Permissions', 'code': 50013}}
    lab.wire.fail = fail
    lab.drain(loops=2, seconds=20)
    snapshot, alerts = lab.look()
    deliveries = snapshot['deliveries']
    d.step('injected: 3 creates lose their answer, 2 are refused 403 (bot lacks permission)', alerts,
           **{k: deliveries[k] for k in ('creates', 'accepted', 'uncertain', 'rejectedCustomer', 'rejectedSystem')},
           jobs=dict(lab.states()))
    d.fires(alerts, 'DELIVERY_UNCERTAIN', 'page', 'three uncertain creates')
    d.fires(alerts, 'DELIVERY_SYSTEM_FAILURES', 'warn', 'three system-caused failures of ten')
    d.expect('the 403s are counted as customer-caused, not ours', deliveries['rejectedCustomer'] == 2
             and deliveries['rejectedSystem'] == 0, [deliveries['rejectedCustomer'], deliveries['rejectedSystem']])
    d.expect('nothing was created twice', lab.wire.duplicates() == 0, lab.wire.duplicates())
    lab.shift_ledger(960)
    d.record['simulated'].append('recovery: the ledger rows were moved 16 minutes into the past (the 15-minute window '
                                 'cannot be waited out in a drill)')
    snapshot, alerts = lab.look()
    d.step('recovered: 16 minutes later (simulated), no new failures', alerts, uncertain=snapshot['deliveries']['uncertain'],
           uncertainJobsLeftForReconciliation=lab.states().get('uncertain', 0))
    d.expect('delivery alerts cleared', not {'DELIVERY_UNCERTAIN', 'DELIVERY_SYSTEM_FAILURES'} & set(severities(alerts)),
             severities(alerts))
    d.record['references'].append('an uncertain create is never sent again: test_a_loop_that_dies_after_discord_accepted_'
                                  'never_causes_a_second_post; the jobs stay uncertain for read-back reconciliation')
    return d.done()


def d3_rate_limit(lab):
    d = Drill('D3', 'RATE_LIMIT', 'Invalid-request budget, a global 429, policy expiry and a spent application budget')
    # (a) the invalid-request budget: 16 of 20 spent in a 10-second window
    lab.fresh(invalid_capacity=20, invalid_window_seconds=10)
    _, alerts = lab.look()
    d.silent(alerts, 'invalid budget: before')
    limiter, identity = lab.provider().rate_limiter, lab.provider()._rate_identity('bot')
    for number in range(16):
        limiter.observe(limiter.reserve_read('GET', '/guilds/%d' % (6900000 + number), identity=identity),
                        {'status': 403, 'headers': {}})
    snapshot, alerts = lab.look()
    invalid = snapshot['coordinator']['guards']['invalid']
    d.step('injected: 16 invalid answers (403) of a 20-per-window budget', alerts, remainingRatio=invalid['remainingRatio'],
           remaining=invalid['remaining'], resetSeconds=invalid['resetSeconds'])
    d.fires(alerts, 'RATE_INVALID_BUDGET', 'page', 'invalid budget 20% left')
    time.sleep((invalid['resetSeconds'] or 0) + 0.5)
    snapshot, alerts = lab.look()
    d.step('recovered: the window reset', alerts, remainingRatio=snapshot['coordinator']['guards']['invalid']['remainingRatio'])
    d.expect('invalid budget alert cleared after the reset', 'RATE_INVALID_BUDGET' not in severities(alerts), severities(alerts))
    # (b) a global 429 with a six-second retry
    lab.fresh()
    limiter, identity = lab.provider().rate_limiter, lab.provider()._rate_identity('bot')
    limiter.observe(limiter.reserve_read('GET', '/guilds/6990001', identity=identity),
                    {'status': 429, 'headers': {'retry-after': '6', 'x-ratelimit-global': 'true', 'x-ratelimit-scope': 'global'},
                     'body': {'message': 'You are being rate limited.', 'retry_after': 6, 'global': True}})
    snapshot, alerts = lab.look()
    d.step('injected: a global 429, retry after 6 s', alerts,
           embargoSeconds=snapshot['coordinator']['guards']['global'].get('embargoSeconds'),
           responses429Global=snapshot['coordinator']['traffic']['responses429Global'])
    d.fires(alerts, 'RATE_EMBARGO', 'warn', 'global embargo active')
    d.fires(alerts, 'RATE_429', 'warn', 'one global 429 in 15 minutes')
    time.sleep(6.5)
    snapshot, alerts = lab.look()
    d.step('the embargo ended', alerts)
    d.expect('embargo alert cleared when it ended', 'RATE_EMBARGO' not in severities(alerts), severities(alerts))
    lab.shift_ledger(960)
    d.record['simulated'].append('the 429 count: ledger moved 16 minutes into the past')
    _, alerts = lab.look()
    d.expect('429 alert cleared after its window', 'RATE_429' not in severities(alerts), severities(alerts))
    # (c) the reviewed policy close to expiry, then renewed
    for days, severity in ((3.0, 'warn'), (0.5, 'page')):
        lab.fresh(days=days)
        snapshot, alerts = lab.look()
        d.step('injected: policy valid for %.1f more days' % days, alerts, daysLeft=snapshot['config']['policy']['daysLeft'],
               laneDaysLeft=snapshot['lane']['policyDaysLeft'])
        d.fires(alerts, 'RATE_POLICY', severity, 'policy %.1f days left' % days)
    lab.fresh(days=20.0)
    _, alerts = lab.look()
    d.expect('policy alert cleared after renewal (a new build with a new policy)', 'RATE_POLICY' not in severities(alerts),
             severities(alerts))
    # (d) the application budget spent for a whole minute: 2 requests a second, asked for continuously for 62 s
    lab.fresh(capacity=2)
    limiter, identity = lab.provider().rate_limiter, lab.provider()._rate_identity('bot')
    admitted, refused, number, until = 0, 0, 0, time.monotonic() + 62
    while time.monotonic() < until:
        number += 1
        try:
            permit = limiter.reserve_read('GET', '/guilds/%d' % (7100000 + number), identity=identity)
        except RateDelayed as error:
            refused += 1
            time.sleep(min(error.retry_after_seconds, 0.5))
            continue
        limiter.observe(permit, {'status': 200, 'headers': {}, 'body': {}})
        admitted += 1
    snapshot, alerts = lab.look()
    d.step('injected: 62 s of demand above a 2-per-second budget', alerts, admitted=admitted, refused=refused,
           admissions60s=snapshot['coordinator']['traffic']['admissions60s'])
    d.fires(alerts, 'RATE_APP_BUDGET_SPENT', 'warn', 'budget spent for the last minute')
    lab.shift_ledger(120)
    d.record['simulated'].append('the quiet minute after the demand: ledger moved 2 minutes into the past')
    _, alerts = lab.look()
    d.expect('budget alert cleared after a quiet minute', 'RATE_APP_BUDGET_SPENT' not in severities(alerts),
             severities(alerts))
    d.record['references'].append('loops sleep out an embargo or a spent budget instead of claiming: '
                                  'test_a_global_429_pauses_every_loop_without_a_retry_storm, '
                                  'test_a_spent_invalid_request_budget_is_waited_out_without_claiming')
    return d.done()


@contextmanager
def serving(app):
    """The real WSGI application on 127.0.0.1, for the checker's own HTTP fetch."""
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass
    server = make_server('127.0.0.1', 0, app, handler_class=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d%s' % (server.server_port, ops.ROUTE)
    finally:
        server.shutdown()
        server.server_close()


def d4_silent_halt(lab):
    from postriff_phase2.hosted_app import HostedApplication
    from types import SimpleNamespace
    d = Drill('D4', 'SILENT_HALT', 'Due work with no progress, a lane that cannot run, a payload that does not answer')
    # (a) due work, nothing claimed or admitted
    lab.fresh([F.Tenant(n) for n in range(5)], 1, due_ago=200)
    snapshot, alerts = lab.look()
    d.step('injected: 5 posts due 200 s ago, no sender ran', alerts, oldestDueLagSeconds=snapshot['queue']['oldestDueLagSeconds'],
           lastClaimAgeSeconds=snapshot['progress']['lastClaimAgeSeconds'],
           lastAdmissionAgeSeconds=snapshot['progress']['lastAdmissionAgeSeconds'])
    d.fires(alerts, 'SILENT_HALT_NO_PROGRESS', 'page', 'no progress')
    lab.drain()
    snapshot, alerts = lab.look()
    d.step('recovered: the shards ran', alerts, verified=lab.states().get('verified', 0))
    d.silent(alerts, 'after the shards ran')
    # (b) the lane flag on, the policy expired: nothing can send
    lab.fresh([F.Tenant(n) for n in range(2)], 1, issued=lab.cluster.now() - 3 * 86400, days=1.0)
    snapshot, alerts = lab.look()
    results, _ = F.run_lanes(lab.worker, 1, seconds=5)
    d.step('injected: lane flag on, reviewed policy expired two days ago', alerts, blocker=snapshot['lane']['blocker'],
           shardStoppedBy=results[0]['stoppedBy'] if results and results[0] else None,
           claimed=results[0]['counters']['claimed'] if results and results[0] else None)
    d.fires(alerts, 'SILENT_HALT_LANE_NOT_READY', 'page', 'lane not ready')
    d.fires(alerts, 'RATE_POLICY', 'page', 'policy not valid')
    lab.fresh([F.Tenant(n) for n in range(2)], 1)
    lab.drain()
    _, alerts = lab.look()
    d.expect('lane alerts cleared with a valid policy', not {'SILENT_HALT_LANE_NOT_READY', 'RATE_POLICY'} & set(severities(alerts)),
             severities(alerts))
    # (c) the payload over loopback HTTP: answering, a wrong secret, an unconfigured runtime, a dead database
    healthy = HostedApplication(service=object(), worker=lab.worker, cron_secret=SECRET)
    with serving(healthy) as url:
        answered = check.fetch(url, SECRET, timeout=10)
        wrong = check.fetch(url, 'not-the-secret-0123456789', timeout=10)
    alerts = check.evaluate(answered, THRESHOLDS, now=lab.cluster.now(), phase='pre_open')
    d.step('the real route over HTTP, right secret', alerts, observed=answered.get('observedAt') is not None)
    d.expect('route answers 200 with a snapshot', answered.get('kind') == ops.KIND, answered.get('kind'))
    d.silent(alerts, 'route answering')
    alerts = check.evaluate(wrong, THRESHOLDS, now=lab.cluster.now())
    d.step('a monitor with the wrong secret', alerts, reason=wrong.get('reason'))
    d.fires(alerts, 'SILENT_HALT_HEALTH_UNANSWERED', 'page', 'HTTP 401 is an alarm, not silence')
    with patch.dict(os.environ, {'POSTRIFF_DATABASE_URL': ''}), serving(HostedApplication(cron_secret=SECRET)) as url:
        unconfigured = check.fetch(url, SECRET, timeout=10)
    alerts = check.evaluate(unconfigured, THRESHOLDS, now=lab.cluster.now())
    d.step('a build whose runtime cannot start', alerts, reason=unconfigured.get('reason'))
    d.fires(alerts, 'SILENT_HALT_HEALTH_UNANSWERED', 'page', 'HTTP 503')

    def dead_database():
        import psycopg
        return psycopg.connect('host=127.0.0.1 port=9 dbname=postgres connect_timeout=1')
    dead = SimpleNamespace(social=lab.hosted, connection_factory=dead_database)
    with serving(HostedApplication(service=object(), worker=dead, cron_secret=SECRET)) as url:
        no_database = check.fetch(url, SECRET, timeout=10)
    alerts = check.evaluate(no_database, THRESHOLDS, now=lab.cluster.now())
    d.step('the database unreachable from the function', alerts, errors=no_database.get('errors'))
    d.fires(alerts, 'SILENT_HALT_DATABASE', 'page', 'database unreachable')
    # (d) the lane flag on and no shard invocation in the logs for 3 minutes, then shards running
    snapshot, _ = lab.look()
    snapshot['fleet'] = check.parse_logs([], 180)
    d.record['simulated'].append('the 3-minute log window without shard lines is an empty window passed to parse_logs')
    alerts = check.evaluate(snapshot, THRESHOLDS, now=lab.cluster.now())
    d.step('injected: no discord.lane.completed line in 180 s', alerts)
    d.fires(alerts, 'SILENT_HALT_NO_SHARDS', 'page', 'no shard lines')
    lab.fresh([F.Tenant(n) for n in range(3)], 1)
    with Captured() as captured:
        lab.drain(loops=3)
    snapshot, _ = lab.look()
    snapshot['fleet'] = check.parse_logs(captured.lines, 180)
    alerts = check.evaluate(snapshot, THRESHOLDS, now=lab.cluster.now())
    d.step('recovered: three shard invocations logged', alerts, laneLines=snapshot['fleet']['laneLines'])
    d.expect('no-shards alert cleared', 'SILENT_HALT_NO_SHARDS' not in severities(alerts), severities(alerts))
    d.record['references'].append('recovery after shard crons stopped and after an expired policy: '
                                  'test_recovery_after_the_shard_crons_stopped_for_minutes, '
                                  'test_recovery_after_the_policy_expired_drains_exactly_once')
    return d.done()


class DrillClock:
    def __init__(self):
        self.at = time.time()

    def __call__(self):
        return self.at


def d5_cross_tenant(lab):
    d = Drill('D5', 'CROSS_TENANT', 'Workspace refusals by the real membership gate: probing, a Discord route, a 4xx spike')
    a, b = F.Tenant(0), F.Tenant(1)
    lab.fresh([a, b], 1)
    lab.drain(loops=2)
    member = str(uuid.uuid4())
    lab.sql('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (member,))
    lab.sql('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (member,))
    lab.sql("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (b.id, member))
    repository = PostgresWorkspaceRepository(lab.cluster.factory(), verify_session=lambda token: member)
    discord = DiscordConnections(type('OAuthStub', (), {'repository': repository})())
    clock = DrillClock()

    def refused(call):
        try:
            call()
        except AlphaError as error:
            return error.status
        return None
    with patch.object(security_signals, 'SIGNAL', security_signals.DenialSignal(clock=clock)), Captured() as captured:
        with repository.transaction('synthetic-session', b.id) as (_cur, row, principal):
            own = row[0] is not None and principal == member
        snapshot, alerts = lab.look()
        d.step('baseline: a member opens their own workspace', alerts, lines=len(captured.lines))
        d.expect('their own workspace opens and logs nothing', own and not [l for l in captured.lines if security_signals.EVENT in l],
                 len(captured.lines))
        d.silent(alerts, 'cross-tenant baseline')
        statuses = Counter()
        for minute in range(3):
            for _ in range(12):
                statuses[refused(lambda: repository.transaction('synthetic-session', a.id).__enter__())] += 1
            clock.at += 60
        statuses[refused(lambda: discord.public_identities(a.id, 'synthetic-session'))] += 1
        snapshot, alerts = lab.look()
        security = snapshot['security']['instance']
        lines = [json.loads(l) for l in captured.lines if security_signals.EVENT in l]
        d.step('injected: one member asks for another workspace 36 times over 3 minutes, once on a Discord route', alerts,
               statuses=dict(statuses), lines=len(lines), deniedTotal=security['deniedTotal'],
               topActorDenials10m=security['topActorDenials10m'], discord=security['denied']['discord'])
        d.expect('every refusal is the uniform 403', statuses == Counter({403: 37}), dict(statuses))
        d.fires(alerts, 'CROSS_TENANT_PROBING', 'page', '37 refusals for one actor in 10 minutes')
        d.fires(alerts, 'CROSS_TENANT_DISCORD', 'warn', 'a refusal from the Discord code path')
        d.expect('one line per actor, family and minute (4 lines for 37 refusals)', len(lines) == 4, len(lines))
        d.expect('lines carry only family, status, actor key and suppressed',
                 all(set(line) == {'event', 'routeFamily', 'status', 'actorKey', 'suppressed'} for line in lines),
                 sorted({key for line in lines for key in line}))
        text = ' '.join(captured.lines)
        d.expect('no workspace or member id in any line', not any(value in text for value in (a.id, b.id, member)), None)
        fleet = check.parse_logs(captured.lines, 600)
        alerts_fleet = check.evaluate({**snapshot, 'fleet': fleet, 'security': {}}, THRESHOLDS, now=lab.cluster.now())
        d.step('the same refusals read from the log lines only (the check-in path)', alerts_fleet,
               fleetDenials=fleet['denials']['deniedTotal'], fleetTop=fleet['denials']['topActorDenials10m'])
        d.fires(alerts_fleet, 'CROSS_TENANT_PROBING', 'page', 'from the log lines alone')
        recorder = request_metrics.Recorder(clock=clock)
        for _ in range(200):
            recorder.record('GET', '/api/workspaces/%s/discord/identities' % a.id, 403, 0.01)
        recorder.flush(lab.cluster.factory(), dict(recorder.buffer))
        snapshot, alerts = lab.look()
        d.step('injected: 200 client errors on a Discord route in the request metrics', alerts,
               responses4xxDiscord=snapshot['security']['responses4xx'].get('discord'))
        d.fires(alerts, 'CROSS_TENANT_DISCORD_4XX', 'warn', '4xx spike on Discord routes')
        clock.at += 16 * 60
        lab.sql("UPDATE public.pr_request_metrics SET minute = minute - interval '16 minutes'")
        d.record['simulated'].append('recovery: the denial counters\' clock and the request-metrics minutes moved 16 minutes on')
        snapshot, alerts = lab.look()
        d.step('recovered: 16 minutes later (simulated), no new refusals', alerts,
               deniedTotal=snapshot['security']['instance']['deniedTotal'])
        d.expect('cross-tenant alerts cleared', not [k for k in severities(alerts) if k.startswith('CROSS_TENANT')],
                 severities(alerts))
    d.record['references'].append('the isolation itself (both directions, reads and writes, no side effects) is the Q-05 probe '
                                  '(branch claude/discord-q05-probe-20261023); this drill proves only the signal')
    return d.done()


def d6_config_drift(lab):
    d = Drill('D6', 'CONFIG', 'A build without the open settings, the reviewed flag off, the server cap filling')
    lab.fresh([F.Tenant(0)], 0)
    _, alerts = lab.look(phase='open')
    d.silent(alerts, 'open build with gate *, cap 10000')
    omitted = {k: v for k, v in VALUES.items() if k not in ('POSTRIFF_DISCORD_CONNECT_WORKSPACES', 'POSTRIFF_DISCORD_GUILD_CAP')}
    snapshot, alerts = lab.look(phase='open', values=omitted)
    d.step('injected: a later build omitted the gate and cap lines', alerts, gate=snapshot['config']['gate']['mode'],
           cap=snapshot['config']['cap']['value'])
    d.fires(alerts, 'CONFIG_GATE', 'page', 'gate closed after the opening')
    d.fires(alerts, 'CONFIG_CAP', 'page', 'cap back to 90')
    _, alerts = lab.look(phase='open')
    d.expect('gate and cap alerts clear when the open build serves again', not {'CONFIG_GATE', 'CONFIG_CAP'} & set(severities(alerts)),
             severities(alerts))
    lab.provider().production_reviewed = False
    _, alerts = lab.look(phase='open')
    d.step('injected: the reviewed flag missing on the serving build', alerts)
    d.fires(alerts, 'CONFIG_REVIEWED', 'page', 'reviewed flag off')
    lab.provider().production_reviewed = True
    _, alerts = lab.look(phase='open')
    d.expect('reviewed alert cleared', 'CONFIG_REVIEWED' not in severities(alerts), severities(alerts))
    capped = {**VALUES, 'POSTRIFF_DISCORD_GUILD_CAP': '100'}
    workspace = F.Tenant(0).id
    for start, stop, severity in ((0, 81, 'warn'), (81, 91, 'page')):
        for number in range(start, stop):
            lab.sql("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,"
                    "access_ciphertext,key_id,scopes) VALUES(%s,%s,'discord',%s,'synthetic','synthetic',ARRAY['bot','identify'])",
                    (workspace, 'synthetic-discord-%03d' % number, str(8000000 + number)))
        snapshot, alerts = lab.look(phase='pre_open', values=capped)
        gate_count = lab.sql(launch_gate._COUNT)[0][0]
        d.step('injected: %d servers held against a cap of 100' % stop, alerts, used=snapshot['config']['servers']['used'],
               ratio=snapshot['config']['servers']['ratio'], gatesOwnCount=gate_count)
        d.fires(alerts, 'CONFIG_CAP_USED', severity, '%d of 100 servers' % stop)
        d.expect('servers used equals the connect gate\'s own count (%d)' % stop,
                 snapshot['config']['servers']['used'] == gate_count == stop, [snapshot['config']['servers']['used'], gate_count])
    _, alerts = lab.look(phase='pre_open')
    d.expect('cap alert cleared with the cap at 10000', 'CONFIG_CAP_USED' not in severities(alerts), severities(alerts))
    snapshot, alerts = lab.look(phase='canary')
    d.step('canary phase with the gate open: an accidental opening', alerts, gate=snapshot['config']['gate']['mode'])
    d.fires(alerts, 'CONFIG_GATE', 'page', 'gate wider than the tester list during the canary')
    listed = {**VALUES, 'POSTRIFF_DISCORD_CONNECT_WORKSPACES': ','.join(F.Tenant(n).id for n in range(2))}
    _, alerts = lab.look(phase='canary', values=listed)
    d.expect('canary gate of two workspaces raises nothing', 'CONFIG_GATE' not in severities(alerts), severities(alerts))
    return d.done()


def o1_hold(lab):
    d = Drill('O1', 'OPERATION', 'Hold ON and OFF with the phone runbook\'s statements, run verbatim in a separate session')
    statements = runbook_statements()
    d.expect('the runbook has the hold statements', {'HOLD_ON', 'HOLD_OFF', 'HOLD_READBACK', 'HOLD_INSERT', 'DRAIN_CHECK'}
             <= set(statements), sorted(statements))
    # (a) a database where no request was ever admitted: the UPDATE alone cannot hold; the fallback insert can
    lab.fresh([F.Tenant(n) for n in range(4)], 1)
    rows = lab.sql(statements['HOLD_READBACK'])
    d.step('read-back before any request', [], policyRows=rows[0][0], held=rows[0][1])
    lab.sql(statements['HOLD_ON'])
    d.expect('on an empty coordinator HOLD_ON changes nothing (the runbook says so)', lab.sql(statements['HOLD_READBACK'])[0][0] == 0,
             lab.sql(statements['HOLD_READBACK'])[0][:2])
    lab.sql(statements['HOLD_INSERT'].replace('DISCORD_APPLICATION_ID', F.APP))
    rows = lab.sql(statements['HOLD_READBACK'])
    results, _ = F.run_lanes(lab.worker, 2, seconds=5)
    snapshot, alerts = lab.look()
    d.step('HOLD_INSERT, then two shards', alerts, policyRows=rows[0][0], held=rows[0][1],
           stoppedBy=sorted({r['stoppedBy'] for r in results}), claimed=sum(r['counters']['claimed'] for r in results),
           discordRequests=len(lab.wire.calls))
    d.expect('the inserted hold is the coordinator\'s own row and stops every loop before a claim',
             rows[0][:2] == (1, 1) and {r['stoppedBy'] for r in results} == {'operator_hold'} and not lab.wire.calls,
             [list(rows[0][:2]), len(lab.wire.calls)])
    d.fires(alerts, 'SILENT_HALT_OPERATOR_HOLD', 'warn', 'hold visible')
    lab.sql(statements['HOLD_OFF'])
    lab.drain()
    _, alerts = lab.look()
    d.expect('after HOLD_OFF the coordinator works with that row and every post is verified once',
             lab.states() == Counter(verified=4) and lab.wire.duplicates() == 0, dict(lab.states()))
    d.silent(alerts, 'after the inserted hold was lifted')
    # (b) the incident shape: a hold set by the operator while four shards are sending
    lab.fresh([F.Tenant(n) for n in range(30)], 1, latency=0.02)
    held = {}

    def after(method, path, answer):
        if method == 'POST' and not held:
            lab.sql(statements['HOLD_ON'])
            held['at'] = lab.cluster.now()
            held['posts'] = len(lab.wire.requests(method='POST'))
    lab.wire.after = after
    results, failures = F.run_lanes(lab.worker, 4, seconds=40)
    lab.wire.after = None
    first = lab.sql(statements['HOLD_READBACK'])[0]
    time.sleep(2)
    second = lab.sql(statements['HOLD_READBACK'])[0]
    late = lab.sql('SELECT count(*) FROM public.pr_discord_request_admissions WHERE reserved_at > to_timestamp(%s)',
                   (held['at'],))[0][0]
    snapshot, alerts = lab.look()
    posts_after = len(lab.wire.requests(method='POST')) - held['posts']
    d.step('HOLD_ON while four shards send', alerts, stoppedBy=sorted({r['stoppedBy'] for r in results if r}),
           postsAfterHold=posts_after, admissionsAfterHold=late, readback=[list(first[:2]), [float(first[2]), float(second[2])]])
    d.expect('every loop stopped with operator_hold', not failures and {r['stoppedBy'] for r in results} == {'operator_hold'},
             sorted({r['stoppedBy'] for r in results if r}))
    d.expect('at most the step each loop had in flight was sent after the hold (<= 4)', posts_after <= 4, posts_after)
    d.expect('nothing was admitted after the hold committed', late == 0, late)
    d.expect('read-back: policy_rows 1, held 1, seconds since the last request growing',
             first[:2] == (1, 1) and float(second[2]) > float(first[2]), [list(first[:2]), float(first[2]), float(second[2])])
    d.fires(alerts, 'SILENT_HALT_OPERATOR_HOLD', 'warn', 'hold visible to the monitor')
    lab.sql(statements['HOLD_OFF'])
    off = lab.sql(statements['HOLD_READBACK'])[0]
    with lab.cluster.connect(autocommit=True) as db:  # posts refused by the hold wait five minutes; skip the wait
        for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
            for job in state['phase2']['jobs']:
                if job['state'] == 'scheduled':
                    job['nextAt'] = 0
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))
    d.record['simulated'].append('after HOLD_OFF the five-minute wait of posts refused by the hold was skipped')
    lab.drain(seconds=40)
    states = lab.states()
    snapshot, alerts = lab.look()
    d.step('HOLD_OFF and resume', alerts, readback=list(off[:2]), jobs=dict(states), duplicates=lab.wire.duplicates())
    d.expect('read-back after HOLD_OFF: held 0', off[:2] == (1, 0), list(off[:2]))
    d.expect('resumed: every post sent at most once; the rest verified, a post sealed when the hold landed is uncertain',
             lab.wire.duplicates() == 0 and set(states) <= {'verified', 'uncertain'} and states.get('uncertain', 0) <= 4,
             dict(states))
    d.silent(alerts, 'after resuming', allowed=('DELIVERY_UNCERTAIN', 'DELIVERY_SYSTEM_FAILURES'))
    d.record['references'].append('the lane property itself: test_an_operator_hold_stops_every_loop_within_one_iteration')
    return d.done()


def o2_rollback_order(lab):
    import test_discord_parallel_lane_postgres as W
    d = Drill('O2', 'OPERATION', 'Rollback order: hold, drain check, the older worker, lift; and the lane flag off')
    statements = runbook_statements()
    lab.fresh([F.Tenant(n) for n in range(8)], 2, latency=0.02)
    held = {}

    def after(method, path, answer):
        if method == 'POST' and len(lab.wire.requests(method='POST')) >= 3 and not held:
            lab.sql(statements['HOLD_ON'])
            held['yes'] = True
    lab.wire.after = after
    F.run_lanes(lab.worker, 2, seconds=20)
    lab.wire.after = None
    drain = lab.sql(statements['DRAIN_CHECK'])[0]
    d.step('1-2: HOLD_ON while sending, loops stopped, DRAIN_CHECK', [], liveLeases=drain[0], sealedNow=drain[1],
           uncertainToReconcile=drain[2])
    d.expect('drain check: no live lease and nothing sealed, so the worker can be switched', drain[0] == 0 and drain[1] == 0,
             list(drain))
    frozen = W.frozen_worker_class()(lab.cluster.factory(), social=lab.hosted, worker_id='frozen-minute', discord_workers=True)
    off = {k: v for k, v in VALUES.items() if k != F.discord_lane.ENV_ENABLED}
    snapshot, alerts = lab.look(values=off, worker=frozen)
    d.step('3: the older (2a5a523d) worker serves, hold still on', alerts, laneEnabled=snapshot['lane']['enabled'])
    d.expect('the payload reads the older worker; lane flag off is not a lane alarm',
             not snapshot['lane']['enabled'] and 'SILENT_HALT_LANE_NOT_READY' not in severities(alerts), severities(alerts))
    lab.sql(statements['HOLD_OFF'])
    with lab.cluster.connect(autocommit=True) as db:  # posts refused by the hold wait five minutes; skip the wait
        for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
            for job in state['phase2']['jobs']:
                if job['state'] == 'scheduled':
                    job['nextAt'] = 0
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))
    d.record['simulated'].append('after HOLD_OFF the five-minute wait of posts refused by the hold was skipped')
    deadline = time.monotonic() + 60
    with F.no_billing(), patch.dict(os.environ, {'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}, clear=False):
        while time.monotonic() < deadline and set(lab.states()) - {'verified', 'uncertain'}:
            frozen.tick(10, 20)
            time.sleep(.2)
    states = lab.states()
    snapshot, alerts = lab.look(values=off, worker=frozen)
    d.step('4: HOLD_OFF, the older worker drains', alerts, jobs=dict(states), duplicates=lab.wire.duplicates())
    d.expect('drained by the older worker, nothing sent twice', lab.wire.duplicates() == 0
             and set(states) <= {'verified', 'uncertain'} and states.get('verified', 0) >= 12, dict(states))
    d.silent(alerts, 'after the rollback', allowed=('DELIVERY_UNCERTAIN', 'DELIVERY_SYSTEM_FAILURES'))
    d.record['references'] += ['the rollback mechanics are the W-02 tests: test_rollback_the_flag_turned_off_mid_run_lets_the_'
                               'frozen_minute_cron_take_over, test_rollback_to_the_frozen_worker_never_recreates_a_sealed_post, '
                               'test_rollback_to_the_frozen_worker_never_recreates_a_post_discord_accepted, '
                               'test_rollback_the_flag_off_then_on_again_keeps_every_post_exactly_once']
    return d.done()


DRILLS = (d0_baseline, d1_backlog, d2_delivery, d3_rate_limit, d4_silent_halt, d5_cross_tenant, d6_config_drift,
          o1_hold, o2_rollback_order)


def run(out=None, only=None):
    receipt = {'kind': 'rafii.discord.ops.drill-receipt', 'version': 1, 'environment': 'isolated',
               'sourceRevision': source_revision(), 'startedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'python': platform.python_version(), 'postgres': None, 'thresholds': 'docs/ops/discord-alert-thresholds.json',
               'command': 'POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin PYTHONPATH=src:tests python tests/discord_ops_drills.py',
               'drills': []}
    lab = Lab()
    try:
        receipt['postgres'] = lab.sql('SHOW server_version')[0][0]
        with patch.object(security_signals, 'SIGNAL', security_signals.DenialSignal()):
            for drill in DRILLS:
                ident = drill.__name__.split('_', 1)[0].upper()
                if only and ident not in only:
                    continue
                try:
                    record = drill(lab)
                except Exception as error:
                    record = {'id': ident, 'result': 'FAIL', 'error': type(error).__name__,
                              'trace': traceback.format_exc()[-1500:]}
                receipt['drills'].append(record)
                print('%s %s %s' % (record['id'], record['result'], record.get('seconds', '')), flush=True)
                if out:
                    Path(out).write_text(json.dumps(receipt, indent=1, sort_keys=True, default=str) + '\n')
    finally:
        lab.close()
    receipt['finishedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    receipt['result'] = 'PASS' if receipt['drills'] and all(r['result'] == 'PASS' for r in receipt['drills']) else 'FAIL'
    if out:
        Path(out).write_text(json.dumps(receipt, indent=1, sort_keys=True, default=str) + '\n')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--out')
    parser.add_argument('--only', help='comma-separated drill ids, e.g. D1,O1')
    args = parser.parse_args(argv)
    if not F.AVAILABLE:
        print('needs POSTRIFF_PG_BIN and psycopg', file=sys.stderr)
        return 2
    receipt = run(args.out, set(args.only.split(',')) if args.only else None)
    print('overall', receipt['result'])
    return 0 if receipt['result'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
