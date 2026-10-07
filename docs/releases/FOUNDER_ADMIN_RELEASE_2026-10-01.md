# Founder Admin Intelligence release — 2026-10-01

Status: code released dark. PR #86 (P0) and PR #88 (P1/P2) are merged to `consumer-saas`, which deploys production. Founder mode stays off until the activation gates below pass. A code commit or passing local test is not signed-in production acceptance.

## Verified recovery checkpoint — October 1, 2026

- Production remains on `047d024e2f95cd409d4fcf2019a66ac6e765ae4e` (PR #88). A fresh authenticated `/api/health` read returned `status: ok`, `configured: true`; it still explicitly reports `customerValidated: false`.
- New production read-only preflight: deployment `dpl_6ETE4xeyvTDNpPSUpvQyLaiN2gTg`, October 2 at 02:34 UTC (October 1 at 22:34 Eastern). It verified the expected project, all **20 Founder migrations**, no missing dependencies, and no partial migration state. The deliberately failed build has no application alias. It ran **preflight, not repair**: redeploying the old staging artifact did not retain its per-build `FOUNDER_MODE` value.
- Staging's existing repair is confirmed in deployment `dpl_EduE1SZN6iap8ZXpXPWEwzWXUUwJ`: 42 view and two function grant gaps repaired; 30 forced-RLS Control tables and 12 browser-inaccessible public tables verified; temporary privileges removed.
- Production's initial apply and three restricted-login setup are confirmed by their deployment logs (`dpl_9pz7MKWC6mT4cguXXTzqBde5iLWq`, `dpl_6kEzRB4GmhToMXf3mjKX6m9CPAGe`). **The production grant-repair execution request was blocked by the tool safety layer and was not executed.** Do not substitute a different execution path or disable safeguards. This is still a blocking gate.
- The Vercel environment-name inventory has no `RAFII_CONTROL_*` settings. Migration **071**, its dedicated CI-ingest login/secret, watchdog configuration, founder enrollment and authenticated production acceptance are not completed by this recovery's code work.
- The recovery branch preserves the previously uncommitted Demo-overlay and CI-evidence changes. It also fixes the CI writer's private-schema lookup order for a legitimate SET-only login, and binds enrollment to a separately verified exact founder UUID. Local Control/PostgreSQL and web contract results are recorded in the recovery receipt; do not treat them as hosted activation.

## What ships

- **P0 (PR #86)**: Founder mode inside the Rafii app at `/founder`, Control v2 embedded at `/api/control/v2/*`, Live metrics with receipts, the 10k fictional Demo dataset, Founder Rafii (read, draft and preview tools only), the founder contact policy, incidents, briefings and the founder cron stage. Migrations 054–056.
- **P1/P2 (PR #88)**: revenue and MRR bridge, AI cost depth, product funnel, retention and risk, operations and support health, data health, founder voice, notifications and briefings, the founder ops workspace, and confirmed founder actions. Instrumentation migrations 057–060 and 062, Control views 063–068, 069 and 070.

Every metric that needs history says when collection started and how many days exist. Nothing unmeasured renders as 0.

## Historical post-merge baseline (superseded by the checkpoint above)

Immediately after PR #88, `/founder` redirected to `/founder/sign-in`, `/api/control/v2/*` answered 404 with the mount unset, and no Founder migrations had yet been applied to hosted databases. The migrations were subsequently applied as recorded above. Real calls, email and push remain off; do not use the old baseline to re-run initial activation blindly.

## Remaining owner activation gates, in order

1. **Re-read state, then complete the approved production grant repair.** The 20 Founder migrations are already recorded as applied. The pinned runner is `docs/releases/founder-admin-2026-10-01/activate_founder.py`; verify its source and migration SHA-256 pins. It distinguishes read-only preflight, initial apply and repair, uses one transaction and verifies cleanup. Require actual successful role-specific reads, not merely a successful ledger insertion or an error-free `GRANT` statement. Stop on a safety/approval refusal.
2. **Apply migration 071 separately after source review and staging qualification.** It is deliberately not in the original 20-migration pinned activation list. Do not edit already-applied migration bytes or silently add 071 to that historical ledger. Verify its restricted ingest writes and environment isolation on staging before production.
3. **Qualify the restricted connection credentials.** Session, reader and watchdog logins already have setup receipts; use or safely recover their credentials rather than broadening a login. Use the Supabase session pooler on port 5432 with `sslmode=verify-full` and the bundled root. The CI collector needs a separate dedicated ingest login, not the session/reader/watchdog or `postgres` credential.
4. **Configure production only after the database gates pass:** `RAFII_CONTROL_ENABLED=1`, `RAFII_CONTROL_MOUNT=embedded`, `RAFII_CONTROL_ENVIRONMENT=production`, `RAFII_CONTROL_ORIGINS` (the production origin), `RAFII_CONTROL_SESSION_DSN`, `RAFII_CONTROL_READER_DSN`, `RAFII_CONTROL_SUPABASE_URL`, `RAFII_CONTROL_SUPABASE_PUBLISHABLE_KEY` and `RAFII_CONTROL_PRODUCTION_PROJECT_REF`. Redeploy the reviewed, passing source; never promote the intentionally failed migration build.
5. **Enroll only James's independently verified identity.** The table is `rafii_control.platform_operators`, not `rafii_control.operators`. The runner now requires `FOUNDER_EXPECTED_USER_ID` through secure configuration. A recent `FOUNDER_REQUIRED` refusal must match that exact UUID. Never derive the expected UUID from the refusal query or assume Vercel team membership proves founder ownership. Ambiguous, mismatched, revoked or other-founder states fail closed. Enrollment does not create an authenticated session or bypass MFA.
6. **Complete James's own authenticator sign-in** at `/founder/sign-in`, then test authenticated desktop/mobile Live and Demo, logout and non-founder refusal. Do not ask him to retry before the mount and grant gates pass.
7. **Create the founder ops workspace** from Settings. It is classified internal and keeps Founder Rafii's runs, calls and costs out of customer numbers.
8. **Configure and verify observability:** the watchdog's read-only login as `RAFII_WATCHDOG_DSN`, and the dedicated CI-ingest DSN as `RAFII_ENGINEERING_INGEST_DSN`. Observe real successful workflow runs. Exact-SHA evidence must not label unmeasured, stale, failed or incomplete checks green.
9. **Optional live channels remain separate decisions:** `RAFII_FOUNDER_VOICE_ENABLED`, `RAFII_FOUNDER_EMAIL_ENABLED`, `RAFII_FOUNDER_PUSH_ENABLED`, `RAFII_FOUNDER_CALLS_ENABLED` plus live delivery in the contact policy. Do not send the stuck customer notification during validation or invent provider usage to clear an attention counter.
10. **Business decisions** remain explicit: refund policy, credits activation, plan catalog (D1), support ticket source (D7) and proposed SLO targets. Technical setup does not settle these decisions.

## Known limits until the recovery source and configuration are accepted

- Production still uses the large per-founder Demo JSON row. The pending recovery replaces it with a deterministic shared read-only base and per-founder changes, preserving existing Demo actions, isolation and replay behavior.
- Production Engineering still lacks hosted trusted CI manifests. The pending collector and migration 071 support them, but a passing local collector test does not mean the production secret/workflow is configured.
- Watchdog and CI-ingest workflows must be checked for real successful writes/reads after configuration; "not configured" is not healthy.
- The production permission repair, environment configuration and real MFA acceptance remain blocking. Preserve this distinction in every handoff.

## Verification

CI gates remain release contracts, disposable database migrations/restore, web contracts, types, lint, production build, copy audit, offline secret scan, consumer browser scenes, Control PostgreSQL and Founder browser acceptance. The recovery adds activation-runner paths to the Control workflow filter so later runner-only edits cannot skip its regression tests. Hosted acceptance still requires healthy customer traffic and cron plus authenticated Founder behavior on the deployed exact SHA.
