# Pinterest acceptance and capability matrix

Updated2026-10-17 UTC. Live product source `e2e5169ff19ac268c0a0ad06994f67b41f69f949`, deployment2tFM READY/promoted20:28Z; source receipt10486d8b. Earlier real read-only provider acceptance was on qualified c8/sF. Baseline7432 incorporated. **NOT PRODUCTION-READY.** Synthetic/disposable checks do not supply real acceptance. [Deployed-source cloud result](evidence/boards-refresh-validation-20261017.json).

| Required acceptance | Status | Evidence / remaining requirement |
|---|---|---|
| Callback console registration | PASS | App1615884 exact rafii.io callback approved/saved/reload-verified2026-10-15. [Receipt](evidence/pinterest-callback-registration.json). Runtime code exchange and identity passed2026-10-17; existing consent reused. |
| Approved local5e4/current7432 sync | PASS | Both completed2026-10-17; current7432 mergeea4bbd36/cloudvvmpxv3mmg. [Receipt](evidence/current7432-validation.json). Same-type local sync approval standing. |
| Public OAuth onboarding | NOT RUN | Needs real eligible new user, provider consent, Standard and release gates. |
| Identity and boards | PASS | REAL official identity200 and boards200 on2026-10-17, same approved business account. Empty items/valid shape/no bookmark; eligible board selection and sections NOT RUN. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Token refresh | PASS | REAL refresh_token POST200 at19:33:32Z, same-account identity200, DB rotation/expiry updated. Normal human fresh sign-in; no security bypass. Automated expiry-triggered live recovery remains NOT RUN. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Reconnection | PASS | REAL new authorization transaction2a93315a exchanged/consumed19:12:39Z after earlier local revocation, same stable business account, two read scopes. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Multi-tenant isolation | NOT RUN | Separate real accounts pending; disposablePG tenant/same-tenant-other-owner/custody/Agent negatives PASS2026-10-17. |
| Image Pin publication | NOT RUN | No approved exact payload or provider Pin ID. Read-only pilot prohibits all Pin operations. |
| Pin verification/visibility | NOT RUN | No real read-back or visibility observation. Exact frozen-metadata/uncertain-outcome checks passed synthetically. |
| Scheduling | NOT RUN | Actual provider execution/edit/cancel/recovery unobserved; worker contracts tested synthetically. |
| Duplicate prevention | PASS | Synthetic concurrency/leases/final authority/known-ID persistence and no lost-response rePOST passed2026-10-17. Real provider behavior unobserved. |
| Account disconnection | PASS | REAL final human-completed DELETE20019:43:55Z; DB revoked and both token ciphertexts erased.0real jobs,0active future jobs; nonempty real cancellation and Pinterest consent revoke NOT RUN. Earlier403 preserved. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| AI Agent authorized end-to-end | NOT RUN | Registration/tenant/current-intent tests PASS2026-10-17; provider-data/write gates closed. |
| Standard Access | NOT RUN | Official console observed Trial active2026-10-17. No submission/approval evidence or actual demo video. |
| Production release/canary | NOT RUN | One approved private Trial quota/config/deployment completed on existing production resources, not public release. No approved canary Pin. [Deployment receipt](evidence/pilot-deployment-20261017.json). |
| Public availability | NOT RUN | Eligible customer's production journey not demonstrated. |
| Synthetic concurrent scale | PASS |1000 simultaneous arrivals/64workers;5007.90users/s;p50/p95/p99 90.28/165.99/171.89ms;0unexpected failures;20expected uncertain outcomes;0provider traffic,2026-10-17. In-process only. |
| Quota/security/callback binding | PASS | DisposablePG17.11 verifies app/host/username/expiry callback rejection and durable consumption, old-env custody denial, forced RLS/bounded DML/no TRUNCATE, quotas/recovery,2026-10-17. Actual PostgreSQL17.6 apply and privilege metadata PASS2026-10-17; no destructive/DML probe. [Apply receipt](evidence/pilot-quota-production-apply-20261017.json). |
| Scoped CI/browser | PASS | New local candidate e2e5169f:463Python/51Node,7PG scripts,Agent,typecheck/lint36warnings0errors/build/synthetic browser,2026-10-17. [Receipt](evidence/capabilities-validation-20261017.json). Full-project CI NOT RUN. |
| Real private pilot execution | PASS | Bounded read-only exchange/identity/empty boards/real refresh/reconnect/final local disconnect verified2026-10-17. No publication, analytics, Agent or new-user/public proof. Original expiry20:40:56Z unchanged. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Provider retention/AI-data policy | BLOCKED | Exact data-flow clarification unresolved; policy/Agent provider-data gates remain closed. |

## Supported feature/access-tier gates

| Capability | Candidate | Bounded read-only Trial | Public Standard acceptance |
|---|---|---|---|
| OAuth/refresh/reconnect | Implemented/tested | REAL exchange/identity/refresh/reconnect PASS for exact approved actor/workspace/business account; final grant locally revoked | Public new-user acceptance NOT RUN |
| Board discovery | Bounded pagination/eligibility | REAL official GET200/empty boards PASS; no eligible destination selected | NOT RUN |
| Board sections | Implemented/tested publishing path | Excluded by egress/action gate | NOT RUN |
| Image Pin | JPEG/PNG≤10MiB Rafii limit; frozen review/approval/read-back | Prohibited; separate exact write approval | Standard/release/action gates |
| Scheduling | Existing durable timezone/worker path; server_schedule metadata fixed in local candidate | Prohibited by original read-only scope | Actual execution NOT RUN |
| Disconnect/pause | Atomic local authority/job/callback cancellation | Available after expiry; actual local disconnect PASS after human MFA | NOT RUN |
| Agent boards | Optional read tool and current-intent/data gates | Excluded from pilot | NOT RUN |
| Native Pin analytics | New local gated adapter/metric-worker implementation;4 native metrics, UTC window definitions | Not enabled; no pins:read; live analytics NOT RUN | Separate release/permission/schema gates |
| Comments/reply | Official public API5.28.0 has no operation; explicitly Unsupported with reason | No unofficial workaround | Provider capability absent |
| Video/tagging/board mutation/updates | Separate future capability gates | Not enabled | NOT RUN |

Identity scope:user_accounts:read; profile/boards adds boards:read; approved image publication/read-back additionally needs pins:read,pins:write. No secret-board scopes; broader old grants rejected in read-only mode. API host selection is distinct from access tier. Sandbox entities/tokens are separate; Trial content is not proof of public visibility. Personal-account data may require Pinterest authorization; actual personal-account eligibility of app1615884 remains unverified. Approved business account identity succeeded; this does not establish personal-account access. [Official recheck2026-10-17](evidence/official-docs-recheck-20261017.json).

## Local capability candidate — 2026-10-17

Product ddbcdde7 plus fixture correction **e2e5169ff19ac268c0a0ad06994f67b41f69f949**, built once as READY dpl_2tFM, not promoted. New exact-source [JCB qd2tzg2hn0](https://depot.dev/orgs/jf34f85hr0/workflows/qd2tzg2hn0) PASS:463Python/51Node,7disposablePG17.11 scripts, typecheck/lint36warnings0errors/build/synthetic browser. Remote/controller0,178.406s.3302local input hashes; remote3555-file fingerprint matches submission. [Receipt](evidence/capabilities-validation-20261017.json). Analytics uses only user_accounts:read,boards:read,pins:read, is disabled by default, requires reviewed provider/execution/current tenant grant plus metric workspace admission and the separately applied schema. No production metric migration or new scopes have been approved/applied. [Official API audit](evidence/capabilities-official-api-20261017.json).

## Current deployment boundary

The exact code deployment was later approved/executed once. READY2tFM/sourcee2e/receipt104 has2217matchingfiles and health/configured PASS. Promotion **BLOCKED**: shared production Discord-token updatedAt changed20:11:17Z before build; actual value change unverified. Live remains sF/c8; flag-off new-source UI NOT RUN. [Receipt](evidence/capabilities-deployment-20261017.json) · [Disposition](NEXT-ACTION-PROMOTION-CONFIG-DRIFT.md).

## Final promotion result

Separate direct APPROVE accepted known shared Discord-setting metadata drift. One promotion completed20:28:14Z, CLI0; rafii.io and project production target2tFM verified, health200/configuredtrue and actual Channels GET200/private read-only UI PASS. Earlier BLOCKED promotion is resolved. No second build/OAuth/provider call/SQL/analytics/public enablement; original20:40:56Z expiry unchanged. Discord behavior unverified. [Receipt](evidence/capabilities-promotion-20261017.json). All provider-write/public-release gates above remain unchanged.
