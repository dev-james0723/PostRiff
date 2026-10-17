# Pinterest acceptance and capability matrix

Updated2026-10-17 UTC. Source `01cdf494c49e43099ef6b61401b84db138746c23`; baseline7432 incorporated. **NOT PRODUCTION-READY.** Synthetic/disposable checks do not supply real acceptance. [Exact-source cloud result](evidence/readonly-trial-validation.json).

| Required acceptance | Status | Evidence / remaining requirement |
|---|---|---|
| Callback console registration | PASS | App1615884 exact rafii.io callback approved/saved/reload-verified2026-10-15. [Receipt](evidence/pinterest-callback-registration.json). Runtime OAuth NOT RUN. |
| Approved local5e4/current7432 sync | PASS | Both completed2026-10-17; current7432 mergeea4bbd36/cloudvvmpxv3mmg. [Receipt](evidence/current7432-validation.json). Same-type local sync approval standing. |
| Public OAuth onboarding | NOT RUN | Needs real eligible new user, provider consent, Standard and release gates. |
| Identity and boards | NOT RUN | No real API read-back. Explicit official-API host path passed with synthetic transport2026-10-17. |
| Token refresh | NOT RUN | No live cycle. DisposablePG12 concurrent callers→1mock refresh passed2026-10-17. |
| Reconnection | NOT RUN | No real authorization recovery. Fresh explicit reconnect/board scopes passed synthetically2026-10-17. |
| Multi-tenant isolation | NOT RUN | Separate real accounts pending; disposablePG tenant/same-tenant-other-owner/custody/Agent negatives PASS2026-10-17. |
| Image Pin publication | NOT RUN | No approved exact payload or provider Pin ID. Read-only pilot prohibits all Pin operations. |
| Pin verification/visibility | NOT RUN | No real read-back or visibility observation. Exact frozen-metadata/uncertain-outcome checks passed synthetically. |
| Scheduling | NOT RUN | Actual provider execution/edit/cancel/recovery unobserved; worker contracts tested synthetically. |
| Duplicate prevention | PASS | Synthetic concurrency/leases/final authority/known-ID persistence and no lost-response rePOST passed2026-10-17. Real provider behavior unobserved. |
| Account disconnection | NOT RUN | Real account test pending. DisposablePG ciphertext removal, stopped custody, pending/claimed callback cancellation, reconnect and expiry cleanup PASS2026-10-17. No remote revoke claimed. |
| AI Agent authorized end-to-end | NOT RUN | Registration/tenant/current-intent tests PASS2026-10-17; provider-data/write gates closed. |
| Standard Access | NOT RUN | Last official console observation Trial active2026-10-15. No submission/approval evidence or actual demo video. |
| Production release/canary | NOT RUN | No approved production SQL/config/credentials/deployment or approved canary Pin. |
| Public availability | NOT RUN | Eligible customer's production journey not demonstrated. |
| Synthetic concurrent scale | PASS |1000 simultaneous arrivals/64workers;4238.33users/s;p50/p95/p99 102.60/192.69/198.96ms;0unexpected failures;20expected uncertain outcomes;0provider traffic,2026-10-17. In-process only. |
| Quota/security/callback binding | PASS | DisposablePG17.11 verifies app/host/username/expiry callback rejection and durable consumption, old-env custody denial, forced RLS/bounded DML/no TRUNCATE, quotas/recovery,2026-10-17. Production17.6 apply NOT RUN. |
| Scoped CI/browser | PASS |413Python/51Node,sixPG scripts,Agent,typecheck/lint(36warnings0errors)/build/synthetic browser,2026-10-17. Full-project CI NOT RUN. |
| Real private pilot execution | BLOCKED | Exact [existing-project external bundle](NEXT-ACTION-READONLY-PILOT.md), account/window and live consent pending; credentials/quota table absent2026-10-17. |
| Provider retention/AI-data policy | BLOCKED | Exact data-flow clarification unresolved; policy/Agent provider-data gates remain closed. |

## Supported feature/access-tier gates

| Capability | Candidate | Bounded read-only Trial | Public Standard acceptance |
|---|---|---|---|
| OAuth/refresh/reconnect | Implemented/tested | Exact actor/workspace/username;≤24h code maximum,4h proposed; real NOT RUN | NOT RUN |
| Board discovery | Bounded pagination/eligibility | Explicit official API or default Sandbox; two read scopes; not activated | NOT RUN |
| Board sections | Implemented/tested publishing path | Excluded by egress/action gate | NOT RUN |
| Image Pin | JPEG/PNG≤10MiB Rafii limit; frozen review/approval/read-back | Prohibited; separate exact write approval | Standard/release/action gates |
| Scheduling | Existing durable Rafii timezone/worker infrastructure | Prohibited | Actual execution NOT RUN |
| Disconnect/pause | Atomic local authority/job/callback cancellation | Available after expiry; real NOT RUN | NOT RUN |
| Agent boards | Optional read tool and current-intent/data gates | Excluded from pilot | NOT RUN |
| Video/tagging/board mutation/updates/analytics | Separate future capability gates | Not enabled | NOT RUN |

Identity scope:user_accounts:read; profile/boards adds boards:read; approved image publication/read-back additionally needs pins:read,pins:write. No secret-board scopes; broader old grants rejected in read-only mode. API host selection is distinct from access tier. Sandbox entities/tokens are separate; Trial content is not proof of public visibility. Personal-account data may require Pinterest authorization; actual eligibility of app1615884 remains unverified. [Official recheck2026-10-17](evidence/official-docs-recheck-20261017.json).
