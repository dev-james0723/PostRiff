'use strict';
// Cloud-only transport/format fixtures. No browser, user data, model or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const test = require('node:test');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/features/agent-team/report-view.tsx'), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText;
const moduleStub = {exports: {}};
const sandbox = {module: moduleStub, exports: moduleStub.exports,
  require: name => name.startsWith('@/') ? {} : require(name),
  ArrayBuffer, Uint8Array, DataView, TextDecoder, Response, Blob, URL,
  AbortController, DOMException, fetch, crypto: crypto.webcrypto, console};
vm.runInNewContext(compiled, sandbox, {filename: 'report-view.tsx'});
const {parseAgentTeamPcmWav, fetchAgentTeamAudio} = moduleStub.exports;
const selection = {workday: '2026-10-04', kind: 'whole_day', version: 1};
const fingerprint = 'a'.repeat(64);
function wav(seconds = .01) {
  const data = Math.floor(seconds * 16000) * 2;
  const b = Buffer.alloc(44 + data);
  b.write('RIFF'); b.writeUInt32LE(36 + data, 4); b.write('WAVE', 8);
  b.write('fmt ', 12); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34);
  b.write('data', 36); b.writeUInt32LE(data, 40); b[44] = 1;
  return b;
}
function asArray(b) {return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);}
function response(raw = wav(), extra = {}, status = 200) {
  return new Response(status === 200 ? raw : null, {status, headers: {
    'Cache-Control': 'private, no-store', 'Content-Type': 'audio/wav', 'Content-Length': String(raw.length),
    'X-Agent-Team-Report-Version': '1', 'X-Agent-Team-Report-Fingerprint': fingerprint,
    'X-Agent-Team-Audio-Sha256': crypto.createHash('sha256').update(raw).digest('hex'), ...extra}});
}
function invoke(fetcher, chosen = selection, signal = new AbortController().signal) {
  return fetchAgentTeamAudio(chosen, fingerprint, async () => 'fixture-token', signal, fetcher);
}
test('authenticated immutable audio succeeds with a real SHA digest and bounded request', async () => {
  let calls = 0;
  const result = await invoke(async (url, init) => {
    calls++; assert.equal(url, '/api/internal/james-agent-team/reports/2026-10-04/whole_day/wav?version=1');
    assert.equal(init.headers.Authorization, 'Bearer fixture-token');
    assert.equal(init.cache, 'no-store'); assert.equal(init.credentials, 'omit'); assert.equal(init.redirect, 'error');
    return response();
  });
  assert.equal(calls, 1); assert.equal(result.pcm.sampleRate, 16000); assert.equal(result.pcm.frames, 160);
});
test('invalid report selections do not request a token or contact ingress', async () => {
  let count = 0;
  for (const bad of [{...selection, kind:'half_day'}, {...selection, workday:'2026-02-30'}, {...selection, version:0}]) {
    await assert.rejects(fetchAgentTeamAudio(bad, fingerprint, async () => {count++;return 'x';}, new AbortController().signal, async () => {count++;return response();}));
  }
  assert.equal(count, 0);
});
test('wrong headers, lengths and bytes never expose an audio Blob', async () => {
  for (const headers of [{'Cache-Control':'public'}, {'X-Agent-Team-Report-Version':'2'},
    {'X-Agent-Team-Report-Fingerprint':'b'.repeat(64)}, {'X-Agent-Team-Audio-Sha256':'0'.repeat(64)},
    {'Content-Type':'text/html'}, {'Content-Length':'46'}]) {
    await assert.rejects(invoke(async () => response(wav(), headers)));
  }
});
test('WAV truncation, wrong format, silence, duration and byte bounds fail', () => {
  const format = wav(); format.writeUInt32LE(22050, 24);
  const silent = wav(); silent[44] = 0;
  const length = wav(); length.writeUInt32LE(999, 4);
  for (const invalid of [wav().subarray(0, 40), format, silent, length, wav(46), Buffer.alloc(2*1024*1024+1)]) {
    assert.throws(() => parseAgentTeamPcmWav(asArray(invalid)));
  }
});
test('authentication failure, unavailable audio and cancellation remain audio errors', async () => {
  for (const status of [401, 403, 404]) await assert.rejects(invoke(async () => response(wav(), {}, status)));
  const abort = new AbortController(); abort.abort(); let calls = 0;
  await assert.rejects(invoke(async () => {calls++;return response();}, selection, abort.signal));
  assert.equal(calls, 0);
});
