/**
 * Runs the lane G browser scenes (scenes.cjs) against the acceptance stack and writes evidence.
 *
 *   node web/tests/agent-ui-e2e/run.cjs --browser=chromium|webkit [--only=id,id] [--out=$AGENT_UI_EVIDENCE_DIR]
 *
 * Env: RAFII_WEB_URL (the web build, loopback only), AGENT_UI_PROVIDER_URL (fixture provider base, no /v1),
 *      AGENT_UI_STACK_STATE (stack.json, for the setup-only fixture CLI), RAFII_TEST_PYTHON (default python).
 * Output: <out>/e2e-<browser>.json  {browser, version, emulation: true, items: [{check: "e2e:<id>", status, detail, metrics, diagnostics?}]}
 *         <out>/e2e-<browser>-<scene>-<n>.png for every page of a scene that did not pass.
 * Exit code: 1 when any scene fails; blocked scenes are reported (strict runs turn them into failures in the shell script).
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { SCENES, Blocked } = require('./scenes.cjs');

const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));
const base = (process.env.RAFII_WEB_URL || 'http://127.0.0.1:4539').replace(/\/$/, '');
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('The lane G scenes run against the local acceptance stack only.');
const providerBase = (process.env.AGENT_UI_PROVIDER_URL || '').replace(/\/v1\/?$/, '').replace(/\/$/, '') || null;
const browserName = args.browser === 'webkit' ? 'webkit' : 'chromium';
const out = path.resolve(String(args.out || process.env.AGENT_UI_EVIDENCE_DIR || '.'));
const only = args.only ? String(args.only).split(',') : null;
// Onboarding tours dismissed exactly as the existing scenes do (site-agent-browser.cjs), so no tour overlays the panel.
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
const VIEWPORTS = [
  { id: 'desktop-1440', width: 1440, height: 900, surface: 'panel' },
  { id: 'panel-360', width: 1440, height: 900, surface: 'panel' },
  { id: 'tablet-768', width: 768, height: 1024, surface: 'panel' },
  { id: 'mobile-390-portrait', width: 390, height: 844, surface: 'mobile' },
  { id: 'mobile-390-landscape', width: 844, height: 390, surface: 'mobile' },
];
const AGENT_PATH = /\/api\/workspaces\/[0-9a-f-]{36}\/agent\/(turns|status|ui\/.*|conversations\/.*|runs\/.*)$/;
const shortPath = (url) => new URL(url).pathname.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, ':id');

async function main() {
  const playwright = require('playwright');
  const engine = playwright[browserName];
  const browser = await engine.launch({ headless: true });
  const version = browser.version();
  const items = [];
  const shared = {};
  for (const { id, run } of SCENES) {
    if (only && !only.includes(id)) continue;
    const principal = randomUUID();
    const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };
    const boot = await fetch(`${base}/api/auth/verify`, { method: 'POST', headers, body: '{}' }).then((r) => r.json()).catch(() => ({}));
    const contexts = [];
    const pages = [];
    const metrics = {};
    const failures = [];
    const consoleLines = [];
    const agentCalls = [];
    const t = {
      base, providerBase, viewports: VIEWPORTS, workspaceId: boot.workspaceId, principal, shared,
      async page({ surface = 'panel', viewport, locale = 'en-US', reducedMotion = 'no-preference', mobile } = {}) {
        const vp = viewport || (surface === 'mobile' ? { width: 390, height: 844 } : { width: 1440, height: 900 });
        const isMobile = mobile ?? vp.width < 768;
        const ctx = await browser.newContext({ viewport: vp, locale, reducedMotion, colorScheme: 'dark', deviceScaleFactor: 1,
                                               ...(browserName === 'chromium' ? { isMobile, hasTouch: isMobile } : { hasTouch: isMobile }) });
        contexts.push(ctx);
        await ctx.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
        await ctx.addInitScript(({ id, tours }) => {
          localStorage.setItem('postriff-dev-principal', id);
          localStorage.setItem('postriff-onboarding', tours);
        }, { id: principal, tours: TOURS });
        const page = await ctx.newPage();
        pages.push(page);
        const opened = Date.now();
        // Diagnostics (kept only for scenes that don't pass): console errors/warnings and every agent API call's status and timing.
        page.on('console', (m) => { if (['error', 'warning'].includes(m.type()) && consoleLines.length < 40) consoleLines.push(`${m.type()}: ${m.text().slice(0, 240)}`); });
        page.on('pageerror', (e) => { if (consoleLines.length < 40) consoleLines.push(`pageerror: ${String(e.message).slice(0, 240)}`); });
        page.on('requestfinished', async (r) => {
          if (!AGENT_PATH.test(new URL(r.url()).pathname) || agentCalls.length >= 80) return;
          const res = await r.response().catch(() => null);
          agentCalls.push({ t: Date.now() - opened, method: r.method(), path: shortPath(r.url()), status: res ? res.status() : null });
        });
        page.on('requestfailed', (r) => {
          if (AGENT_PATH.test(new URL(r.url()).pathname) && agentCalls.length < 80) agentCalls.push({ t: Date.now() - opened, method: r.method(), path: shortPath(r.url()), failed: r.failure()?.errorText });
        });
        return page;
      },
      assert(ok, what, detail) {
        if (!ok) failures.push({ what, detail: detail === undefined ? undefined : JSON.stringify(detail).slice(0, 400) });
      },
      metric(name, value) { metrics[name] = typeof value === 'number' ? Math.round(value * 10) / 10 : value; },
      /** A second workspace for this principal: another owner's workspace (real sign-up through the API) plus a membership row
       *  written by the setup-only fixture CLI on the disposable DB (the trial plan's member slots would refuse an invitation). */
      async joinSecondWorkspace(role = 'editor') {
        const other = randomUUID();
        const res = await fetch(`${base}/api/auth/verify`, { method: 'POST', headers: { ...headers, Authorization: `Bearer dev:${other}` }, body: '{}' });
        const second = await res.json().catch(() => ({}));
        if (!res.ok || !second.workspaceId) throw new Error(`auth/verify for the second owner → ${res.status}`);
        execFileSync(process.env.RAFII_TEST_PYTHON || 'python', ['-m', 'agent_ui_acceptance.fixture_cli', 'add-member', second.workspaceId, principal, role],
                     { env: process.env, stdio: ['ignore', 'pipe', 'pipe'], timeout: 30000 });
        return { workspaceId: second.workspaceId };
      },
    };
    const started = Date.now();
    let status = 'pass';
    let detail = '';
    let diagnostics;
    try {
      detail = String((await run(t)) || 'ok');
      if (failures.length) { status = 'fail'; detail = failures.map((f) => `${f.what}${f.detail ? ` — ${f.detail}` : ''}`).join(' | '); }
    } catch (error) {
      if (error instanceof Blocked) { status = 'blocked'; detail = `BLOCKED ${error.message}`; }
      else { status = 'fail'; detail = `${error.name}: ${String(error.message).split('\n')[0].slice(0, 300)}`; }
    } finally {
      if (status !== 'pass') {
        const hosts = [];
        const shots = [];
        for (const [n, page] of pages.entries()) {
          if (page.isClosed()) continue;
          hosts.push(...await page.evaluate(() => [...document.querySelectorAll('[data-rafii-generated-host], [data-rafii-generated]')].slice(0, 6).map((el) => ({
            tag: el.tagName.toLowerCase(), attrs: Object.fromEntries([...el.attributes].filter((a) => a.name.startsWith('data-') || a.name === 'role' || a.name === 'aria-busy').map((a) => [a.name, a.value.slice(0, 80)])),
            text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 160) }))).catch(() => []));
          const shot = path.join(out, `e2e-${browserName}-${id}-${n}.png`);
          await page.screenshot({ path: shot, fullPage: false }).then(() => shots.push(path.basename(shot))).catch(() => {});
        }
        diagnostics = { console: consoleLines.slice(0, 40), agentCalls: agentCalls.slice(0, 80), generatedHosts: hosts, screenshots: shots, url: pages[0] && !pages[0].isClosed() ? shortPath(pages[0].url()) : null };
      }
      if (providerBase) await fetch(`${providerBase}/__fault`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"fault":null}' }).catch(() => {});
      for (const ctx of contexts) await ctx.close().catch(() => {});
    }
    items.push({ check: `e2e:${id}`, status, detail: detail.slice(0, 600), metrics, ms: Date.now() - started, ...(diagnostics ? { diagnostics } : {}) });
    process.stdout.write(`${status.toUpperCase().padEnd(7)} ${browserName} ${id} — ${detail.slice(0, 200)}\n`);
  }
  await browser.close();
  const counts = Object.fromEntries(['pass', 'fail', 'blocked'].map((s) => [s, items.filter((i) => i.status === s).length]));
  const report = { name: `e2e-${browserName}`, browser: browserName, version, emulation: true, environmentKind: 'ci-browser-emulation',
                   note: 'Viewports/devices are Playwright emulation on a Linux CI runner, not physical devices.', counts, items, finishedAt: new Date().toISOString() };
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, `e2e-${browserName}.json`), JSON.stringify(report, null, 1));
  process.stdout.write(`${browserName}: ${JSON.stringify(counts)}\n`);
  process.exit(counts.fail ? 1 : 0);
}

main().catch((error) => { console.error(error); process.exit(1); });
