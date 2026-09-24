/**
 * Rafii chrome for the forms, dialogs and menus of the account / auth / system family
 * (Design DNA §5.2 materials, §11.1 fields, §12.2 dialogs). These are class recipes over the
 * shared utilities in `styles/rafii.css`, kept in one place until `components/rafii` grows an
 * input and dialog helper; every consumer imports them so one change moves the whole family.
 *
 * Explicit `bg-*` values are passed so tailwind-merge drops the template's `bg-transparent` /
 * `dark:bg-input/30` colours instead of letting them paint over the material.
 */

/** A 48px borderless text field (§11.1): field fill, control radius, 16px on phones. */
export const rafiiInput =
  'rafii-field h-12 rounded-[var(--rafii-radius-control)] border-0 bg-[var(--rafii-surface-field,var(--input))] px-3.5 text-base focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/60 md:text-sm dark:bg-[var(--rafii-surface-field,var(--input))]';

/** The same field material on a Select trigger; the shared chevron stays. */
export const rafiiSelectTrigger =
  'rafii-field h-12 w-full rounded-[var(--rafii-radius-control)] border-0 bg-[var(--rafii-surface-field,var(--input))] pr-3 pl-3.5 text-base focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/60 data-[size=default]:h-12 md:text-sm dark:bg-[var(--rafii-surface-field,var(--input))] dark:hover:bg-[var(--rafii-surface-field,var(--input))]';

/** Elevated glass on a Dialog / AlertDialog popup (§12.2): the phone radius, then the dialog radius. */
export const rafiiDialog =
  'rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] bg-transparent p-5 ring-0 md:rounded-[var(--rafii-radius-dialog)]';

/** A dialog footer without the template's band: spacing separates it from the body. */
export const rafiiDialogFooter = '-mx-5 -mb-5 rounded-none border-0 bg-transparent px-5 pt-1 pb-5';

/** Elevated glass on a Popover / DropdownMenu popup (§5.4 blur roles). */
export const rafiiMenu = 'rafii-elevated rounded-2xl bg-transparent shadow-[var(--rafii-shadow-dialog)] ring-0';

/** A quiet glass icon well beside a title or list row (§14.3). */
export const rafiiIconWell = 'rafii-glass text-foreground flex size-9 shrink-0 items-center justify-center rounded-full';

/** A native checkbox that reads as a Rafii control (§10.6) and keeps a 44px hit area through its label. */
export const rafiiCheckbox = 'accent-foreground size-4 shrink-0 cursor-pointer';

/** The field material on an InputGroup wrapper (Combobox): the inner control keeps its own padding. */
export const rafiiInputGroup =
  'rafii-field h-12 rounded-[var(--rafii-radius-control)] border-0 bg-[var(--rafii-surface-field,var(--input))] pl-1 has-[[data-slot=input-group-control]:focus-visible]:border-transparent has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-ring/60 dark:bg-[var(--rafii-surface-field,var(--input))]';
