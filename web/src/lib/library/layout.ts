/**
 * Bottom clearance and the mobile first-screen budget for the Library (UI spec §1, §6; A059, A065, A066).
 *
 * The fixed layers at the bottom of the app are measured from their own source so the Library can stay clear of
 * them: the mobile tab bar (`components/layout/mobile-tab-bar.tsx`, `h-[calc(4.25rem+env(safe-area-inset-bottom))]`)
 * and the Now Playing bar (`features/now-playing/now-playing-bar.tsx`, `bottom-[calc(4.75rem+env(safe-area-inset-bottom))]`
 * on phones, `md:bottom-5` on wider screens). The app shell already pads the page for the tab bar; this adds the
 * player and keeps the batch bar above both. web/tests/library-intelligence-ui.test.cjs checks these constants
 * against those files.
 *
 * No '@/' imports: the test transpiles this module on its own.
 */

/** Mobile tab bar height, before the safe-area inset. */
export const TAB_BAR_REM = 4.25;
/** Now Playing bar offset from the viewport bottom on phones, before the safe-area inset. */
export const PLAYER_BOTTOM_MOBILE_REM = 4.75;
/** `md:bottom-5`. */
export const PLAYER_BOTTOM_DESKTOP_REM = 1.25;
/** Collapsed player: padding, title row, seek bar and the save row, rounded up. */
export const PLAYER_HEIGHT_REM = 7;
/** The expanded video (`max-h-52`) and its margin. */
export const PLAYER_VIDEO_REM = 13.5;
/** The Library's batch bar: 44 px controls plus padding. */
export const BATCH_BAR_REM = 4;
export const GAP_REM = 0.5;

export interface BottomClearance {
  /** CSS `bottom` for a sticky bar that must sit above every fixed layer. */
  stickyBottom: string;
  /** Extra space after the last result, beyond the shell's own tab-bar padding. */
  spacer: string;
  /** Height from the viewport bottom that fixed layers cover (rem, before the safe-area inset). */
  coveredRem: number;
  /** Where a sticky batch bar's top edge ends up (rem from the viewport bottom). */
  batchTopRem: number;
}

export function bottomClearance({ mobile, playerOpen, playerExpanded = false }: { mobile: boolean; playerOpen: boolean; playerExpanded?: boolean }): BottomClearance {
  const tabBar = mobile ? TAB_BAR_REM : 0;
  const playerTop = playerOpen ? (mobile ? PLAYER_BOTTOM_MOBILE_REM : PLAYER_BOTTOM_DESKTOP_REM) + PLAYER_HEIGHT_REM + (playerExpanded ? PLAYER_VIDEO_REM : 0) : 0;
  const coveredRem = Math.max(tabBar, playerTop);
  const stickyRem = coveredRem + GAP_REM;
  // The shell pads `main` by the tab bar on phones; only what rises above it needs more room.
  const spacerRem = playerOpen ? Math.max(0, playerTop - tabBar) + GAP_REM : 0;
  return {
    stickyBottom: `calc(${stickyRem}rem + env(safe-area-inset-bottom))`,
    spacer: `${spacerRem}rem`,
    coveredRem,
    batchTopRem: stickyRem + BATCH_BAR_REM
  };
}

/**
 * The phone layout above the first result at 390 × 844, in CSS pixels, from the classes used in the Library:
 * app header `h-16`, page padding `pt-3`, title, the Add button row (`h-12`), page gap `gap-5`, the search row
 * (`min-h-11`) with its scope line, the collection switcher row (`h-11`), the filter row (`min-h-11`), the view row (`min-h-11`) and the
 * `gap-3` between them. No banners (the spec's measurement condition).
 */
export const MOBILE_CHROME_PX = {
  appHeader: 64,
  pageTop: 12,
  pageTitle: 36,
  titleGap: 12,
  addButton: 48,
  pageGap: 20,
  search: 44,
  scopeLine: 24,
  switcher: 44,
  filters: 44,
  view: 44,
  gaps: 12 * 4
} as const;

export const CARD_TITLE_PX = 28;
export const PAGE_GUTTER_PX = 16;
export const GRID_GAP_PX = 12;

export function mobileFirstAsset({
  viewportWidth = 390,
  viewportHeight = 844,
  chrome = MOBILE_CHROME_PX,
  columns = 2
}: { viewportWidth?: number; viewportHeight?: number; chrome?: Record<string, number>; columns?: number } = {}) {
  const top = Object.values(chrome).reduce((sum, value) => sum + value, 0);
  const cardWidth = (viewportWidth - PAGE_GUTTER_PX * 2 - GRID_GAP_PX * (columns - 1)) / columns;
  const previewBottom = top + cardWidth;
  const titleBottom = previewBottom + CARD_TITLE_PX;
  const visibleLimit = viewportHeight - TAB_BAR_REM * 16;
  return { top, cardWidth, previewBottom, titleBottom, visibleLimit, visible: titleBottom <= visibleLimit };
}
