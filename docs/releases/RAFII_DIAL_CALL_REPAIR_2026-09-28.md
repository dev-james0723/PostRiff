# Rafii Dial call repair — 2026-09-28

Status: initial transport/cap repair deployed through PR #49; a single authorized real call reached the phone but failed voice acceptance. Follow-up voice repair is under validation. Deployment remains authorized; the one-call authorization has been consumed.
Base: 4f686a72dc3960dc93d27241160af5b1325fd5e5, the production deployment inspected during this task (dpl_4NNSHpEegYSyRR9CiNQSNGhEuaxt).

## Findings

1. Manual requests were explicitly limited by `daily_calls < 6` in the shared request/dispatch planner. The SQL count included failed requests. This was a Rafii limit, independent of Dial.
2. The deployed Dial transport supplied no application User-Agent, so urllib used its Python client signature. Reproducing its GET `/api/v1/self-hosted` returned HTTP 403, Cloudflare, `error code: 1010`. An unauthenticated control with `User-Agent: Rafii/1.0` and `Accept: application/json` instead reached the API's normal HTTP 401 `Unauthorized` response. The original request was reproduced again with no credentials and returned the exact 1010 body.
3. The live Dial dashboard displayed Audio mode enabled, the expected production WebSocket URL, and G.711 mu-law at 8 kHz in both directions. Dashboard settings alone do not establish that the deployment's API key can access this account.
4. Vercel's production environment export masks the API key. Initial probes using that masked value are NOT valid credential tests. The control 401 is expected and is not evidence of an invalid production key.

The transport defect is reproduced locally and is a concrete explanation for the observed pre-call 403. After deployment, the authenticated production setup check passed. One real call reached the phone; successful two-way audio is not yet established.

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

The initial cold-development browser attempt timed out. This was resolved by completing a production build and running the phone browser suite against `next start`: PASS, including the transport diagnostic, real local request/dispatch, phone UI and mobile accessibility. All external phone/model transports in this local acceptance were synthetic.

Full GitHub CI passed on dac637c: release gates run 36372717843 and browser scenes run 36372717875. PR #49 merged as c87593f369839b43448be3e161da2115229ded6b. Vercel production dpl_Ci82yVcxFiTGgu7QcLru6pZSaSs5 reached READY and owns https://postriff-phase2-private.vercel.app. The signed-in production setup action returned “Dial is ready to create a call. This check did not place one.”

Evidence logs (local):
- `/private/tmp/dial-root-cause-phone-tests.log`
- `/private/tmp/dial-root-cause-dial-tests.log`
- `/private/tmp/dial-root-cause-postgres.log`
- `/private/tmp/dial-root-cause-typecheck.log`
- `/private/tmp/dial-root-cause-browser.log`
- `/private/tmp/dial-root-cause-web.log`

## Authorized real test and follow-up

The user separately approved exactly one call to verified phone ending 0208, at most 60 seconds, existing balance/rates, no top-up. Production `RAFII_PHONE_MAX_SECONDS=60` was checked before the single button click. On 2026-09-28 at 03:32:34 UTC, call 423cfbe6-07de-4462-b4a2-185fdb32ff6d was created, answered and ended after 11 seconds. The user reported ringing but no voice / no response after pressing 1. This is FAILED audio acceptance, regardless of the old UI's completed label. No second call was placed.

Runtime evidence: signed Dial media upgraded with HTTP 101; the Live stream then emitted invalid_request_error. Existing diagnostics curated the code/parameter to other, so the exact remote error detail cannot be recovered from that log. Local inspection found a concrete contract defect: the telephone greeting omitted the required nullable `delegation_id` field, while browser voice supplied it. The installed official OpenAI SDK InstructionsAppendEventParam rejects the exact outgoing greeting with `delegation_id: Field required`. Adding explicit null passes. The fallback commentary had the same omission and is repaired too. This is a reproduced defect consistent with the production failure; a second real audio test is still required for end-to-end confirmation.

The follow-up also persists `live_failed` independently of carrier completion, keeps it failed for either callback order, and still reconciles duration/usage. Curated diagnostics now admit the specific missing_required_parameter and delegation_id constants; arbitrary error bodies remain excluded. Diagnostic persistence errors cannot prevent hang-up.

Follow-up validation: SDK regression failed before the fix (`/private/tmp/dial-live-schema-red.log`); 28 phone/media tests passed after correction. Both disposable SQL suites passed, including official SDK schema validation and carrier-first/media-first failure ordering (`/private/tmp/dial-live-postgres.log`). This follow-up is not yet deployed at this receipt revision. Additional paid calls require a new explicit authorization after the deployed fix is reviewable.

References:
- https://github.com/dev-james0723/PostRiff/pull/49
- https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/
- https://docs.getdial.ai/api-reference/rest-api/self-hosted/get-self-hosted
- https://docs.getdial.ai/documentation/platform/self-hosted
- https://developers.openai.com/api/docs/guides/voice-websockets?api=live
