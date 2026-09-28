# Trend Growth Beta release checklist

Status: **local candidate only**. This checklist does not authorize an activation.

## Release baseline

- [x] `origin/consumer-saas` and the current Ready Vercel production deployment both resolve to `7b5ece8b343c1f6aaaae45fe771a9a2b21b810cc` at the 2026-09-28 inspection. Deployment: `dpl_2JX1JhWPnRt5odVWm91atJc6edFh`.
- [ ] Review and merge the tested Growth Beta branch through the normal release gate; then verify that the intended commit, not a newer unrelated commit, is the deployed alias revision.
- [ ] Read-only production database audit: verify migrations `035_growth_metric_reads.sql` and `040_social_trend_intelligence.sql`, the required tables/indexes/RLS, and the exact schema expected by this commit. No migration was executed in this task.

## Stage 1: internal stored Radar

- [ ] Name one internal workspace ID and verify its owner, membership, retention policy and test-data rights. The production `RAFII_TREND_WORKSPACE_ALLOWLIST` name exists; its membership was not disclosed or verified. No wildcard or implicit admission.
- [ ] Provision and verify `RAFII_TREND_CURSOR_SIGNING_KEY` using the approved secret process. Its production variable name was absent at inspection; never publish or log its value.
- [ ] After database and key checks, approve only `RAFII_TREND_INTELLIGENCE_ENABLED`, `RAFII_TREND_RADAR_ENABLED` and `RAFII_TREND_TRUST_RECEIPTS_ENABLED` for the named workspace/deployment. Verify stored-only GET, exact receipt/current-rights checks, limited coverage copy, zero acquisition/model calls on mount, tenant isolation and revocation.

## Stage 2: bounded provider acquisition

- [ ] Approve each `provider:operation` separately under `RAFII_TREND_ALLOWED_OPERATIONS`. A publishing connection or the `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED` flag alone grants no discovery right. At inspection neither variable name was present in production.
- [ ] For each operation, record its source, entitlement, permitted fields, display/LLM/storage rights, retention/deletion, completeness, quotas, cursor semantics, workspace/territory/purpose, revocation, bytes/items/time budget and actual cost model. Run one bounded live smoke only after those approvals.
- [ ] Set explicit per-tick, per-provider, per-workspace and total model/provider spend caps before paid work. Keep model enrichment and notifications off until separately approved.

## Stage 3: views/reach Growth Beta

- [ ] Verify production `POSTRIFF_METRIC_READS` is enabled only for the approved deployment after its database and account analytics rights are confirmed. The variable name was absent at inspection; this task did not change it.
- [ ] With an authorized verified test publication, confirm exactly t0, +1h, +24h and +7d durable schedule rows; due claims/retries/lease fencing; disconnect/revocation; append-only native observations; and unavailable distinct from observed zero. No browser polling is needed to create these reads.
- [ ] Verify the +24h account/provider/language/format/definition cohort, minimum sample, baseline, counter-evidence, `causal=false` wording, owner review and expiry in Performance Learning. Confirm no unqualified follower-conversion option or follower-growth promise.
- [ ] Check bounded worker operational signals, unknown-cost ledger state, provider error/retry rates and unexpected external calls. Run authenticated production UI/API/database smoke for the one workspace and a denied second workspace.

## Rollback and later gates

- [ ] Rehearse disabling `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED`, `RAFII_TREND_MODEL_ENRICHMENT_ENABLED`, `RAFII_TREND_NOTIFICATIONS_ENABLED` and `POSTRIFF_METRIC_READS`; then disable Radar/Intelligence/Trust flags as needed. Confirm the worker stops new dispatch/reads and retained rows continue to honor deletion and rights checks. Do not erase evidence as a rollback shortcut.
- [ ] Keep follower conversion unavailable until a reviewed provider-native `follows` and `profile_visits` pair has matching provider, account, attribution scope, definition and window, and a positive denominator. The current owned-post ingestion contract provides neither pair. Meta's [official Threads post-insights request](https://www.postman.com/meta/threads/request/434u2bd/get-post-insights) lists post views, likes, replies, reposts, quotes and shares; account-level follower information is not a post conversion pair.
- [ ] Require an empirical internal creator cohort and calibrated non-causal outcomes before a broader rollout. Synthetic fixtures and local database/browser proofs do not establish creator lift.
