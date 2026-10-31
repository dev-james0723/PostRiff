/**
 * Note Garden synth: exhaustive orderings of requests, resume outcomes and stop/mute/close (decision D6).
 * Every sequence of up to 5 operations (at most 3 requests) runs against a fake AudioContext whose resume() calls the
 * test settles one by one, and the synth's invariants are checked after every step.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createSynth } from '../src/lib/music-game/synth.ts';

const NOTES = ['C4', 'D4', 'E4', 'F4'];
const HZ = { C4: 262, D4: 294, E4: 330, F4: 349 };
const FADE_END = 0.031;
const tone = (note) => [{ kind: 'tone', note, at: 0, seconds: 0.6 }];

/** Fake AudioContexts (any number) whose resume() calls stay pending until the test settles them. */
function fakeAudio() {
  const made = [];
  const resumes = []; // pending resume() calls across all contexts, oldest first
  const violations = [];
  const param = () => {
    const p = { value: 0 };
    const set = (v) => { p.value = v; return p; };
    Object.assign(p, { setValueAtTime: set, linearRampToValueAtTime: set, exponentialRampToValueAtTime: set, setTargetAtTime: set, cancelScheduledValues: () => p });
    return p;
  };
  const node = (extra = {}) => ({ connect: (n) => n, disconnect() {}, ...extra });
  const factory = () => {
    const ctx = {
      state: 'suspended',
      currentTime: 0,
      destination: node(),
      sources: [],
      resumeCalls: 0,
      closed: false,
      resume() {
        ctx.resumeCalls++;
        if (ctx.state === 'closed') return Promise.reject(new Error('closed'));
        return new Promise((resolve, reject) =>
          resumes.push({
            ctx,
            ok: () => { if (ctx.state !== 'closed') ctx.state = 'running'; resolve(); },
            fail: () => reject(new Error('resume failed'))
          })
        );
      },
      async suspend() { ctx.state = 'suspended'; },
      close() { ctx.closed = true; ctx.state = 'closed'; return Promise.resolve(); },
      createGain() { return node({ gain: param() }); },
      createBiquadFilter() { return node({ type: '', frequency: param(), Q: param() }); },
      createDynamicsCompressor() { return node({ threshold: param(), knee: param(), ratio: param(), attack: param(), release: param() }); },
      createOscillator() {
        if (ctx.closed) violations.push('source created on a closed context');
        const o = node({
          type: '', frequency: param(), stopAt: Infinity, listeners: [],
          addEventListener(type, fn) { if (type === 'ended') o.listeners.push(fn); },
          start() {}, stop(t = 0) { o.stopAt = t; }
        });
        ctx.sources.push(o);
        return o;
      }
    };
    made.push(ctx);
    return ctx;
  };
  const pendingOn = (ctx) => resumes.filter((r) => r.ctx === ctx).length;
  return { factory, made, resumes, violations, pendingOn };
}

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const noteOf = (o) => Object.keys(HZ).find((n) => HZ[n] === Math.round(o.frequency.value));
const allSources = (fake) => fake.made.flatMap((c) => c.sources);
const liveNotes = (fake) => new Set(allSources(fake).filter((o) => o.stopAt > FADE_END && noteOf(o)).map(noteOf));

async function runSequence(ops) {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  const seen = new Set();
  let latest = null; // { note, valid }
  let muted = false;
  let requests = 0;
  const step = async (op) => {
    if (op === 'req') {
      const note = NOTES[requests++];
      latest = { note, valid: !muted };
      synth.request(tone(note));
    } else if (op === 'stop') {
      synth.stop();
      if (latest) latest.valid = false;
    } else if (op === 'mute' || op === 'unmute') {
      muted = op === 'mute';
      synth.setMuted(muted);
      if (latest && muted) latest.valid = false;
    } else if (op === 'close') {
      synth.close();
      if (latest) latest.valid = false;
    } else {
      const pending = fake.resumes.shift();
      if (pending) pending[op === 'resolve' ? 'ok' : 'fail']();
    }
    await flush();
    const label = `${ops.join(' ')} @ ${op}`;
    // Only the latest still-valid request may ever schedule.
    for (const o of allSources(fake)) {
      const note = noteOf(o);
      if (!note || seen.has(note)) continue;
      seen.add(note);
      assert.ok(latest && latest.valid && note === latest.note, `${label}: stale request ${note} scheduled (latest ${JSON.stringify(latest)})`);
    }
    // One sound at a time.
    assert.ok(liveNotes(fake).size <= 1, `${label}: overlapping ${[...liveNotes(fake)]}`);
    // Single flight: never two resume() calls in flight on one context, so no stale failure can exist.
    for (const ctx of fake.made) assert.ok(fake.pendingOn(ctx) <= 1, `${label}: ${fake.pendingOn(ctx)} resumes in flight on one context`);
    assert.deepEqual(fake.violations, [], label);
    // close() stops every source and closes every context the synth made.
    if (op === 'close') {
      assert.equal(liveNotes(fake).size, 0, `${label}: sound after close`);
      assert.ok(fake.made.every((c) => c.closed), `${label}: a context was left open`);
    }
  };
  for (const op of ops) await step(op);
  // Liveness: whatever happened (including a failed resume), a fresh request after unmuting can still play.
  if (muted) await step('unmute');
  latest = { note: 'F4', valid: true };
  synth.request(tone('F4'));
  for (let i = 0; i < 4; i++) {
    for (const pending of fake.resumes.splice(0)) pending.ok();
    await flush();
  }
  assert.ok(liveNotes(fake).has('F4'), `${ops.join(' ')}: a later request could not produce sound`);
  synth.close();
  await flush();
  assert.equal(liveNotes(fake).size, 0);
}

function* sequences(maxLength) {
  const ops = ['req', 'stop', 'mute', 'unmute', 'close', 'resolve', 'reject'];
  function* grow(prefix) {
    yield prefix;
    if (prefix.length === maxLength) return;
    for (const op of ops) {
      if (op === 'req' && prefix.filter((p) => p === 'req').length === 3) continue;
      yield* grow([...prefix, op]);
    }
  }
  yield* grow(['req']);
}

test('every ordering of up to 5 steps keeps the synth invariants', async () => {
  let count = 0;
  for (const ops of sequences(5)) {
    await runSequence(ops);
    count++;
  }
  assert.ok(count > 2000, `ran ${count} orderings`);
});

test('A rejects while B is pending on the same context: one shared resume, B is not orphaned, a later request plays', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  synth.request(tone('C4'));
  synth.request(tone('D4'));
  await flush();
  assert.equal(fake.made.length, 1);
  assert.equal(fake.made[0].resumeCalls, 1, 'both requests share one resume()');
  fake.resumes.shift().fail();
  await flush();
  assert.equal(liveNotes(fake).size, 0, 'nothing plays on a context that could not resume');
  synth.request(tone('E4'));
  await flush();
  for (const pending of fake.resumes.splice(0)) pending.ok();
  await flush();
  assert.ok(liveNotes(fake).has('E4'), 'no permanent failure: a later request plays');
  synth.close();
  await flush();
  assert.ok(fake.made.every((c) => c.closed));
});
