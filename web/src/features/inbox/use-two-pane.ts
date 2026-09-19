'use client';

import { useSyncExternalStore } from 'react';

/** Tailwind's `lg`. `useIsMobile` breaks at 768px, which is too narrow for a list beside a reply composer. */
const QUERY = '(min-width: 1024px)';

function subscribe(onChange: () => void) {
  const query = window.matchMedia(QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/** True when the list and the open comment sit side by side; below it the comment opens in a sheet. */
export function useTwoPane() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => true
  );
}
