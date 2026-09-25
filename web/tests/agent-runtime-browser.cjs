/**
 * Rafii Voice Mode and multimodal turns in a real browser against the local dev harness (spec §32 V-A01…V-A20, §33).
 *
 *   node web/tests/agent-runtime-browser.cjs [--browser=chromium|webkit] [--out=dir] [--shots=off]
 *
 * What is real: the web app, the Rafii panel, the agent API, the Agent Runtime's tools, the PostgreSQL workspace, the
 * writing pipeline (preview writer), proposals, the approval path and the verification re-read. What stands in for an
 * external provider: GPT-Live (a scriptable in-page transport, window.rafiiLiveHarness, development builds only) and the
 * reasoning/image models (the API harness's deterministic Manager, RAFII_AGENT_HARNESS=1). Chromium's fake microphone
 * is used where a real getUserMedia call matters (permission denied). No provider is contacted; no post is approved.
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const { randomUUID } = require('node:crypto');
const base = process.env.RAFII_WEB_URL || 'http://localhost:3290';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
const out = path.resolve(args.out || '.');
fs.mkdirSync(out, { recursive: true });
const principal = randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const results = [];
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

/** A small valid PNG (solid colour), written without any image library. */
function png(width = 480, height = 480) {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([len, body, sum]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 0x7a)]);
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

async function seed() {
  const { workspaceId } = await call('POST', '/api/auth/verify', {});
  const start = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/start`, { capability: 'publish' });
  const state = new URL(start.authorizeUrl).searchParams.get('state');
  const done = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/complete`, { state, code: 'good-code' });
  if (!done.connected) throw new Error('LinkedIn did not connect in the harness');
  let snapshot = await call('GET', `/api/workspaces/${workspaceId}`);
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, {
    expectedRevision: snapshot.revision, action: 'raffi_campaign_create',
    payload: { goal: 'Autumn launch of the practice journal', audience: 'Adult piano learners returning to the instrument', facts: { product: 'Practice journal' } }
  });
  const status = await call('GET', `/api/workspaces/${workspaceId}/agent/status`);
  return { workspaceId, status };
}

async function context(browser, viewport, extra = {}) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark', hasTouch: viewport.width < 768, isMobile: viewport.width < 768, ...extra });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await ctx.addInitScript(({ id, tours, fake }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
    if (fake) window.RAFII_FAKE_LIVE = true;
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '.tsqd-parent-container{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: principal, tours: TOURS, fake: extra.fakeLive !== false });
  return ctx;
}

const launcher = (page) => page.locator('#rafii-launcher');
const panel = (page) => page.locator('#rafii-panel');
const composer = (page) => panel(page).getByLabel('Ask Rafii', { exact: true });
const answers = (page) => panel(page).getByRole('article', { name: "Rafii's answer" });
const voiceState = (page) => page.locator('[data-rafii-voice]').first().getAttribute('data-rafii-voice');
const live = (page, fn, arg) => page.evaluate(fn, arg);
const sent = (page) => page.evaluate(() => (window.rafiiLiveHarness?.sent ?? []).map((e) => ({ type: e.type, delegation_id: e.delegation_id ?? null, content: String(e.content ?? '').slice(0, 300) })));

async function ready(page) {
  await launcher(page).waitFor({ state: 'visible', timeout: 400000 });
  await page.waitForFunction(() => document.querySelector('#rafii-launcher') && !document.querySelector('#rafii-launcher').disabled, null, { timeout: 400000 });
  await page.waitForTimeout(300);
}

async function openPanel(page) {
  if (!(await panel(page).isVisible().catch(() => false))) await launcher(page).click();
  await panel(page).waitFor({ state: 'visible', timeout: 30000 });
}

async function waitAnswers(page, count, timeout = 120000) {
  await page.waitForFunction((n) => document.querySelectorAll('#rafii-panel article[aria-label="Rafii\'s answer"]').length >= n, count, { timeout });
}

async function say(page, text, options) {
  const before = await answers(page).count();
  await live(page, ([t, o]) => window.rafiiLiveHarness.userSays(t, o), [text, options ?? {}]);
  if (options?.delegate === false) return null;
  await waitAnswers(page, before + 1);
  await page.waitForFunction((n) => (window.rafiiLiveHarness?.sent ?? []).filter((e) => e.type === 'session.commentary.append').length >= n, 1, { timeout: 60000 });
  return answers(page).nth(before);
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
  check('seed: workspace, LinkedIn account, a campaign; the agent runtime reports voice available (harness)', Boolean(seeded.workspaceId && seeded.status?.voice?.available && seeded.status?.manager?.available), seeded.status);
  const executablePath = (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const launchArgs = args.browser === 'webkit' ? [] : ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'];
  const browser = await engine.launch({ headless: true, executablePath, args: launchArgs });
  const voiceResponses = [];
  try {
    // --- desktop: a full voice session in the panel ---------------------------------------------------------------------
    const desk = await context(browser, { width: 1440, height: 900 });
    const page = await desk.newPage();
    page.on('response', async (res) => {
      if (/\/agent\/voice\/sessions$/.test(new URL(res.url()).pathname)) voiceResponses.push(await res.text().catch(() => ''));
    });
    await page.goto(`${base}/app/automations`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    await openPanel(page);
    const talk = panel(page).getByRole('button', { name: 'Talk to Rafii' });
    await talk.waitFor({ timeout: 60000 });
    check('V-A01: Voice Mode is offered in the panel with a privacy note', (await talk.isEnabled()) && /keeps a text transcript, not the audio/.test(await panel(page).innerText()));
    await talk.click();
    await page.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'live', null, { timeout: 60000 });
    check('V-A01: voice connects (server-created Live session; the browser only sent its offer)', (await voiceState(page)) === 'live');
    check('V-A20: the voice session response carries no credential', voiceResponses.length > 0 && voiceResponses.every((t) => !/sk-|harness-placeholder|OPENAI_API_KEY/i.test(t)), voiceResponses.map((t) => t.slice(0, 120)));
    const status = page.locator('[data-rafii-voice-status]');
    check('status reads Listening, from session events', /Listening/.test(await status.innerText()));

    const first = await say(page, 'What is missing in the autumn launch campaign?');
    const firstText = first ? await first.innerText() : '';
    const commentary = (await sent(page)).filter((e) => e.type === 'session.commentary.append');
    check('V-A02/V-A04: the spoken request became a backend turn; the answer is in the panel and spoken back with the delegation id', Boolean(first) && commentary.length >= 1 && Boolean(commentary[0].delegation_id), { firstText: firstText.slice(0, 200), commentary });
    const transcript = await page.locator('[data-rafii-voice-transcript]').innerText();
    check('the transcript shows what was said, in the same panel', /What is missing in the autumn launch campaign/.test(transcript));

    // Barge-in: Rafii is speaking; the person starts talking; Rafii's speech stops (full duplex).
    void live(page, () => window.rafiiLiveHarness.rafiiSays('Here is a long explanation of everything in the campaign, one detail after another, slowly and carefully, so there is time to interrupt.', { chunkMs: 60 }));
    await page.waitForFunction(() => window.rafiiLiveHarness.speaking(), null, { timeout: 5000 });
    const speakingStatus = await status.innerText();
    await live(page, () => window.rafiiLiveHarness.userSays('wait', { delegate: false }));
    const lineAt = async () => page.evaluate(() => [...document.querySelectorAll('[data-rafii-voice-transcript] li[data-role="assistant"]')].at(-1)?.textContent ?? '');
    const cut = await lineAt();
    await page.waitForTimeout(700);
    check('V-A03: interrupting stops Rafii mid-sentence (no more speech after the person talks)', /speaking/i.test(speakingStatus) && (await lineAt()) === cut && !(await page.evaluate(() => window.rafiiLiveHarness.speaking())), { speakingStatus, cut });

    // "Stop talking": local audio drops immediately and GPT-Live is told to yield.
    void live(page, () => window.rafiiLiveHarness.rafiiSays('Another long answer that goes on and on for a while so the stop button can be pressed.', { chunkMs: 60 }));
    await page.waitForFunction(() => window.rafiiLiveHarness.speaking(), null, { timeout: 5000 });
    await panel(page).getByRole('button', { name: 'Stop talking' }).click();
    await page.waitForTimeout(200);
    const stopped = (await sent(page)).some((e) => e.type === 'session.instructions.append' && /Stop speaking/.test(e.content));
    check('V-A03: “Stop talking” stops the audio and tells Live to listen', stopped && !(await page.evaluate(() => window.rafiiLiveHarness.speaking())));

    // Mute and unmute the microphone.
    await panel(page).getByRole('button', { name: 'Mute' }).click();
    const muted = !(await page.evaluate(() => window.rafiiLiveHarness.micEnabled()));
    await panel(page).getByRole('button', { name: 'Unmute' }).click();
    check('mute / unmute controls the microphone', muted && (await page.evaluate(() => window.rafiiLiveHarness.micEnabled())));

    // An image attached during the call; Rafii's backend looks at it.
    const file = path.join(out, 'reference.png');
    fs.writeFileSync(file, png());
    await panel(page).locator('input[type="file"][accept="image/png,image/jpeg"]').setInputFiles(file);
    await page.waitForFunction(() => /Image \d+ added/.test(document.querySelector('#rafii-panel')?.textContent ?? ''), null, { timeout: 60000 });
    const thought = (await sent(page)).some((e) => e.type === 'session.thinking.append' && /attached image/.test(e.content));
    const imageAnswer = await say(page, 'What do you think of this reference image?');
    check('V-A17/MM02: an image attached during voice goes to the backend (GPT-Live is told it can’t see it)', thought && Boolean(imageAnswer));

    // The compound request: image, copy, links, schedule proposal (shown and spoken).
    const compound = await say(page, 'Make a matching LinkedIn asset, write the copy, add them to the campaign and schedule it Thursday at 18:00');
    await page.waitForFunction(() => [...document.querySelectorAll('#rafii-panel figure[data-rafii-asset] img')].some((img) => img.src.startsWith('blob:')), null, { timeout: 60000 }).catch(() => null);
    const compoundText = compound ? await compound.innerText() : '';
    const applyButton = compound ? compound.getByRole('button', { name: /^Apply/ }) : null;
    const imageShown = await page.evaluate(() => [...document.querySelectorAll('#rafii-panel figure[data-rafii-asset] img')].some((img) => img.src.startsWith('blob:')));
    const spokenProposal = (await sent(page)).filter((e) => e.type === 'session.commentary.append').at(-1)?.content ?? '';
    check('X04/MM03: the compound request made the image and the draft, linked them, and stopped at a proposal shown and spoken', Boolean(applyButton && (await applyButton.count())) && imageShown && /Thursday|apply/i.test(spokenProposal),
      { compoundText: compoundText.slice(0, 400), imageShown, spokenProposal });
    await shot(page, 'voice-desktop-proposal.png');
    const before = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    check('nothing is prepared before the person decides', before.state.phase2.reviews.length === 0);

    // Spoken “yes” binds to exactly that proposal; the server re-checks and applies; the result is re-read.
    const yes = await say(page, 'yes');
    const after = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    const review = after.state.phase2.reviews.find((r) => r.manifest?.timing?.local?.endsWith('T18:00'));
    check('V-A07: spoken “yes” applied exactly the presented proposal; a review now waits for approval at 18:00 with the image; nothing published',
      Boolean(review) && review.status === 'needs_review' && (review.manifest.media ?? []).length === 1 && after.state.phase2.jobs.length === 0 && /checked/i.test(yes ? await yes.innerText() : ''),
      { reviews: after.state.phase2.reviews.map((r) => [r.status, r.manifest?.timing?.local]) });

    // Navigate with the call on: the session survives, and Live is told where the person is.
    await page.getByRole('link', { name: 'Calendar' }).first().click();
    await page.waitForURL(/\/app\/calendar/, { timeout: 120000 });
    await page.waitForTimeout(800);
    const stillLive = (await voiceState(page)) === 'live';
    const told = (await sent(page)).some((e) => e.type === 'session.thinking.append' && /Calendar/.test(e.content));
    check('V-A02: moving to Calendar keeps Voice Mode live, and Live hears about the page change', stillLive && told);

    // Type while the call is on: the typed turn is answered and Live gets it as context.
    await openPanel(page);
    const typedBefore = await answers(page).count();
    await composer(page).fill('What is still open?');
    await composer(page).press('Enter');
    await waitAnswers(page, typedBefore + 1);
    check('typing during voice works in the same conversation; Live gets the exchange as context',
      (await sent(page)).some((e) => e.type === 'session.thinking.append' && /The user typed/.test(e.content)));

    // Connection drop → truthful reconnect banner → reconnect in the same conversation.
    await live(page, () => window.rafiiLiveHarness.drop());
    await page.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'reconnecting', null, { timeout: 10000 });
    const banner = await panel(page).innerText();
    await panel(page).getByRole('button', { name: 'Reconnect' }).click();
    await page.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'live', null, { timeout: 60000 });
    check('V-A15: a dropped connection shows a truthful reconnect state; reconnecting resumes voice', /Connection lost/.test(banner) && /nothing waiting for approval was lost/i.test(banner));

    const axeLive = await axe(page);
    check('V-A19: axe finds no serious or critical issue with Voice Mode on', axeLive.length === 0, axeLive);

    // End voice; the same conversation continues by text.
    await panel(page).getByRole('button', { name: 'End voice' }).click();
    await page.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'ended', null, { timeout: 30000 });
    const endBefore = await answers(page).count();
    await composer(page).fill('Thanks. What did we just schedule?');
    await composer(page).press('Enter');
    await waitAnswers(page, endBefore + 1);
    check('V-A09: after voice ends, text continues the same conversation', (await answers(page).count()) === endBefore + 1);
    await shot(page, 'voice-desktop-ended.png');
    await desk.close();

    // --- microphone denied: the real WebRTC transport, no fake; text still works ------------------------------------------
    if (args.browser !== 'webkit') {
      const deniedBrowser = await engine.launch({ headless: true, executablePath, args: [] });
      const deniedCtx = await context(deniedBrowser, { width: 1280, height: 860 }, { fakeLive: false });
      await deniedCtx.grantPermissions([], { origin: base });
      const dp = await deniedCtx.newPage();
      await dp.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
      await ready(dp);
      await openPanel(dp);
      await panel(dp).getByRole('button', { name: 'Talk to Rafii' }).click();
      await dp.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'error', null, { timeout: 30000 });
      const deniedText = await panel(dp).innerText();
      await composer(dp).fill('What page am I on?');
      await composer(dp).press('Enter');
      await waitAnswers(dp, 1);
      check('V-A14: microphone denied → a plain explanation, and typing still works', /Microphone|microphone|voice calls/.test(deniedText) && (await answers(dp).count()) >= 1, deniedText.slice(0, 300));
      await deniedBrowser.close();
    }

    // --- phone: reduced motion, reachable controls, no side scroll ---------------------------------------------------------
    const phone = await context(browser, { width: 390, height: 844 }, { reducedMotion: 'reduce' });
    const pp = await phone.newPage();
    await pp.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(pp);
    await launcher(pp).click();
    await panel(pp).waitFor({ state: 'visible' });
    await panel(pp).getByRole('button', { name: 'Talk to Rafii' }).click();
    await pp.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'live', null, { timeout: 60000 });
    const endBox = await panel(pp).getByRole('button', { name: 'End voice' }).boundingBox();
    check('phone: Voice Mode controls are on screen', Boolean(endBox) && endBox.x >= 0 && endBox.x + endBox.width <= 390 && endBox.y + endBox.height <= 844, endBox);
    check('V-A19: reduced motion hides the level animation (the state text stays)', (await pp.locator('[data-rafii-voice-level]').count()) === 0 && /Listening/.test(await pp.locator('[data-rafii-voice-status]').innerText()));
    check('phone: nothing scrolls sideways with voice on', await pp.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1));
    await live(pp, () => window.rafiiLiveHarness.userSays('幫我睇下呢個 campaign 仲欠啲乜'));
    await pp.waitForFunction(() => (window.rafiiLiveHarness?.sent ?? []).some((e) => e.type === 'session.commentary.append'), null, { timeout: 120000 });
    check('V-A11: a Cantonese request is delegated and answered in the same conversation', (await answers(pp).count()) >= 1);
    await shot(pp, 'voice-phone.png');
    await phone.close();

    // --- tablet: sheet with voice ------------------------------------------------------------------------------------------
    const tablet = await context(browser, { width: 834, height: 1112 });
    const tp = await tablet.newPage();
    await tp.goto(`${base}/app/channels`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(tp);
    await launcher(tp).click();
    await panel(tp).waitFor({ state: 'visible' });
    await panel(tp).getByRole('button', { name: 'Talk to Rafii' }).click();
    await tp.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'live', null, { timeout: 60000 });
    check('tablet: Voice Mode runs in the sheet; nothing scrolls sideways', await tp.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1));
    await shot(tp, 'voice-tablet.png');
    await tablet.close();
  } catch (error) {
    check('browser run completed', false, String(error?.stack ?? error).slice(0, 800));
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok);
  fs.writeFileSync(path.join(out, 'agent-runtime-browser.json'), JSON.stringify({ browser: args.browser || 'chromium', base, at: new Date().toISOString(), results }, null, 1));
  process.stdout.write(`\n${results.length - failed.length}/${results.length} passed\n`);
  process.exit(failed.length ? 1 : 0);
})();
