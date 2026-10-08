/**
 * rafii-genui/1 lane D: the browser query/action bridges (G05 G06 G09 G18).
 *
 * Loads the real TS modules (typescript.transpileModule + node:vm, `@/` mapped to web/src) and drives them with a fake
 * transport that records every request. No jsdom; no network.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const SRC = path.join(WEB, 'src');
const cache = new Map();

function resolveLocal(from, name) {
  const base = name.startsWith('@/') ? path.join(SRC, name.slice(2)) : path.resolve(path.dirname(from), name);
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`cannot resolve ${name} from ${from}`);
}

function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const source = fs.readFileSync(filename, 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    fileName: filename,
  }).outputText;
  const module = { exports: {} };
  cache.set(filename, module);
  const context = vm.createContext({
    console, setTimeout, clearTimeout, setImmediate, AbortController, TextEncoder, Response, URL, btoa, crypto: globalThis.crypto, Uint8Array,
  });
  const localRequire = (name) =>
    name.startsWith('@/') || name.startsWith('.') ? load(resolveLocal(filename, name)) : require(require.resolve(name, { paths: [WEB] }));
  vm.runInContext(`(function(require, exports, module){${code}\n})`, context, { filename })(localRequire, module.exports, module);
  return module.exports;
}

const bridgesDir = path.join(SRC, 'features/agent/generative-ui/bridges');
const bridges = load(path.join(bridgesDir, 'index.ts'));
const ARTIFACT_ID = '6c1f2f3e-1111-4222-8333-944455556666';

const ok = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const result = (state = 'available', data = { rows: [1] }) => ({
  state, data, asOf: '2026-10-08T12:00:00Z', sourceRefs: [], revision: '1', nextCursor: null,
  coverage: { known: 1, total: 1, note: null }, warnings: [],
});

function manifest(extra = {}) {
  return {
    manifestId: 'mf_1', bindingVersion: 1, journeyIds: ['J01'], componentGroups: [], expiresAt: null,
    queries: [
      { name: 'drafts_list', description: 'Drafts', argsSchema: { type: 'object', properties: { q: { type: 'string', maxLength: 120 }, platform: { type: 'string', maxLength: 40 } } }, refreshMinSeconds: 60, pageSize: 50 },
      { name: 'draft_read', description: 'One draft', argsSchema: { type: 'object', properties: { draftId: { type: 'string', maxLength: 120 } } }, refreshMinSeconds: null, pageSize: null },
    ],
    actions: [
      { actionId: 'draft_edit', label: 'Save edit', effect: 'MUTATE_REVERSIBLE', requiresConfirmation: true, inputSchema: {}, summary: 'Saves your edit.' },
      { actionId: 'campaign_link', label: 'Add to campaign', effect: 'MUTATE_REVERSIBLE', requiresConfirmation: false, inputSchema: {}, summary: 'Adds.' },
    ],
    ...extra,
  };
}

function artifact(overrides = {}) {
  return { artifactId: ARTIFACT_ID, revision: 2, accepted: true, historical: false, manifest: manifest(), ...overrides };
}

function transport(handler, scopeKey = 'user-1:ws-1') {
  const calls = [];
  const t = {
    base: '/api/workspaces/ws-1/agent/ui',
    scope: 'workspace',
    scopeKey,
    calls,
    async fetch(p, init) {
      calls.push({ path: p, body: init.body, signal: init.signal });
      return handler(p, init.body, calls.length, init);
    },
  };
  return t;
}

function fakeClock(start = 1_000_000) {
  let t = start;
  return { now: () => t, advance: (ms) => { t += ms; } };
}

function manualTimers() {
  const pending = [];
  return {
    pending,
    setTimeout(fn, ms) { const h = { fn, ms, done: false }; pending.push(h); return h; },
    clearTimeout(h) { if (h) h.done = true; },
    flush() { for (const h of pending.splice(0)) if (!h.done) { h.done = true; h.fn(); } },
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test('toolProvider is null until the revision is server-accepted', () => {
  const t = transport(() => ok(result()));
  const pending = bridges.createQueryBridge({ transport: t, artifact: artifact({ accepted: false }) });
  assert.equal(pending.toolProvider(), null);
  const accepted = bridges.createQueryBridge({ transport: t, artifact: artifact() });
  assert.notEqual(accepted.toolProvider(), null);
});

test('Query(writeName), unknown and inherited names are denied with zero requests', async () => {
  const t = transport(() => ok(result()));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact() });
  const provider = q.toolProvider();
  for (const name of ['draft_edit', 'schedule_prepare', 'constructor', 'toString', '__proto__', 'hasOwnProperty', '']) {
    const out = await provider.callTool({ name, arguments: {} });
    assert.equal(out.structuredContent.state, 'denied', name);
    assert.equal(out.structuredContent.data, null);
  }
  assert.equal(t.calls.length, 0);
});

test('a read posts UiQueryV1 to the queries route and wraps the result for OpenUI', async () => {
  const t = transport(() => ok(result()));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact() });
  const out = await q.toolProvider().callTool({ name: 'draft_read', arguments: { draftId: 'v1' } });
  assert.equal(Array.isArray(out.content) && out.content.length === 0, true);
  assert.equal(out.structuredContent.state, 'available');
  assert.equal(t.calls.length, 1);
  assert.equal(t.calls[0].path, '/api/workspaces/ws-1/agent/ui/queries');
  assert.deepEqual(JSON.parse(JSON.stringify(t.calls[0].body)), { artifactId: ARTIFACT_ID, artifactRevision: 2, bindingId: 'draft_read', inputs: { draftId: 'v1' }, cursor: null });
  assert.equal(q.status('draft_read'), 'available');
  assert.equal(q.status('draft_edit'), undefined);
});

test('hidden, collapsed or historical views make zero network calls', async () => {
  const t = transport(() => ok(result()));
  const historical = bridges.createQueryBridge({ transport: t, artifact: artifact({ historical: true }) });
  const out = await historical.read('draft_read', { draftId: 'v1' });
  assert.equal(out.state, 'unavailable');
  assert.equal(t.calls.length, 0);
  historical.setActive(true);
  await historical.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.length, 1);
  historical.setActive(false);
  const paused = await historical.read('draft_read', { draftId: 'v1' });
  assert.equal(paused.state, 'stale', 'the last real result is shown as stale, never re-fetched');
  await historical.read('draft_read', { draftId: 'v2' });
  assert.equal(t.calls.length, 1);
});

test('identical reads inside the refresh interval are served from cache; invalidation refetches', async () => {
  const clock = fakeClock();
  const t = transport(() => ok(result()));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact(), now: clock.now });
  await q.read('draft_read', { draftId: 'v1' });
  await q.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.length, 1);
  clock.advance(29_000);
  await q.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.length, 1, 'refresh minimum is 30 s');
  q.invalidate(['draft_read']);
  await q.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.length, 2);
  clock.advance(31_000);
  await q.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.length, 3);
});

test('at most 4 requests are in flight per artifact', async () => {
  let inFlight = 0;
  let peak = 0;
  const releases = [];
  const t = transport(() => {
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    return new Promise((resolve) => releases.push(() => { inFlight -= 1; resolve(ok(result())); }));
  });
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact() });
  const reads = Array.from({ length: 7 }, (_, i) => q.read('draft_read', { draftId: `v${i}` }));
  await tick();
  assert.equal(t.calls.length, 4);
  for (let i = 0; i < 200 && (t.calls.length < 7 || releases.length); i += 1) {
    while (releases.length) releases.shift()();
    await tick();
  }
  await Promise.all(reads);
  assert.equal(peak, 4);
  assert.equal(t.calls.length, 7);
});

test('more than 60 admissions a minute are refused locally', async () => {
  const clock = fakeClock();
  const t = transport(() => ok(result()));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact(), now: clock.now });
  for (let i = 0; i < 65; i += 1) await q.read('draft_read', { draftId: `v${i}` });
  assert.equal(t.calls.length, 60);
  const refused = await q.read('draft_read', { draftId: 'v-new' });
  assert.equal(refused.state, 'unavailable');
  assert.equal(refused.data, null);
});

test('text search is debounced 300 ms and the superseded request is never sent', async () => {
  const timers = manualTimers();
  const t = transport(() => ok(result()));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact(), timers });
  const a = q.read('drafts_list', { q: 'pi' });
  const b = q.read('drafts_list', { q: 'pia' });
  const c = q.read('drafts_list', { q: 'piano' });
  assert.equal(timers.pending.filter((h) => !h.done).length, 1);
  assert.equal(timers.pending.at(-1).ms, 300);
  timers.flush();
  const [ra, rb, rc] = await Promise.all([a, b, c]);
  assert.equal(t.calls.length, 1);
  assert.equal(t.calls[0].body.inputs.q, 'piano');
  assert.equal(rc.state, 'available');
  assert.notEqual(ra.state, 'available');
  assert.notEqual(rb.state, 'available');
});

test('a failure backs off and never becomes zero or empty data', async () => {
  const clock = fakeClock();
  let fail = true;
  const t = transport(() => (fail ? ok({ error: 'down', code: 'internal_error' }, 503) : ok(result())));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact(), now: clock.now });
  const first = await q.read('draft_read', { draftId: 'v1' });
  assert.equal(first.state, 'unavailable');
  assert.equal(first.data, null);
  const during = await q.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.length, 1, 'backoff: no immediate retry');
  assert.equal(during.state, 'unavailable');
  fail = false;
  clock.advance(1_100);
  const after = await q.read('draft_read', { draftId: 'v1' });
  assert.equal(after.state, 'available');
  assert.equal(t.calls.length, 2);
});

test('404/403 from the server read as denied; malformed bodies as unavailable', async () => {
  const t = transport((_p, body) => (body.inputs.draftId === 'gone' ? ok({ error: 'x', code: 'ui_artifact' }, 404) : ok({ state: 'available', data: 1 })));
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact() });
  assert.equal((await q.read('draft_read', { draftId: 'gone' })).state, 'denied');
  assert.equal((await q.read('draft_read', { draftId: 'odd' })).state, 'unavailable');
});

test('a scope switch or dispose aborts in-flight reads and stops all traffic', async () => {
  const signals = [];
  const t = transport((_p, _b, _n, init) => {
    signals.push(init.signal);
    return new Promise(() => {});
  });
  const q = bridges.createQueryBridge({ transport: t, artifact: artifact() });
  q.read('draft_read', { draftId: 'v1' });
  await tick();
  q.dispose();
  assert.equal(signals[0].aborted, true);
  const after = await q.read('draft_read', { draftId: 'v2' });
  assert.equal(after.state, 'unavailable');
  assert.equal(t.calls.length, 1);
  assert.equal(q.toolProvider(), null);

  const t2 = transport(() => ok(result()));
  const q2 = bridges.createQueryBridge({ transport: t2, artifact: artifact() });
  t2.scopeKey = 'user-2:ws-9';
  const switched = await q2.read('draft_read', { draftId: 'v1' });
  assert.equal(switched.state, 'unavailable');
  assert.equal(t2.calls.length, 0);
});

// --- actions -------------------------------------------------------------------------------------------------------------
const activation = (required = true, expiresIn = 60_000) => ({
  activationId: 'act_' + 'a'.repeat(43), inputDigest: 'd'.repeat(64), expiresAt: new Date(Date.now() + expiresIn).toISOString(),
  confirmation: { required, title: 'Save draft edit', summary: ['Save your edited text.'], target: 'LinkedIn draft', timeZone: null, cost: 'No AI cost' },
});
const actionResult = (body, outcome = 'applied', verified = true) => ({
  actionId: body.actionId, idempotencyKey: body.idempotencyKey, outcome, verified, receiptRef: 'draft:v1@3', proposalRef: null,
  changedRefs: ['draft:v1'], invalidationKeys: ['draft_read'], nextContext: {},
});

async function settle(bridge, phases = ['idle', 'done', 'error', 'confirming']) {
  for (let i = 0; i < 50 && !phases.includes(bridge.state().phase); i += 1) await tick();
  for (let i = 0; i < 5; i += 1) await tick();
}

test('nothing writes until an explicit confirm; then one execute with a durable key', async () => {
  const t = transport((p, body) => (p.endsWith('/activate') ? ok(activation(), 201) : ok(actionResult(body))));
  const a = bridges.createActionBridge({ transport: t, artifact: artifact() });
  assert.equal(a.writesEnabled('draft_edit'), true);
  assert.equal(a.writesEnabled('schedule_prepare'), false);
  assert.equal(a.binding('draft_edit').label, 'Save edit');
  a.request({ actionId: 'draft_edit', controlId: 'save', inputs: { draftId: 'v1', revision: 2, text: 'New text' } });
  await settle(a, ['confirming', 'error']);
  assert.equal(a.state().phase, 'confirming');
  assert.equal(t.calls.length, 1);
  assert.equal(t.calls[0].path.endsWith('/actions/activate'), true);
  assert.equal(a.state().activation.confirmation.title, 'Save draft edit');
  const out = await a.confirm();
  assert.equal(out.outcome, 'applied');
  assert.equal(t.calls.length, 2);
  const body = t.calls[1].body;
  assert.equal(t.calls[1].path, '/api/workspaces/ws-1/agent/ui/actions');
  assert.match(body.idempotencyKey, /^[A-Za-z0-9_-]{16,80}$/);
  assert.equal(body.activationId, activation().activationId);
  assert.deepEqual(JSON.parse(JSON.stringify(body.inputs)), { draftId: 'v1', revision: 2, text: 'New text' });
  assert.equal(a.state().phase, 'done');
  assert.equal(await a.confirm(), null, 'a finished action cannot be confirmed again');
  assert.equal(t.calls.length, 2);
});

test('a double click while activating or confirming is ignored', async () => {
  const t = transport((p, body) => (p.endsWith('/activate') ? ok(activation(), 201) : ok(actionResult(body))));
  const a = bridges.createActionBridge({ transport: t, artifact: artifact() });
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(a, ['confirming']);
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await tick();
  assert.equal(t.calls.length, 1);
  const [one, two] = await Promise.all([a.confirm(), a.confirm()]);
  assert.equal([one, two].filter(Boolean).length, 1);
  assert.equal(t.calls.length, 2);
});

test('a lost reply is reconciled with the same key and activation, never a new one', async () => {
  let sends = 0;
  const t = transport((p, body) => {
    if (p.endsWith('/activate')) return ok(activation(), 201);
    sends += 1;
    if (sends === 1) throw new TypeError('network');
    if (sends === 2) return ok({ error: 'gateway' }, 502);
    return ok(actionResult(body));
  });
  const a = bridges.createActionBridge({ transport: t, artifact: artifact(), reconcileDelays: [1, 1], sleep: () => Promise.resolve() });
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(a, ['confirming']);
  const out = await a.confirm();
  assert.equal(out.outcome, 'applied');
  const executes = t.calls.filter((c) => c.path.endsWith('/actions'));
  assert.equal(executes.length, 3);
  assert.equal(new Set(executes.map((c) => c.body.idempotencyKey)).size, 1);
  assert.equal(new Set(executes.map((c) => c.body.activationId)).size, 1);
});

test('when every reconciliation fails the key is kept: confirm again re-checks with it', async () => {
  let up = false;
  const t = transport((p, body) => {
    if (p.endsWith('/activate')) return ok(activation(), 201);
    if (!up) throw new TypeError('offline');
    return ok(actionResult(body));
  });
  const a = bridges.createActionBridge({ transport: t, artifact: artifact(), reconcileDelays: [1], sleep: () => Promise.resolve() });
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(a, ['confirming']);
  assert.equal(await a.confirm(), null);
  assert.equal(a.state().phase, 'error');
  assert.match(a.state().error, /couldn’t confirm whether this was saved/);
  up = true;
  const out = await a.confirm();
  assert.equal(out.outcome, 'applied');
  const keys = new Set(t.calls.filter((c) => c.path.endsWith('/actions')).map((c) => c.body.idempotencyKey));
  assert.equal(keys.size, 1);
});

test('a server-declared direct action executes on the click without a sheet', async () => {
  const t = transport((p, body) => (p.endsWith('/activate') ? ok(activation(false), 201) : ok(actionResult(body))));
  const a = bridges.createActionBridge({ transport: t, artifact: artifact() });
  a.request({ actionId: 'campaign_link', inputs: { campaignId: 'c1', draftIds: ['v1'] } });
  await settle(a, ['done', 'error']);
  assert.equal(a.state().phase, 'done');
  assert.equal(t.calls.length, 2);
});

test('an action outside the manifest, a disposed bridge or an unaccepted revision sends nothing', async () => {
  const t = transport(() => ok(activation(), 201));
  const a = bridges.createActionBridge({ transport: t, artifact: artifact() });
  a.request({ actionId: 'publish_now', inputs: {} });
  assert.equal(a.state().phase, 'error');
  const pending = bridges.createActionBridge({ transport: t, artifact: artifact({ accepted: false }) });
  assert.equal(pending.writesEnabled('draft_edit'), false);
  pending.request({ actionId: 'draft_edit', inputs: {} });
  a.dispose();
  a.request({ actionId: 'draft_edit', inputs: {} });
  assert.equal(t.calls.length, 0);
});

test('an expired confirmation is refused locally', async () => {
  const t = transport((p, body) => (p.endsWith('/activate') ? ok(activation(true, -1), 201) : ok(actionResult(body))));
  const a = bridges.createActionBridge({ transport: t, artifact: artifact() });
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(a, ['confirming']);
  assert.equal(await a.confirm(), null);
  assert.equal(a.state().phase, 'error');
  assert.equal(t.calls.length, 1);
});

test('the bridge never upgrades a prepared or unverified outcome, and server error text is never shown', async () => {
  const t = transport((p, body) => (p.endsWith('/activate') ? ok(activation(), 201) : ok(actionResult(body, 'prepared', false))));
  const a = bridges.createActionBridge({ transport: t, artifact: artifact() });
  a.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(a, ['confirming']);
  const out = await a.confirm();
  assert.equal(out.outcome, 'prepared');
  assert.equal(out.verified, false);

  const t2 = transport(() => ok({ error: '<script>alert(1)</script> internal trace', code: 'weird' }, 409));
  const b = bridges.createActionBridge({ transport: t2, artifact: artifact() });
  b.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(b, ['error']);
  assert.doesNotMatch(b.state().error, /script|trace/);
});

test('createUiBridges invalidates reads named by a verified result and forwards follow-ups with the artifact ids', async () => {
  const sent = [];
  const t = transport((p, body) => {
    if (p.endsWith('/queries')) return ok(result());
    if (p.endsWith('/activate')) return ok(activation(), 201);
    return ok(actionResult(body));
  });
  const ui = bridges.createUiBridges({ transport: t, artifact: artifact(), onContinue: (r) => sent.push(r) });
  await ui.query.read('draft_read', { draftId: 'v1' });
  await ui.query.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.filter((c) => c.path.endsWith('/queries')).length, 1);
  ui.action.request({ actionId: 'draft_edit', inputs: { text: 'x' } });
  await settle(ui.action, ['confirming']);
  await ui.action.confirm();
  await ui.query.read('draft_read', { draftId: 'v1' });
  assert.equal(t.calls.filter((c) => c.path.endsWith('/queries')).length, 2);
  ui.onContinue({ message: '  compare the second two  ', artifactId: 'forged', artifactRevision: 99, stateRevision: 4 });
  ui.onContinue({ message: '   ', artifactId: ARTIFACT_ID, artifactRevision: 2, stateRevision: 0 });
  assert.deepEqual(JSON.parse(JSON.stringify(sent)), [{ message: 'compare the second two', artifactId: ARTIFACT_ID, artifactRevision: 2, stateRevision: 4 }]);
  ui.query.dispose();
  assert.equal(ui.action.writesEnabled('draft_edit'), false, 'disposing one side stops both');
});

test('context hooks return null outside a provider (never throw)', () => {
  const React = require(require.resolve('react', { paths: [WEB] }));
  const { renderToStaticMarkup } = require(require.resolve('react-dom/server', { paths: [WEB] }));
  const seen = {};
  function Probe() {
    seen.bridges = bridges.useUiBridges();
    seen.action = bridges.useRafiiActionBridge();
    seen.query = bridges.useRafiiQueryBridge();
    seen.state = bridges.useRafiiActionState();
    return null;
  }
  renderToStaticMarkup(React.createElement(Probe));
  assert.equal(seen.bridges, null);
  assert.equal(seen.action, null);
  assert.equal(seen.query, null);
  assert.equal(seen.state.phase, 'idle');
  const t = transport(() => ok(result()));
  const ui = bridges.createUiBridges({ transport: t, artifact: artifact(), onContinue: () => {} });
  renderToStaticMarkup(React.createElement(bridges.UiBridgesProvider, { bridges: ui }, React.createElement(Probe)));
  assert.equal(seen.bridges, ui);
  assert.equal(seen.action, ui.action);
  assert.equal(seen.query, ui.query);
});
