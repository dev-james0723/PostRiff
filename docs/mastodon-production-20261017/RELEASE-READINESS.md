# Rafii × Mastodon — isolated release candidate acceptance, 2026-10-17

## Decision

**PRODUCTION / PUBLIC: NO-GO.** **Isolated source merge + offline Mastodon security regression: CONDITIONAL PASS.** This document neither approves nor executes any external effect. No push, GitHub PR/merge, Vercel deploy, Supabase production migration, real OAuth, Mastodon write, paid runner, or customer release occurred in this workstream.

## Provenance

- Canonical GitHub repository: `dev-james0723/PostRiff`, default `consumer-saas`.
- Verified remote HEAD: `7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1` (read-only `git ls-remote`, checked again after integration).
- Mastodon PR #176 source SHA: `53c8ab899b66e14d7d568146b58e6f85c11c6251`, still **Draft / unmerged**. Existing CI-hardening reference: `92a8dcfad05c3b65ae7b73c241835830546d7000`.
- Isolated worktree: `/Users/ouxianxing/Documents/.agent-worktrees/rafii-mastodon-public-rc-20261017`; branch `local/rafii-mastodon-public-rc-20261017`; no other worktrees intentionally modified.
- Canonical Supabase Production project: `buoyhkbodnhzngaotoel`; read-only verified ledger: 62 applied name/SHA-256 rows, 62 matched source, 0 missing, 0 drift. No Mastodon-specific production tables.
- Origin 113 already used for X hosted migration. The old, never applied Mastodon 113–115 source SQL was renamed within this candidate to **131–133**, preserving original SQL content SHA-256. A scan of 598 local refs and 209 accessible worktrees found no existing 131–139 files; repeat remote/all-ref check before any release.
- Restored source-identical 116/117 Telegram migration files that existed in the production checksum ledger but were absent from the candidate's current base. 103 source was already byte-identical.

## Offline validation receipts

| Test / release gate | Status | Evidence |
| --- | --- | --- |
| Merge conflicts | PASS: four resolved, latest main capability gates retained | `git diff --cached --check` and Git merge commit |
| Mastodon unit regression | PASS: 136/136 | `evidence/mastodon-unit-round4.log` |
| PostgreSQL Mastodon management, RLS | PASS: 27 tests | `evidence/mastodon-postgresql-round2.log` |
| PostgreSQL current and legacy automation | PASS: 2/2 suites; four synthetic status writes across two servers, no duplicates | `evidence/mastodon-postgresql-automation-round4.log` |
| Creation, Agent permission and registry | PASS: 127 pass, 1 skip, 0 fail | `evidence/creation-security-focused.log` |
| Web calendar/receipt contracts | PASS: 11/11 | `evidence/frontend-contracts.log` |
| Frontend lint | PASS: 0 errors, 36 warnings | `evidence/frontend-lint.log` |
| Frontend typecheck | PASS: 0 TypeScript errors with complete existing local dependency snapshot | `evidence/frontend-typecheck-round2.log` |
| Production Next.js build | **BLOCKED:** direct Next executable in read-only dependency snapshot lacked execute bit; Turbopack rejected cross-worktree symlink; Webpack hit 1.5 GiB Node heap limit during compilation | `evidence/frontend-build.log`, `frontend-build-round2.log`, `frontend-build-webpack.log` |
| Full Agent Runtime suite | **PARTIAL:** two unrelated baseline/environment errors (missing local OpenAI SDK; `ScriptedModel` unavailable without SDK), not counted as PASS | `evidence/creation-agent-security-regression.log` |
| Linux Chromium/WebKit end-to-end | **NOT RUN:** browser harness asserts Linux CI and requires isolated Next + PostgreSQL server | Source: `web/tests/mastodon-account-browser.cjs`, `mastodon-queue-browser.cjs` |
| 1,000-user concurrent capacity test | **NOT RUN:** explicitly Linux CI-only; no paid runner permitted | `evidence/mastodon-postgresql.log` |
| Real Mastodon OAuth, connection/disconnect, actual publish/edit/delete/schedules | **NOT RUN / NOT AUTHORIZED** | Provider consent and approved exact action receipts required |
| Production backup + independently tested restore | **UNVERIFIED** | Independent restoration proof required |

## Security, rollback and Beta non-negotiables

1. No new feature or authorization flags will be flipped as part of test fixture repairs. `Mastodon` remains absent from the default original drafting five. Only the per-test synthetic environment opts in to drafting.
2. `mastodon.status` is now a valid **default** native post format; `mastodon.poll` continues to be export-only in the generic publishing gate. A valid default format **does not** bypass provider review, account verification, billing, manual approval or other authorization checks.
3. Separate staging App/DB/Auth/Storage, distinct encryption keys and callback allowlist, zero customer data, no unrelated provider/phone/email egress, verified secret isolation and enforced expense ceiling **must** be approved before any hosted preview.
4. Obtain fresh, explicit human authorization for **two accounts on two different independently hosted Mastodon servers**. Run OAuth one account at a time with exact permission/scope preview. Do not expose tokens/refresh credentials or user data in evidence.
5. For every live test post, edit, delete, media, scheduled post or cancel: require separate preview of exact account, server, content, visibility, operation and digest; obtain explicit owner approval; persist externally verifiable provider IDs and URLs; reconcile an unknown outcome rather than retry blindly.
6. Verify per-workspace isolation, operator permission, token storage and revocation; cross-server account identity and readback; restart/idempotency; native scheduled post cancellation; live rate limits, costs, backups and operational alerts.
7. Rehearse a forward-only migration and production-compatible rollback on a separately approved isolated server. Do not down-migrate or overwrite production customer data. Verify an immutable previous deploy is available; `POSTRIFF_OAUTH_MASTODON_DISABLED=true` only blocks future Rafii dispatch, **not already-scheduled native Mastodon posts**, which require exact-ID cancellation/reconciliation.
8. Restore exact CI green status for the eventual final merge commit and complete Production Next Build, protected Chromium/WebKit and capacity test **before** recommending invited Beta. A successful isolated unit test is not a production pass.
9. Beta rollout proposal (not approved): owner accounts only, then at most five invited customers with separate explicit approval and monitor/rollback criteria; expand to public only after measurable live acceptance. Never switch on public simply because a UI button exists.

## Mandatory separate owner approvals

**Approval A:** a genuinely isolated, cost-bounded hosted Preview (only after verified plan, hard cap and rollback); **Approval B:** exact per-account OAuth grants; **Approval C:** exact individually labelled test posts, edits, deletes, scheduling and cancellation; **Approval D:** protected GitHub PR/merge and Production schema, feature flag, Vercel deploy, invited Beta and ultimately public rollout. This mission approves none of A–D.

## Provenance / current status

This is an isolated RC and NOT a release. The final local commit SHA, checked manifest SHA-256 and ready-to-resume instructions are retained in the sibling Documents report directory. Inspect git and evidence before continuing; re-check live remote HEAD and migration allocations. NEVER apply historical 113 Mastodon SQL to Production.
