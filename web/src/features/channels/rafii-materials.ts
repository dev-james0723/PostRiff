/**
 * Rafii materials on primitives that predate the design DNA (Stream F2: Inbox and Channels).
 *
 * beUI's `StatefulButton` (`components/motion/button/base.tsx`) maps its variants onto the plain
 * shadcn set, so the material is added through `className`. Every string below neutralises the
 * variant classes tailwind-merge dedupes against (`bg-*`, `hover:bg-*`, `ring-*`, `shadow-*`),
 * so the Rafii utility wins whatever the stylesheet order. Shared by `features/inbox`.
 */

/** Inverted primary action (DNA §10.1) for `StatefulButton variant='primary'`. */
export const STATEFUL_ACTION = 'rafii-action rounded-[var(--rafii-radius-control)] hover:brightness-[1.06] active:brightness-100';

/** Quiet glass secondary (DNA §10.2) for `StatefulButton variant='outline'`. */
export const STATEFUL_GLASS =
  'rafii-glass hover:rafii-glass-selected rounded-[var(--rafii-radius-control)] text-foreground hover:text-foreground bg-transparent dark:bg-transparent hover:bg-transparent dark:hover:bg-transparent';

/** 48px standard control (DNA §10.1) and the 44px minimum touch target (DNA §23.1). */
export const CONTROL_48 = 'h-12 gap-2 px-4 text-sm';
export const CONTROL_44 = 'h-11 gap-2 px-4 text-sm';

/** Elevated glass on the existing Dialog / AlertDialog content (common brief, step 4). */
export const DIALOG_ELEVATED = 'rafii-elevated ring-0 shadow-(--rafii-shadow-dialog) rounded-[var(--rafii-radius-dialog)] gap-5 p-6';

/** Elevated glass on the existing Sheet content; a bottom sheet keeps the mobile dialog radius. */
export const SHEET_ELEVATED =
  'rafii-elevated shadow-(--rafii-shadow-dialog) gap-0 data-[side=bottom]:rounded-t-[var(--rafii-radius-mobile-dialog)] data-[side=bottom]:border-t-0 data-[side=right]:border-l-0';

/** Elevated glass on hover cards and popovers that explain one value (DNA §12.4). */
export const POPOVER_ELEVATED = 'rafii-elevated ring-0 shadow-(--rafii-shadow-glass) rounded-2xl p-3.5';

/** The footer of a themed Dialog: the primitive's tinted, bordered band becomes plain spacing. */
export const DIALOG_FOOTER_PLAIN = '-mx-6 -mb-6 rounded-b-[var(--rafii-radius-dialog)] border-t-0 bg-transparent px-6 pt-0 pb-6';
