const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const { renderToStaticMarkup } = require('react-dom/server');

const root = path.resolve(__dirname, '../src');
const view = fs.readFileSync(path.join(root, 'features/agent/conversation-view.tsx'), 'utf8');
const tree = ts.createSourceFile('conversation-view.tsx', view, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function find(predicate) {
  let found;
  function visit(node) { if (predicate(node)) found = node; else ts.forEachChild(node, visit); }
  visit(tree);
  assert.ok(found, 'expected the actual conversation handler/render path');
  return found;
}
function compile(source, imports = {}) {
  const m = new Module(__filename);
  m.require = id => id in imports ? imports[id] : require(id);
  // eslint-disable-next-line no-underscore-dangle -- Compile the actual TS handler without a browser or network.
  m._compile(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, __filename);
  return m.exports;
}
const submitConversationTurn = compile(fs.readFileSync(path.join(root, 'features/agent/credit-turn.ts'), 'utf8')).submitConversationTurn;
const stateMessage = compile(fs.readFileSync(path.join(root, 'components/rafii/state-message.tsx'), 'utf8'), {
  '@/components/icons': { Icons: new Proxy({}, { get: () => () => null }) },
  '@/components/ui/skeleton': { Skeleton: () => null },
  '@/lib/utils': { cn: (...values) => values.filter(Boolean).join(' ') }
});
const errorExpression = find(node => ts.isJsxExpression(node) && node.expression?.getText(tree).startsWith('submitError?.workspaceId')).expression.getText(tree);
const { renderError } = compile(`const { StateMessage } = require('state-message');
exports.renderError = (submitError, workspaceId, conversationId) => (${errorExpression});`, { 'state-message': stateMessage });
const handler = ts.transpileModule(find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'sendTurn').getText(tree), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 }
}).outputText;

function harness() {
  const state = { text: 'From now on, keep my LinkedIn posts under 30 words.', busy: false, error: null, current: true, fail: true, calls: 0, invalidations: [] };
  const failure = Object.assign(new Error('The model request failed (502).'), { name: 'ApiError', status: 502, code: 'bad_gateway' });
  const api = { turn: async () => { state.calls++; if (state.fail) throw failure; return { status: 'memory' }; } };
  const deps = {
    text: state.text, busy: false, running: false, choice: { available: true, requestFields: {} },
    parseSlash: () => null, setText: update => { state.text = typeof update === 'function' ? update(state.text) : update; },
    setCreditLimit() {}, gate: { enter: () => true, alive: () => state.current, leave() {} },
    setSubmitError: error => { state.error = error; }, setBusy: value => { state.busy = value; },
    voiceLearningIntent: () => null, languages: { selection: ['LinkedIn'] }, creditInvalid: false, creditMode: false, imageRequested: false,
    attachmentsOn: false, turnPayload: text => ({ text }), crypto: { randomUUID: () => 'one-idempotency-key' },
    submitConversationTurn, api, workspaceId: 'workspace-a', conversationId: 'conversation-a', maximum: null,
    client: { invalidateQueries: async ({ queryKey }) => { state.invalidations.push(queryKey); }, setQueryData() {} },
    keys: { messages: (w, c) => ['messages', w, c], usage: w => ['usage', w], memoryProposals: w => ['proposals', w], memory: w => ['memory', w] },
    setImageRequested() {}, setVariantIndex() {}, anchor: null, toast: { error() {} },
    agent: { api }, timeZone: 'UTC', commandPayload: () => ({ name: 'test' })
  };
  return {
    state, deps, api,
    send: () => new Function(...Object.keys(deps), `${handler}; return sendTurn;`)(...Object.values(deps))(),
    errorHtml: (workspace = 'workspace-a', conversation = 'conversation-a') => renderToStaticMarkup(renderError(state.error, workspace, conversation))
  };
}

test('a typed application 502 remains visible, preserves the message, and refreshes persisted turn/usage without resubmission', async () => {
  const h = harness();
  const text = h.state.text;
  await h.send();
  assert.equal(h.state.calls, 1);
  assert.equal(h.state.busy, false);
  assert.equal(h.state.text, text);
  assert.deepEqual(h.state.invalidations, [['messages', 'workspace-a', 'conversation-a'], ['usage', 'workspace-a']]);
  assert.match(h.errorHtml(), /role="alert"/);
  assert.match(h.errorHtml(), /Couldn’t complete this turn/);
  assert.match(h.errorHtml(), /The model request failed \(502\)/);
});

test('only a subsequent accepted attempt clears the persistent failure', async () => {
  const h = harness();
  await h.send();
  assert.ok(h.state.error);
  h.state.fail = false;
  await h.send();
  assert.equal(h.state.calls, 2);
  assert.equal(h.state.error, null);
  assert.equal(h.state.text, '');
  assert.equal(h.errorHtml(), '');
});

test('a failed turn never leaks its alert into another workspace or conversation', async () => {
  const h = harness();
  await h.send();
  assert.equal(h.errorHtml('workspace-b'), '');
  assert.equal(h.errorHtml('workspace-a', 'conversation-b'), '');
  const leaving = harness();
  leaving.api.turn = async () => { leaving.state.calls++; leaving.state.current = false; throw Error('Late failure'); };
  await leaving.send();
  assert.equal(leaving.state.error, null);
  assert.deepEqual(leaving.state.invalidations, []);
});

test('agent command failures use the same persistent error and reconciliation path', async () => {
  const h = harness();
  h.deps.parseSlash = () => ({ command: { kind: 'agent' } });
  await h.send();
  assert.equal(h.state.calls, 1);
  assert.equal(h.state.busy, false);
  assert.match(h.errorHtml(), /role="alert"/);
  assert.deepEqual(h.state.invalidations, [['messages', 'workspace-a', 'conversation-a'], ['usage', 'workspace-a']]);
});
