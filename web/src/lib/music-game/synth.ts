/**
 * Note Garden synth (docs/music-game/DESIGN.md §9): soft "garden bell" tones and beat clicks made with Web Audio.
 * No audio files and no network. The AudioContext is created and resumed only from `unlock()`, which the UI calls
 * inside a tap or key handler, so nothing sounds before a child presses something. Sounds are scheduled on the audio
 * clock (no JS timers). Chain: voice -> schedule bus -> master gain (capped) -> limiter -> speakers.
 * Only one schedule sounds at a time: every new sound, stop, mute or close fades the previous bus out and stops its
 * oscillators, so replays, hints, answers and the next question never pile up. `request()` is the safe entry point
 * for the UI: it waits for the AudioContext to resume and schedules only if nothing newer (a sound, stop, mute or
 * close) happened while it waited.
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
/** Fade for superseded sound: quick enough to feel instant, slow enough not to click. */
const FADE = 0.025;
const SEMITONES: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

function frequency(note: string): number {
  const midi = 12 * (Number(note.slice(1)) + 1) + (SEMITONES[note[0]] ?? 0);
  return 440 * Math.pow(2, (midi - 69) / 12);
}

const masterLevel = (volume: string) => Math.min(MAX_MASTER_GAIN, VOLUME_GAIN[volume as SynthVolume] ?? VOLUME_GAIN.medium);

export type Synth = {
  /** Call from a user gesture. Resolves true when sound can play. */
  unlock(): Promise<boolean>;
  /**
   * Replaces whatever is playing with `events` (times in seconds from now), optionally led by a short feedback cue.
   * Resolves when the last note has ended, when a newer sound replaces it, or at once if silent.
   */
  play(events: SynthEvent[], options?: { delay?: number; cue?: 'correct' | 'try-again' }): Promise<void>;
  /** unlock() then play(), unless a newer sound, stop, mute or close happened while the context was resuming. */
  request(events: SynthEvent[], options?: { delay?: number; cue?: 'correct' | 'try-again' }): Promise<void>;
  /** Fades out and stops every queued or sounding note. */
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
  /** The one resume() in flight for the current context, shared by every caller (single flight). */
  let resuming: Promise<void> | null = null;
  /** The one schedule allowed to sound: its own bus into the master, and every oscillator it started. */
  let current: { bus: GainNode; sources: OscillatorNode[] } | null = null;
  let waiting: Array<() => void> = [];
  /** Bumped by every play, stop, mute and close; a request scheduled under an older value is stale. */
  let generation = 0;

  const running = () => !!ctx && !!master && !muted && ctx.state === 'running';

  function settleAll() {
    const list = waiting;
    waiting = [];
    for (const resolve of list) resolve();
  }

  function stopAll() {
    generation++;
    if (current && ctx) {
      const now = ctx.currentTime;
      const { bus, sources } = current;
      bus.gain.cancelScheduledValues(now);
      bus.gain.setValueAtTime(bus.gain.value, now);
      bus.gain.linearRampToValueAtTime(0, now + FADE);
      for (const osc of sources) {
        try {
          osc.stop(now + FADE + 0.005);
        } catch {
          // Already stopped.
        }
      }
    }
    current = null;
    settleAll();
  }

  function source(type: OscillatorType, hz: number, at: number, until: number, into: AudioNode): OscillatorNode {
    const osc = ctx!.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(hz, at);
    osc.connect(into);
    osc.start(at);
    osc.stop(until);
    current?.sources.push(osc);
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
    filter.connect(current!.bus);
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
    gain.connect(current!.bus);
    return source('sine', accent ? 1600 : 1200, at, at + 0.08, gain);
  }

  function schedule(events: SynthEvent[], delay: number, level: number): { last: OscillatorNode | null; end: number } {
    const start = ctx!.currentTime + LEAD_IN + delay;
    if (events.length === 0) return { last: null, end: start };
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

  /** Builds a context with its master gain and limiter. A device without working Web Audio just stays silent. */
  function build(): boolean {
    try {
      const c = options.createContext!();
      const m = c.createGain();
      m.gain.setValueAtTime(masterLevel(volume), c.currentTime);
      const limiter = c.createDynamicsCompressor();
      limiter.threshold.setValueAtTime(-12, c.currentTime);
      limiter.knee.setValueAtTime(0, c.currentTime);
      limiter.ratio.setValueAtTime(20, c.currentTime);
      limiter.attack.setValueAtTime(0.003, c.currentTime);
      limiter.release.setValueAtTime(0.1, c.currentTime);
      m.connect(limiter);
      limiter.connect(c.destination);
      ctx = c;
      master = m;
      return true;
    } catch {
      ctx = null;
      master = null;
      return false;
    }
  }

  /** Stops the current context's sound and closes it. Only ever applied to the current context. */
  function release() {
    stopAll();
    const dead = ctx;
    ctx = null;
    master = null;
    resuming = null;
    if (dead) void dead.close().catch(() => {});
  }

  /**
   * Single flight: at most one resume() per context, stored here and awaited by every caller. Its failure is handled
   * once, by that shared promise, and only if its context is still the current one and never came up. Nothing latches:
   * after a failure the next call builds a fresh context and tries again.
   */
  async function unlock(): Promise<boolean> {
    if (muted || !options.createContext) return false;
    if (!ctx && !build()) return false;
    const owned = ctx!;
    if (owned.state !== 'running') {
      if (!resuming) {
        const flight: Promise<void> = owned
          .resume()
          .then(
            () => undefined,
            () => {
              if (ctx === owned && owned.state !== 'running') release();
            }
          )
          .then(() => {
            if (resuming === flight) resuming = null;
          });
        resuming = flight;
      }
      await resuming;
    }
    if (ctx !== owned || !master || muted || owned.state !== 'running') return false;
    master.gain.cancelScheduledValues(owned.currentTime);
    master.gain.setValueAtTime(masterLevel(volume), owned.currentTime);
    return true;
  }

  function play(events: SynthEvent[], opts: { delay?: number; cue?: 'correct' | 'try-again' } = {}): Promise<void> {
    stopAll();
    if (!running() || (events.length === 0 && !opts.cue)) return Promise.resolve();
    const bus = ctx!.createGain();
    bus.connect(master!);
    current = { bus, sources: [] };
    // Feedback cue at 70% of voice level: a rising C-E-G for correct, one soft low G for "try again".
    const cue: SynthEvent[] =
      opts.cue === 'correct'
        ? ['C5', 'E5', 'G5'].map((note, i) => ({ kind: 'tone', note, at: i * 0.09, seconds: 0.09 }))
        : opts.cue === 'try-again'
          ? [{ kind: 'tone', note: 'G4', at: 0, seconds: 0.2 }]
          : [];
    const lead = schedule(cue, 0, 0.7);
    const main = schedule(events, opts.delay ?? 0, 1);
    const last = main.last && main.end >= lead.end ? main.last : (lead.last ?? main.last);
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
  }

  /** Waits for the shared resume, then schedules only if nothing newer (sound, stop, mute, close) happened meanwhile. */
  function request(events: SynthEvent[], opts: { delay?: number; cue?: 'correct' | 'try-again' } = {}): Promise<void> {
    const token = ++generation;
    return new Promise<void>((resolve) => {
      // Released at once by stop, mute, close or a newer sound, so a resume that never settles cannot hang a caller.
      waiting.push(resolve);
      void unlock().then((ok) => {
        if (!ok || token !== generation) {
          resolve();
          return;
        }
        waiting = waiting.filter((r) => r !== resolve);
        void play(events, opts).then(resolve);
      });
    });
  }

  return {
    unlock,
    play,
    request,
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
    close: release,
    ready() {
      return running();
    },
    supported() {
      return !!options.createContext;
    }
  };
}
