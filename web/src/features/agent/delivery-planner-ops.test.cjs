const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load() {
  const file = path.join(__dirname, 'delivery-planner-ops.ts');
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS }
  }).outputText;
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', code)(require, mod, mod.exports);
  return mod.exports;
}

const P = load();
const a = { key: 'li-a', platform: 'LinkedIn', channelId: 'li-a', languages: ['en-US'] };
const b = { key: 'li-b', platform: 'LinkedIn', channelId: 'li-b', languages: ['zh-Hant-HK'] };
const threads = { key: 'Threads', platform: 'Threads', languages: null };

test('account ids keep same-platform destinations distinct and additions dedupe by key', () => {
  const value = P.addDeliveryTarget(P.addDeliveryTarget([a], b), b);
  assert.deepEqual(value, [a, b]);
  assert.equal(P.deliveryTargetSignature(value), 'li-a\u001fli-b');
});

test('removal never leaves the staged planner with zero destinations', () => {
  assert.deepEqual(P.removeDeliveryTarget([a], 'li-a'), [a]);
  assert.deepEqual(P.removeDeliveryTarget([a, b], 'li-a'), [b]);
});

test('commit values preserve channelId and platform-only targets', () => {
  assert.deepEqual(P.deliveryTargets([a, threads]), [
    { platform: 'LinkedIn', channelId: 'li-a' },
    { platform: 'Threads' }
  ]);
});
