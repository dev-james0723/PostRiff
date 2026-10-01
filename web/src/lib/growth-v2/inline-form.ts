'use client';

/**
 * An inline form that opens in place (a reason picker, an edit row): when it opens, focus moves to its first field, and
 * Escape anywhere inside it cancels. Listening on the form element itself keeps the keyboard path without putting key
 * handlers on a non-interactive element or using `autoFocus`.
 */
import { useEffect, useRef } from 'react';

export function useInlineForm<F extends HTMLElement>(open: boolean, onCancel: () => void) {
  const formRef = useRef<HTMLFormElement>(null);
  const firstRef = useRef<F>(null);
  const cancel = useRef(onCancel);
  useEffect(() => {
    cancel.current = onCancel;
  }, [onCancel]);
  useEffect(() => {
    if (open) firstRef.current?.focus();
  }, [open]);
  useEffect(() => {
    const form = formRef.current;
    if (!open || !form) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') cancel.current();
    };
    form.addEventListener('keydown', onKey);
    return () => form.removeEventListener('keydown', onKey);
  }, [open]);
  return { formRef, firstRef };
}
