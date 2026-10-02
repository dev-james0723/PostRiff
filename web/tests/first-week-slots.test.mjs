/**
 * First week: the person can write any committed post the planner couldn't draft, not only a `planned` one (the
 * server's write_slot takes the person's own words for every post that isn't in Queue).
 *
 *   node --test web/tests/first-week-slots.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { canWriteYourself } from '../src/lib/growth-v2/first-week-slots.ts';

const slot = (status, extra = {}) => ({ status, committed: true, draft: null, ...extra });

test('a committed post without a draft can be written by the person, whatever stopped the planner', () => {
  for (const status of ['planned', 'needs_source', 'needs_input']) assert.equal(canWriteYourself(slot(status)), true, status);
});

test('not offered for a post outside the commitment, one that already has a draft, or one in Queue', () => {
  assert.equal(canWriteYourself(slot('needs_source', { committed: false })), false);
  assert.equal(canWriteYourself(slot('ready', { draft: { text: 'Mine', revision: 1, needsReview: true, origin: 'person' } })), false);
  assert.equal(canWriteYourself(slot('needs_source', { draft: { text: 'Mine', revision: 1, needsReview: true, origin: 'person' } })), false);
  for (const status of ['in_queue', 'approved', 'scheduled', 'published', 'rejected', 'accepted']) assert.equal(canWriteYourself(slot(status)), false, status);
});
