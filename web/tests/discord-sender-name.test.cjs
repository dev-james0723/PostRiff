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
// Validation rules
// ---------------------------------------------------------------------------------------------------------------

test('the editor gives the same verdict as the server validator for every shared case', () => {
  assert.deepEqual(verdicts.limits, logic.SENDER_LIMIT);
  assert.ok(verdicts.cases.length >= 50);
  for (const shared of verdicts.cases) {
    const check = logic.checkSenderName(nameOf(shared), shared.kind);
    const label = `${shared.kind}: ${shared.note}`;
    assert.equal(check.issues.length === 0, shared.accepted, label);
    if (!shared.accepted) assert.deepEqual([...check.issues].sort(), [...shared.issues].sort(), label);
  }
});

test('the shared fixture covers every rule the server has', () => {
  const rules = new Set(verdicts.cases.flatMap((shared) => shared.issues));
  assert.deepEqual([...rules].sort(), [...logic.SENDER_NAME_ISSUES].sort());
  const bots = verdicts.cases.filter((shared) => shared.kind === 'bot');
  const hooks = verdicts.cases.filter((shared) => shared.kind === 'webhook');
  assert.ok(bots.some((shared) => shared.accepted) && bots.some((shared) => !shared.accepted));
  assert.ok(hooks.some((shared) => shared.accepted) && hooks.some((shared) => !shared.accepted));
});

test('length is counted in Unicode code points, as the backend counts it', () => {
  assert.equal(logic.codePointLength('abc'), 3);
  assert.equal(logic.codePointLength('\u{1F600}'), 1);
  assert.equal('\u{1F600}'.length, 2);
  assert.equal(logic.codePointLength('é'), 2);
  assert.equal(logic.codePointLength('D Festival 公告'), 13);
  const over = logic.checkSenderName('x'.repeat(85), 'webhook');
  assert.deepEqual({ length: over.length, limit: over.limit, over: over.over }, { length: 85, limit: 80, over: 5 });
  assert.equal(logic.checkSenderName('x'.repeat(32), 'bot').over, 0);
  assert.equal(logic.checkSenderName('x'.repeat(33), 'bot').over, 1);
  // The profile's own limit wins when the server sends one.
  assert.equal(logic.checkSenderName('x'.repeat(10), 'bot', 8).over, 2);
});

test('reserved words apply to webhook names only, and fold case the way the server does', () => {
  for (const word of ['discord', 'Discord', 'DISCORD', 'xClydex', 'diſcord']) {
    assert.ok(logic.checkSenderName(word, 'webhook').issues.includes('reserved_word'), word);
    assert.ok(!logic.checkSenderName(word, 'bot').issues.includes('reserved_word'), word);
  }
  for (const fine of ['d i s c o r d', 'dıscord', 'DİSCORD', 'ｄｉｓｃｏｒｄ']) {
    assert.ok(!logic.checkSenderName(fine, 'webhook').issues.includes('reserved_word'), fine);
  }
});

test('every broken rule is listed, not only the first', () => {
  const issues = logic.checkSenderName(` ${'​'}${'x'.repeat(90)}Discord `, 'webhook').issues;
  for (const expected of ['surrounding_space', 'too_long', 'control_character', 'reserved_word']) assert.ok(issues.includes(expected), expected);
});

// ---------------------------------------------------------------------------------------------------------------
// Availability states
// ---------------------------------------------------------------------------------------------------------------

test('a refused request maps to the state the backend named, never to a guessed cause', () => {
  const state = (error) => logic.classifySenderRefusal(error);
  for (const reason of logic.SERVER_REASONS) {
    assert.equal(state({ status: 403, code: 'discord_sender_name_unavailable', reason }).key, reason, reason);
    assert.equal(state({ status: 409, reason }).key, reason, reason);
  }
  assert.deepEqual(state({ status: 409, code: 'discord_sender_edit_pending', retryAt: 1792750000 }), { key: 'edit_pending', retryAt: 1792750000, signInAgain: false });
  assert.deepEqual(state({ status: 409, code: 'discord_sender_edit_pending' }), { key: 'edit_pending', retryAt: null, signInAgain: false });
  assert.equal(state({ status: 409, code: 'discord_sender_name_stale' }).key, 'stale');
  assert.deepEqual(state({ status: 403, code: 'step_up_required' }), { key: 'step_up_required', retryAt: null, signInAgain: true });
  assert.deepEqual(state({ status: 403, code: 'security_step_up_required' }), { key: 'step_up_required', retryAt: null, signInAgain: false });
  assert.equal(state({ status: 403, message: 'Please sign in again to continue.' }).signInAgain, true);
  assert.equal(state({ status: 401 }).key, 'step_up_required');
  // The current backend: one code for everything. 403 is permission; the rest cannot be told apart.
  assert.equal(state({ status: 403, code: 'discord_sender_name_required' }).key, 'permission_unclear');
  assert.equal(state({ status: 409, code: 'discord_sender_name_required' }).key, 'failed');
  assert.equal(state({ status: 400, code: 'discord_sender_name_required' }).key, 'failed');
  assert.equal(state({ status: 404 }).key, 'reconnect_required');
  assert.equal(state({ status: 500 }).key, 'failed');
  assert.equal(state({ status: 403, reason: 'something_new' }).key, 'permission_unclear');
  assert.equal(state({ status: 503, reason: 'something_new' }).key, 'failed');
  assert.equal(state({}).key, 'failed');
});

test('a readable profile says whether it can be edited, and why not', () => {
  const state = (profile) => logic.classifySenderProfile(profile);
  assert.equal(state({}).key, 'ready');
  assert.equal(state({ availability: null }).key, 'ready');
  assert.equal(state({ availability: { editable: true } }).key, 'ready');
  for (const reason of logic.SERVER_REASONS) assert.equal(state({ availability: { editable: false, reason } }).key, reason, reason);
  assert.equal(state({ availability: { editable: false, reason: 'edit_pending', retryAt: 1792750000 } }).retryAt, 1792750000);
  assert.equal(state({ availability: { editable: false, reason: 'bot_lacks_change_nickname', retryAt: 5 } }).retryAt, null);
  assert.equal(state({ availability: { editable: false } }).key, 'failed');
  assert.equal(state({ availability: { editable: false, reason: 'something_new' } }).key, 'failed');
});

test('platform switches explain themselves before any request', () => {
  const mode = logic.classifySenderModes;
  assert.equal(mode(undefined, 'bot'), null);
  assert.equal(mode({}, 'bot'), null);
  assert.equal(mode({ bot: { enabled: true } }, 'bot'), null);
  assert.equal(mode({ bot: { enabled: false } }, 'bot').key, 'bot_nickname_disabled');
  assert.equal(mode({ bot: { enabled: false, reason: 'bot_nickname_disabled' } }, 'bot').key, 'bot_nickname_disabled');
  assert.equal(mode({ bot: { enabled: false, reason: 'feature_disabled' } }, 'bot').key, 'feature_disabled');
  assert.equal(mode({ webhook: { enabled: false } }, 'webhook').key, 'feature_disabled');
  // The bot switch does not switch webhook names off (the owner's rule: webhook names come first).
  assert.equal(mode({ bot: { enabled: false } }, 'webhook'), null);
});

test('only the states that can change offer a check, and a check is a read', () => {
  const offered = logic.SENDER_STATES.filter((key) => logic.canCheckAgain(key));
  assert.deepEqual(offered.sort(), ['edit_pending', 'bot_lacks_change_nickname', 'failed', 'member_lacks_manage_nicknames', 'not_authorizing_member', 'permission_unclear', 'reconnect_required', 'stale'].sort());
  assert.equal(logic.canCheckAgain('ready'), false);
});

test('the thirteen states are exactly the ones the copy explains', () => {
  assert.equal(logic.SENDER_STATES.length, 13);
  assert.deepEqual(stateCopy.BLOCKED_STATES.sort(), logic.SENDER_STATES.filter((key) => key !== 'ready').sort());
});

test('retry times are formatted for the reader and never invented', () => {
  assert.equal(logic.formatRetryTime(null, 'en'), null);
  assert.equal(logic.formatRetryTime(Number.NaN, 'en'), null);
  assert.match(logic.formatRetryTime(1792749000, 'en', 'UTC'), /\d{1,2}:\d{2}/);
  const en = packs.en;
  assert.equal(stateCopy.recheckLine(en, null, 'en'), en.senderRecheckSoon);
  assert.equal(stateCopy.recheckLine(en, 1792749000, 'en', 'UTC', 1792749001 * 1000), en.senderRecheckNow);
  assert.match(stateCopy.recheckLine(en, 1792749000, 'en', 'UTC', 1792748000 * 1000), /^Rafii can check again at \d{1,2}:\d{2}/);
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
  // Each of the eight named situations says something different.
  const titles = new Set(stateCopy.BLOCKED_STATES.map((state) => stateCopy.senderStateCopy(packs.en, state).title));
  assert.equal(titles.size, stateCopy.BLOCKED_STATES.length);
});

test('the messages never name another workspace and say what the person can do', () => {
  for (const locale of LOCALES) {
    const elsewhere = stateCopy.senderStateCopy(packs[locale], 'nickname_managed_elsewhere');
    assert.doesNotMatch(`${elsewhere.title}${elsewhere.body}${elsewhere.next}`, /workspace\s+(id|named)|[0-9a-f]{8}-[0-9a-f]{4}/i);
  }
  const english = (state) => stateCopy.senderStateCopy(packs.en, state);
  assert.match(english('feature_disabled').next, /Nothing to do/);
  assert.match(english('bot_nickname_disabled').next, /incoming webhook/);
  assert.match(english('member_lacks_manage_nicknames').body, /Manage Nicknames/);
  assert.match(english('bot_lacks_change_nickname').body, /Change Nickname/);
  assert.match(english('edit_pending').next, /never sends the change a second time/);
  assert.match(english('stale').body, /another member|another Rafii workspace/);
  assert.match(english('step_up_required').next, /Sign out and sign in again/);
});

test('validation messages fill their numbers and name the rule', () => {
  const numbers = { length: 85, limit: 80, over: 5 };
  assert.equal(stateCopy.senderIssueMessage(packs.en, 'too_long', numbers), 'Too long: 85 of 80 characters. Remove 5.');
  for (const locale of LOCALES) {
    for (const issue of logic.SENDER_NAME_ISSUES) {
      const message = stateCopy.senderIssueMessage(packs[locale], issue, numbers);
      assert.ok(message.trim() && !/\{[a-z]+\}/.test(message), `${locale}.${issue}`);
    }
    assert.match(stateCopy.senderIssueMessage(packs[locale], 'reserved_word', numbers), /Discord/);
  }
  assert.equal(stateCopy.fillCount(packs.en.senderCount, { count: 7, limit: 80 }), '7 / 80 characters');
  assert.match(stateCopy.fillCount(packs.en.senderIssueSummary, { limit: 32 }), /^Choose a name of 1–32 characters without surrounding spaces, control characters or reserved webhook names\.$/);
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
  assert.match(en, /people who never use Rafii/);
  assert.match(en, /other Rafii workspaces/);
  assert.match(en, /cannot freeze it per post/);
  assert.match(en, /server administrator can change it at any time/);
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
      const markup = renderToStaticMarkup(React.createElement(SenderStatePanel, {
        state: { key, retryAt: key === 'edit_pending' ? 1792750000 : null, signInAgain: false },
        copy: packs[locale], locale, timeZone: 'UTC', id: 'x', nowMs: 1792749000 * 1000, checkedAtMs: 1792749000 * 1000
      }));
      const lines = stateCopy.senderStateCopy(packs[locale], key);
      assert.match(markup, new RegExp(`data-testid="discord-sender-state-${key}"`));
      assert.match(markup, new RegExp(`data-state="${key}"`));
      for (const part of ['title', 'body', 'next']) assert.ok(text(markup).includes(text(lines[part])), `${locale} ${key} ${part}`);
      assert.ok(text(markup).includes(text(packs[locale].senderStateNextLabel)));
      assert.match(markup, /data-checked-at/);
      assert.equal(/data-recheck/.test(markup), key === 'edit_pending', `${locale} ${key} recheck line`);
      if (locale === 'en') seen.add(text(markup));
    }
  }
  assert.equal(seen.size, stateCopy.BLOCKED_STATES.length);
});

test('a pending change says when it can be checked again; an alert is announced as one', () => {
  const panel = (state, extra) => renderToStaticMarkup(React.createElement(SenderStatePanel, { state, copy: packs.en, locale: 'en', timeZone: 'UTC', id: 'p', ...extra }));
  assert.match(panel({ key: 'edit_pending', retryAt: 1792750000, signInAgain: false }, { nowMs: 1792749000 * 1000 }), /Rafii can check again at \d{1,2}:\d{2}/);
  assert.match(panel({ key: 'edit_pending', retryAt: null, signInAgain: false }), /in about two minutes/);
  assert.match(panel({ key: 'edit_pending', retryAt: 1792748000, signInAgain: false }, { nowMs: 1792749000 * 1000 }), /check again now/);
  assert.match(panel({ key: 'failed', retryAt: null, signInAgain: false }, { role: 'alert' }), /role="alert"/);
  assert.doesNotMatch(panel({ key: 'failed', retryAt: null, signInAgain: false }), /role="alert"/);
  assert.match(panel({ key: 'stale', retryAt: null, signInAgain: false }, { actions: React.createElement('button', null, 'Go') }), /<button>Go<\/button>/);
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
  assert.match(harness, /assert\.deepEqual\([^)]*REQUIRED_CASES/);
});
