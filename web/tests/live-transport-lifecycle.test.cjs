/** Real transport, synthetic browser boundaries: no microphone, WebRTC network, or provider traffic. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function browserBoundary() {
  const peers = [], audios = [];
  let micStops = 0;
  class Events {
    handlers = new Map();
    addEventListener(type, handler) { const handlers = this.handlers.get(type) ?? new Set(); handlers.add(handler); this.handlers.set(type, handlers); }
    removeEventListener(type, handler) { this.handlers.get(type)?.delete(handler); }
    emit(type, event = {}) { for (const handler of this.handlers.get(type) ?? []) handler(event); }
  }
  class Channel extends Events {
    readyState = 'connecting'; sent = [];
    send(raw) { this.sent.push(JSON.parse(raw)); }
    close() { this.readyState = 'closed'; this.emit('close'); }
  }
  class Peer extends Events {
    connectionState = 'new'; iceGatheringState = 'complete'; localDescription = null; channel = new Channel();
    constructor() { super(); peers.push(this); }
    addTrack() {}
    createDataChannel() { return this.channel; }
    async createOffer() { return { type: 'offer', sdp: 'synthetic-offer' }; }
    async setLocalDescription(value) { this.localDescription = value; }
    async setRemoteDescription() { this.connectionState = 'connected'; this.emit('connectionstatechange'); this.channel.readyState = 'open'; this.channel.emit('open'); }
    close() { this.connectionState = 'closed'; this.emit('connectionstatechange'); }
  }
  const window = {};
  const context = vm.createContext({ process: { env: { NODE_ENV: 'test' } }, window, console, Uint8Array, ArrayBuffer, Math, Date, setTimeout, clearTimeout,
    RTCPeerConnection: Peer,
    navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() { micStops++; } }], getAudioTracks: () => [] }) } },
    AudioContext: class { async resume() {} async close() {} },
    document: { body: { appendChild() {} }, createElement: () => { const audio = { setAttribute() {}, remove() {} }; audios.push(audio); return audio; } } });
  const exports = {};
  const filename = path.join(__dirname, '../src/lib/agent-runtime/live-transport.ts');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText;
  vm.runInContext(`(function(exports){${code}\n})`, context, { filename })(exports);
  return { ...exports, peers, audios, window, micStops: () => micStops };
}

test('a remote data-channel close reports closure even while the peer remains connected', async () => {
  const h = browserBoundary(), transport = new h.WebRtcLiveTransport(), states = [];
  transport.onState(state => states.push(state)); await transport.connect(async () => 'synthetic-answer');
  h.peers[0].channel.close();
  assert.equal(h.peers[0].connectionState, 'connected');
  assert.equal(transport.connected(), false);
  assert.equal(states.at(-1), 'closed');
  transport.close(); assert.equal(h.micStops(), 1);
});

test('a data-channel error reports transport failure', async () => {
  const h = browserBoundary(), transport = new h.WebRtcLiveTransport(), states = [];
  transport.onState(state => states.push(state)); await transport.connect(async () => 'synthetic-answer');
  h.peers[0].channel.emit('error'); assert.equal(states.at(-1), 'failed');
  transport.close();
});

test('local close cannot flush queued events through a late data-channel open callback', async () => {
  const h = browserBoundary(), transport = new h.WebRtcLiveTransport();
  await transport.connect(async () => 'synthetic-answer');
  const channel = h.peers[0].channel; channel.readyState = 'connecting';
  transport.send({ type: 'old-event' }); transport.close();
  channel.readyState = 'open'; channel.emit('open');
  assert.deepEqual(channel.sent, []);
});

test('a cancelled fake transport cannot resurrect the QA harness after its server response', async () => {
  const h = browserBoundary(), transport = new h.FakeLiveTransport(), states = [];
  let resolve; const response = new Promise(yes => { resolve = yes; });
  transport.onState(state => states.push(state));
  const pending = transport.connect(async () => response);
  transport.close(); resolve('synthetic-answer');
  await pending.catch(() => undefined);
  assert.equal(h.window.rafiiLiveHarness, undefined);
  assert.equal(states.includes('connected'), false);
});
