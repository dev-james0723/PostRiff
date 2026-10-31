import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_MASTER_GAIN, createSynth } from '../src/lib/music-game/synth.ts';

/** A minimal stand-in for AudioContext that records every gain value it is asked to reach. */
function fakeContextFactory() {
  const made = [];
  const gainValues = [];
  const param = (track = false) => {
    const set = (v) => { if (track) gainValues.push(v); p.value = v; return p; };
    const p = {
      value: 0,
      setValueAtTime: set,
      linearRampToValueAtTime: set,
      exponentialRampToValueAtTime: set,
      setTargetAtTime: set,
      cancelScheduledValues() { return p; }
    };
    return p;
  };
  const node = () => ({ connect: (n) => n, disconnect() {} });
  const factory = () => {
    const ctx = {
      state: 'suspended',
      currentTime: 0,
      destination: node(),
      oscillators: 0,
      resumed: 0,
      async resume() { ctx.resumed++; ctx.state = 'running'; },
      async suspend() { ctx.state = 'suspended'; },
      createGain() { return { ...node(), gain: param(true) }; },
      createBiquadFilter() { return { ...node(), type: '', frequency: param(), Q: param() }; },
      createOscillator() {
        ctx.oscillators++;
        return { ...node(), type: '', frequency: param(), start() {}, stop() {} };
      }
    };
    made.push(ctx);
    return ctx;
  };
  return { factory, made, gainValues };
}

test('no AudioContext exists until the child presses something (unlock)', async () => {
  const fake = fakeContextFactory();
  const synth = createSynth({ createContext: fake.factory });
  synth.play([{ note: 'C4', beats: 1 }]);
  assert.equal(fake.made.length, 0, 'play before unlock is silent and creates nothing');
  assert.equal(synth.ready(), false);
  await synth.unlock();
  assert.equal(fake.made.length, 1);
  assert.equal(fake.made[0].resumed, 1);
  assert.equal(synth.ready(), true);
  await synth.unlock();
  assert.equal(fake.made.length, 1, 'one context is reused');
});

test('notes are scheduled once unlocked, and every gain stays at or under the safe cap', async () => {
  const fake = fakeContextFactory();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  synth.play([{ note: 'C4', beats: 1 }, { note: 'G5', beats: 4 }]);
  assert.ok(fake.made[0].oscillators >= 2);
  assert.ok(MAX_MASTER_GAIN > 0 && MAX_MASTER_GAIN <= 0.5);
  for (const v of fake.gainValues) assert.ok(v <= MAX_MASTER_GAIN + 1e-9, `gain ${v} exceeds cap`);
});

test('muted synth never creates a context and plays nothing', async () => {
  const fake = fakeContextFactory();
  const synth = createSynth({ createContext: fake.factory, muted: true });
  await synth.unlock();
  synth.play([{ note: 'E4', beats: 1 }]);
  assert.equal(fake.made.length, 0);
});

test('muting after sound has started silences further notes', async () => {
  const fake = fakeContextFactory();
  const synth = createSynth({ createContext: fake.factory });
  await synth.unlock();
  synth.setMuted(true);
  const before = fake.made[0].oscillators;
  synth.play([{ note: 'E4', beats: 1 }]);
  assert.equal(fake.made[0].oscillators, before);
  synth.setMuted(false);
  await synth.unlock();
  synth.play([{ note: 'E4', beats: 1 }]);
  assert.ok(fake.made[0].oscillators > before);
});

test('a browser without Web Audio degrades to silence instead of throwing', async () => {
  const synth = createSynth({ createContext: () => { throw new Error('no audio'); } });
  await synth.unlock();
  synth.play([{ note: 'C4', beats: 1 }]);
  assert.equal(synth.ready(), false);
  const none = createSynth({ createContext: undefined });
  await none.unlock();
  none.play([{ note: 'C4', beats: 1 }]);
  assert.equal(none.ready(), false);
});
