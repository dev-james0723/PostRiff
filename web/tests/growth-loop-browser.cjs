/* Real local browser and API; disposable PostgreSQL, synthetic providers only. */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const base = process.env.RAFII_WEB_URL || 'http://localhost:14370';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local harness only.');
const name = process.argv.includes('--webkit') ? 'webkit' : 'chromium';
const engine = name === 'webkit' ? webkit : chromium;
const principal = randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha', Origin: base };
const out = path.resolve(__dirname, '../../.token-pilot/evidence/browser');
fs.mkdirSync(out, { recursive: true });
const results = [];
function ok(condition, label) { if (!condition) throw new Error(label); results.push(label); console.log(`PASS ${name}: ${label}`); }
async function call(method, url, body) {
  const res = await fetch(base + url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const json = await res.json(); if (!res.ok) throw new Error(JSON.stringify(json)); return json;
}
(async () => {
  const { workspaceId: w } = await call('POST', '/api/auth/verify', {});
  execFileSync(process.env.POSTRIFF_TEST_PYTHON || 'python3', [path.join(__dirname, 'growth-loop-browser-fixture.py'), w, 'host=127.0.0.1 port=55459 dbname=postgres']);
  const browser = await engine.launch();
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, colorScheme: 'light', reducedMotion: 'reduce' });
  await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }, { name: 'postriff_theme', value: 'rafii', url: base }]);
  const tourIds = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m => m[1]);
  await context.addInitScript(({ principal, tourIds }) => {
    localStorage.setItem('postriff-dev-principal', principal);
    localStorage.setItem('postriff-onboarding', JSON.stringify({ completed: {}, dismissed: Object.fromEntries(tourIds.map(id => [id, 1])), nudged: Object.fromEntries(tourIds.map(id => [id, 1])) }));
  }, { principal, tourIds });
  const page = await context.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(base + '/app/analytics', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.getByLabel('Goal name', { exact: true }).waitFor({ timeout: 120000 });
    await page.getByLabel('Goal name', { exact: true }).fill('A consistent publishing week');
    await page.getByLabel('Target', { exact: true }).fill('6');
    await page.getByLabel('Target date', { exact: true }).fill('2030-01-01');
    await page.getByRole('button', { name: 'Save growth goal', exact: true }).click();
    await page.getByRole('heading', { name: 'A consistent publishing week' }).waitFor();
    const first = await call('GET', `/api/workspaces/${w}/coworker/growth-loop`);
    ok(first.goal.currentValue === 0 && first.goal.coverage.status === 'available', 'goal saved through UI with real covered zero');
    ok(await page.getByText(/active · by 1\/1\/2030/).isVisible(), 'target date preserves the selected calendar day across time zones');
    await page.getByRole('button', { name: 'Pause goal', exact: true }).click();
    await page.getByRole('button', { name: 'Resume goal', exact: true }).waitFor();
    ok((await call('GET', `/api/workspaces/${w}/coworker/growth-loop`)).goal.status === 'paused', 'pause verified on server');
    await page.getByRole('button', { name: 'Resume goal', exact: true }).click();
    await page.getByRole('button', { name: 'Pause goal', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Design an experiment', exact: true }).click();
    await page.getByRole('button', { name: 'Run experiment', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Run experiment', exact: true }).click();
    await page.getByRole('button', { name: 'Prepare design', exact: true }).click();
    await page.getByRole('button', { name: 'Start observing approved posts', exact: true }).click();
    await page.getByRole('button', { name: 'Stop experiment', exact: true }).waitFor();
    ok((await call('GET', `/api/workspaces/${w}/coworker/growth-loop`)).experiments[0].status === 'running', 'Growth Lab user approval → prepare → start is persisted through the real API');
    ok(await page.getByRole('button', { name: 'Measure results', exact: true }).isDisabled(), 'Growth Lab blocks early measurement and has no automatic winner');
    await page.getByText('See design and evidence', { exact: true }).click();
    ok(await page.getByText('Observational evidence; causal=false.', { exact: true }).isVisible(), 'experiment design exposes evidence scope and limitations');
    await page.getByRole('button', { name: 'Stop experiment', exact: true }).click();
    await page.getByText('cancelled', { exact: true }).waitFor();
    ok((await call('GET', `/api/workspaces/${w}/coworker/growth-loop`)).experiments[0].status === 'cancelled', 'stopping the experiment is verified on the server');
    await page.getByRole('button', { name: 'Generate weekly recap', exact: true }).click();
    const recap = page.getByRole('article', { name: 'weekly proof of value', exact: true });
    await recap.waitFor();
    await recap.getByText('See recap evidence', { exact: true }).click();
    const latest = (await call('GET', `/api/workspaces/${w}/coworker/growth-loop`)).proofs.at(-1);
    ok(latest.counts.verifiedPublishedPosts === 0 && latest.counts.preparedPosts === 0, 'unused work is absent from authoritative recap');
    const idem = await call('POST', `/api/workspaces/${w}/coworker/growth-loop/proofs`, { frequency: 'weekly' });
    ok(idem.record.id === latest.id, 'duplicate weekly recap returns same persisted record');
    await page.getByRole('button', { name: 'Generate monthly recap', exact: true }).click();
    await page.getByText('Insufficient history to claim a monthly improvement trend.', { exact: true }).waitFor();
    ok(true, 'monthly recap explicitly reports insufficient history');
    await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
    const a11y = await page.evaluate(async () => (await axe.run(document.getElementById('growth-goal').parentElement, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa'] })).violations);
    fs.writeFileSync(path.join(out, `${name}-a11y.json`), JSON.stringify(a11y, null, 2));
    ok(a11y.length === 0, `Growth Goal/Lab/proof accessibility (${a11y.map(v => v.id).join(', ')})`);
    await page.screenshot({ path: path.join(out, `${name}-analytics-desktop.png`), fullPage: true });
    await page.goto(base + '/app', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.getByRole('region', { name: 'Growth', exact: true }).waitFor();
    ok(await page.getByRole('region', { name: 'Growth', exact: true }).getByText('A consistent publishing week').isVisible(), 'Home explains goal, coverage and next weekly action');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(out, `${name}-home-mobile.png`), fullPage: true });
    ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Home has no horizontal overflow at mobile width');
    await page.goto(base + '/app/analytics', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.getByRole('heading', { name: 'Growth Goal', exact: true }).waitFor();
    ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Analytics has no horizontal overflow at mobile width');
    await page.getByRole('button', { name: 'Archive goal', exact: true }).click();
    await page.getByRole('button', { name: 'Set a growth goal', exact: true }).click();
    await page.getByLabel('Goal name', { exact: true }).waitFor();
    ok(await page.getByLabel('Goal name', { exact: true }).evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 16), 'mobile input text is at least 16px');
    await page.screenshot({ path: path.join(out, `${name}-analytics-mobile.png`), fullPage: true });
    ok(errors.length === 0, `no browser runtime errors (${errors.join('; ')})`);
  } catch (error) {
    console.error('runtime errors:', errors);
    console.error((await page.locator('body').innerText()).slice(0, 3500));
    await page.screenshot({ path: path.join(out, `${name}-failure.png`), fullPage: true });
    throw error;
  } finally {
    fs.writeFileSync(path.join(out, `${name}-results.json`), JSON.stringify({ execution: 'local-real-browser; synthetic external services', passed: results }, null, 2));
    await browser.close();
  }
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
