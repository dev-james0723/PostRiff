# Pinterest acceptance and capability matrix

Updated2026-10-17 UTC. Live product source `c8ff84fa0c7f95e4b0be5648fd2764a244c6282e`, approved second deployment sFLeor READY/promoted; receipt2848c722. Baseline7432 incorporated. **NOT PRODUCTION-READY.** Synthetic/disposable checks do not supply real acceptance. [New exact-source cloud result](evidence/boards-refresh-validation-20261017.json).

| Required acceptance | Status | Evidence / remaining requirement |
|---|---|---|
| Callback console registration | PASS | App1615884 exact rafii.io callback approved/saved/reload-verified2026-10-15. [Receipt](evidence/pinterest-callback-registration.json). Runtime code exchange and identity passed2026-10-17; existing consent reused. |
| Approved local5e4/current7432 sync | PASS | Both completed2026-10-17; current7432 mergeea4bbd36/cloudvvmpxv3mmg. [Receipt](evidence/current7432-validation.json). Same-type local sync approval standing. |
| Public OAuth onboarding | NOT RUN | Needs real eligible new user, provider consent, Standard and release gates. |
| Identity and boards | NOT RUN | Identity subtest PASS: actual official GET user_account200, business @jamesaucreates/id1126814906675966091. Boards NOT RUN: missing read-only UI entry being repaired. [Real receipt](evidence/pilot-real-oauth-20261017.json). |
| Token refresh | NOT RUN | Live access lifetime30days; no expiry manipulation. Explicit protected refresh fix is deployed; real cycle pending human reconnection. DisposablePG12callers→1mock refresh plus manual refresh/other-owner denial pass2026-10-17. |
| Reconnection | NOT RUN | No real authorization recovery. Fresh explicit reconnect/board scopes passed synthetically2026-10-17. |
| Multi-tenant isolation | NOT RUN | Separate real accounts pending; disposablePG tenant/same-tenant-other-owner/custody/Agent negatives PASS2026-10-17. |
| Image Pin publication | NOT RUN | No approved exact payload or provider Pin ID. Read-only pilot prohibits all Pin operations. |
| Pin verification/visibility | NOT RUN | No real read-back or visibility observation. Exact frozen-metadata/uncertain-outcome checks passed synthetically. |
| Scheduling | NOT RUN | Actual provider execution/edit/cancel/recovery unobserved; worker contracts tested synthetically. |
| Duplicate prevention | PASS | Synthetic concurrency/leases/final authority/known-ID persistence and no lost-response rePOST passed2026-10-17. Real provider behavior unobserved. |
| Account disconnection | PASS | Real scoped disconnect after normal human MFA at17:36:15Z; revoked=true, access/refresh erased.0real jobs, so nonempty cancellation remains synthetic. No provider consent revoke. [Real receipt](evidence/pilot-real-disconnect-20261017.json). DisposablePG ciphertext removal, stopped custody, pending/claimed callback cancellation, reconnect and expiry cleanup PASS2026-10-17. No remote revoke claimed. |
| AI Agent authorized end-to-end | NOT RUN | Registration/tenant/current-intent tests PASS2026-10-17; provider-data/write gates closed. |
| Standard Access | NOT RUN | Official console observed Trial active2026-10-17. No submission/approval evidence or actual demo video. |
| Production release/canary | NOT RUN | One approved private Trial quota/config/deployment completed on existing production resources, not public release. No approved canary Pin. [Deployment receipt](evidence/pilot-deployment-20261017.json). |
| Public availability | NOT RUN | Eligible customer's production journey not demonstrated. |
| Synthetic concurrent scale | PASS |1000 simultaneous arrivals/64workers;5156.91users/s;p50/p95/p99 87.42/161.33/168.12ms;0unexpected failures;20expected uncertain outcomes;0provider traffic,2026-10-17. In-process only. |
| Quota/security/callback binding | PASS | DisposablePG17.11 verifies app/host/username/expiry callback rejection and durable consumption, old-env custody denial, forced RLS/bounded DML/no TRUNCATE, quotas/recovery,2026-10-17. Actual PostgreSQL17.6 apply and privilege metadata PASS2026-10-17; no destructive/DML probe. [Apply receipt](evidence/pilot-quota-production-apply-20261017.json). |
| Scoped CI/browser | PASS |414Python/51Node,sixPG scripts,Agent,typecheck/lint(36warnings0errors)/build/synthetic browser,2026-10-17. Full-project CI NOT RUN. |
| Real private pilot execution | BLOCKED | Bundle approved and activated16:40:56Z, expires20:40:56Z. Real code exchange/identity PASS using prior consent. Boards/refresh/reconnect NOT RUN; disconnect PASS after human MFA. New-source remediation deployed under separate exact approval; fresh Pinterest Give access awaits human. [Receipt](evidence/pilot-real-oauth-20261017.json). |
| Provider retention/AI-data policy | BLOCKED | Exact data-flow clarification unresolved; policy/Agent provider-data gates remain closed. |

## Supported feature/access-tier gates

| Capability | Candidate | Bounded read-only Trial | Public Standard acceptance |
|---|---|---|---|
| OAuth/refresh/reconnect | Implemented/tested | Exact actor/workspace/username;≤24h code maximum,4h approved; real exchange/identity PASS, refresh/reconnect NOT RUN | NOT RUN |
| Board discovery | Bounded pagination/eligibility | Explicit official API or default Sandbox; two read scopes; activated, real boards NOT RUN | NOT RUN |
| Board sections | Implemented/tested publishing path | Excluded by egress/action gate | NOT RUN |
| Image Pin | JPEG/PNG≤10MiB Rafii limit; frozen review/approval/read-back | Prohibited; separate exact write approval | Standard/release/action gates |
| Scheduling | Existing durable Rafii timezone/worker infrastructure | Prohibited | Actual execution NOT RUN |
| Disconnect/pause | Atomic local authority/job/callback cancellation | Available after expiry; actual local disconnect PASS after human MFA | NOT RUN |
| Agent boards | Optional read tool and current-intent/data gates | Excluded from pilot | NOT RUN |
| Video/tagging/board mutation/updates/analytics | Separate future capability gates | Not enabled | NOT RUN |

Identity scope:user_accounts:read; profile/boards adds boards:read; approved image publication/read-back additionally needs pins:read,pins:write. No secret-board scopes; broader old grants rejected in read-only mode. API host selection is distinct from access tier. Sandbox entities/tokens are separate; Trial content is not proof of public visibility. Personal-account data may require Pinterest authorization; actual personal-account eligibility of app1615884 remains unverified. Approved business account identity succeeded; this does not establish personal-account access. [Official recheck2026-10-17](evidence/official-docs-recheck-20261017.json).
