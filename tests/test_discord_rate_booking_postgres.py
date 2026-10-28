"""Real-PostgreSQL proof of booking (docs/w02/OPEN-QUESTIONS.md, Q19): many callers at a full application window are each given
a place in line and sent at it, the ceiling stays exact at the mock's own trailing second, and what can go wrong while a booked
read waits does not reach Discord.

A disposable cluster (tests/discord_lane_fixture.py), the repository's schema, the real coordinator and DiscordProvider, Discord
as the in-process mock (with a random delay between a request's wire time and its arrival, the spread the guard is sized for).
Runs where POSTRIFF_PG_BIN names the PostgreSQL server binaries; synthetic ids only, no network.
"""
import random
import secrets
import threading
import time
import unittest

import psycopg

import discord_lane_fixture as F
from postriff_phase2.discord import rate_limits
from postriff_phase2.discord.rate_limits import RateDelayed, SharedPostgresBudget
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_rate_ceiling_postgres import Stack, busiest_closed, OK

LOCK_STATEMENT = 'WITH scope_lock AS MATERIALIZED ( SELECT scope_key,kind,limit_count'


class Jittered:
    """The transport with a random delay between the coordinator's wire time and the mock's arrival."""
    def __init__(self, wire, spread):
        self.wire, self.spread = wire, spread

    def __call__(self, method, url, **kwargs):
        if self.spread:
            time.sleep(random.uniform(0, self.spread))
        return self.wire(method, url, **kwargs)

    def __getattr__(self, name):
        return getattr(self.wire, name)


class CountedCursor(psycopg.Cursor):
    counts = None

    def execute(self, query, params=None, **kwargs):
        if CountedCursor.counts is not None and ' '.join(str(query).split()).startswith(LOCK_STATEMENT):
            CountedCursor.counts['lock'] += 1
        return super().execute(query, params, **kwargs)


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class BookingOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def stack(self, capacity=25, latency=.05, spread=.08, tenants=6, **policy):
        stack = Stack(self.cluster, capacity=capacity, latency=latency, tenants=tenants, **policy)
        stack.provider.transport = Jittered(stack.wire, spread)
        stack.counts = {'lock': 0}
        stack.limiter.connection_factory = self.counting(stack.limiter.connection_factory, stack.counts)
        return stack

    @staticmethod
    def counting(factory, counts):
        def open_connection():
            connection = factory()
            connection.cursor_factory = CountedCursor
            CountedCursor.counts = counts
            return connection
        return open_connection

    def hammer(self, stack, workers, seconds, *, book, creators=0, create_book=True):
        """`workers` threads reading through the real provider (inside booking() when `book`), `creators` of them taking a permit
        instead and using it a moment later; each refused caller backs off by the quote as a caller does."""
        stop, lock = time.monotonic() + seconds, threading.Lock()
        counts = {'reads': 0, 'creates': 0, 'delayed': 0, 'create_delayed': 0, 'other': []}

        def run(index):
            rng = random.Random(index)
            creator = index < creators
            while time.monotonic() < stop:
                try:
                    if creator:
                        path = '/guilds/%s' % stack.tenants[rng.randrange(len(stack.tenants))].guild
                        permit = stack.limiter.reserve('GET', path, identity=stack.identity,
                                                       book_ahead=1.0 if create_book else 0.0)
                        time.sleep(rng.uniform(.03, .08))                     # the seal
                        stack.limiter.consume(permit, 'GET', path)
                        answer = stack.provider.transport('GET', DiscordProvider.API + path)
                        stack.limiter.observe(permit, answer)
                        key = 'creates'
                    else:
                        with rate_limits.booking(1.0 if book else 0.0):
                            stack.read(rng.randrange(1000))
                        key = 'reads'
                    with lock:
                        counts[key] += 1
                except RateDelayed as error:
                    with lock:
                        counts['create_delayed' if creator else 'delayed'] += 1
                    time.sleep(min(error.retry_after_seconds, 1.0) + secrets.randbelow(26) / 1000)
                except Exception as error:  # noqa: BLE001 - reported by the test
                    with lock:
                        counts['other'].append(repr(error)[:120])
        threads = [threading.Thread(target=run, args=(n,)) for n in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return counts

    # --- the ceiling, at the mock's own trailing second, with a spread between wire time and arrival ----------------------

    def test_24_threads_booking_keep_the_ceiling_with_far_fewer_lock_statements(self):
        """The same twenty-four threads at the owner's cap of 25, polling and booking, over six servers (their routes learned
        within the first second). The ceiling is asserted on the database clock, strictly; the mock's own trailing second is
        asserted with two requests of room, because a stall of this shared box that bunches arrivals by more than the 100 ms
        headroom is the wire jitter the capacity runs measure (docs/w02/RESULTS-GITHUB.md), not something the coordinator
        can prevent. tests/discord_ceiling_probe.py --book 0,1 reports both with the delay distribution."""
        results = {}
        for book in (False, True):
            stack = self.stack(capacity=25)
            counts = self.hammer(stack, 24, 8, book=book)
            stamps = stack.stamps()
            results[book] = dict(counts, admitted=len(stamps), lock=stack.counts['lock'], stack=stack)
            self.assertEqual(counts['other'], [], book)
            self.assertGreater(len(stamps), 80, 'busy enough to meet the cap')
            self.assertLessEqual(busiest_closed(stamps, 1.0), 25, book)
            self.assertLessEqual(stack.wire.peak_second, 27, book)
            self.assertEqual(stack.wire.route429, 0)
        booked, polled = results[True], results[False]
        self.assertGreater(booked['stack'].limiter.booking_stats()['bookings'], 20, 'the window was full often enough to book')
        per = lambda r: r['lock'] / max(1, r['admitted'])   # noqa: E731
        self.assertLessEqual(per(booked), 2.0, 'about one reservation lock statement per admission (its observation is the other)')
        self.assertGreaterEqual(per(polled), per(booked) + .25, 'and the polling control needs more: the lottery booking removes')
        self.assertLess(booked['delayed'], polled['delayed'], 'booked callers are refused far less often')

    def test_creates_are_not_starved_when_reads_are_booked_too_and_are_when_they_are_not(self):
        outcomes = {}
        for create_book in (True, False):
            stack = self.stack(capacity=25, spread=.02)
            counts = self.hammer(stack, 24, 8, book=True, creators=4, create_book=create_book)
            outcomes[create_book] = counts
            self.assertEqual(counts['other'], [], create_book)
            self.assertLessEqual(busiest_closed(stack.stamps(), 1.0), 25)
        fair = outcomes[True]['creates']
        starved = outcomes[False]['creates']
        self.assertGreaterEqual(fair, 8, 'four creators took their share of a window the other twenty kept full')
        self.assertGreater(fair, 2 * starved, 'booked creates against creates left to ask for a slot now: starved (%d against %d)' % (fair, starved))

    # --- what happens while a booked read waits ----------------------------------------------------------------------------

    def full_window(self, stack, count):
        """`count` immediate admissions, answered, spread over a moment so that the next caller must wait for the first to leave."""
        for number in range(count):
            permit = stack.limiter.reserve_read('GET', '/guilds/%d' % (710000000000000500 + number), identity=stack.identity)
            stack.limiter.observe(permit, OK)
            time.sleep(.05)

    def booked_in_a_thread(self, stack, path, results, name='booked'):
        def run():
            try:
                permit = stack.limiter.reserve_read('GET', path, identity=stack.identity, book_ahead=1.0)
                results[name] = ('sent', permit)
            except RateDelayed as error:
                results[name] = ('stopped', error)
            except BaseException as error:  # noqa: BLE001
                results[name] = ('failed', error)
        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def admission(self, stack, permit_or_none=None):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute('SELECT state,extract(epoch from sent_at) FROM public.pr_discord_request_admissions '
                              'WHERE application_key=%s ORDER BY request_seq DESC LIMIT 1', (stack.key,)).fetchone()

    def test_a_booked_read_that_wakes_into_a_global_429_a_hold_or_a_circuit_is_not_sent(self):
        for what in ('global429', 'hold', 'circuit'):
            with self.subTest(what=what):
                stack = self.stack(capacity=3, latency=0, spread=0, failure_threshold=2)
                path = '/guilds/%s' % stack.tenants[0].guild
                stack.read(0)                                    # learns the route: later requests on it are not cold probes
                triggers = []
                for _ in range(2 if what == 'circuit' else 1):
                    time.sleep(.1)
                    triggers.append(stack.limiter.reserve_read('GET', path, identity=stack.identity))
                self.full_window(stack, 3 - 1 - len(triggers))
                results = {}
                thread = self.booked_in_a_thread(stack, path, results)
                time.sleep(.1)
                self.assertNotIn('booked', results, 'it is waiting for its slot')
                if what == 'global429':
                    stack.limiter.observe(triggers[0], {'status': 429, 'headers': {'retry-after': '5', 'x-ratelimit-global': 'true'},
                                                        'body': {'retry_after': 5, 'global': True}})
                elif what == 'hold':
                    with self.cluster.connect(autocommit=True) as db:
                        db.execute("UPDATE public.pr_discord_rate_state SET manual_hold=true WHERE kind='policy' AND scope_key=%s",
                                   ('00:' + stack.key,))
                else:
                    for permit in triggers:
                        stack.limiter.observe(permit, {'status': 500, 'headers': {}})
                thread.join(10)
                kind, outcome = results['booked']
                self.assertEqual(kind, 'stopped', 'it did not go out: %r' % (outcome,))
                self.assertIn(outcome.rate_cause, ('embargo', 'hold'))
                state, _ = self.admission(stack)
                self.assertEqual(state, 'blocked', 'closed unsent; its slot stays spent')
                self.assertEqual(stack.limiter.booking_stats()['gateStops'], 1)
                self.assertEqual(len([c for c in stack.wire.calls if c[1] == 'GET']), 1, 'only the warming read ever reached Discord')

    def test_a_booked_read_whose_process_dies_in_the_wait_keeps_its_slot_and_is_never_sent(self):
        stack = self.stack(capacity=3, latency=0, spread=0)
        self.full_window(stack, 3)
        dying = SharedPostgresBudget(stack.limiter.connection_factory, stack.app, policy=stack.policy,
                                     sleep=lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            dying.reserve_read('GET', '/guilds/710000000000000900', identity=stack.identity, book_ahead=1.0)
        state, sent = self.admission(stack)
        self.assertEqual(state, 'sent', 'an admission with no request at Discord: it holds its slot like any unanswered one')
        self.assertGreater(sent, self.cluster.now(), 'booked ahead of the clock')
        follower = stack.limiter.reserve_read('GET', '/guilds/710000000000000901', identity=stack.identity, book_ahead=1.0)
        self.assertIsNotNone(follower)
        self.assertLessEqual(busiest_closed(stack.stamps(), 1.0), 3)
        self.assertEqual(len(stack.wire.calls), 0, 'nothing reached Discord')

    def test_consume_refuses_a_booked_permit_before_its_slot_and_accepts_it_at_the_slot(self):
        stack = self.stack(capacity=3, latency=0, spread=0)
        self.full_window(stack, 3)
        impatient = SharedPostgresBudget(stack.limiter.connection_factory, stack.app, policy=stack.policy,
                                         sleep=lambda seconds: None, monotonic=lambda: 0.0)
        path = '/guilds/710000000000000902'
        permit = impatient.reserve('GET', path, identity=stack.identity, book_ahead=1.0)
        with self.assertRaises(RateDelayed) as caught:
            impatient.consume(permit, 'GET', path)
        self.assertEqual(caught.exception.rate_cause, 'permit_early')
        with self.cluster.connect(autocommit=True) as db:
            slot = float(db.execute('SELECT extract(epoch from reserved_at) FROM public.pr_discord_request_admissions WHERE id=%s::uuid',
                                    (permit.id,)).fetchone()[0])
        while self.cluster.now() < slot + .002:
            time.sleep(.01)
        impatient.consume(permit, 'GET', path)
        self.assertEqual(self.admission(stack)[0], 'sent')

    def test_a_web_caller_always_finds_a_slot_while_bookings_keep_the_rest_full(self):
        stack = self.stack(capacity=6, latency=.03, spread=0)
        stop, refused, admitted = time.monotonic() + 5, [], []

        def background(index):
            rng = random.Random(index)
            while time.monotonic() < stop:
                try:
                    with rate_limits.booking(1.0):
                        stack.read(rng.randrange(1000))
                except RateDelayed as error:
                    time.sleep(min(error.retry_after_seconds, 1.0))
        threads = [threading.Thread(target=background, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        time.sleep(1.5)
        for _ in range(8):   # a web request now and then, outside booking(): the immediate answer
            try:
                stack.read(secrets.randbelow(1000))
                admitted.append(1)
            except RateDelayed as error:
                refused.append(error.retry_after_seconds)
            time.sleep(.4)
        for thread in threads:
            thread.join()
        self.assertLessEqual(len(refused), 2, 'bookings leave a slot to the callers that cannot wait: %r' % refused)
        self.assertLessEqual(busiest_closed(stack.stamps(), 1.0), 6)


    def test_the_health_payload_shows_the_booked_horizon_while_a_read_waits_and_what_it_waited_afterwards(self):
        from postriff_phase2.discord import ops
        stack = self.stack(capacity=3, latency=0, spread=0)
        self.full_window(stack, 3)
        results = {}
        thread = self.booked_in_a_thread(stack, '/guilds/710000000000000950', results)
        time.sleep(.2)

        def read():
            with self.cluster.connect(autocommit=True) as db, db.cursor() as cur:
                return ops.read_booking(cur, self.cluster.now(), {})
        waiting = read()
        self.assertEqual(waiting['status'], 'observed')
        self.assertEqual(waiting['aheadNow'], 1, 'one admission still waits for its wire time')
        self.assertGreater(waiting['horizonSeconds'], .3)
        self.assertLess(waiting['horizonSeconds'], 1.0)
        thread.join(10)
        self.assertEqual(results['booked'][0], 'sent')
        done = read()
        self.assertEqual(done['aheadNow'], 0)
        self.assertEqual(done['horizonSeconds'], 0.0)
        self.assertEqual(done['bookedReads60s'], 1)
        self.assertGreater(done['bookedReadWaitSeconds60s'], .3)
        self.assertEqual(done['maxBookedReadWaitSeconds60s'], done['meanBookedReadWaitSeconds60s'])
        self.assertEqual(done['bookAheadSeconds'], 1.0)


if __name__ == '__main__':
    unittest.main()
