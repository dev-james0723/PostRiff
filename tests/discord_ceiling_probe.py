"""Local measure of the shared Discord request coordinator at its ceiling: a harness-style probe, not a test.

The real SharedPostgresBudget on a disposable PostgreSQL (tests/discord_lane_fixture.py), the real DiscordProvider for
reads, the in-process mock Discord, K worker threads that keep asking for more than the ceiling allows. Each cell of the
grid is one run; it reports what the capacity harness reports:

  over25      requests the mock's own trailing second saw above the ceiling (the owner's strict measure), and its peak
  admissions  per second while the workers were busy, and the share of the ceiling that is
  jitter     admission-to-wire delay (the coordinator's wire stamp to the mock's arrival), p50 / p99 / p99.9 / max
  creates    permits reserved, how many died before they could be used (permit expiry rate)
  leaked     admissions still `sent` or `uncertain` when the run ended (nothing was lost here, so none is expected)
  locks      reservation lock statements per admission (a refused reservation costs one too), and the bookings made

`--book 0,1` runs each cell without and with booking: the workers call inside rate_limits.booking(), as the lane does, and a
create asks for book_ahead. In that run a full window gives a caller a place in line instead of a refusal to poll for.

`--jitter J` makes every request wait U(0, J) between its admission and the mock, the delay a busy machine or a slow
connection set-up adds; `--guard` overrides SLOT_GUARD_SECONDS where the tree has it. The source tree is an argument so
one probe measures the code before and after a change.

  POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin python tests/discord_ceiling_probe.py TREE --jitter 0,100 --guard 0.05,0.1

Synthetic ids and tokens only; no network beyond the process; never touches another database.
"""
import argparse
import hashlib
import json
import random
import secrets
import sys
import threading
import time
from pathlib import Path


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def busiest_closed(times, span):
    times, best, low = sorted(times), 0, 0
    for high, stamp in enumerate(times):
        while stamp - times[low] > span:
            low += 1
        best = max(best, high - low + 1)
    return best


def run_cell(tree, F, cluster, *, capacity, jitter, guard, threads, seconds, create_share, in_flight, book=False):
    import contextlib
    from postriff_phase2.discord import rate_limits
    from postriff_phase2.discord.rate_limits import RateDelayed, RateCoordinatorUnavailable, RequestIdentity, SharedPostgresBudget
    from postriff_phase2.social_connectors import DiscordProvider
    cluster.reset()
    if guard is not None and hasattr(SharedPostgresBudget, 'SLOT_GUARD_SECONDS'):
        SharedPostgresBudget.SLOT_GUARD_SECONDS = guard
    app = '8%017d' % (int(time.time() * 1000) % 10 ** 11 * 1000 + secrets.randbelow(1000))
    tenants = [F.Tenant(n) for n in range(40)]
    wire = F.MockDiscord(tenants, latency=in_flight, ceiling=capacity)
    arrivals = {}                                         # path -> [epoch of arrival at the mock]
    gate = threading.Lock()

    def wired(method, url, **kwargs):
        if jitter:
            time.sleep(random.uniform(0, jitter))
        with gate:
            arrivals.setdefault(url.removeprefix(DiscordProvider.API), []).append(time.time())
        return wire(method, url, **kwargs)

    provider = DiscordProvider(app, 'synthetic-secret', 'synthetic-bot-token', 'https://rafii.example.invalid',
                               transport=wired, production_reviewed=True)
    provider.authorization_v2_enabled = provider.connections_v2_enabled = provider.rate_v1_enabled = True
    locks = {'n': 0}

    def counted():
        import psycopg

        class Counter(psycopg.Cursor):
            def execute(self, query, params=None, **kwargs):
                if ' '.join(str(query).split()).startswith('WITH scope_lock AS MATERIALIZED ( SELECT scope_key,kind,limit_count'):
                    locks['n'] += 1
                return super().execute(query, params, **kwargs)
        return lambda: psycopg.connect(cluster.dsn, prepare_threshold=None, cursor_factory=Counter)
    limiter = SharedPostgresBudget(counted(), app, policy=F.policy(cluster.now(), capacity=capacity))
    provider.rate_limiter = limiter
    identity = RequestIdentity.make(app, 'bot', 'synthetic-bot-token')
    counts = {'reads': 0, 'creates': 0, 'expired': 0, 'delayed': 0, 'errors': 0}
    stop = time.monotonic() + seconds

    def work(index):
        rng = random.Random(index)
        while time.monotonic() < stop:
            tenant = tenants[rng.randrange(len(tenants))]
            try:
                if rng.random() < create_share:
                    path = '/channels/%s/messages' % tenant.channel
                    permit = limiter.reserve('POST', path, identity=identity, **({'book_ahead': 1.0} if book else {}))
                    with gate:
                        counts['creates'] += 1
                    time.sleep(rng.uniform(.15, 1.0))   # the preflight's seal and consume step, between reserve and use
                    try:
                        limiter.consume(permit, 'POST', path)
                    except RateDelayed:
                        with gate:
                            counts['expired'] += 1
                        continue
                    answer = wired('POST', DiscordProvider.API + path, body={'content': 'synthetic', 'nonce': secrets.token_hex(6)})
                    limiter.observe(permit, answer)
                else:
                    with (rate_limits.booking(1.0) if book else contextlib.nullcontext()):
                        provider._bot('GET', '/guilds/%s/members/%s' % (tenant.guild, F.USER) if rng.random() < .5 else '/guilds/' + tenant.guild)
                    with gate:
                        counts['reads'] += 1
            except RateDelayed as error:
                with gate:
                    counts['delayed'] += 1
                time.sleep(min(error.retry_after_seconds, 1.0) + secrets.randbelow(26) / 1000)
            except RateCoordinatorUnavailable:
                with gate:
                    counts['errors'] += 1
    began = time.monotonic()
    workers = [threading.Thread(target=work, args=(n,)) for n in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    elapsed = time.monotonic() - began
    key = hashlib.sha256(app.encode()).hexdigest()
    with cluster.connect(autocommit=True) as db:
        rows = db.execute('''SELECT extract(epoch from coalesce(sent_at,reserved_at)), state, path_key
            FROM public.pr_discord_request_admissions WHERE application_key=%s ORDER BY request_seq''', (key,)).fetchall()
    wires = [float(row[0]) for row in rows]
    sent = [float(row[0]) for row in rows if row[1] in ('sent', 'observed', 'uncertain')]     # the ones that went to the wire
    leaked = sum(1 for row in rows if row[1] in ('sent', 'uncertain'))
    # admission-to-wire delay: the coordinator's wire stamp to the mock's arrival, matched by path digest and order
    by_digest = {}
    for url, times in arrivals.items():
        by_digest.setdefault(hashlib.sha256(url.encode()).hexdigest(), []).extend(times)
    delays = []
    for stamp, state, digest in rows:
        if state not in ('sent', 'observed', 'uncertain'):
            continue
        hits = sorted(by_digest.get(digest, []))
        for moment in hits:
            if moment >= float(stamp) - .002:
                delays.append(moment - float(stamp))
                hits.remove(moment)
                break
        by_digest[digest] = hits
    busy_from = min(sent) + 1 if sent else 0
    steady = [t for t in sent if busy_from <= t <= max(sent) - 1] if sent else []
    rate = len(steady) / max(1e-9, (max(sent) - min(sent) - 2)) if len(sent) > 2 * capacity else len(sent) / max(elapsed, 1e-9)
    guard_used = getattr(SharedPostgresBudget, 'SLOT_GUARD_SECONDS', None)
    stats = limiter.booking_stats() if hasattr(limiter, 'booking_stats') else {}
    return {'tree': str(tree), 'book': bool(book), 'capacity': capacity, 'jitterMs': int(jitter * 1000), 'guard': guard_used, 'threads': threads,
            'seconds': round(elapsed, 1), 'admissions': len(wires), 'admissionsPerSecond': round(rate, 1),
            'shareOfCeiling': round(rate / capacity, 3), 'over25AtMock': wire.over_ceiling, 'peakTrailingSecondAtMock': wire.peak_second,
            'busiestClosedSecondOfWireStamps': busiest_closed(sent, 1.0), 'route429': wire.route429,
            'wireDelayMs': {k: round(1000 * percentile(delays, q), 1) for k, q in (('p50', .5), ('p99', .99), ('p999', .999), ('max', 1.0))} if delays else None,
            'creates': counts['creates'], 'permitsExpiredUnused': counts['expired'],
            'permitExpiryRate': round(counts['expired'] / counts['creates'], 4) if counts['creates'] else None,
            'reads': counts['reads'], 'delayed': counts['delayed'], 'errors': counts['errors'], 'leakedAtEnd': leaked,
            'lockStatementsPerAdmission': round(locks['n'] / max(1, len(wires)), 2), 'bookings': stats.get('bookings', 0),
            'bookedWaitSecondsMean': round(stats['bookedWaitSeconds'] / stats['bookings'], 3) if stats.get('bookings') else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('tree')
    parser.add_argument('--capacity', type=int, default=25)
    parser.add_argument('--jitter', default='0', help='comma list of milliseconds')
    parser.add_argument('--guard', default='', help='comma list of seconds (SLOT_GUARD_SECONDS), empty = the tree\'s own')
    parser.add_argument('--threads', type=int, default=24)
    parser.add_argument('--seconds', type=float, default=8.0)
    parser.add_argument('--create-share', type=float, default=.14)
    parser.add_argument('--in-flight-ms', type=float, default=100.0, help='the mock\'s answer time')
    parser.add_argument('--book', default='0', help='comma list: 0 = callers are refused at a full window, 1 = they are booked')
    args = parser.parse_args()
    tree = Path(args.tree).resolve()
    sys.path[:0] = [str(tree / 'src'), str(tree / 'tests')]
    import discord_lane_fixture as F
    if not F.AVAILABLE:
        sys.exit('needs POSTRIFF_PG_BIN and psycopg')
    cluster = F.Cluster()
    try:
        for jitter in [float(x) / 1000 for x in args.jitter.split(',')]:
            for guard in ([float(x) for x in args.guard.split(',')] if args.guard else [None]):
                for book in [x.strip() == '1' for x in args.book.split(',')]:
                    print(json.dumps(run_cell(tree, F, cluster, capacity=args.capacity, jitter=jitter, guard=guard, threads=args.threads,
                                              seconds=args.seconds, create_share=args.create_share,
                                              in_flight=args.in_flight_ms / 1000, book=book)),
                          flush=True)
    finally:
        cluster.close()


if __name__ == '__main__':
    main()
