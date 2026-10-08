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

/** A press as the gate sees it: trusted or not, on the control naming `actionId`, inside the node at `owner`. */
function press(actionId, { owner = '0', trusted = true, control = actionId } = {}) {
  const node = { getAttribute: (name) => (name === 'data-task-node' ? owner : null), closest: () => null };
  const target = { getAttribute: (name) => (name === 'data-library-action' ? control : null), closest: (selector) => (selector === '[data-task-node]' ? node : null) };
  return { isTrusted: trusted, currentTarget: target };
}
const live = { event: press('save-1'), actionId: 'save-1', owner: '0', phase: 'live' };

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
  assert.deepEqual(dispatcher.activate({ ...live, phase: 'hydrating' }), { ok: false, reason: 'hydration' });
  assert.deepEqual(dispatcher.activate({ ...live, phase: 'replaying' }), { ok: false, reason: 'replay' });
  assert.deepEqual(dispatcher.activate({ ...live, phase: 'streaming' }), { ok: false, reason: 'streaming' });
  assert.deepEqual(dispatcher.activate({ ...live, event: press('save-1', { trusted: false }) }), { ok: false, reason: 'no-user-activation' });
  assert.deepEqual(dispatcher.activate({ ...live, event: null }), { ok: false, reason: 'no-user-activation' });
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
  for (const line of surface.split('\n').filter((entry) => entry.includes('onAction('))) assert.match(line, /onClick=\{\(event\) => onAction\(/, 'the surface raises an action only from a press, and passes it');
  assert.doesNotMatch(read('action-adapter.ts'), /navigator\.userActivation|lastTrustedPress|addEventListener/, 'no page-wide "recent press" counts as activation');
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
  assert.match(surface, /Renderer && generated && !rendererFailed \?/);
  assert.match(surface, /\) : \(\s*deterministic\s*\)/, 'no renderer mounted → deterministic view');
  const view = fs.readFileSync(path.join(SRC, 'features', 'library', 'library-view.tsx'), 'utf8');
  assert.doesNotMatch(view, /openui|LibraryTaskSurface/i, 'the deterministic Library shell never depends on generated UI');
});

test('runtime action ids: library_ plus the type in snake case, within the manifest pattern', () => {
  assert.equal(P.manifestActionId('collection.save'), 'library_collection_save');
  assert.equal(P.manifestActionId('version.accept_replacement'), 'library_version_accept_replacement');
  for (const type of S.LIBRARY_ACTION_TYPES) assert.match(P.manifestActionId(type), P.MANIFEST_ACTION_ID, type);
  assert.equal(new Set(S.LIBRARY_ACTION_TYPES.map(P.manifestActionId)).size, S.LIBRARY_ACTION_TYPES.length, 'no two types share an id');
  const descriptors = read('descriptors.ts');
  assert.match(descriptors, /export const LIBRARY_OPENUI_ACTION_IDS/);
  assert.match(descriptors, /LIBRARY_ACTION_TYPES\.map\(\(type\) => \[type, manifestActionId\(type\)\]\)/);
  assert.match(descriptors, /actions: entry\.actions/, 'descriptors keep their dotted action types');
});

test('test_missing_on_action_renders_unavailable: without an injected handler, controls are disabled and inert', () => {
  const none = P.resolveActionHandler(undefined);
  assert.equal(none.available, false);
  assert.doesNotThrow(() => none.call('library.open', {}));
  assert.equal(P.resolveActionHandler(null).available, false);
  const calls = [];
  const some = P.resolveActionHandler((id, inputs) => calls.push([id, inputs]));
  assert.equal(some.available, true);
  some.call('library.select', { a: 1 });
  assert.deepEqual(calls, [['library.select', { a: 1 }]]);
  const withEvent = [];
  const event = press('x');
  P.resolveActionHandler((id, inputs, pressed) => withEvent.push(pressed)).call('library.open', {}, event);
  assert.equal(withEvent[0], event, 'the press travels with the call');

  const components = read('components.tsx');
  assert.match(components, /onAction\?: LibraryOnAction \| null;/, 'the handler is optional for the runtime bridge');
  const declared = components.split('\n').filter((line) => /^export function [A-Z]\w+\(\{[^}]*\bonAction\b/.test(line)).length;
  const resolved = (components.match(/const act = resolveActionHandler\(onAction\);/g) || []).length;
  assert.equal(resolved, declared, 'every component with controls resolves its handler');
  assert.equal(declared, 8, 'all components but SourceScope have controls');
  assert.doesNotMatch(components, /\bonAction\(/, 'no component calls the raw handler');
  assert.match(components, /disabled=\{!act\.available \|\| !host\.writesEnabled \|\| host\.busyActionId !== null \|\| control\.disabled/);
  assert.match(components, /disabled=\{!act\.available\} onClick=\{\(event\) => act\.call\('library\.open'/);
  assert.match(components, /Actions aren’t available in this view\./);
  assert.doesNotMatch(components, /useLibraryActionAdapter/, 'inside generated UI only the injected onAction is used');
});


test('activation is tied to the control: a trusted press on that action’s own button, inside the component that owns it', async () => {
  const proposalNode = { component: 'CollectionProposal', props: proposal() };
  const { tree, refs, issued } = issuedFrom([candidate(KEY), proposalNode]);
  const owners = P.collectIssuedOwners(tree.nodes);
  assert.equal(owners.get('save-1'), '1', 'the action belongs to the node that offered it');
  const save = issued.get('save-1');

  assert.deepEqual(P.checkActivation(press('save-1', { owner: '1' }), 'save-1', '1'), { ok: true });
  assert.deepEqual(P.checkActivation(press('save-1', { owner: '1', trusted: false }), 'save-1', '1'), { ok: false, reason: 'no-user-activation' }, 'synthetic events never count');
  assert.deepEqual(P.checkActivation(undefined, 'save-1', '1'), { ok: false, reason: 'no-user-activation' }, 'a call without its press is refused');
  assert.deepEqual(P.checkActivation(press('save-1', { owner: '0' }), 'save-1', '1'), { ok: false, reason: 'not-owner' }, 'a press inside another component does not count');
  assert.deepEqual(P.checkActivation(press('open-1', { owner: '1', control: 'open-1' }), 'save-1', '1'), { ok: false, reason: 'not-owner' }, 'a press on another control does not count');
  assert.deepEqual(P.checkActivation({ isTrusted: true, currentTarget: {} }, 'save-1', '1'), { ok: false, reason: 'not-owner' });

  const { dispatcher, sent } = recorder();
  const elsewhere = dispatcher.activate({ event: press('save-1', { owner: '0' }), actionId: 'save-1', owner: owners.get('save-1'), phase: 'live' });
  assert.deepEqual(elsewhere, { ok: false, reason: 'not-owner' });
  const ok = dispatcher.activate({ event: press('save-1', { owner: '1' }), actionId: 'save-1', owner: owners.get('save-1'), phase: 'live' });
  assert.equal(ok.ok, true);
  assert.equal((await dispatcher.dispatch(save, { token: ok.token, serverRefs: refs })).status, 'applied');
  assert.equal(sent.length, 1);

  const adapter = read('action-adapter.ts');
  assert.match(adapter, /dispatcher\.activate\(\{ event, actionId: envelope\.actionId, owner: owners\.get\(envelope\.actionId\), phase \}\)/);
  assert.match(adapter, /if \(!checkActivation\(event, actionId, owners\.get\(actionId\)\)\.ok\)/, 'Retry needs the same kind of press');
  const surface = read('error-boundary.tsx');
  assert.match(surface, /data-task-node=\{node\.path\}/, 'each rendered node names its path');
  const components = read('components.tsx');
  assert.match(components, /data-library-action=\{actionId\}/, 'each write control names its action');
  assert.match(components, /act\.call\(actionType, \{ actionId \}, event\)/, 'the press is passed with the call');
  assert.equal(P.ACTION_ATTRIBUTE, 'data-library-action');
  assert.equal(P.NODE_ATTRIBUTE, 'data-task-node');
});

test('labels come from the action type: generated text can only describe, never front a write', () => {
  const sneaky = proposal();
  sneaky.actions[0].label = 'Preview';
  assert.equal(parse('CollectionProposal', sneaky).ok, true, 'a generated label is allowed as text…');
  assert.equal(P.actionLabel(sneaky.actions[0].envelope.actionType, sneaky.actions[0].envelope.payload), 'Save collection', '…but the button says what the action does');
  assert.equal(P.actionLabel('collection.override', { mode: 'include' }), 'Include');
  assert.equal(P.actionLabel('collection.override', { mode: 'exclude' }), 'Exclude');
  assert.equal(P.actionLabel('collection.override', {}), 'Include/Exclude');
  assert.equal(P.actionLabel('suggestion.set_state', { state: 'dismissed' }), 'Dismiss');
  assert.equal(P.actionLabel('suggestion.set_state', { state: 'Delete everything' }), 'Update suggestion', 'only known payload values refine a label');
  assert.equal(P.actionLabel('voice.revoke'), 'Remove voice example');
  assert.equal(P.actionLabel('nope.unknown'), 'Unavailable action');
  for (const type of S.LIBRARY_ACTION_TYPES) assert.ok(P.ACTION_LABELS[type], `${type} has a fixed label`);
  const components = read('components.tsx');
  assert.match(components, /const label = actionLabel\(actionType, payload\);/);
  assert.match(components, /\{control\.mode === 'retry' \? 'Retry' : label\}/, 'the visible label is the fixed one');
  assert.match(components, /\{action\.label !== label \? `\$\{action\.label\} · ` : ''\}/, 'a differing generated label is only part of the description');
  assert.doesNotMatch(components, /\n\s*\{action\.label\}\n/, 'never the generated label as button text');
});

test('a failed write becomes Retry with the same press and key; an applied one is done', async () => {
  assert.deepEqual(P.actionControl(undefined), { mode: 'act', disabled: false });
  assert.deepEqual(P.actionControl({ status: 'failed', retryable: true }), { mode: 'retry', disabled: false });
  assert.deepEqual(P.actionControl({ status: 'failed', retryable: false }), { mode: 'blocked', disabled: true });
  assert.deepEqual(P.actionControl({ status: 'applied' }), { mode: 'done', disabled: true });
  for (const status of ['conflict', 'denied', 'requires_confirmation']) assert.deepEqual(P.actionControl({ status }), { mode: 'blocked', disabled: true }, status);
  assert.deepEqual(P.actionControl({ status: 'refused' }), { mode: 'act', disabled: false }, 'nothing was sent: the press can be made again');

  // A save that committed while its answer was lost: Retry re-sends the same activation, so the server replays it.
  const { refs, issued } = issuedFrom([{ component: 'CollectionProposal', props: proposal() }]);
  const save = issued.get('save-1');
  const committed = new Map();
  const lossy = recorder((envelope, call) => {
    if (!committed.has(envelope.idempotencyKey)) committed.set(envelope.idempotencyKey, true);
    else return { status: 'applied', replayed: true, warnings: [] };
    if (call === 1) throw new Error('The connection dropped.');
    return { status: 'applied', warnings: [] };
  });
  const token = lossy.dispatcher.activate(live).token;
  const lost = await lossy.dispatcher.dispatch(save, { token, serverRefs: refs });
  assert.deepEqual([lost.status, lost.retryable], ['failed', true]);
  assert.equal(P.actionControl(lost).mode, 'retry');
  const again = await lossy.dispatcher.dispatch(save, { token, serverRefs: refs, retry: true });
  assert.deepEqual([again.status, again.replayed], ['applied', true], 'answered from the receipt, not applied twice');
  assert.equal(committed.size, 1, 'one key, one write');
  assert.equal(P.actionControl(again).mode, 'done');
  assert.equal((await lossy.dispatcher.dispatch(save, { token, serverRefs: refs })).status, 'refused', 'a used press cannot write again');

  const components = read('components.tsx');
  assert.match(components, /control\.mode === 'retry' \? host\.retry\?\.\(actionId, event\)/, 'the control turns into Retry');
  assert.match(read('error-boundary.tsx'), /retry: adapter\.retry,/, 'the surface wires Retry to the same activation');
  assert.match(read('action-adapter.ts'), /void dispatchLibraryAction\(envelope, token, true\);/);
});
