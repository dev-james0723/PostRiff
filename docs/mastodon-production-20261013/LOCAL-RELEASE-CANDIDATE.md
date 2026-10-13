# Rafii Mastodon integration — isolated local release candidate

Date: 2026-10-13. All actions are local-only unless explicitly identified otherwise.

## Provenance / scope

- Canonical Git repository: dev-james0723/PostRiff.
- Real live rafii.io deployment observed on Vercel:
  - Vercel project: postriff-phase2-private (prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L)
  - deployed source: a7b7e1c17e9f4973dd3048904c1ec032736c423f
  - deployment: dpl_5UV9JCm831i7bUdrQii6qniz9ZCS
- Feature source: Mastodon PR #176, 53c8ab899b66e14d7d568146b58e6f85c11c6251 (Draft as inspected).
- Two existing Telegram migration source files restored byte-for-byte from PR #180,
  116_telegram_identity_controls.sql and 117_telegram_capabilities.sql.
  Their SHA256 values exactly match the production custom ledger:
  - 116: 7605d51c0d15e8366d4f23519fd94c6feb91268214fbddd6750cc7041e542ade
  - 117: 08fd08c26583af2d8a848e463f1c29a7417bb0dcf114cf5c9b3b088b1aa6157a
- Twelve conflicts in cross-feature OAuth / worker / media / queue components were
  reconciled in this disposable isolated worktree. Existing LinkedIn server atomic
  credential/channel binding and Mastodon post-exchange revocation fencing are both
  retained and regression tested.

## Actual validation

- Local Python AST: passed on affected backend modules.
- Mastodon Python unit test discovery: 94 passed.
- LinkedIn Python unit test discovery: 39 passed.
- Shared hosted-wave1 connectors: 41 passed, after fixing a real Mastodon OAuth
  late-revocation/replacement race detected by two initially failing tests.
- SDK-enabled targeted Python suites: 173 tests passed across the Agent Runtime,
  founder/model metering, presenter, phone and YouTube Agent context components.
  Dependencies are installed in a temporary independent Python target directory;
  no paid model or provider calls were authorized or sent.
- Local disposable PostgreSQL 17 suites: five scripts passed, including a fresh
  89-migration hosted install, populated upgrade/ledger replay/restore,
  25 LinkedIn lifecycle tests, 27 Mastodon management tests, and synthetic
  two-instance worker/automation/pause/revocation tests.
- Full Web Node unit contracts: 939 passed, 0 failed.
- TypeScript typecheck: passed with pinned npm dependencies in this worktree.
- Web lint: 0 errors, 36 warnings.
- Next.js local production build: passed under Node.js 24.15.0.
- Current production custom migration ledger inspected READ ONLY: 62 applied,
  all 62 names and SHA256 checksums precisely match the local 89-source manifest.
  27 sources remain pending from that ledger; 113–115 are the scoped Mastodon
  migrations. Do not wholesale apply the other 24. A separate newer 118
  social-cost reservation migration is present in source and not ledger-applied.
- A full 5,158-test Mac-local Python run reported 14 failures and 21 errors:
  most failures arise from Linux-only seccomp/RLIMIT_AS library-renderer tests on
  macOS and missing SDK dependencies in the first run. Targeted SDK tests pass
  after isolated installation; the whole suite still requires clean Linux CI
  with its approved dependencies and complete PostgreSQL/browser gates.
  Do not promote this as a fully green protected CI receipt.

## Blocking release gates (NO-GO)

1. Supabase Preview Branch creation previously failed MIGRATIONS_FAILED, then
   the authorized failed branch was deleted. Empty preview replay starts at the
   official 088_founder_activation_integrity migration; that SQL checks the
   custom postriff_private.schema_migrations ledger, which did not yet exist.
   Its historical checksum preflight and prior business tables must be restored
   in the proper order in a data-free bootstrap. Do not improvise a fake ledger,
   rewrite already-applied source, or run 'migration repair' on production without
   explicit owner approval and an independent release safety review.
2. No clean hosted isolated restore/upgrade and no protected CI for this exact
   cross-release merge revision.
3. Real Mastodon A–E owner-authorized OAuth, signed-in connection, readbacks,
   temporary posting/edit/delete/scheduling, automation, pause/revocation and
   genuinely independent-server account acceptance NOT RUN.
4. Fresh production DB and Storage backup plus independent restoration receipts
   NOT VERIFIED.
5. No formal review of the reconciled PR diff, production scoped migration
   review/approval, protected release/rollback, merged commit or rafii.io live
   acceptance. Do not push/merge/promote/deploy without explicit authorization.

No production schema, production data, account credentials, secret values,
Mastodon statuses, external PRs or existing production deployments were modified.
All live database queries during this work were read only. Candidate intentionally
includes no copied customer data, token, OAuth state or existing secret.
