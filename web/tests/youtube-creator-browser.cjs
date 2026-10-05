/** Real local Next -> hosted Python -> disposable PostgreSQL; SYNTHETIC Google and identity. Never real E2E. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
const base = process.env.YOUTUBE_WEB_URL || 'http://127.0.0.1:4448';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = resolve(__dirname, '../../docs/youtube/evidence');
mkdirSync(out, { recursive: true });
const results = [];
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 390, 320]) {
      const principal = randomUUID();
      const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
      await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
      await context.addInitScript(id => {
        localStorage.setItem('postriff-dev-principal', id);
        localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
      }, principal);
      await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
      const headers = { Authorization: 'Bearer dev:' + principal, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
      const request = async (method, path, data) => {
        const response = await context.request.fetch(base + path, { method, headers, data });
        assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`);
        return response.json();
      };
      const boot = await request('POST', '/api/auth/verify', { plan: 'studio' });
      const wid = boot.workspaceId;
      const started = await request('POST', `/api/workspaces/${wid}/channels/youtube/oauth/start`, { capability: 'publish' });
      const connected = await request('POST', `/api/workspaces/${wid}/channels/youtube/oauth/complete`, { state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'synthetic-code' });
      const cid = connected.connectionId;
      const overview = await request('GET', `/api/workspaces/${wid}/youtube/${encodeURIComponent(cid)}`);
      assert.equal(Object.keys(overview.capabilities).length, 37);
      assert.equal(overview.readiness.production, 'NOT READY');
      assert.equal(overview.capabilities.community_posts.state, 'UNSUPPORTED BY OFFICIAL API');
      assert.ok(Object.values(overview.capabilities).every(cap => cap.state !== 'READY'));
      const page = await context.newPage();
      page.setDefaultTimeout(30000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => {
        if (message.type() === 'error' && /same key|Encountered two children|Hydration failed/.test(message.text())) errors.push('React reconciliation error');
      });
      await page.goto(base + '/app/youtube');
      await page.getByRole('heading', { name: 'YouTube creator', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Capabilities', exact: true }).click();
      await page.getByText('UNSUPPORTED BY OFFICIAL API', { exact: true }).first().waitFor();
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).count(), 0);
      assert.equal(await page.getByLabel('Visibility', { exact: true }).count(), 0);
      await page.screenshot({ path: resolve(out, `LOCAL-SYNTHETIC-capabilities-${width}.png`), fullPage: true });
      await page.getByRole('button', { name: 'Videos', exact: true }).click();
      await page.getByLabel('Video ID', { exact: true }).fill('abcdefghijk');
      await page.getByRole('button', { name: 'Inspect video processing', exact: true }).click();
      const reviewedTitle = 'Exact reviewed local title ' + width + ' ' + principal.slice(0, 8);
      await page.getByLabel('Title', { exact: true }).fill(reviewedTitle);
      await page.getByLabel('Description', { exact: true }).fill('Exact reviewed local description\nhttps://example.com');
      const privacy = page.getByLabel('Visibility', { exact: true });
      assert.deepEqual(await privacy.locator('option').allTextContents(), ['Private']);
      await page.getByRole('button', { name: 'Review metadata change', exact: true }).click();
      await page.getByRole('heading', { name: 'Approve this exact YouTube action', exact: true }).waitFor();
      // Review is an HTTP/DB candidate; the provider still has its old title.
      const before = await request('POST', `/api/workspaces/${wid}/youtube/${encodeURIComponent(cid)}/read/videos`, { id: 'abcdefghijk' });
      assert.notEqual(before.items[0].snippet.title, reviewedTitle);
      const [approvedResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/approve') && response.request().method() === 'POST'),
        page.getByRole('button', { name: 'Approve exact action', exact: true }).click()
      ]);
      const approved = await approvedResponse.json();
      assert.equal(approved.status, 'verified', JSON.stringify({ error: approved.error, status: approved.status, verification: approved.receipt?.verification }));
      await page.getByText(/Edit video: verified/).waitFor();
      const after = await request('POST', `/api/workspaces/${wid}/youtube/${encodeURIComponent(cid)}/read/videos`, { id: 'abcdefghijk' });
      assert.equal(after.items[0].snippet.title, reviewedTitle);
      assert.deepEqual(after.items[0].snippet.tags, ['preserve']);
      await page.getByRole('button', { name: 'Review deletion', exact: true }).click();
      await page.getByLabel('Confirm resource ID', { exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).isEnabled(), false);
      await page.getByLabel('Confirm resource ID', { exact: true }).fill('wrong-video');
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).isEnabled(), false);
      await page.getByRole('button', { name: 'Discard review', exact: true }).click();
      await page.getByRole('button', { name: 'Live', exact: true }).click();
      const [streamsResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/read/streams')),
        page.getByRole('button', { name: 'List streams', exact: true }).click()
      ]);
      assert.ok(streamsResponse.ok());
      assert.equal((await streamsResponse.json()).items[0].id, 'local-stream');
      await page.getByRole('button', { name: /Local stream/ }).first().waitFor();
      assert.equal(await page.locator('body').textContent().then(text => text.includes('synthetic-private-stream-key')), false);
      await page.getByLabel('Stream ID', { exact: true }).fill('local-stream');
      const [configurationResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/stream-configuration')),
        page.getByRole('button', { name: 'Read ingestion configuration after fresh owner sign-in', exact: true }).click()
      ]);
      assert.ok(configurationResponse.ok(), 'Fresh owner must be able to read an existing owned stream configuration.');
      await page.getByLabel('Stream key', { exact: true }).waitFor();
      assert.equal(await page.getByLabel('Stream key', { exact: true }).getAttribute('type'), 'password');
      await page.getByRole('button', { name: 'Clear private stream configuration', exact: true }).click();
      assert.equal(await page.getByLabel('Stream key', { exact: true }).count(), 0);
      const overflow = await page.evaluate(() => ({ width: window.innerWidth, document: document.documentElement.scrollWidth,
        elements: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > window.innerWidth + 1 && el.getBoundingClientRect().width > 0).slice(-12).map(el => ({ tag: el.tagName, width: Math.round(el.getBoundingClientRect().width), text: el.textContent.slice(0, 80) })) }));
      assert.ok(overflow.document <= overflow.width + 1, JSON.stringify(overflow));
      await page.screenshot({ path: resolve(out, `LOCAL-SYNTHETIC-live-${width}.png`), fullPage: true });
      // An arbitrary URL connection cannot resolve an account or carry over the reviewed action.
      await page.goto(base + '/app/youtube?channel=foreign-connection');
      await page.getByRole('heading', { name: 'Connect your creator channel', exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).count(), 0);
      assert.deepEqual(errors, []);
      results.push({ width, execution: 'local-synthetic', realGoogleE2E: false, independentCapabilities: 37,
        productionNotReady: true, officialUnsupportedCommunity: true, publicGateHeld: true, humanReviewBeforeWrite: true,
        metadataPreserved: true, destructiveExactIdGuard: true, privateStreamKeyGuard: true, foreignConnectionRejected: true, noHorizontalOverflow: true });
      await context.close();
    }
    writeFileSync(resolve(out, 'LOCAL-SYNTHETIC-browser.json'), JSON.stringify({ status: 'PASS', execution: 'LOCAL SYNTHETIC; NOT REAL GOOGLE E2E', results }, null, 2) + '\n');
    console.log(JSON.stringify({ status: 'PASS', execution: 'LOCAL SYNTHETIC; NOT REAL GOOGLE E2E', results }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
