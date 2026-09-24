/**
 * Home code-splitting check (local harness only): loads /app and records when the dialog chunks are
 * requested relative to the page's load event and first paint. After the change they should arrive after
 * load (idle preload), not on the critical path.
 *   node web/tests/rafii-home-split.cjs
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local harness only.');
const seed = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json'), 'utf8'));
const DIALOGS = ['content-library', 'channel-bloom-dialog', 'language-dialog', 'model-dialog', 'voice-dialog', 'expanded-idea'];

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.RAFII_CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  const tours = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
  const seen = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(tours.map((id) => [id, 1])), nudged: Object.fromEntries(tours.map((id) => [id, 1])) });
  await context.addInitScript(({ id, seen }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', seen);
    localStorage.setItem('postriff-agent-model', 'deterministic-preview');
  }, { id: seed.principal, seen });
  const page = await context.newPage();
  page.setDefaultTimeout(300000);
  const t0 = Date.now();
  const scripts = [];
  page.on('request', (r) => r.resourceType() === 'script' && scripts.push({ url: r.url(), at: Date.now() - t0 }));
  let loadAt = null;
  page.on('load', () => { loadAt = Date.now() - t0; });
  await page.goto(`${base}/app`, { waitUntil: 'load', timeout: 400000 });
  const enter = page.getByRole('button', { name: 'Enter dev workspace' });
  const pod = page.getByRole('button', { name: /^Choose content type and native format/ });
  await pod.or(enter).first().waitFor();
  if (await enter.isVisible().catch(() => false)) { await enter.click(); await pod.waitFor(); }
  const ready = Date.now() - t0;
  await page.waitForTimeout(8000); // idle preload window
  const dialogs = scripts.filter((s) => DIALOGS.some((d) => s.url.includes(d.replaceAll('-', '_')) || s.url.includes(d)));
  const afterLoad = scripts.filter((x) => loadAt !== null && x.at >= loadAt).map((x) => x.url.split('/').pop().slice(0, 90));
  const result = { loadAt, composerReadyAt: ready, totalScripts: scripts.length, scriptsAfterLoad: afterLoad, dialogChunks: dialogs.map((d) => ({ at: d.at, file: d.url.split('/').pop().slice(0, 90) })), dialogChunksBeforeLoad: dialogs.filter((d) => loadAt !== null && d.at < loadAt).length };
  // Opening the Content Library still works after the split.
  await pod.click();
  result.libraryOpens = await page.getByRole('dialog').filter({ has: page.locator('[data-library-item]') }).first().waitFor({ state: 'visible', timeout: 60000 }).then(() => true, () => false);
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  await browser.close();
})();
