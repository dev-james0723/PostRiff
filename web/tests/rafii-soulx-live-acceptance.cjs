/** Manual, REAL GPT Live + SoulX acceptance sampler. It never starts a call or sends audio itself. */
const fs = require('node:fs');
const { chromium, webkit } = require('playwright');

const browserName = process.env.RAFII_ACCEPTANCE_BROWSER || 'chromium';
const url = process.env.RAFII_ACCEPTANCE_URL || 'http://localhost:3000/app';
const output = process.env.RAFII_ACCEPTANCE_OUTPUT;
if (!output) throw new Error('Set RAFII_ACCEPTANCE_OUTPUT to a private JSON path outside the repository.');
const engine = { chromium, webkit }[browserName];
if (!engine) throw new Error('RAFII_ACCEPTANCE_BROWSER must be chromium or webkit.');

(async () => {
  const browser = await engine.launch({ headless: false });
  try {
    const options = { permissions: ['microphone'] };
    if (process.env.RAFII_ACCEPTANCE_STORAGE_STATE) options.storageState = process.env.RAFII_ACCEPTANCE_STORAGE_STATE;
    const context = await browser.newContext(options);
    const page = await context.newPage();
    await page.goto(url);
    console.log('Sign in if needed, start a real Rafii GPT Live call, then speak. The sampler starts at the first SoulX frame.');
    await page.waitForFunction(() => Boolean(document.querySelector('[data-rafii-soulx-metrics] img')), undefined, { timeout: 600_000 });
    const startedAt = new Date().toISOString();
    const samples = [];
    const start = performance.now();
    let runError = null;
    try {
      while (performance.now() - start < 300_000) {
        const sample = await page.evaluate(() => {
          const layer = document.querySelector('[data-rafii-soulx-metrics]');
          return layer ? { at: performance.now(), status: layer.getAttribute('data-rafii-soulx'),
            frameVisible: Boolean(layer.querySelector('img')),
            metrics: JSON.parse(layer.getAttribute('data-rafii-soulx-metrics')) } : null;
        });
        samples.push(sample);
        await page.waitForTimeout(1000);
      }
    } catch (error) { runError = error; }
    fs.writeFileSync(output, JSON.stringify({ kind: 'real-run-samples', browser: browserName, startedAt,
      endedAt: new Date().toISOString(), elapsedMs: performance.now() - start,
      completeFiveMinutes: !runError && performance.now() - start >= 300_000, samples }, null, 2));
    if (runError) throw runError;
    console.log(`Saved ${samples.length} one-second samples to ${output}. Inspect video, lip sync, and speaker audio directly before marking PASS.`);
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
