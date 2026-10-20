/** Running-app browser candidate. All APIs synthetic; every off-origin request blocked. */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {readFileSync, mkdirSync, writeFileSync, existsSync} = require('node:fs');
const {join} = require('node:path');
const {chromium} = require('playwright');
assert.equal(process.platform, 'linux');
assert.equal(process.env.CI, 'true');
assert.equal(process.env.RAFII_DISCORD_SYNTHETIC_FENCE, '1');
const root = join(__dirname, '../..'), base = 'http://127.0.0.1:4439';
const input = JSON.parse(readFileSync(join(root, '.depot/discord-p0-ui.json')));
const template = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json')));
const wid = input.job.manifest.workspaceId;
const actor = '00000000-0000-0000-0000-000000000001';
for (const name of ['.env', '.env.local', '.env.development', '.env.development.local']) {
  assert.equal(existsSync(join(root, 'web', name)), false, 'The isolated synthetic app must not load local environment files.');
}
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', '-H', '127.0.0.1', '-p', '4439'], {
  cwd: join(root, 'web'), stdio: ['ignore', 'pipe', 'pipe'], env: {PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR,
    CI: 'true', NODE_ENV: 'development', DO_NOT_TRACK: '1', NEXT_TELEMETRY_DISABLED: '1', OPENUI_TELEMETRY_DISABLED: '1',
    NEXT_PUBLIC_APP_URL: base, POSTRIFF_DEV_SSR: '1', NEXT_PUBLIC_SUPABASE_URL: '', NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: '',
    POSTRIFF_API_ORIGIN: 'http://127.0.0.1:4438', NEXT_PUBLIC_SENTRY_DISABLED: '1'}
});
let serverTail = '';
for (const stream of [app.stdout, app.stderr]) stream.on('data', b => { serverTail = (serverTail + b).slice(-5000); });
async function until(check) {
  for (let i = 0; i < 100; i++) { if (await check()) return; await new Promise(r => setTimeout(r, 100)); }
  throw Error('Synthetic browser condition timed out');
}
(async () => {
  let browser, stage = 'startup'; const checks = [];
  try {
    await until(() => fetch(base).then(r => r.status < 500).catch(() => false));
    browser = await chromium.launch({headless: true});
    for (const width of [390, 1280]) {
      const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce', serviceWorkers: 'block', locale: 'en-US'});
      await context.addCookies([{name: 'postriff_dev', value: '1', url: base}]);
      await context.addInitScript(({wid, actor}) => {
        localStorage.setItem('postriff-dev-principal', actor); localStorage.setItem('postriff-workspace', wid);
        localStorage.setItem('postriff-onboarding:' + actor, JSON.stringify({completed: {}, dismissed: {welcome: 1}, nudged: {}}));
      }, {wid, actor});
      let identities = [{...input.connections.identity, discoverGuilds: false},
        {...input.connections.identity, id: 'second-identity', account: 'Second synthetic identity', userId: '818181', discoverGuilds: true}];
      let channels = [], snapshot = structuredClone(template.snapshot), starts = [], discoveries = 0, callbacks = 0, unexpected = 0;
      let holdStart = false, releaseStart, wrongSubject = false, localUnlinks = 0;
      const provider = {id: 'discord', platform: 'Discord', configured: true, connectReady: true, productionReviewed: true,
        discordConnectionsV2: true, capabilities: {identity: true, publish: true}, setupIssues: [],
        discordModes: {webhook: {enabled: false, status: 'unavailable'}, userInstall: {enabled: false, status: 'unavailable'}}};
      snapshot.state.workspace.id = wid;
      snapshot.state.phase2 = {...snapshot.state.phase2, channels, jobs: [], reviews: [], assets: []};
      await context.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url()), path = url.pathname;
        if (url.origin !== base) return route.abort();
        if (!path.startsWith('/api/')) return route.continue();
        const send = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
        if (path.endsWith('/channels/discord/oauth/start') && req.method() === 'POST') {
          const body = req.postDataJSON(); starts.push(body);
          assert.equal(body.input.discordPurpose, 'identity'); assert.equal(body.capability, 'identity');
          if (holdStart) await new Promise(resolve => { releaseStart = resolve; });
          const scopes = body.input.discoverGuilds ? ['identify', 'guilds'] : ['identify'];
          return send({transactionId: 'synthetic-state-transaction', provider: 'discord', platform: 'Discord', scopes,
            discordPurpose: 'identity', capability: 'identity', expiresAt: 9999999999,
            authorizeUrl: 'https://discord.com/oauth2/authorize?' + new URLSearchParams({client_id: '1234567', scope: scopes.join(' '), state: 'synthetic-state-xxxxxxxxxxxxxxxxxxxx'}),
            permissionExplanation: 'Synthetic official OAuth; this does not authorize publishing as you.'}, 201);
        }
        if (path.endsWith('/channels/discord/oauth/complete') && req.method() === 'POST') {
          callbacks++; assert.equal(req.postDataJSON().iss, 'https://discord.com');
          if (wrongSubject) return send({error: 'Reconnect the original Discord identity.', code: 'discord_connection_required'}, 409);
          return send({connected: true, connectionId: identities[0].id, discordPurpose: 'identity', missingScopes: []});
        }
        if (req.method() !== 'GET') { unexpected++; return send({error: 'Unexpected synthetic mutation'}, 400); }
        if (path.endsWith('/guilds')) { discoveries++; return send({identityConnectionId: 'wrong-subject', guilds: [{id: '999999', name: 'MUST NOT APPEAR'}]}); }
        if (path.endsWith('/channels')) return send({channels, providers: [provider], discordIdentities: identities});
        if (path === '/api/catalog') return send({authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {}});
        if (path === '/api/me') return send({userId: actor, displayName: 'Synthetic tester', preferences: {timeZone: 'UTC', locale: 'en'}, mfa: {}});
        if (path === '/api/workspaces') return send({workspaces: [{workspaceId: wid, name: 'Synthetic Discord', plan: 'studio', membership: template.snapshot.membership, memberCounts: {owner: 1}}]});
        if (path === `/api/workspaces/${wid}`) return send(snapshot);
        if (path.includes('/discord/private-review/')) return send({error: 'This private identity is not linked to the current actor.'}, 403);
        if (path.endsWith('/memory')) return send(template.memory);
        if (path.endsWith('/memory/proposals')) return send({pending: [], recent: [], learning: {items: []}});
        return send({error: 'Unhandled synthetic read'}, 404);
      });
      const page = await context.newPage(); page.setDefaultTimeout(30000);
      stage = 'identity-no-server-' + width;
      await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
      await page.getByRole('heading', {name: 'Personal Discord accounts', exact: true}).waitFor();
      assert.equal(channels.length, 0);
      await page.getByRole('button', {name: 'Manage personal account', exact: true}).first().focus();
      await page.keyboard.press('Enter');
      const sheet = page.getByRole('dialog');
      assert.equal(await sheet.getByRole('button', {name: 'Incoming webhook', exact: true}).isDisabled(), true);
      assert.equal(await sheet.getByRole('button', {name: 'User-installed app', exact: true}).isDisabled(), true);
      stage = 'official-scope-upgrade-' + width;
      await sheet.getByRole('button', {name: 'Authorize Discord server', exact: true}).click();
      await sheet.getByText('Server-list permission is needed to choose a server. Your personal account is already linked.', {exact: true}).waitFor();
      assert.equal(discoveries, 0);
      assert.equal(await sheet.getByRole('button', {name: 'Load permitted Discord servers', exact: true}).isDisabled(), true);
      await sheet.getByRole('button', {name: 'Reconnect with server-list permission', exact: true}).focus();
      await page.keyboard.press('Enter');
      assert.equal(await sheet.getByRole('checkbox', {name: 'Allow Rafii to list servers I manage for server selection', exact: true}).isChecked(), true);
      assert.equal(starts.length, 0, 'scope upgrade cannot silently start or authorize OAuth');
      holdStart = true;
      await sheet.getByRole('button', {name: 'Continue', exact: true}).click();
      await until(() => Boolean(releaseStart));
      assert.equal(await sheet.getByRole('button', {name: 'Authorize Discord server', exact: true}).isDisabled(), true);
      await page.keyboard.press('Escape');
      await page.getByRole('button', {name: 'Manage personal account', exact: true}).last().click();
      holdStart = false; releaseStart();
      await sheet.getByRole('button', {name: 'Authorize Discord server', exact: true}).click();
      assert.equal(await sheet.getByRole('link', {name: /Continue to Discord/}).count(), 0, 'late OAuth response must not populate a new connection context');
      stage = 'wrong-discovery-subject-' + width;
      await sheet.getByRole('button', {name: 'Load permitted Discord servers', exact: true}).click();
      await sheet.getByText(/changed during server discovery|Reload|different identity|changed/i).first().waitFor();
      assert.equal(await sheet.getByRole('option', {name: /MUST NOT APPEAR/}).count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.addScriptTag({path: require.resolve('axe-core/axe.min.js')});
      const accessibility = await page.evaluate(() => axe.run({include: [['[aria-label="Discord connection steps"]']]}, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}}));
      assert.deepEqual(accessibility.violations.map(v => v.id), []);
      stage = 'callback-wrong-subject-' + width;
      wrongSubject = true;
      await page.goto(base + '/channels/connect?provider=discord&state=synthetic-state-xxxxxxxxxxxxxxxxxxxx&code=wrong-subject&iss=https%3A%2F%2Fdiscord.com');
      await page.getByText('Reconnect the original Discord identity.', {exact: true}).waitFor();
      wrongSubject = false;
      await page.goto(base + '/channels/connect?provider=discord&state=synthetic-state-yyyyyyyyyyyyyyyyyyyy&code=identity-success&iss=https%3A%2F%2Fdiscord.com');
      await page.waitForURL('**/app/channels?connected=*');
      await page.locator('#discord-identity-' + identities[0].id).waitFor();
      assert.equal(callbacks, 2);
      stage = 'explicit-bot-webhook-composer-sender-' + width;
      const bot = {...structuredClone(input.channel), discordConnectionKind: 'installation'};
      const hook = {...structuredClone(input.channel), id: 'discord-webhook-synthetic', account: 'Synthetic webhook', discordConnectionKind: 'webhook', scopes: ['identify', 'webhook.incoming']};
      hook.discordDestinations = hook.discordDestinations.map(d => ({...d, id: d.id + '-webhook', connectionId: hook.id, senderKind: 'webhook', credentialKind: 'webhook', webhookId: '66112233', botUserId: undefined}));
      channels = [bot, hook]; snapshot.state.phase2.channels = channels;
      snapshot.state.variants = [input.variant]; snapshot.state.speaker.activeRevision = null;
      await page.goto(base + '/app/queue');
      await page.getByRole('button', {name: 'Schedule a draft', exact: true}).click();
      const composer = page.getByRole('dialog');
      await composer.getByRole('combobox', {name: 'Draft', exact: true}).selectOption(input.variant.id);
      await composer.getByRole('combobox', {name: 'Account', exact: true}).selectOption(bot.id);
      assert.match(await composer.locator('[data-discord-sender]').innerText(), /Sender: Rafii bot/);
      await composer.getByRole('combobox', {name: 'Account', exact: true}).selectOption(hook.id);
      assert.match(await composer.locator('[data-discord-sender]').innerText(), /Sender: authorized Rafii webhook/);
      assert.equal(await composer.getByRole('option', {name: identities[0].account, exact: true}).count(), 0);
      assert.equal(unexpected, 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      mkdirSync(join(root, '.depot/discord-multimode-browser'), {recursive: true});
      await page.screenshot({path: join(root, `.depot/discord-multimode-browser/${width}.png`), fullPage: true});
      checks.push({width, identityNoServer: true, officialScopeUpgrade: true, staleResponse: true, wrongSubject: true,
        callback: true, sender: true, unavailableModes: true, keyboard: true, accessibility: 'axe WCAG2A/AA new section', unexpectedMutations: unexpected});
      await context.close();
    }
    writeFileSync(join(root, '.depot/discord-multimode-browser/results.json'), JSON.stringify({execution: 'synthetic-running-browser', checks, realDiscord: 'NOT_RUN'}, null, 2));
    console.log('RAFII_DISCORD_MULTIMODE_BROWSER ' + JSON.stringify({status: 'PASS', checks}));
  } catch (error) {
    console.error('RAFII_DISCORD_MULTIMODE_BROWSER_FAILED ' + JSON.stringify({stage, error: String(error).slice(0, 500)}));
    // server output is bounded but deliberately not printed: route URLs may contain OAuth state.
    process.exitCode = 1;
  } finally { if (browser) await browser.close(); app.kill('SIGTERM'); }
})();
