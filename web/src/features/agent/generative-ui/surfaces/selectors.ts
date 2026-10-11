/**
 * DOM markers of generated views (lane F). The page outline never reads generated text back into the next turn's page context,
 * and Escape inside a generated dialog or the native action confirmation closes that layer, not the whole Rafii panel.
 */
/** C's generated frame (carries data-artifact-id and data-generation-state). */
export const GENERATED_SELECTOR = '[data-rafii-generated]';
/** C's message wrapper (native answer slot, frame, confirmation, status line). */
export const GENERATED_MESSAGE_SELECTOR = '[data-rafii-genui-message]';
/** F's host wrapper on every surface (native controls around C's frame). */
export const GENERATED_HOST_ATTR = 'data-rafii-generated-host';
export const GENERATED_HOST_SELECTOR = '[data-rafii-generated-host]';
/** The expanded full-height dialog of a generated view. */
export const GENERATED_DIALOG_ATTR = 'data-rafii-generated-dialog';
export const GENERATED_DIALOG_SELECTOR = '[data-rafii-generated-dialog]';
/** C's native confirmation sheet for generated actions (a base-ui portal outside the generated subtree). */
export const UI_CONFIRMATION_SELECTORS = ['[data-rafii-genui-confirmation]'];
/** Layers whose own Escape handling wins over "Escape closes Rafii". */
export const ESCAPE_SKIP_SELECTORS = [GENERATED_DIALOG_SELECTOR, ...UI_CONFIRMATION_SELECTORS];
/** Rafii-owned surfaces the page outline skips (kept in step with use-page-context OWN_SURFACES). */
export const OUTLINE_SKIP_SELECTORS = [GENERATED_SELECTOR, GENERATED_MESSAGE_SELECTOR, GENERATED_HOST_SELECTOR, GENERATED_DIALOG_SELECTOR, ...UI_CONFIRMATION_SELECTORS];
