# Security review — Phase 0/1 read-only candidate

Execution: inline source, SQL grants, contract, dependency, artifact and synthetic browser review. This is not an independent penetration test or a production security certification. Exact local results are in `evidence/verification.json`.

## Boundaries reviewed

- The consumer deployment excludes Control source, frontend, entrypoint, requirements and configuration. Control packaging copies an explicit source allowlist and produces its own function archive. Test identity injection is excluded. No consumer worker, payment executor, notification sender or customer agent is mounted.
- A server-owned active founder operator UUID, capability, environment and epoch are required. Editable Supabase metadata and workspace membership cannot enroll an operator. Migration 049 enrolls nobody.
- Supabase server `getUser` verification precedes claim decoding. AAL2 and a genuine MFA AMR timestamp within five minutes are required at exchange. Refresh `iat`, password and passkey claims alone do not establish step-up. The upstream identity/tombstone/revocation check repeats on each protected request.
- Founder tokens are random, opaque and stored only as hashes. Cookies are Secure, HttpOnly, host-only and SameSite Strict, with independent 30-minute idle and eight-hour absolute expiry. No founder token is persisted in browser storage. Operator revocation/epoch changes take effect on the next request.
- Exact host routing, exact unsafe-request Origin and CSRF proof are enforced server-side. A customer bearer alone does not authorize the founder API. Persisted atomic budgets bound exchanges, reads, queries and investigations. Prohibited requests use fixed audit action names and omit raw paths, messages and credentials.
- Non-local database configurations bind to the declared identity project. A Preview binds to distinct staging identity/data authority, rejects redirects/multiple hosts/options, requires distinct reader/session logins, verified TLS and session-mode connections. Actual hosted credentials and roles have not been provisioned or tested.
- Reader, session and ingestion roles are separate, non-superuser and non-BYPASSRLS. All Control tables force RLS and have environment policies. Browser/service-role grants are denied. Reader transactions are read-only, have a five-second timeout and use parameterized fixed templates with capped rows. Identity function search path and execute ACL are fixed.
- The non-login projection owner has BYPASSRLS only with SELECT on enumerated safe canonical columns. It cannot read customer bodies or mutate canonical accounting. Do not grant this owner role to an application login. Actual migration-role privileges must be qualified in staging before any hosted migration.
- Metric DSL schema, dimensions, currency, grain, interval, timezone and output limits are validated before reads. Missing/proposed metrics remain unavailable. Receipts carry query digests, definition versions and source watermarks. Golden kernels do not alter Stripe or the immutable credit ledger.
- Copilot context and capabilities are checked before idempotent reservation. Conflicting requests reject reuse. A failed reserved read stores a content-free blocked result. Founder tools reuse typed agent contracts, retain a separate namespace and expose no effect executor. Customer private content and memory are not loaded. Provider/model calls are zero in local verification.
- Engineering stages remain separate. A single provider green, skipped result, different SHA, missing manifest or infrastructure failure cannot establish checks-passed or production verification. No check dispatch, patch, merge or deployment route is mounted.

## Findings repaired with regression evidence

1. Local forwarding initially rewrote Host; the server correctly denied it. Bounded native HTTP forwarding preserves the configured host and remains forbidden on Vercel.
2. Error codes diverged from the authoritative v2 schema. Wire errors now use its budget, rate, idempotency and stale-preview codes.
3. Copilot reservation preceded context/capability checks. Validation now precedes reservation, and failures after reservation receive a safe terminal record.
4. Prohibited routes and dispatch denials lacked a complete request-bound audit outcome. Both now record content-free denied events.
5. The separate package omitted a reused locale data dependency. The allowlist includes it, and a fresh candidate imports the actual application and catalogs successfully.
6. A Preview could otherwise receive a miswired database DSN despite having a staging auth URL. Database project binding, distinct parsed logins, verified TLS and redirect rejection now fail closed.
7. The first CI run exposed local linked paths in a lockfile generated using shared dependencies. A new portability contract fails on any linked, extraneous or non-registry path. The corrected lockfile and fresh installation passed local type/build/browser checks; final CI outcome is reported separately.
8. Advanced-stage qualification originally covered only check records. Deployment/error regressions reproduced the gap; those records now preserve observations while withholding unqualified merge/deploy/production-verification status too.

## Remaining qualification gates

No production account, role, identity, migration, integration or deployment was exercised. Safe metadata views are verified against the disposable repository RLS schema; actual hosted grants, certificate configuration, staging dataset separation and provider capabilities remain unqualified. Append-only application permissions do not prevent a database superuser from altering audit history. Signed independent audit checkpoints, support grants, private-content retention/deletion, monitors, command approvals and executors belong to later authorized work.

The current scope contains no financial/destructive/external executor, SQL console, unrestricted impersonation, secret viewer or autonomous engineering writer. Re-review authorization and receipt binding before introducing any of these later capabilities.
