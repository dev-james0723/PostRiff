/**
 * Voice import client (spec 5.1) and the upload plan: paths, bodies, the 200-record and 512 kB limits, real progress,
 * and resuming after a failure. No network: `fetch` is a recorder.
 *   node --test tests/voice-import-client.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './fixtures/voice-import/load-ts.mjs';

const { createVoiceImportApi, voiceImportUnavailable } = await loadTs('lib/api/voice-import.ts');
const { ApiError } = await loadTs('lib/api/client.ts');
const { planBatches, sendBatches, itemBytes, exportAccountKey, MAX_BATCH_ITEMS, MAX_BATCH_BYTES, MAX_POST_CHARS } = await loadTs('lib/voice-import/batches.ts');

const W = 'ws 1/a';
const BASE = '/api/workspaces/ws%201%2Fa/voice-imports';

function recorder(respond = () => ({ status: 200, body: {} })) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const call = { url, method: init.method ?? 'GET', headers: init.headers, body: init.body === undefined ? undefined : JSON.parse(init.body) };
    calls.push(call);
    const { status, body, headers } = respond(call);
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
  };
  return calls;
}

test('every route in the spec table: method, path and body', async () => {
  const calls = recorder();
  const api = createVoiceImportApi(async () => 'dev:token');
  const consent = { ownership: 'mine', voiceScope: 'brand', confirmed: true };
  await api.list(W);
  await api.request(W, { route: 'official_api', provider: 'threads', connectionId: 'c1', consent });
  await api.request(W, { route: 'platform_export', provider: 'x', accountKey: 'studio_example', accountLabel: '@Studio_Example', consent });
  await api.sendItems(W, 'imp/1', { items: [{ externalId: '1', text: 'Synthetic.' }], skipped: { unsupported: 1, empty: 2 }, final: true });
  await api.cancel(W, 'imp1');
  await api.refresh(W, 'imp1');
  await api.remove(W, 'imp1');
  await api.posts(W, { provider: 'threads', accountKey: 'acct 1', status: 'eligible', cursor: 'next+1' });
  await api.posts(W);
  await api.correctPost(W, 'p1', { authorship: 'guest' });
  await api.correctPost(W, 'p1', { label: null, excluded: true });
  await api.analysisQuote(W);
  await api.analysisStart(W, 'q1', 'separate:x:studio_example');

  assert.deepEqual(calls.map((call) => [call.method, call.url, call.body]), [
    ['GET', BASE, undefined],
    ['POST', BASE, { route: 'official_api', provider: 'threads', connectionId: 'c1', consent }],
    ['POST', BASE, { route: 'platform_export', provider: 'x', accountKey: 'studio_example', accountLabel: '@Studio_Example', consent }],
    ['POST', `${BASE}/imp%2F1/items`, { items: [{ externalId: '1', text: 'Synthetic.' }], skipped: { unsupported: 1, empty: 2 }, final: true }],
    ['POST', `${BASE}/imp1/cancel`, {}],
    ['POST', `${BASE}/imp1/refresh`, {}],
    ['DELETE', `${BASE}/imp1`, undefined],
    ['GET', `${BASE}/posts?provider=threads&accountKey=acct+1&status=eligible&cursor=next%2B1`, undefined],
    ['GET', `${BASE}/posts`, undefined],
    ['POST', `${BASE}/posts/p1`, { authorship: 'guest' }],
    ['POST', `${BASE}/posts/p1`, { label: null, excluded: true }],
    ['POST', `${BASE}/analysis`, { quote: true }],
    ['POST', `${BASE}/analysis`, { groupKey: 'separate:x:studio_example', quoteId: 'q1' }]
  ]);
  for (const call of calls) {
    assert.equal(call.headers.Authorization, 'Bearer dev:token');
    assert.equal(call.headers['X-PostRiff-Request'], 'founder-alpha');
  }
});

test('the feature is absent when the list route answers 404; other failures are errors with the server message', async () => {
  recorder(() => ({ status: 404, body: { error: 'Voice import is not enabled.', code: 'feature_disabled' } }));
  const api = createVoiceImportApi(async () => 'dev:token');
  const off = await api.list(W).catch((error) => error);
  assert.ok(off instanceof ApiError);
  assert.equal(off.code, 'feature_disabled');
  assert.equal(voiceImportUnavailable(off), true);

  recorder(() => ({ status: 404, body: { error: 'Not found.' } }));
  assert.equal(voiceImportUnavailable(await api.list(W).catch((error) => error)), true, 'a server without the route is treated the same way');

  recorder(() => ({ status: 409, body: { error: 'An import for this account is already running.', code: 'import_active' }, headers: { 'X-Request-ID': 'a'.repeat(32) } }));
  const conflict = await api.request(W, { route: 'official_api', provider: 'threads', connectionId: 'c1', consent: { ownership: 'mine', voiceScope: 'brand', confirmed: true } }).catch((error) => error);
  assert.equal(conflict.status, 409);
  assert.equal(conflict.message, 'An import for this account is already running.');
  assert.equal(conflict.requestId, 'a'.repeat(32));
  assert.equal(voiceImportUnavailable(conflict), false);
  assert.equal(voiceImportUnavailable(new Error('offline')), false);

  const signedOut = await createVoiceImportApi(async () => null).list(W).catch((error) => error);
  assert.equal(signedOut.status, 401);
});

const post = (index, text = `Synthetic post number ${index} about practice.`) => ({ externalId: String(index), text, publishedAt: '2024-01-01T00:00:00.000Z' });

test('batches hold at most 200 records and stay under the byte budget, which is below 512 kB', () => {
  assert.equal(MAX_BATCH_ITEMS, 200);
  assert.ok(MAX_BATCH_BYTES < 512_000);
  const many = Array.from({ length: 450 }, (_, index) => post(index));
  const plan = planBatches(many);
  assert.deepEqual(plan.batches.map((batch) => batch.length), [200, 200, 50]);
  assert.equal(plan.tooLong, 0);
  assert.deepEqual(plan.batches.flat(), many, 'order kept, nothing dropped');

  // Long Chinese posts: three bytes a character, so the byte budget cuts the batch before 200 records.
  const heavy = Array.from({ length: 30 }, (_, index) => post(index, '琴'.repeat(19_000)));
  const split = planBatches(heavy);
  assert.ok(split.batches.length > 1);
  for (const batch of split.batches) {
    const body = JSON.stringify({ items: batch, skipped: { unsupported: 999_999, empty: 999_999 }, final: true });
    assert.ok(new TextEncoder().encode(body).length < 512_000, 'the whole request body is under 512 kB');
    assert.ok(batch.reduce((total, item) => total + itemBytes(item), 0) <= MAX_BATCH_BYTES);
  }
  assert.equal(split.batches.flat().length, 30);
  assert.deepEqual(planBatches([]), { batches: [], tooLong: 0 });
});

test('a post longer than 20,000 characters is left out and counted, never cut; emoji count as one character each', () => {
  assert.equal(MAX_POST_CHARS, 20_000);
  const plan = planBatches([post(1, 'a'.repeat(20_001)), post(2, 'a'.repeat(20_000)), post(3, '🎹'.repeat(20_000)), post(4, '🎹'.repeat(20_001))]);
  assert.equal(plan.tooLong, 2);
  assert.deepEqual(plan.batches.flat().map((item) => item.externalId), ['2', '3']);
  assert.equal(plan.batches.flat()[0].text.length, 20_000);
});

test('progress is what the workspace acknowledged; the last batch carries the skipped counts and closes the upload', async () => {
  const batches = planBatches(Array.from({ length: 450 }, (_, index) => post(index))).batches;
  const bodies = [];
  const progress = [];
  const result = await sendBatches(batches, {
    send: async (body) => {
      bodies.push(body);
      return { import: { id: 'imp1', status: body.final ? 'done' : 'receiving' } };
    },
    skipped: { unsupported: 2, empty: 5 },
    onProgress: (state) => progress.push([state.sent, state.total, state.batch, state.batches])
  });
  assert.deepEqual(result, { ok: true, last: { import: { id: 'imp1', status: 'done' } } });
  assert.deepEqual(bodies.map((body) => [body.items.length, body.final, body.skipped]), [[200, undefined, undefined], [200, undefined, undefined], [50, true, { unsupported: 2, empty: 5 }]]);
  assert.deepEqual(progress, [[200, 450, 1, 3], [400, 450, 2, 3], [450, 450, 3, 3]]);
  // Each batch names its place: the route counts a re-sent batch once (a lost reply, then a resend, adds nothing twice).
  assert.deepEqual(bodies.map((body) => body.seq), [1, 2, 3]);
});

test('a resumed upload keeps each batch number, so a resend after a lost reply is the same batch', async () => {
  const batches = planBatches(Array.from({ length: 450 }, (_, index) => post(index))).batches;
  const seqs = [];
  const resumed = await sendBatches(batches, { send: async (body) => seqs.push(body.seq), skipped: { unsupported: 0, empty: 0 }, from: 1 });
  assert.equal(resumed.ok, true);
  assert.deepEqual(seqs, [2, 3]);
});

test('a failed batch stops the upload and names where to resume; resuming sends only what is left', async () => {
  const batches = planBatches(Array.from({ length: 450 }, (_, index) => post(index))).batches;
  let calls = 0;
  const failing = await sendBatches(batches, {
    send: async () => {
      calls++;
      if (calls === 2) throw new ApiError('Too many requests.', 429);
      return {};
    },
    skipped: { unsupported: 0, empty: 0 }
  });
  assert.equal(failing.ok, false);
  assert.equal(failing.next, 1);
  assert.equal(failing.cancelled, false);
  assert.equal(failing.error.status, 429);
  assert.equal(calls, 2, 'nothing after the failure was sent');

  const sizes = [];
  const progress = [];
  const resumed = await sendBatches(batches, { send: async (body) => sizes.push(body.items.length), skipped: { unsupported: 0, empty: 0 }, from: failing.next, onProgress: (state) => progress.push(state.sent) });
  assert.equal(resumed.ok, true);
  assert.deepEqual(sizes, [200, 50]);
  assert.deepEqual(progress, [400, 450], 'progress continues from the records already acknowledged');

  let sent = 0;
  const stopped = await sendBatches(batches, { send: async () => sent++, skipped: { unsupported: 0, empty: 0 }, cancelled: () => sent >= 1 });
  assert.deepEqual(stopped, { ok: false, next: 1, cancelled: true });
});

test('an export account key is the typed name, trimmed, without @ and in lower case', () => {
  assert.equal(exportAccountKey('  @Studio_Example '), 'studio_example');
  assert.equal(exportAccountKey('琴房  日記'), '琴房 日記');
  assert.equal(exportAccountKey('@@'), '');
  assert.equal([...exportAccountKey('🎹'.repeat(300))].length, 200);
});
