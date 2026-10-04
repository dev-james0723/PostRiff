const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file, mocks = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src/features/notifications', file), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', compiled)((id) => mocks[id] ?? require(id), module, module.exports);
  return module.exports;
}

const { safeAppHref } = load('../notifications/../../lib/coworker/safe-href.ts');
const { founderSafeHref } = (() => {
  const file = path.join(__dirname, '../src/features/founder/shared/safe-href.ts');
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', compiled)(module, module.exports);
  return module.exports;
})();
const presentation = load('presentation.ts', {
  '@/lib/coworker/safe-href': { safeAppHref },
  '@/features/founder/shared/safe-href': { founderSafeHref },
  '@/features/coworker/notifications/labels': { eventLabel: (type) => type }
});
const actions = load('actions.ts');
const live = load('live-state.ts');

function server(id, overrides = {}) {
  return {
    id, status: 'delivered', createdAt: 100, type: 'campaign.approval_required',
    category: 'approvals', severity: 'action', entity: { type: 'variant', id: id },
    payload: { title: 'Review a draft', href: '/app/queue' }, readAt: null, actedAt: null, actionable: true,
    ...overrides
  };
}

test('server adapter preserves source identity, unread and safe app navigation', () => {
  const item = presentation.adaptServer(server('n1'));
  assert.equal(item.id, 'server:n1');
  assert.equal(item.kind, 'action_required');
  assert.equal(item.priority, 'high');
  assert.equal(item.unread, true);
  assert.equal(item.href, '/app/queue');
  assert.equal(item.createdAt, 100000);
  assert.equal(presentation.adaptServer(server('bad', { payload: { title: 'Review a draft', href: 'javascript:alert(1)' } })).href, undefined);
});

test('attention and Founder adapters keep their distinct read and link contracts', () => {
  const attention = presentation.adaptAttention({ id: 'approvals', tone: 'info', title: 'Drafts', description: 'Review', href: '/app/queue', action: 'Review' });
  assert.equal(attention.source, 'attention');
  assert.equal(attention.unread, false);
  assert.equal(attention.dismissible, false);
  const founder = presentation.adaptFounder({ id: 'f1', severity: 'security', title: 'Account changed', href: '/founder/settings', createdAt: 10, read: false });
  assert.equal(founder.kind, 'security');
  assert.equal(founder.href, '/founder/settings');
  assert.equal(founder.unread, true);
  assert.equal(presentation.adaptFounder({ id: 'f2', severity: 'info', title: 'Bad link', href: '//evil.test', createdAt: 10, read: true }).href, undefined);
});

test('priority wins; only explicit shared event keys merge sources', () => {
  const normal = presentation.adaptServer(server('normal', { severity: 'info', type: 'publish.verified' }));
  const critical = presentation.adaptServer(server('critical', { severity: 'critical', type: 'publish.failed' }));
  const sameWords = presentation.adaptServer(server('same-words'));
  assert.deepEqual(presentation.sortNotifications([normal, critical, sameWords]).map((item) => item.id), ['server:critical', 'server:normal', 'server:same-words'].sort((a, b) => {
    const p = { 'server:critical': 0, 'server:same-words': 1, 'server:normal': 2 };
    return p[a] - p[b];
  }));
  const shared = { ...sameWords, source: 'founder', id: 'founder:f1', sourceId: 'f1', dedupeKey: 'event-1' };
  const original = { ...sameWords, dedupeKey: 'event-1' };
  assert.equal(presentation.sortNotifications([shared, original]).length, 1);
  assert.equal(presentation.sortNotifications([sameWords, { ...sameWords, id: 'server:n2', sourceId: 'n2' }]).length, 2);
  const sameEvent = presentation.adaptServer(server('same-event', { dedupeKey: 'event-1', workspaceId: 'w' }));
  const duplicate = presentation.adaptServer(server('duplicate', { dedupeKey: 'event-1', workspaceId: 'w' }));
  const otherWorkspace = presentation.adaptServer(server('other-workspace', { dedupeKey: 'event-1', workspaceId: 'other' }));
  assert.equal(presentation.sortNotifications([sameEvent, duplicate, otherWorkspace]).length, 2);
});

test('surface routing separates live progress, local toast and durable history', () => {
  assert.deepEqual(presentation.chooseSurfaces({ local: true }), ['toast']);
  assert.deepEqual(presentation.chooseSurfaces({ status: 'running' }), ['live']);
  assert.deepEqual(presentation.chooseSurfaces({ status: 'waiting' }), ['live', 'center', 'activity']);
  const item = presentation.adaptServer(server('n1'));
  assert.deepEqual(presentation.chooseSurfaces(item), ['center', 'activity']);
  assert.deepEqual(presentation.chooseSurfaces({ ...item, kind: 'info', unread: false }), ['activity']);
});

test('direct actions stay pending until a verified server result and reject failures', async () => {
  let finish;
  let settled = false;
  const pending = actions.requireConfirmedAction(() => new Promise((resolve) => { finish = resolve; }), 'read').then(() => { settled = true; });
  await Promise.resolve();
  assert.equal(settled, false);
  finish({ verified: true, status: 'read' });
  await pending;
  assert.equal(settled, true);
  await assert.rejects(actions.requireConfirmedAction(async () => ({ verified: false, status: 'read' }), 'read'));
  await assert.rejects(actions.requireConfirmedAction(async () => ({ verified: true, status: 'read' }), 'dismissed'));
});

test('Live Pill state follows real run status and only durable waiting', () => {
  const run = { workspaceId: 'w', runId: 'r', conversationId: 'c', status: 'running', stage: 'drafting', progress: 25, updatedAt: 10 };
  assert.deepEqual(live.deriveLiveState([run], []), { status: 'running', label: 'Rafii · drafting', href: '/app/agent/c', count: 1, progress: 25 });
  const waiting = presentation.adaptAttention({ id: 'approvals', tone: 'info', title: 'Approval required', description: '', href: '/app/queue', action: 'Review' });
  assert.equal(live.deriveLiveState([], [waiting]).status, 'waiting');
  assert.equal(live.deriveLiveState([{ ...run, status: 'completed' }], []).status, 'success');
  assert.equal(live.deriveLiveState([{ ...run, status: 'failed' }], []).status, 'error');
  assert.deepEqual(live.deriveLiveState([], [], true), { status: 'running', label: 'Rafii · Working…', count: 1 });
  assert.equal(live.deriveLiveState([], []).status, 'idle');
});
