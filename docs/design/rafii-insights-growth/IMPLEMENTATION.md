# Rafii Insights / Growth implementation

Spec: RAFII-INSIGHTS-GROWTH-20261004 v1.0. Canonical source: /Users/ouxianxing/Documents/Rafii-Insights-Growth-Spec-2026-10-04.

Integration base verified with git ls-remote and fetch: fc29af29482fb28e1acbd42a62700b0db7e51829 on origin/consumer-saas. Canonical checkout remains d91660b7 with pre-existing dirty content. New native-managed isolated worktree: rafii-insights-growth-20261004/James-Au-Studio; branch codex/rafii-insights-growth-20261004; own Token Pilot lease. Another live owner holds studio-product-finish; that tree is untouched.

## Ownership and compatibility

- Existing native registry / acquisition: insights.py, growth/metric_schedule.py. No new reader; preserve PR107 tracking / worker admission and PR120 account-scoped IG capabilities.
- Extend hypothesis metric-time owner: coworker/performance.py; additive ingestedAt / definitionVersion, metric-local observedAt.
- Extend lesson / replay owner: growth/postmortem.py, closed_loop.py, growth/performance.py; exact IDs, period bounds, per-reading times enter existing basisDigest. Legacy absence stays unavailable.
- New thin projection and workspace aggregate settings / proof attachments: coworker/review.py; no migration or provider/model engine.
- Existing HTTP mount: coworker/http.py. Final route prefix: /api/workspaces/{workspace}/coworker/review. GET projection, GET/POST views, POST classifications, POST snapshots, GET snapshot and GET export all use existing session guard / membership / revision / audit.
- Existing UI: analytics/analytics-view.tsx and growth/growth-studio.tsx; shared ReviewScope panel and runtime contract. Existing Growth Loop hypotheses / experiments remain the only acceptance path.
- Trends: canonical trend-types.ts and generated api.schema.json stay authoritative. Reuse current lineage / receipts / learning; no client lineage.
- Reuse: existing verified job / Evergreen identity; no backfill. Personalization: existing creator_calibration and owner approve/restore; absence of reviewed timing method is method_unavailable.

No merge/deploy authorization for this new scoped branch was established in this task. No merge, deployment, paid calls or new social publication is executed by these changes.

## Evidence boundaries

Historical seven tests from 48af4304 restored without its synthetic RESULTS artifact. Fresh base reproduced 5 pass / 2 fail (p0-red.log). Per-metric and lesson regressions plus relevant existing tests: 76 pass (p0-review-green.log). All these are local unit / synthetic data evidence, not native acceptance. PostgreSQL, browser, exports, build and AC58 are recorded separately.
