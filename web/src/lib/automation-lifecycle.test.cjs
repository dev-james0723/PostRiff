const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load() {
  const file = path.join(__dirname, 'automation-lifecycle.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const L = load();
// The vectors lifecycle.py is tested against (tests/test_postriff_orchestration*.py), from the repository root.
const V = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '..', 'tests', 'fixtures', 'automation_lifecycle.json'), 'utf8'));

test('the same states, transitions, priority, attention set, labels and job map as lifecycle.py', () => {
  assert.deepEqual([...L.ITEM_STATES], V.itemStates);
  assert.deepEqual([...L.RUN_STAGES], V.runStages);
  assert.deepEqual(Object.fromEntries(Object.entries(L.TRANSITIONS).map(([k, v]) => [k, [...v]])), V.transitions);
  assert.deepEqual([...L.PRIORITY], V.priority);
  assert.deepEqual([...L.ATTENTION], V.attention);
  assert.deepEqual(L.LABELS, V.labels);
  assert.deepEqual(L.JOB_ITEM, V.jobItem);
});

test('every move vector: allowed moves only, never review → scheduled without an approval', () => {
  assert.ok(V.moves.length > 0);
  for (const move of V.moves) assert.equal(L.canMove(move.from, move.to), move.allowed, `${move.from} → ${move.to}`);
  assert.equal(L.canMove('ready_for_review', 'scheduled'), false);
  assert.equal(L.canMove('not_a_state', 'approved'), false);
});

test('every status vector', () => {
  for (const item of V.status) assert.equal(L.status(item.run), item.status, JSON.stringify(item.run));
  assert.equal(L.status({}), 'planned');
});

test('every attention vector', () => {
  for (const item of V.attentionCases) assert.equal(L.attention(item.run), item.attention, JSON.stringify(item.run));
});

test('every projected vector', () => {
  for (const item of V.projected) assert.equal(L.projected(item.run), item.projected, JSON.stringify(item.run));
  assert.equal(L.projected({ state: 'held' }), 'held');
});

test('every job vector: held depends on the channel, unknown states map to nothing', () => {
  for (const item of V.jobCases) assert.equal(L.jobItemState(item.job, item.channelReady), item.item, `${item.job} / ${item.channelReady}`);
});

test('labels for every state, and decisions only where raffi_run_decide accepts them', () => {
  for (const state of [...V.itemStates, ...V.runStages]) assert.equal(L.label(state), V.labels[state]);
  assert.equal(L.label('something_new'), 'something new');
  assert.deepEqual(L.decisionsFor({ state: 'ready_for_review' }), { approve: true, revise: true, reject: true });
  assert.deepEqual(L.decisionsFor({ state: 'platform_disconnected' }), { approve: true, revise: true, reject: true });
  assert.deepEqual(L.decisionsFor({ state: 'approved' }), { approve: false, revise: true, reject: true });
  assert.deepEqual(L.decisionsFor({ state: 'platform_disconnected', jobId: 'job-1' }), { approve: false, revise: false, reject: false });
  assert.deepEqual(L.decisionsFor({ state: 'scheduled' }), { approve: false, revise: false, reject: false });
});
