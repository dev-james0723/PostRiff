/**
 * DOM markers of generated views (lane F). The page outline never reads generated text back into the next turn's page context,
 * and Escape inside a generated dialog or the native action confirmation closes that layer, not the whole Rafii panel.
 */
export const GENERATED_ATTR = 'data-rafii-generated';
export const GENERATED_SELECTOR = '[data-rafii-generated]';
/** The expanded full-height dialog of a generated view. */
export const GENERATED_DIALOG_ATTR = 'data-rafii-generated-dialog';
export const GENERATED_DIALOG_SELECTOR = '[data-rafii-generated-dialog]';
/** C's native confirmation sheet for generated actions (outside the generated subtree; lane C names the attribute). */
export const UI_CONFIRMATION_SELECTORS = ['[data-rafii-ui-confirmation]', '[data-rafii-action-confirmation]'];
/** Layers whose own Escape handling wins over "Escape closes Rafii". */
export const ESCAPE_SKIP_SELECTORS = [GENERATED_DIALOG_SELECTOR, ...UI_CONFIRMATION_SELECTORS];
/** Rafii-owned surfaces the page outline skips (added to use-page-context OWN_SURFACES). */
export const OUTLINE_SKIP_SELECTORS = [GENERATED_SELECTOR, GENERATED_DIALOG_SELECTOR, ...UI_CONFIRMATION_SELECTORS];
