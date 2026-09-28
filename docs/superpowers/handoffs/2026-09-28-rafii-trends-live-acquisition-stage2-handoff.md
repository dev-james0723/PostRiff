# Coding Agent Handoff — Rafii Trends Stage 2 Live Acquisition

You are taking ownership of the Rafii / PostRiff Social Trend Intelligence Stage 2 activation.

This is an implementation task, not a planning-only task.

## Authoritative repository

Canonical repository:

`/Users/ouxianxing/.codex/worktrees/trend-live-acquisition-handoff/James-Au-Studio`

Branch created for this handoff:

`codex/trend-live-acquisition-handoff-20260928`

Starting HEAD when the handoff was written:

`ee688397dd39d9cf3df6c99f22c488fa355b54ee`

Canonical release branch:

`consumer-saas`

Before editing, re-fetch and re-check all of this yourself. Do not assume the HEAD is unchanged.

## Read first

Treat this engineering spec as authoritative for the task:

`docs/superpowers/specs/2026-09-28-rafii-trends-live-acquisition-stage2.md`

Also read:

1. `docs/design/social-trend-intelligence/RAFII_SOCIAL_TREND_INTELLIGENCE_MASTER_SPEC_2026-09-27.md`
2. `docs/design/social-trend-intelligence/GROWTH_BETA_RELEASE_READINESS_2026-09-28.md`
3. `docs/design/social-trend-intelligence/GROWTH_BETA_RELEASE_CHECKLIST_2026-09-28.md`
4. `docs/design/social-trend-intelligence/GROWTH_BETA_RELEASE_GATE_2026-09-28.md`
5. `web/src/features/trends/CONTRACT.md`
6. the current provider/worker/planner/policy code under `src/postriff_phase2/growth/trends/`.

Inspect any repository-level agent instructions if they have appeared since this handoff was created.

## Problem to solve

Production currently shows the Trends UI successfully, but the internal workspace returns “No matches in the available scope” even with broad filters.

Do not start by changing the filters or faking a UI result.

The prior audit found the page is behaving as expected for Stage 1: stored Radar is enabled, but production live provider acquisition is still off. There are no live Trend observations feeding the deterministic pipeline.

Your goal is to implement and safely activate the smallest real Stage 2 source path so the internal workspace can receive truthful live Trend evidence.

## Required implementation decision

The first production source is:

`bluesky:live_sample`

Only.

Use the existing Bluesky Jetstream adapter and existing durable Trend worker path.

Do not activate:

- archive replay;
- X;
- Reddit;
- TikTok;
- Instagram discovery;
- LinkedIn discovery;
- licensed listening;
- paid web corroboration;
- model enrichment;
- notifications;
- Stage 3 metric reads.

Do not create a second ingestion architecture.

## First actions

1. Inspect branch, HEAD, status, remotes, worktrees, and origin/consumer-saas.
2. Confirm production alias SHA and current feature-variable names.
3. Confirm the internal workspace remains the only allowlisted workspace.
4. Confirm migrations 035 and 040 are still applied and RLS is intact.
5. Re-check current official Bluesky Jetstream service/protocol/host constraints before any live dispatch.
6. Inspect the current code before editing. Preserve unrelated work.

If any of those checks fail, stop at the concrete blocker with evidence.

## Implement

Follow the spec exactly.

At minimum:

### A. Operator activation path

Create a safe idempotent provider activation tool, preferably:

`scripts/trend_provider_activation.py`

with:

- status
- plan
- apply
- revoke

It must:

- use the existing TrendStore / TrendJobs contracts;
- avoid printing secrets;
- require explicit workspace/provider/operation;
- fail on release SHA mismatch;
- fail on immutable policy conflict;
- never broaden rights;
- never enable extra providers;
- create explicit system/provider/workspace budget dimensions;
- support a zero-microUSD unmetered reservation path only if the current reviewed capability remains unmetered.

### B. Production Bluesky policy

Create a reviewed workspace-local immutable policy for the internal Beta workspace.

Allow only:

- retrieve
- store_raw
- store_metrics
- display_excerpt
- display_link
- derive_metrics
- retain_derivatives

Keep denied/unknown:

- store_embeddings
- llm_process
- share_across_workspaces
- cross_source_combine
- train_or_finetune

Use short initial retention and a bounded schedule. Start with the envelope in the engineering spec unless current provider constraints require a stricter value.

### C. Source acquisition state

The current API only exposes acquisition `none|unverified`.

Add a stronger state only if it is derived from durable recent collection/source-health evidence.

Do not infer “active” from an enabled flag.

If implemented, keep the backend/API/schema/types/UI/browser fixtures synchronized.

Expected states:

- none
- unverified
- active
- degraded

### D. Preserve the GET boundary

Opening `/app/trends` must remain a stored read.

No page mount may:

- start provider acquisition;
- call JEV;
- perform paid search;
- mutate a budget;
- start metric reads.

The cron/worker path owns acquisition.

## Verification before release

Run the focused Trend test suites already established by the Growth Beta work, including:

- Growth Beta unit suite;
- broad `test_trend_*.py` suite;
- disposable PostgreSQL Trend service suite;
- frontend typecheck;
- lint;
- Next production build;
- full Trend browser fixture;
- scoped Radar Beta fixture;
- Learning browser fixture where affected;
- real API + disposable PostgreSQL browser path;
- `git diff --check`.

Add tests for every new activation/status behavior.

Do not claim production readiness from fixtures alone.

## Production activation

After implementation and review gates are green:

1. merge through the normal `consumer-saas` release path;
2. verify production runs the exact merged SHA;
3. apply the reviewed provider contract/policy/budget configuration for the single internal workspace;
4. enable only:
   - `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED=true`
   - `RAFII_TREND_ALLOWED_OPERATIONS=bluesky:live_sample`
5. keep model enrichment, notifications and metric reads off;
6. let the normal cron create and dispatch the bounded live job;
7. verify a successful production collection;
8. verify valid observations and pipeline progress;
9. verify source health and usage ledger;
10. open the authenticated Trends UI and confirm it reports the actual durable acquisition state;
11. perform an authenticated denied-second-workspace API probe;
12. inspect production logs;
13. rehearse rollback.

Do not lower Trend thresholds just to force a visible card.

If live observations exist but no Trend object passes current thresholds, the UI must say that live source acquisition is active but no current matches are available.

## Release completion criteria

Do not call this done until all applicable criteria are evidenced:

- source code committed;
- branch pushed;
- PR/release checks green;
- merged to current `consumer-saas`;
- exact production deployment SHA verified;
- one workspace only;
- exactly one provider operation admitted;
- one successful bounded live Bluesky collection;
- nonzero valid observations;
- pipeline processed live evidence;
- no unexpected model/provider calls;
- no notification send;
- no cross-workspace exposure;
- rollback verified;
- production receipt written.

If production rights/access or current Bluesky contract verification blocks activation, finish all local implementation/tests, commit/push the branch, then stop on that exact blocker rather than bypassing it.
