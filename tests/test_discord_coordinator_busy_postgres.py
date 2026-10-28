"""Real-PostgreSQL proof that a database that is slow does not become a coordinator that is gone (the independent review's NEW-1,
G2E-B-09): a reservation that cannot get the application row's lock within lock_timeout (2 s) was rolled back, admitted nothing and
sent nothing, and is a RateDelayed of 1.5 s with cause `coordinator_busy` (it was a RateCoordinatorUnavailable, which a worker turns
into a 300-second release of the post); a read through the provider is released after that short wait with nothing sent; and the
process is not disabled for good by it.

A disposable cluster (tests/discord_lane_fixture.py), the repository's schema, the real coordinator and DiscordProvider, Discord as
the in-process mock. Runs where POSTRIFF_PG_BIN names the PostgreSQL server binaries; synthetic ids only, no network.
"""
import time
import unittest

import discord_lane_fixture as F
from postriff_phase2.discord.rate_limits import BUSY_WAIT_SECONDS, RateCoordinatorUnavailable, RateDelayed, ReadAdmissionDelayed
from test_discord_rate_ceiling_postgres import Stack


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class BusyOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()
        self.stack = Stack(self.cluster, capacity=25, tenants=3)
        self.stack.read(0)                                  # the rows exist

    def admissions(self):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute('SELECT count(*) FROM public.pr_discord_request_admissions WHERE application_key=%s', (self.stack.key,)).fetchone()[0]

    def test_a_reservation_that_cannot_get_the_application_row_in_time_is_a_short_wait_and_admits_nothing(self):
        before = self.admissions()
        with self.cluster.connect() as holder:
            holder.execute("SELECT 1 FROM public.pr_discord_rate_state WHERE kind='policy' FOR UPDATE")   # another reservation's lock
            began = time.monotonic()
            with self.assertRaises(RateDelayed) as caught:
                self.stack.limiter.reserve_read('GET', '/guilds/%s' % self.stack.tenants[0].guild, identity=self.stack.identity)
            took = time.monotonic() - began
            holder.rollback()
        error = caught.exception
        self.assertNotIsInstance(error, RateCoordinatorUnavailable)
        self.assertEqual((error.rate_cause, error.rate_scope_kind, error.retry_after_seconds), ('coordinator_busy', 'application', BUSY_WAIT_SECONDS))
        self.assertTrue(1.5 < took < 6, 'it waited for the lock for its lock_timeout (2 s) and no longer: %.2f' % took)
        self.assertEqual(self.admissions(), before, 'nothing was admitted')
        self.stack.limiter.observe(self.stack.limiter.reserve_read('GET', '/guilds/%s' % self.stack.tenants[0].guild, identity=self.stack.identity),
                                   {'status': 200, 'headers': {}, 'body': {}})   # the lock is free again: the next one is admitted

    def test_a_read_through_the_provider_is_released_after_the_short_wait_nothing_is_sent_and_the_process_is_not_disabled(self):
        sent = len(self.stack.wire.calls)
        with self.cluster.connect() as holder:
            holder.execute("SELECT 1 FROM public.pr_discord_rate_state WHERE kind='policy' FOR UPDATE")
            with self.assertRaises(ReadAdmissionDelayed) as caught:
                self.stack.read(1)
            holder.rollback()
        self.assertEqual((caught.exception.rate_cause, caught.exception.retry_after_seconds), ('coordinator_busy', BUSY_WAIT_SECONDS))
        self.assertEqual(len(self.stack.wire.calls), sent, 'nothing reached Discord')
        self.assertFalse(self.stack.provider.rate_coordinator_degraded)
        self.stack.read(2)                                  # and the very next read of the same process goes through


if __name__ == '__main__':
    unittest.main()
