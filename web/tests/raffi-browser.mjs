/**
 * Local production build with a synthetic API: Rafii's Home composer, Writing Voice setting, planning strip
 * (Automations) and evidence-backed suggestions, at 1024px and 390px.
 *
 *   RAFFI_WEB_URL=http://127.0.0.1:4439 node web/tests/raffi-browser.mjs
 *
 * Campaigns are planned on the Automations page now, so Home only links there; the old inline campaign form is gone.
 * Every /api request is answered from tests/fixtures/wp04a-workspace.json; nothing leaves the machine. Screenshots
 * go to the system temp directory, never into the repository.
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/wp04a-workspace.json', import.meta.url), 'utf8'));
const base = process.env.RAFFI_WEB_URL || process.env.RAFII_WEB_URL || 'http://127.0.0.1:4439';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = mkdtempSync(join(tmpdir(), 'raffi-browser-'));
const REASON = 'This campaign has confirmed facts but no draft items yet.';
const browser = await chromium.launch({ headless: true, executablePath: process.env.RAFII_CHROMIUM_PATH || undefined });
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
        if (body.action === 'raffi_suggestion_refresh') snapshot.state.raffi.suggestions.push({ id: 'suggestion-browser', kind: 'campaign_gap', reason: REASON, status: 'open', evidence: [{ type: 'campaign', id: 'campaign-browser', revision: 1 }], action: 'campaign', actionRef: null });
        return send(snapshot);
      }
      if (route.request().method() !== 'GET') return send({ error: 'Unexpected mutation' }, 400);
      if (path === '/api/catalog') return send({ authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {} });
      if (path === '/api/workspaces') return send({ workspaces: [{ workspaceId: wid, membership: snapshot.membership, name: 'Rafii browser fixture', plan: 'studio', memberCounts: { owner: 1 } }] });
      if (path === '/api/me') return send({ userId: '00000000-0000-0000-0000-000000000001', displayName: 'Rafii fixture', preferences: { timeZone: 'America/New_York', locale: 'en', alertNewDevice: false }, mfa: {} });
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

    // The composer shows an example of what to type, not instructions.
    await page.getByPlaceholder('Launch post for my new course').waitFor();

    // Writing Voice: a setting that opens a dialog; choosing a voice closes it and the setting says which.
    const settings = page.getByRole('group', { name: 'Draft settings' });
    const voice = settings.getByRole('button', { name: /Writing Voice/ });
    await voice.click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('radiogroup', { name: 'Writing voice' }).waitFor();
    await dialog.getByRole('radio', { name: /Neutral/ }).click();
    await dialog.getByRole('button', { name: 'Use this voice' }).click();
    await dialog.waitFor({ state: 'hidden' });
    assert.match(await voice.innerText(), /Neutral/);

    const planner = page.getByRole('region', { name: 'Automations and Rafii suggestions' });
    await planner.getByRole('heading', { name: 'Automations' }).waitFor();

    // Suggestions: none, then Refresh brings one with its reason and one action to review it.
    await planner.getByText('No suggestions right now', { exact: true }).waitFor();
    await planner.getByRole('button', { name: 'Refresh' }).click();
    await planner.getByRole('heading', { name: '1 idea for you' }).waitFor();
    await planner.getByText(REASON, { exact: true }).waitFor();
    await planner.getByRole('button', { name: `Review: ${REASON}` }).waitFor();
    assert.equal(await planner.getByRole('button', { name: /Dismiss/ }).count(), 1);

    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: join(out, `raffi-home-${width}.png`), fullPage: true });

    // Campaigns and recurring posts are planned on Automations; Home sends you there instead of carrying a form.
    await planner.getByRole('button', { name: /Open Automations/ }).click();
    await page.waitForURL((url) => url.pathname === '/app/automations');
    await context.close();
  }
  console.log(`PASS: Rafii Home composer, Writing Voice, Automations link and suggestions at 1024px and 390px (screenshots in ${out})`);
} finally { await browser.close(); }
