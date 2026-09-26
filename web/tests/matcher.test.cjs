/**
 * `@` typeahead matching (chat-context SPEC §4.3): the required cases and the vectors shared with the server
 * (tests/fixtures/picker-queries.json).
 *
 *   node --test web/tests/matcher.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const ROOT = path.join(__dirname, '..', '..');
function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(source, /from '@\//);
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}
const M = load(path.join(__dirname, '..', 'src', 'features', 'agent', 'attachments', 'matcher.ts'));

const ITEMS = [
  {
    kind: 'post',
    id: 'p-spring',
    label: '春季演奏會',
    sublabel: 'Instagram · zh-Hant-HK',
    updatedAt: 20
  },
  {
    kind: 'post',
    id: 'p-launch',
    label: 'Product launch recap',
    sublabel: 'LinkedIn · en',
    updatedAt: 30
  },
  { kind: 'post', id: 'p-postcard', label: 'Postcard giveaway', sublabel: 'X · en', updatedAt: 10 },
  { kind: 'template', id: 't-1', label: 'Concert announcement', sublabel: 'Event' },
  { kind: 'account', id: 'a-ig', label: 'Instagram · piano_hk', platform: 'Instagram' },
  { kind: 'account', id: 'a-xhs', label: 'Xiaohongshu · dfest', platform: 'Xiaohongshu' },
  { kind: 'folder', id: 'f-1', label: 'Festival', sublabel: '3 accounts' },
  { kind: 'source', id: 's-1', label: 'Programme notes', sublabel: '4 approved facts' },
  { kind: 'image', id: 'i-1', label: 'Photo' },
  { kind: 'video', id: 'v-1', label: 'Video' }
];
const ids = (result) => result.items.map((item) => item.id);

test('parseQuery matches the vectors shared with the server', () => {
  const { vectors } = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'picker-queries.json'), 'utf8')
  );
  assert.ok(vectors.length >= 20);
  for (const v of vectors)
    assert.deepEqual(
      M.parseQuery(v.query),
      { text: v.text, category: v.category, platform: v.platform },
      v.query
    );
});

test('required cases', () => {
  const recent = M.rank('帖子', ITEMS);
  assert.equal(recent.category, 'posts');
  assert.deepEqual(
    ids(recent),
    ['p-launch', 'p-spring', 'p-postcard'],
    '改@帖子 shows recent posts, newest first'
  );
  assert.deepEqual(ids(M.rank('春', ITEMS)), ['p-spring']);
  assert.deepEqual(ids(M.rank('ig', ITEMS)), ['a-ig']);
  assert.deepEqual(ids(M.rank('小紅書', ITEMS)), ['a-xhs']);
  assert.deepEqual(ids(M.rank('＠ＩＧ', ITEMS)), ['a-ig'], 'full-width normalises');
  assert.equal(
    M.rank('post', ITEMS).category,
    'posts',
    '@post is not dropped: it opens the posts group'
  );
  assert.deepEqual(ids(M.rank('postcard', ITEMS)), ['p-postcard']);
});

test('ranking: prefix > word start > substring > recency', () => {
  const items = [
    { kind: 'post', id: 'sub', label: 'Offspring', updatedAt: 99 },
    { kind: 'post', id: 'word', label: 'A spring gala', updatedAt: 50 },
    { kind: 'post', id: 'prefix', label: 'Spring concert', updatedAt: 1 }
  ];
  assert.deepEqual(ids(M.rank('spring', items)), ['prefix', 'word', 'sub']);
  assert.deepEqual(ids(M.rank('相片', ITEMS)), ['i-1', 'v-1']);
  assert.deepEqual(ids(M.rank('notes', ITEMS)), ['s-1']);
  assert.deepEqual(ids(M.rank('programme', ITEMS)), ['s-1']);
});

test('server results win by id; local ones show until it answers', () => {
  const local = [
    { kind: 'post', id: 'a', label: 'local a' },
    { kind: 'post', id: 'b', label: 'local b' }
  ];
  const server = [
    { kind: 'post', id: 'b', label: 'server b' },
    { kind: 'post', id: 'c', label: 'server c' }
  ];
  assert.deepEqual(
    M.mergeResults(local, null).map((i) => i.label),
    ['local a', 'local b']
  );
  assert.deepEqual(
    M.mergeResults(local, server).map((i) => i.label),
    ['server b', 'server c', 'local a']
  );
});

test('the server is asked for one CJK character or two Latin characters', () => {
  assert.equal(M.wantsServer('春'), true);
  assert.equal(M.wantsServer('s'), false);
  assert.equal(M.wantsServer('sp'), true);
  assert.equal(M.wantsServer('帖子'), false, 'a bare alias shows local recents');
});
