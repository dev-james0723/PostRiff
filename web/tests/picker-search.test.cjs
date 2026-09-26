/**
 * Picker server search (chat-context SPEC §4.3, §5.9; PLAN S34): which queries reach the server, how its groups
 * flatten, and that server results win by id while local ones stay until it answers (or when it fails).
 *
 *   node --test web/tests/picker-search.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const SRC = path.join(WEB, 'src');
const cache = new Map();
function resolve(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`]) if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  throw new Error(`cannot resolve ${base}`);
}
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} };
  cache.set(file, mod);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }
  });
  const localRequire = (name) => {
    if (name.startsWith('@/lib/workspace')) return { useWorkspaceApi: () => ({}) };
    if (name.startsWith('@/')) return load(resolve(path.join(SRC, name.slice(2))));
    if (name.startsWith('.')) return load(resolve(path.join(path.dirname(file), name)));
    return require(require.resolve(name, { paths: [WEB] }));
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}
const S = load(path.join(SRC, 'features', 'agent', 'attachments', 'use-picker-search.ts'));
const M = load(path.join(SRC, 'features', 'agent', 'attachments', 'matcher.ts'));

test('only a Han/Kana/Hangul character or two Latin characters reach the server', () => {
  assert.equal(S.searchKey('', true), '');
  assert.equal(S.searchKey('a', true), '');
  assert.notEqual(S.searchKey('ab', true), '');
  assert.notEqual(S.searchKey('春', true), '');
  assert.equal(S.searchKey('春', false), '', 'off when the list is closed');
  assert.notEqual(S.searchKey('ab', true, ['posts']), S.searchKey('ab', true, ['sources']));
  assert.equal(S.SEARCH_DEBOUNCE_MS, 250);
});

test('server groups flatten in the list’s order, only the categories asked for', () => {
  const result = {
    query: 'x',
    verified: true,
    categories: {
      sources: [{ kind: 'source', id: 's1', label: 'Notes' }],
      posts: [{ kind: 'post', id: 'p1', label: 'Spring' }],
      accounts: [{ kind: 'account', id: 'a1', label: 'Instagram · piano' }]
    }
  };
  assert.deepEqual(S.serverItems(result).map((i) => i.id), ['p1', 'a1', 's1']);
  assert.deepEqual(S.serverItems(result, ['sources']).map((i) => i.id), ['s1']);
  assert.deepEqual(S.serverItems(null), []);
});

test('server results win by id; local ones show until it answers or when it fails', () => {
  const local = [{ kind: 'post', id: 'p1', label: 'Local label' }, { kind: 'post', id: 'p2', label: 'Only local' }];
  const server = [{ kind: 'post', id: 'p1', label: 'Server label' }, { kind: 'post', id: 'p3', label: 'Only server' }];
  assert.deepEqual(M.mergeResults(local, null).map((i) => i.label), ['Local label', 'Only local']);
  assert.deepEqual(M.mergeResults(local, server).map((i) => i.label), ['Server label', 'Only server', 'Only local']);
});

test('the mention list and the sheet’s search views use it', () => {
  const hook = fs.readFileSync(path.join(SRC, 'features', 'agent', 'attachments', 'use-composer-attachments.ts'), 'utf8');
  const sheet = fs.readFileSync(path.join(SRC, 'features', 'agent', 'attachments', 'plus-sheet.tsx'), 'utf8');
  assert.match(hook, /usePickerSearch\(mention\.query, localItems, \{ enabled: open \}\)/);
  assert.match(sheet, /usePickerSearch\(query, local, \{/);
});
