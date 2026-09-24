const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load() {
  const file = path.join(__dirname, 'reasoning-map.ts');
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
