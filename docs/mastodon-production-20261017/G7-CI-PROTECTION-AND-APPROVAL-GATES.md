# G7 — GitHub protection, CI and owner authorization policy
**NOT ENFORCED YET.** Prepared locally, no remote GitHub settings, PR, Vercel or Supabase changed.

## GitHub facts checked 2026-10-17

- Repository dev-james0723/PostRiff, default consumer-saas, remote HEAD 7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1.
- GitHub API GET /branches/consumer-saas/protection returned 404 Branch not protected; GET repository rulesets returned an empty list. This means G7 cannot currently truthfully claim a **protected** release PR.
- Existing PR #176 OPEN/DRAFT, head 53c8ab899b66e14d7d568146b58e6f85c11c6251, mergeable=false. Its head has 13 check runs (including successful component/browser checks and skipped dependency-lock entries), which do **not** attest to the new integrated local G7 candidate.
- Main HEAD has two Vercel commit statuses marked success; these are deployment checks, **not** the full Mastodon security/release acceptance matrix. The new local candidate has no GitHub statuses because it was not pushed.
- Current GitHub Actions budget and hard stop need read-only independent reconfirmation before any permitted PR push or CI job; prior separate task approved US$12 monthly with hard stop ON, but that does not authorize G7 spending.

## Proposed protected consumer-saas ruleset (requires specific admin approval)

- Enforcement: ACTIVE, include default branch consumer-saas, apply to admins as well as contributors; no bypass for automation except reviewed emergency release operator.
- Require a PR before merging; no direct pushes, no force pushes or branch deletion; dismiss stale reviews after new code; require codeowner review; require an independent reviewer, with James as separate final human Release Captain.
- Require latest HEAD and resolved conversations. Require named **verified** CI checks on the exact PR merge SHA, not merely the PR head or stale unrelated Vercel status. Never require a check name that does not run.
- Need independent security reviewer for OAuth credentials, dynamic Mastodon server SSRF/DNS/rebinding, RLS, guest→member boundaries and provider egress; a separate operational reviewer for 131–133 locks, database backup/Restore, rollback and cost.
- Before merge, require zero unattended Production deployments triggered by a PR push or merge; confirm Vercel Git Integration/ignored build controls and billing. Any GitHub Settings/Ruleset mutation remains approval-gated.

## Final required checks, not yet satisfied for exact G7 release SHA

| Check | Current evidence | Release-specific acceptance |
|---|---|---|
| CI Typecheck/optimized build | G2 PASS, Node 24.15/Next 16.3.8 | Run on exact narrowed G7 PR SHA in reviewed isolated non-production environment |
| Mastodon unit + ACL negative cases | G1 PASS 136/136 plus PostgreSQL & creation/security | Fresh exact-commit suite; no whole-tenant row access, vault leakage or unknown retry |
| Genuine Linux Chromium + WebKit | G5 Account/Queue 1440/390/320 PASS, 56 categorized WebKit prefetch aborts, zero unclassified | Repeat only if code/refactor changes relevant runtime; verify matching Playwright/browser revisions |
| Synthetic 1,000-user admission | Depot G5 PASS, 32 SQL connections, 0 provider calls | Not real HTTP concurrent user capacity; deploy limited Beta regardless |
| Production PG17 migration/RLS | 62/62 ledger hash match, RLS correct | Verified backup/isolated restore and exact 131–133 transaction postcondition required |
| Real cross-server OAuth and revocation | NOT RUN | Separate user action and readback on two independently operated servers |
| Promotion/rollback | NO DEPLOY | Verify current active alias, exact candidate artifact, safe reset, no orphan native schedules |
| Customer Public Connect | NO-GO | Explicit invited Beta and separate all-user release authorization |

## G7 offline guardrails
- This branch is a local-only worktree. Do not run gh pr create / git push / gh api --method POST/PATCH/PUT, database DDL, vercel deploy/promote/rollback or modify Vercel env.
- A Draft PR body and reviewed **no-domain** production staging instructions are ready. The source scope still spans 146 paths including 22 no-explicit-Mastodon-line paths; narrow/refactor and review before any remote PR.
- Any paid CI starts only after operator specifies exact run count, per-job wall time, no auto-retries and available spending cap.

**Current status: GitHub protection NOT CONFIGURED; G7 PR NOT CREATED; CI for exact G7 commit NOT RUN; release NO-GO.**
