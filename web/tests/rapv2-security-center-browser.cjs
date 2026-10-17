/**
 * RAPv2 Security Center scenes (local harness only). The profile page runs against the dev harness; the account-security
 * routes it reads are answered here with fixed synthetic bodies, so each row's state is exact and nothing is changed:
 *   RAP-016 sign-in method "Unknown"     RAP-117 375px: no sideways scroll, every action reachable
 *   RAP-118 keyboard: visible focus, Escape, focus returns   RAP-119 axe: no serious/critical issue, status in text
 *   RAP-120 reduced motion: the incident dialog is complete with no running animation
 *   RAP-121 "1 recognized browser · 2 sessions"   RAP-126 revoke-others dialog: exact count, explicit confirm/cancel
 *   RAP-127 "This wasn't me" preview: actions and irreversible effects   RAP-128 503: retry/support, never "secure"
 *   DEC-03 (owner decision 3) a workspace read refused at high risk shows "Confirm it's you", never a generic error
 *   DEC-05 (owner decision 5) the "This wasn't me" banner at the next sign-in, until dismissed
 *   node web/tests/rapv2-security-center-browser.cjs [--browser=webkit] [--out=DIR]   (RAFII_WEB_URL defaults to http://localhost:3100)
 * Writes DIR/results.json ({"rows": {"RAP-xxx": {"status", "checks"}}}) and one screenshot per scene.
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const browserName = args.browser === 'webkit' ? 'webkit' : 'chromium';
const engine = browserName === 'webkit' ? webkit : chromium;
const out = path.resolve(args.out || path.join(__dirname, '../../docs/rapv2/evidence', `security-center-${browserName}`));
const seed = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json'), 'utf8'));
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS_SEEN = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });

// The Security settings section (SettingsSection labels itself by its heading id).
const SECTION = 'section[aria-labelledby="profile-security-heading"]';
const now = Math.floor(Date.now() / 1000);
const SESSIONS = {
  sessions: [
    { sessionId: 'sess-current-000000000001', firstSeen: now - 3600, lastSeen: now, client: 'Safari on iPhone', revoked: false, current: true, signInMethod: 'unknown', location: null },
    { sessionId: 'sess-other-0000000000002', firstSeen: now - 7200, lastSeen: now - 600, client: 'Chrome on Mac', revoked: false, current: false, signInMethod: 'oauth', location: 'KKC, HK' },
    { sessionId: 'sess-other-0000000000003', firstSeen: now - 9000, lastSeen: now - 900, client: 'Chrome on Mac', revoked: false, current: false, signInMethod: 'email_code', location: null },
    { sessionId: 'sess-revoked-00000000004', firstSeen: now - 99000, lastSeen: now - 90000, client: 'Firefox on Windows', revoked: true, current: false, signInMethod: 'unknown', location: null }
  ]
};
const iso = (t) => new Date(t * 1000).toISOString().replace(/\.\d+Z$/, 'Z');
const DEVICES = {
  devices: [
    { deviceId: '11111111-1111-4111-8111-111111111111', label: 'Safari on iPhone', state: 'observed', surface: 'web', firstSeen: iso(now - 86400), lastSeen: iso(now), revokedAt: null, revokeReason: null, current: true, sessions: 2, activeSessions: 2 }
  ],
  summary: { recognizedBrowsers: 1, activeSessions: 2 }
};
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });

const rows = {};
let lastPage = null; // for the failure screenshot and text
const seen = []; // API paths the page requested (stubbed or not), for diagnosing a scene that never fills
let failures = 0;
function check(row, name, ok, detail) {
  if (!ok) failures += 1;
  rows[row] = rows[row] || { status: 'PASS', checks: [] };
  rows[row].checks.push({ name, ok: Boolean(ok), ...(ok ? {} : { detail }) });
  if (!ok) rows[row].status = 'FAIL';
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} [${row}] ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 400)}` : ''}\n`);
}

async function prepare(browser, { width = 1280, height = 900, reducedMotion = 'no-preference' } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, reducedMotion });
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base }
  ]);
  await context.addInitScript(({ id, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
  }, { id: seed.principal, tours: TOURS_SEEN });
  const page = await context.newPage();
  lastPage = page;
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) seen.push(`${request.method()} ${url.pathname}`);
  });
  page.on('pageerror', (error) => seen.push(`pageerror ${error.message.slice(0, 200)}`));
  return { context, page };
}

async function enterDev(page, url, ready) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 400000 });
  const enter = page.getByRole('button', { name: 'Enter dev workspace' });
  await ready.or(enter).first().waitFor({ timeout: 400000 });
  if (await enter.isVisible().catch(() => false)) {
    await enter.click();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 400000 });
  }
  await ready.waitFor({ timeout: 300000 });
}

async function open(browser, { width = 1280, height = 900, reducedMotion = 'no-preference', sessions = json(SESSIONS), me = null } = {}) {
  const { context, page } = await prepare(browser, { width, height, reducedMotion });
  if (me) await page.route('**/api/me', async (route) => (route.request().method() === 'GET' ? route.fulfill(json(await me(route))) : route.continue()));
  await page.route('**/api/auth/sessions', (route) => route.fulfill(sessions));
  await page.route('**/api/auth/devices', (route) => route.fulfill(json(DEVICES)));
  await page.route('**/api/auth/security/incidents', (route) => route.fulfill(json({ incidents: [] })));
  await page.route('**/api/me/security-events', (route) => route.fulfill(json({ events: [] })));
  const section = page.locator(SECTION);
  await enterDev(page, `${base}/app/account/profile`, section);
  await section.scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  return { context, page, section };
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: false });
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await engine.launch({ headless: true, executablePath: (browserName === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined });
  try {
    // --- desktop: method, device counts, revoke-others dialog, keyboard, "This wasn't me", axe ------------------------
    {
      const { context, page, section } = await open(browser);
      await section.locator('text=Signed in with >> visible=true').first().waitFor({ timeout: 60000 });
      const text = await section.innerText();
      check('RAP-016', 'the current session reads "Unknown", never a guessed method', /Safari on iPhone[\s\S]*Unknown/.test(text), text.slice(0, 400));
      check('RAP-016', 'recorded methods read as recorded', text.includes('Google or another provider') && text.includes('Email code'), text.slice(0, 600));
      const summary = await page.getByTestId('device-summary').innerText().catch(() => '');
      check('RAP-121', 'the Browsers view says 1 recognized browser and 2 sessions', summary.replace(/\s+/g, ' ').trim() === '1 recognized browser · 2 sessions', summary);
      await shot(page, 'desktop-security-center');

      // RAP-118 + RAP-126: keyboard to "Sign out others", Enter opens the dialog with the exact count, Escape cancels.
      const trigger = section.getByRole('button', { name: 'Sign out others' });
      await trigger.focus();
      const ring = await trigger.evaluate((el) => {
        const style = getComputedStyle(el);
        return { outline: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0, shadow: style.boxShadow !== 'none', focused: document.activeElement === el };
      });
      check('RAP-118', 'the focused trigger shows a visible focus indicator', ring.focused && (ring.outline || ring.shadow), ring);
      await page.keyboard.press('Enter');
      const dialog = page.getByRole('alertdialog');
      await dialog.waitFor({ timeout: 10000 });
      const dialogText = await dialog.innerText();
      check('RAP-126', 'the dialog states the exact number of active other sessions (2, not the revoked one)', /2 other devices will be signed out/.test(dialogText), dialogText);
      check('RAP-126', 'explicit confirm and cancel buttons', (await dialog.getByRole('button', { name: 'Sign out others' }).count()) === 1 && (await dialog.getByRole('button', { name: 'Keep them' }).count()) === 1, dialogText);
      const inside = await page.evaluate(() => Boolean(document.activeElement?.closest('[role="alertdialog"]')));
      check('RAP-118', 'focus moves into the dialog', inside);
      await shot(page, 'desktop-revoke-others-dialog');
      await page.keyboard.press('Escape');
      await dialog.waitFor({ state: 'hidden', timeout: 10000 });
      const back = await trigger.evaluate((el) => document.activeElement === el);
      check('RAP-118', 'Escape cancels and focus returns to the trigger', back);
      // Every action in the section is a real, labelled control reachable by Tab (no hover-only or hidden actions).
      const controls = await section.locator('button:visible').evaluateAll((els) => els.map((el) => ({ name: (el.getAttribute('aria-label') || el.innerText).trim(), tabbable: el.tabIndex >= 0 })));
      check('RAP-118', 'every visible action has a name and is in the tab order', controls.length > 0 && controls.every((c) => c.name && c.tabbable), controls);

      // RAP-127: the "This wasn't me" preview explains actions and what cannot be undone, before anything is sent.
      let posted = 0;
      await page.route('**/api/auth/security/incidents', (route) => {
        if (route.request().method() === 'POST') posted += 1;
        return route.fulfill(json({ incidents: [] }));
      });
      await section.getByRole('button', { name: 'This wasn’t me' }).click();
      const report = page.getByRole('alertdialog');
      await report.waitFor({ timeout: 10000 });
      const preview = (await report.innerText()).replace(/\s+/g, ' ');
      for (const [name, phrase] of [
        ['names the security hold', 'security hold'],
        ['lists what stops acting', 'scheduled posts, automations, Agent tasks and API tokens'],
        ['says approvals must be given again', 'needs your approval again'],
        ['says published posts cannot be undone', 'can’t be undone'],
        ['says connected accounts stay connected', 'stay connected'],
        ['offers signing out other sessions', 'sign out every other session']
      ]) check('RAP-127', `preview ${name}`, preview.toLowerCase().includes(phrase.toLowerCase()), preview);
      check('RAP-127', 'explicit confirm and cancel', (await report.getByRole('button', { name: 'Cancel' }).count()) === 1 && (await report.getByRole('button', { name: 'Yes, this wasn’t me' }).count()) === 1);
      await shot(page, 'desktop-not-me-preview');
      await report.getByRole('button', { name: 'Cancel' }).click();
      await report.waitFor({ state: 'hidden', timeout: 10000 });
      check('RAP-127', 'opening and cancelling the preview sends nothing', posted === 0, posted);

      // RAP-119: axe over the Security section, and status said in words (not colour alone).
      await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
      const violations = await page.evaluate(async (sel) => {
        const result = await window.axe.run(document.querySelector(sel), { resultTypes: ['violations'] });
        return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, sample: v.nodes[0]?.target }));
      }, SECTION);
      check('RAP-119', 'axe finds no serious or critical issue in the Security section', violations.length === 0, violations);
      const words = await section.innerText();
      check('RAP-119', 'session and browser states are words (this device, revoked, this browser), not colour only', ['this device', 'revoked', 'this browser'].every((w) => words.includes(w)), words.slice(0, 500));
      const named = await section.locator('ul[aria-label="Browsers"]').count();
      check('RAP-119', 'the browser list is a labelled list', named === 1);
      await context.close();
    }

    // --- iPhone width: no sideways scroll, actions reachable (RAP-117) -------------------------------------------------
    {
      const { context, page, section } = await open(browser, { width: 375, height: 812 });
      await section.locator('text=Signed in with >> visible=true').first().waitFor({ timeout: 60000 });
      const wide = await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1);
      check('RAP-117', 'no horizontal overflow at 375px', wide, await page.evaluate(() => [document.scrollingElement.scrollWidth, window.innerWidth]));
      const actions = section.locator('button:visible', { hasText: /Revoke|Sign out others|This wasn’t me/ });
      const count = await actions.count();
      const reachable = [];
      for (let i = 0; i < count; i += 1) {
        const button = actions.nth(i);
        await button.scrollIntoViewIfNeeded();
        const box = await button.boundingBox();
        reachable.push(Boolean(box && box.x >= 0 && box.x + box.width <= 376 && box.height >= 32));
      }
      check('RAP-117', 'every session and browser action is on screen and at least 32px tall', count >= 3 && reachable.every(Boolean), { count, reachable });
      await shot(page, 'iphone-375-security-center');
      await context.close();
    }

    // --- reduced motion: the incident dialog is complete without animation (RAP-120) -----------------------------------
    {
      const { context, page, section } = await open(browser, { reducedMotion: 'reduce' });
      await section.getByRole('button', { name: 'This wasn’t me' }).click();
      const report = page.getByRole('alertdialog');
      await report.waitFor({ timeout: 10000 });
      await page.waitForTimeout(400);
      const state = await page.evaluate(() => {
        const dialog = document.querySelector('[role="alertdialog"]');
        const running = document.getAnimations().filter((a) => a.playState === 'running' && (a.effect?.getTiming().iterations === Infinity));
        return { text: dialog?.innerText || '', opacity: dialog ? getComputedStyle(dialog).opacity : '0', infinite: running.length, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches };
      });
      check('RAP-120', 'the browser reports reduced motion', state.reduced);
      check('RAP-120', 'the dialog is fully shown with every effect stated', state.opacity === '1' && /security hold/i.test(state.text) && /can’t be undone/.test(state.text), state);
      check('RAP-120', 'no looping animation runs', state.infinite === 0, state.infinite);
      await shot(page, 'reduced-motion-not-me');
      await context.close();
    }

    // --- backend 503: retry and support, never "secure" (RAP-128) -----------------------------------------------------
    {
      const { context, page, section } = await open(browser, { sessions: json({ error: 'The service is temporarily unavailable.' }, 503) });
      const failed = section.locator('text=Couldn’t load sessions >> visible=true').first();
      await failed.waitFor({ timeout: 60000 });
      const text = await section.innerText();
      check('RAP-128', 'the error says sessions could not be loaded and offers Retry', (await section.getByRole('button', { name: 'Retry' }).count()) >= 1, text.slice(0, 500));
      check('RAP-128', 'it points to support and says it cannot tell whether anything is wrong', /contact support/i.test(text) && /can’t tell you whether anything is wrong/.test(text), text.slice(0, 600));
      check('RAP-128', 'nothing claims the account is secure or safe', !/\b(is secure|are secure|all secure|you’re safe|you are safe|no issues|all good)\b/i.test(text), text.slice(0, 600));
      check('RAP-128', 'the error is announced (role=alert)', (await section.locator('[role="alert"]').count()) >= 1);
      await shot(page, 'sessions-503');
      await context.close();
    }

    // --- DEC-05: the "This wasn't me" banner at the next sign-in, until dismissed ------------------------------------
    {
      const INCIDENT = '22222222-2222-4222-8222-222222222222';
      let dismissed = 0;
      const notice = { kind: 'incident_reported', incidentId: INCIDENT, reportedAt: iso(now - 3600), state: 'user_confirmed', accountHold: true, href: '/app/account/profile' };
      const { context, page } = await open(browser, {
        me: async (route) => ({ ...(await (await route.fetch()).json()), securityNotice: dismissed ? null : notice })
      });
      await page.route(`**/api/auth/security/incidents/${INCIDENT}/dismiss-notice`, (route) => {
        dismissed += 1;
        return route.fulfill(json({ incidentId: INCIDENT, dismissedAt: iso(now) }));
      });
      const banner = page.getByTestId('security-notice-banner');
      await banner.waitFor({ timeout: 60000 });
      const text = (await banner.innerText()).replace(/\s+/g, ' ');
      check('DEC-05', 'the banner says a sign-in was reported and the account is on a security hold', /You reported a sign-in that wasn’t you/.test(text) && /security hold/.test(text), text);
      check('DEC-05', 'it says what is paused and that an email was sent too', /Scheduled posts, automations, Agent tasks and API tokens are paused/.test(text) && /We also sent you an email/.test(text), text);
      check('DEC-05', 'it is a labelled region with a Review security link', (await page.getByRole('region', { name: /You reported a sign-in/ }).count()) === 1 && (await banner.getByRole('link', { name: 'Review security' }).count()) === 1);
      await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
      const violations = await page.evaluate(async () => {
        const result = await window.axe.run(document.querySelector('[data-testid="security-notice-banner"]'), { resultTypes: ['violations'] });
        return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact }));
      });
      check('DEC-05', 'axe finds no serious or critical issue in the banner', violations.length === 0, violations);
      await shot(page, 'decision-5-incident-banner');
      await banner.getByRole('button', { name: 'Dismiss' }).click();
      await banner.waitFor({ state: 'hidden', timeout: 15000 });
      check('DEC-05', 'Dismiss sends one request and the banner goes away', dismissed === 1, dismissed);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.locator(SECTION).waitFor({ timeout: 120000 });
      await page.waitForTimeout(800);
      check('DEC-05', 'after dismissing, a reload shows no banner', (await page.getByTestId('security-notice-banner').count()) === 0);
      await context.close();
    }

    // --- DEC-03: a workspace read refused at high risk asks "Confirm it's you" -----------------------------------------
    {
      const { context, page } = await prepare(browser);
      let next = 'enroll_mfa';
      let refuse = true;
      await page.route(/\/api\/workspaces\/[^/?]+(\/[^?]*)?(\?.*)?$/, (route) => {
        if (!refuse || route.request().method() !== 'GET') return route.continue();
        return route.fulfill(json({ error: 'Set up an authenticator app or security key, then confirm it’s you to continue.', code: 'security_step_up_required', nextAction: next,
                                    security: { outcome: 'step_up', riskLevel: 'high', reasonCodes: ['unknown_device', 'recent_account_change'], policyVersion: 2 } }, 403));
      });
      const screen = page.getByTestId('security-step-up');
      await enterDev(page, `${base}/app`, screen);
      const text = (await screen.innerText()).replace(/\s+/g, ' ');
      check('DEC-03', 'the refused read shows "Confirm it’s you", not a generic error', /Confirm it’s you/.test(text) && !/Couldn’t load your workspace/.test(await page.innerText('body')), text);
      check('DEC-03', 'without a second factor it says to set one up first and links there', /Set up an authenticator app or a passkey first/.test(text) && (await screen.getByRole('link', { name: 'Set up two-step sign-in' }).count()) === 1, text);
      check('DEC-03', 'it says nothing was changed and offers Try again and Sign out', /nothing was changed/.test(text) && (await screen.getByRole('button', { name: 'Try again' }).count()) === 1 && (await screen.getByRole('button', { name: 'Sign out' }).count()) === 1, text);
      check('DEC-03', 'the step-up is announced (role=alert)', (await screen.locator('[role="alert"]').count()) >= 1);
      await shot(page, 'decision-3-confirm-its-you-enroll');
      await screen.getByRole('link', { name: 'Set up two-step sign-in' }).click();
      await page.locator(SECTION).waitFor({ timeout: 120000 });
      check('DEC-03', 'account security stays reachable so a second factor can be set up', (await page.getByTestId('security-step-up').count()) === 0);
      next = 'complete_mfa';
      await page.goto(`${base}/app`, { waitUntil: 'domcontentloaded' });
      await screen.waitFor({ timeout: 120000 });
      check('DEC-03', 'with a second factor it asks for the authenticator or passkey', /authenticator app or passkey/.test(await screen.innerText()), await screen.innerText());
      refuse = false;
      await screen.getByRole('button', { name: 'Try again' }).click();
      await screen.waitFor({ state: 'hidden', timeout: 60000 });
      check('DEC-03', 'once the server allows the read again, Try again opens the workspace', (await page.getByTestId('security-step-up').count()) === 0);
      await context.close();
    }
  } finally {
    await browser.close();
  }

  const summary = { suite: 'rapv2-security-center-browser', browser: browserName, failures, rows };
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(summary, null, 1) + '\n');
  process.stdout.write(JSON.stringify({ suite: summary.suite, browser: browserName, failures, rows: Object.fromEntries(Object.entries(rows).map(([k, v]) => [k, v.status])) }) + '\n');
  process.exit(failures ? 1 : 0);
})().catch(async (error) => {
  console.error(error);
  try {
    fs.mkdirSync(out, { recursive: true });
    if (lastPage) {
      await lastPage.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => undefined);
      const text = await lastPage.locator(SECTION).innerText().catch(() => '(no Security section)');
      fs.writeFileSync(path.join(out, 'failure.txt'), `${error.stack || error}\n\n--- Security section ---\n${text}\n\n--- requests ---\n${seen.join('\n')}\n`);
      console.error(`--- Security section text ---\n${text.slice(0, 2000)}\n--- API requests ---\n${seen.slice(-60).join('\n')}`);
    }
  } catch {
    // diagnostics only
  }
  process.exit(1);
});
