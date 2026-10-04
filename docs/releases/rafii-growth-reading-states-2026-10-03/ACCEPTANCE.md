# Growth Studio reading-state repair

This bounded Stage 3 change distinguishes unavailable native readings from scheduled work and fixes the empty-workspace crash. It does not close Stage 3 provider or production acceptance.

## Behavior

- Every visible publication window receives its native schedule state, due time and failure reason from the existing read-only tracker, covering the same maximum 300 posts as Results.
- Disabled collection, missing schedules (including future horizons), unsupported providers, disconnected accounts, missing analytics permission and exhausted retries do not tell the creator to wait for a result.
- A usable retained native observation is inspectable even when new collection is disabled. Observed zero remains distinct from missing data.
- An empty workspace without a Direct owned Threads/Instagram analytics connection renders an explicit unavailable state and opens the existing Accounts connection flow. A missing post/report cannot crash Results.
- Measurement status inspection performs no provider or model dispatch. Consent, paid-route grants, publication verification, comparability, calibration and owner approval gates remain enforced.

## Local validation

These are local implementation checks with synthetic external services, not authorized production provider success.

- 51 focused Python tests passed for Beta, closed loop, native metric scheduling, Phase 1 and Post Doctor. The 15 Beta tests were rerun after distinguishing a future missing schedule from queued work.
- Disposable PostgreSQL suites for Phase 1, Phase 2 and metric reads passed. Final Phase 2 SQL checks use a separate local port and the runner's `POSTRIFF_TEST_DSN` contract: measured/disabled/scheduled/future/exhausted/missing schedule/revoked rights, including a missing future schedule. Other worktrees' clusters are untouched.
- Three Node reading-state tests, TypeScript, lint, product copy audit and the final production build passed. Lint retains two existing unrelated warnings.
- Actual local browser → API → disposable PostgreSQL checks passed at 1440, 390 and 320 pixels, dark mode, reduced motion and keyboard tabs, with no serious/critical axe violations. External browser requests are blocked. Checks cover result review, explicit Genome approval, Audience-to-Ideas persistence, disabled collection, the empty-workspace state and navigation to Accounts.

Local raw logs and screenshots are retained under `.codex/product-finish-stage3/`; repository CI must pass on the committed head before merge.

## Production gate at preparation

The production alias was READY at SHA `7156703b3725156c6041b059040007ab2ea63fab`. Authorized read-only production database checks found no Threads/Instagram channel, verified publication, metric observation or History Import run in the admitted workspace. Existing Bluesky acquisition had stored real batches, which do not prove downstream projections or Growth outcomes.

Authenticated browser acceptance is waiting for the account owner's MFA. Owned account selection and a publication authorized for measurement are still required. No provider permission, feature flag, production schema/data, model dispatch or publication was changed by this repair. Real Stage 3 acceptance is BLOCKED; sequential Stages 4 and 5 remain open. A deployed build and a truthful unavailable state are separate from real native analytics acceptance.
