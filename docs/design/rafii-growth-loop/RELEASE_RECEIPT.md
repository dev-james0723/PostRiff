# Rafii Growth Loop release receipt

Released 2026-09-26 to the existing `postriff-phase2-private` Vercel project.

- Code commit: `9a75be2021c4a3aedc397fad9f5d6ea9f88eadc3`.
- Pushed branch: `codex/rafii-growth-loop` at `dev-james0723/PostRiff`. No remote merge, force-push or rewrite of `consumer-saas`.
- Production deployment: `dpl_327kLCWpdBeN1pcVU6qbpGMmNjeD`, READY, promoted to the project's production target; Vercel metadata matches the code commit and branch.
- Live app: https://postriff-phase2-private.vercel.app/app/analytics
- Deployment URL: https://postriff-phase2-private-csu3i2ji1-jamesau0723-6572s-projects.vercel.app
- Inspect: https://vercel.com/jamesau0723-6572s-projects/postriff-phase2-private/327kLCWpdBeN1pcVU6qbpGMmNjeD
- Previous production: `dpl_5eTPjMRexcN3yHJ6ZmaYDJE8Nibo` (retained; no deletion).

## Release verification

The local validation gates in IMPLEMENTATION_RECEIPT.md all passed. Vercel built both the Next.js and Python services successfully, then reported READY. A production deployment was created with `vercel@60.1.3 deploy --prod --skip-domain --yes`; after checks, `vercel@60.1.3 promote` completed successfully.

Live checks: `/api/health` returns HTTP 200, status ok, configured true on both the deployment URL and public production alias. `/app/analytics` returns HTTP 307 to sign-in when logged out. The new Growth Loop route returns HTTP 401 / Verified session required when unauthenticated. The promoted production target and Git metadata were re-read from Vercel; they match the released code.

These are deployment/routing/authentication checks. The health response is a configuration check, not a production database schema or provider integration test. Direct production schema inspection remains `validation_unavailable`: Vercel withholds sensitive environment values from downloads. Authenticated Growth Goal/Lab/proof behavior was tested through real local browsers and disposable PostgreSQL with synthetic identities/provider measurements.

Existing production feature flags were preserved. Phase 0 +24h metric collection/history/Post Doctor are not activated by this release; an experiment without enough prospective +24h observations correctly remains insufficient_data. Follower/lead/conversion coverage remains unavailable until an authoritative source is connected. No production migration, billing activation or real social publish was performed. P1 stays outside this P0 pass.

The documentation-only release receipt commit follows the deployed code commit. Documentation is excluded from Vercel deployment input, so it does not change the deployed application.
