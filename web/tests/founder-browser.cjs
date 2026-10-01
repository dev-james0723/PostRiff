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
      await h1.waitFor({ state: 'visible', timeout: 45000 });
      await settle(page, tracker);
      const title = (await h1.innerText()).trim();
      check(`${label}: heading`, heading.test(title), title);
      const body = await page.locator('body').innerText();
      check(`${label}: no fallback state`, !/is on its way|could not be drawn|Section failed/i.test(body), body.match(/[^.\n]*(is on its way|could not be drawn|Section failed)[^.\n]*/i)?.[0]);
      check(`${label}: never renders NaN or undefined`, !/\bNaN\b|\bundefined\b/.test(body), body.match(/[^\n]{0,60}\b(NaN|undefined)\b[^\n]{0,60}/)?.[0]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(`${label}: no horizontal scroll`, overflow <= 1, overflow);
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
    });
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
      for (const mode of ['live', 'demo']) await sectionPass(page, tracker, width, mode, width === 1440 || (width === 390 && mode === 'live'));

      // Deep links land on their panel or tab.
      await attempt(`${width}px ?tab= deep links`, async () => {
        await page.goto(base + '/founder/revenue?mode=demo&tab=payments');
        await page.locator('[data-tab="payments"]').waitFor({ timeout: 30000 });
        await page.waitForTimeout(600);
        const inView = await page.locator('[data-tab="payments"]').evaluate((element) => element.getBoundingClientRect().top < window.innerHeight);
        check(`${width}px revenue ?tab=payments scrolls to its panel`, inView);
        await page.goto(base + '/founder/settings?tab=reports');
        await page.getByRole('tab', { name: 'Reports', selected: true }).waitFor({ timeout: 30000 });
        check(`${width}px settings ?tab=reports selects its tab`, true);
        await page.goto(base + '/control/workspaces');
        await page.waitForURL('**/founder/customers?tab=workspaces', { timeout: 30000 });
        check(`${width}px /control/workspaces redirects to Customers`, true);
        drain(tracker);
      });

      if (width === 1440) {
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
          await page.goto(base + '/founder?mode=demo');
          await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 30000 });
          await page.getByRole('button', { name: 'Ask Rafii' }).first().click();
          const box = page.getByRole('textbox', { name: 'Ask Rafii' });
          await box.waitFor({ timeout: 15000 });
          await box.fill('Summarise the three things that need me today.');
          const turn = page.waitForResponse((response) => response.url().endsWith('/api/control/v2/agent/turns') && response.request().method() === 'POST', { timeout: 60000 });
          await page.getByRole('button', { name: 'Send' }).click();
          const response = await turn;
          check('agent turn is accepted (201)', response.status() === 201, response.status());
          await page.getByRole('article', { name: "Rafii's answer" }).first().waitFor({ timeout: 90000 });
          check('Rafii answer is rendered', true);
          await page.screenshot({ path: path.join(outDir, '1440-demo-rafii.png') });
          const seen = drain(tracker);
          check('Ask Rafii: no page error', seen.pageErrors.length === 0, seen.pageErrors);
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
