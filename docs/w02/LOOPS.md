# W-02 lane: 16 or 24 loops instead of 12 (analysis only; nothing is built)

Status: analysis of 2026-10-28 for the Captain, who asked for one page, docs only, no code. Read at my head `4cf85a78` and the limiter head
`1f51d8e4` (it moved from `3bb12759` while I read: `rate_limits.py` and `social_connectors.py` changed, `lane.py` did not). File:line is the
limiter head unless marked "mine"; the capacity branch is `6ce80f8b`. Labels: [read] code or document, [measured] my run of the real code on a
disposable PostgreSQL or a hosted receipt, [arithmetic] counting or closed-network arithmetic, [inferred], [unknown]. Scratch models
(`loops_model.py`, `stmts2.py`) are not committed.

## The answer

- **Twelve stays in the code for now.** Nothing the lane guarantees depends on the number twelve (2), so 16 loops is a small change (one constant,
  16 JSON lines, four test pins, about 40 lines of documents) and 24 a larger one. The reason to wait is the evidence, not safety: every gain below is
  arithmetic on a database round trip nobody has measured from the function to the pooler, and past 8 to 10 ms it ends at the application-row lock and the
  pooler's pool, not at the window.
- **Where more loops pay** [arithmetic, table in 5]: requests a second at 2 / 5 / 10 ms are 18.6 / 16.0 / 12.6 with 12 loops, 21.7 / 19.7 / 16.3 with 16
  (+17 / +23 / +29 percent), 22.9 / 22.7 / at most 14 to 17 with 24 (the window at 2 and 5 ms, the lock at 10). The knee is 16 loops at 2 ms and at 10 ms,
  20 to 24 at 5 ms.
- **The first step costs no code.** The capacity harness already has `S1` and `S1-24` as profile `sens`, one request per 5 and 10 ms
  (capacity branch, `scripts/discord_lane_capacity_run.py:88-91`). Add one cell, `S1-16`: 16 is the change I would make.
- **Two things move in the closed-network arithmetic**: the 45 ms per millisecond leaves out the connection set-up (section 4), and the lock, not the window, caps the
  high round trip (section 5). Neither is measured yet.

## 1. What 16 and 24 loops take

Twelve is in a constant, a cron list, one check and some words; it is in no arithmetic. `shard()` only parses the route suffix (lane.py:136-141); the number
names the worker (`discord-lane-<n>-<uuid>`, :210) and the answer (:698). There is no partition and no workspace-hash modulus: every loop claims the least
recently claimed due workspace (`ORDER BY hint.last_claimed_at,w.id LIMIT 1 FOR UPDATE OF w SKIP LOCKED`, hosted_worker.py:55-60). Leases belong to a loop
instance (uuid) and last 45 s (discord/worker.py:13). Claims, the F5 consume guard (`_authorize_discord_rate_send`, hosted_worker.py:1080-1105, run inside the
consume transaction, rate_limits.py:1319) and K1's pause rule never read the loop count.

**(a) More cron entries.**
- `lane.py:39` `SHARDS = 12` (the cron count) and `:40` `MAX_SHARDS = 32`: the route already takes 0 to 31 (hosted_app.py:701-706), so 16 and 24 need no route change.
- `vercel.json:102-152`: the worker plus `discord-worker/0` to `/11` = 13 crons. 16 loops add 4 entries (16 lines), 24 add 12 (48 lines, 25 crons in all). A Mastodon
  conflict file; only the cron lines change. The per-project cron limit is [unknown]: four searches of Vercel's documentation (cron usage, pricing, limits) returned only
  the 512-character path and 256-character schedule limits. I recall an older figure of 40 on Pro; it is unverified and I would not rely on it.
- `scripts/check_postriff_hosted_preflight.py:107` `range(12)` (K2: "exactly the worker plus these 12", AS-BUILT.md:18).
- `scripts/discord_rate_policy.py:28-29`: `LANE_SHARDS = 12`, `LANE_MIN_RATE = 1.5 x loops`: 24 at 16 loops (under the owner's 25, quiet), 36 at 24 (it would warn on
  the owner's own 25). The rule is a heuristic for the booked horizon, (cap-1)/1.05 = 22.9 loops, which assumes no loop ever thinks (2).
- Health `status()['shards']` (lane.py:462; "the cron entries", :447; AS-BUILT.md:486). Ops alerts and lag thresholds read no twelve: `SILENT_HALT_NO_SHARDS` fires only on
  zero shard lines (discord_ops_check.py:280-283); the lag warnings are per post (300 s creates, 3,600 s read-backs, lane.py:67, :72).
- Tests that pin 12: `test_discord_lane_booking.py:120` (the constant; it names AMPLIFICATION.md as the reason), `test_discord_parallel_lane.py:86-92` (vercel.json equals
  `range(lane.SHARDS)`), `:194` and `:436` (the whole health dict, `'shards': 12`), `test_discord_ops_check.py:28` (a fixture), `test_discord_rate_policy_tool.py:88` (follows the
  constant), `test_customer_impact_shared_paths.py:289-299` (words and the 69,000-connection sum). The PostgreSQL tests pick their own counts: 12 at
  `test_discord_lane_booking_postgres.py:106`, **16 at :112** (cap 18), 24 "documented, not asserted" (:114).
- Documents: AS-BUILT.md 17 lines (18, 62, 82-87, 224-232, 428, 449, 466, 486, 705), OPEN-QUESTIONS.md 15 (Q5 :49-55; Q19 :303-316, :346), monitoring.sql :103-105 ("twelve loops hold
  at most twelve bookings of the 24": the `remaining` reading the M8 guidance expects), CAPACITY-SIMULATION.md 5, W-02-plan-corrected.md 4. Q5's "12 loops keep 25 a second busy up
  to 0.3 s a request" is already contradicted by S1 (0.58 s a request).
- Cost [arithmetic]: invocations a day 17,280 / 23,040 / 34,560 at 12 / 16 / 24; with the lane on and nothing due a shard opens 4 connections (test_customer_impact_shared_paths.py:297-299):
  69,120 / 92,160 / 138,240 a day.

**(b) Two loops per shard process, in threads** (24 loops from the 12 crons; no cron, name or limit question).
- New: a constant, and `lane.run` (same signature) starting the extra loop on a thread with the same `started`, joining it, and returning both answers; shard numbers n and n+12 for the logs. About
  40 lines and 100 of tests (the patterns are in `test_discord_lane_booking_postgres.py`). The route (hosted_app.py:701-719, a conflict file) does not change. `status()` gets `loops`; `shards` stays "cron entries".
- Thread-safe by design [read]: the booking context is a context variable, per thread (rate_limits.py:58-70, "another thread ... never see it"); its tallies sit under `_booking_lock` (:478); `_QUARANTINED` and the
  purge gate have locks (lane.py:101, :107); each loop has its own `LaneWorker`, id and counters (:205-215); the transport is built per call (provider_base.py:15-16; a new TLS connection a request, as the brief says).
- Shared, so it changes: the one provider object. After a failed coordinator write `rate_coordinator_degraded` is true for 45 s for the process (social_connectors.py:340-357): both loops stop, where today one does.
- Shutdown: `request_shutdown` (hosted_worker.py:159) has no caller in `src`, `api` or `scripts`; a platform kill takes both loops and the 45 s leases recover as for one. CPU: a loop's own CPU is 0.096 s of a 0.58 to
  0.64 s request (RESULTS-GITHUB.md:549-551), 15 percent of a core; two loops use about a third under the GIL [arithmetic]. Fluid in-function concurrency may already put two cron requests in one process: [unknown].
- Idle: invocations stay 17,280 a day; connections double (138,240) unless the second loop starts only after the first claims something.

## 2. Does more concurrency change a safety property?

None depends on the loop count. What changes is waiting and the age of evidence, and they degrade to waiting, not to a duplicate.
- **Double create stays impossible.** The chain is the workspace row lock in the claim (SKIP LOCKED), one live lease per workspace and the trigger of migration 128, the sealed intent before the permit, and a consume
  that rechecks lease, approval, grant and hold and marks `sent` in one transaction before the POST (hosted_worker.py:1080-1105; rate_limits.py:1319-1375: "can never manufacture a fresh POST"). [measured] 0
  duplicates in 18 of my real-code runs on `3dac3ccf` (12 and 24 loops, polling), in the limiter's real-PostgreSQL booking tests at 12 and 16 loops, and in every hosted run, Fcrash's 10 kills included
  (RESULTS-GITHUB.md:39, :113).
- **One workspace is still one post at a time** (Q6). Extra loops help only while more workspaces are due than loops; a loop with nothing to claim pays a 4-statement claim and backs off 0.05 x 2^k s, six misses, then
  stops (lane.py:62-63). A hot channel's 5 creates in 5 s is the same fact: one workspace, one post, a pass of 4 to 5 s, about 0.2 creates a second. The channel limit never binds and loops cannot raise it.
- **Claim contention** is SKIP LOCKED: no loop waits for another's claim. **Wasted claims** are releases: 1.00 to 1.08 passes a post with booking (hosted S0-100, Fdb) against 1.45 to 3.5 polling (my runs); they rise only
  when the horizon is full. **Poison pill**: two workspaces set aside per claim, a 300 s marker every loop honours (lane.py:76-77); more loops find the document sooner and set it aside once.
- **The booking horizon.** The written bound, (cap-1)/1.05 = 22.9 loops (Q19 :303; the test says 24 "need about 27"), holds when every loop is always waiting for a slot. With the measured think time Z = 0.51 s the mean booked wait is
  N/X - Z: 0.22 s at 16 loops, 0.54 s at 24 (X 22.9), 0.88 s at 32, against a 1.0 s horizon; at 24 loops about 12 bookings are outstanding of the 24 the horizon holds [arithmetic]. So 16 is inside both bounds, 24 fits on the
  mean and its risk is the start-of-minute burst (24 loops open a step in the same second, Q21 :410), 32 collapses (my model of `3dac3ccf`, AMPLIFICATION.md: creates a second 3.63 at 16, 3.48 at 24, 0.78 at 32). 24 is unmeasured on a real window.
- **What does get worse: the age of the evidence.** The witness reads each wait for a slot, so the create leaves later: median 1.3 to 2.3 s at 12 loops, 2.2 to 5.7 s at 24 [limiter's simulation, Q19 :318]; hosted oldest 2.72 s at 12; no bound in
  code. The seal rechecks lease, approval, fences and grant, and Discord's answer to the create is the last permission check.
- **Lock timeouts.** A coordinator transaction gives up after 2 s for a lock, 5 s for a statement (rate_limits.py:505). The independent review reproduced 253 in 12 s at 24 loops and 20 ms a statement (:44-47). At the head each is
  a 1.5 s wait (`BUSY_WAIT_SECONDS`, :48, :1107-1116), no longer the 300 s release of the post it was on `02fd679b`: lost time, not a hold, not a duplicate.

## 3. Database connections

- **One per loop at a time** [measured: AS-BUILT.md:226, peak one per loop thread]; the production factory opens a new one for every transaction (hosted_app.py:74-91; the pool is "unset (assumed)", docs/CUSTOMER-IMPACT-INVENTORY.md:136, :172).
  I count 25.0 transactions a post at the head (section 4; the reviewer's 20 was an earlier head). So 16 or 24 loops hold at most 16 or 24 client connections, plus the minute worker's and the web app's (the other 12 crons are the lane itself). The rate of opening them follows
  throughput (3.2 posts a second x 25 = 80 a second at the window), not the loop count.
- **Pool settings in the code**, only if `POSTRIFF_DB_POOL_ENABLED=true`: `max_size` 20 per process, 64 waiting, 8 s (hosted_app.py:53-56), min_size 0, idle 30 s, lifetime 300 s (postgres_pool.py:69-70). A process with 1 or 2 loops uses 1 or 2: 20
  never binds. The pooler does. In transaction mode a server connection is held from BEGIN to COMMIT, **including while a loop waits for the application-row lock**. Mean server connections = rate x hold, hold = 51.6 round trips x r + 0.12 s
  (44.6 statements plus BEGIN and COMMIT of 3.5 transactions a request, 0.07 s of server time, a little Python): 5 / 9 / 15 at 2 / 5 / 10 ms at the window rate. The peak is the lock queue, up to N: 24 loops are 24 + minute worker + web, 26 to 30,
  against `max_connections` 60 shared with Auth, PostgREST and the pooler, and a pooler pool that is [unknown] (your figures: 60; pool unknown).
- **Pool 6 (Fdb)**: ceiling = pool / hold = 6 / (51.6 x 0.008 + 0.12) = 11.3 requests a second; Fdb measured 11.5 [arithmetic agrees with a hosted receipt]. At a pool of 6 no loop count helps: the pool is the ceiling. Fdb's 145 releases and 106
  lock timeouts were on `02fd679b`; at `1f51d8e4` they are 1.5 s waits and the ceiling is the same.

## 4. Statements per request

[measured] Real lane code at `de7f6ba6` (the head's parent; the head changes error handling only), one loop, 6 posts, uncontended: **25.0 transactions, 197.5 statements, 247.5 round trips with BEGIN and COMMIT a post**; 6.33 requests a post,
so 31.2 statements (39.1 round trips) a request. Hosted S1 says 44.6 a request (the receipt calls it statements and round trips), 14 percent above my round trips: claim misses, outlook reads, re-passes [inferred]. By owner: the coordinator's own transactions 12.8 and **125.2 statements** a post (63 percent); the consume
(F5 guard plus coordinator) 11; the lane and worker **61.4** (claims 25.2, completion 12, seal 10, two short result transactions 10, soonest 1.2, outlook 3).

Lane-owned candidates a post (none touches F5's no-second-renewal, F2's restore or the grant checks, which stay as statements):

| saves | what | how |
|---|---|---|
| 6.0 | two `to_regclass` probes at the start of every claim (hosted_worker.py:183, :468) | the loop proved both tables at its start (`_projection_ready`); skip them for `LaneWorker` |
| about 8 | 22 pure `SELECT clock_timestamp()` reads a post, all in worker transactions (`_db_now`, :141) | return the first with the row-lock statement (the select list is evaluated after the lock) and merge the back-to-back pairs of a claim; keep the read after the member and credential waits (:1102) |
| 4.0 | `hold_active` and the membership read, 4 of each a post | one statement |
| not | the six SAVEPOINT statements of the completion (they keep a telemetry failure from aborting the post's record), the cursor upsert, the outlook | |

Total about 18 (up to about 25 with more clock folds and the claim's second membership read, if it is a duplicate; neither checked): 2.5 to 3.5 round trips a request, 5 / 12 / 25 ms (7 / 17 / 35) at 2 / 5 / 10 ms, **0.8 / 1.7 / 2.6 percent (1.1 / 2.3 / 3.7)
of a 12-loop request cycle** (0.65 / 0.75 / 0.95 s), and nothing once the window (16 loops and up at 2 ms) or the lock binds. It is not worth risking the inherited claim, seal and consume code for that. The larger share is the coordinator's (the limiter's file): the `set_config`
of every transaction (13.7 a post, foldable into its first statement), the INSERT-and-reread of a new route bucket (5.3 triples, 10.7 statements removable), the two single-row admission lookups that could be one (6.3): about 30 a post, 4.3 round trips a request
(1.3 / 2.9 / 4.5 percent). All of them run before the application-row lock, so they shorten the cycle, not the lock hold.

A correction to the cycle table (RESULTS-GITHUB.md:580): its 45 ms per millisecond leaves out the connection set-up the harness itself emulates (`db_connect_rtts` 4, capacity script :67) for 3.5 new connections a request, 14 ms more per
millisecond: 12 loops give 15.0 at 5 ms (15.7 there) and 11.3 at 10 ms (12.5). The table in 5 stays on your basis; with the term every 5 and 10 ms cell falls by about 5 and 10 percent and the gain of 16 loops over 12 rises by about 2 points.

## 5. Recommendation

Closed-network arithmetic as in your table (M/M/1//N reproduces its 18.2, 19.8, 20.9, 21.8 at guard 0.1 and its 15.7 and 12.5), guard 0.05 (window 22.9 a second), Z moved by 44.6 x (r - 2 ms); a deterministic slot clock does slightly better, so these are
floors. Requests a second / median lateness in minutes (S1-lane56 14.51 x 18.6 / rate; the standard is 12) [inferred]:

| round trip | 12 loops | 16 loops | 24 loops |
|---|---|---|---|
| 2 ms | 18.6 / 14.5 | 21.7 / 12.4 | 22.9 / 11.8 |
| 5 ms | 16.0 / 16.9 | 19.7 / 13.7 | 22.7 / 11.9 |
| 10 ms | 12.6 / 21.4 | 16.3 / 16.6 (at the lock) | at most 14 to 17 (lock) / 16 to 19 |

The lock bound is an estimate [inferred]: 7.2 exclusive reservations and about 2 exclusive observations a post (9.3 exclusive and 5.5 shared lock statements, RESULTS-GITHUB.md:503), each holding the application row for 4 to 8 round trips
(rate_limits.py:955), allow 52 to 59, 26 to 31 and 14 to 17 requests a second at 2 / 5 / 10 ms, no more (the shared holds also exclude reservations while they overlap). Unmeasured; `sens` reads it (the harness has counted lock
timeouts since `84fe4655`). At 10 ms 16 loops already sit at it.

| rank | change | size | risk | what would justify it |
|---|---|---|---|---|
| 0 | keep 12; run `sens` (S1, S1-24 at 5 and 10 ms) and add `S1-16` | a harness entry, capacity branch | none | the answers to "is the gain there at 5 ms" and "does the lock hold at 24" |
| 1 | **16 loops: 4 more crons** | lane.py 1 line, vercel.json 16, preflight 1, four test pins, about 40 lines of documents | cron limit [unknown]; +5,760 invocations a day; idle connections +33 percent; pooler peak +4 | S1-16 or S1-24 at 5 ms: requests a second +15 percent or more, median and p95 moving toward 12 / 25, no rise in lock timeouts or busy waits, `horizonRefusals` 0, pooled connections under 70 percent of the pool, 0 duplicates |
| 2 | 24 loops: two per process | about 40 lines in lane.py, 100 of tests, policy tool 2, documents about 60 | shared provider state (both loops stop for 45 s), the horizon at its edge, the lock queue at high round trip | S1-24 at 10 ms with no growth in lock timeouts; a pooler pool measured at 28 or more |
| 3 | 24 loops: 12 more crons | rank 1 plus 32 JSON lines | cron limit (25 in all) | as rank 2 |
| 4 | the pooled factory (`POSTRIFF_DB_POOL_ENABLED`) | environment only, the owner's approval | not code; the code already assumes transaction mode (`prepare_threshold=None`, postgres_pool.py:66) | a pooled against an unpooled S1 at 5 and 10 ms (the harness does not pass the variable today): it removes 3.5 connection set-ups a request |
| 5 | merge lane-owned statements | about 40 lines in hosted_worker.py (shared) and lane.py | touches claim, seal and consume | none: 1 to 4 percent |

Plainly: **12 stays for the release candidate.** The change I would make next is rank 1, and only on the `S1-16` or `S1-24` receipts at 5 ms. Go to 24 only through rank 2, and only if the cron limit is the obstacle. Beyond
about 8 to 10 ms no loop count gets more than about 17 a second; there the levers are the pooled factory and the coordinator's statement shape, not loops.
