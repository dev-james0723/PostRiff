# Claude Code — Rafii on-demand Vercel deployment policy
Effective 2026-10-18. Read root `AGENTS.md` and `docs/operations/VERCEL-ON-DEMAND-COST-CONTROL-20261018.md` as the active deployment guidance.

- Rafii Git-triggered Vercel deployment is off (`git.deploymentEnabled=false`) and both Rafii projects have automatic Preview deployments disabled. Do not change these settings incidentally. Older Draft PR #205 documents a historical opt-in WIP skip experiment; it is not the current universal default.
- Code, tests, review branches, ordinary Git pushes, and pull requests do **not** automatically produce Vercel hosted previews. Do not use `vercel deploy` as a substitute for each former webhook or for every small fix.
- Consolidate fixes into tested, SHA-pinned release candidates and check cost/provenance/approval. When approved, create a single Production-target staged candidate with `vercel deploy --prod --skip-domain`, run hosted acceptance, and then promote that exact deployment if authorized. Promotion should not rebuild.
- For browser, OAuth, provider, design, or security checks that truly require a hosted Preview, coordinate a limited exception with the release owner, and immediately restore controls. Never mark canceled/missing previews as QA passing.
- Retain existing consent, tenant isolation, provider approvals, CI, source provenance, app rollback, and production safeguards. No edits to credentials, billing plans, infrastructure budgets, other agents' sessions/worktrees, or deploy/merge/publish without exact authority. Do not stop other Agents to save builds.
- At the end record exact project, SHA, deployment ID, ready state, acceptance result, cost if observed, and rollback target. Preserve privacy in logs and handoffs.
