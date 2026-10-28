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
processes and no policy limit. Production runs in Vercel iad1 against Supabase us-east-1, which are co-located, so
2 ms is the plausible case and 5 ms a stress. The real round trip has not been measured.

## S2: a workspace with 3,000 due posts (profile `s2`, 1023b)

Tree `d80d6eaf`, harness `22e3257e`, pool 20, 2 ms. The 1,999 small workspaces were all served by 17.18 min (drain 17.27
min); the hot workspace sent **0** of its 3,000 posts in 50 minutes.

| Measure | Measured |
|---|---|
| Hot workspace | 0 sent; 2,998 held at approval expiry, 2 uncertain with a sealed intent and no create at the mock |
| Small workspaces (at most 5 posts) | all sent by 17.18 min against the 15 min of the standard; 2,000 sent in total |
| Duplicates, creates after expiry, misroutes | 0, 0, 0 |
| Requests above 25 in a trailing second | 280 (peak 29; 27 in one calendar second) |
| Document of the hot workspace | 15.7 MB of JSON text (5.9 MB stored); a 1-post workspace is 14.5 KB |
| One read-modify-write of it | 2.7 to 3.0 s in the sandbox at load 30; the state UPDATE peaked at 4.57 s on the runner |
| Admissions at the end | 1 `sent`, 2 `sealed`, 52 `reserved`, 343 `blocked` |

The cause is lane defect D3 (`docs/w02/REQUEST-BUDGET.md` section 7.6): the create permit lived to the end of the current
application window, the seal and the second lease renewal each rewrite the whole document, and each took longer than any
window remainder. 134 attempts died before the seal and 2 after it. The other 11 loops idled while one leased job held
the workspace (`claimMisses` 3,158, `idleWaits` 2,516). The profile `s2sizes` (hot workspace of 100, 300 and 1,000
posts) measures where this design stops keeping up once the permit outlives the seal.

## The fault set (profile `faults`, 1023b)

All ten scenarios on tree `d80d6eaf`, harness `22e3257e`, pool 20, 2 ms. Nothing was duplicated or sent late and no
create reached another tenant's channel in any of them. Two harness defects showed in this round and are fixed:
Fdb ran with the matrix's pool 20 and 2 ms instead of its own 6 connections and 8 ms (1a46d43c pins them), and two of
Fcrash's six random kills landed between two loops and were dropped without a record (d0438ead moves them 20 s into the
minute and records a missed kill).

| Scenario | Result |
|---|---|
| F429 (1,000 posts) | 986 sent and verified. The 7 creates that got a 429 were held and never resent, as designed. No request reached the mock inside the embargo that was measured, and creates resumed 2.8 s after it ended. Expected behaviour 7 PASS, 1 FAIL: 7 posts that no 429 touched were unverified when the 12-minute limit ended the run. |
| F5xx (1,000 posts) | 14 creates hit (7 landed): none resent, all 14 `uncertain`; the other 986 verified. 6 `uncertain` and 2 `reserved` admissions left at the end. |
| Fcrash (5,000 posts) | 8 kills delivered of 10 planned (4 random, 4 during a held create; the 2 dropped random kills were not recorded then). 4,995 sent, 4,991 verified, 4 `uncertain`, 5 held at approval expiry; the drain completed. 4 admissions `sent` and never observed: each was its channel's first create on a still unknown route (capped at 1 per window), which locked the channel and held 5 sibling posts. Lateness 17.51 / 34.35 min (median / p95). |
| Fdb (1,500 posts; pool 20, 2 ms by the override bug) | 304 sent, 0 verified in 40 minutes. 689 + 119 lock timeouts in the coordinator's statements (808 `55P03`, 3 `57014` in the log). The run ended with exactly 25 `sent` admissions: every slot of the window held, so creates went 152, 101, 50 and 1 per minute, then 0 for 37 minutes, and 1,195 posts waited "Await Discord shared rate budget" (lane defects D1 and D2). |
| Fexpiry (3,000 posts) | 590 verified, 2,410 held when their approvals lapsed, none pending or failed. |
| Fstall (3,000 posts) | 0 creates during the 10-minute stall, all 3,000 verified, drain 23.7 min after the crons came back; lateness 19.84 / 30.76 / 33.61 min. |
| Fflip (2,000 posts) | 48 of 48 shard answers disabled while the flag was off, the minute worker claimed Discord 100 times, the lane posted 1,551 after it came back; all 2,000 verified. |
| Nmisroute, Ndup | Controls fired: 21 misrouted creates detected by the mock (21 planted), 8 double accepts counted by nonce and by post id (8 planted). |
| Nceiling (policy 100/s, information only) | 1,199 of 1,200 sent; 5,143 requests above 25 in a trailing second (peak 35); 0 bot requests above 50; 2.15 verified posts per second at 8.74 requests per post, about 18.8 requests per second: the same throughput as under the 25/s policy. |

## The lane-budget levers and the spread between runs (profile `s1levers`, 1023d)

Tree `d80d6eaf`, harness `d638bb6f`, pool 20, 2 ms. S1 four times, one lever each. The control is the unchanged S1.

| | Control | Loop budget 58 s | Loop budget 70 s | Warm invocations |
|---|---|---|---|---|
| Lateness median / p95 / max (min) | 13.79 / 27.26 / 32.57 | 14.43 / 30.55 / 34.14 | 15.77 / 35.21 / 37.75 | 14.52 / 30.62 / 34.55 |
| Drain, T to the last verified (min) | 32.66 | 34.23 | 37.84 | 34.64 |
| Plateau duty cycle | 0.82 | 0.93 | 0.99 | 0.89 |
| Plateau active-window rate (requests/s) | 23.1 | 20.8 | 18.6 | 21.1 |
| Plateau requests per created post | 6.32 | 6.61 | 7.14 | 6.52 |
| Busiest 60 s / 300 s (requests/s) | 19.5 / 19.2 | 19.9 / 19.5 | 19.5 / 19.0 | 19.1 / 18.9 |
| Requests above 25 in a trailing second (peak) | 6,741 (35) | 1,662 (31) | 764 (32) | 1,476 (30) |
| Machine load, one-minute peak; PostgreSQL CPU | 5.5; 505 s | 7.6; 776 s | 9.9; 810 s | 7.1; 482 s |

Every run: 5,000 of 5,000 verified, 0 duplicates, 0 creates after expiry, 0 429s.

## What these rounds say

- **The 4-vCPU hosted runner saturates at 16 to 19 requests per second whatever the policy or the duty cycle.** The
  busiest 300 s was 18.9 to 19.5 in all four S1 variants, and the information-only run with the policy at 100/s gave
  about 18.8. The 12 loops, the mock, PgBouncer, the relay and PostgreSQL share four cores, so the ceiling of 25 is not
  what limits the rate here. Do not tune against median lateness on this runner; judge by the correctness measures
  (duplicates, late sends, misroutes, the ceiling counts, held and lost posts, leaked admissions).
- **Run to run, the same code differs by about 3 minutes.** S1 on the same tree and the same runner type gave a median of
  17.19 min in 1023b and 13.79 in 1023d (p95 36.79 against 27.26, max 40.73 against 32.57). A lever has to move the
  median by more than that before one run shows it.
- **The lane-budget lever does not help.** A longer loop budget raised the duty cycle (0.82, 0.93, 0.99) and lowered the
  active-window rate (23.1, 20.8, 18.6 requests/s) and raised the requests per created post (6.32, 6.61, 7.14); the
  product stayed near 19 requests/s and the median did not improve (13.79, 14.43, 15.77). At 70 s up to 24 loops share
  four cores: load peaked at 9.9 and PostgreSQL used 810 s of CPU against 505 s. Warm invocations did not help either
  (14.52). The levers belong on a machine that is not the bottleneck; the requests per post (4.1) are what the code can
  still change.
- **The ceiling counts fall with the rate, not with a fix.** 6,741, 1,662, 764 and 1,476 requests above 25 in a trailing
  second come with sustained rates that are all near 19; the control's peak was 35.
- **Leaked admissions decide the fault runs.** Fdb ended with 25 `sent` admissions and sent nothing for 37 minutes;
  Fcrash's 4 killed creates locked 4 channels; F5xx left 6 `uncertain`. An age bound on unanswered admissions
  (`docs/w02/REQUEST-BUDGET.md` section 7.7) has to make them self-healing, and every receipt now states the open
  admissions by state and probes the budget after the run (launch gates).

