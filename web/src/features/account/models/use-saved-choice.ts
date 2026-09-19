'use client';

import { useEffect, useState } from 'react';

/** Wall-clock seconds that re-render every `intervalMs`, for "received 2 minutes ago" lines. */
export function useNowSeconds(intervalMs = 15_000) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
