/** Cloud-only P1/P2 UI contract. All API writes are intercepted fixture changes. */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {chromium} = require('playwright');
assert.equal(process.platform, 'linux'); assert.equal(process.env.CI, 'true');
const root = join(__dirname, '../..'), base = 'http://127.0.0.1:4439';
const template = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json')));
const fixture = JSON.parse(readFileSync(join(root, '.depot/discord-p0-ui.json')));
const wid = fixture.job.manifest.workspaceId;
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', '-p', '4439', '-H', '127.0.0.1'],
  {cwd: join(root, 'web'), env: process.env, stdio: ['ignore', 'pipe', 'pipe']});
app.stdout.on('data', c => process.stdout.write(c)); app.stderr.on('data', c => process.stderr.write(c));
(async () => {
  let browser, activePage; let stage = 'start'; const checks = [], failures = [];
  try {
    let ready = false;
    for (let i = 0; i < 120; i++) {
      if (await fetch(base).then(r => r.status < 500).catch(() => false)) { ready = true; break; }
      await new Promise(r => setTimeout(r, 500));
    }
    assert.ok(ready); browser = await chromium.launch({headless: true});
    for (const width of [1280, 390]) {
      const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce', serviceWorkers: 'block'});
      try {
        await context.addCookies([{name: 'postriff_dev', value: '1', url: base}]);
        await context.addInitScript(id => {
          localStorage.setItem('postriff-dev-principal', '00000000-0000-0000-0000-000000000001');
          localStorage.setItem('postriff-workspace', id);
          localStorage.setItem('postriff-onboarding:00000000-0000-0000-0000-000000000001', JSON.stringify({completed: {}, dismissed: {welcome: 1}, nudged: {}}));
        }, wid);
        let identities = [structuredClone(fixture.connections.identity)];
        const starts = []; let disconnects = 0, unexpectedMutations = 0;
        const page = await context.newPage(); activePage = page; page.setDefaultTimeout(30000);
        await context.route('**/*', async route => {
          const request = route.request(), url = new URL(request.url()), path = url.pathname;
          if (url.origin !== base) return route.abort();
          if (!path.startsWith('/api/')) return route.continue();
          const send = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
          if (path === `/api/workspaces/${wid}/channels/discord/oauth/start` && request.method() === 'POST') {
            const body = request.postDataJSON(); starts.push(body);
            const install = body.input.discordPurpose === 'installation';
            assert.equal(body.capability, install ? 'publish' : 'identity');
            if (install) {
              assert.equal(body.input.identityConnectionId, identities[0].id);
              assert.equal(body.input.guildId, fixture.connections.guilds[1].id);
            } else assert.equal(body.input.discoverGuilds, true);
            const scopes = install ? ['identify', 'bot'] : ['identify', 'guilds'];
            const params = new URLSearchParams({client_id: fixture.job.manifest.discord.target.applicationId,
              response_type: 'code', state: 'synthetic-state-xxxxxxxxxxxxxxxxxxxxxxxx', scope: scopes.join(' '),
              ...(install ? {guild_id: body.input.guildId, disable_guild_select: 'true'} : {})});
            return send({transactionId: 'synthetic-transaction', provider: 'discord', platform: 'Discord',
              capability: body.capability, scopes, discordPurpose: body.input.discordPurpose,
              authorizeUrl: 'https://discord.com/oauth2/authorize?' + params, expiresAt: 9999999999,
              permissionExplanation: install ? 'Install the bot, then authorize each channel.' : 'Link identity with the selected server-list permission.'}, 201);
          }
          if (path === `/api/workspaces/${wid}/discord/identities/${identities[0].id}/disconnect` && request.method() === 'POST') {
            disconnects++; identities = identities.map(x => ({...x, status: 'disconnected'}));
            return send({disconnected: true, note: 'Disconnected locally. The shared bot stays installed.'});
          }
          if (request.method() !== 'GET') { unexpectedMutations++; return send({error: 'Unexpected fixture mutation'}, 400); }
          if (path.endsWith('/guilds')) return send({identityConnectionId: identities[0].id, guilds: fixture.connections.guilds});
          if (path.endsWith('/channels')) return send({channels: [], discordIdentities: identities, providers: [{id: 'discord', platform: 'Discord', configured: true,
            connectReady: true, productionReviewed: true, discordConnectionsV2: true, capabilities: {identity: true, publish: true}, setupIssues: []}]});
          if (path === '/api/catalog') return send({authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {}});
          if (path === '/api/me') return send({userId: '00000000-0000-0000-0000-000000000001', displayName: 'Synthetic tester', preferences: {timeZone: 'UTC', locale: 'en'}, mfa: {}});
          if (path === '/api/workspaces') return send({workspaces: [{workspaceId: wid, membership: template.snapshot.membership, name: 'Synthetic Discord', plan: 'studio', memberCounts: {owner: 1}}]});
          if (path === `/api/workspaces/${wid}`) return send({...template.snapshot, state: {...template.snapshot.state, workspace: {...template.snapshot.state.workspace, id: wid}, phase2: {...template.snapshot.state.phase2, channels: []}}});
          if (path.endsWith('/memory')) return send(template.memory);
          if (path.endsWith('/memory/proposals')) return send({pending: [], recent: [], learning: {items: []}});
          return send({error: 'Unhandled synthetic read'}, 404);
        });
        stage = 'identity-' + width;
        await page.goto(base + '/app/channels?connect=discord&capability=identity', {waitUntil: 'domcontentloaded'});
        await page.getByRole('checkbox', {name: 'Allow Rafii to list servers I manage for server selection', exact: true}).check();
        await page.getByRole('button', {name: 'Continue', exact: true}).click();
        const authorize = page.getByRole('link', {name: 'Continue to Discord', exact: false});
        await authorize.waitFor(); assert.equal(new URL(await authorize.getAttribute('href')).searchParams.get('scope'), 'identify guilds');
        await page.getByRole('button', {name: 'Back', exact: true}).click();
        stage = 'installation-' + width;
        await page.getByRole('button', {name: 'Authorize Discord server', exact: true}).click();
        assert.equal(await page.getByRole('button', {name: 'Continue', exact: true}).isDisabled(), true);
        await page.getByRole('combobox', {name: 'Discord identity', exact: true}).selectOption(identities[0].id);
        await page.getByRole('button', {name: 'Load permitted Discord servers', exact: true}).click();
        await page.getByRole('combobox', {name: 'Discord server', exact: true}).selectOption(fixture.connections.guilds[1].id);
        await page.getByRole('button', {name: 'Continue', exact: true}).click();
        await authorize.waitFor(); assert.equal(new URL(await authorize.getAttribute('href')).searchParams.get('guild_id'), fixture.connections.guilds[1].id);
        await page.getByRole('button', {name: 'Back', exact: true}).click();
        stage = 'local-disconnect-' + width;
        await page.getByRole('button', {name: 'Disconnect identity from workspace', exact: true}).click();
        await page.getByText(/Synthetic identity.*disconnected/).first().waitFor();
        assert.equal(starts.length, 2); assert.equal(disconnects, 1); assert.equal(unexpectedMutations, 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        checks.push({width, separateIdentityAndInstallation: true, optionalGuildListConsent: true, explicitGuildSelection: true,
          localIdentityDisconnect: true, frozenApprovalSuite: 'separate P0 browser', realDiscordAcceptance: 'NOT_RUN'});
      } catch (error) {
        failures.push({width, stage, error: String(error).slice(0, 1200)});
        console.error('RAFII_DISCORD_CONNECTIONS_BROWSER_VIEWPORT_FAILURE ' + JSON.stringify(failures.at(-1)));
      } finally { await context.close(); }
    }
    assert.equal(failures.length, 0, JSON.stringify(failures));
    console.log('RAFII_DISCORD_CONNECTIONS_BROWSER_JSON ' + JSON.stringify({status: 'PASS', execution: 'cloud-browser-synthetic-api', checks}));
  } catch (error) {
    if (activePage && !activePage.isClosed()) {
      try { console.error('RAFII_DISCORD_CONNECTIONS_BROWSER_FAILURE ' + JSON.stringify({stage,
        url: activePage.url(), buttons: (await activePage.getByRole('button').allTextContents()).slice(0, 25).map(x => x.trim().slice(0, 120))})); } catch (_) {}
    }
    throw error;
  } finally { if (browser) await browser.close(); app.kill('SIGTERM'); }
})().catch(error => {console.error(error); process.exitCode = 1; app.kill('SIGTERM');});
