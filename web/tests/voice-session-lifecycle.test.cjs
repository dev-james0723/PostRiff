/** Execute the real controller in an isolated browser/API boundary, never a microphone or provider call. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
async function drain() { for (let i = 0; i < 25; i++) await Promise.resolve(); }

function harness({ connectGate, transcriptGate, endGate, turnGate, initialFailure, styleGate } = {}) {
  let now = 10_000, timerId = 0;
  const timers = new Map(), transports = [], starts = [], ends = [], transcripts = [], turns = [], answers = [];
  const schedule = (callback, delay, interval = false) => {
    const id = ++timerId;
    timers.set(id, { callback, due: now + delay, delay, interval });
    return id;
  };
  const clock = {
    timers,
    async tick(ms) {
      now += ms;
      for (let round = 0; round < 50; round++) {
        const due = [...timers].filter(([, timer]) => timer.due <= now);
        if (!due.length) break;
        for (const [id, timer] of due) {
          if (!timers.has(id)) continue;
          if (timer.interval) timer.due = now + timer.delay;
          else timers.delete(id);
          timer.callback();
        }
        await drain();
      }
      await drain();
    },
    intervals: () => [...timers.values()].filter(timer => timer.interval).length
  };
  class BoundaryTransport {
    kind = 'fake'; events = new Set(); states = new Set(); state = 'connecting'; closed = false;
    closeCount = 0; mic = true; outputMuted = false; sent = [];
    constructor() { transports.push(this); }
    async connect(offer) {
      this.emitState('connecting');
      await offer('test-offer');
      if (connectGate) await connectGate.promise;
      if (initialFailure) this.emitState(initialFailure);
      else { this.emitState('connected'); this.emit({ type: 'session.started' }); }
    }
    emit(event) { for (const handler of this.events) handler(event); }
    emitState(state) { this.state = state; for (const handler of this.states) handler(state); }
    onEvent(handler) { this.events.add(handler); return () => this.events.delete(handler); }
    onState(handler) { this.states.add(handler); return () => this.states.delete(handler); }
    connected() { return !this.closed && this.state === 'connected'; }
    send(event) { this.sent.push(event); }
    close() { if (!this.closed) this.closeCount++; this.closed = true; this.emitState('closed'); }
    setMicEnabled(enabled) { this.mic = enabled; }
    setOutputMuted(muted) { this.outputMuted = muted; }
    outputLevel() { return 0; }
  }
  const api = {
    async voiceStart() {
      const id = `session-${starts.length + 1}`;
      starts.push(id);
      return { voiceSessionId: id, conversationId: 'conversation', locale: 'en', sdp: 'test-answer' };
    },
    async voiceTranscript(workspaceId, sessionId, lines) {
      transcripts.push({ sessionId, lines });
      if (transcriptGate) await transcriptGate.promise;
    },
    async voiceEnd(workspaceId, sessionId, body) {
      ends.push({ sessionId, body });
      if (endGate) await endGate.promise;
    },
    async turn(workspaceId, body) {
      turns.push(body);
      return turnGate ? await turnGate.promise : { runId: 'run', result: { speakableSummary: 'Result', errors: [] } };
    },
    async conversationState() { return { task: { steps: [{ label: 'Checking', state: 'running' }] } }; }
  };
  const stubs = {
    react: { useSyncExternalStore() {} },
    '@/lib/api/client': { ApiError: class ApiError extends Error {} },
    './live-transport': { createTransport: () => new BoundaryTransport(), VoiceTransportError: class VoiceTransportError extends Error { constructor(code, message) { super(message); this.code = code; } } },
    './panel-actions': { panelActions: () => ({ setStyle: async () => { if (styleGate) await styleGate.promise; } }) },
    './panel-commands': {
      isFarewell: () => false, matchPanelCommand: request => request === 'slower' ? { kind: 'style', patch: { language: 'yue' } } : null,
      voiceCommandsIn: response => response.voiceCommands ?? [], styleInstructions: () => ['Speak slower.'], confirmation: () => 'Changed.'
    }
  };
  const context = vm.createContext({ console, Math, crypto: globalThis.crypto, Uint8Array,
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
    setTimeout: (callback, delay) => schedule(callback, delay), clearTimeout: id => timers.delete(id),
    setInterval: (callback, delay) => schedule(callback, delay, true), clearInterval: id => timers.delete(id) });
  const cache = new Map();
  function load(request, from = path.join(WEB, 'src/lib/agent-runtime/voice-session.ts')) {
    if (stubs[request]) return stubs[request];
    const filename = path.resolve(path.dirname(from), `${request}.ts`);
    if (cache.has(filename)) return cache.get(filename);
    const exports = {}; cache.set(filename, exports);
    const source = fs.readFileSync(filename, 'utf8');
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText;
    vm.runInContext(`(function(require, exports, module){${code}\n})`, context, { filename })(name => load(name, filename), exports, { exports });
    return exports;
  }
  const session = load('./voice-session').voiceSession;
  const host = { api, workspaceId: 'workspace', conversationId: 'conversation', pageContext: () => ({}), onConversation() {}, onAnswer: response => answers.push(response) };
  const userSays = (text = 'Check my plan') => transports.at(-1).emit({ type: 'session.input_transcript.delta', delta: text, start_ms: 0, end_ms: 100 });
  const closed = (transport = transports.at(-1), usage = 7) => transport.emit({ type: 'session.closed', reason: 'close_requested', usage: { seconds: usage } });
  return { session, host, transports, starts, ends, transcripts, turns, answers, clock, userSays, closed };
}

test('End is idempotent while awaiting the provider and preserves authoritative usage', async () => {
  const h = harness(); await h.session.start(h.host);
  const first = h.session.end();
  const second = h.session.end();
  assert.equal(h.session.get().state, 'ending', 'repeated End cannot enable redial before local cleanup');
  assert.equal(h.transports[0].mic, false, 'the microphone is muted immediately');
  assert.equal(h.transports[0].outputMuted, true, 'output is muted immediately');
  assert.equal(h.transports[0].sent.filter(event => event.type === 'session.close').length, 1);
  h.closed(undefined, 23); await h.clock.tick(100); await Promise.all([first, second]);
  assert.equal(h.transports[0].closeCount, 1);
  assert.equal(h.ends.length, 1);
  assert.equal(h.ends[0].body.usageSeconds, 23);
  assert.equal(h.session.get().state, 'ended');
});

test('queued transcript input cannot unmute output or delegate while End awaits acknowledgement', async () => {
  const h = harness(); await h.session.start(h.host);
  h.session.stopSpeaking();
  const ending = h.session.end();
  h.userSays('A queued word after hangup');
  h.transports[0].emit({ type: 'session.delegation.created', delegation: { id: 'late' } });
  await h.clock.tick(700);
  assert.equal(h.transports[0].outputMuted, true);
  assert.equal(h.turns.length, 0);
  assert.equal(h.session.get().transcript.length, 0);
  h.closed(); await h.clock.tick(100); await ending;
});

for (const boundary of ['transcript', 'end']) {
  test(`late ${boundary} persistence cannot close or overwrite a subsequent call`, async () => {
    const gate = deferred(); const h = harness({ [boundary === 'transcript' ? 'transcriptGate' : 'endGate']: gate });
    await h.session.start(h.host); h.userSays();
    const first = h.session.end(); h.closed(); await drain();
    assert.equal(h.transports[0].closed, true, 'local media closes before persistence completes');
    assert.equal(h.session.get().state, 'ended', 'the next deliberate call does not wait for persistence');
    void h.session.end();
    await h.session.start(h.host);
    const next = h.transports[1];
    assert.equal(h.session.get().state, 'live');
    gate.resolve(); await h.clock.tick(100); await first;
    assert.equal(next.closed, false);
    assert.equal(h.session.get().state, 'live');
    assert.equal(h.session.get().voiceSessionId, 'session-2');
    assert.equal(h.clock.intervals(), 1, 'only the new call retains a level meter');
    assert.equal(h.transports[0].events.size, 0);
    assert.equal(h.ends.filter(end => end.sessionId === 'session-1').length, 1);
  });
}

test('a missing session.closed acknowledgement ends locally after the bounded deadline', async () => {
  const h = harness(); await h.session.start(h.host);
  const ending = h.session.end(); await drain(); await h.clock.tick(15_001); await ending;
  assert.equal(h.session.get().state, 'ended');
  assert.equal(h.transports[0].closed, true);
  assert.equal(h.clock.intervals(), 0);
  assert.equal(h.ends.length, 1);
});

test('a transport drop while waiting for the close acknowledgement finishes immediately', async () => {
  const h = harness(); await h.session.start(h.host);
  const ending = h.session.end();
  h.transports[0].emitState('disconnected'); await drain();
  assert.equal(h.session.get().state, 'ended');
  assert.equal(h.transports[0].closed, true);
  await h.clock.tick(100); await ending;
});

test('transport failure during connection reports an error and releases its resources', async () => {
  const h = harness({ initialFailure: 'failed' }); await h.session.start(h.host); await drain();
  assert.equal(h.session.get().state, 'error');
  assert.equal(h.transports[0].closed, true);
  assert.equal(h.clock.intervals(), 0);
  assert.equal(h.ends.length, 1);
});

test('unexpected transport closure is visible even without a session.closed event', async () => {
  const h = harness(); await h.session.start(h.host);
  h.transports[0].emitState('closed'); await drain();
  assert.equal(h.session.get().state, 'error');
  assert.equal(h.session.get().voiceSessionId, null);
  assert.equal(h.clock.intervals(), 0);
});

test('a transport that recovers briefly remains the same live call', async () => {
  const h = harness(); await h.session.start(h.host);
  h.transports[0].emitState('disconnected'); assert.equal(h.session.get().state, 'reconnecting');
  h.transports[0].emitState('connected'); assert.equal(h.session.get().state, 'live');
  assert.equal(h.starts.length, 1);
});

test('reconnect isolates old transcript persistence and ignored queued provider callbacks', async () => {
  const gate = deferred(); const h = harness({ transcriptGate: gate }); await h.session.start(h.host); h.userSays('Old call words');
  const oldHandler = [...h.transports[0].events][0];
  h.transports[0].emitState('disconnected');
  await h.session.reconnect();
  const next = h.transports[1];
  oldHandler({ type: 'session.closed', reason: 'expired' });
  oldHandler({ type: 'session.input_transcript.delta', delta: 'Late old words', start_ms: 0, end_ms: 1 });
  gate.resolve(); await drain();
  assert.equal(h.session.get().state, 'live');
  assert.equal(h.session.get().voiceSessionId, 'session-2');
  assert.equal(next.closed, false);
  assert.equal(h.session.get().transcript.length, 0);
  assert.deepEqual(h.transcripts.map(upload => upload.sessionId), ['session-1']);
});

test('a late delegation result cannot speak, mute, or end a replacement call using the same host', async () => {
  const gate = deferred(); const h = harness({ turnGate: gate }); await h.session.start(h.host);
  h.userSays(); await h.clock.tick(700); h.transports[0].emit({ type: 'session.delegation.created', delegation: { id: 'old-delegation' } }); await drain();
  assert.equal(h.turns.length, 1);
  h.transports[0].emitState('disconnected'); await h.session.reconnect();
  const next = h.transports[1], sentBefore = next.sent.length;
  gate.resolve({ runId: 'old-run', result: { speakableSummary: 'Old answer', errors: [] }, voiceCommands: [{ command: 'mute' }, { command: 'end_call' }] }); await drain();
  assert.equal(next.sent.length, sentBefore);
  assert.equal(next.mic, true);
  assert.equal(h.session.get().endingAfterReply, false);
  assert.equal(h.session.get().state, 'live');
  assert.equal(h.answers.length, 0);
});

test('a delegation still collecting old words cannot submit after reconnect', async () => {
  const h = harness(); await h.session.start(h.host); h.userSays();
  h.transports[0].emit({ type: 'session.delegation.created', delegation: { id: 'collecting' } });
  h.transports[0].emitState('disconnected'); await h.session.reconnect();
  h.userSays('New call request'); await h.clock.tick(1000);
  assert.equal(h.turns.length, 0, 'the old collector must not consume the new call\'s request');
  assert.equal(h.session.get().delegations.length, 0);
});

test('a pending local style command cannot apply to a replacement call', async () => {
  const gate = deferred(); const h = harness({ styleGate: gate }); await h.session.start(h.host);
  h.userSays('slower'); await h.clock.tick(700); h.transports[0].emit({ type: 'session.delegation.created', delegation: { id: 'style' } }); await drain();
  h.transports[0].emitState('disconnected'); await h.session.reconnect();
  const next = h.transports[1], sentBefore = next.sent.length;
  gate.resolve(); await drain();
  assert.equal(next.sent.length, sentBefore);
  assert.equal(h.session.get().locale, 'en');
});

test('End during setup releases the old transport before a late connection resolves', async () => {
  const gate = deferred(); const h = harness({ connectGate: gate });
  const starting = h.session.start(h.host); await drain();
  await h.session.end();
  assert.equal(h.transports[0].closed, true);
  assert.equal(h.session.get().state, 'ended');
  gate.resolve(); await starting; await drain();
  assert.equal(h.session.get().state, 'ended');
  assert.equal(h.clock.intervals(), 0);
});
