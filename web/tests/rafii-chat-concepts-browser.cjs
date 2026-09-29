/** Mobile Agent Chat concept checks against the disposable agent harness and development fake Live transport. */
const { chromium, webkit } = require('playwright');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:3190';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local harness only');
const browserName = process.argv.includes('--browser=webkit') ? 'webkit' : 'chromium';
const engine = browserName === 'webkit' ? webkit : chromium;
const port = Number(process.env.RAFII_VOICE_PG_PORT || 0);
if (!port) throw new Error('Set RAFII_VOICE_PG_PORT to the disposable PostgreSQL port');
const out = path.resolve(process.argv.find((arg) => arg.startsWith('--out='))?.slice(6) || '.');
fs.mkdirSync(out, { recursive: true });
const root = path.resolve(__dirname, '../..');
const tourIds = [...fs.readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((match) => match[1]);
const tours = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(tourIds.map((id) => [id, 1])), nudged: Object.fromEntries(tourIds.map((id) => [id, 1])) });
const principal = randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: ok ? undefined : detail });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ` — ${JSON.stringify(detail).slice(0, 300)}`}`);
}
async function call(method, route, body) {
  const response = await fetch(base + route, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const value = await response.text();
  if (!response.ok) throw new Error(`${method} ${route}: ${response.status} ${value.slice(0, 200)}`);
  return value ? JSON.parse(value) : null;
}
async function main() {
  const { workspaceId } = await call('POST', '/api/auth/verify', {});
  const code = `import psycopg\nfrom consumer_fixtures import approve_budgets\napprove_budgets(lambda: psycopg.connect("host=127.0.0.1 port=${port} dbname=postgres"), ${JSON.stringify(workspaceId)})`;
  execFileSync(process.env.RAFII_PYTHON || 'python3', ['-c', code], { cwd: root, env: { ...process.env, PYTHONPATH: 'src:tests' }, stdio: 'pipe' });
  const status = await call('GET', `/api/workspaces/${workspaceId}/agent/status`);
  check('synthetic harness offers Live voice', Boolean(status.voice?.available && status.flags?.RAFII_VOICE_ENABLED && status.flags?.RAFII_AGENT_V2_ENABLED), status);
  if (!results.at(-1).ok) throw new Error('Synthetic Live unavailable');
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, colorScheme: 'dark', isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
    await context.addCookies([
      { name: 'postriff_dev', value: '1', url: base },
      { name: 'postriff_dev_principal', value: principal, url: base },
      { name: 'postriff_theme', value: 'rafii', url: base }
    ]);
    await context.addInitScript(({ id, tours }) => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('postriff-onboarding', tours);
      window.RAFII_FAKE_LIVE = true;
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style');
        style.textContent = '.tsqd-parent-container,nextjs-portal{display:none!important}';
        document.head.appendChild(style);
      });
    }, { id: principal, tours });
    const page = await context.newPage();
    await page.goto(`${base}/app/calendar`, { waitUntil: 'domcontentloaded', timeout: 240000 });
    const launcher = page.locator('#rafii-launcher');
    await launcher.waitFor({ timeout: 240000 });
    await page.waitForFunction(() => !document.querySelector('#rafii-launcher')?.disabled, null, { timeout: 240000 });
    await launcher.click();
    const panel = page.locator('#rafii-panel');
    await panel.waitFor({ timeout: 30000 });
    await panel.getByRole('button', { name: 'Open Rafii Live' }).first().waitFor({ timeout: 30000 });
    await page.screenshot({ path: path.join(out, 'rafii-chat-home-live-enabled-mobile.png') });
    await panel.getByRole('button', { name: 'Open Rafii Live' }).first().click();
    const stage = panel.getByRole('region', { name: 'Rafii Live' });
    await stage.waitFor();
    check('Live begins as a distinct, full-height screen with current context', /Current context: Calendar/.test(await stage.innerText()) && (await panel.getByRole('button', { name: 'Back to chat' }).count()) === 1);
    await stage.locator('[data-rafii-model-ready="ready"], [data-rafii-model-ready="fallback"]').waitFor({ timeout: 15000 });
    check('the supplied Meshy raccoon loads as the Live 3D model', browserName === 'webkit'
      ? (await stage.locator('[data-rafii-model-ready="ready"], [data-rafii-model-ready="fallback"]').count()) === 1
      : (await stage.locator('[data-rafii-model-ready="ready"]').count()) === 1);
    if ((await stage.locator('[data-rafii-model-ready="ready"]').count()) === 1) {
      await stage.locator('[data-rafii-3d]').screenshot({ path: path.join(out, 'rafii-meshy-stage.png'), omitBackground: true });
    }
    await page.screenshot({ path: path.join(out, 'rafii-live-ready-mobile.png') });
    await stage.getByRole('button', { name: 'Start live conversation' }).click();
    const picker = page.getByRole('dialog', { name: 'How should Rafii talk to you?' });
    await picker.waitFor({ timeout: 30000 });
    check('first Live call asks for a style before starting', (await picker.getByRole('group', { name: 'Starting points' }).getByRole('button').count()) === 3);
    await picker.getByRole('group', { name: 'Starting points' }).getByRole('button', { name: /^Friendly/ }).click();
    await panel.locator('[data-rafii-voice="live"]').waitFor({ timeout: 120000 });
    const fake = await page.evaluate(() => Boolean(window.rafiiLiveHarness));
    check('Live uses the scriptable local transport', fake);
    const listening = await stage.getByRole('status').first().innerText();
    check('Live reports listening', /Listening/.test(listening), listening);
    await page.screenshot({ path: path.join(out, 'rafii-live-listening-mobile.png') });
    await page.evaluate(() => {
      window.rafiiConceptSpeech = 'running';
      void window.rafiiLiveHarness.rafiiSays('Here is a long answer about the calendar and what can be done next, with enough words to show the speaking state in the Live stage.', { chunkMs: 90 }).then(() => { window.rafiiConceptSpeech = 'done'; });
    });
    await stage.getByRole('status').first().getByText('Rafii is speaking').waitFor({ timeout: 15000 });
    check('Live reports speaking from output events', (await stage.locator('[data-rafii-avatar-slot]').count()) === 1);
    await page.screenshot({ path: path.join(out, 'rafii-live-speaking-mobile.png') });
    await stage.getByRole('button', { name: 'Stop Rafii speaking' }).click();
    await page.waitForFunction(() => document.querySelector('#rafii-panel [data-rafii-voice-transcript] li[data-stopped]'), null, { timeout: 15000 });
    check('Stop speaking marks the transcript as interrupted', (await stage.locator('[data-rafii-voice-transcript] li[data-stopped]').count()) > 0);
    await stage.getByText('Live options').click();
    await stage.getByRole('button', { name: 'Mute', exact: true }).click();
    check('Mute is visibly pressed and the microphone is off', (await stage.locator('[data-rafii-voice-mute="on"]').count()) === 1 && /Microphone off/.test(await stage.getByRole('status').first().innerText()));
    await stage.getByRole('button', { name: 'Return to keyboard' }).click();
    check('keyboard fallback returns to a usable composer', (await panel.getByLabel('Ask Rafii', { exact: true }).isVisible()));
    await panel.getByRole('button', { name: 'Open Rafii Live' }).first().click();
    check('Live call remains connected across mode changes', (await stage.getAttribute('data-rafii-voice')) === 'live');
    await stage.getByRole('button', { name: 'End live conversation' }).click();
    await page.waitForFunction(() => ['ended', 'idle'].includes(document.querySelector('#rafii-panel [data-rafii-live-state]')?.getAttribute('data-rafii-live-state')), null, { timeout: 30000 });
    check('End live conversation closes the session', true);
    await context.close();
  } finally {
    await browser.close();
  }
}
main().catch((error) => { results.push({ name: 'run', ok: false, detail: String(error.stack || error) }); console.error(error); }).finally(() => {
  fs.writeFileSync(path.join(out, 'rafii-chat-concepts-browser.json'), JSON.stringify({ base, results }, null, 2));
  console.log(`${results.filter((result) => result.ok).length}/${results.length} checks passed`);
  if (results.some((result) => !result.ok)) process.exitCode = 1;
});
