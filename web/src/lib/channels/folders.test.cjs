const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load() {
  const file = path.join(__dirname, 'folders.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const F = load();
const accounts = [
  { id: 'ig-1', platform: 'Instagram', account: '@studio', connected: true },
  { id: 'ig-2', platform: 'Instagram', account: '@festival', connected: true },
  { id: 'li-1', platform: 'LinkedIn', account: 'Studio profile', connected: true },
  { id: 'th-old', platform: 'Threads', account: '@gone', connected: false }
];
const folders = [
  { id: 'f1', name: 'Festival', symbol: 'music', pinned: true, accountIds: ['ig-1', 'ig-2', 'th-old'] },
  { id: 'f2', name: 'Personal', symbol: 'heart', pinned: false, accountIds: ['ig-1', 'li-1'] }
];
test('two accounts on one platform stay two members; a shared account is counted once', () => {
  let selected = F.toggleGroup([], folders[0], accounts);
  assert.deepEqual(selected, ['ig-1', 'ig-2']);
  assert.deepEqual(F.selectionState(folders[0], selected, accounts), { state: 'all', count: 2, total: 2, missing: ['th-old'] });
  selected = F.toggleGroup(selected, folders[1], accounts);
  assert.deepEqual(selected, ['ig-1', 'ig-2', 'li-1']);
  assert.equal(F.selectionState(folders[1], selected, accounts).state, 'all');
  selected = F.toggleGroup(selected, folders[0], accounts); // all → remove members, keep unrelated
  assert.deepEqual(selected, ['li-1']);
  assert.equal(F.selectionState(folders[1], selected, accounts).state, 'mixed');
  assert.equal(F.selectionState({ accountIds: ['th-old'] }, selected, accounts).state, 'empty');
});
test('validation mirrors the server: name, length, duplicates, members, limit; stale members kept on edit', () => {
  assert.throws(() => F.validateFolder({ name: '  ', accountIds: ['ig-1'] }, folders, accounts), /name/);
  assert.throws(() => F.validateFolder({ name: 'x'.repeat(41), accountIds: ['ig-1'] }, folders, accounts), /40/);
  assert.throws(() => F.validateFolder({ name: 'festival', accountIds: ['ig-1'] }, folders, accounts), /already in use/);
  assert.throws(() => F.validateFolder({ name: 'Ghosts', accountIds: ['th-old'] }, folders, accounts), /connected account/);
  const edited = F.validateFolder({ id: 'f1', name: ' Festival  2026 ', accountIds: ['ig-2', 'th-old', 'ig-2'], symbol: 'rocket' }, folders, accounts, folders[0].accountIds);
  assert.deepEqual(edited.accountIds, ['ig-2', 'th-old']);
  assert.equal(edited.name, 'Festival 2026');
  assert.equal(edited.symbol, 'folder');
  const many = Array.from({ length: 50 }, (_, i) => ({ id: `x${i}`, name: `F${i}`, symbol: 'folder', pinned: false, accountIds: ['ig-1'] }));
  assert.throws(() => F.validateFolder({ name: 'Extra', accountIds: ['ig-1'] }, many, accounts), /50 folders/);
  assert.equal(F.copyName('Festival', folders), 'Festival copy');
});
test('shelf order, search, move rules and labels', () => {
  const four = [...folders, { id: 'f3', name: 'Work', symbol: 'briefcase', pinned: true, accountIds: ['li-1'] }, { id: 'f4', name: 'Launch', symbol: 'spark', pinned: false, accountIds: ['ig-2'] }, { id: 'f5', name: 'Extra', symbol: 'folder', pinned: false, accountIds: ['ig-1'] }];
  assert.deepEqual(F.visibleFolders(four, '', false, accounts).map((f) => f.name), ['Festival', 'Work', 'Personal', 'Launch']);
  assert.deepEqual(F.visibleFolders(four, '', true, accounts).map((f) => f.name), ['Festival', 'Work', 'Personal', 'Launch', 'Extra']);
  assert.deepEqual(F.visibleFolders(four, '@festival', false, accounts).map((f) => f.name), ['Festival', 'Launch']);
  assert.equal(F.canMove(four, 'f3', -1), true); // Work ↔ Festival inside the pinned section
  assert.equal(F.canMove(four, 'f3', 1), false); // would cross into unpinned
  assert.equal(F.selectionLabel(['ig-1', 'ig-2'], F.snapshotContext(four, ['f1'], accounts)), 'Festival');
  assert.equal(F.selectionLabel(['ig-1'], F.snapshotContext(four, ['f1'], accounts)), 'Festival, customized');
  assert.equal(F.selectionLabel(['ig-1', 'ig-2', 'li-1'], F.snapshotContext(four, ['f1', 'f2'], accounts)), '2 folders');
  assert.equal(F.selectionLabel(['ig-1'], null), '1 account');
  assert.equal(F.selectionLabel([], null), 'No accounts');
});
