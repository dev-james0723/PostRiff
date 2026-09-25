/**
 * The Rafii coworker screens in a real browser against the LOCAL dev harness (coworker spec §12, §18, §19):
 *   - /app/weekly: set up the weekly plan in the form, prepare next week, answer the question a personal post asks,
 *     draft the waiting post, accept a ready post (it goes to Queue → Drafts; nothing reads "Scheduled");
 *   - the bell lists the server's "week ready" notification and opening it marks it read;
 *   - /app/overview shows "What needs my attention";
 *   - /app/workspace/personalization: add a voice note, turn it off and on again (read back from the API), export JSON;
 *   - /app/account/notifications: the push opt-in exists and never prompts on load (the harness has no VAPID key, so
 *     the "not turned on" state is checked first, then the preferences response is given a generated public key);
 *   - axe finds no serious or critical issue on the new pages; no page scrolls sideways at phone width; phone inputs
 *     are 16px; with reduced motion no looping animation runs on a settled page.
 *
 *   node web/tests/coworker-browser.cjs [--browser=chromium|webkit] [--out=dir] [--shots=off]
 *
 * Start the harness with the RAFII_* coworker flags and POSTRIFF_RESEARCH=0, and `next dev` on RAFII_WEB_URL
 * (default http://127.0.0.1:3390) with POSTRIFF_API_ORIGIN pointing at it. Nothing reaches a real provider; nothing is
 * approved, scheduled or published.
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID, generateKeyPairSync } = require('node:crypto');

const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:3390';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const browserName = args.browser === 'webkit' ? 'webkit' : 'chromium';
const engine = browserName === 'webkit' ? webkit : chromium;
const out = path.resolve(args.out || path.join(__dirname, '../../docs/design/site-agent/adaptive-social-coworker/web/evidence'));
fs.mkdirSync(out, { recursive: true });
const principal = randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha', Origin: base };
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const results = [];
const shot = (page, name) => (args.shots === 'off' ? null : page.screenshot({ path: path.join(out, `${browserName}-${name}`), fullPage: true }).catch((error) => check(`screenshot ${name}`, false, error.message)));
function check(name, ok, detail) {
  results.push({ browser: browserName, name, ok: Boolean(ok), detail: ok ? undefined : detail });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} [${browserName}] ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 500)}` : ''}\n`);
}

async function call(method, url, body) {
  const res = await fetch(base + url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

/** A workspace with one LinkedIn account (canned consent) and one approved source, so drafts can be checked. */
async function seed() {
  const { workspaceId } = await call('POST', '/api/auth/verify', {});
  const start = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/start`, { capability: 'publish' });
  const state = new URL(start.authorizeUrl).searchParams.get('state');
  const done = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/complete`, { state, code: 'good-code' });
  if (!done.connected) throw new Error('LinkedIn did not connect in the harness');
  let snapshot = await call('GET', `/api/workspaces/${workspaceId}`);
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, {
    expectedRevision: snapshot.revision, action: 'source',
    payload: { kind: 'text', title: 'Bakery notes', text: 'Our sourdough rests for 36 hours before baking.\nThe autumn tasting menu starts on Saturdays at the Main Street shop.\nRegulars can pre-order the Friday bake by Thursday noon.' }
  });
  const source = snapshot.state.sources.find((s) => s.title === 'Bakery notes');
  await call('POST', `/api/workspaces/${workspaceId}/actions`, { expectedRevision: snapshot.revision, action: 'approve_source', payload: { sourceId: source.id, factIds: source.facts.map((f) => f.id) } });
  const status = await call('GET', `/api/workspaces/${workspaceId}/coworker/status`);
  for (const flag of ['RAFII_WEEKLY_OPERATOR_ENABLED', 'RAFII_NOTIFICATIONS_V2_ENABLED', 'RAFII_ADAPTIVE_SKILLS_ENABLED']) {
    if (!status.flags[flag]) throw new Error(`Start the harness with ${flag}=1`);
  }
  return { workspaceId };
}

async function context(browser, viewport, extra = {}) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark', hasTouch: viewport.width < 768, isMobile: browserName === 'chromium' && viewport.width < 768, acceptDownloads: true, ...extra });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await ctx.addInitScript(({ id, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
    // Count permission prompts: the opt-in must never ask on its own.
    window.__permissionAsks = 0;
    if ('Notification' in window) {
      const original = Notification.requestPermission?.bind(Notification);
      Notification.requestPermission = (...a) => {
        window.__permissionAsks += 1;
        return original ? original(...a) : Promise.resolve('default');
      };
    }
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '.tsqd-parent-container{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: principal, tours: TOURS });
  return ctx;
}

async function open(page, route, heading) {
  await page.goto(base + route, { waitUntil: 'domcontentloaded', timeout: 400000 });
  await page.getByRole('heading', { level: 1, name: heading }).waitFor({ timeout: 400000 });
  await page.waitForTimeout(400);
}

async function axe(page, name) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run(document.querySelector('main') ?? document, { resultTypes: ['violations'] });
    return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes.slice(0, 3).map((n) => n.target.join(' ')) }));
  });
  check(`axe: no serious or critical issue on ${name}`, violations.length === 0, violations);
}

const noSideScroll = (page) => page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1);

function vapidPublicKey() {
  const { publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const jwk = publicKey.export({ format: 'jwk' });
  return Buffer.concat([Buffer.from([4]), Buffer.from(jwk.x, 'base64url'), Buffer.from(jwk.y, 'base64url')]).toString('base64url');
}

(async () => {
  const seeded = await seed();
  const w = seeded.workspaceId;
  check('seed: workspace, LinkedIn account and an approved source; coworker flags on', Boolean(w));
  const executablePath = (browserName === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    const desk = await context(browser, { width: 1440, height: 1000 });
    const page = await desk.newPage();
    const consoleErrors = [];
    page.on('pageerror', (error) => consoleErrors.push(error.message));

    // --- weekly: set up in the form --------------------------------------------------------------------------------
    await open(page, '/app/weekly', /Weekly/);
    check('weekly: the sidebar offers Weekly', (await page.getByRole('link', { name: 'Weekly' }).count()) >= 1);
    const setup = page.locator('[data-next-action="setup"]');
    await setup.waitFor({ timeout: 60000 });
    check('weekly: with no plan, the next step is "Set up your week"', /set up your week/i.test(await setup.innerText()));
    await page.getByRole('button', { name: 'Set up your week' }).first().click();
    await page.getByRole('heading', { name: 'Set up your week', exact: true }).waitFor({ timeout: 60000 });
    await page.getByRole('textbox', { name: 'Goals' }).fill('Fill the autumn tasting menu');
    await page.getByRole('checkbox', { name: /Include LinkedIn/ }).first().click();
    // How-to and a personal reflection: the personal post asks a question before Rafii writes it.
    await page.getByLabel(/^Point of view/).selectOption('0');
    await page.getByLabel(/^Building in public/).selectOption('0');
    await page.getByLabel(/^Personal reflection/).selectOption('1');
    await page.getByLabel('Writing model').selectOption('deterministic-preview');
    await page.getByLabel(/^Time zone/).selectOption('Asia/Hong_Kong');
    await shot(page, 'weekly-setup.png');
    await page.getByRole('button', { name: 'Save weekly plan' }).click();
    await page.getByRole('heading', { name: 'Weekly plan', exact: true }).waitFor({ timeout: 60000 });
    let weekly = await call('GET', `/api/workspaces/${w}/coworker/weekly`);
    const recipe = weekly.recipes[0];
    check('weekly: the plan saved from the form is read back from the API', Boolean(recipe && recipe.destinations.length === 1 && recipe.model === 'deterministic-preview' && recipe.contentMix.personal_reflection === 1), recipe);
    check('weekly: saving the plan drafts nothing', weekly.weeks.length === 0, weekly.weeks.length);

    // --- prepare next week -------------------------------------------------------------------------------------------
    await page.getByRole('tab', { name: 'This week' }).click();
    await page.getByRole('button', { name: 'Prepare next week now' }).first().click();
    await page.locator('article[data-slot-status]').first().waitFor({ timeout: 240000 });
    await page.waitForTimeout(500);
    weekly = await call('GET', `/api/workspaces/${w}/coworker/weekly`);
    const week = weekly.weeks[0];
    const statuses = week.slots.map((s) => s.status);
    check('weekly: preparing plans the week and drafts what it can', statuses.includes('ready') && statuses.includes('needs_input'), statuses);
    const nextKind = await page.locator('[data-next-action]').getAttribute('data-next-action');
    check('weekly: a question comes first as the single next step', nextKind === 'answer', nextKind);
    check('weekly: the header says what is ready and what is blocked', /Ready to review/.test(await page.locator('main').innerText()) && /Blocked/.test(await page.locator('main').innerText()));
    check('weekly: posts are grouped by day', (await page.locator('main h3').count()) >= 2);
    const readyCard = page.locator('article[data-slot-status="ready"]').first();
    check('weekly: a ready post shows its draft and status in words', /Draft/.test(await readyCard.innerText()) && /Ready/.test(await readyCard.innerText()));
    await shot(page, 'weekly-prepared.png');

    // --- answer the question, then draft the waiting post -------------------------------------------------------------
    await page.getByRole('button', { name: /^Answer 1 question$/ }).click();
    const question = page.getByRole('textbox', { name: /What happened this week/ });
    await question.fill('This week a regular told us our rye tasted like her grandmother’s, and we kept the recipe exactly as it was.');
    await page.getByRole('button', { name: 'Send answer' }).click();
    await page.waitForTimeout(1500);
    weekly = await call('GET', `/api/workspaces/${w}/coworker/weekly`);
    const answered = weekly.weeks[0].slots.find((s) => s.contentType === 'personal_reflection');
    check('weekly: the answer is stored and the post leaves "needs input"', answered && answered.status === 'planned', answered && answered.status);
    // The week was already in review (the other posts were drafted). Answering reopens it, so the single next step is
    // drafting the answered post, and preparing again drafts it (never a stalled "planned" post).
    check('weekly: answering reopens the week for drafting', weekly.weeks[0].state === 'generating', weekly.weeks[0].state);
    const nextAfter = await page.locator('[data-next-action]').getAttribute('data-next-action');
    check('weekly: after the answer the next step is drafting the waiting post', nextAfter === 'continue', nextAfter);
    await page.getByRole('button', { name: 'Draft 1 waiting post' }).first().click();
    await page.locator(`#slot-${answered.id}:not([data-slot-status="planned"])`).waitFor({ timeout: 240000 });
    weekly = await call('GET', `/api/workspaces/${w}/coworker/weekly`);
    const redrafted = weekly.weeks[0].slots.find((s) => s.id === answered.id);
    check('weekly: the answered post is drafted and the week is back in review', ['ready', 'needs_revision', 'needs_asset'].includes(redrafted && redrafted.status) && weekly.weeks[0].state === 'ready_for_review',
      { slot: redrafted && redrafted.status, week: weekly.weeks[0].state });

    // --- accept one post ----------------------------------------------------------------------------------------------
    const target = page.locator('article[data-slot-status="ready"]').first();
    const slotId = (await target.getAttribute('id')).replace(/^slot-/, '');
    await target.getByRole('button', { name: 'Accept' }).click();
    const accepted = page.locator(`#slot-${slotId}[data-slot-status="accepted"]`);
    await accepted.waitFor({ timeout: 60000 });
    const acceptedText = await accepted.innerText();
    check('weekly: an accepted post says it is in Queue → Drafts, not scheduled', /Queue/.test(acceptedText) && !/\bScheduled\b/.test(acceptedText), acceptedText.slice(0, 300));
    const queueHref = await accepted.getByRole('link', { name: /Open in Queue/ }).getAttribute('href');
    check('weekly: the Queue link opens the drafts view on that draft', /^\/app\/queue\?view=drafts&draft=/.test(queueHref || ''), queueHref);
    const weekDetail = await call('GET', `/api/workspaces/${w}/coworker/weekly/weeks/${weekly.weeks[0].id}`);
    const slot = weekDetail.week.slots.find((s) => s.id === slotId);
    check('weekly: the API reads the post back as accepted (not scheduled or published)', slot && slot.status === 'accepted', slot && slot.status);
    check('weekly: "Scheduled" / "Published" appear only for posts the API says so', !(await page.locator('article[data-slot-status]:not([data-slot-status="scheduled"]):not([data-slot-status="published"])').filter({ hasText: /\b(Scheduled|Published)\b/ }).count()));
    await page.getByRole('button', { name: 'Why Rafii suggested this' }).count();
    await shot(page, 'weekly-accepted.png');
    await axe(page, '/app/weekly');

    // --- bell: the server's notification, opened and marked read -------------------------------------------------------
    const before = await call('GET', `/api/workspaces/${w}/notifications`);
    const readyNote = before.items.find((i) => i.type === 'campaign.week_ready');
    check('bell: the harness emitted "week ready"', Boolean(readyNote), before.items.map((i) => i.type));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { level: 1, name: /Weekly/ }).waitFor({ timeout: 120000 });
    const bell = page.getByRole('button', { name: /^Notifications,/ });
    await page.waitForFunction(() => /unread/.test(document.querySelector('button[aria-label^="Notifications,"]')?.getAttribute('aria-label') ?? ''), null, { timeout: 90000 }).catch(() => {});
    check('bell: the count includes unread server notifications', /unread/.test((await bell.getAttribute('aria-label')) || ''), await bell.getAttribute('aria-label'));
    await bell.click();
    const item = page.getByRole('link', { name: /Next week is ready for review/ });
    await item.waitFor({ timeout: 30000 });
    await shot(page, 'bell.png');
    await item.click();
    await page.waitForURL(/\/app\/weekly\?week=/, { timeout: 60000 });
    await page.waitForTimeout(1500);
    const after = await call('GET', `/api/workspaces/${w}/notifications`);
    check('bell: opening a notification follows its in-app link and marks it read', after.items.find((i) => i.id === readyNote?.id)?.status === 'read', after.items.map((i) => [i.type, i.status]));

    // --- overview: What needs my attention ------------------------------------------------------------------------------
    await open(page, '/app/overview', 'Overview');
    const panel = page.getByRole('region', { name: 'What needs my attention' });
    await panel.waitFor({ timeout: 60000 }).catch(() => {});
    const attention = await call('GET', `/api/workspaces/${w}/coworker/attention`);
    check('overview: "What needs my attention" lists Rafii’s items with a link', attention.items.length === 0 || ((await panel.count()) === 1 && (await panel.getByRole('link').count()) >= 1), { items: attention.items.map((i) => i.type) });
    await shot(page, 'overview-attention.png');

    // --- personalization ----------------------------------------------------------------------------------------------
    await open(page, '/app/workspace/personalization', 'Personalization');
    await page.getByRole('button', { name: 'Add a voice note' }).click();
    await page.getByRole('textbox', { name: 'New voice note' }).fill('Short sentences; no exclamation marks.');
    await page.getByRole('button', { name: 'Add note' }).click();
    const row = page.locator('li[data-origin="explicit"]').filter({ hasText: 'Short sentences; no exclamation marks.' });
    await row.waitFor({ timeout: 60000 });
    check('personalization: a note shows as "You said this" with its scope', /You said this/.test(await row.innerText()) && /Everywhere/.test(await row.innerText()));
    await row.getByRole('button', { name: /^Turn off:/ }).click();
    await row.getByText('Off', { exact: true }).waitFor({ timeout: 30000 });
    let overlays = await call('GET', `/api/workspaces/${w}/coworker/overlays`);
    check('personalization: turning a note off is read back from the API', overlays.voice[0]?.status === 'disabled', overlays.voice.map((i) => i.status));
    await row.getByRole('button', { name: /^Turn on:/ }).click();
    await row.getByText('In use', { exact: true }).waitFor({ timeout: 30000 });
    overlays = await call('GET', `/api/workspaces/${w}/coworker/overlays`);
    check('personalization: turning it back on is read back from the API', overlays.voice[0]?.status === 'active', overlays.voice.map((i) => i.status));
    const [download] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), page.getByRole('button', { name: 'Export JSON' }).click()]);
    const exported = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
    check('personalization: Export JSON downloads the overlays export', exported.schema === 'rafii.overlays-export.v1' && exported.voice.length === 1, { schema: exported.schema });
    await page.getByRole('button', { name: 'Reset my notes…' }).click();
    const dialog = page.getByRole('alertdialog');
    await dialog.waitFor({ timeout: 10000 });
    check('personalization: reset asks for confirmation first', /cannot be undone/.test(await dialog.innerText()));
    await dialog.getByRole('button', { name: 'Keep everything' }).click();
    await dialog.waitFor({ state: 'hidden', timeout: 10000 });
    overlays = await call('GET', `/api/workspaces/${w}/coworker/overlays`);
    check('personalization: cancelling the reset keeps the note', overlays.voice.length === 1);
    await page.getByRole('button', { name: 'Why Rafii suggested this' }).count();
    await shot(page, 'personalization.png');
    await axe(page, '/app/workspace/personalization');

    // --- notification settings: real harness (no VAPID key) ---------------------------------------------------------------
    await open(page, '/app/account/notifications', 'Notifications');
    await page.getByRole('heading', { name: 'Push notifications' }).waitFor({ timeout: 60000 });
    check('notifications: without a VAPID key the page says push is not turned on (no broken button)', (await page.getByText('Push notifications are not turned on for this deployment.').count()) === 1 && (await page.getByRole('button', { name: 'Turn on push notifications' }).count()) === 0);
    check('notifications: per-category choices are labelled', (await page.getByRole('combobox', { name: 'Weekly review by push' }).count()) === 1 && (await page.getByRole('switch', { name: 'Weekly review in the app' }).count()) === 1);
    await page.getByRole('combobox', { name: 'Weekly review by push' }).isDisabled();
    await page.getByRole('switch', { name: 'Comments and mentions in the app' }).click();
    await page.waitForTimeout(1200);
    const prefs = await call('GET', `/api/workspaces/${w}/notification-preferences`);
    check('notifications: a category change is stored for this workspace', prefs.rows.some((r) => r.category === 'engagement' && r.in_app === false), prefs.rows);
    await axe(page, '/app/account/notifications');

    // --- notification settings with push available (preferences response given a generated VAPID public key) ----------
    const key = vapidPublicKey();
    await page.route('**/notification-preferences', async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const response = await route.fetch();
      const body = await response.json();
      body.push = { ...body.push, available: true, vapidPublicKey: key };
      await route.fulfill({ response, json: body });
    });
    await open(page, '/app/account/notifications', 'Notifications');
    const band = page.locator('[data-push-support]');
    await band.waitFor({ timeout: 60000 });
    await page.waitForFunction(() => document.querySelector('[data-push-support]')?.getAttribute('data-push-support') !== 'checking', null, { timeout: 30000 });
    const support = await band.getAttribute('data-push-support');
    const optIn = page.getByRole('button', { name: 'Turn on push notifications' });
    if (support === 'supported') check('notifications: the push opt-in button exists when push is available', (await optIn.count()) === 1);
    else check(`notifications: this browser reports push "${support}" and shows the hint instead of a button`, (await optIn.count()) === 0 && (await band.innerText()).length > 0, support);
    await page.waitForTimeout(1500);
    const asks = await page.evaluate(() => window.__permissionAsks);
    const permission = await page.evaluate(() => ('Notification' in window ? Notification.permission : 'unsupported'));
    const registrations = await page.evaluate(async () => ('serviceWorker' in navigator ? (await navigator.serviceWorker.getRegistrations()).length : 0));
    check('notifications: nothing prompts for permission on load', asks === 0 && permission !== 'granted', { asks, permission });
    check('notifications: no service worker is registered until the person opts in', registrations === 0, registrations);
    await shot(page, 'notifications-push.png');
    await axe(page, '/app/account/notifications (push available)');
    await page.unroute('**/notification-preferences');
    check('no uncaught page errors on the desktop journey', consoleErrors.length === 0, consoleErrors.slice(0, 5));
    await desk.close();

    // --- phone: no sideways scroll, 16px inputs, reduced motion ------------------------------------------------------------
    const phone = await context(browser, { width: 390, height: 844 }, { reducedMotion: 'reduce' });
    const small = await phone.newPage();
    for (const [route, heading] of [['/app/weekly', /Weekly/], ['/app/workspace/personalization', 'Personalization'], ['/app/account/notifications', 'Notifications']]) {
      await open(small, route, heading);
      await small.waitForTimeout(800);
      check(`phone: ${route} does not scroll sideways`, await noSideScroll(small));
      const tiny = await small.evaluate(() => [...document.querySelectorAll('main input:not([type=checkbox]):not([type=hidden]), main textarea, main select')].filter((el) => el.offsetParent !== null && parseFloat(getComputedStyle(el).fontSize) < 16).map((el) => el.outerHTML.slice(0, 80)));
      check(`phone: ${route} inputs are at least 16px`, tiny.length === 0, tiny);
    }
    await open(small, '/app/weekly', /Weekly/);
    check('phone: the bottom bar offers Weekly', (await small.getByRole('navigation', { name: 'Mobile navigation' }).getByRole('link', { name: 'Weekly' }).count()) === 1);
    const reduced = await small.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
    const looping = await small.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running' && a.effect && a.effect.getTiming().iterations === Infinity)
      .map((a) => (a.effect.target && a.effect.target.className ? String(a.effect.target.className).slice(0, 80) : a.animationName || 'animation')));
    check('phone: with reduced motion no looping animation runs on the settled Weekly page', reduced && looping.length === 0, { reduced, looping });
    await shot(small, 'weekly-phone.png');
    await phone.close();
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(out, `${browserName}-results.json`), JSON.stringify({ base, principal, at: new Date().toISOString(), results }, null, 2));
  const failed = results.filter((r) => !r.ok);
  process.stdout.write(`\n${results.length - failed.length}/${results.length} checks passed in ${browserName}\n`);
  process.exit(failed.length ? 1 : 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
