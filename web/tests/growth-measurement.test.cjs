const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readingState, readingStateKey } = require('../src/features/growth/measurement-state.ts');

test('only native observed availability enables the measured state, including observed zero', () => {
  assert.equal(readingState({ horizon: '24h', available: true, state: 'disabled' }).label, 'available');
  assert.equal(readingState({ horizon: '24h', available: false, state: 'measured' }).label, 'unavailable');
});

test('failure, rights and disabled states never tell the creator to wait for a reading', () => {
  for (const state of ['disabled', 'unsupported', 'disconnected', 'rights_unavailable', 'unscheduled', 'unavailable', 'missed', 'not_entitled']) {
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

test('a missed window stays missed and an imported reading is never a measured window', () => {
  const missed = readingState({ horizon: '1h', available: false, state: 'missed' });
  assert.equal(missed.label, 'missed');
  assert.match(missed.detail, /Missing data stays missing\./);
  assert.match(missed.detail, /never stored in its place/);
  assert.notEqual(missed.label, readingState({ horizon: '1h', available: false, state: 'unavailable' }).label);
  const backfill = readingState({ horizon: '24h', available: false, state: 'backfill' });
  assert.equal(backfill.label, 'imported reading');
  assert.match(backfill.detail, /not a 1h, 24h or 7d window/);
  assert.notEqual(backfill.label, readingState({ horizon: '24h', available: true }).label);
  assert.equal(readingStateKey({ horizon: '24h', available: false, state: 'backfill' }), 'backfill');
  assert.equal(readingStateKey({ horizon: '24h', available: false, state: 'toString' }), 'unavailable');
});

test('admission and rights never ask to reconnect; only a real disconnection does', () => {
  for (const state of ['not_entitled', 'rights_unavailable', 'missed', 'disabled', 'unavailable', 'scheduled', 'pending', 'pending_horizon', 'backfill']) {
    const copy = readingState({ horizon: '7d', available: false, state });
    assert.doesNotMatch(copy.title + copy.detail, /reconnect/i, state);
  }
  assert.match(readingState({ horizon: '7d', available: false, state: 'disconnected' }).detail, /Reconnect/);
});

test('every state has a distinct visible mark next to its window label', () => {
  const marks = ['measured', 'scheduled', 'pending', 'missed', 'backfill', 'pending_horizon'].map((state) =>
    readingState({ horizon: '1h', available: state === 'measured', state }).mark);
  assert.equal(new Set(marks).size, marks.length);
});
