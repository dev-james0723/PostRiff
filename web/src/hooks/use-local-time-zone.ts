'use client';

import { useSyncExternalStore } from 'react';
import { getLocalTimeZone } from '@internationalized/date';

const subscribeToNothing = () => () => {};

/**
 * This browser's IANA time zone, or `null` on the server and while hydrating, so nothing zone-dependent is
 * rendered into HTML that the client would then disagree with.
 */
export function useLocalTimeZone() {
  return useSyncExternalStore(subscribeToNothing, getLocalTimeZone, () => null);
}
