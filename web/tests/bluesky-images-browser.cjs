/** Real app/SQL UI; synthetic identity, OAuth and media. No real Bluesky acceptance. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
assert.equal(process.platform, 'linux');
assert.match(process.env.CI || '', /^(1|true)$/i);
const base = process.env.YOUTUBE_WEB_URL;
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = resolve(process.env.YOUTUBE_BROWSER_EVIDENCE_DIR);
mkdirSync(out, { recursive: true });
const results = [];
let page;
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 390]) {
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
      const start = await request('POST', `/api/workspaces/${wid}/channels/bluesky/oauth/start`, { capability: 'publish', input: { handle: 'synthetic.bsky.invalid' } });
      await request('POST', `/api/workspaces/${wid}/channels/bluesky/oauth/complete`, {
        state: new URL(start.authorizeUrl).searchParams.get('state'), code: 'synthetic-code', iss: 'https://oauth.synthetic.invalid'
      });
      const initial = await request('GET', `/api/workspaces/${wid}`);
      assert.equal(initial.state.phase2.assets.filter(a => a.mime === 'image/jpeg').length, 4);
      page = await context.newPage();
      page.setDefaultTimeout(20000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base + '/app/queue');
      const open = page.getByRole('button', { name: 'Schedule a draft', exact: true }).first();
      await open.waitFor();
      await page.waitForFunction(() => [...document.querySelectorAll('button')].some(el => el.textContent.includes('Schedule a draft') && Object.keys(el).some(k => k.startsWith('__reactProps'))));
      await open.click();
      const dialog = page.getByRole('dialog', { name: 'Schedule a draft', exact: true });
      await dialog.getByLabel('Draft', { exact: true }).click();
      await page.getByRole('option').filter({ hasText: 'Bluesky' }).first().click();
      const choose = async (label, number) => {
        await dialog.getByLabel(label, { exact: true }).click();
        const hash = initial.state.phase2.assets.filter(a => a.mime === 'image/jpeg')[number].hash.slice(0, 8);
        await page.getByRole('button', { name: new RegExp(`^Image .*, hash starts with ${hash}$`) }).click();
      };
      await choose('First image (optional)', 0);
      await dialog.getByLabel('Alt text', { exact: true }).fill('Synthetic red image');
      for (let index = 0; index < 3; index++) {
        await dialog.getByRole('button', { name: 'Add another image', exact: true }).click();
        await choose(`Image ${index + 2}`, index + 1);
        await dialog.getByLabel(`Alt text for image ${index + 2}`, { exact: true }).fill(`Synthetic image ${index + 2}`);
      }
      assert.equal(await dialog.getByRole('button', { name: 'Add another image', exact: true }).count(), 0);
      await dialog.getByRole('checkbox', { name: /^I have the rights to publish/ }).check();
      const prepare = dialog.getByRole('button', { name: 'Prepare review', exact: true });
      await dialog.getByLabel('Alt text for image 4', { exact: true }).fill('');
      assert.equal(await prepare.isDisabled(), true);
      await dialog.getByLabel('Alt text for image 4', { exact: true }).fill('Synthetic image 4');
      assert.equal(await prepare.isEnabled(), true);
      await page.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-images-${width}.png`), fullPage: true });
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/actions') && r.request().postDataJSON()?.action === 'p2_review'), prepare.click()
      ]);
      assert.ok(response.ok(), await response.text());
      await dialog.waitFor({ state: 'hidden' });
      const saved = await request('GET', `/api/workspaces/${wid}`);
      const review = saved.state.phase2.reviews.at(-1);
      assert.deepEqual(review.manifest.media.map(a => a.id), initial.state.phase2.assets.filter(a => a.mime === 'image/jpeg').map(a => a.id));
      assert.deepEqual(review.manifest.media.map(a => a.alt), ['Synthetic red image', 'Synthetic image 2', 'Synthetic image 3', 'Synthetic image 4']);
      assert.equal(saved.state.phase2.jobs.length, 0, 'Preparing a review cannot enqueue or publish.');
      await page.getByRole('list', { name: 'Bluesky image descriptions' }).getByText('Image 4: Synthetic image 4', { exact: true }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
      assert.deepEqual(errors, []);
      results.push({ width, fourImagesInOrder: true, individualAlts: true, missingAltBlocked: true, reviewSavedToPostgres: true, unapprovedJobs: 0 });
      await context.close();
    }
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-browser.json'), JSON.stringify({ status: 'pass', execution: 'cloud-synthetic-UI', realOAuth: false, realPublishing: false, productionAcceptance: false, results }, null, 2));
    process.stdout.write(JSON.stringify({ status: 'pass', execution: 'cloud-synthetic-UI', results }) + '\n');
  } catch (error) {
    if (page && !page.isClosed()) await page.screenshot({ path: resolve(out, 'CLOUD-SYNTHETIC-failure.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
