# Rafii Phase 2B — Vercel Preview cost policy

**Status:** Proposed agent workflow awaiting Draft PR review/merge. Phase 2A's Vercel project setting was already applied and tested; this document does not modify the setting.

## Exact scope and facts

- Team: `jamesau0723-6572s-projects` (`team_PgXY5VdAYKcsv0RLoDPHscNq`).
- Project: `postriff-phase2-private` (`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`).
- GitHub: `dev-james0723/PostRiff`; automatic Production branch is `consumer-saas`.
- Existing `commandForIgnoringBuildStep` is a **246-character** custom command with SHA-256 `831b4eb3b1e91e1edaf4de4380b4029d8e2a62ba4c1aaf32bcba893b7d742e63`. Treat the Vercel API as current authority; do not silently edit it.
- Normal `qa/*`, `claude/*`, `codex/*`, `feat/*`, `fix/*`, and all unrelated branches keep their cloud Preview behavior.
- Only GitHub Preview `wip/no-vercel/*` with **no PR ID** is intentionally canceled. Production/custom targets, unknown metadata, or branches with PR IDs continue building.
- The other `rafii-consumer-staging` project shares the GitHub repository but has **different** Git deployment rules; do not infer that this policy controls its bills.

## Safely choose the branch

**Use ordinary branch + hosted Preview whenever any item applies:** browser/E2E screenshots or accessibility, OAuth redirect and account connection, real provider APIs, staging DB validation, any authenticated cloud behavior, human design review, release candidate, PR acceptance, or unclear dependencies.

**Use `wip/no-vercel/<work-item>` only for explicit internal checkpoint work** (documentation, planning, non-deployed unit tests, local refactoring). Before pushing, check for existing PRs, CI dependencies, external callback URLs, worktree state and approvals. Never use a No-Preview branch for human acceptance.

**To transition to QA:** preserve your work; create an ordinary branch (for example `qa/<work-item>`) with a **new distinct SHA** representing the reviewed candidate; then obtain the correct cloud Preview and verify it. GitHub PR creation on an already-canceled SHA does **not** guarantee Vercel will rebuild that same SHA. Avoid force-push or rewriting branches shared with other agents.

**To release:** run required GitHub/Depot tests and cloud acceptance; obtain the user's explicit authorization before merging into `consumer-saas` or triggering Production. A Vercel `READY` state alone is not sufficient.

## Agents, cost controls and receipts

- Claude, Codex and Kynlo should avoid unnecessary automated pushes/redeploys. Push reviewed logical checkpoints only within the user's permission for the task.
- Avoid manual `vercel deploy` from No-Preview branches unless the command's Git metadata and intended environment are independently checked; don't rely on the Git push filter to protect CLI deployments.
- Never lower build-machine specifications, disable Git integration, disable CI or share secrets to force a saving.
- For every cloud build decision record repository, Vercel Project ID, environment, Git branch/SHA, PR number, reason hosted Preview is or is not needed, deployment ID and final state, and authorization. Keep credentials and PII out of receipts.
- Track actual Build CPU usage weekly before claiming cost savings; canceling a Build is not free.

## Phase 2B isolated canary evidence (2026-10-16)

- **Skip branch:** `wip/no-vercel/phase2b-canary-20261016-a`, SHA `5b0ae5a8e37632f85797a65255cbb00c0ef23e79`; deployment `dpl_9jH9MBsjPaejZUEfUCTG7sGRexYZ` was **CANCELED**. Build log explicitly showed Ignored Build Step exit 0. 4 billable CPU-minutes.
- **Normal branch:** `qa/phase2b-canary-20261016-b`, SHA `2231dc1c6f2e87bb7cd0f2f9baf075b141e9d536`; deployment `dpl_CsBkSnMwzKHbm3XP4FYrZkFYCfGD` was **READY**. 16 billable CPU-minutes.
- Both synthetic commits reused the same source tree as the then-current Production HEAD, so no application code changed.
- The two *test-only GitHub branch refs* were verified and removed after acceptance. Vercel deployment evidence was retained.
- At the public comparison rate of US$0.0035 per CPU-minute, skipped vs normal was approximately US$0.014 vs US$0.056, a measured **75% reduction in billed CPU-minutes for this one representative pair**. Do not treat that as a guaranteed invoice saving.
- Vercel may still charge for clone/initialization of ignored builds; see their Ignored Build Step documentation.

## Stop and rollback

Stop if any production build is unexpectedly skipped, an authorized Preview is canceled, a GitHub required status is missing, an agent uses No-Preview for Browser/OAuth testing, or deployment cost rises.

Do **not** silently roll back configuration or replay Production. With separate owner authorization, restore only `postriff-phase2-private.commandForIgnoringBuildStep` to `null`, verify exact readback, and ask before recreating any missed Preview. Canceled commits will not automatically be backfilled.

## References

- [Vercel Ignored Build Step](https://vercel.com/docs/project-configuration/project-settings)
- [System environment variables](https://vercel.com/docs/environment-variables/system-environment-variables)
- [Vercel source configuration precedence](https://vercel.com/docs/project-configuration/vercel-json)
- [Skip canary](https://vercel.com/jamesau0723-6572s-projects/postriff-phase2-private/9jH9MBsjPaejZUEfUCTG7sGRexYZ)
- [Normal Preview canary](https://vercel.com/jamesau0723-6572s-projects/postriff-phase2-private/CsBkSnMwzKHbm3XP4FYrZkFYCfGD)
