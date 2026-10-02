/**
 * Rafii's `/` commands (CONTRACTS.md, Contract 7): the registry, `parseSlash`, the menu's open/close and filtering rules,
 * what a pick does to the text, and the client commands' page, guide and style matching through the panel actions.
 *
 *   node --test web/tests/rafii-commands.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const SRC = path.join(WEB, 'src');
const cache = new Map();

function resolve(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`]) if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  throw new Error(`cannot resolve ${base}`);
}

// Load app modules the way the bundler would: `@/` is src/, JSON is data, packages come from web/node_modules. One
// instance per file, so the panel-action registry the tests fill is the one the commands read.
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} };
  cache.set(file, mod);
  if (file.endsWith('.json')) {
    mod.exports = JSON.parse(fs.readFileSync(file, 'utf8'));
    return mod.exports;
  }
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } });
  const localRequire = (name) => {
    if (name.startsWith('@/')) return load(resolve(path.join(SRC, name.slice(2))));
    if (name.startsWith('.')) return load(resolve(path.join(path.dirname(file), name)));
    return require(require.resolve(name, { paths: [WEB] }));
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}

const C = load(path.join(SRC, 'lib/agent-runtime/commands.ts'));
const M = load(path.join(SRC, 'features/rafii-commands/menu-logic.ts'));
const { registerPanelActions } = load(path.join(SRC, 'lib/agent-runtime/panel-actions.ts'));
const byName = (name) => C.COMMANDS.find((command) => command.name === name);
const names = (list) => list.map((command) => command.name);

/** Register fake panel handlers for one test; every call is recorded. */
function panel(t, overrides = {}) {
  const calls = [];
  const handlers = {
    navigate: (href) => calls.push(['navigate', href]),
    startGuide: async (id) => (calls.push(['startGuide', id]), true),
    stopGuide: () => calls.push(['stopGuide']),
    setStyle: async (patch) => calls.push(['setStyle', patch]),
    openStyle: () => calls.push(['openStyle']),
    startVoice: () => calls.push(['startVoice']),
    newConversation: () => calls.push(['newConversation']),
    ...overrides
  };
  const off = registerPanelActions(Object.fromEntries(Object.entries(handlers).filter(([, fn]) => fn)));
  t.after(off);
  return calls;
}

// ---- Registry ------------------------------------------------------------------------------------------------------

const CONTRACT = ['write', 'rewrite', 'translate', 'hashtags', 'caption', 'repurpose', 'ideas', 'search', 'weather', 'stats', 'review', 'image', 'schedule', 'automation', 'skills', 'guide', 'open', 'style', 'voice', 'new', 'help'];
const CLIENT = ['guide', 'open', 'style', 'voice', 'new', 'help'];

test('the registry has exactly the contract commands, each complete and unique', () => {
  assert.deepEqual(names(C.COMMANDS).toSorted(), CONTRACT.toSorted());
  const groups = C.COMMAND_GROUPS.map((group) => group.id);
  assert.deepEqual(C.COMMAND_GROUPS.map((group) => group.label), ['Write', 'Look up', 'Images', 'Plan', 'Rafii']);
  for (const command of C.COMMANDS) {
    assert.match(command.name, /^[a-z]+$/, command.name);
    assert.ok(Array.isArray(command.aliases) && command.aliases.length > 0, `${command.name} aliases`);
    for (const alias of command.aliases) assert.ok(alias && alias === alias.toLowerCase().trim() && !/\s/.test(alias), `${command.name}: "${alias}"`);
    assert.ok(groups.includes(command.group), `${command.name} group`);
    assert.equal(typeof command.argsHint, 'string', `${command.name} argsHint`);
    assert.ok(['none', 'optional', 'required'].includes(command.takes), `${command.name} takes`);
    assert.equal(command.takes === 'none', command.argsHint === '', `${command.name}: a hint exactly when it takes words`);
    // One sentence: a capital, one full stop at the end and none inside.
    assert.match(command.description, /^[A-Z][^.!?]*[^.!?\s]\.$/, `${command.name} description`);
    assert.ok(['client', 'agent'].includes(command.kind), `${command.name} kind`);
    assert.equal(typeof command.execute === 'function', command.kind === 'client', `${command.name}: execute exactly for client commands`);
  }
  assert.deepEqual(names(C.COMMANDS.filter((command) => command.kind === 'client')).toSorted(), CLIENT.toSorted());
  assert.equal(new Set(names(C.COMMANDS)).size, C.COMMANDS.length, 'unique names');
});

test('aliases never collide: no word finds two commands', () => {
  const owner = new Map();
  for (const command of C.COMMANDS) {
    for (const key of [command.name, ...command.aliases].map(C.commandKey)) {
      assert.ok(!owner.has(key) || owner.get(key) === command.name, `"${key}" belongs to ${owner.get(key)} and ${command.name}`);
      owner.set(key, command.name);
    }
  }
  // Within one command a word appears once.
  for (const command of C.COMMANDS) assert.equal(new Set(command.aliases).size, command.aliases.length, command.name);
});

test('the Chinese words people type find their commands', () => {
  const expected = {
    write: ['寫', '寫post', '出post'], rewrite: ['改寫', '改'], translate: ['翻譯'], hashtags: ['標籤', 'hashtag'], caption: ['文案'], repurpose: ['轉平台'],
    ideas: ['靈感', '諗主意'], search: ['搜尋', '上網', '搜'], weather: ['天氣'], stats: ['數據', '表現'], review: ['待辦', '要處理'], image: ['整圖', '圖片', '生成圖片'],
    schedule: ['排程', '預約'], automation: ['自動化', '自動'], skills: ['技能'], guide: ['教我', '教學', '點樣'], open: ['打開', '開', '去'], style: ['語氣', '風格'],
    voice: ['語音', '講嘢'], new: ['新對話'], help: ['幫助', '指令']
  };
  for (const [name, aliases] of Object.entries(expected)) for (const alias of aliases) assert.ok(byName(name).aliases.includes(alias), `${name} ← ${alias}`);
});

test('the extra page and guide words only name pages and guides the manifests have', () => {
  const pages = new Set(C.OPENABLE_PAGES.map((page) => page.id));
  for (const id of Object.keys(C.PAGE_WORDS)) assert.ok(pages.has(id), `PAGE_WORDS.${id}`);
  const guides = new Set(C.GUIDES.map((guide) => guide.id));
  for (const id of Object.keys(C.GUIDE_WORDS)) assert.ok(guides.has(id), `GUIDE_WORDS.${id}`);
  assert.ok(C.GUIDES.length >= 3, 'the no-match answer names three guides');
});

test('descriptions say what costs, what waits for approval, and where web search is turned on', () => {
  assert.match(byName('image').description, /shows what it uses on your plan/);   // cost wording follows the billing mode (R-COM-04)
  assert.match(byName('schedule').description, /approve/);
  assert.match(byName('schedule').description, /nothing is published/);
  assert.match(byName('search').description, /owner can turn it on under Memory/);
  assert.match(byName('ideas').description, /web search/);
});

// ---- parseSlash ----------------------------------------------------------------------------------------------------

test('parseSlash reads the command and trimmed arguments at the start of a message', () => {
  const cases = [
    ['/write launch day at the studio', 'write', 'launch day at the studio'],
    ['/WRITE Hi', 'write', 'Hi'],
    ['  /search   what changed this week \n', 'search', 'what changed this week'],
    ['／translate French', 'translate', 'French'],
    ['／ＷＥＡＴＨＥＲ Tokyo', 'weather', 'Tokyo'],
    ['/寫 新專輯發佈', 'write', '新專輯發佈'],
    ['/天氣 香港', 'weather', '香港'],
    ['／翻譯 英文', 'translate', '英文'],
    ['/教我 connect instagram', 'guide', 'connect instagram'],
    ['/style concise', 'style', 'concise'],
    ['/draft a post', 'write', 'a post'],
    ['/?', 'help', ''],
    ['/new', 'new', ''],
    ['/write line one\nline two', 'write', 'line one\nline two']
  ];
  for (const [text, name, args] of cases) {
    const parsed = C.parseSlash(text);
    assert.ok(parsed, text);
    assert.equal(parsed.command.name, name, text);
    assert.equal(parsed.args, args, text);
  }
});

test('Chinese typed without a space still splits: /天氣香港 is /weather 香港', () => {
  for (const [text, name, args] of [['/天氣香港', 'weather', '香港'], ['/weather香港', 'weather', '香港'], ['/寫新專輯', 'write', '新專輯'], ['/改寫短啲', 'rewrite', '短啲'], ['/點樣連接IG', 'guide', '連接IG'], ['/打開頻道', 'open', '頻道']]) {
    const parsed = C.parseSlash(text);
    assert.equal(parsed?.command.name, name, text);
    assert.equal(parsed?.args, args, text);
  }
});

test('anything else stays plain text', () => {
  for (const text of ['hello', '', '/', '/ write', '/foo bar', '//write', 'hello /write', '/writehello', '/app/queue is broken', 'and/or', '/newyork']) {
    assert.equal(C.parseSlash(text), null, JSON.stringify(text));
  }
});

test('the payload names the command and caps its words at 1,000 characters', () => {
  assert.deepEqual(C.commandPayload(C.parseSlash('/search who won')), { name: 'search', args: 'who won' });
  const long = C.commandPayload({ command: byName('write'), args: '寫'.repeat(1200) });
  assert.equal(Array.from(long.args).length, 1000);
  const emoji = C.commandPayload({ command: byName('write'), args: '🎹'.repeat(1001) });
  assert.equal(Array.from(emoji.args).length, 1000, 'never splits a character');
});

// ---- The menu: when it opens ---------------------------------------------------------------------------------------

test('the menu opens on a slash at the start or after whitespace, until a space is typed', () => {
  const at = (value, caret = value.length, options) => M.slashMenuState(value, caret, options);
  assert.equal(at('/').open, true);
  assert.equal(at('/').query, '');
  assert.equal(at('/').commands.length, C.COMMANDS.length, 'a bare slash lists every command');
  assert.equal(at('／').open, true, 'full-width slash');
  assert.deepEqual(at('hello /wr').range, { start: 6, end: 9 });
  assert.equal(at('hello /wr').query, 'wr');
  assert.equal(at('line one\n/tr').open, true, 'after a new line');
  assert.equal(at('hello/wr').open, false, 'not inside a word');
  assert.equal(at('/write ').open, false, 'a space ends the command word');
  assert.equal(at('/write launch').open, false);
  assert.equal(at('/wr', 1).open, false, 'caret inside the word');
  assert.equal(at('/wr more', 3).open, true, 'caret at the end of the word, text after it');
  assert.equal(at('/app/queue').open, false, 'paths are not commands');
  assert.equal(at('/zzz').open, false, 'nothing matches, nothing shown');
  assert.equal(at('').open, false);
});

test('the menu stays closed during IME composition and after Esc on the same word', () => {
  assert.equal(M.slashMenuState('/tian', 5, { isComposing: true }).open, false);
  assert.equal(M.slashMenuState('/天', 2, { isComposing: false }).open, true);
  const dismissed = { start: 0, query: 'wr' };
  assert.equal(M.slashMenuState('/wr', 3, { dismissed }).open, false);
  assert.equal(M.slashMenuState('/wri', 4, { dismissed }).open, false, 'typing on keeps it closed');
  assert.equal(M.slashMenuState('/w', 2, { dismissed }).open, true, 'erasing reopens it');
  assert.equal(M.slashMenuState('x /wr', 5, { dismissed }).open, true, 'another slash reopens it');
  assert.equal(M.stillDismissed(M.slashToken('/wri', 4), dismissed), true);
  assert.equal(M.stillDismissed(null, dismissed), false);
});

test('IME key presses are recognised from the event or React’s native event', () => {
  assert.equal(M.isImeEvent({ isComposing: true, keyCode: 13 }), true);
  assert.equal(M.isImeEvent({ keyCode: 229 }), true, 'Safari: the Enter that commits a composition');
  assert.equal(M.isImeEvent({ nativeEvent: { isComposing: true } }), true);
  assert.equal(M.isImeEvent({ nativeEvent: { keyCode: 229 } }), true);
  assert.equal(M.isImeEvent({ key: 'Enter', keyCode: 13, isComposing: false }), false);
});

// ---- The menu: what it lists ---------------------------------------------------------------------------------------

test('filtering puts exact names first, then names it starts, then names containing it', () => {
  assert.equal(names(M.filterCommands('new'))[0], 'new');
  assert.equal(names(M.filterCommands('open'))[0], 'open');
  // One English letter only finds names and aliases starting with it.
  assert.deepEqual(names(M.filterCommands('s')), ['search', 'stats', 'schedule', 'skills', 'style']);
  // From two letters on, containing counts too: after the group's better matches, and a group with only those goes last.
  assert.deepEqual(names(M.filterCommands('st')), ['stats', 'weather', 'style', 'write', 'repurpose', 'ideas'], 'forecast, 寫post, crosspost and brainstorm contain "st"');
  // "re" starts rewrite and repurpose, and aliases of search (research), review, automation (recurring) and new
  // (reset). Weather only contains it (forecast), so it follows the Look up group's better matches; image only contains
  // it (picture) and its group has nothing better, so Images comes last. Groups never split.
  const re = names(M.filterCommands('re'));
  assert.deepEqual(re, ['rewrite', 'repurpose', 'search', 'review', 'weather', 'automation', 'new', 'image']);
  assert.equal(names(M.filterCommands('tag'))[0], 'hashtags', 'an alias prefix counts');
  assert.deepEqual(names(M.filterCommands('zzz')), []);
});

test('Chinese aliases match by containment, exact aliases first', () => {
  assert.deepEqual(names(M.filterCommands('寫')), ['write', 'rewrite'], '寫 is write; 改寫 contains it');
  assert.equal(names(M.filterCommands('圖'))[0], 'image');
  assert.equal(names(M.filterCommands('天'))[0], 'weather');
  assert.equal(names(M.filterCommands('動'))[0], 'automation', '自動 contains 動');
  assert.equal(names(M.filterCommands('教'))[0], 'guide');
  assert.equal(names(M.filterCommands('ｗｒ'))[0], 'write', 'full-width letters');
});

test('rows are grouped under Write, Look up, Images, Plan and Rafii', () => {
  const all = M.groupCommands(M.filterCommands(''));
  assert.deepEqual(all.map((group) => group.label), ['Write', 'Look up', 'Images', 'Plan', 'Rafii']);
  assert.deepEqual(all.flatMap((group) => names(group.commands)), names(M.filterCommands('')));
  // A group with a better match moves up; groups never split.
  const st = M.groupCommands(M.filterCommands('st'));
  assert.equal(new Set(st.map((group) => group.id)).size, st.length);
  assert.deepEqual(st.map((group) => group.label), ['Look up', 'Rafii', 'Write'], 'Write only contains "st"');
});

test('the menu renders a grouped listbox: /name, the hint and the description on each option', () => {
  const React = require(require.resolve('react', { paths: [WEB] }));
  const { renderToStaticMarkup } = require(require.resolve('react-dom/server', { paths: [WEB] }));
  const { SlashCommandMenu, useSlashMenu, applyPick } = load(path.join(SRC, 'features/rafii-commands/command-menu.tsx'));
  assert.equal(typeof useSlashMenu, 'function');
  assert.equal(applyPick, M.applyPick, 'the pure helpers are re-exported for composers');
  const render = (value, caret = value.length, extra = {}) => renderToStaticMarkup(React.createElement(SlashCommandMenu, { value, caret, anchorRef: { current: null }, onPick() {}, onDismiss() {}, ...extra }));
  const all = render('/');
  assert.match(all, /role="listbox"[^>]*aria-label="Commands"/);
  assert.equal(all.match(/role="option"/g).length, C.COMMANDS.length);
  assert.equal(all.match(/role="group"/g).length, 5);
  assert.equal(all.match(/aria-selected="true"/g).length, 1, 'one active option');
  for (const label of ['Write', 'Look up', 'Images', 'Plan', 'Rafii']) assert.ok(all.includes(`>${label}</p>`), label);
  assert.ok(all.includes('>/write</span>') && all.includes('>your idea</span>') && all.includes('>Draft a post for the accounts you chose.</span>'));
  assert.ok(all.includes('pointer-coarse:min-h-11'), 'rows are 44 px on touch');
  const image = render('/整圖');
  assert.equal(image.match(/role="option"/g).length, 1);
  assert.ok(image.includes('the composer shows what it uses on your plan'), 'no legacy unit promised to every plan (R-COM-04)');
  assert.equal(render('hello'), '', 'closed: nothing rendered');
  assert.equal(render('/write '), '');
  assert.equal(render('/wr', 3, { isComposing: true }), '', 'closed during IME composition');
});

// ---- Picking a command ---------------------------------------------------------------------------------------------

test('a pick runs client commands that need no words and inserts everything else', () => {
  const pick = (value, name, start = value.lastIndexOf('/')) => M.applyPick(value, { start, end: value.length }, byName(name));
  assert.deepEqual(pick('/wr', 'write'), { action: 'insert', value: '/write ', caret: 7, args: '' });
  assert.deepEqual(pick('/sea', 'search'), { action: 'insert', value: '/search ', caret: 8, args: '' });
  assert.deepEqual(pick('/op', 'open'), { action: 'insert', value: '/open ', caret: 6, args: '' }, 'open needs a page');
  assert.deepEqual(pick('/gu', 'guide'), { action: 'insert', value: '/guide ', caret: 7, args: '' });
  assert.deepEqual(pick('/vo', 'voice'), { action: 'run', value: '', caret: 0, args: '' });
  assert.deepEqual(pick('/ne', 'new'), { action: 'run', value: '', caret: 0, args: '' });
  assert.deepEqual(pick('/sty', 'style'), { action: 'run', value: '', caret: 0, args: '' }, 'no preset: opens the style settings');
  // `/help` becomes a bare slash, which lists every command.
  const help = pick('/he', 'help');
  assert.deepEqual(help, { action: 'insert', value: '/', caret: 1, args: '' });
  assert.equal(M.slashMenuState(help.value, help.caret).commands.length, C.COMMANDS.length);
});

test('a pick keeps what else was typed', () => {
  const range = (value, word) => ({ start: value.indexOf(word), end: value.indexOf(word) + word.length });
  // Words already after the command word: a client command runs with them.
  assert.deepEqual(M.applyPick('/op channels', range('/op channels', '/op'), byName('open')), { action: 'run', value: '', caret: 0, args: 'channels' });
  assert.deepEqual(M.applyPick('/sty concise', range('/sty concise', '/sty'), byName('style')), { action: 'run', value: '', caret: 0, args: 'concise' });
  assert.deepEqual(M.applyPick('/wr launch day', range('/wr launch day', '/wr'), byName('write')), { action: 'insert', value: '/write launch day', caret: 17, args: 'launch day' });
  // Mid-sentence: a command is the first word of a message, so it moves to the front.
  assert.deepEqual(M.applyPick('Album out Friday /hash', range('Album out Friday /hash', '/hash'), byName('hashtags')), { action: 'insert', value: '/hashtags Album out Friday', caret: 26, args: 'Album out Friday' });
  // A command that needs nothing runs and leaves the sentence alone.
  assert.deepEqual(M.applyPick('hello /ne', range('hello /ne', '/ne'), byName('new')), { action: 'run', value: 'hello ', caret: 6, args: '' });
  assert.deepEqual(M.applyPick('/vo keep this', range('/vo keep this', '/vo'), byName('voice')), { action: 'run', value: 'keep this', caret: 0, args: '' });
  // What a pick inserts is what parseSlash reads on send.
  const inserted = M.applyPick('Album out Friday /hash', range('Album out Friday /hash', '/hash'), byName('hashtags'));
  assert.deepEqual({ name: C.parseSlash(inserted.value).command.name, args: C.parseSlash(inserted.value).args }, { name: 'hashtags', args: 'Album out Friday' });
});

// ---- Client commands -----------------------------------------------------------------------------------------------

test('/open matches page titles, ids and everyday words, and only pages without an id in their path', async (t) => {
  const calls = panel(t);
  const open = byName('open');
  assert.equal(await open.execute('channels'), 'Opening Channels.');
  assert.equal(await open.execute('渠道'), 'Opening Channels.');
  assert.equal(await open.execute('the calendar page'), 'Opening Calendar.');
  assert.equal(await open.execute('chanels'), 'Opening Channels.', 'one typo');
  assert.equal(await open.execute('Usage & plan'), 'Opening Usage & plan.');
  assert.equal(await open.execute('/app/queue'), 'Opening Queue.');
  assert.equal(await open.execute('打開頻道頁'), 'Opening Channels.');
  assert.equal(await open.execute('account settings'), 'Opening Profile.');
  assert.equal(await open.execute('privacy settings'), 'Opening Privacy & data.');
  assert.deepEqual(calls.map(([, href]) => href), ['/app/channels', '/app/channels', '/app/calendar', '/app/channels', '/app/account/billing', '/app/queue', '/app/channels', '/app/account/profile', '/app/account/privacy']);
  for (const page of C.OPENABLE_PAGES) assert.ok(!page.pattern.includes('[') && page.navigable !== false, page.id);
  assert.ok(!C.OPENABLE_PAGES.some((page) => page.id === 'conversation' || page.id === 'help_article'));
  assert.deepEqual(C.findPages('conversation'), []);
});

test('/open asks back instead of guessing, and never navigates without a match', async (t) => {
  const calls = panel(t);
  const open = byName('open');
  assert.match(await open.execute('mem'), /^More than one page matches “mem”: Members or Memory\. Which one\?$/);
  assert.match(await open.execute('天氣'), /^No page matches “天氣”/);
  assert.match(await open.execute(''), /^Which page\?/);
  assert.deepEqual(calls, []);
});

test('/guide matches the guide manifest keywords and starts the guide', async (t) => {
  const calls = panel(t);
  const guide = byName('guide');
  assert.equal(await guide.execute('教我 connect instagram'), 'Starting the guide: Connect a social account.');
  assert.equal(await guide.execute('天氣'), 'Starting the guide: Turn on web search.');
  assert.equal(await guide.execute('how do I schedule a post?'), 'Starting the guide: Schedule a draft.');
  assert.equal(await guide.execute('點樣連接IG'), 'Starting the guide: Connect a social account.');
  assert.equal(await guide.execute('media credits'), 'Starting the guide: Check your plan and credits.');
  assert.equal(await guide.execute('怎么上传图片'), 'Starting the guide: Upload an image to the Library.', 'simplified Chinese');
  const typed = C.parseSlash('/教我 connect instagram');
  assert.equal(typed.command.name, 'guide');
  await typed.command.execute(typed.args);
  assert.deepEqual(calls, [['startGuide', 'connect_account'], ['startGuide', 'turn_on_web_search'], ['startGuide', 'schedule_draft'], ['startGuide', 'connect_account'], ['startGuide', 'check_plan'], ['startGuide', 'upload_image'], ['startGuide', 'connect_account']]);
});

test('/guide with no match lists three guides and starts none', async (t) => {
  const calls = panel(t);
  const answer = await byName('guide').execute('juggling');
  assert.equal(answer, "I don't have a guide for “juggling”. Try “Connect a social account”, “Write a post with Rafii” or “Schedule a draft”.");
  assert.match(await byName('guide').execute(''), /^Which guide\? Try “Connect a social account”, “Write a post with Rafii” or “Schedule a draft”\.$/);
  assert.deepEqual(calls, []);
});

test('/guide says so when the guide could not start here', async (t) => {
  panel(t, { startGuide: async () => false });
  assert.equal(await byName('guide').execute('connect instagram'), 'I couldn\'t start the guide “Connect a social account” here.');
});

test('/style applies a preset or opens the style settings', async (t) => {
  const calls = panel(t);
  const typed = C.parseSlash('/style concise');
  assert.equal(await typed.command.execute(typed.args), 'Style set to Concise.');
  assert.equal(await byName('style').execute('友善'), 'Style set to Friendly.');
  assert.equal(await byName('style').execute('詳細'), 'Style set to Explain in detail.');
  assert.equal(await byName('style').execute('Explain in detail'), 'Style set to Explain in detail.');
  assert.equal(await byName('style').execute(''), 'Opening the style settings.');
  assert.match(await byName('style').execute('pirate'), /^Opening the style settings\. Choose Friendly, Concise or Explain in detail\.$/);
  assert.equal(await byName('style').execute('short and friendly'), 'Opening the style settings. Choose Friendly, Concise or Explain in detail.', 'two presets: let the person choose');
  assert.deepEqual(calls, [
    ['setStyle', { preset: 'concise', chosen: true }],
    ['setStyle', { preset: 'friendly', chosen: true }],
    ['setStyle', { preset: 'explainer', chosen: true }],
    ['setStyle', { preset: 'explainer', chosen: true }],
    ['openStyle'],
    ['openStyle'],
    ['openStyle']
  ]);
  assert.equal(C.findPreset('/style concise'.slice(7)), 'concise');
  assert.equal(C.findPreset('精簡'), 'concise');
});

test('/voice, /new and /help', async (t) => {
  const calls = panel(t);
  assert.equal(await byName('voice').execute(''), 'Starting Voice Mode.');
  assert.equal(await byName('new').execute(''), 'Started a new conversation.');
  assert.equal(await byName('help').execute(''), null, 'the menu is the answer');
  assert.deepEqual(calls, [['startVoice'], ['newConversation']]);
});

test('with no handler on this screen, every client command says it can’t, and never claims success', async () => {
  const cases = { open: 'channels', guide: 'connect instagram', style: 'concise', voice: '', new: '' };
  for (const [name, args] of Object.entries(cases)) {
    const answer = await byName(name).execute(args);
    assert.match(answer, /^I can't .+ from here\.$/, name);
  }
  assert.match(await byName('style').execute(''), /^I can't open the style settings from here\.$/);
});

test('a handler that throws is reported as a failure, not a success', async (t) => {
  const boom = () => {
    throw new Error('boom');
  };
  panel(t, { navigate: boom, startGuide: async () => boom(), setStyle: async () => boom(), openStyle: boom, startVoice: boom, newConversation: boom });
  assert.equal(await byName('open').execute('queue'), "I couldn't open Queue.");
  assert.match(await byName('guide').execute('connect instagram'), /^I couldn't start the guide/);
  assert.equal(await byName('style').execute('concise'), "I couldn't save the style. Try again.");
  assert.equal(await byName('style').execute(''), "I couldn't open the style settings.");
  assert.equal(await byName('voice').execute(''), "I couldn't start Voice Mode.");
  assert.equal(await byName('new').execute(''), "I couldn't start a new conversation.");
});

test('a context can bring its own handlers instead of the registered ones', async () => {
  const seen = [];
  const answer = await byName('open').execute('inbox', { actions: { navigate: (href) => seen.push(href) } });
  assert.equal(answer, 'Opening Inbox.');
  assert.deepEqual(seen, ['/app/inbox']);
});
