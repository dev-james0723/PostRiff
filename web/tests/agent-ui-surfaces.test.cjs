/**
 * rafii-genui/1 lane F: surfaces (generative-ui/surfaces/*).
 * Proves: the D-A21 surface mapping; the presentation plan (passive reopen never POSTs, kill switch is native-only, voice never
 * builds by itself); one session per artifact shared by every surface; a fresh turn POSTs once (concurrent mounts share it,
 * same stable key); reload reads snapshots only; hidden views make no requests; a scope switch disposes sessions and aborts in
 * flight; the outline and Escape skip generated layers; the native frame carries the test markers, never DSL, and never fixes a
 * height or adds a vertical scroller.
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
const STUBS = {
  // C's renderer is lazy (next/dynamic): stand in for it and expose the props F hands it, so F's wiring is checked in isolation.
  'next/dynamic': () => function StubRenderer(props) {
    const React = require(require.resolve('react', { paths: [WEB] }));
    return React.createElement('div', { 'data-stub-renderer': '', 'data-mode': props.render?.mode, 'data-status': props.status ?? '', 'data-active': String(props.active),
      'data-retry': props.onRetry ? '1' : '0', 'data-expand': props.onExpand ? '1' : '0', 'data-historical': String(props.historical), 'data-surface': props.surface,
      'data-manifest': props.manifest?.manifestId ?? '' });
  }
};
function load(file) {
  const filename = path.isAbsolute(file) ? file : path.join(WEB, file);
  if (cache.has(filename)) return cache.get(filename);
  if (filename.endsWith('.json')) {
    const data = JSON.parse(fs.readFileSync(filename, 'utf8'));
    cache.set(filename, { __esModule: true, default: data, ...data });
    return cache.get(filename);
  }
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, resolveJsonModule: true }, fileName: filename }).outputText;
  const module = { exports: {} };
  cache.set(filename, module.exports);
  const req = (name) => (STUBS[name] ? { __esModule: true, default: STUBS[name] } : name.startsWith('@/') || name.startsWith('.') ? load(resolveFile(name, filename)) : require(require.resolve(name, { paths: [WEB] })));
  vm.runInThisContext(`(function(require, exports, module){${code}\n})`, { filename })(req, module.exports, module);
  cache.set(filename, module.exports);
  return module.exports;
}

const plan = load('src/features/agent/generative-ui/surfaces/plan.ts');
const selectors = load('src/features/agent/generative-ui/surfaces/selectors.ts');
const sessions = load('src/features/agent/generative-ui/surfaces/session.ts');
const artifactView = load('src/features/agent/generative-ui/surfaces/artifact.tsx');
const registry = load('src/features/agent/generative-ui/state/registry.ts');
const React = require(require.resolve('react', { paths: [WEB] }));
const { renderToStaticMarkup } = require(require.resolve('react-dom/server', { paths: [WEB] }));

const ART = '6c1f2f3e-1111-4222-8333-944455556666';
const ATT = '7d2a3b4c-2222-4333-8444-a55566667777';
const RUN = '8e3b4c5d-3333-4444-8555-b66677778888';
const MSG = '9f4c5d6e-4444-4555-8666-c77788889999';
const flush = async (n = 20) => { for (let i = 0; i < n; i += 1) await new Promise((resolve) => setImmediate(resolve)); };
const enc = new TextEncoder();
const handoff = { eligible: true, slot: 'main', reason: 'table', journeyIds: ['J06'] };

function view(over = {}, art = {}) {
  return { artifact: { ...{ contractVersion: 'rafii-genui/1', artifactId: ART, conversationId: ART, messageId: MSG, runId: RUN, revision: 1, generationAttemptId: ATT, generationState: 'ready',
    validationState: 'accepted', language: 'openui-lang', languageVersion: '', libraryVersion: '', libraryHash: 'b'.repeat(64), promptHash: '', sourceHash: 'a'.repeat(64),
    canonicalSource: 'root = RafiiRoot([])', fallbackText: 'Native answer.', manifestId: 'm', bindingVersion: 1, safeState: {}, stateRevision: 0, createdAt: 'x', updatedAt: 'x', asOf: null }, ...art },
    manifest: { manifestId: 'm', bindingVersion: 1, journeyIds: [], componentGroups: [], queries: [], actions: [], expiresAt: null }, revisions: [],
    attempt: { attemptId: ATT, kind: 'generate', state: 'ready', reason: null, targetRevision: 1, baseRevision: null, retryOf: null, live: false },
    compatibility: { supported: true, reason: null }, display: { mode: 'generated', reason: null, updating: false },
    access: { role: 'owner', isActor: true, enabled: true, live: true, canQuery: true, canAct: false, canEdit: true, canRetry: true, canPersistState: true, manifestExpired: false,
      historical: false, revokedRefs: [] }, lastSeq: 2, journeyIds: [], surface: 'panel', scope: 'workspace', declared: { stateNames: [], formNames: [] }, ...over };
}
const frameOf = (ev) => `id: ${ev.artifactId}:${ev.seq}\nevent: ${ev.kind}\ndata: ${JSON.stringify(ev)}\n\n`;
const ev = (seq, kind, payload = {}) => ({ contractVersion: 'rafii-genui/1', artifactId: ART, attemptId: ATT, revision: 0, seq, kind, at: 'x', payload });

function transport(scopeKey, handler) {
  const calls = [];
  return { calls, base: '/api/workspaces/w1/agent/ui', scope: 'workspace', scopeKey,
    async fetch(p, init) { calls.push({ p, method: init.method, body: init.body, signal: init.signal }); return handler(p, init, calls.length); } };
}
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

test('surface mapping follows D-A21; expand is offered only where there is room to gain', () => {
  assert.equal(plan.surfaceFor({ kind: 'dock' }), 'panel');
  assert.equal(plan.surfaceFor({ kind: 'above' }), 'panel');
  assert.equal(plan.surfaceFor({ kind: 'overlay', wide: true }), 'panel');
  assert.equal(plan.surfaceFor({ kind: 'overlay', wide: false }), 'mobile');
  assert.equal(plan.surfaceFor({ kind: 'chat' }), 'chat');
  assert.equal(plan.surfaceFor({ kind: 'expanded' }), 'expanded');
  assert.equal(plan.surfaceFor({ kind: 'founder' }), 'founder');
  assert.equal(plan.surfaceFor({ kind: 'voice' }), 'browser_voice');
  assert.equal(plan.canExpand('panel'), true);
  assert.equal(plan.canExpand('mobile'), false, 'on a phone the view renders in place (no nested sheet)');
  assert.equal(plan.canExpand('expanded'), false);
});

test('presentation plan: passive reopen never POSTs; kill switch native-only; voice never builds by itself', () => {
  const base = { enabled: true, handoff, artifacts: [], runId: RUN, fresh: false, latest: true, surface: 'panel' };
  assert.equal(plan.presentationPlan({ ...base, fresh: true }).kind, 'post');
  assert.equal(plan.presentationPlan({ ...base, artifacts: [{ artifactId: ART, slot: 'main' }], fresh: true }).kind, 'load', 'an existing view is read, never rebuilt');
  assert.equal(plan.presentationPlan(base).kind, 'offer', 'reload before the view existed: an explicit offer, not a request');
  assert.equal(plan.presentationPlan({ ...base, latest: false }).kind, 'none');
  assert.equal(plan.presentationPlan({ ...base, enabled: false, fresh: true, artifacts: [{ artifactId: ART, slot: 'main' }] }).kind, 'none');
  assert.equal(plan.presentationPlan({ ...base, fresh: true, modality: 'voice' }).kind, 'offer');
  assert.equal(plan.presentationPlan({ ...base, fresh: true, surface: 'browser_voice' }).kind, 'none');
  assert.equal(plan.presentationPlan({ ...base, fresh: true, handoff: { ...handoff, eligible: false } }).kind, 'none');
  assert.equal(plan.presentationPlan({ ...base, fresh: true, handoff: undefined }).kind, 'none', 'legacy answers stay native');
});

test('reload reads snapshots only (zero presentation POSTs); every surface shares one session per artifact', async () => {
  registry.enterUiScope('workspace:u1:w1');
  sessions.setActiveSessionScope('workspace:u1:w1');
  const t = transport('workspace:u1:w1', (p) => (p.endsWith(`/messages/${MSG}`) ? json({ messageId: MSG, artifacts: [view()] }) : json(view())));
  const loaded = await sessions.loadMessageViews(t, MSG, 'c1');
  const again = await sessions.loadMessageViews(t, MSG, 'c1');
  assert.equal(loaded[0], again[0], 'the panel, full chat and expanded dialog render the same session');
  assert.equal(sessions.sessionFor(t, ART, 'c1'), loaded[0]);
  assert.ok(t.calls.every((c) => c.method === 'GET'), 'reopen is GET only: no presentation, no edit, no retry');
  assert.equal(loaded[0].getState().view.artifact.revision, 1);
  assert.deepEqual(registry.currentUiContext('workspace:u1:w1', 'c1'), { artifactId: ART, artifactRevision: 1, stateRevision: 0 }, 'the ready view becomes the view in use');
});

test('a fresh turn POSTs once with its stable key even when two surfaces mount at the same time', async () => {
  registry.enterUiScope('workspace:u2:w1');
  sessions.setActiveSessionScope('workspace:u2:w1');
  const t = transport('workspace:u2:w1', (p, init) => {
    if (init.method === 'POST' && p.endsWith('/presentations')) {
      return new Response(frameOf(ev(1, 'ui.started')) + frameOf(ev(2, 'ui.delta', { append: 'root = ', offset: 0 })) + frameOf(ev(3, 'ui.ready')),
        { headers: { 'content-type': 'text/event-stream' } });
    }
    return json(view());
  });
  const [a, b] = await Promise.all([sessions.startPresentation({ transport: t, runId: RUN, conversationId: 'c1', surface: 'panel' }),
    sessions.startPresentation({ transport: t, runId: RUN, conversationId: 'c1', surface: 'chat' })]);
  await flush();
  assert.equal(a.session, b.session);
  const posts = t.calls.filter((c) => c.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.idempotencyKey, registry.presentationKey('workspace:u2:w1', RUN));
  assert.deepEqual(Object.keys(posts[0].body).sort(), ['conversationId', 'idempotencyKey', 'parentRunId', 'slot', 'surface']);
  assert.equal(a.session.getState().view.artifact.revision, 1, 'ready → the canonical source is read from the snapshot');
  const refusal = transport('workspace:u2:w1', () => json({ code: 'ui_not_eligible' }, 409));
  const refused = await sessions.startPresentation({ transport: refusal, runId: 'other-run', conversationId: 'c1', surface: 'panel' });
  assert.deepEqual([refused.session, refused.code, refused.status], [null, 'ui_not_eligible', 409]);
});

test('hidden views make no requests; a scope switch disposes sessions and aborts their streams', async () => {
  registry.enterUiScope('workspace:u3:w1');
  sessions.setActiveSessionScope('workspace:u3:w1');
  const t = transport('workspace:u3:w1', (p, init) => {
    if (p.includes('/events')) return new Response(new ReadableStream({ start(c) { c.enqueue(enc.encode(frameOf(ev(3, 'ui.delta', { append: 'x', offset: 0 })))); init.signal?.addEventListener('abort', () => c.error(Object.assign(new Error('aborted'), { name: 'AbortError' }))); } }),
      { headers: { 'content-type': 'text/event-stream' } });
    return json(view());
  });
  const session = sessions.sessionFor(t, ART, 'c1');
  session.retain();
  session.setVisible('v1', false);
  session.adopt(view({ attempt: { attemptId: ATT, kind: 'edit', state: 'streaming', reason: null, targetRevision: 2, baseRevision: 1, retryOf: null, live: true },
    display: { mode: 'generated', reason: null, updating: true } }));
  await flush();
  assert.equal(t.calls.filter((c) => c.p.includes('/events')).length, 0, 'not on screen: no replay, no polling');
  session.setVisible('v1', true);
  await flush();
  const replays = t.calls.filter((c) => c.p.includes('/events'));
  assert.equal(replays.length, 1);
  assert.ok(replays[0].p.endsWith('events?after=2'));
  sessions.setActiveSessionScope('workspace:u3:w2');
  await flush();
  assert.equal(replays[0].signal.aborted, true, 'the workspace switch aborts what was in flight');
  assert.equal(session.isDisposed(), true);
  assert.equal(sessions.sessionCount(), 0);
});

test('a panel turn sent before the runtime status loaded waits for it instead of falling back to the site agent', () => {
  const chat = fs.readFileSync(path.join(WEB, 'src/features/site-agent/chat.tsx'), 'utf8');
  const send = chat.slice(chat.indexOf('const send = useCallback('), chat.indexOf('const continueFromView'));
  assert.ok(send.includes('agent.status ?? (await loadStatus(client, agent.api, w))'), 'send reads the status itself when the query has not answered');
  assert.ok(send.indexOf('loadStatus(') < send.indexOf('if (agentOn)'), 'the runtime is chosen after the status is known');
  assert.ok(send.indexOf('panelStore.setBusy(w, true)') < send.indexOf('loadStatus('), 'the wait happens inside the busy turn (no double send)');
  assert.ok(/markFresh\(uiScope, response\.runId\)/.test(send), 'an eligible answer from this tab is marked fresh');
});

test('the outline and the panel Escape handling skip generated layers (same selectors everywhere)', () => {
  const outline = fs.readFileSync(path.join(WEB, 'src/features/site-agent/use-page-context.ts'), 'utf8');
  for (const selector of selectors.OUTLINE_SKIP_SELECTORS) assert.ok(outline.includes(selector), `OWN_SURFACES includes ${selector}`);
  const panel = fs.readFileSync(path.join(WEB, 'src/features/site-agent/panel.tsx'), 'utf8');
  assert.ok(panel.includes('ESCAPE_SKIP_SELECTORS'), 'Escape inside a generated dialog or confirmation closes that layer, not Rafii');
  assert.ok(selectors.ESCAPE_SKIP_SELECTORS.includes(selectors.GENERATED_DIALOG_SELECTOR));
});

test('the surface host: C renders the frame (no duplicated markers), F passes status, render, active and its controls; no DSL, no fixed height', () => {
  registry.enterUiScope('workspace:u4:w1');
  sessions.setActiveSessionScope('workspace:u4:w1');
  const t = transport('workspace:u4:w1', () => json(view()));
  const session = sessions.sessionFor(t, ART, 'c1');
  session.adopt(view());
  const html = renderToStaticMarkup(React.createElement(artifactView.GeneratedArtifact, { session, surface: 'mobile', runId: RUN, onExpand() {} }));
  assert.match(html, /data-rafii-generated-host=""/);
  assert.doesNotMatch(html, /data-rafii-generated=""|data-artifact-id=|data-generation-state=/, 'C’s frame owns those markers');
  assert.match(html, /data-stub-renderer=""/);
  assert.match(html, /data-mode="generated"/);
  assert.match(html, /data-active="true"/);
  assert.match(html, /data-expand="0"/, 'a phone renders in place: no expand');
  assert.match(html, /data-manifest="m"/);
  assert.match(html, /Change this view/);
  assert.doesNotMatch(html, /RafiiRoot|Query\(|overflow-y|max-h-|h-\[/);
  const panelHtml = renderToStaticMarkup(React.createElement(artifactView.GeneratedArtifact, { session, surface: 'panel', runId: RUN, onExpand() {} }));
  assert.match(panelHtml, /data-expand="1"/);

  const failed = sessions.sessionFor(t, '1c1f2f3e-1111-4222-8333-944455556666', 'c1');
  failed.adopt(view({ attempt: { attemptId: ATT, kind: 'generate', state: 'failed', reason: 'provider_timeout', targetRevision: 1, baseRevision: null, retryOf: null, live: false },
    display: { mode: 'fallback', reason: 'provider_timeout', updating: false } }, { artifactId: '1c1f2f3e-1111-4222-8333-944455556666' }));
  const failedHtml = renderToStaticMarkup(React.createElement(artifactView.GeneratedArtifact, { session: failed, surface: 'panel', runId: RUN }));
  assert.match(failedHtml, /data-mode="fallback"/);
  assert.match(failedHtml, /data-retry="1"/, 'an explicit Try again is offered (with its cost note before anything is sent)');
  assert.match(failedHtml, /data-status="The interactive view isn’t available for this answer. The answer above is complete."/);
  assert.equal(t.calls.filter((c) => c.method === 'POST').length, 0, 'rendering never sends anything');
});
