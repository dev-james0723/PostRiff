'use client';

/**
 * An inline form that opens in place (a reason picker, an edit row, a picker inside a dialog): when it opens, focus moves
 * to its first field, and Escape anywhere inside it cancels (not while an input method is still composing). Listening on
 * the form element itself keeps the keyboard path without putting key handlers on a non-interactive element or using
 * `autoFocus`.
 *
 * Optional, for forms that replace or sit under the control that opened them:
 * - `returnFocus`: when the form closes (or unmounts while open), focus goes back to this element (a ref or a getter,
 *   read at close time) if focus was inside the form or fell back to the page or the dialog around it, so a keyboard
 *   user is never dropped at the top of a dialog. Focus the person already moved elsewhere is left alone.
 * - `containEscape`: Escape cancels only this form, not a dialog or popover around it.
 */
import { useEffect, useRef, type RefObject } from 'react';

export type FocusTarget = RefObject<HTMLElement | null> | (() => HTMLElement | null | undefined);

export interface InlineFormOptions {
  returnFocus?: FocusTarget;
  containEscape?: boolean;
}

function resolve(target: FocusTarget | undefined): HTMLElement | null {
  if (!target) return null;
  return (typeof target === 'function' ? target() : target.current) ?? null;
}

/** Whether closing should hand focus back: focus is gone, on the page, inside the closed form, or on a container of the target. */
export function shouldReturnFocus(active: Element | null, form: Element | null, target: Element, body: Element | null): boolean {
  if (!active || active === body || !active.isConnected) return true;
  if (form && form.contains(active)) return true;
  return active !== target && active.contains(target);
}

export function useInlineForm<F extends HTMLElement>(open: boolean, onCancel: () => void, options: InlineFormOptions = {}) {
  const formRef = useRef<HTMLFormElement>(null);
  const firstRef = useRef<F>(null);
  const cancel = useRef(onCancel);
  const back = useRef(options.returnFocus);
  const contain = useRef(Boolean(options.containEscape));
  useEffect(() => {
    cancel.current = onCancel;
  }, [onCancel]);
  useEffect(() => {
    back.current = options.returnFocus;
    contain.current = Boolean(options.containEscape);
  }, [options.returnFocus, options.containEscape]);
  useEffect(() => {
    if (open) firstRef.current?.focus();
  }, [open]);
  useEffect(() => {
    const form = formRef.current;
    if (!open || !form) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.isComposing) return;
      if (contain.current) event.stopPropagation();
      cancel.current();
    };
    form.addEventListener('keydown', onKey);
    return () => form.removeEventListener('keydown', onKey);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const form = formRef.current;
    return () => {
      const target = resolve(back.current);
      if (!target || !target.isConnected) return;
      if (shouldReturnFocus(document.activeElement, form, target, document.body)) target.focus();
    };
  }, [open]);
  return { formRef, firstRef };
}
