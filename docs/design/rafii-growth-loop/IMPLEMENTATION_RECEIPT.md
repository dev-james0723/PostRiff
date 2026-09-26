# Rafii Growth Loop P0 implementation receipt

Status: implementation and local validation complete; release evidence is recorded separately after deployment.
Execution: real local Python/Next.js/PostgreSQL and Chromium/WebKit. Provider measurements and identity in browser/database tests are synthetic local fixtures; no real social post, model generation, payment or production migration was performed.

## Scope and architecture

Implemented Growth Goal → goal-aware Weekly Operator → existing review/Queue publishing → covered metrics → user-approved experiment → explicit reversible planning preference → next week → weekly/monthly proof.

- New `coworker.growth_loop` is an adapter over the existing workspace aggregate, owner commands, row lock/revision checks, RLS, audit and product events. It reuses `performance`, `insights`, Weekly Operator, Queue, NotificationService and the Time Back ledger. New records are bounded and idempotent. No new SQL migration or separate JEV engine.
- Home shows the primary goal, baseline/current/target, honest coverage and next weekly action. Analytics holds goal management, Growth Lab and persisted proof history. Native metrics stay within one account/platform; missing coverage is null. A user-declared baseline is labelled, and measured increments since activation are added explicitly.
- Experiments require owner approval and a declared 14-day / minimum-five-per-arm design (the API supports 7–60 days and 5–100 samples). Only prospective verified posts with comparable account/language/content-type/definition and +24h readings count. Medians, evidence, counter-evidence, missing samples and causal=false remain inspectable. Results influence planning only after explicit adoption; revocation removes the preference. Voice/brand identity remains separate.
- Proof counts accepted/approved work and verified outcomes. Unused drafts, failed/unverified publishes and listening decisions without accepted artifact/campaign lineage do not count. Time Back retains confidence categories; read failure is unavailable. Monthly comparisons require at least three decisions and three approved edit distances in both completed months. No unconditional improvement claim.
- Existing notification preferences control delivery. Proof events reuse the current detector, digest templates, dedupe and failure isolation. Product-event properties contain record IDs only.
- Real browser testing exposed an existing Decimal timestamp serialization failure in Performance. API timestamps now serialize as nullable numbers. Mixed-platform hypotheses now retain each cohort's native metric.

## Validation

| Gate | Actual result |
|---|---|
| Python growth/JEV, coworker, learning, analytics, Time Back and billing regressions | 424 tests, 0 failures/errors; 4 pre-existing skipped tests |
| PostgreSQL Growth Loop | 9 scenario groups pass, including owner/tenant/RLS, duplicate writes, real metric observations, robust result/adopt/revoke, insufficient data, notification failure, provider/storage failure, unavailable Time Back and sufficient/insufficient monthly history |
| Existing PostgreSQL coworker | 35 scenarios pass; Weekly Operator, performance, notifications and runtime regressions |
| Existing PostgreSQL adaptive learning | 6 checks pass |
| Existing growth metric-read/history PostgreSQL scripts | Both pass; disposable database only |
| Web Node tests | 194 pass, 0 fail |
| TypeScript / lint / production build | Pass; lint 0 errors/warnings |
| Chromium / WebKit | 16 real UI/API checks each; desktop/mobile, goal calendar date, Lab approval/prepare/start/stop, no early result, recap idempotency, monthly honesty and no runtime errors |
| Accessibility | axe WCAG A/AA/2.1 AA checks on Growth Goal/Lab/proof: 0 violations in both browsers |
| Registry and whitespace | `python3 scripts/rafii_skill_registry.py --check`, `git diff --check`: pass |
| Migration audit | 107 local/origin refs and 41 worktrees inspected; existing numbering collisions documented; no new migration allocated |
| Deployment input audit | Vercel 60.1.3 dry-run includes the new API/UI and excludes private settings, credentials, local evidence, tests and tooling contents |

Commands and full local evidence are under `.token-pilot/evidence/` (local, intentionally excluded from Git/Vercel). Browser harness commands: `POSTRIFF_TEST_PYTHON=/Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python node tests/growth-loop-browser.cjs` and the same with `--webkit`, against dedicated loopback ports 14370/14371 and disposable PostgreSQL 55459.

Python command: scoped unittest discovery for `test_growth_*.py`, `test_rafii_*.py`, `test_postriff_learning*.py`, `test_postriff_phase2_learning.py`, `test_postriff_time_savings.py`, `test_postriff_analytics.py`, `test_postriff_billing.py`, `test_postriff_stripe.py` with `PYTHONPATH=src`. PostgreSQL command: `scripts/postriff_disposable_postgres.py` with the corresponding scripts under `tests/phase2/`. Web commands: `node --test tests/*.test.cjs tests/*.test.mjs`, `npm run typecheck`, `npm run lint`, `npm run build` using Node 24.

## Release boundary and limitations

The owner's current instruction explicitly authorizes push and deployment to the existing Rafii Vercel project, superseding the draft handoff's push/deploy prohibition. The original main and growth worktrees remain untouched; `origin/consumer-saas` is not merged or rewritten.

Direct production database inspection: `validation_unavailable` because Vercel intentionally withholds sensitive production environment values from downloads. No placeholder connection or production migration was attempted. Release verification must therefore separately confirm Vercel READY/aliases, backend health and guarded routes. The authenticated business flow is covered by the real local browser/database tests, not claimed as a production user session.

P1 remains outside this pass: Evergreen Compounder, Audience Relationship Memory, Competitor/Whitespace Radar expansion and packaging experiments. Follower/lead/conversion metrics stay unavailable until authoritative provider coverage exists; Phase 0 metric-read/history/Post Doctor feature flags remain at their existing production settings.
