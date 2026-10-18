/**
 * Actual SubstackPanel + shared Rafii components + authenticated API client in Chromium.
 * Only the workspace context and HTTP provider data are synthetic. This is not live Substack acceptance.
 * Run: RAFII_SUBSTACK_CHROMIUM=/path/to/chrome-headless-shell node web/tests/substack-browser.cjs
 * Optional: RAFII_SUBSTACK_UI_EVIDENCE=/absolute/output/directory
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const web = path.resolve(__dirname, '..');
const webRequire = createRequire(path.join(web, 'package.json'));
const { webpack } = webRequire('next/dist/compiled/webpack/webpack.js');
const postcss = webRequire('postcss');
const tailwind = webRequire('@tailwindcss/postcss');
const playwright = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'))
  : webRequire('playwright');
const output = process.env.RAFII_SUBSTACK_UI_EVIDENCE || fs.mkdtempSync(path.join(os.tmpdir(), 'rafii-substack-browser-'));
fs.mkdirSync(output, { recursive: true });
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'rafii-substack-browser-build-'));
const checks = [];
const requests = [];
const errors = [];
const available = (reason = 'Available within Rafii only; manual work does not publish.') => ({ status: 'available', reason, evidence: [] });
const closed = { status: 'requires_official_approval', reason: 'Rafii official access is not granted.', evidence: [] };
const capabilities = Object.fromEntries(['draft_create', 'draft_edit', 'draft_preview', 'draft_approval', 'manual_handoff', 'editorial_schedule', 'public_feed_read', 'public_feed_remove'].map((key) => [key, available()]));
for (const key of ['account_connect', 'publication_analytics', 'post_publish', 'post_schedule', 'notes_create', 'subscribers_read']) capabilities[key] = closed;
const membership = (role = 'owner') => ({ role, can_publish: false, can_reply: false, can_moderate: false, can_manage_connections: false });
const empty = (role) => ({ enabled: true, revision: 1, connections: [], drafts: [], queue: [], capabilities, membership: membership(role) });
const states = { 'w-a': empty('owner'), 'w-b': empty('owner'), 'w-viewer': empty('viewer'), 'w-multi': empty('owner') };
let conflictNextApproval = false;
let malformedNextHandoff = false;
let browser;
let server;

function hashDraft(draft) {
  return crypto.createHash('sha256').update(JSON.stringify([draft.connectionId, draft.title, draft.body, draft.contentType, draft.audience, draft.scheduledFor])).digest('hex');
}

function fixtureConnection(id, publicationUrl) {
  return { id, mode: 'public_feed', publicationUrl, feedUrl: publicationUrl + '/feed', status: 'feed_added', ownershipVerified: false, accountAuthenticated: false, analyticsConnected: false, publishingAuthorized: false, createdAt: '2026-10-18T20:00:00Z' };
}

const existingDraft = { id: 'sd_existing', connectionId: 'sc_multi_a', title: 'Original publication A draft', body: 'Text belonging to the first publication.', contentType: 'article', audience: 'everyone', scheduledFor: null, format: 'markdown', status: 'draft', approvedHash: null, createdAt: '2026-10-18T20:00:00Z', updatedAt: '2026-10-18T20:00:00Z' };
existingDraft.contentHash = hashDraft(existingDraft);
states['w-multi'].connections.push(fixtureConnection('sc_multi_a', 'https://first.substack.com'), fixtureConnection('sc_multi_b', 'https://second.substack.com'));
states['w-multi'].drafts.push(existingDraft);
states['w-viewer'].connections.push(fixtureConnection('sc_multi_a', 'https://first.substack.com'));
states['w-viewer'].drafts.push({ ...existingDraft });

async function build() {
  const stub = path.join(temporary, 'workspace.tsx');
  const entry = path.join(temporary, 'entry.tsx');
  const loader = path.join(temporary, 'loader.cjs');
  fs.writeFileSync(stub, `
    import React, { createContext, useContext, useState } from 'react';
    import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
    import { createApi } from '@/lib/api/client';
    const Context = createContext(null);
    const api = createApi(async () => 'synthetic-substack-session');
    export const useWorkspace = () => useContext(Context);
    export function FixtureWorkspace({ children }) {
      const [workspaceId, setWorkspaceId] = useState(new URLSearchParams(location.search).get('workspace') || 'w-a');
      const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
      return <QueryClientProvider client={client}><Context.Provider value={{ workspaceId, api }}>
        <nav aria-label='Test fixture controls'><button data-testid='switch-workspace-b' onClick={() => setWorkspaceId('w-b')}>Test workspace B</button></nav>
        {children}
      </Context.Provider></QueryClientProvider>;
    }
  `);
  fs.writeFileSync(entry, `
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    import { FixtureWorkspace } from ${JSON.stringify(stub)};
    import { SubstackPanel } from '@/features/channels/substack-panel';
    const requestedDraftId = new URLSearchParams(location.search).get('substackDraft') || undefined;
    createRoot(document.getElementById('root')).render(<FixtureWorkspace><SubstackPanel requestedDraftId={requestedDraftId} onClose={() => {}} /></FixtureWorkspace>);
  `);
  fs.writeFileSync(loader, `const ts=require(${JSON.stringify(webRequire.resolve('typescript'))}); module.exports=function(source){return ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;};`);
  await new Promise((resolve, reject) => {
    const compiler = webpack({
      mode: 'development', context: web, entry, target: 'web', devtool: false,
      output: { path: temporary, filename: 'app.js' },
      resolve: { extensions: ['.tsx', '.ts', '.js', '.mjs', '.json'], modules: [path.join(web, 'node_modules'), 'node_modules'], alias: { '@/lib/workspace/provider$': stub, '@': path.join(web, 'src') } },
      resolveLoader: { modules: [path.join(web, 'node_modules')] },
      module: { rules: [{ test: /\.tsx?$/, exclude: /node_modules/, use: [{ loader }] }] },
      optimization: { minimize: false }, cache: false,
      infrastructureLogging: { level: 'error' }
    });
    compiler.run((error, stats) => compiler.close(() => error ? reject(error) : stats.hasErrors() ? reject(new Error(stats.toString({ all: false, errors: true }))) : resolve()));
  });
  const source = path.join(web, 'src/styles/globals.css');
  const css = await postcss([tailwind({ base: web, optimize: false })]).process(fs.readFileSync(source, 'utf8'), { from: source, to: path.join(temporary, 'app.css') });
  fs.writeFileSync(path.join(temporary, 'app.css'), css.css);
}

async function startServer() {
  server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const respond = (status, payload) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(payload)); };
    if (url.pathname === '/app.js' || url.pathname === '/app.css') {
      res.writeHead(200, { 'Content-Type': url.pathname.endsWith('.css') ? 'text/css' : 'text/javascript' });
      res.end(fs.readFileSync(path.join(temporary, url.pathname.slice(1)))); return;
    }
    if (url.pathname === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end('<!doctype html><html lang="en" data-theme="rafii"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Substack component test</title><link rel="stylesheet" href="/app.css"></head><body><main style="max-width:1100px;margin:20px auto;padding:16px"><div id="root"></div></main><script src="/app.js"></script></body></html>'); return;
    }
    const match = url.pathname.match(/^\/api\/workspaces\/([^/]+)\/substack\/(.+)$/);
    if (!match) return respond(404, { error: 'Fixture route unavailable' });
    try {
      assert.equal(req.headers.authorization, 'Bearer synthetic-substack-session');
      assert.equal(req.headers['x-postriff-request'], 'founder-alpha');
      const state = states[decodeURIComponent(match[1])];
      assert.ok(state, 'known synthetic workspace');
      const route = match[2];
      if (req.method === 'GET') return respond(200, state);
      let raw = '';
      for await (const chunk of req) raw += chunk;
      const payload = JSON.parse(raw);
      requests.push({ workspace: match[1], method: req.method, route, expectedRevision: payload.expectedRevision });
      if (state.membership.role === 'viewer' && !route.endsWith('/refresh')) return respond(403, { error: 'Read-only workspace', code: 'permission_denied' });
      if (payload.expectedRevision !== state.revision) return respond(409, { error: 'Workspace changed', code: 'workspace_revision_conflict' });
      if (route === 'connections') {
        assert.equal(payload.mode, 'public_feed'); assert.equal(payload.confirmed, true);
        state.connections.push(fixtureConnection('sc_a', payload.publicationUrl));
      } else if (route.endsWith('/refresh')) {
        state.revision += 1;
        return respond(200, { ...state, feed: { items: [{ id: 'unsafe', title: '<img src=x onerror="window.feedPwned=1">', summary: '<script>window.feedPwned=1</script>', url: 'javascript:window.feedPwned=1' }, { id: 'normal', title: 'Public post', url: 'https://alice.substack.com/p/example', summary: 'Public source summary' }] } });
      } else if (route.endsWith('/disconnect')) {
        state.connections[0].status = 'disconnected';
        for (const d of state.drafts) { d.status = 'draft'; d.approvedHash = null; }
      } else if (route === 'drafts' || (req.method === 'PATCH' && /^drafts\/[^/]+$/.test(route))) {
        const existing = route === 'drafts' ? undefined : state.drafts.find((d) => d.id === decodeURIComponent(route.split('/')[1]));
        const d = existing || { id: 'sd_' + (state.drafts.length + 1), createdAt: '2026-10-18T20:00:00Z' };
        Object.assign(d, { connectionId: payload.connectionId, title: payload.title, body: payload.body, contentType: payload.contentType || 'article', audience: payload.audience || 'everyone', scheduledFor: payload.scheduledFor, format: 'markdown', status: 'draft', approvedHash: null, updatedAt: '2026-10-18T20:00:00Z' });
        d.contentHash = hashDraft(d);
        if (!existing) state.drafts.push(d);
      } else {
        const d = state.drafts.find((d) => d.id === decodeURIComponent(route.split('/')[1]));
        assert.ok(d, 'draft exists in this workspace');
        assert.equal(payload.contentHash, d.contentHash);
        if (route.endsWith('/approve')) {
          assert.equal(payload.confirmed, true);
          if (conflictNextApproval) {
            conflictNextApproval = false; d.body = 'Newer version from another editor'; d.contentHash = hashDraft(d); d.approvedHash = null; d.status = 'draft'; state.revision += 1;
            return respond(409, { error: 'Draft changed', code: 'substack_approval_stale' });
          }
          d.approvedHash = d.contentHash; d.status = 'approved';
        } else if (route.endsWith('/handoff')) {
          assert.equal(d.approvedHash, d.contentHash);
          d.status = 'handoff_ready'; state.revision += 1;
          return respond(200, { ...state, handoff: { status: 'manual_action_required', publicationUrl: state.connections.find((connection) => connection.id === d.connectionId).publicationUrl, title: d.title, body: d.body, format: 'markdown', contentType: d.contentType, audience: d.audience, contentHash: malformedNextHandoff ? '0'.repeat(64) : d.contentHash, scheduledFor: d.scheduledFor, autoPublished: false } });
        } else if (route.endsWith('/cancel')) { d.status = 'canceled'; d.approvedHash = null; }
        else if (req.method === 'DELETE') { state.drafts = state.drafts.filter((entry) => entry.id !== d.id); }
        else return respond(404, { error: 'Unknown fixture action' });
      }
      state.revision += 1;
      return respond(200, state);
    } catch (error) { errors.push(error.message); return respond(500, { error: error.message }); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return `http://127.0.0.1:${server.address().port}`;
}

async function expectVisible(locator) { await locator.waitFor({ state: 'visible', timeout: 15000 }); }
async function scenario(name, body) { await body(); checks.push({ name, passed: true }); console.log('PASS', name); }

(async () => {
  try {
    await build();
    const origin = await startServer();
    browser = await playwright.chromium.launch({ executablePath: process.env.RAFII_SUBSTACK_CHROMIUM, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking', '--disable-component-update', '--disable-sync'] });
    const context = await browser.newContext({ viewport: { width: 1180, height: 960 }, reducedMotion: 'reduce', timezoneId: 'America/Indiana/Indianapolis' });
    await context.route('**/*', (route) => route.request().url().startsWith(origin) ? route.continue() : route.abort());
    const page = await context.newPage();
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(origin);
    await expectVisible(page.getByRole('heading', { name: 'Add a public publication' }));
    await scenario('Feed consent, real API receipt and separate account claims', async () => {
      assert.equal(await page.getByRole('button', { name: 'Add public feed', exact: true }).isDisabled(), true);
      await page.getByLabel('Publication URL', { exact: true }).fill('https://alice.substack.com');
      await page.getByLabel('I have permission to use this public feed in this workspace', { exact: true }).check();
      await page.getByRole('button', { name: 'Add public feed', exact: true }).click();
      await expectVisible(page.getByText('Public Feed Added: Yes', { exact: true }));
      await expectVisible(page.getByText('Account Authenticated: No', { exact: true }));
      await expectVisible(page.getByText('Publishing Authorized: No', { exact: true }));
      assert.equal(states['w-a'].connections.length, 1);
    });
    await scenario('Hostile feed HTML and executable links remain inert text', async () => {
      await page.getByRole('button', { name: 'Read public feed', exact: true }).click();
      await expectVisible(page.getByText('<script>window.feedPwned=1</script>', { exact: true }));
      assert.equal(await page.locator('a[href^="javascript:"]').count(), 0);
      assert.equal(await page.evaluate(() => window.feedPwned), undefined);
      await page.screenshot({ path: path.join(output, 'substack-publication.png'), fullPage: true });
    });
    await scenario('Unsaved draft survives access-tab review without executing embedded HTML', async () => {
      await page.getByRole('radio', { name: 'Drafts & handoff', exact: true }).click();
      await page.getByLabel('Title', { exact: true }).fill('October rehearsal notes');
      await page.getByLabel('Draft text (Markdown)', { exact: true }).fill('## First movement\n<script>window.draftPwned=1</script>');
      await page.getByRole('radio', { name: 'Access & capabilities', exact: true }).click();
      await expectVisible(page.getByRole('heading', { name: 'Official analytics connection' }));
      assert.equal(await page.getByRole('button', { name: /^Publish( |$)/ }).count(), 0);
      await page.getByRole('radio', { name: 'Drafts & handoff', exact: true }).click();
      assert.equal(await page.getByLabel('Title', { exact: true }).inputValue(), 'October rehearsal notes');
      await page.getByRole('button', { name: 'Preview text', exact: true }).click();
      assert.equal(await page.locator('#substack-draft-preview script').count(), 0);
      assert.equal(await page.evaluate(() => window.draftPwned), undefined);
      await page.getByRole('button', { name: 'Save draft', exact: true }).click();
      await expectVisible(page.getByRole('button', { name: 'Approve this draft', exact: true }));
      assert.equal(states['w-a'].drafts.length, 1);
    });
    await scenario('Exact approval prepares a downloadable manual receipt, never publishes', async () => {
      assert.equal(await page.getByRole('button', { name: 'Prepare manual handoff', exact: true }).isDisabled(), true);
      await page.getByLabel('I reviewed this saved version for manual handoff', { exact: true }).check();
      await page.getByRole('button', { name: 'Approve this draft', exact: true }).click();
      await expectVisible(page.getByText('This saved version is approved for manual handoff. Nothing has been published.', { exact: true }));
      await page.getByRole('button', { name: 'Prepare manual handoff', exact: true }).click();
      await expectVisible(page.getByTestId('substack-handoff-receipt'));
      await expectVisible(page.getByText('Manual action required · Not published · No email sent', { exact: true }));
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download approved Markdown', exact: true }).click();
      const download = await downloadPromise;
      await download.saveAs(path.join(output, 'synthetic-approved-draft.md'));
      assert.match(fs.readFileSync(path.join(output, 'synthetic-approved-draft.md'), 'utf8'), /October rehearsal notes/);
      await page.screenshot({ path: path.join(output, 'substack-draft-handoff.png'), fullPage: true });
    });
    await scenario('An edit invalidates the displayed handoff and a concurrent revision requires review', async () => {
      await page.getByLabel('Draft text (Markdown)', { exact: true }).fill('Revised draft text');
      assert.equal(await page.getByTestId('substack-handoff-receipt').count(), 0);
      assert.equal(await page.getByRole('button', { name: 'Prepare manual handoff', exact: true }).isDisabled(), true);
      await page.getByRole('button', { name: 'Save draft', exact: true }).click();
      await expectVisible(page.getByRole('button', { name: 'Approve this draft', exact: true }));
      conflictNextApproval = true;
      await page.getByLabel('I reviewed this saved version for manual handoff', { exact: true }).check();
      await page.getByRole('button', { name: 'Approve this draft', exact: true }).click();
      await expectVisible(page.getByText('A newer saved version is available', { exact: true }));
      assert.equal(await page.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), 'Revised draft text');
      assert.equal(await page.getByRole('button', { name: 'Prepare manual handoff', exact: true }).isDisabled(), true);
      await page.getByRole('button', { name: 'Load saved version', exact: true }).click();
      assert.equal(await page.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), 'Newer version from another editor');
    });
    await scenario('A mismatched handoff receipt is rejected without a download action', async () => {
      await page.getByLabel('I reviewed this saved version for manual handoff', { exact: true }).check();
      await page.getByRole('button', { name: 'Approve this draft', exact: true }).click();
      await expectVisible(page.getByText('This saved version is approved for manual handoff. Nothing has been published.', { exact: true }));
      malformedNextHandoff = true;
      await page.getByRole('button', { name: 'Prepare manual handoff', exact: true }).click();
      await expectVisible(page.getByText('The handoff receipt did not match the approved draft. Reload the saved draft before trying again.', { exact: true }));
      assert.equal(await page.getByRole('button', { name: 'Download approved Markdown', exact: true }).count(), 0);
      malformedNextHandoff = false;
    });
    await scenario('Disconnect invalidates handoff but retained drafts remain deletable', async () => {
      await page.getByRole('radio', { name: 'Publications', exact: true }).click();
      await page.getByRole('button', { name: 'Remove saved feed', exact: true }).click();
      await expectVisible(page.getByText('No publications saved', { exact: true }));
      await page.getByRole('radio', { name: 'Drafts & handoff', exact: true }).click();
      assert.equal(await page.getByRole('button', { name: 'Prepare manual handoff', exact: true }).isDisabled(), true);
      await page.getByRole('button', { name: 'Delete draft…', exact: true }).click();
      await page.getByRole('button', { name: 'Delete saved draft', exact: true }).click();
      await expectVisible(page.getByText('Choose a publication first', { exact: true }));
      assert.equal(states['w-a'].drafts.length, 0);
    });
    await scenario('Workspace switch cannot display a prior workspace publication or draft', async () => {
      await page.getByTestId('switch-workspace-b').click();
      await expectVisible(page.getByText('No publications saved', { exact: true }));
      assert.equal(await page.getByText('October rehearsal notes', { exact: true }).count(), 0);
      assert.equal(await page.locator('body').innerText().then((text) => text.includes('alice.substack.com')), false);
    });
    await scenario('Viewer can read state but cannot add, edit, approve or delete', async () => {
      const viewer = await context.newPage();
      await viewer.goto(origin + '/?workspace=w-viewer');
      await expectVisible(viewer.getByText('A workspace owner or member with connection permissions can add a publication.', { exact: true }));
      assert.equal(await viewer.getByRole('button', { name: 'Add public feed', exact: true }).count(), 0);
      await viewer.getByRole('radio', { name: 'Drafts & handoff', exact: true }).click();
      assert.equal(await viewer.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), existingDraft.body);
      assert.equal(await viewer.getByLabel('Draft text (Markdown)', { exact: true }).isDisabled(), true);
      assert.equal(await viewer.getByRole('button', { name: 'Save draft', exact: true }).count(), 0);
      assert.equal(await viewer.getByRole('button', { name: 'Approve this draft', exact: true }).count(), 0);
      assert.equal(await viewer.getByRole('button', { name: 'Delete draft…', exact: true }).count(), 0);
      await viewer.close();
    });
    const multiple = await context.newPage();
    multiple.on('pageerror', (error) => errors.push(error.message));
    await multiple.goto(origin + '/?workspace=w-multi');
    await scenario('Starting from the second publication creates a fresh draft bound to that destination', async () => {
      await multiple.getByRole('button', { name: 'Prepare a draft', exact: true }).nth(1).click();
      assert.equal(await multiple.getByLabel('Destination publication', { exact: true }).inputValue(), 'sc_multi_b');
      assert.equal(await multiple.getByLabel('Title', { exact: true }).inputValue(), '');
      assert.equal(await multiple.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), '');
    });
    await scenario('An untitled Note saves, receives approval and exports without an invented heading', async () => {
      await multiple.getByLabel('Content to prepare', { exact: true }).selectOption('note');
      await multiple.getByLabel('Draft text (Markdown)', { exact: true }).fill('A Note with no title.\n\nExact reviewed Note text.');
      assert.equal(await multiple.getByRole('button', { name: 'Save draft', exact: true }).isDisabled(), false);
      await multiple.getByRole('button', { name: 'Save draft', exact: true }).click();
      await expectVisible(multiple.getByRole('button', { name: 'Approve this draft', exact: true }));
      assert.equal(states['w-multi'].drafts[1].title, '');
      assert.equal(states['w-multi'].drafts[1].connectionId, 'sc_multi_b');
      await multiple.getByLabel('I reviewed this saved version for manual handoff', { exact: true }).check();
      await multiple.getByRole('button', { name: 'Approve this draft', exact: true }).click();
      await expectVisible(multiple.getByText('This saved version is approved for manual handoff. Nothing has been published.', { exact: true }));
      await multiple.getByRole('button', { name: 'Prepare manual handoff', exact: true }).click();
      const receipt = multiple.getByTestId('substack-handoff-receipt');
      await expectVisible(receipt);
      assert.equal(await receipt.getByRole('link', { name: 'Open publication' }).getAttribute('href'), 'https://second.substack.com/');
      const downloadPromise = multiple.waitForEvent('download');
      await multiple.getByRole('button', { name: 'Download approved Markdown', exact: true }).click();
      const download = await downloadPromise;
      const file = path.join(output, 'synthetic-approved-note.md');
      await download.saveAs(file);
      assert.equal(fs.readFileSync(file, 'utf8'), 'A Note with no title.\n\nExact reviewed Note text.\n');
    });
    await scenario('Unsaved text requires an explicit decision before draft switching or closing', async () => {
      await multiple.getByLabel('Draft text (Markdown)', { exact: true }).fill('Unsaved Note text to protect');
      await multiple.getByRole('button', { name: 'New draft', exact: true }).click();
      await expectVisible(multiple.getByText('Save your changes before switching drafts', { exact: true }));
      assert.equal(await multiple.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), 'Unsaved Note text to protect');
      await multiple.getByRole('button', { name: 'Keep editing this draft', exact: true }).click();
      await multiple.getByRole('button', { name: 'Close Substack', exact: true }).click();
      await expectVisible(multiple.getByText('This draft has unsaved changes', { exact: true }));
      await multiple.getByRole('button', { name: 'Keep editing', exact: true }).click();
      await multiple.getByRole('radio', { name: 'Publications', exact: true }).click();
      await multiple.getByRole('button', { name: 'Prepare a draft', exact: true }).first().click();
      await expectVisible(multiple.getByText('Save your changes before starting another draft', { exact: true }));
      assert.equal(await multiple.getByLabel('Destination publication', { exact: true }).inputValue(), 'sc_multi_b');
      assert.equal(await multiple.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), 'Unsaved Note text to protect');
      await multiple.getByRole('button', { name: 'Discard changes & start draft', exact: true }).click();
      assert.equal(await multiple.getByLabel('Destination publication', { exact: true }).inputValue(), 'sc_multi_a');
      assert.equal(await multiple.getByLabel('Draft text (Markdown)', { exact: true }).inputValue(), '');
    });
    await multiple.close();
    await scenario('A queue draft link selects only the requested current workspace draft', async () => {
      const linked = await context.newPage();
      await linked.goto(origin + '/?workspace=w-multi&substackDraft=sd_existing');
      await expectVisible(linked.getByRole('heading', { name: 'Review this draft', exact: true }));
      assert.equal(await linked.getByLabel('Title', { exact: true }).inputValue(), 'Original publication A draft');
      assert.equal(await linked.getByLabel('Destination publication', { exact: true }).inputValue(), 'sc_multi_a');
      await linked.getByTestId('switch-workspace-b').click();
      await expectVisible(linked.getByText('This draft is not available in this workspace', { exact: true }));
      assert.equal(await linked.getByLabel('Draft text (Markdown)', { exact: true }).count(), 0);
      assert.equal((await linked.locator('body').innerText()).includes(existingDraft.body), false);
      await linked.goto(origin + '/?workspace=w-multi&substackDraft=sd_unknown');
      await expectVisible(linked.getByText('This draft is no longer available', { exact: true }));
      assert.equal(await linked.getByLabel('Draft text (Markdown)', { exact: true }).count(), 0);
      await linked.close();
    });
    await scenario('Mobile panel has no page-wide horizontal overflow', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole('radio', { name: 'Access & capabilities', exact: true }).click();
      await expectVisible(page.getByRole('heading', { name: 'What is available', exact: true }));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.screenshot({ path: path.join(output, 'substack-mobile-capabilities.png'), fullPage: true });
    });
    assert.deepEqual(errors, []);
    const receipt = { status: 'passed', testKind: 'synthetic_browser_component_acceptance', liveSubstackAcceptance: false, productionDeployed: false, browser: await browser.version(), checks, requests, consoleErrors: errors, output };
    fs.writeFileSync(path.join(output, 'substack-browser-result.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify({ status: 'passed', checks: checks.length, output }));
  } catch (error) {
    fs.writeFileSync(path.join(output, 'substack-browser-result.json'), JSON.stringify({ status: 'failed', testKind: 'synthetic_browser_component_acceptance', error: error.stack, checks, requests, errors, output }, null, 2));
    console.error(error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (server) await new Promise((resolve) => server.close(resolve));
  }
})();
