/**
 * Theme bars check (local harness only): the app header and the phone tab bar must match the page in
 * both appearances, whatever theme is stored. A returning visitor may still carry the retired
 * `active_theme` cookie that older versions wrote on every visit (the starter's Vercel theme); that value
 * is ignored and cleared, and a theme the person picked (`postriff_theme`) still gets bars in its own colours.
 *   node web/tests/rafii-theme-bars.cjs            (RAFII_WEB_URL defaults to http://localhost:3100)
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
const evidence = path.resolve(__dirname, '../../docs/design/rafii-v9/evidence');
const seed = JSON.parse(fs.readFileSync(path.join(evidence, 'seed.json'), 'utf8'));
const out = path.join(evidence, 'theme-bars', args.browser === 'webkit' ? 'webkit' : 'chromium');
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS_SEEN = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });

const CASES = [
  { name: 'legacy-cookie-dark', appearance: 'dark', cookies: { active_theme: 'vercel' }, theme: 'rafii', dark: true },
  { name: 'legacy-cookie-light', appearance: 'light', cookies: { active_theme: 'vercel' }, theme: 'rafii', dark: false },
  { name: 'picked-vercel-dark', appearance: 'dark', cookies: { postriff_theme: 'vercel' }, theme: 'vercel', dark: true },
  { name: 'picked-vercel-light', appearance: 'light', cookies: { postriff_theme: 'vercel' }, theme: 'vercel', dark: false },
  { name: 'default-dark', appearance: 'dark', cookies: {}, theme: 'rafii', dark: true }
];

let failures = 0;
function check(scene, name, ok, detail) {
  if (!ok) failures += 1;
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} [${scene}] ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 400)}` : ''}\n`);
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await engine.launch({ headless: true, executablePath: (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined });
  const results = [];
  for (const c of CASES) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, colorScheme: c.appearance });
    await context.addCookies([
      { name: 'postriff_dev', value: '1', url: base },
      { name: 'postriff_dev_principal', value: seed.principal, url: base },
      ...Object.entries(c.cookies).map(([name, value]) => ({ name, value, url: base }))
    ]);
    await context.addInitScript(({ id, appearance, tours }) => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('theme', appearance);
      localStorage.setItem('postriff-onboarding', tours);
    }, { id: seed.principal, appearance: c.appearance, tours: TOURS_SEEN });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message.slice(0, 200)));
    await page.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    const enter = page.getByRole('button', { name: 'Enter dev workspace' });
    const tabs = page.getByRole('navigation', { name: 'Mobile navigation' });
    await tabs.or(enter).first().waitFor({ timeout: 400000 });
    if (await enter.isVisible().catch(() => false)) { await enter.click(); await tabs.waitFor({ timeout: 300000 }); }
    await page.waitForTimeout(1200);
    const r = await page.evaluate(() => {
      const probe = document.createElement('canvas').getContext('2d');
      const rgba = (css) => {
        probe.clearRect(0, 0, 1, 1);
        probe.fillStyle = '#000'; probe.fillStyle = css;
        probe.fillRect(0, 0, 1, 1);
        const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data;
        return { r, g, b, a: a / 255 };
      };
      // What the eye sees: the bar's fill laid over the page colour behind it.
      const seen = (el) => {
        const bar = rgba(getComputedStyle(el).backgroundColor);
        const page = rgba(getComputedStyle(document.body).backgroundColor);
        const mix = (k) => bar[k] * bar.a + page[k] * (1 - bar.a);
        return Math.round((0.2126 * mix('r') + 0.7152 * mix('g') + 0.0722 * mix('b')) / 2.55);
      };
      const header = document.querySelector('header.rafii-panel');
      const tabBar = document.querySelector('nav[aria-label="Mobile navigation"]');
      return {
        theme: document.documentElement.getAttribute('data-theme'),
        dark: document.documentElement.classList.contains('dark'),
        header: header && seen(header),
        tabBar: tabBar && seen(tabBar),
        page: seen(document.body),
        legacyCookie: document.cookie.split('; ').some((x) => x.startsWith('active_theme='))
      };
    });
    await page.screenshot({ path: path.join(out, `${c.name}.png`) });
    results.push({ ...c, ...r, errors });
    check(c.name, 'theme', r.theme === c.theme, r.theme);
    check(c.name, 'appearance', r.dark === c.dark, r.dark);
    // Brightness 0–100 of the bar as seen on the page: dark bars stay under 20, light bars over 80.
    for (const bar of ['header', 'tabBar']) check(c.name, `${bar} matches the ${c.appearance} page`, r[bar] !== null && (c.dark ? r[bar] < 20 : r[bar] > 80), { [bar]: r[bar], page: r.page });
    check(c.name, 'retired theme cookie cleared', !r.legacyCookie);
    check(c.name, 'no page errors', errors.length === 0, errors);
    await context.close();
  }
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify({ base, at: new Date().toISOString(), results }, null, 2) + '\n');
  await browser.close();
  process.stdout.write(`${failures ? `${failures} FAILED` : 'all passed'}\n`);
  process.exit(failures ? 1 : 0);
})();
