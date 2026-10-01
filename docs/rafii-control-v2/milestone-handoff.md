# Founder Control milestone handoff — 2026-09-30

**Local implementation and synthetic qualification complete. Hosted operational acceptance remains blocked.** This closes only the current read-only workflow milestone. The next activity is the founder's separate independent architecture/product audit; no broader redesign has begun.

## Checkout and delivery

- Worktree: `/Users/ouxianxing/.codex/worktrees/rafii-founder-control-v2/James-Au-Studio`.
- Branch: `feat/rafii-founder-control-v2`; remote: `https://github.com/dev-james0723/PostRiff.git`; target: `consumer-saas`, observed `1acd88a8b77c5e8a3f2b877dd927e755c2900a56`.
- Initial clean HEAD: `be140fdbaad9e13093b3d42215b66ed0a2347a69`. No reset, stash, cleanup, base merge or unrelated worktree edits.
- Implementation commit: `f48a1be242b36dc04664dbb91ba5257a21de5dcd` — Fix Control auth failures and complete synthetic read workflow.
- This handoff is included in the separate documentation/evidence commit. The final receipt gives its exact HEAD; `git log -2 --format=fuller` recovers both commits.
- [Draft PR #83](https://github.com/dev-james0723/PostRiff/pull/83) is open, unmerged, targeting `consumer-saas`. Its remote source remains `be140fd`; its successful Control/consumer CI and consumer Vercel status belong to that foundation. The local continuation has no remote CI result. Current milestone evidence is updated through PR metadata only.
- Source push is held: previous foundation push created a consumer Preview and branch-specific deployment suppression is unverified. No dedicated Control Preview has been created. Do not push under the present no-deploy instruction without verified approved suppression or explicit authorization covering that possible effect.

## Completed implementation

- `hosted.py:get_user()` now distinguishes upstream invalid authentication (401/403), rate limit (429), and unavailable transport/provider/malformed response (503). Success is bounded and requires a valid user UUID. Provider error bodies, headers and messages are not rendered or persisted. Typed failures carry safe request-bound codes through verifier, API, audit and fixed UI retry messages. Founder UUID/capability/MFA checks remain enforced.
- Existing catalog metric `check_failures` v1 follows the real source-receipt/event/projector/rollup/query path. Fixed parameterized read-only SQL caps source input at 1000, grouped output at the requested limit, and statement time at five seconds. The UI shows measured bars and an accessible full quality/lineage table; query receipts persist exact result snapshots, digest, version and watermark; deterministic copilot explains that same receipt.
- Demonstrated genuine measured zero, measured one, missing coverage as unavailable/null, skipped coverage as partial, and old evidence as stale. Duplicate and conflicting/canonical/concurrent replay, query overflow, receipt expiry, environment/currency separation, and unapproved financial-policy boundaries are covered. No catalog definitions were added or financial policies activated.
- Copilot status reads keep the same permission requirement and use a separate 120/minute read budget; the five/minute investigation budget remains enforced. Chart hidden-focus and table scroll-region focusability failures found during browser validation were repaired.

## Verification and evidence

- **61/61 Control tests passed; zero failures/skips; 14 exercised actual disposable PostgreSQL.** Migrations 049 and 051 each applied twice. Commands and raw-log digests: `evidence/read-workflow-checks.json`.
- **4 frontend contracts passed; lint zero errors/warnings; production build passed including typecheck.** Node 24.15.0 / Next 16.3.5.
- Real local Next → WSGI API → restricted PostgreSQL browser journeys passed at 390 and 1440 pixels, including projection/chart/table/receipt/copilot, absent source, 429/503 handling, authentication/CSRF/private canary/logout. **Zero page errors, zero workflow/Settings axe violations, no document overflow**; screenshots visually inspected. This is scoped accessibility evidence, not a complete accessibility certification.
- Fresh local allowlisted function archive passed: 688 files, 2,365,834 bytes, SHA-256 `8d818c8efbd4d6a8c41c18738eb43181b2c06bee68fd779a6b8081f0b4219279`. Changed-source secret scan: 20 files, zero findings. No deployment/runtime invocation occurred.
- Source manifest binds 72 files to the verified implementation. The 96 designed acceptance cases map to **16 passed, 0 failed, 25 blocked, 55 out of scope**. These are case classifications, not 96 executed product tests. Partial proof for broader blocked cases is retained explicitly.
- Historical broader consumer/Python/PostgreSQL results belong to the foundation and were preserved in `foundation-verification.json`; they are not current integration qualification. Failed RED/harness attempts remain in ignored recoverable raw logs.

## Genuine code versus synthetic qualification

The transport classification, authorization/audit handling, projector, materialized storage, bounded SQL, chart/table, durable receipt and deterministic explanation are implemented code. Their complete data workflow was executed using **synthetic identities and check events in a disposable local database**; no dashboard constants replace projection/query results. Fixture admission is enabled only by the excluded local test harness. Hosted construction stays disabled/unqualified and cannot silently consume synthetic measured results. There is no live source adapter qualification, paid model answer or hosted founder login acceptance.

## Staging, schema and remaining risks

- `staging-qualification.md` contains the compact separation of observed configuration, completed technical work and exact missing founder gates. Consumer staging/account access is not Control authorization. Required: dedicated Control project/team/spend, exact origin/RP/domain, actual founder UUID/capabilities, staging/production identity mapping, approved dataset/region/retention and staging-only migration/login enrollment. Credentials belong in approved secure environment storage, never chat.
- Actual hosted role/TLS/data separation, MFA/recovery/cookies/service routing, restore/rollback, and approved fixture/source admission must be qualified after authorization. No dedicated Control project was found in the 20 inspected Vercel projects; connector scope does not prove global resource absence. Vercel connector schema mismatch and omitted CLI Git settings leave deployment suppression unverified.
- Existing **049 is byte-identical**. **050 is occupied by pricing** (`050_free_lifecycle_bootstrap.sql`). New additive **051_rafii_control_read_workflow.sql** is reserved to this worktree and implemented; 047/048 concurrent reservations preserved. Only disposable 049/051 execution occurred. No hosted staging/production migrations, credentials or founder enrollment.
- No current scoped failing check remains. Wider acceptance remains blocked/out of scope: hosted operations, production-scale partitions/leases, customer escalation, model-output injection/fabrication handling, and actual ENOSPC reproduction are not proven by this milestone. Target branch has advanced; no reconciliation or current-target full consumer regression is claimed.
- Paid inference, live polling, notifications, financial/account actions and product engineering writers remain disabled. No merge, promotion, deployment, production configuration change or broader redesign.

## Updated documents and next step

Updated `implementation-log.md`, `security-review.md`, `spec-gap-review.md`, `README.md`, aggregate `evidence/verification.json`; added this handoff, `staging-qualification.md`, current preflight/source/acceptance/check/browser/workflow/archive/secret-scan evidence and four screenshots. Original foundation verification/archive receipts are preserved separately.

**Immediate next step:** run the requested independent architecture/product audit against this local committed candidate and evidence. After that audit, resolve the exact staging approvals and secure credentials; verify approved deployment suppression before source upload. A dedicated Control Preview requires authorization and successful hosted qualification first.
