'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';

const QUERY = '(min-width: 768px)';

function subscribe(onChange: () => void) {
  const query = window.matchMedia(QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/**
 * True at the `md` breakpoint and up: the receipt opens as a side sheet; below it, a bottom drawer.
 * The server (and hydration) assume the wide layout.
 */
export function useWide() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => true
  );
}

/**
 * The width the jobs list actually has. The sidebar takes a different share of the page at every viewport, so the
 * table-or-cards choice reads the list's own width rather than the window's. Null until the first measurement.
 */
export function useElementWidth<T extends HTMLElement>() {
  const [width, setWidth] = useState<number | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((node: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node) return;
    setWidth(node.getBoundingClientRect().width);
    observer.current = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.current.observe(node);
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, width] as const;
}
