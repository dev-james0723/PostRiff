/**
 * rafii-genui/1 lane F: history, reopen and state (generative-ui/state/*).
 * Proves: the reducer shows only server-accepted canonical source as interactive, keeps a first generation as an untrusted
 * preview (byte-exact across fragmented/overlapping deltas, gaps request a replay), keeps the last valid revision on a failed
 * edit, falls back natively for an old library, and re-reads the snapshot on ready/state changes; the persisted-state
 * controller saves declared fields only, debounced, CAS-merges a concurrent tab's edits, records ordered selections, stops on
 * refusal and respects the size cap; applyUiPatch never silently drops typed values; registries are per scope.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const cache = new Map();
function resolveFile(request, from) {
  const base = request.startsWith('@/') ? path.join(WEB, 'src', request.slice(2)) : path.resolve(path.dirname(from), request);
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts')]) if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  return null;
}
function load(file) {
  const filename = path.isAbsolute(file) ? file : path.join(WEB, file);
  if (cache.has(filename)) return cache.get(filename);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }, fileName: filename }).outputText;
  const module = { exports: {} };
  cache.set(filename, module.exports);
  const req = (name) => (name.startsWith('@/') || name.startsWith('.') ? load(resolveFile(name, filename)) : require(require.resolve(name, { paths: [WEB] })));
  vm.runInThisContext(`(function(require, exports, module){${code}\n})`, { filename })(req, module.exports, module);
  cache.set(filename, module.exports);
  return module.exports;
}

const machine = load('src/features/agent/generative-ui/state/artifact-machine.ts');
const persisted = load('src/features/agent/generative-ui/state/persisted-state.ts');
const registry = load('src/features/agent/generative-ui/state/registry.ts');
const ART = '6c1f2f3e-1111-4222-8333-944455556666';
const ATT = '7d2a3b4c-2222-4333-8444-a55566667777';
const flush = async (n = 10) => { for (let i = 0; i < n; i += 1) await new Promise((resolve) => setImmediate(resolve)); };

function artifact(over = {}) {
  return { contractVersion: 'rafii-genui/1', artifactId: ART, conversationId: ART, messageId: ART, runId: ART, revision: 1, generationAttemptId: ATT, generationState: 'ready',
    validationState: 'accepted', language: 'openui-lang', languageVersion: '0.3', libraryVersion: '0.3.2', libraryHash: 'b'.repeat(64), promptHash: 'c'.repeat(64),
    sourceHash: 'a'.repeat(64), canonicalSource: 'root = RafiiRoot([])', fallbackText: 'Native answer.', manifestId: 'm', bindingVersion: 1, safeState: {}, stateRevision: 0,
    createdAt: 'x', updatedAt: 'x', asOf: null, ...over };
}
function view(over = {}, art = {}) {
  return { artifact: artifact(art), manifest: { manifestId: 'm', bindingVersion: 1, journeyIds: ['J06'], componentGroups: [], queries: [], actions: [], expiresAt: null }, revisions: [],
    attempt: { attemptId: ATT, kind: 'generate', state: 'ready', reason: null, targetRevision: 1, baseRevision: null, retryOf: null, live: false },
    compatibility: { supported: true, reason: null }, display: { mode: 'generated', reason: null, updating: false },
    access: { role: 'owner', isActor: true, enabled: true, live: true, canQuery: true, canAct: true, canEdit: true, canRetry: true, canPersistState: true, manifestExpired: false,
      historical: false, revokedRefs: [] }, lastSeq: 3, journeyIds: ['J06'], surface: 'panel', scope: 'workspace', declared: { stateNames: ['$period'], formNames: ['filters'] }, ...over };
}
const ev = (seq, kind, payload = {}, attemptId = ATT) => ({ contractVersion: 'rafii-genui/1', artifactId: ART, attemptId, revision: 0, seq, kind, at: 'x', payload });
const run = (actions, start = machine.INITIAL_ARTIFACT_STATE) => actions.reduce((state, action) => machine.reduceArtifact(state, action), start);

test('reopen: an accepted snapshot renders its canonical source; nothing else is ever interactive', () => {
  const state = run([{ type: 'snapshot', view: view() }]);
  const render = machine.renderOf(state);
  assert.equal(render.mode, 'generated');
  assert.equal(render.artifact.canonicalSource, 'root = RafiiRoot([])');
  assert.equal(machine.statusLine(state), null);
});

test('first generation: a byte-exact preview across fragmented, duplicated and overlapping deltas; a gap asks for a replay', () => {
  const text = 'root = RafiiRoot([t])\nt = Text("粵語🎹")';
  const bytes = new TextEncoder().encode(text);
  const cut = 22; // inside the multi-byte tail of the source
  const head = new TextDecoder().decode(bytes.subarray(0, 19));
  let state = run([{ type: 'snapshot', view: view({ display: { mode: 'pending', reason: null, updating: true }, attempt: { attemptId: ATT, kind: 'generate', state: 'streaming', live: true } },
    { revision: 0, validationState: 'pending', generationState: 'streaming', canonicalSource: null }) }, { type: 'event', event: ev(4, 'ui.started') },
    { type: 'event', event: ev(5, 'ui.delta', { append: head, offset: 0 }) },
    { type: 'event', event: ev(5, 'ui.delta', { append: head, offset: 0 }) },                         // duplicate (replay overlap)
    { type: 'event', event: ev(6, 'ui.delta', { append: text.slice(head.length), offset: 19 }) }]);
  assert.equal(state.candidate.source, text);
  assert.equal(state.candidate.bytes, bytes.length);
  const preview = machine.renderOf(state);
  assert.equal(preview.mode, 'preview');
  assert.equal(preview.accepted, false);
  assert.equal(preview.artifact?.canonicalSource ?? null, null, 'a preview never carries canonical (interactive) source');
  assert.equal(machine.statusLine(state), 'Building the interactive view…');
  state = machine.reduceArtifact(state, { type: 'event', event: ev(8, 'ui.delta', { append: 'x', offset: bytes.length + 5 }) });
  assert.equal(state.needsReplay, true);
  state = machine.reduceArtifact(state, { type: 'event', event: ev(9, 'ui.ready', { sourceHash: 'a'.repeat(64) }) });
  assert.equal(state.needsSnapshot, true, 'ready means: read the canonical source from the snapshot');
  void cut;
});

test('edit streaming keeps the accepted revision on screen; a failed edit keeps it; a failed first view falls back natively', () => {
  let state = run([{ type: 'snapshot', view: view() }, { type: 'event', event: ev(4, 'ui.started') }, { type: 'event', event: ev(5, 'ui.delta', { append: 'chart = ', offset: 0 }) }]);
  assert.equal(state.phase, 'updating');
  assert.equal(machine.renderOf(state).mode, 'generated', 'the old revision stays interactive while the edit streams');
  state = machine.reduceArtifact(state, { type: 'event', event: ev(6, 'ui.failed', { reason: 'parse_rejected' }) });
  assert.equal(machine.renderOf(state).mode, 'generated');
  assert.equal(machine.renderOf(state).artifact.revision, 1);
  assert.match(machine.statusLine(state), /previous view is kept/);

  const first = run([{ type: 'snapshot', view: view({ display: { mode: 'pending', reason: null, updating: true } }, { revision: 0, validationState: 'pending', canonicalSource: null }) },
    { type: 'event', event: ev(4, 'ui.started') }, { type: 'event', event: ev(5, 'ui.failed', { reason: 'provider_timeout' }) }]);
  const render = machine.renderOf(first);
  assert.equal(render.mode, 'fallback');
  assert.equal(render.text, 'Native answer.');
  assert.match(machine.statusLine(first), /answer above is complete/);
});

test('old library version: native fallback without rendering the stored source (no model call involved)', () => {
  const state = run([{ type: 'snapshot', view: view({}, { libraryHash: 'f'.repeat(64) }), supportedLibraryHashes: ['b'.repeat(64)] }]);
  const render = machine.renderOf(state);
  assert.equal(render.mode, 'fallback');
  assert.equal(render.reason, 'library_unsupported');
  assert.equal(state.view.artifact.canonicalSource, null);
  assert.match(machine.statusLine(state), /older version/);
  // The server's own fallback decision is respected too.
  const server = run([{ type: 'snapshot', view: view({ display: { mode: 'fallback', reason: 'library_unsupported', updating: false } }, { canonicalSource: null }) }]);
  assert.equal(machine.renderOf(server).mode, 'fallback');
});

test('another tab changed the state or bindings: re-read the snapshot; unavailable views fall back', () => {
  let state = run([{ type: 'snapshot', view: view() }, { type: 'event', event: ev(4, 'ui.state_changed', { stateRevision: 1 }, null) }]);
  assert.equal(state.needsSnapshot, true);
  state = run([{ type: 'snapshot', view: view() }, { type: 'event', event: ev(4, 'ui.state_changed', { stateRevision: 0 }, null) }]);
  assert.equal(state.needsSnapshot, false, 'our own save echo does not trigger a reload');
  const gone = run([{ type: 'snapshot_failed', status: 404, code: 'ui_artifact_revoked' }]);
  assert.equal(machine.renderOf(gone).mode, 'fallback');
  assert.equal(machine.statusLine(gone), 'This interactive view is no longer available.');
});

function stateHarness({ responses, canPersist = true, declared = { stateNames: ['$period'], formNames: ['filters'] }, initial = { safeState: {}, stateRevision: 0 } } = {}) {
  const calls = [];
  const queue = [];
  const timers = { setTimeout: (fn, ms) => { const t = { fn, ms }; queue.push(t); return t; }, clearTimeout: (t) => { const i = queue.indexOf(t); if (i >= 0) queue.splice(i, 1); } };
  const errors = [];
  const transport = { base: '/api/workspaces/w1/agent/ui', scope: 'workspace', scopeKey: 'workspace:u1:w1',
    async fetch(p, init) { calls.push({ p, init }); const r = responses.shift(); return new Response(JSON.stringify(r.body), { status: r.status }); } };
  const controller = new persisted.UiStateController({ transport, artifactId: ART, initial, declared, canPersist, timers, onError: (code) => errors.push(code) });
  return { controller, calls, queue, errors, fire: async () => { const t = queue.shift(); t?.fn(); await flush(); } };
}

test('persisted state: declared fields only, debounced into one CAS write; secrets and undeclared fields never leave the tab', async () => {
  const h = stateHarness({ responses: [{ status: 200, body: { artifactId: ART, stateRevision: 1, safeState: { $period: '7d' } } }] });
  h.controller.update({ $period: '30d', $secretToken: 'x', $undeclared: 1, other: { a: 1 } });
  h.controller.update({ $period: '7d' });
  assert.equal(h.calls.length, 0);
  assert.equal(h.queue.length, 1);
  assert.equal(h.queue[0].ms, 500);
  await h.fire();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0].init.body, { expectedStateRevision: 0, patch: { $period: '7d' } });
  assert.equal(h.calls[0].p, `/api/workspaces/w1/agent/ui/presentations/${ART}/state`);
  assert.deepEqual(h.controller.dirtyFields(), []);
  assert.equal(h.controller.current().stateRevision, 1);
});

test('persisted state: a conflict re-applies only this tab’s dirty fields over the other tab’s state (both edits survive)', async () => {
  const h = stateHarness({ responses: [
    { status: 409, body: { code: 'ui_state_conflict', current: { stateRevision: 4, safeState: { $period: '90d', filters: { platform: { value: 'IG' } } } } } },
    { status: 200, body: { stateRevision: 5, safeState: { $period: '90d', filters: { platform: { value: 'LinkedIn' } } } } }
  ] });
  h.controller.update({ filters: { platform: { value: 'LinkedIn', componentType: 'Select' } } });
  await h.controller.flush();
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls[1].init.body.expectedStateRevision, 4);
  assert.deepEqual(Object.keys(h.calls[1].init.body.patch), ['filters'], 'the other tab’s $period is not overwritten');
  assert.equal(h.controller.current().stateRevision, 5);
  assert.equal(h.controller.initialState().$period, '90d');
});

test('persisted state: a conflict without a body re-reads the snapshot; refusals stop saving; oversize never sends', async () => {
  const h = stateHarness({ responses: [
    { status: 409, body: { code: 'ui_state_conflict' } },
    { status: 200, body: { artifact: { safeState: { $period: '1d' }, stateRevision: 7 } } },
    { status: 200, body: { stateRevision: 8, safeState: { $period: '7d' } } }
  ] });
  h.controller.update({ $period: '7d' });
  await h.controller.flush();
  assert.deepEqual(h.calls.map((c) => c.init.method), ['POST', 'GET', 'POST']);
  assert.equal(h.calls[2].init.body.expectedStateRevision, 7);

  const viewer = stateHarness({ responses: [{ status: 403, body: { code: 'permission_denied' } }] });
  viewer.controller.update({ $period: '7d' });
  await viewer.controller.flush();
  viewer.controller.update({ $period: '1d' });
  await viewer.controller.flush();
  assert.equal(viewer.calls.length, 1);
  assert.deepEqual(viewer.errors, ['ui_state_forbidden']);

  const big = stateHarness({ responses: [] });
  big.controller.update({ $period: 'x'.repeat(17 * 1024) });
  await big.controller.flush();
  assert.equal(big.calls.length, 0);
  assert.deepEqual(big.errors, ['ui_state_too_large']);

  const local = stateHarness({ responses: [], canPersist: false });
  local.controller.update({ $period: '7d' });
  await local.controller.flush();
  assert.equal(local.calls.length, 0, 'a viewer keeps state in the tab only');
});

test('selection memory: the ordered selection and the list as shown are saved under @selection', async () => {
  const h = stateHarness({ responses: [{ status: 200, body: { stateRevision: 1, safeState: {} } }] });
  h.controller.recordSelection('drafts', [{ type: 'draft', id: 'd2', title: 'Spring' }, { type: 'draft', id: 'd1' }, { type: 'draft', id: 'd2' }, { type: 'Bad Type', id: 'x' }],
    [{ type: 'draft', id: 'd1', title: 'dropped' }, { type: 'draft', id: 'd2' }]);
  await h.controller.flush();
  assert.deepEqual(h.calls[0].init.body.patch['@selection'], {
    items: [{ type: 'draft', id: 'd2', title: 'Spring' }, { type: 'draft', id: 'd1', title: '' }],
    visible: [{ type: 'draft', id: 'd1' }, { type: 'draft', id: 'd2' }], listId: 'drafts'
  });
});

test('applyUiPatch: typed values stay when the new revision still declares them; the others are reported, never silently dropped', () => {
  const result = persisted.applyUiPatch({ safeState: { $period: '7d', $removed: 'typed', filters: { a: 1 } } }, { safeState: { $period: '30d' }, stateRevision: 3 },
    ['$period', '$removed', 'filters'], { stateNames: ['period'], formNames: [] });
  assert.equal(result.initialState.$period, '7d');
  assert.deepEqual(result.lostFields, ['$removed', 'filters']);
  assert.deepEqual(result.lostValues, { $removed: 'typed', filters: { a: 1 } });
});

test('registries: one stable presentation key per scope and run; fresh marks and views in use never cross scopes', () => {
  registry.enterUiScope('workspace:u1:w1');
  const key = registry.presentationKey('workspace:u1:w1', 'run-1');
  assert.match(key, /^[A-Za-z0-9_-]{16,80}$/);
  assert.equal(registry.presentationKey('workspace:u1:w1', 'run-1'), key, 'a remount resends the same key');
  assert.notEqual(registry.presentationKey('workspace:u1:w2', 'run-1'), key);
  registry.markFresh('workspace:u1:w1', 'run-1');
  assert.equal(registry.isFresh('workspace:u1:w1', 'run-1'), true);
  assert.equal(registry.isFresh('workspace:u1:w1', 'run-2'), false, 'history read back from the server is never fresh');
  registry.setUiContext('workspace:u1:w1', 'c1', { artifactId: ART, artifactRevision: 2, stateRevision: 5 });
  assert.deepEqual(registry.currentUiContext('workspace:u1:w1', 'c1'), { artifactId: ART, artifactRevision: 2, stateRevision: 5 });
  assert.equal(registry.currentUiContext('workspace:u1:w1', 'c2'), undefined);
  assert.deepEqual(registry.currentUiContextForWorkspace('w1', 'c1'), { artifactId: ART, artifactRevision: 2, stateRevision: 5 });
  assert.equal(registry.currentUiContextForWorkspace('w2', 'c1'), undefined);
  registry.enterUiScope('workspace:u1:w2');
  assert.equal(registry.isFresh('workspace:u1:w1', 'run-1'), false, 'switching workspace forgets the old scope');
  assert.equal(registry.currentUiContext('workspace:u1:w1', 'c1'), undefined);
  registry.enterUiScope(null);
  assert.deepEqual(registry.registrySizes(), { fresh: 0, inUse: 0, byArtifact: 0, keys: 0 });
});

test('registries: a fresh mark made after a slot rendered notifies it (the turn response may land after the message)', () => {
  registry.enterUiScope('workspace:u9:w9');
  let calls = 0;
  const stop = registry.onUiScopeChange(() => { calls += 1; });
  const before = registry.registryVersion();
  registry.markFresh('workspace:u9:w9', 'run-late');
  assert.equal(calls, 1);
  assert.ok(registry.registryVersion() > before, 'useSyncExternalStore sees a new snapshot');
  registry.markFresh('workspace:u9:w9', 'run-late');
  assert.equal(calls, 1, 'marking the same run again changes nothing');
  stop();
  registry.enterUiScope(null);
});
