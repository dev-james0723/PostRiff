"""Real-PostgreSQL proof of the W-02 Discord lane with many concurrent loops (synthetic tenants, mock Discord).

Each test starts the lane the way K cron shards would: K loops at once over the repository's own schema, triggers,
leases and shared request coordinator, against an in-process Discord that answers with rate-limit headers and counts
every create by its nonce. Properties: every post is created exactly once and verified, including when a loop dies
mid-step and when loops race on one workspace; the coordinator caps the request rate across all loops; one busy
workspace cannot starve the others and a channel's create limit holds; an approval that expires while its post waits
is held and never sent late; an operator hold stops every loop within one iteration; a global 429 pauses every loop
without a retry storm; each loop holds one database connection at a time.

Runs where PostgreSQL server binaries are named by POSTRIFF_PG_BIN. It starts its own disposable cluster and never
reads application credentials or touches any other database. It does not run under the synthetic transport fence
(RAFII_DISCORD_SYNTHETIC_FENCE), which by design refuses every database but the guarded runner's own.
"""
import json
import time
import unittest
from unittest.mock import patch

import discord_lane_fixture as F
from postriff_phase2.discord import worker as discord_worker


class WorkerDied(BaseException):
    """A process that stops mid-step: nothing after this point runs; its open transaction rolls back."""


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class ParallelLaneOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def start(self, tenants, posts, *, capacity=200, ceiling=None, latency=0.0, tracker=None, **seeded):
        F.seed(self.cluster, tenants, posts, **seeded)
        self.wire = F.MockDiscord(tenants, ceiling=ceiling, latency=latency)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=capacity, tracker=tracker)
        self.worker = F.base_worker(self.cluster, self.hosted, tracker)
        return self.worker

    def assert_each_created_once_and_verified(self, expected):
        found = F.jobs(self.cluster)
        self.assertEqual(len(found), expected)
        self.assertEqual(sorted({job['state'] for job in found.values()}), ['verified'])
        for job in found.values():
            self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1, 'one create per approval')
            self.assertEqual(len(job['discordDispatchIntents']), 1)
            self.assertIsNone(job['leaseOwner'])
        self.assertEqual(self.wire.duplicates(), 0)
        self.assertEqual(len(self.wire.requests(method='POST')), expected)
        return found

    # (a) exactly once with many loops ---------------------------------------------------------------------------

    def test_many_loops_create_every_post_exactly_once(self):
        tenants = [F.Tenant(n) for n in range(24)]
        worker = self.start(tenants, 5)
        results, failures = F.run_lanes(worker, 8, seconds=60)
        self.assertEqual(failures, [])
        self.assert_each_created_once_and_verified(120)
        self.assertEqual(sum(r['counters']['posted'] for r in results), 120)
        self.assertEqual(sum(r['counters']['verified'] for r in results), 120)
        self.assertEqual({r['stoppedBy'] for r in results}, {'idle'})
        self.assertEqual(self.wire.route429, 0)

    def test_loops_racing_on_one_workspace_send_one_post_at_a_time(self):
        tenant = F.Tenant(0)
        worker = self.start([tenant], 10)
        live = []

        def watch(method, path, answer):
            if method == 'POST':
                with self.cluster.connect(autocommit=True) as db:
                    state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (tenant.id,)).fetchone()[0]
                live.append(sum(1 for job in state['phase2']['jobs']
                                if job.get('leaseOwner') and job.get('leaseUntil', 0) > time.time()))
        self.wire.after = watch
        results, failures = F.run_lanes(worker, 6, seconds=90)
        self.assertEqual(failures, [])
        self.assert_each_created_once_and_verified(10)
        self.assertEqual(set(live), {1}, 'at most one live Discord lease per workspace, whatever the loop count')

    def crash_once(self, method, suffix, *, nth=2, before=True, posts=3, recover=60):
        """Kill the loop at the `nth` matching request (`before` Discord sees it, or after Discord answered it),
        then let fresh loops recover after the dead loop's lease expires. The second request of a kind finds its
        route already learned, the way almost every request in production does (see the cold-route test below)."""
        tenant = F.Tenant(0)
        worker = self.start([tenant], posts)
        seen = []

        def hook(m, path, answer=None):
            if m == method and path.endswith(suffix):
                seen.append(path)
                if len(seen) == nth:
                    raise WorkerDied()
        if before:
            self.wire.fail = hook
        else:
            self.wire.after = hook
        with patch.object(discord_worker, 'LEASE_SECONDS', 3):
            _, failures = F.run_lanes(worker, 1, seconds=30)
            self.assertEqual([type(error) for _, error in failures], [WorkerDied])
            time.sleep(3.5)  # the dead loop's lease expires; nobody renews it
            self.wire.fail = self.wire.after = None
            results, failures = F.run_lanes(worker, 3, seconds=recover)
        self.assertEqual(failures, [])
        return F.jobs(self.cluster)

    def test_a_loop_that_dies_before_its_intent_is_recovered_and_sent_once(self):
        found = self.crash_once('GET', '/channels')
        self.assertEqual(sorted(job['state'] for job in found.values()), ['verified'] * 3)
        for job in found.values():
            self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1)
        recovered = [job for job in found.values() if job['discordWorker'].get('recoveries')]
        self.assertEqual(len(recovered), 1, 'the dead fence was released as provably unsent, then sent once')

    def test_a_loop_that_dies_after_discord_accepted_never_causes_a_second_post(self):
        found = self.crash_once('POST', '/messages', before=False)
        self.assertEqual(self.wire.duplicates(), 0)
        states = sorted(job['state'] for job in found.values())
        self.assertEqual(states, ['uncertain', 'verified', 'verified'])
        lost = next(job for job in found.values() if job['state'] == 'uncertain')
        self.assertEqual(len(self.wire.creates[F.nonce(lost)]), 1, 'the receipt was lost; the post was not repeated')
        self.assertEqual(len(lost['discordDispatchIntents']), 1, 'its sealed intent stays for manual reconciliation')
        self.assertEqual(sum(len(v) for v in self.wire.creates.values()), 3)

    def test_a_loop_that_dies_as_its_create_leaves_never_reposts_it(self):
        found = self.crash_once('POST', '/messages')
        lost = next(job for job in found.values() if job['state'] == 'uncertain')
        self.assertEqual(self.wire.creates.get(F.nonce(lost), []), [], 'held for manual reconciliation, never re-posted')
        self.assertEqual(sorted(job['state'] for job in found.values()), ['uncertain', 'verified', 'verified'])
        self.assertEqual(self.wire.duplicates(), 0)

    def test_a_loop_that_dies_inside_the_first_request_of_a_route_leaves_that_route_waiting_for_review(self):
        """Existing conservative rule, recorded here: the dead request's admission is never observed, so the
        route's one-request probe stays spent and later posts to that channel wait (unsent, never failed) until
        an operator reviews the admission (docs/w02/monitoring.sql M5). Nothing is sent twice."""
        found = self.crash_once('POST', '/messages', nth=1, before=False, recover=12)
        states = sorted(job['state'] for job in found.values())
        self.assertEqual(states, ['scheduled', 'scheduled', 'uncertain'])
        self.assertEqual(sum(len(v) for v in self.wire.creates.values()), 1)
        self.assertFalse([job for job in found.values() if job['state'] == 'scheduled' and job.get('discordDispatchIntents')])
        with self.cluster.connect(autocommit=True) as db:
            stale = db.execute("SELECT count(*) FROM public.pr_discord_request_admissions WHERE state='sent' "
                               "AND sent_at<clock_timestamp()-interval '3 seconds'").fetchone()[0]
        self.assertEqual(stale, 1)

    # (b) the shared request coordinator caps every loop together ------------------------------------------------

    def rate_run(self, capacity):
        tenants = [F.Tenant(n) for n in range(40)]
        worker = self.start(tenants, 2, capacity=capacity, ceiling=2 * 10)
        started = time.monotonic()
        F.run_lanes(worker, 12, seconds=12)
        return time.monotonic() - started

    def test_the_coordinator_caps_the_request_rate_across_all_loops(self):
        elapsed = self.rate_run(10)
        calls = self.wire.calls
        self.assertGreater(len(calls), 60, 'the run was busy enough to meet the cap')
        # Fixed one-second windows: any trailing second holds at most two windows' worth.
        self.assertLessEqual(self.wire.peak_second, 20)
        self.assertEqual(self.wire.over_ceiling, 0)
        span = calls[-1][0] - calls[0][0]
        self.assertLessEqual(len(calls), 10 * (span + 2), 'never above the policy on average')
        self.assertEqual(self.wire.duplicates(), 0)
        self.assertLess(elapsed, 12 + 30)

    def test_control_the_same_run_exceeds_that_ceiling_when_the_policy_allows_it(self):
        self.rate_run(1000)
        self.assertGreater(self.wire.over_ceiling, 0, 'so the capped run above is the coordinator doing the work')

    def admissions(self, reserve, count, offset=0):
        """`count` reservations on distinct cold resources (one probe each), so only the application budget binds."""
        from postriff_phase2.discord.rate_limits import RateDelayed
        limiter = self.hosted.providers['discord'].rate_limiter
        identity = self.hosted.providers['discord']._rate_identity('bot')
        admitted = 0
        for number in range(count):
            try:
                getattr(limiter, reserve)('GET', '/guilds/%d' % (6900000 + offset + number), identity=identity)
                admitted += 1
            except RateDelayed:
                pass
        return admitted

    def test_permits_of_a_dead_loop_that_were_never_used_free_their_slots(self):
        self.start([F.Tenant(0)], 0, capacity=3)
        self.assertEqual(self.admissions('reserve', 4), 3)  # a dead loop's three permits fill the window
        time.sleep(1.2)  # they were never consumed, so the next window does not count them
        self.assertEqual(self.admissions('reserve', 4, offset=10), 3)

    def test_a_read_whose_process_died_after_admission_keeps_its_slot_until_reviewed(self):
        """Existing conservative rule, recorded here: a spent admission with no observed answer keeps one slot."""
        self.start([F.Tenant(0)], 0, capacity=3)
        self.assertEqual(self.admissions('reserve_read', 1), 1)  # admitted as sent; the answer is never observed
        time.sleep(1.2)
        self.assertEqual(self.admissions('reserve_read', 3, offset=10), 2)
        with self.cluster.connect(autocommit=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_discord_request_admissions WHERE state='sent' "
                                        "AND sent_at<clock_timestamp()-interval '1 second'").fetchone()[0], 1)

    # (c) fairness and the per-channel limit ---------------------------------------------------------------------

    def fairness_run(self, loops, order=None):
        tenants = sorted((F.Tenant(n) for n in range(7)), key=lambda tenant: tenant.id)
        big, small = tenants[0], tenants[1:]  # the busy tenant sorts first by id
        F.seed(self.cluster, [big], 30)
        F.seed(self.cluster, small, 2)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire)
        worker = F.base_worker(self.cluster, self.hosted)
        if order:
            from postriff_phase2 import hosted_worker
            original = hosted_worker.due_workspaces_sql
            replaced = lambda *a, **k: original(*a, **k).replace('ORDER BY hint.last_claimed_at,w.id', 'ORDER BY w.id')
            with patch.object(hosted_worker, 'due_workspaces_sql', replaced):
                F.run_lanes(worker, loops, seconds=90)
        else:
            F.run_lanes(worker, loops, seconds=90)
        creates = sorted((at, channel) for times in self.wire.creates.values() for at, channel, _ in times)
        last_small = max(index for index, (_, channel) in enumerate(creates) if channel != big.channel)
        return sum(1 for _, channel in creates[:last_small] if channel == big.channel)

    def test_one_busy_workspace_cannot_starve_the_others(self):
        before = self.fairness_run(1)
        self.assertLessEqual(before, 8, 'every small tenant finished while the busy one sent only a few')
        self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])

    def test_control_without_the_rotation_one_loop_serves_the_busy_workspace_first(self):
        self.assertGreaterEqual(self.fairness_run(1, order='id'), 20)

    def test_posts_to_one_channel_keep_to_its_create_limit(self):
        # Six workspaces connected to the same server channel: the limit is the channel's, across tenants.
        tenants = [F.Tenant(n, guild='6100000', channel='7100000') for n in range(6)]
        worker = self.start(tenants, 3)
        F.run_lanes(worker, 6, seconds=90)
        self.assertEqual(self.wire.route429, 0, 'no create was refused by the channel limit')
        times = sorted(at for created in self.wire.creates.values() for at, _, _ in created)
        self.assertEqual(len(times), 18)
        self.assertGreaterEqual(times[-1] - times[0], 10, 'eighteen creates at five per five seconds')
        self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])
        self.assertEqual(self.wire.duplicates(), 0)

    # (d) an approval that expires while waiting ------------------------------------------------------------------

    def test_a_post_whose_approval_expires_while_waiting_is_held_and_never_sent_late(self):
        tenants = [F.Tenant(n) for n in range(14)]
        expiry = self.cluster.now() + 8
        at = expiry - 3600  # an approval lives one hour after its scheduled time
        self.start(tenants, 1, capacity=6, latency=.02, now=at - 300, at=at)
        F.run_lanes(self.worker, 3, seconds=30)
        found = F.jobs(self.cluster)
        for job in found.values():
            self.assertAlmostEqual(job['manifest']['expiresAt'], int(at) + 3600, delta=1)
            for _, _, wall in self.wire.creates.get(F.nonce(job), []):
                self.assertLess(wall, job['manifest']['expiresAt'], 'nothing is sent after its approval expired')
        states = [job['state'] for job in found.values()]
        self.assertGreater(states.count('held'), 0, 'the queue outlasted some approvals')
        self.assertGreater(states.count('verified'), 0)
        for job in found.values():
            if job['state'] != 'verified':
                self.assertEqual(self.wire.creates.get(F.nonce(job), []), [])
        self.assertEqual(self.wire.duplicates(), 0)

    # (e) the operator hold --------------------------------------------------------------------------------------

    def hold(self, value=True):
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET manual_hold=%s WHERE kind='policy'", (value,))

    def test_an_operator_hold_stops_every_loop_within_one_iteration(self):
        tenants = [F.Tenant(n) for n in range(30)]
        worker = self.start(tenants, 1)
        held_at = []

        def after(method, path, answer):
            if method == 'POST' and not held_at:
                self.hold()
                held_at.append(time.monotonic())
        self.wire.after = after
        results, failures = F.run_lanes(worker, 4, seconds=60)
        self.assertEqual(failures, [])
        self.assertEqual({r['stoppedBy'] for r in results}, {'operator_hold'})
        late = [call for call in self.wire.calls if call[1] == 'POST' and call[0] > held_at[0]]
        self.assertLessEqual(len(late), 4, 'at most the one step each loop already had in flight')
        found = F.jobs(self.cluster).values()
        self.assertFalse([job for job in found if job['state'] in ('failed', 'held')])
        untouched = [job for job in found if job['state'] == 'scheduled' and not job.get('attempts')]
        self.assertGreaterEqual(len(untouched), 30 - 4 * 3, 'queued posts wait; they are not held or spent')
        # Lifting the hold resumes the same approvals exactly once.
        self.hold(False)
        with self.cluster.connect(autocommit=True) as db:  # skip the five-minute wait of posts refused by the hold
            for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
                for job in state['phase2']['jobs']:
                    if job['state'] == 'scheduled':
                        job['nextAt'] = 0
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                           (json.dumps(state), workspace))
        self.wire.after = None
        F.run_lanes(worker, 4, seconds=60)
        # A hold also blocks every reserved-but-unused create permit (existing rule). A loop that was between
        # sealing and sending records its post as uncertain: nothing was sent, and it waits for manual review.
        found = F.jobs(self.cluster).values()
        stopped = [job for job in found if job['state'] != 'verified']
        self.assertLessEqual(len(stopped), 4)
        self.assertEqual({job['state'] for job in stopped} - {'uncertain'}, set())
        for job in found:
            self.assertLessEqual(len(self.wire.creates.get(F.nonce(job), [])), 1)
            if job['state'] == 'verified':
                self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1)
        self.assertEqual(self.wire.duplicates(), 0)

    def revisions(self):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute("SELECT sum(revision) FROM public.pr_workspaces WHERE state ? 'phase2'").fetchone()[0]

    def held_queue(self):
        worker = self.start([F.Tenant(n) for n in range(5)], 1)
        self.admissions('reserve_read', 1)  # the application scope row exists once any request was admitted
        self.hold()
        return worker

    def test_a_hold_set_before_the_minute_starts_claims_nothing(self):
        worker = self.held_queue()
        before, calls = self.revisions(), len(self.wire.calls)
        results, _ = F.run_lanes(worker, 3, seconds=10)
        self.assertEqual([r['stoppedBy'] for r in results], ['operator_hold'] * 3)
        self.assertEqual([r['counters']['claimed'] for r in results], [0, 0, 0])
        self.assertEqual(len(self.wire.calls), calls)
        self.assertEqual(self.revisions(), before, 'no workspace was even claimed')
        self.assertEqual({job['state'] for job in F.jobs(self.cluster).values()}, {'scheduled'})

    def test_control_the_existing_loop_claims_and_postpones_work_under_the_same_hold(self):
        worker = self.held_queue()
        before = self.revisions()
        with F.no_billing():
            worker.tick_discord(10, 10)
        self.assertGreater(worker.discord_stats['rateDelays'], 0)
        self.assertGreater(self.revisions(), before)
        found = F.jobs(self.cluster).values()
        self.assertTrue(all(job['nextAt'] > time.time() + 200 for job in found), 'each post pushed back five minutes')

    # (f) a global 429 ---------------------------------------------------------------------------------------------

    def embargo_run(self, loop):
        tenants = [F.Tenant(n) for n in range(30)]
        worker = self.start(tenants, 1)
        seen = []

        def fail(method, path):
            if not seen and method == 'GET' and path.endswith('/channels'):
                seen.append(time.monotonic())
                return {'status': 429, 'headers': {'retry-after': '4', 'x-ratelimit-global': 'true',
                                                   'x-ratelimit-scope': 'global'},
                        'body': {'message': 'You are being rate limited.', 'retry_after': 4, 'global': True}}
        self.wire.fail = fail
        loop(worker)
        return seen[0]

    def test_a_global_429_pauses_every_loop_without_a_retry_storm(self):
        started = self.embargo_run(lambda worker: F.run_lanes(worker, 4, seconds=40))
        during = [call for call in self.wire.calls if started < call[0] < started + 3.9]
        self.assertLessEqual(len(during), 3, 'inside the embargo only requests already admitted may still arrive')
        found = F.jobs(self.cluster).values()
        self.assertEqual(sorted({job['state'] for job in found}), ['verified'], 'the denied post was not failed or held')
        self.assertEqual(self.wire.duplicates(), 0)
        self.assertFalse([job for job in found if job.get('discordWorker', {}).get('unsentFailures')])

    def test_a_global_429_makes_each_loop_sleep_instead_of_claiming(self):
        claims = {}

        def lanes(worker):
            results, _ = F.run_lanes(worker, 4, seconds=40)
            claims['lane'] = sum(r['counters']['rateDelayed'] for r in results)
            claims['waits'] = sum(r['counters']['rateWaits'] for r in results)
        self.embargo_run(lanes)
        self.assertGreater(claims['waits'], 0)
        # At most the step each loop had in flight when the 429 landed, one claimed while its observation was being
        # recorded, and a cold-start identity read four loops raced for; the old loop releases nearly every due post.
        self.assertLessEqual(claims['lane'], 4 * 3)

    def test_control_the_existing_loop_keeps_claiming_through_the_same_embargo(self):
        claims = {}

        def tick(worker):
            with F.no_billing():
                parallel = [F.base_worker(self.cluster, self.hosted, name='w02-tick-%d' % n) for n in range(4)]
                import threading
                threads = [threading.Thread(target=lambda w=w: [w.tick_discord(25, 20) for _ in range(2)]) for w in parallel]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                claims['tick'] = sum(w.discord_stats['rateDelays'] for w in parallel)
        self.embargo_run(tick)
        self.assertGreaterEqual(claims['tick'], 20, 'without the lane\'s wait, the loops claim and release nearly every due post')

    # (h) the invalid-request budget --------------------------------------------------------------------------------

    def spent_invalid_budget(self, reset_in=40):
        """Six due posts (three whose approvals lapse in 20 s) and the coordinator's invalid-request row spent until
        `reset_in` seconds from now with no embargo on it (as after an embargo lifted by hand): the coordinator refuses
        every request until the reset (rate_limits._reserve: any capped row with nothing left)."""
        tenants = [F.Tenant(n) for n in range(6)]
        at = self.cluster.now() + 20 - 3600
        F.seed(self.cluster, tenants[:3], 1, now=at - 300, at=at)
        F.seed(self.cluster, tenants[3:], 1)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        self.worker = F.base_worker(self.cluster, self.hosted)
        self.admissions('reserve_read', 1)  # the coordinator's rows exist once any request was admitted
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET remaining=0, blocked_until=NULL, "
                       "reset_at=clock_timestamp()+make_interval(secs=>%s) WHERE kind='invalid'", (reset_in,))
        return self.worker

    def test_a_spent_invalid_request_budget_is_waited_out_without_claiming(self):
        worker = self.spent_invalid_budget()
        before = self.revisions()
        results, failures = F.run_lanes(worker, 4, seconds=10)
        self.assertEqual(failures, [])
        self.assertEqual({r['stoppedBy'] for r in results}, {'rate_wait'})
        for counter in ('claimed', 'rateDelayed', 'held', 'steps'):
            self.assertEqual(sum(r['counters'][counter] for r in results), 0, counter)
        self.assertEqual(self.revisions(), before, 'no workspace was claimed, released or written')
        self.assertEqual(self.wire.calls, [])
        found = F.jobs(self.cluster).values()
        self.assertEqual({job['state'] for job in found}, {'scheduled'}, 'nothing held early')
        self.assertFalse([job for job in found if job.get('attempts') or job.get('discordWorker')])

    def test_control_the_existing_loop_churns_through_the_same_spent_budget(self):
        worker = self.spent_invalid_budget()
        before = self.revisions()
        with F.no_billing():
            worker.tick_discord(10, 10)
        self.assertEqual(worker.discord_stats['rateDelays'], 6, 'every due post claimed, refused and released')
        self.assertGreater(self.revisions(), before)
        found = list(F.jobs(self.cluster).values())
        held = [job for job in found if job['state'] == 'held']
        self.assertEqual(len(held), 3, 'the posts whose approval ends before the reset are held at once')
        self.assertTrue(all(job['discordWorker']['releaseReason'] == 'rate_delayed' for job in found))
        self.assertEqual(self.wire.calls, [], 'the coordinator refused before any request left')

    def test_the_coordinator_embargoes_an_invalid_budget_it_spends_itself_and_the_lane_waits(self):
        """Recorded: when an invalid response spends the budget, the coordinator also sets blocked_until to the
        window's reset, so the lane's embargo read already covered that path; the capped-row rule covers the rest."""
        self.wire = F.MockDiscord([F.Tenant(0)])
        self.hosted = F.social(self.cluster, [F.Tenant(0)], self.wire, invalid_capacity=1)
        limiter, identity = self.hosted.providers['discord'].rate_limiter, self.hosted.providers['discord']._rate_identity('bot')
        limiter.observe(limiter.reserve_read('GET', '/guilds/6900000', identity=identity), {'status': 403, 'headers': {}})
        with self.cluster.connect(autocommit=True) as db:
            remaining, embargo, reset = db.execute(
                "SELECT remaining, extract(epoch from blocked_until-clock_timestamp()), "
                "extract(epoch from reset_at-clock_timestamp()) FROM public.pr_discord_rate_state "
                "WHERE kind='invalid'").fetchone()
        self.assertEqual(remaining, 0)
        self.assertAlmostEqual(float(embargo), float(reset), places=3)
        self.assertGreater(float(reset), 590)
        blocker, wait = F.discord_lane.outlook(F.discord_lane.LaneWorker(F.base_worker(self.cluster, self.hosted), 0))
        self.assertIsNone(blocker)
        self.assertGreater(wait, 590)

    # (g) database connections -------------------------------------------------------------------------------------

    def test_each_loop_holds_one_database_connection_at_a_time(self):
        tracker = F.ConnectionTracker()
        tenants = [F.Tenant(n) for n in range(12)]
        worker = self.start(tenants, 2, tracker=tracker)
        F.run_lanes(worker, 6, seconds=60)
        self.assert_each_created_once_and_verified(24)
        self.assertEqual(tracker.thread_peak, 1)
        self.assertLessEqual(tracker.peak, 6)
        self.assertEqual(tracker.open, 0)


if __name__ == '__main__':
    unittest.main()
