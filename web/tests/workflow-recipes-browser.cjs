/** Real native workflow and API/Task Engine/disposable PG; identity and source data are synthetic. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = 'http://127.0.0.1:4439';
const out = process.env.RAFII_RECIPE_EVIDENCE;
assert(out, 'Controlled evidence directory required');
mkdirSync(out, { recursive: true });
const fixtures = JSON.parse(readFileSync(resolve(out, 'fixture.json'), 'utf8'));
let currentPage;
(async () => {
  const checks = [];
  for (const [engine, browserType] of Object.entries({ chromium, webkit })) {
    const browser = await browserType.launch({ headless: true });
    try {
      for (const width of [1440, 390]) {
        const fixture = fixtures.find(f => f.engine === engine && f.width === width);
        assert(fixture);
        const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
        const headers = { Authorization: 'Bearer dev:' + fixture.principal, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Origin: base };
        const path = base + '/api/workspaces/' + fixture.workspaceId + '/agent/recipes';
        await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: fixture.principal, url: base }]);
        await context.addInitScript(id => localStorage.setItem('postriff-dev-principal', id), fixture.principal);
        const page = currentPage = await context.newPage();
        const errors = []; page.on('pageerror', error => errors.push(error.message));
        await page.goto(base + '/app/automations', { waitUntil: 'domcontentloaded' });
        const welcome = page.getByRole('dialog');
        const dismiss = welcome.getByRole('button', { name: 'Not now', exact: true });
        if (await dismiss.waitFor({ state: 'visible', timeout: 5000 }).then(() => true, () => false)) await dismiss.click();
        const section = page.getByRole('region', { name: 'Personal workflow recipes', exact: true });
        await section.getByRole('button', { name: 'New recipe', exact: true }).click();
        const form = section.getByRole('form', { name: 'Recipe settings' });
        const name = `Library review ${engine} ${width}`;
        await form.getByLabel('Name', { exact: true }).fill(name);
        await form.getByLabel('Operations per day', { exact: true }).fill('3');
        await form.getByLabel('Total operations', { exact: true }).fill('5');
        await form.getByLabel('In-app notifications').selectOption('none');
        const saveResponse = page.waitForResponse(r => r.url() === path && r.request().method() === 'POST');
        await form.getByRole('button', { name: 'Save for review', exact: true }).click();
        const saved = await saveResponse; assert.equal(saved.status(), 201, await saved.text());
        const article = section.getByRole('article', { name, exact: true });
        await article.getByRole('checkbox').check();
        const enableResponse = page.waitForResponse(r => r.url().endsWith('/enable') && r.request().method() === 'POST');
        await article.getByRole('button', { name: 'Enable limited Autopilot', exact: true }).click();
        const enabled = await enableResponse; assert.equal(enabled.status(), 200, await enabled.text());
        let listing = await (await context.request.get(path, { headers })).json();
        let recipe = listing.recipes.find(r => r.config.name === name);
        assert(recipe.policyCurrent); const firstPolicy = recipe.policyId;
        const runResponse = page.waitForResponse(r => r.url().endsWith('/run') && r.request().method() === 'POST');
        await article.getByRole('button', { name: 'Run now', exact: true }).click();
        const run = await runResponse; assert.equal(run.status(), 200, await run.text());
        listing = await run.json(); assert.equal(listing.runs[0].state, 'completed'); assert(listing.runs[0].hasReport);
        const reportId = listing.runs[0].id;
        await section.getByRole('button', { name: 'View report', exact: true }).first().click();
        const report = section.getByRole('region', { name: 'Recipe report', exact: true });
        await report.getByRole('link', { name: 'Rehearsal notes', exact: true }).waitFor({ state: 'visible' });
        const stored = await (await context.request.get(path + '/reports/' + reportId, { headers })).json();
        assert.equal(stored.report.items[0].assetId, fixture.assetId);
        assert(!JSON.stringify(stored).includes('SECRET FILE BODY'));
        await section.scrollIntoViewIfNeeded();
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No horizontal overflow');
        await page.screenshot({ path: resolve(out, `${engine}-${width}-report.png`), fullPage: true });
        checks.push({ engine, width, check: 'Native save/inspect/explicit enable/real Task Engine read/stored metadata report; no file contents' });
        const pauseResponse = page.waitForResponse(r => r.url().endsWith('/stop') && r.request().method() === 'POST');
        await article.getByRole('button', { name: 'Pause', exact: true }).click();
        const paused = await pauseResponse; assert.equal(paused.status(), 200, await paused.text()); recipe = await paused.json();
        const refused = await context.request.post(path + '/' + recipe.id + '/run', { headers, data: { expectedVersion: recipe.version, requestKey: randomUUID() } });
        assert.equal(refused.status(), 409, 'Paused recipe cannot admit');
        await article.getByRole('checkbox').check();
        const resumeResponse = page.waitForResponse(r => r.url().endsWith('/enable') && r.request().method() === 'POST');
        await article.getByRole('button', { name: 'Enable limited Autopilot', exact: true }).click();
        const resumed = await resumeResponse; assert.equal(resumed.status(), 200, await resumed.text()); recipe = await resumed.json();
        assert.notEqual(recipe.policyId, firstPolicy, 'Resuming requires a fresh immutable policy');
        const revokeResponse = page.waitForResponse(r => r.url().endsWith('/stop') && r.request().method() === 'POST');
        await article.getByRole('button', { name: 'Revoke', exact: true }).click();
        const revoked = await revokeResponse; assert.equal(revoked.status(), 200, await revoked.text()); recipe = await revoked.json();
        const denied = await context.request.post(path + '/' + recipe.id + '/run', { headers, data: { expectedVersion: recipe.version, requestKey: randomUUID() } });
        assert.equal(denied.status(), 409, 'Revoked recipe cannot admit');
        await page.goto(base + '/app/automations?recipeReport=' + reportId, { waitUntil: 'domcontentloaded' });
        await section.getByRole('region', { name: 'Recipe report' }).getByRole('link', { name: 'Rehearsal notes' }).waitFor({ state: 'visible' });
        const revokeSource = await context.request.post(path.replace('/recipes', '/permissions/revoke'), { headers, data: { scopes: ['domain:library'], idempotencyKey: randomUUID() } });
        assert.equal(revokeSource.status(), 200, await revokeSource.text());
        const hidden = await context.request.get(path + '/reports/' + reportId, { headers });
        assert.equal(hidden.status(), 403, 'Source revocation hides saved report body');
        assert.deepEqual(errors, []);
        checks.push({ engine, width, check: 'Pause refuses run; explicit resume creates new policy; revoke refuses run; native deep-link reopens retained receipt; source revoke hides report' });
        await context.close(); currentPage = null;
      }
    } finally { await browser.close(); }
  }
  writeFileSync(resolve(out, 'browser-receipt.json'), JSON.stringify({ execution: 'real native UI/API/Task Engine/disposable PG; synthetic identity and source data; zero providers', checks }, null, 2));
  console.log(JSON.stringify({ checks, status: 'PASS' }));
})().catch(async error => {
  writeFileSync(resolve(out, 'browser-failure.json'), JSON.stringify({ error: error.stack }, null, 2));
  if (currentPage && !currentPage.isClosed()) await currentPage.screenshot({ path: resolve(out, 'browser-failure.png'), fullPage: true }).catch(() => {});
  console.error(error); process.exitCode = 1;
});
