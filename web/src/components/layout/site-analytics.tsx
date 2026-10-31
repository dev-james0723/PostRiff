'use client';

import { Analytics } from '@vercel/analytics/next';
import { usePathname } from 'next/navigation';
import { dropPlayPageview, isPlayPath } from '@/lib/play-path';

/**
 * Vercel Web Analytics for every route except the children's /play area (decision D1 = exclude). On /play the
 * component is not rendered, so a direct visit never loads the script; `beforeSend` also drops /play page views if
 * the script was already loaded on another route before a client-side visit to /play.
 */
export function SiteAnalytics() {
  const pathname = usePathname();
  if (isPlayPath(pathname)) return null;
  return <Analytics beforeSend={dropPlayPageview} />;
}
