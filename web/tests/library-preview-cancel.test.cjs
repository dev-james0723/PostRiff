// Library document previews retry (409/429) and refresh on timers. WebKit refuses a fetch that a page
// starts after its navigation has begun and reports `Fetch API cannot load … due to access control
// checks.` (web/tests/library-preview-teardown-browser.cjs reproduces it). These tests pin the client
// contract: the preview request is cancellable and never starts while the page is unloading.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.resolve(__dirname, '../src/lib/api/client.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const ASSET = 'a'.repeat(32);
const settle = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

/** A fresh client module (its page-lifecycle state is module scoped) and a fetch that honours `signal` like a browser. */
function load({ window } = {}) {
  const exports_ = {};
  const calls = [];
  const fetch = (url, options = {}) => {
    calls.push({ url, options });
    return new Promise((resolve, reject) => {
      const { signal } = options;
      if (signal?.aborted) return reject(signal.reason);
      signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
      if (calls.respond) resolve(Response.json({ url: 'https://storage.invalid/page.jpg', mime: 'image/jpeg', page: 1 }));
    });
  };
  const previous = { fetch: global.fetch, window: global.window };
  global.fetch = fetch;
  if (window) global.window = window;
  else delete global.window;
  new Function('exports', 'require', compiled)(exports_, require);
  const api = exports_.createApi(async () => 'private-session');
  const restore = () => {
    global.fetch = previous.fetch;
    if (previous.window === undefined) delete global.window;
    else global.window = previous.window;
  };
  return { api, calls, exports: exports_, restore };
}

/** A page-like event target whose timers run only when the test says the delay has elapsed. */
function fakeWindow() {
  const target = new EventTarget();
  const timers = new Map();
  let next = 0;
  target.delays = [];
  target.setTimeout = (callback, delay) => {
    target.delays.push(delay);
    timers.set(++next, callback);
    return next;
  };
  target.clearTimeout = (id) => timers.delete(id);
  target.elapse = () => {
    const due = [...timers.values()];
    timers.clear();
    due.forEach((callback) => callback());
  };
  return target;
}

async function rejectsWithAbort(promise, message) {
  const outcome = await Promise.race([promise.then(() => 'resolved', (error) => error), settle(1000).then(() => 'still pending')]);
  assert.equal(outcome?.name, 'AbortError', `${message} (got ${outcome?.name ?? outcome})`);
}

for (const variant of ['AbortSignal.any', 'fallback without AbortSignal.any']) {
  test(`document preview request is aborted by its query signal and keeps the 90 s timeout (${variant})`, async () => {
    const any = AbortSignal.any;
    if (variant !== 'AbortSignal.any') delete AbortSignal.any;
    const client = load();
    try {
      const query = new AbortController();
      const pending = client.api.libraryPreviewUrl('w/1', ASSET, query.signal);
      await settle();
      assert.equal(client.calls.length, 1);
      assert.equal(client.calls[0].url, `/api/workspaces/w%2F1/library/files/${ASSET}/preview`);
      assert.equal(client.calls[0].options.headers.Authorization, 'Bearer private-session');
      const sent = client.calls[0].options.signal;
      assert.ok(sent instanceof AbortSignal && !sent.aborted, 'the fetch carries a live signal');
      query.abort();
      await rejectsWithAbort(pending, 'cancelling the query must abort the in-flight preview fetch');
      assert.equal(sent.aborted, true);

      const timed = client.api.libraryPreviewUrl('w', ASSET);
      await settle();
      assert.ok(client.calls[1].options.signal instanceof AbortSignal, 'without a query signal the request still has its timeout');
      assert.equal(client.calls[1].options.signal.aborted, false);
      timed.catch(() => {});
    } finally {
      AbortSignal.any = any;
      client.restore();
    }
  });
}

test('no document preview request starts after beforeunload; a back/forward restore resumes it', async () => {
  const window = fakeWindow();
  const client = load({ window });
  client.calls.respond = true;
  try {
    window.dispatchEvent(new Event('beforeunload'));
    const pending = client.api.libraryPreviewUrl('w', ASSET);
    await settle(5);
    assert.equal(client.calls.length, 0, 'a retry or refresh during navigation must not reach fetch()');
    window.dispatchEvent(new Event('pageshow'));
    assert.deepEqual(await pending, { url: 'https://storage.invalid/page.jpg', mime: 'image/jpeg', page: 1 });
    assert.equal(client.calls.length, 1);
  } finally {
    client.restore();
  }
});

test('an abandoned navigation resumes previews after the pause; a query cancelled meanwhile never fetches', async () => {
  const window = fakeWindow();
  const client = load({ window });
  client.calls.respond = true;
  try {
    window.dispatchEvent(new Event('beforeunload'));
    assert.deepEqual(window.delays, [client.exports.UNLOAD_PAUSE_MS]);
    assert.equal(client.exports.UNLOAD_PAUSE_MS, 15_000);
    const removed = new AbortController();
    const cancelled = client.api.libraryPreviewUrl('w', 'b'.repeat(32), removed.signal);
    const kept = client.api.libraryPreviewUrl('w', ASSET);
    removed.abort();
    await rejectsWithAbort(cancelled, 'a query cancelled while the page unloads rejects as aborted');
    await settle(5);
    assert.equal(client.calls.length, 0, 'nothing is fetched while the page unloads');
    window.elapse();
    assert.equal((await kept).page, 1);
    assert.deepEqual(client.calls.map((call) => call.url), [`/api/workspaces/w/library/files/${ASSET}/preview`]);
    // A later navigation pauses again.
    window.dispatchEvent(new Event('beforeunload'));
    const later = client.api.libraryPreviewUrl('w', ASSET);
    await settle(5);
    assert.equal(client.calls.length, 1);
    window.dispatchEvent(new Event('pageshow'));
    await later;
    assert.equal(client.calls.length, 2);
    window.elapse();
    assert.equal(client.calls.length, 2, 'the released pause timer is cleared');
  } finally {
    client.restore();
  }
});

test('the first-page thumbnail hands React Query its abort signal', () => {
  const thumbnail = fs.readFileSync(path.resolve(__dirname, '../src/features/library/asset-thumbnail.tsx'), 'utf8');
  assert.match(thumbnail, /queryFn:\s*async\s*\(\{\s*signal\s*\}\)\s*=>\s*\{\s*const result = await api\.libraryPreviewUrl\(workspaceId,\s*asset\.id,\s*signal\)/);
});
