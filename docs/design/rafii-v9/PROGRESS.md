# Rafii v9 production integration — progress ledger

Started 2026-09-23 (session 69e3ce2f). Branch `consumer-saas`, HEAD `468811b` at start. Working tree had 115 modified + 78 untracked files from earlier sessions (preserved untouched; snapshot tagged `rafii-v9/baseline-worktree` = stash object `800de3b`, HEAD tagged `rafii-v9/baseline-head`).

References (retained, hashes verified against INPUT-MANIFEST.json): `docs/design/reference/rafii-v9/`.

## Baseline (before any edit)

| Check | Command | Result |
|---|---|---|
| Types | `npm --prefix web run typecheck` | exit 0 |
| Lint | `npm --prefix web run lint` | exit 0 (1 pre-existing warning: `no-inner-declarations`-style hint in `security-card.tsx`) |
| Python unit | `python -m unittest discover -s tests -p 'test_*.py'` | see `evidence/baseline-python.log` (run in phase 1) |
| Node contracts | `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` | see `evidence/baseline-node.log` |

## Resolved reference conflicts

- `docs/rafii-migration/design.md` (2026-09-19, never implemented) proposed a navy/violet palette. The v9 handoff explicitly supersedes colored directions: Rafii chrome is monochrome. Its route disposition table (44 entries) is reused as the inventory seed.
- The prototype keys folders by a demo `account-<platform>` id and bridges back to a platform list. Production keeps real `ChannelView.id` (connection id) end to end: composer selection → destinations → run variants → apply → review manifest.
- The prototype's `Warm/Bold` voices are demo tones. Production Writing Voice = `neutral` | `personalized` (approved samples) exactly as today; no fake tones are added.
- The prototype's Inbox/Calendar/Queue demo views are ignored; the real routes keep their behaviour and get the DNA applied per recipe.

## Execution plan (phases)

1. Discover & baseline — done (this file, `route-ledger.md`, `wiring-matrix.md`).
2. Foundation & shell — `web/src/styles/rafii.css` (tokens/materials), `components/rafii/*`, `lib/rafii/motion.ts`, AppShell/sidebar/header/mobile bar/page container.
3. Homepage vertical slice — v9 composer, real generation (`quickStart`/run polling), per-account drafts, apply/edit persistence.
4. Folders & previews — backend `p2_folder_*` actions + tests, Channel Bloom dialog, account-keyed destinations, preview deck (slide/crossfade/swipe).
5. App-wide migration — every route family (see ledger).
6. Hardening & handoff — type/lint/build/unit/browser checks, evidence at 8 viewports × 2 themes, motion recordings, rollback notes.

## Decisions log

- D1 Theme: a new `rafii` theme (`web/src/styles/rafii.css`) becomes `DEFAULT_THEME`; it maps the semantic `--rafii-*` tokens onto the existing shadcn tokens so every component inherits the monochrome material. Existing named themes remain selectable (existing preference mechanism, cookie `active_theme`); light/dark stays on next-themes. No second theme store.
- D2 Fonts: Geist (already loaded through next/font) is the interface face; editorial accent uses the system serif stack (Georgia). No new font dependency.
- D3 Folders persist in workspace state (`state.phase2.channelFolders`) through the single mutation channel (`POST …/actions`, expected-revision concurrency, membership permission class `edit`). No new table; no tokens stored; members are connection ids.
- D4 Destinations gain an optional `channelId`; two accounts on one platform are two destinations; the same account selected twice collapses to one.
- D5 Content Library: the 31 editorial types + 20 native formats are a local registry (ported artwork, provenance kept). Each item declares its execution mapping to the backend content type / format; unmapped native formats are `planning-only` (recorded, never coerced).
- D6 Reasoning: Low/Medium/High/Max is a stored preference per model; the UI shows the effective mapping for the selected route (`quick/standard/deep`, the CLI's five levels, or "Not applied by this provider").
- D7 Status colour (DNA §4.3 product-wide token decision): the existing `--destructive` token is the only semantic tint (failures and destructive actions). Warnings, success and unread states are monochrome: icon + status text + weight (`AnimatedBadge`, activity strip, overview/audit/member warnings, live island, notification counts); a near-limit allowance bar is hatched, not amber. Native app previews, brand marks and flags keep their own colours.
- D8 Brand copy: user-facing text uses the product name "Rafii" (`siteConfig.name`); legacy "Raffi" survives only in code identifiers (`RaffiPlanner`, `raffi_*` actions), which are not renamed.
- D9 Quick start reuses an idea's active source when the same text is drafted again (`ideas.quick_start`), instead of refusing it as a duplicate; own-writing approval is re-run only when it changes the source's policy, so earlier drafts are not marked stale. Test: `tests/phase2/postgres_quick_start_again.py`.
- D10 Saving Home results onto an existing unscheduled draft for the same account and language follows the existing refresh-in-place rule: an unedited candidate stays a proposed update (reported with a Pipeline link, never accepted silently); a caption edited on Home is recorded as an author edit on that draft.
- D11 Evidence runs use the dev harness with web research off (`postriff-api-offline` launch entry, `POSTRIFF_RESEARCH=0`). The default `postriff-api` entry has research on: the earlier seed/workflow runs on 2026-09-23 (before 22:07 local) sent their synthetic idea text as search queries to the keyless public endpoints `mcp.exa.ai` and `r.jina.ai`.

## Status

See the tables in `route-ledger.md` (routes) and `wiring-matrix.md` (controls). Final status fields are filled in `REPORT.md` at handoff.

## Phase 2 notes (foundation)

- Lightning CSS (Tailwind v4) drops a `backdrop-filter` whose value is `blur(var(--x))` and, when both prefixed and unprefixed declarations are present, keeps only `-webkit-backdrop-filter` (ignored by Chromium). `rafii.css` therefore writes literal blur values and only the unprefixed property.
- Dev harness (`scripts/postriff_dev_hosted.py`): the local consent page gained "Allow as a second account" so the disposable workspace can hold two distinct accounts on one platform (`…devmember2`, `@dev_creator_two`) for the folder/destination evidence. Dev-only; restart the API harness to load it (the disposable DB resets on restart).
- Streams launched 2026-09-23 15:40 local: A folders, B content library, C language/model dialogs, D preview deck, F1 calendar/queue, F2 inbox/channels, F3 ideas/pipeline/library, F4 workspace/overview/analytics, F5 account/auth/system, F6 marketing. Stream E (Home + conversation) follows A–D.

## Interruption record

- 2026-09-23 ~16:10 local: every subagent stream (A–D, F1–F6) was terminated by the account's session rate limit (HTTP 429, reset 19:30). Work on disk at that point: shared foundation complete; backend folders/destinations complete and tested; streams A–D and F1/F3/F4/F5 mid-verification, F2/F6 early. Whole-tree typecheck at 20:15: 4 errors (B, D, F2 files); lint not yet green.
- 20:20 local: streams A, B, C, D, F1 resumed in one wave (5 agents) to stay under the limit; F3, F4 next, then F2, F5, F6; Stream E (Home/composer) follows A–D. Dev harness + web server restarted (disposable DB reset).
- Files created 19:01 by a separate "launch audit" session in this checkout (`src/postriff_phase2/credit_meter.py`, `tests/test_launch_*`, `web/tests/launch-plan-accounts.test.cjs`, `tests/test_credit_meter_preview.py`) are not part of this work and are left untouched.
- 2026-09-23 ~21:30 local: the resumed streams C, D, A, B and F1 completed and reported; F2, F3, F4, F5 and F6 were stopped by "out of usage credits" (HTTP 429) while verifying. Their code was on disk and compiled; the coordinator (this session, continuing on Opus 5.5) finished their verification: full-page review of every route at 1440 dark and 390 light, fixes (profile `<p>`/`<div>` nesting via `settings-section.tsx`, marketing channel directory overflow, shared `CollectionRow` wrap basis, residual status tints per D7) and the evidence sweep.
- 2026-09-24 02:33 UTC: the Next dev server (Turbopack) exited after an internal panic ("Restore of All for task … failed"); restarted with `preview_start postriff-web`. Not caused by application code.

## Phase status (2026-09-24)

- Phases 1–6 done (2026-09-24): checks, evidence, conformance, rollback and status fields in `REPORT.md`; branch `rafii-v9-integration` (10 commits on 468811b, not pushed); file list by group in `v9-files.json`.
- Harness left running for review: `postriff-api-offline` (research off) + `postriff-web`, seeded workspace in `evidence/seed.json`. Switch back with `preview_stop` + `preview_start postriff-api` (resets the disposable database).
- 2026-09-24 18:54 UTC, production release: PR #1 was merged as `df9bea0` and deployed as `dpl_42MDoufsQgKD7rB8K4csc5RDsKyy` (alias postriff-phase2-private.vercel.app). Migration 018 was applied and verified first. Production smoke passed, and publishing stays disabled (no provider review flags). Details are in `orchestration.md` §11 and `migrations-review.md` (Production result).
- Next (needs the owner): physical-device pass (iPhone Safari, Android Chrome); live model/OAuth/publishing verification with authorized credentials; review and merge the branch; decide whether the snapshot and launch-audit commits belong in the merge.
