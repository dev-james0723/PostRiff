/** Isolated local UI/API/SQL acceptance. Transports are fake; visual-only states use the dev fixture. */
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3397';
const visual = process.env.RAFII_VISUAL_URL || 'http://localhost:3398';
for (const url of [base, visual]) if (!['localhost', '127.0.0.1'].includes(new URL(url).hostname)) throw Error('Loopback harness only');
const root = path.resolve(__dirname, '../..');
const out = process.env.RAFII_NOTIFICATION_EVIDENCE_DIR || path.join(root, 'docs/design/founder-admin/rafii-notification-system-2026-10-03/evidence/system-browser');
fs.mkdirSync(out, { recursive: true });
const fixturePython = process.env.RAFII_PYTHON || '/tmp/rafii-notification-20261003-env/bin/python';
const fixturePort = process.env.RAFII_HARNESS_PG_PORT || '55437';

async function screenshot(page, name) {
  // The screenshot records the settled visual state, not a transition frame.
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(out, name + '.png') });
}

async function api(principal, method, url, body) {
  const response = await fetch(base + url, {
    method,
    headers: { Authorization: 'Bearer dev:' + principal, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  assert.ok(response.ok, `${method} ${url}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}

function fixture(action, principal, workspace) {
  return JSON.parse(execFileSync(fixturePython, ['tests/phase2/notification_system_browser_fixture.py', action, fixturePort, principal, workspace], {
    cwd: root, env: { ...process.env, PYTHONPATH: 'src:tests' }, encoding: 'utf8'
  }).trim().split('\n').at(-1));
}

function tourIds() {
  return [...fs.readFileSync(path.join(root, 'web/src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((match) => match[1]);
}

async function setupContext(browser, mobile = false) {
  const principal = randomUUID();
  const workspace = (await api(principal, 'POST', '/api/auth/verify', { plan: 'assist' })).workspaceId;
  const prefix = `/api/workspaces/${workspace}`;
  const snapshot = await api(principal, 'GET', prefix);
  const usage = await api(principal, 'GET', prefix + '/usage');
  // Only attention sources are neutralized for deterministic 0/1/3-card visual states.
  // Notification GET/POST requests below still use the actual SQL-backed local API.
  snapshot.state.speaker.activeRevision = 'synthetic-visual-revision';
  snapshot.state.speaker.provisional = null;
  snapshot.state.phase2.reviews = [];
  snapshot.state.phase2.jobs = [];
  snapshot.state.phase2.channels = [];
  if (snapshot.state.raffi?.campaignPlanning) snapshot.state.raffi.campaignPlanning.occurrences = [];
  usage.lifecycle.status = 'active';
  usage.entitlement.writingBatchesRemaining = 100;
  const channels = { channels: [{ id: 'synthetic-channel', platform: 'LinkedIn', account: 'Visual fixture', connectionState: 'publish_verified', capabilities: {}, evidenceSource: 'synthetic', scopes: [] }], providers: [] };
  const context = await browser.newContext({ viewport: { width: mobile ? 375 : 1280, height: mobile ? 812 : 900 }, isMobile: mobile, hasTouch: mobile });
  await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }, { name: 'postriff_theme', value: 'rafii', url: base }]);
  await context.addInitScript(({ principal, ids }) => {
    localStorage.setItem('postriff-dev-principal', principal);
    localStorage.setItem('postriff-onboarding', JSON.stringify({ completed: {}, dismissed: Object.fromEntries(ids.map((id) => [id, 1])), nudged: {} }));
  }, { principal, ids: tourIds() });
  await context.route(base + prefix, (route) => route.fulfill({ json: snapshot }));
  await context.route(base + prefix + '/channels', (route) => route.fulfill({ json: channels }));
  await context.route(base + prefix + '/usage', (route) => route.fulfill({ json: usage }));
  return { context, principal, workspace, prefix };
}

async function waitBell(page, count) {
  const bell = page.locator('header button[data-slot="popover-trigger"][aria-label^="Notifications,"]');
  await bell.waitFor();
  await page.waitForFunction((value) => {
    const text = document.querySelector('header button[data-slot="popover-trigger"][aria-label^="Notifications,"]')?.getAttribute('aria-label') || '';
    return text.includes(`, ${value} item${value === 1 ? '' : 's'}`);
  }, count, { timeout: 30000 });
  return bell;
}

async function center(page) {
  const section = page.locator('section[aria-label="Notification center"]');
  await section.waitFor();
  return section;
}

async function axe(page, selector) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(async (target) => (await axe.run(target, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } })).violations.map((item) => item.id), selector);
  assert.deepEqual(violations, []);
}

async function appRun(name, engine, mobile) {
  const browser = await engine.launch({ headless: true });
  let page;
  try {
    const { context, principal, workspace, prefix } = await setupContext(browser, mobile);
    fixture('clear', principal, workspace);
    page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(base + '/app/account/notifications', { waitUntil: 'domcontentloaded' });
    let bell = await waitBell(page, 0);
    await bell.click();
    let section = await center(page);
    await section.getByText('All caught up', { exact: true }).waitFor();
    if (!mobile) await screenshot(page, 'desktop.light.collapsed.0');
    await bell.click();

    fixture('seed-one', principal, workspace);
    await page.reload({ waitUntil: 'domcontentloaded' });
    bell = await waitBell(page, 1);
    await bell.click();
    section = await center(page);
    await section.getByText('Post published', { exact: true }).waitFor();
    if (!mobile) await screenshot(page, 'desktop.light.collapsed.1');
    await bell.click();

    fixture('seed-three', principal, workspace);
    await page.reload({ waitUntil: 'domcontentloaded' });
    bell = await waitBell(page, 3);
    await bell.click();
    section = await center(page);
    const trigger = section.getByRole('button', { name: /Expand notification stack/ });
    await trigger.waitFor();
    if (!mobile) await screenshot(page, 'desktop.light.collapsed.3');
    if (mobile) await trigger.tap();
    else { await trigger.focus(); await trigger.press('Enter'); }
    await section.getByRole('button', { name: /Collapse notification stack/ }).waitFor();
    await page.waitForTimeout(450);
    assert.deepEqual((await section.locator('h3').allTextContents()).slice(0, 3), ['Publishing failed', 'Draft needs approval', 'Post published']);
    const actionCard = section.locator('div.group').filter({ hasText: 'Draft needs approval' }).first();
    const review = actionCard.getByRole('button', { name: /Review/ });
    const read = actionCard.getByRole('button', { name: /Mark Draft needs approval as read/ });
    assert.equal(await review.count(), 1);
    assert.equal(await read.count(), 1);
    for (const button of [review, read]) assert.ok((await button.boundingBox()).height >= 43, 'Touch target must be about 44 px');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow');
    await axe(page, 'section[aria-label="Notification center"]');
    await screenshot(page, mobile ? 'mobile.webkit.expanded.375' : 'desktop.light.expanded.3');

    if (!mobile) {
      const delivery = (await api(principal, 'GET', prefix + '/notifications')).items.find((item) => item.payload.title === 'Draft needs approval');
      assert.ok(delivery);
      const actionUrl = base + `${prefix}/notifications/${delivery.id}/read`;
      await context.route(actionUrl, (route) => route.fulfill({ status: 503, json: { error: 'Synthetic action failure' } }));
      await read.click();
      await actionCard.getByRole('alert').waitFor();
      assert.equal(await read.isEnabled(), true, 'Failed action remains available');
      assert.equal((await api(principal, 'GET', prefix + '/notifications')).items.find((item) => item.id === delivery.id).status, 'delivered');
      await screenshot(page, 'desktop.failed-action');
      await context.unroute(actionUrl);
      const confirmed = page.waitForResponse((response) => response.url() === actionUrl && response.status() === 200);
      await read.click();
      await confirmed;
      assert.equal((await api(principal, 'GET', prefix + '/notifications')).items.find((item) => item.id === delivery.id).status, 'read');
      await section.getByRole('button', { name: /Mark Draft needs approval as read/ }).waitFor({ state: 'detached' });
      await page.locator('#notification-activity-heading').waitFor();
      assert.ok((await page.locator('#activity').innerText()).includes('Post published'));
      await section.getByRole('button', { name: /Collapse notification stack/ }).press('Escape');
      assert.ok(await page.evaluate(() => document.activeElement !== document.body));
      await bell.click();
      await context.route(base + prefix + '/notifications', (route) => route.fulfill({ status: 503, json: { error: 'Synthetic partial outage' } }));
      await page.reload({ waitUntil: 'domcontentloaded' });
      bell = page.locator('header button[data-slot="popover-trigger"][aria-label^="Notifications,"]');
      await bell.click();
      section = await center(page);
      await section.getByText('Some updates couldn’t load.', { exact: true }).waitFor({ timeout: 30000 });
      assert.equal(await section.getByText('All caught up', { exact: true }).count(), 0);
      await screenshot(page, 'desktop.partial-source');
      await context.unroute(base + prefix + '/notifications');
    }
    assert.deepEqual(errors, []);
    return { browser: name, mobile, status: 'PASS', workspace, action: mobile ? 'touch, keyboard, 375px, axe' : 'real SQL action failure/retry, priority, history, partial' };
  } catch (error) {
    if (page) await page.screenshot({ path: path.join(out, `${name}.${mobile ? 'mobile' : 'desktop'}.failure.png`), fullPage: true }).catch(() => undefined);
    throw error;
  } finally {
    await browser.close();
  }
}

async function visualRun() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const hydrationErrors = [];
  page.on('console', (message) => { if (/hydrated but some attributes/.test(message.text())) hydrationErrors.push(message.text()); });
  try {
    async function capture(name, query, options = {}) {
      await page.setViewportSize({ width: options.width || 1280, height: 900 });
      await page.emulateMedia({ colorScheme: options.dark ? 'dark' : 'light', reducedMotion: options.reduce ? 'reduce' : 'no-preference' });
      await page.goto(visual + '/dev/notification-system?' + query, { waitUntil: 'domcontentloaded' });
      const fixture = page.locator('main[data-ready="true"]');
      await fixture.waitFor();
      // Keep the Next development toolbar out of fixture evidence; product UI is unchanged.
      await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
      if (options.expand) {
        await page.getByRole('button', { name: /Expand notification stack/ }).click();
        await page.getByRole('button', { name: /Collapse notification stack/ }).waitFor();
      }
      if (name === 'visual.action-required.two-actions') {
        const actionCard = page.locator('div.group').filter({ hasText: 'Draft needs approval' }).first();
        await actionCard.getByRole('button', { name: 'Review drafts' }).waitFor();
        await actionCard.getByRole('button', { name: 'Mark Draft needs approval as read' }).waitFor();
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.waitForTimeout(450);
      await fixture.screenshot({ path: path.join(out, name + '.png') });
      if (options.dark || options.reduce) await axe(page, 'main');
    }
    await capture('visual.desktop.dark.collapsed.4', 'count=4', { dark: true });
    await capture('visual.action-required.two-actions', 'count=3', { expand: true });
    await page.getByText('Rafii workspace').click();
    await page.getByRole('button', { name: /Expand notification stack/ }).waitFor();
    await capture('visual.critical-security', 'count=4', { expand: true });
    await capture('visual.mobile.375.expanded', 'count=3', { width: 375, expand: true });
    await capture('visual.live.running', 'count=3&state=running');
    await capture('visual.live.waiting', 'count=3&state=waiting');
    await capture('visual.live.success', 'count=3&state=success');
    await capture('visual.reduced-motion', 'count=3&state=running', { reduce: true, expand: true });
    await capture('visual.partial-source', 'count=1&partial=1');
    await axe(page, 'main');
    assert.deepEqual(hydrationErrors, [], 'Visual fixture must hydrate cleanly, including reduced motion');
    return { visual: 'synthetic component states', status: 'PASS' };
  } finally { await browser.close(); }
}

(async () => {
  const results = [];
  results.push(await appRun('chromium', chromium, false));
  results.push(await appRun('webkit', webkit, true));
  results.push(await visualRun());
  fs.writeFileSync(path.join(out, 'browser.json'), JSON.stringify({ execution: 'actual loopback UI/API/SQL plus clearly labeled synthetic visual fixture', providerCalls: 0, results }, null, 2));
  console.log(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exitCode = 1; });
