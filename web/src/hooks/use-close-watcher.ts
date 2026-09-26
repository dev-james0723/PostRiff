'use client';

import { useEffect, useRef } from 'react';

interface CloseWatcherLike {
  addEventListener(event: 'close', listener: () => void): void;
  destroy(): void;
}

type CloseWatcherCtor = new () => CloseWatcherLike;

/**
 * Lets the Android back gesture (and Esc) close an open sheet or list instead of leaving the page (chat-context
 * SPEC §4.9). Uses `CloseWatcher` where the browser has it and does nothing elsewhere; the component keeps its own
 * Esc handling for those browsers.
 */
export function watchClose(
  onClose: () => void,
  Ctor: CloseWatcherCtor | undefined
): (() => void) | null {
  if (!Ctor) return null;
  let watcher: CloseWatcherLike;
  try {
    watcher = new Ctor();
  } catch {
    return null; // e.g. created without user activation too many times
  }
  watcher.addEventListener('close', onClose);
  return () => watcher.destroy();
}

export function useCloseWatcher(open: boolean, onClose: () => void) {
  const latest = useRef(onClose);
  useEffect(() => {
    latest.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!open || typeof window === 'undefined') return;
    const Ctor = (window as unknown as { CloseWatcher?: CloseWatcherCtor }).CloseWatcher;
    return watchClose(() => latest.current(), Ctor) ?? undefined;
  }, [open]);
}
