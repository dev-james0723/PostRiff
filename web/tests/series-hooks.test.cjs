/**
 * What a Signature Series change does to the cache (src/lib/growth-v2/series-hooks.ts `seriesChangeOptions`), against a
 * fake query client: a saved change replaces the detail, refreshes the lists and marks the workspace snapshot stale
 * (M13); a revision conflict re-reads that series and its lists so the next try uses the current revision (M14), while
 * other failures leave the cache alone; one intent keeps one idempotency key across retries.
 *
 *   node --test web/tests/series-hooks.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.join(__dirname, '..', 'src');

function load(file, modules = {}) {
  const result = ts.transpileModule(fs.readFileSync(path.join(SRC, file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  const localRequire = (name) => {
    if (name in modules) return modules[name];
    throw new Error(`unexpected import ${name} from ${file}`);
  };
  new Function('require', 'module', 'exports', result.outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}

const client = load('lib/api/client.ts');
const request = load('lib/growth-v2/request.ts', { '@/lib/api/client': client });
const series = load('lib/growth-v2/series.ts', { './request': request });
const hooks = load('lib/growth-v2/series-hooks.ts', {
  react: { useCallback: (fn) => fn, useMemo: (fn) => fn() },
  '@tanstack/react-query': {},
  '@/lib/api/hooks': { keys: { snapshot: (w) => ['snapshot', w] } },
  '@/lib/auth/session': {},
  '@/lib/workspace/provider': {},
  './request': request,
  './series': series
});

function fakeClient() {
  const calls = [];
  return {
    calls,
    setQueryData: (key, value) => calls.push({ set: key, value }),
    invalidateQueries: (filters) => {
      calls.push({ invalidate: filters.queryKey, predicate: filters.predicate });
      return Promise.resolve();
    }
  };
}

const view = { id: 's1', revision: 5 };
const conflict = () => new client.ApiError('This series changed. Read the current version first.', 409, 'revision_conflict');

test('a saved change replaces the detail, refreshes the lists and marks the workspace snapshot stale', () => {
  const qc = fakeClient();
  const options = hooks.seriesChangeOptions(qc, {}, 'w1');
  options.onSuccess({ series: view, canEdit: true, isOwner: false, result: null, replayed: false, verified: true });
  assert.deepEqual(qc.calls[0].set, ['growth-v2', 'w1', 'series', 'detail', 's1']);
  assert.deepEqual(qc.calls[0].value, { series: view, canEdit: true, isOwner: false });
  const invalidated = qc.calls.filter((c) => c.invalidate).map((c) => c.invalidate);
  assert.deepEqual(invalidated, [['growth-v2', 'w1', 'series'], ['snapshot', 'w1']]);
  const lists = qc.calls.find((c) => c.invalidate && c.invalidate.length === 3);
  // The lists refresh; the detail just written is not fetched again.
  assert.equal(lists.predicate({ queryKey: ['growth-v2', 'w1', 'series', 'list', false] }), true);
  assert.equal(lists.predicate({ queryKey: ['growth-v2', 'w1', 'series', 'detail', 's1'] }), false);
});

test('a revision conflict re-reads that series and its lists; other failures and creations change nothing', () => {
  const qc = fakeClient();
  const options = hooks.seriesChangeOptions(qc, {}, 'w1');
  options.onError(conflict(), { kind: 'approve', id: 's1', revision: 4, episodeId: 'e1' });
  assert.deepEqual(qc.calls.map((c) => c.invalidate), [['growth-v2', 'w1', 'series', 'detail', 's1'], ['growth-v2', 'w1', 'series']]);
  assert.equal(qc.calls.some((c) => c.set), false);

  const quiet = fakeClient();
  const other = hooks.seriesChangeOptions(quiet, {}, 'w1');
  other.onError(new client.ApiError('Review the similarity warnings for this draft, then confirm them.', 409, 'warnings_unacknowledged'), { kind: 'link', id: 's1', revision: 5, episodeId: 'e1', variantId: 'v1', acknowledgedWarnings: [] });
  other.onError(new client.ApiError('Nope', 500), { kind: 'plan', id: 's1', revision: 5, count: 2 });
  other.onError(conflict(), { kind: 'create', input: { origin: { kind: 'post', id: 'j1' }, audienceQuestion: 'Q?', goal: 'G' } });
  assert.deepEqual(quiet.calls, []);
  assert.equal(series.isRevisionConflict(conflict()), true);
  assert.equal(series.isRevisionConflict({ status: 409, code: 'idempotency_conflict' }), false);
  assert.equal(series.isRevisionConflict(null), false);
});

test('after a conflict the retry carries the current revision; one intent keeps one idempotency key', async () => {
  const sent = [];
  const api = { approve: async (w, id, episodeId, revision, key) => { sent.push({ revision, key }); return { series: { ...view, revision: revision + 1 } }; } };
  const options = hooks.seriesChangeOptions(fakeClient(), api, 'w1');
  const stale = { kind: 'approve', id: 's1', revision: 4, episodeId: 'e1' };
  await options.mutationFn(stale);
  await options.mutationFn(stale);   // the same intent retried: same key
  await options.mutationFn({ ...stale, revision: 5 });   // a new try after the re-read: current revision, new intent
  assert.equal(sent[0].key, sent[1].key);
  assert.notEqual(sent[2].key, sent[0].key);
  assert.deepEqual(sent.map((s) => s.revision), [4, 4, 5]);
  assert.match(sent[0].key, /^series-approve-/);
});
