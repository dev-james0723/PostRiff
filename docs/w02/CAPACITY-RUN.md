# W-02 capacity harness (gate G5): how it works and how to run it

`scripts/discord_lane_capacity_run.py` measures the Discord send path in real time, with separate OS processes and
the tested tree's own code, against the written standard `docs/w02/capacity-standard.json` (RELEASE-DEFINITION-v2
section 4; owner reply 13 accepted it provisionally as the RC2 stress threshold). It replaces nothing in the
application: it reads a source tree (`--source-tree`, any SHA: RC1, a W-02 head, RC2) and never writes to it.
Results from this sandbox are in `RESULTS-SANDBOX.md`; the official run is meant for the owner's Depot CI
(`docs/w02/depot/discord-lane-capacity.yml.txt`, an inert draft).

Labels used below: [built] what the code does; [measured] seen in a run; [assumed] a choice of the harness.

## What runs

```
cron emulator (parent process, real wall clock: every 60 s at :00 + delivery jitter)
  |-- one fresh OS process per invocation, started 8 s early, importing the tested tree's api/index.py, then at its
  |   cron time serving exactly one GET /api/cron/discord-worker/<n> (n = 0..11 from the tree's vercel.json) or
  |   GET /api/cron/worker through the WSGI app with the cron secret; killed at 300 s (maxDuration)
  |        | Discord: the unchanged http_transport; providers.build_opener sends https://discord.com/api/v10/... to
  |        |          the mock on 127.0.0.1 over plain HTTP (no proxy); any other host or DNS name is refused
  |        v
  |   mock Discord (one process): latency per request, 50/s global ceiling (429 global above it), 5 creates per
  |   5 s per channel, read buckets with x-ratelimit headers, nonce and post-id duplicate counters, isolation check,
  |   failure injections, full request log with its own timestamps
  |        | database: the production factory (one new connection per transaction, POSTRIFF_DB_POOL_ENABLED unset)
  |        v
  |   pooler (one process): transaction pooling over --max-db-connections server connections, --db-latency-ms per
  |   round trip, setup round trips per new client connection, wait and hold timings, SQLSTATE counts
  |        v
  |   PostgreSQL: throwaway cluster from --pg-bin with the production migration set (or an external server)
  |-- sampler (1 s): pg_stat_activity, pooler, CPU of PostgreSQL / mock / pooler, load average, job states (10 s)
  |-- injectors: SIGKILL of shard processes (random and during a create held by the mock), lock holds on the
      coordinator's application row and on workspace rows, cron stalls, lane flag off/on
```

| Piece | Real | Emulated |
|---|---|---|
| Lane, minute worker, claim, leases, approvals, sender, coordinator, schema, triggers | the tested tree's code and migrations [built] | |
| Route, cron-secret check, WSGI parsing | `api/index.py` `app`, one request per process [built] | Vercel's HTTP layer |
| Data | made by the application's own bootstrap, Discord identity link, installation, `choose_destination`, `p2_review`, `p2_approve` [built] | the token exchange itself; Discord answers come from the mock world |
| Invocation isolation | a fresh process per invocation, no shared connections, caches or coordinator state [built] | Vercel containers, cold-start time, Fluid co-location |
| Database | PostgreSQL 16 here (17 on Depot), production migrations, `shared_buffers` 224 MB | Supabase network latency (constant `--db-latency-ms`), Supavisor (harness pooler, no TLS) |
| Discord | | everything: latency, limits, 429 shapes, failures |

The harness itself runs from a copy of its scripts taken into the run directory at the start, so editing the
harness during a run changes nothing in that run.

## Running it in the sandbox

Prerequisites: PostgreSQL server binaries (`POSTRIFF_PG_BIN`, here `/usr/lib/postgresql/16/bin`), the project's
Python with its requirements (here `/opt/prvenv/bin/python`). Take a detached, read-only copy of the SHA under test:

```bash
git -C /home/user/PostRiff worktree add --detach "$SCRATCH/trees/23af7a3a" 23af7a3a55dfeaf15a591dafbc061072be382d53
export POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin PYTHONDONTWRITEBYTECODE=1
uptime   # other agents share the machine; note the load and re-run anything measured under heavy load
nice -n 10 /opt/prvenv/bin/python scripts/discord_lane_capacity_run.py run --scenario S1 \
    --source-tree "$SCRATCH/trees/23af7a3a" --out "$SCRATCH/runs" --label w02-23af7a3a > "$SCRATCH/s1.out" 2>&1 &
tail -f "$SCRATCH/s1.out"     # one progress line per minute; RECEIPT.md and result.json at the end
```

`profile --name release` runs every scenario in turn and writes `SUITE-release.md` (one line per planned scenario,
NOT RUN for any that did not run); `--only S1,S2` narrows it. `analyze RUN_DIR` recomputes a receipt from the raw
files. `scenarios` lists the scenarios. `seed-check --scenario S1` runs only a scenario's seeding (its layout and
its seed processes, released together) on a throwaway cluster and cleans up: a two-minute check of the multi-process
seeding path. The self-checks: `python -m unittest tests.test_discord_lane_capacity_harness` (fast checks always; the
live smoke and a four-process seed check when `POSTRIFF_PG_BIN` is set; `CAP_HARNESS_FULL=1` adds a live ceiling
control).

Seeding with several processes: each seeding process opens its own connection to the mock world but they share the
coordinator, and the bot's own routes (`GET /users/@me`, `GET /oauth2/applications/@me`) have no major parameter, so
while they are still unknown the coordinator admits one discovery request per second for all processes together. The
provider waits at most one second for a read admission and then raises `ReadAdmissionDelayed` (no request was sent):
on an idle GitHub-hosted runner the four seeders start at the same moment and one of them died this way (all four
scaled requests on 2026-10-23, harness 920991d6). The seeder now retries such a delayed GET (never a write), the
harness releases the slices together on purpose so every run meets the worst case, a failing slice's own output
(`seed-<n>.out`) is quoted in `harness.log` and in the error, and the harness refuses a seeding that leaves a request
admission `sent` or `uncertain` (it would hold a slot of the run's budget for good).

A full S1 takes about 40 minutes here (6 minutes of seeding, a lead to T, the drain, collection). The baseline
scenario measures the frozen worker, so point it at RC1: `--source-tree "$SCRATCH/trees/2a5a523d"`.

## Scenarios

| Name | What | Judged by |
|---|---|---|
| `smoke` | 30 posts, 10 workspaces, 20-second cron period, 4 shards | every post verified, no duplicate, no late send, isolation, clean invocations |
| `S1` | 5,000 posts due at T over 2,000 workspaces | section 4 (lateness, duplicates, late sends, ceilings, held, database) |
| `S2` | the same 5,000 with one workspace holding 3,000 | section 4 plus fairness |
| `S2-100`, `S2-300`, `S2-1000` | the same 5,000 posts with the hot workspace holding 100, 300 or 1,000 (profile `s2sizes`; the 3,000 case above stays as the stress case) | judged as S2; the receipt adds the hot workspace's document size, per-transaction time, create rate while it has due posts (REPORTED) and posts per minute |
| `S3` | 13,000 posts due at T | section 4; where approval expiry starts holding posts |
| `S0-100`, `S0-250` | 100 or 250 posts due per minute for 20 minutes, 30% of them at a random second of their minute | `normalLoad` |
| `baseline` | lane flag off, S1 data, 10 minutes, on the frozen RC1 | posts per minute of the minute worker |
| `F429` | global 429 windows (Retry-After 5 s and 3 s), per-route 429 on 5 creates and 5 reads, HTML ban page on 2 reads | no storm, recovery, create-429 held not resent, ban page holds its route, others verified |
| `F5xx` | 500 and timeouts on create, landed or not | never resent, uncertain, others verified, leaked admission slots |
| `Fcrash` | S1 with 6 random SIGKILLs and 4 SIGKILLs during a held create | no duplicate, verified or uncertain only where a kill hit a sealed send, drain completes |
| `Fdb` | pool of 6, 8 ms round trip, 1.5 s statement timeout, 2.5 s lock holds on the coordinator row every 20 s | no duplicate, no starvation, errors reported |
| `Fexpiry` | approvals that lapse 4 minutes into the run (seeder clock seam) | nothing sent late, the rest held |
| `Fstall` | no cron for 10 minutes after T | nothing sent during the stall, all verified after it |
| `Fflip` | lane flag off T+2 to T+6 min | minute worker takes Discord back, lane resumes, no duplicate across the hand-over |
| `Nmisroute`, `Ndup`, `Nceiling` | negative controls: harness misroutes creates; mock double-accepts; policy 100/s (information only) | the counter must fire |

Every scenario also gets the common lines of the standard (duplicates, late sends, ceilings, organic 429s, invalid
requests, database share, statement timeouts) unless the standard marks it not applicable.

## Options that matter

| Option | Default | Meaning |
|---|---|---|
| `--source-tree` | (required) | detached checkout of the SHA under test; its SHA goes into every receipt |
| `--mock-latency` | `uniform:50:150` | ms per Discord request; `fixed:300`, `uniform:150:300`; `--mock-tail-probability`/`--mock-tail-ms` add a tail |
| `--db-latency-ms` | 2 | added per database round trip (half each way) [assumed: Vercel iad1 to the Supabase us-east-1 pooler] |
| `--db-connect-rtts` | 4 | extra round trips per new client connection (TLS and SCRAM a hosted pooler adds) |
| `--max-db-connections` | 20 | pool size; demand beyond it waits like a transaction-mode pooler queue |
| `--lane-max-seconds` | 50 | `POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS` (5 to 120 at 14b78944; at most 90 from 91629568) |
| `--shards` | from `vercel.json` | number of lane cron routes |
| `--policy-capacity` | 25 | coordinator `app_capacity`; anything else makes the run INFORMATION ONLY |
| `--cron-period` | 60 | seconds between cron firings (only the smoke shortens it) |
| `--invocation-mode` | `cold` | `warm` builds the runtime before the request |
| `--pg-bin` | `POSTRIFF_PG_BIN` | server binaries for the throwaway cluster |
| `--admin-database-url`, `--database-url` | | external server: a fresh database per run is created through the admin URL (dropped at the end unless `--keep-database`) and the application connects through `--database-url` (a pooler), with the relay adding `--db-latency-ms` |
| `--pooler pgbouncer` | `harness` | a real PgBouncer (transaction mode) in front of the throwaway cluster, the relay adding latency; `--pgbouncer-bin`; not exercised in this sandbox (no PgBouncer here) |

## What a run leaves behind

`RECEIPT.md` (start with the differences from production, then PASS/FAIL per measure and per expected behaviour),
`result.json` (every figure), `config.json` (settings, SHAs, load average, the rate policy), `seed-manifest.jsonl`
(every post: workspace, job, nonce, due time, approval expiry), `mock/mock-requests.jsonl` (every Discord request
with the mock's timestamps), `mock/mock-summary.json`, `invocations/*.json` (each invocation's timings, status, body,
CPU, memory, log lines), `invocations-summary.json` (the same without the log lines: the part that is uploaded),
`samples.jsonl`, `pooler-final.json`, `database-final.json` (admissions by state, the open admissions, permit fates,
coordinator holds, pg_stat_statements top statements by maximum and by total time, server-log SQLSTATEs, the
largest document, the budget probes, the coordinator's lock statements counted from `pg_stat_statements`),
`admissions.jsonl` (every admission of the run: reserved, sealed, sent, answered and expiry times, state, path digest),
`attempts.jsonl` (every reservation attempt), `health-samples.jsonl` (the operator's health payload, one reading a
minute and one after the run), `final-states.json`, `postgres.log`, `harness/` (the harness copy that ran). Environment files with the synthetic credential key and cron secret are mode 600 and hold
no real secret.

## Reading a receipt

- Lateness is the mock's create time minus the post's due time. A post never created is infinitely late, so a
  single unsent post makes the maximum fail. The application's own records (database states, lane counters) are
  shown as claims next to the mock's figures.
- "Requests above 25 in any trailing second" is the standard as written. The coordinator admits 25 per fixed
  one-second window, so two adjacent windows can put up to 50 into one trailing second by design; the receipt
  reports that measure as written and the Discord 50/s ceiling separately.
- A count of zero is PASS only when something was sent; a run that sent nothing measures nothing.
- `INFO PASS` / `INFO FAIL` mark an information-only run (an unreviewed setting such as a 100/s policy).
- Time to verified (due time to the read-back the mock answered) sits next to lateness. The receipt also gives the
  number of posts still unverified when the last create happened, and every unverified post by its final database
  state and by whether the mock saw a create attempt for it (an `uncertain` post with no create was never sent).
- The request ledger splits every request into the ideal real path (7 per post: the person's grant check
  `GET /oauth2/@me`, four permission-witness reads, the create, the read-back) and named overhead. Overhead covers
  the bot identity pair, repeated preflight passes, 429 answers, injected failures and extra creates or read-backs.
  It counts preflight passes per post in one-post workspaces. The grant-custody line states that the real OAuthService
  path ran, not the lane fixture's `Grants` stub, with the measured count.
- The admission-to-observation time d and the busiest 60 s and 300 s request rates say how much of the 25/s budget
  the lane could use (about 25/(1 + d) while in-flight requests are charged in two windows; see
  `docs/w02/REQUEST-BUDGET.md`).
- **Launch gates** (a table after the expected behaviour; reported, never raised, and they do not change the
  verdicts above). Admissions left without an observed answer at the end, by state (a `sent` or `uncertain` one
  holds a slot of every window on a tree without an age bound). The application budget probed after the run: the
  harness reserves reads on synthetic routes through the tree's own coordinator until it refuses, once at once and
  once after `budget_probe_delay_seconds` (90 s, longer than any age bound for an unanswered request), then observes
  them with a synthetic answer. Nothing is sent anywhere. A whole budget is 25 of 25. Create permits that died
  unused (expired still reserved, or sealed and then blocked). **Owner reply 16 (D-16), two more rows:** the
  coordinator-stamped sends (`sent_at`, the instant the coordinator let a request leave) in any trailing second
  must stay at or under 25 (PASS or FAIL), and the requests above 25 in a trailing second as they arrive at the
  mock are REPORTED in full (count, peak and cause: the coordinator, wire jitter, the mock's processing order),
  never turned into a pass. The standard's own line (`policy_ceiling`, "== 0" at the mock) is still computed as the
  standard is written; reading it as REPORTED is the owner's decision, not the harness's, and
  `docs/w02/capacity-standard.json` is not changed.
- **Wire timing.** Each admission's `sent_at` (database clock) is joined, by path digest and in order, to the mock's
  arrival of that request. The invocation wrapper stamps every request it forwards with its cron source and with
  the time just before the HTTP call, so the delay splits into admission to call (inside the application) and call
  to arrival (loopback, plus the mock's accept and thread start on the same machine). The receipt prints p50 / p90 /
  p99 / p99.9 / max, the spread above the median, and attributes every request the mock counted above 25 in its
  trailing second: the coordinator had already sent more than 25 in that second ('coordinator'), or the arrivals
  bunched ('wire'), or only the mock's own processing order put it over ('mock'). The same stamps make traffic
  from invocations other than the lane shards visible at the mock.
- **Preflight passes.** From the mock log: passes per created post, what a released pass had completed (so which request
  was refused next), the time until the same workspace's next pass (the re-claim), when in the minute the releases fall, and
  whether the application window held 25 sends within 1.1 s over the second after each release. Per step, the wait from the
  previous answer being observed to the next admission. `scripts/discord_lane_cap_release_trace.py RUN_DIR` prints the
  summary and the sequence of events of a few typical released posts.
- **Reservation attempts.** The invocation wrapper wraps the shared coordinator's `reserve_read`, `reserve` and `consume`
  in every cron process and logs each call (time, seconds taken, operation, request kind, credential kind, outcome, and for a
  refusal the quoted wait, scope and cause) to `attempts.jsonl`. A refused reservation leaves no row in the database, so this
  is its only record. The receipt tabulates attempts, refusals and quoted waits by credential and request kind, and how many
  attempts a read step needed. The wrapper also stamps the admitted permit's id on the request it sends, so an admission is
  joined to its arrival at the mock exactly (older logs are joined by path and order). With booking (the limiter's
  `rate_limits.booking()`, from 02fd679b) a `reserve` or `reserve_read` that finds the window full books the next free slot and
  **sleeps inside the call** until it comes, up to a second, then returns the permit: an admitted call is a slot reached, and
  the seconds it took include the sleep. Three more columns separate it: the seconds the coordinator booked for the call (the
  difference of its own `booking_stats()`), the seconds the call actually slept (a wrapper around `_wait_for_slot`, the gate
  after the sleep included) and the `book_ahead` room the caller allowed. The table splits an admitted call's duration into
  calls that did not book and calls that did. A log of a tree without booking has the zeros; a 13-column log of an older harness
  is read as unbooked.
- **Booking.** The lane's own counters `bookedWaits` and `bookedSeconds` (invocation result and the `discord.lane.completed` line,
  summed over the invocations) next to `rateDelayed`, `permitWaits`, `rateWaits`, `steps` and `positionsKept`; the reads the
  coordinator stored booked (a read stored `sent` at a wire time more than 5 ms after its reservation: the difference is its
  wait; a booked create permit is stored reserved at its slot, so its wait is in the attempt log only); the booked calls of the
  attempt log; and the **health payload**. The runner reads `GET /api/ops/discord/health` through the real WSGI entry (a short
  process at a low priority, not counted among the invocations) every `health_period_seconds` (60; 0 turns it off) and once after
  the run, and keeps the reduced readings in `health-samples.jsonl`. The receipt prints, over the busy readings, `coordinator.booking`
  (`bookAheadSeconds`, `aheadNow`, `horizonSeconds`, `bookedReads60s`, `bookedReadWaitSeconds60s`, `meanBookedReadWaitSeconds60s`,
  `maxBookedReadWaitSeconds60s`), the application row `coordinator.guards.policy` and `coordinator.traffic.admissions60s`. **With
  booking the application row means something else**: `remaining` is the number of slots bookings may still fill (the cap less the
  held and less the slot kept for callers that cannot wait) and `resetSeconds` when a booking is possible again, so a busy lane
  keeps it high and it falls to 0 only when the booked horizon is full and callers are refused again; it is no longer "the window
  is nearly spent". A tree before the route answers 404; the receipt says so and shows no booking reading.
- **Lock statements.** The coordinator's `_locked` statement counted from `pg_stat_statements`: the exclusive form (`FOR UPDATE`:
  one per reservation attempt, and per observation that cannot share the lock), the shared form (`FOR SHARE` guards: a GET
  observation that can share), and the seeding statement, with calls per created post, mean and maximum time (a wait for the row
  locks is part of the time). The ceiling is also given by **wire time** (`sent_at`, the instant a request may leave: a booked read
  is stored at its slot, after its reservation) next to the count by reservation instant, and the admission-to-observation time
  d is measured from the wire time.
- **Witness age.** Per create: the person's grant check (else the server read) of its pass to the create reaching
  the mock, p50 / p90 / p99 / max, and the channel list's age.
- **Per lane step.** Loop seconds (minus waits for the budget and for work) per step, and the database share of it:
  statements per step (each a round trip), server execution time per step, and the emulated network time. The
  statements are those of `pg_stat_statements` after seeding; the harness's own recurring statements carry a
  `/*cap-harness*/` comment and are left out.
- **Hot workspace** (scenarios with one): the document as seeded and at the end (jobs, bytes, one read-modify-write
  timed three times and rolled back), the application's UPDATE of a workspace document (mean and maximum), the
  create rate while it had due posts against the physical one per second per channel (REPORTED only; the
  80% target is a proposal for the owner, not applied), the steady rate between its first and last create, its
  posts per minute, and the small workspaces' own lateness (the proposed scope of the lateness lines).
- Identity tokens: the time left at T of every Discord identity (the harness gives each a 7-day token, so none
  expires during a run), `POST /oauth2/token` refreshes seen at the mock, and the largest channel list answered.
- The machine line comes from the environment: a GitHub-hosted runner names itself (`RUNNER_ENVIRONMENT`,
  `RUNNER_NAME`, `ImageOS`), anything else is "outside GitHub Actions".

## The official runs on GitHub-hosted runners

`docs/w02/ci/discord-lane-capacity.yml.txt` is inert text on this branch. `docs/w02/ci/make_request_branch.sh` builds
an orphan request branch `claude/discord-capacity-run-<profile>-<suffix>` holding exactly that workflow,
`capacity/REQUEST.json` and a `vercel.json` with Git deployments off. A push of it runs the profile on standard
ubuntu-24.04 runners. The runner has PostgreSQL 17 from the signed PGDG repository and PgBouncer in transaction
mode. It uses no secret and no environment, has a read-only token, fetches exact SHAs, and deploys nothing.

| Profile | Jobs (one per scenario and pool) |
|---|---|
| `smoke`, `s0`, `s1`, `s2` | the scenario(s) on the tree under test |
| `s2sizes` | S2-100, S2-300, S2-1000 (S2 with a hot workspace of 100, 300 and 1,000 posts) |
| `devset` | the development measurement set: S1, S0-100, Fdb, Fcrash, F429, one runner each, all at once |
| `s0100`, `fdb`, `fcrash`, `f429` | one scenario of the development set alone, to run it again after a failure or a change (the branch name is `claude/discord-capacity-run-<profile>-<suffix>` as for every profile) |
| `s1lane56` | S1 with each lane loop budgeted 56 s (`POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS=56`) instead of 50: the duty-cycle lever alone, to read next to the S1 of the same tree |
| `faults` | F429, F5xx, Fcrash, Fdb, Fexpiry, Fstall, Fflip, Nmisroute, Ndup, Nceiling |
| `release` | every scenario, baseline included |
| `baseline` | the frozen minute worker on the request's baseline SHA (default RC1) |
| `lockbench` | only the shared request coordinator under 1 to 24 processes (`scripts/discord_lane_cap_lockbench.py`) |

The receipt goes to the step summary. Raw evidence goes to the artifact: receipt, result, config, harness log,
every child process's own output (`seed-*.out`, `pooler.out`, `pgbouncer.out`, `mock.out`), the mock's request log,
PostgreSQL's log and PgBouncer's log. The per-run environment files are never uploaded.

`python3 docs/w02/ci/run_tests.py` runs the workflow's own blocks against local git repositories. It covers request
validation, exact-SHA fetches, the request script, action-validator and shellcheck. With `POSTRIFF_PG_BIN` set it
adds a live four-process seed check, a deliberately failing slice and the smallest lock benchmark (119 checks).

## The official run on Depot

The harness runs unchanged on a Linux runner with PostgreSQL 17 (the PGDG packages `consumer-ready.yml` already
installs). Two database variants, both in the inert draft `docs/w02/depot/discord-lane-capacity.yml.txt`:

1. `--pg-bin /usr/lib/postgresql/17/bin` with the harness pooler (the variant exercised here, now on PostgreSQL 17);
2. `--pooler pgbouncer --pgbouncer-bin /usr/sbin/pgbouncer`: a real PgBouncer in transaction mode with the same pool
   size, the harness relay adding the round-trip latency; PgBouncer's `SHOW POOLS` is sampled every second.

An external server works too: `--admin-database-url` (superuser, direct) and `--database-url` (through its pooler).
Run one scenario per job (the draft's matrix) on runners with at least 8 cores, record `uptime` before and after,
and keep the artifacts. The dispatch, the runner size and the cost are the owner's decision.

## Known limits of the harness

- Seeding goes through the application's connect and approval code and the shared coordinator (so the server routes
  are learned as production's connect flow would have learned them); it runs at about 12 to 15 posts per second
  with 4 processes, slower than a direct insert, and it does not replay the OAuth token exchange.
- The pooler authenticates clients itself without TLS; its connection-setup cost is a constant number of round
  trips. TLS CPU and SCRAM are not exercised.
- The mock's read buckets are 50 per second per route and server, an assumption; real Discord buckets differ by
  route. Its global ceiling counts a trailing second, which is stricter than a fixed window.
- Vercel's own behaviour (cold-start time, several invocations sharing one instance under Fluid compute, cron
  delivery delay) is not reproduced; invocations here are fresh processes started 8 s before their cron time.
- One machine runs everything (the database, the pooler, the mock and up to about 13 Python processes). CPU
  contention can only make the lane look slower than it would be on separate instances; the receipt records the
  load average.
