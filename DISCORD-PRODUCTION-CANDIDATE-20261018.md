# Discord repair Production candidate — 2026-10-18

Candidate only. Prepared in an isolated sparse worktree; no push, provider action, browser action, SQL, build, cloud job or deployment was performed.

- Public integration base: `7dc95e2e005cd10069b835867c5b8f8c47a9e391`.
- Complete private repair input: `4fdc09c362f19d41b3d7e66d9a004dfd78f9783a` (includes installation re-verification, original-text manual drafts and literal action classification fix).
- Native-input follow-up: `f54d103bd1583e6cddc25c59663042617ce0ef16`, applied by no-commit cherry-pick onto candidate `17e3844c69a61754fcf65c5c72db9eb26e303005`; all five input file blobs remain exact. The receipt update joins the same local integration commit.
- Verified common ancestor: `730d044078434638f31eb5ca0e57280307ff8317`. Private repair base 7f434 is not an ancestor of the public source.
- Scope: the original105 selected paths plus four additional follow-up paths and this receipt (110 paths relative to public). The five-file native-input follow-up modifies one already-selected browser path and adds two composer paths, one wiring regression and one non-deploy workflow. All original47 runtime paths, four schema migrations, requirements dependency, 30 Python/SQL test paths, browser tests and shared CI validation remain; the two additional runtime paths are the compact and expanded composers.
- Existing source worktree and other branches/worktrees were not edited.

## Preservation and resolution

- Native three-way application had exactly one unmerged path: src/postriff_phase2/store.py, common line79. The conflict was resolved by retaining the public missing/null legacy-trial guard and explanatory comments, immediately after the private Discord engagement-state redaction. All other private store changes remain.
- Combined store Git blob: `666652b3a3a02075f616a461af2bd2eddf7daf5d`.
- Combined store SHA256: `44b14967294ca52f893cbfddc8991b2e410eb91986e5a1443ffd78a5e589f19d`.
- Public store input SHA256 verified: `3544297905808d81032e6387fca03522cf248b210d5ea29baa7914fccbf032f9`.
- All78 public-only changed paths remain byte-identical to the public base, including public tests, Pinterest validation/native recording scripts and evidence. The sole shared path preserves the public trial hunk in the union.
- Public AMR freshness blob remains `fd4fde903ce8bdcec4e78e7f3bf887ffc7bd5d4e`; Pinterest scope validation remains `ac5617a585cfc34ffa478ab9ba8fef2471902519`; web platform/Trial copy remains `60ddc4dae8083af1a08188cd51555414e64fef07`.
- Of the original105 selected paths,102 remain byte-identical to the private4fdc repair. The explicit adaptations are the combined store.py, omission of only package.json script test:discord:capacity:jcb, and the browser regression updated by exact f54d103b. All other package metadata and commands remain identical to the repair input.
- Both .james-cloud-build.json and .depot/workflows/james-cloud-build.yml retain exact public bytes in the index and sparse working tree.

## Explicit exclusions

| Git path | Reason |
| --- | --- |
| `.depot/workflows/discord-admission-api-diagnostic-v1.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-admission-observer-diagnostic-v1.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-capacity-pipeline-workers16-api12-v5.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-capacity-stage-a-workers16-api12-v5.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-capacity-stage-b-v2.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-capacity-stage-b-workers16-api12-v5.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-capacity-stage-b-workers16-parent16-v4.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/discord-capacity-stage-b-workers16-v3.yml` | Standalone capacity/diagnostic qualification workflow; not required by retained runtime, regressions or non-capacity CI. |
| `.depot/workflows/james-cloud-build.yml` | Preserve exact existing public JCB routing; no private task remapping. |
| `.james-cloud-build.json` | Preserve exact existing public JCB routing; no private task remapping. |
| `scripts/discord-capacity-extended-depot.py` | Standalone capacity/source-qualification controller; not imported by retained runtime or tests. |

Partial exclusion: the new package command test:discord:capacity:jcb is omitted. No product/security/schema/test path was excluded.

Retained capacity-related inert dependencies: tests/phase2/postgres_discord_capacity.py is imported by the preserved capacity-control and approval-receipt regressions; scripts/discord_capacity_sources.py is imported by the non-capacity integrated validation source manifest; that contract also requires scripts/discord-capacity-cloud.sh. The owned-runner and generic-suite guards remain unchanged. Retaining these files does not authorize executing their capacity workload. No capacity job or new JCB capacity mapping was created.

The shared consumer-ready workflow retains the guarded, bounded Discord P0–P4 validation step and its timeout. The generic PostgreSQL catalog continues to fence owned Discord suites into their explicit guarded routes.

## Lightweight validation

- PASS: git diff --cached --check; no unmerged entries; store.py AST syntax; package JSON parsing and exact one-command omission.
- PASS: all selected paths and modes accounted for; all78 public-only path blobs preserved; the five native-input follow-up files match exact f54d103b blobs;102 untouched private4fdc paths remain exact; public runtime pins; both public routing files physically and in the index; exact combined store blob.
- validation_unavailable: runtime/unit/SQL/browser/build validation was not authorized in this delegated materialization or follow-up integration task. Root must qualify the new combined commit through the separately authorized cloud CI and affected actual Home browser lane. Prior private-source or base-candidate passes do not qualify this exact combined source. No CI was dispatched here.
- No provider intent, environment, secret, approval, entitlement or activation was changed. Migration source presence does not establish database application.

## Native-input follow-up and remaining qualification

The compact and expanded textareas adopt exact currentTarget.value on standard input events, retain the existing onChange path, attachment ordering, caret and IME behavior, and deduplicate the same native event across the two callbacks. Home free-save guards, entitlement checks and backend commands remain unchanged.

The updated component regression covers exact Unicode/whitespace and callback behavior. The actual Home browser lane covers instance and prototype native setters, destination re-render, Expand, normal typing, free-save readiness without generation, and zero API writes at1280/390. This is prepared coverage, not a claimed browser pass.

The dedicated workflow is an exact-PR-head, same-repository, non-deploy Linux cloud lane. It installs existing pinned dependencies, runs the focused unit/type/lint checks, prepares a provider-fenced synthetic fixture, and exercises real Home in isolated Chromium. Workflow source presence is not execution or a result. Root owns its later qualification and any push/PR.

Five exact follow-up Git paths:

```text
.github/workflows/discord-composer-input.yml
web/src/features/agent/home/expanded-idea-dialog.tsx
web/src/features/agent/home/idea-composer.tsx
web/tests/discord-connections-browser.cjs
web/tests/home-attachments-wiring.test.cjs
```

## Selected delta paths

Git paths below are the original105 selected common-to-repair delta. The native-input list above contributes four additional unique paths; its connections-browser path was already selected. This receipt is the only other tracked path.

```text
.env.example
.github/workflows/consumer-ready.yml
docs/consumer-ready/secret-allowlist.json
migrations/postriff/124_discord_rate_limits.sql
migrations/postriff/125_discord_service_grants.sql
migrations/postriff/126_discord_worker_projection.sql
migrations/postriff/128_discord_lease_protocol_fence.sql
requirements.txt
scripts/discord-browser-cloud.sh
scripts/discord-capacity-cloud.sh
scripts/discord-ci-cloud.sh
scripts/discord-engagement-cloud.sh
scripts/discord-integrated-validation-cloud.sh
scripts/discord-p4-validation-cloud.sh
scripts/discord-validation-cloud.sh
scripts/discord_capacity_sources.py
scripts/linkedin_test_fence/sitecustomize.py
scripts/postriff_disposable_postgres.py
scripts/postriff_pg_suite.py
src/postriff_phase2/account_deletion.py
src/postriff_phase2/automation_runs.py
src/postriff_phase2/campaigns.py
src/postriff_phase2/channels.py
src/postriff_phase2/connection_review.py
src/postriff_phase2/contracts.py
src/postriff_phase2/discord/__init__.py
src/postriff_phase2/discord/authorization.py
src/postriff_phase2/discord/engagement.py
src/postriff_phase2/discord/message_content.py
src/postriff_phase2/discord/oauth.py
src/postriff_phase2/discord/rate_limits.py
src/postriff_phase2/discord/worker.py
src/postriff_phase2/hosted.py
src/postriff_phase2/hosted_app.py
src/postriff_phase2/hosted_social.py
src/postriff_phase2/hosted_worker.py
src/postriff_phase2/manual_drafts.py
src/postriff_phase2/oauth.py
src/postriff_phase2/outcomes.py
src/postriff_phase2/permissions.py
src/postriff_phase2/postgres_pool.py
src/postriff_phase2/publisher.py
src/postriff_phase2/social_connectors.py
src/postriff_phase2/store.py
tests/discord_engagement_reuse_proof.py
tests/discord_engagement_ui_fixture.py
tests/discord_ui_fixture.py
tests/phase2/discord_p4_schema_fixture.sql
tests/phase2/fixtures/discord_legacy_worker_claim_5f93f375.py.txt
tests/phase2/fixtures/discord_rate_limits_baseline_ee30.py.txt
tests/phase2/postgres_discord_admission_index_probe.py
tests/phase2/postgres_discord_authorization.py
tests/phase2/postgres_discord_capacity.py
tests/phase2/postgres_discord_connections.py
tests/phase2/postgres_discord_engagement.py
tests/phase2/postgres_discord_rate_limits.py
tests/phase2/postgres_discord_worker.py
tests/test_context_lens.py
tests/test_discord_capacity_approval_receipt.py
tests/test_discord_capacity_controls.py
tests/test_discord_destinations.py
tests/test_discord_engagement.py
tests/test_discord_installation_reverification.py
tests/test_discord_oauth_lifecycle.py
tests/test_discord_presend_retry.py
tests/test_discord_publish_authorization.py
tests/test_discord_rate_limits.py
tests/test_discord_worker_lifecycle.py
tests/test_hosted_job_dispatch.py
tests/test_hosted_wave1_connectors.py
tests/test_manual_drafts.py
tests/test_pinterest_production_prep.py
tests/test_postgres_pool_controls.py
tests/test_postriff_pg_suite_controls.py
web/package.json
web/src/components/application/post-preview/manifest-preview.tsx
web/src/features/agent/home-view.tsx
web/src/features/analytics/analytics-view.tsx
web/src/features/automations/run-decision.tsx
web/src/features/automations/run-history.tsx
web/src/features/channels/channel-card.tsx
web/src/features/channels/channels-view.tsx
web/src/features/channels/connect-return.tsx
web/src/features/channels/connect-sheet.tsx
web/src/features/channels/destination-picker.tsx
web/src/features/channels/discord-engagement-panel.tsx
web/src/features/inbox/coverage-strip.tsx
web/src/features/inbox/inbox-view.tsx
web/src/features/queue/job-dispatch.ts
web/src/features/queue/job-sheet.tsx
web/src/features/queue/publication-receipt.tsx
web/src/features/queue/publish-approved-post-button.tsx
web/src/features/queue/queue-view.tsx
web/src/features/queue/schedule-dialog.tsx
web/src/lib/api/client.ts
web/src/lib/api/types.ts
web/src/lib/channels/discord-engagement.ts
web/tests/agent-ui-e2e/run.cjs
web/tests/agent-ui-e2e/scenes.cjs
web/tests/channels-connect-deeplink.test.cjs
web/tests/discord-connections-browser.cjs
web/tests/discord-engagement-browser.cjs
web/tests/discord-p0-browser.cjs
web/tests/job-dispatch.test.mjs
web/tests/receipt.test.mjs
```

Machine-readable local evidence and the full review patch are retained under .depot/discord-production-candidate-evidence/ in this worktree. They contain source/diff metadata, not credentials or a source archive.

Usage receipt: local lightweight Git/file/AST controls only; no cloud or paid calls were submitted. Exact token usage and billing cost are unknown; no savings claimed.
