/**
 * Chip model (chat-context SPEC §5.1, §4.4–4.5, §6.9): request fields, labels shared with the server, the default
 * post role, one rework at a time, and label insertion.
 *
 *   node --test web/tests/attachments-chips.test.cjs
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
const C = load(path.join(__dirname, '..', 'src', 'features', 'agent', 'attachments', 'chips.ts'));
const A = 'a'.repeat(32);
const B = 'b'.repeat(32);
const chip = (kind, id, extra = {}) => ({
  key: `${kind}:${id}`,
  kind,
  id,
  label: `${kind} ${id}`.slice(0, 20),
  ...extra
});

test('requestFields keeps order, drops unready and duplicate chips, omits empty keys', () => {
  const chips = [
    chip('post', 'p1', { role: 'rework', label: '春季演奏會' }),
    chip('image', A, { role: 'reference', slot: 'A' }),
    chip('template', 't1', { label: 'Concert announcement' }),
    chip('post', 'p1'),
    chip('video', B, { slot: 'B', upload: { status: 'uploading', progress: 0.4 } }),
    chip('source', 's1', { role: 'reference' })
  ];
  assert.deepEqual(C.requestFields(chips, { imageGeneration: false }), {
    references: [
      { kind: 'post', id: 'p1', label: '春季演奏會', role: 'rework' },
      { kind: 'template', id: 't1', label: 'Concert announcement' },
      { kind: 'source', id: 's1', label: 'source s1' }
    ],
    attachments: [{ assetId: A, role: 'reference', slot: 'A' }]
  });
  assert.deepEqual(C.requestFields([], { imageGeneration: false }), {});
  assert.deepEqual(C.requestFields(chips, { imageGeneration: true }), {});
  assert.deepEqual(C.requestFields([chip('image', A)], { imageGeneration: false }), {
    attachments: [{ assetId: A, role: 'post' }]
  });
});

test('requestFields enforces the limits: 3 posts, 12 references, 4 attachments, 1 video', () => {
  const posts = [1, 2, 3, 4].map((n) => chip('post', `p${n}`));
  assert.equal(C.requestFields(posts, { imageGeneration: false }).references.length, 3);
  const many = Array.from({ length: 15 }, (_, n) => chip('source', `s${n}`));
  assert.equal(C.requestFields(many, { imageGeneration: false }).references.length, 12);
  const media = ['1', '2', '3', '4', '5'].map((n) => chip('image', n.repeat(32)));
  assert.equal(C.requestFields(media, { imageGeneration: false }).attachments.length, 4);
  const videos = [chip('video', A), chip('video', B)];
  assert.deepEqual(C.requestFields(videos, { imageGeneration: false }).attachments, [
    { assetId: A, role: 'post' }
  ]);
});

test('labelFor matches the shared vectors (tests/fixtures/chip-labels.json)', () => {
  const { vectors } = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'chip-labels.json'), 'utf8')
  );
  assert.ok(vectors.length >= 10);
  for (const v of vectors) assert.equal(C.labelFor(v.kind, v.record, v.slot), v.expect, v.name);
  assert.ok(
    !/[\ud800-\udfff]/.test(
      C.labelFor('post', { text: 'a\ud83d' + 'b'.repeat(30) }).replace(
        /[\ud800-\udbff][\udc00-\udfff]/g,
        ''
      )
    )
  );
});

test('postRoleDefault matches the shared REWORK_CUES vectors (tests/fixtures/rework-cues.json)', () => {
  const { vectors } = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'rework-cues.json'), 'utf8')
  );
  for (const v of vectors)
    assert.equal(C.postRoleDefault(v.text, 1), v.rework ? 'rework' : 'inspire', v.text);
  assert.equal(
    C.postRoleDefault('rewrite this', 2),
    'inspire',
    'with two posts nothing is reworked by default'
  );
});

test('only one post can be reworked', () => {
  const chips = [
    chip('post', 'p1', { role: 'rework' }),
    chip('post', 'p2', { role: 'inspire' }),
    chip('image', A, { role: 'post' })
  ];
  const next = C.setPostRole(chips, 'post:p2', 'rework');
  assert.deepEqual(
    next.map((c) => c.role),
    ['inspire', 'rework', 'post']
  );
});

test('nextSlot keeps Photo/Video letters stable', () => {
  assert.equal(C.nextSlot([chip('image', A, { slot: 'A' }), chip('video', B, { slot: 'C' })]), 'B');
  assert.equal(
    C.nextSlot(
      ['A', 'B', 'C', 'D'].map((slot, n) => chip('image', String(n).repeat(32), { slot }))
    ),
    null
  );
});

test('insertLabel uses 「」 next to CJK and “” otherwise, with no spaces added', () => {
  const zh = C.insertLabel('改@帖子', 1, 4, '春季演奏會');
  assert.deepEqual([zh.value, zh.caret], ['改「春季演奏會」', 8]);
  const zhAfter = C.insertLabel('@春，用佢', 0, 2, '春季演奏會');
  assert.equal(zhAfter.value, '「春季演奏會」，用佢');
  const en = C.insertLabel('Write like @spr today', 11, 15, 'Spring concert');
  assert.deepEqual([en.value, en.caret], ['Write like “Spring concert” today', 27]);
  assert.equal(C.insertLabel('@x', 0, 2, 'piano_hk').value, '“piano_hk”');
});
