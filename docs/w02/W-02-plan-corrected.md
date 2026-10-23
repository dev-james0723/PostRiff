# W-02 plan, checked against the code (corrections to `W-02-parallel-sending-plan.md`)

The original plan (ledger branch, `docs/launch-20261023-discord/W-02-parallel-sending-plan.md`, written 2026-10-22 before
any code) is checked here claim by claim against the frozen candidate `2a5a523d` and this branch. Where the code
disagrees, the code wins. Labels: [code] read from the source; [measured] local real-PostgreSQL runs with a mock Discord;
[simulated] the fake-clock model in `scripts/discord_lane_capacity_sim.py`.

## Section 1: what is sent, and the real ceiling

| Plan said | The code says | Verdict |
|---|---|---|
| "Every post costs at least two requests today: the create and a separate read-back" | Six on the bot path: before every create the permission preflight reads the server, the bot's membership, the linked person's membership and the channel list (`DiscordProvider.destinations`, called from `HostedSocial.prepare_discord_dispatch` for every create), then the create, then the read-back in a later step. The bot identity adds two reads per process per minute (cached 60 s). Grant lookup does no provider I/O [code]. 6.12 requests per verified post at 25 per second, 6.32 at 50 [measured]. | **Corrected: six, not two.** "At least two" is literally true but every time in the plan's table is three times too short. |
| Policy 25 requests per second, half of Discord's 50 | Yes: `scripts/discord_rate_policy.py` defaults (`app_capacity` 25 per 1-second window); the reason is that two adjacent fixed windows can admit 2 × 25 within one trailing second [code]. A 50-per-second policy admitted up to 56 requests in a trailing second, 166 requests above 50 in a short run [measured]. | Confirmed. Raising the policy to 50 per 1 s is not the same as using Discord's 50 per second safely; shorter windows are (for example 8 per 0.2 s: 40 per second on average, at most 48 in any second). |

Corrected table (5,000 posts due in the same minute, 12 loops at 25 per second, 16 at 50; drain includes the five-second
wait before each read-back and the cron's 50-second loops):

| Requests per post | Rate | Time to send all | Basis |
|---|---|---|---|
| 6 (today) | 25 per second | about 23 minutes | [measured 3.67 posts/s, extrapolated 22.7 min; simulated 23.0 min] |
| 6 (today) | 50 per second | about 12 to 15 minutes | [simulated 11.7 to 12.5 min; measured 5.4 posts/s with 12 loops, 15.4 min: 12 loops did not fill 50 per second] |
| 2 (create and read-back only) | 25 per second | about 8 minutes | [simulated 7.8 min] |
| 2 | 50 per second | about 5 minutes | [simulated 4.5 to 4.8 min] |
| 1 (read back only when uncertain) | 25 per second | about 4 minutes | [simulated 3.8 min] |
| 1 | 50 per second | about 2.5 minutes | [simulated 2.4 to 2.5 min] |

100,000 posts due at once: about 80 minutes at one request per post and 25 per second, 160 minutes at two, more than four
hours at today's six [simulated]. An approval lives one hour after the scheduled time, so at today's six requests per post
about 13,000 posts due in one minute can go out inside that hour; the rest are held for a fresh approval (OPEN-QUESTIONS.md
Q1).

## Section 2: why it is slow today, and what is already in place

| Plan said | The code says | Verdict |
|---|---|---|
| One cron runs `/api/cron/worker`; at most 25 steps in 45 s, shared with every provider and the maintenance work; the limits are code constants, not function limits (the function may run 300 s) | `configured_worker_limits`: `POSTRIFF_WORKER_MAX_JOBS` default 10, allowed 1 to 25; `POSTRIFF_WORKER_MAX_SECONDS` default 20, allowed 1 to 45 (environment values inside code bounds). With the Discord worker flag on, Discord and the other providers alternate steps. `maxDuration` 300 for `api/index.py` [code]. | Confirmed (the limits are environment-tuned within code bounds). |
| Safe for many workers: workspaces claimed `FOR UPDATE ... SKIP LOCKED`, each worker its own id, each job a lease owner and lease id rechecked at every step | Confirmed, and more: the Discord-only claim takes no global lock, locks one workspace per selection (at most eight examined per claim), allows **one live Discord lease per workspace**, and rotates workspaces by a durable least-recently-served cursor; migration 128 rejects any Discord lease acquired without the current protocol; an intent is sealed before every create and a sealed intent is never re-posted [code]. 8 loops, 120 posts: each created exactly once [measured]. | Confirmed. The one-lease-per-workspace rule is also a cap: one customer's 1,000 posts go one at a time (OPEN-QUESTIONS.md Q6). |
| `tick_discord` exists and is not wired to any cron | Confirmed [code]. The lane does not use it: it runs the same `step(discord_only=True)` in its own loop. | Confirmed. |
| The coordinator denies a request before it is sent when the budget is used up, so more workers cannot push Rafii past its policy | Confirmed: every request (reads included) is admitted in a short transaction on the application-wide policy row before any HTTP [code]; 12 loops at a 10 per second policy never exceeded 20 in any second, and a control run at 1,000 did [measured]; the test now runs at 3 per second (ceiling 6), a cap the loops meet on a slow runner too [measured]. Two qualifications: a request whose process died in flight keeps its slot until reviewed (OPEN-QUESTIONS.md Q3); and every request of every worker takes a row lock on that one policy row, so the coordinator's own throughput is bounded by the database round trip (at 40 ms of lock time per request it cannot pass 25 per second whatever the policy) [simulated]. | Confirmed with the two qualifications. |
| "Different customers are different workspace rows, so 5,000 customers do not contend with each other" [likely] | True for workspace rows. They do contend on the coordinator's application-wide rows (one row lock per request) and on any Discord channel they share (about five creates per channel per five seconds, learned from Discord's headers) [code; measured: one channel shared by six workspaces, no create refused]. | Partly. |
| The capacity run on the earlier branch used 16 workers [handoff note] | Not verifiable from this repository (the harness is on the unmerged #197 branch). | Unchecked. |

## Section 3: the plan, in order

| Step | Plan | Built or found |
|---|---|---|
| 1 | A Discord-only route looping up to about 4 minutes per invocation; a dispatcher that starts 12 to 16 when work is due and chains a successor | **Changed.** Built K = 12 cron shards (`/api/cron/discord-worker/<n>`), each a 50-second loop (cap 90 s), no dispatcher and no chaining (AS-BUILT.md compares the two). Four-minute loops started every minute would overlap about four deep per shard, multiplying concurrency and connections without adding budget. The lane needed one more change the plan did not foresee: at a saturated budget, refused create permits wasted their four preflight reads (with that wait off, 25 per second produced far fewer posts; CAPACITY-SIMULATION.md), so a refused create permit now waits for the next window, at most one second. |
| 1 | Budget limits raised for that lane only | Done: its own flag and budget variables, bounded so a step admitted at the deadline still ends inside 300 s. |
| 1 | Tests on PostgreSQL that two workers never send one post twice | Done, and more (AS-BUILT.md, 24 real-PostgreSQL tests). |
| 1 | Capacity run with the mock set to 50 requests a second (approval row 9, owner's Depot) | Not run (a later, separately approved step). Note for it: 50 per 1-second window exceeded 50 in a trailing second in the local run. |
| 2 | Random offset of up to two minutes on the scheduled time, said in the schedule dialog | Not built (Phase 1b, needs product copy). |
| 3 | Prepare before the minute | Not built. The preflight is four of the six requests; doing it before the minute would move them out of the burst but they still count against the same budget. |
| 4 | One request per post | Not built (changes the evidence design). Its effect is now quantified: six to one requests cuts the 5,000-post drain from about 23 to about 4 minutes at 25 per second. |
| 5 | Approvals that expire while waiting are held, never sent late | Confirmed in code and test: rechecked at claim, before sealing and in the final pre-send guard, and a lease never outlives the approval [code, measured]. One edge: an approval that expires between sealing and sending leaves the post 'uncertain' (nothing sent) rather than 'held'. |
| 6 | Higher Discord limit; webhook limits | Open (OPEN-QUESTIONS.md Q9, Q10). |
| 7 | Always-on worker | Open (Q11). |

## Section 4: risks, added to the plan's list

- Requests per post are six, so every capacity statement in the plan was optimistic by a factor of three.
- A process that dies with a request in flight leaves a slot counted until reviewed, and can block a channel's first route
  until then (Q3); more loops mean more requests in flight.
- An operator hold can leave up to one post per loop 'uncertain' with nothing sent (Q4).
- The coordinator's single policy row is a serialization point whose cost is the production database round trip, not
  measured here.
- Each transaction opens a new database connection unless the pooled factory is enabled: about 20 per post.
- 12 cron entries cost about 17,000 invocations a day even when idle (Q5).
