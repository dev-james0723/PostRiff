# Acceptance matrix — 2026-10-14

Only PASS / FAIL / BLOCKED / NOT RUN are used. A synthetic PASS below never upgrades a real/provider/production NOT RUN.

| Required acceptance | Status | Execution / evidence / date |
|---|---|---|
| Dedicated isolated staging | BLOCKED | Step A approval pending; no deployment or staging qualification. Proposal and source-provenance.json, 2026-10-14. |
| Public OAuth onboarding | NOT RUN | No live authorized-account consent. Synthetic OAuth custody/replay is independently tested below. |
| Identity and boards | NOT RUN | No real identity/board read-back. Numeric identity/eligibility/sections tested with synthetic responses. |
| Token refresh | NOT RUN | No real refresh cycle. Disposable PG: 12 concurrent callers caused exactly one injected refresh. |
| Reconnection | NOT RUN | Real authorization recovery needs approved staging/consent. Credential and consent fences implemented. |
| Multi-tenant negative authorization | PASS | Actual disposable PG, two synthetic tenants; cross-tenant read denied, local disconnect leaves other tenant unaffected. validation-summary.json, 2026-10-14. |
| Real two-account isolation | NOT RUN | No separate authorized Pinterest accounts or provider data. |
| Image Pin publication | NOT RUN | No approved real payload or provider Pin ID. Mock POST cases only. |
| Pin verification and visibility | NOT RUN | Synthetic exact metadata read-back PASS; actual provider read-back/visibility unobserved. |
| Actual scheduled execution/edit/cancel | NOT RUN | Existing scheduler reused; pure cancellation, dispatch fence and state lifecycle checks PASS. No approved live scheduled Pin. |
| Duplicate prevention | PASS | Synthetic lease/cancel/credential/source fence, known-ID retention, lost-create uncertainty and no second POST. CI tests/load, 2026-10-14. |
| Account disconnection | NOT RUN | Real provider consent revocation/real queued jobs unobserved. Disposable local credential removal and pending authority cancellation PASS; no remote revoke is claimed. |
| AI Agent end-to-end authorized action | NOT RUN | Live journey unavailable; optional read-only tool executor/registration are separately tested. |
| Provider retention/AI-data permission | BLOCKED | Current guideline restrictions need clarification for exact data flows; public POLICY_APPROVED and Agent provider-data gates remain off. |
| Standard Access | NOT RUN | No application submitted, no official Standard approval. |
| Production release and canary | NOT RUN | No push/merge/deploy/credentials/migration/enablement or real canary. |
| Public availability | NOT RUN | New eligible customer acceptance on rafii.io is not demonstrated. |
| Synthetic concurrent load | PASS | 1,000 simultaneous arrivals; 64 peak workers; 0 unexpected failures; 980 verified mock read-backs + 20 injected lost create responses retained uncertain; no real provider traffic. validation-summary.json, 2026-10-14. |
| Scoped security/CI/browser contracts | PASS | [JCB plbpx66q8j](https://depot.dev/orgs/jf34f85hr0/workflows/plbpx66q8j), remote exit 0. 132 Python + separate feature-on/off Agent registry + 42 Node tests, disposable PG, load, Hosted typecheck/lint/build, actual-component and preview browser scenarios. |
| Public policy/terms reachability | PASS | Independently HTTP 200 on both public URLs; substance/compliance certification remains NOT RUN. public-policy-reachability.json, 2026-10-14. |

The feature-on/off Agent registration passed in the same final scoped CI; source SHA is finalized in FINAL-RECEIPT. All measured values and raw receipt locations are in `evidence/validation-summary.json`; final shipping/test fingerprints are in `evidence/final-source-hashes.json`.

Synthetic load measured 4,235.87 users/second over 0.23608 s, p50 105.49 ms, p95 196.53 ms, p99 201.85 ms on the disposable 16-vCPU cloud runner with an injected 2-ms provider and 64 worker threads. This measures the in-process adapter/publisher harness. It does not measure HTTP hosting, a production scheduler/database, provider quotas, real OAuth, real account isolation or recovery of a lost real Pin ID. Its values must not be used as production capacity claims.

## v1 capability and access-tier gates

| Capability | Candidate v1 | Trial/Sandbox proof | Public Standard proof |
|---|---|---|---|
| OAuth identity/refresh | Implemented | Real NOT RUN | NOT RUN |
| Board list | Implemented, bounded | Allowed by current read-only proposal, real NOT RUN | NOT RUN |
| Board sections | Implemented/tested | Excluded by current Step A transport allowlist; further scope approval needed | NOT RUN |
| Image Pin | Implemented/tested; JPEG/PNG ≤10 MiB Rafii limit | Exact Pin approval + write-boundary approval required; creator-only content is not public proof | Standard + release + action approvals required |
| Scheduling | Existing durable Rafii worker at user's time zone; no invented native scheduling | Actual execution NOT RUN | NOT RUN |
| Disconnect/pause | Implemented locally; separate provider-settings consent removal | Live NOT RUN | NOT RUN |
| Agent board discovery | Optional flag OFF; no publication tool | Further approved destination/model-data scope required beyond A | NOT RUN |
| Video/product tags/board mutation/Pin updates/analytics | Separate future gates, not activated or promised | NOT RUN | NOT RUN |

Minimum image publishing/reconciliation scopes: user_accounts:read, boards:read, pins:read, pins:write. No secret-board scopes. Eligible personal-account access depends on Pinterest approval, including PINNER_DATA_ACCESS_DENIED restrictions; business eligibility is not a guaranteed entitlement either.
