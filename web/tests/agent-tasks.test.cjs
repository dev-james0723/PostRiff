const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./agent-ui-library-loader.cjs');
const { load } = createLoader();
const model = load('src/features/agent-tasks/model.ts');
const { createTaskApi, taskRequestKey, forgetTaskRequest, readPendingTask, savePendingTask, clearPendingTask, runTaskRequest } = load('src/lib/agent-runtime/tasks.ts');

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
test('Changed resources open supported native destinations without inventing asset deep links', () => {
  assert.equal(model.changedResourceHref({ type: 'library_asset', id: 'abc123' }), '/app/library');
  assert.equal(model.changedResourceHref({ type: 'draft', id: 'draft-1' }), '/app/queue?view=drafts&draft=draft-1');
  assert.equal(model.changedResourceHref({ type: 'source', id: 'source-1' }), '/app/ideas?source=source-1');
  assert.equal(model.changedResourceHref({ type: 'library_asset', id: '../private' }), null);
  assert.equal(model.changedResourceHref({ type: 'unknown', id: 'safe' }), null);
  const report = '12345678-1234-4234-8234-123456789012';
  assert.equal(model.changedResourceHref({ type: 'workflow_report', id: report }), '/app/automations?recipeReport=' + report);
  assert.equal(model.changedResourceHref({ type: 'workflow_report', id: 'not-a-report' }), null);
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

test('An unresolved action keeps its scoped key across module remount until an acknowledged response clears it', () => {
  const prior = Object.getOwnPropertyDescriptor(global, 'sessionStorage');
  const stored = new Map();
  Object.defineProperty(global, 'sessionStorage', { configurable: true, value: {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: (key) => stored.delete(key)
  } });
  try {
    const identity = 'person-a:workspace-a:task-a:cancel:8';
    const key = taskRequestKey(identity);
    const remounted = createLoader().load('src/lib/agent-runtime/tasks.ts');
    assert.equal(remounted.taskRequestKey(identity), key, 'reload must not duplicate an uncertain request');
    assert.notEqual(taskRequestKey('person-b:workspace-a:task-a:cancel:8'), key, 'another person is isolated');
    assert.notEqual(taskRequestKey('person-a:workspace-b:task-a:cancel:8'), key, 'another workspace is isolated');
    assert.notEqual(taskRequestKey('person-a:workspace-a:task-a:approve:8'), key, 'a different operation is isolated');
    forgetTaskRequest(identity);
    assert.notEqual(taskRequestKey(identity), key, 'an acknowledged request no longer reserves its old key');
  } finally {
    if (prior) Object.defineProperty(global, 'sessionStorage', prior); else delete global.sessionStorage;
  }
});
test('Task Center remounts selected detail on role or permission narrowing, not permission ordering', () => {
  let person = 'person-a', workspace = 'workspace-a';
  let access = { role: 'owner', permissions: ['read', 'edit', 'owner'], hasWorkspace: true };
  const { load: isolated } = createLoader({ stubs: {
    '@/lib/auth/session': { useAuth: () => ({ user: { id: person } }) },
    '@/lib/workspace/provider': { useWorkspaceApi: () => ({ workspaceId: workspace }) },
    '@/lib/auth/access': { useWorkspaceAccess: () => access, checkAccess: () => true },
    '@/components/layout/page-container': {}, '@/components/ui/button': {}, '@/components/rafii/state-message': {},
    '@/lib/preferences': {}, 'next/link': {}
  } });
  const { TaskCenter } = isolated('src/features/agent-tasks/task-center.tsx');
  const owner = TaskCenter();
  access = { ...access, permissions: ['owner', 'edit', 'read'] };
  assert.equal(TaskCenter().key, owner.key, 'equivalent entitlements keep the same boundary');
  access = { ...access, role: 'editor', permissions: ['read', 'edit'] };
  const editor = TaskCenter();
  assert.notEqual(editor.key, owner.key, 'demotion remounts completed foreign task detail');
  assert.notEqual(editor.props.boundary, owner.props.boundary, 'queries use the new entitlement boundary');
  access = { ...access, permissions: ['read'] };
  assert.notEqual(TaskCenter().key, editor.key, 'same-role permission narrowing also remounts');
  const narrowed = TaskCenter().key;
  person = 'person-b'; assert.notEqual(TaskCenter().key, narrowed);
  const otherPerson = TaskCenter().key;
  workspace = 'workspace-b'; assert.notEqual(TaskCenter().key, otherPerson);
});

test('Pending descriptors are scoped, validated and contain no approval content or credentials', () => {
  const prior = Object.getOwnPropertyDescriptor(global, 'sessionStorage');
  const stored = new Map();
  Object.defineProperty(global, 'sessionStorage', { configurable: true, value: {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: (key) => stored.delete(key)
  } });
  const scope = 'person-a:workspace-a';
  const record = { key: `task:${require('node:crypto').randomUUID()}`, identity: 'person-a:workspace-a:task-a:cancel:8',
    request: { kind: 'cancel', taskId: 'task-a', version: 8 } };
  try {
    savePendingTask(scope, record);
    assert.deepEqual(JSON.parse(JSON.stringify(readPendingTask(scope))), record);
    assert.equal(readPendingTask('person-b:workspace-a'), null);
    assert.equal(readPendingTask('person-a:workspace-b'), null);
    const slot = [...stored.keys()][0];
    for (const bad of [null, {}, { ...record, key: '' }, { ...record, identity: '' },
      { ...record, request: { kind: 'cancel', taskId: '' } },
      { ...record, request: { kind: 'publish', taskId: 'task-a' } },
      { ...record, request: { kind: 'cancel', taskId: 'task-a', version: '8' } },
      { ...record, request: { kind: 'retry', taskId: 'task-a', step: { stepKey: 'draft' } } },
      { ...record, request: { kind: 'retry', taskId: 'task-a', step: { stepKey: 'draft', generation: -1, undo: null } } },
      { ...record, request: { kind: 'undo', taskId: 'task-a', step: { stepKey: 'draft', generation: 1, undo: null } } },
      { ...record, request: { kind: 'approve', taskId: 'task-a', approval: { approvalId: 'approval-a' } } }
    ]) {
      stored.set(slot, JSON.stringify(bad));
      assert.equal(readPendingTask(scope), null, JSON.stringify(bad));
    }
    stored.set(slot, '{not-json'); assert.equal(readPendingTask(scope), null);
    stored.set(slot, 'x'.repeat(8001)); assert.equal(readPendingTask(scope), null);
    clearPendingTask(scope);
    const privateText = 'PRIVATE-DRAFT-CONTENT';
    savePendingTask(scope, { ...record, token: 'PRIVATE-SESSION-TOKEN', summary: privateText,
      request: { kind: 'approve', taskId: 'task-a', approval: { approvalId: 'approval-a', digest: 'review-digest', summary: { body: privateText } },
        timeZone: 'Asia/Hong_Kong', body: privateText } });
    // The helper may reject unexpected fields or persist only its safe descriptor.
    const persisted = [...stored.values()].join('');
    assert(!persisted.includes(privateText)); assert(!persisted.includes('PRIVATE-SESSION-TOKEN'));
    const safe = readPendingTask(scope);
    if (safe) assert.deepEqual(JSON.parse(JSON.stringify(safe.request)), { kind: 'approve', taskId: 'task-a', approval: { approvalId: 'approval-a', digest: 'review-digest' }, timeZone: 'Asia/Hong_Kong' });
    clearPendingTask(scope); assert.equal(readPendingTask(scope), null);
  } finally {
    if (prior) Object.defineProperty(global, 'sessionStorage', prior); else delete global.sessionStorage;
  }
});
test('Restored requests dispatch only on an explicit call with their original version, generation, compensation and digest', async () => {
  const calls = [];
  const api = Object.fromEntries(['cancel', 'continue', 'retry', 'undo', 'decide'].map((kind) => [kind, (...args) => {
    calls.push({ kind, args }); return Promise.resolve({ outcome: 'applied' });
  }]));
  const key = 'same-restored-key';
  const requests = [
    { kind: 'cancel', taskId: 'task-a', version: 8 },
    { kind: 'continue', taskId: 'task-a' },
    { kind: 'retry', taskId: 'task-a', step: { stepKey: 'draft', generation: 2, undo: null } },
    { kind: 'undo', taskId: 'task-a', step: { stepKey: 'draft', generation: 2, undo: { compensationId: 'undo-a', undoUntil: '2026-10-10T00:00:00Z' } } },
    { kind: 'approve', taskId: 'task-a', approval: { approvalId: 'approval-a', digest: 'captured-digest' }, timeZone: 'Asia/Hong_Kong' },
    { kind: 'reject', taskId: 'task-a', approval: { approvalId: 'approval-a', digest: 'captured-digest' }, timeZone: 'Asia/Hong_Kong' }
  ];
  assert.equal(calls.length, 0);
  for (const request of requests) await runTaskRequest(api, 'workspace-a', request, key);
  assert.deepEqual(calls, [
    { kind: 'cancel', args: ['workspace-a', 'task-a', 8, key] },
    { kind: 'continue', args: ['workspace-a', 'task-a', key] },
    { kind: 'retry', args: ['workspace-a', 'task-a', requests[2].step, key] },
    { kind: 'undo', args: ['workspace-a', 'task-a', requests[3].step, key] },
    { kind: 'decide', args: ['workspace-a', requests[4].approval, 'approve', key, 'Asia/Hong_Kong'] },
    { kind: 'decide', args: ['workspace-a', requests[5].approval, 'reject', key, 'Asia/Hong_Kong'] }
  ]);
});
