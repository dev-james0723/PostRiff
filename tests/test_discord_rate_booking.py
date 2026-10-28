"""Offline contracts for booking: a caller inside booking() that finds the application window full is given the next exact slot
and waits for it inside reserve, instead of being refused and left to poll (docs/w02/OPEN-QUESTIONS.md, Q19).

What must hold, and is proved here on the shared MemoryLedger double with a fake clock:

  * the slot is where the ceiling stays exact: the earliest instant after every wire already stored at which one more wire
    keeps every window at the cap; a booked wire is a wire like any other (its stored time is where the ceiling counts it);
  * nothing is booked beyond the caller's book-ahead, the permit's own life or the caller's deadline; a caller outside
    booking() keeps the immediate answer, and bookings leave it a slot (IMMEDIATE_RESERVE);
  * a permit still to be used counts in every window for a booking (the one way a later booking could otherwise be wrong);
  * the wait is in reserve, after the commit, never in consume; consume refuses a permit before its slot;
  * a booked read that slept looks once more, just before it is sent, for an embargo, a circuit or a hold that began meanwhile;
  * the stored `remaining` and `reset` keep their meaning for lane.outlook;
  * the randomized lives: ceiling exact over every wire, quotes equal to a brute force, bookings never before `now`.

The real PostgreSQL proof (24 threads, the mock's own trailing second) is test_discord_rate_booking_postgres.py.
No network, no credentials.
"""
import random
import unittest
from unittest.mock import patch

from postriff_phase2.discord import rate_limits
from postriff_phase2.discord.rate_limits import (
    SharedPostgresBudget, RequestIdentity, RateDelayed, Permit, HOLD_WAIT_SECONDS)
from test_discord_rate_ceiling import T0, EPS, OK, busiest_closed_window, policy
from test_discord_rate_limits import MemoryLedger, synthetic_policy, APP

SPAN_EPS = EPS      # span = window + guard + one database tick


class Booked(unittest.TestCase):
    """cap 3, window 1, no guard, no reserve: the arithmetic at its plainest. A caller's sleep moves the process's monotonic clock
    and the database clock together, as time does; a test that wants several callers asking at one database instant sets the
    clock back with at() before each."""
    guard = 0.0
    reserve_slots = 0

    def setUp(self, capacity=3, window=1, **more):
        for name, value in (('SLOT_GUARD_SECONDS', self.guard), ('IMMEDIATE_RESERVE', self.reserve_slots)):
            patcher = patch.object(SharedPostgresBudget, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = MemoryLedger(now=T0)
        self.make(capacity, window, **more)

    def make(self, capacity=3, window=1, **more):
        self.policy = policy(capacity, window, **more)
        self.mono, self.sleeps, self.on_sleep, self.statements = 0.0, [], None, []
        self.s = SharedPostgresBudget(self.db.connection, APP, policy=self.policy, sleep=self.sleep, monotonic=lambda: self.mono)
        self.identity = RequestIdentity.make(APP, 'bot', 'booking-bot')
        self.serial = 0
        original = self.db.execute
        self.db.execute = lambda query, params=(): (self.statements.append(' '.join(query.split())[:140]), original(query, params))[1]

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.mono += seconds
        self.db.now += seconds
        if self.on_sleep:
            self.on_sleep()

    def path(self):
        self.serial += 1
        return '/guilds/%d' % (700000000000000000 + self.serial)

    def forget_routes(self):
        self.db.states = {k: v for k, v in self.db.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
        self.db.maps = {}

    def at(self, offset):
        self.db.now = T0 + offset

    def read(self, ahead=0.0):
        permit = self.s.reserve_read('GET', self.path(), identity=self.identity, book_ahead=ahead)
        self.s.observe(permit, OK)
        self.forget_routes()
        return permit

    def book(self, ahead=1.0, observe=True):
        permit = self.s.reserve_read('GET', self.path(), identity=self.identity, book_ahead=ahead)
        if observe:
            self.s.observe(permit, OK)
        return permit

    def create(self, ahead=0.0, **kw):
        permit = self.s.reserve('GET', self.path(), identity=self.identity, book_ahead=ahead, **kw)
        return permit

    def rows(self):
        return sorted(self.db.admissions.values(), key=lambda r: r['seq'])

    def wires(self):
        return sorted(MemoryLedger.wire_time(r) for r in self.rows())

    def denied(self, how):
        with self.assertRaises(RateDelayed) as caught:
            how()
        return caught.exception

    def fill(self, offsets=(0, .3, .6)):
        for offset in offsets:
            self.at(offset)
            self.read()

    def policy_row(self):
        (row,) = [r for r in self.db.states.values() if r['kind'] == 'policy']
        return row


class Arithmetic(Booked):
    def test_a_full_window_books_the_next_exact_slot_and_returns_when_it_has_come(self):
        self.fill()
        self.at(.9)
        self.book()
        slot = T0 + 1 + SPAN_EPS                       # the oldest wire (T0) leaves its span here
        booked = self.rows()[-1]
        self.assertEqual(booked['state'], 'observed')
        self.assertAlmostEqual(booked['sent'], slot, places=9, msg='stored with the slot as its wire time')
        self.assertAlmostEqual(booked['reserved'], T0 + .9, places=9, msg='reserved when it asked')
        self.assertAlmostEqual(sum(self.sleeps), .1 + SPAN_EPS, places=6, msg='it slept exactly until the slot')
        self.assertAlmostEqual(self.mono, .1 + SPAN_EPS, places=6)
        self.assertEqual(self.s.booking_stats()['bookings'], 1)
        self.assertAlmostEqual(self.s.booking_stats()['bookedWaitSeconds'], .1 + SPAN_EPS, places=6)
        self.assertLessEqual(max(self.sleeps), .1 + 1e-9, 'in slices of a tenth of a second at most')

    def test_a_free_slot_is_used_at_once_and_is_not_a_booking(self):
        self.at(0)
        self.book()
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.s.booking_stats()['bookings'], 0)
        self.assertAlmostEqual(self.rows()[0]['sent'], T0, places=9)

    def test_bookings_follow_each_other_in_the_order_they_asked_and_never_exceed_the_cap_in_any_closed_window(self):
        self.fill()
        self.at(.9)
        slots = []
        for _ in range(3):                              # three callers asking at the same database instant
            self.at(.9)
            self.book()
            slots.append(self.rows()[-1]['sent'])
        self.at(.9)
        self.assertEqual(slots, sorted(slots), 'a later caller never gets an earlier slot than one before it')
        for slot, oldest in zip(slots, (0, .3, .6)):
            self.assertAlmostEqual(slot, T0 + oldest + 1 + SPAN_EPS, places=9, msg='each takes the slot of the next wire to leave')
        error = self.denied(lambda: self.book())          # the fourth would be 1.1 s away: beyond the horizon
        self.assertEqual(error.rate_scope_kind, 'application')
        self.assertLessEqual(busiest_closed_window(self.wires(), 1), 3)
        self.assertEqual(len(self.wires()), 6)

    def test_a_booking_is_never_before_the_caller_asked_nor_before_a_wire_already_stored(self):
        self.fill()
        self.at(.9)
        self.book()
        self.at(.95)                                     # a later caller
        self.book()
        first, second = self.wires()[-2:]
        self.assertLess(first, second)
        self.assertGreaterEqual(first, T0 + .9)
        self.assertGreaterEqual(second, T0 + .95)

    def test_beyond_the_book_ahead_it_is_refused_with_the_wait_until_a_booking_is_possible(self):
        for _ in range(3):
            self.read()                                  # all three at T0: the oldest leaves at T0 + 1 + one tick
        error = self.denied(lambda: self.book())
        self.assertEqual(error.rate_scope_kind, 'application')
        self.assertEqual(error.retry_after_seconds, .001, 'a tick beyond a second ahead: floored to the 1 ms minimum')
        self.assertEqual(len(self.db.admissions), 3, 'a refusal leaves no admission and no debit behind')
        self.assertEqual(self.s.booking_stats()['horizonRefusals'], 1)
        self.at(.01)
        self.book()                                      # now inside the horizon
        self.assertEqual(self.s.booking_stats()['bookings'], 1)

    def test_a_shorter_book_ahead_than_the_wait_is_refused_with_the_difference(self):
        self.fill()
        self.at(.9)
        error = self.denied(lambda: self.book(ahead=.05))
        self.assertAlmostEqual(error.retry_after_seconds, .1 + SPAN_EPS - .05, places=6)

    def test_nothing_is_booked_beyond_the_shipped_maximum_and_a_zero_maximum_restores_the_old_behaviour(self):
        self.fill()
        self.at(.9)
        with patch.object(SharedPostgresBudget, 'BOOK_AHEAD_SECONDS', 0.05):
            error = self.denied(lambda: self.book(ahead=5.0))     # asks for 5 s, may have 0.05
        self.assertAlmostEqual(error.retry_after_seconds, .1 + SPAN_EPS - .05, places=6)
        with patch.object(SharedPostgresBudget, 'BOOK_AHEAD_SECONDS', 0.0):
            error = self.denied(lambda: self.book(ahead=1.0))
        self.assertAlmostEqual(error.retry_after_seconds, .1 + SPAN_EPS, places=6, msg='the plain quote of the old behaviour')
        self.assertEqual(self.sleeps, [])

    def test_a_caller_that_does_not_book_keeps_the_immediate_answer_and_the_exact_quote(self):
        self.fill()
        self.at(.9)
        self.book()                                      # a booking holds the slot at T0 + 1 + one tick
        self.at(.9)
        error = self.denied(lambda: self.read())
        self.assertAlmostEqual(error.retry_after_seconds, .4 + SPAN_EPS, places=6,
                               msg='the earliest instant at which one more wire is exact: when the wire at +.3 leaves (+1.3), '
                                   'the booking at +1.0 and the wire at +.6 being the other two')
        self.db.now = T0 + .9 + error.retry_after_seconds - 1e-7
        self.denied(lambda: self.read())
        self.db.now = T0 + .9 + error.retry_after_seconds + 1e-7
        self.read()
        self.assertLessEqual(busiest_closed_window(self.wires(), 1), 3)

    def test_the_wait_is_in_slices_and_the_clock_it_counts_from_is_the_moment_the_reading_arrived(self):
        self.fill()
        self.at(.9)
        self.db.insert_delay = .02                       # the commit took 20 ms of the 100 ms the slot was away
        original = self.db.admit

        def slow(sql, params):
            original(sql, params)
            self.mono += .02                             # ... on this process's clock too
        self.db.admit = slow
        self.book()
        self.assertAlmostEqual(sum(self.sleeps), .1 + SPAN_EPS - .02, places=6, msg='the time the reservation took is not slept twice')


class StoredRow(Booked):
    """lane.outlook waits until `reset` when `remaining` is 0: the stored values must keep the meaning the lane relies on."""
    def test_a_window_that_is_full_but_bookable_shows_nothing_to_wait_for(self):
        self.fill()
        self.at(.9)
        row = self.policy_row()
        self.assertEqual(row['left'], 2, 'as of the last admission (at .6): its window holds three wires, its horizon has two bookings left')
        self.assertEqual(row['reset'], T0 + .6, 'and a booking is possible: reset is that instant, not ahead')

    def test_remaining_is_the_room_of_the_horizon_and_is_zero_exactly_when_a_booking_is_not_possible(self):
        """Found on the first hosted run: remaining was 0 in 21 of 35 busy readings while a booking was possible at once, because it
        counted only the wires up to now, and a saturated lane always has a full span of them. A reader (an alert, the ops ratio)
        takes 0 for spent: it has to mean that no booking is possible, which is when `reset` lies ahead. Three callers book at
        one instant (.9), each into the horizon that ends at 1.9; the row is as of the last of them."""
        self.fill()
        for room in (2, 1, 0):
            self.at(.9)
            self.book()
            row = self.policy_row()
            self.assertEqual(row['left'], room, 'the horizon has %d booking(s) left' % room)
            self.assertEqual(row['left'] == 0, row['reset'] > T0 + .9, 'remaining is 0 exactly when reset lies ahead')
        self.at(.9)
        self.denied(lambda: self.book())

    def test_a_permit_still_to_be_used_takes_room_in_every_window_as_it_does_for_a_booking(self):
        """The same count as _booking_slot: a create permit reserved long before the horizon's last span can be used at any later
        time, so it takes one booking's room however old it is. Counting it only where it was reserved published 2 here, and the
        second booking at .9 would have been refused."""
        self.at(0)
        self.create()                                      # reserved at 0, never used in this test
        self.at(.3)
        self.read()
        self.at(.9)
        self.read()                                        # an immediate admission; its row is the one read below
        row = self.policy_row()
        self.assertEqual(row['left'], 1, 'cap 3 less the permit less the wire at .9 (the wire at .3 leaves before the horizon ends)')
        self.at(.9)
        self.book()
        self.assertEqual(self.policy_row()['left'], 0, 'one booking was left, and the row says so')
        self.assertGreater(self.policy_row()['reset'], T0 + .9)
        self.at(.9)
        self.denied(lambda: self.book())

    def test_a_booked_horizon_that_is_full_shows_when_a_booking_is_possible_again(self):
        self.fill()
        self.at(.9)
        for _ in range(3):
            self.at(.9)
            self.book()                                  # three bookings: slots at T0+1, 1.3, 1.6 (+ one tick)
        self.at(.9)
        row = self.policy_row()
        self.assertEqual(row['left'], 0)
        self.assertGreater(row['reset'], T0 + .9, 'the horizon is full: wait')
        error = self.denied(lambda: self.book())
        self.assertAlmostEqual(row['reset'], T0 + .9 + error.retry_after_seconds, places=6,
                               msg='reset is exactly when the refused caller would be booked inside the horizon')

    def test_without_booking_the_row_is_what_it_has_always_been(self):
        with patch.object(SharedPostgresBudget, 'BOOK_AHEAD_SECONDS', 0.0):
            for offset in (0, .3, .6):
                self.at(offset)
                self.read()
            row = self.policy_row()
            self.assertEqual(row['left'], 0)
            self.assertAlmostEqual(row['reset'], T0 + 1 + SPAN_EPS, places=9, msg='the oldest wire\'s departure')

    def test_whoever_wrote_last_the_row_means_the_same(self):
        """A web request (no booking) and a booking caller that find a free slot leave the same row for the same ledger."""
        stored = []
        for ahead in (0.0, 1.0):
            self.setUp()
            for offset in (0, .3):
                self.at(offset)
                self.read()
            self.at(.6)
            self.book(ahead=ahead)
            stored.append(dict(self.policy_row()))
        self.assertEqual(stored[0], stored[1])
        self.assertEqual((stored[0]['left'], stored[0]['reset']), (2, T0 + .6))

    def test_the_lane_s_reading_of_the_row_waits_only_while_the_horizon_is_full(self):
        """The rule lane.outlook applies to a capped row: wait (reset - now) when remaining <= 0."""
        def waits(now):
            row = self.policy_row()
            return max(0.0, row['reset'] - now) if row['left'] <= 0 else 0.0
        self.fill()
        self.assertEqual(waits(T0 + .9), 0.0)
        for taken in (1, 2, 3):
            self.at(.9)
            self.book()
            self.assertEqual(waits(T0 + .9) > 0.0, taken == 3, 'only the booking that fills the horizon makes the lane wait')
        self.assertLess(waits(T0 + .9), 1.0)


class WebCallersKeepASlot(Booked):
    reserve_slots = 1

    def test_bookings_fill_all_but_the_reserve_so_a_caller_that_cannot_wait_is_never_locked_out(self):
        for offset in (0, .3):
            self.at(offset)
            self.read(ahead=1.0)                         # the background's two slots of three
        self.at(.9)
        self.book()                                      # the third background request is booked, not given the reserved slot
        self.assertAlmostEqual(self.rows()[-1]['sent'], T0 + 1 + SPAN_EPS, places=9)
        self.at(.9)
        self.read()                                      # the web request: the reserved slot, now, with no sleep at all
        self.assertEqual(len(self.sleeps), 2, 'only the booking slept (in two slices)')
        self.at(.9)
        error = self.denied(lambda: self.read())         # and a second web request is refused with an exact quote
        self.assertEqual(error.rate_scope_kind, 'application')
        self.assertLessEqual(busiest_closed_window(self.wires(), 1), 3)
        self.at(.9)
        for _ in range(2):
            self.denied(lambda: self.book(ahead=.05))    # bookings behind that need more than the horizon are refused
        self.assertLessEqual(busiest_closed_window(self.wires(), 1), 3)

    def test_the_reserve_never_takes_the_last_slot_from_the_background(self):
        self.make(1, 1)
        self.at(0)
        self.book()
        self.assertEqual(len(self.db.admissions), 1, 'a cap of one has no slot to reserve: a booking still works')


class BookedPermits(Booked):
    def test_a_booked_permit_is_reserved_at_its_slot_and_lives_its_full_life_from_there(self):
        self.fill()
        self.at(.9)
        permit = self.create(ahead=1.0, valid_until=T0 + 100)
        row = self.db.admissions[permit.id]
        slot = T0 + 1 + SPAN_EPS
        self.assertEqual(row['state'], 'reserved')
        self.assertAlmostEqual(row['reserved'], slot, places=9)
        self.assertAlmostEqual(permit.expires_at, slot + self.policy['permit_ttl_seconds'], places=5)
        self.assertAlmostEqual(self.mono, .1 + SPAN_EPS, places=6, msg='returned when the slot had come')
        self.db.now = slot + .05
        self.s.consume(permit, 'GET', None or self.path_of(permit))

    def path_of(self, permit):
        # the permit knows its path only as a digest: use the last path issued (the reservation just made)
        return '/guilds/%d' % (700000000000000000 + self.serial)

    def test_consume_refuses_a_permit_before_its_slot(self):
        self.fill()
        self.at(.9)
        impatient = SharedPostgresBudget(self.db.connection, APP, policy=self.policy, sleep=lambda s: None, monotonic=lambda: 0.0)
        permit = impatient.reserve('GET', self.path(), identity=self.identity, book_ahead=1.0)   # returned without waiting
        error = self.denied(lambda: impatient.consume(permit, 'GET', '/guilds/%d' % (700000000000000000 + self.serial)))
        self.assertEqual((error.rate_cause, error.rate_scope_kind), ('permit_early', 'permit'))
        self.assertAlmostEqual(error.retry_after_seconds, .1 + SPAN_EPS, places=6)
        self.assertEqual(self.db.admissions[permit.id]['state'], 'reserved', 'still unused and still its slot')
        self.db.now = T0 + 1 + SPAN_EPS + 1e-6
        impatient.consume(permit, 'GET', '/guilds/%d' % (700000000000000000 + self.serial))
        self.assertEqual(self.db.admissions[permit.id]['state'], 'sent')

    def test_no_sleep_happens_in_consume_or_seal(self):
        self.fill()
        self.at(.9)
        permit = self.create(ahead=1.0)
        before = len(self.sleeps)
        self.s.consume(permit, 'GET', self.path_of(permit))
        self.assertEqual(len(self.sleeps), before)

    def test_a_booking_is_refused_when_the_permit_would_not_live_to_be_used(self):
        self.fill()
        self.at(.9)
        slot = 1 + SPAN_EPS
        short = SharedPostgresBudget(self.db.connection, APP, policy={**self.policy, 'permit_ttl_seconds': .05},
                                     sleep=self.sleep, monotonic=lambda: self.mono)
        error = self.denied(lambda: short.reserve('GET', self.path(), identity=self.identity, book_ahead=1.0))
        self.assertEqual(error.rate_scope_kind, 'application', 'a permit shorter than its seal and consume cannot be booked')
        for valid_until, booked in ((T0 + slot + 1.9, False), (T0 + slot + 2.0 + 1e-3, True), (T0 + .95, False)):
            with self.subTest(valid_until=valid_until - T0):
                call = lambda: self.create(ahead=1.0, valid_until=valid_until)   # noqa: E731
                if booked:
                    call()
                else:
                    self.denied(call)
        expiring = SharedPostgresBudget(self.db.connection, APP, policy={**self.policy, 'expires_at': T0 + slot + 1.0},
                                        sleep=self.sleep, monotonic=lambda: self.mono)
        self.denied(lambda: expiring.reserve('GET', self.path(), identity=self.identity, book_ahead=1.0))

    def test_the_wait_stops_at_the_caller_s_deadline_whatever_was_booked(self):
        """A booking is only made while the slot and the permit's life fit before the caller's deadline, so the deadline can
        fall inside the sleep only if this process stalled (or a clock moved): then the sleep ends at the deadline, the permit
        is left to expire unused and the caller is told so."""
        self.fill()
        self.at(.9)
        slot = 1 + SPAN_EPS
        stall = {'done': False}

        def stalling_sleep(seconds):
            self.sleeps.append(seconds)
            self.mono += seconds + (5.0 if not stall['done'] else 0.0)   # the process was frozen for five seconds
            stall['done'] = True
        waiting = SharedPostgresBudget(self.db.connection, APP, policy=self.policy, sleep=stalling_sleep, monotonic=lambda: self.mono)
        with self.assertRaises(RateDelayed) as caught:
            waiting.reserve('GET', self.path(), identity=self.identity, book_ahead=1.0, valid_until=T0 + slot + self.policy['permit_ttl_seconds'] + .05)
        self.assertEqual((caught.exception.rate_cause, caught.exception.rate_scope_kind), ('permit_expired', 'permit'))
        self.assertEqual(len(self.sleeps), 1, 'it did not go on sleeping to a slot past its deadline')
        permit_row = [r for r in self.rows() if r['state'] == 'reserved'][-1]
        self.assertAlmostEqual(permit_row['reserved'], T0 + slot, places=6, msg='the permit is left to expire on its own')

    def test_an_immediate_permit_is_unchanged_by_all_this(self):
        self.at(0)
        permit = self.create(valid_until=T0 + .5)
        self.assertAlmostEqual(permit.expires_at, T0 + .5, places=6, msg='cut by the caller deadline, as before')
        self.assertAlmostEqual(self.db.admissions[permit.id]['reserved'], T0, places=9)

    def test_a_permit_still_to_be_used_counts_in_every_window_for_a_booking(self):
        """Without this a booking could be exact when made and wrong once the permit is used: P is reserved at T0, bookings
        made while it is young would land more than a span later and not count it, and using P at T0 + 1.15 would put four
        wires in one closed second (the naive rule fails exactly this scenario)."""
        self.at(0)
        permit = self.create()                           # P, unused, wire T0
        for offset in (.1, .2):
            self.at(offset)
            self.read()
        self.at(.3)
        self.book()
        self.at(.3)
        self.book()
        slots = sorted(r['sent'] for r in self.rows() if r['state'] == 'observed' and r['sent'] > T0 + 1)
        self.assertAlmostEqual(slots[0], T0 + .1 + 1 + SPAN_EPS, places=9, msg='after .1, the oldest read, not after the permit')
        self.assertAlmostEqual(slots[1], T0 + .2 + 1 + SPAN_EPS, places=9)
        self.db.now = T0 + 1.15
        self.s.consume(permit, 'GET', '/guilds/%d' % (700000000000000000 + 1))
        self.assertLessEqual(busiest_closed_window(self.wires(), 1), 3)
        self.assertEqual(len(self.wires()), 5)


class TheGate(Booked):
    def embargo(self, kind, **change):
        for row in self.db.states.values():
            if row['kind'] == kind:
                row.update(change)

    def test_a_booked_read_that_wakes_into_a_global_embargo_is_not_sent(self):
        self.fill()
        self.at(.9)
        self.on_sleep = lambda: self.embargo('global', blocked=T0 + 5)
        error = self.denied(lambda: self.book(observe=False))
        self.assertEqual((error.rate_cause, error.rate_scope_kind), ('embargo', 'embargo'))
        self.assertAlmostEqual(error.retry_after_seconds, 5 - 1 - SPAN_EPS, places=5, msg='what is left of the embargo')
        self.assertEqual(self.rows()[-1]['state'], 'blocked', 'closed unsent; the slot stays spent')
        self.assertEqual(self.s.booking_stats()['gateStops'], 1)

    def test_a_hold_that_begins_during_the_wait_stops_it_with_the_hold_wait(self):
        self.fill()
        self.at(.9)
        self.on_sleep = lambda: self.embargo('policy', hold=True)
        error = self.denied(lambda: self.book(observe=False))
        self.assertEqual((error.rate_cause, error.rate_scope_kind, error.retry_after_seconds), ('hold', 'embargo', HOLD_WAIT_SECONDS))
        self.assertEqual(self.rows()[-1]['state'], 'blocked')

    def test_a_circuit_that_opens_on_the_route_during_the_wait_stops_it(self):
        self.fill()
        self.at(.9)
        self.on_sleep = lambda: self.embargo('route', circuit=T0 + 30)
        error = self.denied(lambda: self.book(observe=False))
        self.assertEqual(error.rate_cause, 'embargo')
        self.assertEqual(self.rows()[-1]['state'], 'blocked')

    def test_without_anything_new_the_read_goes_on_and_stays_sent(self):
        self.fill()
        self.at(.9)
        permit = self.book(observe=False)
        self.assertEqual(self.db.admissions[permit.id]['state'], 'sent')
        self.assertTrue(any('SET state=\'blocked\'' in sql for sql in self.statements), 'the gate looked')
        self.assertEqual(self.s.booking_stats()['gateStops'], 0)

    def test_a_wait_shorter_than_the_gate_threshold_does_not_look(self):
        self.fill((0, .3, .6))
        self.at(.99)                                      # the slot is .01 s away
        self.statements.clear()
        self.book(observe=False)
        self.assertFalse(any('SET state=\'blocked\'' in sql for sql in self.statements))

    def test_a_create_permit_is_not_gated_here_its_seal_and_consume_are_the_check(self):
        self.fill()
        self.at(.9)
        self.on_sleep = lambda: self.embargo('global', blocked=T0 + 5)
        permit = self.create(ahead=1.0)
        self.assertEqual(self.db.admissions[permit.id]['state'], 'reserved')

    def test_a_hold_before_the_booking_is_the_old_hold_wait_and_books_nothing(self):
        self.fill()
        self.at(.9)
        self.embargo('policy', hold=True)
        error = self.denied(lambda: self.book())
        self.assertEqual((error.rate_cause, error.retry_after_seconds), ('hold', HOLD_WAIT_SECONDS))
        self.assertEqual(self.sleeps, [])


class CrashDuringTheWait(Booked):
    def test_a_booked_read_whose_process_dies_keeps_its_slot_for_its_span_and_is_never_sent(self):
        self.fill()
        self.at(.9)

        def die():
            raise KeyboardInterrupt()
        self.on_sleep = die
        with self.assertRaises(KeyboardInterrupt):
            self.book(observe=False)
        self.on_sleep = None
        dead = self.rows()[-1]
        self.assertEqual(dead['state'], 'sent', 'an admission with no wire request: harmless, and it holds its slot')
        self.assertAlmostEqual(dead['sent'], T0 + 1 + SPAN_EPS, places=9)
        self.book()                                       # the next caller is placed after it, not on top of it
        later = self.rows()[-1]
        self.assertGreaterEqual(later['sent'], dead['sent'])
        self.assertLessEqual(busiest_closed_window(self.wires(), 1), 3)
        self.at(2.5)
        self.assertEqual(self.free(), 2, 'after its span it is still held: nothing says it did not reach Discord')
        self.at(1 + 1 + 30 + 1)                          # window + the unanswered-request margin
        self.assertEqual(self.free(), 3, 'and after the margin it is free again, as any unanswered request')

    def free(self):
        count = 0
        while count < 50:
            try:
                self.read()
            except RateDelayed:
                break
            count += 1
        return count


class ShippedConstants(unittest.TestCase):
    def test_the_booking_numbers_are_the_reviewed_ones(self):
        self.assertEqual(rate_limits.BOOK_AHEAD_SECONDS, 1.0)
        self.assertEqual(SharedPostgresBudget.BOOK_AHEAD_SECONDS, 1.0)
        self.assertEqual(SharedPostgresBudget.IMMEDIATE_RESERVE, 1)
        self.assertEqual(SharedPostgresBudget.BOOK_MIN_LIFE_SECONDS, 0.5)
        self.assertEqual(SharedPostgresBudget.BOOK_GATE_MIN_SECONDS, 0.025)

    def test_nothing_books_outside_the_context_and_it_cannot_exceed_the_maximum(self):
        self.assertEqual(rate_limits.current_book_ahead(), 0.0)
        with rate_limits.booking(5.0):
            self.assertEqual(rate_limits.current_book_ahead(), 1.0)
            with rate_limits.booking(.25):
                self.assertEqual(rate_limits.current_book_ahead(), .25)
            self.assertEqual(rate_limits.current_book_ahead(), 1.0)
        self.assertEqual(rate_limits.current_book_ahead(), 0.0)
        with rate_limits.booking(-3):
            self.assertEqual(rate_limits.current_book_ahead(), 0.0)

    def test_the_tally_counts_this_context_s_bookings_only(self):
        tally = {'bookings': 0, 'bookedWaitSeconds': 0.0}
        limiter = SharedPostgresBudget(MemoryLedger(now=T0).connection, APP, policy=policy(3, 1))
        with rate_limits.booking(1.0, tally):
            limiter._count_booking(bookings=1, bookedWaitSeconds=.4)
        limiter._count_booking(bookings=1, bookedWaitSeconds=.2)
        self.assertEqual(tally, {'bookings': 1, 'bookedWaitSeconds': .4})
        self.assertEqual(limiter.booking_stats()['bookings'], 2)


class Shape(Booked):
    def test_a_booking_costs_the_statements_of_an_immediate_admission_under_the_lock(self):
        self.at(0)
        self.read()
        immediate = [kind for kind, _ in self.db.scope_calls]
        self.db.scope_calls.clear()
        self.fill((.1, .2))
        self.db.scope_calls.clear()
        self.at(.9)
        self.book()
        self.assertEqual([kind for kind, _ in self.db.scope_calls][:3], ['seed', 'lock', 'store'], immediate)


class Lives(unittest.TestCase):
    """Random lives: web reads, booked reads, booked creates used at a random later time, time moving forward in small and
    large steps. After every step the ceiling holds over every stored wire time, and every refusal's quote is the earliest
    instant a brute force finds."""
    SEEDS = tuple(range(1, 33))
    STEPS = 300      # the first life that breaks the ceiling when a permit still to be used is counted as an ordinary wire is seed 15

    def span(self, window, guard):
        return window + min(guard, window / 10) + EPS

    def brute_earliest(self, wires, now, span, slots):
        """The first candidate instant at which every half-open span that holds the new wire, with it, holds <= slots wires.
        (Spans that do not hold it are not its concern: held permits can already make a span busier than `slots`.)"""
        for t in sorted({now} | {w + span for w in wires if w + span > now}):
            alls = sorted(wires + [t])
            if all(sum(1 for w in alls if a <= w < a + span) <= slots for a in alls if a <= t < a + span):
                return t
        return now

    def check_row(self, db, probe, identity, now, where):
        """The application row has just been written, at `now`: it must say what a booking of the whole horizon would find. The
        decision is tried on the ledger as it stands, with a probe of the same policy, and rolled back."""
        (row,) = [dict(r) for r in db.states.values() if r['kind'] == 'policy']   # a copy: the probe changes the ledger's own dicts

        class Rollback(Exception):
            pass
        try:
            with db.connection():
                probe.reserve_read('GET', '/guilds/999999999999999999', identity=identity, book_ahead=SharedPostgresBudget.BOOK_AHEAD_SECONDS)
                raise Rollback()
        except Rollback:
            possible = True
        except RateDelayed:
            possible = False
        self.assertEqual(row['left'] > 0, possible, where + ': remaining is above 0 exactly when a booking of the horizon is possible')
        if row['left'] > 0:
            self.assertLessEqual(row['reset'], now, where + ': and then nothing is ahead')
        else:
            self.assertGreaterEqual(row['reset'], now - 1e-6, where + ': and then reset is when it is')
        return possible

    def run_seed(self, seed):
        rng = random.Random(seed)
        capacity, window = rng.choice((2, 3, 5, 8)), rng.choice((1, 1, .5, 2))
        guard = rng.choice((0.0, .05, .05, .1, .2))      # none, the production headroom (D-16), the one it replaced, and a wide one
        reserve = rng.choice((0, 1, 1))
        with patch.object(SharedPostgresBudget, 'SLOT_GUARD_SECONDS', guard), patch.object(SharedPostgresBudget, 'IMMEDIATE_RESERVE', reserve):
            db = MemoryLedger(now=T0)
            mono = [0.0]

            def sleep(seconds):
                mono[0] += seconds
            limiter = SharedPostgresBudget(db.connection, APP, policy=policy(capacity, window), sleep=sleep, monotonic=lambda: mono[0])
            identity = RequestIdentity.make(APP, 'bot', 'lives-bot')
            probe = SharedPostgresBudget(db.connection, APP, policy=policy(capacity, window), sleep=lambda seconds: None, monotonic=lambda: 0.0)
            probed = [0, 0]
            span = self.span(window, guard)
            permits, serial, booked, refused = [], 0, 0, 0
            for step in range(self.STEPS):
                where = 'seed %d step %d' % (seed, step)
                db.now += rng.choice((0, 1e-6, .01, .05, .1, window / 3, window, span, 2 * window)) if rng.random() < .8 else rng.uniform(0, window)
                db.states = {k: v for k, v in db.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
                db.maps = {}
                # answered requests older than anything a window or a held count can see only slow the double down (it copies itself)
                db.admissions = {k: r for k, r in db.admissions.items()
                                 if r['state'] not in ('observed', 'blocked') or MemoryLedger.wire_time(r) > db.now - 5 * span - 2}
                serial += 1
                path = '/guilds/%d' % (710000000000000000 + serial)
                before = sorted(MemoryLedger.wire_time(r) for r in db.admissions.values())
                roll = rng.random()
                now = db.now
                admitted = False
                if roll < .3:    # a web read: immediate or refused with an exact quote
                    try:
                        permit = limiter.reserve_read('GET', path, identity=identity)
                        limiter.observe(permit, OK)
                        self.assertFalse(limiter.booking_stats()['bookings'] > booked, where)
                        admitted = True
                    except RateDelayed as error:
                        refused += 1
                        held = sum(1 for r in db.admissions.values() if MemoryLedger.wire_time(r) <= now - span and (
                            r['state'] in ('reserved', 'sealed') and r['expires'] > now
                            or r['state'] in ('sent', 'uncertain') and MemoryLedger.wire_time(r) > now - window - 30.0))
                        slots = capacity - held
                        if error.rate_scope_kind == 'application' and slots > 0 and not any(w > now + 1.05 for w in before):
                            wires = [w for w in before if w > now - span]
                            self.assertAlmostEqual(now + error.retry_after_seconds, max(self.brute_earliest(wires, now, span, slots), now + .001),
                                                   places=6, msg=where + ' quote')
                elif roll < .7:  # a booked read
                    try:
                        permit = limiter.reserve_read('GET', path, identity=identity, book_ahead=rng.choice((.25, .5, 1.0)))
                        limiter.observe(permit, OK)
                        admitted = True
                    except RateDelayed:
                        refused += 1
                else:            # a booked create, used later or abandoned
                    try:
                        permit = limiter.reserve('GET', path, identity=identity, book_ahead=1.0, valid_until=now + rng.choice((3, 30, 300)))
                        permits.append((permit, path))
                        admitted = True
                    except RateDelayed:
                        refused += 1
                if admitted:   # the row was written just now, at `now`
                    probed[self.check_row(db, probe, identity, now, where)] += 1
                after = sorted(MemoryLedger.wire_time(r) for r in db.admissions.values())
                new = [w for w in after if w not in before]
                for w in new:
                    self.assertGreaterEqual(w, now - 1e-6, where + ': a wire time is never before the moment it was asked for')
                booked = limiter.booking_stats()['bookings']
                if permits and rng.random() < .35:   # use a permit: at its slot or later, while it lives
                    permit, ppath = permits.pop(rng.randrange(len(permits)))
                    row = db.admissions[permit.id]
                    use_at = max(db.now, row['reserved'])
                    if use_at < permit.expires_at - 1e-3 and row['state'] == 'reserved':
                        db.now = use_at
                        try:
                            limiter.consume(permit, 'GET', ppath)
                        except RateDelayed:
                            pass
                wires = sorted(w for w in (MemoryLedger.wire_time(r) for r in db.admissions.values()) if w > db.now - 4 * span - 3)
                self.assertLessEqual(busiest_closed_window(wires, window), capacity, where + ': the ceiling over every wire')
                self.assertLessEqual(max((sum(1 for w in wires if a <= w < a + span - EPS) for a in wires), default=0), capacity,
                                     where + ': and the same in every span (window and headroom), which is what the guard rests on')
        return booked, refused, probed

    def test_the_ceiling_and_the_quotes_hold_over_random_lives(self):
        total_booked = total_refused = 0
        full = open_ = 0
        for seed in self.SEEDS:
            booked, refused, (closed, opened) = self.run_seed(seed)
            total_booked += booked
            total_refused += refused
            full += closed
            open_ += opened
        self.assertGreater(total_booked, 50, 'the lives were busy enough to book')
        self.assertGreater(total_refused, 50, 'and to refuse')
        self.assertGreater(full, 50, 'and the stored row was checked against a booking that was refused as well as against one that was not')
        self.assertGreater(open_, 50)


if __name__ == '__main__':
    unittest.main()
