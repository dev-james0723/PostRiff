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

test('"Change this view" opens a focused field (fine pointers; a phone keeps the suggestions visible) and sends the live selection as is', () => {
  const source = fs.readFileSync(path.join(WEB, 'src/features/agent/generative-ui/surfaces/artifact.tsx'), 'utf8');
  const edit = source.slice(source.indexOf('export function EditView('));
  assert.match(edit, /useEffect\(\(\) => \{\s*if \(!coarsePointer\(\)\) input\.current\?\.focus\(\);\s*\}, \[\]\)/);
  assert.match(source, /matchMedia\('\(pointer: coarse\)'\)/);
  assert.match(edit, /<input ref=\{input\}/);
  assert.doesNotMatch(edit, /\? \{ selection \} :/, 'the selection is not wrapped in another object');
  // The request carries the selection this tab holds now (controller-local @selection), read at submit, not the snapshot's.
  assert.match(edit, /const current = selectionNow\(\);[\s\S]*session\.edit\(instruction, current\)/);
  assert.match(edit, /liveSelection\(controller\?\.selection\(\), session\.getState\(\)\.view\?\.artifact\.safeState\)/);
  assert.doesNotMatch(edit, /safeState\?\.\['@selection'\]/, 'never the stale snapshot selection directly');
  // Escape closes the panel from anywhere in the form (a focused chip too), and stops there.
  assert.match(edit, /<form onSubmit=\{\(event\) => void submit\(event\)\} onKeyDown=\{onFormKeyDown\}/);
  assert.match(edit, /const onFormKeyDown = [\s\S]*event\.key === 'Escape'[\s\S]*event\.stopPropagation\(\);[\s\S]*onDone\(\);/);
  // A chip tap only fills the field: no edit, no fetch, focus stays on the chip.
  const pick = edit.slice(edit.indexOf('const pick = '), edit.indexOf('const submit = '));
  assert.ok(pick.includes("dispatch({ type: 'pick'"));
  assert.doesNotMatch(pick, /session\.|fetch|submit\(|\.focus\(/);
});

const editForm = load('src/features/agent/generative-ui/surfaces/edit-form.ts');
const frame = load('src/features/agent/generative-ui/surfaces/frame.tsx');
const genLocale = load('src/features/agent/generative-ui/core/locale.tsx');
const timePrefs = load('src/lib/time.ts');
const REPO = path.join(WEB, '..');
const EXAMPLES = path.join(REPO, 'src/postriff_phase2/agent_runtime_v2/generated/journey-examples');
const dCatalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'agent-ui-journeys', 'fixtures', 'd-catalog.json'), 'utf8'));
const J01_SOURCE = fs.readFileSync(path.join(EXAMPLES, 'J01-drafts-studio.openui'), 'utf8').trim();
const access = (over = {}) => ({ role: 'owner', isActor: true, enabled: true, live: true, canQuery: true, canAct: false, canEdit: true, canRetry: true, canPersistState: true,
  manifestExpired: false, historical: false, revokedRefs: [], ...over });
function j01View(id, over = {}) {
  return view({ journeyIds: ['J01'], access: access({ canPersistState: false }), declared: { stateNames: ['$selectedDrafts'], formNames: [] },
    manifest: { manifestId: 'm', bindingVersion: 1, journeyIds: ['J01'], componentGroups: [], actions: [], expiresAt: null,
      queries: dCatalog.journeys.J01.queries.map((q) => ({ name: q.name, description: `PRIVATE ${q.name}`, argsSchema: q.argsSchema, refreshMinSeconds: null, pageSize: null })) },
    ...over }, { artifactId: id, canonicalSource: J01_SOURCE });
}

test('"Change this view" is for the person who asked only (the server refuses anyone else), and never while an older revision is shown', () => {
  registry.enterUiScope('workspace:u5:w1');
  sessions.setActiveSessionScope('workspace:u5:w1');
  const t = transport('workspace:u5:w1', () => json(view()));
  const other = sessions.sessionFor(t, '2c1f2f3e-1111-4222-8333-944455556666', 'c1');
  other.adopt(view({ access: access({ isActor: false }) }, { artifactId: '2c1f2f3e-1111-4222-8333-944455556666' }));
  const html = renderToStaticMarkup(React.createElement(artifactView.GeneratedArtifact, { session: other, surface: 'panel', runId: RUN }));
  assert.doesNotMatch(html, /Change this view/, 'a member who did not ask sees no edit control (it would only get a 403)');
  assert.equal(t.calls.filter((c) => c.method === 'POST').length, 0);

  const base = { access: access(), accepted: true, live: false };
  assert.deepEqual(editForm.editAccess({ ...base, older: null }), { canEdit: true, note: null });
  assert.deepEqual(editForm.editAccess({ ...base, access: access({ isActor: false }), older: null }), { canEdit: false, note: null });
  assert.deepEqual(editForm.editAccess({ ...base, access: access({ canEdit: false }), older: null }), { canEdit: false, note: null });
  assert.deepEqual(editForm.editAccess({ ...base, live: true, older: null }), { canEdit: false, note: null });
  assert.deepEqual(editForm.editAccess({ ...base, accepted: false, older: null }), { canEdit: false, note: null });
  assert.deepEqual(editForm.editAccess({ ...base, older: 'choosing' }), { canEdit: false, note: 'newerVersion' }, 'the dirty-field warning is up');
  assert.deepEqual(editForm.editAccess({ ...base, older: 'kept' }), { canEdit: false, note: 'keptEarlier' }, '"Keep the earlier view" was chosen');
  // C reports the older revision to F (no other renderer change) and F gates on it.
  const renderer = fs.readFileSync(path.join(WEB, 'src/features/agent/generative-ui/renderer.tsx'), 'utf8');
  assert.match(renderer, /const older: 'choosing' \| 'kept' \| null = conflict\s*\? 'choosing'\s*: kept !== null && shown && incoming && incoming\.revision > shown\.revision/);
  assert.match(renderer, /onOlderRef\.current\?\.\(older\)/);
  const adapter = fs.readFileSync(path.join(WEB, 'src/features/agent/generative-ui/surfaces/renderer-adapter.tsx'), 'utf8');
  assert.match(adapter, /onOlderRevision=\{onOlderRevision\}/);
  const host = fs.readFileSync(path.join(WEB, 'src/features/agent/generative-ui/surfaces/artifact.tsx'), 'utf8');
  assert.match(host, /editAccess\(\{ access, accepted, live, older \}\)/);
  assert.match(host, /onOlderRevision=\{setOlder\}/);
  assert.match(host, /<EditView session=\{session\} view=\{view\} blocked=\{editNote\}/);
});

test('the edit field: localized chrome, live-selection chips in a labelled group of type="button" chips; rendering sends nothing', async () => {
  registry.enterUiScope('workspace:u6:w1');
  sessions.setActiveSessionScope('workspace:u6:w1');
  const t = transport('workspace:u6:w1', () => json(view()));
  const id = '3c1f2f3e-1111-4222-8333-944455556666';
  const session = sessions.sessionFor(t, id, 'c1');
  session.adopt(j01View(id));
  // Two drafts picked in this tab (saving is off for this person): the snapshot's @selection is still empty.
  session.stateController().recordSelection('$selectedDrafts', [{ type: 'draft', id: 'd1', title: 'Secret recital 2026' }, { type: 'draft', id: 'd2', title: 'Spring launch' }],
    [{ type: 'draft', id: 'd1' }, { type: 'draft', id: 'd2' }, { type: 'draft', id: 'd3' }]);
  assert.deepEqual(session.getState().view.artifact.safeState, {});
  assert.ok(await artifactView.preloadEditSuggestions(), 'the deriver loads on demand');
  const render = (props = {}) => renderToStaticMarkup(React.createElement(artifactView.EditView, { session, view: session.getState().view, blocked: null, onDone() {}, ...props }));
  const html = render();
  assert.match(html, /What should change\?/);
  assert.match(html, /placeholder="For example: add a chart, compare the selected two, show last month"/);
  assert.match(html, /Updating the view is billed separately\./);
  assert.match(html, /role="group" aria-labelledby="[^"]+" data-rafii-edit-suggestions=""/);
  assert.match(html, />Suggestions</);
  const chips = [...html.matchAll(/<button type="button" aria-pressed="false"[^>]*>([^<]+)<\/button>/g)].map((m) => m[1]);
  assert.deepEqual(chips, ['Compare the 2 selected', 'Needs review', 'Scheduled', 'Saved web sources'], 'the count is the live selection’s');
  assert.match(html, /pointer-coarse:min-h-11/, '44 px targets on a coarse pointer');
  assert.match(html, /whitespace-normal/);
  assert.doesNotMatch(html, /truncate/);
  assert.match(html, /motion-reduce:animate-none/);
  assert.match(html, /rafii-decorative-motion/, 'Rafii’s own reduced-motion setting stops the fade too');
  assert.match(html, /<button type="submit" disabled=""[^>]*>Update view<\/button>/, 'Update view is the only submit, off until there is text');
  assert.equal([...html.matchAll(/type="submit"/g)].length, 1);
  assert.doesNotMatch(html, /Secret recital|Spring launch|PRIVATE|drafts_list|RafiiRoot|Query\(/);
  assert.equal(t.calls.length, 0, 'opening the field and computing the chips make no request');

  // An older revision on screen: no chips, a note, and Update view stays off.
  const blocked = render({ blocked: 'newerVersion' });
  assert.doesNotMatch(blocked, /data-rafii-edit-suggestions/);
  assert.match(blocked, /A newer version is ready\. Use the updated view to change it\./);
  assert.match(render({ blocked: 'keptEarlier' }), /You kept the earlier view/);

  // Traditional Chinese (Hong Kong): the chrome and the chips follow the person's language.
  timePrefs.setTimeDefaults({ locale: 'zh-HK', timeZone: 'Asia/Hong_Kong' });
  try {
    const hk = render();
    assert.match(hk, /想改甚麼？/);
    assert.match(hk, /更新畫面/);
    assert.match(hk, />建議</);
    assert.match(hk, /比較已選的 2 項/);
    assert.match(hk, /需要審閱/);
  } finally {
    timePrefs.setTimeDefaults({ locale: 'en' });
  }
  assert.equal(t.calls.length, 0);
});

test('a chip is a type="button" QuietButton that only calls onPick (no request); the field then holds its instruction', () => {
  const suggestions = [{ id: 'filter:a', rule: 'filter', label: 'Only videos', instruction: 'Show only videos' }, { id: 'period:last7', rule: 'period', label: 'Last 7 days',
    instruction: 'Change the period to the last 7 days (2026-10-03 to 2026-10-09)' }];
  const picked = [];
  const t = transport('workspace:u7:w1', () => json(view()));
  const element = artifactView.SuggestionChips({ suggestions, pressed: 'period:last7', caption: 'Suggestions', captionId: 'cap', onPick: (s) => picked.push(s.id) });
  assert.equal(element.props.role, 'group');
  assert.equal(element.props['aria-labelledby'], 'cap');
  const buttons = element.props.children[1].props.children;
  assert.equal(buttons.length, 2);
  for (const button of buttons) assert.equal(button.type, frame.QuietButton, 'QuietButton is always type="button"');
  assert.deepEqual(buttons.map((b) => b.props.pressed), [false, true]);
  buttons[0].props.onClick();
  assert.deepEqual(picked, ['filter:a']);
  assert.equal(t.calls.length, 0);
  const html = renderToStaticMarkup(element);
  assert.equal([...html.matchAll(/<button type="button"/g)].length, 2);
  assert.match(html, /aria-pressed="true"[^>]*>Last 7 days</);
  assert.equal(artifactView.SuggestionChips({ suggestions: [], pressed: null, caption: 'x', captionId: 'y', onPick() {} }), null, 'no chips, no row');
  // A held Enter/Space repeats: the repeat is dropped (it would re-toggle), the first press is not.
  let prevented = 0;
  buttons[0].props.onKeyDown({ key: 'Enter', repeat: true, preventDefault: () => { prevented += 1; } });
  buttons[0].props.onKeyDown({ key: 'Enter', repeat: false, preventDefault: () => { prevented += 1; } });
  assert.equal(prevented, 1);

  // The field: a tap fills it (pressed), a second tap clears it, typing makes the words the person's own, "Restore my text".
  const { editFieldReducer, EMPTY_FIELD, canRestore } = editForm;
  const chip = { id: 'filter:a', rule: 'filter', instruction: 'Show only videos' };
  let field = editFieldReducer(EMPTY_FIELD, { type: 'type', text: 'my own words' });
  field = editFieldReducer(field, { type: 'pick', suggestion: chip });
  assert.deepEqual(field, { text: 'Show only videos', filled: chip, saved: 'my own words' });
  assert.equal(canRestore(field), true);
  const other = { id: 'period:last7', rule: 'period', instruction: 'Change the period to the last 7 days (2026-10-03 to 2026-10-09)' };
  field = editFieldReducer(field, { type: 'pick', suggestion: other });
  assert.equal(field.saved, 'my own words', 'switching chips keeps the person’s words, not the first chip’s');
  assert.deepEqual(editFieldReducer(field, { type: 'restore' }), { text: 'my own words', filled: null, saved: null });
  const cleared = editFieldReducer(field, { type: 'pick', suggestion: other });
  assert.deepEqual(cleared, { text: '', filled: null, saved: 'my own words' }, 'tapping the pressed chip again clears the field');
  assert.equal(editFieldReducer(field, { type: 'type', text: 'Show only videos!' }).filled, null, 'typing clears aria-pressed');
  assert.deepEqual(editFieldReducer(field, { type: 'unfill' }), { text: '', filled: null, saved: 'my own words' });
  assert.equal(canRestore(editFieldReducer(EMPTY_FIELD, { type: 'pick', suggestion: chip })), false, 'nothing of theirs to restore');
});

test('the live selection wins over the snapshot; the edit body keys stay exactly as validate_patch accepts', async () => {
  const local = { items: [{ type: 'draft', id: 'd1', title: 't' }, { type: 'draft', id: 'd2', title: 'u' }], listId: '$selectedDrafts' };
  const snapshot = { '@selection': { items: [{ type: 'draft', id: 'old', title: 'o' }] } };
  assert.equal(editForm.liveSelection(local, snapshot), local);
  assert.equal(editForm.liveSelection(null, snapshot), snapshot['@selection'], 'no controller yet: the snapshot');
  assert.equal(editForm.liveSelection(null, {}), null);
  assert.equal(editForm.liveSelection(['x'], {}), null);

  registry.enterUiScope('workspace:u8:w1');
  sessions.setActiveSessionScope('workspace:u8:w1');
  const id = '4c1f2f3e-1111-4222-8333-944455556666';
  const t = transport('workspace:u8:w1', (p, init) => (init.method === 'POST' ? json({ view: j01View(id) }) : json(j01View(id))));
  const session = sessions.sessionFor(t, id, 'c1');
  session.adopt(j01View(id));
  const controller = session.stateController();
  let told = 0;
  const stop = controller.subscribeSelection(() => { told += 1; });
  controller.recordSelection('$selectedDrafts', local.items, local.items);
  assert.equal(told, 1, 'a pick tells the edit field (chip counts follow it)');
  controller.recordSelection('$selectedDrafts', local.items, local.items);
  assert.equal(told, 1, 'the same pick again changes nothing');
  stop();
  const result = await session.edit('Compare only the 2 selected drafts', editForm.liveSelection(controller.selection(), session.getState().view.artifact.safeState));
  await flush();
  assert.deepEqual(result, { ok: true });
  const posts = t.calls.filter((c) => c.method === 'POST');
  assert.equal(posts.length, 1);
  assert.ok(posts[0].p.endsWith(`/presentations/${id}/edits`));
  assert.deepEqual(Object.keys(posts[0].body).sort(), ['baseRevision', 'baseSourceHash', 'idempotencyKey', 'instruction', 'selection'], 'no origin/source/suggestion field');
  assert.deepEqual(posts[0].body.selection.items.map((i) => i.id), ['d1', 'd2'], 'the selection the person sees');
  assert.equal(posts[0].body.instruction, 'Compare only the 2 selected drafts');
  const typed = await session.edit('add a chart', null);
  await flush();
  assert.deepEqual(typed, { ok: true });
  assert.deepEqual(Object.keys(t.calls.filter((c) => c.method === 'POST')[1].body).sort(), ['baseRevision', 'baseSourceHash', 'idempotencyKey', 'instruction']);
});

test('refusals read honestly: budget, paused AI, not the asker, busy, conflict — never the generic message for those', () => {
  const of = editForm.editProblemOf;
  assert.equal(of({ code: 'ui_budget', status: 402 }), 'editBudget');
  assert.equal(of({ code: 'ui_budget_unknown', status: 402 }), 'editBudgetUnknown');
  assert.equal(of({ code: null, status: 402 }), 'editBudget');
  assert.equal(of({ code: 'ui_ai_paused', status: 503 }), 'editPaused');
  assert.equal(of({ code: 'ui_forbidden', status: 403 }), 'editNotActor');
  assert.equal(of({ code: 'ui_busy', status: 409 }), 'editBusy');
  assert.equal(of({ code: 'ui_revision_conflict', status: 409 }), 'editConflict');
  assert.equal(of({ code: null, status: 404 }), 'editUnavailable');
  assert.equal(of({ code: 'ui_price_unknown', status: 503 }), 'editFailed');
  assert.equal(of({ code: 'internal', status: 500 }), 'editFailed');
  assert.equal(of({ code: 'ui_in_flight', status: 0 }), null, 'a second press while the first is in flight says nothing');
  const en = genLocale.createGenUiLocale({ locale: 'en' });
  const hk = genLocale.createGenUiLocale({ locale: 'zh-HK' });
  for (const key of ['editBudget', 'editBudgetUnknown', 'editPaused']) {
    assert.notEqual(en.t(key), en.t('editFailed'));
    assert.match(en.t(key), /Nothing was charged/);
    assert.match(hk.t(key), /未有收費/);
  }
  assert.equal(en.t('editConflict'), 'This view changed since you looked at it. The latest version is shown; ask again.', 'existing English kept');
  assert.equal(en.t('editFailed'), 'That change couldn’t be started. The current view is kept.');
  const host = fs.readFileSync(path.join(WEB, 'src/features/agent/generative-ui/surfaces/artifact.tsx'), 'utf8');
  assert.match(host, /setProblem\(editProblemOf\(result\)\)/);
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
