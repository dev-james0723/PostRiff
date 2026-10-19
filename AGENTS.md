# Rafii agent coordination — deployment cost control

Effective: 2026-10-18. Applies to this repository; does not supersede existing security, production provenance, human approval, data isolation, provider access, or release-owner rules.

## Vercel is on-demand, not per commit
- Vercel automatic Git deployment is deliberately disabled in `vercel.json` (`git.deploymentEnabled=false`). The production and staging Vercel projects also have `previewDeploymentsDisabled=true` to suppress repeated Git Preview deployments. Do not undo either control incidentally.
- Git commit, push, PR creation, CI retries, unit tests, and agent handoffs must not imply a Vercel build. Develop and run appropriate tests without a new Vercel deployment when possible. Prefer existing low-cost CI/Depot pipelines that have already been authorized. Do not introduce new paid CI services.
- Never loop `vercel deploy`, `vercel --prod`, `vercel redeploy`, or a deployment hook in response to each code fix. Group related fixes into a reviewed, pinned SHA and **one** Release Candidate build when actual hosted acceptance is needed.
- Existing active agents continue their own worktrees. Do not stop, reset, rebase, merge, or modify other agents' worktrees merely to apply this cost policy.

## Safeguarded release path
1. Preserve the canonical production project `postriff-phase2-private` (`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`) in team `team_PgXY5VdAYKcsv0RLoDPHscNq`. The secondary `rafii-consumer-staging` is `prj_4bfvSc0AC6am9FdknFWcwNYgmcnN`. Explicitly verify the linked project before building; do not deploy staging code to the canonical production target.
2. Run local/synthetic/CI acceptance first; freeze and record exact source commit SHA, branch, change scope, environment, current production/rollback deployment IDs, and human release authorization where required.
3. When an approved hosted candidate is necessary, stage a **production-target** build with `vercel deploy --prod --skip-domain`; it creates a billable build but does **not** auto-assign the public domains. Keep one in-flight RC per release lane; never parallel duplicate candidates for the same SHA.
4. Check READY state, source provenance, secrets hygiene, routes, auth, tenant isolation, and appropriate public-domain health. Promote that same staged production deployment only after its gates and approvals pass; promotion reuses the build. Never treat a preview-target deployment as the tested production artifact.
5. Record deployment URL/ID, exact SHA, build receipt/cost where accessible, promotion verification and current rollback candidate. Roll back only to a verified compatible READY production deployment; do not guess an old URL or alter the database to match.
6. Failed acceptance does not authorize repeated paid builds. Batch fixes, explain the blocking evidence, and request a new hosted build only if justified.

## Cost and change boundaries
- Do not modify Build Machine size, paid features, Speed Insights subscription, team-wide Spend Management pause, credit card, domains, database, production flags, or unrelated projects as a side effect. Notify of costs before committing extra spend. Preserve no-auto-pause for all production projects.
- For a temporary manual preview, first verify whether the project-level preview-disable setting permits it. Do not toggle it broadly without coordinating the affected branches and restoring the control immediately.
- Runbook: `docs/operations/VERCEL-ON-DEMAND-COST-CONTROL-20261018.md`.
