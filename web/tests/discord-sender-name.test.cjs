/**
 * Customer Discord sender names, editor side: the validation rules against the server's verdicts, the availability
 * states, the three locale packs, the Discord-style preview, the state panels, the colours, and the CI wiring that runs
 * the browser cases. No network, no browser; the running-app cases are in discord-sender-name-browser.cjs.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { load, root } = require('./discord-sender-name-load.cjs');

const logic = load('src/lib/channels/discord-sender-name.ts');
const stateCopy = load('src/lib/channels/discord-sender-state-copy.ts');
const palette = load('src/lib/channels/discord-preview-theme.ts');
const { DiscordMessagePreview, previewTimeLabel, previewAuthor } = load('src/features/channels/discord-message-preview.tsx');
const { SenderStatePanel } = load('src/features/channels/discord-sender-state-panel.tsx');
const packs = JSON.parse(fs.readFileSync(path.join(root, 'src/lib/channels/discord-copy.json'), 'utf8'));
const verdicts = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/discord-sender-name-verdicts.json'), 'utf8'));
const repo = path.resolve(root, '..');
const LOCALES = ['en', 'zh-Hant', 'zh-Hans'];
const nameOf = (shared) => ('unit' in shared ? shared.unit.repeat(shared.repeat) : shared.name);
const html = (props) => renderToStaticMarkup(React.createElement(DiscordMessagePreview, props));
const text = (markup) => markup.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------------------------------------------------------
// Validation rules (contract v2)
// ---------------------------------------------------------------------------------------------------------------

test('the editor gives the same verdict, and the same first reason, as the server for every shared case', () => {
  assert.equal(verdicts.schema, 'rafii.discord-sender-name-verdicts.v4');
  assert.deepEqual(verdicts.limits, logic.SENDER_LIMIT);
  assert.ok(verdicts.cases.length >= 120);
  for (const shared of verdicts.cases) {
    const check = logic.checkSenderName(nameOf(shared), shared.kind);
    const label = `${shared.kind}: ${shared.note}`;
    assert.equal(check.issues.length === 0, shared.reason === null, label);
    // The server reports the first rule it finds; the editor lists every rule in the same order.
    if (shared.reason !== null) assert.equal(check.issues[0], shared.reason, label);
  }
});

test('the shared fixture covers every rule the server has, for both kinds', () => {
  const rules = new Set(verdicts.cases.map((shared) => shared.reason).filter(Boolean));
  assert.deepEqual([...rules].sort(), [...logic.SENDER_NAME_ISSUES].sort());
  for (const kind of ['webhook', 'bot']) {
    const mine = verdicts.cases.filter((shared) => shared.kind === kind);
    assert.ok(mine.some((shared) => shared.reason === null), `${kind} has accepted names`);
    assert.ok(mine.some((shared) => shared.reason !== null), `${kind} has refused names`);
  }
});

test('length is the binding of code points and UTF-16 units, as the server keeps both within the limit', () => {
  assert.equal(logic.codePointLength('abc'), 3);
  assert.equal(logic.codePointLength('\u{1F600}'), 1);
  assert.equal('\u{1F600}'.length, 2);
  assert.equal(logic.codePointLength('é'), 2);
  assert.equal(logic.codePointLength('D Festival 公告'), 13);
  const emoji = logic.checkSenderName('\u{1F600}'.repeat(41), 'webhook');
  assert.deepEqual({ length: emoji.length, codePoints: emoji.codePoints, over: emoji.over }, { length: 82, codePoints: 41, over: 2 });
  assert.ok(emoji.issues.includes('too_long'));
  assert.deepEqual(logic.checkSenderName('\u{1F600}'.repeat(40), 'webhook').issues, []);
  const over = logic.checkSenderName('x'.repeat(85), 'webhook');
  assert.deepEqual({ length: over.length, limit: over.limit, over: over.over }, { length: 85, limit: 80, over: 5 });
  assert.equal(logic.checkSenderName('x'.repeat(32), 'bot').over, 0);
  assert.equal(logic.checkSenderName('x'.repeat(33), 'bot').over, 1);
  // The profile's own limit wins when the server sends one.
  assert.equal(logic.checkSenderName('x'.repeat(10), 'bot', { limit: 8 }).over, 2);
});

test('zero width joiners are accepted only where the server accepts them', () => {
  const family = '\u{1F468}\u200d\u{1F469}\u200d\u{1F467}';
  const accepted = [
    family,
    '\u2764\ufe0f\u200d\u{1F525}', // an emoji with its variation selector, then a joiner
    '\u{1F469}\u{1F3FD}\u200d\u{1F4BB}', // a skin tone modifier before the joiner
    '\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645', // Persian, a non-joiner between letters
    '\u0915\u094d\u200c\u0937', // Devanagari, a non-joiner between a mark and a letter
    '^\u200d^' // two modifier symbols: the server counts them as symbols
  ];
  for (const name of accepted) assert.deepEqual(logic.checkSenderName(name, 'webhook').issues, [], JSON.stringify(name));
  const refused = [
    'join\u200dder', 'a\u200cb', '\u200dabc', 'abc\u200d', '\u200c\u0628', '\u0628\u200c \u0628',
    '\u{1F469}\u200dx', '\u{1F469}\u200d\ufe0f\u{1F468}', '\u{1F469}\u200d\u200d\u{1F468}', '\u0645\u200d\u0645'
  ];
  for (const name of refused) assert.deepEqual(logic.checkSenderName(name, 'webhook').issues, ['control_or_format'], JSON.stringify(name));
  // Other control and format characters are refused even next to an emoji sequence.
  assert.ok(logic.checkSenderName(`${family}\u200b`, 'webhook').issues.includes('control_or_format'));
  // The count is UTF-16 units: a family is 5 code points and 8 units, so 10 fit in 80 and 11 do not.
  const ten = logic.checkSenderName(family.repeat(10), 'webhook');
  assert.deepEqual({ length: ten.length, codePoints: ten.codePoints, over: ten.over, issues: ten.issues }, { length: 80, codePoints: 50, over: 0, issues: [] });
  assert.deepEqual(logic.checkSenderName(family.repeat(11), 'webhook').issues, ['too_long']);
  assert.deepEqual(logic.checkSenderName(family.repeat(5), 'bot').issues, ['too_long']);
});

test('reserved words fold the way the server folds, and a bot nickname refuses fewer of them than a webhook name', () => {
  const webhookOnly = ['discord', 'Discord', 'DISCORD', 'xClydex', 'diſcord', 'D1scord', 'd i s c o r d', 'dis_cord', 'dіscord', 'DİSCORD', 'ClYdE'];
  const both = ['P0stR1ff', 'RAFII', 'r a f i i', 'Rafii Helper', 'xpostriffx'];
  for (const word of [...webhookOnly, ...both]) assert.ok(logic.checkSenderName(word, 'webhook').issues.includes('reserved_word'), `webhook ${word}`);
  for (const word of both) assert.ok(logic.checkSenderName(word, 'bot').issues.includes('reserved_word'), `bot ${word}`);
  // Discord restricts usernames, not server nicknames: only the product's names stay reserved on a bot.
  for (const word of [...webhookOnly, 'Everyone', 'HERE', 'he re']) assert.ok(!logic.checkSenderName(word, 'bot').issues.includes('reserved_word'), `bot ${word}`);
  for (const name of ['Everyone', 'HERE', 'he re']) {
    assert.ok(logic.isReservedName(name, 'webhook'), name);
    assert.ok(!logic.isReservedName(name, 'bot'), name);
  }
  for (const fine of ['Here Maps', 'Everyone Welcome', 'Hero', 'Traffic Updates', 'Safari News', 'Acme Weekly']) {
    for (const kind of ['webhook', 'bot']) assert.ok(!logic.isReservedName(fine, kind), `${kind} ${fine}`);
  }
  assert.deepEqual(logic.RESERVED_PARTS.bot, ['rafii', 'postriff']);
  assert.deepEqual(logic.RESERVED_WHOLE.bot, []);
  // Look-alike folding is the server's table, character for character.
  assert.deepEqual(logic.reservedSkeletons('Dïscörd'), ['discord', 'discord']);
  assert.deepEqual(logic.reservedSkeletons('C1yde'), ['ciyde', 'clyde']);
});

test('an unpaired surrogate is a control character, never a crash', () => {
  for (const kind of ['webhook', 'bot']) {
    assert.deepEqual(logic.checkSenderName('a\ud800b', kind).issues, ['control_or_format']);
    // Alone it is also nothing visible; the server reports the first rule, and the first is this one.
    assert.equal(logic.checkSenderName('\udc00', kind).issues[0], 'control_or_format');
  }
});

test('every broken rule is listed in the server order, not only the first', () => {
  const issues = logic.checkSenderName(` ${'​'}${'x'.repeat(90)}@Discord www.x `, 'webhook').issues;
  assert.deepEqual(issues, ['surrounding_space', 'too_long', 'control_or_format', 'forbidden_character', 'url_like', 'reserved_word']);
  assert.deepEqual(logic.checkSenderName('', 'bot').issues, ['empty']);
  assert.deepEqual(logic.checkSenderName('   ', 'bot').issues, ['empty']);
  assert.deepEqual(logic.checkSenderName('Acme Weekly', 'webhook').issues, []);
});

test('the forbidden characters follow the list the server sends', () => {
  assert.ok(logic.checkSenderName('a|b', 'webhook', { forbidden: ['|'] }).issues.includes('forbidden_character'));
  assert.ok(!logic.checkSenderName('a@b', 'webhook', { forbidden: ['|'] }).issues.includes('forbidden_character'));
  assert.deepEqual(logic.FORBIDDEN_CHARACTERS, ['@', '#', ':', '```', '<', '>']);
});

// ---------------------------------------------------------------------------------------------------------------
// Availability states (contract v2)
// ---------------------------------------------------------------------------------------------------------------

const NOW = 1_800_000_000_000;

test('a readable profile lists every reason the name cannot be changed, in the order the server sent them', () => {
  const classify = (profile) => logic.classifySenderProfile(profile, NOW);
  assert.deepEqual(classify({}), []);
  assert.deepEqual(classify({ editable: true, unavailable: [] }), []);
  for (const code of logic.UNAVAILABLE_CODES) {
    const [state] = classify({ editable: false, unavailable: [{ code }] });
    assert.equal(state.key, code, code);
    assert.equal(state.signInAgain, code === 'session_reverification_required', code);
  }
  assert.deepEqual(classify({ editable: false, unavailable: [{ code: 'edit_pending', retryAfterSeconds: 90 }] }), [{ key: 'edit_pending', retryAfterSeconds: 90, retryAtMs: NOW + 90_000, signInAgain: false }]);
  assert.deepEqual(classify({ editable: false, unavailable: [{ code: 'bot_missing_change_nickname', retryAfterSeconds: 5 }] })[0], { key: 'bot_missing_change_nickname', retryAfterSeconds: null, retryAtMs: null, signInAgain: false });
  const several = classify({ editable: false, unavailable: [{ code: 'person_missing_manage_nicknames' }, { code: 'bot_missing_change_nickname' }, { code: 'edit_pending', retryAfterSeconds: 30 }, { code: 'edit_pending' }] });
  assert.deepEqual(several.map((state) => state.key), ['person_missing_manage_nicknames', 'bot_missing_change_nickname', 'edit_pending']);
  // Not editable with nothing we recognise: say so, never guess a cause.
  assert.deepEqual(classify({ editable: false }).map((state) => state.key), ['failed']);
  assert.deepEqual(classify({ editable: false, unavailable: [{ code: 'something_new' }] }).map((state) => state.key), ['failed']);
});

test('a refused request maps to the state the contract names, never to a guessed cause', () => {
  const states = (error) => logic.classifySenderRefusal(error, NOW);
  const first = (error) => states(error)[0];
  for (const code of logic.UNAVAILABLE_CODES) {
    assert.equal(first({ status: 409, code: 'discord_sender_name_unavailable', reasons: [{ code }] }).key, code, code);
  }
  assert.deepEqual(states({ status: 403, code: 'discord_sender_name_unavailable', reasons: [{ code: 'person_role_below_bot' }, { code: 'bot_missing_change_nickname' }] }).map((state) => state.key), ['person_role_below_bot', 'bot_missing_change_nickname']);
  assert.deepEqual(first({ status: 409, code: 'discord_sender_edit_pending', retryAfterSeconds: 118 }), { key: 'edit_pending', retryAfterSeconds: 118, retryAtMs: NOW + 118_000, signInAgain: false });
  assert.deepEqual(first({ status: 409, code: 'discord_sender_edit_pending' }), { key: 'edit_pending', retryAfterSeconds: null, retryAtMs: null, signInAgain: false });
  assert.equal(first({ status: 409, code: 'discord_sender_name_required' }).key, 'stale');
  assert.equal(first({ status: 409, code: 'discord_connection_required' }).key, 'reconnect_required');
  assert.equal(first({ status: 409, code: 'discord_sender_write_unconfirmed' }).key, 'write_unconfirmed');
  // Discord refused the write (nothing changed) and Discord accepted it without confirming (it may have changed) are different answers.
  assert.equal(first({ status: 409, code: 'discord_sender_write_refused' }).key, 'write_refused');
  // 409: reconnect the connection. 503: Discord connections are paused for the whole provider, which a reconnect cannot fix.
  assert.equal(first({ status: 503, code: 'discord_connection_required' }).key, 'provider_unavailable');
  // The provider is not ready: a 503 that still names its reason.
  assert.deepEqual(states({ status: 503, code: 'discord_sender_name_unavailable', reasons: [{ code: 'provider_unavailable' }] }).map((state) => state.key), ['provider_unavailable']);
  // Discord answered the write itself with a rate limit: its own state, with Discord's wait; unchanged, and not a permission problem.
  assert.deepEqual(first({ status: 429, code: 'discord_sender_write_rate_limited', retryAfterSeconds: 31 }), { key: 'write_rate_limited', retryAfterSeconds: 31, retryAtMs: NOW + 31_000, signInAgain: false });
  assert.equal(first({ status: 409, code: 'discord_sender_evidence_invalid' }).key, 'evidence_invalid');
  assert.equal(first({ status: 503, code: 'discord_rate_coordinator_unavailable' }).key, 'provider_unavailable');
  // Rafii's own throttle names what is left of a 10 minute window.
  assert.deepEqual(first({ status: 429, code: 'rate_limited', retryAfterSeconds: 600 }), { key: 'rate_limited', retryAfterSeconds: 600, retryAtMs: NOW + 600_000, signInAgain: false });
  // Discord's shared request capacity is its own state, with the wait it named; Rafii's own throttle stays rate_limited.
  assert.deepEqual(first({ status: 429, code: 'discord_rate_delayed', retryAfterSeconds: 7 }), { key: 'rate_delayed', retryAfterSeconds: 7, retryAtMs: NOW + 7_000, signInAgain: false });
  assert.equal(first({ status: 429, code: 'discord_rate_delayed' }).retryAtMs, null);
  assert.equal(first({ status: 404, code: 'not_found' }).key, 'reconnect_required');
  assert.equal(first({ status: 403, code: 'permission_denied' }).key, 'workspace_permission');
  assert.deepEqual(first({ status: 429, code: 'rate_limited', retryAfterSeconds: 60 }), { key: 'rate_limited', retryAfterSeconds: 60, retryAtMs: NOW + 60_000, signInAgain: false });
  assert.deepEqual(first({ status: 403, code: 'step_up_required' }), { key: 'session_reverification_required', retryAfterSeconds: null, retryAtMs: null, signInAgain: true });
  assert.deepEqual(first({ status: 403, code: 'security_step_up_required' }), { key: 'session_reverification_required', retryAfterSeconds: null, retryAtMs: null, signInAgain: false });
  assert.deepEqual(first({ status: 401, code: 'unauthenticated' }), { key: 'session_reverification_required', retryAfterSeconds: null, retryAtMs: null, signInAgain: true });
  assert.equal(first({ status: 403, message: 'Please sign in again to continue.' }).signInAgain, true);
  for (const status of [502, 503, 504]) assert.equal(first({ status }).key, 'upstream_unavailable', String(status));
  assert.equal(first({}).key, 'upstream_unavailable', 'a network failure has no status');
  // Anything else, including a 409 with a code from the previous backend, is the generic failure.
  assert.equal(first({ status: 500 }).key, 'failed');
  assert.equal(first({ status: 409, code: 'something_new' }).key, 'failed');
  assert.equal(first({ status: 403, code: 'discord_sender_name_unavailable', reasons: [{ code: 'something_new' }] }).key, 'failed');
  assert.equal(first({ status: 403, code: 'discord_sender_name_required' }).key, 'failed');
  assert.equal(first({ status: 400, code: 'discord_sender_name_required' }).key, 'failed');
});

test('only the states that can change offer a check, and a check is a read', () => {
  const offered = logic.SENDER_STATES.filter((key) => logic.canCheckAgain(key));
  assert.deepEqual(offered.sort(), ['bot_missing_change_nickname', 'edit_pending', 'evidence_invalid', 'failed', 'nickname_authority_other_workspace', 'person_missing_manage_nicknames', 'person_role_below_bot', 'provider_unavailable', 'rate_delayed', 'rate_limited', 'reconnect_required', 'stale', 'upstream_unavailable', 'write_rate_limited', 'write_refused', 'write_unconfirmed'].sort());
  // The contract: these three are answered without Discord and must not be retried.
  for (const key of ['sender_names_disabled', 'bot_nickname_disabled', 'not_authorizing_member']) assert.equal(logic.canCheckAgain(key), false, key);
  assert.equal(logic.canCheckAgain('ready'), false);
});

test('the twenty-two states are the twenty-one the copy explains plus ready', () => {
  assert.equal(logic.SENDER_STATES.length, 22);
  assert.deepEqual([...logic.UNAVAILABLE_CODES], ['sender_names_disabled', 'bot_nickname_disabled', 'provider_unavailable', 'not_authorizing_member', 'session_reverification_required', 'person_missing_manage_nicknames', 'person_role_below_bot', 'bot_missing_change_nickname', 'nickname_authority_other_workspace', 'edit_pending'], 'the server order of the reasons (REASON_ORDER)');
  assert.equal(logic.SENDER_STATES[0], 'ready');
  assert.deepEqual([...stateCopy.BLOCKED_STATES].sort(), logic.SENDER_STATES.filter((key) => key !== 'ready').sort());
  for (const code of logic.UNAVAILABLE_CODES) assert.ok(logic.SENDER_STATES.includes(code), code);
});

test('retry times and waits are formatted for the reader and never invented', () => {
  assert.equal(logic.formatRetryTime(null, 'en'), null);
  assert.equal(logic.formatRetryTime(Number.NaN, 'en'), null);
  assert.match(logic.formatRetryTime(1792749000000, 'en', 'UTC'), /\d{1,2}:\d{2}/);
  assert.equal(logic.formatWait(60, 'en'), '60 seconds');
  assert.equal(logic.formatWait(2, 'en'), '2 seconds');
  assert.equal(logic.formatWait(89, 'en'), '89 seconds');
  assert.equal(logic.formatWait(90, 'en'), '2 minutes');
  assert.equal(logic.formatWait(118, 'en'), '2 minutes');
  assert.equal(logic.formatWait(121, 'en'), '3 minutes');
  assert.match(logic.formatWait(60, 'zh-Hant'), /^60\s*秒$/);
  assert.match(logic.formatWait(120, 'zh-Hans'), /^2\s*分钟$/);
  const en = packs.en;
  const state = (retryAtMs, retryAfterSeconds) => ({ retryAtMs, retryAfterSeconds });
  assert.equal(stateCopy.recheckLine(en, state(null, null), 'en'), en.senderRecheckSoon);
  assert.equal(stateCopy.recheckLine(en, state(1792749000000, 60), 'en', 'UTC', 1792749001000), en.senderRecheckNow);
  assert.match(stateCopy.recheckLine(en, state(1792749060000, 60), 'en', 'UTC', 1792749000000), /^Rafii can check again in about 60 seconds, at \d{1,2}:\d{2}/);
  assert.match(stateCopy.recheckLine(en, state(1792749120000, 118), 'en', 'UTC', 1792749000000), /^Rafii can check again in about 2 minutes, at \d{1,2}:\d{2}/);
  // A time without a named wait is still honest about the time only.
  assert.match(stateCopy.recheckLine(en, state(1792749120000, null), 'en', 'UTC', 1792749000000), /^Rafii can check again at \d{1,2}:\d{2}/);
});

test('the card offers the control only when the provider view says yes for that kind', () => {
  const offers = (modes, kind) => logic.senderProviderOffers(modes, kind);
  // Every switch is off unless the server says "true", so a view that is missing, empty or false offers nothing.
  assert.equal(offers(undefined, 'bot'), false);
  assert.equal(offers(null, 'webhook'), false);
  assert.equal(offers({}, 'webhook'), false);
  assert.equal(offers({ bot: { nickname: {} }, webhook: { senderName: {} } }, 'bot'), false, 'a flag that is not present is not a yes');
  assert.equal(offers({ bot: { nickname: { enabled: false } }, webhook: { senderName: { enabled: false } } }, 'bot'), false);
  assert.equal(offers({ bot: { nickname: { enabled: true } } }, 'bot'), true);
  assert.equal(offers({ webhook: { senderName: { enabled: true } } }, 'webhook'), true);
  assert.equal(offers({ bot: { nickname: { enabled: true } } }, 'webhook'), false, 'the bot flag never opens webhook names');
  assert.equal(offers({ webhook: { senderName: { enabled: true } } }, 'bot'), false, 'the webhook flag never opens bot nicknames');
  assert.equal(offers({ webhook: { enabled: true, senderName: { enabled: false } } }, 'webhook'), false, 'the webhook route being open is not the name flag');
});

test('a bot nickname is drawn only when it is known, and a hold is claimed only when something is recorded', () => {
  assert.deepEqual(logic.botNicknameView(undefined, 'channel'), { name: null, source: 'unknown', hold: undefined });
  assert.deepEqual(logic.botNicknameView(undefined, 'manifest'), { name: null, source: 'unknown', hold: undefined });
  assert.deepEqual(logic.botNicknameView('Concert helper', 'channel'), { name: 'Concert helper', source: 'observed', hold: 'pending' });
  assert.deepEqual(logic.botNicknameView('Concert helper', 'manifest'), { name: 'Concert helper', source: 'approved', hold: 'approved' });
  assert.deepEqual(logic.botNicknameView(null, 'channel'), { name: null, source: 'bot_username', hold: 'pending' });
  assert.deepEqual(logic.botNicknameView('', 'manifest'), { name: null, source: 'bot_username', hold: 'approved' });
});

test('a verification says what happened, and the held-post line is recognised without a code', () => {
  const say = (outcome, locale = 'en') => stateCopy.verifyMessage(packs[locale], outcome);
  assert.deepEqual(say({ verified: true, state: 'read_verified' }), { kind: 'done', text: packs.en.senderVerifyDone });
  assert.deepEqual(say({ verified: false, state: 'verification_unavailable' }), { kind: 'repeat', text: packs.en.senderVerifyRepeat });
  assert.equal(say({ verified: false, state: 'reauthorization_required', detail: 'The bot is not in this server.' }).text, 'The connection could not be verified: The bot is not in this server.');
  assert.equal(say({ verified: false, state: 'reauthorization_required' }).text, 'The connection could not be verified: reauthorization required');
  assert.equal(say({ verified: false }, 'zh-Hant').kind, 'failed');
  // The line the worker writes when a bot post is held for a changed nickname (contract, held event line).
  assert.ok(stateCopy.isNicknameHoldNote('The Rafii bot’s server nickname is no longer the one this post was approved under; nothing was posted. Review the post again.'));
  assert.ok(stateCopy.isNicknameHoldNote("The Rafii bot's server nickname is no longer the one this post was approved under. Nothing was posted."));
  assert.ok(!stateCopy.isNicknameHoldNote('Discord custom sender names are switched off; nothing was posted.'));
  assert.ok(!stateCopy.isNicknameHoldNote(null) && !stateCopy.isNicknameHoldNote(undefined));
});

// ---------------------------------------------------------------------------------------------------------------
// Copy: three complete locale packs
// ---------------------------------------------------------------------------------------------------------------

const placeholders = (string) => [...string.matchAll(/\{[a-zA-Z]+\}/g)].map((match) => match[0]).sort().join(',');
const SENDER_KEYS = Object.keys(packs.en).filter((name) => /^(sender|preview)/.test(name));

test('all three locales carry every sender-name and preview line with the same placeholders', () => {
  assert.ok(SENDER_KEYS.length >= 100, `only ${SENDER_KEYS.length} sender or preview lines`);
  for (const locale of LOCALES) assert.deepEqual(Object.keys(packs[locale]).sort(), Object.keys(packs.en).sort(), locale);
  for (const name of SENDER_KEYS) {
    for (const locale of LOCALES) {
      assert.equal(typeof packs[locale][name], 'string', `${locale}.${name}`);
      assert.ok(packs[locale][name].trim(), `${locale}.${name} is empty`);
      assert.equal(placeholders(packs[locale][name]), placeholders(packs.en[name]), `${locale}.${name} placeholders`);
    }
  }
});

test('the Chinese packs are translated, not copied from English, and each uses its own script', () => {
  const english = new Set(['senderWebhookKind', 'previewAppTag']);
  const simplifiedOnly = /[这个们为发过时没会对说开关电邮网设选择无户机务连权员帐账]/;
  const traditionalOnly = /[這個們為發過時沒會對說開關電郵網設選擇無戶機務連權員帳賬]/;
  for (const name of SENDER_KEYS) {
    for (const locale of ['zh-Hant', 'zh-Hans']) {
      const line = packs[locale][name];
      if (!english.has(name)) assert.match(line, /[一-鿿]/, `${locale}.${name} has no Chinese`);
      if (locale === 'zh-Hant') assert.doesNotMatch(line, simplifiedOnly, `zh-Hant.${name} uses a Simplified-only character`);
      if (locale === 'zh-Hans') assert.doesNotMatch(line, traditionalOnly, `zh-Hans.${name} uses a Traditional-only character`);
    }
  }
});

test('every state has a title, a body and a next step in each locale', () => {
  for (const state of stateCopy.BLOCKED_STATES) {
    for (const locale of LOCALES) {
      const lines = stateCopy.senderStateCopy(packs[locale], state);
      for (const part of ['title', 'body', 'next']) assert.ok(lines[part] && lines[part].trim(), `${locale}.${state}.${part}`);
    }
    const english = stateCopy.senderStateCopy(packs.en, state);
    assert.notEqual(english.title, english.body);
  }
  // Each situation says something different.
  const titles = new Set(stateCopy.BLOCKED_STATES.map((state) => stateCopy.senderStateCopy(packs.en, state).title));
  assert.equal(titles.size, stateCopy.BLOCKED_STATES.length);
});

test('the messages never name another workspace and say what the person can do', () => {
  for (const locale of LOCALES) {
    const shared = stateCopy.senderStateCopy(packs[locale], 'nickname_authority_other_workspace');
    assert.doesNotMatch(`${shared.title}${shared.body}${shared.next}`, /workspace\s+(id|named)|[0-9a-f]{8}-[0-9a-f]{4}/i);
  }
  const english = (state) => stateCopy.senderStateCopy(packs.en, state);
  assert.match(english('sender_names_disabled').next, /Nothing to do/);
  assert.doesNotMatch(english('sender_names_disabled').body, /held/, 'the held-post sentence is shown for webhooks only, in its own line');
  assert.match(packs.en.senderStateHeldNote, /is held, and nothing is sent/);
  assert.match(packs.en.senderStateHeldNote, /never sent under another name/);
  assert.match(packs.en.senderStateHeldNote, /stays held after the feature is back on/);
  assert.match(english('bot_nickname_disabled').next, /incoming webhook/);
  assert.match(english('bot_nickname_disabled').body, /Webhook sender names are not affected/);
  assert.match(english('not_authorizing_member').next, /Ask that member/);
  assert.match(english('not_authorizing_member').title, /bot/, 'only the bot nickname is restricted to the authorizing member');
  assert.match(english('not_authorizing_member').body, /Webhook sender names are not affected/);
  assert.match(english('provider_unavailable').body, /on Rafii’s side/);
  assert.match(english('provider_unavailable').next, /Nothing to fix on your side/);
  assert.match(english('rate_delayed').body, /Nothing was changed/);
  assert.match(english('rate_delayed').next, /Rafii does not retry for you/);
  assert.notEqual(english('rate_delayed').title, english('rate_limited').title, 'Discord asking Rafii to wait is not Rafii\'s own limit');
  assert.match(english('person_missing_manage_nicknames').body, /Manage Nicknames/);
  assert.match(english('person_role_below_bot').body, /highest role is above the bot’s highest role/);
  assert.match(english('bot_missing_change_nickname').body, /Change Nickname/);
  assert.match(english('nickname_authority_other_workspace').body, /does not let any workspace change that nickname/);
  assert.match(english('nickname_authority_other_workspace').body, /does not say which workspace/);
  assert.match(english('edit_pending').next, /never sends the change a second time/);
  assert.match(english('stale').body, /another member|another Rafii workspace/);
  assert.match(english('session_reverification_required').next, /Sign out and sign in again/);
  assert.match(english('reconnect_required').next, /Channels page/);
  assert.match(english('write_unconfirmed').body, /The nickname may have changed, and Rafii did not try again/);
  assert.match(english('write_unconfirmed').next, /Check again/);
  assert.match(english('write_refused').body, /The nickname is unchanged, nothing is waiting, and Rafii did not try again/);
  assert.match(english('write_refused').next, /Check again/);
  assert.notEqual(english('write_refused').title, english('write_unconfirmed').title, 'a refusal and an unconfirmed write are different news');
  assert.match(english('write_rate_limited').body, /not a permission problem/);
  assert.match(english('write_rate_limited').body, /The nickname is unchanged, nothing is waiting, and Rafii did not try again/);
  assert.notEqual(english('write_rate_limited').title, english('rate_delayed').title, 'Discord refusing the write is not the shared budget running out');
  assert.match(english('evidence_invalid').body, /Nothing was changed/);
  assert.match(english('evidence_invalid').next, /reconnect the Discord installation/);
  assert.match(english('rate_limited').next, /Wait until the time shown/);
  for (const gone of ['senderCardOff', 'senderCardOffBot', 'senderWhyButton', 'senderViewTitle', 'senderViewDescription']) assert.ok(!(gone in packs.en), `${gone}: with nothing shown while editing is unavailable the card needs no such line`);
  assert.match(english('rate_limited').body, /Nothing was changed/);
  assert.match(english('upstream_unavailable').body, /Nothing was changed/);
  assert.match(english('workspace_permission').next, /workspace owner or administrator/);
});

test('validation messages fill their numbers and name the rule', () => {
  const numbers = { length: 85, limit: 80, over: 5 };
  assert.equal(stateCopy.senderIssueMessage(packs.en, 'too_long', numbers), 'Too long: 85 of 80 characters. Remove 5. Emoji and some symbols count as 2.');
  for (const locale of LOCALES) {
    for (const issue of logic.SENDER_NAME_ISSUES) {
      const message = stateCopy.senderIssueMessage(packs[locale], issue, numbers);
      assert.ok(message.trim() && !/\{[a-z]+\}/.test(message), `${locale}.${issue}`);
    }
    assert.match(stateCopy.senderIssueMessage(packs[locale], 'reserved_word', numbers), /Discord/);
    assert.match(stateCopy.senderIssueMessage(packs[locale], 'reserved_word', numbers), /Rafii/);
    assert.match(stateCopy.senderIssueMessage(packs[locale], 'forbidden_character', numbers), /@ # : < >/);
  }
  assert.equal(stateCopy.fillCount(packs.en.senderCount, { count: 7, limit: 80 }), '7 / 80 characters');
  assert.equal(stateCopy.fillCount(packs.en.senderIssueSummary, { limit: 32 }), 'Choose a name of 1–32 characters without surrounding spaces, control characters, reserved words or mention syntax.');
  // The rules list names every limit the editor enforces.
  assert.equal(packs.en.senderRuleLength.replace('{limit}', '80'), '80 characters at most. Emoji and some symbols count as 2.');
  assert.match(packs.en.senderRuleForbidden, /@ # : < > and ```/);
  assert.match(packs.en.senderRuleReserved, /Discord, Clyde, Rafii, PostRiff, everyone or here/);
  assert.equal(packs.en.senderRuleReservedBot, 'Not Rafii or PostRiff. Look-alikes count too.');
  assert.doesNotMatch(stateCopy.senderIssueMessage(packs.en, 'reserved_word', numbers, 'bot'), /Discord|Clyde|everyone/);
  assert.match(stateCopy.senderIssueMessage(packs.en, 'reserved_word', numbers, 'webhook'), /Discord/);
});

// ---------------------------------------------------------------------------------------------------------------
// Preview
// ---------------------------------------------------------------------------------------------------------------

const AT = new Date('2026-10-25T09:05:00Z');
const base = (locale, extra) => ({ kind: 'webhook', name: 'D Festival 公告', nameSource: 'saved', copy: packs[locale], locale, timeZone: 'UTC', publishAt: AT, heading: packs[locale].previewHeading, ...extra });

test('a webhook post is shown with its custom name, the APP tag, a time and its line breaks', () => {
  for (const locale of LOCALES) {
    const copy = packs[locale];
    const markup = html(base(locale, { text: 'Line one\nLine two\n\nLine four  indented', theme: 'dark' }));
    assert.match(markup, /data-kind="webhook"/);
    assert.match(markup, /data-theme="dark"/);
    assert.match(markup, /<span data-preview-author[^>]*>D Festival 公告<\/span>/);
    assert.match(markup, new RegExp(`<span data-preview-app-tag[^>]*>${copy.previewAppTag}</span>`));
    assert.match(markup, /<time[^>]*datetime="2026-10-25T09:05:00.000Z"/i);
    assert.match(markup, /data-preview-avatar/);
    assert.match(markup, /Line one\nLine two\n\nLine four  indented/);
    assert.match(markup, /whitespace-pre-wrap/);
    assert.ok(markup.includes(copy.previewWebhookNote), `${locale} webhook note`);
    assert.ok(!markup.includes(copy.previewBotNote), `${locale} must not say the bot sentence for a webhook`);
    assert.ok(markup.includes(copy.previewAvatarWebhook), `${locale} avatar note`);
    assert.ok(markup.includes(copy.previewFidelity), `${locale} fidelity note`);
    assert.match(markup, /data-discord-sender-preview/);
    // A screen reader gets the message as one named group, described by the notes that say what the picture cannot show.
    assert.match(markup, /role="group"/);
    assert.ok(markup.includes(`aria-label="${copy.previewMessageLabel}"`), `${locale} group label`);
    const notesId = /aria-describedby="([^"]+)"/.exec(markup)?.[1];
    assert.ok(notesId && markup.includes(`id="${notesId}"`), `${locale} the group points at the notes`);
    assert.match(markup, /data-preview-avatar[^>]*aria-hidden="true"|aria-hidden="true"[^>]*data-preview-avatar/);
  }
});

test('a bot post is shown with the shared server nickname and never as a per-post name', () => {
  for (const locale of LOCALES) {
    const copy = packs[locale];
    const known = html(base(locale, { kind: 'bot', name: 'Concert helper', nameSource: 'observed', text: 'Doors open at 7.' }));
    assert.match(known, /data-kind="bot"/);
    assert.match(known, /<span data-preview-author[^>]*>Concert helper<\/span>/);
    assert.ok(known.includes(copy.previewBotNote), `${locale} shared-nickname note`);
    assert.ok(known.includes(copy.previewBotNameAsOf), `${locale} as-of note`);
    assert.ok(!known.includes(copy.previewWebhookNote), `${locale} must not say the webhook sentence for a bot`);
    assert.ok(known.includes(copy.previewAvatarBot), `${locale} avatar note`);
    assert.match(known, /data-preview-app-tag/);
    const unknown = html(base(locale, { kind: 'bot', name: null, nameSource: 'unknown', text: 'Doors open at 7.' }));
    assert.match(unknown, /data-placeholder="true"/);
    assert.ok(unknown.includes(copy.previewBotNameUnknown), `${locale} generic bot name`);
    assert.ok(unknown.includes(copy.previewBotNameUnknownNote), `${locale} unknown-name note`);
  }
  const en = packs.en.previewBotNote;
  assert.match(en, /Everyone who uses this bot in this server/);
  assert.match(en, /people who use other apps there/);
  assert.match(en, /people who never use Rafii/);
  assert.match(en, /other Rafii workspaces/);
  assert.match(en, /cannot freeze it per post/);
  assert.match(en, /server administrator can change it at any time/);
});

test('queued posts: a webhook post keeps its approved name, a bot post is held if its nickname changes, and neither is promised unless it is known', () => {
  const hook = html(base('en', { text: 'Hi' }));
  assert.ok(hook.includes(packs.en.previewWebhookQueuedNote));
  assert.ok(!hook.includes(packs.en.previewBotQueuedNote));
  assert.ok(!html(base('en', { text: 'Hi', queuedKeepsName: false })).includes(packs.en.previewWebhookQueuedNote));
  const bot = (extra) => html(base('en', { kind: 'bot', name: 'Concert helper', nameSource: 'observed', text: 'Hi', ...extra }));
  assert.ok(bot({ botHold: 'pending' }).includes(packs.en.previewBotQueuedNote));
  assert.ok(!bot({ botHold: 'pending' }).includes(packs.en.previewWebhookQueuedNote));
  assert.ok(bot({ botHold: 'approved' }).includes(packs.en.previewBotApprovedNote));
  assert.ok(!bot({ botHold: 'approved' }).includes(packs.en.previewBotQueuedNote));
  // Without knowledge that the approval records the nickname, nothing about holding is claimed.
  assert.ok(!bot({}).includes(packs.en.previewBotQueuedNote) && !bot({}).includes(packs.en.previewBotApprovedNote));
  assert.ok(bot({}).includes(packs.en.previewBotNote));
  for (const locale of LOCALES) {
    const botNote = html(base(locale, { kind: 'bot', name: 'x', nameSource: 'observed', text: 'Hi', botHold: 'pending' }));
    assert.ok(!botNote.includes(packs[locale].previewWebhookQueuedNote), `${locale}: a bot post is never said to keep a name`);
    assert.ok(botNote.includes(packs[locale].previewBotQueuedNote), `${locale}: the hold note`);
  }
  assert.match(packs.en.previewBotQueuedNote, /holds the post, sends nothing, and asks you to review it again/);
  assert.match(packs.en.previewBotApprovedNote, /held and nothing is sent/);
  assert.doesNotMatch(packs.en.previewBotNote + packs.en.previewBotQueuedNote + packs.en.previewBotApprovedNote, /keeps? the name|whatever nickname the bot has when they are sent/i);
});

test('the preview follows what is typed, and says it is not saved yet', () => {
  const draft = html(base('en', { name: '', nameSource: 'draft', kind: 'webhook' }));
  assert.match(draft, /data-placeholder="true"/);
  assert.ok(draft.includes(packs.en.previewEmptyName));
  assert.ok(draft.includes(packs.en.senderPreviewUnsaved));
  assert.ok(draft.includes(packs.en.senderExample));
  assert.ok(draft.includes(packs.en.previewSampleNote));
  assert.deepEqual(previewAuthor(packs.en, 'webhook', '  ', 'saved'), { label: packs.en.previewWebhookNameDefault, placeholder: true });
  assert.deepEqual(previewAuthor(packs.en, 'bot', null, 'unknown'), { label: packs.en.previewBotNameUnknown, placeholder: true });
  assert.deepEqual(previewAuthor(packs.en, 'bot', 'Rafii', 'observed'), { label: 'Rafii', placeholder: false });
});

test('a webhook default name and a bot username are labelled as what they are', () => {
  const fallback = html(base('en', { kind: 'webhook', name: 'Spidey Bot', nameSource: 'webhook_default', text: 'Hi' }));
  assert.match(fallback, /<span data-preview-author[^>]*>Spidey Bot<\/span>/);
  assert.ok(fallback.includes(packs.en.previewWebhookDefaultNote));
  const username = html(base('en', { kind: 'bot', name: 'Rafii Helper', nameSource: 'bot_username', text: 'Hi' }));
  assert.ok(username.includes(packs.en.previewBotUsernameNote));
  assert.ok(username.includes(packs.en.previewBotNote));
  const tagged = html(base('en', { badge: 'APP', text: 'Hi' }));
  assert.match(tagged, /<span data-preview-app-tag[^>]*>APP<\/span>/);
});

test('light and dark use their own palette, and compact mode keeps the honest lines', () => {
  const dark = html(base('en', { theme: 'dark', text: 'Hello' }));
  const light = html(base('en', { theme: 'light', text: 'Hello' }));
  assert.ok(dark.includes(palette.DISCORD_PREVIEW_PALETTE.dark.surface) || dark.includes('rgb(49, 51, 56)'));
  assert.ok(light.includes(palette.DISCORD_PREVIEW_PALETTE.light.surface) || light.includes('rgb(255, 255, 255)'));
  assert.match(dark, /data-theme="dark"/);
  assert.match(light, /data-theme="light"/);
  const compact = html(base('en', { text: 'Hello', compact: true, kind: 'bot', name: null, nameSource: 'unknown' }));
  assert.ok(compact.includes(packs.en.previewCompactNote));
  assert.ok(compact.includes(packs.en.previewBotNote));
  assert.doesNotMatch(compact, /data-preview-avatar-note|data-preview-fidelity-note/);
  const toggled = html(base('en', { themeToggle: true }));
  assert.match(toggled, /data-preview-theme-toggle/);
  assert.equal((toggled.match(/aria-pressed="/g) || []).length, 2);
});

test('names and text are escaped, never interpreted as markup', () => {
  const hostile = html(base('en', { name: '<img src=x onerror=alert(1)>', text: '<script>alert(1)</script> **bold** https://example.test/' }));
  assert.doesNotMatch(hostile, /<img src=x|<script>alert/);
  assert.match(hostile, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(hostile, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
});

test('an empty message and attached pictures are drawn honestly', () => {
  const empty = html(base('en', { text: '   ' }));
  assert.ok(empty.includes(packs.en.previewEmptyText));
  assert.match(empty, /data-empty="true"/);
  const withPicture = html(base('en', { text: 'Photo', media: [{ url: 'blob:synthetic', alt: 'A stage' }] }));
  assert.match(withPicture, /<img[^>]+alt="A stage"/);
});

test('the time reads as Discord shows it: today, or a dated time', () => {
  // ICU may put a narrow no-break space before AM or PM; readers see a space either way.
  const label = (...args) => previewTimeLabel(...args).replace(/[\u202f\u00a0]/g, ' ');
  const now = new Date('2026-10-25T20:00:00Z');
  assert.equal(label(packs.en, 'en', AT, 'UTC', now), 'Today at 9:05 AM');
  assert.equal(label(packs['zh-Hant'], 'zh-Hant', AT, 'UTC', now).startsWith('今天 '), true);
  assert.equal(label(packs['zh-Hans'], 'zh-Hans', AT, 'UTC', now).startsWith('今天 '), true);
  assert.equal(label(packs.en, 'en', AT, 'UTC', new Date('2026-10-30T00:00:00Z')), '10/25/2026 9:05 AM');
  // The same two instants are the same day in UTC and different days in Hong Kong.
  const late = new Date('2026-10-25T23:30:00Z');
  const earlier = new Date('2026-10-25T10:00:00Z');
  assert.equal(label(packs.en, 'en', late, 'UTC', earlier), 'Today at 11:30 PM');
  assert.equal(label(packs.en, 'en', late, 'Asia/Hong_Kong', earlier), '10/26/2026 7:30 AM');
});

// ---------------------------------------------------------------------------------------------------------------
// State panels
// ---------------------------------------------------------------------------------------------------------------

test('each availability state renders its own message in every locale with a stable test id', () => {
  const seen = new Set();
  for (const locale of LOCALES) {
    for (const key of stateCopy.BLOCKED_STATES) {
      const timed = key === 'edit_pending' || key === 'rate_limited' || key === 'rate_delayed' || key === 'write_rate_limited';
      const markup = renderToStaticMarkup(React.createElement(SenderStatePanel, {
        state: { key, retryAfterSeconds: timed ? 90 : null, retryAtMs: timed ? 1792750000000 : null, signInAgain: false },
        copy: packs[locale], locale, timeZone: 'UTC', id: 'x', nowMs: 1792749000000, checkedAtMs: 1792749000000
      }));
      const lines = stateCopy.senderStateCopy(packs[locale], key);
      assert.match(markup, new RegExp(`data-testid="discord-sender-state-${key}"`));
      assert.match(markup, new RegExp(`data-state="${key}"`));
      for (const part of ['title', 'body', 'next']) assert.ok(text(markup).includes(text(lines[part])), `${locale} ${key} ${part}`);
      assert.ok(text(markup).includes(text(packs[locale].senderStateNextLabel)));
      assert.match(markup, /data-checked-at/);
      assert.equal(/data-recheck/.test(markup), timed, `${locale} ${key} recheck line`);
      if (locale === 'en') seen.add(text(markup));
    }
  }
  assert.equal(seen.size, stateCopy.BLOCKED_STATES.length);
});

test('a held change names its wait and its time; an alert is announced as one', () => {
  const panel = (state, extra) => renderToStaticMarkup(React.createElement(SenderStatePanel, { state, copy: packs.en, locale: 'en', timeZone: 'UTC', id: 'p', ...extra }));
  const base = { signInAgain: false };
  const pending = (retryAtMs, retryAfterSeconds) => ({ key: 'edit_pending', retryAtMs, retryAfterSeconds, ...base });
  assert.match(panel(pending(1792749090000, 90), { nowMs: 1792749000000 }), /Rafii can check again in about 2 minutes, at \d{1,2}:\d{2}/);
  assert.match(panel(pending(1792749090000, 90), { nowMs: 1792749000000 }), /data-retry-after-seconds="90"/);
  assert.match(panel(pending(null, null)), /in about two minutes/);
  assert.match(panel(pending(1792748000000, 90), { nowMs: 1792749000000 }), /check again now/);
  assert.match(panel({ key: 'rate_limited', retryAtMs: 1792749060000, retryAfterSeconds: 60, ...base }, { nowMs: 1792749000000 }), /Rafii can check again in about 60 seconds, at/);
  assert.match(panel({ key: 'rate_delayed', retryAtMs: 1792749007000, retryAfterSeconds: 7, ...base }, { nowMs: 1792749000000 }), /Rafii can check again in about 7 seconds, at/);
  assert.match(panel({ key: 'write_rate_limited', retryAtMs: 1792749031000, retryAfterSeconds: 31, ...base }, { nowMs: 1792749000000 }), /Rafii can check again in about 31 seconds, at/);
  // Rafii's own window runs up to ten minutes.
  assert.match(panel({ key: 'rate_limited', retryAtMs: 1792749600000, retryAfterSeconds: 600, ...base }, { nowMs: 1792749000000 }), /Rafii can check again in about 10 minutes, at/);
  assert.match(panel(pending(null, null)), /id="p-recheck"/);
  // The two held states say different things.
  assert.notEqual(text(panel(pending(null, null))), text(panel({ key: 'rate_limited', retryAtMs: null, retryAfterSeconds: null, ...base })));
  assert.match(panel({ key: 'failed', retryAtMs: null, retryAfterSeconds: null, ...base }, { role: 'alert' }), /role="alert"/);
  assert.doesNotMatch(panel({ key: 'failed', retryAtMs: null, retryAfterSeconds: null, ...base }), /role="alert"/);
  assert.match(panel({ key: 'stale', retryAtMs: null, retryAfterSeconds: null, ...base }, { actions: React.createElement('button', null, 'Go') }), /<button>Go<\/button>/);
});

test('the held-post sentence of the master switch is shown for webhooks only, and nothing is styled as an error', () => {
  const off = { key: 'sender_names_disabled', retryAtMs: null, retryAfterSeconds: null, signInAgain: false };
  const panel = (kind) => renderToStaticMarkup(React.createElement(SenderStatePanel, { state: off, kind, copy: packs.en, locale: 'en', id: 'p' }));
  assert.match(panel('webhook'), /data-held-note/);
  assert.ok(text(panel('webhook')).includes(text(packs.en.senderStateHeldNote)));
  assert.doesNotMatch(panel('bot'), /data-held-note/);
  assert.doesNotMatch(panel(undefined), /data-held-note/);
  assert.doesNotMatch(panel('bot'), /destructive|role="alert"/);
});

// ---------------------------------------------------------------------------------------------------------------
// Colours
// ---------------------------------------------------------------------------------------------------------------

test('the preview colours meet the contrast the repo asks of text, in both themes', () => {
  assert.equal(Math.round(palette.contrastRatio('#ffffff', '#000000')), 21);
  assert.throws(() => palette.relativeLuminance('red'));
  for (const theme of ['dark', 'light']) {
    for (const pair of palette.PREVIEW_CONTRAST_PAIRS) {
      const colours = palette.DISCORD_PREVIEW_PALETTE[theme];
      const ratio = palette.contrastRatio(colours[pair.foreground], colours[pair.background]);
      assert.ok(ratio >= pair.minimum, `${theme}: ${pair.label} is ${ratio.toFixed(2)}:1, needs ${pair.minimum}:1`);
    }
  }
});

// ---------------------------------------------------------------------------------------------------------------
// CI wiring: the browser cases really run, and a failure fails the job
// ---------------------------------------------------------------------------------------------------------------

const cloudScript = fs.readFileSync(path.join(repo, 'scripts/discord-multimode-validation-cloud.sh'), 'utf8');
const workflow = fs.readFileSync(path.join(repo, '.github/workflows/discord-multimode-qualification.yml'), 'utf8');
const gateFunction = cloudScript.match(/multimode_gate\(\) \{[\s\S]*?\n\}/)[0];
const bash = (script, env = {}) => spawnSync('bash', ['-c', script], { cwd: repo, encoding: 'utf8', env: { ...process.env, ...env } });

test('the cloud script runs the sender-name browser harness from web/ as a gate', () => {
  const line = cloudScript.match(/^multimode_gate sender-name-browser node tests\/discord-sender-name-browser\.cjs$/m);
  assert.ok(line, 'the sender-name browser gate line is missing');
  assert.ok(cloudScript.indexOf('cd web') < cloudScript.indexOf(line[0]), 'the gate must run after cd web');
  assert.ok(fs.existsSync(path.join(root, 'tests/discord-sender-name-browser.cjs')));
  assert.match(cloudScript, /^exit "\$result"$/m);
  assert.match(cloudScript, /set -euo pipefail/);
  // The unit gate that runs this file is in the same script.
  assert.match(cloudScript, /multimode_gate web-unit node --test tests\/\*\.test\.mjs tests\/\*\.test\.cjs/);
  assert.match(cloudScript, /multimode_gate discord-python python -m unittest discover -s tests -p 'test_discord\*\.py'/);
});

test('a failing gate makes the script exit non-zero and every gate still reports', () => {
  const failing = bash(`set -euo pipefail\nresult=0\n${gateFunction}\nmultimode_gate one false\nmultimode_gate two true\nexit "$result"`);
  assert.equal(failing.status, 1);
  assert.match(failing.stdout, /DISCORD_MULTIMODE_GATE \{"name":"one","exitCode":1\}/);
  assert.match(failing.stdout, /DISCORD_MULTIMODE_GATE \{"name":"two","exitCode":0\}/);
  const passing = bash(`set -euo pipefail\nresult=0\n${gateFunction}\nmultimode_gate one true\nexit "$result"`);
  assert.equal(passing.status, 0);
});

test('the real harness failing makes the real gate fail (CI is blanked so it stops at its first assertion)', () => {
  const gate = cloudScript.match(/^multimode_gate sender-name-browser node tests\/discord-sender-name-browser\.cjs$/m)[0];
  const run = bash(`set -euo pipefail\nresult=0\n${gateFunction}\ncd web\n${gate}\nexit "$result"`, { CI: '' });
  assert.equal(run.status, 1, run.stderr.slice(0, 400));
  assert.match(run.stdout, /DISCORD_MULTIMODE_GATE \{"name":"sender-name-browser","exitCode":1\}/);
});

test('the workflow runs that script and lets any failed gate fail the job', () => {
  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /id: multimode[\s\S]*?run: bash scripts\/discord-multimode-validation-cloud\.sh/);
  assert.match(workflow, /MULTIMODE_RESULT: \$\{\{ steps\.multimode\.outcome \}\}/);
  assert.match(workflow, /results = \{name:os\.environ\[name\] for name in \('PYTHON_RESULT','MULTIMODE_RESULT','BUILD_RESULT'\)\}/);
  assert.match(workflow, /raise SystemExit\(0 if same and all\(value == 'success' for value in results\.values\(\)\) else 1\)/);
  assert.ok(workflow.indexOf('playwright install --with-deps chromium') < workflow.indexOf('id: multimode'), 'Chromium must be installed before the browser gates');
  assert.match(workflow, /timeout-minutes: \d+/);
});

test('the sender-name harness exits non-zero on any failure and checks its own case list', () => {
  const harness = fs.readFileSync(path.join(__dirname, 'discord-sender-name-browser.cjs'), 'utf8');
  assert.match(harness, /process\.exitCode = 1/);
  assert.match(harness, /assert\.equal\(process\.env\.CI, 'true'\)/);
  assert.match(harness, /REQUIRED_CASES/);
  assert.match(harness, /assert\.deepEqual\(\[\.\.\.ran\[combo\]\]\.sort\(\), \[\.\.\.REQUIRED_CASES\]\.sort\(\)/);
  assert.match(harness, /assert\.deepEqual\(\[\.\.\.once\]\.sort\(\), \[\.\.\.ONCE_CASES\]\.sort\(\)/);
});
