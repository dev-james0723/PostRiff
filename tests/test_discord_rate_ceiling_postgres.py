"""Real-PostgreSQL proof of the exact application-wide ceiling, of the bounded retention of unanswered requests and of the
length of the application row's critical section.

A disposable cluster from tests/discord_lane_fixture.py, the repository's own schema, the real coordinator and the real
DiscordProvider; Discord is the in-process mock. Every ceiling property is computed from the admission table, which is
the database clock, in whole microseconds, on each admission's WIRE time (sent_at, else reserved_at): the busiest CLOSED
interval of one window (and of one window plus the headroom) may hold at most `app_capacity` of them, across every
credential, reads and creates alike. The mock's own trailing second is reported and, where the headroom is widened on
purpose, asserted.

Runs where PostgreSQL server binaries are named by POSTRIFF_PG_BIN; never reads credentials or touches another database.
"""
import hashlib
import json
import os
import random
import secrets
import threading
import time
import unittest
from unittest.mock import patch

import psycopg
from dataclasses import replace

import discord_lane_fixture as F
from postriff_phase2 import providers
from postriff_phase2.discord.rate_limits import RateDelayed, RateCoordinatorUnavailable, RequestIdentity, SharedPostgresBudget
from postriff_phase2.social_connectors import DiscordProvider

GUARD = getattr(SharedPostgresBudget, 'SLOT_GUARD_SECONDS', 0.0)     # the production headroom between a slot's window and its freeing
WIRE = 'coalesce(sent_at,reserved_at)'


def busiest_closed(micros, span):
    """The most admissions in any closed interval of `span` seconds, from whole-microsecond stamps."""
    micros, limit, best, low = sorted(micros), int(round(span * 1_000_000)), 0, 0
    for high, stamp in enumerate(micros):
        while stamp - micros[low] > limit:
            low += 1
        best = max(best, high - low + 1)
    return best


class Counting(psycopg.Connection):
    """A connection that records every statement and commit it sends, in order (one entry is one round trip)."""
    log = None

    def commit(self):
        if self.log is not None:
            self.log.append('COMMIT')
        return super().commit()


class CountingCursor(psycopg.Cursor):
    def execute(self, query, params=None, **kwargs):
        if self.connection.log is not None:
            self.connection.log.append(' '.join(str(query).split()))
        return super().execute(query, params, **kwargs)


class Stack:
    """One application: its policy, coordinator, provider and mock Discord, over a shared cluster."""
    serial = 0

    def __init__(self, cluster, *, capacity=25, window=1, latency=0.0, tenants=40, **policy):
        Stack.serial += 1
        self.cluster = cluster
        self.app = '8%017d' % (int(time.time() * 1000) % 10**11 * 1000 + Stack.serial)
        self.tenants = [F.Tenant(n) for n in range(tenants)]
        self.wire = F.MockDiscord(self.tenants, latency=latency, ceiling=capacity)
        self.provider = DiscordProvider(self.app, 'synthetic-secret', 'synthetic-bot-token', 'https://rafii.example.invalid',
                                        transport=self.wire, production_reviewed=True)
        self.provider.authorization_v2_enabled = self.provider.connections_v2_enabled = self.provider.rate_v1_enabled = True
        self.policy = F.policy(cluster.now(), capacity=capacity, app_window_seconds=window, **policy)
        self.limiter = SharedPostgresBudget(cluster.factory(), self.app, policy=self.policy)
        self.provider.rate_limiter = self.limiter
        self.identity = RequestIdentity.make(self.app, 'bot', 'synthetic-bot-token')
        self.key = hashlib.sha256(self.app.encode()).hexdigest()
        self.capacity, self.window = capacity, window

    def stamps(self):
        """Every admission's wire time (a read when admitted, a create when its permit was used), in microseconds."""
        with self.cluster.connect(autocommit=True) as db:
            return [row[0] for row in db.execute(
                f'SELECT (extract(epoch from {WIRE})*1000000)::bigint FROM public.pr_discord_request_admissions '
                'WHERE application_key=%s ORDER BY request_seq', (self.key,))]

    def read(self, number=0):
        """One real provider GET: admission, mock Discord, observation. Raises RateDelayed when the budget is spent."""
        return self.provider._bot('GET', '/guilds/' + self.tenants[number % len(self.tenants)].guild)

    def hammer(self, workers, seconds):
        """`workers` threads asking for as long as `seconds`, each backing off the way a caller does."""
        stop = time.monotonic() + seconds
        counts = {'ok': 0, 'delayed': 0, 'other': []}
        lock = threading.Lock()

        def run(index):
            rng = random.Random(index)
            while time.monotonic() < stop:
                try:
                    self.read(rng.randrange(1000))
                    outcome = 'ok'
                except RateDelayed as error:
                    outcome = 'delayed'
                    time.sleep(min(error.retry_after_seconds, 1.0) + secrets.randbelow(26) / 1000)
                except Exception as error:  # noqa: BLE001 - reported by the test
                    outcome = 'other'
                    with lock:
                        counts['other'].append(repr(error)[:100])
                with lock:
                    if outcome != 'other':
                        counts[outcome] += 1
        began = time.monotonic()
        threads = [threading.Thread(target=run, args=(n,)) for n in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        counts['elapsed'] = time.monotonic() - began
        return counts


OK = {'status': 200, 'headers': {}}


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class ExactCeilingOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def burst(self, stack, count):
        """`count` simultaneous reservations (each its own thread and connection), answered at once like a caller's
        would be; how many were admitted."""
        admitted, barrier = [], threading.Barrier(count)
        base = 710000000000000000 + 1000 * len(stack.stamps())

        def one(index):
            barrier.wait(30)
            try:
                permit = stack.limiter.reserve_read('GET', '/guilds/%d' % (base + index), identity=stack.identity)
                stack.limiter.observe(permit, OK)
                admitted.append(1)
            except RateDelayed:
                pass
        threads = [threading.Thread(target=one, args=(n,)) for n in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return len(admitted)

    def sleep_until(self, epoch):
        while True:
            remaining = epoch - self.cluster.now()
            if remaining <= 0:
                return
            time.sleep(min(remaining, .05))

    def answered(self, stack, path):
        """One admission, answered at once."""
        permit = stack.limiter.reserve_read('GET', path, identity=stack.identity)
        stack.limiter.observe(permit, OK)
        return permit

    def states(self, stack):
        with self.cluster.connect(autocommit=True) as db:
            return dict(db.execute('SELECT state,count(*) FROM public.pr_discord_request_admissions WHERE application_key=%s '
                                   'GROUP BY state', (stack.key,)).fetchall())

    def circuits(self, stack, *, open_only=False):
        """(circuits set, longest failure streak) over the scope rows THIS application's admissions touched. The tests of a
        class share one cluster, so a count over the whole table would see the circuit another test opened on purpose."""
        condition = 'circuit_until>clock_timestamp()' if open_only else 'circuit_until IS NOT NULL'
        with self.cluster.connect(autocommit=True) as db:
            count, streak = db.execute(
                f'SELECT count(*) FILTER (WHERE {condition}),coalesce(max(error_streak),0) FROM public.pr_discord_rate_state '
                'WHERE scope_key IN (SELECT unnest(scope_keys) FROM public.pr_discord_request_admissions WHERE application_key=%s)',
                (stack.key,)).fetchone()
        return count, streak

    # --- the old failure, made deterministic ------------------------------------------------------------------------

    def test_a_late_burst_and_a_burst_just_after_it_cannot_double_the_ceiling(self):
        """The fixed window refilled every slot when it ended. Nine admissions late in one window and ten right after
        it put 19 into one second against a cap of ten: this fails on the fixed window and passes on the sliding one."""
        stack = Stack(self.cluster, capacity=10)
        self.answered(stack, '/guilds/710000000000000001')   # starts the window
        first = stack.stamps()[0] / 1e6
        self.sleep_until(first + .55)
        late = self.burst(stack, 9)
        self.sleep_until(first + 1.06)        # past the end of the fixed window, past the headroom of the first slot
        early = self.burst(stack, 10)
        stamps = stack.stamps()
        self.assertEqual(late, 9)
        self.assertLessEqual(early, 2, 'only the first admission is old enough to have freed its slot')
        self.assertLessEqual(busiest_closed(stamps, 1.0), 10)
        self.assertLessEqual(busiest_closed(stamps, 1.0 + GUARD), 10)

    def test_a_caller_that_sleeps_exactly_the_quoted_wait_is_admitted_at_its_first_retry(self):
        stack = Stack(self.cluster, capacity=4)
        for number in range(4):
            self.answered(stack, '/guilds/%d' % (710000000000000100 + number))
            time.sleep(.03)
        retries = 0
        for number in range(8):
            while True:
                try:
                    self.answered(stack, '/guilds/%d' % (710000000000000200 + number))
                    break
                except RateDelayed as error:
                    retries += 1
                    self.assertEqual(error.rate_scope_kind, 'application')
                    time.sleep(error.retry_after_seconds + .002)
        self.assertLessEqual(retries, 12, 'about one refusal per admission, not a spin: the quoted wait was the real one')
        self.assertLessEqual(busiest_closed(stack.stamps(), 1.0 + GUARD), 4)

    # --- many threads, several seconds ------------------------------------------------------------------------------

    def run_hammer(self, capacity, in_flight, workers=16, seconds=7):
        stack = Stack(self.cluster, capacity=capacity, latency=in_flight)
        counts = stack.hammer(workers, seconds)
        stamps = stack.stamps()
        steady = [s for s in stamps if stamps[0] + 1_000_000 <= s <= stamps[-1] - 1_000_000]
        span = (stamps[-1] - stamps[0] - 2_000_000) / 1e6
        return stack, counts, stamps, (len(steady) / span if span > 0 else 0.0)

    def test_the_ceiling_holds_for_every_time_in_flight_and_the_rate_stays_up(self):
        """Admission to answer takes 0, 120 and 200 ms (the mock's latency): the busiest second of the database clock
        never exceeds the cap, no route limit of the mock is ever hit, every admission is answered, and the sustained
        rate is a large share of the cap (cap x window / (window + headroom) is the most it can be)."""
        capacity = 10          # a rate this box can carry while other agents load it; the share is what is asserted
        for in_flight in (0, .12, .2):
            with self.subTest(in_flight_ms=int(in_flight * 1000)):
                stack, counts, stamps, rate = self.run_hammer(capacity, in_flight)
                self.assertEqual(counts['other'], [])
                self.assertGreater(len(stamps), 40, 'the run was busy enough to meet the cap')
                self.assertLessEqual(busiest_closed(stamps, 1.0), capacity)
                self.assertLessEqual(busiest_closed(stamps, 1.0 + GUARD), capacity)
                self.assertEqual(stack.wire.route429, 0, 'no route limit was ever reached')
                self.assertEqual(self.states(stack), {'observed': len(stamps)}, 'every admitted request was answered')
                self.assertGreaterEqual(rate, .8 * capacity, 'sustained admissions per second (steady middle of the run)')

    def test_the_owners_cap_holds_with_many_threads_and_the_mock_sees_no_more(self):
        """cap 25 across 32 threads, each answered after 50 ms. The coordinator's guarantee is strict: no closed second of wire
        times holds more than 25. The mock's own trailing second is the arrival side, which the owner's D-16 reads as reported
        and not failed (Discord's real limit is 50): it stays within two requests of the cap and almost never above it. (Asserted
        strictly it failed once in a run on a loaded shared box, when a thread was descheduled for more than the 50 ms the guard
        absorbs between a request's wire time and its arrival; tests/discord_ceiling_probe.py reports the distribution.)"""
        stack, counts, stamps, rate = self.run_hammer(25, .05, workers=32, seconds=8)
        self.assertEqual(counts['other'], [])
        self.assertLessEqual(busiest_closed(stamps, 1.0), 25)
        self.assertLessEqual(stack.wire.over_ceiling, max(2, len(stamps) // 50), 'almost no trailing second above 25 at the mock')
        self.assertLessEqual(stack.wire.peak_second, 27)
        self.assertEqual(stack.wire.route429, 0)

    def mixed_credentials(self, **policy):
        """Twelve threads asking with the bot's token, a person's bearer and the client secret in turn, reads and permits alike,
        for five seconds, on a policy of cap 12 (and whatever else `policy` says)."""
        stack = Stack(self.cluster, capacity=12, **policy)
        bot = stack.identity
        user = RequestIdentity.make(stack.app, 'user', 'someone', '810000000000000001')
        oauth = RequestIdentity.make(stack.app, 'oauth', 'a-client-secret-with-enough-length')
        stop = time.monotonic() + 5
        errors, lock = [], threading.Lock()

        def run(index):
            rng = random.Random(index)
            identity = (bot, user, oauth)[index % 3]
            while time.monotonic() < stop:
                path = '/guilds/%d' % (720000000000000000 + rng.randrange(10**6))
                try:
                    if index % 2:
                        permit = stack.limiter.reserve_read('GET', path, identity=identity)
                    else:
                        permit = stack.limiter.reserve('GET', path, identity=identity)
                        stack.limiter.consume(permit, 'GET', path)
                    stack.limiter.observe(permit, OK)
                except RateDelayed as error:
                    time.sleep(min(error.retry_after_seconds, 1.0) + secrets.randbelow(26) / 1000)
                except RateCoordinatorUnavailable:
                    pass
                except Exception as error:  # noqa: BLE001
                    with lock:
                        errors.append(repr(error)[:100])
        threads = [threading.Thread(target=run, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        return stack

    def kind_stamps(self, stack):
        """(the wire times of the person's bearer, of every other credential), in whole microseconds, and the kinds admitted."""
        with self.cluster.connect(autocommit=True) as db:
            rows = db.execute(f"SELECT credential_kind,(extract(epoch from {WIRE})*1000000)::bigint FROM public.pr_discord_request_admissions "
                              'WHERE application_key=%s ORDER BY request_seq', (stack.key,)).fetchall()
        return ([m for kind, m in rows if kind == 'user'], [m for kind, m in rows if kind != 'user'], {kind for kind, _ in rows})

    def test_every_credential_and_both_kinds_of_admission_share_one_ceiling_without_a_bearer_budget(self):
        """A policy without the bearer pair (what a build that predates the bearer budget reads, and the way back to it): the
        person's bearer is charged to the application budget with every other credential."""
        stack = self.mixed_credentials(bearer_capacity=None, bearer_window_seconds=None)
        stamps = stack.stamps()
        self.assertGreater(len(stamps), 30)
        self.assertLessEqual(busiest_closed(stamps, 1.0), 12)
        self.assertEqual(self.kind_stamps(stack)[2], {'bot', 'user', 'oauth'}, 'all credential kinds were admitted')

    def test_every_credential_but_the_person_s_bearer_shares_one_ceiling_and_the_bearer_has_its_own(self):
        """With the bearer budget (the owner's D-2 option 1): the bot, the client secret and (not here) a webhook secret share the
        application ceiling; the person's own bearer has a second exact ceiling, and neither takes a slot of the other."""
        stack = self.mixed_credentials(bearer_capacity=5, bearer_window_seconds=1)
        bearer, rest, kinds = self.kind_stamps(stack)
        self.assertGreater(len(rest), 30)
        self.assertGreater(len(bearer), 10)
        self.assertLessEqual(busiest_closed(rest, 1.0), 12, 'the bot and the client secret share the application ceiling')
        self.assertLessEqual(busiest_closed(bearer, 1.0), 5, 'the bearer has its own')
        self.assertEqual(kinds, {'bot', 'user', 'oauth'}, 'all credential kinds were admitted')

    def test_a_learned_route_limit_is_never_exceeded(self):
        """The mock allows fifty reads a second per read route and resource. Many threads read one guild through the
        real provider path: 429s from the mock must stay zero."""
        stack = Stack(self.cluster, capacity=25, tenants=1)
        counts = stack.hammer(10, 6)
        self.assertEqual(counts['other'], [])
        self.assertEqual(stack.wire.route429, 0)

    # --- a create reaches Discord when its permit is used, not when it was reserved ----------------------------------

    def test_a_create_used_late_holds_its_slot_from_its_use_so_no_window_of_wire_times_exceeds_the_cap(self):
        """Reserved at once, used 1.3 s later: the slot it holds runs from its use. Counted from its reservation (the
        window before the permit lifetime was lengthened) the cap would be exceeded by one in the second after it."""
        stack = Stack(self.cluster, capacity=5)
        path = '/guilds/730000000000000001'
        permit = stack.limiter.reserve('GET', path, identity=stack.identity)
        time.sleep(1.3)
        stack.limiter.consume(permit, 'GET', path)
        stack.limiter.observe(permit, OK)
        admitted = 0
        for number in range(8):
            try:
                self.answered(stack, '/guilds/%d' % (730000000000000100 + number))
                admitted += 1
            except RateDelayed:
                break
        self.assertEqual(admitted, 4, 'one of the five slots is the create\'s, for a window after its use')
        self.assertLessEqual(busiest_closed(stack.stamps(), 1.0), 5)
        self.assertLessEqual(busiest_closed(stack.stamps(), 1.0 + GUARD), 5)

    def test_a_permit_lives_the_policy_lifetime_and_the_callers_deadline_and_outlives_the_window(self):
        stack = Stack(self.cluster, capacity=25)
        path = '/guilds/730000000000000002'
        permit = stack.limiter.reserve('GET', path, identity=stack.identity)
        with self.cluster.connect(autocommit=True) as db:
            lifetime = db.execute('SELECT extract(epoch from expires_at-reserved_at) FROM public.pr_discord_request_admissions '
                                  'WHERE id=%s', (permit.id,)).fetchone()[0]
        ttl = json.loads(stack.policy)['permit_ttl_seconds']
        self.assertAlmostEqual(float(lifetime), ttl, delta=.05, msg='not the one-second application window')
        time.sleep(1.3)                                          # the window that reserved it is long over
        stack.limiter.consume(permit, 'GET', path)               # it used to die here
        self.assertEqual(self.states(stack), {'sent': 1})
        short = stack.limiter.reserve('GET', '/guilds/730000000000000003', identity=stack.identity,
                                      valid_until=self.cluster.now() + .4)    # the lease or approval ends first
        time.sleep(.6)
        with self.assertRaises(RateDelayed) as caught:
            stack.limiter.consume(short, 'GET', '/guilds/730000000000000003')
        self.assertEqual(caught.exception.rate_cause, 'permit_expired')

    # --- what the exact count costs ----------------------------------------------------------------------------------

    def test_the_application_row_is_held_for_a_reading_one_write_statement_and_the_commit(self):
        """Round trips are what the lock costs. After the statement that takes the locks a reservation sends THREE: one
        that reads the clock and the window (it must start after the lock: a statement keeps the snapshot it began with),
        ONE that writes every changed scope and the admission together, and the commit. It used to send four to seven
        (clock, a count for every refilled row, the scopes, the admission, the commit). An observation sends at most six
        (it used to send nine). Cold and learned routes alike."""
        log = []

        class Connection(Counting):
            pass
        Connection.log = log
        stack = Stack(self.cluster, capacity=25)
        stack.limiter = SharedPostgresBudget(
            lambda: Connection.connect(self.cluster.dsn, prepare_threshold=None, cursor_factory=CountingCursor),
            stack.app, policy=stack.policy)
        headers = {'x-ratelimit-bucket': 'held-for-one', 'x-ratelimit-limit': '1000', 'x-ratelimit-remaining': '999',
                   'x-ratelimit-reset-after': '1.000'}

        def after_the_lock(statements):
            index = next(i for i, text in enumerate(statements) if text.startswith('WITH scope_lock'))
            return statements[index + 1:]
        path = '/guilds/730000000000000010'
        for label in ('cold route', 'learned route'):
            with self.subTest(label):
                log.clear()
                permit = stack.limiter.reserve_read('GET', path, identity=stack.identity)
                rest = after_the_lock(list(log))
                self.assertEqual(len(rest), 3, rest)
                self.assertTrue(rest[0].startswith('WITH tick AS MATERIALIZED'), 'the clock and the window, read after the lock')
                self.assertTrue(rest[1].startswith('WITH scope_store(') and 'INSERT INTO public.pr_discord_request_admissions' in rest[1])
                self.assertEqual(rest[2], 'COMMIT')
                log.clear()
                stack.limiter.observe(permit, {'status': 200, 'headers': headers})
                self.assertLessEqual(len(after_the_lock(list(log))), 7 if label == 'cold route' else 6)

    def test_the_window_statement_reads_a_bounded_number_of_blocks_whatever_the_history(self):
        """O(cap), not O(history): the admissions that can occupy a slot are the newest few hundred by request_seq, and
        the ones held past their span come from the partial index of unresolved admissions. Measured with EXPLAIN
        (ANALYZE, BUFFERS) over 2,000 and then 60,000 retained, answered, hour-old rows."""
        stack = Stack(self.cluster, capacity=25)
        self.answered(stack, '/guilds/730000000000000020')   # creates the row set
        statements = []

        class Spy:
            def __init__(self, cur):
                self.cur = cur

            def execute(self, query, parameters=None):
                statements.append((query, parameters))
                return self.cur.execute(query, parameters)

            def __getattr__(self, name):
                return getattr(self.cur, name)

        blocks = {}
        for history in (2000, 60000):
            with self.cluster.connect() as db:
                db.execute('''INSERT INTO public.pr_discord_request_admissions
                    (id,application_key,auth_key,credential_key,credential_kind,method,path_key,route_key,major_key,scope_keys,
                     state,reserved_at,expires_at,sent_at,outcome_at,status_code,rate_scope)
                    SELECT gen_random_uuid(),%s,%s,%s,'bot','GET',%s,%s,%s,ARRAY[%s,%s,%s,%s,%s,%s],'observed',
                        clock_timestamp()-interval '1 hour'-(g||' milliseconds')::interval,
                        clock_timestamp()-interval '59 minutes',clock_timestamp()-interval '1 hour'-(g||' milliseconds')::interval,
                        clock_timestamp()-interval '59 minutes',200,'unknown'
                    FROM generate_series(1,%s) g''',
                           (stack.key, *(hashlib.sha256(x.encode()).hexdigest() for x in ('a', 'b', 'c', 'd', 'e')),
                            *('0%d:' % n + hashlib.sha256(b'k').hexdigest() for n in range(6)), history))
            with self.cluster.connect(autocommit=True) as db:
                db.execute('ANALYZE public.pr_discord_request_admissions')
            statements.clear()
            with stack.limiter._transaction() as cur:
                stack.limiter._window_state(Spy(cur), 25, 1.0, self.cluster.now())
                query, parameters = statements[-1]
                plan = cur.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query, parameters).fetchone()[0][0]
            text = json.dumps(plan)
            self.assertNotIn('"Node Type": "Seq Scan", "Parallel Aware": false, "Async Capable": false, "Relation Name": "pr_discord_request_admissions"',
                             text, 'no sequential scan of the admissions, however many are retained')

            def total(node):
                return node.get('Shared Hit Blocks', 0) + node.get('Shared Read Blocks', 0)
            blocks[history] = total(plan['Plan'])
        self.assertLessEqual(blocks[60000], blocks[2000] + 40, 'the same few blocks whether 2,000 or 60,000 rows are retained (%r)' % blocks)
        self.assertLess(blocks[60000], 400)

    # --- the nickname route's admissions, on real SQL -----------------------------------------------------------------

    def test_a_lost_nickname_write_is_retired_by_id_after_a_token_rotation_and_every_reader_tolerates_the_result(self):
        """The sender claim keeps only the admission id. After the bot token changed, the permit-based reconcile refuses for
        good (the credential digest differs); by id it settles the row: `observed`, no status invented (NULL), scope
        `unknown`. The reader in ops.py and report() must not trip over a settled row without a status."""
        from postriff_phase2.discord import ops
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}):
            self.nickname_case(ops)

    def nickname_case(self, ops):
        stack = Stack(self.cluster, capacity=25)
        guild = '740000000000009001'
        path = '/guilds/%s/members/@me' % guild
        permit = stack.limiter.reserve('PATCH', path, identity=stack.identity)
        stack.limiter.consume(permit, 'PATCH', path)
        stack.limiter.note_transport_failure(permit)               # the response never came
        self.assertEqual(self.states(stack), {'uncertain': 1})
        with stack.limiter._transaction() as cur:
            with self.assertRaises(RateCoordinatorUnavailable):
                stack.limiter.reconcile_nickname_by_id(cur, permit.id, guild)      # too young: the 120 s have not passed
        with self.cluster.connect(autocommit=True) as db:             # the 120 seconds, and the permit's own deadline, pass
            db.execute("UPDATE public.pr_discord_request_admissions SET reserved_at=reserved_at-interval '3 minutes',"
                       "expires_at=expires_at-interval '3 minutes',sent_at=sent_at-interval '3 minutes' WHERE id=%s", (permit.id,))
        rotated = replace(permit, identity=RequestIdentity.make(stack.app, 'bot', 'the-rotated-bot-token'))
        with stack.limiter._transaction() as cur:
            with self.assertRaises(RateCoordinatorUnavailable):
                stack.limiter.reconcile_nickname(cur, rotated, guild)             # for ever, by permit
            with self.assertRaises(RateCoordinatorUnavailable):
                stack.limiter.reconcile_nickname_by_id(cur, permit.id, '740000000000009002')   # another server
        with stack.limiter._transaction() as cur:
            stack.limiter.reconcile_nickname_by_id(cur, permit.id, guild)
        with stack.limiter._transaction() as cur:
            stack.limiter.reconcile_nickname_by_id(cur, permit.id, guild)         # a duplicate is silent
        with self.cluster.connect(autocommit=True) as db:
            row = db.execute('SELECT state,status_code,rate_scope,outcome_at IS NOT NULL FROM public.pr_discord_request_admissions '
                             'WHERE id=%s', (permit.id,)).fetchone()
        self.assertEqual(row, ('observed', None, 'unknown', True))
        report = stack.limiter.report()
        self.assertEqual(report['status'], 'sampled')
        self.assertIn(('observed', 'unknown'), {(c['state'], c['scope']) for c in report['counts']})
        with self.cluster.connect(autocommit=True) as db, db.cursor() as cur:
            now = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
            ops.read_ledger(cur, now, {})                                         # raises on a type it cannot read

    def test_a_403_and_a_404_close_a_route_for_a_bounded_time_or_not_at_all_on_real_sql(self):
        """The sender-name review measured 86,340 s of refusal after one 403 on the nickname write (up to 31 days). A 403
        closes that server's route for circuit_seconds (30 in the reviewed policy); a 404 on a read closes nothing."""
        stack = Stack(self.cluster, capacity=25)
        circuit = json.loads(stack.policy)['circuit_seconds']
        path = '/guilds/740000000000009100/members/@me'
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}):
            permit = stack.limiter.reserve('PATCH', path, identity=stack.identity)
            stack.limiter.consume(permit, 'PATCH', path)
            stack.limiter.observe(permit, {'status': 403, 'headers': {}})
            with self.assertRaises(RateDelayed) as caught:
                stack.limiter.reserve('PATCH', path, identity=stack.identity)
        self.assertEqual(caught.exception.rate_scope_kind, 'embargo')
        self.assertLessEqual(caught.exception.retry_after_seconds, circuit + .5, 'a bounded circuit, not the policy lifetime')
        self.assertGreater(caught.exception.retry_after_seconds, circuit - 5)
        message = '/channels/740000000000009101/messages/740000000000009102'
        read = stack.limiter.reserve_read('GET', message, identity=stack.identity)
        stack.limiter.observe(read, {'status': 404, 'headers': {}})           # a deleted message
        time.sleep(1.2)                                                       # the cold route's own one-second probe window
        other = stack.limiter.reserve_read('GET', '/channels/740000000000009101/messages/740000000000009103',
                                           identity=stack.identity)           # another message of the channel is read
        stack.limiter.observe(other, {'status': 404, 'headers': {}})
        open_circuits, _streak = self.circuits(stack, open_only=True)
        self.assertEqual(open_circuits, 1, 'only the nickname route of the server that refused is closed')

    # --- the leak that used to stall everything for good ------------------------------------------------------------

    def hostile_world(self, guilds):
        """Each hostile guild's channel list is a 200 over 256 KiB, which the real transport refuses AFTER it arrived."""
        stack = Stack(self.cluster, capacity=25, tenants=guilds + 2)
        hostile = {t.guild for t in stack.tenants[:guilds]}
        wire = stack.wire

        class Response:
            def __init__(self, status, headers, body):
                self.status, self.headers, self._body = status, headers, body

            def read(self, count=-1):
                return self._body if count < 0 else self._body[:count]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Opener:
            def open(self, request, timeout=None):
                path = request.full_url.removeprefix(DiscordProvider.API)
                parts = path.strip('/').split('/')
                if len(parts) == 3 and parts[0] == 'guilds' and parts[2] == 'channels' and parts[1] in hostile:
                    body = json.dumps([{'id': str(7000000 + n), 'type': 0, 'name': 'c%d' % n, 'topic': 'x' * 1024,
                                        'guild_id': parts[1], 'permission_overwrites': []} for n in range(400)]).encode()
                    assert len(body) > 262144
                    return Response(200, {'X-RateLimit-Bucket': 'hostile-list', 'X-RateLimit-Limit': '5',
                                          'X-RateLimit-Remaining': '4', 'X-RateLimit-Reset-After': '5'}, body)
                answer = wire(request.get_method(), request.full_url, headers=dict(request.header_items()), body=None)
                return Response(answer['status'], answer['headers'], json.dumps(answer['body']).encode())

        stack.provider.transport = providers.http_transport      # the real transport, with its real 256 KiB cap
        return stack, hostile, (lambda *handlers: Opener())

    def test_twenty_six_hostile_guilds_leave_the_budget_whole(self):
        """The reviewer's reproduction. Each hostile guild's channel list is a 200 over 256 KiB, which the real transport
        refuses AFTER it arrived. Failing before: every refused answer was recorded as an uncertain admission, 25 of them
        took the shared budget to 0 for every tenant, and nothing released them. Now the refusal is an observed outcome:
        no admission is left unresolved and one window later the whole budget is there."""
        from postriff_alpha.domain import AlphaError
        stack, hostile, opener = self.hostile_world(26)
        with patch.object(providers, 'build_opener', opener):
            refused = 0
            for tenant in stack.tenants[:26]:
                try:
                    stack.provider._bot('GET', '/guilds/%s/channels' % tenant.guild)
                except AlphaError:
                    refused += 1
            self.assertEqual(refused, 26)
        states = self.states(stack)
        self.assertEqual({key: value for key, value in states.items() if key in ('sent', 'uncertain')}, {})
        self.assertGreaterEqual(states.get('observed', 0), 25, 'every admitted call is resolved, none left unresolved')
        time.sleep(1 + GUARD + .25)
        admitted = self.burst(stack, 30)
        self.assertGreaterEqual(admitted, 25, 'the whole budget is back one window after the attack')
        self.assertLessEqual(busiest_closed(stack.stamps(), 1.0), 25)

    def test_one_hostile_guild_with_a_learned_route_cannot_leak_or_open_a_circuit(self):
        """The refined reproduction: a route learned from the answer's own headers, then answered over the cap again and
        again. It used to leak one uncertain admission a call and open the route's circuit after three."""
        from postriff_alpha.domain import AlphaError
        stack, hostile, opener = self.hostile_world(1)
        with patch.object(providers, 'build_opener', opener):
            for _ in range(5):
                with self.assertRaises(AlphaError):
                    stack.provider._bot('GET', '/guilds/%s/channels' % stack.tenants[0].guild)
        states = self.states(stack)
        self.assertEqual(states, {'observed': 5})
        self.assertEqual(self.circuits(stack), (0, 0), 'a refusal for size is not an outage')

    def test_requests_whose_observation_failed_or_whose_process_died_stop_holding_slots(self):
        """Twenty-five reads admitted and never observed (observe() timed out on its lock, or the process died after the
        send), and twenty-five creates that were consumed and then lost: the application is full until window + margin
        has passed since each was sent, then it admits the whole cap again. The margin is shortened to keep the run short."""
        with patch.object(SharedPostgresBudget, 'UNOBSERVED_MARGIN_SECONDS', 1.5, create=True):
            stack = Stack(self.cluster, capacity=10)
            for number in range(5):
                stack.limiter.reserve_read('GET', '/guilds/%d' % (740000000000000000 + number), identity=stack.identity)
            for number in range(5):                       # consume() commits `sent` before the POST: a crash leaves it
                path = '/guilds/%d' % (740000000000000100 + number)
                stack.limiter.consume(stack.limiter.reserve('GET', path, identity=stack.identity), 'GET', path)
            self.assertEqual(self.states(stack), {'sent': 10})
            with self.assertRaises(RateDelayed) as caught:
                self.answered(stack, '/guilds/740000000000000900')
            self.assertEqual(caught.exception.rate_scope_kind, 'application')
            # Past the span (1.05 s) every one of them is older than a window, and only the SQL clause that keeps an unanswered request
            # (sent or uncertain, for the window plus the margin) still counts it: the independent review's mutant S1, which turns that
            # clause off, survived every test that looked only at the start and at the end.
            time.sleep(1.3)
            with self.assertRaises(RateDelayed) as middle:
                self.answered(stack, '/guilds/740000000000000901')
            self.assertEqual(middle.exception.rate_scope_kind, 'application', 'still counted: a request never answered may still reach Discord')
            time.sleep(1.5 + .3 - 1.3 + 1)
            free = 0
            try:
                while free < 20:
                    self.answered(stack, '/guilds/%d' % (740000000000001000 + free))
                    free += 1
            except RateDelayed:
                pass
            self.assertEqual(free, 10, 'the whole cap is back, the ten lost requests still in the table as sent')
            self.assertEqual(self.states(stack).get('sent'), 10)

    def test_a_cold_routes_probe_held_by_a_lost_request_is_freed_when_that_request_ages_out(self):
        """The first request to a route nobody has learned yet is its only probe. If its answer is lost, a second request
        to the same route waits until the first can no longer matter (window + margin), then goes."""
        with patch.object(SharedPostgresBudget, 'UNOBSERVED_MARGIN_SECONDS', 1.5, create=True):
            stack = Stack(self.cluster, capacity=25)
            path = '/guilds/740000000000002000'
            stack.limiter.reserve_read('GET', path, identity=stack.identity)      # never answered
            with self.assertRaises(RateDelayed) as caught:
                stack.limiter.reserve_read('GET', path, identity=stack.identity)
            self.assertIn(caught.exception.rate_scope_kind, ('unknown_route', 'discovery'))
            deadline = time.monotonic() + 8
            while True:
                try:
                    self.answered(stack, path)
                    break
                except RateDelayed:
                    self.assertLess(time.monotonic(), deadline, 'the probe must be freed within window + margin')
                    time.sleep(.3)

    def test_a_refilled_learned_route_whose_permits_all_expired_unused_is_served_at_once(self):
        """The stuck route, scratchpad stuck/repro.py as a test: a learned route (5 per second) is refilled, five permits are
        reserved for the new window and none is ever used. The next read used to be refused with the policy's remaining life
        (86,336 s on a one-day policy) because the window waited for an answer that no request could bring."""
        stack = Stack(self.cluster, capacity=200, tenants=2, permit_ttl_seconds=1)
        stack.wire.read_limit = (5, 1.0)
        path = '/guilds/%s' % stack.tenants[0].guild
        stack.read(0)                                                       # the probe: its answer teaches the route
        stack.read(0)
        time.sleep(1.2)                                                     # that window ends
        permits = [stack.limiter.reserve('GET', path, identity=stack.identity) for _ in range(5)]   # the refill, five permits
        self.assertEqual(len(permits), 5)
        time.sleep(1.5)                                                     # every one expires unused: no request, no answer
        answer = stack.provider._bot('GET', path)                           # was: RateDelayed, wait 86,336 s
        self.assertEqual(answer['status'], 200)
        self.assertEqual(len(stack.wire.calls), 3, 'the three real reads; nothing was sent for the unused permits')

    def test_a_learned_route_whose_answers_were_all_lost_is_served_again(self):
        """A route learned from headers is refilled and then every request of the new window is lost (here: sent and
        never answered). It used to wait for an answer that cannot come, with the policy's end as its next reset."""
        stack = Stack(self.cluster, capacity=100, tenants=3)
        path = '/guilds/%s' % stack.tenants[0].guild
        headers = {'X-RateLimit-Bucket': 'lost-window', 'X-RateLimit-Limit': '3', 'X-RateLimit-Remaining': '2',
                   'X-RateLimit-Reset-After': '1'}
        with patch.object(SharedPostgresBudget, 'UNOBSERVED_MARGIN_SECONDS', 1.0, create=True):
            learner = stack.limiter.reserve_read('GET', path, identity=stack.identity)
            stack.limiter.observe(learner, {'status': 200, 'headers': headers})
            time.sleep(1.1)                                    # the learned window ends
            for _ in range(3):
                stack.limiter.reserve_read('GET', path, identity=stack.identity)   # the refill's slots: never answered
            with self.assertRaises(RateDelayed) as caught:
                stack.limiter.reserve_read('GET', path, identity=stack.identity)
            self.assertLess(caught.exception.retry_after_seconds, 5, 'a poll, never the policy expiry')
            deadline = time.monotonic() + 8
            while True:
                try:
                    stack.limiter.reserve_read('GET', path, identity=stack.identity)
                    break
                except RateDelayed as error:
                    self.assertLess(error.retry_after_seconds, 5)
                    self.assertLess(time.monotonic(), deadline, 'the lapsed wait must end within window + margin')
                    time.sleep(.3)


if __name__ == '__main__':
    unittest.main()
