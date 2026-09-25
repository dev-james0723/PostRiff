# FINAL rollback — 2026-09-24

What changed where, and how to undo it.

| Layer | State | How to roll back |
|---|---|---|
| Candidate (`/Users/ouxianxing/Documents/James-Au-Studio-launch-20260923`) | integration workspace; every pre-edit file saved under `docs/launch-20260923/evidence/final/r1/pre-*`, `r3/pre-sync/` | restore any single file from those folders; the candidate is not shared with other sessions |
| Canonical working tree (`/Users/ouxianxing/Documents/James-Au-Studio`) | files copied in by FINAL-12 (list, pre- and post-image SHA-256 in `FINAL-MERGE-MANIFEST.json`); pre-images saved in the candidate at `evidence/final/promotion/canonical-pre-images/` | `python3 docs/launch-20260923/evidence/final/rollback_promotion.py plan` (read-only), then `… apply`, run from the candidate. Only files still holding exactly what the promotion wrote are restored; anything another session changed since is listed and left alone |
| Canonical `.claude/launch.json` | four local preview entries added: `launch-final-api`, `launch-final-api-legacy`, `launch-final-web`, `launch-final-web-prod` (tool config, not app code; the last one points at a scratch build copy) | delete those four entries |
| Canonical `docs/launch-20260923/` | FINAL deliverables copied in; DB-suite output in `evidence/final-canonical-db-suite/`; a dated section prepended to `STATUS.md` (history kept below it) | restore `STATUS.md` from the saved pre-image; delete the added files if unwanted |
| Git | nothing staged, committed, pushed or merged | nothing to undo |
| Databases | only disposable local PostgreSQL (55438 for the suites, 55761 / 55479 for the harness) was used; no migration touched a shared or production database | nothing to undo |
| Deployment, Stripe, social accounts, email | not touched | nothing to undo |

Before rolling back the canonical tree, check whether other sessions committed on top of the promoted files
(`git -C /Users/ouxianxing/Documents/James-Au-Studio log --oneline -- <path>`): the rollback script restores
working-tree files only and never rewrites history.
