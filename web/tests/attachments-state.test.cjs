/**
 * The composer chip machine, persistence and the estimate key (chat-context SPEC §4.4, §4.7, §11.4, §11.5; PLAN S24).
 *
 *   node --test web/tests/attachments-state.test.cjs
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
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts')])
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
const S = load(path.join(SRC, 'features', 'agent', 'attachments', 'state.ts'));
const B = load(path.join(SRC, 'features', 'agent', 'brief-recovery.ts'));

const run = (actions, start = S.EMPTY) => actions.reduce(S.reduce, start);
const photo = (key, extra = {}) => ({ key, kind: 'image', id: key, label: 'Photo', role: 'post', upload: { status: 'preparing' }, ...extra });
const post = (id, role) => ({ key: `k-${id}`, kind: 'post', id, label: `Post ${id}`, ...(role ? { role } : {}) });

test('an upload goes preparing → uploading(p%) → checking → ready, and only then joins the fields', () => {
  let state = run([{ type: 'add', chip: photo('c1') }]);
  assert.equal(state.chips[0].slot, 'A');
  assert.deepEqual(S.fields(state, { imageGeneration: false }), {});
  assert.equal(S.blockerMessage(state), 'Waiting for 1 upload to finish.');
  state = run([{ type: 'upload', key: 'c1', status: 'uploading', progress: 40.4 }], state);
  assert.deepEqual(state.chips[0].upload, { status: 'uploading', progress: 40 });
  state = run([{ type: 'upload', key: 'c1', status: 'checking' }], state);
  assert.equal(S.blockers(state).length, 1);
  state = run([{ type: 'uploaded', key: 'c1', id: 'a'.repeat(32), meta: { mime: 'image/jpeg' } }], state);
  assert.equal(S.blockerMessage(state), null);
  assert.deepEqual(S.fields(state, { imageGeneration: false }), { attachments: [{ assetId: 'a'.repeat(32), role: 'post', slot: 'A' }] });
  assert.deepEqual(S.fields(state, { imageGeneration: true }), {}, 'image turns send no chips');
});

test('a failed upload blocks nothing, is not sent, and retry goes back to preparing', () => {
  let state = run([{ type: 'add', chip: photo('c1') }, { type: 'add', chip: photo('c2') }]);
  assert.equal(S.blockerMessage(state), 'Waiting for 2 uploads to finish.');
  state = run([{ type: 'failed', key: 'c1', message: 'Upload failed. Try again.' }], state);
  assert.equal(S.blockerMessage(state), 'Waiting for 1 upload to finish.');
  assert.deepEqual(S.fields(state, { imageGeneration: false }), {});
  state = run([{ type: 'retry', key: 'c1' }], state);
  assert.equal(state.chips[0].upload.status, 'preparing');
});

test('reads: reading → read with the note, or failed; reading lines count photos', () => {
  let state = run([{ type: 'add', chip: { key: 'r', kind: 'image', id: 'b'.repeat(32), label: 'Photo', role: 'reference' } }, { type: 'reading', key: 'r' }]);
  assert.equal(S.readingMessage(state), 'Reading 1 photo…');
  state = run([{ type: 'read', key: 'r', note: 'A piano.', milliCredits: 1200 }], state);
  assert.deepEqual(state.chips[0].read, { status: 'read', note: 'A piano.', milliCredits: 1200 });
  assert.equal(S.readingMessage(state), null);
  state = run([{ type: 'readFailed', key: 'r' }], state);
  assert.equal(state.chips[0].read.status, 'failed');
  assert.deepEqual(S.fields(state, { imageGeneration: false }).attachments, [{ assetId: 'b'.repeat(32), role: 'reference', slot: 'A' }], 'read failed still goes out');
});

test('limits and duplicates: 4 media, 1 video, 3 posts, 12 references; the same item once', () => {
  let state = S.EMPTY;
  for (const n of [1, 2, 3, 4, 5]) state = run([{ type: 'add', chip: { key: `m${n}`, kind: 'image', id: `${n}`.repeat(32), label: 'Photo', role: 'post' } }], state);
  assert.equal(state.chips.length, 4);
  assert.deepEqual(state.chips.map((c) => c.slot), ['A', 'B', 'C', 'D']);
  assert.equal(S.refusal(state.chips, { key: 'x', kind: 'image', id: 'f'.repeat(32), label: 'Photo' }), S.LIMIT_MESSAGES.attachments);
  const videos = run([{ type: 'add', chip: { key: 'v1', kind: 'video', id: 'a'.repeat(32), label: 'Video' } }]);
  assert.equal(S.refusal(videos.chips, { key: 'v2', kind: 'video', id: 'b'.repeat(32), label: 'Video' }), S.LIMIT_MESSAGES.videos);
  const posts = run([1, 2, 3].map((n) => ({ type: 'add', chip: post(`p${n}`) })));
  assert.equal(S.refusal(posts.chips, post('p4')), S.LIMIT_MESSAGES.posts);
  assert.equal(S.refusal(posts.chips, post('p1')), 'duplicate');
  const many = run(Array.from({ length: 12 }, (_, n) => ({ type: 'add', chip: { key: `s${n}`, kind: 'source', id: `s${n}`, label: 'Source' } })));
  assert.equal(S.refusal(many.chips, { key: 't', kind: 'template', id: 't', label: 'Template' }), S.LIMIT_MESSAGES.references);
});

test('roles: one rework post at a time; media roles switch and keep a read note', () => {
  let state = run([{ type: 'add', chip: post('p1', 'rework') }, { type: 'add', chip: post('p2', 'inspire') }]);
  state = run([{ type: 'role', key: 'k-p2', role: 'rework' }], state);
  assert.deepEqual(state.chips.map((c) => c.role), ['inspire', 'rework']);
  assert.equal(run([{ type: 'role', key: 'k-p1', role: 'reference' }], state), state, 'a post never takes a media role');
  let media = run([{ type: 'add', chip: { key: 'm', kind: 'image', id: 'c'.repeat(32), label: 'Photo', role: 'reference', read: { status: 'read', note: 'n' } } }]);
  media = run([{ type: 'role', key: 'm', role: 'post' }, { type: 'role', key: 'm', role: 'reference' }], media);
  assert.equal(media.chips[0].read.note, 'n');
});

test('remove → undo within 5 s restores the same place; after 5 s it is gone', () => {
  let state = run([{ type: 'add', chip: post('p1') }, { type: 'add', chip: post('p2') }, { type: 'add', chip: post('p3') }]);
  state = run([{ type: 'remove', key: 'k-p2', at: 1000 }], state);
  assert.deepEqual(state.chips.map((c) => c.id), ['p1', 'p3']);
  const undone = run([{ type: 'undo', at: 1000 + S.UNDO_MS - 1 }], state);
  assert.deepEqual(undone.chips.map((c) => c.id), ['p1', 'p2', 'p3']);
  assert.equal(undone.removed.length, 0);
  const late = run([{ type: 'undo', at: 1000 + S.UNDO_MS }], state);
  assert.deepEqual(late.chips.map((c) => c.id), ['p1', 'p3']);
  assert.deepEqual(S.expired(state, 1000 + S.UNDO_MS).map((c) => c.id), ['p2']);
  assert.equal(run([{ type: 'expire', at: 1000 + S.UNDO_MS }], state).removed.length, 0);
});

test('clearSent keeps chips that did not go out (unsent uploads, and anything added after the send began)', () => {
  let state = run([{ type: 'add', chip: post('p1') }, { type: 'add', chip: photo('c1') }]);
  const sent = S.sentKeys(state, { imageGeneration: false });
  assert.deepEqual(sent, ['k-p1']);
  state = run([{ type: 'add', chip: post('p2') }, { type: 'clearSent', keys: sent }], state);
  assert.deepEqual(state.chips.map((c) => c.key), ['c1', 'k-p2']);
  assert.deepEqual(S.sentKeys(state, { imageGeneration: true }), []);
});

test('persistence: settled chips saved as they are, uploads as stopped; restore re-checks against the snapshot', () => {
  const chips = [
    post('p1', 'rework'),
    { key: 'm', kind: 'image', id: 'd'.repeat(32), label: 'Photo A', role: 'reference', slot: 'A' },
    photo('up', { upload: { status: 'uploading', progress: 50 }, slot: 'B' }),
    photo('bad', { upload: { status: 'failed', message: 'x' } })
  ];
  const saved = S.toSaved(chips);
  assert.deepEqual(saved, [
    { kind: 'post', id: 'p1', label: 'Post p1', role: 'rework' },
    { kind: 'image', id: 'd'.repeat(32), label: 'Photo A', role: 'reference', slot: 'A' },
    { kind: 'image', id: 'up', label: 'Photo', role: 'post', slot: 'B', stopped: true }
  ]);
  const available = new Set([`image:${'d'.repeat(32)}`]);
  const { chips: back, dropped } = S.fromSaved(saved, available, (_, i) => `r${i}`);
  assert.deepEqual(dropped.map((c) => c.id), ['p1'], 'a post no longer in the workspace is dropped');
  assert.deepEqual(back.map((c) => [c.key, c.upload?.status ?? 'settled']), [['r1', 'settled'], ['r2', 'failed']]);
  assert.equal(back[1].upload.message, S.UPLOAD_STOPPED);
});

test('brief recovery v2 stores text and chips, v1 still decodes, other owners and bad chips never restore', () => {
  const raw = B.encodeBrief('u', 'w', 'Draft text', [{ kind: 'post', id: 'p1', label: 'Post', role: 'rework' }]);
  assert.deepEqual(Object.keys(JSON.parse(raw)).sort(), ['chips', 'owner', 'text', 'version', 'workspace']);
  assert.deepEqual(B.decodeBriefState(raw, 'u', 'w'), { text: 'Draft text', chips: [{ kind: 'post', id: 'p1', label: 'Post', role: 'rework' }] });
  assert.equal(B.decodeBrief(raw, 'u', 'w'), 'Draft text');
  assert.equal(B.decodeBriefState(raw, 'other', 'w'), null);
  const v1 = JSON.stringify({ version: 1, owner: 'u', workspace: 'w', text: 'Old' });
  assert.deepEqual(B.decodeBriefState(v1, 'u', 'w'), { text: 'Old', chips: [] });
  const forged = JSON.stringify({ version: 2, owner: 'u', workspace: 'w', text: 't', chips: [{ kind: 'account', id: 'x', label: 'x' }] });
  assert.equal(B.decodeBriefState(forged, 'u', 'w'), null);
  assert.throws(() => B.encodeBrief('u', 'w', 't', [{ kind: 'post', id: 'bad id!', label: 'x' }]));
  assert.equal(B.turnStorageKey('u', 'w', 'c/1'), 'rafii.turn.u.w.c%2F1');
});

test('the credit estimate is keyed on the exact body plus the workspace revision', () => {
  const source = fs.readFileSync(path.join(SRC, 'features', 'agent', 'use-credit-estimate.ts'), 'utf8');
  const { outputText } = ts.transpileModule(source.replace(/^import .*$/gm, ''), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(() => ({}), mod, mod.exports);
  const body = { operation: 'turn', conversationId: 'c', request: { text: 'x', references: [{ kind: 'post', id: 'p1' }] } };
  assert.equal(mod.exports.estimateKey(false, body, 3), '');
  assert.notEqual(mod.exports.estimateKey(true, body, 3), mod.exports.estimateKey(true, body, 4));
  assert.notEqual(mod.exports.estimateKey(true, body, 3), mod.exports.estimateKey(true, { ...body, request: { ...body.request, references: [] } }, 3));
  assert.equal(mod.exports.estimateKey(true, body, 3), mod.exports.estimateKey(true, JSON.parse(JSON.stringify(body)), 3));
});
