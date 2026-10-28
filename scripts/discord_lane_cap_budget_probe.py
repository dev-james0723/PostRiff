#!/usr/bin/env python3
"""After a capacity run: how much of the application budget a fresh window still grants (W-02 capacity harness).

An admission that is never observed (`sent` or `uncertain`) holds one slot of the application budget until something
resolves it. This probe measures the budget the way the lane meets it. It uses the tested tree's own
SharedPostgresBudget, with the run's reviewed policy and the run's synthetic application and bot token. It reserves
reads on synthetic, never-used server routes one after another until the coordinator refuses. Each probe admission is
then observed with a synthetic 200 answer, so the probe leaves nothing open. No request is sent anywhere; the routes
are never called.

Prints one JSON line: {"admitted": n, "refused": {...}, "seconds": s, "waited": w}. `admitted` equal to the policy's
application capacity means the window is whole. Fewer means slots are still held. A probe that took longer than one
window says so (`windowRolled`), and its count is then not a single window's.

`--kind user` probes the bearer budget instead (a policy with the bearer pair, rate_limits.BEARER_KIND): the same reads
with a synthetic bearer identity, never sent anywhere, counted against `bearer_capacity`. The line then says "kind": "user".

  python3 scripts/discord_lane_cap_budget_probe.py --source-tree TREE --dsn DSN --env RUN/env-run.json [--wait 330] [--kind user]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--dsn', required=True, help='direct (admin) database connection of the run')
    parser.add_argument('--env', required=True, help="the run's env-run.json (policy, application id, bot token)")
    parser.add_argument('--wait', type=float, default=0.0, help='seconds to wait before probing')
    parser.add_argument('--max', type=int, default=80, help='stop after this many admissions')
    parser.add_argument('--kind', choices=('bot', 'user'), default='bot',
                        help="which budget to probe: the application's ('bot') or the bearer budget's ('user')")
    args = parser.parse_args(argv)
    tree = Path(args.source_tree).resolve()
    sys.path[:0] = [str(tree), str(tree / 'src')]
    import psycopg
    from postriff_phase2.discord.rate_limits import (RateCoordinatorUnavailable, RateDelayed, RequestIdentity,
                                                      SharedPostgresBudget)
    env = json.loads(Path(args.env).read_text())
    policy = env['POSTRIFF_DISCORD_RATE_POLICY']
    application, bot_token = env['POSTRIFF_OAUTH_DISCORD_CLIENT_ID'], env['POSTRIFF_DISCORD_BOT_TOKEN']
    if args.wait > 0:
        time.sleep(args.wait)

    class Reuse:
        """One connection for the whole probe, so that opening connections does not stretch it past a window: the
        coordinator's own transaction blocks commit on exit, which here leaves the connection open."""
        def __init__(self):
            self.connection = psycopg.connect(args.dsn, client_encoding='utf8', prepare_threshold=None, connect_timeout=8)

        def __call__(self):
            return self

        def __enter__(self):
            return self.connection

        def __exit__(self, kind, value, traceback):
            (self.connection.rollback if kind else self.connection.commit)()
            return False
    budget = SharedPostgresBudget(Reuse(), application, policy=policy)
    # A synthetic bearer for the bearer budget: a person's bearer is never needed, nothing is sent.
    identity = RequestIdentity.make(application, 'bot', bot_token) if args.kind == 'bot' else RequestIdentity.make(
        application, 'user', 'cap-probe-bearer-' + os.urandom(8).hex())
    # Synthetic server ids the run never used (the mock's servers start at another base): a fresh route per probe.
    base = 1397000000000000000 + (int(time.time() * 1000) % 10 ** 8) * 1000
    permits, refused = [], None
    started = time.time()
    for number in range(args.max):
        try:
            permits.append(budget.reserve_read('GET', '/guilds/%d' % (base + number), identity=identity))
        except RateDelayed as error:
            refused = {'scope': getattr(error, 'rate_scope_kind', None), 'cause': getattr(error, 'rate_cause', None),
                       'retryAfterSeconds': round(error.retry_after_seconds, 3)}
            break
        except RateCoordinatorUnavailable:
            refused = {'scope': 'coordinator unavailable'}
            break
    elapsed = time.time() - started
    closed = 0
    for permit in permits:
        try:
            budget.observe(permit, {'status': 200, 'headers': {}, 'body': {}})
            closed += 1
        except Exception:  # recorded below; the run is over, but say so
            pass
    print(json.dumps({'admitted': len(permits), 'refused': refused, 'seconds': round(elapsed, 3),
                      'windowRolled': elapsed > 1.0, 'closed': closed, 'waited': args.wait, 'kind': args.kind,
                      'capacity': json.loads(policy).get('app_capacity' if args.kind == 'bot' else 'bearer_capacity')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
