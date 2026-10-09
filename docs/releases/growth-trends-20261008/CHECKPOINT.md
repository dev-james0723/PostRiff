# Durable checkpoint (repository copy)

The Token Pilot registries for both D Festival and James-Au-Studio are at their
256-item limit. Nothing is deleted from them; durable task state lives here.

## State 2026-10-09T01:10Z

- Integrator worktree `.agent-worktrees/rafii-growth-trends-20261008`, branch
  `claude/growth-trends-launch-20261008` (C0 `5038b16a`, docs `13681401`, plus
  the enrollment rate limit).
- Lane A worktree `.agent-worktrees/rafii-trends-ingestion-20261009`, branch
  `claude/trends-ingestion-recovery-20261009` (base a522482e); workflow
  `wf_6dae7208-5c9`.
- Lane B worktree `.agent-worktrees/rafii-growth-studio-20261009`, branch
  `claude/growth-studio-launch-20261009` (base 5038b16a); lane C worktree
  `.agent-worktrees/rafii-trends-product-20261009`, branch
  `claude/trends-product-launch-20261009` (base 5038b16a); workflow
  `wf_681d3dd6-4aa`.
- Production: a522482e (`dpl_HE8oWvF5TMF7xo63rgS26NSVB3WR`). Migrations 037/038
  applied and verified 01:04:49Z; 103 applied and verified 01:16:09Z.
- Authorization: see RELEASE-RECEIPT.md.

## Next steps

1. 103 after C0 CI passes; then lane A PR → merge → deploy → three-cycle
   ingestion proof and projection/receipt proof.
2. Integrate lanes B and C, resolve shared-contract conflicts, CI, merge, deploy.
3. Enable Growth flags and caps (`POSTRIFF_GROWTH_DAILY_USD_CAP=10`,
   `POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP=4`) and self-serve switches
   (cohort 10 each) only after the schema and the readiness code are live.
4. QA account journey (owner/editor/viewer, two workspaces), founder journey,
   Instagram 1h reading from an existing eligible post if available.
5. Bluesky source-rights review document; share_across_workspaces stays denied
   until it is verified.
6. Admin cost visibility for Growth spend.
