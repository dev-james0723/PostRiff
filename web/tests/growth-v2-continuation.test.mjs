/**
 * Consented Post Doctor continuation (PRD R-FWR-01, AC06/AC07): only the selected text, only in this tab, at most
 * 24 hours, only an opaque nonce in URLs, cleared after import/discard/expiry, safe when storage is blocked.
 *
 *   node --test web/tests/growth-v2-continuation.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CONTINUATION_TTL_MS,
  buildRecord,
  clearContinuation,
  importBody,
  newNonce,
  readContinuation,
  saveContinuation,
  signUpHref
} from '../src/lib/growth-v2/continuation.ts';

class Memory {
  constructor() {
    this.data = new Map();
  }
  getItem(key) {
    return this.data.has(key) ? this.data.get(key) : null;
  }
  setItem(key, value) {
    this.data.set(key, String(value));
  }
  removeItem(key) {
    this.data.delete(key);
  }
}

class Blocked {
  getItem() {
    throw new Error('SecurityError');
  }
  setItem() {
    throw new Error('QuotaExceededError');
  }
  removeItem() {}
}

const NOW = 1_790_870_000_000;
const DRAFT = 'Most adult beginners quit piano because they practise pieces, not skills.';

function record(select = { original: true, edited: false }, edited = null) {
  return buildRecord({ nonce: newNonce(), now: NOW, platform: 'Threads', language: 'en', original: DRAFT, edited, select,
    result: { helping: ['Clear hook'], hurting: [], change: ['Add one example'], status: 'complete', _scores: { a: 1 }, contextDigest: 'x' } });
}

test('only the selected versions are kept, and only qualitative feedback', () => {
  const both = record({ original: true, edited: true }, DRAFT + ' Start tonight.');
  assert.deepEqual(both.items.map((i) => i.kind), ['original', 'edited']);
  assert.deepEqual(Object.keys(both.result).sort(), ['change', 'helping', 'hurting', 'status']);
  const editedOnly = record({ original: false, edited: true }, DRAFT + ' Start tonight.');
  assert.deepEqual(editedOnly.items.map((i) => i.kind), ['edited']);
  assert.throws(() => record({ original: false, edited: true }, DRAFT)); // an unchanged "edit" is not a second version
  assert.throws(() => record({ original: false, edited: false }));
  assert.throws(() => buildRecord({ nonce: newNonce(), now: NOW, platform: 'Threads', language: 'en', original: 'x'.repeat(8001), select: { original: true, edited: false } }));
});

test('save, read and clear in the same tab; expiry clears on access', () => {
  const storage = new Memory();
  const saved = record();
  assert.equal(saveContinuation(storage, saved), true);
  assert.deepEqual(readContinuation(storage, saved.nonce, NOW + 1000), { status: 'ready', record: saved });
  assert.deepEqual(readContinuation(storage, null, NOW + 1000), { status: 'ready', record: saved }); // pending nonce after a URL clean-up
  assert.deepEqual(readContinuation(storage, saved.nonce, NOW + CONTINUATION_TTL_MS + 1), { status: 'expired' });
  assert.equal(storage.data.size, 0);
  const again = record();
  saveContinuation(storage, again);
  clearContinuation(storage, again.nonce);
  assert.deepEqual(readContinuation(storage, again.nonce, NOW), { status: 'missing' });
  assert.equal(storage.data.size, 0);
});

test('blocked storage stores nothing and reports unavailable', () => {
  assert.equal(saveContinuation(new Blocked(), record()), false);
  assert.deepEqual(readContinuation(new Blocked(), newNonce(), NOW), { status: 'unavailable' });
  assert.deepEqual(readContinuation(null, newNonce(), NOW), { status: 'unavailable' });
});

test('damaged, foreign or tampered records are refused and removed', () => {
  const storage = new Memory();
  const saved = record();
  saveContinuation(storage, saved);
  const key = `rafii.continue.v1.${saved.nonce}`;
  for (const raw of ['not json', JSON.stringify({ ...saved, nonce: 'other-nonce-000000000' }), JSON.stringify({ ...saved, items: [{ kind: 'script', text: 'x' }] }),
    JSON.stringify({ ...saved, platform: 'Myspace' })]) {
    storage.setItem(key, raw);
    assert.equal(readContinuation(storage, saved.nonce, NOW).status, 'invalid');
    assert.equal(storage.getItem(key), null);
  }
  assert.equal(readContinuation(storage, '../../etc', NOW).status, 'invalid');
});

test('URLs carry only the opaque nonce; text stays in the request body', () => {
  const saved = record();
  const href = signUpHref(saved.nonce, false);
  assert.ok(href.startsWith('/auth/sign-up?next='));
  assert.ok(!href.includes('piano') && !href.includes(encodeURIComponent('piano')));
  assert.equal(decodeURIComponent(href.split('next=')[1]), `/app/weekly?continue=${saved.nonce}`);
  assert.equal(signUpHref(saved.nonce, true), `/app/weekly?continue=${saved.nonce}`);
  const body = importBody(saved);
  assert.equal(body.idempotencyKey, saved.nonce);
  assert.equal(body.consent, true);
  assert.deepEqual(body.items, saved.items);
  assert.ok(!('result' in body)); // feedback stays in the browser; the server never needs it
});
