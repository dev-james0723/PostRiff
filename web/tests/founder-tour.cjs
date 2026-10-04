/** Local Demo recording of the real UI/API/database. Synthetic identity; no hosted access or provider calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = process.env.RAFII_WEB_URL;
const api = process.env.RAFII_API_URL;
for (const url of [base, api]) {
  const parsed = new URL(url);
  assert.equal(parsed.protocol, 'http:');
  assert.ok(['localhost', '127.0.0.1'].includes(parsed.hostname), 'Tour requires the disposable local harness');
}
const out = path.resolve(process.env.FOUNDER_EVIDENCE_DIR);
async function exchange(context) {
  const result = await context.request.post(base + '/api/control/v2/session/exchange', { headers: { Origin: base, Authorization: 'Bearer synthetic-founder-aal2', 'X-Control-Exchange': '1' }, data: {} });
  assert.equal(result.status(), 200);
}
async function main() {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  let context;
  try {
    context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', recordVideo: { dir: path.join(out, 'tour-recordings'), size: { width: 1440, height: 900 } } });
    await exchange(context);
    const page = await context.newPage();
    const failures = [];
    page.on('pageerror', e => failures.push(e.message));
    page.on('response', r => { if (r.url().includes('/api/control/') && r.status() >= 400) failures.push(r.status() + ' ' + new URL(r.url()).pathname); });
    await page.goto(base + '/founder?mode=demo');
    await page.getByRole('heading', { name: 'Overview', exact: true }).waitFor();
    await page.getByText('Fictional dataset. No real emails, calls or account changes.', { exact: true }).waitFor();
    await page.getByText('10,000', { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(out, 'tour-desktop-demo.png'), fullPage: true });
    await page.waitForTimeout(1200); // Reading time in the requested recording, after the scene is verified.
    await page.goto(base + '/founder/customers?mode=demo');
    const first = page.locator('tbody button[aria-label^="Open "]').first();
    await first.waitFor();
    const name = (await first.getAttribute('aria-label')).slice(5);
    const search = page.getByRole('searchbox', { name: 'Search customers', exact: true });
    const filtered = page.waitForResponse((response) => response.url().endsWith('/workspace/demo/query') && response.request().postDataJSON()?.search === name && !response.request().postDataJSON()?.recordId);
    await search.fill(name);
    assert.equal((await filtered).status(), 200);
    await page.getByRole('button', { name: 'Open ' + name, exact: true }).first().click();
    await page.getByRole('dialog').waitFor();
    await page.getByRole('dialog').getByRole('heading').filter({ hasText: name }).waitFor();
    assert.ok((await page.getByRole('dialog').innerText()).includes(name));
    const actions = page.getByRole('region', { name: 'Demo workspace actions' });
    const workspaceName = actions.getByRole('textbox', { name: 'Sample workspace name' });
    const originalWorkspaceName = await workspaceName.inputValue();
    await workspaceName.fill('Fictional founder tour workspace');
    await actions.getByRole('button', { name: 'Save sample workspace', exact: true }).click();
    await actions.getByRole('status').filter({ hasText: 'Sample workspace saved.' }).waitFor();
    await page.screenshot({ path: path.join(out, 'tour-sandbox-action.png') });
    await page.waitForTimeout(1200);
    await actions.getByRole('button', { name: 'Reset my Demo', exact: true }).click();
    await actions.getByRole('status').filter({ hasText: 'Your Demo changes were reset.' }).waitFor();
    assert.equal(await workspaceName.inputValue(), originalWorkspaceName);
    await page.getByRole('dialog').getByRole('tab', { name: 'Billing', exact: true }).click();
    await page.getByRole('dialog').getByRole('table', { name: 'Payments', exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'tour-customer-details.png') });
    await page.waitForTimeout(1200);
    await page.keyboard.press('Escape');
    await page.goto(base + '/founder/revenue?mode=demo&tab=payments');
    await page.getByRole('tab', { name: 'Payments', selected: true }).waitFor();
    await page.getByRole('heading', { name: 'Payment failures by day', exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'tour-payments.png'), fullPage: true });
    await page.waitForTimeout(1200);
    assert.deepEqual(failures, []);
    const video = page.video();
    await context.close(); context = null;
    await video.saveAs(path.join(out, 'founder-demo-workflow.webm'));
    fs.writeFileSync(path.join(out, 'tour.json'), JSON.stringify({ execution: 'local real UI/API/PostgreSQL; synthetic identity and fictional Demo data; no hosted acceptance', status: 'passed', scenes: ['Overview', 'customer search', 'saved sandbox workspace rename and reset', 'linked billing detail', 'billing review'], base, api }, null, 2));
  } finally { if (context) await context.close(); await browser.close(); }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
