# Rafii Trends Stage 2 Live Acquisition — Engineering Spec

Date: 2026-09-28  
Project: Rafii / PostRiff — Social Trend Intelligence  
Canonical release branch: `consumer-saas`  
Authoritative baseline for this spec: `origin/consumer-saas = ee688397dd39d9cf3df6c99f22c488fa355b54ee`  
Spec branch/worktree: `codex/trend-live-acquisition-handoff-20260928`

## 1. Problem

The production Trends page is loading correctly but returns:

> No matches in the available scope

with all platforms, all languages, and the last 7 days selected.

This is not currently evidence of a frontend-filter bug.

The verified project state shows that Rafii has reached **Stage 1: stored Radar**, but **Stage 2 provider acquisition is still off**. The current page is therefore truthfully showing an empty stored result set because production has no admitted live discovery operation producing Trend observations.

The goal of this work is to move one internal workspace from:

`stored Radar + zero live provider acquisition`

to:

`bounded live source acquisition -> stored observations -> deterministic Trend pipeline -> visible truthful Trend results`

without enabling paid discovery, model enrichment, notifications, or broad multi-workspace rollout.

## 2. Evidence inspected

The following project evidence was inspected before writing this spec:

- `RAFII_TREND_GROWTH_BETA_ACTIVATION_SPEC_2026-09-28.md`
- `GROWTH_BETA_RELEASE_READINESS_2026-09-28.md`
- `GROWTH_BETA_RELEASE_CHECKLIST_2026-09-28.md`
- `GROWTH_BETA_RELEASE_GATE_2026-09-28.md`
- the local production receipt `GROWTH_BETA_PRODUCTION_RELEASE_2026-09-28.md`
- `RAFII_SOCIAL_TREND_INTELLIGENCE_MASTER_SPEC_2026-09-27.md`
- provider registry, worker, planner, frontier, source policy, contracts, and Trend UI code.

Current remote release truth was re-fetched:

- `origin/consumer-saas = ee688397dd39d9cf3df6c99f22c488fa355b54ee`
- PR 69 contains the Growth Beta release work.

The local production receipt reports that the same SHA is deployed to the production alias and that Stage 1 is active only for James's internal workspace. The implementing agent MUST re-verify this before any live change.

## 3. Root cause

The empty page is expected under the current production configuration.

Stage 1 currently has:

- `RAFII_TREND_INTELLIGENCE_ENABLED=true`
- `RAFII_TREND_RADAR_ENABLED=true`
- `RAFII_TREND_TRUST_RECEIPTS_ENABLED=true`
- exactly one internal workspace in `RAFII_TREND_WORKSPACE_ALLOWLIST`
- a Trend cursor signing key.

Stage 2 is intentionally still off:

- `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED` is off/absent
- `RAFII_TREND_ALLOWED_OPERATIONS` is off/absent
- no reviewed production source policy is actively scheduling live discovery
- no provider contract/policy has been approved for production dispatch
- production Trend jobs / Trend nodes were zero in the recorded smoke.

Stage 3 is also intentionally off:

- `POSTRIFF_METRIC_READS` is off
- native analytics rights have not yet been activated for this Beta.

The UI itself already labels the feature as stored conversations with limited coverage. It does not trigger acquisition on page mount, which is correct.

## 4. Decision

### 4.1 First live provider

Use **Bluesky Jetstream `bluesky:live_sample` only** for the first Stage 2 production activation.

Why:

- the implementation already exists;
- the current master spec explicitly identifies Bluesky/AT Protocol as the cleanest open-network source for proving the event-stream architecture;
- the adapter is bounded;
- it has update/delete handling;
- it is unmetered in the current capability contract;
- it requires no user OAuth token in the current adapter;
- it avoids the provider-rights and commercial-contract complexity of X, Reddit, TikTok, Instagram, LinkedIn, or licensed listening in the first live smoke.

Do NOT activate `archive_replay`.

Do NOT treat this one source as platform-wide social coverage.

### 4.2 Scope

Use a **workspace-local source scope** for the existing internal Beta workspace.

Do not begin with a shared cross-workspace source scope.

This avoids:

- cross-customer sharing semantics;
- `share_across_workspaces` rights;
- entitlements for other workspaces;
- a false implication that one sample is a reusable global truth source.

### 4.3 Model / JEV boundary

Keep all of the following OFF for this Stage 2 activation:

- `RAFII_TREND_MODEL_ENRICHMENT_ENABLED`
- `RAFII_TREND_NOTIFICATIONS_ENABLED`
- Opportunity Lab generation
- paid web corroboration
- any model-generated popularity, velocity, virality, reach, or follower estimate.

The first live-source smoke must prove acquisition and the deterministic/stored Trend path before adding model enrichment.

### 4.4 Metric reads

Do not enable `POSTRIFF_METRIC_READS` as part of the same change.

Stage 3 measurement is a separate activation after:

- provider/account analytics rights are confirmed;
- the metric schedule is production-smoked;
- one authorized test publication exists.

This Stage 2 task solves the empty live-discovery path first.

## 5. Architecture already present

The following production code path already exists:

```
cron worker
  -> TrendWorker.tick
  -> FrontierPlanner / schedule planner
  -> reviewed SourcePolicy
  -> ProviderRegistry
  -> exact provider:operation admission
  -> atomic budget reservation
  -> Bluesky Jetstream bounded sample
  -> pr_trend_observations
  -> trend.ingested outbox event
  -> TrendPipeline.consume
  -> stored Trend nodes / episodes / measurements / receipts
  -> refresh_workspace_candidates
  -> GET /trends
  -> Trends UI
```

The implementation should use this path rather than inventing a second ingestion mechanism.

## 6. Required production source contract

Create one immutable production provider contract and one immutable workspace-local source policy for:

- provider: `bluesky`
- operation: `live_sample`
- capability version: current `bluesky.PROTOCOL`
- scope: `workspace:<internal-workspace-uuid>`

The agent MUST re-read the current Bluesky service documentation and the checked-in capability version before live activation. If current service terms, host, or protocol materially differ, stop and update the reviewed contract instead of pretending the old contract remains valid.

### 6.1 Minimal rights

Initial workspace-local policy should allow only what the existing pipeline needs:

Allow:

- `retrieve`
- `store_raw`
- `store_metrics`
- `display_excerpt`
- `display_link`
- `derive_metrics`
- `retain_derivatives`

Deny / unknown:

- `store_embeddings`
- `llm_process`
- `share_across_workspaces`
- `cross_source_combine`
- `train_or_finetune`

No code path may silently promote an unknown/denied right to allow.

### 6.2 Retention

Use a short initial raw retention period suitable for an internal smoke, not an indefinite default.

Recommended starting point:

- raw source retention: 24 hours maximum for the initial Beta policy;
- derived objects follow their existing receipt/retention rules;
- provider deletes/revocations override retention.

The exact reviewed retention must be written into the source policy and receipt.

### 6.3 Initial schedule

Use an explicitly bounded schedule.

Recommended initial smoke envelope:

- `interval_seconds = 120`
- `max_samples = 120`
- `max_items = 100`
- `seconds = 5`
- `reservation_microusd = 0`
- policy expiration no later than the initial controlled test window unless explicitly renewed.

This is a maximum of 12,000 accepted items before filtering/quarantine if every sample is full. It is not a completeness claim.

Do not silently increase the sampling window, item cap, schedule count, or retention to force visible Trends.

## 7. Budget contract

Even an unmetered provider must use explicit budget dimensions because the worker requires them.

Create bounded current-period budget keys for:

- system
- provider
- workspace

For the currently unmetered `bluesky:live_sample`, zero-microUSD reservation is valid under the current capability path.

The implementation must still record usage attempts and distinguish:

- zero settled cost;
- unknown cost;
- no external attempt.

If current provider/service economics differ from the checked-in unmetered contract, do not force `0`; update the reviewed provider contract and require a funded cap.

## 8. Activation tool

Do not perform ad-hoc production SQL as the normal operator path.

Add a dedicated idempotent release/operator script, for example:

`scripts/trend_provider_activation.py`

Required modes:

- `status` — read-only current provider/policy/budget/flag state
- `plan` — validate intended immutable contract/policy and show content-free diff
- `apply` — create the reviewed contract/policy/budgets only after all preconditions pass
- `revoke` — revoke/disable this source safely without deleting evidence

Required safety:

- no secret values printed;
- target workspace must be passed explicitly;
- expected production SHA must be passed explicitly;
- provider and operation must be explicit;
- production execution must refuse a mismatched release SHA;
- immutable conflicts fail closed;
- script cannot broaden rights;
- script cannot enable model enrichment, notifications, other providers, or other workspaces;
- `--dry-run`/plan never writes;
- safe reason codes only.

The script may reuse:

- `TrendStore.register_contract`
- `TrendStore.register_policy`
- `TrendJobs.configure_budget`

Do not duplicate their validation logic in raw SQL where avoidable.

## 9. Production feature configuration

Only after the source contract and budget rows are verified:

Enable:

- `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED=true`
- `RAFII_TREND_ALLOWED_OPERATIONS=bluesky:live_sample`

Preserve:

- existing internal-only workspace allowlist;
- the three Stage 1 core flags;
- signing key;
- all other Trend egress/model/notification flags off.

The first live change must not expand the workspace allowlist.

## 10. Worker and ingestion verification

After activation, verify the normal cron path rather than manually injecting fake observations.

Required evidence:

1. planner sees exactly the intended source policy;
2. a `trend.ingest` job is created;
3. worker admission passes only for `bluesky:live_sample`;
4. external dispatch occurs outside DB locks;
5. a bounded batch completes;
6. usage ledger records the attempt;
7. accepted observations are written;
8. cursor advances with the expected pinned protocol;
9. quarantine count is visible without leaking raw provider payload;
10. `trend.ingested` outbox event is emitted;
11. TrendPipeline consumes the event;
12. derived Trend state is created only from eligible retained observations;
13. source health is updated;
14. subsequent runs are idempotent and fenced.

## 11. UI truthfulness

Do not hide an empty result by fabricating a Trend.

The page should distinguish these states:

1. **Stored Radar, acquisition off**
   - current Stage 1 message.

2. **Live source admitted, not yet verified**
   - operation enabled but no successful recent collection receipt yet.

3. **Live source active**
   - at least one recent successful bounded collection receipt exists.

4. **Live source active, no current Trend matches**
   - acquisition works but the deterministic pipeline has no current Trend object matching filters.

5. **Source degraded / paused**
   - recent health/backoff/quarantine state.

The current `trend_beta.acquisition` enum only supports `none|unverified`. Extend it only if the backend can derive the stronger state from durable recent source-health / ingestion evidence.

Never infer `active` merely from an enabled flag.

Suggested additions:

- `none`
- `unverified`
- `active`
- `degraded`

If this contract change is implemented, update:

- backend schema;
- `trend-types.ts`;
- Trend hooks;
- Trend browser fixtures;
- API schema;
- contract docs.

The empty-state copy should remain explicit that the absence is within the observed sample, not platform-wide.

## 12. What counts as success

The primary success criterion is **a working live acquisition pipeline**, not forcing a specific topic to appear.

Required production success evidence:

- exact deployed SHA verified;
- one workspace remains allowlisted;
- exactly `bluesky:live_sample` is admitted;
- at least one successful production collection;
- nonzero valid observations;
- nonzero pipeline processing;
- current source health available;
- zero unexpected provider/model operations;
- zero notification sends;
- no cross-workspace exposure;
- no 5xx/error cluster;
- rollback path tested.

For the user-facing page:

- if real data forms eligible Trend objects, the page displays them;
- if observations exist but no Trend object passes the current evidence thresholds, the page says live source is active but no current matches were found.

Do not lower evidence thresholds just to make the UI non-empty.

## 13. Stage 3 follow-up

After Stage 2 is stable, a separate task may enable post outcome tracking.

That task should:

- verify native analytics rights for the connected account/provider;
- enable `POSTRIFF_METRIC_READS` only after rights are confirmed;
- verify t0 / +1h / +24h / +7d rows;
- verify unavailable != zero;
- verify +24h like-for-like baseline;
- keep follower conversion unavailable until a qualified matching `follows/profile_visits` contract exists.

This is not required to fix the current empty Trends page.

## 14. Tests

### Unit / contract

Add or update tests for:

- Bluesky production policy manifest validation;
- exact operation allowlist;
- zero-cost explicit budget path;
- denied model/store-embedding/share/train rights;
- provider flag off -> no dispatch;
- operation absent -> no dispatch;
- another workspace -> no dispatch;
- expired/revoked policy -> no dispatch;
- policy/contract version mismatch -> no dispatch;
- recent source health cannot be forged from feature flags.

### PostgreSQL

Verify:

- provider contract immutable insert;
- source policy immutable insert;
- system/provider/workspace budget rows;
- job creation;
- budget reservation/fencing;
- batch completion;
- cursor advancement;
- outbox event;
- pipeline consume;
- delete/revoke;
- tenant isolation;
- rollback leaves evidence consistent.

### Browser/API

Verify at desktop and mobile:

- Stage 1 acquisition-off state;
- Stage 2 unverified state;
- Stage 2 active-source state;
- active-source/no-matches state;
- actual Trend result when seeded by deterministic fixture;
- source degradation state;
- no horizontal overflow;
- axe/accessibility;
- page mount performs stored GET only and starts no acquisition itself.

### Production

Run a bounded production smoke with the real internal workspace:

- inspect exact deployment SHA;
- inspect exact allowed operation list;
- inspect exact workspace allowlist;
- wait for normal cron dispatch;
- verify one bounded live Bluesky collection;
- verify recent source health;
- verify valid observation count;
- verify pipeline/outbox progress;
- open authenticated `/app/trends`;
- verify source-status copy corresponds to durable evidence;
- verify another workspace is denied using an authenticated API path;
- inspect logs for bounded Trend errors;
- verify no model or paid provider call occurred.

## 15. Rollback

Rollback is flag-first.

1. Disable `RAFII_TREND_PROVIDER_OPERATIONS_ENABLED`.
2. Remove `bluesky:live_sample` from `RAFII_TREND_ALLOWED_OPERATIONS`.
3. Revoke or expire the source policy if the source itself must be stopped.
4. Confirm no new ingest jobs dispatch.
5. Allow maintenance/revocation/retention work to continue.
6. Keep durable receipts/evidence required by the current deletion/retention contract.
7. Do not delete rows merely to make dashboards look clean.

If Stage 1 itself must be rolled back later, use the existing core-flag rollback path.

## 16. Non-goals

This task must not:

- activate X/Reddit/TikTok/Instagram/LinkedIn discovery;
- claim all-platform coverage;
- turn on JEV/model enrichment;
- turn on notifications;
- enable follower-growth optimization;
- fabricate Trend objects;
- lower evidence thresholds solely for UI population;
- scrape with browser cookies or private sessions;
- create shared cross-workspace evidence;
- modify unrelated dirty worktrees;
- bundle Stage 3 analytics activation into Stage 2.

## 17. Implementation order

1. Re-check repo/default branch/HEAD and production alias SHA.
2. Re-check current production Stage 1 state.
3. Re-check current official Bluesky Jetstream service/protocol/host constraints.
4. Add activation operator script.
5. Add immutable reviewed contract/policy fixture support.
6. Add source-status derivation from durable evidence.
7. Update API/type/UI contracts if `active/degraded` states are added.
8. Add unit/PostgreSQL/browser tests.
9. Run local full focused gates.
10. Review diff for unrelated changes.
11. Commit/push implementation branch.
12. Merge through normal release branch checks only after review.
13. Deploy exact merged SHA.
14. Apply one workspace-local provider contract/policy/budgets.
15. Enable exactly one provider operation.
16. Observe normal cron live smoke.
17. Verify authenticated UI/API/DB/logs.
18. Run rollback rehearsal.
19. Record a production release receipt.

## 18. Human-only blockers

Stop rather than inventing a workaround if any of these are unresolved:

- current Bluesky service terms/host/protocol do not match the reviewed capability;
- production database write access is unavailable;
- exact internal workspace identity cannot be verified;
- current release SHA cannot be tied to the production alias;
- the current source policy cannot be justified for the requested storage/display/retention rights;
- production external network access to the pinned Jetstream endpoint is blocked.

Do not bypass these by scraping another network or silently broadening provider rights.
