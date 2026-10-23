# H-07 EVIDENCE: what is verified, what is blocked, and why

**H-07 status: BLOCKED.** Nobody has been named as Primary or Backup, no destination exists for either, the owner has not declared that P0 is covered at night, and no delivery path to a person is wired. This status is computed, not written by hand: `python -m rafii_control.oncall.readiness` (exit 2 = BLOCKED) over the shipped policy and `docs/ops/h07-real-evidence.json` (empty). It can become **VERIFIED** only when every row of section 1 has a passing test on real people and real destinations. Isolated drills never count, because a fake provider proves nothing about delivery.

Branch `claude/discord-ops-alerts-20261023`, built on the RC2 integration line `5a94b4f2` with W-02 `5fc6cb21` merged (`d864f25f`). Nothing here was deployed, configured or applied: no Production variable, setting, database row or migration, no paid service, no real person contacted, no external call.

## 1. Verification matrix (one row per requirement)

"Real" is the only column that can make H-07 VERIFIED. "Isolated" is what the drills and tests prove about the logic (`ONCALL-DRILL-RECEIPT.md`, `DRILL-RECEIPT-ISOLATED.md`, the unit tests).

| Requirement | Real test on real people and destinations | Isolated proof (logic only) | What the real test must show |
|---|---|---|---|
| `roster` | **NOT VERIFIED**: nobody named; the shipped roster is a placeholder (`roster_problems`: no push, e-mail or phone for either role) | R01 PASS: gaps, a missing or identical Backup and missing channels are detected; an invalid roster is the engine's own P0 | a named Primary and a different Backup cover every minute of the week, and each received a test page |
| `routing_p0` | **NOT VERIFIED** | R02 PASS: second 0, push and e-mail to the Primary, nothing else; P0 ignores duty hours, holidays and quiet hours | a real P0 (announced test) reaches the Primary by push and e-mail within one evaluation |
| `routing_p1` | **NOT VERIFIED** | R05 PASS: duty hours push and e-mail, Backup after 15 duty minutes; night e-mail at once, push at 09:00 New York time; the spring-forward night counts duty minutes only | the same, observed on the Primary's devices |
| `routing_p2` | **NOT VERIFIED** | R06 PASS: one e-mail at 09:00, nothing else | a P2 e-mail received in duty hours only |
| `push_delivery` | **NOT VERIFIED**: no adapter is wired (option A) and no vendor chosen (option B) | R08 PASS for the fallback logic only | a push received on each person's phone |
| `email_delivery` | **NOT VERIFIED** | as above | an e-mail received by each person |
| `phone_delivery` | **NOT VERIFIED**: no call path without the founder quiet hours and daily cap (`H07-POLICY-MAP.md` section 5) | as above | a call that rang and was answered by each person |
| `acknowledgement` | **NOT VERIFIED** | R07 PASS: push, e-mail, phone and dashboard acknowledgements stop the chain and are recorded; a forged link is refused | an acknowledgement from each channel stops the chain and appears in the timeline |
| `escalation_5min` | **NOT VERIFIED** | R03 PASS: no call at 299.9 s, a call at 300 s | the Primary's phone rings at 5 minutes, not before |
| `escalation_10min_backup` | **NOT VERIFIED** | R04 PASS: nothing to the Backup at 599.9 s; push, e-mail and phone at 600 s | the Backup receives all three at 10 minutes |
| `dedupe` | **NOT VERIFIED** | R09 PASS: one incident for 60 overlapping evaluations, every notification key unique (enforced by PostgreSQL in R12) | a repeating real alert produces one notification per step and channel |
| `suppression` | **NOT VERIFIED** | R10 PASS: maintenance holds the chain until it ends; a security alert pages inside a window; a cause holds its symptoms; a flap within 10 minutes is damped. R11 PASS: storm limit, one summary, the rest later | a maintenance window and an inhibited symptom do not page; a security alert in a window does |
| `audit_trail` | **NOT VERIFIED** | R12 PASS on PostgreSQL (migration 140 applied twice): ordered timeline of steps, deliveries, acknowledgement and resolution; the session role cannot update or delete an event and a trigger refuses even the owner; another environment sees nothing | the real timeline of the end-to-end test, read from Founder Control |
| `end_to_end` | **NOT VERIFIED** | R14 PASS: the real payload of a halted lane, the real evaluator, the engine on PostgreSQL: Primary at once, call at 5, Backup at 10, the Backup acknowledges by phone, the senders drain, the incident resolves by itself and both people get the record | one announced night-time P0 drill from the evaluator to the Backup's call and back to resolution |

Also isolated: R13 PASS (the heartbeat the watchdog role can read, and nothing else; stale after 180 s; a restart after a gap opens `ONCALL_ENGINE_GAP`), R15 PASS (the optional automatic hold: probing never holds, a failed probe holds and the lanes stop, the engine never lifts it). The Discord monitoring itself (the payload, the 40 alert rules, the hold and rollback statements) is drilled in `DRILL-RECEIPT-ISOLATED.md` (9 drills).

## 2. The BLOCKED rule

`src/rafii_control/oncall/readiness.py`, tested in `tests/test_oncall_engine.py` (`Readiness`):

1. **BLOCKED** when the owner has not declared that a named Primary and Backup cover P0 at night, weekends and holidays, or when the roster cannot carry P0 (a gap, a missing Primary or Backup, the same person in both roles, a person without push, e-mail or phone).
2. **NOT_VERIFIED** when cover is declared and the roster is valid, but any requirement of section 1 lacks a passing real test (kind `real`, real people, real destination, a time and a receipt reference). Isolated entries are listed and ignored.
3. **VERIFIED** only when every requirement has a passing real test.

Today: BLOCKED, reasons `night_cover_not_declared` and `roster:{primary,backup}_without_{push,email,phone}`.

## 3. Executable alternatives while BLOCKED

1. **Name the people.** A Primary and a Backup for nights, weekends and holidays (for example a Backup in another time zone), each with a push subscription, an e-mail and a verified phone; declare night cover; then run the real tests of section 1 once (section 6, row H07-A).
2. **Option B**, a paging service with schedules, calls and its own heartbeat monitor (paid; the owner chooses the vendor), driven by the evaluator through a vendor-neutral adapter.
3. **A stop that strands nothing, prepared in advance**: the Discord-paused staged build (`PHONE-RUNBOOK.md` lever 2; Packet 3 row 12b). A woken person can promote it instead of the database hold. The automatic database hold (option D1) is **not recommended**: the hold itself strands posts (section 5, H1).
4. **Smaller exposure**: open with a smaller server cap, or keep the canary gate, until cover exists; or delay the opening. Business decisions for the owner.

## 4. What is proven in isolation, and the counts

| Evidence | Result |
|---|---|
| `tests/test_discord_ops_check.py` (the 40 alert rules, thresholds, command line, fetch) | 63 tests OK; 27 of them fail on the reviewed evaluator (section 5) |
| `tests/test_discord_ops_health.py` (the route and payload) | 17 OK |
| `tests/test_security_signals.py` (the denial signal) | 12 OK |
| `tests/test_oncall_policy.py` (policy, duty hours across both 2026 New York transitions, rosters, the rule-to-priority table) | 17 OK |
| `tests/test_oncall_engine.py` (engine, providers, store in memory, automatic hold logic, readiness) | 36 OK |
| `tests/test_discord_ops_drills_postgres.py` offline part (runbook statements, the hold statements of the engine, migration 141 against the twin) | 4 OK |
| `tests/test_discord_ops_drills_postgres.py` on PostgreSQL 16 (9 drills, `DRAIN_CHECK` at 5,201 workspaces, migration 141 applied twice) | see `DRILL-RECEIPT-ISOLATED.md` and the final report |
| `tests/oncall_drills.py` / `tests/test_oncall_drills_postgres.py` (15 policy rows) | `ONCALL-DRILL-RECEIPT.md` |

The thresholds file holds 45 values for the 40 alert ids (the reviewed head had 41 for 36).

## 5. The independent review of `8e76afdd`: each finding

Reviewer notes and probes: the coordinator's scratchpad `review-ops/` (not in the repository). Probes re-run here on the merged head `d864f25f` with the reviewer's own scripts.

| Finding | Status | Fix | Evidence (fail before, pass after) |
|---|---|---|---|
| **C1** `DRAIN_CHECK` sampled 5,000 workspaces by id | CLOSED | complete statement: the due-work projection's workspaces joined to their state, publish admissions through the unresolved-state index; gate on `live_leases 0` and `publishes_in_flight 0` | before: reviewer `exp_drain` at 5,201 workspaces gave `(0, 0, 0)`; after: `test_c1_the_drain_check_is_complete_above_five_thousand_workspaces` gives `live_leases 1, sealed_now 1, non_terminal_jobs 1`; O2 now runs `DRAIN_CHECK` inside a create in flight and requires a positive count; the reviewer's blind mutant (`SELECT 0,0,0`) re-run on this head: **caught** (O2 fails) |
| **H1** hold text ("nothing is lost", "about an hour") | CLOSED | `PHONE-RUNBOOK.md` rewritten from measurements: which worker owns Discord; read-backs parked 24 h when a Discord-claiming worker runs under the hold; re-approval from about 55 minutes after each post's own scheduled time | re-run on `d864f25f`: **E1** a created post's read-back refused 5 times, then parked 86,400 s "manual provider review" (survives); **E1c** the RC1 file under the hold: unsent post pushed back 5 minutes, created post parked after tick 5 and still parked after the lift (survives); **E3b** approval ending in 200 s: one claim under the hold makes it `held`, not retried after the lift (survives); **E2** see below |
| **H2** rollback order | CLOSED | authority for both `HOLD_ON` and `HOLD_OFF` before step 1; lift at once after the alias read-back; the `dpl_47SGx` decision written out (drain with the hold off, cancel, or a v2 target) | O2 drill: the older worker run under the hold sends nothing (and burns read-back checks, which is why the lift is immediate), then drains after the lift with no duplicate |
| **M1** silent section failures, no schema check, NO_PROGRESS skipped without the ledger | CLOSED | `SILENT_HALT_SECTION` per `errors[]` entry (warn, page when persistent); malformed kind, version, source or sections page `SILENT_HALT_HEALTH_UNANSWERED`; NO_PROGRESS evaluated with an unread age counting as no progress | `test_M1_*` (3 tests) fail on the reviewed evaluator, pass now; the reviewer's `exp_missing` case (ledger missing, 1,500 s overdue, last claim 4,000 s) now pages NO_PROGRESS |
| **M2** BACKLOG page inside the standard burst | CLOSED | warn 900 s, page 2,700 s | `Backlog.test_boundaries` fails before (4 subtests), passes now; D1 drill at 1,000 s warns, at 3,000 s pages |
| **M3** default phase `pre_open` | CLOSED | `--phase` required; the function defaults to `open` | `test_M3_*` fails before, passes now |
| **M4** uncertain alert clears at 15 minutes while unresolved | CLOSED | unwindowed `unresolved` counts (payload and SQL twin, partial index) keep `DELIVERY_UNCERTAIN` and `DELIVERY_STUCK_SENT` at warn until reviewed | `test_M4_*` errors before, passes now; D2 drill: after 16 minutes the share alert clears and the uncertain warning stays with `unresolved 3` |
| **M5** bursts under-reported; probing mapped to `HOLD_ON` | CLOSED | log lines at running counts 1, 10, 100, 1,000 and a final line per minute (per-process label); probing no longer means hold (runbook, evaluator message, on-call policy) | `test_a_burst_is_reported_by_its_size_not_as_one_denial`: the reviewer's 5 + 5 + 5,000 now reads 5,010 from the logs (was 11) and pages; D5 drill: 38 refusals read as 38 from the logs alone |
| **M6** held, failed and created-post signals unused | CLOSED | `DELIVERY_HELD_GROWTH`, `DELIVERY_FAILED_GROWTH` (against the previous report's memory), `SILENT_HALT_NO_CREATE` (no accepted create and no read-back for 10/30 minutes while work is due) | `test_M6_*` (2 tests) fail before, pass now |
| **M7** vacuous drills (coordinator hold, blind drain check, older worker under the hold) | CLOSED | O2: positive drain check, older worker under the hold; O1: proving `HOLD_ON`, key check | the reviewer's two vacuous mutants re-run on this head with his script: "coordinator ignores manual_hold" **caught** (O1 fails "nothing was admitted after the hold committed"; O2 fails "the coordinator refuses the older worker under the hold"), "DRAIN_CHECK replaced by SELECT 0,0,0" **caught** (O2 fails both drain checks); `REVIEW-8E76AFDD-EVIDENCE.md` |
| **M8** fetch followed redirects with the bearer, accepted http, no deadline | CLOSED | https only (http only to this machine), no redirects, one overall deadline, size cap | `test_M8_*` (3 tests) fail before, pass now |
| **M9** no read-only credential for the health route | DESIGNED, NOT APPLIED | migration 141: `public.pr_discord_ops_snapshot()`, the SQL twin as a SECURITY DEFINER function owned by a NOLOGIN, non-BYPASSRLS role with column grants and its own read policies; a NOLOGIN reader role with EXECUTE only; the login is an owner step (row H07-B) | `test_m9_*` on the disposable cluster: applied twice; the reader reads the snapshot and is refused on all six tables; same counts as the twin; `test_migration_141_runs_the_sql_twins_own_statement` |
| **L1** twin read a stale `invalid` row | FIXED, not separately drilled | the most recently updated row per kind | D0 twin parity still passes |
| **L2** twin cannot evaluate the policy, credential hold or configuration | DOCUMENTED | by design: those are process facts; the route and the monitoring function cover the rest | the twin header |
| **L3** crash exit 1 = warn; drain envelopes | CLOSED | exit 3 on an internal error; `{"message": ...}` envelopes unwrapped | `test_L3_*` |
| **L4** unauthenticated traffic inflates the Discord 4xx family | OPEN | not fixed here: `/api/ops/...` is recorded as `/api/:id/discord/:id` by `request_metrics` (a shared module); proposal: add `ops` to its route words in a reviewed change | `CROSS_TENANT_DISCORD_4XX` is a warning only |
| **L5** a wrong id in `HOLD_INSERT` is silent | CLOSED | `HOLD_KEYCHECK`; the read-back explains `policy_rows 2` | O1 drill: a mistyped id is caught and `HOLD_ON` then holds both rows |
| **L6** "about an hour" | CLOSED | "about 55 minutes after each post's own scheduled time" | runbook |
| **L7** HTTP 200 with the database down | DOCUMENTED | the body says it: `SILENT_HALT_DATABASE` pages | D4 drill |
| **L8** cap 10,000 against Discord's 100-server limit for unverified bots | OPEN, owner | Discord's own verification of the bot governs servers beyond 100; the expected cap assumes it | owner item |
| **L9** "the one place" | CLOSED | docstring names the gates that bypass the signal | `security_signals.py` |
| **L10** 40-bit actor key | DOCUMENTED | enough to correlate one member's lines, not to identify them | docstring |
| Counts 36 ids / 41 thresholds vs "32" | CLOSED | 40 ids, 45 threshold values, stated where counted | this page, policy map |

**E2 (a hold landing while posts are sealed) on the merged head.** The coordinator expected it to be gone with W-02 `466232ab`/`f525aa17`, which prove a hold- or embargo-blocked sealed permit unsent and retry it (W-02 tests `test_a_global_429_seen_while_posts_are_sealed_sends_each_once_after_the_embargo` and `..._reserved_but_not_sealed_...`). Three re-runs of the reviewer's probe could not reproduce its interleaving under this machine's load (load average 20 to 37): the probe's threads wait inside `consume` longer than the 5 or 10 second permit lifetime. In each run, one post that was sealed and never sent still ended "uncertain, the original Discord target or message ID is missing" and was parked for 24 hours (no duplicate; never sent). **A control run without any hold gave the same result**, so that residue comes from a loop stalled between sealing and sending past its permit and lease, the case W-02 documents as uncertain by design (`test_control_a_loop_killed_between_seal_and_post_leaves_its_post_uncertain`), not from the hold. Reported to W-02 as an open question; the runbook's "Not covered" says it.

## 6. Production steps and owner inputs (rows for APPROVAL-PACKET-3)

Nothing below is requested by this branch; the Release Captain adds the rows to the packet. Each is a Production operation or an owner decision.

| Row | Who | Operation | Needs first | Risk | Rollback | Cost |
|---|---|---|---|---|---|---|
| H07-A (Packet 3 row 11) | owner | Name the Primary and Backup; give each a push subscription, an e-mail address and a verified phone number, kept in Founder Control (not in the repository); declare honestly whether P0 is covered at night, weekends and holidays. Then, once a delivery path exists (H07-C or H07-D), run each real test of section 1 once, announced, record it in `h07-real-evidence.json` (kind `real`, time, receipt) and re-run `readiness` | a delivery path | real notifications to real people; one announced night test | none | per-call charges of the chosen provider |
| H07-B (review M9) | agent, with owner approval | Apply migration 141 to Production; create the login `rafii_discord_ops_monitor` in role `rafii_discord_ops_reader` with a generated password (read-only session, 5 s statement timeout); give its connection string to the monitor as a secret; read back that it can run `SELECT public.pr_discord_ops_snapshot()` and cannot read a table | the final SHA reviewed; Supabase's migration runner can set the function owner (as 055 does for views) | a new database login | `DROP ROLE` the login; the function and roles are additive | none |
| H07-C (option A) | owner decision, then engineering | Build and review the real adapters (founder outbox for push and e-mail, a P0 call path without the founder quiet hours and the daily cap of 2, acknowledgement links), apply migration 140, register the founder cron stage, set `RAFII_ONCALL_ENGINE_ENABLED=true` | H07-A; review of the P0 call-policy change | the on-call engine pages people | flag off | call minutes; estimate 3 to 5 engineering days [guess] |
| H07-D (option B) | owner | Choose and buy a paging service; invite the Primary and Backup; set the escalation 0, 5 and 10 minutes; give the integration key and heartbeat URL as secrets | H07-A | a new data processor (codes and counts only) | cancel the service | per responder per month |
| H07-E (option C) | owner | The Discord watchdog workflow with the H07-B login (fails on any page or a stale heartbeat; GitHub notifies) | H07-B | GitHub notifications only, no call | disable the workflow | Actions minutes |
| H07-F (D1) | owner decision, **not recommended** | Enable the automatic database hold (`RAFII_ONCALL_AUTO_HOLD_ENABLED`, failed isolation probe only) | H07-C | a false positive pauses Discord for everyone and strands read-backs and approvals | flag off; a person lifts the hold | none |
| 12b (exists) | owner | Prepare the Discord-paused staged build | none | none until promoted | never promote it | build minutes |

## 7. Restore

A database restore rewinds the hold with everything else. The restore lane's `RESTORE-RUNBOOK-PROPOSAL.md` section 4.J (a proposal, not in force) and `RESTORE-HAZARD-DRILL.md` measured why a hold must prove itself and why the Discord-paused build is the stop that survives an in-place restore. `PHONE-RUNBOOK.md` follows both points and does not rely on that proposal's reconciliation tool, which is not reviewed.
