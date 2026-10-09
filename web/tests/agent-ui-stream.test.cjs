/**
 * rafii-genui/1 lane F: the browser stream client (web/src/lib/agent-runtime/use-ui-artifact-stream.ts) against fake transports.
 * Proves: fragmented UTF-8 and line endings, heartbeat before seq de-duplication, duplicates ignored, gap → one replay, backoff,
 * terminal ends the stream, hidden views stop all network use, dispose aborts, refusals don't retry, the client never POSTs or
 * starts a generation, and both transports add only their own auth (no credentials in URLs, envelope unwrapped for founder).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const cache = new Map();
function resolveFile(request, from) {
  const base = request.startsWith('@/') ? path.join(WEB, 'src', request.slice(2)) : path.resolve(path.dirname(from), request);
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts')]) if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  return null;
}
function load(file, stubs = {}) {
  const filename = path.isAbsolute(file) ? file : path.join(WEB, file);
  if (cache.has(filename)) return cache.get(filename);
  const source = fs.readFileSync(filename, 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename }).outputText;
  const module = { exports: {} };
  cache.set(filename, module.exports);
  const req = (name) => {
    if (stubs[name]) return stubs[name];
    if (name.startsWith('@/') || name.startsWith('.')) {
      const target = resolveFile(name, filename);
      if (!target) throw new Error(`cannot resolve ${name} from ${filename}`);
      return load(target, stubs);
    }
    return require(require.resolve(name, { paths: [WEB] }));
  };
  vm.runInThisContext(`(function(require, exports, module){${code}\n})`, { filename })(req, module.exports, module);
  cache.set(filename, module.exports);
  return module.exports;
}

const stream = load('src/lib/agent-runtime/use-ui-artifact-stream.ts');
const ART = '6c1f2f3e-1111-4222-8333-944455556666';
const ATT = '7d2a3b4c-2222-4333-8444-a55566667777';
const enc = new TextEncoder();

function event(seq, kind, payload = {}, extra = {}) {
  return { contractVersion: 'rafii-genui/1', artifactId: ART, attemptId: ATT, revision: 0, seq, kind, at: '2026-10-08T00:00:00.000Z', payload, ...extra };
}
const frame = (ev) => `id: ${ev.artifactId}:${ev.seq}\nevent: ${ev.kind}\ndata: ${JSON.stringify(ev)}\n\n`;
const flush = async (n = 20) => { for (let i = 0; i < n; i += 1) await new Promise((resolve) => setImmediate(resolve)); };

/** A fake transport: each fetch returns the next scripted response; the body stream errors when its request is aborted. */
function transport(script, scope = 'workspace') {
  const calls = [];
  return {
    calls,
    base: '/api/workspaces/w1/agent/ui',
    scope,
    scopeKey: 'workspace:u1:w1',
    async fetch(p, init) {
      calls.push({ path: p, method: init.method, body: init.body, signal: init.signal });
      const next = script.shift();
      if (!next) return new Response(new ReadableStream({ start(c) { init.signal?.addEventListener('abort', () => c.error(Object.assign(new Error('aborted'), { name: 'AbortError' }))); } }), { headers: { 'content-type': 'text/event-stream' } });
      if (next instanceof Error) throw next;
      if (next.status && next.status !== 200) return new Response(JSON.stringify({ code: next.code ?? null }), { status: next.status, headers: { 'content-type': 'application/json' } });
      const chunks = next.chunks;
      return new Response(new ReadableStream({
        start(c) {
          init.signal?.addEventListener('abort', () => { try { c.error(Object.assign(new Error('aborted'), { name: 'AbortError' })); } catch { /* closed */ } });
          for (const chunk of chunks) c.enqueue(typeof chunk === 'string' ? enc.encode(chunk) : chunk);
          if (!next.open) c.close();
        }
      }), { headers: { 'content-type': 'text/event-stream' } });
    }
  };
}

function fakeTimers() {
  const queue = [];
  return { queue, setTimeout: (fn, ms) => { const t = { fn, ms }; queue.push(t); return t; }, clearTimeout: (t) => { const i = queue.indexOf(t); if (i >= 0) queue.splice(i, 1); },
    run: () => { const t = queue.shift(); if (t) t.fn(); return t; } };
}

test('SSE parser: every byte split of multi-byte UTF-8, CRLF/CR edges, comments, multi-line data, partial frame dropped', () => {
  const ev = event(1, 'ui.delta', { append: '粵語 🎹 Ελληνικά', offset: 0 });
  const raw = enc.encode(`: hello\r\n${frame(ev).replace(/\n/g, '\r\n')}`);
  for (let split = 1; split < raw.length; split += 1) {
    const parser = stream.createSseParser();
    const frames = [...parser.push(raw.subarray(0, split)), ...parser.push(raw.subarray(split)), ...parser.end()];
    assert.equal(frames.length, 1, `split ${split}`);
    assert.equal(stream.parseUiEvent(frames[0]).payload.append, '粵語 🎹 Ελληνικά');
    assert.equal(frames[0].id, `${ART}:1`);
  }
  const parser = stream.createSseParser();
  const out = [...parser.push(enc.encode('event: x\rdata: a\rdata: b\r')), ...parser.push(enc.encode('\r')), ...parser.push(enc.encode('data: never finished')), ...parser.end()];
  assert.deepEqual(out.map((f) => [f.event, f.data]), [['x', 'a\nb']]);
  assert.equal(stream.parseUiEvent({ data: '{"not":"an event"}' }), null);
  assert.equal(stream.parseUiEvent({ data: 'not json' }), null);
});

test('stream: heartbeats are liveness only (before dedupe), duplicates ignored, terminal ends without further requests', async () => {
  const t = transport([{ chunks: [frame(event(1, 'ui.started')), frame(event(2, 'ui.delta', { append: 'root', offset: 0 })), frame(event(2, 'ui.heartbeat', {}, { attemptId: null })),
    frame(event(2, 'ui.delta', { append: 'root', offset: 0 })), frame(event(3, 'ui.ready', { sourceHash: 'a'.repeat(64) }))] }]);
  const seen = [];
  let beats = 0;
  const s = new stream.UiArtifactStream({ transport: t, artifactId: ART, afterSeq: 0, onEvent: (e) => seen.push(e.seq + ':' + e.kind), onHeartbeat: () => { beats += 1; }, timers: fakeTimers() });
  s.connect();
  await flush();
  assert.deepEqual(seen, ['1:ui.started', '2:ui.delta', '3:ui.ready']);
  assert.equal(beats, 1);
  assert.equal(s.status, 'done');
  assert.equal(t.calls.length, 1);
  assert.equal(t.calls[0].method, 'GET');
  assert.equal(t.calls[0].path, `/api/workspaces/w1/agent/ui/presentations/${ART}/events?after=0`);
});

test('stream: a seq gap in a producer stream replays the durable log once from the last applied seq; replays are authoritative', async () => {
  const t = transport([{ chunks: [frame(event(7, 'ui.state_changed', { stateRevision: 2 })), frame(event(9, 'ui.ready'))] }]);
  const seen = [];
  const s = new stream.UiArtifactStream({ transport: t, artifactId: ART, afterSeq: 3, onEvent: (e) => seen.push(e.seq), timers: fakeTimers() });
  s.consume(new Response(new ReadableStream({ start(c) { c.enqueue(enc.encode(frame(event(4, 'ui.started')) + frame(event(6, 'ui.checkpoint', { cursor: 0 })))); } }),
    { headers: { 'content-type': 'text/event-stream' } }));
  await flush();
  assert.equal(t.calls.length, 1);
  assert.equal(t.calls[0].path.endsWith('events?after=4'), true, t.calls.map((c) => c.path).join(' '));
  assert.deepEqual(seen, [4, 7, 9], 'the replay fills the gap; its own gaps (compacted deltas) are accepted');
  assert.equal(s.status, 'done');
});

test('stream: transient failures back off and reconnect from lastSeq; refusals fail without retry; max reconnects fail', async () => {
  const timers = fakeTimers();
  const t = transport([{ chunks: [frame(event(1, 'ui.started'))] }, new TypeError('network'), { status: 503 }, { chunks: [frame(event(2, 'ui.ready'))] }]);
  const seen = [];
  const s = new stream.UiArtifactStream({ transport: t, artifactId: ART, onEvent: (e) => seen.push(e.seq), timers, random: () => 0 });
  s.connect();
  await flush();
  assert.equal(timers.queue.length, 1);
  assert.equal(timers.queue[0].ms, 250, 'a tail that closed after progress reconnects promptly');
  timers.run(); await flush();
  assert.equal(timers.queue[0].ms, 500, 'a network error backs off');
  timers.run(); await flush();
  assert.equal(timers.queue[0].ms, 1000, '503 backs off further');
  timers.run(); await flush();
  assert.deepEqual(seen, [1, 2]);
  assert.ok(t.calls.every((c) => c.method === 'GET' && c.path.includes('/events?after=')), 'only replays, never a POST');
  assert.ok(t.calls.slice(1).every((c) => c.path.endsWith('after=1')));

  const refused = transport([{ status: 403, code: 'ui_artifact' }]);
  const r = new stream.UiArtifactStream({ transport: refused, artifactId: ART, onEvent() {}, timers: fakeTimers() });
  r.connect(); await flush();
  assert.equal(r.status, 'failed');
  assert.equal(refused.calls.length, 1);

  const down = transport([new TypeError('x'), new TypeError('x'), new TypeError('x')]);
  const d = new stream.UiArtifactStream({ transport: down, artifactId: ART, onEvent() {}, timers: fakeTimers(), maxReconnects: 2 });
  d.connect(); await flush();
  for (let i = 0; i < 3; i += 1) { d.opts.timers.run(); await flush(); }
  assert.equal(d.status, 'failed');
});

test('stream: hidden views stop network use; showing again resumes after lastSeq; dispose aborts in flight', async () => {
  const t = transport([{ chunks: [frame(event(1, 'ui.started'))], open: true }, { chunks: [frame(event(2, 'ui.ready'))] }]);
  const s = new stream.UiArtifactStream({ transport: t, artifactId: ART, onEvent() {}, timers: fakeTimers() });
  s.connect(); await flush();
  s.setActive(false); await flush();
  assert.equal(t.calls[0].signal.aborted, true);
  assert.equal(s.status, 'paused');
  const callsWhileHidden = t.calls.length;
  await flush();
  assert.equal(t.calls.length, callsWhileHidden, 'no polling or reconnect while hidden');
  s.setActive(true); await flush();
  assert.equal(t.calls.at(-1).path.endsWith('after=1'), true);
  assert.equal(s.status, 'done');

  const live = transport([{ chunks: [frame(event(1, 'ui.started'))], open: true }]);
  const x = new stream.UiArtifactStream({ transport: live, artifactId: ART, onEvent() {}, timers: fakeTimers() });
  x.connect(); await flush();
  x.dispose(); await flush();
  assert.equal(live.calls[0].signal.aborted, true);
  assert.equal(x.status, 'closed');
});

test('stream: an unpersisted terminal frame reusing the last seq is applied once; a POST stream names its artifact', async () => {
  const t = transport([]);
  const seen = [];
  let named = null;
  const s = new stream.UiArtifactStream({ transport: t, artifactId: '', onEvent: (e) => seen.push(`${e.seq}:${e.kind}`), onArtifact: (id) => { named = id; }, timers: fakeTimers() });
  const body = [frame(event(5, 'ui.started')), frame(event(6, 'ui.delta', { append: 'x', offset: 0 })), frame(event(6, 'ui.interrupted', { reason: 'client_gone', persisted: false })),
    frame(event(6, 'ui.interrupted', { reason: 'client_gone', persisted: false }))].join('');
  s.consume(new Response(body, { headers: { 'content-type': 'text/event-stream' } }));
  await flush();
  assert.equal(named, ART);
  assert.deepEqual(seen, ['5:ui.started', '6:ui.delta', '6:ui.interrupted']);
  assert.equal(s.status, 'done');
  assert.equal(t.calls.length, 0, 'reading a handed-in stream makes no request');
});

test('poller (founder transport): durable replay once a second, older seqs ignored, terminal stops it, hidden pauses', async () => {
  const timers = fakeTimers();
  const replies = [
    { events: [event(1, 'ui.started'), event(2, 'ui.delta', { append: 'a', offset: 0 })], done: false },
    { events: [event(2, 'ui.delta', { append: 'a', offset: 0 }), event(3, 'ui.ready')], done: true }
  ];
  const calls = [];
  const founder = { base: '/api/control/v2/agent/ui', scope: 'founder', scopeKey: 'founder:op:live:production',
    async fetch(p, init) { calls.push({ p, method: init.method }); return new Response(JSON.stringify(replies.shift() ?? { events: [], done: true }), { status: 200 }); } };
  const seen = [];
  const source = stream.createUiEventSource({ transport: founder, artifactId: ART, onEvent: (e) => seen.push(e.seq), timers });
  assert.equal(source instanceof stream.UiArtifactPoller, true);
  source.connect(); await flush();
  assert.equal(timers.queue[0].ms, 1000);
  timers.run(); await flush();
  assert.deepEqual(seen, [1, 2, 3]);
  assert.equal(source.status, 'done');
  assert.deepEqual(calls.map((c) => [c.method, c.p.split('?')[1]]), [['GET', 'after=0'], ['GET', 'after=2']]);
});

test('consumer transport: Bearer + guard header only, JSON body, never a credential in the URL', async () => {
  const sent = [];
  const t = stream.createConsumerUiTransport({ workspaceId: 'w 1', principal: 'u1', getToken: async () => 'token-abc', fetch: async (url, init) => { sent.push({ url, init }); return new Response('{}'); } });
  assert.equal(t.base, '/api/workspaces/w%201/agent/ui');
  assert.equal(t.scopeKey, 'workspace:u1:w 1');
  await t.fetch(`${t.base}/queries`, { method: 'POST', body: { bindingId: 'metrics_summary' } });
  await t.fetch(`${t.base}/presentations/x`, { method: 'GET' });
  assert.equal(sent[0].url, '/api/workspaces/w%201/agent/ui/queries', 'the path is used as given (D-A41), not prefixed again');
  assert.equal(sent[0].init.headers.Authorization, 'Bearer token-abc');
  assert.equal(sent[0].init.headers['X-PostRiff-Request'], 'founder-alpha');
  assert.equal(sent[0].init.body, '{"bindingId":"metrics_summary"}');
  assert.equal(sent[1].init.body, undefined);
  assert.equal(sent[1].init.headers['Content-Type'], undefined);
  assert.ok(!sent.some((s) => s.url.includes('token')));
  const client = fs.readFileSync(path.join(WEB, 'src/lib/api/client.ts'), 'utf8');
  assert.ok(client.includes(`APP_GUARD_HEADER = { 'X-PostRiff-Request': '${stream.UI_GUARD_HEADER['X-PostRiff-Request']}' }`), 'same guard value as the app client');
  const signedOut = stream.createConsumerUiTransport({ workspaceId: 'w1', principal: null, getToken: async () => null, fetch: async () => { throw new Error('must not fetch'); } });
  assert.equal((await signedOut.fetch('/x', { method: 'GET' })).status, 401);
});

test('founder transport: cookie + CSRF on POST only, control envelope unwrapped, CSRF refusals reset the token', async () => {
  const sent = [];
  let resets = 0;
  const responses = [
    { status: 200, body: { requestId: 'r', environment: 'production', asOf: 'x', dataState: 'measured', receiptIds: [], data: { state: 'available', data: { rows: [] } } } },
    { status: 403, body: { requestId: 'r', code: 'CSRF_INVALID', message: 'Csrf invalid' } }
  ];
  const t = stream.createFounderUiTransport({ mode: 'live', environment: 'production', principal: 'op', csrf: async () => 'csrf-1', resetCsrf: () => { resets += 1; },
    fetch: async (url, init) => { sent.push({ url, init }); const r = responses.shift(); return new Response(JSON.stringify(r.body), { status: r.status }); } });
  assert.equal(t.scope, 'founder');
  const ok = await t.fetch(`${t.base}/queries`, { method: 'POST', body: { bindingId: 'mrr' } });
  assert.deepEqual(await ok.json(), { state: 'available', data: { rows: [] } });
  assert.equal(sent[0].init.headers['X-CSRF-Token'], 'csrf-1');
  assert.equal(sent[0].init.credentials, 'same-origin');
  assert.equal(sent[0].init.headers.Authorization, undefined, 'no bearer on founder routes');
  const refused = await t.fetch(`${t.base}/queries`, { method: 'POST', body: {} });
  assert.equal(refused.status, 403);
  assert.equal((await refused.json()).code, 'CSRF_INVALID');
  assert.equal(resets, 1);
});
