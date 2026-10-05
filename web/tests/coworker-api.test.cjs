/**
 * The coworker API client (src/lib/coworker/api.ts) against a fake fetch: exact routes from API.md, the session
 * guard headers, ids encoded so a hostile id cannot leave its path segment, feature_disabled recognised, and client
 * errors not retried.
 *
 *   node --test web/tests/coworker-api.test.cjs
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
const zod = require('zod');
const trendTypes = load('lib/coworker/trend-types.ts', { zod });
const reviewContract = load('lib/analytics/review-contract.ts', { zod, '../coworker/trend-types': trendTypes });
const coworker = load('lib/coworker/api.ts', { '@/lib/api/client': client, '@/lib/analytics/review-contract': reviewContract });

function harness(responses = []) {
  const calls = [];
  const queue = [...responses];
  global.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    const next = queue.shift() ?? { status: 200, body: {} };
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), { status: next.status, headers: { 'Content-Type': 'application/json', ...(next.headers ?? {}) } });
  };
  return { calls, api: coworker.createCoworkerApi(async () => 'session-token') };
}

test('growth loop commands retain idempotency keys, use guarded sessions and encode workspace and entity ids', async () => {
  const { calls, api } = harness();
  const w = 'workspace/../other';
  await api.growthLoop(w);
  await api.createGrowthGoal(w, { name: 'Publish consistently', goalType: 'consistency', primaryMetric: 'verified_posts', baselineValue: 0, targetValue: 6, targetAt: '2030-01-01', idempotencyKey: 'request-0001' });
  await api.proposeGrowthExperiment(w, { hypothesisId: 'h1', minimumPerArm: 5, windowDays: 14, idempotencyKey: 'request-0002' });
  await api.growthExperimentAction(w, 'e/../other', 'apply');
  await api.generateGrowthProof(w, 'monthly');
  await api.growthProofAction(w, 'p/../other', 'opened');
  assert.equal(calls[0].url, '/api/workspaces/workspace%2F..%2Fother/coworker/growth-loop');
  assert.equal(JSON.parse(calls[1].init.body).idempotencyKey, 'request-0001');
  assert.equal(JSON.parse(calls[2].init.body).idempotencyKey, 'request-0002');
  assert.ok(calls[3].url.endsWith('/experiments/e%2F..%2Fother/action'));
  assert.deepEqual(JSON.parse(calls[4].init.body), { frequency: 'monthly' });
  assert.ok(calls[5].url.endsWith('/proofs/p%2F..%2Fother/action'));
  for (const call of calls) assert.equal(call.init.headers.Authorization, 'Bearer session-token');
});

test('reads go to the documented routes with the guard header, the session and no-store', async () => {
  const { calls, api } = harness([{ status: 200, body: { recipes: [], weeks: [] } }]);
  await api.weekly('ws 1');
  assert.equal(calls[0].url, '/api/workspaces/ws%201/coworker/weekly');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token');
  assert.equal(calls[0].init.headers['X-PostRiff-Request'], 'founder-alpha');
  assert.equal(calls[0].init.cache, 'no-store');
});

test('every route used by the UI matches API.md', async () => {
  const { calls, api } = harness();
  const w = 'w1';
  await api.status(w);
  await api.attention(w);
  await api.notifications(w, { unread: true, before: 1700000000 });
  await api.markNotification(w, 'd1', 'read');
  await api.preferences(w);
  await api.setPreference(w, { scope: 'workspace', category: 'weekly', push_mode: 'off' });
  await api.pushDevices(w);
  await api.subscribePush(w, { endpoint: 'https://fcm.googleapis.com/x', expirationTime: null, keys: { p256dh: 'p', auth: 'a' } });
  await api.unsubscribePushEndpoint(w, 'https://fcm.googleapis.com/x');
  await api.revokePushDevice(w, 's1');
  await api.createRecipe(w, { name: 'n' });
  await api.updateRecipe(w, 'r1', { name: 'n' });
  await api.recipeStatus(w, 'r1', 'paused');
  await api.prepareWeek(w, 'r1');
  await api.week(w, 'wk1');
  await api.slotAction(w, 'wk1', 's1', 'accept');
  await api.overlays(w);
  await api.exportOverlays(w);
  await api.addNote(w, { memoryType: 'voice', statement: 's', scope: {} });
  await api.editNote(w, 'ov1', { memoryType: 'voice', statement: 's', scope: {} });
  await api.overlayStatus(w, 'ov1', 'disabled');
  await api.resetOverlays(w, 'notes');
  await api.performance(w);
  await api.decideHypothesis(w, 'h1', 'experiment');
  await api.listening(w);
  await api.saveWatchlist(w, { query: 'q', goal: '' });
  await api.decideOpportunity(w, 'o1', 'act');
  await api.engagement(w);
  const got = calls.map((c) => `${c.init.method ?? 'GET'} ${c.url}`);
  const base = '/api/workspaces/w1';
  assert.deepEqual(got, [
    `GET ${base}/coworker/status`,
    `GET ${base}/coworker/attention`,
    `GET ${base}/notifications?unread=1&before=1700000000`,
    `POST ${base}/notifications/d1/read`,
    `GET ${base}/notification-preferences`,
    `PATCH ${base}/notification-preferences`,
    `GET ${base}/push-subscriptions`,
    `POST ${base}/push-subscriptions`,
    `POST ${base}/push-subscriptions/unsubscribe`,
    `DELETE ${base}/push-subscriptions/s1`,
    `POST ${base}/coworker/weekly/recipes`,
    `PATCH ${base}/coworker/weekly/recipes/r1`,
    `POST ${base}/coworker/weekly/recipes/r1/status`,
    `POST ${base}/coworker/weekly/recipes/r1/prepare`,
    `GET ${base}/coworker/weekly/weeks/wk1`,
    `POST ${base}/coworker/weekly/weeks/wk1/slots/s1/accept`,
    `GET ${base}/coworker/overlays`,
    `GET ${base}/coworker/overlays/export`,
    `POST ${base}/coworker/overlays/notes`,
    `PATCH ${base}/coworker/overlays/notes/ov1`,
    `POST ${base}/coworker/overlays/ov1/status`,
    `POST ${base}/coworker/overlays/reset`,
    `GET ${base}/coworker/performance`,
    `POST ${base}/coworker/performance/hypotheses/h1/decide`,
    `GET ${base}/coworker/listening`,
    `POST ${base}/coworker/listening/watchlists`,
    `POST ${base}/coworker/listening/opportunities/o1/decide`,
    `GET ${base}/coworker/engagement`
  ]);
  const byUrl = (suffix, method) => calls.find((c) => c.url.endsWith(suffix) && (c.init.method ?? 'GET') === method);
  assert.deepEqual(JSON.parse(byUrl('/overlays/reset', 'POST').init.body), { scope: 'notes', confirmed: true });
  assert.deepEqual(JSON.parse(byUrl('/recipes/r1/status', 'POST').init.body), { status: 'paused' });
  assert.deepEqual(JSON.parse(byUrl('/opportunities/o1/decide', 'POST').init.body), { decision: 'act' });
  assert.equal(byUrl('/push-subscriptions/s1', 'DELETE').init.body, undefined);
});

test('ids from the server cannot leave their path segment', async () => {
  const { calls, api } = harness();
  await api.slotAction('w1', '../../members', '../x?y#z', 'answer', { answer: 'hi' });
  await api.markNotification('w1', '../../../admin', 'read');
  await api.overlayStatus('w1', 'a/b', 'retired');
  assert.equal(calls[0].url, '/api/workspaces/w1/coworker/weekly/weeks/..%2F..%2Fmembers/slots/..%2Fx%3Fy%23z/answer');
  assert.equal(calls[1].url, '/api/workspaces/w1/notifications/..%2F..%2F..%2Fadmin/read');
  assert.equal(calls[2].url, '/api/workspaces/w1/coworker/overlays/a%2Fb/status');
  assert.deepEqual(JSON.parse(calls[0].init.body), { answer: 'hi' });
});

test('404 feature_disabled is recognised as "feature off", not an error to show', async () => {
  const { api } = harness([{ status: 404, body: { error: 'This Rafii feature isn’t turned on yet.', code: 'feature_disabled' } }]);
  const error = await api.weekly('w1').catch((e) => e);
  assert.ok(error instanceof client.ApiError);
  assert.equal(error.status, 404);
  assert.equal(coworker.isFeatureDisabled(error), true);
  assert.equal(coworker.shouldRetry(0, error), false);
});

test('other refusals keep the server message and are not retried; outages are retried twice', async () => {
  const { api } = harness([{ status: 403, body: { error: 'Workspace unavailable.' } }]);
  const error = await api.attention('w1').catch((e) => e);
  assert.equal(error.message, 'Workspace unavailable.');
  assert.equal(coworker.isFeatureDisabled(error), false);
  assert.equal(coworker.isFeatureDisabled(new client.ApiError('Not found', 404)), false);
  assert.equal(coworker.shouldRetry(0, error), false);
  const outage = new client.ApiError('down', 503);
  assert.equal(coworker.shouldRetry(0, outage), true);
  assert.equal(coworker.shouldRetry(2, outage), false);
});

test('without a session nothing is sent', async () => {
  const calls = [];
  global.fetch = async (...args) => {
    calls.push(args);
    return new Response('{}');
  };
  const api = coworker.createCoworkerApi(async () => null);
  const error = await api.status('w1').catch((e) => e);
  assert.equal(error.status, 401);
  assert.equal(calls.length, 0);
});

test('Scout creation and follow-up keep plan and observed job ids; watch is explicit', async () => {
  const { calls, api } = harness();
  await api.createOpportunity('w', 'op/a', 'plan-a', 'job-a');
  assert.equal(calls[0].url, '/api/workspaces/w/coworker/listening/opportunities/op%2Fa/create');
  assert.deepEqual(JSON.parse(calls[0].init.body), { planId: 'plan-a', outcomeJobId: 'job-a' });
  await api.decideOpportunity('w', 'op', 'watch');
  assert.deepEqual(JSON.parse(calls[1].init.body), { decision: 'watch' });
  await api.saveWatchlist('w', { query: 'topic', goal: 'help', primaryObjective: 'shareability' });
  assert.equal(JSON.parse(calls[2].init.body).primaryObjective, 'shareability');
});
