/**
 * Actual app UI, synthetic APIs only (contract v2, docs/sender-name/UI-API-CONTRACT.md). No Discord credentials or
 * provider IO: every API response comes from this file, and every off-origin request is blocked.
 *
 * Each locale and width runs every case group; the receipt lists the cases that really ran and the run fails when one
 * is missing (REQUIRED_CASES / ONCE_CASES), so a skipped block cannot pass silently. In CI nothing narrows the run.
 * While developing, RAFII_SENDER_CASES=core,states runs only those groups and says so (that run is not evidence).
 */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {createHash} = require('node:crypto');
const {readFileSync, mkdirSync, existsSync, writeFileSync} = require('node:fs');
const {join, resolve} = require('node:path');
const {chromium} = require('playwright');
assert.equal(process.platform, 'linux');
assert.equal(process.env.CI, 'true');
assert.equal(process.env.RAFII_DISCORD_SYNTHETIC_FENCE, '1');
const root = join(__dirname, '../..'), base = 'http://127.0.0.1:4449';
const input = JSON.parse(readFileSync(join(root, '.depot/discord-p0-ui.json')));
const template = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json')));
const packs = JSON.parse(readFileSync(join(root, 'web/src/lib/channels/discord-copy.json')));
const wid = input.job.manifest.workspaceId, actor = '00000000-0000-0000-0000-000000000001';
const outDir = join(root, '.depot/discord-sender-name-browser');
const evidenceDir = process.env.RAFII_EVIDENCE_DIR ? resolve(process.env.RAFII_EVIDENCE_DIR) : null;
for (const name of ['.env', '.env.local', '.env.development', '.env.development.local']) {
  assert.equal(existsSync(join(root, 'web', name)), false, 'Isolated browser must not load local environment files');
}

// What a complete run must have done. The names are the receipt: a case that did not run is missing from it.
const REQUIRED_CASES = [
  'webhook-edit-save', 'webhook-body-has-no-shared-flag', 'bot-shared-confirm-save', 'bot-body-has-shared-flag', 'focus-on-field-after-load', 'focus-returns-to-trigger',
  'validation-too-long', 'validation-surrounding-space', 'validation-spacing', 'validation-forbidden-character', 'validation-url-like', 'validation-reserved-word',
  'validation-control-or-format', 'validation-not-normalized', 'validation-empty', 'validation-emoji-counts-two', 'validation-clears', 'counter-limits',
  'preview-webhook', 'preview-bot', 'preview-live-update', 'preview-theme-toggle', 'preview-contrast',
  'state-sender_names_disabled', 'state-bot_nickname_disabled', 'state-not_authorizing_member', 'state-session_reverification_required', 'state-person_missing_manage_nicknames',
  'state-person_role_below_bot', 'state-bot_missing_change_nickname', 'state-nickname_authority_other_workspace', 'state-edit_pending', 'state-reconnect_required',
  'state-rate_limited', 'state-upstream_unavailable', 'state-workspace_permission', 'state-stale', 'state-failed', 'state-several-reasons', 'state-check-again-is-a-read',
  'state-pending-countdown', 'state-blocked-controls-explain', 'default-off-is-read-only-view', 'card-hint-from-provider', 'card-hint-learned-from-read',
  'failure-stale-reload-no-retry', 'failure-fresh-session', 'failure-post-unavailable', 'failure-server-rule-keeps-form', 'failure-reload-uses-new-fingerprint',
  'protect-double-click', 'protect-enter-twice', 'protect-pending-close', 'protect-escape-while-saving',
  'keyboard-open-type-save', 'keyboard-tab-order', 'keyboard-escape-returns-focus', 'keyboard-state-actions',
  'schedule-preview-webhook', 'schedule-preview-bot', 'schedule-preview-lines-and-time',
  'review-preview-webhook', 'review-preview-bot',
  'no-horizontal-overflow', 'long-values-wrap', 'reduced-motion', 'no-unexpected-requests'
];
// Recorded once per run (English at 1280 px), because they do not depend on locale or width.
const ONCE_CASES = ['dark-scheme-follows-app', 'axe-editor-light', 'axe-editor-dark', 'axe-blocked-state', 'evidence-screenshots'];
const WANT = process.env.RAFII_SENDER_CASES ? new Set(process.env.RAFII_SENDER_CASES.split(',')) : null;
const run = (group) => !WANT || WANT.has(group);

// ---------------------------------------------------------------------------------------------------------------
// The dev server of the isolated app
// ---------------------------------------------------------------------------------------------------------------
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', '--webpack', '-H', '127.0.0.1', '-p', '4449'], {
  cwd: join(root, 'web'), stdio: ['ignore', 'pipe', 'pipe'], env: {PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR,
    CI: 'true', NODE_ENV: 'development', NEXT_TELEMETRY_DISABLED: '1', OPENUI_TELEMETRY_DISABLED: '1',
    NEXT_PUBLIC_APP_URL: base, POSTRIFF_DEV_SSR: '1', NEXT_PUBLIC_SUPABASE_URL: '', NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: '',
    POSTRIFF_API_ORIGIN: 'http://127.0.0.1:4448', NEXT_PUBLIC_SENTRY_DISABLED: '1', POSTRIFF_DIST_DIR: '.next-sender-ui',
    ...(process.env.NEXT_FONT_GOOGLE_MOCKED_RESPONSES ? {NEXT_FONT_GOOGLE_MOCKED_RESPONSES: process.env.NEXT_FONT_GOOGLE_MOCKED_RESPONSES} : {})}
});
let tail = '';
for (const stream of [app.stdout, app.stderr]) stream.on('data', b => { tail = (tail + b).slice(-5000); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(check, what = 'condition') {
  for (let i = 0; i < 400; i++) { if (await check()) return; await sleep(250); }
  throw Error(`Synthetic browser condition timed out: ${what}`);
}
/** The first request to a page compiles it; do that before any timeout-bound step (slow runners). */
async function warm(path) {
  const stop = Date.now() + 900000;
  while (Date.now() < stop) {
    const status = await fetch(base + path, {headers: {cookie: 'postriff_dev=1'}, signal: AbortSignal.timeout(300000)}).then(r => r.status).catch(() => 0);
    if (status && status < 500) return;
    await sleep(1000);
  }
  throw Error(`Dev server never served ${path}`);
}

// ---------------------------------------------------------------------------------------------------------------
// Synthetic contract-v2 responses
// ---------------------------------------------------------------------------------------------------------------
const FORBIDDEN = ['@', '#', ':', '```', '<', '>'];
const hash = label => createHash('sha256').update('synthetic-sender-' + label).digest('hex');
const HOOK = 'synthetic-webhook', BOT = 'synthetic-bot';
const ISSUE_KEYS = {empty: 'senderIssueEmpty', surrounding_space: 'senderIssueSpace', not_normalized: 'senderIssueNotNormalized', too_long: 'senderIssueTooLong',
  control_or_format: 'senderIssueControl', spacing: 'senderIssueSpacing', invisible: 'senderIssueInvisible', forbidden_character: 'senderIssueForbidden',
  url_like: 'senderIssueUrl', reserved_word: 'senderIssueReserved'};
const STATE_TEXT = {
  sender_names_disabled: ['senderStateSenderNamesDisabledTitle', 'senderStateSenderNamesDisabledBody', 'senderStateSenderNamesDisabledNext'],
  bot_nickname_disabled: ['senderStateBotNicknameDisabledTitle', 'senderStateBotNicknameDisabledBody', 'senderStateBotNicknameDisabledNext'],
  not_authorizing_member: ['senderStateNotAuthorizingMemberTitle', 'senderStateNotAuthorizingMemberBody', 'senderStateNotAuthorizingMemberNext'],
  session_reverification_required: ['senderStateSessionReverificationRequiredTitle', 'senderSessionError', 'senderStateSessionReverificationRequiredNext'],
  person_missing_manage_nicknames: ['senderStatePersonMissingManageNicknamesTitle', 'senderStatePersonMissingManageNicknamesBody', 'senderStatePersonMissingManageNicknamesNext'],
  person_role_below_bot: ['senderStatePersonRoleBelowBotTitle', 'senderStatePersonRoleBelowBotBody', 'senderStatePersonRoleBelowBotNext'],
  bot_missing_change_nickname: ['senderStateBotMissingChangeNicknameTitle', 'senderStateBotMissingChangeNicknameBody', 'senderStateBotMissingChangeNicknameNext'],
  nickname_authority_other_workspace: ['senderStateNicknameAuthorityOtherWorkspaceTitle', 'senderStateNicknameAuthorityOtherWorkspaceBody', 'senderStateNicknameAuthorityOtherWorkspaceNext'],
  edit_pending: ['senderStateEditPendingTitle', 'senderChangePending', 'senderStateEditPendingNext'],
  stale: ['senderStateStaleTitle', 'senderStateStaleBody', 'senderStateStaleNext'],
  reconnect_required: ['senderStateReconnectRequiredTitle', 'senderStateReconnectRequiredBody', 'senderStateReconnectRequiredNext'],
  rate_limited: ['senderStateRateLimitedTitle', 'senderStateRateLimitedBody', 'senderStateRateLimitedNext'],
  upstream_unavailable: ['senderStateUpstreamUnavailableTitle', 'senderStateUpstreamUnavailableBody', 'senderStateUpstreamUnavailableNext'],
  workspace_permission: ['senderStateWorkspacePermissionTitle', 'senderStateWorkspacePermissionBody', 'senderStateWorkspacePermissionNext'],
  failed: ['senderStateFailedTitle', 'senderSaveFailed', 'senderStateFailedNext']
};
assert.equal(Object.keys(STATE_TEXT).length, 15);
const fill = (text, values) => text.replace(/\{(\w+)\}/g, (whole, name) => String(values[name] ?? whole));
const squash = value => value.replace(/\s+/g, ' ').trim();
const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function profile(kind, id, extra = {}) {
  const webhook = kind === 'webhook', limit = webhook ? 80 : 32;
  return {contractVersion: 2, connectionId: id, senderKind: kind, scope: webhook ? 'connection' : 'server', guildId: '555555', state: 'verified', maxLength: limit,
    rules: {minLength: 1, maxLength: limit, lengthUnit: 'codepoints', surroundingSpace: false, forbiddenCharacters: FORBIDDEN, reservedWords: true, singleSpacesOnly: true},
    name: 'Acme Weekly', effectiveName: 'Acme Weekly', nameSource: webhook ? 'webhook_default' : 'observed_nickname', savedName: null,
    observedName: 'Acme Weekly', observedAt: 1800000000.5, externalChange: false, fingerprint: hash(id + '-1'),
    feature: {senderNames: true, botNickname: true}, editable: true, unavailable: [],
    preview: {currentDisplayName: 'Acme Weekly', badge: 'APP', audience: webhook ? 'this_connection' : 'everyone_in_server',
      queuedPostsKeepApprovedName: webhook, queuedPostsFollowCurrentNickname: !webhook}, ...extra};
}
const blockedProfile = (kind, id, codes, extra = {}) => profile(kind, id, {editable: false, unavailable: codes.map(code => typeof code === 'string' ? {code} : code), ...extra});
/** The contract's early answers, made without reading Discord: no name, no observation time. */
const unread = {name: '', effectiveName: null, observedName: null, observedAt: null, nameSource: 'none'};

/** Every availability state a GET can reach, how the synthetic server gets there, and on which kind of connection. */
const STATE_SCENARIOS = [
  {state: 'sender_names_disabled', kind: 'webhook', get: () => ({body: blockedProfile('webhook', HOOK, ['sender_names_disabled'], {...unread, feature: {senderNames: false, botNickname: false}})})},
  {state: 'bot_nickname_disabled', kind: 'bot', get: () => ({body: blockedProfile('bot', BOT, ['bot_nickname_disabled'], {...unread, feature: {senderNames: true, botNickname: false}})})},
  {state: 'not_authorizing_member', kind: 'webhook', get: () => ({body: blockedProfile('webhook', HOOK, ['not_authorizing_member'], unread)})},
  {state: 'session_reverification_required', kind: 'webhook', signIn: true, get: () => ({body: blockedProfile('webhook', HOOK, ['session_reverification_required'])})},
  {state: 'person_missing_manage_nicknames', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['person_missing_manage_nicknames'])})},
  {state: 'person_role_below_bot', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['person_role_below_bot'])})},
  {state: 'bot_missing_change_nickname', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['bot_missing_change_nickname'])})},
  {state: 'nickname_authority_other_workspace', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['nickname_authority_other_workspace'])})},
  {state: 'edit_pending', kind: 'bot', again: true, timed: true, get: () => ({body: blockedProfile('bot', BOT, [{code: 'edit_pending', retryAfterSeconds: 90}])})},
  {state: 'reconnect_required', kind: 'webhook', again: true, get: () => ({status: 409, body: {error: 'Reconnect this Discord connection before changing its sender name.', code: 'discord_connection_required'}})},
  {state: 'rate_limited', kind: 'webhook', again: true, timed: true, get: () => ({status: 429, body: {error: 'Too many sender-name requests.', code: 'rate_limited', retryAfterSeconds: 60}})},
  {state: 'upstream_unavailable', kind: 'webhook', again: true, get: () => ({status: 502, body: {error: 'Discord did not return a valid current sender name.', code: 'upstream_error'}})},
  {state: 'workspace_permission', kind: 'webhook', get: () => ({status: 403, body: {error: 'Workspace unavailable.', code: 'permission_denied'}})}
];

// ---------------------------------------------------------------------------------------------------------------
(async () => {
  let browser, browserVersion, stage = 'startup';
  const ran = {};
  const once = new Set();
  const combos = [['en', 1280], ['en', 390], ['zh-Hant', 390], ['zh-Hans', 1280]];
  try {
    stage = 'warm';
    await warm('/app/channels'); await warm('/app/queue');
    const launchOptions = {headless: true,
      ...(process.env.RAFII_TEST_FONTCONFIG ? {env: {...process.env, FONTCONFIG_FILE: process.env.RAFII_TEST_FONTCONFIG}} : {}),
      ...(process.env.RAFII_TEST_CHROMIUM ? {
      executablePath: process.env.RAFII_TEST_CHROMIUM,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-zygote', '--single-process']
    } : {})};
    mkdirSync(outDir, {recursive: true});
    if (evidenceDir) mkdirSync(evidenceDir, {recursive: true});

    for (const [locale, width] of combos) {
      const combo = `${locale}-${width}`;
      stage = combo;
      browser = await chromium.launch(launchOptions);
      browserVersion = browser.version();
      const copy = packs[locale];
      const recorded = ran[combo] = new Set();
      const pass = name => recorded.add(name);

      const newContext = async (extra = {}) => {
        const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce', serviceWorkers: 'block', locale: 'en-US', ...extra});
        await context.addCookies([{name: 'postriff_dev', value: '1', url: base}]);
        await context.addInitScript(({wid, actor}) => {
          localStorage.setItem('postriff-dev-principal', actor); localStorage.setItem('postriff-workspace', wid);
          localStorage.setItem('postriff-onboarding:' + actor, JSON.stringify({completed: {}, dismissed: {welcome: 1}, nudged: {'channels-tips': 1, 'queue-tips': 1}}));
        }, {wid, actor});
        return context;
      };

      // The synthetic workspace of this run: both connection kinds, their profiles, and what the server did with each request.
      const matrix = Object.fromEntries(['identity', 'publish', 'schedule', 'analytics', 'inbox', 'reply', 'moderate'].map(k => [k, {level: k === 'publish' || k === 'schedule' ? 'Direct' : 'Unsupported', evidence: 'Synthetic', verifiedAt: 1800000000, capabilityVersion: 1}]));
      const bot = {...structuredClone(input.channel), id: BOT, account: 'Synthetic bot server', discordConnectionKind: 'installation', connectionState: 'publish_verified', capabilities: matrix};
      const hook = {...bot, id: HOOK, account: 'Synthetic webhook channel', discordConnectionKind: 'webhook', scopes: ['identify', 'webhook.incoming']};
      hook.discordDestinations = hook.discordDestinations.map(d => ({...d, id: d.id + '-webhook', connectionId: hook.id, senderKind: 'webhook', credentialKind: 'webhook', webhookId: '66112233', botUserId: undefined}));
      const channels = [hook, bot], snapshot = structuredClone(template.snapshot);
      snapshot.state.workspace.id = wid;
      snapshot.state.phase2 = {...snapshot.state.phase2, channels, jobs: [], reviews: [], assets: []};
      snapshot.state.speaker.activeRevision = null;
      const world = {profiles: {}, gets: [], posts: [], unexpected: [], blocked: 0, version: 1, getAnswer: null, postAnswer: null, release: null, hold: false, variants: [], reviews: [], providers: [], activity: 0, preferences: {timeZone: 'UTC', locale}};
      const reset = () => {
        world.profiles = {[HOOK]: profile('webhook', HOOK), [BOT]: profile('bot', BOT)};
        world.gets = []; world.posts = []; world.getAnswer = null; world.postAnswer = null; world.hold = false; world.release = null; world.providers = [];
        delete hook.discordSenderName;
      };
      reset();
      const handle = async (route) => {
        const req = route.request(), url = new URL(req.url()), path = url.pathname;
        if (url.origin !== base) { world.blocked++; return route.abort(); }
        if (!path.startsWith('/api/')) return route.continue();
        const send = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
        if (path.endsWith('/discord-sender-name')) {
          const id = path.split('/').at(-2), current = world.profiles[id];
          if (!current) return send({error: 'Unknown connection', code: 'not_found'}, 404);
          if (req.method() === 'GET') {
            world.gets.push(id);
            const answer = world.getAnswer?.(id);
            if (answer) return send(answer.body, answer.status ?? 200);
            return send(current);
          }
          if (req.method() !== 'POST') { world.unexpected.push(`${req.method()} ${path}`); return send({error: 'Unexpected', code: 'invalid_request'}, 400); }
          const body = req.postDataJSON(); world.posts.push({id, body});
          const names = Object.keys(body).sort().join(',');
          const expected = current.senderKind === 'bot' ? 'confirmed,fingerprint,name,sharedServerConfirmed' : 'confirmed,fingerprint,name';
          if (names !== expected || body.confirmed !== true) return send({error: 'Review and confirm the sender name before saving.', code: 'discord_sender_name_unconfirmed'}, 400);
          if (world.hold) await new Promise(resolve => { world.release = resolve; });
          const answer = world.postAnswer?.(id, body);
          if (answer) return send(answer.body, answer.status ?? 200);
          if (body.fingerprint !== current.fingerprint) return send({error: 'Discord sender settings changed. Reload and review the name again.', code: 'discord_sender_name_required'}, 409);
          const webhook = current.senderKind === 'webhook';
          world.profiles[id] = {...current, name: body.name, effectiveName: body.name, savedName: body.name, observedName: body.name, observedAt: 1800000100.5,
            nameSource: webhook ? 'saved_override' : 'observed_nickname', fingerprint: hash(id + '-' + (++world.version)), saved: true,
            preview: {...current.preview, currentDisplayName: body.name}};
          if (webhook) hook.discordSenderName = body.name;
          return send(world.profiles[id]);
        }
        if (path.endsWith('/time-savings/activity') && req.method() === 'POST') { world.activity++; return send({ok: true}); }
        if (req.method() !== 'GET') { world.unexpected.push(`${req.method()} ${path}`); return send({error: 'Unexpected synthetic mutation', code: 'invalid_request'}, 400); }
        if (path.endsWith('/channels')) return send({channels, providers: world.providers, discordIdentities: []});
        if (path === '/api/catalog') return send({authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {}});
        if (path === '/api/me') return send({userId: actor, displayName: 'Synthetic tester', preferences: world.preferences, mfa: {}});
        if (path === '/api/workspaces') return send({workspaces: [{workspaceId: wid, name: 'Synthetic Discord', plan: 'studio', membership: template.snapshot.membership, memberCounts: {owner: 1}}]});
        if (path === `/api/workspaces/${wid}`) { snapshot.state.variants = world.variants; snapshot.state.phase2.reviews = world.reviews; return send(snapshot); }
        if (path.endsWith('/memory')) return send(template.memory);
        if (path.endsWith('/memory/proposals')) return send({pending: [], recent: [], learning: {items: []}});
        if (path.endsWith('/audit')) return send({events: []});
        return send({error: 'Unhandled synthetic read'}, 404);
      };

      const context = await newContext();
      await context.route('**/*', handle);
      const page = await context.newPage(); page.setDefaultTimeout(30000);
      const dialog = page.getByRole('dialog');
      const nameBox = dialog.getByRole('textbox', {name: copy.senderNameLabel, exact: true});
      const saveButton = dialog.getByRole('button', {name: copy.senderSave, exact: true});
      const closeButton = dialog.getByRole('button', {name: copy.senderClose, exact: true});
      const hookButton = page.getByRole('button', {name: `${copy.senderEdit} · ${hook.account}`, exact: true});
      const botButton = page.getByRole('button', {name: `${copy.senderEdit} · ${bot.account}`, exact: true});
      const trigger = kind => kind === 'bot' ? botButton : hookButton;

      const shot = async (target, name, {tall = false, evidence = false} = {}) => {
        const original = target.viewportSize();
        if (tall) await target.setViewportSize({width, height: 2200});
        await sleep(150);
        await target.screenshot({path: join(outDir, `${combo}-${name}.png`)});
        if (evidence && evidenceDir) await target.screenshot({path: join(evidenceDir, `${combo}-${name}.png`)});
        if (tall) await target.setViewportSize(original);
      };
      const focused = () => page.evaluate(() => {
        const element = document.activeElement;
        if (!element || element === document.body) return null;
        return {tag: element.tagName, type: element.getAttribute('type'), save: element.hasAttribute('data-sender-save'), again: element.hasAttribute('data-sender-check-again'),
          theme: element.getAttribute('data-theme-option'), label: element.getAttribute('aria-label'), text: (element.textContent || '').trim().slice(0, 80),
          heading: element.tagName === 'H3' ? element.closest('[data-testid]')?.getAttribute('data-testid') : null, field: element.tagName === 'INPUT' && element.type !== 'checkbox'};
      });
      const overflow = () => page.evaluate(() => {
        const box = document.querySelector('[data-testid="discord-sender-dialog"]') ?? document.querySelector('[role="dialog"]');
        const bad = [];
        if (box) {
          const outer = box.getBoundingClientRect();
          for (const element of box.querySelectorAll('*')) {
            if (element.closest('.sr-only')) continue;
            const rect = element.getBoundingClientRect();
            if (!rect.width || !rect.height || getComputedStyle(element).position === 'fixed') continue;
            if (rect.right > outer.right + 1 || rect.left < outer.left - 1) bad.push(`${element.tagName}.${String(element.className).slice(0, 50)}`);
          }
        }
        return {document: document.documentElement.scrollWidth > innerWidth + 1, dialog: box ? box.scrollWidth > box.clientWidth + 1 : false, bad: bad.slice(0, 5)};
      });
      const assertFits = async what => {
        const result = await overflow();
        assert.deepEqual(result, {document: false, dialog: false, bad: []}, `horizontal overflow at ${what}: ${JSON.stringify(result)}`);
      };
      const open = async (kind, {keyboard = true} = {}) => {
        const button = trigger(kind);
        if (keyboard) { await button.focus(); await page.keyboard.press('Enter'); } else await button.click();
        await dialog.waitFor();
      };
      const closeDialog = async () => {
        if (await dialog.count()) { await page.keyboard.press('Escape'); await dialog.waitFor({state: 'detached'}).catch(async () => { await closeButton.click(); await dialog.waitFor({state: 'detached'}); }); }
      };
      const loaded = value => until(() => nameBox.inputValue().then(v => v === value).catch(() => false), `name field ${value}`);
      const openLoaded = async (kind, value = 'Acme Weekly', options) => { await open(kind, options); await loaded(value); };
      const reasonOf = async () => {
        const id = await saveButton.getAttribute('aria-describedby');
        return id ? squash(await page.evaluate(i => document.getElementById(i)?.innerText ?? '', id)) : null;
      };
      const issues = () => dialog.locator('[data-sender-issues] [data-issue]').evaluateAll(items => items.map(item => [item.getAttribute('data-issue'), item.textContent.trim()]));
      const resetPage = async () => { await closeDialog().catch(() => {}); reset(); };
      const edit = async (value, shared) => {
        await nameBox.fill(value);
        if (shared) await dialog.getByRole('checkbox', {name: copy.senderSharedConfirm, exact: true}).check();
      };

      await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
      await hookButton.waitFor(); await botButton.waitFor();

      // ---------------------------------------------------------------- core: the webhook and bot flows
      if (run('core')) {
        stage = combo + ':core-webhook';
        await open('webhook');
        await loaded('Acme Weekly');
        await until(async () => (await focused())?.field === true, 'focus on the name field after load'); pass('focus-on-field-after-load');
        await nameBox.fill('D Festival 公告');
        assert.match(await dialog.locator('[data-discord-sender-preview]').innerText(), /D Festival 公告/);
        await dialog.getByText(copy.senderWebhookScope, {exact: false}).waitFor();
        assert.equal(await dialog.getByRole('checkbox').count(), 0);
        await shot(page, 'webhook');
        world.hold = true;
        await saveButton.click();
        await until(() => Boolean(world.release), 'held save');
        assert.equal(await saveButton.isDisabled(), true); assert.equal(await closeButton.isDisabled(), true);
        pass('protect-pending-close');
        await page.keyboard.press('Escape'); assert.equal(await dialog.isVisible(), true); pass('protect-escape-while-saving');
        world.hold = false; world.release();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 1);
        assert.deepEqual(Object.keys(world.posts[0].body).sort(), ['confirmed', 'fingerprint', 'name']); pass('webhook-body-has-no-shared-flag');
        await closeButton.click(); await dialog.waitFor({state: 'detached'});
        await until(async () => (await focused())?.label === `${copy.senderEdit} · ${hook.account}`, 'focus back on the trigger'); pass('focus-returns-to-trigger');
        await page.locator('[data-discord-sender]').filter({hasText: 'D Festival 公告'}).waitFor();
        pass('webhook-edit-save');

        stage = combo + ':core-bot';
        await open('bot', {keyboard: false});
        await loaded('Acme Weekly');
        await nameBox.fill('D Festival 助手');
        await dialog.getByText(copy.senderBotScope, {exact: false}).waitFor();
        assert.equal(await saveButton.isDisabled(), true);
        assert.equal(await reasonOf(), squash(copy.senderSaveWhyConfirm));
        await dialog.getByRole('checkbox', {name: copy.senderSharedConfirm, exact: true}).check();
        assert.equal(await saveButton.isDisabled(), false);
        await shot(page, 'bot-editor', {tall: true, evidence: locale === 'zh-Hant' && width === 390});
        await saveButton.click();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 2);
        assert.deepEqual(Object.keys(world.posts[1].body).sort(), ['confirmed', 'fingerprint', 'name', 'sharedServerConfirmed']);
        assert.equal(world.posts[1].body.sharedServerConfirmed, true); pass('bot-body-has-shared-flag');
        pass('bot-shared-confirm-save');
        await resetPage();
      }

      // ---------------------------------------------------------------- validation: the server's rules, before saving
      if (run('validation')) {
        stage = combo + ':validation';
        await openLoaded('bot');
        const cases = [
          ['x'.repeat(33), 'too_long', 'validation-too-long'], [' lead', 'surrounding_space', 'validation-surrounding-space'], ['a  b', 'spacing', 'validation-spacing'],
          ['Team @here', 'forbidden_character', 'validation-forbidden-character'], ['www.example.com', 'url_like', 'validation-url-like'], ['Disc0rd', 'reserved_word', 'validation-reserved-word'],
          ['Zero​width', 'control_or_format', 'validation-control-or-format'], ['Café', 'not_normalized', 'validation-not-normalized'], ['', 'empty', 'validation-empty']
        ];
        for (const [value, issue, label] of cases) {
          await nameBox.fill(value);
          await until(async () => (await issues()).some(([found]) => found === issue), `${issue} listed`);
          const length = Math.max(Array.from(value).length, value.length);
          const listed = await issues();
          assert.equal(listed[0][0], issue, `${issue} is the first rule listed`);
          assert.equal(squash(listed[0][1]), squash(fill(copy[ISSUE_KEYS[issue]], {length, limit: 32, over: Math.max(0, length - 32)})), `${issue} message`);
          assert.equal(await nameBox.getAttribute('aria-invalid'), 'true');
          assert.equal(await saveButton.getAttribute('aria-disabled'), 'true');
          assert.equal(await reasonOf(), squash(copy.senderSaveWhyInvalid));
          assert.equal(squash(await dialog.locator('[data-sender-issues-live]').textContent()), squash(fill(copy.senderIssueSummary, {limit: 32})));
          pass(label);
        }
        await nameBox.fill('\u{1F600}'.repeat(17));
        await until(async () => (await issues()).some(([found]) => found === 'too_long'), 'emoji over the limit');
        assert.equal(squash(await dialog.locator('[data-sender-count]').innerText()), fill(copy.senderCount, {count: 34, limit: 32}));
        assert.equal(await dialog.locator('[data-sender-count]').getAttribute('data-over'), 'true');
        await nameBox.fill('\u{1F600}'.repeat(16));
        await until(async () => (await issues()).length === 0, 'sixteen emoji fit');
        assert.equal(squash(await dialog.locator('[data-sender-count]').innerText()), fill(copy.senderCount, {count: 32, limit: 32}));
        pass('validation-emoji-counts-two');
        await nameBox.fill('Concert helper');
        await until(async () => (await issues()).length === 0, 'rules clear');
        assert.equal(await nameBox.getAttribute('aria-invalid'), 'false');
        assert.equal(squash(await dialog.locator('[data-sender-issues-live]').textContent()), '');
        assert.equal(squash(await dialog.locator('[data-sender-count]').innerText()), fill(copy.senderCount, {count: 14, limit: 32}));
        assert.equal(await reasonOf(), squash(copy.senderSaveWhyConfirm));
        pass('validation-clears');
        await assertFits('bot validation');
        await resetPage();
        await openLoaded('webhook');
        assert.equal(squash(await dialog.locator('[data-sender-count]').innerText()), fill(copy.senderCount, {count: 11, limit: 80}));
        await nameBox.fill('x'.repeat(81));
        await until(async () => (await issues()).some(([found]) => found === 'too_long'), 'webhook limit');
        assert.equal(squash(await dialog.locator('[data-sender-count]').innerText()), fill(copy.senderCount, {count: 81, limit: 80}));
        assert.match((await issues())[0][1], /81/);
        // The rules are listed up front, from the contract, including the product names.
        const rules = squash(await dialog.locator('[data-sender-rules]').innerText());
        for (const line of [fill(copy.senderRuleLength, {limit: 80}), copy.senderRuleSpaces, copy.senderRuleForbidden, copy.senderRuleUrl, copy.senderRuleReserved]) assert.ok(rules.includes(squash(line)), line);
        pass('counter-limits');
        await resetPage();
      }

      // ---------------------------------------------------------------- preview: what Discord will show
      if (run('preview')) {
        stage = combo + ':preview';
        const surface = {dark: 'rgb(49, 51, 56)', light: 'rgb(255, 255, 255)'};
        await openLoaded('webhook');
        const preview = dialog.locator('[data-discord-message-preview]');
        assert.equal(await preview.getAttribute('data-kind'), 'webhook');
        assert.equal(await preview.getAttribute('data-name-source'), 'webhook_default');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), 'Acme Weekly');
        assert.equal(squash(await preview.locator('[data-preview-app-tag]').innerText()), copy.previewAppTag);
        assert.equal(await preview.locator('[data-preview-avatar]').getAttribute('aria-hidden'), 'true');
        assert.equal(squash(await preview.locator('[data-preview-avatar-note]').innerText()), squash(copy.previewAvatarWebhook));
        assert.equal(squash(await preview.locator('[data-preview-fidelity-note]').innerText()), squash(copy.previewFidelity));
        const notes = squash(await preview.locator('[data-preview-notes]').innerText());
        assert.ok(notes.includes(squash(copy.previewWebhookNote)) && notes.includes(squash(copy.previewWebhookDefaultNote)));
        assert.ok(!notes.includes(squash(copy.previewBotNote)), 'a webhook preview never uses the shared-nickname sentence');
        assert.match(squash(await preview.locator('[data-preview-time]').innerText()), new RegExp('^' + escapeRegExp(copy.previewToday).replace('\\{time\\}', '.+') + '$'));
        assert.equal(squash(await preview.locator('[data-preview-body]').innerText()), squash(copy.senderExample));
        assert.equal(await preview.locator('[data-preview-body]').evaluate(element => getComputedStyle(element).whiteSpace), 'pre-wrap');
        pass('preview-webhook');
        // Live: what is typed is what is previewed, marked as not saved yet.
        await nameBox.fill('Spring <b>Gala</b> 音樂會');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), 'Spring <b>Gala</b> 音樂會');
        assert.equal(await preview.locator('[data-preview-author] b').count(), 0, 'a name is text, never markup');
        assert.equal(await preview.getAttribute('data-name-source'), 'draft');
        assert.ok(squash(await preview.locator('[data-preview-notes]').innerText()).includes(squash(copy.senderPreviewUnsaved)));
        await nameBox.fill('');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), copy.previewEmptyName);
        assert.equal(await preview.locator('[data-preview-author]').getAttribute('data-placeholder'), 'true');
        await nameBox.fill('Acme Weekly');
        pass('preview-live-update');
        // Light and dark, with contrast measured on what the browser drew.
        const measure = () => preview.evaluate((section) => {
          const parse = value => value.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
          const luminance = rgb => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
          const ratio = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);
          const message = getComputedStyle(section.querySelector('[data-preview-message]'));
          const background = parse(message.backgroundColor);
          const text = selector => ({selector, ratio: ratio(parse(getComputedStyle(section.querySelector(selector)).color), background)});
          const tag = getComputedStyle(section.querySelector('[data-preview-app-tag]'));
          return {background: message.backgroundColor, ratios: [text('[data-preview-author]'), text('[data-preview-time]'), text('[data-preview-body]'),
            {selector: 'APP tag', ratio: ratio(parse(tag.color), parse(tag.backgroundColor))}]};
        });
        for (const theme of ['light', 'dark']) {
          await preview.locator(`[data-theme-option="${theme}"]`).click();
          assert.equal(await preview.getAttribute('data-theme'), theme);
          assert.equal(await preview.locator(`[data-theme-option="${theme}"]`).getAttribute('aria-pressed'), 'true');
          const result = await measure();
          assert.equal(result.background, surface[theme]);
          for (const {selector, ratio} of result.ratios) assert.ok(ratio >= 4.5, `${theme} ${selector} contrast ${ratio.toFixed(2)}`);
          await shot(page, `webhook-editor-${theme}-preview`, {tall: true, evidence: locale === 'en' && width === 1280 || locale === 'zh-Hans'});
        }
        pass('preview-theme-toggle'); pass('preview-contrast');
        await resetPage();
        await openLoaded('bot');
        const botPreview = dialog.locator('[data-discord-message-preview]');
        assert.equal(await botPreview.getAttribute('data-kind'), 'bot');
        assert.equal(await botPreview.getAttribute('data-name-source'), 'observed');
        assert.equal(squash(await botPreview.locator('[data-preview-author]').innerText()), 'Acme Weekly');
        assert.equal(squash(await botPreview.locator('[data-preview-app-tag]').innerText()), copy.previewAppTag);
        const botNotes = squash(await botPreview.locator('[data-preview-notes]').innerText());
        assert.ok(botNotes.includes(squash(copy.previewBotNote)), 'the bot preview says everyone sees the shared nickname');
        assert.ok(botNotes.includes(squash(copy.previewBotNameAsOf)));
        assert.ok(!botNotes.includes(squash(copy.previewWebhookNote)), 'a bot preview never claims a per-post name');
        assert.equal(squash(await botPreview.locator('[data-preview-avatar-note]').innerText()), squash(copy.previewAvatarBot));
        assert.match(squash(await dialog.locator('[data-sender-observed-at]').innerText()), new RegExp('^' + escapeRegExp(copy.senderCheckedAt).replace('\\{time\\}', '.+') + '$'));
        // A bot nickname that someone else changed in Discord is shown as theirs, not Rafii's.
        await closeDialog();
        world.profiles[BOT] = profile('bot', BOT, {savedName: 'Concert helper', externalChange: true, observedName: 'Acme Weekly'});
        await openLoaded('bot');
        assert.equal(squash(await dialog.locator('[data-sender-external-change]').innerText()), squash(fill(copy.senderExternalChange, {name: 'Acme Weekly'})));
        await resetPage();
        world.profiles[BOT] = profile('bot', BOT, {nameSource: 'bot_username', name: 'Rafii Helper', effectiveName: 'Rafii Helper', observedName: 'Rafii Helper'});
        await openLoaded('bot', 'Rafii Helper');
        assert.ok(squash(await dialog.locator('[data-preview-notes]').innerText()).includes(squash(copy.previewBotUsernameNote)));
        pass('preview-bot');
        await resetPage();
      }

      // ---------------------------------------------------------------- states: every reason the name cannot be changed
      if (run('states')) {
        for (const scenario of STATE_SCENARIOS) {
          stage = `${combo}:state-${scenario.state}`;
          world.getAnswer = () => scenario.get();
          await open(scenario.kind);
          const panel = dialog.getByTestId(`discord-sender-state-${scenario.state}`);
          await panel.waitFor();
          const [title, body, next] = STATE_TEXT[scenario.state].map(name => squash(copy[name]));
          const shown = squash(await panel.innerText());
          assert.ok(shown.includes(title) && shown.includes(body) && shown.includes(next), `${scenario.state} shows its own title, body and next step`);
          assert.ok(shown.includes(squash(copy.senderStateNextLabel)));
          assert.equal(await panel.getAttribute('data-state'), scenario.state);
          // Disabled controls explain themselves, stay reachable, and are announced.
          assert.equal(await saveButton.getAttribute('aria-disabled'), 'true'); assert.equal(await saveButton.isDisabled(), true);
          assert.equal(await reasonOf(), squash(copy.senderSaveWhyBlocked));
          assert.equal(await saveButton.getAttribute('disabled'), null, 'Save is aria-disabled, not removed from the tab order');
          assert.deepEqual(await page.evaluate(() => { const element = document.querySelector('[data-sender-status]'); return {role: element?.getAttribute('role'), live: element?.getAttribute('aria-live')}; }), {role: 'status', live: 'polite'});
          // Keyboard and screen reader land on the explanation.
          await until(async () => (await focused())?.heading === `discord-sender-state-${scenario.state}`, `focus on the ${scenario.state} heading`);
          if (['person_missing_manage_nicknames', 'person_role_below_bot', 'bot_missing_change_nickname', 'nickname_authority_other_workspace', 'edit_pending', 'session_reverification_required', 'bot_nickname_disabled', 'sender_names_disabled', 'not_authorizing_member'].includes(scenario.state)) {
            // A named profile is shown read-only; an unread one says it does not know the name.
            assert.notEqual(await nameBox.getAttribute('readonly'), null, 'the name is read-only');
            assert.equal(await nameBox.getAttribute('aria-readonly'), 'true');
            assert.equal(await dialog.getByRole('checkbox').count(), 0, 'no shared-nickname checkbox while the name cannot be changed');
          }
          if (['sender_names_disabled', 'not_authorizing_member', 'bot_nickname_disabled'].includes(scenario.state)) {
            assert.equal(await nameBox.inputValue(), ''); assert.equal(await nameBox.getAttribute('placeholder'), copy.senderNameNotKnown);
            assert.equal(world.gets.length, 1, 'one read, no retry');
            assert.equal(await dialog.locator('[data-sender-check-again]').count(), 0, 'the contract says do not retry these');
          }
          const again = dialog.locator('[data-sender-check-again]'), signIn = dialog.getByRole('button', {name: copy.senderSignInAgain, exact: true});
          assert.equal(await again.count(), scenario.again ? 1 : 0, `${scenario.state} check-again button`);
          assert.equal(await signIn.count(), scenario.signIn ? 1 : 0, `${scenario.state} sign-in button`);
          if (scenario.state === 'sender_names_disabled') {
            assert.equal(squash(await dialog.locator('[data-held-note]').innerText()), squash(copy.senderStateHeldNote), 'a webhook is told about posts held while the switch is off');
          }
          if (scenario.timed) {
            assert.match(squash(await dialog.locator('[data-recheck]').innerText()), new RegExp('^' + escapeRegExp(copy.senderRecheckIn).replace('\\{wait\\}', '.+').replace('\\{time\\}', '.+') + '$'));
            assert.equal(await dialog.locator('[data-recheck]').getAttribute('data-retry-after-seconds'), scenario.state === 'edit_pending' ? '90' : '60', 'the wait the server named is shown');
            assert.equal(await again.getAttribute('aria-disabled'), 'true', 'a timed state cannot be re-read before its time');
            assert.ok(await again.getAttribute('aria-describedby'));
          }
          assert.equal(world.posts.length, 0, 'a state is found without writing anything');
          await assertFits(scenario.state);
          if (scenario.state === 'bot_nickname_disabled') await shot(page, 'state-bot-nickname-disabled', {tall: true, evidence: locale === 'en' && width === 390});
          if (scenario.state === 'person_missing_manage_nicknames') await shot(page, 'state-person-missing-manage-nicknames', {tall: true, evidence: locale === 'en' && width === 1280});
          if (scenario.state === 'edit_pending') await shot(page, 'state-edit-pending', {tall: true, evidence: locale === 'zh-Hant'});
          await closeDialog();
          pass(`state-${scenario.state}`);
          reset();
        }
        pass('state-blocked-controls-explain');

        // Several reasons at once: each gets its own panel, in the server's order, and one set of buttons.
        stage = combo + ':several-reasons';
        world.getAnswer = () => ({body: blockedProfile('bot', BOT, ['person_role_below_bot', 'bot_missing_change_nickname', 'nickname_authority_other_workspace'])});
        await open('bot');
        await dialog.getByTestId('discord-sender-state-person_role_below_bot').waitFor();
        assert.deepEqual(await dialog.locator('[data-discord-sender-state]').evaluateAll(items => items.map(item => item.getAttribute('data-state'))), ['person_role_below_bot', 'bot_missing_change_nickname', 'nickname_authority_other_workspace']);
        assert.equal(await dialog.locator('[data-sender-check-again]').count(), 1);
        await assertFits('several reasons');
        await resetPage(); pass('state-several-reasons');

        // Check again is a read: it asks the server again, never writes, and the form returns when the cause is gone.
        stage = combo + ':check-again';
        world.getAnswer = () => ({body: blockedProfile('bot', BOT, ['person_missing_manage_nicknames'])});
        await open('bot');
        await dialog.getByTestId('discord-sender-state-person_missing_manage_nicknames').waitFor();
        assert.equal(world.gets.length, 1);
        world.getAnswer = null;
        await dialog.locator('[data-sender-check-again]').click();
        await loaded('Acme Weekly');
        assert.equal(world.gets.length, 2); assert.equal(world.posts.length, 0);
        assert.equal(await dialog.locator('[data-discord-sender-state]').count(), 0);
        assert.equal(await nameBox.getAttribute('readonly'), null);
        await until(async () => (await focused())?.field === true, 'focus on the field after a check');
        await edit('Concert helper', true);
        assert.equal(await saveButton.isDisabled(), false);
        pass('state-check-again-is-a-read');
        await resetPage();

        // A pending change names its time; the button wakes up at it, and one more read follows.
        stage = combo + ':pending-countdown';
        let pendingReads = 0;
        world.getAnswer = () => (++pendingReads === 1 ? {status: 409, body: {error: 'A sender-name change is pending.', code: 'discord_sender_edit_pending', retryAfterSeconds: 2}} : null);
        await open('bot');
        await dialog.getByTestId('discord-sender-state-edit_pending').waitFor();
        const wait = dialog.locator('[data-sender-check-again]');
        assert.equal(await wait.getAttribute('aria-disabled'), 'true');
        await until(async () => (await wait.getAttribute('aria-disabled')) === 'false', 'the check button wakes at the retry time');
        await wait.click(); await loaded('Acme Weekly');
        assert.equal(world.gets.length, 2); assert.equal(world.posts.length, 0);
        pass('state-pending-countdown');
        await resetPage();
      }

      // ---------------------------------------------------------------- the default: both switches off, and the cards
      if (run('cards')) {
        const provider = flags => ({id: 'discord', platform: 'Discord', configured: true, connectReady: true, productionReviewed: true, discordConnectionsV2: true,
          capabilities: {identity: true, publish: true}, setupIssues: [], discordModes: {webhook: {enabled: false, status: 'unavailable'}, userInstall: {enabled: false, status: 'unavailable'}},
          ...(flags ? {discordSenderNames: flags} : {})});
        const hint = page.locator('[data-discord-sender-edit-hint]');
        const hintOf = async button => { const id = await button.getAttribute('aria-describedby'); return id ? squash(await page.evaluate(i => document.getElementById(i)?.innerText ?? '', id)) : null; };

        // The default at the opening: a clean read-only explanation. No error styling, no retry, no polling.
        stage = combo + ':default-off';
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await hookButton.waitFor();
        assert.equal(await hint.count(), 0, 'nothing is claimed about the switches before one is known');
        const bothOff = {senderNames: false, botNickname: false};
        world.getAnswer = id => ({body: blockedProfile(id === BOT ? 'bot' : 'webhook', id, ['sender_names_disabled'], {...unread, feature: bothOff})});
        await open('bot');
        const panel = dialog.getByTestId('discord-sender-state-sender_names_disabled'); await panel.waitFor();
        assert.equal(await panel.getAttribute('role'), null, 'a state found on open is announced politely, not as an alert');
        assert.equal(await dialog.getByRole('alert').count(), 0);
        assert.equal(await dialog.locator('[data-sender-check-again], [data-sender-refusal], [data-sender-issues], [data-sender-rules], [data-sender-count]').count(), 0, 'no retry and no editing aids in a read-only view');
        assert.equal(await panel.evaluate(element => [element, ...element.querySelectorAll('*')].some(node => /destructive|red-/.test(String(node.className)))), false, 'no error styling');
        assert.equal(await dialog.locator('[data-held-note]').count(), 0, 'the held-post sentence is about webhooks');
        assert.equal(await dialog.locator('[data-sender-mode="bot"]').count(), 1);
        const reads = world.gets.length;
        await sleep(1500);
        assert.equal(world.gets.length, reads, 'no polling'); assert.equal(world.posts.length, 0);
        pass('default-off-is-read-only-view');
        // The first read taught the page the switches: every card now says so under its button, without being opened.
        await closeDialog();
        await until(async () => (await hint.count()) === 2, 'both cards learn that sender names are off');
        for (const button of [hookButton, botButton]) assert.equal(await hintOf(button), squash(copy.senderCardOff));
        // A bot-only switch touches the bot card alone (webhook names do not depend on it).
        world.getAnswer = id => ({body: blockedProfile('bot', id, ['bot_nickname_disabled'], {...unread, feature: {senderNames: true, botNickname: false}})});
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await botButton.waitFor();
        assert.equal(await hint.count(), 0, 'a fresh page knows nothing yet');
        await open('bot');
        await dialog.getByTestId('discord-sender-state-bot_nickname_disabled').waitFor();
        await closeDialog();
        await until(async () => (await hint.count()) === 1, 'only the bot card learns');
        assert.equal(await hintOf(botButton), squash(copy.senderCardOff)); assert.equal(await hookButton.getAttribute('aria-describedby'), null);
        pass('card-hint-learned-from-read');
        await resetPage();

        // The server can send the switches with the providers: then the first paint already says it, with no request.
        stage = combo + ':card-hint';
        world.providers = [provider({senderNames: true, botNickname: false})];
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await botButton.waitFor();
        await until(async () => (await hint.count()) === 1, 'the provider switches reach the card');
        assert.equal(await hintOf(botButton), squash(copy.senderCardOff)); assert.equal(await hookButton.getAttribute('aria-describedby'), null);
        assert.equal(world.gets.length, 0, 'the connections page reads no sender name');
        // The button still opens the explanation, which asks the server (a cheap answer without Discord).
        world.getAnswer = id => ({body: blockedProfile('bot', id, ['bot_nickname_disabled'], {...unread, feature: {senderNames: true, botNickname: false}})});
        await open('bot'); await dialog.getByTestId('discord-sender-state-bot_nickname_disabled').waitFor();
        assert.equal(world.gets.length, 1);
        pass('card-hint-from-provider');
        await resetPage();
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await hookButton.waitFor();
      }

      // ---------------------------------------------------------------- failures after a save attempt
      if (run('failures')) {
        // Stale: someone else changed it meanwhile. Nothing is retried; a reload (a read) brings the new fingerprint.
        stage = combo + ':failure-stale';
        await openLoaded('bot');
        const before = world.profiles[BOT].fingerprint, changed = hash('someone-else-changed-it');
        world.profiles[BOT] = {...world.profiles[BOT], fingerprint: changed, name: 'Changed elsewhere', effectiveName: 'Changed elsewhere', observedName: 'Changed elsewhere', externalChange: true, savedName: 'Acme Weekly'};
        await edit('Another name', true);
        await saveButton.click();
        const stale = dialog.getByTestId('discord-sender-state-stale'); await stale.waitFor();
        assert.equal(await stale.getAttribute('role'), 'alert');
        assert.equal(world.posts.length, 1); assert.equal(world.posts[0].body.fingerprint, before);
        assert.equal(await saveButton.getAttribute('aria-disabled'), 'true'); assert.equal(await nameBox.count(), 0, 'the form is gone until a reload');
        const getsBefore = world.gets.length;
        await dialog.getByRole('button', {name: copy.senderReload, exact: true}).click();
        await loaded('Changed elsewhere');
        assert.equal(world.posts.length, 1, 'reload must not retry a write'); assert.equal(world.gets.length, getsBefore + 1);
        pass('failure-stale-reload-no-retry'); pass('state-stale');
        await dialog.locator('[data-sender-external-change]').waitFor();
        await edit('Another name', true);
        await saveButton.click();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 2); assert.equal(world.posts[1].body.fingerprint, changed, 'the second save uses the fingerprint from the reload');
        pass('failure-reload-uses-new-fingerprint');
        await resetPage();

        // The generic failure keeps the long-standing wording and still only offers a reload.
        stage = combo + ':failure-generic';
        await openLoaded('bot');
        world.postAnswer = () => ({status: 409, body: {error: 'The server nickname changed during verification.', code: 'something_new'}});
        await edit('Another name', true); await saveButton.click();
        await dialog.getByRole('alert').filter({hasText: copy.senderSaveFailed}).waitFor();
        assert.equal(await saveButton.isDisabled(), true);
        const posted = world.posts.length;
        await dialog.getByRole('button', {name: copy.senderReload, exact: true}).click();
        await loaded('Acme Weekly');
        assert.equal(world.posts.length, posted, 'Reload must not retry a write');
        pass('state-failed');
        await resetPage();

        // A fresh sign-in is needed: the buttons and words of the long-standing flow.
        stage = combo + ':failure-session';
        await openLoaded('bot');
        world.postAnswer = () => ({status: 403, body: {error: 'Sign in again.', code: 'step_up_required'}});
        await edit('Fresh session needed', true); await saveButton.click();
        await dialog.getByRole('alert').filter({hasText: copy.senderSessionError}).waitFor();
        await dialog.getByRole('button', {name: copy.senderSignInAgain, exact: true}).waitFor();
        assert.equal(await dialog.getByTestId('discord-sender-state-session_reverification_required').count(), 1);
        pass('failure-fresh-session');
        await resetPage();

        // The server refuses at write time with reasons (a switch flipped, a permission removed meanwhile).
        stage = combo + ':failure-unavailable';
        await openLoaded('bot');
        world.postAnswer = () => ({status: 409, body: {error: 'This Discord sender name cannot be changed right now.', code: 'discord_sender_name_unavailable', reasons: [{code: 'bot_nickname_disabled'}]}});
        await edit('Another name', true); await saveButton.click();
        await dialog.getByTestId('discord-sender-state-bot_nickname_disabled').waitFor();
        assert.equal(await dialog.locator('[data-sender-check-again]').count(), 0);
        pass('failure-post-unavailable');
        await resetPage();

        // The server disagrees with the browser about a name: the form stays, with the server's rule, and the fingerprint is kept.
        stage = combo + ':failure-server-rule';
        await openLoaded('webhook');
        world.postAnswer = () => ({status: 400, body: {error: 'Choose a name...', code: 'discord_sender_name_invalid', reason: 'reserved_word', maxLength: 80}});
        await edit('Concert Series'); await saveButton.click();
        const refusal = dialog.locator('[data-sender-refusal]'); await refusal.waitFor();
        assert.equal(squash(await refusal.innerText()), squash(copy.senderIssueReserved));
        assert.equal(await nameBox.count(), 1);
        world.postAnswer = null;
        await edit('Concert Series 2'); await saveButton.click();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 2); assert.equal(world.posts[0].body.fingerprint, world.posts[1].body.fingerprint, 'a pre-write refusal keeps the fingerprint');
        pass('failure-server-rule-keeps-form');
        await resetPage();
      }

      // ---------------------------------------------------------------- protection against repeated actions
      if (run('protect')) {
        stage = combo + ':protect';
        await openLoaded('webhook');
        world.hold = true;
        await nameBox.fill('Double click');
        await saveButton.dblclick();
        await until(() => Boolean(world.release), 'held save');
        await sleep(300);
        assert.equal(world.posts.length, 1, 'a double click sends one write');
        world.hold = false; world.release(); world.release = null;
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 1);
        pass('protect-double-click');
        world.hold = true;
        await nameBox.fill('Enter twice');
        await nameBox.focus(); await page.keyboard.press('Enter');
        await until(() => Boolean(world.release), 'held save by Enter');
        await page.keyboard.press('Enter'); await sleep(300);
        assert.equal(world.posts.length, 2, 'Enter twice sends one write');
        world.hold = false; world.release();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        pass('protect-enter-twice');
        await resetPage();
      }

      // ---------------------------------------------------------------- keyboard
      if (run('keyboard')) {
        stage = combo + ':keyboard';
        await hookButton.focus(); await page.keyboard.press('Enter');
        await dialog.waitFor(); await loaded('Acme Weekly');
        await until(async () => (await focused())?.field === true, 'focus on the field');
        await page.keyboard.press('Control+A'); await page.keyboard.type('Keyboard only');
        assert.equal(await nameBox.inputValue(), 'Keyboard only');
        const order = [];
        for (let i = 0; i < 4; i++) { await page.keyboard.press('Tab'); const f = await focused(); order.push(f?.theme ?? (f?.save ? 'save' : f?.text)); }
        assert.deepEqual(order, ['dark', 'light', copy.senderClose, 'save'], 'tab order: theme switch, Close, Save');
        pass('keyboard-tab-order');
        await page.keyboard.press('Enter');
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 1); assert.equal(world.posts[0].body.name, 'Keyboard only');
        pass('keyboard-open-type-save');
        await page.keyboard.press('Escape'); await dialog.waitFor({state: 'detached'});
        await until(async () => (await focused())?.label === `${copy.senderEdit} · ${hook.account}`, 'focus back after Escape');
        pass('keyboard-escape-returns-focus');
        reset();
        // A bot: the shared-nickname box is on the keyboard path.
        await botButton.focus(); await page.keyboard.press('Enter'); await dialog.waitFor(); await loaded('Acme Weekly');
        await page.keyboard.press('Control+A'); await page.keyboard.type('Keyboard bot');
        for (let i = 0; i < 3; i++) await page.keyboard.press('Tab');
        assert.equal((await focused())?.type, 'checkbox');
        await page.keyboard.press('Space');
        assert.equal(await dialog.getByRole('checkbox').isChecked(), true);
        await resetPage();
        // A blocked state: the explanation takes focus, the next Tab reaches the way forward.
        world.getAnswer = () => ({body: blockedProfile('bot', BOT, ['bot_missing_change_nickname'])});
        await botButton.focus(); await page.keyboard.press('Enter'); await dialog.waitFor();
        await until(async () => (await focused())?.heading === 'discord-sender-state-bot_missing_change_nickname', 'focus on the explanation');
        await page.keyboard.press('Tab');
        assert.equal((await focused())?.again, true, 'Tab from the explanation reaches Check again');
        world.getAnswer = null;
        await page.keyboard.press('Enter');
        await loaded('Acme Weekly');
        pass('keyboard-state-actions');
        await resetPage();
      }

      // ---------------------------------------------------------------- the schedule dialog
      if (run('schedule')) {
        stage = combo + ':schedule';
        world.variants = [{...input.variant, text: 'Line one\n\nLine three: doors open at 7 https://example.test/very/long/path/that/must/wrap/without/overflowing/the/dialog/at/phone/width/' + 'x'.repeat(40)}];
        hook.discordSenderName = 'D Festival 公告';
        await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
        await page.getByRole('button', {name: 'Schedule a draft', exact: true}).click();
        await dialog.waitFor();
        await dialog.getByRole('combobox', {name: 'Draft', exact: true}).selectOption(input.variant.id);
        await dialog.getByRole('combobox', {name: 'Account', exact: true}).selectOption(hook.id);
        const preview = dialog.locator('[data-discord-message-preview]');
        await preview.waitFor();
        assert.equal(await preview.getAttribute('data-kind'), 'webhook');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), 'D Festival 公告');
        assert.equal(await preview.getAttribute('data-name-source'), 'saved');
        assert.equal(squash(await preview.locator('[data-preview-app-tag]').innerText()), copy.previewAppTag);
        const hookNotes = squash(await preview.locator('[data-preview-notes]').innerText());
        assert.ok(hookNotes.includes(squash(copy.previewWebhookNote)) && hookNotes.includes(squash(copy.previewCompactNote)));
        pass('schedule-preview-webhook');
        const lines = await preview.locator('[data-preview-body]').evaluate(element => ({text: element.textContent, white: getComputedStyle(element).whiteSpace}));
        assert.ok(lines.text.startsWith('Line one\n\nLine three: doors open at 7 https://example.test/'), 'the draft text keeps its line breaks');
        assert.equal(lines.white, 'pre-wrap');
        await dialog.locator('input[type="datetime-local"]').fill('2031-03-04T09:05');
        await until(async () => /2031/.test(await preview.locator('[data-preview-time]').innerText()), 'planned time in the preview');
        assert.equal(await preview.locator('[data-preview-time]').getAttribute('datetime'), '2031-03-04T09:05:00.000Z');
        await assertFits('schedule dialog webhook');
        pass('schedule-preview-lines-and-time');
        await shot(page, 'schedule-dialog-preview', {tall: true, evidence: locale === 'en' && width === 1280 || locale === 'zh-Hant'});
        await dialog.getByRole('combobox', {name: 'Account', exact: true}).selectOption(bot.id);
        await until(async () => (await preview.getAttribute('data-kind')) === 'bot', 'bot preview');
        assert.equal(await preview.getAttribute('data-name-source'), 'unknown');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), copy.previewBotNameUnknown);
        assert.equal(await preview.locator('[data-preview-author]').getAttribute('data-placeholder'), 'true');
        const botNotes = squash(await preview.locator('[data-preview-notes]').innerText());
        assert.ok(botNotes.includes(squash(copy.previewBotNote)) && botNotes.includes(squash(copy.previewBotNameUnknownNote)));
        assert.ok(!botNotes.includes(squash(copy.previewWebhookNote)));
        await assertFits('schedule dialog bot');
        pass('schedule-preview-bot');
        await page.keyboard.press('Escape'); await dialog.waitFor({state: 'detached'});
        world.variants = []; delete hook.discordSenderName;
      }

      // ---------------------------------------------------------------- review cards
      if (run('review')) {
        stage = combo + ':review';
        const future = Math.floor(Date.now() / 1000) + 30 * 86400;
        const reviewFor = (kind, name) => {
          const review = structuredClone(input.review);
          review.id = 'synthetic-review-' + kind;
          review.manifest.platform = 'Discord'; review.manifest.channelId = kind === 'webhook' ? hook.id : bot.id; review.manifest.senderKind = kind;
          review.manifest.payload = {...review.manifest.payload, text: 'First line\nSecond line @ the stage door'};
          review.manifest.expiresAt = future + 7200;
          review.manifest.timing = {...review.manifest.timing, timestamp: future, utc: new Date(future * 1000).toISOString(), local: new Date(future * 1000).toISOString().slice(0, 16)};
          if (name) review.manifest.discordSenderName = name; else delete review.manifest.discordSenderName;
          return review;
        };
        for (const kind of ['webhook', 'bot']) {
          world.reviews = [reviewFor(kind, kind === 'webhook' ? 'D Festival 公告' : null)];
          await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
          const preview = page.locator('[data-discord-message-preview]').first();
          await preview.waitFor();
          assert.equal(await preview.getAttribute('data-kind'), kind);
          const notes = squash(await preview.locator('[data-preview-notes]').innerText());
          if (kind === 'webhook') {
            assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), 'D Festival 公告');
            assert.ok(notes.includes(squash(copy.previewWebhookNote)) && !notes.includes(squash(copy.previewBotNote)));
          } else {
            assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), copy.previewBotNameUnknown);
            assert.ok(notes.includes(squash(copy.previewBotNote)) && !notes.includes(squash(copy.previewWebhookNote)));
          }
          assert.equal(squash(await preview.locator('[data-preview-app-tag]').innerText()), copy.previewAppTag);
          assert.equal(await preview.locator('[data-preview-body]').evaluate(element => element.textContent), 'First line\nSecond line @ the stage door');
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `review ${kind} overflow`);
          pass(`review-preview-${kind}`);
        }
        world.reviews = [];
      }

      // ---------------------------------------------------------------- layout, motion, requests
      if (run('layout')) {
        stage = combo + ':layout';
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await hookButton.waitFor();
        for (const kind of ['webhook', 'bot']) {
          reset();
          const long = 'W'.repeat(kind === 'webhook' ? 80 : 32);
          await openLoaded(kind);
          await nameBox.fill(long);
          await assertFits(`${kind} with an unbroken ${long.length}-character name`);
          assert.equal(await dialog.locator('[data-preview-author]').evaluate(element => element.getBoundingClientRect().right <= element.closest('[data-preview-message]').getBoundingClientRect().right + 1), true, 'a long name wraps inside the message box');
          await nameBox.fill('這是一個很長的名稱'.repeat(8).slice(0, kind === 'webhook' ? 72 : 30));
          await assertFits(`${kind} with a long CJK name`);
          await closeDialog();
        }
        pass('long-values-wrap');
        reset();
        await openLoaded('webhook');
        await assertFits('editor'); pass('no-horizontal-overflow');
        // Reduced motion is on for this context, and nothing of the editor animates under it.
        const motion = await page.evaluate(() => ({
          reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
          animated: [...document.querySelectorAll('[data-discord-message-preview], [data-discord-message-preview] *, [data-sender-status] *')]
            .filter(element => getComputedStyle(element).animationName !== 'none' || parseFloat(getComputedStyle(element).transitionDuration) > 0.01).length
        }));
        assert.deepEqual(motion, {reduced: true, animated: 0}); pass('reduced-motion');
        await resetPage();
      }

      // ---------------------------------------------------------------- once per run: dark scheme, axe, evidence
      if (locale === 'en' && width === 1280 && run('layout')) {
        stage = combo + ':dark-and-axe';
        reset();
        const darkContext = await newContext({colorScheme: 'dark'});
        await darkContext.route('**/*', handle);
        const dark = await darkContext.newPage(); dark.setDefaultTimeout(30000);
        await dark.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await dark.getByRole('button', {name: `${copy.senderEdit} · ${hook.account}`, exact: true}).click();
        const darkDialog = dark.getByRole('dialog');
        const darkName = darkDialog.getByRole('textbox', {name: copy.senderNameLabel, exact: true});
        await until(() => darkName.inputValue().then(v => v === 'Acme Weekly').catch(() => false), 'dark editor loaded');
        await until(async () => (await darkDialog.locator('[data-discord-message-preview]').getAttribute('data-theme')) === 'dark', 'preview follows the dark scheme');
        once.add('dark-scheme-follows-app');
        await dark.addScriptTag({path: require.resolve('axe-core/axe.min.js')});
        const axeOf = async (target, selector) => (await target.evaluate(([sel]) => axe.run(document.querySelector(sel), {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}}), [selector]))
          .violations.map(v => `${v.id}: ${v.nodes.slice(0, 2).map(n => n.target.join(' ')).join(' | ')}`);
        assert.deepEqual(await axeOf(dark, '[data-testid="discord-sender-dialog"]'), [], 'axe: editor in the dark scheme');
        once.add('axe-editor-dark');
        await shot(dark, 'webhook-editor-dark-app', {tall: true, evidence: true});
        await darkContext.close();
        reset();
        await openLoaded('webhook');
        await page.addScriptTag({path: require.resolve('axe-core/axe.min.js')});
        assert.deepEqual(await axeOf(page, '[data-testid="discord-sender-dialog"]'), [], 'axe: editor in the light scheme');
        once.add('axe-editor-light');
        await resetPage();
        world.getAnswer = () => ({body: blockedProfile('bot', BOT, ['person_missing_manage_nicknames'])});
        await open('bot'); await dialog.getByTestId('discord-sender-state-person_missing_manage_nicknames').waitFor();
        assert.deepEqual(await axeOf(page, '[data-testid="discord-sender-dialog"]'), [], 'axe: a blocked state');
        once.add('axe-blocked-state');
        await resetPage();
        once.add('evidence-screenshots');
      }

      // ---------------------------------------------------------------- nothing but the sender-name routes was written
      assert.deepEqual(world.unexpected, [], 'The sender editor must never publish, connect or approve posts');
      assert.equal(world.blocked, 0, 'No request left the isolated app');
      pass('no-unexpected-requests');
      await context.close();
      await browser.close(); browser = null;
    }

    stage = 'receipt';
    let receipt;
    if (WANT) {
      receipt = {status: 'subset', note: 'RAFII_SENDER_CASES narrowed this run; it is not evidence', groups: [...WANT], browserVersion, cases: Object.fromEntries(Object.entries(ran).map(([combo, names]) => [combo, [...names].sort()]))};
    } else {
      for (const [locale, width] of combos) {
        const combo = `${locale}-${width}`;
        assert.deepEqual([...ran[combo]].sort(), [...REQUIRED_CASES].sort(), `${combo}: every required case must have run`);
      }
      assert.deepEqual([...once].sort(), [...ONCE_CASES].sort(), 'every once-per-run case must have run');
      receipt = {status: 'pass', browserVersion, combos: combos.map(([locale, width]) => `${locale}-${width}`), casesPerCombo: REQUIRED_CASES.length, onceCases: [...once].sort()};
    }
    writeFileSync(join(outDir, 'results.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify(receipt));
  } catch (error) {
    console.error(JSON.stringify({status: 'fail', stage, error: String(error && error.message || error).slice(0, 1500), server: tail.slice(-800)})); process.exitCode = 1;
  } finally {
    if (browser) await browser.close(); app.kill('SIGTERM');
  }
})();
