/**
 * D12: a /play visit causes no SERVER telemetry at all, not even through the assets and metadata files the page
 * fetches, while a home visit still does. Uses a local Sentry sink; nothing leaves the machine.
 *
 *   SINK=http://public@127.0.0.1:3127/1
 *   NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=$SINK SENTRY_RELEASE=local next build
 *   NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=$SINK SENTRY_RELEASE=local next start -p 3117 -H 127.0.0.1
 *   RAFII_TELEMETRY_URL=http://127.0.0.1:3117 SINK_PORT=3127 node tests/play-server-telemetry-sink.cjs
 *
 * Start the server fresh and touch only /play before this runs (the server flushes counts every 60 s).
 * The browser aborts every off-origin request, so only the Next server can reach the sink. The run takes ~2.5 min.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');

const base = process.env.RAFII_TELEMETRY_URL || 'http://127.0.0.1:3117';
const sinkPort = Number(process.env.SINK_PORT || 3127);
const WAIT_MS = Number(process.env.SINK_WAIT_MS || 70_000); // > the server's 60 s session/client-report flush
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local server only');
const origin = new URL(base).origin;
const pass = (name) => console.log(`ok - ${name}`);

/** Envelopes the server sends, split into their item types and payloads. */
const received = [];
function startSink() {
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => (body += chunk));
    req.on('end', () => {
      const lines = body.split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } });
      const items = [];
      for (let i = 1; i < lines.length; i += 2) items.push({ type: lines[i]?.type, payload: lines[i + 1] });
      received.push({ at: Date.now(), items });
      res.writeHead(200, { 'content-type': 'application/json' }).end('{}');
    });
  });
  return new Promise((resolve) => server.listen(sinkPort, '127.0.0.1', () => resolve(server)));
}

const summary = (from) =>
  received.filter((r) => r.at >= from).flatMap((r) => r.items).map((i) => {
    if (i.type === 'sessions') return { type: 'sessions', counted: (i.payload?.aggregates ?? []).reduce((n, a) => n + (a.exited ?? 0) + (a.errored ?? 0) + (a.crashed ?? 0), 0) };
    if (i.type === 'client_report') return { type: 'client_report', discarded: i.payload?.discarded_events ?? [] };
    return { type: i.type };
  });

async function visit(browser, path, play) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const requests = [];
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    requests.push(url.pathname);
    return route.continue();
  });
  const page = await context.newPage();
  await page.goto(`${base}${path}`);
  await page.waitForLoadState('networkidle');
  if (play) {
    await page.getByRole('button', { name: 'Play' }).click();
    await page.getByRole('button', { name: "Let's go" }).click();
    await page.getByRole('button', { name: /High or Low\?/ }).click();
    await page.getByRole('button', { name: "Let's play" }).click();
    await page.getByRole('button', { name: 'Hear it again' }).click();
    await page.waitForTimeout(1500);
  }
  await context.close();
  return requests;
}

(async () => {
  const sink = await startSink();
  const browser = await chromium.launch({ headless: true });
  try {
    // The page itself references only what it needs: no manifest and no server-hosted icons on /play.
    // (Only /play is touched before the /play window; the home page's HTML is checked in the home phase.)
    const playHtml = await (await fetch(`${base}/play/note-garden`)).text();
    for (const ref of ['manifest.webmanifest', '/icon?', '/apple-icon']) assert.equal(playHtml.includes(ref), false, `/play/note-garden HTML references ${ref}`);
    assert.match(playHtml, /rel="icon" href="data:image\/svg\+xml/, '/play offers an inline icon (no request)');
    // Next always adds the root app/favicon.ico link on every page; headless Chromium never fetches favicons, so a real
    // browser's /favicon.ico request from /play is not exercised here (documented in RUNNING.md).
    pass('/play/note-garden references no manifest, /icon or /apple-icon (inline icon instead); / keeps them all');

    const playStart = Date.now();
    const playRequests = await visit(browser, '/play/note-garden', true);
    const nonStatic = [...new Set(playRequests.filter((p) => !p.startsWith('/_next/static/')))];
    console.log(`  /play visit: ${playRequests.length} server requests; outside /_next/static: ${JSON.stringify(nonStatic)}`);
    assert.ok(nonStatic.every((p) => p === '/play' || p.startsWith('/play/')), `a /play visit only requests /play and /_next/static: ${JSON.stringify(nonStatic)}`);
    await new Promise((r) => setTimeout(r, WAIT_MS));
    const afterPlay = summary(playStart);
    assert.deepEqual(afterPlay, [], `server sent nothing after a /play-only visit: ${JSON.stringify(afterPlay)}`);
    pass(`waited ${WAIT_MS / 1000}s after a /play-only visit: the server sent no sessions, client_report or event`);

    // Positive control: a home visit is still counted by the server (sessions aggregate within the flush window).
    const homeStart = Date.now();
    const homeHtml = await (await fetch(`${base}/`)).text();
    for (const ref of ['manifest.webmanifest', '/favicon.ico', '/icon?', '/apple-icon']) assert.equal(homeHtml.includes(ref), true, `/ HTML still references ${ref}`);
    const homeRequests = await visit(browser, '/', false);
    await new Promise((r) => setTimeout(r, WAIT_MS));
    const afterHome = summary(homeStart);
    const sessions = afterHome.filter((i) => i.type === 'sessions').reduce((n, i) => n + i.counted, 0);
    assert.ok(sessions >= 1, `positive control: home visit counted in server sessions: ${JSON.stringify(afterHome)}`);
    pass(`home visit (${homeRequests.length} requests): server sent ${JSON.stringify(afterHome)}`);
  } finally {
    await browser.close();
    sink.close();
  }
})().catch((error) => {
  console.error(error);
  console.error(JSON.stringify(received.map((r) => r.items), null, 1).slice(0, 2000));
  process.exit(1);
});
