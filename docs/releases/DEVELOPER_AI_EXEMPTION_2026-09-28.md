# JamesAU0723 developer AI quota exemption

Status: APPROVED FOR RELEASE; production UUID setting added, deployment pending. No paid AI calls or phone calls were made for validation.

## Verified target and proposed activation

The user identified JamesAU0723 as their developer/test account and requested removal of AI usage limits. A read-only query in the production Supabase dashboard on 2026-09-28 returned one matching account:

- Project: `buoyhkbodnhzngaotoel` (`postriff-phase2-private`).
- Account name: `jamesau0723`; display name: `Classical Music Life`.
- Immutable auth user ID: `b167161d-37f4-4bc3-ae22-2482c982e5a0`.
- Production setting added: `RAFII_AI_UNLIMITED_USER_IDS=b167161d-37f4-4bc3-ae22-2482c982e5a0`.
- Production application: `postriff-phase2-private.vercel.app`.
- Candidate rebased onto `9785cc0ebace9153b4b71fd49d13087b9d657d83` on `origin/consumer-saas`, preserving PR #53 minute funding and reconnect support.

Activation requires deploying this candidate and applying the above server-only setting to the web/backend and any separately deployed phone runtime using this ledger. Recheck the release branch before integrating; do not deploy the unrelated dirty primary checkout. No schema migration, historical cost reset, fake subscription or credit grant is required. The setting is empty by default; changing a username/profile/request cannot enroll an account.

## Behavior

- Exempts the authenticated user from per-request and rolling 24-hour provider-cost caps, workspace/global budget stops, writing/media allowances, and credit balance/quote gates.
- Keeps immutable reservations, actual/unknown settlement, idempotency and provider cost records. Exempt reservations explicitly hold no shared budget scopes, including after revocation; their costs cannot exhaust other users' budgets.
- Ordinary users retain their existing limits, including in a shared workspace. Removing the UUID restores future quota checks. Old exempt reservations still settle according to their original recorded scopes.
- The authenticated usage response exposes `aiUsageExempt: true` and no credit-gating object for this actor. Existing chat controls therefore do not require a credit limit. The authenticated reasoning catalogue lifts quota-only unavailable hints.
- Phone credit quotes use the same account exemption. Active call identity is still checked for Manager turns.
- Permissions, source consent, publication approvals, explicit automation spending approvals, global AI pause, invalid/unapproved policy refusal, feature switches, input/context/output bounds, concurrency, phone verification/duration/telephony safety controls and upstream provider limits remain. This is an application quota exemption, not free provider service or permission to run paid tests.

## Validation

- Full Python unit suite: **1,696 passed** with `PYTHONPATH=src:tests POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0 /private/tmp/rafii-trend-release-venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.
- Existing budget-policy DB integration: PASS (normal request/person/workspace/global ceilings and pause behavior).
- New developer DB integration: PASS (above all caps, zero allowances, immutable accounting, unknown settlement after revocation, duplicate settlement, forged metadata, ordinary actor rejection, real credit-plan tables without grants).
- Existing credits DB integration: PASS (real hosted service with a synthetic provider, quote binding, reservation/settlement, concurrency, expiry, permissions and pause reconciliation).
- `git diff --check`: PASS.
- No frontend source/layout changes. Production authenticated acceptance is pending deployment; do not describe the account as already unlimited.

DB tests used the existing disposable PostgreSQL runner on dedicated localhost port **55491**, because another session owned 55438. A temporary mirror under `/private/tmp/rafii-developer-quota-tests` linked the candidate source/migrations and copied the runner/tests with only the hardcoded port replaced. Migration-owning tests ran in separate fresh databases. Initial test-harness failures (missing test modules/dependencies, occupied port, synthetic plan price and duplicate migration) were resolved; the final results above are the relevant evidence.

Evidence logs: `/private/tmp/rafii-developer-quota-full-unit-fixed.log`, `/private/tmp/rafii-developer-quota-db.log` (budget policy PASS), `/private/tmp/rafii-developer-quota-db-final.log` (developer test PASS; later credits migration collided), `/private/tmp/rafii-developer-credits-regression.log` (fresh credits run PASS).

## Remaining action and rollback

User approved commit, push and deployment on 2026-09-28. Run required release gates, deploy, and read back the authenticated usage response plus ordinary-account controls without making a paid provider call. A live generation test needs separately scoped cost authorization.

Rollback: remove the UUID from the server-only setting and redeploy/restart the affected runtimes. Keep the ledger unchanged.

The attempt to download the entire production environment was rejected by automatic approval review because it would expose unrelated secrets. No such download succeeded. Identity was instead verified through a narrowly scoped read-only dashboard query, so activation does not require downloading those credentials.

## Inbound immediate hangup repair (approved follow-up)

Production media upgraded to WebSocket (101) at 05:28:56 UTC for the reported inbound call, but no admission row was inserted. Read-only SQL found five prior sessions in 24 hours, none in the last hour, and three attached to authenticated calls. Exact nonsecret Vercel config readback: telephony minute ceiling 170,000 microdollars; unauthenticated greeting pool 1,000,000. The sixth greeting computed 1,020,000 and was silently rejected.

Fix: count only sessions without an authenticated call against the unauthenticated pool. Authenticated reservations already include the 45-second greeting, so this removes duplicate allocation without raising the pool or trusting caller ID. Hourly/caller throttles and failed/unknown greeting holds remain. Add bounded rejection diagnostics without codes, numbers or payloads. Pass the verified actor through inbound code issuance and continuation credit checks. No migration or historical data deletion.

Current-source validation: 1,699 Python tests passed; isolated PostgreSQL developer quota, signed inbound admission/agent integration, and phone duration/renewal suites passed. Added regression proves funded greetings release duplicate admission allocation while unfunded calls still stop; developer code issuance and renewal need no credit quote/grant. Logs: `/private/tmp/rafii-developer-release-unit.log`, `/private/tmp/rafii-developer-release-db.log`. All external providers synthetic; real calls 0.
