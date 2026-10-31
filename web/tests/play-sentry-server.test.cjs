/**
 * Privacy N3 (D1 = exclude) on the server: with the installed Sentry Node SDK and an in-memory transport, a request to
 * /play sends nothing, not even indirectly. Its error is dropped, that drop is not tallied in a client_report, and the
 * request is not counted in the request-session aggregates. A /pricing request is the positive control and reports as
 * usual. instrumentation.ts is transpiled with its project imports resolved to the real modules (no network, no port:
 * requests are driven through an http.Server that Sentry instruments via the diagnostics channel).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const diagnostics = require('node:diagnostics_channel');
const path = require('node:path');
const ts = require('typescript');

function transpile(relative, stubs) {
  const file = path.join(__dirname, '..', 'src', relative);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  const fakeRequire = (id) => {
    if (id in stubs) return stubs[id];
    throw new Error(`unexpected import ${id}`);
  };
  new Function('require', 'module', 'exports', outputText)(fakeRequire, mod, mod.exports);
  return mod.exports;
}

const items = (envelope) => envelope[1].map(([header, payload]) => ({ type: header.type, payload }));

test('server: a /play request and the assets it loads send nothing; other pages (incl. leaving /play) report as usual', async () => {
  // instrumentation.ts reads these when it is evaluated, so set them first (dummy local DSN; nothing leaves the process).
  process.env.NEXT_PUBLIC_SENTRY_DSN = 'https://public@127.0.0.1/1';
  process.env.NEXT_RUNTIME = 'nodejs';
  process.env.SENTRY_RELEASE = 'note-garden-test'; // sessions are only sent with a release, as in production
  delete process.env.NEXT_PUBLIC_SENTRY_DISABLED;
  const Sentry = require('@sentry/node');
  const sent = [];
  const memoryTransport = { send: (envelope) => { sent.push(envelope); return Promise.resolve({}); }, flush: () => Promise.resolve(true) };
  const sentryStub = new Proxy(Sentry, { get: (target, key) => (key === 'makeNodeTransport' ? () => memoryTransport : target[key]) });
  const playPath = transpile('lib/play-path.ts', {});
  const stubs = { '@sentry/nextjs': sentryStub, '@/lib/play-path': playPath, '@/lib/telemetry': transpile('lib/telemetry.ts', {}) };
  const instrumentation = transpile('instrumentation.ts', stubs);

  await instrumentation.register();
  const client = Sentry.getClient();
  assert.ok(client, 'Sentry initialised by register()');
  // Route whatever transport the SDK built to memory, so nothing can leave the process (dummy DSN anyway).
  if (client.getTransport() !== memoryTransport) Object.assign(client, { _transport: memoryTransport });

  const server = http.createServer((req) => {
    Sentry.captureException(new Error(`boom on ${req.url}`));
  });
  diagnostics.channel(Sentry.HTTP_ON_SERVER_REQUEST ?? 'http.server.request.start').publish({ server });
  const play = 'http://127.0.0.1:3117/play/note-garden';
  const requests = [
    { url: '/play/note-garden' }, // the game page: excluded
    { url: '/_next/static/chunks/app.js', referer: play }, // an asset the game page loads: excluded (D12)
    { url: '/pricing' }, // counted
    { url: '/_next/static/chunks/app.js', referer: 'http://127.0.0.1:3117/' }, // the same asset for another page: counted
    { url: '/', referer: play } // leaving the game for the home page: counted
  ];
  for (const { url, referer } of requests) {
    const req = new http.IncomingMessage(new net.Socket());
    Object.assign(req, { url, method: 'GET', headers: { host: '127.0.0.1:3117', ...(referer ? { referer } : {}) } });
    const res = new http.ServerResponse(req);
    server.emit('request', req, res);
    res.emit('close');
  }
  // A cold start's first request runs before Sentry has a request scope for it; its spans still carry the path.
  Sentry.startInactiveSpan({ name: 'GET', attributes: { 'http.target': '/play/note-garden', 'http.method': 'GET' } }).end();
  Sentry.startInactiveSpan({ name: 'GET', attributes: { 'http.target': '/pricing', 'http.method': 'GET' } }).end();

  // Interleaving (rafii-6 D12-3): a /play decision that inherits "sampled" records no drop; the next non-play root's
  // drop must still be tallied (a leftover /play flag must never suppress it).
  const traceId = 'abababababababababababababababab';
  const withParent = (parent, sampleRate, rand, fn) => {
    if (parent === undefined) return fn();
    const baggage = [`sentry-trace_id=${traceId}`, `sentry-sample_rand=${rand}`, ...(sampleRate ? [`sentry-sample_rate=${sampleRate}`] : [])].join(',');
    return Sentry.continueTrace({ sentryTrace: `${traceId}-1234567890abcdef-${parent ? 1 : 0}`, baggage }, fn);
  };
  withParent(true, '0.1', '0.9', () => Sentry.startInactiveSpan({ name: 'GET', attributes: { 'http.target': '/play/note-garden' } }).end());
  Sentry.startInactiveSpan({ name: 'GET', attributes: { 'http.target': '/pricing', 'http.method': 'GET' } }).end();

  // Parity (codex D13-1): non-play spans sample exactly as the old { tracesSampleRate: 0 } options, per the installed
  // SDK's own sampleSpan; /play is never sampled, whatever the parent says.
  const core = require('@sentry/core');
  for (const c of [
    { parent: undefined, sampleRate: undefined, rand: '0.9' },
    { parent: true, sampleRate: '0.1', rand: '0.9' },
    { parent: true, sampleRate: undefined, rand: '0.9' },
    { parent: false, sampleRate: '0.5', rand: '0.1' },
    { parent: false, sampleRate: undefined, rand: '0.1' }
  ]) {
    const actual = withParent(c.parent, c.sampleRate, c.rand, () => {
      const span = Sentry.startInactiveSpan({ name: 'GET', attributes: { 'http.target': '/pricing', 'http.method': 'GET' } });
      const sampled = core.spanIsSampled(span);
      span.end();
      return sampled;
    });
    const [expected] = core.sampleSpan({ tracesSampleRate: 0 }, { name: 'GET', attributes: {}, parentSampled: c.parent, parentSampleRate: c.sampleRate ? Number(c.sampleRate) : undefined }, Number(c.rand));
    assert.equal(actual, expected, `non-play ${JSON.stringify(c)}: sampled ${actual}, old options ${expected}`);
    const play = withParent(c.parent, c.sampleRate, c.rand, () => {
      const span = Sentry.startInactiveSpan({ name: 'GET', attributes: { 'http.target': '/play/note-garden', 'http.method': 'GET' } });
      const sampled = core.spanIsSampled(span);
      span.end();
      return sampled;
    });
    // Without a sampled parent a /play span is not sampled at all. Under a sampled parent (only a crafted request could
    // send one: our browser samples nothing) it may be recorded, but its transaction is dropped before sending (below).
    if (c.parent !== true) assert.equal(play, false, `/play ${JSON.stringify(c)} is not sampled`);
  }
  await Sentry.flush(2000);
  // Outcomes recorded after the first flush go out with the next one; close() flushes them too.
  await Sentry.close(2000);

  const all = sent.flatMap(items);
  const events = all.filter((i) => i.type === 'event');
  assert.equal(events.length, 3, `errors sent for the three non-play requests only, got ${events.length}`);
  assert.match(String(events[0].payload.exception?.values?.[0]?.type ?? ''), /Error/, 'positive control: the /pricing error reports');
  const playTransactions = all.filter((i) => i.type === 'transaction' && /^\/play(\/|$)/.test(String(i.payload?.contexts?.trace?.data?.['http.target'] ?? i.payload?.transaction ?? '')));
  assert.deepEqual(playTransactions.map((i) => i.payload?.transaction), [], 'no /play transaction is ever sent');
  const tallies = all.filter((i) => i.type === 'client_report').flatMap((i) => i.payload.discarded_events ?? []);
  assert.deepEqual(tallies.filter((d) => d.reason === 'before_send'), [], `no tally of the /play drop: ${JSON.stringify(tallies)}`);
  const sampledOut = tallies.filter((d) => d.reason === 'sample_rate' && d.category === 'transaction').reduce((n, d) => n + d.quantity, 0);
  // Non-play roots the old options leave unsampled (the SDK-core span path tallies each one): /pricing and / requests,
  // the out-of-scope /pricing, the interleaved /pricing, and the three unsampled non-play parity cases = 7. /play adds 0.
  assert.equal(sampledOut, 7, `only non-play roots are tallied (never /play, never static assets): ${JSON.stringify(tallies)}`);
  const aggregates = all.filter((i) => i.type === 'sessions').flatMap((i) => i.payload.aggregates ?? []);
  const counted = aggregates.reduce((sum, a) => sum + (a.exited ?? 0) + (a.errored ?? 0) + (a.crashed ?? 0), 0);
  assert.equal(counted, 3, `only the three non-play requests are request sessions: ${JSON.stringify(aggregates)}`);
});

