import { formatDate, relativeTime } from '@/lib/time';

/**
 * "Expires in 4 days · 20 Sep 2026" from a proposal's own `expiresAt`; null when the API gave no expiry.
 * Past the date but still listed as waiting means the expiry sweep has not run yet, so it says that instead.
 */
export function expiryLabel(expiresAt: number | null | undefined, now = Date.now() / 1000) {
  if (!expiresAt) return null;
  if (expiresAt <= now) return 'Past its expiry date; it closes on the next check';
  return `Expires ${relativeTime(expiresAt, now)} · ${formatDate(expiresAt)}`;
}
