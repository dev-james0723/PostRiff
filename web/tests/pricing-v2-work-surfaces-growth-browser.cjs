/** Actual Next components, synthetic browser API only. No real API, DB, funding qualification or provider execution. */
/* eslint-disable no-console -- Preserve scene progress and raw synthetic verification results. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:3039';
const attempt = process.argv[2] ?? 'browser';
assert.match(attempt, /^[a-z0-9-]+$/);
const out = path.resolve(__dirname, '../../.superpowers/sdd/2026-09-28-rafii-pricing-credits-app-wide/task-9-resume-evidence', attempt);
fs.mkdirSync(out, { recursive: true });
const wid = '11111111-1111-4111-8111-111111111111', principal = '22222222-2222-4222-8222-222222222222';
const membership = { role: 'owner', can_publish: true, can_reply: true, can_moderate: true, can_manage_connections: true };
const tours = Object.fromEntries([...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m => [m[1], 1]));
const checks = [], requests = [], unknown = [], errors = [], external = [];
let mode = 'managed_credits', writer = 'paid', qualifiedImage = true, ceiling = 1200, cached = false, previewEligible = true, mediaScene = false;
let rewriteReady = true, rewriteCached = false, radarFail = false, zeroFinished = false, baseCheckReady = false;
const checkResult = { runId: 'synthetic-check', questionSet: 'postdoctor.v2', status: 'completed', dimensions: [], confidence: 'limited', confidenceReasons: [], helping: [], hurting: [], change: [], risks: [] };
const rewriteResult = { runId: 'synthetic-rewrite', original: 'My saved evidence', rewrite: 'My revised evidence', before: checkResult, after: checkResult, grounding: 'supported', changes: [{ id: 'change1', index: 0, before: 'My saved evidence', text: 'My revised evidence', dimension: 'clarity', usesFacts: ['fact1'] }], missingFacts: [], notes: '', userMilliCreditsCharged: 300, userCreditsCharged: 0.3 };
const radarScan = status => ({ id: 'zero-scan', status, query: 'Piano practice', mode: 'quick', sources: ['zero'], useAi: false, maximumUsdMicro: 0, customerCharge: 'none', opportunities: [], notification: false, steps: [], sourceResults: [], usage: { knownUsdMicro: 0, actualUsdMicro: 0, unknownAttempts: 0 } });
const assetId = 'asset-synthetic';
const attachments = { enabled: true, limits: { references: 8, posts: 4, attachments: 4, videos: 1 }, photo: { accept: ['image/png'], convertFrom: [], maxPickBytes: 100000, maxSendBytes: 100000 }, video: { enabled: false, mimes: [], maxBytes: 0, maxSeconds: 0, frames: 4 }, notes: { available: true, processor: { id: 'synthetic-reader', model: 'synthetic/vision', provider: 'synthetic' }, photo: { typicalMilliCredits: 100, ceilingMilliCredits: 1200 }, video: { typicalMilliCredits: 100, ceilingMilliCredits: 1200 }, consentAction: 'media_egress' } };
const options = [
  { id: 'cloud/writer', label: 'Cloud writer', provider: 'cloud', costClass: 'paid', qualified: true, priced: true, detail: 'Synthetic configured writer' },
  { id: 'cli/writer', label: 'CLI writer', provider: 'local', route: 'codex', costClass: 'subscription', qualified: true, priced: true, detail: 'Synthetic subscription writer' },
  { id: 'byok/writer', label: 'Own provider', provider: 'own', costClass: 'byok', qualified: true, priced: true, detail: 'Synthetic own-provider writer' }
];
function activeModel() { return writer === 'paid' ? 'cloud/writer' : writer === 'cli' ? 'cli/writer' : 'byok/writer'; }
function usage() { return {
  billingMode: mode, aiUsageExempt: false, entitlement: { plan: mode === 'free_preview' ? 'free' : mode === 'legacy_allowances' ? 'studio' : 'creator', status: 'active', writingBatches: 0, writingBatchesRemaining: 0, mediaCredits: 0, mediaCreditsRemaining: 0, storageMb: 200, storageBytesUsed: 0, connectedAccounts: 6, resetsAt: null },
  credits: mode === 'managed_credits' ? { availableMilliCredits: 10000, heldMilliCredits: 0, grantedMilliCredits: 10000, usedMilliCredits: 0, reversedMilliCredits: 0, expiredMilliCredits: 0, currentPeriodGrantMilliCredits: 10000, currentPeriodExpiresAt: null, debtMilliCredits: 0, lots: [], spendAvailable: true, spendUnavailableReason: null, quoteType: 'spending_limit', textOnly: true } : null,
  freePreview: mode === 'free_preview' ? { postDoctor: { remaining: 1, eligible: previewEligible, reason: previewEligible ? null : 'funding_unavailable' }, genome: { remaining: 1, eligible: previewEligible, reason: previewEligible ? null : 'funding_unavailable', maxPosts: 20 } } : null,
  subscription: null, budget: null, overage: 'off', ledger: [], planTerms: [], note: '', lifecycle: { status: 'active' }, billing: { provider: 'synthetic', checkoutAvailable: false, portalAvailable: false }, membership
}; }
const snapshot = () => ({ revision: 7, state: { workspace: { id: wid, name: 'Synthetic Task 9', sample: false }, writerDefaults: { model: activeModel() }, speaker: { label: 'Synthetic author', activeRevision: 'voice1', revisions: [], proposals: [], interviews: [] }, sources: [], variants: [{ id: 'saved-variant', revision: 1, text: 'My saved evidence', platform: 'LinkedIn', language: 'en-US', warnings: [], unknowns: [], voiceRevision: 'voice1', needsReview: false, provenance: { runId: 'synthetic-run' } }], approvals: [], skills: [], contentTypes: { installedPacks: [] }, brandHub: {}, mediaEgress: { cloud: true, processors: [{ id: 'synthetic-reader' }] }, phase2: { channels: [], jobs: [], assets: mediaScene ? [{ id: assetId, hash: 'synthetic-hash', mime: 'image/png', width: 1, height: 1, deleted: false, processing: 'decoded' }] : [], channelFolders: [], automations: [] }, coworker: {} } });
const catalog = { radar: true, postDoctor: true, postDoctorV2: true, genome: true, consented: true, routes: ['synthetic:rubric'], allowedRoutes: ['synthetic:rubric', 'synthetic:summary'], writer: 'cloud/writer', writerRoute: 'synthetic:writer', maxHistoryPosts: 20, checksPerDay: 10, rewritesPerDay: 1, postmortem: true, audienceMiner: true, summaryRoute: 'synthetic:summary', audienceConsent: true };
const run = () => ({ runId: 'synthetic-run', conversationId: 'synthetic-conversation', status: 'completed', events: [], cursor: 0, artifact: { variants: [{ platform: 'LinkedIn', language: 'en-US', text: 'My saved evidence', unknowns: [], warnings: [] }] }, artifactHash: 'synthetic-artifact', revision: 7 });
async function response(route) {
  const req = route.request(), u = new URL(req.url()), p = u.pathname, body = req.postDataJSON();
  requests.push({ path: p, method: req.method(), body });
  let json;
  if (p === '/api/catalog') json = { authMode: 'dev', execution: 'synthetic-browser-only', templates: [], routes: [], profileMetadata: {}, phase2: true };
  else if (p === '/api/workspaces') json = { workspaces: [{ workspaceId: wid, membership, name: 'Synthetic Task 9', plan: usage().entitlement.plan, trialPlan: null, owner: { userId: principal, displayName: 'Synthetic author' }, memberCounts: { owner: 1, admin: 0, editor: 0, reviewer: 0, viewer: 0 } }] };
  else if (p === '/api/me') json = { userId: principal, displayName: 'Synthetic author', email: 'fixture@postriff.invalid', mfa: { enforced: false, aal: 'aal1' } };
  else if (p.endsWith('/usage')) json = usage();
  else if (p.endsWith('/models')) json = { models: options, reasoning: [], defaultModel: activeModel(), agents: [], ...(mediaScene ? { attachments } : {}), imageGeneration: { available: true, creditEstimateAvailable: qualifiedImage, model: 'synthetic/image', provider: 'synthetic', costClass: 'paid', independentOfWritingModel: true, detail: 'Synthetic image capability' } };
  else if (p === `/api/workspaces/${wid}`) json = snapshot();
  else if (p.endsWith('/channels')) json = { channels: [], providers: [] };
  else if (p.endsWith('/memory')) json = { files: [], proposals: [], pending: [], research: { enabled: false }, media: { cloud: true, reconfirm: false, decidedAt: 1, decidedBy: principal, processors: [attachments.notes.processor], current: { vision: attachments.notes.processor, image: null }, available: true }, consent: {} };
  else if (p.endsWith('/memory/proposals')) json = { pending: [], proposals: [] };
  else if (p.endsWith('/ideas/credit-estimates') && body.operation === 'post-doctor-rewrite') json = { operation: 'post-doctor-rewrite', estimateKind: 'maximum', estimateMilliCredits: rewriteCached ? 0 : ceiling, ceilingMilliCredits: rewriteCached ? 0 : ceiling, availableMilliCredits: 10000, basis: rewriteCached ? 'completed_rewrite' : 'approved_growth_rewrite_ceiling', model: 'cloud/writer', provider: 'vercel-ai-gateway', policy: 'synthetic-qualified-policy', stateRevision: 7, cached: rewriteCached };
  else if (p.endsWith('/ideas/credit-estimates')) json = { estimateMilliCredits: cached ? 0 : 100, ceilingMilliCredits: cached ? 0 : ceiling, availableMilliCredits: mode === 'free_preview' ? 0 : 10000, basis: 'Synthetic configured prices, UI only', model: body?.request?.imageGeneration?.enabled ? 'synthetic/image' : activeModel(), provider: 'synthetic', policy: 'synthetic', stateRevision: 7, cached };
  else if (p.endsWith('/ideas/credit-quotes')) json = { quoteId: 'synthetic-quote', maxMilliCredits: body.maxMilliCredits, kind: 'spending_limit', expiresAt: 9999999999 };
  else if (p.endsWith('/ideas/media-notes')) json = { assetId: body.assetId, status: 'ready', cached, note: { kind: 'photo', frames: 1, text: 'Synthetic cached photo notes', model: 'synthetic/vision', processor: 'synthetic-reader', at: 1 }, usage: { milliCredits: cached ? 0 : 100, costState: 'actual' } };
  else if (p.endsWith(`/media/${assetId}`)) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1kAAAAASUVORK5CYII=', 'base64') });
  else if (p.endsWith('/ideas/quick-start') || p.endsWith('/turns') || p.endsWith('/events')) json = run();
  else if (p.endsWith('/ideas/conversations') && req.method() === 'POST') json = { conversationId: 'synthetic-conversation' };
  else if (p.endsWith('/ideas/conversations') || p.endsWith('/navigation/conversations')) json = { conversations: [], items: [] };
  else if (p.endsWith('/messages')) json = { messages: [], nextCursor: null };
  else if (p.endsWith('/growth/check')) json = checkResult;
  else if (p.endsWith('/growth/rewrite')) { json = rewriteResult; rewriteCached = true; }
  else if (p.endsWith('/growth/catalog')) json = { ...catalog, baseChecks: { billingMode: mode === 'managed_credits' ? mode : mode === 'free_preview' ? 'free' : 'legacy', available: baseCheckReady, reason: baseCheckReady ? null : 'funding_unavailable' }, rewriteCredits: { billingMode: mode === 'managed_credits' ? mode : mode === 'free_preview' ? 'free' : 'legacy', available: mode === 'managed_credits' && rewriteReady, estimateAvailable: mode === 'managed_credits' && rewriteReady, reason: rewriteReady ? null : 'funding_unavailable' } };
  else if (p.endsWith('/growth/overview')) json = { posts: [], reports: [], calibration: { versions: [], largestCohort: 0, minimumPosts: 20, available: false, notice: '' }, coverage: { maximumPosts: 20, loadedPosts: 0 }, notice: 'Synthetic saved results' };
  else if (p.endsWith('/growth/audience')) json = { conversion: { suggestedTopics: 0, savedTopics: 0, writtenTopics: 0, rate: null, basis: 'synthetic' }, clusters: [], eligibleComments: 1, maximumPerRun: 20, audienceConsent: true, coverage: 'Synthetic comments', notice: '' };
  else if (p.endsWith('/growth/genome')) json = { active: null, versions: [], shares: [], evidence: {} };
  else if (p.endsWith('/growth/radar/scans')) json = { scans: [...(zeroFinished ? [radarScan('completed')] : []), { ...radarScan('quoted'), id: 'old-paid-scan', query: 'Saved paid scan', useAi: true, maximumUsdMicro: 10000, customerCharge: 'credits', maximumCredits: 1 }] };
  else if (p.endsWith('/growth/radar/quotes')) json = radarScan('quoted');
  else if (p.includes('/growth/radar/zero-scan')) { zeroFinished = true; json = radarScan('completed'); }
  else if (p.endsWith('/growth/radar/catalog')) { if (radarFail) return route.fulfill({ status: 503, json: { error: 'Synthetic catalog failure' } }); json = { paidScanAvailable: false, aiAnalysisAvailable: false, sources: [{ id: 'zero', name: 'Qualified public source', status: 'ready', note: 'Server-qualified zero cost' }, { id: 'paid', name: 'Paid source', status: 'credit_bridge_unavailable' }], consent: { sources: ['zero', 'paid'], ai: true }, monitor: { enabled: true, query: 'Saved watch', timezone: 'UTC' }, monitorMaximumUsdMicro: 10000, monitoringAvailable: false, paidMonitoring: true }; }
  else if (p.endsWith('/actions')) json = snapshot();
  else if (p.endsWith('/time-savings')) json = { state: 'empty', completedTasks: 0 };
  else if (p.endsWith('/tools')) json = { tools: [] };
  else { unknown.push(p); return route.fulfill({ status: 503, json: { error: 'Unavailable in this synthetic scene', code: 'synthetic_route_unavailable' } }); }
  return route.fulfill({ json });
}
async function shot(page, name) {
  await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), name + ' has no horizontal overflow');
  checks.push(name);
}
async function fresh(context, page, route) {
  await page.goto(base + route, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.locator('body').waitFor(); // Each scene waits for its actual interactive control below.
}

(async () => {
  console.log('scene:launch');
  const browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  console.log('scene:browser-launched');
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }, { name: 'postriff_theme', value: 'rafii', url: base }]);
  await context.addInitScript(({ principal, wid, tours }) => { localStorage.setItem('postriff-dev-principal', principal); localStorage.setItem('postriff-workspace', wid); localStorage.setItem('postriff-onboarding', JSON.stringify({ completed: tours, dismissed: tours, nudged: tours })); }, { principal, wid, tours });
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.origin !== base) { external.push(u.origin); return route.abort(); }
    if (u.pathname.startsWith('/api/')) return response(route);
    return route.continue();
  });
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', e => errors.push(e.message));
  const count = suffix => requests.filter(r => r.path.endsWith(suffix)).length;
  try {
    console.log('scene:open-saved-draft');
    await fresh(context, page, '/app/pipeline');
    await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
    console.log('scene:saved-draft-open');
    const doctor = page.getByLabel('Post Doctor', { exact: true });
    await doctor.getByLabel('Allow AI analysis of this draft').check();
    assert.ok(await doctor.getByRole('button', { name: 'Check draft', exact: true }).isDisabled(), 'Consent and rewrite readiness cannot fund base checks');
    assert.equal(count('/growth/check'), 0);
    await doctor.getByText('Platform funding for this check is unavailable.', { exact: false }).scrollIntoViewIfNeeded();
    await shot(page, 'managed-base-check-unavailable-desktop');
    await page.setViewportSize({ width: 390, height: 844 }); await shot(page, 'managed-base-check-unavailable-mobile');
    baseCheckReady = true;
    await fresh(context, page, '/app/pipeline');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
    await doctor.getByLabel('Allow AI analysis of this draft').check();
    await doctor.getByText('Platform-funded check; no customer credits charged.', { exact: false }).scrollIntoViewIfNeeded();
    await shot(page, 'managed-base-check-qualified-mobile');
    await page.setViewportSize({ width: 1440, height: 1000 }); await shot(page, 'managed-base-check-qualified-desktop');
    const catalogsBeforeCheck = count('/growth/catalog');
    await doctor.getByRole('button', { name: 'Check draft', exact: true }).click();
    // Synthetic qualification reflects the published server field only; no production funding or policy is activated.
    await doctor.getByRole('button', { name: 'Rewrite and recheck', exact: true }).waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Rewrite and recheck' && !b.disabled));
    assert.ok(count('/growth/catalog') > catalogsBeforeCheck, 'Managed base check fetches current server readiness');
    assert.equal(count('/growth/check'), 1); assert.equal(count('/ideas/credit-quotes'), 0);
    const checked = requests.findLast(r => r.path.endsWith('/growth/check')).body;
    assert.equal(checked.confirmed, true); assert.equal(checked.variantId, 'saved-variant'); assert.equal(checked.variantRevision, 1);
    assert.equal(checked.creditQuoteId, undefined); checks.push('managed-base-check-fresh-projection-no-credit-quote');
    await doctor.getByLabel('Your real facts or examples').fill('My exact evidence');
    await doctor.getByRole('button', { name: 'Rewrite and recheck', exact: true }).click();
    const review = doctor.getByRole('region', { name: 'Review rewrite maximum' });
    await review.waitFor(); console.log('scene:rewrite-review');
    assert.equal(count('/growth/rewrite'), 0);
    assert.equal(count('/ideas/credit-quotes'), 0);
    assert.ok(await review.getByRole('button', { name: 'Approve MAX & rewrite' }).isDisabled());
    await review.getByLabel('Maximum credits for this rewrite').fill('1.2');
    await review.scrollIntoViewIfNeeded(); await shot(page, 'rewrite-max-desktop');
    await page.setViewportSize({ width: 390, height: 844 }); await review.scrollIntoViewIfNeeded(); await shot(page, 'rewrite-max-mobile');
    ceiling = 1300;
    await review.getByRole('button', { name: 'Approve MAX & rewrite' }).click();
    await doctor.getByText('The rewrite plan or revision changed.', { exact: false }).waitFor();
    assert.equal(count('/ideas/credit-quotes'), 0);
    assert.equal(count('/growth/rewrite'), 0);
    assert.equal(await review.getByLabel('Maximum credits for this rewrite').inputValue(), '');
    checks.push('changed-ceiling-clears-approval-before-quote');
    const oldKey = requests.findLast(r => r.body?.operation === 'post-doctor-rewrite').body.request.requestKey;
    await doctor.getByLabel('Your real facts or examples').fill('My updated exact evidence');
    await review.waitFor({ state: 'hidden' });
    await doctor.getByRole('button', { name: 'Rewrite and recheck', exact: true }).click();
    await review.waitFor(); console.log('scene:rewrite-review');
    const newKey = requests.findLast(r => r.body?.operation === 'post-doctor-rewrite').body.request.requestKey;
    assert.notEqual(oldKey, newKey); checks.push('facts-change-invalidates-approval-and-key');
    await review.getByLabel('Maximum credits for this rewrite').fill('1.3');
    await review.getByRole('button', { name: 'Approve MAX & rewrite' }).click();
    await doctor.getByText('Actual charge: 0.3 credits.', { exact: true }).waitFor();
    const quote = requests.findLast(r => r.path.endsWith('/ideas/credit-quotes')), rewrite = requests.findLast(r => r.path.endsWith('/growth/rewrite'));
    assert.equal(quote.body.operation, 'post-doctor-rewrite');
    assert.equal(quote.body.maxMilliCredits, 1300); assert.equal(quote.body.expectedRevision, 7);
    assert.deepEqual(rewrite.body, { ...quote.body.request, expectedRevision: 7, creditQuoteId: 'synthetic-quote' });
    assert.equal(rewrite.body.facts.fact1, 'My updated exact evidence');
    checks.push('exact-estimate-max-quote-rewrite-transport');
    await shot(page, 'rewrite-actual-charge-mobile');
    const quotesBeforeCache = count('/ideas/credit-quotes');
    await doctor.getByRole('button', { name: 'Rewrite and recheck', exact: true }).click();
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Rewrite and recheck' && !b.disabled));
    assert.equal(count('/ideas/credit-quotes'), quotesBeforeCache);
    assert.equal(requests.findLast(r => r.path.endsWith('/growth/rewrite')).body.requestKey, newKey);
    checks.push('completed-replay-no-new-paid-quote');
    await page.setViewportSize({ width: 1440, height: 1000 });
    console.log('scene:open-radar');
    await fresh(context, page, '/app/radar');
    console.log('scene:radar-loaded');
    await page.getByLabel('What is your audience thinking about?').fill('Piano practice');
    await page.getByText('Server-qualified source collection only.', { exact: false }).waitFor();
    assert.ok(await page.getByLabel('Include AI review').isDisabled());
    assert.equal(await page.getByLabel('Include AI review').isChecked(), false);
    assert.ok(await page.getByRole('button', { name: 'Review quote', exact: true }).isDisabled(), 'Stored paid quote remains unstartable');
    assert.equal(await page.getByRole('button', { name: 'Stop scan', exact: true }).isDisabled(), false);
    await page.getByText('Sources, AI permissions & monitoring', { exact: true }).click();
    assert.ok(await page.getByLabel('Paid source').isDisabled());
    assert.equal(await page.getByRole('button', { name: 'Pause daily watch', exact: true }).isDisabled(), false);
    assert.equal(await page.getByText('Allowance: up to', { exact: false }).count(), 0);
    await shot(page, 'radar-qualified-zero-desktop');
    await page.setViewportSize({ width: 390, height: 844 }); await shot(page, 'radar-qualified-zero-mobile');
    await page.getByRole('button', { name: 'Review scan', exact: false }).click();
    await page.getByRole('heading', { name: 'Review your quick scan', exact: true }).waitFor();
    await page.getByText('No customer credits charged. Zero-cost source collection;', { exact: false }).waitFor();
    const radarQuote = requests.findLast(r => r.path.endsWith('/growth/radar/quotes'));
    assert.deepEqual(radarQuote.body.sources, ['zero']); assert.equal(radarQuote.body.useAi, false);
    await page.getByRole('button', { name: 'Confirm & scan', exact: true }).click();
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Confirm & scan'));
    assert.equal(count('/ideas/credit-quotes'), quotesBeforeCache);
    checks.push('v2-zero-source-scan-no-customer-credit-quote');
    await shot(page, 'radar-zero-result-mobile');
    radarFail = true;
    await page.getByRole('button', { name: 'Save Radar permissions', exact: true }).click();
    await page.getByText('Source settings could not load.', { exact: false }).waitFor();
    assert.ok(await page.getByRole('button', { name: 'Review scan', exact: false }).isDisabled(), 'Cached successful catalog with failed refresh cannot authorize');
    checks.push('failed-cached-radar-catalog-refuses-new-scan');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    console.log(JSON.stringify({ execution: 'SYNTHETIC_BROWSER_ONLY', checks, errors, external, unknownRoutes: [...new Set(unknown)] }, null, 2));
  } finally {
    await page.screenshot({ path: path.join(out, 'final-state.png'), fullPage: true, timeout: 10000 }).catch(() => {});
    fs.writeFileSync(path.join(out, 'final-state.html'), await Promise.race([page.content(), new Promise(resolve => setTimeout(() => resolve('<!-- DOM capture timed out -->'), 5000))]));
    fs.writeFileSync(path.join(out, 'scene-results.json'), JSON.stringify({ execution: 'SYNTHETIC_BROWSER_ONLY', checks, requests, errors, external, unknownRoutes: [...new Set(unknown)] }, null, 2));
    await Promise.race([browser.close(), new Promise(resolve => setTimeout(resolve, 10000))]);
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
