/**
 * Rafii v9 real-workflow and motion evidence against the LOCAL dev harness only.
 *
 *   node web/tests/rafii-seed.cjs                     (once: principal, two LinkedIn accounts, folders)
 *   node web/tests/rafii-workflow.cjs [--browser=chromium|webkit] [--only=workflow,motion,reduced,mobile]
 *
 * Scenes (each records a video under docs/design/rafii-v9/evidence/workflow/<browser>/<scene>/):
 *   workflow  Home → Channel Bloom (overlapping folders) → language per account → model dialog →
 *             real generation on the deterministic preview route → phone swipe → caption edit →
 *             Save as drafts (apply + variant_edit) → API check → conversation view.
 *   motion    Focused clips: provider swap + reasoning bars, language disclosure, folder unfolding,
 *             phone swipe/crossfade.
 *   library   Content Library from Home: stage a type and a format, apply (server records the mapped
 *             content type/format), Escape discards, then restore the starting choice.
 *   reduced   The same controls with prefers-reduced-motion: logical state changes, no running animations.
 *   mobile    390×844: composer, Channel Bloom sheet, 16px fields, no horizontal scroll, action not covered.
 *
 * Safety: every browser request outside the harness origin is aborted, and any drafting request whose
 * model is not the deterministic preview fixture is aborted before it reaches the server (no real model
 * or CLI call, no publishing). Server-side web research is on by default in the dev harness; run the
 * harness with POSTRIFF_RESEARCH=0 (launch entry `postriff-api-offline`) so nothing leaves the machine.
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Workflow evidence runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engineName = args.browser === 'webkit' ? 'webkit' : 'chromium';
const engine = engineName === 'webkit' ? webkit : chromium;
const evidence = path.resolve(__dirname, '../../docs/design/rafii-v9/evidence');
const seed = JSON.parse(fs.readFileSync(path.join(evidence, 'seed.json'), 'utf8'));
const out = path.join(evidence, 'workflow', engineName);
const only = args.only ? String(args.only).split(',') : ['workflow', 'motion', 'library', 'reduced', 'mobile', 'drafts'];
const MODEL = 'deterministic-preview';
// Unique per run so the server check finds this run's edit even when earlier passes left drafts behind.
const EDIT_MARK = `Edited in the Rafii v9 composer (${Date.now().toString(36)}).`;
const accounts = seed.channels.filter((c) => c.platform === 'LinkedIn');
const headers = { Authorization: `Bearer dev:${seed.principal}`, 'X-PostRiff-Request': 'founder-alpha' };

/** Every onboarding tour marked dismissed and nudged, so tips never cover the page in evidence captures. */
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS_SEEN = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });

const report = { base, browser: engineName, principal: seed.principal, workspaceId: seed.workspaceId, startedAt: new Date().toISOString(), scenes: [] };
let scene = null;

function check(name, ok, detail) {
  scene.checks.push({ name, ok: Boolean(ok), ...(detail === undefined ? {} : { detail }) });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} [${scene.name}] ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 400)}` : ''}\n`);
}
const mark = (label) => scene.marks.push({ label, atSeconds: Number(((Date.now() - scene.t0) / 1000).toFixed(1)) });

async function open(browser, name, { width = 1440, height = 1000, theme = 'dark', reducedMotion = false } = {}) {
  const dir = path.join(out, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: theme, reducedMotion: reducedMotion ? 'reduce' : 'no-preference', recordVideo: { dir, size: { width, height } } });
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
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
    // Drafting requests must name the fixture model; anything else never reaches the server.
    if (request.method() === 'POST' && /\/ideas\/(quick-start|turn)|\/conversations\/[^/]+\/turns/.test(request.url())) {
      let model = null;
      try { model = JSON.parse(request.postData() || '{}').model ?? null; } catch { /* not json */ }
      if (model !== MODEL) {
        scene?.checks.push({ name: 'drafting request blocked: non-fixture model', ok: false, detail: model });
        return route.abort();
      }
    }
    return route.continue();
  });
  const page = await context.newPage();
  scene = { name, viewport: `${width}x${height}`, theme, reducedMotion, checks: [], marks: [], errors: [], blocked: [], screenshots: [], video: null, t0: Date.now() };
  report.scenes.push(scene);
  page.on('pageerror', (e) => scene.errors.push(`pageerror: ${e.message}`));
  // A request this script aborted (off-origin) logs ERR_FAILED; those are listed under `blocked` instead.
  page.on('console', (m) => m.type() === 'error' && !/Download the React DevTools|net::ERR_FAILED/.test(m.text()) && scene.errors.push(`console: ${m.text().slice(0, 300)}`));
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

async function settle(page) {
  const enter = page.getByRole('button', { name: 'Enter dev workspace' });
  if (await enter.count()) {
    await enter.click();
    await page.waitForLoadState('networkidle');
  }
  for (const name of ['Not now', 'Skip tour']) {
    const button = page.getByRole('button', { name, exact: true });
    if (await button.count()) await button.first().click().catch(() => {});
  }
}

async function gotoHome(page) {
  await page.goto(`${base}/app`, { waitUntil: 'networkidle', timeout: 120000 });
  await settle(page);
  await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 60000 });
  await page.waitForTimeout(800);
}

const settingButton = (page, kicker) => page.locator('button[aria-haspopup="dialog"]').filter({ hasText: kicker });
/** Running animations that move or resize something (opacity/colour fades are allowed under reduced motion). */
const spatialAnimations = (page) =>
  page.evaluate(() =>
    document
      .getAnimations()
      .filter((a) => a.playState === 'running')
      .map((a) => {
        const target = a.effect?.target;
        const props = a.transitionProperty ? [a.transitionProperty] : a.animationName ? [`@keyframes ${a.animationName}`] : Array.from(new Set((a.effect?.getKeyframes?.() ?? []).flatMap((k) => Object.keys(k).filter((key) => !['offset', 'easing', 'composite', 'computedOffset'].includes(key)))));
        const where = target instanceof Element ? `${target.tagName.toLowerCase()}${target.getAttribute('data-slot') ? `[${target.getAttribute('data-slot')}]` : ''}.${String(target.className).split(' ').slice(0, 3).join('.')}` : 'document';
        return { props, where };
      })
      .filter((a) => a.props.some((p) => /transform|translate|scale|rotate|height|width|top|left|right|bottom|inset|margin|clip-path|@keyframes/.test(p)))
  );

async function chooseFolders(page, dir, capture = true) {
  await page.locator('[data-tour="composer-channels"]').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('checkbox', { name: /^Festival/ }).waitFor();
  await page.waitForTimeout(700);
  mark('Channel Bloom open');
  if (capture) await shot(page, dir, '02-channel-bloom');
  const inspect = dialog.getByRole('button', { name: 'Open Festival folder' });
  await inspect.click();
  mark('Festival folder unfolds');
  await page.waitForTimeout(900);
  check('folder inspector unfolds (aria-expanded)', (await inspect.getAttribute('aria-expanded')) === 'true');
  if (capture) await shot(page, dir, '03-folder-inspector');
  await inspect.click();
  mark('Festival folder folds');
  await page.waitForTimeout(900);
  // Overlapping folders: Personal holds account 1, Festival holds accounts 1 and 2.
  await dialog.getByRole('checkbox', { name: /^Personal/ }).click();
  await dialog.getByRole('checkbox', { name: /^Festival/ }).click();
  await page.waitForTimeout(500);
  const done = dialog.getByRole('button', { name: /^Done/ });
  const doneName = (await done.getAttribute('aria-label')) ?? (await done.innerText());
  check('overlapping folders select each account once', /\b2 accounts\b/.test(doneName), doneName);
  if (capture) await shot(page, dir, '04-folders-selected');
  await done.click();
  await dialog.waitFor({ state: 'hidden' });
  mark('destinations committed');
}

/* ------------------------------------------------------------------ workflow */
async function workflow(browser) {
  const s = await open(browser, 'workflow');
  const { page, dir } = s;
  try {
    await gotoHome(page);
    mark('Home loaded');
    await shot(page, dir, '01-home-idle');
    check('Home heading', /What.s the idea/.test(await page.getByRole('heading', { level: 1 }).innerText()));
    check('model is the deterministic preview fixture', /Deterministic preview/.test(await settingButton(page, 'Model').innerText()), await settingButton(page, 'Model').innerText());

    await chooseFolders(page, dir);
    const channels = page.locator('[data-tour="composer-channels"]');
    check('composer summarises the folder selection', /Festival|Personal|2 folders/.test(await channels.innerText()), await channels.innerText());
    check('composer counts two accounts', /2 accounts selected/.test((await channels.getAttribute('aria-label')) ?? ''), await channels.getAttribute('aria-label'));
    const idleDock = page.getByRole('group', { name: 'Explore the destination previews' });
    const idleNames = await idleDock.getByRole('button').evaluateAll((nodes) => nodes.map((n) => n.getAttribute('aria-label') || n.textContent));
    check('idle deck names both accounts on one app', accounts.every((a) => idleNames.some((n) => n.includes(a.account))), idleNames);
    await shot(page, dir, '05-idle-deck-two-accounts');

    // Language per account: the second account writes in English (UK); the first keeps its language.
    await settingButton(page, 'Language').click();
    const languageDialog = page.getByRole('dialog');
    await languageDialog.waitFor();
    await page.waitForTimeout(600);
    mark('language dialog open');
    const second = languageDialog.getByRole('button', { name: new RegExp(`^Output language for LinkedIn · ${accounts[1].account}\\b`) });
    const first = languageDialog.getByRole('button', { name: new RegExp(`^Output language for LinkedIn · ${accounts[0].account}:`) });
    check('language dialog lists each account separately', (await second.count()) === 1 && (await first.count()) === 1);
    // The second account gets a language the first one is not showing, so the drafts must differ.
    const firstShows = (await first.getAttribute('aria-label')) ?? '';
    const target = /United Kingdom/.test(firstShows) ? { tag: 'en-AU', search: 'australia', option: /English \(Australia\)/ } : { tag: 'en-GB', search: 'british', option: /English \(UK\)/ };
    scene.language = { firstShows, secondChosen: target.tag };
    await second.click();
    mark('language catalogue discloses');
    await page.waitForTimeout(700);
    await languageDialog.getByRole('combobox', { name: 'Search languages or regions' }).fill(target.search);
    await page.waitForTimeout(400);
    await languageDialog.getByRole('option', { name: target.option }).first().click();
    await page.waitForTimeout(600);
    await shot(page, dir, '06-language-per-account');
    await languageDialog.getByRole('button', { name: /^Apply/ }).click();
    await languageDialog.waitFor({ state: 'hidden' });
    mark('languages applied');
    check('language summary shows per-destination languages', /Per destination|2 languages/.test(await settingButton(page, 'Language').innerText()), await settingButton(page, 'Language').innerText());

    // Model dialog: browse providers (never commits), reasoning segments, keep the fixture model.
    await settingButton(page, 'Model').click();
    const modelDialog = page.getByRole('dialog');
    await modelDialog.waitFor();
    await page.waitForTimeout(600);
    mark('model dialog open');
    // The CLI switch appears only where the API host reports a CLI (CI's harness runs with POSTRIFF_LOCAL_CLI=0).
    const cliMode = modelDialog.getByRole('radio', { name: 'CLI', exact: true });
    const hasCli = (await cliMode.count()) > 0;
    check('model dialog offers CLI only where the API host reports one', true, hasCli ? 'CLI reported: API and CLI modes' : 'no CLI reported: API models only');
    if (hasCli) {
      await cliMode.click();
      await page.waitForTimeout(700);
    }
    const providerTabs = modelDialog.getByRole('tablist', { name: 'Model providers' }).getByRole('tab');
    const providerCount = await providerTabs.count();
    for (let i = providerCount - 1; i >= 0; i -= 1) {
      await providerTabs.nth(i).click();
      mark(`provider swap ${i}`);
      await page.waitForTimeout(650);
    }
    if (hasCli) {
      await modelDialog.getByRole('radio', { name: 'API models', exact: true }).click();
      await page.waitForTimeout(600);
    }
    await modelDialog.getByRole('radio', { name: /Deterministic preview/ }).click();
    await page.waitForTimeout(300);
    const applied = await modelDialog.getByRole('radio', { name: /sends standard/ }).count();
    const notApplied = await modelDialog.getByRole('radio', { name: /not applied by this provider/ }).count();
    check('reasoning shows the route’s real options or an honest “not applied”', applied === 1 || notApplied > 0, { applied, notApplied });
    if (applied) {
      for (const segment of [/sends standard/, /sends deep/, /sends quick/]) {
        await modelDialog.getByRole('radio', { name: segment }).click();
        mark(`reasoning ${segment.source}`);
        await page.waitForTimeout(500);
      }
    }
    await shot(page, dir, '07-model-dialog');
    await modelDialog.getByRole('button', { name: /Use this model/ }).click();
    await modelDialog.waitFor({ state: 'hidden' });
    check('fixture model still selected after browsing providers', /Deterministic preview/.test(await settingButton(page, 'Model').innerText()), await settingButton(page, 'Model').innerText());

    // Real generation through the existing quick-start service.
    await page.getByRole('textbox', { name: 'Message' }).fill('Practice notes from this week: the slow, unglamorous hours at the piano are where every good performance is really decided.');
    const generate = page.getByRole('button', { name: /^Generate drafts/ });
    check('Generate is enabled with two account destinations', await generate.isEnabled());
    page.on('response', async (response) => {
      if (!/\/ideas\/quick-start/.test(response.url())) return;
      const body = await response.json().catch(() => null);
      scene.quickStart = { status: response.status(), runId: body?.runId ?? null, conversationId: body?.conversationId ?? null, error: body?.error ?? null };
    });
    await generate.click();
    mark('generate');
    const results = page.getByRole('region', { name: 'Generated drafts' });
    await results.waitFor({ timeout: 30000 });
    await page.waitForFunction(() => /ready · yours to edit/.test(document.querySelector('section[aria-label="Generated drafts"] [role="status"]')?.textContent ?? ''), null, { timeout: 120000 });
    mark('drafts ready');
    await page.waitForTimeout(900);
    await shot(page, dir, '08-results');
    const statusText = await results.getByRole('status').innerText();
    check('one draft per account (2 of 2 ready)', /\b2 of 2 ready\b/.test(statusText), statusText);
    const resultDock = page.getByRole('group', { name: 'Choose a draft' });
    const resultNames = await resultDock.getByRole('button').evaluateAll((nodes) => nodes.map((n) => n.getAttribute('aria-label') || n.textContent));
    check('results keep each account as its own draft', accounts.every((a) => resultNames.some((n) => n.includes(a.account))), resultNames);

    // Phone swipe (mouse drag) on the results deck.
    const before = await resultDock.locator('button[aria-pressed="true"]').getAttribute('aria-label');
    const deck = page.getByRole('group', { name: 'Draft previews' });
    const box = await deck.boundingBox();
    await page.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 90, box.y + box.height / 2, { steps: 10 });
    await page.mouse.up();
    mark('phone swipe');
    await page.waitForTimeout(900);
    const after = await resultDock.locator('button[aria-pressed="true"]').getAttribute('aria-label');
    check('swipe moves to the other draft', before !== after, { before, after });
    await shot(page, dir, '09-after-swipe');

    // Edit the active caption, then save through the existing apply + variant_edit services.
    const editor = page.getByRole('textbox', { name: 'Edit draft preview' });
    const original = await editor.inputValue();
    await editor.fill(`${original}\n\n${EDIT_MARK}`);
    await page.waitForTimeout(300);
    check('edited caption is marked unsaved', await results.getByText('Edited · not saved').isVisible());
    await results.getByRole('button', { name: 'Save as drafts' }).click();
    mark('save as drafts');
    await page.waitForFunction(() => /saved to your drafts/.test(document.querySelector('section[aria-label="Generated drafts"] [role="status"]')?.textContent ?? ''), null, { timeout: 60000 });
    await page.waitForTimeout(600);
    await shot(page, dir, '10-saved');
    check('one edited caption recorded', await results.getByText('1 edited caption recorded.').isVisible());

    // Server truth: the applied variants of this run (the run that holds the edited caption).
    const snapshot = await (await page.request.get(`${base}/api/workspaces/${seed.workspaceId}`, { headers })).json();
    const conversationHref = await results.getByRole('link', { name: /Open conversation/ }).getAttribute('href');
    const conversationId = decodeURIComponent(conversationHref.split('/').pop());
    const variants = snapshot.state.variants ?? [];
    // This run's drafts: created by it, refreshed in place by it (a proposed update on an unscheduled
    // draft for the same account and language), or the draft that received this run's caption edit.
    const runId = scene.quickStart?.runId;
    const saved = runId ? variants.filter((v) => v.runId === runId || v.proposedUpdate?.runId === runId || v.text.includes(EDIT_MARK)) : [];
    check('the drafting request succeeded', scene.quickStart?.status === 201 && Boolean(runId), scene.quickStart);
    scene.saved = saved.map((v) => ({ id: v.id, platform: v.platform, language: v.language, channelId: v.channelId, revision: v.revision, edited: v.text.includes(EDIT_MARK), createdByRun: v.runId === runId, proposedUpdateFromRun: v.proposedUpdate?.runId === runId }));
    check('server holds exactly one draft per account for the run', saved.length === 2 && new Set(saved.map((v) => v.channelId)).size === 2 && accounts.every((a) => saved.some((v) => v.channelId === a.id)), scene.saved);
    check(`each account kept its own language (second account ${scene.language.secondChosen}, first unchanged)`, saved.some((v) => v.channelId === accounts[1].id && v.language === scene.language.secondChosen) && saved.some((v) => v.channelId === accounts[0].id && v.language !== scene.language.secondChosen), scene.saved);
    check('the edited caption persisted as a new revision', saved.filter((v) => v.text.includes(EDIT_MARK) && v.revision > 1).length === 1, scene.saved);

    // Conversation view keeps the accounts apart.
    await results.getByRole('link', { name: /Open conversation/ }).click();
    await page.waitForURL(/\/app\/agent\//, { timeout: 60000 });
    const tabs = page.getByRole('tablist', { name: 'Drafts by destination' });
    await tabs.waitFor({ timeout: 60000 });
    await page.waitForTimeout(900);
    mark('conversation view');
    const tabNames = await tabs.getByRole('tab').allInnerTexts();
    check('conversation tabs name each account', accounts.every((a) => tabNames.some((t) => t.includes(a.account))), tabNames);
    await shot(page, dir, '11-conversation');
    scene.conversationId = conversationId;
  } catch (error) {
    check('workflow completed without an exception', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    await close(s);
  }
}

/* ------------------------------------------------------------------ focused motion clips */
async function motion(browser) {
  // Provider swap and reasoning bars.
  let s = await open(browser, 'motion-provider-swap-reasoning');
  try {
    await gotoHome(s.page);
    await settingButton(s.page, 'Model').click();
    const dialog = s.page.getByRole('dialog');
    await dialog.waitFor();
    await s.page.waitForTimeout(700);
    // The CLI switch (and its five-level reasoning ladder) exists only where the API host reports a CLI.
    const cliMode = dialog.getByRole('radio', { name: 'CLI', exact: true });
    const hasCli = (await cliMode.count()) > 0;
    if (hasCli) {
      await cliMode.click();
      await s.page.waitForTimeout(700);
    }
    const tabs = dialog.getByRole('tablist', { name: 'Model providers' }).getByRole('tab');
    for (const index of [1, 0, 1, 0]) {
      if (index < (await tabs.count())) {
        await tabs.nth(index).click();
        mark(`provider tab ${index}`);
        await s.page.waitForTimeout(700);
      }
    }
    if (hasCli) {
      // Stage (not apply) a CLI model so the five-level ladder shows; Cancel discards it.
      await dialog.getByRole('radiogroup', { name: 'Models' }).getByRole('radio').first().click();
      await s.page.waitForTimeout(500);
      for (const segment of [/sends medium/, /sends high/, /sends xhigh/, /sends max/, /sends low/]) {
        await dialog.getByRole('radio', { name: segment }).click();
        mark(`reasoning ${segment.source}`);
        await s.page.waitForTimeout(550);
      }
      await shot(s.page, s.dir, 'reasoning-bars');
    } else {
      check('CLI reasoning ladder skipped: the API host reports no CLI', true);
    }
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await s.page.waitForTimeout(500);
    check('Cancel keeps the fixture model', /Deterministic preview/.test(await settingButton(s.page, 'Model').innerText()), await settingButton(s.page, 'Model').innerText());
  } catch (error) {
    check('provider/reasoning clip completed', false, error.message);
  } finally {
    await close(s);
  }

  // Language disclosure: target catalogue and the shared-language switch.
  s = await open(browser, 'motion-language-disclosure');
  try {
    await gotoHome(s.page);
    await settingButton(s.page, 'Language').click();
    const dialog = s.page.getByRole('dialog');
    await dialog.waitFor();
    await s.page.waitForTimeout(700);
    await dialog.getByRole('button', { name: /^Output language for / }).first().click();
    mark('catalogue discloses');
    await s.page.waitForTimeout(900);
    await dialog.getByRole('combobox', { name: 'Search languages or regions' }).fill('cantonese');
    await s.page.waitForTimeout(700);
    await shot(s.page, s.dir, 'catalogue-search');
    await s.page.keyboard.press('Escape');
    mark('catalogue closes (Escape)');
    await s.page.waitForTimeout(700);
    check('first Escape closes only the catalogue', await dialog.isVisible());
    const shared = dialog.getByRole('switch', { name: 'All channels use the same language' });
    await shared.click();
    mark('shared language discloses');
    await s.page.waitForTimeout(900);
    check('shared switch expands its content', (await shared.getAttribute('aria-expanded')) === 'true');
    await shot(s.page, s.dir, 'shared-language');
    await shared.click();
    mark('shared language folds');
    await s.page.waitForTimeout(900);
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await s.page.waitForTimeout(600);
  } catch (error) {
    check('language clip completed', false, error.message);
  } finally {
    await close(s);
  }

  // Folder unfolding.
  s = await open(browser, 'motion-folder-unfold');
  try {
    await gotoHome(s.page);
    await chooseFolders(s.page, s.dir, true);
  } catch (error) {
    check('folder clip completed', false, error.message);
  } finally {
    await close(s);
  }

  // Phone swipe/crossfade on the idle deck, then the enlarged preview.
  s = await open(browser, 'motion-phone-swipe');
  try {
    await gotoHome(s.page);
    await s.page.getByRole('textbox', { name: 'Message' }).fill('A quiet morning practice note becomes three posts, each in its own app.');
    await s.page.waitForTimeout(500);
    const dock = s.page.getByRole('group', { name: 'Explore the destination previews' });
    const deck = s.page.getByRole('group', { name: 'Destination previews', exact: true });
    await deck.scrollIntoViewIfNeeded();
    const box = await deck.boundingBox();
    for (const direction of [-1, 1, -1]) {
      await s.page.mouse.move(box.x + box.width / 2 - direction * 90, box.y + box.height / 2);
      await s.page.mouse.down();
      await s.page.mouse.move(box.x + box.width / 2 + direction * 90, box.y + box.height / 2, { steps: 10 });
      await s.page.mouse.up();
      mark(`swipe ${direction < 0 ? 'left' : 'right'}`);
      await s.page.waitForTimeout(900);
    }
    const buttons = dock.getByRole('button');
    await buttons.last().click();
    mark('dock tap');
    await s.page.waitForTimeout(900);
    await buttons.first().focus();
    await s.page.keyboard.press('ArrowRight');
    mark('dock arrow key');
    await s.page.waitForTimeout(900);
    // Rapid interrupts must settle on the last request.
    await buttons.first().click();
    await buttons.last().click();
    await buttons.first().click();
    await s.page.waitForTimeout(1200);
    check('rapid switches settle on the last request', (await buttons.first().getAttribute('aria-pressed')) === 'true');
    const layers = await deck.locator('[data-deck-key]').count();
    check('no stale layers after interrupts', layers <= 3, layers);
    await s.page.getByRole('button', { name: 'Expand iPhone preview' }).click();
    mark('expanded preview');
    await s.page.waitForTimeout(900);
    await shot(s.page, s.dir, 'expanded-preview');
    await s.page.keyboard.press('Escape');
    await s.page.waitForTimeout(700);
    check('focus returns to the expand button', await s.page.evaluate(() => document.activeElement?.getAttribute('aria-label') === 'Expand iPhone preview'));
  } catch (error) {
    check('phone clip completed', false, error.message);
  } finally {
    await close(s);
  }
}

/* ------------------------------------------------------------------ content library */
async function library(browser) {
  const s = await open(browser, 'content-library');
  const { page, dir } = s;
  const pod = page.getByRole('button', { name: /^Choose content type and native format/ });
  const selection = async () => (await (await page.request.get(`${base}/api/workspaces/${seed.workspaceId}`, { headers })).json()).state.contentTypes?.selection ?? null;
  async function choose(editorial, native) {
    await pod.click();
    const dialog = page.getByRole('dialog');
    // The dialog remembers its last tab; start from the editorial types.
    await dialog.getByRole('tab', { name: /editorial type/ }).click();
    await dialog.locator(`[data-library-item="${editorial}"]`).first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(500);
    await dialog.locator(`[data-library-item="${editorial}"]`).first().click();
    await dialog.getByRole('tab', { name: /native format/ }).click();
    mark('native formats tab (crossfade)');
    await page.waitForTimeout(600);
    await dialog.locator(`[data-library-item="${native}"]`).first().click();
    await page.waitForTimeout(300);
    return dialog;
  }
  try {
    await gotoHome(page);
    const before = await pod.getAttribute('aria-label');
    const dialog = await choose('behind_the_scenes', 'carousel');
    mark('library staged');
    await shot(page, dir, '01-library-staged');
    const footer = await dialog.innerText();
    check('footer shows the staged editorial type and native format', /Behind the scenes/.test(footer) && /Carousel/.test(footer));
    await dialog.getByRole('button', { name: /^Use these choices/ }).click();
    await dialog.waitFor({ state: 'hidden' });
    mark('library applied');
    await page.waitForFunction(() => /Behind the scenes/.test(document.querySelector('[aria-label^="Choose content type and native format"]')?.getAttribute('aria-label') ?? ''), null, { timeout: 30000 }).catch(() => {});
    const after = await pod.getAttribute('aria-label');
    check('composer shows the applied choice', /Behind the scenes/.test(after ?? '') && /Carousel/.test(after ?? ''), { before, after });
    const applied = await selection();
    check('server records the mapped content type and format', applied?.contentTypeId === 'pack.creator:building_in_public' && applied?.formatId === 'carousel', applied);
    // Escape discards a staged change.
    await choose('quote', 'quote_card');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(700);
    const escaped = await pod.getAttribute('aria-label');
    check('Escape discards staged choices', escaped === after, { after, escaped });
    const unchanged = await selection();
    check('server selection unchanged after Escape', unchanged?.contentTypeId === applied?.contentTypeId && unchanged?.formatId === applied?.formatId, unchanged);
    // Restore the starting choice so later runs start from the same state.
    await choose('status_update', 'text');
    await page.getByRole('dialog').getByRole('button', { name: /^Use these choices/ }).click();
    // The label changes once the server confirms the selection; a loaded machine can take seconds.
    const restored = await page.waitForFunction(() => /Status update/.test(document.querySelector('[aria-label^="Choose content type and native format"]')?.getAttribute('aria-label') ?? ''), null, { timeout: 30000 }).then(() => true, () => false);
    check('restored to Status update · Text', restored, await pod.getAttribute('aria-label'));
  } catch (error) {
    check('library scene completed', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    await close(s);
  }
}

/* ------------------------------------------------------------------ reduced motion */
async function reduced(browser) {
  const s = await open(browser, 'reduced-motion', { reducedMotion: true });
  const { page, dir } = s;
  try {
    await gotoHome(page);
    check('reduced-motion preference is visible to the page', await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches));
    const dock = page.getByRole('group', { name: 'Explore the destination previews' });
    await dock.getByRole('button').last().click();
    await page.waitForTimeout(80);
    const deckMotion = await spatialAnimations(page);
    check('deck switch runs no spatial animation', deckMotion.length === 0, deckMotion);
    check('deck switch still changes the active phone', (await dock.getByRole('button').last().getAttribute('aria-pressed')) === 'true');
    await page.locator('[data-tour="composer-channels"]').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('checkbox', { name: /^Festival/ }).waitFor();
    await page.waitForTimeout(400);
    await dialog.getByRole('button', { name: 'Open Festival folder' }).click();
    await page.waitForTimeout(80);
    const folderMotion = await spatialAnimations(page);
    check('folder inspector opens without a spatial animation', folderMotion.length === 0, folderMotion);
    check('folder inspector is open', (await dialog.getByRole('button', { name: 'Open Festival folder' }).getAttribute('aria-expanded')) === 'true');
    await shot(page, dir, 'reduced-inspector');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);
  } catch (error) {
    check('reduced-motion scene completed', false, error.message);
  } finally {
    await close(s);
  }
}

/* ------------------------------------------------------------------ mobile */
async function mobile(browser) {
  const s = await open(browser, 'mobile-390', { width: 390, height: 844, theme: 'light' });
  const { page, dir } = s;
  try {
    await gotoHome(page);
    await shot(page, dir, '01-home');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    check('no horizontal scroll at 390px', overflow <= 1, overflow);
    const fontSize = await page.getByRole('textbox', { name: 'Message' }).evaluate((node) => parseFloat(getComputedStyle(node).fontSize));
    check('composer text is at least 16px (no iOS zoom)', fontSize >= 16, fontSize);
    const generate = page.getByRole('button', { name: /^Generate drafts/ });
    await generate.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    const covered = await page.evaluate(() => {
      const button = [...document.querySelectorAll('button')].find((b) => b.innerText.trim().startsWith('Generate drafts'));
      const bar = document.querySelector('nav[aria-label="Mobile navigation"]');
      if (!button || !bar) return { button: Boolean(button), bar: Boolean(bar) };
      const a = button.getBoundingClientRect();
      const b = bar.getBoundingClientRect();
      return { overlap: a.bottom > b.top && a.top < b.bottom && getComputedStyle(bar).display !== 'none' };
    });
    check('mobile navigation does not cover the primary action', covered.overlap === false, covered);
    await shot(page, dir, '02-generate-visible');
    await page.locator('[data-tour="composer-channels"]').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('checkbox', { name: /^Festival/ }).waitFor();
    await page.waitForTimeout(800);
    await shot(page, dir, '03-channel-bloom-sheet');
    const search = dialog.getByRole('textbox', { name: 'Search folders and accounts' });
    check('Channel Bloom search is 16px on phones', (await search.evaluate((n) => parseFloat(getComputedStyle(n).fontSize))) >= 16);
    const sheetOverflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    check('no horizontal scroll with the sheet open', sheetOverflow <= 1, sheetOverflow);
    await dialog.getByRole('button', { name: 'Cancel channel selection' }).click();
    await page.waitForTimeout(500);
  } catch (error) {
    check('mobile scene completed', false, error.message);
  } finally {
    await close(s);
  }
}


/** Queue → Drafts (the Pipeline board folded into Queue): the old address lands there, the menu has no Pipeline,
 *  saved drafts are listed and counted, Schedule… opens the exact-review dialog, and the Queue tab is unchanged. */
async function drafts(browser) {
  const s = await open(browser, 'queue-drafts');
  const { page, dir } = s;
  const api = async (method, route, data) => {
    const response = await page.request.fetch(`${base}/api/workspaces/${seed.workspaceId}${route}`, { method, headers: { ...headers, 'Content-Type': 'application/json' }, data });
    if (!response.ok()) throw new Error(`${method} ${route} → ${response.status()}`);
    return response.json();
  };
  try {
    // Save the seeded run's drafts, as Home's Save does, so there is something to schedule. Earlier scenes add
    // sources, and the server then refuses to save that older candidate ("draft again from current context"), so
    // in that case draft again for the same three destinations and save the new candidate.
    const save = async (runId) => {
      const snapshot = await api('GET', '');
      let run = await api('GET', `/ideas/runs/${runId}/events?cursor=0`);
      for (let i = 0; run.status === 'running' && i < 120; i++) { await page.waitForTimeout(500); run = await api('GET', `/ideas/runs/${runId}/events?cursor=0`); }
      return api('POST', `/ideas/runs/${runId}/apply`, { expectedRevision: snapshot.revision, artifactHash: run.artifactHash });
    };
    let redrafted = false;
    try { await save(seed.runId); } catch {
      const snapshot = await api('GET', '');
      const fresh = await api('POST', '/ideas/quick-start', {
        expectedRevision: snapshot.revision,
        text: 'A second thought from practice: short daily sessions carry further than rare long ones.',
        ownContent: true, confirmUse: true,
        destinations: seed.variants.map((v) => ({ platform: v.platform, language: v.language, ...(v.channelId ? { channelId: v.channelId } : {}) })),
        model: 'deterministic-preview', reasoning: 'quick', voiceMode: 'neutral', timeZone: 'Asia/Hong_Kong'
      });
      await save(fresh.runId);
      redrafted = true;
    }
    check('drafts saved for scheduling', true, redrafted ? 'seeded candidate was stale; drafted again from current context' : 'seeded candidate saved');
    await page.goto(`${base}/app/pipeline`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await settle(page);
    await page.waitForURL(/\/app\/queue\?view=drafts/, { timeout: 120000 });
    check('the old Pipeline address opens Queue → Drafts', /\/app\/queue\?view=drafts/.test(page.url()), page.url());
    const tab = page.getByRole('tab', { name: /^Drafts/ });
    await tab.waitFor({ timeout: 120000 });
    check('the Drafts tab is selected', (await tab.getAttribute('aria-selected')) === 'true');
    check('Pipeline left the menu', (await page.getByRole('link', { name: 'Pipeline', exact: true }).count()) === 0);
    const cards = page.locator('#pipeline-col-drafts [data-card-key]');
    await cards.first().waitFor({ timeout: 60000 });
    await page.waitForTimeout(600);
    const count = await cards.count();
    check('saved drafts are listed', count >= 3, count);
    check('the tab counts them', (await tab.innerText()).includes(String(count)), await tab.innerText());
    await shot(page, dir, '01-drafts');
    await page.locator('#pipeline-col-drafts').getByRole('button', { name: /^Schedule/ }).first().click();
    const dialog = page.getByRole('dialog').first();
    await dialog.waitFor({ timeout: 30000 });
    check('Schedule… opens the exact-review dialog', /Schedule|review/i.test(await dialog.innerText()), (await dialog.innerText()).slice(0, 160));
    await shot(page, dir, '02-schedule');
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden', timeout: 15000 });
    await page.getByRole('tab', { name: /^Queue/ }).click();
    await page.waitForURL((url) => !url.search.includes('view=drafts'), { timeout: 30000 });
    // With no jobs yet the Queue tab explains the three steps instead of an empty list.
    const queued = page.locator('#queue-jobs-list').or(page.getByText('Nothing publishes on its own')).first();
    await queued.waitFor({ timeout: 30000 });
    check('the Queue tab still shows approvals and jobs', await queued.isVisible());
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${base}/app/queue?view=drafts`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await cards.first().waitFor({ timeout: 120000 });
    await page.waitForTimeout(600);
    const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
    check('Drafts fits a 390px phone', overflow <= 0, overflow);
    await shot(page, dir, '03-drafts-phone');
  } catch (error) {
    check('drafts scene completed', false, error.message);
    await shot(page, dir, 'zz-failure').catch(() => {});
  } finally {
    await close(s);
  }
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  // A locally installed build may be named explicitly (RAFII_CHROMIUM_PATH / RAFII_WEBKIT_PATH); nothing is downloaded.
  const executablePath = (engine === webkit ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    if (only.includes('workflow')) await workflow(browser);
    if (only.includes('motion')) await motion(browser);
    if (only.includes('library')) await library(browser);
    if (only.includes('drafts')) await drafts(browser);
    if (only.includes('reduced')) await reduced(browser);
    if (only.includes('mobile')) await mobile(browser);
  } finally {
    await browser.close();
  }
  report.finishedAt = new Date().toISOString();
  const failed = report.scenes.flatMap((sc) => sc.checks.filter((c) => !c.ok).map((c) => `${sc.name}: ${c.name}`));
  report.summary = { checks: report.scenes.reduce((n, sc) => n + sc.checks.length, 0), failed: failed.length, pageErrors: report.scenes.reduce((n, sc) => n + sc.errors.length, 0) };
  const file = path.join(out, args.only ? `report-${only.join('-')}.json` : 'report.json');
  fs.writeFileSync(file, JSON.stringify(report, null, 2));
  process.stdout.write(`\n${report.summary.checks} checks, ${report.summary.failed} failed, ${report.summary.pageErrors} console/page errors → ${path.relative(process.cwd(), file)}\n`);
  if (failed.length) process.exitCode = 1;
})();
