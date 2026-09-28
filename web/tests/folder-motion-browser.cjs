/** Real FolderEditor, local synthetic accounts; no API/provider calls or persisted workspace edits. */
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.RAFII_FOLDER_URL || 'http://127.0.0.1:3467';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local preview only');
const out = path.resolve(__dirname, '../../docs/design/folder-motion/evidence');
fs.mkdirSync(out, { recursive: true });
const report = { execution: 'Real editor in local synthetic-account preview; no backend or provider calls', scenarios: [] };
const scenarios = [
  { name: 'desktop-dark', width: 1100, height: 980, theme: 'dark', record: true },
  { name: 'desktop-light', width: 1100, height: 900, theme: 'light' },
  { name: 'mobile-light', width: 390, height: 844, theme: 'light' },
  { name: 'small-mobile', width: 320, height: 640, theme: 'dark' },
  { name: 'system-reduced', width: 390, height: 844, theme: 'light', reduced: true },
  { name: 'app-reduced', width: 1100, height: 900, theme: 'dark', appReduced: true },
  { name: 'safari-mobile', width: 390, height: 844, theme: 'dark', engine: 'webkit' }
];
(async () => {
  for (const scenario of scenarios) {
    const browser = await (scenario.engine === 'webkit' ? webkit : chromium).launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: scenario.width, height: scenario.height }, colorScheme: scenario.theme, reducedMotion: scenario.reduced ? 'reduce' : 'no-preference', ...(scenario.record ? { recordVideo: { dir: out, size: { width: scenario.width, height: scenario.height } } } : {}) });
    const errors = [];
    const apiRequests = [];
    try {
      await context.addCookies([{ name: 'postriff_theme', value: 'rafii', url: base }]);
      await context.addInitScript(({ theme, appReduced }) => {
        localStorage.setItem('theme', theme);
        if (appReduced) localStorage.setItem('rafii.motion', 'reduced');
      }, scenario);
      await context.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== new URL(base).origin) return route.abort();
        if (url.pathname.startsWith('/api/')) { apiRequests.push(url.pathname); return route.abort(); }
        return route.continue();
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`${base}/dev/folder-motion`);
      await page.getByRole('button', { name: 'New folder', exact: true }).click();
      const preview = page.locator('[data-folder-preview]');
      const reduced = Boolean(scenario.reduced || scenario.appReduced);
      await preview.waitFor();
      const opening = await preview.evaluate(el => el.getAnimations({ subtree: true }).filter(a => a.playState === 'running').length);
      assert.equal(opening > 0, !reduced, 'Opening respects motion preference');
      await page.getByRole('textbox', { name: 'Folder name' }).fill('Studio favourites');
      assert.equal(await page.getByRole('button', { name: 'Save folder', exact: true }).isEnabled(), false);
      const member = id => page.locator(`[data-folder-member="${id}"]`);
      const toggle = id => member(id).locator('..').click();
      await toggle('instagram');
      assert.equal(await member('instagram').isChecked(), true);
      const flight = preview.locator('[data-folder-flight="instagram"]');
      assert.equal(await flight.count(), 1);
      assert.equal(await page.getByText('1 account inside', { exact: true }).count(), 1);
      if (reduced) {
        assert.equal(await preview.evaluate(el => el.getAnimations({ subtree: true }).filter(a => a.playState === 'running').length), 0);
        assert.equal(await flight.isVisible(), false);
      } else {
        // Capture the animation itself at explicit times, including occlusion/receipt.
        const frames = [];
        for (const t of [180, 490, 800, 1250]) {
          await preview.evaluate((el, time) => el.getAnimations({ subtree: true }).forEach(a => { a.pause(); a.currentTime = time; }), t);
          const frame = await flight.evaluate(el => ({ transform: getComputedStyle(el).transform, opacity: getComputedStyle(el).opacity }));
          frames.push(frame);
          if (scenario.record) await preview.screenshot({ path: path.join(out, `drop-${t}ms.png`) });
        }
        assert.notEqual(frames[0].transform, frames[1].transform, 'Logo travels, not just crossfades');
        assert.equal(frames[3].opacity, '0', 'Logo is filed after falling behind front leaf');
        await preview.evaluate(el => el.getAnimations({ subtree: true }).forEach(a => a.play()));
      }
      // Scroll to select a later account: folder must remain visible and stationary.
      await page.getByRole('dialog').evaluate(el => Promise.all(el.getAnimations().map(a => a.finished.catch(() => {}))));
      const before = await preview.boundingBox();
      await toggle('facebook');
      const after = await preview.boundingBox();
      assert.ok(Math.abs(before.y - after.y) < 1, 'Preview stays visible during account scrolling');
      assert.ok(after.y >= 0 && after.y + after.height <= scenario.height);
      // Keyboard selection plus rapid independent additions, including a fourth logo.
      await member('threads').focus();
      await page.keyboard.press('Space');
      await toggle('linkedin');
      assert.equal(await preview.locator('[data-folder-logo]').count(), 4);
      assert.equal(await preview.locator('[data-folder-flight="linkedin"]').count(), 1, 'Fourth logo still flies');
      assert.equal(await preview.getByText('+1', { exact: true }).count(), 1);
      await toggle('instagram');
      assert.equal(await preview.locator('[data-folder-logo="instagram"]').count(), 0, 'Removal cancels logo immediately');
      await toggle('instagram');
      if (!reduced) assert.ok(await preview.locator('[data-folder-flight="instagram"]').evaluate(el => el.getAnimations().some(a => a.playState === 'running')), 'Re-add replays flight');
      await page.waitForTimeout(reduced ? 50 : 1500);
      assert.equal(await preview.evaluate(el => el.getAnimations({ subtree: true }).filter(a => a.playState === 'running').length), 0, 'No endless decorative loops');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(out, `${scenario.name}.png`) });
      // Actual editor save validation and submitted membership are exercised in this local harness.
      await page.getByRole('button', { name: 'Save folder', exact: true }).click();
      await page.getByText('Preview saved: Studio favourites · 4 accounts (local only)', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Edit saved preview' }).click();
      assert.equal(await preview.locator('[data-folder-flight]').count(), 0, 'Existing members do not drop on edit');
      await toggle('facebook');
      await toggle('facebook');
      assert.equal(await preview.locator('[data-folder-flight="facebook"]').count(), 1, 'Re-added existing member animates');
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      await page.getByRole('button', { name: 'New folder', exact: true }).click();
      assert.equal(await preview.locator('[data-folder-logo]').count(), 0, 'New dialog resets membership');
      if (!reduced) assert.ok(await preview.evaluate(el => el.getAnimations({ subtree: true }).some(a => a.playState === 'running')), 'Reopening replays intro');
      await page.waitForTimeout(1200);
      await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
      const violations = await page.evaluate(async () => (await axe.run(document.querySelector('[role="dialog"]'), { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations.map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) })));
      assert.deepEqual(violations, []);
      await page.keyboard.press('Escape');
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      assert.deepEqual(errors, []);
      assert.deepEqual(apiRequests, []);
      report.scenarios.push({ ...scenario, passed: true, opening, keyboard: true, rapidAddition: true, reAddition: true, fourthLogo: true, stationaryPreview: true, save: true, reopen: true, axeViolations: 0, apiRequests: 0 });
      console.log(`PASS ${scenario.name}`);
      const video = page.video();
      await context.close();
      if (video) await video.saveAs(path.join(out, 'interaction-check.webm'));
    } finally { await browser.close(); }
  }
  fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify(report, null, 2));
})().catch(error => { fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify({ ...report, failure: String(error) }, null, 2)); console.error(error); process.exitCode = 1; });
