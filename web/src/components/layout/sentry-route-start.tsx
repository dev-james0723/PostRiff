'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';
import { ensureSentryForPath } from '@/lib/sentry-client';

/**
 * Starts browser Sentry on every committed non-play route (D11). A visit that begins on /play has no Sentry until the
 * child reaches a normal page; this effect runs once React has committed that route, so there is no timing guess.
 */
export function SentryRouteStart() {
  const pathname = usePathname();
  useEffect(() => {
    void ensureSentryForPath(pathname);
  }, [pathname]);
  return null;
}
