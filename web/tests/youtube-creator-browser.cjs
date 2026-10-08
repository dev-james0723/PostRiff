/** Cloud Next -> hosted Python -> disposable PostgreSQL; SYNTHETIC Google/identity. Never real Google E2E. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
assert.equal(process.platform, 'linux', 'Browser validation runs only on cloud Linux CI.');
assert.match(process.env.CI || '', /^(1|true)$/i);
const base = process.env.YOUTUBE_WEB_URL || 'http://127.0.0.1:4448';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = resolve(process.env.YOUTUBE_BROWSER_EVIDENCE_DIR || resolve(__dirname, '../../.jcb-artifacts/youtube-browser'));
mkdirSync(out, { recursive: true });
const results = [];
let currentPage;
const proof = status => ({ status, execution: 'CLOUD SYNTHETIC APPLICATION BROWSER; NOT REAL GOOGLE E2E',
  realGoogleE2E: false, productionAcceptance: false, capturedAt: new Date().toISOString(),
  backend: 'loopback Python with disposable PostgreSQL; generated synthetic standard/agentic clients', results });
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 390, 320]) {
      const principal = randomUUID();
      const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
      await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
      await context.addInitScript(id => {
        localStorage.setItem('postriff-dev-principal', id);
        localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
      }, principal);
      await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
      const headers = { Authorization: 'Bearer dev:' + principal, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
      const request = async (method, path, data) => {
        const response = await context.request.fetch(base + path, { method, headers, data });
        assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`);
        return response.json();
      };
      const boot = await request('POST', '/api/auth/verify', { plan: 'studio' });
      const wid = boot.workspaceId;
      const policyPage = await context.newPage();
      await policyPage.goto(base + '/app/youtube');
      const agree = policyPage.getByRole('button', { name: 'Agree to YouTube policies', exact: true });
      await agree.waitFor();
      assert.equal(await agree.isEnabled(), false, 'The synthetic user must explicitly check agreement.');
      await policyPage.getByRole('checkbox', { name: 'I agree to these Privacy Policy and Terms revisions for my YouTube use in this workspace.', exact: true }).check();
      const [accepted] = await Promise.all([
        policyPage.waitForResponse(response => response.url().endsWith('/youtube-policy') && response.request().method() === 'POST'),
        agree.click()
      ]);
      assert.ok(accepted.ok(), await accepted.text());
      assert.equal((await accepted.json()).receipt.userId, principal);
      await policyPage.goto(base + '/app/channels?connect=youtube&capability=publish');
      await policyPage.waitForFunction(() => document.querySelector('[data-tour="connect-continue"]')?.disabled === false);
      await policyPage.getByRole('button', { name: 'Cancel', exact: true }).click();
      for (let reopening = 0; reopening < 2; reopening++) {
        await policyPage.locator('[data-tour="channels-connect"]').first().click();
        await policyPage.locator('[data-tour="connect-platform"]').filter({ hasText: 'YouTube' }).click();
        await policyPage.waitForFunction(() => document.querySelector('[data-tour="connect-continue"]')?.disabled === false);
        await policyPage.getByRole('button', { name: 'Cancel', exact: true }).click();
      }
      results.push({ width, check: 'SYNTHETIC explicit policy checkbox, holder receipt and cached connect-sheet reopen' });
      await policyPage.close();
      const started = await request('POST', `/api/workspaces/${wid}/channels/youtube/oauth/start`, { capability: 'publish' });
      const connected = await request('POST', `/api/workspaces/${wid}/channels/youtube/oauth/complete`, { state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'synthetic-code' });
      const cid = connected.connectionId;
      const agentStarted = await request('POST', `/api/workspaces/${wid}/channels/youtube/oauth/start`, {
        capability: 'autopilot', input: { authorizationLane: 'agentic', agenticConsent: true }
      });
      assert.notEqual(new URL(agentStarted.authorizeUrl).searchParams.get('client_id'), new URL(started.authorizeUrl).searchParams.get('client_id'));
      const agentConnected = await request('POST', `/api/workspaces/${wid}/channels/youtube/oauth/complete`, {
        state: new URL(agentStarted.authorizeUrl).searchParams.get('state'), code: 'synthetic-agentic-code'
      });
      assert.notEqual(agentConnected.connectionId, cid);
      assert.equal(agentConnected.providerAccountId, connected.providerAccountId);
      const overview = await request('GET', `/api/workspaces/${wid}/youtube/${encodeURIComponent(cid)}`);
      assert.equal(Object.keys(overview.capabilities).length, 37);
      assert.equal(overview.readiness.production, 'NOT READY');
      assert.equal(overview.capabilities.community_posts.state, 'UNSUPPORTED BY OFFICIAL API');
      assert.ok(Object.values(overview.capabilities).every(cap => cap.state !== 'READY'));
      const page = await context.newPage();
      currentPage = page;
      page.setDefaultTimeout(30000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => {
        if (message.type() === 'error' && /same key|Encountered two children|Hydration failed/.test(message.text())) errors.push('React reconciliation error');
      });
      await page.goto(base + '/app/youtube?channel=' + cid);
      await page.getByRole('heading', { name: 'YouTube creator', exact: true }).waitFor();
      const channelSelect = page.getByLabel('YouTube channel', { exact: true });
      // The heading renders before the authenticated channel request completes.
      // Wait for both independently authorized connections, not just the shell.
      await channelSelect.getByRole('option', { name: /\(manual authorization\)/ }).waitFor({ state: 'attached' });
      await channelSelect.getByRole('option', { name: /\(autopilot authorization\)/ }).waitFor({ state: 'attached' });
      const channelOptions = await page.getByLabel('YouTube channel', { exact: true }).locator('option').allTextContents();
      assert.ok(channelOptions.some(text => text.includes('(manual authorization)')));
      assert.ok(channelOptions.some(text => text.includes('(autopilot authorization)')));
      const agent = page.getByRole('region', { name: 'YouTube publishing agent', exact: true });
      await agent.getByRole('heading', { name: 'Library publishing plans', exact: true }).waitFor();
      assert.equal(await agent.getByRole('button', { name: 'Prepare reviewable plan', exact: true }).isEnabled(), false);
      const separate = agent.getByRole('button', { name: 'Prepare separate agentic Google consent', exact: true });
      assert.equal(await separate.isEnabled(), false);
      await agent.getByRole('checkbox', { name: 'Request separate Google authorization for owner-authorized Rafii publishing plans', exact: true }).check();
      await separate.click();
      const googleLink = agent.getByRole('link', { name: 'Continue to Google to select and authorize your channel', exact: true });
      await googleLink.waitFor();
      assert.equal(new URL(await googleLink.getAttribute('href')).searchParams.get('client_id'), 'local-agentic-synthetic.apps.googleusercontent.com');
      // Never navigate to Google: all grants and channels in this fixture are synthetic.
      await agent.getByLabel('Library video', { exact: true }).selectOption('b'.repeat(32));
      const planTitle = 'Synthetic bounded Library plan ' + width;
      await agent.getByLabel('Proposed title', { exact: true }).fill(planTitle);
      await agent.getByLabel('Proposed description', { exact: true }).fill('Synthetic planning fixture; no real provider upload.');
      await agent.getByLabel('Planned publication time', { exact: true }).fill(new Date(Date.now() + 2 * 3600000).toISOString().slice(0, 16));
      await agent.getByLabel('IANA time zone', { exact: true }).fill('UTC');
      await agent.getByLabel('Made for kids', { exact: true }).selectOption('no');
      await agent.getByLabel('Realistic altered or synthetic media', { exact: true }).selectOption('no');
      assert.deepEqual(await agent.getByLabel('Intended visibility', { exact: true }).locator('option').allTextContents(), ['Private (stays private)']);
      await agent.getByRole('checkbox', { name: 'Confirm rights to this exact Library video and metadata', exact: true }).check();
      const [planResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/agent/drafts') && response.request().method() === 'POST'),
        agent.getByRole('button', { name: 'Prepare reviewable plan', exact: true }).click()
      ]);
      assert.ok(planResponse.ok(), await planResponse.text());
      const plan = await planResponse.json();
      assert.equal(plan.executed, false);
      assert.equal(plan.providerVerified, false);
      assert.equal(plan.result.status, 'proposed');
      await agent.getByRole('checkbox', { name: `Include ${planTitle} in autopilot policy`, exact: true }).check();
      await agent.getByLabel('Maximum publications per day (1–20)', { exact: true }).fill('1');
      await agent.getByLabel('Authority expires (ISO date with UTC offset)', { exact: true }).fill(new Date(Date.now() + 31 * 86400000).toISOString());
      await agent.getByRole('button', { name: 'Review standing authority for 1 plans', exact: true }).click();
      await agent.getByRole('alert').filter({ hasText: /within 30 days/ }).waitFor();
      await agent.getByLabel('Authority expires (ISO date with UTC offset)', { exact: true }).fill(new Date(Date.now() + 86400000).toISOString());
      await agent.getByRole('button', { name: 'Review standing authority for 1 plans', exact: true }).click();
      const enableAutopilot = agent.getByRole('button', { name: 'Enable bounded autopilot', exact: true });
      await enableAutopilot.waitFor();
      assert.equal(await enableAutopilot.isEnabled(), false);
      await agent.getByRole('checkbox', { name: 'Authorize only the reviewed exact publishing plans within their limits until expiry or revocation', exact: true }).check();
      assert.equal(await enableAutopilot.isEnabled(), false, 'Missing Google/project approval must remain gated even after owner checkbox.');
      const agentView = await request('GET', `/api/workspaces/${wid}/youtube/${cid}/agent`);
      assert.equal(agentView.autopilotGate.canActivate, false);
      assert.equal(agentView.executionState, 'IMPLEMENTED BUT UNVERIFIED');
      assert.equal(agentView.policies[0].status, 'prepared');
      await page.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-agent-${width}.png`), fullPage: true });
      await page.getByRole('button', { name: 'Capabilities', exact: true }).click();
      await page.getByText('UNSUPPORTED BY OFFICIAL API', { exact: true }).first().waitFor();
      const capacity = page.getByRole('region', { name: 'Workspace publishing capacity', exact: true });
      await capacity.waitFor();
      assert.equal(await capacity.locator('[data-youtube-capacity]').count(), 3);
      await capacity.getByText(/These counters cover Rafii requests and do not show Google’s remaining allocation/).waitFor();
      assert.ok(await capacity.evaluate(element => element.getBoundingClientRect().right <= window.innerWidth + 1), 'Capacity controls must fit the mobile viewport.');
      await capacity.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-capacity-${width}.png`) });
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).count(), 0);
      assert.equal(await page.getByLabel('Visibility', { exact: true }).count(), 0);
      await page.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-capabilities-${width}.png`), fullPage: true });
      await page.getByRole('button', { name: 'Videos', exact: true }).click();
      await page.getByLabel('Video ID', { exact: true }).fill('abcdefghijk');
      const [inspection] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/read/videos') && response.request().method() === 'POST'),
        page.getByRole('button', { name: 'Inspect video processing', exact: true }).click()
      ]);
      assert.ok(inspection.ok(), 'The existing video must be inspected before its metadata review.');
      await page.locator('[data-youtube-resource-id="abcdefghijk"]').waitFor();
      const reviewedTitle = 'Exact reviewed local title ' + width + ' ' + principal.slice(0, 8);
      await page.getByLabel('Title', { exact: true }).fill(reviewedTitle);
      await page.getByLabel('Description', { exact: true }).fill('Exact reviewed local description\nhttps://example.com');
      const privacy = page.getByLabel('Visibility', { exact: true });
      assert.deepEqual(await privacy.locator('option').allTextContents(), ['Private']);
      await page.getByRole('button', { name: 'Review metadata change', exact: true }).click();
      await page.getByRole('heading', { name: 'Approve this exact YouTube action', exact: true }).waitFor();
      // Review is an HTTP/DB candidate; the provider still has its old title.
      const before = await request('POST', `/api/workspaces/${wid}/youtube/${encodeURIComponent(cid)}/read/videos`, { id: 'abcdefghijk' });
      assert.notEqual(before.items[0].snippet.title, reviewedTitle);
      const [approvedResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/approve') && response.request().method() === 'POST'),
        page.getByRole('button', { name: 'Approve exact action', exact: true }).click()
      ]);
      const approved = await approvedResponse.json();
      assert.equal(approved.status, 'verified', JSON.stringify({ error: approved.error, status: approved.status, verification: approved.receipt?.verification }));
      await page.getByText(/Edit video: verified/).waitFor();
      const after = await request('POST', `/api/workspaces/${wid}/youtube/${encodeURIComponent(cid)}/read/videos`, { id: 'abcdefghijk' });
      assert.equal(after.items[0].snippet.title, reviewedTitle);
      assert.deepEqual(after.items[0].snippet.tags, ['preserve']);
      await page.getByRole('button', { name: 'Review deletion', exact: true }).click();
      await page.getByLabel('Confirm resource ID', { exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).isEnabled(), false);
      await page.getByLabel('Confirm resource ID', { exact: true }).fill('wrong-video');
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).isEnabled(), false);
      await page.getByRole('button', { name: 'Discard review', exact: true }).click();
      await page.getByRole('button', { name: 'Live', exact: true }).click();
      const [streamsResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/read/streams')),
        page.getByRole('button', { name: 'List streams', exact: true }).click()
      ]);
      assert.ok(streamsResponse.ok());
      assert.equal((await streamsResponse.json()).items[0].id, 'local-stream');
      await page.getByRole('button', { name: /Local stream/ }).first().waitFor();
      assert.equal(await page.locator('body').textContent().then(text => text.includes('synthetic-private-stream-key')), false);
      await page.getByLabel('Stream ID', { exact: true }).fill('local-stream');
      const [configurationResponse] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/stream-configuration')),
        page.getByRole('button', { name: 'Read ingestion configuration after fresh owner sign-in', exact: true }).click()
      ]);
      assert.ok(configurationResponse.ok(), 'Fresh owner must be able to read an existing owned stream configuration.');
      await page.getByLabel('Stream key', { exact: true }).waitFor();
      assert.equal(await page.getByLabel('Stream key', { exact: true }).getAttribute('type'), 'password');
      await page.getByRole('button', { name: 'Clear private stream configuration', exact: true }).click();
      assert.equal(await page.getByLabel('Stream key', { exact: true }).count(), 0);
      const overflow = await page.evaluate(() => ({ width: window.innerWidth, document: document.documentElement.scrollWidth,
        elements: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > window.innerWidth + 1 && el.getBoundingClientRect().width > 0).slice(-12).map(el => ({ tag: el.tagName, width: Math.round(el.getBoundingClientRect().width), text: el.textContent.slice(0, 80) })) }));
      assert.ok(overflow.document <= overflow.width + 1, JSON.stringify(overflow));
      await page.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-live-${width}.png`), fullPage: true });
      // An arbitrary URL connection cannot resolve an account or carry over the reviewed action.
      await page.goto(base + '/app/youtube?channel=foreign-connection');
      await page.getByRole('heading', { name: 'Connect your creator channel', exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Approve exact action', exact: true }).count(), 0);
      assert.deepEqual(errors, []);
      results.push({ width, execution: 'cloud-synthetic', realGoogleE2E: false, independentCapabilities: 37,
        productionNotReady: true, officialUnsupportedCommunity: true, publicGateHeld: true, humanReviewBeforeWrite: true,
        distinctOAuthLaneConnections: true, explicitAgenticConsent: true, reviewableLibraryPlan: true,
        finiteThirtyDayAuthority: true, policyPreviewNotExecution: true, unapprovedAutopilotHeld: true,
        metadataPreserved: true, destructiveExactIdGuard: true, privateStreamKeyGuard: true, foreignConnectionRejected: true, workspaceCapacityVisible: true, noHorizontalOverflow: true });
      await context.close();
    }
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-browser.json'), JSON.stringify(proof('PASS'), null, 2) + '\n');
    console.log(JSON.stringify(proof('PASS')));
  } catch (error) {
    await currentPage?.screenshot({ path: resolve(out, 'CLOUD-SYNTHETIC-failure.png'), fullPage: true }).catch(() => {});
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-browser.json'), JSON.stringify({ ...proof('FAIL'), error: error.message }, null, 2) + '\n');
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
