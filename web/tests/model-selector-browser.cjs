// Requires the isolated synthetic-catalog page at /model-selector-check.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const results = [];
  try {
    for (const width of [1440, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto('http://localhost:4448/model-selector-check');
      const trigger = page.getByLabel('Model', { exact: true });
      await trigger.focus();
      await page.keyboard.press('Enter');
      const search = page.getByRole('combobox', { name: 'Search models and providers' });
      await search.waitFor();
      assert.equal(await page.getByRole('option').count(), 8);
      assert.equal(
        await page
          .getByRole('option')
          .filter({ hasText: 'Gemini CLI' })
          .getAttribute('aria-disabled'),
        'true'
      );
      assert.equal(await page.getByRole('option').locator('svg').count(), 9);
      await search.fill('OpenAI');
      assert.equal(await page.getByRole('option').count(), 1);
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Enter');
      await search.waitFor({ state: 'hidden' });
      assert.equal(await page.getByLabel('Selected model').textContent(), 'codex:default');
      await page.reload();
      assert.equal(await page.getByLabel('Selected model').textContent(), 'codex:default');
      await trigger.click();
      await search.fill('no-such-model');
      await page.getByText('No models found. Try another provider or model.').waitFor();
      await search.fill('Anthropic');
      assert.equal(await page.getByRole('option').count(), 5);
      await page.getByRole('option').filter({ hasText: 'Claude Code · sonnet' }).click();
      await trigger.click();
      await page.getByLabel('Reasoning effort').selectOption('high');
      assert.equal(await page.getByLabel('Selected effort').textContent(), 'high');
      await page.screenshot({
        path: path.resolve(__dirname, `../../docs/model-selector/selector-${width}.png`),
        fullPage: true
      });
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        true
      );
      const popup = page.getByRole('dialog', { name: 'Select model and provider' });
      // Base UI gives this popup a dialog role when it contains its search input.
      const box = await popup.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
      const violations = await page.evaluate(async () =>
        (
          await axe.run(document, {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] }
          })
        ).violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))
      );
      assert.deepEqual(violations, []);
      await page.keyboard.press('Escape');
      await search.waitFor({ state: 'hidden' });
      assert.equal(await trigger.evaluate((el) => el === document.activeElement), true);
      assert.deepEqual(errors, []);
      results.push({
        width,
        search: true,
        keyboard: true,
        persistence: true,
        reasoning: true,
        disabledProvider: true,
        icons: true,
        noOverflow: true,
        axeViolations: 0
      });
      await context.close();
    }
    require('node:fs').writeFileSync(
      path.resolve(__dirname, '../../docs/model-selector/browser-results.json'),
      JSON.stringify(
        { execution: 'Local UI with synthetic catalog; no provider requests', results },
        null,
        2
      )
    );
    console.log(JSON.stringify(results));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
