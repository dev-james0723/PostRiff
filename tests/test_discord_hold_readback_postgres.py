"""Real-PostgreSQL proof that an operator hold does not cost a created post its read-back (B4, the ops review's H1).

A post that Discord already accepted waits for a read-back that confirms it. The existing minute worker does not stop on the
hold by itself: it claims that read-back, the coordinator refuses the read, and the refusal used to be an unavailability.
The read-back took it for an answer it could not read (`uncertain`), kept the check it had spent, came back five seconds
later, and after the fifth refusal (about 25 seconds of hold) parked the post for a day: "Manual provider review required".
A read under a hold is now a wait the read-back already knows how to defer: the check is refunded, the post stays
`provider_accepted`, the next attempt is five minutes away, and the first attempt after the release confirms it.

The disposable cluster and the mock Discord are tests/discord_lane_fixture.py's. Runs where POSTRIFF_PG_BIN names the
PostgreSQL server binaries; reads no credential and touches no other database. Synthetic tenants only.
"""
import json
import time
import unittest

import discord_lane_fixture as F

HOLD_WAIT = 300           # seconds a read refused by a hold is told to wait (rate_limits.HOLD_WAIT_SECONDS)
ATTEMPTS = 8              # more than the five checks a post has, so the old behaviour has parked it by then


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class HoldAndReadBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def start(self):
        tenants = [F.Tenant(0)]
        F.seed(self.cluster, tenants, 1)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        self.worker = F.base_worker(self.cluster, self.hosted)

    def hold(self, value=True):
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET manual_hold=%s WHERE kind='policy'", (value,))

    def the_job(self):
        (job,) = F.jobs(self.cluster).values()
        return job

    def make_due(self):
        """Skip the wait the worker asked for, as a few minutes of the hold would."""
        with self.cluster.connect(autocommit=True) as db:
            for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
                for job in state['phase2']['jobs']:
                    job['nextAt'] = 0
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                           (json.dumps(state), workspace))

    def tick(self):
        with F.no_billing():
            self.worker.tick_discord(1, 10)
        return self.the_job()

    def test_a_created_post_waiting_for_its_read_back_survives_a_hold_of_several_minutes_and_is_read_back_after_the_release(self):
        self.start()
        job = self.tick()                                       # the create; its read-back is due five seconds later
        self.assertEqual(job['state'], 'provider_accepted', 'the post was created and is waiting to be confirmed')
        self.assertEqual(len(self.wire.requests(method='POST')), 1)
        self.hold()
        sent_before = len(self.wire.calls)
        for attempt in range(ATTEMPTS):                         # eight claims, one per five minutes of hold
            self.make_due()
            before = time.time()
            job = self.tick()
            where = 'attempt %d under the hold' % (attempt + 1)
            self.assertEqual(job['state'], 'provider_accepted', where)
            self.assertEqual(job.get('checks', 0), 0, where + ': the check the claim spent was refunded')
            self.assertNotIn('Manual provider review', job.get('nextAction') or '', where)
            self.assertAlmostEqual(job['nextAt'] - before, HOLD_WAIT, delta=30, msg=where + ': five minutes away, not a day')
            self.assertEqual(job.get('discordReadDeferrals', 0), attempt + 1, where)
            self.assertEqual(len(self.wire.calls), sent_before, where + ': nothing reached Discord under the hold')
        self.hold(False)
        self.make_due()
        job = self.tick()
        self.assertEqual(job['state'], 'verified', 'the first attempt after the release confirms the post')
        self.assertEqual(len(self.wire.requests(method='POST')), 1, 'and it was created once')
        self.assertEqual(self.wire.duplicates(), 0)


if __name__ == '__main__':
    unittest.main()
