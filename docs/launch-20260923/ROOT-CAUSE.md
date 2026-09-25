# ROOT-CAUSE: POST 500 and the 42 shared network findings (FINAL-01)

Date: 2026-09-24 (America/Detroit). Integration writer: this session. Evidence run: `evidence/final/r1/`.
Scope: the two findings recorded by the 2026-09-23 22:24 visual sweep (`docs/design/rafii-v9/evidence/routes/summary.json`, `evidence/finish/api-browser.log`, `evidence/finish/visual.log`).

## 1. What was recorded, exactly

| Finding | Count | Recorded as | What the record could not tell |
|---|---|---|---|
| Console `Failed to load resource: net::ERR_FAILED` | 42 of 42 captures | console text only | URL, origin, initiator |
| Console `server responded with a status of 500` | 1 (first capture, `home 390x844 light`) | console text only | URL, method |
| API log `request.completed` status 500 | 1, request ID `3e5e73016b0744c7954e7ba6ba86062b`, `route: api` | by design the API logger omits URL, body, identity and exception text (`hosted_app.py:298`) | which endpoint, stack |

Horizontal overflow: 0 recorded. Axe violations: 0 recorded (axe was injected inline, so it did load). Neither of those numbers is a full accessibility or layout verdict.

## 2. Reproduction on the exact sweep environment

The sweep's servers were still running (web `127.0.0.1:4599`, `POSTRIFF_API_ORIGIN=http://127.0.0.1:4359`, harness `--credit-fixture`, disposable PostgreSQL `55469`, all cwd = candidate). The candidate source had not changed since the sweep except `tests/phase2/postgres_credits.py` (test-only).

`evidence/final/r1/diag-network.cjs` replays the sweep's first steps for a fresh synthetic principal (same cookies, localStorage and the same off-origin `route.abort()` rule as `web/tests/rafii-evidence.cjs:84`) and records only method, origin, pathname, resource type, status, `X-Request-ID`, JSON key names and the sanitized error code. No bodies, cookies or headers are stored.

Result (`evidence/final/r1/diag-red-sweep-env.json`):

| Finding | Method | Origin + pathname | Type | Result | Trigger |
|---|---|---|---|---|---|
| ERR_FAILED | GET | `https://va.vercel-scripts.com/v1/script.debug.js` | script (off-origin) | aborted by the test's own block rule, then `requestfailed net::ERR_FAILED` + console error | every page load: `<Analytics />` in `web/src/app/layout.tsx` |
| 500 | POST | same-origin `/api/auth/verify` (proxied to the API) | fetch | `500 internal_error`, body keys `["plan"]` | first load of `/app` for a new principal |

## 3. Root cause A: POST /api/auth/verify 500

Direct HTTP reproduction against the sweep proxy (same guard header and origin as the browser):

- 1 request for a fresh principal: `201`. A second sequential request: `201`.
- 2 concurrent requests for one fresh principal: exactly one `500 internal_error` in 6 of 6 trials.

Why two concurrent requests: `WorkspaceProvider.load()` (`web/src/lib/workspace/provider.tsx:83-110`) bootstraps when the workspace list is empty. In `next dev`, React Strict Mode runs that effect twice, so a first visit sends two `POST /api/auth/verify` at once. In production builds this double-invoke does not happen, but any two concurrent first-use requests reach the same code.

Where it fails (in-process reproduction, `evidence/final/r1/diag_bootstrap.py`, own disposable PostgreSQL, two threads + barrier):

| Service build | Failures |
|---|---|
| `HostedWorkspaceService` as in production (no fixture) | 0 of 8 calls |
| same + `scripts/launch_credit_fixture.py` (the sweep harness used `--credit-fixture`) | 4 of 8 calls: `psycopg.errors.UniqueViolation` SQLSTATE `23505` on `pr_entitlements_pkey`; frames `scripts/launch_credit_fixture.py:45:bootstrap` -> `src/postriff_phase2/billing.py:59:ensure_entitlement` |

`pr_bootstrap` itself is safe (it takes `pg_advisory_xact_lock` per user). The fixture then runs `Ledger.ensure_entitlement` in a second transaction. `ensure_entitlement` (`billing.py:48-62`) did `SELECT ... FOR UPDATE` (which locks nothing when the row does not exist yet) followed by a plain `INSERT` — a check-then-insert race.

This is not only a fixture problem. Production callers reach the same function without first locking the workspace:

- `Ledger.usage_view` (billing/usage read, `billing.py:150-151`),
- `Ledger.reserve` in legacy allowance mode (`billing.py:76`; credits mode locks `pr_workspaces` first, `require_plan_capacity` locks first).

So two first-time requests for a new workspace (for example the billing page and another usage read at the same moment) could return 500 in production.

Classification (FINAL-01 questions): an application race condition in production code, exposed by a test fixture and by dev Strict Mode; not a schema/seed mismatch, not a missing migration, not a stale server or wrong port.

### Fix

`billing.py` `ensure_entitlement`: `INSERT ... ON CONFLICT(workspace_id) DO NOTHING`, then the existing re-read (`SELECT ... FOR UPDATE`) returns the winner's row. The `pr_subscriptions` insert already used `ON CONFLICT DO NOTHING`. No response was changed to a fake 200; no exception is swallowed.

The client double request was left as is: once the server is race-safe the duplicate is harmless, and production does not double-invoke effects.

### RED -> GREEN

| Check | Before fix | After fix |
|---|---|---|
| `tests/phase2/postgres_entitlement_race.py` (new; 12 rounds x 2 entry points x 6 concurrent callers, disposable PostgreSQL via `scripts/postriff_disposable_postgres.py`) | exit 1: 24 of 24 races failed, `UniqueViolation:23505` (`evidence/final/r1/entitlement-race-red.log`) | exit 0: 24 races x 6 callers, one row each, no errors (`entitlement-race-green.log`) |
| `diag_bootstrap.py` with the credit fixture, 2 concurrent bootstraps | 4 of 8 calls failed | 0 of 16 calls failed |
| Browser flow on a fresh environment (API 4461 with the fix, web 4462) | — | see section 5 |

## 4. Root cause B: 42 x net::ERR_FAILED

`web/src/app/layout.tsx` rendered `<Analytics />` from `@vercel/analytics` 1.6.1 unconditionally. In development this package injects `https://va.vercel-scripts.com/v1/script.debug.js`; in a production build it injects `/_vercel/insights/script.js`, which exists only on Vercel deployments. The evidence script aborts every off-origin request (`rafii-evidence.cjs:84`), so every page logged one `ERR_FAILED`. It was the same optional telemetry request each time, not an API, chunk or font failure.

Fix: render `<Analytics />` only when `process.env.VERCEL === '1'`. Behaviour on Vercel is unchanged; locally no third-party script is requested at all, so nothing needs to be ignored.

Superseded 2026-09-24 (FINAL-12 sync): canonical's later commit `503ab56` ("make Vercel Analytics opt-in") renders `<Analytics />` only when `NEXT_PUBLIC_VERCEL_ANALYTICS === '1'`. It removes the same request for the same reason and is stricter (production analytics is off until the project enables it), so the merged file keeps canonical's line; the root cause and the local result (no third-party script requested) are unchanged.

Test-side rule: the newer canonical `rafii-evidence.cjs` filters every console message matching `/net::ERR_FAILED/`. That is a global ignore and would also hide same-origin failures, so the merged script instead records each aborted request by origin + pathname and reports it as a finding unless it is on a named, empty-by-default expected list (see FINAL-00 merge notes in `FINAL-LEDGER.md`).

## 5. GREEN browser evidence

Fresh environment started by this session: harness `127.0.0.1:4461` (`--credit-fixture`, disposable PostgreSQL `55761`, `POSTRIFF_RESEARCH=0`), web `127.0.0.1:4462` (`next dev --webpack`, `POSTRIFF_DIST_DIR=.next-codex-final`).

- Run 1: navigation timeout on the first compile of `/app/account/billing` (> 90 s under machine load); the old diagnostic lost its events. Recorded as INCOMPLETE, not as a pass.
- Run 2 (fresh principal, `/app` -> `/app/channels` -> `/app/account/billing`): 0 aborted off-origin requests, 0 failed requests, 0 HTTP >= 400, 0 console errors, 0 page errors.
- Run 3 (improved diagnostic that also records each successful visit; fresh principal): `visited /app`, `visited /app/channels`, `visited /app/account/billing`; 0 aborted, 0 failed, 0 HTTP >= 400, 0 console errors, 0 page errors (`evidence/final/r1/diag-green-3.json`).

Source for runs 2-3: candidate with only the two fixes above applied on top of the sweep snapshot (`billing.py` ON CONFLICT, `layout.tsx` Vercel gate).

## 6. Not concluded here

- The full 42-capture sweep has not been re-run on the merged snapshot yet; that belongs to FINAL-11.
- `Google Sans Flex` "Failed to find font override values" build/dev message: separate item in the ledger.
- The dev harness returns 500 for `GET /` on the API port when the legacy static bundle `studio/web/dist-alpha` is absent (seen when a preview tab opened the API root). Dev-harness only, outside the app flow; recorded in the ledger.
