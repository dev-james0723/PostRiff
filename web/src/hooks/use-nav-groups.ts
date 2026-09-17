'use client';

import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'postriff-nav-groups';

/** Labels the person folded away; everything else is open. Empty when storage is unavailable. */
function readClosed(): Record<string, boolean> {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function writeClosed(closed: Record<string, boolean>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(closed));
  } catch {
    /* a per-browser convenience; losing it costs nothing */
  }
}

/**
 * Open/closed state of the sidebar's nav groups, remembered per browser. Groups default to
 * open, and the group holding the active route is opened whenever the route lands in it.
 * The sidebar mounts client-side after the session resolves, so reading storage in the
 * initializer never disagrees with server markup.
 */
export function useNavGroups(activeLabel: string | null) {
  const [closed, setClosed] = useState<Record<string, boolean>>(() =>
    typeof window === 'undefined' ? {} : readClosed()
  );

  useEffect(() => {
    if (!activeLabel || !closed[activeLabel]) return;
    const next = { ...closed, [activeLabel]: false };
    writeClosed(next);
    setClosed(next);
  }, [activeLabel, closed]);

  const isOpen = useCallback((label: string) => !closed[label], [closed]);

  const setOpen = useCallback((label: string, open: boolean) => {
    setClosed((prev) => {
      const next = { ...prev, [label]: !open };
      writeClosed(next);
      return next;
    });
  }, []);

  return { isOpen, setOpen };
}
