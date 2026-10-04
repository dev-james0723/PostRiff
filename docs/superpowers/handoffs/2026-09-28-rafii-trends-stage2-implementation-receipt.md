# Rafii Trends Stage 2 — implementation receipt (production activation blocked)

Date: 2026-09-28 (America/Indiana/Indianapolis). This is a local implementation and release handoff, **not** a production acquisition receipt.

## Release and provider preflight

- Clean starting worktree: `codex/trend-live-acquisition-handoff-20260928`, starting HEAD `3bef0b1d94b6c1e08481b3d2e183a55a245074c9`. Current remote `consumer-saas` was `ee688397dd39d9cf3df6c99f22c488fa355b54ee` when fetched.
- The production alias `postriff-phase2-private.vercel.app` resolved to Ready deployment `dpl_28Qi5dkEdjiSk41K5jJs599eZLSU`; Vercel's deployment API reported Git source `consumer-saas` at that exact SHA.
- Production environment pull showed Intelligence, Radar and Trust Receipts enabled; provider operations, allowed operations, model enrichment, Trend notifications and `POSTRIFF_METRIC_READS` absent. The allowlist contained exactly one UUID; its value is omitted here.
- Current [official Jetstream v2 documentation](https://github.com/bluesky-social/jetstream/blob/main/docs/README.md) describes `jetstream.us-west.bsky.network`, the `network.bsky.jetstream.subscribeEvents` WebSocket, `xrpc.v1.json`, inclusive instance-local sequence cursors, at-least-once delivery, and inline delete/account/sync markers. The checked adapter pins `jetstream-v2-json@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d`. The hosted endpoint itself has not been exercised by this task.

## Implemented candidate

- `scripts/trend_provider_activation.py` provides SHA-pinned `status`, `plan`, `apply`, and `revoke` modes for exactly `bluesky:live_sample` and one explicit workspace. It compares the production alias Git SHA and allowlist, checks excluded flags, audits migration 035/040 checksums and forced RLS, gives a content-free immutable diff, and fails closed on conflicts. It never changes Vercel flags or invokes the provider.
- `src/postriff_phase2/growth/trends/activation.py` defines the reviewed workspace-local manifest: seven allowed rights; embeddings, model processing, cross-workspace sharing, cross-source combination and training denied; 24-hour raw retention; at most four hours of source admission; 120 two-minute samples of at most 100 items and five seconds each; three explicit zero-microUSD budget dimensions. The provider operation is `bluesky:live_sample` only. No archive replay is admitted.
- Authenticated coworker status now derives `active` only from a recent succeeded ingestion batch and current source health. It reports `none`, `unverified`, or `degraded` otherwise. The Trends page explains each state and says when a live sample yielded no current matches. Opening the page remains a stored GET with no acquisition.
- The existing Trend worker, planner, provider registry, pipeline, thresholds and rights gates were preserved. No model enrichment, notifications, paid corroboration, other social provider, or metric read flag was enabled.

## Local validation

- Growth Beta and new activation unit tests: 21 passed. Broad `test_trend_*.py`: 1,035 run; 244 database-gated skips; no failures. Database behavior was verified separately in selected disposable PostgreSQL suites.
- Disposable PostgreSQL groups `postgres_growth_metric_reads`, `postgres_trend_activation`, `postgres_trend_frontier`, `postgres_trend_pipeline`, `postgres_trend_planner`, `postgres_trend_services`, and `postgres_trend_trust`: all exited 0. The new activation test covered exact immutable rows, forced-RLS and migration audit, zero-cost reservation/settlement, job idempotence, workspace denial, revocation and reapply refusal. It also checked `unverified → active → degraded` against real PostgreSQL source-health and ingestion-batch rows. Provider transport remained synthetic/off.
- Node 24 frontend typecheck and scoped lint (zero warnings/errors), canonical JSON Schema export check, and Next production build passed. `git diff --check` and Python compile checks passed.
- Full fixture browser: 82 passing assertion groups at 1440, 390, and 820 px, with 200% reflow, axe, overflow and GET-only checks. Scoped Radar Beta: 30 passing groups. Learning browser: 49 passing checks. Screenshots at 1440 and 390 px were visually inspected.
- The real loopback Next → Python API → disposable PostgreSQL browser path passed 108 checks at 1440, 768, 390, and 430 px. It used synthetic identity and stored seeds, with no provider/model configuration or browser egress. It does not prove live Bluesky collection.

## Concrete blocker and continuation

The connected Supabase account listed only `bookmark-pilot`, not the production project `buoyhkbodnhzngaotoel`. A fresh `trend_provider_activation.py status` check against the verified production SHA and current allowlisted workspace exited 2 with `migration_dsn_missing`. Vercel's production environment pull substitutes `[SENSITIVE]` for the database secret. Therefore production migrations/RLS cannot yet be audited through the approved connection. This task created no production contract, policy, budget, flag, cron job, observation or Trend.

After production migration/Trend database access is available, re-fetch `consumer-saas`, recheck the production alias and current one-workspace allowlist, and run the operator's `status` then `plan` with the exact workspace, provider, operation, merged SHA, and a controlled start/end window. `apply` must match that reviewed plan. Only after the DB rows verify, set `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED=true` and `RAFII_TREND_ALLOWED_OPERATIONS=bluesky:live_sample`, deploy/redeploy the exact merged SHA with those variables, and observe the normal cron. Verify real bounded collection, valid observations, cursor/outbox/pipeline progress, source health, usage ledger, authenticated UI/API, second-workspace denial, no unexpected operations or errors, then record a separate production receipt.

Rollback rehearsal is flag-first: remove the operation from the allowed list and disable provider operations in the live deployment, verify dispatch stops, then use the operator's `revoke` mode if the source must be stopped. Do not delete observations or receipts to conceal an activation attempt; retention and revocation maintenance continue.
