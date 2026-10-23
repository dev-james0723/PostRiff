# W-02 capacity harness: results in the development sandbox (2026-10-23)

**These are correctness and fault-injection results, not capacity evidence.** The sandbox is a 4-core, 15.7 GB
container shared with other agents. Its one-minute load went from about 1 to 40 during these runs, and every process
of a run (database, pooler, mock Discord and each cron invocation) competes for the same 4 cores. Throughput and
lateness measured here are slower than they would be on an idle machine, by an unknown amount. They are never a pass
or a fail of section 4.

The evidence of record is the GitHub-hosted runs: ubuntu-24.04, 4 vCPU, 16 GB, PostgreSQL 17 behind PgBouncer in
transaction mode, one fresh VM per scenario, requested through `docs/w02/ci/`.

Sandbox software: PostgreSQL 16.15, Python 3.13.16 and psycopg 3.3.5 (binary) from a scratch venv, with the
transaction pooler of the harness (pool 20, 2 ms per round trip, 4 round trips per new connection). Every run used
synthetic data and the real code of the tree under test, as a separate OS process per cron invocation. Nothing went
beyond 127.0.0.1.

## Runs

| When (UTC) | Scenario | Tree | Harness | Posts | Sent / verified at the mock | Requests per verified post | Load (start / peak) | Outcome |
|---|---|---|---|---|---|---|---|---|
| 04:40 | smoke | 14b78944 | 997e76d8 | 60 | 0 / 0 | n/a | 1.4 / 1.9 | Harness setup fault: every invocation answered 503, "Hosted Phase 2 is not configured" (no Supabase URL shape). The harness was fixed; NOT MEASURED. |
| 04:45 | smoke | 14b78944 | 997e76d8 | 60 | 60 / 60 | 9.3 | 0.4 / 1.5 | All expected checks pass |
| 04:49 | S1 | 14b78944 | 997e76d8 | 5,000 | not collected | n/a | 0.9 / n/a | Seeded 5,000 posts in 2,000 workspaces (4 processes, 398 s), then lost to a container restart at about 05:00. The cluster was removed before recovery existed; NOT MEASURED. |
| 05:07 | smoke | 62f68c56 | dc8c38ef | 30 | 30 / 30 | 10.5 | 8.4 / 8.4 | All expected checks pass |
| 05:11 | F429 | 62f68c56 | 920991d6 | 1,000 | not run | n/a | 2.4 | Stopped during seeding on purpose (its time limits were wrong); NOT MEASURED |
| 05:15 | smoke | 62f68c56 | 5904201b | 30 | 30 / 30 | 10.8 | 5.5 / 5.8 | All expected checks pass (two-phase seeding) |
| 05:12 | F429 | 62f68c56 | 8f24045b | 1,000 | 887 / 724 | 12.5 (10.2 per sent post) | 2.7 / 14.2 | Ended at its 12-minute limit. Details below. |
| 06:04 | smoke | 62f68c56 | 90ddd791 | 30 | 0 / 0 | n/a | 17.7 / 40.5 | Machine overload: 8 steps in 40 invocations, admission to observation 2.4 s. Ended "no progress for 2 min"; NOT MEASURED. |

Receipts and raw files of each run are under the session scratchpad
(`/tmp/claude-0/-home-user-PostRiff/3cb76cca-883c-52d5-850d-5dab5e917b4a/scratchpad/runs/`). They are not committed.

## F429 on 62f68c56: 1,000 one-post workspaces with injected 429s

Injections: two global 429 windows (T+1.5 min, Retry-After 5 s; T+3.0 min, 3 s), a route 429 on 5 creates and on 5
server reads, and a Cloudflare-style HTML 429 (ban page) on 2 channel-list reads.

- **No duplicates**: 0 by nonce, 0 by post id. **No create after approval expiry.** **Isolation**: 0 misrouted of 887
  creates, 0 creates for an unknown post.
- **Global 429 embargo:** the mock saw 0 bot requests inside the embargo, and creates resumed 3.3 s after it.
- **The 5 posts whose create got an injected 429** are all held and never sent again, as the existing rule says.
- **Strict ceiling, policy_ceiling: FAIL.**
  - At the mock: 5 requests had more than 25 others in the trailing second (peak 26). The most in one calendar second
    was 24.
  - The coordinator's own admission table, read during the run: at most 27 in a trailing second, 25 in a calendar
    second.
  - The cause is in the code: the application window restarts at the first request after it expires, so two windows
    can share a trailing second. Reported to the coordinator; a separate agent is making the ceiling exact. The
    measure was not changed.
- **Not verified at the end (276):**

  | Reason | Posts |
  |---|---|
  | read-back pending at the time limit (`provider_accepted`) | 163 |
  | never claimed before the time limit (`scheduled`, no create) | 106 |
  | held after an injected create 429 | 5 |
  | `uncertain` with **no create at the mock** | 2 |

  - The 2 uncertain posts were sealed when the global 429 arrived. The coordinator stopped their permits
    (`rate_limits.py:917-923`), and `_submit_discord` marks such a post uncertain, "No POST was started; manual review
    required" (`hosted_social.py:473-476`). Reported as a customer-visible effect.
  - "Every other post verified" is a FAIL here because of the time limit at about 12 requests per second under load.
    F429 now has 20 minutes.
- **The read-back waits for a full pass:** 0 read-backs in the first 6 minutes. Create to verified read-back took a
  median 5.9 min and a max 7.6 min. 276 posts were unverified at the last create (`docs/w02/REQUEST-BUDGET.md` 4.2).
- **Requests:** the ledger is 10.2 per sent post. Preflight passes per sent post: one 621, two 229, three 37. The bot
  identity pair added 0.35 per sent post.
- **Harness fault found here:** the injected ban page carried no server, so the ban-page check passed with 0 servers.
  It is fixed in 90ddd791.

## Seeding with several processes (the GitHub-hosted failure)

All four scaled requests on the runner (harness 920991d6) failed in seeding. Reproduced here with the tree's real
connect flow:

| Check | Result |
|---|---|
| 4 processes, 40 workspaces, before the fix | 1 of 1 failed: `ReadAdmissionDelayed` on the bot's `GET /users/@me` in the first workspace |
| 8 processes released together, retry off (negative control) | 2 of 3 failed the same way |
| 8 processes released together, with the fix | 3 of 3 passed (one retried `GET /oauth2/applications/@me (discovery)` once in 3 slices) |
| 4 processes, S1 size (2,000 workspaces, 5,000 posts), with the fix | passed in 915 s at load 16; 20,114 admissions, all `observed`, none left open |
| unit test and offline check: 4 processes, 16 workspaces; a slice failing on purpose | pass; the failing slice's traceback is quoted in `harness.log` and in the error |

Cause: the bot's own routes have no major parameter, so while unknown they get one discovery admission per second
for all processes. The provider waits at most 1 s for a read admission. The fix and the diagnostics are in 22e3257e.

## Lock benchmark (smallest size only)

At load 16, 0 ms injected latency and 20 s per point, with learned routes and no policy limit:

- 1 process: 9.2 admissions/s;
- 2 processes: 18.8/s;
- reserve p50 45 ms, observe p50 63 ms, mostly a new connection per transaction.

That is linear at 2 processes. The full benchmark is profile `lockbench` on the GitHub-hosted runner.

## Not measured here

- The section 4 lateness, fairness and drain (S1, S2) and normal load (S0). These are the GitHub-hosted receipts.
- The frozen worker's posts per minute (baseline). It needs the `release` profile or a baseline request on the runner.
- On this harness version: F5xx, Fcrash, Fdb, Fexpiry, Fstall, Fflip, Nmisroute, Ndup and Nceiling. They are in the
  runner's `faults` profile.
