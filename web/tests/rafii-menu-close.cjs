/**
 * Choosing a page in the menu closes the menu, on a phone (the sheet) and on a desktop (the expanded sidebar back to
 * its icon rail). Runs against the local dev harness:
 *   node web/tests/rafii-menu-close.cjs [--browser=chromium|webkit]
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
const seed = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json'), 'utf8'));
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok: Boolean(ok) });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail)}` : ''}\n`);
};

async function context(browser, viewport, sidebarOpen) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark', hasTouch: viewport.width < 768, isMobile: viewport.width < 768 });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base },
    { name: 'sidebar_state', value: String(sidebarOpen), url: base }
  ]);
  await ctx.addInitScript(({ id, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
    // The dev-only query devtools button floats over the phone tab bar; it does not exist in production.
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '.tsqd-parent-container{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: seed.principal, tours: TOURS });
  return ctx;
}

(async () => {
  const executablePath = (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    // Phone: open "More navigation", tap Automations → the sheet closes and the page opens.
    const phone = await context(browser, { width: 390, height: 844 }, true);
    const page = await phone.newPage();
    await page.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await page.getByRole('button', { name: 'More navigation' }).click({ timeout: 120000 });
    const sheet = page.locator('[data-mobile="true"]');
    await sheet.waitFor({ state: 'visible', timeout: 30000 });
    check('phone: the menu opens', await sheet.isVisible());
    await sheet.getByRole('link', { name: 'Automations', exact: true }).click();
    await page.waitForURL(/\/app\/automations/, { timeout: 120000 });
    await sheet.waitFor({ state: 'detached', timeout: 10000 }).catch(() => {});
    check('phone: choosing a page closes the menu', (await sheet.count()) === 0 || !(await sheet.isVisible()));
    await page.screenshot({ path: path.join(args.out || '.', 'menu-phone-after.png') });
    await phone.close();
    // Desktop: the sidebar is open; choosing a page returns it to the icon rail.
    const desk = await context(browser, { width: 1440, height: 900 }, true);
    const dpage = await desk.newPage();
    await dpage.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    const wrapper = dpage.locator('[data-slot="sidebar"][data-state]').first();
    await wrapper.waitFor({ timeout: 120000 });
    check('desktop: the sidebar starts open', (await wrapper.getAttribute('data-state')) === 'expanded', await wrapper.getAttribute('data-state'));
    await dpage.getByRole('link', { name: 'Calendar', exact: true }).first().click();
    await dpage.waitForURL(/\/app\/calendar/, { timeout: 120000 });
    await dpage.waitForTimeout(400);
    check('desktop: choosing a page collapses the sidebar', (await wrapper.getAttribute('data-state')) === 'collapsed', await wrapper.getAttribute('data-state'));
    await dpage.screenshot({ path: path.join(args.out || '.', 'menu-desktop-after.png') });
    await desk.close();
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok).length;
  process.stdout.write(`\n${results.length} checks, ${failed} failed\n`);
  if (failed) process.exitCode = 1;
})();
