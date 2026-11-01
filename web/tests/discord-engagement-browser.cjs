/** Cloud-only browser controls. API responses are synthetic; all off-origin IO is blocked. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');
assert.equal(process.platform, 'linux'); assert.equal(process.env.CI, 'true');
const root = join(__dirname, '../..'), base = 'http://127.0.0.1:4439';
const template = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json')));
const original = JSON.parse(readFileSync(join(root, '.depot/discord-p0-ui.json')));
const fixtures = JSON.parse(readFileSync(join(root, '.depot/discord-engagement-ui.json')));
const wid = original.job.manifest.workspaceId, channelId = original.channel.id;
const first = fixtures.before.destinations.find(x => x.target.channelId === '7777777');
assert.ok(first);
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', '-p', '4439', '-H', '127.0.0.1'],
  { cwd: join(root, 'web'), env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
app.stdout.on('data', x => process.stdout.write(x)); app.stderr.on('data', x => process.stderr.write(x));
(async () => {
  let browser; const checks = [];
  try {
    let ready = false;
    for (let i = 0; i < 120; i++) {
      if (await fetch(base).then(r => r.status < 500).catch(() => false)) { ready = true; break; }
      await new Promise(r => setTimeout(r, 500));
    }
    assert.ok(ready); browser = await chromium.launch({ headless: true });
    for (const width of [1280, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
      try {
        await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }]);
        await context.addInitScript(id => {
          localStorage.setItem('postriff-dev-principal', '00000000-0000-0000-0000-000000000001');
          localStorage.setItem('postriff-workspace', id);
          localStorage.setItem('postriff-onboarding:00000000-0000-0000-0000-000000000001', JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
        }, wid);
        let status = structuredClone(fixtures.paused), reads = 0, approvals = 0, previews = 0, grants = 0, revokes = 0, broader = false;
        const channel = structuredClone(fixtures.channelPaused);
        assert.ok(channel.capabilities);
        assert.equal(fixtures.channelBefore.capabilities.analytics.availability, 'consent_required');
        assert.equal(fixtures.channelGranted.capabilities.analytics.availability, 'scoped');
        const snapshot = { ...structuredClone(template.snapshot), state: { ...structuredClone(template.snapshot.state),
          workspace: { ...template.snapshot.state.workspace, id: wid }, phase2: { ...template.snapshot.state.phase2, channels: [channel], jobs: [], reviews: [] } } };
        let exactText = '', review = structuredClone(fixtures.review), approvalClicked = false;
        const page = await context.newPage(); page.setDefaultTimeout(30000);
        const pageErrors = []; page.on('pageerror', error => pageErrors.push(String(error)));
        await context.route('**/*', async route => {
          const request = route.request(), url = new URL(request.url()), path = url.pathname;
          if (url.origin !== base) return route.abort();
          if (!path.startsWith('/api/')) return route.continue();
          const send = (body, code = 200) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
          const prefix = `/api/workspaces/${wid}/channels/${channelId}/discord-engagement`;
          if (path === prefix && request.method() === 'GET') return send(status);
          if (path === prefix + '/consent') {
            const body = request.postDataJSON();
            assert.equal(body.destinationId, first.target.id);
            const currentTarget = status.destinations.find(item => item.target.id === body.destinationId);
            assert.ok(currentTarget); assert.equal(body.targetDigest, currentTarget.targetDigest); assert.equal(body.confirmed, true);
            if (Object.values(body.permissions).some(Boolean)) {
              grants++; assert.deepEqual(body.permissions, { analytics: true, inbox: true, reply: true }); broader = body.contentAccess === 'approved_content'; status = structuredClone(broader ? fixtures.broaderGranted : fixtures.granted);
              Object.assign(channel, structuredClone(broader ? fixtures.channelBroaderGranted : fixtures.channelGranted));
            } else { revokes++; status = structuredClone(fixtures.before); Object.assign(channel, structuredClone(fixtures.channelBefore)); }
            return send(status);
          }
          if (path === prefix + '/read') {
            reads++; assert.ok(grants >= 1);
            const body = request.postDataJSON(); assert.equal(body.destinationId, first.target.id);
            return send(broader && body.kind === 'inbox' ? fixtures.broaderInbox : fixtures[body.kind]);
          }
          if (path === prefix + '/preview') {
            previews++; assert.equal(approvals, 0);
            const body = request.postDataJSON(); assert.equal(body.parentMessageId, fixtures.review.parent.id);
            assert.equal(body.destinationId, first.target.id); exactText = body.text;
            review.manifest.payload.text = body.text;
            return send(review);
          }
          if (path === prefix + '/approve') {
            assert.equal(approvalClicked, true); assert.equal(previews, 1); approvals++;
            assert.deepEqual(request.postDataJSON(), { reviewId: review.reviewId, digest: review.digest, confirmed: true });
            status = structuredClone(fixtures.after); status.jobs[0].text = exactText;
            return send(fixtures.approval);
          }
          if (request.method() !== 'GET') return send({ error: 'Unexpected synthetic mutation' }, 400);
          if (path.endsWith('/channels')) return send({ channels: [channel], providers: [{ id: 'discord', platform: 'Discord', configured: true, connectReady: true, productionReviewed: true, capabilities: {} }] });
          if (path === '/api/catalog') return send({ authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {} });
          if (path === '/api/me') return send({ userId: '00000000-0000-0000-0000-000000000001', displayName: 'Synthetic tester', preferences: { timeZone: 'UTC', locale: 'en' }, mfa: {} });
          if (path === '/api/workspaces') return send({ workspaces: [{ workspaceId: wid, membership: template.snapshot.membership, name: 'Synthetic Discord', plan: 'studio', memberCounts: { owner: 1 } }] });
          if (path === `/api/workspaces/${wid}`) return send(snapshot);
          if (path.endsWith('/memory')) return send(template.memory);
          if (path.endsWith('/memory/proposals')) return send({ pending: [], recent: [], learning: { items: [] } });
          if (path.endsWith('/audience/threads')) return send({ threads: [], capabilities: [], replySendingEnabled: false, limits: '', counts: { all: 0, replied: 0, unanswered: 0 } });
          if (path.includes('/analytics/')) return send({ posts: [], connections: [], families: {}, state: 'limited', rules: {} });
          return send({ error: 'Unhandled synthetic read' }, 404);
        });
        await page.goto(base + '/app/channels', { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: 'Discord analytics & conversations', exact: true }).click();
        await page.getByRole('combobox', { name: 'Engagement destination' }).waitFor();
        assert.equal(reads, 0, 'Opening the panel cannot ingest provider data.');
        assert.equal(await page.getByRole('button', { name: 'Read Discord metrics', exact: true }).isDisabled(), true);
        await page.getByText('Engagement rollout is paused', { exact: true }).waitFor();
        assert.equal(await page.getByRole('button', { name: 'Approve selected access', exact: true }).isDisabled(), true);
        assert.equal(reads, 0); assert.equal(approvals, 0);
        status = structuredClone(fixtures.before); Object.assign(channel, structuredClone(fixtures.channelBefore));
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: 'Discord analytics & conversations', exact: true }).click();
        await page.getByRole('combobox', { name: 'Engagement destination' }).selectOption(first.target.id);
        for (const name of ['Read server snapshots and Rafii-managed message metrics', 'Read the partial Discord inbox', 'Prepare replies for my individual approval']) await page.getByRole('checkbox', { name, exact: true }).check();
        await page.getByRole('button', { name: 'Approve selected access', exact: true }).click();
        await page.getByRole('button', { name: 'Read Discord metrics', exact: true }).click();
        await page.getByRole('region', { name: 'Discord metric readings' }).waitFor();
        await page.getByText('Native approximate server snapshot', { exact: true }).waitFor();
        await page.getByText('Rafii-managed messages only', { exact: true }).waitFor();
        assert.match(await page.getByRole('region', { name: 'Discord metric readings' }).innerText(), /lower bound/);
        assert.match(await page.getByRole('region', { name: 'Discord metric readings' }).innerText(), /reach.*unavailable/i);
        await page.getByRole('button', { name: 'Read partial inbox', exact: true }).click();
        const inbox = page.getByRole('region', { name: 'Partial Discord inbox' }); await inbox.waitFor();
        await page.getByText('Content restricted by Discord', { exact: true }).waitFor();
        assert.equal(await inbox.getByRole('button', { name: 'Write a reply', exact: true }).nth(1).isDisabled(), true);
        assert.ok(!(await page.locator('body').innerText()).includes('Unrelated private text'));
        await inbox.getByRole('button', { name: 'Write a reply', exact: true }).first().click();
        await page.getByRole('textbox', { name: 'Exact Discord reply', exact: true }).fill('Exact approved reply @everyone');
        await page.getByRole('button', { name: 'Review exact reply', exact: true }).click();
        const dialog = page.getByRole('dialog', { name: 'Approve this exact Discord reply' }); await dialog.waitFor();
        await dialog.getByText('Exact approved reply @everyone', { exact: true }).waitFor();
        assert.match(await dialog.innerText(), new RegExp(first.target.guildId));
        assert.match(await dialog.innerText(), new RegExp(first.target.channelId));
        assert.match(await dialog.innerText(), new RegExp(review.parent.id));
        assert.equal(approvals, 0); approvalClicked = true;
        await dialog.getByRole('button', { name: 'Approve this exact reply', exact: true }).click();
        await page.getByRole('region', { name: 'My approved Discord replies' }).waitFor();
        assert.equal(approvals, 1); assert.equal(previews, 1);
        await page.getByRole('button', { name: 'Revoke my channel access', exact: true }).click();
        await page.waitForFunction(() => !document.body.innerText.includes('Please clarify the rehearsal time.'));
        assert.equal(revokes, 1); assert.equal(reads, 2);
        assert.equal(await page.getByRole('button', { name: 'Read partial inbox', exact: true }).isDisabled(), true);
        // A separate synthetic app-policy/consent phase exercises future broader
        // mode; no real app settings or provider data are touched.
        status = structuredClone(fixtures.broaderBefore); Object.assign(channel, structuredClone(fixtures.channelBroaderBefore));
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: 'Discord analytics & conversations', exact: true }).click();
        await page.getByRole('combobox', { name: 'Engagement destination' }).selectOption(first.target.id);
        for (const name of ['Read server snapshots and Rafii-managed message metrics', 'Read the partial Discord inbox', 'Prepare replies for my individual approval', 'Read general channel text with separately approved Discord access']) await page.getByRole('checkbox', { name, exact: true }).check();
        await page.getByRole('button', { name: 'Approve selected access', exact: true }).click();
        await page.getByRole('button', { name: 'Read partial inbox', exact: true }).click();
        await page.getByText('Unrelated private text', { exact: true }).waitFor();
        const general = page.getByRole('article').filter({ hasText: 'Unrelated private text' });
        assert.match(await general.innerText(), /channel message/);
        assert.ok(!(await general.innerText()).includes('bot mention'));
        assert.equal(grants, 2); assert.equal(reads, 3);
        await page.goto(base + '/app/inbox', { waitUntil: 'domcontentloaded' });
        await page.getByText('Open Discord conversations above for manual reads with your channel consent.', { exact: true }).waitFor();
        await page.getByText('No collected comments yet', { exact: true }).waitFor();
        assert.doesNotMatch(await page.locator('body').innerText(), /Discord comments aren['’]t available yet/);
        await page.getByRole('button', { name: `Discord conversations · ${channel.account}`, exact: true }).click();
        await page.getByRole('combobox', { name: 'Engagement destination' }).waitFor();
        assert.equal(reads, 3, 'Opening the Inbox entry cannot ingest provider data.');
        assert.equal(await page.getByRole('button', { name: 'Read Discord metrics', exact: true }).count(), 0);
        assert.deepEqual(pageErrors, []);
        checks.push({ width, rolloutOffFenced: true, actualCapabilityProjection: true, consentBeforeRead: true, metricsTruthful: true, partialContent: true, approvedContentLabel: true, inboxEntryTruthful: true, exactHumanApproval: true, revokeClearsData: true, providerWrites: 0 });
      } finally { await context.close(); }
    }
    console.log('RAFII_DISCORD_ENGAGEMENT_BROWSER ' + JSON.stringify({ status: 'PASS', execution: 'synthetic-intercepted-api', checks, realDiscordRequests: 0 }));
  } finally { if (browser) await browser.close(); app.kill('SIGTERM'); }
})().catch(error => { console.error(error); process.exitCode = 1; app.kill('SIGTERM'); });
