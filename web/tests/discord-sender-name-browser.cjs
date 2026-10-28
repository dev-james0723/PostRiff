/**
 * Actual app UI, synthetic APIs only (contract v2, docs/sender-name/UI-API-CONTRACT.md; the `ceiling` group follows
 * docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md). No Discord credentials or provider IO: every API response
 * comes from this file, and every off-origin request is blocked.
 *
 * Each locale and width runs every case group; the receipt lists the cases that really ran and the run fails when one
 * is missing (REQUIRED_CASES / ONCE_CASES), so a skipped block cannot pass silently. In CI nothing narrows the run.
 * While developing, RAFII_SENDER_CASES=core,states (groups) and RAFII_SENDER_COMBOS=en-1280 (locale-width) narrow the run
 * and the receipt says so (such a run is not evidence).
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
/** The hourly ceiling's refusal exactly as the contract shows it (409, code, limit, windowSeconds, no retry field). */
const ceilingContract = JSON.parse(readFileSync(join(__dirname, 'fixtures/discord-hourly-ceiling-contract.json')));
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
  'webhook-reset', 'webhook-reset-focus-and-no-double-post', 'bot-hold-note-and-warning', 'bot-hold-note-absent-when-switch-off', 'validation-joiner-accepted',
  'schedule-preview-bot-nickname', 'review-preview-bot-recorded-nickname',
  'validation-too-long', 'validation-surrounding-space', 'validation-spacing', 'validation-forbidden-character', 'validation-url-like', 'validation-reserved-word',
  'validation-control-or-format', 'validation-not-normalized', 'validation-empty', 'validation-emoji-counts-two', 'validation-clears', 'counter-limits',
  'preview-webhook', 'preview-bot', 'preview-live-update', 'preview-theme-toggle', 'preview-contrast',
  'state-write_refused', 'state-write_rate_limited', 'state-evidence_invalid', 'state-sender_names_disabled', 'state-bot_nickname_disabled', 'state-provider_unavailable', 'state-not_authorizing_member', 'state-session_reverification_required', 'state-person_missing_manage_nicknames',
  'state-person_role_below_bot', 'state-bot_missing_change_nickname', 'state-nickname_authority_other_workspace', 'state-edit_pending', 'state-reconnect_required',
  'state-rate_limited', 'state-rate_delayed', 'state-upstream_unavailable', 'state-workspace_permission', 'state-stale', 'state-failed', 'state-write_unconfirmed', 'state-several-reasons', 'state-check-again-is-a-read',
  'state-pending-countdown', 'state-blocked-controls-explain', 'read-only-view-is-quiet',
  'card-nothing-when-off', 'card-nothing-without-flags', 'card-offered-when-on', 'card-flags-are-per-kind',
  'bot-verify-action', 'queue-hold-verify-action', 'validation-reserved-by-kind', 'webhook-without-own-name-works',
  'failure-stale-reload-no-retry', 'failure-fresh-session', 'failure-post-unavailable', 'failure-server-rule-keeps-form', 'failure-reload-uses-new-fingerprint',
  'protect-double-click', 'protect-enter-twice', 'protect-pending-close', 'protect-escape-while-saving',
  'keyboard-open-type-save', 'keyboard-tab-order', 'keyboard-escape-returns-focus', 'keyboard-state-actions',
  'schedule-preview-webhook', 'schedule-preview-bot', 'schedule-preview-lines-and-time',
  'review-preview-webhook', 'review-preview-bot',
  'no-horizontal-overflow', 'long-values-wrap', 'reduced-motion', 'no-unexpected-requests',
  'ceiling-single-dialog', 'ceiling-single-uses-server-limit', 'ceiling-single-unknown-code', 'ceiling-bulk-keeps-selection', 'ceiling-bulk-remove-then-approve', 'ceiling-bulk-unknown-code',
  'ceiling-reply-dialog', 'ceiling-reply-unknown-code', 'ceiling-decision-dialog', 'ceiling-decision-unknown-code', 'ceiling-run-card-text', 'ceiling-no-page-errors'
];
// Recorded once per run (English at 1280 px), because they do not depend on locale or width.
const ONCE_CASES = ['dark-scheme-follows-app', 'axe-editor-light', 'axe-editor-dark', 'axe-blocked-state', 'axe-ceiling', 'evidence-screenshots'];
const WANT = process.env.RAFII_SENDER_CASES ? new Set(process.env.RAFII_SENDER_CASES.split(',')) : null;
const ONLY = process.env.RAFII_SENDER_COMBOS ? new Set(process.env.RAFII_SENDER_COMBOS.split(',')) : null;
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
  provider_unavailable: ['senderStateProviderUnavailableTitle', 'senderStateProviderUnavailableBody', 'senderStateProviderUnavailableNext'],
  not_authorizing_member: ['senderStateNotAuthorizingMemberTitle', 'senderStateNotAuthorizingMemberBody', 'senderStateNotAuthorizingMemberNext'],
  session_reverification_required: ['senderStateSessionReverificationRequiredTitle', 'senderSessionError', 'senderStateSessionReverificationRequiredNext'],
  person_missing_manage_nicknames: ['senderStatePersonMissingManageNicknamesTitle', 'senderStatePersonMissingManageNicknamesBody', 'senderStatePersonMissingManageNicknamesNext'],
  person_role_below_bot: ['senderStatePersonRoleBelowBotTitle', 'senderStatePersonRoleBelowBotBody', 'senderStatePersonRoleBelowBotNext'],
  bot_missing_change_nickname: ['senderStateBotMissingChangeNicknameTitle', 'senderStateBotMissingChangeNicknameBody', 'senderStateBotMissingChangeNicknameNext'],
  nickname_authority_other_workspace: ['senderStateNicknameAuthorityOtherWorkspaceTitle', 'senderStateNicknameAuthorityOtherWorkspaceBody', 'senderStateNicknameAuthorityOtherWorkspaceNext'],
  edit_pending: ['senderStateEditPendingTitle', 'senderChangePending', 'senderStateEditPendingNext'],
  stale: ['senderStateStaleTitle', 'senderStateStaleBody', 'senderStateStaleNext'],
  write_unconfirmed: ['senderStateWriteUnconfirmedTitle', 'senderStateWriteUnconfirmedBody', 'senderStateWriteUnconfirmedNext'],
  write_refused: ['senderStateWriteRefusedTitle', 'senderStateWriteRefusedBody', 'senderStateWriteRefusedNext'],
  write_rate_limited: ['senderStateWriteRateLimitedTitle', 'senderStateWriteRateLimitedBody', 'senderStateWriteRateLimitedNext'],
  evidence_invalid: ['senderStateEvidenceInvalidTitle', 'senderStateEvidenceInvalidBody', 'senderStateEvidenceInvalidNext'],
  reconnect_required: ['senderStateReconnectRequiredTitle', 'senderStateReconnectRequiredBody', 'senderStateReconnectRequiredNext'],
  rate_limited: ['senderStateRateLimitedTitle', 'senderStateRateLimitedBody', 'senderStateRateLimitedNext'],
  rate_delayed: ['senderStateRateDelayedTitle', 'senderStateRateDelayedBody', 'senderStateRateDelayedNext'],
  upstream_unavailable: ['senderStateUpstreamUnavailableTitle', 'senderStateUpstreamUnavailableBody', 'senderStateUpstreamUnavailableNext'],
  workspace_permission: ['senderStateWorkspacePermissionTitle', 'senderStateWorkspacePermissionBody', 'senderStateWorkspacePermissionNext'],
  failed: ['senderStateFailedTitle', 'senderSaveFailed', 'senderStateFailedNext']
};
assert.equal(Object.keys(STATE_TEXT).length, 21);
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
      queuedPostsKeepApprovedName: webhook, queuedBotPostsHoldIfNicknameChanges: !webhook}, ...extra};
}
const blockedProfile = (kind, id, codes, extra = {}) => profile(kind, id, {editable: false, unavailable: codes.map(code => typeof code === 'string' ? {code} : code), ...extra});
/** The contract's early answers, made without reading Discord: no name, no observation time. */
const unread = {name: '', effectiveName: null, observedName: null, observedAt: null, nameSource: 'none'};

/**
 * The Discord entry of the provider view. `webhook.enabled` is the connect route (closed at the opening); the sender-name flags are
 * `bot.nickname.enabled` and `webhook.senderName.enabled`, and a missing flag is not a yes.
 */
const providerFor = ({bot, webhook} = {}) => ({id: 'discord', platform: 'Discord', configured: true, connectReady: true, productionReviewed: true, discordConnectionsV2: true,
  capabilities: {identity: true, publish: true}, setupIssues: [],
  discordModes: {...(bot === undefined ? {} : {bot: {senderKind: 'bot', nickname: {enabled: bot}}}),
    webhook: {enabled: false, status: 'unavailable', ...(webhook === undefined ? {} : {senderName: {enabled: webhook}})}, userInstall: {enabled: false, status: 'unavailable'}}});

/** Every availability state a GET can reach, how the synthetic server gets there, and on which kind of connection. */
const STATE_SCENARIOS = [
  {state: 'sender_names_disabled', kind: 'webhook', get: () => ({body: blockedProfile('webhook', HOOK, ['sender_names_disabled'], {...unread, feature: {senderNames: false, botNickname: false}})})},
  {state: 'bot_nickname_disabled', kind: 'bot', get: () => ({body: blockedProfile('bot', BOT, ['bot_nickname_disabled'], {...unread, feature: {senderNames: true, botNickname: false}})})},
  {state: 'provider_unavailable', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['provider_unavailable'], unread)})},
  {state: 'not_authorizing_member', kind: 'bot', get: () => ({body: blockedProfile('bot', BOT, ['not_authorizing_member'], unread)})},
  {state: 'session_reverification_required', kind: 'webhook', signIn: true, get: () => ({body: blockedProfile('webhook', HOOK, ['session_reverification_required'])})},
  {state: 'person_missing_manage_nicknames', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['person_missing_manage_nicknames'])})},
  {state: 'person_role_below_bot', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['person_role_below_bot'])})},
  {state: 'bot_missing_change_nickname', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['bot_missing_change_nickname'])})},
  {state: 'nickname_authority_other_workspace', kind: 'bot', again: true, get: () => ({body: blockedProfile('bot', BOT, ['nickname_authority_other_workspace'])})},
  {state: 'edit_pending', kind: 'bot', again: true, timed: true, wait: 90, get: () => ({body: blockedProfile('bot', BOT, [{code: 'edit_pending', retryAfterSeconds: 90}])})},
  {state: 'reconnect_required', kind: 'webhook', again: true, get: () => ({status: 409, body: {error: 'Reconnect this Discord connection before changing its sender name.', code: 'discord_connection_required'}})},
  {state: 'rate_limited', kind: 'webhook', again: true, timed: true, wait: 540, get: () => ({status: 429, body: {error: 'Too many sender-name requests.', code: 'rate_limited', retryAfterSeconds: 540}})},
  {state: 'evidence_invalid', kind: 'bot', again: true, get: () => ({status: 409, body: {error: 'Discord’s answer about the server was not usable.', code: 'discord_sender_evidence_invalid'}})},
  {state: 'rate_delayed', kind: 'webhook', again: true, timed: true, wait: 45, get: () => ({status: 429, body: {error: 'Discord is waiting for shared request capacity. Try again shortly; nothing was changed.', code: 'discord_rate_delayed', retryAfterSeconds: 45}})},
  {state: 'upstream_unavailable', kind: 'webhook', again: true, get: () => ({status: 502, body: {error: 'Discord did not return a valid current sender name.', code: 'upstream_error'}})},
  {state: 'workspace_permission', kind: 'webhook', get: () => ({status: 403, body: {error: 'Workspace unavailable.', code: 'permission_denied'}})}
];

// ---------------------------------------------------------------------------------------------------------------
(async () => {
  let browser, browserVersion, stage = 'startup';
  const ran = {};
  const once = new Set();
  const combos = [['en', 1280], ['en', 390], ['zh-Hant', 390], ['zh-Hans', 1280]].filter(([locale, width]) => !ONLY || ONLY.has(`${locale}-${width}`));
  try {
    stage = 'warm';
    await warm('/app/channels'); await warm('/app/queue'); if (run('ceiling')) await warm('/app/automations');
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
      const world = {profiles: {}, gets: [], posts: [], unexpected: [], blocked: 0, version: 1, getAnswer: null, postAnswer: null, release: null, hold: false, variants: [], reviews: [], jobs: [], providers: [], verifies: [], verifyAnswer: null, activity: 0, preferences: {timeZone: 'UTC', locale},
        actions: [], actionAnswer: null, raffi: null, engagement: null};
      const reset = () => {
        world.profiles = {[HOOK]: profile('webhook', HOOK), [BOT]: profile('bot', BOT)};
        world.gets = []; world.posts = []; world.getAnswer = null; world.postAnswer = null; world.hold = false; world.release = null; world.jobs = []; world.verifies = []; world.verifyAnswer = null;
        world.providers = [providerFor({bot: true, webhook: true})];
        world.actions = []; world.actionAnswer = null; world.raffi = null; world.engagement = null;
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
          const names = Object.keys(body).sort().join(','), clearing = body.reset === true;
          const expected = clearing ? 'confirmed,fingerprint,reset' : current.senderKind === 'bot' ? 'confirmed,fingerprint,name,sharedServerConfirmed' : 'confirmed,fingerprint,name';
          if (names !== expected || body.confirmed !== true) return send({error: 'Review and confirm the sender name before saving.', code: 'discord_sender_name_unconfirmed'}, 400);
          if (world.hold) await new Promise(resolve => { world.release = resolve; });
          const answer = world.postAnswer?.(id, body);
          if (answer) return send(answer.body, answer.status ?? 200);
          if (body.fingerprint !== current.fingerprint) return send({error: 'Discord sender settings changed. Reload and review the name again.', code: 'discord_sender_name_required'}, 409);
          const webhook = current.senderKind === 'webhook';
          if (clearing) {
            if (!webhook) return send({error: 'A bot nickname cannot be cleared from Rafii; choose the nickname you want.', code: 'discord_sender_reset_unsupported'}, 400);
            world.profiles[id] = {...current, name: 'Acme Weekly', effectiveName: 'Acme Weekly', savedName: null, observedName: 'Acme Weekly', observedAt: 1800000100.5,
              nameSource: 'webhook_default', fingerprint: hash(id + '-' + (++world.version)), saved: true, reset: true, preview: {...current.preview, currentDisplayName: 'Acme Weekly'}};
            delete hook.discordSenderName;
            return send(world.profiles[id]);
          }
          world.profiles[id] = {...current, name: body.name, effectiveName: body.name, savedName: body.name, observedName: body.name, observedAt: 1800000100.5,
            nameSource: webhook ? 'saved_override' : 'observed_nickname', fingerprint: hash(id + '-' + (++world.version)), saved: true,
            preview: {...current.preview, currentDisplayName: body.name}};
          if (webhook) hook.discordSenderName = body.name;
          return send(world.profiles[id]);
        }
        // Approvals: a case sets `actionAnswer` to the refusal it wants to see. The synthetic server never approves anything.
        if (path === `/api/workspaces/${wid}/actions` && req.method() === 'POST') {
          const body = req.postDataJSON(); world.actions.push(body);
          const answer = world.actionAnswer?.(body);
          if (answer) return send(answer.body, answer.status);
          world.unexpected.push(`POST ${path} ${body.action}`); return send({error: 'Unexpected synthetic mutation', code: 'invalid_request'}, 400);
        }
        const engagement = /^\/api\/workspaces\/[^/]+\/channels\/[^/]+\/discord-engagement(?:\/(read|preview|approve))?$/.exec(path);
        if (engagement && world.engagement) {
          const state = world.engagement, step = engagement[1] ?? null;
          if (step === null && req.method() === 'GET') return send(state.status);
          if (step === 'read' && req.method() === 'POST') return send(state.inbox);
          if (step === 'preview' && req.method() === 'POST') {
            const body = req.postDataJSON(), number = ++state.previews, stamp = body.localTime ? Math.floor(Date.parse(body.localTime + 'Z') / 1000) : state.now;
            return send({reviewId: `synthetic-reply-${number}`, digest: hash(`reply-${number}`), expiresAt: stamp + 3600, parent: state.inbox.messages[0],
              manifest: {actor, channelId: BOT, destinationId: body.destinationId, payload: {text: body.text}, timing: {timestamp: stamp, timeZone: 'UTC'},
                discord: {target: state.status.destinations[0].target}, engagementReply: {parentMessageId: body.parentMessageId}}});
          }
          if (step === 'approve' && req.method() === 'POST') {
            const body = req.postDataJSON(); state.approvals.push(body);
            const answer = state.answer?.(body);
            if (answer) return send(answer.body, answer.status);
          }
          world.unexpected.push(`${req.method()} ${path}`); return send({error: 'Unexpected synthetic mutation', code: 'invalid_request'}, 400);
        }
        if (path.endsWith('/time-savings/activity') && req.method() === 'POST') { world.activity++; return send({ok: true}); }
        // The card's Verify request: what records a bot's nickname. The synthetic server says verified unless a case says otherwise.
        if (path.endsWith('/verify') && req.method() === 'POST') {
          const id = path.split('/').at(-2); world.verifies.push(id);
          const answer = world.verifyAnswer?.(id);
          return send(answer?.body ?? {connectionId: id, state: 'read_verified', identityVerified: true}, answer?.status ?? 200);
        }
        if (req.method() !== 'GET') { world.unexpected.push(`${req.method()} ${path}`); return send({error: 'Unexpected synthetic mutation', code: 'invalid_request'}, 400); }
        if (path.endsWith('/channels')) return send({channels, providers: world.providers, discordIdentities: []});
        if (path === '/api/catalog') return send({authMode: 'dev', execution: 'dev-synthetic', phase2: true, templates: [], routes: [], profileMetadata: {}});
        if (path === '/api/me') return send({userId: actor, displayName: 'Synthetic tester', preferences: world.preferences, mfa: {}});
        if (path === '/api/workspaces') return send({workspaces: [{workspaceId: wid, name: 'Synthetic Discord', plan: 'studio', membership: template.snapshot.membership, memberCounts: {owner: 1}}]});
        if (path === `/api/workspaces/${wid}`) {
          snapshot.state.variants = world.variants; snapshot.state.phase2.reviews = world.reviews; snapshot.state.phase2.jobs = world.jobs;
          if (world.raffi) snapshot.state.raffi = world.raffi; else delete snapshot.state.raffi;
          return send(snapshot);
        }
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
      // Found by attribute, not by name: the button says "Why can't I change this?" instead of "Edit sender name" once editing is known to be unavailable.
      const hookButton = page.locator(`button[data-discord-sender-edit][aria-label$=" · ${hook.account}"]`);
      const botButton = page.locator(`button[data-discord-sender-edit][aria-label$=" · ${bot.account}"]`);
      const trigger = kind => kind === 'bot' ? botButton : hookButton;

      // `.depot` gets the whole page; the evidence folder gets the dialog alone (or, with `clip`, the strip of the page around a control).
      const shot = async (target, name, {tall = false, evidence = false, around = null} = {}) => {
        const original = target.viewportSize();
        if (tall) await target.setViewportSize({width, height: 2200});
        await sleep(150);
        await target.screenshot({path: join(outDir, `${combo}-${name}.png`)});
        if (evidence && evidenceDir) {
          const evidencePath = join(evidenceDir, `${combo}-${name}.png`);
          const box = target.getByRole('dialog');
          if (around) {
            // The strip runs from above the control to just below it, which keeps the phone's fixed navigation bar out of the picture.
            await around.evaluate(element => element.scrollIntoView({block: 'center'}));
            await sleep(150);
            const at = await around.boundingBox();
            await target.screenshot({path: evidencePath, clip: {x: 0, y: Math.max(0, at.y - 330), width, height: 420}});
          } else if (await box.count()) await box.screenshot({path: evidencePath});
          else await target.screenshot({path: evidencePath});
        }
        if (tall) await target.setViewportSize(original);
      };
      const focused = () => page.evaluate(() => {
        const element = document.activeElement;
        if (!element || element === document.body) return null;
        return {tag: element.tagName, type: element.getAttribute('type'), save: element.hasAttribute('data-sender-save'), again: element.hasAttribute('data-sender-check-again'),
          theme: element.getAttribute('data-theme-option'), label: element.getAttribute('aria-label'), text: (element.textContent || '').trim().slice(0, 80),
          heading: element.tagName === 'H3' ? element.closest('[data-testid]')?.getAttribute('data-testid') : null, field: element.tagName === 'INPUT' && element.type !== 'checkbox'};
      });
      const overflow = (selector = null) => page.evaluate((chosen) => {
        const box = (chosen && document.querySelector(chosen)) ?? document.querySelector('[data-testid="discord-sender-dialog"]') ?? document.querySelector('[role="dialog"]');
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
      }, selector);
      const assertFits = async (what, selector = null) => {
        const result = await overflow(selector);
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
        await shot(page, 'bot-editor', {tall: true, evidence: locale === 'zh-Hant' && width === 390 || locale === 'en' && width === 1280});
        await saveButton.click();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.equal(world.posts.length, 2);
        assert.deepEqual(Object.keys(world.posts[1].body).sort(), ['confirmed', 'fingerprint', 'name', 'sharedServerConfirmed']);
        assert.equal(world.posts[1].body.sharedServerConfirmed, true); pass('bot-body-has-shared-flag');
        pass('bot-shared-confirm-save');
        await resetPage();

        // A webhook with a custom name can go back to the webhook's own name; nothing else can be "reset", and a repeat click sends nothing.
        stage = combo + ':webhook-reset';
        const custom = {name: 'D Festival 公告', effectiveName: 'D Festival 公告', savedName: 'D Festival 公告', nameSource: 'saved_override', observedName: 'Acme Weekly'};
        world.profiles[HOOK] = profile('webhook', HOOK, custom);
        hook.discordSenderName = 'D Festival 公告';
        await openLoaded('webhook', 'D Festival 公告');
        const resetButton = dialog.locator('[data-sender-reset-button]');
        assert.equal(await resetButton.count(), 1);
        assert.equal(squash(await resetButton.innerText()), squash(copy.senderResetLabel));
        assert.equal(squash(await dialog.locator('[data-sender-reset] p').innerText()), squash(copy.senderResetHint));
        assert.equal(await resetButton.getAttribute('aria-disabled'), 'false');
        assert.ok((await resetButton.getAttribute('aria-describedby')).length > 0, 'the button points at what it does');
        world.hold = true;
        await resetButton.click();
        await until(() => Boolean(world.release), 'held reset');
        assert.equal(await resetButton.getAttribute('aria-disabled'), 'true');
        await resetButton.dispatchEvent('click'); await sleep(300);
        assert.equal(world.posts.length, 1, 'a second click while the first is pending sends nothing');
        world.hold = false; world.release(); world.release = null;
        const resetDone = dialog.locator('[data-sender-done="reset"]'); await resetDone.waitFor();
        assert.equal(squash(await resetDone.innerText()), squash(copy.senderResetDone));
        assert.deepEqual(Object.keys(world.posts[0].body).sort(), ['confirmed', 'fingerprint', 'reset']); assert.equal(world.posts[0].body.reset, true);
        assert.equal(await nameBox.inputValue(), 'Acme Weekly');
        assert.equal(await dialog.locator('[data-sender-reset]').count(), 0, 'nothing is left to reset');
        assert.equal(await dialog.locator('[data-discord-message-preview]').getAttribute('data-name-source'), 'webhook_default');
        assert.equal(squash(await dialog.locator('[data-preview-author]').innerText()), 'Acme Weekly');
        await until(async () => (await focused())?.field === true, 'focus goes to the name field once the reset button is gone');
        assert.equal(await saveButton.getAttribute('aria-disabled'), 'true', 'Save is off again until the name changes');
        pass('webhook-reset-focus-and-no-double-post');
        await resetPage();
        await openLoaded('webhook');
        assert.equal(await dialog.locator('[data-sender-reset]').count(), 0, 'a webhook without a custom name has nothing to reset');
        await resetPage();
        await openLoaded('bot');
        assert.equal(await dialog.locator('[data-sender-reset]').count(), 0, 'a bot nickname cannot be cleared from here');
        pass('webhook-reset');
        await resetPage();

        // A webhook that has no name of its own (observedName null): nothing is invented, and the form still works.
        stage = combo + ':webhook-no-own-name';
        world.profiles[HOOK] = profile('webhook', HOOK, {name: '', effectiveName: null, observedName: null, nameSource: 'none',
          preview: {currentDisplayName: null, badge: 'APP', audience: 'this_connection', queuedPostsKeepApprovedName: true, queuedBotPostsHoldIfNicknameChanges: false}});
        await open('webhook');
        await dialog.locator('[data-sender-rules]').waitFor();
        assert.equal(await nameBox.inputValue(), ''); assert.equal(await nameBox.getAttribute('readonly'), null);
        assert.equal(await dialog.locator('[data-discord-sender-state]').count(), 0);
        const noName = dialog.locator('[data-discord-message-preview]');
        assert.equal(await noName.locator('[data-preview-author]').getAttribute('data-placeholder'), 'true');
        assert.equal(squash(await noName.locator('[data-preview-author]').innerText()), copy.previewWebhookNameDefault);
        assert.equal(await saveButton.getAttribute('aria-disabled'), 'true');
        await nameBox.fill('Acme Weekly');
        assert.equal(squash(await noName.locator('[data-preview-author]').innerText()), 'Acme Weekly');
        await until(async () => (await saveButton.getAttribute('aria-disabled')) === 'false', 'Save is on once a name is typed');
        await saveButton.click();
        await dialog.getByText(copy.senderSaved, {exact: true}).waitFor();
        assert.deepEqual(Object.keys(world.posts[0].body).sort(), ['confirmed', 'fingerprint', 'name']); assert.equal(world.posts[0].body.name, 'Acme Weekly');
        pass('webhook-without-own-name-works');
        await resetPage();
      }

      // ---------------------------------------------------------------- validation: the server's rules, before saving
      if (run('validation')) {
        stage = combo + ':validation';
        await openLoaded('bot');
        const cases = [
          ['x'.repeat(33), 'too_long', 'validation-too-long'], [' lead', 'surrounding_space', 'validation-surrounding-space'], ['a  b', 'spacing', 'validation-spacing'],
          ['Team @here', 'forbidden_character', 'validation-forbidden-character'], ['www.example.com', 'url_like', 'validation-url-like'], ['R4fii', 'reserved_word', 'validation-reserved-word'],
          ['Zero​width', 'control_or_format', 'validation-control-or-format'], ['Café', 'not_normalized', 'validation-not-normalized'], ['', 'empty', 'validation-empty']
        ];
        for (const [value, issue, label] of cases) {
          await nameBox.fill(value);
          await until(async () => (await issues()).some(([found]) => found === issue), `${issue} listed`);
          const length = Math.max(Array.from(value).length, value.length);
          const listed = await issues();
          assert.equal(listed[0][0], issue, `${issue} is the first rule listed`);
          assert.equal(squash(listed[0][1]), squash(fill(copy[issue === 'reserved_word' ? 'senderIssueReservedBot' : ISSUE_KEYS[issue]], {length, limit: 32, over: Math.max(0, length - 32)})), `${issue} message`);
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
        // A zero width joiner is fine inside an emoji sequence (4 families are 32 units) and refused between Latin letters, as the server does.
        const family = '\u{1F468}\u200d\u{1F469}\u200d\u{1F467}';
        await nameBox.fill(family.repeat(4));
        await until(async () => (await issues()).length === 0, 'four family emoji fit');
        assert.equal(squash(await dialog.locator('[data-sender-count]').innerText()), fill(copy.senderCount, {count: 32, limit: 32}));
        await nameBox.fill('a\u200cb');
        await until(async () => (await issues()).some(([found]) => found === 'control_or_format'), 'a joiner between Latin letters is refused');
        pass('validation-joiner-accepted');
        // A bot nickname refuses fewer reserved words than a webhook name: Discord restricts usernames, not server nicknames.
        await nameBox.fill('Discord Helper');
        await until(async () => (await issues()).length === 0, 'a bot nickname may say Discord');
        const botRules = squash(await dialog.locator('[data-sender-rules]').innerText());
        assert.ok(botRules.includes(squash(copy.senderRuleReservedBot)) && !botRules.includes(squash(copy.senderRuleReserved)), 'the bot rules name only the product');
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
        await nameBox.fill('Discord Helper');
        await until(async () => (await issues()).some(([found]) => found === 'reserved_word'), 'a webhook name may not say Discord');
        assert.equal(squash((await issues())[0][1]), squash(copy.senderIssueReserved));
        pass('validation-reserved-by-kind');
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
        assert.ok(!notes.includes(squash(copy.previewBotQueuedNote)) && (await dialog.locator('[data-sender-bot-warning]').count()) === 0, 'the held-post sentence is about the bot');
        assert.equal(await dialog.locator('[data-sender-verify]').count(), 0, 'a webhook has no nickname to record');
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
        // The pictures below show a custom name typed in the field, not the webhook's own name.
        await nameBox.fill('Spring Gala Updates');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), 'Spring Gala Updates');
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
        assert.ok(botNotes.includes(squash(copy.previewBotQueuedNote)), 'the editor says an approved bot post is held if the nickname changes');
        assert.ok(!botNotes.includes(squash(copy.previewWebhookQueuedNote)));
        assert.ok(!botNotes.includes(squash(copy.previewWebhookNote)), 'a bot preview never claims a per-post name');
        assert.equal(squash(await dialog.locator('[data-sender-bot-warning]').innerText()), squash(copy.senderBotSaveWarning));
        assert.equal(await dialog.getByRole('checkbox').getAttribute('aria-describedby'), await dialog.locator('[data-sender-bot-warning]').getAttribute('id'), 'the checkbox points at the warning');
        pass('bot-hold-note-and-warning');
        // Verify: the editor offers it (it is what records the bot's nickname) and says what it did, in words.
        const verifyButton = dialog.locator('[data-sender-verify-button]');
        assert.equal(await dialog.locator('[data-sender-verify]').count(), 1);
        assert.equal(squash(await verifyButton.innerText()), squash(copy.senderVerifyLabel));
        assert.equal(squash(await dialog.locator('[data-sender-verify] p').first().innerText()), squash(copy.senderVerifyHint));
        const verifyResult = dialog.locator('[data-sender-verify-result]');
        await verifyButton.click();
        await until(async () => (await verifyResult.getAttribute('data-sender-verify-result')) === 'done', 'verified');
        assert.equal(squash(await verifyResult.innerText()), squash(copy.senderVerifyDone)); assert.deepEqual(world.verifies, [BOT]);
        world.verifyAnswer = () => ({body: {connectionId: BOT, state: 'verification_unavailable', identityVerified: false}});
        await verifyButton.click();
        await until(async () => (await verifyResult.getAttribute('data-sender-verify-result')) === 'repeat', 'verification must be repeated');
        assert.equal(squash(await verifyResult.innerText()), squash(copy.senderVerifyRepeat)); assert.equal(world.verifies.length, 2);
        world.verifyAnswer = () => ({status: 409, body: {error: 'Reconnect', code: 'discord_connection_required'}});
        await verifyButton.click();
        await until(async () => (await verifyResult.getAttribute('data-sender-verify-result')) === 'failed', 'a refused verification is said');
        assert.equal(await dialog.getByRole('alert').count(), 0, 'a refused verification is a status line, not an alert');
        world.verifyAnswer = null;
        pass('bot-verify-action');
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
          if (['person_missing_manage_nicknames', 'person_role_below_bot', 'bot_missing_change_nickname', 'nickname_authority_other_workspace', 'edit_pending', 'session_reverification_required', 'bot_nickname_disabled', 'provider_unavailable', 'sender_names_disabled', 'not_authorizing_member'].includes(scenario.state)) {
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
          if (scenario.state === 'bot_nickname_disabled') {
            // With the nickname switch off nothing is recorded or held, so the preview must not say it is.
            const offNotes = squash(await dialog.locator('[data-preview-notes]').innerText());
            assert.ok(offNotes.includes(squash(copy.previewBotNote)) && !offNotes.includes(squash(copy.previewBotQueuedNote)));
            assert.equal(await dialog.locator('[data-sender-bot-warning]').count(), 0, 'no warning about held posts where the nickname cannot be changed');
            pass('bot-hold-note-absent-when-switch-off');
          }
          if (scenario.timed) {
            assert.match(squash(await dialog.locator('[data-recheck]').innerText()), new RegExp('^' + escapeRegExp(copy.senderRecheckIn).replace('\\{wait\\}', '.+').replace('\\{time\\}', '.+') + '$'));
            assert.equal(await dialog.locator('[data-recheck]').getAttribute('data-retry-after-seconds'), String(scenario.wait), 'the wait the server named is shown');
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
        // The blocked profile already had the same name, so wait for the state itself to go, not for the field.
        await until(async () => (await dialog.locator('[data-discord-sender-state]').count()) === 0, 'the explanation goes once the cause is gone');
        await loaded('Acme Weekly');
        assert.equal(world.gets.length, 2); assert.equal(world.posts.length, 0);
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

      // ---------------------------------------------------------------- the cards: the control exists only when the provider view says yes
      if (run('cards')) {
        const editButtons = page.locator('button[data-discord-sender-edit]');
        const senderUi = page.locator('[data-discord-sender-edit], [data-discord-sender-edit-hint], [data-sender-status]');
        const gotoChannels = async () => { await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'}); await page.locator('[data-discord-sender]').first().waitFor(); };

        // The opening: every switch is off, the provider view says so, and the cards carry no sender-name control, no note and no request.
        stage = combo + ':cards-off';
        world.providers = [providerFor({bot: false, webhook: false})];
        await gotoChannels(); await sleep(700);
        assert.equal(await senderUi.count(), 0, 'no button, no note, nothing to press');
        assert.ok(await page.locator('[data-discord-sender]').count() >= 2, 'the cards themselves are there');
        assert.equal(world.gets.length, 0); assert.equal(world.posts.length, 0);
        pass('card-nothing-when-off');
        // A provider view with no sender-name flag, or with only the webhook connect route open, offers nothing either.
        world.providers = [];
        await gotoChannels(); await sleep(500);
        assert.equal(await senderUi.count(), 0, 'no provider, no control');
        world.providers = [{...providerFor({}), discordModes: {webhook: {enabled: true}, userInstall: {enabled: false}}}];
        await gotoChannels(); await sleep(500);
        assert.equal(await senderUi.count(), 0, 'the webhook route being open is not the name flag');
        pass('card-nothing-without-flags');

        // The flags say yes: the Edit button is on its card, and the page still reads no sender name.
        stage = combo + ':cards-on';
        world.providers = [providerFor({bot: true, webhook: true})];
        await gotoChannels(); await hookButton.waitFor(); await botButton.waitFor();
        assert.equal(await editButtons.count(), 2); assert.equal(squash(await botButton.innerText()), squash(copy.senderEdit));
        assert.equal(world.gets.length, 0, 'the connections page reads no sender name');
        pass('card-offered-when-on');
        world.providers = [providerFor({bot: true, webhook: false})];
        await gotoChannels(); await botButton.waitFor(); await sleep(400);
        assert.equal(await hookButton.count(), 0); assert.equal(await editButtons.count(), 1);
        world.providers = [providerFor({bot: false, webhook: true})];
        await gotoChannels(); await hookButton.waitFor(); await sleep(400);
        assert.equal(await botButton.count(), 0); assert.equal(await editButtons.count(), 1);
        pass('card-flags-are-per-kind');

        // The flag says yes but the server still reports a reason (a switch flipped meanwhile): a clean read-only view. No error styling, no retry, no polling.
        stage = combo + ':read-only-view';
        world.providers = [providerFor({bot: true, webhook: true})];
        await gotoChannels(); await botButton.waitFor();
        world.getAnswer = id => ({body: blockedProfile(id === BOT ? 'bot' : 'webhook', id, ['sender_names_disabled'], {...unread, feature: {senderNames: false, botNickname: false}})});
        await open('bot');
        const panel = dialog.getByTestId('discord-sender-state-sender_names_disabled'); await panel.waitFor();
        assert.equal(await panel.getAttribute('role'), null, 'a state found on open is announced politely, not as an alert');
        assert.equal(await dialog.getByRole('alert').count(), 0);
        assert.equal(await dialog.locator('[data-sender-check-again], [data-sender-refusal], [data-sender-issues], [data-sender-rules], [data-sender-count]').count(), 0, 'no retry and no editing aids in a read-only view');
        assert.equal(await panel.evaluate(element => [element, ...element.querySelectorAll('*')].some(node => /destructive|red-/.test(String(node.className)))), false, 'no error styling');
        assert.equal(await dialog.locator('[data-held-note]').count(), 0, 'the held-post sentence is about webhooks');
        assert.equal(await dialog.locator('[data-sender-mode="bot"]').count(), 1);
        assert.equal(await dialog.locator('[data-sender-verify]').count(), 0, 'nothing to verify for where the name cannot be changed');
        const reads = world.gets.length;
        await sleep(1500);
        assert.equal(world.gets.length, reads, 'no polling'); assert.equal(world.posts.length, 0);
        await closeDialog();
        // The button never changes, so focus returns to the same place.
        assert.equal(squash(await botButton.innerText()), squash(copy.senderEdit));
        await until(async () => (await focused())?.label === `${copy.senderEdit} · ${bot.account}`, 'focus returns to the Edit button');
        pass('read-only-view-is-quiet');
        await resetPage();
        await gotoChannels(); await hookButton.waitFor();
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

        // Discord refused the write or answered with another nickname: unconfirmed. Check again is a read; nothing is resent.
        stage = combo + ':failure-write-unconfirmed';
        await openLoaded('bot');
        world.postAnswer = () => ({status: 409, body: {error: 'Discord refused the nickname change.', code: 'discord_sender_write_unconfirmed'}});
        await edit('Another name', true); await saveButton.click();
        const unconfirmed = dialog.getByTestId('discord-sender-state-write_unconfirmed'); await unconfirmed.waitFor();
        assert.equal(await unconfirmed.getAttribute('role'), 'alert');
        assert.ok(squash(await unconfirmed.innerText()).includes(squash(copy.senderStateWriteUnconfirmedBody)));
        assert.equal(world.posts.length, 1);
        world.postAnswer = null;
        await dialog.getByRole('button', {name: copy.senderCheckAgain, exact: true}).click();
        await loaded('Acme Weekly');
        assert.equal(world.posts.length, 1, 'checking again never resends the change');
        pass('state-write_unconfirmed');
        await resetPage();

        // Discord answered the write with a refusal: nothing changed, nothing waits, and the way forward is a read (never a resend).
        stage = combo + ':failure-write-refused';
        await openLoaded('bot');
        world.postAnswer = () => ({status: 409, body: {error: 'Discord refused the nickname change.', code: 'discord_sender_write_refused'}});
        await edit('Another name', true); await saveButton.click();
        const refused = dialog.getByTestId('discord-sender-state-write_refused'); await refused.waitFor();
        assert.equal(await refused.getAttribute('role'), 'alert');
        assert.ok(squash(await refused.innerText()).includes(squash(copy.senderStateWriteRefusedBody)));
        assert.equal(world.posts.length, 1);
        world.postAnswer = null;
        await dialog.getByRole('button', {name: copy.senderCheckAgain, exact: true}).click();
        await loaded('Acme Weekly');
        assert.equal(world.posts.length, 1, 'checking again never resends the change');
        pass('state-write_refused');
        await resetPage();

        // Discord answered the write with a rate limit: unchanged, a wait Discord named, and the way forward is a read.
        stage = combo + ':failure-write-rate-limited';
        await openLoaded('bot');
        world.postAnswer = () => ({status: 429, body: {error: 'Discord rate limited the nickname change.', code: 'discord_sender_write_rate_limited', retryAfterSeconds: 31}});
        await edit('Another name', true); await saveButton.click();
        const limited = dialog.getByTestId('discord-sender-state-write_rate_limited'); await limited.waitFor();
        assert.equal(await limited.getAttribute('role'), 'alert');
        assert.ok(squash(await limited.innerText()).includes(squash(copy.senderStateWriteRateLimitedBody)));
        assert.equal(await dialog.locator('[data-recheck]').getAttribute('data-retry-after-seconds'), '31');
        assert.equal(await dialog.locator('[data-sender-check-again]').getAttribute('aria-disabled'), 'true', 'not before the time Discord named');
        assert.equal(world.posts.length, 1);
        pass('state-write_rate_limited');
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
        await until(async () => (await dialog.locator('[data-discord-sender-state]').count()) === 0, 'the explanation goes after Check again by keyboard');
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
        // When the channel view carries the nickname a review would record, the preview shows it and says what an approval does with it.
        bot.discordBotNickname = 'Concert helper';
        await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
        await page.getByRole('button', {name: 'Schedule a draft', exact: true}).click();
        await dialog.waitFor();
        await dialog.getByRole('combobox', {name: 'Draft', exact: true}).selectOption(input.variant.id);
        await dialog.getByRole('combobox', {name: 'Account', exact: true}).selectOption(bot.id);
        await until(async () => (await preview.getAttribute('data-kind')) === 'bot', 'bot preview with a nickname');
        assert.equal(await preview.getAttribute('data-name-source'), 'observed');
        assert.equal(squash(await preview.locator('[data-preview-author]').innerText()), 'Concert helper');
        const knownNotes = squash(await preview.locator('[data-preview-notes]').innerText());
        assert.ok(knownNotes.includes(squash(copy.previewBotQueuedNote)) && knownNotes.includes(squash(copy.previewBotNameAsOf)));
        await assertFits('schedule dialog bot with a nickname');
        pass('schedule-preview-bot-nickname');
        await page.keyboard.press('Escape'); await dialog.waitFor({state: 'detached'});
        delete bot.discordBotNickname;
        world.variants = []; delete hook.discordSenderName;
      }

      // ---------------------------------------------------------------- review cards
      if (run('review')) {
        stage = combo + ':review';
        const future = Math.floor(Date.now() / 1000) + 30 * 86400;
        const reviewFor = (kind, name, nickname) => {
          const review = structuredClone(input.review);
          review.id = 'synthetic-review-' + kind;
          review.manifest.platform = 'Discord'; review.manifest.channelId = kind === 'webhook' ? hook.id : bot.id; review.manifest.senderKind = kind;
          review.manifest.payload = {...review.manifest.payload, text: 'First line\nSecond line @ the stage door'};
          review.manifest.expiresAt = future + 7200;
          review.manifest.timing = {...review.manifest.timing, timestamp: future, utc: new Date(future * 1000).toISOString(), local: new Date(future * 1000).toISOString().slice(0, 16)};
          if (name) review.manifest.discordSenderName = name; else delete review.manifest.discordSenderName;
          if (nickname !== undefined) review.manifest.discordBotNickname = nickname; else delete review.manifest.discordBotNickname;
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
        // An approval that recorded the bot's nickname shows it; one that recorded "no nickname" says the bot's own username shows; both say the hold.
        for (const [nickname, source, author] of [['Concert helper', 'approved', 'Concert helper'], [null, 'bot_username', copy.previewBotNameUnknown]]) {
          world.reviews = [reviewFor('bot', null, nickname)];
          await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
          const recorded = page.locator('[data-discord-message-preview]').first();
          await recorded.waitFor();
          assert.equal(await recorded.getAttribute('data-name-source'), source);
          assert.equal(squash(await recorded.locator('[data-preview-author]').innerText()), author);
          const recordedNotes = squash(await recorded.locator('[data-preview-notes]').innerText());
          assert.ok(recordedNotes.includes(squash(copy.previewBotApprovedNote)) && recordedNotes.includes(squash(copy.previewBotNote)));
          assert.ok(!recordedNotes.includes(squash(copy.previewBotQueuedNote)), 'an approved post is told about the hold in the past tense, not as a future approval');
          if (nickname === null) assert.ok(recordedNotes.includes(squash(copy.previewBotUsernameNote)));
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `review recorded nickname ${source} overflow`);
        }
        pass('review-preview-bot-recorded-nickname');
        world.reviews = [];

        // A bot post held because the nickname changed: the line, and the one action that moves it forward (Verify, then review again).
        stage = combo + ':queue-hold';
        const HOLD = 'The Rafii bot’s server nickname is no longer the one this post was approved under; nothing was posted. Review the post again.';
        const heldJob = (id, kind, message) => {
          const job = structuredClone(input.job);
          job.id = id; job.state = 'held'; job.manifest.channelId = kind === 'bot' ? BOT : HOOK; job.manifest.senderKind = kind;
          job.events.push({at: 1800000100.0, execution: 'synthetic', message, state: 'held'});
          return job;
        };
        world.jobs = [heldJob('synthetic-held-bot', 'bot', HOLD)];
        await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
        const hold = page.locator('[data-discord-nickname-hold]').first();
        await hold.waitFor();
        assert.equal(squash(await hold.locator('p').first().innerText()), squash(copy.senderHoldNote));
        const holdVerify = hold.locator('[data-discord-verify]');
        assert.equal(squash(await holdVerify.innerText()), squash(copy.senderVerifyLabel));
        assert.ok((await holdVerify.getAttribute('aria-describedby')).length > 0);
        await shot(page, 'queue-held-nickname', {evidence: locale === 'en' && width === 390 || locale === 'zh-Hant' && width === 390, around: holdVerify});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'the held post fits the page');
        await holdVerify.click();
        const holdResult = hold.locator('[data-discord-verify-result]');
        await until(async () => (await holdResult.getAttribute('data-discord-verify-result')) === 'done', 'the held post verified');
        assert.equal(squash(await holdResult.innerText()), squash(copy.senderVerifyDone)); assert.deepEqual(world.verifies, [BOT]);
        // Another reason for holding, and a webhook post (it has no nickname), get no such action.
        world.jobs = [heldJob('synthetic-held-other', 'bot', 'Discord custom sender names are switched off; nothing was posted.'), heldJob('synthetic-held-hook', 'webhook', HOLD)];
        await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
        await page.getByText('Discord custom sender names are switched off', {exact: false}).first().waitFor();
        assert.equal(await page.locator('[data-discord-nickname-hold]').count(), 0);
        pass('queue-hold-verify-action');
        world.jobs = [];
      }

      // ---------------------------------------------------------------- the Discord hourly ceiling (docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md)
      // The synthetic server answers an approval with the contract's 409 (or with another 409); it never approves anything.
      if (run('ceiling')) {
        stage = combo + ':ceiling';
        const future = Math.floor(Date.now() / 1000) + 30 * 86400;
        const at = index => future + index * 3600;
        const ceilingReview = index => {
          const review = structuredClone(input.review);
          review.id = `synthetic-ceiling-review-${index}`; review.digest = hash(`ceiling-digest-${index}`);
          review.manifest.idempotencyKey = hash(`ceiling-post-${index}`);
          review.manifest.variantId = index === 0 ? input.variant.id : `${input.variant.id}-${index}`;
          review.manifest.platform = 'Discord'; review.manifest.channelId = HOOK; review.manifest.senderKind = 'webhook';
          review.manifest.payload = {...review.manifest.payload, text: `Doors open at 7 (${index})`};
          review.manifest.expiresAt = at(index) + 7200;
          review.manifest.timing = {...review.manifest.timing, timestamp: at(index), utc: new Date(at(index) * 1000).toISOString(), local: new Date(at(index) * 1000).toISOString().slice(0, 16)};
          delete review.manifest.discordSenderName; delete review.manifest.discordBotNickname;
          return review;
        };
        /** The contract's refusal, with the limit it names (the owner may change it). */
        const refuse = (limit = ceilingContract.body.limit) => () => ({status: ceilingContract.status, body: {...ceilingContract.body, limit,
          error: ceilingContract.body.error.replace(String(ceilingContract.body.limit), String(limit))}});
        const paused = () => ({status: 409, body: {error: 'Approvals for this account are paused.', code: 'approvals_paused_synthetic'}});
        const dayOf = seconds => page.evaluate(([epoch]) => {
          const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(epoch * 1000).map(part => [part.type, part.value]));
          return `${parts.year}-${parts.month}-${parts.day}`;
        }, [seconds]);
        const tapTarget = async (locator, what) => {
          const box = await locator.boundingBox();
          assert.ok(box && box.height >= 44 && box.width >= 44, `${what} is a 44 px target (${box && Math.round(box.width)}x${box && Math.round(box.height)})`);
        };
        /** Nothing in the refusal offers a second send, a wait or a countdown. */
        const assertNoRetry = async (scope, what) => {
          assert.doesNotMatch(await scope.innerText(), /retry|try again|reload|countdown|再試|重試|再试|重试|重新載入|重新加载/i, `${what}: words`);
          assert.equal(await scope.locator('time, progress, [role="timer"], [aria-live], [data-retry], [data-countdown]').count(), 0, `${what}: elements`);
        };
        const snap = async (locator, name) => {
          // The dev server's own overlays (route indicator, query devtools button) are not part of the app; keep them out of the pictures.
          if (!(await page.evaluate(() => Boolean(document.getElementById('rafii-evidence-style'))))) {
            await page.addStyleTag({content: 'nextjs-portal,[data-nextjs-toast],[data-next-badge-root],.tsqd-parent-container,.tsqd-open-btn-container{display:none!important}'}).then(handle => handle.evaluate(element => { element.id = 'rafii-evidence-style'; }));
          }
          await sleep(200);
          await locator.screenshot({path: join(outDir, `${combo}-${name}.png`)});
          if (evidenceDir) await locator.screenshot({path: join(evidenceDir, `${combo}-${name}.png`)});
        };
        const noToast = async what => assert.equal(await page.locator('[data-sonner-toast]').count(), 0, `${what}: no toast`);
        // Uncaught errors and React's own warnings (hydration, keys, state updates during render) on these surfaces are failures.
        const trouble = [];
        const onPageError = error => trouble.push(`pageerror: ${String(error).slice(0, 200)}`);
        const onConsole = message => { if (message.type() === 'error' && /hydrat|Warning:|unique "key"|Cannot update a component|Maximum update depth/i.test(message.text())) trouble.push(`console: ${message.text().slice(0, 200)}`); };
        page.on('pageerror', onPageError); page.on('console', onConsole);
        // WCAG 2 A and AA on each new surface, once per run (English at 1280 px): the injected script is lost on every navigation, so it is added where needed.
        const axeCeiling = async (selector, what) => {
          if (locale !== 'en' || width !== 1280) return;
          if (!(await page.evaluate(() => typeof window.axe !== 'undefined'))) await page.addScriptTag({path: require.resolve('axe-core/axe.min.js')});
          const violations = (await page.evaluate(([sel]) => axe.run(document.querySelector(sel), {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}}), [selector]))
            .violations.map(v => `${v.id}: ${v.nodes.slice(0, 2).map(n => n.target.join(' ')).join(' | ')}`);
          assert.deepEqual(violations, [], `axe: ${what}`);
          axed.add(what);
        };
        const axed = new Set();
        const toastWith = async text => { const toast = page.locator('[data-sonner-toast]').filter({hasText: text}); await toast.first().waitFor(); return toast.first(); };

        // ------------------------------------------------------------ one approval, from the Queue card
        stage = combo + ':ceiling-single';
        reset(); world.reviews = [ceilingReview(0)]; world.actionAnswer = refuse();
        await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
        const approveButton = page.locator('button[data-review-approve]');
        await approveButton.waitFor(); assert.equal(await approveButton.count(), 1);
        await approveButton.click();
        const refusalDialog = page.locator('[data-hourly-ceiling-dialog]'); await refusalDialog.waitFor();
        assert.equal(await page.getByRole('dialog', {name: copy.hourlyCeilingTitle, exact: true}).count(), 1, 'the dialog is named by its title');
        assert.equal(squash(await refusalDialog.locator('[data-hourly-ceiling-body]').innerText()), squash(fill(copy.hourlyCeilingBody, {limit: 300})));
        assert.equal(squash(await refusalDialog.locator('[data-hourly-ceiling-state]').innerText()), squash(copy.hourlyCeilingNothingApproved));
        assert.equal(squash(await refusalDialog.locator('[data-hourly-ceiling-moved]').innerText()), squash(copy.hourlyCeilingMoved), 'a move ends here: the earlier time is already cancelled');
        const chooseTime = refusalDialog.locator('[data-hourly-ceiling-action="choose-time"]'), seePosts = refusalDialog.locator('[data-hourly-ceiling-action="see-posts"]');
        assert.equal(squash(await chooseTime.innerText()), squash(copy.hourlyCeilingChooseTime));
        assert.equal(await chooseTime.getAttribute('href'), `/app/queue?view=drafts&draft=${encodeURIComponent(input.variant.id)}`);
        assert.equal(squash(await seePosts.innerText()), squash(copy.hourlyCeilingSeePosts));
        assert.equal(await seePosts.getAttribute('href'), `/app/calendar?view=day&date=${await dayOf(at(0))}`, 'the Calendar day of the post, in the browser zone');
        const closeRefusal = refusalDialog.locator('[data-hourly-ceiling-close]');
        assert.equal(squash(await closeRefusal.innerText()), squash(copy.hourlyCeilingClose));
        const described = await page.evaluate(() => {
          const box = document.querySelector('[data-hourly-ceiling-dialog]'), id = box?.getAttribute('aria-describedby');
          return id ? document.getElementById(id)?.innerText ?? null : null;
        });
        assert.ok(described, 'the dialog has a description');
        for (const part of [fill(copy.hourlyCeilingBody, {limit: 300}), copy.hourlyCeilingNothingApproved, copy.hourlyCeilingMoved]) assert.ok(squash(described).includes(squash(part)), `a screen reader is told: ${part}`);
        for (const [target, what] of [[chooseTime, 'choose another time'], [seePosts, 'see the posts'], [closeRefusal, 'close']]) await tapTarget(target, what);
        await assertNoRetry(refusalDialog, 'single approve');
        await noToast('single approve');
        await assertFits('ceiling single dialog');
        assert.equal(world.actions.length, 1);
        assert.deepEqual(Object.keys(world.actions[0]).sort(), ['action', 'expectedRevision', 'payload']);
        assert.equal(world.actions[0].action, 'p2_approve');
        assert.deepEqual(world.actions[0].payload, {reviewId: 'synthetic-ceiling-review-0', digest: hash('ceiling-digest-0'), confirmed: true});
        await snap(refusalDialog, 'ceiling-single-dialog');
        await axeCeiling('[data-hourly-ceiling-dialog]', 'single dialog');
        await sleep(1500); assert.equal(world.actions.length, 1, 'no automatic retry');
        await page.keyboard.press('Escape'); await refusalDialog.waitFor({state: 'detached'});
        await until(() => approveButton.evaluate(element => element === document.activeElement), 'focus back on the approve button');
        // The review is untouched and still waiting: the same card, the same button, nothing approved.
        assert.equal(await approveButton.count(), 1);
        await sleep(300); assert.equal(world.actions.length, 1, 'closing the explanation sends nothing');
        pass('ceiling-single-dialog');

        // The limit in the text is the response's own when it carries one (the owner may change the ceiling).
        world.actionAnswer = refuse(250);
        await approveButton.click(); await refusalDialog.waitFor();
        assert.equal(squash(await refusalDialog.locator('[data-hourly-ceiling-body]').innerText()), squash(fill(copy.hourlyCeilingBody, {limit: 250})));
        assert.equal(world.actions.length, 2, 'a second press is a second request, made by the person');
        await closeRefusal.click(); await refusalDialog.waitFor({state: 'detached'});
        pass('ceiling-single-uses-server-limit');

        // Any other refusal keeps the old path: a toast with the server's words and a way to reload.
        world.actionAnswer = paused;
        await approveButton.click();
        const pausedToast = await toastWith('Couldn’t approve this post');
        assert.match(await pausedToast.innerText(), /Approvals for this account are paused\./);
        assert.match(await pausedToast.innerText(), /Reload/);
        assert.equal(await refusalDialog.count(), 0, 'no ceiling dialog for another code');
        assert.equal(world.actions.length, 3);
        pass('ceiling-single-unknown-code');

        // ------------------------------------------------------------ several approvals at once, from the Queue
        stage = combo + ':ceiling-bulk';
        reset(); world.reviews = [0, 1, 2].map(ceilingReview); world.actionAnswer = refuse();
        await page.goto(base + '/app/queue', {waitUntil: 'domcontentloaded'});
        const approveAll = page.getByRole('button', {name: 'Approve all 3', exact: true});
        await approveAll.waitFor(); await approveAll.click();
        const bulk = page.getByRole('dialog');
        await bulk.getByRole('heading', {name: 'Approve 3 posts?', exact: true}).waitFor();
        const rows = bulk.locator('li[data-review-id]'), primary = bulk.locator('[data-approve-many-primary]'), removes = bulk.locator('[data-approve-many-remove]');
        const bulkNotice = bulk.locator('[data-hourly-ceiling][data-place="bulk"]');
        assert.equal(await rows.count(), 3); assert.equal(await removes.count(), 0, 'nothing to remove before a refusal');
        await primary.click();
        await bulkNotice.waitFor();
        assert.equal(squash(await bulkNotice.locator('h3').innerText()), squash(copy.hourlyCeilingTitle));
        assert.equal(squash(await bulkNotice.locator('[data-hourly-ceiling-body]').innerText()), squash(fill(copy.hourlyCeilingBody, {limit: 300})));
        assert.equal(squash(await bulkNotice.locator('[data-hourly-ceiling-state]').innerText()), squash(copy.hourlyCeilingBulkNone), 'it says that no post was approved and the selection is unchanged');
        const bulkSee = bulkNotice.locator('[data-hourly-ceiling-action="see-posts"]');
        assert.equal(squash(await bulkSee.innerText()), squash(copy.hourlyCeilingSeePostsMany));
        assert.equal(await bulkSee.getAttribute('href'), `/app/calendar?view=day&date=${await dayOf(at(0))}`);
        assert.equal(await bulkNotice.locator('[data-hourly-ceiling-action="choose-time"]').count(), 0, 'the response does not say which post crossed, so there is no one time to change');
        assert.equal(await page.evaluate(() => { const focus = document.activeElement; return focus?.tagName === 'H3' && Boolean(focus.closest('[data-hourly-ceiling]')); }), true, 'the keyboard moves to the explanation');
        assert.equal(await rows.count(), 3, 'the selection is kept');
        assert.equal(await primary.isDisabled(), true, 'the same selection is not offered again');
        assert.equal(await removes.count(), 3, 'every post can be taken out');
        for (let index = 0; index < 3; index++) {
          const remove = removes.nth(index);
          assert.equal(squash(await remove.innerText()), squash(copy.hourlyCeilingRemove));
          assert.ok((await remove.getAttribute('aria-label')).startsWith(copy.hourlyCeilingRemoveFor.split('{name}')[0]), 'the name starts with the visible word');
          await tapTarget(remove, `remove ${index}`);
        }
        await assertNoRetry(bulkNotice, 'bulk approve'); await noToast('bulk approve');
        await assertFits('ceiling bulk dialog');
        assert.equal(world.actions.length, 1);
        assert.equal(world.actions[0].action, 'p2_approve_many');
        assert.deepEqual(world.actions[0].payload.reviews.map(row => row.reviewId), [0, 1, 2].map(index => `synthetic-ceiling-review-${index}`));
        assert.equal(world.actions[0].payload.confirmed, true);
        await snap(bulk, 'ceiling-bulk-notice');
        await axeCeiling('[role="dialog"]', 'bulk dialog');
        await sleep(1500); assert.equal(world.actions.length, 1, 'no automatic retry');
        pass('ceiling-bulk-keeps-selection');

        // Take a post out: the refusal belonged to the old selection, so the rest can be approved again (and is refused again here).
        await removes.nth(1).click();
        await until(async () => (await rows.count()) === 2, 'the row is gone');
        assert.equal(await bulkNotice.count(), 0, 'a changed selection is a new question');
        assert.equal(await primary.isDisabled(), false);
        assert.equal(squash(await primary.innerText()), 'Approve 2');
        await bulk.getByRole('heading', {name: 'Approve 2 posts?', exact: true}).waitFor();
        assert.equal(await primary.evaluate(element => element === document.activeElement), true, 'the keyboard lands on the button that approves what is left');
        assert.equal(await removes.count(), 2, 'the remove buttons stay');
        assert.equal(await bulk.locator('li[data-review-id="synthetic-ceiling-review-1"]').count(), 0);
        await primary.click(); await bulkNotice.waitFor();
        assert.equal(world.actions.length, 2);
        assert.deepEqual(world.actions[1].payload.reviews.map(row => row.reviewId), ['synthetic-ceiling-review-0', 'synthetic-ceiling-review-2'], 'the removed post is not in the next request');
        await removes.first().click();
        await until(async () => (await rows.count()) === 1, 'the second row is gone');
        assert.equal(await removes.count(), 0, 'the last post cannot be removed');
        assert.equal(await primary.isDisabled(), false);
        await bulk.getByRole('heading', {name: 'Approve 1 post?', exact: true}).waitFor();
        // Closing starts over: a fresh dialog has the whole batch, no explanation and no remove buttons.
        await bulk.getByRole('button', {name: 'Cancel', exact: true}).click(); await bulk.waitFor({state: 'detached'});
        await approveAll.click();
        await bulk.getByRole('heading', {name: 'Approve 3 posts?', exact: true}).waitFor();
        assert.equal(await rows.count(), 3); assert.equal(await bulkNotice.count(), 0); assert.equal(await removes.count(), 0); assert.equal(await primary.isDisabled(), false);
        assert.equal(world.actions.length, 2);
        pass('ceiling-bulk-remove-then-approve');

        // Another refusal keeps the old path: a toast, the selection, and the same button to press again.
        world.actionAnswer = paused;
        await primary.click();
        const bulkToast = await toastWith('Couldn’t approve these posts');
        assert.match(await bulkToast.innerText(), /Approvals for this account are paused\./);
        assert.equal(await bulkNotice.count(), 0, 'no ceiling notice for another code');
        assert.equal(await removes.count(), 0);
        assert.equal(await rows.count(), 3);
        assert.equal(await primary.isDisabled(), false);
        assert.equal(world.actions.length, 3);
        pass('ceiling-bulk-unknown-code');
        await bulk.getByRole('button', {name: 'Cancel', exact: true}).click().catch(() => {});

        // ------------------------------------------------------------ a reply to a message (engagement)
        stage = combo + ':ceiling-reply';
        reset(); world.reviews = []; world.variants = [];
        const replyTarget = bot.discordDestinations[0];
        world.engagement = {previews: 0, approvals: [], answer: refuse(), now: future,
          status: {implemented: true, enabled: true, canReply: true, jobs: [],
            destinations: [{target: replyTarget, targetDigest: hash('reply-target'), contentAccess: 'mentions_only', broaderContentEligible: false, permissions: {analytics: true, inbox: true, reply: true}, expiresAt: future + 86400}],
            limits: {inbox: 'Synthetic inbox limits.', analytics: 'Synthetic analytics limits.', retention: 'Synthetic retention.', broaderAccess: 'Synthetic broader access.', unavailable: []}},
          inbox: {kind: 'inbox', contentAccess: 'mentions_only', target: replyTarget, observedAt: future - 60, coverage: 'latest_page_only', pageLimit: 50, mayHaveOlderMessages: false,
            messages: [{id: '9001', parentMessageId: null, content: 'What time do the doors open?', contentAvailability: 'visible_bot_mention', author: 'Synthetic fan', replyable: true, url: 'https://discord.com/channels/555555/7777777/9001'}]}};
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await page.getByRole('button', {name: 'Discord analytics & conversations', exact: true}).first().click();
        await page.getByRole('combobox', {name: 'Engagement destination'}).waitFor();
        const openReplyReview = async (text, time) => {
          if (await page.getByRole('textbox', {name: 'Exact Discord reply', exact: true}).count() === 0) {
            await page.getByRole('button', {name: 'Read partial inbox', exact: true}).click();
            await page.getByRole('region', {name: 'Partial Discord inbox'}).getByRole('button', {name: 'Write a reply', exact: true}).click();
          }
          await page.getByRole('textbox', {name: 'Exact Discord reply', exact: true}).fill(text);
          if (time) await page.locator('input[aria-label="Discord reply time"]').fill(time);
          await page.getByRole('button', {name: 'Review exact reply', exact: true}).click();
          const review = page.getByRole('dialog', {name: 'Approve this exact Discord reply', exact: true}); await review.waitFor();
          return review;
        };
        const reviewDialog = await openReplyReview('The doors open at 7.');
        const replyApprove = reviewDialog.getByRole('button', {name: 'Approve this exact reply', exact: true});
        await replyApprove.click();
        const replyNotice = reviewDialog.locator('[data-hourly-ceiling][data-place="reply"]'); await replyNotice.waitFor();
        assert.equal(squash(await replyNotice.locator('h3').innerText()), squash(copy.hourlyCeilingTitle));
        assert.equal(squash(await replyNotice.locator('[data-hourly-ceiling-body]').innerText()), squash(fill(copy.hourlyCeilingBody, {limit: 300})));
        assert.equal(squash(await replyNotice.locator('[data-hourly-ceiling-state]').innerText()), squash(copy.hourlyCeilingReply));
        assert.equal(await replyNotice.locator('[data-hourly-ceiling-moved]').count(), 0);
        const replySee = replyNotice.locator('[data-hourly-ceiling-action="see-posts"]');
        assert.equal(await replySee.getAttribute('href'), `/app/calendar?view=day&date=${await dayOf(future)}`);
        const replyChoose = replyNotice.locator('[data-hourly-ceiling-action="choose-time"]');
        assert.equal(squash(await replyChoose.innerText()), squash(copy.hourlyCeilingChooseTime));
        for (const [target, what] of [[replyChoose, 'choose another time'], [replySee, 'see the posts']]) await tapTarget(target, `reply ${what}`);
        await assertNoRetry(replyNotice, 'reply'); await noToast('reply');
        assert.equal(await reviewDialog.isVisible(), true, 'the review stays open');
        assert.equal(await replyApprove.isDisabled(), true, 'the same review is not offered again');
        assert.equal(await page.evaluate(() => { const focus = document.activeElement; return focus?.tagName === 'H3' && Boolean(focus.closest('[data-hourly-ceiling]')); }), true);
        assert.equal(world.engagement.approvals.length, 1);
        assert.deepEqual(world.engagement.approvals[0], {reviewId: 'synthetic-reply-1', digest: hash('reply-1'), confirmed: true});
        await assertFits('ceiling reply dialog', '[role="dialog"][data-slot="dialog-content"]');
        await snap(reviewDialog, 'ceiling-reply-notice');
        await axeCeiling('[role="dialog"][data-slot="dialog-content"]', 'reply dialog');
        await sleep(1500); assert.equal(world.engagement.approvals.length, 1, 'no automatic retry');
        // Choose another time: back to the reply form, with the keyboard on its time field, and a new review can be approved.
        await replyChoose.click(); await reviewDialog.waitFor({state: 'detached'});
        await until(() => page.evaluate(() => document.activeElement?.getAttribute('aria-label') === 'Discord reply time'), 'the time field has the keyboard');
        const nextReview = await openReplyReview('The doors open at 7.', '2031-03-04T09:05');
        assert.equal(await nextReview.locator('[data-hourly-ceiling]').count(), 0, 'a new review is a new question');
        assert.equal(await nextReview.getByRole('button', {name: 'Approve this exact reply', exact: true}).isDisabled(), false);
        pass('ceiling-reply-dialog');
        // Any other refusal keeps the old path: the message at the top of the panel, and the review is closed.
        world.engagement.answer = paused;
        await nextReview.getByRole('button', {name: 'Approve this exact reply', exact: true}).click();
        await nextReview.waitFor({state: 'detached'});
        await page.getByText('Approvals for this account are paused.', {exact: true}).waitFor();
        assert.equal(await page.locator('[data-hourly-ceiling]').count(), 0);
        assert.equal(world.engagement.approvals.length, 2);
        pass('ceiling-reply-unknown-code');
        world.engagement = null;

        // ------------------------------------------------------------ an automation post: the decision, and the card after the queue attempts
        stage = combo + ':ceiling-decision';
        reset();
        const automationVariant = {...input.variant, id: 'synthetic-automation-draft', text: 'Doors open at 7 tonight.', revision: 1};
        const automationDestination = bot.discordDestinations[0];
        const automationItem = {destinationId: automationDestination.id, key: `Discord|${BOT}|en`, platform: 'Discord', channelId: BOT, account: bot.account, language: 'en',
          variantId: automationVariant.id, variantRevision: 1, state: 'ready_for_review', publishAt: at(0)};
        const queueFailed = (number, reason) => ({key: `Discord|${BOT}|en`, platform: 'Discord', channelId: BOT, account: bot.account, language: 'en', variantId: `${automationVariant.id}-${number}`,
          state: 'failed', reason, publishAt: at(number), attempts: 3, lastError: null});
        const runOf = (id, items, daysBack) => ({id, taskId: 'task-ceiling', state: 'completed', scheduledFor: at(0) - daysBack * 86400, anchorAt: at(0) - daysBack * 86400, lifecycle: 'drafted', policy: 'review', items});
        world.variants = [automationVariant];
        world.raffi = {campaignPlanning: {campaigns: [], recurringTasks: [{
          id: 'task-ceiling', campaignId: 'campaign-ceiling', version: 1, status: 'active', name: 'Weekly doors-open note', authorityVersion: 2, route: 'synthetic-writer', createdAt: future - 1e6, updatedAt: future - 1e5,
          schedule: {kind: 'weekly', weekdays: ['Thursday'], localTime: '09:00', timeZone: 'UTC'}, destinations: [{platform: 'Discord', language: 'en', channelId: BOT}], accountLabels: {[BOT]: bot.account}}],
          occurrences: [runOf('run-ceiling-1', [automationItem], 0), runOf('run-ceiling-2', [queueFailed(1, ceilingContract.queueFailureReason)], 1),
            runOf('run-ceiling-3', [queueFailed(2, "It couldn't be queued in time, so it was not published. The draft is kept.")], 2)]}};
        world.actionAnswer = refuse();
        await page.goto(base + '/app/automations', {waitUntil: 'domcontentloaded'});
        const pendingRun = page.locator('[data-automation-run="run-ceiling-1"]');
        await pendingRun.waitFor();
        await pendingRun.getByRole('button', {name: /^Approve the .* post$/}).click();
        const decision = page.getByRole('dialog');
        await decision.getByRole('checkbox').check();
        const decide = decision.getByRole('button', {name: 'Approve post', exact: true});
        await until(async () => !(await decide.isDisabled()), 'the approval is ready');
        await decide.click();
        const decisionNotice = decision.locator('[data-hourly-ceiling][data-place="decision"]'); await decisionNotice.waitFor();
        assert.equal(squash(await decisionNotice.locator('h3').innerText()), squash(copy.hourlyCeilingTitle));
        assert.equal(squash(await decisionNotice.locator('[data-hourly-ceiling-body]').innerText()), squash(fill(copy.hourlyCeilingBody, {limit: 300})));
        assert.equal(squash(await decisionNotice.locator('[data-hourly-ceiling-state]').innerText()), squash(copy.hourlyCeilingDecision), 'the post stays ready for review');
        const decisionSee = decisionNotice.locator('[data-hourly-ceiling-action="see-posts"]');
        assert.equal(await decisionSee.getAttribute('href'), `/app/calendar?view=day&date=${await dayOf(at(0))}`);
        assert.equal(await decisionNotice.locator('[data-hourly-ceiling-action="choose-time"]').count(), 0, 'an automation post has no time of its own to choose');
        await tapTarget(decisionSee, 'decision see the posts');
        await assertNoRetry(decisionNotice, 'decision'); await noToast('decision');
        assert.equal(await decision.isVisible(), true, 'the dialog stays');
        assert.equal(await decide.isDisabled(), true, 'the same request is not offered again');
        assert.equal(await page.evaluate(() => { const focus = document.activeElement; return focus?.tagName === 'H3' && Boolean(focus.closest('[data-hourly-ceiling]')); }), true);
        assert.equal(world.actions.length, 1);
        assert.equal(world.actions[0].action, 'raffi_run_decide'); assert.equal(world.actions[0].payload.decision, 'approve');
        await assertFits('ceiling decision dialog');
        await snap(decision, 'ceiling-decision-notice');
        await axeCeiling('[role="dialog"]', 'decision dialog');
        await sleep(1500); assert.equal(world.actions.length, 1, 'no automatic retry');
        pass('ceiling-decision-dialog');
        // Another refusal keeps the old path: a toast with the server's words, and the dialog can send again.
        await decision.getByRole('button', {name: 'Not now', exact: true}).click(); await decision.waitFor({state: 'detached'});
        world.actionAnswer = paused;
        await pendingRun.getByRole('button', {name: /^Approve the .* post$/}).click();
        await decision.getByRole('checkbox').check();
        await until(async () => !(await decide.isDisabled()), 'the approval is ready again');
        await decide.click();
        const decisionToast = await toastWith('Approvals for this account are paused.');
        assert.ok(decisionToast);
        assert.equal(await decision.locator('[data-hourly-ceiling]').count(), 0);
        await until(async () => !(await decide.isDisabled()), 'the dialog can send again');
        assert.equal(world.actions.length, 2);
        pass('ceiling-decision-unknown-code');
        await decision.getByRole('button', {name: 'Not now', exact: true}).click(); await decision.waitFor({state: 'detached'});

        // The card of a post the scheduler could not queue: the server's English sentence, said in the person's language.
        stage = combo + ':ceiling-run-card';
        const failedRun = page.locator('[data-automation-run="run-ceiling-2"]'), otherRun = page.locator('[data-automation-run="run-ceiling-3"]');
        await failedRun.waitFor();
        const failedLine = failedRun.locator('[data-hourly-ceiling-queue-failed]');
        assert.equal(squash(await failedLine.innerText()), squash(fill(copy.hourlyCeilingQueueFailed, {limit: 300})));
        assert.ok(!(await failedRun.innerText()).includes('This hour is full'), 'the English sentence is replaced, not repeated');
        const cardChoose = failedRun.locator('[data-hourly-ceiling-action="choose-time"]'), cardSee = failedRun.locator('[data-hourly-ceiling-action="see-posts"]');
        assert.equal(await cardChoose.getAttribute('href'), `/app/queue?view=drafts&draft=${encodeURIComponent(automationVariant.id + '-1')}`, 'the approved draft was kept');
        assert.equal(await cardSee.getAttribute('href'), `/app/calendar?view=day&date=${await dayOf(at(1))}`);
        for (const [target, what] of [[cardChoose, 'choose another time'], [cardSee, 'see the posts']]) await tapTarget(target, `card ${what}`);
        assert.doesNotMatch(await failedRun.innerText(), /retry|try again|countdown|再試|重試|再试|重试/i);
        assert.equal(await failedRun.getByRole('button', {name: /^Approve the/}).count(), 0, 'a failed post has no approve button; the draft is the way back');
        assert.equal(squash(await otherRun.innerText()).includes("It couldn't be queued in time, so it was not published. The draft is kept."), true, 'another reason is shown as the server wrote it');
        assert.equal(await otherRun.locator('[data-hourly-ceiling-action]').count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'the card fits the page');
        await snap(failedRun, 'ceiling-run-card');
        await axeCeiling('[data-automation-run="run-ceiling-2"]', 'run card');
        pass('ceiling-run-card-text');
        if (locale === 'en' && width === 1280 && run('ceiling')) {
          assert.deepEqual([...axed].sort(), ['bulk dialog', 'decision dialog', 'reply dialog', 'run card', 'single dialog'], 'axe ran on every new surface');
          once.add('axe-ceiling');
        }

        page.off('pageerror', onPageError); page.off('console', onConsole);
        assert.deepEqual(trouble, [], 'no uncaught errors or React warnings on the new surfaces');
        pass('ceiling-no-page-errors');
        world.raffi = null; world.variants = []; world.reviews = []; world.actionAnswer = null; world.engagement = null;
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
        // The app follows the person's colour scheme; the same page is switched (one browser context only: a second one crashed the single-process Chromium).
        await page.emulateMedia({colorScheme: 'dark'});
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
        await hookButton.waitFor(); await hookButton.click(); await dialog.waitFor();
        await until(() => nameBox.inputValue().then(v => v === 'Acme Weekly').catch(() => false), 'dark editor loaded');
        await until(async () => (await dialog.locator('[data-discord-message-preview]').getAttribute('data-theme')) === 'dark', 'preview follows the dark scheme');
        once.add('dark-scheme-follows-app');
        await page.addScriptTag({path: require.resolve('axe-core/axe.min.js')});
        const axeOf = async (target, selector) => (await target.evaluate(([sel]) => axe.run(document.querySelector(sel), {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}}), [selector]))
          .violations.map(v => `${v.id}: ${v.nodes.slice(0, 2).map(n => n.target.join(' ')).join(' | ')}`);
        assert.deepEqual(await axeOf(page, '[data-testid="discord-sender-dialog"]'), [], 'axe: editor in the dark scheme');
        once.add('axe-editor-dark');
        await shot(page, 'webhook-editor-dark-app', {tall: true, evidence: true});
        await closeDialog();
        await page.emulateMedia({colorScheme: 'light'});
        await page.goto(base + '/app/channels', {waitUntil: 'domcontentloaded'});
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
      assert.deepEqual(world.unexpected, [], 'Only the sender-name routes and the refused approvals of the ceiling cases may be written; nothing is ever published, connected or approved');
      assert.equal(world.blocked, 0, 'No request left the isolated app');
      pass('no-unexpected-requests');
      await context.close();
      await browser.close(); browser = null;
    }

    stage = 'receipt';
    let receipt;
    if (WANT || ONLY) {
      receipt = {status: 'subset', note: 'RAFII_SENDER_CASES or RAFII_SENDER_COMBOS narrowed this run; it is not evidence', groups: WANT ? [...WANT] : 'all', combos: ONLY ? [...ONLY] : 'all', browserVersion, cases: Object.fromEntries(Object.entries(ran).map(([combo, names]) => [combo, [...names].sort()]))};
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
