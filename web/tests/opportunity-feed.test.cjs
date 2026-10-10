const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./agent-ui-library-loader.cjs');
const { load } = createLoader();
const client = load('src/lib/agent-runtime/opportunity-feed.ts');
test('Opportunity navigation is restricted to existing native source panels', () => {
  for (const value of ['https://evil.test', '//evil.test', '/app/founder', '/app/../api/admin', '/app/queue?job=<script>']) assert.equal(client.opportunityHref(value), null);
  for (const value of ['/app/library', '/app/weekly?tab=opportunities', '/app/workspace/personalization', '/app/tasks?task=123']) assert.equal(client.opportunityHref(value), value);
});
test('Opportunity decision sends only the captured ID/digest/decision with session guard', async () => {
  const before = global.fetch, calls = [];
  global.fetch = async (url, init) => { calls.push({ url, ...init }); return { ok: true, json: async () => ({ verified: true }) }; };
  try {
    await client.createOpportunityApi(async () => 'synthetic-session').decide('w/a', { id: 'performance:p', digest: 'a'.repeat(64), reason: 'private content' }, 'experiment');
    assert.deepEqual(JSON.parse(calls[0].body), { id: 'performance:p', digest: 'a'.repeat(64), decision: 'experiment' });
    assert.equal(calls[0].url, '/api/workspaces/w%2Fa/agent/creator-pipeline/opportunities/decide');
    assert.equal(calls[0].headers['X-PostRiff-Request'], 'founder-alpha'); assert.equal(calls[0].cache, 'no-store');
  } finally { global.fetch = before; }
});
