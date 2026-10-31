/**
 * Note Garden synth (docs/music-game/DESIGN.md §9): soft "garden bell" tones and beat clicks made with Web Audio.
 * No audio files and no network. The AudioContext is created and resumed only from `unlock()`, which the UI calls
 * inside a tap or key handler, so nothing sounds before a child presses something. Sounds are scheduled on the audio
 * clock (no JS timers). Chain: voice -> master gain (capped) -> limiter -> speakers.
 * No imports, so node's test runner loads it directly (`web/tests/music-game-synth.test.mjs`).
 */

export type SynthEvent = { kind: 'tone'; note: string; at: number; seconds: number } | { kind: 'click'; at: number; accent: boolean };
export type SynthVolume = 'soft' | 'medium';

/** Hearing safety: the master bus can never exceed this, whatever the setting. There is no "loud". */
export const MAX_MASTER_GAIN = 0.25;
export const VOLUME_GAIN: Record<SynthVolume, number> = { soft: 0.1, medium: 0.2 };
const VOICE_PEAK = 0.6;
const ATTACK = 0.012;
const DECAY = 0.15;
const SUSTAIN = 0.55;
const RELEASE = 0.28;
const LEAD_IN = 0.05;
const SEMITONES: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

function frequency(note: string): number {
  const midi = 12 * (Number(note.slice(1)) + 1) + (SEMITONES[note[0]] ?? 0);
  return 440 * Math.pow(2, (midi - 69) / 12);
}

const masterLevel = (volume: string) => Math.min(MAX_MASTER_GAIN, VOLUME_GAIN[volume as SynthVolume] ?? VOLUME_GAIN.medium);

export type Synth = {
  /** Call from a user gesture. Resolves true when sound can play. */
  unlock(): Promise<boolean>;
  /** Schedules events (times in seconds from now). Resolves when the last one has ended, or at once if silent. */
  play(events: SynthEvent[], options?: { delay?: number; level?: number }): Promise<void>;
  feedback(kind: 'correct' | 'try-again'): void;
  /** Stops every queued or sounding note. */
  stop(): void;
  setMuted(muted: boolean): void;
  setVolume(volume: SynthVolume): void;
  close(): void;
  ready(): boolean;
  /** False when this browser has no Web Audio at all. */
  supported(): boolean;
};

export function createSynth(options: { createContext?: () => AudioContext; muted?: boolean; volume?: string }): Synth {
  let ctx: AudioContext | null = null;
  let master: GainNode | null = null;
  let muted = options.muted === true;
  let volume = options.volume ?? 'medium';
  let failed = false;
  let busyUntil = 0;
  const live = new Set<OscillatorNode>();
  let waiting: Array<() => void> = [];

  const running = () => !!ctx && !!master && !muted && ctx.state === 'running';

  function settleAll() {
    const list = waiting;
    waiting = [];
    for (const resolve of list) resolve();
  }

  function stopAll() {
    for (const osc of live) {
      try {
        osc.stop();
      } catch {
        // Already stopped.
      }
    }
    live.clear();
    busyUntil = 0;
    settleAll();
  }

  function source(type: OscillatorType, hz: number, at: number, until: number, into: AudioNode): OscillatorNode {
    const osc = ctx!.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(hz, at);
    osc.connect(into);
    osc.start(at);
    osc.stop(until);
    live.add(osc);
    osc.addEventListener('ended', () => live.delete(osc), { once: true });
    return osc;
  }

  function bell(at: number, note: string, seconds: number, level: number): OscillatorNode {
    const c = ctx!;
    const hz = frequency(note);
    const peak = VOICE_PEAK * level;
    const held = Math.max(ATTACK + DECAY, seconds);
    const voice = c.createGain();
    const filter = c.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(2500, at);
    filter.Q.setValueAtTime(0.7, at);
    // Ramps only (never jumps) so there are no clicks.
    voice.gain.setValueAtTime(0, at);
    voice.gain.linearRampToValueAtTime(peak, at + ATTACK);
    voice.gain.linearRampToValueAtTime(peak * SUSTAIN, at + ATTACK + DECAY);
    voice.gain.setValueAtTime(peak * SUSTAIN, at + held);
    voice.gain.linearRampToValueAtTime(0, at + held + RELEASE);
    voice.connect(filter);
    filter.connect(master!);
    const end = at + held + RELEASE + 0.02;
    const overtone = c.createGain();
    overtone.gain.setValueAtTime(0.15, at);
    overtone.connect(voice);
    source('sine', hz * 2, at, end, overtone);
    return source('triangle', hz, at, end, voice);
  }

  function click(at: number, accent: boolean): OscillatorNode {
    const c = ctx!;
    const gain = c.createGain();
    gain.gain.setValueAtTime(0, at);
    gain.gain.linearRampToValueAtTime(0.25, at + 0.002);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.06);
    gain.connect(master!);
    return source('sine', accent ? 1600 : 1200, at, at + 0.08, gain);
  }

  function schedule(events: SynthEvent[], delay: number, level: number): { last: OscillatorNode | null; end: number } {
    const start = ctx!.currentTime + LEAD_IN + delay;
    let last: OscillatorNode | null = null;
    let end = start;
    for (const event of events) {
      const at = start + event.at;
      const osc = event.kind === 'tone' ? bell(at, event.note, event.seconds, level) : click(at, event.accent);
      const stopsAt = event.kind === 'tone' ? at + Math.max(ATTACK + DECAY, event.seconds) + RELEASE : at + 0.08;
      if (stopsAt >= end) {
        end = stopsAt;
        last = osc;
      }
    }
    return { last, end };
  }

  return {
    async unlock() {
      if (muted || failed || !options.createContext) return false;
      try {
        if (!ctx) {
          ctx = options.createContext();
          master = ctx.createGain();
          master.gain.setValueAtTime(masterLevel(volume), ctx.currentTime);
          const limiter = ctx.createDynamicsCompressor();
          limiter.threshold.setValueAtTime(-12, ctx.currentTime);
          limiter.knee.setValueAtTime(0, ctx.currentTime);
          limiter.ratio.setValueAtTime(20, ctx.currentTime);
          limiter.attack.setValueAtTime(0.003, ctx.currentTime);
          limiter.release.setValueAtTime(0.1, ctx.currentTime);
          master.connect(limiter);
          limiter.connect(ctx.destination);
        }
        if (ctx.state !== 'running') await ctx.resume();
        master!.gain.cancelScheduledValues(ctx.currentTime);
        master!.gain.setValueAtTime(masterLevel(volume), ctx.currentTime);
        return ctx.state === 'running';
      } catch {
        failed = true;
        ctx = null;
        master = null;
        return false;
      }
    },
    play(events, opts = {}) {
      if (!running() || events.length === 0) return Promise.resolve();
      const { last, end } = schedule(events, opts.delay ?? 0, opts.level ?? 1);
      busyUntil = Math.max(busyUntil, end);
      if (!last) return Promise.resolve();
      return new Promise<void>((resolve) => {
        waiting.push(resolve);
        last.addEventListener(
          'ended',
          () => {
            waiting = waiting.filter((r) => r !== resolve);
            resolve();
          },
          { once: true }
        );
      });
    },
    feedback(kind) {
      // Optional cue at 70% of voice level, skipped while the question's own sound is playing.
      if (!running() || ctx!.currentTime < busyUntil) return;
      const events: SynthEvent[] =
        kind === 'correct'
          ? ['C5', 'E5', 'G5'].map((note, i) => ({ kind: 'tone', note, at: i * 0.09, seconds: 0.09 }))
          : [{ kind: 'tone', note: 'G4', at: 0, seconds: 0.2 }];
      schedule(events, 0, 0.7);
    },
    stop: stopAll,
    setMuted(next) {
      muted = next;
      if (!ctx || !master) return;
      if (muted) {
        const now = ctx.currentTime;
        master.gain.cancelScheduledValues(now);
        master.gain.setValueAtTime(master.gain.value, now);
        master.gain.linearRampToValueAtTime(0, now + 0.03);
        stopAll();
      }
    },
    setVolume(next) {
      volume = next;
      if (ctx && master && !muted) master.gain.setValueAtTime(masterLevel(volume), ctx.currentTime);
    },
    close() {
      stopAll();
      if (ctx) void ctx.close().catch(() => {});
      ctx = null;
      master = null;
    },
    ready() {
      return running();
    },
    supported() {
      return !!options.createContext;
    }
  };
}
