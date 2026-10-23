"""Offline contracts for requests whose answer was never observed, and for learned routes that wait for an answer.

Before: a request marked sent whose answer never came (a transport error after Discord replied, a function killed
between its admission and its answer, an observation that timed out) kept one slot of every scope it was charged to
FOR EVER. Twenty-five of them stalled the whole application for good, and a learned route that was refilled and then
lost its answers kept the policy-expiry sentinel as its next reset: it waited for a fresh answer that no request could
bring, and callers were told to wait until the policy expired.

Now: such a request keeps a slot for its scope's window plus UNOBSERVED_MARGIN_SECONDS, which is as long as it can still
reach Discord; a refilled learned window that no answer has established lapses after the same time and is refilled
again; a late answer from before a refill cannot shrink the refilled window; a caller is never quoted the sentinel.

Storage is the shared MemoryLedger double (fake database clock). The real-PostgreSQL proof is in
test_discord_rate_ceiling_postgres.py.
"""
import unittest

from postriff_phase2.discord.rate_limits import RateDelayed, Permit
from test_discord_rate_ceiling import Base, T0, EPS, MARGIN, OK
from test_discord_rate_limits import A, B

PATH = '/channels/%s/messages/%s' % (A, B)


def headers(remaining, after, limit=3):
    return {'status': 200, 'headers': {'X-RateLimit-Bucket': 'unobserved-route', 'X-RateLimit-Limit': str(limit),
                                       'X-RateLimit-Remaining': str(remaining), 'X-RateLimit-Reset-After': str(after)}}


class UnansweredRequests(Base):
    """Sent but never answered: a slot while the request can still reach Discord, never for ever."""

    def test_one_unanswered_request_keeps_a_slot_past_its_window_for_the_margin_only(self):
        self.read(answered=False)                         # sent at T0; its answer is never observed
        self.at(.5)
        self.assertEqual(self.free_slots(), 2)            # inside its window it counts as the admission it is
        self.at(1 + 2e-6)
        self.assertEqual(self.free_slots(), 2)            # past its window it still holds a slot
        self.at(1 + MARGIN - 1e-3)
        self.assertEqual(self.free_slots(), 2)            # ... until window + margin
        self.at(1 + MARGIN + 1e-3)
        self.assertEqual(self.free_slots(), 3)

    def test_a_hundred_leaked_requests_older_than_the_margin_do_not_reduce_the_budget(self):
        self.make(200, 1)
        for _ in range(100):
            self.s.note_transport_failure(self.read(answered=False))   # sent, then a transport error: never resolved
        self.assertEqual({row['state'] for row in self.db.admissions.values()}, {'uncertain'})
        self.at(1 + 2e-6)
        self.assertEqual(self.free_slots(), 100)          # a hundred slots held while they can still matter
        self.at(1 + MARGIN - 1e-3)
        self.assertEqual(self.free_slots(), 100)
        self.at(1 + MARGIN + 1e-3)
        self.assertEqual(self.free_slots(), 200)          # then the whole budget is back
        self.assertEqual(len(self.db.admissions), 100, 'the rows are kept as evidence; they just stop counting')

    def test_one_leaked_request_inside_its_window_still_counts(self):
        self.s.note_transport_failure(self.read(answered=False))
        self.read()
        self.read()
        self.assertEqual(self.denied().rate_scope_kind, 'application')

    def test_a_late_answer_resolves_the_request_and_frees_its_slot_at_once(self):
        permit = self.read(answered=False)
        self.at(5)                                        # long past its window, still unanswered
        self.assertEqual(self.free_slots(), 2)
        self.s.observe(permit, OK)
        self.assertEqual(self.free_slots(), 3)

    def test_the_cold_probe_of_a_route_is_released_when_its_unanswered_request_ages_out(self):
        path = '/channels/%s' % A
        permit = self.s.reserve_read('GET', path, identity=self.identity)
        self.s.note_transport_failure(permit)
        again = lambda: self.s.reserve_read('GET', path, identity=self.identity)  # noqa: E731
        self.at(3)
        self.assertIn(self.denied(again).rate_scope_kind, ('discovery', 'unknown_route'))  # the probe's answer is unknown
        self.at(1 + MARGIN - 1e-3)
        self.denied(again)
        self.at(1 + MARGIN + 1e-3)
        self.assertIsInstance(again(), Permit)                              # it probes again

    def test_twenty_six_hostile_guilds_stall_a_victim_only_for_window_plus_margin(self):
        """Unit form of the reviewer's reproduction: each hostile guild's answer is refused after it arrived (a channel
        list over 256 KiB), so the request is recorded as uncertain. Twenty-five of them used to cost the whole
        budget for good."""
        self.make(25, 1)
        leaked = 0
        for _ in range(26):
            try:
                self.s.note_transport_failure(self.read(answered=False))
                leaked += 1
            except RateDelayed:
                pass
        self.assertEqual(leaked, 25)
        victim = lambda: self.s.reserve_read('GET', '/guilds/%d' % 700000000000000999, identity=self.identity)  # noqa: E731
        for offset in (1 + 2e-6, 5, 1 + MARGIN - 1e-3):
            self.at(offset)
            self.assertEqual(self.denied(victim).rate_scope_kind, 'application')
        self.at(1 + MARGIN + 1e-3)
        self.assertIsInstance(victim(), Permit)           # served; the application row was not poisoned
        self.assertEqual(self.free_slots(), 24)


class LearnedRouteRecovery(Base):
    """A learned bucket of three per second: its refill, the answers that follow, and the answers that never do."""

    def setUp(self):
        super().setUp(100, 1)     # the application budget must not be what binds here

    def send(self, answer=None):
        permit = self.s.reserve('GET', PATH, identity=self.identity)
        self.s.consume(permit, 'GET', PATH)
        if answer is not None:
            self.s.observe(permit, answer)
        return permit

    def route(self):
        return next(row for row in self.db.states.values() if row['kind'] == 'route' and row['learned'])

    def wait_for(self):
        """The wait a caller is quoted now, or 0 if a reservation would be granted (nothing is kept either way)."""
        try:
            permit = self.s.reserve('GET', PATH, identity=self.identity)
        except RateDelayed as error:
            return error.retry_after_seconds
        self.db.admissions.pop(permit.id)
        return 0

    def test_a_request_nobody_saw_stops_shrinking_a_learned_route_once_it_can_no_longer_matter(self):
        self.send(headers(2, 1))                           # learns the route: three per second
        lost = self.send()                                 # a request whose answer never comes
        self.at(1.5)
        self.send(headers(2, 1))                           # the window rolls: the lost request is carried into it ...
        self.assertEqual(self.route()['left'], 1, 'three, less the request nobody saw, less this one')
        self.at(2 + MARGIN)
        self.send(headers(2, 1))                           # ... and, long past window + margin, it is no longer carried
        self.assertEqual(self.route()['left'], 2, 'three, less this one: the aged-out request takes no slot')
        self.assertEqual(self.db.admissions[lost.id]['state'], 'sent', 'it stays on record for an operator')

    def test_a_late_answer_from_before_a_refill_cannot_drain_the_refilled_bucket(self):
        self.send(headers(2, 1))
        late = self.send()                                 # the last request of window 1: still in flight at its end
        self.at(1.1)                                       # window 1 is over; the next reservation refills
        fresh = self.send()                                # window 2: charges `late` (in flight) and itself
        self.assertEqual(self.route()['left'], 1)
        self.s.observe(late, headers(0, .2))               # its answer: remaining 0 of the window that ended
        self.assertEqual(self.route()['left'], 1, 'it describes the old window; the refill already charged it')
        self.s.observe(fresh, headers(2, 1))               # window 2's own answer establishes the real reset
        self.assertEqual(self.route()['left'], 1)
        self.assertIsNone(self.route()['freshAfter'])
        self.assertAlmostEqual(self.route()['reset'], T0 + 2.1, places=6)

    def test_a_late_stale_answer_and_a_lost_establishing_answer_do_not_wedge_the_route(self):
        self.send(headers(2, 1))
        late = self.send()
        self.at(1.1)
        self.send()                                        # window 2's request: its answer is lost
        self.s.observe(late, headers(0, .2))               # the old window's answer arrives
        for tick in range(4):                              # the route keeps serving: it never waits for the sentinel
            self.at(1.1 + 1.1 * (tick + 1))
            self.send(headers(2, 1))

    def test_an_answer_after_the_new_window_was_established_costs_at_most_the_rest_of_that_window(self):
        """Known and bounded: once the first answer of the new window has cleared the wait, an older request's answer
        is not recognised as old (the row keeps no window start), so it can still drain what is left of THAT window.
        The next window refills in full; nothing waits beyond the established reset."""
        self.send(headers(2, 1))
        late = self.send()
        self.at(1.1)
        fresh = self.send()
        self.s.observe(fresh, headers(2, 1))
        self.assertEqual(self.route()['left'], 1)
        self.s.observe(late, headers(0, .2))
        self.assertLessEqual(self.route()['left'], 1)
        established = self.route()['reset']
        self.assertLessEqual(established - self.db.now, 1.0, 'the lost slots are only those of this window')
        self.db.now = established + .01
        self.send(headers(2, 1))                           # the next window serves again

    def test_a_refilled_window_whose_answers_were_all_lost_is_refilled_again_after_window_plus_margin(self):
        self.send(headers(2, 1))
        self.at(1.1)
        for _ in range(3):
            self.send()                                    # the refill's three slots: every process died before its answer
        self.assertEqual(self.route()['left'], 0)
        self.assertGreater(self.route()['reset'], T0 + 3000, 'waiting for an answer that has the policy expiry as its placeholder')
        lapse = 1.1 + 1 + MARGIN                           # the refill at +1.1 waits a window plus the margin for an answer
        for offset in (2.2, 5, lapse - .5):                # until then callers are quoted a poll, or the lapse if sooner
            self.at(offset)
            self.assertAlmostEqual(self.wait_for(), min(1.0, lapse - offset), places=6, msg='at +%s' % offset)
        self.at(lapse + .5)                                # then the window is refilled once more
        self.assertEqual(self.wait_for(), 0)

    def test_nobody_is_quoted_the_policy_expiry_as_a_wait(self):
        """Every slot is already taken by requests in flight when the window ends (here synthetic rows for the same
        bucket): the refill leaves nothing, and the caller is told to ask again in a window, not at the policy's end."""
        self.send(headers(2, 1))
        template = next(iter(self.db.admissions.values()))
        for number in range(3):
            row = dict(template, id='in-flight-%d' % number, seq=1000 + number, state='sent', reserved=T0 + .5, sent=T0 + .5,
                       expires=T0 + .5 + 1)
            self.db.admissions[row['id']] = row
        self.at(1.1)
        wait = self.wait_for()
        self.assertAlmostEqual(wait, 1.0, places=6)
        self.assertLess(wait, 10)
        for row in list(self.db.admissions.values()):      # their answers arrive
            if row['id'].startswith('in-flight'):
                row['state'] = 'observed'
        self.assertEqual(self.wait_for(), 0)


if __name__ == '__main__':
    unittest.main()
