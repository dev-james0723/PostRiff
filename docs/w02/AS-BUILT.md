# W-02 parallel Discord sending: as built (Phase 1)

Branch `claude/discord-w02-parallel-20261023`, from the frozen release candidate `2a5a523d`. Engineering only: nothing is
deployed, no setting or secret is changed, and the lane does nothing until its flag is set on a new, separately approved
build. Labels: [measured] local real-PostgreSQL runs with a mock Discord; [simulated] the fake-clock model; [reasoned]
read from the code.

## What changed

| File | Change |
|---|---|
| `src/postriff_phase2/discord/lane.py` (new) | The lane: flag and budget parsing, shard parsing, the readiness test (`blocker`), one bounded loop per invocation, the pre-claim coordinator read, the bounded wait for a refused create permit, per-invocation counters and the log line; the minute cron's lag warning (`warn_if_lagging`); the health status (`status`). |
| `src/postriff_phase2/hosted_worker.py` | `tick()` passes `exclude_discord=True` only when the lane is on and the static part of `lane.blocker()` says it can run (the minute cron then does not claim Discord), and with the lane on adds the health status (`discordLaneStatus`) and logs the lag warning from its own report; `_tick` accepts that keyword. With the lane off, or on but unable to run, the code path is the old one, proven against the frozen source (below). |
| `src/postriff_phase2/hosted_app.py` | Route `GET /api/cron/discord-worker/<shard>`: cron secret checked before the runtime starts (as the YouTube lanes); flag read per request; the request log files it under `cron`. |
| `vercel.json` | 12 cron entries `/api/cron/discord-worker/0` to `/11`, every minute. `git.deploymentEnabled` stays `false`; nothing else changed. |
| `scripts/check_postriff_hosted_preflight.py` | The cron check accepts exactly the worker plus these 12 shards. A `discord-parallel-lane` check fails when the lane flag is on without `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` or without the worker lease protocol. |
| `scripts/discord_lane_capacity_sim.py` (new) | The capacity simulation (model and real run). |
| `tests/test_discord_parallel_lane.py` (new) | 66 offline tests (run under the synthetic fence). |
| `tests/test_discord_parallel_lane_postgres.py`, `tests/discord_lane_fixture.py` (new) | 34 real-PostgreSQL tests and their fixture; skipped under the fence. |
| `tests/phase2/fixtures/hosted_worker_2a5a523d.py.txt` (new) | The frozen worker source, pinned by SHA-256, for the flag-off equivalence test. |
| `docs/w02/*` (new) | This file, the corrected plan, open questions, monitors, simulation results. |

No migration, no new table, no new queue, no change to the coordinator, the claim, the lease protocol, the approval
checks, the sender or the launch gate.

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

- `POSTRIFF_DISCORD_WORKER_V1_ENABLED` on: the lease protocol the lane uses. Without it the lane flag has no effect.
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
   without the table the loop stops with `schema`), and the readiness test again on that clock. If nothing is due
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
     (`coordinator_degraded`);
   - read the coordinator's four application-wide rows without locks (policy, bot global, bot credential, invalid
     budget), using the coordinator's own key derivation. A manual hold on the policy row stops the loop
     (`operator_hold`); a hold on another of them (the coordinator holds the credential row after a 401) stops it too
     (`coordinator_hold`); an active block or circuit on any of them, or a capped row with nothing left until its reset
     (the application window or the invalid-request budget: the coordinator refuses on either), is slept out (with
     jitter) before claiming, or ends the loop if it outlasts the budget (`rate_wait`);
   - one existing Discord-only step (`PostgresWorker.step(discord_only=True)`): claim one job from the least recently
     served due workspace (`FOR UPDATE ... SKIP LOCKED`, at most one live Discord lease per workspace), the permission
     preflight, lease renewal, the create permit, the sealed intent, the create, the fenced completion; or a read-back;
   - if nothing could be claimed: sleep until the soonest due work if it is within 10 seconds (a read-back is due five
     seconds after its create), back off briefly if work is overdue but held by another loop, and stop (`idle`) after six
     misses or when nothing is due soon.
5. One log line, `discord.lane.completed`: shard, `stoppedBy`, elapsed seconds and counts only (claimed, posted,
   verified, held, uncertain, rateDelayed, leaseLost, recoveries, retries, deadLetters, claimMisses, rejected, notSent,
   uncertainCreates, rateWaits, idleWaits, permitWaits). No workspace, job, channel, content or lease owner id. An
   exception is logged with its class name only and re-raised, so the request returns 500 with its failure site.

The one behavioural addition inside a step: when the create permit is refused because the application window is spent,
the lane's worker waits for the next window (at most one second, the same bound reads already have) instead of releasing
the job. Without it, at a saturated budget each refused create re-spends its four preflight reads and almost nothing is
created [measured: with the wait off, see CAPACITY-SIMULATION.md]. It waits before any intent is sealed, the job keeps its
live lease, and the step rechecks every fence afterwards. Any other refusal (an embargo, a channel window, a passed lease
or approval deadline) releases the job as before.

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
them silently scheduled: with rate limits off `runtime_from_environment` turns Discord authorization off, so each
claimed post is held and its destination set to `verification_required` [measured offline with the frozen tick];
otherwise each request is refused and the post released for five minutes, held once that passes its approval
[reasoned]. That is today's production behaviour for those settings, with or without W-02.

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

## Database connections

One connection at a time per loop: every transaction is short and opened and closed in sequence; none is held across a
Discord request [measured: peak one per loop thread]. With K = 12 loops, the lane holds at most 12 at once, plus the minute
cron's one. With the production factory (`POSTRIFF_DB_POOL_ENABLED` not `true`) every transaction opens a new connection
through the Supabase pooler: about 20 per post (claim, renewals, seal, completion, and two per Discord request). That
connection churn, not the lane, is likely the largest part of a step's real latency; the pooled factory would remove it
but is a separate setting.

## Fail-safe behaviour

What each cause does, in the minute cron's tick, in the 12 shards, and on the customer's post [reasoned from the
code unless marked]. "Frozen path" means the tick is byte-for-byte the `2a5a523d` code [tested offline]; the
quoted texts are the events and next actions the existing worker writes.

| Cause | Minute tick | Shards | The customer's post | Signal |
|---|---|---|---|---|
| Flag off, or the lease protocol off | frozen path: claims and sends Discord as before W-02 | answer `{"enabled": false}` without starting the runtime | sent as before | `status.blocker` `disabled` |
| Lane budget misconfigured | frozen path, sends as before | 503 `discord_lane_configuration`, nothing claimed | sent as before | shard 503s; `blocker` `configuration` |
| Rate limits off; or rate limits on with no coordinator (no policy, or one that does not parse: `runtime_from_environment` then builds no coordinator and turns Discord authorization off) | frozen path; with Discord authorization off each claimed post is held and its destination set to `verification_required` [measured on PostgreSQL for both] | stop at once, `coordinator_unavailable`, nothing claimed | held: "Discord destination, grant, media or rollout verification is unavailable. Nothing was posted."; the destination must be verified again | the preflight fails; WARNING shard lines; `blocker` `coordinator_unavailable` |
| Policy expired or not yet valid (a well-formed policy outside its validity) | frozen path: each claimed post is released for five minutes, and held once that wait passes its approval | stop at once, `coordinator_unavailable` | later than scheduled ("Await Discord shared rate budget; no POST occurred and this approval remains frozen"), or held ("Discord rate wait outlasts approval; review the frozen destination and approve again") | WARNING shard lines; `blocker` `coordinator_unavailable`; `policyDaysLeft` at or below 0 |
| Coordinator degraded in one process | leaves Discord to the lane | that process's loops stop, `coordinator_degraded`; other processes' loops send | sent by the healthy loops | WARNING lines from that process; its `blocker` `coordinator_degraded` |
| Coordinator degraded in every lane process | leaves Discord to the lane | every loop stops, `coordinator_degraded` | waits; once its approval's hour has passed, held when next claimed ("Discord needs a current human approval bound to this exact destination and content") | WARNING lines; `discord.lane.lagging` after five minutes |
| Operator hold on the policy row | leaves Discord to the lane (it cannot see the hold) | each loop stops before its next claim, `operator_hold` | waits; a post between sealing and sending may be left `uncertain` with nothing sent (Q4) | M6; `operator_hold` lines |
| Shard crons not reaching the function | leaves Discord to the lane | nothing runs | waits; held after its approval's hour | no lane lines; `discord.lane.lagging` after five minutes |
| Projection missing | leaves Discord to the lane | stop at once, `schema` | waits; held after its approval's hour | WARNING lines; `discord.lane.lagging` |
| Embargo, circuit, spent window or invalid-request budget | leaves Discord to the lane | sleep it out, or stop with `rate_wait` | later than scheduled | M4; `rate_wait` lines |

Recovery, measured on real PostgreSQL (`test_discord_parallel_lane_postgres.py`, section (i)): with rate limits off,
an expired policy or no coordinator the shards claim nothing and the minute cron does what the rows above say; once the
configuration is repaired, the lane creates every post still inside its approval exactly once and never sends a held
one (with rate limits off, or with no coordinator, every post was already held, so nothing is sent). A gap of minutes without shard crons logs
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
| Operator hold set | every loop stops before its next claim; a post between sealing and sending may be recorded 'uncertain' with nothing sent (existing coordinator rule, Q4); queued posts wait |
| Global 429 or circuit | loops sleep until it ends; the post whose read was refused waits and is sent later; a 429 on a create holds that post for review (existing rule) |
| Budget exhausted | creates wait for the next window (bounded); reads wait as before |
| Approval expires in the queue | held for a fresh approval when next claimed (monitor M7) |
| Coordinator observation fails in a process | that process's provider refuses every later request; its loops stop with `coordinator_degraded`; its minute cron still leaves Discord to the lane (it could not send either); loops in other processes continue |
| Database unavailable | the loop's exception is logged and the request returns 500; leases expire and are recovered |
| Flag on, projection missing | `schema`, nothing claimed (migration 126 is applied in production); the minute cron cannot see it without a query, so it still leaves Discord to the lane and `discord.lane.lagging` fires after five minutes |
| Flag on, shard crons not reaching the lane (not registered, a 401, a 404, Deployment Protection, a platform skip; a `CRON_SECRET` under 16 characters fails the minute cron's own route too) | no `discord.lane.completed` lines; the minute cron (the lane able to run) leaves Discord alone, so posts wait; `discord.lane.lagging` fires after five minutes; after an hour their approvals lapse and they are held when next claimed |
| Flag on, rate limits off, no coordinator, policy expired or not yet valid, or a bad lane budget | the lane cannot run anywhere: every loop stops at once with the reason (a bad budget answers 503 `discord_lane_configuration`), and the minute cron keeps the frozen Discord path |
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

## What to monitor

The `discord.lane.completed` log lines (12 a minute; sum `posted`, `verified`, `held`, `uncertain`, `rateDelayed`,
`leaseLost` per minute; any `stoppedBy` other than `idle`, `time_budget` or `rate_wait`), and `docs/w02/monitoring.sql`:
M1 oldest due lag, M2 leases expired but still owned, M3 busiest second, M4 rate waits, M5 unanswered admissions (Q3),
M6 holds on the four rows, M7 posts held for an expired approval. The launch monitors Q1 to Q13 still apply.
The lines' `held` (like the minute cron's `discordWorker.counters.held`) misses a post held by a rate-wait release,
one whose wait outlasts its approval: `discord_worker.release_unsent` sets the state before the event that counts it
(unchanged worker code, the same in `2a5a523d`) [measured: 3 such holds counted 0]. M7's `held_total` and
`discordWorker.queue.held` count every held post in their samples.

The minute cron's lag warning, for the failures no lane line reports (a cron that never fires logs nothing): with the
flag on, every tick logs one `discord.lane.lagging` line at WARNING when due Discord work is more than 300 seconds late
(`lane.LAG_WARNING_SECONDS`), or when it could not see the queue. It reads two sources. The Discord report the tick
already makes (`discordWorker.queue`) samples the first 256 workspaces by id (at most 4,096 Discord jobs); its
`oldestEligibleLagSeconds` is the oldest due, unleased job there, and when the report fails its status is
`unavailable`. When the lane owns Discord the tick also reads the projection's oldest due work, every workspace, in one
indexed statement (`lane.projected_lag`, the shards' own due probe): `projectedLagSeconds`. A tick that kept Discord
(the lane cannot run anywhere) runs only the frozen path's statements and does not read the projection. The line
fires when either lag passes the threshold, when the report is `unavailable`, or when the lane owns Discord and the
projection cannot be read, and says which: `report` (`sample` or `unavailable`) and `projection` (`read`,
`unreadable`, or `not_read` when the tick kept Discord). Other fields, counts and codes only: `thresholdSeconds`,
`laneOwnsDiscord`, `laneBlocker` (the readiness reason when the tick kept Discord; null, with `laneOwnsDiscord` true,
when only the tick's own process has a degraded coordinator, whose shard lines then say `coordinator_degraded`),
`depth`, `held`, `uncertain`, `deadLetters` [tested on PostgreSQL: 300 workspaces with the only due post outside the
sample, and a report that fails]. The projection's lag counts a post waiting for manual reconciliation (`uncertain`)
as due, as the report does, and it does not know which deployment a post is bound to. Alert on any such line. It also
fires while a large burst drains (5,000 posts take about 23 minutes), which is worth knowing too (Q1).

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

## Not done

Phase 1b (scheduled-time jitter) is not started. Not run: the owner's Depot capacity run, any hosted build, the
exact-SHA CI workflow on this branch. An independent review's findings are addressed (the readiness test, the lag
warning, the invalid-budget wait, the 90-second cap, the preflight check); that fix set has not been reviewed again.
Not changed on purpose: requests per post, the coordinator's handling of unanswered admissions, the hold's effect on
sealed permits, the step order (Q2 to Q4, Q12).
