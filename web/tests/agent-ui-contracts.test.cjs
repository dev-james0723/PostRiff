/** rafii-genui/1: the browser contract matches the frozen fixture the Python side is also checked against. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const FIXTURES = path.join(WEB, '..', 'tests', 'fixtures', 'agent_ui', 'contracts');
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIXTURES, name), 'utf8'));

function load(file) {
  const filename = path.join(WEB, file);
  const source = fs.readFileSync(filename, 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  const exports = {};
  const context = vm.createContext({ console });
  vm.runInContext(`(function(require, exports, module){${code}\n})`, context, { filename })(
    (name) => require(require.resolve(name, { paths: [WEB] })),
    exports,
    { exports },
  );
  return exports;
}

const contracts = load('src/lib/agent-runtime/ui-contracts.ts');

test('contract manifest equals the frozen fixture', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(contracts.contractManifest())), fixture('contract-manifest.json'));
});

test('canonical JSON agrees with the Python vectors', () => {
  for (const vector of fixture('vectors.json').canonical) {
    assert.equal(contracts.canonicalJson(vector.value), vector.canonical);
  }
});

test('event ids and terminal kinds', () => {
  assert.equal(contracts.parseEventId(contracts.eventId('6c1f2f3e-1111-4222-8333-944455556666', 7)), 7);
  assert.equal(contracts.parseEventId('nope'), null);
  assert.equal(contracts.isTerminalEvent('ui.ready'), true);
  assert.equal(contracts.isTerminalEvent('ui.delta'), false);
  assert.equal(contracts.canTransition('ready', 'streaming'), false);
});

test('the frozen SSE frame parses as a valid UiEventV1', () => {
  const frame = fixture('vectors.json').sseFrame.frame;
  const data = frame.split('\n').find((line) => line.startsWith('data: '));
  const parsed = contracts.uiEventSchema.safeParse(JSON.parse(data.slice(6)));
  assert.equal(parsed.success, true);
});

test('an action result cannot be forged verified by schema alone', () => {
  const prepared = { actionId: 'schedule_propose', idempotencyKey: 'k'.repeat(20), outcome: 'prepared', verified: false,
    receiptRef: null, proposalRef: 'p1', changedRefs: [], invalidationKeys: [], nextContext: {} };
  assert.equal(contracts.uiActionResultSchema.safeParse(prepared).success, true);
  assert.equal(contracts.uiActionResultSchema.safeParse({ ...prepared, outcome: 'published' }).success, false);
});
