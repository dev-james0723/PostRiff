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
const KEY = new Set(['weekly_ready', 'approval_required', 'publish_failed', 'publish_uncertain', 'channel_reconnect', 'security_alert', 'digest', 'weekly_performance', 'phone_call_failed']);
const APP = 'https://app.rafii.example';

async function run(name, launcher, executablePath) {
  const browser = await launcher.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const results = [];
  try {
    for (const scheme of ['light', 'dark']) {
      for (const width of [600, 375]) {
        const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme });
        const page = await context.newPage();
        for (const images of [true, false]) {
        await context.route(APP + '/raffi/**', async (route) => {
          if (!images) return route.abort();
          const name = path.basename(new URL(route.request().url()).pathname);
          const file = path.join(root, 'web/public/raffi', name);
          if (!fs.existsSync(file)) return route.abort();
          return route.fulfill({status:200,contentType:'image/png',body:fs.readFileSync(file)});
        });
        for (const item of index.previews) {
          await page.goto('file://' + path.join(dir, item.file));
          if (!images) await page.evaluate(() => document.querySelectorAll('style').forEach((s) => s.remove()));
          await page.addScriptTag({ content: axeSource });
          const checks = await page.evaluate(async (app) => {
            const axeResult = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] }, rules: { 'color-contrast': { enabled: true } } });
            const links = [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'));
            const bad = links.filter((h) => {try {const u=new URL(h);return u.origin!==app || u.protocol!=='https:';}catch{return true;}});
            const heading = document.querySelector('h1');
            const wordmark = document.querySelector('[data-rafii-wordmark]');
            const character = document.querySelector('img[data-rafii-character]');
            return {
              violations: axeResult.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
              cta: document.querySelectorAll('a.rf-cta-a').length,
              badLinks: bad,
              overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
              headline: heading ? heading.getBoundingClientRect().height > 0 && getComputedStyle(heading).visibility !== 'hidden' : false,
              lang: document.documentElement.lang,
              wordmark: !!wordmark && wordmark.textContent.includes('Rafii') && wordmark.getBoundingClientRect().height > 0,
              character: !!character && character.getAttribute('src') === app + '/raffi/avatar-128.png',
              assetLoaded: !!character && character.complete && character.naturalWidth > 0,
              ctaVisible: !!document.querySelector('a.rf-cta-a') && document.querySelector('a.rf-cta-a').getBoundingClientRect().height >= 44,
            };
          }, APP);
          const ok = checks.violations.length === 0 && checks.cta === 1 && checks.badLinks.length === 0 && !checks.overflow && checks.headline && checks.wordmark && checks.character && (!images || checks.assetLoaded) && checks.ctaVisible && item.htmlBytes < 102000 && fs.readFileSync(path.join(dir,item.file.replace('.html','.txt')),'utf8').includes(item.primaryURL);
          results.push({ browser: name, scheme, width, images, file: item.file, ok, ...checks });
          if ((images || width===375) && KEY.has(item.template) && (item.locale === 'en' || item.locale === 'zh-Hant-HK')) {
            fs.mkdirSync(shots, { recursive: true });
            await page.screenshot({ path: path.join(shots, `${name}.${scheme}.${width}.${images ? 'images' : 'degraded'}.${item.template}.${item.locale}.png`), fullPage: true });
          }
        }
        await context.unroute(APP + '/raffi/**');
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
    JSON.stringify({ execution: 'local static HTML in headless browsers; nothing sent', summary, failures: failed.slice(0, 50), expected: index.previews.length * 16, results: all }, null, 2));
  console.log(JSON.stringify(summary));
  if (failed.length) console.log(JSON.stringify(failed.slice(0, 5), null, 1));
  process.exitCode = failed.length || errors.length ? 1 : 0;
})();
