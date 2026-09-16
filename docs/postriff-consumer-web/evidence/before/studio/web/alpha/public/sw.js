/* PostRiff service worker.
   - Shell (index.html, manifest): network-first, cache fallback → offline still opens the app,
     but a fresh deploy is never masked by a stale shell.
   - Hashed /assets/*: cache-first (immutable by name).
   - /api: only the idempotent workspace snapshot GET is cached (stale-while-revalidate) for
     safe offline viewing of recently loaded drafts. No mutations, auth, tokens or media bytes. */
const SHELL = 'postriff-shell-v2';
const ASSETS = 'postriff-assets-v2';
const DATA = 'postriff-recent-v2';
self.addEventListener('install', (event) => { event.waitUntil(self.skipWaiting()); });
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, ASSETS, DATA].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    if (!/^\/api\/workspaces\/[0-9a-f-]+$/.test(url.pathname)) return;
    event.respondWith(fetch(req).then((res) => { if (res.ok) caches.open(DATA).then((c) => c.put(req, res.clone())); return res; }).catch(() => caches.match(req)));
    return;
  }
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => { if (res.ok) caches.open(ASSETS).then((c) => c.put(req, res.clone())); return res; })));
    return;
  }
  // Shell and everything else: network first.
  event.respondWith(fetch(req).then((res) => { if (res.ok) caches.open(SHELL).then((c) => c.put(req, res.clone())); return res; }).catch(() => caches.match(req).then((hit) => hit || caches.match('/'))));
});
self.addEventListener('push', (event) => {
  // Notifications only open a resource; they never execute an action.
  const data = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || 'PostRiff', { body: data.body || '', data: { url: data.url || '/' } }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow(event.notification.data?.url || '/'));
});
