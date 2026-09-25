/**
 * Sign-out drops this browser's push subscription (src/lib/coworker/push-signout.ts), so a shared browser stops
 * receiving the signed-out person's notifications. It must never register the service worker, throw, or hang.
 *
 *   node --test web/tests/push-signout.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { forgetPushOnSignOut } from '../src/lib/coworker/push-signout.ts';

function withBrowser(serviceWorker, run) {
  const saved = { window: globalThis.window, navigator: Object.getOwnPropertyDescriptor(globalThis, 'navigator') };
  globalThis.window = {};
  Object.defineProperty(globalThis, 'navigator', { value: serviceWorker ? { serviceWorker } : {}, configurable: true });
  return run().finally(() => {
    globalThis.window = saved.window;
    if (saved.navigator) Object.defineProperty(globalThis, 'navigator', saved.navigator);
    else delete globalThis.navigator;
  });
}

test('unsubscribes the existing subscription and never registers the worker', async () => {
  const calls = [];
  const subscription = { unsubscribe: async () => (calls.push('unsubscribe'), true) };
  const serviceWorker = {
    register: () => calls.push('register'),
    getRegistration: async (scope) => (calls.push(`getRegistration ${scope}`), { pushManager: { getSubscription: async () => subscription } })
  };
  await withBrowser(serviceWorker, async () => assert.equal(await forgetPushOnSignOut(), true));
  assert.deepEqual(calls, ['getRegistration /', 'unsubscribe']);
});

test('nothing to do without a worker, a registration or a subscription', async () => {
  await withBrowser(null, async () => assert.equal(await forgetPushOnSignOut(), false));
  await withBrowser({ getRegistration: async () => undefined }, async () => assert.equal(await forgetPushOnSignOut(), false));
  await withBrowser({ getRegistration: async () => ({ pushManager: { getSubscription: async () => null } }) }, async () => assert.equal(await forgetPushOnSignOut(), false));
});

test('an error or a browser that never answers does not block sign-out', async () => {
  await withBrowser({ getRegistration: async () => { throw new Error('denied'); } }, async () => assert.equal(await forgetPushOnSignOut(), false));
  const started = Date.now();
  await withBrowser({ getRegistration: () => new Promise(() => {}) }, async () => assert.equal(await forgetPushOnSignOut(20), false));
  assert.ok(Date.now() - started < 1000);
});

test('on the server it does nothing', async () => {
  assert.equal(typeof globalThis.window, 'undefined');
  assert.equal(await forgetPushOnSignOut(), false);
});
