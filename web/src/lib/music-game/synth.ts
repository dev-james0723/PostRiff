/**
 * Note Garden synth: soft piano-like tones made with Web Audio, no audio files and no network.
 * The AudioContext is created and resumed only from `unlock()`, which the UI calls inside a click or key handler,
 * so browsers' autoplay rules are respected and nothing sounds before a child presses something.
 * Notes are scheduled on the audio clock (no JS timers). No imports, so node's test runner loads it directly.
 */

export type SynthTone = { note: string; beats: number };

/** Loudest the master bus may ever be. Children often wear headphones. */
export const MAX_MASTER_GAIN = 0.3;
const BEAT_SECONDS = 0.6;
const GAP_SECONDS = 0.12;
const SEMITONES: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

function frequency(note: string): number {
  const midi = 12 * (Number(note.slice(1)) + 1) + (SEMITONES[note[0]] ?? 0);
  return 440 * Math.pow(2, (midi - 69) / 12);
}

export type Synth = {
  unlock(): Promise<void>;
  play(tones: SynthTone[]): void;
  setMuted(muted: boolean): void;
  ready(): boolean;
};

export function createSynth(options: { createContext?: () => AudioContext; muted?: boolean }): Synth {
  let ctx: AudioContext | null = null;
  let master: GainNode | null = null;
  let muted = options.muted === true;
  let failed = false;

  function strike(at: number, hz: number, seconds: number) {
    if (!ctx || !master) return;
    // Two partials through a gentle low-pass: a quick hammer-like attack, then a decay toward a quiet sustain.
    const voice = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(Math.min(4000, hz * 6), at);
    filter.Q.setValueAtTime(0.0001, at);
    const peak = 0.28;
    const release = 0.25;
    voice.gain.setValueAtTime(0.0001, at);
    voice.gain.linearRampToValueAtTime(peak, at + 0.008);
    voice.gain.exponentialRampToValueAtTime(peak * 0.35, at + 0.3);
    voice.gain.setValueAtTime(peak * 0.35, at + Math.max(0.3, seconds));
    voice.gain.exponentialRampToValueAtTime(0.0001, at + Math.max(0.3, seconds) + release);
    voice.connect(filter);
    filter.connect(master);
    for (const [type, multiple, level] of [['triangle', 1, 1], ['sine', 2, 0.25]] as const) {
      const osc = ctx.createOscillator();
      const partial = ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(hz * multiple, at);
      partial.gain.setValueAtTime(level * peak, at);
      osc.connect(partial);
      partial.connect(voice);
      osc.start(at);
      osc.stop(at + Math.max(0.3, seconds) + release + 0.05);
    }
  }

  return {
    async unlock() {
      if (muted || failed || !options.createContext) return;
      try {
        if (!ctx) {
          ctx = options.createContext();
          master = ctx.createGain();
          master.gain.setValueAtTime(MAX_MASTER_GAIN, ctx.currentTime);
          master.connect(ctx.destination);
        }
        if (ctx.state !== 'running') await ctx.resume();
      } catch {
        failed = true;
        ctx = null;
        master = null;
      }
    },
    play(tones) {
      if (muted || !ctx || !master || ctx.state !== 'running') return;
      let at = ctx.currentTime + 0.05;
      for (const tone of tones) {
        const seconds = tone.beats * BEAT_SECONDS;
        strike(at, frequency(tone.note), seconds - GAP_SECONDS);
        at += seconds;
      }
    },
    setMuted(next) {
      muted = next;
      if (!ctx) return;
      if (muted) void ctx.suspend().catch(() => {});
    },
    ready() {
      return !!ctx && !muted && ctx.state === 'running';
    }
  };
}
