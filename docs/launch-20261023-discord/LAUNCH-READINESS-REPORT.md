# LAUNCH-READINESS-REPORT (Discord capped Wave 1)

Generated 2026-10-22T21:29:10Z. Candidate: `claude/discord-launch-rc-20261023` at `29bc8ab2` (draft PR #222, not frozen). Live build: `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` (source `c5fc1fd1`, no Discord v2 code).

## Recommendation: **NO-GO today**

A false GO is the worst outcome, and none of the gates that need the owner, Discord or a frozen green build has passed. This is not a failure of the work done so far; it is where the evidence stands.

**Why, in order of weight**

1. **No qualified build exists yet.** CI on the exact frozen SHA has not completed (S-06, S-08), so none of the code items can be VERIFIED under the rule "tests plus CI on the exact SHA".
2. **Nothing real has been proven.** Real OAuth and bot install, one real send with read-back, and an unattended schedule with cancel (X-02 to X-05) all need the dark promotion and the owner's 20-minute session. They have not happened and cannot happen before the owner's approvals.
3. **Owner-only gates are open:** Portal verification status and settings (H-01, H-02), the tester assets and T0 (H-03, D-05), the Release Captain and security-review decision (H-05), on-call (H-07), and approval of the public privacy wording (H-08).
4. **Backup and restore point are unverified** (M-03) and Production env names cannot be fully listed with the tools available (C-02).
5. **Scale:** "thousands" is not possible tomorrow. An unverified app is limited to 100 servers and verification is Discord's timeline. The capped plan is at most 90 servers.

**What would flip it:** every row below that is a Wave 1 MUST becomes VERIFIED with evidence, no abort trigger has fired, and the owner says GO. The fastest honest path is in `RUNBOOK-LAUNCH.md` section 2; the owner's part is about 60 minutes in total.

## Wave 1 GO criteria (54 items; 2 BLOCKED_EXTERNAL, 41 NOT_RUN, 11 VERIFIED)

| ID | Item | Owner | Status | State | Evidence |
|---|---|---|---|---|---|
| D-01 | Launch scope for tomorrow | HUMAN | **NOT_RUN** | default applied by the agent (assumption logged); the owner has not replied: capped Wave 1, at most 90 servers | APPROVAL-PACKET-1.md section 4 |
| D-02 | Which lanes ship in the same RC | HUMAN | **NOT_RUN** | default applied by the agent (assumption logged); the owner has not replied: Discord delta on the live line only | APPROVAL-PACKET-1.md section 4 |
| D-04 | Exposure rule for 'Direct' publish and schedule | HUMAN | **NOT_RUN** | explicit decision requested (packet row 4): REVIEWED passed on the two RC build commands only | APPROVAL-PACKET-1.md row 4 |
| D-05 | Launch time T0 and GO / NO-GO time | HUMAN | **NOT_RUN** | T0 and GO_TIME not given; the agent assumes T0 = 24 hours after its start and says so | APPROVAL-PACKET-1.md section 2 |
| H-01 | Discord Developer Portal: App Verification status, and start verification today | HUMAN | **NOT_RUN** | human only; preparation done | H-01-verification-prep.md |
| H-02 | Portal settings audit | HUMAN | **NOT_RUN** | human only (or AUTH-10 read-only); audit sheet prepared | PORTAL-AUDIT-SHEET.md |
| H-03 | Tester assets and one 20-minute consent session | HUMAN | **NOT_RUN** | human only; session script prepared | TESTER-SESSION-SCRIPT.md |
| H-04 | Reply to the Approval Packets | HUMAN | **NOT_RUN** | Approval Packet 1 rev A sent to the owner 2026-10-22 ~19:35Z; no reply yet | APPROVAL-PACKET-1.md |
| H-05 | Release Captain sign-off and security-review decision | HUMAN | **NOT_RUN** | human only | APPROVAL-PACKET-1.md section 2 |
| H-07 | Support and on-call for the launch window and first 24 hours | HUMAN | **NOT_RUN** | human only | APPROVAL-PACKET-1.md section 2 |
| H-08 | Approve customer-facing Discord disclosures | HUMAN | **NOT_RUN** | wording drafted and committed on the RC as its own commit; awaiting approval; the build waits for it | P-01-privacy-terms-diff.md |
| S-00 | Baseline snapshot of facts (Appendix A) | AGENT | **VERIFIED** |  |  |
| S-01 | Identify the lineage of the build rafii.io serves now | AGENT | **VERIFIED** | live build is c5fc1fd1 (Mastodon production candidate), 257 of 257 listed files identical, 48 of 48 hidden-file probes; no Discord v2 code in production | S-01-lineage-report.md |
| S-02 | Preserve-live matrix | AGENT | **NOT_RUN** | matrix written with the code path, route or cron, tests and proof for every live capability, plus the capability levels Discord will show; it flips to VERIFIED when the full CI on the frozen head is green, beca… | S-02-preserve-live-matrix.md; scripts/rc_superset_proof.py |
| S-03 | Build the RC branch | AGENT | **VERIFIED** | candidate branch built as a merge of the live line c5fc1fd1 and the Discord line b960bfe0 plus the launch controls; 11 conflicted files resolved as unions | branch claude/discord-launch-rc-20261023; merge commit d4572f68 message lists every resolution |
| S-04 | Superset proof | AGENT | **VERIFIED** | superset proof passes with 29 deliberate, explained rewrites; re-run at freeze | scripts/rc_superset_proof.py; tests/test_rc_superset_proof.py |
| S-05 | Migration ledger reconciliation | AGENT | **VERIFIED** | nothing to apply for Discord; migrations 108 to 112 are absent in production but also absent from the live build; retired Mastodon 131 to 133 absent everywhere | S-05-migration-reconciliation.md |
| S-06 | Exact-SHA CI green on the RC head | AGENT | **NOT_RUN** | draft PR #222 runs the pull-request workflows; the dispatched ones (library, agent-ui, qualification) are re-run on every new head. Four inherited failures found and fixed on the candidate: the offline secret s… | https://github.com/dev-james0723/PostRiff/pull/222 |
| S-07 | Dependency and secret hygiene | AGENT | **NOT_RUN** | npm audit 0 vulnerabilities and pip-audit clean at the candidate head (before: 2 critical + 1 high in next 16.3.8 and @sentry/nextjs 10.74.0, and 4 advisories in pypdf 6.20.1; the same lockfile and pin are live… | commit 29bc8ab2 (pypdf, Mastodon opt-in); commit cd0ff8d0 (next, @sentry/nextjs) |
| S-08 | Freeze the RC | AGENT | **NOT_RUN** | not frozen: CI findings, H-08 wording approval and the cap/legal changes still move the head |  |
| G-01 | Fail-closed workspace gate for Discord | AGENT | **NOT_RUN** | implemented and passing locally; awaiting exact-SHA CI on the frozen head. Enforced at connect START and in the catalog; deliberately not at the callback, destinations or publish (would strand a consented insta… | src/postriff_phase2/discord/launch_gate.py; tests/test_discord_launch_gate.py (48 tests) |
| G-02 | Global server cap guard | AGENT | **NOT_RUN** | implemented and passing locally; awaiting exact-SHA CI on the frozen head. Counts every distinct bot-install server including revoked grants (a disconnect leaves the bot in the server) plus installs in flight, … | launch_gate.py; tests: ReserveCapacity, StartCapacity, test_discord_launch_hardening.py |
| G-03 | Truthful gate and capability copy | AGENT | **NOT_RUN** | partial: closed, full, busy, unavailable and late-post wording shipped in three languages, now at every screen that can receive the four codes (connect, server list, destination picker, verify, engagement) and … | web/src/lib/channels/discord-copy.json; web/src/lib/channels/discord-refusal.ts |
| G-04 | Kill-switch drill | AGENT | **NOT_RUN** | implemented and passing locally; awaiting exact-SHA CI on the frozen head. Kill switch composes with the gate (KillSwitch tests). On Vercel the switch needs a new build; the runbook uses a third twin and a data… | tests/test_discord_launch_gate.py KillSwitch; RUNBOOK-INCIDENT.md |
| G-05 | Widen without redeploy | AGENT | **NOT_RUN** | implemented and passing locally; awaiting exact-SHA CI on the frozen head. Correction to the item: env changes reach new builds only, so widening is done by promoting a pre-built twin, not by an env edit | tests/test_discord_launch_gate.py WidenWithoutRedeploy; RUNBOOK-LAUNCH.md section 0 |
| R-01 | Rate policy: generate, validate, calendar | AGENT+APPROVAL | **NOT_RUN** | policy tool and 22 tests pass locally; applying the value is AUTH-4. Policy last used by the coordinator expires between 10-23 18:47Z and 10-24 18:47Z | scripts/discord_rate_policy.py; tests/test_discord_rate_policy_tool.py |
| R-03 | 429 and ban handling | AGENT | **NOT_RUN** | implemented and passing locally; awaiting exact-SHA CI on the frozen head (15 tests: Cloudflare-style 429, scopes, hints, held routes, operator hold) | tests/test_discord_ban_handling.py |
| R-05 | Worker throughput | AGENT | **NOT_RUN** | decision recorded with the budget arithmetic; per-step latency not measured; late-post note in the schedule dialog | MEASUREMENTS.md; tests/test_discord_worker_budget.py |
| C-01 | Env matrix for the RC | AGENT | **VERIFIED** | matrix written; the dangerous values live only on the build commands | C-01-env-matrix.md |
| C-02 | Names-only readback of production env | AGENT | **BLOCKED_EXTERNAL** | incomplete: the tool returned 100 of 271 production env records and only 48 names; no Discord variable exists in the readable window (created 10-14 or later); the older 223 are unreadable. Needs the owner's nam… | private audit (not in the repository); APPROVAL-PACKET-1.md row 8 |
| C-03 | Apply non-secret env changes in one batch | AGENT+APPROVAL | **NOT_RUN** | awaiting AUTH-3 and AUTH-4 | APPROVAL-PACKET-1.md rows 1 to 3 |
| C-04 | Cron lanes | AGENT | **NOT_RUN** | the candidate keeps the only live cron (/api/cron/worker every minute), proven by the superset proof; the post-promotion check is not done | scripts/rc_superset_proof.py crons check |
| C-05 | OAuth start URL audit (read-only) | AGENT | **NOT_RUN** | needs the staged build |  |
| M-02 | RLS, FORCE RLS and grants on Discord tables | AGENT | **VERIFIED** | RLS and FORCE RLS on, anon has no grants, authenticated has no access to the Discord, credential or OAuth tables, service_role grants as migrations 124 to 131 give | private audit (not in the repository); monitoring.sql planned against the schema |
| M-03 | Backup and restore point | AGENT | **BLOCKED_EXTERNAL** | cannot be determined with the tools available: Pro plan means daily backups kept 7 days; PITR is a paid add-on; WAL archiving is running. The owner must read the dashboard | APPROVAL-PACKET-1.md row 11 |
| Q-01 | Pre-flight for the build | AGENT | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| Q-02 | Build ONE staged RC | AGENT+APPROVAL | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| Q-03 | Provenance of the deployed RC | AGENT | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| Q-04 | Smoke on the RC URL | AGENT | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| Q-05 | Hosted tenant-isolation probe | AGENT | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| Q-06 | Rollback target | AGENT | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| Q-07 | Promotion packet | AGENT | **NOT_RUN** | waits for the frozen SHA and the owner | RUNBOOK-LAUNCH.md |
| X-01 | Dark promotion (gate closed except testers and grandfathered workspaces) | AGENT+APPROVAL | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| X-02 | Real OAuth and bot install (PRD A08) | HUMAN | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| X-03 | One real send and read-back (PRD A09) | HUMAN | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| X-04 | Unattended schedule and cancel (PRD A10) | HUMAN | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| X-05 | Revoke and reconnect | HUMAN | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| X-07 | Release receipt (PRD A13) | AGENT | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| X-09 | Post-acceptance exposure decision | AGENT | **NOT_RUN** | waits for the dark promotion and the tester session | RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md |
| P-01 | Privacy notice and terms | AGENT | **VERIFIED** | wording drafted and committed on the RC; approval is H-08 | P-01-privacy-terms-diff.md |
| O-01 | Monitoring queries and thresholds (aggregate-only) | AGENT | **VERIFIED** | eleven aggregate-only monitors with thresholds; every statement planned against the production schema with EXPLAIN (no rows read) | monitoring.sql |
| O-02 | Abort triggers and pre-authorised actions | AGENT | **VERIFIED** | trigger table and abort ladder written for Vercel semantics; AUTH-7 rewritten in the packet | RUNBOOK-INCIDENT.md; APPROVAL-PACKET-1.md row 12 |
| F-02 | Fallback (NO-GO) | AGENT | **NOT_RUN** | the fallback is that D1 (gate closed) stays promoted; the customer wording exists; reschedule criteria not written | RUNBOOK-LAUNCH.md section 2; RUNBOOK-INCIDENT.md section 5 |
| F-03 | Abort / rollback decision tree after opening | AGENT | **VERIFIED** | abort and rollback ladder with speeds and undo steps | RUNBOOK-INCIDENT.md section 1 |

## What was found that the owner should know

- The live site has no Discord v2 code; it was overwritten by other lanes' deployments on 10-21 (`S-01-lineage-report.md`). The LinkedIn lane (#218) is not in the live build either.
- The offline secret scan fails on the live commit itself (174 digests in Mastodon fixtures); the candidate reviews them with reasons. The Mastodon lane will meet the same conflict.
- Vercel applies env changes to new builds only, so "close the gate in seconds" needs a pre-built twin (`RUNBOOK-LAUNCH.md` section 0). This is a deviation from AUTH-1 as written and is asked for explicitly in the packet.
- The server cap now counts revoked grants because a disconnect leaves the shared bot in the server; it can still undercount Discord's own number (deleted workspaces), so the Portal's figure must be compared before opening.
- The public privacy page and the deletion promise do not describe Discord, and for Discord the claim "revoked where supported" is untrue on this line. Drafted wording is in `P-01-privacy-terms-diff.md`.
- The Discord rate policy last used by the coordinator expires between 10-23 18:47Z and 10-24 18:47Z.
- **Security, not Discord-specific:** the live site runs Next.js 16.3.8 and @sentry/nextjs 10.74.0. Advisories published 2026-10-14 (Next.js: two critical remote-code-execution findings and one high denial-of-service; patched in 16.4.1) and 2026-09-24 (Sentry tunnel-route middleware bypass; patched in 10.75.2) reached the advisory database on 2026-10-22. From the app's own source the stated preconditions look unmet for three of the four (no `use cache`, no Server Actions, and the build script has no `--webpack` flag while the Sentry advisory needs a webpack build) and unclear for the image-optimizer one, so this is [Likely] not exploitable today, not proven safe. The candidate carries the patch (next 16.4.2, @sentry/nextjs 10.76.2, `npm audit` 0). The same lockfile is on every other branch, so their `npm audit` gates fail from today too (`S-07`).
- A real-PostgreSQL race test now shows the server cap holds under concurrent starts (`X-08`).
- **An independent review of the gate and the cap found two serious defects that are now fixed with tests:** a refusal by the shared request coordinator (the break-glass hold, an expired rate policy, an open circuit) revoked a person's Discord identity and every server installed through it when their login token had to be refreshed, and the original connect flow (active if a v2 flag is mistyped) added the bot without taking a cap slot. Four smaller defects and four screens that still showed operator wording are fixed too (`G-01`, `G-02`, `G-03`).
- Two more CI gates failed on any tree that contains the Mastodon lane and are fixed here: the generic PostgreSQL step (the Mastodon fixtures need an explicit opt-in) and `pip-audit` (pypdf, bumped to 6.21.1, a deliberate deviation from the instruction to keep 6.20.1).
- The cap cannot see servers the bot joins without a stored row; the Portal count must be compared with `monitoring.sql` Q9 and Q12 before opening and every 2 hours on day 1 (`RUNBOOK-LAUNCH.md` section 6).

## Not done on purpose

No deployment, promotion, env change, migration, Portal action or Discord request. No secret was read. No other lane's branch, session or worktree was touched.
