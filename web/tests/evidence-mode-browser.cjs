/* Real EvidenceDetails rendered by React; synthetic scoped records, native browser disclosure; no live account claim. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require('playwright');
const { makeEnvironment, render } = require('./agent-ui-journeys/_harness.cjs');
const fixture = require('./agent-ui-journeys/fixtures/J06-analytics.json');
const env = makeEnvironment();
const { MetricTable } = env.load('components/journeys/analytics');
const data = structuredClone(fixture.analytics_posts.partial);
data.data.workspaceId = 'workspace-a';
data.data.posts[0].metrics.views.evidence = {
  schema: 'rafii.evidence.v1', workspaceId: 'workspace-a', classification: 'observed', availability: 'available',
  source: { platform: 'Threads', provider: 'threads', entityType: 'provider_post', entityId: 'native-post', connectionId: 'account-a', document: null, href: 'https://example.com/evidence' },
  collectionPeriod: { start: null, end: '2026-10-08T02:00:00Z', basis: 'provider_reading' }, lastSuccessfulSync: '2026-10-08T02:00:03Z',
  definition: { name: 'views', version: '2026-09', description: 'Native provider views, not unique reach.', unit: 'count' }, uncertainty: ['Collection start is not recorded.'],
};
data.data.posts[0].metrics.likes = { value: null, availability: 'not_supported', evidence: { ...data.data.posts[0].metrics.views.evidence, availability: 'not_supported', lastSuccessfulSync: null } };
const html = render(env, MetricTable, { data, metrics: ['views', 'likes'] });
(async () => {
  let checks = 0;
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch({ headless: true });
    try {
      for (const width of [390, 1440]) {
        const page = await browser.newPage({ viewport: { width, height: 960 } });
        let egress = 0;
        await page.route('**/*', route => { egress++; return route.abort(); });
        await page.setContent(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Evidence Mode fixture</title></head><body><main><h1>Account readings</h1>${html}</main></body></html>`);
        const details = page.locator('[data-evidence-mode]');
        assert.equal(await details.count(), 2);
        await details.first().locator('summary').focus();
        await page.keyboard.press('Enter');
        assert.equal(await details.first().getAttribute('open'), '');
        await details.first().getByText('Last successful sync', { exact: true }).waitFor({ state: 'visible' });
        assert.match(await details.first().innerText(), /workspace-a/);
        await details.nth(1).locator('summary').click();
        assert.match(await details.nth(1).innerText(), /not_supported/);
        assert.match(await details.nth(1).innerText(), /Not recorded/);
        const link = details.first().locator('a');
        assert.equal(await link.getAttribute('rel'), 'noopener noreferrer nofollow');
        assert.equal(egress, 0);
        checks += 8;
        await page.close();
      }
    } finally { await browser.close(); }
  }
  console.log(JSON.stringify({ suite: 'evidence-mode-browser', checks, engines: ['chromium', 'webkit'], widths: [390, 1440], data: 'synthetic scoped records; real React render and native disclosure', status: 'passed' }));
})().catch(error => { console.error(error); process.exit(1); });
