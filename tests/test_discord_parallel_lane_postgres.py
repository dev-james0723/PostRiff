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
import hashlib
import importlib.util
import json
import logging
import os
import threading
import time
import unittest
from unittest.mock import patch

import discord_lane_fixture as F
from postriff_phase2.discord import worker as discord_worker
from postriff_phase2.discord.rate_limits import SharedPostgresBudget

SETTLED = ('verified', 'held', 'uncertain', 'failed', 'canceled')  # nothing more happens without a person
FROZEN_SOURCE = F.ROOT / 'tests/phase2/fixtures/hosted_worker_2a5a523d.py.txt'
FROZEN_SHA256 = '8fdfd6e3dc461a88a9d4784a587491e22ada54b27585480a41609fb8c64f76de'  # pragma: allowlist secret -- content hash of the pinned source


class WorkerDied(BaseException):
    """A process that stops mid-step: nothing after this point runs; its open transaction rolls back."""


class Counted:
    """A connection factory that counts what is opened through it: connections, and statements by their SQL. A
    statement for which `refuse(sql)` is true raises instead of running (a failing query, on the real database)."""
    def __init__(self, cluster, refuse=None):
        self.cluster, self.connections, self.statements, self.refuse = cluster, 0, [], refuse or (lambda sql: False)

    def __call__(self):
        self.connections += 1
        return _CountedConnection(F.psycopg.connect(self.cluster.dsn, prepare_threshold=None), self)


class _CountedConnection:
    def __init__(self, connection, counter):
        self._connection, self._counter = connection, counter

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *exc):
        return self._connection.__exit__(*exc)

    def cursor(self, *args, **kwargs):
        return _CountedCursor(self._connection.cursor(*args, **kwargs), self._counter)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _CountedCursor:
    def __init__(self, cursor, counter):
        self._cursor, self._counter = cursor, counter

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cursor.__exit__(*exc)

    def execute(self, sql, *args, **kwargs):
        self._counter.statements.append(sql)
        if self._counter.refuse(sql):
            raise RuntimeError('synthetic statement failure')
        return self._cursor.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def frozen_worker_class():
    """The release candidate's own worker (2a5a523d), as a rollback would run it: the old file in today's package."""
    source = FROZEN_SOURCE.read_bytes()
    assert hashlib.sha256(source).hexdigest() == FROZEN_SHA256, 'the pinned base worker changed'
    namespace = {'__name__': 'postriff_phase2.hosted_worker_2a5a523d', '__package__': 'postriff_phase2',
                 '__builtins__': __builtins__}
    exec(compile(source, str(FROZEN_SOURCE), 'exec'), namespace)
    return namespace['PostgresWorker']


def short_policy(now, seconds):
    """A reviewed policy (the operator tool's own builder) that expires `seconds` after `now`, to the second."""
    spec = importlib.util.spec_from_file_location('discord_rate_policy', F.ROOT / 'scripts/discord_rate_policy.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    value = tool.build(now, days=(60 + seconds + .5) / 86400, revision='w02-lane-test', app_capacity=200)
    return json.dumps(value), value['expires_at']


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

    def drain(self, worker, loops, *, seconds, rounds=4):
        """The lane as consecutive cron minutes: `loops` shards run, and run again while any post still waits to
        be sent or verified (at most `rounds` times). A slow runner may need another minute for what a fast one
        finishes in one, as production would; the properties are checked on the outcome, not on how many minutes
        it took. Returns every loop's result."""
        every = []
        for _ in range(rounds):
            results, failures = F.run_lanes(worker, loops, seconds=seconds)
            self.assertEqual(failures, [])
            every.extend(results)
            if all(job['state'] in SETTLED for job in F.jobs(self.cluster).values()):
                break
        return every

    # (a) exactly once with many loops ---------------------------------------------------------------------------

    def test_many_loops_create_every_post_exactly_once(self):
        tenants = [F.Tenant(n) for n in range(24)]
        worker = self.start(tenants, 5)
        results = self.drain(worker, 8, seconds=60)
        self.assert_each_created_once_and_verified(120)
        self.assertEqual(sum(r['counters']['posted'] for r in results), 120)
        self.assertEqual(sum(r['counters']['verified'] for r in results), 120)
        self.assertEqual(self.wire.route429, 0)
        # Drained, every loop stops at once as idle, claiming nothing.
        idle, failures = F.run_lanes(worker, 8, seconds=60)
        self.assertEqual(failures, [])
        self.assertEqual({r['stoppedBy'] for r in idle}, {'idle'})
        self.assertEqual(sum(r['counters']['claimed'] for r in idle), 0)

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
        self.drain(worker, 6, seconds=90)
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

    # Requests per one-second window. Low enough that twelve loops want more on any runner, a slow one too: the
    # cap must bind for the test to say anything, and the uncapped control must still exceed twice it.
    RATE = 3

    def rate_run(self, capacity):
        """Twelve loops for twelve seconds over 80 posts. Returns the loops' results and how often a loop found
        the application-wide rows spent before a step and waited for the next window (the lane's pre-claim
        outlook; its create-permit waits also count permits that lapsed at a window's end, so they are left out)."""
        tenants = [F.Tenant(n) for n in range(40)]
        worker = self.start(tenants, 2, capacity=capacity, ceiling=2 * self.RATE)
        results, failures = F.run_lanes(worker, 12, seconds=12)
        self.assertEqual(failures, [])
        # Each loop ran on its own twelve-second budget and stopped in order (the loop's timing itself is proven
        # on a scripted clock in test_discord_parallel_lane.TheLoop; a wall-clock bound here measures the runner).
        self.assertEqual({r['budget']['maxSeconds'] for r in results}, {12.0})
        self.assertLessEqual({r['stoppedBy'] for r in results}, {'time_budget', 'rate_wait', 'idle'})
        return results, sum(r['counters']['rateWaits'] for r in results)

    def test_the_coordinator_caps_the_request_rate_across_all_loops(self):
        _, waits = self.rate_run(self.RATE)
        calls = self.wire.calls
        self.assertGreater(waits, 0, 'the run was busy enough to meet the cap')
        # Fixed one-second windows: any trailing second holds at most two windows' worth.
        self.assertLessEqual(self.wire.peak_second, 2 * self.RATE)
        self.assertEqual(self.wire.over_ceiling, 0)
        span = calls[-1][0] - calls[0][0]
        self.assertLessEqual(len(calls), self.RATE * (span + 2), 'never above the policy on average')
        self.assertEqual(self.wire.duplicates(), 0)

    def test_control_the_same_run_exceeds_that_ceiling_when_the_policy_allows_it(self):
        _, waits = self.rate_run(1000)
        self.assertEqual(waits, 0, 'no loop waited for an application window')
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

    def three_per_window(self):
        """Three admissions per three-second window. A window opens at its first reservation, so a slow runner's
        few back-to-back reservations still share one window (with the default one-second window they could
        straddle two and count six slots)."""
        tenants = [F.Tenant(0)]
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=3, app_window_seconds=3)
        return 3

    def test_permits_of_a_dead_loop_that_were_never_used_free_their_slots(self):
        window = self.three_per_window()
        self.assertEqual(self.admissions('reserve', 4), 3)  # a dead loop's three permits fill the window
        time.sleep(window + .2)  # they were never consumed, so the next window does not count them
        self.assertEqual(self.admissions('reserve', 4, offset=10), 3)

    def test_a_read_whose_process_died_after_admission_keeps_its_slot_until_reviewed(self):
        """Existing conservative rule, recorded here: a spent admission with no observed answer keeps one slot."""
        window = self.three_per_window()
        self.assertEqual(self.admissions('reserve_read', 1), 1)  # admitted as sent; the answer is never observed
        time.sleep(window + .2)
        self.assertEqual(self.admissions('reserve_read', 3, offset=10), 2)
        with self.cluster.connect(autocommit=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_discord_request_admissions WHERE state='sent' "
                                        "AND sent_at<clock_timestamp()-interval '1 second'").fetchone()[0], 1)

    # (c) fairness and the per-channel limit ---------------------------------------------------------------------

    def fairness_run(self, loops, order=None):
        """One busy workspace (30 posts, first by id) and six small ones (two each). Returns the workspaces in id
        order and every claim the run made, in order, as (workspace, job), read from the jobs' own audit events.

        Claims, not creates, carry the property: which workspace a loop takes next is the selection's choice, while
        whether that attempt sends now or is deferred (the busy channel's 5-per-5-s window, a create permit that
        lapses at its one-second window end) depends on how fast the runner is."""
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
                self.drain(worker, loops, seconds=90)
        else:
            self.drain(worker, loops, seconds=90)
        return tenants, self.claim_order()

    def claim_order(self):
        """Every claim so far, in order, as (workspace, job), from the jobs' own 'claimed' events."""
        claims = sorted((event['at'], workspace, job_id) for (workspace, job_id), job in F.jobs(self.cluster).items()
                        for event in job['events'] if event['state'] == 'claimed')
        return [(workspace, job_id) for _, workspace, job_id in claims]

    def assert_rotation(self, tenants, claims):
        # Each claim moves its workspace to the back of the due order, also when the attempt is then deferred, and
        # a workspace with a post never attempted is due. So one loop's first fourteen claims are two rounds over
        # all seven workspaces in id order: every small tenant's two posts are attempted while the busy one's
        # thirty have had two attempts. This is the selection's order, whatever the runner's speed.
        ids = [tenant.id for tenant in tenants]
        self.assertEqual([workspace for workspace, _ in claims[:14]], ids + ids, 'two full rounds come first')

    def assert_busy_first(self, tenants, claims):
        # Ordered by id alone, one loop takes the lowest-id workspace while it has a due post, and a post never
        # attempted is due. So the busy workspace stays first until all thirty of its posts were attempted (some
        # sent, the rest deferred to its channel's window): no other workspace is claimed before that.
        big = tenants[0].id
        first_other = next(index for index, (workspace, _) in enumerate(claims) if workspace != big)
        busy = {job for workspace, job in claims if workspace == big}
        self.assertEqual(len(busy), 30)
        self.assertEqual({job for _, job in claims[:first_other]}, busy, 'every busy post was attempted first')

    def test_one_busy_workspace_cannot_starve_the_others(self):
        tenants, claims = self.fairness_run(1)
        self.assert_rotation(tenants, claims)
        self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])
        self.assertEqual(self.wire.duplicates(), 0)

    def test_control_without_the_rotation_one_loop_serves_the_busy_workspace_first(self):
        # A real control: the same assertion fails with the rotation on, whose second claim is already a small
        # tenant's (assert_rotation above).
        self.assert_busy_first(*self.fairness_run(1, order='id'))

    def test_posts_to_one_channel_keep_to_its_create_limit(self):
        # Six workspaces connected to the same server channel: the limit is the channel's, across tenants.
        tenants = [F.Tenant(n, guild='6100000', channel='7100000') for n in range(6)]
        worker = self.start(tenants, 3)
        self.drain(worker, 6, seconds=90)
        self.assertEqual(self.wire.route429, 0, 'no create was refused by the channel limit')
        times = sorted(at for created in self.wire.creates.values() for at, _, _ in created)
        self.assertEqual(len(times), 18)
        self.assertGreaterEqual(times[-1] - times[0], 10, 'eighteen creates at five per five seconds')
        self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])
        self.assertEqual(self.wire.duplicates(), 0)

    # (d) an approval that expires while waiting ------------------------------------------------------------------

    # The coordinator checks a create against its approval and the policy, then records sent_at in the next
    # statement of the same transaction; on a loaded runner that statement can come a little later.
    RELEASE_SLACK = 1.0

    def released_creates(self):
        """When the coordinator let each create leave (its admission's sent_at, the database clock), by
        (workspace, publication): the last instant the system controls. The mock's own arrival time adds the
        commit and the runner's scheduling delay on top, which no deadline check can bound."""
        with self.cluster.connect(autocommit=True) as db:
            rows = db.execute("SELECT workspace_id::text, publication_id, extract(epoch from sent_at)::double precision, "
                              "extract(epoch from expires_at)::double precision "
                              "FROM public.pr_discord_request_admissions WHERE is_publish AND sent_at IS NOT NULL").fetchall()
        released, self.permit_ends = {}, {}
        for workspace, publication, sent, permit_end in rows:
            released.setdefault((workspace, publication), []).append(sent)
            self.permit_ends.setdefault((workspace, publication), []).append(permit_end)
        return released

    def test_a_post_whose_approval_expires_while_waiting_is_held_and_never_sent_late(self):
        tenants = [F.Tenant(n) for n in range(14)]
        expiry = self.cluster.now() + 8
        at = expiry - 3600  # an approval lives one hour after its scheduled time
        self.start(tenants, 1, capacity=6, latency=.02, now=at - 300, at=at)
        F.run_lanes(self.worker, 3, seconds=30)
        found = F.jobs(self.cluster)
        released = self.released_creates()
        for key, job in found.items():
            self.assertAlmostEqual(job['manifest']['expiresAt'], int(at) + 3600, delta=1)
            creates = self.wire.creates.get(F.nonce(job), [])
            self.assertEqual(len(released.get(key, [])), len(creates), 'every create the mock saw was released')
            for sent, permit_end in zip(released.get(key, []), self.permit_ends.get(key, [])):
                # Exact: the permit a create left under was never valid past the approval (the coordinator
                # refuses a permit at its end); and the release itself was recorded before that, give or take
                # the next statement.
                self.assertLessEqual(permit_end, job['manifest']['expiresAt'] + 1e-6)
                self.assertLess(sent, job['manifest']['expiresAt'] + self.RELEASE_SLACK,
                                'nothing is released after its approval expired')
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
                held_at.extend((time.monotonic(), time.time()))
        self.wire.after = after
        results, failures = F.run_lanes(worker, 4, seconds=60)
        self.assertEqual(failures, [])
        self.assertEqual({r['stoppedBy'] for r in results}, {'operator_hold'})
        late = [call for call in self.wire.calls if call[1] == 'POST' and call[0] > held_at[0]]
        self.assertLessEqual(len(late), 4, 'at most the one step each loop already had in flight')
        by_nonce = {F.nonce(job): job for job in F.jobs(self.cluster).values()}
        claimed = {nonce: [event['at'] for event in job['events'] if event['state'] == 'claimed']
                   for nonce, job in by_nonce.items()}
        self.assertLessEqual(sum(at > held_at[1] for times in claimed.values() for at in times), 4,
                             'each loop claims at most once after the hold: the iteration it was in')
        for nonce, times in self.wire.creates.items():
            for _, _, wall in times:
                if wall > held_at[1]:
                    self.assertLess(min(claimed[nonce]), held_at[1], 'a create after the hold was claimed before it')
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
        self.drain(worker, 4, seconds=60)
        # A hold also blocks every reserved-but-unused create permit (existing rule). A loop that was between
        # sealing and sending used to record its post as uncertain with nothing sent; consume() now refuses the
        # blocked permit before any transport and the post is released unsent and sent once (section (m)). The
        # bounds below hold either way.
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
        started = self.embargo_run(lambda worker: self.drain(worker, 4, seconds=40))
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
            # The stored instants, not each one minus its own clock_timestamp() call: two calls can be
            # milliseconds apart when the server process is preempted between them.
            remaining, embargo, reset, left = db.execute(
                "SELECT remaining, extract(epoch from blocked_until), extract(epoch from reset_at), "
                "extract(epoch from reset_at-clock_timestamp()) FROM public.pr_discord_rate_state "
                "WHERE kind='invalid'").fetchone()
        self.assertEqual(remaining, 0)
        self.assertAlmostEqual(float(embargo), float(reset), places=5)
        self.assertGreater(float(left), 590)
        blocker, wait = F.discord_lane.outlook(F.discord_lane.LaneWorker(F.base_worker(self.cluster, self.hosted), 0))
        self.assertIsNone(blocker)
        self.assertGreater(wait, 590)

    # (g) database connections -------------------------------------------------------------------------------------

    def test_each_loop_holds_one_database_connection_at_a_time(self):
        tracker = F.ConnectionTracker()
        tenants = [F.Tenant(n) for n in range(12)]
        worker = self.start(tenants, 2, tracker=tracker)
        self.drain(worker, 6, seconds=60)
        self.assert_each_created_once_and_verified(24)
        self.assertEqual(tracker.thread_peak, 1)
        self.assertLessEqual(tracker.peak, 6)
        self.assertEqual(tracker.open, 0)

    # (i) recovery -------------------------------------------------------------------------------------------------

    def minute(self, worker, *, flag=True):
        """One run of the minute cron (the real PostgresWorker.tick()), with the lane flag on or off."""
        values = {F.discord_lane.ENV_ENABLED: 'true' if flag else 'false', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}
        with patch.dict(os.environ, values), F.no_billing():
            return worker.tick(10, 20)

    def lagging(self, worker):
        """One minute cron run (lane flag on) and the lag warnings it logged."""
        with self.assertLogs('postriff.request', 'DEBUG') as logged:
            logging.getLogger('postriff.request').debug('marker')
            tick = self.minute(worker)
        return tick, [json.loads(r.getMessage()) for r in logged.records if 'discord.lane.lagging' in r.getMessage()]

    def unable(self, cause):
        """Leave this process's provider as the hosted runtime would with `cause`: the lane cannot run anywhere."""
        provider = self.hosted.providers['discord']
        if cause == 'rate limits off':
            # runtime_from_environment: without rate limits it also turns Discord authorization off.
            provider.rate_v1_enabled = provider.authorization_v2_enabled = False
            provider.rate_limiter = None
        elif cause == 'policy expired':
            provider.rate_limiter = SharedPostgresBudget(self.cluster.factory(), F.APP,
                                                         policy=F.policy(self.cluster.now() - 3 * 86400, capacity=200))
        else:
            assert cause == 'no coordinator', cause
            # runtime_from_environment with rate limits on but no policy, or one that does not parse: the coordinator
            # cannot be built, so no limiter is set and Discord authorization is turned off.
            provider.rate_limiter = None
            provider.authorization_v2_enabled = False

    def repair(self):
        """The repaired configuration, as a new deployment builds it: rate limits on and a current reviewed policy."""
        provider = self.hosted.providers['discord']
        provider.rate_v1_enabled = provider.authorization_v2_enabled = True
        provider.rate_coordinator_degraded = False
        provider.rate_limiter = SharedPostgresBudget(self.cluster.factory(), F.APP,
                                                     policy=F.policy(self.cluster.now(), capacity=200))

    def skip_push_back(self):
        """Make the posts pushed back five minutes due now, instead of waiting five minutes."""
        with self.cluster.connect(autocommit=True) as db:
            for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
                for job in state['phase2']['jobs']:
                    if job['state'] == 'scheduled':
                        job['nextAt'] = 0
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                           (json.dumps(state), workspace))

    def destinations(self):
        """The status of every Discord destination that is no longer plainly authorized."""
        with self.cluster.connect(autocommit=True) as db:
            rows = db.execute("SELECT state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall()
        return [destination.get('status') for (state,) in rows for channel in state['phase2']['channels']
                for destination in channel.get('discordDestinations', []) if destination.get('status') != 'authorized']

    def recovery(self, cause):
        """Six due posts, three of whose approvals end in 20 s. The lane cannot run (`cause`): the shards claim
        nothing and the minute cron keeps the frozen path. Then the configuration is repaired and the lane drains.
        Returns the jobs after the frozen minute, the jobs at the end, and the short-approval workspaces."""
        tenants = [F.Tenant(n) for n in range(6)]
        at = self.cluster.now() + 20 - 3600  # an approval lives one hour after its scheduled time
        F.seed(self.cluster, tenants[:3], 1, now=at - 300, at=at)
        F.seed(self.cluster, tenants[3:], 1)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        worker = F.base_worker(self.cluster, self.hosted)
        self.unable(cause)
        results, failures = F.run_lanes(worker, 3, seconds=10)
        self.assertEqual(failures, [])
        self.assertEqual([r['stoppedBy'] for r in results], ['coordinator_unavailable'] * 3)
        self.assertEqual(sum(r['counters']['claimed'] for r in results), 0, 'the shards claim nothing')
        tick = self.minute(worker)
        self.assertNotIn('discordParallelLane', tick, 'the minute cron keeps the frozen Discord path')
        self.assertEqual((tick['discordLaneStatus']['ready'], tick['discordLaneStatus']['blocker']),
                         (False, 'coordinator_unavailable'))
        frozen = F.jobs(self.cluster)
        self.assertEqual(self.wire.calls, [], 'nothing reached Discord while the lane could not run')
        self.repair()
        self.skip_push_back()
        tick = self.minute(worker)
        self.assertTrue(tick['discordParallelLane'] and tick['discordLaneStatus']['ready'])
        results, failures = F.run_lanes(worker, 3, seconds=60)
        self.assertEqual(failures, [])
        return frozen, F.jobs(self.cluster), {tenant.id for tenant in tenants[:3]}

    def assert_frozen_holds(self, frozen, final):
        """Without Discord authorization the frozen path holds each post it claims and asks for its destination to be
        verified again; the repaired lane then has nothing due, and never sends a held post."""
        for job in frozen.values():
            self.assertEqual((job['state'], job['events'][-1]['message']),
                             ('held', 'Discord destination, grant, media or rollout verification is unavailable. '
                                      'Nothing was posted.'))
        self.assertEqual(self.destinations(), ['verification_required'] * 6)
        self.assertEqual({job['state'] for job in final.values()}, {'held'})
        self.assertEqual(self.wire.requests(method='POST'), [])

    def test_recovery_after_rate_limits_were_off_keeps_the_frozen_holds(self):
        """Recorded: the hosted runtime turns Discord authorization off without rate limits."""
        self.assert_frozen_holds(*self.recovery('rate limits off')[:2])

    def test_recovery_after_the_coordinator_was_missing_keeps_the_frozen_holds(self):
        """Recorded: rate limits on but no coordinator (no policy, or one that does not parse) is reachable only with
        Discord authorization off (runtime_from_environment), so the frozen path holds as with rate limits off."""
        self.assert_frozen_holds(*self.recovery('no coordinator')[:2])

    def assert_recovered_after_the_push_back(self, frozen, final, short):
        for (workspace, _), job in frozen.items():
            operation = job['discordWorker']
            self.assertEqual(operation['releaseReason'], 'rate_delayed')
            self.assertAlmostEqual(operation['rateDelayedUntil'] - operation['releasedAt'], 300, delta=1)
            self.assertEqual((job['state'], job['nextAction']),
                             ('held', 'Discord rate wait outlasts approval; review the frozen destination and approve again')
                             if workspace in short else
                             ('scheduled', 'Await Discord shared rate budget; no POST occurred and this approval remains frozen'))
        for (workspace, _), job in final.items():
            creates = len(self.wire.creates.get(F.nonce(job), []))
            if workspace in short:
                self.assertEqual((job['state'], creates), ('held', 0), 'past its approval: held, never sent late')
            else:
                self.assertEqual((job['state'], creates), ('verified', 1), 'inside its approval: created exactly once')
        self.assertEqual(self.wire.duplicates(), 0)

    def test_recovery_after_the_policy_expired_drains_exactly_once(self):
        self.assert_recovered_after_the_push_back(*self.recovery('policy expired'))

    def test_recovery_after_the_shard_crons_stopped_for_minutes(self):
        tenants = sorted((F.Tenant(n) for n in range(7)), key=lambda tenant: tenant.id)
        busy, small = tenants[0], tenants[1:]  # the busy tenant sorts first by id
        gap = self.cluster.now() - 960  # posts scheduled 11 minutes ago; no shard has run since
        F.seed(self.cluster, [busy], 20, now=gap)
        F.seed(self.cluster, small, 2, now=gap)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        worker = F.base_worker(self.cluster, self.hosted)
        for _ in range(2):  # two minutes of the gap
            tick, warnings = self.lagging(worker)
            self.assertTrue(tick['discordParallelLane'], 'the minute cron leaves Discord to the absent lane')
            (warning,) = warnings
            self.assertGreater(warning['oldestEligibleLagSeconds'], 600)
            self.assertEqual((warning['laneOwnsDiscord'], warning['laneBlocker'], warning['depth']), (True, None, 32))
        self.assertEqual(self.wire.calls, [], 'nothing was sent during the gap')
        self.drain(worker, 1, seconds=90)  # the crons arrive again
        self.assert_each_created_once_and_verified(32)
        # The backlog drains fairly: the rotation's first two rounds cover every workspace (see the fairness test).
        self.assert_rotation(tenants, self.claim_order())
        tick, warnings = self.lagging(worker)
        self.assertEqual(warnings, [], 'quiet once drained')

    def test_a_policy_that_expires_mid_run_stops_every_loop_and_renewal_resumes(self):
        tenants = [F.Tenant(n) for n in range(48)]
        worker = self.start(tenants, 1, latency=.1)
        provider = self.hosted.providers['discord']
        raw, expires = short_policy(self.cluster.now(), 4)
        provider.rate_limiter = SharedPostgresBudget(self.cluster.factory(), F.APP, policy=raw)
        results, failures = F.run_lanes(worker, 4, seconds=60)
        self.assertEqual(failures, [])
        self.assertEqual([r['stoppedBy'] for r in results], ['coordinator_unavailable'] * 4, 'every loop stopped')
        self.assertEqual({r['status']['blocker'] for r in results}, {'coordinator_unavailable'})
        found = F.jobs(self.cluster)
        claims = [event['at'] for job in found.values() for event in job.get('events', []) if event['state'] == 'claimed']
        self.assertTrue(claims and min(claims) < expires)
        # Each loop checks the policy before every step, so a loop claims after the expiry at most in the one step
        # it had already begun: a bound by structure, not by how slow the runner is.
        self.assertLessEqual(len([at for at in claims if at > expires]), 4, 'no new step after the expiry')
        released = [sent for times in self.released_creates().values() for sent in times]
        self.assertEqual(len(released), sum(len(times) for times in self.wire.creates.values()))
        self.assertTrue(0 < len(released) < len(tenants), 'the policy expired mid-run')
        self.assertLessEqual(max(end for ends in self.permit_ends.values() for end in ends), expires + 1e-6,
                             'no permit outlived the policy')
        self.assertLess(max(released), expires + self.RELEASE_SLACK, 'no create was released after the expiry')
        # Renewal (a new deployment with a renewed policy): the lane resumes.
        provider.rate_limiter = SharedPostgresBudget(self.cluster.factory(), F.APP,
                                                     policy=F.policy(self.cluster.now(), capacity=200))
        self.skip_push_back()
        self.drain(worker, 4, seconds=60)
        stuck = []
        for job in F.jobs(self.cluster).values():
            creates = len(self.wire.creates.get(F.nonce(job), []))
            self.assertLessEqual(creates, 1, 'never sent twice')
            if job['state'] == 'verified':
                self.assertEqual(creates, 1)
            else:
                stuck.append((job['state'], creates, job['events'][-1]['message']))
        # The step a loop had in flight at the expiry may be left for review (existing rules: refused at the seal it
        # is held, refused at the create it is uncertain with nothing sent); never more than one per loop.
        self.assertLessEqual(len(stuck), 4, stuck)
        self.assertEqual({(state, creates) for state, creates, _ in stuck} - {('held', 0), ('uncertain', 0)}, set(),
                         stuck)
        self.assertEqual(self.wire.duplicates(), 0)

    # (j) rollback -------------------------------------------------------------------------------------------------

    def leave_a_dead_lease(self, method, suffix, *, before, nth=2, within=''):
        """One lane loop dies at the `nth` matching request (`before` Discord sees it, or after Discord answered),
        so it stops mid-step holding a live lease. Returns that job. Only requests whose path contains `within`
        count: the second one on a route is on a learned route, as almost every production request is (dying in
        the first request of a route leaves that route waiting for review instead; Q3 and the cold-route test)."""
        seen = []

        def hook(m, path, answer=None):
            if m == method and path.endswith(suffix) and within in path:
                seen.append(path)
                if len(seen) == nth:
                    raise WorkerDied()
        if before:
            self.wire.fail = hook
        else:
            self.wire.after = hook
        _, failures = F.run_lanes(self.worker, 1, seconds=30)
        self.assertEqual([type(error) for _, error in failures], [WorkerDied])
        self.wire.fail = self.wire.after = None
        (dead,) = [job for job in F.jobs(self.cluster).values()
                   if (job.get('leaseOwner') or '').startswith('discord-lane-')]
        return dead

    @staticmethod
    def key(job):
        return job['manifest']['workspaceId'], job['id']

    def test_rollback_the_flag_turned_off_mid_run_lets_the_frozen_minute_cron_take_over(self):
        tenants = [F.Tenant(n) for n in range(4)]
        self.start(tenants, 4)
        ticks, stop = [], threading.Event()

        def minute_cron():  # the new build's cron, flag off: no patching here, the environment is set below
            while not stop.is_set():
                ticks.append(self.worker.tick(10, 20))
                time.sleep(.2)
        with patch.object(discord_worker, 'LEASE_SECONDS', 3):
            dead = self.leave_a_dead_lease('GET', '/channels', before=True, within='/guilds/%s/' % tenants[0].guild)
            # The flag goes off on a new build. The old build's lane invocations still run to the end of their
            # budget while the new minute cron, on the frozen path, takes Discord back: both at once, then the cron.
            cron = threading.Thread(target=minute_cron)
            with F.no_billing(), patch.dict(os.environ, {F.discord_lane.ENV_ENABLED: 'false',
                                                         'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}):
                cron.start()
                try:
                    _, failures = F.run_lanes(self.worker, 2, seconds=6)
                    self.assertEqual(failures, [])
                    deadline = time.monotonic() + 240  # a wait for an outcome: it ends as soon as all are verified
                    while (time.monotonic() < deadline
                           and {job['state'] for job in F.jobs(self.cluster).values()} != {'verified'}):
                        time.sleep(.5)
                finally:
                    stop.set()
                    cron.join()
        self.assertTrue(ticks and all('discordParallelLane' not in tick and 'discordLaneStatus' not in tick
                                      for tick in ticks), "the new build's minute cron runs the frozen path")
        self.assertGreater(sum(tick['processed'] for tick in ticks), 0, 'and took Discord work')
        found = self.assert_each_created_once_and_verified(16)
        recovered = found[self.key(dead)]
        self.assertEqual(recovered['discordWorker']['recoveries'], 1)
        self.assertIn('Expired Discord fence was provably unsent; bounded recovery recorded',
                      [event['message'] for event in recovered['events']])

    def frozen_rollback(self, method, suffix, *, before):
        """A lane loop dies mid-step holding a lease; the deployment is rolled back to the frozen 2a5a523d worker
        (no lane code at all), whose minute cron then runs alone. Returns the dead job and the final jobs."""
        self.start([F.Tenant(0)], 3)
        frozen = frozen_worker_class()(self.cluster.factory(), social=self.hosted, worker_id='frozen-minute',
                                       discord_workers=True)
        with patch.object(discord_worker, 'LEASE_SECONDS', 3):
            dead = self.leave_a_dead_lease(method, suffix, before=before)
            with F.no_billing(), patch.dict(os.environ, {'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}):
                calls = len(self.wire.calls)
                frozen.tick(10, 20)
                self.assertEqual(F.jobs(self.cluster)[self.key(dead)]['leaseOwner'], dead['leaseOwner'],
                                 'a live lane lease is left alone')
                self.assertEqual(len(self.wire.calls), calls, 'and so is its workspace: one live lease each')
                time.sleep(3.5)  # the dead loop's lease expires
                deadline = time.monotonic() + 180  # a wait for an outcome: it ends as soon as it is reached
                while time.monotonic() < deadline:
                    frozen.tick(10, 20)
                    found = F.jobs(self.cluster)
                    others = [job for key, job in found.items() if key != self.key(dead)]
                    if (all(job['state'] == 'verified' for job in others)
                            and found[self.key(dead)]['state'] in ('verified', 'uncertain')):
                        break
                    time.sleep(.5)
        return dead, F.jobs(self.cluster)

    def assert_others_verified_once(self, found, dead):
        for key, job in found.items():
            if key != self.key(dead):
                self.assertEqual((job['state'], len(self.wire.creates[F.nonce(job)])), ('verified', 1))
        self.assertEqual(self.wire.duplicates(), 0)

    def test_rollback_to_the_frozen_worker_recovers_a_lane_lease_only_as_unsent_after_expiry(self):
        dead, found = self.frozen_rollback('GET', '/channels', before=True)
        job = found[self.key(dead)]
        self.assertEqual((job['state'], len(self.wire.creates[F.nonce(job)])), ('verified', 1))
        self.assertEqual(job['discordWorker']['recoveries'], 1)
        self.assertIn('Expired Discord fence was provably unsent; bounded recovery recorded',
                      [event['message'] for event in job['events']])
        self.assert_others_verified_once(found, dead)

    def test_rollback_to_the_frozen_worker_never_recreates_a_sealed_post(self):
        dead, found = self.frozen_rollback('POST', '/messages', before=True)
        job = found[self.key(dead)]
        self.assertEqual((job['state'], self.wire.creates.get(F.nonce(job), [])), ('uncertain', []))
        self.assertEqual(len(job['discordDispatchIntents']), 1, 'its sealed intent stays for reconciliation')
        self.assertIn('Expired Discord intent requires reconciliation; never repost',
                      [event['message'] for event in job['events']])
        self.assert_others_verified_once(found, dead)

    def test_rollback_to_the_frozen_worker_never_recreates_a_post_discord_accepted(self):
        dead, found = self.frozen_rollback('POST', '/messages', before=False)
        job = found[self.key(dead)]
        self.assertEqual((job['state'], len(self.wire.creates[F.nonce(job)])), ('uncertain', 1))
        self.assert_others_verified_once(found, dead)

    def test_rollback_the_flag_off_then_on_again_keeps_every_post_exactly_once(self):
        worker = self.start([F.Tenant(n) for n in range(10)], 2)
        first, failures = F.run_lanes(worker, 2, seconds=20, steps=3)  # on: some progress
        self.assertEqual(failures, [])
        self.assertGreater(sum(r['counters']['claimed'] for r in first), 0)
        # Off (a build without the flag): every shard answers disabled, and the minute cron sends Discord.
        off = F.discord_lane.run(worker, 0, {'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'})
        self.assertEqual((off['enabled'], off['status']['blocker']), (False, 'disabled'))
        ticks = [self.minute(worker, flag=False) for _ in range(2)]
        self.assertGreater(sum(tick['processed'] for tick in ticks), 0)
        self.assertTrue(all('discordParallelLane' not in tick and 'discordLaneStatus' not in tick for tick in ticks))
        # On again (a build with the flag): the minute cron leaves Discord to the lane, which drains the rest.
        calls = len(self.wire.calls)
        on = self.minute(worker)
        self.assertTrue(on['discordParallelLane'])
        self.assertEqual((on['processed'], len(self.wire.calls)), (0, calls), 'the minute cron claims no Discord')
        self.drain(worker, 3, seconds=60)
        self.assert_each_created_once_and_verified(20)

    # (k) an idle shard ----------------------------------------------------------------------------------------------

    def shard(self):
        """One shard invocation on a worker whose own connections are counted. Returns (result, counter)."""
        counted = Counted(self.cluster)
        worker = F.PostgresWorker(counted, social=self.hosted, worker_id='w02-counted', discord_workers=True)
        (result,), failures = F.run_lanes(worker, 1, seconds=50)
        self.assertEqual(failures, [])
        return result, counted

    def test_an_idle_shard_opens_one_connection_for_one_statement(self):
        """Twelve shards every minute: with nothing due, each opens one connection for one statement (the database
        clock and the soonest due work in the projection) and stops as idle. It used to open four for seven: the
        schema check, the coordinator read, a claim's checks and due query, and the due probe after the miss."""
        tenants = [F.Tenant(n) for n in range(4)]
        now = self.cluster.now()
        F.seed(self.cluster, tenants[:2], 0)  # workspaces without Discord work
        F.seed(self.cluster, tenants[2:], 2, now=now - 60, at=now + 1800)  # approved, due in half an hour
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        result, counted = self.shard()
        self.assertEqual((result['stoppedBy'], counted.connections, len(counted.statements)), ('idle', 1, 1))
        self.assertEqual(counted.statements, [F.discord_lane._SOONEST])
        self.assertEqual((result['counters']['steps'], result['counters']['claimed']), (0, 0))
        self.assertEqual(self.wire.calls, [])
        # Idle by the loop's own rule: the soonest due work lies beyond the idle horizon.
        with self.cluster.connect(autocommit=True) as db:
            soonest = db.execute('SELECT min(next_at) FROM public.pr_discord_worker_projection').fetchone()[0]
        self.assertGreater(soonest - self.cluster.now(), F.discord_lane.IDLE_HORIZON_SECONDS)

    def test_a_shard_with_work_due_runs_the_loop_as_before(self):
        tenants = [F.Tenant(n) for n in range(2)]
        self.start(tenants, 1)
        result, counted = self.shard()
        # The due probe in place of the schema check, then the loop: its coordinator read before the first claim.
        self.assertEqual(counted.statements[0], F.discord_lane._SOONEST)
        self.assertIn('pr_discord_rate_state', counted.statements[1])
        self.assertEqual((result['counters']['posted'], result['counters']['verified']), (2, 2))
        self.assert_each_created_once_and_verified(2)

    def test_on_an_idle_shard_the_p0_signals_still_fire(self):
        tenants = [F.Tenant(n) for n in range(2)]
        now = self.cluster.now()
        F.seed(self.cluster, tenants, 1, now=now - 60, at=now + 1800)  # nothing due within the horizon
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        # A shard that cannot run says why at WARNING every minute, before any database read.
        for cause, reason in (('rate limits off', 'coordinator_unavailable'), ('policy expired', 'coordinator_unavailable'),
                              ('no coordinator', 'coordinator_unavailable'), ('degraded', 'coordinator_degraded')):
            with self.subTest(cause):
                self.repair()
                if cause == 'degraded':
                    self.hosted.providers['discord'].rate_coordinator_degraded = True
                else:
                    self.unable(cause)
                with self.assertLogs('postriff.request', 'WARNING') as logged:
                    result, counted = self.shard()
                entry = json.loads(logged.records[-1].getMessage())
                self.assertEqual((result['stoppedBy'], entry['event'], entry['stoppedBy']),
                                 (reason, 'discord.lane.completed', reason))
                self.assertEqual((result['status']['ready'], result['status']['blocker']), (False, reason))
                self.assertEqual((counted.connections, counted.statements), (0, []))
        self.repair()

    # (m) an embargo seen while posts are sealed ---------------------------------------------------------------------

    def global_429(self, retry):
        """Discord answers another bot request with a global 429, observed by the coordinator as in production: the
        bot's global row is embargoed and every reserved or sealed permit of the bot is blocked (observe()).
        Returns (when it was observed, the end of the embargo), both epoch seconds."""
        provider = self.hosted.providers['discord']
        limiter, identity = provider.rate_limiter, provider._rate_identity('bot')
        permit = limiter.reserve_read('GET', '/guilds/6900999', identity=identity)
        seen = time.time()
        limiter.observe(permit, {'status': 429, 'headers': {'retry-after': str(retry), 'x-ratelimit-global': 'true',
                                                            'x-ratelimit-scope': 'global'},
                                 'body': {'message': 'You are being rate limited.', 'retry_after': retry, 'global': True}})
        with self.cluster.connect(autocommit=True) as db:
            until = db.execute("SELECT extract(epoch from blocked_until)::double precision FROM public.pr_discord_rate_state "
                               "WHERE kind='global'").fetchone()[0]
        return seen, until

    def test_a_global_429_seen_while_posts_are_sealed_sends_each_once_after_the_embargo(self):
        """Three loops each hold a sealed post when a global 429 is observed. consume() refuses each blocked permit
        before any transport, the worker proves the intent unsent from the admission row and releases the post for
        the embargo's remaining time: none is left uncertain, and each is created exactly once, after the embargo."""
        tenants = [F.Tenant(n) for n in range(3)]
        worker = self.start(tenants, 1)
        limiter = self.hosted.providers['discord'].rate_limiter
        real, lock, sealed, embargo, first = limiter.consume, threading.Lock(), threading.Barrier(3), [], []

        def consume(permit, method, path, **kwargs):
            if permit.binding_hash:
                with lock:
                    waits = len(first) < 3
                    first.append(permit.id)
                if waits:  # the first three creates: every loop has sealed its post
                    try:
                        sealed.wait(timeout=30)
                    except threading.BrokenBarrierError:
                        pass
                    with lock:
                        if not embargo:
                            embargo.append(self.global_429(retry=3))
            return real(permit, method, path, **kwargs)
        with patch.object(limiter, 'consume', consume):
            self.drain(worker, 3, seconds=40)
        found = self.assert_each_created_once_and_verified(3)
        (seen, until), = embargo
        during = [wall for times in self.wire.creates.values() for _, _, wall in times if seen <= wall < until]
        self.assertEqual(during, [], 'no create reached Discord during the embargo')
        proofs = [[entry['unsentProof'] for entry in job.get('discordUnsentDispatches', [])] for job in found.values()]
        released = [job for job in found.values()
                    if 'embargo_blocked_admission' in [entry['unsentProof'] for entry in job.get('discordUnsentDispatches', [])]]
        self.assertEqual(len(released), 3, proofs)
        for job in released:
            self.assertIn('A Discord embargo blocked the sealed permit before it was consumed; no POST was started; '
                          'intent archived before safe rate wait', [event['message'] for event in job['events']])

    def test_control_a_create_whose_transport_ran_and_failed_stays_uncertain(self):
        """The same embargo, observed while one create is inside the transport, which then fails: the request may
        have reached Discord, so that post stays uncertain for reconciliation and is never sent again."""
        tenants = [F.Tenant(n) for n in range(2)]
        worker = self.start(tenants, 1)
        hit = []

        def fail(method, path):
            if method == 'POST' and not hit:
                hit.append(self.global_429(retry=3))
                raise ConnectionResetError('synthetic: the connection dropped after the request was handed over')
        self.wire.fail = fail
        self.drain(worker, 2, seconds=40)
        found = F.jobs(self.cluster)
        self.assertEqual(sorted(job['state'] for job in found.values()), ['uncertain', 'verified'])
        lost = next(job for job in found.values() if job['state'] == 'uncertain')
        self.assertEqual(self.wire.creates.get(F.nonce(lost), []), [])
        self.assertEqual(len(self.wire.requests(method='POST')), 2, 'its one transport call, and the other post')
        self.assertEqual(len(lost['discordDispatchIntents']), 1, 'its sealed intent stays for reconciliation')
        self.assertFalse(lost.get('discordUnsentDispatches'))
        self.assertEqual(self.wire.duplicates(), 0)

    def test_control_a_loop_killed_between_seal_and_post_leaves_its_post_uncertain(self):
        """A process that dies after sealing is not the refusal above, even when an embargo blocked its permit too:
        recovery after its lease expires keeps the sealed intent for reconciliation (existing rule), never resends."""
        worker = self.start([F.Tenant(0)], 2)
        limiter = self.hosted.providers['discord'].rate_limiter
        real, killed = limiter.consume, []

        def consume(permit, method, path, **kwargs):
            if permit.binding_hash and not killed:
                killed.append(self.global_429(retry=1))
                raise WorkerDied()
            return real(permit, method, path, **kwargs)
        with patch.object(discord_worker, 'LEASE_SECONDS', 3):
            with patch.object(limiter, 'consume', consume):
                _, failures = F.run_lanes(worker, 1, seconds=30)
            self.assertEqual([type(error) for _, error in failures], [WorkerDied])
            time.sleep(3.5)  # the dead loop's lease expires
            self.drain(worker, 1, seconds=30)
        found = F.jobs(self.cluster)
        self.assertEqual(sorted(job['state'] for job in found.values()), ['uncertain', 'verified'])
        dead = next(job for job in found.values() if job['state'] == 'uncertain')
        self.assertEqual(self.wire.creates.get(F.nonce(dead), []), [])
        self.assertIn('Expired Discord intent requires reconciliation; never repost',
                      [event['message'] for event in dead['events']])
        with self.cluster.connect(autocommit=True) as db:
            blocked = db.execute("SELECT count(*) FROM public.pr_discord_request_admissions WHERE is_publish "
                                 "AND publication_id=%s AND state='blocked' AND sent_at IS NULL", (dead['id'],)).fetchone()[0]
        self.assertEqual(blocked, 1, 'its permit was blocked unsent, and still only an in-call refusal proves that')
        self.assertEqual(self.wire.duplicates(), 0)

    # (l) the lag warning sees every workspace -----------------------------------------------------------------------

    def fill(self, count):
        """`count` workspaces with no Discord work whose ids sort before every synthetic tenant's, so the minute
        tick's report (a sample of the first 256 workspaces by id) is full of them."""
        with self.cluster.connect(autocommit=True) as db:
            for number in range(1, count + 1):
                db.execute('INSERT INTO public.pr_workspaces(id,revision,state) VALUES(%s,1,%s::jsonb)',
                           ('00000000-0000-4000-8000-%012d' % number, json.dumps({'phase2': {'jobs': []}})))

    def test_the_lag_warning_sees_due_work_beyond_the_reports_sample(self):
        tenant = F.Tenant(0)
        self.fill(299)  # 300 workspaces in all; the only Discord post is in the last by id
        F.seed(self.cluster, [tenant], 1, now=self.cluster.now() - 960)  # due eleven minutes ago
        self.wire = F.MockDiscord([tenant])
        self.hosted = F.social(self.cluster, [tenant], self.wire, capacity=200)
        tick, warnings = self.lagging(F.base_worker(self.cluster, self.hosted))
        self.assertTrue(tick['discordParallelLane'])
        self.assertEqual(tick['discordWorker']['queue']['oldestEligibleLagSeconds'], 0.0, 'outside the sample')
        (warning,) = warnings
        self.assertGreater(warning['projectedLagSeconds'], 600)
        self.assertEqual((warning['projection'], warning['report'], warning['laneOwnsDiscord']), ('read', 'sample', True))
        self.assertEqual(self.wire.calls, [], 'the tick itself still leaves Discord to the lane')

    def test_a_queue_report_that_fails_is_a_warning(self):
        self.start([F.Tenant(0)], 1)  # due now: nothing lags
        broken = Counted(self.cluster, refuse=lambda sql: sql.lstrip().startswith('WITH sample AS MATERIALIZED'))
        worker = F.PostgresWorker(broken, social=self.hosted, worker_id='w02-broken-report', discord_workers=True)
        tick, warnings = self.lagging(worker)
        self.assertEqual(tick['discordWorker']['queue']['status'], 'unavailable')
        (warning,) = warnings
        self.assertEqual((warning['report'], warning['oldestEligibleLagSeconds'], warning['projection']),
                         ('unavailable', None, 'read'))
        self.assertLess(warning['projectedLagSeconds'], 300)

    def test_the_minute_tick_still_warns_of_lagging_work_the_idle_shards_cannot_take(self):
        """A loop died holding a lease in a workspace whose other post is long overdue: every shard is idle (one lease
        per workspace, so nothing there is claimable until the lease expires) and the minute tick's lag warning still
        fires from its own sample."""
        tenant = F.Tenant(0)
        F.seed(self.cluster, [tenant], 3, now=self.cluster.now() - 960)  # due eleven minutes ago
        self.wire = F.MockDiscord([tenant])
        self.hosted = F.social(self.cluster, [tenant], self.wire, capacity=200)
        self.worker = F.base_worker(self.cluster, self.hosted)
        self.leave_a_dead_lease('GET', '/channels', before=True)  # the first post sent, the second leased, the third due
        result, counted = self.shard()
        self.assertEqual((result['stoppedBy'], counted.connections, len(counted.statements)), ('idle', 1, 1))
        tick, warnings = self.lagging(self.worker)
        self.assertTrue(tick['discordParallelLane'])
        (warning,) = warnings
        self.assertGreater(warning['oldestEligibleLagSeconds'], 600)
        self.assertEqual((warning['laneOwnsDiscord'], warning['laneBlocker']), (True, None))


if __name__ == '__main__':
    unittest.main()
