/** Actual useRecords options through QueryObserver with deferred local-only reads. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const query = require('@tanstack/react-query');

const directory = path.join(__dirname, '../src/features/founder/customers/kit');
let session;
let reads;
function load(file) {
  const { outputText } = ts.transpileModule(fs.readFileSync(path.join(directory, file), 'utf8'), {
    fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  const dependencies = {
    react: { useMemo: (factory) => factory() },
    '@tanstack/react-query': { ...query, useQuery: (options) => options },
    '@/features/founder/shell/founder-session': { useFounderSession: () => session },
    '@/lib/founder/api': { founderKeys: {}, founderFetch: (url, init) => new Promise((resolve, reject) => reads.push({ url, init, resolve, reject })) }
  };
  new Function('require', 'module', 'exports', outputText)((name) => {
    if (name in dependencies) return dependencies[name];
    if (name.startsWith('.')) return load(name + '.ts');
    return require(name);
  }, mod, mod.exports);
  return mod.exports;
}
const { useRecords } = load('api.ts');
const input = (page = 1, collection = 'customers') => ({ collection, page, search: '', status: 'all', recordId: '' });
const envelope = (mode, environment, id) => ({ environment, dataState: mode === 'demo' ? 'synthetic' : 'measured', data: { mode, rows: [{ id }], workspaces: [], total: 1, page: 1, pageSize: 50, statuses: [] } });
function options(mode, environment, body = input(), ready = true) {
  session = { api: {}, mode, environment, capabilities: [], sessionStatus: ready ? 'ready' : 'loading' };
  return useRecords(body);
}

for (const [name, before, after] of [
  ['Live to Demo', ['live', 'production', input()], ['demo', 'production', input()]],
  ['Demo to Live', ['demo', 'production', input()], ['live', 'production', input()]],
  ['staging to production', ['live', 'staging', input()], ['live', 'production', input()]],
  ['customers to workspaces', ['live', 'production', input()], ['live', 'production', input(1, 'workspaces')]]
]) {
  test(`${name} clears previous records while the new read is pending, then shows only its answer`, async () => {
    reads = [];
    const client = new query.QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } });
    const previous = options(...before);
    client.setQueryData(previous.queryKey, envelope(before[0], before[1], 'old-scope-record'));
    const observer = new query.QueryObserver(client, previous);
    const unsubscribe = observer.subscribe(() => {});
    try {
      const next = options(...after);
      observer.setOptions(next);
      assert.equal(observer.getCurrentResult().data, undefined, 'records from the previous mode, environment or collection must not render');
      assert.equal(observer.getCurrentResult().isPlaceholderData, false);
      assert.equal(reads.length, 1);
      const pending = client.fetchQuery(next);
      reads[0].resolve(envelope(after[0], after[1], 'new-scope-record'));
      await pending;
      assert.equal(observer.getCurrentResult().data.data.rows[0].id, 'new-scope-record');
      assert.equal(observer.getCurrentResult().data.data.mode, after[0]);
      assert.equal(observer.getCurrentResult().data.environment, after[1]);
    } finally { unsubscribe(); client.clear(); }
  });
}

test('same-scope pagination keeps the previous page only until the new page arrives', async () => {
  reads = [];
  const client = new query.QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } });
  const first = options('live', 'production', input(1));
  const oldPage = envelope('live', 'production', 'page-one');
  client.setQueryData(first.queryKey, oldPage);
  const observer = new query.QueryObserver(client, first);
  const unsubscribe = observer.subscribe(() => {});
  try {
    const next = options('live', 'production', input(2));
    observer.setOptions(next);
    assert.equal(observer.getCurrentResult().data, oldPage);
    assert.equal(observer.getCurrentResult().isPlaceholderData, true);
    const pending = client.fetchQuery(next);
    reads[0].resolve(envelope('live', 'production', 'page-two'));
    await pending;
    assert.equal(observer.getCurrentResult().data.data.rows[0].id, 'page-two');
    assert.equal(observer.getCurrentResult().isPlaceholderData, false);
  } finally { unsubscribe(); client.clear(); }
});

test('a new-scope failed read leaves an error and never restores old records', async () => {
  reads = [];
  const client = new query.QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } });
  const first = options('live', 'production');
  client.setQueryData(first.queryKey, envelope('live', 'production', 'live-record'));
  const observer = new query.QueryObserver(client, first);
  const unsubscribe = observer.subscribe(() => {});
  try {
    const next = options('demo', 'production');
    observer.setOptions(next);
    assert.equal(observer.getCurrentResult().data, undefined);
    const pending = client.fetchQuery(next);
    reads[0].reject(new Error('Synthetic delayed source failure'));
    await assert.rejects(pending, /Synthetic delayed source failure/);
    assert.equal(observer.getCurrentResult().data, undefined);
    assert.equal(observer.getCurrentResult().isError, true);
  } finally { unsubscribe(); client.clear(); }
});

test('disabled and unverified-session reads do not carry a prior page', () => {
  const prior = envelope('live', 'production', 'live-record');
  const previousQuery = { queryKey: ['founder', 'live', 'production', 'records', input()] };
  for (const next of [options('live', 'production', null), options('live', 'production', input(), false)]) {
    assert.equal(next.placeholderData(prior, previousQuery), undefined);
    assert.equal(next.enabled, false);
  }
});
