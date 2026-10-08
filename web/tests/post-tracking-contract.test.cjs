const test = require('node:test');
const assert = require('node:assert/strict');
const { loadTypes } = require('./trend-contract.cjs');
const { postTrackingSchema } = loadTypes();

test('post tracking accepts distinct real horizon target, deadline and retry time', () => {
  const horizon = { window: '24h', state: 'scheduled', due_at: 86400, deadline_at: 87000, next_attempt_at: 86520, reason: null };
  const tracking = { enabled: true, as_of: 86500, truncated: false,
    posts: [{ job_id: 'job', provider: 'threads', account: 'account', horizons: [horizon] }] };
  assert.deepEqual(postTrackingSchema.parse(tracking).posts[0].horizons[0], horizon);
  const invalid = structuredClone(tracking);
  invalid.posts[0].horizons[0].next_attempt_at = Infinity;
  assert.equal(postTrackingSchema.safeParse(invalid).success, false);
  invalid.posts[0].horizons[0] = { ...horizon, invented_evidence: true };
  assert.equal(postTrackingSchema.safeParse(invalid).success, false);
});
