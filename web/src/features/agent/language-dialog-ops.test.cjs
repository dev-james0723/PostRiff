const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load() {
  const file = path.join(__dirname, 'language-dialog-ops.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const O = load();
const items = [
  { platform: 'LinkedIn', languages: ['en-US'] },
  { platform: 'Instagram', channelId: 'ig-1', languages: ['zh-Hant-HK', 'en-US'] },
  { key: 'ig-2', platform: 'Instagram', channelId: 'ig-2', languages: null }
];
const current = (item) => item.languages ?? ['ja-JP'];

test('keys: the hook key wins, then platform + account, then platform; the API target is key or platform', () => {
  assert.equal(O.stateKey(items[0]), 'LinkedIn');
  assert.equal(O.stateKey(items[1]), 'Instagram:ig-1');
  assert.equal(O.stateKey(items[2]), 'ig-2');
  assert.equal(O.apiTarget(items[0]), 'LinkedIn');
  assert.equal(O.apiTarget(items[1]), 'Instagram');
  assert.equal(O.apiTarget(items[2]), 'ig-2');
});

test('no staged difference plans nothing; a shared language becomes one useEverywhere', () => {
  const staged = { LinkedIn: ['en-US'], 'Instagram:ig-1': ['zh-Hant-HK', 'en-US'], 'ig-2': ['ja-JP'] };
  assert.deepEqual(O.planLanguageOps(items, current, staged, null), []);
  assert.deepEqual(O.planLanguageOps(items, current, staged, 'fr-FR'), [{ kind: 'everywhere', tag: 'fr-FR' }]);
  const same = [{ platform: 'Threads', languages: ['fr-FR'] }];
  assert.deepEqual(O.planLanguageOps(same, current, {}, 'fr-FR'), [], 'already shared everywhere: nothing to save');
  assert.deepEqual(O.planLanguageOps([], current, {}, 'fr-FR'), []);
});

test('changes, additions and removals are planned per destination, removals from the end', () => {
  const staged = { LinkedIn: ['de-DE', 'fr-FR'], 'Instagram:ig-1': ['zh-Hant-HK'], 'ig-2': ['ko-KR'] };
  const ops = O.planLanguageOps(items, current, staged, null);
  assert.deepEqual(
    ops.map((op) => [op.kind, O.apiTarget(op.item), op.index ?? op.tag, op.tag]),
    [
      ['change', 'LinkedIn', 0, 'de-DE'],
      ['add', 'LinkedIn', 'fr-FR', 'fr-FR'],
      ['remove', 'Instagram', 1, undefined],
      ['change', 'ig-2', 0, 'ko-KR']
    ]
  );
});

test('staged lists are deduped and capped like the hook; an emptied list is ignored', () => {
  assert.deepEqual(O.cleanLanguages(['a', 'b', 'a', 'c', 'd', 'e']), ['a', 'b', 'c', 'd']);
  const ops = O.planLanguageOps([items[0]], current, { LinkedIn: [] }, null);
  assert.deepEqual(ops, []);
});

test('runLanguageOp addresses the hook by the API target', () => {
  const calls = [];
  const api = {
    languagesOf: () => [],
    change: (...a) => calls.push(['change', ...a]),
    add: (...a) => calls.push(['add', ...a]),
    remove: (...a) => calls.push(['remove', ...a]),
    useEverywhere: (...a) => calls.push(['everywhere', ...a])
  };
  O.runLanguageOp(api, { kind: 'change', item: items[1], index: 1, tag: 'fr-FR' });
  O.runLanguageOp(api, { kind: 'add', item: items[2], tag: 'fr-FR' });
  O.runLanguageOp(api, { kind: 'remove', item: items[0], index: 0 });
  O.runLanguageOp(api, { kind: 'everywhere', tag: 'de-DE' });
  assert.deepEqual(calls, [['change', 'Instagram', 1, 'fr-FR'], ['add', 'ig-2', 'fr-FR'], ['remove', 'LinkedIn', 0], ['everywhere', 'de-DE']]);
});
