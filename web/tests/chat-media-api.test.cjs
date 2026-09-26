/**
 * Chat media transport (chat-context SPEC §5.6–5.9, §7.3 step 5): the signed video PUT (progress, one retry on a
 * network error only, no app or session headers, Supabase upload URLs only) and the new API client routes.
 *
 *   node --test web/tests/chat-media-api.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file) {
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const API = path.join(__dirname, '..', 'src', 'lib', 'api');
const U = load(path.join(API, 'upload.ts'));
const C = load(path.join(API, 'client.ts'));
const URL_OK =
  'https://abcd1234.supabase.co/storage/v1/object/upload/sign/postriff-video/ws/video/0f3c.mp4?token=t';

function fakeXhr(script) {
  const made = [];
  const create = () => {
    const outcome = script.shift();
    const on = {};
    const xhr = {
      headers: {},
      upload: { addEventListener: (e, f) => (on['upload:' + e] = f) },
      addEventListener: (e, f) => (on[e] = f),
      status: 0,
      open(method, url) {
        Object.assign(xhr, { method, url });
      },
      setRequestHeader(name, value) {
        xhr.headers[name] = value;
      },
      send(body) {
        xhr.body = body;
        queueMicrotask(() => {
          if (outcome === 'network') return on.error();
          if (outcome === 'abort') return on.abort();
          on['upload:progress']?.({ loaded: 50, total: 100, lengthComputable: true });
          xhr.status = outcome;
          on.load();
        });
      },
      abort() {
        queueMicrotask(() => on.abort());
      }
    };
    made.push(xhr);
    return xhr;
  };
  return { create, made };
}

test('a signed PUT sends only the ticket headers and reports progress', async () => {
  const { create, made } = fakeXhr([200]);
  const progress = [];
  const blob = new Blob(['video']);
  const headers = {
    'Content-Type': 'video/mp4',
    Authorization: 'Bearer secret',
    'X-PostRiff-Request': 'founder-alpha',
    'x-upsert': 'true'
  };
  assert.equal(
    await U.putSignedUpload(URL_OK, blob, headers, (p) => progress.push(p), undefined, create),
    200
  );
  assert.equal(made.length, 1);
  assert.deepEqual([made[0].method, made[0].url, made[0].body], ['PUT', URL_OK, blob]);
  assert.deepEqual(made[0].headers, { 'Content-Type': 'video/mp4' });
  assert.deepEqual(progress, [0.5, 1]);
});

test('one retry on a network error, none on a storage refusal', async () => {
  const retry = fakeXhr(['network', 200]);
  const progress = [];
  assert.equal(
    await U.putSignedUpload(
      URL_OK,
      new Blob(['v']),
      {},
      (p) => progress.push(p),
      undefined,
      retry.create
    ),
    200
  );
  assert.equal(retry.made.length, 2);
  assert.equal(progress[0], 0, 'progress restarts for the retry');
  const twice = fakeXhr(['network', 'network', 200]);
  await assert.rejects(
    U.putSignedUpload(URL_OK, new Blob(['v']), {}, undefined, undefined, twice.create),
    (e) => e.network && e.message === 'Upload failed. Try again.'
  );
  assert.equal(twice.made.length, 2);
  const refused = fakeXhr([400, 200]);
  await assert.rejects(
    U.putSignedUpload(URL_OK, new Blob(['v']), {}, undefined, undefined, refused.create),
    (e) => e.status === 400 && !e.network
  );
  assert.equal(refused.made.length, 1);
});

test('a stop is final and never retried', async () => {
  const controller = new AbortController();
  const { create, made } = fakeXhr(['abort', 200]);
  await assert.rejects(
    U.putSignedUpload(URL_OK, new Blob(['v']), {}, undefined, controller.signal, create),
    (e) => e.message === 'Upload stopped. Try again.'
  );
  assert.equal(made.length, 1);
  controller.abort();
  await assert.rejects(
    U.putSignedUpload(URL_OK, new Blob(['v']), {}, undefined, controller.signal, create)
  );
  assert.equal(made.length, 1, 'an already-stopped upload opens no request');
});

test('only a Supabase signed upload URL is accepted', async () => {
  for (const url of [
    'https://evil.example/storage/v1/object/upload/sign/x',
    'http://abcd.supabase.co/storage/v1/object/upload/sign/x',
    'https://abcd.supabase.co/storage/v1/object/postriff-video/x',
    '/api/workspaces/w/media'
  ]) {
    const { create, made } = fakeXhr([200]);
    await assert.rejects(U.putSignedUpload(url, new Blob(['v']), {}, undefined, undefined, create));
    assert.equal(made.length, 0, url);
  }
});

test('client routes for media notes, videos, playback URLs and picker search', async () => {
  const seen = [];
  global.fetch = async (url, init = {}) => {
    seen.push({ url, method: init.method ?? 'GET', body: init.body, headers: init.headers });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  const api = C.createApi(async () => 'session-token');
  await api.mediaNotes('w 1', { assetId: 'a'.repeat(32), idempotencyKey: 'k' });
  await api.beginVideoUpload('w', {
    mime: 'video/mp4',
    bytes: 10,
    duration: 4,
    width: 1,
    height: 1
  });
  await api.commitVideoUpload('w', 'b'.repeat(32), { frames: [], locationCleared: true });
  await api.abortVideoUpload('w', 'b'.repeat(32));
  await api.mediaUrl('w', 'c'.repeat(32));
  await api.siteAgentSearch('w', '春 季', ['posts', 'library'], 8);
  await api.siteAgentSearch('w', 'x');
  await api.creditEstimate('w', { operation: 'media-notes', request: { assetId: 'a'.repeat(32) } });
  assert.deepEqual(
    seen.map((s) => [s.method, s.url]),
    [
      ['POST', '/api/workspaces/w%201/ideas/media-notes'],
      ['POST', '/api/workspaces/w/media/videos'],
      ['POST', `/api/workspaces/w/media/videos/${'b'.repeat(32)}/commit`],
      ['DELETE', `/api/workspaces/w/media/videos/${'b'.repeat(32)}`],
      ['GET', `/api/workspaces/w/media/${'c'.repeat(32)}/url`],
      [
        'GET',
        '/api/workspaces/w/site-agent/search?q=%E6%98%A5+%E5%AD%A3&categories=posts%2Clibrary&limit=8'
      ],
      ['GET', '/api/workspaces/w/site-agent/search?q=x&limit=8'],
      ['POST', '/api/workspaces/w/ideas/credit-estimates']
    ]
  );
  assert.ok(
    seen.every(
      (s) =>
        s.headers.Authorization === 'Bearer session-token' &&
        s.headers['X-PostRiff-Request'] === 'founder-alpha'
    )
  );
  assert.equal(JSON.parse(seen[7].body).operation, 'media-notes');
});
