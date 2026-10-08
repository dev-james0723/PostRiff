/**
 * Runs the lane G browser scenes (scenes.cjs) against the acceptance stack and writes evidence.
 *
 *   node web/tests/agent-ui-e2e/run.cjs --browser=chromium|webkit [--only=id,id] [--out=$AGENT_UI_EVIDENCE_DIR]
 *
 * Env: RAFII_WEB_URL (the web build, loopback only), AGENT_UI_PROVIDER_URL (fixture provider base, no /v1).
 * Output: <out>/e2e-<browser>.json  {browser, version, emulation: true, items: [{check: "e2e:<id>", status, detail, metrics}]}
 * Exit code: 1 when any scene fails; blocked scenes are reported (strict runs turn them into failures in the shell script).
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
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
    const metrics = {};
    const failures = [];
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
        return ctx.newPage();
      },
      assert(ok, what, detail) {
        if (!ok) failures.push({ what, detail: detail === undefined ? undefined : JSON.stringify(detail).slice(0, 400) });
      },
      metric(name, value) { metrics[name] = typeof value === 'number' ? Math.round(value * 10) / 10 : value; },
    };
    const started = Date.now();
    let status = 'pass';
    let detail = '';
    try {
      detail = String((await run(t)) || 'ok');
      if (failures.length) { status = 'fail'; detail = failures.map((f) => `${f.what}${f.detail ? ` — ${f.detail}` : ''}`).join(' | '); }
    } catch (error) {
      if (error instanceof Blocked) { status = 'blocked'; detail = `BLOCKED ${error.message}`; }
      else { status = 'fail'; detail = `${error.name}: ${String(error.message).split('\n')[0].slice(0, 300)}`; }
    } finally {
      if (providerBase) await fetch(`${providerBase}/__fault`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"fault":null}' }).catch(() => {});
      for (const ctx of contexts) await ctx.close().catch(() => {});
    }
    items.push({ check: `e2e:${id}`, status, detail: detail.slice(0, 600), metrics, ms: Date.now() - started });
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
