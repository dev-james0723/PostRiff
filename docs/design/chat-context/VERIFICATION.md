# Chat attachments — verification record

The integration gate is SPEC §14.4 (run by S35). This file holds the exact commands and the evidence collected so far. "Offline" rows use fakes or a disposable local database: they are not production, storage, browser or live-writer proof.

## SPEC §14.4 commands (worktree root)

```
PYTHONPATH=src:tests POSTRIFF_RESEARCH=0 python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src:tests POSTRIFF_PG_BIN=/opt/homebrew/opt/postgresql@17/bin python scripts/postriff_pg_suite.py \
  postgres_ideas postgres_ideas_references postgres_quick_start_again postgres_credits postgres_media_notes \
  postgres_media_notes_credits postgres_video postgres_consumer_deletion postgres_agent_runtime \
  postgres_agent_runtime_references postgres_site_agent_scenarios postgres_consumer_migrations postgres_final_run_refs
node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs
npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run format:check
node web/scripts/copy-audit.mjs --check
python scripts/postriff_dev_hosted.py --port 4438 --pg-port 55479 &   # private ports, stop afterwards
npm --prefix web run dev -- -p 4439 &
RAFII_WEB_URL=http://127.0.0.1:4439 node web/tests/rafii-seed.cjs
RAFII_WEB_URL=http://127.0.0.1:4439 RAFII_API_URL=http://127.0.0.1:4438 node web/tests/rafii-attachments.cjs
RAFII_WEB_URL=http://127.0.0.1:4439 node web/tests/rafii-workflow.cjs --only=mobile
```

Manual, production-adjacent (each needs James's permission, SPEC §14.1):

```
POSTRIFF_STORAGE_PROBE=1 POSTRIFF_SUPABASE_URL=… POSTRIFF_SUPABASE_SECRET_KEY=… python scripts/postriff_storage_probe.py --create-bucket --max-bytes <cap>
POSTRIFF_STORAGE_PROBE=1 POSTRIFF_SUPABASE_URL=… POSTRIFF_SUPABASE_SECRET_KEY=… python scripts/postriff_storage_probe.py --probe
```

## Copy gate

`node web/scripts/copy-audit.mjs --check` passed on the wave-1 branch (0 banned phrases), so the `ci-copy` step is added to `.github/workflows/consumer-ready.yml` now rather than deferred to S35. The Python `REASONS`/`REMINDERS` tables are covered by `tests/test_turn_references.py` (the copy audit doesn't scan Python).

## Evidence

| Date | Slice | Check | Where | Result |
|---|---|---|---|---|
| 2026-09-26 | S01–S03 | `python -m unittest test_turn_references test_fencing test_media_consent test_mp4_boxes test_asset_kinds` | cloud container, offline | PASS |
| 2026-09-26 | S04 | `python -m unittest test_hosted_storage_video test_postriff_phase2_hosted` (fake openers; no network) | cloud container, offline | PASS |
| 2026-09-26 | S05 | `tests/phase2/rls.sql` with 031, 031 re-run idempotent, `postgres_consumer_migrations.py`, `postgres_repository.py` | disposable PostgreSQL 16, cloud container | PASS |
| 2026-09-26 | S06–S09 | `node --test` ime, media-libs, video-file, credit-turn, chat-media-api, web-primitives, rafii-commands, library-upload-body-size; `npm --prefix web run typecheck`; oxlint on touched files | cloud container, offline | PASS |
| 2026-09-26 | S07 × S03 | JS `blankLocation` output parsed by Python `mp4_boxes.parse_moov`: location present before, absent after | cloud container, one-off | PASS |
| 2026-09-26 | S10 | `python -m unittest test_site_agent_search test_site_agent` + runtime adapter suites | cloud container, offline | PASS |
| 2026-09-26 | S11 | `node web/scripts/copy-audit.mjs --check` | cloud container | PASS |
| 2026-09-26 | wave 1 | Full `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs`: 292/293; the 1 failure (`receipt.test.mjs`) reads an evidence file omitted from the cloud snapshot | cloud container | PASS except snapshot omission |
| 2026-09-26 | wave 1 | Full `npm --prefix web run lint` (780 files) | cloud container | PASS (0 warnings) |
| 2026-09-26 | wave 1 | Full `python -m unittest discover -s tests -p 'test_*.py'`: 1278 tests; the remaining failures are the same at the packaging root 0644880 (Python 3.11 in the container vs the repo's 3.12 f-strings in `notifications/store.py`; no ffmpeg; omitted Xiaohongshu SDK; the pre-existing `notification-planning` registry orphan) | cloud container | PASS except baseline environment failures |
| 2026-09-26 | wave 1 | Full Python suite on Python 3.12 (the repo's `.python-version`; scratch venv from `requirements-dev.txt`): 1323 tests, only 2 errors, both `test_postriff_phase2` media tests that shell out to `ffmpeg` (installed by CI, absent here) | cloud container | PASS except ffmpeg |
| 2026-09-26 | S22 | Full PG suite (`tests/phase2/postgres_*.py`, fresh disposable PostgreSQL 16 per script): 58/59, the 1 is `postgres_migration_013` (its own `initdb` refuses root in the container); after S22 fixes `postgres_ideas_references` (30 checks), `postgres_final_run_refs`, `postgres_ideas`, `postgres_quick_start_again`, `postgres_credits`, `postgres_orchestration`, `postgres_final_credit_estimate` PASS; Python 3.12 unittest 1372, only the 2 ffmpeg errors | cloud container, isolated local PostgreSQL (not production) | PASS except harness/ffmpeg |
| 2026-09-26 | S25 | Full PG suite after S25 (fresh disposable PostgreSQL 16 per script): 59/60, the 1 is `postgres_migration_013` (harness: its own `initdb` refuses root); includes `postgres_ideas_references`, `postgres_quick_start_again`, `postgres_credits` S25 cases, `postgres_agent_runtime` after the `attachment_rows` refactor; Python 3.12 unittest 1374, only the 2 ffmpeg errors | cloud container, isolated local PostgreSQL (not production) | PASS except harness/ffmpeg |
| 2026-09-26 | S27 | Full PG suite after S27: 58/61, then `postgres_consumer_deletion` and `postgres_final_image_routing` PASS after the lazy video-storage fix; `postgres_migration_013` harness-only; `postgres_video` 24/24, `postgres_media_notes` 31/31, `postgres_media_notes_credits` PASS; route smoke tests in `test_postriff_consumer_web` | cloud container, isolated local PostgreSQL, fake storage (not production) | PASS except harness |
| 2026-09-26 | wave 6 | Full PG suite at wave-6 HEAD (S31, S32): 60/61, the 1 is `postgres_migration_013` (harness); then S33: `postgres_agent_runtime_references` (new) PASS, `postgres_agent_runtime` 56/56, `postgres_site_agent_scenarios` 100/100; Python unittest 1387, only the 2 ffmpeg errors | cloud container, isolated local PostgreSQL, scripted models (not production) | PASS except harness/ffmpeg |
| — | S04 | Storage probe (signed PUT, re-PUT refused, HEAD, Range 206 on object and signed URL, oversize refused, cleanup) | Supabase (non-production first) | validation_unavailable: needs credentials and James's permission |
| — | S05 | Migration 031 on production | production runner | validation_unavailable: needs James's permission |
| 2026-09-26 | S35 | `rafii-attachments.cjs` (desktop 1440×1000 and phone 390×844, Chromium): 22/22 — ＋ menu, Library "Add 1", PNG upload, reference role, `改@帖` with focus kept, Enter literal, ArrowDown+Enter 「label」, `name@mail` and pasted `threads.com/@x` closed, Escape, CDP IME (list follows; Enter/⌘+Enter while composing neither picks nor sends), Used this time (post, Photo A in the post, Photo B not used with the free-writer reason), only sent chips cleared, handcrafted MP4 begin → PUT → commit with "No preview in this browser", phone sheet, visualViewport, no overflow, 16 px | cloud container, isolated local harness (production `next build`, disposable PostgreSQL 16, in-memory bucket, fixture reader, flags on) | PASS (Chromium only; CI also runs it) |
| 2026-09-26 | S35 | Browser regression with the harness's chat-media flags on, one seeded DB in CI order: `rafii-workflow --only=workflow,library,drafts` 38/38, `rafii-attachments` 22/22, `ui-simplification-browser` 64/64, `site-agent-browser --browser=chromium` 39/39, `rafii-live-agent-browser` 13/13, `rafii-guide-browser` 16/16, `rafii-menu-close` 4/4; then on a fresh DB with the final scene file `rafii-attachments` 22/22 and `rafii-workflow --only=mobile` 5/5 | cloud container, isolated local harness | PASS |
| 2026-09-26 | S35 | §14.4 offline set at S35 HEAD: `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` 351/352 (the 1 is `receipt.test.mjs`, evidence file omitted from the cloud snapshot); `npm --prefix web run typecheck` PASS; oxlint on the attachments feature and the scene 0 errors; `copy-audit --check` 0 banned phrases; new files oxfmt-clean (whole-tree `format:check` fails at baseline, see notes). Python unittest and the named Postgres scripts: no server source changed after S34, so the wave-6/S34 results above stand (1387 tests, only the 2 ffmpeg errors; PG 60/61 + S33/S34 scripts PASS, the 1 harness-only) | cloud container, offline | PASS except baseline/snapshot/harness items |
| — | S35 | WebKit runs of the scenes | CI `rafii-browser.yml` | validation_unavailable here (Chromium only in the container); runs in CI |
| — | S35 | Manual device checklist (`docs/design/rafii-v9/evidence/attachments/README.md`) | real devices, flags on in a deployment | validation_unavailable: needs devices and James's permission |
| 2026-09-26 | live agent | Real Chromium against the dev harness (production `next build` + `postriff_dev_hosted.py` on disposable PostgreSQL 16, synthetic providers, seeded by `rafii-seed.cjs`; run as a non-root user in a copy of the tree): `rafii-live-agent-browser.cjs` 13/13 (voice flags off) and 14/14 (flags on), `rafii-guide-browser.cjs` 16/16, `rafii-menu-close.cjs` 4/4 | cloud container, isolated local harness | PASS (Chromium only; WebKit runs in CI) |
| 2026-09-26 | wave 2 | Browser regression after the wave-2 UI (same local harness, fresh DB, Chromium): `rafii-live-agent-browser` 13/13, `rafii-guide-browser` 16/16, `rafii-menu-close` 4/4, `rafii-workflow --only=workflow,library,drafts` 38/38, `ui-simplification-browser` 64/64, `site-agent-browser --browser=chromium` 39/39 | cloud container, isolated local harness | PASS |
| 2026-09-26 | wave 5 | Browser regression after the composer/Home/panel wiring, flags off (same local harness, fresh DB, production `next build`, Chromium): `rafii-live-agent-browser` 13/13, `rafii-guide-browser` 16/16, `rafii-menu-close` 4/4, `rafii-workflow --only=workflow,library,drafts` 38/38, `ui-simplification-browser` 64/64, `site-agent-browser --browser=chromium` 39/39 | cloud container, isolated local harness | PASS |
| — | live agent | Independent security/UX verdict on the live-agent slices | — | still open (carried from HANDOFF.md): the scenes above are functional checks, not a review |

## Port onto `consumer-saas` (release, 2026-09-26)

The S01–S35 work was built in a cloud packaging of `feat/chat-attachments` at `7eaf2cd`, which sat on commits that are not on any remote branch: the Rafii live-agent work (migration 030, `/` commands, guides, voice style) and open PRs #29 (`fit-for-upload.ts`) and #30 (composer text limit). The release branch carries only the chat-attachments diff (packaging root `0644880` → `d0dd640`, `transfer/` excluded, no deletions), applied 3-way onto `consumer-saas` at `387ac76` (after PR #31, the model picker).

- Conflicts resolved with PR #31: Auto writer resolution and reasoning levels in `ideas.turn`/`estimate_request`/`_project` keep their order and gain the chip fields; `useCreditEstimate(enabled, body, refreshKey, stateRevision)` keys on both; the composer keeps the `priced` check and adds the upload blocker; the hook's unused `model` option is removed so no view sends a resolved writer id.
- Left out (they need unmerged work): the live-agent pieces (`/` command block in APP_STATE, `ui.guide`/`ui.voice`, the guide overlay fix, `rafii-live-agent-browser.cjs`, the `menu-logic` IME re-export) and the panel's HEIC/`fitForUpload` wiring in `attach-image.tsx` and the Library queue (PR #29). `web/src/lib/image/fit-for-upload.ts` is included because the chip uploads use it; PR #29 will meet it as an existing file.
- `postriff-security-and-approval` is 1.2.0: both branches bumped it to 1.1.0 for different permission rows (`writer_defaults`, `media_egress`).
- `postgres_credits` S25 case: the run request now carries `deadline` (the run's own clock, never priced or digested); the estimate equality ignores it.
- Migration numbering: 030 reserved for the live-agent work, 031 is chat media (`docs/postriff-migration-numbering.md`).

| Date | Check | Where | Result |
|---|---|---|---|
| 2026-09-26 | Python unittest on the port: 1390 tests, only the 2 ffmpeg errors after the catalogue pin fix (33 tools without the live-agent ones) | cloud container | PASS except ffmpeg |
| 2026-09-26 | Full PG suite on the port (fresh disposable PostgreSQL 16 per script): 59/61, then `postgres_credits` PASS after the `deadline` fix; `postgres_migration_013` harness-only | cloud container, isolated local PostgreSQL | PASS except harness |
| 2026-09-26 | `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` 297/297 (the receipt evidence case passes in the real repo: its earlier failure was the packaging omission); typecheck; `npm --prefix web run lint` 0/0; copy audit 0; `rafii_skill_registry.py --check` | cloud container | PASS |

## Known environment notes (cloud container)

- `web/node_modules` was installed with `npm ci --ignore-scripts`; `psycopg` and `cffi` were installed from PyPI. Without `cffi`, `tests/test_rafii_review_fixes.py` panics at baseline too.
- The repo does not pass `oxfmt --check` at baseline (for example `web/src/features/rafii-commands/menu-logic.ts`), so `format:check` over the whole tree is not a usable gate until that is fixed separately. New files in this branch are formatted.


## Explicit skills + productivity connectors (2026-09-26)

Implementation continues the same chat-attachments composer. `skill` and `connector_item` are first-class turn references; social accounts/folders remain destinations. Productivity connectors are explicitly selected, read-only, server-refetched references. No background mailbox/workspace sync is introduced.

| Check | Where | Result |
|---|---|---|
| `PYTHONPATH=src:tests python3 -m unittest tests.test_productivity_connectors tests.test_turn_references tests.test_migration_numbers` | local worktree | PASS — 61/61 |
| Focused web attachment/connector tests including wire-body, picker, IME/state, credit binding and OAuth-return source checks | local worktree | PASS — 54/54 |
| `npm --prefix web run typecheck` | local worktree | PASS |
| `npm --prefix web run lint` | local worktree | PASS — 0 warnings / 0 errors |
| `npm --prefix web run build` | local worktree | PASS — production Next.js build, including `/connectors/connect` and `/app/connectors/connect` |
| Disposable PostgreSQL: `postgres_ideas_references.py`, `postgres_consumer_deletion.py`, `postgres_consumer_migrations.py` | fresh local PostgreSQL 17, deleted after run | PASS — reference/runtime fence, deletion cleanup, migration ledger/replay/RLS/backup+restore |
| Migration 032 | disposable PostgreSQL | PASS — fresh install + populated upgrade + replay |
| Production connector flags | source defaults | SAFE-OFF — `RAFII_NOTION_CONNECTOR_ENABLED` and `RAFII_GMAIL_CONNECTOR_ENABLED` are blank/off by default |

External enablement notes:
- Gmail uses the minimum body-reading scope required by this design, `https://www.googleapis.com/auth/gmail.readonly`. It remains a Google restricted scope; production enablement must not occur until the project has the required OAuth verification/security-assessment posture and valid production credentials.
- Notion is implemented behind its independent feature flag and requires a valid public OAuth integration/client configuration before enablement.
- Tests use fake provider transports/tokens; no real Gmail or Notion user data was read during verification.
