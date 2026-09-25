/*
 * Rafii service worker: Web Push only (coworker spec §18).
 *
 * - No caching and no `fetch` handler: every request goes to the network exactly as without a worker.
 * - `push` shows the server's minimal payload {title, body, url, tag, category}. A payload that is not that JSON
 *   shape is ignored without throwing; it never becomes a notification with guessed text.
 * - `notificationclick` follows only a same-origin relative link inside the app (`/app…`); anything else opens
 *   `/app`. An open Rafii window is focused (and moved to the link) before a new one is opened.
 * - `pushsubscriptionchange` re-subscribes with the same key when it can and tells open pages, so the settings
 *   page can register the new endpoint with the server. It never throws.
 *
 * The link rule mirrors `src/lib/coworker/safe-href.ts`; `web/tests/coworker-sw.test.mjs` runs this file with a
 * fake `self`.
 */
'use strict';

const RAFII_FALLBACK_URL = '/app';
const RAFII_ICON = '/raffi/avatar-128.png';
const RAFII_APP_PATH = /^\/app(?:[/?#]|$)/;

function rafiiHasUnsafeCharacter(value) {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code <= 0x20 || code === 0x7f || code === 0x5c || code === 0xa0 || code === 0x2028 || code === 0x2029) return true;
  }
  return false;
}

/** Same-origin relative path inside the app, or `/app`. */
function rafiiSafeUrl(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 500) return RAFII_FALLBACK_URL;
  if (!RAFII_APP_PATH.test(value) || rafiiHasUnsafeCharacter(value)) return RAFII_FALLBACK_URL;
  try {
    const origin = self.location.origin;
    const url = new URL(value, origin);
    if (url.origin !== origin) return RAFII_FALLBACK_URL;
    if (!(url.pathname === '/app' || url.pathname.startsWith('/app/'))) return RAFII_FALLBACK_URL;
    return url.pathname + url.search + url.hash;
  } catch {
    return RAFII_FALLBACK_URL;
  }
}

/** The notification to show for a push event, or null when the payload is missing or malformed. */
function rafiiNotificationFromPush(event) {
  if (!event || !event.data || typeof event.data.json !== 'function') return null;
  let data;
  try {
    data = event.data.json();
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  if (typeof data.title !== 'string' || !data.title.trim()) return null;
  const title = data.title.trim().slice(0, 80);
  const body = typeof data.body === 'string' ? data.body.trim().slice(0, 160) : '';
  const tag = typeof data.tag === 'string' && data.tag.trim() ? data.tag.trim().slice(0, 64) : undefined;
  const category = typeof data.category === 'string' ? data.category.slice(0, 40) : '';
  const options = { body, icon: RAFII_ICON, data: { url: rafiiSafeUrl(data.url), category } };
  if (tag) options.tag = tag;
  return { title, options };
}

async function rafiiFocusOrOpen(target) {
  const origin = self.location.origin;
  const absolute = new URL(target, origin).href;
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  const sameOrigin = windows.filter((client) => {
    try {
      return new URL(client.url).origin === origin;
    } catch {
      return false;
    }
  });
  const exact = sameOrigin.find((client) => client.url === absolute);
  if (exact) return exact.focus();
  const existing = sameOrigin[0];
  if (existing) {
    try {
      const moved = typeof existing.navigate === 'function' ? await existing.navigate(absolute) : null;
      return (moved || existing).focus();
    } catch {
      // An uncontrolled window cannot be navigated from here: open the link instead.
    }
  }
  if (self.clients.openWindow) return self.clients.openWindow(absolute);
  return undefined;
}

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  const notification = rafiiNotificationFromPush(event);
  if (!notification) return;
  event.waitUntil(self.registration.showNotification(notification.title, notification.options));
});

self.addEventListener('notificationclick', (event) => {
  const data = (event.notification && event.notification.data) || {};
  if (event.notification) event.notification.close();
  event.waitUntil(rafiiFocusOrOpen(rafiiSafeUrl(data.url)).catch(() => undefined));
});

self.addEventListener('pushsubscriptionchange', (event) => {
  const work = (async () => {
    try {
      const old = event.oldSubscription;
      const key = old && old.options ? old.options.applicationServerKey : null;
      if (key && !event.newSubscription) await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      // Client.postMessage has no target origin: the message goes only to this origin's own windows.
      // oxlint-disable-next-line unicorn/require-post-message-target-origin
      for (const client of windows) client.postMessage({ type: 'rafii:push-subscription-changed' });
    } catch {
      // Best effort: the settings page shows this browser as not subscribed and offers to turn push on again.
    }
  })();
  if (event && typeof event.waitUntil === 'function') event.waitUntil(work);
});
