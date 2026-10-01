/**
 * The founder api wrapper (CONTRACTS §6): same-origin cookie credentials, the CSRF token read once from `GET /session`
 * and sent on every non-GET, an `Idempotency-Key` on agent turns that a retry reuses, a 401 that sends the person to
 * `/founder/sign-in`, and fixed error copy that never repeats a server message.
 *
 *   node --test web/tests/founder-api.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const LIB = path.join(__dirname, '..', 'src', 'lib', 'founder');

function load(file, requires = {}) {
  const { outputText } = ts.transpileModule(fs.readFileSync(path.join(LIB, file), 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((name) => (name in requires ? requires[name] : require(name)), mod, mod.exports);
  return mod.exports;
}

const errors = load('errors.ts');
const api = load('api.ts', { './errors': errors, './types': {} });

/** A fetch double that answers from a script and records every call. */
function fakeFetch(script) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, ...init, body: init && init.body ? JSON.parse(init.body) : undefined });
    const answer = script(url, init, calls.length);
    return new Response(JSON.stringify(answer.body ?? {}), { status: answer.status ?? 200, headers: { 'Content-Type': 'application/json' } });
  };
  return { fetch, calls };
}

const session = { requestId: 'r1', environment: 'staging', asOf: '2026-10-01T00:00:00Z', dataState: 'measured', receiptIds: [], data: { assurance: 'aal2', capabilities: ['control.read'], csrfToken: 'csrf-123' } };
const envelope = (data) => ({ requestId: 'r2', environment: 'staging', asOf: '2026-10-01T00:00:00Z', dataState: 'measured', receiptIds: [], data });

test('GET reads carry the cookie, no CSRF token, and never cache', async () => {
  const { fetch, calls } = fakeFetch(() => ({ body: envelope({ pulse: [] }) }));
  const client = api.createFounderApi({ fetch, onUnauthorized: () => assert.fail('no 401 here') });
  const result = await client.overview('demo', '30d');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/control/v2/overview?mode=demo&period=30d');
  assert.equal(calls[0].method, 'GET');
  assert.equal(calls[0].credentials, 'same-origin');
  assert.equal(calls[0].cache, 'no-store');
  assert.equal(calls[0].headers['X-CSRF-Token'], undefined);
  assert.equal(calls[0].headers.Authorization, undefined);
  assert.deepEqual(result.data, { pulse: [] });
});

test('non-GET reads the CSRF token once from /session and sends it with JSON', async () => {
  const { fetch, calls } = fakeFetch((url) => (url.endsWith('/session') ? { body: session } : { body: envelope({ followUp: { id: 'f1' } }) }));
  const client = api.createFounderApi({ fetch });
  await client.createFollowUp({ title: 'Call back' });
  await client.updateFollowUp('f1', { state: 'completed', revision: 1 });
  assert.deepEqual(calls.map((c) => c.url), ['/api/control/v2/session', '/api/control/v2/follow-ups', '/api/control/v2/follow-ups/f1']);
  for (const call of calls.slice(1)) {
    assert.equal(call.method, 'POST');
    assert.equal(call.headers['X-CSRF-Token'], 'csrf-123');
    assert.equal(call.headers['Content-Type'], 'application/json');
    assert.equal(call.credentials, 'same-origin');
  }
  assert.deepEqual(calls[1].body, { title: 'Call back' });
});

test('an incident ack names the data mode in the query (the only place the server reads it) and sends only the version', async () => {
  const { fetch, calls } = fakeFetch((url) => (url.endsWith('/session') ? { body: session } : { body: envelope({ incident: { id: 'i1', version: 4, state: 'acknowledged' } }) }));
  const client = api.createFounderApi({ fetch, onUnauthorized: () => assert.fail('no 401 here') });
  await client.ackIncident('i1', 3, 'live');
  await client.ackIncident('i1', 3, 'demo');
  assert.deepEqual(calls.slice(1).map((c) => c.url), ['/api/control/v2/incidents/i1/ack?mode=live', '/api/control/v2/incidents/i1/ack?mode=demo']);
  for (const call of calls.slice(1)) {
    assert.equal(call.method, 'POST');
    assert.deepEqual(call.body, { version: 3 }, 'mode never travels in the body, where the server would ignore it');
  }
});

test('agent turns carry an Idempotency-Key equal to the body key, and a resend reuses it', async () => {
  const { fetch, calls } = fakeFetch((url, init, n) => (url.endsWith('/session') ? { body: session } : n === 2 ? { status: 503, body: { code: 'SOURCE_UNAVAILABLE', requestId: 'x' } } : { status: 201, body: envelope({ conversationId: 'c1', runId: 'run1', messageId: null, status: 'running', result: null }) }));
  const client = api.createFounderApi({ fetch, onUnauthorized: () => assert.fail('no 401 here') });
  const body = { message: '今個月 AI 成本為甚麼上升？', idempotencyKey: 'key-abc', conversationId: null, mode: 'live', modality: 'text', pageContext: { route: '/founder/ai-cost', section: 'ai-cost', mode: 'live', environment: 'staging', uiCapabilities: ['navigate'] } };
  await assert.rejects(client.agentTurn(body), (error) => error instanceof errors.FounderApiError && error.status === 503);
  const second = await client.agentTurn(body);
  const turns = calls.filter((c) => c.url.endsWith('/agent/turns'));
  assert.equal(turns.length, 2);
  for (const turn of turns) {
    assert.equal(turn.headers['Idempotency-Key'], 'key-abc');
    assert.equal(turn.body.idempotencyKey, 'key-abc');
    assert.equal(turn.headers['X-CSRF-Token'], 'csrf-123');
  }
  assert.equal(second.data.runId, 'run1');
  assert.equal(calls.filter((c) => c.url.endsWith('/session')).length, 1, 'the CSRF token is read once');
});

test('a 401 sends the person to /founder/sign-in with a founder-only next and throws fixed copy', async () => {
  const { fetch } = fakeFetch(() => ({ status: 401, body: { code: 'AUTH_REQUIRED', message: 'secret provider text' } }));
  const redirects = [];
  const client = api.createFounderApi({ fetch, onUnauthorized: (href) => redirects.push(href), currentPath: () => '/founder/ai-cost?mode=demo' });
  await assert.rejects(client.overview('live'), (error) => {
    assert.ok(error instanceof errors.FounderApiError);
    assert.equal(error.status, 401);
    assert.equal(error.code, 'AUTH_REQUIRED');
    assert.equal(error.message, 'Authentication could not be verified. Sign in again.');
    assert.ok(!error.message.includes('secret'));
    return true;
  });
  assert.deepEqual(redirects, ['/founder/sign-in?next=%2Ffounder%2Fai-cost%3Fmode%3Ddemo']);
});

test('error copy is fixed per code and status; server text and foreign next targets never pass through', () => {
  assert.equal(errors.founderErrorMessage(429, 'RATE_LIMITED'), 'Identity source is rate limited. Wait before retrying.');
  assert.equal(errors.founderErrorMessage(409, 'POLICY_DISABLED'), 'This action is switched off by policy. Nothing was sent or dialled.');
  assert.equal(errors.founderErrorMessage(403), 'This operator does not have permission for this view.');
  assert.equal(errors.founderErrorMessage(503, 'SOURCE_UNAVAILABLE'), 'Control source is unavailable. Retry when it recovers; Live values have not been substituted.');
  assert.equal(errors.founderErrorMessage(418, 'TEAPOT'), errors.FOUNDER_ERROR_FALLBACK);
  for (const bad of ['/app', 'https://evil.example/founder', '//evil.example', '/founderx', '/founder/sign-in', null, '/founder/\n']) assert.equal(api.safeFounderNext(bad), '/founder', String(bad));
  assert.equal(api.safeFounderNext('/founder/customers?mode=demo&record=customer-1'), '/founder/customers?mode=demo&record=customer-1');
  assert.equal(api.signInHref('/founder'), '/founder/sign-in');
});

test('a Demo action carries the revision and keeps one request id while the same payload is retried', async () => {
  let attempt = 0;
  const { fetch, calls } = fakeFetch((url, init) => {
    if (url.endsWith('/session')) return { body: session };
    attempt += 1;
    // The server advances the revision past the one the person saw on every accepted save.
    return attempt === 1 ? { status: 503, body: { code: 'SOURCE_UNAVAILABLE' } } : { body: envelope({ mode: 'demo', revision: JSON.parse(init.body).revision + 1 }) };
  });
  const client = api.createFounderApi({ fetch });
  await assert.rejects(client.demoAction('set_scenario', 'scenario', 'cost_anomaly', 7));
  const saved = await client.demoAction('set_scenario', 'scenario', 'cost_anomaly', 7);
  const actions = calls.filter((c) => c.url.endsWith('/workspace/demo/action'));
  assert.equal(actions.length, 2);
  assert.equal(actions[0].body.requestId, actions[1].body.requestId, 'a retry of the same payload reuses its request id');
  assert.deepEqual({ ...actions[1].body, requestId: undefined }, { action: 'set_scenario', targetId: 'scenario', value: 'cost_anomaly', revision: 7, requestId: undefined });
  assert.equal(saved.data.revision, 8);
  await client.demoAction('set_scenario', 'scenario', 'normal', 8);
  const third = calls.filter((c) => c.url.endsWith('/workspace/demo/action'))[2];
  assert.notEqual(third.body.requestId, actions[0].body.requestId, 'a different payload gets a new request id');
});

test('a Demo save whose revision did not advance is refused rather than trusted', async () => {
  const { fetch } = fakeFetch((url) => (url.endsWith('/session') ? { body: session } : { body: envelope({ mode: 'demo', revision: 7 }) }));
  const client = api.createFounderApi({ fetch });
  await assert.rejects(client.demoAction('reset', 'all', '', 7), (error) => error instanceof errors.FounderApiError && error.code === 'UNVERIFIED_RESPONSE');
});

test('founderFetch returns the body as sent (metrics answer with the receipt body, not an envelope)', async () => {
  const receipt = { requestId: 'q1', queryReceiptId: 'rcpt-1', asOf: '2026-10-01T00:00:00Z', dataState: 'measured', rows: [] };
  const { fetch, calls } = fakeFetch((url) => (url.endsWith('/session') ? { body: session } : { body: receipt }));
  const client = api.createFounderApi({ fetch });
  const result = await client.fetch('/metrics/query?mode=live', { method: 'POST', body: { metricIds: ['paid_customers'] } });
  assert.deepEqual(result, receipt);
  const post = calls.find((c) => c.url.endsWith('/metrics/query?mode=live'));
  assert.equal(post.headers['X-CSRF-Token'], 'csrf-123');
  assert.deepEqual(post.body, { metricIds: ['paid_customers'] });
  const direct = await client.metricsQuery({ metricIds: ['paid_customers'], interval: { start: 'a', end: 'b', timeZone: 'UTC' }, groupBy: [], filters: [], comparison: 'none', limit: 10 }, 'demo');
  assert.equal(direct.queryReceiptId, 'rcpt-1');
  assert.ok(calls.at(-1).url.endsWith('/metrics/query?mode=demo'));
});

test('query keys are namespaced by founder, mode and environment', () => {
  assert.deepEqual(api.founderKeys.overview('demo', 'staging', '30d'), ['founder', 'demo', 'staging', 'overview', '30d']);
  assert.deepEqual(api.founderKeys.incidents('live', 'production'), ['founder', 'live', 'production', 'incidents']);
  assert.deepEqual(api.founderKeys.session, ['founder', 'session']);
  assert.equal(api.CONTROL_COOKIE, '__Host-rafii-control');
  assert.deepEqual(api.CONTROL_EXCHANGE_HEADER, { 'X-Control-Exchange': '1' });
});
