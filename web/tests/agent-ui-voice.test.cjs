/**
 * rafii-genui/1 lane F: browser voice continuity (lib/agent-runtime/voice-session.ts) in the same isolated boundary as
 * voice-session-lifecycle.test.cjs (no microphone, no provider, no outbound call).
 * Proves: a spoken request carries the same uiContext as a text turn (host-provided or the tab's view in use for this
 * workspace and conversation, never another workspace's); speech is the server's speakableSummary only, never presentation
 * source or record ids; an ambiguous spoken "yes" travels unchanged (the server's approval binding decides, nothing here).
 */
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

function harness({ connectGate, transcriptGate, endGate, turnGate, initialFailure, styleGate, turnResult } = {}) {
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
      return turnGate ? await turnGate.promise : (turnResult ?? { runId: 'run', result: { speakableSummary: 'Result', errors: [] } });
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
    const filename = request.startsWith('@/')
      ? path.resolve(WEB, 'src', `${request.slice(2)}.ts`)
      : path.resolve(path.dirname(from), `${request}.ts`);
    if (cache.has(filename)) return cache.get(filename);
    const exports = {}; cache.set(filename, exports);
    const source = fs.readFileSync(filename, 'utf8');
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText;
    vm.runInContext(`(function(require, exports, module){${code}\n})`, context, { filename })(name => load(name, filename), exports, { exports });
    return exports;
  }
  const voice = load('./voice-session');
  const session = voice.voiceSession;
  const registry = load('@/features/agent/generative-ui/state/registry');
  const host = { api, workspaceId: 'workspace', conversationId: 'conversation', pageContext: () => ({}), onConversation() {}, onAnswer: response => answers.push(response) };
  const userSays = (text = 'Check my plan') => transports.at(-1).emit({ type: 'session.input_transcript.delta', delta: text, start_ms: 0, end_ms: 100 });
  const closed = (transport = transports.at(-1), usage = 7) => transport.emit({ type: 'session.closed', reason: 'close_requested', usage: { seconds: usage } });
  return { session, host, transports, starts, ends, transcripts, turns, answers, clock, userSays, closed, voice, registry };
}


const ART = '6c1f2f3e-1111-4222-8333-944455556666';
const spoken = (h) => h.transports.at(-1).sent.filter((e) => e.type === 'session.commentary.append').map((e) => e.content);

async function delegate(h, words = 'Compare the second draft') {
  h.userSays(words);
  await h.clock.tick(700);
  h.transports.at(-1).emit({ type: 'session.delegation.created', delegation: { id: `d-${h.turns.length + 1}` } });
  await h.clock.tick(700);
  await drain();
}

test('a spoken request carries the host’s uiContext, like a text turn', async () => {
  const h = harness();
  h.host.uiContext = () => ({ artifactId: ART, artifactRevision: 2, stateRevision: 5 });
  await h.session.start(h.host);
  await delegate(h);
  assert.equal(h.turns.length, 1);
  assert.deepEqual(h.turns[0].uiContext, { artifactId: ART, artifactRevision: 2, stateRevision: 5 });
  assert.equal(h.turns[0].modality, 'voice');
  assert.equal(h.turns[0].conversationId, 'conversation');
});

test('without a host hook, the tab’s view in use for this workspace and conversation is sent; another workspace’s never', async () => {
  const h = harness();
  h.registry.enterUiScope('workspace:u1:workspace');
  h.registry.setUiContext('workspace:u1:workspace', 'conversation', { artifactId: ART, artifactRevision: 1, stateRevision: 3 });
  await h.session.start(h.host);
  await delegate(h);
  assert.deepEqual(h.turns[0].uiContext, { artifactId: ART, artifactRevision: 1, stateRevision: 3 });
  h.registry.enterUiScope('workspace:u1:other-workspace');
  h.registry.setUiContext('workspace:u1:other-workspace', 'conversation', { artifactId: ART, artifactRevision: 9, stateRevision: 9 });
  await delegate(h, 'And the first one');
  assert.equal(h.turns[1].uiContext, undefined, 'a view of another workspace never travels with this call');
});

test('speech is the speakable summary only: presentation source is never read aloud and record ids are left out', async () => {
  const h = harness({ turnResult: { runId: 'run', result: { speakableSummary: 'root = RafiiRoot([table])\ntable = ToolBoundTable(Query("metrics_summary"))', answerText: 'x', errors: [] } } });
  await h.session.start(h.host);
  await delegate(h);
  assert.deepEqual(spoken(h).slice(-1), ['I’ve put the answer in the panel.']);
  assert.equal(h.voice.speakableText({ speakableSummary: `Draft ${ART} is ready to review.` }), 'Draft is ready to review.');
  assert.equal(h.voice.speakableText({ speakableSummary: 'Use @Run(save) now' }), '');
  assert.equal(h.voice.speakableText({ speakableSummary: '你的第二份草稿最好。' }), '你的第二份草稿最好。');
  assert.equal(h.voice.speakableText(null), '');
});

test('an ambiguous spoken "yes" is sent as said: no proposal, action or activation is resolved in the browser', async () => {
  const h = harness();
  h.host.uiContext = () => ({ artifactId: ART, artifactRevision: 2, stateRevision: 5 });
  await h.session.start(h.host);
  await delegate(h, 'yes');
  const body = h.turns[0];
  assert.equal(body.message, 'yes');
  for (const key of ['proposalId', 'digest', 'actionId', 'activationId', 'decision', 'command']) assert.equal(key in body, false, key);
  assert.deepEqual(Object.keys(body.uiContext).sort(), ['artifactId', 'artifactRevision', 'stateRevision']);
});
