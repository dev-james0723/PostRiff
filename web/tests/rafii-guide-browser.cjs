/**
 * Rafii's guided walkthrough in a real browser against the local dev harness (docs/design/rafii-live-agent/CONTRACTS.md,
 * Contract 5). `/guide connect` in the docked panel opens Channels; the cursor points at Connect account, opens the sheet
 * and picks a platform, then waits at Continue for the person: the guide never presses it, so no sign-in (OAuth) starts.
 * Every element the guide clicks carries `data-guide-safe`. The panel stays usable while the guide runs; Stop and Escape
 * end it; on a phone the Rafii drawer makes way and the same steps run.
 *
 * A CI scene (rafii-browser.yml, after rafii-seed.cjs wrote docs/design/rafii-v9/evidence/seed.json); not run locally:
 *   node web/tests/rafii-guide-browser.cjs [--browser=chromium|webkit] [--out=dir] [--shots=off]
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
const out = path.resolve(typeof args.out === 'string' ? args.out : '.');
fs.mkdirSync(out, { recursive: true });
const seed = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json'), 'utf8'));
const read = (rel) => fs.readFileSync(path.resolve(__dirname, '../src', rel), 'utf8');
const TOUR_IDS = [...read('features/onboarding/tours.ts').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const GUIDE = '/guide connect';
// The walkthrough's length, from its steps (web/src/features/rafii-guide/guides.ts, connect_account).
const CONNECT = read('features/rafii-guide/guides.ts').split("id: 'connect_account'")[1]?.split('done:')[0] ?? '';
const STEPS = (CONNECT.match(/\btarget: \[/g) ?? []).length;
if (STEPS < 5) throw new Error(`Could not read the connect_account steps from guides.ts (found ${STEPS}).`);
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok: Boolean(ok), detail: ok ? undefined : detail });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 500)}` : ''}\n`);
};
async function shot(page, name) {
  if (args.shots === 'off') return;
  try {
    await page.screenshot({ path: path.join(out, name) });
  } catch (error) {
    process.stdout.write(`WARN screenshot ${name}: ${String(error?.message ?? error).slice(0, 200)}\n`);
  }
}

async function context(browser, viewport) {
  const phone = viewport.width < 768;
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark', hasTouch: phone, isMobile: phone });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base },
    { name: 'sidebar_state', value: 'true', url: base }
  ]);
  await ctx.addInitScript(({ id, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
    // Every click a script makes (the guide's own clicks: runner.ts calls `el.click()`), with whether the element may be
    // clicked for the person (guides.ts isGuideSafe: its own `data-guide-safe`, or a tab inside a `data-guide-safe="tabs"`
    // list). The person's clicks (Playwright's) are trusted and not listed.
    window.rafiiGuideClicks = [];
    document.addEventListener('click', (event) => {
      if (event.isTrusted) return;
      const el = event.target instanceof Element ? event.target : null;
      const own = el?.getAttribute('data-guide-safe') ?? null;
      const safe = Boolean(el) && ((own !== null && own !== 'tabs') || (el.getAttribute('role') === 'tab' && el.closest('[data-guide-safe]')?.getAttribute('data-guide-safe') === 'tabs'));
      window.rafiiGuideClicks.push({ tour: el?.closest('[data-tour]')?.getAttribute('data-tour') ?? null, tag: el?.tagName ?? null, safe, text: (el?.textContent ?? '').trim().slice(0, 40) });
    }, true);
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '.tsqd-parent-container,nextjs-portal{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: seed.principal, tours: TOURS });
  return ctx;
}

const launcher = (page) => page.locator('#rafii-launcher');
const panel = (page) => page.locator('#rafii-panel');
const composer = (page) => panel(page).getByLabel('Ask Rafii', { exact: true });
// The caption card (guide-overlay.tsx): a section named "Rafii is showing you how".
const card = (page) => page.getByRole('region', { name: 'Rafii is showing you how' });
const stepText = (page, n) => card(page).getByText(`Step ${n} of ${STEPS}`, { exact: true });
// The cursor's wrapper is an empty positioned box (0×0, so never "visible" to Playwright); its arrow is what is drawn.
const cursor = (page) => page.locator('[data-guide-cursor] svg').first();
const ring = (page) => page.locator('[data-guide-ring]');
const ready = (page) => page.waitForFunction(() => document.querySelector('#rafii-launcher') && !document.querySelector('#rafii-launcher').disabled, null, { timeout: 400000 });

/** Opens Rafii from the header; a click that lands before the page has hydrated is simply repeated. */
async function openPanel(page) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (await panel(page).isVisible().catch(() => false)) return true;
    if ((await launcher(page).getAttribute('aria-expanded').catch(() => null)) !== 'true') await launcher(page).click().catch(() => undefined);
    if (await panel(page).waitFor({ state: 'visible', timeout: 8000 }).then(() => true, () => false)) return true;
  }
  return false;
}

async function startGuide(page) {
  await page.evaluate(() => {
    window.rafiiGuideClicks = [];
  });
  await composer(page).fill(GUIDE);
  await composer(page).press('Enter');
  await card(page).waitFor({ state: 'visible', timeout: 60000 });
}

/** Sign-in starts with POST …/channels/<provider>/oauth/start (connect-sheet.tsx `start`): none may happen here. */
function watchOAuth(page) {
  const starts = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.endsWith('/oauth/start')) starts.push(request.url());
  });
  return starts;
}

const guideClicks = (page) => page.evaluate(() => window.rafiiGuideClicks ?? []);

(async () => {
  const executablePath = (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    // Desktop, docked panel: the guide opens Channels and walks to the platform's own sign-in, which it leaves alone.
    const desk = await context(browser, { width: 1440, height: 900 });
    const page = await desk.newPage();
    const oauth = watchOAuth(page);
    await page.goto(`${base}/app/overview`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('desktop: the Rafii panel opens', await openPanel(page));
    check('desktop: the panel docks beside the page', (await panel(page).evaluate((el) => el.tagName)) === 'ASIDE');

    await startGuide(page);
    await page.waitForURL(/\/app\/channels(\?|$)/, { timeout: 60000 });
    check('desktop: /guide connect opens Channels by itself', /\/app\/channels/.test(page.url()), page.url());
    await stepText(page, 1).waitFor({ timeout: 30000 });
    await card(page).getByRole('button', { name: 'Next', exact: true }).waitFor({ timeout: 30000 });
    check('desktop: step 1 points at Connect account and waits for Next', await card(page).getByText('Connect account').isVisible());
    await ring(page).waitFor({ state: 'visible', timeout: 10000 }).catch(() => undefined);
    const drawn = { cursor: await cursor(page).isVisible(), ring: await ring(page).isVisible() };
    check('desktop: the cursor and the ring around the target are drawn', drawn.cursor && drawn.ring, drawn);
    const ringBox = await ring(page).boundingBox();
    const targetBox = await page.locator('[data-tour="channels-connect"]').first().boundingBox();
    check('desktop: the ring surrounds Connect account', Boolean(ringBox && targetBox) && ringBox.x <= targetBox.x && ringBox.y <= targetBox.y
      && ringBox.x + ringBox.width >= targetBox.x + targetBox.width && ringBox.y + ringBox.height >= targetBox.y + targetBox.height, { ringBox, targetBox });
    await shot(page, 'guide-desktop-step-1-connect-account.png');

    // The overlay lets clicks through: the docked conversation stays usable while the guide waits.
    await composer(page).click();
    await composer(page).pressSequentially('still here');
    check('desktop: the panel stays usable above the guide', (await composer(page).inputValue()) === 'still here');
    await composer(page).fill('');

    await card(page).getByRole('button', { name: 'Next', exact: true }).click();
    // Steps 2 and 3 run by themselves (the guide clicks); their captions show only briefly.
    if (await stepText(page, 2).waitFor({ timeout: 5000 }).then(() => true, () => false)) await shot(page, 'guide-desktop-step-2-opens-the-sheet.png');
    const sheet = page.getByRole('dialog', { name: 'Connect account' });
    await sheet.waitFor({ state: 'visible', timeout: 30000 });
    check('desktop: step 2: the cursor opened the connect sheet', await sheet.isVisible());
    if (await stepText(page, 3).waitFor({ timeout: 5000 }).then(() => true, () => false)) await shot(page, 'guide-desktop-step-3-picks-a-platform.png');
    await page.waitForFunction(() => document.querySelector('[data-tour="connect-platform"][aria-pressed="true"]'), null, { timeout: 30000 });
    await stepText(page, 4).waitFor({ timeout: 30000 });
    check('desktop: step 3: a platform is picked', (await page.locator('[data-tour="connect-platform"][aria-pressed="true"]').count()) === 1);
    check('desktop: the card sits above the sheet and can be pressed', await card(page).getByRole('button', { name: 'Next', exact: true }).isEnabled());
    await shot(page, 'guide-desktop-step-4-what-rafii-may-do.png');

    await card(page).getByRole('button', { name: 'Next', exact: true }).click();
    await stepText(page, 5).waitFor({ timeout: 30000 });
    await card(page).getByText('Your turn', { exact: true }).waitFor({ timeout: 10000 });
    // Timing is what is checked: the guide must leave Continue alone however long it waits.
    await page.waitForTimeout(2000);
    check('desktop: step 5 waits for the person at Continue', await sheet.getByRole('button', { name: 'Continue', exact: true }).isVisible());
    check('desktop: the guide never presses Continue, so no sign-in starts (no oauth/start, no “Continue to …” link, still on Channels)',
      oauth.length === 0 && (await sheet.getByRole('link', { name: /^Continue to/ }).count()) === 0 && /\/app\/channels/.test(page.url()), { oauth, url: page.url() });
    check('desktop: step 5 says the sign-in is theirs', /yourself/.test((await card(page).textContent()) ?? ''));
    const clicks = await guideClicks(page);
    check('desktop: the guide clicked only elements marked data-guide-safe (Connect account, the platform), never Continue',
      clicks.length >= 2 && clicks.every((c) => c.safe) && clicks.some((c) => c.tour === 'channels-connect') && clicks.some((c) => c.tour === 'connect-platform')
        && !clicks.some((c) => c.tour === 'connect-continue' || c.tour === 'connect-authorize'), clicks);
    await shot(page, 'guide-desktop-step-5-your-turn-at-continue.png');

    await card(page).getByRole('button', { name: 'Stop', exact: true }).click();
    await card(page).waitFor({ state: 'hidden', timeout: 10000 });
    check('desktop: Stop ends the guide', (await card(page).count()) === 0 || !(await card(page).isVisible()));
    const cursorGone = await page.locator('[data-guide-cursor]').waitFor({ state: 'detached', timeout: 5000 }).then(() => true, () => false);
    check('desktop: … and the cursor goes with it', cursorGone);
    await shot(page, 'guide-desktop-stopped.png');
    await page.keyboard.press('Escape');
    await sheet.waitFor({ state: 'hidden', timeout: 10000 }).catch(() => undefined);

    // Escape (outside the panel) ends a running guide.
    await startGuide(page);
    await stepText(page, 1).waitFor({ timeout: 30000 }).catch(() => undefined);
    await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));
    await page.keyboard.press('Escape');
    await card(page).waitFor({ state: 'hidden', timeout: 10000 });
    check('desktop: Escape ends the guide', (await card(page).count()) === 0 || !(await card(page).isVisible()));
    check('desktop: … and only the guide: the panel stays open', await panel(page).isVisible());
    check('desktop: no sign-in started at any point', oauth.length === 0, oauth);
    await shot(page, 'guide-desktop-escape-ended.png');
    await desk.close();

    // Phone: the Rafii drawer makes way for the page the guide shows, and the same steps run.
    const phone = await context(browser, { width: 390, height: 844 });
    const small = await phone.newPage();
    const phoneOAuth = watchOAuth(small);
    await small.goto(`${base}/app/overview`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(small);
    check('phone: the Rafii drawer opens', await openPanel(small));
    await startGuide(small);
    await panel(small).waitFor({ state: 'hidden', timeout: 10000 }).catch(() => undefined);
    check('phone: the drawer closes so the page shows', (await panel(small).count()) === 0 || !(await panel(small).isVisible()));
    await small.waitForURL(/\/app\/channels(\?|$)/, { timeout: 60000 }).catch(() => undefined);
    await stepText(small, 1).waitFor({ timeout: 30000 });
    check('phone: the guide card is on screen', await card(small).isVisible());
    const box = await card(small).boundingBox();
    check('phone: the card fits the screen', box !== null && box.x >= 0 && box.x + box.width <= 390, box);
    await shot(small, 'guide-phone-step-1-connect-account.png');
    await card(small).getByRole('button', { name: 'Next', exact: true }).click();
    await stepText(small, 4).waitFor({ timeout: 30000 });
    await shot(small, 'guide-phone-step-4-what-rafii-may-do.png');
    await card(small).getByRole('button', { name: 'Next', exact: true }).click();
    await stepText(small, 5).waitFor({ timeout: 30000 });
    const phoneClicks = await guideClicks(small);
    check('phone: step 5 waits at Continue; every guide click was data-guide-safe; no sign-in started',
      (await small.getByRole('dialog', { name: 'Connect account' }).getByRole('button', { name: 'Continue', exact: true }).isVisible())
        && phoneClicks.length >= 2 && phoneClicks.every((c) => c.safe) && phoneOAuth.length === 0, { phoneClicks, phoneOAuth });
    await shot(small, 'guide-phone-step-5-your-turn-at-continue.png');
    await card(small).getByRole('button', { name: 'Stop', exact: true }).click();
    await card(small).waitFor({ state: 'hidden', timeout: 10000 }).catch(() => undefined);
    check('phone: Stop ends the guide', (await card(small).count()) === 0 || !(await card(small).isVisible()));
    await phone.close();
  } catch (error) {
    check('the guide scene ran to the end', false, String(error?.stack ?? error).slice(0, 800));
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok).length;
  fs.writeFileSync(path.join(out, 'rafii-guide-browser.json'), JSON.stringify({ base, engine: args.browser || 'chromium', guide: GUIDE, steps: STEPS, results }, null, 1));
  process.stdout.write(`\n${results.length} checks, ${failed} failed\n`);
  process.exit(failed ? 1 : 0);
})();
