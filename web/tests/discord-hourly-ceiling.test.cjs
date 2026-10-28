/**
 * The Discord hourly ceiling (owner decision, reply 16, D-4; docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md):
 * a workspace may have at most 300 approved Discord posts scheduled within any one hour, and the approval that would
 * make the 301st is refused with HTTP 409, code `discord_workspace_hourly_ceiling`, no retry field. This file covers the
 * one hard-coded number against the contract text, the copy in three locales, the refusal keyed on the code, the notice
 * at each place a person meets it, and the post card line after the scheduler's queue attempts failed. No network and
 * no browser; the running-app cases (single approve, bulk approve, automation decision, reply, post card, at phone and
 * desktop width) are the `ceiling` group of discord-sender-name-browser.cjs.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { load, root } = require('./discord-sender-name-load.cjs');

const copyModule = load('src/lib/channels/discord-copy.ts');
const ceiling = load('src/lib/channels/discord-hourly-ceiling.ts');
const refusal = load('src/lib/channels/discord-refusal.ts');
const notice = load('src/features/channels/discord-hourly-ceiling-notice.tsx');
const { RunDetail } = load('src/features/automations/run-history.tsx');
const client = load('src/lib/api/client.ts');
const packs = JSON.parse(fs.readFileSync(path.join(root, 'src/lib/channels/discord-copy.json'), 'utf8'));
const contract = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/discord-hourly-ceiling-contract.json'), 'utf8'));
const repo = path.resolve(root, '..');
const LOCALES = ['en', 'zh-Hant', 'zh-Hans'];
const KEYS = Object.keys(packs.en).filter((key) => key.startsWith('hourlyCeiling'));
const text = (markup) => markup.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim();
const apiError = (code, extra = {}) => Object.assign(new client.ApiError(extra.message ?? contract.body.error, extra.status ?? 409, code), extra.body === undefined ? {} : { body: extra.body });
const CJK = /[㐀-鿿]/;

// ---------------------------------------------------------------------------------------------------------------
// The one hard-coded number, pinned against the contract
// ---------------------------------------------------------------------------------------------------------------

const CONTRACT_FILE = 'docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md';
const FIXES_BRANCH = 'origin/claude/discord-rc2-g2a-fixes-20261023';

/** The contract text from the working tree (after the fixes branch is merged), else from the fixes branch's ref, else null. */
function contractText() {
  const file = path.join(repo, CONTRACT_FILE);
  if (fs.existsSync(file)) return { from: 'working tree', text: fs.readFileSync(file, 'utf8') };
  const shown = spawnSync('git', ['show', `${FIXES_BRANCH}:${CONTRACT_FILE}`], { cwd: repo, encoding: 'utf8' });
  if (shown.status === 0 && shown.stdout.includes('discord_workspace_hourly_ceiling')) return { from: FIXES_BRANCH, text: shown.stdout };
  return null;
}

test('the one exported constant is the contract fixture\'s limit, and the window is one hour', () => {
  assert.equal(copyModule.WORKSPACE_HOURLY_CEILING, 300);
  assert.equal(copyModule.WORKSPACE_HOURLY_CEILING, contract.body.limit);
  assert.equal(contract.body.windowSeconds, 3600, 'the copy says "any one hour"; a different window needs different words');
  assert.equal(contract.status, 409);
  assert.equal(ceiling.HOURLY_CEILING_CODE, contract.body.code);
  // No second copy of the number in the app code: it is written in one place and the copy takes `{limit}`.
  const sources = ['src/lib/channels/discord-hourly-ceiling.ts', 'src/lib/channels/discord-refusal.ts', 'src/features/channels/discord-hourly-ceiling-notice.tsx',
    'src/components/jobs/review-approve-button.tsx', 'src/features/queue/approve-many-dialog.tsx', 'src/features/automations/run-decision.tsx',
    'src/features/automations/run-history.tsx', 'src/features/channels/discord-engagement-panel.tsx'];
  for (const file of sources) assert.doesNotMatch(fs.readFileSync(path.join(root, file), 'utf8'), /\b300\b/, `${file} must not write the limit`);
  for (const locale of LOCALES) for (const key of KEYS) assert.doesNotMatch(packs[locale][key], /\b300\b/, `${locale}.${key} must take {limit}`);
});

test('the fixture is the contract text (read from the tree when the fixes branch is merged, else from its ref)', (t) => {
  const found = contractText();
  if (!found) return t.skip(`${CONTRACT_FILE} is neither in this tree nor on ${FIXES_BRANCH}; the fixture above still pins the number`);
  const doc = found.text.replace(/\s+/g, ' ');
  const block = /```json\s*([\s\S]*?)```/.exec(found.text);
  assert.ok(block, 'the contract shows the error body as a json block');
  assert.deepEqual(JSON.parse(block[1]), contract.body, `the contract's body (${found.from}) is the fixture's body`);
  assert.ok(doc.includes('`WORKSPACE_HOURLY_CEILING = 300`'));
  assert.ok(doc.includes('`WORKSPACE_HOURLY_WINDOW_SECONDS = 3600`'));
  assert.ok(doc.includes(`at most **${copyModule.WORKSPACE_HOURLY_CEILING}** approved`), 'the exported constant is the number in the contract');
  // The suggested English copy, word for word.
  assert.ok(doc.includes(`title "${contract.copy.title}"`));
  assert.ok(doc.includes(`body "${contract.copy.body}"`));
  for (const action of contract.copy.actions) assert.ok(doc.includes(`"${action}"`), action);
  // And the line the post card shows after the queue attempts failed.
  assert.ok(doc.includes('"It couldn\'t be queued: This hour is full: ..."'));
  assert.ok(contract.queueFailureReason.startsWith("It couldn't be queued: " + contract.body.error.split(' Approve')[0]));
  assert.ok(doc.includes('no `Retry-After` header and no `retryAfter` field'));
});

// ---------------------------------------------------------------------------------------------------------------
// Copy: three locales
// ---------------------------------------------------------------------------------------------------------------

test('the English copy is the contract\'s suggested copy word for word', () => {
  assert.equal(packs.en.hourlyCeilingTitle, contract.copy.title);
  assert.equal(packs.en.hourlyCeilingBody, contract.copy.body);
  assert.equal(packs.en.hourlyCeilingChooseTime, contract.copy.actions[0]);
  assert.equal(packs.en.hourlyCeilingSeePosts, contract.copy.actions[1]);
});

test('every locale has every hourly-ceiling string, with the same placeholders, and nothing that offers a retry', () => {
  assert.ok(KEYS.length >= 14, `${KEYS.length} keys`);
  for (const locale of LOCALES) {
    assert.deepEqual(Object.keys(packs[locale]).filter((key) => key.startsWith('hourlyCeiling')).sort(), [...KEYS].sort(), locale);
    for (const key of KEYS) {
      const value = packs[locale][key];
      assert.equal(typeof value, 'string', `${locale}.${key}`);
      assert.ok(value.trim().length > 0, `${locale}.${key} is empty`);
      assert.deepEqual(value.match(/\{\w+\}/g) ?? [], packs.en[key].match(/\{\w+\}/g) ?? [], `${locale}.${key} placeholders`);
      if (locale !== 'en') assert.match(value, CJK, `${locale}.${key} is not translated`);
      // Nothing to wait for and nothing to resend: no retry wording, no countdown, no waiting time.
      assert.doesNotMatch(value, /\b(retry|try again|countdown|seconds?|minutes?)\b|重試|再試|重试|再试|倒數|倒数|秒|分鐘|分钟/i, `${locale}.${key} offers a retry or a wait`);
    }
  }
  // The three places the number is written take it as {limit}.
  for (const key of ['hourlyCeilingBody', 'hourlyCeilingQueueFailed']) for (const locale of LOCALES) assert.ok(packs[locale][key].includes('{limit}'), `${locale}.${key}`);
});

test('each locale says, in its own words, what was and was not approved at each place', () => {
  const en = packs.en;
  assert.match(en.hourlyCeilingNothingApproved, /^Nothing was approved\./);
  assert.match(en.hourlyCeilingBulkNone, /^No post was approved, and your selection is unchanged\./);
  assert.match(en.hourlyCeilingDecision, /still ready for review/);
  assert.match(en.hourlyCeilingReply, /^The reply was not approved\./);
  assert.match(en.hourlyCeilingMoved, /earlier time is already cancelled/);
  assert.match(en.hourlyCeilingQueueFailed, /^It couldn’t be queued: that hour is full\./);
  assert.match(en.hourlyCeilingQueueFailed, /approved draft is kept/);
  for (const locale of ['zh-Hant', 'zh-Hans']) {
    const pack = packs[locale];
    assert.match(pack.hourlyCeilingBulkNone, /沒有批准任何貼文|没有批准任何帖子/);
    assert.match(pack.hourlyCeilingMoved, /已取消/);
    assert.match(pack.hourlyCeilingQueueFailed, /草稿已保留/);
  }
  // Only Traditional characters in zh-Hant and only Simplified in zh-Hans for the words that differ.
  assert.doesNotMatch(packs['zh-Hant'].hourlyCeilingBody + packs['zh-Hant'].hourlyCeilingBulkNone, /帖子|个|条|选择|没有/);
  assert.doesNotMatch(packs['zh-Hans'].hourlyCeilingBody + packs['zh-Hans'].hourlyCeilingBulkNone, /貼文|個|則|選擇|沒有/);
});

// ---------------------------------------------------------------------------------------------------------------
// The refusal, keyed on the code
// ---------------------------------------------------------------------------------------------------------------

test('only the code makes a refusal the hourly ceiling', () => {
  assert.equal(ceiling.isHourlyCeiling(apiError(contract.body.code)), true);
  assert.equal(ceiling.isHourlyCeiling({ code: contract.body.code }), true);
  for (const other of [apiError('discord_rate_delayed'), apiError('discord_access_closed'), apiError('workspace_revision_conflict'), apiError('approval_expired'),
    apiError(undefined), apiError(contract.body.code.toUpperCase()), apiError(contract.body.code + '_x'), apiError('hour_full', { message: contract.body.error }),
    new Error(contract.body.error), null, undefined, 'discord_workspace_hourly_ceiling', 409, {}]) {
    assert.equal(ceiling.isHourlyCeiling(other), false, String(other?.code ?? other));
  }
  // The English text is a fallback, never the key: the same words under another code are not the ceiling.
  assert.equal(ceiling.isHourlyCeiling(apiError('something_else', { message: contract.body.error })), false);
});

test('discordRefusal answers the code in each language, with the limit, and leaves every other code alone', () => {
  for (const locale of LOCALES) {
    const copy = packs[locale];
    const shown = refusal.discordRefusal(apiError(contract.body.code), copy);
    assert.equal(shown, copy.hourlyCeilingBody.replace('{limit}', '300'), locale);
    assert.ok(shown.includes('300'));
    if (locale !== 'en') assert.notEqual(shown, contract.body.error, `${locale} is not the English fallback`);
    // The code, not the words: another message under the same code is still answered in the person's language.
    assert.equal(refusal.discordRefusal(apiError(contract.body.code, { message: 'x' }), copy), shown);
    // Unknown codes show the server's message, as before; the other Discord refusals keep their own copy.
    assert.equal(refusal.discordRefusal(apiError('something_else', { message: 'The server says no.' }), copy), 'The server says no.');
    assert.equal(refusal.discordRefusal(apiError('discord_rate_delayed'), copy), copy.rateDelayed);
    assert.equal(refusal.discordRefusal(apiError('discord_access_closed'), copy), copy.accessClosed);
    assert.equal(refusal.discordRefusal(apiError('discord_capacity_reached'), copy), copy.capacityReached);
  }
});

test('the limit in the text is the response\'s own when it is a sound whole number, else the one constant', () => {
  const body = (limit) => ({ ...contract.body, limit });
  assert.equal(ceiling.hourlyCeilingLimit(apiError(contract.body.code, { body: contract.body })), 300);
  assert.equal(ceiling.hourlyCeilingLimit(apiError(contract.body.code, { body: body(250) })), 250, 'the owner may change the ceiling');
  assert.equal(ceiling.hourlyCeilingLimit(apiError(contract.body.code, { body: body(1) })), 1);
  for (const unsound of [0, -5, 1.5, NaN, Infinity, '300', '250', null, undefined, true, [], {}, 1e9, Number.MAX_SAFE_INTEGER + 2]) {
    assert.equal(ceiling.hourlyCeilingLimit(apiError(contract.body.code, { body: body(unsound) })), 300, String(unsound));
  }
  assert.equal(ceiling.hourlyCeilingLimit(apiError(contract.body.code)), 300, 'no body');
  assert.equal(ceiling.hourlyCeilingLimit(apiError(contract.body.code, { body: 'text' })), 300);
  assert.equal(ceiling.hourlyCeilingLimit(null), 300);
  assert.equal(refusal.discordRefusal(apiError(contract.body.code, { body: body(250) }), packs.en).includes('250'), true);
  assert.equal(copyModule.hourlyCeilingBody(packs.en), packs.en.hourlyCeilingBody.replace('{limit}', '300'));
  assert.equal(copyModule.hourlyCeilingBody(packs.en, 12), packs.en.hourlyCeilingBody.replace('{limit}', '12'));
});

test('the client makes one request for a refused approval and keeps the body the text reads its limit from', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method, body: JSON.parse(init.body) });
    return new Response(JSON.stringify(contract.body), { status: contract.status, headers: { 'content-type': 'application/json' } });
  };
  try {
    const api = client.createApi(async () => 'synthetic');
    await assert.rejects(api.act('w1', 7, 'p2_approve', { reviewId: 'r1', digest: 'd1', confirmed: true }), (error) => {
      assert.ok(error instanceof client.ApiError);
      assert.equal(error.status, 409);
      assert.equal(error.code, contract.body.code);
      assert.equal(error.message, contract.body.error);
      assert.equal(error.nextAction, undefined);
      assert.deepEqual(error.body, contract.body);
      assert.equal(ceiling.hourlyCeilingLimit(error), contract.body.limit);
      return true;
    });
    await new Promise((resolve) => setTimeout(resolve, 150));
    assert.equal(calls.length, 1, 'no automatic retry in the client');
    assert.deepEqual(calls[0].body, { expectedRevision: 7, action: 'p2_approve', payload: { reviewId: 'r1', digest: 'd1', confirmed: true } });
  } finally {
    globalThis.fetch = original;
  }
});

// ---------------------------------------------------------------------------------------------------------------
// The notice at each place
// ---------------------------------------------------------------------------------------------------------------

const PLACES = [
  { place: 'single', state: 'hourlyCeilingNothingApproved', moving: true, actions: { chooseTime: { href: '/app/queue?view=drafts&draft=v%201' }, see: { href: '/app/calendar?view=day&date=2031-03-04' } } },
  { place: 'bulk', state: 'hourlyCeilingBulkNone', actions: { see: { href: '/app/calendar?view=day&date=2031-03-04', many: true } } },
  { place: 'decision', state: 'hourlyCeilingDecision', actions: { see: { href: '/app/calendar?view=day&date=2031-03-04' } } },
  { place: 'reply', state: 'hourlyCeilingReply', actions: { chooseTime: { onClick() {} }, see: { href: '/app/calendar?view=day&date=2031-03-04' } } }
];
const render = (props) => renderToStaticMarkup(React.createElement(notice.HourlyCeilingNotice, props));

test('the notice names the full hour, the rule with its number, and what is left undone, at every place and in every language', () => {
  for (const locale of LOCALES) {
    const copy = packs[locale];
    for (const { place, state, moving, actions } of PLACES) {
      const html = render({ copy, place, limit: 300, moving, actions });
      const words = text(html);
      const label = `${locale} ${place}`;
      assert.match(html, /role="alert"/, label);
      assert.match(html, new RegExp(`data-place="${place}"`), label);
      assert.ok(words.includes(copy.hourlyCeilingTitle), label);
      assert.ok(words.includes(copy.hourlyCeilingBody.replace('{limit}', '300')), label);
      assert.ok(words.includes(copy[state]), `${label}: ${state}`);
      assert.equal(words.includes(copy.hourlyCeilingMoved), Boolean(moving), `${label}: the move sentence only where a post can be a move`);
      // The title is a focusable heading the notice moves the keyboard to (the button that was pressed is disabled by then).
      assert.match(html, /<h3 [^>]*tabindex="-1"/, label);
      // The way forward: the actions the place has, nothing else.
      if (actions.chooseTime) assert.ok(words.includes(copy.hourlyCeilingChooseTime), label);
      else assert.ok(!words.includes(copy.hourlyCeilingChooseTime), `${label}: no time to choose here`);
      assert.ok(words.includes(actions.see.many ? copy.hourlyCeilingSeePostsMany : copy.hourlyCeilingSeePosts), label);
      if (actions.chooseTime?.href) assert.ok(html.includes(`href="${actions.chooseTime.href.replace(/&/g, '&amp;')}"`), label);
      assert.ok(html.includes(`href="${actions.see.href.replace(/&/g, '&amp;')}"`), label);
      // Nothing offers a second send, a wait or a countdown.
      assert.doesNotMatch(words, /retry|try again|reload|countdown|再試|重試|再试|重试|重新載入|重新加载/i, label);
      assert.doesNotMatch(html, /aria-live|data-retry|data-countdown|<time|<progress/i, label);
    }
  }
});

test('the places say different things: the bulk one that no post was approved, the decision one that the post stays ready, the reply one that it waits', () => {
  const en = packs.en;
  const words = Object.fromEntries(PLACES.map(({ place, moving, actions }) => [place, text(render({ copy: en, place, limit: 300, moving, actions }))]));
  assert.match(words.bulk, /No post was approved, and your selection is unchanged/);
  assert.match(words.bulk, /See the scheduled posts/);
  assert.match(words.decision, /still ready for review/);
  assert.match(words.reply, /The reply was not approved\. It is still waiting for your approval/);
  assert.match(words.single, /Nothing was approved\. This post is still waiting for your approval/);
  assert.match(words.single, /Moving a post\? The earlier time is already cancelled/);
  for (const place of ['bulk', 'decision', 'reply']) assert.doesNotMatch(words[place], /Moving a post/, place);
  assert.equal(new Set(Object.values(words)).size, 4);
});

test('a limit from the response is written into the notice', () => {
  const html = render({ copy: packs.en, place: 'single', limit: 250, actions: {} });
  assert.ok(text(html).includes('at most 250 approved Discord posts'));
  assert.doesNotMatch(html, /data-hourly-ceiling-actions/, 'no actions, no empty row');
});

test('an unknown code is not the ceiling at any place, so each place keeps its own error path', () => {
  // Every place decides with isHourlyCeiling(error); these are the answers its other path receives.
  for (const other of [apiError('discord_rate_delayed', { status: 429 }), apiError('approval_expired'), apiError('workspace_revision_conflict', { message: 'The workspace changed. Reload.' }),
    apiError('review_changed', { message: 'The review changed.' }), apiError(undefined, { status: 500, message: 'Server error' })]) {
    assert.equal(ceiling.isHourlyCeiling(other), false, String(other.code));
    for (const locale of LOCALES) {
      const shown = refusal.discordRefusal(other, packs[locale]);
      assert.ok(shown === other.message || shown === packs[locale][{ discord_rate_delayed: 'rateDelayed' }[other.code]], `${locale} ${other.code}: ${shown}`);
      assert.ok(!shown.includes(packs[locale].hourlyCeilingBody.slice(0, 12)));
    }
  }
});

test('every place that can meet the refusal handles the code and keeps its own path for others', () => {
  const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
  const approve = read('src/components/jobs/review-approve-button.tsx');
  assert.match(approve, /if \(isHourlyCeiling\(err\)\)[\s\S]{0,260}return;[\s\S]*reportActionError\(err, 'Couldn’t approve this post', onReload\)/, 'single approve: the ceiling first, then the old error path');
  assert.match(approve, /<HourlyCeilingDialog[\s\S]*place='single'[\s\S]*moving/);
  const many = read('src/features/queue/approve-many-dialog.tsx');
  assert.match(many, /if \(isHourlyCeiling\(err\)\)[\s\S]{0,260}return;[\s\S]*reportActionError\(err, 'Couldn’t approve these posts', onReload\)/, 'bulk approve');
  assert.match(many, /place='bulk'/);
  assert.match(many, /disabled=\{count === 0 \|\| full !== null\}/, 'the same selection is not offered again');
  const decision = read('src/features/automations/run-decision.tsx');
  assert.match(decision, /if \(isHourlyCeiling\(error\)\)[\s\S]{0,320}return;[\s\S]*approval_expired/, 'automation decision');
  assert.match(decision, /place='decision'/);
  const reply = read('src/features/channels/discord-engagement-panel.tsx');
  assert.match(reply, /isHourlyCeiling\(cause\)/, 'reply approval');
  assert.match(reply, /place='reply'/);
  const card = read('src/features/automations/run-history.tsx');
  assert.match(card, /queueFailureText\(dc, item\.reason\)/, 'post card');
  for (const file of ['src/components/jobs/review-approve-button.tsx', 'src/features/queue/approve-many-dialog.tsx', 'src/features/automations/run-decision.tsx', 'src/features/channels/discord-engagement-panel.tsx', 'src/features/automations/run-history.tsx']) {
    // No place resends the refused request by itself.
    assert.doesNotMatch(read(file), /setTimeout\([^)]*(approve|send|mutate)\(|retry:\s*true|retryAfter/i, file);
  }
});

// ---------------------------------------------------------------------------------------------------------------
// The post card after the scheduler's queue attempts failed
// ---------------------------------------------------------------------------------------------------------------

test('the queue failure sentence is recognized and answered in each language, with its own limit', () => {
  for (const locale of LOCALES) {
    const copy = packs[locale];
    const shown = ceiling.queueFailureText(copy, contract.queueFailureReason);
    assert.equal(shown, copy.hourlyCeilingQueueFailed.replace('{limit}', '300'), locale);
    assert.ok(!shown.includes('This hour is full'), `${locale}: the English sentence is replaced, not repeated`);
    // The scheduler may store the bare message when no reason was written (lastError).
    assert.equal(ceiling.queueFailureText(copy, contract.body.error), shown);
    assert.ok(ceiling.queueFailureText(copy, contract.queueFailureReason.replace('300', '250')).includes('250'));
    // Anything else is the caller's to show unchanged.
    for (const other of ["It couldn't be queued in time, so it was not published. The draft is kept.", "It couldn't be queued: Discord is not connected. The approved draft is kept.",
      'This hour is busy', 'Your plan doesn\'t include publishing right now, so this post was not published. The draft is kept.', '', null, undefined, 300, {}]) {
      assert.equal(ceiling.queueFailureText(copy, other), null, String(other));
    }
  }
  assert.match(ceiling.queueFailureText(packs.en, contract.queueFailureReason), /^It couldn’t be queued: that hour is full\. A workspace can have at most 300 approved Discord posts in any one hour\. The approved draft is kept\. Approve it again for another hour\.$/);
});

const failedRun = (reason, extra = {}) => ({
  id: 'run-1', taskId: 'task-1', state: 'completed', scheduledFor: 1900000000, lifecycle: 'failed', policy: 'approval',
  items: [{ key: 'Discord|c1|en', platform: 'Discord', channelId: 'c1', account: 'Acme Weekly', language: 'en', variantId: 'draft 1/x', state: 'failed', reason, publishAt: 1900003600, attempts: 3, lastError: null, ...extra }]
});
const withLocale = (locale, work) => {
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', { value: { language: locale, userAgent: 'node', platform: 'node' }, configurable: true });
  try { return work(); } finally { if (saved) Object.defineProperty(globalThis, 'navigator', saved); else delete globalThis.navigator; }
};
const card = (run) => renderToStaticMarkup(React.createElement(RunDetail, { run, timeZone: 'UTC', canApprove: true, busy: false, onDecide() {}, onOpenRun() {} }));

test('the post card says it in the person\'s language and offers the two ways forward', () => {
  for (const locale of LOCALES) {
    const html = withLocale(locale, () => card(failedRun(contract.queueFailureReason)));
    const words = text(html);
    const copy = packs[locale];
    assert.ok(words.includes(copy.hourlyCeilingQueueFailed.replace('{limit}', '300')), locale);
    assert.ok(!words.includes('This hour is full'), locale);
    assert.match(html, /data-hourly-ceiling-queue-failed/, locale);
    // The draft was kept: choose another time opens it in Drafts; the Calendar shows the day (its day needs the browser's zone, filled in the browser).
    assert.ok(html.includes('href="/app/queue?view=drafts&amp;draft=draft%201%2Fx"'), locale);
    assert.ok(words.includes(copy.hourlyCeilingChooseTime) && words.includes(copy.hourlyCeilingSeePosts), locale);
    assert.match(html, /href="\/app\/calendar[^"]*"/, locale);
    // A failed post offers no Approve button (the scheduler is done with it); nothing offers a retry.
    assert.doesNotMatch(html, /aria-label="Approve the/, locale);
    assert.doesNotMatch(words, /retry|try again|再試|重試|再试|重试/i, locale);
  }
});

test('the post card keeps any other reason exactly as the server wrote it, with no ceiling actions', () => {
  for (const reason of ["It couldn't be queued in time, so it was not published. The draft is kept.", "It couldn't be queued: Discord is not connected. The approved draft is kept."]) {
    for (const locale of LOCALES) {
      const html = withLocale(locale, () => card(failedRun(reason)));
      assert.ok(text(html).includes(reason), `${locale}: ${reason}`);
      assert.doesNotMatch(html, /data-hourly-ceiling|hourly-ceiling-queue-failed|view=drafts/, `${locale}: ${reason}`);
      assert.ok(!text(html).includes(packs[locale].hourlyCeilingChooseTime));
    }
  }
  // Without a reason, a failed item shows its last error; the ceiling sentence there is answered too.
  const html = withLocale('zh-Hans', () => card(failedRun(null, { lastError: contract.body.error })));
  assert.ok(text(html).includes(packs['zh-Hans'].hourlyCeilingQueueFailed.replace('{limit}', '300')));
});

// ---------------------------------------------------------------------------------------------------------------
// Where the links go
// ---------------------------------------------------------------------------------------------------------------

test('the Calendar link is the day in the zone the Calendar uses, and the draft link opens the draft', () => {
  const at = Date.UTC(2031, 2, 4, 23, 30);
  assert.equal(ceiling.calendarDayHref(at, 'UTC'), '/app/calendar?view=day&date=2031-03-04');
  assert.equal(ceiling.calendarDayHref(at, 'Asia/Hong_Kong'), '/app/calendar?view=day&date=2031-03-05');
  assert.equal(ceiling.calendarDayHref(at, 'America/Los_Angeles'), '/app/calendar?view=day&date=2031-03-04');
  for (const unusable of [[NaN, 'UTC'], [null, 'UTC'], [undefined, 'UTC'], [at, null], [at, undefined], [at, ''], [at, 'Not/AZone']]) {
    assert.equal(ceiling.calendarDayHref(...unusable), '/app/calendar', String(unusable));
  }
  assert.equal(ceiling.draftHref('draft 1/x'), '/app/queue?view=drafts&draft=draft%201%2Fx');
  assert.equal(ceiling.draftHref(''), null);
  assert.equal(ceiling.draftHref(null), null);
  assert.equal(ceiling.draftHref(undefined), null);
});

// ---------------------------------------------------------------------------------------------------------------
// The browser cases are required
// ---------------------------------------------------------------------------------------------------------------

test('the browser harness requires its ceiling cases, so a skipped one cannot pass silently', () => {
  const harness = fs.readFileSync(path.join(__dirname, 'discord-sender-name-browser.cjs'), 'utf8');
  const required = /const REQUIRED_CASES = \[([\s\S]*?)\];/.exec(harness)[1];
  const names = [...required.matchAll(/'(ceiling-[a-z-]+)'/g)].map((match) => match[1]);
  for (const name of ['ceiling-single-dialog', 'ceiling-single-uses-server-limit', 'ceiling-single-unknown-code', 'ceiling-bulk-keeps-selection', 'ceiling-bulk-remove-then-approve',
    'ceiling-bulk-unknown-code', 'ceiling-reply-dialog', 'ceiling-reply-unknown-code', 'ceiling-decision-dialog', 'ceiling-decision-unknown-code', 'ceiling-run-card-text', 'ceiling-no-page-errors']) {
    assert.ok(names.includes(name), `${name} is in REQUIRED_CASES`);
    assert.ok(harness.includes(`pass('${name}')`), `${name} is recorded when it runs`);
  }
  assert.ok(harness.includes('discord-hourly-ceiling-contract.json'), 'the synthetic server answers with the contract\'s body');
  assert.match(/const ONCE_CASES = \[([^\]]*)\]/.exec(harness)[1], /'axe-ceiling'/, 'the new surfaces are checked with axe once per run');
});
