# Spec-to-implementation review

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
