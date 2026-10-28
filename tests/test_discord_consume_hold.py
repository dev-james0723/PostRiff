"""A hold, an embargo or an open circuit that begins after a permit was reserved stops it at consume (the independent review's
G2E-B-16), offline on the shared MemoryLedger double.

reserve() looks at the holds, embargoes and circuits of the scopes a request touches, and observe() blocks the permits still
unused when it sees one. consume() looked at neither: a permit reserved before the operator's hold could still be consumed after
it if no other answer was observed in between, and its POST went out under a hold that the runbook says stops Discord. Now
consume() asks, in one statement without a lock, whether any scope the permit was admitted under has a hold, an embargo or an
open circuit; if so the admission is closed `blocked` in a transaction that commits, and the caller is refused after the commit,
so that a publish permit's refusal is the same signal as one observe() gave (`permit_blocked`: the intent is proved unsent from
its admission row and the post is released). Nothing was sent; the slot stays spent.

The real-PostgreSQL proof is test_discord_consume_hold_postgres.py. No network, no credentials.
"""
import unittest

from postriff_phase2.discord.rate_limits import (
    SharedPostgresBudget, RequestIdentity, RateDelayed, RateCoordinatorUnavailable, HOLD_WAIT_SECONDS, _digest)
from test_discord_rate_limits import MemoryLedger, synthetic_policy, APP, A

PATH = '/channels/%s/messages' % A


def binding(publication):
    return {'workspaceId': '00000000-0000-0000-0000-000000000001', 'publicationId': publication, 'manifestDigest': 'a' * 64,
            'authorizationDigest': 'b' * 64, 'approvalDigest': 'c' * 64, 'workerKey': 'd' * 64, 'leaseKey': _digest(publication),
            'channelKey': _digest(A), 'applicationKey': _digest(APP)}


class Base(unittest.TestCase):
    def setUp(self):
        self.db = MemoryLedger(now=1000)
        self.s = SharedPostgresBudget(self.db.connection, APP, policy=synthetic_policy())
        self.identity = RequestIdentity.make(APP, 'bot', 'synthetic-consume-hold')

    def application_row(self):
        return self.db.states['00:' + self.s.application_key]

    def route_rows(self):
        return [row for key, row in self.db.states.items() if key.startswith('50:')]

    def sealed(self, publication='first'):
        """A publish permit, reserved and sealed; returns (permit, binding, intent)."""
        bound = binding(publication)
        permit = self.s.reserve('POST', PATH, identity=self.identity, binding=bound)
        with self.db.connection() as db, db.cursor() as cur:
            self.s.seal(cur, permit, bound, 'synthetic-intent', self.db.now + 2)
        return permit, bound, 'synthetic-intent'

    def consume(self, permit, bound, intent):
        return self.s.consume(permit, 'POST', PATH, binding=bound, intent_id=intent, authorize=lambda cur: self.db.now + 2)

    def admission(self, permit):
        return self.db.admissions[permit.id]

    def prove_unsent(self, permit, bound, intent):
        """What the worker does with a refused consume: the intent is proved unsent from the admission row."""
        with self.db.connection() as db, db.cursor() as cur:
            self.s.confirm_blocked_publish(cur, permit, bound, intent)


class StopsAtConsume(Base):
    def test_a_permit_is_consumed_when_nothing_has_begun(self):
        permit, bound, intent = self.sealed()
        self.consume(permit, bound, intent)
        self.assertEqual(self.admission(permit)['state'], 'sent')

    def test_a_hold_set_after_the_reservation_stops_the_consume_and_the_intent_is_proved_unsent(self):
        permit, bound, intent = self.sealed()
        self.application_row()['hold'] = True               # the runbook's stop, after the permit was reserved and sealed
        with self.assertRaises(RateDelayed) as caught:
            self.consume(permit, bound, intent)
        self.assertEqual((caught.exception.rate_cause, caught.exception.rate_scope_kind), ('permit_blocked', 'embargo'))
        row = self.admission(permit)
        self.assertEqual(row['state'], 'blocked', 'closed, and the refusal did not roll that back')
        self.assertIsNone(row.get('sent'))
        self.prove_unsent(permit, bound, intent)
        with self.assertRaises(RateDelayed) as again:       # a retry of the same permit is refused the same way, by the existing path
            self.consume(permit, bound, intent)
        self.assertEqual(again.exception.rate_cause, 'permit_blocked')

    def test_a_hold_lifted_afterwards_does_not_revive_the_blocked_permit(self):
        permit, bound, intent = self.sealed()
        self.application_row()['hold'] = True
        with self.assertRaises(RateDelayed):
            self.consume(permit, bound, intent)
        self.application_row()['hold'] = False
        with self.assertRaises(RateDelayed):
            self.consume(permit, bound, intent)
        self.assertEqual(self.admission(permit)['state'], 'blocked')
        self.db.now += 2                                        # past the cold route's probe window
        fresh, bound2, intent2 = self.sealed('second')         # a new reservation is a new permit
        self.consume(fresh, bound2, intent2)
        self.assertEqual(self.admission(fresh)['state'], 'sent')

    def test_an_embargo_on_the_route_or_an_open_circuit_stops_it_for_what_is_left(self):
        for field in ('blocked', 'circuit'):
            with self.subTest(field=field):
                self.setUp()
                permit, bound, intent = self.sealed()
                (route,) = self.route_rows()
                route[field] = self.db.now + 3.0
                with self.assertRaises(RateDelayed) as caught:
                    self.consume(permit, bound, intent)
                self.assertEqual(caught.exception.rate_cause, 'permit_blocked')
                self.assertAlmostEqual(caught.exception.retry_after_seconds, 3.0, places=3)
                self.assertEqual(self.admission(permit)['state'], 'blocked')

    def test_an_embargo_that_has_ended_does_not_stop_it(self):
        permit, bound, intent = self.sealed()
        (route,) = self.route_rows()
        route['blocked'] = self.db.now - 1.0
        route['circuit'] = self.db.now - 1.0
        self.consume(permit, bound, intent)
        self.assertEqual(self.admission(permit)['state'], 'sent')

    def test_a_hold_on_a_scope_the_permit_does_not_touch_does_not_stop_it(self):
        permit, bound, intent = self.sealed()
        other = self.s.reserve('GET', '/channels/%s/messages/%s' % ('999999999999999999', '888888888888888888'),
                               identity=RequestIdentity.make(APP, 'bot', 'synthetic-another-bot'))
        for key in self.admission(other)['keys']:
            if key.startswith('11:'):
                self.db.states[key]['hold'] = True          # another credential's hold
        self.consume(permit, bound, intent)
        self.assertEqual(self.admission(permit)['state'], 'sent')

    def test_a_permit_without_a_binding_is_stopped_too_and_waits_as_a_read_does_for_a_hold(self):
        permit = self.s.reserve('GET', '/guilds/700000000000000001', identity=self.identity)
        self.application_row()['hold'] = True
        with self.assertRaises(RateDelayed) as caught:
            self.s.consume(permit, 'GET', '/guilds/700000000000000001')
        self.assertEqual((caught.exception.rate_cause, caught.exception.rate_scope_kind), ('hold', 'embargo'))
        self.assertAlmostEqual(caught.exception.retry_after_seconds, HOLD_WAIT_SECONDS)
        self.assertEqual(self.admission(permit)['state'], 'blocked')

    def test_the_bearer_budget_s_hold_stops_a_bearer_permit_and_only_it(self):
        self.s = SharedPostgresBudget(self.db.connection, APP, policy={**synthetic_policy(), 'bearer_capacity': 5, 'bearer_window_seconds': 1})
        user = RequestIdentity.make(APP, 'user', 'synthetic-bearer-consume', '444444444444444444')
        mine = self.s.reserve('GET', '/guilds/700000000000000002', identity=user)
        bots = self.s.reserve('GET', '/guilds/700000000000000003', identity=self.identity)
        self.db.states['01:' + self.s.application_key]['hold'] = True
        with self.assertRaises(RateDelayed):
            self.s.consume(mine, 'GET', '/guilds/700000000000000002')
        self.s.consume(bots, 'GET', '/guilds/700000000000000003')
        self.assertEqual((self.admission(mine)['state'], self.admission(bots)['state']), ('blocked', 'sent'))


class StillFailsClosed(Base):
    def test_a_coordinator_that_cannot_answer_the_question_does_not_consume(self):
        permit, bound, intent = self.sealed()
        original = self.s._stopped

        def broken(cur, keys):
            raise OSError('the statement failed')
        self.s._stopped = broken
        with self.assertRaises(RateCoordinatorUnavailable):
            self.consume(permit, bound, intent)
        self.assertEqual(self.admission(permit)['state'], 'sealed', 'nothing was changed: the transaction rolled back')
        self.s._stopped = original
        self.consume(permit, bound, intent)
        self.assertEqual(self.admission(permit)['state'], 'sent')


if __name__ == '__main__':
    unittest.main()
