/** Actual UI + disposable PostgreSQL + synthetic inbound provider. Never places a call. */
const { chromium } = require('playwright');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:3296';
if (!['localhost', '127.0.0.1'].includes(new URL(base).hostname)) throw new Error('Local fake harness only');
const principal = randomUUID();
const headers = { Authorization: `Bearer dev:${principal}`, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha' };

async function api(method, url, body) {
  const response = await fetch(base + url, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  assert.ok(response.ok, `${method} ${url}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}

(async () => {
  const workspace = await api('POST', '/api/auth/verify', { plan: 'studio' });
  const pg = process.env.RAFII_HARNESS_PG_PORT || '55761';
  const code = `import psycopg\nfrom consumer_fixtures import approve_budgets\napprove_budgets(lambda: psycopg.connect("host=127.0.0.1 port=${pg} dbname=postgres"), ${JSON.stringify(workspace.workspaceId)})`;
  execFileSync(process.env.RAFII_PYTHON || 'python3', ['-c', code], {
    cwd: path.resolve(__dirname, '../..'),
    env: { ...process.env, PYTHONPATH: 'src:tests' },
    stdio: 'inherit',
  });

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addCookies([
      { name: 'postriff_dev', value: '1', url: base },
      { name: 'postriff_dev_principal', value: principal, url: base },
      { name: 'postriff_theme', value: 'rafii', url: base },
    ]);
    await context.addInitScript((id) => localStorage.setItem('postriff-dev-principal', id), principal);
    const page = await context.newPage();
    await page.clock.install({ time: Date.now() });
    let issueRequests = 0;
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/phone\/inbound-codes$/.test(new URL(request.url()).pathname)) issueRequests += 1;
    });

    await page.goto(base + '/app/account/notifications', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.getByText('Call Rafii by phone', { exact: true }).click();
    const generate = page.getByRole('button', { name: 'Generate new Agent Pairing Code', exact: true });
    await generate.waitFor({ timeout: 90000 });
    await generate.click();
    await page.getByLabel('Agent Pairing Code').waitFor();
    assert.equal(issueRequests, 1, 'Generating a code makes exactly one request');

    await page.getByRole('button', { name: 'Cancel code', exact: true }).click();
    const cooling = page.getByRole('button', { name: /Try again in \d+s/ });
    await cooling.waitFor();
    assert.ok(await cooling.isDisabled(), 'Cancel/recreate remains disabled during the server issue guard');
    assert.match(await page.getByRole('status').filter({ hasText: 'You can create another code' }).innerText(), /in \d+s/);
    assert.equal(issueRequests, 1, 'Cooldown never sends a rejected second request');

    await page.clock.fastForward(31_000);
    await generate.waitFor();
    assert.equal(await generate.isDisabled(), false, 'Generate becomes available when the 30-second guard expires');
    console.log(JSON.stringify({ status: 'PASS', execution: 'actual UI + disposable PostgreSQL + synthetic inbound provider', issueRequests, realCalls: 0 }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
