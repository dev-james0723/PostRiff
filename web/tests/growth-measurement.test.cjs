const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readingState } = require('../src/features/growth/measurement-state.ts');

test('only native observed availability enables the measured state, including observed zero', () => {
  assert.equal(readingState({ horizon: '24h', available: true, state: 'disabled' }).label, 'available');
  assert.equal(readingState({ horizon: '24h', available: false, state: 'measured' }).label, 'unavailable');
});

test('failure, rights and disabled states never tell the creator to wait for a reading', () => {
  for (const state of ['disabled', 'unsupported', 'disconnected', 'rights_unavailable', 'unscheduled', 'unavailable']) {
    const result = readingState({ horizon: '1h', available: false, state });
    assert.notEqual(result.label, 'not due yet');
    assert.notEqual(result.label, 'scheduled');
    assert.notEqual(result.label, 'in progress');
    assert.ok(result.title && result.detail);
  }
  assert.match(readingState({ horizon: '1h', available: false, state: 'unscheduled' }).detail, /no durable reading/i);
});

test('future, queued and in-progress readings remain distinct and unknown states fail closed', () => {
  assert.equal(readingState({ horizon: '7d', available: false, state: 'pending_horizon' }).label, 'not due yet');
  assert.equal(readingState({ horizon: '1h', available: false, state: 'scheduled' }).label, 'scheduled');
  assert.equal(readingState({ horizon: '1h', available: false, state: 'pending' }).label, 'in progress');
  assert.equal(readingState().label, 'unavailable');
  assert.equal(readingState({ horizon: '1h', available: false }).label, 'unavailable');
  assert.equal(readingState({ horizon: '1h', available: false, state: 'unknown_future_state' }).label, 'unavailable');
});
