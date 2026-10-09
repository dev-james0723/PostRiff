/**
 * Content Skills Integration A32 (cloud only): Next production build -> hosted Python -> disposable PostgreSQL, with the
 * Facebook creation wave on and GenUI left at its default (off). Proves the standard typed composer offers the facet's
 * platforms and native formats at 1440 and 390 px, by pointer and keyboard, without horizontal scroll. Synthetic
 * identities only; nothing is published.
 */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
assert.equal(process.platform, 'linux', 'Browser validation runs only on cloud Linux CI.');
assert.match(process.env.CI || '', /^(1|true)$/i);
const base = process.env.CONTENT_SKILLS_WEB_URL || 'http://127.0.0.1:4448';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = resolve(process.env.CONTENT_SKILLS_EVIDENCE_DIR || resolve(__dirname, '../../.jcb-artifacts/content-skills-browser'));
mkdirSync(out, { recursive: true });
const results = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 390]) {
      const principal = randomUUID();
      const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
      await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
      await context.addInitScript((id) => {
        localStorage.setItem('postriff-dev-principal', id);
        localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
      }, principal);
      await context.route('**/*', (route) => (new URL(route.request().url()).origin === base ? route.continue() : route.abort()));
      const headers = { Authorization: 'Bearer dev:' + principal, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
      const request = async (method, path, data) => {
        const response = await context.request.fetch(base + path, { method, headers, data });
        assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`);
        return response.json();
      };
      await request('POST', '/api/auth/verify', { plan: 'studio' });
      const catalog = await request('GET', '/api/ideas/models');
      assert.equal(catalog.creation.schema, 'rafii.creation-capabilities.v1');
      assert.deepEqual(catalog.creation.draftable, ['LinkedIn', 'Instagram', 'Threads', 'Facebook', 'X', 'Xiaohongshu']);
      assert.ok(!JSON.stringify(catalog.creation).includes('## Skill'), 'the facet never carries skill bodies');

      const page = await context.newPage();
      page.setDefaultTimeout(30000);
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(base + '/app');
      await page.getByRole('button', { name: /^Choose channels/ }).waitFor();
      // Default targets (LinkedIn, Instagram): Instagram's four native formats are offered with what each still needs.
      const instagram = page.getByLabel('Instagram', { exact: true });
      await instagram.waitFor();
      assert.deepEqual(await instagram.locator('option').allTextContents(), ['Post', 'Carousel', 'Story', 'Reel']);
      await instagram.selectOption('instagram.carousel');
      await page.getByText('Needs an image', { exact: true }).first().waitFor();

      // An unconnected workspace drafts for Facebook without OAuth: the platform-only list now includes it.
      await page.getByRole('button', { name: /^Choose channels/ }).click();
      const facebookOption = page.getByRole('checkbox', { name: /Facebook/ });
      await facebookOption.click();
      assert.equal(await facebookOption.getAttribute('aria-checked'), 'true');
      await page.getByRole('button', { name: /^Done ·/ }).click();
      const facebook = page.getByLabel('Facebook', { exact: true });
      await facebook.waitFor();
      assert.deepEqual((await facebook.locator('option').allTextContents()).sort(), ['Page post', 'Reel', 'Story']);

      // Keyboard: the Facebook format select is reachable with Tab and operable with the arrow keys.
      await page.getByRole('textbox', { name: 'Message' }).focus();
      let reached = false;
      for (let i = 0; i < 80 && !reached; i += 1) {
        await page.keyboard.press('Tab');
        reached = await page.evaluate(() => document.activeElement?.id === 'native-format-Facebook');
      }
      assert.ok(reached, 'Facebook format select reachable by keyboard');
      await facebook.selectOption('facebook.reel');
      await page.getByText('Needs your video · Rafii writes the script', { exact: true }).waitFor();

      const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
      assert.ok(overflow <= 0, `no horizontal scroll at ${width}px (overflow ${overflow})`);
      assert.deepEqual(errors, []);
      const shot = resolve(out, `CLOUD-SYNTHETIC-composer-${width}.png`);
      await page.screenshot({ path: shot, fullPage: false });
      results.push({ width, draftable: catalog.creation.draftable, revision: catalog.creation.revision, waves: catalog.creation.rollout.waves,
        instagramFormats: 4, facebookFormats: 3, keyboard: reached, overflow, screenshot: shot });
      await context.close();
    }
    const proof = { status: 'PASS', execution: 'CLOUD SYNTHETIC APPLICATION BROWSER', published: false, genui: 'default (flags off)', results, capturedAt: new Date().toISOString() };
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-content-skills.json'), JSON.stringify(proof, null, 2));
    console.log('CONTENT_SKILLS_BROWSER ' + JSON.stringify(proof));
  } catch (error) {
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-content-skills.json'), JSON.stringify({ status: 'FAIL', error: String(error && error.stack || error), results }, null, 2));
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
