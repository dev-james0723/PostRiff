/**
 * Voice Mode's transcript and hang-up rules (web/src/lib/agent-runtime/voice-transcript.ts), loaded from the TypeScript
 * source: "Stop talking" drops the rest of the stopped reply and marks its line; the person speaking or a new result
 * being said ends the stop; a delegation takes exactly its own words; a goodbye ends the call once Rafii has answered
 * it and gone quiet, at most 10 s later.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');

/** CommonJS from a .ts source; relative .ts and .json imports resolve next to it (JSON as a default import). */
function load(file, cache = new Map()) {
  const filename = path.resolve(WEB, file);
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = new Module(filename, module);
  mod.filename = filename;
  cache.set(filename, mod);
  const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    fileName: filename
  });
  const local = (request) => {
    if (!request.startsWith('.')) return require(request);
    const base = path.resolve(path.dirname(filename), request);
    const found = [base, `${base}.ts`].find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
    if (!found) throw new Error(`Cannot resolve ${request} from ${filename}`);
    return found.endsWith('.json') ? JSON.parse(fs.readFileSync(found, 'utf8')) : load(found, cache);
  };
  new Function('require', 'module', 'exports', outputText)(local, mod, mod.exports);
  return mod.exports;
}

const T = load('src/lib/agent-runtime/voice-transcript.ts');

function ids() {
  let n = 0;
  return () => {
    n += 1;
    return { id: `line-${n}`, seq: n };
  };
}

const user = (delta, startMs, endMs = startMs + 300) => ({ type: 'delta', role: 'user', delta, startMs, endMs });
const rafii = (delta, startMs, endMs = startMs + 300) => ({ type: 'delta', role: 'assistant', delta, startMs, endMs });

/** Apply events in order; returns the last step and every closed line. */
function run(events, state = { lines: [], stopped: false }, next = ids()) {
  const closed = [];
  let step = { state, closed: [], resumed: false, dropped: false };
  for (const event of events) {
    step = T.applyTranscript(step.state, event, next);
    closed.push(...step.closed);
  }
  return { ...step, allClosed: closed, next };
}

test('"Stop talking" cuts the reply off: its line ends there, marked stopped, and the rest of it is dropped', () => {
  const before = run([user('Tell me about the launch', 0, 900), rafii('The launch is', 1000, 1400)]);
  assert.deepEqual(before.allClosed.map((l) => [l.role, l.text]), [['user', 'Tell me about the launch']], 'the person\'s line ends when Rafii answers');

  const stop = T.applyTranscript(before.state, { type: 'stop', inFlight: true }, before.next);
  assert.equal(stop.state.stopped, true);
  const cut = stop.state.lines.at(-1);
  assert.deepEqual([cut.role, cut.text, cut.final, cut.stopped], ['assistant', 'The launch is', true, true]);
  assert.deepEqual(stop.closed, [cut], 'the stopped line is stored as it was heard');
  assert.equal(before.state.lines.at(-1).stopped, undefined, 'the earlier state is not mutated');

  // GPT-Live has no cancel: the stopped reply keeps streaming; none of it is shown, stored or counted.
  for (const delta of [' on Thursday', ' at six', ' and it includes']) {
    const dropped = T.applyTranscript(stop.state, rafii(delta, 1500), before.next);
    assert.equal(dropped.dropped, true);
    assert.equal(dropped.state, stop.state, 'nothing changes while the reply is stopped');
    assert.deepEqual(dropped.closed, []);
  }
});

test('the person speaking again ends the stop; spaces alone do not', () => {
  const stopped = run([user('Explain the plan', 0), rafii('Sure, first', 500), { type: 'stop', inFlight: true }]);
  const blank = T.applyTranscript(stopped.state, user('  ', 2000), stopped.next);
  assert.equal(blank.state.stopped, true, 'an empty delta is not speech');
  assert.equal(blank.resumed, false);
  assert.equal(T.applyTranscript(blank.state, rafii(' second', 2100), stopped.next).dropped, true);

  const spoke = T.applyTranscript(blank.state, user(' wait', 2200), stopped.next);
  assert.equal(spoke.resumed, true);
  assert.equal(spoke.state.stopped, false);
  assert.equal(spoke.state.lines.at(-1).role, 'user');

  // Rafii's next words are a new line; the stopped one keeps its marker and its words.
  const next = T.applyTranscript(spoke.state, rafii('Okay, go ahead.', 2600), stopped.next);
  assert.equal(next.dropped, false);
  const lines = next.state.lines;
  assert.deepEqual(lines.map((l) => [l.role, l.text.trim(), Boolean(l.stopped)]), [
    ['user', 'Explain the plan', false],
    ['assistant', 'Sure, first', true],
    ['user', 'wait', false],
    ['assistant', 'Okay, go ahead.', false]
  ]);
});

test('a new result being said ends the stop, and its words start a new line', () => {
  const stopped = run([user('What is scheduled?', 0), rafii('Let me', 500), { type: 'stop', inFlight: true }]);
  const resumed = T.applyTranscript(stopped.state, { type: 'resume' }, stopped.next);
  assert.equal(resumed.resumed, true);
  assert.equal(resumed.state.stopped, false);
  assert.equal(resumed.state.lines, stopped.state.lines, 'resuming changes no line');
  const said = T.applyTranscript(resumed.state, rafii('Two posts are scheduled.', 900), stopped.next);
  assert.equal(said.state.lines.length, 3);
  assert.deepEqual(said.state.lines.at(-1), { id: 'line-3', seq: 3, role: 'assistant', text: 'Two posts are scheduled.', final: false, startMs: 900, endMs: 1200 });

  // Resuming when nothing was stopped is a no-op.
  const idle = T.applyTranscript(said.state, { type: 'resume' }, stopped.next);
  assert.equal(idle.resumed, false);
  assert.equal(idle.state, said.state);
});

test('stopping when Rafii had already finished marks nothing, but still drops a late reply', () => {
  const quiet = run([user('Thanks', 0), rafii('You are welcome.', 400)]);
  const stop = T.applyTranscript(quiet.state, { type: 'stop', inFlight: false }, quiet.next);
  assert.equal(stop.state.stopped, true);
  assert.equal(stop.state.lines.at(-1).stopped, undefined);
  assert.deepEqual(stop.closed, []);
  assert.equal(T.applyTranscript(stop.state, rafii('Anything else?', 5000), quiet.next).dropped, true);

  // The person's own open line is never marked stopped.
  const talking = run([user('Hold on', 0)]);
  const stopTalking = T.applyTranscript(talking.state, { type: 'stop', inFlight: true }, talking.next);
  assert.equal(stopTalking.state.lines.at(-1).stopped, undefined);
  assert.equal(stopTalking.state.lines.at(-1).final, false);
});

test('words join their line within an utterance gap, a pause starts a new one, and the list is capped', () => {
  const merged = run([user('Open', 0, 200), user(' the calendar', 300, 600)]);
  assert.deepEqual(merged.state.lines.map((l) => l.text), ['Open the calendar']);
  const paused = run([user('Open', 0, 200), user(' later', 200 + T.UTTERANCE_GAP_MS, 1600)]);
  assert.deepEqual(paused.state.lines.map((l) => [l.text, l.final]), [['Open', true], ['later', false]]);
  assert.deepEqual(paused.allClosed.map((l) => l.text), ['Open']);

  const next = ids();
  let state = { lines: [], stopped: false };
  for (let i = 0; i < 70; i += 1) state = T.applyTranscript(state, i % 2 ? rafii(`r${i}`, i * 10) : user(`u${i}`, i * 10), next, { maxLines: 60 }).state;
  assert.equal(state.lines.length, 60);
  assert.equal(state.lines.at(-1).seq, 70, 'sequence numbers keep counting past the cap');
});

test('a delegation takes exactly the words said since the last one, and closes the open line', () => {
  const heard = run([user('Write a post', 0), rafii('Sure', 400), user('about the recital', 1000)]);
  const first = T.takeRequest(heard.state.lines, 0);
  assert.equal(first.request, 'Write a post about the recital');
  assert.equal(first.lastSeq, 3);
  assert.deepEqual(first.closed.map((l) => [l.text, l.final]), [['about the recital', true]]);
  assert.equal(first.lines.at(-1).final, true);

  const later = run([user(' and add hashtags', 5000)], { lines: first.lines, stopped: false }, heard.next);
  const second = T.takeRequest(later.state.lines, first.lastSeq);
  assert.equal(second.request, 'and add hashtags');

  const none = T.takeRequest(first.lines, first.lastSeq);
  assert.equal(none.request, '');
  assert.equal(none.lines, first.lines, 'nothing open: the lines are returned as they were');
  assert.equal(T.lastUserLine(later.state.lines).text.trim(), 'and add hashtags');
  assert.equal(T.lastUserLine(heard.state.lines.slice(0, 2)), null, 'Rafii spoke last');
});

test('after a goodbye the call ends once Rafii has answered and gone quiet, and at most 10 s later', () => {
  const at = 100_000;
  // Nothing said yet: waits for the reply (up to the limit).
  assert.equal(T.hangUpDue({ at, replied: false, lastSoundAt: 0 }, at + 3_000), false);
  assert.equal(T.hangUpDue({ at, replied: false, lastSoundAt: 0 }, at + T.HANG_UP_MAX_MS - 1), false);
  assert.equal(T.hangUpDue({ at, replied: false, lastSoundAt: 0 }, at + T.HANG_UP_MAX_MS), true, 'a reply that never comes still ends the call');
  // Rafii said goodbye: ends after about 1.2 s of quiet.
  const replied = { at, replied: true, lastSoundAt: at + 1_500 };
  assert.equal(T.hangUpDue(replied, at + 1_500 + T.HANG_UP_QUIET_MS - 1), false);
  assert.equal(T.hangUpDue(replied, at + 1_500 + T.HANG_UP_QUIET_MS), true);
  // Still speaking keeps it on, until the limit.
  assert.equal(T.hangUpDue({ at, replied: true, lastSoundAt: at + 9_000 }, at + 9_500), false);
  assert.equal(T.hangUpDue({ at, replied: true, lastSoundAt: at + 9_900 }, at + 10_000), true);
  // Quiet is counted from the goodbye at the earliest (older sound doesn't count).
  assert.equal(T.hangUpDue({ at, replied: true, lastSoundAt: at - 5_000 }, at + 500), false);
  assert.equal(T.HANG_UP_QUIET_MS, 1200);
  assert.equal(T.HANG_UP_MAX_MS, 10_000);
});
