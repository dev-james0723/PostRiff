# RELEASE DEFINITION v2: open to every new customer, no allowlist

Written 2026-10-23 about 03:05Z after the owner's message (`AUTHORIZATION-RECORD.md`, reply 12); updated about 04:40Z after reply 13 (sections 2A, 4, 4A, 5). It replaces the "controlled acceptance on D1" framing. **Release status: NO-GO.** Nothing is promoted, `rafii.io` still serves the old build, and the full opening is not scheduled until every gate below has evidence.

## 1. The deliverable and what counts as done

The owner's standard, in the owner's words: a **new customer needs no manual allowlisting and can connect and use the Discord features of this release by themselves**. A dark build, an invitation, a tester allowlist, a green CI run, a READY build or deployed code do **not** count. If something blocks it, fix what can be fixed, then list the remaining problems; do not substitute a dark build for the goal.

Dark builds and tester sessions remain as **verification steps** on the way, never as the delivery.

## 2. Gates before the full opening (each needs evidence in the ledger)

| Gate | Evidence | Who | State |
|---|---|---|---|
| G1 Final release SHA frozen, exact-SHA CI green on every workflow | `RC-RECEIPT.md` | agent | RC1 `2a5a523d` done; the final SHA is RC2 (RC1 plus W-02) if capacity needs it, see G5 |
| G2 Independent AI security review of the **final** SHA, with the security-fix evidence | review report, finding-by-finding closure | agent | not started (the 2026-10-20 review is for an older SHA) |
| G3 Real flow with the approved tester account and content: consent, destination authorization, immediate publish, schedule, pause or cancel, revoke and reconnect (X-02 to X-06; at most the three messages already approved, text approved by the owner at that moment) | `RC-RECEIPT.md` section 5 | owner + agent | waits for a promoted build |
| G4 Isolation: two accounts A and B, **both directions, reads and writes**, denied with **no side effects**, on the hosted build; the write tests the original script lacked are added; no waiver, no deferral | probe script and receipt | agent (+ accounts) | probe built and validated locally on RC1 (branch `claude/discord-q05-probe-20261023`, 66 of 66 cases, mutation self-tests); the hosted run needs accounts A and B and a build whose connect gate admits them (`docs/q05/PLAN.md` on that branch) |
| G5 Capacity: 5,000 posts due in the same minute meet the latency standard in section 4, on an architecture consistent with production | capacity receipt | agent + owner (Depot) | RC1 cannot pass (7 to 14 hours); W-02 simulated about 23 minutes; W-02 is in independent review |
| G6 People and data: H-07 filled with real names, hours, alert entry and a stop and rollback method that works with the Mac offline; M-03 filled from the real project | `APPROVAL-PACKET-2.md`, section 6 here | owner + agent | M-03 partly read, H-07 open |
| G7 Fresh-customer acceptance **on the opened production**: a brand-new ordinary workspace with no Discord history and no allowlist connects, authorizes a destination, publishes now, schedules, pauses or cancels, reconnects and disconnects | receipt, script in `FRESH-CUSTOMER-ACCEPTANCE.md` (G3 runs before the opening on the dark build of the same final SHA) | owner + agent | after opening |

Open means: `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*` (or an equivalent setting) in effect on the serving Production deployment, server cap 10,000, Direct publishing reviewed flag on. Because the gate value lives on the build command today, a later build that omits it would silently close Discord again; making the open setting durable (a project variable) is a separate step that needs the owner's yes.

## 2A. The release order and the approvals it needs (owner reply 13)

Dark, then private verification, then public. `AUTH-5` is split in three; each stage has its own evidence and its own explicit approval, every failed gate is NO-GO, and a promoted dark build never stands in for a security check. Every Production build, promotion, environment-variable change and the final opening needs the owner's explicit approval, item by item.

| Stage | Evidence that must pass first | Approved separately by the owner | What it allows |
|---|---|---|---|
| **5a Pre-promotion** (nothing in Production changes) | Cross-tenant verification on the exact final SHA in an isolated environment (the Q-05 probe against the real app on a throwaway PostgreSQL with a mock Discord: both directions, reads and writes, no side effects; the probe's mutation self-tests run on copies that can never be deployed); independent code review of the final SHA closed finding by finding with fix evidence (G2); exact-SHA CI green on every workflow (G1); security configuration checks (required and forbidden names, flags, rate policy valid, shard crons registered, cron secret long enough, no env or key file in the upload set, Git deployments off, dependency audits clean); the customer-impact inventory (`CUSTOMER-IMPACT-INVENTORY.md`) showing no observable regression or side effect for existing customers while Discord is off for them | the dark build of the final SHA (the GitHub run approval, request commit named) and any environment variable it needs | a READY staged build that serves nobody |
| **5b Private canary** | 5a all PASS; the stop and rollback method rehearsed in isolation; monitors and alerts working with drill receipts from the isolated run | the Production **promotion** of the dark build; the Production-side rehearsal of the hold and of the rollback | the connect gate admits only the named tester workspace and the two Q-05 accounts. Real Discord objects: the tester session (G3, at most the three messages already approved), the hosted A/B probe including its Discord-object cases, monitors and alerts proved on the real build, the rollback drill |
| **5c Pre-public** | 5b all VERIFIED: hosted A/B probe with no case NOT RUN, G3, capacity (G5, on Depot against section 4), monitoring with drill receipts, on-call hours and alert channels confirmed (G6, so H-07 can be VERIFIED), rollback drill done, the Release Captain has the whole evidence packet | the open build (gate `*`, cap, reviewed flag), its promotion, the full opening, and making the open setting durable (`DURABLE-OPEN-CONFIG-PROPOSAL.md`), each explicitly | every eligible workspace; then the fresh-customer acceptance (G7) |

The capacity run is best done before 5b, because a miss there is the most expensive thing to learn late; it is a 5c requirement, not a 5b one.

## 3. Release scope

Production project `postriff-phase2-private` and its production database only. W-02 stays a separate branch until it is accepted. **If G5 needs W-02 (it does, by arithmetic), the release waits for W-02 to be accepted, integrated and the version re-frozen; the formal full opening then uses that new frozen SHA.** D1 and the approvals that name SHA `2a5a523d` do not carry over to RC2; RC2 needs its own builds and approvals.

## 4. Capacity standard (accepted provisionally by the owner in reply 13 as the RC2 stress-test acceptance threshold)

Accepted as an **internal release benchmark for an extreme spike, not as a promise to customers**; a miss on Depot is answered by optimizing requests per post, scheduling and throughput, **never by lowering the standard**, and any proposal that raises the 25-requests-a-second policy ceiling is reviewed again. The test budget is 25 requests a second and the run must also obey Discord's real global, per-route and other limits.

Scenario: 5,000 scheduled posts, spread over about 2,000 workspaces, all due in the same minute T, one of them a "hot" workspace with 3,000 of the posts in a second run. Measured on the same architecture as production (the Vercel cron shards and the lane, the shared request coordinator, a PostgreSQL of the same major version and comparable size, a mock Discord with 50 to 150 ms latency and a hard ceiling), not only in-process.

| Measure | Acceptable |
|---|---|
| Lateness from T (sent minus due) | median at most 12 min, 95th percentile at most 25 min, maximum at most 40 min (the approval lives 60 min) |
| Duplicates | 0 |
| Sent after the approval expired | 0 (held for a fresh approval instead) |
| Requests above the policy ceiling in any trailing second | 0 |
| Fairness | a workspace with at most 5 posts due is fully sent within 15 min even while the hot workspace has 3,000 due |
| Held or lost posts | 0 below 13,000 due in one minute; above that a stated, bounded number held for a fresh approval |
| Database | peak connections at most 70% of the pooler limit; no statement timeouts |
| Drain time | reported for 5,000 (target about 25 min at 25 requests per second and six requests per post) |

Numbers that follow from the code today: six requests per post; the policy ceiling of 25 requests per second gives about 4 posts per second, so 5,000 posts need about 21 minutes at best. A tighter standard forces fewer requests per post or a higher reviewed ceiling (`docs/w02/OPEN-QUESTIONS.md` Q2 and Q7 on the W-02 branch).

**Scenarios that must be run (reply 13):** fairness with a hot tenant; Discord 429 (global and per-route) and 5xx; retries (an uncertain create is never sent again); a worker crash (a loop killed mid-step); database contention (pooler saturation, lock waits, statement timeouts); approval expiry (held, never sent late); cross-tenant isolation under load (every message reaches its own destination only); backlog recovery (a stall, then recovery drains the queue, including after a configuration fix and after a rollback).

### 4A. Normal-load service level (draft, for the owner to adopt or change)

The benchmark above is a release test for an extreme spike. What customers are promised is the normal-load service level, measured over posts due in minutes when at most 250 Discord posts were due across all customers (about 4 a second, the rate the reviewed 25-requests-a-second ceiling can sustain at six requests per post):

| Measure | Target |
|---|---|
| Sent within 2 minutes of the scheduled time | at least 95% |
| Sent within 5 minutes | at least 99% |
| Sent within 15 minutes | 100% (anything later is an incident) |
| Sent exactly once | 100%: zero duplicates, ever |
| Sent after the customer's approval expired | zero |
| Not sent for a reason on our side (system error, stalled worker) | at most 0.5% of posts, each shown to the customer as held with a reason and re-approvable |
| Held or failed for the customer's own cause (bot removed, missing permission, deleted channel) | not counted, always shown with the reason |
| Valid Discord connection attempts that complete | at least 99% |

Above 250 posts due in a minute the lane drains at the policy rate, fairly across workspaces, and the benchmark numbers apply instead (the customer-facing copy already says a burst of scheduled posts can run late). The capacity harness has a normal-load scenario (S0: 100 and 250 posts a minute for 20 minutes) that measures these figures before the owner adopts them.

## 5. Answers recorded from the owner (reply 12)

| Item | Decision | What remains |
|---|---|---|
| H-05 | James is Release Captain. The independent AI review must correspond to the final release SHA, with the security-fix evidence. After real-flow, isolation and capacity acceptance pass, the owner approves the full opening. The "only D1 controlled acceptance" positioning is deleted | review of the final SHA; the approval itself comes after G3 to G5 |
| Q-05 | No waiver and no deferral past opening: A/B both ways, reads and writes, no side effects, before the full opening; add the missing write tests | two accounts; probe script (in progress) |
| H-07 | Keep as a requirement: real operator, hours, alert entry, and a stop and rollback method that works with the Mac offline; unconfirmed stays open | the owner's names; section 7 here is the method |
| M-03 | Keep as a requirement: real backups, restore points, compute; PITR as it really is; assess sufficiency; no automatic purchase | restore-point times from the dashboard |
| H-03 | Reuse the tester workspace and complete the ids and time slot; add a brand-new ordinary workspace with no Discord history | the ids that only the owner has, the time slot, a new account |
| T0 and GO_TIME | Now the target time of the full opening; postponed if acceptance, capacity or on-call is incomplete; D1 READY is not delivery | no date is set |

### Reply 13 (04:15Z), recorded in `AUTHORIZATION-RECORD.md`

| Item | Decision | State |
|---|---|---|
| Capacity standard | Accepted provisionally as the RC2 stress-test threshold (section 4), plus the scenario list and a normal-load service level (4A) | harness being extended; Depot run still to be started |
| H-07 | James is Release Captain for now, which is not 24/7 cover. Needs remotely operable monitoring, alerts (backlog, delivery failures, rate-limit exhaustion, silent halt, cross-tenant anomalies), stop and rollback with the Mac offline, drill receipts, and confirmed on-call hours and alert channels before public; not VERIFIED until then | design and isolated drills in progress; channels and hours are the owner's |
| M-03 | Read PITR, backup status, latest restorable time, RPO, RTO and the restore procedure with read-only tools; otherwise give the owner the simplest dashboard steps; nothing changed in Production, no destructive restore; without PITR assess risk and alternatives | in progress (section 6) |
| Q-05 | Approved in isolated environments, with mutation tests only in isolated fixtures or branches. Production accounts only through normal sign-up and sign-in; test credentials protected, short-lived, never logged; the owner is asked for the two accounts last, with minimal steps | probe done locally; hosted-run workflow being redesigned to use one-time e-mail codes |
| Release order | 5a, 5b, 5c (section 2A) | documented |
| H-03 | "OK 查" read-only metadata query done (result private); a new empty Discord server approved for planning; real sends only with the previously approved account and at most three approved messages | ids of the public and the private test channel still come from the owner |
| P0 silent halt | configuration validation, explicit fail-safe, alert, health indication, recovery and rollback tests before anything else of W-02 | fix 7 commits at `b33d3bfd` (validation, fail-safe, lag alert); health indication, recovery and rollback tests in progress |
| Durable open configuration | proposal only, nothing changed | `DURABLE-OPEN-CONFIG-PROPOSAL.md` |

## 6. M-03, what the tools can see (read-only, 2026-10-23 02:58Z)

Supabase organization plan: Pro. Project `postriff-phase2-private`, region us-east-1, PostgreSQL 17.6, healthy, 237 MB. **Compute is the smallest tier** (`max_connections` 60, `shared_buffers` 224 MB) [likely: this matches Micro]. Continuous WAL archiving is on and current (Supabase's WAL-G tooling, 26,579 segments, 0 failed, 0 waiting at 04:53Z) [certain]. **Corrected at 05:05Z:** that archiving is not evidence of point-in-time recovery, and Supabase's documentation says PITR needs at least a Small compute while this project's connection limit (60) is the Nano or Micro class, so PITR is **very probably not enabled** and the project very probably has the platform's daily physical backups (7 days) [likely, not verified]. **Not visible to any permitted tool:** whether the PITR add-on is bought, the backup list, the latest backup time. Full audit, methods compared and the restore duplicate-send hazard: `M-03-BACKUP-ASSESSMENT.md`. Assessment (details in `M-03-BACKUP-ASSESSMENT.md`): with daily backups only, the worst case is losing up to 24 hours of writes (new connections, schedules, approvals); with PITR it would be about two minutes. Credentials can be re-authorized and posts re-scheduled, so a daily-only plan is survivable for a launch but weak once many customers schedule posts; PITR is the owner's purchase decision and is not bought automatically. The small compute is a capacity question for G5: it is measured, not assumed, and an upgrade is also the owner's decision. Also read on 2026-10-23 (settings and connection counts only): the application reaches the database through Supavisor, Supabase's transaction pooler [certain: connection list], about ten connections were open in total, `max_connections` is 60 (3 reserved), and the database role's default `statement_timeout` is 120 seconds. Vercel Pro allows 100 cron jobs per project at one-minute precision [Vercel documentation, via web search]; the 13 crons of the W-02 build are within that, and the live per-minute cron already implies the team is on a plan that allows it [likely].

## 7. Stop and rollback with the Mac offline (H-07 method, to be tested before the opening)

1. **Close Discord for everyone, fastest, no deploy:** set the operator hold on the shared request coordinator (the `manual_hold` field of the policy row); every Discord request is then refused before it is sent. Done by the agent through the database tool, or by the owner from a phone with the Supabase SQL editor and the one prepared statement in `RUNBOOK-INCIDENT.md`.
2. **Roll back the serving build:** the agent promotes the previous deployment through the Vercel API (seconds, no rebuild); the owner can do the same from the Vercel dashboard on a phone (Deployments, the previous production build, Instant Rollback).
3. **Stop new connections only:** promote the dark twin or the previous build, or set the build-level kill switch in the next build (slow).
4. Before any rollback to an older worker, set the hold and drain or reconcile in-flight Discord jobs.
All of these need no laptop. The statements and the tested sequence are recorded before the opening; a method that has not been run once is not accepted as H-07 evidence.

## 8. Critical path (no dates are promised; any failed gate postpones)

W-02 independent review and fixes → integrate RC2 → freeze and exact-SHA CI → independent security review of RC2 (and fixes, which means a new SHA and CI) → isolation probe on the hosted build → Depot capacity run → RC2 dark build, owner approval, tester session (G3) → open build, owner approval, promotion → fresh-customer acceptance (G7) → the owner's sign-off. The earliest conceivable finish is today if every step passes the first time and the owner is available for three short sessions; a failed review, a CI failure or a capacity miss moves it to tomorrow or later.

## 9. Status log (newest last; facts only, no secrets or ids)

- **2026-10-23 03:00Z** Owner reply 12 recorded; this definition written; ledger updated.
- **2026-10-23 03:35Z** Independent review of the W-02 lane (head `14b78944`) closed. No new path to a duplicate or a lost post. Three findings, all being fixed on the W-02 branch: (1) HIGH, with the lane flag on but the rate-limit flag off, the policy expired or the shard crons not arriving, the minute worker stops sending Discord while the lane does not run, silently; the exclusion must depend on the lane being ready and a stalled lane must raise a warning; (2) the lane's pre-claim check ignores a spent invalid-request budget; (3) the 120-second hard cap leaves no slack against the 300-second function limit (to 90). The reviewer also says the simulated 23 minutes is an upper bound (mock latency 50 ms, local database, no pooler, no cold starts); the real-time capacity harness exists to measure it.
- **2026-10-23 03:55Z** Q-05 probe built and validated locally on the frozen head by an agent; verified by the captain re-running its self-tests (9 of 9 pass, 40 s). 66 cases (22 reads, 28 writes, 14 controls, 2 no-side-effect snapshots) all pass; every cross-tenant attack denied with no data in the response and no change at API and database level; zero Discord sends; the self-tests prove the probe detects four deliberately broken authorization points (membership gate, connection-to-workspace binding, OAuth state binding, a silent cross-workspace write that only the database snapshot sees). No isolation hole was found in the probed surface [verified by running]. Limits: the local database role bypasses row-level security, and the Vercel layer, production flags and the real rate coordinator are not exercised, so the hosted run is still required (accounts A and B; Discord objects in both tenants need a build whose gate admits them).
- **2026-10-23 03:58Z** Real-time capacity harness started (branch `claude/discord-w02-capacity-20261023`); fresh-customer and real-flow script written (`FRESH-CUSTOMER-ACCEPTANCE.md`).
- **2026-10-23 04:02Z** Workflow draft v4 (the dark twin's gate may hold one to five workspaces) written and tested offline (165 checks); it needs its independent delta review before any use (`BUILD-VIA-GITHUB-ACTIONS.md` section 8).
- **2026-10-23 04:05Z** Read-only look at the shared request coordinator's tables in Production (counts, key prefixes and timestamps only; nothing changed). The application-wide policy row exists (one row, no hold), so the stop statement of section 7 acts on a real row. One credential-scope row carries a hold (set 2026-10-17 19:30Z). **It is not the production bot [Likely]:** the request log shows that hold belongs to a bot token fingerprint that made exactly one request, on 2026-10-17 19:00Z, and got HTTP 401 (the coordinator itself holds a credential row after a 401, as `RUNBOOK-INCIDENT.md` says); the production bot's own fingerprint has 92 admissions, all HTTP 200, between 2026-10-17 20:00Z and 2026-10-19 17:00Z (including the tester's installation window), and no hold. Caveat: the bot token could have been reset after 10-19, which would give a new fingerprint; the first Discord request on a promoted build settles it. The old hold was left alone (holds are lifted only on the owner's word); the baseline check before the tester session (monitoring query Q3) will list it, and it is explained here so it is not mistaken for an incident.
- **2026-10-23 04:10Z** The W-02 fix agent finished (branch `claude/discord-w02-parallel-20261023`, head `b33d3bfd`, seven commits; verified by the captain: branch head, changed files, protected files untouched, 59 offline lane tests pass). All three review findings fixed (readiness-gated hand-over, lag warning, invalid-request wait, 90-second cap, preflight check). Correction to the review's premise: with rate limits off the frozen worker does not send in the hosted runtime either (it holds posts and asks for re-verification), so the stall was visible, not silent; the fix is right either way. One design decision taken by the captain: the minute tick must not keep Discord just because its own process is degraded (change in progress).
- **2026-10-23 04:15Z** Owner reply 13 recorded (`AUTHORIZATION-RECORD.md`). Consequences: AUTH-5 split into 5a, 5b, 5c (section 2A); capacity standard accepted provisionally, scenario list and a normal-load service level added (4, 4A); the hosted Q-05 run must use accounts made by normal sign-up and short-lived secrets (the hosted-run workflow is being redesigned around one-time e-mail codes; personal API tokens cannot be used because their route allowlist would make a denial come from scope, not from tenancy); H-03 metadata read once, read-only (result in a private file); durable open configuration proposal written (`DURABLE-OPEN-CONFIG-PROPOSAL.md`, nothing changed).
- **2026-10-23 04:50Z** Owner reply 14 recorded (goal-driven autonomous execution): the agent decides order, tools and agent assignments; ordinary read-only, reversible non-Production and isolated work needs no further approval; Production builds, promotions, env changes, Production DB or Auth writes or restores, real Discord messages, new costs and external publication still do; the owner asks for an RC2 readiness report once everything inside the authorization has a verified result.
- **2026-10-23 05:05Z** Reply 14 item 1 (the agent may create one blank private Discord server if the tester server is not enough): **not possible for the agent today** and not needed yet. Creating a server needs a signed-in Discord user session; the agent has none, the owner's paired Mac (the only authorized way to drive a logged-in browser) has been offline since 2026-10-22 14:52Z, and the production bot's token is a secret the agent must not read or use. The isolated tests use a mock Discord and need no server. A new server is needed only at stages 5b and 5c (a second tenant with its own server for the A/B Discord-object cases; the fresh-customer session), where the owner's own consents are needed anyway; creating it takes the owner about a minute then (Discord, plus sign, Create My Own, name it), or the agent does it if the Mac is online. Nothing is blocked today.
- **2026-10-23 05:05Z** M-03 audit redone with every permitted read-only method (`M-03-BACKUP-ASSESSMENT.md`): reading corrected (PITR very probably not enabled; daily backups probable; both unverified); the Management API would be definitive but needs an unscoped personal access token (refused); a local point-in-time-restore drill of the duplicate-send hazard has been started (branch `claude/discord-restore-drill-20261023`).
