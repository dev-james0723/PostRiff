/**
 * Rafii's side panel in a real browser against the local dev harness (site agent spec §11, §16): it opens from the
 * header and ⌘J/Ctrl+J on every page; the conversation survives navigation and a reload; answers read the page's
 * selected item; a scheduling proposal is applied through the real review command and waits for approval; Escape
 * returns focus to the launcher; the help pages hand a question to the panel; desktop docks, tablet slides in, phone
 * opens a drawer; no page scrolls sideways; axe finds no serious or critical issue in the open panel; the avatar's
 * thinking ring stops under reduced motion.
 *
 *   node web/tests/site-agent-browser.cjs [--browser=chromium|webkit] [--out=dir] [--shots=off] [--sections=desktop,help,tablet,phone]
 *
 * Seeds its own principal through the harness API (canned LinkedIn consent, deterministic preview writer). Nothing
 * here reaches a real provider; no post is approved or published. Start the harness with POSTRIFF_RESEARCH=0 (as the
 * PostgreSQL runner does): otherwise a drafting turn may look its topic up on the live web, and the seed refuses to run.
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3190';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
// --sections runs part of the journey (each section starts from a fresh page): a browser that dies mid-run can be resumed.
const want = (name) => !args.sections || String(args.sections).split(',').includes(name);
const out = path.resolve(args.out || '.');
fs.mkdirSync(out, { recursive: true });
const principal = randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const results = [];
// --shots=off skips screenshots (a mismatched local WebKit build aborts inside its screenshot call).
const shot = (page, name) => (args.shots === 'off' ? null : page.screenshot({ path: path.join(out, name) }));
const check = (name, ok, detail) => {
  results.push({ name, ok: Boolean(ok), detail: ok ? undefined : detail });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 400)}` : ''}\n`);
};

async function call(method, url, body) {
  const res = await fetch(base + url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

async function seed() {
  const { workspaceId } = await call('POST', '/api/auth/verify', {});
  const start = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/start`, { capability: 'publish' });
  const state = new URL(start.authorizeUrl).searchParams.get('state');
  const done = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/complete`, { state, code: 'good-code' });
  if (!done.connected) throw new Error('LinkedIn did not connect in the harness');
  let snapshot = await call('GET', `/api/workspaces/${workspaceId}`);
  const linkedin = snapshot.state.phase2.channels.find((c) => c.platform === 'LinkedIn');
  const run = await call('POST', `/api/workspaces/${workspaceId}/ideas/quick-start`, {
    expectedRevision: snapshot.revision, text: 'Slow practice builds fast fingers: three minutes, one bar, eyes closed.', ownContent: true, confirmUse: true,
    destinations: [{ platform: 'LinkedIn', language: 'en', channelId: linkedin.id }], model: 'deterministic-preview', reasoning: 'quick', voiceMode: 'neutral', timeZone: 'Asia/Hong_Kong'
  });
  snapshot = await call('GET', `/api/workspaces/${workspaceId}`);
  await call('POST', `/api/workspaces/${workspaceId}/ideas/runs/${run.runId}/apply`, { expectedRevision: snapshot.revision, artifactHash: run.artifactHash });
  snapshot = await call('GET', `/api/workspaces/${workspaceId}`);
  const draft = snapshot.state.variants.find((v) => v.provenance?.runId === run.runId);
  // A confirmed draft (the same action the draft card sends), so scheduling reaches the account check.
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, {
    expectedRevision: snapshot.revision, action: 'p2_variant_review', payload: { variantId: draft.id, variantRevision: draft.revision, confirmed: true, excludedUnknowns: draft.unknowns }
  });
  // An active weekly automation, saved and activated through the builder's own actions.
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, {
    expectedRevision: snapshot.revision, action: 'raffi_recurrence_save',
    payload: { name: 'Friday practice note', goal: 'A short note about practising slowly', audience: 'Adult piano learners', facts: {}, schedule: { weekdays: ['Friday'], localTime: '16:00', timeZone: 'Asia/Hong_Kong' },
               destinations: [{ platform: 'LinkedIn', language: 'en', channelId: linkedin.id }], contentType: null, route: 'deterministic-preview', reasoning: 'quick', maxCostUsdMicro: 0, sourceIds: [], include: null, voiceMode: 'neutral' }
  });
  if (snapshot.state.sources.some((s) => s.origin && s.origin.kind === 'web_research')) throw new Error('The harness looked the seed up on the live web; start it with POSTRIFF_RESEARCH=0.');
  const task = snapshot.state.raffi.campaignPlanning.recurringTasks.find((t) => t.name === 'Friday practice note');
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, { expectedRevision: snapshot.revision, action: 'raffi_recurrence_activate', payload: { taskId: task.id, confirmed: true } });
  return { workspaceId, draftId: draft.id, taskId: task.id };
}

async function context(browser, viewport, extra = {}) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark', hasTouch: viewport.width < 768, isMobile: viewport.width < 768, ...extra });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await ctx.addInitScript(({ id, tours }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '.tsqd-parent-container{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: principal, tours: TOURS });
  return ctx;
}

const launcher = (page) => page.locator('#rafii-launcher');
const panel = (page) => page.locator('#rafii-panel');
const composer = (page) => panel(page).getByLabel('Ask Rafii', { exact: true });
const answers = (page) => panel(page).getByRole('article', { name: "Rafii's answer" });

async function ready(page) {
  await launcher(page).waitFor({ state: 'visible', timeout: 400000 });
  await page.waitForFunction(() => document.querySelector('#rafii-launcher') && !document.querySelector('#rafii-launcher').disabled, null, { timeout: 400000 });
  await page.waitForTimeout(300);
}

// The answer to exactly this question: the first answer after the last bubble holding it (history may still be loading).
const answerTo = (page, text) =>
  page.locator(`xpath=(//*[@id="rafii-panel"]//li[contains(@class,"justify-end")]/p[normalize-space(.)=${JSON.stringify(text)}])[last()]/ancestor::li[1]/following-sibling::li//article[@aria-label="Rafii's answer"]`).first();

async function ask(page, text) {
  await composer(page).fill(text);
  await composer(page).press('Enter');
  const answer = answerTo(page, text);
  await answer.waitFor({ timeout: 180000 });
  await page.waitForFunction(() => !document.querySelector('#rafii-panel [aria-label="Stop this answer"]'), null, { timeout: 180000 });
  return answer;
}

async function noSideScroll(page) {
  return page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1);
}

async function axe(page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async () => {
    const result = await window.axe.run('#rafii-panel', { resultTypes: ['violations'] });
    return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes[0]?.target }));
  });
}

(async () => {
  const seeded = await seed();
  check('seed: workspace, LinkedIn account and a confirmed draft', Boolean(seeded.workspaceId && seeded.draftId), seeded);
  const executablePath = (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  let answer;
  try {
    if (want('desktop')) {
    // --- desktop: sheet above a dialog, docked column, keyboard, page awareness, proposal, navigation, reload, axe -----
    const desk = await context(browser, { width: 1440, height: 900 });
    const page = await desk.newPage();
    const hotkey = process.platform === 'darwin' ? 'Meta+j' : 'Control+j';
    await page.goto(`${base}/app/queue?view=drafts&draft=${seeded.draftId}`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    // The draft opened from the link is a dialog: the page behind it is inert, so Rafii comes up as a sheet above it.
    await page.locator('.t-modal-backdrop[data-open]').first().waitFor({ timeout: 120000 });
    await page.keyboard.press(hotkey);
    await panel(page).waitFor({ state: 'visible', timeout: 30000 });
    check('desktop: ⌘J / Ctrl+J opens the panel', await panel(page).isVisible());
    check('desktop: the launcher reports the panel open', (await launcher(page).getAttribute('aria-expanded')) === 'true');
    check('desktop: over the draft dialog the panel is a sheet above it, not the inert column', (await panel(page).evaluate((el) => el.tagName)) !== 'ASIDE', await panel(page).evaluate((el) => el.tagName));
    check('desktop: suggestions fit the Queue page', (await panel(page).getByRole('group', { name: 'Suggested questions' }).count()) === 1);
    answer = await ask(page, 'What is the status of this draft?');
    const statusText = await answer.innerText();
    check('desktop: the answer reads the draft open in the dialog', /LinkedIn draft/.test(statusText) && /not scheduled|Still needed/.test(statusText), statusText.slice(0, 300));
    // The harness's canned LinkedIn consent grants no publishing scope, so the account is never "Ready for posting":
    // the answer must say so with the app's own reason, offer no proposal, and prepare nothing.
    answer = await ask(page, 'Schedule this draft for Friday at 16:30');
    let snapshot = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    check('desktop: scheduling on an account that cannot post is refused with the app\'s reason, nothing prepared',
      /can't prepare that yet: Verify this exact fixture account/.test(await answer.innerText()) && (await answer.getByRole('button', { name: 'Apply change' }).count()) === 0
        && !snapshot.state.phase2.reviews.some((r) => r.manifest.variantId === seeded.draftId), (await answer.innerText()).slice(0, 300));
    // "Does this sound like me?" with nothing stored to compare against: Rafii says so and judges nothing.
    answer = await ask(page, 'Does this sound like me?');
    const voiceText = await answer.innerText();
    check('desktop: "Does this sound like me?" with no stored voice says so and judges nothing',
      /no approved voice profile or learned preference to compare with/.test(voiceText) && !/Checked against your stored voice/.test(voiceText), voiceText.slice(0, 300));
    // A compound request reports each step with its real state: revised through the writing pipeline (a proposed update
    // on this draft), linked to the campaign, and scheduling on an account that cannot post needs the person.
    answer = await ask(page, 'Shorten this draft, add it to the practising slowly campaign and schedule it for Thursday at 6 PM');
    const compoundText = await answer.innerText();
    snapshot = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    const reworked = snapshot.state.variants.find((v) => v.id === seeded.draftId);
    check('desktop: a compound request lists each step: revised, linked, scheduling needs you on this account, nothing prepared',
      /Revise the draft/.test(compoundText) && /linked to “/.test(compoundText) && /Schedule it/.test(compoundText) && /Needs you/.test(compoundText)
        && Boolean(reworked && reworked.proposedUpdate) && (await answer.getByRole('button', { name: 'Apply change' }).count()) === 0
        && !snapshot.state.phase2.reviews.some((r) => r.manifest.variantId === seeded.draftId), compoundText.slice(0, 500));
    await shot(page, 'site-agent-desktop-over-dialog.png');
    await page.keyboard.press('Escape');
    await panel(page).waitFor({ state: 'hidden', timeout: 10000 });
    check('desktop: Escape closes only Rafii\'s sheet; the draft dialog stays', (await page.locator('.t-modal-backdrop[data-open]').count()) >= 1);
    await page.keyboard.press('Escape');
    await page.locator('.t-modal-backdrop[data-open]').first().waitFor({ state: 'detached', timeout: 10000 }).catch(() => {});
    await page.keyboard.press(hotkey);
    await panel(page).waitFor({ state: 'visible', timeout: 30000 });
    check('desktop: with no dialog open, the panel docks beside the page', (await panel(page).evaluate((el) => el.tagName)) === 'ASIDE', await panel(page).evaluate((el) => el.tagName));
    await page.waitForFunction(() => document.querySelectorAll('#rafii-panel article[aria-label="Rafii\'s answer"]').length >= 2, null, { timeout: 60000 }).catch(() => {});
    check('desktop: the same conversation continues in the column', (await answers(page).count()) >= 2, await answers(page).count());

    // An automation change is a proposal the person applies; the builder open behind it is re-read afterwards.
    await page.goto(`${base}/app/automations?edit=${seeded.taskId}`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    await page.locator('.t-modal-backdrop[data-open]').first().waitFor({ timeout: 120000 });
    await page.keyboard.press(hotkey);
    await panel(page).waitFor({ state: 'visible', timeout: 30000 });
    check('desktop: over the automation builder, ⌘J shows Rafii as a sheet above it', (await panel(page).evaluate((el) => el.tagName)) !== 'ASIDE');
    answer = await ask(page, 'Move it to Thursday at 18:00');
    const apply = answer.getByRole('button', { name: 'Apply change' });
    check('desktop: an automation change is a proposal with Apply and Dismiss', (await apply.count()) === 1 && (await answer.getByRole('button', { name: 'Dismiss' }).count()) === 1, (await answer.innerText()).slice(0, 300));
    snapshot = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    const before = snapshot.state.raffi.campaignPlanning.recurringTasks.find((t) => t.id === seeded.taskId).schedule;
    check('desktop: nothing changes before Apply', JSON.stringify(before).includes('Friday') && !JSON.stringify(before).includes('Thursday'), before);
    await apply.click();
    await answer.getByText('Applied. The automation now follows the new plan.').waitFor({ timeout: 60000 });
    snapshot = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    const after = snapshot.state.raffi.campaignPlanning.recurringTasks.find((t) => t.id === seeded.taskId).schedule;
    check('desktop: Apply changed the stored automation to Thursday 18:00', JSON.stringify(after).includes('Thursday') && JSON.stringify(after).includes('18:00'), after);
    check('desktop: the builder does not jump above Rafii\'s answer', await answer.isVisible() && (await page.locator('#rafii-panel').count()) === 1);
    await shot(page, 'site-agent-desktop-proposal.png');
    await page.keyboard.press('Escape');
    // Rafii's sheet closes; the column the person had open before is back as it was (inert behind the builder).
    await page.waitForFunction(() => { const el = document.querySelector('#rafii-panel'); return !el || el.tagName === 'ASIDE'; }, null, { timeout: 10000 });
    check('desktop: Escape closes only Rafii\'s sheet over the builder; the column is back as it was', (await page.locator('.t-modal-backdrop[data-open]').count()) >= 1);
    await page.waitForTimeout(800);
    await page.getByRole('tab', { name: '4 · Review' }).click({ timeout: 30000 });
    const review = page.locator('#automation-step-review');
    await review.waitFor({ timeout: 30000 });
    const builderText = await review.innerText();
    check('desktop: after Rafii\'s sheet closes, the open builder shows the applied plan', /Thursday|Thu/.test(builderText) && /18:00|6:00\s*PM|6 PM/i.test(builderText), builderText.slice(0, 400));
    await page.keyboard.press('Escape');
    await page.locator('.t-modal-backdrop[data-open]').first().waitFor({ state: 'detached', timeout: 10000 }).catch(() => {});

    // Navigation and reload keep the docked conversation.
    if (!(await panel(page).isVisible())) await page.keyboard.press(hotkey);
    await panel(page).waitFor({ state: 'visible', timeout: 30000 });
    check('desktop: after the builder closes, the docked column is usable', (await panel(page).evaluate((el) => el.tagName)) === 'ASIDE');
    await page.waitForFunction(() => document.querySelectorAll('#rafii-panel article[aria-label="Rafii\'s answer"]').length >= 3, null, { timeout: 60000 }).catch(() => {});
    const turns = await answers(page).count();
    await page.getByRole('link', { name: 'Calendar', exact: true }).first().click();
    await page.waitForURL(/\/app\/calendar/, { timeout: 120000 });
    await page.waitForTimeout(800);
    check('desktop: the panel stays open across navigation', await panel(page).isVisible());
    check('desktop: the conversation survives navigation', (await answers(page).count()) === turns, { before: turns, after: await answers(page).count() });
    answer = await ask(page, 'What page am I on?');
    check('desktop: the page context follows navigation', /Calendar/.test(await answer.innerText()), (await answer.innerText()).slice(0, 200));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await ready(page);
    await panel(page).waitFor({ state: 'visible', timeout: 60000 });
    await page.waitForFunction((n) => document.querySelectorAll('#rafii-panel article[aria-label="Rafii\'s answer"]').length >= n, turns + 1, { timeout: 120000 }).catch(() => {});
    check('desktop: a reload restores the open panel and the conversation', (await answers(page).count()) >= turns + 1, await answers(page).count());
    const violations = await axe(page);
    check('desktop: axe finds no serious or critical issue in the open panel', violations.length === 0, violations);
    check('desktop: nothing scrolls sideways with the panel open', await noSideScroll(page));
    await shot(page, 'site-agent-desktop-docked.png');
    await composer(page).focus();
    await page.keyboard.press('Escape');
    await panel(page).waitFor({ state: 'hidden', timeout: 10000 });
    const focused = await page.waitForFunction(() => document.activeElement?.id === 'rafii-launcher', null, { timeout: 5000 }).then(() => true, () => false);
    check('desktop: Escape closes the panel and focus returns to the launcher', focused, await page.evaluate(() => document.activeElement?.outerHTML?.slice(0, 120)));
    await desk.close();
    }

    if (want('help')) {
    // --- help pages hand a question to the panel ----------------------------------------------------------------------
    const help = await context(browser, { width: 1280, height: 860 });
    const hpage = await help.newPage();
    await hpage.goto(`${base}/app/help`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(hpage);
    await hpage.getByRole('link', { name: /Queue and drafts/i }).first().click();
    await hpage.waitForURL(/\/app\/help\/help_queue/, { timeout: 120000 });
    const opened = await hpage.getByRole('heading', { level: 1, name: /Queue and drafts/ }).waitFor({ timeout: 60000 }).then(() => true, () => false);
    check('help: an article opens from the index', opened, await hpage.getByRole('heading', { level: 1 }).allInnerTexts());
    await hpage.getByRole('button', { name: /Ask Rafii about this/i }).click();
    await panel(hpage).waitFor({ state: 'visible', timeout: 30000 });
    check('help: "Ask Rafii about this" opens the panel with the question ready', ((await composer(hpage).inputValue()) || '').length > 0, await composer(hpage).inputValue());
    await shot(hpage, 'site-agent-help.png');
    await help.close();

    }

    if (want('tablet')) {
    // --- tablet: the panel slides in as a sheet -------------------------------------------------------------------------
    const tablet = await context(browser, { width: 834, height: 1112 });
    const tpage = await tablet.newPage();
    await tpage.goto(`${base}/app/channels`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(tpage);
    await launcher(tpage).click();
    await panel(tpage).waitFor({ state: 'visible', timeout: 30000 });
    check('tablet: the launcher opens the panel as a dialog sheet', (await tpage.getByRole('dialog').count()) >= 1);
    answer = await ask(tpage, 'What can I do here?');
    check('tablet: page question answered for Channels', /Channels/i.test(await answer.innerText()), (await answer.innerText()).slice(0, 200));
    check('tablet: nothing scrolls sideways', await noSideScroll(tpage));
    await shot(tpage, 'site-agent-tablet.png');
    await panel(tpage).getByRole('button', { name: 'Close Rafii' }).click();
    await panel(tpage).waitFor({ state: 'hidden', timeout: 10000 });
    check('tablet: the close button closes the sheet', !(await panel(tpage).isVisible()));
    await tablet.close();

    }

    if (want('phone')) {
    // --- phone: a drawer, a 16px composer (no zoom on focus), no sideways scroll; reduced motion ------------------------
    const phone = await context(browser, { width: 390, height: 844 }, { reducedMotion: 'reduce' });
    const ppage = await phone.newPage();
    await ppage.goto(`${base}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(ppage);
    await launcher(ppage).click();
    await panel(ppage).waitFor({ state: 'visible', timeout: 30000 });
    const fontSize = await composer(ppage).evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    check('phone: the composer is 16px so iOS does not zoom', fontSize >= 16, fontSize);
    const box = await panel(ppage).boundingBox();
    check('phone: the drawer fits the screen width', box && box.width <= 390 + 1, box);
    await composer(ppage).fill('What is scheduled this week?');
    await composer(ppage).press('Enter');
    const ring = await ppage.evaluate(() => {
      const el = document.querySelector('#rafii-panel .ring-2');
      return el ? getComputedStyle(el).animationName : 'none';
    });
    check('phone: reduced motion keeps the thinking ring still', ring === 'none', ring);
    await ppage.waitForFunction(() => document.querySelectorAll('#rafii-panel article[aria-label="Rafii\'s answer"]').length > 0, null, { timeout: 180000 });
    const calendarAnswer = await answers(ppage).last().innerText();
    check('phone: the calendar question is answered from stored state', /scheduled or waiting|Nothing is scheduled/i.test(calendarAnswer), calendarAnswer.slice(0, 200));
    check('phone: nothing scrolls sideways', await noSideScroll(ppage));
    await ppage.waitForTimeout(500);
    const composerBox = await composer(ppage).boundingBox();
    check('phone: after an answer the composer is fully on screen', Boolean(composerBox) && composerBox.y >= 0 && composerBox.y + composerBox.height <= 844, composerBox);
    await shot(ppage, 'site-agent-phone.png');
    await phone.close();
    }
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok);
  fs.writeFileSync(path.join(out, 'site-agent-browser.json'), JSON.stringify({ base, engine: args.browser || 'chromium', principal: 'synthetic', sections: args.sections || 'all', results }, null, 1));
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})().catch((error) => {
  console.error(error);
  // A run that stops early (a browser crash) still records what it checked, and why it stopped.
  fs.writeFileSync(path.join(out, 'site-agent-browser.json'), JSON.stringify({ base, engine: args.browser || 'chromium', principal: 'synthetic', sections: args.sections || 'all', results, stoppedBy: String(error && error.message || error).slice(0, 300) }, null, 1));
  process.exit(1);
});
