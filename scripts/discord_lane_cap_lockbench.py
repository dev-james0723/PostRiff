#!/usr/bin/env python3
"""How much the shared Discord request coordinator's application row lock limits throughput (W-02 capacity harness).

Every Discord request is admitted by SharedPostgresBudget.reserve/reserve_read and recorded by observe, each a short
transaction that locks the coordinator's application-wide policy row ('00:' scope, FOR UPDATE; a learned GET may
observe under FOR SHARE). This benchmark drives only that code, from the tested tree, in K separate OS processes,
each with the production connection factory (one new connection per transaction) through the harness pooler with an
injected round-trip latency, and measures what the lock allows:

  - `--policy unbounded`: app_capacity 100,000, so only locks and round trips bind: the coordinator's ceiling;
  - `--policy 25`: the reviewed 25 per second, to see the policy bind before the lock does.

Each process loops reserve_read -> (think time, standing in for Discord's answer) -> observe on GET routes that were
learned (bucket headers seen) or cold (a new server id each time: discovery probe and exclusive observation).
Output: admissions per second and per-call latency percentiles per configuration, as JSON and a Markdown table.
Synthetic data only; no network beyond 127.0.0.1; no application credential.

  python3 scripts/discord_lane_cap_lockbench.py --source-tree TREE --out DIR --processes 1,4,12,24 --latency-ms 0,2,5
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
APP, BOT_TOKEN = '1390000000000000001', 'cap-bot-token-synthetic-0000000000000000'


def worker(args):
    tree = Path(args.source_tree).resolve()
    sys.path[:0] = [str(tree), str(tree / 'src')]
    import psycopg
    from postriff_phase2.discord.rate_limits import RateDelayed, RateCoordinatorUnavailable, RequestIdentity, SharedPostgresBudget
    dsn = args.dsn

    def factory():
        return psycopg.connect(dsn, client_encoding='utf8', prepare_threshold=None, connect_timeout=8)
    budget = SharedPostgresBudget(factory, APP, policy=args.policy_json)
    identity = RequestIdentity.make(APP, 'bot', BOT_TOKEN)
    rng = random.Random(args.seed)
    learned = ['/guilds/%d/members/1390000000000000002' % (1392000000000000000 + args.seed * 1000 + n) for n in range(40)]
    response = {'status': 200, 'headers': {'x-ratelimit-bucket': 'benchbucket', 'x-ratelimit-limit': '1000',
                                           'x-ratelimit-remaining': '999', 'x-ratelimit-reset-after': '1.000'}, 'body': {}}
    while time.time() < args.start_at:
        time.sleep(0.01)
    reserve, observe, delayed, errors, done = [], [], 0, 0, 0
    cold = 0
    deadline = args.start_at + args.seconds
    while time.time() < deadline:
        if args.routes == 'cold':
            cold += 1
            path = '/guilds/%d' % (1395000000000000000 + args.seed * 10 ** 6 + cold)
        else:
            path = rng.choice(learned)
        began = time.monotonic()
        try:
            permit = budget.reserve_read('GET', path, identity=identity)
        except RateDelayed as error:
            delayed += 1
            time.sleep(min(1.0, error.retry_after_seconds))
            continue
        except RateCoordinatorUnavailable:
            errors += 1
            continue
        reserve.append(time.monotonic() - began)
        if args.think_ms:
            time.sleep(args.think_ms / 1000.0)
        began = time.monotonic()
        try:
            budget.observe(permit, response)
            observe.append(time.monotonic() - began)
            done += 1
        except RateCoordinatorUnavailable:
            errors += 1
    print(json.dumps({'done': done, 'delayed': delayed, 'errors': errors, 'reserve': reserve, 'observe': observe}))
    return 0


def pct(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--dsn', help=argparse.SUPPRESS)
    parser.add_argument('--policy-json', help=argparse.SUPPRESS)
    parser.add_argument('--seed', type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--start-at', type=float, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--out', help='directory for lockbench.json and LOCKBENCH.md')
    parser.add_argument('--pg-bin', default=os.environ.get('POSTRIFF_PG_BIN'))
    parser.add_argument('--processes', default='1,4,12,24')
    parser.add_argument('--latency-ms', default='0,2,5')
    parser.add_argument('--routes', choices=('learned', 'cold'), default='learned')
    parser.add_argument('--think-ms', type=float, default=0.0, help='pause between admission and observation')
    parser.add_argument('--policy', default='unbounded', help="'unbounded' or an app_capacity per second, e.g. 25")
    parser.add_argument('--seconds', type=float, default=20.0)
    parser.add_argument('--pool-size', type=int, default=30)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args)
    import discord_lane_cap_cluster as cluster_tools
    import importlib.util
    tree = Path(args.source_tree).resolve()
    spec = importlib.util.spec_from_file_location('cap_policy_tool', tree / 'scripts/discord_rate_policy.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    capacity = 100000 if args.policy == 'unbounded' else int(args.policy)
    policy = json.dumps(tool.build(time.time(), days=1, revision='cap-lockbench', app_capacity=capacity))
    out = Path(args.out or '.')
    out.mkdir(parents=True, exist_ok=True)
    load_start = open('/proc/loadavg').read().strip()
    cluster = cluster_tools.LocalCluster(args.pg_bin, max_connections=150, log=lambda *a: None)
    rows = []
    try:
        cluster_tools.apply_schema(cluster.dsn, tree, log=lambda *a: None)
        for latency in [float(x) for x in args.latency_ms.split(',')]:
            port = cluster_tools.free_port()
            stats = out / ('lockbench-pooler-%s.json' % latency)
            pooler = subprocess.Popen([sys.executable, '-B', str(HERE / 'discord_lane_cap_pooler.py'), '--mode', 'pool',
                                       '--listen-port', str(port), '--upstream-socket', cluster.socket_path,
                                       '--pool-size', str(args.pool_size), '--latency-ms', str(latency),
                                       '--connect-rtts', '4', '--stats', str(stats)],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert 'pooler.ready' in pooler.stdout.readline()
            dsn = 'host=127.0.0.1 port=%d dbname=postgres user=postgres sslmode=disable' % port
            try:
                for count in [int(x) for x in args.processes.split(',')]:
                    start = time.time() + 3 + count * 0.15
                    children = [subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker',
                                                  '--source-tree', str(tree), '--dsn', dsn, '--policy-json', policy,
                                                  '--seed', str(n + 1), '--start-at', repr(start),
                                                  '--seconds', str(args.seconds), '--routes', args.routes,
                                                  '--think-ms', str(args.think_ms)],
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                                 env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                                for n in range(count)]
                    results = []
                    for child in children:
                        stdout, stderr = child.communicate(timeout=args.seconds + 120)
                        if child.returncode:
                            raise RuntimeError(stderr[-2000:])
                        results.append(json.loads(stdout.strip().splitlines()[-1]))
                    reserve = [v for r in results for v in r['reserve']]
                    observe = [v for r in results for v in r['observe']]
                    done = sum(r['done'] for r in results)
                    row = {'processes': count, 'latencyMs': latency, 'routes': args.routes, 'thinkMs': args.think_ms,
                           'policy': args.policy, 'admissionsPerSecond': round(done / args.seconds, 1),
                           'delayed': sum(r['delayed'] for r in results), 'errors': sum(r['errors'] for r in results),
                           'reserveMs': {k: round(1000 * v, 1) for k, v in (('p50', pct(reserve, .5)), ('p95', pct(reserve, .95)),
                                                                             ('max', max(reserve) if reserve else None)) if v is not None},
                           'observeMs': {k: round(1000 * v, 1) for k, v in (('p50', pct(observe, .5)), ('p95', pct(observe, .95)),
                                                                             ('max', max(observe) if observe else None)) if v is not None},
                           'meanTransactionMs': round(1000 * statistics.mean(reserve + observe), 1) if reserve else None}
                    rows.append(row)
                    print(json.dumps(row), flush=True)
                    with cluster_tools_connect(cluster) as db:
                        db.execute('TRUNCATE public.pr_discord_request_admissions')
            finally:
                pooler.terminate()
                pooler.wait(30)
    finally:
        cluster.close()
    # Several invocations (configurations) accumulate in one lockbench.json and one LOCKBENCH.md.
    try:
        sha = subprocess.run(['git', '-C', str(tree), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    except OSError:
        sha = ''
    import discord_lane_capacity_run as runner_tools
    machine = runner_tools.machine_description()
    load_end = open('/proc/loadavg').read().strip()
    record = {'sourceTree': str(tree), 'sourceSha': sha, 'machine': machine, 'loadAtStart': load_start,
              'loadAtEnd': load_end, 'arguments': {k: getattr(args, k) for k in (
                  'processes', 'latency_ms', 'routes', 'think_ms', 'policy', 'seconds', 'pool_size')}, 'rows': rows}
    store = out / 'lockbench.json'
    previous = json.loads(store.read_text()) if store.exists() else {'runs': []}
    previous.setdefault('runs', []).append(record)
    store.write_text(json.dumps(previous, indent=1))
    where = ('GitHub Actions runner %s (%s, image %s %s)' % (machine.get('runnerName'), machine.get('runnerEnvironment'),
                                                            machine.get('image'), machine.get('imageVersion'))
             if machine.get('kind') == 'github-actions' else 'local machine (the development sandbox is shared: not evidence)')
    header = ['### Lock benchmark: routes %s, policy %s, think %s ms, %s s per configuration, pool %d' % (
                  args.routes, args.policy, args.think_ms, args.seconds, args.pool_size), '',
              'Tree `%s`; %s, %s vCPU, %s GB; load %s at start, %s at end.' % (
                  sha, where, machine.get('cpus'), machine.get('memGb'), load_start.split()[0], load_end.split()[0]), '']
    lines = header + ['| processes | DB round trip ms | routes | think ms | policy | admissions/s | reserve p50/p95 ms | observe p50/p95 ms | delayed | errors |',
                      '|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append('| %d | %s | %s | %s | %s | %s | %s / %s | %s / %s | %d | %d |' % (
            r['processes'], r['latencyMs'], r['routes'], r['thinkMs'], r['policy'], r['admissionsPerSecond'],
            r['reserveMs'].get('p50'), r['reserveMs'].get('p95'), r['observeMs'].get('p50'), r['observeMs'].get('p95'),
            r['delayed'], r['errors']))
    with open(out / 'LOCKBENCH.md', 'a') as handle:
        handle.write('\n'.join(lines) + '\n\n')
    return 0


def cluster_tools_connect(cluster):
    import psycopg
    return psycopg.connect(cluster.dsn, autocommit=True)


if __name__ == '__main__':
    sys.exit(main())
