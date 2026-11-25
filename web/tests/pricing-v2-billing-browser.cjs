/** Source-only React scene proof with real billing components/styles and synthetic reads.
 * No app bootstrap, API/PG, auth, provider or payment execution. Only loopback:3038.
 * TASK8_EVIDENCE_DIR must point inside this worker's ignored ledger.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const postcss = require('postcss');
const tailwind = require('@tailwindcss/postcss');
const webpackBundle = require('next/dist/compiled/webpack/webpack');
const { webpack } = webpackBundle;
const { chromium } = require('playwright');
const { environment } = require('./pricing-v2-billing-loader.cjs');
const { usage, balance, legacy, creator } = require('./pricing-v2-billing-fixtures.cjs');
const WEB = path.resolve(__dirname, '..');
const ROOT = path.dirname(WEB);
const LEDGER = path.join(ROOT, '.superpowers/sdd/2026-09-28-rafii-pricing-credits-app-wide');
const out = path.resolve(process.env.TASK8_EVIDENCE_DIR || path.join(LEDGER, 'task-8-browser'));
assert.ok(out.startsWith(LEDGER + path.sep), 'Evidence must stay in own ignored ledger');
fs.mkdirSync(out, { recursive: true });
const base = 'http://127.0.0.1:3038';
const free = usage('free_preview', { subscription: null, lifecycle: { status: 'free' } });
free.entitlement.plan = 'free'; free.entitlement.planTermsId = 'free-v1';
const ended = { ...free, subscription: { ...usage().subscription, status: 'cancelled' } };
const member = usage(); member.membership = { ...member.membership, role: 'viewer', permissions: ['read'] };
const purchasable = usage('free_preview', { ...free, billing: { provider: 'fixture', checkoutAvailable: true, portalAvailable: false }, planTerms: [creator(7900, { status: 'active', newCheckoutEnabled: true, checkoutAvailable: true })] });
const scenes = {
  managed: usage(),
  unknown: usage('managed_credits', { credits: balance({ currentPeriodGrantMilliCredits: null, currentPeriodExpiresAt: null }) }),
  debt: usage('managed_credits', { credits: balance({ debtMilliCredits: 90000, spendUnavailableReason: 'credit_debt' }) }),
  exempt: usage('managed_credits', { credits: null, aiUsageExempt: true }),
  free, ended, legacy19: legacy(1900), legacy39: legacy(3900), member, purchasable,
  unavailablePacks: usage(),
  r1Plans: purchasable,
  r1Packs: usage()
};
const results = [];
function check(name, fn) {
  return Promise.resolve().then(fn).then(() => { results.push({ name, ok: true }); console.log(`ok ${name}`); });
}
async function r1Scenes(page, width) {
  async function expect(name, fn) {
    try { await fn(); results.push({ name: `${width}/R1/${name}`, ok: true }); console.log(`ok ${width}/R1/${name}`); }
    catch (error) { results.push({ name: `${width}/R1/${name}`, ok: false, error: error.message }); console.log(`FAIL ${width}/R1/${name}: ${error.message}`); }
  }
  const enabled = name => page.getByRole('button', { name, exact: true }).and(page.locator(':enabled'));
  const planCheckout = () => page.locator('#plans button:enabled');
  const reads = method => page.evaluate(method => window.task8Reads[method](), method);
  const settled = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.goto(`${base}/r1Plans`, { waitUntil: 'networkidle' });
  await expect('successful owner has Creator checkout', async () => assert.equal(await planCheckout().count(), 1));
  await reads('failUsage'); await settled();
  await expect('failed Usage retains marked price display', async () => { assert.match(await page.locator('main').innerText(), /Couldn’t refresh/); assert.match(await page.locator('#plans').innerText(), /\$79/); });
  await expect('failed Usage removes plan purchase entry points', async () => { assert.equal(await planCheckout().count(), 0); assert.equal(await page.locator('a[href="#plans"]').count(), 0); });
  // Any exposed stale action is exercised only against the refusing synthetic API, never Stripe.
  if (await planCheckout().count()) await planCheckout().click();
  await expect('failed Usage cannot call checkout', async () => assert.equal(await page.evaluate(() => window.task8Reads.calls.length), 0));
  await page.screenshot({ path: path.join(out, `r1-plan-stale-${width}.png`), fullPage: true });
  await reads('recoverUsage'); await settled();
  await expect('successful recovery restores Creator checkout', async () => assert.equal(await planCheckout().count(), 1));
  await page.evaluate(() => window.task8Reads.owner(false)); await settled();
  await expect('fresh read never bypasses current owner permission', async () => { assert.equal(await planCheckout().count(), 0); assert.equal(await page.locator('a[href="#plans"]').count(), 0); });
  await page.evaluate(() => window.task8Reads.owner(true)); await settled();
  const beforePlan = await page.evaluate(() => window.task8Reads.calls.length);
  await planCheckout().click(); await page.getByRole('alert').filter({ hasText: 'Checkout could not be started.' }).waitFor();
  await expect('recovered eligible owner reaches only refusing synthetic checkout', async () => assert.equal(await page.evaluate(() => window.task8Reads.calls.length), beforePlan + 1));

  await page.goto(`${base}/r1Packs`, { waitUntil: 'networkidle' });
  const pack = '1,000 credits · $15.00';
  await expect('successful owner has pack selection', async () => assert.equal(await enabled(pack).count(), 1));
  await reads('failUsage'); await settled();
  await expect('Usage failure before selection removes pack purchase', async () => { assert.equal(await enabled(pack).count(), 0); assert.equal(await page.getByRole('dialog').count(), 0); });
  await reads('recoverUsage'); await settled();
  await expect('successful Usage recovery restores available pack', async () => assert.equal(await enabled(pack).count(), 1));
  await enabled(pack).click(); await page.getByRole('dialog', { name: 'Confirm purchase' }).waitFor();
  await expect('fresh selection opens confirmation', async () => assert.equal(await enabled('Continue to Stripe').count(), 1));
  await reads('failUsage'); await settled();
  await expect('Usage failure after selection suppresses confirmation', async () => { assert.equal(await enabled('Continue to Stripe').count(), 0); assert.equal(await enabled(pack).count(), 0); });
  if (await enabled('Continue to Stripe').count()) await enabled('Continue to Stripe').click();
  await settled();
  await expect('failed Usage cannot submit a selected purchase', async () => assert.equal(await page.evaluate(() => window.task8Reads.calls.length), 0));
  await page.screenshot({ path: path.join(out, `r1-pack-stale-${width}.png`), fullPage: true });
  await reads('recoverUsage'); await settled();
  await expect('recovery requires a new pack selection', async () => assert.equal(await page.getByRole('dialog').count(), 0));
  if (await enabled('Cancel').count()) await enabled('Cancel').click();
  await enabled(pack).click(); await page.getByRole('dialog').waitFor();
  await reads('failPacks'); await settled();
  await expect('failed pack read suppresses selected confirmation', async () => { assert.equal(await enabled('Continue to Stripe').count(), 0); assert.equal(await enabled(pack).count(), 0); });
  await reads('recoverPacks'); await settled();
  await expect('successful pack recovery requires selection again', async () => assert.equal(await page.getByRole('dialog').count(), 0));
  if (await enabled('Cancel').count()) await enabled('Cancel').click();
  await enabled(pack).click(); await page.getByRole('dialog').waitFor();
  await page.evaluate(() => window.task8Reads.owner(false)); await settled();
  await expect('permission loss suppresses pack selection and confirmation', async () => { assert.equal(await enabled(pack).count(), 0); assert.equal(await enabled('Continue to Stripe').count(), 0); });
  await page.evaluate(() => window.task8Reads.owner(true)); await settled();
  await expect('owner restoration requires fresh selection', async () => assert.equal(await page.getByRole('dialog').count(), 0));
  if (await enabled('Cancel').count()) await enabled('Cancel').click();
  await enabled(pack).click(); await page.getByRole('dialog').waitFor();
  const beforePack = await page.evaluate(() => window.task8Reads.calls.length);
  await enabled('Continue to Stripe').click(); await page.getByRole('alert').filter({ hasText: 'Synthetic scene refuses purchases' }).waitFor();
  await expect('recovered owner and successful catalog reach only refusing synthetic purchase', async () => assert.equal(await page.evaluate(() => window.task8Reads.calls.length), beforePack + 1));
}
async function main() {
  const loader = path.join(out, 'typescript-loader.cjs');
  fs.writeFileSync(loader, `const ts=require(${JSON.stringify(require.resolve('typescript'))});module.exports=function(source){return ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2023,jsx:ts.JsxEmit.ReactJSX}}).outputText;};`);
  const mocks = path.join(__dirname, 'pricing-v2-billing-scene-mocks.tsx');
  const aliases = Object.fromEntries(['next/link', 'next/navigation', '@/components/layout/page-container', '@/lib/api/hooks', '@/lib/auth/access', '@/lib/workspace/provider'].map(name => [name + '$', mocks]));
  const stats = await new Promise((resolve, reject) => {
    const compiler = webpack({ mode: 'development', context: WEB, entry: path.join(__dirname, 'pricing-v2-billing-scene.tsx'), output: { path: out, filename: 'client.js' },
      cache: false, devtool: false, resolve: { extensions: ['.tsx', '.ts', '.js'], alias: { ...aliases, '@': path.join(WEB, 'src') } },
      module: { rules: [{ test: /\.tsx?$/, exclude: /node_modules/, use: loader }] } });
    compiler.run((error, result) => { compiler.close(() => {}); if (error) reject(error); else resolve(result); });
  });
  fs.writeFileSync(path.join(out, 'bundle.log'), stats.toString({ colors: false }));
  assert.equal(stats.hasErrors(), false, stats.toString({ colors: false }));
  assert.equal(stats.hasWarnings(), false, stats.toString({ colors: false }));
  const cssFile = path.join(WEB, 'src/styles/globals.css');
  const css = (await postcss([tailwind({ base: WEB, optimize: false })]).process(fs.readFileSync(cssFile, 'utf8'), { from: cssFile })).css;
  fs.writeFileSync(path.join(out, 'billing.css'), css);
  const rendered = new Map();
  for (const [name, data] of Object.entries(scenes)) {
    const packResponse = name === 'r1Packs' ? { available: true, packs: [{ id: 'r1-synthetic-pack', label: 'Synthetic active row', amountCents: 1500, currency: 'usd', milliCredits: 1000000 }] } : name === 'unavailablePacks' ? { available: false, packs: [{ id: 'inactive', label: 'Inactive', amountCents: 1500, currency: 'usd', milliCredits: 1000000 }] } : undefined;
    const markup = environment(data, packResponse).render('features/billing/billing-view.tsx', 'BillingView');
    const fixture = JSON.stringify({ usage: data, packs: packResponse ?? { available: false, packs: [] } }).replace(/</g, '\\u003c');
    const html = `<!doctype html><html lang="en" data-theme="rafii"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Billing synthetic scene ${name}</title><link rel="stylesheet" href="/billing.css"><style>main{max-width:1100px;margin:auto;padding:24px}h1{font-size:1.5rem;margin-bottom:24px}body{font-family:system-ui,sans-serif}</style></head><body><div id="scene">${markup}</div><script>window.task8Scene=${fixture}</script><script src="/client.js"></script></body></html>`;
    rendered.set('/' + name, html); fs.writeFileSync(path.join(out, name + '.html'), html);
  }
  const server = http.createServer((req, res) => {
    const route = new URL(req.url, base).pathname;
    if (route === '/billing.css') { res.writeHead(200, { 'Content-Type': 'text/css' }); res.end(css); }
    else if (route === '/client.js') { res.writeHead(200, { 'Content-Type': 'text/javascript' }); res.end(fs.readFileSync(path.join(out, 'client.js'))); }
    else if (rendered.has(route)) { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(rendered.get(route)); }
    else { res.writeHead(404); res.end(); }
  });
  // EADDRINUSE aborts; never attach to or stop another worker's listener.
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(3038, '127.0.0.1', resolve); });
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.TASK8_CHROMIUM_PATH || undefined });
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, reducedMotion: 'reduce' });
      const errors = [], external = [];
      await context.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) { external.push(route.request().url()); return route.abort(); }
        return route.continue();
      });
      const page = await context.newPage(); page.on('pageerror', err => errors.push(err.message));
      page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
      for (const [name] of process.env.TASK8_R1_ONLY === '1' ? [] : Object.entries(scenes).filter(([name]) => !name.startsWith('r1'))) {
        await page.goto(`${base}/${name}`, { waitUntil: 'networkidle' });
        const tag = `${width}/${name}`;
        await check(`${tag} no horizontal overflow`, async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)));
        await check(`${tag} source styles applied`, async () => assert.equal(await page.locator('[data-tour="billing-plan"]').evaluate(el => getComputedStyle(el).paddingTop), '20px'));
        await check(`${tag} authoritative pack gate`, async () => assert.equal(await page.getByRole('heading', { name: 'Add credits', exact: true }).count(), 0));
        if (name.startsWith('legacy')) {
          await check(`${tag} legacy receipt and allowances`, async () => {
            await page.getByText('Legacy plan', { exact: true }).waitFor();
            assert.ok(await page.getByRole('progressbar', { name: 'AI writing batches' }).count());
            assert.ok((await page.locator('[data-tour="billing-plan"]').innerText()).includes(name === 'legacy19' ? '$19' : '$39'));
          });
        } else {
          await check(`${tag} no legacy allowance meters`, async () => assert.equal(await page.getByRole('progressbar', { name: 'AI writing batches' }).count(), 0));
        }
        const managed = page.getByRole('region', { name: 'Managed credits', exact: true });
        if (['managed', 'unknown', 'debt', 'exempt', 'member', 'unavailablePacks'].includes(name)) {
          const credits = page.locator('section[aria-label="Managed credits"]');
          await check(`${tag} credit readings have no false usage percentage`, async () => { await credits.waitFor(); assert.equal(await credits.getByRole('progressbar').count(), 0); });
          if (name === 'unknown') await check(`${tag} unknown grant and expiry`, async () => assert.match(await credits.innerText(), /Current-period grant\s+Unavailable[\s\S]*expiry unavailable/));
          if (name === 'debt') await check(`${tag} debt announced separately`, async () => assert.match(await credits.getByRole('alert').innerText(), /90 credits/));
        }
        if (['free', 'ended', 'purchasable'].includes(name)) {
          await check(`${tag} actual Free action policy and no wallet`, async () => {
            assert.equal(await managed.count(), 0); assert.equal(await page.locator('section[aria-label="Managed credits"]').count(), 0);
            assert.match(await page.locator('section[aria-labelledby="free-preview-heading"]').innerText(), /1 preview remaining · Preview unavailable/);
            assert.equal(await page.getByRole('heading', { name: 'Free', exact: true }).count(), 1);
          });
        }
        await check(`${tag} actual checkout availability`, async () => assert.equal(await page.getByRole('button', { name: 'Choose Creator', exact: true }).count(), name === 'purchasable' ? 1 : 0));
        if (name === 'member') await check(`${tag} no owner USD disclosure`, async () => assert.equal(await page.getByText('Advanced usage · USD costs', { exact: true }).count(), 0));
        else {
          await check(`${tag} USD disclosure is closed and keyboard accessible`, async () => {
            const summary = page.getByText('Advanced usage · USD costs', { exact: true });
            assert.equal(await summary.locator('..').getAttribute('open'), null);
            await summary.focus(); await page.keyboard.press('Enter');
            assert.notEqual(await summary.locator('..').getAttribute('open'), null);
            await summary.focus(); await page.keyboard.press('Enter');
          });
        }
        if (name === 'ended') await check(`${tag} ended price retained only as history`, async () => {
          const history = page.getByText('Previous plan', { exact: true }); await history.click();
          assert.match(await history.locator('..').innerText(), /Creator · \$49/);
        });
        await page.screenshot({ path: path.join(out, `${name}-${width}.png`), fullPage: true });
      }
      await r1Scenes(page, width);
      await check(`${width} no page errors or external requests`, () => { assert.deepEqual(errors, []); assert.deepEqual(external, []); });
      await context.close();
    }
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ execution: 'synthetic-React-render-browser', apiPG: false, results }, null, 2));
  }
  const failed = results.filter(result => !result.ok).length;
  console.log(`${results.length} synthetic browser checks, ${failed} failed; no API/PG or payment execution.`);
  if (failed) process.exitCode = 1;
}
main().catch(error => { console.error(error); process.exitCode = 1; });
