"""The lane with booking, on real PostgreSQL (docs/w02/OPEN-QUESTIONS.md Q19; docs/w02/AMPLIFICATION.md section 3).

The W-02 lane over a disposable cluster and the in-process mock Discord, twelve (sixteen) loops at an application window they
keep full. What booking must give: a pass is not thrown away at a refusal (about one pass per post), nothing is sent twice,
the wire stays within the cap, and what can happen while a booked read waits does not reach Discord or a post: an approval
that ends, a loop that dies, a pause. The seal-to-consume interval (F5) never contains a sleep.

Capacity. The capacity of the shared box limits what is *reachable* here (twelve loops and the coordinator in one Python process);
the cap of these tests is chosen so that the window, not the lock, binds, and so that the loops fit the booked horizon. The horizon
holds about (cap - 1) / 1.1 callers (each loop holds one booking at a time and a slot is a window plus its headroom, 1.1 s), fewer
while create permits are outstanding. Beyond that the lane does not degrade a little: its passes are refused at the horizon, released
and repeated, and almost nothing is created (4 loops at a cap of 4 took 216 s for 12 posts, 3 loops at a cap of 4 made 202 requests
for each post they finished; polling took 60 s). OPEN-QUESTIONS Q19 has the measured edge. At the owner's cap of 25 the horizon
holds about 22 loops; the lane keeps 12 shards.

Runs where POSTRIFF_PG_BIN names the PostgreSQL server binaries; synthetic tenants only, no network.
"""
import threading
import time
import unittest
from unittest.mock import patch

import discord_lane_fixture as F
from postriff_phase2.discord import rate_limits, worker as discord_worker
from postriff_phase2.discord.rate_limits import SharedPostgresBudget
from test_discord_rate_ceiling_postgres import busiest_closed

SETTLED = ('verified', 'held', 'uncertain', 'failed')


class WorkerDied(BaseException):
    """The process is gone (not an Exception: nothing in the lane may catch it)."""


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class LaneBookingOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def start(self, tenants, posts, *, capacity=14, latency=.1, **seeded):
        F.seed(self.cluster, tenants, posts, **seeded)
        self.wire = F.MockDiscord(tenants, ceiling=capacity, latency=latency)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=capacity)
        self.worker = F.base_worker(self.cluster, self.hosted)
        self.limiter = self.hosted.providers['discord'].rate_limiter
        return self.worker

    def drain(self, loops, *, seconds, rounds=5):
        results = []
        for _ in range(rounds):
            found, failures = F.run_lanes(self.worker, loops, seconds=seconds)
            self.assertEqual(failures, [])
            results.extend(found)
            if all(job['state'] in SETTLED for job in F.jobs(self.cluster).values()):
                break
        return results

    def make_due(self):
        import json
        with self.cluster.connect(autocommit=True) as db:
            for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
                for job in state['phase2']['jobs']:
                    job['nextAt'] = 0
                    job.get('discordWorker', {}).pop('rateDelayedUntil', None)
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))

    def passes_per_post(self):
        guild_reads = [c for c in self.wire.calls if c[1] == 'GET' and len(c[2].strip('/').split('/')) == 2 and c[2].startswith('/guilds/')]
        return len(guild_reads) / max(1, len(self.wire.requests(method='POST')))

    def stamps(self):
        with self.cluster.connect(autocommit=True) as db:
            return [row[0] for row in db.execute(
                'SELECT (extract(epoch from coalesce(sent_at,reserved_at))*1000000)::bigint '
                'FROM public.pr_discord_request_admissions ORDER BY request_seq')]

    def verified_once(self, expected):
        found = F.jobs(self.cluster)
        self.assertEqual(len(found), expected)
        self.assertEqual(sorted({job['state'] for job in found.values()}), ['verified'])
        for job in found.values():
            self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1, 'one create per approval')
        self.assertEqual(self.wire.duplicates(), 0)

    # (f) (g) the lane at a window it keeps full -------------------------------------------------------------------------

    def saturated(self, loops, capacity, tenants=40, posts=3):
        self.start([F.Tenant(n) for n in range(tenants)], posts, capacity=capacity)
        results = self.drain(loops, seconds=60)
        self.verified_once(tenants * posts)
        counters = {key: sum(r['counters'][key] for r in results) for key in ('rateDelayed', 'permitWaits', 'bookedWaits', 'bookedSeconds')}
        self.assertEqual(self.wire.route429, 0)
        self.assertLessEqual(busiest_closed(self.stamps(), 1.0), capacity, 'the ceiling on the database clock')
        self.assertLessEqual(self.wire.peak_second, capacity + 2, 'and at the mock, within the headroom\'s room for a stalled box')
        return counters

    def test_twelve_loops_at_a_full_window_make_about_one_pass_per_post_and_never_post_twice(self):
        counters = self.saturated(12, capacity=14)
        self.assertGreater(counters['bookedWaits'], 20, 'the window was full often enough to book')
        self.assertLessEqual(self.passes_per_post(), 1.1, counters)
        self.assertLessEqual(counters['rateDelayed'], 12, 'releases are rare: only the horizon can refuse')

    def test_sixteen_loops_do_the_same_with_the_cap_they_need(self):
        """Sixteen loops hold sixteen bookings; a horizon of one second holds 0.9 x cap of them, so the cap that carries
        them is 18. Twenty-four loops need about 27 (the owner's 25 carries 22): documented, not asserted."""
        counters = self.saturated(16, capacity=18, tenants=48)
        self.assertGreater(counters['bookedWaits'], 20)
        self.assertLessEqual(self.passes_per_post(), 1.25, counters)

    # (h) an approval that ends inside a pass ----------------------------------------------------------------------------

    def test_an_approval_ending_inside_a_pass_of_booked_reads_is_held_and_never_sent_late(self):
        tenants = [F.Tenant(n) for n in range(14)]
        expiry = self.cluster.now() + 8
        at = expiry - 3600
        self.start(tenants, 1, capacity=6, latency=.02, now=at - 300, at=at)
        F.run_lanes(self.worker, 3, seconds=30)
        found = F.jobs(self.cluster)
        with self.cluster.connect(autocommit=True) as db:
            rows = db.execute("SELECT workspace_id::text, publication_id, extract(epoch from sent_at)::double precision "
                              "FROM public.pr_discord_request_admissions WHERE is_publish AND sent_at IS NOT NULL").fetchall()
        released = {(workspace, publication): sent for workspace, publication, sent in rows}
        for key, job in found.items():
            created = self.wire.creates.get(F.nonce(job), [])
            if key in released:
                self.assertLess(released[key], job['manifest']['expiresAt'] + 1.0, 'nothing is released after its approval ended')
            elif job['state'] != 'verified':
                self.assertEqual(created, [], 'a post that did not leave was never created')
        states = [job['state'] for job in found.values()]
        self.assertGreater(states.count('held'), 0, 'the queue outlasted some approvals')
        self.assertGreater(states.count('verified'), 0)
        self.assertEqual(self.wire.duplicates(), 0)
        self.assertGreater(self.limiter.booking_stats()['bookings'], 0)

    # (i) a loop killed inside a booked sleep ----------------------------------------------------------------------------

    def test_a_loop_killed_inside_a_booked_sleep_sends_nothing_and_a_later_claim_sends_once(self):
        tenants = [F.Tenant(n) for n in range(3)]
        self.start(tenants, 1, capacity=6, latency=.02)
        for number in range(6):                                   # a full window: the first read must wait for its slot
            permit = self.limiter.reserve_read('GET', '/guilds/%d' % (710000000000000500 + number), identity=self.hosted.providers['discord']._rate_identity('bot'))
            self.limiter.observe(permit, {'status': 200, 'headers': {}})
            time.sleep(.05)
        died = []

        def die(seconds):
            died.append(seconds)
            raise WorkerDied()
        with patch.object(self.limiter, '_sleep', die), patch.object(discord_worker, 'LEASE_SECONDS', 3):
            _, failures = F.run_lanes(self.worker, 1, seconds=20)
            self.assertEqual([type(error) for _, error in failures], [WorkerDied])
        self.assertTrue(died, 'it died while waiting for a booked slot')
        self.assertEqual(self.wire.requests(method='POST'), [], 'nothing was created')
        self.assertEqual(len(self.wire.calls), 0, 'and not even the booked read reached Discord')
        time.sleep(3.5)                                           # the dead loop's lease expires; nobody renews it
        results, failures = F.run_lanes(self.worker, 3, seconds=45)
        self.assertEqual(failures, [])
        self.drain(3, seconds=45)
        self.verified_once(3)

    # (j) F5: no sleep between the seal and the consume ------------------------------------------------------------------

    def test_no_sleep_happens_between_the_seal_and_the_consume(self):
        tenants = [F.Tenant(n) for n in range(6)]
        self.start(tenants, 2, capacity=8, latency=.02)             # four loops fit the horizon of a cap of 8 (about 6)
        state = threading.local()
        violations, seals, consumes = [], [], []
        seal, consume, sleep = SharedPostgresBudget.seal, SharedPostgresBudget.consume, self.limiter._sleep

        def sealed(limiter, *args, **kwargs):
            result = seal(limiter, *args, **kwargs)
            state.gap = True
            seals.append(1)
            return result

        def consumed(limiter, *args, **kwargs):
            state.gap = False
            consumes.append(1)
            return consume(limiter, *args, **kwargs)

        def sleeping(seconds):
            if getattr(state, 'gap', False):
                violations.append(seconds)
            return sleep(seconds)
        with patch.object(SharedPostgresBudget, 'seal', sealed), patch.object(SharedPostgresBudget, 'consume', consumed), \
                patch.object(self.limiter, '_sleep', sleeping):
            self.drain(4, seconds=40)
        self.verified_once(12)
        self.assertGreaterEqual(len(seals), 12)
        self.assertGreaterEqual(len(consumes), 12)
        self.assertGreater(self.limiter.booking_stats()['bookings'], 0, 'the run did sleep for slots')
        self.assertEqual(violations, [], 'a sleep in the seal-to-consume interval would spend the permit F5 left it')

    # (k) a pause while a read waits for its slot ------------------------------------------------------------------------

    def test_a_pause_while_reads_wait_for_their_slots_claims_nothing_new_and_leaves_every_post_as_it_was(self):
        tenants = [F.Tenant(n) for n in range(16)]
        self.start(tenants, 2, capacity=8, latency=.05)
        provider = self.hosted.providers['discord']
        claims, paused_at = [], []
        from postriff_phase2.discord import lane
        claim = lane.LaneWorker.claim

        def counted(worker, **options):
            claims.append(time.monotonic())
            return claim(worker, **options)

        def pause():
            time.sleep(2.5)
            provider.execution_enabled = False
            paused_at.append(time.monotonic())
        timer = threading.Thread(target=pause)
        with patch.object(lane.LaneWorker, 'claim', counted):
            timer.start()
            results, failures = F.run_lanes(self.worker, 4, seconds=30)
            timer.join()
        self.assertEqual(failures, [])
        self.assertTrue(paused_at)
        self.assertEqual({r['stoppedBy'] for r in results}, {'discord_paused'})
        late = [at for at in claims if at > paused_at[0] + .5]
        self.assertEqual(late, [], 'nothing new was claimed after the pause')
        held = set()
        for key, job in F.jobs(self.cluster).items():
            if job['state'] == 'held':
                held.add(key)
                continue
            self.assertIn(job['state'], ('scheduled', 'provider_accepted', 'verified'), 'a pause is a wait, not a verdict about a post')
        # The one thing a pause can still do to a post (the existing rule for the kill switch, AS-BUILT "A paused Discord is a wait"):
        # it lands after a loop has sealed its intent and the create is refused at the transport. That post is held with nothing
        # posted, and there can be at most one for each loop.
        self.assertLessEqual(len(held), 4)
        for key in held:
            job = F.jobs(self.cluster)[key]
            self.assertEqual(job['events'][-1]['message'], 'Discord transport is unavailable. Nothing was posted.')
            self.assertEqual(self.wire.creates.get(F.nonce(job), []), [], 'and nothing was posted')
        self.assertEqual(self.wire.duplicates(), 0)
        provider.execution_enabled = True                         # and when it is lifted everything goes through, once
        self.make_due()                                           # (the step each loop had in flight was released with a cooldown)
        self.drain(4, seconds=45)
        found = F.jobs(self.cluster)
        self.assertEqual(len(found), 32)
        for key, job in found.items():
            if key in held:
                self.assertEqual(job['state'], 'held', 'a held post needs a new approval; the pause lifting does not send it')
                continue
            self.assertEqual(job['state'], 'verified')
            self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1, 'one create per approval')
        self.assertEqual(self.wire.duplicates(), 0)

if __name__ == '__main__':
    unittest.main()
