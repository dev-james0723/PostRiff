const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load() {
  const file = path.join(__dirname, 'who-can-act.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const { whoCanAct } = load();

test('a proposed voice is an owner decision, whatever page it opens', () => {
  assert.deepEqual(whoCanAct({ id: 'voice-proposal', href: '/app/workspace/brand' }), { permission: 'owner', label: 'the owner' });
});

test('other items follow their destination page', () => {
  assert.equal(whoCanAct({ id: 'voice', href: '/app/workspace/brand' }).permission, 'edit');
  assert.equal(whoCanAct({ id: 'past-due', href: '/app/account/billing' }).permission, 'owner');
  assert.equal(whoCanAct({ id: 'approvals', href: '/app/queue' }).permission, 'approve');
});

test('a query string or hash does not change the destination', () => {
  assert.equal(whoCanAct({ id: 'reconnect-1', href: '/app/channels?filter=attention' }).permission, 'manage_connections');
  assert.equal(whoCanAct({ id: 'x', href: '/app/queue#job' }).permission, 'approve');
});

test('an unknown destination is null, never a guess', () => {
  assert.equal(whoCanAct({ id: 'x', href: '/app/somewhere' }), null);
});
