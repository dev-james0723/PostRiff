const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

// Execute the real exported pure functions. React contexts aren't rendered.
function load(relative) {
  const file = path.resolve(__dirname, '../src', relative);
  const m = new Module(file);
  m.paths = Module._nodeModulePaths(path.dirname(file));
  const original = m.require.bind(m);
  m.require = name => name.startsWith('@/') ? {} : original(name);
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX }
  }).outputText, file);
  return m.exports;
}

test('effective Free and Creator are never trial fallback', () => {
  const { toPlan } = load('lib/workspace/provider.tsx');
  assert.equal(typeof toPlan, 'function');
  for (const plan of ['free', 'creator', 'trial', 'studio', 'assist']) assert.equal(toPlan(plan), plan);
  assert.equal(toPlan(null), 'trial');
});

test('v2 plan rank preserves role, permission and capability gates', () => {
  const { checkAccess } = load('lib/auth/access.tsx');
  for (const plan of ['free', 'creator']) {
    const access = { plan, role: 'editor', permissions: ['read', 'edit'], hasWorkspace: true, capabilities: [] };
    assert.equal(checkAccess(access, { plan: 'trial' }), true);
    assert.equal(checkAccess(access, { plan }), true);
    assert.equal(checkAccess(access, { permission: 'owner' }), false);
    assert.equal(checkAccess(access, { role: 'admin' }), false);
    assert.equal(checkAccess(access, { capability: 'paid-media' }), false);
  }
  const legacy = { plan: 'assist', role: 'viewer', permissions: ['read'], hasWorkspace: true, capabilities: [] };
  assert.equal(checkAccess(legacy, { plan: 'studio' }), true);
  assert.equal(checkAccess({ ...legacy, plan: 'free' }, { plan: 'creator' }), false);
});

test('signup transport retains legacy selectors and explicit Free without paid authority', () => {
  const { selectedPlan, rememberPlan } = load('lib/workspace/provider.tsx');
  const storage = new Map();
  const previous = globalThis.localStorage;
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) };
  try {
    assert.equal(selectedPlan(), 'studio');
    for (const plan of ['studio', 'assist', 'free']) {
      rememberPlan(plan);
      assert.equal(selectedPlan(), plan);
    }
    rememberPlan('creator');
    assert.equal(selectedPlan(), 'studio');
  } finally { globalThis.localStorage = previous; }
});

test('usage client passes explicit nullable evidence and modes unchanged', async () => {
  const { createApi } = load('lib/api/client.ts');
  const previous = globalThis.fetch;
  const calls = [];
  const payload = { billingMode: 'free_preview', credits: null, freePreview: {
    postDoctor: { remaining: 0, eligible: false, reason: 'used' },
    genome: { remaining: 1, eligible: false, reason: 'funding_unavailable', maxPosts: 20 }
  } };
  globalThis.fetch = async (url, options) => { calls.push([url, options]); return new Response(JSON.stringify(payload)); };
  try {
    const api = createApi(async () => 'synthetic');
    assert.deepEqual(await api.usage('workspace / one'), payload);
    assert.equal(calls[0][0], '/api/workspaces/workspace%20%2F%20one/usage');
    await api.bootstrap('free');
    assert.deepEqual(JSON.parse(calls[1][1].body), { plan: 'free' });
  } finally { globalThis.fetch = previous; }
});
