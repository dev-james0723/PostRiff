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


## The limiter head `3dac3ccf`: development measurement 1028

**A development measurement, not G5 evidence.** Every source change shifts the capacity-source digest, so the final evidence
needs the integrated SHA. Tree `3dac3ccfe9a793cc6a412b01d8de87dc17fc2b7e` (the head of `claude/discord-rc2-limiter-20261023`),
harness `ffdab63c66264e38074d687bf7b9b1f92de72cbd`, standard ubuntu-24.04 runners, pool 20, 2 ms. Requests
`claude/discord-capacity-run-devset-1028a` (run 40657396377: S1, S0-100, Fdb, Fcrash, F429) and
`claude/discord-capacity-run-s2sizes-1028b` (run 40657448334: S2-100, S2-300, S2-1000). The figures below were re-read
from the artifacts with the harness analysis of this branch (`analyze` on the downloaded directory), which adds lines the
runner's own receipt did not have (guard sizing, preflight passes). Local copies of the receipts:
`/tmp/claude-0/-home-user-PostRiff/3cb76cca-883c-52d5-850d-5dab5e917b4a/scratchpad/cap-1028/x-<scenario>/`.

### Against the standard and the earlier S1 rounds

| | S1 1023b | S1 1023d | **S1 1028 (limiter head)** |
|---|---|---|---|
| Lateness median / p95 / max (min), limits 12 / 25 / 40 | 17.19 / 36.79 / 40.73 | 13.79 / 27.26 / 32.57 | **19.77 / 37.87 / 43.52** |
| Drain, T to the last verified (min) | 40.82 | 32.66 | 43.61 |
| Duplicates, creates after expiry, misroutes, organic 429s | 0, 0, 0, 0 | 0, 0, 0, 0 | 0, 0, 0, 0 |
| Requests per verified post | 7.85 | 7.32 | 8.95 |
| Plateau duty cycle x active-window rate x requests per created post | 0.78 x 20.9 x 6.75 | 0.82 x 23.1 x 6.32 | 0.80 x 21.3 x 8.19 |
| Implied median from those three (min) | 17.35 | 14.03 | 20.05 |
| Busiest 10 s / 60 s / 300 s (requests/s) | 22.5 / n/a / n/a | 25.0 / 19.5 / 19.2 | 22.4 / 17.5 / 17.3 |
| Requests above 25 in a trailing second at the mock (peak) | 856 (29) | 6,741 (35) | 56 (28) |
| Peak in a calendar second at the mock; by the coordinator's sent_at (trailing / calendar) | 28; 29 / 28 | 31; 33 / 31 | 27; **25 / 25** |
| Create permits that died unused | not measured | not measured | 0 of 5,000 |
| Admissions left without an answer; budget probe after 3 s and 90 s | not measured | not measured | none; 25 of 25 and 25 of 25 |
| Lane releases (`rateDelayed`), steps | not measured | 20, 10,258 | 4,714, 15,021 |

The median is 6.0 minutes worse than 1023d and 2.6 worse than 1023b; the spread between those two rounds on the same code
was 3.4, so the gap to the better round is outside the spread and the gap to the worse one is inside it. The decomposition says why: the duty cycle and the active-window rate are those of the earlier
rounds, the **requests per created post rose from 6.3 to 8.2**, and the implied median (20.05) reproduces the measured one
(19.77). The extra requests are repeated preflight passes: 8,655 successful witness requests beyond one pass per post
(1.73 per post; 1023b 0.65, 1023d 0.17), 1.53 server reads per post.

| Other scenarios, same run | Result |
|---|---|
| S0-100 | All normal-load measures PASS (sent within 2 / 5 / 15 min 100 / 100 / 100%; lateness 0.32 / 0.62 / 0.87 min). 20 requests above 25 (7 wire jitter, 13 the mock's processing order, 0 coordinator; 1023b 2,117); 0 permits died; no open admissions. 866 of 2,866 passes released. |
| Fdb (pool 6, 8 ms, pinned) | 1,500 of 1,500 verified, no starvation, 0 above 25 (peak 19), 0 permits died. 98 admissions left without an answer (54 bot reads, 14 user reads, 30 creates, all older than 60 s) and the budget probe is still 25 of 25 at 3 s and at 90 s: the age bound works. Lock timeouts 210 (808 at pool 20), 1 statement timeout. Lateness 9.52 / 20.80 / 27.77 min. |
| Fcrash | 10 kills planned, 10 delivered (6 random, 4 during a create), 0 missed. 4,995 verified, 5 uncertain (4 killed creates that reached the mock, 1 sealed and never sent), none held (1023b: 5 held, 4 channels locked). 1 permit died after the seal (the kill). 6 admissions left without an answer, budget 25 of 25. 16 above 25. Lateness 17.63 / 33.89 min. |
| F429 | 986 of 1,000 sent and verified; 7 held by design after a create 429; 6 above 25 (1023b 255). 5 posts stay `scheduled` for 20 minutes after an injected route 429 on `GET /guilds/{id}` (see the open items). 0 permits died, no open admissions. |
| S2-100, S2-300, S2-1000 | See "S2 with a hot workspace" below. |

### Wire jitter and the guard

`sent_at` of every admission against its arrival at the mock (S1: 44,750 of 44,750 paired). Admission to arrival, p50 / p90 / p99 /
p99.9 / max: 51.2 / 64.6 / 169.1 / 285.7 / 364.0 ms; all but about 1 ms of it is inside the application (admission to the HTTP
call p50 50.3, p99.9 280.6 ms; call to arrival p50 0.8, p99.9 14.7 ms). The floor of about 40 to 50 ms is not jitter. A guard has
to cover the spread: for each request and the 26th after it in send order (windows at the ceiling, 41,780 of them), the later
one arrived under a second after the first in 54 windows (0.129%); the delay of the first minus the delay of the later one was
p99 38, p99.9 148, p99.99 193, max 214 ms, against a smallest slack of 103.7 ms (the 0.1 s guard in force). The same on F429
(0.088%, p99.9 145 ms) and S0-100 (0.106%, p99.9 159 ms). With the 0.1 s guard 0.09 to 0.13% of the windows at the ceiling were
violated at the mock; the median slack of those windows is 146 to 156 ms, more than the minimum. Had every window sat at the 0.1 s
minimum, the share would have been 0.30 to 0.43%; a guard of 0.15 s would give 0.09 to 0.14%, 0.2 s 0 to 0.014%, and 0.25 s none in
these runs (inference from the measured delays of S1, S0-100 and F429). The runner is CPU-saturated, which
inflates application-side variance, and the real network variance between Vercel and Discord is not modelled.

### Why S1 got slower: released posts and repeated passes

**What the receipts hold.** The mock's log gives every request with its time and workspace; `admissions.jsonl` gives every
admission (reserved, sent, answered); the database statistics give the coordinator's lock statements; the lane counters give
the releases. **A refused reservation leaves no row anywhere**, so the wait the coordinator quoted to it is in none of them. What
follows is measured where it says measured and inferred where it says inferred. The harness now records every reservation
attempt with its outcome and quoted wait (`attempts.jsonl`, written by the invocation wrapper), so the next hosted run answers the rest.

**(a) Reservation attempts, outcomes and waits.**

1. *Attempts and refusals, per run (inferred from the database statements).* One reservation attempt runs one lock statement
   on the scope rows (`_locked`, the `scope_lock` statement without a `guarded` part); an observation runs the same statement
   only when it cannot share the lock, which is a create's. So attempts are about those statements minus the creates; a cross-check
   from the route-bucket lookup (once per attempt and once per observation) gives 5 to 7 thousand more in S1, so the refused count
   is between 41 and 48 thousand.

| Run | Admissions | Reservation attempts | Refused (estimate) | Refused per admission | Refused per created post | Releases (`rateDelayed`) |
|---|---|---|---|---|---|---|
| S1 | 44,750 | 87,793 | 43,043 (41 to 48 thousand) | 0.96 | 8.6 | 4,714 |
| S0-100 | 16,584 | 29,467 | 12,883 | 0.78 | 6.4 | 1,052 |
| F429 | 8,743 | 16,897 | 8,154 | 0.93 | 8.2 | 833 |
| S2-100 | 39,162 | 62,624 | 23,462 | 0.60 | 4.7 | 1,608 |
| Fcrash | 39,279 | 63,089 | 23,810 | 0.61 | 4.8 | 1,630 |
| Fdb (pool 6, 8 ms) | 11,442 | 12,412 | 970 | 0.08 | 0.6 | 142 |

   About half of all reservation attempts in S1 are refused (43,043 of 87,793 = 49%). The provider gives a read three attempts
   inside one second (`read_attempts` 3, a one-second wait deadline); if every attempt were refused with probability p
   independently, the 12% of reads that end in a release (below) would mean p near 0.5, which agrees.

2. *Where the releases fall, by the request that was refused (measured from the mock log; the first row inferred).* A pass
   starts at the grant check and goes on to the server read, two member reads and the channel list, then the create permit. The
   last request a released pass completed names the next one, which was refused:

| Request refused (credential) | Admitted in the run | Posts released at it | Share of attempts at this step that ended in a release | Wait from the previous answer to the admission, p50 / p90 / p99 (share over 100 ms / over 1 s) |
|---|---|---|---|---|
| grant check (user) | 8,730 | about 984 (releases whose pass never reached the mock: 4,714 - 3,730) | about 10% | n/a (first request of a claim) |
| server read (bot) | 7,652 | 1,078 | 12% | 174 / 381 / 547 ms (95% / 0%) |
| first member read (bot) | 6,468 | 1,184 | 15% | 156 / 406 / 1,374 ms (68% / 3.4%) |
| second member read (bot) | 5,780 | 688 | 11% | 122 / 316 / 459 ms (61% / 0%) |
| channel list (bot) | 5,025 | 755 | 13% | 131 / 343 / 524 ms (64% / 0%) |
| create permit (bot) | 5,000 | 25 | 0.5% | 224 / 595 / 964 ms (98% / 0.6%) |

   So 99.3% of the visible releases are a refused witness read, not the create. The wait column is the time between the answer
   to the previous request being observed and this request's admission: it holds every refused attempt, every sleep and the
   reservation's own lock wait, so it is the cost of getting a slot, not the quoted wait. S0-100 shows the same medians
   (127 to 207 ms), so most of it is the cost of an admission at 2 ms per round trip with twelve loops queueing on the
   application row, not only refusals.

3. *The quoted wait.* Not recorded. What bounds it: after a refusal the lane releases the post with a cooldown equal to the wait
   that was quoted (`release_unsent`, `job['nextAt'] = now + retry_after`), so the time from the last answer of a released pass
   to the next pass of the same workspace is that wait plus the claim latency: p10 0.72 s, p50 0.92 s for the 87% of re-claims
   that take under 2 s. The quotes that release a read are the long ones: the provider (`social_connectors.py`, the read
   loop) raises `ReadAdmissionDelayed` as soon as a quoted wait does not fit in what is left of its one-second deadline, so a
   post is released at a quote of about 0.7 s or more and a shorter quote is slept through. A quote that long means the window's
   sends are bunched into the last few hundred milliseconds (the loops retry at the same instant and are admitted in waves).

**(b) Released posts: how often the whole pass repeats, and the sequences.**

| S1 | |
|---|---|
| Passes / created posts / released passes | 8,730 / 5,000 / 3,730 (43% of passes; 0 open at the end) |
| Posts by number of passes | 1: 2,882; 2: 1,214; 3: 508; 4: 208; 5: 117; 6: 41; 7: 17; 8: 7; 9: 4; 10: 1; 12: 1 (mean 1.746) |
| Re-claim of the same post after a release, p10 / p50 / p90 / p99 / max | 0.72 / 0.92 / 124 / 1,016 / 1,375 s; 87% within 2 s |
| Release by second of the minute (5 s bins, seconds 5 to 50) | 385 to 429 per bin: flat, not a burst at the start of the minute |
| Releases per minute after T | 84 to 139 until minute 28, then falling to 4 to 11 by minute 38 |
| Application window (25 sends within 1.1 s) over the second after a release | full at some instant 3,224 (86%), never full 500 (13%, maximum 20 to 24), full throughout 6 |

Typical sequences (S1, seconds after T; the sends column is the application window's occupancy at the moment of the admission,
the wait column the time since the previous answer was observed):

**one quick release: workspace 0**

| t after T (s) | request | shard | wait after the previous answer (ms) | sends in the last 1.1 s at admission | note |
|---|---|---|---|---|---|
| 193.301 | grant check (user) | lane0 |  | 23 | status 200 |
| 193.984 | server read | lane0 | 409 | 25 | status 200 |
| 194.539 | member read | lane0 | 321 | 22 | status 200 |
| 194.600 | **released** after grant+guild+member | | | 24 / 25 / 23 / 24 / 23 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 0.80 s later |
| 195.403 | grant check (user) | lane2 |  | 25 | status 200 |
| 195.808 | server read | lane2 | 184 | 22 | status 200 |
| 196.293 | member read | lane2 | 289 | 24 | status 200 |
| 196.663 | member read | lane2 | 179 | 23 | status 200 |
| 197.052 | channel list | lane2 | 120 | 24 | status 200 |
| 198.289 | CREATE | lane2 | 784 | 24 | status 200 |

**several releases in a row: workspace 7**

| t after T (s) | request | shard | wait after the previous answer (ms) | sends in the last 1.1 s at admission | note |
|---|---|---|---|---|---|
| 334.594 | grant check (user) | lane11 |  | 25 | status 200 |
| 334.716 | **released** after grant | | | 25 / 23 / 22 / 25 / 25 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 0.70 s later |
| 335.414 | grant check (user) | lane11 |  | 25 | status 200 |
| 335.497 | **released** after grant | | | 25 / 25 / 24 / 23 / 23 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 0.85 s later |
| 336.346 | grant check (user) | lane11 |  | 24 | status 200 |
| 336.448 | **released** after grant | | | 24 / 22 / 24 / 25 / 25 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 0.89 s later |
| 337.337 | grant check (user) | lane0 |  | 24 | status 200 |
| 337.699 | server read | lane0 | 160 | 24 | status 200 |
| 337.807 | **released** after grant+guild | | | 23 / 25 / 23 / 23 / 24 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 884.98 s later |
| 1222.787 | grant check (user) | lane8 |  | 25 | status 200 |
| 1223.165 | server read | lane8 | 147 | 25 | status 200 |
| 1223.469 | member read | lane8 | 35 | 23 | status 200 |
| 1223.978 | member read | lane8 | 238 | 24 | status 200 |
| 1224.271 | channel list | lane8 | 127 | 25 | status 200 |
| 1224.861 | CREATE | lane8 | 149 | 21 | status 200 |

**a long wait for the re-claim: workspace 7**

| t after T (s) | request | shard | wait after the previous answer (ms) | sends in the last 1.1 s at admission | note |
|---|---|---|---|---|---|
| 2312.182 | grant check (user) | lane1 |  | 22 | status 200 |
| 2312.576 | server read | lane1 | 120 | 23 | status 200 |
| 2313.202 | member read | lane1 | 337 | 24 | status 200 |
| 2313.490 | member read | lane1 | 65 | 25 | status 200 |
| 2313.600 | **released** after grant+guild+member+member | | | 24 / 24 / 24 / 23 / 23 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 283.53 s later |
| 2597.130 | grant check (user) | lane8 |  | 24 | status 200 |
| 2597.574 | server read | lane8 | 213 | 25 | status 200 |
| 2598.122 | member read | lane8 | 301 | 24 | status 200 |
| 2598.546 | member read | lane8 | 198 | 25 | status 200 |
| 2598.894 | channel list | lane8 | 70 | 24 | status 200 |
| 2599.604 | CREATE | lane8 | 272 | 24 | status 200 |

**released at the create: workspace 34**

| t after T (s) | request | shard | wait after the previous answer (ms) | sends in the last 1.1 s at admission | note |
|---|---|---|---|---|---|
| 2107.570 | grant check (user) | lane2 |  | 24 | status 200 |
| 2107.956 | server read | lane2 | 195 | 23 | status 200 |
| 2108.042 | **released** after grant+guild | | | 23 / 24 / 23 / 25 / 25 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 0.78 s later |
| 2108.825 | grant check (user) | lane2 |  | 25 | status 200 |
| 2109.168 | server read | lane2 | 105 | 24 | status 200 |
| 2109.263 | **released** after grant+guild | | | 24 / 25 / 24 / 24 / 25 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 1.07 s later |
| 2110.330 | grant check (user) | lane3 |  | 25 | status 200 |
| 2110.776 | server read | lane3 | 151 | 23 | status 200 |
| 2110.879 | **released** after grant+guild | | | 24 / 23 / 24 / 22 / 23 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 0.64 s later |
| 2111.519 | grant check (user) | lane3 |  | 25 | status 200 |
| 2111.884 | server read | lane3 | 100 | 25 | status 200 |
| 2112.461 | member read | lane3 | 341 | 25 | status 200 |
| 2112.881 | member read | lane3 | 167 | 24 | status 200 |
| 2113.595 | channel list | lane3 | 398 | 23 | status 200 |
| 2113.683 | **released** after grant+guild+member+member+channels | | | 22 / 24 / 24 / 25 / 23 at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass 447.67 s later |
| 2561.349 | grant check (user) | lane9 |  | 25 | status 200 |
| 2561.672 | server read | lane9 | 96 | 23 | status 200 |
| 2562.234 | member read | lane9 | 299 | 24 | status 200 |
| 2562.475 | member read | lane9 | 79 | 25 | status 200 |
| 2562.884 | channel list | lane9 | 235 | 23 | status 200 |
| 2563.387 | CREATE | lane9 | 137 | 24 | status 200 |

**Reading (inference).**

- The application window sits at 22 to 25 of 25 slots throughout the active seconds. A request needs a slot to free, and
  the slot goes to whichever of the twelve loops asks first; with three attempts inside one second, a read that loses twice or
  three times is released (12% of read steps), and the post starts again from the grant check at its next claim.
- A release costs the reads already admitted (1.73 extra preflight requests per post on average) and, in 13% of the cases, a
  wait behind the round-robin: p90 124 s, p99 1,016 s, longest 1,375 s. That tail is the p95 and maximum lateness. Of the
  3,245 re-claims within 2 s, 1,784 (55%) went on to create and 1,461 (45%) were released again, up to 12 passes for one
  post; of the 485 slower ones, 334 created and 151 were released again.
- The same shard re-claims the same workspace three times in a row (workspace 7 above) at 0.70, 0.85 and 0.89 s, each time
  released after the grant check: the cooldown matches the quote but the quote is as long as the slot's remaining life, so the
  retry meets a full window again.
- Releases are not a start-of-minute burst: they run flat from second 5 to second 50, at about 400 per five-second bin, and
  fall only when the backlog drains.
- The first member read waits over one second in 3.4% of S1's steps and 7.1% of S0-100's, against 0% for the other reads: a
  different cap, probably the one-per-second admission of a route or major the coordinator has not learned yet (the discovery
  scope); the attempt log will show the scope.

### Open items found by these runs

- **F429, five posts never retried their server read.** Workspaces 259, 298, 305, 301 and 558: the injected route 429 on
  `GET /guilds/{id}` (Retry-After 2 s, bucket header `injected-guilds-{id}`, limit 5, remaining 0, reset 2 s) was answered once.
  For the next 1,000 seconds the lane asks only for the grant check every 300 s (+466 s, +785 s, +1,085 s after T) and sends no
  request to the mock; the post stays `scheduled` with "Await Discord shared rate budget; no POST occurred". 1023b also ended
  F429 with seven posts `scheduled` that way (its mock did not attribute injected answers to a server, so the workspaces
  cannot be matched; the count is the same, five route-429 victims and two ban-page victims), so the limiter's stuck-route fix does
  not cover this case. Reproduce with
  `scripts/discord_lane_capacity_run.py run --scenario F429`.
  **Resolved in 1028c:** the mock's injected bucket id carried the template's braces, which is not a valid bucket id, and the coordinator (by
  reviewed design) holds such a route as a manual hold that only an operator releases. It was a fault of the harness, not of the limiter; with
  a valid id all five posts verify (cf9aaecd).
- **First member read, discovery or learned-route waits** (above).

<!-- s2-sizes -->

## S2 with a hot workspace of 100, 300 and 1,000 posts (profile `s2sizes`, 1028b, limiter head `3dac3ccf`)

The same 5,000 posts: the hot workspace holds N, the other 5,000 - N are spread over 1,999 workspaces. Pool 20, 2 ms, judged as S2 (the standard is unchanged; the proposed measures are REPORTED lines only).

| | S2-100 | S2-300 | S2-1000 |
|---|---|---|---|
| Hot workspace sent | 100 of 100 | 292 of 300 (the rest held when the approvals lapsed) | 236 of 1000 (the rest held when the approvals lapsed) |
| Hot workspace lateness median / p95 / max (min) | 41.27 / 43.39 / 43.57 | 47.76 / 58.86 / never | never / never / never |
| Hot workspace first / last create (min after T) | 13.74 / 43.57 | 3.32 / 59.83 | 13.39 / 59.90 |
| Hot create rate from T to its last create (per second; share of the physical 1 per second) | 0.038 (4%) | 0.078 (8%) | 0.049 (5%) |
| Hot create rate while it was the only workspace with work | median 21 per minute (range 13 to 23) over 5 minutes | median 15 per minute (range 8 to 19) over 19 minutes | median 12 per minute (range 8 to 12) over 18 minutes |
| Document as seeded | 586,649 bytes (212,689 stored); idle read-modify-write 0.044 / 0.041 / 0.042 s | 1,625,357 bytes (606,967 stored); idle read-modify-write 0.105 / 0.104 / 0.103 s | 5,260,348 bytes (1,986,815 stored); idle read-modify-write 0.259 / 0.249 / 0.248 s |
| Document at the end of the run | 880,285 bytes (371,917 stored); idle read-modify-write 0.068 / 0.068 / 0.076 s | 2,512,875 bytes (1,085,831 stored); idle read-modify-write 0.159 / 0.158 / 0.157 s | 6,084,825 bytes (2,420,429 stored); idle read-modify-write 0.291 / 0.294 / 0.289 s |
| The application's UPDATE of a workspace document | mean 4.6 ms, max 304 ms, 28,291 calls | mean 10.6 ms, max 1025 ms, 30,537 calls | mean 12.8 ms, max 1618 ms, 28,686 calls |
| Small workspaces (at most 5 posts): all sent by (min); their lateness median / p95 / max (min) | 37.35; 17.18 / 33.27 / 37.35 | 38.61; 17.40 / 33.45 / 38.61 | 35.13; 15.66 / 30.15 / 35.13 |
| Standard lateness lines for all posts, median / p95 / max (min) | 17.45 / 33.83 / 43.57 | 18.46 / 41.30 / never | 19.67 / never / never |
| Drain, T to the last verified (min) | 44.67 | 62.48 | 80.52 |
| Requests above 25 in a trailing second (peak by send time) | 10 (25) | 41 (25) | 97 (25) |
| Duplicates, misroutes; permits died unused; open admissions | 0, 0; 0; none | 0, 0; 0; none | 0, 0; 4; none |

**Reading (inference).**

- The 1023b failure (the 3,000-post workspace sent nothing; the permit died before the seal) is gone at these sizes: the hot workspace sends, and no permit died at 100 and 300 posts (4 of 4,240 did at 1,000, after the seal, while a 6 MB document is rewritten).
- The document does not bind at 100 to 300 posts but starts to at 1,000. One read-modify-write of it costs 0.04 to 0.16 s with nothing else running at 100 and 300 posts and 0.25 to 0.29 s at 1,000 (5.3 to 6.1 MB of JSON), and the application's own UPDATE of a workspace document averages 5, 11 and 13 ms with a worst case of 0.3, 1.0 and 1.6 s under load, against 2 to 3 ms and 40 ms for a one-post workspace. At 1,000 posts the hot workspace's rate alone is 12 per minute, one post every 5 s, below the 15 to 21 of the smaller ones, and 4 of its create permits died after the seal.
- What binds is the serial service of one workspace. A workspace is served one job per claim and one leased job at a time, and claims go round robin over the workspaces, so the hot workspace gets about one post per round while 2,000 workspaces have work (about one post every ten minutes) and only after the small workspaces are done (minute 38 to 39) does it get a loop to itself: a median of 21 (S2-100), 15 (S2-300) and 12 (S2-1000) posts per minute, 0.2 to 0.35 per second, one step of about 3 to 5 s per post while the other eleven loops idle. That is 20 to 35% of the physical one per second per channel, so the proposed target of 80% is not met at any size, and a workspace of 300 posts needs about 20 minutes after the others are done: 8 of its 300 lapsed at 60 minutes, and of 1,000 posts only 236 were sent in the hour (764 held when their approvals lapsed), against the 16.7 minutes the one create per second of its channel would allow.
- The small workspaces are not slowed by the hot one beyond the S1 effect (their lateness median 15.7 to 17.4 min against 19.8 in S1), but every workspace of at most five posts finished only at 35 to 39 minutes against the standard's 15.
<!-- /s2-sizes -->

<!-- booking-1028c -->

## The limiter head `02fd679b` (booking, P2): development measurement 1028c

**A development measurement, not G5 evidence.** Tree `02fd679b4a70ec501b4f68a6e3f6d30d6a8330ac` (`claude/discord-rc2-limiter-20261023`:
booking in `reserve` and `reserve_read`, the lane books around its preflight reads and the create permit, N-1, retention B3), standard
ubuntu-24.04 runners, PgBouncer pool 20. Requests: `claude/discord-capacity-run-devset-1028c` (run 40699076272, harness `cba323ea`:
S1, S0-100, Fdb, Fcrash, F429), `claude/discord-capacity-run-fdb-1028d` (run 40701987691, harness `36675db7`: Fdb again, see below) and
`claude/discord-capacity-run-s1lane56-1028e` (run 40705094663, harness `3bbc344c`). Local copies of the receipts:
`/tmp/claude-0/-home-user-PostRiff/3cb76cca-883c-52d5-850d-5dab5e917b4a/scratchpad/cap-1028c/x-<scenario>/`. The limiter has since fixed
two things this run found (the read-back of an ordinary post was not booked: `72ab8886`; migration 142's rollback file broke
`postriff_migrate`: `8c1841bd`); **the next S1 is to be taken on its final head**.

**What this harness assumes, plainly.** The 2 ms database round trip (a relay in front of PgBouncer adds it to every statement), the
50 to 150 ms Discord latency (uniform, mean 100 ms), one 4-vCPU GitHub-hosted runner that also runs PostgreSQL, PgBouncer, the relay,
the mock Discord and all twelve loops, and cold Python processes started every minute, are assumptions of the harness, not measurements
of Vercel, Supabase or Discord. The runner is close to CPU-saturated while the lane is active (load average up to 6.9 on 4 vCPUs). The
sensitivity to the first two is worked out below from the receipts and is to be measured at 5 and 10 ms on the final head (profile
`release`), so that G5 does not rest on a favourable guess.

### S1 against the standard and the earlier rounds

| | S1 1023d | S1 1028a (`3dac3ccf`) | **S1 1028c (`02fd679b`)** | Limiter's prediction |
|---|---|---|---|---|
| Lateness median / p95 / max (min), limits 12 / 25 / 40 | 13.79 / 27.26 / 32.57 | 19.77 / 37.87 / 43.52 | **15.66 / 30.55 / 32.37** (median and p95 FAIL, max PASS) | median about 16 |
| Drain, T to the last verified (min); last create | 32.66 | 43.61 | 36.76; T+32.37 | |
| Time to verified, median / p95 (min); first read-back (min after T) | 29.78 / 32.34; 21.4 | 40.12 / 43.18; 29.3 | 34.24 / 36.56; 25.2 | |
| Duplicates, creates after expiry, misroutes, organic 429s | 0, 0, 0, 0 | 0, 0, 0, 0 | 0, 0, 0, 0 | |
| Posts a minute on the plateau (minutes 3 to 5) | not recorded | 132, 131, 119 | 159, 160, 159 (159 a minute for 24 minutes) | 150 to 158 |
| Requests per verified post; per created post on the plateau | 7.32; 6.32 | 8.95; 8.19 | 7.18; 6.16 | 7.0 |
| Plateau duty cycle x active-window rate x requests per created post | 0.82 x 23.1 x 6.32 | 0.80 x 21.3 x 8.19 | 0.78 x 20.7 x 6.16 | |
| Implied median from those three (min) | 14.03 | 20.05 | 16.00 (measured 15.66) | |
| Busiest 10 s / 60 s / 300 s (requests a second) | 25.0 / 19.5 / 19.2 | 22.4 / 17.5 / 17.3 | 22.0 / 16.7 / 16.5 | |
| Requests above 25 in a trailing second at the mock (peak) | 6,741 (35) | 56 (28) | **7 (26)**: coordinator 0, wire jitter 2, the mock's processing order 5 | |
| Peak by the coordinator's wire time (`sent_at`), trailing / calendar second | not recorded | 25 / 25 | **25 / 25** (by reservation instant 31 / 30: a booked read is stored at its slot) | at most 25 |
| Create permits that died unused; admissions left unanswered; budget probe at 3 s and 90 s | not recorded | 0 of 5,000; none; 25 of 25 and 25 of 25 | 0 of 5,000; none; 25 of 25 and 25 of 25 | |
| Lane releases (`rateDelayed`), permitWaits, rateWaits | 20, 1,563, 2,247 | 4,714, 4,864, 7,235 | **0, 0, 0** | 0 |
| Lane steps; `positionsKept`; preflight passes a post | 10,258; none; not recorded | 15,021; 4,305; 1.746 | 10,177; 0; 1.000 | passes 1.0 |
| `bookedWaits`, `bookedSeconds` | n/a | n/a | 26,829 (5.37 a post), 4,504 s (mean 0.168 s a booking, 0.90 s a post) | |
| Reservation lock statements a created post, exclusive form (mean time) | not recorded | 18.6 (47.3 ms) | **8.85 (34.7 ms)** | 7.5 to 8 |
| Shared lock form a created post (mean time) | not recorded | 7.55 (23.8 ms) | 5.78 (15.1 ms) | |
| Witness age at the create, oldest witness read to the create at the mock, p50 / p90 / max (s) | not recorded | 2.34 / 2.89 / 4.58 | 2.72 / 3.02 / 4.33 | 1.3 to 2.3 (simulated) |
| Wire jitter, `sent_at` to arrival at the mock, p50 / p99 / p99.9 / max (ms) | not recorded | 51 / 169 / 286 / 364 | 76 / 236 / 444 / 546 | |
| Guard sizing: windows at the ceiling; the 26th arrived under a second after the first | not recorded | 41,780; 54 (0.129%) | 30,080; 11 (0.037%) | |

The median is 4.1 minutes better than on `3dac3ccf` and the limiter's model (about 16) was right to a quarter of a minute; the
maximum now passes. The standard's median (12) and p95 (25) still fail by 3.7 and 5.6 minutes. The decomposition says why the gain is what it
is: the duty cycle and the active-window rate did not move (0.78 x 20.7), the whole gain is the requests per created post (8.19 to 6.16) and
the end of the releases (4,714 to 0) and of the repeated passes (1.746 to 1.000 a post).

**Lock statements.** Counted from `pg_stat_statements` by statement text (the `scope_lock` exclusive and shared forms): 44,263 and 28,889
calls. The 18.6 of 1028a is the exclusive form (92,793 calls). The limiter's 7.5 to 8 is not reached: 8.85, of which about 0.27 are the
1,371 refused attempts of the unbooked read-backs. The mean time of the exclusive form is lower (34.7 against 47.3 ms) but it is still the
heaviest statement: 1,537 s of the run's 2,429 s of server time (63%), the shared form 435 s (18%).

### The other scenarios of the same run

| | S0-100 | Fdb | Fcrash | F429 |
|---|---|---|---|---|
| Result | all normal-load measures PASS; lateness 0.29 / 0.53 / 0.67 min (1028a 0.32 / 0.62 / 0.87) | 1,500 of 1,500 verified, no starvation; lateness 9.62 / 21.21 / 27.87 min (1028a 9.52 / 20.80 / 27.77) | 10 kills planned, 10 delivered (6 random, 4 during a create), 0 missed; 4,994 verified, 6 uncertain (kills hit sealed sends; 1028a 5), none held; lateness 15.83 / 30.69 min | 992 of 1,000 verified; 6 held by design after a create 429; 2 waiting behind the two ban pages; **the five posts that stayed scheduled in 1028a all verify** |
| Requests above 25 at the mock (peak); 1028a | 15 (27); 20 (26): wire jitter 8, mock order 7, coordinator 0 | 0 (19); 0 (19) | 8 (26); 16 (27): wire jitter 2, mock order 6, coordinator 0 | 0 (25); 6 (27) |
| Peak by the coordinator's wire time (`sent_at`), trailing second | 25 | 18 | 25 | 25 |
| Releases, permitWaits, rateWaits, bookedWaits | 0, 0, 0, 9,948 (1028a 1,052, 1,399, 1,394) | 145, 0, 0, 0 (1028a 142, 0, 0) | 0, 0, 0, 26,976 (1028a 1,630, 2,925, 2,925) | 20, 0, 14, 5,830 (1028a 833, 890, 1,051) |
| Requests per verified post; passes a post | 7.25; 1.000 (1028a 8.29; 1.43) | 7.63; 1.076 (1028a 7.63; 1.078) | 7.19; 1.001 (1028a 7.86; 1.263) | 7.29; 1.016 (1028a 8.87; 1.647) |
| Permits died unused; admissions left unanswered | 0; none | 0; 91, all older than 60 s (1028a 98), budget probe 25 of 25 at 3 s and 90 s | 2 (1 before the seal, 1 after: the kills); 8 (2 booked reads killed during their wait that never left, 1 read and 5 creates that reached the mock with no answer observed), budget probe 25 of 25 | 0; none |
| Lock statements a post, exclusive / shared (mean ms) | 9.38 / 5.25 (36.6 / 13.3) | 9.28 / 5.92 (86.6 / 50.0) | 8.88 / 5.78 (32.5 / 13.8) | 9.90 / 5.27 (21.4 / 6.3) |

- **Fdb has no booking to show** (`bookedWaits` 0): at 11.5 requests a second, with a 6-connection pool and 8 ms round trips, the window never fills. Its
  result is the result of `3dac3ccf`: the database is the limit, not the window. The 145 releases are lock timeouts (the attempt log now holds
  the class and SQLSTATE of every error: `LockNotAvailable` 55P03, 97 on reads and 9 on reservations; the server log counts 197 lock timeouts and 1 statement timeout).
- **Fdb was lost once.** In the devset run (1028c) one of the four seeding processes got `RateCoordinatorUnavailable` from its first `GET /oauth2/@me`
  70 s into connecting the 1,000 workspaces and the run ended before anything was measured. The coordinator turns every failure inside its
  transaction into that error and hides the cause (`raise ... from None`). A local seeding check of Fdb on the same tree passed, and the re-run
  (1028d, one-scenario profile `fdb`) seeded without a single retry, so the cause is **not known**; seeding now tries a GET again up to five times and counts
  each with the class and SQLSTATE of the hidden failure (`seed-N.out`), and the attempt log records the same for every error of the run.
- **F429 now ends as designed.** The injected route 429 had carried `x-ratelimit-bucket: injected-guilds-{id}`, which is not a bucket id (the
  coordinator accepts `[A-Za-z0-9_-]{1,128}`), and the coordinator holds a route whose 429 names an invalid bucket as a manual hold that only an operator
  releases. The mock's id is now `injected-guilds-id` (cf9aaecd). Workspaces 184, 392, 631, 909 and 988 had their server read answered with the 429 and
  all five posts verified; the only manual holds left are the two ban-page routes, which are by design.

### Booking in the receipts

- **Horizon.** Reads lying ahead of the clock (a wire time not yet reached) when a read was reserved, p50 / p90 / p99 / max: S1 1 / 5 / 7 / 10, S0-100 1 / 5 / 7 / 10
  (a full horizon at 25 a second holds about 21). The health payload agrees: `horizonSeconds` p50 0, p90 0.161, max 0.225 of 1.0; `aheadNow` 0 / 3 / 5. **The booked
  horizon was never full.** 70.7% of S1's admitted reads were booked, their wait p50 / p90 / p99 / max 0.161 / 0.279 / 0.358 / 0.428 s.
- **Where the time goes.** 26,826 booked calls in the attempt log (22,416 reads, 4,410 create reservations), planned wait p50 0.166 s, slept in the call p50 0.172 s (the wait and the gate after it).
  Per call kind (share booked): grant check 79%, server read 84%, member reads 93%, channel list 91%, create reserve 88%, bot identity 50%; **read-back 0%**.
- **`coordinator.guards.policy remaining` under booking.** Q19 and AS-BUILT say it "stays high and falls to 0 only when the horizon is full". In S1 it was 0 in 21 of the 35 busy
  readings, with `resetSeconds` 0.0 in all of them and the horizon empty or shallow (never above 0.225 s): `left` is the free slots among the wires at or before now, so it is 0
  whenever the last 1.1 s holds 24 sent wires, which a saturated lane does all the time, while a booking is still possible at once. An alert that reads `remaining == 0` as
  spent would fire in 60% of the busy minutes; `horizonSeconds` near `bookAheadSeconds` is the full-horizon signal. (Told to the limiter.)

### The read-back of an ordinary post was not booked (found by this run, fixed at 72ab8886)

In F429 and S1 not one of the read-backs (`GET /channels/{id}/messages/{id}`) carried `book_ahead`: S1 6,371 attempts for 5,000 read-backs, 1,371 refused (21.5%, quoted wait p50 41 ms, max 360 ms),
562 needed two attempts, 160 three, 163 gave up after three; F429 1,559 attempts for 992, 567 refused (36%), 27 gave up. The bot identity reads inside the same step were unbooked too (49 of 202 in F429).
Cause: the worker reconciles an ordinary Discord post with `social.reconcile`, `PacedSocial` wrapped only `reconcile_discord` (a reply's read-back), and `HostedSocial.reconcile` calls its own
`reconcile_discord`. At saturation a caller that does not book can use roughly the one slot the booking leaves (about 0.9 a second) against about 2.5 read-backs a second in S1, so on this head the read-backs
poll against the bookings; the figures above (time to verified 34.2 min) under-state booking. The limiter's fix puts `reconcile` inside `booking()`; it has to be measured.

### One request cycle of a lane loop (arithmetic from the receipts of S1 1028c; no new run)

Twelve loops at 20.7 requests a second in the active window is 0.58 s per request per loop. On the whole-run handler-time basis (all lane handler seconds
over all requests the mock saw: 23,039 s over 35,889) it is 0.642 s. Per request:

| | seconds per request | share | source |
|---|---|---|---|
| (a) mock Discord latency | 0.100 | 16% | the mock's own applied latency, mean over the run (uniform 50 to 150 ms: an assumption) |
| (b) coordinator and other database time | 0.157 | 24% | every statement after seeding: 44.6 a request; server execution 0.068 s (the two lock statements 0.055) plus 44.6 round trips of 2 ms = 0.089 s |
| (c) booked sleep | 0.128 | 20% | slept inside `reserve` and `reserve_read` (attempt log; the lane counter says 4,504 s, 0.125 s) |
| (d) Python and the runner | 0.257 | 40% | the rest: the loop's own CPU 0.096 s (3,442 CPU-s), waiting for a CPU 0.161 s |
| cycle | 0.642 | | |

The coordinator's own calls without the sleep take 0.086 s per request (reservations) and 0.013 s (consumes); the observations after each answer are in (b) but not logged separately.
CPU: lane processes 4,089 CPU-s, PostgreSQL 669, the latency relay 502, the mock 48: 5,308 of the 9,685 CPU-s four vCPUs give in 2,421 s (55% of the run, about 0.15 CPU-s per request, so
the runner's own limit is about 27 requests a second at 100% busy and the lane reaches 20.7 in its active window).

Closed-network arithmetic with N loops, a delay of Z = (a) + (b) + (d) = 0.513 s per request and one window that serves a slot every 45.8 ms (24 slots in 1.1 s, 21.8 a second); M/M/1//N, the same
for a measured 18.7 a second on the handler basis (the model says 18.2):

| | requests a second (handler basis) | change |
|---|---|---|
| 12 loops as measured | 18.7 (model 18.2) | |
| no sleep at all, (c) = 0 | 23.4 | +25%, above the window's 21.8 |
| guard 0.05 s (a slot every 43.8 ms, 22.9 a second) | 18.6 | +2% |
| a separate bearer budget (the grant check, 1 of 7.18 requests, leaves the window) | 19.3 | +6% |
| both | 19.6 | +8% |
| 14 loops, same window | 19.8 | +9% |
| 16 loops | 20.9 | +15% |
| 24 loops | 21.8 (the window) | +17% |
| database round trip 5 ms instead of 2 (+0.134 s a request) | 15.7 | -14% |
| database round trip 10 ms | 12.5 | -31% |
| Discord latency 150 ms instead of 100 | 17.2 | -5% |
| Discord latency 250 ms | 15.5 | -15% |

Reading (inference). **At twelve loops the loops and the window limit together, and the runner's CPU is a third limit.** The 12 loops could offer at most 23.4 requests a second even
with no sleeping, 7% above the window's 21.8; the window is busy 83% of the time (18.2 of 21.8) and a request waits 0.10 to 0.13 s for its slot because the arrivals are
bunched, not because the horizon is full. Widening the window by the 0.05 s guard (+5%) or taking the grant check out of it (+16% of window per post) therefore gains 2% to 8% at a fixed
Z, and less on this runner, where (b) and (d) grow with the rate (the lock selects queue on the application row and the run queue lengthens). More loops raise the offered load
(+9% at 14, +15% at 16) and, here, the CPU wait with it. The sensitivity to the two assumptions is larger than any lever: each millisecond of database round trip adds 45 ms to a request (44.6 statements),
so 5 ms costs 14% of the rate and 10 ms 31%, which would move this run's median lateness from 15.7 to about 18 and about 23 minutes by the same arithmetic. The statements a request runs (44.6, about
ten round trips for each coordinator transaction: begin, settings, route map, seed, lock, reading, store, commit) matter as much as the round trip.

### Moved the wrong way, or not as modelled

- **Wire jitter and witness age rose.** `sent_at` to arrival p50 76 ms (51), p99.9 444 ms (286), max 546 ms (364), spread above the median at p99.9 368 ms (234); the oldest witness read is 2.72 s old at the create (2.34),
  against the 1.3 to 2.3 s of the limiter's simulation. Each booked read waits about 0.17 s and a pass has five of them, plus the create permit's wait (302 ms p50). The guard held better, not worse: 11 of 30,080 windows at the ceiling
  (0.037%, 1028a 0.129%), because booked slots are 45.8 ms apart by construction; the delay difference p99.9 is 143 ms and the maximum 206 ms against a slack of 100 ms.
- **The duty cycle did not rise on its own**: 0.78 (0.80). The lane is active from second 6 to second 51 of each minute: a cold start of about 6 s on a loaded runner, then a 50 s budget. A 56 s budget (S1-lane56, below) lifts it to 0.89 and the median lateness to 14.51 minutes, at the price of a wider wire tail on this runner.
- **Read-backs** (above).
- **The booked horizon is shallow** and the requests above 25 at the mock are 7: five are the mock's own processing order, two wire jitter, none the coordinator.
- **Hosted runs that lost data**: Fdb once (above).

### The 56-second lane loop (S1-lane56)

Same tree (`02fd679b`), same runner type, one run each: `POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS` 50 (the S1 above) and 56 (run 40705094663, harness `3bbc344c`).

| | S1, 50 s | **S1-lane56, 56 s** |
|---|---|---|
| Lateness median / p95 / max (min), limits 12 / 25 / 40 | 15.66 / 30.55 / 32.37 | 14.51 / 28.16 / 29.68 |
| Drain, T to the last verified (min) | 36.76 | 33.80 |
| Posts a minute on the plateau (minutes 3 to 5) | 159, 160, 159 | 173, 171, 173 |
| Plateau duty cycle | 0.78 | 0.89 |
| Active-window rate (requests a second) | 20.7 | 19.8 |
| Requests per created post on the plateau; per verified post | 6.16; 7.18 | 6.15; 7.16 |
| Implied median from duty x rate x requests per post (min) | 16.00 | 14.66 |
| Busiest 10 s / 60 s / 300 s (requests a second) | 22.0 / 16.7 / 16.5 | 22.1 / 18.1 / 17.8 |
| Reservation lock statements a created post, exclusive / shared (mean time) | 8.85 / 5.78 (34.7 / 15.1 ms) | 8.89 / 5.76 (36.2 / 15.5 ms) |
| Peak by the coordinator's wire time (`sent_at`), trailing / calendar second | 25 / 25 | 25 / 25 |
| Requests above 25 in a trailing second at the mock (REPORTED, owner reply 16) | 7 (peak 26): wire jitter 2, mock order 5, coordinator 0 | 11 (peak 28): wire jitter 9, mock order 2, coordinator 0 |
| Wire jitter, `sent_at` to arrival, p50 / p99 / p99.9 / max (ms) | 76 / 236 / 444 / 546 | 74 / 443 / 535 / 651 |
| Guard sizing, windows at the ceiling | 30080 windows, 11 violations (0.037%) | 29046 windows, 20 violations (0.069%) |
| Witness age at the create, p50 / p90 / max (s) | 2.72 / 3.02 / 4.33 | 2.74 / 3.77 / 5.72 |
| `bookedWaits`, `bookedSeconds` | 26829, 4504 s | 26118, 4711 s |
| Mean lane handler seconds a loop | 48.0 | 52.9 |
| Peak 1-minute load average of the runner (4 vCPUs) | 6.9 | 7.3 |
| Permits died unused | 0 | 0 |

Reading (inference). The lever does what the arithmetic said and little more: **the duty cycle rises from 0.78 to 0.89 (the lane is active from second 6 to 51 of each minute at 50 s and from second 5 to 58 at 56 s), the posts a minute from 159 to 173, and the median lateness falls from 15.66 to 14.51 minutes (p95 30.55 to 28.16, maximum 32.37 to 29.68)**. The requests per post (6.16 and 6.15) and the lock statements per post do not move; the active-window rate falls from 20.7 to 19.8 a second because twelve busier loops share four vCPUs (peak load average 7.3 against 6.9). One run each: the spread between 1023b and 1023d on the same code was 3.4 minutes in the median, so 1.2 minutes between two single runs is inside it and cannot be read alone; the duty cycle (0.78 to 0.82 in the earlier rounds) and the posts a minute moved by 14% and 9%, which is more than that spread explains and is what the arithmetic predicts. The cost shows in the tail of the wire: p99 443 ms against 236, p99.9 535 against 444, maximum 651 against 546, because the runner is more saturated; 20 of 29046 windows at the ceiling were violated against 11 (0.069% against 0.037%) with the 0.1 s guard, and the oldest witness read at the create reached 3.77 s at p90 and 5.72 s at the maximum. Requests above 25 at the mock: 11 against 7, none stamped above 25 by the coordinator (peak 25 trailing second in both).

<!-- /booking-1028c -->
