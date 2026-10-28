"""Offline contracts for the exact application-wide ceiling and the bounded retention of unanswered requests.

The ceiling: in ANY interval of one window of the database clock the coordinator grants at most `app_capacity`
admissions across every credential, reserve and reserve_read alike. A slot frees strictly more than one window after
the admission that held it, so a CLOSED interval of exactly one window never holds more than the cap.

The retention: a request whose answer was never observed (sent, or uncertain after a transport failure) keeps one slot
only while it can still reach Discord, its scope's window plus UNOBSERVED_MARGIN_SECONDS. It used to keep it forever.

Storage is the shared MemoryLedger double, so these prove the arithmetic and the lifecycle, not SQL or locks; the real
PostgreSQL proof is test_discord_rate_ceiling_postgres.py. No network, no credentials, a fake database clock.
"""
import copy
import heapq
import random
import unittest
from unittest.mock import patch

from postriff_phase2.discord.rate_limits import (
    SharedPostgresBudget, RequestIdentity, RateDelayed, RateCoordinatorUnavailable, Permit)
from test_discord_rate_limits import MemoryLedger, synthetic_policy, APP, A, B

T0 = 1000
EPS = 1e-6      # one tick of the database clock: the margin by which a slot frees AFTER a whole window
# Written out here, not read from the implementation, so a change of the margin must change this file too.
MARGIN = 30.0
GUARD = .05     # the production headroom between a slot's window and its freeing (SLOT_GUARD_SECONDS), written out here (the owner's D-16: 0.05 s, was 0.1 s)
OK = {'status': 200, 'headers': {}}


def policy(capacity=3, window=1, **more):
    return {**synthetic_policy(), 'app_capacity': capacity, 'app_window_seconds': window, **more}


def busiest_closed_window(stamps, window):
    """The most admissions in any CLOSED interval of `window` seconds (both ends included)."""
    stamps, best, low = sorted(stamps), 0, 0
    for high, stamp in enumerate(stamps):
        while stamp - stamps[low] > window:
            low += 1
        best = max(best, high - low + 1)
    return best


class Base(unittest.TestCase):
    guard = 0.0   # the arithmetic is shown at the exact window; DefaultHeadroom runs with the production headroom

    def setUp(self, capacity=3, window=1, **more):
        patcher = patch.object(SharedPostgresBudget, 'SLOT_GUARD_SECONDS', self.guard, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = MemoryLedger(now=T0)
        self.make(capacity, window, **more)

    def make(self, capacity=3, window=1, **more):
        self.policy = policy(capacity, window, **more)
        self.s = SharedPostgresBudget(self.db.connection, APP, policy=self.policy)
        self.identity = RequestIdentity.make(APP, 'bot', 'ceiling-bot')
        self.serial = 0

    def path(self):
        """A different cold resource every time, so only the application budget can bind."""
        self.serial += 1
        return '/guilds/%d' % (700000000000000000 + self.serial)

    def forget_routes(self):
        """Every cold resource here is used once, so its route rows can never matter again. Dropping them keeps the
        double (which copies itself for every transaction) small; the application, credential and invalid rows stay."""
        self.db.states = {k: v for k, v in self.db.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
        self.db.maps = {}

    def read(self, limiter=None, answered=True):
        """A GET admitted and, like a real caller's, answered at once. answered=False leaves it sent and unobserved."""
        limiter = limiter or self.s
        permit = limiter.reserve_read('GET', self.path(), identity=self.identity)
        if answered:
            limiter.observe(permit, OK)
        self.forget_routes()
        return permit

    def create(self):
        permit = self.s.reserve('GET', self.path(), identity=self.identity)
        self.forget_routes()
        return permit

    def denied(self, how=None):
        with self.assertRaises(RateDelayed) as caught:
            (how or self.read)()
        return caught.exception

    def stamps(self):
        return sorted(row['reserved'] for row in self.db.admissions.values())

    def at(self, offset):
        self.db.now = T0 + offset

    def policy_row(self):
        rows = [row for row in self.db.states.values() if row['kind'] == 'policy']
        self.assertEqual(len(rows), 1)
        return rows[0]

    def free_slots(self):
        """How many reservations the coordinator would grant in a row right now. The ledger is restored afterwards."""
        snapshot = copy.deepcopy((self.db.states, self.db.maps, self.db.admissions))
        granted = 0
        try:
            while granted < 10000:
                self.read(answered=False)
                granted += 1
        except RateDelayed:
            pass
        finally:
            self.db.states, self.db.maps, self.db.admissions = snapshot
        return granted


class ExactCeilingArithmetic(Base):
    def test_a_burst_of_cap_then_one_more_waits_exactly_one_window(self):
        for _ in range(3):
            self.read()
        error = self.denied()
        self.assertEqual(error.rate_scope_kind, 'application')
        self.assertAlmostEqual(error.retry_after_seconds, 1 + EPS, places=9)
        self.assertEqual(len(self.db.admissions), 3, 'a denial leaves no admission and no debit behind')

    def test_the_wait_is_exactly_the_time_until_the_next_admission_works(self):
        for offset in (0, .1, .2):
            self.at(offset)
            self.read()
        for step in range(6):
            error = self.denied()
            start = self.db.now
            self.db.now = start + error.retry_after_seconds - 1e-7   # a tenth of a tick early: still refused
            self.denied()
            self.db.now = start + error.retry_after_seconds + 1e-7   # a tenth of a tick late: admitted
            self.read()
            self.assertEqual(len(self.stamps()), 4 + step)
            self.assertLessEqual(busiest_closed_window(self.stamps(), 1), 3)
        self.assertGreater(self.db.now, T0 + 2, 'six admissions after the first three took two windows, not one')

    def test_a_slot_frees_strictly_after_one_window_not_at_it(self):
        for _ in range(3):
            self.read()
        self.at(1.0)  # exactly one window later: the closed interval [T0, T0+1] would hold four
        self.assertEqual(self.denied().retry_after_seconds, .001, 'a remainder of one tick is floored to the 1 ms minimum')
        self.at(1 + .5e-6)  # half a tick past it is still inside the same database microsecond
        self.denied()
        self.at(1 + 2e-6)  # a whole tick past it: free
        self.read()
        self.assertLessEqual(busiest_closed_window(self.stamps(), 1), 3)

    def test_staggered_admissions_free_one_slot_at_a_time(self):
        for offset in (0, .3, .6):
            self.at(offset)
            self.read()
        self.at(.9)
        self.assertAlmostEqual(self.denied().retry_after_seconds, .1 + EPS, places=9)
        self.at(1 + 2e-6)  # only the admission at +0 is more than a window old
        self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, .3 + EPS - 2e-6, places=9)
        self.at(1.3 + 2e-6)
        self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, .3 + EPS - 2e-6, places=9)
        self.assertEqual(len(self.stamps()), 5)
        self.assertLessEqual(busiest_closed_window(self.stamps(), 1), 3)

    def test_the_boundary_between_two_fixed_windows_no_longer_doubles_the_ceiling(self):
        """The fixed window refilled every slot when it ended: nine admissions late in one window and ten right after
        it put 19 of a cap of ten into one trailing second. That is the burst that must not be granted any more."""
        self.make(10, 1)
        self.read()                                   # starts the window the fixed scheme would have used
        self.at(.9)
        for _ in range(9):
            self.read()                               # nine more, late in that window: ten in all
        self.at(1.0 + 2e-6)                           # the fixed window refilled here
        granted = 0
        for _ in range(10):
            try:
                self.read()
                granted += 1
            except RateDelayed:
                pass
        self.assertEqual(granted, 1, 'only the first admission is a window old: one slot has freed')
        self.assertLessEqual(busiest_closed_window(self.stamps(), 1), 10)

    def test_a_quiet_period_gives_the_whole_cap_back(self):
        for _ in range(3):
            self.read()
        self.denied()
        self.at(60)
        for _ in range(3):
            self.read()
        self.denied()
        self.assertEqual(busiest_closed_window(self.stamps(), 1), 3)

    def test_reads_creates_and_credentials_share_one_ceiling(self):
        self.read()
        self.create()
        other = RequestIdentity.make(APP, 'user', 'someone-else', A)
        self.s.reserve_read('GET', self.path(), identity=other)
        hook = RequestIdentity.make(APP, 'webhook', 'a-webhook-token')
        error = self.denied(lambda: self.s.reserve('GET', self.path(), identity=hook))
        self.assertEqual(error.rate_scope_kind, 'application')

    def test_two_applications_do_not_share_a_ceiling(self):
        for _ in range(3):
            self.read()
        second = SharedPostgresBudget(self.db.connection, '987654321098765432', policy=self.policy)
        identity = RequestIdentity.make('987654321098765432', 'bot', 'ceiling-bot-2')
        for _ in range(3):
            second.reserve_read('GET', self.path(), identity=identity)

    def test_a_window_other_than_one_second_uses_its_own_length(self):
        self.make(2, .25)
        self.read()
        self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, .25 + EPS, places=9)
        self.at(.25 + 2e-6)
        self.read()

    def test_a_cap_of_one_admits_one_per_window(self):
        self.make(1, 1)
        self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, 1 + EPS, places=9)
        self.at(1 + 2e-6)
        self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, 1 + EPS, places=9)

    def test_a_database_clock_behind_an_admission_it_already_stamped_cannot_double_the_ceiling(self):
        self.at(5)
        for _ in range(2):
            self.read()
        self.at(3)  # the clock stepped back two seconds: the two stamped at 5 are still in force, in the future
        self.read()
        error = self.denied()
        self.assertAlmostEqual(error.retry_after_seconds, 1 + EPS, places=9, msg='the oldest of the three goes first')
        self.at(4 + 2e-6)
        self.read()
        self.at(5 + 4e-6)
        self.read()
        self.assertLessEqual(busiest_closed_window(self.stamps(), 1), 3)


class DefaultHeadroom(Base):
    """The production headroom (SLOT_GUARD_SECONDS, 50 ms on a one-second window): a slot frees that long after the window,
    so two requests admitted a window apart arrive a window apart even when the earlier one is the slower."""
    guard = GUARD

    def test_a_slot_frees_a_window_plus_the_headroom_after_its_admission(self):
        for _ in range(3):
            self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, 1 + GUARD + EPS, places=9)
        self.at(1 + 1e-3)                    # a window later, the headroom not yet over
        self.denied()
        self.at(1 + GUARD + 2e-6)
        self.read()
        self.assertLessEqual(busiest_closed_window(self.stamps(), 1 + GUARD), 3, 'the headroom is part of the bound')
        self.assertLessEqual(busiest_closed_window(self.stamps(), 1), 3)

    def test_the_headroom_never_exceeds_a_tenth_of_a_short_window(self):
        self.make(2, .1)
        self.read()
        self.read()
        self.assertAlmostEqual(self.denied().retry_after_seconds, .1 + .01 + EPS, places=9)

    def test_the_headroom_costs_a_known_share_of_the_rate(self):
        """cap x window / (window + headroom): 25 per second becomes 23.8, which is 95% of the ceiling."""
        self.make(25, 1)
        for second in range(4):
            granted = 0
            self.at(second * (1 + GUARD + 2e-6))   # the first instant the previous burst's slots are free
            for _ in range(60):
                try:
                    self.read()
                    granted += 1
                except RateDelayed:
                    break
            self.assertEqual(granted, 25)
        self.assertAlmostEqual(25 / (1 + GUARD), 23.81, places=2)


class ShippedConstants(unittest.TestCase):
    """The classes above patch the headroom (Base.setUp) and so cannot see what production ships; this one reads it.

    Both numbers were chosen with measurements (tests/discord_ceiling_probe.py; the leak receipts of the unanswered-request
    lock-outs) and the launch gate is judged against them: changing either must be deliberate, which means changing this
    file in the same commit."""

    def test_the_shipped_slot_headroom_and_unanswered_request_margin_are_the_reviewed_ones(self):
        self.assertEqual(SharedPostgresBudget.SLOT_GUARD_SECONDS, GUARD)
        self.assertEqual(SharedPostgresBudget.UNOBSERVED_MARGIN_SECONDS, MARGIN)


class PolicyAndHold(Base):
    def test_tightening_applies_at_once_and_counts_what_was_already_admitted(self):
        self.make(5, 1)
        for _ in range(4):
            self.read()
        tighter = SharedPostgresBudget(self.db.connection, APP, policy={**self.policy, 'revision': 'tighter', 'app_capacity': 2})
        self.at(.5)
        error = self.denied(lambda: self.read(tighter))
        self.assertEqual(error.rate_scope_kind, 'application')
        self.assertAlmostEqual(error.retry_after_seconds, 1 + EPS - .5, places=9)
        self.at(1 + 2e-6)
        self.read(tighter)
        self.read(tighter)
        self.denied(lambda: self.read(tighter))  # two per window now, however many the old policy allowed
        self.assertEqual(self.policy_row()['cap'], 2)

    def test_a_looser_policy_cannot_raise_the_ceiling_while_the_tighter_one_is_valid(self):
        self.make(2, 1)
        self.read()
        looser = SharedPostgresBudget(self.db.connection, APP, policy={**self.policy, 'revision': 'looser', 'app_capacity': 50})
        self.read(looser)
        self.denied(lambda: self.read(looser))
        self.assertEqual(self.policy_row()['cap'], 2)

    def test_a_reviewed_raise_is_an_operator_update_of_the_stored_cap_and_nothing_else_raises_it(self):
        """A renewal alone never raises the ceiling (the test above), and neither does a later reservation under the renewed
        revision: the stored cap (limit_count of the application row) is the ceiling in force. The deliberate path is an
        UPDATE of that row; the exact window uses it at the next reservation. Pinned so a raise can neither happen by
        accident nor stop being possible, and so that a later, tighter policy still tightens a raised cap."""
        self.make(2, 1)
        self.read()
        higher = SharedPostgresBudget(self.db.connection, APP, policy={**self.policy, 'revision': 'raised', 'app_capacity': 5})
        for second in range(3):
            self.at(second * 1.2)
            self.read(higher)
        self.assertEqual(self.policy_row()['cap'], 2, 'renewed, and used under the renewed revision: unchanged')
        self.at(4)
        self.policy_row()['cap'] = 5                                                  # the operator's UPDATE of limit_count
        self.assertEqual([self.read(higher) is not None for _ in range(5)], [True] * 5)
        self.denied(lambda: self.read(higher))
        tighter = SharedPostgresBudget(self.db.connection, APP, policy={**self.policy, 'revision': 'tighter', 'app_capacity': 3})
        self.at(6)
        self.read(tighter)
        self.assertEqual(self.policy_row()['cap'], 3, 'a later, tighter policy still tightens a raised cap')

    def test_hold_refuses_everything_and_release_resumes_with_the_same_exact_state(self):
        """A hold refuses every request. A create is unavailable (nothing was or will be sent). A read is a wait of five
        minutes with the cause `hold`: that is what lets the read-back of a post that was already created defer, instead of
        burning one of its five checks on every attempt and being parked for a day (B4, the ops review's H1)."""
        self.read()
        self.read()
        self.policy_row()['hold'] = True
        with self.assertRaises(RateCoordinatorUnavailable):
            self.create()  # held while a slot is free
        wait = self.denied()
        self.assertEqual((wait.rate_cause, wait.rate_scope_kind, wait.retry_after_seconds), ('hold', 'embargo', 300.0))
        self.at(.1)
        self.policy_row()['hold'] = False
        self.read()  # the third and last slot of the window the hold interrupted
        self.denied()
        self.policy_row()['hold'] = True
        wait = self.denied()  # held and full: the hold, not the window, is what a caller sees
        self.assertEqual((wait.rate_cause, wait.retry_after_seconds), ('hold', 300.0))
        with self.assertRaises(RateCoordinatorUnavailable):
            self.create()
        self.policy_row()['hold'] = False
        self.assertEqual(len(self.db.admissions), 3, 'a hold neither admits nor refunds anything')
        self.at(1 + 2e-6)
        self.assertEqual(self.free_slots(), 2, 'the two admitted at +0 have freed; the one at +.1 has not')

    def test_a_hold_on_the_credential_or_the_bot_scope_defers_reads_the_same_way(self):
        """The coordinator holds the credential after a 401; a read behind that hold, or behind one on the bot's global scope, is
        a wait too, and a create is unavailable."""
        def hold(kind, value):
            # a refused reservation rolls back and replaces the double's state objects: look the row up every time
            (row,) = [state for state in self.db.states.values() if state['kind'] == kind]
            row['hold'] = value
        self.read()
        for kind in ('credential', 'global'):
            hold(kind, True)
            wait = self.denied()
            self.assertEqual((wait.rate_cause, wait.rate_scope_kind), ('hold', 'embargo'), kind)
            with self.assertRaises(RateCoordinatorUnavailable):
                self.create()
            hold(kind, False)
        self.read()

    def test_the_application_row_mirrors_the_window_for_readers(self):
        """lane.outlook reads remaining/reset without locks: a full window shows 0 and the exact next-slot time. That is the
        row without booking (BOOK_AHEAD_SECONDS 0, the switch that restores the old behaviour); with it the row is the
        booking horizon's (test_discord_rate_booking.StoredRow)."""
        with patch.object(SharedPostgresBudget, 'BOOK_AHEAD_SECONDS', 0.0):
            self.read()
            self.assertEqual(self.policy_row()['left'], 2)
            self.read()
            self.read()
            row = self.policy_row()
            self.assertEqual(row['left'], 0)
            self.assertAlmostEqual(row['reset'], T0 + 1 + EPS, places=9)
            self.at(.4)
            self.denied()
            self.assertEqual(self.policy_row()['reset'], row['reset'], 'a denial writes nothing')


class ReadsUnderAHold(Base):
    """What a caller of the Discord provider sees under an operator hold (B4): a read is a deferral that sends nothing,
    which is all the read-back of a created post needs to keep its checks; a create is still unavailable."""

    def provider(self):
        from postriff_phase2.social_connectors import DiscordProvider
        self.calls = []

        def transport(method, url, **kwargs):
            self.calls.append((method, url))
            return {'status': 200, 'headers': {}, 'body': {'id': '700000000000000009'}}
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.invalid', transport=transport)
        provider.rate_v1_enabled = True
        provider.rate_limiter = self.s
        return provider

    def test_a_direct_read_under_a_hold_is_a_deferral_that_sends_nothing_and_resumes_when_the_hold_is_lifted(self):
        from postriff_phase2.discord.rate_limits import ReadAdmissionDelayed
        provider = self.provider()
        message = '/channels/700000000000000002/messages/700000000000000003'
        provider._bot('GET', '/guilds/700000000000000001')          # the application row exists
        self.policy_row()['hold'] = True
        for _ in range(8):                                           # more attempts than a post has checks
            with self.assertRaises(ReadAdmissionDelayed) as wait:
                provider._bot('GET', message)
            self.assertEqual((wait.exception.rate_cause, wait.exception.rate_scope_kind, wait.exception.retry_after_seconds),
                             ('hold', 'embargo', 300.0))
        self.assertEqual(len(self.calls), 1, 'nothing was sent under the hold')
        self.assertEqual(len(self.db.admissions), 1, 'and nothing was admitted or charged')
        self.policy_row()['hold'] = False
        self.at(2)
        provider._bot('GET', message)
        self.assertEqual(len(self.calls), 2, 'the first read after the release goes out')

    def test_a_create_under_a_hold_is_still_unavailable_not_a_wait(self):
        provider = self.provider()
        provider._bot('GET', '/guilds/700000000000000001')
        self.policy_row()['hold'] = True
        with self.assertRaises(RateCoordinatorUnavailable):
            self.s.reserve('POST', '/channels/700000000000000002/messages', identity=self.identity)
        self.assertEqual(len(self.calls), 1)


class ReleasedReservations(Base):
    def test_a_reservation_rolled_back_after_its_debit_costs_no_slot(self):
        self.db.insert_delay = 2  # the permit expires while it is being stored
        error = self.denied()
        self.assertEqual((error.rate_cause, error.rate_scope_kind), ('permit_expired', 'permit'))
        self.assertFalse(self.db.admissions)
        self.db.insert_delay = 0
        self.assertEqual(self.free_slots(), 3)

    def test_an_unused_permit_holds_its_slot_until_it_expires_and_no_longer(self):
        for _ in range(3):
            self.create()                  # reserved, never consumed; the test policy's permit lifetime is 2 seconds
        self.denied(self.create)
        self.at(1.5)                       # older than its span, still usable: it may be consumed any moment
        self.assertEqual(self.free_slots(), 0)
        self.at(2 - 1e-6)
        self.assertEqual(self.free_slots(), 0)
        self.at(2 + 1e-6)                  # expired: nothing carries over
        self.assertEqual(self.free_slots(), 3)

    def test_an_abandoned_admission_is_not_refunded_inside_its_window(self):
        permit = self.read(answered=False)
        self.s.abandon_unsent_read(permit)
        self.assertEqual(self.db.admissions[permit.id]['state'], 'blocked')
        self.assertEqual(self.free_slots(), 2)
        self.at(1 + 2e-6)
        self.assertEqual(self.free_slots(), 3)

    def test_a_permit_lives_the_policy_lifetime_lease_and_approval_and_no_window_ends_it(self):
        self.assertAlmostEqual(self.create().expires_at, T0 + 2, places=6)           # permit_ttl_seconds, longer than the window
        self.setUp(3, .4)
        self.assertAlmostEqual(self.create().expires_at, T0 + 2, places=6)           # not the .4-second window
        self.setUp(3, 1)
        self.assertAlmostEqual(self.s.reserve('GET', self.path(), identity=self.identity, valid_until=T0 + 1.5).expires_at,
                               T0 + 1.5, places=6)                                  # the caller's lease or approval ends first
        self.assertAlmostEqual(self.s.reserve('GET', self.path(), identity=self.identity, valid_until=T0 + 9).expires_at,
                               T0 + 2, places=6)                                    # and never extends the lifetime
        with self.assertRaises(RateDelayed) as caught:
            self.s.reserve('GET', self.path(), identity=self.identity, valid_until=T0 - 1)
        self.assertEqual(caught.exception.rate_cause, 'window_expiring')            # a deadline already past admits nothing

    def test_a_permit_is_usable_after_the_window_that_reserved_it_ended(self):
        path, later = '/guilds/700000000000000001', '/guilds/700000000000000002'
        permit = self.s.reserve('GET', path, identity=self.identity)
        self.at(1.9)
        self.s.consume(permit, 'GET', path)                                          # it used to die at 1.0
        self.assertEqual(self.db.admissions[permit.id]['state'], 'sent')
        unused = self.s.reserve('GET', later, identity=self.identity)                # reserved at 1.9, lives to 3.9
        self.at(4.0)
        with self.assertRaises(RateDelayed):
            self.s.consume(unused, 'GET', later)
        self.assertEqual(self.db.admissions[unused.id]['state'], 'reserved')


class WireTime(Base):
    """An admission occupies a slot from the moment it can reach Discord. A create is admitted as a permit and
    reaches Discord only when it is consumed, which can be seconds later: its slot runs from its use, not its reservation,
    or a late create would land in a window that already holds the cap."""
    def test_a_create_used_late_occupies_a_slot_from_its_use_not_from_its_reservation(self):
        self.setUp(2, 1)
        permit = self.s.reserve('GET', '/guilds/700000000000000100', identity=self.identity)   # reserved at T0
        self.at(1.5)
        self.assertEqual(self.free_slots(), 1, 'the unused permit still holds one of the two slots')
        self.s.consume(permit, 'GET', '/guilds/700000000000000100')                            # on the wire at T0 + 1.5
        self.s.observe(permit, OK)
        self.at(1.6)
        self.read()                                                                           # the second slot
        self.at(1.7)
        error = self.denied()
        self.assertAlmostEqual(error.retry_after_seconds, 2.5 + EPS - 1.7, places=6, msg='the create frees at its use + 1')
        self.at(2.5 + 2e-6)
        self.read()
        wires = [row['sent'] if row['sent'] is not None else row['reserved'] for row in self.db.admissions.values()]
        self.assertLessEqual(busiest_closed_window(wires, 1), 2)

    def test_a_permit_that_is_never_used_costs_one_span_from_its_reservation_after_it_expires(self):
        self.setUp(2, 1)
        self.s.reserve('GET', '/guilds/700000000000000200', identity=self.identity)
        self.at(2 + 1e-6)                                                                     # expired unused
        self.assertEqual(self.free_slots(), 2)
        self.read()
        self.assertEqual(self.free_slots(), 1)

    def test_the_slot_of_a_used_permit_does_not_free_when_the_answer_comes(self):
        """A request answered at once still occupies its span: the answer says nothing of when the next may leave."""
        self.setUp(1, 1)
        permit = self.s.reserve('GET', '/guilds/700000000000000300', identity=self.identity)
        self.at(.9)
        self.s.consume(permit, 'GET', '/guilds/700000000000000300')
        self.s.observe(permit, OK)
        self.at(1.5)                                                                          # a window after the RESERVATION
        error = self.denied()
        self.assertAlmostEqual(error.retry_after_seconds, .9 + 1 + EPS - 1.5, places=6)


class SlidingModel:
    """The specification as plain Python, tracking each request's state only from what the API told the caller.

    It shares nothing with the implementation: no SQL, no ledger rows, no scope keys."""
    def __init__(self, capacity, window, margin, guard):
        self.capacity, self.window, self.margin, self.rows = capacity, window, margin, []
        self.span = window + min(guard, window / 10)   # how long an admission occupies a slot
        self.decisions = {'ok': 0, 'wait': 0, 'retained': 0}   # what the run actually exercised

    def decide(self, now):
        """('ok', None) or ('wait', seconds until the next admission is possible)."""
        held, occupied = 0, []
        for row in self.rows:
            wire = row['sent'] if row['sent'] is not None else row['at']   # a permit not used yet has no wire time
            if wire > now - self.span - EPS:   # inside its span: it occupies a slot whatever became of it
                occupied.append(wire)
            elif row['state'] in ('reserved', 'sealed') and row['expires'] > now:   # older: only while it may still be used
                held += 1
            elif row['state'] in ('sent', 'uncertain') and wire > now - self.window - self.margin:   # or still unanswered
                held += 1
        self.decisions['retained'] += held > 0
        slots = self.capacity - held
        if slots <= 0:
            outcome = 'wait', self.window
        else:
            occupied.sort()
            outcome = (('wait', occupied[len(occupied) - slots] + self.span + EPS - now)
                       if len(occupied) >= slots else ('ok', None))
        self.decisions[outcome[0]] += 1
        return outcome


class RandomizedAgainstModel(unittest.TestCase):
    """The coordinator against the model over random lives: reserve, reserve_read, consume, answer, fail, abandon,
    holds, tightening and every awkward time step. Seeds are fixed; a failure names the seed and the step."""
    SEEDS = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597)
    STEPS = 260

    def run_seed(self, seed):
        rng = random.Random(seed)
        capacity, window = rng.choice((1, 2, 3, 5, 8)), rng.choice((1, 1, .5, .25, 2))
        guard = rng.choice((0.0, GUARD, GUARD, .2))   # none, the production headroom, and one wide enough to bind
        with patch.object(SharedPostgresBudget, 'SLOT_GUARD_SECONDS', guard, create=True):
            return self.live(seed, rng, capacity, window, guard)

    def live(self, seed, rng, capacity, window, guard):
        db = MemoryLedger(now=T0)
        base = policy(capacity, window)
        limiter = SharedPostgresBudget(db.connection, APP, policy=base)
        identity = RequestIdentity.make(APP, 'bot', 'randomized-bot')
        model = SlidingModel(capacity, window, MARGIN, guard)
        outstanding = []      # (permit, path, model row) in the order they were admitted
        every_wire = {}       # each admission's wire time (its reservation until a permit is used), kept because old rows are pruned
        serial, on_hold, tightened = 0, False, False
        span = model.span
        steps = [0, 1e-6, 2e-6, .5e-6, .01, .2, window / 2, window - 1e-6, window, window + .5e-6, window + 2e-6,
                 span - 1e-6, span, span + .5e-6, span + 2e-6, 2 * window, 3.7, MARGIN, window + MARGIN + 2e-6,
                 window + MARGIN - 1e-6]
        label = lambda step, what: 'seed %d step %d: %s' % (seed, step, what)  # noqa: E731
        for step in range(self.STEPS):
            if db.now > T0 + 3000:
                break
            roll = rng.random()
            db.now += rng.choice(steps) if rng.random() < .75 else rng.uniform(0, 2 * window)
            now = db.now
            # Every resource is cold and used once: its route rows can never matter again (see Base.forget_routes).
            db.states = {k: v for k, v in db.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
            db.maps = {}
            # A row older than window + margin can neither fill a window nor be carried into one: the model keeps its own.
            db.admissions = {k: v for k, v in db.admissions.items() if v['reserved'] > now - window - MARGIN - 5}
            outstanding = [entry for entry in outstanding if entry[0].id in db.admissions]
            if roll < .55:  # a reservation, of a random kind
                read = rng.random() < .5
                serial += 1
                method = 'GET' if read or rng.random() < .5 else 'POST'   # a write that is lost stays unresolved; a read does not
                path = ('/guilds/%d' if method == 'GET' else '/channels/%d/messages') % (700000000000000000 + serial)
                expected = model.decide(now)
                try:
                    permit = (limiter.reserve_read if read else limiter.reserve)(method, path, identity=identity)
                except RateDelayed as error:
                    if on_hold:   # a hold comes before any window: a read under it is a five-minute wait with the cause hold
                        self.assertTrue(read, label(step, 'only a read waits under a hold; a create is unavailable'))
                        self.assertEqual((error.rate_cause, error.rate_scope_kind, error.retry_after_seconds),
                                         ('hold', 'embargo', 300.0), label(step, 'a read under a hold'))
                        continue
                    self.assertEqual(expected[0], 'wait', label(step, 'denied but the model grants'))
                    detail = 'wait; scope %s, method %s, read %s, the model said %r' % (error.rate_scope_kind, method, read, expected)
                    if tightened:   # admissions made under the larger cap can outnumber what is scanned: the quote may be longer
                        self.assertGreaterEqual(error.retry_after_seconds, max(.001, expected[1]) - 1e-7, label(step, detail))
                    else:
                        self.assertAlmostEqual(error.retry_after_seconds, max(.001, expected[1]), places=7, msg=label(step, detail))
                    self.assertEqual(error.rate_scope_kind, 'application', label(step, 'scope'))
                except RateCoordinatorUnavailable:
                    self.assertTrue(on_hold, label(step, 'unavailable without a hold'))
                    self.assertFalse(read, label(step, 'a read under a hold waits; it is not unavailable'))
                else:
                    self.assertFalse(on_hold, label(step, 'granted under a hold'))
                    self.assertEqual(expected[0], 'ok', label(step, 'granted but the model waits %r' % (expected,)))
                    at = db.admissions[permit.id]['reserved']
                    every_wire[permit.id] = at
                    row = {'at': at, 'state': 'sent' if read else 'reserved', 'sent': at if read else None,
                           'expires': permit.expires_at}
                    model.rows.append(row)
                    outstanding.append((permit, method, path, row))
            elif roll < .70 and outstanding and not on_hold:   # consume a permit that was not a read
                permit, method, path, row = rng.choice(outstanding)
                if row['state'] == 'reserved':
                    try:
                        limiter.consume(permit, method, path)
                    except RateDelayed:
                        self.assertLessEqual(row['expires'], now, label(step, 'consume refused before expiry'))
                    else:
                        row['state'], row['sent'] = 'sent', now
                        every_wire[permit.id] = now
            elif roll < .85 and outstanding and not on_hold:   # resolve a sent request one way or another
                permit, method, path, row = rng.choice(outstanding)
                if row['state'] == 'sent':
                    how = rng.choice(('answer', 'answer', 'fail', 'abandon'))
                    if how == 'abandon' and method != 'GET':
                        how = 'fail'
                    if how == 'answer':
                        limiter.observe(permit, OK)
                        row['state'] = 'observed'
                    elif how == 'fail':
                        limiter.note_transport_failure(permit)
                        row['state'] = 'observed' if method == 'GET' else 'uncertain'   # a read is resolved at once
                    else:
                        limiter.abandon_unsent_read(permit)
                        row['state'] = 'blocked'
            elif roll < .90:    # the operator's hold, on or off (once the application row exists)
                rows = [state for state in db.states.values() if state['kind'] == 'policy']
                if rows:
                    on_hold = not on_hold
                    rows[0]['hold'] = on_hold
            elif roll < .93 and not on_hold:   # a reviewed policy tightens the cap
                capacity = max(1, capacity - rng.choice((0, 1, 2)))
                tightened = tightened or capacity < model.capacity
                model.capacity = min(model.capacity, capacity)
                limiter = SharedPostgresBudget(db.connection, APP, policy={**base, 'revision': 'tight-%d' % step,
                                                                           'app_capacity': capacity})
        # The invariant, from the ledger alone: no closed interval of one window holds more than the cap that was in
        # force. (A tightening can only lower it, so the initial cap is the weakest bound; the model checked the rest.)
        self.assertLessEqual(busiest_closed_window(list(every_wire.values()), window), base['app_capacity'], 'seed %d' % seed)
        self.assertLessEqual(busiest_closed_window(list(every_wire.values()), model.span), base['app_capacity'], 'seed %d, span' % seed)
        return model.decisions

    def test_every_seed_agrees_with_the_model_and_keeps_the_ceiling(self):
        total = {'ok': 0, 'wait': 0, 'retained': 0}
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                for key, count in self.run_seed(seed).items():
                    total[key] += count
        # The seeds must have exercised the interesting decisions, not just easy grants.
        self.assertGreater(total['ok'], 400)
        self.assertGreater(total['wait'], 200)
        self.assertGreater(total['retained'], 40, 'decisions made while an unanswered request held a slot past its window')


class SustainedRate(unittest.TestCase):
    """The ceiling must not cost throughput. Under a backlog the coordinator still admits the whole cap whatever the time
    between a request's admission and the recording of its answer; the fixed window charged a request still in flight
    when a new window began to that window as well. Deterministic: a fake clock and a seeded jitter.

    N clients ask in a closed loop. A refused client sleeps its wait plus 0 to 25 ms (what providers._discord_http
    does); an admitted request is in flight for `in_flight` seconds, is answered, and its client asks again at once."""

    def simulate(self, in_flight, clients=8, seconds=7.0, warmup=2.0, cap=25, window=1.0, seed=7):
        rng = random.Random(seed)
        db = MemoryLedger(now=T0)
        limiter = SharedPostgresBudget(db.connection, APP, policy=policy(cap, window, permit_ttl_seconds=5,
                                                                          invalid_capacity=100000))
        identity = RequestIdentity.make(APP, 'bot', 'simulated-bot')
        events = [(T0 + rng.uniform(0, .03), client, 'ask', None) for client in range(clients)]
        heapq.heapify(events)
        stamps, majors, pruned = [], 0, T0
        while events[0][0] < T0 + seconds:
            at, client, what, permit = heapq.heappop(events)
            db.now = at
            if what == 'ask':
                majors += 1
                try:
                    permit = limiter.reserve_read('GET', '/guilds/%d' % (700000000000000000 + majors), identity=identity)
                except RateDelayed as error:
                    heapq.heappush(events, (at + max(error.retry_after_seconds, .005) + rng.randrange(26) / 1000, client, 'ask', None))
                else:
                    stamps.append(db.admissions[permit.id]['reserved'])
                    heapq.heappush(events, (at + in_flight, client, 'answer', permit))
            else:
                limiter.observe(permit, OK)
                heapq.heappush(events, (at, client, 'ask', None))
            if at - pruned > 1:   # one-time resources, and answered requests a few windows old, can never matter again
                pruned = at
                db.states = {k: v for k, v in db.states.items() if k[:3] in ('00:', '10:', '11:', '20:')}
                db.maps = {}
                db.admissions = {k: v for k, v in db.admissions.items()
                                 if v['state'] in ('sent', 'reserved') or v['reserved'] > at - 3 * window}
        steady = [stamp for stamp in stamps if T0 + warmup <= stamp < T0 + seconds]
        return len(steady) / (seconds - warmup), busiest_closed_window(stamps, window)

    def test_a_backlog_gets_the_whole_cap_whatever_the_time_in_flight(self):
        for in_flight in (0, .12, .2):
            with self.subTest(in_flight_ms=int(in_flight * 1000)):
                rate, busiest = self.simulate(in_flight)
                self.assertGreaterEqual(rate, .96 * 25 / (1 + GUARD), 'sustained admissions per second: the cap less the headroom')
                self.assertLessEqual(busiest, 25, 'and never more than the cap in any closed second')


if __name__ == '__main__':
    unittest.main()
