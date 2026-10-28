"""The lane's side of booking (docs/w02/OPEN-QUESTIONS.md, Q19; docs/w02/AMPLIFICATION.md), offline.

The lane asks to be booked in exactly four places, around the calls that read or reserve for a post: the preflight, the create
permit and the read-back, which the worker makes in two ways (`reconcile_discord` for a reply, `reconcile` for every other post,
which reaches HostedSocial's own `reconcile_discord`). Nothing else books: a direct provider call, another thread, the minute worker and a web request keep
the immediate answer. The loop's budget, the stored application row `lane.outlook` reads and the two new counters are proved
here; the coordinator's arithmetic is test_discord_rate_booking.py, real PostgreSQL is test_discord_lane_booking_postgres.py.
No database, network or credential.
"""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from postriff_phase2.discord import lane, rate_limits
from postriff_phase2.discord.rate_limits import RequestIdentity, SharedPostgresBudget
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_parallel_lane import FakeLane, ON, Outlook
from test_discord_rate_ceiling import OK, T0, policy
from test_discord_rate_limits import APP, MemoryLedger


class Seen:
    """A social whose Discord calls report the booking context they were made in."""
    def __init__(self):
        self.calls, self.providers, self.aside = [], {}, []

    def note(self, name):
        self.calls.append((name, rate_limits.current_book_ahead()))
        thread = threading.Thread(target=lambda: self.aside.append((name, rate_limits.current_book_ahead())))
        thread.start()
        thread.join()

    def prepare_discord_dispatch(self, manifest, **kw):
        self.note('prepare')
        return {'prepared': True}

    def reserve_discord_send(self, manifest, **kw):
        self.note('reserve')
        return 'permit'

    def reconcile_discord(self, manifest, job, **kw):
        self.note('reconcile')
        return {'state': 'verified'}

    def reconcile(self, manifest, job):
        """HostedSocial.reconcile: the worker's read-back of every post that is not a reply goes through it, and it calls ITS OWN
        reconcile_discord, never the wrapper's (hosted_worker.py, hosted_social.py)."""
        if manifest.get('platform') == 'Discord':
            return self.reconcile_discord(manifest, job)
        return {'state': 'uncertain'}

    def submit_discord_authorized(self, manifest, dispatch):
        self.note('submit')
        return {'state': 'provider_accepted'}

    def anything_else(self):
        self.note('other')


class TheLaneBooksInFourPlacesOnly(unittest.TestCase):
    def test_prepare_reserve_and_both_read_backs_run_inside_booking_and_nothing_else_does(self):
        seen = Seen()
        paced = lane.PacedSocial(seen)
        paced.prepare_discord_dispatch({}, read_authorize=None)
        paced.reserve_discord_send({}, job={})
        paced.reconcile_discord({}, {}, read_authorize=None)           # a reply's read-back
        paced.reconcile({'platform': 'Discord'}, {})                    # every other post's: the worker's `reconcile`
        paced.submit_discord_authorized({}, {})
        paced.anything_else()
        self.assertEqual(seen.calls, [('prepare', 1.0), ('reserve', 1.0), ('reconcile', 1.0), ('reconcile', 1.0),
                                      ('submit', 0.0), ('other', 0.0)])
        self.assertEqual(rate_limits.current_book_ahead(), 0.0, 'and none of it outlives the call')

    def test_the_read_back_of_an_ordinary_post_is_booked_though_the_worker_calls_reconcile_not_reconcile_discord(self):
        """Found on the first hosted run of the lane with booking: 1,559 read-backs, none booked. PacedSocial wrapped only
        reconcile_discord; the worker calls `reconcile`, which PacedSocial forwarded, and HostedSocial.reconcile calls its own
        reconcile_discord, so the wrapper and its context were never entered."""
        seen = Seen()
        lane.PacedSocial(seen).reconcile({'platform': 'Discord'}, {'providerReference': 'channel/message'})
        self.assertEqual(seen.calls, [('reconcile', 1.0)])
        self.assertEqual(seen.aside, [('reconcile', 0.0)], 'on this thread only')

    def test_a_second_thread_never_sees_the_context(self):
        seen = Seen()
        lane.PacedSocial(seen).prepare_discord_dispatch({})
        self.assertEqual(seen.aside, [('prepare', 0.0)])

    def test_a_direct_provider_call_and_a_web_request_get_the_immediate_answer(self):
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', production_reviewed=True)
        self.assertEqual(provider._book_ahead(), {})
        self.assertEqual(provider._book_ahead(.7), {})
        with rate_limits.booking(1.0):
            self.assertEqual(provider._book_ahead(), {'book_ahead': 1.0})
            self.assertEqual(provider._book_ahead(.3), {'book_ahead': .3}, 'within the wait a call has left')
            self.assertEqual(provider._book_ahead(.003), {}, 'a wait that short is not a booking')
            self.assertEqual(provider._book_ahead(-1), {})
        self.assertEqual(provider._book_ahead(), {})

    def test_the_minute_worker_s_social_is_never_wrapped(self):
        """The frozen minute path builds no PacedSocial: its calls reach HostedSocial as they always did."""
        social = Seen()
        PostgresWorker(lambda: None, social=social, worker_id='minute', discord_workers=True)
        self.assertNotIsInstance(social, lane.PacedSocial)
        social.prepare_discord_dispatch({})
        self.assertEqual(social.calls, [('prepare', 0.0)])

    def test_the_lane_s_tally_counts_its_own_bookings(self):
        paced = lane.PacedSocial(Seen())
        self.assertEqual(paced.booked, {'bookings': 0, 'bookedWaitSeconds': 0.0})
        limiter = SharedPostgresBudget(MemoryLedger(now=T0).connection, APP, policy=policy(3, 1))
        with rate_limits.booking(1.0, paced.booked):
            limiter._count_booking(bookings=1, bookedWaitSeconds=.25)
        limiter._count_booking(bookings=1, bookedWaitSeconds=.5)
        self.assertEqual(paced.booked, {'bookings': 1, 'bookedWaitSeconds': .25})

    def test_booking_is_one_second_ahead_and_the_shard_count_is_unchanged(self):
        self.assertEqual(lane.BOOK_AHEAD_SECONDS, 1.0)
        self.assertEqual(lane.SHARDS, 12, 'raised only after the booked horizon is re-measured at more loops (AMPLIFICATION.md)')


class BookingStep(FakeLane):
    """A lane whose step reserves through the real PacedSocial, over a social that books on a real coordinator (MemoryLedger)
    whose clock the lane's fake clock drives, so that a booking's wait is the loop's time."""
    def __init__(self, pass_reads=6, fill=True, **kw):
        super().__init__(**kw)
        self.ledger = MemoryLedger(now=T0)
        self.limiter = SharedPostgresBudget(self.ledger.connection, APP, policy=policy(3, 1), sleep=self.sleep_both,
                                            monotonic=self.monotonic)
        self.identity = RequestIdentity.make(APP, 'bot', 'lane-booking-bot')
        self.pass_reads, self.serial = pass_reads, 0
        for offset in ((0, .3, .6) if fill else ()):    # a full window at the start
            self.ledger.now = T0 + offset
            self.read()
        self.ledger.now = T0 + .1                        # the oldest wire leaves in .9 s: a booking is possible
        self.now = 0.0

    def sleep_both(self, seconds):
        self.now += seconds
        self.ledger.now += seconds

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.sleep_both(seconds)

    def read(self):
        self.serial += 1
        permit = self.limiter.reserve_read('GET', '/guilds/%d' % (700000000000000000 + self.serial), identity=self.identity,
                                           book_ahead=rate_limits.current_book_ahead())
        self.limiter.observe(permit, OK)
        self.ledger.states = {k: v for k, v in self.ledger.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
        self.ledger.maps = {}

    def step(self, worker, **kw):
        self.started.append(self.now)
        worker.social.prepare_discord_dispatch({'reads': self.pass_reads})
        worker.discord_stats['claims'] += 1
        return True

    def run(self, values=None, prepare=None, **kw):
        social = SimpleNamespace(providers={}, prepare_discord_dispatch=prepare or (
            lambda manifest, **kw: [self.read() for _ in range(manifest['reads'])]))
        base = PostgresWorker(lambda: None, social=social, worker_id='fake', discord_workers=True)
        with self.patched():
            return lane.run(base, 2, {**ON, **(values or {})}, started=0.0, sleep=self.sleep, monotonic=self.monotonic,
                            rng=SimpleNamespace(random=lambda: 0.0), **kw)


def exact_arithmetic(case):
    """No headroom and no reserve: the plain window of the arithmetic tests (the booked horizon is what these tests are about)."""
    for name, value in (('SLOT_GUARD_SECONDS', 0.0), ('IMMEDIATE_RESERVE', 0)):
        patcher = patch.object(SharedPostgresBudget, name, value)
        patcher.start()
        case.addCleanup(patcher.stop)


class TheLoopWithBlockingReservations(unittest.TestCase):
    def setUp(self):
        exact_arithmetic(self)

    def test_a_coordinator_that_blocks_a_second_per_reservation_still_ends_the_invocation_inside_budget_plus_one_step(self):
        fake = BookingStep(fill=False)
        result = fake.run({lane.ENV_SECONDS: '50'}, prepare=lambda manifest, **kw: [fake.sleep_both(1.0) for _ in range(6)])
        self.assertEqual(result['stoppedBy'], 'time_budget')
        self.assertTrue(all(at < 50 for at in fake.started), 'no step starts after the budget')
        self.assertEqual([round(b - a) for a, b in zip(fake.started, fake.started[1:])], [6] * (len(fake.started) - 1),
                         'a pass takes six seconds')
        self.assertLessEqual(result['elapsedSeconds'], 50 + 6, 'and the last one ended within one step of the budget')

    def test_a_pass_of_booked_reads_at_a_full_window_takes_the_time_of_its_slots_and_the_loop_still_ends_on_time(self):
        fake = BookingStep(pass_reads=6)
        result = fake.run({lane.ENV_SECONDS: '50'})
        self.assertEqual(result['stoppedBy'], 'time_budget')
        self.assertTrue(all(at < 50 for at in fake.started))
        step_seconds = max(b - a for a, b in zip(fake.started, fake.started[1:]))
        self.assertGreaterEqual(step_seconds, 2.0, 'six reads at two bookable slots a second take seconds, slept in the coordinator')
        self.assertLessEqual(result['elapsedSeconds'], 50 + step_seconds + .5)

    def test_the_two_counters_carry_the_lane_s_own_bookings_into_the_result(self):
        fake = BookingStep(pass_reads=3)
        result = fake.run({lane.ENV_SECONDS: '12'})
        counters = result['counters']
        self.assertIn('bookedWaits', lane.COUNTERS)
        self.assertIn('bookedSeconds', lane.COUNTERS)
        self.assertGreater(counters['bookedWaits'], 0)
        self.assertGreater(counters['bookedSeconds'], 0.0)
        self.assertEqual(counters['bookedWaits'], fake.limiter.booking_stats()['bookings'], 'every booking was the lane\'s')
        self.assertAlmostEqual(counters['bookedSeconds'], fake.limiter.booking_stats()['bookedWaitSeconds'], places=2)
        self.assertEqual(counters['rateDelayed'], 0)

    def test_without_a_full_window_nothing_is_counted(self):
        fake = BookingStep(pass_reads=1, fill=False)
        result = fake.run({lane.ENV_STEPS: '1'})
        self.assertEqual((result['counters']['bookedWaits'], result['counters']['bookedSeconds']), (0, 0.0))


class OutlookReadsTheBookedHorizon(unittest.TestCase):
    """lane.outlook waits for the policy row's `reset` while `remaining` is 0. With bookings the coordinator stores, for a window
    that is full but bookable within the horizon, the room the horizon has left and a `reset` that is not ahead: the loop does
    not wait; once the horizon is full, `remaining` is 0 and `reset` is when a booking is possible again."""
    def setUp(self):
        exact_arithmetic(self)
        self.fixture = Outlook('test_it_reads_the_four_application_wide_rows_without_locking')   # its fake cursor and worker
        self.fixture.setUp()
        self.ledger = MemoryLedger(now=T0)
        self.coordinator = SharedPostgresBudget(self.ledger.connection, APP, policy=policy(3, 1),
                                                sleep=lambda s: setattr(self.ledger, 'now', self.ledger.now + s),
                                                monotonic=lambda: self.ledger.now)
        self.identity = RequestIdentity.make(APP, 'bot', 'outlook-bot')
        self.serial = 0

    def book(self, offset):
        self.ledger.now = T0 + offset
        self.serial += 1
        permit = self.coordinator.reserve_read('GET', '/guilds/%d' % (700000000000000000 + self.serial), identity=self.identity,
                                               book_ahead=1.0)
        self.coordinator.observe(permit, OK)
        self.ledger.states = {k: v for k, v in self.ledger.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
        self.ledger.maps = {}

    def outlook(self):
        """What the lane would read: the policy row of the ledger, in the shape of the lane's statement, at ledger time."""
        fixture = self.fixture
        state = self.ledger.states['00:' + self.coordinator.application_key]
        policy_key = fixture.keys()[0]
        fixture.rows = [fixture.row(policy_key, 'policy', remaining=state['left'], reset=fixture.now + (state['reset'] - self.ledger.now))]
        return state, lane.outlook(fixture.worker)

    def test_a_full_but_bookable_window_is_not_a_wait_and_a_full_horizon_is(self):
        for offset in (0, .3, .6):
            self.book(offset)
        self.ledger.now = T0 + .9
        state, found = self.outlook()
        self.assertEqual(state['left'], 2, 'the window holds three wires (the cap) but the horizon of the last admission has room for two')
        self.assertEqual(found, (None, 0.0), 'and a booking is possible now: the loop claims')
        for _ in range(3):
            self.ledger.now = T0 + .9
            self.book(.9)
        self.ledger.now = T0 + .9
        state, (blocker, wait) = self.outlook()
        self.assertEqual(state['left'], 0)
        self.assertIsNone(blocker)
        self.assertGreater(wait, 0.0, 'three more bookings fill the horizon: the loop waits for the next one to be possible')
        self.assertLess(wait, 1.0)


if __name__ == '__main__':
    unittest.main()
