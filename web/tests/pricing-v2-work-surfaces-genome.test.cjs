/* eslint-disable no-underscore-dangle -- Source-bound synthetic callers use Node Module compilation. */
// Synthetic Node fixtures only: no browser, server, provider or database execution.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
global.fetch = () => { throw new Error('Network is forbidden in these synthetic fixtures'); };

function load(relative, mocks = {}) {
  const file = path.resolve(__dirname, '../src', relative), m = new Module(file);
  m.paths = module.paths;
  m.require = id => Object.hasOwn(mocks, id) ? mocks[id] : require(id);
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
  }).outputText, file);
  return m.exports;
}
const managed = { billingMode: 'managed_credits', freePreview: null };
const free = (remaining = 1, eligible = true) => ({ billingMode: 'free_preview', freePreview: {
  genome: { remaining, eligible, reason: eligible ? null : 'funding_unavailable', maxPosts: 20 }
} });
const readyCatalog = (billingMode = 'managed_credits') => ({ genome: true, consented: true,
  baseChecks: { billingMode, available: true }, rewriteCredits: { billingMode, available: true, estimateAvailable: true },
  genomeAnalysis: { billingMode, available: true, reason: null, maxPosts: 20, csvImport: { available: true, reason: null } }
});
function availability(...args) {
  const { genomeAvailability } = load('features/growth/availability.ts');
  assert.equal(typeof genomeAvailability, 'function', 'Genome consumes its independent concrete server projection');
  return genomeAvailability(...args);
}
test('managed Genome uses its own fresh platform-funded projection with null Free counters', () => {
  const result = availability(managed, readyCatalog(), true);
  assert.equal(result.available, true);
  assert.match(result.detail, /platform.funded/i);
  assert.match(result.detail, /20/);
  assert.doesNotMatch(result.detail, /approve|MAX|daily allowance|from your balance/i);
});
test('other Growth readiness and raw consent cannot qualify missing or malformed managed Genome', () => {
  for (const genomeAnalysis of [undefined, null, { billingMode: 'free', available: true, maxPosts: 20 },
    { billingMode: 'managed_credits', available: false, maxPosts: 20 },
    { billingMode: 'managed_credits', available: 'true', maxPosts: 20 },
    { billingMode: 'managed_credits', available: true },
    ...[19, 21, '20', null].map(maxPosts => ({ billingMode: 'managed_credits', available: true, maxPosts }))]) {
    assert.equal(availability(managed, { ...readyCatalog(), genomeAnalysis }, true).available, false);
  }
});
test('CSV independently needs exact server csvImport readiness', () => {
  const catalog = readyCatalog();
  for (const csvImport of [undefined, null, { available: false }, { available: 'true' }]) {
    const changed = { ...catalog, genomeAnalysis: { ...catalog.genomeAnalysis, csvImport } };
    assert.equal(availability(managed, changed, true).available, true, 'owned selected samples do not depend on CSV');
    assert.equal(availability(managed, changed, true, true).available, false);
  }
  assert.equal(availability(managed, catalog, true, true).available, true);
});
test('missing, stale, failed and revoked catalogs never qualify Genome', () => {
  for (const usage of [managed, free(), { billingMode: 'legacy_allowances', freePreview: null }]) {
    for (const catalog of [null, { ...readyCatalog(), genome: false }, { ...readyCatalog(), consented: false }]) {
      assert.equal(availability(usage, catalog, true).available, false);
    }
    assert.equal(availability(usage, readyCatalog(), false).available, false);
  }
  assert.equal(availability(null, readyCatalog(), true).available, false);
  assert.equal(availability({ billingMode: undefined }, readyCatalog('free'), true).available, false);
});
test('Free retains one lifetime recent-20 analysis and refuses exhausted or ineligible usage', () => {
  const catalog = readyCatalog('free');
  assert.equal(availability(free(), catalog, true).available, true);
  assert.match(availability(free(), catalog, true).detail, /1 lifetime recent-20 Genome analysis remaining/);
  assert.equal(availability(free(0), catalog, true).available, false);
  assert.equal(availability(free(1, false), catalog, true).available, false);
  assert.equal(availability(free(), readyCatalog(), true).available, false, 'billing mode mismatch');
  assert.equal(availability(free(), { ...catalog, genomeAnalysis: undefined }, true).available, false);
});
test('legacy keeps its daily allowance without requiring a v2 projection', () => {
  const catalog = { genome: true, consented: true };
  const result = availability({ billingMode: 'legacy_allowances', freePreview: null }, catalog, true);
  assert.equal(result.available, true);
  assert.match(result.detail, /legacy daily allowance/);
});
test('public Genome projection is optional and its advertised maximum is exactly 20', () => {
  const types = path.resolve(__dirname, '../src/lib/growth/types.ts');
  const virtual = path.resolve(__dirname, 'genome-contract-virtual.ts');
  const source = `import type { GrowthCatalog } from '../src/lib/growth/types';
const omitted: Pick<GrowthCatalog, 'genomeAnalysis'> = {};
const exact: NonNullable<GrowthCatalog['genomeAnalysis']> = {billingMode:'managed_credits',available:true,reason:null,maxPosts:20,csvImport:{available:false,reason:'permission_required'}};
// @ts-expect-error A general credit allowance does not change the server maximum.
const wrong: NonNullable<GrowthCatalog['genomeAnalysis']> = {...exact,maxPosts:21};
void [omitted,exact,wrong];`;
  const options = { noEmit: true, strict: true, skipLibCheck: true, types: [], target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS };
  const host = ts.createCompilerHost(options), originalRead = host.readFile, originalExists = host.fileExists;
  host.readFile = file => file === virtual ? source : originalRead(file);
  host.fileExists = file => file === virtual || originalExists(file);
  const program = ts.createProgram([virtual, types], options, host);
  assert.deepEqual(ts.getPreEmitDiagnostics(program).map(d => ts.flattenDiagnosticMessageText(d.messageText, '\n')), []);
});

function find(node, predicate) {
  if (!node || typeof node !== 'object') return null;
  if (predicate(node)) return node;
  for (const child of [node.props?.children].flat(Infinity)) { const found = find(child, predicate); if (found) return found; }
  return null;
}
const tick = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
function scenario({ mode = 'managed_credits', role = 'owner', savedStatus = 'proposed' } = {}) {
  let cursor = 0;
  const slots = [], calls = [];
  const state = { usage: mode === 'free_preview' ? free() : { billingMode: mode, freePreview: null },
    catalog: readyCatalog(mode === 'free_preview' ? 'free' : mode === 'legacy_allowances' ? 'legacy' : mode),
    catalogSuccess: true, catalogError: false, catalogStale: false, fresh: null, freshError: null,
    postError: null, role, workspaceId: 'workspace', sources: [{ id: 'owned-selected', title: 'My owned sample', kind: 'voice_sample', active: true, selected: true },
      { id: 'not-selected', title: 'Unselected', kind: 'voice_sample', active: true, selected: false }], pendingCatalog: null };
  const version = { id: 'saved-genome', status: savedStatus, postCount: 2, measuredPosts: 0, suppliedMetricsPosts: 0,
    statements: [{ id: 'statement', text: 'Saved pattern', label: 'My selected label', grade: 'supported', evidenceIds: [], counterEvidenceIds: [], cohort: { platform: 'LinkedIn', language: 'en-US' } }] };
  const query = { data: { versions: [version], active: savedStatus === 'approved' ? version : null, evidence: {}, shares: [{ id: 'saved-share', revoked: false }] },
    refetch: async () => { calls.push(['saved-refresh']); } };
  const snapshot = { get data() { return { revision: 7, state: { sources: state.sources } }; }, refetch: async () => { calls.push(['snapshot-refresh']); } };
  const usage = { get data() { return state.usage; }, refetch: async () => { calls.push(['usage-refresh']); return { data: state.usage }; } };
  const catalog = { get data() { return state.catalog; }, get isSuccess() { return state.catalogSuccess; },
    get isError() { return state.catalogError; }, get isStale() { return state.catalogStale; },
    refetch: async () => {
      calls.push(['catalog']);
      if (state.pendingCatalog) await state.pendingCatalog;
      if (state.freshError) { state.catalogSuccess = false; state.catalogError = true; throw state.freshError; }
      if (state.fresh) state.catalog = structuredClone(state.fresh);
      return { data: state.catalog, isSuccess: state.catalogSuccess, isError: state.catalogError, isStale: state.catalogStale };
    } };
  const api = { analyzeHistory: async (_workspace, body) => {
    calls.push(['history', structuredClone(body)]);
    if (state.postError) { state.fresh = { ...state.catalog, genomeAnalysis: { ...state.catalog.genomeAnalysis, available: false, reason: 'funding_unavailable' } }; throw state.postError; }
    return { genome: { id: 'new-genome' } };
  } };
  const hooks = { ...React, useRef: initial => { const i = cursor++; return slots[i] ??= { current: initial }; },
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; } };
  const plain = ({ children }) => React.createElement('div', {}, children);
  const mocks = { react: hooks, 'next/link': plain,
    '@tanstack/react-query': { useQuery: options => { state.savedQuery = options; return query; } },
    '@/components/ui/button': { Button: ({ children, disabled }) => React.createElement('button', { disabled }, children) },
    '@/components/rafii': { Surface: plain }, '@/lib/api/hooks': { useUsage: () => usage, useSnapshot: () => snapshot,
      useAct: () => ({ isPending: false, mutateAsync: async body => { calls.push(['manual', body]); return { path: '/synthetic-card' }; } }) },
    '@/lib/auth/access': { useWorkspaceAccess: () => ({ role: state.role }) }, '@/lib/workspace/provider': { useWorkspaceApi: () => ({ api, workspaceId: state.workspaceId }) },
    './shared': { useGrowthCatalog: () => catalog, GrowthConsent: () => null }, './availability': load('features/growth/availability.ts') };
  const { GenomePanel } = load('features/growth/genome-panel.tsx', mocks);
  const render = () => { cursor = 0; return GenomePanel(); };
  const control = label => find(render(), n => n.props?.['aria-label'] === label);
  const propose = () => find(render(), n => n.props?.children === 'Propose my Genome');
  const selectSample = () => { control('Analyze My owned sample').props.onChange({ target: { checked: true } });
    control('Confirm owned history retention and analysis').props.onChange({ target: { checked: true } }); };
  const submit = async () => { propose().props.onClick(); await tick(); };
  const upload = async () => {
    let reads = 0;
    const file = { size: 40, text: async () => { reads++; return 'text,platform\nMy owned post,LinkedIn'; } };
    await control('Owned history CSV').props.onChange({ target: { files: [file] } });
    const account = control('CSV account');
    if (account) account.props.onChange({ target: { value: 'My account' } });
    control('Confirm owned history retention and analysis').props.onChange({ target: { checked: true } });
    return reads;
  };
  return { state, calls, render, control, propose, selectSample, submit, upload };
}
test('actual managed caller freshly rechecks Genome before the unchanged history POST, with no quote', async () => {
  const f = scenario(); f.selectSample();
  assert.equal(f.propose().props.disabled, false);
  await f.submit();
  assert.deepEqual(f.calls.map(c => c[0]), ['catalog', 'history', 'saved-refresh', 'snapshot-refresh', 'usage-refresh']);
  const body = f.calls.find(c => c[0] === 'history')[1];
  assert.deepEqual(body, { sourceIds: ['owned-selected'], ownContent: true, retainText: true, confirmed: true, requestKey: body.requestKey });
  assert.match(body.requestKey, /^[\da-f-]{36}$/);
});
for (const changed of [{ available: false }, { billingMode: 'free' }, { maxPosts: 21 }, { maxPosts: undefined }]) {
  test(`fresh managed refusal ${JSON.stringify(changed)} stops before history POST`, async () => {
    const f = scenario(); f.selectSample(); f.state.fresh = { ...f.state.catalog, genomeAnalysis: { ...f.state.catalog.genomeAnalysis, ...changed } };
    await f.submit();
    assert.equal(f.calls.some(c => c[0] === 'history'), false);
    assert.equal(f.propose().props.disabled, true);
  });
}
for (const field of ['catalogStale', 'catalogError', 'catalogSuccess']) {
  test(`cached ${field} cannot authorize even an invoked click`, async () => {
    const f = scenario(); f.selectSample(); f.state[field] = field !== 'catalogSuccess';
    assert.equal(f.propose().props.disabled, true);
    await f.submit(); assert.deepEqual(f.calls, []);
  });
}
test('fresh failed catalog never reuses cached qualified data for a POST', async () => {
  const f = scenario(); f.selectSample(); f.state.freshError = new Error('Catalog unavailable');
  await f.submit(); assert.deepEqual(f.calls.map(c => c[0]), ['catalog']);
  assert.equal(f.propose().props.disabled, true);
});
for (const status of [402, 409]) {
  test(`history ${status} refreshes funding truth without creating a quote or automatic retry`, async () => {
    const f = scenario(); f.selectSample(); f.state.postError = Object.assign(new Error('Server refused analysis'), { status });
    await f.submit();
    assert.equal(f.calls.filter(c => c[0] === 'history').length, 1);
    assert.equal(f.calls.filter(c => c[0] === 'catalog').length, 2);
    assert.equal(f.calls.filter(c => c[0] === 'usage-refresh').length, 1);
    assert.equal(f.propose().props.disabled, true);
    assert.match(renderToStaticMarkup(f.render()), /Server refused analysis/);
  });
}
test('pending catalog cannot send input whose owned consent or source selection changed', async () => {
  const f = scenario(); f.selectSample(); let release;
  f.state.pendingCatalog = new Promise(resolve => { release = resolve; });
  f.propose().props.onClick();
  f.control('Analyze My owned sample').props.onChange({ target: { checked: false } });
  release(); await tick();
  assert.equal(f.calls.some(c => c[0] === 'history'), false);
  assert.equal(f.control('Confirm owned history retention and analysis').props.checked, false);
});
test('duplicate clicks while catalog is pending do not submit duplicate history requests', async () => {
  const f = scenario(); f.selectSample(); let release;
  f.state.pendingCatalog = new Promise(resolve => { release = resolve; });
  const click = f.propose().props.onClick; click(); click(); release(); await tick();
  assert.equal(f.calls.filter(c => c[0] === 'catalog').length, 1);
  assert.equal(f.calls.filter(c => c[0] === 'history').length, 1);
});
for (const change of ['workspace', 'billingMode', 'sourceGrants']) {
  test(`a changed ${change} during the fresh read cannot submit the earlier context`, async () => {
    const f = scenario(); f.selectSample(); let release;
    f.state.pendingCatalog = new Promise(resolve => { release = resolve; });
    f.propose().props.onClick();
    if (change === 'workspace') f.state.workspaceId = 'other-workspace';
    if (change === 'billingMode') f.state.usage = free();
    if (change === 'sourceGrants') f.state.sources = [];
    f.render(); release(); await tick();
    assert.equal(f.calls.some(c => c[0] === 'history'), false);
  });
}
test('stale catalog offers a manual truth refresh without submitting an analysis', async () => {
  const f = scenario(); f.state.catalogStale = true;
  const refresh = find(f.render(), n => n.props?.children === 'Refresh Genome availability');
  assert.ok(refresh);
  refresh.props.onClick(); await tick();
  assert.deepEqual(f.calls.map(c => c[0]), ['catalog']);
});
test('CSV uses exact owner input and needs csvImport again immediately before POST', async () => {
  const f = scenario(); assert.equal(await f.upload(), 1);
  f.state.fresh = { ...f.state.catalog, genomeAnalysis: { ...f.state.catalog.genomeAnalysis, csvImport: { available: false, reason: 'permission_required' } } };
  await f.submit(); assert.equal(f.calls.some(c => c[0] === 'history'), false);
  const success = scenario(); await success.upload(); await success.submit();
  const body = success.calls.find(c => c[0] === 'history')[1];
  assert.deepEqual(body, { data: 'text,platform\nMy owned post,LinkedIn', account: 'My account', ownContent: true, retainText: true, confirmed: true, requestKey: body.requestKey });
});
test('unqualified CSV never reads an uploaded file; an editor still selects granted samples', async () => {
  const f = scenario(); f.state.catalog.genomeAnalysis.csvImport.available = false;
  assert.equal(f.control('Owned history CSV').props.disabled, true);
  assert.equal(await f.upload(), 0);
  const editor = scenario({ role: 'editor' });
  assert.equal(editor.control('Owned history CSV'), null);
  editor.selectSample(); await editor.submit();
  assert.deepEqual(editor.calls.find(c => c[0] === 'history')[1].sourceIds, ['owned-selected']);
});
test('explicit owned consent and currently selected source grants remain necessary at the caller', async () => {
  const f = scenario(); f.selectSample();
  f.control('Confirm owned history retention and analysis').props.onChange({ target: { checked: false } });
  await f.submit(); assert.deepEqual(f.calls, []);
  f.control('Confirm owned history retention and analysis').props.onChange({ target: { checked: true } });
  f.state.sources = f.state.sources.map(s => ({ ...s, selected: false }));
  await f.submit(); assert.deepEqual(f.calls, [], 'lost source grants refuse before new I/O');
});
test('Free and legacy callers retain their exact transport and recheck fresh catalog truth', async () => {
  for (const mode of ['free_preview', 'legacy_allowances']) {
    const f = scenario({ mode }); f.selectSample(); await f.submit();
    assert.equal(f.calls[0][0], 'catalog'); assert.equal(f.calls[1][0], 'history');
    assert.equal(Object.hasOwn(f.calls[1][1], 'creditQuoteId'), false);
  }
});
test('saved Genome evidence, approval, restore and share controls remain readable without new spending', async () => {
  for (const savedStatus of ['proposed', 'superseded', 'approved']) {
    const f = scenario({ savedStatus }); f.state.catalog.genomeAnalysis.available = false;
    f.state.catalog.genome = false;
    let tree = f.render();
    assert.equal(f.state.savedQuery.enabled, true, 'stored Genome read is independent of feature/spend readiness');
    assert.match(renderToStaticMarkup(tree), /Saved pattern/);
    if (savedStatus !== 'approved') {
      const name = savedStatus === 'superseded' ? 'Restore this approved version' : 'Approve this Genome';
      find(tree, n => n.props?.children === name).props.onClick(); await tick();
      assert.equal(f.calls.find(c => c[0] === 'manual')[1].action, savedStatus === 'superseded' ? 'genome_restore' : 'genome_approve');
    } else {
      f.control('Share My selected label').props.onChange({ target: { checked: true } }); tree = f.render();
      find(tree, n => n.props?.children === 'Create public link for selected labels').props.onClick(); await tick();
      assert.deepEqual(f.calls.find(c => c[0] === 'manual')[1].payload, { genomeId: 'saved-genome', statementIds: ['statement'], confirmed: true });
    }
    assert.equal(f.calls.some(c => c[0] === 'history' || c[0] === 'catalog'), false);
  }
  const missing = scenario(); missing.state.catalog = undefined;
  assert.match(renderToStaticMarkup(missing.render()), /Saved pattern/);
});
