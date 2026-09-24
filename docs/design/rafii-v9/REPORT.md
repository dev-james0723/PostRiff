# Rafii v9 production integration — report

Date: 2026-09-24. Repository: `/Users/ouxianxing/Documents/James-Au-Studio` (branch `consumer-saas`, HEAD `468811b` at start, unchanged). Authority: `docs/design/reference/rafii-v9/` (DNA v8 + v9 addendum + prototype, hashes checked against `INPUT-MANIFEST.json`). Ledger: `PROGRESS.md`; coverage: `route-ledger.md`; controls: `wiring-matrix.md`.

## 1. What was delivered

- **Design system in the real app.** A `rafii` theme (monochrome liquid glass, borderless resting surfaces, Geist + serif-italic accents, motion roles, reduced-motion and no-`backdrop-filter` fallbacks) is the default theme; the existing theme selector and light/dark switch still work. Shared components in `web/src/components/rafii/` (Surface, PageHeader, SegmentedControl, StateMessage, Workbar/ActiveFilters, FilterPanel, RafiiDialog, InfoTip, CollectionRow, SemanticIllustration, ReasoningBars) and `web/src/lib/rafii/motion.ts`; button variants `glass`/`action`/`quiet`; restyled shell (header, sidebar, mobile tab bar, page container).
- **Homepage (`/app`) on the real services.** v9 composer (Context Pocket, content type from the 31 + 20 Content Library, Channel Bloom accounts and folders, per-destination language, model + reasoning, writing voice) → the existing `quickStart` run → one editable draft per account in the native phone deck → "Save as drafts" through `applyRun` + `variant_edit`. No iframe, no prototype code path, no screenshots.
- **Account identity end to end.** `Destination.channelId` from selection to run, variants, apply, conversation and plan review; the server verifies it against the workspace's live connections. Two accounts on one platform are two drafts; overlapping folders never duplicate a draft. Saved folders persist in workspace state through `p2_folder_save/delete/move`.
- **Every Rafii-owned route migrated** with loading, empty, error, permission and stale states on the shared components; routes, permissions and behaviour unchanged. 43 routes were captured: 23 authenticated app routes and 20 auth, invitation, system and marketing pages (`route-ledger.md`). The auth callback handler is not visual; `/dev/*` galleries are not product routes.

## 2. Code location and how to run

- Working tree: all changes are in the shared checkout (uncommitted there, as the other sessions' work is).
- Branch: `rafii-v9-integration` (created with git plumbing; HEAD, the index and the working tree of the shared checkout were not touched). See §9 for the commit list.
- Run locally (research off, nothing leaves the machine):

```
preview: postriff-api-offline (4331) + postriff-web (3100)   # .claude/launch.json
node web/tests/rafii-seed.cjs                                 # synthetic principal, two LinkedIn accounts, folders
RAFII_CHROMIUM_PATH=… node web/tests/rafii-workflow.cjs       # real-input workflow + motion recordings
RAFII_CHROMIUM_PATH=… node web/tests/rafii-evidence.cjs       # every route × 8 viewports × 2 themes (+ axe)
```

Environment variable names used: `POSTRIFF_RESEARCH` (0 = web research off in the harness), `RAFII_WEB_URL`, `RAFII_DEV_PRINCIPAL`, `RAFII_CHROMIUM_PATH`, `RAFII_WEBKIT_PATH` (local browser builds; nothing is downloaded).

## 3. Verification results (this build)

| Check | Command | Result | Baseline (before any edit) |
|---|---|---|---|
| Types | `npx tsc --noEmit` (web) | 0 errors | 0 errors |
| Lint | `npm run lint` (web) | 0 warnings, 0 errors | 0 errors, 1 warning |
| Node contracts (baseline command) | `node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs` | 42/42 pass | 38/38 |
| Node incl. new unit files | + `src/**/*.test.cjs` (folders, Channel Bloom, taxonomy, reasoning map, language ops, preview deck) | 89/89 pass | n/a |
| Python unit | `.venv/bin/python -m unittest discover -s tests` (PYTHONPATH=src:tests) | 607 OK | 577 OK |
| PostgreSQL integration | `scripts/postriff_disposable_postgres.py` with `postgres_quick_start_again` (new), `postgres_ideas`, `postgres_research`, `postgres_agent_plan`, `postgres_billing`, `postgres_api_tokens`, `postgres_cli_route`, `postgres_cli_reasoning`, `postgres_raffi_planning`, `postgres_channels` | all pass (billing needs `PYTHONPATH=src:tests`) | — |
| Real workflow, Chromium | `web/tests/rafii-workflow.cjs` (workflow, motion, reduced, mobile) + `--only=library` | 40/40 + 6/6 checks, 0 console/page errors | — |
| Real workflow, WebKit | same, `--browser=webkit` | 40/40 + 6/6 checks, 0 console/page errors | — |
| Route evidence, Chromium | `web/tests/rafii-evidence.cjs` | 688 captures (43 routes × 8 viewports × 2 themes). Findings only: 16 × the harness 500 on API settings, 16 × the expected 404 on the not-found route, 1 intermittent axe colour-contrast on sign-in at 375 light (not reproducible in 3 re-runs). No horizontal overflow; no other axe violation | — |
| Route evidence, WebKit | same, 390×844 + 1440×1000 | 172 captures (43 routes × 2 viewports × 2 themes). Findings only: 4 × the harness 500, 4 × the expected 404 | — |
| Production build | `next build` in a clean worktree of the branch | exit 0, "Compiled successfully" (worktree of the branch with cloned node_modules; typecheck 0 errors, lint 0/0, Python 607 OK there too) | — |

Mock boundary: drafting in automation uses the `deterministic-preview` fixture route (the workflow script aborts any drafting request with another model before it reaches the server); OAuth accounts are the dev harness's synthetic provider; nothing was published, sent or charged. No live model, OAuth, publishing or payment path was exercised.

### Real workflows verified (both browsers)

1. Home → Channel Bloom: saved folders load from the server; the Festival folder's inspector unfolds and folds; selecting the overlapping Personal + Festival folders stages exactly two accounts.
2. The idle deck names both accounts on the one platform.
3. Language dialog lists each account separately; changing only the second account applies to it alone (server confirms: first account keeps its language).
4. Model dialog: provider swaps and reasoning segments do not change the committed model; the fixture route shows an honest "not applied by this provider".
5. Generate → real run → "2 of 2 ready"; results keep each account as its own draft; mouse swipe moves the deck.
6. Caption edit → "Save as drafts" → the server holds exactly one draft per account for the run, the edited caption as a new revision; a refresh of an existing unscheduled draft stays a proposed update and is reported (observed in WebKit).
7. Conversation view names each account.
8. Motion clips: provider swap + reasoning bars, language disclosure (Escape closes the catalogue first), folder unfolding, phone swipe/dock/rapid interrupts/expanded preview with focus return.
9. Reduced motion: no spatial animation on deck switch or folder inspector; state still changes.
10. 390×844: no horizontal scroll, 16px composer text, the mobile bar never covers Generate, Channel Bloom sheet with 16px search.
11. Content Library from Home: stage "Behind the scenes" + "Carousel", apply → the server records `pack.creator:building_in_public` / `carousel`; Escape discards staged choices; the starting choice is restored.

Recordings (`.webm`, one per scene and browser) and screenshots: `evidence/workflow/<browser>/<scene>/`; reports: `evidence/workflow/<browser>/report.json`.

## 4. Design-DNA conformance

| DNA area | Status | Notes |
|---|---|---|
| Monochrome materials, borderless surfaces | conforms | glass / selected / elevated / quiet / composer materials as tokens; pages use `Surface`, not per-page palettes |
| Colour permissions (§4.3) | conforms | decision D7: `--destructive` is the only semantic tint; warnings/success/unread are icon + text + weight; near-limit bars hatched. Native previews, brand marks and flags keep their colours (allowed) |
| Typography | conforms with deviation | Geist from next/font; editorial accent uses the system serif stack (no new font dependency, D2) |
| WHAT → FIND → VIEW → COMMIT | conforms | page headers, workbars/filters, collection rows, one primary action per task surface |
| Staged vs applied | conforms | dialogs stage; Apply/Done commits; Cancel/Escape discards (Channel Bloom, language, model, content library) |
| Honest states | conforms | loading/empty/error/permission/stale/partial/unsupported via `StateMessage`; refused starts and refresh-in-place proposals are shown, not hidden |
| Controls & touch targets | conforms | 44–48px primary controls, 16px inputs on phones; month-calendar chips stay 26px (tab-skipped; day view lists every event) |
| Motion roles & reduced motion | conforms | tokens per role; spatial motion off under reduced motion (verified in the browser) |
| Mobile | conforms | no horizontal scroll at 320–430px after the fixes in §6 (evidence sweep) |
| Hyphenation | deviation | long model names hyphenate where the browser has dictionaries; headless Chromium breaks the word — button padding was reduced below 400px so "Deterministic preview" fits |

## 5. Decisions

D1–D11 in `PROGRESS.md` (theme default, fonts, folders in workspace state, `channelId` destinations, local Content Library registry, reasoning preference per model, status colour, brand copy "Rafii", quick start source reuse, refresh-in-place reporting, research-off evidence harness).

## 6. Defects found and fixed during integration

- Changing one account's language silently re-languaged the other account on the same platform (platform memory) → other accounts keep what they show.
- A refused generation start was invisible on Home → shown in the results column with Try again.
- Drafting the same idea again failed with "That source is already here…" → the quick start reuses the active source (D9, backend + PostgreSQL test).
- Caption edits were lost when the run refreshed an existing unscheduled draft → recorded on that draft; unedited refreshes reported (D10).
- Conversation composer: one chip per platform hid the second account → one pill per account; the composer is now one destinations row + one tools row with a single primary action (feedback from the founder's phone screenshot).
- Profile `<div>` inside `<p>` (hydration error), unlabeled combobox buttons, low-contrast account label on the active draft tab.
- Horizontal overflow on phones: header at 320px, channel directory grid, connector setup messages, collection rows, unpositioned horizontal scrollers, segmented controls with large counts, the legal page layout.
- Keyboard access to tables that scroll sideways (focusable, labelled region only while they overflow).
- Setting buttons: top-aligned so icon and label rows line up whatever the value length; values hyphenate instead of breaking mid-word.
- Tour prompts covering page titles in evidence (pre-dismissed in the scripts, not in the product).

## 7. Remaining limitations and unverified items

- **Devices.** Emulation only: headless Chromium (build 1243) and WebKit (build 2359) through Playwright, at 320–1920px. No physical iPhone/Safari, Android or Edge check was run; real mobile keyboards were not inspected.
- **Live services not exercised.** Drafting used the `deterministic-preview` fixture; accounts came from the harness's synthetic OAuth provider; no live model or CLI call, real OAuth, publishing, schedule approval, message sending or payment was performed. These need the owner's authorization and credentials.
- **API settings in the harness.** `/app/account/api` loads its token list from `GET …/tokens`, which returns 500 in the local harness because the disposable schema has no API-token table (pre-existing environment gap, not touched by this work). The page shows its error state; this is the only console error besides the not-found route's expected 404.
- **Not captured / not forced.** Invitation acceptance (only the invalid-token state is captured), the global-error boundary and the app gate's error states, and the Content Library's nested Escape order (tooltip → evidence → filters) with a real keyboard.
- **Accessibility scope.** axe-core WCAG 2 A/AA automated rules on every capture (clean apart from the items above) plus the keyboard/focus checks in the workflow. No manual screen-reader (VoiceOver/NVDA) pass; this is not a full conformance claim.
- **Motion.** Recorded (`.webm`) and checked for state/interrupt/reduced-motion behaviour, not measured frame by frame.
- **Accounts.** Two accounts on one platform were verified with LinkedIn (the harness trial allows two connected accounts).
- **Small targets kept.** Month-calendar event chips stay 26px (tab-skipped; the day view lists every event) and the mini month picker's cells 36px.
- **Hyphenation.** Long values hyphenate only where the browser has dictionaries.
- **Dev server.** Turbopack panicked once during the run ("Restore of All for task … failed") and was restarted; not reproduced.
- **Research egress before 22:07 (2026-09-23).** The default `postriff-api` harness entry has web research on; earlier seed/workflow runs sent their synthetic idea text as queries to `mcp.exa.ai` and `r.jina.ai` (keyless public endpoints). All later evidence ran with `POSTRIFF_RESEARCH=0`.
- **Shared checkout.** Other sessions' uncommitted work (including a still-active launch-audit session and the Dori animation work) remains in the working tree untouched; the dirty `vendor/xiaohongshu-mcp…` submodule was not changed.

## 8. Rollback

Nothing was deployed and no database migration was run. The backend changes are additive: `channelId` is optional on destinations and variants, folders live in workspace state (`phase2.channelFolders`) behind three new actions, and the quick start reuses a matching source. The pre-v9 code never reads these keys, so data written by v9 is inert if the code is rolled back.

1. **Branch.** Nothing is merged. To roll back after a merge, revert the v9 commits newest first (tooling, pages, home, preview, dialogs, library, destinations, foundation); the snapshot and launch-audit commits are independent.
2. **Look only, without reverting code.** The previous themes remain selectable in Appearance (cookie `active_theme`); setting `DEFAULT_THEME` back in `web/src/components/themes/theme.config.ts` restores the old default in one line. The v9 page structure stays.
3. **Shared working tree (uncommitted).** `docs/design/rafii-v9/v9-files.json` lists every v9 file by group. For a tracked file, `git show rafii-v9/baseline-worktree:<path>` is its pre-v9 content (other sessions' earlier edits included); files v9 created can be deleted; `model_runtime.py` and `plan.ts` also carry the launch-audit promotion, whose pre-image is in that session's `evidence/pre-promotion/`. The five pre-existing untracked files that v9 also edited have no recorded pre-v9 content (listed in the same file; the edits are small).
4. **Dev harness.** Stop `postriff-api-offline` and start `postriff-api` to return to the research-on harness (the disposable database resets on restart).

## 9. Branch and commits

Branch `rafii-v9-integration` on top of `468811b` (not pushed; `consumer-saas`, its index and working tree untouched). List with hashes: `git log --oneline 468811b..rafii-v9-integration`.

1. `chore: snapshot uncommitted work from earlier sessions (before Rafii v9)`: the baseline stash tree plus the earlier sessions' untracked code, tests, scripts and one test fixture (no build output, research bundles or zips), so the v9 commits build on what they were developed against.
2. `feat(rafii): design tokens, materials, motion and shared components`
3. `feat(channels): account-keyed destinations and saved channel folders` (backend + UI + tests)
4. `feat(library): content library taxonomy, artwork and selection dialog`
5. `feat(agent): output-language and model dialogs with reasoning mapping`
6. `feat(preview): native phone deck, dock and expanded preview`
7. `feat(home): v9 composition on real generation, conversation and plan review`
8. `feat(pages): apply the Rafii design DNA to every app, account, auth and marketing route`
9. `docs(rafii): integration ledger, reports and evidence tooling`
10. `chore: include launch-audit promotions from the shared checkout`: the separate launch-audit session's promoted files, kept apart so they can be dropped.

The branch tip matches the verified working tree file for file, except `.claude/launch.json` (another session's Dori preview entry is left out). Only the tip is build-verified; the intermediate commits are grouped for review.

## 10. Status fields

- **IMPLEMENTED** — v9 design system and shell; Home on the real quick-start service with Content Library, Channel Bloom accounts/folders, language/model/voice dialogs and the native phone deck; account-keyed destinations and saved folders (backend + UI); conversation and plan review by account; every Rafii-owned route migrated; the defects in §6 fixed. Local code in the shared checkout and on branch `rafii-v9-integration` (not pushed).
- **FUNCTIONALLY_VERIFIED** — Chromium and WebKit real-input runs: Home workflow 40/40 checks each, Content Library 6/6 each (fixture model, synthetic accounts, local harness); Python 607, node 89, typecheck, lint and the PostgreSQL suites listed in §3; render checks for every captured route.
- **VISUALLY_VERIFIED** — 43 routes captured: Chromium 688 screenshots at 8 viewports × 2 themes, WebKit 172 at 390/1440 × 2 themes, every capture checked for console errors, horizontal overflow and axe (§3); full-page review by eye of every route at 1440 dark and 390 light; screen recordings of the workflow, motion, library, reduced-motion and 390 scenes in both browsers. Visual review is by eye plus automated checks, not a pixel comparison with the prototype.
- **BLOCKED_OR_UNVERIFIED** — physical devices; live model/CLI generation, real OAuth, publishing, schedule approval, payments (need owner authorization); API-token list (harness schema gap); invitation acceptance; global-error and gate error states; manual screen-reader pass.
- **PREVIEW_DEPLOYMENT** — none. No preview deployment was created; verification ran on the local dev harness only.
- **PRODUCTION_DEPLOYMENT** — none. Nothing was deployed, migrated or published.

## 11. After the release: Automations and next steps (2026-09-24)

Built on top of this branch after the production deploy; **not deployed**.

- Automations Phases 1–3 (hub and builder; templates, monthly and countdown schedules, "drafts ready",
  batching and spend; triggers from new Ideas material and strong posts, evergreen): see
  `automations.md` for design, safety rules, verification and limitations.
- Home speed: dialogs code-split and preloaded when idle; Vercel Analytics opt-in
  (`NEXT_PUBLIC_VERCEL_ANALYTICS=1`).
- CI: `.github/workflows/rafii-browser.yml` runs the Rafii Playwright scenes on pull requests.
- Before deploying: the read-only production migration check in `migrations-review.md` (Automations
  need 018; 013 stays blocked on approval), then the steps in `real-world-checks.md` that need James.
