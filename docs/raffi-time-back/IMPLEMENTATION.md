# Time Back MVP — implementation notes (2026-09-25)

Source of truth: [ENGINEERING.md](ENGINEERING.md) (the supplied spec, saved unchanged). This note records what was built,
where the code required a decision the spec left open, how it was verified, and what is left for a release workflow.

- Worktree `/Users/ouxianxing/Documents/James-Au-Studio-time-back`, local branch `feat/time-back-mvp` (not pushed).
- Started from `origin/consumer-saas` = `b5de49f` (the planning SHA); fast-forwarded to `fc72e0c` (PR #6 and #7 merged
  meanwhile) with the work re-applied without conflicts, then re-verified.
- Migration: `migrations/postriff/023_time_savings.sql` (additive; not applied to any hosted database).

## What ships

| Work package | Where |
| --- | --- |
| WP1 data | Migration 023: `pr_time_savings_ledger`, `pr_time_savings_calibrations`, `pr_time_savings_preferences`, `pr_active_work_sessions`; `src/postriff_phase2/time_savings.py` |
| WP2 verified publish | `with_time_back()` fans out the worker's `on_verified` (comment ingestion first, unchanged; Time Back always after); wired in `hosted_app.py` and the dev harness |
| WP3 read API + Overview | `GET /api/workspaces/{id}/time-savings?range=7d|30d|year|all`; `useTimeSavings`; Overview stat "Time back · 30 days" replaces "Writing batches left" |
| WP4 active time | `web/src/lib/time-back/active-time.ts` (pure tracker), `use-active-work-timer.ts`; `POST …/time-savings/activity`; attached to Home composer and conversation (`conversation:<id>`), draft editor and schedule dialog (`variant:<id>`) |
| WP5 other outcomes | Repository effect `TimeSavingsService.capture`: drafts, adaptations, automation activation |
| WP6 calibration | `POST …/time-savings/calibrations`; prompt, dismissal, "Your typical times" overrides |
| WP7 detail | `web/src/features/time-back/time-back-section.tsx` at the top of Analytics, apart from "Post performance" |

## Decisions where the spec left room or the code differed

1. **Counted once, whatever the version.** The spec's `unique(workspace_id, dedupe_key)` is kept exactly (the key includes
   the calculator version). A second unique index on `(workspace_id, task_kind, outcome_kind, outcome_ref)` stops a v2
   calculator or a publish backfill from counting the same outcome again.
2. **Invariants in the database.** `saved = baseline − active` (never below zero; a baseline-only estimate saves the
   baseline), `confidence` follows from the row (measured / personalized / estimated), and an `UPDATE` trigger makes ledger
   rows immutable for every role. New baselines never rewrite earlier rows.
3. **Person foreign keys cascade.** Account deletion runs `DELETE FROM pr_profiles`; the spec's plain reference would have
   made deletion fail for anyone with Time Back rows in another workspace.
4. **Completion boundaries (WP5, verified in code).**
   - `draft`: a publish job is created for a generated variant (`p2_approve`, bulk approve, automation commit), or a
     person approves an automation post (`raffi_run_decide`). Counted once per variant; only variants whose first revision
     is Raffi's writing (`ideas-candidate`, `fixture`). Saving a candidate, generating, suggesting or reviewing counts nothing.
   - `adapt`: siblings share the root they were derived from, else the writing run. The first accepted version is the
     `draft`; each genuinely separate further version (another platform, language or account) is an `adapt`. A version
     for a slot already counted, or with text identical to a counted version, adds nothing (James, 2026-09-25: never
     double-count an identical outcome). Text is compared in memory from the workspace state; none is stored.
   - `recurring_setup`: a recurring task moving from draft (or created) to active. Resume, re-activation after an edit and
     one-time schedules do not count.
   - `campaign_plan`: **not recorded.** No campaign activation exists in the code; a campaign becomes active only as its
     recurring automation, which `recurring_setup` counts. The default stays in the registry for a future boundary.
5. **Beneficiary.** Publish: `job.approvedBy`, which the worker already requires to equal the manifest actor; under owner
   standing authority that is the grantor. Drafts: the approving person. The beneficiary must still be an active member,
   otherwise no row is written.
6. **Failure isolation.** Every write runs in its own savepoint and never raises. If the publish row cannot be written,
   `job.timeSavings = "pending"` is saved together with the verified state and the cron (`maintain()`) repairs it
   idempotently. Command effects log a class-name-only diagnostic.
7. **No lock on the workspace row.** Time Back endpoints read membership without `FOR UPDATE`, so heartbeats never make
   the publishing worker skip a workspace.
8. **Active time.** Nothing is sent until there is an active second (unmeasured stays unmeasured, never 0). Heartbeats are
   cumulative and idempotent; the server accepts at most 90 s for a new session, at most the wall-clock time since the
   previous beat plus 15 s, and 4 h per session. `consumed_seconds` credits measured time to one outcome only.
9. **Calibration.** Asked only for a kind completed in the last 7 days, with no override, fewer than three answers and
   no answer or dismissal in 30 days. Lower median of the latest seven answers. "More than 1 hour" asks how much more
   (1½–4 h) instead of guessing. Overrides and prompt pacing live in `pr_time_savings_preferences`. Shown in the
   Analytics section and, per James (2026-09-25), right after the person approves a post on any page
   (`post-approval-calibration.tsx` in the app shell): one optional question per approval, under the same server limits.
10. **Display.** Whole minutes; the server allocates breakdown minutes so they add up exactly to the displayed total.
11. **Copy.** The interface says "Rafii": the naming audit rejects "Raffi" in user-visible text.
12. **Scope.** API tokens have no Time Back scope (allowlist unchanged). The allowance stat moved off the Overview; the
    Billing meters already show it, and "Needs your attention" now reminds when two or fewer writing batches are left.
13. **Privacy.** A `time_back` retention class is added to the notice and the public legal table. Time Back is **not** in
    the workspace export, as James decided on 2026-09-25 ("not for now").

## Verification (merged tree `fc72e0c` + changes unless noted)

| Gate | Result |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_*.py'` | 943 OK (27 new in `tests/test_postriff_time_savings.py`) |
| `python scripts/postriff_pg_suite.py` | see the report; `tests/phase2/postgres_time_savings.py` covers 17 acceptance checks |
| `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` | 111/111 (11 new in `web/tests/time-back.test.mjs`) |
| `npm --prefix web run typecheck` / `lint` / `copy-audit --check` | exit 0 / 0 warnings 0 errors / 0 banned |
| Isolated production build | passed on `b5de49f` + changes; the rebuild on `fc72e0c` was refused by the machine's local resource guard (swap 95%, load ~30) and is left to CI |
| Browser (local harness) | `evidence/`: Overview and Analytics, desktop and 375 px: empty, populated, unavailable |

## Known limitations

- Draft time counts at approval; a later cancellation does not remove the row (rows are immutable by design).
- The Home composer is measured only once its conversation exists; typing the first request is not measured.
- Final seconds of activity can arrive after a very quick approval (heartbeats every 45 s); the row then under-measures.
- The dev harness's synthetic providers cannot publish, so the local browser evidence used the tests' technique (a
  trusted channel-verify command and the real worker with a synthetic adapter). Real provider verification is unchanged code.
- Existing verified posts are not backfilled (spec §14: from activation forward).
- The post-approval question is covered by unit tests and runs in every CI browser scene's app shell, but was not
  exercised live: the machine's resource guard (swap ~95%, 26 Next/Playwright processes) ruled out a local dev server.

## For an explicit release workflow

1. Review and commit `feat/time-back-mvp`; open a PR against `consumer-saas`; let CI run the full gates and build.
2. Apply migration 023 to production only with explicit approval (it is additive and idempotent).
3. Deploy; smoke: Overview shows "None yet" for a new account; approving a post and a verified publication each add one row.
