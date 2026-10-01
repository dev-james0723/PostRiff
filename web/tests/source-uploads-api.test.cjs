/**
 * The source uploads client (src/lib/growth-v2/source-uploads.ts) against a fake fetch and a fake XMLHttpRequest:
 * exact routes, the session guard on every app call, ids that can't leave their path segment, feature_disabled
 * recognised, and the file itself sent only to a signed Supabase Storage URL without the session bearer.
 *
 *   node --test web/tests/source-uploads-api.test.cjs
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
const upload = load('lib/api/upload.ts');
const request = load('lib/growth-v2/request.ts', { '@/lib/api/client': client });
const uploads = load('lib/growth-v2/source-uploads.ts', { '@/lib/api/client': client, '@/lib/api/upload': upload, './request': request });

function harness(responses = []) {
  const calls = [];
  const queue = [...responses];
  global.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    const next = queue.shift() ?? { status: 200, body: {} };
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), { status: next.status, headers: { 'Content-Type': 'application/json' } });
  };
  return { calls, api: uploads.createSourceUploadsApi(async () => 'session-token') };
}

test('every app call goes to its exact route with the session guard', async () => {
  const { calls, api } = harness();
  const id = '0f3c0e3a-9d5b-4c1e-8f7a-6b5c4d3e2f10';
  await api.limits('w1');
  await api.list('w1', 'cur/sor', 10);
  await api.begin('w1', { kind: 'pdf', name: 'a.pdf', mime: 'application/pdf', bytes: 10, idempotencyKey: 'k-12345678' });
  await api.commit('w1', id);
  await api.process('w1', id);
  await api.cancel('w1', id);
  await api.remove('w1', id);
  await api.quote('w1', id);
  await api.transcribe('w1', id, { maxMilliCredits: 1200, idempotencyKey: 'k-12345678' });
  await api.selectPages('w1', id, { from: 1, to: 3, idempotencyKey: 'k-12345678' });
  await api.text('w1', id);
  await api.saveText('w1', id, { expectedRevision: 0, text: 'Corrected.', idempotencyKey: 'k-12345678' });
  await api.review('w1', id, 1);
  await api.createSource('w1', id, { expectedRevision: 1, idempotencyKey: 'k-12345678', confirmReviewed: true });
  await api.addTranscript('w1', { name: 't.srt', format: 'srt', text: '1', idempotencyKey: 'k-12345678' });
  const base = '/api/workspaces/w1/source-uploads';
  assert.deepEqual(calls.map((c) => `${c.init.method ?? 'GET'} ${c.url}`), [
    `GET ${base}/limits`, `GET ${base}?limit=10&cursor=cur%2Fsor`, `POST ${base}`, `POST ${base}/${id}/commit`, `POST ${base}/${id}/process`,
    `POST ${base}/${id}/cancel`, `DELETE ${base}/${id}`, `GET ${base}/${id}/quote`, `POST ${base}/${id}/transcribe`, `POST ${base}/${id}/pages`,
    `GET ${base}/${id}/text`, `POST ${base}/${id}/text`, `POST ${base}/${id}/review`, `POST ${base}/${id}/source`, `POST ${base}/transcripts`
  ]);
  for (const call of calls) {
    assert.equal(call.init.headers.Authorization, 'Bearer session-token');
    assert.equal(call.init.headers['X-PostRiff-Request'], 'founder-alpha');
  }
  assert.deepEqual(JSON.parse(calls[13].init.body), { expectedRevision: 1, idempotencyKey: 'k-12345678', confirmReviewed: true });
});

test('a hostile id cannot leave its path segment', async () => {
  const { calls, api } = harness();
  await api.status('w1', '../../billing/checkout');
  assert.equal(calls[0].url, '/api/workspaces/w1/source-uploads/..%2F..%2Fbilling%2Fcheckout');
});

test('feature_disabled is recognised so the panel hides itself', async () => {
  const { api } = harness([{ status: 404, body: { error: 'off', code: 'feature_disabled' } }]);
  await assert.rejects(api.limits('w1'), (error) => request.isFeatureDisabled(error) && error.code === 'feature_disabled');
});

test('the file goes only to a signed Storage URL, without the session bearer or app headers', async () => {
  const { api } = harness();
  const sent = [];
  class FakeXhr {
    constructor() {
      this.headers = {};
      this.listeners = {};
      this.upload = { addEventListener: (event, fn) => (this.progress = fn) };
      this.status = 200;
    }
    open(method, url) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(name, value) {
      this.headers[name] = value;
    }
    addEventListener(event, fn) {
      this.listeners[event] = fn;
    }
    abort() {}
    send(body) {
      sent.push({ method: this.method, url: this.url, headers: this.headers, size: body.size });
      this.progress({ loaded: body.size, total: body.size, lengthComputable: true });
      this.listeners.load();
    }
  }
  global.XMLHttpRequest = FakeXhr;
  const ticket = { method: 'PUT', url: 'https://abcd1234.supabase.co/storage/v1/object/upload/sign/rafii-source-uploads/w/source/a.pdf?token=t', expiresAt: 0, maxBytes: 10,
    headers: { 'Content-Type': 'application/pdf', Authorization: 'Bearer leaked', 'X-PostRiff-Request': 'founder-alpha' } };
  const fractions = [];
  await api.transfer(ticket, new Blob(['%PDF-1.4']), (f) => fractions.push(f));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].method, 'PUT');
  assert.deepEqual(sent[0].headers, { 'Content-Type': 'application/pdf' });
  assert.deepEqual(fractions.at(-1), 1);
  await assert.rejects(api.transfer({ ...ticket, url: 'https://evil.example.com/upload' }, new Blob(['x'])));
  assert.equal(sent.length, 1);
});
