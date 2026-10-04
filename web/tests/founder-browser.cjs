/**
 * Founder Admin browser scene (CONTRACTS §8.G, PRD §10.1 P0-1/P0-8, §10.5) against the LOCAL dev harness only:
 * a production build of the web app, the real Python API with Control embedded on /api/control/v2, and a disposable
 * PostgreSQL with the founder migrations and restricted roles. Identity is synthetic (scripts/postriff_dev_hosted.py
 * --founder-fixture): opaque tokens the harness maps to fictional founder/non-founder users; every request still goes
 * through the real Boundary (operator row, AAL2, cookie, CSRF, capabilities, budgets, audit). No provider is reached.
 *
 *   RAFII_WEB_URL=http://localhost:4439 RAFII_API_URL=http://127.0.0.1:4438 node web/tests/founder-browser.cjs
 *
 * Every check is recorded and the scene continues, so one run reports every failure; the exit code is 1 when any
 * check failed. Screenshots and a JSON summary go to FOUNDER_EVIDENCE_DIR (default .founder-browser-evidence/).
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const base = (process.env.RAFII_WEB_URL || 'http://localhost:4439').replace(/\/$/, '');
const apiBase = (process.env.RAFII_API_URL || 'http://127.0.0.1:4438').replace(/\/$/, '');
for (const url of [base, apiBase]) if (!['127.0.0.1', 'localhost'].includes(new URL(url).hostname)) throw new Error('The founder scene runs against the local harness only.');
const CRON = 'Bearer ' + 'd'.repeat(24);
const outDir = path.resolve(process.env.FOUNDER_EVIDENCE_DIR || path.join(__dirname, '../../.founder-browser-evidence'));
const executablePath = process.env.RAFII_CHROMIUM_PATH || undefined;
const FOUNDER = 'synthetic-founder-aal2';
const MOBILE_FOUNDER = 'synthetic-founder-mobile-aal2';
const NON_FOUNDER = 'synthetic-non-founder-aal2';
const SECTIONS = [
  ['overview', '/founder', /Overview|business|today/i],
  ['customers', '/founder/customers', /Customers/],
  ['revenue', '/founder/revenue', /Revenue/],
  ['product', '/founder/product', /Product/],
  ['ai-cost', '/founder/ai-cost', /AI/],
  ['operations', '/founder/operations', /Operations/],
  ['support', '/founder/support', /Support/],
  ['settings', '/founder/settings', /Settings/],
  ['advanced', '/founder/advanced', /Advanced/]
];
const WIDTHS = [1440, 768, 390];

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: ok ? undefined : detail });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 600)}` : ''}\n`);
  return Boolean(ok);
}

async function attempt(name, work) {
  try {
    return await work();
  } catch (error) {
    check(name, false, String(error && error.message ? error.message : error).split('\n')[0]);
    return undefined;
  }
}

async function exchange(context, token) {
  return context.request.post(base + '/api/control/v2/session/exchange', { headers: { Origin: base, Authorization: 'Bearer ' + token, 'X-Control-Exchange': '1' }, data: {} });
}

/** Wait until no /api/control request has been in flight for `quiet` ms (bounded). */
async function settle(page, tracker, quiet = 700, limit = 30000) {
  const started = Date.now();
  let calmSince = Date.now();
  while (Date.now() - started < limit) {
    if (tracker.inflight > 0) calmSince = Date.now();
    else if (Date.now() - calmSince >= quiet) return true;
    await page.waitForTimeout(100);
  }
  return false;
}

async function axe(page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async () => {
    const run = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } });
    return run.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious').map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(' ')) }));
  });
}

function track(page) {
  const tracker = { inflight: 0, consoleErrors: [], pageErrors: [], apiFailures: [], requestFailures: [] };
  page.on('request', (request) => {
    if (request.url().includes('/api/control/')) tracker.inflight += 1;
  });
  const done = (request) => {
    if (request.url().includes('/api/control/')) tracker.inflight = Math.max(0, tracker.inflight - 1);
  };
  page.on('requestfinished', done);
  page.on('requestfailed', (request) => {
    done(request);
    const reason = request.failure()?.errorText || 'failed';
    // Navigations abort the previous page's prefetches and RSC payloads; those are not failures of the page under test.
    if (reason !== 'net::ERR_ABORTED') tracker.requestFailures.push(`${reason} ${request.method()} ${request.url()}`);
  });
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/control/') && response.status() >= 400) tracker.apiFailures.push(`${response.status()} ${response.request().method()} ${url.replace(base, '')}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') tracker.consoleErrors.push(message.text().slice(0, 300));
  });
  page.on('pageerror', (error) => tracker.pageErrors.push(String(error.message || error).slice(0, 300)));
  return tracker;
}

function drain(tracker) {
  const out = { consoleErrors: tracker.consoleErrors.splice(0), pageErrors: tracker.pageErrors.splice(0), apiFailures: tracker.apiFailures.splice(0), requestFailures: tracker.requestFailures.splice(0) };
  return out;
}

async function sectionPass(page, tracker, width, mode, axeHere) {
  for (const [id, url, heading] of SECTIONS) {
    const target = base + url + (mode === 'demo' ? '?mode=demo' : '');
    const label = `${width}px ${mode} ${id}`;
    await attempt(`${label}: page opens`, async () => {
      await page.goto(target, { waitUntil: 'domcontentloaded' });
      const h1 = page.getByRole('heading', { level: 1 }).first();
      try {
        await h1.waitFor({ state: 'visible', timeout: 45000 });
      } catch (error) {
        // Record what the page shows instead, so a CI run explains itself.
        fs.mkdirSync(outDir, { recursive: true });
        await page.screenshot({ path: path.join(outDir, `FAIL-${width}-${mode}-${id}.png`), fullPage: true }).catch(() => {});
        const seen = await page.evaluate(() => ({ url: location.href, title: document.title,
          headings: [...document.querySelectorAll('h1,h2')].slice(0, 6).map((h) => ({ tag: h.tagName, text: h.textContent.trim().slice(0, 60), visible: h.getBoundingClientRect().height > 0 && getComputedStyle(h).visibility !== 'hidden', hidden: Boolean(h.closest('[aria-hidden="true"],[inert]')) })),
          dialogs: [...document.querySelectorAll('[role="dialog"]')].map((d) => (d.getAttribute('aria-label') || d.textContent.trim()).slice(0, 60)),
          text: document.body.innerText.slice(0, 300) })).catch(() => null);
        check(`${label}: page state when the heading did not appear`, false, { ...seen, api: drain(tracker) });
        throw error;
      }
      await settle(page, tracker);
      const title = (await h1.innerText()).trim();
      check(`${label}: heading`, heading.test(title), title);
      const body = await page.locator('body').innerText();
      check(`${label}: no fallback state`, !/is on its way|could not be drawn|Section failed/i.test(body), body.match(/[^.\n]*(is on its way|could not be drawn|Section failed)[^.\n]*/i)?.[0]);
      check(`${label}: never renders NaN or undefined`, !/\bNaN\b|\bundefined\b/.test(body), body.match(/[^\n]{0,60}\b(NaN|undefined)\b[^\n]{0,60}/)?.[0]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      let culprits;
      if (overflow > 1) {
        // Name what sticks out: the widest and the narrowest elements whose right edge passes the viewport.
        culprits = await page.evaluate(() => {
          // The rightmost elements past the viewport, with their positioning: an absolutely positioned element escapes a
          // scroller that is not its containing block, so position matters more than the DOM ancestry here.
          const limit = window.innerWidth + 1;
          const out = [];
          for (const element of document.querySelectorAll('body *')) {
            const rect = element.getBoundingClientRect();
            if (rect.width > 0 && rect.right > limit) {
              const cls = typeof element.className === 'string' ? element.className : '';
              const style = getComputedStyle(element);
              out.push({ tag: element.tagName.toLowerCase(), cls: cls.slice(0, 120), role: element.getAttribute('role'), label: element.getAttribute('aria-label'),
                         position: style.position, right: Math.round(rect.right), width: Math.round(rect.width), text: (element.textContent || '').trim().slice(0, 40) });
            }
          }
          out.sort((a, b) => b.right - a.right || a.width - b.width);
          return out.slice(0, 6);
        });
      }
      check(`${label}: no horizontal scroll`, overflow <= 1, { overflow, culprits });
      if (axeHere) {
        const violations = await axe(page);
        check(`${label}: axe without critical/serious violations`, violations.length === 0, violations);
      }
      fs.mkdirSync(outDir, { recursive: true });
      await page.screenshot({ path: path.join(outDir, `${width}-${mode}-${id}.png`), fullPage: true });
      const seen = drain(tracker);
      check(`${label}: no failed control request`, seen.apiFailures.length === 0, seen.apiFailures);
      check(`${label}: no page error`, seen.pageErrors.length === 0, seen.pageErrors);
      check(`${label}: no console error`, seen.consoleErrors.length === 0, seen.consoleErrors);
      check(`${label}: no failed request`, seen.requestFailures.length === 0, seen.requestFailures);
      if (id === 'customers') await customerDetailPass(page, tracker, width, mode);
    });
  }
}

/** The same selected account's metadata must open in Customer 360 in both modes, at every viewport. */
async function customerDetailPass(page, tracker, width, mode) {
  const label = `${width}px ${mode} Customer 360`;
  await attempt(`${label}: opens`, async () => {
    const open = page.locator('tbody button[aria-label^="Open "]').first();
    await open.waitFor();
    const name = (await open.getAttribute('aria-label')).slice(5);
    const fetched = page.waitForResponse((response) => {
      if (!response.url().endsWith(`/workspace/${mode}/query`) || response.request().method() !== 'POST') return false;
      return Boolean(response.request().postDataJSON()?.recordId);
    });
    await open.click();
    const response = await fetched;
    const payload = await response.json();
    check(`${label}: real detail API succeeds`, response.status() === 200, payload.code);
    const data = payload.data;
    check(`${label}: detail returns linked records`, Boolean(data?.linkedRecords), payload.code);
    if (!data?.linkedRecords) return;
    const linked = data.linkedRecords;
    const selected = response.request().postDataJSON().recordId;
    check(`${label}: exact selected account returned`, data.rows?.[0]?.id === selected, data.rows?.[0]?.id);
    const workspaces = new Set(data.workspaces.map((row) => row.id));
    check(`${label}: linked records belong to selected workspaces`, Object.values(linked).flat().every((row) => !row.workspaceId || workspaces.has(row.workspaceId)));
    const dialog = page.locator('[role="dialog"][aria-label="Customer 360"]');
    await dialog.getByRole('heading').filter({ hasText: name }).waitFor();
    await settle(page, tracker);
    check(`${label}: displays selected name`, (await dialog.innerText()).includes(name));
    if (mode === 'demo') {
      const liveBefore = (await (await page.context().request.get(base + '/api/control/v2/workspace/live')).json()).data;
      const actions = dialog.getByRole('region', { name: 'Demo workspace actions' });
      const input = actions.getByRole('textbox', { name: 'Sample workspace name' });
      const original = await input.inputValue();
      const sample = 'Fictional browser workspace ' + width;
      await input.fill(sample);
      await actions.getByRole('button', { name: 'Save sample workspace', exact: true }).click();
      await actions.getByRole('status').filter({ hasText: 'Sample workspace saved.' }).waitFor();
      const body = { collection: 'customers', search: '', status: 'all', page: 1, recordId: selected };
      const persisted = await (await page.context().request.post(base + '/api/control/v2/workspace/demo/query', { headers: { Origin: base, 'X-CSRF-Token': (await (await page.context().request.get(base + '/api/control/v2/session')).json()).data.csrfToken }, data: body })).json();
      check(`${label}: sandbox rename persists through the real API`, persisted.data.workspaces[0].name === sample, persisted.code);
      await actions.getByRole('button', { name: 'Reset my Demo', exact: true }).click();
      await actions.getByRole('status').filter({ hasText: 'Your Demo changes were reset.' }).waitFor();
      check(`${label}: reset restores the original linked sample`, await input.inputValue() === original);
      const liveAfter = (await (await page.context().request.get(base + '/api/control/v2/workspace/live')).json()).data;
      check(`${label}: Demo actions leave canonical Live workspaces unchanged`, JSON.stringify(liveBefore.workspaces) === JSON.stringify(liveAfter.workspaces));
    } else {
      check(`${label}: Live never offers a Demo mutation`, await dialog.getByRole('region', { name: 'Demo workspace actions' }).count() === 0);
    }
    for (const tab of ['Billing', 'Usage & AI cost', 'Connections', 'Support', 'Activity', 'Advanced']) {
      await dialog.getByRole('tab', { name: tab, exact: true }).click();
      await settle(page, tracker);
      const text = await dialog.innerText();
      check(`${label} ${tab}: wired source without historical placeholders`, !/P1|054 views|not part of the Live query yet|per-customer view is/.test(text), text.slice(-400));
      check(`${label} ${tab}: no invalid values`, !/\bNaN\b|\bundefined\b/.test(text), text.slice(-400));
      if (tab === 'Billing' && linked.invoices?.length) check(`${label}: shows the exact invoice`, text.includes(String(linked.invoices[0].number ?? linked.invoices[0].id)));
      if (tab === 'Connections' && !linked.connections) check(`${label}: missing connection source is explicit`, /not configured|not part of this Demo dataset/.test(text));
      if (tab === 'Usage & AI cost' && mode === 'live') check(`${label}: history does not invent a balance`, /verified current balance is not included/.test(text) && !/Balance after/.test(text));
      if (tab === 'Billing') await page.screenshot({ path: path.join(outDir, `${width}-${mode}-customer-billing.png`), fullPage: true });
    }
    const violations = await axe(page);
    check(`${label}: axe without critical/serious violations`, violations.length === 0, violations);
    check(`${label}: no horizontal page overflow`, await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    try {
      await page.waitForFunction((element) => element === document.activeElement, await open.elementHandle(), { timeout: 3000 });
      check(`${label}: Escape closes and returns keyboard focus`, true);
    } catch {
      check(`${label}: Escape closes and returns keyboard focus`, false, await page.evaluate(() => ({ active: document.activeElement?.outerHTML.slice(0,300), openers: [...document.querySelectorAll('[data-customer-open]')].slice(0,2).map((element) => ({ id: element.getAttribute('data-customer-open'), text: element.outerHTML.slice(0,200) })) })));
    }
    const seen = drain(tracker);
    check(`${label}: no failed control request`, seen.apiFailures.length === 0, seen.apiFailures);
    check(`${label}: no page error`, seen.pageErrors.length === 0, seen.pageErrors);
    check(`${label}: no console error`, seen.consoleErrors.length === 0, seen.consoleErrors);
  });
}

/**
 * Every tab of every section, clicked in turn: pages load a tab's queries only when it opens, so the default view alone
 * does not prove a tab is free of failed requests, errors, "NaN" or sideways scroll. The page's own tabs are the first
 * tablist in the main landmark; panels may hold nested tablists, which their own tab exercises.
 */
async function tabSweep(page, tracker, width, mode) {
  for (const [id, url] of SECTIONS) {
    const label = `${width}px ${mode} ${id}`;
    let count = 0;
    await attempt(`${label}: tabs listed`, async () => {
      await page.goto(base + url + (mode === 'demo' ? '?mode=demo' : ''), { waitUntil: 'domcontentloaded' });
      await page.getByRole('heading', { level: 1 }).first().waitFor({ state: 'visible', timeout: 45000 });
      await settle(page, tracker);
      drain(tracker);   // the default view was checked by sectionPass
      count = await page.locator('#main-content [role="tablist"]').first().locator('[role="tab"]').count();
    });
    for (let index = 0; index < count; index += 1) {
      const tab = page.locator('#main-content [role="tablist"]').first().locator('[role="tab"]').nth(index);
      const name = ((await tab.innerText().catch(() => '')) || `#${index}`).trim().replace(/\s+/g, ' ');
      const where = `${label} tab "${name}"`;
      await attempt(`${where}: opens`, async () => {
        if ((await tab.getAttribute('aria-disabled')) === 'true' || (await tab.isDisabled())) return;
        if ((await tab.getAttribute('aria-selected')) !== 'true') await tab.click();
        await settle(page, tracker);
        const body = await page.locator('#main-content').innerText();
        check(`${where}: no fallback state`, !/is on its way|could not be drawn|Section failed/i.test(body), body.match(/[^.\n]*(is on its way|could not be drawn|Section failed)[^.\n]*/i)?.[0]);
        check(`${where}: never renders NaN or undefined`, !/\bNaN\b|\bundefined\b/.test(body), body.match(/[^\n]{0,60}\b(NaN|undefined)\b[^\n]{0,60}/)?.[0]);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        check(`${where}: no horizontal scroll`, overflow <= 1, overflow);
        const seen = drain(tracker);
        if (seen.apiFailures.length || seen.pageErrors.length || seen.consoleErrors.length || overflow > 1) {
          await page.screenshot({ path: path.join(outDir, `FAIL-tab-${width}-${mode}-${id}-${index}.png`), fullPage: true }).catch(() => {});
        }
        check(`${where}: no failed control request`, seen.apiFailures.length === 0, seen.apiFailures);
        check(`${where}: no page error`, seen.pageErrors.length === 0, seen.pageErrors);
        check(`${where}: no console error`, seen.consoleErrors.length === 0, seen.consoleErrors);
      });
    }
  }
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  // One founder cron tick, so Live source health has its first probe (the deployed cron runs every minute).
  await attempt('cron tick runs the founder stage', async () => {
    const response = await fetch(apiBase + '/api/cron/worker', { headers: { Authorization: CRON } });
    const body = await response.json();
    check('cron tick runs the founder stage', response.status === 200 && body.founder && ['ok', 'partial'].includes(body.founder.status), { status: response.status, founder: body.founder && body.founder.status });
    check('cron founder stage has no unavailable stage', !Object.values(body.founder || {}).some((stage) => stage && stage.status === 'unavailable'),
      Object.fromEntries(Object.entries(body.founder || {}).filter(([, stage]) => stage && stage.status === 'unavailable')));
  });

  const browser = await chromium.launch({ headless: true, executablePath });
  try {
    // Signed out: the shell is gated, the API answers 401, a non-founder AAL2 identity is refused.
    const anonymous = await browser.newContext();
    await attempt('signed-out founder routes go to sign-in', async () => {
      const page = await anonymous.newPage();
      await page.goto(base + '/founder/revenue?tab=payments');
      check('signed-out founder routes go to sign-in', /\/founder\/sign-in\?next=/.test(page.url()), page.url());
      await page.getByRole('heading', { name: 'Sign in as the founder' }).waitFor({ timeout: 30000 });
      check('sign-in page renders', true);
      check('signed-out session is 401', (await anonymous.request.get(base + '/api/control/v2/session')).status() === 401);
      check('a consumer bearer cannot use Control', (await anonymous.request.get(base + '/api/control/v2/session', { headers: { Authorization: 'Bearer dev:00000000-0000-4000-8000-00000000f001' } })).status() === 401);
      const refused = await exchange(anonymous, NON_FOUNDER);
      check('non-founder AAL2 exchange is refused', refused.status() === 403, refused.status());
      const bogus = await exchange(anonymous, 'not-a-known-token');
      check('unknown identity exchange is refused', bogus.status() === 401, bogus.status());
    });
    await anonymous.close();

    for (const width of WIDTHS) {
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 }, reducedMotion: 'reduce' });
      const page = await context.newPage();
      const tracker = track(page);
      const login = await attempt(`${width}px founder exchange`, async () => {
        const response = await exchange(context, width === 390 ? MOBILE_FOUNDER : FOUNDER);
        check(`${width}px founder exchange`, response.status() === 200, response.status());
        const cookies = await context.cookies(base);
        check(`${width}px session cookie is host-only, HttpOnly, SameSite=Strict`, cookies.some((c) => c.name === '__Host-rafii-control' && c.httpOnly && c.sameSite === 'Strict' && c.path === '/'), cookies.map((c) => ({ name: c.name, httpOnly: c.httpOnly, sameSite: c.sameSite })));
        return (await response.json()).data;
      });
      if (!login) {
        await context.close();
        continue;
      }
      if (process.argv.includes('--customers')) {
        for (const mode of ['live', 'demo']) {
          await page.goto(base + '/founder/customers?mode=' + mode);
          await page.getByRole('heading', { name: 'Customers', exact: true }).waitFor();
          await settle(page, tracker);
          await customerDetailPass(page, tracker, width, mode);
        }
        await context.close();
        continue;
      }
      for (const mode of ['live', 'demo']) await sectionPass(page, tracker, width, mode, width === 1440 || (width === 390 && mode === 'live'));
      if (width !== 768) for (const mode of ['live', 'demo']) await tabSweep(page, tracker, width, mode);

      // Deep links land on their panel or tab.
      await attempt(`${width}px ?tab= deep links`, async () => {
        // Pages with real tabs select the named tab; pages with anchored panels scroll to the panel.
        await page.goto(base + '/founder/revenue?mode=demo&tab=payments');
        await page.getByRole('tab', { name: 'Payments', selected: true }).waitFor({ timeout: 30000 });
        check(`${width}px revenue ?tab=payments selects its tab`, true);
        await page.goto(base + '/founder/operations?mode=demo&tab=connections');
        await page.locator('[data-tab="connections"]').waitFor({ timeout: 30000 });
        await settle(page, tracker);   // panels above load after the first scroll; the page keeps the target in place
        const inView = await page.locator('[data-tab="connections"]').evaluate((element) => element.getBoundingClientRect().top < window.innerHeight);
        check(`${width}px operations ?tab=connections scrolls to its panel`, inView);
        await page.goto(base + '/founder/settings?tab=reports');
        await page.getByRole('tab', { name: 'Reports', selected: true }).waitFor({ timeout: 30000 });
        check(`${width}px settings ?tab=reports selects its tab`, true);
        await page.goto(base + '/control/workspaces');
        await page.waitForURL('**/founder/customers?tab=workspaces', { timeout: 30000 });
        check(`${width}px /control/workspaces redirects to Customers`, true);
        drain(tracker);
      });

      if (width === 1440) {
        // Hold the real Demo record read: the loading table must clear Live records immediately.
        await attempt('Live to Demo record boundary with a delayed read', async () => {
          await page.goto(base + '/founder/customers');
          await page.getByRole('heading', { name: 'Customers', exact: true }).waitFor({ timeout: 30000 });
          await settle(page, tracker);
          const openRecords = page.locator('button[aria-label^="Open "]');
          const liveLabels = await openRecords.evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label')));
          check('record boundary has a nonempty Live population', liveLabels.length > 0, liveLabels);
          if (!liveLabels.length) return;
          let releaseRead;
          const held = new Promise((resolve) => { releaseRead = resolve; });
          const pattern = '**/api/control/v2/workspace/demo/query';
          await page.route(pattern, async (route) => { await held; await route.continue(); });
          try {
            const nextRead = page.waitForRequest(pattern, { timeout: 10000 });
            await page.getByRole('radio', { name: 'Demo', exact: true }).click();
            await nextRead;
            const pendingLabels = await openRecords.evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label')));
            check('pending Demo read never displays Live rows', !pendingLabels.some((label) => liveLabels.includes(label)), pendingLabels);
            await page.screenshot({ path: path.join(outDir, '1440-demo-record-boundary-pending.png') });
          } finally {
            releaseRead();
            await settle(page, tracker);
            await page.unroute(pattern);
          }
          const demoLabels = await openRecords.evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label')));
          check('settled Demo population is nonempty and distinct from Live', demoLabels.length > 0 && !demoLabels.some((label) => liveLabels.includes(label)), demoLabels);
          const seen = drain(tracker);
          check('record boundary has no failed control request', seen.apiFailures.length === 0, seen.apiFailures);
        });

        // The real ticket APIs, original tenant and production-built controls;
        // every identity/message here is synthetic and the harness is loopback-only.
        await attempt('original-tenant support workflow and reveal scope', async () => {
          await exchange(context, FOUNDER);
          const headers = { Origin: base, 'X-PostRiff-Request': 'founder-alpha', Authorization: 'Bearer dev:00000000-0000-4000-8000-00000000f0aa' };
          const bootstrap = await context.request.post(base + '/api/auth/verify', { headers, data: { plan: 'studio' } });
          check('support customer fixture bootstraps without a provider', bootstrap.status() === 201, bootstrap.status());
          const workspace = (await bootstrap.json()).workspaceId;
          if (!workspace) throw new Error('Synthetic support tenant was not created');
          async function create(category, message) {
            const response = await context.request.post(`${base}/api/workspaces/${workspace}/support/tickets`, {
              headers, data: { requestId: require('node:crypto').randomUUID(), category, message }
            });
            check(`support ${category} ticket is created in its original tenant`, response.status() === 201, response.status());
            return (await response.json()).ticket;
          }
          const first = await create('technical', 'Synthetic browser support original A');
          const second = await create('account', 'Synthetic browser support original B');
          await page.goto(base + '/founder/support?tab=inbox');
          await page.getByRole('heading', { name: 'In-app support inbox', exact: true }).waitFor({ timeout: 30000 });
          await settle(page, tracker);
          const selectFirst = () => page.getByRole('button', { name: new RegExp(first.id.slice(-8)) }).click();
          const selectSecond = () => page.getByRole('button', { name: new RegExp(second.id.slice(-8)) }).click();
          await selectFirst();
          check('support originals are masked before reveal', !(await page.locator('body').innerText()).includes('Synthetic browser support original A'));
          await page.getByLabel('Ticket priority', { exact: true }).selectOption('urgent');
          await page.getByLabel('Ticket assignee', { exact: true }).selectOption('me');
          let pending = page.waitForResponse((r) => r.url().endsWith(`/support/tickets/${first.id}/triage`) && r.request().method() === 'POST');
          await page.getByRole('button', { name: 'Save triage', exact: true }).click();
          const triage = await pending;
          check('support triage succeeds through the protected API', triage.status() === 200, triage.status());
          await settle(page, tracker);
          const triageResult = (await triage.json()).data.ticket;
          check('support priority and self assignment are durable', triageResult.priority === 'urgent' && Boolean(triageResult.assigneeId), triageResult);
          pending = page.waitForResponse((r) => r.url().endsWith(`/support/tickets/${first.id}/reveal`) && r.request().method() === 'POST');
          await page.getByRole('button', { name: 'Reveal original support message and identity', exact: true }).click();
          const revealed = await pending;
          check('explicit recent-factor support reveal succeeds', revealed.status() === 200, revealed.status());
          await page.getByText('customer: Synthetic browser support original A', { exact: true }).waitFor({ timeout: 10000 });
          check('revealed original appears only after the deliberate action', true);

          await selectSecond();
          check('selecting another ticket clears the earlier reveal', !(await page.locator('body').innerText()).includes('Synthetic browser support original A'));
          let releaseReveal;
          const heldReveal = new Promise((resolve) => { releaseReveal = resolve; });
          const pattern = `**/api/control/v2/support/tickets/${second.id}/reveal`;
          await page.route(pattern, async (route) => { await heldReveal; await route.continue(); });
          try {
            const started = page.waitForRequest(pattern, { timeout: 10000 });
            await page.getByRole('button', { name: 'Reveal original support message and identity', exact: true }).click();
            await started;
            await selectFirst();
          } finally {
            releaseReveal();
            await settle(page, tracker);
            await page.unroute(pattern);
          }
          check('a delayed previous-ticket reveal cannot display in the new selection', !(await page.locator('body').innerText()).includes('Synthetic browser support original B'));
          await page.getByRole('button', { name: 'Reveal original support message and identity', exact: true }).click();
          await page.getByText('customer: Synthetic browser support original A', { exact: true }).waitFor({ timeout: 10000 });
          await page.getByRole('radio', { name: 'Demo', exact: true }).click();
          await settle(page, tracker);
          const demoText = await page.locator('body').innerText();
          check('Demo clears support selection and raw original content', !demoText.includes('Synthetic browser support original A') && !demoText.includes('Synthetic browser support original B'));
          await page.getByRole('radio', { name: 'Live', exact: true }).click();
          await settle(page, tracker);
          check('returning to Live does not restore a previous raw reveal', !(await page.locator('body').innerText()).includes('Synthetic browser support original A'));
          await selectFirst();
          await page.getByLabel('In-app reply', { exact: true }).fill('Synthetic Founder support reply');
          pending = page.waitForResponse((r) => r.url().endsWith(`/support/tickets/${first.id}/reply`) && r.request().method() === 'POST');
          await page.getByRole('button', { name: 'Send in-app reply', exact: true }).click();
          const sent = await pending;
          check('support reply stays in-app', sent.status() === 200 && (await sent.json()).data.delivery === 'in_app', sent.status());
          await settle(page, tracker);
          const original = await (await context.request.get(`${base}/api/workspaces/${workspace}/support/tickets/${first.id}`, { headers })).json();
          check('the original customer reads the Founder reply and its waiting state', original.messages.at(-1)?.body === 'Synthetic Founder support reply' && original.ticket.status === 'waiting_customer', original.ticket);
          check('original customer workflow includes creation triage and reply', ['created', 'triage', 'message'].every((kind) => original.history.some((event) => event.kind === kind)), original.history.map((event) => event.kind));
          await page.getByLabel('Related ticket ID', { exact: true }).fill(second.id);
          pending = page.waitForResponse((r) => r.url().endsWith(`/support/tickets/${first.id}/link`) && r.request().method() === 'POST');
          await page.getByRole('button', { name: 'Link ticket', exact: true }).click();
          const linked = await pending;
          const linkedTicket = (await linked.json()).data.ticket;
          check('support duplicate relation is durable in the original tenant', linked.status() === 200 && linkedTicket.status === 'duplicate' && linkedTicket.duplicateOfTicketId === second.id, linkedTicket);
          await settle(page, tracker);
          // The original customer UI submits one optional response for a new
          // human-supported resolution. These identities stay loopback-only.
          await selectSecond();
          await page.getByLabel('In-app reply', { exact: true }).fill('Synthetic resolution explanation');
          pending = page.waitForResponse((r) => r.url().endsWith(`/support/tickets/${second.id}/reply`) && r.request().method() === 'POST');
          await page.getByRole('button', { name: 'Send in-app reply', exact: true }).click();
          check('survey resolution receives a human in-app reply', (await pending).status() === 200);
          await settle(page, tracker);
          await page.getByLabel('Ticket status', { exact: true }).selectOption('resolved');
          pending = page.waitForResponse((r) => r.url().endsWith(`/support/tickets/${second.id}/status`) && r.request().method() === 'POST');
          await page.getByRole('button', { name: 'Update status', exact: true }).click();
          check('new observed support resolution commits through its API', (await pending).status() === 200);
          await settle(page, tracker);
          const offered = await (await context.request.get(`${base}/api/workspaces/${workspace}/support/tickets/${second.id}`, { headers })).json();
          check('the original customer receives an eligible resolution survey', offered.survey?.state === 'eligible' && offered.survey.helpful === null, offered.survey);
          const customerContext = await browser.newContext({ viewport: { width: 1440, height: 960 }, colorScheme: 'dark' });
          const customerErrors = [];
          try {
            await customerContext.addCookies([
              { name: 'postriff_dev', value: '1', url: base },
              { name: 'postriff_dev_principal', value: '00000000-0000-4000-8000-00000000f0aa', url: base },
              { name: 'postriff_theme', value: 'rafii', url: base }
            ]);
            const tourSource = fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8');
            const tours = [...tourSource.matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((match) => match[1]);
            await customerContext.addInitScript(({ ids }) => {
              localStorage.setItem('postriff-dev-principal', '00000000-0000-4000-8000-00000000f0aa');
              localStorage.setItem('postriff-onboarding', JSON.stringify({ completed: {}, dismissed: Object.fromEntries(ids.map((id) => [id, 1])), nudged: Object.fromEntries(ids.map((id) => [id, 1])) }));
            }, { ids: tours });
            const customerPage = await customerContext.newPage();
            customerPage.on('pageerror', (error) => customerErrors.push(String(error)));
            await customerPage.goto(base + '/app/account/profile#profile-support');
            await customerPage.getByRole('heading', { name: 'Support', exact: true }).waitFor({ timeout: 30000 });
            await customerPage.getByRole('button', { name: 'account · resolved', exact: true }).click();
            await customerPage.getByText('Was this support resolution helpful?', { exact: true }).waitFor({ timeout: 10000 });
            const feedback = customerPage.waitForResponse((r) => r.url().endsWith(`/support/tickets/${second.id}/survey`) && r.request().method() === 'POST');
            await customerPage.getByRole('button', { name: 'Yes, it helped', exact: true }).click();
            const feedbackResponse = await feedback;
            const savedFeedback = await feedbackResponse.json();
            check('customer feedback is saved by the actual original-tenant API', feedbackResponse.status() === 201 && savedFeedback.survey?.helpful === true && savedFeedback.duplicate === false, savedFeedback);
            await customerPage.getByText('Your feedback for this resolution is recorded.', { exact: true }).waitFor({ timeout: 10000 });
            check('customer feedback controls close after the recorded answer', await customerPage.getByRole('button', { name: 'Yes, it helped', exact: true }).count() === 0);
            const customerViolations = await axe(customerPage);
            check('customer support feedback has no critical or serious accessibility violations', customerViolations.length === 0, customerViolations);
            check('customer support feedback has no page error', customerErrors.length === 0, customerErrors);
          } finally {
            await customerContext.close();
          }
          await page.reload();
          await settle(page, tracker);
          const feedbackSummary = await page.locator('[aria-label="Support satisfaction summary"]').innerText();
          check('Founder feedback shows actual response and offer counts with qualified scope', feedbackSummary.includes('1 responses') && feedbackSummary.includes('1 resolution offers') && feedbackSummary.includes('100%') && feedbackSummary.includes('does not measure satisfaction across all customers'), feedbackSummary);

          const violations = await axe(page);
          check('support workflow has no critical or serious accessibility violations', violations.length === 0, violations);
          const seen = drain(tracker);
          check('support workflow has no failed control request', seen.apiFailures.length === 0, seen.apiFailures);
          check('support workflow has no page error', seen.pageErrors.length === 0, seen.pageErrors);
        });

        // Evidence drawer from a real receipt; Escape closes it and returns focus.
        await attempt('evidence drawer opens from ?evidence=', async () => {
          const overview = await (await context.request.get(base + '/api/control/v2/overview?mode=demo&period=30d')).json();
          const receipt = overview.receiptIds && overview.receiptIds[0];
          check('overview returns receipts', Boolean(receipt), overview.receiptIds);
          await page.goto(`${base}/founder?mode=demo&evidence=${receipt}`);
          const drawer = page.getByRole('dialog', { name: 'Evidence' });
          await drawer.waitFor({ timeout: 30000 });
          await settle(page, tracker);
          const text = await drawer.innerText();
          check('evidence drawer shows the receipt', text.includes(receipt.slice(0, 8)) || /receipt/i.test(text), text.slice(0, 200));
          const violations = await axe(page);
          check('evidence drawer axe without critical/serious violations', violations.length === 0, violations);
          await page.keyboard.press('Escape');
          await drawer.waitFor({ state: 'hidden', timeout: 10000 });
          check('Escape closes the evidence drawer', true);
          const seen = drain(tracker);
          check('evidence drawer: no failed control request', seen.apiFailures.length === 0, seen.apiFailures);
        });

        // Founder Rafii answers a Demo question through the founder runtime (harness model, no provider).
        await attempt('Ask Rafii answers in Demo', async () => {
          // Hold the actual session read: a slow session must preserve the draft,
          // never send into an unknown-environment thread that disappears later.
          let releaseSession;
          const sessionGate = new Promise((resolve) => { releaseSession = resolve; });
          const sessionPath = '**/api/control/v2/session';
          const holdSession = async (route) => { await sessionGate; await route.continue(); };
          await page.route(sessionPath, holdSession);
          try {
            await page.goto(base + '/founder?mode=demo');
            await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 30000 });
            await page.getByRole('button', { name: 'Ask Rafii' }).first().click();
            const box = page.getByRole('textbox', { name: 'Ask Rafii' });
            await box.waitFor({ timeout: 15000 });
            const question = 'Summarise the three things that need me today.';
            await box.fill(question);
            const send = page.getByRole('button', { name: 'Send', exact: true });
            check('Ask Rafii waits for the known session environment', await send.isDisabled());
            const suggested = page.getByRole('group', { name: 'Suggested questions' }).getByRole('button');
            check('suggested questions wait for the session environment', await suggested.count() > 0 && await suggested.evaluateAll((buttons) => buttons.every((button) => button.disabled)));
            await box.press('Enter');
            check('Enter during session loading preserves the draft', await box.inputValue() === question);
            check('Enter during session loading creates no temporary thread', !(await page.getByRole('log', { name: 'Conversation with Rafii' }).innerText()).includes(question));
            releaseSession();
            const turn = page.waitForResponse((response) => response.url().endsWith('/api/control/v2/agent/turns') && response.request().method() === 'POST', { timeout: 60000 });
            await send.click({ timeout: 30000 });
            const response = await turn;
            check('agent turn is accepted (201)', response.status() === 201, response.status());
            await page.getByRole('article', { name: "Rafii's answer" }).first().waitFor({ timeout: 90000 });
            check('Rafii answer is rendered', true);
            await page.screenshot({ path: path.join(outDir, '1440-demo-rafii.png') });
            const seen = drain(tracker);
            check('Ask Rafii: no page error', seen.pageErrors.length === 0, seen.pageErrors);
          } finally {
            releaseSession();
            await page.unroute(sessionPath, holdSession);
          }
        });

        // Founder voice: the strip opens from the panel. Voice is off in this harness, so "Talk to Rafii" is disabled and
        // says why; its status request answers 200 with blockers, never an error.
        await attempt('founder voice strip explains why voice is off', async () => {
          const toggle = page.getByRole('button', { name: 'Voice', exact: true });
          await toggle.click();
          const strip = page.getByRole('region', { name: 'Voice' });
          await strip.waitFor({ timeout: 15000 });
          await settle(page, tracker);
          const talk = strip.getByRole('button', { name: /Talk to Rafii/ });
          check('voice: Talk to Rafii is disabled while voice is off', (await talk.count()) > 0 && (await talk.first().isDisabled()), await talk.count());
          const text = await strip.innerText();
          check('voice: the strip names a reason', /[a-z]+_[a-z_]+|not enabled|turned off|off/i.test(text), text.slice(0, 200));
          await page.screenshot({ path: path.join(outDir, '1440-demo-voice.png') });
          await toggle.click();
          const seen = drain(tracker);
          check('voice: no failed control request', seen.apiFailures.length === 0, seen.apiFailures);
          check('voice: no page error', seen.pageErrors.length === 0, seen.pageErrors);
          check('voice: no console error', seen.consoleErrors.length === 0, seen.consoleErrors);
        });

        // Settings: the contact policy saves through control.settings with a fresh second factor. Delivery stays off.
        await attempt('contact policy saves', async () => {
          const again = await exchange(context, FOUNDER);   // a fresh exchange keeps the step-up window open
          check('fresh exchange for step-up', again.status() === 200, again.status());
          await page.goto(base + '/founder/settings?tab=contact');
          const save = page.getByRole('button', { name: /Save policy/ });
          await save.waitFor({ timeout: 30000 });
          await settle(page, tracker);
          const put = page.waitForResponse((response) => response.url().endsWith('/api/control/v2/contact-policy') && response.request().method() === 'PUT', { timeout: 30000 });
          await save.click();
          const response = await put;
          check('contact policy PUT succeeds', response.status() === 200, response.status());
          const policy = await (await context.request.get(base + '/api/control/v2/contact-policy')).json();
          check('live delivery stays disabled after saving', policy.data && policy.data.policy && policy.data.policy.liveDeliveryEnabled === false, policy.data && policy.data.policy);
          drain(tracker);
        });

        // The policy GET includes immutable fields; the actual form must omit them from the protected PUT.
        await attempt('Founder policy settings round trip', async () => {
          const again = await exchange(context, FOUNDER);
          check('fresh exchange for Founder policy', again.status() === 200, again.status());
          await page.goto(base + '/founder/settings?tab=budgets');
          const save = page.getByRole('button', { name: 'Save Founder settings', exact: true });
          await save.waitFor({ timeout: 30000 });
          await settle(page, tracker);
          const before = await (await context.request.get(base + '/api/control/v2/founder-policy')).json();
          await page.getByLabel('Daily cap (USD)', { exact: true }).fill('75');
          const put = page.waitForResponse((response) => response.url().endsWith('/api/control/v2/founder-policy') && response.request().method() === 'PUT', { timeout: 30000 });
          await save.click();
          const response = await put;
          check('Founder policy form PUT succeeds', response.status() === 200, response.status());
          const sent = response.request().postDataJSON();
          check('Founder policy PUT omits immutable server fields', !['version', 'revision', 'approvalRef', 'entitlement', 'financialConfirmationRequired', 'financialRetention', 'supportSource', 'customerPiiDefault'].some((key) => key in sent.changes), sent);
          const after = await response.json();
          check('Founder policy saves the edited cap and increments revision', after.data?.settings?.dailySpendUsdMicro === 75000000 && after.data?.revision === before.data.revision + 1, after.data);
          check('Founder entitlement and financial protections survive settings save', after.data?.settings?.entitlement === 'unlimited' && after.data?.settings?.financialConfirmationRequired === true && after.data?.settings?.financialRetention === 'immutable', after.data);
          const contact = await (await context.request.get(base + '/api/control/v2/contact-policy')).json();
          check('Founder policy save preserves disabled delivery', contact.data?.policy?.liveDeliveryEnabled === false, contact.data);
          await page.getByRole('status').filter({ hasText: 'Founder settings saved.' }).waitFor({ timeout: 30000 });
          drain(tracker);
        });

        // Follow-ups: a draft with a time is confirmed from the Overview; a draft is never scheduled on its own.
        await attempt('follow-up confirm', async () => {
          const session = await (await context.request.get(base + '/api/control/v2/session')).json();
          const csrf = session.data.csrfToken;
          const due = new Date(Date.now() + 26 * 3600 * 1000).toISOString();
          const title = 'Check the payment failure list ' + Date.now();
          const created = await context.request.post(base + '/api/control/v2/follow-ups', { headers: { Origin: base, 'X-CSRF-Token': csrf }, data: { title, dueAt: due, state: 'draft', sourceType: 'manual' } });
          check('follow-up draft is created', created.status() === 200, created.status());
          await page.goto(base + '/founder?tab=follow-ups');
          const confirm = page.getByRole('button', { name: `Confirm: ${title}` });
          await confirm.waitFor({ timeout: 30000 });
          const write = page.waitForResponse((response) => /\/api\/control\/v2\/follow-ups\/[^/]+$/.test(response.url()) && response.request().method() === 'POST', { timeout: 30000 });
          await confirm.click();
          check('follow-up confirm succeeds', (await write).status() === 200);
          await page.getByRole('button', { name: `Done: ${title}` }).waitFor({ timeout: 30000 });
          const listed = await (await context.request.get(base + '/api/control/v2/follow-ups')).json();
          const row = (listed.data.followUps || []).find((item) => item.title === title);
          check('follow-up is scheduled after confirm', row && row.state === 'scheduled', row);
          drain(tracker);
        });
      }

      // Sign out ends the founder session in the API, not only in the page.
      await attempt(`${width}px sign out`, async () => {
        await page.goto(base + '/founder');
        await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 30000 });
        if (width >= 768) {
          await page.getByRole('button', { name: 'Sign out' }).first().click();
        } else {
          await page.getByRole('button', { name: /menu|sidebar/i }).first().click();
          await page.getByRole('button', { name: 'Founder session' }).click();
          await page.getByRole('menuitem', { name: 'Sign out' }).click();
        }
        await page.waitForURL('**/founder/sign-in**', { timeout: 30000 });
        check(`${width}px sign out returns to sign-in`, true);
        check(`${width}px session is gone after sign out`, (await context.request.get(base + '/api/control/v2/session')).status() === 401);
      });
      await context.close();
    }
  } finally {
    await browser.close();
  }
  const failed = results.filter((result) => !result.ok);
  const summary = { execution: 'local harness: Next production build, embedded Control, disposable restricted PostgreSQL, synthetic founder identities', base, checks: results.length, failed: failed.length, failures: failed };
  fs.writeFileSync(path.join(outDir, 'founder-browser.json'), JSON.stringify(summary, null, 2));
  process.stdout.write(`\n${results.length - failed.length}/${results.length} checks passed\n`);
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
