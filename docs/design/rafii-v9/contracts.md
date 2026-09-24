# Rafii v9 integration — shared contracts for parallel streams

Read `Rafii_Design_DNA_v8.md` §2, §5–§12, §18–§20 and `Rafii_Design_DNA_v9_Addendum.md` in `docs/design/reference/rafii-v9/` before building. The prototype (`rafii-prototype-v9.html`, source zip → `src/*.css`, `src/app.js`) is the approved visual/interaction reference; the repository is authoritative for routes, data, permissions.

## Foundation already in place (do not fork it; extend by reporting gaps)

- Theme: `web/src/styles/rafii.css` — `[data-theme='rafii']` (default theme) feeds shadcn tokens from semantic `--rafii-*` tokens in light and `.dark`. Motion roles `--rafii-time-*`, `--rafii-ease-*`; radii `--rafii-radius-*`; control sizes `--rafii-control-*`.
- Material utilities (Tailwind `@utility`, usable with variants): `rafii-glass`, `rafii-glass-selected`, `rafii-lens`, `rafii-elevated`, `rafii-composer`, `rafii-quiet`, `rafii-field`, `rafii-panel`, `rafii-action`, `rafii-scrim`, `rafii-serif`, `rafii-eyebrow`, `rafii-focus`, `rafii-paper`. Reduced effects/motion hooks: `[data-effects='reduced']`, `[data-motion='reduced']`, `.rafii-decorative-motion`, `.rafii-spatial-motion`.
- Components `web/src/components/rafii/` (import from `@/components/rafii`): `Surface`, `PageHeader`, `SegmentedControl` (persistent lens, radio/tabs patterns), `StateMessage` (empty/loading/error/permission/offline/stale/partial/unsupported), `Workbar` + `ActiveFilters`, `FilterPanel` + `FilterSelect`, `RafiiDialog*` (elevated glass dialog: header/body/footer; bottom sheet on phones), `InfoTip` (descriptive tooltip that never selects its parent), `CollectionRow`.
- `Button` gained variants `glass | action | quiet` and sizes `control (48px) | hero (56px) | icon-control (44px round)`.
- Motion `web/src/lib/rafii/motion.ts`: `useMotionPreference()` (OS + app setting), `motionAllowed()`, `animateHeight()/useMeasuredDisclosure()` (480ms measured height), `beginSwap()/useCrossfadeSwap()` (430ms crossfade keeping an inert outgoing clone), `RAFII_TIME`, `RAFII_EASE_CSS`.
- Shell: `AppShell` (ambient canvas), `Header` (glass panel), `MobileTabBar` (lens), `PageContainer` (uses `PageHeader`; props `pageEyebrow`, `pageAccent`, `density`, `width='reading'`).

## Data contracts (backend done, tested)

- Destination: `{ platform, language, channelId? }` (`web/src/lib/api/types.ts` `Destination`). `channelId` is a `Phase2State.channels[].id`. Two accounts on one platform = two destinations; the same account in the same language twice is a client error (server 400). Server rejects unknown/revoked/other-platform ids with 409. `RunVariant`/`SnapshotVariant` carry `channelId` (+`account` on run variants); `SchedulePlanDestination.channelId` too. `ideas.apply` refreshes a draft in place only for the same (platform, language, channelId).
- Folders: `Phase2State.channelFolders?: ChannelFolder[]` `{ id, name, symbol, pinned, accountIds }`. Mutations through `api.act(workspaceId, expectedRevision, action, payload)`:
  - `p2_folder_save` `{ id?, name, symbol?, pinned?, accountIds }` (create when no id; edit keeps stale member ids already stored)
  - `p2_folder_delete` `{ id }`
  - `p2_folder_move` `{ id, delta: -1 | 1 }` (within pinned/unpinned section)
  - Limits: 40-char names, 50 folders, no nesting. Errors come back as `ApiError` messages; 409 on stale revision → refetch snapshot and retry once (pattern in `use-channel-languages.ts` `save`).
- Client folder rules: `web/src/lib/channels/folders.ts` (tested): `cleanSelection`, `selectionState`, `toggleGroup`, `validateFolder`, `copyName`, `visibleFolders`, `canMove`, `snapshotContext`, `selectionLabel`, `FolderAccount`.
- Accounts for pickers: `state.phase2.channels` → `{ id, platform, account, displayState }`. Drafting is possible for `DRAFT_PLATFORMS` (`LinkedIn | Instagram | Threads | Xiaohongshu`, `features/agent/composer.tsx`); an account on another platform is shown but not selectable as a draft destination (explain, do not hide). A platform with no connected account may still be drafted at platform level (existing behaviour: "No account connected yet · drafts only").
- Languages: `useChannelLanguages` (`features/agent/use-channel-languages.ts`) remembers languages per platform (`language_settings` action). Keep multi-language per destination.

## Rules every stream follows

1. Monochrome Rafii chrome only. Real media, flags, provider marks and native previews keep colour.
2. Resting surfaces borderless (use materials); visible focus (`rafii-focus` or the Button ring); 44px touch targets; 16px text entry on phones; readable labels (no 7–9px text).
3. WHAT → FIND → VIEW → COMMIT: one dominant primary action per active surface; no duplicate controls.
4. Staged vs applied: dialogs stage changes, `Apply/Done` commits, Cancel/close restores. Filters and view switches never mutate content or destinations.
5. Honest states: no fake success; use `StateMessage`; never invent counts.
6. Motion: use `lib/rafii/motion.ts`; respect `useMotionPreference().reduced`; outgoing layers inert and cleaned up; rapid actions settle on the last request.
7. Accessibility: correct roles (`radiogroup`/`tablist`/`checkbox` with `aria-checked='mixed'`), labels, Escape order (deepest layer first), focus return.
8. Do not add dependencies. Do not start dev servers on new ports (the harness runs on 3100/4331; use it read-only if you need to look). Do not edit files outside your stream's list; report needed changes to shared files instead.
9. Before finishing: `npm --prefix web run typecheck` and `npm --prefix web run lint` must pass; add `*.test.cjs` node tests for pure logic (pattern: `web/src/lib/channels/folders.test.cjs`).
