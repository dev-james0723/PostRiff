# Trustworthy Read-only Founder Home — LOCAL milestone

This adds one journey: Founder Home → GitHub Checks → chart/access table → selected receipt drawer → deterministic explanation. Business health remains unavailable. Metadata is manually captured from dev-james0723/PostRiff. No provider client or writer is mounted in the application, and no polling or model call occurs.

## Source and admission

`github-workflow/1` accepts a bounded first page (100 runs, 1 MiB response, 128 KiB normalized capture) of pull-request workflow metadata at an exact SHA. The server owns required workflow names and provider workflow IDs. Capture includes local capture/request UUID, requested/observed UTC times, exact resource URL, provider-body digest, manifest version, safe workflow metadata and total/returned coverage. It excludes log content, credentials and actor information.

The manifest scope is the two named Control/release workflows, not GitHub branch protection, all check suites, test results or release qualification. Completed success/failure count as known observations; skipped, missing, queued, incomplete coverage, cancellation and infrastructure failures retain distinct states and never become a known zero. Results describe the selected capture observed within the query's half-open interval; they do not sum 28 days of workflow history. Only grouping by suite and failure_class and comparison=none are supported. Invalid shape, unsupported comparison and excessive output fail explicitly.

The capture import CLI requires an explicit LOCAL disposable loopback DSN, exact file digest and `--admit-read-only` for provider-observed metadata. This is an operator-reviewed, manually asserted admission boundary, not automatic provider attestation. Review origin, metadata and digest before admission. It cannot confer GitHub access. Synthetic imports cannot be admitted. Provider-observed test captures stay unqualified until that explicit admission. Operational snapshots are LOCAL only and immutable; no business rollup is populated. Reader/ingest roles cannot update/delete snapshots; browser/session roles cannot import them. Hosted admission is not implemented.

Read-time trust checks admission, source version, conflicts, coverage and valid non-future timestamps before aging. A qualified observation older than 900 seconds is stale. Stale numbers are historical table evidence only; chart points require current measured values. Stored last observations remain inspectable with their qualification flag; they do not independently prove health.

## Query, receipt and failure semantics

Each normalized immutable receipt includes operator/environment, authorization request ID, full query/digest, interval/timezone/filters/comparison, definition versions, safe rows, source SHA/version/manifest/capture/request/URL/digest, coverage and calculated as-of/age. A bounded excerpt never implies a population total. GET, explanation and cached run reuse recheck capabilities, owner, expiry and synthetic environment restrictions. Legacy lineage also uses metric versions and stored result metric IDs.

The frontend uses query generations, normalized structural query comparison and snapshot identity to bind a result. Changed queries clear receipt selection and explanation. Last successful evidence stays explicitly labeled previous with its original query. A failed attempt has its own query and error. Explanations require explicit drawer selection, verify returned receipt IDs, and cannot overwrite after query change/close/reopen. The drawer contains a readable definition/quality/coverage summary and deliberate technical lineage drill-down. It traps Tab at the dialog edges and restores the opener on close/Escape.

Unsupported spend/activation/deployment/agent questions and unsupported filters/time/comparisons return a blocked read with no query receipt or inferred causal answer. Selected-receipt explanation uses the saved rows without re-querying. Provider calls=0; no executor exists.

Authorization `allowed` is separate from terminal `succeeded`/`failed`/`denied`. Generic failures return a fixed safe 503 and persist request-linked terminal audit where the audit store works. If the audit store fails, the request fails closed and emits a minimal safe correlation log; it cannot honestly promise a durable DB audit during a DB outage. Recovery of a running record older than two minutes records terminal blocked/unknown and a failed audit. Late completion cannot overwrite it or report success.

Bounds: HTTP request budget 10 seconds, independent terminal-audit budget 2 seconds, DB statement/connect timeout at most 5 seconds or the remaining budget, bounded startup role/timeout initialization and TCP keepalive/user timeout. Next forwarding times out at 13 seconds; browser reads at 14 seconds. A deadline can terminate only cooperating operations. The manual injected client must honor its timeout and is never mounted on the application. Failure tests use fake provider faults and real PostgreSQL sleep/cancel/process exit; they are not a live provider-load SLA.

## Upstream revocation contract and hosted gate

At exchange, a real hosted verifier must validate identity through approved Supabase `/auth/v1/user`, require AAL2 with MFA proof <=300 seconds, and map the server-held active founder operator. Each request rechecks founder session expiry (30-minute idle, 8-hour absolute), operator status/capabilities/auth epoch, and `rafii_control.identity_active(user, upstream_session)`.

That restricted SECURITY DEFINER function checks a non-deleted profile, no account tombstone and no matching `pr_session_revocations` row. It is NOT a live Supabase session-introspection call on every request. The hosted release must establish and verify how every upstream logout/session revocation/deletion reaches this projection; a missing synchronization path is a hard blocker. Tests prove local insertion of a revocation denies an existing cookie and fail closed on identity-store outage. They do not prove actual hosted Supabase logout/revocation, genuine MFA, TLS or role enrollment. Test-only synthetic identities/bootstrap are excluded from packaged source.

## Delivery boundary

Parent is unpublished LOCAL continuation c16747efcaa298a05477d1fda680d23cb9108dad, not older remote be140fdbaad9e13093b3d42215b66ed0a2347a69. The isolated local clone branch is codex/rafii-founder-home-20260930. Its origin points to the original local checkout; do not push there. Source upload, merge, deploy, hosted role/identity enrollment, migrations/configuration and paid operations are not authorized. The original checkout is preserved.

Source upload needs an already-approved verified route that guarantees no deployment from the push. No such route is verified here. A later hosted milestone separately needs approved project/domain/environment, restricted dataset/logins/secret delivery, migration ownership and number, identity/MFA/revocation synchronization, internal Next/API transport, exact-SHA hosted CI/TLS/CSRF/RLS/recovery/rollback verification and retention/access policy. This milestone authorizes no shared deployment setting change to create that route.

## Reproduce LOCAL checks

Use existing dependencies; do not install provider SDKs or load consumer secrets.

- `.control-venv/bin/python scripts/rafii_control_pg.py` starts a uniquely ported disposable PostgreSQL cluster, reapplies 049/051/052 twice and runs all Control tests. It never accepts a hosted DSN.
- From control-web: `node --test tests/*.test.mjs`, `node node_modules/typescript/bin/tsc --noEmit`, `node node_modules/oxlint/bin/oxlint app proxy.ts`, `node node_modules/next/dist/bin/next build --webpack`.
- `.control-venv/bin/python scripts/rafii_control_pg.py --browser --browser-only --home-browser --capture /absolute/reviewed-capture.json --evidence-dir /absolute/new-proof-directory` starts the actual local built Next application and WSGI/restricted PG. The fixture identity is explicitly synthetic. The reviewed public capture is manually admitted only into this disposable DB. Browser fault interceptions supplement real integration.

Fresh acceptance logs, screenshots, immutable manifests, commit/changed-file list and all 12 condition results live in the session's `rafii-home-implementation/README.md`. Historical tracked evidence remains historical. A source candidate, local test or provider workflow success is not uploaded source, staging qualification or production acceptance.
