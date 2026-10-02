/**
 * RAFII Product Growth v2 — real local Next/API/PostgreSQL journeys (PRD §15.1 group C; AC06–AC10, AC37, AC39).
 * Identity, models and providers are the dev harness's synthetic ones; nothing reaches a provider or charges.
 *
 * Journeys: the first week (Post Doctor continuation), business results, relationship follow-ups, Signature Series,
 * visual packs, raw source intake, the Creator credit confirmation (recorded not_run with its reason) and the Pricing v2
 * public page. Each runs at 1440 desktop, 768 tablet and 390 phone, with a Traditional Chinese case, a keyboard-only
 * step, axe (no serious or critical issue) and no horizontal scroll. Prerequisite data is made through the real API
 * routes only (never by writing to the database); every result says what was checked against the API's read-back.
 *
 *   RAFII_GROWTH_WEB_URL=http://127.0.0.1:4443 RAFII_GROWTH_API_URL=http://127.0.0.1:4442 RAFII_GROWTH_PRICING_CATALOG=v2 \
 *     node web/tests/growth-v2-browser.cjs --out=docs/design/rafii-product-growth/evidence/ci-browser [--only=results,series]
 *
 * Harness: RAFII_WEEKLY_OPERATOR_ENABLED=1 RAFII_FIRST_WEEK_ENABLED=1 … python scripts/postriff_dev_hosted.py --growth-fixture …
 * (the slice flags as in .github/workflows/rafii-browser.yml); the web dev server with NEXT_PUBLIC_PRICING_CATALOG=v2.
 */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync, readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const base = process.env.RAFII_GROWTH_WEB_URL || 'http://127.0.0.1:4443';
// The harness API itself: the signed-URL PUT of a source upload is forwarded to its dev-synthetic bucket.
const apiOrigin = process.env.RAFII_GROWTH_API_URL || 'http://127.0.0.1:4442';
// What the web dev server was started with; the Pricing v2 page is checked only when it says v2.
const pricingCatalog = (process.env.RAFII_GROWTH_PRICING_CATALOG || '').trim().toLowerCase();
const outArg = process.argv.find((a) => a.startsWith('--out='));
const out = resolve(process.cwd(), outArg ? outArg.slice(6) : 'docs/design/rafii-product-growth/evidence/ci-browser');
const onlyArg = process.argv.find((a) => a.startsWith('--only='));
const only = onlyArg ? onlyArg.slice(7).split(',').filter(Boolean) : [];
const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'phone', width: 390, height: 844 }
];
// The program journeys' language and zone per viewport: every journey has a Traditional Chinese run (tablet).
const LANGUAGE = { desktop: 'en', tablet: 'zh-Hant', phone: 'en' };
const ZONE = { desktop: 'America/New_York', tablet: 'Asia/Hong_Kong', phone: 'Europe/London' };
// Page tours this run never needs offered ("New to …?" toasts would only cover the controls under test).
const PAGE_TOURS = ['analytics-tips', 'inbox-tips', 'library-tips', 'ideas-tips'];
const DRAFT_EN = 'Most adult beginners quit piano because they practise pieces, not skills. Five minutes on one skill first changes that.';
const DRAFT_ZH = '很多成年初學者放棄鋼琴，是因為只練曲子、不練技巧。先花五分鐘練一個技巧，情況就會不同。';
const results = [];
const failures = [];
const warnings = [];
const journeys = [];
let C = null;   // the product's own EN/zh-Hant copy, loaded from the slices' pure modules

function record(scenario, passed, extra = {}) {
  results.push({ scenario, passed, ...extra });
  if (!passed) failures.push(scenario);
}

async function axeCheck(page, label) {
  const source = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
  await page.addScriptTag({ content: source });
  const found = await page.evaluate(async () => {
    // The Next.js development indicator (`nextjs-portal`) is a dev-server tool, not product UI.
    const report = await window.axe.run({ exclude: [['nextjs-portal']] }, { resultTypes: ['violations'] });
    return report.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, targets: v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ').slice(0, 300) }));
  });
  record(`axe: no serious/critical violations — ${label}`, found.length === 0, { violations: found });
}

async function noHorizontalScroll(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  record(`layout: no horizontal scroll — ${label}`, overflow <= 1, { overflowPx: overflow });
}

async function context(browser, viewport, principal, options = {}) {
  const ctx = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    reducedMotion: 'reduce',
    ...(options.locale ? { locale: options.locale } : {}),
    ...(options.timezoneId ? { timezoneId: options.timezoneId } : {})
  });
  await ctx.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
  // The anonymous Post Doctor allows three checks a day per client address (anti-abuse; the platform edge sets
  // X-Forwarded-For in production). Each anonymous run here is its own synthetic visitor (TEST-NET-2 address).
  if (options.visitor) await ctx.setExtraHTTPHeaders({ 'X-Forwarded-For': `198.51.100.${options.visitor}` });
  await ctx.addInitScript(({ id, nudged }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged }));
  }, { id: principal, nudged: options.quiet ? Object.fromEntries(PAGE_TOURS.map((tour) => [tour, 1])) : {} });
  if (options.quiet) {
    // The dev server's floating indicator sits over the bottom-left corner of phone sheets; it is not product UI.
    await ctx.addInitScript(() => {
      const add = () => {
        const style = document.createElement('style');
        style.textContent = 'nextjs-portal{display:none!important}';
        document.head.appendChild(style);
      };
      if (document.head) add();
      else document.addEventListener('DOMContentLoaded', add, { once: true });
    });
  }
  await ctx.route('**/*', (route) => (new URL(route.request().url()).origin === base ? route.continue() : route.abort()));
  return ctx;
}

function watch(page) {
  page.setDefaultTimeout(25000);
  page.on('pageerror', (error) => failures.push(`page error: ${error.message}`));
  page.on('console', (message) => {
    // Development builds log extra diagnostics; console errors are kept as evidence, page errors and 5xx fail the run.
    if (message.type() === 'error' && !/Failed to load resource/.test(message.text())) warnings.push(`console: ${message.text().slice(0, 200)}`);
  });
  page.on('response', (response) => {
    if (response.url().startsWith(base + '/api/') && response.status() >= 500) failures.push(`network ${response.status()} ${response.url()}`);
  });
}

let visitors = 0;

async function firstWeekJourney(browser, viewport, draft, language) {
  const principal = randomUUID();
  const ctx = await context(browser, viewport, principal, { visitor: (visitors += 1) });
  const page = await ctx.newPage();
  watch(page);
  const label = `${viewport.name}/${language}`;
  // 1. Anonymous Post Doctor: nothing is kept before consent.
  await page.goto(base + '/post-doctor');
  await page.getByRole('textbox', { name: 'Your draft' }).fill(draft);
  await page.getByLabel('Draft language').selectOption(language === 'zh-Hant' ? 'zh-HK' : 'en');
  await page.getByRole('checkbox', { name: 'Allow analysis of my public draft' }).check();
  await page.getByRole('button', { name: 'Check my draft' }).click();
  await page.getByRole('button', { name: 'Continue with this draft' }).waitFor();
  const before = await page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith('rafii.continue')));
  record(`AC06 nothing kept before consent — ${label}`, before.length === 0, { keys: before });
  await page.getByRole('textbox', { name: 'Your draft' }).fill(draft + (language === 'zh-Hant' ? '今晚就開始。' : ' Start tonight.'));
  await page.getByRole('button', { name: 'Continue with this draft' }).click();
  const dialog = page.getByRole('dialog', { name: 'Continue with this draft' });
  await dialog.waitFor();
  await page.screenshot({ path: resolve(out, `${label.replace('/', '-')}-1-consent.png`) });
  await dialog.getByRole('button', { name: 'Keep it and sign up' }).click();
  // 2. Sign-up redirects a signed-in dev identity straight to `next`; only the nonce is in the URL.
  await page.waitForURL(/\/app\/weekly/);
  const url = page.url();
  record(`AC06 URL carries only an opaque nonce — ${label}`, !url.includes(encodeURIComponent(draft.slice(0, 10))) && !url.includes('piano') && !/%E5|%E9/.test(url), { url: url.replace(/continue=[^&]+/, 'continue=…') });
  const importRegion = page.getByRole('region', { name: 'Import your Post Doctor draft' });
  await importRegion.waitFor();
  await page.screenshot({ path: resolve(out, `${label.replace('/', '-')}-2-import.png`) });
  await importRegion.getByRole('button', { name: 'Import into this workspace' }).click();
  await importRegion.waitFor({ state: 'detached' });
  const kept = await page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith('rafii.continue')));
  record(`AC06 browser copy cleared after import — ${label}`, kept.length === 0, { keys: kept });
  record(`AC06 URL cleaned after reading the nonce — ${label}`, !page.url().includes('continue='), {});
  // 3. Missing context only, then explicit acceptance.
  const purpose = page.getByLabel('What should these posts do?');
  if (await purpose.count()) {
    await purpose.fill(language === 'zh-Hant' ? '招收十一月班' : 'Fill the November cohort');
    await page.getByLabel('Who are they for?').fill(language === 'zh-Hant' ? '成年鋼琴初學者' : 'Adult piano beginners');
    await page.getByRole('button', { name: 'Continue' }).click();
  }
  await page.getByRole('button', { name: 'Accept this draft' }).click();
  // 4. Plan without a connected account, commit, write the rest yourself, hand off.
  await page.getByRole('button', { name: 'Plan my week' }).click();
  await page.getByRole('button', { name: /Commit these \d posts/ }).click();
  // Wait for the committed week before counting the posts to write (counting at once raced the commit and saw none).
  await page.getByText('Change the committed posts').waitFor();
  const writes = page.getByRole('textbox', { name: 'Write it yourself' });
  for (let left = await writes.count(), i = 0; left > 0; i += 1) {
    await writes.first().fill(language === 'zh-Hant' ? `第${i + 2}篇：一個練習技巧。` : `Post ${i + 2}: one practice skill.`);
    await page.getByRole('button', { name: 'Save this post' }).first().click();
    await until(async () => (await writes.count()) < left, 'the written post is saved as a draft');
    left = await writes.count();
  }
  await page.screenshot({ path: resolve(out, `${label.replace('/', '-')}-3-week.png`), fullPage: true });
  await axeCheck(page, `first week ${label}`);
  await noHorizontalScroll(page, `first week ${label}`);
  // "I posted it" stays beside a recorded handoff (with Undo), so each post's own button is used once; the server's
  // answer to each handoff is checked, so a refusal says why.
  const used = page.getByRole('button', { name: 'I posted it' });
  const handoffs = await used.count();
  for (let i = 0; i < handoffs; i += 1) {
    const answered = page.waitForResponse((response) => /\/first-week\/slots\/[^/]+\/handoff$/.test(new URL(response.url()).pathname), { timeout: 20000 }).catch(() => null);
    await used.nth(i).click();
    const response = await answered;
    const body = response ? await response.json().catch(() => null) : null;
    const toasts = await page.locator('[data-sonner-toast]').allInnerTexts().catch(() => []);
    if (!response || !response.ok()) {
      await page.screenshot({ path: resolve(out, `FAIL-first-week-${label.replace('/', '-')}.png`), fullPage: true }).catch(() => undefined);
      throw new Error(`handoff ${i + 1}: ${response ? response.status() : 'no request'} ${JSON.stringify(body).slice(0, 300)} toasts ${JSON.stringify(toasts).slice(0, 300)}`);
    }
    const slots = (body?.slots ?? []).map((s) => ({ status: s.status, handoff: s.handoff && { state: s.handoff.state, stale: Boolean(s.handoff.stale) } }));
    // The last handoff completes the week, and the panel then shows the delivered summary instead of each post.
    const recorded = async () => (await page.getByText('You posted it yourself.').count()) > i || (body?.complete === true && (await page.getByText('Your first week is delivered').count()) > 0);
    await until(recorded, 'the handoff is recorded').catch(async (error) => {
      await page.screenshot({ path: resolve(out, `FAIL-first-week-${label.replace('/', '-')}.png`), fullPage: true }).catch(() => undefined);
      throw new Error(`${error.message}; server step ${body?.step}, delivered ${body?.delivered}/${body?.committed}, slots ${JSON.stringify(slots)}, toasts ${JSON.stringify(toasts).slice(0, 200)}`);
    });
  }
  await page.getByText('Your first week is delivered').waitFor();
  const view = await page.evaluate(async () => {
    const id = localStorage.getItem('postriff-dev-principal');
    const workspaces = await (await fetch('/api/workspaces', { headers: { Authorization: `Bearer dev:${id}`, 'X-PostRiff-Request': 'founder-alpha' } })).json();
    const wid = workspaces.workspaces[0].workspaceId;
    return (await fetch(`/api/workspaces/${wid}/first-week`, { headers: { Authorization: `Bearer dev:${id}`, 'X-PostRiff-Request': 'founder-alpha' } })).json();
  });
  record(`AC10 delivered by assisted handoff, never "published" — ${label}`, view.complete === true && view.slots.every((s) => s.status !== 'published'),
    { delivered: view.delivered, committed: view.committed, step: view.step });
  await page.screenshot({ path: resolve(out, `${label.replace('/', '-')}-4-delivered.png`) });
  await ctx.close();
}

async function blockedStorage(browser) {
  const ctx = await context(browser, VIEWPORTS[0], randomUUID(), { visitor: (visitors += 1) });
  await ctx.addInitScript(() => {
    Object.defineProperty(window, 'sessionStorage', { get() { throw new DOMException('blocked', 'SecurityError'); } });
  });
  const page = await ctx.newPage();
  watch(page);
  await page.goto(base + '/post-doctor');
  await page.getByRole('textbox', { name: 'Your draft' }).fill(DRAFT_EN);
  await page.getByRole('checkbox', { name: 'Allow analysis of my public draft' }).check();
  await page.getByRole('button', { name: 'Check my draft' }).click();
  await page.getByRole('button', { name: 'Continue with this draft' }).click();
  await page.getByRole('button', { name: 'Keep it and sign up' }).click();
  await page.getByRole('alert').filter({ hasText: 'blocked temporary storage' }).waitFor();
  record('AC07 blocked storage keeps nothing and says so', page.url().includes('/post-doctor'), {});
  await ctx.close();
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* Program journeys: shared helpers                                                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

/** The slices' own words (English and Traditional Chinese), from the same pure modules the app renders. */
async function loadCopy() {
  const load = (path) => import(pathToFileURL(resolve(__dirname, '../src', path)).href);
  const [results, relationships, series, visualPack, intake, proof, briefs] = await Promise.all([
    load('features/growth/results/present.ts'),
    load('lib/growth-v2/relationships-model.ts'),
    load('features/library/series/series-copy.ts'),
    load('lib/growth-v2/visual-pack-logic.ts'),
    load('lib/growth-v2/source-uploads-model.ts'),
    load('lib/growth-v2/proof-present.ts'),
    load('lib/growth-v2/briefs-present.ts')
  ]);
  const both = (make) => ({ en: make('en'), 'zh-Hant': make('zh-Hant') });
  return {
    results: results.COPY,
    followUp: both(relationships.followUpCopy),
    series: series.COPY,
    visualPack: both(visualPack.copyFor),
    intake: intake.COPY,
    proof: both(proof.proofCopy),
    brief: both(briefs.briefCopy),
    fill: series.fill
  };
}

const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const fileLabel = (label) => label.replaceAll('/', '-');
const shot = (page, name, fullPage = false) => page.screenshot({ path: resolve(out, `${name}.png`), fullPage }).catch(() => undefined);

/** The harness API as this synthetic principal (same session rules as the app: bearer + guard header + origin). */
function apiFor(ctx, principal) {
  const headers = { Authorization: `Bearer dev:${principal}`, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
  async function call(method, path, data) {
    const response = await ctx.request.fetch(base + path, { method, headers, data, failOnStatusCode: false, timeout: 90000 });
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      /* not JSON */
    }
    return { status: response.status(), body, text };
  }
  async function must(method, path, data) {
    const answer = await call(method, path, data);
    if (answer.status >= 400) throw new Error(`${method} ${path} → ${answer.status} ${answer.text.slice(0, 300)}`);
    return answer.body;
  }
  async function bytes(path) {
    const response = await ctx.request.get(base + path, { headers, failOnStatusCode: false, timeout: 90000 });
    if (!response.ok()) throw new Error(`GET ${path} → ${response.status()}`);
    return response.body();
  }
  return { call, must, bytes };
}

async function until(check, message, timeout = 30000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeout) {
    last = await check();
    if (last) return last;
    await new Promise((done) => setTimeout(done, 400));
  }
  throw new Error(`timed out: ${message}`);
}

/**
 * Keyboard only: start a few stops earlier in the page's own Tab order, press Tab until `target` has focus, and return
 * how many presses it took. Fails when the target can't be reached by Tab at all.
 */
async function tabTo(page, target, { back = 4, max = 30 } = {}) {
  let started = null;
  for (let attempt = 0; ; attempt += 1) {
    try {
      await target.waitFor({ state: 'visible' });
      await target.scrollIntoViewIfNeeded();
      const handle = await target.elementHandle();
      started = await page.evaluate(({ element, back }) => {
        const focusable = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
        const root = element.closest('[role=dialog]') || document;
        const all = [...root.querySelectorAll(focusable)].filter((node) => node.tabIndex >= 0 && node.getClientRects().length > 0
          && getComputedStyle(node).visibility !== 'hidden' && !node.closest('[inert]'));
        const index = all.indexOf(element);
        if (index < 1) return index === 0 ? 'first' : null;
        all[Math.max(0, index - back)].focus();
        return 'ok';
      }, { element: handle, back });
      break;
    } catch (error) {
      // A re-render between finding the control and focusing near it: find it again (twice at most).
      if (attempt >= 2 || !/not attached|detached|Execution context was destroyed/i.test(String(error.message))) throw error;
      await page.waitForTimeout(500);
    }
  }
  if (started === null) throw new Error('keyboard: the target is not in the Tab order');
  if (started === 'first') await page.keyboard.press('Shift+Tab');
  for (let presses = 0; presses <= max; presses += 1) {
    if (await target.evaluate((node) => node === document.activeElement)) return presses;
    await page.keyboard.press('Tab');
  }
  throw new Error(`keyboard: Tab never reached ${await target.evaluate((node) => node.outerHTML.slice(0, 160))}`);
}

/**
 * Wait until `locator`'s element survives a second: the preferences provider re-keys the app when the person's saved
 * language or the browser's zone arrives, which remounts the page once after it first appears.
 */
async function stable(page, locator, ms = 1000) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const handle = await locator.elementHandle();
    await page.waitForTimeout(ms);
    if (await handle.evaluate((node) => node.isConnected).catch(() => false)) return;
  }
  throw new Error('the page kept re-rendering');
}

/** From the current focus, Tab forward until `target` has focus (a form's own submit button). */
async function tabForward(page, target, max = 12) {
  for (let presses = 0; presses <= max; presses += 1) {
    if (await target.evaluate((node) => node === document.activeElement)) return presses;
    await page.keyboard.press('Tab');
  }
  throw new Error(`keyboard: Tab never reached ${await target.evaluate((node) => node.outerHTML.slice(0, 160))}`);
}

/** A fresh synthetic principal and workspace for one journey run; zh-Hant runs save the language preference first. */
async function setup(browser, viewport, language) {
  const principal = randomUUID();
  // Every browser is en-US: a zh-Hant run reads Traditional Chinese only because the person's saved language says so.
  const ctx = await context(browser, viewport, principal, { quiet: true, timezoneId: ZONE[viewport.name], locale: 'en-US' });
  ctx.setDefaultNavigationTimeout(180000);
  const api = apiFor(ctx, principal);
  const boot = await api.must('POST', '/api/auth/verify', { plan: 'studio' });
  const wid = boot.workspaceId;
  if (language === 'zh-Hant') {
    const saved = await api.must('PATCH', '/api/me', { locale: 'zh-Hant' });
    assert.equal(saved.preferences.locale, 'zh-Hant');
  }
  const features = (await api.must('GET', `/api/workspaces/${wid}/growth-features`)).features;
  const page = await ctx.newPage();
  watch(page);
  page.setDefaultNavigationTimeout(180000);   // a development server compiles each page on its first visit
  return { principal, ctx, page, wid, features, ...api };
}

/** One journey at one viewport: its own workspace, failure evidence, and a pass/fail row for the summary table. */
async function runJourney(journey, browser, viewport, run) {
  const language = LANGUAGE[viewport.name];
  const label = `${journey}/${viewport.name}/${language}`;
  const entry = { journey, viewport: `${viewport.name} ${viewport.width}`, language, status: 'fail' };
  journeys.push(entry);
  const before = failures.length;
  const started = Date.now();
  let env = null;
  try {
    env = await setup(browser, viewport, language);
    await run(env, { label, viewport, language, zh: language === 'zh-Hant', entry });
  } catch (error) {
    failures.push(`${label}: ${String(error.message).split('\n')[0].slice(0, 400)}`);
    entry.error = String(error.message).slice(0, 900);
    if (env?.page) {
      entry.url = env.page.url();
      entry.alerts = (await env.page.getByRole('alert').allInnerTexts().catch(() => [])).map((text) => text.slice(0, 200)).slice(0, 5);
      await shot(env.page, `FAIL-${fileLabel(label)}`, true);
    }
  } finally {
    entry.seconds = Math.round((Date.now() - started) / 1000);
    entry.status = failures.length === before ? 'pass' : 'fail';
    if (env?.ctx) await env.ctx.close().catch(() => undefined);
  }
}

const want = (name) => only.length === 0 || only.includes(name);

/* ------------------------------------------------------------------------------------------------------------------ */
/* 1. Business results (Analytics → Business results)                                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

async function resultsJourney(env, { label, zh, entry }) {
  const { page, wid, must, ctx } = env;
  const copy = C.results[zh ? 'zh-Hant' : 'en'];
  await page.goto(base + '/app/analytics');
  const region = page.getByRole('region', { name: copy.title, exact: true });
  await region.waitFor({ timeout: 120000 });
  await stable(page, region);
  await region.scrollIntoViewIfNeeded();
  await region.getByText(copy.ledger.empty, { exact: true }).waitFor();

  // Keyboard only: Tab to "Record a result", Enter opens the form; the form is filled and saved from the keyboard.
  const recordButton = region.getByRole('button', { name: copy.ledger.record, exact: true });
  const presses = await tabTo(page, recordButton);
  await page.keyboard.press('Enter');
  const form = page.getByRole('dialog', { name: copy.form.title, exact: true });
  await form.waitFor();
  // A select wrapped in its <label> carries its current option in its name ("What happened Lead"): match the label part.
  await form.getByLabel(copy.form.type).selectOption('booking');
  await form.getByLabel(copy.form.amount, { exact: true }).fill('45.50');
  await form.getByLabel(copy.form.currency, { exact: true }).fill('USD');
  const note = zh ? '預約了十一月班的試堂' : 'Booked a trial lesson for the November cohort';
  await form.getByLabel(copy.form.note, { exact: true }).fill(note);
  const save = form.getByRole('button', { name: copy.form.save, exact: true });
  const submitPresses = await tabForward(page, save);
  await page.keyboard.press('Enter');
  await form.waitFor({ state: 'hidden' });
  record(`results: keyboard opens, fills and saves a declaration — ${label}`, true, { tabPresses: presses, submitPresses });

  const ledger = region.getByRole('list', { name: copy.tabs.ledger, exact: true });
  const row = ledger.getByRole('listitem').filter({ hasText: note });
  await row.waitFor();
  await row.getByText(copy.classes.user_declared, { exact: true }).waitFor();
  record(`results: the declaration is listed under "${copy.classes.user_declared}" with its amount — ${label}`, (await row.innerText()).includes('45.50'));
  const cards = region.getByRole('list', { name: copy.title, exact: true }).getByRole('listitem');
  const declaredCard = cards.filter({ hasText: copy.classes.user_declared });
  await declaredCard.getByText(copy.count(1, 'booking'), { exact: true }).waitFor();
  const connectedCard = cards.filter({ hasText: copy.classes.first_party_reported });
  const platformCard = cards.filter({ hasText: copy.classes.provider_native });
  const separate = (await connectedCard.getByText(copy.noResults, { exact: true }).count()) === 1 && (await platformCard.getByText(copy.notConnected, { exact: true }).count()) === 1
    && !(await connectedCard.innerText()).includes('45.50') && !(await platformCard.innerText()).includes('45.50');
  let summary = await must('GET', `/api/workspaces/${wid}/results/summary`);
  const blended = Object.keys(summary).filter((key) => /total|combined|sum/i.test(key));
  record(`results: provenance classes are never summed (three separate sources, no blended total) — ${label}`,
    separate && blended.length === 0 && summary.classes.first_party_reported === null && summary.classes.provider_native === null
    && summary.classes.user_declared.counts.booking === 1 && summary.classes.user_declared.money.usd?.minor === 4550,
    { classes: summary.classes, blendedKeys: blended });
  await shot(page, `${fileLabel(label)}-1-declared`);

  // Amend: a new version of the same result (it still counts once).
  await row.getByRole('button', { name: copy.item.edit, exact: true }).click();
  const amend = page.getByRole('dialog', { name: copy.form.amendTitle, exact: true });
  await amend.getByLabel(copy.form.amount, { exact: true }).fill('60');
  await amend.getByRole('button', { name: copy.form.saveEdit, exact: true }).click();
  await amend.waitFor({ state: 'hidden' });
  await row.getByText(copy.item.edited, { exact: true }).waitFor();
  await until(async () => (await row.innerText()).includes('60.00'), 'the amended amount in the ledger');
  await until(async () => (await declaredCard.innerText()).includes('60.00'), 'the summary follows the amendment');
  let events = await must('GET', `/api/workspaces/${wid}/results/events?provenance=user_declared`);
  summary = await must('GET', `/api/workspaces/${wid}/results/summary`);
  record(`results: amend makes a new version, summary updates — ${label}`,
    events.items.length === 1 && events.items[0].amended === true && events.items[0].amount?.minor === 6000 && events.items[0].status === 'active'
    && summary.classes.user_declared.counts.booking === 1 && summary.classes.user_declared.money.usd?.minor === 6000,
    { item: events.items[0], money: summary.classes.user_declared.money });

  // Reverse: kept in the history, marked reversed, out of every total.
  await row.getByRole('button', { name: copy.item.reverse, exact: true }).click();
  const reverse = page.getByRole('dialog', { name: copy.reverse.title, exact: true });
  await reverse.getByLabel(copy.reverse.reason, { exact: true }).fill(zh ? '學生取消了預約' : 'The student cancelled');
  await reverse.getByRole('button', { name: copy.reverse.confirm, exact: true }).click();
  await reverse.waitFor({ state: 'hidden' });
  await row.getByText(copy.item.reversed, { exact: true }).waitFor();
  await declaredCard.getByText(copy.allWithdrawn, { exact: true }).waitFor();
  events = await must('GET', `/api/workspaces/${wid}/results/events?provenance=user_declared`);
  summary = await must('GET', `/api/workspaces/${wid}/results/summary`);
  record(`results: reverse keeps the row, marks it reversed and the summary drops it — ${label}`,
    events.items.length === 1 && events.items[0].status === 'reversed' && summary.classes.user_declared.reversed === 1
    && !summary.classes.user_declared.counts.booking && Object.keys(summary.classes.user_declared.money).length === 0,
    { status: events.items[0]?.status, declared: summary.classes.user_declared });
  await shot(page, `${fileLabel(label)}-2-reversed`);
  await axeCheck(page, `results ledger ${label}`);
  await noHorizontalScroll(page, `results ledger ${label}`);

  // A tracking link: the server makes it; a click through it carries rafii_ref to the destination.
  await region.getByRole('tab', { name: copy.tabs.links, exact: true }).click();
  await region.getByRole('button', { name: copy.links.create, exact: true }).click();
  const create = page.getByRole('dialog', { name: copy.links.createTitle, exact: true });
  await create.getByLabel(copy.links.destination, { exact: true }).fill('https://example.com/booking');
  const linkLabel = zh ? '預約頁面' : 'Booking page';
  await create.getByLabel(copy.links.label, { exact: true }).fill(linkLabel);
  await create.getByLabel(copy.links.campaign, { exact: true }).fill('nov-cohort');
  await create.getByRole('button', { name: copy.links.createButton, exact: true }).click();
  const made = page.getByRole('dialog', { name: copy.links.created, exact: true });
  await made.waitFor();
  const shown = await made.getByRole('textbox').inputValue();
  await shot(page, `${fileLabel(label)}-3-link-ready`);
  const slug = shown.split('/api/l/')[1] || '';
  const hop = await ctx.request.get(`${base}/api/l/${slug}`, {
    maxRedirects: 0, failOnStatusCode: false,
    headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36' }
  });
  const location = hop.headers().location || '';
  record(`results: the tracking link redirects with rafii_ref — ${label}`,
    /^https?:\/\/[^/]+\/api\/l\/[A-Za-z0-9_-]{10,32}$/.test(shown) && hop.status() === 302 && location.startsWith(`https://example.com/booking?rafii_ref=${slug}.`),
    { shown, status: hop.status(), location });
  entry.trackingLink = { shown, location };
  await made.getByRole('button', { name: copy.secret.done, exact: true }).last().click();
  await made.waitFor({ state: 'hidden' });
  const links = region.getByRole('list', { name: copy.tabs.links, exact: true });
  await links.getByText(linkLabel, { exact: true }).waitFor();
  const listed = await must('GET', `/api/workspaces/${wid}/results/links`);
  record(`results: the link is listed and its click counted (clicks, not people) — ${label}`,
    listed.items.length === 1 && listed.items[0].label === linkLabel && listed.items[0].clicks.counted + listed.items[0].clicks.likelyBot === 1 && listed.items[0].clicks.unit === 'clicks_not_people',
    { clicks: listed.items[0]?.clicks });
  await axeCheck(page, `results links ${label}`);
  await noHorizontalScroll(page, `results links ${label}`);
  await shot(page, `${fileLabel(label)}-4-links`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 2. Relationships: Inbox → Follow-ups                                                                                 */
/* ------------------------------------------------------------------------------------------------------------------ */

async function followUpJourney(env, { label, zh, viewport, entry }) {
  const { page, wid, must } = env;
  const copy = C.followUp[zh ? 'zh-Hant' : 'en'];
  const resultsCopy = C.results[zh ? 'zh-Hant' : 'en'];
  const twoPane = viewport.width >= 1024;
  // A result the person already declared (Business results API), to pick when marking the follow-up won.
  const seedNote = zh ? '工作坊名額' : 'Workshop seat';
  const seeded = await must('POST', `/api/workspaces/${wid}/results/events`, {
    type: 'sale', occurredAt: new Date(Date.now() - 3600e3).toISOString(), amount: { minor: 12000, currency: 'usd' }, quantity: 1, note: seedNote,
    idempotencyKey: `seed-${randomUUID()}`
  });
  const seededId = seeded.result.id;

  // No comments in this workspace (the harness has no Inbox thread here): the manual, no-thread path.
  await page.goto(base + '/app/inbox');
  await page.getByRole('heading', { name: 'Inbox', level: 1 }).waitFor({ timeout: 120000 });
  await stable(page, page.getByRole('heading', { name: 'Inbox', level: 1 }));
  const openView = page.getByRole('button', { name: copy.tab, exact: true });
  const presses = await tabTo(page, openView);
  await page.keyboard.press('Enter');
  const start = page.getByRole('button', { name: copy.newFollowUp, exact: true });
  const startPresses = await tabTo(page, start, { back: 3 });
  await page.keyboard.press('Enter');
  const form = page.getByRole('form', { name: copy.track, exact: true });
  await form.waitFor();
  record(`follow-ups: keyboard reaches Follow-ups and "${copy.newFollowUp}" — ${label}`, true, { tabPresses: presses, startPresses });
  const name = zh ? '陳美玲' : 'Mei Chan';
  await form.getByLabel(copy.name, { exact: true }).fill(name);
  await form.getByLabel(copy.interest, { exact: true }).fill(zh ? '想為女兒報讀私人鋼琴課' : 'Private piano lessons for her daughter');
  await form.getByLabel(copy.nextAction, { exact: true }).fill(zh ? '傳送十一月時間表' : 'Send the November timetable');
  const day = new Date(Date.now() + 2 * 86400e3).toISOString().slice(0, 10);
  await form.locator('input[type="datetime-local"]').fill(`${day}T10:00`);
  await form.getByRole('button', { name: copy.create, exact: true }).click();

  const card = page.locator('section[data-follow-up]');
  await card.getByRole('heading', { name, exact: true }).waitFor();
  const relationshipId = await card.getAttribute('data-follow-up');
  let detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  record(`follow-ups: created without a thread, due in the person's zone — ${label}`,
    detail.state === 'new' && detail.threadIds.length === 0 && detail.due?.local === `${day}T10:00` && detail.due?.timeZone === ZONE[viewport.name],
    { state: detail.state, due: detail.due, threads: detail.threadIds.length });
  const cardText = await card.innerText();
  record(`follow-ups: a follow-up without a conversation says so in the person's language (no platform named) — ${label}`,
    cardText.includes(copy.noConversationHint) && !cardText.includes('the platform'), { hint: copy.noConversationHint });
  await shot(page, `${fileLabel(label)}-1-created`);

  // Set a new due time in the editor.
  await card.getByRole('button', { name: copy.edit, exact: true }).click();
  await card.locator('input[type="datetime-local"]').fill(`${day}T11:30`);
  await card.getByRole('button', { name: copy.save, exact: true }).click();
  await card.getByRole('button', { name: copy.edit, exact: true }).waitFor();
  detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  record(`follow-ups: due time changed — ${label}`, detail.due?.local === `${day}T11:30` && detail.due?.revision === 2, { due: detail.due });

  // Snooze, then undo it.
  await card.getByRole('button', { name: copy.snooze, exact: true }).click();
  await card.getByRole('group', { name: copy.snooze, exact: true }).getByRole('button', { name: copy.snoozeWeek, exact: true }).click();
  await card.getByText(copy.snoozedUntil(''), { exact: false }).waitFor();
  detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  const snoozed = detail.followUp.status === 'snoozed' && detail.snoozedUntil > Date.now() / 1000 + 6 * 86400;
  await shot(page, `${fileLabel(label)}-2-snoozed`);
  // Wide screens: the toast's Undo. Below 1024 px the follow-up is a modal sheet, so the toast outside it is hidden from
  // keyboard and assistive tech; the card's own "Unsnooze" is the undo there.
  if (twoPane) await page.getByRole('button', { name: copy.undo, exact: true }).click();
  else await card.getByRole('button', { name: copy.unsnooze, exact: true }).click();
  entry.undo = twoPane ? 'toast Undo' : 'card Unsnooze (toast is outside the modal sheet)';
  await until(async () => (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship.snoozedUntil === null, 'snooze undone');
  await card.getByText(copy.snoozedUntil(''), { exact: false }).waitFor({ state: 'hidden' });
  detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  record(`follow-ups: snooze and undo — ${label}`, snoozed && detail.snoozedUntil === null && detail.followUp.status === 'scheduled', { followUp: detail.followUp, undo: entry.undo });

  // Won, by picking the declared result.
  await card.getByRole('combobox', { name: copy.state, exact: true }).selectOption('won');
  await card.getByText(copy.wonPick, { exact: true }).waitFor();
  await card.getByRole('radio', { name: new RegExp(escapeRe(seedNote)) }).check();
  await card.getByRole('button', { name: copy.confirm, exact: true }).click();
  await card.getByText(`${copy.states.won} · ${copy.provenance.user_declared}`, { exact: true }).waitFor();
  detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  record(`follow-ups: won by picking a declared result — ${label}`, detail.state === 'won' && detail.won?.resultId === seededId && detail.won?.provenance === 'user_declared', { won: detail.won });
  await shot(page, `${fileLabel(label)}-3-won-picked`);

  // Reopen, then won again by recording the result in place.
  await card.getByRole('button', { name: copy.reopen, exact: true }).click();
  await card.getByRole('combobox', { name: copy.state, exact: true }).waitFor();
  detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  const reopened = detail.state === 'new' && detail.won === null;
  await card.getByRole('combobox', { name: copy.state, exact: true }).selectOption('won');
  await card.getByRole('button', { name: resultsCopy.form.title, exact: true }).click();
  const inPlace = card.locator('form').filter({ hasText: resultsCopy.form.intro });
  await inPlace.getByLabel(resultsCopy.form.type, { exact: true }).selectOption('booking');
  await inPlace.getByLabel(resultsCopy.form.amount, { exact: true }).fill('80');
  await inPlace.getByLabel(resultsCopy.form.currency, { exact: true }).fill('USD');
  await inPlace.getByRole('button', { name: copy.wonRecordAndSelect, exact: true }).click();
  await until(async () => (await card.getByRole('radio', { checked: true }).count()) === 1 && (await card.getByRole('radio', { checked: true }).getAttribute('value')) !== seededId,
    'the recorded result is selected');
  const recordedId = await card.getByRole('radio', { checked: true }).getAttribute('value');
  await card.getByRole('button', { name: copy.confirm, exact: true }).click();
  await card.getByText(`${copy.states.won} · ${copy.provenance.user_declared}`, { exact: true }).waitFor();
  detail = (await must('GET', `/api/workspaces/${wid}/relationships/${relationshipId}`)).relationship;
  const declared = await must('GET', `/api/workspaces/${wid}/results/events?provenance=user_declared`);
  const recorded = declared.items.find((item) => item.id === recordedId);
  record(`follow-ups: reopened, then won by "${resultsCopy.form.title}" in place — ${label}`,
    reopened && detail.state === 'won' && detail.won?.resultId === recordedId && recordedId !== seededId
    && recorded?.type === 'booking' && recorded?.amount?.minor === 8000 && recorded?.provenance === 'user_declared',
    { won: detail.won, recorded: recorded && { type: recorded.type, amount: recorded.amount, provenance: recorded.provenance } });
  await shot(page, `${fileLabel(label)}-4-won-recorded`, true);
  await axeCheck(page, `follow-ups ${label}`);
  await noHorizontalScroll(page, `follow-ups ${label}`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 3. Signature Series (Library → Series)                                                                               */
/* ------------------------------------------------------------------------------------------------------------------ */

const SERIES_FACTS = {
  en: ['Adult beginners improve fastest with five focused minutes on one skill before each piece.',
    'Short daily practice works better than one long weekend session for adult learners.',
    'Recording one take a week helps adult students hear their own progress.',
    'A teacher check-in every two weeks keeps adult beginners from practising mistakes.'],
  'zh-Hant': ['成年初學者每次練曲前先專注練五分鐘技巧，進步最快。',
    '對成年學生來說，每天短時間練習比週末一次長時間練習更有效。',
    '每星期錄一次音，可以幫助成年學生聽到自己的進步。',
    '每兩星期與老師檢查一次，可以避免成年初學者重複練錯。']
};

async function seriesJourney(env, { label, zh }) {
  const { page, wid, must, call } = env;
  const lang = zh ? 'zh-Hant' : 'en';
  const copy = C.series[lang];
  const facts = SERIES_FACTS[lang];
  // An eligible original through the workspace's own commands: a source with approved facts.
  let snapshot = await must('GET', `/api/workspaces/${wid}`);
  snapshot = await must('POST', `/api/workspaces/${wid}/actions`, {
    expectedRevision: snapshot.revision, action: 'source', payload: { kind: 'text', title: zh ? '成年初學者練習筆記' : 'Practice notes for adult beginners', text: facts.join('\n') }
  });
  const source = snapshot.state.sources.at(-1);
  snapshot = await must('POST', `/api/workspaces/${wid}/actions`, {
    expectedRevision: snapshot.revision, action: 'approve_source', payload: { sourceId: source.id, factIds: source.facts.map((fact) => fact.id) }
  });

  await page.goto(base + '/app/library');
  const section = page.getByRole('region', { name: copy.sectionTitle, exact: true });
  await section.waitFor({ timeout: 120000 });
  await stable(page, section);
  await section.scrollIntoViewIfNeeded();
  await section.getByText(copy.emptyTitle, { exact: true }).waitFor();
  const startButton = section.getByRole('button', { name: copy.newSeries, exact: true });
  const presses = await tabTo(page, startButton, { back: 2 });
  await page.keyboard.press('Enter');
  const create = page.getByRole('dialog', { name: copy.createTitle, exact: true });
  await create.waitFor();
  record(`series: keyboard reaches "${copy.newSeries}" — ${label}`, true, { tabPresses: presses });
  await create.getByRole('radio', { name: copy.sourceSource, exact: true }).click();
  await create.getByRole('radio', { name: new RegExp(escapeRe(facts[0].slice(0, 18))) }).check();
  const question = zh ? '成年初學者應該怎樣練習？' : 'How should adult beginners practise?';
  await create.getByLabel(copy.audienceQuestion).fill(question);
  await create.getByLabel(copy.goal).fill(zh ? '幫助成年學生建立穩定的練習習慣' : 'Help adult students build a steady practice habit');
  await create.getByRole('button', { name: copy.create, exact: true }).click();
  const detail = page.getByRole('dialog', { name: question, exact: true });
  await detail.waitFor();
  const episodes = detail.getByRole('article');
  await until(async () => (await episodes.count()) === 3, 'three planned episodes');
  const listed = await must('GET', `/api/workspaces/${wid}/series`);
  const seriesId = listed.items[0].id;
  let view = (await must('GET', `/api/workspaces/${wid}/series/${seriesId}`)).series;
  record(`series: created from a source with approved facts, 3 episodes planned — ${label}`,
    view.origin.kind === 'source' && view.episodes.length === 3 && view.episodes.every((e) => e.workflowState === 'planned') && view.claims.length === facts.length,
    { episodes: view.episodes.length, claims: view.claims.length, language: view.language });

  // Plan more: fill the plan up to four waiting episodes.
  await detail.getByRole('combobox', { name: copy.planMore, exact: true }).selectOption('4');
  await detail.getByRole('button', { name: copy.planMore, exact: true }).click();
  await until(async () => (await episodes.count()) === 4, 'a fourth planned episode');
  await shot(page, `${fileLabel(label)}-1-planned`);

  // Approve an episode angle ("Keep this angle"); approval as next is offered while its facts are current.
  const first = episodes.first();
  await first.getByRole('button', { name: copy.approveNext, exact: true }).waitFor();
  await first.getByRole('button', { name: copy.accept, exact: true }).click();
  await first.getByText(copy.angleAccepted, { exact: true }).waitFor();
  view = (await must('GET', `/api/workspaces/${wid}/series/${seriesId}`)).series;
  const firstEpisode = view.episodes.find((e) => e.index === 1) ?? view.episodes[0];
  record(`series: an episode angle approved (kept) — ${label}`,
    view.episodes.length === 4 && view.decisions.some((d) => d.decision === 'accept' && d.episodeId === firstEpisode.id && d.status === 'active'),
    { decisions: view.decisions.map((d) => ({ decision: d.decision, storage: d.storage })) });

  // The source changes (one fact withdrawn from approval): every claim of it needs review again, and an episode built
  // on those claims can't be approved (an episode without claims has nothing to re-check and stays approvable).
  snapshot = await must('GET', `/api/workspaces/${wid}`);
  await must('POST', `/api/workspaces/${wid}/actions`, {
    expectedRevision: snapshot.revision, action: 'approve_source', payload: { sourceId: source.id, factIds: source.facts.slice(1).map((fact) => fact.id) }
  });
  view = (await must('GET', `/api/workspaces/${wid}/series/${seriesId}`)).series;
  const gated = view.episodes.filter((e) => e.workflowState === 'planned' && e.claimIds.length > 0).sort((a, b) => a.index - b.index)[0];
  if (!gated) throw new Error('no planned episode carries a claim to re-check');
  await page.reload();
  await section.waitFor({ timeout: 120000 });
  await stable(page, section);
  await section.scrollIntoViewIfNeeded();
  const row = section.getByRole('button', { name: new RegExp(escapeRe(question)) });
  await row.getByText(copy.needsReview.split('{n}')[1].trim(), { exact: false }).waitFor();
  await row.click();
  await detail.waitFor();
  await detail.getByText(copy.next.review_facts, { exact: true }).waitFor();
  const gatedCard = episodes.filter({ has: page.getByRole('heading', { name: `${gated.index}. ${copy.role[gated.role]}`, exact: true }) });
  await gatedCard.getByText(copy.factNeeds, { exact: true }).waitFor();
  const approveOffered = await gatedCard.getByRole('button', { name: copy.approveNext, exact: true }).count();
  const refused = await call('POST', `/api/workspaces/${wid}/series/${seriesId}/episodes/${gated.id}/approve`, {
    expectedRevision: view.revision, idempotencyKey: `approve-${randomUUID()}`
  });
  record(`series: the fact-review gate blocks approval while a claim needs review — ${label}`,
    gated.factState === 'needs_fact_review' && gated.canApprove === false && gated.blockedReason === 'needs_fact_review' && approveOffered === 0
    && refused.status === 409 && refused.body?.code === 'needs_fact_review' && view.claims.every((c) => c.freshness.state !== 'ok'),
    { episode: gated.index, reasons: gated.factReasons, approveOffered, status: refused.status, code: refused.body?.code, message: refused.body?.error });
  await shot(page, `${fileLabel(label)}-2-gated`);
  await axeCheck(page, `series detail ${label}`);
  await noHorizontalScroll(page, `series detail ${label}`);

  // Review the facts: confirm the changed ones, remove the one without support; then approval is offered again.
  const factsRegion = detail.getByRole('region', { name: copy.factsHeading, exact: true });
  for (let round = 0; round < 8; round += 1) {
    const flagged = factsRegion.getByRole('listitem').filter({ has: page.getByRole('button', { name: copy.removeFact, exact: true }) });
    const remaining = await flagged.count();
    if (remaining === 0) break;
    // Pin the row by its fact text: once "Still true" opens its form, its buttons go and `first()` would move on.
    const claimText = (await flagged.first().locator('span').first().innerText()).trim();
    const item = factsRegion.getByRole('listitem').filter({ hasText: claimText });
    const unsupported = (await item.getByText(copy.reason.missing_support, { exact: true }).count()) > 0 || (await item.getByText(copy.reason.source_unavailable, { exact: true }).count()) > 0;
    if (!unsupported && (await item.getByRole('button', { name: copy.stillTrue, exact: true }).count()) > 0) {
      await item.getByRole('button', { name: copy.stillTrue, exact: true }).click();
      await item.getByRole('button', { name: copy.save, exact: true }).click();
    } else {
      await item.getByRole('button', { name: copy.removeFact, exact: true }).click();
    }
    await until(async () => (await flagged.count()) < remaining, 'one fact reviewed');
  }
  await gatedCard.getByRole('button', { name: copy.approveNext, exact: true }).click();
  await gatedCard.getByText(copy.state.approved, { exact: true }).waitFor();
  view = (await must('GET', `/api/workspaces/${wid}/series/${seriesId}`)).series;
  record(`series: after the facts are reviewed the episode is approved as next — ${label}`,
    view.episodes.find((e) => e.id === gated.id)?.workflowState === 'approved' && view.claims.every((c) => c.freshness.state === 'ok' || c.freshness.state === 'removed'),
    { claims: view.claims.map((c) => c.freshness.state) });
  await shot(page, `${fileLabel(label)}-3-approved`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 4. Visual pack (Library → Carousels)                                                                                 */
/* ------------------------------------------------------------------------------------------------------------------ */

const PACK_DRAFT = {
  en: 'Most adult beginners quit piano because they practise pieces, not skills. Five minutes on one skill first changes that. Pick the hardest bar of the week. Play it slowly with a metronome. Record one take on Friday. Keep the take you like and start again on Monday.',
  'zh-Hant': '很多成年初學者放棄鋼琴，是因為只練曲子、不練技巧。先花五分鐘練一個技巧，情況就會不同。選出這星期最難的一小節。用節拍器慢慢彈。星期五錄一次音。留下你喜歡的一段，星期一重新開始。'
};

function pngSize(buffer) {
  const signature = buffer.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  return signature ? { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) } : null;
}

/** Entries of a zip (central directory), and a STORED entry's bytes. */
function zipEntries(buffer) {
  let end = -1;
  for (let i = buffer.length - 22; i >= Math.max(0, buffer.length - 65557); i -= 1) {
    if (buffer.readUInt32LE(i) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) return [];
  const entries = [];
  let at = buffer.readUInt32LE(end + 16);
  for (let n = buffer.readUInt16LE(end + 10); n > 0; n -= 1) {
    if (buffer.readUInt32LE(at) !== 0x02014b50) break;
    const nameLength = buffer.readUInt16LE(at + 28);
    entries.push({ name: buffer.toString('utf8', at + 46, at + 46 + nameLength), method: buffer.readUInt16LE(at + 10), size: buffer.readUInt32LE(at + 24), local: buffer.readUInt32LE(at + 42) });
    at += 46 + nameLength + buffer.readUInt16LE(at + 30) + buffer.readUInt16LE(at + 32);
  }
  return entries;
}

function zipStored(buffer, entry) {
  const start = entry.local + 30 + buffer.readUInt16LE(entry.local + 26) + buffer.readUInt16LE(entry.local + 28);
  return buffer.subarray(start, start + entry.size);
}

async function visualPackJourney(env, { label, zh, entry }) {
  const { page, wid, must, call, bytes } = env;
  const lang = zh ? 'zh-Hant' : 'en';
  const copy = C.visualPack[lang];
  const fill = C.fill;
  // The person's own draft (no model writes it), and a connected account to ask the Queue handoff for.
  await must('POST', `/api/workspaces/${wid}/first-week/start`, {
    idempotencyKey: `vp-${randomUUID()}`, consent: true, text: PACK_DRAFT[lang], platform: 'Instagram', language: zh ? 'zh-HK' : 'en'
  });
  const started = await must('POST', `/api/workspaces/${wid}/channels/threads/oauth/start`, { capability: 'publish' });
  const connected = await must('POST', `/api/workspaces/${wid}/channels/threads/oauth/complete`, { state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'good-code' });
  const channelId = connected.connectionId;

  await page.goto(base + '/app/library');
  const section = page.getByRole('region', { name: copy.title, exact: true });
  await section.waitFor({ timeout: 120000 });
  await stable(page, section);
  await section.scrollIntoViewIfNeeded();
  await section.getByText(copy.empty, { exact: true }).waitFor();
  const newButton = section.getByRole('button', { name: copy.newCarousel, exact: true });
  const presses = await tabTo(page, newButton);
  await page.keyboard.press('Enter');
  const choose = page.getByRole('dialog', { name: copy.chooseDraft, exact: true });
  await choose.waitFor();
  const radio = choose.getByRole('radio', { name: new RegExp(escapeRe(PACK_DRAFT[lang].slice(0, 16))) });
  await radio.focus();
  await page.keyboard.press('Space');
  const make = choose.getByRole('button', { name: copy.make, exact: true });
  const makePresses = await tabForward(page, make);
  await page.keyboard.press('Enter');
  record(`visual pack: keyboard opens the chooser, picks the draft and makes the carousel — ${label}`, true, { tabPresses: presses, makePresses });
  const titled = (state, n) => page.getByRole('dialog', { name: `${copy.states[state]} · ${fill(copy.version, { n })}`, exact: true });
  let editor = titled('draft', 1);
  await editor.waitFor({ timeout: 60000 });
  const packId = (await must('GET', `/api/workspaces/${wid}/visual-packs`)).items[0].id;

  // Edit one slide → a new version.
  const slideText = zh ? '先專注練五分鐘技巧，進步就會不同。' : 'Five focused minutes on one skill changes everything.';
  await editor.getByRole('textbox', { name: copy.text, exact: true }).nth(1).fill(slideText);
  await editor.getByRole('button', { name: copy.save, exact: true }).click();
  editor = titled('draft', 2);
  await editor.waitFor();
  let view = await must('GET', `/api/workspaces/${wid}/visual-packs/${packId}`);
  record(`visual pack: a slide edit saves a new version — ${label}`, view.revision.revision === 2 && view.revision.slides[1].text === slideText && view.history.some((h) => h.revision === 1 && h.state === 'superseded'),
    { revision: view.revision.revision, history: view.history.map((h) => `${h.revision}:${h.state}`) });

  // Render on the server, then look at the actual files.
  await editor.getByRole('button', { name: copy.render, exact: true }).click();
  editor = titled('rendered', 2);
  await editor.waitFor({ timeout: 90000 });
  const preview = editor.getByRole('region', { name: copy.preview, exact: true });
  await until(async () => (await preview.getByRole('img').count()) === 6, 'six rendered slides in the preview', 60000);
  await preview.scrollIntoViewIfNeeded();
  await shot(page, `${fileLabel(label)}-1-rendered`);
  view = await must('GET', `/api/workspaces/${wid}/visual-packs/${packId}`);
  const sizes = [];
  for (const slide of view.revision.render.slides) {
    const png = await bytes(slide.href);
    sizes.push(pngSize(png));
    writeFileSync(resolve(out, `${fileLabel(label)}-slide-${String(slide.position).padStart(2, '0')}.png`), png);
  }
  record(`visual pack: six server-rendered 1080×1350 PNGs with alt text — ${label}`,
    sizes.length === 6 && sizes.every((s) => s && s.width === 1080 && s.height === 1350) && view.revision.render.slides.every((s) => s.altText.trim().length > 0),
    { sizes, language: view.pack.language });

  // Accept this exact revision, export, download the zip.
  await editor.getByRole('checkbox', { name: copy.acceptConfirm, exact: true }).check();
  await editor.getByRole('button', { name: copy.accept, exact: true }).click();
  editor = titled('accepted', 2);
  await editor.getByRole('button', { name: copy.export, exact: true }).click();
  editor = titled('export_ready', 2);
  await editor.waitFor({ timeout: 60000 });
  const [download] = await Promise.all([page.waitForEvent('download'), editor.getByRole('button', { name: copy.download, exact: true }).click()]);
  const zipPath = resolve(out, `${fileLabel(label)}.zip`);
  await download.saveAs(zipPath);
  const zip = readFileSync(zipPath);
  const names = zipEntries(zip).map((e) => e.name);
  const firstSlide = zipEntries(zip).find((e) => e.name === 'slide-01.png');
  const slideInZip = firstSlide && firstSlide.method === 0 ? pngSize(zipStored(zip, firstSlide)) : null;
  editor = titled('downloaded', 2);
  await editor.waitFor();
  view = await must('GET', `/api/workspaces/${wid}/visual-packs/${packId}`);
  record(`visual pack: the export zip downloads complete and the server records it — ${label}`,
    zip.subarray(0, 4).equals(Buffer.from('PK\x03\x04', 'latin1')) && ['slide-01.png', 'slide-06.png', 'caption.txt', 'alt-text.txt', 'manifest.json'].every((n) => names.includes(n))
    && slideInZip?.width === 1080 && view.revision.state === 'downloaded' && view.revision.facts.downloadCount === 1,
    { bytes: zip.length, names, state: view.revision.state, filename: download.suggestedFilename() });

  // Queue is refused with its reason; nothing is queued.
  await editor.getByText(copy.queueNote, { exact: true }).waitFor();
  const queueButtons = await editor.getByRole('button', { name: zh ? /佇列|排程/ : /queue|schedule/i }).count();
  const refused = await call('POST', `/api/workspaces/${wid}/visual-packs/${packId}/queue`, { expectedRevision: 2, channelId });
  const after = await must('GET', `/api/workspaces/${wid}/visual-packs/${packId}`);
  const capability = after.handoff.queue.channels.find((c) => c.channelId === channelId);
  record(`visual pack: queueing is refused with its reason (no verified multi-image publisher) — ${label}`,
    queueButtons === 0 && refused.status === 409 && refused.body?.code === 'unsupported_input' && /no publisher has verified multi-image support/.test(refused.body?.error || '')
    && /Nothing was queued/.test(refused.body?.error || '') && after.handoff.queue.available === false && capability?.supported === false
    && after.revision.state === 'downloaded' && after.revision.facts.queuedAt === null,
    { status: refused.status, code: refused.body?.code, message: refused.body?.error, capability });
  entry.queueRefusal = refused.body?.error;
  await shot(page, `${fileLabel(label)}-2-downloaded`);
  await axeCheck(page, `visual pack editor ${label}`);
  await noHorizontalScroll(page, `visual pack editor ${label}`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 5. Raw source intake (Ideas → upload panel)                                                                          */
/* ------------------------------------------------------------------------------------------------------------------ */

const PDF_LINES = ['Practice notes for adult piano beginners.', 'Five focused minutes on one skill before each piece speeds up progress.',
  'Short daily sessions work better than one long weekend session.', 'Recording one take every Friday helps students hear their own progress.'];

/** A one-page text PDF (Helvetica, real text layer), built byte for byte with a correct cross-reference table. */
function makePdf(lines) {
  const esc = (text) => text.replace(/[\\()]/g, (c) => `\\${c}`);
  const stream = ['BT', '/F1 12 Tf', '72 720 Td', ...lines.flatMap((line, i) => [...(i ? ['0 -20 Td'] : []), `(${esc(line)}) Tj`]), 'ET'].join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream, 'latin1')} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
  ];
  let body = '%PDF-1.4\n';
  const offsets = [];
  objects.forEach((object, i) => {
    offsets.push(Buffer.byteLength(body, 'latin1'));
    body += `${i + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(body, 'latin1');
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}

/** Half a second of 8 kHz mono silence as a real WAV file. */
function makeWav(seconds = 0.5, rate = 8000) {
  const data = Buffer.alloc(Math.round(seconds * rate) * 2);
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

/**
 * A record of the upload panel over time, for the keyboard step's evidence: which heading, button and file input are
 * on the page (each new element gets a number, so a re-render that replaces them shows), where focus is, what Enter
 * and Space did (keydown, keypress, whether anything prevented them) and which clicks reached the button and the input.
 * It observes only; nothing here decides pass or fail.
 */
async function installIntakeProbe(page, copy, startedAt) {
  await page.evaluate(({ title, choose, startedAt }) => {
    const log = [];
    let count = 0;
    const id = (node) => (node ? (node.__probe ??= ++count) : 0);
    const describe = (node) => (!node || node === document.body ? 'body' : `${node.tagName.toLowerCase()}#${id(node)}`);
    const at = () => Date.now() - startedAt;
    let last = '';
    const tick = () => {
      const heading = [...document.querySelectorAll('h2')].find((node) => node.textContent.trim() === title) || null;
      const section = heading?.closest('section') || null;
      const button = section ? [...section.querySelectorAll('button')].find((node) => node.textContent.trim() === choose) || null : null;
      const input = section?.querySelector('input[type=file]') || null;
      for (const [node, kind] of [[button, 'button'], [input, 'input']]) {
        if (node && !node.__probeClicks) {
          node.__probeClicks = true;
          node.addEventListener('click', (event) => log.push({ t: at(), click: kind, id: id(node), trusted: event.isTrusted, connected: node.isConnected }));
        }
      }
      const state = `h2#${id(heading)} button#${id(button)} input#${id(input)} focus=${describe(document.activeElement)}`;
      if (state !== last) {
        last = state;
        log.push({ t: at(), state });
      }
    };
    setInterval(tick, 50);
    tick();
    for (const type of ['keydown', 'keypress', 'keyup']) {
      window.addEventListener(type, (event) => {
        if (event.key === 'Enter' || event.key === ' ') log.push({ t: at(), [type]: event.key, target: describe(event.target) });
      }, true);
      window.addEventListener(type, (event) => {
        if ((event.key === 'Enter' || event.key === ' ') && event.defaultPrevented) log.push({ t: at(), prevented: type });
      });
    }
    window.__intakeProbe = log;
  }, { title: copy.title, choose: copy.choose, startedAt });
}

async function intakeJourney(env, { label, zh, entry }) {
  const { page, wid, must, call, ctx } = env;
  const copy = C.intake[zh ? 'zh-Hant' : 'en'];
  // Evidence for the keyboard step: the person's saved preferences as the app read them, and Chromium's own notes.
  const startedAt = Date.now();
  const preferences = [];
  const notes = [];
  page.on('response', (response) => {
    if (new URL(response.url()).pathname !== '/api/me' || response.request().method() !== 'GET') return;
    response.json().then((body) => preferences.push({ t: Date.now() - startedAt, status: response.status(), locale: body?.preferences?.locale ?? null, timeZone: body?.preferences?.timeZone ?? null }))
      .catch(() => preferences.push({ t: Date.now() - startedAt, status: response.status() }));
  });
  page.on('console', (message) => {
    if (/chooser|activation/i.test(message.text())) notes.push({ t: Date.now() - startedAt, type: message.type(), text: message.text().slice(0, 160) });
  });
  const limits = await must('GET', `/api/workspaces/${wid}/source-uploads/limits`);
  record(`intake: limits shown before upload — PDF on, audio refused with transcription_route_not_enabled — ${label}`,
    limits.storage === 'ready' && limits.formats.pdf.supported === true && limits.formats.audio.supported === false && limits.formats.audio.reason === 'transcription_route_not_enabled',
    { storage: limits.storage, pdf: limits.formats.pdf, audio: { supported: limits.formats.audio.supported, reason: limits.formats.audio.reason } });
  // The signed-URL PUT goes to a Supabase-shaped URL; this run forwards it to the harness's dev-synthetic bucket.
  await ctx.route('https://devharness.supabase.co/**', async (route) => {
    const token = new URL(route.request().url()).searchParams.get('token');
    const response = await fetch(`${apiOrigin}/dev/upload/${token}`, {
      method: 'PUT', headers: { 'Content-Type': route.request().headers()['content-type'] || 'application/octet-stream' }, body: route.request().postDataBuffer()
    });
    await route.fulfill({ status: response.ok ? 200 : 400, contentType: 'application/json', body: '{"Key":"ok"}' });
  });
  const begins = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/source-uploads$/.test(new URL(request.url()).pathname)) begins.push(request.url());
  });

  await page.goto(base + '/app/ideas');
  await installIntakeProbe(page, copy, startedAt);
  const panel = page.getByRole('region', { name: copy.title, exact: true });
  await panel.waitFor({ timeout: 120000 });
  await stable(page, panel);
  await panel.scrollIntoViewIfNeeded();
  await panel.getByText(copy.audioOff, { exact: true }).waitFor();
  const choose = panel.getByRole('button', { name: copy.choose, exact: true });

  // Keyboard only: Tab to "Choose a file", Enter opens the picker. A recording is refused before anything uploads.
  // Every Enter press is recorded with the probe's account of it; a press that opens nothing is kept as evidence.
  let presses = 0;
  let audioPicker = null;
  const attempts = [];
  for (let attempt = 1; attempt <= 2 && !audioPicker; attempt += 1) {
    presses += await tabTo(page, choose);
    const pressedAt = Date.now() - startedAt;
    const opened = page.waitForEvent('filechooser', { timeout: 10000 }).catch(() => null);
    await page.keyboard.press('Enter');
    audioPicker = await opened;
    attempts.push({ pressedAt, opened: Boolean(audioPicker) });
  }
  entry.keyboardPicker = {
    attempts, preferences, notes, probe: await page.evaluate(() => window.__intakeProbe).catch((error) => `unavailable: ${error.message.slice(0, 80)}`)
  };
  if (!audioPicker) throw new Error(`keyboard: Enter on the focused "${copy.choose}" button never opened the file picker (${attempts.length} presses; probe in the summary)`);
  const wav = makeWav();
  await audioPicker.setFiles({ name: 'lesson-recording.wav', mimeType: 'audio/wav', buffer: wav });
  await panel.getByRole('alert').filter({ hasText: copy.audioOff }).waitFor();
  const refusedApi = await call('POST', `/api/workspaces/${wid}/source-uploads`, {
    kind: 'audio', name: 'lesson-recording.wav', mime: 'audio/wav', bytes: wav.length, idempotencyKey: `audio-${randomUUID()}`
  });
  record(`intake: audio refused with transcription_route_not_enabled before upload — ${label}`,
    begins.length === 0 && refusedApi.status === 409 && refusedApi.body?.code === 'transcription_route_not_enabled',
    { tabPresses: presses, beginRequests: begins.length, status: refusedApi.status, code: refusedApi.body?.code });
  await shot(page, `${fileLabel(label)}-1-audio-refused`);

  // A small text PDF: upload → check → read → review the text → correct it → create the source.
  const [pdfPicker] = await Promise.all([page.waitForEvent('filechooser'), choose.click()]);
  await pdfPicker.setFiles({ name: 'practice-notes.pdf', mimeType: 'application/pdf', buffer: makePdf(PDF_LINES) });
  const detail = panel.getByRole('region', { name: 'practice-notes.pdf', exact: true });
  await detail.getByRole('heading', { name: copy.reviewTitle, exact: true }).waitFor({ timeout: 120000 });
  const area = detail.getByRole('textbox', { name: copy.reviewTitle, exact: true });
  const extracted = await area.inputValue();
  const flat = extracted.replace(/\s+/g, ' ');
  record(`intake: the extracted text is the PDF's text, for review — ${label}`, PDF_LINES.every((line) => flat.includes(line)), { characters: extracted.length });
  await shot(page, `${fileLabel(label)}-2-review`);
  const addition = zh ? '每星期錄一次音，可以幫助成年學生聽到自己的進步。' : 'A weekly recording helps adult students hear their progress.';
  await area.fill(`${extracted.trimEnd()}\n${addition}`);
  await detail.getByRole('button', { name: copy.useAsSource, exact: true }).click();
  // Below lg the new source opens in a modal sheet, which hides the panel from role queries: find the text itself.
  await page.getByText(copy.sourceCreated, { exact: true }).waitFor({ timeout: 60000 });
  const uploads = await must('GET', `/api/workspaces/${wid}/source-uploads`);
  const upload = uploads.items.find((item) => item.name === 'practice-notes.pdf');
  const snapshot = await must('GET', `/api/workspaces/${wid}`);
  const source = (snapshot.state.sources || []).find((s) => s.id === upload?.job?.sourceId);
  const approved = (source?.facts || []).filter((fact) => fact.approved);
  record(`intake: reviewed text became a source with approved statements (correction kept) — ${label}`,
    upload?.job?.state === 'completed' && Boolean(source) && source.origin?.kind === 'source_upload' && approved.length >= PDF_LINES.length
    && approved.some((fact) => fact.text.includes(addition.slice(0, 12))),
    { job: upload?.job?.state, statements: approved.length, origin: source?.origin?.kind });
  await shot(page, `${fileLabel(label)}-3-source`);
  if (await page.getByRole('dialog').count()) await page.keyboard.press('Escape');   // the source inspector sheet below lg
  await axeCheck(page, `intake ${label}`);
  await noHorizontalScroll(page, `intake ${label}`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 8. Proof revisions (Analytics → Proof of value → Evidence by revision)                                               */
/* ------------------------------------------------------------------------------------------------------------------ */

async function proofJourney(env, { label, zh, entry }) {
  const { page, wid, must } = env;
  const copy = C.proof[zh ? 'zh-Hant' : 'en'];
  // Results the person declared inside last week's completed period (Monday to Monday, UTC: the workspace's default).
  const now = new Date();
  const monday = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - ((now.getUTCDay() + 6) % 7));
  const lastWeek = (day, hour) => new Date(monday - 7 * 86400e3 + day * 86400e3 + hour * 3600e3).toISOString();
  await must('POST', `/api/workspaces/${wid}/results/events`, {
    type: 'lead', occurredAt: lastWeek(3, 12), quantity: 1, note: zh ? '工作坊查詢' : 'Workshop enquiry', idempotencyKey: `proof-${randomUUID()}`
  });
  await page.goto(base + '/app/analytics');
  const section = page.getByRole('region', { name: copy.title, exact: true });
  await section.waitFor({ timeout: 120000 });
  await stable(page, section);
  await section.scrollIntoViewIfNeeded();
  await section.getByText(copy.empty, { exact: true }).waitFor();
  // Keyboard only: Tab to the owner's "Recompute last week", Enter records revision 1 from stored records.
  const recompute = section.getByRole('button', { name: copy.refresh, exact: true });
  const presses = await tabTo(page, recompute, { back: 3 });
  await page.keyboard.press('Enter');
  await section.getByRole('status').filter({ hasText: copy.appended(1) }).waitFor({ timeout: 60000 });
  const card = section.getByRole('article');
  await card.getByRole('heading', { name: new RegExp(escapeRe(copy.revision(1))) }).waitFor();
  let proof = (await must('GET', `/api/workspaces/${wid}/proof/proofs?frequency=weekly`)).proofs[0];
  const firstOutcomes = proof?.latest.counts.figures.outcomes;
  record(`proof: keyboard recompute records revision 1 with the declared result counted by its source — ${label}`,
    proof?.latest.revision === 1 && proof.latest.reason === 'initial' && firstOutcomes?.dataState !== 'unavailable' && Boolean(firstOutcomes?.value?.user_declared)
    && (await card.innerText()).includes(copy.provenance.user_declared),
    { tabPresses: presses, outcomes: firstOutcomes?.value, dataState: firstOutcomes?.dataState, period: proof && [proof.periodStart, proof.periodEnd, proof.timeZone] });
  await shot(page, `${fileLabel(label)}-1-revision1`);

  // Late data: another result in the same period; recomputing appends revision 2 with what changed, revision 1 stays.
  await must('POST', `/api/workspaces/${wid}/results/events`, {
    type: 'booking', occurredAt: lastWeek(4, 15), amount: { minor: 9000, currency: 'usd' }, quantity: 1, note: zh ? '預約試堂' : 'Trial lesson booked',
    idempotencyKey: `proof-${randomUUID()}`
  });
  await recompute.click();
  await section.getByRole('status').filter({ hasText: copy.appended(2) }).waitFor({ timeout: 60000 });
  await card.getByRole('heading', { name: new RegExp(escapeRe(copy.revision(2))) }).waitFor();
  await card.getByText(copy.history, { exact: true }).click();
  const history = card.locator('details').filter({ hasText: copy.history }).locator('ol > li');
  await until(async () => (await history.count()) === 2, 'two revisions in the history');
  const historyText = await history.allInnerTexts();
  proof = (await must('GET', `/api/workspaces/${wid}/proof/proofs?frequency=weekly`)).proofs[0];
  const late = proof.revisions.find((r) => r.revision === 2);
  const kept = await must('GET', `/api/workspaces/${wid}/proof/proofs/${proof.proofId}/revisions/1`);
  record(`proof: late data appends revision 2 with its correction; revision 1 stays readable — ${label}`,
    proof.latest.revision === 2 && proof.revisions.length === 2 && late?.reason === 'late_data' && late.correction.some((c) => c.figure === 'outcomes')
    && Boolean(kept) && historyText.some((text) => text.includes(copy.reason.late_data) && text.includes(copy.correction)),
    { revisions: proof.revisions.map((r) => `${r.revision}:${r.reason}`), correction: late?.correction?.map((c) => c.figure), history: historyText.map((t) => t.slice(0, 160)) });
  entry.proofId = proof.proofId;
  await shot(page, `${fileLabel(label)}-2-revision2`);
  await axeCheck(page, `proof ${label}`);
  await noHorizontalScroll(page, `proof ${label}`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 9. Opportunity brief (Weekly → This week)                                                                            */
/* ------------------------------------------------------------------------------------------------------------------ */

async function briefJourney(env, { label, zh, entry }) {
  const { page, wid, must } = env;
  const copy = C.brief[zh ? 'zh-Hant' : 'en'];
  const current = await must('GET', `/api/workspaces/${wid}/briefs/current`);
  await page.goto(base + '/app/weekly');
  const panel = page.getByRole('region', { name: copy.title, exact: true });
  await panel.waitFor({ timeout: 120000 });
  await stable(page, panel);
  await panel.scrollIntoViewIfNeeded();
  const chips = await panel.getByRole('list', { name: copy.coverage, exact: true }).getByRole('listitem').allInnerTexts();
  const expected = current.coverage.map((source) => `${copy.source[source.source]}: ${copy.sourceState[source.state]}`);
  const items = current.edition?.items ?? current.items ?? [];
  record(`brief: each stored source shows its own state, as the API reports it — ${label}`,
    expected.length === 3 && expected.every((text) => chips.some((chip) => chip.trim() === text)),
    { chips, coverage: current.coverage.map((source) => `${source.source}:${source.state}${source.reason ? `(${source.reason})` : ''}`), dataState: current.dataState });
  if (items.length === 0) {
    // An empty brief says so (valid result or no source), never an invented opportunity.
    const description = current.dataState === 'unavailable' ? copy.emptyUnavailable : copy.emptyAvailable;
    await panel.getByText(copy.emptyTitle, { exact: true }).waitFor();
    record(`brief: no stored evidence → an honest empty brief, no invented item — ${label}`,
      (await panel.getByText(description, { exact: true }).count()) === 1 && (await panel.getByRole('button', { name: copy.saveIdea }).count()) === 0, { dataState: current.dataState });
    entry.keyboard = 'not applicable: an empty brief offers no action';
    entry.actions = 'not_run: the growth harness stores no trend, listening or Radar evidence (research is off and the Radar/trend fixtures are not started), so the brief has no item to accept, save, dismiss or restore';
  } else {
    entry.actions = `not_run: ${items.length} stored item(s) appeared; item actions are not scripted in this journey`;
  }
  await shot(page, `${fileLabel(label)}`);
  await axeCheck(page, `brief ${label}`);
  await noHorizontalScroll(page, `brief ${label}`);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* 7. Pricing v2 public page                                                                                            */
/* ------------------------------------------------------------------------------------------------------------------ */

async function pricingJourney(browser, viewport) {
  const entry = { journey: 'pricing-v2', viewport: `${viewport.name} ${viewport.width}`, language: 'en', status: 'fail',
    zhHant: 'not applicable: the public pricing page has English copy only' };
  journeys.push(entry);
  if (pricingCatalog !== 'v2') {
    entry.status = 'not_run';
    entry.reason = 'the web dev server under test was not started with NEXT_PUBLIC_PRICING_CATALOG=v2 (RAFII_GROWTH_PRICING_CATALOG is not v2)';
    return;
  }
  const label = `pricing-v2/${viewport.name}`;
  const before = failures.length;
  const ctx = await context(browser, viewport, randomUUID(), { quiet: true });
  const page = await ctx.newPage();
  watch(page);
  try {
    await page.goto(base + '/pricing', { timeout: 180000 });
    const free = page.getByRole('group', { name: 'Free', exact: true });
    const creator = page.getByRole('group', { name: 'Creator', exact: true });
    await free.waitFor({ timeout: 90000 });
    await creator.waitFor();
    const planCards = await page.locator('[role="group"][aria-labelledby^="plan-"]').count();
    record(`pricing: Free and Creator only — ${label}`, planCards === 2, { planCards });
    const visible = await page.locator('body').innerText();
    const inMain = (await page.locator('main').textContent()) || '';
    const trial = [...new Set([...(visible.match(/[^.\n]*\btrials?\b[^.\n]*/gi) || []), ...(inMain.match(/[^.\n]*\btrials?\b[^.\n]*/gi) || [])])].slice(0, 5);
    record(`pricing: no "trial" wording — ${label}`, trial.length === 0, { trial });
    // Every action on the page that reads like buying leads somewhere real; nothing is a disabled or dead buy button.
    const actions = await page.locator('a, button').evaluateAll((nodes) => nodes.filter((node) => node.getClientRects().length > 0).map((node) => ({
      tag: node.tagName.toLowerCase(), text: (node.innerText || node.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 80),
      href: node.getAttribute('href'), disabled: node.hasAttribute('disabled') || node.getAttribute('aria-disabled') === 'true',
      inCard: Boolean(node.closest('[role="group"][aria-labelledby^="plan-"]'))
    })));
    const buyish = actions.filter((a) => a.inCard || /\b(buy|subscribe|purchase|checkout|upgrade|get creator|start free|choose|pricing)\b/i.test(a.text));
    const dead = [];
    for (const action of buyish) {
      if (action.disabled || (action.tag === 'a' && (!action.href || action.href === '#' || action.href.startsWith('javascript:')))) {
        dead.push({ ...action, why: 'disabled or no target' });
        continue;
      }
      if (action.tag === 'button') {
        if (action.inCard) dead.push({ ...action, why: 'a plan card button without a link' });
        continue;
      }
      const target = new URL(action.href, base);
      if (target.origin !== base) continue;
      const response = await ctx.request.get(target.href, { failOnStatusCode: false, timeout: 120000 });
      if (response.status() >= 400) dead.push({ ...action, why: `HTTP ${response.status()}` });
    }
    const creatorAction = { text: (await creator.getByRole('link').innerText()).trim(), href: await creator.getByRole('link').getAttribute('href') };
    record(`pricing: no dead buy button (every plan action leads somewhere real) — ${label}`, dead.length === 0 && buyish.some((a) => a.inCard),
      { checked: buyish.length, dead, creatorAction });
    // Keyboard only: Tab to Creator's action and Enter follows it.
    const creatorLink = creator.getByRole('link');
    const presses = await tabTo(page, creatorLink, { back: 3 });
    await Promise.all([page.waitForURL((url) => url.pathname.startsWith('/auth/sign-up') || url.pathname.startsWith('/app'), { timeout: 120000 }), page.keyboard.press('Enter')]);
    record(`pricing: keyboard reaches and follows Creator's action — ${label}`, true, { tabPresses: presses, landed: new URL(page.url()).pathname });
    await page.goto(base + '/pricing', { timeout: 180000 });
    await free.waitFor();
    // The FAQ reveals on scroll: bring it into view as a reader would, then capture the whole page.
    const faq = page.locator('#faq');
    await faq.scrollIntoViewIfNeeded();
    await faq.getByRole('button').first().waitFor({ state: 'visible', timeout: 15000 });
    record(`pricing: the FAQ shows when scrolled to — ${label}`, (await faq.getByRole('button').count()) > 0, { questions: await faq.getByRole('button').count() });
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(1200);   // let each section's reveal finish before the capture
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot(page, `pricing-v2-${viewport.name}`, true);
    await axeCheck(page, `pricing ${label}`);
    await noHorizontalScroll(page, `pricing ${label}`);
  } catch (error) {
    failures.push(`${label}: ${String(error.message).split('\n')[0].slice(0, 400)}`);
    entry.error = String(error.message).slice(0, 900);
    await shot(page, `FAIL-${fileLabel(label)}`, true);
  } finally {
    entry.status = failures.length === before ? 'pass' : 'fail';
    await ctx.close().catch(() => undefined);
  }
}

/* ------------------------------------------------------------------------------------------------------------------ */

async function main() {
  mkdirSync(out, { recursive: true });
  C = await loadCopy();
  const browser = await chromium.launch({ headless: true });
  try {
    if (want('first-week')) {
      const runs = [...VIEWPORTS.map((viewport) => [viewport, viewport.name === 'tablet' ? DRAFT_ZH : DRAFT_EN, viewport.name === 'tablet' ? 'zh-Hant' : 'en']), [VIEWPORTS[2], DRAFT_ZH, 'zh-Hant']];
      for (const [viewport, draft, language] of runs) {
        const entry = { journey: 'first-week', viewport: `${viewport.name} ${viewport.width}`, language, status: 'fail' };
        journeys.push(entry);
        const before = failures.length;
        await firstWeekJourney(browser, viewport, draft, language).catch((error) => {
          failures.push(`${viewport.name}${language === 'zh-Hant' && viewport.name === 'phone' ? ' zh' : ''}: ${error.message.slice(0, 300)}`);
          entry.error = error.message.slice(0, 600);
        });
        entry.status = failures.length === before ? 'pass' : 'fail';
      }
      const entry = { journey: 'first-week blocked storage', viewport: 'desktop 1440', language: 'en', status: 'fail' };
      journeys.push(entry);
      const before = failures.length;
      await blockedStorage(browser).catch((error) => failures.push(`blocked storage: ${error.message.slice(0, 300)}`));
      entry.status = failures.length === before ? 'pass' : 'fail';
    }
    const program = [['results', resultsJourney], ['follow-ups', followUpJourney], ['series', seriesJourney], ['visual-pack', visualPackJourney],
      ['intake', intakeJourney], ['proof', proofJourney], ['brief', briefJourney]];
    for (const [name, run] of program) {
      if (!want(name)) continue;
      for (const viewport of VIEWPORTS) await runJourney(name, browser, viewport, run);
    }
    if (want('creator-credits')) {
      journeys.push({ journey: 'creator-credits', viewport: 'all', language: 'en, zh-Hant', status: 'not_run',
        reason: 'The growth harness builds HostedWorkspaceService with pricing_v2_enabled=False and credits_enabled=False (no credit wallet), so '
          + 'Ledger.growth_mode never returns managed_credits and the Post Doctor never asks for a credit quote. The only existing credit fixture '
          + '(--credit-fixture, scripts/launch_credit_fixture.py) writes plan terms with the legacy candidate policy credits-candidate-2026-09-23-v1 '
          + '(not credits-v2-2026-09-28) straight into the database at bootstrap and swaps the writer runtime. Reaching managed credits would need '
          + 'new privileged seeding (a v2 plan-terms row or a fixture-signed Creator subscription plus a wallet grant), which this run does not fake.' });
    }
    if (want('pricing')) for (const viewport of VIEWPORTS) await pricingJourney(browser, viewport);
  } finally {
    await browser.close();
  }
  const summary = { generatedAt: new Date().toISOString(), base, execution: 'local dev harness: synthetic identity, deterministic models, disposable PostgreSQL; no provider calls',
    storage: 'dev-synthetic in-memory private storage (scripts/postriff_dev_hosted.py DevAssets): source-upload bucket and rendered Visual Pack slides',
    passed: results.filter((r) => r.passed).length, failed: failures.length, journeys, results, failures, warnings: warnings.slice(0, 80) };
  writeFileSync(resolve(out, 'growth-v2-browser.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ passed: summary.passed, failed: summary.failed, journeys: journeys.map((j) => `${j.journey} ${j.viewport} ${j.language}: ${j.status}`), failures: failures.slice(0, 30) }, null, 2));
  process.exit(failures.length ? 1 : 0);
}

main();
