# RC2 EVIDENCE PACKET (living; state: **NO-GO**)

Started 2026-10-23 about 04:40Z under owner reply 13 ("continue engineering until a complete RC2 release evidence packet exists, then submit the Production operations that need my approval"). It is updated at every stage with commit SHA, test receipts, PASS/FAIL, remaining risks and blockers. A line without a receipt is NOT RUN, never PASS. Nothing in Production has been built, promoted or changed for RC2. Rollback target for any future promotion: `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` (the build serving `rafii.io` today).

## 0. Identity

| Field | Value |
|---|---|
| RC1 (frozen, approvals and the staged build D1 `dpl_25ihHyiZCzZXAjVsJqJiYcCWA51n` belong to it; unpromoted) | `2a5a523d788eef67a5c7dbed609a98efa6650eef` |
| RC2 definition | RC1 plus the W-02 parallel Discord lane (and, if the capacity run demands it, the request-count optimization; and the small additive health and cross-tenant-log hunks from the ops branch once reviewed) |
| RC2 branch / frozen SHA / draft PR | not created yet. Created only after: W-02 fixes complete, delta re-review closed, ops hunks reviewed. The frozen SHA is then the only thing every receipt below refers to |
| W-02 branch head at the last update | `23af7a3a55dfeaf15a591dafbc061072be382d53` (pushed; the fix agent is still adding recovery and rollback tests) |
| Live (what customers use) | `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, source `c5fc1fd1`, no Discord v2 code |

## 1. Gate board (RELEASE-DEFINITION-v2.md)

| Gate | Evidence wanted | State | Receipt / link | Remaining risk or blocker |
|---|---|---|---|---|
| G1 frozen final SHA, exact-SHA CI on every workflow | run URLs per workflow on the RC2 SHA | NOT RUN | - | RC2 does not exist yet. Early local equivalents on the W-02 head: offline secret scan PASS (3,369 files, 0 unexpected), 59 offline lane tests PASS |
| G2 independent AI security review of the FINAL SHA with fix evidence | review report; `SECURITY-FIX-EVIDENCE.md` rows CLOSED | NOT RUN | register started, findings E-1/E-2 (the 2026-10-20 review) UNKNOWN | the old report must be found or the reviewer must re-derive its two P1 findings |
| G3 real flow with the approved tester account and content | tester-session receipt (stage 5b) | NOT RUN | script: `FRESH-CUSTOMER-ACCEPTANCE.md`, `TESTER-SESSION-SCRIPT.md` | needs the Production promotion approval; public and private test channel ids and a time slot from the owner |
| G4 A/B isolation, both directions, reads and writes, no side effects | local on the exact SHA (5a), hosted with real Discord objects (5b/5c) | PARTIAL: local on RC1 PASS (66 of 66, 9 self-tests incl. 4 detected mutations) | branch `claude/discord-q05-probe-20261023` @ `40fa4a4e`; hosted runner built (61 offline checks, 15 of 15 mutations caught), independent review of it running | re-run locally on the final SHA; hosted run needs accounts A and B by normal sign-up and short-lived codes, asked of the owner last |
| G5 capacity: 5,000 posts due in one minute against the accepted standard, plus the failure scenarios | Depot receipts S0, S1, S2 and injections | NOT RUN (harness in progress) | `docs/w02/RESULTS-SANDBOX.md` on `claude/discord-w02-capacity-20261023` when written | simulated 23 minutes is an upper bound; real figures unknown. A miss means optimizing requests per post, never lowering the standard |
| G6 people and data: H-07 (remote monitoring, alerts, stop and rollback, drill receipts, confirmed hours and channels), M-03 | drill receipt; owner's hours and channels; backup screenshots | NOT VERIFIED | `M-03-BACKUP-ASSESSMENT.md` (facts and four screenshots to take); ops branch `claude/discord-ops-20261023` (in progress) | on-call hours and alert channels are the owner's; PITR state unproven |
| G7 fresh-customer acceptance on the opened production | receipt | NOT RUN | `FRESH-CUSTOMER-ACCEPTANCE.md` | only after the opening |

## 2. Stage 5a (pre-promotion, nothing in Production changes)

| Item | State | Receipt |
|---|---|---|
| Cross-tenant verification on the exact final SHA in isolation (probe + mutation self-tests, copies never deployable) | PARTIAL (RC1 done) | see G4 |
| Independent code review of the final SHA, closed finding by finding | W-02 review round 1 closed (3 findings, 1 re-rated); delta re-review pending; final-SHA review not started | `SECURITY-FIX-EVIDENCE.md` |
| Exact-SHA CI | NOT RUN | - |
| Security configuration checks (required and forbidden names, flags, policy valid, crons registered, cron secret length, upload set clean, Git deployments off, dependency audits) | NOT RUN for RC2. The build route's preflight exists and passed for RC1 (run 39882363204); W-02 added the lane check to `scripts/check_postriff_hosted_preflight.py` | `BUILD-VIA-GITHUB-ACTIONS.md` |
| Customer-impact inventory (no observable regression or side effect for existing customers while Discord is off for them) | IN PROGRESS: **first findings are not clean.** FB-1 HIGH (Facebook approvals break in RC1: half-carried integration, fix in progress on `claude/discord-rc2-fixes-20261023`), CH-1 and BG-1 and WB-1 MEDIUM, PR-1 and SC-1 LOW to MEDIUM | branch `claude/discord-impact-20261023` (`docs/CUSTOMER-IMPACT-INVENTORY.md`) |
| Build workflow v4 (dark gate list of up to five workspaces) | written, 165 offline checks, independent delta review running | `BUILD-VIA-GITHUB-ACTIONS.md` section 8 |

## 3. Stage 5b (private canary) and 5c (pre-public)

Not started; both need the owner's separate approvals (section 5).

## 4. Findings and risks carried (ranked)

1. Capacity is the long pole: RC1 sends 6 to 12 posts a minute (7 to 14 hours for 5,000); W-02 is simulated at about 23 minutes but not measured; the Supabase project runs on the smallest compute (60 connections) behind a transaction pooler.
2. G2 depends on a report (E-1, E-2) nobody can find yet.
3. H-07 cannot be VERIFIED without the owner's on-call hours and alert channels; until then the agent-operated check-ins are best effort and not cover.
4. Restore hazard: a database restore can make already-sent posts look unsent and cause duplicates; every restore starts with the operator hold (`M-03-BACKUP-ASSESSMENT.md` section 4).
5. The open setting lives on the build command; a later build that omits it silently closes Discord (`DURABLE-OPEN-CONFIG-PROPOSAL.md`).
6. Pre-existing and outside this release: with the YouTube fleet on, the minute worker's invalidation lacks the deployment-binding filter (W-4 in the register).
7. **FB-1 (HIGH, found by the impact inventory, confirmed by probe):** RC1 breaks Facebook approvals and holds approved Facebook posts (the integration took two of the three pieces of one change). Existing customers with a Facebook Page would be hit as soon as RC1 or RC2 serves them. Fix for RC2 in progress; whether any Production workspace has a Facebook connection or queued post is unknown from here (a read-only count can answer it).
8. Other customer-visible or background side effects of the candidate with Discord off (CH-1, BG-1, WB-1, PR-1, SC-1) are listed in the inventory; WB-1 needs a Production decision at Packet 3 (the two worker-budget variables set on 2026-10-23 apply to every provider on any new build).

## 5. Production operations that will need the owner's explicit approval (none requested yet)

To be written as an exact numbered list in Packet 3 once sections 1 and 2 are green: (a) project variables the lane needs; (b) the dark build of the RC2 SHA (GitHub run approval, request commit named) and the gate-list secret; (c) its promotion; (d) the production rehearsals of the operator hold and of the rollback; (e) the hosted A/B runs (each a GitHub Environment approval); (f) the Depot capacity run and its cost; (g) the tester session and the real messages (at most three, approved account and content, anything outside the earlier approval asked precisely); (h) the open build and its promotion; (i) making the open configuration durable; (j) the extra real messages of the fresh-customer session.

## 6. Change log

- 2026-10-23 04:40Z skeleton created from the state after owner reply 13.
- 2026-10-23 05:10Z impact inventory first findings recorded (FB-1 HIGH); RC1 receipt corrected; fixes agent started.
