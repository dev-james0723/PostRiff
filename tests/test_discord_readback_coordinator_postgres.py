"""Real-PostgreSQL proof that a process without a usable request coordinator does not cost a created post its read-back (N-1).

The runbook's second lever is a build whose reviewed rate policy does not parse: the process has no coordinator (oauth.py leaves no
limiter and marks it degraded) and every Discord request is refused before it is built. The reviewer expected "nothing held,
parked or marked uncertain". For a post that was not yet created that is so: it is released unsent and tried again in five
minutes. For a post that Discord had already accepted it was not: its read-back was refused the same way, took the refusal for an
answer it could not read (`uncertain`), kept the check each claim spent, and after the fifth claim parked the post for a day
("Manual provider review required"), still parked after the coordinator came back. Now the exact lookup waits: the receipt is
kept, the check is refunded, the next attempt is five minutes away, and the first attempt after the coordinator returns confirms
the post. The same holds when the coordinator exists but cannot reach its database. Nothing that creates changes: with no
coordinator no create leaves, no preflight read reaches Discord, and nothing is posted twice.

The disposable cluster and the mock Discord are tests/discord_lane_fixture.py's. Runs where POSTRIFF_PG_BIN names the PostgreSQL
server binaries; reads no credential and touches no other database. Synthetic tenants only.
"""
import json
import time
import unittest

import discord_lane_fixture as F

WAIT = 300                # seconds a read-back is told to wait (rate_limits.COORDINATOR_WAIT_SECONDS)
ATTEMPTS = 8              # more than the five checks a post has, so the old behaviour has parked it by then


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class ReadBackWithoutACoordinator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def start(self, tenants=1):
        tenants = [F.Tenant(n) for n in range(tenants)]
        F.seed(self.cluster, tenants, 1)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        self.worker = F.base_worker(self.cluster, self.hosted)
        self.provider = self.hosted.providers['discord']

    def lose_the_coordinator(self):
        """What oauth.py sets when SharedPostgresBudget refuses the reviewed policy."""
        self.saved = self.provider.rate_limiter
        self.provider.rate_limiter, self.provider.rate_coordinator_degraded = None, True

    def take_its_database_away(self):
        import psycopg
        self.saved = self.provider.rate_limiter.connection_factory

        def down():
            raise psycopg.OperationalError('synthetic: the coordinator\'s database is not reachable')
        self.provider.rate_limiter.connection_factory = down

    def restore(self):
        if callable(self.saved):
            self.provider.rate_limiter.connection_factory = self.saved
        else:
            self.provider.rate_limiter, self.provider.rate_coordinator_degraded = self.saved, False

    def jobs(self):
        return list(F.jobs(self.cluster).values())

    def make_due(self):
        """Skip the wait the worker asked for, as a few minutes of it would."""
        with self.cluster.connect(autocommit=True) as db:
            for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
                for job in state['phase2']['jobs']:
                    job['nextAt'] = 0
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                           (json.dumps(state), workspace))

    def tick(self, steps=5):
        with F.no_billing():
            self.worker.tick_discord(steps, 10)
        return self.jobs()

    def created(self, jobs):
        return [job for job in jobs if job.get('providerReference')]

    def waits(self, job, attempt):
        where = 'attempt %d without a coordinator' % attempt
        self.assertEqual(job['state'], 'provider_accepted', where)
        self.assertEqual(job.get('checks', 0), 0, where + ': the check the claim spent was refunded')
        self.assertNotIn('Manual provider review', job.get('nextAction') or '', where)
        self.assertAlmostEqual(job['nextAt'] - time.time(), WAIT, delta=30, msg=where + ': five minutes away, not a day')
        self.assertEqual(job.get('discordReadDeferrals', 0), attempt, where)

    def survives(self, lose, restore_message):
        self.start()
        (job,) = self.tick(steps=1)                             # the create; its read-back is due five seconds later
        self.assertEqual(job['state'], 'provider_accepted', 'the post was created and is waiting to be confirmed')
        self.assertEqual(len(self.wire.requests(method='POST')), 1)
        lose()
        reached = len(self.wire.calls)
        for attempt in range(1, ATTEMPTS + 1):
            self.make_due()
            (job,) = self.tick()
            self.waits(job, attempt)
            self.assertEqual(len(self.wire.calls), reached, 'attempt %d: nothing reached Discord' % attempt)
        self.restore()
        self.make_due()
        (job,) = self.tick()
        self.assertEqual(job['state'], 'verified', restore_message)
        self.assertEqual(len(self.wire.requests(method='POST')), 1, 'and it was created once')
        self.assertEqual(self.wire.duplicates(), 0)

    def test_a_created_post_waits_for_its_read_back_while_the_process_has_no_coordinator(self):
        self.survives(self.lose_the_coordinator, 'the first attempt after the coordinator is back confirms the post')

    def test_a_created_post_waits_for_its_read_back_while_the_coordinators_database_is_down(self):
        self.survives(self.take_its_database_away, 'the first attempt after the database is back confirms the post')

    def test_posts_not_created_yet_still_wait_and_nothing_is_created_without_a_coordinator(self):
        self.start(tenants=2)
        jobs = self.tick(steps=1)                               # one step: one of the two posts is created
        (done,) = [job for job in jobs if job['state'] == 'provider_accepted']
        self.assertEqual(len(self.wire.requests(method='POST')), 1, 'one post was created before the coordinator went')
        self.lose_the_coordinator()
        reached = len(self.wire.calls)
        for attempt in range(1, ATTEMPTS + 1):
            self.make_due()
            jobs = self.tick()
            (still_created,) = self.created(jobs)
            self.waits(still_created, attempt)
            (unsent,) = [job for job in jobs if not job.get('providerReference')]
            self.assertEqual(unsent['state'], 'scheduled', 'the other post is released unsent, not held or uncertain')
            self.assertFalse(unsent.get('discordDispatchIntents'), 'no intent was sealed')
            self.assertEqual(len(self.wire.requests(method='POST')), 1, 'and nothing was created without a coordinator')
            self.assertEqual(len(self.wire.calls), reached, 'no preflight read reached Discord either')
        self.restore()
        for _ in range(4):
            self.make_due()
            jobs = self.tick()
        self.assertEqual(sorted(job['state'] for job in jobs), ['verified', 'verified'], 'both posts are confirmed once it is back')
        self.assertEqual(len(self.wire.requests(method='POST')), 2, 'each created once')
        self.assertEqual(self.wire.duplicates(), 0)


if __name__ == '__main__':
    unittest.main()
