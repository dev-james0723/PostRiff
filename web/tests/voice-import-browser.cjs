'use strict';
/**
 * Voice import (plan E5; IMP-3, IMP-6, PRO-4…6) through the real web app and the hosted Python handlers of the local
 * dev harness. Synthetic identity, synthetic provider history and synthetic export files only. No API response is
 * mocked; every request that leaves the harness origin is blocked.
 *
 * Journey at 1440 and 375 px, each in a fresh workspace:
 *   1. Channels → the Threads card's "Learn from this account's posts" → one consent → the connected-account import
 *      runs to done (the harness ticker reads the canned pages) → the coverage receipt says what was read.
 *   2. Upload the synthetic X export (tweets.js + note-tweet.js): read in the browser, sent in batches with real
 *      progress, counted by the workspace exactly as sent → delete that import, its posts go with it.
 *   3. Build the voice proposal → Brand Brain review: evidence excerpts load, one quick correction ("This sounds like
 *      me"), approve → one post marked representative in the evidence browser.
 * Checked along the way: the polite live regions of the receipt and of the upload progress, truthful totals (an
 * unknown total stays unknown; images and video are "not analysed"), the X row's reason with the export offered
 * instead, no horizontal scrolling, and axe (WCAG 2.x A/AA) on the import panel.
 *
 * This script starts nothing. It needs, already running:
 *   API  LC_ALL=C <venv>/bin/python scripts/postriff_dev_hosted.py --port 4331 --voice-import-fixture
 *   web  NEXT_PUBLIC_BRAND_BRAIN_V11=1 npm run dev -- -p 3100   (in web/; step 3 is in Brand Brain v1.1)
 * Run:   node web/tests/voice-import-browser.cjs        (Node 24)
 * Env:   RAFII_WEB_URL                     the web app (default http://localhost:3100; loopback only)
 *        RAFII_VOICE_IMPORT_PROVIDER       the connected platform to read (default threads; the harness connects
 *                                          threads and linkedin)
 *        RAFII_VOICE_IMPORT_TICK           wait (default): the harness ticker advances the read (--voice-import-fixture);
 *                                          cron: also call GET /api/cron/worker, as production's cron does. Note that
 *                                          the cron step also runs the harness's other due work for every workspace.
 *        RAFII_CRON_SECRET                 with cron: the harness's cron secret (default: the value
 *                                          scripts/postriff_dev_hosted.py passes, 24 × "d")
 *        RAFII_VOICE_IMPORT_EVIDENCE_DIR   screenshots and result.json (default .token-pilot/reports/voice-import-browser)
 */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const base = (process.env.RAFII_WEB_URL || 'http://localhost:3100').replace(/\/+$/, '');
const target = new URL(base);
if (!['localhost', '127.0.0.1'].includes(target.hostname) || target.origin !== base) {
  throw new Error(`RAFII_WEB_URL must be a plain loopback origin such as http://localhost:3100 (got ${base}). This script runs only against the local dev harness.`);
}
const provider = (process.env.RAFII_VOICE_IMPORT_PROVIDER || 'threads').trim().toLowerCase();
const tickMode = (process.env.RAFII_VOICE_IMPORT_TICK || 'wait').trim().toLowerCase();
if (!['wait', 'cron'].includes(tickMode)) throw new Error(`RAFII_VOICE_IMPORT_TICK must be "wait" or "cron" (got ${tickMode}).`);
const cronSecret = process.env.RAFII_CRON_SECRET || 'd'.repeat(24);
const root = path.resolve(__dirname, '../..');
const out = path.resolve(process.env.RAFII_VOICE_IMPORT_EVIDENCE_DIR || path.join(root, '.token-pilot/reports/voice-import-browser'));
const X_FILES = ['tweets.js', 'note-tweet.js'].map((name) => path.join(__dirname, 'fixtures/voice-import/x/data', name));
const WIDTHS = [1440, 375];
const CONSENT = 'I have the right to use this writing, and Rafii may keep the text for this purpose.';
const NOT_ANALYSED = 'Text is analysed. Images and video are not analysed.';
const tours = Object.fromEntries([...fs.readFileSync(path.join(root, 'web/src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((match) => [match[1], 1]));

const checks = [];
const accessibility = [];
const screenshots = [];
const pageErrors = [];
const record = (width, check) => {
  checks.push({ width, check });
  console.log(`voice-import browser [${width}] ${check}`);
};
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const posts = (n) => `${new Intl.NumberFormat('en').format(n)} ${n === 1 ? 'post' : 'posts'}`;

function client(principal) {
  const headers = { 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Authorization: `Bearer dev:${principal}`, Origin: base };
  return async function api(method, url, body) {
    const response = await fetch(base + url, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(60_000) });
    const text = await response.text();
    if (!response.ok) throw Object.assign(new Error(`${method} ${url} → ${response.status} ${text.slice(0, 400)}`), { status: response.status, body: text });
    return text ? JSON.parse(text) : null;
  };
}

/** Fails at once, and says what to start, when the harness is not there or is not the synthetic one. */
async function preflight() {
  let config;
  try {
    const response = await fetch(`${base}/api/auth/config`, { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new Error(`HTTP ${response.status} (is the API harness on port 4331 running behind the web app?)`);
    config = await response.json();
  } catch (error) {
    throw new Error(
      [
        `No Rafii dev harness answered at ${base}/api/auth/config: ${error?.cause?.code || error.message}.`,
        'This script starts nothing. Start the harness first, then run it again:',
        '  API  LC_ALL=C <venv>/bin/python scripts/postriff_dev_hosted.py --port 4331 --voice-import-fixture',
        '  web  cd web && NEXT_PUBLIC_BRAND_BRAIN_V11=1 npm run dev -- -p 3100',
        'or set RAFII_WEB_URL to the running web app.'
      ].join('\n'),
      { cause: error }
    );
  }
  if (config?.execution !== 'dev-synthetic') throw new Error(`${base} is not the synthetic dev harness (execution: ${config?.execution ?? 'unknown'}). This script runs only there.`);
  for (const file of X_FILES) assert.ok(fs.existsSync(file), `fixture missing: ${path.relative(root, file)}`);
}

/** The receipt, coverage and routes. 404 means voice import is off on this API. */
async function voiceImports(api, ws) {
  try {
    return await api('GET', `${ws}/voice-imports`);
  } catch (error) {
    if (error.status === 404) {
      throw new Error('Voice import is off on this API (GET …/voice-imports answered 404). Start the API harness with the voice import fixture (--voice-import-fixture: POSTRIFF_VOICE_IMPORT=1 and its fixture providers); migration 140 must be applied.', { cause: error });
    }
    throw error;
  }
}

/** One tick of the API's cron step, which reads the pages of a connected-account import. */
async function cronTick() {
  const response = await fetch(`${base}/api/cron/worker`, { headers: { Authorization: `Bearer ${cronSecret}`, 'X-PostRiff-Request': 'founder-alpha' }, signal: AbortSignal.timeout(60_000) });
  if (response.status === 401) throw new Error('GET /api/cron/worker refused the cron secret. Set RAFII_CRON_SECRET to the secret the API harness runs with, or RAFII_VOICE_IMPORT_TICK=wait when the harness ticks voice import itself.');
  if (!response.ok) throw new Error(`GET /api/cron/worker → ${response.status} ${(await response.text()).slice(0, 300)}`);
  return response.json();
}

/** Waits for this account's latest run to end, ticking the cron step for a connected-account read. */
async function finishImport(api, ws, platform, route) {
  const deadline = Date.now() + 120_000;
  let ticks = 0;
  let ticked = false;
  while (Date.now() < deadline) {
    const view = await voiceImports(api, ws);
    const run = (view.imports ?? []).find((item) => item.provider === platform && item.route === route);
    if (run && ['done', 'failed', 'cancelled'].includes(run.status)) {
      assert.equal(run.status, 'done', `the ${platform} import ended "${run.status}" (${run.failure ?? 'no reason given'})`);
      return { run, view };
    }
    if (route === 'official_api' && tickMode === 'cron') {
      const result = await cronTick();
      ticks += 1;
      ticked ||= Boolean(result && Object.prototype.hasOwnProperty.call(result, 'voiceImport'));
      if (ticks >= 3 && !ticked) throw new Error('GET /api/cron/worker has no voiceImport step, so nothing reads the connected account. The API needs the voice import cron wiring (hosted_app: result["voiceImport"] = importer.tick()).');
    }
    await sleep(1_500);
  }
  throw new Error(
    route === 'official_api' && tickMode === 'wait'
      ? `the ${platform} import did not finish within 120 s: nothing advanced it. The harness ticks voice import only when started with --voice-import-fixture; or run with RAFII_VOICE_IMPORT_TICK=cron to call GET /api/cron/worker.`
      : `the ${platform} ${route} import did not finish within 120 s (tick mode: ${tickMode})`
  );
}

const hydrated = async (locator) => {
  await locator.waitFor();
  const end = Date.now() + 30_000;
  while (Date.now() < end) {
    if (await locator.evaluate((el) => Object.keys(el).some((key) => key.startsWith('__reactProps')), undefined, { timeout: Math.max(1, end - Date.now()) }).catch(() => false)) return;
    await sleep(50);
  }
  throw new Error('Hydration timeout');
};

async function shot(page, name) {
  const file = path.join(out, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  screenshots.push(path.relative(root, file));
}

async function noOverflow(page, width, what, scroller) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${what} at ${width}: the page scrolls sideways`);
  if (scroller) assert.equal(await scroller.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), true, `${what} at ${width}: the panel scrolls sideways`);
}

/** axe on the import panel (WCAG 2.x A/AA). Serious and critical findings fail. */
async function axePanel(page, panel, width, moment) {
  await panel.evaluate((el) => el.setAttribute('data-axe-target', 'voice-import'));
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run('[data-axe-target="voice-import"]', { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] }, resultTypes: ['violations'] });
    return result.violations.map((violation) => ({ id: violation.id, impact: violation.impact, help: violation.help, targets: violation.nodes.map((node) => String(Array.isArray(node.target) ? node.target[0] : node.target)) }));
  });
  await panel.evaluate((el) => el.removeAttribute('data-axe-target'));
  accessibility.push({ width, moment, violations });
  const blocking = violations.filter((violation) => ['serious', 'critical'].includes(violation.impact));
  assert.deepEqual(blocking, [], `axe (${moment}, ${width}): serious or critical violations in the import panel: ${JSON.stringify(blocking, null, 2)}`);
}

/** A polite live region inside `scope`, holding `text`. */
async function liveRegion(scope, text, what) {
  const region = scope.locator('[role="status"][aria-live="polite"]').filter({ hasText: text }).first();
  try {
    await region.waitFor({ timeout: 15_000 });
  } catch {
    throw new Error(`${what}: "${text}" is not announced from a polite live region (role=status, aria-live=polite).`);
  }
  return region;
}

/** The one consent: whose writing, how Rafii uses it, and the confirmation (which clears when an answer changes). */
async function consent(scope, start) {
  const step = scope.getByTestId('voice-import-consent');
  assert.equal(await start.isDisabled(), true, 'nothing starts before the consent is complete');
  await step.getByRole('radio', { name: 'Mine', exact: true }).click();
  await step.getByRole('radio', { name: /^Blend into this brand/ }).click();
  await step.getByRole('checkbox', { name: CONSENT, exact: true }).click();
  await step.locator('[role="checkbox"][aria-checked="true"]').waitFor();
  assert.equal(await start.isDisabled(), false, 'one consent is enough to start');
}

/** Same rule as `traitSettled` (lib/voice-import/review.ts): what the review needs before the proposal can be saved. */
function settled(trait) {
  if (trait.decision === 'reject' || trait.status === 'historical') return true;
  if (['insufficient', 'user-defined'].includes(trait.evidenceLevel) || trait.userAuthored) return true;
  const ids = Array.isArray(trait.evidence?.postIds) ? trait.evidence.postIds.filter((id) => typeof id === 'string' && id) : [];
  return Math.max(Number(trait.evidence?.count) || 0, ids.length) > 0;
}

const actionResponse = (page, name) => page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/actions') && response.request().postDataJSON()?.action === name, { timeout: 60_000 });

async function journey(browser, width) {
  const principal = randomUUID();
  const api = client(principal);
  const boot = await api('POST', '/api/auth/verify', { plan: 'studio' });
  const workspaceId = boot.workspaceId;
  const ws = `/api/workspaces/${workspaceId}`;
  let view = await voiceImports(api, ws);
  const official = (view.routes ?? []).find((row) => row.provider === provider)?.official;
  if (!official?.available) {
    throw new Error(`${provider} cannot be read through a connected account on this API (${official?.reason ?? 'not listed'}${official?.detail ? `: ${official.detail}` : ''}). Start the harness with the voice import fixture so ${provider} is an allowed provider (POSTRIFF_VOICE_IMPORT_PROVIDERS).`);
  }
  const xRoute = (view.routes ?? []).find((row) => row.provider === 'x');
  assert.equal(xRoute?.official?.available, false, 'X is never read through its API (billed reads)');
  assert.equal(xRoute?.export?.available, true, 'X can be brought in from its archive');
  // Connect the synthetic account through the harness's own OAuth fixture.
  const started = await api('POST', `${ws}/channels/${provider}/oauth/start`, { capability: 'publish' });
  const connected = await api('POST', `${ws}/channels/${provider}/oauth/complete`, { state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'good-code' });
  assert.ok(connected?.connected && connected.connectionId, `the synthetic ${provider} account connected (${JSON.stringify(connected)})`);
  const activeBefore = (await api('GET', ws)).state.speaker?.activeRevision ?? null;

  const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 960 }, reducedMotion: 'reduce', locale: 'en-US' });
  await context.route('**/*', (route) => (new URL(route.request().url()).origin === base ? route.continue() : route.abort()));
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await context.addInitScript(
    ({ id, workspace, progress }) => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('postriff-workspace', workspace);
      const seen = JSON.stringify({ completed: progress, dismissed: progress, nudged: progress });
      localStorage.setItem('postriff-onboarding', seen);
      localStorage.setItem(`postriff-onboarding:${id}`, seen);
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style');
        style.textContent = '.tsqd-parent-container,nextjs-portal{display:none!important}';
        document.head.appendChild(style);
      });
    },
    { id: principal, workspace: workspaceId, progress: tours }
  );
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  page.on('pageerror', (error) => pageErrors.push({ width, message: error.message }));
  page.on('console', (message) => {
    if (message.type() === 'error') console.log(`[${width}] browser console error: ${message.text().slice(0, 300)}`);
  });

  try {
    // 1. From the account's card on Channels, one consent, then the connected-account import runs to done.
    await page.goto(`${base}/app/channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const entry = page.getByTestId(`voice-import-entry-${provider}`);
    try {
      await hydrated(entry);
    } catch {
      throw new Error(`The ${provider} card on Channels has no "Learn from this account’s posts" control (data-testid voice-import-entry-${provider}).`);
    }
    await entry.click();
    const sheet = page.getByRole('dialog', { name: /^Learn from this account/ });
    await sheet.waitFor();
    const panel = sheet.getByTestId('voice-import-panel');
    await panel.waitFor();
    const summary = panel.getByTestId('voice-import-summary');
    assert.equal(await summary.getAttribute('role'), 'status');
    assert.equal(await summary.getAttribute('aria-live'), 'polite');
    await summary.getByText('No posts retrieved yet.', { exact: true }).waitFor();
    await summary.getByText(NOT_ANALYSED, { exact: true }).waitFor();
    const xRow = panel.getByTestId('voice-import-platform-x');
    await xRow.getByText(/X charges for each post an app reads/).waitFor();
    await xRow.getByRole('button', { name: 'Upload export: X', exact: true }).waitFor();
    assert.equal(await xRow.getByRole('button', { name: /^Connect and import/ }).count(), 0, 'an unavailable route is never offered as a button');
    const connectFlow = panel.getByTestId(`voice-import-connect-${provider}`);
    await connectFlow.waitFor();
    const start = panel.getByTestId(`voice-import-start-${provider}`);
    await consent(connectFlow, start);
    const scroller = sheet.locator('.overflow-y-auto').first();
    await noOverflow(page, width, 'consent', scroller);
    await shot(page, `consent-${width}`);
    await axePanel(page, panel, width, 'consent step open');
    record(width, `Channels card opened the import panel on ${provider}; X says why its API is not used and offers the export; one consent enables the start; axe clean`);

    await start.click();
    const receipt = panel.getByTestId(`voice-import-receipt-${provider}`);
    await receipt.waitFor();
    const { view: afterRead } = await finishImport(api, ws, provider, 'official_api');
    await receipt.getByText('Finished', { exact: true }).waitFor({ timeout: 30_000 });
    const account = (afterRead.coverage?.accounts ?? []).find((item) => item.provider === provider);
    assert.ok(account && account.retrieved > 0, `the receipt counts the ${provider} posts (${JSON.stringify(account)})`);
    const totalLine = account.totalKnown ? `${posts(account.retrieved)} retrieved; the source lists no more.` : `${posts(account.retrieved)} retrieved; the platform does not say how many exist.`;
    await liveRegion(receipt, totalLine, 'receipt total');
    await liveRegion(receipt, 'Finished', 'run status');
    await summary.getByText(NOT_ANALYSED, { exact: true }).waitFor();
    await panel.getByTestId('voice-import-states').getByText(/^Retrieved · (done|partly)$/).waitFor();
    if (account.moreRemaining === true) await receipt.getByText('More posts exist that were not read.', { exact: true }).waitFor();
    await noOverflow(page, width, 'receipt', scroller);
    await receipt.scrollIntoViewIfNeeded();
    await shot(page, `receipt-${width}`);
    await axePanel(page, panel, width, 'receipt after the read');
    record(width, `Connected-account import ran to done; the receipt counts ${account.retrieved} posts, ${account.totalKnown ? 'says the source lists no more' : 'says the platform gives no total'}, and says images and video are not analysed; announced politely; axe clean`);

    // 2. The X export: read in the browser, sent with real progress, counted exactly, then deleted with its posts.
    await xRow.getByRole('button', { name: 'Upload export: X', exact: true }).click();
    const upload = panel.getByTestId('voice-import-upload-x');
    await upload.waitFor();
    await upload.locator('input[type="file"]:not([webkitdirectory])').setInputFiles(X_FILES);
    const readyLine = await liveRegion(upload, 'Posts ready to send:', 'upload summary');
    const ready = Number(((await readyLine.getByText(/^Posts ready to send: \d+$/).textContent()) ?? '').match(/\d+/)?.[0]);
    assert.ok(ready > 0, 'the browser found posts in the X export');
    await upload.getByLabel('Account name', { exact: true }).fill('synthetic_x_account');
    const send = upload.getByTestId('voice-import-send-x');
    await consent(upload, send);
    await send.click();
    await liveRegion(upload, 'All posts were sent. The receipt now counts them.', 'upload end');
    await upload.getByText(`Posts sent: ${ready} / ${ready}`, { exact: true }).waitFor();
    await noOverflow(page, width, 'upload', scroller);
    await shot(page, `upload-${width}`);
    await upload.getByRole('button', { name: 'Done', exact: true }).click();
    const { view: afterUpload } = await finishImport(api, ws, 'x', 'platform_export');
    const xAccount = (afterUpload.coverage?.accounts ?? []).find((item) => item.provider === 'x');
    assert.equal(xAccount?.retrieved, ready, 'the workspace counts each post the browser sent, once');
    const xReceipt = panel.getByTestId('voice-import-receipt-x');
    await xReceipt.getByText('Finished', { exact: true }).waitFor({ timeout: 30_000 });
    await xReceipt.getByRole('button', { name: 'Delete import', exact: true }).click();
    const confirm = page.getByRole('alertdialog');
    await confirm.getByRole('button', { name: 'Delete import and posts', exact: true }).click();
    const removed = page.locator('[data-sonner-toast]').filter({ hasText: /Import deleted\. Posts removed: \d+/ });
    await removed.waitFor();
    assert.equal(Number(((await removed.textContent()) ?? '').match(/Posts removed: (\d+)/)?.[1]), ready, 'deleting the import removed exactly the posts it supplied');
    await xReceipt.waitFor({ state: 'detached' });
    view = await voiceImports(api, ws);
    assert.equal((view.imports ?? []).some((item) => item.provider === 'x'), false, 'the X run is gone');
    assert.equal((view.coverage?.accounts ?? []).some((item) => item.provider === 'x'), false, 'no X posts remain');
    record(width, `X export: ${ready} posts read in the browser and sent with real progress (${ready} / ${ready}); the workspace counted ${ready}; deleting the import removed its ${ready} posts`);

    // 3. Build the proposal, review it in Brand Brain, correct one trait, approve, then mark one post.
    const build = panel.getByTestId('voice-import-build');
    await build.click();
    await page.locator('[data-sonner-toast]').filter({ hasText: /Proposal built\./ }).waitFor();
    let state = (await api('GET', ws)).state;
    assert.equal(state.speaker?.provisional?.analysisMethod, 'voice_import', 'a proposal built from the imported posts waits for review');
    assert.equal(state.speaker?.activeRevision ?? null, activeBefore, 'building a proposal changes nothing in use');
    await panel.getByRole('link', { name: 'Review the proposed voice', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/app/workspace/brand' && url.searchParams.get('step') === 'review');
    const brain = page.getByTestId('brand-brain');
    try {
      // The first visit compiles the Brand page in the dev server.
      await brain.waitFor({ timeout: 120_000 });
    } catch {
      throw new Error('The Brand page is the legacy view: the review with quick corrections is in Brand Brain v1.1. Restart the web app with NEXT_PUBLIC_BRAND_BRAIN_V11=1 and run again.');
    }
    const review = page.getByTestId('bb-step-review');
    await review.waitFor();
    await review.getByTestId('bb-import-header').waitFor();
    await review.getByText('Learned from your imported posts', { exact: true }).waitFor();
    const traits = state.speaker.provisional.dimensions ?? [];
    assert.ok(traits.length > 0, 'the proposal has traits');
    const cited = traits.find((trait) => (trait.evidence?.postIds ?? []).length > 0) ?? traits[0];
    const card = review.getByTestId(`bb-trait-${cited.id}`);
    if ((cited.evidence?.postIds ?? []).length > 0) {
      await card.getByText('Why Rafii thinks this', { exact: true }).click();
      await card.getByTestId('trait-evidence').locator('blockquote').first().waitFor({ timeout: 30_000 });
    }
    const corrected = actionResponse(page, 'brand_brain_trait_correct');
    await card.getByRole('button', { name: 'This sounds like me', exact: true }).click();
    const correction = await corrected;
    assert.ok(correction.ok(), await correction.text());
    await card.locator('button[aria-pressed="true"]', { hasText: 'This sounds like me' }).waitFor();
    state = (await api('GET', ws)).state;
    assert.equal(state.speaker.provisional.dimensions.find((trait) => trait.id === cited.id)?.decision, 'accept', 'the correction is stored on the proposal');
    await noOverflow(page, width, 'review');
    await shot(page, `review-${width}`);
    record(width, `Brand Brain review of the import proposal: evidence excerpts load, "This sounds like me" stored on trait ${cited.id}`);

    // Traits that cite no posts must be ruled out before saving (the review's own rule).
    for (const trait of state.speaker.provisional.dimensions.filter((item) => !settled(item))) {
      const ruled = actionResponse(page, 'brand_brain_trait_correct');
      await review.getByTestId(`bb-trait-${trait.id}`).getByRole('button', { name: 'Someone else wrote this', exact: true }).click();
      assert.ok((await ruled).ok());
      record(width, `Trait ${trait.id} cites no posts, so it was marked "Someone else wrote this" before saving`);
    }
    const save = page.getByTestId('bb-save-proposal');
    await page.waitForFunction(() => !document.querySelector('[data-testid="bb-save-proposal"]')?.disabled, undefined, { timeout: 30_000 });
    await save.click();
    await page.getByTestId('bb-step-preview').waitFor();
    await page.getByTestId('bb-approve').click();
    const approval = page.getByRole('alertdialog');
    await approval.getByRole('button', { name: 'Confirm approval', exact: true }).click();
    await approval.waitFor({ state: 'hidden' });
    state = (await api('GET', ws)).state;
    assert.ok((state.speaker?.activeRevision ?? 0) > (activeBefore ?? 0), 'the owner approval made the imported voice active');
    const active = state.speaker.revisions.find((item) => item.revision === state.speaker.activeRevision);
    assert.equal(active?.profile?.analysisMethod, 'voice_import');
    record(width, 'Owner approved the import proposal; it is the active voice revision');

    await page.getByRole('tab', { name: 'Sources & permissions', exact: true }).click();
    const ledger = page.getByTestId('voice-import-panel');
    const ledgerReceipt = ledger.getByTestId(`voice-import-receipt-${provider}`);
    await ledgerReceipt.getByRole('button', { name: 'Show posts', exact: true }).click();
    const evidence = ledgerReceipt.getByTestId('voice-import-evidence');
    const post = evidence.locator('li', { has: page.getByRole('button', { name: 'Representative', exact: true }) }).first();
    await post.waitFor({ timeout: 30_000 });
    const marked = page.waitForResponse((response) => response.request().method() === 'POST' && /\/voice-imports\/posts\/[^/]+$/.test(new URL(response.url()).pathname), { timeout: 30_000 });
    await post.getByRole('button', { name: 'Representative', exact: true }).click();
    const markedResponse = await marked;
    assert.ok(markedResponse.ok(), await markedResponse.text());
    await post.locator('button[aria-pressed="true"]', { hasText: 'Representative' }).waitFor();
    assert.equal((await markedResponse.json())?.post?.label, 'representative');
    await noOverflow(page, width, 'evidence browser');
    await shot(page, `evidence-${width}`);
    await axePanel(page, ledger, width, 'evidence browser open in Brand Brain');
    record(width, 'Evidence browser in Sources & permissions: one post marked representative through the posts route; axe clean');
  } catch (error) {
    await page.screenshot({ path: path.join(out, `failure-${width}.png`), fullPage: true }).catch(() => {});
    console.log((await page.locator('body').innerText().catch(() => '')).slice(-3000));
    throw error;
  } finally {
    await context.close();
  }
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  await preflight();
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of WIDTHS) await journey(browser, width);
  } finally {
    await browser.close();
  }
  assert.deepEqual(pageErrors, [], 'no page errors');
  const report = { status: 'PASS', base, widths: WIDTHS, provider, tickMode, execution: 'local dev harness; real web app and hosted handlers; synthetic identity, provider history and export files; no mocked API responses', checks, accessibility, screenshots, pageErrors };
  fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: 'PASS', checks: checks.length, evidence: path.relative(root, out) }));
})().catch((error) => {
  try {
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ status: 'FAIL', base, error: String(error?.stack || error), checks, accessibility, screenshots, pageErrors }, null, 2));
  } catch {
    /* the report directory is not writable: the console still has the error */
  }
  console.error(error?.stack || error);
  process.exitCode = 1;
});
