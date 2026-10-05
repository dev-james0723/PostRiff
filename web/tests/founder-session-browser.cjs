/** Cold founder session: keep a draft until its environment is known, then render the same Demo turn. Local fake-provider harness only. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const base = (process.env.RAFII_WEB_URL || 'http://localhost:4439').replace(/\/$/, '');
assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname), 'This regression uses the disposable local founder harness only.');
const out = path.resolve(process.env.FOUNDER_EVIDENCE_DIR || '.founder-session-evidence');
fs.mkdirSync(out, { recursive: true });
const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), ...(!ok ? { detail } : {}) });
  process.stdout.write(`${ok ? 'ok' : 'FAIL'} ${name}\n`);
}

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.RAFII_CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  let release;
  let page;
  const controlReads = [];
  const held = new Promise((resolve) => { release = resolve; });
  try {
    const login = await context.request.post(base + '/api/control/v2/session/exchange', { headers: { Origin: base, Authorization: 'Bearer synthetic-founder-aal2', 'X-Control-Exchange': '1' }, data: {} });
    assert.equal(login.status(), 200);
    await context.route('**/api/control/v2/session', async (route) => { await held; await route.continue(); });
    page = await context.newPage();
    page.on('response', (response) => { const pathname = new URL(response.url()).pathname; if (pathname.startsWith('/api/control/') && controlReads.length < 100) controlReads.push({ method: response.request().method(), path: pathname, status: response.status() }); });
    let turns = 0;
    page.on('request', (request) => { if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/api/control/v2/agent/turns')) turns += 1; });
    const sessionRead = page.waitForRequest('**/api/control/v2/session', { timeout: 120000 });
    await page.goto(base + '/founder?mode=demo', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await sessionRead;
    await page.getByRole('button', { name: 'Ask Rafii', exact: true }).first().click();
    const box = page.getByRole('textbox', { name: 'Ask Rafii', exact: true });
    await box.waitFor({ timeout: 15000 });
    const question = 'Summarise the three things that need me today.';
    await box.fill(question);
    const send = page.getByRole('button', { name: 'Send', exact: true });
    check('Send waits for the cold founder session environment', await send.isDisabled());
    await box.press('Enter');
    const keptDraft = (await box.inputValue()) === question;
    check('Enter preserves the unsent question while session metadata is pending', keptDraft);
    check('No agent request starts while session metadata is pending', turns === 0, turns);
    await page.screenshot({ path: path.join(out, 'cold-session-pending.png') });
    const accepted = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/api/control/v2/agent/turns'), { timeout: 30000 }).catch(() => null);
    release();
    if (keptDraft) {
      await page.waitForFunction(() => { const button = document.querySelector('button[aria-label="Send"]'); return button instanceof HTMLButtonElement && !button.disabled; }, null, { timeout: 30000 });
      await box.press('Enter');
    }
    const response = await accepted;
    check('The accepted request retains Demo mode', response?.status() === 201 && JSON.parse(response.request().postData()).mode === 'demo', response?.status());
    const answer = page.getByRole('article', { name: "Rafii's answer" }).first();
    const rendered = await answer.waitFor({ timeout: 10000 }).then(() => true, () => false);
    check('The accepted answer stays in the visible Demo/local thread', rendered);
    check('Exactly one question is submitted after readiness', turns === 1, turns);
    await page.screenshot({ path: path.join(out, 'cold-session-completed.png') });
  } catch (error) {
    await page?.screenshot({ path: path.join(out, 'cold-session-failure.png') }).catch(() => {});
    if (page) fs.writeFileSync(path.join(out, 'cold-session-failure.txt'), (await page.locator('body').innerText().catch(() => '')).slice(-6000));
    throw error;
  } finally {
    release();
    await context.close();
    await browser.close();
    fs.writeFileSync(path.join(out, 'founder-session-browser.json'), JSON.stringify({ execution: 'actual local Chromium / API / disposable PostgreSQL; synthetic founder identity and agent provider', checks, controlReads, newPhysicalModelCalls: 0 }, null, 2));
  }
  process.exitCode = checks.some((check) => !check.ok) ? 1 : 0;
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
