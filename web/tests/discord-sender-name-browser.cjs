/** Actual app UI, synthetic APIs only. No Discord credentials or provider IO. */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {readFileSync, mkdirSync, existsSync} = require('node:fs');
const {join} = require('node:path');
const {chromium} = require('playwright');
assert.equal(process.platform, 'linux');
assert.equal(process.env.CI, 'true');
assert.equal(process.env.RAFII_DISCORD_SYNTHETIC_FENCE, '1');
const root = join(__dirname, '../..'), base = 'http://127.0.0.1:4449';
const input = JSON.parse(readFileSync(join(root, '.depot/discord-p0-ui.json')));
const template = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json')));
const packs = JSON.parse(readFileSync(join(root, 'web/src/lib/channels/discord-copy.json')));
const wid = input.job.manifest.workspaceId, actor = '00000000-0000-0000-0000-000000000001';
for (const name of ['.env', '.env.local', '.env.development', '.env.development.local']) {
  assert.equal(existsSync(join(root, 'web', name)), false, 'Isolated browser must not load local environment files');
}
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', '--webpack', '-H', '127.0.0.1', '-p', '4449'], {
  cwd: join(root, 'web'), stdio: ['ignore', 'pipe', 'pipe'], env: {PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR,
    CI: 'true', NODE_ENV: 'development', NEXT_TELEMETRY_DISABLED: '1', OPENUI_TELEMETRY_DISABLED: '1',
    NEXT_PUBLIC_APP_URL: base, POSTRIFF_DEV_SSR: '1', NEXT_PUBLIC_SUPABASE_URL: '', NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: '',
    POSTRIFF_API_ORIGIN: 'http://127.0.0.1:4448', NEXT_PUBLIC_SENTRY_DISABLED: '1', POSTRIFF_DIST_DIR: '.next-sender-ui'}
});
let tail = '';
for (const stream of [app.stdout, app.stderr]) stream.on('data', b => { tail = (tail + b).slice(-5000); });
async function until(check) {
  for (let i = 0; i < 160; i++) { if (await check()) return; await new Promise(r => setTimeout(r, 250)); }
  throw Error('Synthetic browser condition timed out');
}
(async () => {
  let browser, browserVersion, stage = 'startup';
  const checks = [];
  try {
    await until(() => fetch(base).then(r => r.status < 500).catch(() => false));
    const launchOptions = {headless: true,
      ...(process.env.RAFII_TEST_FONTCONFIG ? {env: {...process.env, FONTCONFIG_FILE: process.env.RAFII_TEST_FONTCONFIG}} : {}),
      ...(process.env.RAFII_TEST_CHROMIUM ? {
      executablePath: process.env.RAFII_TEST_CHROMIUM,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-zygote', '--single-process']
    } : {})};
    for (const [locale, width] of [['en', 1280], ['en', 390], ['zh-Hant', 390], ['zh-Hans', 1280]]) {
      stage = `${locale}-${width}`;
      browser = await chromium.launch(launchOptions);
      browserVersion = browser.version();
      const copy = packs[locale];
      const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce', serviceWorkers: 'block', locale: 'en-US'});
      await context.addCookies([{name: 'postriff_dev', value: '1', url: base}]);
      await context.addInitScript(({wid, actor}) => {
        localStorage.setItem('postriff-dev-principal', actor); localStorage.setItem('postriff-workspace', wid);
        localStorage.setItem('postriff-onboarding:' + actor, JSON.stringify({completed: {}, dismissed: {welcome: 1}, nudged: {}}));
      }, {wid, actor});
      const matrix = Object.fromEntries(['identity', 'publish', 'schedule', 'analytics', 'inbox', 'reply', 'moderate'].map(k => [k, {level: k === 'publish' || k === 'schedule' ? 'Direct' : 'Unsupported', evidence: 'Synthetic', verifiedAt: 1800000000, capabilityVersion: 1}]));
      const bot = {...structuredClone(input.channel), id: 'synthetic-bot', account: 'Synthetic bot server', discordConnectionKind: 'installation', connectionState: 'publish_verified', capabilities: matrix};
      const hook = {...bot, id: 'synthetic-webhook', account: 'Synthetic webhook channel', discordConnectionKind: 'webhook', scopes: ['identify', 'webhook.incoming']};
      const channels = [hook, bot], snapshot = structuredClone(template.snapshot);
      snapshot.state.workspace.id = wid;
      snapshot.state.phase2 = {...snapshot.state.phase2, channels, jobs: [], reviews: [], assets: []};
      const profiles = {
        [hook.id]: {connectionId: hook.id, senderKind: 'webhook', scope: 'connection', guildId: '555555', name: 'Rafii', maxLength: 80, fingerprint: 'hook-v1', state: 'verified'},
        [bot.id]: {connectionId: bot.id, senderKind: 'bot', scope: 'server', guildId: '555555', name: 'Rafii', maxLength: 32, fingerprint: 'bot-v1', state: 'verified'}
      };
      const posts = []; let releasePost, holdPost = true, rejectPost = false;
      await context.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url()), path = url.pathname;
        if (url.origin !== base) return route.abort();
        if (!path.startsWith('/api/')) return route.continue();
        const send = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
        if (path.endsWith('/discord-sender-name')) {
          const id = path.split('/').at(-2), profile = profiles[id]; assert.ok(profile);
          if (req.method() === 'GET') return send(profile);
          assert.equal(req.method(), 'POST');
          const body = req.postDataJSON(); posts.push({id, body});
          assert.equal(body.confirmed, true); assert.equal(body.fingerprint, profile.fingerprint);
          if (id === bot.id) assert.equal(body.sharedServerConfirmed, true);
          if (holdPost) await new Promise(resolve => { releasePost = resolve; });
          if (rejectPost) return send({error: 'Synthetic refusal', code: rejectPost === 'session' ? 'step_up_required' : 'discord_sender_name_required'}, rejectPost === 'session' ? 403 : 409);
          profile.name = body.name; profile.fingerprint += '-saved';
          if (id === hook.id) hook.discordSenderName = body.name;
          return send(profile);
        }
        assert.equal(req.method(), 'GET', 'Sender editor must never publish, connect or approve posts');
        if (path.endsWith('/channels')) return send({channels, providers: [], discordIdentities: []});
        if (path === '/api/catalog') return send({authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {}});
        if (path === '/api/me') return send({userId: actor, displayName: 'Synthetic tester', preferences: {timeZone: 'UTC', locale}, mfa: {}});
        if (path === '/api/workspaces') return send({workspaces: [{workspaceId: wid, name: 'Synthetic Discord', plan: 'studio', membership: template.snapshot.membership, memberCounts: {owner: 1}}]});
        if (path === `/api/workspaces/${wid}`) return send(snapshot);
        if (path.endsWith('/memory')) return send(template.memory);
        if (path.endsWith('/memory/proposals')) return send({pending: [], recent: [], learning: {items: []}});
        if (path.endsWith('/audit')) return send({events: []});
        return send({error: 'Unhandled synthetic read'}, 404);
      });
      const page = await context.newPage(); page.setDefaultTimeout(30000);
      await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
      const hookButton = page.getByRole('button', {name: `${copy.senderEdit} · ${hook.account}`, exact: true});
      const botButton = page.getByRole('button', {name: `${copy.senderEdit} · ${bot.account}`, exact: true});
      await hookButton.focus(); await page.keyboard.press('Enter');
      const dialog = page.getByRole('dialog');
      const name = dialog.getByRole('textbox', {name: copy.senderNameLabel, exact: true});
      await until(() => name.inputValue().then(v => v === 'Rafii').catch(() => false));
      await name.fill('D Festival 公告');
      assert.match(await dialog.locator('[data-discord-sender-preview]').innerText(), /D Festival 公告/);
      await dialog.getByText(copy.senderWebhookScope, {exact: false}).waitFor();
      assert.equal(await dialog.getByRole('checkbox').count(), 0);
      mkdirSync(join(root, '.depot/discord-sender-name-browser'), {recursive: true});
      await page.screenshot({path: join(root, `.depot/discord-sender-name-browser/${locale}-${width}-webhook.png`)});
      await dialog.getByRole('button', {name: copy.senderSave, exact: true}).click();
      await until(() => Boolean(releasePost));
      assert.equal(await dialog.getByRole('button', {name: copy.senderSave, exact: true}).isDisabled(), true);
      assert.equal(await dialog.getByRole('button', {name: copy.senderClose, exact: true}).isDisabled(), true);
      await page.keyboard.press('Escape'); assert.equal(await dialog.isVisible(), true);
      holdPost = false; releasePost();
      await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
      assert.equal(posts.length, 1);
      await dialog.getByRole('button', {name: copy.senderClose, exact: true}).click();
      await page.locator('[data-discord-sender]').filter({hasText: 'D Festival 公告'}).waitFor();
      await botButton.click();
      await until(() => name.inputValue().then(v => v === 'Rafii').catch(() => false));
      await name.fill('D Festival 助手');
      await dialog.getByText(copy.senderBotScope, {exact: false}).waitFor();
      assert.equal(await dialog.getByRole('button', {name: copy.senderSave, exact: true}).isDisabled(), true);
      await dialog.getByRole('checkbox', {name: copy.senderSharedConfirm, exact: true}).check();
      await page.screenshot({path: join(root, `.depot/discord-sender-name-browser/${locale}-${width}-bot.png`)});
      await dialog.getByRole('button', {name: copy.senderSave, exact: true}).click();
      await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
      assert.equal(posts.length, 2);
      await name.fill('x'.repeat(33));
      assert.equal(await dialog.getByRole('button', {name: copy.senderSave, exact: true}).isDisabled(), true);
      await name.fill('Another name');
      await dialog.getByRole('checkbox', {name: copy.senderSharedConfirm, exact: true}).check();
      rejectPost = true;
      await dialog.getByRole('button', {name: copy.senderSave, exact: true}).click();
      await dialog.getByRole('alert').filter({hasText: copy.senderSaveFailed}).waitFor();
      assert.equal(await dialog.getByRole('button', {name: copy.senderSave, exact: true}).isDisabled(), true);
      const beforeReload = posts.length;
      await dialog.getByRole('button', {name: copy.senderReload, exact: true}).click();
      await until(() => name.inputValue().then(v => v === 'D Festival 助手').catch(() => false));
      assert.equal(posts.length, beforeReload, 'Reload must not retry a write');
      await name.fill('Fresh session needed');
      await dialog.getByRole('checkbox', {name: copy.senderSharedConfirm, exact: true}).check();
      rejectPost = 'session';
      await dialog.getByRole('button', {name: copy.senderSave, exact: true}).click();
      await dialog.getByRole('alert').filter({hasText: copy.senderSessionError}).waitFor();
      await dialog.getByRole('button', {name: copy.senderSignInAgain, exact: true}).waitFor();
      assert.equal(await dialog.getByText(copy.senderPermissionError, {exact: true}).count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      mkdirSync(join(root, '.depot/discord-sender-name-browser'), {recursive: true});
      await page.screenshot({path: join(root, `.depot/discord-sender-name-browser/${locale}-${width}.png`), fullPage: true});
      checks.push({locale, width, webhook: true, sharedBot: true, pending: true, staleReload: true, localized: true, freshSessionRecovery: true});
      await context.close();
      await browser.close(); browser = null;
    }
    console.log(JSON.stringify({status: 'pass', browserVersion, checks}));
  } catch (error) {
    console.error(JSON.stringify({status: 'fail', stage, error: error.message, server: tail})); process.exitCode = 1;
  } finally {
    if (browser) await browser.close(); app.kill('SIGTERM');
  }
})();
