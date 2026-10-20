/** Real local Next -> Python -> PostgreSQL -> worker. X and login identities are SYNTHETIC. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { chromium, webkit } = require('playwright');
const control = JSON.parse(fs.readFileSync(process.env.RAFII_X_FIXTURE_CONTROL_FILE, 'utf8'));
const base = process.env.RAFII_X_BROWSER_BASE || control.base;
assert.equal(new URL(base).hostname, '127.0.0.1');
assert.equal(control.classification, 'synthetic-local-only');
const out = path.resolve(process.env.RAFII_X_BROWSER_EVIDENCE_DIR);
fs.mkdirSync(out, { recursive: true });
const fixtureHeaders = { 'X-Fixture-Secret': control.secret, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAUAAAAFACAIAAABC8jL9AAADt0lEQVR4nO3TQQ0AIBDAMMC/58MDH7KkVbDP9swsoOn8DgDeGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwLC6LhItBX3KIhzFAAAAAElFTkSuQmCC', 'base64');
const cases = process.env.RAFII_X_BROWSER_DESKTOP_ONLY ? [['desktop-chromium', chromium, 1440, process.env.RAFII_X_CHROMIUM_EXECUTABLE]] : [
  ['desktop-chromium', chromium, 1440, process.env.RAFII_X_CHROMIUM_EXECUTABLE],
  ['mobile-webkit', webkit, 390, process.env.RAFII_X_WEBKIT_EXECUTABLE]
];
const results = [];
async function main() {
  for (const [name, type, width, executablePath] of cases) {
    const browser = await type.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
    let page;
    try {
      const context = await browser.newContext({ viewport: { width, height: 1000 }, isMobile: width < 600, reducedMotion: 'reduce' });
      const principal = randomUUID();
      await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
      await context.addInitScript(id => {
        localStorage.setItem('postriff-dev-principal', id);
        localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
      }, principal);
      const blocked = [];
      await context.route('**/*', route => {
        const origin = new URL(route.request().url()).origin;
        if (origin === base) return route.continue();
        blocked.push(origin); return route.abort();
      });
      const headers = { Authorization: 'Bearer dev:' + principal, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
      async function api(method, endpoint, data, expected = 200) {
        const response = await context.request.fetch(base + endpoint, { method, headers, data });
        assert.equal(response.status(), expected, `${method} ${endpoint}: ${response.status()} ${(await response.text()).slice(0,600)}`);
        return response.json();
      }
      async function stats() {
        const response = await context.request.get(base + '/api/x-fixture/stats', { headers: fixtureHeaders });
        assert.ok(response.ok()); return response.json();
      }
      async function tick() {
        const response = await context.request.post(base + '/api/x-fixture/tick', { headers: fixtureHeaders, data: {} });
        assert.ok(response.ok(), await response.text()); return response.json();
      }
      const boot = await api('POST', '/api/auth/verify', { plan: 'studio' }, 201);
      const wid = boot.workspaceId; assert.ok(wid);
      page = await context.newPage(); page.setDefaultTimeout(30000);
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base + '/app/x', { waitUntil: 'domcontentloaded', timeout: 90000 });
      await page.getByRole('heading', { name: 'Manage X', exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Approve this action', exact: true }).count(), 0);
      const started = await api('POST', `/api/workspaces/${wid}/channels/x/oauth/start`, { capability: 'publish' }, 201);
      assert.ok(started.scopes.includes('media.write'));
      assert.equal(new URL(started.authorizeUrl).origin, base);
      await page.waitForLoadState('networkidle', { timeout: 30000 });
      await page.goto(started.authorizeUrl);
      const completedOAuth = page.waitForResponse(response => response.url().endsWith('/channels/x/oauth/complete') && response.status() === 200, { timeout: 30000 });
      await page.getByRole('button', { name: 'Allow synthetic X account', exact: true }).click();
      await page.waitForURL(url => url.pathname !== '/dev/x/consent' && url.pathname !== '/api/oauth/x/callback', { timeout: 30000 });
      await completedOAuth.catch(async () => {
        const channels = await api('GET', `/api/workspaces/${wid}/channels`);
        assert.ok(channels.channels.some(c => c.platform === 'X'), 'Actual authenticated callback must create a connection.');
      });
      const channels = await api('GET', `/api/workspaces/${wid}/channels`);
      const connected = channels.channels.find(c => c.platform === 'X'); assert.ok(connected);
      const cid = connected.id, endpoint = `/api/workspaces/${wid}/x/${cid}`;
      await page.waitForLoadState('networkidle', { timeout: 30000 });
      await page.goto(base + '/app/x?channel=' + cid);
      await page.getByLabel('Connected X account', { exact: true }).getByRole('option', { name: /synthetic_x_customer/ }).waitFor({ state: 'attached' });
      await page.getByLabel('Action', { exact: true }).getByRole('option', { name: 'Upload approved workspace media', exact: true }).waitFor({ state: 'attached' });
      const before = await stats();
      await page.getByLabel('Action', { exact: true }).selectOption('media.upload');
      await page.getByLabel('Add image to this workspace', { exact: true }).setInputFiles({ name: 'synthetic-score.png', mimeType: 'image/png', buffer: png });
      await page.getByLabel('Workspace media asset', { exact: true }).getByRole('option', { name: /image\/jpeg/ }).waitFor({ state: 'attached' });
      const assetId = await page.getByLabel('Workspace media asset', { exact: true }).locator('option').last().getAttribute('value');
      await page.getByLabel('Workspace media asset', { exact: true }).selectOption(assetId);
      await page.getByLabel('alt text', { exact: true }).fill('Synthetic printed piano score');
      await page.getByRole('button', { name: 'Preview exact action', exact: true }).click();
      await page.getByRole('heading', { name: 'Review exact action', exact: true }).waitFor();
      assert.equal((await stats()).media, before.media, 'Preview cannot upload to the provider.');
      assert.equal(await page.getByRole('button', { name: 'Approve this action', exact: true }).isEnabled(), false);
      await page.getByLabel('Approve this exact action and estimated usage', { exact: true }).check();
      await page.getByRole('button', { name: 'Approve this action', exact: true }).click();
      await page.getByRole('status').filter({ hasText: /Approval recorded/ }).waitFor();
      let upload;
      for (let attempt = 0; attempt < 8; attempt++) {
        await tick(); const overview = await api('GET', endpoint);
        upload = overview.operations.find(op => op.operation === 'media.upload');
        if (upload?.state === 'verified') break;
        await page.waitForTimeout(200);
      }
      assert.equal(upload?.state, 'verified', JSON.stringify(upload));
      assert.equal(upload.receipts.length, 2); assert.equal(upload.receipts[0].mediaStep, 'upload');
      assert.equal(upload.receipts[1].mediaStep, 'metadata');
      const mediaId = upload.receipts[1].resourceId;
      assert.ok(mediaId && upload.receipts[1].mediaReady);
      // Exercise the actual live-polled receipt update, without replacing the page.
      await page.locator(`[data-x-operation="${upload.id}"][data-x-state="verified"]`).waitFor();
      await page.getByLabel('Action', { exact: true }).selectOption('posts.create');
      await page.getByLabel('text', { exact: true }).fill('Approved synthetic media post — ' + name);
      await page.getByLabel('Attach uploaded media ' + mediaId, { exact: true }).check();
      const prePost = await stats();
      await page.getByRole('button', { name: 'Preview exact action', exact: true }).click();
      await page.getByRole('heading', { name: 'Review exact action', exact: true }).waitFor();
      assert.equal((await stats()).posts, prePost.posts, 'Post preview cannot publish.');
      await page.getByLabel('Approve this exact action and estimated usage', { exact: true }).check();
      await page.getByRole('button', { name: 'Approve this action', exact: true }).click();
      await page.getByRole('status').filter({ hasText: /Approval recorded/ }).waitFor();
      let post;
      for (let attempt = 0; attempt < 8; attempt++) {
        await tick(); post = (await api('GET', endpoint)).operations.find(op => op.operation === 'posts.create');
        if (post?.state === 'verified') break;
        await page.waitForTimeout(200);
      }
      assert.equal(post?.state, 'verified', JSON.stringify(post));
      assert.deepEqual(post.receipts.map(r => r.method), ['POST', 'GET']);
      assert.deepEqual(post.receipts[1].mediaKeys, [upload.receipts[1].mediaKey]);
      const finalStats = await stats();
      assert.equal(finalStats.posts, prePost.posts + 1);
      assert.ok(finalStats.authEvents.some(event => event.event === 'pkce_exchange' && event.s256Verified));
      assert.equal(finalStats.realProviderCalls, 0);
      // Full durable schedule approval and cancellation through the same API,
      // while the browser confirms the row and retained receipts.
      const scheduled = await api('POST', endpoint + '/preview', { operation: 'posts.create', body: { text: 'Never publish this canceled synthetic schedule' }, requestKey: randomUUID(), scheduleAt: Date.now() / 1000 + 3600 }, 201);
      await api('POST', `${endpoint}/operations/${scheduled.id}/approve`, { digest: scheduled.digest, confirmed: true }, 202);
      await api('POST', `${endpoint}/operations/${scheduled.id}/cancel`, {});
      await tick(); assert.equal((await stats()).posts, finalStats.posts);
      assert.equal((await api('GET', endpoint)).operations.find(op => op.id === scheduled.id).state, 'canceled');
      const stranger = await context.request.get(base + endpoint, { headers: { ...headers, Authorization: 'Bearer dev:' + randomUUID() } });
      assert.ok([403, 404].includes(stranger.status()));
      await page.locator(`[data-x-operation="${post.id}"][data-x-state="verified"]`).waitFor();
      await page.locator(`[data-x-operation="${scheduled.id}"][data-x-state="canceled"]`).waitFor();
      await page.waitForLoadState('networkidle', { timeout: 30000 });
      await page.getByRole('heading', { name: 'Manage X', exact: true }).waitFor();
      await page.getByText('Recorded API result 1', { exact: true }).first().waitFor();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No horizontal overflow.');
      assert.deepEqual(errors, []); assert.deepEqual(blocked, [], 'No external browser requests are allowed.');
      await page.screenshot({ path: path.join(out, `SYNTHETIC-X-${name}-${width}.png`), fullPage: true });
      results.push({ name, width, authenticated: 'synthetic Rafii session', oauth: 'real PKCE/SQL with synthetic X consent', mediaUpload: 'verified synthetic response', altText: true, postReadback: true, scheduleCanceled: true, foreignTenantDenied: true, noOverflow: true, errors, realProviderCalls: 0 });
      await context.close();
    } catch (error) {
      if (page) {
        await page.screenshot({ path: path.join(out, `SYNTHETIC-FAILURE-${name}.png`), fullPage: true }).catch(() => {});
        fs.writeFileSync(path.join(out, 'failure-page.txt'), (await page.locator('body').innerText().catch(() => '')).slice(0,8000));
      }
      fs.writeFileSync(path.join(out, 'browser-result.json'), JSON.stringify({ status: 'FAIL', evidenceClass: 'synthetic', results, error: error.message }, null, 2));
      throw error;
    } finally { await browser.close(); }
  }
  const result = { status: 'PASS', evidenceClass: 'local application E2E with synthetic provider and identity', publicReady: false, results };
  fs.writeFileSync(path.join(out, 'browser-result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
