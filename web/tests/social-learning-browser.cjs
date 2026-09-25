/** Real Chromium + real Next UI, synthetic APIs; never connects to external accounts. */
const assert = require('node:assert/strict');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
const fixture = JSON.parse(readFileSync(resolve(__dirname, 'fixtures/wp04a-workspace.json'), 'utf8'));
const base = process.env.SOCIAL_WEB_URL;
assert.ok(base && new URL(base).hostname === '127.0.0.1', 'Explicit loopback-only server required');
const out = process.env.SOCIAL_EVIDENCE_DIR;
assert.ok(out, 'Explicit isolated evidence directory required');
mkdirSync(out, { recursive: true });
const provider = (id, platform) => ({ id, platform, configured: true, connectReady: true, productionReviewed: false, capabilities: { identity: true, posts_read: id === 'instagram', publish: true }, setupIssues: [], executionPaused: false, historyAvailableForApp: id === 'instagram', historyPermission: id === 'instagram' ? 'instagram_business_basic' : 'r_member_social' });
const account = (id, platform, accountId, scopes) => ({ id, platform, account: 'Synthetic ' + platform, providerAccountId: accountId, accountType: platform === 'Instagram' ? 'BUSINESS' : 'member', connectionState: 'read_verified', displayState: 'read_verified', scopes, capabilities: {}, evidenceSource: 'synthetic_browser_fixture' });

(async () => {
 const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) });
 const results = [];
 try {
  for (const width of [1024, 390]) {
   const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
   await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }]);
   await context.addInitScript(() => { const id = '00000000-0000-0000-0000-000000000001'; localStorage.setItem('postriff-dev-principal', id); localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: { 'brand-tips': 1 } })); });
   const snapshot = structuredClone(fixture.snapshot);
   snapshot.state.sources = [];
   snapshot.state.speaker.provisional = null;
   const wid = snapshot.state.workspace.id;
   const channels = [account('connection-ig', 'Instagram', '1789', ['instagram_business_basic']), account('connection-li', 'LinkedIn', 'urn:li:person:synthetic', ['openid', 'profile', 'w_member_social'])];
   const providers = [provider('instagram', 'Instagram'), provider('linkedin', 'LinkedIn')];
   const calls = [], unexpected = [], pageErrors = [];
   const page = await context.newPage(); page.setDefaultTimeout(20000);
   page.on('pageerror', error => pageErrors.push(error.message));
   await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    if (url.origin !== base) return route.abort();
    if (!path.startsWith('/api/')) return route.continue();
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    const body = req.method() === 'POST' ? req.postDataJSON() : null;
    calls.push({ method: req.method(), path, body });
    if (path.endsWith('/channels/connection-ig/posts') && req.method() === 'POST') {
      assert.equal(body.confirmed, true);
      const later = Boolean(body.cursor), id = later ? 'post-2' : 'post-1';
      return send({ connectionId: 'connection-ig', providerAccountId: '1789', receipt: later ? 'synthetic-page-2' : 'synthetic-page-1', expiresAt: Date.now() / 1000 + 600, posts: [{ id, text: later ? 'A second original caption.' : 'Hello from my own writing. 🎵', platform: 'Instagram', publishedAt: later ? '2025-01-01T12:00:00Z' : '2026-09-20T12:00:00Z', mediaType: later ? 'VIDEO' : 'IMAGE', permalink: null, thumbnailUrl: null }], nextCursor: later ? null : 'after-first', scannedCount: 1, skippedCount: 0, partialCoverage: true, coverageNote: 'Synthetic API-visible sample', coverage: { startedFromBeginning: !later, endReached: later } });
    }
    if (path.endsWith('/channels/connection-ig/posts/import') && req.method() === 'POST') {
      assert.equal(body.confirmedAuthorship, true);
      snapshot.revision += 1;
      snapshot.state.sources.push(...body.selections.flatMap(selection => selection.postIds.map(id => ({ id: 'sample-' + id, kind: 'voice_sample', title: 'Imported ' + id, text: id === 'post-1' ? 'Hello from my own writing. 🎵' : 'A second original caption.', platform: 'Instagram', active: true, selected: false, revision: 1, contentHash: 'a'.repeat(64), visibility: 'workspace-private', useGrants: [], label: body.labels[id] ?? '', voiceOrigin: 'official_api' }))));
      return send(snapshot);
    }
    if (req.method() !== 'GET') { unexpected.push(req.method() + ' ' + path); return send({ error: 'Unexpected mutation in social learning fixture' }, 403); }
    if (path === '/api/catalog') return send({ authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {} });
    if (path === '/api/workspaces') return send({ workspaces: [{ workspaceId: wid, membership: snapshot.membership, name: 'Social learning fixture', plan: 'studio', memberCounts: { owner: 1 } }] });
    if (path === '/api/me') return send({ userId: '00000000-0000-0000-0000-000000000001', displayName: 'Synthetic owner', preferences: { timeZone: 'UTC', locale: 'en', alertNewDevice: false }, mfa: {} });
    if (path === `/api/workspaces/${wid}`) return send(snapshot);
    if (path.endsWith('/channels')) return send({ channels, providers });
    if (path.endsWith('/usage')) return send({ subscription: { plan: 'studio', status: 'active' }, trial: {}, balances: [] });
    if (path.endsWith('/memory')) return send(fixture.memory);
    if (path.endsWith('/memory/proposals')) return send({ pending: [], recent: [], learning: { items: [] } });
    if (path.endsWith('/ideas/conversations')) return send({ conversations: [] });
    if (path.endsWith('/audit')) return send({ entries: [] });
    if (path === '/api/ideas/models') return send({ models: [{ id: 'deterministic-preview', label: 'Deterministic preview', qualified: true, costClass: 'none', detail: 'Fixture, no model call', reasoning: [{ id: 'quick', available: true, detail: 'Fixture' }] }], reasoning: [{ id: 'quick', available: true, detail: 'Fixture' }], agents: [] });
    unexpected.push('GET ' + path); return send({ error: 'Unhandled fixture route' }, 404);
   });
   try {
    await page.goto(base + '/app/workspace/brand');
    await page.getByLabel('Account to read posts from').selectOption('connection-ig');
    await page.getByRole('button', { name: /Load my posts/ }).click();
    await page.getByLabel('Choose post post-1').check();
    await page.getByLabel('Classify post post-1').selectOption('representative');
    await page.getByRole('button', { name: 'Load more posts', exact: true }).click();
    await page.getByText(/Loaded 2 posts from Jan 2025–Sep 2026/).waitFor();
    assert.equal(await page.getByLabel('Choose post post-1').isChecked(), true);
    await page.getByLabel('Search retrieved posts').fill('second');
    assert.equal(await page.getByLabel('Choose post post-1').count(), 0);
    await page.getByLabel('Choose post post-2').check();
    await page.getByLabel('Classify post post-2').selectOption('sponsored');
    await page.getByLabel('Search retrieved posts').fill('');
    const retain = page.getByRole('button', { name: /Retain \d+ selected posts/ });
    assert.equal(await retain.isDisabled(), true);
    // Chromium's computed name includes the short aria-label before the visible consent text.
    // Match the actual consent wording without assuming that it begins the accessible name.
    const retentionConsent = page.getByRole('checkbox', { name: /I wrote the selected captions and consent to retaining them as private samples\./ });
    assert.equal(await retentionConsent.isChecked(), false);
    assert.equal(calls.filter(call => call.path.endsWith('/posts/import')).length, 0);
    await retentionConsent.focus();
    await page.keyboard.press('Space');
    assert.equal(await retentionConsent.isChecked(), true);
    assert.equal(await retain.isEnabled(), true);
    await page.getByLabel('Classify post post-2').selectOption('outdated');
    assert.equal(await retentionConsent.isChecked(), false);
    assert.equal(await retain.isDisabled(), true);
    await page.getByLabel('Classify post post-2').selectOption('sponsored');
    await retentionConsent.check();
    await retain.click();
    await page.getByText('Imported post-1', { exact: true }).waitFor();
    const retained = calls.find(call => call.path.endsWith('/posts/import'));
    assert.deepEqual(retained.body.selections.flatMap(selection => selection.postIds).sort(), ['post-1', 'post-2']);
    assert.deepEqual(retained.body.labels, { 'post-1': 'representative', 'post-2': 'sponsored' });
    assert.ok(snapshot.state.sources.every(source => !source.selected && source.useGrants.length === 0));
    const beforeLinkedIn = calls.filter(call => call.path.endsWith('/posts')).length;
    await page.getByLabel('Account to read posts from').selectOption('connection-li');
    await page.getByText(/LinkedIn hasn't granted permission to import past posts/).waitFor();
    assert.equal(await page.getByRole('button', { name: /Load my posts/ }).isDisabled(), true);
    assert.equal(calls.filter(call => call.path.endsWith('/posts')).length, beforeLinkedIn);
    await page.getByLabel('Writing sample import format').selectOption('json');
    await page.getByLabel('Writing sample', { exact: true }).fill('[{"text":"My manually provided text","platform":"LinkedIn"}]');
    assert.equal(await page.getByRole('button', { name: 'Retain samples', exact: true }).isDisabled(), true);
    const manualConsent = page.getByRole('checkbox', { name: /I wrote or have permission to use this text and consent to private retention/ });
    await manualConsent.check();
    assert.equal(await page.getByRole('button', { name: 'Retain samples', exact: true }).isEnabled(), true);
    await page.getByLabel('Writing sample', { exact: true }).fill('[{"text":"Changed sample","platform":"LinkedIn"}]');
    assert.equal(await manualConsent.isChecked(), false);
    assert.equal(await page.getByRole('button', { name: 'Retain samples', exact: true }).isDisabled(), true);
    await page.screenshot({ path: resolve(out, `social-picker-${width}.png`), fullPage: true });
    await page.goto(base + '/app');
    await page.getByLabel('Message', { exact: true }).fill('Analyze my recent Instagram posts and learn how I write.');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await page.getByRole('region', { name: 'Review writing samples with Rafii' }).waitFor();
    await page.getByLabel('Choose post post-1').waitFor();
    assert.equal(await page.getByLabel('Choose post post-1').isChecked(), true);
    assert.equal(await page.getByRole('button', { name: /Retain \d+ selected posts/ }).isDisabled(), true);
    assert.equal(calls.filter(call => /quick-start|\/turns|\/analy|\/publish/.test(call.path)).length, 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(pageErrors, []);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: resolve(out, `social-chat-${width}.png`), fullPage: true });
    results.push({ width, status: 'PASS', multiPageSelection: true, classifications: true, retentionConsent: true, keyboardConsent: true, consentInvalidatedOnSampleChange: true, noAutomaticAnalysis: true, linkedinHistoryBlocked: true, manualConsent: true, chatProposesWithoutPublishing: true, realOAuth: false });
   } catch (error) {
    // Only synthetic localhost fixture controls; never inspect a real account or credential field.
    const controls = await page.locator('[data-slot="checkbox"], input[type="checkbox"]').evaluateAll(nodes => nodes.map(node => ({ tag: node.tagName, id: node.id, role: node.getAttribute('role'), label: node.getAttribute('aria-label'), labelledBy: node.getAttribute('aria-labelledby'), checked: node.getAttribute('aria-checked'), labels: [...(node.labels ?? [])].map(label => label.textContent.trim().slice(0, 250)) })));
    console.log(JSON.stringify({ diagnostic: 'synthetic-checkbox-labels', width, controls }));
    writeFileSync(resolve(out, `failure-${width}.txt`), (await page.locator('body').innerText()).slice(0, 22000));
    await page.screenshot({ path: resolve(out, `failure-${width}.png`), fullPage: true });
    throw error;
   } finally { await context.close(); }
  }
  writeFileSync(resolve(out, 'browser-results.json'), JSON.stringify({ execution: 'Real Next UI and Chromium, synthetic API; not live OAuth', results }, null, 2));
  console.log(JSON.stringify(results));
 } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
