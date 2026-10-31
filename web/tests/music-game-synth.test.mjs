/** Note Garden synth (DESIGN §9): gesture-only AudioContext, capped master volume, limiter, mute that stops sound. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_MASTER_GAIN, VOLUME_GAIN, createSynth } from '../src/lib/music-game/synth.ts';

/** A minimal AudioContext stand-in. Records every value each gain node is asked to reach. */
function fakeAudio() {
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
      async resume() { ctx.resumed++; ctx.state = 'running'; },
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
        const o = node({ type: '', frequency: param(), started: false, stopped: false, onended: null, start() { o.started = true; }, stop() { o.stopped = true; } });
        ctx.sources.push(o);
        return o;
      }
    };
    made.push(ctx);
    return ctx;
  };
  return { factory, made };
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
    synth.play([{ kind: 'tone', note: 'G5', at: 0, seconds: 3 }, { kind: 'click', at: 0, accent: true }]);
    synth.feedback('correct');
    const master = fake.made[0].gains[0];
    assert.ok(master.log.length > 0);
    for (const v of master.log) assert.ok(v <= MAX_MASTER_GAIN, `${volume}: ${v}`);
    for (const g of fake.made[0].gains.slice(1)) for (const v of g.log) assert.ok(v <= 0.6 + 1e-9, 'voice peak 0.6');
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
  const last = sources.find((s) => typeof s.onended === 'function');
  last.onended();
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
  assert.ok(ctx.sources.every((s) => s.stopped));
  const count = ctx.sources.length;
  synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  assert.equal(ctx.sources.length, count, 'nothing new while muted');
  synth.setMuted(false);
  await synth.unlock();
  synth.play([{ kind: 'tone', note: 'C4', at: 0, seconds: 0.6 }]);
  assert.ok(ctx.sources.length > count);
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
