import test from 'node:test';
import assert from 'node:assert/strict';
import { jobKind, KIND_META } from '../src/features/calendar/calendar-kinds.ts';

for (const [state, kind] of [['held','held'],['uncertain','uncertain'],['future-state','unknown'],['scheduled','waiting'],['provider_accepted','accepted'],['processing','processing'],['verified','verified'],['submitting','in-flight']]) {
  test(`${state} has an honest calendar state`, () => assert.equal(jobKind(state), kind));
}
test('uncertain never spins as Publishing', () => {
  const meta = KIND_META[jobKind('uncertain')];
  assert.equal(meta.status, 'warning');
  assert.match(meta.label, /not confirmed/i);
});
test('app opening and manual completion remain distinct from API verification', () => {
  assert.equal(jobKind('handoff_opened'),'assisted');
  assert.equal(jobKind('user_reported_completed'),'manual');
});
