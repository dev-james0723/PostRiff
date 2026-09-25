import { formatDate, relativeTime } from '@/lib/time';

/**
 * "Expires in 4 days" from a proposal's own `expiresAt`, with the exact date for a tooltip; null when the API
 * gave no expiry. Past the date but still listed as waiting means the expiry sweep has not run yet.
 */
export function expiryLabel(expiresAt: number | null | undefined, now = Date.now() / 1000): { text: string; exact: string } | null {
  if (!expiresAt) return null;
  if (expiresAt <= now) return { text: 'Expiring', exact: formatDate(expiresAt) };
  return { text: `Expires ${relativeTime(expiresAt, now)}`, exact: formatDate(expiresAt) };
}
