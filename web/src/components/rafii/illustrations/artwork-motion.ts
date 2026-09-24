'use client';

/**
 * Decorative artwork only breathes while it can be seen (DNA v8 §14.5, §18.6): one shared
 * IntersectionObserver marks each illustration visible or not, the document's visibility state pauses
 * everything in a background tab, and the caller's `enabled` flag carries the person's own pause.
 * Reduced motion is handled in CSS through `.rafii-decorative-motion` (styles/rafii.css).
 */
import { useEffect, useState, useSyncExternalStore, type RefObject } from 'react';

let observer: IntersectionObserver | null = null;
const listeners = new WeakMap<Element, (visible: boolean) => void>();

function sharedObserver(): IntersectionObserver | null {
  if (observer) return observer;
  if (typeof IntersectionObserver === 'undefined') return null;
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) listeners.get(entry.target)?.(entry.isIntersecting);
    },
    { threshold: 0.05 }
  );
  return observer;
}

/** Reports whether `element` is on screen; without IntersectionObserver it counts as visible. */
export function observeVisibility(element: Element, onChange: (visible: boolean) => void): () => void {
  const io = sharedObserver();
  if (!io) {
    onChange(true);
    return () => {};
  }
  listeners.set(element, onChange);
  io.observe(element);
  return () => {
    listeners.delete(element);
    io.unobserve(element);
  };
}

function subscribeHidden(callback: () => void) {
  document.addEventListener('visibilitychange', callback);
  return () => document.removeEventListener('visibilitychange', callback);
}

export function useDocumentHidden(): boolean {
  return useSyncExternalStore(
    subscribeHidden,
    () => document.hidden,
    () => false
  );
}

/** True while the artwork should run its loops: enabled by the person, on screen, and in a visible tab. */
export function useArtworkPlaying(ref: RefObject<Element | null>, enabled: boolean): boolean {
  const [visible, setVisible] = useState(false);
  const hidden = useDocumentHidden();
  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;
    return observeVisibility(element, setVisible);
  }, [ref, enabled]);
  return enabled && visible && !hidden;
}
