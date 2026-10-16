# PostRiff / Rafii coding agent guardrails

These repo-wide instructions supplement more specific instructions in subdirectories. Do not use this file to override the user's explicit per-task approval limits.

## Production and security
- Never push directly to `consumer-saas`, merge a PR, promote a Vercel deployment, modify Production configuration, or publish to external social providers without explicit authorization for that action.
- Do not change Vercel project settings, Git integration, runtime secrets, OAuth callbacks, or release checks as a shortcut to reduce build costs.
- Do not confuse Vercel `READY` with passing GitHub CI, authenticated browser acceptance, or production readiness.

## Vercel Preview spend: explicit opt-out
- Read `docs/ops/vercel-preview-cost-phase2b.md` before choosing the branch or triggering a cloud build.
- In the **postriff-phase2-private** Vercel project only, a GitHub Preview branch named `wip/no-vercel/*` with no PR causes the approved Ignored Build Step to exit 0 (CANCELED). Do not assume other Vercel projects share this setting.
- Use the `wip/no-vercel/*` namespace only for authorized disposable internal WIP that does not need a hosted URL, Browser/E2E, authenticated OAuth/callback, visual review, external-provider testing, or any PR-based acceptance. If uncertain, keep the ordinary branch and Preview.
- For needed cloud QA, use an ordinary branch outside that namespace, with a **new unique Git commit SHA** before pushing. Merely opening a PR on an already-canceled SHA might not create a new deployment.
- Do not delete/rewrite other agents' branches or alter their worktrees. Never force-push shared refs.
- Batch low-risk work into purposeful checkpoints; don't automatically redeploy or push every tiny edit. Respect any push approvals specified for the task.
- Preserve all required GitHub checks and human sign-offs. A CANCELED build can still consume startup CPU and deployment quota.

## Evidence
- For controlled cost experiments, record project, exact branch, SHA, GitHub PR ID if any, Vercel deployment ID/state, billable CPU metadata, reason for Preview vs No-Preview, and required approval.
- No tokens, cookies, OAuth secrets, account data, or private environment-variable values in receipts.
- On a wrong skip, stop and report; do not silently change `commandForIgnoringBuildStep` or issue a Production redeploy.
