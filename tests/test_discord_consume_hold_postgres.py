"""Real-PostgreSQL proof that a hold, an embargo or a circuit that begins after a permit was reserved stops it at consume (the
independent review's G2E-B-16; its reproduction was poc/h16_hold_consume.py): the runbook's hold is an UPDATE of the state row and
touches no admission, and consume() used to read none of the state rows, so a permit reserved before the hold and consumed after it
went out unless some other answer was observed in between. Now consume() asks in one statement without a lock; the admission is
closed `blocked` in a transaction that commits, the caller is refused after it, and the intent is proved unsent from the admission
row (`confirm_blocked_publish`), the signal the worker already turns into a release.

A disposable cluster (tests/discord_lane_fixture.py), the repository's schema, the real coordinator. Runs where POSTRIFF_PG_BIN
names the PostgreSQL server binaries; synthetic ids only, no network.
"""
import unittest
import uuid

import discord_lane_fixture as F
from postriff_phase2.discord.rate_limits import RateDelayed, RequestIdentity, SharedPostgresBudget, _digest

CHANNEL = '700000000000000001'


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class HoldAtConsume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()
        self.identity = RequestIdentity.make(F.APP, 'bot', 'synthetic-' + uuid.uuid4().hex[:16])
        self.s = SharedPostgresBudget(self.cluster.factory(), F.APP, policy=F.policy(self.cluster.now(), capacity=25))

    def hold(self, value=True):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute("UPDATE public.pr_discord_rate_state SET manual_hold=%s WHERE kind='policy'", (value,)).rowcount

    def row(self, permit):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute('SELECT state,sent_at IS NULL FROM public.pr_discord_request_admissions WHERE id=%s::uuid', (permit.id,)).fetchone()

    def binding(self, publication):
        return {'workspaceId': str(uuid.uuid4()), 'publicationId': publication, 'manifestDigest': 'a' * 64, 'authorizationDigest': 'b' * 64,
                'approvalDigest': 'c' * 64, 'workerKey': 'd' * 64, 'leaseKey': _digest(publication), 'channelKey': _digest(CHANNEL),
                'applicationKey': self.s.application_key}

    def sealed(self, publication):
        bound = self.binding(publication)
        path = '/channels/%s/messages' % CHANNEL
        permit = self.s.reserve('POST', path, identity=self.identity, binding=bound)
        with self.cluster.factory()() as db, db.cursor() as cur:
            self.s.seal(cur, permit, bound, 'synthetic-intent', self.cluster.now() + 5)
        return permit, bound, path

    def test_a_sealed_publish_permit_reserved_before_the_hold_is_not_consumed_after_it(self):
        permit, bound, path = self.sealed('before-the-hold')
        self.assertEqual(self.hold(), 1, 'the runbook\'s hold took')
        with self.assertRaises(RateDelayed) as caught:
            self.s.consume(permit, 'POST', path, binding=bound, intent_id='synthetic-intent', authorize=lambda cur: self.cluster.now() + 5)
        self.assertEqual((caught.exception.rate_cause, caught.exception.rate_scope_kind), ('permit_blocked', 'embargo'))
        self.assertEqual(self.row(permit), ('blocked', True), 'closed and never marked sent, and the refusal did not roll that back')
        with self.cluster.factory()() as db, db.cursor() as cur:
            self.s.confirm_blocked_publish(cur, permit, bound, 'synthetic-intent')      # the intent is proved unsent
        self.hold(False)
        with self.assertRaises(RateDelayed):
            self.s.consume(permit, 'POST', path, binding=bound, intent_id='synthetic-intent', authorize=lambda cur: self.cluster.now() + 5)
        self.assertEqual(self.row(permit), ('blocked', True), 'lifting the hold does not revive it')

    def test_the_same_permit_is_consumed_when_nothing_began(self):
        permit, bound, path = self.sealed('no-hold')
        self.s.consume(permit, 'POST', path, binding=bound, intent_id='synthetic-intent', authorize=lambda cur: self.cluster.now() + 5)
        self.assertEqual(self.row(permit), ('sent', False))

    def test_an_unbound_permit_is_stopped_too(self):
        path = '/guilds/700000000000000009'
        permit = self.s.reserve('GET', path, identity=self.identity)
        self.hold()
        with self.assertRaises(RateDelayed) as caught:
            self.s.consume(permit, 'GET', path)
        self.assertEqual(caught.exception.rate_cause, 'hold')
        self.assertEqual(self.row(permit), ('blocked', True))

    def test_an_embargo_that_begins_after_the_reservation_stops_it_for_what_is_left(self):
        permit, bound, path = self.sealed('embargoed')
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET blocked_until=clock_timestamp()+interval '4 seconds' "
                       "WHERE kind='route' AND scope_key IN (SELECT unnest(scope_keys) FROM public.pr_discord_request_admissions WHERE id=%s::uuid)",
                       (permit.id,))
        with self.assertRaises(RateDelayed) as caught:
            self.s.consume(permit, 'POST', path, binding=bound, intent_id='synthetic-intent', authorize=lambda cur: self.cluster.now() + 5)
        self.assertEqual(caught.exception.rate_cause, 'permit_blocked')
        self.assertTrue(3.0 < caught.exception.retry_after_seconds <= 4.0, caught.exception.retry_after_seconds)
        self.assertEqual(self.row(permit), ('blocked', True))


if __name__ == '__main__':
    unittest.main()
