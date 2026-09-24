/**
 * Automations, end to end against the local dev harness (real UI input, real API, real worker):
 *   node web/tests/rafii-automations.cjs [--browser=chromium|webkit] [--no-run]
 *
 * Builds an automation through the four-step builder (content type from the Content Library, today's
 * weekday a few minutes ahead in Hong Kong time, two LinkedIn accounts from the Festival folder plus a
 * second language, the fixture writer), activates it as the owner, waits for the scheduled minute and
 * triggers the harness cron, then checks the run history, the drafts it wrote, editing (back to draft),
 * activate / pause / resume / cancel, the Home panel, a phone layout and axe (WCAG 2 A/AA).
 * Drafting uses the `deterministic-preview` fixture only; nothing is scheduled or published.
 * Writes evidence/automations/<browser>/ (screenshots, video, report.json).
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
const api = process.env.RAFII_API_URL || 'http://localhost:4331';
if (![base, api].every((url) => ['127.0.0.1', 'localhost'].includes(new URL(url).hostname))) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engineName = args.browser === 'webkit' ? 'webkit' : 'chromium';
const engine = engineName === 'webkit' ? webkit : chromium;
const evidence = path.resolve(__dirname, '../../docs/design/rafii-v9/evidence');
const seed = JSON.parse(fs.readFileSync(path.join(evidence, 'seed.json'), 'utf8'));
const out = path.join(evidence, 'automations', engineName);
const MODEL = 'deterministic-preview';
const ZONE = 'Asia/Hong_Kong';
const CRON = 'd'.repeat(24); // the dev harness cron secret (scripts/postriff_dev_hosted.py)
const headers = { Authorization: `Bearer dev:${seed.principal}`, 'X-PostRiff-Request': 'founder-alpha' };
const accounts = seed.channels.filter((c) => c.platform === 'LinkedIn');
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS_SEEN = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const NAME = `Weekly practice tip ${Date.now().toString(36).slice(-4)}`;
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const report = { base, browser: engineName, workspaceId: seed.workspaceId, startedAt: new Date().toISOString(), scenes: [] };
let scene = null;
function check(name, ok, detail) {
  scene.checks.push({ name, ok: Boolean(ok), ...(detail === undefined ? {} : { detail }) });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} [${scene.name}] ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 500)}` : ''}\n`);
}

async function open(browser, name, { width = 1440, height = 1000, theme = 'dark' } = {}) {
  const dir = path.join(out, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: theme, timezoneId: 'America/New_York', recordVideo: { dir, size: { width, height } } });
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base },
    { name: 'active_theme', value: 'rafii', url: base }
  ]);
  await context.addInitScript(({ id, theme, model, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('theme', theme);
    localStorage.setItem('postriff-onboarding', tours);
    localStorage.setItem('postriff-agent-model', model);
  }, { id: seed.principal, theme, model: MODEL, tours: TOURS_SEEN });
  await context.route('**/*', async (route) => {
    const request = route.request();
    if (new URL(request.url()).origin !== new URL(base).origin) {
      scene?.blocked.push(request.url().slice(0, 160));
      return route.abort();
    }
    // An automation may only be saved with the fixture writer; anything else never reaches the server.
    if (request.method() === 'POST' && /\/actions$/.test(request.url())) {
      let body = {};
      try { body = JSON.parse(request.postData() || '{}'); } catch { /* not json */ }
      if (body.action === 'raffi_recurrence_save' && body.payload?.route !== MODEL) {
        scene?.checks.push({ name: 'automation save blocked: non-fixture writer', ok: false, detail: body.payload?.route });
        return route.abort();
      }
    }
    return route.continue();
  });
  context.setDefaultTimeout(90000);
  const page = await context.newPage();
  scene = { name, viewport: `${width}x${height}`, theme, checks: [], errors: [], blocked: [], screenshots: [], axe: [], video: null, t0: Date.now() };
  report.scenes.push(scene);
  const where = () => { try { return new URL(page.url()).pathname; } catch { return '?'; } };
  page.on('pageerror', (e) => scene.errors.push(`pageerror at ${where()}: ${e.message}`));
  page.on('console', (m) => m.type() === 'error' && !/Download the React DevTools|net::ERR_FAILED/.test(m.text()) && scene.errors.push(`console at ${where()}: ${m.text().slice(0, 300)}`));
  return { context, page, dir };
}

async function close({ context, page, dir }) {
  const video = page.video();
  await context.close();
  if (video) {
    const named = path.join(dir, `${scene.name}.webm`);
    fs.renameSync(await video.path(), named);
    scene.video = path.relative(evidence, named);
  }
  scene.durationSeconds = Number(((Date.now() - scene.t0) / 1000).toFixed(1));
}

async function shot(page, dir, label) {
  const file = path.join(dir, `${label}.png`);
  await page.screenshot({ path: file });
  scene.screenshots.push(path.relative(evidence, file));
}

async function axe(page, label) {
  await page.addScriptTag({ content: axeSource });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run(document, { runOnly: ['wcag2a', 'wcag2aa'], resultTypes: ['violations'] });
    return result.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(' ')) }));
  });
  scene.axe.push({ label, violations });
  check(`axe clean: ${label}`, violations.length === 0, violations);
}

async function settle(page) {
  const enter = page.getByRole('button', { name: 'Enter dev workspace' });
  if (await enter.count()) {
    await enter.click();
    await page.waitForLoadState('domcontentloaded');
  }
  for (const name of ['Not now', 'Skip tour']) {
    const button = page.getByRole('button', { name, exact: true });
    if (await button.count()) await button.first().click().catch(() => {});
  }
}

/** Wait for the app (or its dev sign-in gate) to render, then pass the gate if it shows. */
async function arrive(page, ready) {
  const enter = page.getByRole('button', { name: 'Enter dev workspace' });
  await ready.or(enter).first().waitFor({ timeout: 400000 });
  if (await enter.isVisible().catch(() => false)) {
    await enter.click();
    await ready.first().waitFor({ timeout: 300000 });
  }
  await settle(page);
}

async function gotoHub(page) {
  // A loaded machine can take minutes to compile a route; wait for the page itself, not network silence.
  await page.goto(`${base}/app/automations`, { waitUntil: 'domcontentloaded', timeout: 400000 });
  await arrive(page, page.getByRole('heading', { name: 'Automations', level: 1 }));
  await page.getByText(/No automations yet|Active/).first().waitFor({ timeout: 120000 });
  await page.waitForTimeout(600);
}

const snapshot = async (page) => (await (await page.request.get(`${base}/api/workspaces/${seed.workspaceId}`, { headers })).json()).state;
const ours = async (page) => {
  const planning = (await snapshot(page)).raffi?.campaignPlanning ?? { recurringTasks: [], occurrences: [], campaigns: [] };
  const task = planning.recurringTasks.findLast((t) => t.name === NAME);
  return { task, planning, runs: planning.occurrences.filter((o) => o.taskId === task?.id) };
};
const card = (page) => page.locator('article').filter({ has: page.getByRole('heading', { name: NAME }) });
const overflow = (page) => page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);

/** Today's weekday and a wall time `minutes` ahead in `zone` (the automation's first run). */
function soon(minutes, zone) {
  const at = new Date(Date.now() + minutes * 60000);
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: zone, weekday: 'long', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(at).map((p) => [p.type, p.value]));
  return { weekday: parts.weekday, time: `${parts.hour}:${parts.minute}` };
}

async function chooseContent(page, builder, editorial, native) {
  await builder.getByRole('button', { name: /^(Choose|Change)$/ }).click();
  const library = page.getByRole('dialog').filter({ has: page.locator('[data-library-item]') }).last();
  await library.getByRole('tab', { name: /editorial type/ }).click();
  await library.locator(`[data-library-item="${editorial}"]`).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(400);
  await library.locator(`[data-library-item="${editorial}"]`).first().click();
  await library.getByRole('tab', { name: /native format/ }).click();
  await page.waitForTimeout(500);
  await library.locator(`[data-library-item="${native}"]`).first().click();
  await library.getByRole('button', { name: /^Use these choices/ }).click();
  await library.waitFor({ state: 'hidden' });
}

async function build(browser) {
  const s = await open(browser, 'build-and-run');
  const { page, dir } = s;
  try {
    await gotoHub(page);
    const before = await ours(page);
    check('no automation with this name yet', !before.task);
    await shot(page, dir, '01-hub-before');

    await page.getByRole('button', { name: 'New automation' }).first().click();
    const builder = page.getByRole('dialog', { name: /automation/i }).first();
    await builder.getByLabel('Name', { exact: true }).waitFor();
    await page.waitForTimeout(500);
    await builder.getByLabel('Name', { exact: true }).fill(NAME);
    // Channels and times inside the brief are text, never settings (checked on the server after the run).
    await builder.getByLabel('What should each draft be about?').fill('One practical practice tip for adult piano students. Share it on Instagram at 8pm tomorrow.');
    await builder.getByLabel('Who is it for?').fill('Adult beginners and parents of young students');
    await chooseContent(page, builder, 'behind_the_scenes', 'carousel');
    check('content type chip shows the Library choice', /Behind the scenes/.test(await builder.innerText()) && /Carousel/.test(await builder.innerText()));
    await shot(page, dir, '02-builder-what');
    await axe(page, 'builder: what');

    await builder.getByRole('tab', { name: /When/ }).click();
    // Far enough ahead that a slow machine still saves and activates before the minute arrives.
    const when = soon(8, ZONE);
    for (const day of ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']) {
      const button = builder.getByRole('button', { name: day, exact: true });
      const pressed = (await button.getAttribute('aria-pressed')) === 'true';
      if (pressed !== (day === when.weekday)) await button.click();
    }
    await builder.getByLabel('At', { exact: true }).fill(when.time);
    await builder.getByLabel('Time zone').selectOption(ZONE);
    await page.waitForTimeout(400);
    const whenText = await builder.innerText();
    check('schedule preview names the day, time and zone', whenText.includes(`${when.weekday}s at`) && whenText.includes('Hong Kong time'), whenText.slice(0, 400));
    check('preview lists the first run and the viewer’s own time', /First run ·/.test(whenText) && /your time/.test(whenText));
    await shot(page, dir, '03-builder-when');

    await builder.getByRole('tab', { name: /Where/ }).click();
    await builder.getByRole('button', { name: 'Choose accounts or folders' }).click();
    const bloom = page.getByRole('dialog').filter({ has: page.getByRole('checkbox', { name: /^Festival/ }) }).last();
    await bloom.getByRole('checkbox', { name: /^Festival/ }).click();
    await page.waitForTimeout(400);
    await bloom.getByRole('button', { name: /^Done/ }).click();
    await bloom.waitFor({ state: 'hidden' });
    await page.waitForTimeout(400);
    for (const account of accounts) check(`destination listed: ${account.account}`, (await builder.innerText()).includes(account.account));
    // A second language for the first account: two drafts for it each run.
    await builder.getByRole("button", { name: `Add a language for ${accounts[0].account}`, exact: true }).click();
    const search = page.getByRole('combobox').last();
    await search.fill('Hong Kong');
    await page.waitForTimeout(300);
    await search.press('Enter');
    await page.waitForTimeout(500);
    check('three drafts each run (two accounts, one with two languages)', (await builder.innerText()).includes('3 drafts each run'), (await builder.innerText()).slice(0, 600));
    check('folder label kept for display', /From Festival/.test(await builder.innerText()));
    await shot(page, dir, '04-builder-where');

    await builder.getByRole('tab', { name: /Review/ }).click();
    await builder.getByLabel('Writer').selectOption(MODEL);
    await builder.getByLabel('Cost limit per run (USD)').fill('0');
    await page.waitForTimeout(300);
    const review = await builder.innerText();
    check('budget shows the per-run limit and the monthly ceiling', /Up to \$0\.00 a run · up to 5 runs a month · at most \$0\.00 a month/.test(review), review.slice(0, 800));
    check('nothing blocks saving', !/Choose at least|Name the automation|Describe/.test(review));
    await shot(page, dir, '05-builder-review');
    await axe(page, 'builder: review');
    await builder.getByRole('button', { name: 'Save and activate' }).click();
    await builder.waitFor({ state: 'hidden', timeout: 30000 });
    await page.waitForTimeout(800);

    const saved = await ours(page);
    const t = saved.task;
    check('saved and active on the server', t?.status === 'active' && t?.authorityVersion === 2, t && { status: t.status, authority: t.authorityVersion });
    check('schedule: today in Hong Kong at the chosen minute', JSON.stringify(t?.schedule?.weekdays) === JSON.stringify([when.weekday]) && t?.schedule?.localTime === when.time && t?.schedule?.timeZone === ZONE, t?.schedule);
    const expected = [`LinkedIn|en|${accounts[0].id}`, `LinkedIn|${t?.destinations?.[1]?.language}|${accounts[0].id}`, `LinkedIn|en|${accounts[1].id}`];
    check('three destinations: both accounts, the first in two languages', t?.destinations?.length === 3 && new Set(t.destinations.map((d) => d.channelId)).size === 2 && t.destinations.filter((d) => d.channelId === accounts[0].id).length === 2, { destinations: t?.destinations, expected });
    check('content type recorded on the automation', t?.contentType?.contentTypeId === 'pack.creator:building_in_public' && t?.contentType?.formatId === 'carousel', t?.contentType);
    check('fixture writer, quick, $0 limit', t?.route === MODEL && t?.reasoning === 'quick' && t?.maxCostUsdMicro === 0);
    check('Home content selection untouched by the automation', (await snapshot(page)).contentTypes?.selection?.contentTypeId !== 'pack.creator:building_in_public');
    await card(page).waitFor();
    check('card shows Active and the next run', /Active/.test(await card(page).innerText()) && /next run/i.test(await card(page).innerText()));
    await shot(page, dir, '06-hub-active');
    await axe(page, 'hub with an automation');

    const due = (t?.nextOccurrence?.scheduledFor ?? 0) * 1000;
    check('first run is within minutes (today, not next week)', due > Date.now() && due - Date.now() < 15 * 60000, t?.nextOccurrence);
    if (!args['no-run'] && due > Date.now() && due - Date.now() < 15 * 60000) {
      const wait = Math.max(0, due - Date.now()) + 4000;
      process.stdout.write(`waiting ${Math.round(wait / 1000)}s for the scheduled minute (${t.nextOccurrence.local})\n`);
      await page.waitForTimeout(wait);
      const cron = await (await fetch(`${api}/api/cron/worker`, { headers: { Authorization: `Bearer ${CRON}` } })).json();
      const prepared = cron.campaignPreparation?.runs ?? (cron.campaignPreparation ? [cron.campaignPreparation] : []);
      check('harness cron ran the automation', prepared.length === 1 && prepared[0].state === 'completed', cron.campaignPreparation ?? cron);
      const ran = await ours(page);
      const runOne = ran.runs.at(-1);
      check('one completed run with a conversation', ran.runs.length === 1 && runOne?.state === 'completed' && Boolean(runOne?.conversationId), ran.runs);
      const conversation = await (await page.request.get(`${base}/api/workspaces/${seed.workspaceId}/ideas/conversations/${runOne.conversationId}/messages`, { headers })).json();
      const assistant = (conversation.messages ?? []).filter((m) => m.role === 'assistant').at(-1)?.body ?? {};
      const platforms = (assistant.destinations ?? []).map((d) => d.platform);
      check('drafts only for the chosen accounts (brief named Instagram)', platforms.length === 3 && platforms.every((p) => p === 'LinkedIn'), assistant.destinations);
      check('no schedule plan from the time in the brief', !assistant.plan, assistant.plan);
      check('conversation titled with the automation name', (conversation.title ?? '').startsWith(NAME), conversation.title);
      const second = await (await fetch(`${api}/api/cron/worker`, { headers: { Authorization: `Bearer ${CRON}` } })).json();
      check('a second tick does not repeat the run', second.campaignPreparation?.idle === true && (await ours(page)).runs.length === 1, second.campaignPreparation);
      check('run records its draft count and cost', runOne.draftCount === 3 && runOne.costUsdMicro === 0, { draftCount: runOne.draftCount, cost: runOne.costUsdMicro });
      // The in-app digest: Home's attention list names the ready drafts until someone opens them.
      await page.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
      await arrive(page, page.getByRole('region', { name: 'Automations and Rafii suggestions' }));
      await page.waitForTimeout(800);
      check('Home attention lists the ready automation drafts', (await page.getByText(/3 automation drafts ready/).count()) > 0);
      await gotoHub(page);
      const text = await card(page).innerText();
      check('card shows the last run as Drafts ready', /Last run/.test(text) && /Drafts ready/.test(text), text.slice(0, 600));
      check('card shows 1 new run and this month’s spend', /1 new/.test(text) && /\$0\.00 spent this month/.test(text), text.slice(0, 600));
      // Personal opt-in to the "drafts ready" email.
      await card(page).getByRole('switch', { name: /Email me when drafts from/ }).click();
      await page.waitForTimeout(800);
      check('email opt-in recorded for this member only', JSON.stringify((await ours(page)).task?.emailWatchers) === JSON.stringify([seed.principal]), (await ours(page)).task?.emailWatchers);
      await card(page).getByRole('button', { name: /Run history/ }).click();
      await page.waitForTimeout(500);
      await shot(page, dir, '07-run-history');
      await card(page).getByRole('button', { name: 'Review latest drafts' }).click();
      await page.waitForURL(/\/app\/agent\//, { timeout: 60000 });
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1500);
      const body = await page.locator('main').innerText();
      check('conversation shows drafts for both accounts', accounts.every((a) => body.includes(a.account)), body.slice(0, 600));
      await shot(page, dir, '08-drafts');
      check('opening the drafts marked the run as seen', Boolean((await ours(page)).runs.at(-1)?.seenAt));
      await gotoHub(page);
      check('the new-drafts chip is gone after review', !/\b1 new\b/.test(await card(page).innerText()));
    }

    // Editing the definition returns it to draft; the owner activates it again.
    await card(page).getByRole('button', { name: 'Edit' }).click();
    const edit = page.getByRole('dialog', { name: /automation/i }).first();
    await edit.getByLabel('Name', { exact: true }).waitFor();
    await edit.getByRole('tab', { name: /When/ }).click();
    const later = soon(90, ZONE);
    await edit.getByLabel('At', { exact: true }).fill(later.time);
    await edit.getByRole('tab', { name: /Review/ }).click();
    check('edit warns that saving returns it to draft', /returns it to draft/.test(await edit.innerText()));
    await edit.getByRole('button', { name: 'Save as draft' }).click();
    await edit.waitFor({ state: 'hidden', timeout: 30000 });
    await page.waitForTimeout(600);
    const edited = (await ours(page)).task;
    check('edited definition is a draft, version 2, no activation', edited?.status === 'draft' && edited?.version === 2 && !edited?.activatedBy && edited?.schedule.localTime === later.time, edited && { status: edited.status, version: edited.version });
    check('card shows Draft and Activate', /Draft/.test(await card(page).innerText()) && (await card(page).getByRole('button', { name: 'Activate' }).count()) === 1);
    await card(page).getByRole('button', { name: 'Activate' }).click();
    await page.waitForTimeout(800);
    check('activated again', (await ours(page)).task?.status === 'active');
    await card(page).getByRole('button', { name: 'Pause' }).click();
    await page.waitForTimeout(800);
    check('paused', (await ours(page)).task?.status === 'paused' && /Paused/.test(await card(page).innerText()));
    await card(page).getByRole('button', { name: 'Resume' }).click();
    await page.waitForTimeout(800);
    check('resumed', (await ours(page)).task?.status === 'active');

    // Home lists it and links back.
    await page.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    const panel = page.getByRole('region', { name: 'Automations and Rafii suggestions' });
    await arrive(page, panel);
    await panel.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    check('Home panel lists the automation', (await panel.innerText()).includes(NAME));
    await shot(page, dir, '09-home-panel');
    await panel.getByRole('button', { name: /^Open Automations/ }).click();
    await page.waitForURL(/\/app\/automations/, { timeout: 60000 });
    await page.getByRole('heading', { name: 'Automations', level: 1 }).waitFor();

    // Cancel needs a confirmation and moves it to the cancelled list.
    await card(page).getByRole('button', { name: 'Cancel automation' }).click();
    const confirm = page.getByRole('dialog').filter({ hasText: 'No further drafts will be prepared' });
    await confirm.waitFor();
    await shot(page, dir, '10-cancel-confirm');
    await confirm.getByRole('button', { name: 'Cancel automation' }).click();
    await page.waitForTimeout(900);
    check('cancelled on the server', (await ours(page)).task?.status === 'cancelled');
    check('cancelled automation leaves the active list', (await card(page).count()) === 0 && /Cancelled \(\d+\)/.test(await page.locator('main').innerText()));
    await shot(page, dir, '11-hub-after-cancel');
  } catch (error) {
    check('build-and-run scene completed', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    await close(s);
  }
}

async function templates(browser) {
  const s = await open(browser, 'templates');
  const { page, dir } = s;
  const created = [];
  try {
    await gotoHub(page);
    const eventDay = new Date(Date.now() + 20 * 86400000);
    const eventDate = new Intl.DateTimeFormat('en-CA', { timeZone: ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(eventDay);
    for (const template of ['Event countdown', 'Monthly recap']) {
      await page.getByRole('button', { name: 'New automation' }).first().click();
      const builder = page.getByRole('dialog', { name: /automation/i }).first();
      await builder.getByLabel('Name', { exact: true }).waitFor();
      await page.waitForTimeout(500);
      await builder.getByRole('button', { name: new RegExp(`^${template}`) }).click();
      await page.waitForTimeout(300);
      check(`${template}: template fills the name`, (await builder.getByLabel('Name', { exact: true }).inputValue()) === template);
      await builder.getByLabel('Who is it for?').fill('Students and their families');
      if (template === 'Event countdown') {
        await builder.getByLabel('Venue').fill('City Hall');
        await builder.getByRole('tab', { name: /When/ }).click();
        check('countdown: schedule type selected', (await builder.getByRole('radio', { name: 'Countdown' }).getAttribute('aria-checked')) === 'true');
        check('countdown: 14 days before and on the day pressed', (await builder.getByRole('button', { name: '14 days before' }).getAttribute('aria-pressed')) === 'true' && (await builder.getByRole('button', { name: 'On the day' }).getAttribute('aria-pressed')) === 'true');
        await builder.getByLabel('Event date').fill(eventDate);
        await builder.getByLabel('Time zone').selectOption(ZONE);
        await page.waitForTimeout(400);
        check('countdown: preview lists the first run', /First run ·/.test(await builder.innerText()) && /Countdown to/.test(await builder.innerText()));
        await shot(page, dir, '01-countdown-when');
      } else {
        check('recap: published posts included', await builder.getByRole('checkbox', { name: 'Include my published posts from the last month' }).isChecked());
        await builder.getByRole('tab', { name: /When/ }).click();
        check('recap: monthly on the last day', (await builder.getByRole('radio', { name: 'Monthly' }).getAttribute('aria-checked')) === 'true' && (await builder.getByRole('button', { name: 'Last day of the month' }).getAttribute('aria-pressed')) === 'true');
        await shot(page, dir, '02-recap-when');
      }
      await builder.getByRole('tab', { name: /Where/ }).click();
      await builder.getByRole('button', { name: 'Choose accounts or folders' }).click();
      const bloom = page.getByRole('dialog').filter({ has: page.getByRole('checkbox', { name: /^Personal/ }) }).last();
      await bloom.getByRole('checkbox', { name: /^Personal/ }).click();
      await page.waitForTimeout(300);
      await bloom.getByRole('button', { name: /^Done/ }).click();
      await bloom.waitFor({ state: 'hidden' });
      await builder.getByRole('tab', { name: /Review/ }).click();
      await builder.getByLabel('Writer').selectOption(MODEL);
      await page.waitForTimeout(300);
      if (template === 'Event countdown') check('countdown budget counts the whole countdown', /for the whole countdown/.test(await builder.innerText()));
      await builder.getByRole('button', { name: 'Save as draft' }).click();
      await builder.waitFor({ state: 'hidden', timeout: 60000 });
      await page.waitForTimeout(600);
      const planning = (await snapshot(page)).raffi.campaignPlanning;
      const task = planning.recurringTasks.at(-1);
      created.push(task.id);
      const campaign = planning.campaigns.find((c) => c.id === task.campaignId);
      if (template === 'Event countdown') {
        check('countdown saved: kind, days and event date as the date fact', task.schedule.kind === 'countdown' && JSON.stringify(task.schedule.daysBefore) === '[14,7,1,0]' && task.schedule.eventDate === eventDate && campaign.facts.date === eventDate && campaign.facts.venue === 'City Hall', { schedule: task.schedule, facts: campaign.facts });
        check('countdown content type from the template', task.contentType?.contentTypeId === 'postriff:promote', task.contentType);
      } else {
        check('recap saved: monthly last day, reads 31 days of published posts', task.schedule.kind === 'monthly' && JSON.stringify(task.schedule.monthDays) === '["last"]' && task.include?.recentPostsDays === 31, { schedule: task.schedule, include: task.include });
        check('recap content type from the template', task.contentType?.contentTypeId === 'postriff:update', task.contentType);
      }
    }
    await shot(page, dir, '03-hub-with-templates');
  } catch (error) {
    check('templates scene completed', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    // Leave nothing running: cancel what this scene created (owner action through the same API).
    for (const taskId of created) {
      const current = await (await page.request.get(`${base}/api/workspaces/${seed.workspaceId}`, { headers })).json().catch(() => null);
      if (current) await page.request.post(`${base}/api/workspaces/${seed.workspaceId}/actions`, { headers, data: { expectedRevision: current.revision, action: 'raffi_recurrence_cancel', payload: { taskId, confirmed: true } } }).catch(() => {});
    }
    await close(s);
  }
}

/** Phase 3: an automation started by new material in Ideas, and the evergreen option. */
async function triggers(browser) {
  const s = await open(browser, 'triggers');
  const { page, dir } = s;
  const created = [];
  const act = async (action, payload) => {
    const current = await (await page.request.get(`${base}/api/workspaces/${seed.workspaceId}`, { headers })).json();
    return (await page.request.post(`${base}/api/workspaces/${seed.workspaceId}/actions`, { headers, data: { expectedRevision: current.revision, action, payload } })).json();
  };
  try {
    await gotoHub(page);
    for (const template of ['New idea → drafts', 'Evergreen reshare']) {
      await page.getByRole('button', { name: 'New automation' }).first().click();
      const builder = page.getByRole('dialog', { name: /automation/i }).first();
      await builder.getByLabel('Name', { exact: true }).waitFor();
      await page.waitForTimeout(500);
      await builder.getByRole('button', { name: new RegExp(`^${template}`) }).click();
      await builder.getByLabel('Who is it for?').fill('Students and their families');
      if (template === 'Evergreen reshare') {
        check('evergreen: option ticked by the template', await builder.getByRole('checkbox', { name: /fresh take each run/ }).isChecked());
        check('evergreen: 60 days minimum age', (await builder.getByRole('combobox', { name: 'Minimum age of the post to reshare' }).inputValue()) === '60');
      }
      await builder.getByRole('tab', { name: /When/ }).click();
      await page.waitForTimeout(300);
      if (template === 'New idea → drafts') {
        check('trigger: New idea selected', (await builder.getByRole('radio', { name: 'New idea' }).getAttribute('aria-checked')) === 'true');
        const pressed = async (name) => (await builder.getByRole('button', { name, exact: true }).getAttribute('aria-pressed')) === 'true';
        check('trigger: ideas, notes and links start a run; documents do not', (await pressed('Ideas')) && (await pressed('Notes')) && (await pressed('Links')) && !(await pressed('Documents')));
        check('trigger: no time to pick', (await builder.getByLabel('At', { exact: true }).count()) === 0);
        check('trigger: summary names the daily limit', /When you add a new idea, note or link to Ideas · up to 3 runs a day/.test(await builder.innerText()), (await builder.innerText()).slice(0, 400));
        await shot(page, dir, '01-trigger-when');
      }
      await builder.getByRole('tab', { name: /Where/ }).click();
      await builder.getByRole('button', { name: 'Choose accounts or folders' }).click();
      const bloom = page.getByRole('dialog').filter({ has: page.getByRole('checkbox', { name: /^Personal/ }) }).last();
      await bloom.getByRole('checkbox', { name: /^Personal/ }).click();
      await page.waitForTimeout(300);
      await bloom.getByRole('button', { name: /^Done/ }).click();
      await bloom.waitFor({ state: 'hidden' });
      await builder.getByRole('tab', { name: /Review/ }).click();
      await builder.getByLabel('Writer').selectOption(MODEL);
      await page.waitForTimeout(300);
      await builder.getByRole('button', { name: template === 'New idea → drafts' ? 'Save and activate' : 'Save as draft' }).click();
      await builder.waitFor({ state: 'hidden', timeout: 60000 });
      await page.waitForTimeout(600);
      const task = (await snapshot(page)).raffi.campaignPlanning.recurringTasks.at(-1);
      created.push(task.id);
      if (template === 'Evergreen reshare') {
        check('evergreen saved in the definition', task.include?.evergreen?.minAgeDays === 60 && JSON.stringify(task.schedule.weekdays) === '["Wednesday"]', { include: task.include, schedule: task.schedule });
        continue;
      }
      check('trigger saved and active, watching from activation', task.schedule.kind === 'on_new_source' && task.status === 'active' && typeof task.watchFrom === 'number' && !task.nextOccurrence, { schedule: task.schedule, status: task.status, watchFrom: task.watchFrom });
      check('trigger card waits for something new', /Waiting for something new in Ideas/.test(await page.locator('article').filter({ has: page.getByRole('heading', { name: task.name }) }).innerText()));
      // Add an idea the way Home's Context Pocket does, then let the harness cron scan and run.
      await act('source', { kind: 'idea', title: 'Practice with a metronome', text: 'Start slow, then add ten beats a minute each day until the passage feels easy.' });
      const cron = await (await fetch(`${api}/api/cron/worker`, { headers: { Authorization: `Bearer ${CRON}` } })).json();
      const prepared = cron.campaignPreparation?.runs ?? [];
      check('cron scanned Ideas and ran the new idea once', prepared.length === 1 && prepared[0].state === 'completed', cron.campaignPreparation);
      const planning = (await snapshot(page)).raffi.campaignPlanning;
      const runs = planning.occurrences.filter((o) => o.taskId === task.id);
      const source = (await snapshot(page)).sources.findLast((x) => x.title === 'Practice with a metronome');
      check('the run carries the new idea as its event', runs.length === 1 && runs[0].event?.sourceId === source?.id && runs[0].state === 'completed', runs);
      const again = await (await fetch(`${api}/api/cron/worker`, { headers: { Authorization: `Bearer ${CRON}` } })).json();
      check('the same idea never runs twice', again.campaignPreparation?.idle === true, again.campaignPreparation);
      await gotoHub(page);
      const cardEl = page.locator('article').filter({ has: page.getByRole('heading', { name: task.name }) });
      await cardEl.getByRole('button', { name: /Run history/ }).click();
      await page.waitForTimeout(400);
      check('run history names the idea that started it', /From “Practice with a metronome”/.test(await cardEl.innerText()), (await cardEl.innerText()).slice(0, 500));
      await shot(page, dir, '02-trigger-run-history');
    }
  } catch (error) {
    check('triggers scene completed', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    for (const taskId of created) await act('raffi_recurrence_cancel', { taskId, confirmed: true }).catch(() => {});
    await close(s);
  }
}

async function phone(browser) {
  const s = await open(browser, 'phone', { width: 390, height: 844, theme: 'light' });
  const { page, dir } = s;
  try {
    await gotoHub(page);
    check('hub fits a 390px phone', (await overflow(page)) <= 0, await overflow(page));
    await shot(page, dir, '01-hub');
    await page.getByRole('button', { name: 'New automation' }).first().click();
    const builder = page.getByRole('dialog', { name: /automation/i }).first();
    await builder.getByLabel('Name', { exact: true }).waitFor();
    await page.waitForTimeout(700);
    check('builder field text is 16px on phones (no zoom)', (await builder.getByLabel('Name', { exact: true }).evaluate((el) => getComputedStyle(el).fontSize)) === '16px');
    await shot(page, dir, '02-builder-what');
    await builder.getByRole('tab', { name: /When/ }).click();
    await page.waitForTimeout(400);
    const box = await builder.getByRole('button', { name: 'Wednesday', exact: true }).boundingBox();
    check('weekday toggles are at least 44px tall', (box?.height ?? 0) >= 44, box);
    await shot(page, dir, '03-builder-when');
    await builder.getByRole('button', { name: 'Back' }).click();
    await builder.getByRole('button', { name: 'Cancel' }).click();
    await builder.waitFor({ state: 'hidden' });
  } catch (error) {
    check('phone scene completed', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    await close(s);
  }
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const executablePath = (engine === webkit ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    if (!args.only || String(args.only).includes('build')) await build(browser);
    if (!args.only || String(args.only).includes('templates')) await templates(browser);
    if (!args.only || String(args.only).includes('triggers')) await triggers(browser);
    if (!args.only || String(args.only).includes('phone')) await phone(browser);
  } finally {
    await browser.close();
  }
  report.finishedAt = new Date().toISOString();
  const failed = report.scenes.flatMap((sc) => sc.checks.filter((c) => !c.ok).map((c) => `${sc.name}: ${c.name}`));
  report.summary = { checks: report.scenes.reduce((n, sc) => n + sc.checks.length, 0), failed: failed.length, pageErrors: report.scenes.reduce((n, sc) => n + sc.errors.length, 0) };
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  for (const sc of report.scenes) for (const e of sc.errors) process.stdout.write(`ERROR [${sc.name}] ${e.slice(0, 400)}\n`);
  process.stdout.write(`\n${report.summary.checks} checks, ${report.summary.failed} failed, ${report.summary.pageErrors} console/page errors → ${path.relative(process.cwd(), path.join(out, 'report.json'))}\n`);
  if (failed.length || report.summary.pageErrors) process.exitCode = 1;
})();
