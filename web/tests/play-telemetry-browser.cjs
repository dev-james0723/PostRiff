/**
 * D1 = exclude, checked in a real browser: no analytics or telemetry leaves the /play area, while other routes keep
 * theirs. Run against a production build made WITH telemetry switched on and a dummy local Sentry DSN, e.g.
 *   NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=https://public@127.0.0.1/1 next build && next start -p 3117 -H 127.0.0.1
 *   RAFII_TELEMETRY_URL=http://127.0.0.1:3117 node tests/play-telemetry-browser.cjs
 * Every off-origin request is aborted (recorded, never sent), so nothing can reach a real analytics or Sentry host.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

const base = process.env.RAFII_TELEMETRY_URL || 'http://127.0.0.1:3117';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local server only');
const origin = new URL(base).origin;
const pass = (name) => console.log(`ok - ${name}`);

/** Analytics or telemetry: Vercel insights, the Sentry tunnel, or any known collector host. */
function isTelemetry(url) {
  const u = new URL(url);
  if (u.origin === origin) return u.pathname.startsWith('/_vercel/') || u.pathname.startsWith('/monitoring');
  return true; // anything off-origin counts (the dummy DSN points at 127.0.0.1:443, also off-origin)
}

async function open(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const log = [];
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith('data:') || url.startsWith('blob:')) return route.continue();
    log.push({ url, offOrigin: new URL(url).origin !== origin });
    return new URL(url).origin === origin ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  return { context, page, log };
}

const sentryLoaded = (page) => page.evaluate(() => typeof window.__SENTRY__ === 'object' && window.__SENTRY__ !== null);
const analyticsScript = (page) => page.evaluate(() => [...document.scripts].some((s) => (s.src || '').includes('/_vercel/insights/')));
const telemetryIn = (log, from = 0) => log.slice(from).filter((r) => isTelemetry(r.url)).map((r) => r.url);

async function playABit(page) {
  await page.getByRole('button', { name: 'Play' }).click();
  await page.getByRole('button', { name: "Let's go" }).click();
  await page.getByRole('button', { name: /High or Low\?/ }).click();
  await page.getByRole('button', { name: "Let's play" }).click();
  await page.getByRole('button', { name: 'Hear it again' }).click();
  // A client-side error on /play: Sentry (if it were loaded) must not send it.
  await page.evaluate(() => setTimeout(() => { throw new Error('telemetry probe on /play'); }, 0));
  await page.waitForTimeout(1500);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    // F1 + F2a: direct load of /play/note-garden.
    {
      const { context, page, log } = await open(browser);
      const response = await page.goto(`${base}/play/note-garden`);
      assert.equal(response.status(), 200);
      await page.waitForLoadState('networkidle');
      await playABit(page);
      assert.equal(await analyticsScript(page), false, 'no Vercel Analytics script on /play');
      assert.equal(await sentryLoaded(page), false, 'Sentry SDK never loaded or initialised on /play');
      assert.deepEqual(telemetryIn(log), [], 'no analytics/telemetry requests from /play');
      assert.deepEqual(log.filter((r) => r.offOrigin), [], 'no off-origin requests from /play');
      pass(`direct /play/note-garden: ${log.length} requests, 0 telemetry, 0 off-origin, no analytics script, no Sentry`);
      await context.close();
    }

    // Positive control + F2b: /pricing keeps analytics and Sentry; then a client-side visit to /play sends nothing.
    {
      const { context, page, log } = await open(browser);
      await page.goto(`${base}/pricing`);
      await page.waitForLoadState('networkidle');
      await page.waitForFunction(() => typeof window.__SENTRY__ === 'object', null, { timeout: 15000 });
      assert.equal(await analyticsScript(page), true, 'non-play route still loads Vercel Analytics');
      assert.ok(log.some((r) => new URL(r.url).pathname === '/_vercel/insights/script.js'), 'non-play route requests /_vercel/insights/script.js');
      assert.equal(await sentryLoaded(page), true, 'non-play route still initialises Sentry');
      const beforeError = log.length;
      await page.evaluate(() => setTimeout(() => { throw new Error('telemetry probe on /pricing'); }, 0));
      await page.waitForTimeout(2000);
      const controlSent = telemetryIn(log, beforeError);
      assert.ok(controlSent.length > 0, 'positive control: an error on /pricing is sent to Sentry (so the /play check below is meaningful)');
      pass(`/pricing: analytics script requested, Sentry initialised, error sent (${controlSent.length} telemetry request(s), aborted locally)`);

      const mark = log.length;
      await page.evaluate(() => window.next.router.push('/play/note-garden'));
      await page.getByRole('heading', { name: 'Note Garden' }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/play/note-garden', 'client-side navigation (no reload)');
      assert.equal(await sentryLoaded(page), true, 'same page session: SDK already loaded from /pricing');
      await playABit(page);
      // Try the analytics queue directly too: beforeSend must drop it on /play.
      await page.evaluate(() => window.va?.('event', { name: 'probe' }));
      await page.waitForTimeout(1000);
      assert.deepEqual(telemetryIn(log, mark), [], 'no analytics/telemetry after client-side navigation into /play');
      assert.deepEqual(log.slice(mark).filter((r) => r.offOrigin), [], 'no off-origin requests on /play');
      pass(`client-side /pricing -> /play/note-garden: ${log.length - mark} requests, 0 telemetry, 0 off-origin`);

      // Leaving /play restores the other routes' telemetry exactly as before.
      const back = log.length;
      await page.evaluate(() => window.next.router.push('/pricing'));
      await page.waitForFunction(() => location.pathname === '/pricing');
      await page.evaluate(() => setTimeout(() => { throw new Error('telemetry probe back on /pricing'); }, 0));
      await page.waitForTimeout(2000);
      assert.ok(telemetryIn(log, back).length > 0, 'telemetry resumes after leaving /play');
      pass(`client-side /play -> /pricing: telemetry resumes (${telemetryIn(log, back).length} request(s), aborted locally)`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
