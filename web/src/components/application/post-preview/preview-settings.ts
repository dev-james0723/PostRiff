'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * Per-viewer preview choices (guides on or off, light or dark), shared by every preview on the page and kept in
 * this browser. Storage can be missing or blocked; the choice then lasts until the page closes.
 */

const PREFIX = 'postriff.preview.';
const listeners = new Set<() => void>();
const memory = new Map<string, string>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function read(key: string) {
  if (memory.has(key)) return memory.get(key) ?? null;
  try {
    const value = localStorage.getItem(PREFIX + key);
    if (value !== null) memory.set(key, value);
    return value;
  } catch {
    return null;
  }
}

export function usePreviewSetting<T extends string>(key: string, fallback: T, allowed: readonly T[]) {
  const stored = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null
  );
  const value = stored !== null && (allowed as readonly string[]).includes(stored) ? (stored as T) : fallback;
  const set = useCallback(
    (next: T) => {
      memory.set(key, next);
      try {
        localStorage.setItem(PREFIX + key, next);
      } catch {
        /* the choice lasts for this page only */
      }
      listeners.forEach((listener) => listener());
    },
    [key]
  );
  return [value, set] as const;
}
