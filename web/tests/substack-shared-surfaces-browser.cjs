/**
 * Narrow Chromium acceptance for actual SubstackManualQueue and CalendarView.
 * Uses real Rafii hooks/client/calendar/popovers; only workspace identity, HTTP
 * responses and the unrelated closed ScheduleDialog are fixtures.
 * No provider calls or real publishing; not production or live Substack acceptance.
 * Run: RAFII_SUBSTACK_CHROMIUM=/path/to/chrome-headless-shell node web/tests/substack-shared-surfaces-browser.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { createRequire } = require('node:module');
const web = path.resolve(__dirname, '..');
const webRequire = createRequire(path.join(web, 'package.json'));
const { webpack } = webRequire('next/dist/compiled/webpack/webpack.js');
const postcss = webRequire('postcss');
const tailwind = webRequire('@tailwindcss/postcss');
const playwright = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'))
  : webRequire('playwright');
const output = process.env.RAFII_SUBSTACK_UI_EVIDENCE || fs.mkdtempSync(path.join(os.tmpdir(), 'rafii-substack-shared-browser-'));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'rafii-substack-shared-build-'));
fs.mkdirSync(output, { recursive: true });
const errors = [];
const requests = [];
const checks = [];
const connectionId = 'sc_' + '1'.repeat(32);
const draftId = 'sd_' + '2'.repeat(32);
const queueId = 'sq_' + '3'.repeat(32);
const contentHash = 'a'.repeat(64);
const title = '<img src=x onerror="window.sharedPwned=1">';
const body = 'PRIVATE_DRAFT_BODY_MUST_NOT_APPEAR_ON_SHARED_SURFACES';
const scheduledFor = '2026-10-18T14:00:00Z';
const snapshot = {
  revision: 1,
  state: {
    workspace: { id: 'w-shared', sample: false },
    phase2: { jobs: [], reviews: [], channels: [] },
    variants: [],
    substack: {
      version: 1,
      connections: [{ id: connectionId, mode: 'public_feed', status: 'feed_added', publicationUrl: 'https://sharedfixture.substack.com' }],
      drafts: [{ id: draftId, connectionId, title, body, contentHash, approvedHash: contentHash, status: 'approved', scheduledFor }],
      queue: [{ id: queueId, draftId, connectionId, contentHash, kind: 'manual_handoff', status: 'pending_manual', scheduledFor, autoPublished: false }]
    }
  }
};
let enabled = true;
let browser;
let server;

async function build() {
  const workspace = path.join(temporary, 'workspace.tsx');
  const entry = path.join(temporary, 'entry.tsx');
  const schedule = path.join(temporary, 'schedule.tsx');
  const loader = path.join(temporary, 'loader.cjs');
  fs.writeFileSync(workspace, `
    import React, { createContext, useContext, useState } from 'react';
    import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
    import { createApi } from '@/lib/api/client';
    import { WorkspaceAccessProvider } from '@/lib/auth/access';
    const Context = createContext(null);
    const api = createApi(async () => 'synthetic-substack-shared-session');
    export const useWorkspace = () => useContext(Context);
    export const useWorkspaceApi = () => useContext(Context);
    export function FixtureWorkspace({ children }) {
      const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
      const workspaceId = new URLSearchParams(location.search).get('workspace') || 'w-shared';
      const access = { role: 'viewer', permissions: ['read'], plan: 'trial', hasWorkspace: true, capabilities: [] };
      async function disableFeature() {
        await fetch('/__fixture/disable', { method: 'POST' });
        await client.invalidateQueries({ queryKey: ['channels', workspaceId] });
      }
      return <QueryClientProvider client={client}><Context.Provider value={{ api, workspaceId }}><WorkspaceAccessProvider value={access}>
        <nav aria-label='Synthetic test controls'><button data-testid='disable-fixture-feature' onClick={disableFeature}>Disable fixture feature</button></nav>
        {children}
      </WorkspaceAccessProvider></Context.Provider></QueryClientProvider>;
    }
  `);
  fs.writeFileSync(schedule, 'export function ScheduleDialog() { return null; }');
  fs.writeFileSync(entry, `
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    import { NuqsTestingAdapter } from 'nuqs/adapters/testing';
    import { InfobarProvider } from '@/components/ui/infobar';
    import { useSnapshot, useChannels } from '@/lib/api/hooks';
    import { useWorkspaceApi } from '@/lib/workspace/provider';
    import { substackManualEntries } from '@/lib/substack/manual-queue';
    import { SubstackManualQueue } from '@/features/queue/substack-manual-queue';
    import { CalendarView } from '@/features/calendar/calendar-view';
    import { FixtureWorkspace } from ${JSON.stringify(workspace)};
    function SharedSurfaces() {
      const snapshot = useSnapshot();
      const channels = useChannels();
      const { workspaceId } = useWorkspaceApi();
      const entries = substackManualEntries(snapshot.data?.state, workspaceId, !channels.isError && channels.data?.substack?.available === true, Date.now() / 1000);
      return <><div style={{padding: '20px'}}><SubstackManualQueue entries={entries} /></div><CalendarView /></>;
    }
    createRoot(document.getElementById('root')).render(<FixtureWorkspace><NuqsTestingAdapter searchParams={{ date: '2026-10-18' }} hasMemory><InfobarProvider defaultOpen={false}><div className='flex min-w-0 flex-1 flex-col'><SharedSurfaces /></div></InfobarProvider></NuqsTestingAdapter></FixtureWorkspace>);
  `);
  fs.writeFileSync(loader, `const ts=require(${JSON.stringify(webRequire.resolve('typescript'))}); module.exports=function(source){return ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;};`);
  await new Promise((resolve, reject) => {
    const compiler = webpack({
      mode: 'development', context: web, entry, target: 'web', devtool: false,
      output: { path: temporary, filename: 'app.js' },
      resolve: { extensions: ['.tsx', '.ts', '.js', '.mjs', '.json'], modules: [path.join(web, 'node_modules'), 'node_modules'], alias: { '@/lib/workspace/provider$': workspace, '@/features/queue/schedule-dialog$': schedule, '@': path.join(web, 'src') } },
      resolveLoader: { modules: [path.join(web, 'node_modules')] },
      module: { rules: [{ test: /\.tsx?$/, exclude: /node_modules/, use: [{ loader }] }] },
      plugins: [new webpack.DefinePlugin({ 'process.env': JSON.stringify({ NODE_ENV: 'development' }) })],
      optimization: { minimize: false }, cache: false, infrastructureLogging: { level: 'error' }
    });
    compiler.run((error, stats) => compiler.close(() => error ? reject(error) : stats.hasErrors() ? reject(new Error(stats.toString({ all: false, errors: true }))) : resolve()));
  });
  const source = path.join(web, 'src/styles/globals.css');
  const css = await postcss([tailwind({ base: web, optimize: false })]).process(fs.readFileSync(source, 'utf8'), { from: source, to: path.join(temporary, 'app.css') });
  fs.writeFileSync(path.join(temporary, 'app.css'), css.css);
}

async function startServer() {
  server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const json = (status, value) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
    if (url.pathname === '/app.js' || url.pathname === '/app.css') {
      res.writeHead(200, { 'Content-Type': url.pathname.endsWith('.css') ? 'text/css' : 'text/javascript' });
      res.end(fs.readFileSync(path.join(temporary, url.pathname.slice(1)))); return;
    }
    if (url.pathname === '/__fixture/disable' && req.method === 'POST') { enabled = false; return json(200, { fixtureEnabled: false }); }
    if (url.pathname === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end('<!doctype html><html lang="en" data-theme="rafii"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Substack shared surfaces test</title><link rel="stylesheet" href="/app.css"></head><body><main style="max-width:1180px;margin:20px auto"><div id="root"></div></main><script src="/app.js"></script></body></html>'); return;
    }
    try {
      const match = url.pathname.match(/^\/api\/workspaces\/(w-shared|w-other)(\/channels)?$/);
      assert.ok(match, `fixture-only route: ${url.pathname}`);
      assert.equal(req.method, 'GET', 'shared surfaces must not issue mutation requests');
      assert.equal(req.headers.authorization, 'Bearer synthetic-substack-shared-session');
      assert.equal(req.headers['x-postriff-request'], 'founder-alpha');
      requests.push({ method: req.method, path: url.pathname });
      return json(200, match[2] ? { channels: [], providers: [], substack: { available: enabled } } : snapshot);
    } catch (error) { errors.push(error.message); return json(500, { error: error.message }); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return `http://127.0.0.1:${server.address().port}`;
}

async function visible(locator) { await locator.waitFor({ state: 'visible', timeout: 15000 }); }
async function scenario(name, body) { await body(); checks.push({ name, passed: true }); console.log('PASS', name); }

(async () => {
  try {
    await build();
    const origin = await startServer();
    browser = await playwright.chromium.launch({ executablePath: process.env.RAFII_SUBSTACK_CHROMIUM, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking', '--disable-component-update', '--disable-sync'] });
    const context = await browser.newContext({ viewport: { width: 1180, height: 1100 }, reducedMotion: 'reduce', timezoneId: 'America/Indiana/Indianapolis' });
    await context.route('**/*', (route) => route.request().url().startsWith(origin) ? route.continue() : route.abort());
    const page = await context.newPage();
    page.on('pageerror', (error) => errors.push(error.stack || error.message));
    await page.goto(origin);
    await scenario('Queue card escapes the title, omits draft body and links to the exact approved draft', async () => {
      const queue = page.getByTestId('substack-manual-queue');
      await visible(queue);
      await visible(queue.getByText(title, { exact: true }));
      await visible(queue.getByText('These drafts need you to finish in Substack. Target times and prepared handoffs do not confirm publication.', { exact: true }));
      assert.match(await queue.innerText(), /Target:/);
      assert.equal((await page.locator('body').innerText()).includes(body), false);
      assert.equal(await queue.locator('img').count(), 0);
      assert.equal(await page.evaluate(() => window.sharedPwned), undefined);
      assert.equal(await queue.getByRole('link', { name: 'Open Substack draft', exact: true }).getAttribute('href'), `/app/channels?connect=substack&substackDraft=${draftId}`);
      await queue.screenshot({ path: path.join(output, 'substack-shared-queue.png') });
    });
    await scenario('Calendar renders the scheduled manual handoff and its real detail popover', async () => {
      const event = page.locator('[data-tour="calendar-event"]');
      await visible(event);
      assert.equal(await event.count(), 1);
      assert.match(await event.getAttribute('aria-label'), /Substack, Manual handoff/);
      await event.click();
      await visible(page.getByText('Finish this draft in Substack. This target and a prepared handoff do not confirm publication.', { exact: true }));
      await visible(page.getByText(/^Manual handoff target:/));
      assert.equal((await page.locator('body').innerText()).includes(body), false);
      assert.equal(await page.evaluate(() => window.sharedPwned), undefined);
      assert.equal(await page.getByRole('link', { name: 'Open Substack draft', exact: true }).count(), 2);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.screenshot({ path: path.join(output, 'substack-calendar-manual-handoff.png'), fullPage: true });
      await page.keyboard.press('Escape');
    });
    await scenario('A server feature rollback hides both Queue and Calendar manual handoffs', async () => {
      await page.getByTestId('disable-fixture-feature').click();
      await page.getByTestId('substack-manual-queue').waitFor({ state: 'detached' });
      await visible(page.getByText('Nothing scheduled', { exact: true }));
      assert.equal(await page.locator('[data-tour="calendar-event"]').count(), 0);
    });
    await scenario('A snapshot from another workspace cannot render shared Substack entries', async () => {
      enabled = true;
      await page.goto(origin + '/?workspace=w-other');
      await visible(page.getByText('Nothing scheduled', { exact: true }));
      assert.equal(await page.getByTestId('substack-manual-queue').count(), 0);
      assert.equal(await page.locator('[data-tour="calendar-event"]').count(), 0);
      assert.equal((await page.locator('body').innerText()).includes(title), false);
    });
    assert.deepEqual(errors, []);
    const receipt = { status: 'passed', testKind: 'synthetic_browser_shared_surfaces', liveSubstackAcceptance: false, productionDeployed: false, browser: await browser.version(), checks, requests, consoleErrors: errors };
    fs.writeFileSync(path.join(output, 'substack-shared-surfaces-browser-result.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify({ status: 'passed', checks: checks.length, output }));
  } catch (error) {
    fs.writeFileSync(path.join(output, 'substack-shared-surfaces-browser-result.json'), JSON.stringify({ status: 'failed', testKind: 'synthetic_browser_shared_surfaces', error: error.stack, checks, requests, errors }, null, 2));
    console.error(error); process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (server) await new Promise((resolve) => server.close(resolve));
  }
})();
