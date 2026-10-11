/** Cloud Next -> hosted Python -> SQL. Synthetic Mastodon only; no live acceptance. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
assert.equal(process.platform, 'linux');
assert.match(process.env.CI || '', /^(1|true)$/i);
const base = process.env.MASTODON_WEB_URL || 'http://127.0.0.1:4448';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = resolve(process.env.MASTODON_BROWSER_EVIDENCE_DIR || resolve(__dirname, '../../.jcb-artifacts/mastodon-browser'));
mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const checks = [];
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
      const connections = [];
      for (const instance of ['mastodon.social', 'mastodon.online']) {
        const started = await request('POST', `/api/workspaces/${wid}/channels/mastodon/oauth/start`, { capability: 'management', input: { instance } });
        const connected = await request('POST', `/api/workspaces/${wid}/channels/mastodon/oauth/complete`, {
          state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'synthetic-code'
        });
        assert.match(connected.providerAccountId, new RegExp('@' + instance.replace('.', '\\.') + '$'));
        connections.push(connected.connectionId);
      }
      assert.notEqual(connections[0], connections[1]);
      const page = await context.newPage();
      page.setDefaultTimeout(30000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base + '/app/channels');
      await page.getByText('Mastodon account controls', { exact: true }).first().waitFor();
      const controls = page.locator('details').filter({ has: page.getByText('Mastodon account controls', { exact: true }) }).first();
      await controls.locator('summary').click();
      await controls.getByRole('button', { name: 'analytics', exact: true }).click();
      await controls.getByText('followers:', { exact: true }).waitFor();
      assert.equal((await controls.textContent()).includes('PRIVATE_FIXTURE_EXCLUDED_FROM_ANALYTICS'), false);
      await controls.getByLabel('Post, account, list or schedule ID', { exact: true }).fill('123');
      await controls.getByRole('button', { name: 'Review action', exact: true }).click();
      await controls.getByRole('button', { name: 'Approve exact action', exact: true }).waitFor();
      assert.match(await controls.textContent(), /Target ID: 123/);
      await controls.getByRole('button', { name: 'Approve exact action', exact: true }).click();
      await controls.getByRole('status').filter({ hasText: 'accepted' }).waitFor();
      await controls.getByLabel('Mastodon account action', { exact: true }).click();
      await page.getByRole('option', { name: 'Edit profile', exact: true }).click();
      await controls.getByRole('checkbox', { name: 'Change display name', exact: true }).check();
      await controls.getByLabel('Display name', { exact: true }).fill('SYNTHETIC profile');
      await controls.getByLabel('Default post visibility', { exact: true }).click();
      await page.getByRole('option', { name: 'Followers-only', exact: true }).click();
      await controls.getByRole('button', { name: 'Review action', exact: true }).click();
      await controls.getByRole('button', { name: 'Approve exact action', exact: true }).waitFor();
      assert.match(await controls.textContent(), /SYNTHETIC profile/);
      assert.match(await controls.textContent(), /privacy: private/);
      assert.equal((await controls.textContent()).includes('note:'), false);
      await controls.getByRole('button', { name: 'Approve exact action', exact: true }).click();
      await controls.getByRole('status').filter({ hasText: 'accepted' }).waitFor();
      const proposal = await request('POST', `/api/workspaces/${wid}/channels/${connections[0]}/mastodon/actions`, { action: 'favourite', targetId: '123' });
      await page.goto(base + '/app/channels?mastodonAction=' + proposal.actionId + '&connection=' + connections[0]);
      const prepared = page.locator('details').filter({ has: page.getByText('Mastodon account controls', { exact: true }) });
      await prepared.getByRole('button', { name: 'Approve exact action', exact: true }).waitFor();
      await page.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-channels-${width}.png`), fullPage: false });
      assert.deepEqual(errors, []);
      const overflow = await page.evaluate(() => ({ width: innerWidth, documentWidth: document.documentElement.scrollWidth, elements: [...document.querySelectorAll('body *')].filter((node) => node.getBoundingClientRect().right > innerWidth + 2).sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right).slice(0, 20).map((node) => ({ tag: node.tagName, text: node.textContent.slice(0, 40), className: String(node.className), right: node.getBoundingClientRect().right, width: node.getBoundingClientRect().width, position: getComputedStyle(node).position, parent: String(node.parentElement?.className), parentOverflow: getComputedStyle(node.parentElement).overflowX })) }));
      assert.ok(overflow.documentWidth <= width + 2, JSON.stringify(overflow));
      checks.push({ width, checks: ['two synthetic instance-qualified OAuth accounts', 'bounded native analytics excludes private content', 'exact action preview and receipt', 'Agent preview link hydration', 'selected profile fields and default privacy exact approval', 'no runtime errors or page overflow'] });
      await context.close();
    }
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-browser.json'), JSON.stringify({ status: 'PASS', realMastodonAcceptance: false, productionAcceptance: false, checks }, null, 2));
    console.log(JSON.stringify({ status: 'PASS', execution: 'CLOUD SYNTHETIC APPLICATION BROWSER', realMastodonAcceptance: false, checks }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
