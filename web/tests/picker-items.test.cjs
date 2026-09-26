/**
 * Picker data and the `@` list helpers (chat-context SPEC §4.3, PLAN S23): the snapshot filters mirror
 * `reads.picker_search`, aliases switch groups, recents are 8 per group newest first, and the list's rows, ids,
 * keys, ARIA and announcements follow the SPEC.
 *
 *   node --test web/tests/picker-items.test.cjs
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
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')])
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  throw new Error(`cannot resolve ${base}`);
}
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} };
  cache.set(file, mod);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }
  });
  const localRequire = (name) => {
    if (name.startsWith('@/')) return load(resolve(path.join(SRC, name.slice(2))));
    if (name.startsWith('.')) return load(resolve(path.join(path.dirname(file), name)));
    return require(require.resolve(name, { paths: [WEB] }));
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}
const DIR = path.join(SRC, 'features', 'agent', 'attachments');
const P = load(path.join(DIR, 'picker-items.ts'));
const L = load(path.join(DIR, 'mention-list.tsx'));

const ME = 'user-me';
const snapshot = {
  state: {
    variants: [
      { id: 'v-old', platform: 'Instagram', language: 'zh-Hant-HK', text: '春季演奏會\n門票今日開售', channelId: 'ch-ig' },
      { id: 'v-rejected', platform: 'LinkedIn', language: 'en', text: 'Rejected draft', rejected: true },
      { id: 'v-new', platform: 'LinkedIn', language: 'en', text: 'Product launch recap' },
      { id: 'v-scheduled', platform: 'Threads', language: 'en', text: 'Scheduled one' }
    ],
    contentTypes: {
      catalog: [{ id: 'pack.creator:tutorial_how_to', label: 'How-to' }],
      templates: [
        { id: 't-mine', name: 'My weekly tip', ownerUserId: ME, visibility: 'private', contentTypeId: 'pack.creator:tutorial_how_to' },
        { id: 't-shared', name: 'Team recap', ownerUserId: 'someone', visibility: 'workspace' },
        { id: 't-private', name: 'Their private', ownerUserId: 'someone', visibility: 'private' },
        { id: 't-archived', name: 'Old', ownerUserId: ME, visibility: 'workspace', archived: true }
      ]
    },
    sources: [
      { id: 's-ok', title: 'Recital notes', active: true, kind: 'text', facts: [{ approved: true }, { approved: false }] },
      { id: 's-voice', title: 'Voice sample', active: true, kind: 'voice_sample' },
      { id: 's-banned', title: 'Banned', active: true, kind: 'text', sourcePolicy: 'prohibited' },
      { id: 's-gone', title: 'Withdrawn source', active: false, kind: 'text' }
    ],
    phase2: {
      channels: [
        { id: 'ch-ig', platform: 'Instagram', account: 'piano_hk' },
        { id: 'ch-li', platform: 'LinkedIn', account: 'Piano Studio' },
        { id: 'ch-x', platform: 'X', account: 'old', revoked: true },
        { id: 'ch-red', platform: 'Xiaohongshu', account: '琴室' }
      ],
      channelFolders: [{ id: 'f-1', name: 'Hong Kong', accountIds: ['ch-ig', 'ch-x', 'ch-gone'] }],
      assets: [
        { id: 'a-photo', mime: 'image/jpeg', processing: 'decoded', deleted: false, createdAt: 5, width: 800, height: 600 },
        { id: 'a-video', mime: 'video/mp4', processing: 'ready', deleted: false, createdAt: 9, duration: 12 },
        { id: 'a-uploading', mime: 'video/mp4', processing: 'uploading', deleted: false },
        { id: 'a-deleted', mime: 'image/png', processing: 'decoded', deleted: true },
        { id: 'a-leaving', mime: 'image/png', processing: 'decoded', deleted: false, deletionPending: true }
      ],
      jobs: [{ manifest: { variantId: 'v-scheduled', timing: { timestamp: 1_800_000_000 } } }],
      reviews: []
    }
  }
};
const ids = (result, category) => (result.groups.find((g) => g.category === category)?.items ?? []).map((i) => i.id);

test('filters mirror the server: rejected posts, hidden templates, disconnected accounts, unusable sources, unready media', () => {
  const all = P.pickerItems(snapshot, ME, '');
  assert.deepEqual(ids(all, 'posts').toSorted(), ['v-new', 'v-old', 'v-scheduled']);
  assert.deepEqual(ids(all, 'templates').toSorted(), ['t-mine', 't-shared']);
  assert.deepEqual(ids(all, 'accounts').toSorted(), ['ch-ig', 'ch-li', 'ch-red']);
  assert.deepEqual(ids(all, 'sources'), ['s-ok']);
  assert.deepEqual(ids(all, 'library').toSorted(), ['a-photo', 'a-video']);
  const folder = all.groups.find((g) => g.category === 'folders').items[0];
  assert.equal(folder.sublabel, '1 account');
  const source = all.groups.find((g) => g.category === 'sources').items[0];
  assert.equal(source.sublabel, '1 approved fact');
  const template = all.groups.find((g) => g.category === 'templates').items.find((i) => i.id === 't-mine');
  assert.equal(template.sublabel, 'How-to');
  const account = all.groups.find((g) => g.category === 'accounts').items.find((i) => i.id === 'ch-ig');
  assert.equal(account.label, 'Instagram · piano_hk');
  assert.equal(account.state, 'Connected');
  // Without a principal, only workspace templates show.
  assert.deepEqual(ids(P.pickerItems(snapshot, null, ''), 'templates'), ['t-shared']);
});

test('recents: newest first, a scheduled post by its time, 8 per group', () => {
  const all = P.pickerItems(snapshot, ME, '');
  assert.deepEqual(ids(all, 'posts'), ['v-scheduled', 'v-new', 'v-old']);
  assert.deepEqual(ids(all, 'library'), ['a-video', 'a-photo']);
  const many = { state: { variants: Array.from({ length: 12 }, (_, n) => ({ id: `v${n}`, platform: 'LinkedIn', text: `Post ${n}` })) } };
  const posts = ids(P.pickerItems(many, ME, ''), 'posts');
  assert.equal(posts.length, P.RECENTS);
  assert.equal(posts[0], 'v11');
});

test('aliases switch the group; platform aliases pick accounts on that platform', () => {
  const posts = P.pickerItems(snapshot, ME, '帖子');
  assert.equal(posts.category, 'posts');
  assert.deepEqual(posts.groups.map((g) => g.category), ['posts']);
  assert.deepEqual(ids(P.pickerItems(snapshot, ME, 'ig'), 'accounts'), ['ch-ig']);
  assert.deepEqual(ids(P.pickerItems(snapshot, ME, '小紅書'), 'accounts'), ['ch-red']);
  assert.deepEqual(ids(P.pickerItems(snapshot, ME, 'ＩＧ'), 'accounts'), ['ch-ig']);
  assert.deepEqual(ids(P.pickerItems(snapshot, ME, '春'), 'posts'), ['v-old']);
  // `photo` is a Library alias: the whole group, newest first (SPEC §4.3); text after it filters within the group.
  assert.deepEqual(ids(P.pickerItems(snapshot, ME, 'photo'), 'library'), ['a-video', 'a-photo']);
  assert.deepEqual(ids(P.pickerItems(snapshot, ME, 'library video'), 'library'), ['a-video']);
  assert.ok(ids(P.pickerItems(snapshot, ME, 'post'), 'posts').length > 0, '@post is not dropped');
});

test('mention list rows: Keep first, at most four matches, then More…, stable ids', () => {
  const items = P.flatten(P.pickerItems(snapshot, ME, ''));
  const options = L.mentionOptions('m1', '', items);
  assert.equal(options[0].type, 'keep');
  assert.equal(options[0].label, 'Keep “@” as text');
  assert.equal(options.filter((o) => o.type === 'item').length, L.MENTION_ROWS);
  assert.equal(options.at(-1).label, 'More…');
  assert.equal(options[1].id, `m1-${items[0].kind}-${items[0].id}`);
  assert.deepEqual(L.mentionOptions('m1', '', items).map((o) => o.id), options.map((o) => o.id));
  const few = L.mentionOptions('m1', '春', items.slice(0, 2));
  assert.equal(few.length, 3);
  assert.equal(few[0].label, 'Keep “@春” as text');
});

test('keys: arrows move, Enter picks only off the Keep row, Escape closes; ARIA and announcements', () => {
  assert.deepEqual(L.mentionKey('ArrowDown', 0, 3), { type: 'move', index: 1 });
  assert.deepEqual(L.mentionKey('ArrowUp', 0, 3), { type: 'move', index: 2 });
  assert.equal(L.mentionKey('Enter', 0, 3), null);
  assert.deepEqual(L.mentionKey('Enter', 2, 3), { type: 'choose', index: 2 });
  assert.deepEqual(L.mentionKey('Escape', 1, 3), { type: 'close' });
  assert.equal(L.mentionKey('a', 1, 3), null);

  let stopped = 0;
  let closed = 0;
  const event = (key, extra = {}) => ({ key, preventDefault: () => stopped++, stopPropagation: () => stopped++, nativeEvent: {}, ...extra });
  const list = { open: true, active: 1, count: 3, onMove() {}, onChoose() {}, onClose: () => closed++ };
  assert.equal(L.handleMentionKeyDown(event('Escape'), list), true);
  assert.equal(stopped, 2);
  assert.equal(closed, 1);
  assert.equal(L.handleMentionKeyDown(event('Escape', { keyCode: 229 }), list), false, 'IME keys are not the list’s');
  assert.equal(L.handleMentionKeyDown(event('Escape'), { ...list, composing: true }), false);
  assert.equal(L.handleMentionKeyDown(event('Escape'), { ...list, open: false }), false);

  assert.deepEqual(L.mentionTextareaProps(false, 'm1', null), { 'aria-autocomplete': 'list', 'aria-haspopup': 'listbox' });
  assert.deepEqual(L.mentionTextareaProps(true, 'm1', 'm1-keep'), {
    'aria-autocomplete': 'list',
    'aria-haspopup': 'listbox',
    'aria-controls': 'm1',
    'aria-activedescendant': 'm1-keep'
  });
  assert.equal(L.announcement([{ label: '春季演奏會' }, {}, {}]), '3 matches · 春季演奏會');
  assert.equal(L.announcement([{ label: 'One' }]), '1 match · One');
  assert.equal(L.announcement([]), 'No match. The @ stays as text.');
});

test('the list never takes focus and keeps the keyboard', () => {
  const source = fs.readFileSync(path.join(DIR, 'mention-list.tsx'), 'utf8');
  assert.match(source, /initialFocus=\{false\}/);
  assert.match(source, /finalFocus=\{false\}/);
  assert.match(source, /anchor=\{anchor\}/);
  assert.match(source, /onPointerDown=\{\(event\) => event\.preventDefault\(\)\}/);
  assert.match(source, /useVisualViewport/);
  assert.match(source, /modal=\{false\}/);
});
