const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  parseReadiness,
  readinessOrUnverified,
  readinessCopy,
  READINESS_UNVERIFIED,
  READINESS_STATES,
  STATE_COPY
} = require('../src/lib/feature-readiness.ts');

const ready = { state: 'ready', reasonCodes: [], canRead: true, canRun: true, lastSuccessfulReadAt: null, nextStep: null };

test('accepts the exact server payload for every state', () => {
  assert.deepEqual(parseReadiness(ready), ready);
  const outage = {
    state: 'temporarily_unavailable',
    reasonCodes: ['provider_unavailable'],
    canRead: true,
    canRun: false,
    lastSuccessfulReadAt: '2026-10-05T13:45:24.890629Z',
    nextStep: { kind: 'wait' }
  };
  assert.deepEqual(parseReadiness(outage), outage);
  for (const state of READINESS_STATES) assert.ok(STATE_COPY[state].title, state);
});

test('fails closed on malformed, unknown or unsafe payloads', () => {
  const broken = [
    undefined,
    null,
    {},
    { ...ready, state: 'maybe' },
    { ...ready, canRun: true, canRead: false },
    { ...ready, reasonCodes: ['growth_off'] },
    { ...ready, reasonCodes: ['Not A Code'] },
    { ...ready, state: 'setup_required', reasonCodes: ['x'], nextStep: { kind: 'consent', href: 'https://evil.example/app' } },
    { ...ready, state: 'setup_required', reasonCodes: ['enrollment_required'], nextStep: { kind: 'email', href: '/app' } },
    { ...ready, state: 'temporarily_unavailable', reasonCodes: ['provider_unavailable'], canRun: false, nextStep: { kind: 'connect', href: '/app/channels' } },
    { ...ready, lastSuccessfulReadAt: 'yesterday' }
  ];
  for (const value of broken) {
    assert.equal(parseReadiness(value), null, JSON.stringify(value));
    assert.deepEqual(readinessOrUnverified(value), READINESS_UNVERIFIED);
  }
  assert.equal(READINESS_UNVERIFIED.canRun, false);
  assert.equal(READINESS_UNVERIFIED.canRead, false);
});

test('copy prefers feature reason copy, outages never mention reconnecting, non-owners are routed to the owner', () => {
  const setup = parseReadiness({
    state: 'setup_required',
    reasonCodes: ['enrollment_required'],
    canRead: false,
    canRun: false,
    lastSuccessfulReadAt: null,
    nextStep: { kind: 'contact_owner' }
  });
  assert.ok(setup);
  const copy = readinessCopy(setup, { enrollment_required: { title: 'Turn on Trends for this workspace.' } });
  assert.equal(copy.title, 'Turn on Trends for this workspace.');
  assert.equal(copy.action, 'Ask the workspace owner');
  assert.doesNotMatch(STATE_COPY.temporarily_unavailable.detail, /reconnect/i);
  assert.equal(readinessCopy(READINESS_UNVERIFIED).action, 'Try again');
});
