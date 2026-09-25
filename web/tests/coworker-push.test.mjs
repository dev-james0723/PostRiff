/**
 * Web Push helpers (src/lib/coworker/push-keys.ts): VAPID key conversion and what the opt-in offers per browser.
 *
 *   node --test web/tests/coworker-push.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isVapidKey, pushSupport, urlBase64ToUint8Array } from '../src/lib/coworker/push-keys.ts';

const here = path.dirname(fileURLToPath(import.meta.url));

/** A real P-256 public key as the server publishes it (uncompressed point, base64url without padding). */
function vapidPublicKey() {
  const { publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const jwk = publicKey.export({ format: 'jwk' });
  const raw = Buffer.concat([Buffer.from([4]), Buffer.from(jwk.x, 'base64url'), Buffer.from(jwk.y, 'base64url')]);
  return { text: raw.toString('base64url'), raw };
}

test('converts a VAPID public key to the 65 bytes PushManager.subscribe needs', () => {
  const { text, raw } = vapidPublicKey();
  const bytes = urlBase64ToUint8Array(text);
  assert.ok(bytes instanceof Uint8Array);
  assert.equal(bytes.length, 65);
  assert.equal(bytes[0], 4);
  assert.deepEqual(Buffer.from(bytes), raw);
  assert.equal(isVapidKey(text), true);
});

test('handles base64url characters and missing padding', () => {
  // 0xfb 0xff 0xbf encodes to "+/+/" in base64 and "-_-_" in base64url.
  assert.deepEqual([...urlBase64ToUint8Array('-_-_')], [0xfb, 0xff, 0xbf]);
  assert.deepEqual([...urlBase64ToUint8Array('AQ')], [1]);
  assert.deepEqual([...urlBase64ToUint8Array('AQI')], [1, 2]);
  assert.deepEqual([...urlBase64ToUint8Array('AQID')], [1, 2, 3]);
});

test('refuses text that is not base64url, and short or wrong keys are not VAPID keys', () => {
  assert.throws(() => urlBase64ToUint8Array('not base64!'));
  assert.throws(() => urlBase64ToUint8Array('a+b/'));
  assert.equal(isVapidKey(''), false);
  assert.equal(isVapidKey(null), false);
  assert.equal(isVapidKey('AQID'), false);
  const { raw } = vapidPublicKey();
  raw[0] = 2;
  assert.equal(isVapidKey(raw.toString('base64url')), false);
});

const base = { hasServiceWorker: true, hasPushManager: true, hasNotification: true, isIOS: false, isStandalone: false, secureContext: true };

test('a desktop browser with the push APIs is supported', () => {
  assert.equal(pushSupport(base), 'supported');
});

test('iPhone Safari outside the Home Screen gets the install hint, not a broken button', () => {
  assert.equal(pushSupport({ ...base, hasPushManager: false, hasNotification: false, isIOS: true, isStandalone: false }), 'ios-install');
});

test('the Home Screen app on iOS 16.4+ is supported; an older one is not', () => {
  assert.equal(pushSupport({ ...base, isIOS: true, isStandalone: true }), 'supported');
  assert.equal(pushSupport({ ...base, hasPushManager: false, isIOS: true, isStandalone: true }), 'unsupported');
});

test('no push APIs, or an insecure page, is unsupported', () => {
  assert.equal(pushSupport({ ...base, hasPushManager: false }), 'unsupported');
  assert.equal(pushSupport({ ...base, secureContext: false }), 'unsupported');
});

test('the opt-in never asks for permission outside a click handler', () => {
  const code = (file) => fs.readFileSync(path.join(here, file), 'utf8').replace(/\/\*[^]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  const source = code('../src/lib/coworker/push.ts');
  const optIn = code('../src/features/coworker/notifications/push-opt-in.tsx');
  // requestPermission lives only in subscribe(), and subscribe() is only called from the button's handler.
  assert.equal(source.match(/requestPermission\(/g)?.length, 1);
  assert.match(source, /export async function subscribe\([^)]*\)[^{]*\{[^]*?requestPermission\(\)/);
  assert.doesNotMatch(optIn, /requestPermission/);
  assert.equal(optIn.match(/await subscribe\(/g)?.length, 1);
  assert.match(optIn, /async function turnOn\(\)[^]*?await subscribe\(/);
  assert.match(optIn, /onClick=\{\(\) => void turnOn\(\)\}/);
  // Nothing registers the worker on load: only subscribe() registers it.
  assert.doesNotMatch(optIn, /serviceWorker\.register/);
});
