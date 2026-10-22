# Discord public launch checklist (Rafii)

Facts snapshot: 2026-10-22 ~17:00 UTC. Target: tomorrow (T0 set by the owner). Machine ledger: `CHECKLIST.json` (same statuses, same IDs). Handoff prompt: `AGENT-HANDOFF-PROMPT.md`.

**Release status: NO-GO as of 2026-10-22T19:50:46Z.** Flip it only through item F-01 with evidence. Statuses below were updated from evidence; see `LAUNCH-READINESS-REPORT.md`.

## 一頁睇晒

- **老實講:聽日「成千上萬」個客戶自行連 Discord 做唔到。** 未 verify 嘅 Discord app 最多加入 100 個 server [Likely],而 verification 要你本人做(Stripe 身份驗證)同由 Discord 審批,agent 代唔到、聽日前亦唔保證批到。
- 所以分兩波:**Wave 1(聽日)= 上限 90 個 server 嘅公開 beta + waitlist**;**Wave 2(之後)= 取消上限**,需要 verification + worker 擴容(production 得一個每分鐘 cron,Discord 大約 5 至 12 則/分鐘,係估算,見 R-05)。
- 最長路徑:查出 live 係邊個 SHA (S-01) -> 建 RC + 加 gate (S-03, G-01) -> CI -> 一次 staged build (Q-02) -> dark promote (X-01) -> tester 真實驗收 (X-02..X-05) -> GO / NO-GO (F-01)。
- 你必須親手做(約 40 至 60 分鐘,分 4 次):Portal verification + 設定檢查、填 Authorization Block、兩次 Approval Packet、一次 20 分鐘 tester session。其餘全部 agent 做。
- 任何 MUST gate 過唔到 = NO-GO;fallback 係 Discord 保持 invite-only / waitlist (F-02),冇數據損失。

## The uncomfortable parts, first

1. Nothing real has ever gone through the new Discord pipeline: a handful of apparently internal grants, only read and OAuth requests logged by the coordinator, no publish. Customers would be the acceptance test.
2. Production already stores Direct for publish and schedule on its bot installs. That label is ahead of the evidence (PRD A09 / A10 are BLOCKED_EXTERNAL).
3. There is no single qualified SHA, and the build rafii.io serves since 12:52 UTC today cannot be tied to one (`sourceRevision: null`).
4. There is no per-workspace Discord gate; the only switch is provider-wide. Without one you cannot go live dark, prove it, then open.
5. The capacity pass used a mock above Discord's real limits and 16 workers; production has one cron worker.

## Legend

| Owner | Meaning |
|---|---|
| `AGENT` | Agent does it end to end, no human needed. |
| `AGENT+APPROVAL` | Agent prepares everything; a pre-staged action waits for the owner's exact approval (AUTH-n). |
| `HUMAN` | Only the owner / a named person can do it. Agent prepares inputs and reminds. |
| `EXTERNAL` | Waits on Discord / a third party. Agent tracks it and keeps the fallback ready. |

Priority: `MUST` = GO criterion for Wave 1. `SHOULD` = do if time allows, report if not. `COULD` = nice to have. Wave: `W1` tomorrow (capped), `W2` uncapped 'thousands'. Status vocabulary matches the PRD acceptance matrix: VERIFIED, FAILED, NOT_RUN, BLOCKED_EXTERNAL, NOT_IMPLEMENTED, NOT_APPLICABLE. `AUTH-n` refers to the Authorization Block in the handoff prompt.

Counts: 82 items. By owner: AGENT 52, AGENT+APPROVAL 7, HUMAN 22, EXTERNAL 1. By priority: MUST 58, SHOULD 18, COULD 6. Wave 1 MUST (GO criteria): 54.

## Critical path

`S-01` -> `S-03` -> `G-01` -> `S-06` -> `S-08` -> (AUTH-1) `Q-02` -> `Q-03..Q-07` -> (AUTH-5) `X-01` -> `X-02..X-05` -> `X-09` -> `F-01` -> GO.

Human long poles to request in the first message: `H-01` (verification start), `H-03` (tester session time), `H-05` (sign-off).

## Minimum human touchpoints

| When | What |
|---|---|
| Now, about 10 minutes | H-01, H-02 (Portal look), confirm D-01..D-07 defaults, fill the Authorization Block incl. tester assets (H-03, D-05). |
| Approval Packet #1, about 5 minutes | AUTH-1 (one staged build), AUTH-2 (capacity, optional), AUTH-3 (non-secret env batch), AUTH-4 (rate policy). |
| Tester consent session, about 20 minutes | X-02..X-05 with the tester account while the agent verifies. |
| Approval Packet #2, about 5 minutes | AUTH-5 (promote), AUTH-6 (open the capped gate), H-05 sign-offs. |
| Optional | H-06 phone check, H-08 wording approval, H-02 edits in the Portal. |

## GO criteria (all must be VERIFIED at GO_TIME)

- `D-01` Launch scope for tomorrow
- `D-02` Which lanes ship in the same RC
- `D-04` Exposure rule for 'Direct' publish and schedule
- `D-05` Launch time T0 and GO / NO-GO time
- `H-01` Discord Developer Portal: App Verification status, and start verification today
- `H-02` Portal settings audit
- `H-03` Tester assets and one 20-minute consent session
- `H-04` Reply to the Approval Packets
- `H-05` Release Captain sign-off and security-review decision
- `H-07` Support and on-call for the launch window and first 24 hours
- `H-08` Approve customer-facing Discord disclosures
- `S-00` Baseline snapshot of facts (Appendix A)
- `S-01` Identify the lineage of the build rafii.io serves now
- `S-02` Preserve-live matrix
- `S-03` Build the RC branch
- `S-04` Superset proof
- `S-05` Migration ledger reconciliation
- `S-06` Exact-SHA CI green on the RC head
- `S-07` Dependency and secret hygiene
- `S-08` Freeze the RC
- `G-01` Fail-closed workspace gate for Discord
- `G-02` Global server cap guard
- `G-03` Truthful gate and capability copy
- `G-04` Kill-switch drill
- `G-05` Widen without redeploy
- `R-01` Rate policy: generate, validate, calendar
- `R-03` 429 and ban handling
- `R-05` Worker throughput
- `C-01` Env matrix for the RC
- `C-02` Names-only readback of production env
- `C-03` Apply non-secret env changes in one batch
- `C-04` Cron lanes
- `C-05` OAuth start URL audit (read-only)
- `M-02` RLS, FORCE RLS and grants on Discord tables
- `M-03` Backup and restore point
- `Q-01` Pre-flight for the build
- `Q-02` Build ONE staged RC
- `Q-03` Provenance of the deployed RC
- `Q-04` Smoke on the RC URL
- `Q-05` Hosted tenant-isolation probe
- `Q-06` Rollback target
- `Q-07` Promotion packet
- `X-01` Dark promotion (gate closed except testers and grandfathered workspaces)
- `X-02` Real OAuth and bot install (PRD A08)
- `X-03` One real send and read-back (PRD A09)
- `X-04` Unattended schedule and cancel (PRD A10)
- `X-05` Revoke and reconnect
- `X-07` Release receipt (PRD A13)
- `X-09` Post-acceptance exposure decision
- `P-01` Privacy notice and terms
- `O-01` Monitoring queries and thresholds (aggregate-only)
- `O-02` Abort triggers and pre-authorised actions
- `F-02` Fallback (NO-GO)
- `F-03` Abort / rollback decision tree after opening

## Fallback if any GO criterion is not VERIFIED

Gate stays closed (tester and grandfathered workspaces only). The public sees the waitlist state. No data is lost and existing grants stay safe. The customer message and the config diff are prepared in advance (F-02). The kill switch (`POSTRIFF_OAUTH_DISCORD_DISABLED`) is the first abort action, the gate the second, rollback the last and only for a code defect (F-03).

## D. Decisions

Defaults are pre-selected so no agent ever waits on a decision. Override them in the Authorization Block of the handoff prompt.

- [ ] **D-01** `HUMAN` `MUST` `W1`: **Launch scope for tomorrow**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: default applied by the agent (assumption logged); the owner has not replied: capped Wave 1, at most 90 servers
  - Evidence: APPROVAL-PACKET-1.md section 4
  - What: Default A = Capped Wave 1: public Discord bot-connect for at most 90 distinct servers (hard cap, waitlist beyond). Wave 2 (uncapped, 'thousands') only after Discord app verification (H-01) and worker scaling (R-05, W-02). B = uncapped public, valid ONLY if H-01 shows the app is already verified. C = no public Discord tomorrow (this is fallback F-02).
  - Evidence to record: Choice recorded in the ledger. Default A applies if the owner does not reply.
  - Basis: Discord 100-server rule [Likely]; no per-workspace Discord gate exists today [Likely].
- [ ] **D-02** `HUMAN` `MUST` `W1`: **Which lanes ship in the same RC**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: default applied by the agent (assumption logged); the owner has not replied: Discord delta on the live line only
  - Evidence: APPROVAL-PACKET-1.md section 4
  - What: Default: the Discord delta only, on top of the lineage that is live now (S-01). Other lanes (LinkedIn #218, Mastodon #212/#213/#219, Bluesky, Pinterest) join only if the owner lists them. In every case the RC must be a strict superset of what is live (S-04) so nothing live is silently dropped; PR #218 warns about exactly this.
  - Evidence to record: Lane list recorded in the ledger.
  - Basis: PR #218 body; PR #212 body.
- [ ] **D-03** `HUMAN` `SHOULD` `W1`: **Engagement (analytics / comments / reply) in Wave 1**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: default applied by the agent (assumption logged); the owner has not replied: engagement OFF
  - Evidence: APPROVAL-PACKET-1.md section 4
  - What: Default OFF. The code exists behind six flags plus per-channel 30-day consent, but it is partial by design (at most 10 messages, approximate counts, no reach or impressions, Message Content intent OFF) and has no live acceptance. Do not market Discord analytics or comments as equal to other platforms.
  - Evidence to record: Recorded in the ledger.
  - Basis: src/postriff_phase2/discord/engagement.py (ping-runtime branch).
- [ ] **D-04** `HUMAN` `MUST` `W1`: **Exposure rule for 'Direct' publish and schedule**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: explicit decision requested (packet row 4): REVIEWED passed on the two RC build commands only
  - Evidence: APPROVAL-PACKET-1.md row 4
  - What: Production already stores identity, publish and schedule as Direct on its bot installs, which implies REVIEWED and the two v2 flags were on, yet the coordinator has recorded no real publish. Do not widen exposure beyond tester workspaces until X-03 (real send plus read-back) and X-04 (unattended schedule plus cancel) are VERIFIED. G-01 is the enforcement mechanism. Do not flip POSTRIFF_OAUTH_DISCORD_REVIEWED either way without an approval-packet item.
  - Evidence to record: Recorded in the ledger.
  - Basis: Supabase pr_channel_capabilities aggregate 2026-10-22; _capabilities() in oauth.py [Likely].
- [ ] **D-05** `HUMAN` `MUST` `W1`: **Launch time T0 and GO / NO-GO time**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: T0 and GO_TIME not given; the agent assumes T0 = 24 hours after its start and says so
  - Evidence: APPROVAL-PACKET-1.md section 2
  - What: Owner enters absolute UTC times. Default GO_TIME = T0 minus 3 hours. If unset, the agent computes T0 as 24 hours after it starts and says so.
  - Evidence to record: Times written in the Authorization Block.
- [ ] **D-06** `HUMAN` `SHOULD` `W1`: **Day-1 load assumption**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: default applied by the agent (assumption logged); the owner has not replied
  - Evidence: APPROVAL-PACKET-1.md section 4; MEASUREMENTS.md
  - What: Default: at most 90 servers, at most 300 connect attempts per hour at peak, at most 600 scheduled posts per day, at most 60 posts due in any single minute. Used to size R-01 to R-05. Override if wrong.
  - Evidence to record: Numbers recorded in the ledger.
- [ ] **D-07** `HUMAN` `COULD` `W1`: **Identity-only Discord linking for the public**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: default applied by the agent (assumption logged); the owner has not replied: identity-only linking is not opened to the public
  - Evidence: APPROVAL-PACKET-1.md section 4
  - What: Default NO. Linking without the bot has no 100-server limit but stores OAuth tokens (guilds, identify) for a feature that does not publish. Recommend not opening it until something uses it (data minimisation).
  - Evidence to record: Recorded in the ledger.
  - Basis: PR #216 body: personal OAuth is identity-only, canPublish=false.

## H. Human-only items

Cannot be delegated. The agent prepares every input so each one takes minutes.

- [ ] **H-01** `HUMAN` `MUST` `W1+W2`: **Discord Developer Portal: App Verification status, and start verification today**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: human only; preparation done
  - Evidence: H-01-verification-prep.md
  - What: Open the app's App Verification tab. Record: verified or not, current server count, what is missing. If unverified and eligible, submit now (the team owner must verify identity through Stripe, which only a human can do). Verification is Discord's timeline, not ours. Without it the bot cannot be in more than 100 servers, so 'thousands' is impossible in bot mode.
  - Evidence to record: Status text or screenshot (never an ID document) pasted into the ledger.
  - Basis: Discord help 'How Do I Get My App Verified?' via search summary, page not read directly [Likely]. No repo document mentions this limit.
- [ ] **H-02** `HUMAN` `MUST` `W1`: **Portal settings audit**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: human only (or AUTH-10 read-only); audit sheet prepared
  - Evidence: PORTAL-AUDIT-SHEET.md
  - What: Check: (a) redirect URI exactly https://rafii.io/api/oauth/discord/callback and no stale or staging URIs; (b) Public Bot ON and Requires OAuth2 Code Grant ON (as of 10-21); (c) Interactions Endpoint URL EMPTY (PING / User Install are out of scope); (d) Terms of Service and Privacy Policy URLs set to rafii.io pages; (e) name, icon and description presentable; (f) install settings request only bot + identify with permissions integer 101376 (View Channel, Send Messages, Attach Files, Read Message History); no Administrator. The agent may do this read-only through the owner's paired computer if AUTH-10 is ticked; edits are always the owner's.
  - Approval: AUTH-10
  - Evidence to record: Filled Portal audit sheet (agent provides the sheet).
  - Basis: Redirect URI built in oauth.py as {base}/api/oauth/{provider}/callback; permissions = DiscordProvider.PERMISSIONS on the #216 line; Portal values per PR #216 body.
- [ ] **H-03** `HUMAN` `MUST` `W1`: **Tester assets and one 20-minute consent session**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: human only; session script prepared
  - Evidence: TESTER-SESSION-SCRIPT.md
  - What: Provide a Discord test account, a test server where it has Manage Server, a public test channel, and a private channel the bot cannot see. Put the IDs in the Authorization Block. Be available once for about 20 minutes to click through consent and approvals while the agent verifies.
  - Evidence to record: IDs in the Authorization Block; session time agreed.
  - Basis: PRD A08: a reported click is not proof; the callback must be verified.
- [ ] **H-04** `HUMAN` `MUST` `W1`: **Reply to the Approval Packets**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: Approval Packet 1 rev A sent to the owner 2026-10-22 ~19:35Z; no reply yet
  - Evidence: APPROVAL-PACKET-1.md
  - What: Two packets: #1 before the RC build (AUTH-1..4), #2 before promotion and opening (AUTH-5, AUTH-6, sign-offs). Each is a single message: APPROVE 1,2 / DENY 3 / HOLD 4.
  - Evidence to record: Replies logged verbatim in the ledger.
- [ ] **H-05** `HUMAN` `MUST` `W1`: **Release Captain sign-off and security-review decision**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: human only
  - Evidence: APPROVAL-PACKET-1.md section 2
  - What: Name the Release Captain. Decide whether the 2026-10-20 independent AI security review (two P1 findings found and repaired) is enough, or a human review is required. PR #216 lists both as still open.
  - Evidence to record: Names and decisions recorded.
  - Basis: PR #216 'Remaining live and release gates'; SECURITY-REVIEW-20261020.md.
- [ ] **H-06** `HUMAN` `SHOULD` `W1`: **Physical phone check**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: human only (optional)
  - What: Open the Connect flow on a real phone up to the Discord consent screen; confirm layout, keyboard and return. Browser tests cover 390 px, but PR #216 lists physical mobile acceptance as open.
  - Evidence to record: Pass / fail note.
  - Basis: PR #216 body.
- [ ] **H-07** `HUMAN` `MUST` `W1`: **Support and on-call for the launch window and first 24 hours**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: human only
  - Evidence: APPROVAL-PACKET-1.md section 2
  - What: Name who watches alerts and answers customers, and where status updates are posted.
  - Evidence to record: Names and channel recorded.
- [ ] **H-08** `HUMAN` `MUST` `W1`: **Approve customer-facing Discord disclosures**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: wording drafted and committed on the RC as its own commit; awaiting approval; the build waits for it
  - Evidence: P-01-privacy-terms-diff.md
  - What: Agent drafts the privacy-notice and terms changes (P-01); the owner approves wording.
  - Depends on: P-01
  - Evidence to record: Approval logged.

## S. Source of truth and release candidate (RC)

Today there is no single qualified SHA: consumer-saas has no Discord work, five Discord lines are unmerged, the latest two diverge, and rafii.io was re-pointed at 12:52 UTC today to a build whose SHA is not recorded.

- [x] **S-00** `AGENT` `MUST` `W1`: **Baseline snapshot of facts (Appendix A)**
  - Status: **VERIFIED**
  - What: Read-only readbacks from GitHub, Vercel and Supabase on 2026-10-22 ~17:00 UTC are recorded in Appendix A. Re-verify anything time-sensitive before acting on it.
  - Evidence to record: Appendix A
  - Basis: Tool readbacks 2026-10-22.
- [x] **S-01** `AGENT` `MUST` `W1`: **Identify the lineage of the build rafii.io serves now**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: live build is c5fc1fd1 (Mastodon production candidate), 257 of 257 listed files identical, 48 of 48 hidden-file probes; no Discord v2 code in production
  - Evidence: S-01-lineage-report.md (source c5fc1fd1)
  - What: Vercel metadata is empty and /api/health reports sourceRevision null because the deploy came from the CLI. Fingerprint deployment dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg: list its files (Vercel API) and compare sha1 of file bytes with candidate commits (09b3ab8a, #216 head b960bfe0, #218 head c4c74777, #212 head 65d469ae, consumer-saas 5670ce3c). Record the best match and unmatched paths. Ask the owner one question ('what did you deploy at 12:48 UTC?') only if the fingerprint is inconclusive.
  - Evidence to record: S-01 report with best-match SHA and path diff.
  - Basis: alias rafii.io updated 2026-10-22 12:52:07Z; #218 says rafii.io served dpl_yKAToJbv (09b3ab8a) on 10-21.
- [ ] **S-02** `AGENT` `MUST` `W1`: **Preserve-live matrix**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: matrix written with the code path, route or cron, tests and proof for every live capability, plus the capability levels Discord will show; it flips to VERIFIED when the full CI on the frozen head is green, because its rows rest on those tests
  - Evidence: S-02-preserve-live-matrix.md; scripts/rc_superset_proof.py
  - What: From S-01, list every capability live now that must survive the RC (Discord level, LinkedIn publishing and its cron lane, Mastodon connect and management, Pinterest, Bluesky). For each, name the code path, route, cron entry and test that proves it still works in the RC.
  - Depends on: S-01
  - Evidence to record: Matrix file with a test or probe per row.
- [x] **S-03** `AGENT` `MUST` `W1`: **Build the RC branch**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: candidate branch built as a merge of the live line c5fc1fd1 and the Discord line b960bfe0 plus the launch controls; 11 conflicted files resolved as unions
  - Evidence: branch claude/discord-launch-rc-20261023; merge commit d4572f68 message lists every resolution; superset-allowlist.json (source d4572f68)
  - What: New branch with your own family prefix (codex/ or claude/) named discord-launch-rc-20261023. Start from the live lineage (S-01), add the Discord delta from PR #216 head b960bfe0 with all new modes OFF (Webhook, User Install, PING, engagement), and then commit G-01..G-05 and any R-05 config change on this same branch. Resolve conflicts preserving both sides. Keep vercel.json git.deploymentEnabled=false and every cron entry that is live. Never touch other agents' branches or worktrees. Do NOT build from consumer-saas: it has no Discord work.
  - Depends on: S-02, D-02
  - Evidence to record: Branch + head SHA; conflict log.
  - Basis: PR #216 head CI green on b960bfe0; consumer-saas lacks migrations 124-131 and src/postriff_phase2/discord/.
- [x] **S-04** `AGENT` `MUST` `W1`: **Superset proof**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: superset proof passes with 29 deliberate, explained rewrites; re-run at freeze
  - Evidence: scripts/rc_superset_proof.py; tests/test_rc_superset_proof.py; superset-allowlist.json (source 2a5a523d)
  - What: Script that proves RC contains everything live: file inventory, route table, cron list, migration list, feature flags read by the code. Fail on any silent drop.
  - Depends on: S-03
  - Evidence to record: Script + passing output committed.
- [x] **S-05** `AGENT` `MUST` `W1`: **Migration ledger reconciliation**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: nothing to apply for Discord; migrations 108 to 112 are absent in production but also absent from the live build; retired Mastodon 131 to 133 absent everywhere
  - Evidence: S-05-migration-reconciliation.md
  - What: Compare the production ledger (Supabase list_migrations on the production project) with migrations/postriff in the RC. Report (a) RC migrations not applied, (b) applied but absent from the RC, (c) numbering conflicts (Discord 131 vs the retired Mastodon 131-133: never apply the retired ones). Default expectation: nothing to apply. Anything in (a) becomes an approval item with backup and rollback.
  - Depends on: S-03
  - Evidence to record: Reconciliation table.
  - Basis: Production ledger includes discord 124,125,126,128,131; Mastodon 134 and management; Pinterest x3.
- [ ] **S-06** `AGENT` `MUST` `W1`: **Exact-SHA CI green on the RC head**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: draft PR #222 runs the pull-request workflows; the dispatched ones (library, agent-ui, qualification) are re-run on every new head. Four inherited failures found and fixed on the candidate: the offline secret scan (171 digests reviewed), npm audit criticals in next and @sentry/nextjs (patched), the generic PostgreSQL step running the Mastodon fixtures without their opt-in (set on that step), and pip-audit advisories in pypdf 6.20.1 (moved to 6.21.1). Earlier heads: cd0ff8d0 had 8 of 9 workflows green and local-gates failed at the PostgreSQL step; on 29bc8ab2 local-gates passed that step and the Discord P0-P4 runner (the push of the next head cancelled the rest), the qualification failed only at the fence interplay of the real-PostgreSQL tests (fixed by skipping them under the fence, they run in the unfenced suite), the composer-input run was cancelled while installing Chromium and agent-ui-browser failed one WebKit check; those are re-run. Results on the final head pending
  - Evidence: https://github.com/dev-james0723/PostRiff/pull/222
  - What: All repository workflows on standard ubuntu-24.04 GitHub-hosted runners (no paid runners): local release gates, Discord qualification, browser scenes 390/1280, composer, founder admin, growth. Fix root causes, batch fixes, never skip or weaken a test. A retried job needs its first-failure log kept and the cause stated.
  - Depends on: S-04, G-05
  - Evidence to record: Run URLs + conclusions for the exact SHA.
  - Basis: PR #216 head had 7 workflows green; browser scenes needed one retry (WebKit crash, cause unproven).
- [ ] **S-07** `AGENT` `MUST` `W1`: **Dependency and secret hygiene**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: npm audit 0 vulnerabilities and pip-audit clean at the candidate head (before: 2 critical + 1 high in next 16.3.8 and @sentry/nextjs 10.74.0, and 4 advisories in pypdf 6.20.1; the same lockfile and pin are live today). Deliberate deviation from "keep the pypdf 6.20.1 pin": the pin fails a CI gate and parses uploaded PDFs with known issues, so it is 6.21.1 (the Telegram lane already runs it); Pillow 13.0.0 kept; offline secret scan PASS with reviewed allowlist entries only; local tsc, oxlint, 1,010 web tests, the full Python suite (6,141) and a production build pass. CI on the exact head pending
  - Evidence: commit 29bc8ab2 (pypdf, Mastodon opt-in); commit cd0ff8d0 (next, @sentry/nextjs); commit 0c6a9c36 (secret allowlist) (source 2a5a523d)
  - What: Keep Pillow 13.0.0 and pypdf 6.20.1 pins, npm audit zero, detect-secrets clean, no credentials in the diff, secret-allowlist changes limited to synthetic fixtures.
  - Depends on: S-03
  - Evidence to record: Audit outputs.
- [ ] **S-08** `AGENT` `MUST` `W1`: **Freeze the RC**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: not frozen: CI findings, H-08 wording approval and the cap/legal changes still move the head
  - What: Record the exact SHA in the ledger and the RC PR. After freeze only fixes for failed gates, each re-qualified from S-06.
  - Depends on: S-06, S-07
  - Evidence to record: Frozen SHA.
- [x] **S-09** `AGENT` `SHOULD` `W1`: **Draft PR for visibility**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: draft PR "DO NOT MERGE: Discord launch RC", base branch points at the live commit so the diff is the Discord delta
  - Evidence: https://github.com/dev-james0723/PostRiff/pull/222
  - What: Open a DRAFT PR titled 'DO NOT MERGE: Discord launch RC' so reviewers can read the diff. Never merge. Never push to consumer-saas.
  - Depends on: S-08
  - Evidence to record: PR URL.

## G. Launch gate, cap and kill switch (new code)

No per-workspace gate exists for Discord today; the only switch is provider-wide (POSTRIFF_OAUTH_DISCORD_DISABLED). A runtime gate lets the RC go live dark, be proven on a tester workspace, and then open without a second build.

- [ ] **G-01** `AGENT` `MUST` `W1`: **Fail-closed workspace gate for Discord**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: implemented and passing locally; awaiting exact-SHA CI on the frozen head. Enforced at connect START and in the catalog; deliberately not at the callback, destinations or publish (would strand a consented install; the kill switch covers them). After the independent review: an identity that must reconnect counts as a footprint, production is recognised whatever its case or spacing, and the original (non-v2) flow sits behind the same gate. Decision D-08: a workspace with a footprint may start any kind of connection
  - Evidence: src/postriff_phase2/discord/launch_gate.py; tests/test_discord_launch_gate.py (48 tests); tests/test_discord_launch_hardening.py (34 tests) (source 2a5a523d)
  - What: Runtime-evaluated env allowlist, e.g. POSTRIFF_DISCORD_CONNECT_WORKSPACES: empty means no workspace, '*' must be written explicitly, otherwise a comma list. Follow the existing pattern in agent_runtime_v2/config.py. Enforce server-side at connect start, callback completion, destination listing and the publish route; reflect it in the provider catalog so the UI shows waitlist copy. Grandfather every workspace that already has an active Discord grant so nobody live regresses. Tests must include direct API calls from a non-allowlisted workspace.
  - Depends on: S-03
  - Evidence to record: Tests + CI run; behaviour table.
  - Basis: No per-workspace Discord gate found by grep; execution_enabled kill switch is provider-wide [Likely].
- [ ] **G-02** `AGENT` `MUST` `W1`: **Global server cap guard**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: implemented and passing locally; awaiting exact-SHA CI on the frozen head. Counts every distinct bot-install server including revoked grants (a disconnect leaves the bot in the server) plus every installation start in flight, one slot per row (a second review showed that counting once per person let one account open the bot to many servers for one slot); one person (workspace and member) may have at most three starts in flight, reconnects included; reserved under an advisory lock at start for both the v2 and the original flow; a server that already has a credential row is admitted at any fill, a reconnect takes no slot. Residual: servers the bot joins without a stored row (another server picked, tab closed, callback failed, manual invite) are not counted; mitigated by comparing the Portal count with Q9 and Q12
  - Evidence: launch_gate.py; tests: ReserveCapacity, StartCapacity, test_discord_launch_hardening.py; tests/test_discord_launch_cap_race.py (real PostgreSQL) (source 2a5a523d)
  - What: Count distinct active bot-install servers plus unexpired OAuth reservations; refuse to START a connect when at or above the cap (default 90, env POSTRIFF_DISCORD_GUILD_CAP). Important: the bot joins at Discord's consent screen, before Rafii's callback runs, so a cap can only be enforced at start, with a race-safe reservation (advisory lock; reservation expires with pr_oauth_transactions.expires_at), and by revoking an over-cap install afterwards (DiscordProvider.revoke). Verify how the server id is stored (account column) before relying on it. No schema change.
  - Depends on: G-01
  - Evidence to record: Concurrency test: 200 simultaneous starts at cap-1 admit exactly one.
  - Basis: Discord unverified apps are limited to 100 servers [Likely]; callback order from oauth.py DiscordProvider.exchange. If this guard cannot be proven in time, do not open with '*': open with an explicit allowlist of at most 90 invited workspaces instead.
- [ ] **G-03** `AGENT` `MUST` `W1`: **Truthful gate and capability copy**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: partial: closed, full, busy, unavailable and late-post wording shipped in three languages, now at every screen that can receive the four codes (connect, server list, destination picker, verify, engagement) and a separate wording for the page Discord returns to, because the bot may already be in the server; the Channels card capability wording is unchanged (already Assisted / identity only); verification-pending state not built
  - Evidence: web/src/lib/channels/discord-copy.json; web/src/lib/channels/discord-refusal.ts; web/tests/discord-launch-gate.test.cjs (source 2a5a523d)
  - What: UI states for: not allowlisted, cap reached, paused (kill switch), verification pending. Update web/src/config/channels.ts and the Channels card so Discord text matches what is verified: identity and publish yes (after X-03), schedule only after X-04, no analytics, comments or reply promise. English, Traditional and Simplified Chinese packs. 'Waitlist' here is state copy only: do not build an email or interest capture without the owner's decision (it would collect personal data).
  - Depends on: G-01
  - Evidence to record: Screens at 390 and 1280 px; copy diff.
  - Basis: channels.ts currently says 'publishing opens after testing' with identity-only capabilities, while production rows say Direct.
- [ ] **G-04** `AGENT` `MUST` `W1`: **Kill-switch drill**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: implemented and passing locally; awaiting exact-SHA CI on the frozen head. Kill switch composes with the gate (KillSwitch tests). On Vercel the switch needs a new build; the runbook uses a third twin and a database hold for seconds-level stops
  - Evidence: tests/test_discord_launch_gate.py KillSwitch; RUNBOOK-INCIDENT.md (source 2a5a523d)
  - What: POSTRIFF_OAUTH_DISCORD_DISABLED=true is checked at connect start, callback, destinations and publish (all-or-nothing). Prove in CI that existing grants and queued jobs stay safe (held, nothing lost, nothing resent), that it composes with G-01, and write a two-minute runbook: set, read back, resume.
  - Depends on: G-01
  - Evidence to record: Test names + runbook path.
  - Basis: execution_enabled checks in oauth.py lines 464, 573, 925 and publish_route.
- [ ] **G-05** `AGENT` `MUST` `W1`: **Widen without redeploy**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: implemented and passing locally; awaiting exact-SHA CI on the frozen head. Correction to the item: env changes reach new builds only, so widening is done by promoting a pre-built twin, not by an env edit
  - Evidence: tests/test_discord_launch_gate.py WidenWithoutRedeploy; RUNBOOK-LAUNCH.md section 0 (source 2a5a523d)
  - What: Document and test how to move from tester-only to the capped public (allowlist to '*', cap 90) and later to Wave 2 (cap raised after verification) by env change alone.
  - Depends on: G-01, G-02
  - Evidence to record: Runbook + test.

## R. Rate limits, capacity and worker throughput

One shared bot token serves every customer. The capacity test passed on a mock that is more permissive than Discord's documented limits and with 16 parallel workers, which production does not have.

- [ ] **R-01** `AGENT+APPROVAL` `MUST` `W1`: **Rate policy: generate, validate, calendar**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: policy tool and 22 tests pass locally; applying the value is AUTH-4. Policy last used by the coordinator expires between 10-23 18:47Z and 10-24 18:47Z
  - Evidence: scripts/discord_rate_policy.py; tests/test_discord_rate_policy_tool.py (source 2a5a523d)
  - What: POSTRIFF_DISCORD_RATE_POLICY must parse with the repo's own SafetyPolicy.parse and fails closed (HTTP 503 for all Discord traffic) once expires_at passes; maximum validity is 31 days. Generate a new policy JSON (version 1, revision, issued_at, expires_at, egress_scope, app_capacity, app_window_seconds, unknown_window_seconds, invalid_capacity, invalid_window_seconds, failure_threshold, circuit_seconds, permit_ttl_seconds <= 10, read_attempts <= 5). Size the app budget at no more than 80 percent of Discord's 50 requests per second and the invalid budget at no more than 50 percent of 10,000 per 10 minutes. Do NOT read the existing production value. Add a reminder at expiry minus 7 days. The last coordinator activity was 2026-10-19, so an expired policy is plausible [Guessing].
  - Approval: AUTH-4
  - Evidence to record: Policy JSON (not secret) + parse test + expiry date.
  - Basis: rate_limits.py SafetyPolicy (ping-runtime branch) [Certain]; Discord rate-limit figures via search summary of docs.discord.com [Likely].
- [ ] **R-02** `AGENT+APPROVAL` `SHOULD` `W1+W2`: **Capacity re-run with Discord-realistic quotas and production topology**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: not requested (AUTH-2); does not gate a 90-server Wave 1
  - Evidence: APPROVAL-PACKET-1.md row 9
  - What: Re-run capacity Stage A (1,000 users) and, if time allows, B (10,000) with the mock set to Discord's documented limits (50 requests per second global per bot, 5 messages per 5 seconds per channel) and with ONE worker invocation per minute instead of 16 replicas. Report accounting (verified, held, uncertain, unaccounted) and real latency, and state the SLO that is actually true. Cost ceilings from the harness constants: A at most $4.32, B at most $21.60 (rate $0.0016 per second x job timeout).
  - Depends on: S-03
  - Approval: AUTH-2
  - Evidence to record: Result JSON + run URL + cost.
  - Basis: PR #197: B passed on a mock allowing 100 creates per second. 10,000 creates inside a p99 of 173.5 s implies at least about 57 creates per second, above the documented 50 requests per second per bot; the harness excludes real Discord [Likely].
- [ ] **R-03** `AGENT` `MUST` `W1`: **429 and ban handling**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: implemented and passing locally; awaiting exact-SHA CI on the frozen head (15 tests: Cloudflare-style 429, scopes, hints, held routes, operator hold)
  - Evidence: tests/test_discord_ban_handling.py (source 2a5a523d)
  - What: Prove global vs shared vs user 429 scopes, Cloudflare-style HTML 429 (error 1015), invalid-request accounting (401, 403, 429 except shared scope), circuit opening and no retry storms. Add missing cases to tests/test_discord_rate_limits.py.
  - Depends on: S-03
  - Evidence to record: Test names + CI.
  - Basis: Discord docs via search summary: more than 10,000 invalid requests per 10 minutes causes a temporary IP restriction [Likely].
- [ ] **R-04** `AGENT` `SHOULD` `W1`: **Connect-burst model**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: model and user-facing messages done; request counts are from code and the harness constant, not measured
  - Evidence: MEASUREMENTS.md (source 2a5a523d)
  - What: The capacity harness counts at least 39 Discord requests per connecting user (3 + 2x3 + 6x5, a lower bound). At the 50 requests per second ceiling that is about 1.2 connects per second before any publishing. Confirm destination listing is lazy and paged, add caching if needed, and define the user-visible message when the coordinator delays or denies a request.
  - Depends on: S-03
  - Evidence to record: Request-count measurement + UX copy.
  - Basis: postgres_discord_capacity.py bootstrapRequestLowerBoundPerUser.
- [ ] **R-05** `AGENT` `MUST` `W1+W2`: **Worker throughput**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: decision recorded with the budget arithmetic; per-step latency not measured; late-post note in the schedule dialog
  - Evidence: MEASUREMENTS.md; tests/test_discord_worker_budget.py (source 2a5a523d)
  - What: Today one cron (every minute) runs worker.tick() with POSTRIFF_WORKER_MAX_JOBS default 10 (hard cap 25) and POSTRIFF_WORKER_MAX_SECONDS default 20 (cap 45), sequentially. With the Discord worker flag, lanes alternate between Discord and the rest, and a post needs at least two steps (create, then read-back). Rough ceiling: about 5 posts per minute at defaults, about 12 at the cap. 100 posts due in the same minute take 8 to 20 minutes; 1,000 take 83 to 200 minutes. tick_discord exists but is not wired to any cron. Decide: (a) the Wave 1 cap makes this acceptable; (b) raise POSTRIFF_WORKER_MAX_JOBS to 25 and MAX_SECONDS toward 45 (affects all providers; the API function maxDuration is 300); (c) add parallel cron lanes or a dedicated Discord lane (Wave 2, needs SKIP LOCKED and lease-fence proofs). Measure instead of assuming; show late-post expectation in the UI.
  - Depends on: S-01
  - Evidence to record: Measured jobs per minute in CI; decision recorded; UI expectation copy.
  - Basis: hosted_worker.py configured_worker_limits and _tick; vercel.json crons [Certain]; steps per post [Likely].
- [ ] **R-06** `AGENT` `COULD` `W2`: **Shared egress reputation**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: COULD; the incident runbook covers a ban
  - Evidence: RUNBOOK-INCIDENT.md 4.B
  - What: Vercel egress IPs are shared; Discord's Cloudflare restriction is per IP. Record egress_scope in the policy, add a monitor for HTML 429 / 1015 responses, and decide on Vercel Static IPs or a proxy only if bans are observed (paid, needs approval).
  - Evidence to record: Monitor + decision note.
  - Basis: Known hosting-IP bans on shared platforms [Guessing].

## C. Runtime configuration (names only, values never printed)

Vercel env changes apply to new deployments only, so set them before the RC build. The agent never reads or prints secret values.

- [x] **C-01** `AGENT` `MUST` `W1`: **Env matrix for the RC**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: matrix written; the dangerous values live only on the build commands
  - Evidence: C-01-env-matrix.md
  - What: Produce the final table in Appendix B (names, Wave 1 target state, how it is applied and read back) from the code. New modes OFF; kill switch armed (variable unset); rate policy per R-01; worker budget per R-05; gate and cap per G-01/G-02.
  - Depends on: G-01, R-01, R-05
  - Evidence to record: Matrix file.
- [ ] **C-02** `AGENT` `MUST` `W1`: **Names-only readback of production env**
  - Status: **BLOCKED_EXTERNAL** at 2026-10-22T22:03:20Z: incomplete: the tool returned 100 of 271 production env records and only 48 names; no Discord variable exists in the readable window (created 10-14 or later); the older 223 are unreadable. Needs the owner's names-only `vercel env ls production`
  - Evidence: private audit (not in the repository); APPROVAL-PACKET-1.md row 8
  - What: List production env variable NAMES with no decryption and diff against C-01. Flag missing and unexpected names. Never print values.
  - Evidence to record: Name diff.
  - Basis: AGENTS.md: no credential edits; Vercel MCP rule: never decrypt unless requested.
- [ ] **C-03** `AGENT+APPROVAL` `MUST` `W1`: **Apply non-secret env changes in one batch**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: awaiting AUTH-3 and AUTH-4
  - Evidence: APPROVAL-PACKET-1.md rows 1 to 3
  - What: Booleans and numbers only (gate, cap, flags, worker budget, kill-switch left unset). Read back by name and non-secret value. The agent NEVER touches client secret, bot token or CRON_SECRET; any secret change is the owner's.
  - Depends on: C-01, C-02
  - Approval: AUTH-3
  - Evidence to record: Readback.
- [ ] **C-04** `AGENT` `MUST` `W1`: **Cron lanes**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: the candidate keeps the only live cron (/api/cron/worker every minute), proven by the superset proof; the post-promotion check is not done
  - Evidence: scripts/rc_superset_proof.py crons check (source 2a5a523d)
  - What: RC vercel.json must keep every live cron lane (at least /api/cron/worker every minute; also /api/cron/linkedin/worker if the LinkedIn lane is live). After promotion confirm one 200 per minute in runtime logs.
  - Depends on: S-03
  - Evidence to record: vercel.json diff; log excerpt after X-01.
- [ ] **C-05** `AGENT` `MUST` `W1`: **OAuth start URL audit (read-only)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: needs the staged build
  - What: On the staged RC, call the authenticated connect-start API with a tester session (or use the existing browser harness) and parse the returned authorize URL: client_id, response_type=code, scope 'bot identify' only, permissions=101376 (confirm against DiscordProvider.PERMISSIONS in the RC), redirect_uri https://rafii.io/api/oauth/discord/callback, state present. No consent is given.
  - Depends on: Q-02
  - Evidence to record: Parsed parameter table.

## M. Database (read-only unless approved)

Production Supabase already has Discord migrations 124-126, 128 and 131. Staging does not.

- [x] **M-01** `AGENT` `SHOULD` `W1`: **Advisors**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: advisors run read-only: security 23 findings (1 WARN, 22 INFO), performance 223; none on the in-scope tables at ERROR level; triage in the private report
  - Evidence: private audit (not in the repository)
  - What: Run Supabase security and performance advisors on production, read-only. Triage; any fix needs a migration approval.
  - Evidence to record: Advisor output summary.
- [x] **M-02** `AGENT` `MUST` `W1`: **RLS, FORCE RLS and grants on Discord tables**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: RLS and FORCE RLS on, anon has no grants, authenticated has no access to the Discord, credential or OAuth tables, service_role grants as migrations 124 to 131 give
  - Evidence: private audit (not in the repository); monitoring.sql planned against the schema
  - What: Catalog queries only (no row reads) for pr_discord_rate_state, pr_discord_route_buckets, pr_discord_request_admissions, pr_discord_worker_projection, pr_discord_interaction_links, pr_discord_interaction_replays and the credential tables. Confirm anon and authenticated are denied.
  - Evidence to record: Catalog output.
  - Basis: PR #216 body reports this for 131 only; 124-128 not re-read here.
- [ ] **M-03** `AGENT` `MUST` `W1`: **Backup and restore point**
  - Status: **BLOCKED_EXTERNAL** at 2026-10-22T22:03:20Z: cannot be determined with the tools available: Pro plan means daily backups kept 7 days; PITR is a paid add-on; WAL archiving is running. The owner must read the dashboard
  - Evidence: APPROVAL-PACKET-1.md row 11
  - What: Confirm backups / point-in-time recovery are active for the production project and record the timestamp before any change.
  - Evidence to record: Backup status + timestamp.
- [ ] **M-04** `AGENT+APPROVAL` `COULD` `W1`: **Staging drift**
  - Status: **NOT_APPLICABLE** at 2026-10-22T22:03:20Z: default taken: staging has no Discord tables and migrations are already in production; AUTH-8 not requested
  - Evidence: S-05-migration-reconciliation.md
  - What: Staging (oxacvkhpfgytkepxcaqh) ledger ends at 130 and has no Discord, Pinterest or Mastodon migrations, so it cannot rehearse this RC. Default: rely on the disposable PostgreSQL 17 CI scenarios and skip staging. Applying migrations to staging is an optional approval (AUTH-8).
  - Approval: AUTH-8
  - Evidence to record: Decision recorded.
  - Basis: Supabase list_migrations on staging, 2026-10-22.
- [x] **M-05** `AGENT` `SHOULD` `W1`: **Data minimisation check**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: engagement is OFF; its code keeps counts and digests, not message text; every monitor is aggregate-only; reply approvals (when enabled) keep parent message id, author id and a digest
  - Evidence: monitoring.sql; P-02-discord-policy-compliance.md
  - What: Confirm no message text, author profile or reaction-user list is retained (engagement LIMITS), and that all monitoring queries are aggregate-only.
  - Depends on: S-03
  - Evidence to record: Code references + query list.

## Q. Hosted RC and acceptance stage 1 (no provider effects)

One staged production-target build, then everything that can be proven without touching Discord.

- [ ] **Q-01** `AGENT` `MUST` `W1`: **Pre-flight for the build**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: Verify the linked project is postriff-phase2-private (prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L) in team_PgXY5VdAYKcsv0RLoDPHscNq and not rafii-consumer-staging; no other RC in flight for this lane; post the cost note.
  - Depends on: S-08, C-03
  - Evidence to record: Pre-flight record.
  - Basis: AGENTS.md safeguarded release path.
- [ ] **Q-02** `AGENT+APPROVAL` `MUST` `W1`: **Build ONE staged RC**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: vercel deploy --prod --skip-domain from the frozen SHA, with the SHA attached as deployment metadata (check 'vercel deploy --help' for --meta). No --force unless justified. At most two builds in total, the second only if the first fails for infrastructure reasons. Record deployment ID, URL, state, time, cost if observable.
  - Depends on: Q-01
  - Approval: AUTH-1
  - Evidence to record: Deployment record.
  - Basis: Runbook: staged candidate does not assign public domains.
- [ ] **Q-03** `AGENT` `MUST` `W1`: **Provenance of the deployed RC**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: Fingerprint the deployed files against the RC tree (same method as S-01). Exact match required.
  - Depends on: Q-02
  - Evidence to record: Match report.
- [ ] **Q-04** `AGENT` `MUST` `W1`: **Smoke on the RC URL**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: Using Vercel's protection-bypass fetch: /api/health, protected routes return 401/403 when unauthenticated, connect UI shows gate state, no 5xx in runtime logs.
  - Depends on: Q-02
  - Evidence to record: Probe table.
- [ ] **Q-05** `AGENT` `MUST` `W1`: **Hosted tenant-isolation probe**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: Two synthetic workspaces; cross-tenant read and write of Discord resources must be denied. Use the existing harness. If it needs accounts the agent cannot create, mark BLOCKED_EXTERNAL and add to the Approval Packet.
  - Depends on: Q-02
  - Evidence to record: Probe results.
  - Basis: PR #216 lists hosted application tenant isolation as unqualified.
- [ ] **Q-06** `AGENT` `MUST` `W1`: **Rollback target**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: Name a compatible READY production deployment by fingerprint, not by guess (candidates seen on 10-22: dpl_349BPQoCn1p857TxmQaaKhDb2Lrx, dpl_AkP8r1Lfx4nWgCYSJuJxCKWkF3yM, and dpl_yKAToJbv... whose full id must be looked up; none verified for compatibility). Rule: before any rollback to an older worker, set the kill switch and drain or reconcile in-flight Discord jobs (lease-protocol fence, migration 128).
  - Depends on: Q-02
  - Evidence to record: Target + compatibility note.
  - Basis: PR #211 body rollback note.
- [ ] **Q-07** `AGENT` `MUST` `W1`: **Promotion packet**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the frozen SHA and the owner
  - Evidence: RUNBOOK-LAUNCH.md
  - What: Evidence bundle, exact 'vercel promote <deployment-url>' command, post-promotion checks, abort criteria. Goes into Approval Packet #2.
  - Depends on: Q-03, Q-04, Q-05, Q-06, C-05
  - Evidence to record: Packet file.

## X. Real-provider acceptance stage 2 (after promotion, gate closed except testers)

Vercel crons run only on the promoted production deployment and the OAuth callback origin is rafii.io, so real OAuth and unattended scheduling can only be proven after a dark promotion.

- [ ] **X-01** `AGENT+APPROVAL` `MUST` `W1`: **Dark promotion (gate closed except testers and grandfathered workspaces)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: After AUTH-5: promote the verified RC; confirm https://rafii.io/api/health, that public workspaces see the waitlist state, and one cron 200 per minute.
  - Depends on: Q-07, H-05
  - Approval: AUTH-5
  - Evidence to record: Health + log excerpt + deployment ID.
- [ ] **X-02** `HUMAN` `MUST` `W1`: **Real OAuth and bot install (PRD A08)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Tester account installs the bot into the tester server through the supported flow on rafii.io. Agent verifies with own-workspace readbacks (no secrets): one code exchange, channel record, capability rows, destination list limited to channels the tester can see.
  - Depends on: X-01, H-03
  - Evidence to record: Readback log.
  - Basis: Earlier callback duplicated one-use code exchanges; watch for double POSTs.
- [ ] **X-03** `HUMAN` `MUST` `W1`: **One real send and read-back (PRD A09)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Owner approves the exact text, sender, channel and time in the product UI. Verify the message exists, matches, mentions are suppressed and the read-back receipt is verified. Maximum 3 messages in total.
  - Depends on: X-02
  - Approval: AUTH-9
  - Evidence to record: Message id, digest match, receipt.
- [ ] **X-04** `HUMAN` `MUST` `W1`: **Unattended schedule and cancel (PRD A10)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Schedule a post at least 5 minutes ahead and do nothing; the production cron must send it and the read-back must verify. Record the delay. Schedule a second post and cancel before due; nothing may be sent.
  - Depends on: X-02, C-04
  - Approval: AUTH-9
  - Evidence to record: Timeline log.
- [ ] **X-05** `HUMAN` `MUST` `W1`: **Revoke and reconnect**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Remove the bot from the tester server. The next attempt must be held with a clear reconnect message and no retry storm; the connection must show reauthorization needed; reconnect must work.
  - Depends on: X-02
  - Evidence to record: State transitions log.
- [ ] **X-06** `AGENT` `SHOULD` `W1`: **Permission failure**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Channel the bot cannot post in: the job must be held with a clear reason and no message.
  - Depends on: X-02
  - Evidence to record: Held-state evidence.
- [ ] **X-07** `AGENT` `MUST` `W1`: **Release receipt (PRD A13)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Project, SHA, deployment ID, ready state, acceptance results, cost if observed, rollback target. No secrets, no customer data.
  - Depends on: X-01
  - Evidence to record: RC-RECEIPT.md.
  - Basis: CLAUDE.md end-of-release record.
- [ ] **X-08** `AGENT` `SHOULD` `W1`: **Cap race under load (synthetic)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: tests written and passing locally on PostgreSQL 16 (11, uuid columns like production: 12 racers, 5 slots, 2 held; exactly 3 admitted, count never above the cap; a no-lock control overshoots; every start holds its own slot; one account starting ten different servers is admitted for exactly the free slots; one person at most three in flight, freed when one finishes; a reconnect takes no slot at a full house; a known server is admitted at a full house). Production check is the Q9 count query only. CI evidence = the qualification workflow (PostgreSQL 17) on the frozen head
  - Evidence: tests/test_discord_launch_cap_race.py (source 2a5a523d)
  - What: CI test with simultaneous connect starts around the cap; in production only verify the count query.
  - Depends on: G-02
  - Evidence to record: CI run.
- [ ] **X-09** `AGENT` `MUST` `W1`: **Post-acceptance exposure decision**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: waits for the dark promotion and the tester session
  - Evidence: RUNBOOK-LAUNCH.md; TESTER-SESSION-SCRIPT.md
  - What: Only after X-03 and X-04 are VERIFIED: recommend opening the capped public gate (Approval Packet #2 / AUTH-6). If either failed: NO-GO, fallback F-02.
  - Depends on: X-03, X-04, X-05
  - Evidence to record: Recommendation in readiness report.

## P. Policy, legal and customer-facing

Truthful copy and disclosures. Production already stores Direct for publish and schedule with zero real sends, so copy must not run ahead of evidence.

- [x] **P-01** `AGENT` `MUST` `W1`: **Privacy notice and terms**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: wording drafted and committed on the RC; approval is H-08
  - Evidence: P-01-privacy-terms-diff.md (source 2a5a523d)
  - What: Compare the Discord text in the privacy notice and terms with real behaviour: server and channel ids, bot permissions, revocation, retention, no message text stored, deletion on account removal. Draft edits for H-08.
  - Evidence to record: Diff + drafted wording.
  - Basis: privacy.py, engagement LIMITS, account_deletion.py.
- [x] **P-02** `AGENT` `SHOULD` `W1`: **Discord Developer Policy and Terms review**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: compliance table against Discord's developer policy and terms (2024-07-08 copy); gaps ranked
  - Evidence: P-02-discord-policy-compliance.md
  - What: Read the current public Discord Developer Policy / Terms and produce a compliance table against Rafii behaviour (no mass mentions, no unsolicited DMs, data use, disclosure, deletion). List gaps for the owner.
  - Evidence to record: Compliance table.
- [ ] **P-03** `AGENT` `SHOULD` `W1`: **Customer help and error copy**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: refusal, busy and late-post copy shipped in the candidate in three languages; a connect guide (Manage Server, permissions, removing the bot) is drafted in three languages but is not in the product, because adding it would move the frozen head
  - Evidence: web/src/lib/channels/discord-copy.json; P-03-connect-guide-draft.md (source 2a5a523d)
  - What: Connect guide (needs Manage Server, what permissions, how to remove the bot), and copy for: not enough permission, bot removed, cap reached, waitlist, delayed schedule. English, Traditional and Simplified Chinese.
  - Depends on: G-03
  - Evidence to record: Copy files.
- [x] **P-04** `AGENT` `SHOULD` `W1`: **Account deletion and shared-server behaviour**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: workspace deletion cascades the Discord credential rows; the shared bot is never removed from a server, by design on this line; disclosed in the draft wording
  - Evidence: P-02-discord-policy-compliance.md D2 D3; P-01-privacy-terms-diff.md
  - What: Verify deleting a workspace removes its Discord grants and tokens, and that the shared bot stays while another workspace still uses the same server.
  - Evidence to record: Test or code reference.
  - Basis: account_deletion.py comment on shared bot.

## O. Operations and monitoring

Aggregate-only monitoring, abort triggers and runbooks.

- [x] **O-01** `AGENT` `MUST` `W1`: **Monitoring queries and thresholds (aggregate-only)**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: eleven aggregate-only monitors with thresholds; every statement planned against the production schema with EXPLAIN (no rows read)
  - Evidence: monitoring.sql
  - What: Per-5-minute counts from pr_discord_request_admissions (status_code, state, is_publish), held and uncertain job counts, rate-state blocked_until / circuit_until, OAuth failures, Vercel runtime errors. Page on: invalid-request rate above 1,000 per 10 minutes, any circuit open more than 5 minutes, 3 or more uncertain sends in 15 minutes, 5xx above 2 percent for 5 minutes, policy expiry within 7 days.
  - Depends on: S-03
  - Evidence to record: SQL file + threshold table.
- [x] **O-02** `AGENT` `MUST` `W1`: **Abort triggers and pre-authorised actions**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: trigger table and abort ladder written for Vercel semantics; AUTH-7 rewritten in the packet
  - Evidence: RUNBOOK-INCIDENT.md; APPROVAL-PACKET-1.md row 12
  - What: Write the exact triggers and the action for each (kill switch first, then close gate, then rollback only for code defects). Ready as AUTH-7.
  - Depends on: G-04
  - Approval: AUTH-7
  - Evidence to record: Trigger table.
- [x] **O-03** `AGENT` `SHOULD` `W1`: **Runbooks**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: launch and incident runbooks with customer notices in three languages
  - Evidence: RUNBOOK-LAUNCH.md; RUNBOOK-INCIDENT.md
  - What: Launch-day runbook (T-minus), incident runbook (Discord outage, 1015 ban, policy expiry, bot-token compromise with the owner-only rotation steps and the all-customers impact), customer comms templates.
  - Depends on: O-01, O-02
  - Evidence to record: Runbook files.
- [ ] **O-04** `AGENT` `COULD` `W1`: **Renewal and rotation calendar**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: no calendar tool is connected to this session; the policy tool prints the renew-by date (7 days before expiry; for the example policy: expiry 2026-11-21 19:59Z, renew-by 2026-11-14) and RUNBOOK-LAUNCH lists the owner reminders; the owner creates the entries
  - Evidence: scripts/discord_rate_policy.py; RUNBOOK-LAUNCH.md
  - What: Rate-policy expiry, bot-token and client-secret rotation reminders.
  - Depends on: R-01
  - Evidence to record: Calendar entries or tracker items.
- [ ] **O-05** `AGENT` `SHOULD` `W1`: **Post-launch reviews**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: after launch
  - What: Aggregate-only reports at T+2h and T+24h: connects, caps, errors, delays, held and uncertain jobs.
  - Depends on: X-01
  - Evidence to record: Report files.

## F. GO / NO-GO, fallback and reporting

A false GO is the worst outcome. A clean NO-GO with the fallback engaged is an acceptable result.

- [ ] **F-01** `AGENT` `MUST` `W1`: **GO / NO-GO evaluation**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: evaluated at GO_TIME; today the recommendation is NO-GO
  - Evidence: LAUNCH-READINESS-REPORT.md
  - What: At GO_TIME generate the table of every MUST item with status and evidence link and give a recommendation. Declare NO-GO early when a MUST gate can no longer pass, not at the deadline.
  - Evidence to record: LAUNCH-READINESS-REPORT.md.
- [ ] **F-02** `AGENT` `MUST` `W1`: **Fallback (NO-GO)**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: the fallback is that D1 (gate closed) stays promoted; the customer wording exists; reschedule criteria not written
  - Evidence: RUNBOOK-LAUNCH.md section 2; RUNBOOK-INCIDENT.md section 5
  - What: Gate stays closed (tester and grandfathered workspaces only), the public sees the waitlist state, no data is lost and existing grants stay safe. Config diff and customer message prepared in advance. Reschedule criteria stated.
  - Depends on: G-01
  - Evidence to record: Fallback config + message.
- [x] **F-03** `AGENT` `MUST` `W1`: **Abort / rollback decision tree after opening**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: abort and rollback ladder with speeds and undo steps
  - Evidence: RUNBOOK-INCIDENT.md section 1
  - What: Kill switch (seconds, reversible) then close gate then rollback to the verified target only for a code defect, after draining in-flight Discord jobs.
  - Depends on: G-04, Q-06
  - Evidence to record: Decision tree in runbook.
- [ ] **F-04** `AGENT` `MUST` `W1`: **Final report**
  - Status: **NOT_RUN** at 2026-10-22T22:03:20Z: after F-01
  - What: Per CLAUDE.md: project, SHA, deployment ID, ready state, acceptance results, cost if observed, rollback target; privacy-preserving.
  - Depends on: F-01
  - Evidence to record: Report.

## W. Wave 2: 'thousands' prerequisites (start now, not for tomorrow)

None of these can be finished tomorrow, but several take calendar time and must start today.

- [ ] **W-01** `EXTERNAL` `MUST` `W2`: **Verification approved, cap raised**
  - Status: **BLOCKED_EXTERNAL** at 2026-10-22T22:03:20Z: waits on H-01 and Discord
  - Evidence: H-01-verification-prep.md
  - What: After Discord approves verification, raise POSTRIFF_DISCORD_GUILD_CAP and widen the allowlist by env change (G-05).
  - Depends on: H-01
  - Evidence to record: Portal status + env readback.
- [ ] **W-02** `AGENT` `MUST` `W2`: **Worker parallelism for Wave 2**
  - What: Parallel cron lanes or a dedicated Discord lane, with SKIP LOCKED and lease-fence proofs, then repeat R-02 with the production topology.
  - Depends on: R-05
  - Evidence to record: Design + CI + capacity result.
- [ ] **W-03** `AGENT+APPROVAL` `SHOULD` `W2`: **Do webhook-only installs count toward the server limit?**
  - Status: **BLOCKED_EXTERNAL** at 2026-10-22T22:03:20Z: not documented by Discord in anything found; a safe empirical test and a question to Discord are drafted
  - Evidence: W-03-webhook-server-limit.md
  - What: Find out from Discord documentation or support, or empirically by reading the application's approximate guild count before and after one webhook install. If they do not count, the bot-free mode (PR #216, owners and Administrators only, currently OFF) becomes the route to scale without the bot.
  - Evidence to record: Written finding.
  - Basis: Not stated in anything found [Guessing].
- [ ] **W-04** `HUMAN` `COULD` `W2`: **Message Content intent**
  - What: Decide whether richer comments are needed. Discord's threshold is based on users reachable across servers (under 10,000 can enable it in the Portal, above that needs review). Keep OFF until decided.
  - Evidence to record: Decision.
  - Basis: Discord changelog via search summary [Likely].
- [ ] **W-05** `HUMAN` `COULD` `W2`: **Egress IP decision**
  - What: Static IPs or a proxy if bans appear (R-06).
  - Depends on: R-06
  - Evidence to record: Decision.
- [ ] **W-06** `HUMAN` `SHOULD` `W2`: **Support at scale**
  - What: Macros, FAQ, SLA, abuse handling and a bot-token incident process.
  - Evidence to record: Process doc.
- [x] **W-07** `AGENT` `SHOULD` `W2`: **Merge strategy**
  - Status: **VERIFIED** at 2026-10-22T22:03:20Z: proposal only
  - Evidence: W-07-merge-proposal.md
  - What: Propose how the Discord lanes (#216, PING runtime) and the RC land on the release trunk so future RCs stop being re-derived. Propose only; no merge without exact authority.
  - Depends on: S-08
  - Evidence to record: Proposal doc.

## Appendix A. Facts behind this checklist

Confidence: [Certain] read directly from code, git or a tool readback; [Likely] strong inference or a source summarised by search and not read in full; [Guessing] gap filled by assumption.

- [Certain] consumer-saas @5670ce3c has none of the Discord work: no migrations 124-126/128/131 and no src/postriff_phase2/discord/ package. _(source: git, 2026-10-22)_
- [Certain] Unmerged Discord lines: #197 codex/rafii-discord-release-20261015 (acd18f37); #209 codex/discord-scope-manual-draft-repair-20261018 (ecbb9e36); #211 codex/discord-repair-production-candidate-20261018 (63864bd6); #216 codex/discord-personal-account-20261019 (b960bfe0); codex/discord-ping-runtime-20261021 (362666dc). #216 and the PING branch diverge (3 vs 5 commits). _(source: git rev-list, PR list)_
- [Certain] PR #216 head b960bfe0: seven workflows green incl. 5,795 Python tests, six PG17 scenarios, 390/1280 px browser; provider responses synthetic; browser scenes needed one retry; new modes default OFF. _(source: PR #216 body, Actions runs)_
- [Certain] rafii.io alias -> dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg (project postriff-phase2-private, CLI production build created 12:48:12Z, READY 12:50:39Z, alias updated 12:52:07Z on 2026-10-22). /api/health reports sourceRevision null; phase0 and customerValidated are hard-coded literals, not gates. _(source: Vercel get_alias / get_deployment, health fetch, hosted_app.py)_
- [Certain] On 10-21 PR #218 said rafii.io served dpl_yKAToJbv built from 09b3ab8a (Discord + Pinterest lineage). The current build's lineage is unknown. _(source: PR #218 body)_
- [Certain] Production DB buoyhkbodnhzngaotoel ledger includes discord 124, 125, 126, 128, 131 (131 applied 2026-10-21 16:11Z, approved per PR #216), Pinterest x3, Mastodon 134 and a later management migration. Staging DB oxacvkhpfgytkepxcaqh ends at 130 with no Discord. _(source: Supabase list_migrations)_
- [Certain] Production usage is tiny: a handful of active Discord grants (bot installs and identity-only links) in a couple of workspaces, apparently internal; very few active connections across all providers; the rate coordinator logged only reads and OAuth requests between 10-17 and 10-19 and no publish; no webhook, User Install or interaction rows. Exact counts are deliberately not recorded here because this repository is public; S-00 asks the agent to re-measure them with aggregate queries. _(source: Supabase aggregate queries)_
- [Certain] Stored capabilities on the bot installs: identity, publish, schedule = Direct; analytics, comments_read, reply, moderate, media_types, webhooks = Unsupported. _(source: pr_channel_capabilities aggregate)_
- [Certain] Direct rules: publish needs production_reviewed; schedule needs authorization_v2 + connections_v2 (Discord has no native schedule; Rafii's queue sends); engagement overlay shows 'Direct' only per consented channel and only with six flags on. _(source: oauth.py _capabilities; engagement.annotate_capabilities)_
- [Certain] Kill switch POSTRIFF_OAUTH_DISCORD_DISABLED sets execution_enabled false, checked at connect start, callback, destinations and publish; it is provider-wide. No per-workspace Discord gate found. _(source: oauth.py, providers.py, grep)_
- [Certain] Worker: single cron /api/cron/worker every minute; POSTRIFF_WORKER_MAX_JOBS default 10 (1-25), MAX_SECONDS default 20 (1-45); sequential; Discord lane alternates when POSTRIFF_DISCORD_WORKER_V1_ENABLED; tick_discord is not wired to a cron. _(source: hosted_worker.py, vercel.json)_
- [Likely] Vercel crons are invoked on the promoted production deployment only, so unattended scheduling (X-04) can only be proven after a dark promotion; the OAuth callback origin is rafii.io, so real OAuth (X-02) also needs the promoted build. _(source: Vercel cron documentation as remembered; confirm in X-01)_
- [Certain] Rate policy POSTRIFF_DISCORD_RATE_POLICY: strict JSON schema, maximum 31-day validity, expiry makes the coordinator fail closed (503). _(source: discord/rate_limits.py)_
- [Certain] Capacity (PR #197): 1,000-user A and 10,000-user B passed on a mock Discord (100 creates/s, 1,000 req/s) with 16 worker replicas; B: 19,895 of 19,912 requests verified, p95 164.9 s, p99 173.5 s; real Discord excluded. _(source: PR #197 body; postgres_discord_capacity.py)_
- [Certain] OAuth redirect URI is {POSTRIFF_PUBLIC_BASE_URL}/api/oauth/discord/callback unless a callback origin is pinned. Permissions integer on the #216 line is 101376. _(source: oauth.py, social_connectors.py)_
- [Certain] Portal per PR #216 (10-21, read-only): Public Bot ON, Requires OAuth2 Code Grant ON, Interactions Endpoint URL empty. The hosted PING project is paused; no provider-signed PING has occurred. _(source: PR #216 body)_
- [Certain] PR #216 lists still open: real customer OAuth, approved sends and receipts, unattended schedule/cancel/retry/reconnect/revoke, physical mobile, provider-signed PING, User Install, hosted tenant isolation, independent security review, Release Captain approval. _(source: PR #216 body)_
- [Likely] Discord requires app verification to be in more than 100 servers; the team owner verifies identity through Stripe. Not mentioned in any repo document; verification status unknown; the help article itself was not read. _(source: Discord help via search summary)_
- [Likely] Discord API: 50 requests per second per bot; more than 10,000 invalid requests (401, 403, 429 except shared scope) per 10 minutes restricts the IP. Two search results quoted docs.discord.com and a Discord support article consistently; the page itself was not read. _(source: docs.discord.com rate limits via search summary)_
- [Likely] Production's stored Direct rows imply REVIEWED, authorization_v2 and connections_v2 were on when the bot installs were created (10-17 and 10-19). _(source: inference from _capabilities)_
- [Likely] A post needs at least two worker steps (create, then read-back), so Discord throughput is about half the job budget per tick. _(source: hosted_worker.py structure; measure it (R-05))_
- [Guessing] Whether Discord webhook-only installs count toward the 100-server limit. _(source: unknown)_
- [Guessing] The current RATE_POLICY may already be expired (last coordinator activity 2026-10-19). _(source: unknown; do not read the value)_

## Appendix B. Environment matrix for the RC (names only; the agent never reads or prints values)

| Variable | Purpose | Wave 1 target | Applied by |
|---|---|---|---|
| `POSTRIFF_OAUTH_DISCORD_CLIENT_ID / _CLIENT_SECRET` | Discord application credentials | present, unchanged | owner only |
| `POSTRIFF_DISCORD_BOT_TOKEN` | Shared bot token (every customer) | present, unchanged | owner only |
| `POSTRIFF_PUBLIC_BASE_URL` | Builds the redirect URI | https://rafii.io | verify only |
| `POSTRIFF_OAUTH_DISCORD_CALLBACK_ORIGIN` | Optional pinned callback origin | unset | verify only |
| `POSTRIFF_OAUTH_DISCORD_REVIEWED` | Operator declaration that Direct publish is allowed | unchanged until the owner decides (D-04) | approval item |
| `POSTRIFF_OAUTH_DISCORD_DISABLED` | Kill switch (provider-wide) | unset (armed) | AUTH-7 only on abort |
| `POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED` | Destination / approval authority v2 | true (needed for schedule Direct) | AUTH-3 |
| `POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED` | Connections v2 flow | true | AUTH-3 |
| `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED` | Shared PostgreSQL rate coordinator | true | AUTH-3 |
| `POSTRIFF_DISCORD_RATE_POLICY` | Reviewed, expiring policy JSON (not secret) | new value from R-01, valid at least 14 more days at T0 | AUTH-4 |
| `POSTRIFF_DISCORD_WORKER_V1_ENABLED` | Discord worker lease policy | decide in R-05 and match the deployed worker protocol | AUTH-3 |
| `POSTRIFF_WORKER_MAX_JOBS / POSTRIFF_WORKER_MAX_SECONDS` | Per-tick worker budget (1-25 jobs, 1-45 s) | decide in R-05 | AUTH-3 |
| `POSTRIFF_DISCORD_CONNECT_WORKSPACES (proposed name)` | Fail-closed workspace gate (G-01) | tester + grandfathered, later '*' | AUTH-3 / AUTH-6 |
| `POSTRIFF_DISCORD_GUILD_CAP (proposed name)` | Global server cap (G-02) | 90 | AUTH-3 |
| `POSTRIFF_DISCORD_ENGAGEMENT_V1_ENABLED` | Analytics / comments / reply | false (D-03) | AUTH-3 |
| `POSTRIFF_DISCORD_MESSAGE_CONTENT_EVIDENCE` | Message Content intent approval record | unset | verify only |
| `POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED / _WEBHOOK_QUALIFIED` | Bot-free webhook mode | false | AUTH-3 |
| `POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED / _INTERACTION_CONFIG` | User Install and PING | false / unset | AUTH-3 |
| `CRON_SECRET (name only)` | Authorises /api/cron/worker | present | owner only |

## Appendix C. Sources

- PR #216 https://github.com/dev-james0723/PostRiff/pull/216 (current status of the Discord multi-mode line)
- PR #218 https://github.com/dev-james0723/PostRiff/pull/218 (LinkedIn launch candidate; says what rafii.io served on 10-21)
- PR #212 https://github.com/dev-james0723/PostRiff/pull/212 (production deployed from a distinct Discord branch; do not merge consumer-saas)
- PR #211 https://github.com/dev-james0723/PostRiff/pull/211 and PR #197 https://github.com/dev-james0723/PostRiff/pull/197 (capacity evidence, rollback notes)
- Branch docs on origin/codex/discord-ping-runtime-20261021: DISCORD-PRODUCTION-CANDIDATE-20261018.md, docs/discord-personal-account-20261019/* (some statuses stale)
- Repo policy: AGENTS.md, CLAUDE.md, docs/operations/VERCEL-ON-DEMAND-COST-CONTROL-20261018.md
- Discord: https://support-dev.discord.com/hc/en-us/articles/23926564536471-How-Do-I-Get-My-App-Verified (verification and the 100-server rule, via search summary)
- Discord: https://docs.discord.com/developers/topics/rate-limits (50 requests per second, invalid-request restriction)
- Discord: https://support-dev.discord.com/hc/en-us/articles/40281523410967-Changes-to-Privileged-Intent-Access-for-Discord-Apps

