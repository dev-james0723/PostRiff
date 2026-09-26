const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
/**
 * The reasoning vocabulary of the model picker (src/features/agent/reasoning-map.ts): the legacy ladder mapping and
 * the per-model levels (Auto, gateway efforts, Thorough), the v1 → v2 preference move and the cost hints.
 *
 *   node --test web/tests/reasoning-map.test.cjs
 */
function load() {
  const file = path.resolve(__dirname, '../src/features/agent/reasoning-map.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const R = load();
const cli = ['low', 'medium', 'high', 'xhigh', 'max'].map((id) => ({ id, available: true, detail: 'Requested CLI effort; the selected model must support it.' }));
const managed = [
  { id: 'quick', available: true, detail: 'One pass, shortest answer.' },
  { id: 'standard', available: true, detail: 'One pass with a self-check for invented facts.' },
  { id: 'deep', available: true, detail: 'Two passes: draft, then a critique-and-revise pass.' }
];
const fixture = [
  { id: 'quick', available: true, detail: 'Deterministic preview only.' },
  { id: 'standard', available: false, detail: 'Requires a qualified model route.' },
  { id: 'deep', available: false, detail: 'Requires a qualified model route.' }
];

test('CLI routes: five real segments, four-bar scale with High+ half-lit, identity mapping', () => {
  const m = R.mapReasoning('xhigh', cli, 'Claude Code · sonnet');
  assert.equal(m.applied, true);
  assert.deepEqual(m.segments.map((s) => s.label), ['Low', 'Medium', 'High', 'High+', 'Max']);
  assert.deepEqual(m.segments.map((s) => s.bars), [1, 2, 3, 3.5, 4]);
  assert.deepEqual(m.segments.map((s) => s.id), ['low', 'medium', 'high', 'xhigh', 'max']);
  assert.equal(m.effective, 'xhigh');
  assert.equal(m.summary, 'Effective for Claude Code · sonnet: xhigh');
  assert.equal(R.mapReasoning('max', cli, 'x').effective, 'max');
  assert.equal(R.mapReasoning('low', cli, 'x').effective, 'low');
});

test('no stored preference: the lowest option is the provider default (today\'s behaviour, no extra cost)', () => {
  const m = R.mapReasoning(null, cli, 'Claude Code · sonnet');
  assert.equal(m.stored, false);
  assert.equal(m.preference, 'low');
  assert.equal(m.effective, 'low');
  assert.equal(m.summary, 'Provider default for Claude Code · sonnet: low');
  assert.equal(R.mapReasoning(undefined, managed, 'm').effective, 'quick');
});

test('managed routes: three segments Low/Medium/High → quick/standard/deep; higher preferences fall to the nearest lower level', () => {
  const m = R.mapReasoning('medium', managed, 'gpt · PostRiff managed');
  assert.deepEqual(m.segments.map((s) => [s.label, s.id, s.bars]), [['Low', 'quick', 1], ['Medium', 'standard', 2], ['High', 'deep', 3]]);
  assert.equal(m.effective, 'standard');
  assert.equal(m.summary, 'Effective for gpt · PostRiff managed: standard');
  const max = R.mapReasoning('max', managed, 'm');
  assert.equal(max.effective, 'deep');
  assert.equal(max.preference, 'max');
  assert.equal(max.summary, 'Effective for m: deep (nearest to Max)');
  assert.equal(R.mapReasoning('xhigh', managed, 'm').effective, 'deep');
});

test('a route with only `quick` is not applied: greyed generic segments, preference kept, run still sends quick', () => {
  const m = R.mapReasoning('high', fixture, 'Deterministic preview');
  assert.equal(m.applied, false);
  assert.equal(m.selected, null);
  assert.equal(m.summary, R.NOT_APPLIED);
  assert.equal(m.summary, 'Not applied by this provider');
  assert.equal(m.preference, 'high');
  assert.equal(m.effective, 'quick');
  assert.deepEqual(m.segments.map((s) => s.label), ['Low', 'Medium', 'High', 'Max']);
  assert.deepEqual(m.segments.map((s) => s.bars), [1, 2, 3, 4]);
});

test('empty or missing option lists never invent a value', () => {
  const none = R.mapReasoning('high', [], 'x');
  assert.equal(none.applied, false);
  assert.equal(none.effective, null);
  assert.equal(R.mapReasoning('high', undefined, 'x').effective, null);
});

test('option ids from the composer\'s existing chooseReasoning normalise to ladder levels', () => {
  assert.equal(R.normaliseLevel('deep'), 'high');
  assert.equal(R.normaliseLevel('standard'), 'medium');
  assert.equal(R.normaliseLevel('quick'), 'low');
  assert.equal(R.normaliseLevel(' MAX '), 'max');
  assert.equal(R.normaliseLevel('xhigh'), 'xhigh');
  assert.equal(R.normaliseLevel('turbo'), null);
  assert.equal(R.normaliseLevel(3), null);
});

test('a partial ladder (the synthetic selector fixture: low + high) picks the nearest lower level', () => {
  const partial = [{ id: 'low', available: true, detail: 'Low' }, { id: 'high', available: true, detail: 'High' }];
  const m = R.mapReasoning('medium', partial, 'Claude Code · sonnet');
  assert.deepEqual(m.segments.map((s) => s.label), ['Low', 'High']);
  assert.equal(m.effective, 'low');
  assert.equal(m.summary, 'Effective for Claude Code · sonnet: low (nearest to Medium)');
  assert.equal(R.mapReasoning('max', partial, 'x').effective, 'high');
});

test('unknown vocabularies are read by rank and every segment keeps a real option id', () => {
  const odd = ['calm', 'brisk', 'intense'].map((id) => ({ id, available: true, detail: '' }));
  const m = R.mapReasoning(null, odd, 'x');
  assert.deepEqual(m.segments.map((s) => s.level), ['low', 'medium', 'high']);
  assert.deepEqual(m.segments.map((s) => s.id), ['calm', 'brisk', 'intense']);
  assert.equal(R.mapReasoning('max', odd, 'x').effective, 'intense');
  const six = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => ({ id, available: true, detail: '' }));
  assert.deepEqual(R.mapReasoning(null, six, 'x').segments.map((s) => s.level), ['low', 'medium', 'high', 'xhigh', 'max', 'max']);
});

/* ---------- per-model levels (catalogue v2) ---------- */

const item = (id, kind, label, extra = {}) => ({ id, kind, label, available: true, detail: `${label} detail`, sends: kind === 'effort' ? id : null, typicalMilliCredits: null, ceilingMilliCredits: null, ...extra });
// openai/gpt-6-sol as the server lists it: Auto, the gateway efforts (xhigh/max not offered yet), Thorough.
const sol = [
  item('auto', 'auto', 'Auto', { typicalMilliCredits: 4000, ceilingMilliCredits: 20000 }),
  item('none', 'effort', 'Off'),
  item('minimal', 'effort', 'Minimal'),
  item('low', 'effort', 'Low'),
  item('medium', 'effort', 'Medium'),
  item('high', 'effort', 'High', { typicalMilliCredits: 9000, ceilingMilliCredits: 60000 }),
  item('xhigh', 'effort', 'Extra high', { available: false, detail: 'Not offered yet: too slow for one draft' }),
  item('max', 'effort', 'Max', { available: false, detail: 'Not offered yet: too slow for one draft' }),
  item('thorough', 'pass', 'Thorough (draft, then revise)', { typicalMilliCredits: 8000, ceilingMilliCredits: 40000 })
];
// minimax/minimax-m3 has no effort scale: Auto and Thorough only.
const minimax = [item('auto', 'auto', 'Auto'), item('thorough', 'pass', 'Thorough (draft, then revise)')];

test('managed levels keep the catalogue order and labels; Off and Minimal stay distinct from Low', () => {
  const levels = R.levelsFor(sol);
  assert.deepEqual(levels.map((l) => l.label), ['Auto', 'Off', 'Minimal', 'Low', 'Medium', 'High', 'Extra high', 'Max', 'Thorough (draft, then revise)']);
  assert.equal(new Set(levels.map((l) => l.label)).size, levels.length, 'no label repeats');
  assert.deepEqual(levels.map((l) => l.bars), [null, 0, 0.5, 1, 2, 3, 3.5, 4, 4]);
  assert.equal(levels.find((l) => l.id === 'thorough').sends, 'thorough', 'a pass names its own id');
  assert.equal(levels.find((l) => l.id === 'high').sends, 'high');
  assert.equal(R.hasAutoLevel(sol), true);
  assert.equal(R.hasAutoLevel(managed), false, 'the legacy quick/standard/deep list has no Auto');
  assert.equal(R.hasAutoLevel(fixture), false);
});

test('Auto as the writer offers only Auto and Thorough', () => {
  assert.deepEqual(R.levelsFor(sol, true).map((l) => l.id), ['auto', 'thorough']);
  assert.deepEqual(R.levelsFor(minimax, true).map((l) => l.id), ['auto', 'thorough']);
});

test('the default level is Auto; a stored level not offered or unavailable falls back to Auto on a managed writer', () => {
  const levels = R.levelsFor(sol);
  assert.equal(R.chooseLevel(levels, null, true).id, 'auto');
  assert.equal(R.chooseLevel(levels, 'high', true).id, 'high');
  assert.equal(R.chooseLevel(levels, 'xhigh', true).id, 'auto', 'available: false → auto');
  assert.equal(R.chooseLevel(levels, 'max', true).id, 'auto');
  assert.equal(R.chooseLevel(levels, 'quick', true).id, 'auto', 'not listed → auto');
  assert.equal(R.chooseLevel(R.levelsFor(minimax), 'high', true).id, 'auto');
  assert.equal(R.chooseLevel(R.levelsFor(sol, true), 'high', true).id, 'auto', 'Auto as the writer never sends an effort');
  assert.equal(R.chooseLevel(R.levelsFor(sol, true), 'thorough', true).id, 'thorough');
});

test('other routes keep today\'s rule: the stored option if listed and available, else the first available one', () => {
  assert.equal(R.chooseLevel(R.levelsFor(fixture), null, false).id, 'quick');
  assert.equal(R.chooseLevel(R.levelsFor(fixture), 'deep', false).id, 'quick', 'deep is unavailable on the fixture');
  assert.equal(R.chooseLevel(R.levelsFor(fixture), 'auto', false).id, 'quick');
  assert.equal(R.chooseLevel(R.levelsFor(cli), null, false).id, 'low');
  assert.equal(R.chooseLevel(R.levelsFor(cli), 'xhigh', false).id, 'xhigh');
  assert.equal(R.chooseLevel([], null, false), null);
  // Items without a label are named from the fallback table.
  assert.deepEqual(R.levelsFor(fixture).map((l) => [l.label, l.sends, l.available]), [['Quick', 'quick', true], ['Standard', 'standard', false], ['Deep', 'deep', false]]);
  assert.deepEqual(R.levelsFor(cli).map((l) => l.label), ['Low', 'Medium', 'High', 'Extra high', 'Max']);
});

test('v1 preferences move once: managed ladder values become Auto or Thorough, CLI efforts stay, the rest is dropped', () => {
  const moved = R.migrateReasoningPreferences({
    'openai/gpt-6-sol': 'high',
    'anthropic/claude-sonnet-5': 'low',
    'google/gemini-3.8-flash': 'medium',
    'bytedance/seed-2.1-turbo': 'xhigh',
    'minimax/minimax-m3': 'max',
    'claude-code:sonnet': 'xhigh',
    'codex:default': 'medium',
    'deterministic-preview': 'high',
    'openai/gpt-6-luna': 'turbo'
  });
  assert.deepEqual(moved, {
    'openai/gpt-6-sol': 'thorough',
    'anthropic/claude-sonnet-5': 'auto',
    'google/gemini-3.8-flash': 'auto',
    'bytedance/seed-2.1-turbo': 'auto',
    'minimax/minimax-m3': 'auto',
    'claude-code:sonnet': 'xhigh',
    'codex:default': 'medium'
  });
  assert.deepEqual(R.migrateReasoningPreferences(null), {});
  assert.deepEqual(R.migrateReasoningPreferences(['high']), {});
});

test('v2 preferences are read verbatim, including ids the old ladder could not store', () => {
  assert.deepEqual(R.readReasoningPreferences({ auto: 'thorough', 'openai/gpt-6-sol': 'none', x: 3, y: '' }), { auto: 'thorough', 'openai/gpt-6-sol': 'none' });
  assert.deepEqual(R.readReasoningPreferences('nope'), {});
});

test('cost hints: credits only under credit billing, else relative to Auto, never provider dollars', () => {
  const levels = R.levelsFor(sol);
  const auto = levels.find((l) => l.id === 'auto');
  const high = levels.find((l) => l.id === 'high');
  const thorough = levels.find((l) => l.id === 'thorough');
  assert.equal(R.levelHint(high, auto, true), 'about 9.0 credits · up to 60.0 for a large request');
  assert.equal(R.levelHint(auto, auto, true), 'about 4.0 credits · up to 20.0 for a large request');
  assert.equal(R.levelHint(high, auto, false), 'about 3× Auto');
  assert.equal(R.levelHint(thorough, auto, false), 'about 2× Auto');
  assert.equal(R.levelHint(auto, auto, false), null, 'Auto is not compared with itself');
  assert.equal(R.levelHint(levels.find((l) => l.id === 'low'), auto, true), null, 'no credits when the catalogue has none (unpriced)');
  assert.equal(R.levelHint(null, auto, true), null);
});
