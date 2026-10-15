# Pinterest acceptance and capability matrix

Updated2026-10-15 UTC, quota-hardening source `6d36716cfcc945fcc93a819ba243ffa870a1a799`, retaining earlier b99cf89a checks. **NOT PRODUCTION-READY.** Mock/synthetic evidence never supplies a real-account result. [Exact-source cloud receipt](https://depot.dev/orgs/jf34f85hr0/workflows/bcz5vdqznw) · [machine-readable evidence](evidence/pilot-current-production-validation.json).

| Required acceptance | Status | Evidence / remaining requirement |
|---|---|---|
| OAuth callback console registration | PASS | Approved app1615884 URI saved and verified after reload,2026-10-15. [Receipt](evidence/pinterest-callback-registration.json) · [Screenshot](evidence/pinterest-callback-registered.jpg). Runtime OAuth remains NOT RUN. |
| Quota migration least privilege | PASS | Cloud7lkkltn4d9 on disposablePG16.15: Supabase broad defaults, forced RLS, migration replay, bounded service-role DML and denied TRUNCATE,2026-10-15. [Receipt](evidence/quota-permission-validation.json). Production17.6 apply/parity NOT RUN. |
| Latest live security-baseline integration | BLOCKED | Live5e4f4e13 differs from current candidate. Automatic review rejected local merge pending exact approval; no merge executed. [Action](NEXT-ACTION-MERGE.md). |
| Public OAuth onboarding | NOT RUN | Needs exact authorized real account, consent and eligible-customer acceptance. Synthetic Authorization Code/state tests passed2026-10-15. |
| Identity and boards | NOT RUN | No real provider read-back. Synthetic pagination, account ID and username binding passed. |
| Token refresh | NOT RUN | No live refresh cycle. DisposablePG12 concurrent callers→1 mock refresh passed2026-10-15. |
| Reconnection | NOT RUN | No real recovery. DisposablePG fresh explicit consent after disconnect passed; UI helper retains board-read scope. |
| Multi-tenant isolation | NOT RUN | Required separate real accounts not tested. DisposablePG negative tenant/same-tenant-other-owner/custody/Agent tests PASS2026-10-15. |
| Image Pin publication | NOT RUN | No specifically approved real payload or provider Pin ID. |
| Pin verification/visibility | NOT RUN | No real provider read-back or visibility observation. Synthetic exact metadata/missing-ID uncertainty tests passed. |
| Scheduling | NOT RUN | Actual scheduled provider execution, edit/cancel/recovery unobserved; existing worker contracts tested synthetically. |
| Duplicate prevention | PASS | Synthetic concurrency, lease/final-authority checks, durable known ID and no lost-response resubmit; cloud2026-10-15. Real provider duplicate behavior unobserved. |
| Account disconnection | NOT RUN | Real consent removal/provider access stop unobserved. DisposablePG ciphertext removal, stopped token access, pending/claimed callback cancellation and fresh reconnect PASS2026-10-15; no remote revocation claimed. |
| AI Agent authorized end-to-end | NOT RUN | Optional read-only tool registration/tenant/current-intent tests PASS; provider-data/publication gates closed. |
| Standard Access | NOT RUN | App1615884 last console observation: Trial access active2026-10-15, after approved callback reload/read-back. No submission or official Standard approval. |
| Production release/canary | NOT RUN | No production DB/config/credentials/deployment/enablement or approved canary. |
| Public availability | NOT RUN | New eligible customer's production journey not demonstrated. |
| Synthetic concurrent scale | PASS | 1000 simultaneous arrivals/64 workers;4620.41 users/s; p50/p95/p99 96.10/180.68/186.30ms;0 unexpected/duplicate POST,20 expected uncertain responses,0 real provider calls. In-process harness only,2026-10-15. |
| Scoped CI/security/browser contracts | PASS |270Python/51Node, separate Agent registry, disposablePG incl browser-session guards, Hosted typecheck/lint/build/UI, remote/controller0,2026-10-15. Full-project CI NOT RUN. |
| Provider retention/AI-data policy | BLOCKED | Exact data-flow requirements unresolved; POLICY_APPROVED and Agent provider-data gates stay closed. |

## Supported feature/access-tier gates

| Capability | Candidate | Bounded read-only Trial pilot | Public Standard acceptance |
|---|---|---|---|
| OAuth identity/refresh/reconnect | Implemented/tested | Exact actor/workspace/username,≤24h; real NOT RUN | NOT RUN |
| Board discovery | Bounded pagination and eligibility | Two read scopes; Sandbox-only, real NOT RUN | NOT RUN |
| Board sections | Implemented/tested for publishing | Excluded by egress/action gate | NOT RUN |
| Image Pin | JPEG/PNG≤10MiB Rafii limit; frozen review/approval/read-back | Prohibited; separate exact write/Pin approval needed | Standard/release/action approval required |
| Scheduling | Existing durable Rafii timezone/worker infrastructure | Prohibited | Actual execution NOT RUN |
| Disconnect/pause | Atomic local authority/job/callback cancellation | Allowed even after expiry; real NOT RUN | NOT RUN |
| Agent boards | Optional read-only feature/data gates | Excluded until separately qualified | NOT RUN |
| Video/product tagging/board mutation/Pin updates/analytics | Separate future capability gates | Not enabled | NOT RUN |

Identity-only scope:`user_accounts:read`; profile+boards:`user_accounts:read,boards:read`; approved image publishing/read-back additionally needs`pins:read,pins:write`. No secret-board scopes. The pilot rejects prior broader grants rather than silently reusing their authorization. Personal-account access can require Pinterest approval (`PINNER_DATA_ACCESS_DENIED`); business-account eligibility is not a guaranteed entitlement. Sandbox boards/visibility are separate from live Pinterest, and neither Sandbox nor Trial results establish public visibility. See [pilot operation scope](READONLY-PILOT-CANDIDATE.md).

Fresh continuation preflight: live5e4f4e13/READY is not yet merged into the candidate; the exact local merge approval is pending. The rafii.io callback was saved and reload-verified; real OAuth remains NOT RUN. Credential pair/quota table remain absent. Team Pro/overdue alone does not prove deployment rejection because a later READY deployment exists. No deployment attempted. See FINAL-RECEIPT and NEXT-ACTION-MERGE.
