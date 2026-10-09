# Release receipt — Growth Studio + Trends (in progress)

Each entry has environment, timestamp and proof. Status words: VERIFIED,
UNVERIFIED, BLOCKED. This file is updated as the release advances.

## Authorization

- 2026-10-09 (James, in session): approved production steps 1–3 (migrations
  037/038/103, merging validated PRs into consumer-saas with automatic deploy,
  enabling the Growth/Postmortem/Audience Miner/Genome and self-serve flags),
  Growth caps US$10/day global and US$4/day per workspace, self-serve cohorts
  of 10 for Trends and 10 for Growth measurement, a QA account
  `hinsingau.pianist+rafii-qa1@gmail.com`. Bluesky cross-workspace sharing is
  conditional on a documented rights review; a new public Instagram post needs
  separate approval.

## Database (production `buoyhkbodnhzngaotoel`)

### 037_growth_phase1 + 038_growth_closed_loop — VERIFIED applied

- Backups: the Supabase organization is on the free plan (no platform
  backups); the CLI account cannot list backups (HTTP 403). These migrations are
  additive only (11 new empty tables), so the restore reference is the pre-apply
  state below plus `migration-rollback.sql` (refuses if any new table has rows).
- Pre-apply (2026-10-09T01:03:36Z, read-only): ledger 57 rows (035, 036 present;
  no 037/038); 168 public tables; none of the 11 target tables present;
  workspaces 5, memberships 5. Dependencies `pr_workspaces`,
  `pr_audience_threads` present. App role `postgres` has BYPASSRLS (same as the
  existing force-RLS credit tables without policies).
- Applied: Supabase `apply_migration` name `growth_phase1_closed_loop_037_038`,
  2026-10-09T01:04:49.751Z, SQL `migration-037-038-guarded.sql` (guard refuses
  if a ledger row or any target table exists; lock_timeout 5s).
- Post-apply (2026-10-09T01:05:08Z, read-only): all 11 tables exist, 0 rows,
  `relrowsecurity` and `relforcerowsecurity` true; no grants to
  anon/authenticated/PUBLIC; ledger rows `037_growth_phase1.sql` sha
  7e9be37ec035… and `038_growth_closed_loop.sql` sha ac6e52d5a326…; ledger 59
  rows; workspaces 5, memberships 5 (unchanged).
- Security advisors (01:05:18Z): only INFO `rls_enabled_no_policy` for the new
  tables (deny-all for browser roles, same as existing credit tables); the two
  WARN items (pg_trgm in public, leaked-password protection) predate this
  release.
- Running code at a522482e touches these tables only behind `to_regclass`
  guards (`growth/service.py` invalidate/sweep), on empty tables.

### 103_feature_enrollments — VERIFIED applied

- Gate: C0 CI run 37866547621 (head 5038b16a) PASS — ci-python 4020 tests OK
  (371 pre-existing skips), ci-postgres all suites exit 0 including
  `postgres_feature_enrollments` (forced RLS, owner-only, idempotency, cohort
  cap under a concurrent race, kill switch, denylist, read admission vs egress,
  authenticated role denied), ci-web incl. `feature-readiness.test.cjs`,
  typecheck/lint/build, browser.
- Applied: `apply_migration` name `feature_enrollments_103`,
  2026-10-09T01:16:09.533Z, SQL `migration-103-guarded.sql`.
- Post-apply (01:16:21Z, read-only): table exists, 0 rows, RLS+force true, only
  policy `pr_feature_enrollments_runtime` (service_role), 0 grants to
  anon/authenticated/PUBLIC, ledger row sha b3b8b681bf78…, ledger 60 rows,
  workspaces 5 (unchanged).
- Running code at a522482e does not read this table; C0 code treats a missing
  table as "not enrolled".
