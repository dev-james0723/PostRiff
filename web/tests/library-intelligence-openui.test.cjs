/**
 * Rafii Intelligent Library — T10 safe task-specific OpenUI components (UI spec §7–8; A067–A070).
 *
 * Real logic from src/lib/library/openui-policy.ts (no imports) and openui-schemas.ts (zod only), transpiled on their
 * own like media-libs.test.cjs, plus source assertions on the descriptors, adapter and fallback surface.
 *
 *   node --test web/tests/library-intelligence-openui.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.join(__dirname, '..', 'src');
const LIB = path.join(SRC, 'lib', 'library');
const OPENUI = path.join(SRC, 'features', 'library', 'intelligence', 'openui');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(source, /from '@\//, `${path.basename(file)} must not use @/ imports (plain node --test transpile)`);
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const P = load(path.join(LIB, 'openui-policy.ts'));
const S = load(path.join(LIB, 'openui-schemas.ts'));
const parse = S.parseLibraryProps;
const read = (file) => fs.readFileSync(path.join(OPENUI, file), 'utf8');

const KEY = 'a'.repeat(32);
const KEY2 = 'b'.repeat(32);
const FOREIGN = 'f'.repeat(32);
const SHA = 'c'.repeat(64);
const ref = (assetId = KEY, versionId = assetId) => ({ assetId, versionId, sha256: SHA });
const candidate = (assetId = KEY, title = 'Brahms notes') => ({
  component: 'AssetCandidateCard',
  props: { assetRef: ref(assetId), title, kind: 'document', mime: 'text/markdown', snippet: 'Pedalling in bar 12', locatorLabel: 'Page 2', matchReasons: ['Exact phrase'] }
});
const envelope = (overrides = {}) => ({ actionId: 'save-1', uiInstanceId: 'task-1', actionType: 'collection.save', targetRefs: [ref(KEY)], expectedRevision: 4, payload: {}, ...overrides });
const proposal = (overrides = {}) => ({
  name: 'Recital',
  ruleSummary: 'Documents tagged recital',
  before: [{ assetRef: ref(KEY), title: 'Programme' }],
  after: [{ assetRef: ref(KEY), title: 'Programme' }, { assetRef: ref(KEY2), title: 'Budget' }],
  effect: 'Saves the rule. Files are referenced, not copied.',
  actions: [{ label: 'Save collection', effect: 'Creates the collection with these members.', envelope: envelope(overrides) }]
});
const pack = (overrides = {}) => ({
  packId: KEY,
  revision: 2,
  goal: 'Spring recital post',
  evidence: [{ sourceRef: { assetRef: ref(KEY) }, title: 'Programme', rationale: 'Dates and pieces', rights: 'internal' }],
  style: [{ sourceRef: { assetRef: ref(KEY2) }, title: 'My old post', rationale: 'Your own writing' }],
  gaps: ['No photo of the hall'],
  rightsWarnings: [],
  actions: [{ label: 'Save pack', effect: 'Keeps this pack for drafting.', envelope: envelope({ actionId: 'pack-1', actionType: 'source_pack.create', ...overrides }) }]
});
const comparison = () => ({
  title: 'Programme',
  before: { ref: ref(KEY, KEY), versionNo: 1, createdAt: 1700000000, current: false, approved: true },
  after: { ref: ref(KEY, KEY2), versionNo: 2, createdAt: 1700500000, current: true, approved: null },
  differences: [{ field: 'Date', before: '3 May', after: '10 May' }],
  affectedDrafts: 1,
  actions: []
});
const scopeProps = { kind: 'workspace', selectedCount: 0 };

function recorder(result = { status: 'applied', warnings: [] }) {
  const sent = [];
  let made = 0;
  const dispatcher = P.createLibraryDispatcher({
    send: async (sentEnvelope) => {
      sent.push(sentEnvelope);
      return typeof result === 'function' ? result(sentEnvelope, sent.length) : result;
    },
    newKey: () => `lib-ui-${++made}-0000000000000000`,
    readOnlyTypes: S.READ_ONLY_ACTION_TYPES
  });
  return { dispatcher, sent };
}

function issuedFrom(nodes) {
  const tree = P.validateTaskTree(nodes, parse);
  assert.ok(tree.ok, JSON.stringify(tree.errors));
  return { tree, refs: P.collectServerRefs(tree.nodes), issued: P.collectIssuedActions(tree.nodes) };
}

const live = { userActivation: true, phase: 'live' };

test('test_unknown_component_rejected: only the nine allowlisted components with strict, plain-text props render', () => {
  assert.deepEqual(S.LIBRARY_OPENUI_NAMES, ['AssetCandidateCard', 'SourceCitation', 'SourceScope', 'VersionComparison', 'CollectionProposal', 'SourcePackReview', 'DraftWorkspace', 'ProcessingStatus', 'SuggestionReview']);
  assert.equal(parse('ScriptRunner', {}), null, 'unknown component → null');
  assert.equal(parse('constructor', {}), null, 'no prototype names');
  const mixed = P.validateTaskTree([candidate(), { component: 'IFrame', props: { src: 'https://example.org' } }], parse);
  assert.equal(mixed.ok, false);
  assert.deepEqual(mixed.nodes, [], 'one unknown component invalidates the whole result');
  assert.match(mixed.errors.join(' '), /Unknown component “IFrame”/);

  const props = candidate().props;
  assert.equal(parse('AssetCandidateCard', props).ok, true);
  assert.equal(parse('AssetCandidateCard', { ...props, onClick: 'alert(1)' }).ok, false, 'strict: no extra props');
  assert.equal(parse('AssetCandidateCard', { ...props, title: '<img src=x onerror=alert(1)>' }).ok, false, 'no markup');
  assert.equal(parse('AssetCandidateCard', { ...props, snippet: 'see https://evil.example' }).ok, false, 'no links');
  assert.equal(parse('AssetCandidateCard', { ...props, assetRef: { assetId: 'not-a-key', versionId: '', sha256: '' } }).ok, false, 'server-issued keys only');

  // Positional props: stable key order, required before optional.
  assert.deepEqual(Object.keys(S.AssetCandidateCardSchema.shape), ['assetRef', 'title', 'kind', 'mime', 'snippet', 'locatorLabel', 'matchReasons']);
  for (const name of S.LIBRARY_OPENUI_NAMES) {
    const shape = S.LIBRARY_OPENUI_SCHEMAS[name].schema.shape;
    const optional = Object.keys(shape).map((key) => shape[key].safeParse(undefined).success);
    assert.ok(optional.every((value, index) => !optional.slice(0, index).includes(true) || value), `${name}: required props come first`);
  }

  const descriptors = read('descriptors.ts');
  assert.match(descriptors, /export const LIBRARY_OPENUI_DESCRIPTORS/);
  for (const name of S.LIBRARY_OPENUI_NAMES) assert.match(descriptors, new RegExp(`describe\\('${name}', ${name}\\)`), name);
  assert.match(descriptors, /propsSchema: entry\.schema/);
  assert.match(descriptors, /actions: entry\.actions/);
  for (const file of ['descriptors.ts', 'components.tsx', 'action-adapter.ts', 'error-boundary.tsx']) assert.doesNotMatch(read(file), /@openuidev/, `${file}: no OpenUI dependency of our own`);
  assert.doesNotMatch(fs.readFileSync(path.join(LIB, 'openui-schemas.ts'), 'utf8'), /@openuidev/);
});

test('test_forged_target_denied: only refs and actions issued in this result can be acted on', async () => {
  const { refs, issued } = issuedFrom([{ component: 'CollectionProposal', props: proposal() }]);
  assert.ok(refs.has(`${KEY}:${KEY}`) && refs.has(`${KEY2}:${KEY2}`));
  const save = issued.get('save-1');
  assert.ok(save);

  const { dispatcher, sent } = recorder();
  const forged = await dispatcher.dispatch({ ...save, targetRefs: [ref(FOREIGN)] }, { token: dispatcher.activate(live).token, serverRefs: refs });
  assert.equal(forged.status, 'denied');
  assert.equal(forged.local, true);
  assert.equal(sent.length, 0, 'refused before anything is sent');

  const ok = await dispatcher.dispatch(save, { token: dispatcher.activate(live).token, serverRefs: refs });
  assert.equal(ok.status, 'applied');
  assert.equal(sent.length, 1);
  assert.match(sent[0].idempotencyKey, /^[A-Za-z0-9_.:-]{16,120}$/);

  // Payloads and approving actions are refused by the schema, before any control exists.
  assert.equal(parse('CollectionProposal', proposal({ payload: { note: 'https://evil.example' } })).ok, false, 'no URLs');
  assert.equal(parse('CollectionProposal', proposal({ payload: { q: 'select * from pr_workspaces' } })).ok, false, 'no SQL');
  assert.equal(parse('CollectionProposal', proposal({ actionType: 'voice.revoke' })).ok, false, 'only the actions this component may offer');
  assert.equal(parse('SourcePackReview', pack({ payload: { approveRights: true } })).ok, false, 'a source pack cannot approve rights');
  assert.equal(parse('SourcePackReview', pack()).ok, true);

  const adapter = read('action-adapter.ts');
  assert.match(adapter, /issued\.get\(inputs\.actionId\)/, 'a control names an issued envelope, never builds one');
  assert.match(adapter, /envelope\.actionType !== actionId/);
  assert.match(adapter, /!serverRefs\.has\(refKey\(ref\)\)/, 'select/open accept issued refs only');
});

test('test_hydration_no_mutation: no write without a fresh press on a finished, live result', async () => {
  const { refs, issued } = issuedFrom([{ component: 'CollectionProposal', props: proposal() }]);
  const save = issued.get('save-1');
  const { dispatcher, sent } = recorder();
  assert.deepEqual(dispatcher.activate({ userActivation: true, phase: 'hydrating' }), { ok: false, reason: 'hydration' });
  assert.deepEqual(dispatcher.activate({ userActivation: true, phase: 'replaying' }), { ok: false, reason: 'replay' });
  assert.deepEqual(dispatcher.activate({ userActivation: true, phase: 'streaming' }), { ok: false, reason: 'streaming' });
  assert.deepEqual(dispatcher.activate({ userActivation: false, phase: 'live' }), { ok: false, reason: 'no-user-activation' });
  assert.equal((await dispatcher.dispatch(save, { token: null, serverRefs: refs })).status, 'refused');
  assert.equal(sent.length, 0);

  const token = dispatcher.activate(live).token;
  assert.equal((await dispatcher.dispatch(save, { token, serverRefs: refs })).status, 'applied');
  assert.equal((await dispatcher.dispatch(save, { token, serverRefs: refs })).status, 'refused', 'one press, one mutation');
  assert.equal(sent.length, 1);

  const base = P.initialSurfaceState({ kind: 'workspace' });
  assert.equal(P.surfacePhase({ ...base, status: 'complete' }, { hydrated: false, replay: false }), 'hydrating');
  assert.equal(P.surfacePhase({ ...base, status: 'complete' }, { hydrated: true, replay: true }), 'replaying');
  assert.equal(P.surfacePhase({ ...base, status: 'streaming' }, { hydrated: true, replay: false }), 'streaming');
  assert.equal(P.surfacePhase({ ...base, status: 'complete' }, { hydrated: true, replay: false }), 'live');

  // Components only call onAction from presses: no effects in the task components at all.
  assert.doesNotMatch(read('components.tsx'), /useEffect|useLayoutEffect/);
  const surface = read('error-boundary.tsx');
  for (const line of surface.split('\n').filter((entry) => entry.includes('onAction('))) assert.match(line, /onClick=\{\(\) => onAction\(/, 'the surface raises an action only from a press');
  assert.match(read('action-adapter.ts'), /if \(event\.isTrusted\) lastTrustedPress\.current = Date\.now\(\)/, 'synthetic events do not count as a press');
});

test('test_stale_revision_conflict: stale or conflicting writes are surfaced, never retried automatically', async () => {
  const { refs, issued } = issuedFrom([{ component: 'CollectionProposal', props: proposal() }]);
  const save = issued.get('save-1');

  const local = recorder();
  const stale = await local.dispatcher.dispatch(save, { token: local.dispatcher.activate(live).token, serverRefs: refs, knownRevision: 7 });
  assert.equal(stale.status, 'conflict');
  assert.equal(stale.local, true);
  assert.equal(local.sent.length, 0);

  const server = recorder({ status: 'conflict', warnings: ['This source version changed. Refresh before using it.'] });
  const token = server.dispatcher.activate(live).token;
  const conflict = await server.dispatcher.dispatch(save, { token, serverRefs: refs, knownRevision: 4 });
  assert.deepEqual(conflict, { status: 'conflict', message: 'This source version changed. Refresh before using it.', retryable: false });
  assert.equal((await server.dispatcher.dispatch(save, { token, serverRefs: refs, retry: true })).status, 'refused', 'a conflict is not retried');
  assert.equal(server.sent.length, 1);

  const flaky = recorder((_, call) => {
    if (call === 1) throw new Error('network');
    return { status: 'applied', warnings: [] };
  });
  const press = flaky.dispatcher.activate(live).token;
  const failed = await flaky.dispatcher.dispatch(save, { token: press, serverRefs: refs });
  assert.equal(failed.status, 'failed');
  assert.equal(flaky.sent.length, 1, 'no automatic retry');
  assert.equal((await flaky.dispatcher.dispatch(save, { token: press, serverRefs: refs, retry: true })).status, 'applied');
  assert.equal(flaky.sent[1].idempotencyKey, flaky.sent[0].idempotencyKey, 'an explicit retry of the same press reuses its key');
  await flaky.dispatcher.dispatch(save, { token: flaky.dispatcher.activate(live).token, serverRefs: refs });
  assert.notEqual(flaky.sent[2].idempotencyKey, flaky.sent[0].idempotencyKey, 'a new press gets a new key');

  assert.equal(P.outcomeFromResult({ status: 'requires_confirmation', warnings: [] }).status, 'requires_confirmation');
  assert.equal(P.outcomeFromResult({ status: 'denied', warnings: [] }).message, 'Not allowed for your role or these items.');
  assert.equal(P.outcomeFromResult({ status: 'applied', replayed: true, warnings: [] }).message, 'Already done');

  // One mutation at a time.
  let release;
  const gate = new Promise((resolve) => (release = resolve));
  const slow = recorder(async () => {
    await gate;
    return { status: 'applied', warnings: [] };
  });
  const first = slow.dispatcher.dispatch(save, { token: slow.dispatcher.activate(live).token, serverRefs: refs });
  const second = await slow.dispatcher.dispatch(save, { token: slow.dispatcher.activate(live).token, serverRefs: refs });
  assert.equal(second.status, 'busy');
  release();
  assert.equal((await first).status, 'applied');
  assert.equal(slow.sent.length, 1);
});

test('test_one_repair_only: one parser repair, then an honest error', () => {
  assert.equal(P.OPENUI_LIMITS.maxRepairs, 1);
  assert.equal(P.OPENUI_LIMITS.automaticMutationRetry, false);
  let state = P.initialSurfaceState({ kind: 'workspace' }, [KEY]);
  state = P.applyStreamFrame(state, { parseError: true, final: false }, parse);
  assert.equal(state.status, 'repairing');
  assert.equal(P.canRepair(state), true);
  state = P.applyStreamFrame(state, { parseError: true, final: false }, parse);
  assert.equal(state.status, 'error');
  assert.equal(state.repairs, 1);
  assert.equal(P.canRepair(state), false);
  assert.deepEqual(state.selection, [KEY]);
  assert.match(read('error-boundary.tsx'), /const repairing = canRepair\(state\);/);
});

test('test_component_depth_cap: 100 components, depth 12, 5 reads per cycle', async () => {
  const nest = (depth) => {
    let node = { component: 'SourceScope', props: scopeProps };
    for (let level = 1; level < depth; level += 1) node = { component: 'SourceScope', props: scopeProps, children: [node] };
    return node;
  };
  assert.equal(P.validateTaskTree(nest(12), parse).ok, true);
  const deep = P.validateTaskTree(nest(13), parse);
  assert.equal(deep.ok, false);
  assert.match(deep.errors.join(' '), /deeper than 12/);
  assert.deepEqual(deep.nodes, [], 'never silently truncated');
  assert.equal(P.validateTaskTree(Array.from({ length: 100 }, () => ({ component: 'SourceScope', props: scopeProps })), parse).ok, true);
  const many = P.validateTaskTree(Array.from({ length: 101 }, () => ({ component: 'SourceScope', props: scopeProps })), parse);
  assert.equal(many.ok, false);
  assert.match(many.errors.join(' '), /More than 100 components/);

  const budget = P.createReadBudget();
  assert.deepEqual(Array.from({ length: 6 }, () => budget.take()), [true, true, true, true, true, false]);
  budget.reset();
  assert.equal(budget.take(), true);

  const { refs } = issuedFrom([candidate()]);
  const { dispatcher, sent } = recorder({ status: 'applied', warnings: [] });
  const reads = P.createReadBudget();
  const lookup = envelope({ actionId: 'lookup-1', actionType: 'sources.select' });
  const results = [];
  for (let index = 0; index < 6; index += 1) results.push((await dispatcher.dispatch(lookup, { token: null, serverRefs: refs, readBudget: reads })).status);
  assert.deepEqual(results, ['applied', 'applied', 'applied', 'applied', 'applied', 'refused']);
  assert.equal(sent.length, 5);
});

test('test_partial_stream_preserves_selection: frames never reset scope, selection or drafts', () => {
  const scope = { kind: 'collection', collectionId: KEY };
  let state = P.initialSurfaceState(scope, [KEY, KEY2]);
  state = P.applyStreamFrame(state, { nodes: [candidate(KEY)], final: false }, parse);
  assert.equal(state.status, 'streaming');
  assert.deepEqual(state.selection, [KEY, KEY2], 'an item missing from a partial frame stays selected');
  assert.deepEqual(state.scope, scope);
  state = { ...state, drafts: { 'draft:Post': 'My own edit' } };
  state = P.applyStreamFrame(state, { nodes: [{ component: 'Unknown' }], final: false }, parse);
  assert.equal(state.status, 'error');
  assert.equal(state.nodes.length, 1, 'the last valid result stays for the fallback');
  assert.deepEqual(state.selection, [KEY, KEY2]);
  assert.deepEqual(state.drafts, { 'draft:Post': 'My own edit' });
  state = P.applyStreamFrame(state, { nodes: [candidate(KEY), candidate(KEY2, 'Budget')], final: true }, parse);
  assert.equal(state.status, 'complete');
  assert.deepEqual(state.selection, [KEY, KEY2]);
  assert.deepEqual(state.drafts, { 'draft:Post': 'My own edit' });
  assert.deepEqual(P.keepSelection([KEY], undefined), [KEY]);

  const surface = read('error-boundary.tsx');
  assert.match(surface, /selection: readonly string\[\];/, 'selection is the host’s, passed in');
  assert.match(surface, /onSelectionChange\(on \? \[\.\.\.rest, ref\.assetId\] : rest\)/);
  assert.match(surface, /draft: \(key, initial\) => state\.drafts\[key\] \?\? initial/);
});

test('test_fallback_browsing_works: the same validated data renders without OpenUI, and the Library never depends on it', () => {
  const tree = P.validateTaskTree([candidate(KEY), { component: 'SourcePackReview', props: pack() }, { component: 'VersionComparison', props: comparison() }], parse);
  assert.ok(tree.ok, JSON.stringify(tree.errors));
  const items = P.fallbackItems(tree.nodes);
  const titles = items.map((item) => item.title);
  assert.ok(titles.includes('Brahms notes'));
  assert.ok(titles.includes('My old post'));
  assert.ok(titles.some((title) => /newer version/.test(title)), 'each compared version stays reachable');
  assert.equal(new Set(items.map((item) => `${item.ref.assetId}:${item.ref.versionId}`)).size, items.length, 'each item once');
  assert.equal(parse('VersionComparison', { ...comparison(), after: { ...comparison().after, ref: ref(KEY, KEY) } }).ok, false, 'a comparison names two versions');

  const surface = read('error-boundary.tsx');
  assert.match(surface, /static getDerivedStateFromError\(\)/);
  assert.match(surface, /fallback=\{deterministic\}/, 'a renderer failure shows the deterministic view');
  assert.match(surface, /fallback=\{<PlainItems nodes=\{\[node\]\} onAction=\{onAction\} \/>\}/, 'one failing part falls back on its own');
  assert.match(surface, /Renderer && !rendererFailed \?/);
  assert.match(surface, /\) : \(\s*deterministic\s*\)/, 'no renderer mounted → deterministic view');
  const view = fs.readFileSync(path.join(SRC, 'features', 'library', 'library-view.tsx'), 'utf8');
  assert.doesNotMatch(view, /openui|LibraryTaskSurface/i, 'the deterministic Library shell never depends on generated UI');
});
