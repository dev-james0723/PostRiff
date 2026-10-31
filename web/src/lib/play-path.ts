/**
 * Decision D1 = exclude: the /play/* routes (children's games) send no analytics or telemetry. One shared test of
 * "is this the play area?" for Vercel Web Analytics and Sentry (client and server). Every other route is unaffected.
 * Pure (no imports) so node's test runner can load it directly (`web/tests/play-telemetry.test.mjs`).
 */

/**
 * True for exactly /play or anything under /play/; false for /player, /playground, /app/play. Case-sensitive and not
 * decoded, like Next's routing: the game renders only at the literal lowercase path (/PLAY/… and /%70lay/… are 404s).
 */
export function isPlayPath(pathname: string | null | undefined): boolean {
  return typeof pathname === 'string' && (pathname === '/play' || pathname.startsWith('/play/'));
}

/** Same test for a full or relative URL (query and hash ignored). */
export function isPlayUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  try {
    return isPlayPath(new URL(url, 'http://local.invalid').pathname);
  } catch {
    return false;
  }
}

/** `beforeSend` for @vercel/analytics: drop page views and events from /play, pass everything else unchanged. */
export function dropPlayPageview<T extends { url: string }>(event: T): T | null {
  return isPlayUrl(event.url) ? null : event;
}

/** True when a Sentry event or transaction came from /play (request URL, or a transaction name like "GET /play/x"). */
export function isPlayEvent(event: { request?: { url?: string }; transaction?: string }): boolean {
  if (isPlayUrl(event.request?.url)) return true;
  const name = event.transaction?.replace(/^[A-Z]+\s+/, '');
  return isPlayPath(name);
}
