'use client';

import { useEffect, useState } from 'react';

/**
 * The same browser key `useModelChoice` stores the default writer under (`features/agent/use-model.ts`).
 * The hook does not say when it fell back from a saved choice, so this page reads the raw value itself
 * to explain the fallback. Read once on mount, like the hook, and updated when this page picks a writer.
 */
const STORAGE_KEY = 'postriff-agent-model';

export function useSavedChoice() {
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => {
    try {
      setSaved(localStorage.getItem(STORAGE_KEY));
    } catch {
      /* private mode: nothing saved */
    }
  }, []);
  return [saved, setSaved] as const;
}

/** Wall-clock seconds that re-render every `intervalMs`, for "received 2 minutes ago" lines. */
export function useNowSeconds(intervalMs = 15_000) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
