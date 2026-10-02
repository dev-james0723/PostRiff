/** Actual Next components, synthetic browser API only. No real API, DB, funding qualification or provider execution. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:3039';
const attempt = process.argv[2] ?? 'browser';
assert.match(attempt, /^[a-z0-9-]+$/);
const onlyMedia = process.argv[3] === 'media-only';
assert.ok(!process.argv[3] || onlyMedia, 'Use media-only to rerun the affected scenes');
const out = path.resolve(__dirname, '../../.superpowers/sdd/2026-09-28-rafii-pricing-credits-app-wide/task-9-evidence', attempt);
fs.mkdirSync(out, { recursive: true });
const wid = '11111111-1111-4111-8111-111111111111', principal = '22222222-2222-4222-8222-222222222222';
const membership = { role: 'owner', can_publish: true, can_reply: true, can_moderate: true, can_manage_connections: true };
const tours = Object.fromEntries([...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m => [m[1], 1]));
const checks = [], requests = [], unknown = [], errors = [], external = [];
let mode = 'managed_credits', writer = 'paid', qualifiedImage = true, ceiling = 1200, cached = false, previewEligible = false, mediaScene = false;
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
const snapshot = () => ({ revision: 7, state: { workspace: { id: wid, name: 'Synthetic Task 9', sample: false }, writerDefaults: { model: activeModel() }, speaker: { label: 'Synthetic author', activeRevision: 'voice1', revisions: [], proposals: [], interviews: [] }, sources: [], variants: [], approvals: [], skills: [], contentTypes: { installedPacks: [] }, brandHub: {}, mediaEgress: { cloud: true, processors: [{ id: 'synthetic-reader' }] }, phase2: { channels: [], jobs: [], assets: mediaScene ? [{ id: assetId, hash: 'synthetic-hash', mime: 'image/png', width: 1, height: 1, deleted: false, processing: 'decoded' }] : [], channelFolders: [], automations: [] }, coworker: {} } });
const genomeCatalog = () => {
  const available = mode === 'legacy_allowances' || mode === 'free_preview' && previewEligible;
  return { billingMode: mode === 'free_preview' ? 'free' : mode === 'legacy_allowances' ? 'legacy' : 'managed_credits', available, reason: available ? null : 'funding_unavailable', maxPosts: 20, csvImport: { available, reason: available ? null : 'funding_unavailable' } };
};
const catalog = { radar: true, postDoctor: true, postDoctorV2: true, genome: true, consented: true, routes: ['synthetic:rubric'], allowedRoutes: ['synthetic:rubric', 'synthetic:summary'], writer: 'cloud/writer', writerRoute: 'synthetic:writer', maxHistoryPosts: 20, checksPerDay: 10, rewritesPerDay: 1, postmortem: true, audienceMiner: true, summaryRoute: 'synthetic:summary', audienceConsent: true };
const run = () => ({ runId: 'synthetic-run', conversationId: 'synthetic-conversation', status: 'completed', events: [], cursor: 0, artifact: { variants: [] }, artifactHash: 'synthetic-artifact', revision: 7 });
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
  else if (p.endsWith('/ideas/credit-estimates')) json = { estimateMilliCredits: cached ? 0 : 100, ceilingMilliCredits: cached ? 0 : ceiling, availableMilliCredits: mode === 'free_preview' ? 0 : 10000, basis: 'Synthetic configured prices, UI only', model: body?.request?.imageGeneration?.enabled ? 'synthetic/image' : activeModel(), provider: 'synthetic', policy: 'synthetic', stateRevision: 7, cached };
  else if (p.endsWith('/ideas/credit-quotes')) json = { quoteId: 'synthetic-quote', maxMilliCredits: body.maxMilliCredits, kind: 'spending_limit', expiresAt: 9999999999 };
  else if (p.endsWith('/ideas/media-notes')) json = { assetId: body.assetId, status: 'ready', cached, note: { kind: 'photo', frames: 1, text: 'Synthetic cached photo notes', model: 'synthetic/vision', processor: 'synthetic-reader', at: 1 }, usage: { milliCredits: cached ? 0 : 100, costState: 'actual' } };
  else if (p.endsWith(`/media/${assetId}`)) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1kAAAAASUVORK5CYII=', 'base64') });
  else if (p.endsWith('/ideas/quick-start') || p.endsWith('/turns') || p.endsWith('/events')) json = run();
  else if (p.endsWith('/ideas/conversations') && req.method() === 'POST') json = { conversationId: 'synthetic-conversation' };
  else if (p.endsWith('/ideas/conversations') || p.endsWith('/navigation/conversations')) json = { conversations: [], items: [] };
  else if (p.endsWith('/messages')) json = { messages: [], nextCursor: null };
  else if (p.endsWith('/growth/catalog')) json = { ...catalog, genomeAnalysis: genomeCatalog() };
  else if (p.endsWith('/growth/overview')) json = { posts: [], reports: [], calibration: { versions: [], largestCohort: 0, minimumPosts: 20, available: false, notice: '' }, coverage: { maximumPosts: 20, loadedPosts: 0 }, notice: 'Synthetic saved results' };
  else if (p.endsWith('/growth/audience')) json = { conversion: { suggestedTopics: 0, savedTopics: 0, writtenTopics: 0, rate: null, basis: 'synthetic' }, clusters: [], eligibleComments: 1, maximumPerRun: 20, audienceConsent: true, coverage: 'Synthetic comments', notice: '' };
  else if (p.endsWith('/growth/genome')) json = { active: null, versions: [], shares: [], evidence: {} };
  else if (p.endsWith('/growth/radar/scans')) json = { scans: [] };
  else if (p.endsWith('/growth/radar/catalog')) json = { sources: [], consent: { sources: [], ai: false }, monitor: { enabled: false }, monitorMaximumUsdMicro: 0, monitoringAvailable: false, paidMonitoring: false };
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
  const browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
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
  try {
    if (!onlyMedia) {
    await fresh(context, page, '/app');
    await page.getByRole('button', { name: 'Generate image', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Generate image', exact: true }).click();
    const input = page.locator('textarea').first(); await input.fill('A synthetic piano on a quiet stage');
    const max = page.getByLabel('Maximum credits for this image'); await max.waitFor();
    await page.getByText('Usually about', { exact: false }).first().waitFor();
    await max.fill('1.2'); await shot(page, 'home-image-desktop');
    await page.setViewportSize({ width: 390, height: 844 }); await shot(page, 'home-image-mobile');
    await page.getByRole('button', { name: /Generate drafts/ }).click();
    await page.waitForFunction(() => !document.querySelector('input[aria-label="Maximum credits for this image"]')?.disabled);
    const q = requests.findLast(r => r.path.endsWith('/credit-quotes'));
    const sent = requests.findLast(r => r.path.endsWith('/quick-start'));
    assert.ok(q && sent, 'Home performs synthetic quote before synthetic quick-start');
    assert.equal(q.body.maxMilliCredits, 1200); assert.deepEqual(q.body.request.imageGeneration, { enabled: true, count: 1 });
    const estimate = requests.findLast(r => r.path.endsWith('/credit-estimates'));
    assert.deepEqual(estimate.body.request.imageGeneration, sent.body.imageGeneration);
    checks.push('home-image-estimate-quote-submit-binding');
    writer = 'cli'; await page.setViewportSize({ width: 1440, height: 1000 });
    await fresh(context, page, '/app/agent/synthetic-conversation');
    await page.getByRole('button', { name: 'Generate image', exact: true }).click();
    await page.locator('textarea').first().fill('A separately paid image with a CLI writer');
    await page.getByLabel('Maximum credits for this image').fill('1.2');
    await page.getByText('Usually about', { exact: false }).first().waitFor();
    await shot(page, 'conversation-cli-image-desktop');
    await page.setViewportSize({ width: 390, height: 844 }); await shot(page, 'conversation-cli-image-mobile');
    await page.getByRole('button', { name: /Send/ }).last().click();
    await page.waitForFunction(() => !document.querySelector('input[aria-label="Maximum credits for this image"]'));
    const turnQuote = requests.findLast(r => r.path.endsWith('/credit-quotes'));
    assert.equal(turnQuote.body.operation, 'turn'); assert.deepEqual(turnQuote.body.request.imageGeneration, { enabled: true, count: 1 });
    checks.push('cli-writer-image-still-approves-maximum');
    writer = 'paid'; await page.setViewportSize({ width: 1440, height: 1000 });
    await fresh(context, page, '/app/ideas');
    await page.getByLabel('Your idea').fill('A synthetic idea worth keeping');
    await page.getByRole('button', { name: 'Draft now', exact: true }).click();
    const dialog = page.getByRole('dialog'); await dialog.getByRole('heading', { name: 'Review this draft’s maximum' }).waitFor();
    assert.ok(await dialog.getByRole('button', { name: 'Approve maximum & draft' }).isDisabled());
    await dialog.getByText('Usually about', { exact: false }).waitFor(); await dialog.getByLabel('Maximum credits for this draft').fill('1.2');
    await shot(page, 'ideas-approval-desktop'); await page.setViewportSize({ width: 390, height: 844 }); await shot(page, 'ideas-approval-mobile');
    await dialog.getByRole('button', { name: 'Approve maximum & draft' }).click(); await dialog.waitFor({ state: 'hidden' }); checks.push('ideas-no-paid-submit-before-approval');
    mode = 'free_preview'; await fresh(context, page, '/app/ideas');
    await page.getByText('Free has no managed writing allowance.', { exact: false }).first().waitFor();
    await page.getByLabel('Your idea').fill('Keep this manual idea');
    assert.ok(await page.getByRole('button', { name: 'Draft now', exact: true }).isDisabled());
    assert.equal(await page.getByRole('button', { name: 'Save to ideas', exact: true }).isDisabled(), false);
    await shot(page, 'free-ideas-mobile');
    await fresh(context, page, '/app/workspace/brand');
    await page.getByText('1 lifetime recent-20 Genome analysis remaining.', { exact: false }).waitFor();
    await page.getByText('Platform funding is unavailable.', { exact: false }).waitFor();
    assert.ok(await page.getByRole('button', { name: 'Propose my Genome' }).isDisabled()); await shot(page, 'free-genome-funding-off-mobile');
    mode = 'managed_credits'; await fresh(context, page, '/app/growth?view=audience');
    await page.getByText('This AI task is unavailable until', { exact: false }).waitFor();
    assert.ok(await page.getByRole('button', { name: 'Find audience insights' }).isDisabled()); await shot(page, 'managed-growth-unavailable-mobile');
    await page.setViewportSize({ width: 1440, height: 1000 }); await shot(page, 'managed-growth-unavailable-desktop');
    await fresh(context, page, '/app/account/models');
    await page.getByText('Managed drafts use a task estimate', { exact: false }).waitFor();
    assert.equal(await page.locator('[data-tour="models-current"]').getByText(/writing batch/).count(), 0); await shot(page, 'managed-writing-now-desktop');
    mode = 'legacy_allowances'; await fresh(context, page, '/app/ideas'); await page.getByText('No writing batches left', { exact: true }).waitFor(); await shot(page, 'legacy-ideas-desktop');
    qualifiedImage = false; mode = 'managed_credits'; await fresh(context, page, '/app');
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.trim() === 'Generate image' && button.title.includes('qualified image credit estimate')));
    assert.ok(await page.getByRole('button', { name: 'Generate image', exact: true }).isDisabled()); checks.push('unqualified-image-disabled');
    }
    mediaScene = true; writer = 'cli'; ceiling = 1200;
    async function mediaHome() {
      await page.addInitScript(({ principal, wid, assetId }) => sessionStorage.setItem(`rafii.brief.${principal}.${wid}`, JSON.stringify({ version: 2, owner: principal, workspace: wid, text: 'Manual reference', chips: [{ kind: 'image', id: assetId, label: 'Photo', role: 'reference' }] })), { principal, wid, assetId });
      await fresh(context, page, '/app');
      await page.getByRole('button', { name: 'Photo, Reference', exact: true }).click();
    }
    await mediaHome(); await page.getByRole('button', { name: 'Read · approve MAX 1.2 credits' }).waitFor();
    await page.getByText('About 0.1 credits', { exact: false }).waitFor();
    await shot(page, 'cli-writer-media-max-desktop'); await page.setViewportSize({ width: 390, height: 844 }); await shot(page, 'cli-writer-media-max-mobile');
    const readsBefore = requests.filter(r => r.path.endsWith('/media-notes')).length, quotesBefore = requests.filter(r => r.path.endsWith('/credit-quotes')).length;
    ceiling = 1300; await page.getByRole('button', { name: 'Read · approve MAX 1.2 credits' }).click();
    await page.getByText('The fresh estimate exceeds your approved maximum.', { exact: false }).first().waitFor();
    assert.equal(requests.filter(r => r.path.endsWith('/media-notes')).length, readsBefore); assert.equal(requests.filter(r => r.path.endsWith('/credit-quotes')).length, quotesBefore); checks.push('media-fresh-ceiling-refused-before-quote-read');
    ceiling = 1200; await page.getByRole('button', { name: 'Retry · approve MAX 1.2 credits' }).click();
    await page.getByText('Synthetic cached photo notes', { exact: true }).waitFor();
    const mediaQuote = requests.findLast(r => r.path.endsWith('/credit-quotes')); assert.equal(mediaQuote.body.operation, 'media-notes'); assert.equal(mediaQuote.body.maxMilliCredits, 1200); assert.deepEqual(mediaQuote.body.request, { assetId }); checks.push('media-cli-retry-retains-approved-maximum');
    mode = 'free_preview'; cached = true; await mediaHome();
    const freeQuotesBefore = requests.filter(r => r.path.endsWith('/credit-quotes')).length;
    await page.getByRole('button', { name: 'Use cached notes', exact: true }).click(); await page.getByText('Synthetic cached photo notes', { exact: true }).waitFor();
    assert.equal(requests.filter(r => r.path.endsWith('/credit-quotes')).length, freeQuotesBefore); await shot(page, 'free-cached-notes-mobile'); checks.push('free-cached-read-no-credit-quote');
    assert.deepEqual(errors, [], 'No uncaught component errors');
    console.log(JSON.stringify({ execution: 'SYNTHETIC_BROWSER_ONLY', checks, unknownRoutes: [...new Set(unknown)], blockedExternalOrigins: [...new Set(external)], errors }, null, 2));
  } finally {
    await page.screenshot({ path: path.join(out, 'final-state.png'), fullPage: true }).catch(() => {});
    fs.writeFileSync(path.join(out, 'final-state.html'), await page.content());
    fs.writeFileSync(path.join(out, 'scene-results.json'), JSON.stringify({ execution: 'SYNTHETIC_BROWSER_ONLY', checks, requests, unknownRoutes: [...new Set(unknown)], external, errors }, null, 2));
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
