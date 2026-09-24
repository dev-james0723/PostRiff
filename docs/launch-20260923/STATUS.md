# 2026-09-24 FINAL integration: LOCAL_VERIFIED and integrated into this working tree — not committed, not deployed

Supersedes, for the current code: the 2026-09-23 section below where it says TypeScript errors remain, the latest
build / full PostgreSQL suite / browser were NOT_RUN, and V9 Home controls, cloud-first UI, saved folders and copy
were not promoted. History below is kept unchanged.

- Integration writer worked in `/Users/ouxianxing/Documents/James-Au-Studio-launch-20260923` (FINAL-00…12). 128 files
  were copied into this working tree on 2026-09-24 08:54:30Z with pre-image checks (`FINAL-MERGE-MANIFEST.json`);
  canonical's newer v9 / Automations work was merged in first, not overwritten.
- Same content as release snapshot r6 (`d9573b5e…`): Python 689 OK, tsc 0, lint 0/0, Node 135/135, PostgreSQL 47/47,
  production build exit 0, two browser journeys exit 0, 352-capture route matrix with only named errors. Re-run here
  after promotion: identical results (`evidence/final-canonical-db-suite/` for the DB suite).
- Still NOT_RUN: live models, Stripe Sandbox, real payments, real publishing, production migrations and deployment.
  Nothing was committed or pushed. Decisions and exact asks: `FINAL-AUTHORIZATION.md`.
- Read next: `FINAL-DELIVERY.md` (status by layer, tests, gaps), `FINAL-LEDGER.md` (every step), `FINAL-ROLLBACK.md`.

# 2026-09-23 launch execution: PARTIAL / RELEASE BLOCKED

Original repo: `/Users/ouxianxing/Documents/James-Au-Studio`, branch `consumer-saas`.
Base HEAD: `468811b73d28b4389f931519827c05d0e6c8abfb`.
Isolated current-source candidate: `/Users/ouxianxing/Documents/James-Au-Studio-launch-20260923`.
Candidate branch: `codex/launch-audit-20260923`.

## Promoted with pre-image hash checks
- `src/postriff_phase2/model_runtime.py`: account IDs survive cloud requests and response matching; ambiguous, duplicate and foreign accounts fail closed.
- `web/src/features/agent/plan.ts`: reviews bind the correct generation and account, never an unrelated fallback draft.
- `src/postriff_phase2/credit_meter.py`: versioned NON-BILLABLE credit calculator only, not an activated wallet or replacement billing ledger.
- Regression files: `tests/test_launch_cloud_accounts.py`, `tests/test_credit_meter_preview.py`, `tests/test_launch_provider_routes.py`, `web/tests/launch-plan-accounts.test.cjs`.

## Fresh validation after promotion
- Canonical Python: 607 tests PASS, exit 0, with `PYTHONPATH=src:tests`.
- Canonical Node contracts/locales: 42 tests PASS, no failures/skips.
- Canonical TypeScript: 4 existing errors remain. NOT release-ready.
- Candidate TypeScript: 1 new callback nullability error. Candidate lint: 3 errors/5 warnings.
- Latest build, full PostgreSQL suite, browser/phone, paid models, voice-quality evaluation, OAuth, social publishing and payments: NOT_RUN.

## Not promoted
V9 Home controls/results, cloud-first/no-silent-fallback UI and baseline UI fixes remain unaccepted in the candidate. A later UI batch was blocked by tool safety checks and was not retried through another route. Saved folders on Channels, remaining copy, nullability/Strict Mode/duplicate-submit fixes and browser acceptance remain unfinished. Do not deploy this candidate or claim the six-feature report complete.

## Evidence and boundaries
Candidate `docs/launch-20260923/evidence/` contains logs, `promotion.json`, and `pre-promotion/` originals. `source-before.json` records the original snapshot; filtering credentials is not a completed artifact secret audit.
No commit, push, deployment, production migration, real model call, social action or customer charge was performed. Existing subscriptions and balances are unchanged. New pricing remains proposed; see `CREDITS-CANDIDATE.md`.
