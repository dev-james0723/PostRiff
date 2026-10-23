# W-02 capacity simulation (offline; no network, no Discord, no Depot)

`scripts/discord_lane_capacity_sim.py` has two parts. Neither is the owner's capacity run (row 9 of approval packet 1,
the Depot harness on the unmerged #197 branch), which is a later, separately approved step and was not attempted.

## What is simulated, and what is not

| | Model (`model`) | Real run (`real`) |
|---|---|---|
| Code | arithmetic only | the actual lane, claim, leases, triggers (126, 128), shared coordinator (124) and sender |
| Database | none | disposable local PostgreSQL 16 (sub-millisecond round trip) |
| Discord | none | in-process mock: 50 ms per request, rate-limit headers, five creates per channel per five seconds, counts every create by its nonce and every request above 50 in a trailing second |
| Clock | fake | real seconds |
| Cron | 50-second loops every minute | 12 loops started together, each with the default 50-second budget, again each minute until drained |

Not measured by either: real Discord latency and behaviour, the production database round trip (the coordinator's row
lock and every transaction cost far more there), TLS connection setup per transaction, Vercel cold starts and
concurrency, shared egress-address limits, large workspace documents (every claim and completion rewrites the whole
workspace document).

## Real run: the actual code at the 25 per second policy, 12 loops, 400 synthetic posts in 400 workspaces

Command: `POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin python3 scripts/discord_lane_capacity_sim.py real --posts 400`

| | Lane as built | Same, with the create-permit wait off (`--unpaced`) |
|---|---|---|
| Verified | 400 of 400 | 400 of 400 |
| Create permits that waited for the next window | 192 | 0 (wait off) |
| Duplicate creates | 0 | 0 |
| Requests above 50 in any trailing second | 0 | 0 |
| Busiest trailing second | 40 requests | 36 |
| Requests per verified post | 6.12 | 10.1 |
| Average request rate | 22.5 per second | 20.7 per second |
| Posts per second | 3.67 | 2.05 |
| 5,000 posts, extrapolated | about 22.7 minutes | about 40.6 minutes |
| Posts released by a rate refusal | 2 | 391 |

Requests per verified post above six are preflight reads that a refusal later made worthless; the create-permit wait
removes most of them.

The same run at a **50 per second policy** (12 loops): 400 of 400 verified, 0 duplicates, 6.32 requests per post, 34.2
requests per second (12 loops at 50 ms per request could not fill 50), 5.4 posts per second (about 15.4 minutes for 5,000),
and **166 requests above 50 in a trailing second (busiest second: 56)**. A fixed one-second window of 50 can admit up to
100 across a window boundary; that is why the reviewed policy is 25. Approaching Discord's 50 safely needs shorter
windows (for example 8 per 0.2 seconds: 40 per second on average, at most 48 in any second), not a larger number.

## Model: time to drain a burst of posts due at the same moment

Command: `python3 scripts/discord_lane_capacity_sim.py model`. Assumptions: every post in its own workspace; 150 ms per
Discord request; 30 ms per database transaction; a read-back five seconds after its create; loops admit steps for 50 of
every 60 seconds; every request holds the coordinator's policy row lock for the given time (a stand-in for the
production round trip). "Budget only" is posts × requests ÷ rate, the floor.

| Posts | Policy | Requests per post | Lock per request | Loops | Drain | Posts/s | Budget only | Past the one-hour approval |
|---|---|---|---|---|---|---|---|---|
| 5,000 | 25/s | 1 | 4 ms | 12 | 3.8 min | 21.9 | 3.3 min | no |
| 5,000 | 25/s | 2 | 4 ms | 12 | 7.8 min | 10.7 | 6.7 min | no |
| 5,000 | 25/s | 6 (today) | 4 ms | 12 | 23.0 min | 3.6 | 20.0 min | no |
| 5,000 | 25/s | 6 (today) | 40 ms | 12 | 23.8 min | 3.5 | 20.0 min | no |
| 5,000 | 50/s | 1 | 4 ms | 16 | 2.4 min | 34.9 | 1.7 min | no |
| 5,000 | 50/s | 2 | 4 ms | 16 | 4.5 min | 18.5 | 3.3 min | no |
| 5,000 | 50/s | 6 (today) | 4 ms | 16 | 11.7 min | 7.1 | 10.0 min | no |
| 5,000 | 50/s | 6 (today) | 40 ms | 16 | 23.1 min | 3.6 | 10.0 min | no |
| 100,000 | 25/s | 1 | 4 ms | 12 | 79 min | 21.0 | 67 min | yes |
| 100,000 | 25/s | 2 | 4 ms | 12 | 159 min | 10.5 | 133 min | yes |
| 100,000 | 25/s | 6 (today) | 4 ms | 12 | over 4 h | | 400 min | yes |
| 100,000 | 50/s | 1 | 4 ms | 16 | 49 min | 33.9 | 33 min | no |
| 100,000 | 50/s | 2 | 4 ms | 16 | 91 min | 18.4 | 67 min | yes |
| 100,000 | 50/s | 6 (today) | 4 ms | 16 | 235 min | 7.1 | 200 min | yes |

The full table (also 20 ms locks) is printed by the command. Readings:

- At today's six requests per post the 25 per second policy, not the number of loops, is the limit: 12 loops keep it
  busy (measured 22.5 of 25 per second).
- The coordinator's row lock caps the whole system at one request per lock time. At 40 ms per request (four
  statements at a 10 ms round trip) it cannot pass 25 per second, so a 50 per second policy then gains nothing. The
  production round trip is the first thing the owner's capacity run should measure.
- The 50-second loops and the five-second read-back wait add 10 to 20 percent to the budget-only floor.
- Bursts of 100,000 outlast the one-hour approval at every setting except one request per post at 50 per second.

## Correctness in every run

0 duplicate creates and 0 requests above the trailing-second ceiling at the 25 per second policy, in every real run.
The 24 real-PostgreSQL tests (`tests/test_discord_parallel_lane_postgres.py`) assert these properties directly, with
crashes, races, holds, a global 429, a spent invalid-request budget and expiring approvals.
