/**
 * Render check for the Rafii notification emails (adaptive coworker spec §17): every preview written by
 * scripts/rafii_email_previews.py is opened in Chromium and WebKit, light and dark, at 600 px and 375 px, and checked:
 * axe-core (WCAG 2 A/AA rules that apply to email HTML), exactly one primary CTA, every link absolute https on the app
 * origin (or the privacy/unsubscribe pages), no horizontal overflow on a phone, a visible headline. Screenshots of the
 * key templates go to evidence/email-shots/. Nothing is sent anywhere.
 *
 *   RAFII_CHROMIUM_PATH=... RAFII_WEBKIT_PATH=... node scripts/rafii_email_render_check.cjs
 */
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const { chromium, webkit } = require(path.join(root, 'web/node_modules/playwright'));
const axeSource = fs.readFileSync(path.join(root, 'web/node_modules/axe-core/axe.min.js'), 'utf8');
const dir = path.join(root, 'docs/design/site-agent/adaptive-social-coworker/evidence/email');
const shots = path.join(root, 'docs/design/site-agent/adaptive-social-coworker/evidence/email-shots');
const index = JSON.parse(fs.readFileSync(path.join(dir, 'index.json'), 'utf8'));
const KEY = new Set(['weekly_ready', 'approval_required', 'publish_failed', 'publish_uncertain', 'channel_reconnect', 'security_alert', 'digest', 'weekly_performance']);
const APP = 'https://app.rafii.example';

async function run(name, launcher, executablePath) {
  const browser = await launcher.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const results = [];
  try {
    for (const scheme of ['light', 'dark']) {
      for (const width of [600, 375]) {
        const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme });
        const page = await context.newPage();
        for (const item of index.previews) {
          await page.goto('file://' + path.join(dir, item.file));
          await page.addScriptTag({ content: axeSource });
          const checks = await page.evaluate(async (app) => {
            const axeResult = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] }, rules: { 'color-contrast': { enabled: true } } });
            const links = [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'));
            const bad = links.filter((h) => !(h.startsWith(app + '/app') || h === app + '/privacy' || h.startsWith(app + '/api/notifications/unsubscribe')));
            const heading = document.querySelector('h1');
            return {
              violations: axeResult.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
              cta: document.querySelectorAll('a.rf-cta-a').length,
              badLinks: bad,
              overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
              headline: heading ? heading.getBoundingClientRect().height > 0 && getComputedStyle(heading).visibility !== 'hidden' : false,
              lang: document.documentElement.lang,
            };
          }, APP);
          const ok = checks.violations.length === 0 && checks.cta === 1 && checks.badLinks.length === 0 && !(width === 375 && checks.overflow) && checks.headline;
          results.push({ browser: name, scheme, width, file: item.file, ok, ...checks });
          if (KEY.has(item.template) && (item.locale === 'en' || item.locale === 'zh-Hant-HK')) {
            fs.mkdirSync(shots, { recursive: true });
            await page.screenshot({ path: path.join(shots, `${name}.${scheme}.${width}.${item.template}.${item.locale}.png`), fullPage: true });
          }
        }
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  return results;
}

(async () => {
  const all = [];
  const targets = [['chromium', chromium, process.env.RAFII_CHROMIUM_PATH], ['webkit', webkit, process.env.RAFII_WEBKIT_PATH]];
  const errors = [];
  for (const [name, launcher, exe] of targets) {
    try {
      all.push(...(await run(name, launcher, exe)));
    } catch (error) {
      errors.push({ browser: name, error: String(error && error.message || error).slice(0, 400) });
    }
  }
  const failed = all.filter((r) => !r.ok);
  const summary = { checked: all.length, passed: all.length - failed.length, failed: failed.length, browsers: [...new Set(all.map((r) => r.browser))], errors };
  fs.writeFileSync(path.join(root, 'docs/design/site-agent/adaptive-social-coworker/evidence/email-render.json'),
    JSON.stringify({ execution: 'local static HTML in headless browsers; nothing sent', summary, failures: failed.slice(0, 50) }, null, 2));
  console.log(JSON.stringify(summary));
  if (failed.length) console.log(JSON.stringify(failed.slice(0, 5), null, 1));
  process.exitCode = failed.length || errors.length ? 1 : 0;
})();
