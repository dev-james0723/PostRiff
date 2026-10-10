# Independent final code review — Meta public discovery

Review date: 2026-10-10. Reviewer: delegated `meta_control` agent.

**Disposition: no open P0/P1 implementation findings identified in the reviewed boundaries after the fixes below.** This is a static code-review disposition for the exact dirty-worktree files hashed below. It is not a CI pass, deployment approval, Meta App Review approval, live-data acceptance, or an authorization to enable provider traffic.

Base Git HEAD: `b0d595f9a4dd62107f45cb084ccff672f2d2640b`. The working tree contains uncommitted changes; HEAD alone does not identify the assessed implementation.

## Independence and scope

Reviewed parent/other-agent changes in the Meta transport, runtime admission, worker, local quota deferral, retry/source health, migration 110 trust helpers, stored source status, HTTP endpoints, and public-source UI. Existing service/hosted authentication and shared store helpers were inspected where needed to trace behavior. The reviewer implemented `meta_control.py`; that file and its owned tests are deliberately excluded from this independent signoff. Enrollment requires the separate storage-agent review already requested by the coordinator.

No production files were changed during this review. This receipt is the only file written for the final review task.

## Resolved findings

1. **Workspace/trust lock inversion — resolved in the assessed source.** `load_authorization` takes the shared trust fence before locking the authorization and credential rows, but its joined workspace row is no longer included in `FOR SHARE`. The authenticated HTTP path can therefore hold its existing workspace update lock and acquire the exclusive trust fence without the previously reported cycle. Workspace deletion state remains checked by the query and SQL authorization helper. `test_runtime_admission_does_not_lock_workspace_row` exercises admission while another connection holds the workspace row; its source was reviewed, not executed by this reviewer.

2. **Known authorization failure retaining LIVE/trusted evidence — resolved in the assessed source.** For exact public Meta provider/operation pairs, 401/403 failure handling acquires the exclusive trust fence before writing the source-health suspension. Migration 110 now rejects authorization when the exact workspace/provider health row is `revoked`. That helper feeds runtime admission and the observation/ancestor validity chain, so committed suspension removes trusted descendants and prevents a LIVE status. The source-status query also reads `next_allowed_at`; an active cooldown yields PAUSED. A 429 cooldown does not itself revoke retained rights. The PostgreSQL regression covers 401, 403 and 429 through real `fail_attempt`, three-level lineage, and runtime admission; this reviewer inspected the test without claiming it passed.

3. **Unbounded DNS/slow body read — resolved by the default transport implementation.** All three adapters instantiate `MetaDeadlineTransport` when no test transport is supplied. One absolute monotonic deadline is passed through `_fetch`; both Instagram requests share the original 15-second operation deadline. DNS, TLS, response reading and child JSON parsing run in an isolated stdlib subprocess. The parent communicates only for the remaining deadline, then kills and reaps a surviving child. The parent checks elapsed time again before accepting the result. This bounds provider I/O under ordinary process scheduling; the receipt does not assert that unrelated database admission waits have a 15-second deadline.

4. **Sanitized HTTP metadata lost before retry admission — resolved.** Numeric status and bounded Retry-After survive as `MetaTransportError` metadata. Provider response bodies, original credential-bearing exceptions and raw headers are not forwarded. The worker passes only safe status/Retry-After values to its single retry owner. Terminal attempt exhaustion retains the provider cooldown, so a new job cannot immediately evade a 429 delay.

5. **Local quota denial consuming an external attempt — resolved.** Only the trusted `MetaCollector` reports its HTTP-start counter. A first quota denial with zero transport attempts returns through `defer_local`, releasing the reservation, restoring the attempt count, retaining the payload, and dropping the lease. A denial after Instagram's first request retains the already incurred attempt and usage accounting. The narrow worker and PostgreSQL regressions distinguish those cases.

6. **Persisted policy rights/retention mismatch — consumer enforcement present.** Runtime compares the supplied SourcePolicy with the immutable reviewed-policy capsule, including exact identity, scope, operation, rights and retention. SQL compares stored and manifest rights with the capsule, binds policy identifiers and scope, and prevents retention above the reviewed ceiling. This assesses enforcement of the capsule by other agents' code; it does not independently review this agent's enrollment implementation.

## Transport and UI checks

The transport allows only pinned Graph hosts and fixed versioned operation paths; rejects arbitrary destinations, extra credential headers and secret query parameters; refuses redirects; ignores provider `paging.next`; and bounds response bodies and returned IPC output. Tokens enter the child over stdin and are used only in the Authorization header, not command arguments or the environment. Child stderr is discarded. Safe errors are constructed outside caught provider exceptions. Synthetic transport results remain synthetic and cannot qualify as LIVE.

The UI uses the existing authenticated API client, workspace-scoped query keys, response schema validation and polling. GET requires the interactive authenticated workspace transaction; DELETE additionally requires `manage_connections`. Authorization IDs remain scoped to the authenticated workspace. Public source registration is not exposed by these HTTP routes. A fresh, valid, provider-response observation plus a separately reviewed third-party source identity is required for LIVE; the client removes a LIVE claim at its expiry deadline. The UI explicitly limits coverage to selected queries, hashtags or reviewed Pages and keeps optional JEV interpretation separate from measured trend data.

## Validation limits and remaining release gates

- This final pass used source/test inspection and SHA-256 capture only. It ran no test suite, browser session, live HTTP request, database migration, or provider/model call. No CI result is claimed here. Parent-owned cloud validation must be assessed separately against the same snapshot.
- The slow-child deadline test, isolated child round-trip test, credential boundary tests, quota/retry tests and PostgreSQL suspension/lock tests were inspected as regressions. Their presence is not an execution result.
- Actual public access approval, current scope/feature diagnostics, operator evidence, fresh consent, and a genuine permitted non-owned sample remain external acceptance gates. Published app status or synthetic fixtures do not satisfy them.
- Current Meta operation/field compatibility still requires the authorized canary/official-review evidence, particularly Instagram hashtag response fields. This review did not make a live Meta call or establish public App Review approval.
- Any change to the files below invalidates this exact snapshot receipt for that file and requires an appropriately scoped review/validation update.

## Assessed file fingerprints

SHA-256 captured at 2026-10-10T14:29:26.659365+00:00. Paths are relative to the worktree root above.

```text
9d6ea1718a3c465611388fc50a895ba60f859c09de542decbf370f5d8be29911  src/postriff_phase2/growth/trends/providers/meta_public.py
c50add5a9ffc0907b04b6108b5c48c18f627945785157a81eda97ee4206055e8  src/postriff_phase2/growth/trends/providers/meta_runtime.py
788d6d9b092c3b9ea164470592a6d40aeea989278185a5ee784a373a6ae3c750  src/postriff_phase2/growth/trends/providers/base.py
c70f2475b78d543f6355aae31ba0a4b23707299494f2aba648e7896d5140aa90  src/postriff_phase2/growth/trends/worker.py
777f44ed2e354a9098a66454b1284df227bc8e53e377bcca4d68ffde0f92aea1  src/postriff_phase2/growth/trends/jobs.py
91649dd164e50d10eb8cf70546b7eeb16ebfc90ad6e5c229420e3def8f9e2805  src/postriff_phase2/growth/trends/retry.py
819a41d0bce8dc8ba4d957216a185781788aa5809ec5bde012f4440bd5b12a9b  src/postriff_phase2/growth/trends/source_health.py
838d378d8fd7c343178d84dd050e626e31e2e4c647bc98ae8d12047d60d3acc9  src/postriff_phase2/growth/trends/store.py
0702c840ee4966bcf32fe367305245310ca981bf0db43f483d97bceebc569edf  src/postriff_phase2/growth/trends/meta_sources.py
fd14d72635eb8b1624d2981435cfd27d0a12336e7db1b22330139f4ce722e037  src/postriff_phase2/growth/trends/http.py
e4c6c8410192f421e8d831b7227eee23b12992bf29138509fdf4bea6692a298b  src/postriff_phase2/growth/trends/service.py
6a595b3bccb6fb53b962c69235156d13c972aeacee547e611790f2c1c239a6b5  src/postriff_phase2/hosted.py
49d7dea6cddcd3694c8e0617eb4ff94fbe6c6b168799d6848a2ef31f8306d342  migrations/postriff/110_meta_public_trends.sql
393ff4dd2fb8fdb9c5b609fe73de56f3e1106ddb226e3ff6a516a93248e02d4a  web/src/features/trends/public-sources.tsx
f18b466510ea52747062356df7c07999dcdad355a8882e202cbb2e7718d46e15  web/src/features/trends/public-source-types.ts
8eef811611450511766776a0102a858a2b8cf1179ff1f9af69321d0d440f4acd  web/src/features/trends/api.ts
c95b7965f21c0754180ea521fd98269000afc23d2deddab7d2c8028af8abe061  web/src/features/trends/hooks.ts
4a07272a2bf7c6c8d09e71af7120ee6550ee064c37a7b301e376fdb40cb8d529  web/src/features/trends/present.tsx
100f44b36a00a251a066669dee9fafefb08f50220f38c58c7790b8b8bd2f0a16  web/src/features/trends/trends-view.tsx
076c95420c62b1f46933d68bd27aba2a038dbd2ff4bcace4086c0264d0efb65b  tests/test_trend_meta_public.py
f2ccec97a27ece26f390d3ee6638ba10b2ade80582f85652c8c6fd490d9dae7c  tests/test_trend_meta_runtime.py
328e92e16763878b23a9b7af8f3d6f30030b9466b245c03530458fe466662a5a  tests/test_trend_meta_status.py
7b77ddae5ab6095e0ed6316b7db7ede7205985a86f2154ee1a5b34a959494836  tests/test_trend_meta_worker.py
b8f3a2cea335d6d38f8a832c6d6dbeebce764c747ac7e0979a9e055ec16e0c76  tests/phase2/postgres_trend_meta.py
```

Receipt: static review complete; no production execution or CI success claimed; usage/cost unknown.
