/** Cloud-only fixture UI verification; real OAuth and Discord publication are excluded. */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {readFileSync, mkdirSync} = require('node:fs');
const {join} = require('node:path');
const {chromium} = require('playwright');
assert.equal(process.platform, 'linux'); assert.equal(process.env.CI, 'true');
const root = join(__dirname, '../..'), base = 'http://127.0.0.1:4439';
const template = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json')));
const input = JSON.parse(readFileSync(join(root, '.depot/discord-p0-ui.json')));
assert.equal(input.channel.displayState, 'Ready for posting', 'Use the actual channel-view projection.');
assert.equal(input.review.status, 'needs_review', 'Preparing a review must not simulate approval.');
const wid = input.job.manifest.workspaceId, channelId = input.channel.id;
const first = input.channel.discordDestinations.find(d => d.channelId === '7777777');
const second = input.channel.discordDestinations.find(d => d.channelId === '8888888');
assert.ok(first && second);
assert.equal(input.job.manifest.destinationId, first.id);
assert.equal(input.job.state, 'scheduled');
assert.ok(Number.isFinite(input.job.nextAt));
const nowSeconds = input.job.nextAt + 1;
assert.ok(nowSeconds < input.job.manifest.expiresAt);
const messageId = '4444444';
const messageUrl = `https://discord.com/channels/${first.guildId}/${first.channelId}/${messageId}`;
const frozenManifest = JSON.stringify(input.job.manifest);
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', '-p', '4439', '-H', '127.0.0.1'],
  {cwd: join(root, 'web'), env: process.env, stdio: ['ignore', 'pipe', 'pipe']});
app.stdout.on('data', c => process.stdout.write(c)); app.stderr.on('data', c => process.stderr.write(c));
(async () => {
  let browser, activePage; let stage = 'server-start'; const checks = [];
  try {
    let ready = false;
    for (let i = 0; i < 120; i++) {
      if (await fetch(base).then(r => r.status < 500).catch(() => false)) { ready = true; break; }
      await new Promise(r => setTimeout(r, 500));
    }
    assert.ok(ready); browser = await chromium.launch({headless: true});
    for (const width of [1280, 390]) {
      const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce', serviceWorkers: 'block'});
      await context.addCookies([{name: 'postriff_dev', value: '1', url: base}]);
      await context.addInitScript(({id, now}) => {
        // Advance only the fixture UI clock to the approved due time; never edit its frozen manifest.
        Date.now = () => now;
        localStorage.setItem('postriff-dev-principal', '00000000-0000-0000-0000-000000000001');
        localStorage.setItem('postriff-workspace', id);
        localStorage.setItem('postriff-onboarding:00000000-0000-0000-0000-000000000001', JSON.stringify({completed: {}, dismissed: {welcome: 1}, nudged: {}}));
      }, {id: wid, now: nowSeconds * 1000});
      let channel = {...structuredClone(input.channel), discordDestinations: [structuredClone(second)]};
      let snapshot = {...structuredClone(template.snapshot), state: {...structuredClone(template.snapshot.state),
        workspace: {...template.snapshot.state.workspace, id: wid},
        speaker: {...template.snapshot.state.speaker, activeRevision: null}, variants: [structuredClone(input.variant)],
        phase2: {...template.snapshot.state.phase2, channels: [channel], assets: [], jobs: [], reviews: []}}};
      let choices = [first, second].map(d => ({id: d.channelId, stableId: d.id, authorizedId: d.id === second.id ? d.id : null,
        guildId: d.guildId, guildName: d.guildName, name: d.channelName, kind: d.kind, selected: d.id === second.id}));
      let authorizations = 0, removals = 0, preparations = 0, approvals = 0, dispatches = 0, unexpectedMutations = 0;
      let approvalClicked = false, dispatchClicked = false, blockedOffOrigin = 0;
      let activeWorkStartedAt = null, activityRequests = 0; const activitySessions = new Map();
      const activityUrl = `${base}/api/workspaces/${wid}/time-savings/activity`;
      const page = await context.newPage(); activePage = page; page.setDefaultTimeout(30000);
      stage = 'authorize-channel-' + width;
      await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url()), p = url.pathname;
        if (url.origin !== base) { blockedOffOrigin++; return route.abort(); }
        if (!p.startsWith('/api/')) return route.continue();
        const send = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
        const rejectMutation = action => {
          unexpectedMutations++;
          console.error('RAFII_DISCORD_UNEXPECTED_MUTATION ' + JSON.stringify({stage, method: request.method(),
            path: p.replace(/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/gi, ':id').replace(/\/\d+(?=\/|$)/g, '/:id').slice(0, 180),
            action: action === undefined ? null : typeof action === 'string' && /^[A-Za-z0-9_:-]{1,64}$/.test(action) ? action : '[redacted]'}));
          return send({error: 'Unexpected synthetic action'}, 400);
        };
        if (request.url() === activityUrl && request.method() === 'POST') {
          // ScheduleDialog closes its draft timer after preparing review. Accept aggregate telemetry only.
          const beat = request.postDataJSON();
          assert.ok(beat && typeof beat === 'object' && !Array.isArray(beat));
          assert.deepEqual(Object.keys(beat).sort(), ['activeSeconds', 'clientSessionKey', 'sequence', 'taskKind', 'workflowKey',
            ...(Object.hasOwn(beat, 'closed') ? ['closed'] : [])].sort());
          assert.equal(beat.workflowKey, `variant:${input.variant.id}`); assert.equal(beat.taskKind, 'draft');
          assert.match(beat.clientSessionKey, /^[A-Za-z0-9_-]{16,64}$/);
          assert.ok(activeWorkStartedAt !== null);
          assert.ok(Number.isSafeInteger(beat.activeSeconds) && beat.activeSeconds > 0 && beat.activeSeconds <= 86400);
          assert.ok(beat.activeSeconds <= Math.ceil((performance.now() - activeWorkStartedAt) / 1000) + 1);
          assert.ok(Number.isSafeInteger(beat.sequence) && beat.sequence > 0 && beat.sequence <= 1000000);
          if (Object.hasOwn(beat, 'closed')) assert.equal(beat.closed, true);
          const previous = activitySessions.get(beat.clientSessionKey);
          assert.notEqual(previous?.closed, true, 'A closed timer cannot send another beat.');
          assert.equal(beat.sequence, (previous?.sequence ?? 0) + 1);
          assert.ok(beat.activeSeconds >= (previous?.activeSeconds ?? 0));
          activitySessions.set(beat.clientSessionKey, beat); activityRequests++;
          return send({accepted: true, activeSeconds: beat.activeSeconds, sequence: beat.sequence});
        }
        if (p === `/api/workspaces/${wid}/channels/${channelId}/destination` && request.method() === 'POST') {
          assert.equal(request.postDataJSON().destinationId, first.channelId); authorizations++;
          channel = {...channel, discordDestinations: [structuredClone(first), structuredClone(second)], defaultDestinationId: first.id};
          snapshot.state.phase2.channels = [channel]; snapshot.revision++;
          choices = choices.map(d => ({...d, authorizedId: d.stableId, selected: d.id === first.channelId}));
          return send({connectionId: channelId, destinationId: first.channelId});
        }
        if (p === `/api/workspaces/${wid}/channels/${channelId}/destinations/${first.id}` && request.method() === 'DELETE') {
          removals++; channel = {...channel, discordDestinations: channel.discordDestinations.map(d => d.id === first.id ? {...d, status: 'revoked'} : d)};
          snapshot.state.phase2.channels = [channel]; snapshot.revision++;
          choices = choices.map(d => d.stableId === first.id ? {...d, authorizedId: null, selected: false} : d);
          return send({connectionId: channelId, destinationId: first.id, status: 'revoked'});
        }
        if (p === `/api/workspaces/${wid}/actions` && request.method() === 'POST') {
          const {expectedRevision, action, payload} = request.postDataJSON();
          assert.equal(expectedRevision, snapshot.revision);
          if (action === 'p2_review') {
            assert.equal(approvals, 0); assert.equal(dispatches, 0);
            assert.equal(payload.channelId, channelId); assert.equal(payload.destinationId, first.id); preparations++;
            snapshot.state.phase2.reviews = [structuredClone(input.review)];
          } else if (action === 'p2_approve') {
            assert.equal(approvalClicked, true, 'Only the explicit human approval click can accept this fixture.');
            assert.equal(preparations, 1); assert.equal(approvals, 0); assert.equal(dispatches, 0);
            assert.equal(snapshot.state.phase2.jobs.length, 0);
            assert.deepEqual(payload, {reviewId: input.review.id, digest: input.review.digest, confirmed: true});
            approvals++;
            snapshot.state.phase2.reviews = [{...structuredClone(input.review), status: 'approved', jobId: input.job.id}];
            // The backend-produced approved job is returned only in response to the real client approval request.
            snapshot.state.phase2.jobs = [structuredClone(input.job)];
          } else {
            return rejectMutation(action);
          }
          snapshot.revision++; return send(snapshot);
        }
        if (p === `/api/workspaces/${wid}/jobs/${input.job.id}/execute` && request.method() === 'POST') {
          assert.equal(dispatchClicked, true); assert.equal(approvalClicked, true); assert.equal(approvals, 1); assert.equal(dispatches, 0);
          assert.deepEqual(request.postDataJSON(), {approvalDigest: input.job.approvalDigest});
          const scheduled = snapshot.state.phase2.jobs[0];
          assert.equal(scheduled.state, 'scheduled'); assert.equal(JSON.stringify(scheduled.manifest), frozenManifest);
          assert.equal(channel.defaultDestinationId, second.id, 'A changed default must not replace the approved target.');
          dispatches++;
          snapshot.state.phase2.jobs = [{...scheduled, state: 'provider_accepted',
            providerReference: `${first.channelId}/${messageId}`, url: messageUrl, verification: null,
            attempts: [{number: 1, startedAt: nowSeconds, endedAt: nowSeconds}],
            events: [...scheduled.events, {at: nowSeconds, state: 'provider_accepted', message: 'Synthetic Discord acceptance', execution: 'synthetic'}]}];
          snapshot.revision++; return send({processed: 1, execution: 'dev-synthetic', jobId: input.job.id});
        }
        if (request.method() !== 'GET') return rejectMutation();
        if (p === '/api/catalog') return send({authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {}});
        if (p === '/api/me') return send({userId: '00000000-0000-0000-0000-000000000001', displayName: 'Synthetic tester', preferences: {timeZone: 'UTC', locale: 'en'}, mfa: {}});
        if (p === '/api/workspaces') return send({workspaces: [{workspaceId: wid, membership: template.snapshot.membership, name: 'Synthetic Discord', plan: 'studio', memberCounts: {owner: 1}}]});
        if (p === `/api/workspaces/${wid}`) return send(snapshot);
        if (p.endsWith('/destinations')) return send({connectionId: channelId, scope: 'connection', destinations: choices});
        if (p.endsWith('/channels')) return send({channels: [{...channel, connectionState: 'publish_verified', canManage: true,
          capabilities: {identity: {level: 'Direct'}, publish: {level: 'Direct'}}}], providers: [{id: 'discord', platform: 'Discord', configured: true,
          connectReady: true, hasDestinations: true, destinationScope: 'connection', destinationLabel: 'Channel', capabilities: {identity: true, publish: true}}]});
        if (p.endsWith('/usage')) return send({entitlement: {planTermsId: 'synthetic-studio', writingBatchesRemaining: 1, mediaCreditsRemaining: 0,
          connectedAccounts: 10, members: 1, storageMb: 100, resetsAt: null, source: 'fixture', version: 1}, subscription: null, budget: null,
          overage: 'disabled', ledger: [], planTerms: [], lifecycle: {status: 'active', canPublish: true}, membership: template.snapshot.membership});
        if (p.endsWith('/memory')) return send(template.memory);
        if (p.endsWith('/memory/proposals')) return send({pending: [], recent: [], learning: {items: []}});
        return send({error: 'Unhandled synthetic read'}, 404);
      });
      await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
      await page.getByRole('button', {name: 'Authorize Discord channel', exact: true}).click();
      await page.getByRole('button').filter({hasText: `${first.guildName} · ${first.channelName} (${first.channelId})`}).click();
      await page.getByText('Channel authorized and set as the default.', {exact: false}).waitFor();
      await page.keyboard.press('Escape'); assert.equal(authorizations, 1);
      stage = 'prepare-review-' + width; activeWorkStartedAt = performance.now();
      // A passive review must be future-dated; advance to the unchanged approved due time only after it exists.
      await page.evaluate(now => { Date.now = () => now; }, (input.job.manifest.timing.timestamp - 60) * 1000);
      await page.getByRole('link', {name: 'Queue', exact: true}).first().click();
      await page.getByRole('button', {name: 'Schedule a draft', exact: true}).click();
      const composer = page.getByRole('dialog');
      await composer.getByRole('combobox', {name: 'Draft', exact: true}).selectOption(input.variant.id);
      await composer.getByRole('combobox', {name: 'Account', exact: true}).selectOption(channelId);
      assert.equal(await composer.getByRole('button', {name: 'Prepare review', exact: true}).isDisabled(), true);
      await composer.getByRole('combobox', {name: 'Discord server and channel', exact: true}).selectOption(first.id);
      const destinationLabel = (await composer.getByRole('combobox', {name: 'Discord server and channel', exact: true}).locator('option:checked').innerText()).trim();
      assert.equal(destinationLabel, `${first.guildName} · ${first.channelName}`, 'The closed destination field must show the selected server and channel.');
      assert.equal(destinationLabel.includes(first.id), false, 'The authorization ID remains a payload value, never the selected destination label.');
      assert.match(await composer.locator('[data-discord-target]').innerText(), /555555.*7777777/);
      await composer.locator('input[type="datetime-local"]').fill(input.job.manifest.timing.local);
      await composer.getByRole('checkbox', {name: /I have the rights/}).check();
      const timeField = composer.locator('input[type="datetime-local"]');
      await timeField.fill('2000-01-01T00:00');
      assert.equal(await composer.getByRole('button', {name: 'Prepare review', exact: true}).isDisabled(), true, 'An expired local time cannot prepare a review.');
      assert.equal(preparations, 0);
      await timeField.fill('');
      assert.equal(await composer.getByRole('button', {name: 'Prepare review', exact: true}).isDisabled(), true, 'An empty time cannot prepare a review.');
      await timeField.fill(input.job.manifest.timing.local);
      assert.match(await composer.locator('[data-review-time]').innerText(), new RegExp(input.job.manifest.timing.local.replace('T', ' ')));
      assert.equal(await composer.locator('[data-review-time] time').getAttribute('datetime'), new Date(input.job.manifest.timing.timestamp * 1000).toISOString());
      assert.equal(await composer.getByRole('button', {name: 'Prepare review', exact: true}).isEnabled(), true);
      // Keep the field unchanged while its deadline passes, and click before the timer can render.
      await page.evaluate(now => {
        Date.now = () => now;
        document.querySelector('[data-tour="schedule-prepare"]').click();
      }, (input.job.manifest.timing.timestamp + 1) * 1000);
      assert.equal(preparations, 0, 'The immediate submission guard refuses a just-expired form.');
      await page.waitForFunction(() => document.querySelector('[data-tour="schedule-prepare"]')?.disabled === true);
      assert.equal(await timeField.inputValue(), input.job.manifest.timing.local, 'Expiry does not silently change the proposed time.');
      await page.evaluate(now => { Date.now = () => now; }, (input.job.manifest.timing.timestamp - 60) * 1000);
      await page.waitForFunction(() => document.querySelector('[data-tour="schedule-prepare"]')?.disabled === false);
      // Whole active seconds must be positive so cleanup telemetry is covered independent of click speed.
      await page.waitForTimeout(1100);
      const activityClosed = page.waitForResponse(response => response.url() === activityUrl &&
        response.request().method() === 'POST' && response.request().postDataJSON().closed === true);
      await composer.getByRole('button', {name: 'Prepare review', exact: true}).click();
      await page.locator('[data-discord-frozen-target]').first().waitFor(); assert.equal(preparations, 1);
      assert.equal((await activityClosed).status(), 200);
      assert.equal(activitySessions.size, 1); assert.equal([...activitySessions.values()][0].closed, true);
      assert.equal(approvals, 0); assert.equal(dispatches, 0); assert.equal(snapshot.state.phase2.jobs.length, 0);
      assert.equal(await page.getByRole('button', {name: 'Publish approved post', exact: true}).count(), 0);
      stage = 'explicit-human-approval-' + width;
      await page.evaluate(now => { Date.now = () => now; }, nowSeconds * 1000);
      approvalClicked = true;
      await page.getByRole('button', {name: 'Approve & schedule', exact: true}).click();
      await page.getByRole('button', {name: 'Approve & schedule', exact: true}).waitFor({state: 'detached'});
      assert.equal(approvals, 1); assert.equal(dispatches, 0);
      assert.equal(snapshot.state.phase2.jobs[0].state, 'scheduled');
      assert.equal(JSON.stringify(snapshot.state.phase2.jobs[0].manifest), frozenManifest);
      channel.defaultDestinationId = second.id; snapshot.revision++;
      stage = 'frozen-approved-target-' + width;
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.getByRole('button', {name: 'Preview the Discord post', exact: true}).first().click();
      assert.match(await page.locator('[data-discord-frozen-target]').first().innerText(), /7777777/);
      await page.keyboard.press('Escape');
      await page.goto(base + '/app/queue?job=' + encodeURIComponent(input.job.id), {waitUntil: 'domcontentloaded'});
      const receipt = page.locator('[aria-label="Publication receipt"]');
      await receipt.waitFor();
      assert.equal(await receipt.getByRole('link').count(), 0);
      assert.match(await page.getByRole('dialog').locator('[data-discord-frozen-target]').first().innerText(), /555555.*7777777/);
      assert.equal(dispatches, 0);
      stage = 'synthetic-approved-dispatch-' + width;
      dispatchClicked = true;
      await page.getByRole('button', {name: 'Publish approved post', exact: true}).click();
      const permalink = receipt.getByRole('link', {name: 'Open Discord message', exact: true});
      await permalink.waitFor(); assert.equal(dispatches, 1);
      assert.equal(await permalink.getAttribute('href'), messageUrl);
      assert.match(await receipt.innerText(), /Accepted by Discord\. Verification is pending\./);
      assert.equal(await receipt.getByText(/Verified ·/).count(), 0);
      assert.equal(await page.getByRole('button', {name: 'Publish approved post', exact: true}).count(), 0);
      // Simulate the existing worker's later provider-lookup projection, without any Discord request.
      const accepted = snapshot.state.phase2.jobs[0];
      snapshot.state.phase2.jobs = [{...accepted, state: 'verified', verification: {method: 'provider_lookup', at: nowSeconds + 1},
        events: [...accepted.events, {at: nowSeconds + 1, state: 'verified', message: 'Synthetic provider lookup', execution: 'synthetic'}]}];
      assert.equal(JSON.stringify(snapshot.state.phase2.jobs[0].manifest), frozenManifest); snapshot.revision++;
      stage = 'synthetic-verified-receipt-' + width;
      await page.reload({waitUntil: 'domcontentloaded'});
      await receipt.getByText(/Verified · provider lookup/).waitFor();
      assert.equal(await permalink.getAttribute('href'), messageUrl);
      assert.equal(await receipt.getByText(/Verification is pending/).count(), 0);
      assert.equal(await page.getByRole('button', {name: 'Publish approved post', exact: true}).count(), 0);
      stage = 'remove-channel-' + width;
      await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
      await page.getByRole('button', {name: 'Authorize Discord channel', exact: true}).click();
      await page.getByRole('button', {name: 'Remove channel authorization', exact: true}).first().click();
      await page.getByText('Channel authorization removed. Pending posts to this channel are held.', {exact: true}).waitFor(); assert.equal(removals, 1);
      assert.equal(channel.discordDestinations.find(d => d.id === first.id).status, 'revoked');
      assert.equal(choices.find(d => d.stableId === first.id).authorizedId, null);
      assert.equal(approvals, 1); assert.equal(dispatches, 1);
      assert.equal(unexpectedMutations, 0); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      checks.push({width, explicitDestinationSelection: true, selectedDestinationLabel: true, authorizationRefresh: true, explicitHumanApproval: true,
        approvalRequests: approvals, syntheticDispatchRequests: dispatches, frozenTargetAfterDefaultEdit: true,
        scheduledReceipt: true, acceptedReceiptPendingVerification: true, verifiedProviderLookupReceipt: true,
        boundPermalinkInspectedWithoutNavigation: true, localDestinationRemoval: true, activityRequests, closedDraftTimer: true, blockedOffOrigin,
        realDiscordRequests: 0, realDiscordAcceptance: 'NOT_RUN'});
      mkdirSync(join(root, '.depot/discord-p0-evidence'), {recursive: true});
      await page.screenshot({path: join(root, `.depot/discord-p0-evidence/channels-${width}.png`), fullPage: true});
      await context.close();
    }
    console.log(JSON.stringify({status: 'PASS', execution: 'cloud-browser-synthetic-api', checks}));
  } catch (error) {
    if (activePage && !activePage.isClosed()) {
      try {
        console.error('RAFII_DISCORD_BROWSER_FAILURE ' + JSON.stringify({stage,
          url: activePage.url(), buttons: (await activePage.getByRole('button').allTextContents()).slice(0, 25).map(s => s.trim().slice(0, 120)),
          heading: (await activePage.getByRole('heading').allTextContents()).slice(0, 10)}));
      } catch (_) { /* Diagnostics cannot replace the original failure. */ }
    }
    throw error;
  } finally {
    if (browser) await browser.close(); app.kill('SIGTERM');
  }
})().catch(error => {console.error(error); process.exitCode = 1; app.kill('SIGTERM');});
