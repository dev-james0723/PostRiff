/** Local production build with synthetic API: Raffi composer, campaign and suggestion UI. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require('/Users/ouxianxing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/wp04a-workspace.json', import.meta.url), 'utf8'));
const base = process.env.RAFFI_WEB_URL || 'http://127.0.0.1:4439';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = new URL('../../docs/raffi-six-core-features/evidence/browser/', import.meta.url); mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
try {
  for (const width of [1024, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
    await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }]);
    await context.addInitScript(() => { localStorage.setItem('postriff-dev-principal', '00000000-0000-0000-0000-000000000001'); localStorage.setItem('postriff-onboarding:00000000-0000-0000-0000-000000000001', JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} })); });
    const snapshot = structuredClone(fixture.snapshot);
    snapshot.state.sources.push({ id: 'voice-browser', kind: 'voice_sample', title: 'Selected sample', text: 'Short opening. ✨', active: true, selected: true, revision: 1, contentHash: 'a'.repeat(64), visibility: 'workspace-private', useGrants: [{ purpose: 'generation', route: 'local-cli' }] });
    snapshot.state.raffi = { campaignPlanning: { campaigns: [], recurringTasks: [], occurrences: [] }, suggestions: [] };
    const wid = snapshot.state.workspace.id;
    const page = await context.newPage(); page.setDefaultTimeout(20_000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) return route.abort();
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
      const path = url.pathname;
      if (route.request().method() === 'POST' && path === `/api/workspaces/${wid}/actions`) {
        const body = route.request().postDataJSON(); snapshot.revision += 1;
        if (body.action === 'raffi_campaign_create') snapshot.state.raffi.campaignPlanning.campaigns.push({ id: 'campaign-browser', version: 1, goal: body.payload.goal, audience: body.payload.audience, facts: body.payload.facts, status: 'draft', missingFacts: [], items: [] });
        if (body.action === 'raffi_suggestion_refresh') snapshot.state.raffi.suggestions.push({ id: 'suggestion-browser', kind: 'campaign_gap', reason: 'This campaign has confirmed facts but no draft items yet.', status: 'open', evidence: [{ type: 'campaign', id: 'campaign-browser', revision: 1 }], action: 'campaign', actionRef: null });
        return send(snapshot);
      }
      if (route.request().method() !== 'GET') return send({ error: 'Unexpected mutation' }, 400);
      if (path === '/api/catalog') return send({ authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {} });
      if (path === '/api/workspaces') return send({ workspaces: [{ workspaceId: wid, membership: snapshot.membership, name: 'Raffi browser fixture', plan: 'studio', memberCounts: { owner: 1 } }] });
      if (path === '/api/me') return send({ userId: '00000000-0000-0000-0000-000000000001', displayName: 'Raffi fixture', preferences: { timeZone: 'America/New_York', locale: 'en', alertNewDevice: false }, mfa: {} });
      if (path === `/api/workspaces/${wid}`) return send(snapshot);
      if (path.endsWith('/channels')) return send({ channels: [], providers: [] });
      if (path.endsWith('/usage')) return send({ subscription: { plan: 'studio', status: 'active' }, trial: {}, balances: [] });
      if (path.endsWith('/memory')) return send(fixture.memory);
      if (path.endsWith('/memory/proposals')) return send({ pending: [], recent: [], learning: { items: [] } });
      if (path.endsWith('/ideas/conversations')) return send({ conversations: [] });
      if (path === '/api/ideas/models') return send({ models: [{ id: 'deterministic-preview', label: 'Deterministic preview', qualified: true, costClass: 'none', detail: 'Local fixture', reasoning: [{ id: 'quick', available: true, detail: 'Local fixture' }] }], reasoning: [{ id: 'quick', available: true, detail: 'Local fixture' }], agents: [] });
      return send({ error: `Unhandled ${path}` }, 404);
    });
    await page.goto(`${base}/app`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Neutral voice' }).waitFor();
    await page.getByRole('button', { name: 'Neutral voice' }).click();
    await page.getByRole('button', { name: 'Writing like me' }).waitFor();
    await page.getByPlaceholder('Campaign goal').fill('Autumn concert launch');
    await page.getByPlaceholder('Audience').fill('Local listeners');
    await page.getByPlaceholder('Date, if relevant').fill('2027-10-01');
    await page.getByPlaceholder('Venue, if relevant').fill('Hall A');
    await page.getByRole('button', { name: 'Create reviewable campaign' }).click();
    await page.getByText('Autumn concert launch', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Refresh' }).click();
    await page.getByText('This campaign has confirmed facts but no draft items yet.', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: new URL(`raffi-home-${width}.png`, out).pathname, fullPage: true });
    await context.close();
  }
  console.log('PASS: Raffi composer toggle, campaign persistence UI, evidence suggestion UI, 1024px and 390px');
} finally { await browser.close(); }
