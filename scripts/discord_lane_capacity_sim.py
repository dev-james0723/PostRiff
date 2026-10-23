#!/usr/bin/env python3
"""W-02 capacity simulation: how fast K Discord lanes drain a burst, and that nothing is sent twice or too fast.

Two parts, both offline (no network, no Discord, no Depot, no deployment, no application credentials):

  model  A deterministic fake-clock model of the lane: K loops, a fixed-window request budget (the coordinator's
         policy), per-request latency, per-step database time, the one-minute cron with a 50-second loop budget, the
         five-second wait before a read-back, and a serialized coordinator row lock. It answers "how long do 5,000
         (or 100,000) posts due in one minute take" for 1, 2 or 6 requests per post. Only the arithmetic is modelled.
  real   The actual lane code (claims, leases, triggers, the shared coordinator, the real sender) on a disposable
         local PostgreSQL (POSTRIFF_PG_BIN) against an in-process mock Discord with latency and a hard ceiling, over a
         few hundred synthetic posts, timed in real seconds. It measures requests per post, posts per second,
         duplicates and over-ceiling requests, and extrapolates to 5,000.

Not measured by either: real Discord latency and behaviour, Vercel cold starts and egress-IP limits, the production
database's round trip (local PostgreSQL is sub-millisecond, so the coordinator's row lock is far cheaper here than it
will be there), connection setup over TLS, and big workspace documents.

  python3 scripts/discord_lane_capacity_sim.py model
  POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin python3 scripts/discord_lane_capacity_sim.py real --posts 400
"""
import argparse
import heapq
import itertools
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Requests per text post on the bot path today: guild, bot member, linked member, channel list, create, read-back.
CURRENT_REQUESTS = 6


def model(posts, *, capacity, requests_per_post, lanes=12, latency=.15, db_seconds=.03, lock_seconds=.004,
          loop_seconds=50, readback_delay=5.0, window=1.0, horizon=4 * 3600):
    """Fake-clock drain of `posts` due at t=0 (all different workspaces). Returns seconds until the last is done.

    A post is a create step (requests_per_post - 1 requests when there is a read-back, else 1) and, for two or more
    requests, a read-back step five seconds later. Each request first queues for the coordinator's row lock
    (`lock_seconds`, serialized across every loop), then for a slot in its fixed one-second window, then takes
    `latency`. Each step adds `db_seconds` per transaction (claim, renewals, seal, completion, and two per request).
    Loops admit steps only during the first `loop_seconds` of each cron minute; a step in flight finishes.
    """
    create_requests = requests_per_post - 1 if requests_per_post >= 2 else 1
    readback = requests_per_post >= 2
    used, lock_free, order = {}, 0.0, itertools.count()
    readbacks = []  # (due time, post)
    done, finished_at, requests, next_create = 0, 0.0, 0, 0
    # One event per lane: (time, order, lane, step). A step is None while the lane looks for work.
    events = [(0.0, next(order), lane, None) for lane in range(lanes)]
    heapq.heapify(events)
    while done < posts:
        at, _, lane, step = heapq.heappop(events)
        if at > horizon:
            return None
        if step is None:
            minute_start = math.floor(at / 60) * 60
            if at - minute_start >= loop_seconds:  # this loop has stopped; the next minute starts a new one
                heapq.heappush(events, (minute_start + 60, next(order), lane, None))
                continue
            if readbacks and readbacks[0][0] <= at:
                step = {'kind': 'readback', 'post': heapq.heappop(readbacks)[1], 'left': 1, 'transactions': 2}
            elif next_create < posts:
                step = {'kind': 'create', 'post': next_create, 'left': create_requests, 'transactions': 4}
                next_create += 1
            else:
                wake = readbacks[0][0] if readbacks else at + 1
                heapq.heappush(events, (max(wake, at + .01), next(order), lane, None))
                continue
            heapq.heappush(events, (at + 2 * db_seconds, next(order), lane, step))  # claim, first renewal
            continue
        if step['left']:
            # Every attempt holds the coordinator's row lock; a refused one sleeps to the next window.
            start = max(at, lock_free)
            lock_free = start + lock_seconds
            index = math.floor(lock_free / window)
            if used.get(index, 0) >= capacity:
                heapq.heappush(events, ((index + 1) * window, next(order), lane, step))
                continue
            used[index] = used.get(index, 0) + 1
            requests += 1
            step['left'] -= 1
            heapq.heappush(events, (lock_free + latency + 2 * db_seconds, next(order), lane, step))
            continue
        end = at + db_seconds * step['transactions']
        if step['kind'] == 'readback' or not readback:
            done += 1
            finished_at = max(finished_at, end)
        else:
            heapq.heappush(readbacks, (end + readback_delay, step['post']))
        heapq.heappush(events, (end, next(order), lane, None))
    return {'seconds': round(finished_at, 1), 'requests': requests, 'postsPerSecond': round(posts / finished_at, 2)}


def model_table():
    rows = []
    for posts in (5000, 100000):
        for capacity in (25, 50):
            for per_post in (1, 2, CURRENT_REQUESTS):
                for lock in (.004, .02, .04):
                    result = model(posts, capacity=capacity, requests_per_post=per_post, lock_seconds=lock,
                                   lanes=16 if capacity == 50 else 12)
                    ideal = posts * per_post / capacity
                    rows.append({'posts': posts, 'policyPerSecond': capacity, 'requestsPerPost': per_post,
                                 'lockSecondsPerRequest': lock, 'lanes': 16 if capacity == 50 else 12,
                                 'drainSeconds': result and result['seconds'],
                                 'drainMinutes': result and round(result['seconds'] / 60, 1),
                                 'postsPerSecond': result and result['postsPerSecond'],
                                 'budgetOnlyMinutes': round(ideal / 60, 1),
                                 'pastOneHourApproval': bool(result and result['seconds'] > 3600)})
    return rows


def real(posts, *, capacities=(25, 50), lanes=12, latency=.05, tenants=None, paced=True, minutes=8):
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    import discord_lane_fixture as F
    from postriff_phase2.discord import lane as discord_lane
    if not F.AVAILABLE:
        raise SystemExit('Set POSTRIFF_PG_BIN to PostgreSQL server binaries (and install psycopg) for the real run.')
    results = []
    cluster = F.Cluster()
    try:
        for capacity in capacities:
            cluster.reset()
            group = [F.Tenant(n) for n in range(tenants or posts)]
            per = max(1, posts // len(group))
            F.seed(cluster, group, per)
            # The mock refuses nothing for being fast; it counts requests beyond Discord's 50 per trailing second.
            wire = F.MockDiscord(group, latency=latency, ceiling=50)
            hosted = F.social(cluster, group, wire, capacity=capacity)
            worker = F.base_worker(cluster, hosted)
            original = discord_lane.PacedSocial.reserve_discord_send
            if not paced:
                discord_lane.PacedSocial.reserve_discord_send = lambda self, manifest, **kw: self._social.reserve_discord_send(manifest, **kw)
            values = {**F.LANE_ENV, discord_lane.ENV_SECONDS: '50'}
            started, outcomes = time.monotonic(), []
            try:
                with F.no_billing():
                    # One cron minute: K loops at once, each with the default 50-second budget; repeat until drained.
                    for minute in range(minutes):
                        threads = [threading.Thread(target=lambda n=number: outcomes.append(discord_lane.run(worker, n, values)))
                                   for number in range(lanes)]
                        for thread in threads:
                            thread.start()
                        for thread in threads:
                            thread.join()
                        if all(job['state'] in ('verified', 'held', 'failed', 'uncertain') for job in F.jobs(cluster).values()):
                            break
                        time.sleep(max(0.0, started + 60 * (minute + 1) - time.monotonic()))
            finally:
                discord_lane.PacedSocial.reserve_discord_send = original
            elapsed = time.monotonic() - started
            found = F.jobs(cluster)
            states = {}
            for job in found.values():
                states[job['state']] = states.get(job['state'], 0) + 1
            verified = [job for job in found.values() if job['state'] == 'verified']
            last = max((max(t for t, _, _ in wire.creates[F.nonce(job)]) for job in verified), default=None)
            calls = len(wire.calls)
            span = (wire.calls[-1][0] - wire.calls[0][0]) if calls > 1 else 0
            rate = len(verified) / span if span else None
            results.append({
                'policyPerSecond': capacity, 'lanes': lanes, 'mockLatencySeconds': latency, 'posts': len(found),
                'pacedCreatePermit': paced, 'states': states, 'elapsedSeconds': round(elapsed, 1),
                'requests': calls, 'requestsPerVerifiedPost': round(calls / len(verified), 2) if verified else None,
                'requestsPerSecond': round(calls / span, 1) if span else None,
                'postsPerSecond': round(rate, 2) if rate else None,
                'extrapolated5000Minutes': round(5000 / rate / 60, 1) if rate else None,
                'duplicates': wire.duplicates(), 'overDiscordCeiling': wire.over_ceiling,
                'peakRequestsInOneSecond': wire.peak_second, 'route429': wire.route429,
                'invocations': len(outcomes),
                'stoppedBy': sorted({o['stoppedBy'] for o in outcomes if o}),
                'rateDelayed': sum(o['counters']['rateDelayed'] for o in outcomes if o),
                'permitWaits': sum(o['counters']['permitWaits'] for o in outcomes if o),
                'lastCreateAfterStartSeconds': round(last - wire.calls[0][0], 1) if last and calls else None})
    finally:
        cluster.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='part', required=True)
    sub.add_parser('model')
    run = sub.add_parser('real')
    run.add_argument('--posts', type=int, default=400)
    run.add_argument('--lanes', type=int, default=12)
    run.add_argument('--latency', type=float, default=.05)
    run.add_argument('--capacity', type=int, action='append')
    run.add_argument('--unpaced', action='store_true', help='turn off the lane\'s create-permit wait (comparison)')
    args = parser.parse_args()
    if args.part == 'model':
        print(json.dumps({'part': 'model', 'simulated': True, 'rows': model_table()}, indent=1))
    else:
        print(json.dumps({'part': 'real', 'simulated': 'mock Discord; real code and PostgreSQL',
                          'rows': real(args.posts, capacities=tuple(args.capacity or (25, 50)), lanes=args.lanes,
                                       latency=args.latency, paced=not args.unpaced)}, indent=1))


if __name__ == '__main__':
    main()
