# W-02 parallel Discord sending: as built (Phase 1)

Branch `claude/discord-w02-parallel-20261023`, from the frozen release candidate `2a5a523d`. Engineering only: nothing is
deployed, no setting or secret is changed, and the lane does nothing until its flag is set on a new, separately approved
build. Labels: [measured] local real-PostgreSQL runs with a mock Discord; [simulated] the fake-clock model; [reasoned]
read from the code.

## What changed

| File | Change |
|---|---|
| `src/postriff_phase2/discord/lane.py` (new) | The lane: flag and budget parsing, shard parsing, the readiness test (`blocker`), one bounded loop per invocation, the pre-claim coordinator read, the bounded wait for a refused create permit, per-invocation counters and the log line; the minute cron's lag warning (`warn_if_lagging`). |
| `src/postriff_phase2/hosted_worker.py` | `tick()` passes `exclude_discord=True` only when the lane is on and `lane.blocker()` says it can run in that process (the minute cron then does not claim Discord), and with the lane on logs the lag warning from its own report; `_tick` accepts that keyword. With the lane off, or on but unable to run, the code path is the old one, proven against the frozen source (below). |
| `src/postriff_phase2/hosted_app.py` | Route `GET /api/cron/discord-worker/<shard>`: cron secret checked before the runtime starts (as the YouTube lanes); flag read per request; the request log files it under `cron`. |
| `vercel.json` | 12 cron entries `/api/cron/discord-worker/0` to `/11`, every minute. `git.deploymentEnabled` stays `false`; nothing else changed. |
| `scripts/check_postriff_hosted_preflight.py` | The cron check accepts exactly the worker plus these 12 shards. A `discord-parallel-lane` check fails when the lane flag is on without `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` or without the worker lease protocol. |
| `scripts/discord_lane_capacity_sim.py` (new) | The capacity simulation (model and real run). |
| `tests/test_discord_parallel_lane.py` (new) | 41 offline tests (run under the synthetic fence). |
| `tests/test_discord_parallel_lane_postgres.py`, `tests/discord_lane_fixture.py` (new) | 21 real-PostgreSQL tests and their fixture; skipped under the fence. |
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
| Cost when idle | K invocations a minute (about 17,000 a day at K = 12), each answers in milliseconds with the flag off and runs three short queries with it on | one invocation a minute |
| Failure | a lost or failed invocation is replaced next minute | a broken chain waits for the next cron minute; a bug can fan out without bound |
| Moving parts | none new: the platform's scheduler | authenticated HTTP calls from the function to its own deployment URL (Deployment Protection, URL discovery, a bypass secret), chain-depth fencing |
| Throughput | up to 50 of every 60 seconds per loop | continuous |

The dispatcher's only real gain is the last row; the model puts the duty-cycle cost at about 10 to 15 percent of drain
time [simulated]. It adds a new path that can multiply invocations, which the cost policy forbids doing casually.

## What one invocation does

1. Route: cron secret (before any runtime or database work), shard check, flag check. Off: `{"enabled": false}`.
2. A fresh worker instance with its own lease owner id (`discord-lane-<shard>-<random>`) and its own counters, sharing
   the process's connection factory, provider, approval checks and completion hooks.
3. The projection table (migration 126, applied in production) must exist, or the loop stops with `schema`.
4. Loop until the budget, the step backstop, or a stop condition:
   - the readiness test `lane.blocker()`, the same one the minute tick asks (below), with this process's clock and
     then the database clock: rate limits off, or no coordinator, or a policy outside its validity stops the loop
     (`coordinator_unavailable`); a process whose coordinator lost an observation stops (`coordinator_degraded`);
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

The existing minute cron, with the flag on and the lane able to run in its process, runs every other provider exactly
as before and does not claim Discord (`exclude_discord`). "Able to run" is `lane.blocker()`, the same pure test every
lane iteration asks: a valid lane budget, `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED` on, a shared coordinator whose
reviewed policy is valid now, and no lost observation in that process. It reads no database, so the minute tick cannot
see an operator hold (the lane stops on it and the tick still leaves Discord alone, which is what a hold asks for) or a
missing projection (the lane stops with `schema`; the lag warning below catches it), nor whether the shard crons fire
at all. Otherwise, and with the flag off, the tick is byte-for-byte the frozen code path [measured: the equivalence
test runs the frozen `hosted_worker.py` and this one side by side on the same inputs and compares every SQL statement
and parameter, every Discord request, the final state and the tick result; with the flag off, and with the flag on but
rate limits off, no coordinator, an expired or not-yet-valid policy, a degraded coordinator or a bad lane budget; the
one addition is the lag warning's log line]. With a bad lane budget the frozen path sends as before. In the
coordinator states it cannot send in the hosted runtime either, but it records that on every post instead of leaving
them silently scheduled: with rate limits off `runtime_from_environment` turns Discord authorization off, so each
claimed post is held and its destination set to `verification_required` [measured offline with the frozen tick];
otherwise each request is refused and the post released for five minutes, held once that passes its approval
[reasoned]. That is today's production behaviour for those settings, with or without W-02.

Keeping Discord to one scheduler is a preference, not a safety property. The lease protocol (one live Discord lease per
workspace, the lease owner and lease id rechecked at every step, an intent sealed before any create) makes the minute
cron and lane loops safe together. They can overlap already: a person's "post now" runs the same step beside both; at
a policy's edges two processes' clocks may disagree; and when one process's coordinator is degraded, that process's
minute cron keeps the frozen path, which releases each Discord post it claims for five minutes (as before W-02), while
lane loops in healthy processes send the rest [reasoned].

## Safety properties and their evidence

| Property | How | Test (file: real PostgreSQL unless noted) |
|---|---|---|
| Every post created exactly once, none skipped, with 8 loops over 120 posts | existing claim, lease and sealed-intent protocol, unchanged | `test_many_loops_create_every_post_exactly_once` |
| Loops racing on one workspace | one live Discord lease per workspace | `test_loops_racing_on_one_workspace_send_one_post_at_a_time` |
| A loop dies before its intent | lease expires; the job is released as provably unsent and sent once | `test_a_loop_that_dies_before_its_intent_is_recovered_and_sent_once` |
| A loop dies after Discord accepted, or as the create leaves | the sealed intent forbids a new create; the job is reconciled by hand ('uncertain') | `test_a_loop_that_dies_after_discord_accepted_...`, `..._as_its_create_leaves_...` |
| Request rate across all loops | the shared coordinator admits every request; 12 loops at a 10 per second policy never passed 20 in any second | `test_the_coordinator_caps_the_request_rate_across_all_loops`, with a control that the same run exceeds it when the policy allows |
| Permits of a dead loop | unused permits expire with their window; a request that died in flight keeps its slot (existing rule, Q3) | `test_permits_of_a_dead_loop_that_were_never_used_free_their_slots`, `test_a_read_whose_process_died_...` |
| One busy workspace cannot starve the others | least-recently-served rotation plus one lease per workspace | `test_one_busy_workspace_cannot_starve_the_others`, with a control ordering by id |
| A channel's create limit (5 per 5 s) | the coordinator learns the channel's bucket from Discord's headers | `test_posts_to_one_channel_keep_to_its_create_limit` |
| An approval that expires while its post waits is held, never sent late | approval rechecked at claim, seal and the final pre-send guard; a lease never outlives the approval | `test_a_post_whose_approval_expires_while_waiting_is_held_and_never_sent_late` |
| Operator hold stops the lane within one iteration | pre-claim read of `manual_hold` | `test_an_operator_hold_stops_every_loop_within_one_iteration`, `test_a_hold_set_before_the_minute_starts_claims_nothing`, with a control that the old loop claims and postpones every post under the same hold |
| A global 429 pauses every loop without a retry storm, and the denied post is not failed | embargo read before each claim; rate waits never count as attempts | `test_a_global_429_pauses_every_loop_without_a_retry_storm`, `test_a_global_429_makes_each_loop_sleep_instead_of_claiming`, with a control that the old loop claims and releases every post |
| A spent invalid-request budget pauses every loop without claiming, and nothing is held early | pre-claim read applies the coordinator's rule to every capped row; when the coordinator spends that budget itself it also sets `blocked_until` to the reset, which the read already honoured | `test_a_spent_invalid_request_budget_is_waited_out_without_claiming`, with a control that the old loop claims, releases and holds every due post; `test_the_coordinator_embargoes_an_invalid_budget_it_spends_itself_and_the_lane_waits` |
| One database connection per loop at a time | sequential transactions, none held across HTTP | `test_each_loop_holds_one_database_connection_at_a_time` |
| The last step ends inside the function limit | admission deadline, budget capped at 90 s (a larger setting is clamped) | offline `test_no_budget_can_outlast_the_function_limit_with_one_step_in_flight`, `test_a_budget_above_ninety_seconds_is_clamped_to_ninety`, `test_a_configured_120_seconds_runs_for_90`, `test_no_step_starts_after_the_budget_...` |
| Flag off, or on with the lane unable to run, is the frozen behaviour | flag read as the exact string; one readiness test (`lane.blocker`) for the tick and the lane; equivalence with `2a5a523d` | offline `FlagOffIsTheFrozenBase`, `LaneReadiness`, `ExistingTick` |

## Database connections

One connection at a time per loop: every transaction is short and opened and closed in sequence; none is held across a
Discord request [measured: peak one per loop thread]. With K = 12 loops, the lane holds at most 12 at once, plus the minute
cron's one. With the production factory (`POSTRIFF_DB_POOL_ENABLED` not `true`) every transaction opens a new connection
through the Supabase pooler: about 20 per post (claim, renewals, seal, completion, and two per Discord request). That
connection churn, not the lane, is likely the largest part of a step's real latency; the pooled factory would remove it
but is a separate setting.

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
| Coordinator observation fails in a process | that process's provider refuses every later request; its loops stop with `coordinator_degraded`; other processes continue |
| Database unavailable | the loop's exception is logged and the request returns 500; leases expire and are recovered |
| Flag on, projection missing | `schema`, nothing claimed (migration 126 is applied in production); the minute cron cannot see it without a query, so it still leaves Discord to the lane and `discord.lane.lagging` fires after five minutes |
| Flag on, shard crons not reaching the lane (not registered, 401 from a wrong or short `CRON_SECRET`, 404, Deployment Protection, a platform skip) | no `discord.lane.completed` lines; the minute cron (lane able to run in its process) leaves Discord alone, so posts wait; `discord.lane.lagging` fires after five minutes; after an hour their approvals lapse and they are held when next claimed |
| Flag on, rate limits off, no coordinator, policy expired or not yet valid, coordinator degraded, or a bad lane budget | the lane cannot run: every loop stops at once with the reason (a bad budget answers 503 `discord_lane_configuration`), and the minute cron of that process keeps the frozen Discord path |
| Build-level kill switch (`POSTRIFF_OAUTH_DISCORD_DISABLED`) | unchanged: a claimed post is held, as today |

## Turning it off

- **Seconds:** the runbook's hold, `UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy'`.
  Every loop stops before its next claim (at most the one step it has in flight, seconds) and every Discord request
  everywhere is refused before transport. Lift with `manual_hold = false`. Only on the owner's word, as the runbook says.
- **Minutes:** a build without the flag (environment changes reach new deployments only), or promote the previous
  deployment. The minute cron then claims Discord again exactly as before, and the shard routes answer
  `{"enabled": false}` without starting the runtime.

## What to monitor

The `discord.lane.completed` log lines (12 a minute; sum `posted`, `verified`, `held`, `uncertain`, `rateDelayed`,
`leaseLost` per minute; any `stoppedBy` other than `idle`, `time_budget` or `rate_wait`), and `docs/w02/monitoring.sql`:
M1 oldest due lag, M2 leases expired but still owned, M3 busiest second, M4 rate waits, M5 unanswered admissions (Q3),
M6 holds on the four rows, M7 posts held for an expired approval. The launch monitors Q1 to Q13 still apply.

The minute cron's lag warning, for the failures no lane line reports (a cron that never fires logs nothing): with the
flag on, every tick reads the Discord report it already makes (`discordWorker.queue`) and logs one
`discord.lane.lagging` line at WARNING when the oldest due, unleased Discord job is more than 300 seconds late
(`lane.LAG_WARNING_SECONDS`). Fields, counts and codes only: `oldestEligibleLagSeconds`, `thresholdSeconds`,
`laneOwnsDiscord`, `laneBlocker` (the readiness reason when the tick kept Discord), `depth`, `held`, `uncertain`,
`deadLetters`. It adds no query [tested offline: the same statements with and without the warning]. Alert on any such
line. It also fires while a large burst drains (5,000 posts take about 23 minutes), which is worth knowing too (Q1). It
is blind where the report is: workspaces outside its sample (the first 256 by id, at most 4,096 Discord jobs) and a
failed report (`queue.status` `unavailable`); M1 reads the whole projection.

## Capacity

See `CAPACITY-SIMULATION.md`. In short [measured, mock Discord, local PostgreSQL]: 12 loops at the 25 per second policy
verified 400 of 400 posts with 0 duplicates and 0 requests above 50 in any second, at 6.1 requests and 3.7 posts per
second, which extrapolates to about 23 minutes for 5,000 posts due at once [the model agrees]. At two requests per post the
same budget gives about 8 minutes, at one about 4 [simulated]. These need the owner's capacity run against the real
platform before any claim is made to customers.

## Not done

Phase 1b (scheduled-time jitter) is not started. Not run: the owner's Depot capacity run, any hosted build, the
exact-SHA CI workflow on this branch, an independent review. Not changed on purpose: requests per post, the coordinator's
handling of unanswered admissions, the hold's effect on sealed permits, the step order (Q2 to Q4, Q12).
