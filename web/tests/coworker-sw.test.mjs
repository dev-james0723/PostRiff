/**
 * The Rafii service worker (web/public/sw.js) run in a sandbox with a fake `self`: push shows only a well-formed
 * payload, malformed payloads are ignored without throwing, notification clicks follow only same-origin `/app`
 * links (focusing an open window first), and nothing is cached or intercepted.
 *
 *   node --test web/tests/coworker-sw.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(here, '../public/sw.js'), 'utf8');
const ORIGIN = 'https://rafii.example';

function load({ windows = [], subscribe } = {}) {
  const listeners = {};
  const shown = [];
  const opened = [];
  const subscribed = [];
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, fn) => {
      listeners[type] = fn;
    },
    skipWaiting: () => undefined,
    registration: {
      showNotification: async (title, options) => {
        shown.push({ title, options });
      },
      pushManager: {
        subscribe: subscribe ?? (async (options) => {
          subscribed.push(options);
          return {};
        })
      }
    },
    clients: {
      claim: async () => undefined,
      matchAll: async () => windows,
      openWindow: async (url) => {
        opened.push(url);
        return { url };
      }
    }
  };
  const context = vm.createContext({ self, URL, console });
  vm.runInContext(SOURCE, context, { filename: 'sw.js' });
  return { listeners, shown, opened, subscribed, context };
}

/** Dispatch like the browser: collect waitUntil promises and settle them. */
async function dispatch(listener, event) {
  const waits = [];
  const full = { ...event, waitUntil: (p) => waits.push(p) };
  listener(full);
  await Promise.all(waits);
  return waits.length;
}

const pushEvent = (payload) => ({ data: { json: () => payload } });

function windowClient(url, { navigate } = {}) {
  const calls = { focus: 0, navigate: [] };
  const client = {
    url,
    focus: async () => {
      calls.focus += 1;
      return client;
    },
    navigate:
      navigate ??
      (async (to) => {
        calls.navigate.push(to);
        return client;
      }),
    postMessage: () => undefined
  };
  return { client, calls };
}

test('registers push, notificationclick and pushsubscriptionchange; no fetch handler, so nothing is cached or intercepted', () => {
  const { listeners } = load();
  assert.equal(typeof listeners.push, 'function');
  assert.equal(typeof listeners.notificationclick, 'function');
  assert.equal(typeof listeners.pushsubscriptionchange, 'function');
  assert.equal(listeners.fetch, undefined);
  assert.doesNotMatch(SOURCE, /caches\.|addEventListener\(['"]fetch/);
});

test('push shows the minimal payload with the Rafii icon, the tag and a same-origin deep link', async () => {
  const { listeners, shown } = load();
  await dispatch(listeners.push, pushEvent({ title: 'Next week is ready', body: '5 posts to review', url: '/app/weekly?week=wk_1', tag: 'week_ready:wk_1', category: 'weekly' }));
  assert.equal(shown.length, 1);
  assert.equal(shown[0].title, 'Next week is ready');
  assert.equal(shown[0].options.body, '5 posts to review');
  assert.equal(shown[0].options.tag, 'week_ready:wk_1');
  assert.equal(shown[0].options.icon, '/raffi/avatar-128.png');
  assert.equal(shown[0].options.data.url, '/app/weekly?week=wk_1');
  assert.equal(shown[0].options.data.category, 'weekly');
});

for (const [name, url] of [
  ['an absolute external URL', 'https://evil.example/app'],
  ['a protocol-relative URL', '//evil.example/app'],
  ['a javascript: URL', 'javascript:alert(1)'],
  ['a path outside the app', '/auth/sign-in'],
  ['a look-alike prefix', '/application'],
  ['a dot-segment escape', '/app/../auth/sign-in'],
  ['a backslash trick', '/app\\@evil.example'],
  ['a non-string', 42]
]) {
  test(`push with ${name} links to /app instead`, async () => {
    const { listeners, shown } = load();
    await dispatch(listeners.push, pushEvent({ title: 'Rafii', body: 'x', url }));
    assert.equal(shown[0].options.data.url, '/app');
  });
}

for (const [name, event] of [
  ['JSON that fails to parse', { data: { json: () => { throw new SyntaxError('bad json'); } } }],
  ['no data at all', { data: null }],
  ['an array', pushEvent(['Rafii'])],
  ['a string', pushEvent('Rafii')],
  ['no title', pushEvent({ body: 'Only a body', url: '/app' })],
  ['a blank title', pushEvent({ title: '   ', url: '/app' })]
]) {
  test(`a malformed push (${name}) is ignored without throwing`, async () => {
    const { listeners, shown } = load();
    const waits = await dispatch(listeners.push, event);
    assert.equal(shown.length, 0);
    assert.equal(waits, 0);
  });
}

test('long text is trimmed to lock-screen size', async () => {
  const { listeners, shown } = load();
  await dispatch(listeners.push, pushEvent({ title: 'T'.repeat(200), body: 'B'.repeat(500), url: '/app' }));
  assert.equal(shown[0].title.length, 80);
  assert.equal(shown[0].options.body.length, 160);
});

test('click focuses a window already on the link', async () => {
  const exact = windowClient(`${ORIGIN}/app/weekly?week=wk_1`);
  const { listeners, opened } = load({ windows: [exact.client] });
  let closed = 0;
  await dispatch(listeners.notificationclick, { notification: { data: { url: '/app/weekly?week=wk_1' }, close: () => (closed += 1) } });
  assert.equal(closed, 1);
  assert.equal(exact.calls.focus, 1);
  assert.deepEqual(exact.calls.navigate, []);
  assert.deepEqual(opened, []);
});

test('click moves an open Rafii window to the link and focuses it', async () => {
  const open = windowClient(`${ORIGIN}/app/queue`);
  const { listeners, opened } = load({ windows: [open.client] });
  await dispatch(listeners.notificationclick, { notification: { data: { url: '/app/weekly' }, close: () => undefined } });
  assert.deepEqual(open.calls.navigate, [`${ORIGIN}/app/weekly`]);
  assert.equal(open.calls.focus, 1);
  assert.deepEqual(opened, []);
});

test('click opens a new window when no Rafii window is open (other origins are ignored)', async () => {
  const foreign = windowClient('https://elsewhere.example/app/weekly');
  const { listeners, opened } = load({ windows: [foreign.client] });
  await dispatch(listeners.notificationclick, { notification: { data: { url: '/app/weekly' }, close: () => undefined } });
  assert.equal(foreign.calls.focus, 0);
  assert.deepEqual(opened, [`${ORIGIN}/app/weekly`]);
});

test('click with an external link opens /app, never the external site', async () => {
  const { listeners, opened } = load();
  await dispatch(listeners.notificationclick, { notification: { data: { url: 'https://evil.example/phish' }, close: () => undefined } });
  assert.deepEqual(opened, [`${ORIGIN}/app`]);
});

test('click without data opens /app', async () => {
  const { listeners, opened } = load();
  await dispatch(listeners.notificationclick, { notification: { close: () => undefined } });
  assert.deepEqual(opened, [`${ORIGIN}/app`]);
});

test('a window that cannot be navigated falls back to opening the link', async () => {
  const stuck = windowClient(`${ORIGIN}/app`, { navigate: async () => { throw new TypeError('not controlled'); } });
  const { listeners, opened } = load({ windows: [stuck.client] });
  await dispatch(listeners.notificationclick, { notification: { data: { url: '/app/inbox' }, close: () => undefined } });
  assert.deepEqual(opened, [`${ORIGIN}/app/inbox`]);
});

test('pushsubscriptionchange re-subscribes with the old key and tells open windows', async () => {
  const messages = [];
  const page = { url: `${ORIGIN}/app`, postMessage: (m) => messages.push(m) };
  const { listeners, subscribed } = load({ windows: [page] });
  const key = new Uint8Array([4, 1, 2]).buffer;
  await dispatch(listeners.pushsubscriptionchange, { oldSubscription: { options: { applicationServerKey: key } }, newSubscription: null });
  assert.equal(subscribed.length, 1);
  assert.equal(subscribed[0].userVisibleOnly, true);
  assert.equal(subscribed[0].applicationServerKey, key);
  assert.deepEqual(JSON.parse(JSON.stringify(messages)), [{ type: 'rafii:push-subscription-changed' }]);
});

test('pushsubscriptionchange never throws, even when re-subscribing fails', async () => {
  const { listeners } = load({ subscribe: async () => { throw new Error('push service down'); } });
  await assert.doesNotReject(dispatch(listeners.pushsubscriptionchange, { oldSubscription: { options: { applicationServerKey: new ArrayBuffer(65) } } }));
  await assert.doesNotReject(dispatch(listeners.pushsubscriptionchange, {}));
});
