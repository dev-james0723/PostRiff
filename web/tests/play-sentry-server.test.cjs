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

test('server: a /play request sends no event, no tally of its drop and no request session; /pricing reports as usual', async () => {
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
  if (fs.existsSync(path.join(__dirname, '..', 'src', 'lib', 'sentry-play-filter.ts'))) stubs['@/lib/sentry-play-filter'] = transpile('lib/sentry-play-filter.ts', {});
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
  for (const url of ['/play/note-garden', '/pricing']) {
    const req = new http.IncomingMessage(new net.Socket());
    Object.assign(req, { url, method: 'GET', headers: { host: '127.0.0.1:3117' } });
    const res = new http.ServerResponse(req);
    server.emit('request', req, res);
    res.emit('close');
  }
  await Sentry.flush(2000);
  // Outcomes recorded after the first flush go out with the next one; close() flushes them too.
  await Sentry.close(2000);

  const all = sent.flatMap(items);
  const events = all.filter((i) => i.type === 'event');
  assert.equal(events.length, 1, `exactly one error sent (the /pricing one), got ${events.length}`);
  assert.match(String(events[0].payload.exception?.values?.[0]?.type ?? ''), /Error/, 'positive control: the /pricing error reports');
  const tallies = all.filter((i) => i.type === 'client_report').flatMap((i) => i.payload.discarded_events ?? []);
  assert.deepEqual(tallies.filter((d) => d.reason === 'before_send'), [], `no tally of the /play drop: ${JSON.stringify(tallies)}`);
  const sampledOut = tallies.filter((d) => d.reason === 'sample_rate' && d.category === 'transaction').reduce((n, d) => n + d.quantity, 0);
  assert.equal(sampledOut, 1, `only the /pricing request's sampled-out transaction is tallied: ${JSON.stringify(tallies)}`);
  const aggregates = all.filter((i) => i.type === 'sessions').flatMap((i) => i.payload.aggregates ?? []);
  const counted = aggregates.reduce((sum, a) => sum + (a.exited ?? 0) + (a.errored ?? 0) + (a.crashed ?? 0), 0);
  assert.equal(counted, 1, `only the /pricing request is a request session: ${JSON.stringify(aggregates)}`);
});
