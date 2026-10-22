# Rafii Vercel on-demand builds — cost-control runbook

Date: 2026-10-18 (America/Detroit). Goal: stop duplicate Git-triggered previews and reduce repeated Production CLI builds without interrupting rafii.io or active agents.

## Proven baseline
- Team: `team_PgXY5VdAYKcsv0RLoDPHscNq` (Pro).
- Production project: `postriff-phase2-private` / `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`.
- Duplicate Git staging project: `rafii-consumer-staging` / `prj_4bfvSc0AC6am9FdknFWcwNYgmcnN`.
- 2026-10-18 EDT deployment sample: 44 deployments; 26 production-project (17 preview + 9 production-target), 17 staging-project (all canceled), 1 unrelated `bookmark-pilot`. Seventeen staging deployments shared Git SHA with a production-project deployment.
- On 2026-10-18 Vercel weekly email: $20.02 metered usage, $16.07 Build CPU Minutes and ~4,600 build CPU minutes; $20 plan credit exhausted. Statement is from email, not an instantaneous balance.
- Both Rafii projects were using 4-vCPU Standard/Elastic build machines with elastic concurrency enabled. A Basic machine may be cheaper but has less CPU; do not downgrade this multi-service Next.js+Python deployment without one proven representative build and resource/timeout evidence.
- Old project-level ignore commands did **not** prevent repeated canceled staging deployments. This is why the trigger is disabled upstream.
- `vercel.json` before change: `git.deploymentEnabled` disabled only `codex/rafii-brand-brain-v11`. After change `git.deploymentEnabled=false`; other rewrites, services, cron, and headers unchanged.

## Changes made
1. Vercel project API update `previewDeploymentsDisabled=true` for staging `prj_4bfvSc0AC6am9FdknFWcwNYgmcnN`; readback confirmed.
2. Vercel project API update `previewDeploymentsDisabled=true` for production `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; readback confirmed.
3. GitHub `dev-james0723/PostRiff` / default branch `consumer-saas`: `vercel.json` `git.deploymentEnabled=false` at commit `036f94e9b4cf976f2a92e81dc7725ad9d5dc3285`; all other config kept intact. This targets Git webhooks, **not** manually authorized Vercel CLI deploys.
4. The cost-control release policy is documented in root `AGENTS.md`; no Production build, alias change, or deployment is part of this task.

## On-demand release contract
- Code/test locally first, ideally one integration branch with explicit SHA and a single RC. Run relevant tests and required preflight; do not trigger a Vercel Build for ordinary commits or unit test fixes.
- Freeze release SHA, identify exact team and project, current production deployment, rollback candidate, and any pending promotions. Respect all provider-specific human approvals and production isolation.
- After valid authorization, run `vercel deploy --prod --skip-domain` **once** from the correct linked project. This is a production-target build but no automatic public alias change. Avoid `--force` unless necessary; don't build the same SHA concurrently from other agents.
- Verify deployed URL/health, exact source provenance, critical routes, callback, auth, tenant boundaries, security and current production alias. Then `vercel promote <verified-production-deployment-url>` after release gate (no new build). Do not promote Preview targets as if they were Production builds.
- Verify public `https://rafii.io/api/health` after promotion and document receipt. If broken, use a verified compatible rollback candidate. Never roll back by guessing URLs or overwriting the production database.
- `vercel build` + `vercel deploy --prebuilt` is an optional future optimization, not yet accepted for this multi-service repository: build-time system environment variables and Next.js skew protection can behave differently. Validate separately.
- An exceptional urgent fix can justify a new build; record why, scope, owner, and cost instead of bypassing all release review.

## Rollback of **cost controls** (no app rollback)
- Re-enable Git Previews individually only if needed: API PATCH `previewDeploymentsDisabled:false` to the corresponding Vercel project; record the affected project and restore it after acceptance.
- To re-enable automatic Git deployment, revert GitHub commit `036f94e9b4cf976f2a92e81dc7725ad9d5dc3285` or edit `git.deploymentEnabled` as intended. Because this affects both linked Rafii projects, first coordinate the branch and release owner. Do not revert as a reflexive response to canceled previews.
- Do not cancel existing in-flight releases or change domain mapping to implement or roll back this cost policy.

## Billing follow-up
- Audit Speed Insights ($10 on prior invoice) before canceling any subscription; no subscription change is included in this work.
- Review Spend Management and ensure only web/email (optional SMS) notifications; **do not** enable team-wide Production Pause, which would make public sites return 503.
- Track new Git-triggered previews and CLI deployments over 24–72 hours; separate build count reduction from actual USD savings. If snapshots show persistent Git previews from stale agent branches, inspect project-level settings and git integration events rather than adding more ignored-build commands.
- Reminder: Deployment Storage retention is changing October 23; if no opt-out, >30-day retention is reduced. Evaluate rollback evidence before that date; do not opt out into paid storage casually.

## Evidence sources
- Official Vercel Git Configuration: https://vercel.com/docs/project-configuration/git-configuration
- Official Vercel staged deployment CLI: https://vercel.com/docs/cli/deploy
- Official Spend Management: https://vercel.com/docs/spend-management
