/** Synthetic signed TUS protocol tests; no Storage/provider acceptance. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { webcrypto } = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../src/lib/api/resumable-upload.ts'), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
const mod = { exports: {} }; new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
const U = mod.exports;
const ASSET = 'a'.repeat(32), FP = 'f'.repeat(64), WS = '5b2e7c1a-0000-4000-8000-000000000001';
const ENDPOINT = 'https://abcd.storage.supabase.co/storage/v1/upload/resumable';
const URL = ENDPOINT + '/synthetic-session';
const grant = () => ({ assetId: ASSET, expiresAt: 8000, maxBytes: 30 * 1024 * 1024,
  resumable: { protocol: 'tus', endpoint: ENDPOINT, headers: { 'x-signature': 'one-object-token' }, chunkBytes: U.TUS_CHUNK_BYTES,
    metadata: { bucketName: 'postriff-video', objectName: `${WS}/video/${ASSET}.mp4`, contentType: 'video/mp4', cacheControl: '3600' } } });
const record = (changes = {}) => ({ version: 1, assetId: ASSET, fingerprint: FP, url: URL, createdAt: 1000, ...changes });
function wire(size, options = {}) {
  const w = { calls: [], offset: options.offset ?? 0, dropped: false, conflicted: false };
  w.fetcher = async (url, init) => {
    w.calls.push({ url, ...init });
    assert.equal(init.credentials, 'omit'); assert.equal(init.redirect, 'error');
    assert.equal(init.headers['x-signature'], 'one-object-token');
    assert.equal(init.headers['Tus-Resumable'], '1.0.0');
    assert.equal(Object.keys(init.headers).some((key) => /authorization|apikey|cookie|x-postriff|x-upsert/i.test(key)), false);
    if (init.method === 'POST') return new Response(null, { status: 201, headers: { Location: options.location ?? URL } });
    if (init.method === 'HEAD') {
      if (options.expired) return new Response(null, { status: 410 });
      return new Response(null, { status: 200, headers: { 'Upload-Length': String(options.length ?? size), 'Upload-Offset': String(w.offset) } });
    }
    assert.equal(init.method, 'PATCH'); assert.equal(Number(init.headers['Upload-Offset']), w.offset);
    assert.ok(init.body.size <= U.TUS_CHUNK_BYTES);
    if (options.refused) return new Response(null, { status: 403 });
    if (options.conflict && !w.conflicted) { w.conflicted = true; return new Response(null, { status: 409 }); }
    w.offset += init.body.size;
    if (options.drop && !w.dropped) { w.dropped = true; throw new TypeError('Synthetic dropped response after accepted chunk'); }
    return new Response(null, { status: 204, headers: { 'Upload-Offset': String(w.offset) } });
  };
  return w;
}
const options = (w, updates = {}) => ({ fingerprint: FP, fetcher: w.fetcher, now: () => 1000, sleep: async () => {}, ...updates });

test('signed TUS creates empty session and sends exactly six-MiB chunks with safe headers', async () => {
  const blob = new Blob([new Uint8Array(U.TUS_CHUNK_BYTES + 17)]); const w = wire(blob.size); const checkpoints = [];
  const result = await U.uploadResumableVideo(grant(), blob, options(w, { onCheckpoint: (x) => checkpoints.push(x) }));
  assert.equal(result.url, URL); assert.equal(w.offset, blob.size);
  assert.deepEqual(w.calls.map((x) => x.method), ['POST', 'HEAD', 'PATCH', 'PATCH']);
  assert.equal(w.calls[0].body, undefined); assert.equal(w.calls[2].body.size, U.TUS_CHUNK_BYTES); assert.equal(w.calls[3].body.size, 17);
  assert.match(w.calls[0].headers['Upload-Metadata'], /bucketName /);
  assert.doesNotMatch(JSON.stringify(checkpoints), /one-object-token|x-signature/);
});

test('resuming uses provider HEAD offset and never creates a replacement object', async () => {
  const blob = new Blob([new Uint8Array(U.TUS_CHUNK_BYTES + 17)]); const w = wire(blob.size, { offset: U.TUS_CHUNK_BYTES });
  await U.uploadResumableVideo(grant(), blob, options(w, { previous: record() }));
  assert.deepEqual(w.calls.map((x) => x.method), ['HEAD', 'PATCH']); assert.equal(w.calls[1].body.size, 17);
});

test('lost accepted PATCH response is reconciled by HEAD before the next chunk', async () => {
  const blob = new Blob([new Uint8Array(U.TUS_CHUNK_BYTES + 17)]); const w = wire(blob.size, { drop: true });
  await U.uploadResumableVideo(grant(), blob, options(w));
  assert.deepEqual(w.calls.map((x) => x.method), ['POST', 'HEAD', 'PATCH', 'HEAD', 'PATCH']);
  assert.equal(w.calls.filter((x) => x.method === 'PATCH').length, 2); assert.equal(w.offset, blob.size);
});

test('already accepted final chunk requires only HEAD and no second PATCH', async () => {
  const blob = new Blob(['accepted']); const w = wire(blob.size, { offset: blob.size });
  await U.uploadResumableVideo(grant(), blob, options(w, { previous: record() }));
  assert.deepEqual(w.calls.map((x) => x.method), ['HEAD']);
});

test('foreign session redirect is rejected before bytes or the signature leave the configured origin', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size, { location: 'https://evil.example/steal' });
  await assert.rejects(U.uploadResumableVideo(grant(), blob, options(w)), (e) => e.code === 'protocol');
  assert.equal(w.calls.length, 1); assert.equal(w.calls[0].body, undefined);
});

test('changed file fingerprint or asset cannot resume an existing session', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size);
  await assert.rejects(U.uploadResumableVideo(grant(), blob, options(w, { previous: record({ fingerprint: 'd'.repeat(64) }) })), (e) => e.code === 'invalid_grant');
  assert.equal(w.calls.length, 0);
});

test('expired grant stops before any request and requires same-object renewal', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size); const ticket = grant(); ticket.expiresAt = 999;
  await assert.rejects(U.uploadResumableVideo(ticket, blob, options(w)), (e) => e.code === 'expired');
  assert.equal(w.calls.length, 0);
});

test('expired session does not silently POST a new session or repeat upload', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size, { expired: true });
  await assert.rejects(U.uploadResumableVideo(grant(), blob, options(w, { previous: record() })), (e) => e.code === 'session_expired');
  assert.deepEqual(w.calls.map((x) => x.method), ['HEAD']);
});

test('wrong upload length fails before any chunk', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size, { length: blob.size - 1 });
  await assert.rejects(U.uploadResumableVideo(grant(), blob, options(w)), (e) => e.code === 'protocol');
  assert.equal(w.calls.some((x) => x.method === 'PATCH'), false);
});

test('409 concurrency response reconciles offset before bounded retry', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size, { conflict: true });
  await U.uploadResumableVideo(grant(), blob, options(w));
  assert.deepEqual(w.calls.map((x) => x.method), ['POST', 'HEAD', 'PATCH', 'HEAD', 'PATCH']);
});

test('permission refusal never automatically submits another chunk', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size, { refused: true });
  await assert.rejects(U.uploadResumableVideo(grant(), blob, options(w)), (e) => e.code === 'expired' && e.status === 403);
  assert.equal(w.calls.filter((x) => x.method === 'PATCH').length, 1);
});

test('resume persistence excludes all credentials and is scoped by workspace/content fingerprint', () => {
  const values = new Map(); const store = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
  U.saveVideoResume(WS, { ...record(), 'x-signature': 'never-persist', accessToken: 'never-persist' }, store);
  assert.doesNotMatch([...values.values()][0], /never-persist|signature|accessToken/);
  assert.equal(U.loadVideoResume('foreign-workspace', FP, store), null);
  assert.equal(U.loadVideoResume(WS, FP, store).assetId, ASSET);
  U.clearVideoResume(WS, FP, store); assert.equal(values.size, 0);
});

test('full fingerprint changes for middle content changes and never reads more than one chunk', async () => {
  const original = new Uint8Array(U.TUS_CHUNK_BYTES + 17); const changed = original.slice(); changed[Math.floor(U.TUS_CHUNK_BYTES / 2)] = 1;
  const identity = { name: 'original.mp4', lastModified: 1000 };
  const one = await U.fingerprintVideo(new Blob([original]), identity, webcrypto);
  const two = await U.fingerprintVideo(new Blob([changed]), identity, webcrypto);
  assert.match(one, /^[0-9a-f]{64}$/); assert.notEqual(one, two);
});

test('forbidden broad authorization headers in the grant are rejected', async () => {
  const blob = new Blob(['video']); const w = wire(blob.size); const ticket = grant(); ticket.resumable.headers.authorization = 'Bearer never-forward';
  await assert.rejects(U.uploadResumableVideo(ticket, blob, options(w)), (e) => e.code === 'invalid_grant');
  assert.equal(w.calls.length, 0);
});
