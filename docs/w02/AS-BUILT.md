# W-02 parallel Discord sending: as built (Phase 1)

Branch `claude/discord-w02-parallel-20261023`, from the frozen release candidate `2a5a523d`. Engineering only: nothing is
deployed, no setting or secret is changed, and the lane does nothing until its flag is set on a new, separately approved
build. Labels: [measured] local real-PostgreSQL runs with a mock Discord; [simulated] the fake-clock model; [reasoned]
read from the code.

## What changed

| File | Change |
|---|---|
| `src/postriff_phase2/discord/lane.py` (new) | The lane: flag and budget parsing, shard parsing, the readiness test (`blocker`), one bounded loop per invocation, the pre-claim coordinator read, the bounded wait for a refused create permit, per-invocation counters and the log line; the minute cron's lag warning (`warn_if_lagging`); the health status (`status`); the worker's guard for a document it cannot read (`LaneWorker.claim`). |
| `src/postriff_phase2/hosted_worker.py` | `tick()` passes `exclude_discord=True` when the lane is on and the static part of `lane.blocker()` says it can run (the minute cron then does not claim Discord), and whenever Discord is paused (`lane.paused()`, with the lane off or on but unable to run), and with the lane on adds the health status (`discordLaneStatus`) and logs the lag warning from its own report and, when the lane owns Discord, the projection; `_tick` accepts that keyword. With the lane off, or on but unable to run, the code path is the old one, proven against the frozen source (below), with one deliberate exception: a paused Discord is a wait, not a hold, and the tick leaves it alone ("A paused Discord is a wait"). After review: the seal path and the unsent-permit recovery also release a permit an embargo or hold blocked before it was used ("A permit an embargo blocks before it is used"); the three releases for a rate wait call a hook that does nothing here and that the lane's worker uses to keep a post's place ("A release the shared budget caused keeps its place"). |
| `src/postriff_phase2/discord/rate_limits.py`, `src/postriff_phase2/social_connectors.py` | After review, at the coordinator's request: `seal()` and `consume()` refuse a reserved or sealed permit that an embargo or hold blocked, before any transport, as `permit_blocked` (with the embargo's remaining time), `confirm_blocked_publish()` proves such an intent unsent from its admission row, and the sender turns that refusal into the same pre-transport signal as an expired unconsumed permit ("A permit an embargo blocks before it is used", below). |
| `rate_limits.py`, `social_connectors.py`, `hosted_social.py`, `discord/lane.py`, `discord/ops.py` (limiter branch, after the first hosted measurement) | Booking: the lane's preflight reads, create permit and read-back are given the next exact slot of a full application window and wait for it inside the coordinator, instead of being refused and asking again; two lane counters and a health section show it ("Booking", below; Q19). |
| `src/postriff_phase2/hosted_app.py` | Route `GET /api/cron/discord-worker/<shard>`: cron secret checked before the runtime starts (as the YouTube lanes); flag read per request; the request log files it under `cron`. |
| `vercel.json` | 12 cron entries `/api/cron/discord-worker/0` to `/11`, every minute. `git.deploymentEnabled` stays `false`; nothing else changed. |
| `scripts/check_postriff_hosted_preflight.py` | The cron check accepts exactly the worker plus these 12 shards. A `discord-parallel-lane` check fails when the lane flag is on without `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` or without the worker lease protocol. A `discord-worker-protocol` check fails when any Discord feature flag is on (authorization v2, connections v2, rate limits, webhook, user install, engagement, the lane) and `POSTRIFF_DISCORD_WORKER_V1_ENABLED` is not 1 or true ("The worker flag and migration 128"). |
| `scripts/discord_lane_capacity_sim.py` (new) | The capacity simulation (model and real run). |
| `tests/test_discord_parallel_lane.py` (new) | 104 offline tests (run under the synthetic fence). |
| `tests/test_discord_worker_lifecycle.py` | Its in-memory database double answers the lane's projection due probe. |
| `tests/test_discord_parallel_lane_postgres.py`, `tests/discord_lane_fixture.py` (new) | 62 real-PostgreSQL tests and their fixture; skipped under the fence. |
| `tests/phase2/fixtures/hosted_worker_2a5a523d.py.txt` (new) | The frozen worker source, pinned by SHA-256, for the flag-off equivalence test. |
| `docs/w02/*` (new) | This file, the corrected plan, open questions, monitors, simulation results. |

No migration, no new table, no new queue; the claim, the lease protocol, the approval checks and the launch gate are
unchanged. One change to the coordinator and the sender, made after review at the coordinator's request: a permit that
an embargo or hold blocked before it was used, sealed or not, is proven unsent and released ("A permit an embargo
blocks before it is used").

## Flags and limits

| Name | Meaning | Default |
|---|---|---|
| `POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED` | Lane on. Exact string `true` (like the other Discord flags); also needs `POSTRIFF_DISCORD_WORKER_V1_ENABLED` on (`1` or `true`), whose lease protocol the lane uses. | off |
| `POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS` | How long one invocation admits new steps: at least 5; a value above 90 is clamped to 90. | 50 |
| `POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_STEPS` | Steps per invocation, 1 to 5,000 (a backstop). | 600 |

A misconfigured budget (under 5 seconds, not a number, or steps out of range) answers 503 `discord_lane_configuration`
and claims nothing; the minute cron then keeps Discord (`configuration`).

Prerequisites. The lane runs only with all of these; while any is missing the shard loops claim nothing. The minute
cron keeps Discord when one of the first four is missing (not when only its own process's coordinator is degraded);
it cannot see the last three, which is what the lag warning is for:

- `POSTRIFF_DISCORD_WORKER_V1_ENABLED` on (1 or true): the lease protocol the lane uses. Without it the lane flag has no effect, and the preflight requires it whenever any Discord feature flag is on ("The worker flag and migration 128").
- `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` (exact string): the shared coordinator that admits every request.
  Without it the loops stop with `coordinator_unavailable`, and the hosted runtime also turns Discord authorization
  off, so the minute cron holds each due Discord post and asks for its destination to be verified again (today's
  behaviour with rate limits off). The preflight fails this combination.
- A reviewed policy in `POSTRIFF_DISCORD_RATE_POLICY` that is valid now (`issued_at` to `expires_at`, at most 31 days;
  judge and renew it with `scripts/discord_rate_policy.py`). Outside it every Discord request is refused.
- A valid lane budget (above).
- `CRON_SECRET` of at least 16 ASCII characters (the preflight asks for 32): the shard routes answer 401 to anything
  else before any work.
- The 12 cron entries reaching the function: registered from `vercel.json` on the production deployment, not stopped
  by Deployment Protection, answering 200. A cron that never runs logs nothing; the lag warning is the signal.
- Migration 126's projection (applied in production), or the loops stop with `schema`.

Rollout order (each deployment is a separately approved release step under the on-demand deployment policy):

1. Deploy a build with the lane flag off. The 12 shards answer `{"enabled": false}` without starting the runtime:
   12 `request.completed` lines a minute with route `cron` and status 200.
2. Confirm `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` and a policy that is not expired (and not about to be), with
   the preflight's `discord-parallel-lane` check and `scripts/discord_rate_policy.py`.
3. Set `POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED=true` and redeploy (environment changes reach new deployments only).
4. Confirm 12 `discord.lane.completed` lines a minute, `stoppedBy` `idle`, `time_budget` or `rate_wait`; the minute
   cron's result shows `discordParallelLane: true`; no `discord.lane.lagging` lines.
5. To stop fast: the operator hold on the policy row (Turning it off, below). Every loop stops before its next claim;
   the minute cron cannot see the hold and keeps leaving Discord alone, so posts wait.
6. To stop fully: redeploy, or promote the previous build, with the flag off.

Time limit [reasoned, tested offline]: `api/index.py` may run 300 s (`vercel.json`). One step admitted just before the
deadline may still make seven Discord requests at the transport's 20-second timeout plus its transactions (160 s
reserved), a cold start's imports run before the budget starts (20 s reserved), and 30 s are left as a margin, so the
budget is capped at 300 − 160 − 20 − 30 = 90 s. The margin is room, not a bound: the default database factory
(`hosted_app.postgres_factory`) opens a connection per transaction with an 8-second connect timeout and sets no
`statement_timeout` (only the coordinator's own transactions set one), so nothing caps a step's database time by
itself. The loop checks the deadline before every claim and never interrupts a step. Default 50 s keeps each shard to
about one loop at a time under the one-minute cron.

## The fan-out: 12 cron shards (chosen) versus a self-chaining dispatcher

Chosen: each cron entry starts one loop every minute, so one minute starts K = 12 concurrent loops. The entries use
path segments (`/api/cron/discord-worker/3`), the pattern Vercel documents for one handler in several cron jobs; the
brief's `?shard=i` query form is not documented for cron paths. A shard number only names the loop; every loop claims
any due work. The route accepts shards 0 to 31.

| | K cron shards (built) | Self-chaining dispatcher (not built) |
|---|---|---|
| Concurrency | fixed K per minute; bounded by configuration | grows with the queue; needs its own global counter to bound it |
| Cost when idle | K invocations a minute (about 17,000 a day at K = 12), each answers in milliseconds with the flag off; with it on, one connection for one statement when nothing is due (none when the lane cannot run) | one invocation a minute |
| Failure | a lost or failed invocation is replaced next minute | a broken chain waits for the next cron minute; a bug can fan out without bound |
| Moving parts | none new: the platform's scheduler | authenticated HTTP calls from the function to its own deployment URL (Deployment Protection, URL discovery, a bypass secret), chain-depth fencing |
| Throughput | up to 50 of every 60 seconds per loop | continuous |

The dispatcher's only real gain is the last row; the model puts the duty-cycle cost at about 10 to 15 percent of drain
time [simulated]. It adds a new path that can multiply invocations, which the cost policy forbids doing casually.

## What one invocation does

1. Route: cron secret (before any runtime or database work), shard check, flag check. Off: `{"enabled": false}`.
2. A fresh worker instance with its own lease owner id (`discord-lane-<shard>-<random>`) and its own counters, sharing
   the process's connection factory, provider, approval checks and completion hooks.
3. A first look before any claim. The readiness test `lane.blocker()` on this process's clock, with no database: a lane
   that cannot run stops here with its reason and its WARNING line, every minute. Then one statement on one
   connection: the database clock and the soonest `next_at` in the projection (migration 126, applied in production;
   without the table the loop stops with `schema`) over the workspaces not set aside (`_CLAIMABLE`; "A document the
   claim cannot read", below), and the readiness test again on that clock. If nothing is due
   within 10 seconds the invocation stops (`idle`) before the coordinator read and before any claim [measured: one
   connection and one statement, where it used to open four connections for seven statements;
   `test_an_idle_shard_opens_one_connection_for_one_statement`]. The loop claims only through the projection's due
   rows (`due_workspaces_sql`, a row whose `next_at` has passed), so this skips nothing it could have claimed: work
   that becomes due later is taken by the next minute's invocations, as before when a loop stopped `idle` after a
   claim miss. When it stops here, the coordinator's hold and embargo are not read (there is nothing to send), so an
   idle shard reports `idle` where it would have said `operator_hold`; the health status, which reads no database,
   and the minute tick's lag warning are unchanged.
4. Loop until the budget, the step backstop, or a stop condition:
   - the readiness test `lane.blocker()` (the minute tick asks its static part, below), with this process's clock
     and then the database clock: rate limits off, or no coordinator, or a policy outside its validity stops the loop
     (`coordinator_unavailable`); a process whose coordinator lost an observation stops its own loops
     (`coordinator_degraded`); a paused Discord (execution disabled, authorization off) stops them before any claim
     (`discord_paused`, "A paused Discord is a wait");
   - read the coordinator's four application-wide rows without locks (policy, bot global, bot credential, invalid
     budget), using the coordinator's own key derivation. A manual hold on the policy row stops the loop
     (`operator_hold`); a hold on another of them (the coordinator holds the credential row after a 401) stops it too
     (`coordinator_hold`); an active block or circuit on any of them, or a capped row with nothing left until its reset
     (the application window or the invalid-request budget: the coordinator refuses on either), is slept out (with
     jitter) before claiming, or ends the loop if it outlasts the budget (`rate_wait`);
   - one existing Discord-only step (`PostgresWorker.step(discord_only=True)`): claim one job from the least recently
     served due workspace (`FOR UPDATE ... SKIP LOCKED`, at most one live Discord lease per workspace), the permission
     preflight, lease renewal (once; the seal extends the lease itself, "The lease after the seal"), the create permit,
     the sealed intent, the create, the fenced completion; or a read-back;
   - if nothing could be claimed: sleep until the soonest due work if it is within 10 seconds (a read-back is due five
     seconds after its create), back off briefly if work is overdue but held by another loop, and stop (`idle`) after six
     misses or when nothing is due soon.
5. One log line, `discord.lane.completed`: shard, `stoppedBy`, elapsed seconds and counts only (claimed, posted,
   verified, held, uncertain, rateDelayed, leaseLost, recoveries, retries, deadLetters, claimMisses, rejected, notSent,
   uncertainCreates, rateWaits, idleWaits, permitWaits, quarantined, positionsKept, bookedWaits, bookedSeconds). No workspace, job, channel, content or lease owner id. An
   exception is logged with its class name only and re-raised, so the request returns 500 with its failure site.

The behavioural addition inside a step has two layers. First, booking ("Booking", below): the preflight's reads, the create
permit and the read-back are asked for inside `rate_limits.booking()`, so where the application window is full each is given
the next exact slot, at most one second ahead, and waits for it inside the coordinator. Second, the older bounded wait stays
for what a booking cannot cover (the booked horizon full, or a permit that lapsed while it was being stored): when the create
permit is refused because the application window is spent, the lane's worker waits for the next window (at most one second,
the same bound reads already have) instead of releasing the job. Without any wait, at a saturated budget each refused create
re-spends its four preflight reads and almost nothing is created [measured: with the wait off, see CAPACITY-SIMULATION.md].
Both happen before any intent is sealed, the job keeps its live lease, and the step rechecks every fence afterwards. Any other
refusal (an embargo, a channel window, a passed lease or approval deadline) releases the job as before.

The existing minute cron, with the flag on and the lane able to run, runs every other provider exactly as before and
does not claim Discord (`exclude_discord`). "Able to run" is the static part of `lane.blocker()`
(`process_state=False`), one implementation with the full rule every lane iteration asks: a valid lane budget,
`POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED` on, and a shared coordinator whose reviewed policy is valid now. A coordinator
degraded in the minute cron's own process does not count: that process cannot send either (every request there is
refused before transport), so the tick still leaves Discord to the lane loops of healthy processes, and the loops of
the degraded process stop themselves (`coordinator_degraded`, the full rule). The test reads no database, so the
minute tick cannot see an operator hold (the lane stops on it and the tick still leaves Discord alone, which is what a
hold asks for) or a missing projection (the lane stops with `schema`; the lag warning below catches it), nor whether
the shard crons fire at all. Otherwise, and with the flag off, the tick is byte-for-byte the frozen code path
[measured: the equivalence test runs the frozen `hosted_worker.py` and this one side by side on the same inputs and
compares every SQL statement and parameter, every Discord request, the final state and the tick result; with the flag
off, and with the flag on but rate limits off, no coordinator, an expired or not-yet-valid policy or a bad lane
budget; the one addition is the lag warning's log line]. With a bad lane budget the frozen path sends as before. In the
coordinator states it cannot send in the hosted runtime either, but it records that on every post instead of leaving
them silently scheduled: with rate limits off `runtime_from_environment` turns Discord authorization off, so Discord is
paused. The frozen code held each claimed post and set its destination to `verification_required` [measured with the
frozen tick]; the tick now claims no Discord post while it is paused and touches nothing ("A paused Discord is a
wait"). Otherwise each request is refused and the post released for five minutes, held once that passes its approval
[reasoned].

Keeping Discord to one scheduler is a preference, not a safety property. The lease protocol (one live Discord lease per
workspace, the lease owner and lease id rechecked at every step, an intent sealed before any create) makes the minute
cron and lane loops safe together. They can overlap already: a person's "post now" runs the same step beside both,
and at a policy's edges two processes' clocks may disagree [reasoned]. A degraded coordinator is deliberately not a
reason to overlap: if the minute cron of a degraded process took Discord back, it could not send either; its frozen
path would claim up to about five Discord posts a minute and release each for five minutes (holding those near the
end of their approval) while lane loops in healthy processes could have sent them [reasoned]. Instead that process
leaves Discord to the lane, and only its own loops stop.

## Safety properties and their evidence

| Property | How | Test (file: real PostgreSQL unless noted) |
|---|---|---|
| Every post created exactly once, none skipped, with 8 loops over 120 posts | existing claim, lease and sealed-intent protocol, unchanged | `test_many_loops_create_every_post_exactly_once` |
| Loops racing on one workspace | one live Discord lease per workspace | `test_loops_racing_on_one_workspace_send_one_post_at_a_time` |
| A loop dies before its intent | lease expires; the job is released as provably unsent and sent once | `test_a_loop_that_dies_before_its_intent_is_recovered_and_sent_once` |
| A loop dies after Discord accepted, or as the create leaves | the sealed intent forbids a new create; the job is reconciled by hand ('uncertain') | `test_a_loop_that_dies_after_discord_accepted_...`, `..._as_its_create_leaves_...` |
| Request rate across all loops | the shared coordinator admits every request; 12 loops at a 3 per second policy met the cap (they waited for the next window) and never passed 6 in any second (earlier runs at 10 per second never passed 20) | `test_the_coordinator_caps_the_request_rate_across_all_loops`, with a control that the same run exceeds it when the policy allows |
| Permits of a dead loop | unused permits expire with their window; a request that died in flight keeps its slot (existing rule, Q3) | `test_permits_of_a_dead_loop_that_were_never_used_free_their_slots`, `test_a_read_whose_process_died_...` |
| One busy workspace cannot starve the others | least-recently-served rotation plus one lease per workspace | `test_one_busy_workspace_cannot_starve_the_others` (one loop's first 14 claims are two rounds over all 7 workspaces), with a control ordering by id (all 30 busy posts are claimed before any other workspace) |
| A channel's create limit (5 per 5 s) | the coordinator learns the channel's bucket from Discord's headers | `test_posts_to_one_channel_keep_to_its_create_limit` |
| An approval that expires while its post waits is held, never sent late | approval rechecked at claim, seal and the final pre-send guard; a lease never outlives the approval | `test_a_post_whose_approval_expires_while_waiting_is_held_and_never_sent_late` |
| Operator hold stops the lane within one iteration | pre-claim read of `manual_hold` | `test_an_operator_hold_stops_every_loop_within_one_iteration`, `test_a_hold_set_before_the_minute_starts_claims_nothing`, with a control that the old loop claims and postpones every post under the same hold |
| A global 429 pauses every loop without a retry storm, and the denied post is not failed | embargo read before each claim; rate waits never count as attempts | `test_a_global_429_pauses_every_loop_without_a_retry_storm`, `test_a_global_429_makes_each_loop_sleep_instead_of_claiming`, with a control that the old loop claims and releases every post |
| A spent invalid-request budget pauses every loop without claiming, and nothing is held early | pre-claim read applies the coordinator's rule to every capped row; when the coordinator spends that budget itself it also sets `blocked_until` to the reset, which the read already honoured | `test_a_spent_invalid_request_budget_is_waited_out_without_claiming`, with a control that the old loop claims, releases and holds every due post; `test_the_coordinator_embargoes_an_invalid_budget_it_spends_itself_and_the_lane_waits` |
| One database connection per loop at a time | sequential transactions, none held across HTTP | `test_each_loop_holds_one_database_connection_at_a_time` |
| The last step ends inside the function limit | admission deadline, budget capped at 90 s (a larger setting is clamped) | offline `test_no_budget_can_outlast_the_function_limit_with_one_step_in_flight`, `test_a_budget_above_ninety_seconds_is_clamped_to_ninety`, `test_a_configured_120_seconds_runs_for_90`, `test_no_step_starts_after_the_budget_...` |
| One malformed job document stops only its own workspace | the lane's claim pins a failure of reading a document on the workspace being read and sets it aside for 300 s (its rotation cursor dated ahead), then goes on | `test_a_job_document_the_claim_cannot_read_stops_only_its_own_workspace`, `test_a_workspace_set_aside_is_skipped_until_its_window_ends_and_a_repaired_document_is_claimed_again`, `test_the_malformed_shapes_the_claim_already_handles_never_reach_the_guard`, `test_a_failure_in_every_workspace_is_the_claim_code_not_a_document_and_still_raises`; offline `Quarantine` |
| A paused Discord (kill switch, authorization off, rate limits off) never holds a post or demotes a destination | the lane and the minute tick claim nothing while paused (the posts are not touched at all); a scoped claim that meets the pause releases the post unsent for a minute; a revoked connection or missing permission still holds | `test_a_paused_discord_is_not_claimed_by_the_lane_and_nothing_is_lost`, `test_a_paused_discord_leaves_the_minute_crons_posts_untouched_however_long_the_pause`, `test_recovery_after_rate_limits_were_off_waits_and_then_drains_exactly_once`, `test_recovery_after_the_coordinator_was_missing_waits_and_then_drains_exactly_once`, `test_a_revoked_connection_still_holds_the_post_and_asks_for_the_destination_again`; offline `PausedDiscord` |
| A lease or approval lost after the seal never lets the create out | the consume guard rechecks lease, cancellation, approval, role and grant under the workspace lock; the lane no longer renews a second time | `test_a_withdrawal_after_the_seal_is_caught_by_the_consume_guard_not_a_second_renewal`, `test_a_lease_lost_after_the_seal_ends_uncertain_without_a_post_and_keeps_the_intent`, the seal and consume crash tests; the minute worker's step still renews twice: `test_the_minute_workers_step_still_renews_after_the_seal`; offline `NoSecondRenewal` |
| A release the shared budget caused does not cost the tenant its turn, and no tenant gets more work for it | the post's `lastDispatchedAt` and the workspace cursor are put back, the retry is due at once, at most 3 times per post, system-wide causes only | `test_a_post_the_shared_budget_released_is_claimed_again_before_anything_else`, `test_permit_expiries_do_not_change_the_rotation_or_any_workspaces_share_of_the_work`, `test_the_position_is_kept_three_times_for_one_post_and_then_the_penalty_applies`; a tenant's own resource keeps the penalty: `test_a_release_caused_by_one_tenants_resource_keeps_its_penalty`, `test_a_transient_preflight_failure_keeps_its_penalty`; controls: `test_control_the_old_penalty_...`, `test_control_without_the_restore_...`; offline `PositionKept` |
| Flag off, or on with the lane unable to run, is the frozen behaviour | flag read as the exact string; one readiness test (`lane.blocker`) for the tick (its static part) and the lane (the full rule); equivalence with `2a5a523d` | offline `FlagOffIsTheFrozenBase`, `LaneReadiness`, `ExistingTick` |

How the PostgreSQL tests stay off the runner's clock (an early CI run failed the id-ordered fairness control with 19
of the 20 busy creates it counted; a faster runner gives the small tenants more of each channel window):
- Order properties are read from the jobs' own `claimed` events: which workspace a loop takes next is the selection's
  choice, while whether that attempt sends now or is deferred depends on the runner's speed.
- "Never sent late" is checked on the coordinator's own record, not the mock's arrival time. The exact bound is the
  permit: a create's permit never ends after its approval or the policy (`permit_end <= expiresAt`), and `consume()`
  refuses a permit at its end by the database clock. The release instant (`sent_at`) is written by the next statement
  of that transaction, so the tests allow it `RELEASE_SLACK` = 1 s: as tested, "never sent late" reads "released no
  later than 1 s after expiry", while the permit check above is exact.
- A test that checks an outcome after a time-boxed run repeats the run, as the next cron minute would, while any post
  still waits to be sent or verified (at most four runs); fast runners use one.
- The coordinator-cap pair runs at 3 requests per second (ceiling 6), a cap twelve loops meet on a slow runner too, and
  counts the loops' own application-window waits as the sign the cap was met.
- The global-429 tests count from the coordinator's record of the 429 (its admission's outcome) to the embargo's end,
  both on the database clock: nothing is admitted in that window, at most one request per other loop still arrives,
  and each loop claims at most once in it. Counting from the 429's arrival at the mock widened both bounds on a slow
  runner by however long the record took.

## Database connections

One connection at a time per loop: every transaction is short and opened and closed in sequence; none is held across a
Discord request [measured: peak one per loop thread]. With K = 12 loops, the lane holds at most 12 at once, plus the minute
cron's one. With the production factory (`POSTRIFF_DB_POOL_ENABLED` not `true`) every transaction opens a new connection
through the Supabase pooler: about 20 per post (claim, renewals, seal, completion, and two per Discord request). That
connection churn, not the lane, is likely the largest part of a step's real latency; the pooled factory would remove it
but is a separate setting.

## A permit an embargo blocks before it is used

An embargo or hold that the coordinator observes after a create's intent was sealed blocks that unused permit
(`observe()`: every reserved or sealed admission in the blocked scope becomes `blocked`). The post used to end
`uncertain` though nothing was sent, waiting for manual reconciliation: one global 429 could strand about one post
per running loop. The invariant now: a sealed intent is retried only when `consume()` itself refuses its permit in the
same call, before any transport, and the worker then proves from the admission row, under its lock in the workspace
transaction, that the permit was blocked while sealed and never consumed (`confirm_blocked_publish`: state `blocked`,
this intent, `sealed_at` set, no `sent_at`). `consume()` is the only way from a publish permit to its POST and commits
`sent` before any transport, so that intent never left and never can. The intent is archived as unsent
(`unsentProof` `embargo_blocked_admission`), the post goes back to scheduled for the embargo's remaining time (held
with the existing "rate wait outlasts approval" reason if that passes its approval), and an event records it. It
shares the eight-recovery bound of an expired unconsumed permit. Anything where the transport may have run (a failed
or timed-out request, a lost response) and anything without the in-call refusal (a process killed between sealing
and sending, a lease taken over, a restart) stays `uncertain` and is reconciled as before [measured on PostgreSQL:
`test_a_global_429_seen_while_posts_are_sealed_sends_each_once_after_the_embargo` and its two controls].

The sibling, a permit reserved but not yet sealed when the embargo or hold is observed, used to end `held` at the
seal ("Discord rate permit expired or changed before sealing"): a new approval for a post nothing had touched.
No intent exists there, so `seal()` now refuses such a permit (state `blocked`, no intent, never sent) as a rate
wait for the embargo's remaining time, and the worker releases the post the way it releases a permit that expired
before sealing (same eight-recovery bound; event "A Discord embargo blocked the rate permit before its intent was
sealed") [measured on PostgreSQL: three loops each holding a reserved permit at a global 429; all three were held
before the change, all three are sent once after the embargo now].

## A document the claim cannot read

One workspace's malformed Discord job used to stop the whole lane (independent review G2E-C-10). A job with `events: null`
(or `attempts` or `discordReceipts` null, or `events` a string) raised in the claim, which rolled back; the rotation order
(least recently served first) kept offering that workspace first, so no other workspace was ever claimed [measured on real
PostgreSQL: every claim raised, the healthy due posts in the other workspaces were never claimed]. No customer path that
writes such a document was found, so this is structural, not a known attack.

The lane's worker (`LaneWorker.claim`; the loops' unscoped Discord claim only) now pins a failure of reading a document on
the workspace being read and sets that workspace aside. Its rotation cursor is dated `QUARANTINE_SECONDS` (300) ahead and
marked (`quarantinedUntil`), in its own short transaction (the failed claim's has rolled back), so the claim skips it until the
window ends and then goes on to the next workspace, and the shards' own look at the queue (`_CLAIMABLE`, the loop's copy of the
due probe) does not count it, so an idle system with one such workspace is still idle at the first look. Nothing else in the
document changes: a repaired document is claimed again by itself when the window ends (the first normal claim clears the
mark). It is counted (`quarantined`: the lane health status, `discord.lane.completed`, the shard answer's counters) and
logged as one `discord.lane.quarantined` line with the exception class only, no workspace, job, channel or lease owner id.

Only failures of reading a document are set aside (AttributeError, TypeError, KeyError, IndexError, ValueError); a database
error, a lost revision or anything else is raised as before. One claim sets aside at most `MAX_QUARANTINES_PER_CLAIM` (2)
workspaces: a third failure in the same claim is no longer one document but the claim code itself, and it raises as before,
so a defect that hits every workspace is loud and cannot quietly set the queue aside. The six other malformed shapes the
review found (the discord manifest or its channel missing, the manifest gone, `nextAt` a string, the approval digest or
the authorization missing) were already held or skipped by the existing checks and never reach the guard [measured].

Costs and limits [reasoned unless marked]: during its window the whole workspace waits, its healthy posts too (late, not
lost; the lag warning fires when they are 300 s late, because the lag read still counts them, and the ops health payload
shows the same lag); a document that stays broken is found again every 300 s, one log line each time; `quarantined` counts
this process's events since it started, other processes count their own. The guard is the lane's worker only, so the
minute cron's frozen Discord path (flag off, or the lane unable to run) keeps the old behaviour and
`FlagOffIsTheFrozenBase` stays true byte for byte.

## A release the shared budget caused keeps its place

A claim stamps the post's `lastDispatchedAt` and the workspace's rotation cursor before the preflight. A post released
unsent because a create permit ended unused used to go behind its never-claimed siblings, and its workspace to the back of
the round, though it had completed nothing: in the 5,000-post run [independent review of the capacity receipt] 503 of 2,000
workspaces were hit, a released post's median re-claim delay was 729 s, and those workspaces' posts were 26.6 minutes late
against 15.3 for the others.

When the denial is system-wide (the application window was spent: `rate_scope_kind` `application`; or a create permit
ended unused: `rate_cause` `permit_expired`, before the seal or sealed and not consumed) the lane's worker
(`LaneWorker._discord_rate_released`, called by the three rate releases in their own transaction) puts both stamps back as the
claim found them (kept in memory from the candidate it read, never stored) and makes the retry due at once. Restoring only one
of the two does almost nothing [reviewer's model: the workspace's next claim takes a due read-back and spends the turn], so
both are restored. At most `MAX_POSITION_RESTORES` (3) times per post (`discordPositionRestores` on the job, counted per
invocation as `positionsKept`); the retries stay bounded as before (`ratePermitRetries` at most 8, `rateReadRetries` under 3).
A release that one tenant's resource caused keeps today's penalty: a learned or unknown route or channel window, the cold-route
probe, an embargo (also one that blocked a permit), a provider 429, a window about to end, and a transient preflight failure;
otherwise workspaces sharing a full channel could take their turn over and over. So does a post that is held or canceled by
the release. The base worker's hook does nothing, so the minute cron's frozen path is unchanged.

The snapshot is read from the candidate row the way the claim itself reads it: a mapping, or the JSON text of one (`LaneWorker._document`;
the quarantine mark of a set-aside workspace is found in a text document the same way). A document that is neither takes no
snapshot at all, and a post without one keeps today's penalty. A restore from an empty snapshot would pop the cursor and the
dispatch stamp, a jump to the front of the rotation [found by the independent delta re-review; the PostgreSQL driver returns
mappings, so only a driver that hands over text could reach it].

Why this is fair [reasoned; the rotation and shares measured in `test_permit_expiries_do_not_change_the_rotation_or_any_workspaces_share_of_the_work`]:
1. The round robin gives each tenant one claim per round while others wait: it bounds a tenant's share of *completed* work.
   A claim released unsent completed none and spent shared admissions, so counting it as the tenant's turn charged the tenant
   for a system event, and a random quarter of the tenants carried the system's failure.
2. A restored turn is the same claim again, not an extra one. A tenant still completes at most one create per round while
   others wait; the retry is the claim that was released, bounded as above, and other tenants lose at most that retried claim,
   whose cost was spent anyway. With every fourth create permit ending unused, taking the immediate retries out leaves the
   round-robin order and every workspace's number of posts as without the expiries.
3. Only ordering metadata changes. `lastDispatchedAt` orders a workspace's jobs at claim; the cursor orders workspaces and feeds
   the projection. No approval, lease, intent, permit or check changes.

## The lease after the seal

The step renewed the lease a second time after the intent was sealed and before the create: one more whole-document
transaction on the seal-to-consume path, where 83 percent of the permit expiries of the 5,000-post run happened
[independent review of the capacity receipt]. The lane's worker no longer does (`LaneWorker.renew_discord_lease`); the
renewal after the preflight stays, and the base worker, so the minute cron's frozen path, renews twice as before.
It added no authorization: the seal has just extended the lease to 45 s under the workspace lock, and consume()'s live
guard (`_authorize_discord_rate_send`) rechecks the lease, cancellation, approval, role and grant under that lock, later
than a renewal could. The skip applies only once that guard is attached to the sealed post (without it, with rate limits off,
which the lane never runs with, the renewal stays).

Consequence [measured on PostgreSQL]: a withdrawal, cancellation or approval change after the seal is refused by the consume
guard instead of by the renewal. The permit is not consumed (the admission stays `sealed`), no POST starts, the sealed
intent stays for manual reconciliation, and the post ends `uncertain` with the completion's "Discord delivery is uncertain.
Reconcile before any further publication." (before: "Discord authority changed during renewal; no new dispatch is
permitted"). A lease lost after the seal is refused by the same guard; the completion cannot write a lease that is no longer
ours, so the next claim's expiry recovery records `uncertain` ("Expired Discord intent requires reconciliation; never
repost"), as it did after the renewal's early return. The intent is kept either way and nothing is posted twice. One
counter moves: a lease lost between the seal and the create is no longer counted in `leaseLost`; it shows as `uncertain`
and `uncertainCreates`.

## A paused Discord is a wait

With Discord paused (execution disabled: the abort ladder's kill switch `POSTRIFF_OAUTH_DISCORD_DISABLED`, or a provider
flag not set; or authorization off, which the hosted runtime also does without rate limits) the permission preflight
refuses every post with a 409 "paused" error. The step completed each one as held with `not_sent` evidence, and that also
sets its destination to `verification_required` [independent review of the send path; measured: 4 workspaces, 8 posts,
4 of 4 destinations demoted, 8 of 8 posts held, 0 Discord requests]. After the switch was off again nothing posted and every
customer had to authorize again, though the incident runbook says "existing grants stay stored".

Now (1) the lane's loops stop before any claim (`lane.paused()`: the provider's flags, pure; `blocker()` still comes first,
so a lane that cannot run says why), `stoppedBy` `discord_paused`: no post and no read-back is touched. (2) The minute tick
does the same: `tick()` passes `exclude_discord=True` whenever `lane.paused()` is true, with the lane flag off (today's
production) and with it on but the lane unable to run, so a pause never makes it claim a Discord post. The first version of
this fix let the tick claim and release each post, and the independent re-review found the churn: every post was claimed
again each minute for as long as the pause lasted, and each cycle appended a claim, a submitting and a release event and an
attempt and rewrote the workspace document twice (measured on that version: five minutes of a pause added 15 events and
5 attempts to a post; a day's kill switch would add some 4,300 events and 1,400 attempts per due post, in a document every
later claim rewrites). The posts now wait untouched, with the stamps they had, and are claimed at once when the pause ends.
A back-off that grows was rejected: it would delay the posts after the unpause. (3) A step that still meets the pause (a
person's scoped "post now", a pause that began after the claim) releases the post unsent for `PAUSED_RETRY_SECONDS` (60)
with the existing rate-wait release: no attempt is consumed, it is not counted in `rateDelays`, the destination is
untouched, and the post is held only when the wait passes its approval, as for any rate wait (never sent late). A revoked
connection or a missing permission is another error and still holds the post and asks for the destination again [measured].

The frozen path: `FlagOffIsTheFrozenBase` pins the minute cron in the states it runs, none of which pauses Discord, and it
stays green. In a paused state the minute cron now differs from the frozen code in two places: `tick()` leaves Discord
alone, and the branch of the step that a scoped claim or a mid-step pause can still reach (the frozen code held the post
and demoted the destination); together they are the one deliberate exception to "flag off is the frozen path". Read-backs
too: neither the lane nor the minute tick claims the read-back of an already created post while paused, so the existing rule
(a read-back that meets a disabled execution is completed `uncertain`: "The original Discord application is unavailable.
Keep the receipt for manual review.") can only be reached by a scoped claim; the read-back is made after the pause.

## A read-back waits for the coordinator

A post that Discord already accepted keeps its receipt and waits for a read-back that confirms it. That read has to be admitted
by the shared request coordinator like every other, so with a coordinator that cannot admit anything (none attached, degraded,
its policy ended, its database down) it was refused before it was built. `reconcile_discord` took that refusal for an answer it
could not read: the post became `uncertain`, the claim kept the check it had spent, and after the fifth claim the post was
parked for 86,400 s ("Manual provider review required"), still parked when the coordinator came back [the ops review's N-1,
reproduced by its probe `exp_runbook2.py e5`: checks 7, next attempt in 86,399.9 s]. The runbook's second lever, a build without a
usable coordinator, therefore did strand created posts, though it said it stranded nothing.

Now `RateCoordinatorUnavailable` raised anywhere in the lookup is a wait for that exact lookup, as a read refused by a hold is
(Q17): the post stays `provider_accepted` with its receipt, the result is the existing deferral (`discordReadDeferred`,
`discordReadAdmissionDenied`), the worker refunds the check, and the next attempt is `COORDINATOR_WAIT_SECONDS` (300) away, for
as long as it lasts; the first attempt after the coordinator is back confirms the post. Only the coordinator is a wait: a lookup
that fails for any other reason (a connection that changed, a mismatch, a missing field) is `uncertain` as before. Everything that
creates stays fail-closed and is not touched: the preflight and the permit still raise `RateCoordinatorUnavailable`, nothing
leaves, no read reaches Discord, and a post not yet created is released for five minutes. A person's own requests are unchanged
(a 503 "Connecting to Discord is paused for a moment"): only the read-back of an existing receipt changed. The wait is one event
per claim (`discordReadDeferrals` counts them), about 288 a day per waiting post; the claims come from the minute tick, which keeps
the frozen path in this state because `lane.paused()` is false (it asks the provider's flags, and this state leaves them on).
Whether the tick should treat "no usable coordinator" as a pause, so that nothing is claimed at all, is Q20.

## The worker flag and migration 128

Migration 128's guard trigger (installed in production) refuses the claim of a Discord post by a worker that does not use
the fenced lease protocol: CheckViolation "Discord requires the current fenced worker protocol before dispatch."
`POSTRIFF_DISCORD_WORKER_V1_ENABLED` (1 or true) is what makes the worker use it. With the flag unset or mistyped, the
minute worker still claims a due Discord post the old way, the guard refuses, and the whole claim transaction aborts on
every attempt: the tenant cursor does not advance, so the same workspace is first again every tick and the later
workspaces of that claim, of any provider, are never processed [independent review of the send path, scope B: three ticks,
another tenant's due post still scheduled]. This is the frozen worker's behaviour with that guard installed, with or without
W-02, and the earlier statements that Discord is then "held, not sent" or "claimed and sent as before" were wrong for a
database with migration 128.

Fixed at the release, not in the frozen path: the hosted preflight now fails a build with any Discord feature flag on
(authorization v2, connections v2, rate limits, webhook, user install, engagement, the lane) and the worker flag not 1 or
true (`discord-worker-protocol`; the lane's own check stays). Environment changes reach new deployments only, so every
deployment passes it. Not done, proposed (the owner decides, it touches the frozen path): in `PostgresWorker.claim`, react to
that one CheckViolation (sqlstate 23514 and its message), roll back, run the claim again with `exclude_discord` for the rest
of the process's life, count it (`discord_stats['fenced']`, created on first use so no trace changes) and log one WARNING.
It acts only after the failure the frozen code raises, so `FlagOffIsTheFrozenBase` would stay green; the caveat is that in
that state the minute worker would stop raising and leave Discord posts unsent. The simpler "the tick excludes Discord
when the flag is off" is not proposed: it changes the trace `test_flag_on_without_the_worker_protocol_matches_the_base_exactly`
pins.

## Fail-safe behaviour

What each cause does, in the minute cron's tick, in the 12 shards, and on the customer's post [reasoned from the
code unless marked]. "Frozen path" means the tick is byte-for-byte the `2a5a523d` code [tested offline]; the
quoted texts are the events and next actions the existing worker writes.

| Cause | Minute tick | Shards | The customer's post | Signal |
|---|---|---|---|---|
| Flag off, or the lease protocol off | frozen path: claims Discord as before W-02. With the worker flag off AND migration 128 installed (as in production) a due Discord post is refused by the database guard and the claim aborts for every provider ("The worker flag and migration 128"); the preflight now fails such a build | answer `{"enabled": false}` without starting the runtime | sent as before when the worker flag is on; with it off and migration 128 installed not sent, and the claim aborts | `status.blocker` `disabled`; the preflight's `discord-worker-protocol` |
| Lane budget misconfigured | frozen path, sends as before | 503 `discord_lane_configuration`, nothing claimed | sent as before | shard 503s; `blocker` `configuration` |
| Rate limits off (`POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED` unset) | frozen path; `runtime_from_environment` then turns Discord authorization off, so Discord is paused: the tick claims no Discord post and touches nothing (before K1: held, destination set to `verification_required`) [measured on PostgreSQL] | stop at once, `coordinator_unavailable`, nothing claimed | later than scheduled (the post is not touched while Discord is paused), sent after the repair if still inside its approval; held, never sent late, if its approval has ended by then; no destination is touched | the preflight fails; WARNING shard lines; `blocker` `coordinator_unavailable` |
| Rate limits on but no usable coordinator: no reviewed policy (`rate_policy_raw` unset: an inert coordinator whose policy is None), or one that does not parse (`OAuthService` leaves no limiter and marks it degraded, `oauth.py`). The runbook's second lever, a build without a usable coordinator | frozen path, and it does claim: authorization stays ON here, so `lane.paused()` is false and K1 does not apply (an earlier version of this table, and the lane suite's "no coordinator" case, took this state for a pause; only `runtime_from_environment`'s own failure turns authorization off). A post not yet created is released unsent for five minutes ("Proven unsent Discord operation released: rate_delayed"; held once that passes its approval), a created post's read-back waits five minutes with its check refunded and its receipt kept ("A read-back waits for the coordinator"); before that fix the first claim made it `uncertain`, each claim spent a check and the fifth parked it for a day, for good (the ops review's N-1) [measured on PostgreSQL, `test_discord_readback_coordinator_postgres.py`] | stop at once, `coordinator_unavailable`, nothing claimed | later than scheduled; sent after the repair if still inside its approval, else held, never sent late; a created post is confirmed by its read-back after the repair; nothing is posted twice | the preflight fails; WARNING shard lines; `blocker` `coordinator_unavailable`; events "Discord message receipt retained; request coordination is unavailable for the exact read-back" |
| Discord paused: execution disabled (the kill switch `POSTRIFF_OAUTH_DISCORD_DISABLED`, or a provider flag not set), or authorization off | the minute tick claims no Discord post (nothing is touched); a step that still meets the pause releases the post unsent for a minute (never held, destination untouched) | every loop stops before any claim, `discord_paused` (WARNING line) | waits; sent after the pause if still inside its approval; held (never sent late) once the wait passes its approval; no customer has to authorize again [measured on PostgreSQL: 4 workspaces, 8 posts: before, 4 of 4 destinations demoted and 8 of 8 posts held] | `discord_paused` lines; the ops health payload's `executionEnabled`, `authorizationV2`, `killSwitch` |
| Policy expired or not yet valid (a well-formed policy outside its validity) | frozen path: each claimed post is released for five minutes, and held once that wait passes its approval | stop at once, `coordinator_unavailable` | later than scheduled ("Await Discord shared rate budget; no POST occurred and this approval remains frozen"), or held ("Discord rate wait outlasts approval; review the frozen destination and approve again") | WARNING shard lines; `blocker` `coordinator_unavailable`; `policyDaysLeft` at or below 0 |
| Coordinator degraded in one process | leaves Discord to the lane | that process's loops stop, `coordinator_degraded`; other processes' loops send | sent by the healthy loops | WARNING lines from that process; its `blocker` `coordinator_degraded` |
| Coordinator degraded in every lane process | leaves Discord to the lane | every loop stops, `coordinator_degraded` | waits; once its approval's hour has passed, held when next claimed ("Discord needs a current human approval bound to this exact destination and content") | WARNING lines; `discord.lane.lagging` after five minutes |
| Operator hold on the policy row | leaves Discord to the lane (it cannot see the hold) | each loop stops before its next claim, `operator_hold` | waits; a post whose permit the hold blocked before it was used, sealed or not, is released unsent and sent once after the hold (Q4; a sealed one used to be left `uncertain`, a reserved one `held`, with nothing sent) | M6; `operator_hold` lines |
| Shard crons not reaching the function | leaves Discord to the lane | nothing runs | waits; held after its approval's hour | no lane lines; `discord.lane.lagging` after five minutes |
| Projection missing | leaves Discord to the lane | stop at once, `schema` | waits; held after its approval's hour | WARNING lines; `discord.lane.lagging` |
| Embargo, circuit, spent window or invalid-request budget | leaves Discord to the lane | sleep it out, or stop with `rate_wait` | later than scheduled; a post whose permit was reserved or sealed when the embargo is observed is released unsent and sent once after it [measured on PostgreSQL: three loops, a global 429, both cases] | M4; `rate_wait` lines |

Recovery, measured on real PostgreSQL (`test_discord_parallel_lane_postgres.py`, section (i)): with rate limits off,
an expired policy or no coordinator (that suite sets it with authorization off, the paused case; the state `OAuthService`
leaves, authorization on, is `test_discord_readback_coordinator_postgres.py`) the shards claim nothing and the minute cron
does what the rows above say; once the
configuration is repaired, the lane creates every post still inside its approval exactly once and never sends a held
one (with rate limits off, or with no coordinator, the posts waited unsent: those inside their approval are created
once after the repair, the others were held, as with an expired policy). A gap of minutes without shard crons logs
`discord.lane.lagging` every minute (`laneOwnsDiscord` true) while nothing is sent; when the crons return the backlog
drains exactly once and fairly, and the warning stops. A policy that expires mid-run stops every loop
(`coordinator_unavailable`); nothing is claimed or created after it, and renewal resumes, leaving at most the step each
loop had in flight for review (refused at the seal it is held, refused at the create it is uncertain with nothing
sent; in two characterization runs every such step was released instead, and sent after renewal).

Rollback, measured the same way (section (j)): turning the flag off on a new build while old lane invocations still
run, with one post leased by a loop that died mid-step, lets the frozen minute cron and the old loops work side by
side; the dead lease is recovered once, as provably unsent, after it expires, and every post is created exactly once.
Rolling back to the frozen `2a5a523d` worker itself while a lane worker id holds a lease: that worker leaves the
workspace alone while the lease lives, then recovers the post only as unsent (sent once), or, when the post has a
sealed intent or Discord already accepted it, marks it uncertain and never creates it again. Turning the flag off
and on again keeps every post exactly once (off: the shards answer disabled and the minute cron sends; on: the
minute cron claims no Discord). The operator hold stops every loop within its iteration: no loop claims more than
once after the hold, every create after it was claimed before it, and lifting the hold resumes exactly once.

## Health status

`lane.status(social, now, values=None)` is the lane's health indication: pure and cheap (no database, network or
secret; codes, numbers and booleans only), version 1, a shape kept stable for a protected health route and monitors
[tested offline: shape, each cause, purity]. It is in the minute cron's result whenever the flag is on
(`discordLaneStatus`, next to `discordParallelLane`), in every shard answer (`status`, which the
`discord.lane.completed` line also carries), and callable directly.

| Field | Type | Meaning |
|---|---|---|
| `version` | integer | 1 |
| `enabled` | boolean | the flag and the Discord worker lease protocol are on (`lane.enabled()`) |
| `ready` | boolean | the lane runs in this process now (`blocker` is null) |
| `blocker` | string or null | why not: `disabled`, `configuration`, `coordinator_unavailable`, or `coordinator_degraded` (this process only); the full rule of `lane.blocker()` |
| `maxSeconds` | number or null | one invocation's time budget after clamping (at most 90); null when the budget is misconfigured |
| `maxSteps` | integer or null | one invocation's step backstop; null when misconfigured |
| `shards` | integer | cron entries, 12 |
| `policyDaysLeft` | number or null | days until the reviewed policy expires, two decimals, negative once expired; null when no policy is visible (no coordinator, or the flag-off shard answer, which starts no runtime) |
| `quarantined` | integer | workspaces this process has set aside since it started because the claim could not read their document ("A document the claim cannot read", below); 0 on a healthy system. The ops health payload copies this status, so it shows there too |

In the minute cron's result `discordParallelLane` says whether that tick left Discord to the lane (the static causes)
and `discordLaneStatus.blocker` what stops the lane in that process (the full rule): with only that process degraded
the first is true and the second `coordinator_degraded`. A misconfigured budget makes the shard answer a 503 error,
which carries no status.

## Failure modes

| Event | What happens |
|---|---|
| A loop crashes between steps | nothing in flight; the next minute's loops continue |
| A loop crashes mid-step before the intent | lease expires (45 s); released as unsent; sent once later |
| A loop crashes after sealing or after the create left | never re-posted; the job is 'uncertain' for manual reconciliation; the request's admission keeps a slot until reviewed, and if it was the first request on that route, later posts to that channel wait until review (Q3) |
| Operator hold set | every loop stops before its next claim; a post whose permit the hold blocked before it was used is released unsent (Q4); queued posts wait |
| Global 429 or circuit | loops sleep until it ends; the post whose read was refused waits and is sent later; a 429 on a create holds that post for review (existing rule) |
| An embargo, circuit or hold begins while a read waits for its booked slot | a read that slept 25 ms or more is looked at once more just before it is sent; if any scope it was admitted under is now held, embargoed or in circuit it is closed `blocked`, not sent (its slot stays spent), and the post waits as for the same refusal at admission (a hold: five minutes, as in Q17). A booked create's permit is blocked by the existing rule and refused at seal or consume before any transport |
| A loop dies inside a booked wait | nothing was sent: a booked read is stored `sent` but had not left, so it is never sent, keeps its slot until its scope's window plus 30 s (31 s on the application row) and then stops counting; a booked create's permit expires unused (5 s) and the post is released when its lease expires and sent once later. A loop is in one booked wait at a time: at most one slot per shard, 12 of 25 for at most 31 s if every shard dies at once |
| Budget exhausted | the lane's reads and creates are booked the next exact slot, at most one second ahead, and wait for it inside the coordinator; beyond that horizon they wait for the next window (bounded) as before; web requests are refused as before ("Booking") |
| Approval expires in the queue | held for a fresh approval when next claimed (monitor M7) |
| Coordinator observation fails in a process | that process's provider refuses every later request; its loops stop with `coordinator_degraded`; its minute cron still leaves Discord to the lane (it could not send either); loops in other processes continue |
| Database unavailable | the loop's exception is logged and the request returns 500; leases expire and are recovered |
| Flag on, projection missing | `schema`, nothing claimed (migration 126 is applied in production); the minute cron cannot see it without a query, so it still leaves Discord to the lane and `discord.lane.lagging` fires after five minutes |
| Flag on, shard crons not reaching the lane (not registered, a 401, a 404, Deployment Protection, a platform skip; a `CRON_SECRET` under 16 characters fails the minute cron's own route too) | no `discord.lane.completed` lines; the minute cron (the lane able to run) leaves Discord alone, so posts wait; `discord.lane.lagging` fires after five minutes; after an hour their approvals lapse and they are held when next claimed |
| Flag on, rate limits off, no coordinator, policy expired or not yet valid, or a bad lane budget | the lane cannot run anywhere: every loop stops at once with the reason (a bad budget answers 503 `discord_lane_configuration`), and the minute cron keeps the frozen Discord path |
| A job document the claim cannot read (a null where a list belongs) | that workspace is set aside for 300 s, counted (`quarantined`) and logged once; every other workspace is claimed as usual; a third such failure in one claim is raised |
| A route answers with a bucket id outside Discord's alphabet (`[A-Za-z0-9_-]{1,128}`: a test double's template, an intermediary rewriting headers), or with rate-limit numbers that cannot be read | that one route of that one server is held (`manual_hold`, kind `route`): nothing is sent to it, its posts stay `scheduled` ("Await Discord shared rate budget; no POST occurred") and are claimed again every five minutes, every other server is untouched, the health payload counts it under `coordinator.kinds.route.holds`; only an operator lifts it ("Releasing a held route", below). Proven by `tests/test_discord_route_429_postgres.py` (the capacity harness's F429 sent `injected-guilds-{id}`; the same 429 with a well-formed bucket delays the post two seconds and it is verified) |
| Build-level kill switch (`POSTRIFF_OAUTH_DISCORD_DISABLED`) | unchanged: a claimed post is held, as today |

## Turning it off

- **Seconds:** the runbook's hold, `UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy'`.
  Every loop stops before its next claim (at most the one step it has in flight, seconds) and every new Discord
  request admission everywhere is refused before transport. A create whose permit was reserved before the hold can
  still go out: neither the permit's consumption nor its live guard reads the hold, so until the coordinator next
  records a response and blocks the remaining unused permits (Q4), the step a loop had in flight may still post
  [reasoned from the code; measured: at most one create per loop after the hold, each claimed before it]. Lift with
  `manual_hold = false`. Only on the owner's word, as the runbook says.
- **Minutes:** a build without the flag (environment changes reach new deployments only), or promote the previous
  deployment. The minute cron then claims Discord again exactly as before, and the shard routes answer
  `{"enabled": false}` without starting the runtime.

## Releasing a held route

The coordinator holds a route (not the application) when Discord, or something between us and Discord, answers it with a
bucket id outside `[A-Za-z0-9_-]{1,128}` or with rate-limit numbers it cannot read. This is a reviewed fail-closed rule: a
header it cannot trust is not learned, and the route waits for a person. Only that route of that server is affected. To see
whether any are held, and to lift them (statements for the operator, read the first before running the second; they never
touch the application-wide row of the kill switch, which is `kind = 'policy'`):

```sql
SELECT kind, count(*) AS held, round(min(extract(epoch FROM now() - updated_at))) AS seconds_since_change
FROM public.pr_discord_rate_state WHERE manual_hold GROUP BY kind;
UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE manual_hold AND kind = 'route';
```

Run the second statement only after the cause is understood (a bad intermediary or a test double is the usual one; if the
cause persists the next answer holds the route again). Posts of that server go out on their next claim, at most five
minutes later. The hold of the shared bot credential after a 401 (`kind = 'credential'`) and the kill switch (`kind =
'policy'`) are separate decisions and are not lifted by this.

## What to monitor

The `discord.lane.completed` log lines (12 a minute; sum `posted`, `verified`, `held`, `uncertain`, `rateDelayed`,
`leaseLost` per minute; any `stoppedBy` other than `idle`, `time_budget` or `rate_wait`), and `docs/w02/monitoring.sql`:
M1 oldest due lag, M2 leases expired but still owned, M3 busiest second, M4 rate waits, M5 unanswered admissions (Q3),
M6 holds on the four rows, M7 posts held for an expired approval. The launch monitors Q1 to Q13 still apply. The lane's
`bookedWaits` and `bookedSeconds` and the health payload's `coordinator.booking` show the booking ("Booking", below).
The lines' `held` (like the minute cron's `discordWorker.counters.held`) misses a post held by a rate-wait release,
one whose wait outlasts its approval: `discord_worker.release_unsent` sets the state before the event that counts it
(unchanged worker code, the same in `2a5a523d`) [measured: 3 such holds counted 0]. M7's `held_total` and
`discordWorker.queue.held` count every held post in their samples.

The minute cron's lag warning, for the failures no lane line reports (a cron that never fires logs nothing): with the
flag on, every tick logs one `discord.lane.lagging` line at WARNING when due Discord work has waited too long, or when it
could not see the queue. It reads two sources. The Discord report the tick already makes (`discordWorker.queue`) samples
the first 256 workspaces by id (at most 4,096 Discord jobs); its `oldestEligibleLagSeconds` is the oldest due, unleased
job there, create or read-back (unchanged), and when the report fails its status is `unavailable`. When the lane owns
Discord the report also tells creates from read-backs: `oldestEligibleCreateLagSeconds` (the oldest due post not yet
created) and `oldestEligibleReadbackLagSeconds` (the oldest due post the claim would reconcile: a created post waiting for
its read-back), because read-backs are deferred behind creates by design. When the lane owns Discord the tick also reads
the projection's oldest due work, every workspace, in one indexed statement (`lane.projected_lag`, the shards' own due
probe): `projectedLagSeconds`. A tick that kept Discord (the lane cannot run anywhere) runs only the frozen path's
statements, reads no projection and has no split.

The thresholds (M5): a create more than 300 s late (`LAG_WARNING_SECONDS`); a read-back more than 3,600 s late
(`READBACK_LAG_WARNING_SECONDS`; in the 5,000-post run a created post was confirmed 18 minutes later at the median and 32 at
the slowest); the projection's lag against 300 s, because it cannot tell a create from a read-back, unless the sample shows
the deferral signature (a read-back waiting more than 300 s and no create that late), when it counts against 3,600 s. A
report without the split (the frozen tick's) counts its whole `oldestEligibleLagSeconds` as before. The line also fires when
the report is `unavailable`, or when the lane owns Discord and the projection cannot be read, and says which: `report`
(`sample` or `unavailable`), `projection` (`read`, `unreadable`, or `not_read` when the tick kept Discord) and `lateKinds`
(`creates`, `readbacks`, `projection`, or `sample` for a report without the split). Other fields, counts and codes only:
`oldestEligibleLagSeconds`, `oldestEligibleCreateLagSeconds`, `oldestEligibleReadbackLagSeconds`, `projectedLagSeconds`,
`thresholdSeconds`, `readbackThresholdSeconds`, `laneOwnsDiscord`, `laneBlocker` (the readiness reason when the tick kept
Discord; null, with `laneOwnsDiscord` true, when only the tick's own process has a degraded coordinator, whose shard lines
then say `coordinator_degraded`), `depth`, `held`, `uncertain`, `deadLetters` [tested on PostgreSQL: 300 workspaces with the
only due post outside the sample, a report that fails, and a deferred read-back that no longer keeps the warning on while a
late create or a read-back past an hour still does]. The projection's lag counts a post waiting for manual reconciliation
(`uncertain`) as due, as the report does, and it does not know which deployment a post is bound to. Alert on any such line.
A large burst still warns while its creates are late (5,000 posts take about 23 minutes), which is worth knowing (Q1); it no
longer keeps warning for read-backs that wait behind them. Known limit: the projection (migration 126) holds one `next_at`
per workspace, so the split is the sample's, and a late create hidden beyond the sample while read-backs drain is seen at the
read-back threshold. An exact split over every workspace needs a projection column (a new migration, not made). Without a
migration, a reader of the projection can take the oldest due `next_at` among workspaces with `last_claimed_at = 0`: a
workspace the lane never served can only hold a create.

## Capacity

See `CAPACITY-SIMULATION.md`. In short [measured, mock Discord, local PostgreSQL]: 12 loops at the 25 per second policy
verified 400 of 400 posts with 0 duplicates and 0 requests above 50 in any second, at 6.1 requests and 3.7 posts per
second, which extrapolates to about 23 minutes for 5,000 posts due at once [the model agrees]. At two requests per post the
same budget gives about 8 minutes, at one about 4 [simulated]. These need the owner's capacity run against the real
platform before any claim is made to customers.

## Known limits, not changed

- The pre-claim read sees the coordinator's stored rows. A new reviewed policy that lowers a capacity in the middle of
  a window is applied by the coordinator inside each reservation and rolled back with the refusal, so until that
  window resets the read says go while every first read is refused, and the loops release the posts they claim for
  the rest of the window, as the old loop does (at most one second on the application row; on the invalid-request row
  up to its window, 600 s by default) [reasoned]. Mirroring that recalculation in the lane would copy coordinator
  internals; left to the coordinator's reviewer.
- With the YouTube fleet on, the minute cron's claim (the `exclude_youtube` branch of `_claim`) runs the engine's
  invalidation over every non-YouTube job of a workspace it locks, Discord jobs included and without
  `_invalidate_owned`'s filter (which also leaves out jobs bound to another deployment), so it can still hold a
  scheduled, approved or claimed Discord job whose approval, channel or entitlement changed (it never claims or
  sends one). The same in `2a5a523d`; W-02 changes nothing about it [reasoned].
- A degraded coordinator stays degraded for the life of its process (the flag is cleared only when the runtime
  attaches the coordinator) [reasoned]. If every process that runs lane loops is degraded, every loop stops and every
  minute cron still leaves Discord to the lane, so due posts wait unsent. Nothing could be sent in that state either
  way; the signals are the shard lines (`coordinator_degraded`, at WARNING) and, after five minutes, the lag warning
  with `laneOwnsDiscord` true, which does not name the cause.
- A learned route used to close until the policy expired when the permits reserved after its refill all expired unused.
  Resolved on the limiter branch: such a route is probed again at once (`_window_unused`), and one whose requests were
  sent but never answered waits at most a window plus the margin; see "The shared request coordinator after the limiter
  work" below.

## The shared request coordinator after the limiter work

`rate_limits.py` (`SharedPostgresBudget`) changed on the limiter branch; the lane is unchanged. What a reader of this
document should know:

- **The 25 per second is exact and counts wire times.** The application row admits when the admissions occupying a slot
  plus those held are fewer than the cap. An admission occupies a slot from its wire time (`sent_at`: a read when it is
  admitted, a create when its permit is consumed; else its reservation) for one span, the window plus
  `SLOT_GUARD_SECONDS` (0.1 s). A permit not used yet, and a request sent but never answered, keep a slot as well
  (`held`). So no closed second of wire times holds more than the cap, and arrivals at Discord stay within it while the
  admission-to-wire spread is at most 100 ms; the cost is 22.7 of 25 a second at the ceiling and nothing below it. The
  capacity harness reports the real spread (wire jitter p99.9): the guard is the one constant to set from it. With booking a
  wire time may also lie up to one second ahead of the database clock (a booked slot); the rule, `_fits`, is the same.
- **A permit lives `permit_ttl_seconds`** (5 in the reviewed policy), the lease and the approval, not its window: a
  window that ends while a permit is unused refills its row counting the permit as pending, and the application window
  holds a slot for it until it is used or expires. Before, 11.5% of create preflights of a 5,000-post run were repeated
  because the permit died before it could be sealed.
- **Nothing stays unresolved for ever.** A read whose transport failed is resolved at once (observed 503); an answer that
  arrived and was refused for its size (`ProviderResponseLimit`) is recorded with its real status and headers; a request
  whose outcome is unknown (a write, a lost process, an observation that timed out) keeps its slot for its scope's window
  plus 30 s (`UNOBSERVED_MARGIN_SECONDS`, the transport's 20 s timeout and allowance) and then stops counting; the row
  stays `sent` or `uncertain` for an operator and for the claim paths that retire it. A guild owner can no longer take
  the shared budget to zero with an oversized channel list.
- **Refusals.** 401 holds the credential; 403 (and a 404 on a webhook) opens the route's circuit for 30 s, doubling per
  consecutive refusal up to 16 minutes; a 404 on anything else opens none; 429 embargoes the scope Discord names; three
  5xx or transport failures open the 30 s circuit.
- **The lock.** A reservation sends, after the statement that takes the locks, a reading of the clock and the window, one
  statement that writes the scopes and the admission, and the commit; an observation sends six (was nine). The reading
  cannot be part of the lock statement: in READ COMMITTED a statement that waited for a lock keeps its start-of-statement
  snapshot and would not see the admission the previous holder committed meanwhile.
- **A policy renewal can only tighten.** `_roll` keeps the stored cap and window of the policy, invalid-request and
  discovery rows as the minimum cap and the maximum window of every policy whose expiry has not passed (the stored expiry is
  the latest of them). A renewal with a higher `app_capacity` therefore changes nothing until the stored expiry is past. A
  deliberate raise is an operator act: apply the new policy, then UPDATE the application row's `limit_count` (an UPDATE
  the service role may make; the stored cap is the ceiling in force and a reservation under the renewed revision does not
  reconsider it); the policy tool also refuses an `app_capacity` above half the bot limit and must be changed (reviewed)
  first. It cannot happen by accident, and a later, tighter policy still tightens a raised cap.
- **The sender-name write.** `PATCH /guilds/{id}/members/@me` is admitted only while `POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED`
  is exactly `true`, read at call time: turning the flag off refuses new admissions at once, and an admission that already
  exists is retired by `abandon_unsent_nickname`, `reconcile_nickname` or `reconcile_nickname_by_id`, each silent for one
  that is settled (`observed`, `blocked`), however young. The by-id reconciler needs no token (a rotated token cannot strand
  an admission); it accepts only this application's bot, unbound, non-publish PATCH of the nickname route and the exact guild
  path, and only once the admission is 120 s old and its permit has expired. Such rows keep counting against the ceiling for
  their span (no refund) and carry no status code (`NULL`, scope `unknown`); the age bound changes no row, so the claim path
  can still retire an orphan after it.

- A route whose first (cold) probe never got an answer refuses every later request with the probe window (about a second),
  so the approved posts to that channel churn (claim, three admitted reads, release) until their approval ends [independent
  review of the send path: 10 such guilds, 86 percent of the requests in 30 s were their reads]. A refusal by an embargo or a
  circuit already carries the embargo's remaining time, and the release waits until its end (`nextAt` = release time plus
  that wait; offline `PositionKept`, penalty cases); this refusal has no end to wait for. The cause is the coordinator's
  (the unanswered admission keeps its slot, Q3); left to the coordinator's reviewer.

## Booking

*Why.* The first hosted measurement of the lane (5,000 posts, 12 shards, 25 a second) took a median of 19.8 minutes against a
plan of 12, with 8.95 requests and 18.6 reservation lock statements a post and 4,714 posts released after a refused read. A
full window refused a read with the time until a slot freed; every refused read slept that quote and asked again, about half
of the 12 shards woke for the same freed slot, one won, and a read that lost three times (1 s) released its whole post and
threw away the one to five preflight reads it had already made. Booking gives a caller that finds the window full a place in
line instead (Q19 has the models and the measurements).

*Who books.* Only the three calls the lane makes for a post, on the lane's own thread: `PacedSocial` wraps
`prepare_discord_dispatch` (the identity, server, two membership and channel reads), `reserve_discord_send` (the create
permit, a bot's or a webhook's) and `reconcile_discord` (the read-back) in `rate_limits.booking(BOOK_AHEAD_SECONDS, tally)`, a
context variable. `DiscordProvider._book_ahead(room)` hands its seconds (never more than `BOOK_AHEAD_SECONDS`, 1.0, and not
more than a read's own remaining wait; nothing under 5 ms) to `reserve_read` / `reserve` as `book_ahead`, and passes no
keyword at all outside the context. A direct provider call, another thread, the minute worker (it shares a warm instance's
provider and never sees the context), and every web request (connect, destinations, installation checks, webhook set-up, the
message-content check, reply reads, the sender-name routes) get the immediate answer or refusal they always got.

*The rule.* A booking caller is admitted at once when one more wire time now is exact in every window that holds it. If not,
`_booking_slot` gives the earliest instant at or after now, and not before any wire time already stored, at which it is exact
in every window of one span (the window plus the guard) that holds it; a permit not used yet counts in every window for a
booking (it may be used at any later time), so it is taken out of the wires and out of the free slots. The caller is refused,
as an immediate caller would be, with the wait until a booking is possible, if the slot is more than its book-ahead away, if
no slot is free for bookings, if a create's permit (`permit_ttl_seconds`, 5) would not live `BOOK_MIN_LIFE_SECONDS` (0.5 s)
after its slot, or if the slot plus the permit's life would pass the caller's deadline (the lease, the approval, the
policy's end). Otherwise the admission is stored with the slot as its wire time (a read: `sent`, `sent_at` = slot; a create:
`reserved`, `reserved_at` = slot, living `permit_ttl_seconds` from there), its scopes are debited as for any admission (the
same statements under the lock: the lock, the reading, one write, the commit), and `reserve` / `reserve_read` return when the
slot has come. The sleep is after the commit with no lock held, in slices of at most 0.1 s, counted on the process's
monotonic clock from the moment the database clock was read (a send is never early by the reservation's own duration), and a
create's sleep also ends at its deadline if that comes first (the permit is left to expire, `permit_expired`). There is no
sleep in `seal` or `consume` (F5), and `consume` refuses a booked permit before its slot (`permit_early`).

*Exactness.* Unchanged: at every instant at most `cap` wire times lie in any half-open span, so no closed second of wire times
holds more than `cap`; only a wire time may now lie ahead of the clock. Bookings fill all but `IMMEDIATE_RESERVE` (1) slots,
so a web request, which cannot wait, always finds one (4 percent of the ceiling at saturation). A wire time further ahead
than the book-ahead plus 50 ms (the database clock stepped back) is waited out as before: every wire counts and the quote is
the wait.

*What the application row stores.* The same whoever wrote it. `remaining` is the free slots that bookings may still fill
(`cap` less the held, less `IMMEDIATE_RESERVE`, less the wire times up to now; never below 0), and `reset_at`, while none is
free, the instant from which a booking within the book-ahead is possible (the next wire to leave its span, less the
book-ahead; an instant already past means possible now). `lane.outlook`, which waits while `remaining` is 0 and `reset` lies
ahead, is unchanged and now waits only while the booked horizon is full. For a monitor this changes the meaning: a busy lane
keeps the window full and `remaining` no longer approaches 0 with it; it reaches 0 when the horizon is full and callers are
refused again. With `BOOK_AHEAD_SECONDS` 0 the row is what it has always been.

*The gate.* A booked read that slept at least 25 ms (`BOOK_GATE_MIN_SECONDS`) is looked at once more just before it is sent:
one short statement of its own, with no application or scope lock, closes it `blocked` if any scope it was admitted under now
has a manual hold, an embargo or an open circuit, and the caller is told as at admission (a hold: `RateDelayed(300,
cause='hold', scope='embargo')`; an embargo: what is left of it). Its slot stays spent. What can still reach Discord after an
embargo begins is what could before: whatever lies between this look (for a wait under 25 ms, the commit) and the wire. A
booked create's permit is blocked by the existing rule for unused permits and refused at seal or consume.

*A process that dies in the wait* is in the failure table: nothing is sent, at most one slot per shard is held, for at most 31
seconds.

*The lane.* The counters `bookedWaits` and `bookedSeconds` (in `lane.COUNTERS`; summed in the invocation result and the
`discord.lane.completed` line) count the lane's own bookings. Nothing else changes: the loop budget (a step's seven requests
may each wait one second, so a step may take seven seconds longer; `STEP_RESERVE_SECONDS` 160 holds it, 147 of 160), the
lease and its renewal, F2 (a post refused beyond the horizon keeps its place), the pause and K1, the quarantine, the frozen
path, the shard count (12).

*Health payload.* `coordinator.booking`: `status`, `bookAheadSeconds`, `aheadNow` (admissions whose wire time is still ahead),
`horizonSeconds` (how far ahead the latest lies; close to `bookAheadSeconds` means the horizon is full and callers are being
refused again), `bookedReads60s`, `bookedReadWaitSeconds60s`, `meanBookedReadWaitSeconds60s`, `maxBookedReadWaitSeconds60s`.
Reads only: a create's booked wait is not recorded (`aheadNow` counts creates).

*Limits.* A horizon of one second holds about (`cap` - 1) / 1.1 bookers, one for each loop in a booked wait: about 21 at the
reviewed 25, comfortably 12 loops, 24 at the edge. A caller beyond the horizon is refused and asks again, and a pass refused
part-way is released with its reads wasted: with 12 loops booking makes more posts than polling from a budget of 12 a second up
(34 to 66 percent more) and fewer below 10 (at a budget of 8, 12.5 posts a minute against 33), with few loops the same edge (3
loops at a budget of 4 finished 4 of 12 posts in 295 s); the ceiling stays exact throughout (Q19 has the numbers). The policy tool
warns (`lane_booking`) under 1.5 a second for each shard, 18. The evidence behind a create grows older: its
permission reads come first in a pass and each may now wait up to a second [simulated: median 1.3 to 2.3 s at 12 loops, 2.2
to 5.7 s at 24; no bound in the code]; what the send rests on besides them (approval, lease, fences) is rechecked at the seal
and consume as before. A gated or abandoned booked read still spent its slot.

*Off.* The lane's flag returns Discord to the minute worker, which never books; a build with `BOOK_AHEAD_SECONDS = 0` in
`rate_limits.py` (pinned by `ShippedConstants`) restores the old coordinator behaviour for every caller.

*Evidence.* `tests/test_discord_rate_booking.py` (36 offline: the arithmetic, the stored row, the web reserve, booked permits,
the deadline, the gate, a crash in the wait, the constants, the statement shape, and 32 randomized lives of 300 steps checked
against a brute-force count of every closed second, which also catches the permit mutation); `tests/test_discord_rate_booking_postgres.py`
(24 threads on PostgreSQL keep the ceiling with far fewer lock statements; creates are not starved when reads are booked too;
the gate against a 429, a hold and a circuit; a dying process; `consume` before the slot; a web caller; the health payload);
`tests/test_discord_lane_booking.py` (the three places and no others, the counters, a coordinator that blocks a second per
reservation still ends the invocation inside budget plus one step, `outlook`); `tests/test_discord_lane_booking_postgres.py`
(12 and 16 loops at a full window: about one pass a post, nothing posted twice; an approval ending inside a pass; a loop killed
inside a booked sleep; no sleep between the seal and the consume; a pause during booked waits).

## Not done

Phase 1b (scheduled-time jitter) is not started. Not run: the owner's Depot capacity run, any hosted build, the
exact-SHA CI workflow on this branch, the hosted-runner measurement after booking (the capacity harness's). An independent review's findings are addressed (the readiness test, the lag
warning, the invalid-budget wait, the 90-second cap, the preflight check); that fix set has not been reviewed again.
Not changed on purpose: requests per post, the coordinator's handling of unanswered admissions, the hold's effect on
sealed permits, the step order (Q2 to Q4, Q12).
