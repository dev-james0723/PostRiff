/**
 * Deep links that arrive from the server (notification payloads, attention items, push data) are data, not
 * trusted navigation. Only a same-origin relative path inside the signed-in app (`/app`, `/app/…`, `/app?…`,
 * `/app#…`) is followed; anything else falls back to `/app`. The service worker (`public/sw.js`) applies the
 * same rule; both are tested in `web/tests/coworker-deeplink.test.mjs`.
 *
 * No imports: node's test runner loads this file directly.
 */

export const APP_FALLBACK = '/app';
const APP_PATH = /^\/app(?:[/?#]|$)/;
/** Backslashes (some browsers read `\` as `/`), whitespace and control characters never appear in our links. */
function hasUnsafeCharacter(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code <= 0x20 || code === 0x7f || code === 0x5c || code === 0xa0 || code === 0x2028 || code === 0x2029) return true;
  }
  return false;
}

export function safeAppHref(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > 500) return APP_FALLBACK;
  if (!APP_PATH.test(value) || hasUnsafeCharacter(value)) return APP_FALLBACK;
  try {
    const base = 'https://rafii.invalid';
    const url = new URL(value, base);
    if (url.origin !== base || !APP_PATH.test(url.pathname + (url.search || '') + (url.hash || ''))) return APP_FALLBACK;
    // `/app/../x` normalises outside the app: refuse it.
    if (!(url.pathname === '/app' || url.pathname.startsWith('/app/'))) return APP_FALLBACK;
    return url.pathname + url.search + url.hash;
  } catch {
    return APP_FALLBACK;
  }
}

/** The Queue's drafts view, focused on one draft when its id is known. */
export function queueDraftHref(variantId: string | null | undefined): string {
  return variantId ? `/app/queue?view=drafts&draft=${encodeURIComponent(variantId)}` : '/app/queue?view=drafts';
}
