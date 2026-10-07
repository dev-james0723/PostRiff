# Spec-to-implementation review

## Current continuation coverage — 2026-09-30

**Local read workflow verified at `f48a1be242b36dc04664dbb91ba5257a21de5dcd`; hosted/full-v2 operational acceptance BLOCKED.** The historical table below describes foundation `be140fdbaad9e13093b3d42215b66ed0a2347a69` and is superseded where this current section states a completed local capability.

| Applicable milestone | Current status | Evidence / remaining limit |
|---|---|---|
| HTTP error classification through verifier/API/UI/audit | passed | Hosted transport regressions, persisted restricted audit codes, fixed UI errors and browser 429/503 route preservation; no raw provider response exposed |
| Source event -> materialized metric -> bounded query | passed locally | Existing check_failures v1; canonical synthetic check receipts, real PostgreSQL transaction and bounded fixed SQL; local fixture mode only |
| Genuine zero / unavailable / stale / partial | passed locally | Eligible success gives 0; absent source null; skipped source partial; old source stale; measured-only chart plus all-state table |
| Duplicate/conflicting/concurrent events | passed locally | Event identity/digest and source-receipt uniqueness; no inflated count or second materialization |
| Chart/table -> receipt -> grounded copilot | passed locally | Real 390/1440 Next/API/DB browser, zero relevant axe violations; persisted receipt snapshot and cited deterministic answer; no model call |
| Currency and proposed policy boundaries | passed within read-only scope | Pure native-currency kernels and DSL currency checks; MRR/financial policies remain unavailable/inactive; no financial authority claimed |
| Staging qualification / dedicated Control Preview | blocked | Compact discovered configuration/technical/approval table in staging-qualification.md; no approved dedicated project, identity, roles, region/retention or source/fixture admission |
| Remote source delivery | blocked | Scoped local commit exists; PR #83 evidence is updated separately. Push could trigger a consumer Preview and suppression/approval is unverified |

`evidence/read-workflow-acceptance.json` maps all 96 designed cases: **16 passed, 0 failed, 25 blocked, 55 out of scope**. Each passed case names current commit/test/log digest. Broader cases with only a local invariant remain blocked; billing, notifications, account commands, support delivery, monitors, experiments and engineering writers stay outside this iteration. The package's 66 historical validation checks are not product acceptance counts.

Current verification is in evidence/verification.json; the exact old aggregate is foundation-verification.json. No old broad-suite result is relabeled as acceptance of the current remote target. Safe hosted source adapters, policy activation, real MFA/role/transport/rollback qualification and full-v2 acceptance remain open. No catalog was expanded.

## Historical foundation gap review (preserved)

Authority: the byte-verified complete September 29 v2 spec and accompanying tech-pack. V1 is background only. Scope: the user's Phase 0 and Phase 1 boundary, read-only shell, safe metadata and analytical/intelligence foundations. Full v2 operational acceptance is not claimed.

| Requested item | Implemented evidence | Operational limit / next gate |
|---|---|---|
| Founder authentication and platform capabilities | `auth.py`, `hosted.py`, operator table, deny/epoch/MFA tests | Bind the actual verified founder UUID and enroll reviewed dedicated logins separately |
| AAL2/step-up and separate session | Verified upstream identity, MFA freshness, hashed opaque host cookie, idle/absolute expiry, revocation | Real Supabase MFA/account recovery and hosted login journey remain untested; no enrollment/backdoor |
| Ops domain/route and disabled flag | Exact-origin proxy/API gates, separate entrypoint and packaging, default flag false | Approve project, ops domain/TLS and staging/production mapping |
| Audit trail | Append-only role grants, request UUIDs, allowed/denied/prohibited content-free events | No independent immutable audit export; retention policy unresolved |
| Command/Overview | Versioned overview, source quality, metadata and receipt navigation | Unqualified business values explicitly unavailable; no production KPI claim |
| Users/User 360 and Workspaces | Canonical column-limited projections, UUID validation, capped read templates, suppression canary tests | No email/name/private customer body or unrestricted impersonation; support grants are later work |
| Business/product/AI/system analytics foundation | Authoritative 63-definition/44-chart catalogs, bounded DSL, query receipts, cursors/events/rollup schema, quality states, financial/retention golden kernels | Proposed definitions are not activated; materialization and approved policy consumption are not connected. No fabricated chart series |
| Logs/errors/deployments/check read models | Bounded source-health/engineering evidence projections and workbench, exact-SHA stage qualification | No live Sentry/GitHub/Vercel ingestion adapter/poller has been activated or connected; no code-check dispatcher |
| Founder Rafii tools/recommendation framework | Isolated typed read/proposal registry, deterministic named metric reads, persisted idempotent runs, evidence/expiry/schema validation | No paid language model, voice, customer memory, automatic proposal execution or scheduled investigation. Generic tool execution/custom saved-chart generation is not implemented |
| Reuse and sources of truth | Existing Supabase verifier, pure agent contracts, Rafii CSS/chart/query libraries, canonical billing metadata and existing release/DB harnesses | Billing/credits/notifications stay owned by existing systems; no duplicate financial writer or sender |
| Approval and engineering honesty | No financial/destructive/external/SQL/code effect route; separate suspected/reproduced/candidate/checks/merged/deployed/production-verified states | Future actions require complete digest/version/expiry/idempotency approval and source-specific verification, not this read-only candidate |

## Acceptance coverage and remaining work

The pack's 96 designed acceptance cases describe the complete v2 system. Its validator's 66 passing checks validate the package, not 96 executed product scenarios. The implemented tests exercise the Phase 0/1 subset; monitors, support delivery, billing commands, controlled patches and destructive lifecycle cases are deliberately not claimed as executed. See `evidence/verification.json` for actual counts, skips, environments and recoverable logs.

Before expanding authority in Phase 2, complete staging qualification and approve source access, data region/retention, financial metric policies and any provider/model budget. Connect bounded source adapters to existing canonical receipts, qualify rollup materialization and required engineering manifests, then test stale/missing coverage and provider evidence. The current foundation must continue to return unavailable until those qualifications exist. Implement the remaining rich copilot/chart behaviors if included in the next approved work package. No approval can be inferred from a successful local test or this PR.

The separate `rafii-control` Vercel project was not found during read-only discovery. A dedicated qualified Preview cannot be created under the current release policy without approved project/staging configuration. The existing consumer project is not a substitute for that deployment boundary. No Control Preview, production migration, merge, promotion, DNS change or live integration was performed.
