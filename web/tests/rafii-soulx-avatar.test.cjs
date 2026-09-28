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
  result.startSession = async (frame, error, metric) => { result.frame = frame; result.error = error; result.metric = metric; metric({ connection: 'connected' }); };
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
  const sentAt = performance.now() - 100;
  soulx.frame({ generation: 0, sequence: 1, jpeg: 'old', generatedAt: performance.now(), sourcePcmSentAt: sentAt });
  assert.equal(call.get().frame.jpeg, 'old');
  call.displayed(1);
  assert.ok(call.get().metrics.steadyFrameLatencyMs >= 100);
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
  let client;
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
  global.fetch = async (url, options) => { requests.push({ url: String(url), method: options.method }); return { ok: true, json: async () => ({ id: 'test-session', protocolVersion: 2 }) }; };
  try {
    client = new SoulXRenderer('http://127.0.0.1:8765');
    const frames = []; const metrics = [];
    await client.startSession((frame) => frames.push(frame), () => {}, (metric) => metrics.push(metric));
    client.pushAudio(Int16Array.from([100, -100]), 0);
    for (let i = 0; !FakeSocket.instance?.sent.length && i < 20; i++) await new Promise((resolve) => setTimeout(resolve, 1));
    const packet = FakeSocket.instance.sent[0];
    assert.equal(new DataView(packet).getUint32(0, true), 0);
    assert.equal(new DataView(packet).getUint32(4, true), 1);
    assert.equal(new DataView(packet).getInt16(8, true), 100);
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'audio_accepted', sessionId: 'test-session', generation: 0 }) });
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'metrics', sessionId: 'test-session', generation: 0, queueDepth: 1, firstFrameMs: 123, droppedFrames: 0 }) });
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'frame', sessionId: 'test-session', generation: 0, sequence: 1, sourcePacketId: 1, jpeg: 'abc' }) });
    assert.equal(frames[0].jpeg, 'data:image/jpeg;base64,abc');
    assert.equal(typeof frames[0].sourcePcmSentAt, 'number');
    FakeSocket.instance.emit('message', { data: JSON.stringify({ type: 'frame', sessionId: 'other-session', generation: 0, sequence: 2, jpeg: 'wrong' }) });
    assert.equal(frames.length, 1);
    assert.equal(metrics.find((metric) => metric.firstFrameMs === 123).firstFrameMs, 123);
    client.interrupt(1);
    assert.deepEqual(JSON.parse(FakeSocket.instance.sent.at(-1)), { type: 'interrupt', generation: 1 });
    client.endSession();
    assert.deepEqual(requests.filter((item) => item.method).map((item) => item.method), ['POST', 'DELETE']);
  } finally { client?.endSession(); global.fetch = originalFetch; global.WebSocket = originalWebSocket; }
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
    process.env.SOULX_AVATAR_URL = 'https://untrusted.example/';
    assert.deepEqual(await (await route.GET()).json(), { mode: 'disabled', url: null });
    process.env.SOULX_AVATAR_URL = 'http://127.0.0.1:8765';
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

test('worker disconnect reconnects, advances generation, and rejects old session frames', async () => {
  const originalFetch = global.fetch; const originalWebSocket = global.WebSocket;
  let posts = 0; let client;
  const sockets = [];
  class Socket {
    static OPEN = 1;
    readyState = 0; bufferedAmount = 0; sent = []; listeners = {};
    constructor(url) { this.url = String(url); sockets.push(this); queueMicrotask(() => { this.readyState = 1; this.emit('open', {}); }); }
    addEventListener(type, callback) { (this.listeners[type] ??= []).push(callback); }
    emit(type, event) { for (const callback of this.listeners[type] ?? []) callback(event); }
    send(value) { this.sent.push(value); }
    close() { if (this.readyState === 3) return; this.readyState = 3; this.emit('close', {}); }
  }
  global.WebSocket = Socket;
  global.fetch = async (_url, options = {}) => options.method === 'POST'
    ? { ok: true, json: async () => ({ id: `s${++posts}`, protocolVersion: 2 }) }
    : { ok: true, json: async () => ({ processRssBytes: 1000, cpuUserSeconds: 1, cpuSystemSeconds: 0 }) };
  try {
    const frames = []; const metrics = [];
    client = new SoulXRenderer('http://127.0.0.1:8765');
    await client.startSession((frame) => frames.push(frame), () => {}, (metric) => metrics.push(metric));
    for (let i = 0; sockets.length < 1 && i < 20; i++) await new Promise((resolve) => setTimeout(resolve, 1));
    await new Promise((resolve) => setTimeout(resolve, 1));
    client.interrupt(1);
    sockets[0].close();
    client.pushAudio(Int16Array.from([100, 200]), 1);
    for (let i = 0; sockets.length < 2 && i < 20; i++) await new Promise((resolve) => setTimeout(resolve, 1));
    assert.equal(sockets.length, 2);
    await new Promise((resolve) => setTimeout(resolve, 1));
    assert.deepEqual(JSON.parse(sockets[1].sent[0]), { type: 'interrupt', generation: 1 });
    assert.equal(new DataView(sockets[1].sent[1]).getUint32(0, true), 1);
    sockets[0].emit('message', { data: JSON.stringify({ type: 'frame', sessionId: 's1', generation: 1, sequence: 1, jpeg: 'old' }) });
    assert.equal(frames.length, 0);
    sockets[1].emit('message', { data: JSON.stringify({ type: 'frame', sessionId: 's2', generation: 1, sequence: 2, jpeg: 'new' }) });
    assert.equal(frames[0].sequence, 2);
    assert.ok(metrics.some((metric) => metric.connection === 'reconnecting'));
    assert.ok(metrics.some((metric) => typeof metric.reconnectMs === 'number'));
  } finally { client?.endSession(); global.fetch = originalFetch; global.WebSocket = originalWebSocket; }
});

test('missing worker at startup retries without stopping the avatar audio observer', async () => {
  const originalFetch = global.fetch; const originalWebSocket = global.WebSocket;
  let attempts = 0; let client;
  class Socket {
    static OPEN = 1;
    readyState = 0; bufferedAmount = 0; listeners = {}; sent = [];
    constructor() { queueMicrotask(() => { this.readyState = 1; this.emit('open', {}); }); }
    addEventListener(type, callback) { (this.listeners[type] ??= []).push(callback); }
    emit(type, event) { for (const callback of this.listeners[type] ?? []) callback(event); }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; this.emit('close', {}); }
  }
  global.WebSocket = Socket;
  global.fetch = async (_url, options = {}) => {
    if (options.method === 'POST' && ++attempts === 1) throw new Error('worker is starting');
    return { ok: true, json: async () => ({ id: 'recovered', protocolVersion: 2 }) };
  };
  try {
    const metrics = [];
    client = new SoulXRenderer('http://127.0.0.1:8765');
    await client.startSession(() => {}, () => {}, (metric) => metrics.push(metric));
    client.pushAudio(Int16Array.from([500, 500]), 0);
    for (let i = 0; !metrics.some((metric) => metric.connection === 'connected') && i < 100; i++)
      await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(attempts, 2);
    assert.ok(metrics.some((metric) => metric.connection === 'reconnecting'));
    assert.ok(metrics.some((metric) => metric.connection === 'connected'));
    assert.ok(metrics.some((metric) => typeof metric.reconnectMs === 'number'));
  } finally { client?.endSession(); global.fetch = originalFetch; global.WebSocket = originalWebSocket; }
});
