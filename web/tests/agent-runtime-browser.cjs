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
  const res = await fetch(base + url, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

/** A valid PNG written without any image library: solid colour, or random noise (which barely compresses, like a photo). */
function png(width = 480, height = 480, noise = false) {
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
  const row = () => Buffer.concat([Buffer.from([0]), noise ? require('node:crypto').randomBytes(width * 3) : Buffer.alloc(width * 3, 0x7a)]);
  const raw = Buffer.concat(Array.from({ length: height }, row));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

/** Fixture (as in the PostgreSQL suites): an owner's approved spending budget, written to the harness's own database. Budget approval
 *  is an operator data decision in this product, not an API; without it every paid route (voice included) is refused with 402. */
/** Fixture (as in the PostgreSQL suites): the harness's canned LinkedIn consent grants no publishing scope, so no harness account is ever
 *  "Ready for posting". This marks that account server-verified with the publish scope, through the same command the scenarios use. */
function verifyLinkedIn(workspaceId) {
  const { execFileSync } = require('node:child_process');
  const root = path.resolve(__dirname, '../..');
  const code = [
    'import psycopg, time',
    'from postriff_phase2.hosted import HostedWorkspaceService',
    `dsn = "host=127.0.0.1 port=${process.env.RAFII_HARNESS_PG_PORT || '55622'} dbname=postgres"`,
    `svc = HostedWorkspaceService(lambda: psycopg.connect(dsn), lambda token: ${JSON.stringify(principal)})`,
    `snap = svc.repository.get(${JSON.stringify(workspaceId)}, "fixture")`,
    'ch = next(c for c in snap["state"]["phase2"]["channels"] if c["platform"] == "LinkedIn")',
    'rec = {"id": ch["id"], "platform": "LinkedIn", "account": ch["account"], "accountType": ch.get("accountType") or "member", "scopes": ["w_member_social"], "verifiedAt": time.time(), "expiresAt": time.time() + 10**7, "capabilityVersion": ch.get("capabilityVersion") or 1, "providerAccountId": ch.get("providerAccountId") or "urn:dev:fixture"}',
    `svc.repository.command(${JSON.stringify(workspaceId)}, "fixture", snap["revision"], lambda s, a: svc.commands.upsert_verified_channel(s, a, rec))`
  ].join('\n');
  execFileSync(process.env.RAFII_PYTHON || 'python3', ['-c', code], { cwd: root, env: { ...process.env, PYTHONPATH: 'src:tests' }, stdio: 'inherit' });
}

function approveBudget(workspaceId) {
  const { execFileSync } = require('node:child_process');
  const root = path.resolve(__dirname, '../..');
  const code = `import psycopg\nfrom consumer_fixtures import approve_budgets\napprove_budgets(lambda: psycopg.connect("host=127.0.0.1 port=${process.env.RAFII_HARNESS_PG_PORT || '55622'} dbname=postgres"), ${JSON.stringify(workspaceId)})`;
  execFileSync(process.env.RAFII_PYTHON || 'python3', ['-c', code], { cwd: root, env: { ...process.env, PYTHONPATH: 'src:tests' }, stdio: 'inherit' });
}

async function seed() {
  const { workspaceId } = await call('POST', '/api/auth/verify', {});
  approveBudget(workspaceId);
  const start = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/start`, { capability: 'publish' });
  const state = new URL(start.authorizeUrl).searchParams.get('state');
  const done = await call('POST', `/api/workspaces/${workspaceId}/channels/linkedin/oauth/complete`, { state, code: 'good-code' });
  if (!done.connected) throw new Error('LinkedIn did not connect in the harness');
  verifyLinkedIn(workspaceId);
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

/** Type a question and send it. The local Playwright WebKit build (2359) aborts inside AppKit's text-input hook
 *  (NSTextInputContext textInputClientDidUpdateSelection, unrecognised on this macOS) when a field is filled after a
 *  client-side navigation; on WebKit the value is set through the DOM with a real input event (React's own change path)
 *  and sent with the Send button. Chromium types normally. Either way the app's real submit path runs. */
async function askTyped(page, text) {
  if (args.browser === 'webkit') {
    await composer(page).evaluate((el, value) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, text);
    await panel(page).getByRole('button', { name: 'Send' }).click();
  } else {
    await composer(page).fill(text);
    await composer(page).press('Enter');
  }
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
      if (new URL(res.url()).pathname.endsWith('/agent/voice/sessions')) voiceResponses.push(await res.text().catch(() => ''));
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
    // “next Thursday”: the harness runs on the real clock, and the app refuses a time in the past (as it should).
    const compound = await say(page, 'Make a matching LinkedIn asset, write the copy, add them to the campaign and schedule it next Thursday at 18:00');
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

    // Navigate with the call on: the session survives, and Live is told where the person is.
    await page.getByRole('link', { name: 'Calendar' }).first().click();
    await page.waitForURL(/\/app\/calendar/, { timeout: 120000 });
    await page.waitForTimeout(800);
    const stillLive = (await voiceState(page)) === 'live';
    const told = (await sent(page)).some((e) => e.type === 'session.thinking.append' && /Calendar/.test(e.content));
    check('V-A02: moving to Calendar keeps Voice Mode live, and Live hears about the page change', stillLive && told);
    await openPanel(page);

    // Spoken “yes” binds to exactly that proposal; the server re-checks and applies; the result is re-read.
    const yes = await say(page, 'yes');
    const after = await call('GET', `/api/workspaces/${seeded.workspaceId}`);
    const review = after.state.phase2.reviews.find((r) => r.manifest?.timing?.local?.endsWith('T18:00'));
    check('V-A18/V-A07: after moving pages, the spoken “yes” applied exactly the presented proposal; a review now waits for approval at 18:00 with the image; nothing published',
      Boolean(review) && review.status === 'needs_review' && (review.manifest.media ?? []).length === 1 && after.state.phase2.jobs.length === 0 && /checked/i.test(yes ? await yes.innerText() : ''),
      { reviews: after.state.phase2.reviews.map((r) => [r.status, r.manifest?.timing?.local]) });

    // Type while the call is on: the typed turn is answered and Live gets it as context.
    const typedBefore = await answers(page).count();
    await askTyped(page, 'What is still open?');
    await waitAnswers(page, typedBefore + 1);
    check('typing during voice works in the same conversation; Live gets the exchange as context',
      (await sent(page)).some((e) => e.type === 'session.thinking.append' && /The user typed/.test(e.content)));

    // A long call: past 60 transcript lines (the list keeps the last 60), a spoken request still carries exactly its own words.
    for (let i = 0; i < 36; i += 1) {
      await live(page, (n) => window.rafiiLiveHarness.userSays(`note number ${n}`, { delegate: false }), i);
      await live(page, (n) => window.rafiiLiveHarness.rafiiSays(`okay ${n}`, { chunkMs: 0 }), i);
    }
    await say(page, 'Tell me the next step for the launch');
    const longCall = await say(page, 'What is on the calendar this week?');
    const working = (await sent(page)).filter((e) => e.type === 'session.thinking.append' && e.content.startsWith('Working on:')).map((e) => e.content);
    check('long call: past 60 transcript lines, a spoken request still carries exactly its own words', Boolean(longCall) && Boolean(working.at(-1)?.startsWith('Working on: What is on the calendar this week?.')), working.at(-1));

    // A brief drop that WebRTC recovers by itself: back to live on its own, and End voice stays available meanwhile.
    await live(page, () => window.rafiiLiveHarness.drop());
    await page.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'reconnecting', null, { timeout: 10000 });
    const endWhileDropped = await panel(page).getByRole('button', { name: 'End voice' }).isVisible();
    await live(page, () => window.rafiiLiveHarness.recover());
    await page.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'live', null, { timeout: 10000 }).catch(() => null);
    const recovered = (await page.evaluate(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice'))) === 'live';
    check('a brief drop that recovers returns to live by itself; End voice stays available while reconnecting', endWhileDropped && recovered, { endWhileDropped, recovered });

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
    await askTyped(page, 'Thanks. What did we just schedule?');
    await waitAnswers(page, endBefore + 1);
    check('V-A09: after voice ends, text continues the same conversation', (await answers(page).count()) === endBefore + 1);
    await shot(page, 'voice-desktop-ended.png');

    // A photo bigger than a Vercel request allows (4.5 MB) is scaled down in the browser and still added.
    const big = path.join(out, 'large-photo.png');
    fs.writeFileSync(big, png(1600, 1300, true));
    const upload = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/agent/attachments'), { timeout: 60000 });
    await panel(page).locator('input[type="file"][accept="image/png,image/jpeg"]').setInputFiles(big);
    const uploaded = await upload.catch(() => null);
    const bodyBytes = Buffer.byteLength(uploaded?.request().postData() ?? '');
    check('MM01: a photo larger than a request allows is scaled down in the browser (body under 4.5 MB) and added',
      fs.statSync(big).size > 4_500_000 && bodyBytes > 0 && bodyBytes < 4_500_000 && uploaded?.status() === 201, { fileBytes: fs.statSync(big).size, bodyBytes, status: uploaded?.status() });
    fs.rmSync(big, { force: true });
    await desk.close();

    // --- microphone denied: the real WebRTC transport, no fake; text still works ------------------------------------------
    if (args.browser !== 'webkit') {
      const deniedBrowser = await engine.launch({ headless: true, executablePath, args: ['--deny-permission-prompts'] });
      const deniedCtx = await context(deniedBrowser, { width: 1280, height: 860 }, { fakeLive: false });
      await deniedCtx.grantPermissions([], { origin: base });
      const dp = await deniedCtx.newPage();
      await dp.goto(`${base}/app`, { waitUntil: 'domcontentloaded', timeout: 400000 });
      await ready(dp);
      await openPanel(dp);
      await panel(dp).getByRole('button', { name: 'Talk to Rafii' }).click();
      await dp.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'error', null, { timeout: 30000 });
      const deniedText = await panel(dp).innerText();
      await askTyped(dp, 'What page am I on?');
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
    await waitAnswers(pp, 1).catch(() => null);
    check('V-A11: a Cantonese request is delegated and answered in the same conversation', (await answers(pp).count()) >= 1);
    await shot(pp, 'voice-phone.png');
    await panel(pp).getByRole('button', { name: 'End voice' }).click();
    await pp.waitForFunction(() => document.querySelector('[data-rafii-voice]')?.getAttribute('data-rafii-voice') === 'ended', null, { timeout: 30000 }).catch(() => null);
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
    // Leaving the signed-in app with the call on (as signing out does, a client-side navigation): the call ends with it.
    await tp.evaluate(() => window.next.router.push('/auth/sign-in'));
    await tp.waitForFunction(() => (window.rafiiLiveHarness?.sent ?? []).some((e) => e.type === 'session.close'), null, { timeout: 30000 }).catch(() => null);
    const closedOnLeave = await tp.evaluate(() => (window.rafiiLiveHarness?.sent ?? []).some((e) => e.type === 'session.close'));
    check('leaving the app (as signing out does) ends the call and releases the microphone', closedOnLeave);
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
