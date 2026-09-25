/**
 * Button recipes shared by the Usage & plan page. Lifecycle states (trial ended, payment failed,
 * ending, ended) are no longer a separate alert: the plan summary at the top of the page carries
 * them with its one action, so the same date is never said twice.
 */

/** The glass recipe on a secondary motion button (DNA §10.2). */
export const GLASS_STATEFUL =
  'rafii-glass hover:rafii-glass-selected h-12 rounded-[var(--rafii-radius-control)] border-0 bg-transparent px-4 text-sm hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent';
/** The inverted primary on a motion button (DNA §10.1). */
export const ACTION_STATEFUL = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-4 text-sm hover:brightness-[1.06]';
