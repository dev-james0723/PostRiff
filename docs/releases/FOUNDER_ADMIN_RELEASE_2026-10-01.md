# Founder Admin Intelligence release — 2026-10-01

Status: code released dark. PR #86 (P0) and PR #88 (P1/P2) merge to `consumer-saas`, which deploys production. Founder mode stays off in production until the owner steps below are done. Post-merge production checks are recorded as comments on each PR.

## What ships

- **P0 (PR #86)**: Founder mode inside the Rafii app at `/founder`, Control v2 embedded at `/api/control/v2/*`, Live metrics with receipts, the 10k fictional Demo dataset, Founder Rafii (read, draft and preview tools only), the founder contact policy, incidents, briefings and the founder cron stage. Migrations 054–056.
- **P1/P2 (PR #88)**: revenue and MRR bridge, AI cost depth, product funnel, retention and risk, operations and support health, data health, founder voice, notifications and briefings, the founder ops workspace, and confirmed founder actions. Instrumentation migrations 057–060 and 062, Control views 063–068, 069 and 070.

Every metric that needs history says when collection started and how many days exist. Nothing unmeasured renders as 0.

## Production state after merge

- `/founder` redirects to `/founder/sign-in`. `/api/control/v2/*` answers 404 because `RAFII_CONTROL_MOUNT` is unset. Consumer routes are unchanged.
- The instrumentation writers run but skip quietly until their tables exist. No migration from 049 on is applied in any hosted database.
- Real calls, email and push stay off. Founder Rafii uses no paid inference in production until Control is mounted and the owner allows it.

## Owner activation, in order

1. **Decide the projection-ownership grant.** Migrations 049, 053, 054 and 055 hand view ownership to the projection roles. The migration runner role needs membership in those roles to do that. This release does not grant it. Either approve that grant for the runner, or apply the migrations as a role that already has it.
2. **Apply hosted migrations, staging first, then production.** Order: 049, 051–056, then 057–060 and 062, then 063–070. The public instrumentation files 057–060 and 062 do not reference the Control schema and can go first on their own, which starts data collection earlier. Every file is idempotent.
3. **Create the restricted logins** for the session and reader roles. Use the Supabase session pooler on port 5432 with `sslmode=verify-full`; Control bundles the Supabase root certificate.
4. **Set production environment variables on Vercel:** `RAFII_CONTROL_ENABLED=1`, `RAFII_CONTROL_MOUNT=embedded`, `RAFII_CONTROL_ENVIRONMENT=production`, `RAFII_CONTROL_ORIGINS` (the production origin), `RAFII_CONTROL_SESSION_DSN`, `RAFII_CONTROL_READER_DSN`, `RAFII_CONTROL_SUPABASE_URL`, `RAFII_CONTROL_SUPABASE_PUBLISHABLE_KEY` and `RAFII_CONTROL_PRODUCTION_PROJECT_REF`. Redeploy.
5. **Enroll the founder operator** with reviewed SQL: one row in `rafii_control.operators` for James's user id per environment.
6. **Sign in.** James enrolls an authenticator (Account, then Security) and signs in at `/founder/sign-in`.
7. **Create the founder ops workspace** from Settings. It is classified internal and keeps Founder Rafii's runs, calls and costs out of customer numbers.
8. **Optional channels**, each its own decision: `RAFII_FOUNDER_VOICE_ENABLED`, `RAFII_FOUNDER_EMAIL_ENABLED`, `RAFII_FOUNDER_PUSH_ENABLED`, `RAFII_FOUNDER_CALLS_ENABLED` plus live delivery in the contact policy, and the watchdog's read-only login as the repository secret `RAFII_WATCHDOG_DSN`.
9. **Business decisions** the pages already name as blockers: refund policy, credits activation, the plan catalog (D1), the support ticket source (D7) and the SLO targets, which are shown as proposed.

## Known limits

- The Demo dataset is one row of about 66 MB of JSON per founder. The first Demo open writes it and can take several seconds against a hosted database; Demo statements get up to 30 s within the request deadline. Storing only the founder's changes over the deterministic dataset would remove this cost.
- Engineering evidence reads "suspected" in production: the trusted required-check manifest is only recorded locally, so production never claims "checks passed".
- The watchdog workflow runs every 10 minutes and reports "not configured" until its read-only login exists.

## Verification

- CI on each PR: release gates (Python contracts, disposable database migrations with restore, web contracts, typecheck, lint, production build, copy audit, offline secret scan), Rafii browser scenes, the Control PostgreSQL suite with every founder migration applied twice, and the founder browser gate. The gate runs every section in Live and Demo at 1440, 768 and 390 px, every tab at 1440 and 390 px, axe, and the sign-in, Ask Rafii, voice, contact policy, follow-up and sign-out journeys.
- Production after each merge: the deployment is ready on the merge commit, health answers ok, `/founder` redirects to sign-in, `/api/control/v2/session` is not mounted, and runtime logs show no new errors.
