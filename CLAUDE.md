# Claude Code — PostRiff / Rafii

Read and follow the repo-root `AGENTS.md` and `docs/ops/vercel-preview-cost-phase2b.md` before choosing a cloud-preview branch or invoking Vercel CLI.

- The approved No-Preview WIP namespace is **opt-in**, never a universal default.
- Existing PR branches continue receiving normal Preview builds; do not rename active branches to save CPU.
- Never assume a CANCELED Preview can serve OAuth, browser, visual, or human review.
- Moving from No-Preview WIP into QA requires a distinct commit SHA outside `wip/no-vercel/*`.
- Production (`consumer-saas`), provider publication, sensitive settings, merges, and deployments require the user's applicable explicit approval.
- Do not modify other agents' running sessions, dirty worktrees, or pending approvals.
