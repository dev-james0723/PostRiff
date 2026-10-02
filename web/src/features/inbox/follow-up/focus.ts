'use client';

/**
 * Keyboard focus for the follow-up's inline panels (an edit form, the snooze choices, the "won" picker, start or link a
 * follow-up). The panel is mounted only while open: `usePanelFocus` moves focus to its first field when it mounts and
 * lets Escape anywhere inside it cancel; `useReturnFocus`, in the component that owns the panel, puts focus back on the
 * control that opened it when the panel closes (save or cancel), unless focus already went somewhere on purpose. The
 * Escape listener sits on the panel element itself, so no key handler lands on a non-interactive element and no
 * `autoFocus` is needed.
 */
import { useEffect, useRef, type RefObject } from 'react';

const FIELDS = 'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href]';

export function usePanelFocus<P extends HTMLElement>(onCancel: () => void) {
  const panelRef = useRef<P>(null);
  const cancel = useRef(onCancel);
  useEffect(() => {
    cancel.current = onCancel;
  }, [onCancel]);
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    panel.querySelector<HTMLElement>(FIELDS)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation(); // the panel closes, not the sheet or dialog around it
      cancel.current();
    };
    panel.addEventListener('keydown', onKey);
    return () => panel.removeEventListener('keydown', onKey);
  }, []);
  return panelRef;
}

/** `fallback` takes focus when the opener is gone after the change (e.g. the stage control of a follow-up just won). */
export function useReturnFocus(open: boolean, returnTo: RefObject<HTMLElement | null>, fallback?: RefObject<HTMLElement | null>) {
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open && typeof document !== 'undefined') {
      const active = document.activeElement;
      // Focus left with the panel (it sits on the body now): give it back to the opener.
      if (!active || active === document.body) {
        const target = returnTo.current?.isConnected ? returnTo.current : fallback?.current;
        target?.focus();
      }
    }
    wasOpen.current = open;
  }, [open, returnTo, fallback]);
}
