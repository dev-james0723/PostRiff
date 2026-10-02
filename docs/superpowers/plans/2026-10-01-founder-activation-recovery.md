# Founder Activation Recovery Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; preserve the existing isolated worktree and the source-specific verification receipt. Do not restart or duplicate this activation.

**Goal:** Recover the interrupted Founder Admin activation without weakening authorization, losing local agent work, or representing unverified production as complete.

**Architecture:** Retain the pinned, transaction-scoped activation runner. Repair code in the existing `claude/founder-activation` worktree. Hosted writes remain explicit reviewed actions, and a tool denial is a stop for that hosted operation, not permission to change routes or disable safeguards.

**Tech Stack:** Python 3.12, PostgreSQL 17, Supabase, Next.js 16.3.8, Node 24, Vercel, GitHub Actions.

**Spec:** `docs/design/founder-admin/CONTRACTS.md`, `docs/releases/FOUNDER_ADMIN_RELEASE_2026-10-01.md`, and James's October 1 request to complete the interrupted activation.

## Global Constraints

- Worktree: `/Users/ouxianxing/Documents/James-Au-Studio-founder-admin`; never reset the canonical checkout or absorb Product Growth's concurrent work.
- Vercel project: `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; team: `team_PgXY5VdAYKcsv0RLoDPHscNq`.
- Supabase production: `buoyhkbodnhzngaotoel`; staging: `oxacvkhpfgytkepxcaqh`.
- Hosted runner uses the target's own database configuration, validates project and migration SHA-256 pins, and terminates its build deliberately so it cannot serve traffic.
- No secret values in source, tool output, logs or receipts. No bypass of MFA, RLS, TLS, approval controls, or deployment gates.
- Unknown provider usage stays unknown. No customer email, charge, refund, provider call or invented usage reconciliation is part of code validation.
- Never equate a CI check, commit, push or deployment with signed-in production acceptance.

## Review Focus

1. A recent refused account is not proof of founder ownership: require a separately verified exact UUID.
2. A revoked founder must not be silently reactivated by initial enrollment.
3. A legitimate NOINHERIT login cannot resolve a private schema until assuming its permitted role; do not grant broader login privileges as a workaround.
4. Old or mismatched CI evidence must not make the current release green; retain exact-SHA provenance tests.
5. Shared Demo base data must be immutable and isolated by founder/environment; preserve the PostgreSQL mutation, replay and legacy-upgrade tests.

## Task 1: Establish the actual checkpoint

- [x] Verify branch, uncommitted work and production deployment SHA.
- [x] Read staging repair and production apply/login logs from the actual Vercel deployments.
- [x] Run a new production read-only preflight; retain the unchanged production alias.
- [x] Record that the hosted repair execution was blocked by the tool safety layer; stop this operation without an alternate route.

## Task 2: Preserve and harden the activation runner

**Files:** `docs/releases/founder-admin-2026-10-01/activate_founder.py`, `tests/control/test_activation_runner.py`.

- [x] Commit the previously untracked pinned runner before further changes.
- [x] Add real disposable-PostgreSQL tests for absent/invalid UUID pins, mismatched and ambiguous refused identities, idempotent matching enrollment, existing other founder, and revoked founder.
- [x] Observe the unsafe enrollment cases fail before editing production logic.
- [x] Require `FOUNDER_EXPECTED_USER_ID`, serialize enrollment by environment, reject mismatched/revoked accounts, and preserve MFA/session creation boundaries.
- [x] Pass the full Control PostgreSQL suite, including these regression tests: 550 tests, zero failures/errors/skips.

## Task 3: Validate the pending Demo and CI evidence work

**Files:** `demo_dataset.py`, `workspace.py`, `ci_evidence.py`, `intelligence.py`, their Control tests, migration 071, Founder engineering UI/tests and workflow.

- [x] Run the existing full Control suite before modification: 541 tests, one genuine CI-ingest schema-resolution error.
- [x] Fix the query order without broadening database access; keep the original login privilege test before any data write.
- [x] Update the query-order unit regression to assert the security ordering instead of a brittle absolute index.
- [x] Re-run Control PostgreSQL (550 passed), web contracts (618 passed), typecheck (passed), lint (zero errors; one pre-existing warning) and offline source secrets (2,455 files, no unexpected findings). Full Python 3.12/declared-dependency suite: 3,662 tests, 338 environment skips, zero failures/errors; source fingerprint unchanged. The shared old Python 3.14 venv was not a valid release environment and its failing diagnostic run is retained in the local receipt.
- [ ] Commit all reviewed pending work explicitly; exclude generated test evidence churn and credentials.
- [ ] Push a scoped PR against `consumer-saas`; do not merge while gates or hosted qualification remain incomplete.

## Task 4: Hosted activation gates (not fulfilled by code-only checks)

- [ ] Production grant repair and exact-role reads, with temporary privileges removed.
- [ ] Apply migration 071 through an approved, pinned staged runner; create and qualify a dedicated CI-ingest login separately from session/reader/watchdog.
- [ ] Configure the validated restricted DSNs and required `RAFII_CONTROL_*` production settings. Keep Control off until prerequisites pass.
- [ ] Install watchdog and CI-ingest secrets through secure configuration, then verify actual workflow execution.
- [ ] Verify James's exact Supabase identity independently, enroll only that identity, and complete his own MFA sign-in.
- [ ] Test authenticated desktop/mobile Live and Demo, identity refusal, logout, healthy customer traffic and cron.

Receipt location on James's Mac: `/Users/ouxianxing/Downloads/RAFII-Founder-Repair-20261001/`. Any remaining blocked gate must be stated explicitly in the final receipt.
