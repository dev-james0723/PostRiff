/**
 * The writer the web sends when the person chose none (src/features/agent/use-model.ts): Rafii's managed AI writer
 * when offered, never an implicit "Templates (no AI model)". Nothing chosen is Auto: the workspace default, else the
 * deployment's, and a managed writer on Auto is not named in the request at all.
 *
 *   node --test web/tests/model-default.test.cjs
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const file = path.resolve(__dirname, '../src/features/agent/use-model.ts');
const loaded = new Module(file);
loaded.paths = module.paths;
loaded.require = (id) => (id === './reasoning-map' ? {} : require(id));
loaded._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file);
const { resolveModelChoice, storedModelChoice, shortLabel } = loaded.exports;

const fixture = { id: 'deterministic-preview', qualified: true, costClass: 'none', route: 'fixture' };
const managed = { id: 'openai/gpt-6-sol', qualified: true, costClass: 'paid' };

test('no catalogue yet means no model, so the server picks its default writer', () => {
  assert.equal(resolveModelChoice([], null), '');
});

test('the managed writer is the default; templates only when nothing else is offered', () => {
  assert.equal(resolveModelChoice([fixture, managed], null), 'openai/gpt-6-sol');
  assert.equal(resolveModelChoice([fixture], null), 'deterministic-preview');
});

test('a fixture saved under the old key is not a choice of templates; a new explicit choice is kept', () => {
  assert.equal(storedModelChoice(null, 'deterministic-preview'), null);
  assert.equal(storedModelChoice(null, 'openai/gpt-6-sol'), 'openai/gpt-6-sol');
  assert.equal(storedModelChoice('deterministic-preview', 'openai/gpt-6-sol'), 'deterministic-preview');
  assert.equal(resolveModelChoice([fixture, managed], storedModelChoice(null, 'deterministic-preview')), 'openai/gpt-6-sol');
});

test('templates are named for what they are', () => {
  assert.equal(shortLabel(undefined, 'deterministic-preview'), 'Templates (no AI model)');
});

/* ---------- Auto: the workspace default, else the deployment's ---------- */

const { resolveAuto, requestFieldsFor, AUTO_MODEL } = loaded.exports;
const sol = { id: 'openai/gpt-6-sol', displayName: 'gpt-6-sol', qualified: true, costClass: 'paid', priced: true };
const sonnet = { id: 'anthropic/claude-sonnet-5', displayName: 'claude-sonnet-5', qualified: true, costClass: 'paid', priced: true };
const unpriced = { id: 'minimax/minimax-m3', displayName: 'minimax-m3', qualified: true, costClass: 'paid', priced: false };
const catalogue = [fixture, sol, sonnet, unpriced];
const defaults = { workspace: 'anthropic/claude-sonnet-5', deployment: 'openai/gpt-6-sol' };

test('Auto is stored as a marker and resolves to the workspace default, else the deployment default', () => {
  assert.equal(AUTO_MODEL, 'auto');
  assert.equal(resolveModelChoice(catalogue, null, defaults), 'anthropic/claude-sonnet-5');
  assert.equal(resolveModelChoice(catalogue, 'auto', defaults), 'anthropic/claude-sonnet-5', 'the stored marker is never sent as a model');
  assert.equal(resolveModelChoice(catalogue, null, { workspace: null, deployment: 'openai/gpt-6-sol' }), 'openai/gpt-6-sol');
  assert.equal(resolveModelChoice(catalogue, 'auto', {}), 'openai/gpt-6-sol', 'no defaults yet: today\'s first paid managed writer');
  assert.equal(resolveModelChoice([fixture], 'auto', { deployment: null }), 'deterministic-preview');
});

test('an unpriced or withdrawn workspace default falls back to the deployment default, with a note', () => {
  assert.equal(resolveModelChoice(catalogue, null, { workspace: 'minimax/minimax-m3', deployment: 'openai/gpt-6-sol' }), 'openai/gpt-6-sol');
  assert.equal(resolveModelChoice(catalogue, null, { workspace: 'openai/gone', deployment: 'openai/gpt-6-sol' }), 'openai/gpt-6-sol');
  const stale = resolveAuto(catalogue, { workspace: 'minimax/minimax-m3', deployment: 'openai/gpt-6-sol' });
  assert.deepEqual(stale, { model: 'openai/gpt-6-sol', source: 'deployment', note: 'The workspace default writer minimax/minimax-m3 is no longer offered, so Rafii uses gpt-6-sol.' });
  assert.deepEqual(resolveAuto(catalogue, defaults), { model: 'anthropic/claude-sonnet-5', source: 'workspace', note: null });
  assert.deepEqual(resolveAuto(catalogue, { workspace: null, deployment: 'openai/gpt-6-sol' }), { model: 'openai/gpt-6-sol', source: 'deployment', note: null });
});

test('an explicit pick still wins over Auto, even when it is unavailable', () => {
  assert.equal(resolveModelChoice(catalogue, 'openai/gpt-6-sol', defaults), 'openai/gpt-6-sol');
  assert.equal(resolveModelChoice(catalogue, 'deterministic-preview', defaults), 'deterministic-preview');
  assert.equal(resolveModelChoice(catalogue, 'missing/model', defaults), 'missing/model');
});

test('requests never carry an "auto" marker: managed Auto omits the model, the Auto level omits reasoning', () => {
  assert.deepEqual(requestFieldsFor({ auto: true, managed: true, model: 'anthropic/claude-sonnet-5', level: 'auto' }), {});
  assert.deepEqual(requestFieldsFor({ auto: true, managed: true, model: 'anthropic/claude-sonnet-5', level: 'thorough' }), { reasoning: 'thorough' });
  assert.deepEqual(requestFieldsFor({ auto: false, managed: true, model: 'openai/gpt-6-sol', level: 'auto' }), { model: 'openai/gpt-6-sol' });
  assert.deepEqual(requestFieldsFor({ auto: false, managed: true, model: 'openai/gpt-6-sol', level: 'high' }), { model: 'openai/gpt-6-sol', reasoning: 'high' });
});

test('templates and CLIs keep today\'s request: their model and an explicit level, on Auto too', () => {
  assert.deepEqual(requestFieldsFor({ auto: true, managed: false, model: 'deterministic-preview', level: 'quick' }), { model: 'deterministic-preview', reasoning: 'quick' });
  assert.equal(requestFieldsFor({ auto: true, managed: false, model: 'deterministic-preview', level: null }).reasoning, 'quick');
  assert.deepEqual(requestFieldsFor({ auto: false, managed: false, model: 'claude-code:sonnet', level: 'low' }), { model: 'claude-code:sonnet', reasoning: 'low' });
});

test('an old managed "high" (the two-pass Deep) becomes Thorough, not a single effort=high pass', () => {
  // use-model.ts with the real reasoning-map: the same chain the hook runs on first load.
  const mapFile = path.resolve(__dirname, '../src/features/agent/reasoning-map.ts');
  const map = new Module(mapFile);
  map._compile(ts.transpileModule(fs.readFileSync(mapFile, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, mapFile);
  const R = map.exports;
  const levels = [
    { id: 'auto', kind: 'auto', label: 'Auto', available: true, detail: '' },
    { id: 'high', kind: 'effort', label: 'High', sends: 'high', available: true, detail: '' },
    { id: 'thorough', kind: 'pass', label: 'Thorough (draft, then revise)', available: true, detail: '' }
  ];
  const stored = R.migrateReasoningPreferences({ 'openai/gpt-6-sol': 'high' });
  assert.equal(stored['openai/gpt-6-sol'], 'thorough');
  const level = R.chooseLevel(R.levelsFor(levels), stored['openai/gpt-6-sol'], R.hasAutoLevel(levels));
  assert.deepEqual(requestFieldsFor({ auto: false, managed: true, model: 'openai/gpt-6-sol', level: level.id }), { model: 'openai/gpt-6-sol', reasoning: 'thorough' });
});

test('every sender spreads the Auto-aware request fields; the Rafii panel names the resolved writer', () => {
  const src = (file) => fs.readFileSync(path.resolve(__dirname, '../src', file), 'utf8');
  const home = src('features/agent/home-view.tsx');
  assert.ok(home.includes('...choice.requestFields'), 'Home estimate, quick start and automation answers');
  assert.ok(!/model: choice\.model/.test(home) && !/reasoning: choice\.reasoning/.test(home), 'Home never sends the resolved id or level itself');
  assert.ok(home.includes('value={choice.dialogValue}') && home.includes('onApply={choice.applyDialog}'), 'the dialog round-trips Auto');
  const conversation = src('features/agent/conversation-view.tsx');
  assert.ok(conversation.includes('...choice.requestFields') && !/model: choice\.model/.test(conversation));
  assert.ok(src('features/ideas/use-draft.ts').includes('choice.requestFields.model'), 'Ideas pins only an explicit writer and never sends reasoning');
  assert.ok(src('features/site-agent/chat.tsx').includes('model: choice.model'), 'the panel sends the concrete id, never "auto"');
  const generation = src('features/agent/home/use-home-generation.ts');
  assert.ok(generation.includes('model?: string;') && generation.includes('reasoning?: string;'));
});
