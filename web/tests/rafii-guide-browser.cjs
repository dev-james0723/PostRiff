/**
 * Rafii's guided walkthrough in a real browser against the local dev harness (docs/design/rafii-live-agent/CONTRACTS.md,
 * Contract 5). `/guide connect a social account` in the docked panel opens Channels; the cursor points at Connect
 * account, opens the sheet and picks a platform, then waits at Continue for the person: the guide never presses it.
 * The panel stays usable while the guide runs; Stop and Escape end it; on a phone the Rafii drawer makes way.
 *
 * A CI scene (rafii-browser.yml); not run locally:
 *   node web/tests/rafii-guide-browser.cjs [--browser=chromium|webkit] [--out=dir]
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
const out = typeof args.out === 'string' ? args.out : '.';
fs.mkdirSync(out, { recursive: true });
const seed = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json'), 'utf8'));
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const GUIDE = '/guide connect a social account';
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok: Boolean(ok) });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail)}` : ''}\n`);
};

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
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '.tsqd-parent-container{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: seed.principal, tours: TOURS });
  return ctx;
}

const launcher = (page) => page.locator('#rafii-launcher');
const panel = (page) => page.locator('#rafii-panel');
const composer = (page) => panel(page).getByLabel('Ask Rafii', { exact: true });
const card = (page) => page.getByRole('region', { name: 'Rafii is showing you how' });
const ready = (page) => page.waitForFunction(() => document.querySelector('#rafii-launcher') && !document.querySelector('#rafii-launcher').disabled, null, { timeout: 400000 });

async function startGuide(page) {
  await composer(page).fill(GUIDE);
  await composer(page).press('Enter');
  await card(page).waitFor({ state: 'visible', timeout: 60000 });
}

(async () => {
  const executablePath = (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    // Desktop, docked panel: the guide opens Channels and walks to the platform's own sign-in, which it leaves alone.
    const desk = await context(browser, { width: 1440, height: 900 });
    const page = await desk.newPage();
    await page.goto(`${base}/app/overview`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+j' : 'Control+j');
    await panel(page).waitFor({ state: 'visible', timeout: 30000 });
    check('desktop: the panel docks beside the page', (await panel(page).evaluate((el) => el.tagName)) === 'ASIDE');

    await startGuide(page);
    await page.waitForURL(/\/app\/channels(\?|$)/, { timeout: 60000 });
    check('the guide opens Channels by itself', /\/app\/channels/.test(page.url()), page.url());
    await card(page).getByText('Step 1 of 6').waitFor({ timeout: 30000 });
    await card(page).getByRole('button', { name: 'Next' }).waitFor({ timeout: 30000 });
    check('step 1 points at Connect account and waits for Next', await card(page).getByText('Connect account').isVisible());
    await page.locator('[data-guide-ring]').waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    check('the cursor and the ring are drawn', (await page.locator('[data-guide-cursor]').isVisible()) && (await page.locator('[data-guide-ring]').isVisible()));
    await page.screenshot({ path: path.join(out, 'guide-step-1.png') });

    // The overlay lets clicks through: the docked conversation stays usable while the guide waits.
    await composer(page).click();
    await composer(page).type('still here');
    check('the panel stays usable above the guide', (await composer(page).inputValue()) === 'still here');
    await composer(page).fill('');

    await card(page).getByRole('button', { name: 'Next' }).click();
    const sheet = page.getByRole('dialog', { name: 'Connect account' });
    await sheet.waitFor({ state: 'visible', timeout: 30000 });
    check('step 2: the cursor opened the connect sheet', await sheet.isVisible());
    await page.waitForFunction(() => document.querySelector('[data-tour="connect-platform"][aria-pressed="true"]'), null, { timeout: 30000 });
    await card(page).getByText('Step 4 of 6').waitFor({ timeout: 30000 });
    check('step 3: a platform is picked', (await page.locator('[data-tour="connect-platform"][aria-pressed="true"]').count()) === 1);
    check('the card sits above the sheet and can be pressed', await card(page).getByRole('button', { name: 'Next' }).isEnabled());
    await page.screenshot({ path: path.join(out, 'guide-step-4.png') });

    await card(page).getByRole('button', { name: 'Next' }).click();
    await card(page).getByText('Step 5 of 6').waitFor({ timeout: 30000 });
    await card(page).getByText('Your turn').waitFor({ timeout: 10000 });
    await page.waitForTimeout(2000);
    check('step 5 waits for the person at Continue', await sheet.getByRole('button', { name: 'Continue', exact: true }).isVisible());
    check('the guide never presses Continue or starts the sign-in', (await sheet.getByRole('link', { name: /^Continue to/ }).count()) === 0);
    check('step 5 says the sign-in is theirs', /yourself/.test((await card(page).textContent()) ?? ''));
    await page.screenshot({ path: path.join(out, 'guide-step-5.png') });

    await card(page).getByRole('button', { name: 'Stop' }).click();
    await card(page).waitFor({ state: 'hidden', timeout: 10000 });
    check('Stop ends the guide', (await card(page).count()) === 0 || !(await card(page).isVisible()));
    await page.keyboard.press('Escape');
    await sheet.waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});

    // Escape (outside the panel) ends a running guide.
    await startGuide(page);
    await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));
    await page.keyboard.press('Escape');
    await card(page).waitFor({ state: 'hidden', timeout: 10000 });
    check('Escape ends the guide', (await card(page).count()) === 0 || !(await card(page).isVisible()));
    await desk.close();

    // Phone: the Rafii drawer makes way for the page the guide shows.
    const phone = await context(browser, { width: 390, height: 844 });
    const small = await phone.newPage();
    await small.goto(`${base}/app/overview`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(small);
    await launcher(small).click();
    await panel(small).waitFor({ state: 'visible', timeout: 30000 });
    await startGuide(small);
    await panel(small).waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});
    check('phone: the drawer closes so the page shows', (await panel(small).count()) === 0 || !(await panel(small).isVisible()));
    check('phone: the guide card is on screen', await card(small).isVisible());
    const box = await card(small).boundingBox();
    check('phone: the card fits the screen', box !== null && box.x >= 0 && box.x + box.width <= 390, box);
    await small.screenshot({ path: path.join(out, 'guide-phone.png') });
    await card(small).getByRole('button', { name: 'Stop' }).click();
    await phone.close();
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok).length;
  process.stdout.write(`\n${results.length} checks, ${failed} failed\n`);
  if (failed) process.exitCode = 1;
})();
