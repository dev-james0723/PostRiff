# Production Release and Recovery Runbook

**Owner: A only.** B–F produce tested commits; G supplies independent evidence. No worker lane deploys independently or merges directly into production. This is the same release as implementation, not an optional follow-up.

## 1. Baseline and integration

Read exact origin/production branch and current active PRs. At preparation, remote consumer-saas was `3da806f0e31a01396a3bd4a9e27f66f9b21ce816`; re-resolve at execution. The primary local worktree is dirty and behind that ref, so use isolated worktrees. Preserve unrelated social/Library/domain-migration work and collaborate with their owners. Do not force-push a shared branch, reset/clean/stash someone else's work, or cherry-pick unreviewed unrelated features.

A owns the integration branch and merges tested lane commits in dependency order. Freeze a candidate SHA for G. A change after G's tests invalidates affected evidence and requires rerun; a moving branch name is not evidence. Check the final diff for accidental secrets, package-manager churn, unrelated files and hardcoded old domains.

## 2. Environment and privacy

Reuse existing Vercel project and model/auth/DB paths. Verify actual production project binding before deploying; do not create a similarly named replacement project. Reuse relative same-origin API URLs; validate rafii.io, login callbacks, CORS/Origin checks, private media, CSP, microphone policy and preview protection. Do not remove old OAuth callbacks/webhook routes or blanket-redirect them as part of this UI integration.

Set OpenUI installation telemetry off before local and CI dependency installs. Leave new Gateway/Autofix/observability vendors off unless previously authorized and verified. Never print secret values into commands, logs or the release receipt. Missing credentials: inspect available approved environment/secret management first; ask only for the genuinely missing authorization step, not 'send me all your keys'.

Suggested feature flags (new names; A may map to existing flags and document the mapping):
- `RAFII_GENUI_ENABLED`: rendering and presentation generation eligibility.
- `RAFII_GENUI_ACTIONS_ENABLED`: guarded reversible actions/proposals through original policy.
- `RAFII_GENUI_EDITS_ENABLED`: incremental semantic presentation edits.
- `RAFII_GENUI_FOUNDER_ENABLED`: founder-only surface/capability eligibility.

Development and unapproved environments default off. During this release, after gates pass, enable the full tested feature set for intended eligible production users. Persistently off flags or internal-only demo access are not the final state. Existing plan/role restrictions remain; enabling flags never grants domain privileges.

## 3. Schema and route changes

Prefer existing run/message artifact fields. Only add technical storage/indexes necessary for safe revision/idempotency/leases; coordinator allocates migration names/sequence and verifies live schema first. Test migrations on private DB, keep old readers compatible, use narrow bounded backfill if required and avoid destructive downgrade. Do not delete old conversations or rebuild accounts.

If a parser/stream route is added under `/api`, its explicit rewrite must precede the current catch-all to Python. Test exact production route resolution and authentication. Do not assume the example Next `/api/chat` works with Rafii's routing. No broad WSGI/ASGI migration unless a recorded compatibility failure makes the minimal adapter insufficient.

## 4. Release sequence

1. Run all new tests and launch-critical existing regressions on integrated SHA; G verifies all nine real journeys and security/accounting/fault/device gates.
2. Complete required live provider tests within existing authorized spend and confirm usage capture. Preview success does not waive production smoke.
3. Open/update PR with scope, contract/library hashes, migration/route impact, tests, screenshots, known external dependencies and rollback plan. Use existing required CI/protection and auto-merge workflow when eligible; do not bypass failing checks for speed.
4. Merge only the accepted candidate or reconcile the merge commit and rerun affected tests. Push/merge through the real production branch and existing Git/Vercel pipeline; no separate unrelated deploy.
5. Confirm deployment identity and running SHA, then verify canonical rafii.io through authenticated routes using a controlled workspace and non-destructive data. If deployment protection blocks the test, use existing approved access, never weaken protection globally.
6. Enable internal/test scope first for an immediate smoke and then the intended eligible production audience after all checks pass. This bounded rollout is part of this same delivery, not a week-long feature deferral. Verify flags in actual runtime, not just an env file.
7. Verify navigation, ordinary text fallback, generated views, a safe reversible edit/proposal, history reload, private media and correct credits on production. Do not publish/send/charge/phone real users as a smoke test.
8. Record final state in `release-receipt.json` and human-readable receipt; provide James the production result, not only a preview link.

## 5. Kill switch and rollback

On cross-tenant exposure, unauthorized effect or unexplained billing duplicate: immediately disable GenUI actions/generation using the approved feature-control path, preserve evidence and notify the release owner. On renderer/provider-specific fault: disable the affected capability, serve native results and keep stored business state unchanged. Do not repair a visual failure by rerunning a committed domain action.

A rollback restores the last verified application deployment while retaining additive compatible records and the original ledger. Reconcile in-flight provider attempts, pending reservations and action idempotency entries first; retain unknown cost states for proper accounting, not assumed zero. Restore flags deliberately. Validate old-client read/fallback of new artifacts and native approval access. Never drop new storage or delete history merely to revert the UI.

Perform a rollback/flag drill in preview before production. Record the previous verified deployment ID/SHA at execution time rather than guessing from an old message. Restoring production requires the same known-good origin/auth checks.

## 6. Required release receipt fields

`status` (`verified_production` only when complete, otherwise `blocked`/`partial`), `scope`, `final_commit_sha`, `merge_sha`, `pr_url`, `ci_results`, `deployment_id`, `deployment_sha`, `canonical_origin`, `verified_at`, `timezone`, `library_versions_and_hashes`, `contract_hash`, `migrations`, `feature_flag_state`, `eligible_audience`, `journey_results`, `gate_results`, `real_provider_evidence`, `real_database_evidence`, `physical_device_evidence`, `model_attempt_and_cost_summary`, `rollback_deployment`, `rollback_drill`, `known_unverified_items`, `remaining_human_action`.

No field is filled with 'done' without an evidence reference. Use null/unverified explicitly when unknown. Do not count queued jobs, unmerged PRs, ready preview deployments or generated screenshots as verified production.

## 7. Handling genuine external blockers

Resolve missing in-repo code, schema mappings, stream adapters, test setup and orchestration autonomously. For OAuth/provider approval, new billing/egress consent, an absent secret, or essential physical-device access, complete independent work and report the exact smallest prerequisite plus its affected gate. Do not ask James to decide basic engineering implementation details. Do not wait idle or re-send the same generic blocker report. Do not claim guaranteed next-day launch in the presence of unresolved required gates.
