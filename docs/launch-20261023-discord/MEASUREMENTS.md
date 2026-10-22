# R-04 and R-05: connect burst and worker throughput

Derived from the code and the repository's own harness constants. **Nothing here was measured against real Discord or a real worker invocation**; the real figures need the capacity run (AUTH-2, `APPROVAL-PACKET-1.md` row 9). Statements are labelled [Certain] (read from code or a test), [Likely] (inference) or [Guessing].

## R-04 Connect burst

| Quantity | Value | Basis |
|---|---|---|
| App-wide request budget in the proposed policy | 25 requests per second, 1 second window | `scripts/discord_rate_policy.py` defaults; Discord's documented ceiling is 50 per second per bot, and the budget is kept at half so two back-to-back windows stay inside it [Certain for the numbers, Likely for Discord's ceiling] |
| Requests per onboarding in the capacity harness | 39 (identity: token, `@me`, user = 3; installation: 3 each for two steps = 6; five permission-evidence reads for each of six destinations = 30) | `bootstrapRequestLowerBoundPerUser` in `tests/phase2/postgres_discord_capacity.py`; the harness calls it a lower bound because it leaves out the server and channel listings and refreshes [Certain] |
| Requests for a typical single-server, single-channel connect | about 12 to 20 | counted from the same steps with one destination plus the listings [Guessing] |
| Onboardings per second at the budget | about 0.64 at 39 requests; about 1.7 at 15 | 25 / 39 and 25 / 15 |
| Onboardings per hour at the budget | about 2,300 at 39 requests; about 6,000 at 15 | arithmetic |
| Day-1 assumption (D-06) | 300 connect attempts per hour at peak | checklist default |
| Budget used by the assumption | about 3.3 requests per second, 13 percent of 25 | 300 x 39 / 3600 |

Conclusion for Wave 1 [Likely]: the request budget is not the constraint at 90 servers. The cap and the invalid-request budget are. At Wave 2 volume the budget and the bot's 50 per second ceiling matter and the figures need the capacity run.

What a person sees when the coordinator refuses (new in the release candidate, English, Traditional and Simplified Chinese):

- delayed, `discord_rate_delayed` (HTTP 429): "Discord is busy right now. Nothing was connected or posted. Try again in a minute."
- unavailable, `discord_rate_coordinator_unavailable` (HTTP 503; for example an expired policy): "Connecting to Discord is paused for a moment. Nothing was connected or posted. Try again later."

Before this change the person would have seen the server's operator wording ("Restore the reviewed rate policy or reconnect").

A refusal at the OAuth callback, after Discord's consent screen, can leave the bot in a server without a finished Rafii connection. The server cap counts installations that are started or mid-exchange so a slot is held for them; the person is told to start again from Channels.

## R-05 Worker throughput

What the code does [Certain, `hosted_worker.py` and `tests/test_discord_worker_budget.py`]:

- One cron, `/api/cron/worker`, every minute. One invocation runs at most `POSTRIFF_WORKER_MAX_JOBS` steps (default 10, allowed 1 to 25) and stops at `POSTRIFF_WORKER_MAX_SECONDS` (default 20, allowed 1 to 45).
- A Discord post needs at least two steps: the create (the request is built after a rate reservation and an intent are committed) and a separate reconciliation step that reads the message back. `tick_discord` (a Discord-only lane) exists but is not wired to any cron.
- With the Discord worker flag on, the Discord lane and the other providers alternate; when both have work each gets every second step, and when one is idle the other gets all of them.

| Budget | Steps per minute | Discord posts per minute, only Discord work | Discord posts per minute, other providers also busy | 60 posts due in one minute drain in |
|---|---|---|---|---|
| default 10 jobs, 20 s | 10 | 5 | about 2.5 | about 12 minutes (up to 24) |
| 25 jobs, 40 s | 25 | 12 | about 6 | about 5 minutes (up to 10) |

These assume each step finishes quickly enough for the job budget to be the binding limit. If a step takes longer than 2 seconds at the default (or 1.6 seconds at 25 jobs and 40 s), the time budget binds first and throughput is lower [Likely]. I have no measurement of the real step latency.

Decision (R-05): for Wave 1 the load assumption (at most 600 scheduled posts per day, at most 60 due in one minute) is acceptable at the default budget, but a burst at a popular time such as the top of the hour would run up to about 12 minutes late. Raising the budget to 25 jobs and 40 seconds (Approval Packet 1, row 3) is cheap insurance and affects all providers. The schedule dialog now says plainly that Discord posts due in the same minute can arrive several minutes late. A parallel or dedicated Discord lane (checklist W-02) is a Wave 2 item and needs lease-fence proofs and the capacity run first.

Approval timing interacts with lateness: an approval expires, and a post that cannot be sent before its approval expires is held for a fresh approval, not sent late. The runbook monitor Q7 (oldest eligible lag) shows how late the queue is running.

## R-05 update 23:13Z: the owner wants thousands to tens of thousands of users

The cap is set to 10,000 servers, so the cap is no longer what limits use. The worker is. With the approved budget (25 jobs, 40 seconds) the figures above give 12 Discord posts a minute when only Discord has work and about 6 when other providers are busy, that is 8,640 to 17,280 posts a day at best, spread perfectly. Real traffic is not spread: a day's posts cluster in a few hours.

| Customers who post that day | Posts each | Posts that day | Average per minute | At 5 times the average (a peak) | Reading |
|---|---|---|---|---|---|
| 1,000 | 2 | 2,000 | 1.4 | 7 | fits at 12 a minute; may queue at 6 |
| 5,000 | 2 | 10,000 | 6.9 | 35 | queues for hours at a peak |
| 10,000 | 3 | 30,000 | 20.8 | 104 | the queue grows all day: needs parallelism |

Arithmetic only, with invented usage; step latency is not measured. What a customer sees when the queue is long: the schedule dialog says posts may arrive several minutes late; a post whose approval expires first is held for a fresh approval. The monitor Q7 (oldest eligible lag) shows it. The next engineering step is W-02 (a parallel or dedicated Discord lane); it needs the lease-fence proofs and the capacity run, and it is a new release candidate, not part of the frozen build.

