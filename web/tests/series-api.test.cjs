/**
 * The Signature Series client (src/lib/growth-v2/series.ts) against a fake fetch: the documented routes, ids encoded so
 * a hostile id cannot leave its path segment, the session and guard headers, the series revision and idempotency key on
 * every change, and feature_disabled recognised so the UI hides itself.
 *
 *   node --test web/tests/series-api.test.cjs
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

function harness(responses = []) {
  const calls = [];
  const queue = [...responses];
  global.fetch = async (url, init = {}) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : undefined });
    const next = queue.shift() ?? { status: 200, body: {} };
    return new Response(JSON.stringify(next.body), { status: next.status, headers: { 'Content-Type': 'application/json' } });
  };
  return { calls, api: series.createSeriesApi(async () => 'session-token') };
}

test('reads use the documented routes with the session, the guard header and no-store', async () => {
  const { calls, api } = harness();
  await api.list('w/1', { cursor: 'abc', archived: true });
  await api.list('w1');
  await api.get('w1', 's/../x');
  await api.posts('w1', { minAgeDays: 60 });
  await api.sources('w1', { cursor: 'c2' });
  await api.checkDraft('w1', 's1', 'e/1', 'v?1');
  assert.deepEqual(calls.map((c) => c.url), [
    '/api/workspaces/w%2F1/series?limit=25&cursor=abc&archived=1',
    '/api/workspaces/w1/series?limit=25',
    '/api/workspaces/w1/series/s%2F..%2Fx',
    '/api/workspaces/w1/series/candidates?kind=post&minAgeDays=60',
    '/api/workspaces/w1/series/candidates?kind=source&cursor=c2',
    '/api/workspaces/w1/series/s1/episodes/e%2F1/drafts/v%3F1/check'
  ]);
  for (const call of calls) {
    assert.equal(call.init.headers.Authorization, 'Bearer session-token');
    assert.equal(call.init.headers['X-PostRiff-Request'], 'founder-alpha');
    assert.equal(call.init.cache, 'no-store');
  }
});

test('every change posts its series revision and one idempotency key', async () => {
  const { calls, api } = harness();
  const w = 'w1';
  await api.create(w, { origin: { kind: 'post', id: 'j1' }, audienceQuestion: 'Q?', goal: 'G' }, 'key-create-1');
  await api.plan(w, 's1', 4, 3, 'key-plan-0001');
  await api.setStatus(w, 's1', 5, 'paused', 'key-status-01');
  await api.decide(w, 's1', 'e1', 6, 'do_not_repeat', 'role', 'key-decide-01');
  await api.approve(w, 's1', 'e1', 7, 'key-approve-1');
  await api.link(w, 's1', 'e1', 8, 'v1', ['similar_to_original:j1'], 'key-link-0001');
  await api.unlink(w, 's1', 'e1', 9, 'v1', 'key-unlink-01');
  await api.claim(w, 's1', 'cl_1', 10, { action: 'reviewed', reviewBy: '2027-01-01' }, 'key-claim-001');
  await api.revoke(w, 's1', 'sd_1', 11, 'key-revoke-01');
  assert.deepEqual(calls.map((c) => [c.init.method, c.url.replace('/api/workspaces/w1/series', '')]), [
    ['POST', ''], ['POST', '/s1/plan'], ['POST', '/s1/status'], ['POST', '/s1/episodes/e1/angle'], ['POST', '/s1/episodes/e1/approve'],
    ['POST', '/s1/episodes/e1/drafts'], ['POST', '/s1/episodes/e1/drafts/v1/unlink'], ['POST', '/s1/claims/cl_1'], ['POST', '/s1/decisions/sd_1/revoke']
  ]);
  assert.deepEqual(calls[0].body, { origin: { kind: 'post', id: 'j1' }, audienceQuestion: 'Q?', goal: 'G', idempotencyKey: 'key-create-1' });
  assert.equal(calls[0].body.expectedRevision, undefined);
  calls.slice(1).forEach((call, i) => assert.equal(call.body.expectedRevision, i + 4));
  assert.equal(calls[1].body.count, 3);
  assert.deepEqual(calls[3].body, { decision: 'do_not_repeat', level: 'role', expectedRevision: 6, idempotencyKey: 'key-decide-01' });
  assert.deepEqual(calls[5].body.acknowledgedWarnings, ['similar_to_original:j1']);
  assert.deepEqual(calls[7].body, { action: 'reviewed', reviewBy: '2027-01-01', expectedRevision: 10, idempotencyKey: 'key-claim-001' });
  for (const call of calls) assert.equal(call.init.headers['Content-Type'], 'application/json');
});

test('feature_disabled and conflicts surface as typed errors, never as success', async () => {
  const { api } = harness([
    { status: 404, body: { error: 'This feature is not available.', code: 'feature_disabled' } },
    { status: 409, body: { error: 'This series changed. Read the current version first.', code: 'revision_conflict' } }
  ]);
  await assert.rejects(api.list('w1'), (error) => request.isFeatureDisabled(error));
  await assert.rejects(api.approve('w1', 's1', 'e1', 1, 'key-approve-2'), (error) => error.status === 409 && error.code === 'revision_conflict' && !request.isFeatureDisabled(error));
});
