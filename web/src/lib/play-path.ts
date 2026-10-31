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

/**
 * True when a Sentry event or transaction came from /play: its request URL, a transaction name like "GET /play/x", or
 * the span's own http.target (a span outside any request scope, e.g. a cold start's first request).
 */
export function isPlayEvent(event: { request?: { url?: string }; transaction?: string; contexts?: { trace?: { data?: Record<string, unknown> } } }): boolean {
  if (isPlayUrl(event.request?.url)) return true;
  const name = event.transaction?.replace(/^[A-Z]+\s+/, '');
  const target = event.contexts?.trace?.data?.['http.target'];
  return isPlayPath(name) || isPlayUrl(typeof target === 'string' ? target : undefined);
}

/** Files a page loads rather than pages: build assets, optimised images and the site metadata files. */
const ASSET = /^\/(_next\/(static|image)\b|manifest\.webmanifest$|favicon\.ico$|icon\b|apple-icon\b)/;

/**
 * D12: an asset or metadata request made by a /play page (its Referer is /play). Such requests are /play traffic for
 * server telemetry. Page and RSC requests are never matched, so leaving /play still counts as a visit to the next
 * page. Only a same-host Referer counts; a request without a Referer cannot be attributed and is not matched.
 */
export function isPlayAssetRequest(url: string | null | undefined, referer: string | null | undefined): boolean {
  if (!url || !referer || !isPlayUrl(referer)) return false;
  try {
    const request = new URL(url, 'http://local.invalid');
    // Same host only (codex D13-3): another site's /play page is not this game. Host, not full origin, so a TLS proxy
    // that reports the request as http while the browser's Referer is https still matches.
    return request.host === new URL(referer).host && ASSET.test(request.pathname);
  } catch {
    return false;
  }
}
