/**
 * The Rafii live agent upgrade in a real browser against the local dev harness (docs/design/rafii-live-agent/CONTRACTS.md):
 * - how Rafii talks (Contract 1): the style control in More options, the style sheet and its three starting
 *   points, More options, Escape, Account › Preferences, a reload;
 * - `/` commands in the panel composer (Contract 7): the menu and its groups, filtering, Enter picks without sending,
 *   Esc, `/open channels`, `/style concise`, `/help`;
 * - `/weather Hong Kong` answered without a model.
 * The full-screen Live mode is checked by rafii-chat-concepts-browser.cjs. The old compact voice scenes below are kept
 * for historical reference and no longer run: their selectors describe the previous panel layout.
 * Guides and the on-screen cursor (Contract 5) are web/tests/rafii-guide-browser.cjs; they are not repeated here.
 *
 *   node web/tests/rafii-live-agent-browser.cjs [--browser=chromium|webkit] [--out=dir] [--shots=off]
 *     [--sections=style,style-phone,slash,slash-phone,weather]
 *
 * style, style-phone, slash and slash-phone run against RAFII_WEB_URL: any build of the web app and any local harness
 * that applied migration 030 (tests/phase2/rls.sql includes it).
 *
 * Weather runs against RAFII_VOICE_WEB_URL (default: RAFII_WEB_URL), backed by RAFII_AGENT_HARNESS=1 and the
 * disposable database at RAFII_VOICE_PG_PORT. It proves the API is the local stand-in before asking for weather.
 * The rafii-browser.yml job starts that pair on 4440/4441, beside the scenes' own harness and production build.
 *
 * Each section seeds its own synthetic principal through the harness API (`Bearer dev:<uuid>`), so a first call is
 * always a first call and sections can run alone (--sections resumes a run a crashed browser stopped). Nothing here
 * reaches a provider, publishes or approves anything. /weather is only sent after the API proved it is the QA harness
 * (its GPT-Live stand-in answered a session), so the real Open-Meteo is never called.
 */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3190';
const voiceBase = process.env.RAFII_VOICE_WEB_URL || base;
for (const url of [base, voiceBase]) {
  if (!['127.0.0.1', 'localhost'].includes(new URL(url).hostname)) throw new Error('Runs against the local harness only.');
}
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const engine = args.browser === 'webkit' ? webkit : chromium;
const SECTIONS = ['style', 'style-phone', 'slash', 'slash-phone', 'weather'];
const asked = args.sections ? String(args.sections).split(',').map((s) => s.trim()).filter(Boolean) : SECTIONS;
const unknown = asked.filter((name) => !SECTIONS.includes(name));
if (unknown.length) throw new Error(`Unknown section(s): ${unknown.join(', ')}. Sections: ${SECTIONS.join(', ')}. Full-screen Live is in web/tests/rafii-chat-concepts-browser.cjs.`);
const want = (name) => asked.includes(name);
const out = path.resolve(args.out || '.');
fs.mkdirSync(out, { recursive: true });
const ROOT = path.resolve(__dirname, '../..');
const read = (rel) => fs.readFileSync(path.resolve(__dirname, '../src', rel), 'utf8');

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

const TOUR_IDS = [...read('features/onboarding/tours.ts').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });

// The `/` commands and the menu's headings, read from the registry itself (web/src/lib/agent-runtime/commands.ts).
const COMMANDS_TS = read('lib/agent-runtime/commands.ts');
const COMMAND_NAMES = [...COMMANDS_TS.matchAll(/^\s*\{ name: '([a-z]+)'/gm)].map((m) => m[1]);
const COMMAND_GROUPS = [...COMMANDS_TS.matchAll(/\{ id: '[a-z_]+', label: '([^']+)' \}/g)].map((m) => m[1]);
// The three starting points (web/src/lib/agent-runtime/style.ts PRESETS, twin of agent_runtime_v2/style.py PRESETS).
const PRESETS = Object.fromEntries(
  [...read('lib/agent-runtime/style.ts').matchAll(/(\w+): \{ label: '([^']+)', description: '[^']*', style: \{ tone: '(\w+)', detail: '(\w+)', pace: '(\w+)', initiative: '(\w+)' \} \}/g)]
    .map(([, id, label, tone, detail, pace, initiative]) => [id, { label, fields: { tone, detail, pace, initiative } }])
);
if (COMMAND_NAMES.length < 10 || COMMAND_GROUPS.length < 3 || Object.keys(PRESETS).join() !== 'friendly,concise,explainer') {
  throw new Error(`Could not read the command registry or the style presets from source: ${JSON.stringify({ COMMAND_NAMES, COMMAND_GROUPS, PRESETS })}`);
}

const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok: Boolean(ok), detail: ok ? undefined : detail });
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 500)}` : ''}\n`);
};
// Screenshots are evidence for people; a failed capture is reported but is not a check.
async function shot(page, name) {
  if (args.shots === 'off') return;
  try {
    await page.screenshot({ path: path.join(out, name) });
  } catch (error) {
    process.stdout.write(`WARN screenshot ${name}: ${String(error?.message ?? error).slice(0, 200)}\n`);
  }
}

/** Polls `probe` until it returns something truthy (that value) or the time runs out (null). Not a fixed sleep. */
async function until(probe, { timeout = 15000, interval = 200 } = {}) {
  const end = Date.now() + timeout;
  for (;;) {
    let value = null;
    try {
      value = await probe();
    } catch {
      value = null;
    }
    if (value) return value;
    if (Date.now() >= end) return null;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

const esc = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const json = (text) => {
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const matches = (style, fields) => Boolean(style) && Object.entries(fields).every(([key, value]) => style[key] === value);

/* ---------------------------------------------------------------------------------------------------------------------- */
/* The harness: a synthetic person per section                                                                           */
/* ---------------------------------------------------------------------------------------------------------------------- */

function person(url) {
  const principal = randomUUID();
  const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };
  async function call(method, route, body) {
    const res = await fetch(url + route, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const text = await res.text();
    if (!res.ok) throw new Error(`${method} ${route} → ${res.status} ${text.slice(0, 300)}`);
    return text ? JSON.parse(text) : null;
  }
  return { url, principal, call };
}

/** A new principal with its own workspace (the harness bootstraps both on first sight). */
async function seed(url) {
  const who = person(url);
  const { workspaceId } = await who.call('POST', '/api/auth/verify', {});
  return { ...who, workspaceId };
}

/** GET /api/me → preferences.agentStyle (hosted.py `me`, normalised by agent_runtime_v2/style.py). */
const styleOf = async (who) => (await who.call('GET', '/api/me'))?.preferences?.agentStyle ?? null;

async function pollStyle(who, wanted, timeout = 20000) {
  let last = null;
  const hit = await until(async () => {
    last = await styleOf(who);
    return last && wanted(last) ? last : null;
  }, { timeout, interval: 300 });
  return { ok: Boolean(hit), style: hit ?? last };
}

/** Voice reserves spend: approve this workspace's budget in the voice harness's disposable database (fixture, as agent-runtime-browser.cjs). */
function approveBudget(workspaceId) {
  const port = Number(process.env.RAFII_VOICE_PG_PORT || process.env.RAFII_HARNESS_PG_PORT || 0);
  if (!port) return { ok: false, error: 'Set RAFII_VOICE_PG_PORT to the voice harness --pg-port: a voice session reserves spend, which needs an approved budget.' };
  const code = `import psycopg\nfrom consumer_fixtures import approve_budgets\napprove_budgets(lambda: psycopg.connect("host=127.0.0.1 port=${port} dbname=postgres"), ${JSON.stringify(workspaceId)})`;
  try {
    execFileSync(process.env.RAFII_PYTHON || 'python3', ['-c', code], { cwd: ROOT, env: { ...process.env, PYTHONPATH: 'src:tests' }, stdio: 'pipe' });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: String(error?.stderr || error?.message || error).slice(-400) };
  }
}

/** Budget approved and Voice Mode offered by this harness (agent status: voice available and both flags on). */
async function voiceReady(who, label) {
  const budget = approveBudget(who.workspaceId);
  check(`${label}: the synthetic workspace may spend on voice (budget approved in the harness database)`, budget.ok, budget.error);
  let status;
  try {
    status = await who.call('GET', `/api/workspaces/${who.workspaceId}/agent/status`);
  } catch (error) {
    status = { error: String(error.message).slice(0, 200) };
  }
  const on = Boolean(status?.voice?.available && status?.flags?.RAFII_VOICE_ENABLED && status?.flags?.RAFII_AGENT_V2_ENABLED);
  check(`${label}: the harness offers Voice Mode (agent status: voice available, RAFII_VOICE_ENABLED and RAFII_AGENT_V2_ENABLED on)`, on,
    { hint: 'start the API harness with RAFII_AGENT_HARNESS=1', voice: status?.voice, flags: status?.flags, error: status?.error });
  return budget.ok && on;
}

/**
 * Whether the API is the agent QA harness: its GPT-Live stand-in names sessions `live_harness_…` (harness.live_transport).
 * The same switch installs the Open-Meteo stand-in (agent_runtime_v2/http.py), so /weather never leaves the machine.
 */
async function qaHarness(who) {
  try {
    const started = await who.call('POST', `/api/workspaces/${who.workspaceId}/agent/voice/sessions`, { sdp: 'v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=rafii-scene-probe\r\nt=0 0\r\n' });
    await who.call('POST', `/api/workspaces/${who.workspaceId}/agent/voice/sessions/${encodeURIComponent(started.voiceSessionId)}/end`, { reason: 'user_ended', usageSeconds: 0 }).catch(() => null);
    return { ok: String(started.liveSessionId).startsWith('live_harness_'), liveSessionId: started.liveSessionId };
  } catch (error) {
    return { ok: false, error: String(error.message).slice(0, 300) };
  }
}

/* ---------------------------------------------------------------------------------------------------------------------- */
/* The browser                                                                                                           */
/* ---------------------------------------------------------------------------------------------------------------------- */

async function context(browser, who, viewport, { fakeLive = false, ...extra } = {}) {
  const phone = viewport.width < 768;
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: 'dark', hasTouch: phone, isMobile: phone, ...extra });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: who.url },
    { name: 'postriff_dev_principal', value: who.principal, url: who.url },
    { name: 'postriff_theme', value: 'rafii', url: who.url }
  ]);
  await ctx.addInitScript(({ id, tours, fake }) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', tours);
    // Read by createTransport when a call starts (development builds only).
    if (fake) window.RAFII_FAKE_LIVE = true;
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      // Query devtools and the Next.js dev indicator stay out of clicks and evidence.
      style.textContent = '.tsqd-parent-container,nextjs-portal{display:none!important}';
      document.head.appendChild(style);
    });
  }, { id: who.principal, tours: TOURS, fake: fakeLive });
  return ctx;
}

const launcher = (page) => page.locator('#rafii-launcher');
const panel = (page) => page.locator('#rafii-panel');
const composer = (page) => panel(page).getByLabel('Ask Rafii', { exact: true });
const answers = (page) => panel(page).getByRole('article', { name: "Rafii's answer" });
// StyleButton (rafii-voice/style-sheet.tsx) in the conversation header (site-agent/chat.tsx): "Rafii’s style: <preset>".
// Voice Mode's idle row carries a second one while voice is on; the header's comes first.
const stylePill = (page) => panel(page).getByRole('button', { name: /Rafii[’']s style:/ }).first();
async function revealStylePill(page) {
  const menu = panel(page).getByRole('button', { name: 'More Rafii options' });
  if ((await menu.getAttribute('aria-expanded')) !== 'true') await menu.click();
  await stylePill(page).waitFor({ timeout: 30000 });
}
const styleSheet = (page) => page.getByRole('dialog', { name: 'How Rafii talks to you' });
const firstRunSheet = (page) => page.getByRole('dialog', { name: 'How should Rafii talk to you?' });
const startingPoints = (sheet) => sheet.getByRole('radiogroup', { name: 'Starting points', exact: true });
const presetRadio = (sheet, id) => startingPoints(sheet).getByRole('radio', { name: new RegExp(`^${esc(PRESETS[id].label)}`) });
const setting = (sheet, group) => sheet.getByRole('radiogroup', { name: group, exact: true });
const commandMenu = (page) => panel(page).getByRole('listbox', { name: 'Commands', exact: true });
const commandNotes = (page) => panel(page).getByRole('list', { name: 'Panel commands', exact: true });
const voiceBox = (page) => panel(page).getByRole('region', { name: 'Voice Mode', exact: true });
const talkButton = (page) => panel(page).getByRole('button', { name: 'Talk to Rafii', exact: true });
const voiceStatus = (page) => panel(page).locator('[data-rafii-voice-status]');
const callIndicator = (page) => page.getByRole('region', { name: 'Rafii Voice Mode', exact: true });
const avatarStage = (page) => panel(page).locator('[data-rafii-3d]');

async function avatarSnapshot(page) {
  const stage = avatarStage(page);
  const count = await stage.count();
  if (!count) return null;
  return stage.first().evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return {
      count: document.querySelectorAll('#rafii-panel [data-rafii-3d]').length,
      surface: el.getAttribute('data-rafii-3d'),
      mode: el.getAttribute('data-rafii-avatar-mode'),
      mouth: Number(el.getAttribute('data-rafii-mouth-open') ?? '0'),
      ready: el.getAttribute('data-rafii-model-ready'),
      continuous: el.getAttribute('data-rafii-continuous-motion'),
      canvases: el.querySelectorAll('canvas').length,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    };
  });
}

async function ready(page) {
  await launcher(page).waitFor({ state: 'visible', timeout: 400000 });
  await page.waitForFunction(() => document.querySelector('#rafii-launcher') && !document.querySelector('#rafii-launcher').disabled, null, { timeout: 400000 });
}

/** Opens Rafii from the header; a click that lands before the page has hydrated is simply repeated. */
async function openPanel(page) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (await panel(page).isVisible().catch(() => false)) return true;
    if ((await launcher(page).getAttribute('aria-expanded').catch(() => null)) !== 'true') await launcher(page).click().catch(() => undefined);
    if (await panel(page).waitFor({ state: 'visible', timeout: 8000 }).then(() => true, () => false)) return true;
  }
  return false;
}

async function noSideScroll(page) {
  return page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1);
}

async function axe(page, selector) {
  if (!(await page.evaluate(() => Boolean(window.axe)))) await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async (sel) => {
    const result = await window.axe.run(sel, { resultTypes: ['violations'] });
    return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes[0]?.target }));
  }, selector);
}

/** Requests the checks read: style saves, voice sessions and turns to Rafii (node-side times, for ordering). */
function watchNetwork(page) {
  const net = { stylePatches: [], voiceStarts: [], voiceStartResponse: null, voiceEnds: [], turns: [], rafii3d: [], rafii3dFailures: [], rafii3dRuntimeErrors: [] };
  page.on('request', (request) => {
    const { pathname } = new URL(request.url());
    const method = request.method();
    const at = Date.now();
    if (method === 'PATCH' && pathname === '/api/me') net.stylePatches.push({ at, body: json(request.postData()) });
    else if (method === 'POST' && pathname.endsWith('/agent/voice/sessions')) net.voiceStarts.push({ at });
    else if (method === 'POST' && /\/agent\/voice\/sessions\/[^/]+\/end$/.test(pathname)) net.voiceEnds.push({ at, body: json(request.postData()) });
    else if (method === 'POST' && /\/(agent|site-agent)\/turns$/.test(pathname)) net.turns.push({ at, pathname, body: json(request.postData()) });
  });
  page.on('response', async (response) => {
    const pathname = new URL(response.url()).pathname;
    if (response.request().method() === 'POST' && pathname.endsWith('/agent/voice/sessions')) {
      net.voiceStartResponse = await response.json().catch(() => null);
    }
    if (pathname.endsWith('/raffi/raffi-live-v1.glb')) net.rafii3d.push({ status: response.status(), url: response.url() });
  });
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).pathname.endsWith('/raffi/raffi-live-v1.glb')) net.rafii3dFailures.push(request.failure()?.errorText ?? 'request failed');
  });
  page.on('console', (message) => {
    const text = message.text();
    if (message.type() === 'error' && /raffi-live-v1|rafii-live-avatar|webgl|three|gltf/i.test(text)) net.rafii3dRuntimeErrors.push(text.slice(0, 400));
  });
  page.on('pageerror', (error) => {
    const text = String(error?.message ?? error);
    if (/raffi-live-v1|rafii-live-avatar|webgl|three|gltf/i.test(text)) net.rafii3dRuntimeErrors.push(text.slice(0, 400));
  });
  return net;
}

/* ---------------------------------------------------------------------------------------------------------------------- */
/* style: the pill, the sheet, More options, Escape, Account › Preferences, a reload                                      */
/* ---------------------------------------------------------------------------------------------------------------------- */

async function styleSection(browser) {
  const who = await seed(base);
  const initial = await styleOf(who);
  check('style: a new person starts on the default style, not yet chosen (GET /api/me → preferences.agentStyle)',
    initial && initial.chosen === false && matches(initial, PRESETS.friendly.fields) && initial.voice === 'marin' && initial.language === 'auto', initial);
  const ctx = await context(browser, who, DESKTOP);
  try {
    const page = await ctx.newPage();
    const net = watchNetwork(page);
    await page.goto(`${base}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('style: the Rafii panel opens', await openPanel(page));
    await revealStylePill(page);
    const named = await panel(page).getByRole('button', { name: /Rafii[’']s style:.*Friendly/ }).first().waitFor({ timeout: 60000 }).then(() => true, () => false);
    const pill = stylePill(page);
    check('style: the conversation header has the style pill, naming the style in use (Friendly)', named, await pill.textContent().catch(() => null));
    check('style: the pill says it opens a dialog, closed for now', (await pill.getAttribute('aria-haspopup')) === 'dialog' && (await pill.getAttribute('aria-expanded')) === 'false');
    await shot(page, 'style-desktop-1-pill-in-panel-header.png');

    await pill.click();
    const sheet = styleSheet(page);
    await sheet.waitFor({ timeout: 30000 });
    const counts = await Promise.all(Object.keys(PRESETS).map((id) => presetRadio(sheet, id).count()));
    const radios = await startingPoints(sheet).getByRole('radio').count();
    check('style: the pill opens the style sheet with the three starting points (Friendly, Concise, Explain in detail)', radios === 3 && counts.every((n) => n === 1), { radios, counts });
    check('style: the sheet carries the marker that lets the panel leave Escape to it', (await page.locator('[data-rafii-style-sheet]').count()) === 1);
    check('style: Friendly is marked as the one in use', (await presetRadio(sheet, 'friendly').getAttribute('aria-checked')) === 'true');
    await shot(page, 'style-desktop-2-sheet-three-presets.png');

    await presetRadio(sheet, 'concise').click();
    let saved = await pollStyle(who, (s) => s.chosen === true && matches(s, PRESETS.concise.fields));
    check('style: picking Concise saves it (GET /api/me: direct tone, concise detail, normal pace, waits to be asked; chosen)', saved.ok, saved.style);
    check('style: … sent as PATCH /api/me { agentStyle: { preset: "concise", chosen: true } }',
      net.stylePatches.some((p) => p.body?.agentStyle?.preset === 'concise' && p.body.agentStyle.chosen === true), net.stylePatches.map((p) => p.body));
    const marked = await until(async () => (await presetRadio(sheet, 'concise').getAttribute('aria-checked')) === 'true');
    check('style: … and Concise is now the one marked', Boolean(marked));
    await shot(page, 'style-desktop-3-concise-picked.png');

    const more = sheet.getByRole('button', { name: 'More options', exact: true });
    check('style: More options starts folded for a starting point', (await more.getAttribute('aria-expanded')) === 'false');
    await more.click();
    const unfolded = await until(async () => (await more.getAttribute('aria-expanded')) === 'true' && (await setting(sheet, 'Tone').isVisible()));
    const values = {};
    for (const group of ['Tone', 'Detail', 'Speaking pace', 'Voice', 'Language', 'Suggestions']) {
      values[group] = ((await setting(sheet, group).locator('[role="radio"][aria-checked="true"]').textContent().catch(() => null)) ?? '').trim() || null;
    }
    check('style: More options opens tone, detail, speaking pace, voice, language and suggestions, set as Concise sets them',
      Boolean(unfolded) && same(values, { Tone: 'Direct', Detail: 'Concise', 'Speaking pace': 'Normal', Voice: 'Marin', Language: 'Match my language', Suggestions: 'Wait for me to ask' }), values);
    await shot(page, 'style-desktop-4-more-options.png');

    await setting(sheet, 'Voice').getByRole('radio', { name: 'Cedar', exact: true }).click();
    saved = await pollStyle(who, (s) => s.voice === 'cedar');
    check('style: choosing the Cedar voice saves it and keeps Concise (a voice is not part of a starting point)',
      saved.ok && matches(saved.style, PRESETS.concise.fields) && (await presetRadio(sheet, 'concise').getAttribute('aria-checked')) === 'true', saved.style);
    await setting(sheet, 'Speaking pace').getByRole('radio', { name: 'Slower', exact: true }).click();
    saved = await pollStyle(who, (s) => s.pace === 'slower');
    const customNote = await sheet.getByText('Custom: your own mix of the settings under More options.').waitFor({ timeout: 10000 }).then(() => true, () => false);
    const markedNone = (await startingPoints(sheet).locator('[role="radio"][aria-checked="true"]').count()) === 0;
    check('style: a slower pace makes a custom mix: saved, no starting point marked, and the sheet says “Custom”', saved.ok && customNote && markedNone, { style: saved.style, customNote, markedNone });
    await shot(page, 'style-desktop-5-custom-mix.png');
    await presetRadio(sheet, 'concise').click();
    saved = await pollStyle(who, (s) => matches(s, PRESETS.concise.fields) && s.voice === 'cedar');
    check('style: picking Concise again restores its settings and keeps the chosen voice', saved.ok, saved.style);

    const sheetIssues = await axe(page, '[data-rafii-style-sheet]');
    check('style: axe finds no serious or critical issue in the style sheet', sheetIssues.length === 0, sheetIssues);

    // Escape inside the sheet: the sheet closes; the docked panel (whose own Escape needs focus inside it) stays.
    await presetRadio(sheet, 'concise').focus();
    await page.keyboard.press('Escape');
    const closed = await sheet.waitFor({ state: 'hidden', timeout: 10000 }).then(() => true, () => false);
    check('style: Escape closes the style sheet …', closed);
    check('style: … and only the sheet: the Rafii panel stays open, docked', (await panel(page).isVisible()) && (await panel(page).evaluate((el) => el.tagName)) === 'ASIDE');
    const pillSays = await until(async () => {
      const text = await stylePill(page).textContent();
      return /Concise/.test(text ?? '') ? text : null;
    });
    check('style: the pill now says Concise', Boolean(pillSays), await stylePill(page).textContent().catch(() => null));
    await shot(page, 'style-desktop-6-escape-keeps-panel.png');

    // Account › Preferences (/app/account/profile): the same sheet, from the "Rafii’s style" row.
    await page.goto(`${base}/app/account/profile`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    const prefs = page.getByRole('region', { name: 'Preferences', exact: true });
    await prefs.waitFor({ timeout: 120000 });
    const summary = () => page.locator('#pref-rafii-style').textContent().then((t) => (t ?? '').trim(), () => null);
    const rowText = await until(async () => {
      const text = await summary();
      return text && /Concise/.test(text) ? text : null;
    }, { timeout: 30000 });
    check('style: Account › Preferences has a “Rafii’s style” row with the saved style', (await prefs.getByText('Rafii’s style', { exact: true }).count()) === 1 && rowText === 'Concise · Cedar voice · Match my language', rowText ?? await summary());
    await shot(page, 'style-desktop-7-account-preferences-row.png');
    await prefs.getByRole('button', { name: /^Change Rafii[’']s style$/ }).click();
    const again = styleSheet(page);
    const opened = await again.waitFor({ timeout: 30000 }).then(() => true, () => false);
    check('style: the row opens the same style sheet (its marker, the starting points, Concise marked)',
      opened && (await page.locator('[data-rafii-style-sheet]').count()) === 1 && (await presetRadio(again, 'concise').getAttribute('aria-checked')) === 'true');
    await presetRadio(again, 'explainer').click();
    saved = await pollStyle(who, (s) => matches(s, PRESETS.explainer.fields) && s.voice === 'cedar');
    check('style: a change made from the Account row saves too (Explain in detail, voice kept)', saved.ok, saved.style);
    await shot(page, 'style-desktop-8-account-row-opens-same-sheet.png');
    await again.getByRole('button', { name: 'Done', exact: true }).click();
    await again.waitFor({ state: 'hidden', timeout: 10000 }).catch(() => undefined);
    const rowAfter = await until(async () => {
      const text = await summary();
      return text && /Explain in detail/.test(text) ? text : null;
    });
    check('style: the row’s summary follows the change', rowAfter === 'Explain in detail · Cedar voice · Match my language', rowAfter ?? await summary());

    // A reload: the pill, the row and the API all keep it.
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    await openPanel(page);
    await revealStylePill(page);
    const pillAfter = await until(async () => {
      const text = await stylePill(page).textContent();
      return /Explain in detail/.test(text ?? '') ? text : null;
    }, { timeout: 60000 });
    const rowReloaded = await until(async () => {
      const text = await summary();
      return text && /Explain in detail/.test(text) ? text : null;
    }, { timeout: 30000 });
    const stored = await styleOf(who);
    check('style: after a reload the pill, the Account row and GET /api/me still say Explain in detail with the Cedar voice',
      Boolean(pillAfter) && Boolean(rowReloaded) && matches(stored, PRESETS.explainer.fields) && stored.voice === 'cedar' && stored.chosen === true, { pillAfter, rowReloaded, stored });
    check('style: nothing scrolls sideways', await noSideScroll(page));
    await shot(page, 'style-desktop-9-after-reload.png');
  } finally {
    await ctx.close();
  }
}

async function stylePhoneSection(browser) {
  const who = await seed(base);
  const ctx = await context(browser, who, PHONE, { reducedMotion: 'reduce' });
  try {
    const page = await ctx.newPage();
    await page.goto(`${base}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('style phone: the Rafii drawer opens', await openPanel(page));
    await revealStylePill(page);
    const pill = stylePill(page);
    await pill.waitFor({ timeout: 60000 });
    const label = await until(async () => {
      const text = await pill.textContent();
      return /Friendly/.test(text ?? '') ? text : null;
    }, { timeout: 30000 });
    check('style phone: the header pill keeps its label at phone width', Boolean(label), await pill.textContent().catch(() => null));
    await pill.click();
    const sheet = styleSheet(page);
    await sheet.waitFor({ timeout: 30000 });
    const box = await page.locator('[data-rafii-style-sheet]').boundingBox();
    check('style phone: the style sheet fits the screen width', Boolean(box) && box.x >= 0 && box.x + box.width <= PHONE.width + 1, box);
    const presetsOnScreen = await Promise.all(Object.keys(PRESETS).map(async (id) => {
      const b = await presetRadio(sheet, id).boundingBox();
      return Boolean(b) && b.y >= 0 && b.y + b.height <= PHONE.height && b.x >= 0 && b.x + b.width <= PHONE.width + 1;
    }));
    check('style phone: the three starting points are on screen', presetsOnScreen.every(Boolean), presetsOnScreen);
    check('style phone: nothing scrolls sideways with the sheet open', await noSideScroll(page));
    await shot(page, 'style-phone-1-sheet-over-drawer.png');
    await presetRadio(sheet, 'explainer').click();
    const saved = await pollStyle(who, (s) => s.chosen === true && matches(s, PRESETS.explainer.fields));
    check('style phone: picking Explain in detail saves it (GET /api/me)', saved.ok, saved.style);
    await sheet.getByRole('button', { name: 'More options', exact: true }).click();
    await setting(sheet, 'Language').scrollIntoViewIfNeeded().catch(() => undefined);
    // Every option of every setting sits inside the sheet's width (the grids wrap instead of running off the side).
    const outside = await page.locator('[data-rafii-style-sheet]').evaluate((el) => {
      const frame = el.getBoundingClientRect();
      return [...el.querySelectorAll('[role="radio"]')].map((radio) => ({ text: radio.textContent?.trim(), box: radio.getBoundingClientRect() }))
        .filter(({ box }) => box.width > 0 && (box.left < frame.left - 1 || box.right > frame.right + 1)).map(({ text }) => text);
    });
    check('style phone: More options fits the sheet (no option runs off the side)', outside.length === 0 && (await noSideScroll(page)), outside);
    await shot(page, 'style-phone-2-more-options.png');
    await presetRadio(sheet, 'explainer').focus();
    await page.keyboard.press('Escape');
    const closed = await sheet.waitFor({ state: 'hidden', timeout: 10000 }).then(() => true, () => false);
    check('style phone: Escape closes only the sheet; the Rafii drawer stays', closed && (await panel(page).isVisible()));
    await shot(page, 'style-phone-3-escape-keeps-drawer.png');
  } finally {
    await ctx.close();
  }
}

/* ---------------------------------------------------------------------------------------------------------------------- */
/* slash: the / menu in the panel composer (rafii-commands/command-menu.tsx, mounted in site-agent/chat.tsx)              */
/* ---------------------------------------------------------------------------------------------------------------------- */

async function menuOptions(page) {
  return (await commandMenu(page).getByRole('option').allTextContents()).map((text) => text.trim());
}

async function slashSection(browser) {
  const who = await seed(base);
  const ctx = await context(browser, who, DESKTOP);
  try {
    const page = await ctx.newPage();
    const net = watchNetwork(page);
    await page.goto(`${base}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('slash: the Rafii panel opens', await openPanel(page));
    const input = composer(page);
    const menu = commandMenu(page);

    await input.fill('/');
    const opened = await menu.waitFor({ timeout: 15000 }).then(() => true, () => false);
    const headings = opened ? await menu.getByRole('group').evaluateAll((groups) => groups.map((g) => document.getElementById(g.getAttribute('aria-labelledby') ?? '')?.textContent?.trim() ?? null)) : [];
    check('slash: typing “/” opens the command menu with its group headings', opened && same(headings, COMMAND_GROUPS), { headings, expected: COMMAND_GROUPS });
    const all = opened ? await menuOptions(page) : [];
    check('slash: a bare “/” lists every command', all.length === COMMAND_NAMES.length && COMMAND_NAMES.every((name) => all.some((row) => row.startsWith(`/${name}`))), { shown: all.length, expected: COMMAND_NAMES.length });
    // The menu sets these on the input in an effect after it opens.
    const readWiring = () => input.evaluate((el) => ({ focused: document.activeElement === el, controls: el.getAttribute('aria-controls'), active: el.getAttribute('aria-activedescendant'), autocomplete: el.getAttribute('aria-autocomplete') }));
    const wiring = (await until(async () => {
      const w = await readWiring();
      return w.controls && w.active ? w : null;
    }, { timeout: 5000 })) ?? (await readWiring());
    const listId = await menu.getAttribute('id');
    check('slash: focus stays in the input, which drives the list (aria-controls, aria-activedescendant, aria-autocomplete=list)',
      wiring.focused && wiring.controls === listId && Boolean(wiring.active) && wiring.autocomplete === 'list', { wiring, listId });
    const issues = await axe(page, '#rafii-panel');
    check('slash: axe finds no serious or critical issue in the panel with the menu open', issues.length === 0, issues);
    await shot(page, 'slash-desktop-1-menu-all-commands.png');

    await menu.focus();
    const activeBefore = await menu.getAttribute('aria-activedescendant');
    await menu.press('ArrowDown');
    const keyboardMoved = await until(async () => (await menu.getAttribute('aria-activedescendant')) !== activeBefore);
    check('slash: the scrollable list keeps focus and supports arrow-key navigation', Boolean(keyboardMoved) && (await menu.evaluate((el) => document.activeElement === el)));
    await menu.press('Escape');
    const listEscaped = await menu.waitFor({ state: 'hidden', timeout: 5000 }).then(() => true, () => false);
    check('slash: Escape from the list returns focus to the composer and keeps the panel open', listEscaped && (await input.evaluate((el) => document.activeElement === el)) && (await panel(page).isVisible()));
    await input.fill('');
    await input.fill('/wea');
    const filtered = await until(async () => {
      const rows = await menuOptions(page);
      return rows.length === 1 ? rows : null;
    }, { timeout: 10000 });
    check('slash: “/wea” filters the menu to /weather', Boolean(filtered) && filtered[0].startsWith('/weather'), filtered ?? await menuOptions(page).catch(() => null));
    await shot(page, 'slash-desktop-2-filtered-to-weather.png');
    const turnsBefore = net.turns.length;
    await input.press('Enter');
    // A send would have emptied the input: "/weather " proves Enter picked the command instead.
    const picked = await until(async () => ((await input.inputValue()) === '/weather ' ? true : null), { timeout: 10000 });
    check('slash: Enter picks /weather without sending: the input reads “/weather ”', Boolean(picked) && net.turns.length === turnsBefore, { value: await input.inputValue(), turns: net.turns.length - turnsBefore });
    check('slash: … and the menu closes', await menu.waitFor({ state: 'hidden', timeout: 5000 }).then(() => true, () => false));

    await input.fill('/we');
    await menu.waitFor({ timeout: 10000 });
    await input.press('Escape');
    const escaped = await menu.waitFor({ state: 'hidden', timeout: 5000 }).then(() => true, () => false);
    check('slash: Esc closes the menu, and only the menu (the panel stays open)', escaped && (await panel(page).isVisible()));
    await input.press('a');
    // Timing is what is checked here: the menu must not come back while the same word is being typed.
    const reopened = await menu.waitFor({ state: 'visible', timeout: 1200 }).then(() => true, () => false);
    check('slash: … and stays closed while the same word goes on (“/wea”)', !reopened && (await input.inputValue()) === '/wea', { reopened, value: await input.inputValue() });
    await input.fill('');

    await input.fill('/open channels');
    const beforeOpen = net.turns.length;
    await input.press('Enter');
    const moved = await page.waitForURL(/\/app\/channels(\?|$)/, { timeout: 120000 }).then(() => true, () => false);
    const openNote = await commandNotes(page).getByText('Opening Channels.', { exact: true }).waitFor({ timeout: 15000 }).then(() => true, () => false);
    check('slash: /open channels goes to Channels and says so in the panel', moved && openNote, { url: page.url(), openNote });
    check('slash: … without a turn to Rafii (a client command)', net.turns.length === beforeOpen, net.turns.slice(beforeOpen));
    await shot(page, 'slash-desktop-3-open-channels.png');

    await input.fill('/style concise');
    const beforeStyle = net.turns.length;
    await input.press('Enter');
    const saved = await pollStyle(who, (s) => s.chosen === true && matches(s, PRESETS.concise.fields));
    check('slash: /style concise saves the style (GET /api/me)', saved.ok, saved.style);
    const styleNote = await commandNotes(page).getByText('Style set to Concise.', { exact: true }).waitFor({ timeout: 15000 }).then(() => true, () => false);
    await revealStylePill(page);
    const pillSays = await until(async () => /Concise/.test((await stylePill(page).textContent()) ?? ''));
    check('slash: … says “Style set to Concise.”, the header pill follows, and nothing went to Rafii', styleNote && Boolean(pillSays) && net.turns.length === beforeStyle, { styleNote, pill: await stylePill(page).textContent().catch(() => null) });
    await shot(page, 'slash-desktop-4-style-concise.png');
    await panel(page).getByRole('button', { name: 'More Rafii options' }).click();

    await input.fill('/help');
    await menu.waitFor({ timeout: 10000 }).catch(() => undefined);
    await input.press('Enter');
    const full = await until(async () => {
      const value = await input.inputValue();
      const rows = await menuOptions(page);
      return value === '/' && rows.length === COMMAND_NAMES.length ? rows : null;
    }, { timeout: 10000 });
    check('slash: /help shows the full menu (the input becomes “/”)', Boolean(full), { value: await input.inputValue(), rows: (await menuOptions(page).catch(() => [])).length });
    await shot(page, 'slash-desktop-5-help-full-menu.png');
    await input.press('Escape');
    check('slash: nothing scrolls sideways', await noSideScroll(page));
  } finally {
    await ctx.close();
  }
}

async function slashPhoneSection(browser) {
  const who = await seed(base);
  const ctx = await context(browser, who, PHONE, { reducedMotion: 'reduce' });
  try {
    const page = await ctx.newPage();
    await page.goto(`${base}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('slash phone: the Rafii drawer opens', await openPanel(page));
    const input = composer(page);
    const menu = commandMenu(page);
    await input.fill('/');
    const opened = await menu.waitFor({ timeout: 15000 }).then(() => true, () => false);
    const box = opened ? await menu.boundingBox() : null;
    check('slash phone: “/” opens the menu above the composer, inside the screen', opened && Boolean(box) && box.x >= 0 && box.y >= 0 && box.x + box.width <= PHONE.width + 1, box);
    check('slash phone: nothing scrolls sideways with the menu open', await noSideScroll(page));
    await shot(page, 'slash-phone-1-menu.png');
    await input.fill('/wea');
    const filtered = await until(async () => {
      const rows = await menuOptions(page);
      return rows.length === 1 ? rows : null;
    }, { timeout: 10000 });
    check('slash phone: “/wea” filters to /weather', Boolean(filtered) && filtered[0].startsWith('/weather'), filtered);
    await shot(page, 'slash-phone-2-filtered-to-weather.png');
    await input.press('Enter');
    const picked = await until(async () => ((await input.inputValue()) === '/weather ' ? true : null), { timeout: 10000 });
    check('slash phone: Enter picks it without sending', Boolean(picked), await input.inputValue());
  } finally {
    await ctx.close();
  }
}

/* ---------------------------------------------------------------------------------------------------------------------- */
/* voice: the fake GPT-Live transport (window.rafiiLiveHarness) drives what the person and Rafii say                      */
/* ---------------------------------------------------------------------------------------------------------------------- */

const voiceState = (page) => page.evaluate(() => document.querySelector('#rafii-panel [data-rafii-voice]')?.getAttribute('data-rafii-voice') ?? null);

async function waitVoice(page, states, timeout) {
  return page.waitForFunction((wanted) => {
    const state = document.querySelector('#rafii-panel [data-rafii-voice]')?.getAttribute('data-rafii-voice');
    return wanted.includes(state) ? state : null;
  }, states, { timeout }).then((handle) => handle.jsonValue(), () => null);
}

/**
 * Records, in the page, what the voice checks read: every event sent to "GPT-Live" and every stretch Rafii speaks (with
 * times), and each change of the call's state and status line (a transient "Ending the call…" is never missed).
 */
async function instrument(page) {
  await page.evaluate(() => {
    const harness = window.rafiiLiveHarness;
    const record = { log: [], statuses: [] };
    window.rafiiSceneLog = record;
    const says = harness.rafiiSays;
    // The stand-in speaks commentary through `window.rafiiLiveHarness.rafiiSays`, so this sees every reply.
    harness.rafiiSays = async (text, options) => {
      record.log.push({ kind: 'say', at: Date.now(), text });
      try {
        return await says(text, options);
      } finally {
        record.log.push({ kind: 'said', at: Date.now(), text });
      }
    };
    const push = harness.sent.push.bind(harness.sent);
    harness.sent.push = (...events) => {
      for (const event of events) record.log.push({ kind: 'sent', at: Date.now(), type: event.type, content: String(event.content ?? '').slice(0, 300) });
      return push(...events);
    };
    let last = '';
    const read = () => {
      const state = document.querySelector('#rafii-panel [data-rafii-voice]')?.getAttribute('data-rafii-voice') ?? null;
      const text = document.querySelector('#rafii-panel [data-rafii-voice-status]')?.textContent?.trim() ?? null;
      const indicator = document.querySelector('[data-rafii-voice-indicator]')?.textContent?.trim() ?? null;
      const key = `${state}|${text}|${indicator}`;
      if (key !== last) {
        last = key;
        record.statuses.push({ at: Date.now(), state, text, indicator });
      }
    };
    new MutationObserver(read).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['data-rafii-voice'] });
    read();
  });
}

const liveLog = (page) => page.evaluate(() => window.rafiiSceneLog ?? { log: [], statuses: [] });

/** The mute button's paired foreground and red fill, with the red status dot. */
function muteColours(page) {
  return page.evaluate(() => {
    const box = document.querySelector('#rafii-panel section[data-rafii-voice]');
    const button = box?.querySelector('[data-rafii-voice-mute]');
    const dot = box?.querySelector('[data-rafii-voice-dot]');
    const probe = document.createElement('span');
    probe.style.color = 'var(--destructive-foreground)';
    probe.style.backgroundColor = 'var(--destructive)';
    (box ?? document.body).appendChild(probe);
    const resolved = getComputedStyle(probe);
    const want = { color: resolved.color, background: resolved.backgroundColor };
    probe.remove();
    return {
      want,
      pressed: button?.getAttribute('aria-pressed') ?? null,
      mute: button?.getAttribute('data-rafii-voice-mute') ?? null,
      label: button?.textContent?.trim() ?? null,
      buttonColor: button ? getComputedStyle(button).color : null,
      buttonBackground: button ? getComputedStyle(button).backgroundColor : null,
      dot: dot?.getAttribute('data-rafii-voice-dot') ?? null,
      dotColor: dot ? getComputedStyle(dot).backgroundColor : null,
      status: box?.querySelector('[data-rafii-voice-status]')?.textContent?.trim() ?? null
    };
  });
}

/** The Button has `transition-all`: read the foreground and fill until both settle. */
async function waitRed(page) {
  let state = null;
  const ok = await until(async () => {
    state = await muteColours(page);
    return state.pressed === 'true' && state.buttonColor === state.want.color && state.buttonBackground === state.want.background && state.dotColor === state.want.background;
  }, { timeout: 5000, interval: 100 });
  return { ok: Boolean(ok), state };
}

/**
 * "Talk to Rafii" on a first call: the style picker comes first; choosing a starting point saves it, then the call
 * starts on the stand-in. Returns true when the call is live on the fake transport.
 */
async function firstCall(page, who, net, presetId, label, shotName) {
  const talk = talkButton(page);
  await talk.waitFor({ timeout: 120000 });
  const enabled = await until(() => talk.isEnabled(), { timeout: 60000 });
  check(`${label}: “Talk to Rafii” is offered`, Boolean(enabled));
  await talk.click();
  const picker = firstRunSheet(page);
  const shown = await picker.waitFor({ timeout: 30000 }).then(() => true, () => false);
  check(`${label}: the first call opens the style picker first (“How should Rafii talk to you?”)`, shown);
  if (!shown) return false;
  const group = picker.getByRole('group', { name: 'Starting points', exact: true });
  const counts = await Promise.all(Object.values(PRESETS).map((p) => group.getByRole('button', { name: new RegExp(`^${esc(p.label)}`) }).count()));
  check(`${label}: … offering the three starting points, before any call has started`,
    counts.every((n) => n === 1) && net.voiceStarts.length === 0 && (await voiceState(page)) === 'idle', { counts, voiceStarts: net.voiceStarts.length });
  const box = await page.locator('[data-rafii-style-sheet]').boundingBox();
  const viewport = page.viewportSize();
  check(`${label}: the picker fits the screen`, Boolean(box) && box.x >= 0 && box.x + box.width <= viewport.width + 1, box);
  await shot(page, shotName);
  await group.getByRole('button', { name: new RegExp(`^${esc(PRESETS[presetId].label)}`) }).click();
  const state = await waitVoice(page, ['live', 'error'], 120000);
  const saved = await pollStyle(who, (s) => s.chosen === true && matches(s, PRESETS[presetId].fields));
  check(`${label}: choosing “${PRESETS[presetId].label}” saves it (GET /api/me → preferences.agentStyle, chosen)`, saved.ok, saved.style);
  const patchAt = net.stylePatches.find((p) => p.body?.agentStyle?.preset === presetId)?.at;
  const startAt = net.voiceStarts[0]?.at;
  check(`${label}: … and only then does the call start`, state === 'live' && patchAt !== undefined && startAt !== undefined && patchAt <= startAt,
    { state, patchAt, startAt, status: state === 'error' ? await voiceStatus(page).textContent().catch(() => null) : undefined,
      hint: state === 'error' ? 'a production build (next start) has no fake GPT-Live transport: run the voice sections against next dev' : undefined });
  if (state !== 'live') return false;
  const fake = await page.evaluate(() => Boolean(window.rafiiLiveHarness));
  check(`${label}: the call runs on the scriptable GPT-Live stand-in (development build)`, fake, 'window.rafiiLiveHarness is missing: createTransport returns the fake only when NODE_ENV !== "production" and window.RAFII_FAKE_LIVE === true');
  const session = await until(() => net.voiceStartResponse, { timeout: 5000 });
  check(`${label}: the session came from the QA harness’s GPT-Live stand-in`, String(session?.liveSessionId).startsWith('live_harness_'), session);
  if (!fake) await voiceBox(page).getByRole('button', { name: 'End voice', exact: true }).click().catch(() => undefined);
  return fake;
}

async function voiceSection(browser) {
  const who = await seed(voiceBase);
  if (!(await voiceReady(who, 'voice'))) return;
  const ctx = await context(browser, who, DESKTOP, { fakeLive: true });
  try {
    const page = await ctx.newPage();
    const net = watchNetwork(page);
    await page.goto(`${voiceBase}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('voice: the Rafii panel opens', await openPanel(page));
    if (!(await firstCall(page, who, net, 'explainer', 'voice', 'voice-desktop-1-first-call-style-picker.png'))) return;
    await instrument(page);
    await page.evaluate(() => {
      window.rafiiThinkingSeen = [];
      const scan = () => {
        for (const node of document.querySelectorAll('[data-rafii-thinking-op]')) {
          const value = node.getAttribute('data-rafii-thinking-op');
          if (value && window.rafiiThinkingSeen.at(-1) !== value) window.rafiiThinkingSeen.push(value);
        }
      };
      const observer = new MutationObserver(scan);
      observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-rafii-thinking-op'] });
      window.rafiiThinkingObserver = observer;
      scan();
    });
    const box = voiceBox(page);
    const listening = await until(async () => ((await voiceStatus(page).textContent()) ?? '').trim() === 'Listening', { timeout: 10000 });
    check('voice: the call is live and the status reads Listening', Boolean(listening), await voiceStatus(page).textContent().catch(() => null));
    const readyThinking = await box.locator('[data-rafii-thinking-op]').getAttribute('data-rafii-thinking-op').catch(() => null);
    check('voice ThinkingOps: a live call with no delegated work is the real idle/ready “breathing” state', readyThinking === 'breathing', readyThinking);
    const avatar = await until(async () => {
      const value = await avatarSnapshot(page);
      return value?.ready === 'ready' && value.canvases === 1 ? value : null;
    }, { timeout: 15000, interval: 100 });
    check('voice 3D: exactly one live Rafii canvas is ready; no active speaker uses the idle visual pose',
      Boolean(avatar) && avatar.count === 1 && avatar.surface === 'live' && avatar.mode === 'idle', avatar);
    check('voice 3D: the canonical local GLB loaded with HTTP 200 and no 3D runtime/request failure',
      net.rafii3d.some((entry) => entry.status === 200) && net.rafii3dFailures.length === 0 && net.rafii3dRuntimeErrors.length === 0,
      { responses: net.rafii3d, failures: net.rafii3dFailures, runtime: net.rafii3dRuntimeErrors });
    await shot(page, 'voice-desktop-2-call-live.png');

    // Mute: a pressed "Unmute" in the destructive colour, the status dot too; the microphone really is off.
    const before = await muteColours(page);
    await box.getByRole('button', { name: 'Mute', exact: true }).click();
    const pressed = await box.getByRole('button', { name: 'Unmute', exact: true, pressed: true }).waitFor({ timeout: 10000 }).then(() => true, () => false);
    const red = await waitRed(page);
    check('voice: Mute becomes a pressed “Unmute” (aria-pressed=true, data-rafii-voice-mute=on)', pressed && red.state?.mute === 'on', red.state);
    check('voice: … the button fill and status dot turn red, with the button’s paired foreground for contrast',
      red.ok && before.buttonBackground !== red.state.want.background && before.dot === 'live', { before, after: red.state });
    const micOff = await page.evaluate(() => window.rafiiLiveHarness.micEnabled() === false);
    check('voice: … the status says Microphone off and the microphone is off', (red.state?.status ?? '').startsWith('Microphone off') && micOff, { status: red.state?.status, micOff });
    const issues = await axe(page, '#rafii-panel');
    check('voice: axe finds no serious or critical issue in the panel with a muted call', issues.length === 0, issues);
    await shot(page, 'voice-desktop-3-muted-red.png');

    // The panel closed: the call indicator says "Microphone off", its icon in the destructive colour.
    await panel(page).getByRole('button', { name: 'Close Rafii', exact: true }).click();
    await panel(page).waitFor({ state: 'hidden', timeout: 10000 }).catch(() => undefined);
    const indicator = callIndicator(page);
    const shownIndicator = await indicator.waitFor({ timeout: 10000 }).then(() => true, () => false);
    const said = shownIndicator ? (await indicator.innerText()).replace(/\s+/g, ' ').trim() : null;
    const icon = shownIndicator ? await indicator.evaluate((el) => {
      const svg = el.querySelector('svg');
      const probe = document.createElement('span');
      probe.style.color = 'var(--destructive)';
      el.appendChild(probe);
      const want = getComputedStyle(probe).color;
      probe.remove();
      return { color: svg ? getComputedStyle(svg).color : null, want, className: svg?.getAttribute('class') ?? null };
    }) : null;
    check('voice: with the panel closed, the call indicator reads “Microphone off”', /Microphone off/.test(said ?? ''), said);
    check('voice: … with the microphone icon in the destructive colour', Boolean(icon) && icon.color === icon.want, icon);
    await shot(page, 'voice-desktop-4-panel-closed-microphone-off.png');
    await indicator.getByRole('button', { name: /Open Rafii/ }).click();
    await panel(page).waitFor({ state: 'visible', timeout: 15000 });
    check('voice: the indicator opens Rafii again, the call still live and muted',
      (await voiceState(page)) === 'live' && (await box.getByRole('button', { name: 'Unmute', exact: true }).count()) === 1);
    await box.getByRole('button', { name: 'Unmute', exact: true }).click();
    const unmuted = await until(async () => (await box.getByRole('button', { name: 'Mute', exact: true, pressed: false }).count()) === 1
      && (await page.evaluate(() => window.rafiiLiveHarness.micEnabled())));
    check('voice: Unmute turns the microphone back on', Boolean(unmuted));

    // Stop talking: GPT-Live (and the stand-in) can't cancel a reply, so the rest of it keeps streaming; none of it may show.
    const LONG = 'Here is a long answer about your week, one detail after another, slowly and carefully, so there is time to stop it before the end, and this closing sentence must never reach the transcript.';
    const rafiiLines = () => page.evaluate(() => [...document.querySelectorAll('#rafii-panel [data-rafii-voice-transcript] li[data-role="assistant"]')].map((li) => li.textContent ?? ''));
    await page.evaluate((text) => {
      window.rafiiSceneLongReply = 'running';
      void window.rafiiLiveHarness.rafiiSays(text, { chunkMs: 60 }).then(() => {
        window.rafiiSceneLongReply = 'done';
      });
    }, LONG);
    await page.waitForFunction(() => {
      const li = [...document.querySelectorAll('#rafii-panel [data-rafii-voice-transcript] li[data-role="assistant"]')].at(-1);
      return window.rafiiLiveHarness.speaking() && li && (li.textContent ?? '').trim().split(/\s+/).length >= 6;
    }, null, { timeout: 15000 });
    const speakingStatus = (await voiceStatus(page).textContent()) ?? '';
    const speakingAvatar = await until(async () => {
      const value = await avatarSnapshot(page);
      return value?.mode === 'speaking' && value.mouth > 0.02 ? value : null;
    }, { timeout: 5000, interval: 40 });
    check('voice 3D: real outgoing fake-WebRTC level drives Speaking mode and a non-zero mouth shape', Boolean(speakingAvatar), speakingAvatar);
    const linesBefore = (await rafiiLines()).length;
    await box.getByRole('button', { name: 'Stop talking', exact: true }).click();
    const interruptedAvatar = await until(async () => {
      const value = await avatarSnapshot(page);
      return value?.mode === 'interrupted' && value.mouth === 0 ? value : null;
    }, { timeout: 1200, interval: 20 });
    check('voice 3D: Stop talking immediately switches to Interrupted and closes the mouth', Boolean(interruptedAvatar), interruptedAvatar);
    await page.waitForFunction(() => document.querySelector('#rafii-panel [data-rafii-voice-transcript] li[data-role="assistant"][data-stopped]'), null, { timeout: 5000 }).catch(() => undefined);
    const stoppedLine = () => page.evaluate(() => [...document.querySelectorAll('#rafii-panel [data-rafii-voice-transcript] li[data-role="assistant"][data-stopped]')].at(-1)?.textContent ?? null);
    const cut = await stoppedLine();
    // The stand-in streams the rest of the reply regardless; wait for it to have finished.
    await page.waitForFunction(() => window.rafiiSceneLongReply === 'done', null, { timeout: 30000 });
    const after = await stoppedLine();
    const linesAfter = await rafiiLines();
    const stopLog = await liveLog(page);
    check('voice: Rafii was speaking when Stop talking was pressed', /Rafii is speaking/.test(speakingStatus), speakingStatus);
    check('voice: Stop talking marks the cut-off reply “(stopped)”', /\(stopped\)\s*$/.test(after ?? ''), after);
    // The list shows the last six lines, so "nothing new" is read from the last line as well as the count.
    check('voice: … and no more of that reply appears, although it kept streaming',
      cut !== null && after === cut && linesAfter.at(-1) === after && linesAfter.length === linesBefore && !linesAfter.some((line) => /never reach the transcript/.test(line)),
      { cut, after, last: linesAfter.at(-1), linesBefore, linesAfter: linesAfter.length });
    const listeningAgain = await until(async () => ((await voiceStatus(page).textContent()) ?? '').trim() === 'Listening', { timeout: 5000 });
    check('voice: … its audio stays off, Live is told to listen, and the status is back to Listening',
      (await page.evaluate(() => window.rafiiLiveHarness.outputMuted())) && stopLog.log.some((e) => e.kind === 'sent' && e.type === 'session.instructions.append' && /Stop speaking now/.test(e.content)) && Boolean(listeningAgain));
    await shot(page, 'voice-desktop-5-stop-talking.png');

    // "That's all" alone is not a goodbye: it goes to Rafii as a request, and the call stays on.
    const commentaryBefore = (await liveLog(page)).log.filter((e) => e.kind === 'sent' && e.type === 'session.commentary.append').length;
    const thatsAllAt = await page.evaluate(() => Date.now());
    await page.evaluate(() => window.rafiiLiveHarness.userSays("That's all"));
    const answered = await page.waitForFunction((n) => (window.rafiiSceneLog?.log ?? []).filter((e) => e.kind === 'sent' && e.type === 'session.commentary.append').length > n, commentaryBefore, { timeout: 180000 }).then(() => true, () => false);
    await page.waitForFunction(() => {
      const log = window.rafiiSceneLog?.log ?? [];
      const lastSay = log.toReversed().find((e) => e.kind === 'say');
      return Boolean(lastSay) && log.some((e) => e.kind === 'said' && e.at >= lastSay.at && e.text === lastSay.text);
    }, null, { timeout: 30000 }).catch(() => undefined);
    // Timing is what is checked: longer than the 1.2 s of quiet after which a goodbye would hang up.
    const hungUp = await page.waitForFunction(() => document.querySelector('#rafii-panel [data-rafii-voice]')?.getAttribute('data-rafii-voice') !== 'live', null, { timeout: 3000 }).then(() => true, () => false);
    const thatsAll = await liveLog(page);
    const working = thatsAll.log.filter((e) => e.kind === 'sent' && e.type === 'session.thinking.append' && /^Working on: That's all\b/.test(e.content));
    check('voice: “that’s all” alone goes to Rafii as a request (not a panel command) and is answered', answered && working.length === 1, { answered, working });
    const thinkingSeen = await page.evaluate(() => window.rafiiThinkingSeen ?? []);
    check('voice ThinkingOps: real speech and delegation drive listening plus backend work states (not a timed demo)',
      thinkingSeen.includes('breathing') && thinkingSeen.includes('listening') && thinkingSeen.some((op) => ['working', 'solving', 'searching', 'weaving'].includes(op)),
      thinkingSeen);
    check('voice: … and does not hang up: no “Ending the call…”, still live 3 s after the reply',
      !hungUp && !thatsAll.statuses.some((s) => s.at >= thatsAllAt && /Ending the call/.test(s.text ?? '')), { hungUp, statuses: thatsAll.statuses.filter((s) => s.at >= thatsAllAt) });
    await shot(page, 'voice-desktop-6-thats-all-keeps-call.png');

    // A goodbye: "Ending the call…", one short goodbye, then the call ends ~1.2 s after the reply goes quiet (10 s at most).
    const goodbyeAt = await page.evaluate(() => Date.now());
    const turnsBeforeGoodbye = net.turns.length;
    await page.evaluate(() => window.rafiiLiveHarness.userSays('Goodbye'));
    const ending = await page.waitForFunction(() => /Ending the call/.test(document.querySelector('#rafii-panel [data-rafii-voice-status]')?.textContent ?? ''), null, { timeout: 10000, polling: 'raf' }).then(() => true, () => false);
    if (ending) await shot(page, 'voice-desktop-7-ending-the-call.png');
    const endedState = await waitVoice(page, ['ended', 'error', 'idle'], 20000);
    const bye = await liveLog(page);
    const byeSaid = bye.log.filter((e) => e.kind === 'said' && e.at >= goodbyeAt && /Bye for now/.test(e.text)).at(-1);
    const closeSent = bye.log.find((e) => e.kind === 'sent' && e.type === 'session.close' && e.at >= goodbyeAt);
    check('voice: a goodbye shows “Ending the call…”', ending || bye.statuses.some((s) => s.at >= goodbyeAt && /Ending the call/.test(s.text ?? '')), bye.statuses.filter((s) => s.at >= goodbyeAt));
    check('voice: … Rafii says one short goodbye (“Bye for now; I’m ending the call.”), handled in the browser without a turn to Rafii',
      Boolean(byeSaid) && net.turns.length === turnsBeforeGoodbye, { byeSaid, turns: net.turns.slice(turnsBeforeGoodbye) });
    check('voice: … then the call ends by itself (session.close sent, the panel says the call ended)', endedState === 'ended' && Boolean(closeSent), { endedState, closeSent });
    const quietMs = closeSent && byeSaid ? closeSent.at - byeSaid.at : null;
    const sinceGoodbyeMs = closeSent ? closeSent.at - goodbyeAt : null;
    check('voice: … about 1.2 s after the reply went quiet, and within 10 s of the goodbye', quietMs !== null && quietMs >= 1000 && sinceGoodbyeMs <= 10500, { quietMs, sinceGoodbyeMs });
    const told = await until(() => net.voiceEnds.some((e) => e.body?.reason === 'close_requested'), { timeout: 10000 });
    check('voice: … and the server is told the session ended', Boolean(told), net.voiceEnds);
    await shot(page, 'voice-desktop-8-call-ended.png');
    await box.getByRole('button', { name: 'Close', exact: true }).click();
    const idle = await waitVoice(page, ['idle'], 10000);
    check('voice: Close returns the panel to its idle state, with “Talk to Rafii” again', idle === 'idle' && (await talkButton(page).isVisible()), idle);
    check('voice: nothing scrolls sideways', await noSideScroll(page));
    await shot(page, 'voice-desktop-9-back-to-idle.png');
  } finally {
    await ctx.close();
  }
}

async function voicePhoneSection(browser) {
  const who = await seed(voiceBase);
  if (!(await voiceReady(who, 'voice phone'))) return;
  const ctx = await context(browser, who, PHONE, { fakeLive: true, reducedMotion: 'reduce' });
  try {
    const page = await ctx.newPage();
    const net = watchNetwork(page);
    await page.goto(`${voiceBase}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('voice phone: the Rafii drawer opens', await openPanel(page));
    if (!(await firstCall(page, who, net, 'friendly', 'voice phone', 'voice-phone-1-first-call-style-picker.png'))) return;
    const box = voiceBox(page);
    const controls = {};
    for (const name of ['Mute', 'Stop talking', 'End voice']) controls[name] = await box.getByRole('button', { name, exact: true }).boundingBox();
    check('voice phone: Mute, Stop talking and End voice are on screen',
      Object.values(controls).every((b) => b && b.x >= 0 && b.y >= 0 && b.x + b.width <= PHONE.width + 1 && b.y + b.height <= PHONE.height + 1), controls);
    check('voice phone: reduced motion drops the level meter; the status stays',
      (await page.locator('[data-rafii-voice-level]').count()) === 0 && Boolean(await until(async () => /Listening/.test((await voiceStatus(page).textContent()) ?? ''), { timeout: 10000 })));
    const mobileAvatar = await until(async () => {
      const value = await avatarSnapshot(page);
      return value?.ready === 'ready' && value.canvases === 1 ? value : null;
    }, { timeout: 15000, interval: 100 });
    check('voice phone 3D: the model is ready in the idle visual pose and reduced motion disables continuous character motion',
      Boolean(mobileAvatar) && mobileAvatar.surface === 'live' && mobileAvatar.mode === 'idle' && mobileAvatar.continuous === 'off', mobileAvatar);
    check('voice phone 3D: the stage fits the 390px viewport without clipping sideways',
      Boolean(mobileAvatar) && mobileAvatar.rect.x >= -1 && mobileAvatar.rect.x + mobileAvatar.rect.width <= PHONE.width + 1, mobileAvatar?.rect);
    check('voice phone: nothing scrolls sideways', await noSideScroll(page));
    await shot(page, 'voice-phone-2-call-live.png');
    await box.getByRole('button', { name: 'Mute', exact: true }).click();
    const red = await waitRed(page);
    check('voice phone: Mute turns pressed and red here too', red.ok, red.state);
    await shot(page, 'voice-phone-3-muted-red.png');
    await box.getByRole('button', { name: 'End voice', exact: true }).click();
    const ended = await waitVoice(page, ['ended', 'error'], 30000);
    check('voice phone: End voice ends the call', ended === 'ended', ended);
  } finally {
    await ctx.close();
  }

  // A separate uncached context deliberately blocks the GLB. Voice remains live and usable on the existing 2D Rafii.
  const fallbackCtx = await context(browser, who, PHONE, { fakeLive: true, reducedMotion: 'reduce' });
  try {
    await fallbackCtx.route('**/raffi/raffi-live-v1.glb', (route) => route.abort('failed'));
    const page = await fallbackCtx.newPage();
    watchNetwork(page);
    await page.goto(`${voiceBase}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('voice phone fallback: the Rafii drawer opens', await openPanel(page));
    const talk = talkButton(page);
    await talk.waitFor({ timeout: 120000 });
    await until(() => talk.isEnabled(), { timeout: 60000 });
    await talk.click();
    const live = await waitVoice(page, ['live', 'error'], 120000);
    const fallbackAvatar = await until(async () => {
      const value = await avatarSnapshot(page);
      return value?.ready === 'fallback' && value.surface === 'fallback' ? value : null;
    }, { timeout: 15000, interval: 100 });
    const fallbackControls = live === 'live'
      ? await Promise.all(['Mute', 'Stop talking', 'End voice'].map((name) => voiceBox(page).getByRole('button', { name, exact: true }).isEnabled()))
      : [];
    check('voice phone fallback: blocking the GLB degrades to the static Rafii without breaking the live call or controls',
      live === 'live' && Boolean(fallbackAvatar) && fallbackControls.every(Boolean), { live, avatar: fallbackAvatar, controls: fallbackControls });
    if (live === 'live') await voiceBox(page).getByRole('button', { name: 'End voice', exact: true }).click();
  } finally {
    await fallbackCtx.close();
  }
}

/* ---------------------------------------------------------------------------------------------------------------------- */
/* weather: /weather Hong Kong, answered without a model (agent_runtime_v2/commands.py `direct`)                          */
/* ---------------------------------------------------------------------------------------------------------------------- */

async function weatherSection(browser) {
  const who = await seed(voiceBase);
  const budget = approveBudget(who.workspaceId);
  const probe = budget.ok ? await qaHarness(who) : { ok: false, error: budget.error };
  check('weather: the API is the agent QA harness (its GPT-Live stand-in answered), so /weather uses the Open-Meteo stand-in', probe.ok, probe);
  if (!probe.ok) {
    process.stdout.write('SKIP weather: /weather is not sent to a harness that could reach the real Open-Meteo\n');
    return;
  }
  const ctx = await context(browser, who, DESKTOP);
  try {
    const page = await ctx.newPage();
    await page.goto(`${voiceBase}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 400000 });
    await ready(page);
    check('weather: the Rafii panel opens', await openPanel(page));
    // The Live entry appears from the same agent status as typed agent commands.
    const agentOn = await panel(page).getByRole('button', { name: 'Open Rafii Live' }).first().waitFor({ timeout: 60000 }).then(() => true, () => false);
    check('weather: the panel talks to the agent runtime here', agentOn);
    const turn = page.waitForResponse((r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/agent/turns'), { timeout: 120000 });
    await composer(page).fill('/weather Hong Kong');
    await composer(page).press('Enter');
    const response = await turn.catch(() => null);
    const sent = response ? json(response.request().postData()) : null;
    const body = response ? await response.json().catch(() => null) : null;
    check('weather: /weather Hong Kong goes to Rafii as typed, with command { name: "weather", args: "Hong Kong" }',
      sent?.message === '/weather Hong Kong' && sent?.command?.name === 'weather' && sent?.command?.args === 'Hong Kong', sent);
    check('weather: … and is answered without a model (composedBy: deterministic)', body?.result?.composedBy === 'deterministic', body?.result ? { composedBy: body.result.composedBy, answer: body.result.answerText } : body);
    const text = await until(async () => {
      const t = await answers(page).last().innerText();
      return /Open-Meteo/.test(t) ? t : null;
    }, { timeout: 60000 });
    check('weather: the panel shows the direct answer: place, temperature, conditions, today’s range, rain chance and source (the stand-in’s data)',
      Boolean(text) && /Hong Kong, Harness/.test(text) && /26°C/.test(text) && /partly cloudy/.test(text) && /24°C to 28°C/.test(text) && /20% chance of rain/.test(text) && /Source: Open-Meteo/.test(text),
      text ?? await answers(page).last().innerText().catch(() => null));
    await shot(page, 'weather-desktop-hong-kong.png');
  } finally {
    await ctx.close();
  }
}

/* ---------------------------------------------------------------------------------------------------------------------- */

const RUN = { style: styleSection, 'style-phone': stylePhoneSection, slash: slashSection, 'slash-phone': slashPhoneSection, voice: voiceSection, 'voice-phone': voicePhoneSection, weather: weatherSection };
const report = (extra = {}) => fs.writeFileSync(path.join(out, 'rafii-live-agent-browser.json'),
  JSON.stringify({ base, voiceBase, engine: args.browser || 'chromium', principal: 'synthetic', sections: asked, results, ...extra }, null, 1));

(async () => {
  const executablePath = (args.browser === 'webkit' ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  try {
    for (const name of SECTIONS) {
      if (!want(name)) continue;
      process.stdout.write(`\n— ${name}\n`);
      try {
        await RUN[name](browser);
      } catch (error) {
        // One section stopping (a timeout, a crash) is recorded and the next section still runs.
        check(`${name}: the section ran to the end`, false, String(error?.stack ?? error).slice(0, 800));
      }
    }
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok);
  report();
  process.stdout.write(`\n${results.length - failed.length}/${results.length} checks passed\n`);
  process.exit(failed.length || !results.length ? 1 : 0);
})().catch((error) => {
  process.stderr.write(`${String(error?.stack ?? error)}\n`);
  report({ stoppedBy: String(error?.message || error).slice(0, 300) });
  process.exit(1);
});
