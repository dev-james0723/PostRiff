/** Actual screens + disposable PG + deterministic AI fixtures. No external host, model or publishing. */
const { chromium, webkit } = require('playwright');
const engine = process.env.POSTRIFF_BROWSER_ENGINE || 'chromium';
const assertEngine = ['chromium','webkit'].includes(engine);
if (!assertEngine) throw new Error('Unsupported browser engine');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:3295';
assert.equal(new URL(base).hostname, '127.0.0.1');
const principal = randomUUID();
const root = path.resolve(__dirname, '../..');
const out = process.env.POSTRIFF_GROWTH_EVIDENCE_DIR || path.join(root, 'docs/design/growth-phase1/evidence');
fs.mkdirSync(out, { recursive: true });
const headers = {
  'Content-Type': 'application/json',
  'X-PostRiff-Request': 'founder-alpha',
  Authorization: 'Bearer dev:' + principal,
  Origin: base
};
async function api(method, url, body) {
  const response = await fetch(base + url, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  assert.ok(response.ok, `${url}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true });
}
async function mobile(page, selector) {
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    'No horizontal overflow'
  );
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(
    async (selector) =>
      (await window.axe.run(selector, { resultTypes: ['violations'] })).violations
        .filter((v) => ['serious', 'critical'].includes(v.impact))
        .map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    selector
  );
  assert.deepEqual(violations, []);
}
(async () => {
  assert.equal((await api('GET', '/api/auth/config')).execution, 'dev-synthetic');
  const { workspaceId: wid } = await api('POST', '/api/auth/verify', { plan: 'studio' });
  assert.equal(
    (await api('GET', `/api/workspaces/${wid}/growth/catalog`)).writer,
    'fixture/writer'
  );
  function fixture(kind) {
    return JSON.parse(
      execFileSync(
        process.env.POSTRIFF_TEST_PYTHON || 'python3',
        ['tests/phase2/growth_browser_fixture.py', kind, process.env.POSTRIFF_GROWTH_TEST_PG_PORT || '55795', principal, wid],
        { cwd: root, encoding: 'utf8' }
      ).trim()
    );
  }
  fixture('draft');
  const tours = Object.fromEntries(
    [
      ...fs
        .readFileSync(path.join(root, 'web/src/features/onboarding/tours.ts'), 'utf8')
        .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
    ].map((m) => [m[1], 1])
  );
  const browser = await ({chromium,webkit})[engine].launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
    reducedMotion: 'reduce'
  });
  await context.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort()
  );
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await context.addInitScript(
    ({ principal, wid, tours }) => {
      localStorage.setItem('postriff-dev-principal', principal);
      localStorage.setItem('postriff-workspace', wid);
      localStorage.setItem(
        'postriff-onboarding',
        JSON.stringify({ completed: {}, dismissed: tours, nudged: {} })
      );
    },
    { principal, wid, tours }
  );
  const page = await context.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('Browser error:', msg.text().slice(0, 800));
  });
  page.on('requestfailed', (request) =>
    console.log('Request failed:', new URL(request.url()).pathname, request.failure()?.errorText)
  );
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  const checks = [];
  try {
    await page.goto(base + '/app/queue?view=drafts', {
      waitUntil: 'domcontentloaded',
      timeout: 120000
    });
    console.log('Queue loaded');
    await page.getByRole('button', { name: 'Edit', exact: true }).first().click({ timeout: 60000 });
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('checkbox', { name: 'Allow growth AI models' }).check();
    await dialog.getByRole('button', { name: 'Allow growth AI', exact: true }).click();
    await dialog.getByRole('checkbox', { name: 'Allow AI analysis of this draft' }).check();
    await dialog.getByRole('button', { name: 'Check draft', exact: true }).click();
    await dialog.getByText('Helping:', { exact: false }).waitFor();
    console.log('Post Doctor checked');
    assert.equal(await dialog.locator('dl > div').count(), 9);
    await dialog.getByRole('button', { name: 'Rewrite and recheck', exact: true }).click();
    await dialog
      .getByRole('checkbox', { name: 'Use change 2', exact: true })
      .uncheck({ timeout: 60000 });
    await dialog.getByRole('button', { name: 'Use selected changes', exact: true }).click();
    await page.waitForFunction(
      () =>
        document.querySelector('[aria-label="Draft text"]')?.value ===
        'A clearer opening. Another idea!'
    );
    const snapshot = await api('GET', `/api/workspaces/${wid}`);
    assert.equal(snapshot.state.variants[0].text, 'A clearer opening. Another idea!');
    assert.equal(snapshot.state.variants[0].needsReview, true);
    assert.equal(snapshot.state.phase2.jobs.length, 0, 'Accepting advice never publishes');
    await mobile(page, '[role="dialog"]');
    await screenshot(page, 'composer-mobile');
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    checks.push('composer consent, nine levels, selected edits and publishing boundary');
    console.log('Composer accepted selected changes');

    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(base + '/app/workspace/brand', {
      waitUntil: 'domcontentloaded',
      timeout: 120000
    });
    const genome = page.getByLabel('Creator Genome', { exact: true });
    const csv =
      'text,platform,language,post_id\nMy first own teaching note.,Threads,en,g1\nMy second own teaching note.,Threads,en,g2\nMy third own teaching note.,Threads,en,g3\n';
    await genome
      .getByLabel('Owned history CSV')
      .setInputFiles({ name: 'history.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
    await genome.getByLabel('CSV account').fill('My owned fixture account');
    await genome
      .getByRole('checkbox', { name: 'Confirm owned history retention and analysis' })
      .check();
    await genome.getByRole('button', { name: 'Propose my Genome', exact: true }).click();
    await genome
      .getByRole('button', { name: 'Approve this Genome', exact: true })
      .waitFor({ timeout: 90000 });
    await genome.getByText('Review supporting posts and counterexamples').first().click();
    await genome.getByText('My first own teaching note.', { exact: true }).first().waitFor();
    const firstGenome = await genome.getByLabel('Genome version', { exact: true }).inputValue();
    await genome.getByRole('button', { name: 'Approve this Genome', exact: true }).click();
    await genome.getByText('Create a public Content DNA card', { exact: true }).click();
    await genome
      .getByRole('checkbox', { name: /^Share / })
      .first()
      .check();
    await genome
      .getByRole('button', { name: 'Create public link for selected labels', exact: true })
      .click();
    const link = genome.getByRole('link', { name: 'Open my Content DNA card' });
    await link.waitFor();
    const dna = await link.getAttribute('href');
    const shared = await context.newPage();
    await shared.goto(base + dna, { waitUntil: 'domcontentloaded' });
    await shared.getByText('Creator-selected writing labels.', { exact: false }).waitFor();
    assert.ok(!(await shared.locator('body').innerText()).includes('My first own teaching note.'));
    await screenshot(shared, 'content-dna');
    await shared.close();
    await mobile(page, '[aria-label="Creator Genome"]');
    await screenshot(page, 'genome-mobile');
    await genome
      .getByRole('button', { name: /^Revoke Content DNA card / })
      .first()
      .click();
    await genome
      .getByRole('button', { name: /^Revoke Content DNA card / })
      .waitFor({ state: 'hidden' });
    const revoked = await fetch(base + '/api/content-dna/' + dna.split('/').at(-1));
    assert.equal(revoked.status, 404);
    const priorGenome = fixture('genome-prior');
    assert.equal(priorGenome.execution, 'explicitly synthetic prior version in disposable Phase 1 database');
    assert.notEqual(priorGenome.genomeId, firstGenome);
    await page.reload({waitUntil:'domcontentloaded'});
    await genome.getByLabel('Genome version', { exact: true }).selectOption(priorGenome.genomeId);
    await genome.getByRole('button', { name: 'Restore this approved version', exact: true }).click();
    await genome.getByRole('button', { name: 'Restore this approved version', exact: true }).waitFor({state:'hidden'});
    const restored = await api('GET', `/api/workspaces/${wid}/growth/genome`);
    assert.equal(restored.active.id, priorGenome.genomeId);
    checks.push('Genome corpus, evidence, approve, select and restore prior version, public label preview and revoke');

    // Recheck the accepted revision so the verified fixture captures its exact advice.
    let current = await api('GET', `/api/workspaces/${wid}`);
    const variant = current.state.variants[0];
    await api('POST', `/api/workspaces/${wid}/growth/check`, {
      variantId: variant.id,
      variantRevision: variant.revision,
      confirmed: true,
      requestKey: randomUUID()
    });
    const { jobId } = fixture('feedback');
    const feedback = await api('GET', `/api/workspaces/${wid}/growth/feedback/${jobId}`);
    assert.equal(feedback.prediction.contentRevision, variant.revision);
    assert.equal(feedback.readings.find((r) => r.horizon === '24h').metrics.likes.multiple, 3);
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(base + '/app/analytics', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page
      .getByRole('row')
      .filter({ has: page.getByText('30', { exact: true }) })
      .first()
      .click({ timeout: 60000 });
    const observed = page.getByLabel('Observed performance feedback', { exact: true });
    await observed.getByText('24h reading', { exact: true }).waitFor();
    await mobile(page, '[aria-label="Observed performance feedback"]');
    await screenshot(page, 'feedback-mobile');
    checks.push('exact publication revision and native observed feedback screen');

    await page.goto(base + '/post-doctor', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page
      .getByRole('textbox', { name: 'Your draft', exact: true })
      .fill('My own short draft, with one useful point.');
    await page.getByRole('checkbox', { name: 'Allow analysis of my public draft' }).check();
    await page.getByRole('button', { name: 'Check my draft', exact: true }).click();
    await page.getByText('Confidence:', { exact: false }).waitFor();
    await mobile(page, 'main');
    await screenshot(page, 'public-mobile');
    checks.push('public checks, qualitative feedback, mobile layout and accessibility');
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(out, 'browser.json'),
      JSON.stringify(
        {
          status: 'PASS',
          engine,
          execution: 'actual UI + disposable PostgreSQL + deterministic model/provider fixtures',
          checks,
          realModelCalls: 0,
          livePosts: 0
        },
        null,
        2
      ) + '\n'
    );
    console.log(
      JSON.stringify({ status: 'PASS', checks, evidence: out, realModelCalls: 0, livePosts: 0 })
    );
  } finally {
    await screenshot(page, 'last-state').catch(() => {});
    await browser.close();
  }
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
