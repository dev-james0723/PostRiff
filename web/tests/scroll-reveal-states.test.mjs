/**
 * ScrollReveal: the hidden state the server renders is the one the browser hydrates, with or without reduced motion
 * (a mismatch is never repaired, and left the server's blur on the revealed Pricing FAQ); with reduced motion the
 * offset and the blur go at once and only the opacity fades.
 *
 *   node --test web/tests/scroll-reveal-states.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { revealStates } from '../src/components/motion/scroll-reveal-states.ts';

const options = { y: 12, blur: 4, duration: 0.6, delay: 0.06, ease: [0.16, 1, 0.3, 1] };

test('the hidden state does not depend on the reduced-motion preference the server cannot know', () => {
  assert.deepEqual(revealStates(true, options).hidden, revealStates(false, options).hidden);
  assert.deepEqual(revealStates(false, options).hidden, { opacity: 0, y: 12, filter: 'blur(4px)' });
});

test('revealed content ends unblurred and in place either way, so nothing the server rendered is left on it', () => {
  for (const reduce of [true, false]) {
    const { shown } = revealStates(reduce, options);
    assert.equal(shown.opacity, 1);
    assert.equal(shown.y, 0);
    assert.equal(shown.transitionEnd.filter, 'none');
  }
});

test('with reduced motion only the opacity animates; the offset and blur are dropped at once', () => {
  const reduced = revealStates(true, options).transition;
  assert.deepEqual(reduced.y, { duration: 0 });
  assert.deepEqual(reduced.filter, { duration: 0 });
  assert.equal(reduced.duration, 0.6);
  assert.equal(reduced.delay, 0.06);
  const full = revealStates(false, options).transition;
  assert.equal(full.y, undefined);
  assert.equal(full.filter, undefined);
  assert.deepEqual(full, { duration: 0.6, ease: options.ease, delay: 0.06 });
});
