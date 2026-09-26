// How Rafii talks (Contract 1): the web style module against its server twin, and the save behind useAgentStyle.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { QueryClient } = require('@tanstack/react-query');

const SRC = path.join(__dirname, '..', 'src');
const STYLE_PY = path.join(__dirname, '..', '..', 'src', 'postriff_phase2', 'agent_runtime_v2', 'style.py');

/** Loads a TypeScript module; `stubs` stand in for imports the test replaces (aliases, toasts). */
function load(rel, stubs = {}) {
  const file = path.join(SRC, rel);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((id) => (id in stubs ? stubs[id] : require(id)), mod, mod.exports);
  return mod.exports;
}

const S = load('lib/agent-runtime/style.ts');

test('normalizeStyle turns anything into a complete, valid style', () => {
  for (const raw of [undefined, null, 'friendly', 42, [], {}]) assert.deepEqual(S.normalizeStyle(raw), S.DEFAULT_STYLE);
  const saved = { tone: 'direct', detail: 'detailed', pace: 'faster', voice: 'coral', language: 'yue', initiative: 'ask', chosen: true };
  assert.deepEqual(S.normalizeStyle(saved), saved);
  // Each unknown value falls back on its own; other keys are dropped; only a real `true` counts as chosen.
  assert.deepEqual(S.normalizeStyle({ tone: 'rude', detail: 'concise', voice: 'Marin', language: 'fr', extra: 'x', chosen: 'true' }), { ...S.DEFAULT_STYLE, detail: 'concise' });
  assert.equal(S.normalizeStyle({ chosen: 1 }).chosen, false);
  assert.deepEqual(Object.keys(S.normalizeStyle({ extra: 1 })).sort(), ['chosen', 'detail', 'initiative', 'language', 'pace', 'tone', 'voice']);
});

test('presetOf names the starting point a style matches, and nothing for a custom mix', () => {
  assert.equal(S.presetOf(S.DEFAULT_STYLE), 'friendly');
  for (const [id, preset] of Object.entries(S.PRESETS)) {
    assert.equal(S.presetOf({ ...S.DEFAULT_STYLE, ...preset.style }), id);
    // Voice, language and chosen are not part of a starting point.
    assert.equal(S.presetOf({ ...S.DEFAULT_STYLE, ...preset.style, voice: 'sage', language: 'cmn', chosen: true }), id);
  }
  assert.equal(S.presetOf({ ...S.DEFAULT_STYLE, ...S.PRESETS.concise.style, pace: 'slower' }), null);
  assert.equal(S.presetOf({ ...S.DEFAULT_STYLE, tone: 'playful' }), null);
  assert.deepEqual(Object.keys(S.PRESETS), ['friendly', 'concise', 'explainer']);
  assert.deepEqual(Object.values(S.PRESETS).map((preset) => preset.label), ['Friendly', 'Concise', 'Explain in detail']);
});

test('the web style module matches the server one (style.py)', () => {
  const py = fs.readFileSync(STYLE_PY, 'utf8');
  const tuple = (name) => JSON.parse(`[${py.match(new RegExp(`^${name} = \\((.*)\\)$`, 'm'))[1]}]`);
  assert.deepEqual([tuple('TONES'), tuple('DETAILS'), tuple('PACES'), tuple('VOICES'), tuple('LANGUAGES'), tuple('INITIATIVE')], [[...S.TONES], [...S.DETAILS], [...S.PACES], [...S.VOICES], [...S.LANGUAGES], [...S.INITIATIVE]]);
  const { chosen, ...defaults } = S.DEFAULT_STYLE;
  assert.equal(chosen, false);
  assert.deepEqual(JSON.parse(py.match(/^DEFAULT = (\{.*\})$/m)[1]), defaults);
  const block = py.match(/^PRESETS = \{\n([\s\S]*?)\n\}/m)[1];
  const presets = Object.fromEntries(block.split('\n').map((line) => line.match(/^\s*"(\w+)": (\{.*\}),?$/)).map((m) => [m[1], JSON.parse(m[2])]));
  assert.deepEqual(presets, Object.fromEntries(Object.entries(S.PRESETS).map(([id, preset]) => [id, preset.style])));
  // Every value has a label a person reads.
  for (const [values, labels] of [[S.TONES, S.TONE_LABELS], [S.DETAILS, S.DETAIL_LABELS], [S.PACES, S.PACE_LABELS], [S.VOICES, S.VOICE_LABELS], [S.LANGUAGES, S.LANGUAGE_LABELS], [S.INITIATIVE, S.INITIATIVE_LABELS]]) {
    assert.deepEqual(Object.keys(labels), [...values]);
  }
});

/* ---- saving (use-agent-style.ts) ---- */

const flush = () => new Promise((resolve) => setImmediate(resolve));
const ME = { userId: 'u1', displayName: 'James', sessionId: null, mfa: {}, preferences: { timeZone: 'Asia/Hong_Kong', locale: '', alertNewDevice: false, agentStyle: S.DEFAULT_STYLE } };

function saving() {
  const toasts = [];
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }
  const U = load('lib/agent-runtime/use-agent-style.ts', {
    './style': S,
    './panel-actions': { registerPanelActions: () => () => undefined },
    '@/lib/api/client': { ApiError },
    '@/lib/api/hooks': { keys: { me: ['me'] }, useMe: () => ({}) },
    '@/lib/workspace/provider': { useWorkspace: () => ({}) },
    sonner: { toast: { error: (message) => toasts.push(message) } }
  });
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  client.setQueryData(['me'], ME);
  const shown = () => client.getQueryData(['me']).preferences.agentStyle;
  return { U, client, toasts, ApiError, shown };
}

test('applyStylePatch merges like the server: the preset, then single fields', () => {
  const { U } = saving();
  assert.deepEqual(U.applyStylePatch(S.DEFAULT_STYLE, { preset: 'explainer', chosen: true }), { ...S.DEFAULT_STYLE, ...S.PRESETS.explainer.style, chosen: true });
  assert.deepEqual(U.applyStylePatch(S.DEFAULT_STYLE, { preset: 'concise', tone: 'playful' }), { ...S.DEFAULT_STYLE, ...S.PRESETS.concise.style, tone: 'playful' });
  const custom = { ...S.DEFAULT_STYLE, voice: 'verse', language: 'en', chosen: true };
  assert.deepEqual(U.applyStylePatch(custom, { preset: 'friendly' }), { ...custom, ...S.PRESETS.friendly.style });
  assert.deepEqual(U.applyStylePatch(custom, { tone: undefined, pace: 'faster' }), { ...custom, pace: 'faster' });
});

test('a save shows at once, then settles on what the server kept', async () => {
  const { U, client, shown } = saving();
  const sent = [];
  let answer;
  const pending = U.saveStyle(client, (patch) => (sent.push(patch), new Promise((resolve) => (answer = resolve))), { preset: 'concise', chosen: true });
  await flush();
  assert.deepEqual(sent, [{ preset: 'concise', chosen: true }]);
  assert.deepEqual(shown(), { ...S.DEFAULT_STYLE, ...S.PRESETS.concise.style, chosen: true });
  const kept = { ...S.DEFAULT_STYLE, ...S.PRESETS.concise.style, voice: 'cedar', chosen: true };
  answer({ displayName: 'James', preferences: { ...ME.preferences, agentStyle: kept } });
  await pending;
  assert.deepEqual(shown(), kept);
  assert.equal(client.getQueryData(['me']).preferences.timeZone, 'Asia/Hong_Kong');
  client.clear();
});

test('a refused save rolls back, says why and rejects', async () => {
  const { U, client, toasts, ApiError, shown } = saving();
  const refusal = new ApiError('Rafii’s style can’t be saved yet. Try again after the update finishes.', 503);
  await assert.rejects(U.saveStyle(client, async () => Promise.reject(refusal), { tone: 'playful', chosen: true }), (error) => error === refusal);
  assert.deepEqual(shown(), S.DEFAULT_STYLE);
  assert.deepEqual(toasts, [refusal.message]);
  // Without an answer from the server (offline), the toast says so in the app's own words.
  await assert.rejects(U.saveStyle(client, async () => Promise.reject(new TypeError('Failed to fetch')), { tone: 'playful' }));
  assert.equal(toasts.length, 2);
  assert.match(toasts[1], /^Couldn’t save how Rafii talks/);
  assert.deepEqual(shown(), S.DEFAULT_STYLE);
  client.clear();
});

test('saves reach the server one at a time, in order, and an earlier answer never undoes a later change', async () => {
  const { U, client, shown } = saving();
  const calls = [];
  const answers = [];
  const send = (patch) => (calls.push(patch), new Promise((resolve) => answers.push(resolve)));
  const first = U.saveStyle(client, send, { tone: 'playful' });
  const second = U.saveStyle(client, send, { voice: 'coral' });
  await flush();
  assert.deepEqual(calls, [{ tone: 'playful' }]);
  assert.deepEqual([shown().tone, shown().voice], ['playful', 'coral']);
  answers[0]({ displayName: 'James', preferences: { ...ME.preferences, agentStyle: { ...S.DEFAULT_STYLE, tone: 'playful' } } });
  await first;
  await flush();
  assert.deepEqual(calls, [{ tone: 'playful' }, { voice: 'coral' }]);
  assert.equal(shown().voice, 'coral');
  const kept = { ...S.DEFAULT_STYLE, tone: 'playful', voice: 'coral' };
  answers[1]({ displayName: 'James', preferences: { ...ME.preferences, agentStyle: kept } });
  await second;
  assert.deepEqual(shown(), kept);
  client.clear();
});
