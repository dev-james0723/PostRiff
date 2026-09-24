const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.resolve(__dirname, '..', '..', '..');
const cache = new Map();

/** React-only modules the pure helpers never call at module level; stubbed so the loader stays small. */
const STUBS = {
  '@/lib/workspace/provider': {
    useWorkspaceApi() {
      throw new Error('hooks are not exercised here');
    }
  }
};

/** Loads a TypeScript module with `@/` imports resolved against `web/src` (types-only imports are erased). */
function load(file) {
  const resolved = path.resolve(file);
  if (cache.has(resolved)) return cache.get(resolved).exports;
  const result = ts.transpileModule(fs.readFileSync(resolved, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } });
  const mod = { exports: {} };
  cache.set(resolved, mod);
  const localRequire = (spec) => {
    if (STUBS[spec]) return STUBS[spec];
    if (spec.startsWith('@/')) return load(path.join(SRC, `${spec.slice(2)}.ts`));
    if (spec.startsWith('.')) return load(path.join(path.dirname(resolved), `${spec}.ts`));
    return require(spec);
  };
  new Function('require', 'module', 'exports', result.outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}

const H = load(path.join(__dirname, 'helpers.ts'));
const D = load(path.join(SRC, 'features', 'agent', 'use-destinations.ts'));

const draftable = H.draftableFrom(['LinkedIn', 'Instagram', 'Threads', 'Xiaohongshu']);
const channels = [
  { id: 'ig-1', platform: 'Instagram', account: '@studio', displayState: 'Ready for posting' },
  { id: 'ig-2', platform: 'Instagram', account: '@festival', displayState: 'Finish setup' },
  { id: 'li-1', platform: 'LinkedIn', account: 'Studio profile', displayState: 'Ready for posting' },
  { id: 'fb-1', platform: 'Facebook', account: 'Studio page', displayState: 'Ready for posting' },
  { id: 'th-old', platform: 'Threads', account: '@gone', displayState: 'Reconnect', revoked: true }
];
const accounts = H.toFolderAccounts(channels);

test('accounts come from the snapshot: connected until revoked, state kept as the provider reports it', () => {
  assert.deepEqual(accounts[0], { id: 'ig-1', platform: 'Instagram', account: '@studio', state: 'Ready for posting', connected: true });
  assert.equal(accounts[4].connected, false);
  assert.deepEqual(H.toFolderAccounts(undefined), []);
});

test('member status separates gone connections from platforms drafting cannot write for yet', () => {
  assert.equal(H.memberStatus('ig-1', accounts, draftable), 'ready');
  assert.equal(H.memberStatus('th-old', accounts, draftable), 'missing');
  assert.equal(H.memberStatus('nope', accounts, draftable), 'missing');
  assert.equal(H.memberStatus('fb-1', accounts, draftable), 'unavailable');
  const pickable = H.pickableAccounts(accounts, draftable);
  assert.deepEqual(pickable.map((a) => a.connected), [true, true, true, false, false]);
  assert.equal(H.draftReason('Facebook'), 'Drafting is not available for Facebook yet');
});

test('a folder reading counts only selectable members and names the rest', () => {
  const folder = { accountIds: ['ig-1', 'ig-2', 'fb-1', 'th-old', 'gone'] };
  const none = H.readFolder(folder, [], accounts, draftable);
  assert.deepEqual({ state: none.state, count: none.count, total: none.total }, { state: 'none', count: 0, total: 2 });
  assert.deepEqual(none.missing, ['th-old', 'gone']);
  assert.deepEqual(none.unavailable, ['fb-1']);
  assert.equal(H.folderStateText(none), '2 accounts');
  assert.equal(H.membersNote(none), '2 no longer connected · 1 not available for drafting');
  const some = H.readFolder(folder, ['ig-1', 'li-1'], accounts, draftable);
  assert.equal(H.folderStateText(some), '1 of 2 selected');
  const all = H.readFolder(folder, ['ig-1', 'ig-2'], accounts, draftable);
  assert.equal(H.folderStateText(all), '2 selected');
  assert.equal(H.membersNote({ missing: [], unavailable: [] }), null);
  assert.equal(H.membersNote({ missing: ['x'], unavailable: [] }), '1 no longer connected');
  assert.equal(H.folderStateText(H.readFolder({ accountIds: ['th-old'] }, [], accounts, draftable)), 'No accounts to select');
  assert.equal(H.folderStateText({ state: 'none', count: 0, total: 1 }), '1 account');
});

test('the inspector sits after the row that holds the inspected card', () => {
  assert.equal(H.inspectorSlot(0, 3), 1); // first row: after card 1
  assert.equal(H.inspectorSlot(1, 3), 1);
  assert.equal(H.inspectorSlot(2, 3), 2); // incomplete last row: after the last card
  assert.equal(H.inspectorSlot(2, 4), 3);
  assert.equal(H.inspectorSlot(4, 5, 2), 4);
  assert.equal(H.inspectorSlot(1, 6, 3), 2); // three columns
  assert.equal(H.inspectorSlot(-1, 3), -1); // nothing inspected
  assert.equal(H.inspectorSlot(0, 0), -1);
  assert.equal(H.inspectorSlot(5, 3), -1);
});

test('words: Done label, toggle feedback, peek marks', () => {
  assert.equal(H.doneLabel(0), 'Done · 0 accounts selected');
  assert.equal(H.doneLabel(1), 'Done · 1 account selected');
  assert.equal(H.doneLabel(3), 'Done · 3 accounts selected');
  assert.equal(H.toggleFeedback(false, 2), 'Added 2 accounts. Overlapping folders updated.');
  assert.equal(H.toggleFeedback(true, 1), 'Removed 1 account. Overlapping folders updated.');
  const peek = H.peekAccounts({ accountIds: ['ig-1', 'gone', 'li-1', 'fb-1', 'ig-2'] }, accounts);
  assert.deepEqual(peek.shown.map((a) => a.id), ['ig-1', 'li-1', 'fb-1']);
  assert.equal(peek.more, 1);
  assert.deepEqual(Object.keys(H.SYMBOL_LABELS), ['folder', 'spark', 'music', 'briefcase', 'heart', 'globe']);
});

test('stored destinations decode tolerantly and never carry anything but ids, platforms and a context', () => {
  const empty = { selected: [], platformOnly: [], context: null };
  assert.deepEqual(D.decodeDestinations(null), empty);
  assert.deepEqual(D.decodeDestinations('not json'), empty);
  assert.deepEqual(D.decodeDestinations(JSON.stringify({ version: 2, selected: ['a'] })), empty);
  const stored = D.decodeDestinations(JSON.stringify({ version: 1, selected: ['ig-1', 'ig-1', 7, 'li-1'], platformOnly: ['Threads'], context: { sources: [{ id: 'f1', name: 'Festival', accountIds: ['ig-1', null] }, { id: 3 }] } }));
  assert.deepEqual(stored, { selected: ['ig-1', 'li-1'], platformOnly: ['Threads'], context: { sources: [{ id: 'f1', name: 'Festival', accountIds: ['ig-1'] }] } });
  assert.equal(D.destinationsStorageKey('ws-1'), 'rafii.destinations.ws-1');
});
