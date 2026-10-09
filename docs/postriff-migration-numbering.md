# PostRiff migration numbering

Owner decision, 2026-09-25. It covers `migrations/postriff/NNN_*.sql` on every branch. Pick numbers from this file, and update it in the same change that adds a migration.

## Reserved numbers

| Number | Files | Owner | State |
|---|---|---|---|
| 001–019 | existing chain (003 is local-only) | — | See "Production shape" below: not every one of them is applied in production. |
| 020–022 | `020_credit_quotes`, `021_credit_purchases`, `022_credit_payment_lifecycle` | credits (PR #2) | **Applied in production** (according to the release session and its local runner logs). Permanently occupied. |
| 023 | `023_time_savings` | Time Back (PR #9) | **Taken, against the reservation.** The owner's decision retired 023, but PR #9 merged `023_time_savings.sql` into `consumer-saas` (`b5b7964`, 2026-09-25 17:30 UTC). Renumbering a migration on the shared branch is riskier than keeping it: once any database applies it, the runner refuses a changed ledger. So 023 now means Time Back, unless the owner decides otherwise. ai-routing's old `023_companion_relay` still moves to 029. The release executor confirms whether production has 023. |
| 024–025 | `024_notification_core`, `025_coworker_evidence_growth` | Rafii Adaptive Social Coworker (`ecb3ff3`) | Local only. Do not renumber them unless a real dependency requires it. |
| 026–029 | ai-routing's four migrations, renumbered from 020–023 | ai-routing | Reserved. The files still carry 020–023 on `ai-routing` and must be renamed before that branch lands (checklist below). |
| 030 | `030_agent_style` | Rafii live agent | Taken on `consumer-saas`. |
| 031 | `031_chat_media` | Chat attachments | Taken on `consumer-saas`; production application is recorded in the chat-context verification evidence. |
| 032 | `032_productivity_connectors` | Chat productivity connectors | Taken on `consumer-saas`. |
| 033 | `033_phone_mode` | Rafii Phone Mode | Taken on `consumer-saas`; verify the deployment ledger before any one-off apply. |
| 034 | `034_unified_notifications` | Rafii Unified Notifications | Taken on `consumer-saas`; verify the deployment ledger before any one-off apply. |
| 035 | `035_growth_metric_reads` | Growth Phase 0 / Active Scout | Renumbered from the isolated branch's 032 during the 2026-09-27 production reconciliation to avoid the existing 032 collision. |
| 036 | `036_dial_phone_provider` | Rafii Dial Phone | Taken on `consumer-saas`; adds Dial to the existing phone provider constraint. |
| 037–040 | `037_growth_phase1`, `038_growth_closed_loop`, `039_radar`, `040_social_trend_intelligence` | active Rafii release worktrees | Reserved to avoid colliding with in-flight Growth / Radar / Social Trend Intelligence work. They are not implied applied merely by this reservation; re-check before release. |
| 041 | `041_context_navigation` | Rafii Context Navigation | Additive search indexes and workspace-scoped Moments; apply before the corresponding API release. |
| 042 | `042_phone_inbound` | Shared inbound Rafii phone v1 | Reserved on `codex/rafii-inbound-v1`; additive, apply before releasing the direction-column reader. |
| 043–046 | `043_phone_duration`, `044_social_provider_webhooks`, `045_phone_caller_identity`, `046_phone_passkey_identity` | released consumer work | Occupied on verified `consumer-saas` base `d91660b` (2026-09-29). |
| 047 | Inbox operational sync / Universal Library in active worktrees | concurrent owners | Occupied; competing in-flight uses were observed. Control does not rename or absorb either. |
| 048 | `048_pricing_credit_catalog_v2` | pricing owner | Occupied in an active ref/worktree. |
| 049 | `049_rafii_control_foundation` | `feat/rafii-founder-control-v2` | Additive private Control schema and restricted roles; disposable-only verification. No production apply. |
| 050 | `050_free_lifecycle_bootstrap` | pricing owner | Occupied in active pricing ref/worktree; preserved. |
| 051 | `051_rafii_control_read_workflow` | `feat/rafii-founder-control-v2` | Additive safe audit/query snapshots and local synthetic materialization; disposable only. |
| 052–053 | `052_rafii_control_investigations`, `053_rafii_control_business_workspace` | Founder Control (PR #85 → #86) | Additive private Control schema and business projections. |
| 054–055 | `054_rafii_control_founder_views`, `055_rafii_control_founder_contact` | Founder Admin v2 P0 (`claude/founder-admin-v2`, PR #86) | Founder projections, follow-ups, snapshots; contact policy, briefings, incidents. |
| 056 | `056_rafii_control_founder_capabilities` | Founder Admin v2 (PR #86) | Declares the P1/P2 founder capabilities; changes no operator. |
| 057–062 | `057_founder_billing_events`, `058_founder_ai_usage`, `059_founder_product`, `060_founder_reliability`, `061_founder_notifications`, `062_founder_admin_actions` | Founder Admin v2 P1/P2 slices (`docs/design/founder-admin/CONTRACTS.md` §8) | Reserved 2026-10-01 after a scan of every ref and worktree (047, 048, 050 held by other owners; nothing at 056+). 061 stayed unused. |
| 063–068 | `063_founder_revenue_views`, `064_founder_ai_views`, `065_founder_product_views`, `066_founder_ops_views`, `067_founder_comms_views`, `068_founder_actions_views` | Founder Admin v2 P1/P2 slices | The `rafii_control` half of each slice; 057–062 hold only public-schema instrumentation so it can ship before the Control schema. |
| 069–070 | `069_founder_ops_bootstrap`, `070_founder_ops_settings` | Founder Admin v2 P1/P2 (`claude/founder-admin-p1p2`) | 069 makes `pr_bootstrap` prefer a customer workspace over the founder's internal ops workspace; 070 stores each founder's ops workspace (`rafii_control.founder_settings`). Scanned every remote branch and worktree on 2026-10-01: no other 069–079. 061 stayed unused. |
| 071 | `071_founder_engineering_evidence` | Founder Admin (`claude/founder-activation`) | Hosted CI evidence for Advanced › Engineering: lifts 052's local-only manifest for `ci_attested` rows and lets `rafii_control_ingest` write check rows (verdict columns only) in its session environment. Additive and idempotent; creates no login. Written by `.github/workflows/founder-engineering-evidence.yml`. |
| 080–089 | — | RAFII Product Growth v2 (PR #87) | Reserved by that session. |
| 098–102 | `098_youtube_authorization_generation`, `099_youtube_policy_acceptance`, `100_social_cost_reservations` / `100_youtube_api_privacy_erasure`, `101_x_oauth_provider`, `102_agent_ui_artifacts` | concurrent YouTube, social, X and OpenUI branches | Observed on refs/worktrees on 2026-10-09 (100 is used twice by different branches). 098 and 102 were already applied in production by their owners. Not touched here. |
| 103 | `103_feature_enrollments` | Growth Studio + Trends launch (`claude/growth-trends-launch-20261008`) | Additive: `pr_feature_enrollments` (service role only, forced RLS). Scanned every ref and worktree on 2026-10-09: no other 103. Apply before the code that reads it; the code treats a missing table as "not enrolled". |
| 072–079, 104 and up | — | next new migration | Re-scan active refs and worktrees before choosing. |

## Inventory (scan of 2026-09-25 after `git fetch origin`, re-run after the release)

- 020–022 (credits): `origin/consumer-saas`, `origin/raffi/agent-runtime-merge`, `origin/raffi/launch-final`, `origin/raffi/site-agent-release`, `origin/fix/channel-lifecycle` and their local branches, plus `feat/time-back-mvp`, `release/pr2-reconcile`, `release/pr2-update`, `rafii/coworker-integration` and `rafii/integration-runtime-coworker`.
- 020–023 (ai-routing's own files, same numbers): only the local `ai-routing` branch and its worktree. There is no remote branch.
- 023 (Time Back): `origin/consumer-saas` since `b5b7964`. See the 023 row above.
- 024–025: only `rafii/coworker-wp0-wp11`, `rafii/coworker-integration` and `rafii/integration-runtime-coworker`.
- 026–029: only `rafii/ai-routing-renumber-026-029` and its worktree.
- 030–035: unused on every local and remote ref and in every worktree's `migrations/postriff/`, tracked or not.

Phone Mode inventory rechecked on 2026-09-26 after `consumer-saas` advanced to `96426af`: all relevant local/remote refs and all active worktrees were inspected, including untracked migration files. 030, 031 and both existing uses of 032 are occupied. Only the Phone Mode worktree contains 033. No applied migration was renamed or changed. The earlier 2026-09-25 inventory above is historical.

Re-run this before choosing or applying any number:

```sh
git fetch origin
for ref in $(git for-each-ref --format='%(refname:short)' refs/heads refs/remotes); do
  git ls-tree --name-only "$ref" migrations/postriff/ | sed "s#migrations/postriff/##" | grep -E '^0(2[0-9]|3[0-9])_' | sed "s#^#$ref #"
done | sort -k2
git worktree list --porcelain | awk '/^worktree /{print $2}' | while read wt; do ls "$wt/migrations/postriff" 2>/dev/null | grep -E '^0(2[0-9]|3[0-9])_' | sed "s#^#$wt #"; done
```

## How the runner treats numbers

`scripts/postriff_migrate.py`:
- refuses two files with the same number in one tree ("Duplicate migration numbers");
- applies pending files in file-name order and accepts gaps;
- refuses a database whose ledger lists a migration the branch lacks, or whose checksum differs from the file. Never rename or edit an applied file;
- refuses a database that has the schema but **no ledger** ("explicit reviewed baseline adoption is required").

**Production has no ledger** (`docs/design/rafii-v9/migrations-review.md`). So production migrations do not go through `postriff_migrate.py`. They go through one-off, never-aliased runners pinned to each file's sha256, the way 018, 019 and 020–022 were applied. Build the next runner from the post-fix 020–022 runner: prepared statements off, one transaction per file, sha256 pins, snapshots before and after.

## Production shape (as recorded)

- 001, 002 and 004–013 are treated as present: 010–012 are not listed as missing in the 2026-09-24 check, and 013 had no legacy rows left to rewrite. Verify read-only before the next production migration.
- 014 and 015 policies: absent. 016 (`pr_api_tokens`): absent on purpose, pending the API-token decision. 017: not widened.
- 018 and 019: applied with one-off runners. 020–022: applied, per the release session.
- `docs/launch-20260923/FINAL-BILLING-MATRIX.md:7` still says 020–022 are applied nowhere. It is stale; its owner should correct it.

## Apply order (each step needs the owner's authorization)

1. **Coworker:** 024, then 025. Staging first, then production, and **before** any build containing the coworker code is deployed there. Account deletion deletes from the 024/025 tables whatever the flags say. Production-shaped rehearsal (2026-09-25, disposable PostgreSQL 17 without 014–017 and without a ledger, with 018–022):
   - both apply cleanly, and applying both again is a no-op;
   - the 10 new tables have forced row-level security and no `anon` or `public` grants;
   - `pr_reply_drafts_origin_check` becomes `manual | ai_fixture | copilot`;
   - the credit tables are untouched.
2. **ai-routing:** 026, 027, 028, 029, only after the renumbering below, and before deploying its code.

## Test loader (`tests/phase2/rls.sql`)

It loads 001, 002, 004–012, 018, 019, then 023–025 and the released 030–036 chain, followed by 041 Context Navigation. **Never** add 020–022: the credit PostgreSQL tests and `scripts/launch_credit_fixture.py` apply those themselves.

## ai-routing renumbering checklist (later, when that stage is authorized)

**Prepared (local only, 2026-09-25):** branch `rafii/ai-routing-renumber-026-029` @ `0a69f78` (worktree `James-Au-Studio-ai-routing-renumber`), one commit on `ai-routing` `d2f23f7`. It covers steps 3 and 4 for the tracked files. On that branch, all 19 PostgreSQL script runs pass and 486 unit tests pass. Steps 1, 2, 5 and 6 are still open, and so are the untracked ai-routing docs in its own worktree. The `ai-routing` branch itself is unchanged.

1. Re-run the inventory above. If 026–029 are no longer all free, use the next free contiguous range and update this file.
2. Confirm that ai-routing's 020–023 were never applied to any shared database (staging or production ledger, or the runner records).
3. `git mv` the files: `020_ai_routing` → `026_ai_routing`, `021_ai_connections` → `027_ai_connections`, `022_mcp_connector` → `028_mcp_connector`, `023_companion_relay` → `029_companion_relay`.
4. Update every in-file reference:
   - `tests/phase2/rls.sql` lines 26–29 on ai-routing: `\ir` 026–029, after 025;
   - `docs/ai-routing/README.md:40` ("migration 020");
   - `src/postriff_phase2/ratelimit.py:4` ("migration 022", which becomes 028);
   - the untracked ai-routing docs in its worktree (`migration-rollback.md`, `route-contract.md`, `developer-setup.md`).
5. Run the full chain 001–029 on a disposable PostgreSQL, and the production-shaped rehearsal. Then staging, then production.
6. ai-routing is a stale fork (September 17–20) of lines already merged into `consumer-saas`, so bring it up to date before any of this.
