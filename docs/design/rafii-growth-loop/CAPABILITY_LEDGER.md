# Growth Loop capability reconciliation

Inspected 2026-09-26. Isolated branch `codex/rafii-growth-loop`, integration baseline `1687c7e`, combines consumer `387ac76` with growth `0ba0c60`. The original growth worktree, including its untracked official collector and tests, remains untouched.

| Requirement | Baseline status | Reuse / implementation boundary |
|---|---|---|
| Growth Goal, honest coverage, Home | Missing | Workspace document, repository.command permission/revision/audit/verification, insights.summary provider definitions |
| Goal-aware weekly planning | Reusable primitive | weekly_operator.slot_brief; add strategy context without changing recipe constraints, approval or publishing |
| Growth Lab lifecycle | Partially implemented | pr_strategy_hypotheses has evidence, counter evidence, revision, causal=false and initial experiment JSON; extend through workspace experiments and performance.observations |
| Comparable measured results | Reusable primitive | performance features, MIN_ARM=5, insights comparison-age cohorts and medians; prospective bounded cohorts only |
| Approved strategy separate from identity | Reusable primitive | overlays selection and explicit strategy preferences; no mutation of voice/brand |
| Weekly / monthly proof | Missing | Verified queue receipts, weekly plans, review state, campaign planning, engagement, existing time_savings summaries; store bounded immutable period snapshots |
| Digest / in-app / enabled push | Already implemented | NotificationService, catalog, detector, email_render and delivery idempotency; add proof event, no provider replacement |
| Time Back | Already implemented | migration 023 and time_savings; preserve confidence and dedupe semantics; no export or accounting changes |
| Growth/JEV/Radar | Existing active Phase 0 | Reuse evidence/hypotheses; no new scoring or judgment engine; inherited 032 is not a new migration |
| Tenant isolation / audit / instrumentation | Reusable primitive | pr_workspaces RLS, repository.command and pr_product_events; IDs/counts only |
| P1 compounder / relationships / whitespace | Roadmap | Out of this P0 pass |

## State and migration decision

No new SQL migration: new records are stored under `state.coworker.growthLoop`, inside the existing row locked workspace aggregate. This preserves workspace ownership, deletion cascade, existing RLS, optimistic revision checks, and audit infrastructure. One active primary goal and idempotency are validated inside repository.command. The existing hypothesis table remains the source of hypotheses, never duplicated.

Migration numbering audit inspected 107 local/origin refs and 41 worktrees. Existing cross-branch collisions at 020, 021, 022, 023 and 026 are recorded in the local evidence; none is allocated or changed by this pass. Growth Phase 0 migration 032 is inherited and receives its existing tests; no production migration is authorized or needed by the new P0 workspace state.

## Release authority

The owner explicitly started implementation and said “Push and deploy after done.” This supersedes the draft handoff push/deploy prohibition for this branch and the existing Rafii Vercel project. No billing activation, social sends, or production migrations are included.
