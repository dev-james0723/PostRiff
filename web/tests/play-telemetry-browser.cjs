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
  let page = null;
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith('data:') || url.startsWith('blob:')) return route.continue();
    // pageUrl: where the page was when the request left, so "nothing while on /play" can be checked per request.
    log.push({ url, offOrigin: new URL(url).origin !== origin, body: route.request().postData() || '', pageUrl: page?.url() ?? '' });
    return new URL(url).origin === origin ? route.continue() : route.abort();
  });
  page = await context.newPage();
  return { context, page, log };
}

const sentryLoaded = (page) => page.evaluate(() => typeof window.__SENTRY__ === 'object' && window.__SENTRY__ !== null);
const analyticsScript = (page) => page.evaluate(() => [...document.scripts].some((s) => (s.src || '').includes('/_vercel/insights/')));
const telemetryIn = (log, from = 0) => log.slice(from).filter((r) => isTelemetry(r.url)).map((r) => r.url);
/** Page views queued for Vercel Analytics (locally the script 404s, so the queue keeps every call). */
const queuedPageviews = (page) => page.evaluate(() => (window.vaq || []).filter(([kind]) => kind === 'pageview').map(([, p]) => p?.path ?? p?.route ?? '?'));

/** What the browser does when a tab is hidden or closed: Sentry flushes client reports then. */
async function hidePage(page) {
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));
  });
  await page.waitForTimeout(800);
  await page.evaluate(() => {
    delete document.visibilityState;
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

/** Answer `count` questions with the mouse (first open answer until Next). */
async function answerQuestions(page, count) {
  for (let q = 0; q < count; q++) {
    await page.waitForFunction(() => {
      const group = document.querySelector('[aria-label="Answers"]');
      return group?.getAttribute('aria-busy') !== 'true' && [...group.querySelectorAll('button')].some((b) => !b.disabled);
    }, null, { timeout: 15000 });
    while (!(await page.getByRole('button', { name: 'Next', exact: true }).isVisible())) {
      await page.locator('[aria-label="Answers"] button:not([disabled])').first().click();
    }
    await page.getByRole('button', { name: 'Next', exact: true }).click();
  }
}

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
      await answerQuestions(page, 3);
      // Client-side navigation within /play, then the tab is hidden and closed (client_report flush on hide).
      await page.evaluate(() => window.next.router.push('/play/note-garden?again=1'));
      await page.waitForFunction(() => location.search === '?again=1');
      // Same route, new search params: the game keeps the child's place in the level.
      await page.getByText(/^(Question \d+ of \d+|\d+ of \d+)$/).waitFor();
      await hidePage(page);
      await page.waitForTimeout(1000);
      assert.deepEqual(telemetryIn(log, mark), [], 'no /monitoring, /_vercel/* or collector request during the whole /play stay');
      assert.deepEqual(log.slice(mark).filter((r) => r.offOrigin), [], 'no off-origin requests on /play');
      const playViews = (await queuedPageviews(page)).filter((p) => p.startsWith('/play'));
      assert.deepEqual(playViews, [], 'no /play page view is even queued for Vercel Analytics');
      pass(`client-side /pricing -> /play/note-garden, 3+ questions, nav within /play, hide: ${log.length - mark} requests, 0 telemetry, 0 off-origin, 0 /play page views queued`);

      // Leaving /play: the other route's analytics resume. Expected exactly: the Analytics component mounts again and
      // queues a /pricing page view; Sentry sends errors again. The one Sentry session envelope emitted at the moment
      // of leaving (while the address bar still shows /play) is dropped by design.
      const back = log.length;
      await page.evaluate(() => window.next.router.push('/pricing'));
      await page.waitForFunction(() => location.pathname === '/pricing');
      await page.waitForFunction(() => (window.vaq || []).some(([kind, p]) => kind === 'pageview' && (p?.path ?? p?.route) === '/pricing'));
      await page.evaluate(() => setTimeout(() => { throw new Error('telemetry probe back on /pricing'); }, 0));
      await page.waitForTimeout(2000);
      assert.ok(telemetryIn(log, back).length > 0, 'Sentry resumes after leaving /play');
      assert.deepEqual((await queuedPageviews(page)).filter((p) => p.startsWith('/play')), [], 'still no /play page view queued');
      // Hiding the tab on /pricing flushes Sentry's client_report as usual, minus any tally of what was dropped on /play.
      const beforeHide = log.length;
      await hidePage(page);
      await page.waitForTimeout(1000);
      const reports = log.slice(beforeHide).map((r) => r.body).filter((body) => body.includes('"client_report"'));
      assert.ok(reports.length > 0, 'positive control: a client_report is flushed on hide off /play');
      assert.ok(reports.every((body) => !body.includes('"before_send"')), `no count of /play drops in later client reports: ${reports.join(' ').slice(0, 300)}`);
      pass(`client-side /play -> /pricing: /pricing page view queued, Sentry resumes (${telemetryIn(log, back).length} request(s)), client_report on hide carries no /play tally`);
      await context.close();
    }

    // Positive control for a session that starts on /play (privacy N1): leaving /play for a normal page starts that
    // page's analytics and Sentry exactly as a direct visit would, and nothing is sent while the page is on /play.
    for (const target of ['/pricing', '/']) {
      const { context, page, log } = await open(browser);
      await page.goto(`${base}/play/note-garden`);
      await page.waitForLoadState('networkidle');
      await playABit(page);
      assert.equal(await sentryLoaded(page), false);
      assert.deepEqual(telemetryIn(log), [], 'nothing while on /play');
      await page.evaluate((href) => window.next.router.push(href), target);
      await page.waitForFunction((href) => location.pathname === href, target);
      await page.waitForFunction(() => typeof window.__SENTRY__ === 'object', null, { timeout: 15000 });
      await page.waitForFunction(() => [...document.scripts].some((s) => (s.src || '').includes('/_vercel/insights/')));
      const views = await queuedPageviews(page);
      assert.deepEqual(views, [target], `Vercel Analytics: one page view, for ${target} only (got ${JSON.stringify(views)})`);
      const beforeError = log.length;
      await page.evaluate(() => setTimeout(() => { throw new Error('telemetry probe after leaving /play'); }, 0));
      await page.waitForTimeout(2000);
      assert.ok(telemetryIn(log, beforeError).length > 0, `Sentry sends from ${target} after a session that began on /play`);
      const fromPlay = log.filter((r) => isTelemetry(r.url) && new URL(r.pageUrl || base).pathname.startsWith('/play'));
      assert.deepEqual(fromPlay.map((r) => r.url), [], 'no telemetry request left while the page was on /play, including the moment of leaving');
      pass(`direct /play boot -> client-side ${target}: Sentry initialised, analytics script loaded, page views ${JSON.stringify(views)}, error sent, 0 requests while on /play`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
