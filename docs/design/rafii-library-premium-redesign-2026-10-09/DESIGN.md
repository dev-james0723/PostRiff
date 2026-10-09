# Rafii Library — premium redesign (2026-10-09)

Branch `claude/rafii-library-premium-redesign-20261009`, stacked on `claude/rafii-intelligent-library-20261008`. The
Library product and security decisions of the 2026-10-08 engineering package (`docs/design/rafii-intelligent-library-2026-10-08/`,
the same content as `Rafii-Intelligent-Library-Engineering-Package-2026-10-08.pdf`) stay in force: one Add, scope beside
search, Used/Unused as a filter, honest previews, no fabricated analysis, source-purpose permissions, URL-restored state.

## 1. Before state (observed)

Screenshots in `before/` come from the remote browser harness on the current candidate (headless Chromium and WebKit, a
synthetic dev workspace with sample files, signed in through the dev identity provider; not production data).

| Area | Problem observed |
|---|---|
| Buttons | Two competing heights (90 controls at 48 px `control`, 36 hand-overridden to 44 px); 20 filled `action` buttons across the Library; the page Add, the empty-state Choose assets, the detail panel's Use in draft and Use in a post all render as primaries. |
| Chrome | At 390 × 844 the header, search, scope line, Search/Ask, collection row, All/Unused/Used, Filters and the view row stack to ~530 px; Add sits alone on its own row. Desktop repeats the pattern with 48 px controls everywhere. |
| Usage | All / Unused / Used is a large segmented control styled as primary navigation. |
| Cards | Audio and video cards render a full player (play, time, speed select, timeline, volume) on every tile; video previews start (muted) as they scroll into view. Every card shows a usage badge ("Unused") even when nothing is used. Short documents show a whole white page letterboxed into a square. Card actions exist only in a context menu (no visible affordance on touch). |
| Detail | A modal sheet over a blurred page; the first screen is processing states and a permission list; the real preview is below the fold under Content; the footer has up to five buttons including two primaries. |
| Selection | The batch bar is a large floating card with eight equal-weight buttons, including Delete. |
| Rail | Collections and storage sit in a rail, but Smart views and manual collections are mixed and management expands inline. |

## 2. Direction

A calm creative-asset workspace in Rafii's own materials: soft neutrals, the existing green action colour, glass only where
it separates layers (sticky toolbar, bulk bar, inspector edge). Density comes from alignment and a strict control scale,
not from smaller type. Previews carry the colour; chrome is monochrome.

## 3. Layout

Desktop (≥1024): app navigation → Library rail (216 px, collapsible to 52 px) → workspace → inspector (only when an item is
open). From 1280 px the inspector docks beside the grid (384 px, sticky, non-modal) and the rail collapses while it is open
below 1600 px; below 1280 it is a sheet; on phones a drawer.

Workspace stack, top to bottom:
1. Header row: `Library` + info, and the single primary `Add` (Upload files / Paste link / Quick note) on the same row at
   every width.
2. Search: one 40 px field (`/` focuses it). Under it, the scope in words ("Searching Entire permitted Library", "This
   collection", "Selected N items") is itself the scope picker when more than one scope exists; Search/Ask sits at the
   right of that line as a quiet two-option switch when Ask is available.
3. Toolbar: Type, Usage, Status, Tag as compact native selects that show their value; Clear when any is set; Sort after a
   divider; then the count, Gallery/List and density. Nothing hides behind a Filters panel: on phones the filters are one
   row that scrolls inside itself, with the count and view controls on the row below.
4. Results. The bulk bar replaces nothing; it sticks to the bottom only while something is selected.

At 390 × 844 the first card's title and the top of its preview are above the fold (asserted by the browser harness, A059).

Rail: `All assets` (the whole permitted Library), `Collections` (manual) with a quiet `New collection`, `Smart views`
(rule-based collections) with `New smart view` when the service is reachable, and a one-line storage meter at the bottom
(warning only from server values). Recent and Starred are not shown: no recency view or star exists in the product yet.

## 4. Control system (`web/src/features/library/ui/controls.tsx`)

One scale, mapped onto the existing `Button` materials (no change to the shared design tokens):

| Tone | Material | Use |
|---|---|---|
| primary | `action` (filled) | Exactly one per surface: page Add; the confirm step of a dialog. |
| secondary | `glass` | Contextual commitments: Use in draft, Download, Add to collection, Save. |
| ghost | `quiet` | Utilities: filters, sort, view, scope, clear, options. |
| danger | `destructive` | Delete/Remove; always separated from positive actions and confirmed. |

Sizes: `md` 36 px and `sm` 32 px on fine pointers; both become 44 px on coarse pointers (`pointer-coarse:`). Icon buttons
are square at the same heights, always with `aria-label` and a tooltip. One radius (`--rafii-radius-control`), 16 px icons,
`gap-1.5`, 12 px horizontal padding (`md`), 10 px (`sm`). Focus: the existing ring; pressed: 1 px translate (already in
`Button`); loading: spinner replaces the leading icon, label stays.

## 5. Cards (`asset-card.tsx`, `asset-list-row.tsx`, shared parts in `asset-card-parts.tsx`)

Order: preview → title (one line, truncated, the full name in the tooltip and the accessible name) → one meta line
(type · duration, dimensions or size) → at most one status (Processing, Needs attention, Publishing, Used in N). "Unused"
and "Stored privately" are not shown: they are the defaults (Unused is a filter; every item is private).

- Images: whole picture, letterboxed on a neutral 4:3 tile (no destructive crop).
- Video: real poster and duration chip. One muted preview at a time may play while visible (never under reduced motion,
  never after the person pauses it), labelled "Silent preview"; sound only starts from a press.
- Audio: real decoded waveform after the first play (never a decorative timeline); a calm audio tile before that; play,
  time and seek visible; speed and volume behind Playback options.
- Documents: the real rendered first page, framed from the top of the page so text is legible; label `PDF · PAGE 1` only on
  a real raster; Preparing/Unavailable otherwise.
- Selection: checkbox top-left on hover/focus/selection mode, always on coarse pointers; selected = 2 px foreground ring.
- Actions: a visible More (⋯) button top-right (hover/focus on fine pointers, always on touch) with the same items as the
  context menu; Delete last, separated, destructive.
- Density: comfortable and compact use the same component; compact shrinks the grid gap, caption padding and hides the
  meta line.

## 6. Inspector (`asset-detail.tsx`)

Header (title, close) → large preview → one action row (secondary: Use in draft, Use in a post — or a quiet Open Ideas
when the item can't be posted; icon buttons: Open original, Download original) → sticky section tabs Overview · Content ·
Related · Usage. Overview leads with what the item is, the summary and suggested uses; processing states and source
permissions sit in a "Processing and permissions" disclosure; technical details stay collapsed; Delete stays in the danger
area at the end.

From 1280 px the inspector is a docked, non-modal panel: focus moves to its heading when it opens, Escape closes it while
focus is inside, and focus returns to the card that opened it. The query, filters, selection and scroll position are
untouched. Below 1280 px it is a sheet; on phones a drawer whose footer keeps the actions in thumb reach.

## 7. Motion

Only opacity/transform; 150–200 ms ease-out for hover/press and menus, 240 ms for the inspector; no tilt or scale on
cards; `prefers-reduced-motion` removes movement and keeps opacity.

## 8. Verification

Remote browser harness (Chromium + WebKit) at 1440 × 900, 768 × 1024, 390 × 844, 844 × 390 and 200 % zoom with mixed file
types, long and Cantonese/Traditional Chinese/English names and > 200 items; screenshots return through the CI log.
Existing Library acceptance (formats, collections, document viewer, inline media, transcripts, deletion) must keep
passing. Real iPhone Safari remains a manual check (A066).

## 9. After (head `ea99149e`, run `rjzngvv5pw`)

Screenshots in `after/` come from the same remote harness as `before/`, on the final head. Run
[rjzngvv5pw](https://depot.dev/orgs/jf34f85hr0/workflows/rjzngvv5pw) on Depot `depot-ubuntu-24.04-16` passed with remote
exit 0; its receipt binds `sourceHead` ea99149e. The after workspace also holds the harness's 200+ bulk items and its
long Cantonese/Traditional Chinese/English names, so the item counts differ from `before/`. All runs, failures included,
are listed in `runs.md`.

| View | Before | After |
|---|---|---|
| Desktop 1440 × 900 | `before/library-chromium-desktop-1440x900.jpg` | `after/library-chromium-desktop-1440x900.jpg` |
| Desktop, item open | `before/library-chromium-desktop-1440x900-detail.jpg` (modal sheet) | `after/library-chromium-desktop-1440x900-detail.jpg` (docked inspector) |
| Desktop, selection | `before/library-chromium-desktop-1440x900-selected.jpg` | `after/library-chromium-desktop-1440x900-selected.jpg` |
| Tablet 768 × 1024 | `before/library-chromium-tablet-768x1024.jpg` | `after/library-chromium-tablet-768x1024.jpg` |
| Phone 390 × 844 | `before/library-chromium-phone-390x844.jpg` | `after/library-chromium-phone-390x844.jpg` |
| Phone, item open | `before/library-chromium-phone-390x844-detail.jpg` | `after/library-chromium-phone-390x844-detail.jpg` |
| Phone, selection | `before/library-chromium-phone-390x844-selected.jpg` | `after/library-chromium-phone-390x844-selected.jpg` |
| WebKit 1440 / 390 | `before/library-webkit-1440.jpg`, `before/library-webkit-390.jpg` | `after/library-webkit-1440.jpg`, `after/library-webkit-390.jpg` |

New in `after/` (no before equivalent): `library-chromium-phone-landscape-844x390.jpg`, `library-chromium-zoom-200-1280x800.jpg`,
`library-chromium-*-player.jpg` (Now Playing clearance).

What changed, observed in the screenshots:

- **One primary.** Add is the only filled control on the page. The empty state, inspector and bulk bar use secondary or
  ghost controls (the harness also asserts exactly one `.rafii-action` in the Library page).
- **Phone first view.** Before, Add sat on its own row and All/Unused/Used plus Filters took two more rows. The first card's
  player pushed its title below the fold. After, the header holds Library and Add on one row, the filters are one
  scrolling row, and the first two cards' titles are above the fold at 390 × 844 (A059 asserts the preview position).
- **Cards.** "Unused" and "Stored privately" badges are gone. Each card shows its name, one meta line, and a status only when one
  applies. Audio cards keep a compact player (play, timeline, Playback options) instead of the full player with speed and
  volume on every tile. In narrow cards the time label gives way so the timeline stays usable.
- **Desktop item view.** A non-modal docked inspector replaces the blurred modal sheet. The grid, filters and selection
  stay visible and usable; the rail collapses to icons while it is open.
- **Selection.** One compact bar: count, Select all shown, Search only these, then the actions, with Delete separated in
  the destructive style. On phones both rows scroll inside themselves and fade at the edge.

Known limits, unchanged by this redesign:

- Short text documents (MD, CSV) show their real first page, so at tile size the text is tiny. That is honest, but it is
  hard to read.
- List view keeps an inline player on every audio and video row. The existing Library acceptance requires it.
- The "New to Library?" tour prompt overlaps the header for 8 s on a first visit (app-wide onboarding).
- Real iPhone Safari (A066) still needs a device.
