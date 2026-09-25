/**
 * UI simplification behaviour scenes against the LOCAL dev harness only (spec §37: first-run empty states and the
 * shared connection status). Real pages, real API, real rendering; only the channel-state scenes rewrite the one
 * /channels response in the browser to reach states a fresh connection cannot.
 *
 *   RAFII_WEB_URL=http://127.0.0.1:4439 node web/tests/ui-simplification-browser.cjs
 *
 * Empty states: a short title, at most one short sentence, at most one action — and that action appears nowhere else
 * on the page (the header does not repeat what the empty state owns). Connection status: the words shown are the
 * shared `STATUS` vocabulary from src/lib/status-labels.ts, never a sentence. Writes nothing to the repository.
 */
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { chromium } = require('playwright');

const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:4439';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('These scenes run against the local harness only.');
const executablePath = process.env.RAFII_CHROMIUM_PATH || undefined;

/** The shared status words, read from the source the components import. */
const STATUS = Object.fromEntries(
  [...fs.readFileSync(path.resolve(__dirname, '../src/lib/status-labels.ts'), 'utf8').matchAll(/^\s+(\w+): '([^']+)',?$/gm)].map((m) => [m[1], m[2]])
);
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS_SEEN = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok) });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 400)}` : ''}\n`);
}
const words = (text) => (text || '').trim().split(/\s+/).filter(Boolean).length;

async function api(principal, method, url, body) {
  const res = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${text.slice(0, 200)}`);
  return JSON.parse(text);
}

async function open(browser, principal, width, errors) {
  const context = await browser.newContext({ viewport: { width, height: width > 500 ? 1000 : 844 }, reducedMotion: 'reduce' });
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base }
  ]);
  await context.addInitScript(({ id, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
  }, { id: principal, tours: TOURS_SEEN });
  await context.route('**/*', (route) => (new URL(route.request().url()).origin !== new URL(base).origin ? route.abort() : route.continue()));
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => message.type() === 'error' && errors.push(message.text()));
  return { context, page };
}

/**
 * The page's empty state (`StateMessage` panel: role=status, a title paragraph, optional sentence and actions) and
 * every visible action on the page with the same accessible name, counted over the whole document.
 */
async function readEmptyState(page, title) {
  const state = page.locator('main [role="status"]').filter({ has: page.getByText(title, { exact: true }) }).first();
  await state.waitFor();
  const texts = await state.locator('p').allInnerTexts();
  const actions = state.locator('a:visible, button:visible');
  const names = [];
  for (let i = 0; i < (await actions.count()); i += 1) names.push((await actions.nth(i).innerText()).trim());
  const elsewhere = {};
  for (const name of names) {
    const all = page.locator('a:visible, button:visible').filter({ hasText: new RegExp(`^\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*$`) });
    elsewhere[name] = await all.count();
  }
  return { title: texts[0], description: texts[1] ?? null, actions: names, counts: elsewhere };
}

const EMPTY = [
  { route: '/app/queue', title: 'Nothing scheduled', action: 'Connect account' },
  { route: '/app/automations', title: 'No automations yet', action: 'New automation' },
  { route: '/app/channels', title: 'No accounts connected', action: 'Connect account' }
];

async function emptyStates(browser) {
  const principal = randomUUID();
  await api(principal, 'POST', '/api/auth/verify', {});
  for (const width of [1440, 390]) {
    const errors = [];
    const { context, page } = await open(browser, principal, width, errors);
    for (const scene of EMPTY) {
      await page.goto(base + scene.route, { waitUntil: 'domcontentloaded' });
      const state = await readEmptyState(page, scene.title);
      const tag = `[${width}] ${scene.route}`;
      check(`${tag} empty state says "${scene.title}"`, state.title === scene.title, state);
      check(`${tag} title is short`, words(state.title) <= 5, state.title);
      check(`${tag} at most one short sentence under the title`, state.description === null || words(state.description) <= 12, state.description);
      check(`${tag} one primary action: ${scene.action}`, state.actions.length === 1 && state.actions[0].includes(scene.action), state.actions);
      check(`${tag} the header does not repeat the empty state's action`, Object.values(state.counts).every((n) => n === 1), state.counts);
      check(`${tag} no horizontal overflow`, !(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)));
    }
    // Usage & plan on a new workspace: the plan in one glance, nothing about how billing is built.
    await page.goto(`${base}/app/account/billing`, { waitUntil: 'domcontentloaded' });
    const plan = page.locator('[data-tour="billing-plan"]');
    await plan.getByRole('heading', { name: 'Trial' }).waitFor();
    const planText = await plan.innerText();
    check(`[${width}] Usage & plan reads "Trial · N days left"`, /^Trial\s+\d+ days? left/m.test(planText.trim()), planText);
    const main = await page.locator('main').innerText();
    check(`[${width}] Usage & plan has no deployment, export or conversion commentary`, !/deployment|converts|exportable|billing is not enabled|current plan/i.test(main), main.slice(0, 300));
    check(`[${width}] Usage & plan does not repeat the trial end date by default`, !/ends\s+\w{3}\s+\d/i.test(await plan.locator(':scope > div').first().innerText()));
    check(`[${width}] no console or page errors`, errors.length === 0, errors);
    await context.close();
  }
}

async function connectionStatus(browser) {
  const principal = randomUUID();
  const boot = await api(principal, 'POST', '/api/auth/verify', {});
  const start = await api(principal, 'POST', `/api/workspaces/${boot.workspaceId}/channels/linkedin/oauth/start`, { capability: 'publish' });
  await api(principal, 'POST', `/api/workspaces/${boot.workspaceId}/channels/linkedin/oauth/complete`, { state: new URL(start.authorizeUrl).searchParams.get('state'), code: 'good-code' });
  const listed = await api(principal, 'GET', `/api/workspaces/${boot.workspaceId}/channels`);
  const channel = listed.channels[0];

  const errors = [];
  const { context, page } = await open(browser, principal, 1440, errors);
  let rewrite = null;
  await page.route(`**/api/workspaces/${boot.workspaceId}/channels`, async (route) => {
    if (!rewrite || route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.channels = body.channels.map((c) => (c.id === channel.id ? rewrite(c) : c));
    return route.fulfill({ response, json: body });
  });
  const card = page.locator(`[id="channel-${channel.id}"]`);
  const badge = async () => (await card.locator('header').innerText()).split('\n').map((line) => line.trim()).filter(Boolean);

  // The harness's platforms are not production-reviewed, so a fresh connection is never publish-verified there;
  // the verified states are set on the one /channels response, the way the API reports them in production.
  const month = () => Date.now() / 1000 + 30 * 86400;
  rewrite = (c) => ({ ...c, connectionState: 'publish_verified', expiresAt: month() });
  await page.goto(`${base}/app/channels`, { waitUntil: 'domcontentloaded' });
  await card.getByText(STATUS.connected, { exact: true }).waitFor();
  check('a live account reads "Connected" (STATUS.connected)', (await badge()).includes(STATUS.connected), await badge());
  check('the card never describes the connection in a sentence', !/successfully|currently|is connected|connection (is|was)/i.test(await card.innerText()));
  check('a connected card offers no Reconnect', (await card.getByRole('button', { name: /Reconnect/ }).count()) === 0);

  const scenes = [
    { name: 'read-only access', state: (c) => ({ ...c, connectionState: 'read_verified', expiresAt: month() }), label: STATUS.readOnly, reconnect: false, line: null },
    { name: 'expired access', state: (c) => ({ ...c, connectionState: 'token_expired', expiresAt: Date.now() / 1000 - 3600 }), label: STATUS.reconnect, reconnect: true, line: 'Access expired.' },
    { name: 'revoked access', state: (c) => ({ ...c, connectionState: 'reauthorization_required' }), label: STATUS.reconnect, reconnect: true, line: 'Access revoked.' },
    { name: 'missing permissions', state: (c) => ({ ...c, connectionState: 'scope_missing' }), label: STATUS.missingPermissions, reconnect: true, line: 'No permissions granted.' },
    {
      name: 'disconnected on purpose',
      state: (c) => ({ ...c, connectionState: 'reauthorization_required', capabilities: Object.fromEntries(Object.entries(c.capabilities).map(([k, v]) => [k, { ...v, evidence: 'Disconnected by the customer.' }])) }),
      label: STATUS.disconnected,
      reconnect: false,
      line: null
    }
  ];
  for (const scene of scenes) {
    rewrite = scene.state;
    await page.goto(`${base}/app/channels`, { waitUntil: 'domcontentloaded' });
    await card.getByText(scene.label, { exact: true }).waitFor();
    check(`${scene.name}: badge reads "${scene.label}"`, (await badge()).includes(scene.label), await badge());
    if (scene.line) check(`${scene.name}: one short line says what happened`, (await card.getByText(scene.line, { exact: true }).count()) === 1);
    if (scene.reconnect) check(`${scene.name}: Reconnect is offered`, (await card.getByRole('button', { name: /Reconnect/ }).count()) >= 1);
  }

  // Overview's Channels card reads the same words.
  rewrite = (c) => ({ ...c, connectionState: 'publish_verified', expiresAt: month() });
  await page.goto(`${base}/app/overview`, { waitUntil: 'domcontentloaded' });
  await page.getByText(STATUS.connected, { exact: true }).first().waitFor();
  check('Overview shows the same "Connected" status', (await page.getByText(STATUS.connected, { exact: true }).count()) >= 1);
  check('no console or page errors (status scenes)', errors.length === 0, errors);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath });
  try {
    await emptyStates(browser);
    await connectionStatus(browser);
  } catch (error) {
    check('scenes ran to completion', false, error.message.split('\n')[0]);
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length} checks, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
