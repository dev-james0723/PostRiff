# Rafii Dial call repair — 2026-09-28

Status at initial handoff: LOCAL CANDIDATE. The user subsequently approved deployment in this chat. Release verification is in progress; no paid live call is authorized.
Base: 4f686a72dc3960dc93d27241160af5b1325fd5e5, the production deployment inspected during this task (dpl_4NNSHpEegYSyRR9CiNQSNGhEuaxt).

## Findings

1. Manual requests were explicitly limited by `daily_calls < 6` in the shared request/dispatch planner. The SQL count included failed requests. This was a Rafii limit, independent of Dial.
2. The deployed Dial transport supplied no application User-Agent, so urllib used its Python client signature. Reproducing its GET `/api/v1/self-hosted` returned HTTP 403, Cloudflare, `error code: 1010`. An unauthenticated control with `User-Agent: Rafii/1.0` and `Accept: application/json` instead reached the API's normal HTTP 401 `Unauthorized` response. The original request was reproduced again with no credentials and returned the exact 1010 body.
3. The live Dial dashboard displayed Audio mode enabled, the expected production WebSocket URL, and G.711 mu-law at 8 kHz in both directions. Dashboard settings alone do not establish that the deployment's API key can access this account.
4. Vercel's production environment export masks the API key. Initial probes using that masked value are NOT valid credential tests. The control 401 is expected and is not evidence of an invalid production key.

The transport defect is reproduced locally and is a concrete explanation for the observed pre-call 403. Its correction still requires an authenticated production setup check; a successful real call is not yet established.

## Changes

- Remove the manual six-request daily cap. Keep automatic-call limits, opt-in/verification, one-active-call gate, daily spending limits, idempotency, and ambiguous-call reconciliation.
- Identify the authenticated API client honestly as `Rafii/1.0` and request JSON. Keep the same fixed API origin, TLS verification and no-redirect handling.
- Preserve only the exact non-sensitive Cloudflare 1010 signature as a curated transport classification. Arbitrary response bodies are still discarded. No automatic retries were introduced.
- Display a specific network-block message rather than labelling this known infrastructure error as an account restriction.

## Validation

PASS: 20 phone unit tests and 22 Dial unit tests.
PASS: both `tests/phase2/postgres_phone_mode.py` and `tests/phase2/postgres_dial_phone.py` against a disposable local PostgreSQL with synthetic phone/model transports. Includes seven same-day failed manual requests through the real request and delivery ledger; no provider POST and no six-request rejection.
PASS: frontend `tsc --noEmit` and focused oxlint (zero warnings/errors).
PASS: `git diff --check`.

`validation_unavailable`: full local browser acceptance did not complete. First attempt exceeded startup allowance during Next.js compilation. With the allowance increased, the real browser reached `/app/account/notifications`, but the webpack compilation remained pending and the harness timed out after 300 seconds. No browser pass is claimed. Typecheck/lint and the real backend/SQL checks provide lower-level coverage; the new browser regression remains available for a built preview. Do not repeatedly retry an unchanged cold webpack harness; use a completed production build or inspect local compiler/resource contention first.

The full repository CI release suite was not run; this receipt covers the scoped checks above.

Evidence logs (local):
- `/private/tmp/dial-root-cause-phone-tests.log`
- `/private/tmp/dial-root-cause-dial-tests.log`
- `/private/tmp/dial-root-cause-postgres.log`
- `/private/tmp/dial-root-cause-typecheck.log`
- `/private/tmp/dial-root-cause-browser.log`
- `/private/tmp/dial-root-cause-web.log`

## Authorized next boundary

The user requested diagnosis, repair and removal of the six-call cap. Production release was subsequently explicitly approved by the user. A paid live call is still not authorized. Release procedure: refresh the production base, review the scoped diff, run required CI/preview checks, deploy, then use the owner-only Check calling setup action (GET only). A later explicit call approval needs the target and spending cap; do not place calls merely to test setup.

References:
- https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/
- https://docs.getdial.ai/api-reference/rest-api/self-hosted/get-self-hosted
- https://docs.getdial.ai/documentation/platform/self-hosted
