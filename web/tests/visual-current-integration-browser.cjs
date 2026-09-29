/** Current VisualCollection + canonical W decision integration.
 * Explicit synthetic API, signed-page and document-visibility fixtures only.
 * The application uses Chromium's native IntersectionObserver (diagnostic wrapper only).
 * No real API/DB, provider/model, publication or production qualification is claimed.
 * Run against the parent's built loopback preview; this file never builds/starts a server.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID, createHmac } = require('node:crypto');
const { chromium } = require('playwright');
const { fixtures } = require('./trend-fixtures.cjs');
const workspaceFixture = require('./fixtures/wp04a-workspace.json');
const t = require('./trend-contract.cjs').loadTypes();
const viewports = [
  { width: 1440, height: 900 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
  { width: 430, height: 932 }
];
const results = [];
function pass(width, name, details) {
  results.push({ width, name, pass: true, details });
  process.stdout.write(`PASS ${width} ${name}\n`);
}
function deferred() {
  let release;
  const promise = new Promise(resolve => { release = resolve; });
  return { promise, release };
}
function candidates(rows) {
  return rows.filter(op => ['candidate', 'ready'].includes(op.state) && op.verification_state === 'verified')
    .map(op => ({ opportunity_id: op.id, revision: op.revision }));
}
async function runViewport(browser, base, out, viewport) {
  const { width } = viewport;
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
  const f = fixtures();
  const snapshot = structuredClone(workspaceFixture.snapshot);
  const wid = snapshot.state.workspace.id;
  const root = `/api/workspaces/${wid}/coworker/trends`;
  const snapshotPath = `/api/workspaces/${wid}`;
  const calls = [], errors = [], consoleErrors = [], external = [], fixtureErrors = [], nativeFailures = [];
  const sourceId = randomUUID();
  const sourceTitle = 'Demo data: accepted visual integration source 🎹';
  const savedSource = {
    id: sourceId, kind: 'research', title: sourceTitle,
    text: 'Explicit synthetic contribution. No generated draft or first-hand claim.',
    selected: false, active: true, visibility: 'private-local', facts: [],
    createdAt: new Date().toISOString(), sourcePolicy: 'internal_reference',
    egressConsent: [], useApprovals: [], unknowns: ['Synthetic browser fixture only.']
  };
  snapshot.state.sources = [];
  snapshot.state.phase2.channels = [{
    ...snapshot.state.phase2.channels[0], id: 'synthetic-channel',
    platform: 'bluesky', account: 'Demo destination', revoked: false
  }];
  f.trend.id = randomUUID();
  f.trend.trust_receipt_id = randomUUID();
  f.trend.dna_profile.trust_receipt_id = f.trend.trust_receipt_id;
  f.trend.canonical_topic = 'Demo data: native observation integration 🎹';
  f.receipt = { ...f.receipt, ...f.trend, receipt_id: f.trend.trust_receipt_id };
  const otherTrend = {
    ...structuredClone(f.trend), id: randomUUID(), trust_receipt_id: randomUUID(),
    canonical_topic: 'Demo data: another delivered conversation'
  };
  otherTrend.dna_profile.trust_receipt_id = otherTrend.trust_receipt_id;
  const ready = {
    ...structuredClone(f.opportunity), id: randomUUID(), trend_id: f.trend.id,
    trust_receipt_id: f.trend.trust_receipt_id, source_id: null, draft_id: null,
    platform_targets: ['bluesky'], title: 'Demo data: supported original contribution'
  };
  const outsideTrend = {
    ...structuredClone(ready), id: randomUUID(), trend_id: otherTrend.id,
    trust_receipt_id: otherTrend.trust_receipt_id, title: 'Demo data: other conversation first in page'
  };
  const outsidePlatform = {
    ...structuredClone(ready), id: randomUUID(), platform_targets: ['tiktok'],
    title: 'Demo data: another platform in the same signed page'
  };
  const insufficient = {
    ...structuredClone(ready), id: randomUUID(), state: 'candidate',
    title: 'Demo data: candidate with insufficient fit',
    workspace_fit: { ...structuredClone(ready.workspace_fit), sufficient: false,
      reason: 'The synthetic sample does not establish workspace fit.' }
  };
  const removed = {
    ...structuredClone(insufficient), id: randomUUID(),
    title: 'Demo data: candidate removed after dismissal'
  };
  // Deliberately include another trend/platform and candidate in the original server order.
  // A page reconstructed from the selected/filtered/sliced visible cards will fail verification.
  const opportunities = [outsideTrend, ready, outsidePlatform, insufficient, removed];
  const accepted = new Set(), dismissed = new Set(), exposureResults = new Map(), tokens = new Map();
  const flagsOn = Object.fromEntries(t.TREND_FLAGS.map(key => [key, [
    'RAFII_TREND_INTELLIGENCE_ENABLED', 'RAFII_TREND_RADAR_ENABLED',
    'RAFII_TREND_TRUST_RECEIPTS_ENABLED', 'RAFII_TREND_SATURATION_ENABLED'
  ].includes(key)]));
  let flags = {}, mode = 'normal', snapshotGate = null;
  const currentOpportunities = () => opportunities
    .filter(op => !(op.id === removed.id && dismissed.has(op.id)))
    .filter(op => mode !== 'candidate-only' || ![ready.id, outsidePlatform.id].includes(op.id))
    .map(op => ({ ...op, state: dismissed.has(op.id) ? 'dismissed' : accepted.has(op.id) ? 'accepted' : op.state,
      source_id: accepted.has(op.id) ? sourceId : null }));
  const pageEnvelope = () => {
    const rows = currentOpportunities();
    const eligible = candidates(rows);
    const payload = Buffer.from(JSON.stringify(eligible)).toString('base64url');
    // Test-only signature: validates exact page order, not the real service's HMAC implementation.
    const token = `synthetic.${payload}.${createHmac('sha256', 'explicit-synthetic-browser-only').update(payload).digest('base64url')}`;
    tokens.set(token, eligible);
    return { ...f.envelope(rows), exposure_token: token };
  };
  for (const op of opportunities) t.opportunitySchema.parse(op);
  for (const trend of [f.trend, otherTrend]) t.trendSchema.parse(trend);
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  const tours = [...fs.readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8')
    .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m => m[1]);
  await context.addInitScript(({ tours, base }) => {
    if (location.origin !== base) return;
    const principal = '00000000-0000-0000-0000-000000000001';
    localStorage.setItem('postriff-dev-principal', principal);
    const state = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(tours.map(id => [id, 1])), nudged: Object.fromEntries(tours.map(id => [id, 1])) });
    localStorage.setItem('postriff-onboarding', state);
    localStorage.setItem('postriff-onboarding:' + principal, state);
    window.syntheticVisibility = 'hidden';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.syntheticVisibility });
    window.visualNativeObservations = [];
    const NativeObserver = window.IntersectionObserver;
    window.IntersectionObserver = class extends NativeObserver {
      constructor(callback, options) {
        super((entries, observer) => {
          for (const entry of entries) if (entry.target.hasAttribute('data-trend-opportunity')) {
            window.visualNativeObservations.push({ at: performance.now(), intersects: entry.isIntersecting,
              rect: entry.intersectionRect.toJSON(), title: entry.target.querySelector('h3')?.textContent });
          }
          callback(entries, observer);
        }, options);
      }
    };
  }, { tours, base });
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    if (url.origin !== base) { external.push(url.origin); return route.abort(); }
    if (!p.startsWith('/api/')) return route.continue();
    const body = req.method() === 'POST' ? req.postDataJSON() : null;
    calls.push({ path: p, query: url.search, method: req.method(), body, at: Date.now() });
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    try {
      if (p === root) {
        if (mode === 'list-error') return send({ code: 'source_unavailable' }, 503);
        return send({ ...f.envelope(url.searchParams.get('query') === 'nothing' ? [] : [f.trend, otherTrend]),
          next_cursor: mode === 'pagination' && !url.searchParams.has('cursor') ? 'synthetic-next-page' : null });
      }
      if (p === root + '/opportunities') {
        if (mode === 'opportunity-error') return send({ code: 'source_unavailable' }, 503);
        return send(pageEnvelope());
      }
      if (p === root + '/exposures') {
        t.exposureInputSchema.parse(body);
        assert.ok(tokens.has(body.exposure_token), 'Only an issued page token may be reported');
        assert.deepEqual(body.eligible_candidates, tokens.get(body.exposure_token), 'Exact original eligible page order');
        const op = opportunities.find(item => item.id === body.opportunity_id);
        assert.ok(op && body.eligible_candidates.some(c => c.opportunity_id === op.id));
        assert.equal(body.opportunity_revision, op.revision);
        assert.equal(body.trust_receipt_id, op.trust_receipt_id);
        assert.equal(body.context_digest, op.context_digest);
        const old = exposureResults.get(body.event_id);
        if (old) assert.deepEqual(old.input, body, 'Stable UUID retries retain the entire binding');
        const result = old?.result ?? { exposure_id: randomUUID(), event_id: body.event_id,
          opportunity_id: op.id, opportunity_revision: op.revision, trust_receipt_id: op.trust_receipt_id,
          context_digest: op.context_digest, measurement: 'client_reported_view',
          eligible_candidate_count: body.eligible_candidates.length, recorded_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 120000).toISOString(), existing: false };
        exposureResults.set(body.event_id, { input: structuredClone(body), result });
        return send(f.envelope({ ...result, existing: Boolean(old) }));
      }
      if (p.endsWith('/accept')) {
        t.acceptOpportunitySchema.parse(body);
        assert.equal(p, `${root}/opportunities/${ready.id}/accept`);
        assert.equal(body.revision, ready.revision);
        assert.equal(body.angle_id, ready.angles[0].id);
        assert.equal(body.channel_id, 'synthetic-channel');
        assert.equal(body.goal, 'Demonstrate an original listening exercise');
        assert.ok([...exposureResults.values()].some(row => row.result.exposure_id === body.exposure_id && row.result.opportunity_id === ready.id));
        const existing = accepted.has(ready.id);
        accepted.add(ready.id);
        if (!existing) {
          snapshot.revision++;
          snapshot.state.sources.push({ ...savedSource, origin: { kind: 'trend_opportunity', trendLineage: {
            opportunity_id: ready.id, opportunity_revision: ready.revision,
            trust_receipt_id: ready.trust_receipt_id, context_digest: ready.context_digest
          } } });
        }
        return send(f.envelope({ source_id: sourceId, href: `/app/ideas?source=${sourceId}`, verified: true, existing }));
      }
      if (p.endsWith('/dismiss')) {
        t.dismissOpportunityInputSchema.parse(body);
        const id = p.split('/').at(-2);
        assert.ok([insufficient.id, removed.id].includes(id));
        assert.equal(body.revision, 1);
        assert.ok([...exposureResults.values()].some(row => row.result.exposure_id === body.exposure_id && row.result.opportunity_id === id));
        const existing = dismissed.has(id); dismissed.add(id);
        return send(f.envelope({ opportunity_id: id, revision: body.revision, state: 'dismissed', exposure_id: body.exposure_id ?? null, existing }));
      }
      if (p === snapshotPath) { if (snapshotGate && accepted.size) await snapshotGate.promise; return send(structuredClone(snapshot)); }
      if (p === `${root}/${f.trend.id}/receipts/${f.trend.trust_receipt_id}`) return send(f.envelope(f.receipt));
      if (p === `${root}/${otherTrend.id}/receipts/${otherTrend.trust_receipt_id}`) return send(f.envelope({ ...f.receipt, ...otherTrend, receipt_id: otherTrend.trust_receipt_id }));
      if (p.endsWith('/saturation')) return send(f.envelope(f.saturation));
      if (p === root + '/methodology') return send(f.envelope(f.methodology));
      if (p === root + '/calibration') return send(f.envelope(f.calibration));
      if (p === root + '/watches') return send(f.envelope([]));
      if (p === '/api/auth/config') return send({ provider: 'dev', execution: 'dev-synthetic', flow: 'dev' });
      if (p === '/api/bootstrap') return send({ workspaceId: wid });
      if (p === '/api/catalog') return send({ authMode: 'dev', execution: 'dev-synthetic', platforms: ['Bluesky'], languages: ['en'], presets: [], voices: [], phase2: true, templates: [], routes: [], profileMetadata: {} });
      if (p === '/api/workspaces') return send({ workspaces: [{ workspaceId: wid, membership: snapshot.membership, name: 'Demo visual integration workspace', plan: 'studio', memberCounts: { owner: 1 } }] });
      if (p === '/api/me') return send({ userId: '00000000-0000-0000-0000-000000000001', displayName: 'Synthetic owner', preferences: { timeZone: 'UTC', locale: 'en', alertNewDevice: false }, mfa: {} });
      if (p.endsWith('/coworker/status')) return send({ flags,
        trend_beta: { state: Object.keys(flags).length ? 'stored_radar' : 'feature_off',
          radar_available: Object.keys(flags).length > 0, acquisition: 'none',
          metric_reads_enabled: false, follower_conversion: 'unavailable' },
        weekly: { recipes: 0, weeks: 0 }, notifications: { enabled: false } });
      if (p.endsWith('/usage')) return send({
        entitlement: { planTermsId: 'synthetic-studio', writingBatchesRemaining: 1, mediaCreditsRemaining: 0,
          connectedAccounts: 1, members: 1, storageMb: 1, resetsAt: null, source: 'synthetic', version: 1 },
        subscription: null, budget: null, overage: 'off', ledger: [], planTerms: [],
        note: 'Explicit synthetic browser allowance; no model dispatch is permitted.',
        lifecycle: { status: 'active', canPublish: false }, membership: snapshot.membership
      });
      if (p.endsWith('/memory')) return send(workspaceFixture.memory);
      if (p.endsWith('/memory/proposals')) return send({ pending: [], recent: [], learning: { items: [] } });
      if (p.endsWith('/ideas/conversations')) return send({ conversations: [] });
      if (p.endsWith('/channels')) return send({ channels: snapshot.state.phase2.channels, providers: [] });
      if (p.endsWith('/audit')) return send({ entries: [] });
      if (p.endsWith('/time-savings')) return send({});
      if (p === '/api/ideas/models') return send({ models: [{ id: 'deterministic-preview', label: 'Synthetic preview', qualified: true, costClass: 'none', reasoning: [{ id: 'quick', available: true }] }], reasoning: [{ id: 'quick', available: true }], agents: [] });
      if (req.method() !== 'GET') fixtureErrors.push(`Unexpected mutation ${req.method()} ${p}`);
      return send({ error: 'Unavailable unrelated synthetic route' }, 404);
    } catch (error) {
      fixtureErrors.push(String(error));
      return send({ error: 'Synthetic fixture assertion failed' }, 500);
    }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push({ text: message.text(), location: message.location() }); });
  page.on('requestfailed', req => { if (req.failure()?.errorText !== 'net::ERR_ABORTED') nativeFailures.push({ url: req.url(), error: req.failure()?.errorText }); });
  const visibility = state => page.evaluate(state => { window.syntheticVisibility = state; document.dispatchEvent(new Event('visibilitychange')); }, state);
  const exposures = id => calls.filter(c => c.path === root + '/exposures' && (!id || c.body.opportunity_id === id));
  const decisions = action => calls.filter(c => c.path.endsWith('/' + action));
  const contribution = title => page.getByRole('region', { name: 'Original contribution', exact: true }).filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  const load = async () => { await page.goto(base + '/app/trends'); await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor(); };
  const waitDwell = ms => page.waitForTimeout(ms); // The product contract is a continuous500ms dwell.
  const selectOpportunity = async op => { await page.getByRole('combobox', { name: 'Choose an opportunity', exact: true }).selectOption(op.id); await contribution(op.title).waitFor(); };
  const expose = async op => {
    const count = exposures(op.id).length;
    await visibility('hidden');
    await contribution(op.title).scrollIntoViewIfNeeded();
    const response = page.waitForResponse(res => res.url() === base + root + '/exposures' && res.request().postDataJSON().opportunity_id === op.id);
    const started = Date.now(); await visibility('visible');
    assert.equal((await response).status(), 200, 'The exact signed-page exposure fixture accepts the event');
    assert.ok(exposures(op.id).at(-1).at - started >= 500, 'Event is dispatched only after500ms visible dwell');
    await page.waitForFunction(() => window.visualNativeObservations.some(row => row.intersects && row.rect.width > 0 && row.rect.height > 0));
    await waitDwell(600); assert.equal(exposures(op.id).length, count + 1, 'One event per unchanged mounted binding');
    return exposures(op.id).at(-1).body;
  };
  try {
    await page.goto(base + '/app/trends');
    await page.getByText('Trend Beta is off', { exact: true }).waitFor();
    await visibility('visible'); await waitDwell(650);
    assert.equal(calls.filter(c => c.path.startsWith(root)).length, 0);
    pass(width, 'defaultOFF makes no trend reads, exposure or decision calls');

    flags = flagsOn; await load();
    const card = contribution(ready.title); await card.scrollIntoViewIfNeeded();
    await waitDwell(650); assert.equal(exposures().length, 0);
    await page.evaluate(() => { const cover = document.createElement('div'); cover.id = 'synthetic-occluder'; cover.style.cssText = 'position:fixed;inset:0;z-index:99999;background:white'; document.body.append(cover); });
    await visibility('visible'); await waitDwell(650); assert.equal(exposures().length, 0);
    await visibility('hidden'); await page.evaluate(() => document.getElementById('synthetic-occluder').remove());
    await visibility('visible'); await waitDwell(150); await visibility('hidden'); await waitDwell(550);
    assert.equal(exposures().length, 0);
    await visibility('visible'); await waitDwell(150); await page.goto('about:blank'); await waitDwell(550);
    assert.equal(exposures().length, 0);
    pass(width, 'delivery, hidden/occluded, sub500ms and unmounted cards never become views');

    await load();
    // A connected platform selection changes the visible cards, not the signed page subset.
    const platformControl = page.getByRole('region', { name: "Where It's Moving", exact: true })
      .getByRole('button').filter({ hasText: 'Bluesky' });
    await platformControl.click();
    assert.equal(await platformControl.getAttribute('aria-pressed'), 'true');
    assert.equal(await page.getByRole('option', { name: outsidePlatform.title, exact: true }).count(), 0);
    const observed = await expose(ready);
    assert.deepEqual(observed.eligible_candidates, candidates(opportunities));
    assert.equal(observed.eligible_candidates.length, 5);
    assert.equal(observed.eligible_candidates[0].opportunity_id, outsideTrend.id);
    assert.ok(observed.eligible_candidates.some(c => c.opportunity_id === outsidePlatform.id));
    pass(width, 'native visible observer reports the full signed ordered page, including off-trend/platform candidates');

    await card.getByText('Develop this idea', { exact: true }).click();
    await card.getByRole('combobox', { name: /^Destination account/ }).selectOption('synthetic-channel');
    await card.getByLabel('Your goal', { exact: true }).fill('Demonstrate an original listening exercise');
    snapshotGate = deferred();
    const refreshed = page.waitForRequest(req => req.url() === base + snapshotPath && req.method() === 'GET');
    await card.getByRole('button', { name: 'Save to Ideas', exact: true }).click();
    await refreshed;
    assert.equal(await page.getByRole('link', { name: 'Review source and create original post', exact: true }).count(), 0);
    assert.ok(await card.getByRole('button', { name: 'Saving…', exact: true }).isDisabled());
    const opportunityRefetch = page.waitForResponse(res => res.url() === base + root + '/opportunities' && res.status() === 200);
    snapshotGate.release(); snapshotGate = null;
    const ideas = page.getByRole('link', { name: 'Review source and create original post', exact: true });
    await ideas.waitFor(); await opportunityRefetch;
    assert.equal(decisions('accept').length, 1);
    assert.equal(decisions('accept')[0].body.exposure_id, exposureResults.get(observed.event_id).result.exposure_id);
    assert.equal(await ideas.getAttribute('href'), `/app/ideas?source=${sourceId}`);
    await ideas.focus(); await page.keyboard.press('Enter');
    await page.waitForURL(url => url.pathname === '/app/ideas' && url.searchParams.get('source') === sourceId);
    const inspector = width < 1024 ? page.getByRole('dialog') : page.getByRole('complementary', { name: 'Source inspector' });
    await inspector.getByText(sourceTitle, { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(out, `ideas-immediate-${width}.png`) });
    await page.reload(); await inspector.getByText(sourceTitle, { exact: true }).first().waitFor();
    pass(width, 'accept binds measured exposure; Ideas waits for canonical snapshot, refetches opportunities and survives navigation/reload');

    mode = 'candidate-only'; await load(); await selectOpportunity(insufficient);
    const candidate = contribution(insufficient.title);
    await candidate.getByText('Content angles are unavailable until workspace fit has enough support.', { exact: true }).waitFor();
    assert.equal(await candidate.getByRole('button', { name: 'Save to Ideas', exact: true }).count(), 0);
    assert.ok(await page.getByRole('button', { name: 'Create original post', exact: true }).isDisabled());
    assert.ok(await candidate.getByRole('button', { name: 'Not relevant', exact: true }).isEnabled());
    const candidateView = await expose(insufficient);
    await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
    const axe = await page.evaluate(async () => (await window.axe.run(document.querySelector('main'))).violations.map(v => ({ id: v.id, impact: v.impact })));
    assert.deepEqual(axe.filter(v => ['serious', 'critical'].includes(v.impact)), []);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(out, `candidate-insufficient-${width}.png`) });
    pass(width, 'insufficient candidate remains visible with creation disabled and dismissal usable; viewport and axe', { axe });
    const refreshAfterDismiss = page.waitForResponse(res => res.url() === base + root + '/opportunities' && res.status() === 200);
    await candidate.getByRole('button', { name: 'Not relevant', exact: true }).focus(); await page.keyboard.press('Enter');
    const status = page.getByText('Marked not relevant. The conversation and its evidence remain available.', { exact: true });
    await status.waitFor(); await refreshAfterDismiss;
    await page.waitForFunction(() => document.activeElement?.textContent === 'Marked not relevant. The conversation and its evidence remain available.');
    assert.equal(decisions('dismiss').at(-1).body.exposure_id, exposureResults.get(candidateView.event_id).result.exposure_id);
    await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor();
    await page.getByRole('button', { name: 'Why should I trust this?', exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, `dismissed-focus-${width}.png`) });
    pass(width, 'canonical keyboard dismissal keeps status/focus through refetch and preserves trend/evidence');

    await selectOpportunity(removed); await expose(removed);
    const removedRefresh = page.waitForResponse(res => res.url() === base + root + '/opportunities' && res.status() === 200);
    await contribution(removed.title).getByRole('button', { name: 'Not relevant', exact: true }).focus(); await page.keyboard.press('Enter');
    await removedRefresh;
    await page.waitForFunction(() => document.activeElement?.matches('.vi-creative-anchor[tabindex="-1"]') && document.activeElement.querySelector('h3')?.textContent === 'Creative Opportunity');
    assert.equal(await page.getByRole('option', { name: removed.title, exact: true }).count(), 0);
    pass(width, 'server-removed dismissed row falls back to the creative-section heading anchor focus');

    await visibility('hidden'); mode = 'pagination'; await load();
    const next = page.waitForRequest(req => new URL(req.url()).pathname === root && new URL(req.url()).searchParams.get('cursor') === 'synthetic-next-page');
    await page.getByRole('button', { name: 'Next page', exact: true }).click(); await next;
    await page.getByRole('button', { name: /^Filters/ }).click();
    const filtered = page.waitForRequest(req => { const u = new URL(req.url()); return u.pathname === root && u.searchParams.get('platform') === 'bluesky' && !u.searchParams.has('cursor'); });
    await page.getByRole('combobox', { name: /^Platform/ }).selectOption('bluesky'); await filtered;
    await page.getByRole('button', { name: /^Filters/ }).click();
    await page.getByLabel('Search trends', { exact: true }).fill('nothing');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await page.getByText('No matches in the available scope', { exact: true }).waitFor();
    mode = 'opportunity-error'; await load();
    await page.getByText('Workspace opportunities are unavailable', { exact: true }).waitFor();
    assert.equal(await page.getByRole('region', { name: 'Original contribution', exact: true }).count(), 0);
    pass(width, 'cursor/filter reset, empty search and opportunity-error retain original query semantics');
    assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(fixtureErrors, []);
    assert.deepEqual(nativeFailures, []);
    assert.equal(snapshot.state.sources.length, 1);
    assert.equal(decisions('accept').length, 1); assert.equal(decisions('dismiss').length, 2);
    assert.ok(calls.filter(c => c.method === 'POST').every(c => c.path === root + '/exposures' || c.path.endsWith('/accept') || c.path.endsWith('/dismiss')));
    pass(width, 'no runtime failures, unexpected egress/mutations, generation or publication');
    fs.writeFileSync(path.join(out, `calls-${width}.json`), JSON.stringify(calls, null, 2) + '\n');
  } catch (error) {
    results.push({ width, name: 'viewport failure', pass: false, error: String(error) });
    fs.writeFileSync(path.join(out, `failure-${width}.json`), JSON.stringify({ error: String(error), calls, errors, consoleErrors, fixtureErrors, external, nativeFailures,
      observations: await page.evaluate(() => window.visualNativeObservations).catch(() => []),
      text: await page.locator('body').innerText().catch(() => '') }, null, 2) + '\n');
    await page.screenshot({ path: path.join(out, `failure-${width}.png`) }).catch(() => {});
    throw error;
  } finally {
    snapshotGate?.release();
    await context.close();
  }
}
async function main() {
  const base = process.env.TREND_WEB_URL, out = process.env.TREND_EVIDENCE_DIR;
  assert.ok(base && new URL(base).hostname === '127.0.0.1' && out, 'Explicit loopback preview URL + isolated evidence directory required');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const failures = [];
    for (const viewport of viewports) {
      try { await runViewport(browser, base, out, viewport); }
      catch (error) { failures.push(error); console.error(`${viewport.width}: ${error}`); }
    }
    if (failures.length) throw new AggregateError(failures, `${failures.length} viewport(s) failed; exact artifacts retained`);
  }
  finally {
    await browser.close();
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ execution: 'explicit_synthetic_API_signed_page_and_visibility_fixtures',
      native_intersection_observer: true, viewports, results, real_API_DB: false, builds_started: 0 }, null, 2) + '\n');
  }
}
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
