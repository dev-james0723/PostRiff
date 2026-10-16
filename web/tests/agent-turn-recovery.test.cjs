// A panel turn whose POST response never arrives (background tab, dropped connection) must still settle from the
// server's own record once the person can see the tab again, and the generated view for it must start exactly once.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const read = (rel) => fs.readFileSync(path.join(WEB, rel), 'utf8');

function load(rel) {
  const file = path.join(WEB, rel);
  assert.ok(fs.existsSync(file), `${rel} must exist`);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

/** A tab whose visibility the test controls; `window`/`document` are installed only for the test's duration. */
function fakeTab(initial = 'hidden') {
  const doc = new EventTarget();
  doc.visibilityState = initial;
  const win = new EventTarget();
  const saved = { window: globalThis.window, document: globalThis.document };
  globalThis.window = win;
  globalThis.document = doc;
  return {
    show() { doc.visibilityState = 'visible'; doc.dispatchEvent(new Event('visibilitychange')); },
    hide() { doc.visibilityState = 'hidden'; doc.dispatchEvent(new Event('visibilitychange')); },
    focus() { win.dispatchEvent(new Event('focus')); },
    online() { win.dispatchEvent(new Event('online')); },
    restore() { globalThis.window = saved.window; globalThis.document = saved.document; }
  };
}

const flush = async (n = 8) => { for (let i = 0; i < n; i += 1) await new Promise((resolve) => setImmediate(resolve)); };
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const COMPLETED = { conversationId: 'c1', runId: 'run-1', messageId: 'm1', status: 'completed', result: { blocks: [], ui: { eligible: true } } };
const RUNNING = { conversationId: 'c1', runId: 'run-1', messageId: null, status: 'running', result: null };

test('hidden tab + lost response: nothing polls while hidden, becoming visible reconciles to completed and the view starts once', async () => {
  const R = load('src/lib/agent-runtime/turn-recovery.ts');
  const registry = load('src/features/agent/generative-ui/state/registry.ts');
  const tab = fakeTab('hidden');
  try {
    let clock = 0;
    let originalSignal;
    const replays = [];
    const send = (signal) => { originalSignal = signal; return new Promise(() => {}); }; // the response never arrives
    const replay = async () => { replays.push(clock); return COMPLETED; };
    let settled = 0;
    const turn = R.settleAgentTurn({ send, replay, wake: (listener) => R.resyncSignals(listener, { intervalMs: 5 }), now: () => clock, minAgeMs: 15_000 })
      .then((response) => { settled += 1; return response; });

    clock = 60_000;           // the run finished on the server while the tab was in the background
    await wait(30);           // timers had every chance to fire: a hidden tab must not poll
    await flush();
    assert.equal(replays.length, 0, 'no request while the tab is hidden');
    assert.equal(settled, 0, 'still waiting');

    tab.show();
    tab.focus();              // visibilitychange and focus arrive together: one authoritative read, not two
    const response = await turn;
    assert.equal(response.status, 'completed');
    assert.equal(response.runId, 'run-1');
    assert.equal(replays.length, 1, 'exactly one reconcile read for the pair of events');
    assert.equal(originalSignal.aborted, true, 'the lost request is released');

    // The panel marks the eligible answer fresh exactly as it does for a normal response; the presentation key is stable.
    const scope = 'workspace:u1:w1';
    const presentations = new Set();
    const onAnswer = (answer) => {
      if (answer.runId && answer.result?.ui?.eligible) {
        registry.markFresh(scope, answer.runId);
        if (registry.isFresh(scope, answer.runId)) presentations.add(registry.presentationKey(scope, answer.runId));
      }
    };
    onAnswer(response);
    tab.hide(); tab.show(); tab.online(); // later wakes after settling change nothing
    await flush();
    onAnswer(response);       // a remount reading the same answer reuses the same key
    assert.equal(settled, 1, 'the turn settles once');
    assert.equal(replays.length, 1, 'wakes after settling are unsubscribed');
    assert.equal(presentations.size, 1, 'one presentation idempotency key for the run');
  } finally {
    tab.restore();
  }
});

test('a lost response (network error) while the run is still running waits, then settles on the next visible wake', async () => {
  const R = load('src/lib/agent-runtime/turn-recovery.ts');
  const tab = fakeTab('visible');
  try {
    let clock = 0;
    let next = RUNNING;
    let replays = 0;
    let rejectOriginal;
    const send = () => new Promise((_resolve, reject) => { rejectOriginal = reject; });
    const replay = async () => { replays += 1; return next; };
    let outcome = null;
    const turn = R.settleAgentTurn({ send, replay, wake: (listener) => R.resyncSignals(listener, { intervalMs: 60_000 }), now: () => clock, minAgeMs: 15_000, sleep: async () => { clock = 15_000; } })
      .then((value) => { outcome = { value }; }, (error) => { outcome = { error }; });
    await flush();
    tab.hide();
    rejectOriginal(new TypeError('Failed to fetch'));
    await flush();
    assert.equal(replays, 1, 'the lost response is checked against the server record once (after the safe age)');
    assert.equal(outcome, null, 'a run that is still running keeps the turn working, not failed');
    next = COMPLETED;
    clock = 90_000;
    tab.show();
    await turn;
    assert.equal(replays, 2);
    assert.equal(outcome.value.status, 'completed');
  } finally {
    tab.restore();
  }
});

test('a normal response settles directly; a real server error still fails; a lost response with no record fails truthfully', async () => {
  const R = load('src/lib/agent-runtime/turn-recovery.ts');
  const noWake = () => () => {};
  let replays = 0;
  const replay = async () => { replays += 1; return COMPLETED; };
  assert.deepEqual(await R.settleAgentTurn({ send: async () => COMPLETED, replay, wake: noWake }), COMPLETED);
  assert.equal(replays, 0, 'no extra request when the response arrives');

  const refusal = Object.assign(new Error('Ask Rafii something.'), { name: 'ApiError', status: 400, code: 'bad_request' });
  await assert.rejects(R.settleAgentTurn({ send: async () => { throw refusal; }, replay, wake: noWake }), /Ask Rafii something/);
  assert.equal(replays, 0, 'a server refusal is not resent');

  const lost = new TypeError('Failed to fetch');
  await assert.rejects(R.settleAgentTurn({ send: async () => { throw lost; }, replay: async () => { throw new TypeError('Failed to fetch'); }, wake: noWake, now: () => 20_000, minAgeMs: 15_000, sleep: async () => {} }),
    (error) => error === lost, 'when the record cannot be read either, the original error surfaces');
});

test('wakes before the safe age never resend (the original may not have opened its run yet)', async () => {
  const R = load('src/lib/agent-runtime/turn-recovery.ts');
  let fire;
  let replays = 0;
  let clock = 0;
  let resolveOriginal;
  const turn = R.settleAgentTurn({ send: () => new Promise((resolve) => { resolveOriginal = resolve; }), replay: async () => { replays += 1; return COMPLETED; },
    wake: (listener) => { fire = listener; return () => { fire = null; }; }, now: () => clock, minAgeMs: 15_000 });
  clock = 3_000;
  fire();
  await flush();
  assert.equal(replays, 0);
  resolveOriginal(COMPLETED);
  assert.equal((await turn).runId, 'run-1');
  assert.equal(fire, null, 'wake listeners are removed once settled');
});

test('the visible slow check is bounded and stops while hidden', async () => {
  const R = load('src/lib/agent-runtime/turn-recovery.ts');
  const tab = fakeTab('visible');
  try {
    let calls = 0;
    const stop = R.resyncSignals(() => { calls += 1; }, { intervalMs: 3, maxTicks: 2 });
    await wait(40);
    assert.equal(calls, 2, 'at most maxTicks slow checks');
    tab.hide();
    const before = calls;
    await wait(20);
    assert.equal(calls, before);
    stop();
    tab.show();
    assert.equal(calls, before, 'nothing fires after unsubscribe');
  } finally {
    tab.restore();
  }
});

test('the run observer reports a finished run so a pending turn can reconcile without waiting for the response', async () => {
  const R = load('src/lib/agent-runtime/turn-recovery.ts');
  const tab = fakeTab('hidden');
  try {
    let calls = 0;
    const stop = R.resyncSignals(() => { calls += 1; }, { intervalMs: 60_000 });
    R.noteRunEnded();
    assert.equal(calls, 1);
    stop();
    R.noteRunEnded();
    assert.equal(calls, 1);
  } finally {
    tab.restore();
  }
  const hook = read('src/lib/agent-runtime/use-thinking-state.ts');
  assert.match(hook, /noteRunEnded\(\)/, 'the existing event observer signals the end of the run');
});

test('the panel sends Agent Runtime turns through the recovery path with one idempotency key and still marks eligible answers fresh', () => {
  const chat = read('src/features/site-agent/chat.tsx');
  const send = chat.slice(chat.indexOf('const send = useCallback('), chat.indexOf('const continueFromView'));
  assert.match(send, /settleAgentTurn\(\{/);
  assert.match(send, /wake: resyncSignals/);
  assert.match(send, /const idempotencyKey = newKey\(\);/, 'the original request and its replay share one key');
  assert.match(send, /idempotencyKey,\n/);
  assert.match(send, /markFresh\(uiScope, response\.runId\)/);
});
