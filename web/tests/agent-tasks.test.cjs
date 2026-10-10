const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./agent-ui-library-loader.cjs');
const { load } = createLoader();
const model = load('src/features/agent-tasks/model.ts');
const { createTaskApi } = load('src/lib/agent-runtime/tasks.ts');

test('Task results only navigate within the app after URL normalization', () => {
  for (const value of ['https://evil.test', '//evil.test/app', '/application', '/app/../../api/admin', '/app/%2e%2e/api', '/app/\\evil', '/app/%2fevil']) assert.equal(model.safeTaskHref(value), null, value);
  assert.equal(model.safeTaskHref('/app/queue?job=abc'), '/app/queue?job=abc');
  assert.equal(model.safeTaskHref('/app/agent/abc?task=def'), '/app/agent/abc?task=def');
});
test('Queued provider work is never presented as verified publication', () => {
  const receipt = { verified: true, outcome: 'applied', checks: [{ name: 'saved', ok: true }], providerReceipt: { state: 'queued', verifiedAt: null } };
  assert.equal(model.receiptVerified(receipt), false);
  assert.equal(model.receiptVerified({ ...receipt, providerReceipt: { state: 'verified', verifiedAt: '2026-10-10T00:00:00Z' } }), true);
  assert.equal(model.receiptVerified({ ...receipt, providerReceipt: null, checks: [{ name: 'saved', ok: false }] }), false);
  assert.equal(model.receiptVerified({ ...receipt, providerReceipt: null, verified: null }), false);
});
test('Approval preview preserves long text and marks omitted or empty summaries incomplete', () => {
  const body = 'x'.repeat(12000);
  const full = model.summaryLines({ platform: 'Threads', body, targets: [{ account: 'creator', quantity: 3 }], empty: null });
  assert.equal(full.complete, true);
  assert.equal(full.lines.find((r) => r.label === 'body').value, body);
  assert(full.lines.some((r) => r.value === '3'));
  assert.equal(model.summaryLines({ body: 'x'.repeat(50001) }).complete, false);
  assert.equal(model.summaryLines({}).complete, false);
  assert.equal(model.summaryLines({ a: { b: { c: { d: { e: { f: { g: { h: { i: { j: 'hidden' } } } } } } } } } }).complete, false);
});
test('Task state labels preserve partial/failed distinctions in both Chinese scripts', () => {
  assert.equal(model.language('zh-TW'), 'zh-Hant'); assert.equal(model.language('zh-CN'), 'zh-Hans');
  assert.notEqual(model.stateLabel('failed', 'en'), model.stateLabel('completed', 'en'));
  assert.equal(model.isOpen('completed'), false); assert.equal(model.isOpen('blocked'), true);
});
test('Transport binds workspace, exact digest, generation, version and caller-held retry key', async () => {
  const old = global.fetch; const calls = [];
  global.fetch = async (path, options) => { calls.push({ path, ...options }); return { ok: true, json: async () => ({ outcome: 'applied' }) }; };
  try {
    const api = createTaskApi(async () => 'session-token');
    await api.cancel('workspace/a', 'task/b', 12, 'same-key');
    await api.cancel('workspace/a', 'task/b', 12, 'same-key');
    assert.equal(calls[0].path, '/api/workspaces/workspace%2Fa/agent/tasks/task%2Fb/cancel');
    assert.equal(calls[0].body, calls[1].body);
    assert.deepEqual(JSON.parse(calls[0].body), { idempotencyKey: 'same-key', expectedVersion: 12 });
    assert.equal(calls[0].headers.Authorization, 'Bearer session-token');
    assert.equal(calls[0].headers['X-PostRiff-Request'], 'founder-alpha');
    assert.equal(calls[0].cache, 'no-store');
    await api.retry('w', 't', { stepKey: 'write/draft', generation: 4 }, 'retry-key');
    assert.equal(JSON.parse(calls[2].body).expectedGeneration, 4);
    await api.decide('w', { approvalId: 'a', digest: 'original-digest' }, 'approve', 'approval-key', 'Asia/Hong_Kong');
    assert.deepEqual(JSON.parse(calls[3].body), { decision: 'approve', digest: 'original-digest', idempotencyKey: 'approval-key', timeZone: 'Asia/Hong_Kong' });
  } finally { global.fetch = old; }
});
test('Missing session and aborted stale reads cannot issue a request', async () => {
  const old = global.fetch; let calls = 0; global.fetch = async () => { calls++; throw Error('must not fetch'); };
  try {
    await assert.rejects(createTaskApi(async () => null).list('w', 'open', 'mine', null), (e) => e.status === 401);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(createTaskApi(async () => 'session').detail('w', 't', controller.signal), (e) => e.name === 'AbortError');
    assert.equal(calls, 0);
  } finally { global.fetch = old; }
});
