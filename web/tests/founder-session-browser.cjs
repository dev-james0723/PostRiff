/** Focused regression for a question sent while the real founder session is loading. Local QA only. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const base = (process.env.RAFII_WEB_URL || 'http://localhost:4439').replace(/\/$/, '');
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Disposable local founder harness only.');
const out = path.resolve(process.env.FOUNDER_EVIDENCE_DIR || '.codex/founder-session-evidence');
const checks = [];
function check(name, ok) {
  checks.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.RAFII_CHROMIUM_PATH || undefined });
  let releaseSession;
  let completed = false;
  let page;
  const pageErrors = [];
  const controlResponses = [];
  const gate = new Promise((resolve) => { releaseSession = resolve; });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', extraHTTPHeaders: { Connection: 'close' } });
    const exchange = await context.request.post(base + '/api/control/v2/session/exchange', {
      headers: { Origin: base, Authorization: 'Bearer synthetic-founder-aal2', 'X-Control-Exchange': '1' }, data: {}
    });
    if (exchange.status() !== 200) throw new Error(`Local founder exchange: ${exchange.status()}`);
    await context.route('**/api/control/v2/session', async (route) => { await gate; await route.continue(); });
    page = await context.newPage();
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('response', (response) => {
      if (response.url().includes('/api/control/v2/')) controlResponses.push({ path: new URL(response.url()).pathname, status: response.status() });
    });
    let turns = 0;
    page.on('request', (request) => {
      if (request.url().endsWith('/api/control/v2/agent/turns') && request.method() === 'POST') turns += 1;
    });
    // The session request starts after hydration. An SSR button can be visible before its handler exists.
    await Promise.all([
      page.waitForRequest((request) => request.url().endsWith('/api/control/v2/session'), { timeout: 60000 }),
      page.goto(base + '/founder?mode=demo', { waitUntil: 'domcontentloaded', timeout: 60000 })
    ]);
    await page.getByRole('button', { name: 'Ask Rafii', exact: true }).first().click();
    const box = page.getByRole('textbox', { name: 'Ask Rafii' });
    await box.waitFor();
    const question = 'Summarise the three things that need me today.';
    await box.fill(question);
    check('Send waits for the authenticated environment', await page.getByRole('button', { name: 'Send', exact: true }).isDisabled());
    const suggestions = page.getByRole('group', { name: 'Suggested questions' }).getByRole('button');
    check('Suggested questions wait for the authenticated environment', await suggestions.first().isDisabled());
    await box.press('Enter');
    check('Enter while the session loads preserves the typed question', await box.inputValue() === question);
    check('No turn is dispatched while the session loads', turns === 0);
    releaseSession();
    await page.getByText('Viewing Overview · Demo data · local', { exact: false }).waitFor({ timeout: 30000 });
    check('Send becomes available after the real session is ready', await page.getByRole('button', { name: 'Send', exact: true }).isEnabled());
    await box.fill(question);
    check('The ready composer contains the preserved question', await box.inputValue() === question);
    const [turn] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/control/v2/agent/turns') && response.request().method() === 'POST', { timeout: 60000 }),
      box.press('Enter')
    ]);
    check('A ready Demo turn is accepted', turn.status() === 201);
    await page.getByRole('article', { name: "Rafii's answer" }).first().waitFor({ timeout: 30000 });
    check('The real QA answer stays in the visible Demo/local thread', true);
    await page.screenshot({ path: path.join(out, 'founder-session-ready.png') });
    completed = true;
  } catch (error) {
    if (page) {
      await page.screenshot({ path: path.join(out, 'founder-session-failed.png') }).catch(() => {});
      console.error((await page.locator('body').innerText().catch(() => '')).slice(-1800));
      console.error(JSON.stringify({ pageErrors, controlResponses }));
    }
    throw error;
  } finally {
    releaseSession();
    await browser.close();
    const result = { status: completed && checks.every((c) => c.ok) ? 'PASS' : 'FAIL', execution: 'real browser/API/disposable PG; delayed session transport; synthetic founder and model only', checks, pageErrors, controlResponses, realProviderCalls: 0 };
    fs.writeFileSync(path.join(out, 'founder-session.json'), JSON.stringify(result, null, 2) + '\n');
  }
  if (checks.some((c) => !c.ok)) process.exitCode = 1;
})().catch((error) => { console.error(error); process.exitCode = 1; });
