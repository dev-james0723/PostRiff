/**
 * Inbox paging rules (src/features/inbox/pages.ts): a refreshed first page never drops loaded conversations, and a
 * linked conversation that isn't loaded yet is looked for page by page, within a bound.
 *
 *   node --test web/tests/inbox-pages.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { retainLoaded, SEEK_PAGES, seekState } from '../src/features/inbox/pages.ts';

const id = (item) => item.id;
const items = (...ids) => ids.map((value) => ({ id: value }));

test('older pages survive a refreshed first page, and so does whatever slid off it', () => {
  const first = items('t9', 't8', 't7');
  const older = items('t6', 't5');
  // An approved reply refreshes page 1 without new comments: nothing is dropped.
  assert.deepEqual(retainLoaded(first, items('t9', 't8', 't7'), older, id).map(id), ['t6', 't5']);
  // Two new comments push t8 and t7 off page 1: they stay loaded (with the older pages), none twice.
  assert.deepEqual(retainLoaded(first, items('t11', 't10', 't9'), older, id).map(id), ['t8', 't7', 't6', 't5']);
  // Whatever page 1 now holds is not kept twice.
  assert.deepEqual(retainLoaded(first, items('t6', 't9', 't8'), older, id).map(id), ['t7', 't5']);
  assert.deepEqual(retainLoaded([], items('t1'), [], id), []);
});

test('a linked conversation is looked for page by page, then the person decides', () => {
  const base = { wanted: 't-old', found: false, loaded: true, cursor: 'c1', pages: 0 };
  assert.equal(seekState(base), 'seeking');
  assert.equal(seekState({ ...base, pages: SEEK_PAGES - 1 }), 'seeking');
  assert.equal(seekState({ ...base, pages: SEEK_PAGES }), 'more'); // bounded: the person chooses to keep looking
  assert.equal(seekState({ ...base, cursor: null }), 'missing'); // everything loaded and it isn't there
  assert.equal(seekState({ ...base, found: true }), 'idle');
  assert.equal(seekState({ ...base, wanted: null }), 'idle');
  assert.equal(seekState({ ...base, loaded: false }), 'idle'); // nothing to say before the first page
});
