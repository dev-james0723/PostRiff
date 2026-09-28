# Rafii Trend Growth Beta release gate — 2026-09-28

**Status: blocked before merge, deployment, migration, and Beta activation.** This receipt supersedes the local-test exception in `GROWTH_BETA_RELEASE_READINESS_2026-09-28.md`. It does not certify production data, provider rights, or creator outcomes.

## Exact release state

- Fresh `origin/consumer-saas`: `a6033925bd8c94b8f8b98efea48741fb57f110da`. Since the earlier readiness base `7b5ece8`, PR 68 added a read-only calendar answer card. Its changed paths do not overlap the Growth Beta candidate. The candidate cherry-picked cleanly onto this base in isolated branch `codex/trend-growth-beta-release-20260928`; the shared dirty checkout and all other worktrees were preserved.
- Current production alias `postriff-phase2-private.vercel.app`: Ready Vercel deployment `dpl_BzCBac3CQ4QRCR5CFct5TstUTQry`, reporting the exact same `a6033925bd8c94b8f8b98efea48741fb57f110da` Git commit. This is the **previous production commit**, not a Growth Beta deployment.
- No release PR merge, production deployment, production migration, production environment change, provider operation, paid/model call, test publication, or Beta cohort activation occurred in this continuation.

## Final local candidate validation

All tests below ran against the new release branch. Provider and identity fixtures were synthetic. The disposable PostgreSQL runs were local, not production audits.

- Growth Beta unit: 84 passed. Broad Trend unit: 1,029 run, 785 passed and 244 database-gated skips. The first broad attempt used a Python environment missing `jsonschema`; the complete rerun with the project environment passed.
- Disposable PostgreSQL: 20 Growth metric-read checks and 138 Trend service tests passed, including RLS/tenant denial, exact publication identity, stale lease fencing, revocation, unknown versus observed zero, and +24h comparison behavior.
- Node 24 frontend typecheck, scoped lint (0 warnings/errors), and clean Next production build passed. The build included the newer calendar merge and the release branch's Growth Beta source.
- Repaired the full historical `web/tests/trend-browser.cjs` fixture for the current Trend DNA layout without changing product behavior. Against the **final candidate production build**, all 70 assertion groups passed at 1440, 390, and 820 px, including 200% equivalent reflow. The scoped Radar Beta fixture passed 18 groups; the Learning browser fixture passed 49 checks. An initial concurrent browser run ran out of local screenshot space; both affected suites passed when rerun sequentially against the same build.
- The real API plus disposable PostgreSQL browser path passed at 1440, 768, 390, and 430 px with the **final candidate production build**. Its synthetic stored publications never claimed measured outcomes; current-rights revocation removed options/outcomes. The harness reported no provider/model configuration, browser egress, or production verification.
- `git diff --check` and `node --check web/tests/trend-browser.cjs` passed. Generated builds and a temporary production environment pull were removed after verification.

## Production preflight blockers

1. **Production database access:** the connected Supabase account lists only `bookmark-pilot`; requesting migrations for the app's production project `buoyhkbodnhzngaotoel` returned `You do not have permission to perform this action`. Vercel's production `POSTRIFF_DATABASE_URL` was redacted as `[SENSITIVE]` in the environment pull. Therefore migration 035/040 ordering/current checksums, live tables/functions/RLS, tenant isolation, metric-read permissions, and live rollback posture are **unverified**. The older closeout's 040 result is historical evidence only.
2. **Named cohort and signing key:** the production `RAFII_TREND_WORKSPACE_ALLOWLIST` variable exists, but its exact value and owner/membership/retention/rights were not verifiable through the available interface. `RAFII_TREND_CURSOR_SIGNING_KEY` is absent. No workspace is approved by this receipt.
3. **Feature and cost configuration:** `RAFII_TREND_INTELLIGENCE_ENABLED`, `RAFII_TREND_RADAR_ENABLED`, `RAFII_TREND_TRUST_RECEIPTS_ENABLED`, `RAFII_TREND_ALLOWED_OPERATIONS`, and `POSTRIFF_METRIC_READS` are absent from the production variable-name inventory. No provider:operation rights grant, native analytics entitlement, per-operation cost/rate ceiling, or authorized verified test publication was supplied. Do not turn on acquisition, model enrichment, notifications, publishing, or broader OAuth scopes to bypass this gate.

Follower conversion remains unavailable: the reviewed native-contract registry has no qualified matching `follows` / `profile_visits` pair. No follower-growth claim or fabricated popularity, velocity, reach, views, or virality metric is allowed. All unknown or unavailable values remain distinct from measured zero.

## Resume path and rollback

Grant the release operator read/migration access to Supabase project `buoyhkbodnhzngaotoel` (or provide `RAFII_TREND_MIGRATION_DSN` through the approved secret channel), name one approved internal workspace UUID with owner, membership, retention and source rights, and approve each requested provider/analytics operation with its actual cost ceiling. First run the read-only, SHA-pinned `scripts/trend_release_migrate.py plan --target production --plan <secure-plan-path>` against that project and audit live RLS, permissions and tables. Apply only a reviewed pending migration through that script, then recheck `origin/consumer-saas`, required PR checks and production config before merge/deployment. After exact-commit deployment, enable stored Radar for that one workspace first; enable metric reads only with confirmed native analytics rights and cost controls; perform authenticated production and denied-second-workspace smokes before claiming success.

Rollback is flag-first: disable provider operations, model enrichment, notifications, and `POSTRIFF_METRIC_READS`; if needed disable Radar, Intelligence, and Trust Receipts. Confirm workers stop new dispatch/reads while retained rows still honor revocation, deletion, and rights checks. Do not erase evidence or broaden access as a rollback shortcut.
