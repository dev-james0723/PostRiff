# Connection-first recovery — active, awaiting real gates

**0/8 providers have verified ordinary-external-user connection acceptance on the observed deployment.** This is not a claim that every provider is technically incapable of connecting. No new provider E2E pass, release, review submission or X spending authority has been claimed.

## Current source and environment

- Isolated worktree: `/Users/ouxianxing/Documents/James-Au-Studio-social-connection-recovery`
- Candidate branch: `codex/social-connection-recovery-20261007`; final source/validation revision is recorded in `evidence/validation.json`.
- Initial source: `80bc24d20397a90257cb5571f8a3914a652bfb51`; historical implementation `6037ff7c594b3f580ed6d13ab6f20e9b0b1590c3` is an ancestor.
- Locally integrated current deployed source `91f6572c46fe9c357ca23ba43524f1ea3f27814e` in merge `e46917952b7ad1e8813966997eabb3dc495531d3`. This is a local Git merge, not a merged PR. It preserves intervening customer features/Next16.3.8 rather than deploying the older historical tree over them.
- Remote `https://github.com/dev-james0723/PostRiff.git`; push/PR/preview authorized; see evidence/release.json for observed result.
- Observed production: https://postriff-phase2-private.vercel.app ; project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; deployment `dpl_9Jiq5wtAzg7iwJHC7DqW5kbJw8en`.
- Production backend is the same Vercel project's `postriff_api` / `api.index:app`, reached by `/api` routing. `rafii-consumer-staging` was not changed.
- Working preview URL: **pending authorized creation**. A cloud test server that has ended is not a preview URL.
- Main checkout, unrelated dirty files and submodules remain outside this worktree's scoped edits. No reset, stash, force push or blanket commit.

## Executed engineering

1. Authenticated OAuth context recovery resolves the initiating workspace from server-owned state and the same user/active membership. The normal callback UI restores that workspace after sign-in rather than trusting the currently selected workspace.
2. Redirect transactions are claimed durably before exchange, preventing replay after failed/unknown exchange. Credentials, capabilities and workspace channel state now commit in one transaction, including repository effects. Failure cannot leave a credential-only connection.
3. Wrong/foreign reconnect identifiers are rejected. Facebook selection persists the Page destination and account type; personal identity alone is `DESTINATION_REQUIRED`.
4. Transient verification failures preserve an otherwise stored grant and return verification unavailable. Unknown refreshed scope evidence cannot erase scopes or become requested-scope proof. Existing rotation locks and compare-and-swap protections remain.
5. Public app eligibility uses an app/callback/minimum-scope/external-audience evidence record, independent of publishing approval and customer-specific E2E records. No approved records or `liveVerified=true` values were inserted. Facebook additionally requires a matching exact-scope Business Login configuration. Existing operation gates remain intact.
6. X onboarding supports an app-level, expiring, endpoint-allowlisted budget with workspace limits. Durable reservations survive transaction rollback and serialize the app cap. New migration100 is additive and not applied in production. No spending policy enabled and no metered calls made.
7. Resolved cloud validation's vulnerable transitive dependencies by reviewed remote lockfile repair (oxfmt/tinypool, sharp/libvips, source-map-js); no local installation. Corrected a deployed-source test's missing `node:test` import. All heavyweight checks run via internal JCB/Depot.

## Acceptance and action gates

Read [eight-provider map](CONNECTION-ACCEPTANCE.json), [single Action Required list](ACTION-REQUIRED.md), [review drafts](REVIEW-PACK.md), and [redacted operator observations](evidence/observations.json).

Google's actual runtime YouTube client and callback match the console, but project audience is External Testing. Meta inventory currently fails HTTP500; browser policy bypass was neither needed nor attempted. LinkedIn/Pinterest require operator login. Threads/Pinterest production client pairs are missing. The visible TikTok app is a Draft; runtime-key-to-console mapping is not yet verified. Visible X app OAuth2 is not configured; runtime mapping is still required before changing it. Environment key presence never proved token exchange validity.

Owners have not supplied the two ordinary Rafii test identities/workspaces or performed minimum read consent. Real iPhone Mirroring timed out, so Safari acceptance is `validation_unavailable`. No genuine provider review demo has been produced or submitted. Review text/shot list is prepared, not fabricated evidence. Time-dependent renewal remains pending.

Original `capability-matrix.csv` still has **205 rows**, original `live-e2e-matrix.json` still has **196 NOT_RUN cases** and **zero live passes**. Connection cases now preserve old blocker text under historical fields and separate identity/read consent from publication approval. LinkedIn member identity uses the actual OIDC source, without Community Management as a prerequisite.

## Resume without repeating the project

1. Read the latest validation receipt and poll only an actually active run; don't rerun passed unchanged suites.
2. Recheck current deployment SHA before a release. Use the verified source ancestry and inspect only subsequent changes.
3. Complete the specific operator/owner gates in ACTION-REQUIRED.md. Reuse existing apps and grants; store secrets only in approved secret stores. No blanket provider enabling.
4. Obtain exact preview/release approval; open the PR and use established checks/merge/deploy path. Apply migration100 only after checking the actual database and migration reservation. Preserve existing encrypted key/grants.
5. Run genuine ordinary-user connection acceptance through the deployed normal UI on desktop and real iPhone with two isolated users/workspaces; record actual grants, app/account/destination, workspace, revision, trace and timestamp. Update only proven provider acceptance. No post tests without a separate exact manifest/approval.
6. Release only a provider subset that passes the required gates; retain accurate pending states for the others. Rollback uses the verified prior deployment and retains token/cost records, not revocation/key rotation.

Token Pilot registry exhaustion must not block feature recovery. This file is the scoped continuation receipt; unrelated registry entries must not be removed. Token counters/cost savings are unknown unless actual host evidence supplies them.
