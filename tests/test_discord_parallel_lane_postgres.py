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
from contextlib import contextmanager
from unittest.mock import patch

import discord_lane_fixture as F
from postriff_phase2.discord import worker as discord_worker
from postriff_phase2.discord.rate_limits import RateDelayed, SharedPostgresBudget

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
        # thirty have had two attempts. This is the selection's order, whatever the runner's speed. A post released
        # because of the shared budget and claimed again at once (F2) is the same turn, so it counts once.
        ids = [tenant.id for tenant in tenants]
        self.assertEqual([workspace for workspace, _ in self.turns(claims)[:14]], ids + ids, 'two full rounds come first')

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

    EMBARGO = 10  # seconds of the injected global 429: long enough that a loop's next pre-claim read lands inside it

    def embargo_run(self, loop):
        tenants = [F.Tenant(n) for n in range(30)]
        worker = self.start(tenants, 1)
        self.wire.clock = time.time  # request times on the database's clock, to compare with its records
        seen, retry = [], self.EMBARGO

        def fail(method, path):
            if not seen and method == 'GET' and path.endswith('/channels'):
                seen.append(time.time())
                return {'status': 429, 'headers': {'retry-after': str(retry), 'x-ratelimit-global': 'true',
                                                   'x-ratelimit-scope': 'global'},
                        'body': {'message': 'You are being rate limited.', 'retry_after': retry, 'global': True}}
        self.wire.fail = fail
        loop(worker)
        return seen[0]

    def embargo_window(self):
        """When the coordinator recorded the global 429 (its admission's outcome) and when the embargo it set ends."""
        with self.cluster.connect(autocommit=True) as db:
            (recorded,), = db.execute("SELECT extract(epoch from outcome_at)::double precision FROM "
                                      "public.pr_discord_request_admissions WHERE status_code=429").fetchall()
            until = db.execute("SELECT extract(epoch from blocked_until)::double precision FROM public.pr_discord_rate_state "
                               "WHERE kind='global'").fetchone()[0]
        return recorded, until

    def claims_between(self, start, end):
        return [event['at'] for job in F.jobs(self.cluster).values() for event in job['events']
                if event['state'] == 'claimed' and start <= event['at'] < end]

    def test_a_global_429_pauses_every_loop_without_a_retry_storm(self):
        self.embargo_run(lambda worker: self.drain(worker, 4, seconds=40))
        recorded, until = self.embargo_window()
        with self.cluster.connect(autocommit=True) as db:
            admitted = db.execute("SELECT count(*) FROM public.pr_discord_request_admissions WHERE reserved_at>=to_timestamp(%s) "
                                  "AND reserved_at<to_timestamp(%s)", (recorded, until)).fetchone()[0]
        self.assertEqual(admitted, 0, 'from its record to its end, the embargo admits nothing')
        # So only a request admitted before the record can still arrive: at most one per other loop (a loop sends one
        # request at a time, and the loop that got the 429 is recording it).
        during = [call for call in self.wire.calls if recorded <= call[0] < until]
        self.assertLessEqual(len(during), 3, 'inside the embargo only requests already admitted may still arrive')
        found = F.jobs(self.cluster).values()
        self.assertEqual(sorted({job['state'] for job in found}), ['verified'], 'the denied post was not failed or held')
        self.assertEqual(self.wire.duplicates(), 0)
        self.assertFalse([job for job in found if job.get('discordWorker', {}).get('unsentFailures')])

    def test_a_global_429_makes_each_loop_sleep_instead_of_claiming(self):
        waits = []

        def lanes(worker):
            results, _ = F.run_lanes(worker, 4, seconds=40)
            waits.append(sum(r['counters']['rateWaits'] for r in results))
        self.embargo_run(lanes)
        recorded, until = self.embargo_window()
        self.assertGreater(waits[0], 0, 'the loops waited the embargo out')
        # Every iteration reads the coordinator's rows before it claims, so once the embargo is recorded a loop
        # claims at most once more (the iteration whose read came first) and then sleeps until it ends. The old
        # loop claims and releases nearly every due post in the same window (the control below).
        self.assertLessEqual(len(self.claims_between(recorded, until)), 4)

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
        self.assertGreater(len(self.claims_between(*self.embargo_window())), 4, 'more than the lane\'s one per loop')

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

    def test_recovery_after_rate_limits_were_off_waits_and_then_drains_exactly_once(self):
        """The hosted runtime turns Discord authorization off without rate limits: Discord is paused. The frozen minute
        cron used to hold every post it claimed and ask for its destination to be verified again (K1); now each post
        waits unsent, no destination is touched, and the repaired lane sends what is still inside its approval."""
        self.assert_recovered_after_the_push_back(*self.recovery('rate limits off'),
                                                  cooldown=discord_worker.PAUSED_RETRY_SECONDS)
        self.assertEqual(self.destinations(), [], 'no destination was demoted')

    def test_recovery_after_the_coordinator_was_missing_waits_and_then_drains_exactly_once(self):
        """Rate limits on but no coordinator (no policy, or one that does not parse) is reachable only with Discord
        authorization off (runtime_from_environment): paused, as with rate limits off."""
        self.assert_recovered_after_the_push_back(*self.recovery('no coordinator'),
                                                  cooldown=discord_worker.PAUSED_RETRY_SECONDS)
        self.assertEqual(self.destinations(), [], 'no destination was demoted')

    def assert_recovered_after_the_push_back(self, frozen, final, short, cooldown=300):
        for (workspace, _), job in frozen.items():
            operation = job['discordWorker']
            self.assertEqual(operation['releaseReason'], 'rate_delayed')
            self.assertAlmostEqual(operation['rateDelayedUntil'] - operation['releasedAt'], cooldown, delta=1)
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

    def expire_after_the_first_create(self, provider, seconds):
        """The reviewed policy ends `seconds` after the first create reaches Discord, whatever the runner's start-up
        time (a policy that ends a fixed time after the test builds it can end before the loops have sent
        anything). The policy in force is long-lived; the first create's answer replaces it, once, by a short one
        built at that instant, as a deployment whose policy runs out mid-run. Returns the list that receives that
        policy's expiry (empty until the first create)."""
        ended, lock = [], threading.Lock()

        def after(method, path, answer):
            if method == 'POST' and path.endswith('/messages'):
                with lock:
                    if not ended:
                        raw, expires = short_policy(self.cluster.now(), seconds)
                        provider.rate_limiter = SharedPostgresBudget(self.cluster.factory(), F.APP, policy=raw)
                        ended.append(expires)
        self.wire.after = after
        return ended

    def test_a_policy_that_expires_mid_run_stops_every_loop_and_renewal_resumes(self):
        tenants = [F.Tenant(n) for n in range(48)]
        worker = self.start(tenants, 1, latency=.1)
        provider = self.hosted.providers['discord']
        ended = self.expire_after_the_first_create(provider, 4)
        results, failures = F.run_lanes(worker, 4, seconds=60)
        self.assertEqual(failures, [])
        self.assertEqual([r['stoppedBy'] for r in results], ['coordinator_unavailable'] * 4, 'every loop stopped')
        self.assertEqual({r['status']['blocker'] for r in results}, {'coordinator_unavailable'})
        self.assertEqual(len(ended), 1, 'a first create went out, which started the short policy')
        expires = ended[0]
        self.wire.after = None
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
        self.assertEqual(counted.statements, [F.discord_lane._CLAIMABLE])
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
        self.assertEqual(counted.statements[0], F.discord_lane._CLAIMABLE)
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

    def at_the_429(self, real, permit_of, parties=3):
        """Wrap a coordinator step (consume or seal) so that the first `parties` publish permits to reach it wait for
        each other (at most 30 s, well inside a lease), then one global 429 is observed while they all wait. Returns
        the wrapper, the embargo [(observed, until)] and the permit ids that were waiting at that moment."""
        lock, gate, embargo, first, blocked = threading.Lock(), threading.Barrier(parties), [], [], []

        def wrapper(*args, **kwargs):
            permit = permit_of(*args, **kwargs)
            if permit.binding_hash:
                with lock:
                    waits = len(first) < parties
                    if waits:
                        first.append(permit.id)
                if waits:
                    try:
                        gate.wait(timeout=30)
                    except threading.BrokenBarrierError:
                        pass  # a slow loop: the 429 still lands while the others wait
                    with lock:
                        if not embargo:
                            embargo.append(self.global_429(retry=3))
                            blocked.extend(first)
            return real(*args, **kwargs)
        return wrapper, embargo, blocked

    def publications(self, permits):
        """(workspace, publication) of each publish admission among `permits`; at least the one that observed the 429."""
        with self.cluster.connect(autocommit=True) as db:
            keys = {tuple(row) for row in db.execute("SELECT workspace_id::text, publication_id FROM "
                                                      "public.pr_discord_request_admissions WHERE id=ANY(%s::uuid[])",
                                                      (permits,)).fetchall()}
        self.assertEqual(len(keys), len(permits))
        self.assertGreaterEqual(len(keys), 1)
        return keys

    def test_a_global_429_seen_while_posts_are_sealed_sends_each_once_after_the_embargo(self):
        """Three loops each hold a sealed post when a global 429 is observed. consume() refuses each blocked permit
        before any transport, the worker proves the intent unsent from the admission row and releases the post for
        the embargo's remaining time: none is left uncertain, and each is created exactly once, after the embargo."""
        tenants = [F.Tenant(n) for n in range(3)]
        worker = self.start(tenants, 1)
        limiter = self.hosted.providers['discord'].rate_limiter
        consume, embargo, blocked = self.at_the_429(limiter.consume, lambda permit, *rest, **kw: permit)
        with patch.object(limiter, 'consume', consume):
            self.drain(worker, 3, seconds=40)
        found = self.assert_each_created_once_and_verified(3)
        (seen, until), = embargo
        during = [wall for times in self.wire.creates.values() for _, _, wall in times if seen <= wall < until]
        self.assertEqual(during, [], 'no create reached Discord during the embargo')
        for key in self.publications(blocked):  # every post whose sealed permit the 429 blocked (three, unless slow)
            self.assertIn('embargo_blocked_admission',
                          [entry['unsentProof'] for entry in found[key].get('discordUnsentDispatches', [])])
            self.assertIn('A Discord embargo blocked the sealed permit before it was consumed; no POST was started; '
                          'intent archived before safe rate wait', [event['message'] for event in found[key]['events']])

    def test_a_global_429_seen_while_permits_are_reserved_but_not_sealed_sends_each_once_after_it(self):
        """The sibling: three loops each hold a reserved create permit, no intent sealed yet, when a global 429 is
        observed. seal() refuses each blocked permit as a rate wait for the embargo's remaining time: no post is held
        (it used to need a new approval), and each is created exactly once, after the embargo."""
        tenants = [F.Tenant(n) for n in range(3)]
        worker = self.start(tenants, 1)
        limiter = self.hosted.providers['discord'].rate_limiter
        seal, embargo, blocked = self.at_the_429(limiter.seal, lambda cur, permit, *rest, **kw: permit)
        with patch.object(limiter, 'seal', seal):
            self.drain(worker, 3, seconds=40)
        found = self.assert_each_created_once_and_verified(3)
        (seen, until), = embargo
        during = [wall for times in self.wire.creates.values() for _, _, wall in times if seen <= wall < until]
        self.assertEqual(during, [], 'no create reached Discord during the embargo')
        for key in self.publications(blocked):  # every post whose reserved permit the 429 blocked (three, unless slow)
            self.assertIn('A Discord embargo blocked the rate permit before its intent was sealed; frozen approval waits '
                          'without a POST', [event['message'] for event in found[key]['events']])
            self.assertNotIn('embargo_blocked_admission',
                             [entry['unsentProof'] for entry in found[key].get('discordUnsentDispatches', [])],
                             'no intent had been sealed under the blocked permit')

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

    def test_read_backs_deferred_behind_creates_keep_the_lag_warning_off_until_an_hour_but_late_creates_do_not(self):
        """M5: a post created long ago whose read-back still waits is deferred by design (creates are claimed first);
        it must not keep the five-minute warning on. The report tells creates from read-backs; the old field is the
        mixed lag as before."""
        tenants = [F.Tenant(n) for n in range(2)]
        now = self.cluster.now()
        F.seed(self.cluster, tenants[:1], 1)
        F.seed(self.cluster, tenants[1:], 1)  # the second workspace's create; park_create moves its due time
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, capacity=200)
        worker = F.base_worker(self.cluster, self.hosted)
        late = tenants[1].id

        def read_back(age):  # the first workspace's post was created `age` seconds ago; its read-back waits
            self.corrupt(tenants[0].id, lambda job: job.update(state='provider_accepted', nextAt=self.cluster.now() - age))

        def park_create(parked):  # the second workspace's create: due long ago, or not due for an hour
            when = self.cluster.now() - 400 if not parked else self.cluster.now() + 3600
            self.corrupt(late, lambda job: job.update(nextAt=when))
        park_create(True)
        read_back(1500)
        tick, warnings = self.lagging(worker)
        queue = tick['discordWorker']['queue']
        self.assertAlmostEqual(queue['oldestEligibleReadbackLagSeconds'], 1500, delta=30)
        self.assertEqual(queue['oldestEligibleCreateLagSeconds'], 0.0)
        self.assertAlmostEqual(queue['oldestEligibleLagSeconds'], 1500, delta=30, msg='the old field is the mixed lag')
        self.assertEqual(warnings, [], 'only a deferred read-back waits: no warning, as the burst needs')
        # A create due 400 s ago is late whatever the read-back does.
        park_create(False)
        tick, warnings = self.lagging(worker)
        (warning,) = warnings
        self.assertEqual(warning['lateKinds'], ['creates', 'projection'])
        self.assertAlmostEqual(warning['oldestEligibleCreateLagSeconds'], 400, delta=30)
        self.assertAlmostEqual(warning['oldestEligibleReadbackLagSeconds'], 1500, delta=30)
        # A read-back that waits more than an hour is late too.
        park_create(True)
        read_back(3700)
        tick, warnings = self.lagging(worker)
        (warning,) = warnings
        self.assertEqual(warning['lateKinds'], ['readbacks', 'projection'])
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

    # (m) a document the claim cannot read stops only its own workspace (G2E-C-10) ----------------------------------

    def corrupt(self, workspace, damage, *, job=0):
        """Damage one job of a workspace's stored document, the way a bad write or an old migration could."""
        with self.cluster.connect() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,)).fetchone()[0]
            damage(state['phase2']['jobs'][job])
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                       (json.dumps(state), workspace))

    def poisoned(self, damage, *, workspaces=4, bad_posts=2):
        """The workspace first in the claim order (the lowest id, never served) has `bad_posts` due posts, the first
        damaged; the others have one each. Returns (bad tenant, healthy tenants, the damaged post's nonce, worker)."""
        tenants = sorted((F.Tenant(n) for n in range(workspaces)), key=lambda tenant: tenant.id)
        bad, healthy = tenants[0], tenants[1:]
        states = F.seed(self.cluster, [bad], bad_posts)
        F.seed(self.cluster, healthy, 1)
        nonce = F.nonce(states[bad.id]['phase2']['jobs'][0])
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire)
        self.corrupt(bad.id, damage)
        return bad, healthy, nonce, F.base_worker(self.cluster, self.hosted)

    def quarantine_lines(self, logged):
        return [json.loads(record.getMessage()) for record in logged.records
                if 'discord.lane.quarantined' in record.getMessage()]

    def assert_healthy_workspaces_created_once(self, healthy):
        found = F.jobs(self.cluster)
        for tenant in healthy:
            (job,) = [job for (workspace, _), job in found.items() if workspace == tenant.id]
            self.assertEqual(job['state'], 'verified', 'a healthy workspace is served')
            self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1)
        self.assertEqual(self.wire.duplicates(), 0)

    def test_a_job_document_the_claim_cannot_read_stops_only_its_own_workspace(self):
        """Before: a job with `events: null` raised in every claim, and the workspace stayed first in the claim order,
        so the healthy workspaces' due posts were never claimed (G2E-C-10)."""
        bad, healthy, damaged, worker = self.poisoned(lambda job: job.__setitem__('events', None))
        before = F.discord_lane.quarantined()
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            results = self.drain(worker, 1, seconds=30)  # failures, if any, are asserted by drain
        self.assertNotIn('error', {result['stoppedBy'] for result in results}, 'the loop was not stopped by the document')
        self.assert_healthy_workspaces_created_once(healthy)
        self.assertEqual(self.wire.creates.get(damaged, []), [], 'the damaged post was not sent')
        # Counted, and logged as one line with the exception class only.
        self.assertEqual(sum(result['counters']['quarantined'] for result in results), 1)
        (line,) = self.quarantine_lines(logged)
        self.assertEqual(line, {'event': 'discord.lane.quarantined', 'error': 'AttributeError',
                                'quarantineSeconds': F.discord_lane.QUARANTINE_SECONDS})
        raw = '\n'.join(record.getMessage() for record in logged.records)
        found = F.jobs(self.cluster)
        for private in (bad.id, bad.guild, bad.channel, damaged, *[job['id'] for job in found.values()]):
            self.assertNotIn(private, raw, 'no identifier is logged')
        self.assertEqual(F.discord_lane.quarantined() - before, 1)
        self.assertEqual(F.discord_lane.status(self.hosted, time.time())['quarantined'], F.discord_lane.quarantined())
        # Only its rotation cursor changed: dated ahead, behind every other workspace.
        with self.cluster.connect(autocommit=True) as db:
            state, projected = db.execute(
                'SELECT w.state,p.last_claimed_at FROM public.pr_workspaces w JOIN public.pr_discord_worker_projection p '
                'ON p.workspace_id=w.id WHERE w.id=%s', (bad.id,)).fetchone()
        cursor = state['phase2'][discord_worker.CURSOR]
        self.assertGreater(cursor['quarantinedUntil'], self.cluster.now() + F.discord_lane.QUARANTINE_SECONDS - 60)
        self.assertEqual((cursor['lastClaimedAt'], projected), (cursor['quarantinedUntil'], cursor['quarantinedUntil']))
        self.assertEqual([job['state'] for job in state['phase2']['jobs']], ['scheduled', 'scheduled'])
        self.assertIsNone(state['phase2']['jobs'][0]['events'], 'the damaged document is left for a person to repair')

    def test_a_workspace_set_aside_is_skipped_until_its_window_ends_and_a_repaired_document_is_claimed_again(self):
        bad, healthy, damaged, worker = self.poisoned(lambda job: job.__setitem__('attempts', None))
        results = self.drain(worker, 1, seconds=30)
        self.assertEqual(sum(result['counters']['quarantined'] for result in results), 1)
        self.assert_healthy_workspaces_created_once(healthy)
        calls = len(self.wire.calls)
        # Inside the window nothing is read, claimed, counted or logged again, and an idle shard stops at its first look.
        with self.assertNoLogs('postriff.request', 'WARNING'):
            results, failures = F.run_lanes(worker, 2, seconds=30)
        self.assertEqual(failures, [])
        self.assertEqual({r['stoppedBy'] for r in results}, {'idle'})
        self.assertEqual((sum(r['counters']['quarantined'] for r in results), sum(r['counters']['steps'] for r in results)),
                         (0, 0))
        self.assertEqual(len(self.wire.calls), calls, 'no request for the workspace set aside')
        # Repaired, and its window over: the same workspace is claimed again, with no restart or manual step.
        now = self.cluster.now()
        self.corrupt(bad.id, lambda job: job.__setitem__('attempts', []))
        with self.cluster.connect() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (bad.id,)).fetchone()[0]
            state['phase2'][discord_worker.CURSOR].update(quarantinedUntil=now - 1, lastClaimedAt=now - 1)
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                       (json.dumps(state), bad.id))
        self.drain(worker, 1, seconds=30)
        found = F.jobs(self.cluster)
        self.assertEqual(sorted({job['state'] for job in found.values()}), ['verified'])
        self.assertEqual(len(self.wire.creates[damaged]), 1)
        self.assertEqual(self.wire.duplicates(), 0)

    def test_the_malformed_shapes_the_claim_already_handles_never_reach_the_guard(self):
        """The review found six other shapes the existing checks hold or skip without raising. They still do, with
        healthy workspaces claimed after them, and the guard is not involved (nothing is set aside)."""
        shapes = {
            'manifest.discord removed': lambda job: job['manifest'].pop('discord'),
            'manifest.channelId points nowhere': lambda job: job['manifest'].__setitem__('channelId', 'no-such-channel'),
            'manifest removed': lambda job: job.pop('manifest'),
            'nextAt is a string': lambda job: job.__setitem__('nextAt', 'soon'),
            'approvalDigest missing': lambda job: job.pop('approvalDigest'),
            'discordAuthorization removed': lambda job: job.pop('discordAuthorization'),
        }
        for name, damage in shapes.items():
            with self.subTest(name):
                self.cluster.reset()
                bad, healthy, damaged, worker = self.poisoned(damage)
                with self.assertNoLogs('postriff.request', 'WARNING'):
                    results, failures = F.run_lanes(worker, 1, seconds=30)
                self.assertEqual(failures, [])
                self.assertEqual(results[0]['counters']['quarantined'], 0)
                self.assert_healthy_workspaces_created_once(healthy)
                self.assertEqual(self.wire.creates.get(damaged, []), [], 'the damaged post was not sent')

    def test_a_failure_in_every_workspace_is_the_claim_code_not_a_document_and_still_raises(self):
        """Two workspaces are set aside, the third failure in the same claim is raised: a defect that hits every
        workspace is loud (as before), not a queue quietly set aside."""
        tenants = sorted((F.Tenant(n) for n in range(4)), key=lambda tenant: tenant.id)
        F.seed(self.cluster, tenants, 1)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire)
        for tenant in tenants:
            self.corrupt(tenant.id, lambda job: job.__setitem__('events', None))
        lane_worker = F.discord_lane.LaneWorker(F.base_worker(self.cluster, self.hosted), 0)
        with F.no_billing(), self.assertRaises(AttributeError):
            lane_worker.claim(discord_only=True)
        self.assertEqual(lane_worker.discord_stats['quarantined'], F.discord_lane.MAX_QUARANTINES_PER_CLAIM)
        self.assertEqual(self.wire.calls, [])

    # (n) a release the shared budget caused keeps the post's queue position (F2) ------------------------------------

    # One-minute application windows and a three-second permit life: only the releases a test injects are caused by
    # the shared budget. With the reviewed one-second window a permit also ends by itself between the reserve and the
    # seal now and then, which F2 treats the same way and a fixed claim order would have to allow for.
    SLOW_BUDGET = dict(capacity=2000, app_window_seconds=60, permit_ttl_seconds=3)

    def queue_of_three(self):
        """Three workspaces in claim order, one loop: the first has two due posts (A1, A2), the others one each (B1,
        C1). Returns the tenants, the posts' ids as a dict and the worker."""
        tenants = sorted((F.Tenant(n) for n in range(3)), key=lambda tenant: tenant.id)
        states = F.seed(self.cluster, tenants[:1], 2)
        F.seed(self.cluster, tenants[1:], 1)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, **self.SLOW_BUDGET)
        a1, a2 = (job['id'] for job in states[tenants[0].id]['phase2']['jobs'])
        (b1,), (c1,) = ([job_id for (ws, job_id) in F.jobs(self.cluster) if ws == tenant.id] for tenant in tenants[1:])
        return {'A1': a1, 'A2': a2, 'B1': b1, 'C1': c1}, F.base_worker(self.cluster, self.hosted)

    @contextmanager
    def refusing(self, where, post, error, *, times=1):
        """The post's first `times` attempts are refused at `where` the way the shared budget refuses them: a create
        permit it cannot get (reserve), a permit that ended before its intent was sealed (seal) or before it was used
        (consume: the step is slow, the permit's life ends, and the coordinator's own check refuses)."""
        left = [times]

        def now(job_id):
            if job_id == post and left[0] > 0:
                left[0] -= 1
                return True
            return False
        if where == 'reserve':
            real = self.hosted.reserve_discord_send

            def reserve(manifest, **kwargs):
                if now(kwargs['job']['id']):
                    raise error
                return real(manifest, **kwargs)
            with patch.object(self.hosted, 'reserve_discord_send', reserve):
                yield
        elif where == 'seal':
            real = SharedPostgresBudget.seal

            def seal(limiter, cur, permit, binding, intent_id, valid_until):
                if now(binding['publicationId']):
                    raise error
                return real(limiter, cur, permit, binding, intent_id, valid_until)
            with patch.object(SharedPostgresBudget, 'seal', seal):
                yield
        else:
            assert where == 'consume', where
            real = SharedPostgresBudget.consume

            def consume(limiter, permit, method, path, *, binding=None, intent_id=None, authorize=None):
                if now(binding['publicationId']):
                    time.sleep(self.SLOW_BUDGET['permit_ttl_seconds'] + .3)
                return real(limiter, permit, method, path, binding=binding, intent_id=intent_id, authorize=authorize)
            with patch.object(SharedPostgresBudget, 'consume', consume):
                yield

    @staticmethod
    def turns(claims):
        """The claims with each immediate repeat of the same post taken out: a retry that kept its place is the same
        turn again, so what is left is the order in which workspaces were served."""
        return [claim for index, claim in enumerate(claims) if index == 0 or claim != claims[index - 1]]

    def post(self, post_id):
        return next(job for (_, job_id), job in F.jobs(self.cluster).items() if job_id == post_id)

    def test_a_post_the_shared_budget_released_is_claimed_again_before_anything_else(self):
        """The 5,000-post run: a create permit that ended unused sent its post behind its never-claimed sibling and its
        workspace to the back of the round (median re-claim delay 729 s). Now the retry is the very next claim."""
        for where, error in (('reserve', RateDelayed(2.0, scope='application')),
                             ('seal', RateDelayed(.05, cause='permit_expired')),
                             ('consume', None)):
            with self.subTest(where):
                self.cluster.reset()
                posts, worker = self.queue_of_three()
                with self.refusing(where, posts['A1'], error):
                    self.drain(worker, 1, seconds=90)
                claims = [job_id for _, job_id in self.claim_order()]
                self.assertEqual(claims[:2], [posts['A1']] * 2, 'A1 again at once')
                self.assertEqual([self.names(posts, job_id) for job_id in self.turns(claims)[:4]], ['A1', 'B1', 'C1', 'A2'],
                                 'and the round goes on in order')
                self.assertEqual(self.post(posts['A1'])['discordPositionRestores'], 1)
                self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])
                self.assertEqual(self.wire.duplicates(), 0)
                self.assertEqual(len(self.wire.creates[F.nonce(self.post(posts['A1']))]), 1, 'sent once, after the retry')

    @staticmethod
    def names(posts, job_id):
        return next(name for name, wanted in posts.items() if wanted == job_id)

    def test_control_the_old_penalty_sends_the_released_post_behind_its_sibling_and_the_round(self):
        # What the same release did before: the claim's stamps stayed, so the retry waits for the round and for A2.
        posts, worker = self.queue_of_three()
        with patch.object(F.discord_lane.LaneWorker, '_discord_rate_released', lambda *args, **kwargs: None):
            with self.refusing('reserve', posts['A1'], RateDelayed(2.0, scope='application')):
                self.drain(worker, 1, seconds=90)
        claims = [job_id for _, job_id in self.claim_order()]
        self.assertEqual([self.names(posts, job_id) for job_id in claims[:5]], ['A1', 'B1', 'C1', 'A2', 'A1'])
        self.assertNotIn('discordPositionRestores', self.post(posts['A1']))

    def test_a_release_caused_by_one_tenants_resource_keeps_its_penalty(self):
        """Otherwise workspaces sharing a full channel could take their turn over and over."""
        causes = (('a learned channel window', 'reserve', RateDelayed(.2, scope='learned_route')),
                  ('an unknown route', 'reserve', RateDelayed(.2, scope='unknown_route')),
                  ('the cold-route probe', 'reserve', RateDelayed(.2, scope='discovery')),
                  ('a guild-scoped embargo', 'reserve', RateDelayed(.2, scope='embargo')),
                  ('a provider 429', 'reserve', RateDelayed(.2, cause='provider_429')),
                  ('a window about to end', 'reserve', RateDelayed(.2, cause='window_expiring', scope='permit')),
                  ('an embargo that blocked the permit', 'seal', RateDelayed(.2, cause='permit_blocked', scope='embargo')))
        for name, where, error in causes:
            with self.subTest(name):
                self.cluster.reset()
                posts, worker = self.queue_of_three()
                with self.refusing(where, posts['A1'], error):
                    self.drain(worker, 1, seconds=90)
                claims = [job_id for _, job_id in self.claim_order()]
                self.assertNotEqual(claims[1], posts['A1'], 'not claimed again at once')
                self.assertEqual([self.names(posts, job_id) for job_id in claims[:4]], ['A1', 'B1', 'C1', 'A2'],
                                 'the penalty: behind the round and its sibling')
                self.assertNotIn('discordPositionRestores', self.post(posts['A1']))
                self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])

    def test_a_transient_preflight_failure_keeps_its_penalty(self):
        posts, worker = self.queue_of_three()
        real, seen = self.hosted.prepare_discord_dispatch, []

        def prepare(manifest, **kwargs):
            if manifest['discord']['publicationId'] == posts['A1'] and not seen:
                seen.append(1)
                raise TimeoutError('synthetic preflight timeout')
            return real(manifest, **kwargs)
        with patch.object(self.hosted, 'prepare_discord_dispatch', prepare):
            self.drain(worker, 1, seconds=90)
        claims = [job_id for _, job_id in self.claim_order()]
        self.assertEqual([self.names(posts, job_id) for job_id in claims[:5]], ['A1', 'B1', 'C1', 'A2', 'A1'])
        self.assertNotIn('discordPositionRestores', self.post(posts['A1']))

    def test_the_position_is_kept_three_times_for_one_post_and_then_the_penalty_applies(self):
        posts, worker = self.queue_of_three()
        with self.refusing('reserve', posts['A1'], RateDelayed(2.0, scope='application'), times=4):
            self.drain(worker, 1, seconds=90)
        claims = [job_id for _, job_id in self.claim_order()]
        self.assertEqual([self.names(posts, job_id) for job_id in claims[:8]], ['A1', 'A1', 'A1', 'A1', 'B1', 'C1', 'A2', 'A1'],
                         'three retries kept the place; the fourth release cost the turn')
        self.assertEqual(self.post(posts['A1'])['discordPositionRestores'], 3)
        self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])

    def fair_queue(self):
        """The fairness queue with a smaller busy workspace (8 posts, first by id) and six of two posts each."""
        tenants = sorted((F.Tenant(n) for n in range(7)), key=lambda tenant: tenant.id)
        F.seed(self.cluster, tenants[:1], 8)
        F.seed(self.cluster, tenants[1:], 2)
        self.wire = F.MockDiscord(tenants)
        self.hosted = F.social(self.cluster, tenants, self.wire, **self.SLOW_BUDGET)
        return tenants, F.base_worker(self.cluster, self.hosted)

    def expire_every_fourth_permit(self, injected):
        real = SharedPostgresBudget.seal
        count = [0]

        def seal(limiter, cur, permit, binding, intent_id, valid_until):
            count[0] += 1
            if count[0] % 4 == 0:
                injected.append((binding['publicationId'], len(self.claim_order())))
                raise RateDelayed(.05, cause='permit_expired')
            return real(limiter, cur, permit, binding, intent_id, valid_until)
        return patch.object(SharedPostgresBudget, 'seal', seal)

    def test_permit_expiries_do_not_change_the_rotation_or_any_workspaces_share_of_the_work(self):
        """The busy-workspace fairness run with every fourth create permit ending unused. Each such release is
        retried at once, and taking those retries out leaves the round-robin order untouched: a restored turn is
        the same claim again, not an extra one, so no tenant completes more work than without the expiries."""
        tenants, worker = self.fair_queue()
        injected = []
        with self.expire_every_fourth_permit(injected):
            self.drain(worker, 1, seconds=90)
        claims = self.claim_order()
        self.assertGreaterEqual(len(injected), 4, 'the expiries happened')
        for post, claimed_so_far in injected:
            self.assertEqual(claims[claimed_so_far][1], post, 'the retry is the very next claim')
        self.assert_rotation(tenants, claims)
        self.assertEqual(sorted({job['state'] for job in F.jobs(self.cluster).values()}), ['verified'])
        self.assertEqual(self.wire.duplicates(), 0)
        shares = {tenant.id: sum(1 for creates in self.wire.creates.values() if creates and creates[0][1] == tenant.channel)
                  for tenant in tenants}
        self.assertEqual(shares, {tenants[0].id: 8, **{tenant.id: 2 for tenant in tenants[1:]}})

    def test_control_without_the_restore_the_same_expiries_cost_every_released_post_its_turn(self):
        tenants, worker = self.fair_queue()
        injected = []
        with patch.object(F.discord_lane.LaneWorker, '_discord_rate_released', lambda *args, **kwargs: None):
            with self.expire_every_fourth_permit(injected):
                self.drain(worker, 1, seconds=90)
        claims = self.claim_order()
        early = [(post, claimed_so_far) for post, claimed_so_far in injected if claimed_so_far < 12]  # others still due
        self.assertGreaterEqual(len(early), 2)
        for post, claimed_so_far in early:
            self.assertNotEqual(claims[claimed_so_far][1], post, 'the retry waits behind the other workspaces')

    # (o) no second lease renewal after the seal (F5) --------------------------------------------------------------

    RENEWED = 'Hosted worker renewed the same Discord fence'

    def change_between_seal_and_create(self, change):
        """One post, one loop. `change(job)` is applied to the stored post after its intent was sealed and just before
        its create permit is consumed, the window the second lease renewal used to cover. Returns the post, the lane
        results and the states of the request admissions."""
        tenant = F.Tenant(0)
        worker = self.start([tenant], 1)
        real = SharedPostgresBudget.consume

        def consume(limiter, permit, method, path, *, binding=None, intent_id=None, authorize=None):
            self.corrupt(tenant.id, change)
            return real(limiter, permit, method, path, binding=binding, intent_id=intent_id, authorize=authorize)
        with patch.object(SharedPostgresBudget, 'consume', consume):
            results = self.drain(worker, 1, seconds=30)
        (job,) = F.jobs(self.cluster).values()
        with self.cluster.connect(autocommit=True) as db:
            admissions = [state for (state,) in db.execute('SELECT state FROM public.pr_discord_request_admissions WHERE is_publish')]
        return job, results, admissions

    def assert_sealed_unsent_and_renewed_once(self, job, admissions):
        self.assertEqual(self.wire.requests(method='POST'), [], 'no POST started')
        self.assertEqual(len(job['discordDispatchIntents']), 1, 'the sealed intent is kept')
        self.assertEqual(admissions, ['sealed'], 'the permit was never consumed')
        self.assertEqual(sum(event['message'] == self.RENEWED for event in job['events']), 1,
                         'renewed once, after the preflight; not again after the seal')
        self.assertEqual(job['state'], 'uncertain')

    def test_a_withdrawal_after_the_seal_is_caught_by_the_consume_guard_not_a_second_renewal(self):
        job, results, admissions = self.change_between_seal_and_create(lambda job: job.__setitem__('cancelRequested', True))
        self.assert_sealed_unsent_and_renewed_once(job, admissions)
        first = next(event for event in job['events'] if event['state'] == 'uncertain')
        self.assertEqual(first['message'], 'Discord delivery is uncertain. Reconcile before any further publication.',
                         'the guard refused the create; before, the renewal ended the step "authority changed during renewal"')
        self.assertEqual(sum(r['counters']['uncertainCreates'] for r in results), 1)
        self.assertEqual(sum(r['counters']['leaseLost'] for r in results), 0)

    def test_a_lease_lost_after_the_seal_ends_uncertain_without_a_post_and_keeps_the_intent(self):
        job, results, admissions = self.change_between_seal_and_create(lambda job: job.__setitem__('leaseUntil', time.time() - 5))
        self.assert_sealed_unsent_and_renewed_once(job, admissions)
        first = next(event for event in job['events'] if event['state'] == 'uncertain')
        self.assertEqual(first['message'], 'Expired Discord intent requires reconciliation; never repost',
                         'the guard refused the create; the expiry recovery of the next claim records it')
        self.assertEqual(sum(r['counters']['uncertainCreates'] for r in results), 1, 'the guard refusal is counted')
        self.assertEqual(self.wire.duplicates(), 0)

    def test_the_minute_workers_step_still_renews_after_the_seal(self):
        # F5 is the lane worker's alone: the base worker (the minute cron's frozen path) renews twice, as before.
        tenant = F.Tenant(0)
        worker = self.start([tenant], 1)
        with F.no_billing():
            while worker.step(discord_only=True):
                pass
        (job,) = F.jobs(self.cluster).values()
        self.assertEqual(sum(event['message'] == self.RENEWED for event in job['events']), 2)
        self.assertEqual(len(self.wire.creates[F.nonce(job)]), 1, 'created once; its read-back is not due yet')

    # (p) a paused Discord is a wait, not a verdict about a post (K1) ---------------------------------------------

    def pause(self, how):
        provider = self.hosted.providers['discord']
        if how == 'execution disabled':  # POSTRIFF_OAUTH_DISCORD_DISABLED, the abort ladder's kill switch
            provider.execution_enabled = False
        else:
            provider.authorization_v2_enabled = False

    def unpause(self):
        provider = self.hosted.providers['discord']
        provider.execution_enabled = provider.authorization_v2_enabled = True

    def paused_queue(self, how):
        tenants = [F.Tenant(n) for n in range(4)]
        worker = self.start(tenants, 2)
        self.pause(how)
        return tenants, worker

    def assert_waiting_untouched(self):
        found = F.jobs(self.cluster)
        self.assertEqual(sorted({job['state'] for job in found.values()}), ['scheduled'])
        self.assertEqual(self.destinations(), [], 'no destination was demoted')
        self.assertEqual(self.wire.calls, [], 'nothing reached Discord')

    def assert_all_created_once_after_the_pause(self, worker, count):
        self.unpause()
        self.skip_push_back()
        self.drain(worker, 2, seconds=60)
        self.assert_each_created_once_and_verified(count)
        self.assertEqual(self.destinations(), [])

    def test_a_paused_discord_is_not_claimed_by_the_lane_and_nothing_is_lost(self):
        """Before: with the kill switch on, the lane claimed every due post, the preflight refused with a pause, and
        each post was held with its destination demoted: after the switch was off again nothing posted and every
        customer had to authorize again (4 of 4 destinations, 8 of 8 posts in the review's run)."""
        for how in ('execution disabled', 'authorization off'):
            with self.subTest(how):
                self.cluster.reset()
                tenants, worker = self.paused_queue(how)
                results, failures = F.run_lanes(worker, 2, seconds=30)
                self.assertEqual(failures, [])
                self.assertEqual({result['stoppedBy'] for result in results}, {'discord_paused'})
                self.assertEqual(sum(result['counters']['claimed'] for result in results), 0, 'nothing was claimed')
                self.assert_waiting_untouched()
                self.assert_all_created_once_after_the_pause(worker, 8)

    def test_a_paused_discord_is_a_wait_for_the_minute_cron_too_never_a_hold(self):
        """The frozen minute cron (lane flag off, or the lane unable to run) also claims Discord. A pause there
        released each post unsent for a minute at a time instead of holding it and demoting its destination."""
        for how in ('execution disabled', 'authorization off'):
            with self.subTest(how):
                self.cluster.reset()
                tenants, worker = self.paused_queue(how)
                for _ in range(2):
                    self.minute(worker, flag=False)
                self.assert_waiting_untouched()
                found = F.jobs(self.cluster)
                released = [job for job in found.values() if job['discordWorker'].get('releaseReason') == 'rate_delayed']
                self.assertGreaterEqual(len(released), 4, 'the cron touched posts and released them')
                for job in released:
                    operation = job['discordWorker']
                    self.assertAlmostEqual(operation['rateDelayedUntil'] - operation['releasedAt'],
                                           discord_worker.PAUSED_RETRY_SECONDS, delta=1)
                    self.assertEqual(job['nextAction'], 'Await Discord shared rate budget; no POST occurred and this approval remains frozen')
                    self.assertEqual(discord_worker.attempt_count(job), 0, 'a pause is not an attempt')
                self.assert_all_created_once_after_the_pause(worker, 8)

    def test_a_revoked_connection_still_holds_the_post_and_asks_for_the_destination_again(self):
        """Only a pause became a wait: a real revocation or a missing permission is another error and holds as before."""
        tenants = [F.Tenant(n) for n in range(2)]
        worker = self.start(tenants, 1)
        revoked, real = tenants[0].id, self.hosted.oauth.discord_grant_for_worker

        def grant(workspace, connection, *, cur=None):
            if workspace == revoked:
                raise F.P.AlphaError('Discord authorization was revoked.', 409)
            return real(workspace, connection, cur=cur)
        with patch.object(self.hosted.oauth, 'discord_grant_for_worker', grant):
            self.drain(worker, 1, seconds=30)
        found = F.jobs(self.cluster)
        self.assertEqual({workspace: job['state'] for (workspace, _), job in found.items()},
                         {revoked: 'held', tenants[1].id: 'verified'})
        self.assertEqual(self.destinations(), ['verification_required'])


if __name__ == '__main__':
    unittest.main()
