/**
 * RAFII Product Growth v2 — real local Next/API/PostgreSQL journeys (PRD §15.1 group C; AC06–AC10, AC37, AC39).
 * Identity, models and providers are the dev harness's synthetic ones; nothing reaches a provider or charges.
 *
 *   RAFII_GROWTH_WEB_URL=http://127.0.0.1:4443 node web/tests/growth-v2-browser.cjs --out=docs/design/rafii-product-growth/evidence/ci-browser
 *
 * Harness: RAFII_WEEKLY_OPERATOR_ENABLED=1 RAFII_FIRST_WEEK_ENABLED=1 python scripts/postriff_dev_hosted.py --growth-fixture …
 */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync, readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');

const base = process.env.RAFII_GROWTH_WEB_URL || 'http://127.0.0.1:4443';
const outArg = process.argv.find((a) => a.startsWith('--out='));
const out = resolve(process.cwd(), outArg ? outArg.slice(6) : 'docs/design/rafii-product-growth/evidence/ci-browser');
const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'phone', width: 390, height: 844 }
];
const DRAFT_EN = 'Most adult beginners quit piano because they practise pieces, not skills. Five minutes on one skill first changes that.';
const DRAFT_ZH = '很多成年初學者放棄鋼琴，是因為只練曲子、不練技巧。先花五分鐘練一個技巧，情況就會不同。';
const results = [];
const failures = [];
const warnings = [];

function record(scenario, passed, extra = {}) {
  results.push({ scenario, passed, ...extra });
  if (!passed) failures.push(scenario);
}

async function axeCheck(page, label) {
  const source = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
  await page.addScriptTag({ content: source });
  const found = await page.evaluate(async () => {
    const report = await window.axe.run(document, { resultTypes: ['violations'] });
    return report.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
  });
  record(`axe: no serious/critical violations — ${label}`, found.length === 0, { violations: found });
}

async function noHorizontalScroll(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  record(`layout: no horizontal scroll — ${label}`, overflow <= 1, { overflowPx: overflow });
}

async function context(browser, viewport, principal) {
  const ctx = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, reducedMotion: 'reduce' });
  await ctx.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
  await ctx.addInitScript((id) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
  }, principal);
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

async function firstWeekJourney(browser, viewport, draft, language) {
  const principal = randomUUID();
  const ctx = await context(browser, viewport, principal);
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
  const writes = page.getByRole('textbox', { name: 'Write it yourself' });
  const count = await writes.count();
  for (let i = 0; i < count; i += 1) {
    await page.getByRole('textbox', { name: 'Write it yourself' }).first().fill(language === 'zh-Hant' ? `第${i + 2}篇：一個練習技巧。` : `Post ${i + 2}: one practice skill.`);
    await page.getByRole('button', { name: 'Save this post' }).first().click();
    await page.waitForTimeout(300);
  }
  await page.screenshot({ path: resolve(out, `${label.replace('/', '-')}-3-week.png`), fullPage: true });
  await axeCheck(page, `first week ${label}`);
  await noHorizontalScroll(page, `first week ${label}`);
  const used = page.getByRole('button', { name: 'I posted it' });
  const handoffs = await used.count();
  for (let i = 0; i < handoffs; i += 1) {
    await page.getByRole('button', { name: 'I posted it' }).first().click();
    await page.waitForTimeout(300);
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
  const ctx = await context(browser, VIEWPORTS[0], randomUUID());
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

async function main() {
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of VIEWPORTS) {
      await firstWeekJourney(browser, viewport, viewport.name === 'tablet' ? DRAFT_ZH : DRAFT_EN, viewport.name === 'tablet' ? 'zh-Hant' : 'en').catch((error) => {
        failures.push(`${viewport.name}: ${error.message.slice(0, 300)}`);
      });
    }
    await firstWeekJourney(browser, VIEWPORTS[2], DRAFT_ZH, 'zh-Hant').catch((error) => failures.push(`phone zh: ${error.message.slice(0, 300)}`));
    await blockedStorage(browser).catch((error) => failures.push(`blocked storage: ${error.message.slice(0, 300)}`));
  } finally {
    await browser.close();
  }
  const summary = { generatedAt: new Date().toISOString(), base, execution: 'local dev harness: synthetic identity, deterministic models, disposable PostgreSQL; no provider calls',
    passed: results.filter((r) => r.passed).length, failed: failures.length, results, failures, warnings: warnings.slice(0, 50) };
  writeFileSync(resolve(out, 'growth-v2-browser.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ passed: summary.passed, failed: summary.failed, failures: failures.slice(0, 20) }, null, 2));
  process.exit(failures.length ? 1 : 0);
}

main();
