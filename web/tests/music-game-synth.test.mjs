/** Note Garden synth (DESIGN §9): gesture-only AudioContext, capped master volume, limiter, mute that stops sound. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_MASTER_GAIN, VOLUME_GAIN, createSynth } from '../src/lib/music-game/synth.ts';

/** A minimal AudioContext stand-in. Records every value each gain node is asked to reach. */
function fakeAudio({ deferResume = false } = {}) {
  const pendingResumes = [];
  const made = [];
  const param = (log) => {
    const p = { value: 0 };
    const set = (v) => { log?.push(v); p.value = v; return p; };
    Object.assign(p, { setValueAtTime: set, linearRampToValueAtTime: set, exponentialRampToValueAtTime: set, setTargetAtTime: set, cancelScheduledValues: () => p });
    return p;
  };
  const node = (extra = {}) => ({ connections: [], connect(n) { this.connections.push(n); return n; }, disconnect() {}, ...extra });
  const factory = () => {
    const ctx = {
      state: 'suspended',
      currentTime: 0,
      gains: [],
      sources: [],
      compressors: [],
      closed: false,
      resumed: 0,
      destination: node(),
      resume() {
        ctx.resumed++;
        if (!deferResume) { ctx.state = 'running'; return Promise.resolve(); }
        // Deferred: the test decides when the browser finishes resuming.
        return new Promise((resolve, reject) =>
          pendingResumes.push({
            ok: () => { ctx.state = 'running'; resolve(); },
            fail: () => reject(new Error('resume failed'))
          })
        );
      },
      async suspend() { ctx.state = 'suspended'; },
      async close() { ctx.closed = true; ctx.state = 'closed'; },
      createGain() { const log = []; const g = node({ gain: param(log), log }); ctx.gains.push(g); return g; },
      createBiquadFilter() { return node({ type: '', frequency: param(), Q: param() }); },
      createDynamicsCompressor() {
        const c = node({ threshold: param(), knee: param(), ratio: param(), attack: param(), release: param() });
        ctx.compressors.push(c);
        return c;
      },
      createOscillator() {
        const o = node({
          type: '', frequency: param(), started: false, stopped: false, listeners: [],
          addEventListener(type, fn) { if (type === 'ended') o.listeners.push(fn); },
          end() { for (const fn of o.listeners.splice(0)) fn(); },
          start() { o.started = true; },
          // Records the latest requested stop time; a superseded schedule gets pulled forward to the fade.
          stop(t = 0) { o.stopped = true; o.stopAt = t; }
        });
        ctx.sources.push(o);
        return o;
      }
    };
    made.push(ctx);
    return ctx;
  };
  const flush = async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  };
  const finishResume = async () => {
    for (const pending of pendingResumes.splice(0)) pending.ok();
    await flush();
  };
  /** Settle one pending resume() (oldest first = index 0) by resolving or rejecting it. */
  const settleResume = async (index, how) => {
    const [pending] = pendingResumes.splice(index, 1);
    pending[how === 'reject' ? 'fail' : 'ok']();
    await flush();
  };
  return { factory, made, finishResume, settleResume, pendingResumes };
}

test('volume levels follow DESIGN: medium 0.20, soft 0.10, hard ceiling 0.25', () => {
  assert.equal(VOLUME_GAIN.medium, 0.2);
  assert.equal(VOLUME_GAIN.soft, 0.1);
  assert.equal(MAX_MASTER_GAIN, 0.25);
});

test('no AudioContext exists until unlock() (called from a tap); one context is reused', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  assert.equal(fake.made.length, 0, 'play before unlock is silent and creates nothing');
  assert.equal(await synth.unlock(), true);
  await synth.unlock();
  assert.equal(fake.made.length, 1);
  assert.equal(synth.ready(), true);
});

test('signal chain: master gain -> limiter -> speakers, with the DESIGN limiter settings', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  const ctx = fake.made[0];
  const [master] = ctx.gains;
  const [limiter] = ctx.compressors;
  assert.ok(master.connections.includes(limiter));
  assert.ok(limiter.connections.includes(ctx.destination));
  assert.deepEqual([limiter.threshold.value, limiter.knee.value, limiter.ratio.value, limiter.attack.value, limiter.release.value], [-12, 0, 20, 0.003, 0.1]);
});

test('the master gain never goes above the hard ceiling, whatever the volume', async () => {
  for (const volume of ['soft', 'medium', 'loud']) {
    const fake = fakeAudio();
    const synth = createSynth({ createContext: fake.factory, volume });
    await synth.unlock();
    synth.setVolume('medium');
    synth.play([{ kind: 'tone', note: 'G5', at: 0, seconds: 3 }, { kind: 'click', at: 0, accent: true }], { cue: 'correct' });
    const master = fake.made[0].gains[0];
    assert.ok(master.log.length > 0);
    for (const v of master.log) assert.ok(v <= MAX_MASTER_GAIN, `${volume}: ${v}`);
    // Voices peak at 0.6 and schedule buses sit at unity, all before the capped master.
    for (const g of fake.made[0].gains.slice(1)) for (const v of g.log) assert.ok(v <= 1, `${v}`);
  }
});

test('tones and clicks are scheduled on the audio clock and play() settles when the last one ends', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  let settled = false;
  const done = synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }, { kind: 'tone', note: 'G4', at: 1, seconds: 0.6 }, { kind: 'click', at: 0, accent: true }]).then(() => { settled = true; });
  const sources = fake.made[0].sources;
  assert.ok(sources.length >= 3 && sources.every((s) => s.started));
  await Promise.resolve();
  assert.equal(settled, false);
  for (const s of sources) s.end();
  await done;
  assert.equal(settled, true);
});

test('muted: no context is ever made and play() settles at once', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory, muted: true });
  assert.equal(await synth.unlock(), false);
  await synth.play([{ kind: 'tone', note: 'E4', at: 0, seconds: 0.6 }]);
  assert.equal(fake.made.length, 0);
});

test('muting mid-sound ramps the master to 0, stops queued sources and settles waiting play() calls', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  const pending = synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  synth.setMuted(true);
  await pending;
  const ctx = fake.made[0];
  assert.equal(ctx.gains[0].log.at(-1), 0);
  assert.ok(ctx.sources.every((s) => s.stopAt <= FADE_END), 'queued notes stopped at once');
  const count = ctx.sources.length;
  synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  assert.equal(ctx.sources.length, count, 'nothing new while muted');
  synth.setMuted(false);
  await synth.unlock();
  synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  assert.ok(ctx.sources.length > count);
});

const FADE_END = 0.031;
const tone = (note, at = 0, seconds = 0.6) => ({ kind: 'tone', note, at, seconds });

test('replay during playback: the earlier schedule is faded and stopped, only the new one stays active', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  const ctx = fake.made[0];
  let firstSettled = false;
  const first = synth.play([tone('C4'), tone('G4', 1), { kind: 'click', at: 0, accent: true }]).then(() => { firstSettled = true; });
  const firstSources = ctx.sources.slice();
  const firstBus = ctx.gains[1];
  synth.play([tone('C4'), tone('G4', 1)]);
  const secondSources = ctx.sources.slice(firstSources.length);
  await first;
  assert.equal(firstSettled, true, 'the superseded play() settles, so a first-play answer lock is released');
  assert.ok(firstSources.every((s) => s.stopAt <= FADE_END), 'old notes stop within the fade');
  assert.equal(firstBus.log.at(-1), 0, 'old bus fades to silence');
  assert.ok(secondSources.length > 0 && secondSources.every((s) => s.stopAt > 0.3), 'new notes keep their full length');
});

test('a feedback cue and the answer sound form one schedule, replaced by the next sound', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  const ctx = fake.made[0];
  synth.play([tone('E4')], { cue: 'correct', delay: 0.35 });
  const answer = ctx.sources.slice();
  assert.ok(answer.length >= 8, 'three cue notes plus the answer note, two partials each');
  synth.play([], { cue: 'try-again' });
  assert.ok(answer.every((s) => s.stopAt <= FADE_END));
  assert.ok(ctx.sources.length > answer.length, 'the try-again cue plays on its own');
});

test('question transition / leaving: stop() silences the active schedule and later sounds start clean', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  const ctx = fake.made[0];
  const pending = synth.play([tone('C5', 0, 2.5)]);
  synth.stop();
  await pending;
  assert.ok(ctx.sources.every((s) => s.stopAt <= FADE_END));
  const before = ctx.sources.length;
  synth.play([tone('D4')]);
  assert.ok(ctx.sources.slice(before).every((s) => s.stopAt > 0.3));
});

test('close() releases the context (route unmount)', async () => {
  const fake = fakeAudio();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  synth.close();
  assert.equal(fake.made[0].closed, true);
  assert.equal(synth.ready(), false);
});

test('a browser without Web Audio degrades to silence instead of throwing', async () => {
  const broken = createSynth({ createContext: () => { throw new Error('no audio'); } });
  assert.equal(await broken.unlock(), false);
  await broken.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  assert.equal(broken.supported(), true);
  const none = createSynth({ createContext: undefined });
  assert.equal(none.supported(), false);
  assert.equal(await none.unlock(), false);
});

/** Frequencies of every oscillator the synth scheduled (two partials per tone, one per click). */
const scheduledHz = (fake) => (fake.made[0]?.sources ?? []).map((o) => Math.round(o.frequency.value));
const C4 = 262; // fundamental of C4
const G5 = 784; // fundamental of G5

test('pending unlock: stop() before resume finishes means the stale request never schedules', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  synth.stop();
  await fake.finishResume();
  await a;
  assert.deepEqual(scheduledHz(fake), [], 'A never schedules');
  const b = synth.request([tone('G5')]);
  for (let i = 0; i < 5; i++) await Promise.resolve();
  assert.ok(scheduledHz(fake).includes(G5), 'a later request still plays');
  for (const s of fake.made[0].sources) s.end();
  await b;
});

test('pending unlock: a newer request replaces an older one; only the latest schedules', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  const b = synth.request([tone('G5')]);
  await fake.finishResume();
  await a;
  assert.ok(!scheduledHz(fake).includes(C4), 'A never schedules');
  assert.ok(scheduledHz(fake).includes(G5), 'B schedules');
  for (const s of fake.made[0].sources) s.end();
  await b;
});

test('pending unlock: a direct play() also invalidates an older pending request', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  synth.play([tone('G5')]); // not running yet: schedules nothing, but A is now stale
  await fake.finishResume();
  await a;
  assert.deepEqual(scheduledHz(fake), []);
});

test('pending unlock: mute then unmute before resume finishes still drops the muted-era request', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  synth.setMuted(true);
  synth.setMuted(false); // the child flips sound back on before the browser finished resuming
  await fake.finishResume();
  await a;
  assert.deepEqual(scheduledHz(fake), [], 'the muted-era request stays dead');
});

// Guard test: the 19decc01 code also passed this, but only because its unlock() hit a TypeError on the cleared master
// and fell into the catch. It pins the intended behaviour so a refactor of that path cannot start sound after unmount.
test('pending unlock: close() (unmount) before resume finishes means nothing schedules', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  synth.close();
  await fake.finishResume();
  await a;
  assert.deepEqual(scheduledHz(fake), []);
  assert.equal(synth.ready(), false);
});

test('single flight: two waiting requests share one resume(); only the newer plays and close() stops and closes it', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  const b = synth.request([tone('G5', 0, 2)]);
  await Promise.resolve();
  assert.equal(fake.pendingResumes.length, 1, 'one resume() for both requests');
  await fake.settleResume(0, 'resolve');
  await a;
  const ctx = fake.made[0];
  const playing = ctx.sources.slice();
  assert.ok(scheduledHz(fake).includes(G5) && !scheduledHz(fake).includes(C4), 'only the newer request plays');
  assert.equal(synth.ready(), true);
  synth.close();
  assert.ok(playing.every((s) => s.stopAt <= FADE_END), 'close() stops every live source');
  assert.equal(ctx.closed, true, 'close() closes the live context');
  await b;
});

test('failed resume: the owned context is closed, waiting requests settle, and a later request builds a fresh context', async () => {
  const fake = fakeAudio({ deferResume: true });
  const synth = createSynth({ createContext: fake.factory });
  const a = synth.request([tone('C4')]);
  await fake.settleResume(0, 'reject');
  await a;
  assert.deepEqual(scheduledHz(fake), []);
  assert.equal(fake.made[0].closed, true, 'the context it owned is released, not orphaned');
  const b = synth.request([tone('G5')]);
  await Promise.resolve();
  assert.equal(fake.made.length, 2, 'no permanent failure latch: a fresh context is built');
  await fake.settleResume(0, 'resolve');
  assert.ok(fake.made[1].sources.length > 0, 'and it plays');
  for (const s of fake.made[1].sources) s.end();
  await b;
});
