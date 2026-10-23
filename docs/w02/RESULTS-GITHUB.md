# W-02 capacity: results on GitHub-hosted runners (evidence of record)

All runs here:

- **Tree under test:** `d80d6eaf678591b3818f384f6d9c9ed92c6dc474` (the W-02 head, with the same `src/` as 62f68c56). The
  baseline ran the RC1 tree `2a5a523d788eef67a5c7dbed609a98efa6650eef`.
- **Harness:** `22e3257e4362a8dcf82e30fd6a0c17010c4d25ec`.
- **Machine:** a standard ubuntu-24.04 GitHub-hosted runner, 4 vCPU and 16 GB, one fresh VM per scenario.
- **Database:** PostgreSQL 17 behind PgBouncer in transaction mode, pool 20, with 2 ms per database round trip added by
  the harness relay.
- **Coordinator:** the fixed-window coordinator of the W-02 head.

The coordinator pushed the requests (suffix `1023b`). The figures below were read from the artifacts and re-analysed
with this branch's analysis (`scripts/discord_lane_capacity_run.py analyze`). The analysis changes only the derived
lines; every measurement comes from the mock's own log and the run's database.

## Against the written standard (`docs/w02/capacity-standard.json`)

| Measure | S1 (5,000 at T) | S0-100 | S0-250 | Baseline (RC1, 10 min) |
|---|---|---|---|---|
| Lateness median ≤ 12 min | **FAIL** 17.19 | n/a | n/a | n/a |
| Lateness p95 ≤ 25 min | **FAIL** 36.79 | n/a | n/a | n/a |
| Lateness max ≤ 40 min | **FAIL** 40.73 | n/a | n/a | n/a |
| Duplicates (nonce, post id) = 0 | PASS | PASS | PASS | PASS |
| Creates after approval expiry = 0 | PASS | PASS | PASS | PASS |
| Requests above 25 in a trailing second = 0 | **FAIL** 856 (peak 29) | **FAIL** 2,117 (peak 33) | **FAIL** 5,345 (peak 32) | PASS (peak 6) |
| Bot requests above Discord's 50/s = 0 | PASS | PASS | PASS | PASS |
| Organic create 429s and global 429s = 0 | PASS | PASS | PASS | PASS |
| Invalid requests in 10 min ≤ 2,000 | PASS (0) | PASS (0) | PASS (0) | PASS (0) |
| Held or lost below 13,000 = 0 | PASS (5,000 of 5,000 verified) | n/a | n/a | n/a |
| Pooled connections ≤ 70% of the pool | PASS 0.60 | PASS 0.60 | PASS 0.65 | PASS 0.05 |
| Statement timeouts = 0 | PASS | PASS | PASS | PASS |
| Normal load: sent within 2 / 5 / 15 min ≥ 95 / 99 / 100% | n/a | PASS 100 / 100 / 100 | **FAIL** 27.3 / 59.0 / 95.5 | n/a |
| Drain, T to the last verified post (reported) | 40.82 min | | | |
| Requests per verified post (reported) | 7.85 | 7.49 | 7.43 | not measured (0 verified) |

Expected behaviour:

- in every run: no duplicates, no late sends, and isolation (0 misrouted creates);
- in S1, S0-100 and S0-250: clean workers (every invocation answered 200, none was killed, no egress was refused).

**All PASS**, except the baseline's own claim. The RC1 frozen worker created 21.9 posts per minute and verified 0 in
its 10 minutes, so 5,000 posts would take about 3.8 hours. The claim of 6 to 12 per minute that the check carried was
too low.

## What explains S1 (details and code references: `docs/w02/REQUEST-BUDGET.md` section 7)

- **Pacing.**
  - The lane sends from second 6 to second 51 of each minute: duty cycle 78%. The loop budget is 50 s and the runtime
    is built inside each cold invocation.
  - In those seconds it runs at 20.9 requests/s, 84% of 25.
  - Before the first read-back (T+24.6 min) a created post cost 6.749 requests.
  - Together these imply a median of 17.35 min, against 17.19 measured.
- **Requests.**
  - 7.850 per verified post: 7.000 essential, 0.653 repeated preflight (653 passes released before their create) and
    0.197 bot identity.
  - The grant check ran on the real path: one `GET /oauth2/@me` per preflight.
- **The tail is released posts.**
  - Releases: 503 workspaces had at least one preflight released before its create.
  - Requeue: a claim stamps `lastDispatchedAt`, so a released post goes behind its workspace's never-claimed posts, at
    12 to 14 minutes per round.
  - Lateness: posts of those workspaces have median 26.6, p95 39.8 and max 40.7 min, against 15.3 / 30.6 / 32.6 for
    the rest.
  - Every post later than 32.6 min was among them.
- **Read-back.**
  - Create to verified: median 18.15 min, p95 30.13.
  - Due to verified: median 35.6 min.
  - A workspace's read-backs come only after all its creates, one job per claim, round robin.
- **Ceiling.** The coordinator's own table shows 29 admissions in a trailing second and 28 in one calendar second.
  The application window is a 1-second window that restarts at the first request after it expires.

## Lock benchmark (profile `lockbench`)

Admissions per second of the shared coordinator alone (one reserve and one observe transaction per request), learned
routes:

| | 1 process | 4 | 12 | 24 |
|---|---|---|---|---|
| 0 ms round trip | 68.5 | 128.3 | 129.2 | 119.2 |
| 2 ms | 10.6 | 31.9 | 42.4 | 47.4 |
| 5 ms | 4.2 | 14.1 | 20.5 | 23.2 |
| 2 ms, 120 ms Discord answer between reserve and observe | | | 24.6 | 30.6 |
| 2 ms, the reviewed 25/s policy | | | 23.4 | 24.9 |

At 2 ms the application-row lock is the main latency contributor: reserve p50 153 ms and observe 122 ms at 12
processes, against 39 and 56 ms alone. It is not a hard ceiling below 25. At 5 ms it is: below 25/s even with 24
processes and no policy limit.

## Not yet in this file

- S2 and the faults profile (Fcrash and the others) were still running when this was written.
- The `s1levers` profile (S1, S1-lane58, S1-lane70, S1-warm) is prepared but not yet requested.
