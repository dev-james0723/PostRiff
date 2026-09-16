'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Keeps a button's outcome ("success", "error") on screen for a moment, then lets it
 * return to idle. A new flash replaces the previous one and restarts the timer.
 */
export function useFlash<T>(duration = 1800) {
  const [value, setValue] = useState<T | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  const flash = useCallback(
    (next: T) => {
      if (timer.current) clearTimeout(timer.current);
      setValue(next);
      timer.current = setTimeout(() => setValue(null), duration);
    },
    [duration]
  );
  return [value, flash] as const;
}
