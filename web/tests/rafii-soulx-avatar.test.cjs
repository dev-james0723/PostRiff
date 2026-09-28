const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(name) {
  const source = fs.readFileSync(path.join(__dirname, '../src/lib/agent-runtime', name + '.ts'), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  new Function('require', 'exports', output)(require, exports);
  return exports;
}

const { AvatarSession, Pcm16Resampler } = load('avatar-bridge');
const { SoulXRenderer } = load('soulx-renderer');
global.requestAnimationFrame = (callback) => { callback(); return 1; };

function transport() {
  let observer = null;
  const played = [];
  return {
    played,
    subscriptions: 0,
    onAssistantAudio(handler) { this.subscriptions++; observer = handler; return () => { observer = null; }; },
    emit(samples, rate = 48000) { played.push(samples); observer?.(samples, rate, performance.now()); },
    hasObserver: () => Boolean(observer)
  };
}

function renderer() {
  const result = { audio: [], interrupts: [], ended: false };
  result.startSession = async (frame, error, metric) => { result.frame = frame; result.error = error; result.metric = metric; };
  result.pushAudio = (data, generation) => result.audio.push({ data: [...data], generation });
  result.interrupt = (generation) => result.interrupts.push(generation);
  result.endSession = () => { result.ended = true; };
  return result;
}

test('audio tap keeps original playback object, ordering and 48k-to-16k samples', async () => {
  const call = new AvatarSession(); const live = transport(); const soulx = renderer();
  await call.start(live, soulx);
  const a = Float32Array.from({ length: 480 }, (_, i) => 0.2 + i / 10000);
  const b = Float32Array.from({ length: 480 }, (_, i) => 0.3 + i / 10000);
  live.emit(a); live.emit(b);
  assert.equal(live.played[0], a);
  assert.equal(live.played[1], b);
  assert.equal(soulx.audio.length, 2);
  assert.equal(soulx.audio[0].generation, 0);
  assert.equal(soulx.audio[0].data.length + soulx.audio[1].data.length, 320);
  assert.ok(soulx.audio[0].data[0] > 6000);
  assert.ok(soulx.audio[1].data[0] > soulx.audio[0].data[0]);
  call.end(); assert.equal(live.hasObserver(), false);
});

test('two Live sessions keep audio and renderer queues isolated', async () => {
  const a = new AvatarSession(); const b = new AvatarSession();
  const liveA = transport(); const liveB = transport(); const renderA = renderer(); const renderB = renderer();
  await Promise.all([a.start(liveA, renderA), b.start(liveB, renderB)]);
  liveA.emit(Float32Array.from({ length: 480 }, () => 0.3));
  assert.equal(renderA.audio.length, 1); assert.equal(renderB.audio.length, 0);
  liveB.emit(Float32Array.from({ length: 480 }, () => 0.5));
  assert.equal(renderA.audio.length, 1); assert.equal(renderB.audio.length, 1);
  a.end(); b.end();
});

test('interrupt rejects stale frames, clears image and resumes on new generation', async () => {
  const call = new AvatarSession(); const live = transport(); const soulx = renderer();
  await call.start(live, soulx);
  live.emit(Float32Array.from({ length: 480 }, () => 0.4));
  soulx.frame({ generation: 0, sequence: 1, jpeg: 'old', generatedAt: performance.now() });
  assert.equal(call.get().frame.jpeg, 'old');
  call.interrupt();
  assert.equal(call.get().frame, null);
  assert.deepEqual(soulx.interrupts, [1]);
  soulx.frame({ generation: 0, sequence: 2, jpeg: 'stale', generatedAt: performance.now() });
  assert.equal(call.get().frame, null);
  assert.equal(call.get().metrics.droppedFrames, 1);
  call.resume(); live.emit(Float32Array.from({ length: 480 }, () => 0.5));
  assert.equal(soulx.audio.at(-1).generation, 1);
  soulx.frame({ generation: 1, sequence: 3, jpeg: 'new', generatedAt: performance.now() });
  assert.equal(call.get().frame.jpeg, 'new');
  call.end();
});

test('speech ending retires the generation so late video cannot reopen the mouth', async () => {
  const call = new AvatarSession(); const live = transport(); const soulx = renderer();
  await call.start(live, soulx);
  live.emit(Float32Array.from({ length: 480 }, () => 0.3));
  call.pushAudio(new Float32Array(480), 48000, performance.now() + 1600);
  assert.equal(call.get().status, 'listening');
  assert.equal(call.get().frame, null);
  assert.deepEqual(soulx.interrupts, [1]);
  soulx.frame({ generation: 0, sequence: 7, jpeg: 'late', generatedAt: performance.now() });
  assert.equal(call.get().frame, null);
  call.end();
});

test('worker disconnect is avatar-only and disabled mode never subscribes', async () => {
  const disabled = new AvatarSession(); const live = transport();
  assert.equal(live.subscriptions, 0);
  assert.equal(disabled.get().status, 'idle');
  const call = new AvatarSession(); const soulx = renderer(); await call.start(live, soulx);
  soulx.error('worker disconnected');
  assert.equal(call.get().status, 'offline');
  assert.equal(live.hasObserver(), false);
  live.emit(Float32Array.from({ length: 480 }, () => 0.4));
  assert.equal(live.played.length, 1);
  assert.equal(soulx.audio.length, 0);
});

test('resampler preserves chunk boundaries and handles 44.1 kHz input', () => {
  const whole = new Pcm16Resampler(); const split = new Pcm16Resampler();
  const input = Float32Array.from({ length: 4410 }, (_, i) => Math.sin(i / 30));
  const expected = [...whole.convert(input, 44100)];
  const actual = [...split.convert(input.subarray(0, 1001), 44100), ...split.convert(input.subarray(1001), 44100)];
  assert.deepEqual(actual, expected);
  assert.ok(actual.length >= 1599 && actual.length <= 1600);
});

test('SoulX worker protocol opens, streams PCM, receives frames, interrupts and closes', async () => {
  const originalFetch = global.fetch; const originalWebSocket = global.WebSocket;
  const requests = [];
  class FakeSocket {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    sent = [];
    listeners = {};
    constructor(url) { this.url = String(url); FakeSocket.instance = this; queueMicrotask(() => this.emit('open', {})); }
    addEventListener(type, callback) { (this.listeners[type] ??= []).push(callback); }
    emit(type, event) { for (const callback of this.listeners[type] ?? []) callback(event); }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; this.emit('close', {}); }
  }
  global.WebSocket = FakeSocket;
  global.fetch = async (url, options) => { requests.push({ url: String(url), method: options.method }); return { ok: true, json: async () => ({ id: 'test-session' }) }; };
  try {
    const client = new SoulXRenderer('http://127.0.0.1:8765');
    const frames = []; const metrics = [];
    await client.startSession((frame) => frames.push(frame), () => {}, (metric) => metrics.push(metric));
    client.pushAudio(Int16Array.from([100, -100]), 0);
    const packet = FakeSocket.instance.sent[0];
    assert.equal(new DataView(packet).getUint32(0, true), 0);
    assert.equal(new DataView(packet).getInt16(4, true), 100);
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'audio_accepted', generation: 0 }) });
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'metrics', generation: 0, queueDepth: 1, firstFrameMs: 123, droppedFrames: 0 }) });
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'frame', generation: 0, sequence: 1, jpeg: 'abc' }) });
    assert.equal(frames[0].jpeg, 'data:image/jpeg;base64,abc');
    assert.equal(metrics.at(-1).firstFrameMs, 123);
    client.interrupt(1);
    assert.deepEqual(JSON.parse(FakeSocket.instance.sent.at(-1)), { type: 'interrupt', generation: 1 });
    client.endSession();
    assert.deepEqual(requests.map((item) => item.method), ['POST', 'DELETE']);
  } finally { global.fetch = originalFetch; global.WebSocket = originalWebSocket; }
});

test('disabled and production modes never expose the avatar worker URL', async () => {
  const file = fs.readFileSync(path.join(__dirname, '../src/app/api/rafii/avatar/config/route.ts'), 'utf8');
  const output = ts.transpileModule(file, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const route = {}; new Function('require', 'exports', output)(require, route);
  const prior = { AVATAR_MODE: process.env.AVATAR_MODE, SOULX_AVATAR_URL: process.env.SOULX_AVATAR_URL, NODE_ENV: process.env.NODE_ENV };
  try {
    process.env.SOULX_AVATAR_URL = 'http://127.0.0.1:8765';
    process.env.AVATAR_MODE = 'disabled';
    process.env.NODE_ENV = 'development';
    assert.deepEqual(await (await route.GET()).json(), { mode: 'disabled', url: null });
    process.env.AVATAR_MODE = 'soulx';
    assert.deepEqual(await (await route.GET()).json(), { mode: 'soulx', url: 'http://127.0.0.1:8765' });
    process.env.NODE_ENV = 'production';
    assert.deepEqual(await (await route.GET()).json(), { mode: 'disabled', url: null });
  } finally {
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

test('two seconds of queued PCM is the upper bound during a stalled worker startup', () => {
  const client = new SoulXRenderer('http://127.0.0.1:8765');
  for (let i = 0; i < 300; i++) client.pushAudio(Int16Array.from({ length: 1600 }, () => i), 0);
  const pendingBytes = client.pending.reduce((sum, item) => sum + item.data.byteLength, 0);
  assert.ok(pendingBytes <= 64000);
  assert.ok(client.dropped > 0);
  client.endSession();
});
