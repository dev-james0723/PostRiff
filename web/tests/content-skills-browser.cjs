/**
 * Content Skills Integration A32 (cloud only): Next production build -> hosted Python -> disposable PostgreSQL, with the
 * Facebook creation wave on and GenUI left at its default (off). Proves the standard typed composer offers the facet's
 * platforms and native formats at 1440 and 390 px, by pointer and keyboard, without horizontal scroll, then drafts with
 * the no-cost Templates writer and checks the review facts beside each draft (A29: format, writing guide, media, publish
 * readiness, disconnected account). axe and the accessibility tree are automated checks, not a screen-reader audit.
 * Synthetic identities only; nothing is published.
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
const settingButton = (page, kicker) => page.locator('button[aria-haspopup="dialog"]').filter({ hasText: kicker });

/** The no-cost Templates writer (fixture route): no model, no spend. Writers outside the featured list sit behind "More models". */
async function useTemplatesWriter(page) {
  await settingButton(page, 'Model').click();
  const dialog = page.getByRole('dialog');
  await dialog.waitFor();
  const row = dialog.getByRole('radio', { name: /Templates \(no AI model\)/ }).first();
  if (!(await row.isVisible().catch(() => false))) {
    const more = dialog.getByRole('button', { name: /More models/ });
    if ((await more.count()) && (await more.getAttribute('aria-expanded')) !== 'true') await more.click();
  }
  await row.click();
  await dialog.getByRole('button', { name: /Use this model/ }).click();
  await dialog.waitFor({ state: 'hidden' });
}

/** Serious or critical axe findings inside one region (automated; not a screen-reader audit). */
async function axe(page, selector) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async (scope) => {
    const result = await window.axe.run(scope, { resultTypes: ['violations'] });
    return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes[0]?.target }));
  }, selector);
}

/** The facts the review shows for the active draft, as {label: value}. */
async function factsOf(page) {
  const facts = page.locator('section[aria-label="Generated drafts"] [data-native-facts]');
  await facts.waitFor();
  return facts.evaluate((dl) => Object.fromEntries([...dl.querySelectorAll('dt')].map((dt) => [dt.textContent.trim(), dt.nextElementSibling?.textContent.trim() ?? ''])));
}

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
      const { workspaceId } = await request('POST', '/api/auth/verify', { plan: 'studio' });
      assert.ok(workspaceId, 'synthetic workspace created');
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

      // A29 review: draft with the no-cost Templates writer, then read what the review says beside each draft.
      await useTemplatesWriter(page);
      await page.getByRole('textbox', { name: 'Message' }).fill('SYNTHETIC: slow practice at the piano is where a good performance is decided.');
      const generate = page.getByRole('button', { name: /^Generate drafts/ });
      assert.ok(await generate.isEnabled(), 'Generate is enabled with the Templates writer');
      await generate.click();
      const drafts = page.getByRole('region', { name: 'Generated drafts' });
      await drafts.waitFor({ timeout: 60000 });
      await page.waitForFunction(() => /ready · yours to edit/.test(document.querySelector('section[aria-label="Generated drafts"] [role="status"]')?.textContent ?? ''), null, { timeout: 120000 });
      const dock = page.getByRole('group', { name: 'Choose a draft' });
      const pick = async (platform) => {
        await dock.getByRole('button', { name: new RegExp('^' + platform) }).first().click();
        await page.waitForTimeout(400);
        return factsOf(page);
      };
      const review = {};
      review.instagram = await pick('Instagram');
      assert.equal(review.instagram.Format, 'Carousel');
      assert.equal(review.instagram.Publishing, 'Export only · Rafii can’t publish this format yet');
      assert.equal(review.instagram.Media, 'Needs an image');
      assert.match(review.instagram.Account, /No Instagram account connected/);
      assert.ok(review.instagram['Writing guide'], 'the writing-guide route is shown');
      review.facebook = await pick('Facebook');
      assert.equal(review.facebook.Format, 'Reel');
      assert.match(review.facebook.Media, /Rafii wrote the script, not a video/);
      assert.equal(review.facebook.Publishing, 'Export only · Rafii can’t publish this format yet');
      assert.match(review.facebook.Account, /No Facebook account connected · draft, copy and export only/);
      review.linkedin = await pick('LinkedIn');
      assert.equal(review.linkedin.Format, 'Post');
      assert.equal(review.linkedin.Publishing, 'Connect LinkedIn to publish');
      assert.ok(!review.linkedin.Media, 'an optional-media post claims no media need');
      // Accessible names: the facts are a description list read as term/definition pairs.
      const tree = await drafts.locator('[data-native-facts]').ariaSnapshot();
      assert.match(tree, /term: Publishing/);
      assert.match(tree, /definition: Connect LinkedIn to publish/);
      // Keyboard: the caption editor is reachable by Tab from the draft chooser.
      await dock.getByRole('button').first().focus();
      let editorReached = false;
      for (let i = 0; i < 40 && !editorReached; i += 1) {
        await page.keyboard.press('Tab');
        editorReached = await page.evaluate(() => document.activeElement?.id === 'rafii-draft-editor');
      }
      assert.ok(editorReached, 'caption editor reachable by keyboard from the draft chooser');
      const axeReview = await axe(page, 'section[aria-label="Generated drafts"]');
      assert.deepEqual(axeReview, [], 'axe: no serious or critical issue in the review region');
      const reviewOverflow = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
      assert.ok(reviewOverflow <= 0, `review: no horizontal scroll at ${width}px (overflow ${reviewOverflow})`);
      // Drafting scheduled, reviewed or published nothing (A29: no public post as a side effect).
      const snapshot = await request('GET', '/api/workspaces/' + encodeURIComponent(workspaceId));
      const sideEffects = { jobs: (snapshot.state?.phase2?.jobs ?? []).length, reviews: (snapshot.state?.phase2?.reviews ?? []).length };
      assert.deepEqual(sideEffects, { jobs: 0, reviews: 0 }, 'drafting created no review or publish job');
      assert.deepEqual(errors, []);
      await drafts.scrollIntoViewIfNeeded();
      const reviewShot = resolve(out, `CLOUD-SYNTHETIC-review-${width}.png`);
      await page.screenshot({ path: reviewShot, fullPage: false });
      results.push({ width, draftable: catalog.creation.draftable, revision: catalog.creation.revision, waves: catalog.creation.rollout.waves,
        instagramFormats: 4, facebookFormats: 3, keyboard: reached, overflow, screenshot: shot,
        review: { facts: review, keyboardEditor: editorReached, axeSeriousOrCritical: axeReview.length, overflow: reviewOverflow, sideEffects, screenshot: reviewShot } });
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
